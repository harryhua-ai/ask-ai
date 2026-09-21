"""Issue #100 AC5/AC6:批量修复幂等键有界 + 碰撞安全;批不因单文档失败中断。

生产事故(2026-09-21):``repair-all`` 的幂等键按
``bulk-repair-v1:{source_id}:{doc.source_id}`` 全量拼接,长嵌套路径 /
Unicode 文件名超出 ``document_repair_tasks.idempotency_key`` 的
``varchar(100)``,首个长身份 INSERT 即 ``StringDataRightTruncationError``,
HTTP 500 且整批中止 —— 操作员唯一的批量恢复原语确定性不可用。

契约:

- AC5:确定性有界碰撞安全身份;同身份重试幂等(同键 → 原任务);
  任意长合法身份不再因键长失败;短身份保持既有 v1 键(连续性);
- AC6:逐文档隔离 —— 单文档受理/执行失败只降级该项 failed,整批继续
  处理完全部资格集;聚合与逐项 lineage(doc_source_id/task_id/error)
  如实可审计;单文档修复既有语义不回归。

真实 Postgres(TEST_DATABASE_URL);Weaviate/嵌入用测试替身注入 app.state
(与 Track C U-8/U-14 门测试同约定)。
"""

import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.api.admin.data_sources import _bulk_repair_idempotency_key
from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import (
    DataSource,
    Document,
    DocumentRepairTask,
    DocumentVersion,
    DocumentVersionChunk,
    IndexGeneration,
    SyncLog,
    SyncRequest,
    User,
)
from backend.main import app

SRC = f"bulk100-{uuid.uuid4().hex[:10]}"
ORDINAL = uuid.uuid4().int % 900_000_000 + 100_000_000
BULK_URL = f"/api/admin/data-sources/{SRC}/documents/repair-all"

# 长嵌套 Unicode 身份:legacy v1 键远超 100 字符(生产事故形态)
DOC_LONG = f"{SRC}/main/知识库/支持案例/2026/九月/上传批次-03/_nested/deep/path/document-with-a-very-long-descriptive-name-最终版.md"
DOC_SHORT = f"{SRC}/main/short.md"
DOC_REPAIRABLE = f"{SRC}/main/repairable.md"


class _FakeCollection:
    """weaviate v4 collection 测试替身(同 Track C INT-C-01 在服代语义)。"""

    def __init__(self, objects: list[dict]) -> None:
        self.objects: list[dict] = [dict(o) for o in objects]
        self.inserted: list[dict] = []

    def iterator(self, return_properties=None, **kw):
        def _gen():
            for o in self.objects:
                props = dict(o)
                if return_properties:
                    props = {k: props.get(k) for k in return_properties}
                yield SimpleNamespace(properties=props)

        return _gen()

    @property
    def data(self):
        coll = self

        class _Data:
            def insert(self, *, properties, vector, uuid):
                coll.inserted.append(properties)
                coll.objects.append(dict(properties))
                return uuid

        return _Data()


class _FakeEmbedder:
    def embed(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


@pytest_asyncio.fixture(loop_scope="session")
async def bulk_seed():
    """播种:1 filesystem 源 + 2 attention 文档(短/长身份)+ 完整版本/chunks。"""
    factory = app.state.session_factory
    async with factory() as session:
        session.add(
            DataSource(
                id=SRC,
                type="filesystem",
                product="probe",
                config={"root_path": f"data/uploads/data-sources/{SRC}"},
                sync_interval="24h",
                enabled=True,
            )
        )
        # active 且无可解析现行版本 ⇒ attention 资格(批量修复资格集形态);
        # 修复执行走「无现行版本 → rebuild_requested」真实交接路径。
        for doc_id in (DOC_SHORT, DOC_LONG):
            session.add(
                Document(
                    source_id=doc_id,
                    content_hash="c" * 64,
                    source_type="filesystem",
                    product="probe",
                    title=doc_id.rsplit("/", 1)[-1],
                    url=f"file:///{doc_id}",
                    branch="",
                    chunk_count=0,
                    lifecycle="active",
                )
            )
        session.add(
            Document(
                source_id=DOC_REPAIRABLE,
                content_hash="c" * 64,
                source_type="filesystem",
                product="probe",
                title=DOC_REPAIRABLE.rsplit("/", 1)[-1],
                url=f"file:///{DOC_REPAIRABLE}",
                branch="",
                chunk_count=0,
                lifecycle="missing_candidate",
            )
        )
        await session.commit()
    yield
    async with factory() as session:
        await session.execute(DocumentRepairTask.__table__.delete().where(DocumentRepairTask.source_id == SRC))
        await session.execute(SyncLog.__table__.delete().where(SyncLog.source_id == SRC))
        await session.execute(SyncRequest.__table__.delete().where(SyncRequest.source_id == SRC))
        await session.execute(
            DocumentVersionChunk.__table__.delete().where(
                DocumentVersionChunk.version_id.in_(
                    select(DocumentVersion.id).where(DocumentVersion.source_id.like(f"{SRC}/%"))
                )
            )
        )
        await session.execute(
            DocumentVersion.__table__.delete().where(DocumentVersion.source_id.like(f"{SRC}/%"))
        )
        await session.execute(Document.__table__.delete().where(Document.source_id.like(f"{SRC}/%")))
        await session.execute(IndexGeneration.__table__.delete().where(IndexGeneration.source_id == SRC))
        await session.execute(DataSource.__table__.delete().where(DataSource.id == SRC))
        await session.execute(User.__table__.delete().where(User.email.like(f"{SRC}%")))
        await session.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def admin_headers():
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email=f"{SRC}-admin@test.com",
                role="admin",
                password_hash=hash_password("pass123"),
            )
        )
        await session.commit()
    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}
    async with factory() as session:
        await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def vector_stack():
    saved = {
        k: getattr(app.state, k, None)
        for k in ("weaviate_client", "embedder", "weaviate_class_name")
    }
    collection = _FakeCollection([])
    client = SimpleNamespace(collections=SimpleNamespace(get=lambda _name: collection))
    app.state.weaviate_client = client
    app.state.embedder = _FakeEmbedder()
    app.state.weaviate_class_name = "Document"
    yield {"client": client}
    for k, v in saved.items():
        if v is not None:
            setattr(app.state, k, v)


# --------------------------------------------------------------------------- #
# AC5:幂等键有界 + 碰撞安全 + 连续性
# --------------------------------------------------------------------------- #


def test_bulk_key_short_identity_keeps_legacy_v1_key():
    """短身份:保持既有 v1 键(向后连续;既有行重试幂等不被键换代破坏)。"""
    key = _bulk_repair_idempotency_key("src", "src/main/a.md")
    assert key == f"bulk-repair-v1:src:src/main/a.md"


def test_bulk_key_long_identity_bounded_and_deterministic():
    """AC5:超长身份 ⇒ 有界(<100)且确定(同身份恒同键;重试幂等)。"""
    k1 = _bulk_repair_idempotency_key(SRC, DOC_LONG)
    k2 = _bulk_repair_idempotency_key(SRC, DOC_LONG)
    assert k1 == k2
    assert len(k1) <= 100, "任意长合法身份生成的键必须 ≤ varchar(100) 列宽"
    assert k1.startswith("bulk-repair-v2:")


def test_bulk_key_distinct_identities_never_collide():
    """碰撞安全:不同身份 ⇒ 不同键(确定性身份,非顺序/时间戳)。"""
    keys = {
        _bulk_repair_idempotency_key(SRC, f"{SRC}/main/{name}.md")
        for name in ("a", "b", "知识库/支持案例/很长" * 20)
    }
    assert len(keys) == 3


@pytest.mark.asyncio(loop_scope="session")
async def test_repair_all_long_identity_no_truncation_failure(
    admin_headers, bulk_seed, vector_stack
):
    """AC5 主链:长 Unicode 嵌套身份 ⇒ repair-all 200,不再 varchar 溢出。

    RED(现状):首个长身份 INSERT 即
    ``asyncpg.exceptions.StringDataRightTruncationError`` → HTTP 500。
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post(BULK_URL, headers=admin_headers)
    assert resp.status_code == 200, (
        "长身份不得因幂等键列宽溢出使 repair-all 整体 500"
        f"(现状返回 {resp.status_code}: {resp.text[:200]})"
    )
    body = resp.json()
    by_doc = {i["doc_source_id"]: i for i in body["items"]}
    assert DOC_LONG in by_doc, "长身份文档必须在批内被逐项处理(不得整批中止)"

    # 任务行落库键全部 ≤ 100 且重试幂等(同身份同键 → 原任务)
    async with app.state.session_factory() as session:
        keys = (
            (
                await session.execute(
                    select(DocumentRepairTask.idempotency_key).where(
                        DocumentRepairTask.source_id == SRC
                    )
                )
            )
            .scalars()
            .all()
        )
    assert all(k is not None and len(k) <= 100 for k in keys)


@pytest.mark.asyncio(loop_scope="session")
async def test_repair_all_retry_is_idempotent(admin_headers, bulk_seed, vector_stack):
    """AC5:同批重试 ⇒ 幂等(原任务复用,不产生重复执行记录)。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        first = await client.post(BULK_URL, headers=admin_headers)
        second = await client.post(BULK_URL, headers=admin_headers)
    assert first.status_code == 200 and second.status_code == 200
    async with app.state.session_factory() as session:
        task_keys = (
            (
                await session.execute(
                    select(DocumentRepairTask.doc_source_id, DocumentRepairTask.idempotency_key)
                    .where(DocumentRepairTask.source_id == SRC)
                )
            )
            .all()
        )
    per_doc = {}
    for doc_id, key in task_keys:
        per_doc.setdefault(doc_id, set()).add(key)
    for doc_id, seen in per_doc.items():
        assert len(seen) == 1, f"重试不得为同一文档制造第二把幂等键:{doc_id}"


# --------------------------------------------------------------------------- #
# AC6:逐文档隔离,批不中断
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio(loop_scope="session")
async def test_bulk_repair_continues_after_per_document_failure(
    admin_headers, bulk_seed, vector_stack, monkeypatch
):
    """AC6:单文档受理/执行失败 ⇒ 该项 failed,其余文档照常处理完毕。"""
    import backend.api.admin.data_sources as ds_mod

    real_execute = ds_mod.execute_repair_task
    call_count = {"n": 0}

    async def flaky_execute(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated per-document execution failure")
        return await real_execute(*args, **kwargs)

    monkeypatch.setattr(ds_mod, "execute_repair_task", flaky_execute)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post(BULK_URL, headers=admin_headers)
    assert resp.status_code == 200, (
        "单文档失败不得使整批 500 中止 —— 逐项隔离,资格集必须处理完"
    )
    body = resp.json()
    assert body["eligible"] == 3
    assert body["failed"] >= 1, "失败文档必须如实计入 failed(不伪装成功)"
    assert body["succeeded"] + body["rebuild_requested"] + body["failed"] == body["eligible"]
    failed_items = [i for i in body["items"] if i["status"] == "failed"]
    assert failed_items and failed_items[0]["error"], (
        "失败项必须携带 error 明细(逐项 lineage 可审计)"
    )
