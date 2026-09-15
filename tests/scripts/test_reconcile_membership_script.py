"""#71 Production correction mechanism — `scripts/reconcile_membership.py`.

Frozen requirements 14-16:

- authorized, reviewable correction for the confirmed stale corpus using the
  SAME authoritative membership semantics as the sync-side reconciliation;
- dry-run / exact plan BEFORE any mutation (default = dry-run);
- the stale population is recomputed from authoritative truth at execution
  time — never hard-coded;
- apply retires via tombstone semantics only (no physical row deletion, no
  vector deletion in this mechanism — physical purge stays with GC).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import scripts.reconcile_membership as script
from backend.config import load_settings
from backend.db.models import DataSource, Document, DocumentVersion
from backend.db.session import get_engine, get_session_factory, init_db
from backend.services.document_lifecycle import DocLifecycle

pytestmark = pytest.mark.asyncio(loop_scope="session")

SRC = "wiki-documents-local"
STALE = f"{SRC}/main/docs/a/2-sdk-reference.md"
HEALTHY = f"{SRC}/main/docs/0-overview.md"


class _Connector:
    def __init__(self, members: set[str]) -> None:
        self._members = members

    def membership_source_ids(self) -> set[str]:
        return set(self._members)


@pytest.fixture
def sync_factory(db_engine):
    """同步账本面(与 pipeline._session_factory 同语义;schema 由 async 侧建)。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    dsn = os.environ.get("TEST_DATABASE_URL", load_settings().postgres_dsn)
    engine = create_engine(dsn.replace("+asyncpg", "+psycopg2"))
    try:
        yield sessionmaker(bind=engine)
    finally:
        engine.dispose()


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
            await session.execute(
                delete(Document).where(Document.source_id.like(f"{SRC}/%"))
            )
            await session.execute(
                delete(DocumentVersion).where(DocumentVersion.source_id.like(f"{SRC}/%"))
            )
            await session.execute(delete(DataSource).where(DataSource.id == SRC))
            await session.commit()
        await engine.dispose()


def _mk_source(session) -> None:
    session.add(DataSource(id=SRC, type="github", product="wiki", config={}))


def _mk_active_doc(session, source_id: str) -> None:
    doc = Document(
        source_id=source_id,
        source_type="github",
        product="wiki",
        title=source_id.rsplit("/", 1)[-1],
        url=f"https://example.com/{source_id}",
        branch="main",
        chunk_count=8,
        content_hash="h-" + source_id,
        lifecycle=DocLifecycle.ACTIVE,
    )
    session.add(doc)
    session.flush()
    version = DocumentVersion(
        source_id=source_id,
        version_seq=1,
        content_hash=doc.content_hash,
        metadata_hash="mh-" + source_id,
        generation_id="00000000-0000-0000-0000-000000000000",
        generation_ordinal=0,
        status="active",
        title=doc.title,
        url=doc.url,
        chunk_count=8,
    )
    session.add(version)
    doc.current_version_id = version.id


async def _seed(db_engine) -> None:
    factory = get_session_factory(db_engine)
    async with factory() as session:
        _mk_source(session)
        _mk_active_doc(session, STALE)
        _mk_active_doc(session, HEALTHY)
        await session.commit()


async def test_c1_dry_run_plan_is_exact_and_mutates_nothing(db_engine, sync_factory, capsys):
    await _seed(db_engine)

    plan = await script.build_plan(sync_factory, _Connector({HEALTHY}), SRC)

    assert plan["source_prefix"] == SRC
    assert plan["mode"] == "dry_run"
    assert [e["path"] for e in plan["entries"]] == [STALE]
    assert plan["entries"][0]["action"] == "RETIRE_STALE_DOCUMENT"
    assert plan["entries"][0]["chunk_count"] == 8
    assert plan["total_documents"] == 1
    # exact plan is JSON-serializable (reviewable artifact)
    payload = json.dumps(plan, ensure_ascii=False)
    assert STALE in payload

    factory = get_session_factory(db_engine)
    async with factory() as session:
        doc = (
            await session.execute(select(Document).where(Document.source_id == STALE))
        ).scalar_one()
        assert doc.lifecycle == DocLifecycle.ACTIVE  # dry-run mutated nothing


async def test_c2_apply_retires_via_tombstone_and_recomputes_population(
    db_engine, sync_factory, capsys
):
    """Requirement 16: population recomputed at execution time; tombstone only."""
    await _seed(db_engine)
    factory = get_session_factory(db_engine)
    connector = _Connector({HEALTHY})

    plan = await script.build_plan(sync_factory, connector, SRC)
    assert plan["total_documents"] == 1
    result = await script.apply_plan(
        factory, sync_factory, connector, SRC, reason="authorized-correction"
    )

    assert result["status"] == "completed"
    assert result["stale_retired"] == 1
    async with factory() as session:
        doc = (
            await session.execute(select(Document).where(Document.source_id == STALE))
        ).scalar_one()
        assert doc.lifecycle == DocLifecycle.DELETED  # logical delete, row retained
        healthy = (
            await session.execute(select(Document).where(Document.source_id == HEALTHY))
        ).scalar_one()
        assert healthy.lifecycle == DocLifecycle.ACTIVE

    # idempotent re-run: population recomputed → empty
    result2 = await script.apply_plan(
        factory, sync_factory, connector, SRC, reason="authorized-correction"
    )
    assert result2["stale_retired"] == 0
    assert result2["stale_detected"] == 0


async def test_c3_apply_persists_currency_truth(db_engine, sync_factory):
    await _seed(db_engine)
    factory = get_session_factory(db_engine)
    connector = _Connector({HEALTHY})

    await script.apply_plan(
        factory, sync_factory, connector, SRC, reason="authorized-correction"
    )

    async with factory() as session:
        ds = (
            await session.execute(select(DataSource).where(DataSource.id == SRC))
        ).scalar_one()
    assert ds.membership_status == "current"
    assert ds.membership_stale_retired == 1
