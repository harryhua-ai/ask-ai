"""Issue #91 P0 sync 面收敛回归:ne301 型「大缺失→补灌→零激活→同缺失」循环终止。

生产事实(2026-09-17 只读取证,cron 三连轮):
    ne301-local authoritative=15870 / serving=5379 / missing=10491 →
    每轮补灌 10491 篇嵌入 ~1h42m → 88 篇 content 级安全排除毒化整代 →
    零激活 → 下轮同 missing。lowpower-camera-local / neomind-local /
    neomind-extensions-local 同构。

本文件在真实 sync 编排(``scripts.sync._sync_one``)+ 真实 GenerationBuilder +
真实 Weaviate 上证明收敛契约:排除物分区后,第一轮收敛、第二轮真 no-change
零重嵌、新合法成员仍被补灌、瞬态失败依旧 fail-closed、政策缺席与安全排除
语义互不干扰。连接器 stub(零外网),账本共享测试库,SRC 前缀隔离。
"""

from __future__ import annotations

import hashlib
import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
import weaviate
from sqlalchemy import delete, select

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import scripts.sync as sync_mod
from backend.config import load_settings
from backend.connectors.base import RawDocument
from backend.connectors.registry import SourceConfig
from backend.db.models import (
    DataSource,
    Document,
    DocumentVersion,
    IndexGeneration,
    SyncLog,
    SyncRun,
)
from backend.db.session import get_engine, get_session_factory, init_db
from backend.services.document_lifecycle import DocLifecycle

pytestmark = pytest.mark.asyncio(loop_scope="session")

TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test",
)
WEAVIATE_PORT = int(os.environ.get("P1_WEAVIATE_PORT", "8080"))
CLASS_NAME = "I91ConvProbe"

SRC = "i91conv-local"
OK1 = f"{SRC}/main/docs/overview.md"
OK2 = f"{SRC}/main/docs/setup.md"
OK3 = f"{SRC}/main/CHANGELOG.md"
OK_NEW = f"{SRC}/main/docs/new-arrival.md"
BIN = f"{SRC}/main/framework/morsefirmware/bcf_aw_hm593.mbin"
POLICY_EXCLUDED = f"{SRC}/main/vendor/third-party-sdk/lib.so"

BINARY_CONTENT = "BCF\x00\x00\x01\x02\x03firmware-bytes\x00\x00"


def _hash(x: str) -> str:
    return hashlib.sha256(x.encode()).hexdigest()


def _raw_doc(source_id: str, content: str | None = None) -> RawDocument:
    text = content if content is not None else (
        f"# {source_id.rsplit('/', 1)[-1]}\n\n"
        "alpha paragraph about connectors and sync.\n\n"
        "beta paragraph about retrieval and ranking.\n\n"
        "gamma paragraph about lifecycle and generations.\n\n"
        "delta paragraph about activation and versions.\n\n"
        "epsilon paragraph about membership reconciliation.\n\n"
        "zeta paragraph about atomic generations.\n\n"
    )
    return RawDocument(
        source_id=source_id,
        source_type="github",
        product="wiki",
        title=source_id.rsplit("/", 1)[-1],
        content=text,
        url=f"https://github.com/example/blob/{source_id}",
        metadata={"path": source_id},
        content_hash=_hash(text),
        branch=source_id.split("/")[1],
    )


def _bin_doc() -> RawDocument:
    return _raw_doc(BIN, BINARY_CONTENT)


# --------------------------------------------------------------------------- #
# harness(#82 套件同法:connector stub + 真实 builder/pipeline/账本/Weaviate)
# --------------------------------------------------------------------------- #


@dataclass
class _Report:
    expected_chunks: int = 10
    actual_chunks: int = 10
    missing_source_ids: list = field(default_factory=list)
    refill_source_ids: list = field(default_factory=list)
    orphan_count: int = 0
    orphan_chunks: dict = field(default_factory=dict)
    stale_chunk_count: int = 0
    is_healthy: bool = True


class _Connector:
    """增量零产出(SHA 短路形);成员全集与 fetch_all 由测试注入。"""

    def __init__(self, members: set[str], full_docs: list[RawDocument]) -> None:
        self._members = members
        self._full_docs = full_docs

    DECLARES_DELETIONS = True  # git 类自证删除:缺席确认面不介入

    def membership_source_ids(self) -> set[str]:
        return set(self._members)

    def fetch_all(self):
        return iter(list(self._full_docs))

    def fetch_changes(self, since):
        return iter([])

    def fetch_deleted(self, since):
        return []


class _FakeEmbedder:
    dimension = 8

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.fail = False

    def embed(self, texts):
        if self.fail:
            raise RuntimeError("fake embedder boom")
        self.calls.append(list(texts))
        return [[0.1] * self.dimension for _ in texts]


def _uuid4():
    return uuid.uuid4()


_CURRENT: dict = {"connector": None}


@pytest.fixture(autouse=True)
def _stub_registry(monkeypatch):
    monkeypatch.setattr(
        sync_mod.ConnectorRegistry, "create", lambda cfg: _CURRENT["connector"]
    )
    yield
    _CURRENT["connector"] = None


@pytest.fixture
def healthy_report(monkeypatch):
    report = _Report()
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        sync_mod, "verify_source_vectors", AsyncMock(return_value=report), raising=True
    )
    return report


def _make_weaviate_client():
    try:
        client = weaviate.connect_to_local("localhost", WEAVIATE_PORT)
    except Exception:  # noqa: BLE001
        pytest.skip(f"local Weaviate 不可达(port={WEAVIATE_PORT})")
    if client.collections.exists(CLASS_NAME):
        client.collections.delete(CLASS_NAME)
    return client


@pytest_asyncio.fixture(loop_scope="session")
async def db_engine():
    engine = get_engine(TEST_DSN)
    try:
        await init_db(engine)
        from scripts.migrate_add_membership_currency import migrate as _migrate

        await _migrate(engine)
        yield engine
    finally:
        f = get_session_factory(engine)
        async with f() as session:
            for model, col in (
                (SyncRun, SyncRun.source_id),
                (SyncLog, SyncLog.source_id),
            ):
                await session.execute(delete(model).where(col == SRC))
            await session.execute(delete(Document).where(Document.source_id.like(f"{SRC}/%")))
            await session.execute(
                delete(DocumentVersion).where(DocumentVersion.source_id.like(f"{SRC}/%"))
            )
            await session.execute(delete(IndexGeneration).where(IndexGeneration.source_id == SRC))
            await session.execute(delete(DataSource).where(DataSource.id == SRC))
            try:
                from backend.db.models import IngestionExclusion

                await session.execute(
                    delete(IngestionExclusion).where(
                        IngestionExclusion.source_id.like(f"{SRC}/%")
                    )
                )
            except Exception:  # noqa: BLE001 - 基线无该表
                pass
            await session.commit()
        await engine.dispose()


@pytest.fixture
def sync_factory(db_engine):
    import sqlalchemy

    engine = sqlalchemy.create_engine(TEST_DSN.replace("+asyncpg", "+psycopg2"))
    try:
        yield sqlalchemy.orm.sessionmaker(bind=engine, expire_on_commit=False)
    finally:
        engine.dispose()


def _real_stack(sync_factory):
    """真实 IngestionPipeline + GenerationBuilder(fake embedder + 真 Weaviate)。"""
    from backend.pipeline.ingest import IngestionPipeline
    from backend.pipeline.generation_builder import GenerationBuilder

    client = _make_weaviate_client()
    embedder = _FakeEmbedder()
    pipeline = IngestionPipeline(
        embedder,
        client,
        class_name=CLASS_NAME,
        max_tokens=40,
        overlap=0,
        session_factory=sync_factory,
        max_chunk_chars=2000,
    )
    builder = GenerationBuilder(pipeline, sync_factory)
    stack = SimpleNamespace(
        client=client,
        embedder=embedder,
        pipeline=pipeline,
        builder=builder,
    )
    return stack


def _embedded_texts(stack) -> list[str]:
    return [t for batch in stack.embedder.calls for t in batch]


async def _seed(db_engine, docs: list[tuple[str, str]]) -> None:
    factory = get_session_factory(db_engine)
    async with factory() as session:
        session.add(DataSource(id=SRC, type="github", product="wiki", config={}))
        for sid, lifecycle_state in docs:
            doc = Document(
                source_id=sid,
                source_type="github",
                product="wiki",
                title=sid.rsplit("/", 1)[-1],
                url=f"https://github.com/example/blob/{sid}",
                branch=sid.split("/")[1],
                chunk_count=4,
                content_hash=_hash(sid),
                lifecycle=lifecycle_state,
            )
            session.add(doc)
            if lifecycle_state in DocLifecycle.SERVING:
                version = DocumentVersion(
                    id=_uuid4(),
                    source_id=sid,
                    version_seq=1,
                    content_hash=doc.content_hash,
                    metadata_hash=_hash("m" + sid),
                    generation_id="00000000-0000-0000-0000-000000000000",
                    generation_ordinal=0,
                    status="active",
                    title=doc.title,
                    url=doc.url,
                    chunk_count=4,
                )
                session.add(version)
                doc.current_version_id = version.id
        await session.commit()


async def _latest_sync_log(db_engine) -> SyncLog:
    factory = get_session_factory(db_engine)
    async with factory() as session:
        row = (
            await session.execute(
                select(SyncLog)
                .where(SyncLog.source_id == SRC)
                .order_by(SyncLog.started_at.desc())
                .limit(1)
            )
        ).scalar_one()
        session.expunge(row)
        return row


async def _serving_ids(db_engine) -> set[str]:
    factory = get_session_factory(db_engine)
    async with factory() as session:
        rows = (
            await session.execute(
                select(Document.source_id).where(
                    Document.source_id.like(f"{SRC}/%"),
                    Document.lifecycle.in_(DocLifecycle.SERVING),
                )
            )
        ).all()
    return {str(r[0]) for r in rows}


def _cfg() -> SourceConfig:
    return SourceConfig(
        id=SRC,
        type="github",
        product="wiki",
        enabled=True,
        config={},
        sync_interval="24h",
    )


# --------------------------------------------------------------------------- #
# RED-1:第一轮收敛(生产循环机制的 sync 面复现 → 分区后收敛)
# --------------------------------------------------------------------------- #


async def test_first_cycle_converges_despite_permanent_exclusion(
    db_engine, sync_factory, healthy_report
):
    """账本 1 在服 + 权威 3 合法 1 二进制:第一轮必须收敛而不是整轮 failed。

    基线 RED:补灌批次含排除物 → build_generation IngestFailures →
    SyncLog failed、零激活 —— 与生产 ne301-local 每轮失败完全同构。
    """
    stack = _real_stack(sync_factory)
    factory = get_session_factory(db_engine)
    await _seed(db_engine, [(OK1, DocLifecycle.ACTIVE)])
    members = {OK1, OK2, OK3, BIN}
    _CURRENT["connector"] = _Connector(
        members=members, full_docs=[_raw_doc(OK2), _raw_doc(OK3), _bin_doc()]
    )

    await sync_mod._sync_one(
        _cfg(), stack.pipeline, factory, triggered_by="manual", builder=stack.builder
    )
    log = await _latest_sync_log(db_engine)
    assert log.status == "success", (
        f"第一轮必须收敛(基线:failed,生产循环机制);error={log.error_detail[:200]}"
    )

    serving = await _serving_ids(db_engine)
    assert serving == {OK1, OK2, OK3}, "3 合法成员全部在服"
    from backend.db.models import IngestionExclusion

    async with factory() as session:
        rows = (
            (
                await session.execute(
                    select(IngestionExclusion).where(IngestionExclusion.source_id == BIN)
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1 and rows[0].reason == "binary_content", (
        "排除物持久化登记(可审计)"
    )

    delta = dict(log.delta_counts or {})
    assert delta["membership_excluded"] == 1, "对账面必须暴露永久排除计数"
    assert delta["permanent_excluded"] == 1, "构建面必须暴露分区计数"
    # 排除物零嵌入(嵌入只发生在合法内容上)
    embedded = "\n".join(_embedded_texts(stack))
    assert "firmware-bytes" not in embedded, "排除物绝不进入嵌入"
    stack.client.close()


async def test_second_cycle_true_no_change_zero_reembed(
    db_engine, sync_factory, healthy_report
):
    """AC5/AC6:收敛后下一轮同权威 = 真 no-change:零构建、零嵌入、零补灌。"""
    stack = _real_stack(sync_factory)
    factory = get_session_factory(db_engine)
    await _seed(
        db_engine,
        [
            (OK1, DocLifecycle.ACTIVE),
            (OK2, DocLifecycle.ACTIVE),
            (OK3, DocLifecycle.ACTIVE),
        ],
    )
    from backend.db.models import IngestionExclusion

    async with factory() as session:
        session.add(
            IngestionExclusion(
                source_id=BIN,
                content_hash=_hash(BINARY_CONTENT),
                reason="binary_content",
                detail="NUL byte in head sample",
                stage="SAFETY_FILTER",
            )
        )
        await session.commit()

    _CURRENT["connector"] = _Connector(
        members={OK1, OK2, OK3, BIN},
        full_docs=[_raw_doc(OK2), _raw_doc(OK3), _bin_doc()],
    )
    await sync_mod._sync_one(
        _cfg(), stack.pipeline, factory, triggered_by="cron", builder=stack.builder
    )
    log = await _latest_sync_log(db_engine)
    assert log.status == "success"
    delta = dict(log.delta_counts or {})
    assert delta["unchanged_count"] == 3
    assert "membership_backfilled" not in delta, "排除物不得再触发补灌"
    assert _embedded_texts(stack) == [], "第二轮零嵌入(生产 GPU 放大循环终止)"
    stack.client.close()


async def test_new_eligible_member_still_backfilled(
    db_engine, sync_factory, healthy_report
):
    """AC6:收敛态下新增合法权威成员仍被检测、补灌、激活;排除物保持排除。"""
    stack = _real_stack(sync_factory)
    factory = get_session_factory(db_engine)
    await _seed(
        db_engine,
        [
            (OK1, DocLifecycle.ACTIVE),
            (OK2, DocLifecycle.ACTIVE),
            (OK3, DocLifecycle.ACTIVE),
        ],
    )
    from backend.db.models import IngestionExclusion

    async with factory() as session:
        session.add(
            IngestionExclusion(
                source_id=BIN,
                content_hash=_hash(BINARY_CONTENT),
                reason="binary_content",
                detail="NUL byte in head sample",
                stage="SAFETY_FILTER",
            )
        )
        await session.commit()

    _CURRENT["connector"] = _Connector(
        members={OK1, OK2, OK3, OK_NEW, BIN},
        full_docs=[_raw_doc(OK_NEW), _bin_doc()],
    )
    await sync_mod._sync_one(
        _cfg(), stack.pipeline, factory, triggered_by="manual", builder=stack.builder
    )
    log = await _latest_sync_log(db_engine)
    assert log.status == "success"
    serving = await _serving_ids(db_engine)
    assert OK_NEW in serving, "新合法成员正常补灌"
    assert BIN not in serving, "排除物绝不入服务真值"
    assert _embedded_texts(stack) != [] and "firmware-bytes" not in "\n".join(
        _embedded_texts(stack)
    ), "嵌入只发生在新合法成员"
    stack.client.close()


async def test_transient_embed_failure_still_fails_closed_sync(
    db_engine, sync_factory, healthy_report
):
    """AC7:sync 面瞬态失败(嵌入故障)依旧整轮 failed、零激活,绝不伪装收敛。"""
    stack = _real_stack(sync_factory)
    stack.embedder.fail = True
    factory = get_session_factory(db_engine)
    await _seed(db_engine, [(OK1, DocLifecycle.ACTIVE)])
    _CURRENT["connector"] = _Connector(
        members={OK1, OK2}, full_docs=[_raw_doc(OK2)]
    )
    await sync_mod._sync_one(
        _cfg(), stack.pipeline, factory, triggered_by="manual", builder=stack.builder
    )
    log = await _latest_sync_log(db_engine)
    assert log.status == "failed", "瞬态失败必须 fail-closed"
    serving = await _serving_ids(db_engine)
    assert OK2 not in serving, "瞬态失败零激活"
    stack.client.close()


async def test_policy_absence_and_safety_exclusion_no_mismatch(
    db_engine, sync_factory, healthy_report
):
    """AC9:connector 政策排除(枚举面)与运行时安全排除(登记面)互不干扰。

    - 政策排除物不在权威枚举 → 与 missing/排除账目完全无关;
    - 安全排除物在枚举内 → 分区登记压制补灌;即便政策重新纳入它,
      也绝不复活(不重复嵌入、不入服务)。
    """
    stack = _real_stack(sync_factory)
    factory = get_session_factory(db_engine)
    await _seed(
        db_engine,
        [(OK1, DocLifecycle.ACTIVE), (OK2, DocLifecycle.ACTIVE)],
    )
    from backend.db.models import IngestionExclusion

    async with factory() as session:
        session.add(
            IngestionExclusion(
                source_id=BIN,
                content_hash=_hash(BINARY_CONTENT),
                reason="binary_content",
                detail="NUL byte in head sample",
                stage="SAFETY_FILTER",
            )
        )
        await session.commit()

    # 阶段1:政策排除(POLICY_EXCLUDED 不在枚举);BIN 仍在枚举但已被登记压制
    _CURRENT["connector"] = _Connector(
        members={OK1, OK2, OK3, BIN},  # POLICY_EXCLUDED 被连接器政策排除
        full_docs=[_raw_doc(OK3), _bin_doc()],
    )
    await sync_mod._sync_one(
        _cfg(), stack.pipeline, factory, triggered_by="manual", builder=stack.builder
    )
    log = await _latest_sync_log(db_engine)
    assert log.status == "success"
    delta = dict(log.delta_counts or {})
    assert delta["membership_missing"] == 1 and delta["membership_backfilled"] == 1, (
        "只有 OK3 是 actionable missing"
    )
    assert delta["membership_excluded"] == 1, "安全排除计数恰 1(政策排除物不进该账目)"

    # 阶段2:政策重新纳入 POLICY_EXCLUDED(变文本文件)→ 正常补灌;BIN 仍被压制
    docs = [
        _raw_doc(POLICY_EXCLUDED, "# vendored sdk readme\n\ncontent paragraph.\n\n"),
        _bin_doc(),
    ]
    _CURRENT["connector"] = _Connector(
        members={OK1, OK2, OK3, OK_NEW + "x", POLICY_EXCLUDED, BIN} - {OK_NEW + "x"},
        full_docs=docs,
    )
    await sync_mod._sync_one(
        _cfg(), stack.pipeline, factory, triggered_by="manual", builder=stack.builder
    )
    serving = await _serving_ids(db_engine)
    assert POLICY_EXCLUDED in serving, "政策恢复纳入 → 正常入库"
    assert BIN not in serving, "安全排除不因重复出现在枚举而复活"
    assert "firmware-bytes" not in "\n".join(_embedded_texts(stack)), (
        "已排除内容绝不重复嵌入"
    )
    stack.client.close()
