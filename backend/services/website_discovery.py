"""通用 Website Discovery 原语(S0 skeleton;#17 网站自动发现消费)。

PD-3 冻结的组合顺序,本模块提供**纯组合骨架 + 注入式抓取**:
    robots.txt ``Sitemap:`` 指令
      → 显式 sitemap_url(如有)
      → 通用候选回退(/sitemap_index.xml → /sitemap.xml)
      → sitemap index 递归(**全部子表,不做任何命名过滤**)
      → urlset 条目提取(canonical 归一 + 同域边界)
      → URL candidates(交由 source_discovery 合同为推荐/预览消费)

与 connector(web_crawl.py)的关系:#17 将以本模块替换其 Yoast 专用的
``_SITEMAP_KIND_RE`` 子表过滤;S0 **不改 connector**,零行为变化。
``fetch_fn: Callable[[str], str | None]`` 注入(None=抓取失败不抛异常),
使全部组合逻辑可离线单测;#17 接线 requests/httpx 即可。

V1 冻结(PD-3 不支持,原语亦不假设):JS rendering / OCR / 图片理解 /
PDF ingestion / 无上限抓取 / 跨域自动抓取(index 内的外域子表一律丢弃)。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlparse

from backend.connectors.web_crawl import canonical_url, parse_sitemap_index, parse_urlset

FetchFn = Callable[[str], "str | None"]

# robots.txt Sitemap: 指令(组无关——规范定义 Sitemap 不隶属任何 user-agent 组)
_ROBOTS_SITEMAP_RE = re.compile(r"^sitemap\s*:\s*(\S+)\s*$", re.IGNORECASE)


def parse_robots_sitemaps(text: str) -> list[str]:
    """robots.txt → Sitemap: 指令 URL 列表(保持出现顺序,去重)。"""
    out: list[str] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        m = _ROBOTS_SITEMAP_RE.match(raw.strip())
        if m:
            url = m.group(1)
            if url not in seen:
                seen.add(url)
                out.append(url)
    return out


def fallback_sitemap_candidates(base_url: str) -> list[str]:
    """通用回退候选(显式配置与 robots 指令都缺失时按序尝试)。"""
    base = base_url.rstrip("/")
    return [f"{base}/sitemap_index.xml", f"{base}/sitemap.xml"]


@dataclass
class SitemapSource:
    """一个已解析的 sitemap 资源(index 或 urlset)。"""

    url: str
    kind: str  # "index" | "urlset"


@dataclass
class SitemapDiscovery:
    """sitemap 发现结果(#17 preview 的 URL 候选来源)。"""

    base_url: str
    requested_url: str | None = None
    robots_sitemaps: list[str] = field(default_factory=list)
    resolved: list[SitemapSource] = field(default_factory=list)
    entries: dict[str, str | None] = field(default_factory=dict)  # {canonical_url: lastmod}
    errors: list[str] = field(default_factory=list)  # fetch_failed:<url> / not_sitemap:<url>

    @property
    def zero_discovery(self) -> bool:
        """零发现显式标志(禁止把「没发现」当「没内容」静默成功)。"""
        return not self.entries

    def warnings(self) -> list[str]:
        """人读告警(冻结文案;零发现必告警)。"""
        out: list[str] = []
        if self.zero_discovery:
            out.append("未发现任何 sitemap URL:请核对站点地址,或在高级选项手填 sitemap 地址")
        for err in self.errors[:10]:
            kind, _, url = err.partition(":")
            if kind == "fetch_failed":
                out.append(f"sitemap 资源抓取失败: {url}")
            elif kind == "not_sitemap":
                out.append(f"地址不是有效的 sitemap: {url}")
            elif kind == "cross_domain_skipped":
                out.append(f"已跳过跨域 sitemap(不跨域自动抓取): {url}")
        return out


def discover_sitemap_entries(
    base_url: str,
    fetch_fn: FetchFn,
    *,
    sitemap_url: str | None = None,
    max_sitemaps: int = 25,
    max_entries: int = 20000,
) -> SitemapDiscovery:
    """按 PD-3 冻结顺序组合 sitemap 发现(纯编排,IO 全部经 fetch_fn 注入)。

    组合顺序:显式 sitemap_url > robots ``Sitemap:`` 指令 > 通用回退。
    index 递归其**全部**子表(同域过滤,无任何命名偏好——Yoast 专用
    正则的退休在此完成);urlset 条目经 :func:`canonical_url` 归一并
    丢弃外域(PD-3:不跨域)。
    """
    base = base_url.rstrip("/")
    result = SitemapDiscovery(base_url=base_url, requested_url=sitemap_url)
    base_host = urlparse(base_url).netloc.lower()

    def _same_host(url: str) -> bool:
        return urlparse(url).netloc.lower() == base_host

    seen: set[str] = set()

    def _drain(urls: list[str], *, stop_on_entries: bool) -> None:
        """处理同一层级的一组 sitemap 候选(index 子表在同层继续入队)。"""
        queue = [u for u in urls if not (u in seen or seen.add(u))]
        while queue and len(result.resolved) < max_sitemaps and len(result.entries) < max_entries:
            # 回退层语义:已有任何发现即停止(有界试探,不重复请求)
            if stop_on_entries and result.entries:
                return
            url = queue.pop(0)
            text = fetch_fn(url)
            if text is None:
                result.errors.append(f"fetch_failed:{url}")
                continue
            subs = parse_sitemap_index(text)
            if subs:
                result.resolved.append(SitemapSource(url=url, kind="index"))
                for sub in subs:
                    sub = sub.strip()
                    if not sub or sub in seen:
                        continue
                    # 外域子表丢弃(PD-3 不跨域);协议相对补 scheme
                    if sub.startswith("//"):
                        sub = f"https:{sub}"
                    if _same_host(sub):
                        seen.add(sub)
                        queue.append(sub)
                continue
            urlset = parse_urlset(text)
            if urlset:
                result.resolved.append(SitemapSource(url=url, kind="urlset"))
                for loc, lastmod in urlset.items():
                    canon = canonical_url(base_url, loc)
                    if canon is None:  # 外域/非法 URL
                        continue
                    result.entries.setdefault(canon, lastmod)
            else:
                result.errors.append(f"not_sitemap:{url}")

    if sitemap_url:
        _drain([sitemap_url], stop_on_entries=False)
    else:
        robots = fetch_fn(f"{base}/robots.txt")
        if robots:
            for url in parse_robots_sitemaps(robots):
                # PD-3:不跨域自动抓取——robots 声明的他域 sitemap 显式跳过,
                # 不静默(站点方若确有需求,走显式 sitemap_url 配置)
                if _same_host(url):
                    result.robots_sitemaps.append(url)
                else:
                    result.errors.append(f"cross_domain_skipped:{url}")
        # ① robots 指令(声明的同域 sitemap 全取)② 通用回退(成功即停)
        _drain(result.robots_sitemaps, stop_on_entries=False)
        _drain(fallback_sitemap_candidates(base), stop_on_entries=True)
    return result


# ---------------------------------------------------------------------------
# URL 级知识分类(preview 推荐启发;#17 消费。分类只影响推荐,不影响
# Technical Safety——URL 抓取后的正文质量仍由 connector 薄内容阈值裁决)
# ---------------------------------------------------------------------------

# 低价值默认排除(PD-3:login/register/account/search/cart/checkout/
# user center/tag/category/archive;query 变体由 canonical 归一剥离)
URL_EXCLUDE_PATTERNS: tuple[str, ...] = (
    "/login",
    "/signin",
    "/register",
    "/signup",
    "/account",
    "/my-account",
    "/cart",
    "/checkout",
    "/search",
    "/tag/",
    "/tags/",
    "/category/",
    "/archive",
    "/author/",
    "/wp-login",
    "/wp-admin",
    "/wp-json",
    "/feed",
    "/privacy",
    "/terms",
    "/cookie",
)

# 优先知识类别的路径启发(PD-3 优先清单 → 既有 KnowledgeRole 词表,零新词)
_PRIORITY_ROLE_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("api", "sdk", "reference", "docs/api"), "api_reference"),
    (("faq", "troubleshoot", "known-issue", "known_issue"), "troubleshooting"),
    (("product", "products", "solution", "solutions"), "product_doc"),
    (
        ("doc", "docs", "documentation", "guide", "guides", "manual", "tutorial", "support"),
        "technical_doc",
    ),
)


def classify_url(path: str) -> tuple[str, str]:
    """URL 路径 → (KnowledgeRole, recommendation)。纯函数。

    规则:命中低价值排除清单 → (technical_doc, exclude);命中优先类别
    → (对应角色, include);其余未知路径保守给 (technical_doc, review)
    ——preview 宁可让管理员多看,不静默纳入。
    """
    p = (path or "/").lower()
    if any(pat in p for pat in URL_EXCLUDE_PATTERNS):
        return ("technical_doc", "exclude")
    for hints, role in _PRIORITY_ROLE_HINTS:
        if any(h in p for h in hints):
            return (role, "include")
    return ("technical_doc", "review")
