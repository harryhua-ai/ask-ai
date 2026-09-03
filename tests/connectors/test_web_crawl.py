"""C8:web_crawl connector 契约测试(A1,全部离线 mock,不触真实官网)。

覆盖:sitemap 索引解析(三子表合并去重/排除)、排除规则(含配置替换)、
HTML→Markdown 清洗、增量(lastmod)、删除(状态文件差集)、元数据。
"""

import json
from datetime import UTC, datetime

import backend.connectors.web_crawl as wc
from backend.connectors.registry import ConnectorRegistry, SourceConfig
from backend.connectors.web_crawl import (
    html_to_markdown,
    parse_sitemap_index,
    parse_urlset,
)

# --------------------------------------------------------------------------- #
# sitemap 解析
# --------------------------------------------------------------------------- #

INDEX_XML = """<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://www.camthink.ai/post-sitemap.xml</loc></sitemap>
  <sitemap><loc>https://www.camthink.ai/page-sitemap.xml</loc></sitemap>
  <sitemap><loc>https://www.camthink.ai/product-sitemap.xml</loc></sitemap>
  <sitemap><loc>https://www.camthink.ai/category-sitemap.xml</loc></sitemap>
</sitemapindex>"""

URLSET = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.camthink.ai/products/neoeyes-503/</loc><lastmod>2026-08-20</lastmod></url>
  <url><loc>https://www.camthink.ai/products/neoeyes-503/</loc><lastmod>2026-08-21</lastmod></url>
</urlset>"""


def test_parse_sitemap_index_keeps_all_entries() -> None:
    locs = parse_sitemap_index(INDEX_XML)
    assert len(locs) == 4
    assert any("post-sitemap" in l for l in locs)


def test_parse_urlset_dedupes_and_keeps_lastmod() -> None:
    urls = parse_urlset(URLSET)
    assert urls == {"https://www.camthink.ai/products/neoeyes-503/": "2026-08-20"}


# --------------------------------------------------------------------------- #
# connector:sitemap 发现 + 排除规则
# --------------------------------------------------------------------------- #

PAGE_URLSET = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.camthink.ai/products/neoeyes-503/</loc><lastmod>2026-08-20</lastmod></url>
  <url><loc>https://www.camthink.ai/store/neoeyes-503-buy/</loc><lastmod>2026-08-20</lastmod></url>
  <url><loc>https://www.camthink.ai/privacy-policy/</loc><lastmod>2026-08-20</lastmod></url>
  <url><loc>https://www.camthink.ai/solutions/security-monitoring/</loc></url>
</urlset>"""


def _make_connector(tmp_path, extra: dict | None = None) -> wc.WebCrawlConnector:
    cfg = {
        "base_url": "https://www.camthink.ai",
        "crawl_delay_ms": 0,
        **(extra or {}),
    }
    return wc.WebCrawlConnector(
        SourceConfig(
            id="website-camthink",
            type="web_crawl",
            product="website",
            enabled=True,
            config=cfg,
            sync_interval="24h",
        )
    )


def _patch_http(monkeypatch, pages: dict[str, str]) -> list[str]:
    """把 requests.get 替换为本地表查找;返回实际请求的 URL 顺序。"""
    requested: list[str] = []

    class _Resp:
        status_code = 200

        @property
        def text(self):
            return pages[requested[-1]]

        def raise_for_status(self):
            return None

    def _get(url, **kwargs):
        requested.append(url)
        assert kwargs.get("headers", {}).get("User-Agent", "").startswith("ask-ai-crawler")
        return _Resp()

    monkeypatch.setattr(wc.requests, "get", _get)
    return requested


def test_sitemap_discovers_three_tables_excludes_store_and_privacy(tmp_path, monkeypatch):
    """三子表合并去重;/store/ 与隐私页排除;category 子表不抓。"""
    fetched = []

    def _get(url, **kwargs):
        fetched.append(url)
        if url.endswith("sitemap_index.xml"):
            return _FakeText(INDEX_XML)
        return _FakeText(PAGE_URLSET)

    monkeypatch.setattr(wc.requests, "get", _get)
    conn = _make_connector(tmp_path)
    entries = conn._sitemap_entries()

    # 只有 page 子表内容(测试桩简化);/store/ 与 privacy 被排除;无 lastmod 的保留
    assert entries == {
        "https://www.camthink.ai/products/neoeyes-503/": "2026-08-20",
        "https://www.camthink.ai/solutions/security-monitoring/": None,
    }
    # category 子表未被请求(只抓 post/page/product 三类)
    assert not any("category-sitemap" in u for u in fetched)
    # 索引 + 三子表 = 4 次请求(排除发生在 URL 集,不省子表请求)
    assert len([u for u in fetched if u.endswith(".xml")]) == 4


def test_same_domain_links_excludes_wp_json(tmp_path):
    """<head> 里 <link rel=api.w.org href=…/wp-json/> 不作内容页发现(实爬教训)。"""
    conn = _make_connector(tmp_path)
    conn._seen_urls = set()
    html = (
        "<html><head>"
        '<link rel="https://api.w.org/" href="https://www.camthink.ai/wp-json/">'
        "</head><body>"
        '<a href="/product/neoedge-ai-box-ng4500/">NG4500</a>'
        "</body></html>"
    )
    links = conn._same_domain_links(html)
    assert links == ["https://www.camthink.ai/product/neoedge-ai-box-ng4500/"]


class _FakeText:
    def __init__(self, text):
        self.text = text
        self.status_code = 200

    def raise_for_status(self):
        return None


# --------------------------------------------------------------------------- #
# HTML → Markdown 清洗
# --------------------------------------------------------------------------- #


def test_html_to_markdown_strips_noise_and_keeps_body():
    """导航/页脚/脚本/cookie 提示被剥离;正文标题/段落/列表进 Markdown。"""
    html = """
    <html><head><title>NeoEyes 503 | CamThink</title></head>
    <body>
      <nav><a href="/">Home</a><a href="/products">Products</a></nav>
      <div id="cookie-banner">We use cookies to improve your experience.</div>
      <main>
        <h1>NeoEyes 503 Edge AI Camera</h1>
        <p>The NeoEyes 503 (NG4500) delivers 4K vision on-device.</p>
        <ul><li>4K capture</li><li>On-device inference</li></ul>
        <pre><code>demo.run()</code></pre>
      </main>
      <footer><p>Copyright CamThink</p></footer>
      <script>window.dataLayer=[];</script>
    </body></html>
    """
    title, md = html_to_markdown(html)
    assert "NeoEyes 503 Edge AI Camera" in title or "NeoEyes 503" in title
    assert "NG4500" in md
    assert "4K capture" in md
    assert "- " in md  # 列表项
    assert "Cookies" not in md and "cookie" not in md.lower()
    assert "Copyright CamThink" not in md
    assert "dataLayer" not in md
    assert "terminal prompts" not in md


# --------------------------------------------------------------------------- #
# 增量与删除
# --------------------------------------------------------------------------- #


def test_fetch_changes_filters_by_lastmod(tmp_path, monkeypatch):
    """增量:lastmod >= since 抓取;更旧与无 lastmod 的不进增量。"""
    conn = _make_connector(tmp_path)
    since = datetime(2026, 8, 15, tzinfo=UTC)
    monkeypatch.setattr(
        wc.WebCrawlConnector,
        "_sitemap_entries",
        lambda self: {
            "https://www.camthink.ai/a/": "2026-08-20",
            "https://www.camthink.ai/b/": "2026-08-01",  # 早于 since
            "https://www.camthink.ai/c/": None,  # 无 lastmod
        },
    )
    monkeypatch.setattr(conn, "_fetch_page", lambda url: (_fake_doc(url), []))
    urls = [d.url for d in conn.fetch_changes(since)]
    assert urls == ["https://www.camthink.ai/a/"]


def _fake_doc(url: str):
    import hashlib

    from backend.connectors.base import RawDocument

    return RawDocument(
        source_id=url,
        source_type="web_crawl",
        product="website",
        title=url,
        content=url,
        url=url,
        metadata={},
        content_hash=hashlib.sha256(url.encode()).hexdigest(),
    )


def test_fetch_deleted_diffs_state_file(tmp_path, monkeypatch):
    """删除(全量轮):上一轮有、本轮视野消失的 URL → 判删并更新状态。"""
    conn = _make_connector(tmp_path)
    state_path = tmp_path / "crawl-state" / "website-camthink.json"
    monkeypatch.setattr(
        wc.WebCrawlConnector,
        "_sitemap_entries",
        lambda self: {
            "https://www.camthink.ai/keep/": None,
        },
    )
    monkeypatch.setattr(conn, "_state_path", state_path)
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps(["website-camthink/keep", "website-camthink/gone"]))
    # 模拟全量轮视野(含 fetch_all 已置 _last_run_full)
    conn._seen_urls = {"https://www.camthink.ai/keep/"}
    conn._last_run_full = True
    deleted = conn.fetch_deleted(datetime.now(UTC))
    assert deleted == ["website-camthink/gone"]
    # 阶段⑩ W6:fetch_deleted 只报差集,快照在删除效应安全完成后由
    # commit_membership_snapshot 推进(未 commit 前旧快照保留)
    assert json.loads(state_path.read_text()) == ["website-camthink/keep", "website-camthink/gone"]
    conn.commit_membership_snapshot()
    assert json.loads(state_path.read_text()) == ["website-camthink/keep"]


def test_registry_registers_web_crawl() -> None:
    """web_crawl 已注册(ConnectorRegistry 可创建)。"""
    conn = ConnectorRegistry.create(
        SourceConfig(
            id="website-camthink",
            type="web_crawl",
            product="website",
            enabled=True,
            config={"base_url": "https://www.camthink.ai"},
            sync_interval="24h",
        )
    )
    assert conn.source_id == "website-camthink"
    assert conn.product == "website"


# --------------------------------------------------------------------------- #
# WEB 覆盖任务:URL 规范化 / robots / 最小内容 / URL 感知哈希 / 抓取统计
# --------------------------------------------------------------------------- #


def test_canonical_url_normalizes_variants():
    """规范化:去 query/fragment、host 小写、补尾斜杠、压缩 //;外域拒绝。"""
    base = "https://www.camthink.ai"
    f = wc.canonical_url
    assert f(base, "/about?q=1#top") == "https://www.camthink.ai/about/"
    assert f(base, "https://WWW.CAMTHINK.AI/about") == "https://www.camthink.ai/about/"
    assert f(base, "https://www.camthink.ai//a//b/") == "https://www.camthink.ai/a/b/"
    assert f(base, "/") == "https://www.camthink.ai/"
    assert f(base, "https://evil.example.com/a/") is None
    assert f(base, "//resources.camthink.ai/x/") is None


def test_same_content_different_paths_get_distinct_hashes(tmp_path, monkeypatch):
    """内容哈希含 URL 路径:同 md 不同页不得互撞(PG (content_hash,branch) 主键)。"""
    pages = {
        "https://www.camthink.ai/robots.txt": "User-agent: *\nAllow: /",
        "https://www.camthink.ai/sitemap_index.xml": INDEX_XML,
        "https://www.camthink.ai/post-sitemap.xml": URLSET,
        "https://www.camthink.ai/page-sitemap.xml": URLSET,
        "https://www.camthink.ai/product-sitemap.xml": URLSET,
        "https://www.camthink.ai/a/": "<html><body><main><p>"
        + "x" * 300
        + "</p></main></body></html>",
        "https://www.camthink.ai/b/": "<html><body><main><p>"
        + "x" * 300
        + "</p></main></body></html>",
    }
    urlset = """<?xml version="1.0"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://www.camthink.ai/a/</loc></url>
      <url><loc>https://www.camthink.ai/b/</loc></url>
    </urlset>"""
    for k in ("post-sitemap.xml", "page-sitemap.xml", "product-sitemap.xml"):
        pages[f"https://www.camthink.ai/{k}"] = urlset
    _patch_http(monkeypatch, pages)
    conn = _make_connector(tmp_path)
    docs = list(conn.fetch_all())
    by_path = {d.metadata["path"]: d for d in docs}
    assert by_path["a"].content == by_path["b"].content  # 内容相同
    assert by_path["a"].content_hash != by_path["b"].content_hash  # 哈希不同(URL 感知)


def test_min_content_pages_rejected_and_counted(tmp_path, monkeypatch):
    """薄内容页(< 200 字符)不入语料,计入 rejected.low_content(噪声防渗)。"""
    pages = {
        "https://www.camthink.ai/robots.txt": "User-agent: *\nAllow: /",
        "https://www.camthink.ai/sitemap_index.xml": INDEX_XML,
        "https://www.camthink.ai/post-sitemap.xml": URLSET,
        "https://www.camthink.ai/page-sitemap.xml": URLSET,
        "https://www.camthink.ai/product-sitemap.xml": URLSET,
        "https://www.camthink.ai/thin/": "<html><body><p>ok</p></body></html>",
        "https://www.camthink.ai/rich/": "<html><body><main><p>"
        + "y" * 300
        + "</p></main></body></html>",
    }
    urlset = """<?xml version="1.0"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://www.camthink.ai/thin/</loc></url>
      <url><loc>https://www.camthink.ai/rich/</loc></url>
    </urlset>"""
    for k in ("post-sitemap.xml", "page-sitemap.xml", "product-sitemap.xml"):
        pages[f"https://www.camthink.ai/{k}"] = urlset
    _patch_http(monkeypatch, pages)
    conn = _make_connector(tmp_path)
    docs = [d.url for d in conn.fetch_all()]
    assert docs == ["https://www.camthink.ai/rich/"]
    stats = conn.run_stats
    assert stats["rejected"]["low_content"] == 1
    assert stats["extracted"] == 1


def test_robots_disallow_blocks_crawl_and_counts(tmp_path, monkeypatch):
    """robots Disallow 对具名/通配 UA 组生效:被禁 URL 不抓取并计入 rejected.robots。"""
    pages = {
        "https://www.camthink.ai/robots.txt": ("User-agent: *\nDisallow: /private/\nAllow: /"),
        "https://www.camthink.ai/sitemap_index.xml": INDEX_XML,
        "https://www.camthink.ai/post-sitemap.xml": URLSET,
        "https://www.camthink.ai/page-sitemap.xml": URLSET,
        "https://www.camthink.ai/product-sitemap.xml": URLSET,
        "https://www.camthink.ai/rich/": "<html><body><main><p>"
        + "z" * 300
        + "</p></main></body></html>",
    }
    urlset = """<?xml version="1.0"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://www.camthink.ai/private/secret/</loc></url>
      <url><loc>https://www.camthink.ai/rich/</loc></url>
    </urlset>"""
    for k in ("post-sitemap.xml", "page-sitemap.xml", "product-sitemap.xml"):
        pages[f"https://www.camthink.ai/{k}"] = urlset
    requested = _patch_http(monkeypatch, pages)
    conn = _make_connector(tmp_path)
    docs = [d.url for d in conn.fetch_all()]
    assert docs == ["https://www.camthink.ai/rich/"]
    assert not any("/private/" in u for u in requested)
    assert conn.run_stats["rejected"]["robots"] == 1


def test_run_stats_reports_failures_without_breaking_crawl(tmp_path, monkeypatch):
    """单页失败计入 run_stats.failed(+URL),不中断其余页面(可观测,不吞没)。"""
    pages = {
        "https://www.camthink.ai/robots.txt": "User-agent: *\nAllow: /",
        "https://www.camthink.ai/sitemap_index.xml": INDEX_XML,
        "https://www.camthink.ai/post-sitemap.xml": URLSET,
        "https://www.camthink.ai/page-sitemap.xml": URLSET,
        "https://www.camthink.ai/product-sitemap.xml": URLSET,
        "https://www.camthink.ai/rich/": "<html><body><main><p>"
        + "w" * 300
        + "</p></main></body></html>",
    }
    # 仅 products 页(会失败)与 rich 页入表,避免 URLSET 其余无页面 URL 干扰
    urlset = """<?xml version="1.0"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://www.camthink.ai/products/neoeyes-503/</loc></url>
      <url><loc>https://www.camthink.ai/rich/</loc></url>
    </urlset>"""
    for k in ("post-sitemap.xml", "page-sitemap.xml", "product-sitemap.xml"):
        pages[f"https://www.camthink.ai/{k}"] = urlset
    real_get = None

    def _get(url, **kwargs):
        if url.endswith("/products/neoeyes-503/"):
            raise wc.requests.ConnectionError("boom")
        return _patch_http_get(pages)(url, **kwargs)

    real_get = _get
    monkeypatch.setattr(wc.requests, "get", _get)
    conn = _make_connector(tmp_path)
    docs = [d.url for d in conn.fetch_all()]
    assert docs == ["https://www.camthink.ai/rich/"]
    assert conn.run_stats["failed"] == 1
    assert any("products/neoeyes-503" in u for u in conn.run_stats["failed_urls"])
    assert conn.run_stats["extracted"] == 1


def _patch_http_get(pages: dict):
    class _Resp:
        status_code = 200

        @property
        def text(self):
            return pages[_current[0]]

        def raise_for_status(self):
            return None

    _current = [None]

    def _get(url, **kwargs):
        _current[0] = url
        return _Resp()

    return _get


def test_fetch_deleted_only_after_full_crawl(tmp_path, monkeypatch):
    """增量轮不删文档(BFS 发现页不因 sitemap 缺失被误删);全量轮才做差集删除。"""
    conn = _make_connector(tmp_path)
    state_path = tmp_path / "crawl-state" / "website-camthink.json"
    monkeypatch.setattr(
        wc.WebCrawlConnector,
        "_sitemap_entries",
        lambda self: {
            "https://www.camthink.ai/keep/": None,
        },
    )
    monkeypatch.setattr(conn, "_state_path", state_path)
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps(["website-camthink/keep", "website-camthink/gone"]))

    # 增量轮:不做删除、不覆写状态
    assert conn.fetch_deleted(datetime.now(UTC)) == []
    assert json.loads(state_path.read_text()) == ["website-camthink/keep", "website-camthink/gone"]

    # 全量轮:差集删除候选生效;快照仍待删除效应完成后推进(阶段⑩ W6)
    conn._seen_urls = {"https://www.camthink.ai/keep/"}
    conn._last_run_full = True
    assert conn.fetch_deleted(datetime.now(UTC)) == ["website-camthink/gone"]
    assert json.loads(state_path.read_text()) == ["website-camthink/keep", "website-camthink/gone"]
    conn.commit_membership_snapshot()
    assert json.loads(state_path.read_text()) == ["website-camthink/keep"]


def test_sitemap_entries_canonicalizes_and_dedupes(tmp_path, monkeypatch):
    """sitemap URL 规范化:大小写 host/无尾斜杠变体与规范形态合并去重。"""
    urlset = """<?xml version="1.0"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://www.camthink.ai/about</loc></url>
      <url><loc>https://WWW.camthink.ai/about/</loc></url>
    </urlset>"""

    def _get(url, **kwargs):
        if url.endswith("sitemap_index.xml"):
            return _FakeText(INDEX_XML)
        return _FakeText(urlset)

    monkeypatch.setattr(wc.requests, "get", _get)
    conn = _make_connector(tmp_path)
    entries = conn._sitemap_entries()
    assert entries == {"https://www.camthink.ai/about/": None}


def test_excluded_links_counted_once_across_pages(tmp_path, monkeypatch):
    """G005 计数语义:导航里反复出现的排除链接只计一次;已见链接不重复计数。"""
    nav = '<a href="/store/x/">Store</a><a href="/rich/">Rich</a>'
    page_html = f"<html><body><main><p>{'q' * 300}</p>{nav}</main></body></html>"
    urlset = """<?xml version="1.0"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://www.camthink.ai/rich/</loc></url>
    </urlset>"""
    pages = {
        "https://www.camthink.ai/robots.txt": "User-agent: *\nAllow: /",
        "https://www.camthink.ai/sitemap_index.xml": INDEX_XML,
        "https://www.camthink.ai/post-sitemap.xml": urlset,
        "https://www.camthink.ai/page-sitemap.xml": urlset,
        "https://www.camthink.ai/product-sitemap.xml": urlset,
        "https://www.camthink.ai/rich/": page_html,
    }
    _patch_http(monkeypatch, pages)
    conn = _make_connector(tmp_path)
    docs = list(conn.fetch_all())
    assert [d.url for d in docs] == ["https://www.camthink.ai/rich/"]
    # /store/x/ 被 sitemap 阶段与页面链接发现各遇一次,但 unique 计数 = 1
    assert conn.run_stats["rejected"]["exclude"] == 1


# --------------------------------------------------------------------------- #
# P1 退休安全:权威成员集(accepted)与抽取成功分离
# --------------------------------------------------------------------------- #


def test_authoritative_source_ids_include_failed_and_rejected_pages(tmp_path, monkeypatch):
    """accepted(成员)先于抓取记账:抓取失败/薄内容被拒页仍在权威成员集;
    增量轮返回 None。 retiring 决策据此与抽取成功分离(Planner 修正)。"""
    connector = _make_connector(tmp_path)  # 默认 min_content:thin 页判薄被拒
    urlset = """<?xml version="1.0"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.camthink.ai/products/neoeyes-503/</loc></url>
  <url><loc>https://www.camthink.ai/page-fetch-fail/</loc></url>
  <url><loc>https://www.camthink.ai/page-thin/</loc></url>
</urlset>"""
    monkeypatch.setattr(
        connector,
        "_sitemap_entries",
        lambda: {
            "https://www.camthink.ai/products/neoeyes-503/": None,
            "https://www.camthink.ai/page-fetch-fail/": None,
            "https://www.camthink.ai/page-thin/": None,
        },
    )
    pages = {
        "https://www.camthink.ai/products/neoeyes-503/": "<html><body>"
        + "rich " * 400
        + "</body></html>",
        # page-fetch-fail:故意缺席 → _fetch_page RuntimeError
        "https://www.camthink.ai/page-thin/": "<html><body>thin</body></html>",
    }

    def _fake_get(url, **kw):
        class _Resp:
            status_code = 200

            def __init__(self, text):
                self.text = text

            def raise_for_status(self):
                pass

        if "robots.txt" in url:
            return _Resp("User-agent: *\nAllow: /")
        if "page-fetch-fail" in url:
            raise RuntimeError("boom")  # 模拟单页 HTTP/超时失败
        return _Resp(pages[url])

    monkeypatch.setattr(wc.requests, "get", _fake_get)

    docs = list(connector.fetch_all())
    assert [d.source_id for d in docs] == ["website-camthink/products/neoeyes-503"]

    membership = connector.authoritative_source_ids()
    assert membership is not None
    # 抓取失败页与薄内容页都仍是权威源成员(成员资格 ≠ 抽取成功)
    assert "website-camthink/page-fetch-fail" in membership
    assert "website-camthink/page-thin" in membership
    assert "website-camthink/products/neoeyes-503" in membership


def test_authoritative_source_ids_none_on_incremental_round(tmp_path, monkeypatch):
    """增量轮(fetch_changes)无权威成员集证据 → 返回 None。"""
    connector = _make_connector(tmp_path)
    assert connector.authoritative_source_ids() is None
