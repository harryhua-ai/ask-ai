"""缺口观察状态机(U-15;Ownership: Track E Wave 1,IF-1 挂载实现)。

权威语义(track-e-contract.md U-15 冻结):
- 状态机:OPEN → OBSERVING → RESOLVED,唯一权威持久真值 =
  ``question_clusters.status``(词表 IF-1 = backend/services/gap_status.py)+
  本服务的观察元数据(gap_observations)与流转事件(gap_observation_events)。
- 进入 OBSERVING 三前置(全部满足,缺一不可,任一失败 → 409 不转移):
    ① 操作者确认内容修复完成(``confirmed=True`` 请求语义);
    ② 相关源 sync/reindex 成功 —— 相关源集合 = 缺口归属会话引用证据
       (conversations.sources[*].source_id 的数据源前缀;证据规则见
       ``derive_gap_source_ids``),每个相关源在 sync_runs 的最新一行必须
       status=completed(真实读 sync_runs,不Mock);
    ③ post-sync 验证成功 —— 上述最新 completed run 的 consistency 结构化
       事实(sync_runs.record_consistency 落账的 verify_source_vectors 结果)
       必须存在且健康(missing=0 / refill=0 / orphan_count=0);NULL=未知 →
       拒绝(不推断)。
- 观察窗默认 7 天(window_ends_at 持久化);OBSERVING 期间同一 gap 证据
  失败复现(观察开始后新归属会话证据)→ 回 OPEN;满窗无复现 → RESOLVED;
  操作者可中止 → OPEN。**禁止任何直接手动 RESOLVED 路径** —— RESOLVED 的
  唯一进入方式 = 满窗无复现评估,且判定必须持久化(lazy-on-read 或显式
  evaluate 端点触发;本服务同时被两者复用)。
- 全部转移:gap_observations(元数据封闭)+ gap_observation_events
  (append-only 事件,时间戳/actor/from→to)持久化,可审计、History 可见。

与 Track D/F 边界:本服务不消费原因分类词表(gap_taxonomy),不做用户
聚合(gap→source 前缀推导仅服务于同步核验前置,不是 U-18 的归因投影)。
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import (
    Conversation,
    GapObservation,
    GapObservationEvent,
    QuestionCluster,
    SyncRun,
)

# ---- 观察窗默认(冻结语义:7 天) ----
OBSERVATION_WINDOW_DAYS_DEFAULT = 7

# ---- 流转事件词表(gap_observation_events.event_type;append-only) ----
EVENT_START = "start"
EVENT_RECURRENCE = "recurrence"
EVENT_ABORT = "abort"
EVENT_RESOLVE = "resolve"

# ---- gap_observations.ended_reason 词表 ----
ENDED_RECURRENCE = "recurrence"
ENDED_ABORTED = "aborted"
ENDED_WINDOW_ELAPSED = "window_elapsed"

# ---- sync 门失败原因码(gates 明细机器真值) ----
SYNC_NO_EVIDENCE = "no_sync_evidence"
SYNC_NOT_COMPLETED = "last_sync_not_completed"
VERIFY_NO_FACT = "no_consistency_evidence"
VERIFY_UNHEALTHY = "consistency_unhealthy"
SYNC_NO_RELATED_SOURCE = "no_related_source_evidence"


class ObservationGateError(Exception):
    """前置门未通过(进入 OBSERVING 被拒)。``gates`` = 机器可读失败明细。"""

    def __init__(self, code: str, gates: dict[str, Any] | None = None):
        super().__init__(code)
        self.code = code
        self.gates: dict[str, Any] = gates or {}


class ObservationStateError(Exception):
    """非法状态转移(如重复 start / 非 OBSERVING 中止)。"""

    def __init__(self, code: str, from_status: str):
        super().__init__(code)
        self.code = code
        self.from_status = from_status


@dataclass(frozen=True)
class SyncGateReport:
    """前置②③核验报告(真实读 sync_runs 的结论)。"""

    ok: bool
    sync: dict[str, str] = field(default_factory=dict)  # source_id → 失败原因码
    verification: dict[str, str] = field(default_factory=dict)


def derive_gap_source_ids(sources_rows: list[list[Any]]) -> list[str]:
    """缺口归属会话引用证据 → 相关数据源 id 集合(去重、稳定序)。

    证据规则:conversation.sources[*].source_id 形如
    ``{data_source_id}/{document_slug}``(灌入管道身份;verify_source_vectors
    同一前缀语义)。取 ``/`` 前缀即数据源 id;无 ``/`` 的裸值按整值处理
    (健壮性;不猜测、不补全)。
    """
    ids: set[str] = set()
    for sources in sources_rows:
        if not isinstance(sources, list):
            continue
        for entry in sources:
            if not isinstance(entry, dict):
                continue
            sid = entry.get("source_id")
            if isinstance(sid, str) and sid:
                ids.add(sid.split("/", 1)[0] or sid)
    return sorted(ids)


async def check_sync_gates(session: AsyncSession, source_ids: list[str]) -> SyncGateReport:
    """前置②③:每个相关源的 sync_runs 最新一行必须 completed 且携带健康
    consistency 事实(真实读 DB;同步核验与 post-sync 验证钩子)。"""
    sync_fail: dict[str, str] = {}
    verify_fail: dict[str, str] = {}
    for sid in source_ids:
        run = (
            (
                await session.execute(
                    select(SyncRun)
                    .where(SyncRun.source_id == sid)
                    .order_by(SyncRun.started_at.desc(), SyncRun.id.desc())
                    .limit(1)
                )
            )
            .scalars()
            .first()
        )
        if run is None:
            sync_fail[sid] = SYNC_NO_EVIDENCE
            continue
        if run.status != "completed":
            sync_fail[sid] = SYNC_NOT_COMPLETED
            continue
        consistency = run.consistency if isinstance(run.consistency, dict) else None
        if consistency is None:
            verify_fail[sid] = VERIFY_NO_FACT
            continue
        unhealthy = (
            int(consistency.get("missing", 0) or 0) > 0
            or int(consistency.get("refill", 0) or 0) > 0
            or int(consistency.get("orphan_count", 0) or 0) > 0
        )
        if unhealthy:
            verify_fail[sid] = VERIFY_UNHEALTHY
    return SyncGateReport(
        ok=not sync_fail and not verify_fail, sync=sync_fail, verification=verify_fail
    )


async def _related_source_ids(session: AsyncSession, cluster_id: str) -> list[str]:
    rows = await session.execute(
        select(Conversation.sources).where(Conversation.cluster_id == cluster_id)
    )
    return derive_gap_source_ids([r for r in rows.scalars()])


async def _add_event(
    session: AsyncSession,
    cluster_id: str,
    event_type: str,
    from_status: str,
    to_status: str,
    actor: str | None,
    detail: dict[str, Any] | None = None,
) -> None:
    session.add(
        GapObservationEvent(
            cluster_id=cluster_id,
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            actor=actor,
            detail=detail or {},
        )
    )


async def start_observation(
    session: AsyncSession,
    cluster: QuestionCluster,
    *,
    actor: str,
    confirmed: bool,
    window_days: int = OBSERVATION_WINDOW_DAYS_DEFAULT,
) -> GapObservation:
    """OPEN → OBSERVING(三前置门;调用方负责先校验 gap 存在)。

    成功:更新 cluster.status、落 gap_observations 行(观察窗元数据)与
    start 流转事件,由调用方 commit。任一前置失败抛 ObservationGateError,
    状态零变化。
    """
    if cluster.status != "open":
        raise ObservationStateError("invalid_state", cluster.status)
    gates: dict[str, Any] = {}
    # 前置①:操作者确认内容修复完成
    if not confirmed:
        gates["confirmation"] = False
    # 前置②③:相关源 sync/reindex 成功 + post-sync 验证成功(真实读 sync_runs)。
    # 无相关源引用证据 → 无法核验同步真相,诚实拒绝(不推断成功)。
    source_ids = await _related_source_ids(session, str(cluster.id))
    if not source_ids:
        gates["sync"] = {SYNC_NO_RELATED_SOURCE: SYNC_NO_EVIDENCE}
    else:
        report = await check_sync_gates(session, source_ids)
        if not report.ok:
            gates["sync"] = report.sync
            gates["verification"] = report.verification
    if gates:
        raise ObservationGateError("gate_failed", gates)

    now = datetime.now(UTC)
    cluster.status = "observing"
    observation = GapObservation(
        cluster_id=cluster.id,
        started_at=now,
        window_days=window_days,
        window_ends_at=now + timedelta(days=window_days),
        is_active=True,
    )
    session.add(observation)
    await session.flush()
    await _add_event(
        session,
        str(cluster.id),
        EVENT_START,
        "open",
        "observing",
        actor,
        {"window_days": window_days, "sources": await _related_source_ids(session, str(cluster.id))},
    )
    return observation


async def count_recurrence_evidence(
    session: AsyncSession, cluster_id: str, started_at: datetime
) -> int:
    """复现证据计数:观察开始后新归属该聚类的会话数(同一 gap 证据失败复现)。"""
    total = await session.execute(
        select(func.count())
        .select_from(Conversation)
        .where(Conversation.cluster_id == cluster_id, Conversation.created_at > started_at)
    )
    return int(total.scalar() or 0)


async def evaluate_observation(
    session: AsyncSession, cluster: QuestionCluster
) -> dict[str, Any] | None:
    """对单个 OBSERVING 聚类执行窗口评估(判定持久化;调用方 commit)。

    - 复现(观察开始后新归属会话证据 > 0)→ 回 OPEN,ended_reason=recurrence;
    - 满窗(now >= window_ends_at)无复现 → RESOLVED,ended_reason=window_elapsed
      (RESOLVED 唯一进入路径);
    - 窗内无复现 → 不转移(None)。
    返回转移摘要 dict 或 None。
    """
    if cluster.status != "observing":
        return None
    observation = (
        (
            await session.execute(
                select(GapObservation)
                .where(
                    GapObservation.cluster_id == cluster.id,
                    GapObservation.is_active.is_(True),
                )
                .order_by(GapObservation.started_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    if observation is None:
        return None
    cid = str(cluster.id)
    recurrence = await count_recurrence_evidence(session, cid, observation.started_at)
    now = datetime.now(UTC)
    if recurrence > 0:
        cluster.status = "open"
        observation.is_active = False
        observation.ended_at = now
        observation.ended_reason = ENDED_RECURRENCE
        await _add_event(
            session, cid, EVENT_RECURRENCE, "observing", "open", None,
            {"new_evidence_count": recurrence},
        )
        return {"gap_id": cid, "to_status": "open", "reason": ENDED_RECURRENCE}
    if now >= observation.window_ends_at:
        cluster.status = "resolved"
        observation.is_active = False
        observation.ended_at = now
        observation.ended_reason = ENDED_WINDOW_ELAPSED
        await _add_event(
            session, cid, EVENT_RESOLVE, "observing", "resolved", None,
            {"window_days": observation.window_days},
        )
        return {"gap_id": cid, "to_status": "resolved", "reason": ENDED_WINDOW_ELAPSED}
    return None


async def abort_observation(
    session: AsyncSession, cluster: QuestionCluster, *, actor: str
) -> GapObservation:
    """操作者中止 OBSERVING → OPEN(禁止把中止表达为 resolved)。"""
    if cluster.status != "observing":
        raise ObservationStateError("invalid_state", cluster.status)
    observation = (
        (
            await session.execute(
                select(GapObservation)
                .where(
                    GapObservation.cluster_id == cluster.id,
                    GapObservation.is_active.is_(True),
                )
                .order_by(GapObservation.started_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    now = datetime.now(UTC)
    cluster.status = "open"
    if observation is not None:
        observation.is_active = False
        observation.ended_at = now
        observation.ended_reason = ENDED_ABORTED
    await _add_event(session, str(cluster.id), EVENT_ABORT, "observing", "open", actor)
    return observation


async def serialize_observation_state(
    session: AsyncSession, cluster: QuestionCluster
) -> dict[str, Any]:
    """观察状态投影(侧板观察区/History 数据源;先评估后读,判定持久化)。"""
    observation = (
        (
            await session.execute(
                select(GapObservation)
                .where(GapObservation.cluster_id == cluster.id)
                .order_by(GapObservation.started_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    recurrence: dict[str, Any] | None = None
    if cluster.status == "observing" and observation is not None:
        n = await count_recurrence_evidence(session, str(cluster.id), observation.started_at)
        recurrence = {"recurred": n > 0, "new_evidence_count": n}
    return {
        "gap_id": str(cluster.id),
        "status": cluster.status,
        "observation": None
        if observation is None
        else {
            "started_at": observation.started_at.isoformat() if observation.started_at else None,
            "window_days": observation.window_days,
            "window_ends_at": observation.window_ends_at.isoformat()
            if observation.window_ends_at
            else None,
            "is_active": observation.is_active,
            "ended_at": observation.ended_at.isoformat() if observation.ended_at else None,
            "ended_reason": observation.ended_reason,
        },
        "recurrence": recurrence,
    }
