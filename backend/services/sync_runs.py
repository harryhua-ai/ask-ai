"""SyncRun 共享可观测核心(⑪+⑫ Wave-0)。

一行 ``sync_runs`` = ONE SOURCE × ONE ATTEMPT 的运行真相。职责边界(冻结):

- ``sync_requests`` 仍是执行交接/恢复权威(阶段⑨/⑩)——本模块**绝不**
  写请求行、绝不参与 attempt cap / 退避 / 复检判定,只在对账裁决**之后**
  把遥测行盖章为与裁决一致的状态(服从而非第二权威);
- ``sync_log`` 仍是业务历史结局(SyncRun 终态只链接它,不复制其语义);
- 本模块供 sync.py(单写者)与读侧派生(阶段⑪/⑫)共同使用。

进度语义:``stage_total IS NULL`` = 分母未知(增量抓取未 materialize、
crawl 全量轮候选集未定型等),此时 ``progress_fraction`` 返回 None——
调用方**禁止**制造百分比,只允许呈现真实计数(HARD BOUNDARY)。
"""

import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db.models import SyncRequest, SyncRun

logger = logging.getLogger(__name__)

# ---- Canonical progress stages(冻结词表) ----
STAGE_DISCOVER = "DISCOVER"
STAGE_SAFETY_FILTER = "SAFETY_FILTER"
STAGE_FETCH = "FETCH"
STAGE_PARSE = "PARSE"
STAGE_CHUNK = "CHUNK"
STAGE_EMBED = "EMBED"
STAGE_INDEX = "INDEX"
STAGE_CONSISTENCY = "CONSISTENCY"
STAGE_DONE = "DONE"

# ---- SyncRun persistent status(仅真实运行四态) ----
RUN_RUNNING = "running"
RUN_COMPLETED = "completed"
RUN_FAILED = "failed"
RUN_INTERRUPTED = "interrupted"

# ---- Derived run-state vocabulary(由 sync_requests + sync_runs 派生) ----
STATE_IDLE = "IDLE"
STATE_QUEUED = "QUEUED"
STATE_WAITING = "WAITING"
STATE_RUNNING = "RUNNING"
STATE_RECOVERING = "RECOVERING"
STATE_COMPLETED = "COMPLETED"
STATE_FAILED = "FAILED"
STATE_INTERRUPTED = "INTERRUPTED"

RETENTION_DAYS = 30


def progress_fraction(stage_total: int | None, stage_current: int | None) -> float | None:
    """仅当分母存在且 > 0 时返回 0..1 比例;否则 None(禁止假百分比)。"""
    if stage_total is None or stage_total <= 0:
        return None
    if stage_current is None:
        return None
    return max(0.0, min(1.0, stage_current / stage_total))


def serialize_consistency(report) -> dict:
    """VectorGapReport → 结构化 dict(只留计数与集合大小,不塞自由文本)。"""
    return {
        "expected_chunks": report.expected_chunks,
        "actual_chunks": report.actual_chunks,
        "missing": len(report.missing_source_ids),
        "refill": len(report.refill_source_ids),
        "stale_chunk_count": report.stale_chunk_count,
        "orphan_count": report.orphan_count,
    }


async def start_run(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    source_id: str,
    attempt: int = 1,
    request_id: int | None = None,
    recovery: bool = False,
    triggered_by: str = "cron",
) -> SyncRun:
    """创建一条 running 运行行(attempt 启动即落事实,不等同步结束)。"""
    async with session_factory() as session:
        row = SyncRun(
            source_id=source_id,
            attempt=attempt,
            request_id=request_id,
            recovery=recovery,
            triggered_by=triggered_by,
            status=RUN_RUNNING,
            stage=STAGE_DISCOVER,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        session.expunge(row)
    return row


async def update_progress(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: int,
    *,
    stage: str,
    stage_current: int | None = None,
    stage_total: int | None = None,
) -> None:
    """推进 stage 与计数;分母未知就保持 None,绝不伪造。"""
    async with session_factory() as session:
        await session.execute(
            update(SyncRun)
            .where(SyncRun.id == run_id)
            .values(stage=stage, stage_current=stage_current, stage_total=stage_total)
        )
        await session.commit()


async def update_counters(
    session_factory: async_sessionmaker[AsyncSession], run_id: int, **counters: object
) -> None:
    """合并写事实计数(discovered/accepted/extracted/docs_done/chunks_written…)。"""
    async with session_factory() as session:
        row = (await session.execute(select(SyncRun).where(SyncRun.id == run_id))).scalar_one()
        merged = dict(row.counters or {})
        merged.update({k: v for k, v in counters.items() if v is not None})
        await session.execute(update(SyncRun).where(SyncRun.id == run_id).values(counters=merged))
        await session.commit()


async def record_consistency(
    session_factory: async_sessionmaker[AsyncSession], run_id: int, report: dict
) -> None:
    """落一致性校验事实(verify_source_vectors 的结构化结果)。"""
    async with session_factory() as session:
        await session.execute(
            update(SyncRun).where(SyncRun.id == run_id).values(consistency=report)
        )
        await session.commit()


async def finish_run(
    session_factory: async_sessionmaker[AsyncSession],
    run_id: int,
    *,
    status: str,
    error_summary: str | None = None,
    sync_log_id: UUID | None = None,
) -> None:
    """终态落账:completed/failed/interrupted;running 行到此必须有结论。"""
    values: dict = {
        "status": status,
        "finished_at": datetime.now(UTC),
        "stage": STAGE_DONE if status == RUN_COMPLETED else None,
    }
    if error_summary is not None:
        values["error_summary"] = error_summary[:500]
    if sync_log_id is not None:
        values["sync_log_id"] = sync_log_id
    async with session_factory() as session:
        await session.execute(update(SyncRun).where(SyncRun.id == run_id).values(**values))
        await session.commit()


# --------------------------------------------------------------------------- #
# 对账盖章:telemetry 服从 recovery truth(阶段⑩裁决之后的只写遥测)
# --------------------------------------------------------------------------- #


async def complete_runs_with_evidence(
    session_factory: async_sessionmaker[AsyncSession],
    request_id: int,
    evidence_log_ids: dict[str, UUID],
) -> int:
    """孤儿完成吸收:把该 request 的 running 行按证据日志链到 sync_log。

    仅当某源的 terminal sync_log 已存在(实际完成优先,阶段⑩原则)时,
    该源的 running 行 → completed + sync_log_id;无证据的行不动
    (由调用方随后 interrupt)。
    """
    if not evidence_log_ids:
        return 0
    stamped = 0
    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(SyncRun).where(
                        SyncRun.request_id == request_id, SyncRun.status == RUN_RUNNING
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            log_id = evidence_log_ids.get(row.source_id)
            if log_id is None:
                continue
            await session.execute(
                update(SyncRun)
                .where(SyncRun.id == row.id)
                .values(
                    status=RUN_COMPLETED,
                    finished_at=datetime.now(UTC),
                    sync_log_id=log_id,
                    stage=STAGE_DONE,
                )
            )
            stamped += 1
        await session.commit()
    return stamped


async def interrupt_running_runs(
    session_factory: async_sessionmaker[AsyncSession], request_id: int
) -> int:
    """把该 request 的全部 running 行盖章 interrupted(进程被中断是事实)。

    由 reconcile_stale_running 在其裁决分支内调用——attempt 归属、上限、
    退避仍全部由阶段⑩既有逻辑决定,本函数只同步遥测真相。
    """
    async with session_factory() as session:
        result = await session.execute(
            update(SyncRun)
            .where(SyncRun.request_id == request_id, SyncRun.status == RUN_RUNNING)
            .values(status=RUN_INTERRUPTED, finished_at=datetime.now(UTC))
        )
        await session.commit()
        return int(result.rowcount or 0)


# --------------------------------------------------------------------------- #
# Retention:30 天,最小机制(执行面启动时顺手清理;无调度器)
# --------------------------------------------------------------------------- #


async def purge_expired_sync_runs(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    days: int = RETENTION_DAYS,
    now: datetime | None = None,
) -> int:
    """删除 started_at 早于保留期的**非 running**行;running 行绝不清理。"""
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(days=days)
    async with session_factory() as session:
        result = await session.execute(
            delete(SyncRun).where(SyncRun.started_at < cutoff, SyncRun.status != RUN_RUNNING)
        )
        await session.commit()
        return int(result.rowcount or 0)


# --------------------------------------------------------------------------- #
# Derived run state(⑪/⑫ 读侧共用;IDLE 不持久化虚假行)
# --------------------------------------------------------------------------- #


def derive_run_state(
    request: SyncRequest | None, run: SyncRun | None, *, now: datetime | None = None
) -> str:
    """由权威请求行 + 最新运行行派生呈现态(纯函数,可无 DB 测试)。

    优先级:在途请求(执行面权威)→ RUNNING/RECOVERING/WAITING/QUEUED;
    无在途请求 → 最近运行行终态 COMPLETED/FAILED/INTERRUPTED(遗留 running
    视作 RUNNING——等对账盖章的瞬态);两者皆无 → IDLE。
    RECOVERING 属于 Run state:有恢复语义(failure_kind/attempt>1)即在途恢复。
    """
    now = now or datetime.now(UTC)
    if request is not None and request.status in ("pending", "running"):
        recovering = (request.attempt_count or 0) > 1 or request.failure_kind is not None
        if request.status == "running":
            return STATE_RECOVERING if recovering else STATE_RUNNING
        # pending:恢复重试等待 / 排队 / 定时等待
        if recovering:
            return STATE_RECOVERING
        if request.next_retry_at is not None and request.next_retry_at > now:
            return STATE_WAITING
        return STATE_QUEUED
    if run is not None:
        return {
            RUN_RUNNING: STATE_RUNNING,
            RUN_COMPLETED: STATE_COMPLETED,
            RUN_FAILED: STATE_FAILED,
            RUN_INTERRUPTED: STATE_INTERRUPTED,
        }.get(run.status, STATE_RUNNING)
    return STATE_IDLE
