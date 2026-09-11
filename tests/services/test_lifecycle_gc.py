"""P1 生命周期 GC 地基门测试(资格时序 / 墓碑默认关闭 / dry-run 默认 / P0-A)。

契约锚点:
- Freeze §8a:RETIRED 生成代 retired + 7 天后可自动物理 GC;被接替文档
  superseded + 7 天;墓碑文档 deleted + ``tombstone_days`` —— **不设隐式
  默认**(None = 墓碑物理 GC 关闭;已废除的 30 天默认禁止回用);
- P0-A:物理删除只按版本自身命名空间的确定性 UUID 点删,禁止 TEXT 属性
  过滤删除;
- dry-run 默认;``apply=True`` 才落删除;删除动作全部入 GCReport。
"""

import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.db.models import (
    Base,
    Document,
    DocumentVersion,
    DocumentVersionChunk,
    IndexGeneration,
)
from backend.pipeline.ingest import chunk_uuids_for_version
from backend.services import document_lifecycle as lifecycle
from backend.services.lifecycle_gc import sweep

TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test",
)

SRC = "p1gc-probe"
# GC 探针代专用高位 ordinal(全局唯一约束;与 builder 等套件分配域隔离)
PROBE_ORDINAL = 918273  # 第二枚探针代用 PROBE_ORDINAL+1(ordinal 全局唯一)


@pytest_asyncio.fixture()
async def env():
    sync_engine = create_engine(TEST_DSN.replace("+asyncpg", "+psycopg2"))
    Base.metadata.create_all(sync_engine)
    sync_factory = sessionmaker(sync_engine, expire_on_commit=False)
    async_engine = create_async_engine(TEST_DSN)
    async_sf = async_sessionmaker(async_engine, expire_on_commit=False)

    with sync_factory() as s:
        _purge(s)

    collection = MagicMock()
    pipeline = SimpleNamespace(_collection=collection, _session_factory=sync_factory)
    yield SimpleNamespace(
        sync_factory=sync_factory,
        async_factory=async_sf,
        collection=collection,
        pipeline=pipeline,
    )
    with sync_factory() as s:
        _purge(s)
    sync_engine.dispose()
    await async_engine.dispose()


def _purge(s) -> None:
    for row in s.execute(
        select(Document).where(Document.source_id.like(f"{SRC}%"))
    ).scalars():
        s.delete(row)
    for row in s.execute(
        select(DocumentVersion).where(DocumentVersion.source_id.like(f"{SRC}%"))
    ).scalars():
        s.delete(row)
    for row in s.execute(
        select(DocumentVersionChunk).where(
            DocumentVersionChunk.version_id.in_(
                select(DocumentVersion.id).where(DocumentVersion.source_id.like(f"{SRC}%"))
            )
        )
    ).scalars():
        s.delete(row)
    for row in s.execute(
        select(IndexGeneration).where(
            (IndexGeneration.source_id == SRC) | (IndexGeneration.ordinal == PROBE_ORDINAL)
        )
    ).scalars():
        s.delete(row)
    s.commit()


def _seed_retired_generation(s, *, gc_eligible_at: datetime, ordinal: int | None = None) -> IndexGeneration:
    gen = IndexGeneration(
        ordinal=ordinal or PROBE_ORDINAL,
        source_id=SRC,
        status=lifecycle.GenerationStatus.RETIRED,
        withdrawn_at=gc_eligible_at - timedelta(days=7),
        retired_at=gc_eligible_at - timedelta(days=7),
        gc_eligible_at=gc_eligible_at,
    )
    s.add(gen)
    s.flush()
    return gen


def _seed_doc_with_version(
    s,
    sid: str,
    *,
    gen: IndexGeneration | None,
    chunks: int = 2,
    lifecycle_state: str = "active",
    superseded_at: datetime | None = None,
    deleted_at: datetime | None = None,
) -> tuple[Document, DocumentVersion]:
    doc = Document(
        source_id=sid,
        content_hash=f"h-{sid}",
        source_type="github",
        product="probe",
        title=sid,
        url=f"https://x/{sid}",
        metadata_={},
        branch="",
        chunk_count=chunks,
        lifecycle=lifecycle_state,
        superseded_at=superseded_at,
        deleted_at=deleted_at,
    )
    s.add(doc)
    s.flush()
    version = DocumentVersion(
        source_id=sid,
        version_seq=1,
        content_hash=doc.content_hash,
        metadata_hash="m",
        generation_id=gen.id if gen else lifecycle.LEGACY_GENERATION_ID,
        generation_ordinal=gen.ordinal if gen else lifecycle.LEGACY_GENERATION_ORDINAL,
        status="superseded" if lifecycle_state == "superseded" else "active",
        title=sid,
        url=doc.url,
        chunk_count=chunks,
    )
    s.add(version)
    s.flush()
    for i in range(chunks):
        s.add(
            DocumentVersionChunk(
                version_id=version.id,
                chunk_index=i,
                text=f"text-{sid}-{i}",
                props={"source_id": sid, "chunk_index": i},
            )
        )
    doc.current_version_id = version.id
    s.flush()
    return doc, version


# --------------------------------------------------------------------------- #
# 资格时序
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_retired_generation_gc_eligible_only_after_7d(env):
    """RETIRED 代:gc_eligible_at 未到不进资格;已到(或更早)进资格。"""
    now = datetime.now(UTC)
    with env.sync_factory() as s:
        not_yet = _seed_retired_generation(s, gc_eligible_at=now + timedelta(days=1))
        due = _seed_retired_generation(
            s, gc_eligible_at=now - timedelta(hours=1), ordinal=PROBE_ORDINAL + 1
        )
        s.commit()
    due_id = str(due.id)
    not_yet_id = str(not_yet.id)

    report = await sweep(env.async_factory, env.pipeline, now=now)
    assert due_id in report.generations_eligible
    assert not_yet_id not in report.generations_eligible
    # dry-run 默认:零物理删除
    assert report.dry_run is True
    assert report.objects_deleted == 0
    env.collection.data.delete_many.assert_not_called()


@pytest.mark.asyncio
async def test_superseded_doc_eligible_at_7d_and_tombstone_disabled_by_default(env):
    """被接替文档 7 天资格;墓碑窗默认关闭(tombstone_days=None 不产生资格)。"""
    now = datetime.now(UTC)
    with env.sync_factory() as s:
        _seed_doc_with_version(
            s,
            f"{SRC}/sup-old",
            gen=None,
            lifecycle_state="superseded",
            superseded_at=now - timedelta(days=8),
        )
        _seed_doc_with_version(
            s,
            f"{SRC}/sup-new",
            gen=None,
            lifecycle_state="superseded",
            superseded_at=now - timedelta(days=1),
        )
        _seed_doc_with_version(
            s,
            f"{SRC}/tomb-old",
            gen=None,
            lifecycle_state="deleted",
            deleted_at=now - timedelta(days=30),
        )
        s.commit()

    report = await sweep(env.async_factory, env.pipeline, now=now)
    assert f"{SRC}/sup-old" in report.documents_eligible
    assert f"{SRC}/sup-new" not in report.documents_eligible
    # 墓碑窗无隐式默认:deleted 不因时间自动进入物理 GC 资格(30 天默认已废除)
    assert f"{SRC}/tomb-old" not in report.documents_eligible

    # 显式配置后墓碑才有资格;且仅超窗者入选
    report2 = await sweep(env.async_factory, env.pipeline, now=now, tombstone_days=7)
    assert f"{SRC}/tomb-old" in report2.documents_eligible


# --------------------------------------------------------------------------- #
# apply:精确 UUID 点删(P0-A)+ 账本清理 + 审计账本
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_apply_purges_due_generation_via_exact_uuids(env):
    """apply:到期 RETIRED 代 → 按版本命名空间确定性 UUID 点删对象 +
    chunk 副本删除 + purged_at 盖章;版本元数据行保留作审计。"""
    now = datetime.now(UTC)
    with env.sync_factory() as s:
        gen = _seed_retired_generation(s, gc_eligible_at=now - timedelta(hours=1))
        gen_id = gen.id
        _, version = _seed_doc_with_version(s, f"{SRC}/genver", gen=gen, chunks=2)
        s.commit()
        version_id = version.id
        ordinal = version.generation_ordinal

    report = await sweep(env.async_factory, env.pipeline, now=now, apply=True)
    assert report.dry_run is False
    assert str(gen_id) in report.generations_eligible
    assert report.objects_deleted == 2
    assert report.chunk_rows_deleted == 2
    # P0-A:全部删除经 by_id contains_any(确定性 UUID),无 TEXT 属性过滤
    calls = env.collection.data.delete_many.call_args_list
    assert calls, "apply 必须产生对象删除"
    expected_uuids = set(chunk_uuids_for_version(f"{SRC}/genver", str(gen_id), ordinal, 2))
    got = {str(v) for c in calls for v in c.kwargs["where"].value}
    assert got == expected_uuids

    with env.sync_factory() as s:
        chunks = s.execute(
            select(DocumentVersionChunk).where(
                DocumentVersionChunk.version_id == version_id
            )
        ).scalars().all()
        assert chunks == []  # 持久副本已清
        versions = s.execute(
            select(DocumentVersion).where(DocumentVersion.id == version_id)
        ).scalars().all()
        assert len(versions) == 1  # 版本元数据行保留(链可回放)
        gen_row = s.execute(
            select(IndexGeneration).where(IndexGeneration.id == gen_id)
        ).scalar_one()
        assert gen_row.purged_at is not None
    # 幂等:purged 盖章后不再进资格
    report2 = await sweep(env.async_factory, env.pipeline, now=now, apply=True)
    assert str(gen_id) not in report2.generations_eligible


@pytest.mark.asyncio
async def test_apply_purges_doomed_document_rows_and_objects(env):
    """apply:超窗被接替文档 → 对象+版本+chunk+文档行全清;审计计数一致。"""
    now = datetime.now(UTC)
    with env.sync_factory() as s:
        _, version = _seed_doc_with_version(
            s,
            f"{SRC}/doomed",
            gen=None,
            chunks=1,
            lifecycle_state="superseded",
            superseded_at=now - timedelta(days=9),
        )
        s.commit()
        version_id = version.id
        ordinal = version.generation_ordinal

    report = await sweep(env.async_factory, env.pipeline, now=now, apply=True)
    assert f"{SRC}/doomed" in report.documents_eligible
    assert report.documents_deleted == 1
    assert report.versions_deleted == 1
    assert report.chunk_rows_deleted == 1

    expected_uuids = set(
        chunk_uuids_for_version(
            f"{SRC}/doomed", str(lifecycle.LEGACY_GENERATION_ID), ordinal, 1
        )
    )
    got = {
        str(v)
        for c in env.collection.data.delete_many.call_args_list
        for v in c.kwargs["where"].value
    }
    assert expected_uuids <= got

    with env.sync_factory() as s:
        assert (
            s.execute(
                select(Document).where(Document.source_id == f"{SRC}/doomed")
            ).scalar_one_or_none()
            is None
        )
        assert (
            s.execute(
                select(DocumentVersion).where(DocumentVersion.id == version_id)
            ).scalar_one_or_none()
            is None
        )


@pytest.mark.asyncio
async def test_never_touches_eligible_less_serving_documents(env):
    """serving 文档(active/missing_candidate)永不在 GC 资格内。"""
    now = datetime.now(UTC)
    with env.sync_factory() as s:
        _seed_doc_with_version(s, f"{SRC}/alive", gen=None, lifecycle_state="active")
        _seed_doc_with_version(
            s,
            f"{SRC}/grace",
            gen=None,
            lifecycle_state="missing_candidate",
            superseded_at=now - timedelta(days=100),
        )
        s.commit()

    report = await sweep(env.async_factory, env.pipeline, now=now, apply=True)
    assert report.documents_eligible == []
    assert report.documents_deleted == 0
    env.collection.data.delete_many.assert_not_called()
