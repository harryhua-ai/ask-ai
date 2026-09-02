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
    )
    rag, _ = _build_orchestrator([sr])
    result = await rag.answer("NE301 是什么", "widget")

    assert len(result.sources) == 1
    src = result.sources[0]
    assert src["url"] == WIKI_CANONICAL_OVERVIEW
    assert src["provenance_url"] == f"{WIKI_BLOB}/docs/5-neoeyes-ne301-series/0-overview.md"
    assert src["type"] == "github"


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
    )
    rag, _ = _build_orchestrator([sr])

    events = [json.loads(evt) async for evt in rag.stream_answer("NE301 是什么", "widget")]
    sources_event = next(e for e in events if e["type"] == "sources")
    assert sources_event["sources"][0]["url"] == WIKI_CANONICAL_OVERVIEW
    assert (
        sources_event["sources"][0]["provenance_url"]
        == f"{WIKI_BLOB}/docs/5-neoeyes-ne301-series/0-overview.md"
    )
