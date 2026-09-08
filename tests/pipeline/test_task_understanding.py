"""INC-3 合并任务理解测试(契约 §19 语料 + A1-A19 验收点)。

覆盖:
- 结构化解析黄金集(完整/legacy 兼容形/逐字段非法/整体畸形/LLM 异常);
- 回退矩阵:失败绝不产生 off_topic 拒答,检索可用性保持,fallback 可观测;
- A2:无合格历史 rewritten == extracted(模型不遵守也强制);
- #26:欠指定域内问题 → clarification_required(澄清信封,非拒答);
- #27:能力/导向(ZH/EN 语义类)→ capability_orientation(intent=product,非拒答);
- capture 轮豁免;真 off_topic 仍拒答;mode↔category 双向一致性修复;
- 单调用计数;answer/stream parity。
"""

import json

import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.pipeline.task_understanding import (
    MODE_CAPABILITY,
    MODE_CLARIFICATION,
    MODE_OFF_TOPIC,
    MODE_STANDARD,
    TaskUnderstanding,
    understand_task,
)

QUESTION = "What is included in the box?"
ZH_CAPABILITY = "你会干什么"
EN_CAPABILITY = "What can you do?"


def _llm_ok(payload: dict) -> AsyncMock:
    llm = AsyncMock()
    llm.generate.return_value = MagicMock(content=json.dumps(payload, ensure_ascii=False))
    return llm


def _llm_raises() -> AsyncMock:
    llm = AsyncMock()
    llm.generate.side_effect = RuntimeError("provider down")
    return llm


def _llm_content(content: str) -> AsyncMock:
    llm = AsyncMock()
    llm.generate.return_value = MagicMock(content=content)
    return llm


HISTORY = [
    {"role": "user", "content": "我想了解 NE301"},
    {"role": "assistant", "content": "NE301 是一款…"},
    {"role": "user", "content": "价格多少"},
]

# --------------------------------------------------------------------------- #
# 结构化解析与逐字段回退(契约 §5/§7)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_full_valid_payload_parses_verbatim():
    llm = _llm_ok(
        {
            "category": "support",
            "reason": "故障排查",
            "confidence": 0.9,
            "interaction_mode": "standard",
            "extracted_query": "NE101 CEREG 注册失败",
            "rewritten_query": "NE101 蜂窝网络 CEREG 注册失败排查",
        }
    )
    u = await understand_task("NE101 老是注册失败", HISTORY, llm)
    assert (u.category, u.interaction_mode, u.fallback_used, u.parse_ok) == (
        "support",
        "standard",
        False,
        True,
    )
    assert u.extracted_query == "NE101 CEREG 注册失败"
    assert u.rewritten_query == "NE101 蜂窝网络 CEREG 注册失败排查"


@pytest.mark.unit
async def test_legacy_category_only_payload_falls_back_per_field():
    """仅 legacy 形(只有 category):mode 由 category 推导,查询回退原 query,
    fallback_used=True 且 parse_ok=True(结构可解析)。"""
    llm = _llm_ok({"category": "support", "reason": "r"})
    u = await understand_task("q", None, llm)
    assert u.category == "support"
    assert u.interaction_mode == "standard"
    assert u.extracted_query == "q"
    assert u.rewritten_query == "q"
    assert u.fallback_used is True and u.parse_ok is True


@pytest.mark.unit
async def test_total_failure_fails_open_never_off_topic():
    """契约 §7/A11:整体失败 → product/conf=0/standard/原 query;绝不 off_topic。"""
    u = await understand_task("anything", HISTORY, _llm_raises())
    assert u.category == "product"
    assert u.confidence == 0.0
    assert u.interaction_mode == "standard"
    assert u.extracted_query == "anything"
    assert u.rewritten_query == "anything"
    assert u.fallback_used is True and u.parse_ok is False


@pytest.mark.unit
async def test_malformed_json_never_becomes_off_topic():
    for bad in ["", "不是 JSON", '{"category":', "[]"]:
        u = await understand_task("q", HISTORY, _llm_content(bad))
        assert u.interaction_mode != MODE_OFF_TOPIC
        assert u.category != "off_topic"
        assert u.fallback_used is True


@pytest.mark.unit
async def test_invalid_category_fails_open_product():
    llm = _llm_ok({"category": "unknown-new", "interaction_mode": "standard"})
    u = await understand_task("q", None, llm)
    assert u.category == "product"
    assert u.fallback_used is True


@pytest.mark.unit
async def test_mode_category_bidirectional_consistency_repair():
    """mode=standard + category=off_topic → 修复为 mode=off_topic(反向同理)。"""
    u1 = await understand_task(
        "q", None, _llm_ok({"category": "off_topic", "interaction_mode": "standard"})
    )
    assert u1.interaction_mode == MODE_OFF_TOPIC
    u2 = await understand_task(
        "q", None, _llm_ok({"category": "product", "interaction_mode": "off_topic"})
    )
    assert u2.category == "off_topic"


# --------------------------------------------------------------------------- #
# A2:无合格历史 rewritten == extracted(模型不遵守也强制)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_no_history_forces_rewritten_equals_extracted():
    llm = _llm_ok(
        {
            "category": "product",
            "interaction_mode": "standard",
            "extracted_query": "E",
            "rewritten_query": "R",
        }
    )
    u = await understand_task("q", None, llm)
    assert u.rewritten_query == u.extracted_query == "E"
    u2 = await understand_task("q", [{"role": "user", "content": "hi"}], llm)  # len<2 同判据
    assert u2.rewritten_query == u2.extracted_query


# --------------------------------------------------------------------------- #
# #26:欠指定域内问题 → 澄清(非拒答);真无关 → 仍拒答
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_issue26_underspecified_in_domain_is_clarification_not_off_topic():
    llm = _llm_ok(
        {
            "category": "product",
            "reason": "域内但未指明产品",
            "confidence": 0.8,
            "interaction_mode": "clarification_required",
            "extracted_query": QUESTION,
            "rewritten_query": QUESTION,
        }
    )
    u = await understand_task(QUESTION, None, llm)
    assert u.interaction_mode == MODE_CLARIFICATION
    assert u.category == "product"  # legacy 兼容映射:非 off_topic 域内类


@pytest.mark.unit
async def test_issue26_true_unrelated_still_off_topic():
    llm = _llm_ok(
        {
            "category": "off_topic",
            "reason": "天气闲聊",
            "confidence": 0.95,
            "interaction_mode": "off_topic",
            "extracted_query": "今天天气怎么样",
            "rewritten_query": "今天天气怎么样",
        }
    )
    u = await understand_task("今天天气怎么样", None, llm)
    assert u.interaction_mode == MODE_OFF_TOPIC
    assert u.category == "off_topic"


# --------------------------------------------------------------------------- #
# #27:能力/导向(ZH/EN 语义类)→ capability_orientation,legacy=product
# --------------------------------------------------------------------------- #


@pytest.mark.unit
@pytest.mark.parametrize(
    "text", [ZH_CAPABILITY, "你可以帮我什么", "怎么用你", EN_CAPABILITY, "How can you help me?"]
)
async def test_issue27_capability_orientation_semantic_class(text):
    """语义类覆盖(非短语补丁):ZH/EN 等价表达 → capability_orientation。"""
    llm = _llm_ok(
        {
            "category": "product",
            "reason": "询问助手能力",
            "confidence": 0.9,
            "interaction_mode": "capability_orientation",
            "extracted_query": text,
            "rewritten_query": text,
        }
    )
    u = await understand_task(text, None, llm)
    assert u.interaction_mode == MODE_CAPABILITY
    assert u.category == "product"  # 契约 §3 兼容映射
    assert u.interaction_mode != MODE_OFF_TOPIC


# --------------------------------------------------------------------------- #
# 编排层路由(信封/信键/短路豁免)
# --------------------------------------------------------------------------- #


def _orchestrator(llm):
    from backend.pipeline.rag import RAGOrchestrator

    searcher = MagicMock()
    searcher.search.return_value = []
    searcher.search_symbols.return_value = []
    searcher.search_bucket.return_value = []
    reranker = MagicMock()
    reranker.rerank.return_value = []
    return RAGOrchestrator(searcher, reranker, llm, system_prompt="s", min_results_to_answer=1)


def _understanding(payload: dict):
    llm = AsyncMock()
    llm.generate.return_value = MagicMock(content=json.dumps(payload, ensure_ascii=False))
    return llm


@pytest.mark.unit
async def test_issue26_clarification_envelope_is_not_off_topic_reject():
    """A6/A18:欠指定域内 → 澄清信封(result_key=clarification_required),非拒答。"""
    llm = _understanding(
        {
            "category": "product",
            "reason": "缺产品上下文",
            "confidence": 0.8,
            "interaction_mode": "clarification_required",
            "extracted_query": QUESTION,
            "rewritten_query": QUESTION,
        }
    )
    rag = _orchestrator(llm)
    result = await rag.answer(QUESTION, "widget")
    assert result.result_key == "clarification_required"
    assert result.is_answered is False
    assert result.intent == "product"
    assert "off_topic" not in json.dumps(result.trace_payload)
    assert result.trace_payload["type"] == "task_clarify"
    assert result.trace_payload["interaction_mode"] == "clarification_required"


@pytest.mark.unit
async def test_issue27_orientation_envelope_is_not_off_topic_reject():
    """A9/A18:能力导向 → 欢迎引导信封(capability_orientation),legacy intent=product。"""
    llm = _understanding(
        {
            "category": "product",
            "reason": "助手能力询问",
            "confidence": 0.9,
            "interaction_mode": "capability_orientation",
            "extracted_query": ZH_CAPABILITY,
            "rewritten_query": ZH_CAPABILITY,
        }
    )
    rag = _orchestrator(llm)
    result = await rag.answer(ZH_CAPABILITY, "widget")
    assert result.result_key == "capability_orientation"
    assert result.is_answered is True
    assert result.intent == "product"
    assert "off_topic" not in json.dumps(result.trace_payload)


@pytest.mark.unit
async def test_capture_turn_with_off_topic_mode_still_proceeds():
    """契约 §12:capture 轮即使判为 off_topic 也必须继续(联系方式捕获不丢失)。"""
    llm = _understanding(
        {
            "category": "off_topic",
            "reason": "r",
            "confidence": 0.9,
            "interaction_mode": "off_topic",
            "extracted_query": "john@example.com",
            "rewritten_query": "john@example.com",
        }
    )
    rag = _orchestrator(llm)
    lead_ctx = MagicMock()
    lead_ctx.capture_mode = True
    result = await rag.answer("john@example.com", "widget", lead_ctx=lead_ctx)
    # capture 轮不被新拒答路径吞掉(继续走生成/捕获确认)
    assert result.trace_payload["config_snapshot"]["alpha"] == 0.5  # 走到主管线的证据
    assert result.result_key != "off_topic"


@pytest.mark.unit
async def test_single_understanding_call_on_normal_path():
    """A1:正常路径恰好 1 次应用层理解调用(不再有独立 extract/rewrite 调用)。"""
    llm = _understanding(
        {
            "category": "product",
            "reason": "r",
            "confidence": 0.9,
            "interaction_mode": "standard",
            "extracted_query": "NE301 选型",
            "rewritten_query": "NE301 选型",
        }
    )
    rag = _orchestrator(llm)
    await rag.answer("NE301 选型", "widget", conversation_history=HISTORY)
    understanding_calls = [
        c for c in llm.generate.call_args_list if c.kwargs.get("task") == "task_understanding"
    ]
    assert len(understanding_calls) == 1
    assert not any(
        c.kwargs.get("task") in ("intent", "query_rewrite") for c in llm.generate.call_args_list
    )


@pytest.mark.unit
async def test_trace_legacy_keys_derived_from_single_call():
    """A17:legacy stages.intent/stages.rewrite 由单次结果派生;stages.understanding 如实单调用。"""
    llm = _understanding(
        {
            "category": "product",
            "reason": "r",
            "confidence": 0.9,
            "interaction_mode": "standard",
            "extracted_query": "E",
            "rewritten_query": "E",
        }
    )
    rag = _orchestrator(llm)
    events = []
    async for raw in rag.stream_answer("NE301 选型", "widget"):
        events.append(json.loads(raw))
    complete = [e for e in events if e["type"] == "complete"][0]
    stages = complete["trace_payload"]["stages"]
    assert stages["understanding"]["one_call"] is True
    assert stages["understanding"]["interaction_mode"] == "standard"
    assert stages["intent"]["category"] == "product"  # legacy 兼容键仍在
    assert stages["rewrite"]["consolidated"] is True
    assert stages["rewrite"]["extract_ms"] is None  # 不伪装独立 LLM 计时


@pytest.mark.unit
async def test_query_language_preserved_zh_en():
    """契约 §17:提取/改写保持用户语言(ZH/EN 回归)。"""
    for q, lang_marker in [
        ("NE301 电池怎么监控?", "NE301"),
        ("How to monitor the battery?", "battery"),
    ]:
        llm = _understanding(
            {
                "category": "product",
                "reason": "r",
                "confidence": 0.9,
                "interaction_mode": "standard",
                "extracted_query": q,
                "rewritten_query": q,
            }
        )
        rag = _orchestrator(llm)
        result = await rag.answer(q, "widget", conversation_history=HISTORY)
        # 检索消费侧拿到的就是原语言查询(经 understanding 透传)
        assert lang_marker in result.trace_payload["stages"]["rewrite"]["extracted"]


@pytest.mark.unit
def test_task_understanding_routing_chain_configured():
    """契约 §14:task_understanding 拥有独立路由身份(非生产默认链,yaml 可解析)。"""
    import yaml

    cfg = yaml.safe_load(open("config/llm_providers.yaml"))
    chain = cfg["routing"]["task_understanding"]["chain"]
    assert chain, "task_understanding 链必须配置"
    assert chain[0]["provider"] in {p["id"] for p in cfg["providers"]}
