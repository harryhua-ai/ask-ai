"""web_crawl connector(C8):官网 sitemap 爬取数据源。

流程:sitemap 索引发现(Yoast post/page/product 三子表,合并去重)→
排除规则过滤(`/store/`、登录/隐私等非知识页)→ 纯 HTTP 抓取(UA +
超时重试 + 延时限速)→ stdlib HTML 清洗为 Markdown(剥导航/页脚/脚本/
cookie 提示,优先 main/article 正文)→ RawDocument(product=website,
language=en,content_hash 增量)。

增量:全量靠 content_hash 去重;增量用 sitemap lastmod ≥ since 提速
(无 lastmod 的 URL 不进增量,避免每轮全站重抓)。删除:持久化上一轮
URL 清单(``data/crawl-state/<id>.json``),本轮消失的 URL 经
``fetch_deleted`` 返回。

红线:爬取加 UA 与延时(默认 500ms/页),不对目标站点施压。
"""

import hashlib
import logging
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import requests

from backend.connectors.base import RawDocument
from backend.connectors.registry import ConnectorRegistry, SourceConfig

logger = logging.getLogger(__name__)

# 默认排除清单:商城(woocommerce-mall 源已覆盖)/ 登录 / 隐私条款等非知识页。
# 源 config.exclude_patterns 提供时整体替换本清单。
DEFAULT_EXCLUDE_PATTERNS: list[str] = [
    "/store/",
    "/wp-login",
    "/wp-admin",
    "/wp-json",  # WP REST API 入口(<head> link 发现),非内容页
    "/cart",
    "/checkout",
    "/my-account",
    "/login",
    "/signin",
    "/privacy",
    "/terms",
    "/cookie",
]

# Yoast SEO sitemap 索引:仅取知识类三子表(post/page/product)
_SITEMAP_KIND_RE = re.compile(r"(post|page|product)-sitemap")
_SM_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"

# 抓取 UA:标识爬虫 + 指向目标站,便于站点方识别与限流
USER_AGENT = "ask-ai-crawler/0.1 (+camthink-ai knowledge indexer)"


def _local_name(tag: str) -> str:
    """去掉 XML 命名空间前缀(兼容带/不带 xmlns 的 sitemap)。"""
    return tag.rsplit("}", 1)[-1]


def parse_sitemap_index(xml_text: str) -> list[str]:
    """解析 sitemap index,返回子 sitemap 的 loc 列表(非 index 结构返回空)。"""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    if _local_name(root.tag) != "sitemapindex":
        return []
    return [
        (elm.text or "").strip()
        for elm in root.iter()
        if _local_name(elm.tag) == "loc" and (elm.text or "").strip()
    ]


def parse_urlset(xml_text: str) -> dict[str, str | None]:
    """解析 urlset,返回 {loc: lastmod|None};非法 XML 返回空。"""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {}
    if _local_name(root.tag) != "urlset":
        return {}
    out: dict[str, str | None] = {}
    for url_elm in root.iter():
        if _local_name(url_elm.tag) != "url":
            continue
        loc: str | None = None
        lastmod: str | None = None
        for child in url_elm.iter():
            name = _local_name(child.tag)
            if name == "loc" and not loc and (child.text or "").strip():
                loc = child.text.strip()
            elif name == "lastmod" and not lastmod and (child.text or "").strip():
                lastmod = child.text.strip()
        if loc:
            out.setdefault(loc, lastmod)
    return out


_SKIP_TAGS = frozenset(
    {
        "script", "style", "noscript", "nav", "header", "footer", "aside",
        "form", "iframe", "svg", "button", "select", "option", "label",
        "head", "template",
    }
)
_BLOCK_TAGS = frozenset({"p", "div", "section", "article", "main", "ul", "ol", "table", "hr"})


class _MarkdownExtractor(HTMLParser):
    """stdlib HTML → Markdown 提取器。

    - 跳过 script/style/nav/header/footer/aside 等噪音标签(计数防御畸形嵌套)
    - id/class 含 ``cookie`` 的元素整块跳过(cookie 提示条)
    - 存在 <main>/<article> 时仅取其内部正文;否则取全文档(噪音靠跳过清单)
    - h1-h6 → # 标题;p → 段落;li → 列表项;pre → 围栏代码;blockquote → 引用
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_stack: list[str] = []  # 跳过区标签栈(容忍区间内非 skip 闭合标签)
        self._buf: list[str] = []
        self._parts: list[str] = []
        self._heading_prefix = ""
        self._list_stack: list[str] = []
        self._title: str | None = None
        self._page_title: str | None = None

    def _in_skip(self) -> bool:
        return bool(self._skip_stack)

    # -- 内部 --

    def _flush(self) -> None:
        text = "".join(self._buf).strip()
        self._buf = []
        if not text:
            return
        if self._heading_prefix:
            self._parts.append(f"\n{self._heading_prefix} {text}\n")
            if self._title is None and self._heading_prefix == "#":
                self._title = text
            self._heading_prefix = ""
        elif self._list_stack:
            self._parts.append(f"\n- {text}")
        else:
            self._parts.append(f"\n{text}\n")

    def _attr_has_cookie(self, attrs) -> bool:
        for k, v in attrs:
            if k in ("id", "class") and v and "cookie" in v.lower():
                return True
        return False

    # -- HTMLParser 协议 --

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._buf = []  # <title> 单独捕获(页面专属标题,优于全站通用 h1)
            return
        if self._in_skip():
            # 跳过区内所有开始标签都入栈(包括嵌套的非 skip 标签),
            # 保证对应闭合标签能正确出栈
            if tag not in ("br", "img", "input", "hr", "meta", "link"):
                self._skip_stack.append(tag)
            return
        if tag in _SKIP_TAGS:
            self._skip_stack.append(tag)
            return
        if self._attr_has_cookie(attrs):
            self._skip_stack.append(tag)
            return
        if tag in ("main", "article"):
            # 首个 main/article 开启正文捕获:丢弃其之前的噪音(顶部导航等)
            self._parts.clear()
            self._buf = []
            self._heading_prefix = ""
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._flush()
            self._heading_prefix = "#" * int(tag[1])
        elif tag == "li":
            self._flush()
            self._list_stack.append(tag)
        elif tag in ("ul", "ol"):
            self._list_stack.append(tag)
        elif tag == "pre":
            self._flush()
            self._parts.append("\n```\n")
        elif tag == "blockquote":
            self._flush()
            self._parts.append("\n> ")
        elif tag in _BLOCK_TAGS or tag == "br":
            self._flush()
            if tag == "br":
                self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._page_title = "".join(self._buf).strip()
            self._buf = []
            return
        # 跳过区退出:闭合标签匹配栈中最近一次同名入栈(容忍嵌套)
        if tag in self._skip_stack:
            for i in range(len(self._skip_stack) - 1, -1, -1):
                if self._skip_stack[i] == tag:
                    del self._skip_stack[i]
                    break
            return
        if self._heading_prefix and tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._flush()
            return
        if tag == "li" and self._list_stack and self._list_stack[-1] == "li":
            self._list_stack.pop()
            self._flush()
        elif tag in ("ul", "ol") and self._list_stack:
            if self._list_stack and self._list_stack[-1] in ("ul", "ol"):
                self._list_stack.pop()
            self._flush()
        elif tag == "pre":
            self._flush()
            self._parts.append("\n```\n")
        elif tag == "blockquote" or tag in _BLOCK_TAGS:
            self._flush()

    def handle_data(self, data):
        if self._in_skip():
            return
        self._buf.append(data)

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self._parts.append("\n")

    # -- 结果 --

    def result(self) -> tuple[str, str]:
        """返回 (title, markdown);title 优先 h1,缺省空串。"""
        self._flush()
        md = "".join(self._parts)
        md = re.sub(r"\n{3,}", "\n\n", md).strip()
        title = (self._title or "").strip()
        return title, md


def html_to_markdown(html: str) -> tuple[str, str]:
    """HTML → (title, markdown)。

    title 优先取 ``<title>``(页面专属,剥 " | 站点名" 后缀),回退第一个 h1。
    """
    parser = _MarkdownExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception as exc:  # noqa: BLE001 - 畸形 HTML 不应中断爬取
        logger.warning("HTML 清洗失败: %s", str(exc)[:120])
        return "", ""
    h1_title, md = parser.result()
    page_title = (parser._page_title or "").strip()
    page_title = re.split(r"\s*[|\u2013\-]\s+CamThink\s*$", page_title)[0].strip()
    return (page_title or h1_title), md


def _html_title_fallback(html: str) -> str:
    m = re.search(r"<title[^>]*>([^<]*)</title>", html, re.IGNORECASE | re.DOTALL)
    return m.group(1).strip() if m else ""


def _url_to_source_path(url: str) -> str:
    """URL → 稳定 source_id 后缀:去 scheme/host,保留 path(空路径 → index)。"""
    path = urlparse(url).path.strip("/")
    return path or "index"


@ConnectorRegistry.register("web_crawl")
class WebCrawlConnector:
    """官网 sitemap 爬取 connector(C8)。

    config:
        - ``base_url`` (str, 必填): 站点根,如 ``https://www.camthink.ai``
        - ``sitemap_url`` (str, 可选): 缺省 ``{base_url}/sitemap_index.xml``
        - ``exclude_patterns`` (list[str], 可选): 提供时替换默认排除清单
        - ``crawl_delay_ms`` (int, 可选): 页面抓取间隔,默认 500(勿压站点)
    """

    def __init__(self, config: SourceConfig) -> None:
        self._config = config
        self._id = config.id
        self._product = config.product or "website"
        self._base_url = str(config.config["base_url"]).rstrip("/")
        self._sitemap_url = str(
            config.config.get("sitemap_url") or f"{self._base_url}/sitemap_index.xml"
        )
        self._excludes = list(
            config.config.get("exclude_patterns", DEFAULT_EXCLUDE_PATTERNS)
        )
        self._delay_s = int(config.config.get("crawl_delay_ms", 500)) / 1000
        self._channel_visibility = config.channel_visibility
        self._state_path = Path("data/crawl-state") / f"{config.id}.json"
        self._entries_cache: dict[str, str | None] | None = None

    @property
    def source_id(self) -> str:
        return self._id

    @property
    def product(self) -> str:
        return self._product

    # ---------------- 抓取原语 ----------------

    def _http_get(self, url: str) -> str:
        """GET 文本;UA + 20s 超时 + 2 次重试(仅网络/5xx),最终失败抛 RuntimeError。"""
        last: Exception | None = None
        for attempt in range(3):
            try:
                resp = requests.get(
                    url,
                    headers={"User-Agent": USER_AGENT},
                    timeout=20,
                )
                if resp.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {resp.status_code}")
                resp.raise_for_status()
                return resp.text
            except requests.RequestException as exc:
                last = exc
                logger.warning("抓取失败(第 %d 次) %s: %s", attempt + 1, url, str(exc)[:120])
                time.sleep(1 + attempt)
        raise RuntimeError(f"抓取失败(重试耗尽) {url}: {last}")

    def _excluded(self, url: str) -> bool:
        path = urlparse(url).path.lower()
        return any(pattern.lower() in path for pattern in self._excludes)

    def _sitemap_entries(self) -> dict[str, str | None]:
        """sitemap 索引 → 三子表(post/page/product)合并去重的 {url: lastmod}。"""
        if self._entries_cache is not None:
            return self._entries_cache
        index_xml = self._http_get(self._sitemap_url)
        entries: dict[str, str | None] = {}
        for sub in parse_sitemap_index(index_xml):
            if not _SITEMAP_KIND_RE.search(sub):
                continue
            for url, lastmod in parse_urlset(self._http_get(sub)).items():
                if self._excluded(url):
                    continue
                entries.setdefault(url, lastmod)
            time.sleep(self._delay_s)  # 子表请求间限速
        logger.info("web_crawl %s: sitemap 共 %d 个 URL(排除后)", self._id, len(entries))
        self._entries_cache = entries
        return entries

    _SKIP_HREF_EXTS = frozenset(
        {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".css", ".js",
         ".zip", ".gz", ".mp4", ".mp3", ".ico", ".woff", ".woff2", ".ttf"}
    )

    def _same_domain_links(self, html: str) -> list[str]:
        """提取同域内容页链接(去锚点/查询/资产后缀/排除项),供增量发现。"""
        host = urlparse(self._base_url).netloc
        out: list[str] = []
        for m in re.finditer(r'href=["\']([^"\']+)["\']', html):
            raw = m.group(1).strip()
            if raw.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            if raw.startswith("//"):
                # 协议相对链接(如 "//resources.camthink.ai"):外域跳过,同域转绝对
                ext_host = urlparse(f"https:{raw}").netloc
                if ext_host and ext_host != host:
                    continue
                raw = f"https:{raw}"
            # 站方残缺 href(如 "resources.camthink.ai" 无 scheme)会拼出
            # 垃圾 URL:无斜杠且含点 → 视为域名样式,跳过
            if "/" not in raw and "." in raw:
                continue
            absu = raw if raw.startswith("http") else f"{self._base_url}/{raw.lstrip('/')}"
            pu = urlparse(absu)
            if pu.netloc != host or pu.query:
                continue
            path = pu.path
            if Path(path).suffix.lower() in self._SKIP_HREF_EXTS:
                continue
            absu = f"{self._base_url}{path.rstrip('/')}/" if path.rstrip("/") else f"{self._base_url}/"
            if absu in self._seen_urls or self._excluded(absu):
                continue
            out.append(absu)
        return out

    def _fetch_page(self, url: str) -> tuple[RawDocument, list[str]]:
        """抓取单页 → (RawDocument, 页内发现的同域新链接)。"""
        html = self._http_get(url)
        time.sleep(self._delay_s)  # 页面间限速
        title, md = html_to_markdown(html)
        if not title:
            title = _html_title_fallback(html)
        new_links = self._same_domain_links(html)
        path = _url_to_source_path(url)
        doc = RawDocument(
            source_id=f"{self._id}/{path}",
            source_type="web_crawl",
            product=self._product,
            title=title or path,
            content=md,
            url=url,
            metadata={"language": "en", "path": path},
            content_hash=hashlib.sha256(md.encode()).hexdigest(),
            channel_visibility=self._channel_visibility,
        )
        return doc, new_links

    def _load_state(self) -> set[str]:
        try:
            import json

            return set(json.loads(self._state_path.read_text()))
        except (OSError, ValueError):
            return set()

    def _save_state(self, ids: set[str]) -> None:
        import json

        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps(sorted(ids), ensure_ascii=False))

    # ---------------- Connector 协议 ----------------

    def fetch_all(self) -> Iterator[RawDocument]:
        """全量:sitemap 起点 + 同域链接发现(BFS,上限 max_pages)。"""
        self._seen_urls: set[str] = set(self._sitemap_entries())
        queue = sorted(self._seen_urls)
        extra_cap = int(self._config.config.get("max_pages", 150))
        failures = 0
        successes = 0
        while queue:
            url = queue.pop(0)
            try:
                doc, links = self._fetch_page(url)
            except RuntimeError as exc:
                # 发现链接可能 404/残缺:单页失败跳过,不拖垮整轮同步
                failures += 1
                logger.warning("页面抓取失败,跳过 %s: %s", url, str(exc)[:120])
                continue
            successes += 1
            for link in links:
                if link not in self._seen_urls and len(self._seen_urls) < len(
                    self._sitemap_entries()
                ) + extra_cap:
                    self._seen_urls.add(link)
                    queue.append(link)
            yield doc
        if successes == 0 and failures > 0:
            raise RuntimeError(f"全量抓取全部失败({failures} 页)")

    def fetch_changes(self, since: datetime) -> Iterator[RawDocument]:
        """增量:仅 lastmod 存在且 ≥ since 的 URL(无 lastmod 不进增量)。"""
        self._seen_urls: set[str] = set(self._sitemap_entries())
        for url in sorted(self._sitemap_entries()):
            lastmod = self._sitemap_entries()[url]
            if not lastmod:
                continue
            try:
                changed_at = datetime.fromisoformat(lastmod)
            except ValueError:
                continue
            if changed_at.tzinfo is None:
                changed_at = changed_at.replace(tzinfo=UTC)  # 无时区按 UTC(站点惯例)
            since_utc = since if since.tzinfo else since.replace(tzinfo=UTC)
            if changed_at < since_utc:
                continue
            doc, _ = self._fetch_page(url)
            yield doc

    def fetch_deleted(self, since: datetime) -> list[str]:
        """删除:本轮已知 URL 集合(sitemap + 发现页)相比上一轮消失的文档。"""
        known = set(getattr(self, "_seen_urls", set()) or set(self._sitemap_entries()))
        current_ids = {f"{self._id}/{_url_to_source_path(u)}" for u in known}
        previous = self._load_state()
        self._save_state(current_ids)
        return sorted(previous - current_ids)
