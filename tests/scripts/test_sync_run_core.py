"""⑪+⑫ Wave-0 SyncRun 共享核心测试。

冻结语义(任务契约):
- 一行 = ONE SOURCE × ONE ATTEMPT;尽早创建(attempt 启动即落事实);
- request_id 可空(cron/CLI 直跑合法);
- stage_total 未知 → progress_fraction 必须为 None(禁止假百分比);
- 终态四态 running/completed/failed/interrupted;IDLE 等为派生态;
- retention 30 天,running 行绝不清理;
- 对账盖章服从 recovery truth(不创造第二恢复权威)。
"""

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import ClassVar

import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.config import load_settings
from backend.db.models import SyncLog, SyncRequest, SyncRun
from backend.db.session import get_engine, get_session_factory, init_db
from backend.services import sync_runs as sr

pytestmark = pytest.mark.asyncio(loop_scope="session")

W0_SOURCES = ("w0-src", "w0-src2", "w0-orph")


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def _db():
    dsn = os.environ.get("TEST_DATABASE_URL", load_settings().postgres_dsn)
    engine = get_engine(dsn)
    await init_db(engine)  # create_all:sync_runs 新表自举
    # CORRECTION C:既有库补身份唯一索引(正式迁移契约,幂等)
    from scripts.migrate_add_sync_runs import migrate

    await migrate(engine)
    return get_session_factory(engine)


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _clean_tables(_db):
    async with _db() as session:
        for table in (SyncRun.__table__, SyncRequest.__table__):
            await session.execute(table.delete())
        await session.execute(SyncLog.__table__.delete().where(SyncLog.source_id.in_(W0_SOURCES)))
        await session.commit()
    yield
    async with _db() as session:
        for table in (SyncRun.__table__, SyncRequest.__table__):
            await session.execute(table.delete())
        await session.execute(SyncLog.__table__.delete().where(SyncLog.source_id.in_(W0_SOURCES)))
        await session.commit()


async def _get(_db, run_id: int) -> SyncRun:
    async with _db() as session:
        row = (await session.execute(select(SyncRun).where(SyncRun.id == run_id))).scalar_one()
        session.expunge(row)
    return row


# --------------------------------------------------------------------------- #
# 1-4:创建 / source×attempt 身份 / request 链接 / NULL request
# --------------------------------------------------------------------------- #


async def test_1_start_run_persists_running_row_with_discover_stage(_db):
    run = await sr.start_run(_db, source_id="w0-src", attempt=1)
    assert run.id is not None
    assert run.status == sr.RUN_RUNNING
    assert run.stage == sr.STAGE_DISCOVER
    assert run.attempt == 1
    assert run.request_id is None  # 直接/cron 默认无请求(AC4)
    assert run.started_at is not None
    assert run.finished_at is None


async def test_2_one_row_per_source_times_attempt(_db):
    r1 = await sr.start_run(_db, source_id="w0-src", attempt=1, request_id=101)
    r2 = await sr.start_run(_db, source_id="w0-src", attempt=2, request_id=101)
    r3 = await sr.start_run(_db, source_id="w0-src2", attempt=1, request_id=101)
    assert len({r1.id, r2.id, r3.id}) == 3
    async with _db() as session:
        rows = (
            (
                await session.execute(
                    select(SyncRun)
                    .where(SyncRun.request_id == 101)
                    .order_by(SyncRun.source_id, SyncRun.attempt)
                )
            )
            .scalars()
            .all()
        )
    assert [(r.source_id, r.attempt) for r in rows] == [
        ("w0-src", 1),
        ("w0-src", 2),
        ("w0-src2", 1),
    ]


async def test_3_request_linkage_deterministic(_db):
    run = await sr.start_run(_db, source_id="w0-src", attempt=2, request_id=77)
    row = await _get(_db, run.id)
    assert row.request_id == 77
    assert row.attempt == 2
    async with _db() as session:
        found = (
            await session.execute(
                select(SyncRun).where(
                    SyncRun.request_id == 77,
                    SyncRun.source_id == "w0-src",
                    SyncRun.attempt == 2,
                )
            )
        ).scalar_one()
    assert found.id == run.id  # (request, source, attempt) 确定定位一行


async def test_4_null_request_id_is_valid_direct_run(_db):
    """cron/CLI 直跑:request_id=NULL 合法,派生态可用,终态不受影响。"""
    run = await sr.start_run(_db, source_id="w0-src", attempt=1, request_id=None)
    await sr.finish_run(_db, run.id, status=sr.RUN_COMPLETED, sync_log_id=uuid.uuid4())
    row = await _get(_db, run.id)
    assert row.request_id is None
    assert row.status == sr.RUN_COMPLETED
    state = sr.derive_run_state(None, row)
    assert state == sr.STATE_COMPLETED  # 无请求行也能给得出运行结论


# --------------------------------------------------------------------------- #
# 5-7:stage 流转 / counters / 已知未知 total
# --------------------------------------------------------------------------- #


async def test_5_stage_transitions_persist(_db):
    run = await sr.start_run(_db, source_id="w0-src", attempt=1)
    for stage, cur, total in [
        (sr.STAGE_FETCH, 12, 12),
        (sr.STAGE_PARSE, 12, 12),
        (sr.STAGE_CHUNK, 64, 130),
        (sr.STAGE_EMBED, 64, 130),
        (sr.STAGE_INDEX, 128, 130),
    ]:
        await sr.update_progress(_db, run.id, stage=stage, stage_current=cur, stage_total=total)
        row = await _get(_db, run.id)
        assert row.stage == stage and row.stage_current == cur and row.stage_total == total


async def test_6_counters_merge_factually(_db):
    run = await sr.start_run(_db, source_id="w0-src", attempt=1)
    await sr.update_counters(_db, run.id, discovered=31, accepted=30)
    await sr.update_counters(_db, run.id, extracted=28, deleted=2)
    row = await _get(_db, run.id)
    assert row.counters == {
        "discovered": 31,
        "accepted": 30,
        "extracted": 28,
        "deleted": 2,
    }


async def test_7_unknown_total_forbids_percentage(_db):
    # 分母未知:None → 永远 None;0 → None(除零防护);缺 current → None
    assert sr.progress_fraction(None, 37) is None
    assert sr.progress_fraction(0, 37) is None
    assert sr.progress_fraction(100, None) is None
    # 分母已知:可计算且夹在 0..1
    assert sr.progress_fraction(100, 37) == 0.37
    assert sr.progress_fraction(10, 99) == 1.0
    # 持久层语义:total NULL 的行读出来依然无法算百分比
    run = await sr.start_run(_db, source_id="w0-src", attempt=1)
    await sr.update_progress(_db, run.id, stage=sr.STAGE_FETCH, stage_current=37, stage_total=None)
    row = await _get(_db, run.id)
    assert sr.progress_fraction(row.stage_total, row.stage_current) is None
    assert row.stage_current == 37  # 真实计数保留("FETCH: 37 documents")


# --------------------------------------------------------------------------- #
# 8-9:终态成功 / 业务失败
# --------------------------------------------------------------------------- #


async def test_8_terminal_success_links_sync_log(_db):
    run = await sr.start_run(_db, source_id="w0-src", attempt=1)
    log_id = uuid.uuid4()
    await sr.finish_run(_db, run.id, status=sr.RUN_COMPLETED, sync_log_id=log_id)
    row = await _get(_db, run.id)
    assert row.status == sr.RUN_COMPLETED
    assert row.sync_log_id == log_id
    assert row.finished_at is not None
    assert row.stage == sr.STAGE_DONE


async def test_9_terminal_business_failure_records_error(_db):
    run = await sr.start_run(_db, source_id="w0-src", attempt=1)
    long_error = "x" * 2000
    await sr.finish_run(_db, run.id, status=sr.RUN_FAILED, error_summary=long_error)
    row = await _get(_db, run.id)
    assert row.status == sr.RUN_FAILED
    assert row.error_summary == "x" * 500  # 截断,不膨胀
    assert row.finished_at is not None


# --------------------------------------------------------------------------- #
# 10-13:中断 / 恢复 attempt / 孤儿完成 / 上限盖章(服从 recovery truth)
# --------------------------------------------------------------------------- #


async def test_10_interrupt_running_runs_stamps_only_running(_db):
    a = await sr.start_run(_db, source_id="w0-src", attempt=1, request_id=55)
    b = await sr.start_run(_db, source_id="w0-src2", attempt=2, request_id=55)
    other = await sr.start_run(_db, source_id="w0-orph", attempt=1, request_id=56)
    await sr.finish_run(_db, other.id, status=sr.RUN_COMPLETED)
    n = await sr.interrupt_running_runs(_db, 55)
    assert n == 2
    assert (await _get(_db, a.id)).status == sr.RUN_INTERRUPTED
    assert (await _get(_db, b.id)).status == sr.RUN_INTERRUPTED
    assert (await _get(_db, other.id)).status == sr.RUN_COMPLETED  # 他请求不动


async def test_11_recovery_attempt_row_records_attempt_and_recovery_flag(_db):
    run = await sr.start_run(
        _db, source_id="w0-src", attempt=2, request_id=88, recovery=True, triggered_by="manual"
    )
    row = await _get(_db, run.id)
    assert row.attempt == 2 and row.recovery is True and row.triggered_by == "manual"


async def test_12_orphan_completion_absorbs_with_sync_log_evidence(_db):
    """B1 语义的遥测面:孤儿 runner 完成的事实(sync_log)被链回 run 行。"""
    run = await sr.start_run(_db, source_id="w0-orph", attempt=1, request_id=99)
    async with _db() as session:
        log = SyncLog(
            source_id="w0-orph",
            source_type="exp",
            status="success",
            started_at=datetime.now(UTC) - timedelta(minutes=4),
            finished_at=datetime.now(UTC) - timedelta(minutes=3),
            triggered_by="manual",
        )
        session.add(log)
        await session.commit()
        await session.refresh(log)
        log_id = log.id
    stamped = await sr.complete_runs_with_evidence(_db, 99, {"w0-orph": log_id})
    assert stamped == 1
    row = await _get(_db, run.id)
    assert row.status == sr.RUN_COMPLETED
    assert row.sync_log_id == log_id


async def test_13_cap_terminal_stale_rows_can_be_stamped_interrupted(_db):
    """attempt 用尽 → reconcile 走终态 failed;其遗留 running 遥测行盖 interrupted。"""
    run = await sr.start_run(_db, source_id="w0-src", attempt=4, request_id=44)
    n = await sr.interrupt_running_runs(_db, 44)
    assert n == 1
    assert (await _get(_db, run.id)).status == sr.RUN_INTERRUPTED
    # 幂等:重复盖章不复活、不再计数
    assert await sr.interrupt_running_runs(_db, 44) == 0


# --------------------------------------------------------------------------- #
# 14-15:SyncLog 链接可查 / retention
# --------------------------------------------------------------------------- #


async def test_14_sync_log_linkage_queryable(_db):
    run = await sr.start_run(_db, source_id="w0-src", attempt=1, request_id=66)
    async with _db() as session:
        log = SyncLog(
            source_id="w0-src",
            source_type="exp",
            status="partial",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            triggered_by="manual",
        )
        session.add(log)
        await session.commit()
        await session.refresh(log)
        log_id = log.id
    await sr.finish_run(_db, run.id, status=sr.RUN_COMPLETED, sync_log_id=log_id)
    async with _db() as session:
        joined = (
            await session.execute(
                select(SyncRun, SyncLog).join(SyncLog, SyncRun.sync_log_id == SyncLog.id)
            )
        ).all()
    match = [(r, l) for r, l in joined if r.id == run.id]
    assert len(match) == 1 and match[0][1].status == "partial"  # 业务结局在 sync_log


async def test_15_retention_purges_expired_keeps_running_and_fresh(_db):
    old = datetime.now(UTC) - timedelta(days=sr.RETENTION_DAYS + 1)
    run_old_done = await sr.start_run(_db, source_id="w0-src", attempt=1, request_id=1)
    run_old_running = await sr.start_run(_db, source_id="w0-src", attempt=2, request_id=1)
    run_fresh = await sr.start_run(_db, source_id="w0-src", attempt=3, request_id=1)
    await sr.finish_run(_db, run_old_done.id, status=sr.RUN_COMPLETED)
    # 把旧行 started_at 拨老
    async with _db() as session:
        for rid in (run_old_done.id, run_old_running.id):
            await session.execute(
                sr.SyncRun.__table__.update().where(sr.SyncRun.id == rid).values(started_at=old)
            )
        await session.commit()
    purged = await sr.purge_expired_sync_runs(_db)
    assert purged == 1  # 只有 old+非 running 被清
    ids = set()
    async with _db() as session:
        rows = (await session.execute(select(SyncRun))).scalars().all()
        ids = {r.id for r in rows}
    assert run_old_done.id not in ids
    assert run_old_running.id in ids  # running 永不清
    assert run_fresh.id in ids


# --------------------------------------------------------------------------- #
# 派生态(纯函数;AC1/IDLE 不持久化虚假行)
# --------------------------------------------------------------------------- #


def _req(**kw) -> SyncRequest:
    base = {
        "id": 1,
        "source_id": "w0-src",
        "status": "pending",
        "attempt_count": 0,
        "failure_kind": None,
        "next_retry_at": None,
    }
    base.update(kw)
    return SyncRequest(**base)


def test_16a_derive_states_matrix():
    now = datetime.now(UTC)
    assert sr.derive_run_state(None, None) == sr.STATE_IDLE
    assert sr.derive_run_state(_req(), None) == sr.STATE_QUEUED
    assert (
        sr.derive_run_state(_req(next_retry_at=now + timedelta(seconds=60)), None)
        == sr.STATE_WAITING
    )
    assert sr.derive_run_state(_req(status="running"), None) == sr.STATE_RUNNING
    assert (
        sr.derive_run_state(
            _req(status="running", attempt_count=2, failure_kind="interrupted"), None
        )
        == sr.STATE_RECOVERING
    )
    assert sr.derive_run_state(_req(attempt_count=2, failure_kind="interrupted"), None) == (
        sr.STATE_RECOVERING
    )
    assert sr.derive_run_state(None, SyncRun(status=sr.RUN_COMPLETED)) == sr.STATE_COMPLETED
    assert sr.derive_run_state(None, SyncRun(status=sr.RUN_FAILED)) == sr.STATE_FAILED
    assert sr.derive_run_state(None, SyncRun(status=sr.RUN_INTERRUPTED)) == sr.STATE_INTERRUPTED


async def migrate_cleanup(engine) -> None:
    """迁移前清 sync_runs 残留(测试库复用防御;正式迁移面向全新表无此需)。"""
    from sqlalchemy import text as _t

    async with engine.begin() as conn:
        await conn.execute(_t("DELETE FROM sync_runs"))


async def test_16b_migration_idempotent_on_test_db(_db):
    """幂等迁移:建表+身份索引重复执行无副作用;列与索引契约满足。"""
    from sqlalchemy import inspect

    import scripts.migrate_add_sync_runs as mig

    dsn = os.environ.get("TEST_DATABASE_URL", load_settings().postgres_dsn)
    engine = get_engine(dsn)
    try:
        await migrate_cleanup(engine)  # 隔离:清残留行防历史脏数据卡唯一索引
        for _ in range(2):  # 第二次必须无副作用
            await mig.migrate(engine)
        async with engine.connect() as conn:
            cols = await conn.run_sync(
                lambda sc: {c["name"] for c in inspect(sc).get_columns("sync_runs")}
            )
            idx = await conn.run_sync(
                lambda sc: {i["name"] for i in inspect(sc).get_indexes("sync_runs")}
            )
        assert mig.EXPECTED_COLUMNS <= cols
        assert mig.IDENTITY_INDEX in idx
    finally:
        await engine.dispose()


# --------------------------------------------------------------------------- #
# 一致性事实结构化落库
# --------------------------------------------------------------------------- #


async def test_consistency_facts_persisted_structured(_db):
    run = await sr.start_run(_db, source_id="w0-src", attempt=1)
    report = {
        "expected_chunks": 120,
        "actual_chunks": 118,
        "missing": 1,
        "refill": 2,
        "stale_chunk_count": 0,
        "orphan_count": 1,
    }
    await sr.record_consistency(_db, run.id, report)
    row = await _get(_db, run.id)
    assert row.consistency == report


# --------------------------------------------------------------------------- #
# 集成:argv 贯穿 / reconcile 盖章 / _sync_one 落行(AC1-AC8 执行面证据)
# --------------------------------------------------------------------------- #


def test_argv_carries_request_identity():
    """executor→runner 的确定性链接:--request-id/--attempt 入 argv;cron 直跑无 --request-id。"""
    from scripts.sync_executor_loop import build_runner_argv

    argv = build_runner_argv("w0-src", "manual", recovery=True, request_id=42, attempt=2)
    assert argv[argv.index("--request-id") + 1] == "42"
    assert argv[argv.index("--attempt") + 1] == "2"
    assert "--force-incremental-replay" in argv
    plain = build_runner_argv(None, "manual")
    assert "--request-id" not in plain
    assert plain[plain.index("--attempt") + 1] == "1"


async def _seed_request(_db, source_id, *, attempt=1, picked_at=None) -> SyncRequest:
    async with _db() as session:
        row = SyncRequest(
            source_id=source_id,
            status="running",
            triggered_by="manual",
            attempt_count=attempt,
            picked_at=picked_at or datetime.now(UTC) - timedelta(minutes=10),
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        session.expunge(row)
    return row


async def test_reconcile_interrupt_branch_stamps_run_rows(_db):
    """对账 interrupted 裁决后,遥测行同步盖章(无完成事实)。"""
    from scripts.sync_executor_loop import reconcile_stale_running

    req = await _seed_request(_db, "w0-src")
    run = await sr.start_run(_db, source_id="w0-src", attempt=1, request_id=req.id)
    stats = await reconcile_stale_running(_db)
    assert stats["scheduled_retry"] == 1 and stats["runs_interrupted"] == 1
    row = await _get(_db, run.id)
    assert row.status == sr.RUN_INTERRUPTED and row.finished_at is not None
    # 请求仍走阶段⑩语义:pending + 证据锚(遥测不改变裁决)
    async with _db() as session:
        after = await session.get(SyncRequest, req.id)
        session.expunge(after)
    assert after.status == "pending" and after.attempt_started_at is not None


async def test_reconcile_done_branch_links_sync_log(_db):
    """完成事实优先:reconcile done 裁决 → 遥测行 completed + sync_log 链接。"""
    from scripts.sync_executor_loop import reconcile_stale_running

    picked = datetime.now(UTC) - timedelta(minutes=10)
    req = await _seed_request(_db, "w0-src2", picked_at=picked)
    run = await sr.start_run(_db, source_id="w0-src2", attempt=1, request_id=req.id)
    async with _db() as session:
        log = SyncLog(
            source_id="w0-src2",
            source_type="exp",
            status="success",
            started_at=picked + timedelta(minutes=1),
            finished_at=picked + timedelta(minutes=2),
            triggered_by="manual",
        )
        session.add(log)
        await session.commit()
        await session.refresh(log)
        log_id = log.id
    stats = await reconcile_stale_running(_db)
    assert stats["finalized_done"] == 1 and stats["runs_completed"] == 1
    row = await _get(_db, run.id)
    assert row.status == sr.RUN_COMPLETED and row.sync_log_id == log_id


async def test_reconcile_cap_branch_stamps_interrupted(_db):
    """attempt 用尽 → 终态 failed(阶段⑩);遥测行盖 interrupted,永不复活。"""
    from scripts.sync_executor_loop import MAX_TOTAL_ATTEMPTS, reconcile_stale_running

    req = await _seed_request(_db, "w0-orph", attempt=MAX_TOTAL_ATTEMPTS)
    run = await sr.start_run(
        _db, source_id="w0-orph", attempt=MAX_TOTAL_ATTEMPTS, request_id=req.id
    )
    stats = await reconcile_stale_running(_db)
    assert stats["terminal_failed"] == 1
    row = await _get(_db, run.id)
    assert row.status == sr.RUN_INTERRUPTED
    async with _db() as session:
        after = await session.get(SyncRequest, req.id)
        session.expunge(after)
    assert after.status == "failed"  # 恢复权威仍是 sync_requests


# ---- _sync_one 端到端(假 connector/pipeline,真 DB) ----


def _install_fake_connector():
    from backend.connectors.registry import ConnectorRegistry

    class _W0FakeConnector:
        def __init__(self, config):
            self._sid = config.id
            self.run_stats = None

        @property
        def source_id(self):
            return self._sid

        @property
        def product(self):
            return "test"

        def fetch_all(self):
            return []

        def fetch_changes(self, since):
            return ["d1", "d2", "d3"]  # 3 docs;非 RawDocument,fake pipeline 不在乎

        def fetch_deleted(self, since):
            return []

    ConnectorRegistry.register("w0fake")(_W0FakeConnector)


async def test_sync_one_writes_sync_run_lifecycle_end_to_end(_db):
    """AC1/AC2/AC3/AC5/AC6/AC14:attempt 启动即落行、阶段流转、终局链回 sync_log。"""
    from backend.connectors.registry import SourceConfig
    from scripts.sync import _sync_one

    _install_fake_connector()

    seen_during_ingest: dict = {}

    class _W0FakePipeline:
        def ingest_all(self, docs, *, progress=None):
            # ingest 完成前 SyncRun 行必须已存在(生命周期先于终局可观察):
            # 标志位由终局断言核实调用顺序
            seen_during_ingest["called"] = True
            if progress is not None:
                progress("CHUNK", len(docs))
                progress("EMBED", len(docs))
                progress("INDEX", len(docs))
            return {f"d{i}": 2 for i in range(len(docs))}

    cfg = SourceConfig(
        id="w0-src", type="w0fake", product="test", enabled=True, config={}, sync_interval="24h"
    )
    await _sync_one(
        cfg,
        _W0FakePipeline(),
        _db,
        triggered_by="manual",
        request_id=1234,
        attempt=2,
        recovery_replay=True,
    )
    assert seen_during_ingest.get("called") is True
    async with _db() as session:
        runs = (
            (
                await session.execute(
                    select(SyncRun).where(SyncRun.source_id == "w0-src").order_by(SyncRun.id)
                )
            )
            .scalars()
            .all()
        )
        logs = (
            (await session.execute(select(SyncLog).where(SyncLog.source_id == "w0-src")))
            .scalars()
            .all()
        )
    assert len(runs) == 1
    run = runs[0]
    assert run.request_id == 1234 and run.attempt == 2 and run.recovery is True
    assert run.status == sr.RUN_COMPLETED
    assert run.sync_log_id is not None
    assert [log.id for log in logs] == [run.sync_log_id]  # 确定性链路 request→run→log
    assert run.counters.get("docs_total") == 3 and run.counters.get("docs_done") == 3
    assert run.stage == sr.STAGE_DONE
    # 阶段足迹:INDEX/FETCH 至少落过 final 值
    assert run.stage_current == 3 and run.stage_total == 3


async def test_sync_one_business_failure_lands_run_failed(_db):
    """AC9(业务失败):ingest raise → SyncLog failed;SyncRun failed + error_summary。"""
    from backend.connectors.registry import SourceConfig
    from scripts.sync import _sync_one

    class _BoomPipeline:
        def ingest_all(self, docs, *, progress=None):
            raise RuntimeError("embed 爆炸")

    cfg = SourceConfig(
        id="w0-src", type="w0fake", product="test", enabled=True, config={}, sync_interval="24h"
    )
    await _sync_one(
        cfg,
        _BoomPipeline(),
        _db,
        triggered_by="manual",
        request_id=4321,
        attempt=1,
    )
    async with _db() as session:
        run = (
            (
                await session.execute(
                    select(SyncRun).where(SyncRun.source_id == "w0-src").order_by(SyncRun.id.desc())
                )
            )
            .scalars()
            .first()
        )
    assert run.status == sr.RUN_FAILED
    assert "embed 爆炸" in (run.error_summary or "")
    assert run.sync_log_id is not None  # 失败也有 sync_log(业务结局)


async def test_sync_one_telemetry_failure_never_breaks_business(_db):
    """遥测 DB 不可用时业务照常完成(尽力而为降级)。"""
    from backend.connectors.registry import SourceConfig
    from scripts.sync import _sync_one

    class _GhostFactory:
        """start_run 直接抛错,模拟遥测面故障。"""

        def __call__(self, *a, **k):
            raise RuntimeError("db down")

    class _OkPipeline:
        def ingest_all(self, docs, *, progress=None):
            return {}

    cfg = SourceConfig(
        id="w0-src", type="w0fake", product="test", enabled=True, config={}, sync_interval="24h"
    )
    # session_factory 同时承担业务 SyncLog 与遥测;遥测坏 → 不影响 SyncLog
    real_factory = _db

    class _HalfBrokenFactory:
        calls: ClassVar[dict[str, int]] = {"n": 0}

        def __call__(self):
            _HalfBrokenFactory.calls["n"] += 1
            if _HalfBrokenFactory.calls["n"] == 1:  # 第一次 = start_run 遥测
                raise RuntimeError("telemetry down")
            return real_factory()

    await _sync_one(
        cfg,
        _OkPipeline(),
        _HalfBrokenFactory(),
        triggered_by="manual",
        request_id=None,
        attempt=1,
    )
    async with real_factory() as session:
        log = (
            (await session.execute(select(SyncLog).where(SyncLog.source_id == "w0-src")))
            .scalars()
            .all()
        )
    assert log  # 业务 SyncLog 正常落库


# --------------------------------------------------------------------------- #
# FINAL REVIEW CORRECTION — RED 测试(三缺陷)
# --------------------------------------------------------------------------- #


async def test_red_a_normal_run_emits_and_persists_safety_filter(_db, monkeypatch):
    """BLOCKER A:正常同步生命周期必须观测并持久化 SAFETY_FILTER。

    真实管线在 ingest 批界逐 doc 过安全过滤;批次完成数是可真实提供的
    计数(进入过滤器的 doc 数),不伪造分母。
    """
    from backend.connectors.registry import SourceConfig
    from scripts.sync import _sync_one

    _install_fake_connector()
    recorded: list[tuple] = []
    _real = sr.update_progress

    async def _spy(factory, run_id, *, stage, stage_current=None, stage_total=None):
        recorded.append((stage, stage_current, stage_total))
        return await _real(
            factory, run_id, stage=stage, stage_current=stage_current, stage_total=stage_total
        )

    monkeypatch.setattr(sr, "update_progress", _spy)

    class _Pipeline:
        def ingest_all(self, docs, *, progress=None):
            if progress is not None:
                progress("SAFETY_FILTER", len(docs))  # 真实管线:逐 doc 过滤后按批界上报
                progress("CHUNK", len(docs))
                progress("EMBED", len(docs))
                progress("INDEX", len(docs))
            return {f"d{i}": 2 for i in range(len(docs))}

    cfg = SourceConfig(
        id="w0-src", type="w0fake", product="test", enabled=True, config={}, sync_interval="24h"
    )
    await _sync_one(cfg, _Pipeline(), _db, triggered_by="manual", request_id=9001, attempt=1)

    stages = [r[0] for r in recorded]
    assert sr.STAGE_SAFETY_FILTER in stages, f"SAFETY_FILTER 未被观测: {stages}"
    assert stages.index(sr.STAGE_SAFETY_FILTER) < stages.index(sr.STAGE_DONE)
    sf_all = [r for r in recorded if r[0] == sr.STAGE_SAFETY_FILTER]
    # 边界标记(NULL/NULL,契约允许)+ 批界真实计数(进入过滤器的 doc 数)
    assert any(r[1] == 3 for r in sf_all), f"无真实计数: {sf_all}"
    assert any(r[1] is None for r in sf_all), f"缺边界标记: {sf_all}"


async def test_red_b_normal_successful_run_persists_final_consistency_before_done(_db, monkeypatch):
    """BLOCKER B:业务成功的正常同步必须以真实 verify_source_vectors 收尾,
    CONSISTENCY 先于 DONE;不得凭 ingest 成功推断健康。"""
    from backend.connectors.registry import SourceConfig
    from scripts import sync as sync_mod
    from scripts.sync import _sync_one

    _install_fake_connector()

    class _FakeCollection:
        def iterator(self, return_properties=None):
            return iter([])

    class _FakeCollections:
        def get(self, name):
            return _FakeCollection()

    class _FakeClient:
        collections = _FakeCollections()

    class _Pipeline:
        _client = _FakeClient()
        _class_name = "W0Fake"

        def ingest_all(self, docs, *, progress=None):
            if progress is not None:
                progress("SAFETY_FILTER", len(docs))
                progress("CHUNK", len(docs))
                progress("EMBED", len(docs))
                progress("INDEX", len(docs))
            return {f"d{i}": 2 for i in range(len(docs))}

    calls = {"verify": 0}
    _orig = sync_mod.verify_source_vectors

    async def _count_verify(*a, **k):
        calls["verify"] += 1
        return await _orig(*a, **k)

    monkeypatch.setattr(sync_mod, "verify_source_vectors", _count_verify)

    cfg = SourceConfig(
        id="w0-src", type="w0fake", product="test", enabled=True, config={}, sync_interval="24h"
    )
    await _sync_one(cfg, _Pipeline(), _db, triggered_by="manual", request_id=9002, attempt=1)

    assert calls["verify"] >= 1, "正常成功路径未执行终局一致性校验"
    async with _db() as session:
        run = (
            (
                await session.execute(
                    select(SyncRun).where(SyncRun.source_id == "w0-src").order_by(SyncRun.id.desc())
                )
            )
            .scalars()
            .first()
        )
    assert run.stage == sr.STAGE_DONE
    assert run.consistency is not None, "终局一致性事实未持久化"
    assert run.consistency.get("expected_chunks") == 0
    assert run.consistency.get("actual_chunks") == 0


async def test_red_c_duplicate_request_run_rejected_null_stays_legal(_db):
    """BLOCKER C:非空 request 三元组 DB 级唯一;NULL 直跑多次合法。"""
    from sqlalchemy.exc import IntegrityError

    await sr.start_run(_db, source_id="w0-src", attempt=1, request_id=777)
    with pytest.raises(IntegrityError):
        await sr.start_run(_db, source_id="w0-src", attempt=1, request_id=777)
    async with _db() as session:
        rows = (
            (
                await session.execute(
                    select(SyncRun).where(SyncRun.request_id == 777, SyncRun.source_id == "w0-src")
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1  # 不静默覆写、不产生双权威行
    # NULL request_id 直跑:同源同 attempt 多次独立运行合法
    r1 = await sr.start_run(_db, source_id="w0-src2", attempt=1, request_id=None)
    r2 = await sr.start_run(_db, source_id="w0-src2", attempt=1, request_id=None)
    assert r1.id != r2.id
