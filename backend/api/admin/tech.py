"""技术性能聚合端点。

语义定版(OBS-01/02/03,证据=真实 Trace 写入路径调查):
- 真实失败(fail):Trace.type == "generation_error"(routes.py PC-06 唯一失败
  持久化路径,用户收到失败文案、无恢复可能);容错支持 stage error 字段且未
  recovered 的未来写入。慢成功≠失败,诊断异常≠失败。
- 诊断异常(anomaly):阶段耗时超 NORMAL_MAX 或含错误证据(含真实失败,
  保持 异常 ⊃ 失败 包含关系)。这是诊断信号率,不是失败率。
- 降级恢复(recovered):未失败且含 rerank.fallback(重排滤光→降级用 fused
  结果→用户仍获答案)或 error+recovered 证据。独立信号,不并入异常/失败。
  注:deepseek 客户端存在 max_attempts=2 重试但仅落日志不落 trace,生产
  trace 无 retry_count 字段,故「重试率」标签退役(调查详见执行报告 §10)。
- 健康度(health):确定性五态推导,阈值复用既有 UI 告警阈值,不新增产品语义。
"""

from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import Trace

tech_router = APIRouter(prefix="/tech", tags=["技术性能"])
ViewerDep = Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))]

NORMAL_MAX: dict[str, int] = {
    "intent": 3000,
    "rewrite": 4000,
    "retrieve": 3000,
    "rerank": 3000,
    "generate": 30000,
    "output": 100,
}

STAGE_NAMES = ("intent", "rewrite", "retrieve", "rerank", "generate", "output")

STAGE_LABELS = {
    "intent": "意图识别",
    "rewrite": "查询改写",
    "retrieve": "检索",
    "rerank": "重排",
    "generate": "生成",
    "output": "输出",
}

FAILURE_KIND_LABELS = {
    "empty_generation": "空生成",
    "provider_error": "供应商异常",
    "stream_interrupted": "流中断",
}

# 健康度阈值:复用既有 UI 告警阈值(anomaly>10% / fail>5% / P95>5000ms),
# 仅收拢为服务级判定,不发明新产品阈值。
HEALTH_ANOMALY_RATE = 0.10
HEALTH_P95_MS = 5000
HEALTH_CRITICAL_FAIL_RATE = 0.05
HEALTH_CRITICAL_FAIL_COUNT = 5
# 低于该样本量时比例指标不稳定,健康结论降级为「证据不足」(§19)。
MIN_CONFIDENT_SAMPLE = 10


def _percentile(sorted_vals: list[float], pct: float) -> float:
    """计算百分位数(线性插值法)。"""
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * pct
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def _extract_failure_kind(t: Trace) -> str | None:
    """从 trace 携带证据提取失败类别(routes.py PC-06 写入路径)。"""
    if t.type != "generation_error":
        return None
    kind = (t.config_snapshot or {}).get("failure_kind")
    if not kind:
        error_sd = (t.stages or {}).get("error")
        if isinstance(error_sd, dict):
            kind = error_sd.get("kind")
    return kind or "unknown"


def _classify_trace(t: Trace) -> dict[str, Any]:
    """按证据对单条 trace 分类:failure / anomaly / recovered + 明细。"""
    stages = t.stages or {}
    slow_stages: list[str] = []
    errored: list[tuple[str, bool]] = []  # (stage, recovered)
    fallback = False
    for sname in STAGE_NAMES:
        sd = stages.get(sname)
        if not isinstance(sd, dict):
            continue
        ms_val = sd.get("ms", 0)
        if ms_val > NORMAL_MAX.get(sname, 999999):
            slow_stages.append(sname)
        if sd.get("error"):
            errored.append((sname, bool(sd.get("recovered"))))
        if sd.get("fallback"):
            fallback = True

    is_failure = t.type == "generation_error" or any(not rec for _, rec in errored)
    is_anomaly = bool(slow_stages) or bool(errored) or is_failure
    is_recovered = (not is_failure) and (fallback or any(rec for _, rec in errored))
    return {
        "failure": is_failure,
        "anomaly": is_anomaly,
        "recovered": is_recovered,
        "failure_kind": _extract_failure_kind(t),
        "slow_stages": slow_stages,
        "errored": errored,
    }


def _count_flags(traces: list) -> dict[str, int]:
    """统计上一时间窗的 anomaly/fail/recovered 条数(与主循环同源分类)。"""
    flags = {"anomaly": 0, "fail": 0, "recovered": 0}
    for t in traces:
        cls = _classify_trace(t)
        if cls["anomaly"]:
            flags["anomaly"] += 1
        if cls["failure"]:
            flags["fail"] += 1
        if cls["recovered"]:
            flags["recovered"] += 1
    return flags


def _anomaly_label(atype: str) -> str:
    """异常类型 → 人类可读标签(机器类型 type 字段原样保留)。"""
    if atype.startswith("generation_error:"):
        kind = atype.split(":", 1)[1]
        return f"生成失败·{FAILURE_KIND_LABELS.get(kind, kind)}"
    if atype.endswith("_slow"):
        return f"{STAGE_LABELS.get(atype[:-5], atype[:-5])}缓慢"
    if atype.endswith("_error"):
        return f"{STAGE_LABELS.get(atype[:-6], atype[:-6])}错误"
    return atype


def _anomaly_severity(atype: str) -> str:
    """语义严重度:错误类=error,慢类=slow(前端按语义着色,不按计数)。"""
    return "slow" if atype.endswith("_slow") else "error"


def _derive_health(
    n: int, fail_count: int, fail_rate: float, anomaly_rate: float, p95_ms: int
) -> dict[str, Any]:
    """确定性服务健康推导(失败与诊断异常严格分级,证据可解释)。"""
    if n == 0:
        return {
            "status": "no_data",
            "reasons": ["所选时间窗内无 trace 数据,无法评估服务状态"],
            "sample_size": 0,
        }

    reasons: list[str] = []
    critical = fail_count > 0 and (
        fail_rate >= HEALTH_CRITICAL_FAIL_RATE or fail_count >= HEALTH_CRITICAL_FAIL_COUNT
    )
    if fail_count > 0:
        if critical:
            reasons.append(
                f"存在 {fail_count} 条真实失败(占 {fail_rate:.1%}),"
                "已达严重阈值(失败率≥5% 或失败≥5 条)"
            )
        else:
            reasons.append(
                f"存在 {fail_count} 条真实失败(占 {fail_rate:.1%}),需要关注"
            )
    if anomaly_rate > HEALTH_ANOMALY_RATE:
        reasons.append(
            f"诊断异常率 {anomaly_rate:.0%} 偏高(超过性能阈值或含错误;"
            "属诊断信号,不等同服务失败)"
        )
    if p95_ms > HEALTH_P95_MS:
        reasons.append(f"P95 耗时 {p95_ms}ms 偏高(>{HEALTH_P95_MS}ms)")

    if critical:
        status = "critical"
    elif fail_count > 0 or anomaly_rate > HEALTH_ANOMALY_RATE or p95_ms > HEALTH_P95_MS:
        status = "degraded"
    elif n < MIN_CONFIDENT_SAMPLE:
        return {
            "status": "insufficient_data",
            "reasons": [
                f"样本过少(仅 {n} 条 trace),证据不足以给出自信的健康判定"
            ],
            "sample_size": n,
        }
    else:
        status = "healthy"
        reasons.append("未检测到真实失败,诊断异常与延迟均处正常范围")

    if n < MIN_CONFIDENT_SAMPLE and status == "degraded":
        reasons.append(f"样本过少(仅 {n} 条 trace),结论需谨慎")
    return {"status": status, "reasons": reasons, "sample_size": n}


def _empty_payload(start: datetime, end: datetime, earliest_row: Any) -> dict[str, Any]:
    """零 trace 响应:字段齐全,健康度=no_data,不假装任何结论。"""
    return {
        "kpi": {
            "p95_ms": 0,
            "anomaly_rate": 0.0,
            "fail_rate": 0.0,
            "recovered_rate": 0.0,
            "anomaly_count": 0,
            "fail_count": 0,
            "recovered_count": 0,
            "anomaly_delta": None,
            "fail_delta": None,
            "recovered_delta": None,
            "failure_kinds": {},
            "trace_total": 0,
            "window": {"from": start.isoformat(), "to": end.isoformat()},
            "baseline": 0,
            "baseline_source": "current_window_p50_fallback",
            "comparison": 0.0,
        },
        "stages": {
            s: {
                "p50": 0,
                "p95": 0,
                "normal_max": NORMAL_MAX.get(s, 0),
                "p50_pct": 0.0,
                "p95_pct": 0.0,
                "over_count": 0,
            }
            for s in STAGE_NAMES
        },
        "trends": [],
        "anomalies": [],
        "degradations": [],
        "health": {
            "status": "no_data",
            "reasons": ["所选时间窗内无 trace 数据,无法评估服务状态"],
            "sample_size": 0,
        },
        "trace_coverage_from": earliest_row.isoformat() if earliest_row else None,
    }


@tech_router.get("/performance")
async def tech_performance(
    _: ViewerDep,
    request: Request,
    range: str = Query(default="7d"),
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
) -> dict[str, Any]:
    """返回技术性能聚合数据:健康度、KPI(含分母)、阶段 P50/P95、趋势。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    days = {"today": 1, "7d": 7, "30d": 30}.get(range, 7)
    end = datetime.now(UTC)
    start = end - timedelta(days=days)

    if date_from:
        start = datetime.fromisoformat(date_from).replace(tzinfo=UTC)
    if date_to:
        end = datetime.fromisoformat(date_to).replace(tzinfo=UTC)

    async with factory() as session:
        rows = await session.execute(
            select(Trace).where(Trace.created_at >= start, Trace.created_at <= end)
        )
        traces = rows.scalars().all()

        # 取上一等长时间窗的 trace 做环比/基线
        prev_end = start
        prev_start = start - timedelta(days=days)
        prev_rows = await session.execute(
            select(Trace).where(Trace.created_at >= prev_start, Trace.created_at < prev_end)
        )
        prev_traces = prev_rows.scalars().all()

        # 取最早 trace 时间(trace 覆盖起始)
        earliest = await session.execute(
            select(Trace.created_at).order_by(Trace.created_at.asc()).limit(1)
        )
        earliest_row = earliest.scalar_one_or_none()

    if not traces:
        return _empty_payload(start, end, earliest_row)

    total_ms_list: list[float] = []
    stage_ms: dict[str, list[float]] = {s: [] for s in STAGE_NAMES}
    stage_over_count: Counter[str] = Counter()
    anomaly_count = 0
    fail_count = 0
    recovered_count = 0
    failure_kinds: Counter[str] = Counter()

    # 异常分类计数(机器类型;前端展示用 label/severity 字段)
    anomaly_type_count: dict[str, int] = defaultdict(int)
    # 降级检测(产品路径降级,与恢复信号区分)
    degradation_type_count: dict[str, int] = defaultdict(int)

    for t in traces:
        if t.total_ms is not None:
            total_ms_list.append(t.total_ms)
        stages = t.stages or {}
        for sname in STAGE_NAMES:
            sd = stages.get(sname)
            if isinstance(sd, dict) and "ms" in sd:
                stage_ms[sname].append(sd["ms"])

        cls = _classify_trace(t)
        if cls["anomaly"]:
            anomaly_count += 1
        if cls["failure"]:
            fail_count += 1
            failure_kinds[cls["failure_kind"] or "unknown"] += 1
        if cls["recovered"]:
            recovered_count += 1

        for sname in cls["slow_stages"]:
            stage_over_count[sname] += 1
            anomaly_type_count[f"{sname}_slow"] += 1
        for sname, _rec in cls["errored"]:
            anomaly_type_count[f"{sname}_error"] += 1
        if cls["failure"]:
            anomaly_type_count[f"generation_error:{cls['failure_kind']}"] += 1

        # 降级检测:从 trace type 判断(产品路径降级)
        trace_type = t.type or "rag"
        if trace_type == "reject_short":
            degradation_type_count["短输入/拒答"] += 1
        elif trace_type == "override":
            degradation_type_count["人工覆盖"] += 1
        elif trace_type == "clarify":
            degradation_type_count["澄清追问"] += 1

        # 从 stages 检测 RRF 降级:仅当 retrieve 阶段真实存在且带 path_counts
        # 证据时才判单路 —— 失败/拒答 trace 无 retrieve 阶段,缺失证据≠降级证据
        retrieve_sd = stages.get("retrieve")
        if isinstance(retrieve_sd, dict):
            path_counts = retrieve_sd.get("path_counts")
            if isinstance(path_counts, dict) and path_counts:
                symbol_count = path_counts.get("symbol", 0)
                boost_count = path_counts.get("boost", 0)
                if symbol_count == 0 and boost_count == 0:
                    degradation_type_count["单路检索"] += 1

    n = len(traces)
    total_sorted = sorted(total_ms_list)
    p95_total = _percentile(total_sorted, 0.95) if total_sorted else 0

    # 阶段 P50/P95
    stage_result: dict[str, dict[str, Any]] = {}
    for sname in STAGE_NAMES:
        vals = sorted(stage_ms[sname])
        stage_result[sname] = {
            "p50": int(_percentile(vals, 0.50)) if vals else 0,
            "p95": int(_percentile(vals, 0.95)) if vals else 0,
            "normal_max": NORMAL_MAX.get(sname, 0),
            "over_count": stage_over_count.get(sname, 0),
        }
    # p50_pct/p95_pct(相对各段最大 P95 的比例,前端 DualStageBar 双色条用)
    max_p95 = max((s["p95"] for s in stage_result.values()), default=0)
    for sname in STAGE_NAMES:
        sd = stage_result[sname]
        sd["p50_pct"] = round(sd["p50"] / max_p95 * 100, 1) if max_p95 else 0.0
        sd["p95_pct"] = round(sd["p95"] / max_p95 * 100, 1) if max_p95 else 0.0

    # 基线:上一等长时间窗 P95;缺失时回退本窗 P50 —— baseline_source 如实
    # 区分历史对比与诊断参考,前端据此展示,不得把回退值标成历史基线。
    prev_total_ms = sorted(t.total_ms for t in prev_traces if t.total_ms is not None)
    has_prev = bool(prev_total_ms)
    baseline_p95 = (
        int(_percentile(prev_total_ms, 0.95))
        if has_prev
        else int(_percentile(total_sorted, 0.50))
    )
    baseline_source = "previous_window" if has_prev else "current_window_p50_fallback"

    # 环比:当前 P95 vs 基线 P95(仅历史对比时有意义)
    comparison = (
        round((p95_total - baseline_p95) / baseline_p95, 4) if baseline_p95 else 0.0
    )

    # 异常/失败/恢复环比 delta:上一窗无数据时置 null(不假装环比)
    cur_flags = {
        "anomaly": anomaly_count,
        "fail": fail_count,
        "recovered": recovered_count,
    }
    prev_flags = _count_flags(prev_traces)
    if has_prev or prev_traces:
        prev_n = len(prev_traces) or 1
        deltas: dict[str, float | None] = {
            key: round(cur_flags[key] / n - prev_flags[key] / prev_n, 4) if n else 0.0
            for key in cur_flags
        }
    else:
        deltas = {"anomaly": None, "fail": None, "recovered": None}

    # 趋势(按天)
    daily_totals: dict[str, list[int]] = defaultdict(list)
    for t in traces:
        if t.total_ms is not None and t.created_at:
            day_key = t.created_at.strftime("%m-%d")
            daily_totals[day_key].append(t.total_ms)
    trends = []
    for day_key in sorted(daily_totals.keys()):
        vals = sorted(daily_totals[day_key])
        trends.append(
            {
                "date": day_key,
                "p50": int(_percentile(vals, 0.50)),
                "p95": int(_percentile(vals, 0.95)),
            }
        )

    # 异常分布列表:机器类型保留,label/severity 供前端语义展示
    anomaly_total = sum(anomaly_type_count.values()) or 1
    anomalies = [
        {
            "type": atype,
            "label": _anomaly_label(atype),
            "severity": _anomaly_severity(atype),
            "count": count,
            "pct": round(count / anomaly_total * 100, 1),
        }
        for atype, count in sorted(anomaly_type_count.items(), key=lambda x: -x[1])
    ]

    # 降级链路列表
    degradations = [
        {"from": "正常 RAG", "to": dtype, "reason": f"{dtype} 共 {count} 次"}
        for dtype, count in sorted(degradation_type_count.items(), key=lambda x: -x[1])
    ]

    health = _derive_health(
        n=n,
        fail_count=fail_count,
        fail_rate=fail_count / n,
        anomaly_rate=anomaly_count / n,
        p95_ms=int(p95_total),
    )

    return {
        "kpi": {
            "p95_ms": int(p95_total),
            "anomaly_rate": round(anomaly_count / n, 4) if n else 0.0,
            "fail_rate": round(fail_count / n, 4) if n else 0.0,
            "recovered_rate": round(recovered_count / n, 4) if n else 0.0,
            "anomaly_count": anomaly_count,
            "fail_count": fail_count,
            "recovered_count": recovered_count,
            "anomaly_delta": deltas["anomaly"],
            "fail_delta": deltas["fail"],
            "recovered_delta": deltas["recovered"],
            "failure_kinds": dict(failure_kinds),
            "trace_total": n,
            "window": {"from": start.isoformat(), "to": end.isoformat()},
            "baseline": baseline_p95,
            "baseline_source": baseline_source,
            "comparison": comparison,
        },
        "stages": stage_result,
        "trends": trends,
        "anomalies": anomalies,
        "degradations": degradations,
        "health": health,
        "trace_coverage_from": earliest_row.isoformat() if earliest_row else None,
    }
