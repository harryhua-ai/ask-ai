"""v1.6.3 Track C(U-11):调度器权威 next_run_at 真值持久化。

冻结语义(DS-P4-03):倒计时 = **scheduler 权威**;调度现实与 sync_interval
不符时禁止纯派生倒计时。本服务是调度真值的唯一维护点:

- 持久化:真值落 ``data_sources.next_run_at`` 列(权威状态,非读时即兴计算);
- reconcile 规则(调度现实优先,任何不构成倒计时的现实 → NULL):
    1. 源禁用 → NULL(UI 诚实呈现「已暂停」);
    2. 存在未完结交接请求(pending/running 同步进行中)→ NULL(UI 呈现
       「同步进行中」——进行中不存在"下次");
    3. 从未同步 → NULL(UI 呈现「等待首次调度」);
    4. 否则 = 最近一次同步完成时间 + sync_interval(区间调度语义);
       已过期仍持久化真实过期时点(UI 呈现「已到期待调度」,不伪装未来)。
- 刷新时机:同步完成(sync_log 落库后由执行面/读面 reconcile)与配置
  变更(sync_interval/enabled PUT)时刷新;读面 reconcile 幂等收敛。

写入点全部经 ``reconcile_next_run_at``;禁止任何前端从 sync_interval 派生。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import DataSource, SyncLog, SyncRequest
from backend.services.source_lifecycle import is_sync_eligible

_INTERVAL_RE = re.compile(r"^(\d+)([hm])$")

# 调度真值状态词表(UI 呈现映射的唯一权威值域)
SCHEDULE_STATE_SCHEDULED = "scheduled"  # next_run_at 非空,倒计时有效
SCHEDULE_STATE_SYNCING = "syncing"  # 同步进行中,无"下次"
SCHEDULE_STATE_PAUSED = "paused"  # 源禁用
SCHEDULE_STATE_WAITING_FIRST = "waiting_first"  # 从未同步,等待首次调度
SCHEDULE_STATE_DELETING = "deleting"  # 删除流程中,调度停摆


def parse_interval_seconds(interval: str | None) -> int | None:
    """sync_interval 表达式("6h"/"30m")→ 秒;不合法 → None。"""
    m = _INTERVAL_RE.match((interval or "").strip())
    if not m:
        return None
    n = int(m.group(1))
    return n * 3600 if m.group(2) == "h" else n * 60


def is_due(next_run_at: datetime | None, now: datetime) -> bool:
    """判断自动调度资格；NULL 表示等待首次调度，因此可执行。"""
    if next_run_at is None:
        return True
    if next_run_at.tzinfo is None and now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    elif next_run_at.tzinfo is not None and now.tzinfo is None:
        now = now.replace(tzinfo=next_run_at.tzinfo)
    return next_run_at <= now


def should_run_source(
    *, next_run_at: datetime | None, now: datetime, triggered_by: str
) -> bool:
    """手动触发绕过 due gate；cron/其它自动触发必须到期。"""
    if triggered_by == "manual":
        return True
    return is_due(next_run_at, now)


async def _has_inflight_request(session: AsyncSession, source_id: str) -> bool:
    """是否存在未完结交接请求(pending/running = 同步进行中的调度现实)。"""
    row = await session.execute(
        select(func.count())
        .select_from(SyncRequest)
        .where(
            SyncRequest.source_id == source_id,
            SyncRequest.status.in_(["pending", "running"]),
        )
    )
    return int(row.scalar() or 0) > 0


async def _last_sync_finished_at(session: AsyncSession, source_id: str) -> datetime | None:
    """最近一次成功同步完成时点(finished_at 优先,回退 started_at)。"""
    row = await session.execute(
        select(SyncLog.finished_at, SyncLog.started_at)
        .where(SyncLog.source_id == source_id, SyncLog.status == "success")
        .order_by(SyncLog.started_at.desc())
        .limit(1)
    )
    rec = row.first()
    if rec is None:
        return None
    return rec[0] or rec[1]


def compute_next_run_at(
    *,
    enabled: bool,
    lifecycle_state: str | None,
    has_inflight: bool,
    last_finished_at: datetime | None,
    interval_seconds: int | None,
) -> datetime | None:
    """调度真值纯函数(reconcile 规则;NULL = 调度现实不构成倒计时)。"""
    if not enabled:
        return None
    if not is_sync_eligible(lifecycle_state):
        return None  # 删除在途/失败:调度停摆
    if has_inflight:
        return None  # 同步进行中:完成后再刷新(执行面/读面 reconcile)
    if interval_seconds is None:
        return None
    if last_finished_at is None:
        return None  # 从未同步:等待首次调度,不虚构首次时点
    return last_finished_at + timedelta(seconds=interval_seconds)


async def reconcile_next_run_at(session: AsyncSession, ds: DataSource) -> datetime | None:
    """reconcile 并持久化单源调度真值(幂等;返回权威 next_run_at)。"""
    inflight = await _has_inflight_request(session, ds.id)
    last_finished = await _last_sync_finished_at(session, ds.id)
    value = compute_next_run_at(
        enabled=bool(ds.enabled),
        lifecycle_state=ds.lifecycle_state,
        has_inflight=inflight,
        last_finished_at=last_finished,
        interval_seconds=parse_interval_seconds(ds.sync_interval),
    )
    # 30 秒内抖动不回写(避免读面反复 UPDATE);其余差异收敛持久化
    current = ds.next_run_at
    if current is not None and value is not None and abs((current - value).total_seconds()) < 30:
        return current
    if current != value:
        ds.next_run_at = value
        await session.commit()
    return value


def schedule_state_of(ds: DataSource, has_inflight: bool) -> str:
    """调度现实状态词表(呈现映射唯一权威;与 next_run_at NULL 语义一致)。"""
    if not ds.enabled:
        return SCHEDULE_STATE_PAUSED
    if not is_sync_eligible(ds.lifecycle_state):
        return SCHEDULE_STATE_DELETING
    if has_inflight:
        return SCHEDULE_STATE_SYNCING
    if ds.next_run_at is None:
        return SCHEDULE_STATE_WAITING_FIRST
    return SCHEDULE_STATE_SCHEDULED


async def inflight_request_map(session: AsyncSession, source_ids: list[str]) -> dict[str, bool]:
    """批量查询进行中交接请求(列表读面 reconcile 用)。"""
    if not source_ids:
        return {}
    rows = await session.execute(
        select(SyncRequest.source_id, func.count())
        .where(
            SyncRequest.source_id.in_(source_ids),
            SyncRequest.source_id.is_not(None),
            SyncRequest.status.in_(["pending", "running"]),
        )
        .group_by(SyncRequest.source_id)
    )
    return {row[0]: True for row in rows.all() if row[0]}


def truth_payload(ds: DataSource, state: str) -> dict[str, Any]:
    """调度真值响应(权威值原样;interval 仅作周期配置呈现,不参与倒计时)。"""
    return {
        "source_id": ds.id,
        "next_run_at": ds.next_run_at.isoformat() if ds.next_run_at else None,
        "state": state,
        "sync_interval": ds.sync_interval,
        "enabled": bool(ds.enabled),
    }
