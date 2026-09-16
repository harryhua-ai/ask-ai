"""Issue #83:repair authority 服从 lifecycle 真值(fail-closed 门)。

生产事故(wiki 2-sdk-reference,墓碑 2026-09-15T09:22:20Z):管理员对已
墓碑文档点击"重新处理",repair 从持久 chunk 副本再物化向量并宣称
"知识内容已成功进入当前服务"(8/8 一致性通过)——Lifecycle authority
与 Repair authority 脱节。

冻结语义(本套件):
- ``deleted``(墓碑)→ repair 受理/执行均 fail-closed 拒绝(零 embed、
  零 vector insert、零 lifecycle restore);
- ``superseded`` → 同上;
- TOCTOU:task 受理后再墓碑 → 执行阶段再次 fail-closed(任务如实置
  failed,绝不把 index completeness 宣称为 serving success);
- active + 真实 index gap → repair 继续成功(资格修复能力保留);
- healthy active 重复 repair → 幂等 no-op(0 重灌,复验通过);
- 历史 version/chunk 审计数据不动(本套件零删除断言)。

真实 Postgres(TEST_DATABASE_URL);Weaviate/嵌入用测试替身注入
app.state(接口同 weaviate v4 client;替身带在服代 props,与
test_data_sources_track_c 同构)。
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import (
    DataSource,
    Document,
    DocumentRepairTask,
    DocumentVersion,
    DocumentVersionChunk,
    IndexGeneration,
    User,
)
from backend.main import app
from backend.services.document_repair import create_repair_task, execute_repair_task

pytestmark = pytest.mark.asyncio(loop_scope="session")

SRC = f"u83-{uuid.uuid4().hex[:10]}"
ORDINAL = uuid.uuid4().int % 900_000_000 + 100_000_000
NOW = datetime.now(UTC)

DOC_TOMBSTONE = f"{SRC}/main/2-sdk-reference.md"  # 墓碑(生产事故同型:8/12 在服)
DOC_SUPERSEDED = f"{SRC}/main/old-guide.md"  # 被接替(8/12 在服)
DOC_GAP = f"{SRC}/main/getting-started.md"  # active + 真实缺口(10/12)
DOC_HEALTHY = f"{SRC}/main/healthy.md"  # healthy active(12/12)
DOC_TOCTOU = f"{SRC}/main/toctou.md"  # 受理后再墓碑(0/12,不墓碑必全量重灌)
REPAIR_URL = f"/api/admin/data-sources/{SRC}/documents/repair"

# 文档 → 在服对象数(替身集合初始状态;缺口 = 期望 12 − 在服数)
SERVING_COUNTS = {
    DOC_TOMBSTONE: 8,
    DOC_SUPERSEDED: 8,
    DOC_GAP: 10,
    DOC_HEALTHY: 12,
    DOC_TOCTOU: 0,
}
ALL_DOCS = (
    (DOC_TOMBSTONE, "deleted"),
    (DOC_SUPERSEDED, "superseded"),
    (DOC_GAP, "active"),
    (DOC_HEALTHY, "active"),
    (DOC_TOCTOU, "active"),
)


class _FakeCollection:
    """weaviate v4 collection 测试替身(iterator/data.insert)。

    存完整 properties(含 generation_ordinal);insert 计数供零写入断言。"""

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
                coll.inserted.append(dict(properties))
                coll.objects.append(dict(properties))
                return uuid

        return _Data()

    def inserted_for(self, doc_source_id: str) -> list[dict]:
        return [p for p in self.inserted if p.get("source_id") == doc_source_id]


class _CountingEmbedder:
    """计数嵌入替身(零 embed 断言用)。"""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return [[0.1, 0.2, 0.3] for _ in texts]


async def _mk_version(session, doc_source_id: str, chunk_count: int = 12):
    """建 current 版本 + 持久 chunk 副本(账本真值;墓碑也保留——审计)。"""
    version = DocumentVersion(
        source_id=doc_source_id,
        version_seq=1,
        content_hash="a" * 64,
        metadata_hash="b" * 64,
        generation_id=_mk_version.gen.id,
        generation_ordinal=_mk_version.gen.ordinal,
        status="active",
        title=doc_source_id.rsplit("/", 1)[-1],
        url=f"https://wiki.example.com/{doc_source_id.rsplit('/', 1)[-1]}",
        chunk_count=chunk_count,
    )
    session.add(version)
    await session.flush()
    for i in range(chunk_count):
        session.add(
            DocumentVersionChunk(
                version_id=version.id,
                chunk_index=i,
                text=f"{doc_source_id}#chunk-{i}",
                props={
                    "source_id": doc_source_id,
                    "source_type": "github",
                    "chunk_index": i,
                    "title": doc_source_id.rsplit("/", 1)[-1],
                },
            )
        )
    return version


@pytest_asyncio.fixture(loop_scope="session")
async def seed():
    """播种:1 源 + 5 文档(墓碑/接替/缺口/健康/TOCTOU)+ current 版本 + chunks。"""
    factory = app.state.session_factory
    async with factory() as session:
        gen = IndexGeneration(ordinal=ORDINAL, source_id=SRC, status="ready")
        session.add(gen)
        await session.flush()
        _mk_version.gen = gen
        session.add(
            DataSource(
                id=SRC,
                type="github",
                product="u83",
                config={"base_url": "https://wiki.example.com"},
                sync_interval="24h",
                enabled=True,
            )
        )
        for doc_id, lifecycle in ALL_DOCS:
            version = await _mk_version(session, doc_id)
            doc = Document(
                source_id=doc_id,
                content_hash="c" * 64,
                source_type="github",
                product="u83",
                title=doc_id.rsplit("/", 1)[-1],
                url=f"https://wiki.example.com/{doc_id.rsplit('/', 1)[-1]}",
                branch="",
                chunk_count=12,
                lifecycle=lifecycle,
                current_version_id=version.id,
            )
            if lifecycle == "deleted":
                doc.deleted_at = NOW
            if lifecycle == "superseded":
                doc.superseded_by = f"{SRC}/main/new-guide.md"
                doc.superseded_at = NOW
            session.add(doc)
        await session.commit()
    yield
    # 清理(墓碑/接替/健康行全删;历史审计数据在本套件内不产生真实删除语义)
    async with factory() as session:
        await session.execute(
            DocumentRepairTask.__table__.delete().where(DocumentRepairTask.source_id == SRC)
        )
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
    """注入 Weaviate/嵌入测试替身(退出恢复原值)。"""
    saved = {
        k: getattr(app.state, k, None)
        for k in ("weaviate_client", "embedder", "weaviate_class_name")
    }
    objects: list[dict] = []
    for doc_id, lifecycle in ALL_DOCS:
        for i in range(SERVING_COUNTS[doc_id]):
            objects.append(
                {
                    "source_id": doc_id,
                    "chunk_index": i,
                    "generation_ordinal": ORDINAL,
                }
            )
    collection = _FakeCollection(objects)
    embedder = _CountingEmbedder()
    client = SimpleNamespace(collections=SimpleNamespace(get=lambda _name: collection))
    app.state.weaviate_client = client
    app.state.embedder = embedder
    app.state.weaviate_class_name = "Document"
    yield {"client": client, "collection": collection, "embedder": embedder}
    for k, v in saved.items():
        if v is not None:
            setattr(app.state, k, v)


# --------------------------------------------------------------------------- #
# RED 复现面(生产事故同型):墓碑/接替 repair 必须 fail-closed
# --------------------------------------------------------------------------- #


async def test_u83_deleted_tombstone_repair_fail_closed(admin_headers, seed, vector_stack):
    """墓碑文档 repair:受理即拒绝(409);零 embed、零 insert、零 restore。

    生产事故同型:2-sdk-reference 墓碑后仍持 current_version + persisted
    chunks;未守卫的 repair 会从历史副本再物化并宣称 serving success。
    """
    collection = vector_stack["collection"]
    embedder = vector_stack["embedder"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post(
            REPAIR_URL, json={"doc_source_id": DOC_TOMBSTONE}, headers=admin_headers
        )
    assert resp.status_code == 409, resp.text
    assert "退役" in resp.json()["detail"]
    # 零 embed、零 vector insert
    assert embedder.calls == []
    assert collection.inserted_for(DOC_TOMBSTONE) == []
    # 零任务受理(无 succeeded 语义残留)
    factory = app.state.session_factory
    async with factory() as session:
        tasks = (
            (
                await session.execute(
                    select(DocumentRepairTask).where(
                        DocumentRepairTask.doc_source_id == DOC_TOMBSTONE
                    )
                )
            )
            .scalars()
            .all()
        )
        assert tasks == []
        doc = (
            await session.execute(Document.__table__.select().where(Document.source_id == DOC_TOMBSTONE))
        ).first()
        assert doc.lifecycle == "deleted"  # 零 lifecycle restore
        assert doc.deleted_at is not None
        # Acceptance 8:历史审计数据保留(current version + 持久 chunks 未动)
        version = (
            await session.execute(
                select(DocumentVersion).where(DocumentVersion.source_id == DOC_TOMBSTONE)
            )
        ).scalar_one()
        assert version is not None
        chunks = (
            (
                await session.execute(
                    select(DocumentVersionChunk).where(
                        DocumentVersionChunk.version_id == version.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(chunks) == 12


async def test_u83_superseded_repair_fail_closed(admin_headers, seed, vector_stack):
    """被接替文档 repair:同样 fail-closed(409;零 embed/insert)。"""
    collection = vector_stack["collection"]
    embedder = vector_stack["embedder"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post(
            REPAIR_URL, json={"doc_source_id": DOC_SUPERSEDED}, headers=admin_headers
        )
    assert resp.status_code == 409, resp.text
    assert embedder.calls == []
    assert collection.inserted_for(DOC_SUPERSEDED) == []
    factory = app.state.session_factory
    async with factory() as session:
        doc = (
            await session.execute(Document.__table__.select().where(Document.source_id == DOC_SUPERSEDED))
        ).first()
        assert doc.lifecycle == "superseded"
        assert doc.superseded_by is not None


async def test_u83_toctou_tombstone_after_create_rejected_at_execute(seed, vector_stack):
    """TOCTOU:task 受理后、执行前墓碑 → 执行阶段 fail-closed。

    任务如实置 failed(错误注明退役拒绝);零 embed、零 insert;
    result 不携带任何 serving success 语义(不把 index completeness
    宣称为"已成功进入当前服务")。
    """
    collection = vector_stack["collection"]
    embedder = vector_stack["embedder"]
    factory = app.state.session_factory
    async with factory() as session:
        task, created = await create_repair_task(
            session, SRC, DOC_TOCTOU, requested_by="toctou-test", idempotency_key=None
        )
        assert created is True
        assert task.status == "pending"
        # 受理后墓碑(与 tombstone_document 同语义:lifecycle→deleted + deleted_at;
        # 原语为同步会话版,此处以账本同字段等价施加)
        doc = (
            await session.execute(select(Document).where(Document.source_id == DOC_TOCTOU))
        ).scalar_one()
        doc.lifecycle = "deleted"
        doc.deleted_at = datetime.now(UTC)
        await session.commit()

    finished = await execute_repair_task(
        factory,
        weaviate_client=vector_stack["client"],
        embedder=embedder,
        class_name="Document",
        task_id=task.id,
    )
    assert finished.status == "failed"
    assert finished.error is not None and "退役" in finished.error
    assert embedder.calls == []  # 零 embed
    assert collection.inserted_for(DOC_TOCTOU) == []  # 零 vector insert
    # 验证诚实:无 succeeded / 无 consistency=passed 语义
    assert finished.result is None or finished.result.get("consistency") != "passed"
    async with factory() as session:
        doc = (
            await session.execute(Document.__table__.select().where(Document.source_id == DOC_TOCTOU))
        ).first()
        assert doc.lifecycle == "deleted"  # 零 lifecycle restore


# --------------------------------------------------------------------------- #
# 资格能力保留:active + 真实缺口成功;healthy 幂等 no-op
# --------------------------------------------------------------------------- #


async def test_u83_active_genuine_gap_repair_still_succeeds(admin_headers, seed, vector_stack):
    """active + 真实 index gap(10/12)→ repair 成功且只补缺口(零过度写入)。"""
    collection = vector_stack["collection"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post(
            REPAIR_URL, json={"doc_source_id": DOC_GAP}, headers=admin_headers
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "succeeded"
    assert sorted(body["result"]["repaired_indices"]) == [10, 11]
    assert body["result"]["consistency"] == "passed"
    assert len(collection.inserted_for(DOC_GAP)) == 2
    factory = app.state.session_factory
    async with factory() as session:
        doc = (
            await session.execute(Document.__table__.select().where(Document.source_id == DOC_GAP))
        ).first()
        assert doc.lifecycle == "active"  # 零 lifecycle 变更


async def test_u83_healthy_active_repair_idempotent_noop(admin_headers, seed, vector_stack):
    """healthy active(12/12)重复 repair → 幂等 no-op 成功(0 重灌,复验通过)。"""
    collection = vector_stack["collection"]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        first = await client.post(
            REPAIR_URL, json={"doc_source_id": DOC_HEALTHY}, headers=admin_headers
        )
        second = await client.post(
            REPAIR_URL, json={"doc_source_id": DOC_HEALTHY}, headers=admin_headers
        )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["status"] == "succeeded"
    assert second.json()["status"] == "succeeded"
    assert first.json()["result"]["repaired_indices"] == []
    assert second.json()["result"]["repaired_indices"] == []
    assert second.json()["result"]["consistency"] == "passed"
    assert collection.inserted_for(DOC_HEALTHY) == []
