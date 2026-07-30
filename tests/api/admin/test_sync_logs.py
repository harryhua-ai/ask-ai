"""同步日志查询端点测试。"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import SyncLog, User
from backend.main import app

# 所有 admin API 测试共享 session 级事件循环（与 conftest 的 session fixture 对齐）
pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def auth_headers():
    """创建管理员用户 + 一条测试同步日志，返回 Authorization 头。

    测试结束后仅清理本测试创建的数据（source_id="test"），不删除其他同步日志。
    """
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email="sync-admin@test.com",
                role="admin",
                password_hash=hash_password("pass123"),
            )
        )
        session.add(
            SyncLog(
                source_id="test",
                source_type="github",
                status="success",
            )
        )
        await session.commit()
    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}
    # 清理：仅删除本测试创建的同步日志和用户，避免破坏共享 dev 数据
    async with factory() as session:
        await session.execute(SyncLog.__table__.delete().where(SyncLog.source_id == "test"))
        await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.commit()


async def test_list_sync_logs(auth_headers):
    """验证 GET /api/admin/sync-logs 返回分页结果且包含测试创建的日志。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/sync-logs", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert data["page"] == 1
    assert data["size"] == 20
    assert any(log["source_id"] == "test" for log in data["items"])


async def test_list_sync_logs_filter_by_source_id(auth_headers):
    """验证 source_id 过滤参数生效。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/admin/sync-logs",
            params={"source_id": "test"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert all(log["source_id"] == "test" for log in data["items"])


async def test_list_sync_logs_filter_by_status(auth_headers):
    """验证 status 过滤参数生效。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/admin/sync-logs",
            params={"status": "success"},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert all(log["status"] == "success" for log in data["items"])


async def test_list_sync_logs_requires_auth():
    """验证未认证请求返回 401。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/sync-logs")
    assert resp.status_code == 401
