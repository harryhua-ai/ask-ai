"""独立同步执行面主循环(SYNC EXECUTION PLANE,部署级容器隔离)。

阶段⑨ FINAL(Planner PARTIAL 修正):backend 容器内 detached 子进程
挡不住 Docker 容器生命周期(``docker compose restart backend`` /
``--force-recreate`` / 镜像替换会终止容器内全部进程)。本脚本部署为
**独立 ``sync-executor`` 容器服务**(compose anchor 与 backend 同镜像 /
env / 卷 / GPU),把执行面真正移出 backend 容器:

    backend 容器 ── INSERT pending(交接)──▶ sync_requests(Postgres)
                                                  │ 领用(FOR UPDATE SKIP LOCKED)
                                                  ▼
                            本循环(独立容器)── 子进程 ──▶ scripts/sync.py

阶段⑩ 恢复语义(冻结):
- **检测**:执行面启动对账遗留 running —— 以 sync_log 执行事实分流:
  单源已有 terminal 事实 → 本次执行实际完成 → done(E1 假阴性修复);
  无完成事实(含 sync-all 保守不做推断)→ interrupted → 延迟恢复;
- **有界重试**:runner 非零退出 / spawn 失败 → attempt_count+1 已计入,
  按 30/120/600s 退避安排 pending(next_retry_at);MAX_TOTAL_ATTEMPTS=4,
  第 4 次仍失败 → terminal failed。**禁止无限重试**;
- **恢复重放**:attempt>1 的重试对 GitHub 增量附带
  ``--force-incremental-replay``(关闭 remote-SHA 短路,按 last-success
  边界重读 git 历史,F16 修复);
- **孤儿复检**:interrupted 重试到期、真正启动前再查一次 sync_log ——
  等待期孤儿 runner 已完成 → 直接 done,不二次执行。

设计要点
--------
- **ONE BUSINESS SYNC IMPLEMENTATION**:领用后以子进程运行
  ``scripts/sync.py``(manual/scheduled/CLI/recovery 同一 runner);
  source_id / triggered_by / 恢复上下文以 argv 数据参数传递,无 shell。
- **串行执行是特性**:一次领用一个请求,跑完再取下一个 —— 单 GPU 不被
  并发 embed 打爆。
- **status 是交接/进程级语义**:done/failed 记录 runner 进程结果;业务
  成败以 sync_log 为准(JOB SUCCESS ≠ KNOWLEDGE HEALTH)。业务级
  failed/partial(runner 正常退出)不属于本恢复调度范围(§14)。
- 持久状态仍四态(pending/running/done/failed);INTERRUPTED/RETRYING
  为派生呈现态,不入库。

用法(容器 entrypoint / 本地开发):
    python scripts/sync_executor_loop.py
"""

import asyncio
import logging
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, or_, select, update

# 让脚本直接执行时也能导入 backend 包(与 scripts/sync.py 同约定)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import Settings, load_settings
from backend.db.models import SyncLog, SyncRequest
from backend.db.session import get_engine, get_session_factory, init_db

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
SYNC_SCRIPT = REPO_ROOT / "scripts" / "sync.py"

# 交接队列轮询间隔(秒)。手动同步启动延迟上界 ≈ 一个轮询周期 + 当前在跑行程。
POLL_INTERVAL_SECONDS = 2.0

# ---- 阶段⑩ 恢复策略(冻结值) ----
# attempt_count = 实际启动过的 runner 次数(首次启动=1);上限 = 1 + 3 次恢复。
MAX_TOTAL_ATTEMPTS = 4
# 第 N 次实际执行失败后的恢复退避(秒):retry#1→30s、#2→120s、#3→600s。
DEFAULT_BACKOFF_SECONDS = (30, 120, 600)


def _backoff_seconds() -> tuple[int, int, int]:
    """恢复退避秒数;测试/本地 harness 可经环境变量注入短值(生产默认 30/120/600)。"""
    raw = os.environ.get("SYNC_RETRY_BACKOFF_SECONDS")
    if not raw:
        return DEFAULT_BACKOFF_SECONDS
    try:
        parts = tuple(int(x) for x in raw.split(","))
        if len(parts) == 3:
            return parts  # type: ignore[return-value]
    except ValueError:
        pass
    logger.warning("SYNC_RETRY_BACKOFF_SECONDS 格式非法(%r),回退默认退避", raw)
    return DEFAULT_BACKOFF_SECONDS


def build_runner_argv(
    source_id: str | None, triggered_by: str, *, recovery: bool = False
) -> list[str]:
    """构造 sync runner argv(逐元素列表,无 shell)。

    与 cron(``python3 scripts/sync.py``)、CLI 同一脚本入口;
    ``--triggered-by`` 保留 sync_log 触发方语义(sync-all 若不显式标记
    会被旧规则误记为 cron)。

    ``recovery=True``(恢复重试,attempt_count>1)时附加
    ``--force-incremental-replay``:关闭 GitHub 增量的 remote-SHA 短路,
    强制按 last-success 边界重读 git 历史(F16 修复);其余 connector
    忽略该上下文。
    """
    argv = [sys.executable, str(SYNC_SCRIPT), "--triggered-by", triggered_by]
    if recovery:
        argv.append("--force-incremental-replay")
    if source_id is not None:
        argv += ["--source", source_id]
    return argv


async def _has_terminal_sync_log_after(session_factory, source_id: str, picked_at) -> bool:
    """查询某源在 picked_at 之后是否已有 terminal sync_log(该次执行的事实证据)。

    任意 terminal 状态(success/partial/failed)都证明 runner 走完了自己的
    执行(业务成败按 Contract §14 不归本恢复调度)。
    """
    if picked_at is None:
        return False
    async with session_factory() as session:
        result = await session.execute(
            select(SyncLog.id)
            .where(
                SyncLog.source_id == source_id,
                SyncLog.status.in_(["success", "partial", "failed"]),
                func.coalesce(SyncLog.finished_at, SyncLog.started_at) >= picked_at,
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None


async def reconcile_stale_running(session_factory) -> dict[str, int]:
    """执行面启动对账:以 sync_log 执行事实分流遗留 running 行(替代一律 failed)。

    分流顺序(Planner FINAL REVIEW CORRECTION A 冻结):
      1. 单源且 picked_at 后已有 terminal sync_log → 实际完成 → **done**
         (事实优先;E1 假阴性修复;不受 attempt cap 影响);
      2. 否则 attempt_count >= MAX_TOTAL_ATTEMPTS → **terminal failed**
         (failure_kind=interrupted、next_retry_at=NULL、finished_at 落值,
         永不再 claim —— 中断路径同样受上限约束,不得出现第 5 次启动);
      3. 否则 → interrupted:pending + next_retry_at(≥ 一个退避),并保留
         证据锚 ``attempt_started_at = picked_at``(被中断 attempt 的执行
         开始时间)——retry claim 会覆盖 picked_at,孤儿完成复检必须锚定
         本列(CORRECTION B);attempt_count 不在对账时递增。
    """
    stats = {"finalized_done": 0, "scheduled_retry": 0, "terminal_failed": 0}
    backoff = _backoff_seconds()
    async with session_factory() as session:
        rows = (
            (await session.execute(select(SyncRequest).where(SyncRequest.status == "running")))
            .scalars()
            .all()
        )
        for row in rows:
            if row.source_id is not None and await _has_terminal_sync_log_after(
                session_factory, row.source_id, row.picked_at
            ):
                row.status = "done"
                row.finished_at = func.now()
                row.error = None
                stats["finalized_done"] += 1
                logger.warning(
                    "stale running 对账: request_id=%d 的源 %s 已有完成事实 → done(不重跑)",
                    row.id,
                    row.source_id,
                )
            elif int(row.attempt_count or 0) >= MAX_TOTAL_ATTEMPTS:
                row.status = "failed"
                row.failure_kind = "interrupted"
                row.next_retry_at = None
                row.finished_at = func.now()
                row.error = (
                    f"中断检测且已达 MAX_TOTAL_ATTEMPTS={MAX_TOTAL_ATTEMPTS},"
                    "终态失败(不再自动恢复,需人工重新触发)"
                )
                stats["terminal_failed"] += 1
                logger.warning(
                    "stale running 对账: request_id=%d attempt=%d 已达上限 → 终态失败",
                    row.id,
                    row.attempt_count,
                )
            else:
                attempt = max(int(row.attempt_count or 0), 1)
                delay = backoff[min(attempt, len(backoff)) - 1]
                retry_at = datetime.now(UTC) + timedelta(seconds=delay)
                row.status = "pending"
                row.failure_kind = "interrupted"
                row.next_retry_at = retry_at
                row.attempt_started_at = row.picked_at  # 证据锚(被中断 attempt 的开始时间)
                row.error = (
                    "中断检测(上次运行无完成事实),已安排恢复重试于 "
                    f"{retry_at.isoformat()}(attempt={attempt}/{MAX_TOTAL_ATTEMPTS})"
                )
                stats["scheduled_retry"] += 1
                logger.warning(
                    "stale running 对账: request_id=%d 无完成事实 → interrupted,恢复重试安排于 %s",
                    row.id,
                    retry_at.isoformat(),
                )
        await session.commit()
    return stats


async def claim_next(session_factory) -> SyncRequest | None:
    """原子领用最旧的**到期** pending 请求(FOR UPDATE SKIP LOCKED,多副本安全)。

    - ``next_retry_at IS NULL OR next_retry_at <= now()``:未来恢复重试不可领;
    - **不在此处递增 attempt_count**:递增只随真实 runner 启动发生
      (execute_request,Planner CORRECTION B——领用会覆盖 picked_at,
      attempt 语义与证据锚必须分离)。
    """
    async with session_factory() as session:
        subq = (
            select(SyncRequest.id)
            .where(
                SyncRequest.status == "pending",
                or_(
                    SyncRequest.next_retry_at.is_(None),
                    SyncRequest.next_retry_at <= func.now(),
                ),
            )
            .order_by(SyncRequest.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        result = await session.execute(
            update(SyncRequest)
            .where(SyncRequest.id == subq)
            .values(status="running", picked_at=func.now())
            .returning(SyncRequest)
        )
        req = result.scalar_one_or_none()
        await session.commit()
        return req


async def run_runner(
    source_id: str | None,
    triggered_by: str,
    *,
    argv: list[str] | None = None,
    recovery: bool = False,
) -> int:
    """以子进程运行 sync runner 并等待退出(argv 可注入供测试)。"""
    real_argv = (
        argv if argv is not None else build_runner_argv(source_id, triggered_by, recovery=recovery)
    )
    logger.warning("执行面启动 sync runner: argv=%s", " ".join(real_argv))
    proc = await asyncio.create_subprocess_exec(*real_argv, cwd=str(REPO_ROOT))
    return await proc.wait()


async def _finalize(
    session_factory, request_id: int, *, exit_code: int | None, error: str | None
) -> str:
    async with session_factory() as session:
        await session.execute(
            update(SyncRequest)
            .where(SyncRequest.id == request_id)
            .values(
                status="done" if (exit_code == 0 and error is None) else "failed",
                runner_exit_code=exit_code,
                error=error,
                next_retry_at=None,
                finished_at=func.now(),
            )
        )
        await session.commit()
    return "done" if (exit_code == 0 and error is None) else "failed"


async def _schedule_retry(session_factory, req: SyncRequest, kind: str, error: str) -> str:
    """失败分流:attempt 未达上限 → pending+退避;已达 → terminal failed。"""
    attempt = int(req.attempt_count or 0)
    if attempt >= MAX_TOTAL_ATTEMPTS:
        async with session_factory() as session:
            await session.execute(
                update(SyncRequest)
                .where(SyncRequest.id == req.id)
                .values(
                    status="failed",
                    failure_kind=kind,
                    next_retry_at=None,
                    error=f"{error}(已达 MAX_TOTAL_ATTEMPTS={MAX_TOTAL_ATTEMPTS},终态失败)",
                    finished_at=func.now(),
                )
            )
            await session.commit()
        logger.warning(
            "同步请求终态失败: request_id=%d kind=%s attempts=%d/%d",
            req.id,
            kind,
            attempt,
            MAX_TOTAL_ATTEMPTS,
        )
        return "failed"
    delay = _backoff_seconds()[min(attempt, len(DEFAULT_BACKOFF_SECONDS)) - 1]
    retry_at = datetime.now(UTC) + timedelta(seconds=delay)
    async with session_factory() as session:
        await session.execute(
            update(SyncRequest)
            .where(SyncRequest.id == req.id)
            .values(
                status="pending",
                failure_kind=kind,
                next_retry_at=retry_at,
                error=f"{error}(恢复重试安排于 {retry_at.isoformat()},"
                f"attempt={attempt}/{MAX_TOTAL_ATTEMPTS})",
            )
        )
        await session.commit()
    logger.warning(
        "同步请求安排恢复重试: request_id=%d kind=%s retry_at=%s backoff=%ds",
        req.id,
        kind,
        retry_at.isoformat(),
        delay,
    )
    return "retry-scheduled"


async def _increment_attempt(session_factory, request_id: int) -> int:
    """真实启动 runner 前递增 attempt_count(SQL 级 +1),返回新值。"""
    async with session_factory() as session:
        result = await session.execute(
            update(SyncRequest)
            .where(SyncRequest.id == request_id)
            .values(attempt_count=SyncRequest.attempt_count + 1)
            .returning(SyncRequest.attempt_count)
        )
        value = int(result.scalar_one())
        await session.commit()
        return value


async def execute_request(
    session_factory, req: SyncRequest, *, argv: list[str] | None = None
) -> str:
    """执行单个已领用请求并按恢复策略落账。

    - **启动点上限护栏**:attempt_count 已达 MAX_TOTAL_ATTEMPTS → 不递增、
      不启动,直接终态 failed(双重防线;正常流由对账/调度先行拦截);
    - 启动前复检(interrupted 的到期重试):证据边界锚定
      ``attempt_started_at``(被中断 attempt 的开始时间)——retry claim 会
      覆盖 picked_at,CORRECTION B;等待期孤儿 runner 已完成 → 直接 done,
      不二次执行;
    - attempt_count 在真实启动前递增(§4 冻结语义:启动后 = 1);
    - exit 0 → done;非零 → runner_failed 有界重试;spawn 失败 →
      spawn_failed 有界重试;MAX_TOTAL_ATTEMPTS 用尽 → terminal failed。
    """
    if int(req.attempt_count or 0) >= MAX_TOTAL_ATTEMPTS:
        async with session_factory() as session:
            await session.execute(
                update(SyncRequest)
                .where(SyncRequest.id == req.id)
                .values(
                    status="failed",
                    failure_kind=req.failure_kind or "interrupted",
                    next_retry_at=None,
                    finished_at=func.now(),
                    error=(
                        f"已达 MAX_TOTAL_ATTEMPTS={MAX_TOTAL_ATTEMPTS},"
                        "拒绝再次启动 runner(终态失败)"
                    ),
                )
            )
            await session.commit()
        logger.warning(
            "启动点上限护栏: request_id=%d attempt=%d 已达上限,拒绝启动",
            req.id,
            req.attempt_count,
        )
        return "failed"

    if req.failure_kind == "interrupted" and req.source_id is not None:
        # 复检证据边界 = 被中断 attempt 的开始时间(旧数据无锚时回退 picked_at)。
        # 首启即中断(attempt=1)同样在等待期可能被孤儿 runner 完成,CORRECTION B。
        boundary = req.attempt_started_at or req.picked_at
        if await _has_terminal_sync_log_after(session_factory, req.source_id, boundary):
            logger.warning(
                "恢复复检: request_id=%d 的源 %s 在等待期已由孤儿 runner 完成 → done(不二次执行)",
                req.id,
                req.source_id,
            )
            async with session_factory() as session:
                await session.execute(
                    update(SyncRequest)
                    .where(SyncRequest.id == req.id)
                    .values(status="done", next_retry_at=None, error=None, finished_at=func.now())
                )
                await session.commit()
            return "done"

    # 中断恢复(含首启即中断 attempt=1)必须带 F16 旁路:clone 可能已前进
    recovery = req.attempt_count > 1 or req.failure_kind == "interrupted"
    attempt = await _increment_attempt(session_factory, req.id)
    req.attempt_count = attempt  # 同步内存对象:_schedule_retry 的上限判断必须看到新值
    logger.warning(
        "启动 sync runner(attempt=%d/%d) recovery=%s",
        attempt,
        MAX_TOTAL_ATTEMPTS,
        recovery,
    )
    try:
        exit_code = await run_runner(
            req.source_id, req.triggered_by or "manual", argv=argv, recovery=recovery
        )
    except OSError as exc:
        return await _schedule_retry(
            session_factory, req, "spawn_failed", f"sync runner 启动失败: {exc}"
        )
    if exit_code == 0:
        return await _finalize(session_factory, req.id, exit_code=0, error=None)
    return await _schedule_retry(
        session_factory, req, "runner_failed", "sync runner 非零退出(业务结果见 sync_log)"
    )


async def drain_once(session_factory, *, argv: list[str] | None = None) -> bool:
    """领用并执行一个请求;无到期请求返回 False(供 run_forever 与测试复用)。"""
    req = await claim_next(session_factory)
    if req is None:
        return False
    logger.warning(
        "执行面领用同步请求: request_id=%d key=%s triggered_by=%s attempt=%d",
        req.id,
        "sync-all" if req.source_id is None else req.source_id,
        req.triggered_by,
        req.attempt_count,
    )
    await execute_request(session_factory, req, argv=argv)
    return True


async def run_forever(settings: Settings) -> None:
    """执行面主循环:启动对账 → 领用到期请求 → 串行执行 → 恢复分流 → 轮询。"""
    engine = get_engine(settings.postgres_dsn)
    await init_db(engine)  # create_all:缺表自愈(dev/首次)
    from backend.db.session import ensure_recovery_columns

    await ensure_recovery_columns(engine)  # 阶段⑩恢复列幂等补齐
    session_factory = get_session_factory(engine)
    try:
        stats = await reconcile_stale_running(session_factory)
    except Exception as exc:  # noqa: BLE001 - 对账失败不阻断执行面启动
        logger.error("stale running 对账失败(启动继续): %s", str(exc)[:300])
        stats = {}
    if stats:
        logger.warning("启动对账完成: %s", stats)
    logger.warning(
        "同步执行面已启动(独立于 backend 容器生命周期): poll=%.1fs max_attempts=%d",
        POLL_INTERVAL_SECONDS,
        MAX_TOTAL_ATTEMPTS,
    )
    while True:
        try:
            processed = await drain_once(session_factory)
        except Exception as exc:  # noqa: BLE001 - 单请求异常不得终止执行面
            logger.error("执行面处理异常(继续轮询): %s", str(exc)[:300])
            processed = False
        if not processed:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)


def main() -> None:
    """容器 entrypoint:配置日志 → 加载 Settings → 常驻循环。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    asyncio.run(run_forever(load_settings()))


if __name__ == "__main__":
    main()
