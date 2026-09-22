"""Issue #105 (R2) — commerce metadata freshness along the REAL connector paths.

Role A REVIEW_1(#109 评论 5772503175)整改:全部测试改用**真实
`_variation_to_document` 输出**(mock HTTP,零外网)喂 builder,禁止合成
VARIANT_CONTENT + 手改 metadata 的状态。

生产机械事实(#28 评论 5771553047 + R2 只读取证,2026-09-22):

- `5110:5950/5951`:documents 行 JSONB 仍 `stock_status=instock`、
  `date_modified=2026-09-18T14:02:32`(v1 时代),而行 `content_hash` 已是
  v2(1233ac44…,2026-09-21 20:25 激活,outofstock 内容);
- 根因(代码 + 生产 dual-proven):**内容变更激活路径不回写
  `documents.metadata_`** —— `activate_document_version` 只同步
  content_hash/chunk_count/title/url;`metadata_` 仅存在于
  `_build_and_activate` 的「新行」分支。分类器权威是
  `DocumentVersion.metadata_hash`(激活时已写新值)⇒ 之后每轮 UNCHANGED,
  账本行 JSONB 商业真值永久陈旧 —— **不是 metadata-only 路径**。

两类自然路径都必须收敛(R2 契约):

- metadata-only natural class:purchasable / on_sale / permalink /
  date_modified 变化 **不改变** content_hash ⇒ METADATA_CHANGED ⇒
  零重嵌收敛 serving + ledger + chunk 副本;
- content-changing commerce class:stock_status / stock_quantity / price /
  sale 变化**天然改变** content(连接器把这些写进可检索文本)⇒
  CONTENT_CHANGED ⇒ 重建收敛 serving 真值 **且账本行 JSONB 同步追平**。

另含 R2 blocker 2:metadata-only 的 Weaviate 失败必须 fail-closed ——
serving 更新失败不得推进任何权威状态,下一轮 normal sync 必须重试并收敛。
"""

import os
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import weaviate
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

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
PREFIX = "issue105-src/"
SID = PREFIX + "5110/5950"  # = 连接器 source_id `{config.id}/{pid}/{vid}`

D1 = "2026-09-20T10:00:00"
D2 = "2026-09-21T17:31:44"
PERMALINK_V1 = "https://www.example.com/store/probe/?attribute_pa_model=wi-fi"
PERMALINK_V2 = "https://www.example.com/store/probe-v2/?attribute_pa_model=wi-fi"


def _make_connector():
    import backend.connectors.woocommerce  # noqa: F401 - 触发 @register

    return ConnectorRegistry.create(
        SourceConfig(
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
    )


def _parent() -> dict:
    return {
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


def _variation(**overrides) -> dict:
    """真实 wc/v3 variation payload 形态(通用探针产品,零硬编码商业真值)。"""
    v: dict = {
        "id": 5950,
        "sku": "76.001.000042",
        "price": "199.9",
        "regular_price": "199.9",
        "sale_price": "",
        "on_sale": False,
        "purchasable": True,
        "stock_status": "instock",
        "stock_quantity": 5,
        "permalink": PERMALINK_V1,
        "date_modified": D1,
        "attributes": [
            {"id": 1, "name": "Model", "slug": "pa_model", "option": "wi-fi"}
        ],
        "status": "publish",
    }
    v.update(overrides)
    return v


def _fetch_variation_doc(overrides: dict):
    """经真实连接器管线(mock HTTP)产出 variation RawDocument。

    content / content_hash / metadata 全部由 `_variation_to_document`
    权威生成 —— 测试不手工构造内容状态。
    """
    connector = _make_connector()

    def _fake_get(path: str, *, params=None):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        if path.endswith("/products"):
            resp.json.return_value = [_parent()]
        else:
            assert path.endswith("/products/5110/variations")
            resp.json.return_value = [_variation(**overrides)]
        return resp

    with patch.object(connector, "_get", side_effect=_fake_get):
        docs = [
            d
            for d in connector.fetch_changes(datetime(2026, 9, 1, tzinfo=UTC))
            if d.metadata.get("variation_id") == 5950
        ]
    assert len(docs) == 1
    return docs[0]


# --------------------------------------------------------------------------- #
# 真实栈 fixture(真 PG + 真 Weaviate;不可达 skip,与门测试套件同模式)
# --------------------------------------------------------------------------- #


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


def _versions(sf):
    with sf() as s:
        ver = s.execute(
            select(DocumentVersion)
            .where(DocumentVersion.source_id == SID)
            .order_by(DocumentVersion.version_seq)  # id 是 UUID 无序;seq 才是版本序
        ).scalars().all()
        s.expunge_all()
    return ver


def _row(sf):
    with sf() as s:
        row = s.execute(select(Document).where(Document.source_id == SID)).scalar_one()
        s.expunge(row)
    return row


def _chunk_copies(sf, version):
    with sf() as s:
        chunks = s.execute(
            select(DocumentVersionChunk).where(
                DocumentVersionChunk.version_id == version.id
            )
        ).scalars().all()
        s.expunge_all()
    return chunks


def _serving_objects(ns, version):
    uuids = generation_chunk_uuids(SID, str(version.generation_id), version.chunk_count)
    from weaviate.classes.query import Filter

    resp = ns.pipeline._collection.query.fetch_objects(
        filters=Filter.by_id().contains_any(uuids), limit=len(uuids)
    )
    return resp.objects


# --------------------------------------------------------------------------- #
# 前提腿:content equality ≠ commerce metadata equality(真实连接器语义)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_content_equality_does_not_imply_commerce_metadata_equality():
    """authoritative commerce metadata 变化**不必**改变 content_hash。

    purchasable / on_sale / permalink / date_modified 均不在连接器可检索
    文本行内:两个真实 Store payload 可以 content 逐字节相等而商业真值相反
    ⇒ 同 hash + 异 commerce metadata 是连接器**天然产出**,非合成状态。
    对照组:stock_status 在 Stock 行内 ⇒ 真实连接器下必改 content_hash。
    """
    d1 = _fetch_variation_doc({})
    d2 = _fetch_variation_doc(
        {
            "purchasable": False,
            "on_sale": True,
            "permalink": PERMALINK_V2,
            "date_modified": D2,
        }
    )
    assert d1.content_hash == d2.content_hash, "purchasable/on_sale/permalink/date 不改内容 ⇒ 同 hash"
    assert d2.metadata["purchasable"] is False and d1.metadata["purchasable"] is True
    assert d2.metadata["date_modified"] == D2
    d3 = _fetch_variation_doc({"stock_status": "outofstock", "date_modified": D2})
    assert d3.content_hash != d1.content_hash, (
        "stock_status 变化经真实连接器必然改变 content(Stock 行)⇒ CONTENT_CHANGED 类"
    )


# --------------------------------------------------------------------------- #
# Class M:metadata-only natural class(同 hash)零重嵌全收敛
# --------------------------------------------------------------------------- #


def test_metadata_only_natural_class_converges_serving_and_ledger(stack):
    """purchasable/on_sale/permalink/date_modified(真实连接器输出,同 hash)
    ⇒ METADATA_CHANGED ⇒ 零重嵌收敛 serving commerce props + 账本行 + chunk 副本。
    """
    t1 = _fetch_variation_doc({})
    t2 = _fetch_variation_doc(
        {
            "purchasable": False,
            "on_sale": True,
            "permalink": PERMALINK_V2,
            "date_modified": D2,
        }
    )
    assert t1.content_hash == t2.content_hash

    stack.builder.build_generation([t1], source_id=SRC)
    v1 = _versions(stack.sync_factory)[0]
    stack.embedder.calls.clear()

    accounting = stack.builder.build_generation([t2], source_id=SRC)
    assert accounting.metadata_docs == [SID], "同 hash 商业真值变化必须走 metadata-only 路径"
    assert accounting.updated_docs == [] and accounting.new_docs == []
    assert stack.embedder.calls == [], "metadata-only 零重嵌(AC3)"
    versions = _versions(stack.sync_factory)
    assert len(versions) == 1 and versions[0].id == v1.id, "零版本分叉"

    for obj in _serving_objects(stack, versions[0]):
        assert obj.properties.get("purchasable") is False
        assert obj.properties.get("on_sale") is True
        assert obj.properties.get("commerce_synced_at") == D2, (
            "commerce_synced_at 必须如实取 Store snapshot date_modified"
        )
    row = _row(stack.sync_factory)
    assert row.metadata_["purchasable"] is False and row.metadata_["on_sale"] is True
    assert row.metadata_["date_modified"] == D2
    assert row.url == PERMALINK_V2
    for c in _chunk_copies(stack.sync_factory, versions[0]):
        assert c.props.get("purchasable") is False
        assert c.props.get("commerce_synced_at") == D2


# --------------------------------------------------------------------------- #
# Class C:content-changing commerce class(真实 STOCK/PRICE/SALE/QTY 变化)
#   —— 生产 5110:5950/5951 的真实路径;账本行 JSONB 必须随激活追平(RED 根因)
# --------------------------------------------------------------------------- #


def test_content_changed_stock_class_converges_ledger_and_serving(stack):
    """stock_status 变化(真实连接器:改 Stock 行 ⇒ hash 变)⇒ CONTENT_CHANGED
    ⇒ 重建收敛 serving **且 documents.metadata_ 追平**。

    RED(整改前):激活只同步 content_hash/chunk_count/title/url,
    行 JSONB 永久停留 v1 的 instock/D1 —— 生产 5110:5950/5951 实录。
    """
    t1 = _fetch_variation_doc({})
    t2 = _fetch_variation_doc({"stock_status": "outofstock", "date_modified": D2})
    assert t2.content_hash != t1.content_hash, "真实连接器下 stock_status 变化必改 content_hash"

    stack.builder.build_generation([t1], source_id=SRC)
    stack.embedder.calls.clear()

    accounting = stack.builder.build_generation([t2], source_id=SRC)
    assert accounting.updated_docs == [SID], "内容变更必须走 CONTENT_CHANGED 重建路径"
    assert accounting.metadata_docs == []
    assert len(stack.embedder.calls) >= 1, "内容变更必须真实重嵌(非 metadata-only)"
    versions = _versions(stack.sync_factory)
    assert len(versions) == 2, "内容变更 ⇒ 新版本(v2)"

    row = _row(stack.sync_factory)
    assert row.content_hash == versions[1].content_hash == t2.content_hash
    assert row.metadata_["stock_status"] == "outofstock", (
        "RED(#105 R2 根因): 激活路径必须回写 documents.metadata_ —— "
        "分类器权威(version.metadata_hash)已新而行 JSONB 停在 v1,永久陈旧"
    )
    assert row.metadata_["date_modified"] == D2
    assert versions[1].metadata_hash != versions[0].metadata_hash

    for obj in _serving_objects(stack, versions[1]):
        assert obj.properties.get("stock_status") == "outofstock"
        assert obj.properties.get("commerce_synced_at") == D2
    for c in _chunk_copies(stack.sync_factory, versions[1]):
        assert c.props.get("stock_status") == "outofstock"


def test_content_changed_price_sale_qty_class_converges(stack):
    """price/sale/stock_quantity 变化(真实连接器:改 Price/Sale/Stock 行)
    ⇒ CONTENT_CHANGED ⇒ 账本 + serving 商业真值收敛。
    """
    t1 = _fetch_variation_doc({})
    stack.builder.build_generation([t1], source_id=SRC)

    t2 = _fetch_variation_doc(
        {
            "price": "179.9",
            "regular_price": "199.9",
            "sale_price": "179.9",
            "on_sale": True,
            "stock_quantity": 3,
            "date_modified": D2,
        }
    )
    assert t2.content_hash != t1.content_hash, "price/sale/qty 变化经真实连接器必改 content"

    accounting = stack.builder.build_generation([t2], source_id=SRC)
    assert accounting.updated_docs == [SID]
    versions = _versions(stack.sync_factory)
    assert len(versions) == 2

    row = _row(stack.sync_factory)
    assert row.metadata_["price"] == "179.9"
    assert row.metadata_["sale_price"] == "179.9"
    assert row.metadata_["on_sale"] is True
    assert row.metadata_["stock_quantity"] == 3
    assert row.metadata_["date_modified"] == D2

    for obj in _serving_objects(stack, versions[1]):
        assert obj.properties.get("price") == "179.9"
        assert obj.properties.get("sale_price") == "179.9"
        assert obj.properties.get("on_sale") is True
        assert obj.properties.get("stock_quantity") == 3


def test_production_shape_stock_flip_then_repeat_sync_stays_converged(stack):
    """生产事故三连形状:T0 首灌(instock)→ T1 翻 outofstock(内容变更轮)
    → T2 重复同步(UNCHANGED)—— 账本行商业真值必须在 T1 追平且 T2 保持。

    RED(整改前):T1 轮行 JSONB 不追平 ⇒ T2 起 UNCHANGED ⇒ 永久陈旧
    (生产 2026-09-22 实录:行 date_modified 停在 v1 时代)。
    """
    t0 = _fetch_variation_doc({})
    t1 = _fetch_variation_doc({"stock_status": "outofstock", "date_modified": D2})

    stack.builder.build_generation([t0], source_id=SRC)
    stack.builder.build_generation([t1], source_id=SRC)
    row = _row(stack.sync_factory)
    assert row.metadata_["stock_status"] == "outofstock", "翻 stock 轮必须追平行 JSONB(根因)"
    assert row.metadata_["date_modified"] == D2

    repeat = stack.builder.build_generation([t1], source_id=SRC)
    assert repeat.unchanged_docs == [SID], "收敛后重复同步必须判 UNCHANGED"
    assert repeat.metadata_docs == [] and repeat.updated_docs == []
    row_after = _row(stack.sync_factory)
    assert row_after.metadata_["stock_status"] == "outofstock", "UNCHANGED 轮不得回退已收敛真值"
    assert row_after.metadata_["date_modified"] == D2


# --------------------------------------------------------------------------- #
# R2 blocker 2:metadata-only serving 失败 ⇒ fail-closed + 下轮可重试
# --------------------------------------------------------------------------- #


def test_metadata_only_serving_failure_is_fail_closed_and_retryable(
    stack, monkeypatch
):
    """Weaviate 对象更新失败 ⇒ **不推进任何权威状态**(version.metadata_hash /
    账本行 / chunk 副本原样),下一轮 normal sync 仍判 METADATA_CHANGED 重试并
    三面收敛;全程零重嵌、零版本分叉。旧实现「吞异常 + 账本先行」记录假收敛
    且永不自愈 —— 本测试锁定 fail-closed 语义。
    """
    t1 = _fetch_variation_doc({})
    t2 = _fetch_variation_doc(
        {
            "purchasable": False,
            "on_sale": True,
            "permalink": PERMALINK_V2,
            "date_modified": D2,
        }
    )
    stack.builder.build_generation([t1], source_id=SRC)
    v1 = _versions(stack.sync_factory)[0]
    row1 = _row(stack.sync_factory)
    v1_meta_hash = v1.metadata_hash
    stack.embedder.calls.clear()

    # 第一轮:serving 对象更新注入失败
    collection = stack.pipeline._collection

    def _boom(*args, **kwargs):
        raise RuntimeError("injected weaviate update outage")

    monkeypatch.setattr(collection.data, "update", _boom)
    with pytest.raises(RuntimeError, match="injected weaviate update outage"):
        stack.builder.build_generation([t2], source_id=SRC)
    monkeypatch.undo()

    # 失败轮:权威不前推(无假收敛)
    failed_versions = _versions(stack.sync_factory)
    assert len(failed_versions) == 1 and failed_versions[0].id == v1.id
    assert failed_versions[0].metadata_hash == v1_meta_hash, (
        "serving 失败绝不推进 DocumentVersion.metadata_hash(否则下轮 UNCHANGED 永不重试)"
    )
    row_failed = _row(stack.sync_factory)
    assert row_failed.metadata_ == row1.metadata_, "serving 失败不得记录假账本收敛"
    for c in _chunk_copies(stack.sync_factory, failed_versions[0]):
        assert c.props.get("purchasable") is True, "chunk 副本不得在失败轮前推"
    assert stack.embedder.calls == [], "重试路径同样零重嵌"

    # 第二轮:normal sync 自动重试(分类器仍见 metadata 差异)→ 三面收敛
    accounting = stack.builder.build_generation([t2], source_id=SRC)
    assert accounting.metadata_docs == [SID], "失败轮不前推权威 ⇒ 下轮仍 METADATA_CHANGED 可重试"
    versions = _versions(stack.sync_factory)
    assert len(versions) == 1 and versions[0].id == v1.id, "零版本分叉"
    assert stack.embedder.calls == [], "全程零重嵌"

    for obj in _serving_objects(stack, versions[0]):
        assert obj.properties.get("purchasable") is False
        assert obj.properties.get("commerce_synced_at") == D2
    row2 = _row(stack.sync_factory)
    assert row2.metadata_["purchasable"] is False
    assert row2.metadata_["date_modified"] == D2
    assert versions[0].metadata_hash != v1_meta_hash, "成功轮才前推权威"
    for c in _chunk_copies(stack.sync_factory, versions[0]):
        assert c.props.get("purchasable") is False
        assert c.props.get("commerce_synced_at") == D2


@pytest.mark.unit
def test_repeat_sync_idempotent_after_convergence(stack):
    """AC4:收敛后重复相同 sync ⇒ UNCHANGED、零写入(守卫,真实连接器文档)。"""
    t2 = _fetch_variation_doc(
        {
            "purchasable": False,
            "on_sale": True,
            "permalink": PERMALINK_V2,
            "date_modified": D2,
        }
    )
    stack.builder.build_generation([t2], source_id=SRC)
    stack.embedder.calls.clear()

    repeat = stack.builder.build_generation([t2], source_id=SRC)
    assert repeat.unchanged_docs == [SID], "收敛后重复 sync 必须判 UNCHANGED(幂等)"
    assert repeat.metadata_docs == [] and repeat.new_docs == [] and repeat.updated_docs == []
    assert stack.embedder.calls == [], "UNCHANGED 零 embed"
    versions = _versions(stack.sync_factory)
    assert len(versions) == 1
    for obj in _serving_objects(stack, versions[0]):
        assert obj.properties.get("purchasable") is False
        assert obj.properties.get("commerce_synced_at") == D2
