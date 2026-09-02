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

设计要点
--------
- **ONE BUSINESS SYNC IMPLEMENTATION**:领用后以子进程运行
  ``scripts/sync.py``(manual/scheduled/CLI 同一 runner);source_id /
  triggered_by 以 argv 数据参数传递,无 shell(无注入面)。
- **串行执行是特性**:一次领用一个请求,跑完再取下一个 —— 单 GPU 不被
  并发 embed 打爆(与 sync-all 单 pipeline 的既有约束一致)。
- **status 是交接/进程级语义**:done/failed 记录 runner 进程退出码;
  业务成败以 sync_log 为准(后台进程崩溃但退出码 0 的场景由覆盖门控
  /partial 语义兜住,JOB SUCCESS ≠ KNOWLEDGE HEALTH)。
- **启动诚实清理**:执行面重启时把遗留 ``running`` 行标记 failed
  (上次进程中断)。**不自动恢复/重跑** —— interrupted recovery 是
  阶段⑩,本 Gate 不越界。
- **spawn 失败显式落账**:runner 无法启动(OSError)→ 行记 failed +
  错误,循环继续服务后续请求,绝不吞掉。

用法(容器 entrypoint / 本地开发):
    python scripts/sync_executor_loop.py
"""

import asyncio
import logging
import sys
from pathlib import Path

from sqlalchemy import func, select, update

# 让脚本直接执行时也能导入 backend 包(与 scripts/sync.py 同约定)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import Settings, load_settings
from backend.db.models import SyncRequest
from backend.db.session import get_engine, get_session_factory, init_db

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
SYNC_SCRIPT = REPO_ROOT / "scripts" / "sync.py"

# 交接队列轮询间隔(秒)。手动同步启动延迟上界 ≈ 一个轮询周期 + 当前在跑行程。
POLL_INTERVAL_SECONDS = 2.0


def build_runner_argv(source_id: str | None, triggered_by: str) -> list[str]:
    """构造 sync runner argv(逐元素列表,无 shell)。

    与 cron(``python3 scripts/sync.py``)、CLI 同一脚本入口;
    ``--triggered-by`` 保留 sync_log 触发方语义(sync-all 若不显式标记
    会被旧规则误记为 cron)。
    """
    argv = [sys.executable, str(SYNC_SCRIPT), "--triggered-by", triggered_by]
    if source_id is not None:
        argv += ["--source", source_id]
    return argv


async def fail_stale_running(session_factory) -> int:
    """执行面启动清理:上次进程中断遗留的 running 行诚实标记 failed。

    不自动恢复/重跑(阶段⑩范围);pending 行不受影响(照常领用)。
    """
    async with session_factory() as session:
        result = await session.execute(
            update(SyncRequest)
            .where(SyncRequest.status == "running")
            .values(
                status="failed",
                error="执行面进程重启:上次运行中断,标记失败(中断自动恢复属阶段⑩,请重新触发)",
                finished_at=func.now(),
            )
        )
        await session.commit()
        return int(result.rowcount or 0)


async def claim_next(session_factory) -> SyncRequest | None:
    """原子领用最旧的 pending 请求(FOR UPDATE SKIP LOCKED,多副本安全)。"""
    async with session_factory() as session:
        subq = (
            select(SyncRequest.id)
            .where(SyncRequest.status == "pending")
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
    source_id: str | None, triggered_by: str, *, argv: list[str] | None = None
) -> int:
    """以子进程运行 sync runner 并等待退出(argv 可注入供测试)。"""
    real_argv = argv if argv is not None else build_runner_argv(source_id, triggered_by)
    logger.warning("执行面启动 sync runner: argv=%s", " ".join(real_argv))
    proc = await asyncio.create_subprocess_exec(*real_argv, cwd=str(REPO_ROOT))
    return await proc.wait()


async def mark_finished(
    session_factory, request_id: int, *, exit_code: int | None, error: str | None
) -> str:
    """落交接结果:exit_code==0 → done,否则 failed(spawn 失败 error 必非空)。"""
    status = "done" if (exit_code == 0 and error is None) else "failed"
    async with session_factory() as session:
        await session.execute(
            update(SyncRequest)
            .where(SyncRequest.id == request_id)
            .values(
                status=status,
                runner_exit_code=exit_code,
                error=error,
                finished_at=func.now(),
            )
        )
        await session.commit()
    logger.warning(
        "同步请求完成: request_id=%d status=%s exit_code=%s%s",
        request_id,
        status,
        exit_code,
        "" if error is None else f" error={error[:200]}",
    )
    return status


async def execute_request(
    session_factory, req: SyncRequest, *, argv: list[str] | None = None
) -> str:
    """跑单个已领用请求并落账(spawn 失败也显式落账,不吞)。"""
    try:
        exit_code = await run_runner(req.source_id, req.triggered_by or "manual", argv=argv)
    except OSError as exc:
        return await mark_finished(
            session_factory,
            req.id,
            exit_code=None,
            error=f"sync runner 启动失败: {exc}",
        )
    return await mark_finished(
        session_factory,
        req.id,
        exit_code=exit_code,
        error=None if exit_code == 0 else "sync runner 非零退出(业务结果见 sync_log)",
    )


async def drain_once(session_factory, *, argv: list[str] | None = None) -> bool:
    """领用并执行一个请求;队列空返回 False(供 run_forever 与测试复用)。"""
    req = await claim_next(session_factory)
    if req is None:
        return False
    logger.warning(
        "执行面领用同步请求: request_id=%d key=%s triggered_by=%s",
        req.id,
        "sync-all" if req.source_id is None else req.source_id,
        req.triggered_by,
    )
    await execute_request(session_factory, req, argv=argv)
    return True


async def run_forever(settings: Settings) -> None:
    """执行面主循环:启动清理 → 领用 → 串行执行 → 落账 → 轮询。"""
    engine = get_engine(settings.postgres_dsn)
    await init_db(engine)  # create_all:sync_requests 缺表时自愈(dev/首次)
    session_factory = get_session_factory(engine)
    stale = await fail_stale_running(session_factory)
    if stale:
        logger.warning("启动清理:%d 个中断遗留 running 请求已标记 failed", stale)
    logger.warning(
        "同步执行面已启动(独立于 backend 容器生命周期): poll=%.1fs",
        POLL_INTERVAL_SECONDS,
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
