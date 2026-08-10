"""RAG trace 插桩测试。

answer() 签名: answer(query, channel='widget', conversation_history=None, product_filter=None)
IntentResult 只有 category + reason,无 confidence。
LLMResponse 字段: content/model/tokens_input/tokens_output/latency_ms。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.llm.base import LLMResponse
from backend.pipeline.rag import RAGOrchestrator


def _build_test_orchestrator(*, intent_category="commercial") -> RAGOrchestrator:
    """构造 mock 依赖的 orchestrator。intent_category 控制意图分类返回。"""

    llm = MagicMock()

    def _generate_side_effect(messages, **kwargs):
        task = kwargs.get("task", "generation")
        if task == "intent":
            return LLMResponse(
                content=f'{{"category":"{intent_category}","reason":"test"}}',
                model="test",
                tokens_input=5,
                tokens_output=5,
                latency_ms=20,
            )
        if task in ("extract", "rewrite"):
            return LLMResponse(
                content="改写后的查询",
                model="test",
                tokens_input=5,
                tokens_output=5,
                latency_ms=30,
            )
        return LLMResponse(
            content="答案文本",
            model="test",
            tokens_input=10,
            tokens_output=5,
            latency_ms=100,
        )

    llm.generate = AsyncMock(side_effect=_generate_side_effect)

    searcher = MagicMock()
    searcher.search = MagicMock(return_value=[])
    searcher.search_symbols = MagicMock(return_value=[])
    searcher.search_bucket = MagicMock(return_value=[])

    reranker = MagicMock()
    reranker.rerank = MagicMock(
        return_value=[
            MagicMock(
                url="http://x",
                title="t",
                text="ctx",
                source_type="github",
                product="NE503",
                score=0.9,
            )
        ]
    )

    return RAGOrchestrator(
        searcher=searcher,
        reranker=reranker,
        llm=llm,
        system_prompt="test",
        min_results_to_answer=1,
    )


@pytest.mark.asyncio
async def test_answer_produces_trace_payload():
    """正常 RAG 流程,answer() 返回的 RAGAnswer 带 trace_payload,含 5 阶段 ms。"""
    orch = _build_test_orchestrator(intent_category="commercial")
    result = await orch.answer("NE503 价格", channel="widget")
    assert result.trace_payload is not None
    tp = result.trace_payload
    assert tp["type"] == "rag"
    for stage in ("intent", "rewrite", "retrieve", "rerank", "generate"):
        assert stage in tp["stages"]
        assert "ms" in tp["stages"][stage]
    assert tp["total_ms"] >= 0
    assert tp["intent"] == "commercial"


@pytest.mark.asyncio
async def test_answer_off_topic_trace_type():
    """off_topic 短路:trace_payload type=reject_short,只含 intent 阶段。"""
    orch = _build_test_orchestrator(intent_category="off_topic")
    result = await orch.answer("今天天气", channel="widget")
    assert result.trace_payload["type"] == "reject_short"
    assert "intent" in result.trace_payload["stages"]
    assert "generate" not in result.trace_payload["stages"]
