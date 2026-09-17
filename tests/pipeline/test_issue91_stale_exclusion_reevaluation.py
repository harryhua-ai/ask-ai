"""Issue #91 Role A REVIEW_2:陈旧排除的失效/重评估语义(P0 blocker 回归)。

Blocker(旧实现,a2b61ec):对账按 source_id **无界**压制 ——
同身份内容变更(不安全 → 安全)后,陈旧排除仍压制 missing ⇒ 永不重取 ⇒
builder 永无重判机会 ⇒ 合法权威内容永久缺席服务。

契约语义(两层级,防 GPU 循环复活):
- Tier 1(即时):builder 对任何到达它的内容**永远重跑现行政策**,
  本表只是记账绝不是门 —— 增量路径的内容变更即刻重判;
- Tier 2(有界兜底):对账压制仅窗口内有效(7 天,自 last_confirmed_at);
  过期身份重回 missing ⇒ 补灌重取 ⇒ 重判。同内容不安全 = 刷新确认
  (压制重启,零嵌入);内容变更 = 按事实处置(安全=激活+清登记);
  政策/规则演进由此获得确定性重评估路径。

三循环主序列(本文件核心):排除 → 内容变安全(过期后)→ 重评估激活
→ 真 no-change 零重嵌。真实 sync 编排 + 真实 builder/Weaviate,连接器 stub。
"""

from __future__ import annotations

import hashlib
import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
import weaviate
from sqlalchemy import delete, select, text

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import scripts.sync as sync_mod
from backend.connectors.base import RawDocument
from backend.connectors.registry import SourceConfig
from backend.db.models import (
    DataSource,
    Document,
    DocumentVersion,
    IndexGeneration,
    IngestionExclusion,
    SyncLog,
    SyncRun,
)
from backend.db.session import get_engine, get_session_factory, init_db
from backend.services.document_lifecycle import DocLifecycle

pytestmark = pytest.mark.asyncio(loop_scope="session")

# 压制窗口 = 7 天(backend.services.ingestion_exclusions 常量);回拨 8 天
# 即越过窗口(测试对实现形状无依赖,不 import 服务模块以保持 RED 可运行)。
EXPIRED_DELTA = timedelta(days=8)

TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test",
)
WEAVIATE_PORT = int(os.environ.get("P1_WEAVIATE_PORT", "8080"))
CLASS_NAME = "I91StaleProbe"

SRC = "i91stale-local"
OK1 = f"{SRC}/main/docs/overview.md"
FLIP = f"{SRC}/main/etc/credentials.txt"
POLICY_GONE = f"{SRC}/main/fw/old-artifact.mbin"

UNSAFE_CONTENT = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow fake\n-----END RSA PRIVATE KEY-----\n"
SAFE_CONTENT = "# credentials guide\n\nhow to rotate credentials safely.\n\nsecond paragraph for chunking.\n\nthird paragraph.\n\nfourth paragraph.\n\n"


def _hash(x: str) -> str:
    return hashlib.sha256(x.encode()).hexdigest()


def _raw_doc(source_id: str, content: str) -> RawDocument:
    return RawDocument(
        source_id=source_id,
        source_type="github",
        product="wiki",
        title=source_id.rsplit("/", 1)[-1],
        content=content,
        url=f"https://github.com/example/blob/{source_id}",
        metadata={"path": source_id},
        content_hash=_hash(content),
        branch=source_id.split("/")[1],
    )


@dataclass
class _Report:
    expected_chunks: int = 10
    actual_chunks: int = 10
    missing_source_ids: list = field(default_factory=list)
    refill_source_ids: list = field(default_factory=list)
    orphan_count: int = 0
    orphan_chunks: dict = field(default_factory=dict)
    stale_chunk_count: int = 0
    is_healthy: bool = True


class _Connector:
    DECLARES_DELETIONS = True

    def __init__(self, members: set[str], full_docs: list[RawDocument]) -> None:
        self._members = members
        self._full_docs = full_docs

    def membership_source_ids(self) -> set[str]:
        return set(self._members)

    def fetch_all(self):
        return iter(list(self._full_docs))

    def fetch_changes(self, since):
        return iter([])

    def fetch_deleted(self, since):
        return []


class _FingerprintConnector(_Connector):
    """REVIEW_3:具备权威内容指纹能力的连接器(github 同构,窄面)。

    ``membership_content_fingerprints(ids)`` 返回给定身份的当前权威内容
    sha256(与 RawDocument.content_hash 同变换)。无能力的连接器不实现
    该方法 —— 对账按 Tier 2 窗口兜底。
    """

    def __init__(self, members, full_docs, fingerprints: dict[str, str]) -> None:
        super().__init__(members, full_docs)
        self._fingerprints = fingerprints
        self.fingerprint_queries: list[list[str]] = []

    def membership_content_fingerprints(self, source_ids):
        ids = list(source_ids)
        self.fingerprint_queries.append(ids)
        return {sid: fp for sid, fp in self._fingerprints.items() if sid in set(ids)}


class _FakeEmbedder:
    dimension = 8

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.fail = False

    def embed(self, texts):
        if self.fail:
            raise RuntimeError("fake embedder boom")
        self.calls.append(list(texts))
        return [[0.1] * self.dimension for _ in texts]


def _uuid4():
    return uuid.uuid4()


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


def _make_weaviate_client():
    try:
        client = weaviate.connect_to_local("localhost", WEAVIATE_PORT)
    except Exception:  # noqa: BLE001
        pytest.skip(f"local Weaviate 不可达(port={WEAVIATE_PORT})")
    if client.collections.exists(CLASS_NAME):
        client.collections.delete(CLASS_NAME)
    return client


@pytest_asyncio.fixture(loop_scope="session")
async def db_engine():
    engine = get_engine(TEST_DSN)
    try:
        await init_db(engine)
        from scripts.migrate_add_membership_currency import migrate as _migrate

        await _migrate(engine)
        from scripts.migrate_add_ingestion_exclusions import migrate as _excl
        from scripts.migrate_widen_document_source_id_500 import migrate as _widen

        await _excl(engine)
        await _widen(engine)
        yield engine
    finally:
        f = get_session_factory(engine)
        async with f() as session:
            for model, col in ((SyncRun, SyncRun.source_id), (SyncLog, SyncLog.source_id)):
                await session.execute(delete(model).where(col == SRC))
            await session.execute(delete(Document).where(Document.source_id.like(f"{SRC}/%")))
            await session.execute(
                delete(DocumentVersion).where(DocumentVersion.source_id.like(f"{SRC}/%"))
            )
            await session.execute(delete(IndexGeneration).where(IndexGeneration.source_id == SRC))
            await session.execute(delete(DataSource).where(DataSource.id == SRC))
            await session.execute(
                delete(IngestionExclusion).where(IngestionExclusion.source_id.like(f"{SRC}/%"))
            )
            await session.commit()
        await engine.dispose()


@pytest.fixture
def sync_factory(db_engine):
    import sqlalchemy

    engine = sqlalchemy.create_engine(TEST_DSN.replace("+asyncpg", "+psycopg2"))
    try:
        yield sqlalchemy.orm.sessionmaker(bind=engine, expire_on_commit=False)
    finally:
        engine.dispose()


def _real_stack(sync_factory):
    from backend.pipeline.generation_builder import GenerationBuilder
    from backend.pipeline.ingest import IngestionPipeline

    client = _make_weaviate_client()
    embedder = _FakeEmbedder()
    pipeline = IngestionPipeline(
        embedder,
        client,
        class_name=CLASS_NAME,
        max_tokens=40,
        overlap=0,
        session_factory=sync_factory,
        max_chunk_chars=2000,
    )
    builder = GenerationBuilder(pipeline, sync_factory)
    return SimpleNamespace(
        client=client, embedder=embedder, pipeline=pipeline, builder=builder
    )


def _cfg() -> SourceConfig:
    return SourceConfig(
        id=SRC,
        type="github",
        product="wiki",
        enabled=True,
        config={},
        sync_interval="24h",
    )


def _embedded_texts(stack) -> list[str]:
    return [t for batch in stack.embedder.calls for t in batch]


async def _seed_active(db_engine, source_id: str) -> None:
    factory = get_session_factory(db_engine)
    async with factory() as session:
        session.add(DataSource(id=SRC, type="github", product="wiki", config={}))
        doc = Document(
            source_id=source_id,
            source_type="github",
            product="wiki",
            title=source_id.rsplit("/", 1)[-1],
            url=f"https://github.com/example/blob/{source_id}",
            branch="main",
            chunk_count=4,
            content_hash=_hash(source_id),
            lifecycle=DocLifecycle.ACTIVE,
        )
        session.add(doc)
        session.add(
            DocumentVersion(
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
                chunk_count=4,
            )
        )
        doc.current_version_id = None
        await session.commit()


async def _latest_sync_log(db_engine) -> SyncLog:
    factory = get_session_factory(db_engine)
    async with factory() as session:
        row = (
            await session.execute(
                select(SyncLog)
                .where(SyncLog.source_id == SRC)
                .order_by(SyncLog.started_at.desc())
                .limit(1)
            )
        ).scalar_one()
        session.expunge(row)
        return row


async def _serving_ids(db_engine) -> set[str]:
    factory = get_session_factory(db_engine)
    async with factory() as session:
        rows = (
            await session.execute(
                select(Document.source_id).where(
                    Document.source_id.like(f"{SRC}/%"),
                    Document.lifecycle.in_(DocLifecycle.SERVING),
                )
            )
        ).all()
    return {str(r[0]) for r in rows}


async def _expire_exclusions(db_engine, source_ids: set[str]) -> None:
    """把指定身份的排除登记回拨出压制窗口(模拟窗口流逝)。"""
    factory = get_session_factory(db_engine)
    stale_ts = datetime.now(UTC) - EXPIRED_DELTA
    async with factory() as session:
        for sid in source_ids:
            await session.execute(
                text(
                    "UPDATE ingestion_exclusions SET last_confirmed_at = :ts "
                    "WHERE source_id = :sid"
                ),
                {"ts": stale_ts, "sid": sid},
            )
        await session.commit()


async def _exclusion_row(db_engine, source_id: str):
    factory = get_session_factory(db_engine)
    async with factory() as session:
        row = (
            await session.execute(
                select(IngestionExclusion).where(IngestionExclusion.source_id == source_id)
            )
        ).scalar_one_or_none()
        if row is not None:
            session.expunge(row)
        return row


# --------------------------------------------------------------------------- #
# Role A REVIEW_2 主序列:三循环
# --------------------------------------------------------------------------- #


async def test_stale_exclusion_cycle2_reevaluates_changed_content(
    db_engine, sync_factory, healthy_report
):
    """循环1 排除;循环2 内容变安全 → 陈旧排除不得压制重评估 → 激活+清登记;
    循环3 真 no-change 零重嵌。旧实现:循环2 missing 被无界压制 ⇒ 永缺席。"""
    stack = _real_stack(sync_factory)
    factory = get_session_factory(db_engine)
    await _seed_active(db_engine, OK1)

    # ---- 循环 1:不安全内容 → 永久排除、不入服、登记持久化 ----
    _CURRENT["connector"] = _Connector(
        members={OK1, FLIP}, full_docs=[_raw_doc(FLIP, UNSAFE_CONTENT)]
    )
    await sync_mod._sync_one(
        _cfg(), stack.pipeline, factory, triggered_by="manual", builder=stack.builder
    )
    log1 = await _latest_sync_log(db_engine)
    assert log1.status == "success"
    assert FLIP not in await _serving_ids(db_engine), "不安全内容不入服"
    row1 = await _exclusion_row(db_engine, FLIP)
    assert row1 is not None and row1.content_hash == _hash(UNSAFE_CONTENT), (
        "排除登记持久化"
    )
    confirm_count_1 = row1.times_confirmed

    # ---- 循环 2:同身份权威内容变为安全(压制窗口已过)----
    # 旧实现:missing 被无界压制 → 永不重取 → 永缺席(本测试的 RED 点)。
    await _expire_exclusions(db_engine, {FLIP})
    _CURRENT["connector"] = _Connector(
        members={OK1, FLIP}, full_docs=[_raw_doc(FLIP, SAFE_CONTENT)]
    )
    await sync_mod._sync_one(
        _cfg(), stack.pipeline, factory, triggered_by="manual", builder=stack.builder
    )
    log2 = await _latest_sync_log(db_engine)
    assert log2.status == "success", f"循环2 必须收敛: {log2.error_detail[:200]}"
    serving = await _serving_ids(db_engine)
    assert FLIP in serving, (
        "陈旧排除不得压制重评估:内容变安全后必须重取、重判、激活"
        "(旧实现:永久缺席 —— P0 blocker)"
    )
    assert await _exclusion_row(db_engine, FLIP) is None, "激活必须清除陈旧排除登记"
    # 重评估是真实激活:安全内容被嵌入入账
    assert any("credentials guide" in t for t in _embedded_texts(stack)), (
        "重评估必须真实抓取并嵌入安全内容"
    )

    # ---- 循环 3:一切未变 → 真 no-change、零重嵌、零 actionable missing ----
    embedded_before = len(_embedded_texts(stack))
    _CURRENT["connector"] = _Connector(
        members={OK1, FLIP},
        full_docs=[_raw_doc(FLIP, SAFE_CONTENT), _raw_doc(OK1, f"content of {OK1}")],
    )
    await sync_mod._sync_one(
        _cfg(), stack.pipeline, factory, triggered_by="cron", builder=stack.builder
    )
    log3 = await _latest_sync_log(db_engine)
    assert log3.status == "success"
    delta3 = dict(log3.delta_counts or {})
    assert delta3.get("membership_missing", 0) == 0, "零 actionable missing"
    assert len(_embedded_texts(stack)) == embedded_before, "循环3 零重复嵌入"
    assert FLIP in await _serving_ids(db_engine)
    stack.client.close()
    _ = confirm_count_1


async def test_expired_exclusion_same_unsafe_content_reconfirmed_without_embedding(
    db_engine, sync_factory, healthy_report
):
    """窗口过期 + 内容仍旧不安全:重评估只做抓取+安全扫描(登记刷新,压制
    重启),零嵌入、不入服 —— 有界重评估绝不复活 GPU 循环。"""
    stack = _real_stack(sync_factory)
    factory = get_session_factory(db_engine)
    await _seed_active(db_engine, OK1)

    _CURRENT["connector"] = _Connector(
        members={OK1, FLIP}, full_docs=[_raw_doc(FLIP, UNSAFE_CONTENT)]
    )
    await sync_mod._sync_one(
        _cfg(), stack.pipeline, factory, triggered_by="manual", builder=stack.builder
    )
    row1 = await _exclusion_row(db_engine, FLIP)
    assert row1 is not None
    confirm1 = row1.times_confirmed
    embedded_before = len(_embedded_texts(stack))

    # 窗口过期,内容不变:重评估 → 重确认
    await _expire_exclusions(db_engine, {FLIP})
    _CURRENT["connector"] = _Connector(
        members={OK1, FLIP}, full_docs=[_raw_doc(FLIP, UNSAFE_CONTENT)]
    )
    await sync_mod._sync_one(
        _cfg(), stack.pipeline, factory, triggered_by="manual", builder=stack.builder
    )
    log = await _latest_sync_log(db_engine)
    assert log.status == "success"
    row2 = await _exclusion_row(db_engine, FLIP)
    assert row2 is not None, "同内容不安全:登记必须保留(重确认)"
    assert row2.times_confirmed == confirm1 + 1, "重确认计数递增"
    assert row2.last_confirmed_at > row1.last_confirmed_at, "压制窗口重启"
    assert FLIP not in await _serving_ids(db_engine), "不安全内容依旧不入服"
    assert len(_embedded_texts(stack)) == embedded_before, "重评估零嵌入(不复活 GPU 循环)"
    stack.client.close()


async def test_policy_evolution_reevaluates_previously_excluded_identity(
    db_engine, sync_factory, healthy_report, monkeypatch
):
    """政策/规则演进:同身份同内容曾被排除,窗口过期后按**现行政策**重判 ——
    判定放宽 ⇒ 正常激活 + 清登记(有界确定性重评估,而非永久压制)。"""
    stack = _real_stack(sync_factory)
    factory = get_session_factory(db_engine)
    await _seed_active(db_engine, OK1)

    _CURRENT["connector"] = _Connector(
        members={OK1, FLIP}, full_docs=[_raw_doc(FLIP, UNSAFE_CONTENT)]
    )
    await sync_mod._sync_one(
        _cfg(), stack.pipeline, factory, triggered_by="manual", builder=stack.builder
    )
    assert await _exclusion_row(db_engine, FLIP) is not None
    assert FLIP not in await _serving_ids(db_engine)

    # 模拟政策演进(现行政策放宽):重评估轮的判定面返回 safe
    from backend.connectors.safety import SafetyVerdict

    class _RelaxedPolicy:
        def check_content(self, content):
            return SafetyVerdict(True)

    monkeypatch.setattr(stack.pipeline, "_safety", _RelaxedPolicy())

    await _expire_exclusions(db_engine, {FLIP})
    _CURRENT["connector"] = _Connector(
        members={OK1, FLIP}, full_docs=[_raw_doc(FLIP, UNSAFE_CONTENT)]
    )
    await sync_mod._sync_one(
        _cfg(), stack.pipeline, factory, triggered_by="manual", builder=stack.builder
    )
    log = await _latest_sync_log(db_engine)
    assert log.status == "success"
    assert FLIP in await _serving_ids(db_engine), "政策放宽后重评估必须可入库"
    assert await _exclusion_row(db_engine, FLIP) is None, "重判通过 ⇒ 登记清除"
    stack.client.close()


async def test_incremental_content_change_bypasses_suppression_immediately(
    db_engine, sync_factory, healthy_report
):
    """Tier 1(即时):内容变更经增量路径到达 builder ⇒ 无论窗口是否过期,
    现行政策即刻重判;安全 ⇒ 激活 + 清登记(fresh 排除行也被自愈)。"""
    stack = _real_stack(sync_factory)
    factory = get_session_factory(db_engine)
    await _seed_active(db_engine, OK1)

    _CURRENT["connector"] = _Connector(
        members={OK1, FLIP}, full_docs=[_raw_doc(FLIP, UNSAFE_CONTENT)]
    )
    await sync_mod._sync_one(
        _cfg(), stack.pipeline, factory, triggered_by="manual", builder=stack.builder
    )
    assert await _exclusion_row(db_engine, FLIP) is not None

    # 增量路径:fetch_changes 直接送来变更后的安全内容(窗口未过期)
    class _IncrementalConnector(_Connector):
        def fetch_changes(self, since):
            return iter([_raw_doc(FLIP, SAFE_CONTENT)])

    _CURRENT["connector"] = _IncrementalConnector(
        members={OK1, FLIP}, full_docs=[_raw_doc(FLIP, SAFE_CONTENT)]
    )
    await sync_mod._sync_one(
        _cfg(), stack.pipeline, factory, triggered_by="manual", builder=stack.builder
    )
    log = await _latest_sync_log(db_engine)
    assert log.status == "success"
    assert FLIP in await _serving_ids(db_engine), "即时重评估:内容变更即刻激活"
    assert await _exclusion_row(db_engine, FLIP) is None, "激活清除登记"
    stack.client.close()


async def test_reconcile_purges_expired_exclusions_out_of_authority(
    db_engine, sync_factory
):
    """卫生:窗口过期且身份已不在权威枚举 ⇒ 对账事务内清除登记(幂等);
    枚举内的过期行保留(它们是重评估请求)。"""
    factory = get_session_factory(db_engine)
    await _seed_active(db_engine, OK1)
    async with factory() as session:
        session.add(
            IngestionExclusion(
                source_id=POLICY_GONE,
                content_hash=_hash("x"),
                reason="binary_content",
                detail="d",
                stage="SAFETY_FILTER",
            )
        )
        session.add(
            IngestionExclusion(
                source_id=FLIP,
                content_hash=_hash(UNSAFE_CONTENT),
                reason="secret_content",
                detail="d",
                stage="SAFETY_FILTER",
            )
        )
        await session.commit()
    await _expire_exclusions(db_engine, {POLICY_GONE, FLIP})

    from backend.services.membership_currency import reconcile_membership

    connector = _Connector(members={OK1, FLIP}, full_docs=[])  # POLICY_GONE 已退出权威
    result = reconcile_membership(sync_factory, connector, SRC, reason="i91:purge")
    assert result.status == "completed"
    assert await _exclusion_row(db_engine, POLICY_GONE) is None, "越权过期登记被清除"
    assert await _exclusion_row(db_engine, FLIP) is not None, "枚举内过期行保留待重评估"


# --------------------------------------------------------------------------- #
# Role A REVIEW_3:同源内容变更立即失效压制(不等 TTL)
# --------------------------------------------------------------------------- #


async def test_immediate_content_change_reevaluation_without_ttl(
    db_engine, sync_factory, healthy_report
):
    """无任何人工过期:循环1 排除(A);循环2 同身份权威内容变为安全(B)
    ⇒ 指纹漂移立即失效压制 ⇒ 重取、重判、激活、清登记;循环3 真 no-change
    零重嵌。旧实现:7 天窗口内压制 ⇒ 永久缺席。"""
    stack = _real_stack(sync_factory)
    factory = get_session_factory(db_engine)
    await _seed_active(db_engine, OK1)

    # ---- 循环 1:X = 不安全内容(A)→ 排除持久化、不入服 ----
    safe_doc = _raw_doc(FLIP, SAFE_CONTENT)
    unsafe_doc = _raw_doc(FLIP, UNSAFE_CONTENT)
    connector = _FingerprintConnector(
        members={OK1, FLIP},
        full_docs=[unsafe_doc],
        fingerprints={},  # 排除发生前:无登记身份,对账不查指纹
    )
    _CURRENT["connector"] = connector
    await sync_mod._sync_one(
        _cfg(), stack.pipeline, factory, triggered_by="manual", builder=stack.builder
    )
    row1 = await _exclusion_row(db_engine, FLIP)
    assert row1 is not None and row1.content_hash == _hash(UNSAFE_CONTENT), (
        "循环1:排除(A)持久化"
    )
    assert FLIP not in await _serving_ids(db_engine)

    # ---- 循环 2(立即,无 TTL 等待):权威内容变为安全(B)----
    # 指纹漂移(A ≠ B)⇒ 陈旧排除必须立即失效 ⇒ X 重回 actionable missing
    # ⇒ 补灌重取 ⇒ 现行安全判定通过 ⇒ 激活 ⇒ 清登记 ⇒ 入服。
    connector = _FingerprintConnector(
        members={OK1, FLIP},
        full_docs=[safe_doc],
        fingerprints={FLIP: _hash(SAFE_CONTENT)},
    )
    _CURRENT["connector"] = connector
    await sync_mod._sync_one(
        _cfg(), stack.pipeline, factory, triggered_by="manual", builder=stack.builder
    )
    log2 = await _latest_sync_log(db_engine)
    assert log2.status == "success", f"循环2 必须收敛: {log2.error_detail[:200]}"
    assert FLIP in await _serving_ids(db_engine), (
        "内容变更(指纹漂移)必须立即失效压制并重评估激活"
        "(旧实现:TTL 窗口内永久缺席)"
    )
    assert await _exclusion_row(db_engine, FLIP) is None, "激活清除陈旧排除"
    assert any("credentials guide" in t for t in _embedded_texts(stack)), (
        "重评估真实抓取并嵌入安全内容"
    )

    # ---- 循环 3:一切未变 → 真 no-change、零重嵌、零 actionable missing ----
    embedded_before = len(_embedded_texts(stack))
    connector = _FingerprintConnector(
        members={OK1, FLIP},
        full_docs=[safe_doc],
        fingerprints={FLIP: _hash(SAFE_CONTENT)},
    )
    _CURRENT["connector"] = connector
    await sync_mod._sync_one(
        _cfg(), stack.pipeline, factory, triggered_by="cron", builder=stack.builder
    )
    log3 = await _latest_sync_log(db_engine)
    assert log3.status == "success"
    assert dict(log3.delta_counts or {}).get("membership_missing", 0) == 0
    assert len(_embedded_texts(stack)) == embedded_before, "循环3 零重复嵌入"
    stack.client.close()


async def test_fingerprint_match_keeps_suppression_without_reembed(
    db_engine, sync_factory, healthy_report
):
    """指纹一致(内容未变)+ 窗口内:压制保持、零补灌、零嵌入 —— 指纹机制
    绝不复活 GPU 循环。"""
    stack = _real_stack(sync_factory)
    factory = get_session_factory(db_engine)
    await _seed_active(db_engine, OK1)

    unsafe_doc = _raw_doc(FLIP, UNSAFE_CONTENT)
    _CURRENT["connector"] = _Connector(
        members={OK1, FLIP}, full_docs=[unsafe_doc]
    )
    await sync_mod._sync_one(
        _cfg(), stack.pipeline, factory, triggered_by="manual", builder=stack.builder
    )
    embedded_before = len(_embedded_texts(stack))

    connector = _FingerprintConnector(
        members={OK1, FLIP},
        full_docs=[unsafe_doc],
        fingerprints={FLIP: _hash(UNSAFE_CONTENT)},  # 指纹一致
    )
    _CURRENT["connector"] = connector
    await sync_mod._sync_one(
        _cfg(), stack.pipeline, factory, triggered_by="cron", builder=stack.builder
    )
    log = await _latest_sync_log(db_engine)
    assert log.status == "success"
    delta = dict(log.delta_counts or {})
    assert delta.get("membership_excluded", 0) == 1, "指纹一致 ⇒ 窗口内压制保持"
    assert "membership_backfilled" not in delta, "不补灌"
    assert len(_embedded_texts(stack)) == embedded_before, "零重复嵌入"
    assert FLIP not in await _serving_ids(db_engine)
    stack.client.close()


async def test_fingerprint_capability_absent_keeps_ttl_fallback(
    db_engine, sync_factory, healthy_report
):
    """无指纹能力的连接器:窗口内压制兜底不变(Tier 2),回归保护。"""
    stack = _real_stack(sync_factory)
    factory = get_session_factory(db_engine)
    await _seed_active(db_engine, OK1)

    _CURRENT["connector"] = _Connector(
        members={OK1, FLIP}, full_docs=[_raw_doc(FLIP, UNSAFE_CONTENT)]
    )
    await sync_mod._sync_one(
        _cfg(), stack.pipeline, factory, triggered_by="manual", builder=stack.builder
    )
    embedded_before = len(_embedded_texts(stack))

    _CURRENT["connector"] = _Connector(
        members={OK1, FLIP}, full_docs=[_raw_doc(FLIP, UNSAFE_CONTENT)]
    )
    await sync_mod._sync_one(
        _cfg(), stack.pipeline, factory, triggered_by="cron", builder=stack.builder
    )
    delta = dict((await _latest_sync_log(db_engine)).delta_counts or {})
    assert delta.get("membership_excluded", 0) == 1, "无指纹能力 ⇒ 窗口内压制兜底"
    assert len(_embedded_texts(stack)) == embedded_before
    stack.client.close()
