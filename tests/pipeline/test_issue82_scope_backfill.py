"""Issue #82 sync 面回归:authority−ledger 补灌方向 + 计数真值。

生产事实(ne301-local,2026-09-15 只读取证)驱动的三条契约:

1. 「未变更 N 篇」等现役口径必须排除墓碑行(5534 = 5379 在服 + 155 已退休,
   旧实现把墓碑计入 → 假真值);
2. 成员对账新增 authority−ledger 方向:配置范围内却不在服的成员(分支
   scope 扩大后新纳入的既有内容 / 墓碑后重回权威)必须被上报并经既有
   ingest 路径定向补灌 —— 「无 Git diff」绝不掩盖 membership scope 变化;
3. 补灌是真实新增:SyncLog items_new / delta new_count 如实呈现,绝不伪装
   「无变更」;unchanged 桶不重复计入被补灌重建的成员。

零外网:connector 全 stub;账本用共享测试库(TEST_DATABASE_URL),
SRC 前缀隔离,前后清理。
"""

from __future__ import annotations

import hashlib
import os
import sys
import uuid
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
from backend.services.membership_currency import reconcile_membership

pytestmark = pytest.mark.asyncio(loop_scope="session")

SRC = "issue82-backfill-local"
HEALTHY = f"{SRC}/main/docs/overview.md"
NEW_MEMBER = f"{SRC}/halow/docs/halow-knowledge.md"
RETURNED = f"{SRC}/main/docs/returned.md"
GONE = f"{SRC}/main/docs/gone.md"


def _uuid4():
    import uuid

    return uuid.uuid4()


def _hash(x: str) -> str:
    return hashlib.sha256(x.encode()).hexdigest()


def _raw_doc(source_id: str) -> RawDocument:
    return RawDocument(
        source_id=source_id,
        source_type="github",
        product="wiki",
        title=source_id.rsplit("/", 1)[-1],
        content=f"content of {source_id}",
        url=f"https://github.com/example/blob/main/{source_id}",
        metadata={"path": source_id},
        content_hash=_hash(source_id),
        branch=source_id.split("/")[1],
    )


# --------------------------------------------------------------------------- #
# harness(与 test_sync_membership 同法:registry stub + 真实账本)
# --------------------------------------------------------------------------- #


@dataclass
class _Report:
    """verify_source_vectors stub payload."""

    expected_chunks: int = 10
    actual_chunks: int = 10
    missing_source_ids: list = field(default_factory=list)
    refill_source_ids: list = field(default_factory=list)
    orphan_count: int = 0
    orphan_chunks: dict = field(default_factory=dict)
    stale_chunk_count: int = 0
    is_healthy: bool = True


class _StubBuilder:
    """GenerationBuilder stand-in:记录调用,返回受控 BuildAccounting。"""

    def __init__(self, new_docs: list[str] | None = None) -> None:
        self._new_docs = new_docs or []
        self.calls: list[tuple[list[RawDocument], bool]] = []

    def build_generation(self, docs, *, source_id, force_rebuild=False, progress=None):
        from backend.pipeline.generation_builder import BuildAccounting

        self.calls.append((list(docs), force_rebuild))
        return BuildAccounting(
            source_id=source_id,
            new_docs=list(self._new_docs) if docs else [],
            chunks_written=2 * len(docs),
        )

    def repair_documents(self, doc_ids, *, source_id_scope=None):  # pragma: no cover
        return ([], [], 0)


class _Connector:
    """增量零产出(SHA 短路);成员全集含账本缺失成员;fetch_all 可供补灌。"""

    def __init__(
        self,
        members: set[str],
        full_docs: list[RawDocument] | None = None,
    ) -> None:
        self._members = members
        self._full_docs = full_docs or []

    def membership_source_ids(self) -> set[str]:
        return set(self._members)

    def fetch_all(self):
        return iter(self._full_docs)

    def fetch_changes(self, since):
        return iter([])

    def fetch_deleted(self, since):
        return []


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


def _mk_doc(session, source_id: str, lifecycle: str) -> Document:
    doc = Document(
        source_id=source_id,
        source_type="github",
        product="wiki",
        title=source_id.rsplit("/", 1)[-1],
        url=f"https://github.com/example/blob/main/{source_id}",
        branch=source_id.split("/")[1],
        chunk_count=8,
        content_hash=_hash(source_id),
        lifecycle=lifecycle,
    )
    session.add(doc)
    if lifecycle in DocLifecycle.SERVING:
        version = DocumentVersion(
            id=_uuid4(),
            source_id=source_id,
            version_seq=1,
            content_hash=doc.content_hash,
            metadata_hash=_hash("m" + source_id),
            generation_id="00000000-0000-0000-0000-000000000000",
            generation_ordinal=0,
            status="active",
            title=doc.title,
            url=doc.url,
            chunk_count=8,
        )
        session.add(version)
        doc.current_version_id = version.id
    return doc


_CURRENT: dict = {"connector": None}


@pytest.fixture(autouse=True)
def _stub_registry(monkeypatch):
    monkeypatch.setattr(
        sync_mod.ConnectorRegistry, "create", lambda cfg: _CURRENT["connector"]
    )
    yield
    _CURRENT["connector"] = None


@pytest.fixture
def healthy_report(monkeypatch):
    report = _Report()
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        sync_mod, "verify_source_vectors", AsyncMock(return_value=report), raising=True
    )
    return report


@pytest_asyncio.fixture(loop_scope="session")
async def db_engine():
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
    import sqlalchemy

    dsn = os.environ.get("TEST_DATABASE_URL", load_settings().postgres_dsn)
    engine = sqlalchemy.create_engine(dsn.replace("+asyncpg", "+psycopg2"))
    try:
        yield sqlalchemy.orm.sessionmaker(bind=engine)
    finally:
        engine.dispose()


async def _seed(db_engine, docs: list[tuple[str, str]]) -> None:
    factory = get_session_factory(db_engine)
    async with factory() as session:
        session.add(DataSource(id=SRC, type="github", product="wiki", config={}))
        for sid, lifecycle in docs:
            _mk_doc(session, sid, lifecycle)
        await session.commit()


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
            items_new=row.items_new,
            items_unchanged=row.items_unchanged,
            delta_counts=dict(row.delta_counts or {}),
            error_detail=row.error_detail,
        )


# --------------------------------------------------------------------------- #
# 1. 计数真值:墓碑不入现役口径(#82 验收)
# --------------------------------------------------------------------------- #


async def test_count_documents_excludes_tombstoned_rows(db_engine):
    """`_count_documents` 只统计 SERVING 行(active/missing_candidate)。

    生产反例:ne301-local 报「未变更 5534 篇」实为 5379 在服 + 155 已墓碑
    (2026-09-15 对账退休)。旧实现无 lifecycle 过滤 → 假真值。
    """
    factory = get_session_factory(db_engine)
    await _seed(
        db_engine,
        [
            (HEALTHY, DocLifecycle.ACTIVE),
            (f"{SRC}/main/docs/grace.md", DocLifecycle.MISSING_CANDIDATE),
            (GONE, DocLifecycle.DELETED),
            (f"{SRC}/main/docs/old-gen.md", DocLifecycle.SUPERSEDED),
            (f"{SRC}/main/docs/discovered.md", DocLifecycle.DISCOVERED),
        ],
    )
    assert await sync_mod._count_documents(factory, SRC) == 2


# --------------------------------------------------------------------------- #
# 2. 无变更轮的 authority−ledger 补灌(#82 核心语义)
# --------------------------------------------------------------------------- #


async def test_no_change_round_backfills_missing_authority_members(
    db_engine, sync_factory, healthy_report
):
    """分支 scope 扩大后 SHA 恒等 + 内容早于窗口 ⇒ 增量零产出,但成员对账
    必须看到缺失成员并经既有 ingest 路径(force_rebuild,激活路径内置墓碑
    撤销)定向补灌;轮次如实记新增,绝不伪装「无变更」。"""
    factory = get_session_factory(db_engine)
    await _seed(db_engine, [(HEALTHY, DocLifecycle.ACTIVE)])
    connector = _Connector(
        members={HEALTHY, NEW_MEMBER},  # 权威全集含 halow 新纳入分支
        full_docs=[_raw_doc(NEW_MEMBER)],
    )
    _CURRENT["connector"] = connector
    builder = _StubBuilder(new_docs=[NEW_MEMBER])

    result = await sync_mod._sync_one(
        _cfg(),
        _Pipeline(sync_factory),
        factory,
        triggered_by="manual",
        builder=builder,
    )
    assert result is not True  # no-change 路径不携带传输失败语义

    # 补灌走了既有 ingest 路径:fetch_all 过滤 + force_rebuild(墓碑撤销语义)
    assert len(builder.calls) == 1
    docs, force_rebuild = builder.calls[0]
    assert [d.source_id for d in docs] == [NEW_MEMBER]
    assert force_rebuild is True

    log = await _latest_sync_log(factory)
    assert log.status == "success"
    assert log.items_new == 1, "补灌必须记为真实新增,而不是「无变更」"
    assert log.items_unchanged == 1, "unchanged 只含原本就在服的成员"
    assert log.delta_counts["new_count"] == 1
    assert log.delta_counts["unchanged_count"] == 1
    assert log.delta_counts["membership_backfilled"] == 1
    assert log.delta_counts["membership_missing"] == 1
    assert log.delta_counts["membership_status"] == "current"


async def test_no_change_round_without_missing_keeps_true_nochange_fast_path(
    db_engine, sync_factory, healthy_report
):
    """控制(Acceptance 3):账本 ⊆ 权威且无缺口 ⇒ 零抓取零构建,
    真 no-change fast path 分毫不变。"""
    factory = get_session_factory(db_engine)
    await _seed(db_engine, [(HEALTHY, DocLifecycle.ACTIVE)])
    connector = _Connector(members={HEALTHY}, full_docs=[])
    _CURRENT["connector"] = connector
    builder = _StubBuilder()

    await sync_mod._sync_one(
        _cfg(),
        _Pipeline(sync_factory),
        factory,
        triggered_by="cron",
        builder=builder,
    )
    assert builder.calls == []  # 零补灌构建
    log = await _latest_sync_log(factory)
    assert log.status == "success"
    assert log.items_new == 0
    assert log.delta_counts["unchanged_count"] == 1
    assert "membership_backfilled" not in log.delta_counts


# --------------------------------------------------------------------------- #
# 3. 对账服务上报缺失成员(墓碑后重回权威 / 从未灌入)
# --------------------------------------------------------------------------- #


async def test_reconcile_reports_missing_including_tombstoned_authority_member(
    db_engine, sync_factory
):
    """authority−ledger 方向:缺失 = 权威 − 在服。覆盖两类:从未灌入(docC)
    与墓碑后重回权威(docB —— 上游删除后重新出现,应经补灌撤销墓碑);
    retirement 方向(docA)语义不变。"""
    await _seed(
        db_engine,
        [
            (GONE, DocLifecycle.ACTIVE),  # 已退出权威 → stale(退休方向)
            (RETURNED, DocLifecycle.DELETED),  # 墓碑但仍在权威 → missing(补灌方向)
        ],
    )
    connector = _Connector(members={RETURNED, NEW_MEMBER})
    result = reconcile_membership(
        sync_factory, connector, SRC, reason="issue82:test"
    )
    assert result.status == "completed"
    assert set(result.stale_ids) == {GONE}
    assert result.retired == 1
    assert set(result.missing_ids) == {RETURNED, NEW_MEMBER}
    # 本服务只对账不灌入:墓碑行保持 DELETED,由调用方经 ingest 路径恢复
    with sync_factory() as session:
        row = (
            session.execute(select(Document).where(Document.source_id == RETURNED))
            .scalar_one()
        )
        assert row.lifecycle == DocLifecycle.DELETED


# --------------------------------------------------------------------------- #
# 4. Role A 验收面(2026-09-16 批准)
# --------------------------------------------------------------------------- #


class _LedgerWritingBuilder:
    """以最小账本语义模拟 build_generation 的激活面:upsert 在服 Document 行。

    用于不变量集成断言(AUTHORITY == LEDGER SERVING):真实 build_generation
    的激活事务会写账本;stub 不写则不变量无从谈起。仅最小等价 —— 新成员
    建行、已存在行恢复 SERVING(墓碑撤销的最小语义,与
    activate_document_version 的恢复方向一致)。
    """

    def __init__(self, session_factory) -> None:
        self._f = session_factory
        self.built: list[str] = []

    def build_generation(self, docs, *, source_id, force_rebuild=False, progress=None):
        from backend.pipeline.generation_builder import BuildAccounting

        new_ids: list[str] = []
        with self._f() as session:
            for d in docs:
                self.built.append(d.source_id)
                row = (
                    session.execute(
                        select(Document).where(Document.source_id == d.source_id)
                    )
                    .scalar_one_or_none()
                )
                if row is None:
                    new_ids.append(d.source_id)
                    _mk_doc(session, d.source_id, DocLifecycle.ACTIVE)
                elif row.lifecycle not in DocLifecycle.SERVING:
                    row.lifecycle = DocLifecycle.ACTIVE
            session.commit()
        return BuildAccounting(
            source_id=source_id,
            new_docs=new_ids,
            chunks_written=2 * len(docs),
        )


async def test_expansion_backfill_does_not_rebuild_current_members(
    db_engine, sync_factory, healthy_report
):
    """Role A 验收 2:「仅补灌新增 scope」—— scope 扩张轮,已 current 成员
    不得被重复摄取/重建。fetch_all 返回完整权威全集(含已 current 成员),
    断言构建批次只含缺失成员。"""
    factory = get_session_factory(db_engine)
    await _seed(db_engine, [(HEALTHY, DocLifecycle.ACTIVE)])
    connector = _Connector(
        members={HEALTHY, NEW_MEMBER},
        full_docs=[_raw_doc(NEW_MEMBER), _raw_doc(HEALTHY)],  # 全集,含已 current
    )
    _CURRENT["connector"] = connector
    builder = _LedgerWritingBuilder(sync_factory)

    await sync_mod._sync_one(
        _cfg(),
        _Pipeline(sync_factory),
        factory,
        triggered_by="manual",
        builder=builder,
    )
    assert builder.built == [NEW_MEMBER], (
        f"scope 扩张只补缺失成员;实际构建了: {builder.built}"
    )
    log = await _latest_sync_log(factory)
    assert log.status == "success"
    assert log.delta_counts["membership_backfilled"] == 1
    # 已 current 成员的账本行原样保留(无重建/重激活副作用)
    with sync_factory() as session:
        row = (
            session.execute(select(Document).where(Document.source_id == HEALTHY))
            .scalar_one()
        )
        assert row.lifecycle == DocLifecycle.ACTIVE


async def test_post_sync_invariant_authority_equals_serving_ledger(
    db_engine, sync_factory, healthy_report
):
    """Role A 验收 3:同步成功后 AUTHORITY == LEDGER MEMBERSHIP TRUTH ==
    CURRENT SERVING SCOPE(非退休账本成员集合 == 权威成员集合),且权威
    对账复检零 stale、零 missing、零 residual。"""
    factory = get_session_factory(db_engine)
    await _seed(db_engine, [(HEALTHY, DocLifecycle.ACTIVE)])
    authority = {HEALTHY, NEW_MEMBER}
    connector = _Connector(
        members=authority,
        full_docs=[_raw_doc(NEW_MEMBER), _raw_doc(HEALTHY)],
    )
    _CURRENT["connector"] = connector
    builder = _LedgerWritingBuilder(sync_factory)

    await sync_mod._sync_one(
        _cfg(),
        _Pipeline(sync_factory),
        factory,
        triggered_by="manual",
        builder=builder,
    )
    log = await _latest_sync_log(factory)
    assert log.status == "success"

    # AUTHORITY == 账本在服成员(非退休)
    with sync_factory() as session:
        serving = {
            str(sid)
            for (sid,) in session.execute(
                select(Document.source_id).where(
                    Document.source_id.like(f"{SRC}/%"),
                    Document.lifecycle.in_(DocLifecycle.SERVING),
                )
            )
        }
    assert serving == authority, (
        f"同步后不变量破坏: authority={sorted(authority)} serving={sorted(serving)}"
    )
    # 复检:权威对账零缺口(两方向同时收敛)
    result = reconcile_membership(sync_factory, connector, SRC, reason="issue82:invariant")
    assert result.stale_ids == ()
    assert result.missing_ids == ()
    assert result.residual_ids == ()
    assert result.status == "completed"
