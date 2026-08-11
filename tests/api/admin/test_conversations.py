"""对话审查端点测试。"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import desc, select

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import Conversation, Trace, User
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


async def test_list_conversations_q_search(auth_headers):
    """q 参数全文搜索 question/answer(ILIKE)。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/admin/conversations?q=test%20question",
            headers=auth_headers,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert all(
        "test question" in c["question"].lower() or "test question" in (c["answer"] or "").lower()
        for c in data["items"]
    )

    # 搜不存在的关键词 → fixture 的 test question 不在结果里
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp2 = await client.get(
            "/api/admin/conversations?q=zzz_nomatch_zzz",
            headers=auth_headers,
        )
    data2 = resp2.json()
    assert all("test question" not in c["question"].lower() for c in data2["items"])


async def test_list_conversations_trace_summary_latest_turn_and_confidence(auth_headers):
    """trace_summary 取最新一轮(turn_index 最大)的 trace,且含 confidence。"""
    factory = app.state.session_factory
    async with factory() as session:
        conv = await session.execute(
            select(Conversation).where(Conversation.question == "test question")
        )
        conv = conv.scalar_one()
        # 先建 turn 0(低置信),再建 turn 1(高置信,应被选中)
        session.add(
            Trace(
                conversation_id=conv.id,
                turn_index=0,
                type="rag",
                stages={"intent": {"ms": 50}},
                total_ms=100,
                intent="commercial",
                confidence=0.30,
                config_snapshot={},
            )
        )
        session.add(
            Trace(
                conversation_id=conv.id,
                turn_index=1,
                type="rag",
                stages={"intent": {"ms": 60}},
                total_ms=200,
                intent="commercial",
                confidence=0.85,
                config_snapshot={},
            )
        )
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/admin/conversations?q=test%20question", headers=auth_headers
        )
    items = resp.json()["items"]
    target = [c for c in items if c["question"] == "test question"][0]
    ts = target["trace_summary"]
    assert ts is not None
    # 取最新轮次(turn 1)
    assert ts["confidence"] == 0.85
    assert ts["total_ms"] == 200
    # 清理本次创建的 trace
    async with factory() as session:
        await session.execute(Trace.__table__.delete().where(Trace.conversation_id == conv.id))
        await session.commit()
