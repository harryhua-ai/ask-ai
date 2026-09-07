"""INC-1 — 答案管线可观测基线(编排器级)。

- Trace 新增 ``llm_calls``(每次 LLM 调用的结构化事件 + 条件跳过标记),
  挂在 trace_payload 顶层;
- extract/rewrite 计时分离(extract_ms/rewrite_ms,保留合并 ms);
- 修剪阶段独立延迟(prune_ms);
- 流式 ``generate.tokens_output`` = provider 实际用量(原为字符数),
  字符数改存 ``answer_chars``。
"""

import json
from unittest.mock import MagicMock

import pytest

from backend.llm import telemetry
from backend.llm.base import LLMResponse
from backend.llm.registry import LLMRouter
from backend.pipeline.rag import RAGOrchestrator
from backend.retrieval.search import SearchResult

QUESTION = "NE301 支持热成像入侵检测吗"


class _FakeProvider:
    """按 prompt 内容分派响应的假 provider(经 LLMRouter 统计调用事件)。"""

    provider_id = "fake"

    def __init__(self, intent_category="product"):
        self._intent_category = intent_category

    @property
    def default_model(self):
        return "fake-model"

    async def health_check(self):
        return True

    async def generate(self, messages, **kwargs):
        prompt = messages[-1]["content"] if messages else ""
        if "意图分类" in prompt:
            content = json.dumps(
                {
                    "category": self._intent_category,
                    "reason": "产品问题",
                    "confidence": 0.9,
                }
            )
        else:
            content = prompt.split("\n")[-1][:200] or QUESTION
        return LLMResponse(
            content=content,
            model="fake-model",
            tokens_input=11,
            tokens_output=7,
            latency_ms=1,
        )

    async def stream(self, messages, **kwargs):
        yield "**结论**"
        yield "支持 [1]"
        telemetry.record_stream_usage(7, 22)


def _search_result():
    return SearchResult(
        text="NE301 文档内容",
        source_id="s1",
        source_type="github",
        product="ne301",
        title="NE301 文档",
        url="https://example.com/ne301",
        score=0.9,
        chunk_index=0,
    )


def _router_llm(intent_category="product"):
    return LLMRouter(
        providers={"fake": _FakeProvider(intent_category)},
        routing={
            "generation": [{"provider": "fake"}],
            "intent": [{"provider": "fake"}],
            "query_rewrite": [{"provider": "fake"}],
        },
    )


def _make_rag(llm, *, pruner=True, results=None):
    sr = results if results is not None else [_search_result()]
    searcher = MagicMock()
    searcher.search.return_value = sr
    searcher.search_symbols.return_value = []
    searcher.search_bucket.return_value = []
    reranker = MagicMock()
    reranker.rerank.return_value = sr

    class _P:
        async def prune(self, query, chunks):
            return chunks

    return RAGOrchestrator(
        searcher,
        reranker,
        llm,
        system_prompt="sys",
        pruner=_P() if pruner else None,
        min_results_to_answer=1,
    )


async def _collect_stream(rag, query):
    events = []
    async for chunk in rag.stream_answer(query, "widget"):
        events.append(json.loads(chunk))
    return events


@pytest.mark.unit
async def test_stream_trace_records_llm_calls_usage_split_timings():
    rag = _make_rag(_router_llm())
    events = await _collect_stream(rag, QUESTION)
    complete = [e for e in events if e["type"] == "complete"][0]
    trace = complete["trace_payload"]
    stages = trace["stages"]
    calls = trace["llm_calls"]

    tasks = [c["task"] for c in calls if not c.get("skipped")]
    assert "intent" in tasks
    # 无对话历史:rewrite_query 不触发 LLM(契约:history<2 直接返回)→ 仅 extract
    assert tasks.count("query_rewrite") == 1
    assert "generation" in tasks

    gen = [c for c in calls if c["task"] == "generation"][0]
    assert gen["success"] is True
    assert gen["complete"] is True
    assert gen["thinking"] == "disabled"
    assert gen["generation_chain_fallback"] is False
    assert gen["tokens_input"] == 7
    assert gen["tokens_output"] == 22
    assert isinstance(gen["latency_ms"], int)

    # INC-1 修正:流式 tokens_output = provider 实际用量(原为字符数)
    assert stages["generate"]["tokens_output"] == 22
    assert stages["generate"]["tokens_input"] == 7
    assert stages["generate"]["answer_chars"] == len(complete["answer"])

    # 计时分离 + 修剪独立延迟
    assert "extract_ms" in stages["rewrite"]
    assert "rewrite_ms" in stages["rewrite"]
    assert stages["rewrite"]["extract_ms"] >= 0
    assert stages["rewrite"]["rewrite_ms"] >= 0
    assert stages["rerank"]["prune_ms"] is not None


@pytest.mark.unit
async def test_stream_internal_only_evidence_generation_runs_with_real_usage():
    """仅内部证据命中:可见 sources=0 但生成照常 —— llm_calls 必须如实记录。"""
    internal = SearchResult(
        text="内部案例",
        source_id="case-1",
        source_type="filesystem",
        product="knowledge",
        title="内部案例",
        url="",
        score=0.9,
        chunk_index=0,
    )
    rag = _make_rag(_router_llm(), results=[internal])
    events = await _collect_stream(rag, QUESTION)
    complete = [e for e in events if e["type"] == "complete"][0]
    trace = complete["trace_payload"]
    assert complete["sources"] == []  # 访客不可见
    gen = [c for c in trace["llm_calls"] if c["task"] == "generation" and c.get("success")]
    assert gen, "内部证据参与生成时,generation 调用必须留痕"
    assert trace["stages"]["generate"]["tokens_output"] == 22
    assert trace["stages"]["generate"]["answer_chars"] == len(complete["answer"])


@pytest.mark.unit
async def test_stream_empty_retrieval_records_generation_skip():
    """检索完全为空 → no_evidence 拒答,generation 必须记录为 skipped。"""
    rag = _make_rag(_router_llm(), results=[])
    events = await _collect_stream(rag, QUESTION)
    complete = [e for e in events if e["type"] == "complete"][0]
    calls = complete["trace_payload"]["llm_calls"]
    skipped = {c["task"]: c.get("reason") for c in calls if c.get("skipped")}
    assert skipped.get("pruning") == "no_candidates"
    assert skipped.get("generation") == "insufficient_evidence_reject"


@pytest.mark.unit
async def test_off_topic_short_circuit_records_skips():
    rag = _make_rag(_router_llm("off_topic"))
    events = await _collect_stream(rag, "帮我写一首关于秋天的诗")
    complete = [e for e in events if e["type"] == "complete"][0]
    calls = complete["trace_payload"]["llm_calls"]
    skipped = {c["task"]: c.get("reason") for c in calls if c.get("skipped")}
    assert skipped.get("query_extraction") == "off_topic_short_circuit"
    assert skipped.get("generation") == "off_topic_short_circuit"
    assert complete["result_key"] == "off_topic"


@pytest.mark.unit
async def test_social_short_circuit_records_all_skipped():
    rag = _make_rag(_router_llm())
    events = await _collect_stream(rag, "你好")
    complete = [e for e in events if e["type"] == "complete"][0]
    calls = complete["trace_payload"]["llm_calls"]
    assert calls, "短路路径也必须留下跳过标记"
    assert all(c.get("skipped") for c in calls)
    assert any(c.get("reason") == "smalltalk_short_circuit" for c in calls)


@pytest.mark.unit
async def test_answer_path_records_llm_calls_and_split_timings():
    rag = _make_rag(_router_llm())
    result = await rag.answer(QUESTION, "widget")
    trace = result.trace_payload
    calls = trace["llm_calls"]
    assert any(c["task"] == "generation" and c.get("success") for c in calls)
    assert "extract_ms" in trace["stages"]["rewrite"]
    assert "rewrite_ms" in trace["stages"]["rewrite"]
    assert trace["stages"]["generate"]["tokens_input"] == 11
    assert trace["stages"]["generate"]["tokens_output"] == 7


@pytest.mark.unit
async def test_inc1_attribution_demo():
    """归因演示:同一请求的 Trace 现已包含区分 K3/K4/K6/K7 所需的元数据。

    - K3(检索): retrieve.path_counts + 候选;
    - K4(重排/剪枝): rerank.prune_ms + pruned;
    - K6(组合): citation_integrity 统计(public/background);
    - K7(生成): llm_calls generation 事件(provider/model/latency/token/thinking)。
    """
    rag = _make_rag(_router_llm())
    events = await _collect_stream(rag, QUESTION)
    complete = [e for e in events if e["type"] == "complete"][0]
    stages = complete["trace_payload"]["stages"]

    assert {"ms", "path_counts"} <= set(stages["retrieve"])  # K3
    assert {"pruned", "prune_ms"} <= set(stages["rerank"])  # K4
    assert {"public_chunks", "background_chunks"} <= set(stages["citation_integrity"])  # K6
    gen = [c for c in complete["trace_payload"]["llm_calls"] if c["task"] == "generation"][0]
    assert {"provider", "model", "latency_ms", "tokens_output", "success"} <= set(gen)  # K7
