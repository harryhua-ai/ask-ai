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

from backend.connectors.safety import FileAdmission, KnowledgeRole
from backend.connectors.web_crawl import (
    DEFAULT_EXCLUDE_PATTERNS,
    canonical_url,
    parse_sitemap_index,
    parse_urlset,
)
from backend.services.source_discovery import (
    DiscoveryResult,
    ORIGIN_FAMILY_CONFLICT,
    annotate_scope,
    apply_discovery_rules,
    build_discovery_result,
    parse_discovery_rules,
    rules_matching,
)

FetchFn = Callable[[str], "str | None"]

# robots.txt Sitemap: 指令(组无关——规范定义 Sitemap 不隶属任何 user-agent 组)
_ROBOTS_SITEMAP_RE = re.compile(r"^sitemap\s*:\s*(\S+)\s*$", re.IGNORECASE)

# 合法但为空的 urlset 识别(parse_urlset 无法区分「空 urlset」与「非 sitemap」,
# 两者都返回 {};证据纪律要求二者分开记账,不得把合法空集标成 not_sitemap)
_URLSET_ROOT_RE = re.compile(r"<(?:[\w.-]+:)?urlset(?:\s|>)", re.IGNORECASE)


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
    # entries 实际来源层(explicit|robots|generic|none;#17 诚实呈现用,
    # robots 声明但失败的候选不冒充来源)
    entry_source: str = "none"

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
        """处理同一层级的一组 sitemap 候选(index 子表在同层继续入队)。

        回退层语义(#17 修正):「已有任何发现即停止」只作用于**根候选**
        (有界试探,不重复请求);已被解析 index 收录的**子表**不受停止
        规则约束——index 既已解析,其子表就是本次发现的承诺范围,在根
        候选出条目后被抛弃会造成「index 解析成功、子表静默丢失」。
        """
        roots = [u for u in urls if not (u in seen or seen.add(u))]
        children: list[str] = []
        while (
            (roots or children)
            and len(result.resolved) < max_sitemaps
            and len(result.entries) < max_entries
        ):
            if children:
                url = children.pop(0)
            else:
                if stop_on_entries and result.entries:
                    return
                url = roots.pop(0)
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
                        children.append(sub)
                continue
            urlset = parse_urlset(text)
            if urlset:
                result.resolved.append(SitemapSource(url=url, kind="urlset"))
                for loc, lastmod in urlset.items():
                    canon = canonical_url(base_url, loc)
                    if canon is None:  # 外域/非法 URL
                        continue
                    result.entries.setdefault(canon, lastmod)
            elif _URLSET_ROOT_RE.search(text[:2048]):
                # 合法但为空的 urlset:计入 resolved,零 entries,无错误证据
                result.resolved.append(SitemapSource(url=url, kind="urlset"))
            else:
                result.errors.append(f"not_sitemap:{url}")

    if sitemap_url:
        _drain([sitemap_url], stop_on_entries=False)
        result.entry_source = "explicit" if result.entries else "none"
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
        # ① robots 指令(声明的同域 sitemap 全取)② 通用回退(根候选成功即停)
        _drain(result.robots_sitemaps, stop_on_entries=False)
        if result.entries:
            result.entry_source = "robots"
        _drain(fallback_sitemap_candidates(base), stop_on_entries=True)
        if result.entries and not result.robots_sitemaps:
            result.entry_source = "generic"
        elif result.entries and result.entry_source == "none":
            result.entry_source = "generic"
    return result


# ---------------------------------------------------------------------------
# URL 级知识分类(preview 推荐启发;#17 消费。分类只影响推荐,不影响
# Technical Safety——URL 抓取后的正文质量仍由 connector 薄内容阈值裁决)
# ---------------------------------------------------------------------------

# 低价值默认排除(PD-3:login/register/account/search/cart/checkout/
# user center/tag/category/archive;query 变体由 canonical 归一剥离)。
# ``/store/`` 为 C8 商城分离契约对齐:预览排除必须与 crawl 排除(连接器
# 默认清单含 /store/)同视野,否则「预览说排除、同步却抓入」。
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
    "/store/",
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


# ---------------------------------------------------------------------------
# #17 Website Simple Mode:preview / recommendation 组装(纯函数,IO 仍注入)
# ---------------------------------------------------------------------------

# 大型下载/二进制资产后缀:V1 文本管线(HTML→Markdown)不消费,sitemap 里
# 出现即预览排除(与 web_crawl 页内链接发现的资产跳过后缀同词表 + 文档类)。
BINARY_ASSET_SUFFIXES: frozenset[str] = frozenset(
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
        ".tar",
        ".mp4",
        ".mp3",
        ".ico",
        ".woff",
        ".woff2",
        ".ttf",
        ".pdf",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".dmg",
        ".exe",
        ".apk",
    }
)

# V1 能力边界(冻结文案;preview 必须让管理员知道系统没做什么)
CAPABILITY_NOTES_WEBSITE: tuple[str, ...] = (
    "V1 仅静态 HTML 与 sitemap 发现:需要 JavaScript 渲染的页面无法被发现",
    "仅采集与站点同域的 URL;跨域 sitemap 与链接一律跳过,不会自动跟随",
    "同步阶段会从页面链接做同域受控扩展发现(有上限);预览仅呈现 sitemap 发现结果",
    "正文质量在抓取后仍由薄内容阈值二次过滤;预览推荐不等于最终入库",
)


def url_group_key(url: str) -> str:
    """URL → 首层路径段分组键(确认 UI 的主视图;根页归 ``(root)``)。"""
    path = urlparse(url).path.strip("/")
    first = path.split("/", 1)[0] if path else ""
    return first or "(root)"


def apply_family_evidence(result: DiscoveryResult) -> DiscoveryResult:
    """族群证据分类(Planner REV 1 §2;#22 网站侧 L2 证据通道)。

    同前缀家族(首层路径段)内**已判定成员**的归票:
    - 投票来源 = 持久规则继承成员(``rule:*`` 印章)+ 优先类别 hint 命中成员
      (recommendation=include 且无印章)。L1 成员(二进制/URL 排除清单,
      ``l1:*`` 印章)基于自身证据排除,**不参与投票**;
    - 族内票**完全一致** → 未判定成员(兜底 review)继承该决策为 L2,
      盖 ``family:*`` 印章(frozen 文案「同族路径已有一致判定」);
    - 族内票**冲突** → 未判定成员维持 review 并盖 ``family_conflict`` 印章
      (真歧义如实暴露,不得用默认值美化);
    - 无票 → 兜底 review 原样保留(unknown path 本身永远不是 include/review 理由)。

    仅用于 Website preview:仓库侧 review 带(1MB–64MB/密钥模板)按 PD-2
    冻结维持人工,不由族群证据自动翻转。
    """
    if result.group_key is None:
        return result
    origins = dict(result.decision_origins)
    families: dict[str, list] = {}
    for a in result.candidates:
        families.setdefault(result.group_key(a.path), []).append(a)
    for _key, members in families.items():
        votes: set[str] = set()
        for m in members:
            origin = origins.get(m.path, "")
            if origin.startswith("rule:"):
                votes.add(origin.split(":", 1)[1])
            elif origin.startswith(("l1:", ORIGIN_FAMILY_CONFLICT)):
                continue
            elif m.recommendation == "include":
                votes.add("include")
        if len(votes) > 1:
            for m in members:
                if m.recommendation == "review" and not origins.get(m.path):
                    origins[m.path] = ORIGIN_FAMILY_CONFLICT
            continue
        if not votes:
            continue
        decision = next(iter(votes))
        for m in members:
            if m.recommendation == "review" and not origins.get(m.path):
                m.recommendation = decision
                origins[m.path] = f"family:{decision}"
    result.decision_origins = origins
    from backend.services.source_discovery import _rebuild_views

    _rebuild_views(result)
    return result


def build_website_preview(
    base_url: str,
    fetch_fn: FetchFn,
    *,
    sitemap_url: str | None = None,
    max_sitemaps: int = 25,
    max_entries: int = 5000,
    discovery_rules: list[dict] | None = None,
) -> DiscoveryResult:
    """Website Simple Mode 发现 → 统一 DiscoveryResult(source_discovery envelope)。

    组合:PD-3 冻结顺序的 :func:`discover_sitemap_entries` → 逐 URL 走
    ``classify_url`` + 二进制资产排除(复用 FileAdmission 单候选模型,
    Technical Safety / Knowledge filtering 语义不另起一套)→
    :func:`build_discovery_result` 聚合。零发现不伪装成功:entries 为空时
    warnings 保留冻结告警,candidates/totals 为空,由调用方(UI)显式呈现。

    ``recommended_config`` 编译产物 = 既有 web_crawl config JSONB 词表:
    ``base_url`` + 排除清单(连接器默认 ∪ 预览排除,保证「预览=同步视野」);
    sitemap 地址默认自动管理,**不**钉死解析结果(站点迁移 sitemap 后
    下轮同步自动跟随;显式 override 走 Advanced 配置)。

    #22 治理增量:``discovery_rules``(既有源持久策略,治理记忆)→ 规则继承
    → 族群证据分类(unknown path 靠证据而非默认值)→ 规则排除项并入编译
    exclude_patterns(预览=同步视野)→ 逐 include 组 scope_confirmed。
    """
    discovery = discover_sitemap_entries(
        base_url,
        fetch_fn,
        sitemap_url=sitemap_url,
        max_sitemaps=max_sitemaps,
        max_entries=max_entries,
    )
    base = base_url.rstrip("/")

    candidates: list[FileAdmission] = []
    decision_origins: dict[str, str] = {}
    for url in sorted(discovery.entries):
        # canonical_url 统一补尾斜杠,后缀判定须先剥掉(如 /a.pdf/ → .pdf)
        path = urlparse(url).path.rstrip("/")
        last_dot = path.rsplit(".", 1)
        ext = f".{last_dot[1].lower()}" if len(last_dot) == 2 and last_dot[1] else ""
        if ext in BINARY_ASSET_SUFFIXES:
            decision_origins[url] = "l1:binary"
            candidates.append(
                FileAdmission(
                    path=url,
                    size=0,
                    technical_safe=False,
                    technical_reason="binary_content",
                    knowledge_role=KnowledgeRole.BINARY.value,
                    recommendation="exclude",
                )
            )
            continue
        role, rec = classify_url(urlparse(url).path)
        if rec == "exclude":
            decision_origins[url] = "l1:exclude"  # URL 排除清单=L1,规则不可翻转
        candidates.append(
            FileAdmission(
                path=url,
                size=0,
                technical_safe=True,
                technical_reason=None,
                knowledge_role=role,
                recommendation=rec,
            )
        )

    # 发现方式(诚实呈现 sitemap 实际从哪一层解析而来:显式指定 / robots
    # 声明 / 通用回退 / 无)。由发现层记账(entry_source),声明但失败的
    # 候选不冒充来源——失败证据已进 warnings。
    if sitemap_url:
        mode = "explicit"
    else:
        mode = discovery.entry_source

    warnings = list(discovery.warnings())
    if len(discovery.entries) >= max_entries:
        warnings.append(f"发现 URL 数达到预览上限 {max_entries},预览已截断(不影响同步范围)")

    target = {
        "base_url": base,
        "requested_sitemap_url": sitemap_url,
        "discovery_mode": mode,
        "resolved_sitemaps": [s.url for s in discovery.resolved],
        "robots_declared": list(discovery.robots_sitemaps),
        "cross_domain_skipped": [
            e.partition(":")[2] for e in discovery.errors if e.startswith("cross_domain_skipped:")
        ],
    }

    result = build_discovery_result(
        "web_crawl",
        target,
        candidates,
        group_key=url_group_key,
        recommended_config={
            "base_url": base,
            # 连接器默认清单 ∪ 预览排除清单:写入 config 后 crawl 视野与预览一致
            # (含 C8 /store/ 商城分离,不会因整体替换而丢失)。
            "exclude_patterns": sorted(set(DEFAULT_EXCLUDE_PATTERNS) | set(URL_EXCLUDE_PATTERNS)),
        },
        warnings=warnings,
        capability_notes=list(CAPABILITY_NOTES_WEBSITE),
    )
    result.decision_origins = decision_origins

    # #22 治理链:规则继承 → 族群证据(unknown path 证据化,兜底 review 保留)
    # → 规则排除项并入编译清单(预览=同步视野)→ 逐 include 组 scope 确认。
    rules = parse_discovery_rules(discovery_rules)
    result = apply_discovery_rules(result, rules)
    result = apply_family_evidence(result)
    matched = rules_matching(result, rules)
    rule_exclude = sorted({r["pattern"] for r in matched if r["decision"] == "exclude"})
    if rule_exclude:
        result.recommended_config = {
            **result.recommended_config,
            "exclude_patterns": sorted(
                set(result.recommended_config.get("exclude_patterns") or []) | set(rule_exclude)
            ),
        }
    result.warnings = list(result.warnings) + annotate_scope(result)
    return result
