"""INC-4 确定性证据规划契约测试(A-L 验收矩阵 + INC-3 增量修订)。

覆盖(冻结契约语义):
- EvidenceSlot/EvidencePlan 接口与四角色词表;
- 规划矩阵 A-L:factual/recommendation/support/commercial/comparison 映射,
  三类零检索模式不产计划,畸形输入 fail-open,resolver 身份权威不被取代;
- INC-3 增量修订:evidence_intent 字段(同一调用、additive、缺失/非法/畸形
  → factual fail-open,不新增第五 legacy category);
- L. 零增量 LLM 调用(单次 task_understanding + 生成 = 既有两次);
- J. answer/stream plan parity;
- trace 有界可检(evidence_intent/slots/required/citation/derived_from/fallback)。

性能契约:derive_evidence_plan 纯本地查表(零 IO/零 LLM),不新增串行往返。
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.pipeline.rag import RAGOrchestrator
from backend.pipeline.task_understanding import (
    MODE_CAPABILITY,
    MODE_CLARIFICATION,
    MODE_OFF_TOPIC,
    MODE_STANDARD,
    TaskUnderstanding,
    understand_task,
)
from backend.pipeline.evidence_planning import (
    CITATION_BACKGROUND_ALLOWED,
    CITATION_CITABLE_REQUIRED,
    ROLE_CASE_EVIDENCE,
    ROLE_PRODUCT_SPEC,
    ROLE_SOLUTION_GUIDE,
    ROLE_STORE_OFFICIAL,
    EvidencePlan,
    EvidenceSlot,
    derive_evidence_plan,
)
from backend.pipeline.product_resolver import MODE_COMPARISON, MODE_EXACT, ProductResolution
from backend.retrieval.search import SearchResult

BOX_QUERY = "What is included in the box?"
RECO_QUERY = "我们在找一款适合仓库温控监测的设备,帮我推荐选型"
PRICE_QUERY = "NE503 多少钱"
SUPPORT_QUERY = "设备蜂窝网络注册失败怎么办"


def _u(
    category: str = "product",
    mode: str = MODE_STANDARD,
    intent: str = "factual",
    fallback: bool = False,
    parse_ok: bool = True,
) -> TaskUnderstanding:
    return TaskUnderstanding(
        category=category,
        reason="r",
        confidence=0.9,
        interaction_mode=mode,
        extracted_query="q",
        rewritten_query="q",
        evidence_intent=intent,
        fallback_used=fallback,
        parse_ok=parse_ok,
    )


def _plan(understanding, resolution):
    return derive_evidence_plan(understanding, resolution)


def _roles(plan):
    return [s.role for s in plan.slots]


def _required(plan):
    return {s.role: s.required for s in plan.slots}


# --------------------------------------------------------------------------- #
# 规划矩阵 A-D:检索类任务 → 显式 slot 结构
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_a_factual_lookup_product_spec_required():
    """A:factual lookup → PRODUCT_SPEC required + CITABLE_REQUIRED,继承解析域。"""
    plan = _plan(
        _u("product", intent="factual"), ProductResolution(MODE_EXACT, ("ne503",), "query")
    )
    assert _roles(plan) == [ROLE_PRODUCT_SPEC]
    slot = plan.slots[0]
    assert slot.required is True
    assert slot.citation_requirement == CITATION_CITABLE_REQUIRED
    assert slot.product_scope == ()  # 空 = 继承 resolver 解析域(权威在 resolver)


@pytest.mark.unit
def test_b_recommendation_solution_guide_plus_support():
    """B:recommendation → SOLUTION_GUIDE required + PRODUCT_SPEC 支撑槽。

    #31:案例证据(CASE_EVIDENCE)作为可选背景槽参与方案推荐的覆盖组合
    (Product/Solution/Case 多类证据综合;缺失由 coverage 诚实呈现)。
    """
    plan = _plan(
        _u("product", intent="recommendation"),
        ProductResolution(MODE_EXACT, ("ne503",), "query"),
    )
    assert _roles(plan) == [ROLE_SOLUTION_GUIDE, ROLE_PRODUCT_SPEC, ROLE_CASE_EVIDENCE]
    assert plan.slots[0].required is True
    assert plan.slots[0].citation_requirement == CITATION_CITABLE_REQUIRED
    assert plan.slots[1].required is False
    assert plan.slots[2].required is False


@pytest.mark.unit
def test_c_support_case_evidence_background_not_citable():
    """C:troubleshooting → CASE_EVIDENCE(BACKGROUND_ALLOWED)+ PRODUCT_SPEC 支撑;
    filesystem 证据不因被选而公开可引用。"""
    plan = _plan(_u("support"), ProductResolution("none", (), "none"))
    assert _roles(plan) == [ROLE_CASE_EVIDENCE, ROLE_PRODUCT_SPEC]
    case = plan.slots[0]
    assert case.citation_requirement == CITATION_BACKGROUND_ALLOWED
    assert case.required is False
    assert plan.slots[1].citation_requirement == CITATION_CITABLE_REQUIRED


@pytest.mark.unit
def test_d_commercial_store_official_required():
    """D:commercial/pricing → STORE_OFFICIAL required;wiki 价格不得静默替代 Store 真相
    (缺失可经 planning/coverage 语义观察)。"""
    plan = _plan(_u("commercial"), ProductResolution(MODE_EXACT, ("ne503",), "query"))
    assert _roles(plan) == [ROLE_STORE_OFFICIAL, ROLE_PRODUCT_SPEC]
    assert plan.slots[0].required is True
    assert plan.slots[0].citation_requirement == CITATION_CITABLE_REQUIRED
    assert plan.slots[1].required is False


# --------------------------------------------------------------------------- #
# 规划矩阵 E:comparison 语义投影,执行管线冻结
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_e_comparison_per_target_spec_from_resolver():
    """E:comparison → 每 target 一个 PRODUCT_SPEC;scope 只来自 resolver 目标,
    不来自理解输出(身份权威边界)。"""
    plan = _plan(
        _u("product", intent="recommendation"),
        ProductResolution(MODE_COMPARISON, ("ne301", "ne503"), "query"),
    )
    assert [s.role for s in plan.slots] == [ROLE_PRODUCT_SPEC, ROLE_PRODUCT_SPEC]
    assert [s.product_scope for s in plan.slots] == [("ne301",), ("ne503",)]
    assert all(s.required for s in plan.slots)
    assert all(s.citation_requirement == CITATION_CITABLE_REQUIRED for s in plan.slots)


# --------------------------------------------------------------------------- #
# 规划矩阵 F/G/H:零检索模式 → 无证据计划
# --------------------------------------------------------------------------- #


@pytest.mark.unit
@pytest.mark.parametrize(
    "mode",
    [MODE_CLARIFICATION, MODE_CAPABILITY, MODE_OFF_TOPIC],
)
def test_fgh_zero_retrieval_modes_have_no_plan(mode):
    plan = _plan(_u("product", mode=mode), ProductResolution("none", (), "none"))
    assert plan.slots == ()


# --------------------------------------------------------------------------- #
# 规划矩阵 I:畸形输入 fail-open(规划器自身永不抛错/不重试)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_i_degraded_understanding_falls_open_to_factual_plan():
    """I:畸形/回退理解 → factual 计划(PRODUCT_SPEC),不重试、不抛错。"""
    plan = _plan(
        _u("product", intent="design", fallback=True, parse_ok=False),
        ProductResolution("none", (), "none"),
    )
    assert _roles(plan) == [ROLE_PRODUCT_SPEC]
    assert plan.slots[0].required is True
    assert plan.fallback_used is True


@pytest.mark.unit
def test_i_unknown_category_never_raises():
    """规划器对任意畸形 category/mode 全 fail-open(单 optional spec slot)。"""
    for cat in ("", None, "unknown"):
        plan = (
            _plan(_u(cat or "product"), ProductResolution("none", (), "none"))
            if cat
            else _plan(
                TaskUnderstanding(category="product", evidence_intent="factual"),
                ProductResolution("none", (), "none"),
            )
        )
        assert isinstance(plan, EvidencePlan)


# --------------------------------------------------------------------------- #
# 规划矩阵 K:resolver 身份权威 / L:零增量 LLM / 纯度
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_k_plan_never_reads_product_identity_from_understanding():
    """K:plan 的产品身份仅来自 resolution;TaskUnderstanding 无产品字段可读。"""
    u = _u("product", intent="recommendation")
    assert not hasattr(u, "targets")
    plan = _plan(u, ProductResolution(MODE_COMPARISON, ("ne301",), "query"))
    assert plan.slots[0].product_scope == ("ne301",)
    assert plan.resolution_targets == ("ne301",)


@pytest.mark.unit
def test_l_planner_is_local_and_llm_free():
    """L(结构面):规划器签名不含 llm/IO 依赖,输出可哈希冻结值对象。"""
    import inspect

    sig = inspect.signature(derive_evidence_plan)
    assert "llm" not in sig.parameters
    plan = _plan(_u(), ProductResolution(MODE_EXACT, ("ne503",), "query"))
    assert hash(plan)  # frozen + 可哈希(纯值对象,可进 trace/日志)


# --------------------------------------------------------------------------- #
# INC-3 增量修订:evidence_intent(同一调用 / additive / fail-open)
# --------------------------------------------------------------------------- #


def _llm_ok(payload: dict) -> AsyncMock:
    llm = AsyncMock()
    llm.generate.return_value = MagicMock(content=json.dumps(payload, ensure_ascii=False))
    return llm


HISTORY = [
    {"role": "user", "content": "我想了解 NE301"},
    {"role": "assistant", "content": "NE301 是一款…"},
]


@pytest.mark.unit
async def test_amendment_recommendation_parsed_from_same_invocation():
    """修订 2:同一 Task Understanding 调用区分 factual / recommendation。"""
    llm = _llm_ok(
        {
            "category": "product",
            "reason": "选型推荐",
            "confidence": 0.9,
            "interaction_mode": "standard",
            "evidence_intent": "recommendation",
            "extracted_query": RECO_QUERY,
            "rewritten_query": RECO_QUERY,
        }
    )
    u = await understand_task(RECO_QUERY, HISTORY, llm)
    assert u.evidence_intent == "recommendation"
    assert u.fallback_used is False
    assert llm.generate.await_count == 1


@pytest.mark.unit
async def test_amendment_factual_default_when_absent():
    """缺失 = legacy INC-3 合法兼容形态:缺省 factual,不视为退化
    (fallback_used 不被新字段的缺席污染,向后兼容)。"""
    llm = _llm_ok(
        {
            "category": "product",
            "reason": "r",
            "confidence": 0.9,
            "interaction_mode": "standard",
            "extracted_query": "q",
            "rewritten_query": "q",
        }
    )
    u = await understand_task("NE503 支持哪些接口", HISTORY, llm)
    assert u.evidence_intent == "factual"
    assert u.fallback_used is False


@pytest.mark.unit
async def test_amendment_invalid_value_fails_open_factual():
    llm = _llm_ok(
        {
            "category": "product",
            "reason": "r",
            "confidence": 0.9,
            "interaction_mode": "standard",
            "evidence_intent": "design",
            "extracted_query": "q",
            "rewritten_query": "q",
        }
    )
    u = await understand_task("NE503 支持哪些接口", HISTORY, llm)
    assert u.evidence_intent == "factual"
    assert u.fallback_used is True


@pytest.mark.unit
async def test_amendment_total_fallback_is_factual_no_retry():
    llm = AsyncMock()
    llm.generate.side_effect = RuntimeError("provider down")
    u = await understand_task(SUPPORT_QUERY, HISTORY, llm)
    assert u.evidence_intent == "factual"
    assert u.parse_ok is False
    assert u.fallback_used is True
    assert llm.generate.await_count == 1  # 不重试


@pytest.mark.unit
def test_amendment_no_fifth_legacy_category():
    from backend.pipeline.intent import VALID_CATEGORIES

    assert set(VALID_CATEGORIES) == {"commercial", "product", "support", "off_topic"}


# --------------------------------------------------------------------------- #
# 管线集成:trace 可检 / J parity / L 零增量调用 / I 管线级 fail-open
# --------------------------------------------------------------------------- #


def _make_llm(payload: dict) -> AsyncMock:
    llm = _llm_ok(payload)

    async def _stream(messages, **kwargs):
        yield "ok"

    llm.stream = _stream
    return llm


def _orchestrator(payload: dict, *, with_result: bool = False):
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
    reranker.rerank_scored.return_value = ([sr] if with_result else [], [])
    reranker.rerank_scored.return_value = ([sr] if with_result else [], [])
    reranker.rerank_scored.return_value = ([sr] if with_result else [], [])
    rag = RAGOrchestrator(
        searcher, reranker, _make_llm(payload), system_prompt="s", min_results_to_answer=1
    )
    return rag


_FACTUAL = {
    "category": "product",
    "reason": "r",
    "confidence": 0.9,
    "interaction_mode": "standard",
    "evidence_intent": "factual",
    "extracted_query": BOX_QUERY,
    "rewritten_query": BOX_QUERY,
}
_RECOMMEND = {
    "category": "product",
    "reason": "选型推荐",
    "confidence": 0.9,
    "interaction_mode": "standard",
    "evidence_intent": "recommendation",
    "extracted_query": RECO_QUERY,
    "rewritten_query": RECO_QUERY,
}


@pytest.mark.unit
async def test_trace_plan_inspectable_bounded_answer():
    """trace 暴露有界语义事实:intent/slots/required/citation/scope/fallback;无思维链。"""
    rag = _orchestrator(_FACTUAL, with_result=True)
    result = await rag.answer(BOX_QUERY, "widget", page_context={"product": "NE503"})
    plan_stage = result.trace_payload["stages"]["plan"]
    assert plan_stage["evidence_intent"] == "factual"
    assert plan_stage["slots"] == [
        {
            "role": ROLE_PRODUCT_SPEC,
            "product_scope": [],
            "required": True,
            "citation_requirement": CITATION_CITABLE_REQUIRED,
        }
    ]
    assert plan_stage["derived_from"]["resolution_targets"] == ["ne503"]
    assert plan_stage["fallback_used"] is False
    assert "reason" not in plan_stage


@pytest.mark.unit
async def test_recommendation_plan_visible_in_answer():
    rag = _orchestrator(_RECOMMEND, with_result=True)
    result = await rag.answer(RECO_QUERY, "widget", page_context={"product": "NE503"})
    plan_stage = result.trace_payload["stages"]["plan"]
    assert plan_stage["evidence_intent"] == "recommendation"
    # #31:推荐计划含可选案例槽
    assert [s["role"] for s in plan_stage["slots"]] == [ROLE_SOLUTION_GUIDE, ROLE_PRODUCT_SPEC, ROLE_CASE_EVIDENCE]
    assert plan_stage["slots"][0]["required"] is True


async def _collect(rag, query, **kwargs):
    events = []
    async for raw in rag.stream_answer(query, "widget", **kwargs):
        events.append(json.loads(raw))
    return events


@pytest.mark.unit
async def test_j_answer_stream_plan_parity():
    """J:answer 与 stream 消费等价 plan 语义,stages.plan 逐字段一致。"""
    r1 = await _orchestrator(_RECOMMEND, with_result=True).answer(
        RECO_QUERY, "widget", page_context={"product": "NE503"}
    )
    events = await _collect(
        _orchestrator(_RECOMMEND, with_result=True), RECO_QUERY, page_context={"product": "NE503"}
    )
    complete = [e for e in events if e["type"] == "complete"][-1]
    assert r1.trace_payload["stages"]["plan"] == complete["trace_payload"]["stages"]["plan"]
    assert complete["trace_payload"]["stages"]["plan"]["slots"][0]["role"] == ROLE_SOLUTION_GUIDE


@pytest.mark.unit
async def test_l_zero_incremental_llm_calls_in_pipeline():
    """L:管线总 generate 调用 = 1 次理解 + 1 次生成(INC-3 基线),零增量。"""
    rag = _orchestrator(_FACTUAL, with_result=True)
    await rag.answer(BOX_QUERY, "widget", page_context={"product": "NE503"})
    llm = rag._llm
    understanding_calls = [
        c for c in llm.generate.call_args_list if c.kwargs.get("task") == "task_understanding"
    ]
    assert len(understanding_calls) == 1
    assert len(llm.generate.call_args_list) == 2  # 理解 + 生成,无规划调用


@pytest.mark.unit
async def test_i_pipeline_degraded_understanding_still_plans_factual():
    """I(管线级):理解整体失败 → factual 计划,检索保持可用,不重试。

    with_result=False:检索为空在生成前走不足语义拒答(拒绝载荷含 stages),
    避免 mock LLM 在生成段再次抛错干扰断言焦点。"""
    rag = _orchestrator(_FACTUAL, with_result=False)
    llm = AsyncMock()
    llm.generate.side_effect = RuntimeError("down")

    async def _stream(messages, **kwargs):
        yield "ok"

    llm.stream = _stream
    rag._llm = llm
    result = await rag.answer(BOX_QUERY, "widget", page_context={"product": "NE503"})
    plan_stage = result.trace_payload["stages"]["plan"]
    assert plan_stage["evidence_intent"] == "factual"
    assert plan_stage["fallback_used"] is True
    assert plan_stage["slots"][0]["role"] == ROLE_PRODUCT_SPEC
    assert llm.generate.await_count == 1
