"""Issue #174: source deletion must remove every rebuildable content copy."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from backend.db.models import (
    DataSource,
    Document,
    DocumentVersion,
    DocumentVersionChunk,
    IndexGeneration,
)
from backend.main import app
from backend.services.source_deletion import process_pending_deletions
from backend.services.source_lifecycle import DELETE_FAILED

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _clear_source(source_id: str) -> None:
    factory = app.state.session_factory
    async with factory() as session:
        version_ids = list(
            (
                await session.execute(
                    select(DocumentVersion.id).where(
                        DocumentVersion.source_id.startswith(f"{source_id}/", autoescape=True)
                    )
                )
            ).scalars()
        )
        if version_ids:
            await session.execute(
                DocumentVersionChunk.__table__.delete().where(
                    DocumentVersionChunk.version_id.in_(version_ids)
                )
            )
        await session.execute(
            DocumentVersion.__table__.delete().where(
                DocumentVersion.source_id.startswith(f"{source_id}/", autoescape=True)
            )
        )
        await session.execute(
            Document.__table__.delete().where(
                Document.source_id.startswith(f"{source_id}/", autoescape=True)
            )
        )
        await session.execute(
            IndexGeneration.__table__.delete().where(IndexGeneration.source_id == source_id)
        )
        await session.execute(DataSource.__table__.delete().where(DataSource.id == source_id))
        await session.commit()


async def _seed_upload_source(source_id: str, upload_root: Path) -> None:
    current_generation = IndexGeneration(
        id=uuid.uuid4(),
        ordinal=2_000_000 + int(source_id[-6:], 16),
        source_id=source_id,
        status="ready",
        doc_count=1,
        chunk_count=1,
        ready_at=datetime.now(UTC),
        activated_at=datetime.now(UTC),
    )
    old_generation = IndexGeneration(
        id=uuid.uuid4(),
        ordinal=3_000_000 + int(source_id[-6:], 16),
        source_id=source_id,
        status="ready",
        doc_count=1,
        chunk_count=2,
        ready_at=datetime.now(UTC),
    )
    current_version = DocumentVersion(
        id=uuid.uuid4(),
        source_id=f"{source_id}/current.md",
        version_seq=1,
        content_hash="a" * 64,
        metadata_hash="b" * 64,
        generation_id=current_generation.id,
        generation_ordinal=current_generation.ordinal,
        status="active",
        title="current",
        url="upload://current.md",
        chunk_count=1,
    )
    ghost_version = DocumentVersion(
        id=uuid.uuid4(),
        source_id=f"{source_id}/ghost.md",
        version_seq=1,
        content_hash="c" * 64,
        metadata_hash="d" * 64,
        generation_id=old_generation.id,
        generation_ordinal=old_generation.ordinal,
        status="superseded",
        title="ghost",
        url="upload://ghost.md",
        chunk_count=2,
    )
    factory = app.state.session_factory
    async with factory() as session:
        session.add_all(
            [
                DataSource(
                    id=source_id,
                    type="filesystem",
                    product="issue174",
                    enabled=True,
                    config={
                        "upload_mode": True,
                        "root_path": str(upload_root / source_id),
                    },
                    sync_interval="24h",
                    lifecycle_state="delete_requested",
                ),
                current_generation,
                old_generation,
                current_version,
                ghost_version,
                Document(
                    source_id=current_version.source_id,
                    content_hash=current_version.content_hash,
                    source_type="filesystem",
                    product="issue174",
                    title="current",
                    url="upload://current.md",
                    metadata_={},
                    branch="",
                    chunk_count=1,
                    current_version_id=current_version.id,
                ),
                DocumentVersionChunk(
                    version_id=current_version.id,
                    chunk_index=0,
                    text="current customer body",
                    props={"source_id": current_version.source_id},
                ),
                DocumentVersionChunk(
                    version_id=ghost_version.id,
                    chunk_index=0,
                    text="ghost customer body one",
                    props={"source_id": ghost_version.source_id},
                ),
                DocumentVersionChunk(
                    version_id=ghost_version.id,
                    chunk_index=1,
                    text="ghost customer body two",
                    props={"source_id": ghost_version.source_id},
                ),
            ]
        )
        await session.commit()


async def _content_counts(source_id: str) -> dict[str, int]:
    factory = app.state.session_factory
    async with factory() as session:
        version_ids = select(DocumentVersion.id).where(
            DocumentVersion.source_id.startswith(f"{source_id}/", autoescape=True)
        )
        return {
            "sources": int(
                (
                    await session.execute(
                        select(func.count()).select_from(DataSource).where(DataSource.id == source_id)
                    )
                ).scalar_one()
            ),
            "documents": int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(Document)
                        .where(Document.source_id.startswith(f"{source_id}/", autoescape=True))
                    )
                ).scalar_one()
            ),
            "versions": int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(DocumentVersion)
                        .where(
                            DocumentVersion.source_id.startswith(
                                f"{source_id}/", autoescape=True
                            )
                        )
                    )
                ).scalar_one()
            ),
            "chunks": int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(DocumentVersionChunk)
                        .where(DocumentVersionChunk.version_id.in_(version_ids))
                    )
                ).scalar_one()
            ),
            "generations": int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(IndexGeneration)
                        .where(IndexGeneration.source_id == source_id)
                    )
                ).scalar_one()
            ),
        }


async def _run_one(source_id: str) -> list[str]:
    settings = app.state.settings
    return await process_pending_deletions(
        app.state.session_factory,
        settings.weaviate_url,
        settings.weaviate_class_name,
        source_ids=[source_id],
    )


async def test_delete_upload_source_removes_all_rebuildable_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches the old worker deleting only DataSource + current Document rows."""
    source_id = f"i174-{uuid.uuid4().hex[:6]}"
    upload_root = tmp_path / "data-sources"
    source_dir = upload_root / source_id
    source_dir.mkdir(parents=True)
    (source_dir / "original.md").write_text("original customer body", encoding="utf-8")
    await _clear_source(source_id)
    await _seed_upload_source(source_id, upload_root)
    monkeypatch.setattr(
        "backend.services.source_deletion.UPLOADS_CORPUS_ROOT", upload_root, raising=False
    )
    monkeypatch.setattr(
        "backend.services.source_deletion.purge_source_corpus_sync",
        lambda *args, **kwargs: {"ledger_docs": 1, "orphans": 0, "residue": 0},
    )
    try:
        assert await _run_one(source_id) == [source_id]
        assert await _content_counts(source_id) == {
            "sources": 0,
            "documents": 0,
            "versions": 0,
            "chunks": 0,
            "generations": 0,
        }
        assert not source_dir.exists()
    finally:
        await _clear_source(source_id)


async def test_upload_root_identity_mismatch_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches trusting config.root_path or silently skipping an unsafe upload tree."""
    source_id = f"i174-{uuid.uuid4().hex[:6]}"
    upload_root = tmp_path / "data-sources"
    source_dir = upload_root / source_id
    sibling_dir = upload_root / f"{source_id}-sibling"
    source_dir.mkdir(parents=True)
    sibling_dir.mkdir()
    (source_dir / "own.md").write_text("own", encoding="utf-8")
    (sibling_dir / "keep.md").write_text("keep", encoding="utf-8")
    await _clear_source(source_id)
    await _seed_upload_source(source_id, upload_root)
    factory = app.state.session_factory
    async with factory() as session:
        ds = await session.get(DataSource, source_id)
        assert ds is not None
        ds.config = {"upload_mode": True, "root_path": str(sibling_dir)}
        await session.commit()
    monkeypatch.setattr(
        "backend.services.source_deletion.UPLOADS_CORPUS_ROOT", upload_root, raising=False
    )
    monkeypatch.setattr(
        "backend.services.source_deletion.purge_source_corpus_sync",
        lambda *args, **kwargs: {"ledger_docs": 1, "orphans": 0, "residue": 0},
    )
    try:
        assert await _run_one(source_id) == [source_id]
        counts = await _content_counts(source_id)
        assert counts["sources"] == 1
        async with factory() as session:
            ds = await session.get(DataSource, source_id)
            assert ds is not None
            assert ds.lifecycle_state == "delete_failed"
            assert "root_path" in (ds.lifecycle_error or "")
        assert (source_dir / "own.md").read_text(encoding="utf-8") == "own"
        assert (sibling_dir / "keep.md").read_text(encoding="utf-8") == "keep"
    finally:
        await _clear_source(source_id)


async def test_final_database_commit_failure_preserves_retry_anchor_and_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches reporting success when the final all-or-nothing DB commit fails."""
    source_id = f"i174-{uuid.uuid4().hex[:6]}"
    upload_root = tmp_path / "data-sources"
    source_dir = upload_root / source_id
    source_dir.mkdir(parents=True)
    (source_dir / "original.md").write_text("original", encoding="utf-8")
    await _clear_source(source_id)
    await _seed_upload_source(source_id, upload_root)

    async def _fail_final_commit(session) -> None:
        raise RuntimeError("simulated final DB commit failure")

    monkeypatch.setattr(
        "backend.services.source_deletion.UPLOADS_CORPUS_ROOT", upload_root, raising=False
    )
    monkeypatch.setattr(
        "backend.services.source_deletion.purge_source_corpus_sync",
        lambda *args, **kwargs: {"ledger_docs": 1, "orphans": 0, "residue": 0},
    )
    monkeypatch.setattr(
        "backend.services.source_deletion._commit_final_deletion",
        _fail_final_commit,
        raising=False,
    )
    try:
        assert await _run_one(source_id) == [source_id]
        counts = await _content_counts(source_id)
        assert counts == {
            "sources": 1,
            "documents": 1,
            "versions": 2,
            "chunks": 3,
            "generations": 2,
        }
        factory = app.state.session_factory
        async with factory() as session:
            ds = await session.get(DataSource, source_id)
            assert ds is not None
            assert ds.lifecycle_state == "delete_failed"
            assert "simulated final DB commit failure" in (ds.lifecycle_error or "")
    finally:
        await _clear_source(source_id)


async def test_ghost_source_with_zero_documents_still_converges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """0 当前 Document 但 Version/Chunk/generation 仍在的 ghost 来源不能被跳过。"""
    source_id = f"i174-{uuid.uuid4().hex[:6]}"
    upload_root = tmp_path / "data-sources"
    source_dir = upload_root / source_id
    source_dir.mkdir(parents=True)
    (source_dir / "orphan.md").write_text("ghost body", encoding="utf-8")
    await _clear_source(source_id)
    await _seed_upload_source(source_id, upload_root)
    factory = app.state.session_factory
    async with factory() as session:
        await session.execute(
            Document.__table__.delete().where(
                Document.source_id.startswith(f"{source_id}/", autoescape=True)
            )
        )
        await session.commit()
    assert (await _content_counts(source_id))["documents"] == 0
    monkeypatch.setattr(
        "backend.services.source_deletion.UPLOADS_CORPUS_ROOT", upload_root, raising=False
    )
    monkeypatch.setattr(
        "backend.services.source_deletion.purge_source_corpus_sync",
        lambda *args, **kwargs: {"ledger_docs": 0, "orphans": 0, "residue": 0},
    )
    try:
        assert await _run_one(source_id) == [source_id]
        assert await _content_counts(source_id) == {
            "sources": 0,
            "documents": 0,
            "versions": 0,
            "chunks": 0,
            "generations": 0,
        }
        assert not source_dir.exists()
    finally:
        await _clear_source(source_id)


async def test_cross_source_generation_identity_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """版本指向他源 generation 时必须整体失败,绝不能跨源删除。"""
    source_id = f"i174-{uuid.uuid4().hex[:6]}"
    other_id = f"i174-{uuid.uuid4().hex[:6]}"
    upload_root = tmp_path / "data-sources"
    source_dir = upload_root / source_id
    source_dir.mkdir(parents=True)
    (source_dir / "own.md").write_text("own body", encoding="utf-8")
    await _clear_source(source_id)
    await _clear_source(other_id)
    await _seed_upload_source(source_id, upload_root)
    foreign_generation = IndexGeneration(
        id=uuid.uuid4(),
        ordinal=4_000_000 + int(other_id[-6:], 16),
        source_id=other_id,
        status="ready",
        doc_count=1,
        chunk_count=1,
        ready_at=datetime.now(UTC),
    )
    factory = app.state.session_factory
    async with factory() as session:
        session.add(foreign_generation)
        version = (
            await session.execute(
                select(DocumentVersion).where(
                    DocumentVersion.source_id == f"{source_id}/current.md"
                )
            )
        ).scalar_one()
        version.generation_id = foreign_generation.id
        version.generation_ordinal = foreign_generation.ordinal
        await session.commit()

    def _must_not_purge(*args, **kwargs) -> dict[str, int]:
        raise AssertionError("purge must not run before identity guards pass")

    monkeypatch.setattr(
        "backend.services.source_deletion.purge_source_corpus_sync", _must_not_purge
    )
    try:
        assert await _run_one(source_id) == [source_id]
        counts = await _content_counts(source_id)
        assert counts == {
            "sources": 1,
            "documents": 1,
            "versions": 2,
            "chunks": 3,
            "generations": 2,
        }
        factory = app.state.session_factory
        async with factory() as session:
            ds = await session.get(DataSource, source_id)
            assert ds is not None
            assert ds.lifecycle_state == "delete_failed"
            assert "generation identity" in (ds.lifecycle_error or "")
            other_generation = await session.get(IndexGeneration, foreign_generation.id)
            assert other_generation is not None
            assert other_generation.source_id == other_id
        assert (source_dir / "own.md").read_text(encoding="utf-8") == "own body"
    finally:
        await _clear_source(source_id)
        await _clear_source(other_id)


async def test_upload_is_rejected_after_delete_acceptance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches an upload recreating files after DELETE_REQUESTED was persisted."""
    from backend.api.admin import data_sources as api

    source_id = f"i174-{uuid.uuid4().hex[:6]}"
    upload_root = tmp_path / "data-sources"
    upload_root.mkdir()
    await _clear_source(source_id)
    factory = app.state.session_factory
    async with factory() as session:
        session.add(
            DataSource(
                id=source_id,
                type="filesystem",
                product="issue174",
                enabled=True,
                config={
                    "upload_mode": True,
                    "root_path": str(upload_root / source_id),
                },
                sync_interval="24h",
                lifecycle_state="delete_requested",
            )
        )
        await session.commit()

    class _File:
        filename = "late.md"
        size = 4

        async def read(self) -> bytes:
            return b"late"

    monkeypatch.setattr(api, "UPLOADS_CORPUS_ROOT", upload_root)
    try:
        with pytest.raises(HTTPException) as caught:
            await api.upload_source_files(
                source_id,
                None,
                SimpleNamespace(app=app),
                [_File()],
                ["late.md"],
            )
        assert caught.value.status_code == 409
        assert not (upload_root / source_id / "late.md").exists()
    finally:
        await _clear_source(source_id)


async def test_upload_permission_failure_is_retryable_and_second_sweep_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A partial first attempt retains the anchor; retry converges every layer."""
    from backend.services import source_deletion as deletion
    from backend.services.upload_storage import remove_owned_upload_tree as real_remove

    source_id = f"i174-{uuid.uuid4().hex[:6]}"
    upload_root = tmp_path / "data-sources"
    source_dir = upload_root / source_id
    source_dir.mkdir(parents=True)
    (source_dir / "blocked.md").write_text("blocked", encoding="utf-8")
    await _clear_source(source_id)
    await _seed_upload_source(source_id, upload_root)
    calls = 0

    def _fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise PermissionError("simulated upload permission denial")
        return real_remove(*args, **kwargs)

    monkeypatch.setattr(deletion, "UPLOADS_CORPUS_ROOT", upload_root)
    monkeypatch.setattr(deletion, "remove_owned_upload_tree", _fail_once)
    monkeypatch.setattr(
        deletion,
        "purge_source_corpus_sync",
        lambda *args, **kwargs: {"ledger_docs": 1, "orphans": 0, "residue": 0},
    )
    try:
        assert await _run_one(source_id) == [source_id]
        first = await _content_counts(source_id)
        assert first == {
            "sources": 1,
            "documents": 1,
            "versions": 2,
            "chunks": 3,
            "generations": 2,
        }
        factory = app.state.session_factory
        async with factory() as session:
            ds = await session.get(DataSource, source_id)
            assert ds is not None
            assert ds.lifecycle_state == "delete_failed"
            assert "permission denial" in (ds.lifecycle_error or "")

        from backend.services.source_deletion import request_deletion

        async with factory() as session:
            retried = await request_deletion(
                session, source_id, allowed_from=frozenset({DELETE_FAILED})
            )
        assert retried.accepted is True
        assert await _run_one(source_id) == [source_id]
        assert await _content_counts(source_id) == {
            "sources": 0,
            "documents": 0,
            "versions": 0,
            "chunks": 0,
            "generations": 0,
        }
        assert not source_dir.exists()
    finally:
        await _clear_source(source_id)


async def test_upload_holds_source_lock_until_file_write_finishes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An upload already writing finishes before DELETE can become accepted."""
    from backend.api.admin import data_sources as api
    from backend.services.source_deletion import request_deletion
    from backend.services.source_lifecycle import ACTIVE

    source_id = f"i174-{uuid.uuid4().hex[:6]}"
    upload_root = tmp_path / "data-sources"
    upload_root.mkdir()
    await _clear_source(source_id)
    factory = app.state.session_factory
    async with factory() as session:
        session.add(
            DataSource(
                id=source_id,
                type="filesystem",
                product="issue174",
                enabled=True,
                config={"upload_mode": True, "root_path": str(upload_root / source_id)},
                sync_interval="24h",
            )
        )
        await session.commit()

    read_started = asyncio.Event()
    allow_read = asyncio.Event()

    class _SlowFile:
        filename = "first.md"
        size = 5

        async def read(self) -> bytes:
            read_started.set()
            await allow_read.wait()
            return b"first"

    monkeypatch.setattr(api, "UPLOADS_CORPUS_ROOT", upload_root)
    upload_task = asyncio.create_task(
        api.upload_source_files(
            source_id,
            None,
            SimpleNamespace(app=app),
            [_SlowFile()],
            ["first.md"],
        )
    )
    await asyncio.wait_for(read_started.wait(), timeout=1)

    async def _accept_delete():
        async with factory() as session:
            return await request_deletion(
                session, source_id, allowed_from=frozenset({ACTIVE})
            )

    delete_task = asyncio.create_task(_accept_delete())
    await asyncio.sleep(0.05)
    try:
        assert not delete_task.done(), "DELETE bypassed the upload's source-row lock"
        allow_read.set()
        upload_result = await asyncio.wait_for(upload_task, timeout=1)
        accepted = await asyncio.wait_for(delete_task, timeout=1)
        assert upload_result["saved"] == 1
        assert accepted.accepted is True
        assert (upload_root / source_id / "first.md").read_bytes() == b"first"
    finally:
        allow_read.set()
        if not upload_task.done():
            await upload_task
        if not delete_task.done():
            await delete_task
        await _clear_source(source_id)
