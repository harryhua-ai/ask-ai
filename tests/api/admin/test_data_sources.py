"""数据源管理端点测试。"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import DataSource, User
from backend.main import app

# 所有 admin API 测试共享 session 级事件循环（与 conftest 的 session fixture 对齐）
pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def auth_headers():
    """创建管理员用户并返回 Authorization 头；测试结束后清理测试数据源与用户。"""
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email="ds-admin@test.com",
                role="admin",
                password_hash=hash_password("pass123"),
            )
        )
        await session.commit()
    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}
    # 清理：仅删除本测试创建的数据源和用户，避免破坏 Task 9 迁移的共享 dev 数据
    async with factory() as session:
        await session.execute(DataSource.__table__.delete().where(DataSource.id == "test-source"))
        await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.commit()


async def test_create_and_list_data_source(auth_headers):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/data-sources",
            json={
                "id": "test-source",
                "type": "github",
                "product": "test",
                "config": {"owner": "camthink-ai", "repo": "test"},
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        resp = await client.get("/api/admin/data-sources", headers=auth_headers)
        assert resp.status_code == 200
        assert any(s["id"] == "test-source" for s in resp.json())


async def test_preview_branches(auth_headers, monkeypatch):
    """preview-branches 应调 GitHub API 返回分支列表(mock httpx)。"""
    from unittest.mock import AsyncMock, MagicMock

    import backend.api.admin.data_sources as mod

    fake_resp = MagicMock()
    fake_resp.raise_for_status.return_value = None
    fake_resp.json.return_value = [{"name": "main"}, {"name": "hw-v1.2"}]
    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=None)
    fake_client.get = AsyncMock(return_value=fake_resp)
    monkeypatch.setattr(mod.httpx, "AsyncClient", lambda *a, **kw: fake_client)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/admin/data-sources/preview-branches?owner=o&repo=r",
            headers=auth_headers,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["branches"] == ["main", "hw-v1.2"]
