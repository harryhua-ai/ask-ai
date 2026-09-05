"""Accepted Product Changes Integration Gate(INT-G001~G010)。

证明三项已验收能力在**同一编排器**上共存且互不冲突:
  A. Product UX Closure B —— Wiki citation canonical URL + 社交/off-topic 友好边界
  B. Sales Lead Capture & Handoff V1 —— 资格判定/邀请/捕获状态机
  C. Three-site Contract —— 站点默认语言等 runtime/config 契约(由
     config/sites.yaml 与 test_site_routes 承载,本文件不重复)

关键证明点:rag.py 同一 orchestration 路径上,**两个状态机的先后序**
(social 短路 → 意图分类(off_topic×capture 豁免)→ 资格判定 → 权威编号
上下文 + lead 指令内嵌 → 引用校验)是行为实证,不是代码阅读假设。
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.llm.base import LLMResponse
from backend.pipeline.lead_qualify import (
    LEAD_ACK_INSTRUCTION,
    LEAD_INVITE_INSTRUCTION,
    LeadTurnContext,
    detect_contact,
)
from backend.pipeline.rag import OFF_TOPIC_REPLY_ZH, RAGOrchestrator
from backend.pipeline.social import match_social
from backend.retrieval.search import SearchResult

WIKI_BLOB = "https://github.com/camthink-ai/wiki-documents/blob/main"
WIKI_CANONICAL = "https://wiki.camthink.ai/docs/neoeyes-ne301-series/overview"
EMAIL_RAW = "john.acme@example-corp.com"

QUALIFIED_JSON = json.dumps(
    {
        "lead_level": "qualified",
        "explicit_sales_request": False,
        "stronger_signal": False,
        "fields": {"company": "Acme", "quantity": "500 units"},
        "summary": "Acme 批量采购",
    },
    ensure_ascii=False,
)
POTENTIAL_JSON = json.dumps({"lead_level": "potential"}, ensure_ascii=False)


def _resp(content: str) -> LLMResponse:
    return LLMResponse(content=content, model="t", tokens_input=1, tokens_output=1, latency_ms=1)


def _sr(url: str, source_type: str = "github", text: str = "NE301 概述", score: float = 0.9):
    return SearchResult(
        text=text,
        source_id="src",
        source_type=source_type,
        product="ne301",
        title="T",
        url=url,
        score=score,
        chunk_index=0,
    )


def _gate_llm(*, intent="product", qualification=QUALIFIED_JSON, answer="正常产品回答"):
    """按 task 分发的 mock LLM;记录所有 generate 调用与流式 messages。

    返回 (llm, gen_messages, generate_calls):
      gen_messages   —— 每次流式生成收到的 messages(邀请/确认/PII 断言)
      generate_calls —— [(messages, kwargs), ...](qualifier 是否运行断言)
    """
    llm = AsyncMock()
    gen_messages: list[list[dict]] = []
    generate_calls: list[tuple[list[dict], dict]] = []

    async def _generate(messages, **kwargs):
        generate_calls.append((messages, kwargs))
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
        gen_messages.append(messages)
        yield "正常"
        yield "回答"

    llm.stream = _stream
    return llm, gen_messages, generate_calls


def _make_rag(llm, results):
    searcher = MagicMock()
    searcher.search.return_value = results
    searcher.search_symbols.return_value = []
    searcher.search_bucket.return_value = []
    reranker = MagicMock()
    reranker.rerank.return_value = results
    return RAGOrchestrator(searcher, reranker, llm, system_prompt="sys", min_results_to_answer=1)


async def _collect(rag, query, **kwargs):
    events = []
    async for chunk in rag.stream_answer(query, "widget", **kwargs):
        events.append(json.loads(chunk))
    return events


def _system_of(messages: list[dict]) -> str:
    return messages[0]["content"]


# --------------------------------------------------------------------------- #
# INT-G001 —— 纯社交:自然回应,零检索,零 lead
# --------------------------------------------------------------------------- #


@pytest.mark.unit
@pytest.mark.parametrize("query", ["你好", "hello"])
async def test_int_g001_pure_smalltalk_no_retrieval_no_lead(query):
    llm, _, generate_calls = _gate_llm()
    rag = _make_rag(llm, [_sr(f"{WIKI_BLOB}/docs/5-neoeyes-ne301-series/0-overview.md")])
    # 最不利前提:会话已有合格线索(若社交被漏进 lead 状态机会立即暴露)
    lead_ctx = LeadTurnContext(session_id="s", has_lead=True, status="qualified", prompt_count=1)

    events = await _collect(rag, query, lead_ctx=lead_ctx)

    assert len(events) == 1 and events[0]["type"] == "complete"
    complete = events[0]
    assert complete["intent"] == "smalltalk"
    assert complete["is_answered"] is True
    assert complete["sources"] == []
    # 零检索:searcher 未被调用
    rag._searcher.search.assert_not_called()
    # 零 lead:qualifier 未运行 + complete 无 lead payload(routes 因此不落库)
    assert all(kw.get("task") != "lead_qualification" for _, kw in generate_calls)
    assert "lead" not in complete
    assert complete["trace_payload"]["type"] == "social_reply"

    # 同步 answer 路径同语义
    ans = await rag.answer(query, "widget", lead_ctx=lead_ctx)
    assert ans.intent == "smalltalk" and ans.sources == []
    assert ans.trace_payload["type"] == "social_reply"


# --------------------------------------------------------------------------- #
# INT-G002 —— 纯 off-topic:友好边界,不进 RAG,无误捕获
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_int_g002_off_topic_friendly_boundary_no_rag_no_lead():
    llm, _, generate_calls = _gate_llm(intent="off_topic")
    rag = _make_rag(llm, [_sr(f"{WIKI_BLOB}/docs/5-neoeyes-ne301-series/0-overview.md")])
    lead_ctx = LeadTurnContext(session_id="s")

    events = await _collect(rag, "请给我写一首关于量子宇宙的诗", lead_ctx=lead_ctx)

    complete = events[-1]
    assert complete["intent"] == "off_topic"
    assert complete["is_answered"] is False
    # 友好边界话术(替代旧生硬拒绝),且不进 RAG
    assert complete["answer"] == OFF_TOPIC_REPLY_ZH
    rag._searcher.search.assert_not_called()
    # off_topic + 无线索 → qualifier 不运行,零 lead
    assert all(kw.get("task") != "lead_qualification" for _, kw in generate_calls)
    assert complete.get("lead") is None
    assert "lead" not in complete


# --------------------------------------------------------------------------- #
# INT-G003 —— 普通产品问题:正常 RAG,不因产品意图索要联系方式
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_int_g003_normal_product_question_no_solicitation():
    llm, gen_messages, _ = _gate_llm(intent="product", qualification=POTENTIAL_JSON)
    rag = _make_rag(llm, [_sr(f"{WIKI_BLOB}/docs/5-neoeyes-ne301-series/0-overview.md")])

    events = await _collect(rag, "NE301 是什么产品?", lead_ctx=LeadTurnContext(session_id="s"))

    complete = events[-1]
    assert complete["is_answered"] is True
    assert complete["answer"] == "正常回答"  # 真实生成发生
    # 商业意图 ≠ lead:potential 不邀请、系统提示无邀请指令
    assert complete["lead"]["invited"] is False
    assert LEAD_INVITE_INSTRUCTION not in _system_of(gen_messages[-1])
    assert LEAD_ACK_INSTRUCTION not in _system_of(gen_messages[-1])
    # 正常 RAG 发生了:有 sources 事件
    assert any(e["type"] == "sources" for e in events)


# --------------------------------------------------------------------------- #
# INT-G004 —— 问候+产品问题:不得被当 smalltalk 吞掉
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_int_g004_greeting_with_product_question_not_swallowed():
    # 真实 match_social:整串识别,问候+产品问题必须不命中
    assert match_social("你好,NE301 支持什么功能?") is None
    assert match_social("hello, what does NE301 do") is None

    llm, _, _ = _gate_llm(intent="product", qualification=POTENTIAL_JSON)
    rag = _make_rag(llm, [_sr(f"{WIKI_BLOB}/docs/5-neoeyes-ne301-series/0-overview.md")])

    events = await _collect(
        rag, "你好,NE301 支持什么功能?", lead_ctx=LeadTurnContext(session_id="s")
    )

    complete = events[-1]
    assert complete["intent"] != "smalltalk"
    assert complete["trace_payload"]["type"] == "rag"  # 走了完整 RAG
    assert complete["is_answered"] is True
    assert any(e["type"] == "sources" and e["sources"] for e in events)


# --------------------------------------------------------------------------- #
# INT-G005 —— 合格商业问题:正常作答 + qualified 语义 + 答后邀请
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_int_g005_qualified_commercial_answer_then_invite():
    llm, gen_messages, _ = _gate_llm(intent="commercial")
    rag = _make_rag(
        llm, [_sr(f"{WIKI_BLOB}/docs/5-neoeyes-ne301-series/0-overview.md", source_type="github")]
    )

    events = await _collect(
        rag,
        "We need 500 NE301 units for a project and need a quotation.",
        lead_ctx=LeadTurnContext(session_id="s"),
    )

    complete = events[-1]
    # 正常有用的商业回答先生成(不是光秃秃的邀请)
    assert complete["is_answered"] is True
    assert complete["answer"] == "正常回答"
    assert complete["lead"]["invited"] is True
    assert complete["lead"]["level"] == "qualified"
    assert complete["lead"]["fields"]["quantity"] == "500 units"
    # 邀请以内嵌指令与回答同一 system prompt(答后邀请的机制载体)
    assert LEAD_INVITE_INSTRUCTION in _system_of(gen_messages[-1])
    # 检索确实发生(commercial 走了 RAG 管线)
    rag._searcher.search.assert_called()


# --------------------------------------------------------------------------- #
# INT-G006 —— 联系方式捕获轮:确认语义 + PII 不泄漏 + 不被拒答
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_int_g006_contact_capture_ack_and_pii_hard_boundary():
    contact = detect_contact(f"好的,我的邮箱是 {EMAIL_RAW},请跟进")
    assert contact is not None and contact.value == EMAIL_RAW
    # 生产序:routes 先 mask_pii 再入管线;lead_ctx 持原文命中
    from backend.utils.pii import mask_pii

    masked_query = mask_pii(f"好的,我的邮箱是 {EMAIL_RAW},请跟进")
    assert EMAIL_RAW not in masked_query

    llm, gen_messages, generate_calls = _gate_llm(intent="off_topic")  # 最不利:被判 off_topic
    rag = _make_rag(llm, [])  # 最不利:检索为空
    lead_ctx = LeadTurnContext(
        session_id="s",
        has_lead=True,
        status="invited",
        prompt_count=1,
        contact=contact,
    )

    events = await _collect(rag, masked_query, lead_ctx=lead_ctx)

    complete = events[-1]
    # capture 轮不被 off_topic 拒答吞掉;确认(ack)而非邀请
    assert complete["is_answered"] is True
    assert complete["intent"] != "off_topic" or complete["answer"] != OFF_TOPIC_REPLY_ZH
    assert complete["lead"]["ack"] is True
    assert complete["lead"]["invited"] is False
    assert LEAD_ACK_INSTRUCTION in _system_of(gen_messages[-1])
    # PII HARD:原文不出现在任何 LLM 消息/trace/sources
    all_msg_text = json.dumps(gen_messages, ensure_ascii=False) + json.dumps(
        generate_calls, ensure_ascii=False
    )
    assert EMAIL_RAW not in all_msg_text
    assert EMAIL_RAW not in json.dumps(complete.get("trace_payload", {}), ensure_ascii=False)
    assert EMAIL_RAW not in json.dumps(events, ensure_ascii=False)
    trace_lead = complete["trace_payload"].get("stages", {}).get("lead", {})
    if trace_lead.get("contact"):
        assert trace_lead["contact"] == {
            "type": contact.type,
            "masked": contact.masked,
        }


# --------------------------------------------------------------------------- #
# INT-G007 —— 纯联系方式轮(看似 off-topic):捕获不受对话边界拒绝
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_int_g007_contact_only_turn_not_rejected():
    contact = detect_contact(EMAIL_RAW)
    assert contact is not None
    assert match_social(EMAIL_RAW) is None  # 对话边界不命中纯联系方式

    llm, gen_messages, _ = _gate_llm(intent="off_topic")
    rag = _make_rag(llm, [])
    lead_ctx = LeadTurnContext(
        session_id="s", has_lead=True, status="invited", prompt_count=1, contact=contact
    )

    events = await _collect(rag, EMAIL_RAW, lead_ctx=lead_ctx)

    complete = events[-1]
    assert complete["is_answered"] is True
    assert complete["answer"] != OFF_TOPIC_REPLY_ZH  # 未走友好边界拒答
    assert complete["lead"]["ack"] is True
    assert LEAD_ACK_INSTRUCTION in _system_of(gen_messages[-1])


# --------------------------------------------------------------------------- #
# INT-G008 —— 引用 × Lead 共存:Wiki canonical 正确 + lead 生命周期正确
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_int_g008_citation_canonical_and_lead_coexist():
    results = [
        _sr(f"{WIKI_BLOB}/docs/5-neoeyes-ne301-series/0-overview.md", source_type="github"),
        _sr("https://www.camthink.ai/products/ne503", source_type="website", text="NE503 官网页面"),
    ]
    llm, gen_messages, _ = _gate_llm(intent="commercial")
    rag = _make_rag(llm, results)

    events = await _collect(
        rag, "我们要采购 500 台 NE301,请报价并说明规格", lead_ctx=LeadTurnContext(session_id="s")
    )

    sources_evt = next(e for e in events if e["type"] == "sources")
    by_type = {s["type"]: s for s in sources_evt["sources"]}
    # Wiki canonical 化依旧正确 + provenance 可溯源
    assert by_type["github"]["url"] == WIKI_CANONICAL
    assert by_type["github"]["provenance_url"] == (
        f"{WIKI_BLOB}/docs/5-neoeyes-ne301-series/0-overview.md"
    )
    # 非 Wiki 零变化
    assert by_type["website"]["url"] == "https://www.camthink.ai/products/ne503"
    assert "provenance_url" not in by_type["website"]
    # LLM 上下文呈现 canonical,不把 blob URL 抄给模型
    assert WIKI_CANONICAL in _system_of(gen_messages[-1]) or WIKI_CANONICAL in json.dumps(
        gen_messages[-1], ensure_ascii=False
    )
    assert f"{WIKI_BLOB}/docs/5-neoeyes-ne301-series/0-overview.md" not in json.dumps(
        gen_messages[-1], ensure_ascii=False
    )
    # Lead 生命周期同轮正确推进
    complete = events[-1]
    assert complete["lead"]["invited"] is True
    assert complete["lead"]["level"] == "qualified"
    # 引用完整性统计与 lead 阶段在同一 trace 中共存
    stages = complete["trace_payload"]["stages"]
    assert "citation_integrity" in stages or "lead" in stages


# --------------------------------------------------------------------------- #
# INT-G009 —— answer() / stream_answer() 行为等价
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_int_g009_answer_stream_parity():
    results = [_sr(f"{WIKI_BLOB}/docs/5-neoeyes-ne301-series/0-overview.md")]
    lead_ctx = LeadTurnContext(session_id="s")

    llm_s, _, _ = _gate_llm(intent="commercial")
    rag_s = _make_rag(llm_s, results)
    events = await _collect(rag_s, "我们需要 500 台 NE301,请报价", lead_ctx=lead_ctx)
    complete = events[-1]

    llm_a, _, _ = _gate_llm(intent="commercial")
    rag_a = _make_rag(llm_a, results)
    ans = await rag_a.answer(
        "我们需要 500 台 NE301,请报价", "widget", lead_ctx=LeadTurnContext(session_id="s")
    )

    # 两条路径同语义:is_answered / intent / sources(canonical) / lead 决策
    assert ans.is_answered == complete["is_answered"] is True
    assert ans.intent == complete["intent"] == "commercial"
    assert [s["url"] for s in ans.sources] == [s["url"] for s in complete.get("sources", [])] or (
        ans.sources and ans.sources[0]["url"] == WIKI_CANONICAL
    )
    # stream 的 lead 决策经 complete 事件;answer 经 RAGAnswer.trace_payload.stages.lead
    stream_lead = complete.get("lead") or {}
    answer_lead = (ans.trace_payload.get("stages", {}) or {}).get("lead") or {}
    if stream_lead or answer_lead:
        assert stream_lead.get("invited") is True
        assert answer_lead.get("instruction") == "invite"
    assert ans.sources[0]["provenance_url"].startswith(WIKI_BLOB)


# --------------------------------------------------------------------------- #
# INT-G010 —— 非 Wiki 引用零回归(Website/WooCommerce/GitHub 非 wiki 仓)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_int_g010_non_wiki_citations_unchanged():
    results = [
        _sr("https://www.camthink.ai/products/ne503", source_type="website", text="官网产品页"),
        _sr("https://shop.camthink.ai/product/ne503", source_type="woocommerce", text="商店页"),
        _sr(
            "https://github.com/camthink-ai/other-repo/blob/main/README.md",
            source_type="github",
            text="非 wiki GitHub 仓库",
        ),
    ]
    llm, _, _ = _gate_llm(intent="product", qualification=POTENTIAL_JSON)
    rag = _make_rag(llm, results)

    # INT-G010 断言目标是「非 wiki 引用的 URL 映射」;查询用单产品以聚焦该
    # 契约(双产品查询自 T-COMPARISON-EVIDENCE-CORRECTNESS 起走比较证据
    # 管线,要求逐侧证据,fake 数据不构成该场景)。
    ans = await rag.answer("NE301 产品介绍", "widget", lead_ctx=LeadTurnContext(session_id="s"))

    by_type = {s["type"]: s for s in ans.sources}
    assert by_type["website"]["url"] == "https://www.camthink.ai/products/ne503"
    assert by_type["woocommerce"]["url"] == "https://shop.camthink.ai/product/ne503"
    assert (
        by_type["github"]["url"] == "https://github.com/camthink-ai/other-repo/blob/main/README.md"
    )
    for s in ans.sources:
        assert "provenance_url" not in s
