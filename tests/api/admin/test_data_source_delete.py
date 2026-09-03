"""#18 非阻塞数据源删除生命周期测试(weaviate 全 mock,不触真实库)。

冻结契约:删除受理与执行分离的 durable lifecycle
- G001 删除受理 = 202 + 持久 DELETE_REQUESTED(API 不等待 purge,
  受理阶段 purge 零调用);
- G002 执行完成后配置行+账本行按前缀清理(无 tombstone),purge 收到
  正确前缀与账本;
- G005 前缀边界安全(afp001-a 不得波及 afp001-ab);
- G006 purge 失败 → DELETE_FAILED + lifecycle_error,配置与账本原样
  保留可重试;retry 受理 → 执行成功 → 行移除;
- G007 重复删除点击幂等(两次 202,状态不退化,purge 只执行一次)。
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import DataSource, Document, User
from backend.main import app

pytestmark = pytest.mark.asyncio(loop_scope="session")

_USER_EMAIL = "afp001-delete@test.com"


@pytest_asyncio.fixture(loop_scope="session")
async def del_seed():
    factory = app.state.session_factory
    async with factory() as session:
        await session.execute(User.__table__.delete().where(User.email == _USER_EMAIL))
        await session.execute(
            DataSource.__table__.delete().where(DataSource.id.in_(["afp001-a", "afp001-b"]))
        )
        await session.execute(
            Document.__table__.delete().where(Document.source_id.like("afp001-%"))
        )
        await session.commit()

    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email=_USER_EMAIL,
                role="admin",
                password_hash=hash_password("pass"),
            )
        )
        session.add(
            DataSource(
                id="afp001-a",
                type="github",
                product="ne101",
                enabled=True,
                config={"repo_url": "https://example.com/a.git"},
                sync_interval="24h",
            )
        )
        session.add(
            DataSource(
                id="afp001-b",
                type="github",
                product="ne301",
                enabled=True,
                config={"repo_url": "https://example.com/b.git"},
                sync_interval="24h",
            )
        )
        for sid in ("afp001-a/doc1", "afp001-a/doc2", "afp001-b/doc1"):
            session.add(
                Document(
                    content_hash=uuid.uuid4().hex,
                    source_id=sid,
                    source_type="github",
                    product="x",
                    title=sid,
                    url="https://example.com",
                    metadata_={},
                    branch="",
                    chunk_count=3,
                )
            )
        await session.commit()

    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}

    async with factory() as session:
        await session.execute(User.__table__.delete().where(User.email == _USER_EMAIL))
        await session.execute(
            DataSource.__table__.delete().where(DataSource.id.in_(["afp001-a", "afp001-b"]))
        )
        await session.execute(
            Document.__table__.delete().where(Document.source_id.like("afp001-%"))
        )
        await session.commit()


async def _doc_prefix_exists(prefix: str) -> bool:
    factory = app.state.session_factory
    from sqlalchemy import func

    async with factory() as session:
        n = (
            await session.execute(
                select(func.count())
                .select_from(Document)
                .where(Document.source_id.like(f"{prefix}/%"))
            )
        ).scalar()
    return bool(n)


async def _lifecycle_of(source_id: str) -> tuple[str | None, str | None]:
    """返回 (lifecycle_state, lifecycle_error),行不存在返回 (None, None)。"""
    factory = app.state.session_factory
    async with factory() as session:
        ds = (
            await session.execute(select(DataSource).where(DataSource.id == source_id))
        ).scalar_one_or_none()
        if ds is None:
            return None, None
        return ds.lifecycle_state, ds.lifecycle_error


async def _process_deletions() -> list[str]:
    """驱动后台删除 sweep(测试环境无 lifespan worker,手动推进)。"""
    from backend.services.source_deletion import process_pending_deletions

    settings = app.state.settings
    return await process_pending_deletions(
        app.state.session_factory, settings.weaviate_url, settings.weaviate_class_name
    )


@pytest.fixture
def fake_purge(monkeypatch):
    """记录 purge 调用参数;可注入异常。"""
    calls: list[dict] = []

    def _fake(weaviate_url, class_name, prefix, ledger):
        calls.append(
            {
                "weaviate_url": weaviate_url,
                "class_name": class_name,
                "prefix": prefix,
                "ledger": list(ledger),
            }
        )
        return {"ledger_chunks": sum(cc for _, cc in calls[-1]["ledger"]), "orphans": 0}

    monkeypatch.setattr(
        "backend.services.source_deletion.purge_source_corpus_sync", _fake
    )
    return calls


async def test_delete_acceptance_is_nonblocking_and_durable(del_seed, fake_purge):
    """G001:202 受理即返回,purge 零调用,行保留且 DELETE_REQUESTED 持久化。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete("/api/admin/data-sources/afp001-a", headers=del_seed)
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "delete_requested"
    assert body["accepted"] is True
    # 受理阶段绝不执行 purge(API 不等待向量清理)
    assert fake_purge == []
    # 行保留,状态持久化(刷新页面即可恢复),账本原样
    state, error = await _lifecycle_of("afp001-a")
    assert state == "delete_requested"
    assert error is None
    assert await _doc_prefix_exists("afp001-a")


async def test_delete_lifecycle_completes_and_removes_rows(del_seed, fake_purge):
    """G002:受理 → sweep 执行 → 配置行+账本行移除;purge 参数正确。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete("/api/admin/data-sources/afp001-a", headers=del_seed)
    assert resp.status_code == 202

    processed = await _process_deletions()
    assert processed == ["afp001-a"]
    factory = app.state.session_factory
    async with factory() as session:
        gone = (
            await session.execute(select(DataSource).where(DataSource.id == "afp001-a"))
        ).scalar_one_or_none()
        assert gone is None  # 成功删除,无 tombstone
    assert not await _doc_prefix_exists("afp001-a")
    # purge 参数:类名与前缀正确,账本含该源 2 篇(每篇 3 chunk)
    assert len(fake_purge) == 1
    call = fake_purge[0]
    assert call["class_name"] == app.state.settings.weaviate_class_name
    assert call["prefix"] == "afp001-a"
    assert sorted(call["ledger"]) == [("afp001-a/doc1", 3), ("afp001-a/doc2", 3)]


async def test_delete_keeps_unrelated_source(del_seed, fake_purge):
    """G005:删除 afp001-a 全流程不得波及 afp001-b 的配置与账本。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.delete("/api/admin/data-sources/afp001-a", headers=del_seed)
    await _process_deletions()
    state_b, _ = await _lifecycle_of("afp001-b")
    assert state_b is None  # B 保持正常态(NULL=active)
    assert await _doc_prefix_exists("afp001-b")


async def test_delete_failure_marks_failed_and_retry_succeeds(del_seed, monkeypatch):
    """G006:purge 失败 → DELETE_FAILED + 错误持久化,行/账本保留;
    retry 受理清错误,执行成功后行移除。"""

    calls: list[str] = []

    def _boom(weaviate_url, class_name, prefix, ledger):
        calls.append(prefix)
        raise RuntimeError("weaviate down")

    monkeypatch.setattr(
        "backend.services.source_deletion.purge_source_corpus_sync", _boom
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        accept = await client.delete("/api/admin/data-sources/afp001-a", headers=del_seed)
    assert accept.status_code == 202
    processed = await _process_deletions()
    assert processed == ["afp001-a"]  # 认领了,但终态是失败

    state, error = await _lifecycle_of("afp001-a")
    assert state == "delete_failed"
    assert error is not None and "weaviate down" in error
    assert await _doc_prefix_exists("afp001-a")  # 配置+账本保留可重试

    # retry:DELETE 端点直接重发(allowed_from 含 delete_failed)
    monkeypatch.setattr(
        "backend.services.source_deletion.purge_source_corpus_sync",
        lambda *a, **k: {"ledger_docs": 2, "orphans": 0, "residue": 0},
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        retried = await client.delete("/api/admin/data-sources/afp001-a", headers=del_seed)
    assert retried.status_code == 202
    state, error = await _lifecycle_of("afp001-a")
    assert state == "delete_requested" and error is None
    assert await _process_deletions() == ["afp001-a"]
    assert await _lifecycle_of("afp001-a") == (None, None)  # 行已移除
    assert not await _doc_prefix_exists("afp001-a")


async def test_delete_retry_endpoint_only_from_failed(del_seed, fake_purge):
    """专用 retry 端点:DELETE_FAILED → 202;正常态 ACTIVE → 409。"""
    # 先造一个 DELETE_FAILED 行
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.delete("/api/admin/data-sources/afp001-a", headers=del_seed)
    factory = app.state.session_factory
    from sqlalchemy import update

    async with factory() as session:
        await session.execute(
            update(DataSource)
            .where(DataSource.id == "afp001-a")
            .values(lifecycle_state="delete_failed", lifecycle_error="boom")
        )
        await session.commit()

    # ACTIVE 源走 retry 端点 → 409(没有失败可重试)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        wrong = await client.post("/api/admin/data-sources/afp001-b/delete/retry", headers=del_seed)
    assert wrong.status_code == 409

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ok = await client.post("/api/admin/data-sources/afp001-a/delete/retry", headers=del_seed)
    assert ok.status_code == 202
    assert ok.json()["status"] == "delete_requested"
    state, error = await _lifecycle_of("afp001-a")
    assert state == "delete_requested" and error is None


async def test_repeated_delete_click_is_idempotent(del_seed, fake_purge):
    """G007:重复点击删除 → 两次 202(第二次幂等 accepted=False),
    状态不退化;最终 sweep 只执行一次 purge、行正确移除。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.delete("/api/admin/data-sources/afp001-a", headers=del_seed)
        second = await client.delete("/api/admin/data-sources/afp001-a", headers=del_seed)
    assert first.status_code == 202
    assert second.status_code == 202
    assert second.json()["accepted"] is False
    assert second.json()["status"] == "delete_requested"
    assert fake_purge == []  # 幂等受理不重复执行

    assert await _process_deletions() == ["afp001-a"]
    # 全部清理后第三次删除 → 404
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        third = await client.delete("/api/admin/data-sources/afp001-a", headers=del_seed)
    assert third.status_code == 404


async def test_delete_missing_source_404(del_seed, fake_purge):
    """删除不存在的源 → 404。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete("/api/admin/data-sources/no-such-src", headers=del_seed)
    assert resp.status_code == 404


async def test_list_exposes_lifecycle_fields(del_seed, fake_purge):
    """列表端点透出 lifecycle 字段:受理后可见(刷新恢复状态的基础)。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.delete("/api/admin/data-sources/afp001-a", headers=del_seed)
        listed = (
            await client.get("/api/admin/data-sources", headers=del_seed)
        ).json()
    row = next(s for s in listed if s["id"] == "afp001-a")
    assert row["lifecycle_state"] == "delete_requested"
    assert row["lifecycle_error"] is None
    assert row["lifecycle_since"] is not None


def test_purge_prefix_boundary_safe(monkeypatch):
    """G005/G2(向量面):purge 只按确定性 UUID 点删 + 边界内对象 UUID 兜底;
    afp001-ab / 相似前缀源对象必须幸存;删除原语不得是 TEXT 属性过滤。"""
    import re as _re

    from backend.pipeline.ingest import _deterministic_uuid
    from backend.services import source_deletion as sd

    ledger = [("afp001-a/doc1", 2), ("afp001-a/doc2", 2)]
    sibling_uuids = [_deterministic_uuid("afp001-ab/doc1", i) for i in range(2)]
    orphan_u = str(uuid.uuid4())

    class _FakeItem:
        def __init__(self, uuid, sid):
            self.uuid = uuid
            self.properties = {"source_id": sid}

    OBJECTS: dict[str, object] = {}
    for sid, cc in ledger:
        for i in range(cc):
            u = _deterministic_uuid(sid, i)
            OBJECTS[u] = _FakeItem(u, sid)
    for u in sibling_uuids:
        OBJECTS[u] = _FakeItem(u, "afp001-ab/doc1")
    OBJECTS[orphan_u] = _FakeItem(orphan_u, "afp001-a/ghost")

    delete_many_filters: list = []
    deleted_by_id: list[str] = []

    class _FakeData:
        def delete_many(self, where):
            # 模拟真实删除:从过滤对象中解析 UUID(repr 含值),逐个移除
            delete_many_filters.append(where)
            for u in _re.findall(
                r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", str(where)
            ):
                OBJECTS.pop(u, None)

        def delete_by_id(self, uuid):
            deleted_by_id.append(str(uuid))
            OBJECTS.pop(str(uuid), None)

    class _FakeCollection:
        data = _FakeData()

        def iterator(self, return_properties=None):
            return iter(list(OBJECTS.values()))

    class _FakeCollections:
        def __init__(self, coll):
            self._coll = coll

        def get(self, name):
            return self._coll

    collection = _FakeCollection()

    class _FakeClient:
        collections = _FakeCollections(collection)

        def close(self):
            return None

    monkeypatch.setattr(sd.weaviate, "connect_to_local", lambda host, port, **k: _FakeClient())
    stats = sd.purge_source_corpus_sync("http://localhost:8080", "Document", "afp001-a", ledger)

    # Phase 1 确实发生(by_id 过滤,而非 TEXT 属性过滤)
    assert len(delete_many_filters) >= 1
    # 过滤器中出现的任何 UUID 都必须属于 A 源(不得夹带兄弟源)
    for f in delete_many_filters:
        for u in _re.findall(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", str(f)
        ):
            assert u in {(_deterministic_uuid(sid, i)) for sid, cc in ledger for i in range(cc)}, u
    # 边界:孤儿兜底只清边界内 UUID,afp001-ab 幸存
    assert orphan_u in deleted_by_id
    for u in sibling_uuids:
        assert u in OBJECTS, "兄弟源对象被误删"
    # 验证段通过:残留 0
    assert stats["orphans"] >= 1 and stats["residue"] == 0
