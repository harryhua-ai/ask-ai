"""同步执行交接客户端(ONLINE PLANE → SYNC EXECUTION PLANE)。

阶段⑨ FINAL(Planner PARTIAL 修正):backend 不再自行派生同步子进程
(进程级 setsid 隔离挡不住 Docker 容器生命周期 —— backend 容器重启/
重建会连带终止容器内全部进程)。改为**DB 交接**:触发 = 向
``sync_requests`` 表写入一行持久请求;独立 ``sync-executor`` 容器
(``scripts/sync_executor_loop.py``)轮询领用并运行 ``scripts/sync.py``。

    backend 容器 ── INSERT pending ──▶ sync_requests(Postgres)
                                            │ claim(FOR UPDATE SKIP LOCKED)
                                            ▼
                              sync-executor 容器 ──▶ scripts/sync.py

- **accepted = 请求已持久进入执行面交接队列**(DB commit 成功),
  不是 sync success;业务结果仍以 sync_log 为准。
- 同 key 已有 pending/running 请求 → already-running,不重复入队
  (§11 最低并发安全;执行面本身串行,不会并发打 GPU)。
- 执行面容器短时不可用 ≠ 交接失败:请求持久滞留 pending,执行面恢复
  后照常领用(比子进程 spawn 更强的提交语义)。
- source_id 是**数据参数**(存入行字段),绝不构成命令字符串。
"""

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import SyncRequest

logger = logging.getLogger(__name__)

# 视为"在途"的状态:阻塞同 key 重复入队
_ACTIVE_STATES = ("pending", "running")


class SyncRequestSubmitError(RuntimeError):
    """交接请求写入失败(DB 不可用等)—— 调用方必须显式报错,不伪装 accepted。"""


@dataclass
class SyncSubmit:
    """submit_sync_request 结果:state ∈ {"accepted", "already-running"}。"""

    state: str
    request_id: int | None


async def find_active_request(session: AsyncSession, source_id: str | None) -> SyncRequest | None:
    """返回同 key(source_id 或 sync-all 的 NULL)最新在途请求;无则 None。"""
    key_filter = (
        SyncRequest.source_id.is_(None) if source_id is None else SyncRequest.source_id == source_id
    )
    result = await session.execute(
        select(SyncRequest)
        .where(SyncRequest.status.in_(_ACTIVE_STATES), key_filter)
        .order_by(SyncRequest.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def submit_sync_request(
    session: AsyncSession, source_id: str | None, *, triggered_by: str = "manual"
) -> SyncSubmit:
    """把一次手动同步持久交接给独立执行面:写 pending 行并提交。

    Args:
        session: 请求作用域的异步会话(提交失败时由调用方回滚/报错)。
        source_id: 单源同步的源 ID;``None`` 表示同步全部启用源。
        triggered_by: 记入请求行,执行面透传给 ``sync.py --triggered-by``。

    Returns:
        SyncSubmit(accepted 携带新请求 id;already-running 携带在途 id)。

    Raises:
        SyncRequestSubmitError: 写库失败 —— HTTP 层必须映射为明确失败。
    """
    active = await find_active_request(session, source_id)
    if active is not None:
        logger.warning(
            "同步请求已在交接队列在途,跳过重复提交: key=%s request_id=%d status=%s",
            "sync-all" if source_id is None else source_id,
            active.id,
            active.status,
        )
        return SyncSubmit(state="already-running", request_id=active.id)
    req = SyncRequest(source_id=source_id, triggered_by=triggered_by, status="pending")
    session.add(req)
    try:
        await session.commit()
    except Exception as exc:  # 交接失败必须显式上抛(HTTP 502),非盲捕获
        raise SyncRequestSubmitError(f"交接请求写入失败: {exc}") from exc
    await session.refresh(req)
    logger.warning(
        "同步请求已交接独立执行面: request_id=%d key=%s triggered_by=%s",
        req.id,
        "sync-all" if source_id is None else source_id,
        triggered_by,
    )
    return SyncSubmit(state="accepted", request_id=req.id)
