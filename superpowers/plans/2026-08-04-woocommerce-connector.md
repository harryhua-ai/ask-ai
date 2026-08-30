# WooCommerce 商城 Connector 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 实现 `WooCommerceConnector`(products → RawDocument),作为 `commercial` 意图数据源,接入 ask-ai 数据源框架。

**Architecture:** SDKConnector 模式 — WooCommerce REST API v3(Basic Auth)拉 products,HTML 清洗 description/short_description,结构化字段拼成可检索文本,映射 category→product。全量 40 产品(小规模,无需分页优化);增量用 `modified_after`;删除检测对比 DB vs API。

**Tech Stack:** Python 3.12 / requests 2.34(已装)/ pytest(MagicMock mock HTTP)/ WooCommerce REST API v3。

**Spec:** memory `woocommerce-mall-connector.md` + `ask-ai-product-scope.md`(commercial 数据源)

**Terminal target:** implementation(tested branch,不 integrate — P0#2 reindex 占用 Weaviate)

## Analysis Gate Delta(已核实)

- `DataSourceConnector` Protocol(base.py:49-66):`fetch_all` / `fetch_changes(since)` / `fetch_deleted(since)` — connector 需实现三个
- `@ConnectorRegistry.register("woocommerce")` 注册(registry.py:56)
- `SourceConfig.config` dict 透传 connector 参数(registry.py:39)
- `RawDocument`(base.py:12-46):`source_type="woocommerce"`,`channel_visibility` 从 SourceConfig 透传
- `requests` 2.34 已装,无新依赖
- HTML 清洗:用标准库 `html.parser`(无新依赖)
- WooCommerce 规模:40 产品 / 6 分类(Accessories 18 / AI Cameras 5 / Edge AI Boxes 2 / Modules & Dev Kits 14 / NE101/NE301/NE503)
- `product` 映射:category name → ne101/ne301/ne503/accessories/aitoolstack 等(无 category 的归 "commercial")
- sync.py 已通用,connector 实现 Protocol 即可(sync.py:168-215)

## Global Constraints

- 测试用 `TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test`
- venv: `.venv/bin/python`
- 凭证从 `.env`(`WOOCOMMERCE_STORE_URL` / `WOOCOMMERCE_CONSUMER_KEY` / `WOOCOMMERCE_CONSUMER_SECRET`),**永不硬编码**
- `source_type="woocommerce"`(用于 P0#1 intent 路由 commercial boost 桶)
- 不碰 working tree 未提交改动(query_rewrite.py / widget / conftest.py)
- 不 integrate(P0#2 reindex 跑中,不抢 Weaviate)

---

## File Structure

| 文件 | 责任 | 操作 |
|---|---|---|
| `backend/connectors/woocommerce.py` | WooCommerceConnector 实现 | 新增 |
| `backend/connectors/__init__.py` | 触发 register(若需要) | 检查 |
| `tests/connectors/test_woocommerce.py` | connector 单测(mock HTTP) | 新增 |
| `config/data_sources.yaml` | 加 woocommerce 源配置(示例) | 修改(可选,DB 为准) |

---

## Task 1: WooCommerceConnector 核心实现

**Files:**
- Create: `backend/connectors/woocommerce.py`
- Test: `tests/connectors/test_woocommerce.py`

**Interfaces:**
- Consumes: `DataSourceConnector`、`RawDocument`(base.py)、`SourceConfig`、`ConnectorRegistry`(registry.py)
- Produces: `WooCommerceConnector`(register "woocommerce")

- [ ] **Step 1: 写失败测试**

`tests/connectors/test_woocommerce.py`:

```python
"""WooCommerceConnector 测试(mock HTTP,不触真实 API)。"""

import json
from datetime import UTC, datetime, timedelta
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


def _mock_product(**overrides):
    """构造一个 WooCommerce product JSON(测试用)。"""
    p = {
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
    import backend.connectors.woocommerce
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
    import backend.connectors.woocommerce
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

    sync.py:213 调用 fetch_deleted(since) 不传 known_ids,故 WooCommerce
    删除检测降级为不检测(与 filesystem.py:182-189 范式一致)。
    加 known_ids 参数会让 mock 测试自洽但生产静默失效(silent failure),
    故严格匹配 Protocol 签名。
    """
    import backend.connectors.woocommerce
    cfg = _make_config()
    connector = ConnectorRegistry.create(cfg)
    deleted = connector.fetch_deleted(datetime.now(UTC))
    assert deleted == []


@pytest.mark.unit
def test_woocommerce_html_cleaning_strips_tags_and_skips_script_style():
    """HTML 标签清洗为纯文本;script/style 块内容被跳过(不混进 CSS/JS)。"""
    import backend.connectors.woocommerce
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
def test_woocommerce_category_to_product_mapping():
    """category name → product 映射(NE301→ne301,无匹配→commercial)。"""
    import backend.connectors.woocommerce
    cfg = _make_config()
    connector = ConnectorRegistry.create(cfg)
    assert connector._category_to_product([{"name": "NE301"}]) == "ne301"
    assert connector._category_to_product([{"name": "Accessories"}]) == "accessories"
    assert connector._category_to_product([{"name": "Unknown"}]) == "commercial"
    assert connector._category_to_product([]) == "commercial"
```

- [ ] **Step 2: 运行测试,确认失败**

```bash
TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test .venv/bin/python -m pytest tests/connectors/test_woocommerce.py -q
```

Expected: FAIL(模块不存在)

- [ ] **Step 3: 实现 WooCommerceConnector**

`backend/connectors/woocommerce.py`:

```python
"""WooCommerce 商城数据源 Connector(commercial 意图数据源)。

通过 WooCommerce REST API v3(Basic Auth)拉 products,转 RawDocument:
- 全量:分页拉所有 publish 产品
- 增量:``modified_after`` 参数拉变更
- 删除检测:对比 DB 已知 IDs vs 当前 API IDs(需调用方传 known_ids)

产品 → RawDocument 映射:
- 结构化字段(name/price/sku/stock/categories)拼成可检索文本(BM25/dense 都能命中)
- short_description / description 的 HTML 清洗为纯文本
- category name → product 映射(NE301→ne301 等)
- source_type = "woocommerce"(供 P0#1 commercial 意图 boost 桶路由)

凭证从 SourceConfig.config 读(store_url / consumer_key / consumer_secret),
永不硬编码。
"""

import hashlib
import logging
from collections.abc import Iterator
from datetime import datetime
from html.parser import HTMLParser
from typing import Any

import requests

from backend.connectors.base import RawDocument
from backend.connectors.registry import ConnectorRegistry, SourceConfig

logger = logging.getLogger(__name__)

# category name(小写) → product 标识
_CATEGORY_MAP = {
    "ne101": "ne101",
    "ne301": "ne301",
    "ne503": "ne503",
    "accessories": "accessories",
    "ai cameras": "aitoolstack",
    "edge ai boxes": "aitoolstack",
    "modules & dev kits": "aitoolstack",
}


class _HTMLTextExtractor(HTMLParser):
    """从 HTML 提取纯文本(去标签),跳过 script/style 块内容。

    script/style 的文本内容(CSS/JS 代码)会被 handle_data 接收,
    若不跳过会混进检索内容。用 _ignore_depth 计数,在 script/style
    标签内时不收集 data。
    """

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._ignore_depth: int = 0  # >0 表示在 script/style 内

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ARG002
        if tag in ("script", "style"):
            self._ignore_depth += 1

    def handle_endtag(self, tag: str) -> None:  # noqa: ARG002
        if tag in ("script", "style") and self._ignore_depth > 0:
            self._ignore_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._ignore_depth > 0:
            return  # 跳过 script/style 内容
        stripped = data.strip()
        if stripped:
            self._parts.append(stripped)

    def get_text(self) -> str:
        return " ".join(self._parts)


class WooCommerceConnector:
    """WooCommerce 商城 Connector(实现 DataSourceConnector Protocol)。

    通过 ``SourceConfig.config`` 提供参数:
    - ``store_url`` (str, 必填): 商城站点(如 ``https://www.camthink.ai``)
    - ``consumer_key`` (str, 必填): WooCommerce REST API key
    - ``consumer_secret`` (str, 必填): WooCommerce REST API secret
    - ``per_page`` (int, 可选): 分页大小,默认 100(单次拉全量,40 产品)
    """

    def __init__(self, config: SourceConfig) -> None:
        self._config = config
        self._store_url: str = config.config["store_url"].rstrip("/")
        self._key: str = config.config["consumer_key"]
        self._secret: str = config.config["consumer_secret"]
        self._per_page: int = int(config.config.get("per_page", 100))
        self._channel_visibility: tuple[str, ...] = config.channel_visibility

    @property
    def source_id(self) -> str:
        return self._config.id

    @property
    def product(self) -> str:
        return self._config.product

    def _get(self, path: str, *, params: dict | None = None) -> Any:
        """发起 GET 请求(Basic Auth)。

        Args:
            path: API 路径(如 ``/wp-json/wc/v3/products``)。
            params: 查询参数。

        Returns:
            Response 对象。
        """
        url = f"{self._store_url}{path}"
        return requests.get(
            url,
            auth=(self._key, self._secret),
            params=params or {},
            headers={"User-Agent": "ask-ai/1.0"},
            timeout=30,
        )

    @staticmethod
    def _clean_html(html: str) -> str:
        """HTML → 纯文本(去标签,保留文本内容)。"""
        extractor = _HTMLTextExtractor()
        extractor.feed(html or "")
        return extractor.get_text()

    @staticmethod
    def _category_to_product(categories: list[dict]) -> str:
        """category name → product 标识(无匹配 → commercial)。"""
        for cat in categories or []:
            name = (cat.get("name") or "").lower()
            if name in _CATEGORY_MAP:
                return _CATEGORY_MAP[name]
        return "commercial"

    def _product_to_document(self, p: dict) -> RawDocument:
        """单个 product JSON → RawDocument。"""
        pid = p["id"]
        name = p.get("name", "")
        price = p.get("price", "")
        regular = p.get("regular_price", "")
        sale = p.get("sale_price", "")
        sku = p.get("sku", "")
        stock_status = p.get("stock_status", "")
        stock_qty = p.get("stock_quantity")
        cats = [c.get("name", "") for c in p.get("categories", [])]
        short_desc = self._clean_html(p.get("short_description", ""))
        desc = self._clean_html(p.get("description", ""))
        permalink = p.get("permalink", "")

        # 拼成可检索文本(价格/SKU/库存/分类 + 描述)
        parts = [
            f"# {name}",
            f"SKU: {sku}" if sku else "",
            f"Price: ${price}" if price else "",
            f"Regular: ${regular}" if regular and regular != price else "",
            f"Sale: ${sale}" if sale and sale != price else "",
            f"Stock: {stock_status}" + (f" ({stock_qty})" if stock_qty is not None else ""),
            f"Categories: {', '.join(cats)}" if cats else "",
            short_desc,
            desc,
        ]
        content = "\n\n".join(part for part in parts if part)
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        product_tag = self._category_to_product(p.get("categories", []))

        return RawDocument(
            source_id=f"{self._config.id}/{pid}",
            source_type="woocommerce",
            product=product_tag,
            title=name,
            content=content,
            url=permalink,
            metadata={
                "product_id": pid,
                "sku": sku,
                "price": price,
                "regular_price": regular,
                "sale_price": sale,
                "stock_status": stock_status,
                "stock_quantity": stock_qty,
                "categories": cats,
                "type": p.get("type", ""),
                "status": p.get("status", ""),
                "date_modified": p.get("date_modified", ""),
            },
            content_hash=content_hash,
            channel_visibility=self._channel_visibility,
            branch="",  # 非分支源
        )

    def _fetch_page(self, **params) -> list[dict]:
        """拉一页 products(raise_for_status 异常向上传播)。"""
        resp = self._get(
            "/wp-json/wc/v3/products",
            params={"per_page": self._per_page, "status": "publish", **params},
        )
        resp.raise_for_status()
        return resp.json()

    def fetch_all(self) -> Iterator[RawDocument]:
        """全量抓取所有 publish 产品。"""
        try:
            products = self._fetch_page()
        except Exception as exc:  # noqa: BLE001
            logger.error("WooCommerce fetch_all 失败: %s", str(exc)[:200])
            return
        for p in products:
            try:
                yield self._product_to_document(p)
            except Exception as exc:  # noqa: BLE001
                logger.warning("product %s 转换失败: %s", p.get("id"), str(exc)[:200])

    def fetch_changes(self, since: datetime) -> Iterator[RawDocument]:
        """增量抓取:modified_after 过滤。"""
        try:
            products = self._fetch_page(modified_after=since.isoformat())
        except Exception as exc:  # noqa: BLE001
            logger.error("WooCommerce fetch_changes 失败: %s", str(exc)[:200])
            return
        for p in products:
            try:
                yield self._product_to_document(p)
            except Exception as exc:  # noqa: BLE001
                logger.warning("product %s 转换失败: %s", p.get("id"), str(exc)[:200])

    def fetch_deleted(self, since: datetime) -> list[str]:
        """检测已删除的 product(诚实降级:始终返回 [])。

        WooCommerce REST API 无删除事件 webhook,且 sync.py:213 调用
        ``fetch_deleted(since)`` 不传已知 IDs,无法做差集对比。故严格匹配
        Protocol 签名,返回 ``[]``(与 filesystem.py:182-189 范式一致)。

        若后续需要删除检测,应由调用方(sync.py)维护 known_ids 快照
        对比,或接入 WooCommerce webhook。

        Args:
            since: 未使用(保留 Protocol 签名兼容)。
        """
        return []


# 触发 @register
ConnectorRegistry.register("woocommerce")(WooCommerceConnector)
```

- [ ] **Step 4: 运行测试,确认通过**

```bash
TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test .venv/bin/python -m pytest tests/connectors/test_woocommerce.py -q
```

Expected: PASS(6 新)

- [ ] **Step 5: Commit**

```bash
git add backend/connectors/woocommerce.py tests/connectors/test_woocommerce.py
git commit -m "feat(connector): WooCommerceConnector(commercial 数据源,HTML 清洗+category 映射)"
```

---

## Task 2: sync.py 触发 woocommerce register + 冒烟

**Files:**
- Modify: `scripts/sync.py`(若 import 不含 woocommerce)
- Verify: connector 可被 registry 找到

- [ ] **Step 1: 检查 sync.py connector imports**

```bash
grep -n "import backend.connectors" scripts/sync.py
```

- [ ] **Step 2: 加 woocommerce import(若缺)**

在 sync.py 的 connector import 块加 `import backend.connectors.woocommerce  # noqa: F401`。

- [ ] **Step 3: 冒烟测试(不触真实 API)**

```bash
.venv/bin/python -c "
import backend.connectors.woocommerce
from backend.connectors.registry import ConnectorRegistry
print('woocommerce registered:', 'woocommerce' in ConnectorRegistry._connectors)
"
```

Expected: `True`

- [ ] **Step 4: Commit(若有 sync.py 改动)**

```bash
git add scripts/sync.py
git commit -m "chore(sync): import woocommerce connector 触发 @register"
```

---

## Task 3: data_source 配置 + 真实拉取验证(Real-Run Gate)

**Files:**
- Modify: `config/data_sources.yaml`(示例配置,DB 为准)

- [ ] **Step 1: 加 YAML 配置示例**

在 `config/data_sources.yaml` 末尾加:

```yaml
  - id: "woocommerce-mall"
    type: "woocommerce"
    product: "commercial"
    enabled: true
    config:
      store_url: "https://www.camthink.ai"
      consumer_key: "ck-placeholder-fill-from-env"
      consumer_secret: "cs-placeholder-fill-from-env"
      per_page: 100
    sync_interval: "1h"
    channel_visibility:
      - widget
      - api
```

> **注**:生产配置走 DB(data_sources 表,admin 管理)。YAML 仅作示例/seed。
> **凭证**:实际从 `.env` 环境变量读,connector 可改为 `os.environ.get("WOOCOMMERCE_*")` fallback(见 Step 3)。

- [ ] **Step 2: connector 凭证 env fallback(推荐)**

修改 `WooCommerceConnector.__init__`,允许 config 缺凭证时从 `os.environ` 读:

```python
import os
# __init__ 中:
self._key: str = config.config.get("consumer_key") or os.environ.get("WOOCOMMERCE_CONSUMER_KEY", "")
self._secret: str = config.config.get("consumer_secret") or os.environ.get("WOOCOMMERCE_CONSUMER_SECRET", "")
self._store_url: str = (
    config.config.get("store_url")
    or os.environ.get("WOOCOMMERCE_STORE_URL", "")
).rstrip("/")
if not all([self._store_url, self._key, self._secret]):
    raise ValueError("WooCommerce 凭证缺失(check config / WOOCOMMERCE_* env)")
```

加对应单测(`test_woocommerce_env_fallback`)。

- [ ] **Step 3: Real-Run Gate — 真实拉取验证**

```bash
set -a; source .env; set +a
.venv/bin/python -c "
import asyncio, sys; sys.path.insert(0, '.')
import backend.connectors.woocommerce
from backend.connectors.registry import ConnectorRegistry, SourceConfig
from collections import Counter
cfg = SourceConfig(id='woocommerce-mall', type='woocommerce', product='commercial',
                   enabled=True, config={}, sync_interval='1h')
conn = ConnectorRegistry.create(cfg)
docs = list(conn.fetch_all())
print(f'拉取到 {len(docs)} 个产品 RawDocument')
# H1: 断言全量覆盖(暴露未来超 per_page=100 的静默截断)
assert len(docs) == 40, f'预期 40 产品,实得 {len(docs)}(可能分页截断)'
# M1: 打印 product 分布,人工确认映射合法
print('product 分布:', dict(Counter(d.product for d in docs)))
for d in docs[:3]:
    print(f'  {d.product:12s} | {d.title[:50]} | sku={d.metadata.get(\"sku\",\"\")} | price=\${d.metadata.get(\"price\",\"\")}')
# 验证 source_type / channel_visibility / HTML 清洗
assert all(d.source_type == 'woocommerce' for d in docs)
assert all(d.channel_visibility == ('widget','api') for d in docs)
assert all('<' not in d.content for d in docs), 'HTML 标签残留'
print('✅ Real-Run Gate 通过:40 产品全量 + RawDocument 正确 + HTML 清洗')
"
```

Expected: 拉取到 **40** 个产品(H1 断言),product 分布打印(M1 人工确认),HTML 无标签残留。

> **M1 人工确认点**:product 分布应含 ne101/ne301/ne503/accessories/aitoolstack/commercial。
> 若 `aitoolstack` 标签数与 AI Cameras(5)+Edge AI Boxes(2)+Modules & Dev Kits(14)=21 不符,需调整 `_CATEGORY_MAP`。
> 若有 product 标签不在预期集,记录并调整映射表。

- [ ] **Step 4: Commit**

```bash
git add backend/connectors/woocommerce.py tests/connectors/test_woocommerce.py config/data_sources.yaml
git commit -m "feat(woocommerce): env fallback 凭证 + YAML 配置示例 + real-run 验证"
```

---

## Self-Review Checklist

- [ ] WooCommerceConnector 实现 DataSourceConnector Protocol(三方法,`fetch_deleted(since)` 严格匹配签名)
- [ ] `@ConnectorRegistry.register("woocommerce")` 注册
- [ ] HTML 清洗(`<p><strong>` 等标签去除 + script/style 块内容跳过,文本保留)
- [ ] category → product 映射(NE301→ne301,无匹配→commercial;Real-Run 人工确认分布)
- [ ] `source_type="woocommerce"`(供 P0#1 boost 桶)
- [ ] 凭证 env fallback(永不硬编码)
- [ ] fetch_changes 用 modified_after
- [ ] fetch_deleted 诚实降级返回 [](sync.py 不传 known_ids,不假装检测)
- [ ] 单测全绿(含 mock HTTP + env fallback + script/style 跳过)
- [ ] **Real-Run Gate:真实拉取 40 产品(H1 断言全量)+ RawDocument 正确 + HTML 清洗**(不 substitute test)

---

## Plan Review 修复记录(Round 1)

| # | 级别 | 问题 | 修复 |
|---|------|------|------|
| C1 | CRITICAL | `fetch_deleted(since, known_ids=None)` 偏离 Protocol,sync.py 不传 known_ids → 生产静默失效 | 删 known_ids 参数,严格 `fetch_deleted(self, since) -> []`,诚实降级(同 filesystem 范式);测试改验证"返回 []" |
| H1 | HIGH | 无分页,超 100 产品静默截断 | Real-Run Gate 断言 `len(docs) == 40`(暴露未来截断);docstring 标注 ≤100 限制 |
| M1 | MEDIUM | category→product 映射未全验证(aitoolstack 合法性) | Real-Run 打印 product 分布 + 人工确认说明 |
| M2 | MEDIUM | `_clean_html` 未跳过 script/style 内容(CSS/JS 混进检索) | `_HTMLTextExtractor` 加 `_ignore_depth` 计数,script/style 内不收集 data;测试加 script/style 用例 |

---

## 后续衔接(不在本 plan)

- **P0#1 commercial 路由**:WooCommerce 接入后,改 intent spec §3.1.3 的 ~3 处代码改动(commercial 从拒答转作答 + woocommerce boost 桶)
- **sync 接入生产**:P0#2 reindex 完成后,把 woocommerce data_source 加到 DB,跑一次 sync 灌入 Weaviate
- **增量频率**:40 产品规模小,建议每小时全量刷新(价格/库存动态)
