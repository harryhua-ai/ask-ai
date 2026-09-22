"""Issue #105 (R4, REVIEW_R3) — 空增量轮 mirror-drift 可达性(端到端集成)。

Blocker:存量残形行(active version 双 hash 现行 + serving 现行,**仅
documents 行镜像滞后 v1**)在 ``last_success > Store date_modified`` 时,
``fetch_changes(since)`` 恒空 ⇒ 文档永远进不了 ``GenerationBuilder`` ⇒
R3 的 builder-local 对账不可达 ⇒ AC6 不可达。

本测试经**真实 ``_sync_one → WooCommerce connector → GenerationBuilder``
路径**复现并锁定收敛(连接器 HTTP mock,零外网):

- 种子:v1 首灌 → v2 正常激活(真连接器文档,真 PG + 真 Weaviate);
- 仅把 documents.metadata_ 回滚 v1(模拟旧代码已制造的持久状态);
- 预置 ``last_success`` 晚于 Store date_modified ⇒ 增量抓取为空
  (mock:带 modified_after 的 listing 返回空 = 真实 Store 形状);
- 正常(非 reindex)Woo sync ⇒ 行镜像必须追平 v2;
- 第二轮同步 = 真 UNCHANGED,零写入。

不硬编码真实产品身份;不动 Woo 身份/获取语义;无 reindex/手工 SQL。
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import weaviate
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from backend.connectors.registry import ConnectorRegistry, SourceConfig
from backend.db.models import (
    Base,
    DataSource,
    Document,
    DocumentVersion,
    IndexGeneration,
    SyncLog,
)
from backend.pipeline.generation_builder import GenerationBuilder
from backend.pipeline.ingest import IngestionPipeline, generation_chunk_uuids
from scripts.sync import _last_success_at, _sync_one

pytestmark = pytest.mark.asyncio

TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test",
)
WEAVIATE_PORT = int(os.environ.get("P1_WEAVIATE_PORT", "8080"))
CLASS_NAME = "Issue105SyncProbe"
SRC = "issue105-sync-src"
SID = f"{SRC}/5110/5950"

D1 = "2026-09-20T10:00:00"
D2 = "2026-09-21T17:31:44"
LAST_SUCCESS = datetime(2026, 9, 22, 6, 0, 0, tzinfo=UTC)  # 晚于 Store date_modified


def _source_config() -> SourceConfig:
    return SourceConfig(
        id=SRC,
        type="woocommerce",
        product="commercial",
        enabled=True,
        config={
            "store_url": "https://www.example.com",
            "consumer_key": "ck_test",
            "consumer_secret": "cs_test",
        },
        sync_interval="1h",
    )


def _make_connector() -> object:
    import backend.connectors.woocommerce  # noqa: F401 - 触发 @register

    return ConnectorRegistry.create(_source_config())


def _fake_get_for(variation_payload: dict):
    """按真实 API 形状构造 connector._get 替身:

    - 带 ``modified_after`` 的增量 listing → **空**(last_success 晚于
      Store date_modified ⇒ fetch_changes 恒空,blocker 的核心形状);
    - 无 modified_after 的全量 listing → 完整权威发现(absence 确认用);
    - variations 端点 → 当前 Store 真值(v2,outofstock)。
    """
    parent = {
        "id": 5110,
        "name": "Probe Camera",
        "slug": "probe-camera",
        "permalink": "https://www.example.com/store/probe-camera/",
        "type": "variable",
        "status": "publish",
        "stock_status": "instock",
        "date_modified": D2,
        "categories": [{"id": 1, "name": "Probe", "slug": "probe"}],
        "variations": [5950],
    }
    variation = {
        "id": 5950,
        "sku": "76.001.000042",
        "price": "199.9",
        "regular_price": "199.9",
        "sale_price": "",
        "on_sale": False,
        "purchasable": True,
        "stock_status": "instock",
        "stock_quantity": 5,
        "permalink": "https://www.example.com/store/probe/?attribute_pa_model=wi-fi",
        "date_modified": D1,
        "attributes": [
            {"id": 1, "name": "Model", "slug": "pa_model", "option": "wi-fi"}
        ],
        "status": "publish",
    }
    variation.update(variation_payload)

    def _fake_get(path: str, *, params=None):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        if path.endswith("/products"):
            if params and params.get("modified_after"):
                resp.json.return_value = []  # 增量窗口内 Store 无变更 ⇒ 空
            else:
                resp.json.return_value = [parent]  # 全量权威发现
        else:
            assert path.endswith("/products/5110/variations")
            resp.json.return_value = [variation]
        return resp

    return _fake_get


def _variation_doc(connector, vid: int = 5950):
    docs = [d for d in connector.fetch_all() if d.metadata.get("variation_id") == vid]
    assert len(docs) == 1
    return docs[0]


class _FakeEmbedder:
    dimension = 8

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return [[0.1] * self.dimension for _ in texts]


def _healthy_report():
    return SimpleNamespace(
        expected_chunks=1,
        actual_chunks=1,
        missing_source_ids=[],
        refill_source_ids=[],
        stale_chunk_count=0,
        orphan_count=0,
        is_healthy=True,
    )


def _async_const(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner


def _purge(s) -> None:
    for row in s.execute(select(SyncLog).where(SyncLog.source_id == SRC)).scalars():
        s.delete(row)
    for row in s.execute(select(DataSource).where(DataSource.id == SRC)).scalars():
        s.delete(row)
    for row in s.execute(
        select(Document).where(Document.source_id.like(f"{SRC}/%"))
    ).scalars():
        s.delete(row)
    for row in s.execute(
        select(DocumentVersion).where(DocumentVersion.source_id.like(f"{SRC}/%"))
    ).scalars():
        s.delete(row)
    for row in s.execute(
        select(IndexGeneration).where(IndexGeneration.source_id == SRC)
    ).scalars():
        s.delete(row)
    s.commit()


@pytest.fixture()
async def stack(monkeypatch):
    try:
        client = weaviate.connect_to_local("localhost", WEAVIATE_PORT)
    except Exception:  # noqa: BLE001 - 不可达即跳过(与真 Weaviate 集成套件同模式)
        pytest.skip(f"local Weaviate 不可达(port={WEAVIATE_PORT})")
    sync_engine = create_engine(TEST_DSN.replace("+asyncpg", "+psycopg2"))
    Base.metadata.create_all(sync_engine)
    sync_factory = sessionmaker(sync_engine, expire_on_commit=False)
    from sqlalchemy.ext.asyncio import create_async_engine

    async_engine = create_async_engine(TEST_DSN)
    from backend.db.session import get_session_factory

    async_factory = get_session_factory(async_engine)

    with sync_factory() as s:
        _purge(s)
    if client.collections.exists(CLASS_NAME):
        client.collections.delete(CLASS_NAME)

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

    # 预置 last_success:晚于 Store date_modified ⇒ fetch_changes 恒空(blocker 形状)
    with sync_factory() as s:
        s.add(
            SyncLog(
                source_id=SRC,
                source_type="woocommerce",
                status="success",
                started_at=datetime(2026, 9, 22, 5, 0, 0, tzinfo=UTC),
                finished_at=LAST_SUCCESS,
                triggered_by="seed",
            )
        )
        s.add(
            DataSource(
                id=SRC,
                type="woocommerce",
                product="commercial",
                config={
                    "store_url": "https://www.example.com",
                    "consumer_key": "ck_test",
                    "consumer_secret": "cs_test",
                },
            )
        )
        s.commit()

    # verify 恒健康(焦点 = mirror 可达性,非向量校验;既有 harness 同模式)
    monkeypatch.setattr(
        "scripts.sync.verify_source_vectors", _async_const(_healthy_report())
    )

    yield SimpleNamespace(
        client=client,
        sync_factory=sync_factory,
        async_factory=async_factory,
        pipeline=pipeline,
        embedder=embedder,
        cfg=_source_config(),
    )
    with sync_factory() as s:
        _purge(s)
    if client.collections.exists(CLASS_NAME):
        client.collections.delete(CLASS_NAME)
    client.close()
    async_engine.dispose()
    sync_engine.dispose()


def _versions(sync_factory):
    with sync_factory() as s:
        ver = (
            s.execute(
                select(DocumentVersion)
                .where(DocumentVersion.source_id == SID)
                .order_by(DocumentVersion.version_seq)
            )
            .scalars()
            .all()
        )
        s.expunge_all()
    return ver


def _row(sync_factory):
    with sync_factory() as s:
        row = s.execute(select(Document).where(Document.source_id == SID)).scalar_one()
        s.expunge(row)
    return row


def _generation_count(sync_factory) -> int:
    with sync_factory() as s:
        return len(
            s.execute(
                select(IndexGeneration).where(IndexGeneration.source_id == SRC)
            )
            .scalars()
            .all()
        )


async def _latest_sync_log(async_factory) -> SyncLog | None:
    async with async_factory() as s:
        result = await s.execute(
            text(
                "SELECT id FROM sync_log WHERE source_id = :sid "
                "ORDER BY started_at DESC LIMIT 1"
            ),
            {"sid": SRC},
        )
        row = result.first()
        log_id = row[0] if row else None
    if log_id is None:
        return None
    engine = create_engine(TEST_DSN.replace("+asyncpg", "+psycopg2"))
    try:
        with sessionmaker(engine, expire_on_commit=False)() as s:
            log = s.get(SyncLog, log_id)
            s.expunge(log)
            return log
    finally:
        engine.dispose()


async def test_empty_incremental_sync_reconciles_mirror_drift(stack, monkeypatch):
    """RED→GREEN:blocker 形状下正常 sync 必须把行镜像追平 v2。

    步骤:v1 灌入 → v2 激活 → 仅回滚行镜像到 v1(历史持久状态)→
    last_success 晚于 Store date_modified ⇒ fetch_changes 空 → 正常
    (非 reindex)Woo sync。RED(整改前):行停留 v1。GREEN:行追平 v2,
    零重嵌/零版本分叉/零新代,serving 不退化;第二轮 = 真 UNCHANGED。
    """
    import backend.connectors.woocommerce  # noqa: F401 - 触发 @register

    # --- 种子:v1 → v2(真连接器文档,经真 builder 激活) ---
    c1 = _make_connector()
    monkeypatch.setattr(c1, "_get", _fake_get_for({}))
    t1 = _variation_doc(c1)
    c2 = _make_connector()
    monkeypatch.setattr(
        c2, "_get", _fake_get_for({"stock_status": "outofstock", "date_modified": D2})
    )
    t2 = _variation_doc(c2)
    assert t1.content_hash != t2.content_hash

    builder = GenerationBuilder(stack.pipeline, stack.sync_factory)
    builder.build_generation([t1], source_id=SRC)
    builder.build_generation([t2], source_id=SRC)
    assert len(_versions(stack.sync_factory)) == 2
    gens_before = _generation_count(stack.sync_factory)

    # --- 模拟历史持久状态:仅行镜像回滚 v1 ---
    with stack.sync_factory() as s:
        row = s.execute(select(Document).where(Document.source_id == SID)).scalar_one()
        stale = dict(row.metadata_)
        stale["stock_status"] = "instock"
        stale["date_modified"] = D1
        row.metadata_ = stale
        s.commit()

    last_success = await _last_success_at(stack.async_factory, SRC)
    assert last_success is not None, "预置 last_success 必须生效"

    # --- 正常(非 reindex)Woo sync:真 _sync_one → 真 connector → 真 builder ---
    # 增量抓取(mock modified_after listing)恒空 ⇒ 文档只能经权威发现到达。
    from backend.connectors.woocommerce import WooCommerceConnector

    def _create(config):
        # 直接实例化(绕开已被 monkeypatch 的 Registry.create,防递归)
        conn = WooCommerceConnector(config)
        monkeypatch.setattr(
            conn,
            "_get",
            _fake_get_for({"stock_status": "outofstock", "date_modified": D2}),
        )
        return conn

    monkeypatch.setattr("scripts.sync.ConnectorRegistry.create", _create)
    stack.embedder.calls.clear()

    await _sync_one(stack.cfg, stack.pipeline, stack.async_factory, triggered_by="test")

    log = await _latest_sync_log(stack.async_factory)
    assert log is not None and log.status == "success", (
        f"对账轮必须 success;error_detail={getattr(log, 'error_detail', None)}"
    )
    assert (log.delta_counts or {}).get("mirror_reconciled_count") == 1, (
        "RED(REVIEW_R3): 空增量轮下 mirror-drift 行进不了 builder —— "
        "正常 sync 必须对账行镜像(加性投影修复计数)"
    )
    row = _row(stack.sync_factory)
    assert row.metadata_["stock_status"] == "outofstock", "行镜像必须追平 v2 真值"
    assert row.metadata_["date_modified"] == D2
    versions = _versions(stack.sync_factory)
    assert len(versions) == 2, "零版本分叉"
    assert _generation_count(stack.sync_factory) == gens_before, "零新代"
    assert stack.embedder.calls == [], "对账零重嵌"

    from weaviate.classes.query import Filter

    uuids = generation_chunk_uuids(
        SID, str(versions[1].generation_id), versions[1].chunk_count
    )
    resp = stack.pipeline._collection.query.fetch_objects(
        filters=Filter.by_id().contains_any(uuids), limit=len(uuids)
    )
    assert resp.objects, "在服对象必须存在"
    for obj in resp.objects:
        assert obj.properties.get("stock_status") == "outofstock", "serving 真值不退化"

    # --- 第二轮:真 UNCHANGED,零写入 ---
    mirror_before = _row(stack.sync_factory).metadata_
    await _sync_one(stack.cfg, stack.pipeline, stack.async_factory, triggered_by="test")
    log2 = await _latest_sync_log(stack.async_factory)
    assert log2 is not None and log2.status == "success"
    assert (log2.delta_counts or {}).get("mirror_reconciled_count") == 0, "已收敛 ⇒ 零对账"
    assert (log2.delta_counts or {}).get("unchanged_count") == 1, "第二轮 = 真 UNCHANGED"
    assert _row(stack.sync_factory).metadata_ == mirror_before, "行镜像不再变化"
    assert stack.embedder.calls == [], "全程零重嵌"
    assert len(_versions(stack.sync_factory)) == 2
    assert _generation_count(stack.sync_factory) == gens_before


# --------------------------------------------------------------------------- #
# R5(REVIEW_R4):no-change 钩子必须严格 mirror-drift-only
# --------------------------------------------------------------------------- #


def _base_variation(vid: int, **overrides) -> dict:
    v = {
        "id": vid,
        "sku": f"76.001.0000{vid}",
        "price": "199.9",
        "regular_price": "199.9",
        "sale_price": "",
        "on_sale": False,
        "purchasable": True,
        "stock_status": "instock",
        "stock_quantity": 5,
        "permalink": f"https://www.example.com/store/probe/?attribute_pa_model={vid}",
        "date_modified": D1,
        "attributes": [
            {"id": 1, "name": "Model", "slug": "pa_model", "option": "wi-fi"}
        ],
        "status": "publish",
    }
    v.update(overrides)
    return v


def _multi_connector():
    """四形状探针源:5950 drift / 5951 healthy / 5952 METADATA_CHANGED / 5953 CONTENT_CHANGED。"""
    import backend.connectors.woocommerce  # noqa: F401 - 触发 @register

    return ConnectorRegistry.create(_source_config())


def _multi_fake_get(current_variations: list[dict]):
    parent = {
        "id": 5110,
        "name": "Probe Camera",
        "slug": "probe-camera",
        "permalink": "https://www.example.com/store/probe-camera/",
        "type": "variable",
        "status": "publish",
        "stock_status": "instock",
        "date_modified": D2,
        "categories": [{"id": 1, "name": "Probe", "slug": "probe"}],
        "variations": [5950, 5951, 5952, 5953],
    }

    def _fake_get(path: str, *, params=None):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        if path.endswith("/products"):
            if params and params.get("modified_after"):
                resp.json.return_value = []  # 空增量(blocker 形状)
            else:
                resp.json.return_value = [parent]
        else:
            assert path.endswith("/products/5110/variations")
            resp.json.return_value = current_variations
        return resp

    return _fake_get


async def test_no_change_hook_is_strictly_mirror_drift_only(stack, monkeypatch):
    """REVIEW_R4 冻结语义:no-change 钩子只处理
    「ledger 存在 + ACTIVE + classifier==UNCHANGED + _row_mirror_drifted」
    的有界集;真实 METADATA_CHANGED / CONTENT_CHANGED **不归本钩子**
    (零 embed/零新版本/零新代,mirror_reconciled_count 只计真对账)。
    """
    conn = _multi_connector()
    builder = GenerationBuilder(stack.pipeline, stack.sync_factory)
    gen0 = _generation_count(stack.sync_factory)

    # --- 种子 ---
    # 5950: v1 → v2 正常激活(随后仅回滚行镜像 = drift+UNCHANGED)
    monkeypatch.setattr(conn, "_get", _multi_fake_get([_base_variation(5950)]))
    d5950_v1 = _variation_doc(conn)
    monkeypatch.setattr(
        conn, "_get", _multi_fake_get([
            _base_variation(5950, stock_status="outofstock", date_modified=D2)
        ])
    )
    d5950_v2 = _variation_doc(conn)
    assert d5950_v1.content_hash != d5950_v2.content_hash
    builder.build_generation([d5950_v1], source_id=SRC)
    builder.build_generation([d5950_v2], source_id=SRC)

    # 5951: v1 灌入,当前真值不变(healthy UNCHANGED)
    monkeypatch.setattr(conn, "_get", _multi_fake_get([_base_variation(5951)]))
    d5951 = _variation_doc(conn, vid=5951)
    builder.build_generation([d5951], source_id=SRC)

    # 5952: v1 灌入(purchasable=true);当前真值 purchasable=false(同 hash)
    # ⇒ active version 视角 = METADATA_CHANGED
    monkeypatch.setattr(conn, "_get", _multi_fake_get([_base_variation(5952)]))
    d5952 = _variation_doc(conn, vid=5952)
    builder.build_generation([d5952], source_id=SRC)

    # 5953: v1 灌入(instock 默认);当前真值 outofstock(hash 不同)⇒ CONTENT_CHANGED
    monkeypatch.setattr(conn, "_get", _multi_fake_get([_base_variation(5953)]))
    d5953 = _variation_doc(conn, vid=5953)
    builder.build_generation([d5953], source_id=SRC)

    seeded_generations = _generation_count(stack.sync_factory)
    assert seeded_generations >= 1

    # 仅 5950 行镜像回滚 v1(历史残形);5951/5952/5953 行保持激活时真值
    def _sid(vid):
        return f"{SRC}/5110/{vid}"

    with stack.sync_factory() as s:
        row = s.execute(
            select(Document).where(Document.source_id == f"{SRC}/5110/5950")
        ).scalar_one()
        stale = dict(row.metadata_)
        stale["stock_status"] = "instock"
        stale["date_modified"] = D1
        row.metadata_ = stale
        s.commit()
    row_healthy_before = _row_metadata_of(stack.sync_factory, f"{SRC}/5110/5951")
    row_meta_before = _row_metadata_of(stack.sync_factory, f"{SRC}/5110/5952")
    row_content_before_hash = _row_hash_of(stack.sync_factory, f"{SRC}/5110/5953")
    total_versions_before = _total_version_count(stack.sync_factory)
    stack.embedder.calls.clear()

    # --- 空增量轮 + 全量发现含全部四形状 → 正常 sync ---
    from backend.connectors.woocommerce import WooCommerceConnector

    def _create(config):
        c = WooCommerceConnector(config)
        monkeypatch.setattr(
            c,
            "_get",
            _multi_fake_get([
                # Store 当前真值:5950 已是 v2(UNCHANGED+drift);
                _base_variation(5950, stock_status="outofstock", date_modified=D2),
                # 5951 healthy;
                _base_variation(5951),
                # 5952 同 hash 异 metadata ⇒ METADATA_CHANGED;
                _base_variation(5952, purchasable=False),
                # 5953 异 hash ⇒ CONTENT_CHANGED
                _base_variation(5953, stock_status="outofstock", date_modified=D2),
            ]),
        )
        return c

    monkeypatch.setattr("scripts.sync.ConnectorRegistry.create", _create)
    await _sync_one(stack.cfg, stack.pipeline, stack.async_factory, triggered_by="test")

    log = await _latest_sync_log(stack.async_factory)
    assert log is not None and log.status == "success", (
        f"error_detail={getattr(log, 'error_detail', None)}"
    )
    assert (log.delta_counts or {}).get("mirror_reconciled_count") == 1, (
        "RED(REVIEW_R4): 钩子必须只对账真 mirror-drift 行(不得 churn "
        "METADATA_CHANGED/CONTENT_CHANGED 文档)"
    )

    # drift 行:追平
    row_drift = _row_metadata_of(stack.sync_factory, f"{SRC}/5110/5950")
    assert row_drift["stock_status"] == "outofstock"
    assert row_drift["date_modified"] == D2

    # healthy 行:零写入
    assert _row_metadata_of(stack.sync_factory, f"{SRC}/5110/5951") == row_healthy_before

    # METADATA_CHANGED 行:不归本钩子(保持原状,归属正常抓取轮)
    assert _row_metadata_of(stack.sync_factory, f"{SRC}/5110/5952") == row_meta_before, (
        "no-change 钩子不得处理真实 METADATA_CHANGED"
    )

    # CONTENT_CHANGED 行:零 embed/零新版本/行不变
    assert _row_hash_of(stack.sync_factory, f"{SRC}/5110/5953") == row_content_before_hash
    assert _row_metadata_of(stack.sync_factory, f"{SRC}/5110/5953")["stock_status"] == "instock"
    assert stack.embedder.calls == [], "钩子零重嵌(含对 CONTENT_CHANGED 的未处理)"
    assert _total_version_count(stack.sync_factory) == total_versions_before, "零新版本"
    assert _generation_count(stack.sync_factory) == seeded_generations, "零新代"

    # --- 第二轮:幂等,计数归零 ---
    await _sync_one(stack.cfg, stack.pipeline, stack.async_factory, triggered_by="test")
    log2 = await _latest_sync_log(stack.async_factory)
    assert log2 is not None and log2.status == "success"
    assert (log2.delta_counts or {}).get("mirror_reconciled_count") == 0
    assert stack.embedder.calls == []


def _row_metadata_of(sync_factory, sid) -> dict:
    with sync_factory() as s:
        row = s.execute(select(Document).where(Document.source_id == sid)).scalar_one()
        meta = dict(row.metadata_ or {})
    return meta


def _row_hash_of(sync_factory, sid) -> str:
    with sync_factory() as s:
        row = s.execute(select(Document).where(Document.source_id == sid)).scalar_one()
        return row.content_hash


def _total_version_count(sync_factory) -> int:
    with sync_factory() as s:
        return len(
            s.execute(select(DocumentVersion)).scalars().all()
        )
