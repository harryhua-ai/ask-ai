"""Issue #28 RED — WooCommerce variable-product variation truth (Track B1).

表征性 RED(RCA 证据,非实现):
- 契约:v1.6.4 Track B §B1-1..B1-3(docs/v164-iteration-contracts-20260913,
  docs/engineering/tasks/v164-track-b-evidence-authority-commercial-truth-contract.md)
- 现状(main b338c3c):连接器只拉 /wp-json/wc/v3/products 父产品,
  从不调用 variations 端点;Weaviate COLLECTION_PROPERTIES 无任何 commerce
  property;_build_props 不投影 commerce 元数据。
- 本文件全部断言按契约 §4 待 pin 的 B1→B2 接口提案编写
  (variation_identity_key = "<product_id>:<variation_id>",见 RCA 报告);
  当前 main 实测 FAIL(RED),pin 后由实现阶段转 GREEN。

零外网:全部 fixture mock,不触真实 Store API。
"""

from unittest.mock import MagicMock, patch

import pytest

from backend.connectors.registry import ConnectorRegistry, SourceConfig


def _make_config(**overrides: object) -> SourceConfig:
    config: dict[str, object] = {
        "store_url": "https://www.example.com",
        "consumer_key": "ck_test",
        "consumer_secret": "cs_test",
    }
    config.update(overrides)  # type: ignore[arg-type]
    return SourceConfig(
        id="woocommerce-mall",
        type="woocommerce",
        product="commercial",
        enabled=True,
        config=config,  # type: ignore[arg-type]
        sync_interval="1h",
    )


def _mock_variable_product(**overrides: object) -> dict:
    """WooCommerce variable product JSON(wc/v3 products 端点形态)。"""
    p: dict[str, object] = {
        "id": 319,
        "name": "NeoEyes NE101 Modular Sensing Camera",
        "slug": "neoeyes-ne101",
        "permalink": "https://www.example.com/store/neoeyes-ne101/",
        "sku": "",
        "price": "69",
        "regular_price": "",
        "sale_price": "",
        "stock_status": "instock",
        "stock_quantity": None,
        "type": "variable",
        "status": "publish",
        "date_modified": "2026-08-12T10:40:27",
        "categories": [{"id": 167, "name": "NE101", "slug": "ne101"}],
        "variations": [5229, 5230],
        "attributes": [
            {
                "id": 6,
                "name": "Connectivity",
                "slug": "pa_ne101-models",
                "variation": True,
                "options": ["WiFi", "LTE Cat.1 North America"],
            }
        ],
        "short_description": "<p>NE101 camera.</p>",
        "description": "<p>Full description.</p>",
    }
    p.update(overrides)
    return p


def _mock_simple_product() -> dict:
    return {
        "id": 1984,
        "name": "NeoEyes NE101 Dev Kit",
        "slug": "neoeyes-ne101-dev-kit",
        "permalink": "https://www.example.com/store/neoeyes-ne101-dev-kit/",
        "sku": "76.001.000001",
        "price": "129",
        "regular_price": "129",
        "sale_price": "",
        "stock_status": "instock",
        "stock_quantity": 7,
        "type": "simple",
        "status": "publish",
        "date_modified": "2026-08-12T10:40:27",
        "categories": [{"id": 167, "name": "NE101", "slug": "ne101"}],
        "short_description": "<p>Dev kit.</p>",
        "description": "<p>Full description.</p>",
    }


def _mock_variation(vid: int, **overrides: object) -> dict:
    """WooCommerce variation JSON(wc/v3 products/{id}/variations 端点形态)。

    字段对照 2026-09-15 只读核验的 camthink.ai 真实端点:
    id/parent_id/sku/price/regular_price/sale_price/on_sale/stock_status/
    stock_quantity/purchasable/permalink/attributes[name,slug,option]/
    status/date_modified。
    """
    v: dict[str, object] = {
        "id": vid,
        "parent_id": 319,
        "sku": f"73.001.00000{vid}G",
        "price": "108",
        "regular_price": "108",
        "sale_price": "",
        "on_sale": False,
        "stock_status": "instock",
        "stock_quantity": None,
        "purchasable": True,
        "permalink": (
            "https://www.example.com/store/neoeyes-ne101/"
            f"?attribute_pa_ne101-models=ne101-hl01&attribute_pa_lens=60-15cm&variation_id={vid}"
        ),
        "attributes": [
            {
                "id": 6,
                "name": "Connectivity",
                "slug": "pa_ne101-models",
                "option": "Wi-Fi Halow 915 MHz",
            },
            {"id": 15, "name": "Lens", "slug": "pa_lens", "option": "60°FOV, 15CM"},
        ],
        "status": "publish",
        "date_modified": "2026-07-10T18:03:06",
    }
    v.update(overrides)
    return v


def _patch_connector_routes(connector, products: list[dict], variation_routes: dict[int, list[dict]]):
    """按 API 路径 mock connector._get(products 与 per-product variations)。"""

    def _fake_get(path: str, *, params=None):
        resp = MagicMock()
        resp.raise_for_status = MagicMock()
        if path.endswith("/products"):
            resp.json.return_value = products
        else:
            matched = False
            for pid, variations in variation_routes.items():
                if path == f"/wp-json/wc/v3/products/{pid}/variations":
                    resp.json.return_value = variations
                    matched = True
                    break
            if not matched:
                raise AssertionError(f"unexpected connector request: {path}")
        return resp

    return patch.object(connector, "_get", side_effect=_fake_get)


# --------------------------------------------------------------------------- #
# B1-1: variable product ⇒ parent + N variation documents(端点真值)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_variable_product_yields_parent_plus_variation_documents():
    """B1-1 RED:variable product 摄取必须产出父文档 + 每 variation 一档。

    当前 main:fetch_all 只拉 products 端点,从不调 variations 端点,
    返回 1 个文档 ⇒ 本测试 FAIL(RED)。
    """
    import backend.connectors.woocommerce  # noqa: F401 - 触发 @register

    connector = ConnectorRegistry.create(_make_config())
    products = [_mock_variable_product(), _mock_simple_product()]
    variation_routes = {
        319: [_mock_variation(5229), _mock_variation(5230)],
    }
    with _patch_connector_routes(connector, products, variation_routes):
        docs = list(connector.fetch_all())

    # 父产品 1 + 简单产品 1 + 两个真实 variation 各 1 = 4(禁止笛卡尔合成:
    # 只有端点列出的 2 个 variation,即便 attributes 理论组合是 2×2)
    assert len(docs) == 4, (
        f"RED(B1-1): 期望 4 文档(2 父 + 2 variation),实得 {len(docs)}; "
        "当前连接器不摄取 variations 端点"
    )
    var_docs = [d for d in docs if "/319/" in d.source_id]
    assert {d.source_id for d in var_docs} == {
        "woocommerce-mall/319/5229",
        "woocommerce-mall/319/5230",
    }, "variation source_id 必须携带 product_id/variation_id 双重身份(反混淆)"


@pytest.mark.unit
def test_variation_document_structured_metadata():
    """B1-1/B1-3 RED:variation 文档必须带结构化商业元数据(身份键贯穿)。

    断言的字段名 = B1→B2 接口提案(契约 §4 待 pin):
    variation_identity_key = "<product_id>:<variation_id>"。
    """
    import backend.connectors.woocommerce  # noqa: F401

    connector = ConnectorRegistry.create(_make_config())
    products = [_mock_variable_product()]
    variation_routes = {319: [_mock_variation(5243)]}
    with _patch_connector_routes(connector, products, variation_routes):
        docs = list(connector.fetch_all())

    var_docs = [d for d in docs if d.metadata.get("variation_id") == 5243]
    assert var_docs, (
        "RED(B1-1): 无 variation 文档 —— 连接器零 variations 摄取"
    )
    meta = var_docs[0].metadata
    # 身份(反混淆贯穿键)
    assert meta["variation_identity_key"] == "319:5243"
    assert meta["product_id"] == 319
    # 商业真值
    assert meta["sku"] == "73.001.000005243G"
    assert meta["price"] == "108"
    assert meta["regular_price"] == "108"
    assert meta["sale_price"] == ""
    assert meta["on_sale"] is False
    assert meta["stock_status"] == "instock"
    assert meta["purchasable"] is True
    # 结构化 attributes(非 prose)
    attrs = meta["attributes"]
    assert {"slug": "pa_ne101-models", "option": "Wi-Fi Halow 915 MHz"} in attrs
    assert {"slug": "pa_lens", "option": "60°FOV, 15CM"} in attrs
    # canonical identity + freshness
    assert var_docs[0].url == meta["permalink"]
    assert meta["date_modified"] == "2026-07-10T18:03:06"
    # doc 类型可判别(下游 B2 依赖)
    assert meta["commerce_type"] == "variation"
    assert var_docs[0].content_type == "variation"
    assert var_docs[0].source_type == "woocommerce"


@pytest.mark.unit
def test_simple_product_unchanged_single_document():
    """契约 §4.1: simple / non-variable 产品行为不变(单文档,零 variation 字段)。"""
    import backend.connectors.woocommerce  # noqa: F401

    connector = ConnectorRegistry.create(_make_config())
    products = [_mock_simple_product()]
    with _patch_connector_routes(connector, products, {}):
        docs = list(connector.fetch_all())

    assert len(docs) == 1
    d = docs[0]
    assert d.source_id == "woocommerce-mall/1984"
    assert d.metadata.get("variation_id") in (None, 0)
    assert d.metadata.get("commerce_type") in ("", None, "product", "simple")
    assert "129" in d.content


@pytest.mark.unit
def test_no_cartesian_synthesis_only_listed_variations():
    """B1-2 RED:只代表端点列出的 variation(20 真实,不合成理论组合)。

    fixture: attributes 提供 2 个 connectivity 选项,端点只列出 1 个
    variation ⇒ 必须恰好 1 个 variation 文档(2×4 笛卡尔积禁止)。
    """
    import backend.connectors.woocommerce  # noqa: F401

    connector = ConnectorRegistry.create(_make_config())
    products = [_mock_variable_product()]
    variation_routes = {319: [_mock_variation(5229)]}  # 端点只返回 1 个
    with _patch_connector_routes(connector, products, variation_routes):
        docs = list(connector.fetch_all())

    var_docs = [d for d in docs if "/319/" in d.source_id]
    assert len(var_docs) == 1, (
        f"RED(B1-2): 端点只列 1 variation,实得 {len(var_docs)} "
        "(合成组合或漏摄取)"
    )


# --------------------------------------------------------------------------- #
# B1-3: 变体身份作为结构化 metadata 贯穿 chunk 持久化
# --------------------------------------------------------------------------- #


def _make_chunk(doc):
    from backend.pipeline.chunk import Chunk

    return Chunk(
        text=doc.content,
        document=doc,
        chunk_index=0,
        total_chunks=1,
        start_char=0,
        end_char=len(doc.content),
    )


def _variation_raw_document() -> object:
    """构造 variation RawDocument(按上面连接器契约的产出形态)。"""
    from backend.connectors.base import RawDocument

    return RawDocument(
        source_id="woocommerce-mall/319/5243",
        source_type="woocommerce",
        product="ne101",
        title="NeoEyes NE101 Modular Sensing Camera — Wi-Fi Halow 915 MHz / 60°FOV, 15CM",
        content="# NeoEyes NE101 — Wi-Fi Halow 915 MHz / 60°FOV, 15CM\n\nSKU: 73.001.00000770G\nPrice: $108",
        url="https://www.example.com/store/neoeyes-ne101/?attribute_pa_ne101-models=ne101-hl01&attribute_pa_lens=60-15cm",
        metadata={
            "product_id": 319,
            "variation_id": 5243,
            "variation_identity_key": "319:5243",
            "commerce_type": "variation",
            "sku": "73.001.00000770G",
            "price": "108",
            "regular_price": "108",
            "sale_price": "",
            "on_sale": False,
            "stock_status": "instock",
            "stock_quantity": None,
            "purchasable": True,
            "attributes": [
                {"slug": "pa_ne101-models", "option": "Wi-Fi Halow 915 MHz"},
                {"slug": "pa_lens", "option": "60°FOV, 15CM"},
            ],
            "permalink": "https://www.example.com/store/neoeyes-ne101/?attribute_pa_ne101-models=ne101-hl01&attribute_pa_lens=60-15cm",
            "date_modified": "2026-07-10T18:03:06",
        },
        content_hash="deadbeef",
        channel_visibility=("widget", "api"),
        branch="",
        content_type="variation",
    )


@pytest.mark.unit
def test_variation_identity_survives_chunk_props_projection():
    """B1-3 RED:chunk 持久化必须携带结构化 variation 身份/商业字段。

    当前 main:ingest._build_props 不投影任何 commerce 元数据 ⇒ FAIL(RED)。
    """
    from backend.pipeline.ingest import _build_props

    doc = _variation_raw_document()
    props = _build_props(_make_chunk(doc), doc)

    for field in (
        "variation_identity_key",
        "product_id",
        "variation_id",
        "commerce_type",
        "sku",
        "price",
        "regular_price",
        "sale_price",
        "stock_status",
        "purchasable",
        "commerce_synced_at",
    ):
        assert field in props, f"RED(B1-3): Weaviate props 缺 {field}"
    assert props["variation_identity_key"] == "319:5243"
    # 反混淆:不同 variation 的 identity key 必然不同(两 variation / 两产品不合并)
    other = _variation_raw_document()
    # RawDocument frozen:metadata dict 原位变异(不重赋值属性)
    other.metadata["variation_id"] = 5229
    other.metadata["variation_identity_key"] = "319:5229"
    other_props = _build_props(_make_chunk(other), other)
    assert other_props["variation_identity_key"] != props["variation_identity_key"]


@pytest.mark.unit
def test_collection_schema_declares_commerce_properties():
    """B1-3 RED:Weaviate schema 定义必须声明 commerce property(加性演进)。

    当前 main:COLLECTION_PROPERTIES 无任何 commerce 字段 ⇒ FAIL(RED)。
    生产只读核验(2026-09-15,43.132.189.162 /v1/schema)同样为零 commerce
    property,24 个 property 全部非商业。
    """
    from backend.pipeline.ingest import COLLECTION_PROPERTIES

    names = {n for n, _ in COLLECTION_PROPERTIES}
    for field in (
        "variation_identity_key",
        "variation_id",
        "product_id",
        "commerce_type",
        "sku",
        "price",
        "regular_price",
        "sale_price",
        "stock_status",
        "purchasable",
    ):
        assert field in names, f"RED(B1-3): COLLECTION_PROPERTIES 缺 {field}"


# --------------------------------------------------------------------------- #
# B1-5: B1→B2 接口 — identity key 规则(供契约 §4 pin)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_variation_identity_key_is_product_scoped_deterministic():
    """B1-5 RED:identity key 必须是 product+variation 复合、确定性可重导。

    提案 pin 值:f"{product_id}:{variation_id}"(十进制,无填充)。
    """
    import backend.connectors.woocommerce  # noqa: F401

    connector = ConnectorRegistry.create(_make_config())
    products = [_mock_variable_product()]
    variation_routes = {319: [_mock_variation(5229), _mock_variation(358)]}
    with _patch_connector_routes(connector, products, variation_routes):
        docs = list(connector.fetch_all())

    keys = {
        d.metadata["variation_identity_key"]
        for d in docs
        if d.metadata.get("variation_id")
    }
    assert keys == {"319:5229", "319:358"}, (
        f"RED(B1-5): identity key 提案未实现,实得 {keys}"
    )
