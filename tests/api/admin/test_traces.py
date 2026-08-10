"""trace 查询端点测试。

模式参照 tests/api/admin/test_conversations.py:用 app.state.session_factory seed 数据,
ASGITransport + AsyncClient 请求,精准清理。
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import Conversation, Trace, User
from backend.main import app

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def trace_auth_and_seed():
    """seed 1 条 conversation + 1 条 trace,返回 (headers, conversation_id)。"""
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    conv_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email="trace-test@test.com",
                role="admin",
                password_hash=hash_password("pass"),
            )
        )
        session.add(
            Conversation(
                id=conv_id,
                question="NE503 价格",
                channel="widget",
                is_answered=True,
                intent_tag="commercial",
            )
        )
        session.add(
            Trace(
                conversation_id=conv_id,
                turn_index=0,
                type="rag",
                stages={"intent": {"ms": 50}, "generate": {"ms": 500}},
                total_ms=800,
                intent="commercial",
                config_snapshot={},
            )
        )
        await session.commit()
    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}, str(conv_id)
    async with factory() as session:
        await session.execute(Trace.__table__.delete().where(Trace.conversation_id == conv_id))
        await session.execute(Conversation.__table__.delete().where(Conversation.id == conv_id))
        await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.commit()


async def test_list_traces(trace_auth_and_seed):
    auth_headers, conv_id = trace_auth_and_seed
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            f"/api/admin/conversations/{conv_id}/traces", headers=auth_headers
        )
    assert resp.status_code == 200
    traces = resp.json()
    assert len(traces) >= 1
    t = traces[0]
    assert t["type"] == "rag"
    assert "generate" in t["stages"]
    assert t["intent"] == "commercial"
