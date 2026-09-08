"""INC-3 修订 CONTEXT-AWARE-UNDERSTANDING + GENERIC-CORE-01 测试。

语义验证(T1-T13,验证行为而非实现细节):
- T1 无上下文欠指定 → clarification_required;
- T2/T3/T4 resolver 已安全确立目标(page_context/product_hint/会话确立)
  → 不得冗余澄清,正常域内管线继续;
- T5/T6 ambiguous/unsupported 语义不变(fail-closed 保持);
- T7 resolver 产品身份权威不被理解输出取代;
- T8 answer/stream parity;
- T9 通用核心 prompt 无厂商身份;
- T11/T12 失败回退与单调用保持。
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.pipeline.rag import RAGOrchestrator
from backend.retrieval.search import SearchResult

BOX_QUERY = "What is included in the box?"
_UNDERSTAND_CLARIFY = {
    "category": "product",
    "reason": "缺产品上下文",
    "confidence": 0.8,
    "interaction_mode": "clarification_required",
    "extracted_query": BOX_QUERY,
    "rewritten_query": BOX_QUERY,
}
_UNDERSTAND_STANDARD = {
    "category": "product",
    "reason": "r",
    "confidence": 0.9,
    "interaction_mode": "standard",
    "extracted_query": BOX_QUERY,
    "rewritten_query": BOX_QUERY,
}


def _make_llm(payload: dict) -> AsyncMock:
    llm = AsyncMock()
    llm.generate.return_value = MagicMock(content=json.dumps(payload, ensure_ascii=False))

    async def _stream(messages, **kwargs):
        yield "ok"

    llm.stream = _stream
    return llm


def _orchestrator(payload: dict, *, with_result: bool = False):
    """真实 resolver/taxonomy + 记录型检索边界。with_result=True 时检索有货。"""
    llm = _make_llm(payload)
    sr = SearchResult(
        text="NE503 包装清单:主机、电源适配器、天线。",
        source_id="site/neoeye-ne503",
        source_type="website",
        product="ne503",
        title="NE503",
        url="https://example.com/ne503",
        score=0.9,
        chunk_index=0,
    )
    searcher = MagicMock()
    searcher.search.return_value = [sr] if with_result else []
    searcher.search_symbols.return_value = []
    searcher.search_bucket.return_value = []
    reranker = MagicMock()
    reranker.rerank.return_value = [sr] if with_result else []
    rag = RAGOrchestrator(searcher, reranker, llm, system_prompt="s", min_results_to_answer=1)
    return rag, searcher, llm


async def _collect(rag, query, **kwargs):
    events = []
    async for raw in rag.stream_answer(query, "widget", **kwargs):
        events.append(json.loads(raw))
    return events


# --------------------------------------------------------------------------- #
# T1-T4:上下文可解 → 正常域内;不可解 → 澄清
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_t1_no_context_underspecified_clarifies():
    """T1:首轮无任何上下文 → clarification_required(非 off_topic/非拒答)。"""
    rag, _, _ = _orchestrator(_UNDERSTAND_CLARIFY)
    result = await rag.answer(BOX_QUERY, "widget")
    assert result.result_key == "clarification_required"
    assert result.trace_payload["interaction_mode"] == "clarification_required"
    assert result.trace_payload["stages"]["understanding"]["context_reconciled"] is False


@pytest.mark.unit
async def test_t2_page_context_resolved_proceeds_in_domain():
    """T2:page_context 确立 NE503 → 不得冗余澄清,正常域内继续。"""
    rag, searcher, _ = _orchestrator(_UNDERSTAND_CLARIFY, with_result=True)
    result = await rag.answer(BOX_QUERY, "widget", page_context={"product": "NE503"})
    assert result.result_key != "clarification_required"
    assert result.is_answered is True
    stages = result.trace_payload["stages"]
    assert stages["understanding"]["context_reconciled"] is True
    # T7:检索作用域绑定 resolver 目标(resolver 权威),非理解输出
    labels = [str(x).lower() for x in searcher.search.call_args.kwargs["product_labels"]]
    assert "ne503" in labels


@pytest.mark.unit
async def test_t3_product_hint_resolved_proceeds_in_domain():
    """T3:显式 product_hint → 不得冗余澄清。"""
    rag, searcher, _ = _orchestrator(_UNDERSTAND_CLARIFY, with_result=True)
    result = await rag.answer(BOX_QUERY, "widget", product_hint="NE503")
    assert result.result_key != "clarification_required"
    assert result.trace_payload["stages"]["understanding"]["context_reconciled"] is True
    labels = [str(x).lower() for x in searcher.search.call_args.kwargs["product_labels"]]
    assert "ne503" in labels


@pytest.mark.unit
async def test_t4_conversation_established_product_no_redundant_clarify():
    """T4:多轮指代追问且 resolver 经会话确立唯一产品 → 不冗余澄清。"""
    history = [
        {"role": "user", "content": "看看 NE301"},
        {"role": "assistant", "content": "NE301 是一款 AI 相机产品。"},
    ]
    rag, _, _ = _orchestrator(_UNDERSTAND_CLARIFY, with_result=True)
    result = await rag.answer("这个设备支持热成像吗", "widget", conversation_history=history)
    assert result.result_key != "clarification_required"
    assert result.trace_payload["stages"]["understanding"]["context_reconciled"] is True


# --------------------------------------------------------------------------- #
# T5/T6:resolver 既有 fail-closed 语义不变
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_t5_ambiguous_short_circuit_unchanged():
    """T5:指代在场但无处解析 → resolver 澄清短路(理解 LLM 不被调用)。"""
    llm = _make_llm(_UNDERSTAND_STANDARD)
    rag, _, _ = _orchestrator(_UNDERSTAND_STANDARD)
    rag._llm = llm
    result = await rag.answer("这个设备支持热成像吗", "widget")
    assert result.result_key == "product_ambiguous"
    llm.generate.assert_not_called()


@pytest.mark.unit
async def test_t6_unsupported_path_unchanged():
    """T6:不可解析的显式 hint → resolver unsupported 短路不变。"""
    rag, _, llm = _orchestrator(_UNDERSTAND_STANDARD)
    result = await rag.answer(BOX_QUERY, "widget", product_hint="Acme X9")
    assert result.result_key == "product_not_supported"
    llm.generate.assert_not_called()


# --------------------------------------------------------------------------- #
# T8:answer/stream parity
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_t8_answer_stream_parity_for_clarify_and_reconcile():
    """T8:T1(澄清)与 T2(调和继续)在流式路径行为等价。"""
    rag1, _, _ = _orchestrator(_UNDERSTAND_CLARIFY)
    events1 = await _collect(rag1, BOX_QUERY)
    c1 = [e for e in events1 if e["type"] == "complete"][-1]
    assert c1["result_key"] == "clarification_required"
    assert c1["interaction_mode"] == "clarification_required"

    rag2, _, _ = _orchestrator(_UNDERSTAND_CLARIFY, with_result=True)
    events2 = await _collect(rag2, BOX_QUERY, page_context={"product": "NE503"})
    c2 = [e for e in events2 if e["type"] == "complete"][-1]
    assert c2["result_key"] != "clarification_required"
    assert c2["trace_payload"]["stages"]["understanding"]["context_reconciled"] is True


# --------------------------------------------------------------------------- #
# T9:通用核心无厂商身份
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_t9_generic_core_prompt_has_no_vendor_identity():
    """修订 §5:通用理解核心不得假设部署身份为特定厂商。"""
    source = Path("backend/pipeline/task_understanding.py").read_text()
    assert "CamThink" not in source


# --------------------------------------------------------------------------- #
# T11/T12:fail-open 与单调用保持(修订不回归)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_t11_total_failure_still_fail_opens():
    llm = AsyncMock()
    llm.generate.side_effect = RuntimeError("down")
    rag, _, _ = _orchestrator(_UNDERSTAND_STANDARD)
    rag._llm = llm
    result = await rag.answer("random question", "widget")
    assert result.result_key != "off_topic"
    assert result.trace_payload["stages"]["understanding"]["fallback_used"] is True


@pytest.mark.unit
async def test_t12_single_understanding_call_maintained():
    rag, _, llm = _orchestrator(_UNDERSTAND_STANDARD, with_result=True)
    await rag.answer(BOX_QUERY, "widget", page_context={"product": "NE503"})
    understanding_calls = [
        c for c in llm.generate.call_args_list if c.kwargs.get("task") == "task_understanding"
    ]
    assert len(understanding_calls) == 1
    assert not any(
        c.kwargs.get("task") in ("intent", "query_rewrite") for c in llm.generate.call_args_list
    )
