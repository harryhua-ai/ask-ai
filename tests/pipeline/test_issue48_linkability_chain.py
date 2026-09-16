"""Issue #48 / Track C C-7 — 跨源链路回归套件(stored URL → API citation JSON)。

冻结契约(docs/v164-iteration-contracts-20260913 §1 C-7):对每个可链接
来源类型,自动断言链路「存储 URL → API citation JSON(link_state)」;
非可点击类同时断言无 href 形态的 API 输出。渲染侧
「API citation JSON → rendered href(含 <a> 缺席断言)」由 widget vitest
``issue48BadgeLinkabilityGuard.test.ts`` 的同名 chain fixtures 承接 ——
两侧 fixture 逐字同源,合并即为 C-7 要求的端到端链路套件。

状态词表(Track C C-3,与 rag._derive_link_state / widget LinkState 对齐):
external(可点击 canonical)/ none(无外部目的地)/ private(非公开)/
stale(可能已移动/失效)。
"""

import pytest

from backend.pipeline.citation import PUBLIC_SOURCE_TYPES
from backend.pipeline.rag import RAGOrchestrator
from backend.retrieval.search import SearchResult

WIKI_BLOB = "https://github.com/camthink-ai/wiki-documents/blob/main"


def _sr(
    url: str,
    title: str,
    source_type: str = "github",
    *,
    visitor_reachability: str = "unknown",
    frontmatter_slug: str | None = None,
    product: str = "ne503",
    source_id: str | None = None,
    channel_visibility: tuple[str, ...] = ("widget", "api"),
) -> SearchResult:
    return SearchResult(
        text="chunk text",
        source_id=source_id or f"src/{title}",
        source_type=source_type,
        product=product,
        title=title,
        url=url,
        score=0.9,
        chunk_index=0,
        channel_visibility=channel_visibility,
        frontmatter_slug=frontmatter_slug,
        visitor_reachability=visitor_reachability,
    )


def _extract(results):
    orchestrator = RAGOrchestrator.__new__(RAGOrchestrator)
    return orchestrator._extract_sources(results)


def _single(results):
    sources = _extract(results)
    assert len(sources) == 1, f"expected exactly one serialized source, got {sources}"
    return sources[0]


# --------------------------------------------------------------------------- #
# (a) external:可点击 canonical 链接类
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_chain_github_public_repo_blob_keeps_canonical_url_external():
    """C-4/acceptance 3:公开仓库 blob URL 原样保留,identity 不改写。"""
    url = "https://github.com/camthink-ai/neoruntime/blob/main/docker/dev/build.sh"
    src = _single([_sr(url, "build", visitor_reachability="public")])
    assert src["url"] == url
    assert src["link_state"] == "external"
    assert src["type"] == "github"
    assert src["title"] == "build"


@pytest.mark.unit
def test_chain_github_legacy_unknown_reachability_preserves_clickable_semantics():
    """零回填约束:存量对象(unknown)保持既有可点击语义,不推断 private。"""
    url = "https://github.com/camthink-ai/neoruntime/blob/main/README.md"
    src = _single([_sr(url, "README")])
    assert src["url"] == url
    assert src["link_state"] == "external"


@pytest.mark.unit
def test_chain_wiki_slug_authority_maps_to_canonical_external():
    """C-6:wiki canonical 映射保留;slug 权威映射结果 = external 可点击。"""
    blob = f"{WIKI_BLOB}/docs/5-neoeyes-ne301-series/0-overview.md"
    src = _single(
        [
            _sr(
                blob,
                "0-overview",
                frontmatter_slug="/neoeyes-ne301-series/overview",
            )
        ]
    )
    assert src["url"] == "https://wiki.camthink.ai/docs/neoeyes-ne301-series/overview"
    assert src["provenance_url"] == blob
    assert src["link_state"] == "external"


@pytest.mark.unit
def test_chain_website_and_web_crawl_and_woocommerce_are_external():
    """非 GitHub 链接类不受状态推导影响(全部 external 可点击)。"""
    for source_type, url in [
        ("website", "https://docs.camthink.ai/guide"),
        ("web_crawl", "https://www.camthink.ai/blog/post"),
        ("woocommerce", "https://www.camthink.ai/product/ne503"),
    ]:
        src = _single([_sr(url, source_type, source_type=source_type)])
        assert src["url"] == url, source_type
        assert src["link_state"] == "external", source_type


# --------------------------------------------------------------------------- #
# (c) private:非公开仓库 —— 不伪造公开可导航(identity 字段保留)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_chain_github_private_repo_keeps_identity_but_state_private():
    """C-4/acceptance 3:私库 URL 保留(identity),状态 private 禁点击。"""
    url = "https://github.com/camthink-ai/some-private-repo/blob/main/docs/x.md"
    src = _single([_sr(url, "private-doc", visitor_reachability="private")])
    assert src["url"] == url
    assert src["link_state"] == "private"


# --------------------------------------------------------------------------- #
# (d) stale:存量 wiki blob 回退(branch-ref 404 窗口,生产实证类)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_chain_wiki_legacy_blob_fallback_is_stale():
    """C-4:缺 slug 权威的存量 wiki blob = 可能已移动/失效 → stale。"""
    url = (
        f"{WIKI_BLOB}/docs/6-neoeyes-ne503-series/4-application-guide/"
        "1-app-development/reference/2-sdk-reference.md"
    )
    src = _single([_sr(url, "2-sdk-reference")])
    assert src["url"] == url  # 存储真值不改写
    assert src["link_state"] == "stale"


@pytest.mark.unit
def test_chain_wiki_malformed_slug_blob_fallback_is_stale():
    """slug 存在但不安全 → 映射被拒回退 blob → 同属 stale 类。"""
    url = f"{WIKI_BLOB}/docs/x/y.md"
    src = _single([_sr(url, "y", frontmatter_slug="not-absolute")])
    assert src["url"] == url
    assert src["link_state"] == "stale"


# --------------------------------------------------------------------------- #
# (b) none + C-5 关闭:无外部目的地 / 非公开链接类
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_chain_knowledge_case_url_blank_with_explicit_none_state():
    """C-3/acceptance 2:url="" 置空路径以显式 none 状态表达非可点击。"""
    src = _single(
        [
            _sr(
                "",
                "knowledge-case-a",
                source_type="filesystem",
                product="knowledge",
                source_id="kc/knowledge-case-a",
            )
        ]
    )
    assert src["url"] == ""
    assert src["link_state"] == "none"
    assert src["source_id"] == "kc/knowledge-case-a"


@pytest.mark.unit
def test_chain_woocommerce_empty_permalink_never_reaches_api_sources():
    """acceptance 4:woo 空 permalink(伪 URL)不进入 API sources。"""
    sources = _extract([_sr("", "broken-product", source_type="woocommerce")])
    assert sources == []


@pytest.mark.unit
def test_chain_local_git_closed_out_of_public_sources():
    """C-5:local_git(file://)不再是公开展示类 —— 不进可见 sources。"""
    assert "local_git" not in PUBLIC_SOURCE_TYPES
    sources = _extract(
        [_sr("file:///repo/docs/x.md", "local-git", source_type="local_git")]
    )
    assert sources == []


# --------------------------------------------------------------------------- #
# 状态词表封闭性(C-3:序列化只产出冻结四态)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_chain_serialized_link_states_are_within_frozen_vocabulary():
    """任意混合输入序列化后,link_state ∈ {external, none, private, stale}。"""
    results = [
        _sr("https://github.com/camthink-ai/neoruntime/blob/main/docker/dev/build.sh", "build", visitor_reachability="public"),
        _sr("https://github.com/camthink-ai/priv/blob/main/a.md", "priv", visitor_reachability="private"),
        _sr(f"{WIKI_BLOB}/docs/moved.md", "moved"),
        _sr("https://www.camthink.ai/product/ne503", "ne503", source_type="woocommerce"),
        _sr("", "kc", source_type="filesystem", product="knowledge", source_id="kc/kc"),
        _sr("file:///x.md", "lg", source_type="local_git"),
        _sr("", "woo-broken", source_type="woocommerce"),
    ]
    states = {s["link_state"] for s in _extract(results)}
    assert states == {"external", "private", "stale", "none"}
