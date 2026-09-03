"""W2 Sync Truth Backend:运行时事实列 + record_device + 读侧派生测试。

冻结语义(任务契约 / Frozen Discovery §18-19):
- execution_device ∈ {gpu, cpu, gpu_to_cpu} 受控词表,自由文本拒绝(机器真值);
- record_device 是 W1 的冻结写入通道,截断语义 reason≤32 / detail≤500;
- derive_source_state 每源切片真相:sync-all 串行队列 QUEUED、切片终态如实、
  恢复语义 RECOVERING、无证据 IDLE(不 fake active);
- is_ingestion_skipped 只认 run-local 可证明事实,禁止猜测;
- 迁移幂等:重复执行无副作用,既有行保留。
"""

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.config import load_settings
from backend.db.models import SyncLog, SyncRequest, SyncRun
from backend.db.session import get_engine, get_session_factory, init_db
from backend.services import sync_runs as sr

pytestmark = pytest.mark.asyncio(loop_scope="session")

W2_SOURCES = ("w2-src", "w2-src2")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def _db():
    dsn = os.environ.get("TEST_DATABASE_URL", load_settings().postgres_dsn)
    engine = get_engine(dsn)
    await init_db(engine)
    # 正式迁移契约(幂等):共享测试库可能缺 W2 运行时事实列
    from scripts.migrate_add_sync_run_runtime_facts import migrate

    await migrate(engine)
    return get_session_factory(engine)


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _clean_tables(_db):
    async with _db() as session:
        await session.execute(SyncRun.__table__.delete().where(SyncRun.source_id.in_(W2_SOURCES)))
        await session.execute(SyncRequest.__table__.delete())
        await session.execute(SyncLog.__table__.delete().where(SyncLog.source_id.in_(W2_SOURCES)))
        await session.commit()
    yield
    async with _db() as session:
        await session.execute(SyncRun.__table__.delete().where(SyncRun.source_id.in_(W2_SOURCES)))
        await session.execute(SyncRequest.__table__.delete())
        await session.execute(SyncLog.__table__.delete().where(SyncLog.source_id.in_(W2_SOURCES)))
        await session.commit()


def _request(**kw) -> SyncRequest:
    defaults = dict(status="running", triggered_by="manual", attempt_count=1)
    defaults.update(kw)
    return SyncRequest(**defaults)


async def _get_run(_db, run_id: int) -> SyncRun:
    async with _db() as session:
        row = (await session.execute(select(SyncRun).where(SyncRun.id == run_id))).scalar_one()
        session.expunge(row)
    return row


# --------------------------------------------------------------------------- #
# 迁移幂等 + record_device(W1 冻结写入通道)
# --------------------------------------------------------------------------- #


async def test_1_migration_is_idempotent_and_columns_present(_db):
    from sqlalchemy import inspect as sa_inspect

    from scripts.migrate_add_sync_run_runtime_facts import RUNTIME_FACT_COLUMNS, migrate

    # 迁移已由 fixture 执行一次;这里对同一 DSN 再执行两次验证幂等
    from backend.db.session import get_engine

    engine = get_engine(os.environ.get("TEST_DATABASE_URL", load_settings().postgres_dsn))
    try:
        await migrate(engine)
        await migrate(engine)
        async with engine.connect() as conn:
            columns = {
                c["name"]
                for c in (await conn.run_sync(lambda sc: sa_inspect(sc).get_columns("sync_runs")))
            }
        assert set(RUNTIME_FACT_COLUMNS) <= columns
    finally:
        await engine.dispose()


async def test_2_record_device_persists_gpu_and_rejects_free_text(_db):
    run = await sr.start_run(_db, source_id="w2-src", attempt=1)
    await sr.record_device(_db, run.id, execution_device="gpu")
    row = await _get_run(_db, run.id)
    assert row.execution_device == "gpu"
    assert row.fallback_reason is None and row.fallback_detail is None

    # 自由文本/越界值一律拒绝(机器真值纪律)
    for bad in ("GPU", "cuda:0", "nvidia-3090", "gpu->cpu", ""):
        with pytest.raises(ValueError):
            await sr.record_device(_db, run.id, execution_device=bad)


async def test_3_record_device_fallback_telemetry_and_truncation(_db):
    run = await sr.start_run(_db, source_id="w2-src", attempt=1)
    long_detail = "x" * 900
    await sr.record_device(
        _db,
        run.id,
        execution_device="gpu_to_cpu",
        fallback_reason="cuda_oom",
        fallback_detail=long_detail,
    )
    row = await _get_run(_db, run.id)
    assert row.execution_device == "gpu_to_cpu"
    assert row.fallback_reason == "cuda_oom"
    assert row.fallback_detail == "x" * 500  # 截 500
    # 词表:gpu_to_cpu 同时表达「发生过降级」+「最终 CPU」
    assert sr.DEVICE_GPU_TO_CPU == "gpu_to_cpu"


async def test_4_run_telemetry_device_channel_is_best_effort(_db):
    """_RunTelemetry.device 冻结通道:成功落值;run 未创建/DB 失败静默降级。"""
    import scripts.sync as sync_mod

    tel = sync_mod._RunTelemetry()
    # run_id 为 None(未 start)→ 不写不炸
    await tel.device(_db, execution_device="cpu")
    run = await sr.start_run(_db, source_id="w2-src", attempt=1)
    tel.run_id = run.id
    await tel.device(_db, execution_device="gpu_to_cpu", fallback_reason="cuda_init_failure")
    row = await _get_run(_db, run.id)
    assert row.execution_device == "gpu_to_cpu"
    assert row.fallback_reason == "cuda_init_failure"


# --------------------------------------------------------------------------- #
# derive_source_state:⑫ 每源切片真相(纯函数矩阵)
# --------------------------------------------------------------------------- #


def _run(status: str, **kw) -> SyncRun:
    return SyncRun(source_id=kw.pop("source_id", "w2-src"), status=status, **kw)


def test_5_pending_request_queued_waiting_recovering():
    req = _request(status="pending", attempt_count=0, failure_kind=None, next_retry_at=None)
    assert sr.derive_source_state(req, None, None) == sr.STATE_QUEUED
    req.next_retry_at = datetime.now(UTC) + timedelta(seconds=60)
    assert sr.derive_source_state(req, None, None) == sr.STATE_WAITING
    req2 = _request(status="pending", attempt_count=2, failure_kind="runner_failed")
    assert sr.derive_source_state(req2, None, None) == sr.STATE_RECOVERING


def test_6_running_request_slice_truth():
    # 请求运行中 + 该源 running 切片 → RUNNING
    req = _request(status="running", attempt_count=1)
    run = _run(sr.RUN_RUNNING, request_id=req.id, attempt=1)
    assert sr.derive_source_state(req, run, run) == sr.STATE_RUNNING
    # 恢复语义(attempt_count>1)→ RECOVERING
    req2 = _request(status="running", attempt_count=2)
    assert sr.derive_source_state(req2, run, run) == sr.STATE_RECOVERING
    # sync-all 串行队列:请求 running 但该源切片未开始 → QUEUED(不冒充 RUNNING)
    assert sr.derive_source_state(req, None, None) == sr.STATE_QUEUED
    # 切片已终态 → 如实呈现切片终态(多源互不污染)
    done = _run(sr.RUN_COMPLETED, request_id=req.id, attempt=1)
    assert sr.derive_source_state(req, done, done) == sr.STATE_COMPLETED
    failed = _run(sr.RUN_FAILED, request_id=req.id, attempt=1)
    assert sr.derive_source_state(req, failed, failed) == sr.STATE_FAILED


def test_7_no_request_uses_latest_run_only():
    assert sr.derive_source_state(None, None, None) == sr.STATE_IDLE
    latest = _run(sr.RUN_COMPLETED)
    assert sr.derive_source_state(None, None, latest) == sr.STATE_COMPLETED
    # cron 直跑(run request_id=NULL)运行中 → RUNNING(遗留瞬态/真实在途)
    live = _run(sr.RUN_RUNNING, request_id=None)
    assert sr.derive_source_state(None, None, live) == sr.STATE_RUNNING


def test_8_is_ingestion_skipped_only_from_provable_facts():
    assert sr.is_ingestion_skipped({"ingestion_skipped": 1}, None) is True
    # 历史行兜底:unchanged>0 且 new=0 且 written=0
    log = SyncLog(
        source_id="w2-src",
        source_type="github",
        status="success",
        items_new=0,
        items_updated=0,
        items_unchanged=5,
    )
    assert sr.is_ingestion_skipped({}, log) is True
    # refill/真实灌入 → 绝不误标
    refilled = SyncLog(
        source_id="w2-src",
        source_type="github",
        status="partial",
        items_new=0,
        items_updated=12,
        items_unchanged=5,
    )
    assert sr.is_ingestion_skipped({}, refilled) is False
    assert sr.is_ingestion_skipped(None, None) is False


# --------------------------------------------------------------------------- #
# 读侧查询 helpers
# --------------------------------------------------------------------------- #


async def test_9_latest_runs_by_source_and_request_grouping(_db):
    r1 = await sr.start_run(_db, source_id="w2-src", attempt=1)
    await sr.finish_run(_db, r1.id, status=sr.RUN_COMPLETED)
    await asyncio.sleep(0.03)
    r2 = await sr.start_run(_db, source_id="w2-src", attempt=2)
    r3 = await sr.start_run(_db, source_id="w2-src2", attempt=1, request_id=77)
    await sr.finish_run(_db, r3.id, status=sr.RUN_FAILED)

    latest = await sr.get_latest_runs_by_source(_db)
    assert latest["w2-src"].id == r2.id
    assert latest["w2-src2"].id == r3.id
    running = await sr.get_running_runs(_db)
    assert {r.id for r in running} == {r2.id}

    grouped = await sr.get_latest_runs_for_requests(_db, [77])
    assert grouped[(77, "w2-src2")].id == r3.id

    rows, total = await sr.list_runs(_db, source_id="w2-src", status=sr.RUN_COMPLETED)
    assert total == 1 and rows[0].id == r1.id
    rows, total = await sr.list_runs(_db, status=sr.RUN_FAILED, offset=0, limit=10)
    assert total >= 1 and all(r.status == sr.RUN_FAILED for r in rows)
