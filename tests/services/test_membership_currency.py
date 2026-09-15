"""#71 Authoritative membership reconciliation — service-level acceptance tests.

RED→GREEN contract (Issue #71 frozen requirements 1-8, 13, 16-17):

- stale_set = current ledger serving membership − authoritative membership;
- stale_set documents retire via ``tombstone_document`` (logical delete,
  existing lifecycle semantics — never physical row deletion);
- correctness MUST NOT depend on git event windows or ``fetch_deleted``;
- repeated reconciliation converges idempotently;
- unrelated healthy documents are never touched;
- persisted currency truth is written ONLY after reconciliation completes.

会话面:账本退休 = 同步 Session(与 sync.py fetch_deleted 墓碑块同面);
货币真值持久化 = 异步 Session(SyncLog/调度真值同面)。
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import delete

from backend.config import load_settings
from backend.db.models import DataSource, Document, DocumentVersion
from backend.db.session import get_engine, get_session_factory, init_db
from backend.services.document_lifecycle import DocLifecycle
from backend.services.membership_currency import (
    MEMBERSHIP_STATUS_CURRENT,
    MEMBERSHIP_STATUS_FAILED,
    MEMBERSHIP_STATUS_STALE,
    MEMBERSHIP_STATUS_UNSUPPORTED,
    ledger_active_membership,
    persist_membership_truth,
    reconcile_membership,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

SRC = "wiki-documents-local"

def _hash(sid: str) -> str:
    import hashlib
    return hashlib.sha256(sid.encode()).hexdigest()



# --------------------------------------------------------------------------- #
# fixtures / helpers
# --------------------------------------------------------------------------- #


class _StubMembershipConnector:
    """Minimal connector exposing only the authoritative membership face."""

    def __init__(self, members: set[str]) -> None:
        self._members = members
        self.enumerations = 0

    def membership_source_ids(self) -> set[str]:
        self.enumerations += 1
        return set(self._members)


class _RaisingMembershipConnector:
    def membership_source_ids(self) -> set[str]:
        raise RuntimeError("authoritative enumeration unavailable")


def _mk_source(session, source_id: str = SRC) -> DataSource:
    ds = DataSource(id=source_id, type="github", product="wiki", config={})
    session.add(ds)
    return ds


def _mk_active_doc(session, source_id: str, chunk_count: int = 3) -> Document:
    doc = Document(
        source_id=source_id,
        source_type="github",
        product="wiki",
        title=source_id.rsplit("/", 1)[-1],
        url=f"https://example.com/{source_id}.md",
        branch="main",
        chunk_count=chunk_count,
        content_hash=_hash(source_id),
        lifecycle=DocLifecycle.ACTIVE,
    )
    session.add(doc)
    session.flush()
    version = DocumentVersion(
        source_id=source_id,
        version_seq=1,
        content_hash=doc.content_hash,
        metadata_hash=_hash("m" + source_id),
        generation_id="00000000-0000-0000-0000-000000000000",
        generation_ordinal=0,
        status="active",
        title=doc.title,
        url=doc.url,
        chunk_count=chunk_count,
    )
    session.add(version)
    doc.current_version_id = version.id
    session.flush()
    return doc


@pytest_asyncio.fixture(loop_scope="session")
async def db_engine():
    """Per-test engine on the session loop(conftest 的 db_engine 绑定函数循环)."""
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
            await session.execute(
                delete(Document).where(Document.source_id.like(f"{SRC}/%"))
            )
            await session.execute(
                delete(DocumentVersion).where(DocumentVersion.source_id.like(f"{SRC}/%"))
            )
            await session.execute(delete(DataSource).where(DataSource.id == SRC))
            await session.commit()
        await engine.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def factory(db_engine):
    return get_session_factory(db_engine)


@pytest.fixture
def sync_factory(db_engine):
    """同步账本面(与 pipeline._session_factory 同语义;schema 由 async 侧建)。"""
    dsn = os.environ.get("TEST_DATABASE_URL", load_settings().postgres_dsn)
    engine = create_engine(dsn.replace("+asyncpg", "+psycopg2"))
    try:
        yield sessionmaker(bind=engine)
    finally:
        engine.dispose()


async def _seed(factory, docs: dict[str, str]) -> None:
    """docs: source_id → lifecycle;额外建立 DataSource 行。"""
    async with factory() as session:
        _mk_source(session)
        for sid, lifecycle_value in docs.items():
            doc = _mk_active_doc(session, sid)
            if lifecycle_value != DocLifecycle.ACTIVE:
                doc.lifecycle = lifecycle_value
        await session.commit()


async def _lifecycle_of(factory, source_id: str) -> str:
    async with factory() as session:
        doc = (
            await session.execute(
                select(Document).where(Document.source_id == source_id)
            )
        ).scalar_one()
        return doc.lifecycle


# --------------------------------------------------------------------------- #
# reconciliation semantics
# --------------------------------------------------------------------------- #


async def test_r1_upstream_delete_retires_stale_ledger_document(factory, sync_factory):
    """Requirement 4/5: stale_set = ledger serving − authoritative; tombstone only."""
    await _seed(factory, {f"{SRC}/main/keep.md": "active", f"{SRC}/main/deleted-upstream.md": "active"})

    connector = _StubMembershipConnector({f"{SRC}/main/keep.md"})
    result = reconcile_membership(sync_factory, connector, SRC, reason="test")

    assert result.status == "completed"
    assert result.stale_ids == (f"{SRC}/main/deleted-upstream.md",)
    assert result.retired == 1
    assert result.residual_ids == ()
    assert await _lifecycle_of(factory, f"{SRC}/main/deleted-upstream.md") == DocLifecycle.DELETED
    async with factory() as session:
        stale = (
            await session.execute(
                select(Document).where(Document.source_id == f"{SRC}/main/deleted-upstream.md")
            )
        ).scalar_one()
        assert stale.deleted_at is not None  # logical delete — row retained
    assert await _lifecycle_of(factory, f"{SRC}/main/keep.md") == DocLifecycle.ACTIVE


async def test_r2_rename_old_identity_retires_new_stays(factory, sync_factory):
    """Requirement 17 (minimum): old identity retires, new identity is member."""
    await _seed(factory, {f"{SRC}/main/old-path/sdk.md": "active", f"{SRC}/main/new-path/sdk.md": "active"})

    connector = _StubMembershipConnector({f"{SRC}/main/new-path/sdk.md"})
    result = reconcile_membership(sync_factory, connector, SRC, reason="rename")

    assert result.stale_ids == (f"{SRC}/main/old-path/sdk.md",)
    assert result.retired == 1
    assert await _lifecycle_of(factory, f"{SRC}/main/old-path/sdk.md") == DocLifecycle.DELETED
    assert await _lifecycle_of(factory, f"{SRC}/main/new-path/sdk.md") == DocLifecycle.ACTIVE


async def test_r3_repeated_reconciliation_converges_idempotently(factory, sync_factory):
    """Requirement 7: second run observes empty stale set and stays stable."""
    await _seed(factory, {f"{SRC}/main/ghost.md": "active"})

    connector = _StubMembershipConnector(set())
    first = reconcile_membership(sync_factory, connector, SRC, reason="round-1")
    assert first.stale_ids == (f"{SRC}/main/ghost.md",)
    assert first.retired == 1

    second = reconcile_membership(sync_factory, connector, SRC, reason="round-2")
    assert second.stale_ids == ()
    assert second.retired == 0
    assert second.status == "completed"
    assert connector.enumerations == 2  # authoritative truth re-derived each round


async def test_r4_missing_candidate_counts_as_current_ledger_membership(factory, sync_factory):
    """Serving set includes missing_candidate (grace); it is part of stale_set."""
    await _seed(factory, {f"{SRC}/main/vanished.md": DocLifecycle.MISSING_CANDIDATE})

    connector = _StubMembershipConnector(set())
    result = reconcile_membership(sync_factory, connector, SRC, reason="grace-expired")
    assert result.stale_ids == (f"{SRC}/main/vanished.md",)
    assert result.retired == 1


async def test_r5_superseded_and_deleted_are_not_stale_candidates(factory, sync_factory):
    """Only current serving truth participates; historical rows stay auditable."""
    await _seed(
        factory,
        {
            f"{SRC}/main/superseded.md": DocLifecycle.SUPERSEDED,
            f"{SRC}/main/already-deleted.md": DocLifecycle.DELETED,
        },
    )

    connector = _StubMembershipConnector(set())
    result = reconcile_membership(sync_factory, connector, SRC, reason="scope")
    assert result.stale_ids == ()
    assert result.retired == 0


async def test_r6_enumeration_failure_propagates_and_mutates_nothing(factory, sync_factory):
    """Requirement 8: authority unavailable → no retirement, no truth advance."""
    await _seed(factory, {f"{SRC}/main/ghost.md": "active"})

    connector = _RaisingMembershipConnector()
    with pytest.raises(RuntimeError, match="authoritative enumeration unavailable"):
        reconcile_membership(sync_factory, connector, SRC, reason="test")

    assert await _lifecycle_of(factory, f"{SRC}/main/ghost.md") == DocLifecycle.ACTIVE


async def test_r7_ledger_active_membership_queries_serving_set(factory, sync_factory):
    await _seed(
        factory,
        {
            f"{SRC}/main/a.md": "active",
            f"{SRC}/main/b.md": DocLifecycle.SUPERSEDED,
        },
    )
    with sync_factory() as session:
        members = ledger_active_membership(session, SRC)
    assert members == {f"{SRC}/main/a.md"}


# --------------------------------------------------------------------------- #
# persisted currency truth
# --------------------------------------------------------------------------- #


async def test_r8_persist_membership_truth_current(factory):
    async with factory() as session:
        _mk_source(session)
        await session.commit()

    checked = datetime.now(UTC)
    await persist_membership_truth(
        factory,
        SRC,
        status=MEMBERSHIP_STATUS_CURRENT,
        stale_detected=0,
        stale_retired=0,
        checked_at=checked,
    )
    async with factory() as session:
        ds = (await session.execute(select(DataSource).where(DataSource.id == SRC))).scalar_one()
    assert ds.membership_status == MEMBERSHIP_STATUS_CURRENT
    assert ds.membership_stale_detected == 0
    assert ds.membership_stale_retired == 0
    assert ds.membership_checked_at is not None


async def test_r9_persist_membership_truth_stale_carries_unresolved_drift(factory):
    async with factory() as session:
        _mk_source(session)
        await session.commit()

    await persist_membership_truth(
        factory,
        SRC,
        status=MEMBERSHIP_STATUS_STALE,
        stale_detected=5,
        stale_retired=2,
        detail={"residual": [f"{SRC}/main/x.md"]},
    )
    async with factory() as session:
        ds = (await session.execute(select(DataSource).where(DataSource.id == SRC))).scalar_one()
    assert ds.membership_status == MEMBERSHIP_STATUS_STALE
    assert ds.membership_stale_detected == 5
    assert ds.membership_stale_retired == 2
    assert ds.membership_detail["residual"] == [f"{SRC}/main/x.md"]


async def test_r10_persist_membership_truth_failed_and_unsupported(factory):
    async with factory() as session:
        _mk_source(session)
        await session.commit()

    await persist_membership_truth(factory, SRC, status=MEMBERSHIP_STATUS_FAILED)
    await persist_membership_truth(factory, SRC, status=MEMBERSHIP_STATUS_UNSUPPORTED)
    async with factory() as session:
        ds = (await session.execute(select(DataSource).where(DataSource.id == SRC))).scalar_one()
    assert ds.membership_status == MEMBERSHIP_STATUS_UNSUPPORTED


async def test_r11_missing_source_row_is_an_explicit_truth_failure(factory):
    """R2 BLOCKER 2: truth establishment failure is NEVER silent (row missing)."""
    from backend.services.membership_currency import MembershipTruthPersistenceError

    with pytest.raises(MembershipTruthPersistenceError, match="source row missing"):
        await persist_membership_truth(
            factory, "vanished-source-r11", status=MEMBERSHIP_STATUS_CURRENT
        )


async def test_r12_status_vocabulary_is_frozen():
    """Guards the Admin/UI contract: exactly four persisted states."""
    assert {
        MEMBERSHIP_STATUS_CURRENT,
        MEMBERSHIP_STATUS_STALE,
        MEMBERSHIP_STATUS_FAILED,
        MEMBERSHIP_STATUS_UNSUPPORTED,
    } == {"current", "stale", "failed", "unsupported"}
