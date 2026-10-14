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


def _build_orchestrator(
    reranked: list[SearchResult],
    *,
    answer: str = "answer",
    visibility_guard=None,
):
    """构造最小编排器:searcher/reranker 返回 reranked,LLM 返回固定答案。"""
    searcher = MagicMock()
    searcher.search.return_value = reranked
    reranker = MagicMock()
    reranker.rerank.return_value = reranked
    reranker.rerank_scored.return_value = (reranked, [])
    if visibility_guard is not None:
        # Preserve request-local metadata attached by the visibility guard.
        reranker.rerank_scored.side_effect = lambda _query, results, **_kwargs: (results, [])
    llm = AsyncMock()

    async def _generate(messages, task=None, **_kwargs):
        if task == "task_understanding":
            prompt = messages[-1]["content"]
            query = prompt.rsplit("## 用户输入\n", 1)[-1].strip()
            structured = {
                "category": "product",
                "reason": "test fixture",
                "confidence": 0.9,
                "interaction_mode": "standard",
                "evidence_intent": "factual",
                "extracted_query": query,
                "rewritten_query": query,
            }
            return _make_llm_response(json.dumps(structured, ensure_ascii=False))
        return _make_llm_response(answer)

    llm.generate.side_effect = _generate
    llm.describe_chain = MagicMock(return_value=None)

    async def _stream(*_args, **_kwargs):
        yield answer

    # 生产 llm.stream 是普通方法(调用即返回 async 生成器,非协程),
    # 故用普通函数注入,不能用 AsyncMock(其 __call__ 会先返回协程)。
    llm.stream = lambda *a, **k: _stream()
    rag = RAGOrchestrator(
        searcher=searcher,
        reranker=reranker,
        llm=llm,
        system_prompt="You are helpful.",
        min_results_to_answer=1,
        visibility_guard=visibility_guard,
    )
    return rag, llm


def _upload_aware_visibility_guard(results: list[SearchResult]):
    """Build the real guard from authoritative source-type/config fixtures."""
    from backend.services.source_visibility import SourceVisibilityGuard, policy_for_source

    policies = {}
    for result in results:
        source_prefix = result.source_id.split("/", 1)[0]
        config = (
            {"upload_mode": True, "channel_visibility": ["widget"]}
            if source_prefix.startswith("upload-")
            else {}
        )
        # The source row is authoritative; chunk source_type may be historical.
        source_type = "filesystem" if source_prefix.startswith("upload-") else result.source_type
        policies[source_prefix] = policy_for_source(source_type, config)

    async def load_policies():
        return policies

    return SourceVisibilityGuard(load_policies, ttl=60)


@pytest.mark.unit
async def test_upload_only_knowledge_stays_in_generation_context_without_visitor_source():
    upload = SearchResult(
        text="上传资料说明设备需要 12 V 电源。",
        source_id="upload-support/internal-guide.md",
        source_type="filesystem",
        product="knowledge",
        title="不可公开的内部文件名",
        url="",
        score=0.9,
        chunk_index=0,
    )
    rag, llm = _build_orchestrator(
        [upload],
        answer="设备需要 12 V 电源 [1]。",
        visibility_guard=_upload_aware_visibility_guard([upload]),
    )

    result = await rag.answer("设备需要什么电源", "widget")
    events = [json.loads(event) async for event in rag.stream_answer("设备需要什么电源", "widget")]
    source_event = next(event for event in events if event["type"] == "sources")
    complete_event = next(event for event in events if event["type"] == "complete")

    assert result.sources == []
    assert "[1]" not in result.answer
    assert source_event["sources"] == result.sources
    assert complete_event["sources"] == result.sources
    assert complete_event["answer"] == result.answer
    generation_messages = next(
        call.args[0]
        for call in reversed(llm.generate.call_args_list)
        if call.kwargs.get("task") == "generation"
    )
    prompt = str(generation_messages)
    assert "设备需要 12 V 电源" in prompt
    assert "后台上传资料" in prompt
    assert "后台上传资料」可以支持回答" in prompt
    assert (
        "## 后台上传资料(可用于回答;仅由此处支持的事实不得标注 [N] 或归因于可引用资料)"
        in prompt
    )
    citable_context, upload_context = prompt.split("## 后台上传资料", 1)
    assert "(无可引用资料)" in citable_context
    assert "设备需要 12 V 电源" not in citable_context
    assert "设备需要 12 V 电源" in upload_context
    assert "不可公开的内部文件名" not in prompt
    assert "upload-support/internal-guide.md" not in prompt
    assert "/srv/private/internal-guide.md" not in prompt


@pytest.mark.unit
async def test_mixed_upload_and_public_sources_share_contiguous_visible_citations_in_sync_and_stream():
    upload = SearchResult(
        text="仅上传资料支持：安装前检查现场空间。",
        source_id="upload-support/internal-guide.md",
        # Stale chunk metadata must not override authoritative DataSource type.
        source_type="github",
        product="knowledge",
        title="内部安装指南",
        # Simulate stale historical URL metadata colliding with a public page.
        url="https://github.com/camthink-ai/wiki/blob/main/docs/ne301/power.md",
        score=0.95,
        chunk_index=0,
    )
    public = SearchResult(
        text="公开 Wiki 说明设备工作电压为 24 V。",
        source_id="wiki/main/docs/ne301/power.md",
        source_type="github",
        product="ne301",
        title="NE301 供电说明",
        url="https://github.com/camthink-ai/wiki/blob/main/docs/ne301/power.md",
        score=0.8,
        chunk_index=0,
    )
    public_second = SearchResult(
        text="公开 Wiki 说明外壳防护等级为 IP65。",
        source_id="wiki/main/docs/ne301/enclosure.md",
        source_type="github",
        product="ne301",
        title="NE301 防护等级",
        url="https://github.com/camthink-ai/wiki/blob/main/docs/ne301/enclosure.md",
        score=0.75,
        chunk_index=0,
    )
    answer = (
        "公开 Wiki 说明工作电压为 24 V [1]。\n"
        "安装前还应检查现场空间 [3]。\n"
        "公开 Wiki 说明外壳防护等级为 IP65 [2]。"
    )
    rag, llm = _build_orchestrator(
        [upload, public, public_second],
        answer=answer,
        visibility_guard=_upload_aware_visibility_guard([upload, public, public_second]),
    )

    result = await rag.answer("供电和安装准备", "widget")
    events = [json.loads(event) async for event in rag.stream_answer("供电和安装准备", "widget")]
    source_event = next(event for event in events if event["type"] == "sources")
    complete_event = next(event for event in events if event["type"] == "complete")

    assert [source["title"] for source in result.sources] == ["NE301 供电说明", "NE301 防护等级"]
    assert "24 V [1]" in result.answer
    assert "IP65 [2]" in result.answer
    assert "[3]" not in result.answer
    assert source_event["sources"] == result.sources
    assert complete_event["sources"] == result.sources
    assert complete_event["answer"] == result.answer
    generation_messages = next(
        call.args[0]
        for call in reversed(llm.generate.call_args_list)
        if call.kwargs.get("task") == "generation"
    )
    prompt = str(generation_messages)
    assert "[1] [GitHub] NE301 供电说明" in prompt
    assert "[2] [GitHub] NE301 防护等级" in prompt
    assert "仅上传资料支持：安装前检查现场空间。" in prompt
    citable_context, upload_context = prompt.split("## 后台上传资料", 1)
    assert "仅上传资料支持：安装前检查现场空间。" not in citable_context
    assert "仅上传资料支持：安装前检查现场空间。" in upload_context
    assert "内部安装指南" not in prompt
    assert "upload-support/internal-guide.md" not in prompt


@pytest.mark.unit
async def test_public_only_citation_keeps_original_numbering_and_link():
    public = SearchResult(
        text="公开 Wiki 说明设备工作电压为 24 V。",
        source_id="wiki/main/docs/ne301/power.md",
        source_type="github",
        product="ne301",
        title="NE301 供电说明",
        url="https://github.com/camthink-ai/wiki/blob/main/docs/ne301/power.md",
        score=0.8,
        chunk_index=0,
    )
    rag, _ = _build_orchestrator([public], answer="设备工作电压为 24 V [1]。")

    result = await rag.answer("NE301 电压", "widget")
    events = [json.loads(event) async for event in rag.stream_answer("NE301 电压", "widget")]
    source_event = next(event for event in events if event["type"] == "sources")
    complete_event = next(event for event in events if event["type"] == "complete")

    assert len(result.sources) == 1
    assert result.sources[0]["url"] == public.url
    assert "24 V [1]" in result.answer
    assert source_event["sources"] == result.sources
    assert complete_event["sources"] == result.sources
    assert complete_event["answer"] == result.answer


@pytest.mark.unit
async def test_non_upload_first_party_knowledge_case_keeps_existing_source_behavior():
    case = SearchResult(
        text="NE101 的供电案例内容。",
        source_id="solution-case/ne101/power.md",
        source_type="filesystem",
        product="knowledge",
        title="NE101 供电案例",
        url="",
        score=0.9,
        chunk_index=0,
    )
    rag, _ = _build_orchestrator([case], visibility_guard=_upload_aware_visibility_guard([case]))

    result = await rag.answer("NE101 供电案例", "widget")

    assert len(result.sources) == 1
    assert result.sources[0]["title"] == "NE101 供电案例"
    assert result.sources[0]["url"] == ""
    assert result.sources[0]["source_id"] == case.source_id


@pytest.mark.unit
async def test_non_upload_internal_background_remains_context_only():
    internal = SearchResult(
        text="历史案例曾记录 NE101 旧版固件上电后重启。",
        source_id="internal-case/ne101/private.md",
        source_type="filesystem",
        product="knowledge",
        title="内部案例",
        url="file:///srv/private/case.md",
        score=0.9,
        chunk_index=0,
        channel_visibility=("widget", "internal"),
    )
    rag, llm = _build_orchestrator([internal])

    result = await rag.answer("NE101 案例", "widget")

    generation_messages = next(
        call.args[0]
        for call in reversed(llm.generate.call_args_list)
        if call.kwargs.get("task") == "generation"
    )
    prompt = str(generation_messages)
    assert result.sources == []
    assert "## 背景资料(仅供理解上下文,禁止引用,严禁在其内容后标注 [N])" in prompt
    assert "「背景资料」仅供理解上下文,禁止引用" in prompt
    assert "「背景资料」仅供理解上下文,禁止作为回答依据" not in prompt
    assert "历史案例曾记录 NE101 旧版固件上电后重启。" in prompt


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
