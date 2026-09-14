"""RAGOrchestrator 引用 URL canonical 化集成测试(CIT-URL Contract)。

覆盖 sources 产出(LLM context / SSE sources 事件 / 同步 answer)对
Wiki canonical URL 的呈现,以及 GitHub provenance 的保留。
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.llm.base import LLMResponse
from backend.pipeline.rag import RAGOrchestrator
from backend.retrieval.search import SearchResult

WIKI_BLOB = "https://github.com/camthink-ai/wiki-documents/blob/main"
WIKI_CANONICAL_OVERVIEW = "https://wiki.camthink.ai/docs/neoeyes-ne301-series/overview"
NE503_SDK_BLOB = f"{WIKI_BLOB}/docs/6-neoeyes-ne503-series/3-sdk/reference.md"
NE503_RESOURCES_BLOB = (
    f"{WIKI_BLOB}/docs/6-neoeyes-ne503-series/4-application-guide/3-resources.md"
)


def _make_llm_response(content: str = "answer") -> LLMResponse:
    return LLMResponse(
        content=content,
        model="test-model",
        tokens_input=10,
        tokens_output=5,
        latency_ms=50,
    )


def _build_orchestrator(reranked: list[SearchResult]):
    """构造最小编排器:searcher/reranker 返回 reranked,LLM 返回固定答案。"""
    searcher = MagicMock()
    searcher.search.return_value = reranked
    reranker = MagicMock()
    reranker.rerank.return_value = reranked
    reranker.rerank_scored.return_value = (reranked, [])
    reranker.rerank_scored.return_value = (reranked, [])
    llm = AsyncMock()
    llm.generate.return_value = _make_llm_response()

    async def _stream(*_args, **_kwargs):
        yield "answer"

    # 生产 llm.stream 是普通方法(调用即返回 async 生成器,非协程),
    # 故用普通函数注入,不能用 AsyncMock(其 __call__ 会先返回协程)。
    llm.stream = lambda *a, **k: _stream()
    rag = RAGOrchestrator(
        searcher=searcher,
        reranker=reranker,
        llm=llm,
        system_prompt="You are helpful.",
        min_results_to_answer=1,
    )
    return rag, llm


@pytest.mark.unit
async def test_wiki_citation_uses_canonical_url_with_github_provenance():
    """G001+G006:Wiki chunk citation → canonical URL,原 GitHub URL 保留为 provenance。"""
    sr = SearchResult(
        text="NE301 概述",
        source_id="wiki/main/docs/5-neoeyes-ne301-series/0-overview.md",
        source_type="github",
        product="ne301",
        title="0-overview",
        url=f"{WIKI_BLOB}/docs/5-neoeyes-ne301-series/0-overview.md",
        score=0.9,
        chunk_index=0,
        frontmatter_slug="/neoeyes-ne301-series/overview",
    )
    rag, _ = _build_orchestrator([sr])
    result = await rag.answer("NE301 是什么", "widget")

    assert len(result.sources) == 1
    src = result.sources[0]
    assert src["url"] == WIKI_CANONICAL_OVERVIEW
    assert src["provenance_url"] == f"{WIKI_BLOB}/docs/5-neoeyes-ne301-series/0-overview.md"
    assert src["type"] == "github"


@pytest.mark.unit
async def test_wiki_citation_prefers_frontmatter_slug_authority():
    sr = SearchResult(
        text="NE503 SDK reference",
        source_id="wiki/main/docs/6-neoeyes-ne503-series/3-sdk/reference.md",
        source_type="github",
        product="ne503",
        title="SDK reference",
        url=f"{WIKI_BLOB}/docs/6-neoeyes-ne503-series/3-sdk/reference.md",
        score=0.9,
        chunk_index=0,
        frontmatter_slug="/neoeyes-ne503-series/sdk/reference",
    )
    rag, _ = _build_orchestrator([sr])
    result = await rag.answer("SDK reference", "widget")

    assert result.sources[0]["url"] == (
        "https://wiki.camthink.ai/docs/neoeyes-ne503-series/sdk/reference"
    )
    assert result.sources[0]["provenance_url"] == sr.url


@pytest.mark.unit
async def test_normal_github_citation_unchanged_no_provenance_key():
    """G002:普通 GitHub citation 仍为 GitHub URL,零回归(无 provenance 键)。"""
    github_url = "https://github.com/camthink-ai/lowpower_camera/blob/main/README.md"
    sr = SearchResult(
        text="摄像头 README",
        source_id="gh/main/README.md",
        source_type="github",
        product="ne101",
        title="README",
        url=github_url,
        score=0.9,
        chunk_index=0,
    )
    rag, _ = _build_orchestrator([sr])
    result = await rag.answer("lowpower_camera 是什么", "widget")

    assert result.sources[0]["url"] == github_url
    assert "provenance_url" not in result.sources[0]


@pytest.mark.unit
async def test_website_citation_unchanged():
    """G005:Website(web_crawl)citation 行为不变。"""
    site_url = "https://www.camthink.ai/products/ne301"
    sr = SearchResult(
        text="NE301 产品页",
        source_id="webcrawl/1",
        source_type="web_crawl",
        product="ne301",
        title="NE301",
        url=site_url,
        score=0.9,
        chunk_index=0,
    )
    rag, _ = _build_orchestrator([sr])
    result = await rag.answer("NE301 页面", "widget")

    assert result.sources[0]["url"] == site_url
    assert "provenance_url" not in result.sources[0]


@pytest.mark.unit
async def test_woocommerce_citation_unchanged():
    """G005:WooCommerce citation 行为不变。"""
    store_url = "https://shop.example.com/products/ne301"
    sr = SearchResult(
        text="NE301 产品商品",
        source_id="woocommerce/1",
        source_type="woocommerce",
        product="ne301",
        title="NE301",
        url=store_url,
        score=0.9,
        chunk_index=0,
    )
    rag, _ = _build_orchestrator([sr])
    result = await rag.answer("NE301 商品", "widget")

    assert result.sources[0]["url"] == store_url
    assert "provenance_url" not in result.sources[0]


@pytest.mark.unit
async def test_wiki_translation_chunks_dedup_to_single_canonical_source():
    """G003:同一 Wiki 文档的中文与 i18n 翻译 chunk → 去重为单条 canonical source。"""
    zh = SearchResult(
        text="概述中文",
        source_id="wiki/main/docs/5-neoeyes-ne301-series/0-overview.md",
        source_type="github",
        product="ne301",
        title="0-overview",
        url=f"{WIKI_BLOB}/docs/5-neoeyes-ne301-series/0-overview.md",
        score=0.9,
        chunk_index=0,
        frontmatter_slug="/neoeyes-ne301-series/overview",
    )
    en = SearchResult(
        text="overview en",
        source_id="wiki/main/i18n/en/docusaurus-plugin-content-docs/current/"
        "5-neoeyes-ne301-series/0-overview.md",
        source_type="github",
        product="ne301",
        title="0-overview",
        url=f"{WIKI_BLOB}/i18n/en/docusaurus-plugin-content-docs/current/"
        "5-neoeyes-ne301-series/0-overview.md",
        score=0.8,
        chunk_index=0,
        frontmatter_slug="/neoeyes-ne301-series/overview",
    )
    rag, _ = _build_orchestrator([zh, en])
    result = await rag.answer("NE301 overview", "widget")

    assert len(result.sources) == 1
    assert result.sources[0]["url"] == WIKI_CANONICAL_OVERVIEW


@pytest.mark.unit
async def test_llm_context_carries_canonical_url():
    """LLM 上下文中的 URL 行呈现 canonical URL,避免模型把 blob URL 抄进答案。"""
    sr = SearchResult(
        text="NE301 概述",
        source_id="wiki/main/docs/5-neoeyes-ne301-series/0-overview.md",
        source_type="github",
        product="ne301",
        title="0-overview",
        url=f"{WIKI_BLOB}/docs/5-neoeyes-ne301-series/0-overview.md",
        score=0.9,
        chunk_index=0,
        frontmatter_slug="/neoeyes-ne301-series/overview",
    )
    rag, llm = _build_orchestrator([sr])
    await rag.answer("NE301 是什么", "widget")

    messages = llm.generate.call_args[0][0]
    context_text = messages[-1]["content"]
    assert WIKI_CANONICAL_OVERVIEW in context_text
    assert WIKI_BLOB not in context_text


@pytest.mark.unit
async def test_stream_sources_event_uses_canonical_url_with_provenance():
    """流式路径 parity:sources 事件同样 canonical + provenance。"""
    sr = SearchResult(
        text="NE301 概述",
        source_id="wiki/main/docs/5-neoeyes-ne301-series/0-overview.md",
        source_type="github",
        product="ne301",
        title="0-overview",
        url=f"{WIKI_BLOB}/docs/5-neoeyes-ne301-series/0-overview.md",
        score=0.9,
        chunk_index=0,
        frontmatter_slug="/neoeyes-ne301-series/overview",
    )
    rag, _ = _build_orchestrator([sr])

    events = [json.loads(evt) async for evt in rag.stream_answer("NE301 是什么", "widget")]
    sources_event = next(e for e in events if e["type"] == "sources")
    assert sources_event["sources"][0]["url"] == WIKI_CANONICAL_OVERVIEW
    assert (
        sources_event["sources"][0]["provenance_url"]
        == f"{WIKI_BLOB}/docs/5-neoeyes-ne301-series/0-overview.md"
    )


@pytest.mark.unit
@pytest.mark.parametrize("channel", ["widget", "admin"])
async def test_legacy_ne503_sdk_resources_keep_blob_destination_in_answer_and_stream(channel):
    """#64:存量无 slug 对话与流式都不得发出猜测的 Wiki URL。"""
    results = [
        SearchResult(
            text="NE503 SDK reference",
            source_id="wiki/main/docs/6-neoeyes-ne503-series/3-sdk/reference.md",
            source_type="github",
            product="ne503",
            title="SDK reference",
            url=NE503_SDK_BLOB,
            score=0.9,
            chunk_index=0,
        ),
        SearchResult(
            text="NE503 resources",
            source_id="wiki/main/docs/6-neoeyes-ne503-series/4-application-guide/3-resources.md",
            source_type="github",
            product="ne503",
            title="resources",
            url=NE503_RESOURCES_BLOB,
            score=0.8,
            chunk_index=0,
        ),
    ]
    rag, _ = _build_orchestrator(results)

    answer = await rag.answer("NE503 SDK resources", channel)
    stream_events = [json.loads(evt) async for evt in rag.stream_answer("NE503 SDK resources", channel)]
    streamed = next(event for event in stream_events if event["type"] == "sources")

    expected = [NE503_SDK_BLOB, NE503_RESOURCES_BLOB]
    assert [source["url"] for source in answer.sources] == expected
    assert [source["url"] for source in streamed["sources"]] == expected
    assert all(source["url"] and source["url"].startswith("https://github.com/") for source in answer.sources)
    assert all("https://wiki.camthink.ai/" not in source["url"] for source in answer.sources)


@pytest.mark.unit
@pytest.mark.parametrize("url", ["", "https://", "not-a-url"])
def test_public_source_with_empty_or_fake_url_is_not_rendered_as_clickable(url):
    """CIT-URL:空或伪 URL 不得进入访客可点击 sources。"""
    source = SearchResult(
        text="unknown",
        source_id="wiki/main/unknown.md",
        source_type="github",
        product="ne503",
        title="unknown",
        url=url,
        score=0.9,
        chunk_index=0,
    )
    rag, _ = _build_orchestrator([])

    assert rag._extract_sources([source]) == []
