"""AFP-001 数据源删除生命周期单元测试(weaviate 全 mock,不触真实库)。

合同:删除数据源 ⇒ 该源独占知识退出访客检索:
- G001 源删除成功(配置行消失);
- G002 账本(documents)按前缀清理;
- G005 前缀边界安全(afp001-a 不得波及 afp001-ab);
- G006 向量清理失败 → 可观察错误,配置与账本原样保留(可重试);
- G007 重复删除安全(再次 DELETE → 404;purge 幂等可重复)。
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
            DataSource.__table__.delete().where(
                DataSource.id.in_(["afp001-a", "afp001-b"])
            )
        )
        await session.execute(
            Document.__table__.delete().where(
                Document.source_id.like("afp001-%")
            )
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
            DataSource.__table__.delete().where(
                DataSource.id.in_(["afp001-a", "afp001-b"])
            )
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


@pytest.fixture
def fake_purge(monkeypatch):
    """记录 purge 调用参数;可注入异常。"""
    calls: list[dict] = []

    def _fake(weaviate_url, class_name, prefix, ledger):
        calls.append(
            {"weaviate_url": weaviate_url, "class_name": class_name,
             "prefix": prefix, "ledger": list(ledger)}
        )
        return {"ledger_chunks": sum(cc for _, cc in calls[-1]["ledger"]), "orphans": 0}

    monkeypatch.setattr(
        "backend.api.admin.data_sources._purge_source_corpus_sync", _fake
    )
    return calls


async def test_delete_source_purges_corpus_and_rows(del_seed, fake_purge):
    """G001/G002:删除成功 → 配置行+账本行按前缀清理;purge 收到正确前缀与账本。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(
            "/api/admin/data-sources/afp001-a", headers=del_seed
        )
    assert resp.status_code == 204
    factory = app.state.session_factory
    async with factory() as session:
        gone = (
            await session.execute(select(DataSource).where(DataSource.id == "afp001-a"))
        ).scalar_one_or_none()
        assert gone is None
    assert not await _doc_prefix_exists("afp001-a")
    # purge 参数:类名与前缀正确,账本含该源 2 篇(每篇 3 chunk)
    assert len(fake_purge) == 1
    call = fake_purge[0]
    assert call["class_name"] == app.state.settings.weaviate_class_name
    assert call["prefix"] == "afp001-a"
    assert sorted(call["ledger"]) == [("afp001-a/doc1", 3), ("afp001-a/doc2", 3)]


async def test_delete_source_keeps_unrelated_source(del_seed, fake_purge):
    """G005:删除 afp001-a 不得波及 afp001-b 的配置与账本。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.delete("/api/admin/data-sources/afp001-a", headers=del_seed)
    factory = app.state.session_factory
    async with factory() as session:
        keep = (
            await session.execute(select(DataSource).where(DataSource.id == "afp001-b"))
        ).scalar_one_or_none()
        assert keep is not None
    assert await _doc_prefix_exists("afp001-b")


async def test_delete_failure_is_observable_and_preserves_state(del_seed, monkeypatch):
    """G006:向量清理失败 → 错误可观察(非 2xx),配置与账本原样保留可重试。"""
    def _boom(*a, **k):
        raise RuntimeError("weaviate down")

    monkeypatch.setattr(
        "backend.api.admin.data_sources._purge_source_corpus_sync", _boom
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete(
            "/api/admin/data-sources/afp001-a", headers=del_seed
        )
    assert resp.status_code >= 500
    assert "weaviate down" in resp.text
    factory = app.state.session_factory
    async with factory() as session:
        keep = (
            await session.execute(select(DataSource).where(DataSource.id == "afp001-a"))
        ).scalar_one_or_none()
        assert keep is not None  # 配置保留(可重试),绝不假报成功
    assert await _doc_prefix_exists("afp001-a")


async def test_delete_missing_source_404(del_seed, fake_purge):
    """G007:重复删除 → 第二次 404(第一次已删干净);purge 幂等由实现保证。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.delete(
            "/api/admin/data-sources/afp001-a", headers=del_seed
        )
        second = await client.delete(
            "/api/admin/data-sources/afp001-a", headers=del_seed
        )
    assert first.status_code == 204
    assert second.status_code == 404


def test_purge_prefix_boundary_safe(monkeypatch):
    """G005(向量面):purge 只清 `prefix/` 边界内对象;afp001-ab 不受波及。"""
    import backend.api.admin.data_sources as ds_mod

    equal_calls: list = []
    deleted_by_id: list[str] = []

    class _FakeData:
        def delete_many(self, where):
            equal_calls.append(where)
            return None

        def delete_by_id(self, uuid):
            deleted_by_id.append(str(uuid))
            return None

    class _FakeItem:
        def __init__(self, uuid, sid):
            self.uuid = uuid
            self.properties = {"source_id": sid}

    class _FakeCollection:
        def iterator(self, return_properties=None):
            return iter(
                [
                    _FakeItem("u-own-1", "afp001-a/doc1"),
                    _FakeItem("u-own-2", "afp001-a/doc2"),
                    _FakeItem("u-other", "afp001-ab/doc1"),  # 相似前缀,必须幸存
                ]
            )

        data = _FakeData()

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

    monkeypatch.setattr(
        ds_mod.weaviate, "connect_to_local",
        lambda host, port, **k: _FakeClient(),
    )
    ledger = [("afp001-a/doc1", 2), ("afp001-a/doc2", 2)]
    stats = ds_mod._purge_source_corpus_sync(
        "http://localhost:8080", "Document", "afp001-a", ledger
    )
    # 账本阶段:每个 doc source_id 一次 Equal 精确删除
    assert len(equal_calls) == len(ledger)
    # 边界:孤儿兜底只清边界内 UUID,afp001-ab 幸存
    assert "u-other" not in deleted_by_id
    assert sorted(deleted_by_id) == ["u-own-1", "u-own-2"]
    assert stats["orphans"] == 2
