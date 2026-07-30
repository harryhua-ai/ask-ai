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
    # 拒答时不应调用 LLM
    llm.generate.assert_not_called()


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
async def test_rag_rejects_when_below_min_results():
    """rerank 结果不足 min_results_to_answer 条时拒答(P0-2)。"""
    sr = _make_sr()
    searcher = MagicMock()
    searcher.search.return_value = [sr, sr]
    reranker = MagicMock()
    reranker.rerank.return_value = [sr]  # 只有 1 条 < min_results=3
    llm = AsyncMock()

    rag = RAGOrchestrator(searcher, reranker, llm, system_prompt="test", min_results_to_answer=3)
    result = await rag.answer("query", "widget")

    assert result.is_answered is False
    llm.generate.assert_not_called()


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
