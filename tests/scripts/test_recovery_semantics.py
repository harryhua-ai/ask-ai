"""阶段⑩ 恢复语义测试:持久化字段 / 领用过滤 / 中断对账 / 有界重试退避。

冻结语义(Contract §4-§7):
- 持久状态仍四态(pending/running/done/failed);新增最小恢复字段
  attempt_count / failure_kind / next_retry_at;
- attempt_count = 实际启动过的 runner 次数(首次启动=1);MAX_TOTAL_ATTEMPTS=4;
- 退避 30/120/600s(测试可用短值注入);未到 next_retry_at 不可领取;
- stale running 对账以 sync_log 为执行事实:已完成→done(不重跑);
  未完成→interrupted→延迟恢复;sync-all 保守整批重跑;
- 同 key 去重不退化(retry 等待期新触发 → already-running)。
"""

import os
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.config import load_settings
from backend.db.models import SyncRequest
from backend.db.session import get_engine, get_session_factory, init_db

pytestmark = pytest.mark.asyncio(loop_scope="session")

REPO = os.environ.get(
    "EXP_REPO", "/Users/harryhua/Documents/GitHub/ask-ai/.worktrees/ingest-safety"
)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def _db():
    from backend.db.session import ensure_recovery_columns

    dsn = os.environ.get("TEST_DATABASE_URL", load_settings().postgres_dsn)
    engine = get_engine(dsn)
    await init_db(engine)
    await ensure_recovery_columns(engine)  # 幂等:老表补列
    return get_session_factory(engine)


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _clean_table(_db):
    async with _db() as session:
        await session.execute(SyncRequest.__table__.delete())
        await session.commit()
    yield
    async with _db() as session:
        await session.execute(SyncRequest.__table__.delete())
        await session.commit()


async def _add(factory, **kwargs) -> SyncRequest:
    async with factory() as session:
        row = SyncRequest(**kwargs)
        session.add(row)
        await session.commit()
        await session.refresh(row)
        session.expunge(row)
    return row


async def _get(factory, request_id) -> SyncRequest:
    async with factory() as session:
        row = (
            await session.execute(select(SyncRequest).where(SyncRequest.id == request_id))
        ).scalar_one()
        session.expunge(row)
    return row


# --------------------------------------------------------------------------- #
# 持久化模型:最小恢复字段(Contract §4)
# --------------------------------------------------------------------------- #


async def test_sync_request_model_has_recovery_fields(_db):
    """新列存在且默认安全:attempt_count=0、failure_kind=None、next_retry_at=None。"""
    row = await _add(_db, source_id="r-src", status="pending")
    assert row.attempt_count == 0
    assert row.failure_kind is None
    assert row.next_retry_at is None


async def test_ensure_recovery_columns_idempotent(_db):
    """迁移幂等:对已有列的表重复执行不报错、不丢数据。"""
    from backend.db.session import ensure_recovery_columns

    await _add(
        _db, source_id="mig-src", status="pending", attempt_count=2, failure_kind="interrupted"
    )
    dsn = os.environ.get("TEST_DATABASE_URL", load_settings().postgres_dsn)
    engine = get_engine(dsn)
    await ensure_recovery_columns(engine)  # 第二次执行
    await ensure_recovery_columns(engine)
    async with _db() as session:
        rows = (
            (await session.execute(select(SyncRequest).where(SyncRequest.source_id == "mig-src")))
            .scalars()
            .all()
        )
    assert len(rows) == 1 and rows[0].attempt_count == 2
    await engine.dispose()


# --------------------------------------------------------------------------- #
# 领用语义:next_retry_at 过滤 + attempt_count 递增(Contract §7)
# --------------------------------------------------------------------------- #


async def test_claim_skips_future_retry_and_claims_when_due(_db):
    from scripts.sync_executor_loop import claim_next

    future = await _add(
        _db,
        source_id="fut-src",
        status="pending",
        attempt_count=1,
        failure_kind="interrupted",
        next_retry_at=datetime.now(UTC) + timedelta(hours=1),
    )
    due = await _add(
        _db,
        source_id="due-src",
        status="pending",
        attempt_count=1,
        failure_kind="interrupted",
        next_retry_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    claimed = await claim_next(_db)
    assert claimed is not None and claimed.id == due.id  # 未来重试不可领,到期可领
    row = await _get(_db, claimed.id)
    assert row.attempt_count == 2  # 领用即递增(recovery runner 将启动)
    again = await claim_next(_db)
    assert again is None or again.id == future.id  # future 未到齐不允许被领
    assert again is None


async def test_claim_increments_attempt_on_first_run(_db):
    from scripts.sync_executor_loop import claim_next

    row = await _add(_db, source_id="first-src", status="pending")
    claimed = await claim_next(_db)
    assert claimed.id == row.id
    assert (await _get(_db, row.id)).attempt_count == 1  # 首次启动后 = 1


# --------------------------------------------------------------------------- #
# stale running 对账:sync_log 是执行事实(Contract §6)
# --------------------------------------------------------------------------- #


async def _seed_log(factory, source_id, status, finished_at):
    from backend.db.models import SyncLog

    async with factory() as session:
        session.add(
            SyncLog(
                source_id=source_id,
                source_type="exp",
                status=status,
                started_at=finished_at - timedelta(seconds=5),
                finished_at=finished_at,
                triggered_by="manual",
            )
        )
        await session.commit()


async def test_stale_running_with_success_log_finalizes_done(_db):
    """E1 假阴性修复:孤儿 runner 已成功 → done,不得错标 failed,不得重跑。"""
    from scripts.sync_executor_loop import reconcile_stale_running

    picked = datetime.now(UTC) - timedelta(minutes=5)
    row = await _add(_db, source_id="orphan-src", status="running", picked_at=picked)
    await _seed_log(_db, "orphan-src", "success", datetime.now(UTC))
    result = await reconcile_stale_running(_db)
    assert result["finalized_done"] == 1 and result["scheduled_retry"] == 0
    after = await _get(_db, row.id)
    assert after.status == "done"


async def test_stale_running_without_log_schedules_delayed_retry(_db):
    """真中断:无 terminal sync_log → interrupted + next_retry_at(不立即双跑)。"""
    from scripts.sync_executor_loop import reconcile_stale_running

    picked = datetime.now(UTC) - timedelta(minutes=5)
    row = await _add(_db, source_id="dead-src", status="running", picked_at=picked, attempt_count=1)
    result = await reconcile_stale_running(_db)
    assert result["scheduled_retry"] == 1 and result["finalized_done"] == 0
    after = await _get(_db, row.id)
    assert after.status == "pending"  # 可简化回 pending(Contract §5 允许)
    assert after.failure_kind == "interrupted"
    assert after.next_retry_at is not None
    assert after.attempt_count == 1  # 对账不递增;递增只发生在真实启动


async def test_stale_running_with_failed_log_finalizes_done_process_completed(_db):
    """有 terminal 失败事实 = 进程已完成执行:finalize done(业务失败不进本 Gate 调度,§14)。"""
    from scripts.sync_executor_loop import reconcile_stale_running

    picked = datetime.now(UTC) - timedelta(minutes=5)
    row = await _add(_db, source_id="bizfail-src", status="running", picked_at=picked)
    await _seed_log(_db, "bizfail-src", "failed", datetime.now(UTC))
    await reconcile_stale_running(_db)
    assert (await _get(_db, row.id)).status == "done"


async def test_stale_running_before_pick_at_log_not_confused(_db):
    """picked_at 之前的旧 sync_log 不算本次执行事实 → 仍按中断处理。"""
    from scripts.sync_executor_loop import reconcile_stale_running

    picked = datetime.now(UTC) - timedelta(minutes=5)
    row = await _add(_db, source_id="stale-log-src", status="running", picked_at=picked)
    await _seed_log(_db, "stale-log-src", "success", picked - timedelta(minutes=10))
    result = await reconcile_stale_running(_db)
    assert result["scheduled_retry"] == 1
    assert (await _get(_db, row.id)).failure_kind == "interrupted"


async def test_stale_sync_all_conservative_interrupted(_db):
    """sync-all(source_id NULL)不做事后完成推断 → 保守整批恢复。"""
    from scripts.sync_executor_loop import reconcile_stale_running

    picked = datetime.now(UTC) - timedelta(minutes=5)
    row = await _add(_db, source_id=None, status="running", picked_at=picked)
    await _seed_log(_db, "some-src", "success", datetime.now(UTC))  # 部分源成功也不能推断整批完成
    result = await reconcile_stale_running(_db)
    assert result["scheduled_retry"] == 1 and result["finalized_done"] == 0
    after = await _get(_db, row.id)
    assert after.status == "pending" and after.failure_kind == "interrupted"


# --------------------------------------------------------------------------- #
# 有界重试:失败分流 / 退避 / 终态(Contract §4/§15)
# --------------------------------------------------------------------------- #


async def test_runner_failure_schedules_retry_with_backoff(_db):
    from scripts.sync_executor_loop import execute_request

    row = await _add(_db, source_id="retry-src", status="running", attempt_count=1)
    req = await _get(_db, row.id)
    status = await execute_request(_db, req, argv=["/bin/sh", "-c", "exit 7"])
    assert status == "retry-scheduled"
    after = await _get(_db, row.id)
    assert after.status == "pending"
    assert after.failure_kind == "runner_failed"
    assert after.next_retry_at is not None
    delta = after.next_retry_at - datetime.now(UTC)
    assert timedelta(seconds=25) < delta <= timedelta(seconds=31)  # 默认退避 #1 = 30s


async def test_spawn_failure_schedules_retry_with_kind(_db):
    from scripts.sync_executor_loop import execute_request

    row = await _add(_db, source_id="spawn-src", status="running", attempt_count=2)
    req = await _get(_db, row.id)
    status = await execute_request(_db, req, argv=["/nonexistent/interpreter", "-c", "pass"])
    assert status == "retry-scheduled"
    after = await _get(_db, row.id)
    assert after.failure_kind == "spawn_failed"
    delta = after.next_retry_at - datetime.now(UTC)
    assert timedelta(seconds=110) < delta <= timedelta(seconds=125)  # 退避 #2 = 120s


async def test_attempts_exhausted_terminal_failed(_db):
    """第 4 次实际执行仍失败 → terminal failed,不再调度。"""
    from scripts.sync_executor_loop import execute_request

    row = await _add(_db, source_id="term-src", status="running", attempt_count=4)
    req = await _get(_db, row.id)
    status = await execute_request(_db, req, argv=["/bin/sh", "-c", "exit 3"])
    assert status == "failed"
    after = await _get(_db, row.id)
    assert after.status == "failed"
    assert after.failure_kind == "runner_failed"
    assert after.next_retry_at is None
    claimed = await __import__("scripts.sync_executor_loop", fromlist=["claim_next"]).claim_next(
        _db
    )
    assert claimed is None  # terminal 行不再被启动


async def test_success_clears_retry_state(_db):
    from scripts.sync_executor_loop import execute_request

    row = await _add(
        _db,
        source_id="ok-src",
        status="running",
        attempt_count=2,
        failure_kind="interrupted",
        next_retry_at=datetime.now(UTC) + timedelta(hours=1),
    )
    req = await _get(_db, row.id)
    status = await execute_request(_db, req, argv=["/bin/sh", "-c", "exit 0"])
    assert status == "done"
    after = await _get(_db, row.id)
    assert after.status == "done"
    assert after.next_retry_at is None


# --------------------------------------------------------------------------- #
# 重试到期前的孤儿完成复检(Contract §6)
# --------------------------------------------------------------------------- #


async def test_retry_due_rechecks_orphan_completion_before_spawn(_db):
    """恢复 runner 启动前复检 sync_log:孤儿已在等待期完成 → done,不二次执行。"""
    from scripts.sync_executor_loop import execute_request

    picked = datetime.now(UTC) - timedelta(minutes=10)
    row = await _add(
        _db,
        source_id="orphan2-src",
        status="pending",
        attempt_count=2,
        failure_kind="interrupted",
        next_retry_at=datetime.now(UTC) - timedelta(seconds=1),
        picked_at=picked,
    )
    await _seed_log(_db, "orphan2-src", "success", datetime.now(UTC))  # 等待期孤儿完成
    req = await _get(_db, row.id)
    status = await execute_request(_db, req, argv=["/bin/sh", "-c", "exit 0"])
    assert status == "done"
    after = await _get(_db, row.id)
    assert after.status == "done"
    assert after.runner_exit_code is None  # 未启动 recovery runner


async def test_retry_due_with_no_completion_runs_recovery_runner(_db):
    """复检无完成事实 → 真正启动 recovery runner(非 interrupted 类不受影响)。"""
    from scripts.sync_executor_loop import execute_request

    picked = datetime.now(UTC) - timedelta(minutes=10)
    row = await _add(
        _db,
        source_id="gorecov-src",
        status="pending",
        attempt_count=2,
        failure_kind="interrupted",
        next_retry_at=datetime.now(UTC) - timedelta(seconds=1),
        picked_at=picked,
    )
    req = await _get(_db, row.id)
    status = await execute_request(_db, req, argv=["/bin/sh", "-c", "exit 0"])
    assert status == "done"
    after = await _get(_db, row.id)
    assert after.runner_exit_code == 0  # 真实启动了 recovery runner


# --------------------------------------------------------------------------- #
# 同 key 去重不退化(Contract §7/AC10)
# --------------------------------------------------------------------------- #


async def test_retry_wait_blocks_duplicate_trigger(_db):
    from backend.services.sync_requests import find_active_request

    await _add(
        _db,
        source_id="dedupe-src",
        status="pending",
        attempt_count=1,
        failure_kind="interrupted",
        next_retry_at=datetime.now(UTC) + timedelta(hours=1),
    )
    async with _db() as session:
        active = await find_active_request(session, "dedupe-src")
    assert active is not None  # retry 等待期仍是在途 → Admin 新触发必须 already-running
