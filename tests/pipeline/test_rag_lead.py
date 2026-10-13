"""RAGOrchestrator × Lead Capture 集成测试。

在管线层证明产品语义(LEAD-G001~G005):
- 普通/潜在线索轮不内嵌邀请指令(G001);
- qualified 轮先正常回答再追加邀请指令(G002/G003);
- One-Proactive-Ask:已邀请过不再邀请,更强信号才再邀请(G005/契约 §7);
- 联系方式捕获轮:off_topic 不拒答、确认指令内嵌、空检索也生成(G004);
- qualifier 失败 fail-open,确定性 explicit_sales_hint 仍触发邀请;
- 无 lead_ctx 时行为与基线完全一致(G012 回归面)。
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.llm.base import LLMResponse
from backend.pipeline.lead_qualify import (
    LEAD_ACK_INSTRUCTION,
    LEAD_INVITE_INSTRUCTION,
    ContactHit,
    LeadTurnContext,
)
from backend.pipeline.rag import RAGOrchestrator
from backend.retrieval.search import SearchResult

QUALIFIED_JSON = json.dumps(
    {
        "lead_level": "qualified",
        "explicit_sales_request": False,
        "stronger_signal": False,
        "fields": {"company": "Acme", "quantity": "500 units"},
        "summary": "Acme 要 500 台",
    },
    ensure_ascii=False,
)
POTENTIAL_JSON = json.dumps({"lead_level": "potential"}, ensure_ascii=False)


def _resp(content: str) -> LLMResponse:
    return LLMResponse(content=content, model="t", tokens_input=1, tokens_output=1, latency_ms=1)


def _make_lead_llm(*, intent="commercial", qualification=QUALIFIED_JSON, answer="正常回答"):
    """按 task 关键字分发的 mock LLM,规避多次 generate 的顺序耦合。

    返回 (llm, streamed_messages)——streamed_messages 记录每次流式生成
    收到的 messages(邀请/确认指令断言用)。
    """
    llm = AsyncMock()
    streamed: list[list[dict]] = []

    async def _generate(messages, **kwargs):
        task = kwargs.get("task", "generation")
        if task == "intent":
            return _resp(json.dumps({"category": intent, "reason": "r", "confidence": 0.9}))
        if task == "lead_qualification":
            return _resp(qualification)
        if task == "query_rewrite":
            return _resp("rewritten")
        return _resp(answer)

    llm.generate = AsyncMock(side_effect=_generate)

    async def _stream(messages, **kwargs):
        streamed.append(messages)
        yield "正常"
        yield "回答"

    llm.stream = _stream
    return llm, streamed


def _make_rag(llm, *, results=None):
    sr = SearchResult(
        text="doc",
        source_id="s",
        source_type="woocommerce",
        product="ne503",
        title="T",
        url="https://e.com",
        score=0.9,
        chunk_index=0,
    )
    searcher = MagicMock()
    searcher.search.return_value = results if results is not None else [sr]
    searcher.search_symbols.return_value = []
    searcher.search_bucket.return_value = []
    reranker = MagicMock()
    reranker.rerank.return_value = results if results is not None else [sr]
    reranker.rerank_scored.return_value = (results if results is not None else [sr], [])
    reranker.rerank_scored.return_value = (results if results is not None else [sr], [])
    return RAGOrchestrator(searcher, reranker, llm, system_prompt="sys")


def _ctx(**kw) -> LeadTurnContext:
    return LeadTurnContext(session_id="sess-1", **kw)


async def _collect(rag, query, **kwargs):
    events = []
    async for chunk in rag.stream_answer(query, "widget", **kwargs):
        events.append(json.loads(chunk))
    return events


@pytest.mark.unit
async def test_qualified_appends_invite_after_full_answer():
    """G002/G003:qualified → 生成消息带邀请指令,complete 带 invited=True。"""
    llm, streamed = _make_lead_llm(intent="commercial")
    rag = _make_rag(llm)
    events = await _collect(rag, "我们需要 500 台,请给正式报价", lead_ctx=_ctx())
    complete = events[-1]
    assert complete["is_answered"] is True
    assert complete["lead"]["invited"] is True
    assert complete["lead"]["level"] == "qualified"
    assert complete["lead"]["fields"]["company"] == "Acme"

    assert LEAD_INVITE_INSTRUCTION in streamed[-1][0]["content"]


@pytest.mark.unit
async def test_potential_no_invite():
    """G001:potential(含询价)不内嵌邀请指令。"""
    llm, streamed = _make_lead_llm(intent="product", qualification=POTENTIAL_JSON)
    rag = _make_rag(llm)
    events = await _collect(rag, "NE503 多少钱?", lead_ctx=_ctx())
    assert events[-1]["lead"]["invited"] is False
    system_msg = streamed[-1][0]["content"]
    assert LEAD_INVITE_INSTRUCTION not in system_msg
    assert LEAD_ACK_INSTRUCTION not in system_msg


@pytest.mark.unit
async def test_bulk_pricing_is_qualified_even_when_llm_says_none():
    llm, _ = _make_lead_llm(
        intent="commercial", qualification=json.dumps({"lead_level": "none"})
    )
    rag = _make_rag(llm)
    events = await _collect(rag, "What are your bulk prices?", lead_ctx=_ctx())
    assert events[-1]["lead"]["level"] == "qualified"
    assert events[-1]["lead"]["invited"] is True
    assert events[-1]["trace_payload"]["stages"]["lead"]["qualification_status"] == "fallback"


@pytest.mark.unit
async def test_bulk_pricing_does_not_use_deterministic_fallback_when_qualifier_fails():
    llm, _ = _make_lead_llm(intent="commercial")
    original_generate = llm.generate

    async def _generate(messages, **kwargs):
        if kwargs.get("task") == "lead_qualification":
            raise RuntimeError("qualifier unavailable")
        return await original_generate(messages, **kwargs)

    llm.generate = AsyncMock(side_effect=_generate)
    rag = _make_rag(llm)
    events = await _collect(rag, "What are your bulk prices?", lead_ctx=_ctx())
    assert events[-1]["lead"]["ran"] is False
    assert events[-1]["lead"]["level"] == "none"
    assert events[-1]["lead"]["invited"] is False
    assert events[-1]["trace_payload"]["stages"]["lead"]["qualification_status"] == "failed"


@pytest.mark.unit
@pytest.mark.parametrize(
    "query",
    [
        "What are your bulk prices?",
        "Price for 120 pcs?",
        "Please provide a formal quotation for our project",
        "We have a project requirement for warehouse deployment",
        "We are looking for a distributor partnership",
        "We will purchase next quarter",
    ],
)
async def test_strong_purchase_signals_still_qualify_and_invite_after_answer(query):
    llm, streamed = _make_lead_llm(
        intent="commercial", qualification=json.dumps({"lead_level": "none"})
    )
    rag = _make_rag(llm)
    events = await _collect(rag, query, lead_ctx=_ctx())
    assert events[-1]["is_answered"] is True
    assert events[-1]["lead"]["level"] == "qualified"
    assert events[-1]["lead"]["invited"] is True
    assert LEAD_INVITE_INSTRUCTION in streamed[-1][0]["content"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "query",
    [
        "Can I buy in Chile?",
        "Where can I buy in Australia?",
        "Quote from the user manual",
        "Please quote the source code",
        "What is the purchase timeline?",
        "采购时间表是什么？",
    ],
)
async def test_information_queries_with_purchase_words_do_not_upgrade_or_invite(query):
    llm, streamed = _make_lead_llm(
        intent="commercial", qualification=json.dumps({"lead_level": "none"})
    )
    rag = _make_rag(llm)
    events = await _collect(rag, query, lead_ctx=_ctx())
    assert events[-1]["lead"]["level"] == "none"
    assert events[-1]["lead"]["invited"] is False
    assert LEAD_INVITE_INSTRUCTION not in streamed[-1][0]["content"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "query",
    [
        "Can I buy in Chile?",
        "Where can I buy in Australia?",
        "Please quote the source code",
        "What is the purchase timeline?",
    ],
)
async def test_information_query_qualifier_failure_does_not_use_purchase_fallback(query):
    llm, _ = _make_lead_llm(intent="commercial")
    original_generate = llm.generate

    async def _generate(messages, **kwargs):
        if kwargs.get("task") == "lead_qualification":
            raise RuntimeError("qualifier unavailable")
        return await original_generate(messages, **kwargs)

    llm.generate = AsyncMock(side_effect=_generate)
    rag = _make_rag(llm)
    events = await _collect(rag, query, lead_ctx=_ctx())
    assert events[-1]["lead"]["level"] == "none"
    assert events[-1]["lead"]["invited"] is False
    assert events[-1]["lead"]["ran"] is False


@pytest.mark.unit
async def test_qualification_trace_distinguishes_failure_from_real_none():
    llm, _ = _make_lead_llm(intent="commercial", qualification="not json")
    rag = _make_rag(llm)
    failed = await _collect(rag, "What is NE503?", lead_ctx=_ctx())
    failed_stage = failed[-1]["trace_payload"]["stages"]["lead"]
    assert failed_stage["qualification_status"] == "failed"

    llm, _ = _make_lead_llm(intent="commercial", qualification=json.dumps({"lead_level": "none"}))
    rag = _make_rag(llm)
    none = await _collect(rag, "What is NE503?", lead_ctx=_ctx())
    none_stage = none[-1]["trace_payload"]["stages"]["lead"]
    assert none_stage["qualification_status"] == "completed"
    assert none_stage["level"] == "none"


@pytest.mark.unit
@pytest.mark.parametrize("streaming", [False, True])
async def test_clarification_path_records_purchase_qualification(monkeypatch, streaming):
    from backend.pipeline import rag as rag_module
    from backend.pipeline.task_understanding import MODE_CLARIFICATION, TaskUnderstanding

    async def _clarify(*args, **kwargs):
        return TaskUnderstanding(
            category="commercial",
            interaction_mode=MODE_CLARIFICATION,
            extracted_query="What are your bulk prices?",
            rewritten_query="What are your bulk prices?",
        )

    monkeypatch.setattr(rag_module, "understand_task", _clarify)
    llm, _ = _make_lead_llm(intent="commercial")
    rag = _make_rag(llm)
    if streaming:
        events = await _collect(rag, "What are your bulk prices?", lead_ctx=_ctx())
        trace = events[-1]["trace_payload"]
    else:
        answer = await rag.answer("What are your bulk prices?", "widget", lead_ctx=_ctx())
        trace = answer.trace_payload
    assert trace["stages"]["lead"]["level"] == "qualified"
    assert trace["stages"]["lead"]["instruction"] is None


@pytest.mark.unit
async def test_ineligible_support_turn_has_explainable_lead_skip(monkeypatch):
    from backend.pipeline import rag as rag_module
    from backend.pipeline.task_understanding import MODE_STANDARD, TaskUnderstanding

    async def _support(*args, **kwargs):
        return TaskUnderstanding(
            category="support",
            interaction_mode=MODE_STANDARD,
            extracted_query="NE301 firmware issue",
            rewritten_query="NE301 firmware issue",
        )

    monkeypatch.setattr(rag_module, "understand_task", _support)
    llm, _ = _make_lead_llm(intent="support")
    rag = _make_rag(llm)
    answer = await rag.answer("NE301 firmware issue", "widget", lead_ctx=_ctx())
    stage = answer.trace_payload["stages"]["lead"]
    assert stage["qualification_status"] == "skipped"
    assert stage["skip_reason"] == "intent_not_eligible"


@pytest.mark.unit
async def test_one_proactive_ask_second_turn_no_reinvite():
    """G005:已邀请过(prompt_count=1)且无更强信号 → 不再邀请。"""
    llm, _ = _make_lead_llm(intent="commercial")
    rag = _make_rag(llm)
    ctx = _ctx(has_lead=True, prompt_count=1, status="qualified")
    events = await _collect(rag, "还是想了解报价", lead_ctx=ctx)
    assert events[-1]["lead"]["invited"] is False


@pytest.mark.unit
async def test_stronger_signal_allows_one_reinvite():
    """契约 §7:实质更强信号允许再邀请一次(上限 2)。"""
    stronger = json.dumps({"lead_level": "qualified", "stronger_signal": True}, ensure_ascii=False)
    llm, _ = _make_lead_llm(intent="commercial", qualification=stronger)
    rag = _make_rag(llm)
    ctx = _ctx(has_lead=True, prompt_count=1, status="qualified")
    events = await _collect(rag, "数量加到 2000 台,下个月就要", lead_ctx=ctx)
    assert events[-1]["lead"]["invited"] is True

    ctx_capped = _ctx(has_lead=True, prompt_count=2, status="qualified")
    events2 = await _collect(rag, "数量加到 5000 台", lead_ctx=ctx_capped)
    assert events2[-1]["lead"]["invited"] is False


@pytest.mark.unit
async def test_capture_mode_bypasses_off_topic_and_acks():
    """G004:补联系方式轮即使被判 off_topic 也不拒答,内嵌确认指令。"""
    llm, streamed = _make_lead_llm(intent="off_topic", answer="已记录")
    rag = _make_rag(llm, results=[])  # 空检索也必须生成
    rag._reranker.rerank.return_value = []
    ctx = _ctx(
        has_lead=True,
        status="qualified",
        contact=ContactHit(type="email", value="john@example.com", masked="j***@example.com"),
    )
    events = await _collect(rag, "john@example.com", lead_ctx=ctx)
    complete = events[-1]
    assert complete["is_answered"] is True  # 未被 off_topic 拒答
    assert complete["lead"]["ack"] is True
    assert LEAD_ACK_INSTRUCTION in streamed[-1][0]["content"]


@pytest.mark.unit
async def test_capture_trace_is_pii_safe():
    """契约 §14:trace 的 lead 阶段只有 type+masked,绝无联系方式原文。"""
    llm, _ = _make_lead_llm(intent="off_topic")
    rag = _make_rag(llm, results=[])
    rag._reranker.rerank.return_value = []
    ctx = _ctx(
        contact=ContactHit(type="email", value="john@example.com", masked="j***@example.com")
    )
    events = await _collect(rag, "john@example.com", lead_ctx=ctx)
    trace = events[-1]["trace_payload"]
    assert "john@example.com" not in json.dumps(trace, ensure_ascii=False)
    assert trace["stages"]["lead"]["contact"] == {"type": "email", "masked": "j***@example.com"}


@pytest.mark.unit
async def test_qualifier_fail_open_with_explicit_hint_still_invites():
    """qualifier 异常 fail-open;确定性「转人工/要求报价」短语仍触发邀请。"""
    llm, _ = _make_lead_llm(intent="commercial")
    orig_generate = llm.generate

    async def _generate(messages, **kwargs):
        if kwargs.get("task") == "lead_qualification":
            raise RuntimeError("llm down")
        return await orig_generate(messages, **kwargs)

    llm.generate = AsyncMock(side_effect=_generate)

    rag = _make_rag(llm)
    ctx = _ctx(explicit_sales_hint=True)
    events = await _collect(rag, "请转接人工销售", lead_ctx=ctx)
    assert events[-1]["lead"]["invited"] is True
    assert events[-1]["lead"]["ran"] is False


@pytest.mark.unit
async def test_reject_path_still_reports_lead_payload():
    """qualified 信号在检索为空拒答时不丢失(invited=False,因未展示邀请)。"""
    llm, _ = _make_lead_llm(intent="commercial")
    rag = _make_rag(llm, results=[])
    rag._reranker.rerank.return_value = []
    events = await _collect(rag, "请报 500 台的价格", lead_ctx=_ctx())
    complete = events[-1]
    assert complete["is_answered"] is False
    assert complete["lead"]["level"] == "qualified"
    assert complete["lead"]["invited"] is False
    assert complete["trace_payload"]["stages"]["lead"]["qualification_status"] == "completed"

    llm, _ = _make_lead_llm(intent="commercial")
    rag = _make_rag(llm, results=[])
    rag._reranker.rerank.return_value = []
    result = await rag.answer("请报 500 台的价格", "widget", lead_ctx=_ctx())
    assert result.trace_payload["stages"]["lead"]["level"] == "qualified"


@pytest.mark.unit
async def test_no_lead_ctx_baseline_unchanged():
    """G012 回归面:无 lead_ctx 时行为与基线一致(无 lead 阶段/指令)。"""
    llm, streamed = _make_lead_llm(intent="commercial")
    rag = _make_rag(llm)
    events = await _collect(rag, "NE503 报价多少?")
    complete = events[-1]
    assert complete["lead"] is None
    assert "lead" not in complete["trace_payload"]["stages"]
    assert LEAD_INVITE_INSTRUCTION not in streamed[-1][0]["content"]
    # 不应发起 lead_qualification 调用
    tasks = [c.kwargs.get("task") for c in llm.generate.call_args_list]
    assert "lead_qualification" not in tasks


@pytest.mark.unit
async def test_sync_answer_parity_invite():
    """answer() 同步路径与流式同语义:qualified → 邀请指令内嵌。"""
    llm, _ = _make_lead_llm(intent="commercial")
    rag = _make_rag(llm)
    result = await rag.answer("批量采购请报价", "widget", lead_ctx=_ctx())
    assert result.is_answered is True
    gen_call = next(c for c in llm.generate.call_args_list if c.kwargs.get("task") == "generation")
    assert LEAD_INVITE_INSTRUCTION in gen_call.args[0][0]["content"]
    assert "lead" in result.trace_payload["stages"]


@pytest.mark.unit
async def test_english_lead_flow_invite():
    """LEAD-G015:英文强信号会话同样触发邀请(指令要求跟随回答语言)。"""
    en_qual = json.dumps(
        {
            "lead_level": "qualified",
            "explicit_sales_request": False,
            "stronger_signal": False,
            "fields": {"company": "Acme", "quantity": "500 units", "timeline": "next month"},
            "summary": "Acme 需 500 台,下月采购",
        },
        ensure_ascii=False,
    )
    llm, streamed = _make_lead_llm(intent="commercial", qualification=en_qual)
    rag = _make_rag(llm)
    events = await _collect(
        rag, "We need 500 units for our project, please send a formal quotation", lead_ctx=_ctx()
    )
    complete = events[-1]
    assert complete["lead"]["invited"] is True
    assert complete["lead"]["level"] == "qualified"
    assert complete["lead"]["fields"]["quantity"] == "500 units"
    assert LEAD_INVITE_INSTRUCTION in streamed[-1][0]["content"]
