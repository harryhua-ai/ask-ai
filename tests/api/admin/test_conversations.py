"""对话审查端点测试。"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import Conversation, User
from backend.main import app

# 所有 admin API 测试共享 session 级事件循环（与 conftest 的 session fixture 对齐）
pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def auth_headers():
    """创建管理员用户 + 测试对话，返回认证头；测试结束后按 question 精准清理。"""
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email="admin-conv@test.com",
                role="admin",
                password_hash=hash_password("pass"),
            )
        )
        session.add(Conversation(question="test question", channel="widget", is_answered=True))
        await session.commit()
    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}
    # 精准清理：仅删除本测试创建的对话与用户（避免影响其他测试数据）
    async with factory() as session:
        await session.execute(
            Conversation.__table__.delete().where(Conversation.question == "test question")
        )
        await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.commit()


async def test_list_conversations_filtered(auth_headers):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/admin/conversations?channel=widget&is_answered=true",
            headers=auth_headers,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert all(c["channel"] == "widget" for c in data["items"])
