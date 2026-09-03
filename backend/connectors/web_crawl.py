"""web_crawl connector(C8 + WEB 覆盖修正):官网 sitemap 爬取数据源。

流程:robots.txt 校验(Disallow 前缀,允许清单优先)→ sitemap 发现
(#17 起通用组合:robots ``Sitemap:`` 指令 → 显式 sitemap_url 配置 →
通用回退 → index 全部同域子表,URL 规范化合并去重;Yoast 三子表命名
过滤已按 S0 冻结方向退役)→ 排除规则过滤
(`/store/`、登录/隐私等非知识页)→ 纯 HTTP 抓取(UA + 超时重试 + 延时
限速)→ stdlib HTML 清洗为 Markdown(剥导航/页脚/脚本/cookie 提示,优先
main/article 正文)→ 薄内容过滤 → RawDocument(product=website,
language=en,content_hash=URL 感知增量)。

WEB 覆盖修正(2026-09-01,合同#6/#7):
- ``run_stats``:discovered/accepted/extracted/failed/rejected 全程记账,
  单页失败与薄内容不再静默吞没,由同步层写入 SyncLog 真实呈现覆盖;
- URL 规范化(canonical_url):sitemap 与页内链接统一形态(去 query/
  fragment、host 小写、压缩 //、统一尾斜杠),杜绝变体重复知识;
- content_hash 含 URL 路径:同内容不同页不再在 PG (content_hash,branch)
  主键上互撞(旧实现 sha256(md) 会让后页覆盖前页账本行);
- fetch_deleted 仅在全量轮做差集删除:增量轮的 sitemap-only 视野不再把
  BFS 发现页误判为"已消失"而删除(覆盖震荡根因)。

增量:全量靠 content_hash 去重;增量用 sitemap lastmod ≥ since 提速
(无 lastmod 的 URL 不进增量)。删除:见上(仅全量轮)。

红线:爬取加 UA 与延时(默认 500ms/页),robots Disallow 遵从,
不对目标站点施压。
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

# 薄内容阈值:提取正文低于该字符数的页面视为非知识页(模板/跳转/挑战页),
# 不入语料并计入 rejected.low_content。config.min_content_chars 可覆盖。
MIN_CONTENT_CHARS = 200

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


def canonical_url(base_url: str, url: str) -> str | None:
    """URL 规范化(WEB-G005):同站内容页的稳定唯一形态。

    规则:scheme 限定 http(s);host 小写;去 fragment;去 query(内容页
    不含查询参数,跟踪/排序变体不产生重复知识);压缩重复斜杠;统一补尾
    斜杠;相对路径按 base_url 补全。外域或非法 URL 返回 None。

    Returns:
        规范化 URL;外域/非法返回 None。
    """
    base = urlparse(base_url)
    if url.startswith("//"):
        # 协议相对链接(//host/path):携带自己的 host,补 scheme 后按外域判定
        url = f"{base.scheme}:{url}"
    elif "://" not in url:
        url = f"{base.scheme}://{base.netloc}{url}"
    u = urlparse(url)
    if u.scheme not in ("http", "https"):
        return None
    if u.netloc.lower() != base.netloc.lower():
        return None
    path = re.sub(r"//+", "/", u.path) or "/"
    if not path.endswith("/"):
        path += "/"
    return f"{base.scheme}://{base.netloc.lower()}{path}"


def parse_robots_disallows(text: str, agent: str = "ask-ai-crawler") -> list[str]:
    """解析 robots.txt,返回对该 UA 生效的 Disallow 前缀列表。

    组匹配:具名组(= agent,大小写不敏感)优先;无具名组时用 ``*`` 组;
    Allow/未知行忽略;空行结束当前组。
    """
    groups: dict[str, list[str]] = {}
    current: list[str] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, _, val = line.partition(":")
        key = key.strip().lower()
        val = val.strip()
        if key == "user-agent":
            current = groups.setdefault(val.lower(), [])
        elif key == "disallow" and current is not None:
            if val:
                current.append(val)
        # Allow / Sitemap / 未知字段:忽略(Disallow 空值 = 全允许,不记录)
    named = groups.get(agent.lower())
    if named:
        return named
    return groups.get("*", [])


_SKIP_TAGS = frozenset(
    {
        "script",
        "style",
        "noscript",
        "nav",
        "header",
        "footer",
        "aside",
        "form",
        "iframe",
        "svg",
        "button",
        "select",
        "option",
        "label",
        "head",
        "template",
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
    """官网 sitemap 爬取 connector(C8 + WEB 覆盖修正)。

    config:
        - ``base_url`` (str, 必填): 站点根,如 ``https://www.camthink.ai``
        - ``sitemap_url`` (str, 可选): 显式 sitemap 地址(Advanced override);
          缺省自动发现(robots.txt ``Sitemap:`` 指令 → 通用回退
          ``/sitemap_index.xml`` → ``/sitemap.xml``,#17 Simple Mode 语义)
        - ``exclude_patterns`` (list[str], 可选): 提供时替换默认排除清单
        - ``crawl_delay_ms`` (int, 可选): 页面抓取间隔,默认 500(勿压站点)
        - ``min_content_chars`` (int, 可选): 薄内容阈值,默认 200

    run_stats(迭代结束后可读;同步层写入 SyncLog 呈现真实覆盖,合同#6/#7):
        ``{full, discovered, accepted, extracted, failed, failed_urls,
        rejected: {exclude, robots, low_content}}``
    """

    def __init__(self, config: SourceConfig) -> None:
        self._config = config
        self._id = config.id
        self._product = config.product or "website"
        self._base_url = str(config.config["base_url"]).rstrip("/")
        # None = 自动发现(robots 指令 → 通用回退);显式字符串 = Advanced override
        self._sitemap_url: str | None = (
            str(config.config.get("sitemap_url")).strip()
            if str(config.config.get("sitemap_url") or "").strip()
            else None
        )
        self._excludes = list(config.config.get("exclude_patterns", DEFAULT_EXCLUDE_PATTERNS))
        self._delay_s = int(config.config.get("crawl_delay_ms", 500)) / 1000
        self._min_content = int(config.config.get("min_content_chars", MIN_CONTENT_CHARS))
        self._channel_visibility = config.channel_visibility
        self._state_path = Path("data/crawl-state") / f"{config.id}.json"
        self._entries_cache: dict[str, str | None] | None = None
        self._robots_cache: list[str] | None = None
        # WEB-G006:抓取统计(迭代过程中累积,同步层读取)
        self.run_stats: dict | None = None
        self._last_run_full = False
        self._seen_urls: set[str] = set()
        self._rejected_urls: set[str] = set()
        # P1 退休安全:本轮全量发现的权威成员 URL(robots 通过即记,先于单页
        # 抓取/抽取)——成员资格与抽取成功分离,供 sync 退休决策使用。
        self._accepted_urls: list[str] | None = None
        # 阶段⑩ W6:待提交快照(全量轮 fetch_deleted 计算,删除效应安全完成后
        # 由 commit_membership_snapshot 落盘);None = 无待提交。
        self._pending_snapshot: set[str] | None = None

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

    def _robots_disallows(self) -> list[str]:
        """robots.txt Disallow 前缀(每轮缓存);获取失败按全允许处理。"""
        if self._robots_cache is not None:
            return self._robots_cache
        try:
            text = self._http_get(f"{self._base_url}/robots.txt")
            disallows = parse_robots_disallows(text, USER_AGENT.split("/")[0])
        except Exception as exc:  # noqa: BLE001 - 无 robots/抓取失败 → 全允许
            logger.info("robots.txt 不可得,按全允许处理: %s", str(exc)[:120])
            disallows = []
        self._robots_cache = disallows
        return disallows

    def _robots_blocked(self, url: str) -> bool:
        path = urlparse(url).path
        return any(path.startswith(prefix) for prefix in self._robots_disallows())

    _REJECTED_URLS_CAP = 500  # 每类拒绝原因记录的 URL 上限(证据可读性)

    def _new_stats(self) -> dict:
        return {
            "full": False,
            "discovered": 0,
            "accepted": 0,
            "extracted": 0,
            "failed": 0,
            "failed_urls": [],
            "rejected": {"exclude": 0, "robots": 0, "low_content": 0},
            "rejected_urls": {"exclude": [], "robots": [], "low_content": []},
        }

    def _discovery_fetch(self, url: str) -> str | None:
        """sitemap 发现用抓取:任何失败返回 None(证据由发现层 errors 记账,不抛异常)。

        复用 ``_http_get``(UA/超时/重试);每次抓取后按 ``crawl_delay_ms``
        限速(与旧版子表间限速同语义,礼貌优先)。
        """
        text: str | None = None
        try:
            text = self._http_get(url)
        except RuntimeError as exc:
            logger.info("sitemap 发现抓取失败: %s: %s", url, str(exc)[:120])
        time.sleep(self._delay_s)
        return text

    def _sitemap_entries(self) -> dict[str, str | None]:
        """sitemap 发现 → 规范化合并去重 {url: lastmod}(排除规则照常生效)。

        #17:Yoast 三子表命名过滤(``_SITEMAP_KIND_RE``)按 S0 冻结方向退役,
        统一走 ``website_discovery.discover_sitemap_entries`` 组合原语——
        robots.txt ``Sitemap:`` 指令 → 显式 ``sitemap_url`` 配置 → 通用回退
        (``/sitemap_index.xml`` → ``/sitemap.xml``)→ index 全部同域子表,
        无任何命名偏好。canonical 归一与同域边界由发现层完成;此处仅叠加
        默认/配置排除。发现层零条目且有失败证据(全部候选抓取失败/非
        sitemap)→ RuntimeError 显式失败(零发现不伪装成功);urlset 合法
        但为空 → 空集照常完成(与旧语义一致)。

        惰性导入:website_discovery 复用本模块解析原语(canonical_url 等),
        模块级互相导入会成环。
        """
        if self._entries_cache is not None:
            return self._entries_cache
        from backend.services.website_discovery import discover_sitemap_entries

        discovery = discover_sitemap_entries(
            self._base_url,
            self._discovery_fetch,
            sitemap_url=self._sitemap_url,
        )
        entries: dict[str, str | None] = {}
        for canon, lastmod in discovery.entries.items():
            if self._excluded(canon):
                self._stats_reject("exclude", canon)
                continue
            entries[canon] = lastmod
        if not discovery.entries and discovery.errors:
            raise RuntimeError(
                "sitemap 自动发现失败(零 URL,证据: " + "; ".join(discovery.errors[:5]) + ")"
            )
        logger.info(
            "web_crawl %s: sitemap 自动发现(%s)共 %d 个 URL(排除后 %d)",
            self._id,
            self._sitemap_url or "robots/通用回退",
            len(discovery.entries),
            len(entries),
        )
        self._entries_cache = entries
        return entries

    _SKIP_HREF_EXTS = frozenset(
        {
            ".jpg",
            ".jpeg",
            ".png",
            ".gif",
            ".webp",
            ".svg",
            ".css",
            ".js",
            ".zip",
            ".gz",
            ".mp4",
            ".mp3",
            ".ico",
            ".woff",
            ".woff2",
            ".ttf",
        }
    )

    def _stats_reject(self, reason: str, url: str | None = None) -> None:
        """拒绝计数;提供 url 时按唯一 URL 去重(导航重复链接不膨胀计数)。"""
        if self.run_stats is None:
            return
        if url is not None:
            if url in self._rejected_urls:
                return
            self._rejected_urls.add(url)
            lst = self.run_stats["rejected_urls"].get(reason)
            if lst is not None and len(lst) < self._REJECTED_URLS_CAP:
                lst.append(url)
        self.run_stats["rejected"][reason] = self.run_stats["rejected"].get(reason, 0) + 1

    def _same_domain_links(self, html: str) -> list[str]:
        """提取同域内容页链接(规范化/去资产后缀/排除项),供增量发现。"""
        out: list[str] = []
        for m in re.finditer(r'href=["\']([^"\']+)["\']', html):
            raw = m.group(1).strip()
            if raw.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            # 站方残缺 href(如 "resources.camthink.ai" 无 scheme)会拼出
            # 垃圾 URL:无斜杠且含点 → 视为域名样式,跳过
            if "/" not in raw and "." in raw:
                continue
            absu = raw[2:] if raw.startswith("//") else raw
            path_part = absu if absu.startswith("/") else f"/{absu}"
            if Path(urlparse(f"https://x{path_part}").path).suffix.lower() in self._SKIP_HREF_EXTS:
                continue
            canon = canonical_url(self._base_url, absu)
            if canon is None:
                continue  # 外域(含协议相对外域)
            if canon in self._seen_urls:
                continue  # 已在视野(已知页),非拒绝
            if self._excluded(canon):
                self._stats_reject("exclude", canon)
                continue
            out.append(canon)
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
            # content_hash 含 URL 路径:同内容不同页不互撞(PG 主键保护,WEB-G005)
            content_hash=hashlib.sha256(f"{path}|{md}".encode()).hexdigest(),
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

    def authoritative_source_ids(self) -> set[str] | None:
        """本轮全量发现的权威成员集(source_id 空间),无全量轮 → None。

        成员资格以「robots 通过并被接受」为准 —— 先于单页抓取/抽取记账,
        故临时抓取失败、超时、薄内容被拒的页面**仍在成员集内**。退休决策
        必须以本集合(权威枚举)为证据,而非抽取成功的产出集合。
        """
        if not getattr(self, "_last_run_full", False) or self._accepted_urls is None:
            return None
        return {f"{self._id}/{_url_to_source_path(u)}" for u in self._accepted_urls}

    def fetch_all(self) -> Iterator[RawDocument]:
        """全量:sitemap 起点 + 同域链接发现(BFS,上限 max_pages)+ 全程记账。"""
        self.run_stats = self._new_stats()
        self._accepted_urls = []
        self._rejected_urls = set()
        self._robots_cache = None  # 每轮全量重新获取 robots
        self._seen_urls: set[str] = set(self._sitemap_entries())
        self.run_stats["discovered"] = len(self._seen_urls)
        self._last_run_full = True
        self.run_stats["full"] = True
        queue = sorted(self._seen_urls)
        extra_cap = int(self._config.config.get("max_pages", 150))
        failures = 0
        successes = 0
        while queue:
            url = queue.pop(0)
            if self._robots_blocked(url):
                self._stats_reject("robots", url)
                logger.info("robots Disallow,跳过 %s", url)
                continue
            self.run_stats["accepted"] += 1
            self._accepted_urls.append(url)
            try:
                doc, links = self._fetch_page(url)
            except RuntimeError as exc:
                # 发现链接可能 404/残缺:单页失败跳过并记账,不拖垮整轮同步
                failures += 1
                self.run_stats["failed"] += 1
                self.run_stats["failed_urls"].append(url)
                logger.warning("页面抓取失败,跳过 %s: %s", url, str(exc)[:120])
                continue
            if len(doc.content.strip()) < self._min_content:
                # 薄内容(模板壳/挑战页/空壳)不入语料,计入 rejected
                self._stats_reject("low_content", url)
                logger.info("薄内容页面跳过 %s(md=%d 字符)", url, len(doc.content.strip()))
                continue
            successes += 1
            self.run_stats["extracted"] += 1
            for link in links:
                if (
                    link not in self._seen_urls
                    and len(self._seen_urls) < len(self._sitemap_entries()) + extra_cap
                ):
                    self._seen_urls.add(link)
                    self.run_stats["discovered"] += 1
                    queue.append(link)
            yield doc
        if successes == 0 and failures > 0:
            raise RuntimeError(f"全量抓取全部失败({failures} 页)")

    def fetch_changes(self, since: datetime) -> Iterator[RawDocument]:
        """增量:仅 lastmod 存在且 ≥ since 的 URL(无 lastmod 不进增量)。

        增量轮视野仅限 sitemap(不 BFS),故 ``_last_run_full=False``:
        fetch_deleted 在增量轮不做删除(防 BFS 发现页被误删,覆盖震荡根因)。
        """
        self.run_stats = self._new_stats()
        self._last_run_full = False
        self._accepted_urls = None  # 增量轮无权威成员集证据
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
            self.run_stats["extracted"] += 1
            yield doc

    def commit_membership_snapshot(self) -> None:
        """推进成员快照(阶段⑩ W6 冻结序:retirement 效应安全完成后才落盘)。

        由 sync 层在删除循环完成后调用;删除中途被 kill 时本方法不会执行,
        旧快照保留 → 下一轮重新报告同一差集(重复删除幂等,PRUNE IS
        DOCUMENT-LOCAL 不变)。无待提交快照(增量轮/重复调用)→ no-op。
        """
        if self._pending_snapshot is not None:
            self._save_state(self._pending_snapshot)
            self._pending_snapshot = None

    def fetch_deleted(self, since: datetime) -> list[str]:
        """删除:仅全量轮做差集(上一轮状态 vs 本轮 全量视野)。

        增量轮视野仅 sitemap,若据此判删会把 BFS 发现页误删(覆盖震荡),
        故增量轮返回 [] 且不推进快照。

        阶段⑩ W6:全量轮也**不再在此处落盘**——只计算差集并把当前成员集
        挂入 ``_pending_snapshot``,由 sync 层在删除循环安全完成后调用
        ``commit_membership_snapshot()`` 推进。kill 于删除中途 → 旧快照
        保留 → 未完成的 retirement 下轮重新发现(幂等重删收敛)。
        """
        if not self._last_run_full:
            return []
        known = set(self._seen_urls or set())
        current_ids = {f"{self._id}/{_url_to_source_path(u)}" for u in known}
        previous = self._load_state()
        self._pending_snapshot = current_ids
        return sorted(previous - current_ids)
