"""独立同步执行面主循环测试(sync_requests 交接 → 子进程 sync.py)。

阶段⑨ FINAL + 阶段⑩ 恢复语义:执行面 = 独立 sync-executor 容器,
运行 ``scripts/sync_executor_loop.py``。本文件覆盖交接语义的业务规则:

- 领用:最旧 pending 原子置 running(FOR UPDATE SKIP LOCKED);
- 执行:子进程运行 scripts/sync.py(同一业务 runner,AC7),argv 数据
  参数无 shell;
- 落账:退出码 0 → done;非零/启动失败 → 有界恢复重试(阶段⑩);
- 启动对账:遗留 running 以 sync_log 分流(阶段⑩,详 tests/scripts/
  test_recovery_semantics.py)。

全部走真实测试库(TEST_DATABASE_URL)+ 真实子进程(stub runner)。
"""

import os
import sys

import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.db.models import SyncRequest
from backend.db.session import ensure_recovery_columns, get_engine, get_session_factory, init_db
from scripts.sync_executor_loop import (
    build_runner_argv,
    claim_next,
    drain_once,
    execute_request,
    reconcile_stale_running,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

# stub runner:写入标记后按 argv[2] 指定退出码退出(argv[3]=持续秒数)
_STUB_RUNNER = (
    "import sys, time\n"
    "from pathlib import Path\n"
    "Path(sys.argv[1]).write_text('started')\n"
    "time.sleep(float(sys.argv[3]))\n"
    "sys.exit(int(sys.argv[2]))\n"
)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def _db():
    # 测试库优先(TEST_DATABASE_URL),回退 settings(与 admin conftest 同约定)
    from backend.config import load_settings

    dsn = os.environ.get("TEST_DATABASE_URL", load_settings().postgres_dsn)
    engine = get_engine(dsn)
    await init_db(engine)
    await ensure_recovery_columns(engine)  # 阶段⑩恢复列幂等补齐(老测试库)
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


def _stub_argv(marker, exit_code=0, hold=0.1):
    return [sys.executable, "-c", _STUB_RUNNER, str(marker), str(exit_code), str(hold)]


async def _add_request(factory, source_id, status="pending", triggered_by="manual") -> int:
    async with factory() as session:
        row = SyncRequest(source_id=source_id, status=status, triggered_by=triggered_by)
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row.id


async def _get_request(factory, request_id) -> SyncRequest:
    async with factory() as session:
        row = (
            await session.execute(select(SyncRequest).where(SyncRequest.id == request_id))
        ).scalar_one()
        session.expunge(row)
    return row


# --------------------------------------------------------------------------- #
# runner argv 构造(AC7:manual/scheduled/CLI 同一 scripts/sync.py)
# --------------------------------------------------------------------------- #


async def test_build_runner_argv_single_source():
    argv = build_runner_argv("some-src", "manual")
    assert argv[0] == sys.executable
    assert argv[1].endswith("scripts/sync.py")
    assert argv[argv.index("--triggered-by") + 1] == "manual"
    assert argv[argv.index("--source") + 1] == "some-src"


async def test_build_runner_argv_all_sources():
    """sync-all:NULL source → 不带 --source,脚本内部遍历全部启用源。"""
    argv = build_runner_argv(None, "manual")
    assert "--source" not in argv
    assert argv[argv.index("--triggered-by") + 1] == "manual"


# --------------------------------------------------------------------------- #
# 启动清理(诚实失败,不自动恢复)
# --------------------------------------------------------------------------- #


async def test_reconcile_interrupted_schedules_retry_only(_db):
    """阶段⑩:中断遗留 running → 延迟恢复重试;pending 行不受影响(诚实+有界)。"""
    running_id = await _add_request(_db, "stale-src", status="running")
    pending_id = await _add_request(_db, "fresh-src", status="pending")
    stats = await reconcile_stale_running(_db)
    assert stats["scheduled_retry"] == 1 and stats["finalized_done"] == 0
    row = await _get_request(_db, running_id)
    assert row.status == "pending"
    assert row.failure_kind == "interrupted"
    assert row.next_retry_at is not None
    assert (await _get_request(_db, pending_id)).status == "pending"  # pending 不受影响


# --------------------------------------------------------------------------- #
# 领用(FOR UPDATE SKIP LOCKED)
# --------------------------------------------------------------------------- #


async def test_claim_next_claims_oldest_pending(_db):
    first = await _add_request(_db, "src-a")
    await _add_request(_db, "src-b")
    req = await claim_next(_db)
    assert req is not None and req.id == first
    row = await _get_request(_db, first)
    assert row.status == "running"
    assert row.picked_at is not None
    # 第二次领用拿到的是下一个 pending,而非同一行
    req2 = await claim_next(_db)
    assert req2 is not None and req2.id != first


async def test_claim_next_returns_none_when_queue_empty(_db):
    assert await claim_next(_db) is None


# --------------------------------------------------------------------------- #
# 执行与落账(真实子进程)
# --------------------------------------------------------------------------- #


async def test_execute_request_success_marks_done(_db, tmp_path):
    req_id = await _add_request(_db, "ok-src")
    req = await _get_request(_db, req_id)
    status = await execute_request(_db, req, argv=_stub_argv(tmp_path / "m1"))
    assert status == "done"
    row = await _get_request(_db, req_id)
    assert row.status == "done"
    assert row.runner_exit_code == 0
    assert row.error is None
    assert row.finished_at is not None


async def test_execute_request_child_failure_schedules_bounded_retry(_db, tmp_path):
    """阶段⑩:子进程非零退出 → runner_failed 有界重试(pending+退避),可诊断;
    退避期内不可再领用;到期后重跑收敛。"""
    from datetime import UTC, datetime

    fail_id = await _add_request(_db, "bad-src")
    # 首次执行(经领用,attempt 0→1)失败 → 有界重试
    assert await drain_once(_db, argv=_stub_argv(tmp_path / "m2", exit_code=3)) is True
    row = await _get_request(_db, fail_id)
    assert row.status == "pending"
    assert row.attempt_count == 1
    assert row.failure_kind == "runner_failed"
    assert row.next_retry_at is not None
    # 未到期不可领用(防重复执行)
    assert await drain_once(_db, argv=_stub_argv(tmp_path / "m3")) is False
    # 到期后重跑收敛(attempt 1→2)
    async with _db() as session:
        r = await session.get(SyncRequest, fail_id)
        r.next_retry_at = datetime.now(UTC)
        await session.commit()
    assert await drain_once(_db, argv=_stub_argv(tmp_path / "m4")) is True
    done_row = await _get_request(_db, fail_id)
    assert done_row.status == "done"
    assert done_row.attempt_count == 2  # 首次 + 一次恢复


async def test_execute_request_spawn_failure_schedules_retry_explicitly(_db):
    """阶段⑩:runner 无法启动 → spawn_failed 有界重试(显式 error,不吞、不假报)。"""
    req_id = await _add_request(_db, "spawn-fail-src")
    req = await _get_request(_db, req_id)
    status = await execute_request(_db, req, argv=["/nonexistent/interpreter", "-c", "pass"])
    assert status == "retry-scheduled"
    row = await _get_request(_db, req_id)
    assert row.status == "pending"
    assert row.failure_kind == "spawn_failed"
    assert row.next_retry_at is not None
    assert row.error and "启动失败" in row.error


async def test_drain_once_processes_in_id_order_then_empty(_db, tmp_path):
    """串行执行是特性:按 id 顺序逐个跑完;队列空返回 False。"""
    id1 = await _add_request(_db, "q-1")
    id2 = await _add_request(_db, "q-2")
    assert await drain_once(_db, argv=_stub_argv(tmp_path / "q1")) is True
    assert (await _get_request(_db, id1)).status == "done"
    assert (await _get_request(_db, id2)).status == "pending"  # 串行:第一个跑完才轮到
    assert await drain_once(_db, argv=_stub_argv(tmp_path / "q2")) is True
    assert (await _get_request(_db, id2)).status == "done"
    assert await drain_once(_db, argv=_stub_argv(tmp_path / "q3")) is False
