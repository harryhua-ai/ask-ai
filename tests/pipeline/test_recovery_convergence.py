"""E3/E4/E5 崩溃收敛自动化回归(阶段⑩)。

Discovery 实验证明:任一点位中断后,source 级重放(全新 pipeline 重跑同一
文档集)收敛到 账本==向量、零重复 chunk。本文件把三个击杀点固化为确定性回归:
"kill" = 第一个 pipeline 实例在检查点被弃置(半途状态留在真实 PG 账本与
fake 向量库),第二个 pipeline 全新重放。

- E3:fetch 后未灌入即中断 → 重放全量补齐;
- E4:向量已写、账本未写(W1)→ 重放覆盖写同 UUID + 账本补齐;
- E5:批内部分账本提交(1/N)→ 重放补齐。

断言:documents 账本行数 == 向量对象数;向量 UUID 全局唯一(零重复)。
"""

import os
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from backend.config import load_settings
from backend.connectors.base import RawDocument
from backend.db.models import Document
from backend.db.session import get_engine, get_session_factory, init_db
from backend.pipeline.ingest import IngestionPipeline

pytestmark = pytest.mark.asyncio(loop_scope="session")

N_DOCS = 6


class _Embed:
    dimension = 8

    def embed(self, texts):
        return [[0.1] * self.dimension for _ in texts]


class _FakeWeaviate:
    """以确定性 UUID 为键的向量库替身:记录对象,可断言唯一性。"""

    def __init__(self):
        self.objects: dict[str, dict] = {}

    def make_client(self):
        store = self.objects
        client = MagicMock()
        client.collections.exists.return_value = True
        collection = MagicMock()
        collection.name = "RecoveryConv"

        result = MagicMock()
        result.errors = {}
        collection.data.insert_many.side_effect = lambda objs: (
            store.update({o.uuid: {"props": o.properties, "vector": o.vector} for o in objs})
            or result
        )
        collection.data.insert.side_effect = lambda properties=None, vector=None, uuid=None: (
            store.update({uuid: {"props": properties, "vector": vector}})
        )
        collection.data.replace.side_effect = lambda properties=None, vector=None, uuid=None: (
            store.update({uuid: {"props": properties, "vector": vector}})
        )
        client.collections.get.return_value = collection
        return client


def _docs(gen: str = "a"):
    docs = []
    for i in range(N_DOCS):
        sid = f"conv-src/default/doc{i:02d}.md"
        content = f"# doc {i} gen{gen}\n\n" + "paragraph content. " * 120
        docs.append(
            RawDocument(
                source_id=sid,
                source_type="conv",
                product="conv",
                title=f"doc{i}",
                content=content,
                url=f"https://conv.local/{i}",
                metadata={"path": f"doc{i:02d}.md"},
                content_hash=__import__("hashlib").sha256(f"{sid}|{gen}".encode()).hexdigest(),
                branch="default",
            )
        )
    return docs


class _Abort(Exception):
    """受控中断:模拟 runner 在检查点被 kill。"""


@pytest_asyncio.fixture(loop_scope="session")
async def _env():
    dsn = os.environ.get("TEST_DATABASE_URL", load_settings().postgres_dsn)
    engine = get_engine(dsn)
    await init_db(engine)
    factory = get_session_factory(engine)
    async with factory() as session:
        await session.execute(delete(Document).where(Document.source_id.like("conv-src/%")))
        await session.commit()
    return factory, engine


async def _ledger(factory):
    async with factory() as session:
        count = (
            await session.execute(
                select(func.count())
                .select_from(Document)
                .where(Document.source_id.like("conv-src/%"))
            )
        ).scalar()
        rows = (
            await session.execute(
                select(Document.source_id, Document.chunk_count).where(
                    Document.source_id.like("conv-src/%")
                )
            )
        ).all()
    return int(count), dict(rows)


async def _run_pipeline(store: _FakeWeaviate, factory, docs, abort_after=None):
    """一次 pipeline 运行;abort_after=(phase, n) 在指定检查点抛 _Abort 模拟 kill。

    phase: "before"(未写任何东西) / "vector"(向量写完、账本未写) /
    "ledger"(第 n 个文档账本提交后)。
    """
    sync_factory = None
    if abort_after is None or abort_after[0] in ("vector", "ledger"):
        from backend.db.session import get_sync_session_factory

        sync_factory = get_sync_session_factory(os.environ["TEST_DATABASE_URL"])
    pipeline = IngestionPipeline(
        _Embed(), store.make_client(), class_name="RecoveryConv", session_factory=sync_factory
    )
    orig_upsert = IngestionPipeline._upsert_postgres

    if abort_after is None:
        pipeline.ingest_all(docs)
        return

    phase, n = abort_after
    if phase == "before":
        raise _Abort

    if phase == "vector":
        # 账本 upsert 前被杀:让首个 upsert 直接弃置
        def upsert_abort(self, doc, chunk_count):
            raise _Abort

        IngestionPipeline._upsert_postgres = upsert_abort
        try:
            pipeline.ingest_all(docs)
        finally:
            IngestionPipeline._upsert_postgres = orig_upsert
        return

    # ledger:逐 doc 提交,第 n 个提交后弃置
    committed = {"i": 0}

    def upsert_count(self, doc, chunk_count):
        orig_upsert(self, doc, chunk_count)
        committed["i"] += 1
        if committed["i"] >= n:
            raise _Abort

    IngestionPipeline._upsert_postgres = upsert_count
    try:
        pipeline.ingest_all(docs)
    finally:
        IngestionPipeline._upsert_postgres = orig_upsert


@pytest.mark.parametrize(
    "abort_after",
    [
        None,  # E3 前置基线:完整跑(无中断)
        ("before", 0),  # E3:fetch 后未灌入
        ("vector", 0),  # E4:向量已写/账本未写(W1/F13)
        ("ledger", 1),  # E5:批内部分账本提交(1/6)
    ],
)
async def test_crash_then_replay_converges(_env, abort_after):
    factory, engine = _env
    store = _FakeWeaviate()
    docs = _docs("a")

    # 第一轮:在指定检查点中断(None = 完整跑完的基线)
    if abort_after is not None:
        if abort_after[0] == "before":
            with pytest.raises(_Abort):
                await _run_pipeline(store, factory, docs, abort_after=abort_after)
        else:
            try:
                await _run_pipeline(store, factory, docs, abort_after=abort_after)
            except _Abort:
                pass

    # 第二轮:全新 pipeline 源级重放(恢复语义)
    await _run_pipeline(store, factory, docs, abort_after=None)

    # 收敛断言:账本 == 向量,零重复
    count, rows = await _ledger(factory)
    assert count == N_DOCS, f"账本行数 {count} != {N_DOCS}"
    assert len(rows) == N_DOCS
    uuids = list(store.objects.keys())
    assert len(uuids) >= N_DOCS  # 每 doc ≥1 chunk
    assert len(uuids) == len(set(uuids)), "重复向量 UUID(违反零重复)"
    for sid, cc in rows.items():
        per_doc = sum(1 for u, o in store.objects.items() if o["props"]["source_id"] == sid)
        assert per_doc == cc, f"{sid}: 账本 {cc} != 向量 {per_doc}"
    await engine.dispose()
