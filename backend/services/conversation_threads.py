"""#87:会话(Thread)确定性边界算法。

冻结语义(CONVERSATION-REVIEW-PRODUCT-UI-CONTRACT-20260917 §Thread boundary):
- 归组键 = (session_id, site_id, channel):同键、按时间排序后相邻间隔
  ``<= 30 分钟`` ⇒ 同一 Thread;间隔 > 30min / site 变化 / transport 变化 ⇒ 分裂;
  仅跨零点不分裂(间隔按时长计算,与墙上时刻无关)。
- ``session_id`` 缺失的历史行 = 诚实 singleton(每行自成一线程),不猜测归组。
- thread_id 由线程首条 Turn 的 id 确定性派生(短、稳定、跨请求一致),
  不引入额外持久化状态。
- 纯函数、无 I/O;输入行的字段面只有 id/session_id/site_id/channel/created_at
  —— 不读问题文本、不做任何语义/身份推断(AC1/AC6)。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta

# 冻结边界:不活动间隔上限(契约明文 <=30 分钟;不做配置化以免语义漂移)
THREAD_INACTIVITY_GAP = timedelta(minutes=30)


@dataclass(frozen=True)
class ThreadGroup:
    """一条有界 Review Thread(轮次按时间升序)。"""

    thread_id: str
    session_id: str | None
    site_id: str | None
    channel: str | None
    turn_ids: tuple[str, ...]
    started_at: datetime
    last_activity_at: datetime

    @property
    def turn_count(self) -> int:
        return len(self.turn_ids)


def _derive_thread_id(first_turn_id: str) -> str:
    digest = hashlib.sha256(str(first_turn_id).encode("utf-8")).hexdigest()[:10]
    return f"thread_{digest}"


def build_threads(rows) -> list[ThreadGroup]:
    """把会话轻量行聚合成有界线程列表(无序输入容忍,内部按时间排序)。

    Args:
        rows: 具有 ``id / session_id / site_id / channel / created_at`` 的行。

    Returns:
        按 ``last_activity_at`` 降序的线程列表(展示序由调用方决定时也可重排)。
    """
    turn = sorted(rows, key=lambda r: r.created_at)

    groups: dict[tuple, list] = {}
    order: list[tuple] = []
    legacy_rows: list = []
    for row in turn:
        if row.session_id is None:
            legacy_rows.append(row)
            continue
        key = (row.session_id, row.site_id, row.channel)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(row)

    threads: list[ThreadGroup] = []
    for key in order:
        key_rows = groups[key]
        current: list = [key_rows[0]]
        for row in key_rows[1:]:
            assert current, "current 非空不变量"
            if row.created_at - current[-1].created_at > THREAD_INACTIVITY_GAP:
                threads.append(_make_thread(current))
                current = []
            current.append(row)
        if current:
            threads.append(_make_thread(current))

    # legacy:无 session_id 的行各自成线程(诚实 singleton)
    for row in legacy_rows:
        threads.append(_make_thread([row]))

    threads.sort(key=lambda t: t.last_activity_at, reverse=True)
    return threads


def _make_thread(rows: list) -> ThreadGroup:
    first = rows[0]
    last = rows[-1]
    return ThreadGroup(
        thread_id=_derive_thread_id(first.id),
        session_id=first.session_id,
        site_id=first.site_id,
        channel=first.channel,
        turn_ids=tuple(r.id for r in rows),
        started_at=first.created_at,
        last_activity_at=last.created_at,
    )
