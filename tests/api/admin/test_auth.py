"""Admin 认证端点测试。"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.auth.jwt import hash_password
from backend.db.models import User
from backend.main import app

# 所有 admin API 测试共享 session 级事件循环（与 conftest 的 session fixture 对齐）
pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def admin_user():
    """在 app.state.session_factory 中插入一个管理员用户。"""
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        user = User(
            id=user_id,
            email="admin@test.com",
            name="Admin",
            role="admin",
            password_hash=hash_password("testpass123"),
        )
        session.add(user)
        await session.commit()
    yield user_id
    async with factory() as session:
        await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.commit()


async def test_login_success(admin_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/auth/login",
            json={"email": "admin@test.com", "password": "testpass123"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["user"]["email"] == "admin@test.com"


async def test_login_wrong_password(admin_user):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/auth/login",
            json={"email": "admin@test.com", "password": "wrong"},
        )
    assert resp.status_code == 401


async def test_me_without_token():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/auth/me")
    assert resp.status_code == 401
