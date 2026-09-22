"""Issue #105 RED — content equality ≠ commerce metadata equality(增量同步新鲜度)。

生产实证(#28 验收波,#28 评论 5771553047):Store 变体 5110:5950/5951 已
``outofstock``,canonical re-sync 成功后账本 ``stock_status`` 仍 ``instock``、
``commerce_synced_at`` 恒空 —— content_hash 相等被当作「无变化」,authoritative
commerce metadata 的差异被系统性丢弃。

本文件按任务 RED 规格构造 T1/T2:

- T1:content_hash = H;commerce metadata:stock_status=instock、
  purchasable=true、date_modified=D1、stock_quantity=5;
- T2:content_hash **仍 = H**(内容一字不改);authoritative Store metadata
  改变(stock_status=outofstock、purchasable=false、date_modified=D2)。

缺陷核心 = **content equality != commerce metadata equality**:正常增量
sync 必须在 content 未变时仍把 serving/vector commerce props(含
commerce_synced_at)收敛到 Store 真值 —— 零重嵌、零版本分叉、幂等,
绝不用 --reindex/手工修数充当正确性机制。

两条腿:

- 连接器腿(纯单元):真实连接器语义下,purchasable/on_sale/permalink/
  date_modified 变化**天然不改变 content**(这些字段本就不在可检索文本
  行内)⇒ 同 content_hash + 异 commerce metadata 是真实存在类,非合成;
- 构建器腿(真 PG + 真 Weaviate,不可达 skip):T1→T2 走增量分类路径,
  证明当前 main 的 serving/vector commerce metadata 不收敛(RED),
  修复后收敛且幂等(GREEN)。

零外网;不硬编码任何真实产品/SKU。
"""

import os
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import weaviate
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.connectors.base import RawDocument
from backend.connectors.registry import ConnectorRegistry, SourceConfig
from backend.db.models import (
    Base,
    Document,
    DocumentVersion,
    DocumentVersionChunk,
    IndexGeneration,
)
from backend.pipeline.generation_builder import GenerationBuilder
from backend.pipeline.ingest import generation_chunk_uuids

TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test",
)
WEAVIATE_PORT = int(os.environ.get("P1_WEAVIATE_PORT", "8080"))
CLASS_NAME = "Issue105Probe"
SRC = "issue105-src"
PREFIX = "issue105/"
SID = PREFIX + "5110/5950"

# T1/T2 **同一** content(缺陷核心:content 相等;禁止改文本来制造 RED)
VARIANT_CONTENT = (
    "# Probe Camera — Wi-Fi\n\n"
    "SKU: 76.001.000042\n\n"
    "Price: $199.9\n\n"
    "Stock: instock (5)\n\n"
    "Attributes: pa_model=wi-fi"
)

D1 = "2026-09-20T10:00:00"
D2 = "2026-09-21T17:31:44"


def _woo_meta(
    *,
    stock_status: str,
    purchasable: bool,
    date_modified: str,
    stock_quantity: int | None,
    permalink: str = "https://www.example.com/store/probe/?attribute_pa_model=wi-fi",
    on_sale: bool = False,
) -> dict:
    """变体 commerce metadata(键 = 连接器 `_variation_to_document` 词表)。"""
    return {
        "product_id": 5110,
        "variation_id": 5950,
        "variation_identity_key": "5110:5950",
        "commerce_type": "variation",
        "sku": "76.001.000042",
        "price": "199.9",
        "regular_price": "199.9",
        "sale_price": "",
        "on_sale": on_sale,
        "stock_status": stock_status,
        "stock_quantity": stock_quantity,
        "purchasable": purchasable,
        "attributes": [{"slug": "pa_model", "option": "wi-fi"}],
        "variation_attributes": ["pa_model=wi-fi"],
        "permalink": permalink,
        "date_modified": date_modified,
        "categories": ["Probe"],
        "type": "variation",
        "status": "publish",
    }


def _woo_doc(metadata: dict, content: str = VARIANT_CONTENT) -> RawDocument:
    import hashlib

    return RawDocument(
        source_id=SID,
        source_type="woocommerce",
        product="probe-camera",
        title="Probe Camera — Wi-Fi",
        content=content,
        url=metadata["permalink"],
        metadata=metadata,
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        channel_visibility=("widget", "api"),
        branch="",
        content_type="variation",
    )


class _FakeEmbedder:
    dimension = 8

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return [[0.1] * self.dimension for _ in texts]


@pytest.fixture()
def stack():
    try:
        client = weaviate.connect_to_local("localhost", WEAVIATE_PORT)
    except Exception:  # noqa: BLE001 - 不可达即跳过(与真 Weaviate 集成套件同模式)
        pytest.skip(f"local Weaviate 不可达(port={WEAVIATE_PORT})")
    sync_engine = create_engine(TEST_DSN.replace("+asyncpg", "+psycopg2"))
    Base.metadata.create_all(sync_engine)
    sync_factory = sessionmaker(sync_engine, expire_on_commit=False)

    with sync_factory() as s:
        _purge(s)
    if client.collections.exists(CLASS_NAME):
        client.collections.delete(CLASS_NAME)

    embedder = _FakeEmbedder()
    from backend.pipeline.ingest import IngestionPipeline

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

    yield SimpleNamespace(
        client=client,
        sync_factory=sync_factory,
        pipeline=pipeline,
        builder=builder,
        embedder=embedder,
    )

    with sync_factory() as s:
        _purge(s)
    if client.collections.exists(CLASS_NAME):
        client.collections.delete(CLASS_NAME)
    client.close()
    sync_engine.dispose()


def _purge(s) -> None:
    for row in s.execute(
        select(Document).where(Document.source_id.like(f"{PREFIX}%"))
    ).scalars():
        s.delete(row)
    for row in s.execute(
        select(DocumentVersion).where(DocumentVersion.source_id.like(f"{PREFIX}%"))
    ).scalars():
        s.delete(row)
    for row in s.execute(
        select(IndexGeneration).where(IndexGeneration.source_id == SRC)
    ).scalars():
        s.delete(row)
    s.commit()


def _current_version(sf):
    with sf() as s:
        ver = s.execute(
            select(DocumentVersion).where(DocumentVersion.source_id == SID)
        ).scalars().all()
        s.expunge_all()
    return ver


def _serving_objects(ns, version):
    uuids = generation_chunk_uuids(SID, str(version.generation_id), version.chunk_count)
    from weaviate.classes.query import Filter

    resp = ns.pipeline._collection.query.fetch_objects(
        filters=Filter.by_id().contains_any(uuids), limit=len(uuids)
    )
    return resp.objects


# --------------------------------------------------------------------------- #
# 连接器腿:同 content_hash + 异 commerce metadata 是真实语义类(零外网)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_content_equality_does_not_imply_commerce_metadata_equality():
    """AC1 前提:authoritative commerce metadata 变化**不必**改变 content。

    purchasable / on_sale / permalink / date_modified 均不在可检索文本行内:
    两个真实 Store variation payload 可以 content 逐字节相等而商业真值相反
    ⇒ content_hash 相等是这些字段变化时的**常态**,不是合成场景。
    """
    import backend.connectors.woocommerce  # noqa: F401 - 触发 @register

    connector = ConnectorRegistry.create(
        SourceConfig(
            id="woocommerce-mall",
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
    )
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
    # T1:在售可购;T2:下架不可购 + permalink 改版 + date_modified 推进。
    # price/stock/attrs/sku 全部不变 ⇒ content 逐字节相等。
    v_t1 = {
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
        "attributes": [{"id": 1, "name": "Model", "slug": "pa_model", "option": "wi-fi"}],
        "status": "publish",
    }
    v_t2 = {
        **v_t1,
        "purchasable": False,
        "on_sale": True,
        "permalink": "https://www.example.com/store/probe-v2/?attribute_pa_model=wi-fi",
        "date_modified": D2,
    }

    with patch.object(
        connector,
        "_get",
        side_effect=lambda path, *, params=None: _resp(
            [parent] if path.endswith("/products") else [v_t1]
        ),
    ):
        t1_docs = [d for d in connector.fetch_changes(datetime(2026, 9, 20, 10, 0, 0, tzinfo=UTC)) if d.metadata.get("variation_id") == 5950]
    with patch.object(
        connector,
        "_get",
        side_effect=lambda path, *, params=None: _resp(
            [parent] if path.endswith("/products") else [v_t2]
        ),
    ):
        t2_docs = [d for d in connector.fetch_changes(datetime(2026, 9, 21, 17, 0, 0, tzinfo=UTC)) if d.metadata.get("variation_id") == 5950]

    assert len(t1_docs) == 1 and len(t2_docs) == 1
    d1, d2 = t1_docs[0], t2_docs[0]
    # 增量抓取**看得见** T2(fetch_changes 返回了它)…
    assert d2.metadata["date_modified"] == D2
    # …且 content_hash 与 T1 完全相等(content equality):
    assert d1.content_hash == d2.content_hash
    # …而 authoritative commerce metadata 已变(metadata equality 不成立):
    assert d1.metadata["purchasable"] is True and d2.metadata["purchasable"] is False
    assert d1.metadata["on_sale"] is False and d2.metadata["on_sale"] is True
    assert d1.metadata["permalink"] != d2.metadata["permalink"]


def _resp(payload) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = payload
    return resp


# --------------------------------------------------------------------------- #
# 构建器腿:T1→T2(同 hash)增量路径必须收敛 serving commerce 真值
# --------------------------------------------------------------------------- #


def test_metadata_only_converges_serving_commerce_props(stack):
    """AC1+AC2:content 未变、Store 商业真值变化 ⇒ 正常增量 sync 收敛。

    RED(当前 main):账本 metadata 收敛,但 Weaviate 对象 props 与持久
    chunk 副本的 commerce props(stock_status/purchasable/commerce_synced_at)
    残留 T1 旧值 —— serving 真值不收敛。
    GREEN:同一 metadata-only 路径同步刷新 commerce props(向量不动)。
    """
    t1 = _woo_doc(
        _woo_meta(
            stock_status="instock",
            purchasable=True,
            date_modified=D1,
            stock_quantity=5,
        )
    )
    t2 = _woo_doc(
        _woo_meta(
            stock_status="outofstock",
            purchasable=False,
            date_modified=D2,
            stock_quantity=5,
        )
    )
    assert t1.content_hash == t2.content_hash, "T1/T2 必须同 content_hash(缺陷前提)"

    first = stack.builder.build_generation([t1], source_id=SRC)
    assert first.new_docs == [SID]
    versions = _current_version(stack.sync_factory)
    assert len(versions) == 1
    v1 = versions[0]
    stack.embedder.calls.clear()

    # T2:同 content_hash,authoritative commerce metadata 已变 → 增量分类
    second = stack.builder.build_generation([t2], source_id=SRC)
    assert second.metadata_docs == [SID], "T2 必须走 metadata-only 路径(FC-5:不重嵌不分叉)"
    assert stack.embedder.calls == [], "metadata-only 零重嵌(AC3)"
    versions = _current_version(stack.sync_factory)
    assert len(versions) == 1 and versions[0].id == v1.id, "零版本分叉(AC3)"

    # 账本收敛(此半在当前 main 已真:metadata-only 全量替换 metadata_)
    with stack.sync_factory() as s:
        row = s.execute(select(Document).where(Document.source_id == SID)).scalar_one()
        assert row.metadata_["stock_status"] == "outofstock"
        assert row.metadata_["commerce_type"] == "variation"

    # serving/vector commerce props 收敛(RED:当前 main 残留 T1 旧值)
    objects = _serving_objects(stack, versions[0])
    assert objects, "在服对象必须存在"
    for obj in objects:
        assert obj.properties.get("stock_status") == "outofstock", (
            "RED(#105): metadata-only 路径不投影 commerce props —— serving "
            "stock_status 残留 T1 旧值,生产 5110:5950/5951 缺陷的机制级复现"
        )
        assert obj.properties.get("purchasable") is False
        assert obj.properties.get("commerce_synced_at") == D2, (
            "commerce_synced_at 必须如实取 Store snapshot date_modified(不伪造时间)"
        )
        assert obj.properties.get("variation_identity_key") == "5110:5950"

    # 持久 chunk 副本(repair 重建真值源)同步收敛
    with stack.sync_factory() as s:
        chunks = s.execute(
            select(DocumentVersionChunk).where(
                DocumentVersionChunk.version_id == versions[0].id
            )
        ).scalars().all()
    assert chunks
    for c in chunks:
        assert c.props.get("stock_status") == "outofstock", (
            "持久 chunk 副本 commerce props 必须同步(否则 repair 重建会复活陈旧商业真值)"
        )


def test_metadata_only_clears_unmanaged_stock_quantity(stack):
    """AC2(诚实缺席):端点停止管理库存(None)⇒ serving 不得残留旧数量。

    COMMERCE_PROPS 词表:stock_quantity None = 端点未管理库存 → 键省略
    (不写 0 伪装)。merge update 语义下「省略」= 残留 ⇒ 必须显式收敛到缺席。
    """
    t1 = _woo_doc(
        _woo_meta(stock_status="instock", purchasable=True, date_modified=D1, stock_quantity=5)
    )
    t2 = _woo_doc(
        _woo_meta(stock_status="instock", purchasable=True, date_modified=D2, stock_quantity=None)
    )
    stack.builder.build_generation([t1], source_id=SRC)
    stack.embedder.calls.clear()

    accounting = stack.builder.build_generation([t2], source_id=SRC)
    assert accounting.metadata_docs == [SID]
    assert stack.embedder.calls == []
    versions = _current_version(stack.sync_factory)
    objects = _serving_objects(stack, versions[0])
    for obj in objects:
        assert not obj.properties.get("stock_quantity"), (
            "RED(#105): 端点已不管理库存,serving 不得残留 T1 的 stock_quantity"
        )


def test_repeat_sync_idempotent_after_convergence(stack):
    """AC4:收敛后重复相同 sync ⇒ UNCHANGED、零写入、props 不再抖动。"""
    t2 = _woo_doc(
        _woo_meta(stock_status="outofstock", purchasable=False, date_modified=D2, stock_quantity=5)
    )
    stack.builder.build_generation([t2], source_id=SRC)
    stack.embedder.calls.clear()

    repeat = stack.builder.build_generation([t2], source_id=SRC)
    assert repeat.unchanged_docs == [SID], "收敛后重复 sync 必须判 UNCHANGED(幂等)"
    assert repeat.metadata_docs == [] and repeat.new_docs == [] and repeat.updated_docs == []
    assert stack.embedder.calls == [], "UNCHANGED 零 embed"
    versions = _current_version(stack.sync_factory)
    assert len(versions) == 1
    for obj in _serving_objects(stack, versions[0]):
        assert obj.properties.get("stock_status") == "outofstock"
        assert obj.properties.get("commerce_synced_at") == D2
