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
