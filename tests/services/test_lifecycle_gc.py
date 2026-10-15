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


# --------------------------------------------------------------------------- #
# #162:普通墓碑(真实 tombstone_document 原语)≠ GC opt-in。
# 生产 fetch_deleted/membership 路径经 tombstone_document 落 retirement 记录
# (gc_eligible_at=None);sweep 不得据此把它们拉进 7 天自动物理清理资格。
# --------------------------------------------------------------------------- #


def _seed_ordinary_tombstone(s, sid: str, *, reason: str, age_days: int, now: datetime) -> Document:
    """按生产路径建文档+版本,再经真实 tombstone_document 原语落墓碑。

    ``now=`` 回填 deleted_at/retired_at(= 原语写出的 N 天前生产形态);
    retirement 记录保持原语原样(gc_eligible_at=None),零手工元数据。
    """
    doc, _ = _seed_doc_with_version(s, sid, gen=None)
    assert lifecycle.tombstone_document(s, sid, reason=reason, now=now - timedelta(days=age_days))
    return doc


@pytest.mark.asyncio
async def test_ordinary_tombstone_via_real_primitive_never_auto_eligible(env):
    """fetch_deleted/membership 普通墓碑:tombstone_days=None 时超 7 天/30 天
    仍不进 documents_eligible;apply 亦零 Weaviate 删除(A-5 分层,#162)。"""
    now = datetime.now(UTC)
    with env.sync_factory() as s:
        _seed_ordinary_tombstone(
            s,
            f"{SRC}/prim-fd",
            reason="fetch_deleted:gh-probe",
            age_days=8,
            now=now,
        )
        _seed_ordinary_tombstone(
            s,
            f"{SRC}/prim-mem",
            reason="membership_reconcile",
            age_days=31,
            now=now,
        )
        s.commit()

    report = await sweep(env.async_factory, env.pipeline, now=now)
    assert f"{SRC}/prim-fd" not in report.documents_eligible
    assert f"{SRC}/prim-mem" not in report.documents_eligible
    # 普通墓碑无自动窗可观察:不得伪装成 retirement_pending 证据面
    assert report.retirement_pending == []
    # dry-run 默认 + 资格为空 → 零物理动作
    assert report.dry_run is True
    assert report.objects_deleted == 0
    env.collection.data.delete_many.assert_not_called()

    # apply=True 也不产生任何删除(资格判定为空,非 dry-run 门控所致)
    report_apply = await sweep(env.async_factory, env.pipeline, now=now, apply=True)
    assert report_apply.documents_eligible == []
    assert report_apply.documents_deleted == 0
    env.collection.data.delete_many.assert_not_called()


@pytest.mark.asyncio
async def test_ordinary_tombstone_enters_eligibility_only_with_explicit_window(env):
    """显式 tombstone_days:真实原语墓碑仅超窗者入资格(7 天/30 天窗分档)。"""
    now = datetime.now(UTC)
    with env.sync_factory() as s:
        _seed_ordinary_tombstone(s, f"{SRC}/optin-d2", reason="fetch_deleted:x", age_days=2, now=now)
        _seed_ordinary_tombstone(s, f"{SRC}/optin-d8", reason="fetch_deleted:x", age_days=8, now=now)
        _seed_ordinary_tombstone(s, f"{SRC}/optin-d31", reason="membership_reconcile", age_days=31, now=now)
        s.commit()

    report = await sweep(env.async_factory, env.pipeline, now=now, tombstone_days=7)
    assert f"{SRC}/optin-d2" not in report.documents_eligible
    assert f"{SRC}/optin-d8" in report.documents_eligible
    assert f"{SRC}/optin-d31" in report.documents_eligible

    report30 = await sweep(env.async_factory, env.pipeline, now=now, tombstone_days=30)
    assert report30.documents_eligible == [f"{SRC}/optin-d31"]


@pytest.mark.asyncio
async def test_tombstone_gc_eligible_at_malformations_never_auto_eligible(env):
    """gc_eligible_at=null/缺省/畸形:一律不构成自动资格锚(无 opt-in 时
    零资格;显式 opt-in 时按 deleted_at 锚走墓碑窗,#162)。"""
    now = datetime.now(UTC)
    cases = ("null", "missing", "malformed")
    with env.sync_factory() as s:
        for name in cases:
            doc = _seed_ordinary_tombstone(
                s, f"{SRC}/mal-{name}", reason=f"fetch_deleted:{name}", age_days=10, now=now
            )
            # 防御面:模拟既有/损坏行的三种 gc_eligible_at 形态(JSONB 整体重赋值)
            orig = lifecycle.get_retirement_record(doc)
            if name == "null":
                record = {**orig, "gc_eligible_at": None}
            elif name == "missing":
                record = {k: v for k, v in orig.items() if k != "gc_eligible_at"}
            else:
                record = {**orig, "gc_eligible_at": "not-a-timestamp"}
            doc.metadata_ = {**doc.metadata_, lifecycle.RETIREMENT_META_KEY: record}
        s.commit()

    report = await sweep(env.async_factory, env.pipeline, now=now)
    for name in cases:
        assert f"{SRC}/mal-{name}" not in report.documents_eligible
    assert report.retirement_pending == []
    env.collection.data.delete_many.assert_not_called()

    report_opt = await sweep(env.async_factory, env.pipeline, now=now, tombstone_days=7)
    assert sorted(report_opt.documents_eligible) == sorted(f"{SRC}/mal-{n}" for n in cases)


# --------------------------------------------------------------------------- #
# #162 AC2:真实 confirm_absence_retirement 的 7 天自动窗语义不变
# --------------------------------------------------------------------------- #


def _seed_confirmed_absence(s, sid: str, *, retired_when: datetime, now: datetime) -> Document:
    """按生产缺席确认路径(真实原语)落确认退休;now= 回填 retired_at。"""
    doc, _ = _seed_doc_with_version(s, sid, gen=None)
    lifecycle.confirm_absence_retirement(
        doc,
        reason=lifecycle.RETIRE_REASON_DISCOVERY,
        actor=lifecycle.ACTOR_SYNC_ABSENCE,
        evidence={"confirmations": 2},
        now=retired_when,
    )
    return doc


@pytest.mark.asyncio
async def test_confirmed_absence_retirement_auto_window_unchanged(env):
    """确认缺席退休:retired_at+7d 自动资格不变 —— 未到期不合格(含显式
    更短墓碑窗亦不得提前),到期进资格;普通墓碑不受影响同场对照。"""
    now = datetime.now(UTC)
    with env.sync_factory() as s:
        _seed_confirmed_absence(s, f"{SRC}/absence-early", retired_when=now - timedelta(days=2), now=now)
        _seed_confirmed_absence(s, f"{SRC}/absence-due", retired_when=now - timedelta(days=8), now=now)
        s.commit()

    report = await sweep(env.async_factory, env.pipeline, now=now)
    assert f"{SRC}/absence-early" not in report.documents_eligible
    assert f"{SRC}/absence-early" in report.retirement_pending
    assert f"{SRC}/absence-due" in report.documents_eligible
    env.collection.data.delete_many.assert_not_called()

    # 显式更短的墓碑窗(tombstone_days=1)不压缩自动窗:提前仍不合格
    report_opt = await sweep(env.async_factory, env.pipeline, now=now, tombstone_days=1)
    assert f"{SRC}/absence-early" not in report_opt.documents_eligible
    assert f"{SRC}/absence-early" in report_opt.retirement_pending
    assert f"{SRC}/absence-due" in report_opt.documents_eligible


@pytest.mark.asyncio
async def test_apply_purges_confirmed_absence_document_deterministically(env):
    """apply:到期确认缺席退休文档 → 确定性 UUID 点删 + 账本行全清 +
    审计计数一致 + 幂等(第二轮零资格零删除)。"""
    now = datetime.now(UTC)
    with env.sync_factory() as s:
        doc, version = _seed_doc_with_version(s, f"{SRC}/absence-doomed", gen=None, chunks=1)
        lifecycle.confirm_absence_retirement(
            doc,
            reason=lifecycle.RETIRE_REASON_DISCOVERY,
            actor=lifecycle.ACTOR_SYNC_ABSENCE,
            now=now - timedelta(days=8),
        )
        s.commit()
        ordinal = version.generation_ordinal

    report = await sweep(env.async_factory, env.pipeline, now=now, apply=True)
    assert f"{SRC}/absence-doomed" in report.documents_eligible
    assert report.documents_deleted == 1
    assert report.versions_deleted == 1
    assert report.chunk_rows_deleted == 1
    got = {
        str(v)
        for c in env.collection.data.delete_many.call_args_list
        for v in c.kwargs["where"].value
    }
    assert got == set(
        chunk_uuids_for_version(f"{SRC}/absence-doomed", str(lifecycle.LEGACY_GENERATION_ID), ordinal, 1)
    )
    with env.sync_factory() as s:
        assert (
            s.execute(
                select(Document).where(Document.source_id == f"{SRC}/absence-doomed")
            ).scalar_one_or_none()
            is None
        )

    # 幂等:行已清除,第二轮 sweep 零资格、零删除
    env.collection.data.delete_many.reset_mock()
    report2 = await sweep(env.async_factory, env.pipeline, now=now, apply=True)
    assert report2.documents_eligible == []
    assert report2.documents_deleted == 0
    env.collection.data.delete_many.assert_not_called()
