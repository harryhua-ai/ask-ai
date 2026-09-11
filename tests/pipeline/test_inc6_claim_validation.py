"""INC-6 主张—证据验证 v1 契约测试(RED 先行 + A-T 验收矩阵)。

覆盖(冻结契约语义):
- 每个引用标记的 claim-window 产出显式四态结果:SUPPORTED / UNSUPPORTED /
  UNVALIDATABLE / NOT_APPLICABLE + 有界 reason codes;
- UNVALIDATABLE/NOT_APPLICABLE 不得计入 SUPPORTED(计数不变量);
- citation_no → 完整稳定身份集(源级编号,一对多,不择一);
- 身份 → INC-5 slot matched 的完整角色集(不坍缩多角色;未命中=空集不伪造);
- 既有强制行为零回归(悬空/数值无据/产品不合格剔除、链接/围栏/跨 token、
  只剔标记不改正文);
- 流式与非流式验证语义等价;trace 有界零正文;
- NEW_LLM_CALLS = 0。
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.pipeline.citation import CitationStreamFilter, validate_citations
from backend.pipeline.rag import RAGOrchestrator
from backend.retrieval.search import SearchResult

FACTUAL_Q = "NE503 的价格是多少?"
RECO_Q = "我们在找一款适合仓库温控监测的设备,帮我推荐选型"
PRICE_Q = "NE503 多少钱?"


def _sr(
    source_id: str,
    source_type: str = "website",
    product: str = "ne503",
    title: str = "NE503 产品页",
    text: str = "价格 $599。",
    *,
    url: str = "",
    chunk_index: int = 0,
    score: float = 0.9,
) -> SearchResult:
    return SearchResult(
        text=text,
        source_id=source_id,
        source_type=source_type,
        product=product,
        title=title,
        url=url or f"https://example.com/{source_id}",
        score=score,
        chunk_index=chunk_index,
    )


STORE_NE503 = _sr("store/ne503", "woocommerce", "ne503", "NE503 智能网关", "价格 $599。")
SPEC_NE503 = _sr("site/ne503-spec", "website", "ne503", "NE503 规格书", "接口 RS485,重量 500g。")


def _rag(
    payload: dict, candidates: list[SearchResult], answer: str = "价格 599 元 [1]。"
) -> RAGOrchestrator:
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
            return MagicMock(content=json.dumps(payload, ensure_ascii=False))
        return MagicMock(content=answer)

    llm.generate = AsyncMock(side_effect=_generate)

    async def _stream(messages, **kwargs):
        yield answer

    llm.stream = _stream
    return RAGOrchestrator(searcher, reranker, llm, system_prompt="s", min_results_to_answer=1)


_COMMERCIAL = {
    "category": "commercial",
    "reason": "r",
    "confidence": 0.9,
    "interaction_mode": "standard",
    "evidence_intent": "factual",
    "extracted_query": PRICE_Q,
    "rewritten_query": PRICE_Q,
}


def _claim_validation(trace: dict) -> dict:
    return trace["stages"]["citation_integrity"]["claim_validation"]


# --------------------------------------------------------------------------- #
# RED-1/2:结果语义缺失(无确定性条件 ≠ 支持;空窗 ≠ 支持)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_red1_nonnumeric_window_is_unvalidatable_not_supported():
    """真实主张窗口、无显著数值 → 无确定性必要条件可证 ⇒ UNVALIDATABLE,
    不得计为 SUPPORTED;标记保留(既有行为)。"""
    f = CitationStreamFilter(n_sources=1, source_texts={1: ["价格 599 元"]})
    out = f.feed("该设备支持多种外部接口,适合工业部署 [1]")
    out += f.finish()
    counts = f.stats["outcome_counts"]
    assert counts["UNVALIDATABLE"] == 1
    assert counts["SUPPORTED"] == 0
    assert "[1]" in out  # 标记保留(行为不变),但真值如实
    events = f.stats["validation_events"]
    assert events[0]["outcome"] == "UNVALIDATABLE"
    assert events[0]["reason"] == "no_deterministic_necessary_condition"


@pytest.mark.unit
def test_red2_vacuous_window_is_not_applicable_not_supported():
    """空/纯空白窗口的标记 ⇒ NOT_APPLICABLE/vacuous_window,不得计为 SUPPORTED;
    标记可见行为保持(v1 不新增剔除策略)。"""
    f = CitationStreamFilter(n_sources=1, source_texts={1: ["价格 599 元"]})
    out = f.feed("[1] 价格 599 元")
    out += f.finish()
    counts = f.stats["outcome_counts"]
    assert counts["NOT_APPLICABLE"] == 1
    assert counts["SUPPORTED"] == 0
    assert "[1]" in out


# --------------------------------------------------------------------------- #
# RED-5/6/7:既有剔除行为 → UNSUPPORTED + 显式 reason(行为零变更)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_red5_numeric_unsupported_is_unsupported_with_reason():
    f = CitationStreamFilter(n_sources=1, source_texts={1: ["价格 599 元"]})
    out = f.feed("价格 999 元 [1]")
    out += f.finish()
    assert "[1]" not in out  # 既有剔除不变
    assert "价格 999 元" in out  # 只剔标记,不改正文
    counts = f.stats["outcome_counts"]
    assert counts["UNSUPPORTED"] == 1
    assert counts["SUPPORTED"] == 0
    assert f.stats["validation_events"][0]["reason"] == "numeric_unsupported"


@pytest.mark.unit
def test_red6_product_ineligible_is_unsupported_with_reason():
    f = CitationStreamFilter(
        n_sources=1,
        source_texts={1: ["价格 599 元"]},
        source_products={1: "ne301"},
        eligible_slugs={"ne503"},
    )
    out = f.feed("价格 599 元 [1]")
    out += f.finish()
    assert "[1]" not in out
    assert f.stats["validation_events"][0]["outcome"] == "UNSUPPORTED"
    assert f.stats["validation_events"][0]["reason"] == "product_ineligible"


@pytest.mark.unit
def test_red7_dangling_marker_is_unsupported_with_reason():
    f = CitationStreamFilter(n_sources=1, source_texts={1: ["价格 599 元"]})
    out = f.feed("价格 599 元 [2]")
    out += f.finish()
    assert "[2]" not in out
    assert f.stats["validation_events"][0]["outcome"] == "UNSUPPORTED"
    assert f.stats["validation_events"][0]["reason"] == "dangling_marker"


# --------------------------------------------------------------------------- #
# RED-3/4:角色归因缺失(多角色完整保留 / 未命中=空集不伪造)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_red3_multirole_citation_gets_complete_role_set():
    """woocommerce 证据同时命中 STORE_OFFICIAL(required)与 PRODUCT_SPEC(optional):
    归因=完整角色集 multi_role,不坍缩为单一角色。"""
    rag = _rag(_COMMERCIAL, [STORE_NE503])
    result = await rag.answer(PRICE_Q, "widget")
    cv = _claim_validation(result.trace_payload)
    attr = cv["role_attribution"]["1"]
    assert set(attr["roles"]) == {"STORE_OFFICIAL", "PRODUCT_SPEC"}
    assert attr["attribution"] == "multi_role"
    # 数值支持窗口 → SUPPORTED(确定性)
    assert cv["outcome_counts"]["SUPPORTED"] == 1
    assert cv["validation_events"][0]["outcome"] == "SUPPORTED"


@pytest.mark.unit
def test_red4_unmatched_citable_evidence_gets_empty_role_set():
    """终局可引用身份未命中任何 slot(matched=∅)→ 空角色集 unattributed,
    绝不伪造角色;coverage=None(无计划)同理全 unattributed。"""
    from backend.pipeline.claim_validation import build_role_attribution
    from backend.pipeline.evidence_selection import build_coverage_report
    from backend.pipeline.evidence_planning import derive_evidence_plan
    from backend.pipeline.product_resolver import ProductResolution
    from backend.pipeline.task_understanding import TaskUnderstanding

    citable = [{"source_id": "site/x", "chunk_index": 0, "citation_no": 1}]
    # 命中面:coverage 存在但身份不在任何 matched
    u = TaskUnderstanding(
        category="product",
        reason="r",
        confidence=0.9,
        extracted_query="q",
        rewritten_query="q",
    )
    plan = derive_evidence_plan(u, ProductResolution("exact", ("ne503",), "query"))
    other = _sr("site/other", "website", "platform-x", title="平台说明")
    coverage = build_coverage_report(plan, [other], taxonomy=None)  # platform-x ∉ scope
    attr = build_role_attribution(citable, coverage)
    assert attr["1"]["roles"] == []
    assert attr["1"]["attribution"] == "unattributed"
    # 无计划(coverage=None)→ 全部 unattributed,不伪造
    attr_none = build_role_attribution(citable, None)
    assert attr_none["1"]["roles"] == []
    assert attr_none["1"]["attribution"] == "unattributed"


# --------------------------------------------------------------------------- #
# A-T 验收矩阵
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_acceptance_a_valid_numeric_supported():
    """A:数值在源文本中可得 → SUPPORTED(确定性必要条件通过)。"""
    f = CitationStreamFilter(n_sources=1, source_texts={1: ["价格 599 元"]})
    out = f.feed("价格 599 元 [1]")
    out += f.finish()
    assert "[1]" in out
    assert f.stats["outcome_counts"]["SUPPORTED"] == 1
    assert f.stats["validation_events"][0]["reason"] == "all_checks_passed"


@pytest.mark.unit
def test_acceptance_g_marker_removal_never_rewrites_claim_text():
    """G:剔除只发生在标记本身;主张文本逐字保留(含数值)。"""
    f = CitationStreamFilter(n_sources=1, source_texts={1: ["价格 599 元"]})
    out = f.feed("价格 999 元,支持宽温 [1]")
    out += f.finish()
    assert out == "价格 999 元,支持宽温 "


@pytest.mark.unit
def test_acceptance_h_one_citation_no_maps_multiple_identities():
    """H:同源多 chunk 共享 citation_no;归因保留全部身份(不择一)。"""
    from backend.pipeline.claim_validation import build_role_attribution

    citable = [
        {"source_id": "site/x", "chunk_index": 0, "citation_no": 1},
        {"source_id": "site/x", "chunk_index": 1, "citation_no": 1},
    ]
    attr = build_role_attribution(citable, None)
    assert len(attr["1"]["identities"]) == 2
    assert {"source_id": "site/x", "chunk_index": 0} in attr["1"]["identities"]
    assert {"source_id": "site/x", "chunk_index": 1} in attr["1"]["identities"]


@pytest.mark.unit
def test_acceptance_i_j_identity_multirole_preserved():
    """I/J:一身份多角色 → 全部保留;attribution=multi_role。"""
    from backend.pipeline.claim_validation import build_role_attribution
    from backend.pipeline.evidence_planning import derive_evidence_plan
    from backend.pipeline.evidence_selection import build_coverage_report
    from backend.pipeline.product_resolver import ProductResolution
    from backend.pipeline.task_understanding import TaskUnderstanding

    u = TaskUnderstanding(
        category="commercial",
        reason="r",
        confidence=0.9,
        extracted_query="q",
        rewritten_query="q",
    )
    plan = derive_evidence_plan(u, ProductResolution("exact", ("ne503",), "query"))
    coverage = build_coverage_report(plan, [STORE_NE503], taxonomy=None)
    citable = [{"source_id": STORE_NE503.source_id, "chunk_index": 0, "citation_no": 1}]
    attr = build_role_attribution(citable, coverage)
    assert set(attr["1"]["roles"]) == {"STORE_OFFICIAL", "PRODUCT_SPEC"}
    assert attr["1"]["attribution"] == "multi_role"


@pytest.mark.unit
def test_acceptance_l_store_role_only_from_inc5_matched():
    """L:STORE_OFFICIAL 归因只来自 INC-5 matched 到该角色的身份;wiki 块不因
    提及价格而获得 STORE 角色。"""
    from backend.pipeline.claim_validation import build_role_attribution
    from backend.pipeline.evidence_planning import derive_evidence_plan
    from backend.pipeline.evidence_selection import build_coverage_report
    from backend.pipeline.product_resolver import ProductResolution
    from backend.pipeline.task_understanding import TaskUnderstanding

    u = TaskUnderstanding(
        category="commercial",
        reason="r",
        confidence=0.9,
        extracted_query="q",
        rewritten_query="q",
    )
    plan = derive_evidence_plan(u, ProductResolution("exact", ("ne503",), "query"))
    wiki_price = _sr("github-wiki/price", "github", "ne503", "价格说明", "售价 599。")
    coverage = build_coverage_report(plan, [wiki_price], taxonomy=None)
    citable = [{"source_id": wiki_price.source_id, "chunk_index": 0, "citation_no": 1}]
    attr = build_role_attribution(citable, coverage)
    assert "STORE_OFFICIAL" not in attr["1"]["roles"]
    assert "PRODUCT_SPEC" in attr["1"]["roles"]


@pytest.mark.unit
def test_acceptance_m_solution_role_only_from_inc5_matched():
    """M:SOLUTION_GUIDE 归因只来自 INC-5 方案匹配语义;通用规格不获得。"""
    from backend.pipeline.claim_validation import build_role_attribution
    from backend.pipeline.evidence_planning import derive_evidence_plan
    from backend.pipeline.evidence_selection import build_coverage_report
    from backend.pipeline.product_resolver import ProductResolution
    from backend.pipeline.task_understanding import TaskUnderstanding

    u = TaskUnderstanding(
        category="product",
        reason="r",
        confidence=0.9,
        evidence_intent="recommendation",
        extracted_query="q",
        rewritten_query="q",
    )
    plan = derive_evidence_plan(u, ProductResolution("exact", ("ne503",), "query"))
    solution = _sr("site/reco", "website", "ne503", "仓库温控选型方案", "推荐 NE503。")
    coverage = build_coverage_report(plan, [solution], taxonomy=None)
    citable = [{"source_id": solution.source_id, "chunk_index": 0, "citation_no": 1}]
    attr = build_role_attribution(citable, coverage)
    assert set(attr["1"]["roles"]) == {"SOLUTION_GUIDE", "PRODUCT_SPEC"}


@pytest.mark.unit
def test_acceptance_o_background_never_numbered():
    """O:背景证据不在 citable(无编号)→ 角色归因无条目,绝不升格。"""
    from backend.pipeline.claim_validation import build_role_attribution

    # citable 只含可引用身份;filesystem 背景块根本不该出现在输入里
    citable = [{"source_id": "site/x", "chunk_index": 0, "citation_no": 1}]
    attr = build_role_attribution(citable, None)
    assert "kb/ticket-1" not in {i["source_id"] for ids in attr.values() for i in ids["identities"]}


@pytest.mark.unit
def test_acceptance_r_trace_bounded_no_chunk_body():
    """R:验证事件有界(≤32)且不含 chunk 正文;截断有显式标记。"""
    f = CitationStreamFilter(n_sources=1, source_texts={1: ["价格 599 元"]})
    long_claim = "无显著数值的主张窗口。" * 40
    text = "".join(f"{long_claim} [{i % 9 + 1}]" for i in range(40))
    f.feed(text)
    f.finish()
    assert len(f.stats["validation_events"]) <= 32
    assert f.stats["validation_events_truncated"] is True
    body = json.dumps(f.stats["validation_events"], ensure_ascii=False)
    assert "599" not in body  # 源文本未泄漏(窗口只记字符数)
    for ev in f.stats["validation_events"]:
        assert set(ev.keys()) == {"citation_no", "outcome", "reason", "window_chars"}


@pytest.mark.unit
def test_acceptance_s_counters_consistent_and_compatible():
    """S:既有计数器保留;UNSUPPORTED 计数=三类剔除之和;N/A 不进 SUPPORTED。
    段首空窗(标记紧邻段首)⇒ NOT_APPLICABLE。"""
    f = CitationStreamFilter(n_sources=2, source_texts={1: ["价格 599 元"], 2: ["接口 RS485"]})
    text = "[1] 价格 999 元 [1] 支持 [3] 无条件主张 [2]"
    f.feed(text)
    f.finish()
    s = f.stats
    assert s["markers_seen"] == 4
    assert s["unsupported_dropped"] == 1  # 999 无据
    assert s["dangling_dropped"] == 1  # [3] 越界
    c = s["outcome_counts"]
    assert (
        c["UNSUPPORTED"]
        == s["dangling_dropped"] + s["unsupported_dropped"] + s["ineligible_product_dropped"]
    )
    assert c["UNVALIDATABLE"] == 1  # "无条件主张" 无显著数值
    assert c["NOT_APPLICABLE"] == 1  # 段首空窗
    assert c["SUPPORTED"] == 0  # N/A 与 UNVALIDATABLE 均不得计入 SUPPORTED


# --------------------------------------------------------------------------- #
# P:流式/非流式验证语义等价 + 管线级接线
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_acceptance_p_stream_and_answer_validation_parity():
    """P:等价条件下 answer 与 stream 产出等价 claim_validation(含角色归因)。"""
    rag_a = _rag(_COMMERCIAL, [STORE_NE503])
    result = await rag_a.answer(PRICE_Q, "widget")

    rag_s = _rag(_COMMERCIAL, [STORE_NE503])
    events = []
    async for raw in rag_s.stream_answer(PRICE_Q, "widget"):
        events.append(json.loads(raw))
    complete = [e for e in events if e["type"] == "complete"][-1]

    cv_answer = _claim_validation(result.trace_payload)
    cv_stream = _claim_validation(complete["trace_payload"])
    assert cv_answer["outcome_counts"] == cv_stream["outcome_counts"]
    assert cv_answer["validation_events"] == cv_stream["validation_events"]
    assert cv_answer["role_attribution"] == cv_stream["role_attribution"]


@pytest.mark.unit
async def test_acceptance_t_zero_incremental_llm_calls():
    """T:总 generate 调用 = 1 理解 + 1 生成,验证零 LLM。"""
    rag = _rag(_COMMERCIAL, [STORE_NE503])
    await rag.answer(PRICE_Q, "widget")
    assert len(rag._llm.generate.call_args_list) == 2
