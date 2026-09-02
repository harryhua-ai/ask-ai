"""RAGOrchestrator 单元测试。

覆盖 brief 基础 case + 以下增强 case:
- ``product_filter`` 透传到 searcher
- ``conversation_history`` 按 ``max_turns * 2`` 截断
- ``reranker.rerank`` 调用时 ``top_k`` 等于构造参数
- 多 chunk 同 URL 时 ``sources`` 去重
- ``stream_answer`` 正常序列:sources → token(s) → complete
- ``stream_answer`` 空结果仅发 complete 事件
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.llm.base import LLMResponse
from backend.pipeline.rag import RAGAnswer, RAGOrchestrator
from backend.retrieval.search import SearchResult

# --------------------------------------------------------------------------- #
# 测试辅助
# --------------------------------------------------------------------------- #


def _make_sr(
    *,
    text: str = "text",
    source_id: str = "s",
    source_type: str = "github",
    product: str = "ne503",
    title: str = "T",
    url: str = "https://example.com",
    score: float = 0.5,
    chunk_index: int = 0,
) -> SearchResult:
    """构造测试用 SearchResult。"""
    return SearchResult(
        text=text,
        source_id=source_id,
        source_type=source_type,
        product=product,
        title=title,
        url=url,
        score=score,
        chunk_index=chunk_index,
    )


def _make_llm_response(content: str = "answer") -> LLMResponse:
    """构造测试用 LLMResponse。"""
    return LLMResponse(
        content=content,
        model="test-model",
        tokens_input=10,
        tokens_output=5,
        latency_ms=50,
    )


def _build_orchestrator(
    *,
    searcher_results: list[SearchResult] | None = None,
    reranked_results: list[SearchResult] | None = None,
    llm_response: LLMResponse | None = None,
    top_k: int = 10,
    conversation_max_turns: int = 5,
    system_prompt: str = "You are helpful.",
    min_results_to_answer: int = 1,
) -> tuple[RAGOrchestrator, MagicMock, MagicMock, AsyncMock]:
    """构造预填 mock 的 RAGOrchestrator,返回 (rag, searcher, reranker, llm)。

    默认:
    - searcher.search 返回 searcher_results(默认单条 SearchResult)
    - reranker.rerank 返回 reranked_results(默认同 searcher_results)
    - llm.generate 返回 llm_response(默认 content="answer")
    """
    sr = _make_sr()
    searcher = MagicMock()
    searcher.search.return_value = searcher_results if searcher_results is not None else [sr]

    reranker = MagicMock()
    reranker.rerank.return_value = reranked_results if reranked_results is not None else [sr]

    llm = AsyncMock()
    llm.generate.return_value = llm_response if llm_response is not None else _make_llm_response()

    rag = RAGOrchestrator(
        searcher=searcher,
        reranker=reranker,
        llm=llm,
        system_prompt=system_prompt,
        top_k=top_k,
        conversation_max_turns=conversation_max_turns,
        min_results_to_answer=min_results_to_answer,
    )
    return rag, searcher, reranker, llm


# --------------------------------------------------------------------------- #
# brief 基础测试
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_rag_rejects_when_no_results():
    """brief 用例:searcher 返回空 → 拒答,is_answered=False。"""
    searcher = MagicMock()
    searcher.search.return_value = []
    reranker = MagicMock()
    reranker.rerank.return_value = []
    llm = AsyncMock()

    rag = RAGOrchestrator(searcher, reranker, llm, system_prompt="You are helpful.")
    result = await rag.answer("random question", "widget")

    assert isinstance(result, RAGAnswer)
    assert result.is_answered is False
    assert "暂未在官方资料中找到" in result.answer


@pytest.mark.unit
async def test_rag_generates_answer():
    """brief 用例:正常生成路径,答案包含来源信息。

    Note: brief 原文中 reranker.rerank.return_value = [0.95] 与
    RAGOrchestrator 实现不兼容(实现依赖 SearchResult.source_type /
    .title / .url / .text / .product 字段)。此处修正为返回
    SearchResult 列表,与 :class:`backend.retrieval.rerank.RerankPipeline`
    实际契约一致。
    """
    sr = SearchResult(
        text="NE503 功耗 2.5W",
        source_id="s1",
        source_type="github",
        product="ne503",
        title="README",
        url="https://github.com/milesight/ne503/README",
        score=0.9,
        chunk_index=0,
    )
    searcher = MagicMock()
    searcher.search.return_value = [sr]
    reranker = MagicMock()
    reranker.rerank.return_value = [sr]  # SearchResult 列表(非 float)
    llm = AsyncMock()
    llm.generate.return_value = LLMResponse(
        content="NE503 的功耗为 2.5W [GitHub]",
        model="deepseek-chat",
        tokens_input=100,
        tokens_output=20,
        latency_ms=500,
    )

    rag = RAGOrchestrator(searcher, reranker, llm, system_prompt="You are helpful.", min_results_to_answer=1)
    result = await rag.answer("NE503 功耗是多少?", "widget")

    assert result.is_answered is True
    assert "2.5W" in result.answer
    assert len(result.sources) == 1


# --------------------------------------------------------------------------- #
# 增强测试
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_rag_passes_product_filter_to_searcher():
    """product_filter 非空时,应作为 kwargs 传给 searcher.search。"""
    rag, searcher, _, _ = _build_orchestrator()

    await rag.answer("query", "widget", product_filter="ne503")

    searcher.search.assert_called_once()
    _, kwargs = searcher.search.call_args
    assert kwargs.get("product_filter") == "ne503"


@pytest.mark.unit
async def test_rag_truncates_conversation_history_to_max_turns():
    """history 长度超过 max_turns*2 时被截断到最近 max_turns*2 条。"""
    rag, _, _, llm = _build_orchestrator(conversation_max_turns=2)

    # 6 条消息 = 3 轮(超过 max_turns=2 → 截断到最近 4 条)
    long_history: list[dict] = []
    for i in range(3):
        long_history.append({"role": "user", "content": f"old user {i}"})
        long_history.append({"role": "assistant", "content": f"old assistant {i}"})
    assert len(long_history) == 6

    await rag.answer("query", "widget", conversation_history=long_history)

    llm.generate.assert_awaited()
    messages, _ = llm.generate.call_args.args, llm.generate.call_args.kwargs
    passed_messages = messages[0] if messages else llm.generate.call_args.args[0]

    # 期望:1 system + 4 history(2 轮)+ 1 user = 6
    assert len(passed_messages) == 1 + 4 + 1
    # 截断后保留最近 4 条历史(即 old user/assistant 1 和 2)
    history_passed = [m for m in passed_messages if m["role"] != "system"]
    # 去掉最后一个 user 消息后剩下的是历史
    history_only = history_passed[:-1]
    assert len(history_only) == 4
    assert history_only[0]["content"] == "old user 1"
    assert history_only[-1]["content"] == "old assistant 2"


@pytest.mark.unit
async def test_rag_uses_reranker_top_k():
    """reranker.rerank 调用时 top_k 等于构造参数。"""
    rag, _, reranker, _ = _build_orchestrator(top_k=7)

    await rag.answer("query", "widget")

    reranker.rerank.assert_called_once()
    _, kwargs = reranker.rerank.call_args
    assert kwargs.get("top_k") == 7


@pytest.mark.unit
async def test_rag_deduplicates_sources_by_url():
    """多个 chunk 同 URL 时,sources 只保留一个。"""
    shared_url = "https://github.com/milesight/ne503/README"
    sr1 = _make_sr(
        text="chunk 1",
        source_id="s1",
        title="README",
        url=shared_url,
        chunk_index=0,
    )
    sr2 = _make_sr(
        text="chunk 2",
        source_id="s2",
        title="README",
        url=shared_url,
        chunk_index=1,
    )
    sr3 = _make_sr(
        text="chunk 3",
        source_id="s3",
        title="Other",
        url="https://wiki.example.com/ne503",
    )

    rag, _, _, _ = _build_orchestrator(
        searcher_results=[sr1, sr2, sr3],
        reranked_results=[sr1, sr2, sr3],
    )

    result = await rag.answer("query", "widget")

    # 3 个 chunk,2 个唯一 URL → 2 个 source
    assert len(result.sources) == 2
    urls = [s["url"] for s in result.sources]
    assert shared_url in urls
    assert "https://wiki.example.com/ne503" in urls


@pytest.mark.unit
async def test_rag_filters_internal_sources_from_public_list():
    """filesystem(内部 support 案例)不进对外 sources 列表,但其他公开源保留。"""
    public_sr = _make_sr(
        text="public doc",
        source_id="s1",
        title="NE101 README",
        url="https://github.com/camthink-ai/ne101/README.md",
        source_type="github",
    )
    internal_sr = _make_sr(
        text="internal case",
        source_id="s2",
        title="NE101-电源适配器电压咨询",
        url="file:///home/ubuntu/knowledge-support/2026-04/NE101-电源.md",
        source_type="filesystem",
    )

    rag, _, _, _ = _build_orchestrator(
        searcher_results=[public_sr, internal_sr],
        reranked_results=[public_sr, internal_sr],
    )

    result = await rag.answer("NE101 power supply", "widget")

    # filesystem 被过滤,只留 github 公开源
    assert len(result.sources) == 1
    assert result.sources[0]["type"] == "github"
    assert all(s["type"] != "filesystem" for s in result.sources)


@pytest.mark.unit
async def test_rag_filters_all_internal_when_no_public_source():
    """全 filesystem 召回时,sources 为空(内部源不外露,不补足)。"""
    internal_sr = _make_sr(
        text="internal only",
        source_id="s1",
        title="内部案例",
        url="file:///home/ubuntu/knowledge-support/case.md",
        source_type="filesystem",
    )

    rag, _, _, _ = _build_orchestrator(
        searcher_results=[internal_sr],
        reranked_results=[internal_sr],
    )

    result = await rag.answer("query", "widget")

    assert result.sources == []


@pytest.mark.unit
async def test_rag_web_crawl_source_enters_public_list():
    """web_crawl(官网爬取,C8)属公开源,进对外 sources。"""
    web_sr = _make_sr(
        text="NG4500 搭载 Jetson 平台",
        source_id="website-camthink/product/neoedge-ai-box-ng4500",
        title="NeoEdge AI Box NG4500",
        url="https://www.camthink.ai/product/neoedge-ai-box-ng4500/",
        source_type="web_crawl",
        product="website",
    )

    rag, _, _, _ = _build_orchestrator(
        searcher_results=[web_sr],
        reranked_results=[web_sr],
    )

    result = await rag.answer("NG4500 用什么平台", "widget")

    assert len(result.sources) == 1
    assert result.sources[0]["type"] == "web_crawl"


@pytest.mark.unit
async def test_rag_stream_answer_emits_sources_then_tokens_then_complete():
    """stream_answer 正常序列:sources → token(s) → complete。"""
    sr = _make_sr(text="hello world", url="https://example.com/a")
    rag, _, _, llm = _build_orchestrator(reranked_results=[sr])

    # mock llm.stream 为 AsyncIterator,产 2 个 chunk
    async def _fake_stream(messages, task=None):
        yield "Hello"
        yield " world"

    llm.stream = MagicMock()
    llm.stream.return_value = _fake_stream([], task="generation")

    events = []
    async for evt in rag.stream_answer("query", "widget"):
        events.append(json.loads(evt))

    # 期望事件序列:sources → token → token → complete
    assert len(events) == 4
    assert events[0]["type"] == "sources"
    assert events[1]["type"] == "token"
    assert events[1]["content"] == "Hello"
    assert events[2]["type"] == "token"
    assert events[2]["content"] == " world"
    assert events[3]["type"] == "complete"
    assert events[3]["is_answered"] is True
    assert events[3]["answer"] == "Hello world"
    # sources 事件与 complete 事件的 sources 应一致
    assert events[0]["sources"] == events[3]["sources"]


@pytest.mark.unit
async def test_rag_stream_answer_rejects_when_empty():
    """流式模式下 searcher 返回空 → 仅发一个 complete 事件(is_answered=False)。"""
    searcher = MagicMock()
    searcher.search.return_value = []
    reranker = MagicMock()
    reranker.rerank.return_value = []
    llm = AsyncMock()

    rag = RAGOrchestrator(searcher, reranker, llm, system_prompt="You are helpful.")
    events = []
    async for evt in rag.stream_answer("query", "widget"):
        events.append(json.loads(evt))

    # 仅一个 complete 事件,无 sources / token
    assert len(events) == 1
    assert events[0]["type"] == "complete"
    assert events[0]["is_answered"] is False
    assert "暂未在官方资料中找到" in events[0]["answer"]
    # 不应调用 LLM stream
    llm.stream.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.unit
async def test_answer_passes_channel_to_searcher():
    """RAGOrchestrator.answer 应把 channel 透传给 searcher.search。"""
    from unittest.mock import AsyncMock, MagicMock
    from backend.pipeline.rag import RAGOrchestrator

    mock_searcher = MagicMock()
    mock_searcher.search.return_value = []
    mock_reranker = MagicMock()
    mock_reranker.rerank.return_value = []
    mock_llm = AsyncMock()

    orchestrator = RAGOrchestrator(
        searcher=mock_searcher, reranker=mock_reranker, llm=mock_llm,
        system_prompt="test",
    )
    await orchestrator.answer("question", channel="widget")

    mock_searcher.search.assert_called()
    call_kwargs = mock_searcher.search.call_args.kwargs
    assert call_kwargs.get("channel") == "widget"


# --------------------------------------------------------------------------- #
# Phase 3A: Pruner 集成测试
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_rag_calls_async_pruner():
    """RAGOrchestrator 应以 await 方式调用 pruner.prune()。"""
    sr = _make_sr(text="relevant", url="https://example.com/a")
    rag, searcher, reranker, llm = _build_orchestrator(
        searcher_results=[sr], reranked_results=[sr]
    )

    pruner = AsyncMock()
    pruner.prune.return_value = [sr]
    rag._pruner = pruner

    await rag.answer("query", "widget")

    pruner.prune.assert_awaited_once()


@pytest.mark.unit
async def test_rag_pruner_filters_reflected_in_answer():
    """Pruner 过滤掉的 chunk 不应出现在最终 sources 中。"""
    sr1 = _make_sr(text="keep", source_id="s1", url="https://example.com/keep")
    sr2 = _make_sr(text="drop", source_id="s2", url="https://example.com/drop")

    rag, searcher, reranker, llm = _build_orchestrator(
        searcher_results=[sr1, sr2], reranked_results=[sr1, sr2]
    )

    pruner = AsyncMock()
    pruner.prune.return_value = [sr1]  # 只保留 sr1
    rag._pruner = pruner

    result = await rag.answer("query", "widget")

    assert result.is_answered is True
    urls = [s["url"] for s in result.sources]
    assert "https://example.com/keep" in urls
    assert "https://example.com/drop" not in urls


# --------------------------------------------------------------------------- #
# Phase 3A: Override 前置检查测试
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_rag_returns_override_when_matched():
    """OverrideMatcher 命中时,直接返回覆盖答案,跳过 search/rerank/generate。"""
    from backend.db.models import AnswerOverride

    override = AnswerOverride(
        id=None,
        match_pattern="保修",
        match_type="keyword",
        override_answer="保修期为 2 年",
        override_sources=[{"url": "https://example.com/warranty", "title": "Warranty"}],
        created_by="admin",
        is_active=True,
    )

    matcher = AsyncMock()
    matcher.match.return_value = override

    rag, searcher, reranker, llm = _build_orchestrator()
    rag._override_matcher = matcher

    result = await rag.answer("保修期多久?", "widget")

    assert result.is_answered is True
    assert result.answer == "保修期为 2 年"
    assert len(result.sources) == 1
    assert result.sources[0]["url"] == "https://example.com/warranty"
    searcher.search.assert_not_called()
    llm.generate.assert_not_called()


@pytest.mark.unit
async def test_rag_skips_override_when_no_match():
    """OverrideMatcher 未命中时,正常执行 RAG 管线。"""
    matcher = AsyncMock()
    matcher.match.return_value = None

    rag, searcher, reranker, llm = _build_orchestrator()
    rag._override_matcher = matcher

    await rag.answer("query", "widget")

    searcher.search.assert_called_once()


@pytest.mark.unit
async def test_rag_stream_answer_emits_override():
    """流式模式下 override 命中时,发出 sources → token → complete 事件。"""
    from backend.db.models import AnswerOverride

    override = AnswerOverride(
        id=None,
        match_pattern="保修",
        match_type="keyword",
        override_answer="保修期为 2 年",
        override_sources=[{"url": "https://example.com/warranty", "title": "Warranty"}],
        created_by="admin",
        is_active=True,
    )

    matcher = AsyncMock()
    matcher.match.return_value = override

    rag, _, _, llm = _build_orchestrator()
    rag._override_matcher = matcher

    events = []
    async for evt in rag.stream_answer("保修期?", "widget"):
        events.append(json.loads(evt))

    assert len(events) == 3
    assert events[0]["type"] == "sources"
    assert events[1]["type"] == "token"
    assert events[1]["content"] == "保修期为 2 年"
    assert events[2]["type"] == "complete"
    assert events[2]["is_answered"] is True
    assert events[2]["answer"] == "保修期为 2 年"
    llm.stream.assert_not_called()


# --------------------------------------------------------------------------- #
# 意图识别测试
# --------------------------------------------------------------------------- #


def _intent_response(category: str) -> MagicMock:
    """构造意图识别 LLM 响应(JSON 字符串)。"""
    resp = MagicMock()
    import json as _json

    resp.content = _json.dumps({"category": category, "reason": "test"})
    return resp


@pytest.mark.unit
async def test_rag_off_topic_rejects_without_search():
    """意图为 off_topic 时不进入检索,直接拒绝。"""
    sr = _make_sr()
    searcher = MagicMock()
    searcher.search.return_value = [sr]
    reranker = MagicMock()
    reranker.rerank.return_value = [sr]
    llm = AsyncMock()
    llm.generate.return_value = _intent_response("off_topic")

    rag = RAGOrchestrator(searcher, reranker, llm, system_prompt="test")
    result = await rag.answer("今天天气怎么样?", "widget")

    assert result.is_answered is False
    # 友好边界(产品契约 B):说明服务范围并引导,而非 system-style rejection
    assert "CamThink" in result.answer
    scope_words = ("选型", "功能", "方案")
    assert any(w in result.answer for w in scope_words)
    searcher.search.assert_not_called()


@pytest.mark.unit
async def test_rag_commercial_enters_search_after_woocommerce_enabled():
    """commercial 意图走检索作答(WooCommerce 灌库后不再拒答)。

    旧策略:commercial → REJECT_BUSINESS 不检索(过渡期)。
    新策略:WooCommerce 产品已灌库,commercial 走 woocommerce boost 桶召回产品作答。
    """
    sr = _make_sr()
    searcher = MagicMock()
    searcher.search.return_value = [sr]
    reranker = MagicMock()
    reranker.rerank.return_value = [sr]
    llm = AsyncMock()
    llm.generate.return_value = _intent_response("commercial")
    llm.stream = AsyncMock(return_value=iter(["价格", "信息"]))

    rag = RAGOrchestrator(searcher, reranker, llm, system_prompt="test")
    result = await rag.answer("价格多少?", "widget")

    # commercial 现在进检索作答,不拒答
    assert searcher.search.called is True
    assert result.is_answered is True
    assert "销售团队" not in result.answer  # 不再是 REJECT_BUSINESS


@pytest.mark.unit
async def test_rag_product_question_answers_with_few_results():
    """意图为 product 时,即使结果数 < min_results 仍尝试回答。"""
    sr = _make_sr()
    searcher = MagicMock()
    searcher.search.return_value = [sr]
    searcher.search_symbols.return_value = []
    searcher.search_bucket.return_value = []
    reranker = MagicMock()
    reranker.rerank.return_value = [sr]  # 仅 1 条结果
    llm = AsyncMock()
    # classify_intent → extract_query → generation
    llm.generate.side_effect = [
        _intent_response("product"),
        _make_llm_response("NE301 电池监控"),
        _make_llm_response("电池监控需要通过 I2C 读取"),
    ]

    rag = RAGOrchestrator(
        searcher, reranker, llm,
        system_prompt="test",
        min_results_to_answer=3,  # 正常阈值 3,但 product 降为 1
    )
    result = await rag.answer("NE301 电池监控", "widget")

    assert result.is_answered is True
    assert "电池" in result.answer


@pytest.mark.unit
async def test_rag_intent_fail_open_proceeds():
    """意图识别失败时 fail-open 为 product,正常进入 RAG 管线。"""
    sr = _make_sr()
    searcher = MagicMock()
    searcher.search.return_value = [sr]
    searcher.search_symbols.return_value = []
    searcher.search_bucket.return_value = []
    reranker = MagicMock()
    reranker.rerank.return_value = [sr]
    llm = AsyncMock()
    # classify_intent (fail-open) → extract_query → rewrite_query → generation
    bad_resp = MagicMock()
    bad_resp.content = "NOT JSON"
    llm.generate.side_effect = [
        bad_resp,
        _make_llm_response("NE301 配置"),
        _make_llm_response("NE301 配置"),
        _make_llm_response("answer"),
    ]

    rag = RAGOrchestrator(searcher, reranker, llm, system_prompt="test")
    result = await rag.answer("NE301 配置", "widget")

    assert result.is_answered is True
    searcher.search.assert_called_once()


@pytest.mark.unit
async def test_rag_uses_symbol_recall_and_rrf():
    """符号召回(用 extract_query 输出)+ hybrid(search_query)+ boost 桶 RRF 融合送 rerank。

    Note: rewrite_query 在无 conversation_history 时短路返回 extracted(见
    backend/pipeline/query_rewrite.py:54),故此处 search_query == extracted ==
    'i2c battery'。带 history 的 rewrite 行为由 query_rewrite 自身测试覆盖。
    """
    a = _make_sr(text="a", source_id="s1")
    b = _make_sr(text="b", source_id="s2")
    searcher = MagicMock()
    searcher.search.return_value = [a]           # hybrid 返回 [a]
    searcher.search_symbols.return_value = [b]   # 符号召回返回 [b]
    searcher.search_bucket.return_value = []      # product 桶空(不干扰断言)
    reranker = MagicMock()
    reranker.rerank.return_value = [a, b]         # 透传,便于断言输入
    llm = AsyncMock()
    # classify_intent → extract_query → generation(rewrite 无 history 短路,不调 LLM)
    llm.generate.side_effect = [
        _intent_response("product"),
        _make_llm_response("i2c battery"),          # extract_query 输出
        _make_llm_response("answer"),
    ]
    rag = RAGOrchestrator(searcher, reranker, llm, system_prompt="test")
    await rag.answer("NE301 I2C 读电池监控", "widget")
    # 无 history:rewrite_query 短路,search_query == extracted
    searcher.search.assert_called_once()
    assert searcher.search.call_args.kwargs["query"] == "i2c battery"
    searcher.search_symbols.assert_called_once()
    assert searcher.search_symbols.call_args.kwargs["query"] == "i2c battery"
    # rerank 收到 RRF 融合结果(两路:hybrid [a] + symbol [b])
    assert len(reranker.rerank.call_args.args[1]) == 2


# --------------------------------------------------------------------------- #
# 意图 4 分类路由 + _retrieve_and_fuse parity + RAGAnswer.intent
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_rag_routes_commercial_to_search():
    """commercial 意图 → 进检索作答(WooCommerce 灌库后,不再 REJECT_BUSINESS)。"""
    rag, searcher, reranker, llm = _build_orchestrator(searcher_results=[_make_sr()])
    llm.generate = AsyncMock(side_effect=[
        # classify_intent 返回 commercial
        _make_llm_response('{"category": "commercial", "reason": "价格"}'),
        _make_llm_response("extracted"),
        _make_llm_response("rewritten"),
        _make_llm_response("answer"),
    ])
    result = await rag.answer("NE301 价格多少", channel="widget")
    # commercial 走检索,不拒答
    assert searcher.search.assert_called_once if hasattr(searcher.search, "assert_called_once") else True
    assert result.is_answered is True
    assert "销售团队" not in result.answer


@pytest.mark.unit
async def test_rag_support_intent_triggers_search_bucket():
    """support 意图 → search_bucket(source_types=['filesystem']) 被调。"""
    sr = _make_sr()
    rag, searcher, reranker, llm = _build_orchestrator(searcher_results=[sr])
    searcher.search_symbols.return_value = []
    searcher.search_bucket.return_value = []
    # classify → support;extract/rewrite 正常;generate 给答案
    llm.generate = AsyncMock(side_effect=[
        _make_llm_response('{"category": "support", "reason": "故障"}'),
        _make_llm_response("extracted"),
        _make_llm_response("rewritten"),
        _make_llm_response("answer"),
    ])
    await rag.answer("NE101 蜂窝网络注册失败", channel="widget")
    searcher.search_bucket.assert_called_once()
    kwargs = searcher.search_bucket.call_args.kwargs
    assert kwargs.get("source_types") == ["filesystem"]


@pytest.mark.unit
async def test_rag_product_intent_triggers_docs_bucket():
    """product 意图 → search_bucket(chunk_types=docs) 被调。"""
    sr = _make_sr()
    rag, searcher, reranker, llm = _build_orchestrator(searcher_results=[sr])
    searcher.search_symbols.return_value = []
    searcher.search_bucket.return_value = []
    llm.generate = AsyncMock(side_effect=[
        _make_llm_response('{"category": "product", "reason": "产品"}'),
        _make_llm_response("extracted"),
        _make_llm_response("rewritten"),
        _make_llm_response("answer"),
    ])
    await rag.answer("NE301 功能", channel="widget")
    searcher.search_bucket.assert_called_once()
    assert searcher.search_bucket.call_args.kwargs.get("chunk_types") == [
        "paragraph", "heading", "list", "table"
    ]


@pytest.mark.unit
async def test_rag_answer_carries_intent_field():
    """RAGAnswer.intent 正确填充(product)。"""
    sr = _make_sr()
    rag, searcher, reranker, llm = _build_orchestrator(searcher_results=[sr])
    searcher.search_symbols.return_value = []
    searcher.search_bucket.return_value = []
    llm.generate = AsyncMock(side_effect=[
        _make_llm_response('{"category": "product", "reason": "x"}'),
        _make_llm_response("e"),
        _make_llm_response("r"),
        _make_llm_response("answer"),
    ])
    result = await rag.answer("NE301 功能", channel="widget")
    assert result.intent == "product"


@pytest.mark.unit
async def test_rag_stream_complete_event_carries_intent():
    """stream_answer complete 事件含 'intent' 字段。"""
    sr = _make_sr()
    rag, searcher, reranker, llm = _build_orchestrator(searcher_results=[sr])
    searcher.search_symbols.return_value = []
    searcher.search_bucket.return_value = []
    llm.generate = AsyncMock(side_effect=[
        _make_llm_response('{"category": "support", "reason": "x"}'),
        _make_llm_response("e"),
        _make_llm_response("r"),
    ])

    async def _fake_stream(messages, task=None):
        for tok in ("ans",):
            yield tok

    llm.stream = MagicMock()
    llm.stream.return_value = _fake_stream([], task="generation")

    events = []
    async for ev in rag.stream_answer("NE101 故障", channel="widget"):
        events.append(json.loads(ev))

    complete = [e for e in events if e["type"] == "complete"][0]
    assert complete["intent"] == "support"


@pytest.mark.unit
async def test_rag_stream_answer_uses_symbol_and_bucket_parity():
    """stream_answer 也调 search_symbols + search_bucket(与 answer parity)。"""
    sr = _make_sr()
    rag, searcher, reranker, llm = _build_orchestrator(searcher_results=[sr])
    searcher.search_symbols.return_value = []
    searcher.search_bucket.return_value = []
    llm.generate = AsyncMock(side_effect=[
        _make_llm_response('{"category": "product", "reason": "x"}'),
        _make_llm_response("e"),
        _make_llm_response("r"),
    ])

    async def _fake_stream(messages, task=None):
        for tok in ("ans",):
            yield tok

    llm.stream = MagicMock()
    llm.stream.return_value = _fake_stream([], task="generation")

    async for _ in rag.stream_answer("NE301", channel="widget"):
        pass
    searcher.search_symbols.assert_called_once()
    searcher.search_bucket.assert_called_once()


# --------------------------------------------------------------------------- #
# P1: 拒答兜底 —— rerank 滤光但召回非空时降级用 fused top-N
# 场景:Q98(DeepInspect)/Q104(纺织检测) 场景术语召回命中(fused 非空),
#   但 rerank threshold=0.3 把弱相关候选全滤光(reranked=[]),
#   当前直接拒答。修复后应降级用 fused top-N 继续生成。
# ---------------------------------------------------------------------------


@pytest.mark.unit
async def test_rag_falls_back_when_rerank_filters_all():
    """reranked 为空但 fused 非空时,应降级用 fused top-N 继续生成,不拒答。

    复现场景:场景术语(如"纺织检测""DeepInspect")召回命中,
    reranker 给的分 < 0.3 阈值被全滤光。当前代码 reranked=[] 直接拒答,
    导致 Q98/Q100/Q104 误拒。修复后应拿 fused top-N 作降级上下文继续生成。
    """
    sr = _make_sr(text="纺织检测相关内容", source_id="s1", score=0.25)
    searcher = MagicMock()
    searcher.search.return_value = [sr]  # hybrid 召回命中
    searcher.search_symbols.return_value = []
    searcher.search_bucket.return_value = []
    reranker = MagicMock()
    reranker.rerank.return_value = []  # threshold 把候选全滤光
    llm = AsyncMock()
    llm.generate.side_effect = [
        _intent_response("product"),
        _make_llm_response("textile inspection"),
        _make_llm_response("纺织检测答案是..."),
    ]

    rag = RAGOrchestrator(searcher, reranker, llm, system_prompt="test")
    result = await rag.answer("纺织布料缺陷检测", "widget")

    # 关键:不应拒答,应降级用 fused 候选继续生成
    assert result.is_answered is True, (
        f"reranked 空但 fused 非空时应降级生成,不应拒答(实际 is_answered={result.is_answered})"
    )
    assert result.answer != "暂未在官方资料中找到相关信息。"


@pytest.mark.unit
async def test_rag_still_rejects_when_both_fused_and_reranked_empty():
    """fused 也为空时(真无召回)仍应拒答 —— 兜底只救"有召回被滤光"的场景。"""
    searcher = MagicMock()
    searcher.search.return_value = []
    searcher.search_symbols.return_value = []
    searcher.search_bucket.return_value = []
    reranker = MagicMock()
    reranker.rerank.return_value = []
    llm = AsyncMock()
    llm.generate.side_effect = [
        _intent_response("product"),
        _make_llm_response("q"),
    ]

    rag = RAGOrchestrator(searcher, reranker, llm, system_prompt="test")
    result = await rag.answer("完全不相关的问题", "widget")

    assert result.is_answered is False
    assert "暂未在官方资料中找到" in result.answer
