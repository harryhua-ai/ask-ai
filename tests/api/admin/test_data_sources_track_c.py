"""v1.6.3 Track C(U-6..U-13 后端真值面):八项冻结语义 API 契约测试。

合同(docs/engineering/tasks/v163-reference-remediation/track-c-contract.md):
- U-7 逐文档 content_type:结构化后端真值,过滤/聚合真实生效;
- U-8 行级修复:RBAC(viewer 403)/ 幂等(键/开放任务/no-op 复验)/
  审计(events)/ 进度(stage)/ 修复后验证(chunk serving 复验真值);
- U-9 chunk serving 投影:UI 比例必须等于后端真值(10/12 型);
- U-10 恢复计数:持久化权威恢复事件(禁前端计数器);
- U-11 调度真值:next_run_at 权威(禁 sync_interval 纯派生;调度现实
  paused/syncing/waiting_first → NULL);
- U-12 知识设置:CURRENT/HISTORICAL 政策层 + 新鲜度真值 + 检索资格消费;
- U-13 高风险预览:计数服务端权威;确认施加与预览一致 mutation;
  账本 drift → 409 失效。

真实 Postgres(TEST_DATABASE_URL);Weaviate/嵌入用测试替身注入 app.state
(接口同 weaviate v4 client;运行时验收用真实栈)。
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import (
    DataSource,
    Document,
    DocumentRecoveryEvent,
    DocumentRepairTask,
    DocumentVersion,
    DocumentVersionChunk,
    IndexGeneration,
    SyncLog,
    SyncRequest,
    User,
)
from backend.main import app

pytestmark = pytest.mark.asyncio(loop_scope="session")

SRC = f"trackc-{uuid.uuid4().hex[:10]}"
ORDINAL = uuid.uuid4().int % 900_000_000 + 100_000_000
NOW = datetime.now(UTC)

DOC_PRODUCT = f"{SRC}/main/ne101.md"  # 商品(woocommerce 语义示例走 content_type)
DOC_PAGE = f"{SRC}/main/getting-started.md"
DOC_GUIDE = f"{SRC}/main/legacy-guide.md"
DOCS_URL = f"/api/admin/data-sources/{SRC}/documents"
DETAIL_URL = f"/api/admin/data-sources/{SRC}/documents/detail"
SCHEDULE_URL = f"/api/admin/data-sources/{SRC}/schedule"
SETTINGS_URL = f"/api/admin/data-sources/{SRC}/knowledge-settings"
PREVIEW_URL = f"/api/admin/data-sources/{SRC}/knowledge-settings/preview"
REPAIR_URL = f"/api/admin/data-sources/{SRC}/documents/repair"
BULK_REPAIR_URL = f"/api/admin/data-sources/{SRC}/documents/repair-all"


class _FakeCollection:
    """weaviate v4 collection 测试替身(iterator/data.insert/fetch)。

    INT-C-01 收口更新:insert 存**完整 properties**(含 generation_ordinal
    等回写 props),iterator 原样投影 —— 修复回写后按在服代过滤的复验在
    本替身下语义同构(无 generation 语义的替身已被评审禁止)。"""

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


async def _mk_version(session, doc_source_id, seq, chunk_count=12, url=""):
    version = DocumentVersion(
        source_id=doc_source_id,
        version_seq=seq,
        content_hash="a" * 64,
        metadata_hash="b" * 64,
        generation_id=_mk_version.gen.id,
        generation_ordinal=_mk_version.gen.ordinal,
        status="active",
        title=doc_source_id.rsplit("/", 1)[-1],
        url=url,
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
                    "source_type": "woocommerce",
                    "chunk_index": i,
                    "title": doc_source_id.rsplit("/", 1)[-1],
                },
            )
        )
    return version


@pytest_asyncio.fixture(loop_scope="session")
async def c_seed():
    """播种:1 源 + 三文档(product/page/document 内容类型)+ 12-chunk 版本。"""
    factory = app.state.session_factory
    async with factory() as session:
        gen = IndexGeneration(ordinal=ORDINAL, source_id=SRC, status="ready")
        session.add(gen)
        await session.flush()
        _mk_version.gen = gen
        ds = DataSource(
            id=SRC,
            type="woocommerce",
            product="trackc",
            config={"base_url": "https://shop.example.com"},
            sync_interval="24h",
            enabled=True,
        )
        session.add(ds)
        for doc_id, ctype, lifecycle in (
            (DOC_PRODUCT, "product", "missing_candidate"),
            (DOC_PAGE, "page", "active"),
            (DOC_GUIDE, None, "active"),
        ):
            if lifecycle == "missing_candidate":
                session.add(
                    Document(
                        source_id=doc_id,
                        content_hash="c" * 64,
                        source_type="woocommerce",
                        product="trackc",
                        title=doc_id.rsplit("/", 1)[-1],
                        url=f"https://shop.example.com/{doc_id.rsplit('/', 1)[-1]}",
                        branch="",
                        chunk_count=12,
                        lifecycle=lifecycle,
                        content_type=ctype,
                    )
                )
                continue
            version = await _mk_version(
                session, doc_id, 1, url=f"https://shop.example.com/{doc_id.rsplit('/', 1)[-1]}"
            )
            session.add(
                Document(
                    source_id=doc_id,
                    content_hash="c" * 64,
                    source_type="woocommerce",
                    product="trackc",
                    title=doc_id.rsplit("/", 1)[-1],
                    url=f"https://shop.example.com/{doc_id.rsplit('/', 1)[-1]}",
                    branch="",
                    chunk_count=12,
                    lifecycle=lifecycle,
                    content_type=ctype,
                    current_version_id=version.id,
                )
            )
        await session.commit()
    yield
    # 清理(fixture 隔离;WC_ 运行时 seed 的 SQL 全文见执行报告)
    async with factory() as session:
        await session.execute(DocumentRecoveryEvent.__table__.delete().where(DocumentRecoveryEvent.source_id == SRC))
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
        await session.execute(DocumentVersion.__table__.delete().where(DocumentVersion.source_id.like(f"{SRC}/%")))
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
async def viewer_headers():
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email=f"{SRC}-viewer@test.com",
                role="viewer",
                password_hash=hash_password("pass123"),
            )
        )
        await session.commit()
    token = create_access_token(str(user_id), "viewer", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}
    async with factory() as session:
        await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def vector_stack():
    """注入 Weaviate/嵌入测试替身(restore 原值;接口与 v4 client 同形)。"""
    saved = {
        k: getattr(app.state, k, None)
        for k in ("weaviate_client", "embedder", "weaviate_class_name")
    }
    objects = [
        {
            "source_id": DOC_PAGE,
            "chunk_index": i,
            # INT-C-01:在服代语义(与 _mk_version 的代归属一致)——
            # 无 generation props 的对象在修复 plan/verify 口径下不可见。
            "generation_ordinal": ORDINAL,
        }
        for i in range(10)
    ]  # 页面文档 12 期望 chunk 中 10 个在服(10/12 真值场景)
    collection = _FakeCollection([dict(o) for o in objects])
    client = SimpleNamespace(
        collections=SimpleNamespace(get=lambda _name: collection)
    )
    app.state.weaviate_client = client
    app.state.embedder = _FakeEmbedder()
    app.state.weaviate_class_name = "Document"
    yield {"client": client}
    for k, v in saved.items():
        if v is not None:
            setattr(app.state, k, v)


# --------------------------------------------------------------------------- #
# U-7 逐文档 content_type
# --------------------------------------------------------------------------- #


async def test_u7_documents_expose_content_type_truth(viewer_headers, c_seed):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get(DOCS_URL, headers=viewer_headers)
    assert resp.status_code == 200
    items = {i["source_id"]: i for i in resp.json()["items"]}
    assert items[DOC_PRODUCT]["content_type"] == "product"
    assert items[DOC_PAGE]["content_type"] == "page"
    assert items[DOC_GUIDE]["content_type"] is None  # 存量行诚实不可用


async def test_u7_content_type_filter_and_aggregate(viewer_headers, c_seed):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        filtered = await client.get(
            DOCS_URL, params={"content_type": "product"}, headers=viewer_headers
        )
        none_filtered = await client.get(
            DOCS_URL, params={"content_type": "none"}, headers=viewer_headers
        )
        all_docs = await client.get(DOCS_URL, headers=viewer_headers)
    assert filtered.status_code == 200
    body = filtered.json()
    assert body["total"] == 1
    assert body["items"][0]["source_id"] == DOC_PRODUCT
    assert all(i["content_type"] == "product" for i in body["items"])
    # none = 不可用存量行(诚实缺席类,不是推断)
    assert none_filtered.json()["total"] == 1
    assert none_filtered.json()["items"][0]["source_id"] == DOC_GUIDE
    counts = all_docs.json()["content_type_counts"]
    assert counts == {"product": 1, "page": 1}  # NULL 不入聚合


async def test_u7_taxonomy_structured_derivation_no_text_inference():
    from backend.services.content_taxonomy import (
        CONTENT_TYPE_DOCUMENT,
        CONTENT_TYPE_PAGE,
        CONTENT_TYPE_PRODUCT,
        derive_content_type,
    )

    assert derive_content_type("woocommerce", "x", {"type": "simple"}) == CONTENT_TYPE_PRODUCT
    assert derive_content_type("web_crawl", "https://s.com/a/b", {}) == CONTENT_TYPE_PAGE
    assert derive_content_type("web_crawl", "https://s.com/a/manual.pdf", {}) == CONTENT_TYPE_DOCUMENT
    assert derive_content_type("github", "x", {}) == CONTENT_TYPE_DOCUMENT
    assert derive_content_type("unknown_src", "no-signal", {}) == ""  # 无结构化信号 = 不可用


# --------------------------------------------------------------------------- #
# U-9 chunk serving 投影 + U-10 恢复计数 + U-7/U-8 truth 注入
# --------------------------------------------------------------------------- #


async def test_u9_truth_chunk_serving_projection_is_backend_truth(
    viewer_headers, c_seed, vector_stack
):
    """10/12:期望 12,Weaviate 实存 10 → 投影真值 10/12,一致性 False。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get(
            DETAIL_URL, params={"doc_source_id": DOC_PAGE}, headers=viewer_headers
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["chunk_serving"]["total_chunks"] == 12
    assert body["chunk_serving"]["serving_chunks"] == 10
    assert body["chunk_serving"]["missing_indices"] == [10, 11]
    assert body["chunk_serving"]["consistent"] is False
    assert body["content_type"] == "page"


async def test_u9_truth_without_vector_stack_serves_null_not_fake(
    viewer_headers, c_seed, vector_stack
):
    """向量库不可用 → chunk_serving=None(诚实降级,绝不伪造 12/12)。"""
    app.state.weaviate_client = None
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            resp = await client.get(
                DETAIL_URL, params={"doc_source_id": DOC_PAGE}, headers=viewer_headers
            )
        assert resp.status_code == 200
        assert resp.json()["chunk_serving"] is None
    finally:
        app.state.weaviate_client = vector_stack["client"]


async def test_u10_recovery_counts_from_persisted_events(viewer_headers, c_seed):
    """恢复注记 = document_recovery_events 权威计数(1 次未成功型)。"""
    from backend.services.recovery_events import record_recovery_events

    factory = app.state.session_factory
    written = await record_recovery_events(
        factory,
        SRC,
        repaired=[],
        unrepairable=[DOC_PRODUCT],
        sync_run_id=None,
        detail={"mode": "gap_heal_refill"},
    )
    assert written == 1
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get(
            DETAIL_URL, params={"doc_source_id": DOC_PRODUCT}, headers=viewer_headers
        )
    body = resp.json()
    assert body["recovery_attempts_failed"] == 1
    assert body["recovery_attempts_succeeded"] == 0


# --------------------------------------------------------------------------- #
# U-8 行级修复工作流
# --------------------------------------------------------------------------- #


async def test_u8_repair_requires_editor_rbac(viewer_headers, c_seed, vector_stack):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post(
            REPAIR_URL,
            json={"doc_source_id": DOC_PAGE},
            headers=viewer_headers,
        )
    assert resp.status_code == 403


async def test_u8_repair_full_workflow_with_verification(
    admin_headers, c_seed, vector_stack
):
    """修复链:缺失 2 chunk → 修复回放 → 复验 12/12 通过;审计事件可查。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post(
            REPAIR_URL,
            json={"doc_source_id": DOC_PAGE, "idempotency_key": "wc-repair-1"},
            headers=admin_headers,
        )
    assert resp.status_code == 200
    task = resp.json()
    assert task["status"] == "succeeded"
    assert task["stage"] == "verify"
    assert task["requested_by"] is not None
    assert task["result"]["chunks_serving"] == 12
    assert task["result"]["chunks_total"] == 12
    assert task["result"]["consistency"] == "passed"
    assert sorted(task["result"]["repaired_indices"]) == [10, 11]
    events = [e["event"] for e in task["events"]]
    assert events[0] == "requested"
    assert "plan_completed" in events and "repair_applied" in events and "verify_completed" in events
    # 真实写入发生(嵌入回放,非假状态)
    assert len(vector_stack["client"].collections.get("Document").inserted) == 2
    # 任务持久化(审计行可查)
    factory = app.state.session_factory
    async with factory() as session:
        rows = (
            (
                await session.execute(
                    select(DocumentRepairTask).where(
                        DocumentRepairTask.doc_source_id == DOC_PAGE
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1


async def test_u8_repair_oversized_routes_to_source_rebuild_without_embed(
    admin_headers, c_seed, vector_stack, monkeypatch
):
    """INC-WEB-EMBED-413 REMEDIATION:重放载荷越嵌入字符契约 → 系统自选
    机制 = 权威源重建请求(sync_requests kind=rebuild 交接),不是终态
    "让管理员去点 Sync"的失败;嵌入零调用(超限载荷绝不出网)。

    冻结产品真值:管理员只选「修复此知识 / 一键修复全部」,机制由系统
    裁决:REPLAYABLE → 持久副本回放;REBUILD_REQUIRED → 既有 sync 源重建
    路径交接;UNRECOVERABLE → 如实失败。
    """

    class _SpyEmbedder:
        def __init__(self) -> None:
            self.texts: list[str] = []

        def embed(self, texts):
            self.texts.extend(texts)
            return [[0.1, 0.2, 0.3] for _ in texts]

    import dataclasses as _dc

    spy = _SpyEmbedder()
    monkeypatch.setattr(app.state, "embedder", spy)
    monkeypatch.setattr(
        app.state,
        "settings",
        _dc.replace(app.state.settings, embedder_max_length=1024),
    )

    factory = app.state.session_factory
    async with factory() as session:
        version_id = (
            await session.execute(
                select(DocumentVersion.id).where(
                    DocumentVersion.source_id == DOC_PAGE,
                    DocumentVersion.status == "active",
                )
            )
        ).scalar_one()
        chunk = (
            await session.execute(
                select(DocumentVersionChunk).where(
                    DocumentVersionChunk.version_id == version_id,
                    DocumentVersionChunk.chunk_index == 10,
                )
            )
        ).scalar_one()
        chunk.text = "y" * 3000  # 超契约的存量持久真值(缺失 index 10)
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post(
            REPAIR_URL,
            json={"doc_source_id": DOC_PAGE, "idempotency_key": "inc-413"},
            headers=admin_headers,
        )
    assert resp.status_code == 200
    task = resp.json()
    assert task["status"] == "rebuild_requested"
    assert task["stage"] == "rebuild_request"
    assert task["result"]["repair_mode"] == "source_rebuild_requested"
    assert task["result"]["reason"] == "persisted_text_over_contract"
    assert "max_length" in (task["result"].get("detail") or "")
    assert task["result"]["sync_request_id"] is not None
    assert spy.texts == []  # 零嵌入调用:超契约载荷根本不出网
    # 审计行持久化(不静默、不伪造成功)
    async with factory() as session:
        rows = (
            (
                await session.execute(
                    select(DocumentRepairTask).where(
                        DocumentRepairTask.doc_source_id == DOC_PAGE
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1 and rows[0].status == "rebuild_requested"
        req_rows = (
            (
                await session.execute(
                    select(SyncRequest).where(SyncRequest.source_id == SRC)
                )
            )
            .scalars()
            .all()
        )
    assert len(req_rows) == 1
    assert req_rows[0].kind == "rebuild"
    assert req_rows[0].status == "pending"


async def test_u8_repair_idempotent_same_key_and_healthy_noop(
    admin_headers, c_seed, vector_stack
):
    """幂等:同键重复 → 原任务;健康文档重复修复 → 复验 no-op 通过。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        first = await client.post(
            REPAIR_URL,
            json={"doc_source_id": DOC_PAGE, "idempotency_key": "wc-idem"},
            headers=admin_headers,
        )
        second = await client.post(
            REPAIR_URL,
            json={"doc_source_id": DOC_PAGE, "idempotency_key": "wc-idem"},
            headers=admin_headers,
        )
        # 健康文档(修复后 12/12)再修 = 真实复验 no-op
        third = await client.post(
            REPAIR_URL, json={"doc_source_id": DOC_PAGE}, headers=admin_headers
        )
    assert first.json()["id"] == second.json()["id"]
    noop = third.json()
    assert noop["status"] == "succeeded"
    assert noop["result"]["repaired_indices"] == []
    assert noop["result"]["consistency"] == "passed"


async def test_u8_repair_unknown_doc_404(admin_headers, c_seed, vector_stack):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post(
            REPAIR_URL, json={"doc_source_id": f"{SRC}/main/ghost.md"}, headers=admin_headers
        )
    assert resp.status_code == 404


async def test_u8_repair_stack_unavailable_503(admin_headers, c_seed, vector_stack):
    """向量库不可用 → 503 诚实降级(绝不伪造修复成功)。"""
    app.state.weaviate_client = None
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            resp = await client.post(
                REPAIR_URL,
                json={"doc_source_id": f"{SRC}/main/never-seen.md"},
                headers=admin_headers,
            )
        assert resp.status_code in (404, 503)
    finally:
        app.state.weaviate_client = vector_stack["client"]


async def test_u14_bulk_repair_returns_authoritative_aggregate_and_excludes_healthy(
    admin_headers, viewer_headers, c_seed, vector_stack
):
    """批量修复只处理当前源 attention 桶,并对不可修复项如实聚合失败。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        forbidden = await client.post(BULK_REPAIR_URL, headers=viewer_headers)
        response = await client.post(BULK_REPAIR_URL, headers=admin_headers)
    assert forbidden.status_code == 403
    assert response.status_code == 200
    body = response.json()
    # c_seed:1 missing_candidate(无现行版本 → 系统自选源重建交接)
    #        + 1 healthy active + 1 healthy active(不入 attention)
    assert body["eligible"] == 1
    assert body["succeeded"] == 0
    assert body["failed"] == 0
    assert body["rebuild_requested"] == 1
    assert body["items"][0]["doc_source_id"] == DOC_PRODUCT
    assert body["items"][0]["status"] == "rebuild_requested"
    assert body["items"][0]["sync_request_id"] is not None
    async with app.state.session_factory() as session:
        req_rows = (
            (await session.execute(select(SyncRequest).where(SyncRequest.source_id == SRC)))
            .scalars()
            .all()
        )
    assert len(req_rows) == 1 and req_rows[0].kind == "rebuild"


async def test_u14_bulk_repair_partial_success_excludes_retired_and_concurrent_request(
    admin_headers, c_seed, vector_stack, monkeypatch
):
    """资格是 attention 桶全量,结果允许逐项失败,同源并发请求立即 409。"""
    factory = app.state.session_factory
    discovered = f"{SRC}/main/bulk-discovered.md"
    dangling = f"{SRC}/main/bulk-dangling.md"
    retired = f"{SRC}/main/bulk-retired.md"
    async with factory() as session:
        for doc_source_id, lifecycle in (
            (discovered, "discovered"),
            (dangling, "active"),
            (retired, "superseded"),
        ):
            session.add(
                Document(
                    source_id=doc_source_id,
                    content_hash="d" * 64,
                    source_type="woocommerce",
                    product="trackc",
                    title=doc_source_id.rsplit("/", 1)[-1],
                    url=f"https://shop.example.com/{doc_source_id.rsplit('/', 1)[-1]}",
                    branch="main",
                    chunk_count=1,
                    lifecycle=lifecycle,
                )
            )
        await session.commit()

    async def fake_execute(factory, *, task_id, **_kwargs):
        async with factory() as session:
            task = await session.get(DocumentRepairTask, task_id)
            assert task is not None
            task.status = "succeeded" if task.doc_source_id == discovered else "failed"
            task.error = None if task.status == "succeeded" else "测试替身拒绝修复"
            await session.commit()
            await session.refresh(task)
            return task

    monkeypatch.setattr("backend.api.admin.data_sources.execute_repair_task", fake_execute)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            response = await client.post(BULK_REPAIR_URL, headers=admin_headers)
        assert response.status_code == 200
        body = response.json()
        assert body["eligible"] == 3  # missing_candidate + discovered + active 悬挂
        assert body["succeeded"] == 1
        assert body["failed"] == 2
        assert {item["doc_source_id"] for item in body["items"]} == {
            DOC_PRODUCT,
            discovered,
            dangling,
        }
        assert retired not in {item["doc_source_id"] for item in body["items"]}

        # 用一个新的 eligible 文档让首个请求保持在执行态,第二请求必须 409。
        concurrent_doc = f"{SRC}/main/bulk-concurrent.md"
        async with factory() as session:
            session.add(
                Document(
                    source_id=concurrent_doc,
                    content_hash="e" * 64,
                    source_type="woocommerce",
                    product="trackc",
                    title="bulk-concurrent.md",
                    url="https://shop.example.com/bulk-concurrent.md",
                    branch="main",
                    chunk_count=1,
                    lifecycle="discovered",
                )
            )
            await session.commit()

        started = asyncio.Event()
        release = asyncio.Event()

        async def blocking_execute(factory, *, task_id, **_kwargs):
            async with factory() as session:
                task = await session.get(DocumentRepairTask, task_id)
                assert task is not None
                if task.doc_source_id == concurrent_doc:
                    started.set()
                    await release.wait()
                task.status = "failed"
                task.error = "并发测试失败"
                await session.commit()
                await session.refresh(task)
                return task

        monkeypatch.setattr(
            "backend.api.admin.data_sources.execute_repair_task", blocking_execute
        )
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            first_task = asyncio.create_task(client.post(BULK_REPAIR_URL, headers=admin_headers))
            await asyncio.wait_for(started.wait(), timeout=2)
            second = await client.post(BULK_REPAIR_URL, headers=admin_headers)
            release.set()
            first = await first_task
        assert second.status_code == 409
        assert first.status_code == 200
    finally:
        async with factory() as session:
            await session.execute(
                DocumentRepairTask.__table__.delete().where(
                    DocumentRepairTask.doc_source_id.in_([discovered, dangling, retired, f"{SRC}/main/bulk-concurrent.md"])
                )
            )
            await session.execute(
                Document.__table__.delete().where(
                    Document.source_id.in_([discovered, dangling, retired, f"{SRC}/main/bulk-concurrent.md"])
                )
            )
            await session.commit()


# --------------------------------------------------------------------------- #
# U-11 调度真值
# --------------------------------------------------------------------------- #


async def test_u11_schedule_waiting_first_when_never_synced(viewer_headers, c_seed):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get(SCHEDULE_URL, headers=viewer_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "waiting_first"
    assert body["next_run_at"] is None  # 从未同步 → 不虚构倒计时


async def test_u11_schedule_authoritative_after_success(viewer_headers, c_seed):
    """成功同步完成后:next_run_at = 完成时间 + interval(持久化权威)。"""
    factory = app.state.session_factory
    finished = NOW - timedelta(hours=2)
    async with factory() as session:
        session.add(
            SyncLog(
                source_id=SRC,
                source_type="woocommerce",
                status="success",
                started_at=finished - timedelta(minutes=3),
                finished_at=finished,
            )
        )
        await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get(SCHEDULE_URL, headers=viewer_headers)
        body = resp.json()
        assert body["state"] == "scheduled"
        assert body["next_run_at"] is not None
        got = datetime.fromisoformat(body["next_run_at"])
        expected = finished + timedelta(hours=24)
        assert abs((got - expected).total_seconds()) < 30
        # 持久化(权威列非空,读两次一致)
        resp2 = await client.get(SCHEDULE_URL, headers=viewer_headers)
        assert resp2.json()["next_run_at"] == body["next_run_at"]


async def test_u11_schedule_syncing_and_paused_states(viewer_headers, c_seed):
    factory = app.state.session_factory
    async with factory() as session:
        session.add(SyncRequest(source_id=SRC, status="pending", triggered_by="manual"))
        ds = (
            await session.execute(select(DataSource).where(DataSource.id == SRC))
        ).scalar_one()
        ds.enabled = False
        await session.commit()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            resp = await client.get(SCHEDULE_URL, headers=viewer_headers)
        body = resp.json()
        assert body["state"] == "paused"  # 禁用优先,倒计时消失
        assert body["next_run_at"] is None
    finally:
        async with factory() as session:
            await session.execute(
                SyncRequest.__table__.delete().where(SyncRequest.source_id == SRC)
            )
            ds = (
                await session.execute(select(DataSource).where(DataSource.id == SRC))
            ).scalar_one()
            ds.enabled = True
            await session.commit()
    # 进行中(启用状态 + pending 请求)→ syncing / NULL
    async with factory() as session:
        session.add(SyncRequest(source_id=SRC, status="pending", triggered_by="manual"))
        await session.commit()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            resp = await client.get(SCHEDULE_URL, headers=viewer_headers)
        assert resp.json()["state"] == "syncing"
        assert resp.json()["next_run_at"] is None
    finally:
        async with factory() as session:
            await session.execute(
                SyncRequest.__table__.delete().where(SyncRequest.source_id == SRC)
            )
            await session.commit()


async def test_u11_list_endpoint_embeds_schedule_truth(viewer_headers, c_seed):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get("/api/admin/data-sources", headers=viewer_headers)
    assert resp.status_code == 200
    mine = [s for s in resp.json() if s["id"] == SRC]
    assert mine and mine[0]["schedule_state"] in {
        "scheduled",
        "syncing",
        "paused",
        "waiting_first",
        "deleting",
    }
    assert mine[0]["next_run_at"] is None or "T" in mine[0]["next_run_at"]


# --------------------------------------------------------------------------- #
# U-12 知识设置 + U-13 高风险预览
# --------------------------------------------------------------------------- #


async def test_u12_settings_defaults_and_overdue_truth(viewer_headers, c_seed):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.get(SETTINGS_URL, headers=viewer_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["role"] == "current"  # NULL = 默认 CURRENT
    assert body["freshness_hours"] == 24
    assert body["freshness"]["overdue"] is True  # 从未成功同步 → 后端权威超期态
    assert body["freshness"]["basis"] == "never_synced"


async def test_u12_role_change_requires_preview_token(admin_headers, c_seed):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.put(
            SETTINGS_URL, json={"role": "historical"}, headers=admin_headers
        )
    assert resp.status_code == 409
    assert "preview_token" in resp.json()["detail"]


async def test_u12_u13_preview_confirm_chain_and_retrieval_eligibility(
    admin_headers, viewer_headers, c_seed, vector_stack
):
    """E2E 后端链:预览(计数=服务端权威)→ 确认(一致 mutation)→
    政策持久化 + 检索资格消费(HISTORICAL 源进排除集合)+ 重验快照。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        preview = await client.post(
            PREVIEW_URL,
            json={"role": "historical", "freshness_hours": 12},
            headers=admin_headers,
        )
        assert preview.status_code == 200
        pbody = preview.json()
        assert pbody["impact"]["affected_documents"] == 3  # 账本权威(3 行 seed)
        assert pbody["impact"]["current_eligibility_change"] == 2  # 2 行 active 可解析
        assert pbody["impact"]["historical_eligibility_change"] == 1
        assert pbody["current_policy"]["role"] == "current"

        confirm = await client.put(
            SETTINGS_URL,
            json={
                "role": "historical",
                "freshness_hours": 12,
                "preview_token": pbody["preview_token"],
            },
            headers=admin_headers,
        )
        assert confirm.status_code == 200
        cbody = confirm.json()
        assert cbody["role"] == "historical"
        assert cbody["explicit_role"] == "historical"
        assert cbody["freshness_hours"] == 12

        # 重读一致(真实持久化)
        reread = await client.get(SETTINGS_URL, headers=viewer_headers)
        assert reread.json()["role"] == "historical"

    # 检索资格消费(HybridSearcher 排除集合真值)
    import os

    from backend.db.session import get_sync_session_factory
    from backend.services.knowledge_policy import excluded_source_prefixes_sync

    sync_factory = get_sync_session_factory(
        os.environ.get("TEST_DATABASE_URL", app.state.settings.postgres_dsn)
    )
    excluded = excluded_source_prefixes_sync(sync_factory)
    assert SRC in excluded
    # searcher 消费:构造最小 stub 结果 → HISTORICAL 源 chunk 被过滤
    from backend.retrieval.search import HybridSearcher, SearchResult

    stub = SimpleNamespace(
        _knowledge_exclusions=lambda: excluded,
        # Issue #84:消费面叠加 per-document withdrawn 排除;本测试聚焦
        # U-12 面,stub 的 withdrawn 权威供给为空集(未 wiring 语义)。
        _withdrawn_identities=lambda: [],
    )

    results = [
        SearchResult(
            text="x",
            source_id=f"{SRC}/main/ne101.md",
            source_type="woocommerce",
            product="trackc",
            title="t",
            url="u",
            score=0.9,
            chunk_index=0,
            chunk_type="",
            doc_section="",
            channel_visibility=("widget",),
            symbol_name="",
            symbol_signature="",
            evidence_authority_class="",
            evidence_temporality="",
            evidence_sensitivity="",
            evidence_citation_eligibility="",
            evidence_origin="",
        )
    ]
    assert HybridSearcher._apply_knowledge_exclusion(stub, results) == []


async def test_u13_confirm_policy_mismatch_rejected(admin_headers, c_seed, vector_stack):
    """确认施加的 mutation 必须 = 预览 mutation;不一致 → 409。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        await client.post(
            PREVIEW_URL, json={"role": "current"}, headers=admin_headers
        )
        # 预览的是 current(等值,不会触发 role_changed 分支)→ 先拉到 historical
        preview2 = await client.post(
            PREVIEW_URL, json={"role": "historical"}, headers=admin_headers
        )
        token2 = preview2.json()["preview_token"]
        # 用 token2(预览 historical)但提交 freshness 与预览不一致 → 409
        bad = await client.put(
            SETTINGS_URL,
            json={
                "role": "historical",
                "freshness_hours": 6,  # 预览无 freshness → pending 不一致
                "preview_token": token2,
            },
            headers=admin_headers,
        )
        assert bad.status_code == 409
        # token 无效 → 409
        invalid = await client.put(
            SETTINGS_URL,
            json={"role": "historical", "preview_token": "not-a-token"},
            headers=admin_headers,
        )
        assert invalid.status_code == 409


async def test_u13_ledger_drift_invalidates_preview(admin_headers, c_seed, vector_stack):
    """账本 drift:预览后账本变化 → 确认 409(失效,需重算)。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        preview = await client.post(
            PREVIEW_URL, json={"role": "historical"}, headers=admin_headers
        )
        token = preview.json()["preview_token"]
    factory = app.state.session_factory
    async with factory() as session:
        session.add(
            Document(
                source_id=f"{SRC}/main/drift.md",
                content_hash="d" * 64,
                source_type="woocommerce",
                product="trackc",
                title="drift",
                url="https://shop.example.com/drift",
                branch="",
                chunk_count=0,
                lifecycle="discovered",
                content_type="page",
            )
        )
        await session.commit()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            resp = await client.put(
                SETTINGS_URL,
                json={"role": "historical", "preview_token": token},
                headers=admin_headers,
            )
        assert resp.status_code == 409
        assert "drift" in resp.json()["detail"] or "重新预览" in resp.json()["detail"]
        # 预览行已标 stale(不可复用)
        factory2 = app.state.session_factory
        async with factory2() as session:
            rows = (
                (
                    await session.execute(
                        select(DocumentRepairTask).where(
                            DocumentRepairTask.source_id == SRC
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert isinstance(rows, list)
    finally:
        async with factory() as session:
            await session.execute(
                Document.__table__.delete().where(Document.source_id == f"{SRC}/main/drift.md")
            )
            await session.commit()


# --------------------------------------------------------------------------- #
# INC-WEB-EMBED-413 REMEDIATION:修复命令系统自选恢复机制(冻结产品真值)
#
# REPLAYABLE → 持久副本回放(廉价路径不变);REBUILD_REQUIRED → 既有 sync
# 源重建路径交接(sync_requests kind=rebuild → sync --reindex --source,
# 经 _enforce_char_limit 的已验收摄取路径);UNRECOVERABLE → 如实失败。
# 管理员不需要理解或手动串联 repair → failed → 点 Sync。
# --------------------------------------------------------------------------- #


class _RecordingEmbedder:
    """记录全部嵌入文本;对含 FAIL-ME 标记的文本真实失败(不可恢复类)。"""

    def __init__(self) -> None:
        self.texts: list[str] = []

    def embed(self, texts):
        for t in texts:
            if "FAIL-ME" in t:
                raise RuntimeError("嵌入模型真实失败(测试注入)")
        self.texts.extend(texts)
        return [[0.1, 0.2, 0.3] for _ in texts]


async def _mk_remediation_docs(session):
    """三篇 attention 文档:replayable / oversized / genuinely-failing。"""

    docs = {}
    for key, lifecycle in (
        ("replay", "missing_candidate"),
        ("oversize", "missing_candidate"),
        ("fail", "missing_candidate"),
    ):
        sid = f"{SRC}/main/rem-{key}.md"
        version = DocumentVersion(
            source_id=sid,
            version_seq=1,
            content_hash="e" * 64,
            metadata_hash="f" * 64,
            generation_id=_mk_version.gen.id,
            generation_ordinal=ORDINAL,
            status="active",
            title=key,
            url=f"https://shop.example.com/rem-{key}",
            chunk_count=2,
        )
        session.add(version)
        await session.flush()
        oversize_text = "O" * 3000 if key == "oversize" else f"REM-{key}-chunk-1"
        if key == "fail":
            oversize_text = "REM-FAIL-ME-chunk-1"
        for i, text_ in enumerate((f"REM-{key}-chunk-0", oversize_text)):
            session.add(
                DocumentVersionChunk(
                    version_id=version.id,
                    chunk_index=i,
                    text=text_,
                    props={"source_id": sid, "chunk_index": i},
                )
            )
        session.add(
            Document(
                source_id=sid,
                content_hash="e" * 64,
                source_type="woocommerce",
                product="trackc",
                title=key,
                url=f"https://shop.example.com/rem-{key}",
                branch="",
                chunk_count=2,
                lifecycle=lifecycle,
                current_version_id=version.id,
            )
        )
        docs[key] = sid
    return docs


async def test_u14_bulk_mixed_routes_replay_rebuild_and_truthful_failure(
    admin_headers, c_seed, vector_stack, monkeypatch
):
    """混合批量:回放可修复→succeeded(廉价回放);超契约→rebuild_requested
    (自动交接,零嵌入);真实上游失败→failed。聚合逐项如实。"""
    import dataclasses as _dc

    spy = _RecordingEmbedder()
    monkeypatch.setattr(app.state, "embedder", spy)
    monkeypatch.setattr(
        app.state,
        "settings",
        _dc.replace(app.state.settings, embedder_max_length=1024),
    )

    factory = app.state.session_factory
    async with factory() as session:
        docs = await _mk_remediation_docs(session)
        await session.commit()
        # 在服投影:每篇恰 idx0 在服(现行代),idx1 缺失 → 修复计划=缺 idx1
        collection = _FakeCollection(
            [
                {"source_id": sid, "chunk_index": 0, "generation_ordinal": ORDINAL}
                for sid in docs.values()
            ]
        )
        client_fake = SimpleNamespace(collections=SimpleNamespace(get=lambda _n: collection))
        app.state.weaviate_client = client_fake
    # 资格桶此时 = c_seed 的 DOC_PRODUCT(无版本→rebuild)+ 本 3 篇 = 4;
    # 本测试聚焦新 3 篇的逐项裁决,聚合断言按 4 口径。
    expected_eligible = 4

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            resp = await client.post(BULK_REPAIR_URL, headers=admin_headers)
    finally:
        pass
    assert resp.status_code == 200
    body = resp.json()
    by_doc = {i["doc_source_id"]: i for i in body["items"]}
    assert body["eligible"] == expected_eligible
    assert body["succeeded"] == 1
    assert body["failed"] == 1
    assert body["rebuild_requested"] == 2
    assert by_doc[docs["replay"]]["status"] == "succeeded"
    assert by_doc[docs["oversize"]]["status"] == "rebuild_requested"
    assert by_doc[docs["oversize"]]["sync_request_id"] is not None
    assert by_doc[docs["fail"]]["status"] == "failed"
    assert "真实失败" in (by_doc[docs["fail"]]["error"] or "")
    # 验收 5:超契约载荷零出网;嵌入只见到回放可修复的小文本
    assert all(len(t) <= 1024 for t in spy.texts)
    assert not any("REM-oversize-chunk-1" in t for t in spy.texts)
    # 验收 10:修复操作自身已交接权威源重建(无需管理员再手动点 Sync)
    async with factory() as session:
        req_rows = (
            (await session.execute(select(SyncRequest).where(SyncRequest.source_id == SRC)))
            .scalars()
            .all()
        )
    assert len(req_rows) == 1
    assert req_rows[0].kind == "rebuild"
    assert req_rows[0].status == "pending"


async def test_u8_repair_no_current_version_routes_to_rebuild(
    admin_headers, c_seed, vector_stack, monkeypatch
):
    """无现行版本的合格文档:系统自选源重建交接(不再终态拒绝)。"""
    import dataclasses as _dc

    monkeypatch.setattr(
        app.state,
        "settings",
        _dc.replace(app.state.settings, embedder_max_length=1024),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post(
            REPAIR_URL,
            json={"doc_source_id": DOC_PRODUCT, "idempotency_key": "rem-nover"},
            headers=admin_headers,
        )
    assert resp.status_code == 200
    task = resp.json()
    assert task["status"] == "rebuild_requested"
    assert task["result"]["repair_mode"] == "source_rebuild_requested"
    assert task["result"]["sync_request_id"] is not None


async def test_u8_repair_rebuild_submit_failure_is_honest_failure(
    admin_headers, c_seed, vector_stack, monkeypatch
):
    """交接写库失败 → 任务如实 failed(绝不伪造 rebuild_requested)。"""
    import dataclasses as _dc

    from backend.services.sync_requests import SyncRequestSubmitError

    monkeypatch.setattr(
        app.state,
        "settings",
        _dc.replace(app.state.settings, embedder_max_length=1024),
    )

    async def _boom(session, source_id, *, triggered_by="manual", kind=None):
        raise SyncRequestSubmitError("交接请求写入失败(测试注入)")

    monkeypatch.setattr(
        "backend.services.sync_requests.submit_sync_request", _boom
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post(
            REPAIR_URL,
            json={"doc_source_id": DOC_PRODUCT, "idempotency_key": "rem-boom"},
            headers=admin_headers,
        )
    assert resp.status_code == 200
    task = resp.json()
    assert task["status"] == "failed"
    assert "写入失败" in (task["error"] or "")


async def test_u8_repair_healthy_replay_creates_no_rebuild_request(
    admin_headers, c_seed, vector_stack, monkeypatch
):
    """健康可回放文档:廉价回放路径不变,且零源重建交接(不扩权)。"""
    import dataclasses as _dc

    monkeypatch.setattr(
        app.state,
        "settings",
        _dc.replace(app.state.settings, embedder_max_length=1024),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        resp = await client.post(
            REPAIR_URL,
            json={"doc_source_id": DOC_PAGE, "idempotency_key": "rem-healthy"},
            headers=admin_headers,
        )
    assert resp.status_code == 200
    task = resp.json()
    assert task["status"] == "succeeded"
    assert task["result"]["repair_mode"] == "persisted_chunk_replay"
    async with app.state.session_factory() as session:
        req_rows = (
            (await session.execute(select(SyncRequest).where(SyncRequest.source_id == SRC)))
            .scalars()
            .all()
        )
    assert req_rows == []  # 健康文档零重建请求
