"""#71 Authoritative membership reconciliation — `_sync_one` acceptance tests.

Frozen requirements under test (Issue #71 authorization):

- reconciliation runs even when content delta is empty / remote SHA unchanged
  (requirement 6) — the exact #71 blackout/short-circuit class;
- stale_set retires via existing tombstone semantics (requirement 5);
- kill/interruption safety: no persisted success truth before reconciliation
  completes (requirement 8);
- Admin health consumes persisted currency truth (requirements 10-11);
- counter semantics: stale_detected / stale_retired observable separately,
  items_new/items_deleted no longer carry orphan-vector operations
  (requirement 13);
- repeated sync converges idempotently (requirement 7);
- exact #71 NE503-class reproduction (acceptance list).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import scripts.sync as sync_mod
from backend.config import load_settings
from backend.connectors.base import RawDocument
from backend.connectors.registry import SourceConfig
from backend.db.models import DataSource, Document, DocumentVersion, SyncLog, SyncRun
from backend.db.session import get_engine, get_session_factory, init_db
from backend.services.document_lifecycle import DocLifecycle

pytestmark = pytest.mark.asyncio(loop_scope="session")

SRC = "wiki-documents-local"

def _uuid4():
    import uuid
    return uuid.uuid4()


def _hash(sid: str) -> str:
    import hashlib
    return hashlib.sha256(sid.encode()).hexdigest()

OLD = f"{SRC}/main/docs/6-neoeyes-ne503-series/4-application-guide/1-app-development/reference/2-sdk-reference.md"
OLD_I18N = f"{SRC}/main/i18n/en/docusaurus-plugin-content-docs/current/6-neoeyes-ne503-series/4-application-guide/1-app-development/reference/2-sdk-reference.md"
SUCCESSOR = f"{SRC}/main/docs/6-neoeyes-ne503-series/4-application-guide/3-reference/1-sdk-reference.md"
HEALTHY = f"{SRC}/main/docs/6-neoeyes-ne503-series/0-overview.md"


# --------------------------------------------------------------------------- #
# harness
# --------------------------------------------------------------------------- #


@dataclass
class _Report:
    """verify_source_vectors stub payload with real numeric fields."""

    expected_chunks: int = 10
    actual_chunks: int = 10
    missing_source_ids: list = field(default_factory=list)
    refill_source_ids: list = field(default_factory=list)
    orphan_count: int = 0
    orphan_chunks: dict = field(default_factory=dict)
    stale_chunk_count: int = 0
    is_healthy: bool = True


class _StubBuilder:
    """GenerationBuilder stand-in with real BuildAccounting semantics."""

    def __init__(self, new_docs: list[str] | None = None) -> None:
        self._new_docs = new_docs or []
        self.calls: list[list[RawDocument]] = []
        from backend.pipeline.generation_builder import BuildAccounting

        self._accounting_cls = BuildAccounting

    def build_generation(self, docs, *, source_id, force_rebuild=False, progress=None):
        self.calls.append(list(docs))
        return self._accounting_cls(
            source_id=source_id,
            new_docs=list(self._new_docs),
            chunks_written=2 * len(docs),
        )

    def repair_documents(self, doc_ids, *, source_id_scope=None):  # pragma: no cover
        return ([], [], 0)


class _Connector:
    """Sync connector stub: delta empty (SHA short-circuit), windows expired."""

    def __init__(
        self,
        changes: list[RawDocument] | None = None,
        deleted: list[str] | None = None,
        members: set[str] | None = None,
        enumerate_error: Exception | None = None,
        with_membership: bool = True,
    ) -> None:
        self._changes = changes or []
        self._deleted = deleted or []
        self._members = members
        self._enumerate_error = enumerate_error
        if with_membership:
            self.membership_source_ids = self._membership  # type: ignore[attr-defined]

    def _membership(self) -> set[str]:
        if self._enumerate_error is not None:
            raise self._enumerate_error
        return set(self._members or set())

    def fetch_all(self):
        return iter([])

    def fetch_changes(self, since):
        return iter(self._changes)

    def fetch_deleted(self, since):
        return list(self._deleted)


class _Pipeline:
    def __init__(self, session_factory) -> None:
        self._embedder = None
        self._session_factory = session_factory


def _cfg() -> SourceConfig:
    return SourceConfig(
        id=SRC,
        type="github",
        product="wiki",
        enabled=True,
        config={},
        sync_interval="24h",
    )


def _mk_source(session) -> DataSource:
    ds = DataSource(id=SRC, type="github", product="wiki", config={})
    session.add(ds)
    return ds


def _mk_active_doc(session, source_id: str, ordinal: int = 0) -> Document:
    doc = Document(
        source_id=source_id,
        source_type="github",
        product="wiki",
        title=source_id.rsplit("/", 1)[-1],
        url=f"https://github.com/example/blob/main/{source_id}",
        branch="main",
        chunk_count=8,
        content_hash=_hash(source_id),
        lifecycle=DocLifecycle.ACTIVE,
    )
    session.add(doc)
    version = DocumentVersion(
        id=_uuid4(),
        source_id=source_id,
        version_seq=1,
        content_hash=doc.content_hash,
        metadata_hash=_hash("m" + source_id),
        generation_id="00000000-0000-0000-0000-000000000000",
        generation_ordinal=ordinal,
        status="active",
        title=doc.title,
        url=doc.url,
        chunk_count=8,
    )
    session.add(version)
    doc.current_version_id = version.id
    return doc


async def _seed(db_engine, docs: dict[str, int]) -> None:
    factory = get_session_factory(db_engine)
    async with factory() as session:
        _mk_source(session)
        for sid, ordinal in docs.items():
            _mk_active_doc(session, sid, ordinal=ordinal)
        await session.commit()


def _raw_doc(source_id: str) -> RawDocument:
    return RawDocument(
        source_id=source_id,
        source_type="github",
        product="wiki",
        title=source_id.rsplit("/", 1)[-1],
        content="content",
        url=f"https://github.com/example/blob/main/{source_id}",
        metadata={"path": source_id},
        content_hash=_hash(source_id),
        branch="main",
    )


async def _latest_sync_log(factory) -> SyncLog:
    async with factory() as session:
        row = (
            await session.execute(
                select(SyncLog)
                .where(SyncLog.source_id == SRC)
                .order_by(SyncLog.started_at.desc())
                .limit(1)
            )
        ).scalar_one()
        return SimpleNamespace(
            status=row.status,
            items_deleted=row.items_deleted,
            items_new=row.items_new,
            delta_counts=dict(row.delta_counts or {}),
            error_detail=row.error_detail,
        )


async def _doc(factory, source_id: str) -> Document:
    async with factory() as session:
        return (
            await session.execute(select(Document).where(Document.source_id == source_id))
        ).scalar_one()


async def _datasource(factory) -> DataSource:
    async with factory() as session:
        ds = (
            await session.execute(select(DataSource).where(DataSource.id == SRC))
        ).scalar_one()
        session.expunge(ds)
        return ds


_CURRENT: dict = {"connector": None}


def _register(connector) -> None:
    _CURRENT["connector"] = connector


@pytest.fixture(autouse=True)
def _stub_registry(monkeypatch):
    """_sync_one 起手即 ConnectorRegistry.create(cfg);测试注入受控 connector。"""
    monkeypatch.setattr(
        sync_mod.ConnectorRegistry, "create", lambda cfg: _CURRENT["connector"]
    )
    yield
    _CURRENT["connector"] = None


@pytest.fixture
def healthy_report(monkeypatch):
    """Patch verify_source_vectors everywhere sync.py consumes it."""
    report = _Report()
    monkeypatch.setattr(
        sync_mod, "verify_source_vectors", _async_return(report), raising=True
    )
    return report


@pytest_asyncio.fixture(loop_scope="session")
async def db_engine():
    """Per-test engine on the session loop (conftest 的 db_engine 绑定函数循环)."""
    dsn = os.environ.get("TEST_DATABASE_URL", load_settings().postgres_dsn)
    engine = get_engine(dsn)
    try:
        await init_db(engine)
        from scripts.migrate_add_membership_currency import migrate as _migrate
        await _migrate(engine)  # #71 加性列(共享测试库的既有表需补列)
        yield engine
    finally:
        f = get_session_factory(engine)
        async with f() as session:
            await session.execute(delete(SyncRun).where(SyncRun.source_id == SRC))
            await session.execute(delete(SyncLog).where(SyncLog.source_id == SRC))
            await session.execute(
                delete(Document).where(Document.source_id.like(f"{SRC}/%"))
            )
            await session.execute(
                delete(DocumentVersion).where(DocumentVersion.source_id.like(f"{SRC}/%"))
            )
            await session.execute(delete(DataSource).where(DataSource.id == SRC))
            await session.commit()
        await engine.dispose()


@pytest.fixture
def sync_factory(db_engine):
    """同步账本面(与 pipeline._session_factory 同语义;schema 由 async 侧建)。"""
    import sqlalchemy
    dsn = os.environ.get("TEST_DATABASE_URL", load_settings().postgres_dsn)
    engine = sqlalchemy.create_engine(dsn.replace("+asyncpg", "+psycopg2"))
    try:
        yield sqlalchemy.orm.sessionmaker(bind=engine)
    finally:
        engine.dispose()


def _truth_commit_failing_factory(real_factory, fail_state: dict):
    """真值持久化注入面:仅当会话持有已置 membership_status 的脏 DataSource
    (即成员货币真值写)时令 commit 失败;SyncLog/SyncRun/调度写不受影响 ——
    在持久层故障注入,使「吞错 best-effort」实现与「显式失败」契约可分辨。
    """
    from contextlib import asynccontextmanager

    from backend.db.models import DataSource as _DS

    @asynccontextmanager
    async def _ctx():
        async with real_factory() as session:
            original_commit = session.commit

            async def _commit():
                truth_write_pending = any(
                    isinstance(obj, _DS) and obj.membership_status is not None
                    for obj in session.dirty
                )
                if truth_write_pending and fail_state["fail"]:
                    raise RuntimeError("simulated truth persistence outage")
                await original_commit()

            session.commit = _commit  # type: ignore[method-assign]
            yield session

    return _ctx


# --------------------------------------------------------------------------- #
# R2 BLOCKER 2: truth persistence is NOT best-effort
# --------------------------------------------------------------------------- #


async def test_t1_truth_persistence_failure_is_never_success_or_current(
    db_engine, sync_factory, monkeypatch, healthy_report
):
    """RED-2: reconcile succeeds + truth commit raises ⇒ partial, no current claim."""
    factory = get_session_factory(db_engine)
    await _seed(db_engine, {OLD: 0, HEALTHY: 0})
    connector = _Connector(members={HEALTHY})
    _register(connector)
    fail_state = {"fail": True}
    failing_factory = _truth_commit_failing_factory(factory, fail_state)

    await sync_mod._sync_one(
        _cfg(),
        _Pipeline(sync_factory),
        failing_factory,
        triggered_by="cron",
        builder=_StubBuilder(),
    )

    log = await _latest_sync_log(factory)
    assert log.status == "partial"
    assert "truth persistence" in (log.error_detail or "").lower()
    membership_status = log.delta_counts.get("membership_status")
    assert membership_status != "current"  # no false current claim
    ds = await _datasource(factory)
    assert ds.membership_status is None  # nothing persisted — no fabricated truth


async def test_t2_tombstones_survive_failure_then_next_round_establishes_truth(
    db_engine, sync_factory, monkeypatch, healthy_report
):
    """RED-3: committed tombstones are not undone; next round re-establishes truth."""
    factory = get_session_factory(db_engine)
    await _seed(db_engine, {OLD: 0, HEALTHY: 0})
    connector = _Connector(members={HEALTHY})
    _register(connector)
    fail_state = {"fail": True}
    failing_factory = _truth_commit_failing_factory(factory, fail_state)

    await sync_mod._sync_one(
        _cfg(),
        _Pipeline(sync_factory),
        failing_factory,
        triggered_by="cron",
        builder=_StubBuilder(),
    )

    stale = await _doc(factory, OLD)
    assert stale.lifecycle == DocLifecycle.DELETED  # retirement NOT rolled back
    ds = await _datasource(factory)
    assert ds.membership_status is None

    log1 = await _latest_sync_log(factory)
    assert log1.status == "partial"  # truth not established ⇒ never success

    # Round 2 with healthy persistence: converges and establishes truth.
    fail_state["fail"] = False
    await sync_mod._sync_one(
        _cfg(),
        _Pipeline(sync_factory),
        factory,
        triggered_by="cron",
        builder=_StubBuilder(),
    )
    log2 = await _latest_sync_log(factory)
    assert log2.status == "success"
    assert log2.delta_counts["membership_status"] == "current"
    assert log2.delta_counts["stale_detected"] == 0
    ds2 = await _datasource(factory)
    assert ds2.membership_status == "current"


async def test_t3_unsupported_truth_persistence_failure_is_visible(
    db_engine, sync_factory, monkeypatch, healthy_report
):
    """RED-4: unsupported truth write failing must not pass as successful."""
    factory = get_session_factory(db_engine)
    await _seed(db_engine, {HEALTHY: 0})
    connector = _Connector(with_membership=False)
    _register(connector)
    fail_state = {"fail": True}
    failing_factory = _truth_commit_failing_factory(factory, fail_state)

    await sync_mod._sync_one(
        _cfg(),
        _Pipeline(sync_factory),
        failing_factory,
        triggered_by="cron",
        builder=_StubBuilder(),
    )

    log = await _latest_sync_log(factory)
    assert log.status == "partial"
    assert "truth persistence" in (log.error_detail or "").lower()
    assert log.delta_counts.get("membership_status") != "unsupported"
    ds = await _datasource(factory)
    assert ds.membership_status is None  # no fabricated persisted truth


def _async_return(value):
    from unittest.mock import AsyncMock

    return AsyncMock(return_value=value)


# --------------------------------------------------------------------------- #
# acceptance scenarios
# --------------------------------------------------------------------------- #


async def test_s1_sha_unchanged_no_change_round_still_reconciles(
    db_engine, sync_factory, monkeypatch, healthy_report
):
    """Requirement 6: empty delta / SHA short-circuit round MUST reconcile (#71)."""
    factory = get_session_factory(db_engine)
    await _seed(db_engine, {OLD: 0, HEALTHY: 0})
    connector = _Connector(members={HEALTHY})
    _register(connector)

    await sync_mod._sync_one(
        _cfg(),
        _Pipeline(sync_factory),
        factory,
        triggered_by="cron",
        builder=_StubBuilder(),
    )

    stale = await _doc(factory, OLD)
    healthy = await _doc(factory, HEALTHY)
    assert stale.lifecycle == DocLifecycle.DELETED
    assert healthy.lifecycle == DocLifecycle.ACTIVE

    log = await _latest_sync_log(factory)
    assert log.status == "success"
    assert log.delta_counts["stale_detected"] == 1
    assert log.delta_counts["stale_retired"] == 1
    assert log.delta_counts["membership_status"] == "current"

    ds = await _datasource(factory)
    assert ds.membership_status == "current"
    assert ds.membership_stale_detected == 1
    assert ds.membership_stale_retired == 1
    assert ds.membership_checked_at is not None


async def test_s2_rename_round_old_identity_retires_new_ingests(
    db_engine, sync_factory, monkeypatch, healthy_report
):
    """Requirement 17 (minimum): old retires; new identity ingests; no double-serving."""
    factory = get_session_factory(db_engine)
    await _seed(db_engine, {OLD: 0, HEALTHY: 0})
    connector = _Connector(changes=[_raw_doc(SUCCESSOR)], members={SUCCESSOR, HEALTHY})
    _register(connector)
    builder = _StubBuilder(new_docs=[SUCCESSOR])

    await sync_mod._sync_one(
        _cfg(),
        _Pipeline(sync_factory),
        factory,
        triggered_by="cron",
        builder=builder,
    )

    old = await _doc(factory, OLD)
    assert old.lifecycle == DocLifecycle.DELETED
    assert [d.source_id for d in builder.calls[0]] == [SUCCESSOR]  # new identity ingested

    log = await _latest_sync_log(factory)
    assert log.delta_counts["stale_detected"] == 1
    assert log.delta_counts["stale_retired"] == 1
    assert log.items_deleted == 1  # document-level retirement accounting


async def test_s3_enumeration_failure_downgrades_round_and_persists_failed(
    db_engine, sync_factory, monkeypatch, healthy_report
):
    """Requirement 8/10: unresolved authority ≠ success; truth says failed."""
    factory = get_session_factory(db_engine)
    await _seed(db_engine, {OLD: 0, HEALTHY: 0})
    connector = _Connector(enumerate_error=RuntimeError("github api unavailable"))
    _register(connector)

    await sync_mod._sync_one(
        _cfg(),
        _Pipeline(sync_factory),
        factory,
        triggered_by="cron",
        builder=_StubBuilder(),
    )

    log = await _latest_sync_log(factory)
    assert log.status == "partial"
    assert "membership" in (log.error_detail or "").lower()

    ds = await _datasource(factory)
    assert ds.membership_status == "failed"
    stale = await _doc(factory, OLD)
    assert stale.lifecycle == DocLifecycle.ACTIVE  # evidence first — untouched


async def test_s4_connector_without_membership_capability_is_reported_unsupported(
    db_engine, sync_factory, monkeypatch, healthy_report
):
    """Requirement 18: connectors without the capability keep legacy behavior."""
    factory = get_session_factory(db_engine)
    await _seed(db_engine, {HEALTHY: 0})
    connector = _Connector(with_membership=False)
    _register(connector)

    await sync_mod._sync_one(
        _cfg(),
        _Pipeline(sync_factory),
        factory,
        triggered_by="cron",
        builder=_StubBuilder(),
    )

    log = await _latest_sync_log(factory)
    assert log.status == "success"  # legacy semantics preserved
    ds = await _datasource(factory)
    assert ds.membership_status == "unsupported"
    assert log.delta_counts["membership_status"] == "unsupported"


async def test_s5_kill_safety_retirement_is_atomic_and_success_not_claimed(
    db_engine, sync_factory, monkeypatch, healthy_report
):
    """Requirement 8: mid-retirement failure → no truth advance, no partial state."""
    factory = get_session_factory(db_engine)
    await _seed(db_engine, {OLD: 0, HEALTHY: 0})
    connector = _Connector(members={HEALTHY})
    _register(connector)

    from backend.services import membership_currency as mc

    real_tombstone = mc.tombstone_document

    def _boom(session, source_id, *, reason="", now=None):
        if source_id == OLD:
            raise RuntimeError("simulated kill mid-reconciliation")
        return real_tombstone(session, source_id, reason=reason, now=now)

    monkeypatch.setattr(mc, "tombstone_document", _boom)

    await sync_mod._sync_one(
        _cfg(),
        _Pipeline(sync_factory),
        factory,
        triggered_by="cron",
        builder=_StubBuilder(),
    )

    log = await _latest_sync_log(factory)
    assert log.status == "partial"  # never claims success over unresolved drift
    ds = await _datasource(factory)
    assert ds.membership_status == "failed"
    stale = await _doc(factory, OLD)
    assert stale.lifecycle == DocLifecycle.ACTIVE  # atomic: nothing half-retired


async def test_s6_exact_ne503_class_reproduction(db_engine, sync_factory, monkeypatch, healthy_report):
    """Acceptance: the exact #71 shape — rename + successor deletion + blackout.

    Ledger holds the stale path, its i18n twin and the (also deleted) successor;
    connector yields no changes (SHA short-circuit) and no windowed deletions.
    After one round all three are retired and out of the serving projection.
    """
    factory = get_session_factory(db_engine)
    await _seed(db_engine, {OLD: 1, OLD_I18N: 1, SUCCESSOR: 1, HEALTHY: 0})
    connector = _Connector(changes=[], deleted=[], members={HEALTHY})
    _register(connector)

    from backend.services.document_lifecycle import (
        active_generation_ordinals_async_session,
    )

    async with factory() as session:
        before = await active_generation_ordinals_async_session(session)
    assert before == [0, 1]  # stale generation still serving pre-reconciliation

    await sync_mod._sync_one(
        _cfg(),
        _Pipeline(sync_factory),
        factory,
        triggered_by="cron",
        builder=_StubBuilder(),
    )

    for sid in (OLD, OLD_I18N, SUCCESSOR):
        doc = await _doc(factory, sid)
        assert doc.lifecycle == DocLifecycle.DELETED, sid
    healthy = await _doc(factory, HEALTHY)
    assert healthy.lifecycle == DocLifecycle.ACTIVE

    async with factory() as session:
        after = await active_generation_ordinals_async_session(session)
    assert after == [0]  # stale provenance out of the serving projection

    log = await _latest_sync_log(factory)
    assert log.status == "success"
    assert log.delta_counts["stale_detected"] == 3
    assert log.delta_counts["stale_retired"] == 3


async def test_s7_repeated_rounds_converge(db_engine, sync_factory, monkeypatch, healthy_report):
    """Requirement 7: second round reports zero stale, states stable."""
    factory = get_session_factory(db_engine)
    await _seed(db_engine, {OLD: 0, HEALTHY: 0})
    connector = _Connector(members={HEALTHY})
    _register(connector)

    for _ in range(2):
        await sync_mod._sync_one(
            _cfg(),
            _Pipeline(sync_factory),
            factory,
            triggered_by="cron",
            builder=_StubBuilder(),
        )

    log = await _latest_sync_log(factory)
    assert log.status == "success"
    assert log.delta_counts["stale_detected"] == 0
    assert log.delta_counts["stale_retired"] == 0
    stale = await _doc(factory, OLD)
    assert stale.lifecycle == DocLifecycle.DELETED  # stable, not resurrected


async def test_s8_normal_round_counts_stale_documents_as_deleted(
    db_engine, sync_factory, monkeypatch, healthy_report
):
    """Requirement 13: stale retirements are document deletions, separately observable."""
    factory = get_session_factory(db_engine)
    await _seed(db_engine, {OLD: 0, HEALTHY: 0})
    connector = _Connector(changes=[_raw_doc(HEALTHY)], members={HEALTHY})
    _register(connector)

    await sync_mod._sync_one(
        _cfg(),
        _Pipeline(sync_factory),
        factory,
        triggered_by="cron",
        builder=_StubBuilder(new_docs=[HEALTHY]),
    )

    log = await _latest_sync_log(factory)
    assert log.items_deleted == 1
    assert log.delta_counts["stale_detected"] == 1
    assert log.delta_counts["stale_retired"] == 1
    assert log.delta_counts["retired_count"] == 1


async def test_s9_no_change_repair_path_no_longer_overloads_items_counters(
    db_engine, sync_factory, monkeypatch
):
    """Requirement 13: orphan-vector operations leave items_new/items_deleted alone."""
    factory = get_session_factory(db_engine)
    async with factory() as session:
        _mk_source(session)
        await session.commit()

    unhealthy = _Report(expected_chunks=5, actual_chunks=2, is_healthy=False)
    unhealthy.refill_source_ids = ["doc-missing"]
    unhealthy.missing_source_ids = ["doc-missing"]
    healthy_again = _Report()
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        sync_mod,
        "verify_source_vectors",
        AsyncMock(side_effect=[unhealthy, healthy_again]),
        raising=True,
    )
    builder = _StubBuilder()

    log_entry = SyncLog(source_id=SRC, source_type="github", status="success")
    connector = _Connector(members={HEALTHY})
    _register(connector)
    await sync_mod._handle_no_change(
        SRC,
        110,
        connector,
        _Pipeline(sync_factory),
        factory,
        log_entry,
        0.0,
        telemetry=None,
        builder=builder,
    )

    assert log_entry.items_new == 0
    assert log_entry.items_deleted == 0
    assert log_entry.delta_counts["ledger_rebuilt_count"] == 0
    assert log_entry.delta_counts["orphan_vectors_retired"] == 0
    assert log_entry.delta_counts["retired_count"] == 0  # documents, not vectors
