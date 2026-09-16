"""Issue #25 RED 表征测试:fs 源文件消失的两击退休契约(fixture 级)。

契约锚点(docs/engineering/tasks/v164-track-a-lifecycle-retirement-contract.md,
FROZEN @ docs/v164-iteration-contracts-20260913):

- A-1:完整权威发现后,账本与权威清单的差集是一等生命周期事实;不能自证
  删除的连接器(filesystem/woo)由**账本侧确认**(向量侧 EXTRA_CONFIRMED_RETIRED
  的镜像)驱动退休;
- A-2:第一次完整发现缺席 ⇒ missing_candidate 宽限(仍在服务,Needs Attention
  可见);第二次连续完整发现缺席 ⇒ RETIRED(即时撤出服务,deleted_at 为 GC
  计时锚,资格 = retired_at + 7d);不完整/失败/低覆盖发现不推进计数;
- A-7:reconciliation 保持显式,不扩大 repair 去复活 source-confirmed-removed
  的内容。

当前 main 实测 = **RED**(2026-09-15 @ b338c3c..648b391):
- `filesystem.fetch_deleted()` 恒 [](filesystem.py:214-221),tombstone 分支
  (scripts/sync.py:1164-1176)对 fs 永远死代码;
- 无任何「账本行 ∈ 账本 − 完整发现」的 ledger 侧缺席确认路径;
  `_discover_source_docs` 的完整性守卫仅被孤儿向量分支消费;
- 无变更路径对 fs 恒 healthy(sync 后账本行永远停留 active,永不进入
  missing_candidate,更不会 RETIRED)⇒ 本文件全部断言在 main 上失败。

零 Weaviate / 零 embed:verify_source_vectors 与 GenerationBuilder 全 patch,
账本语义走真实 Postgres(TEST_DATABASE_URL,与 P1 生命周期门测试同约定)。
实现 HOW 开放:仅经由稳定 seam `_sync_one` 驱动,断言只落账本可见结果。
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.db.models import Base, Document, DocumentVersion
from backend.services import document_lifecycle as lifecycle
from scripts.sync import _sync_one

pytestmark = pytest.mark.asyncio

SRC = "fs25red"
KEEP = f"{SRC}/main/keep.md"
GONE = f"{SRC}/main/gone.md"


# --------------------------------------------------------------------------- #
# fs 形态 stub connector:删除检测不可用(fetch_deleted→[] 是 fs 现状契约),
# 权威完整发现 = fetch_all(抽取即枚举,无 run_stats/authoritative 原语)。
# --------------------------------------------------------------------------- #


class _FsShapeConnector:
    """filesystem 形态连接器 stub。

    - ``fetch_changes`` 恒空:文件消失对增量窗口不可见(删文件不产生 mtime
      事件,这正是 founding defect);
    - ``fetch_all`` 返回当前磁盘权威全集(gone.md 已从盘上删除);
    - ``fetch_deleted`` 恒 [](filesystem.py:214 现状);
    - ``discover_error`` 非空时 fetch_all 抛异常(瞬时扫描失败,模拟
      不完整发现;Acceptance 3:不推进确认计数)。
    """

    def __init__(self, *, discover_error: Exception | None = None) -> None:
        self._discover_error = discover_error

    @property
    def source_id(self) -> str:  # pragma: no cover - 形态占位
        return SRC

    def fetch_changes(self, since):
        return iter([])

    def fetch_all(self):
        if self._discover_error is not None:
            raise self._discover_error
        return iter([MagicMock(source_id=KEEP)])

    def fetch_deleted(self, since):
        return []  # fs 现状:无法重建删除事件


def _doc(sid: str, chunk_count: int = 2) -> Document:
    return Document(
        content_hash=f"hash-{sid}",
        source_id=sid,
        source_type="filesystem",
        product="probe",
        title=sid.rsplit("/", 1)[-1],
        url=f"file:///{sid}",
        metadata_={},
        branch="main",
        chunk_count=chunk_count,
    )


@pytest.fixture()
def sync_factory(db_engine):
    """同步 + 异步两个会话工厂,共用同一测试库。"""
    from backend.db.session import get_session_factory

    sync_engine = create_engine(
        os.environ["TEST_DATABASE_URL"].replace("+asyncpg", "+psycopg2")
    )
    Base.metadata.create_all(sync_engine)
    try:
        yield (
            sessionmaker(bind=sync_engine, expire_on_commit=False),
            get_session_factory(db_engine),
        )
    finally:
        sync_engine.dispose()


@pytest.fixture(autouse=True)
def _seed_ledger(sync_factory):
    """种子:源内两行 active(keep 在盘,gone 已从盘删除),各带初始版本。"""
    sync_sf, _ = sync_factory
    with sync_sf() as session:
        for row in session.execute(
            select(Document).where(Document.source_id.like(f"{SRC}/%"))
        ).scalars():
            session.delete(row)
        for row in session.execute(
            select(DocumentVersion).where(DocumentVersion.source_id.like(f"{SRC}/%"))
        ).scalars():
            session.delete(row)
        session.commit()
        keep, gone = _doc(KEEP), _doc(GONE, chunk_count=1)
        session.add(keep)
        session.add(gone)
        session.flush()
        lifecycle.ensure_initial_version(session, keep)
        lifecycle.ensure_initial_version(session, gone)
        session.commit()
    yield
    with sync_sf() as session:
        for row in session.execute(
            select(Document).where(Document.source_id.like(f"{SRC}/%"))
        ).scalars():
            session.delete(row)
        for row in session.execute(
            select(DocumentVersion).where(DocumentVersion.source_id.like(f"{SRC}/%"))
        ).scalars():
            session.delete(row)
        session.commit()


def _lifecycle_of(sync_factory, sid: str) -> str | None:
    sync_sf, _ = sync_factory
    with sync_sf() as session:
        row = session.execute(
            select(Document).where(Document.source_id == sid)
        ).scalar_one()
        return row.lifecycle


def _deleted_at_of(sync_factory, sid: str) -> datetime | None:
    sync_sf, _ = sync_factory
    with sync_sf() as session:
        row = session.execute(
            select(Document).where(Document.source_id == sid)
        ).scalar_one()
        return row.deleted_at


async def _run_sync(sync_factory, connector, monkeypatch, n_times: int = 1) -> None:
    """经稳定 seam `_sync_one` 驱动 n 轮同步(无变更路径;零向量副作用)。"""
    from backend.services.vector_consistency import VectorGapReport

    sync_sf, async_sf = sync_factory

    pipeline = MagicMock()
    pipeline._session_factory = None  # 墓碑原语依赖的账本工厂由被测路径自建/注入

    healthy = VectorGapReport(
        expected_chunks=3,
        actual_chunks=3,
        missing_source_ids=[],
        refill_source_ids=[],
        stale_chunk_count=0,
        orphan_count=0,
    )

    builder = MagicMock()
    builder.repair_documents.return_value = ([], [], 0)
    builder.build_generation.return_value = MagicMock(
        chunks_written=0,
        new_docs=[],
        updated_docs=[],
        metadata_docs=[],
        unchanged_docs=[],
    )

    monkeypatch.setattr("scripts.sync.ConnectorRegistry.create", lambda cfg: connector)
    monkeypatch.setattr("scripts.sync.verify_source_vectors", _async_const(healthy))
    monkeypatch.setattr("scripts.sync.GenerationBuilder", lambda *a, **k: builder)

    cfg = MagicMock()
    cfg.id = SRC
    cfg.type = "filesystem"

    for _ in range(n_times):
        await _sync_one(cfg, pipeline, async_sf, triggered_by="cron")


def _async_const(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner


async def test_two_complete_discoveries_retire_disappeared_file(sync_factory, monkeypatch):
    """契约主链(Acceptance 1):删除 → sync#1 missing_candidate → sync#2 RETIRED。

    - sync#1(第一次完整发现,keep 在、gone 不在)⇒ gone 进入
      missing_candidate 宽限(仍在 SERVING,保上一代服务);keep 不受影响;
    - sync#2(第二次连续完整发现,同一缺席)⇒ gone RETIRED(tombstone,
      deleted_at 落锚;即时退出 SERVING,服务投影不再含它),GC 资格锚 =
      retired 时刻 + 7 天;
    - 全程零 Weaviate 副作用(本轮校验 healthy:向量仍在——这正是缺陷的
      更隐蔽形态:缺口检测根本不会触发,必须由发现差集驱动)。

    当前 main:两条 sync 全走 healthy no-change 分支,gone 永远 active ⇒
    第一条断言即 RED。
    """
    connector = _FsShapeConnector()
    await _run_sync(sync_factory, connector, monkeypatch, n_times=1)

    # ---- 第一次完整发现后:宽限态(仍在服务)----
    assert _lifecycle_of(sync_factory, GONE) == lifecycle.DocLifecycle.MISSING_CANDIDATE, (
        "sync#1 完整发现观察到 gone.md 缺席 ⇒ 必须进入 missing_candidate 宽限态"
        "(A-2 第一次确认;当前 main 无缺席确认路径,行停留 active)"
    )
    assert _lifecycle_of(sync_factory, KEEP) == lifecycle.DocLifecycle.ACTIVE
    assert GONE in lifecycle.DocLifecycle.SERVING  # 宽限态仍在服务集(词表不变式)

    # ---- 第二次连续完整发现后:退休 ----
    await _run_sync(sync_factory, connector, monkeypatch, n_times=1)

    assert _lifecycle_of(sync_factory, GONE) == lifecycle.DocLifecycle.DELETED, (
        "sync#2 连续完整发现同一缺席 ⇒ 必须退休(A-2 第二次确认;"
        "当前 main 永远不会到达)"
    )
    deleted_at = _deleted_at_of(sync_factory, GONE)
    assert deleted_at is not None, "退休必须落 deleted_at(GC 计时锚;A-4 复用)"
    assert GONE not in lifecycle.DocLifecycle.SERVING, (
        "RETIRED 即时退出服务集(TB-P1 冻结撤出时序;≤1 天上限)"
    )
    assert _lifecycle_of(sync_factory, KEEP) == lifecycle.DocLifecycle.ACTIVE


async def test_incomplete_discovery_does_not_advance_confirmation(sync_factory, monkeypatch):
    """Acceptance 3:失败/不完整发现不是确认,不推进计数。

    完整发现 #1 ⇒ missing_candidate;随后两次 fetch_all 抛错(瞬时扫描失败)
    ⇒ 必须停留 missing_candidate,绝不允许被确认为 RETIRED。
    (当前 main:第 1 条断言 RED——同上,无确认路径。)
    """
    await _run_sync(sync_factory, _FsShapeConnector(), monkeypatch, n_times=1)
    assert _lifecycle_of(sync_factory, GONE) == lifecycle.DocLifecycle.MISSING_CANDIDATE

    failing = _FsShapeConnector(discover_error=RuntimeError("transient scan failure"))
    await _run_sync(sync_factory, failing, monkeypatch, n_times=2)

    assert _lifecycle_of(sync_factory, GONE) == lifecycle.DocLifecycle.MISSING_CANDIDATE, (
        "不完整/失败发现不得推进确认计数(A-2/Acceptance 3;G004 类守卫)"
    )
    assert _deleted_at_of(sync_factory, GONE) is None


async def test_retired_gc_eligibility_is_seven_days_after_retirement(sync_factory, monkeypatch):
    """A-4(冻结时序复用):retired_at + 7d 方可物理 GC;资格锚不早于退休时刻。

    以 deleted_at 为锚断言 7 天窗(词表常量 RETIRED_RETENTION_DAYS);
    doc 级资格物理落点(列 vs sweep 期计算)属 HOW 开放,断言只锁语义。
    (当前 main:deleted_at 恒 None ⇒ RED。)
    """
    await _run_sync(sync_factory, _FsShapeConnector(), monkeypatch, n_times=2)

    deleted_at = _deleted_at_of(sync_factory, GONE)
    assert deleted_at is not None
    now = datetime.now(UTC)
    assert now - deleted_at < timedelta(days=lifecycle.RETIRED_RETENTION_DAYS), (
        "退休后 7 天保留窗内不得物理 GC(A-4:RETIRED retained 7 days)"
    )
