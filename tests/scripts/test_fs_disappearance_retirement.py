"""Issue #25 Track A 契约测试:fs/woo 源文件消失的两击退休(fixture 级)。

契约锚点(docs/engineering/tasks/v164-track-a-lifecycle-retirement-contract.md,
FROZEN @ docs/v164-iteration-contracts-20260913):

- A-1:完整权威发现后,账本与权威清单的差集是一等生命周期事实;不能自证
  删除的连接器(filesystem/woo)由**账本侧确认**(向量侧 EXTRA_CONFIRMED_RETIRED
  的镜像)驱动退休;
- A-2:第一次完整发现缺席 ⇒ missing_candidate 宽限(仍在服务,Needs Attention
  可见);第二次连续完整发现缺席 ⇒ RETIRED(即时撤出服务,deleted_at 为 GC
  计时锚,资格 = retired_at + 7d);不完整/失败/低覆盖发现不推进计数;
- A-3:政策缺席(include_dirs/file_types/排除)绝不推进计数,独立 reason
  呈现,重包含恢复;
- A-6:退休决策持久化 reason/evidence/actor,幂等,#50 详情面可读;
- A-7:reconciliation 保持显式,不扩大 repair 去复活 source-confirmed-removed。

历史(RED 证据):本文件在实现前的 main baseline b338c3c 上 3/3 FAIL
(首断言 'active' == 'missing_candidate' 精确命中 founding defect)。

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
# fs/woo 形态 stub connector:删除检测不可用(fetch_deleted→[] 是现状契约),
# 权威完整发现 = fetch_all(抽取即枚举,无 run_stats/authoritative 原语)。
# --------------------------------------------------------------------------- #


class _ListingConnector:
    """filesystem / woocommerce 形态连接器 stub(Track A 契约面)。

    - ``fetch_changes`` 恒空:文件消失对增量窗口不可见(删文件不产生 mtime
      事件,这正是 founding defect);
    - ``fetch_all`` 返回当前磁盘权威全集(``listing``;gone 默认不在 ——
      已从盘上删除);
    - ``fetch_deleted`` 恒 [](filesystem.py:214 现状);
    - ``DECLARES_DELETIONS = False``:不能自证删除 → 账本侧缺席确认负责
      退休(Track A A-1);
    - ``policy_absence_reason``:范围分类(A-3),``policy_reason`` 非空时
      全部缺席判为政策范围外;
    - ``discover_error`` 非空时 fetch_all 抛异常(瞬时扫描失败,模拟
      不完整发现;Acceptance 3:不推进确认计数)。
    """

    DECLARES_DELETIONS = False

    def __init__(
        self,
        *,
        listing: tuple[str, ...] = (KEEP,),
        policy_reason: str | None = None,
        discover_error: Exception | None = None,
    ) -> None:
        self._listing = listing
        self._policy_reason = policy_reason
        self._discover_error = discover_error

    @property
    def source_id(self) -> str:  # pragma: no cover - 形态占位
        return SRC

    def fetch_changes(self, since):
        return iter([])

    def fetch_all(self):
        if self._discover_error is not None:
            raise self._discover_error
        return iter([MagicMock(source_id=sid) for sid in self._listing])

    def fetch_deleted(self, since):
        return []  # fs/woo 现状:无法重建删除事件

    def policy_absence_reason(self, source_id: str) -> str | None:
        return self._policy_reason


class _WooShapeConnector(_ListingConnector):
    """woo 形态:listing 即权威(policy 恒 None);显式子类仅作语义标注。"""


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


def _row_of(sync_factory, sid: str) -> Document:
    sync_sf, _ = sync_factory
    with sync_sf() as session:
        return session.execute(
            select(Document).where(Document.source_id == sid)
        ).scalar_one()


def _lifecycle_of(sync_factory, sid: str) -> str | None:
    return _row_of(sync_factory, sid).lifecycle


def _deleted_at_of(sync_factory, sid: str) -> datetime | None:
    return _row_of(sync_factory, sid).deleted_at


def _absence_of(sync_factory, sid: str) -> dict | None:
    return lifecycle.get_absence_state(_row_of(sync_factory, sid))


def _retirement_of(sync_factory, sid: str) -> dict | None:
    return lifecycle.get_retirement_record(_row_of(sync_factory, sid))


async def _run_sync(sync_factory, connector, monkeypatch, n_times: int = 1) -> None:
    """经稳定 seam `_sync_one` 驱动 n 轮同步(无变更路径;零向量副作用)。"""
    from backend.services.vector_consistency import VectorGapReport

    sync_sf, async_sf = sync_factory

    pipeline = MagicMock()
    # 缺席确认/墓碑原语依赖账本同步会话工厂(真实 PG;Track A A-1/A-2)
    pipeline._session_factory = sync_sf

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
    """
    connector = _ListingConnector()
    await _run_sync(sync_factory, connector, monkeypatch, n_times=1)

    # ---- 第一次完整发现后:宽限态(仍在服务)----
    assert _lifecycle_of(sync_factory, GONE) == lifecycle.DocLifecycle.MISSING_CANDIDATE, (
        "sync#1 完整发现观察到 gone.md 缺席 ⇒ 必须进入 missing_candidate 宽限态"
        "(A-2 第一次确认)"
    )
    assert _lifecycle_of(sync_factory, KEEP) == lifecycle.DocLifecycle.ACTIVE
    first = _absence_of(sync_factory, GONE)
    assert first is not None and int(first["confirmations"]) == 1
    assert _lifecycle_of(sync_factory, GONE) in lifecycle.DocLifecycle.SERVING  # 宽限态仍在服务集(词表不变式)

    # ---- 第二次连续完整发现后:退休 ----
    await _run_sync(sync_factory, connector, monkeypatch, n_times=1)

    assert _lifecycle_of(sync_factory, GONE) == lifecycle.DocLifecycle.DELETED, (
        "sync#2 连续完整发现同一缺席 ⇒ 必须退休(A-2 第二次确认)"
    )
    deleted_at = _deleted_at_of(sync_factory, GONE)
    assert deleted_at is not None, "退休必须落 deleted_at(GC 计时锚;A-4 复用)"
    assert _lifecycle_of(sync_factory, GONE) not in lifecycle.DocLifecycle.SERVING, (
        "RETIRED 即时退出服务集(TB-P1 冻结撤出时序;≤1 天上限)"
    )
    assert _lifecycle_of(sync_factory, KEEP) == lifecycle.DocLifecycle.ACTIVE


async def test_incomplete_discovery_does_not_advance_confirmation(sync_factory, monkeypatch):
    """Acceptance 3:失败/不完整发现不是确认,不推进计数。

    完整发现 #1 ⇒ missing_candidate;随后两次 fetch_all 抛错(瞬时扫描失败)
    ⇒ 必须停留 missing_candidate,绝不允许被确认为 RETIRED。
    """
    await _run_sync(sync_factory, _ListingConnector(), monkeypatch, n_times=1)
    assert _lifecycle_of(sync_factory, GONE) == lifecycle.DocLifecycle.MISSING_CANDIDATE

    failing = _ListingConnector(discover_error=RuntimeError("transient scan failure"))
    await _run_sync(sync_factory, failing, monkeypatch, n_times=2)

    assert _lifecycle_of(sync_factory, GONE) == lifecycle.DocLifecycle.MISSING_CANDIDATE, (
        "不完整/失败发现不得推进确认计数(A-2/Acceptance 3;G004 类守卫)"
    )
    assert _deleted_at_of(sync_factory, GONE) is None
    state = _absence_of(sync_factory, GONE)
    assert state is not None and int(state["confirmations"]) == 1, (
        "不完整发现轮次不得改变确认计数"
    )


async def test_retired_gc_eligibility_is_seven_days_after_retirement(sync_factory, monkeypatch):
    """A-4(冻结时序复用):retired_at + 7d 方可物理 GC;资格锚不早于退休时刻。

    以 deleted_at 为锚断言 7 天窗(词表常量 RETIRED_RETENTION_DAYS);
    doc 级资格物理落点(列 vs sweep 期计算)属 HOW 开放,断言只锁语义。
    """
    await _run_sync(sync_factory, _ListingConnector(), monkeypatch, n_times=2)

    deleted_at = _deleted_at_of(sync_factory, GONE)
    assert deleted_at is not None
    now = datetime.now(UTC)
    assert now - deleted_at < timedelta(days=lifecycle.RETIRED_RETENTION_DAYS), (
        "退休后 7 天保留窗内不得物理 GC(A-4:RETIRED retained 7 days)"
    )


# ---- Acceptance 2(A-3):政策缺席不计数、独立 reason、重包含恢复 ----
async def test_policy_absence_frozen_then_reinclusion_restores(sync_factory, monkeypatch):
    """政策范围外缺席:计数恒 0 不推进;独立 reason 呈现;重包含恢复 active。"""
    # 第 1-2 次发现:gone 因政策(file_types)不可见
    policy_conn = _ListingConnector(policy_reason="file_types")
    await _run_sync(sync_factory, policy_conn, monkeypatch, n_times=2)

    assert _lifecycle_of(sync_factory, GONE) == lifecycle.DocLifecycle.MISSING_CANDIDATE, (
        "政策缺席仍应进入宽限态(Needs Attention 呈现,仍在服务)"
    )
    state = _absence_of(sync_factory, GONE)
    assert state is not None and state["policy_reason"] == "file_types", (
        "政策缺席必须有独立 surfaced reason(A-3)"
    )
    assert int(state["confirmations"]) == 0, (
        "政策缺席绝不推进确认计数(Acceptance 2;连续两次也不得确认)"
    )
    assert _deleted_at_of(sync_factory, GONE) is None

    # 第 3 次发现:政策重包含(gone 回到权威清单)→ 恢复 active + 清状态
    restored_conn = _ListingConnector(listing=(KEEP, GONE))
    await _run_sync(sync_factory, restored_conn, monkeypatch, n_times=1)

    assert _lifecycle_of(sync_factory, GONE) == lifecycle.DocLifecycle.ACTIVE, (
        "重包含必须恢复(A-3:without resurrection side-effects)"
    )
    assert _deleted_at_of(sync_factory, GONE) is None
    assert _absence_of(sync_factory, GONE) is None, "恢复后缺席状态必须清除"


# ---- Acceptance 4(A-1 对 woo 同构):fixture 级两发现退休 + A-6 审计 ----
async def test_woo_shape_fixture_two_discoveries_retire(sync_factory, monkeypatch):
    """woo 形态(无政策过滤,listing 即权威)走同一确认流(Acceptance 4)。"""
    connector = _WooShapeConnector()
    assert connector.policy_absence_reason(GONE) is None
    await _run_sync(sync_factory, connector, monkeypatch, n_times=2)

    assert _lifecycle_of(sync_factory, GONE) == lifecycle.DocLifecycle.DELETED
    record = _retirement_of(sync_factory, GONE)
    assert record is not None, "退休决策必须持久化(A-6)"
    assert record["reason"] == lifecycle.RETIRE_REASON_DISCOVERY
    assert record["actor"] == lifecycle.ACTOR_SYNC_ABSENCE
    assert (
        int(record["evidence"]["confirmations"]) == lifecycle.ABSENCE_CONFIRMATIONS_REQUIRED
    )
    assert record["gc_eligible_at"] is not None


# ---- Acceptance 5(A-6):确认扫描幂等 —— 重放零变更 ----
async def test_idempotent_reconfirmation_after_retirement(sync_factory, monkeypatch):
    """退休后再跑确认扫描:零变更(lifecycle/记录/时间戳稳定)。"""
    connector = _ListingConnector()
    await _run_sync(sync_factory, connector, monkeypatch, n_times=2)
    first = _retirement_of(sync_factory, GONE)
    assert first is not None

    await _run_sync(sync_factory, connector, monkeypatch, n_times=2)
    again = _retirement_of(sync_factory, GONE)
    assert again == first, "重复确认扫描必须幂等(Acceptance 5)"
    assert _lifecycle_of(sync_factory, GONE) == lifecycle.DocLifecycle.DELETED


# ---- A-5:GC 物理 apply config gate(CLI 意图 ∧ 配置开门)----
async def test_gc_apply_requires_config_gate():
    from types import SimpleNamespace

    from scripts.gc_lifecycle import resolve_apply

    gate_off = SimpleNamespace(lifecycle_gc_apply=False)
    gate_on = SimpleNamespace(lifecycle_gc_apply=True)

    apply, note = resolve_apply(False, gate_off)
    assert apply is False and "default" in note, "默认必须 report-only(A-5)"

    apply, note = resolve_apply(True, gate_off)
    assert apply is False and "LIFECYCLE_GC_APPLY" in note, (
        "--apply 无配置开门必须显式拒绝(A-5:physical apply is config-gated)"
    )

    apply, note = resolve_apply(True, gate_on)
    assert apply is True, "CLI 意图 + 配置开门 → 允许物理 apply"


# ---- A-2/A-4:GC 资格 = retired_at + 7d(dry-run 判定)----
async def test_gc_eligibility_only_after_seven_days(sync_factory, monkeypatch):
    from backend.services.lifecycle_gc import sweep

    await _run_sync(sync_factory, _ListingConnector(), monkeypatch, n_times=2)
    assert _lifecycle_of(sync_factory, GONE) == lifecycle.DocLifecycle.DELETED

    pipeline = MagicMock()
    # 退休当下:7 天窗内,不得取得资格(单列呈现 retirement_pending)
    report_now = await sweep(sync_factory[1], pipeline, now=datetime.now(UTC), apply=False)
    assert GONE not in report_now.documents_eligible
    assert GONE in report_now.retirement_pending

    # +8 天:自动取得资格(A-2:gc_eligible_at = retired_at + 7d)
    future = datetime.now(UTC) + timedelta(days=8)
    report_future = await sweep(sync_factory[1], pipeline, now=future, apply=False)
    assert GONE in report_future.documents_eligible
