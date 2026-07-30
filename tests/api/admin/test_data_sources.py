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
    # 清理：删除本测试可能创建的数据源和用户
    async with factory() as session:
        await session.execute(DataSource.__table__.delete())
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
