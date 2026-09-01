"""OBS-01/02/03 技术性能语义修正验收测试(OBS-G001..G007 后端部分)。

语义基线(调查定案):
- 真实失败 = Trace.type == "generation_error"(生产唯一失败持久化路径,
  routes.py PC-06),容错支持 stage error 字段且未 recovered;
- 诊断异常 = 阶段耗时超 NORMAL_MAX 或含错误证据(包含真实失败,异常⊃失败);
- 降级恢复 = 未失败且含 rerank.fallback 或 error+recovered 证据(独立信号,
  不并入异常/失败);
- 健康度 = 确定性五态(no_data/critical/degraded/insufficient_data/healthy);
- 基线 = baseline_source 区分上一窗 P95 与本窗 P50 回退;prev 窗空时 delta=null。

测试通过 date_from/date_to 锁定独立时间窗,避免同库其他测试 trace 污染计数。
"""

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import Conversation, Trace, User
from backend.main import app

pytestmark = pytest.mark.asyncio(loop_scope="session")

_USER_EMAIL = "tech-semantics@test.com"
# 独立时间窗:当前窗 2026-06-01,上一窗(range=today → 1 天)为 2026-05-31
_CUR_FROM = "2026-06-01"
_CUR_TO = "2026-06-02"
_CUR_AT = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)
_PREV_AT = datetime(2026, 5, 31, 12, 0, 0, tzinfo=UTC)

_FAST_STAGES = {
    "intent": {"ms": 50},
    "rewrite": {"ms": 100},
    "retrieve": {"ms": 200},
    "rerank": {"ms": 150},
    "generate": {"ms": 2000},
}


@pytest_asyncio.fixture(loop_scope="session", autouse=True)
async def _clean_scenario_data():
    """每个测试前清除本文件场景数据(question='obs-scenario'),避免窗口累积污染。"""
    factory = app.state.session_factory
    async with factory() as session:
        await session.execute(
            Conversation.__table__.delete().where(Conversation.question == "obs-scenario")
        )
        await session.commit()
    yield


@pytest_asyncio.fixture(loop_scope="session")
async def semantics_seed():
    """创建测试管理员并清理本文件专用邮箱(数据用独立时间窗隔离)。"""
    factory = app.state.session_factory
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
        await session.commit()
    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}
    async with factory() as session:
        await session.execute(User.__table__.delete().where(User.email == _USER_EMAIL))
        await session.commit()


async def _seed_trace(
    *,
    trace_type: str = "rag",
    stages: dict | None = None,
    total_ms: int = 3000,
    created_at: datetime = _CUR_AT,
    failure_kind: str | None = None,
) -> None:
    """在独立时间窗内落一条 trace(带所属 conversation,满足 FK)。"""
    factory = app.state.session_factory
    async with factory() as session:
        conv = Conversation(
            id=uuid.uuid4(),
            question="obs-scenario",
            channel="widget",
            is_answered=trace_type != "generation_error",
        )
        session.add(conv)
        config_snapshot = {"failure_kind": failure_kind} if failure_kind else {}
        session.add(
            Trace(
                conversation_id=conv.id,
                turn_index=0,
                type=trace_type,
                stages=stages or {},
                total_ms=total_ms,
                created_at=created_at,
                config_snapshot=config_snapshot,
            )
        )
        await session.commit()


async def _fetch(headers: dict) -> dict:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            f"/api/admin/tech/performance?range=today&from={_CUR_FROM}&to={_CUR_TO}",
            headers=headers,
        )
    assert resp.status_code == 200
    return resp.json()


async def test_g001_high_anomaly_zero_failure_not_presented_as_failure(semantics_seed):
    """OBS-G001:高诊断异常+零失败 → 不得把诊断信号表述为服务失败。"""
    for _ in range(2):
        await _seed_trace(stages={**_FAST_STAGES, "generate": {"ms": 50000}}, total_ms=60000)
    await _seed_trace(stages=_FAST_STAGES, total_ms=3000)

    j = await _fetch(semantics_seed)
    kpi = j["kpi"]
    assert kpi["fail_count"] == 0
    assert kpi["fail_rate"] == 0.0
    assert kpi["anomaly_count"] == 2
    assert kpi["failure_kinds"] == {}
    health = j["health"]
    assert health["status"] in ("degraded", "critical")
    assert health["status"] != "critical"  # 无真实失败不得 critical
    # 健康度理由不得声称存在真实失败
    assert all("真实失败" not in r for r in health["reasons"])


async def test_g002_real_failures_surfaced_with_stronger_severity(semantics_seed):
    """OBS-G002:存在未恢复失败 → 失败显性呈现,严重度高于慢阶段异常。"""
    for _ in range(10):
        await _seed_trace(stages=_FAST_STAGES, total_ms=3000)
    for _ in range(2):
        await _seed_trace(
            trace_type="generation_error",
            stages={"error": {"kind": "provider_error"}},
            total_ms=4000,
            failure_kind="provider_error",
        )
    # 一条慢但成功的诊断异常
    await _seed_trace(stages={**_FAST_STAGES, "rerank": {"ms": 9000}}, total_ms=12000)

    j = await _fetch(semantics_seed)
    kpi = j["kpi"]
    assert kpi["fail_count"] == 2
    assert abs(kpi["fail_rate"] - round(2 / 13, 4)) < 1e-6
    assert kpi["failure_kinds"] == {"provider_error": 2}
    # 包含关系:失败 ⊆ 诊断异常
    assert kpi["anomaly_count"] >= kpi["fail_count"]
    # 2/13 ≈ 15.4% ≥ 5% → critical
    assert j["health"]["status"] == "critical"
    assert any("失败" in r for r in j["health"]["reasons"])


async def test_g002b_isolated_failure_is_degraded_not_critical(semantics_seed):
    """OBS-G002b:孤立失败(比例<5% 且 <5 条)→ degraded 而非 critical。"""
    for _ in range(24):
        await _seed_trace(stages=_FAST_STAGES, total_ms=3000)
    await _seed_trace(
        trace_type="generation_error",
        stages={"error": {"kind": "empty_generation"}},
        total_ms=3000,
        failure_kind="empty_generation",
    )

    j = await _fetch(semantics_seed)
    assert j["kpi"]["fail_count"] == 1
    assert j["health"]["status"] == "degraded"
    assert any("失败" in r for r in j["health"]["reasons"])


async def test_g003_dominant_stage_identifiable_via_over_count(semantics_seed):
    """OBS-G003:慢主导阶段可识别 —— stages 暴露各段超阈值计数。"""
    for _ in range(3):
        await _seed_trace(stages={**_FAST_STAGES, "rewrite": {"ms": 9000}}, total_ms=11000)
    await _seed_trace(stages={**_FAST_STAGES, "rerank": {"ms": 9000}}, total_ms=11000)

    j = await _fetch(semantics_seed)
    stages = j["stages"]
    assert stages["rewrite"]["over_count"] == 3
    assert stages["rerank"]["over_count"] == 1
    assert stages["intent"]["over_count"] == 0
    assert stages["generate"]["over_count"] == 0


async def test_g004_recovered_not_presented_as_failure(semantics_seed):
    """OBS-G004:降级恢复(rerank fallback / error+recovered)不计入失败。"""
    await _seed_trace(
        stages={"rerank": {"ms": 100, "fallback": True, "fallback_count": 5}},
        total_ms=3000,
    )
    await _seed_trace(
        stages={"generate": {"ms": 100, "error": True, "recovered": True}},
        total_ms=3000,
    )

    j = await _fetch(semantics_seed)
    kpi = j["kpi"]
    assert kpi["fail_count"] == 0
    assert kpi["recovered_count"] == 2
    # error 证据属诊断异常(合同 §11:恢复信号也需关注 → degraded);
    # fallback 本身不是异常(独立恢复信号)
    assert kpi["anomaly_count"] == 1
    assert j["health"]["status"] == "degraded"
    # 关键:恢复场景不得被表述为未恢复失败
    assert all("真实失败" not in r for r in j["health"]["reasons"])


async def test_g005_healthy_period_calm(semantics_seed):
    """OBS-G005:正常周期 → healthy,无失败/异常信号。"""
    for _ in range(12):
        await _seed_trace(stages=_FAST_STAGES, total_ms=3000)

    j = await _fetch(semantics_seed)
    assert j["health"]["status"] == "healthy"
    kpi = j["kpi"]
    assert kpi["fail_count"] == 0
    assert kpi["anomaly_count"] == 0
    assert kpi["anomaly_rate"] == 0.0


async def test_g006_no_data_and_insufficient_sample(semantics_seed):
    """OBS-G006:零数据 → no_data;样本过小且健康 → insufficient_data。"""
    # 空窗
    j = await _fetch(semantics_seed)
    assert j["health"]["status"] == "no_data"
    assert j["kpi"]["trace_total"] == 0

    # 小样本健康 → 证据不足,不得给出自信 healthy
    for _ in range(3):
        await _seed_trace(stages=_FAST_STAGES, total_ms=3000)
    j = await _fetch(semantics_seed)
    assert j["health"]["status"] == "insufficient_data"
    assert j["kpi"]["trace_total"] == 3


async def test_g007_baseline_source_truthfulness(semantics_seed):
    """OBS-G007:上一窗缺失 → baseline=本窗 P50 回退且 delta=null;有上一窗 → 历史对比。"""
    await _seed_trace(stages=_FAST_STAGES, total_ms=3000)
    await _seed_trace(stages=_FAST_STAGES, total_ms=5000)

    j = await _fetch(semantics_seed)
    assert j["kpi"]["baseline_source"] == "current_window_p50_fallback"
    assert j["kpi"]["anomaly_delta"] is None
    assert j["kpi"]["fail_delta"] is None
    assert j["kpi"]["recovered_delta"] is None

    # 上一窗有数据 → 历史对比成立
    await _seed_trace(stages=_FAST_STAGES, total_ms=4000, created_at=_PREV_AT)
    j = await _fetch(semantics_seed)
    assert j["kpi"]["baseline_source"] == "previous_window"
    assert isinstance(j["kpi"]["anomaly_delta"], (int, float))


async def test_anomaly_items_carry_label_severity_machine_type(semantics_seed):
    """OBS-03:异常项含人类可读 label + 语义 severity,机器类型保留。"""
    await _seed_trace(stages={**_FAST_STAGES, "generate": {"ms": 50000}}, total_ms=60000)
    await _seed_trace(
        trace_type="generation_error",
        stages={"error": {"kind": "stream_interrupted"}},
        total_ms=4000,
        failure_kind="stream_interrupted",
    )

    j = await _fetch(semantics_seed)
    by_type = {a["type"]: a for a in j["anomalies"]}
    assert "generate_slow" in by_type
    assert by_type["generate_slow"]["severity"] == "slow"
    assert by_type["generate_slow"]["label"]
    assert "generation_error:stream_interrupted" in by_type
    assert by_type["generation_error:stream_interrupted"]["severity"] == "error"
    assert by_type["generation_error:stream_interrupted"]["label"]


async def test_kpi_denominators_and_window_present(semantics_seed):
    """OBS-02/§12:KPI 含分母 trace_total 与查询窗口,无裸百分比。"""
    for _ in range(4):
        await _seed_trace(stages=_FAST_STAGES, total_ms=3000)

    j = await _fetch(semantics_seed)
    kpi = j["kpi"]
    assert kpi["trace_total"] == 4
    assert kpi["window"]["from"].startswith("2026-06-01")
    assert kpi["window"]["to"].startswith("2026-06-02")
    assert j["health"]["sample_size"] == 4


async def test_failure_trace_without_retrieve_stage_is_not_degradation(semantics_seed):
    """缺陷修复回归:无 retrieve 阶段的失败 trace 不得计入「单路检索」降级。"""
    await _seed_trace(
        trace_type="generation_error",
        stages={"error": {"kind": "provider_error"}},
        total_ms=3000,
        failure_kind="provider_error",
    )

    j = await _fetch(semantics_seed)
    assert j["degradations"] == []
    assert j["kpi"]["fail_count"] == 1
