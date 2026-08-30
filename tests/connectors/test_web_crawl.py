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
        wc.WebCrawlConnector, "_sitemap_entries", lambda self: {
            "https://www.camthink.ai/a/": "2026-08-20",
            "https://www.camthink.ai/b/": "2026-08-01",  # 早于 since
            "https://www.camthink.ai/c/": None,  # 无 lastmod
        }
    )
    monkeypatch.setattr(
        conn, "_fetch_page", lambda url: (_fake_doc(url), [])
    )
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
    """删除:上一轮有、本轮 sitemap 消失的 URL → fetch_deleted 返回并更新状态。"""
    conn = _make_connector(tmp_path)
    state_path = tmp_path / "crawl-state" / "website-camthink.json"
    monkeypatch.setattr(
        wc.WebCrawlConnector, "_sitemap_entries", lambda self: {
            "https://www.camthink.ai/keep/": None,
        }
    )
    monkeypatch.setattr(conn, "_state_path", state_path)
    # 上一轮状态文件里有 keep 与 gone 两个;本轮只剩 keep → gone 被判删
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        json.dumps(
            [
                "website-camthink/keep",
                "website-camthink/gone",
            ]
        )
    )
    # 状态文件路径随 CWD(tmp_path)解析
    deleted = conn.fetch_deleted(datetime.now(UTC))
    assert deleted == ["website-camthink/gone"]
    # 状态已更新为当前集合
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
