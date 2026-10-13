"""Frozen EN/ZH clarification calibration cases for Issue #118."""

import json
from unittest.mock import MagicMock

import pytest

from backend.llm.base import LLMResponse
from backend.pipeline.rag import RAGOrchestrator
from backend.pipeline.task_understanding import understand_task
from backend.retrieval.search import SearchResult

GENERIC_ANSWERABLE = (
    "Is there a subscription fee?",
    "where to buy in australia",
    "I need night vision x2",
    "分辨率最高的产品是哪个？价格如何？",
    "how to hide this inside a vehicle?",
)
NECESSARY_CLARIFICATION = (
    "Which product fits my project?",
    "这台设备应该刷哪个硬件版本？",
    "这个设备支持什么？",
)


class CapturingLLM:
    def __init__(self, payload):
        self.payload = payload
        self.prompt = ""

    async def generate(self, messages, **kwargs):
        task = kwargs.get("task")
        if task == "task_understanding":
            self.prompt = messages[-1]["content"]
            content = json.dumps(self.payload)
        else:
            content = "Supported answer [1]"
        return LLMResponse(
            content=content,
            model="test",
            tokens_input=1,
            tokens_output=1,
            latency_ms=1,
        )

    def stream(self, messages, **kwargs):
        async def _stream():
            yield "Supported answer [1]"

        return _stream()


def _rag_for_payload(payload):
    llm = CapturingLLM(payload)
    evidence = SearchResult(
        text="Official public policy and product information.",
        source_id="official/public-info",
        source_type="website",
        product="unknown",
        title="Official information",
        url="https://example.com/official-info",
        score=0.9,
        chunk_index=0,
    )
    searcher = MagicMock()
    searcher.search.return_value = [evidence]
    searcher.search_symbols.return_value = []
    searcher.search_bucket.return_value = []
    reranker = MagicMock()
    reranker.rerank.return_value = [evidence]
    reranker.rerank_scored.return_value = ([evidence], [])
    rag = RAGOrchestrator(searcher, reranker, llm, system_prompt="test", min_results_to_answer=1)
    return rag, searcher


@pytest.mark.unit
@pytest.mark.parametrize("query", GENERIC_ANSWERABLE)
async def test_generic_answerable_calibration_cases_do_not_use_unconditional_model_clarify(query):
    llm = CapturingLLM(
        {
            "category": "product",
            "reason": "generic question can be searched without selecting one product",
            "confidence": 0.9,
            "interaction_mode": "standard",
            "evidence_intent": "factual",
            "extracted_query": query,
            "rewritten_query": query,
        }
    )

    result = await understand_task(query, None, llm)

    assert result.interaction_mode == "standard"
    assert query in llm.prompt

    rag, searcher = _rag_for_payload(llm.payload)
    answer = await rag.answer(query, "widget")

    assert searcher.search.called
    assert answer.is_answered is True
    assert answer.result_key != "clarification_required"


@pytest.mark.unit
@pytest.mark.parametrize("query", NECESSARY_CLARIFICATION)
async def test_selector_deixis_and_version_calibration_cases_remain_clarifications(query):
    llm = CapturingLLM(
        {
            "category": "product",
            "reason": "answer depends on missing product, device, or version",
            "confidence": 0.9,
            "interaction_mode": "clarification_required",
            "evidence_intent": "recommendation",
            "extracted_query": query,
            "rewritten_query": query,
        }
    )

    result = await understand_task(query, None, llm)

    assert result.interaction_mode == "clarification_required"
    assert query in llm.prompt

    rag, searcher = _rag_for_payload(llm.payload)
    answer = await rag.answer(query, "widget")

    assert answer.result_key in ("clarification_required", "product_ambiguous")
    assert searcher.search.call_count == 0


@pytest.mark.unit
async def test_understanding_prompt_distinguishes_generic_evidence_questions_from_selectors():
    query = "Is there a subscription fee?"
    llm = CapturingLLM(
        {
            "category": "commercial",
            "reason": "public purchase policy question",
            "confidence": 0.9,
            "interaction_mode": "standard",
            "extracted_query": query,
            "rewritten_query": query,
        }
    )

    await understand_task(query, None, llm)

    assert "公共事实、购买政策、泛能力或有证据的横向对比" in llm.prompt
    assert "Which product fits my project?" in llm.prompt
    assert "产品型号、具体场景或硬件版本" in llm.prompt
    assert "缺少产品型号)→ clarification_required" not in llm.prompt
