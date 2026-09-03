"""Website Discovery 原语测试(S0 / PD-3 组合契约)。

全部离线:fetch_fn 注入。覆盖——
- robots Sitemap: 指令发现;
- 通用候选回退(/sitemap_index.xml → /sitemap.xml,非 Yoast 也可用);
- sitemap index 递归全部子表(无命名过滤 = Yoast 专用正则的退休);
- urlset 提取 + canonical 归一 + 外域丢弃;
- 零发现显式告警;
- URL 分类启发(低价值排除 / 优先类别 / 未知 review)。
"""

from backend.services.website_discovery import (
    classify_url,
    discover_sitemap_entries,
    fallback_sitemap_candidates,
    parse_robots_sitemaps,
)

BASE = "https://www.example.com"

ROBOTS = """
User-agent: *
Disallow: /private/
Sitemap: {base}/sitemap_index.xml
Sitemap: https://cdn.example.com/external.xml
""".format(base=BASE)

INDEX_XML = """<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>{base}/pages-1.xml</loc></sitemap>
  <sitemap><loc>{base}/products.xml</loc></sitemap>
  <sitemap><loc>https://other-host.net/evil.xml</loc></sitemap>
</sitemapindex>
""".format(base=BASE)

# 非 Yoast 命名(pages-1/products)——按 design 必须被收录
PAGES_XML = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{base}/</loc><lastmod>2026-09-01</lastmod></url>
  <url><loc>{base}/docs/quickstart/?utm_source=x</loc></url>
  <url><loc>{base}/login</loc></url>
</urlset>
""".format(base=BASE)

PRODUCTS_XML = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{base}/products/ne301</loc><lastmod>2026-09-02</lastmod></url>
</urlset>
""".format(base=BASE)

GENERIC_SITEMAP_XML = PAGES_XML  # /sitemap.xml 直取形态


def _fetch_map(mapping, hits=None):
    def fetch(url: str):
        if hits is not None:
            hits.append(url)
        return mapping.get(url)

    return fetch


# ------------------------------------------------------- robots 指令


def test_parse_robots_sitemaps():
    urls = parse_robots_sitemaps(ROBOTS)
    assert urls == [f"{BASE}/sitemap_index.xml", "https://cdn.example.com/external.xml"]


def test_robots_without_sitemap_directive():
    assert parse_robots_sitemaps("User-agent: *\nDisallow: /\n") == []


def test_fallback_candidates():
    assert fallback_sitemap_candidates(BASE) == [
        f"{BASE}/sitemap_index.xml",
        f"{BASE}/sitemap.xml",
    ]


# ------------------------------------------------------- 组合发现


def test_discovery_via_robots_directive_and_index_all_children():
    """robots 指令 → index → 全部同域子表(无命名过滤);外域子表丢弃。"""
    fetch = _fetch_map(
        {
            f"{BASE}/robots.txt": ROBOTS,
            f"{BASE}/sitemap_index.xml": INDEX_XML,
            f"{BASE}/pages-1.xml": PAGES_XML,
            f"{BASE}/products.xml": PRODUCTS_XML,
        }
    )
    d = discover_sitemap_entries(BASE, fetch)
    assert [s.kind for s in d.resolved] == ["index", "urlset", "urlset"]
    assert set(d.entries) == {
        f"{BASE}/",
        f"{BASE}/docs/quickstart/",  # query 已剥离 + 尾斜杠归一
        f"{BASE}/login/",
        f"{BASE}/products/ne301/",
    }
    assert d.entries[f"{BASE}/"] == "2026-09-01"
    assert not any(e.startswith("fetch_failed") for e in d.errors)
    assert not d.zero_discovery


def test_robots_cross_domain_sitemap_skipped_explicitly():
    """PD-3 不跨域:robots 声明的他域 sitemap 显式跳过并出告警,不静默。"""
    hits: list[str] = []
    fetch = _fetch_map(
        {
            f"{BASE}/robots.txt": ROBOTS,
            f"{BASE}/sitemap_index.xml": INDEX_XML,
            f"{BASE}/pages-1.xml": PAGES_XML,
            f"{BASE}/products.xml": PRODUCTS_XML,
        },
        hits=hits,
    )
    d = discover_sitemap_entries(BASE, fetch)
    assert "https://cdn.example.com/external.xml" not in hits  # 从未抓取
    assert any(e.startswith("cross_domain_skipped:") for e in d.errors)
    assert any("跨域" in w for w in d.warnings())


def test_discovery_generic_sitemap_xml_fallback():
    """非 Yoast 站点:robots 无指令、index 缺席 → /sitemap.xml 通用回退。"""
    hits: list[str] = []
    fetch = _fetch_map(
        {
            f"{BASE}/robots.txt": "User-agent: *\nDisallow: /nopriv/\n",
            f"{BASE}/sitemap_index.xml": None,  # 404
            f"{BASE}/sitemap.xml": GENERIC_SITEMAP_XML,
        },
        hits=hits,
    )
    d = discover_sitemap_entries(BASE, fetch)
    assert hits == [
        f"{BASE}/robots.txt",
        f"{BASE}/sitemap_index.xml",
        f"{BASE}/sitemap.xml",
    ]
    assert d.zero_discovery is False
    assert f"{BASE}/login/" in d.entries


def test_zero_discovery_is_explicit_not_silent():
    """全部候选失败/无效:zero_discovery 显式 + 人读告警(禁止静默成功)。"""
    fetch = _fetch_map({f"{BASE}/robots.txt": None})  # robots 无,两个回退都失败
    d = discover_sitemap_entries(BASE, fetch)
    assert d.zero_discovery
    assert any("未发现任何 sitemap" in w for w in d.warnings())
    assert len(d.errors) == 2  # 两个回退都记录 fetch_failed


def test_not_sitemap_response_is_recorded():
    """HTML/垃圾响应 ≠ sitemap:记 not_sitemap,不中断其余候选。"""
    fetch = _fetch_map(
        {
            f"{BASE}/robots.txt": f"Sitemap: {BASE}/blog.xml\n",
            f"{BASE}/blog.xml": "<html>404 page</html>",
            f"{BASE}/sitemap.xml": GENERIC_SITEMAP_XML,
        }
    )
    d = discover_sitemap_entries(BASE, fetch)
    assert any(e.startswith("not_sitemap:") for e in d.errors)
    assert d.entries  # 回退仍工作


def test_explicit_sitemap_url_skips_robots():
    hits: list[str] = []
    fetch = _fetch_map({f"{BASE}/custom.xml": PRODUCTS_XML}, hits=hits)
    d = discover_sitemap_entries(BASE, fetch, sitemap_url=f"{BASE}/custom.xml")
    assert hits == [f"{BASE}/custom.xml"]  # 显式配置优先,不请求 robots
    assert set(d.entries) == {f"{BASE}/products/ne301/"}


def test_index_depth_and_caps():
    """递归上限:子表数计入 max_sitemaps(防无界;PD-3 反对 unbounded crawler)。"""
    many_index = (
        "<sitemapindex>"
        + "".join(f"<sitemap><loc>{BASE}/s{i}.xml</loc></sitemap>" for i in range(40))
        + "</sitemapindex>"
    )
    fetch = _fetch_map({f"{BASE}/sitemap_index.xml": many_index})
    d = discover_sitemap_entries(BASE, fetch, max_sitemaps=5)
    assert len(d.resolved) <= 5


# ------------------------------------------------------- URL 分类启发


def test_classify_url_priority_categories():
    assert classify_url("/products/ne301") == ("product_doc", "include")
    assert classify_url("/docs/quickstart/") == ("technical_doc", "include")
    assert classify_url("/api/reference/auth") == ("api_reference", "include")
    assert classify_url("/faq/power") == ("troubleshooting", "include")


def test_classify_url_low_value_excluded():
    for p in ("/login", "/cart", "/my-account", "/tags/iot", "/search?q=x"):
        role, rec = classify_url(p)
        assert rec == "exclude", p


def test_classify_url_unknown_is_review_not_silent_include():
    assert classify_url("/some-random-page/") == ("technical_doc", "review")


# ------------------------------------------------------- #17 preview 组装

from backend.services.source_discovery import reason_text
from backend.services.website_discovery import (  # noqa: E402
    build_website_preview,
    url_group_key,
)


def _rec_counts(result):
    counts = {"include": 0, "exclude": 0, "review": 0}
    for c in result.candidates:
        counts[c.recommendation] += 1
    return counts


def test_preview_recommendation_counts_and_modes():
    """robots 模式:发现→分类→推荐计数;target 呈现发现方式与解析结果。"""
    fetch = _fetch_map(
        {
            f"{BASE}/robots.txt": ROBOTS,
            f"{BASE}/sitemap_index.xml": INDEX_XML,
            f"{BASE}/pages-1.xml": PAGES_XML,
            f"{BASE}/products.xml": PRODUCTS_XML,
        }
    )
    result = build_website_preview(BASE, fetch)
    assert result.kind == "web_crawl"
    # login=exclude;docs/quickstart、products/ne301=include;根页=review
    assert _rec_counts(result) == {"include": 2, "exclude": 1, "review": 1}
    assert result.totals["files"] == 4
    assert result.target["discovery_mode"] == "robots"
    assert f"{BASE}/sitemap_index.xml" in result.target["robots_declared"]
    assert result.target["resolved_sitemaps"] == [
        f"{BASE}/sitemap_index.xml",
        f"{BASE}/pages-1.xml",
        f"{BASE}/products.xml",
    ]


def test_preview_reasons_are_frozen_copy_not_generated():
    """逐候选带人读理由(枚举映射,与 wire 层 reason_text 同一冻结文案)。"""
    fetch = _fetch_map(
        {
            f"{BASE}/robots.txt": ROBOTS,
            f"{BASE}/sitemap_index.xml": INDEX_XML,
            f"{BASE}/pages-1.xml": PAGES_XML,
            f"{BASE}/products.xml": PRODUCTS_XML,
        }
    )
    result = build_website_preview(BASE, fetch)
    by_rec = {}
    for c in result.candidates:
        by_rec[(c.recommendation, c.path)] = reason_text(c)
    assert by_rec[("include", f"{BASE}/products/ne301/")] == "属于产品文档,建议纳入"
    assert by_rec[("include", f"{BASE}/docs/quickstart/")] == "属于技术文档,建议纳入"
    assert by_rec[("exclude", f"{BASE}/login/")] == "知识价值低(技术文档),建议排除"
    assert by_rec[("review", f"{BASE}/")] == "需要人工确认(技术文档)"


def test_preview_binary_asset_url_excluded_with_reason():
    """下载/二进制资产 URL:technical_safe=False,推荐排除(文本管线不消费)。"""
    assets_xml = """<?xml version="1.0"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>{base}/downloads/datasheet.pdf</loc></url>
      <url><loc>{base}/products/ne301</loc></url>
    </urlset>
    """.format(base=BASE)
    fetch = _fetch_map(
        {
            f"{BASE}/robots.txt": f"Sitemap: {BASE}/sitemap.xml\n",
            f"{BASE}/sitemap.xml": assets_xml,
        }
    )
    result = build_website_preview(BASE, fetch)
    pdf = next(c for c in result.candidates if "datasheet.pdf" in c.path)
    assert pdf.technical_safe is False
    assert pdf.technical_reason == "binary_content"
    assert pdf.recommendation == "exclude"
    assert reason_text(pdf) == "二进制内容,不可作为文本知识"
    assert result.totals["unsafe_files"] == 1


def test_preview_recommended_config_unifies_preview_and_crawl_scope():
    """推荐配置 = 连接器词表;排除清单必须含 /store/(C8)与预览排除词表
    (预览=同步视野,不出现「预览说排除、同步却抓入」)。"""
    fetch = _fetch_map(
        {
            f"{BASE}/robots.txt": ROBOTS,
            f"{BASE}/sitemap_index.xml": INDEX_XML,
            f"{BASE}/pages-1.xml": PAGES_XML,
            f"{BASE}/products.xml": PRODUCTS_XML,
        }
    )
    result = build_website_preview(BASE, fetch)
    cfg = result.recommended_config
    assert cfg["base_url"] == BASE
    pats = set(cfg["exclude_patterns"])
    assert "/store/" in pats  # C8 商城分离
    assert "/search" in pats and "/tag/" in pats  # 预览排除词表
    # sitemap 地址不钉死:默认自动管理(下轮同步自动跟随站点)
    assert "sitemap_url" not in cfg


def test_preview_zero_discovery_is_explicit_not_success():
    """零发现:200 语义但 totals=0 + 冻结告警(禁止伪装成功)。"""
    fetch = _fetch_map({f"{BASE}/robots.txt": None})
    result = build_website_preview(BASE, fetch)
    assert result.totals["files"] == 0
    assert result.candidates == []
    assert result.target["discovery_mode"] == "none"
    assert any("未发现任何 sitemap" in w for w in result.warnings)
    assert result.capability_notes  # 能力边界必须随结果呈现


def test_preview_generic_mode_and_cross_domain_reason():
    """通用回退命中 → discovery_mode=generic;跨域 sitemap 跳过带原因。"""
    fetch = _fetch_map(
        {
            f"{BASE}/robots.txt": ROBOTS,  # 含跨域声明 cdn.example.com
            f"{BASE}/sitemap_index.xml": None,  # 404
            f"{BASE}/sitemap.xml": GENERIC_SITEMAP_XML,
        }
    )
    result = build_website_preview(BASE, fetch)
    assert result.target["discovery_mode"] == "generic"
    assert result.target["cross_domain_skipped"] == ["https://cdn.example.com/external.xml"]
    assert any("跨域" in w for w in result.warnings)


def test_preview_groups_by_first_path_segment():
    """分组 = 首层路径段;混合推荐组保守给 review(共享聚合规则)。"""
    fetch = _fetch_map(
        {
            f"{BASE}/robots.txt": ROBOTS,
            f"{BASE}/sitemap_index.xml": INDEX_XML,
            f"{BASE}/pages-1.xml": PAGES_XML,
            f"{BASE}/products.xml": PRODUCTS_XML,
        }
    )
    result = build_website_preview(BASE, fetch)
    keys = {g.key for g in result.groups}
    assert keys == {"(root)", "docs", "login", "products"}
    for g in result.groups:
        assert g.count >= 1 and g.samples


def test_url_group_key():
    assert url_group_key(f"{BASE}/docs/api/auth/") == "docs"
    assert url_group_key(f"{BASE}/") == "(root)"


def test_preview_explicit_sitemap_mode():
    """显式 sitemap_url → discovery_mode=explicit(Advanced override 可用)。"""
    fetch = _fetch_map({f"{BASE}/custom.xml": PRODUCTS_XML})
    result = build_website_preview(BASE, fetch, sitemap_url=f"{BASE}/custom.xml")
    assert result.target["discovery_mode"] == "explicit"
    assert result.target["requested_sitemap_url"] == f"{BASE}/custom.xml"
    assert _rec_counts(result) == {"include": 1, "exclude": 0, "review": 0}
