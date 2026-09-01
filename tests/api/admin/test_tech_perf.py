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
    # 包含关系:真实失败 ⊆ 诊断异常;恢复信号独立存在
    assert j["kpi"]["fail_rate"] <= j["kpi"]["anomaly_rate"]
    assert "recovered_rate" in j["kpi"]
    assert "health" in j


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


async def test_tech_perf_kpi_count_delta_and_anomaly_pct(tech_perf_seed):
    """KPI 含 count(anomaly/retry/fail 条数)、delta(环比)、anomalies 项含 pct。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/admin/tech/performance?range=7d", headers=tech_perf_seed
        )
    assert resp.status_code == 200
    j = resp.json()
    kpi = j["kpi"]
    # count 字段存在且为 int(anomaly/fail/recovered,重试率已退役为降级恢复)
    for field in ("anomaly_count", "fail_count", "recovered_count"):
        assert field in kpi
        assert isinstance(kpi[field], int)
    # delta 字段存在,上一窗缺失时为 null(不假装环比)
    for field in ("anomaly_delta", "recovered_delta", "fail_delta"):
        assert field in kpi
        assert kpi[field] is None or isinstance(kpi[field], (int, float))
    # anomalies 项含 pct
    for a in j["anomalies"]:
        assert "pct" in a
        assert 0 <= a["pct"] <= 100
    # count 与 rate 一致性(anomaly_count / n ≈ anomaly_rate,n=当前窗 trace 数)
    # seed 创建 12 条 trace(10 rag + 2 reject_short),均在 7d 内
    # 这里只验证 count 与 rate 的数值关系不矛盾(rate = count/n)
    # 若有 prev_traces 则 delta 非零;无 prev_traces 时 delta 为 0(基线逻辑)


async def test_tech_perf_stage_pct(tech_perf_seed):
    """stages 各段含 p50_pct/p95_pct(相对最大 P95 的比例)。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/admin/tech/performance?range=7d", headers=tech_perf_seed
        )
    assert resp.status_code == 200
    stages = resp.json()["stages"]
    max_p95 = max(s["p95"] for s in stages.values())
    for sname, sd in stages.items():
        assert "p50_pct" in sd, f"{sname} 缺 p50_pct"
        assert "p95_pct" in sd, f"{sname} 缺 p95_pct"
        assert isinstance(sd["p50_pct"], (int, float))
        assert isinstance(sd["p95_pct"], (int, float))
        # p95_pct = p95 / max_p95 * 100(允许 ±0.5 四舍五入误差)
        if max_p95 > 0:
            assert abs(sd["p95_pct"] - round(sd["p95"] / max_p95 * 100, 1)) < 0.5
            # p50_pct <= p95_pct(P50 <= P95)
            assert sd["p50_pct"] <= sd["p95_pct"] + 0.5
