"""技术性能聚合端点测试。"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import Conversation, Trace, User
from backend.main import app

pytestmark = pytest.mark.asyncio(loop_scope="session")

_USER_EMAIL = "tech-perf@test.com"
_created_user_ids: list[uuid.UUID] = []
_created_conv_ids: list[uuid.UUID] = []


@pytest_asyncio.fixture(loop_scope="session")
async def tech_perf_seed():
    """seed: 10 条 rag trace(total_ms 各不同), 2 条 reject_short。"""
    factory = app.state.session_factory
    # 预清理(前次运行残留)
    async with factory() as session:
        await session.execute(User.__table__.delete().where(User.email == _USER_EMAIL))
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
        for i in range(10):
            conv_id = uuid.uuid4()
            session.add(
                Conversation(
                    id=conv_id,
                    question=f"q{i}",
                    channel="widget",
                    is_answered=True,
                    intent_tag="product",
                )
            )
            session.add(
                Trace(
                    conversation_id=conv_id,
                    turn_index=0,
                    type="rag",
                    stages={
                        "intent": {"ms": 50},
                        "rewrite": {"ms": 100},
                        "retrieve": {"ms": 200},
                        "rerank": {"ms": 150},
                        "generate": {"ms": 100 * (i + 1)},
                    },
                    total_ms=200 + i * 100,
                    intent="product",
                    config_snapshot={},
                )
            )
        for i in range(2):
            conv_id = uuid.uuid4()
            session.add(
                Conversation(
                    id=conv_id,
                    question=f"off{i}",
                    channel="widget",
                    is_answered=False,
                    intent_tag="off_topic",
                )
            )
            session.add(
                Trace(
                    conversation_id=conv_id,
                    turn_index=0,
                    type="reject_short",
                    stages={"intent": {"ms": 30}},
                    total_ms=50,
                    intent="off_topic",
                    config_snapshot={},
                )
            )
        await session.commit()
    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}
    # 后清理
    async with factory() as session:
        await session.execute(User.__table__.delete().where(User.email == _USER_EMAIL))
        await session.commit()


async def test_tech_perf_returns_kpi(tech_perf_seed):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/admin/tech/performance?range=7d", headers=tech_perf_seed
        )
    assert resp.status_code == 200
    j = resp.json()
    assert j["kpi"]["p95_ms"] > 0
    assert j["kpi"]["fail_rate"] <= j["kpi"]["retry_rate"] <= j["kpi"]["anomaly_rate"]


async def test_tech_perf_stage_percentiles(tech_perf_seed):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/admin/tech/performance?range=7d", headers=tech_perf_seed
        )
    stages = resp.json()["stages"]
    for s in ("intent", "retrieve", "rerank", "generate"):
        assert stages[s]["p50"] > 0
        assert stages[s]["p95"] >= stages[s]["p50"]
        assert "normal_max" in stages[s]
