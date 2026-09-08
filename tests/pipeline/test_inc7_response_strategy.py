"""INC-7 自然响应层契约测试(RED 先行 + A-X 验收矩阵)。

覆盖(冻结实现契约语义):
- ResponseStrategy 确定性四字段(response_frame/directness/coverage_framing/
  gap_labels),零 LLM、零 IO、全 total;
- partial_supported 只来自 CoverageReport 真值;gap_labels 原样透传不重算;
- 覆盖不完整 ≠ 拒答(无拒绝权威字段);无证据权威保留在既有拒答门;
- 比较(Issue #19)/lead/澄清/能力/无关短路所有权不可被通用策略覆盖;
- strategy=None 与推导失败 ⇒ 今日行为逐字节保留(兼容契约);
- 引用契约/语言权威/真值行原样保留;编译不触碰 Admin base 与证据真值;
- answer/stream 语义等价;trace 有界零正文;
- NEW_LLM_CALLS = 0(纯函数,无 IO/异步)。

新模块经惰性导入引用:基线(无该模块)上每条测试独立 RED,
而非收集期整包报错——保留逐项 RED 证据。
"""

from dataclasses import fields
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.pipeline.evidence_planning import derive_evidence_plan
from backend.pipeline.evidence_selection import build_coverage_report
from backend.pipeline.product_resolver import ProductResolution
from backend.pipeline.rag import RAGOrchestrator
from backend.pipeline.task_understanding import TaskUnderstanding
from backend.retrieval.search import SearchResult


def _rs():
    """惰性导入被测模块(基线缺失 ⇒ 该测试独立 ModuleNotFoundError=RED)。"""
    from backend.pipeline import response_strategy as mod

    return mod


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

PRODUCT_STYLE = "PRODUCT_STYLE_MARKER 通用产品风格"
INTENT_STYLES = {
    "product": PRODUCT_STYLE,
    "commercial": "COMMERCIAL_STYLE_MARKER",
    "support": "SUPPORT_STYLE_MARKER",
}


def _u(
    category: str = "product",
    evidence_intent: str = "factual",
    interaction_mode: str = "standard",
) -> TaskUnderstanding:
    return TaskUnderstanding(
        category=category,
        reason="r",
        confidence=0.9,
        interaction_mode=interaction_mode,
        extracted_query="q",
        rewritten_query="q",
        evidence_intent=evidence_intent,
    )


RES_EXACT = ProductResolution("exact", ("ne503",), "query")
RES_COMPARISON = ProductResolution("comparison", ("ne301", "ne503"), "query")


def _sr(
    source_id: str,
    product: str = "ne503",
    title: str = "NE503",
    text: str = "内容。",
    source_type: str = "website",
):
    return SearchResult(
        text=text,
        source_id=source_id,
        source_type=source_type,
        product=product,
        title=title,
        url=f"https://example.com/{source_id}",
        score=0.9,
        chunk_index=0,
    )


STORE_NE503 = _sr(
    "store/ne503", title="NE503 商店页", text="价格 $599。", source_type="woocommerce"
)
SPEC_NE503 = _sr("site/ne503-spec", title="NE503 规格书", text="接口 RS485。")


def _plan(u: TaskUnderstanding, resolution: ProductResolution = RES_EXACT):
    return derive_evidence_plan(u, resolution)


def _coverage_commercial_partial():
    """commercial 计划 + 缺 STORE_OFFICIAL → coverage_complete=False。"""
    u = _u("commercial")
    plan = _plan(u)
    return build_coverage_report(
        plan,
        [SPEC_NE503],
        citable_ids=frozenset({(SPEC_NE503.source_id, SPEC_NE503.chunk_index)}),
    )


def _coverage_commercial_complete():
    u = _u("commercial")
    plan = _plan(u)
    return build_coverage_report(
        plan,
        [STORE_NE503],
        citable_ids=frozenset({(STORE_NE503.source_id, STORE_NE503.chunk_index)}),
    )


def _rag() -> RAGOrchestrator:
    searcher = MagicMock()
    reranker = MagicMock()
    llm = AsyncMock()
    return RAGOrchestrator(
        searcher,
        reranker,
        llm,
        system_prompt="BASE_SYSTEM",
        min_results_to_answer=1,
        intent_styles=dict(INTENT_STYLES),
    )


def _msg_kwargs() -> dict:
    return dict(
        query="NE503 多少钱?",
        context="【可引用资料】\n<SOURCE 1> 价格 $599 </SOURCE 1>",
        language="中文",
        history=None,
        channel="widget",
        intent="commercial",
    )


# --------------------------------------------------------------------------- #
# RED-1 / RED-2 / RED-3:策略推导(帧/覆盖真值/缺口透传)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_red1_factual_vs_recommendation_frames_differ():
    """RED-1:factual 与 recommendation 必须产出可区分的实现策略。"""
    u_factual = _u("product", "factual")
    u_reco = _u("product", "recommendation")
    s_factual = _rs().derive_response_strategy(u_factual, RES_EXACT, _plan(u_factual), None)
    s_reco = _rs().derive_response_strategy(u_reco, RES_EXACT, _plan(u_reco), None)
    assert s_factual is not None and s_reco is not None
    assert s_factual.response_frame != s_reco.response_frame
    assert s_factual.directness != s_reco.directness


@pytest.mark.unit
def test_frame_mapping_full_table():
    """category×evidence_intent → 冻结四帧决定性映射(确定性纯函数)。"""
    cases = [
        (("product", "factual"), ("factual_lookup", "concise_direct")),
        (("product", "recommendation"), ("recommendation", "guided_expansion")),
        (("support", "factual"), ("troubleshooting", "guided_expansion")),
        (("commercial", "factual"), ("commercial", "concise_direct")),
    ]
    for (category, intent), (frame, directness) in cases:
        u = _u(category, intent)
        s = _rs().derive_response_strategy(u, RES_EXACT, _plan(u, RES_EXACT), None)
        assert s is not None, (category, intent)
        assert s.response_frame == frame, (category, intent)
        assert s.directness == directness, (category, intent)


@pytest.mark.unit
def test_derive_is_deterministic_zero_llm():
    """A:相同输入 ⇒ 相同策略;纯同步函数(零异步/零 IO 面)。"""
    u = _u("commercial")
    plan = _plan(u)
    cov = _coverage_commercial_partial()
    a = _rs().derive_response_strategy(u, RES_EXACT, plan, cov)
    b = _rs().derive_response_strategy(u, RES_EXACT, plan, cov)
    assert a == b
    import inspect

    assert not inspect.iscoroutinefunction(_rs().derive_response_strategy)
    assert not inspect.iscoroutinefunction(_rs().compile_strategy_instructions)


@pytest.mark.unit
def test_red2_partial_coverage_derives_partial_supported():
    """RED-2:CoverageReport 部分真值必须进入响应策略。"""
    cov = _coverage_commercial_partial()
    assert cov.coverage_complete is False
    s = _rs().derive_response_strategy(_u("commercial"), RES_EXACT, _plan(_u("commercial")), cov)
    assert s is not None
    assert s.coverage_framing == "partial_supported"


@pytest.mark.unit
def test_red3_gap_labels_pass_through_verbatim():
    """RED-3:missing_required 真值原样进入策略,不重算不改写。"""
    cov = _coverage_commercial_partial()
    assert cov.missing_required  # 缺口非空(STORE_OFFICIAL)
    s = _rs().derive_response_strategy(_u("commercial"), RES_EXACT, _plan(_u("commercial")), cov)
    assert s is not None
    assert s.gap_labels == cov.missing_required


@pytest.mark.unit
def test_complete_or_missing_coverage_gives_none_framing():
    """覆盖完整 / 无覆盖报告(CoverageReport=None)⇒ framing=none。"""
    u = _u("commercial")
    plan = _plan(u)
    s_complete = _rs().derive_response_strategy(u, RES_EXACT, plan, _coverage_commercial_complete())
    assert s_complete is not None
    assert s_complete.coverage_framing == "none"
    assert s_complete.gap_labels == ()
    s_none_cov = _rs().derive_response_strategy(u, RES_EXACT, plan, None)
    assert s_none_cov is not None
    assert s_none_cov.coverage_framing == "none"


@pytest.mark.unit
def test_support_plan_zero_required_vacuously_complete():
    """troubleshooting 计划(无 required 槽)空真视为 complete,不触发 framing。"""
    u = _u("support")
    plan = _plan(u)
    cov = build_coverage_report(plan, [], citable_ids=frozenset())
    assert cov.required_total == 0
    s = _rs().derive_response_strategy(u, RES_EXACT, plan, cov)
    assert s is not None
    assert s.response_frame == "troubleshooting"
    assert s.coverage_framing == "none"


# --------------------------------------------------------------------------- #
# Fail-open 契约
# --------------------------------------------------------------------------- #


@pytest.mark.unit
@pytest.mark.parametrize(
    "u,res,plan,cov",
    [
        (None, None, None, None),
        ("garbage", "garbage", "garbage", "garbage"),
        (_u(), None, None, None),
        (object(), object(), object(), object()),
    ],
)
def test_fail_open_garbage_inputs_return_none_never_raise(u, res, plan, cov):
    """畸形输入 ⇒ None(回退今日行为),绝不抛错。"""
    assert _rs().derive_response_strategy(u, res, plan, cov) is None


@pytest.mark.unit
def test_fail_open_unknown_category_returns_none():
    """未知 category ⇒ None(今日行为:未知意图无风格段)。"""
    u = _u("unknown_category")
    assert _rs().derive_response_strategy(u, RES_EXACT, _plan(u), None) is None


# --------------------------------------------------------------------------- #
# RED-7:既有路径所有权(短路/比较/lead)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
@pytest.mark.parametrize("mode", ["clarification_required", "capability_orientation", "off_topic"])
def test_zero_retrieval_modes_return_none(mode):
    """澄清/能力/无关属冻结短路所有权;推导永不为其产出通用策略。"""
    u = _u("product", "factual", interaction_mode=mode)
    assert _rs().derive_response_strategy(u, RES_EXACT, _plan(u), None) is None


@pytest.mark.unit
def test_comparison_mode_returns_none():
    """比较路径由 Issue #19 契约独占;推导返回 None ⇒ 编译回落今日行为。"""
    u = _u("product", "factual")
    plan = _plan(u, RES_COMPARISON)
    cov = _coverage_commercial_partial()  # 即便覆盖不完整也不得叠加通用帧
    assert _rs().derive_response_strategy(u, RES_COMPARISON, plan, cov) is None


# --------------------------------------------------------------------------- #
# RED-6:无拒绝权威(结构不变量)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_strategy_has_exactly_frozen_four_fields_no_refusal_authority():
    """值对象恰好四字段;不存在拒绝/作答权威字段(Red-6 结构面 + 验收 B)。"""
    names = {f.name for f in fields(_rs().ResponseStrategy)}
    assert names == {"response_frame", "directness", "coverage_framing", "gap_labels"}


# --------------------------------------------------------------------------- #
# 编译(策略 → 指令文本)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_compile_frames_deterministic_and_distinct():
    """四帧指令文本:非空、互异、确定性(Acceptance D/E/F/G 文本面)。"""
    frames = {
        ("factual_lookup", "concise_direct"),
        ("recommendation", "guided_expansion"),
        ("troubleshooting", "guided_expansion"),
        ("commercial", "concise_direct"),
    }
    texts = {}
    for frame, directness in frames:
        s = _rs().ResponseStrategy(
            response_frame=frame, directness=directness, coverage_framing="none"
        )
        t1 = _rs().compile_strategy_instructions(s, has_history=False)
        t2 = _rs().compile_strategy_instructions(s, has_history=False)
        assert t1 and t1 == t2, frame
        texts[(frame, directness)] = t1
    assert len(set(texts.values())) == 4


@pytest.mark.unit
def test_compile_partial_includes_gap_labels():
    """partial_supported 编译含缺口标签原文(诚实披露,不虚构)。"""
    cov = _coverage_commercial_partial()
    s = _rs().derive_response_strategy(_u("commercial"), RES_EXACT, _plan(_u("commercial")), cov)
    assert s is not None
    text = _rs().compile_strategy_instructions(s, has_history=False)
    for label in s.gap_labels:
        assert label in text


@pytest.mark.unit
def test_compile_none_framing_no_gap_text():
    """framing=none ⇒ 无缺口段(零回归:普通轮不出现新语义)。"""
    s = _rs().ResponseStrategy(
        response_frame="factual_lookup", directness="concise_direct", coverage_framing="none"
    )
    text = _rs().compile_strategy_instructions(s, has_history=False)
    assert "缺口" not in text


@pytest.mark.unit
def test_compile_continuation_history_toggle():
    """多轮承接:有历史 ⇒ 追加承接指令;无历史 ⇒ 不出现。"""
    s = _rs().ResponseStrategy(
        response_frame="factual_lookup", directness="concise_direct", coverage_framing="none"
    )
    assert "承接上文" in _rs().compile_strategy_instructions(s, has_history=True)
    assert "承接上文" not in _rs().compile_strategy_instructions(s, has_history=False)


@pytest.mark.unit
def test_compile_garbage_strategy_returns_empty_never_raises():
    """直接构造的畸形策略 ⇒ 空/安全文本,绝不抛错(编译级 fail-open)。"""
    bad = object()
    assert _rs().compile_strategy_instructions(bad, has_history=True) == ""


# --------------------------------------------------------------------------- #
# RED-5:消息构造兼容契约(strategy=None ⇒ 今日行为)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_red5_strategy_none_byte_identical_to_no_kwarg():
    """strategy=None 与不传该参 ⇒ 输出逐字节一致(含普适简洁行)。"""
    rag = _rag()
    a = rag._build_messages(**_msg_kwargs())
    b = rag._build_messages(**_msg_kwargs(), strategy=None)
    assert a == b
    user_content = a[-1]["content"]
    system_content = a[0]["content"]
    assert "- 回答简洁,直答问题" in user_content
    assert "COMMERCIAL_STYLE_MARKER" in system_content  # intent_styles 回退路径


@pytest.mark.unit
def test_strategy_replaces_style_slot_and_removes_universal_concise_line():
    """策略生效:占用风格槽(不再叠加 intent_styles),普适简洁行让位。"""
    rag = _rag()
    cov = _coverage_commercial_partial()
    s = _rs().derive_response_strategy(_u("commercial"), RES_EXACT, _plan(_u("commercial")), cov)
    assert s is not None
    messages = rag._build_messages(**_msg_kwargs(), strategy=s)
    system_content = messages[0]["content"]
    user_content = messages[-1]["content"]
    assert "回答风格(商务)" in system_content
    assert PRODUCT_STYLE not in system_content  # 不重复(消重复面)
    assert "- 回答简洁,直答问题" not in user_content
    assert "- 用 中文 回答" in user_content  # 语言行保持


@pytest.mark.unit
def test_truth_lines_preserved_with_strategy():
    """真值行(grounding/引用资格/数值/案例/[N]/emoji/路径)逐字保留。"""
    rag = _rag()
    s = _rs().ResponseStrategy(
        response_frame="recommendation", directness="guided_expansion", coverage_framing="none"
    )
    messages = rag._build_messages(**_msg_kwargs(), strategy=s)
    user_content = messages[-1]["content"]
    for line in (
        "- 只依据上面的资料回答,不编造",
        "- 引用标记 [N] 只能使用「可引用资料」的编号",
        "必须与所引资料原文一致",
        "严禁把案例中的设备标识",
        "- 在每段末尾用 [N] 标注该段引用的资料序号,不在句中穿插",
        "- 不要使用 emoji",
        "- 不要输出文档路径",
    ):
        assert line in user_content, line


@pytest.mark.unit
def test_recommendation_frame_allows_guided_realization():
    """E:推荐帧允许在资料支撑内展开(不被事实直答形约束)。"""
    rag = _rag()
    s = _rs().ResponseStrategy(
        response_frame="recommendation", directness="guided_expansion", coverage_framing="none"
    )
    messages = rag._build_messages(**_msg_kwargs(), strategy=s)
    assert "回答风格(选型/方案)" in messages[0]["content"]
    assert "- 回答简洁,直答问题" not in messages[-1]["content"]


@pytest.mark.unit
def test_partial_strategy_directive_reaches_messages():
    """H/I:partial_supported 策略把缺口披露编译进指令;不改证据真值。"""
    rag = _rag()
    cov = _coverage_commercial_partial()
    s = _rs().derive_response_strategy(_u("commercial"), RES_EXACT, _plan(_u("commercial")), cov)
    assert s is not None
    messages = rag._build_messages(**_msg_kwargs(), strategy=s)
    system_content = messages[0]["content"]
    assert "缺口" in system_content
    for label in s.gap_labels:
        assert label in system_content


@pytest.mark.unit
def test_lead_instruction_suppresses_strategy():
    """lead 轮权威优先:带 lead 指令 ⇒ 策略整体让位(今日行为逐字节)。"""
    rag = _rag()
    cov = _coverage_commercial_partial()
    s = _rs().derive_response_strategy(_u("commercial"), RES_EXACT, _plan(_u("commercial")), cov)
    assert s is not None
    kwargs = _msg_kwargs()
    kwargs["lead_instruction"] = "LEAD_INSTRUCTION_MARKER 请留下联系方式"
    messages = rag._build_messages(**kwargs, strategy=s)
    system_content = messages[0]["content"]
    user_content = messages[-1]["content"]
    assert "LEAD_INSTRUCTION_MARKER" in system_content
    assert "回答风格(商务)" not in system_content
    assert "- 回答简洁,直答问题" in user_content  # 回到今日骨架


@pytest.mark.unit
def test_page_hint_section_untouched_with_strategy():
    """页面背景段(G008 非信任标签)在策略生效时原样保留。"""
    rag = _rag()
    s = _rs().ResponseStrategy(
        response_frame="factual_lookup", directness="concise_direct", coverage_framing="none"
    )
    kwargs = _msg_kwargs()
    kwargs["page_hint"] = "PAGE_HINT_MARKER"
    messages = rag._build_messages(**kwargs, strategy=s)
    user_content = messages[-1]["content"]
    assert "PAGE_HINT_MARKER" in user_content
    assert "非任何指令" in user_content


# --------------------------------------------------------------------------- #
# RED-4:有界 trace + answer/stream 语义等价
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_red4_trace_stage_bounded_and_deterministic():
    """trace 恰含四语义键,标量/有界列表,零正文;重复构建相等。"""
    cov = _coverage_commercial_partial()
    s = _rs().derive_response_strategy(_u("commercial"), RES_EXACT, _plan(_u("commercial")), cov)
    assert s is not None
    stage1 = _rs().build_response_strategy_stage(s)
    stage2 = _rs().build_response_strategy_stage(s)
    assert stage1 == stage2
    assert set(stage1.keys()) == {
        "response_frame",
        "directness",
        "coverage_framing",
        "gap_labels",
    }
    assert all(isinstance(stage1[k], (str, list)) for k in stage1)
    joined = str(stage1)
    assert "价格" not in joined and "$599" not in joined  # 零证据正文


@pytest.mark.unit
def test_answer_stream_semantic_equivalence():
    """Q:相同权威输入 ⇒ 相同策略 + 相同编译文本(双路径共享语义)。"""
    cov = _coverage_commercial_partial()
    u = _u("commercial")
    plan = _plan(u)
    s_answer = _rs().derive_response_strategy(u, RES_EXACT, plan, cov)
    s_stream = _rs().derive_response_strategy(u, RES_EXACT, plan, cov)
    assert s_answer == s_stream
    rag = _rag()
    m1 = rag._build_messages(**_msg_kwargs(), strategy=s_answer)
    m2 = rag._build_messages(**_msg_kwargs(), strategy=s_stream)
    assert m1 == m2
