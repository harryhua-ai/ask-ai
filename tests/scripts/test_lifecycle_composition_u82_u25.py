"""#82×#25 Lifecycle composition 不变量(组合树 integration/v1.6.3-r5-lifecycle-comp)。

两个 accepted 候选的语义缝(#82 = branch-scope expansion backfill +
authority−ledger reconciliation + serving-only count truth;#25 = 两击缺席
退休 + 政策缺席冻结 + 恢复)。本套件只锁定**跨机制**不变量,单 Issue 契约
由各自既有套件冻结(test_issue82_* / test_fs_disappearance_retirement):

- INV-C1(git 退休唯一路):能自证删除的连接器(DECLARES_DELETIONS=True,
  git/web)对缺席确认机完全免疫 —— #82 收缩路径(membership reconciliation)
  是 git 文档退休的唯一通道,缺席机不重复处理、不产生第二退休语义;
- INV-C2(政策缺席两轮冻结,不垫底):scope 外缺席连续两轮完整发现,
  lifecycle 保持 active、确认计数恒 0(A-3);解除政策原因后真实范围缺席
  的计数从零起算 —— 政策轮绝不垫底;
- INV-C3(重入恢复):一次确认候选(missing_candidate)在权威清单重新
  包含(#82 扩大/补灌方向)后,单轮同步即恢复 active 并清除缺席状态 ——
  恢复语义与补灌语义在组合树上无缝衔接。

真实 Postgres(TEST_DATABASE_URL);经稳定 seam ``_sync_one`` 驱动(与
test_fs_disappearance_retirement 同构,零向量副作用)。
"""

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.db.models import Base, Document, DocumentVersion
from backend.services import document_lifecycle as lifecycle

pytestmark = pytest.mark.asyncio

SRC = "u82u25comp"
DOC = f"{SRC}/main/doc-a.md"


class _GitShapeConnector:
    """git 形态:能自证删除(DECLARES_DELETIONS=True,INV-C1 边界面)。"""

    DECLARES_DELETIONS = True

    @property
    def source_id(self) -> str:
        return SRC

    def fetch_changes(self, since):
        return iter([])

    def fetch_all(self):
        return iter([])

    def fetch_deleted(self, since):
        return []

    def policy_absence_reason(self, source_id: str) -> str | None:
        return None


class _FsShapeConnector:
    """fs 形态:不能自证删除;policy_reason 可切换(INV-C2/C3 面)。"""

    DECLARES_DELETIONS = False

    def __init__(self, *, listing: tuple[str, ...], policy_reason: str | None = None):
        self._listing = listing
        self._policy_reason = policy_reason

    @property
    def source_id(self) -> str:
        return SRC

    def fetch_changes(self, since):
        return iter([])

    def fetch_all(self):
        return iter([MagicMock(source_id=sid) for sid in self._listing])

    def fetch_deleted(self, since):
        return []

    def policy_absence_reason(self, source_id: str) -> str | None:
        return self._policy_reason


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
        doc = _doc(DOC)
        session.add(doc)
        session.flush()
        lifecycle.ensure_initial_version(session, doc)
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


def _absence_of(sync_factory, sid: str) -> dict | None:
    return lifecycle.get_absence_state(_row_of(sync_factory, sid))


async def _run_sync(sync_factory, connector, monkeypatch, n_times: int = 1) -> list[dict]:
    """经 _sync_one 稳定 seam 驱动 n 轮同步;返回每轮 absence_change 记账。"""
    from scripts.sync import _sync_one
    from backend.services.vector_consistency import VectorGapReport

    sync_sf, async_sf = sync_factory
    pipeline = MagicMock()
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

    rounds = []
    for _ in range(n_times):
        await _sync_one(cfg, pipeline, async_sf, triggered_by="cron")
    return rounds


def _async_const(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner


async def test_c1_git_deletion_proof_connector_is_immune_to_absence_machine(
    sync_factory, monkeypatch
):
    """INV-C1:git 形态(自证删除)即使账本行不在发现集,缺席机也零介入 ——
    #82 收缩的成员对账是 git 退休唯一通道,无第二退休语义。"""
    from scripts.sync import _reconcile_source_absence

    connector = _GitShapeConnector()
    result = _reconcile_source_absence(SRC, connector, MagicMock(), sync_run_id=None)
    assert result["complete"] is False
    assert result["confirmed"] == []
    assert result["candidates"] == []
    assert result["policy_absent"] == []
    assert result["restored"] == []
    # 账本行零变更:缺席状态从未写入
    assert _absence_of(sync_factory, DOC) is None
    assert _row_of(sync_factory, DOC).lifecycle == "active"


async def test_c2_policy_absence_two_rounds_freeze_then_strikes_start_from_zero(
    sync_factory, monkeypatch
):
    """INV-C2:scope 收缩(政策范围外)连续两轮完整发现缺席 → 不退休、计数
    恒 0;解除政策原因后真实缺席两轮才退休 —— 政策轮不垫底。"""
    # 两轮:文档缺席且被分类为政策范围外
    connector = _FsShapeConnector(listing=(), policy_reason="branch-narrowed-u82")
    await _run_sync(sync_factory, connector, monkeypatch, n_times=2)
    row = _row_of(sync_factory, DOC)
    assert row.lifecycle == "missing_candidate", (
        "政策范围外缺席入宽限呈现( Needs Attention),但绝不确认为退休(A-3)"
    )
    absence = _absence_of(sync_factory, DOC)
    assert absence is not None
    assert absence["confirmations"] == 0, "政策缺席不计入确认计数"
    assert absence["policy_reason"] == "branch-narrowed-u82"

    # 解除政策原因(重新纳入范围)但文档仍缺席:两轮真实缺席 → 第二轮退休
    in_scope_gone = _FsShapeConnector(listing=(), policy_reason=None)
    await _run_sync(sync_factory, in_scope_gone, monkeypatch, n_times=1)
    row = _row_of(sync_factory, DOC)
    assert row.lifecycle == "missing_candidate", "第一次范围内缺席 = 宽限候选"
    await _run_sync(sync_factory, in_scope_gone, monkeypatch, n_times=1)
    row = _row_of(sync_factory, DOC)
    assert row.lifecycle == "deleted", "两次连续范围内完整发现缺席 → RETIRED"


async def test_c3_reexpansion_inclusion_restores_candidate_in_one_round(
    sync_factory, monkeypatch
):
    """INV-C3:一次确认候选(missing_candidate)重新进入权威清单
    (#82 扩大/补灌方向物化后)→ 单轮同步恢复 active + 缺席状态清除。"""
    connector = _FsShapeConnector(listing=(), policy_reason=None)
    await _run_sync(sync_factory, connector, monkeypatch, n_times=1)
    row = _row_of(sync_factory, DOC)
    assert row.lifecycle == "missing_candidate"

    # 权威清单重新包含(补灌方向:listing 恢复)
    back = _FsShapeConnector(listing=(DOC,), policy_reason=None)
    await _run_sync(sync_factory, back, monkeypatch, n_times=1)
    row = _row_of(sync_factory, DOC)
    assert row.lifecycle == "active", "重新出现 → 恢复 serving"
    assert _absence_of(sync_factory, DOC) is None, "恢复时缺席状态清除"
    assert row.deleted_at is None
