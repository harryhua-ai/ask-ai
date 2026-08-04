"""WooCommerceConnector 测试(mock HTTP,不触真实 API)。

测试设计:
- 单测,标记 ``@pytest.mark.unit``,mock ``_get`` 返回构造的 product JSON
- 不触真实 WooCommerce API,不依赖 DB
- 覆盖:注册、fetch_all、fetch_changes(modified_after)、fetch_deleted(诚实降级)、
  HTML 清洗(含 script/style 跳过)、category→product 映射
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from backend.connectors.registry import ConnectorRegistry, SourceConfig


def _make_config(**overrides: object) -> SourceConfig:
    """构造一个 woocommerce SourceConfig(凭证用测试占位值)。"""
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


def _mock_product(**overrides: object) -> dict:
    """构造一个 WooCommerce product JSON(测试用,字段对齐真实 API v3)。"""
    p: dict[str, object] = {
        "id": 100,
        "name": "NE301 Sensor Kit",
        "slug": "ne301-sensor-kit",
        "permalink": "https://www.example.com/store/ne301-sensor-kit/",
        "sku": "76.002.000003",
        "price": "88",
        "regular_price": "99",
        "sale_price": "88",
        "stock_status": "instock",
        "stock_quantity": 15,
        "type": "simple",
        "status": "publish",
        "date_modified": "2026-07-28T10:22:31",
        "categories": [{"id": 167, "name": "NE301", "slug": "ne301"}],
        "short_description": "<p>Multi-<strong>sensor</strong> kit for NE301.</p>",
        "description": "<h2>Overview</h2><p>Full description here.</p>",
        "images": [{"src": "https://www.example.com/img.jpg"}],
    }
    p.update(overrides)
    return p


@pytest.mark.unit
def test_woocommerce_registered():
    """注册装饰器绑定 'woocommerce' 类型。"""
    import backend.connectors.woocommerce  # noqa: F401 - 触发 @register

    assert "woocommerce" in ConnectorRegistry._connectors


@pytest.mark.unit
def test_woocommerce_fetch_all_returns_raw_documents():
    """fetch_all 拉 products → RawDocument,HTML 清洗,字段拼接。"""
    import backend.connectors.woocommerce  # noqa: F401

    cfg = _make_config()
    connector = ConnectorRegistry.create(cfg)
    mock_resp = MagicMock()
    mock_resp.json.return_value = [_mock_product()]
    mock_resp.headers = {"X-WP-Total": "1"}
    mock_resp.raise_for_status = MagicMock()
    with patch.object(connector, "_get", return_value=mock_resp):
        docs = list(connector.fetch_all())
    assert len(docs) == 1
    d = docs[0]
    assert d.source_type == "woocommerce"
    assert d.source_id == "woocommerce-mall/100"  # cfg.id/product_id
    assert "NE301 Sensor Kit" in d.title
    assert "88" in d.content  # price
    assert "76.002.000003" in d.content  # sku
    # HTML 清洗:<strong> 标签去除
    assert "<strong>" not in d.content
    assert "sensor" in d.content  # 文本保留
    assert d.product == "ne301"  # category 映射
    assert d.url == "https://www.example.com/store/ne301-sensor-kit/"
    assert d.channel_visibility == ("widget", "api")


@pytest.mark.unit
def test_woocommerce_fetch_changes_uses_modified_after():
    """fetch_changes 传 modified_after 参数。"""
    import backend.connectors.woocommerce  # noqa: F401

    cfg = _make_config()
    connector = ConnectorRegistry.create(cfg)
    mock_resp = MagicMock()
    mock_resp.json.return_value = []
    mock_resp.headers = {"X-WP-Total": "0"}
    mock_resp.raise_for_status = MagicMock()
    with patch.object(connector, "_get", return_value=mock_resp) as mock_get:
        since = datetime.now(UTC) - timedelta(hours=24)
        list(connector.fetch_changes(since))
    # 验证 params 含 modified_after
    call_kwargs = mock_get.call_args
    params = call_kwargs.kwargs.get("params", {})
    assert "modified_after" in params


@pytest.mark.unit
def test_woocommerce_fetch_deleted_returns_empty_honest_degradation():
    """fetch_deleted 严格匹配 Protocol(since),返回 [](诚实降级)。

    sync.py:213 调用 ``fetch_deleted(since)`` 不传 known_ids,故 WooCommerce
    删除检测降级为不检测(与 filesystem.py:182-189 范式一致)。
    加 known_ids 参数会让 mock 测试自洽但生产静默失效(silent failure),
    故严格匹配 Protocol 签名。
    """
    import backend.connectors.woocommerce  # noqa: F401

    cfg = _make_config()
    connector = ConnectorRegistry.create(cfg)
    deleted = connector.fetch_deleted(datetime.now(UTC))
    assert deleted == []


@pytest.mark.unit
def test_woocommerce_html_cleaning_strips_tags_and_skips_script_style():
    """HTML 标签清洗为纯文本;script/style 块内容被跳过(不混进 CSS/JS)。"""
    import backend.connectors.woocommerce  # noqa: F401

    cfg = _make_config()
    connector = ConnectorRegistry.create(cfg)
    html = (
        "<h2>Title</h2>"
        "<p>Text with <a href='x'>link</a> and <strong>bold</strong>.</p>"
        "<script>alert(1)</script>"
        "<style>.x{color:red}</style>"
    )
    text = connector._clean_html(html)
    assert "<" not in text
    assert ">" not in text
    assert "Title" in text and "bold" in text
    # script/style 内容被排除
    assert "alert" not in text
    assert "color:red" not in text
    assert ".x{" not in text


@pytest.mark.unit
def test_woocommerce_html_cleaning_handles_malformed_tags_and_keeps_lt():
    """畸形标签(``</strong >``、带属性未闭合)被清扫,合法 ``<`` 比较符保留。

    Real-Run 发现 WooCommerce 产品描述含实体编码泄露的 ``</strong >``
    (空格畸形标签,HTMLParser 不识别),以及合法的 ``<5%``、``< -33%``
    比较文本。清洗须:删畸形标签残留,保留合法比较符号。
    """
    import backend.connectors.woocommerce  # noqa: F401

    cfg = _make_config()
    connector = ConnectorRegistry.create(cfg)
    # 模拟 Real-Run 发现的真实畸形 HTML
    html = (
        "<p>Distortion &lt; 1% and haze &lt;5%.</p>"
        "<p><strong>Spec</strong> text &lt;/strong &gt; leak</p>"
    )
    text = connector._clean_html(html)
    # 畸形标签残留被删(</strong > 不在输出)
    assert "</strong" not in text
    assert "<strong" not in text
    # 合法 < 比较符保留(语义信息)
    assert "< 1%" in text or "<1%" in text
    assert "<5%" in text


@pytest.mark.unit
def test_woocommerce_category_to_product_mapping():
    """category name → product 映射(NE301→ne301,无匹配→commercial)。"""
    import backend.connectors.woocommerce  # noqa: F401

    cfg = _make_config()
    connector = ConnectorRegistry.create(cfg)
    assert connector._category_to_product([{"name": "NE301"}]) == "ne301"
    assert connector._category_to_product([{"name": "Accessories"}]) == "accessories"
    assert connector._category_to_product([{"name": "Unknown"}]) == "commercial"
    assert connector._category_to_product([]) == "commercial"


@pytest.mark.unit
def test_woocommerce_category_mapping_decodes_html_entities():
    """WooCommerce API 返回的 category name 含 HTML 实体(``&amp;``),需解码。

    Real-Run 发现 ``Modules &amp; Dev Kits`` 不解码会 miss 映射 → commercial,
    应解码后匹配 ``modules & dev kits`` → aitoolstack。
    """
    import backend.connectors.woocommerce  # noqa: F401

    cfg = _make_config()
    connector = ConnectorRegistry.create(cfg)
    # &amp; 实体 — Real-Run 真实数据
    assert (
        connector._category_to_product([{"name": "Modules &amp; Dev Kits"}])
        == "aitoolstack"
    )
    # AI Cameras 实体安全
    assert connector._category_to_product([{"name": "AI Cameras"}]) == "aitoolstack"
    # 多 category:列表顺序遍历,先命中者胜出(Real-Run 中 AI Cameras 在 NE 前时→aitoolstack,
    # 与 plan M1 期望 aitoolstack=AI Cameras(5)+Edge AI Boxes(2)+Modules&Dev Kits(14)=21 一致)
    assert (
        connector._category_to_product(
            [{"name": "AI Cameras"}, {"name": "NE301"}]
        )
        == "aitoolstack"  # AI Cameras 在前,先命中
    )
    # 反序:NE301 在前 → ne301
    assert (
        connector._category_to_product(
            [{"name": "NE301"}, {"name": "AI Cameras"}]
        )
        == "ne301"
    )


@pytest.mark.unit
def test_woocommerce_env_fallback_reads_creds_from_env(monkeypatch):
    """config 缺凭证时,fallback 到 WOOCOMMERCE_* 环境变量。"""
    import backend.connectors.woocommerce  # noqa: F401

    monkeypatch.setenv("WOOCOMMERCE_STORE_URL", "https://env.example.com")
    monkeypatch.setenv("WOOCOMMERCE_CONSUMER_KEY", "ck_env")
    monkeypatch.setenv("WOOCOMMERCE_CONSUMER_SECRET", "cs_env")
    cfg = SourceConfig(
        id="woocommerce-mall",
        type="woocommerce",
        product="commercial",
        enabled=True,
        config={},  # 无凭证,强制走 env
        sync_interval="1h",
    )
    connector = ConnectorRegistry.create(cfg)
    assert connector._store_url == "https://env.example.com"
    assert connector._key == "ck_env"
    assert connector._secret == "cs_env"


@pytest.mark.unit
def test_woocommerce_config_takes_precedence_over_env(monkeypatch):
    """config 凭证优先于环境变量(防 env 污染覆盖显式配置)。"""
    import backend.connectors.woocommerce  # noqa: F401

    monkeypatch.setenv("WOOCOMMERCE_CONSUMER_KEY", "ck_env_should_lose")
    cfg = _make_config(consumer_key="ck_config_wins")
    connector = ConnectorRegistry.create(cfg)
    assert connector._key == "ck_config_wins"


@pytest.mark.unit
def test_woocommerce_missing_creds_raises_value_error(monkeypatch):
    """config 与 env 都无凭证 → ValueError(快速失败,不静默空 auth)。"""
    import backend.connectors.woocommerce  # noqa: F401

    monkeypatch.delenv("WOOCOMMERCE_STORE_URL", raising=False)
    monkeypatch.delenv("WOOCOMMERCE_CONSUMER_KEY", raising=False)
    monkeypatch.delenv("WOOCOMMERCE_CONSUMER_SECRET", raising=False)
    cfg = SourceConfig(
        id="woocommerce-mall",
        type="woocommerce",
        product="commercial",
        enabled=True,
        config={},  # 全空
        sync_interval="1h",
    )
    with pytest.raises(ValueError, match="凭证缺失"):
        ConnectorRegistry.create(cfg)
