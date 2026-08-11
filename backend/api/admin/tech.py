"""技术性能聚合端点。"""

from collections import defaultdict
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


@tech_router.get("/performance")
async def tech_performance(
    _: ViewerDep,
    request: Request,
    range: str = Query(default="7d"),
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
) -> dict[str, Any]:
    """返回技术性能聚合数据:KPI、阶段 P50/P95 表、趋势。"""
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

        # 取前一天的 trace 做环比
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
        return {
            "kpi": {
                "p95_ms": 0,
                "anomaly_rate": 0.0,
                "retry_rate": 0.0,
                "fail_rate": 0.0,
                "baseline": 0,
                "comparison": 0.0,
            },
            "stages": {
                s: {"p50": 0, "p95": 0, "normal_max": NORMAL_MAX.get(s, 0)} for s in STAGE_NAMES
            },
            "trends": [],
            "anomalies": [],
            "degradations": [],
            "trace_coverage_from": earliest_row.isoformat() if earliest_row else None,
        }

    total_ms_list: list[float] = []
    stage_ms: dict[str, list[float]] = {s: [] for s in STAGE_NAMES}
    anomaly_count = 0
    retry_count = 0
    fail_count = 0

    # 异常分类计数
    anomaly_type_count: dict[str, int] = defaultdict(int)
    # 降级检测
    degradation_type_count: dict[str, int] = defaultdict(int)

    for t in traces:
        if t.total_ms is not None:
            total_ms_list.append(t.total_ms)
        stages = t.stages or {}
        for sname in STAGE_NAMES:
            sd = stages.get(sname)
            if isinstance(sd, dict) and "ms" in sd:
                stage_ms[sname].append(sd["ms"])

        # 异常:任意阶段超基线或含 error
        is_anomaly = False
        for sname in STAGE_NAMES:
            sd = stages.get(sname)
            if isinstance(sd, dict):
                ms_val = sd.get("ms", 0)
                if ms_val > NORMAL_MAX.get(sname, 999999):
                    is_anomaly = True
                    anomaly_type_count[f"{sname}_slow"] += 1
                if sd.get("error"):
                    is_anomaly = True
                    anomaly_type_count[f"{sname}_error"] += 1
        if is_anomaly:
            anomaly_count += 1

        # retry:stages 含 error/retry 标记
        has_retry = any(
            isinstance(sd, dict) and (sd.get("error") or sd.get("retry_count"))
            for sd in stages.values()
        )
        if has_retry:
            retry_count += 1

        # 失败:retry 后仍 error
        has_persistent_error = any(
            isinstance(sd, dict) and sd.get("error") and not sd.get("recovered")
            for sd in stages.values()
        )
        if has_persistent_error:
            fail_count += 1

        # 降级检测:从 trace type 判断
        trace_type = t.type or "rag"
        if trace_type == "reject_short":
            degradation_type_count["短输入/拒答"] += 1
        elif trace_type == "override":
            degradation_type_count["人工覆盖"] += 1
        elif trace_type == "clarify":
            degradation_type_count["澄清追问"] += 1

        # 从 stages 检测 RRF 降级
        retrieve_sd = stages.get("retrieve", {})
        if isinstance(retrieve_sd, dict):
            path_counts = retrieve_sd.get("path_counts", {})
            if isinstance(path_counts, dict):
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
        }

    # 基线:取前一轮的 P95 作为基线;无前一轮则取本轮 P50
    prev_total_ms = sorted(t.total_ms for t in prev_traces if t.total_ms is not None)
    baseline_p95 = (
        int(_percentile(prev_total_ms, 0.95))
        if prev_total_ms
        else int(_percentile(total_sorted, 0.50))
    )

    # 环比:当前 P95 vs 基线 P95
    comparison = round((p95_total - baseline_p95) / baseline_p95, 4) if baseline_p95 else 0.0

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

    # 异常分布列表
    anomalies = [
        {"type": atype, "count": count}
        for atype, count in sorted(anomaly_type_count.items(), key=lambda x: -x[1])
    ]

    # 降级链路列表
    degradations = [
        {"from": "正常 RAG", "to": dtype, "reason": f"{dtype} 共 {count} 次"}
        for dtype, count in sorted(degradation_type_count.items(), key=lambda x: -x[1])
    ]

    return {
        "kpi": {
            "p95_ms": int(p95_total),
            "anomaly_rate": round(anomaly_count / n, 4) if n else 0.0,
            "retry_rate": round(retry_count / n, 4) if n else 0.0,
            "fail_rate": round(fail_count / n, 4) if n else 0.0,
            "baseline": baseline_p95,
            "comparison": comparison,
        },
        "stages": stage_result,
        "trends": trends,
        "anomalies": anomalies,
        "degradations": degradations,
        "trace_coverage_from": earliest_row.isoformat() if earliest_row else None,
    }
