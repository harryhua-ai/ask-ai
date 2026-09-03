"""⑫ Sync Truth 读侧 API(W2 Sync Truth Backend;Frozen Discovery §19 contract)。

- ``GET /sync-status``  全部相关源 bulk 运行态(request + latest run 读时派生;
  #9 刷新恢复的**唯一**事实源——前端禁止再用本地内存/时间戳启发式);
- ``GET /sync-runs``    运行历史(ONE SOURCE × ONE ATTEMPT + sync_log join;#15);
- ``GET /sync-health``  五维健康(读时派生,无 SourceHealthSnapshot;#11)。

纪律(冻结):
- ``sync_requests`` 仍是执行/恢复权威;``sync_runs`` 是运行遥测真相;本路由只读;
- ``stage_total IS NULL`` ⇒ 分母未知,响应原样透传 NULL,前端禁止伪造百分比;
- 无证据 → UNKNOWN / INSUFFICIENT_DATA,禁止默认 HEALTHY(绿色假健康禁令);
- 设备/一致性/计数全部消费结构化列,不解析自由文本 error_detail 作机器真值;
- ``request_id IS NULL`` 是合法 cron 直跑路径,与 request 托管运行同等呈现。
"""

import re
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.admin.schemas import (
    HealthDimension,
    SourceHealthItem,
    SourceHealthResponse,
    SyncRunHistoryItem,
    SyncRunLogSummary,
    SyncRunsResponse,
    SyncStatusItem,
    SyncStatusResponse,
)
from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import DataSource, Document, SyncLog, SyncRequest, SyncRun
from backend.services.sync_runs import (
    RUN_FAILED,
    STAGE_DISCOVER,
    STAGE_FETCH,
    STAGE_PARSE,
    derive_source_state,
    get_latest_runs_by_source,
    get_latest_runs_for_requests,
    get_running_runs,
    get_sync_logs_by_ids,
    is_ingestion_skipped,
    list_runs,
)

router = APIRouter(tags=["同步运行"])
ViewerDep = Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))]

_ACTIVE_STATES = {"QUEUED", "WAITING", "RUNNING", "RECOVERING"}
_EXPECTED_STATES = ("REQUIRED", "OPTIONAL", "DISCOVERY", "EXCLUDED")
_INTERVAL_RE = re.compile(r"^(\d+)([hm])$")
_MIN_CONFIDENT_SYNCS = 3
_FRESHNESS_MULTIPLIER = 2.0
_DEFAULT_INTERVAL_SECONDS = 24 * 3600.0
_COVERAGE_OK_RATIO = 0.8


def _recovering(request: SyncRequest) -> bool:
    return (request.attempt_count or 0) > 1 or request.failure_kind is not None


def _pick_active_request(
    source_id: str,
    source_requests: dict[str, SyncRequest],
    sync_all_requests: list[SyncRequest],
) -> SyncRequest | None:
    """该源的在途请求:source 专属请求优先,否则最新一条 sync-all(NULL)。"""
    specific = source_requests.get(source_id)
    if specific is not None:
        return specific
    if sync_all_requests:
        return sync_all_requests[-1]
    return None


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _duration_seconds(run: SyncRun) -> float | None:
    if run.finished_at is not None and run.started_at is not None:
        return round((run.finished_at - run.started_at).total_seconds(), 3)
    return None


# --------------------------------------------------------------------------- #
# GET /sync-status(#9 刷新恢复 + #12 realtime bulk 事实源)
# --------------------------------------------------------------------------- #


@router.get("/sync-status", response_model=SyncStatusResponse)
async def get_sync_status(_: ViewerDep, request: Request) -> SyncStatusResponse:
    """全部相关源的当前运行态快照(bulk,单次请求)。

    - active 判定 = 在途请求(pending/running,含 sync-all ``source_id IS NULL``)
      **或** running 运行行(覆盖 cron 直跑路径);
    - 状态由 ``derive_source_state`` 读时派生(8 词表),无请求且无运行行 → IDLE;
    - sync-all 请求下每源独立呈现(切片已终态的源如实呈现终态,串行队列内
      的源呈现 QUEUED),互不污染。
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        active_requests = (
            (
                await session.execute(
                    select(SyncRequest)
                    .where(SyncRequest.status.in_(("pending", "running")))
                    .order_by(SyncRequest.id)
                )
            )
            .scalars()
            .all()
        )
        sources = (
            (await session.execute(select(DataSource).order_by(DataSource.id))).scalars().all()
        )
    latest_runs = await get_latest_runs_by_source(factory)
    running_runs = await get_running_runs(factory)
    runs_by_request = await get_latest_runs_for_requests(
        factory, [req.id for req in active_requests]
    )

    source_requests: dict[str, SyncRequest] = {
        req.source_id: req for req in active_requests if req.source_id is not None
    }
    sync_all_requests = [req for req in active_requests if req.source_id is None]
    enabled_ids = {ds.id for ds in sources if ds.enabled}
    # 主题集 = enabled 源 ∪ 在途请求源 ∪ running 运行源 ∪ (sync-all 展开到 enabled)
    subjects: set[str] = set(enabled_ids)
    subjects.update(source_requests.keys())
    subjects.update(run.source_id for run in running_runs)
    if sync_all_requests:
        subjects |= enabled_ids

    items: list[SyncStatusItem] = []
    for source_id in sorted(subjects):
        req = _pick_active_request(source_id, source_requests, sync_all_requests)
        run_for_request = runs_by_request.get((req.id, source_id)) if req else None
        latest = latest_runs.get(source_id)
        state = derive_source_state(req, run_for_request, latest)
        view_run = run_for_request if req is not None else latest
        recovering = req is not None and _recovering(req) and state in _ACTIVE_STATES
        items.append(
            SyncStatusItem(
                source_id=source_id,
                state=state,
                request_id=req.id if req else None,
                attempt=(req.attempt_count if req else (view_run.attempt if view_run else None)),
                recovering=recovering,
                stage=view_run.stage if view_run else None,
                stage_current=view_run.stage_current if view_run else None,
                stage_total=view_run.stage_total if view_run else None,
                counters=dict(view_run.counters or {}) if view_run else {},
                execution_device=view_run.execution_device if view_run else None,
                started_at=_iso(view_run.started_at) if view_run else None,
                updated_at=_iso(view_run.updated_at) if view_run else None,
            )
        )
    return SyncStatusResponse(items=items)


# --------------------------------------------------------------------------- #
# GET /sync-runs(#15 per-source 运行历史;delta 全部 run-local 可证明)
# --------------------------------------------------------------------------- #


@router.get("/sync-runs", response_model=SyncRunsResponse)
async def list_sync_runs(
    _: ViewerDep,
    request: Request,
    source_id: str | None = Query(default=None),
    status: str | None = Query(default=None, pattern="^(running|completed|failed|interrupted)$"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> SyncRunsResponse:
    """运行历史分页(started_at 倒序;join sync_log;duration 读侧计算)。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    runs, total = await list_runs(
        factory,
        source_id=source_id,
        status=status,
        offset=(page - 1) * size,
        limit=size,
    )
    logs = await get_sync_logs_by_ids(factory, [r.sync_log_id for r in runs if r.sync_log_id])
    items = [
        SyncRunHistoryItem(
            id=run.id,
            source_id=run.source_id,
            triggered_by=run.triggered_by,
            request_id=run.request_id,
            attempt=run.attempt,
            recovery=run.recovery,
            status=run.status,
            started_at=_iso(run.started_at) or "",
            finished_at=_iso(run.finished_at),
            duration_seconds=_duration_seconds(run),
            stage=run.stage,
            counters=dict(run.counters or {}),
            consistency=dict(run.consistency) if run.consistency else None,
            execution_device=run.execution_device,
            fallback_reason=run.fallback_reason,
            fallback_detail=run.fallback_detail,
            error_summary=run.error_summary,
            ingestion_skipped=is_ingestion_skipped(run.counters, logs.get(run.sync_log_id)),
            sync_log=_log_summary(log) if (log := logs.get(run.sync_log_id)) else None,
        )
        for run in runs
    ]
    return SyncRunsResponse(items=items, total=total, page=page, size=size)


def _log_summary(log: SyncLog) -> SyncRunLogSummary:
    """业务结局摘要;**真实语义命名**:items_updated 是写入 chunk 总数。"""
    return SyncRunLogSummary(
        id=str(log.id),
        status=log.status,
        items_new=log.items_new or 0,
        chunks_written=log.items_updated or 0,
        items_deleted=log.items_deleted or 0,
        items_unchanged=log.items_unchanged or 0,
        error_detail=log.error_detail,
    )


# --------------------------------------------------------------------------- #
# GET /sync-health(#11 五维健康;读时派生,无 SourceHealthSnapshot)
# --------------------------------------------------------------------------- #


def _dim(state: str, evidence: str | None = None, as_of: Any = None) -> HealthDimension:
    return HealthDimension(state=state, evidence=evidence, as_of=_iso(as_of))


def _parse_interval_seconds(raw: str | None) -> float | None:
    r"""``^\d+[hm]$`` → 秒;解析失败返回 None(调用方降级 UNKNOWN,不猜测)。"""
    if not raw:
        return None
    match = _INTERVAL_RE.match(raw)
    if match is None:
        return None
    value, unit = int(match.group(1)), match.group(2)
    return float(value * 3600 if unit == "h" else value * 60)


def _connectivity_dim(latest: SyncRun | None) -> HealthDimension:
    """Connectivity:以最近运行的失败相位作机器证据(DISCOVER/FETCH=连接性)。"""
    if latest is None:
        return _dim("unknown", "no sync_runs evidence")
    if latest.status == RUN_FAILED and latest.stage in (STAGE_DISCOVER, STAGE_FETCH):
        return _dim(
            "failed",
            f"run #{latest.id} failed at {latest.stage}",
            latest.finished_at or latest.started_at,
        )
    if latest.status == RUN_FAILED and latest.stage == STAGE_PARSE:
        return _dim(
            "degraded",
            f"run #{latest.id} failed at PARSE(fetch/extract 异常)",
            latest.finished_at or latest.started_at,
        )
    return _dim(
        "ok", f"latest run #{latest.id} {latest.status}@{latest.stage or '-'}", latest.started_at
    )


def _sync_dim(rows: list[Any], days: int) -> HealthDimension:
    """Sync:30 天窗口业务成功率(与既有 source-health 口径一致,MIN 3 次)。"""
    total = len(rows)
    success = sum(1 for row in rows if row.status == "success")
    as_of = rows[-1].started_at if rows else None
    if total < _MIN_CONFIDENT_SYNCS:
        return _dim(
            "insufficient_data",
            f"{success}/{total} syncs in {days}d (<{_MIN_CONFIDENT_SYNCS})",
            as_of,
        )
    rate = success / total
    state = "healthy" if rate >= 0.9 else ("degraded" if rate >= 0.5 else "critical")
    return _dim(state, f"{success}/{total} syncs succeeded in {days}d", as_of)


def _coverage_dim(latest: SyncRun | None) -> HealthDimension:
    """Coverage:仅 connector 结构化 counters(accepted/extracted)可证明;缺 → unknown。"""
    if latest is None:
        return _dim("unknown", "no sync_runs evidence")
    counters = latest.counters or {}
    accepted = counters.get("accepted")
    extracted = counters.get("extracted")
    if (
        not isinstance(accepted, (int, float))
        or accepted <= 0
        or not isinstance(extracted, (int, float))
    ):
        return _dim("unknown", "no structured coverage counters for this source type")
    ratio = extracted / accepted
    state = "ok" if ratio >= _COVERAGE_OK_RATIO else "partial"
    return _dim(state, f"extracted={int(extracted)}/{int(accepted)} accepted", latest.finished_at)


def _freshness_dim(
    enabled: bool, interval_raw: str | None, last_success: Any, now: datetime
) -> HealthDimension:
    """Freshness:阈值 = 2 × sync_interval;enabled 且从未成功 → stale(不猜 healthy)。"""
    if not enabled:
        return _dim("unknown", "source disabled")
    interval = _parse_interval_seconds(interval_raw)
    if interval is None:
        interval = _DEFAULT_INTERVAL_SECONDS
    threshold = interval * _FRESHNESS_MULTIPLIER
    if last_success is None:
        return _dim("stale", "no successful sync on record", now)
    age = (now - last_success).total_seconds()
    state = "fresh" if age <= threshold else "stale"
    return _dim(state, f"last success {int(age)}s ago (threshold={int(threshold)}s)", now)


def _consistency_dim(latest: SyncRun | None) -> HealthDimension:
    """Consistency:missing/orphan 分别呈现、任一>0 即 degraded;#13 修复事实同维消费。

    Correction Gate(#13→#11):账本身份面事实进同一读时派生——
    - verification_failed 仍最优先(校验不可用 ≠ 判定健康/不健康);
    - missing/orphan 语义不变(degraded);
    - polluted_artifact_chunks>0 或 repair_required=true → degraded:
      历史 unsafe artifact 待修是可见的可行动状态,经既有 overall
      precedence(consistency==degraded → ACTION_REQUIRED)升级;
    - duplicate_doc_count 单独>0 不判不健康(#13 D2:同内容不同合法路径
      为合法共存),仅作信息事实入 evidence;
    - retired/repaired 是本轮已处置量(补救计数),非未决问题,不参与判定。
    """
    if latest is None or not latest.consistency:
        return _dim("unknown", "no consistency evidence")
    facts = latest.consistency
    if "verification_failed" in facts:
        return _dim("unknown", f"verification_failed: {facts['verification_failed']}")
    missing = facts.get("missing") or 0
    orphan = facts.get("orphan_count") or 0
    if missing or orphan:
        return _dim(
            "degraded",
            f"missing={missing} (账本有/向量缺), extra_orphan={orphan} (向量有/账本无)",
            latest.finished_at or latest.started_at,
        )
    polluted = facts.get("polluted_artifact_chunks") or 0
    repair_required = bool(facts.get("repair_required"))
    if polluted or repair_required:
        evidence = (
            f"polluted_artifact_chunks={polluted} (历史 unsafe artifact 待修), "
            f"repair_required={repair_required}"
        )
        if "duplicate_doc_count" in facts:
            evidence += f", duplicate_doc_count={facts['duplicate_doc_count']} (信息事实,合法共存)"
        return _dim("degraded", evidence, latest.finished_at or latest.started_at)
    evidence = (
        f"missing=0, extra_orphan=0 (expected={facts.get('expected_chunks')},"
        f" actual={facts.get('actual_chunks')})"
    )
    if "duplicate_doc_count" in facts:
        evidence += f", duplicate_doc_count={facts['duplicate_doc_count']} (信息事实,合法共存)"
    return _dim("ok", evidence, latest.finished_at or latest.started_at)


def _expected_state_of(source: DataSource) -> str:
    """显式 config.expected_state 优先;缺省 enabled→REQUIRED / disabled→EXCLUDED。

    ⚠️ REQUIRED 默认的 CamThink 生产源清单前置复核尚未在生产行上完成
    (W2 报告「前置复核」节);任何例外源可通过 config.expected_state
    覆盖,无需迁移。
    """
    explicit = (source.config or {}).get("expected_state")
    if explicit in _EXPECTED_STATES:
        return str(explicit)
    return "REQUIRED" if source.enabled else "EXCLUDED"


def _overall_health(
    *,
    expected_state: str,
    recovering: bool,
    document_count: int,
    has_success: bool,
    connectivity: str,
    sync_state: str,
    coverage: str,
    freshness: str,
    consistency: str,
) -> str:
    """聚合:EXCLUDED → RECOVERING overlay → EMPTY_* → worst-of(unknown 不拖低)。

    - EXCLUDED(禁用/显式排除)不被任何 overlay 改写——排除语义最权威;
    - RECOVERING 是 active-run overlay:在途恢复期间不因旧成功记录显示 HEALTHY;
    - EMPTY_* 由 Coverage×expected_state 派生(0 文档 × 从未成功 = 意外空);
    - unknown 维度不参与 worst-of(缺证据 ≠ 不健康,单维如实呈现 unknown)。
    """
    if expected_state == "EXCLUDED":
        return "EXCLUDED"
    if recovering:
        return "RECOVERING"
    if expected_state == "REQUIRED" and document_count == 0 and not has_success:
        return "EMPTY_UNEXPECTED"
    if expected_state in ("OPTIONAL", "DISCOVERY") and document_count == 0:
        return "EMPTY_EXPECTED"
    if connectivity == "failed" or consistency == "degraded" or sync_state == "critical":
        return "ACTION_REQUIRED"
    if freshness == "stale":
        return "STALE"
    if sync_state == "degraded":
        return "DEGRADED"
    if coverage == "partial":
        return "PARTIAL"
    if sync_state == "insufficient_data":
        return "INSUFFICIENT_DATA"
    return "HEALTHY"


@router.get("/sync-health", response_model=SourceHealthResponse)
async def get_source_health(
    _: ViewerDep,
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
) -> SourceHealthResponse:
    """全部数据源五维健康快照(读时派生;无证据 → UNKNOWN/INSUFFICIENT_DATA)。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    now = datetime.now(UTC)
    window_start = now - timedelta(days=days)
    async with factory() as session:
        sources = (
            (await session.execute(select(DataSource).order_by(DataSource.id))).scalars().all()
        )
        window_logs = (
            await session.execute(
                select(
                    SyncLog.source_id,
                    SyncLog.status,
                    SyncLog.started_at,
                )
                .where(SyncLog.started_at >= window_start)
                .order_by(SyncLog.started_at)
            )
        ).all()
        last_success_rows = (
            await session.execute(
                select(
                    SyncLog.source_id,
                    func.max(func.coalesce(SyncLog.finished_at, SyncLog.started_at)),
                )
                .where(SyncLog.status == "success")
                .group_by(SyncLog.source_id)
            )
        ).all()
        active_requests = (
            (
                await session.execute(
                    select(SyncRequest)
                    .where(SyncRequest.status.in_(("pending", "running")))
                    .order_by(SyncRequest.id)
                )
            )
            .scalars()
            .all()
        )
        doc_counts: dict[str, int] = {}
        for source in sources:
            doc_counts[source.id] = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(Document)
                        .where(Document.source_id.like(f"{source.id}/%"))
                    )
                ).scalar()
                or 0
            )
    latest_runs = await get_latest_runs_by_source(factory)
    runs_by_request = await get_latest_runs_for_requests(
        factory, [req.id for req in active_requests]
    )

    logs_by_source: dict[str, list[Any]] = {}
    for row in window_logs:
        logs_by_source.setdefault(row.source_id, []).append(row)
    last_success: dict[str, Any] = {sid: ts for sid, ts in last_success_rows if ts}
    source_requests: dict[str, SyncRequest] = {
        req.source_id: req for req in active_requests if req.source_id is not None
    }
    sync_all_requests = [req for req in active_requests if req.source_id is None]

    items: list[SourceHealthItem] = []
    for source in sources:
        latest = latest_runs.get(source.id)
        req = _pick_active_request(source.id, source_requests, sync_all_requests)
        run_for_request = runs_by_request.get((req.id, source.id)) if req else None
        state = derive_source_state(req, run_for_request, latest)
        recovering = req is not None and _recovering(req) and state in _ACTIVE_STATES

        connectivity = _connectivity_dim(latest)
        sync_dim = _sync_dim(logs_by_source.get(source.id, []), days)
        coverage = _coverage_dim(latest)
        freshness = _freshness_dim(
            source.enabled, source.sync_interval, last_success.get(source.id), now
        )
        consistency = _consistency_dim(latest)
        expected_state = _expected_state_of(source)
        overall = _overall_health(
            expected_state=expected_state,
            recovering=recovering,
            document_count=doc_counts.get(source.id, 0),
            has_success=source.id in last_success,
            connectivity=connectivity.state,
            sync_state=sync_dim.state,
            coverage=coverage.state,
            freshness=freshness.state,
            consistency=consistency.state,
        )
        items.append(
            SourceHealthItem(
                source_id=source.id,
                source_type=source.type,
                enabled=source.enabled,
                expected_state=expected_state,
                overall=overall,
                recovering=recovering,
                document_count=doc_counts.get(source.id, 0),
                connectivity=connectivity,
                sync=sync_dim,
                coverage=coverage,
                freshness=freshness,
                consistency=consistency,
            )
        )
    return SourceHealthResponse(items=items)
