"""INC-7 流式 trace parity 矫正契约测试(Production Gate FAIL 唯一败项 H)。

背景(生产门 RCA,docs ecd55aa):stream 的 complete 事件 trace_payload 显式
枚举 stages 键,漏 `response_strategy` → 生产唯一应答面(流式)上 INC-7 观测
结构性缺失,违反 INC-7 冻结契约 §Trace/§Answer-Stream-Parity。

冻结矫正边界:
- 只补投影,不改派生/编译/生成行为(NEW_LLM_CALLS=0);
- 有界四字段,零正文/零推理/零新字段;
- 抑制路径(comparison/lead 权威轮)保持缺席;
- answer/stream 语义等价。
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

import backend.pipeline.rag as rag_module
from backend.pipeline.lead_qualify import LeadTurnContext
from backend.pipeline.rag import RAGOrchestrator
from backend.retrieval.search import SearchResult

EXPECTED_STRATEGY = {
    "response_frame": "factual_lookup",
    "directness": "concise_direct",
    "coverage_framing": "none",
    "gap_labels": [],
}


def _sr(source_id: str, product: str = "ne503", title: str = "NE503", text: str = "接口 RS485。"):
    return SearchResult(
        text=text,
        source_id=source_id,
        source_type="website",
        product=product,
        title=title,
        url=f"https://example.com/{source_id}",
        score=0.9,
        chunk_index=0,
    )


def _rag() -> RAGOrchestrator:
    """与 INC-6 契约测试同构的管线级 fixture(同源 mock 管线供 answer/stream 共用)。"""
    candidates = [_sr("site/ne503-spec"), _sr("site/ne503-guide")]
    searcher = MagicMock()
    searcher.search.return_value = list(candidates)
    searcher.search_symbols.return_value = []
    searcher.search_bucket.return_value = []
    reranker = MagicMock()
    reranker.rerank.side_effect = lambda q, results, top_k=None: list(results)[: top_k or 10]
    reranker.rerank_scored.side_effect = lambda q, results, top_k=None: (list(results)[: top_k or 10], [])
    llm = AsyncMock()

    async def _generate(messages, **kwargs):
        task = kwargs.get("task", "generation")
        if task in ("intent", "task_understanding"):
            payload = {
                "category": "product",
                "reason": "probe",
                "confidence": 0.9,
                "interaction_mode": "standard",
                "evidence_intent": "factual",
                "extracted_query": "NE503 接口",
                "rewritten_query": "NE503 接口",
            }
            return MagicMock(content=json.dumps(payload, ensure_ascii=False))
        if task == "lead_qualifier":
            return MagicMock(content="{}")
        return MagicMock(content="NE503 提供 RS485 接口 [1]。")

    llm.generate = AsyncMock(side_effect=_generate)

    async def _stream(messages, **kwargs):
        yield "NE503 提供 RS485 接口 [1]。"

    llm.stream = _stream
    return RAGOrchestrator(
        searcher,
        reranker,
        llm,
        system_prompt="s",
        min_results_to_answer=1,
    )


async def _collect_stream(rag: RAGOrchestrator, **kwargs) -> list[dict]:
    events = []
    async for raw in rag.stream_answer(**kwargs):
        events.append(json.loads(raw))
    return events


def _complete(events: list[dict]) -> dict:
    for evt in events:
        if evt.get("type") == "complete":
            return evt
    raise AssertionError("stream 未产出 complete 事件")


@pytest.mark.asyncio
@pytest.mark.unit
async def test_red_stream_complete_trace_exposes_response_strategy():
    """RED-A/B/C:适用流式生成路径的 complete trace 必须暴露有界四字段策略。"""
    rag = _rag()
    events = await _collect_stream(rag, query="NE503 有哪些接口?")
    complete = _complete(events)
    stages = complete["trace_payload"]["stages"]
    assert stages["response_strategy"] == EXPECTED_STRATEGY


@pytest.mark.asyncio
@pytest.mark.unit
async def test_answer_stream_strategy_parity():
    """RED-D:等价输入下 answer 与 stream 暴露等价 ResponseStrategy 语义。"""
    rag = _rag()
    result = await rag.answer(query="NE503 有哪些接口?")
    answer_strategy = result.trace_payload["stages"]["response_strategy"]
    events = await _collect_stream(rag, query="NE503 有哪些接口?")
    stream_strategy = _complete(events)["trace_payload"]["stages"]["response_strategy"]
    assert answer_strategy == stream_strategy


@pytest.mark.asyncio
@pytest.mark.unit
async def test_lead_invite_turn_stream_trace_stays_suppressed():
    """E(回归守卫,基线即绿):lead 权威轮(明确销售信号→邀请)流式 trace 保持无策略段。"""
    rag = _rag()
    lead_ctx = LeadTurnContext(session_id="smoke", explicit_sales_hint=True)
    events = await _collect_stream(rag, query="NE503 有哪些接口?", lead_ctx=lead_ctx)
    complete = _complete(events)
    stages = complete["trace_payload"]["stages"]
    assert "response_strategy" not in stages
    assert stages["lead"]["instruction"]  # lead 权威指令在场(邀请)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_stream_reservation_stages_are_sanitized_and_match_answer(monkeypatch):
    """流式仅公开 reservation/retention 汇总，不把 Trace 身份元数据外发。"""
    private_info = {
        "promotions": [
            {"rule": "R1_required_slot_target", "role": "solution_guide", "target": "ne503",
             "source_id": "private/source", "chunk_index": 42, "score": 0.17},
            {"rule": "R2_page_completion", "role": "product_spec", "target": "ne503",
             "source_id": "private/source2", "chunk_index": 43, "score": 0.87},
        ],
        "solution_retention": [
            {"source_id": "private/source", "chunk_index": 42},
        ],
        "internal_debug": "secret-marker",
    }

    async def fake_reserve(*args, **kwargs):
        return [], private_info

    monkeypatch.setattr(rag_module, "reserve_plan_evidence", fake_reserve)
    rag = _rag()
    rag._reranker.rerank_scored.side_effect = lambda q, results, top_k=None: (
        list(results)[: top_k or 10], [(r, r.score) for r in results]
    )
    result = await rag.answer(query="NE503 有哪些接口?")
    events = await _collect_stream(rag, query="NE503 有哪些接口?")
    answer_stages = result.trace_payload["stages"]
    stream_stages = _complete(events)["trace_payload"]["stages"]

    assert stream_stages["evidence_reservation"] == {
        "promotion_count": 2,
        "promotion_roles": {"solution_guide": 1, "product_spec": 1},
        "checks_not_fired": 0,
    }
    assert stream_stages["solution_retention"] == {"retained_count": 1}
    assert answer_stages["evidence_reservation"]["promotions"] == private_info["promotions"]
    assert answer_stages["evidence_reservation"]["solution_retention"] == private_info["solution_retention"]
    assert "private/source" not in json.dumps(stream_stages)
    assert "secret-marker" not in json.dumps(stream_stages)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("events", "expected"),
    [
        (
            [{"rule": "R3_spec_rescue", "fired": False, "reason": "slot_met"}],
            {"promotion_count": 0, "promotion_roles": {}, "checks_not_fired": 1},
        ),
        (
            [
                {"rule": "R1_required_slot_target", "role": "solution_guide", "target": "ne503",
                 "source_id": "private/r1", "chunk_index": 2, "score": 0.4},
                {"rule": "R2_page_completion", "role": "product_spec", "target": "ne503",
                 "source_id": "private/r2", "chunk_index": 3, "score": 0.8},
                {"rule": "R3_spec_rescue", "fired": False, "reason": "slot_met"},
            ],
            {"promotion_count": 2,
             "promotion_roles": {"product_spec": 1, "solution_guide": 1},
             "checks_not_fired": 1},
        ),
    ],
)
def test_public_reservation_trace_counts_only_successful_res_info_events(events, expected):
    """真实 R1/R2/R3 audit 事件形状不会把未触发检查算作晋升。"""
    raw = {"promotions": events, "solution_retention": [
        {"source_id": "private/retained", "chunk_index": 9}
    ]}
    public = rag_module._public_reservation_trace({"evidence_reservation": raw})
    assert public["evidence_reservation"] == expected
    assert public["solution_retention"] == {"retained_count": 1}
    assert "private/" not in json.dumps(public)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_stream_reservation_stages_are_absent_when_not_run():
    events = await _collect_stream(_rag(), query="NE503 有哪些接口?")
    stages = _complete(events)["trace_payload"]["stages"]
    assert "evidence_reservation" not in stages
    assert "solution_retention" not in stages
