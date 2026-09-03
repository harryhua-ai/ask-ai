"""⑫ Realtime progress:ingest 移入工作线程 + 批界进度实时持久化 + short-circuit 事实。

冻结语义(W2 契约):
- ingest_all 全程在 asyncio.to_thread 工作线程执行,事件循环不阻塞——
  同进程内并发读者(API/health)可从 sync_runs 读到真实批界相位;
- 批界回调按 SYNC_PROGRESS_FLUSH_INTERVAL_SECONDS 防抖摊销落笔(不做
  每 chunk DB storm);终笔与既有语义一致(四 stage 终值,结束态 INDEX→…→DONE);
- short-circuit(无上游变更+一致性健康)落 counters.ingestion_skipped=1,
  与 refill/孤儿处置等真实灌入路径严格区分;
- 任一 doc 灌入失败 → SyncLog failed + SyncRun failed(既有契约不变)。
"""

import asyncio
import os
import threading
import time
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.config import load_settings
from backend.db.models import SyncLog, SyncRequest, SyncRun
from backend.db.session import get_engine, get_session_factory, init_db
from backend.services import sync_runs as sr
import scripts.sync as sync_mod
from backend.connectors.registry import SourceConfig

pytestmark = pytest.mark.asyncio(loop_scope="session")

SRC = "w2-rt"


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def _db():
    dsn = os.environ.get("TEST_DATABASE_URL", load_settings().postgres_dsn)
    engine = get_engine(dsn)
    await init_db(engine)
    from scripts.migrate_add_sync_run_runtime_facts import migrate

    await migrate(engine)
    return get_session_factory(engine)


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _clean(_db):
    async with _db() as session:
        await session.execute(SyncRun.__table__.delete().where(SyncRun.source_id == SRC))
        await session.execute(SyncLog.__table__.delete().where(SyncLog.source_id == SRC))
        await session.execute(SyncRequest.__table__.delete().where(SyncRequest.source_id == SRC))
        await session.commit()
    yield
    async with _db() as session:
        await session.execute(SyncRun.__table__.delete().where(SyncRun.source_id == SRC))
        await session.execute(SyncLog.__table__.delete().where(SyncLog.source_id == SRC))
        await session.execute(SyncRequest.__table__.delete().where(SyncRequest.source_id == SRC))
        await session.commit()


class _StubConnector:
    def __init__(self, doc_ids: list[str]) -> None:
        self._doc_ids = doc_ids

    def fetch_changes(self, since):  # noqa: ANN001, ANN202
        return list(self._doc_ids)

    def fetch_all(self):  # noqa: ANN202
        return [SimpleNamespace(source_id=doc) for doc in self._doc_ids]

    def fetch_deleted(self, since):  # noqa: ANN001, ANN202
        return []


class _BlockingPipeline:
    """ingest_all 工作线程侧替身:回调后阻塞,直到测试显式放行。"""

    def __init__(self, doc_ids: list[str], raise_before_index: bool = False) -> None:
        self._doc_ids = doc_ids
        self._raise_before_index = raise_before_index
        self._release = threading.Event()

    def release(self) -> None:
        self._release.set()

    def ingest_all(self, docs, progress=None):  # noqa: ANN001, ANN202
        if progress is not None:
            progress(sr.STAGE_SAFETY_FILTER, len(docs))
            progress(sr.STAGE_CHUNK, len(docs))
            progress(sr.STAGE_EMBED, len(docs))
        if self._raise_before_index:
            raise RuntimeError("批量 embed 失败(模拟 GPU 故障)")
        assert self._release.wait(timeout=15), "ingest 未被测试放行"
        if progress is not None:
            progress(sr.STAGE_INDEX, len(docs))
        return {doc: 1 for doc in docs}


class _NoopPipeline:
    def ingest_all(self, docs, progress=None):  # noqa: ANN001, ANN202
        return {i: 2 for i, _ in enumerate(docs)}  # 每 doc 2 chunks(不可哈希对象作 key 不安全)


def _healthy_report() -> SimpleNamespace:
    return SimpleNamespace(
        expected_chunks=10,
        actual_chunks=10,
        missing_source_ids=[],
        refill_source_ids=[],
        stale_chunk_count=0,
        orphan_count=0,
        orphan_chunks=[],
        is_healthy=True,
    )


def _gap_report() -> SimpleNamespace:
    return SimpleNamespace(
        expected_chunks=10,
        actual_chunks=8,
        missing_source_ids=["d1"],
        refill_source_ids=["d1"],
        stale_chunk_count=0,
        orphan_count=1,
        orphan_chunks=["x"],
        is_healthy=False,
    )


async def _latest_run(_db) -> SyncRun | None:
    async with _db() as session:
        row = (
            await session.execute(
                select(SyncRun).where(SyncRun.source_id == SRC).order_by(SyncRun.id.desc()).limit(1)
            )
        ).scalar_one_or_none()
        if row is not None:
            session.expunge(row)
    return row


async def _wait_for_stage(_db, stage: str, timeout: float = 10.0) -> SyncRun:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = await _latest_run(_db)
        if row is not None and row.stage == stage:
            return row
        await asyncio.sleep(0.05)
    row = await _latest_run(_db)
    raise AssertionError(
        f"未在 {timeout}s 内观测到 stage={stage};当前={row and (row.stage, row.status)}"
    )


async def test_1_realtime_progress_persists_while_ingest_blocked(_db, monkeypatch):
    """ingest 阻塞在工作线程期间:事件循环不被阻塞,EMBED 相位已持久化。"""
    monkeypatch.setattr(sync_mod, "SYNC_PROGRESS_FLUSH_INTERVAL_SECONDS", 0.05)

    async def _fake_verify(session_factory, pipeline, source_id):
        return _healthy_report()

    monkeypatch.setattr(sync_mod, "verify_source_vectors", _fake_verify)
    monkeypatch.setattr(
        sync_mod.ConnectorRegistry,
        "create",
        classmethod(lambda cls, cfg: _StubConnector(["d1", "d2"])),
    )

    cfg = SourceConfig(
        id=SRC, type="github", product="t", enabled=True, config={}, sync_interval="24h"
    )
    pipeline = _BlockingPipeline(["d1", "d2"])
    task = asyncio.create_task(sync_mod._sync_one(cfg, pipeline, _db, triggered_by="cron"))

    # 并发轮询(事件循环活着)→ 在 ingest 仍阻塞时读到 EMBED 批界事实
    row = await _wait_for_stage(_db, sr.STAGE_EMBED)
    assert row.status == sr.RUN_RUNNING
    assert row.stage_current == 2
    assert row.stage_total == 2  # 分母真实;stage_total 为 None 的场景由 API 测试覆盖

    pipeline.release()
    await asyncio.wait_for(task, timeout=15)

    final = await _latest_run(_db)
    assert final.status == sr.RUN_COMPLETED
    assert final.stage == sr.STAGE_DONE
    assert final.counters.get("docs_total") == 2
    assert final.counters.get("docs_done") == 2
    async with _db() as session:
        log = (
            (
                await session.execute(
                    select(SyncLog).where(SyncLog.source_id == SRC).order_by(SyncLog.id.desc())
                )
            )
            .scalars()
            .first()
        )
    assert log is not None and log.status == "success"
    assert log.items_new == 2 and log.items_updated == 2


async def test_2_ingest_failure_keeps_failed_contract(_db, monkeypatch):
    """批量 embed 失败:既有契约不变——SyncLog failed + SyncRun failed + error_summary。"""
    monkeypatch.setattr(sync_mod, "SYNC_PROGRESS_FLUSH_INTERVAL_SECONDS", 0.05)

    async def _fake_verify(session_factory, pipeline, source_id):
        return _healthy_report()

    monkeypatch.setattr(sync_mod, "verify_source_vectors", _fake_verify)
    monkeypatch.setattr(
        sync_mod.ConnectorRegistry,
        "create",
        classmethod(lambda cls, cfg: _StubConnector(["d1", "d2"])),
    )

    cfg = SourceConfig(
        id=SRC, type="github", product="t", enabled=True, config={}, sync_interval="24h"
    )
    pipeline = _BlockingPipeline(["d1", "d2"], raise_before_index=True)
    await asyncio.wait_for(sync_mod._sync_one(cfg, pipeline, _db, triggered_by="cron"), timeout=15)

    final = await _latest_run(_db)
    assert final.status == sr.RUN_FAILED
    assert "批量 embed 失败" in (final.error_summary or "")
    async with _db() as session:
        log = (
            (
                await session.execute(
                    select(SyncLog).where(SyncLog.source_id == SRC).order_by(SyncLog.id.desc())
                )
            )
            .scalars()
            .first()
        )
    assert log.status == "failed"


async def test_3_short_circuit_writes_ingestion_skipped_fact(_db, monkeypatch):
    """无上游变更 + 一致性健康 → counters.ingestion_skipped=1(机器事实)。"""

    async def _fake_verify(session_factory, pipeline, source_id):
        return _healthy_report()

    monkeypatch.setattr(sync_mod, "verify_source_vectors", _fake_verify)

    tel = sync_mod._RunTelemetry()
    await tel.start(
        _db, source_id=SRC, request_id=None, attempt=1, recovery=False, triggered_by="cron"
    )
    log_entry = SyncLog(source_id=SRC, source_type="github", status="success")
    await sync_mod._handle_no_change(
        SRC,
        7,
        _StubConnector([]),
        _NoopPipeline(),
        _db,
        log_entry,
        time.monotonic(),
        telemetry=tel,
    )
    assert log_entry.status == "success"
    assert log_entry.items_new == 0 and log_entry.items_updated == 0
    assert log_entry.items_unchanged == 7
    run = await _latest_run(_db)
    assert run.counters.get("ingestion_skipped") == 1
    assert sr.is_ingestion_skipped(run.counters, log_entry) is True


async def test_4_gap_refill_is_not_short_circuit(_db, monkeypatch):
    """缺口补灌 = 真实灌入:绝不落 ingestion_skipped;复验收敛 → success。"""
    reports = iter([_gap_report(), _healthy_report()])

    async def _fake_verify(session_factory, pipeline, source_id):
        return next(reports)

    monkeypatch.setattr(sync_mod, "verify_source_vectors", _fake_verify)
    # 孤儿 reconciliation:无孤儿 chunk 细节时走保留分支,不删除任何向量
    monkeypatch.setattr(sync_mod, "_reconcile_orphan_vectors", lambda *a, **k: (0, 0, 1))

    tel = sync_mod._RunTelemetry()
    await tel.start(
        _db, source_id=SRC, request_id=None, attempt=1, recovery=False, triggered_by="cron"
    )
    log_entry = SyncLog(source_id=SRC, source_type="github", status="success")
    connector = _StubConnector(["d1"])
    await sync_mod._handle_no_change(
        SRC,
        7,
        connector,
        _NoopPipeline(),
        _db,
        log_entry,
        time.monotonic(),
        telemetry=tel,
    )
    assert log_entry.status == "success"  # 复验收敛
    assert log_entry.items_updated == 2  # refill 真实灌入(_NoopPipeline 每 doc 2 chunks)
    assert log_entry.items_new == 0
    run = await _latest_run(_db)
    assert "ingestion_skipped" not in (run.counters or {})
    assert sr.is_ingestion_skipped(run.counters, log_entry) is False
    # missing 与 orphan 是不同事实,同一 consistency 载荷内分别可读
    facts = run.consistency or {}
    assert "missing" in facts and "orphan_count" in facts


def test_5_consistency_facts_keep_missing_and_orphan_distinct():
    facts = sync_mod._consistency_facts(_gap_report())
    assert facts["missing"] == 1
    assert facts["orphan_count"] == 1
    assert facts["refill"] == 1
    assert facts["expected_chunks"] == 10 and facts["actual_chunks"] == 8
