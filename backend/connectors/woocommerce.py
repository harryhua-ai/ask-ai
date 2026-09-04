"""WooCommerce 商城数据源 Connector(commercial 意图数据源)。

通过 WooCommerce REST API v3(Basic Auth)拉 products,转 RawDocument:
- 全量:单页拉所有 publish 产品(≤100,当前规模 40)
- 增量:``modified_after`` 参数拉变更
- 删除检测:诚实降级返回 [](WooCommerce 无删除事件 webhook,且 sync.py:213
  调用 ``fetch_deleted(since)`` 不传已知 IDs,无法做差集;同 filesystem.py:182-189)

产品 → RawDocument 映射:
- 结构化字段(name/price/sku/stock/categories)拼成可检索文本(BM25/dense 都能命中)
- short_description / description 的 HTML 清洗为纯文本(跳过 script/style 块)
- category name → product 映射(NE301→ne301 等,无匹配→commercial)
- source_type = "woocommerce"(供 P0#1 commercial 意图 boost 桶路由)

凭证从 SourceConfig.config 读(store_url / consumer_key / consumer_secret),
config 缺失时 fallback 到 ``WOOCOMMERCE_*`` 环境变量,永不硬编码。
"""

import hashlib
import logging
import os
import re
from collections.abc import Iterator
from datetime import datetime
from html import unescape
from html.parser import HTMLParser
from typing import Any

import requests

from backend.connectors.base import RawDocument
from backend.connectors.registry import ConnectorRegistry, SourceConfig

logger = logging.getLogger(__name__)

# category name(小写) → product 标识
# 设备类别(具体型号)优先判定;广品线(AI Cameras / Edge AI Boxes /
# Modules & Dev Kits)仅作设备类别未命中时的回退 —— Issue #19(RC2):
# 旧实现按 categories 列表序先命中先胜,真实设备页(categories=
# ["AI Cameras", "NE301"])被广品线抢注为 aitoolstack,导致
# 设备身份在商店元数据中丢失(比较查询证据饥饿的直接成因)。
_DEVICE_CATEGORY_MAP = {
    "ne101": "ne101",
    "ne301": "ne301",
    "ne302": "ne302",
    "ne503": "ne503",
    "ng4500": "ng4500",
}
_BROAD_CATEGORY_MAP = {
    "ai cameras": "aitoolstack",
    "edge ai boxes": "aitoolstack",
    "modules & dev kits": "aitoolstack",
}


def _device_identity_from_text(text: str) -> str | None:
    """从产品名/slug/URL 文本确定性派生设备身份(Issue #19 Store Identity)。

    走 taxonomy 别名扫描(与问答侧同一词表,零 LLM),只认 ``kind=product``
    的设备 slug —— aitoolstack/neomind 等 platform 桶不是设备身份,不在此
    认领;无设备命中返回 ``None``(调用方回退类别映射,**禁止猜测**)。

    连接器 ingest(name+slug)与元数据迁移(title+url)共用本函数,
    保证两侧派生语义逐字一致。
    """
    if not text:
        return None
    from backend.product_taxonomy import get_taxonomy

    taxonomy = get_taxonomy()
    for slug in taxonomy.extract_products(text):
        entity = taxonomy.entity(slug)
        if entity is not None and entity.kind == "product":
            return slug
    return None


class _HTMLTextExtractor(HTMLParser):
    """从 HTML 提取纯文本(去标签),跳过 script/style 块内容。

    script/style 的文本内容(CSS/JS 代码)会被 handle_data 接收,
    若不跳过会混进检索内容(BM25 噪声 / dense 向量偏移)。用 _ignore_depth
    计数,在 script/style 标签内时不收集 data。

    计数而非布尔:防御嵌套或未闭合标签(虽然 script/style 不该嵌套,但
    HTMLParser 对畸形 HTML 容错,_ignore_depth > 0 的判断在任何情况下都安全)。
    """

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._ignore_depth: int = 0  # >0 表示在 script/style 内

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._ignore_depth += 1

    def handle_endtag(self, tag: str) -> None:
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


# 残留标签清扫:匹配 ``<`` 后跟可选 ``/`` 与字母的畸形标签序列。
# 用于清理 HTMLParser 未识别的畸形标签(如实体解码后泄露的 ``</strong >``、
# 带属性的未闭合 ``<strong data-x>``)。不匹配 ``<5%``、``< -33%`` 等合法
# 比较表达式(它们 ``<`` 后非字母)。
_RESIDUAL_TAG_RE = re.compile(r"</?\s*[a-zA-Z][^>]*?>")


class WooCommerceConnector:
    """WooCommerce 商城 Connector(实现 DataSourceConnector Protocol)。

    通过 ``SourceConfig.config`` 提供参数(config 缺失时 fallback 环境变量):
    - ``store_url`` (str, 必填): 商城站点(如 ``https://www.camthink.ai``)
    - ``consumer_key`` (str, 必填): WooCommerce REST API key
    - ``consumer_secret`` (str, 必填): WooCommerce REST API secret
    - ``per_page`` (int, 可选): 单页大小,默认 100(当前规模 40,单页可拉全量)

    Note:
        当前实现单页拉取(per_page=100),适用于 ≤100 产品的规模。若未来产品数
        超过 100,需加分页循环(读 ``X-WP-TotalPages`` 头迭代),否则会静默截断。
        Real-Run Gate(Task 3 Step 3)断言 ``len(docs) == 40`` 以暴露未来截断。
    """

    def __init__(self, config: SourceConfig) -> None:
        self._config = config
        cfg = config.config
        # 凭证:config 优先,缺失 fallback 到环境变量(永不硬编码)
        self._store_url: str = (
            cfg.get("store_url") or os.environ.get("WOOCOMMERCE_STORE_URL", "")
        ).rstrip("/")
        self._key: str = cfg.get("consumer_key") or os.environ.get(
            "WOOCOMMERCE_CONSUMER_KEY", ""
        )
        self._secret: str = cfg.get("consumer_secret") or os.environ.get(
            "WOOCOMMERCE_CONSUMER_SECRET", ""
        )
        self._per_page: int = int(cfg.get("per_page", 100))
        self._channel_visibility: tuple[str, ...] = config.channel_visibility
        if not all([self._store_url, self._key, self._secret]):
            raise ValueError(
                "WooCommerce 凭证缺失(check config / WOOCOMMERCE_* env)"
            )

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
            requests.Response 对象(调用方负责 raise_for_status / json)。
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
        """HTML → 纯文本(去标签,跳过 script/style 内容,保留文本)。

        两阶段清洗:
        1. ``_HTMLTextExtractor`` 处理标准标签 + 跳过 script/style 块内容
        2. ``_RESIDUAL_TAG_RE`` 扫除 HTMLParser 漏掉的畸形标签残留
           (如实体解码后泄露的 ``</strong >``、带属性未闭合标签),
           同时不误伤合法的 ``<`` 比较符(``<5%``、``< -33%`` 等)

        Args:
            html: 原始 HTML 字符串(product.description / short_description)。

        Returns:
            纯文本(可能含合法的 ``<`` / ``>`` 比较符号,不含 HTML 标签)。
        """
        extractor = _HTMLTextExtractor()
        extractor.feed(html or "")
        text = extractor.get_text()
        return _RESIDUAL_TAG_RE.sub("", text)

    @staticmethod
    def _category_to_product(categories: list[dict]) -> str:
        """category name → product 标识(无匹配 → commercial)。

        Issue #19(RC2)修正:**设备类别优先于广品线类别** —— 先查
        ``_DEVICE_CATEGORY_MAP``,任一 category 命中具体型号即返回;全部
        未命中再查 ``_BROAD_CATEGORY_MAP``(aitoolstack 广品线),最后
        commercial 兜底。旧实现按列表序先命中先胜,设备页被广品线抢注。

        Args:
            categories: product JSON 的 ``categories`` 字段
                (``[{"name": "NE301", ...}, ...]``)。

        Returns:
            product 标识(ne101/ne301/ne302/ne503/ng4500/commercial/
            aitoolstack)。
        """
        names = [unescape(cat.get("name") or "").lower() for cat in categories or []]
        for name in names:
            if name in _DEVICE_CATEGORY_MAP:
                return _DEVICE_CATEGORY_MAP[name]
        for name in names:
            if name in _BROAD_CATEGORY_MAP:
                return _BROAD_CATEGORY_MAP[name]
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
        cats = [unescape(c.get("name", "")) for c in p.get("categories", [])]
        short_desc = self._clean_html(p.get("short_description", ""))
        desc = self._clean_html(p.get("description", ""))
        permalink = p.get("permalink", "")

        # 拼成可检索文本(价格/SKU/库存/分类 + 描述)
        # 同价字段不重复打(sale==price 时跳过 sale 行)
        parts = [
            f"# {name}",
            f"SKU: {sku}" if sku else "",
            f"Price: ${price}" if price else "",
            f"Regular: ${regular}" if regular and regular != price else "",
            f"Sale: ${sale}" if sale and sale != price else "",
            f"Stock: {stock_status}"
            + (f" ({stock_qty})" if stock_qty is not None else ""),
            f"Categories: {', '.join(cats)}" if cats else "",
            short_desc,
            desc,
        ]
        content = "\n\n".join(part for part in parts if part)
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        # Issue #19(Store Identity Contract):设备身份优先由产品名+slug
        # 确定性派生(与迁移脚本同一函数);类别映射仅作回退,且设备类别
        # 先于广品线类别判定。
        product_tag = (
            _device_identity_from_text(f"{name} {p.get('slug', '')}")
            or self._category_to_product(p.get("categories", []))
        )

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

    def _fetch_page(self, **params: Any) -> list[dict]:
        """拉一页 products(raise_for_status 异常向上传播)。"""
        resp = self._get(
            "/wp-json/wc/v3/products",
            params={"per_page": self._per_page, "status": "publish", **params},
        )
        resp.raise_for_status()
        return resp.json()

    def fetch_all(self) -> Iterator[RawDocument]:
        """全量抓取所有 publish 产品(单页,≤per_page)。

        HTTP 错误(401/5xx 等)直接向上抛,由 ``_sync_one`` 记
        SyncLog status=failed——首次同步失败不得伪装成"空结果"。
        """
        products = self._fetch_page()
        for p in products:
            try:
                yield self._product_to_document(p)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "product %s 转换失败: %s", p.get("id"), str(exc)[:200]
                )

    def fetch_changes(self, since: datetime) -> Iterator[RawDocument]:
        """增量抓取:modified_after 过滤。

        HTTP 错误(401/5xx 等)直接向上抛。2026-08-04~08-17 教训:此处
        吞异常返回空会让 sync_log 记 success,商城数据静默冻结 13 天;
        增量窗口改为"上次成功时间"后,静默失败更会把窗口推过缺口。
        """
        products = self._fetch_page(modified_after=since.isoformat())
        for p in products:
            try:
                yield self._product_to_document(p)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "product %s 转换失败: %s", p.get("id"), str(exc)[:200]
                )

    def fetch_deleted(self, since: datetime) -> list[str]:
        """检测已删除的 product(诚实降级:始终返回 [])。

        WooCommerce REST API 无删除事件 webhook,且 sync.py:213 调用
        ``fetch_deleted(since)`` 不传已知 IDs,无法做差集对比。故严格匹配
        Protocol 签名(``fetch_deleted(self, since)``),返回 ``[]``
        (与 filesystem.py:182-189 范式一致)。

        若后续需要删除检测,应由调用方(sync.py)维护 known_ids 快照
        对比,或接入 WooCommerce webhook。

        Args:
            since: 未使用(保留 Protocol 签名兼容)。
        """
        return []


# 触发 @register
ConnectorRegistry.register("woocommerce")(WooCommerceConnector)
