"""用户管理端点测试。"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import User
from backend.main import app

# 所有 admin API 测试共享 session 级事件循环（与 conftest 的 session fixture 对齐）
pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def auth_token():
    """创建管理员用户并返回 JWT token；测试结束后清理本测试创建的所有用户。

    使用 "admin-crud@test.com" 避免与 test_auth.py 的 admin_user fixture 邮箱冲突。
    """
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email="admin-crud@test.com",
                name="Admin CRUD",
                role="admin",
                password_hash=hash_password("pass123"),
            )
        )
        await session.commit()
    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield token
    # 清理：删除本测试创建的 admin 用户以及通过 API 创建的测试用户（邮箱以 @test.com 结尾）
    async with factory() as session:
        await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.execute(User.__table__.delete().where(User.email.endswith("@test.com")))
        await session.commit()


async def test_list_users_requires_auth():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/users")
    assert resp.status_code == 401


async def test_create_and_list_user(auth_token):
    transport = ASGITransport(app=app)
    headers = {"Authorization": f"Bearer {auth_token}"}
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/users",
            json={"email": "new@test.com", "password": "newpass123", "role": "viewer"},
            headers=headers,
        )
        assert resp.status_code == 201
        resp = await client.get("/api/admin/users", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()) >= 1
