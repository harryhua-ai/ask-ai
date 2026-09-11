"""INC-5 确定性证据选择与组合契约测试(RED 先行 + A-R 验收矩阵)。

覆盖(冻结契约语义):
- RED-1..4 缺失能力证明(实现后转 GREEN):required SOLUTION_GUIDE 不可被
  通用规格证据虚假覆盖 / STORE_OFFICIAL 不可被 wiki 替代 / 比较单侧缺失
  不得全量覆盖 / CASE_EVIDENCE 背景可用 ≠ 公开引用权威;
- 角色匹配谓词(仅持久化结构事实:source_type / title / doc_section);
- 产品隔离(§8)+ resolver 权威不取代;
- 引用/信任语义(CITABLE_REQUIRED 只可被可公开引用证据满足;BACKGROUND_ALLOWED
  不自动升格为公开引用权威);
- 覆盖真值 = 终局生成上下文事实(被剪掉/被上下文截断的证据不得继续计入覆盖);
- required 优先的稳定选择(不删证据、不新增检索、不改既有剪枝/排名约束);
- answer/stream parity、零新增 LLM、fail-open(无新全局拒答)。

性能契约:选择/覆盖为纯本地确定性函数(零 IO/零 LLM),不新增串行往返。
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.pipeline.rag import RAGOrchestrator
from backend.pipeline.task_understanding import understand_task
from backend.retrieval.search import SearchResult

FACTUAL_Q = "NE503 的包装清单里有什么?"
RECO_Q = "我们在找一款适合仓库温控监测的设备,帮我推荐选型"
SUPPORT_Q = "设备蜂窝网络注册失败怎么办"
PRICE_Q = "NE503 多少钱"
CMP_Q = "NE301 和 NE503 有什么区别?"

_ROLE_PRODUCT_SPEC = "PRODUCT_SPEC"
_ROLE_SOLUTION_GUIDE = "SOLUTION_GUIDE"
_ROLE_CASE_EVIDENCE = "CASE_EVIDENCE"
_ROLE_STORE_OFFICIAL = "STORE_OFFICIAL"


# --------------------------------------------------------------------------- #
# 证据夹具(结构性事实:source_type / product / title 决定角色语义)
# --------------------------------------------------------------------------- #


def _sr(
    source_id: str,
    source_type: str,
    product: str,
    title: str,
    text: str = "正文",
    *,
    url: str = "",
    chunk_index: int = 0,
    score: float = 0.9,
    chunk_type: str = "paragraph",
    doc_section: str = "",
    channel_visibility: tuple[str, ...] = ("widget", "api"),
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
        chunk_type=chunk_type,
        doc_section=doc_section,
        channel_visibility=channel_visibility,
    )


SPEC_NE503 = _sr("site/ne503-spec", "website", "ne503", "NE503 产品规格书", "NE503 接口:RS485×2。")
SPEC_NE301 = _sr("site/ne301-spec", "website", "ne301", "NE301 产品规格书", "NE301 接口:RS485×2。")
SOLUTION_NE503 = _sr(
    "site/reco-solution",
    "website",
    "ne503",
    "仓库温控监控选型方案",
    "推荐 NE503 作为仓库温控网关。",
)
WIKI_PRICE = _sr(
    "github-wiki/price-notes",
    "github",
    "ne503",
    "NE503 价格说明",
    "NE503 售价 $599(历史文档)。",
)
STORE_NE503 = _sr("store/ne503-gw", "woocommerce", "ne503", "NE503 智能分析网关", "价格 $599。")
CASE_TICKET = _sr(
    "kb/ticket-128", "filesystem", "knowledge", "案例:蜂窝注册失败排查", "历史工单案例正文。"
)


# --------------------------------------------------------------------------- #
# 编排器夹具(与 INC-4 契约测试同构:mock 理解 LLM + 检索面)
# --------------------------------------------------------------------------- #


def _make_llm(payload: dict) -> AsyncMock:
    llm = AsyncMock()
    llm.generate.return_value = MagicMock(content=json.dumps(payload, ensure_ascii=False))

    async def _stream(messages, **kwargs):
        yield "答案 [1]"

    llm.stream = _stream
    return llm


def _payload(category: str, intent: str) -> dict:
    return {
        "category": category,
        "reason": "r",
        "confidence": 0.9,
        "interaction_mode": "standard",
        "evidence_intent": intent,
        "extracted_query": "q",
        "rewritten_query": "q",
    }


def _rag(payload: dict, candidates: list[SearchResult]) -> RAGOrchestrator:
    searcher = MagicMock()
    searcher.search.return_value = list(candidates)
    searcher.search_symbols.return_value = []
    searcher.search_bucket.return_value = []
    reranker = MagicMock()
    reranker.rerank.side_effect = lambda q, results, top_k=None: list(results)[: top_k or 10]
    reranker.rerank_scored.side_effect = lambda q, results, top_k=None: (list(results)[: top_k or 10], [])
    return RAGOrchestrator(
        searcher, reranker, _make_llm(payload), system_prompt="s", min_results_to_answer=1
    )


def _coverage(result):
    return result.trace_payload["stages"]["evidence"]["coverage"]


def _slots(cov):
    return {s["role"]: s for s in cov["slots"]}


def _ids(matched):
    return {(m["source_id"], m["chunk_index"]) for m in matched}


async def _collect(rag, query, **kwargs):
    events = []
    async for raw in rag.stream_answer(query, "widget", **kwargs):
        events.append(json.loads(raw))
    return events


# --------------------------------------------------------------------------- #
# RED-1:required SOLUTION_GUIDE 缺失时必须可观察,规格证据不得虚假覆盖
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_red1_recommendation_missing_solution_evidence_is_truthful():
    """只有通用规格证据时:SOLUTION_GUIDE uncovered + 缺失可观察;生成 fail-open。"""
    rag = _rag(_payload("product", "recommendation"), [SPEC_NE503])
    result = await rag.answer(RECO_Q, "widget")
    cov = _coverage(result)
    slots = _slots(cov)
    assert cov["coverage_complete"] is False
    assert cov["required_covered"] == 0
    assert slots[_ROLE_SOLUTION_GUIDE]["covered"] is False
    assert slots[_ROLE_SOLUTION_GUIDE]["required"] is True
    assert _ids(slots[_ROLE_SOLUTION_GUIDE]["matched"]) == set()
    assert _ROLE_SOLUTION_GUIDE in cov["missing_required"]
    # 通用规格证据不得顶替 SOLUTION_GUIDE(可匹配其自身角色,而非方案槽)
    assert slots[_ROLE_PRODUCT_SPEC]["covered"] is True
    # N:缺 required 仍用有效证据生成,无新全局拒答
    assert result.is_answered is True


@pytest.mark.unit
async def test_red1b_real_solution_evidence_covers_required_solution_slot():
    """真实方案/选型证据(结构性标题信号)可覆盖 required SOLUTION_GUIDE → complete。"""
    rag = _rag(_payload("product", "recommendation"), [SPEC_NE503, SOLUTION_NE503])
    result = await rag.answer(RECO_Q, "widget")
    cov = _coverage(result)
    slots = _slots(cov)
    assert slots[_ROLE_SOLUTION_GUIDE]["covered"] is True
    assert cov["coverage_complete"] is True
    assert result.is_answered is True


# --------------------------------------------------------------------------- #
# RED-2:STORE_OFFICIAL 不可被 wiki/通用文档虚假覆盖
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_red2_store_official_not_covered_by_wiki_price_evidence():
    """只有 wiki 价格证据时:STORE_OFFICIAL uncovered(带价格文本也不行);fail-open。"""
    rag = _rag(_payload("commercial", "factual"), [WIKI_PRICE])
    result = await rag.answer(PRICE_Q, "widget")
    cov = _coverage(result)
    slots = _slots(cov)
    assert slots[_ROLE_STORE_OFFICIAL]["covered"] is False
    assert slots[_ROLE_STORE_OFFICIAL]["required"] is True
    assert _ids(slots[_ROLE_STORE_OFFICIAL]["matched"]) == set()
    # missing_required 携带解析域标签(如 STORE_OFFICIAL(ne503)),角色前缀可观察
    assert any(m.split("(")[0] == _ROLE_STORE_OFFICIAL for m in cov["missing_required"])
    assert cov["coverage_complete"] is False
    # wiki 证据按其真实角色(规格/文档)参与,不冒充 Store 当局
    assert slots[_ROLE_PRODUCT_SPEC]["covered"] is True
    assert result.is_answered is True


@pytest.mark.unit
async def test_acceptance_e_legitimate_store_evidence_covers_store_official():
    """E:合法 Store(woocommerce)证据覆盖 required STORE_OFFICIAL → complete。"""
    rag = _rag(_payload("commercial", "factual"), [STORE_NE503])
    result = await rag.answer(PRICE_Q, "widget")
    cov = _coverage(result)
    slots = _slots(cov)
    assert slots[_ROLE_STORE_OFFICIAL]["covered"] is True
    assert _ids(slots[_ROLE_STORE_OFFICIAL]["matched"]) == {(STORE_NE503.source_id, 0)}
    assert cov["coverage_complete"] is True
    assert result.is_answered is True


# --------------------------------------------------------------------------- #
# RED-3:比较单侧缺失 → 覆盖不得为 complete(专用比较管线保持,只补真值)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_red3_comparison_partial_evidence_cannot_be_complete():
    """比较要求 A+B,最终证据只支持 A:B 槽 uncovered、不得全量覆盖;
    既有 D-preflight 拒答语义保持(is_answered=False)。"""
    rag = _rag(_payload("product", "factual"), [SPEC_NE301])
    result = await rag.answer(CMP_Q, "widget")
    # Q:既有比较证据契约保持(缺侧显式不足,不静默降级)
    assert result.is_answered is False
    cov = _coverage(result)
    assert cov["coverage_complete"] is False
    by_scope = {tuple(s["product_scope"]): s for s in cov["slots"]}
    missing_side = by_scope[("ne503",)]
    assert missing_side["covered"] is False
    assert _ids(missing_side["matched"]) == set()
    # A 侧证据在候选中可匹配,但生成被拒 → 未进入终局上下文 → 不得计为已覆盖
    a_side = by_scope[("ne301",)]
    assert _ids(a_side["matched"]) == {(SPEC_NE301.source_id, SPEC_NE301.chunk_index)}
    assert a_side["covered"] is False


# --------------------------------------------------------------------------- #
# RED-4(2026-09-11 #28 修订):CASE_EVIDENCE 与引用权威的关系
# 旧契约「案例证据一律背景、永无公开引用权威」已被 #28 收窄为:
# 第一方知识案例(filesystem+knowledge,无 internal 标记)= 有编号可引用、
# 路径置空;其余 filesystem(非 knowledge 或显式 internal)维持背景语义。
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_red4_case_evidence_background_without_citation_authority():
    """#28 修订:知识案例证据覆盖 CASE_EVIDENCE 槽且进入公开编号引用权威
    (标题展示、路径置空);非 knowledge 的 filesystem 仍无引用权威。"""
    plain_internal = _sr(
        "kb/attachment-9", "filesystem", "ne503", "内部附件", "非知识库内部文件正文。"
    )
    rag = _rag(_payload("support", "factual"), [CASE_TICKET, SPEC_NE503, plain_internal])
    result = await rag.answer(SUPPORT_Q, "widget")
    cov = _coverage(result)
    slots = _slots(cov)
    assert slots[_ROLE_CASE_EVIDENCE]["covered"] is True
    # CASE 槽按来源类型(filesystem)匹配:知识案例与普通内部附件都在槽覆盖内;
    # 引用权威的差异在下方 citable 集合断言(#28 只豁免 knowledge 案例)
    assert _ids(slots[_ROLE_CASE_EVIDENCE]["matched"]) == {
        (CASE_TICKET.source_id, 0),
        (plain_internal.source_id, 0),
    }
    # 引用权威真值(#28):第一方知识案例进入可编号集合;规格证据在;
    # 非 knowledge 的 filesystem 仍被排除在编号权威之外
    cite = result.trace_payload["stages"]["citation_integrity"]
    citable_ids = {(c["source_id"], c["chunk_index"]) for c in cite["citable"]}
    assert (CASE_TICKET.source_id, CASE_TICKET.chunk_index) in citable_ids
    assert (SPEC_NE503.source_id, SPEC_NE503.chunk_index) in citable_ids
    assert (plain_internal.source_id, plain_internal.chunk_index) not in citable_ids
    # 访客可见 sources:知识案例以 path-less 条目呈现,内部附件不出现
    case_sources = [s for s in result.sources if s["type"] == "filesystem"]
    assert len(case_sources) == 1
    assert case_sources[0]["url"] == ""
    assert case_sources[0]["title"] == CASE_TICKET.title
    assert all(s["type"] != "filesystem" or s["url"] == "" for s in result.sources)
    assert result.is_answered is True


@pytest.mark.unit
async def test_red4b_citable_required_slot_never_satisfied_by_background_chunk():
    """CITABLE_REQUIRED 槽永不被仅背景资格的证据满足(信任语义单元面)。"""
    from backend.pipeline.citation import PUBLIC_SOURCE_TYPES
    from backend.pipeline.evidence_planning import (
        CITATION_CITABLE_REQUIRED,
        EvidenceSlot,
    )
    from backend.pipeline.evidence_selection import evidence_matches_slot

    background_chunk = CASE_TICKET
    citable_slot = EvidenceSlot(
        role=_ROLE_PRODUCT_SPEC,
        required=True,
        citation_requirement=CITATION_CITABLE_REQUIRED,
    )
    assert background_chunk.source_type not in PUBLIC_SOURCE_TYPES
    assert evidence_matches_slot(citable_slot, background_chunk, resolution_targets=()) is False


# --------------------------------------------------------------------------- #
# A-R 验收矩阵(单元面:纯函数语义)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_acceptance_a_factual_product_lookup_covered_by_scoped_spec():
    """A:PRODUCT_SPEC 由正确域内产品证据覆盖。"""
    from backend.pipeline.evidence_planning import EvidenceSlot
    from backend.pipeline.evidence_selection import evidence_matches_slot

    slot = EvidenceSlot(role=_ROLE_PRODUCT_SPEC, required=True)
    assert evidence_matches_slot(slot, SPEC_NE503, resolution_targets=("ne503",)) is True


@pytest.mark.unit
def test_acceptance_b_solution_evidence_matches_solution_role():
    """B:方案/选型结构性信号(title)使证据可匹配 SOLUTION_GUIDE。"""
    from backend.pipeline.evidence_planning import EvidenceSlot
    from backend.pipeline.evidence_selection import evidence_matches_slot

    slot = EvidenceSlot(role=_ROLE_SOLUTION_GUIDE, required=True)
    assert evidence_matches_slot(slot, SOLUTION_NE503, resolution_targets=("ne503",)) is True
    assert evidence_matches_slot(slot, SPEC_NE503, resolution_targets=("ne503",)) is False


@pytest.mark.unit
def test_acceptance_c_generic_spec_never_satisfies_solution_slot():
    """C(单元面):无方案信号的通用规格不得匹配 SOLUTION_GUIDE。"""
    from backend.pipeline.evidence_planning import EvidenceSlot
    from backend.pipeline.evidence_selection import evidence_matches_slot

    slot = EvidenceSlot(role=_ROLE_SOLUTION_GUIDE, required=True)
    for title in ("NE503 产品规格书", "NE503 datasheet", "NE503 包装清单", "NE503 用户手册"):
        chunk = _sr("site/x", "website", "ne503", title)
        assert evidence_matches_slot(slot, chunk, resolution_targets=()) is False


@pytest.mark.unit
def test_acceptance_d_case_slot_allows_background_disposition():
    """D:CASE_EVIDENCE(BACKGROUND_ALLOWED)由 filesystem 案例匹配;非案例源不冒充。"""
    from backend.pipeline.evidence_planning import (
        CITATION_BACKGROUND_ALLOWED,
        EvidenceSlot,
    )
    from backend.pipeline.evidence_selection import evidence_matches_slot

    slot = EvidenceSlot(
        role=_ROLE_CASE_EVIDENCE, required=False, citation_requirement=CITATION_BACKGROUND_ALLOWED
    )
    assert evidence_matches_slot(slot, CASE_TICKET, resolution_targets=()) is True
    assert evidence_matches_slot(slot, SPEC_NE503, resolution_targets=()) is False


@pytest.mark.unit
def test_acceptance_f_wiki_store_role_predicates_are_disjoint():
    """F(单元面):wiki(github)与 Store(woocommerce)角色谓词互斥。"""
    from backend.pipeline.evidence_planning import EvidenceSlot
    from backend.pipeline.evidence_selection import evidence_matches_slot

    store_slot = EvidenceSlot(role=_ROLE_STORE_OFFICIAL, required=True)
    spec_slot = EvidenceSlot(role=_ROLE_PRODUCT_SPEC, required=True)
    assert evidence_matches_slot(store_slot, WIKI_PRICE, resolution_targets=("ne503",)) is False
    assert evidence_matches_slot(store_slot, STORE_NE503, resolution_targets=("ne503",)) is True
    assert evidence_matches_slot(spec_slot, STORE_NE503, resolution_targets=("ne503",)) is True


@pytest.mark.unit
def test_acceptance_i_product_isolation_unrelated_product_cannot_cover():
    """I:产品 X 的证据不满足 scope=Y 的槽位;空 scope 继承 resolver 目标。"""
    from backend.pipeline.evidence_planning import EvidenceSlot
    from backend.pipeline.evidence_selection import evidence_matches_slot

    scoped = EvidenceSlot(role=_ROLE_PRODUCT_SPEC, required=True, product_scope=("ne503",))
    assert evidence_matches_slot(scoped, SPEC_NE301, resolution_targets=()) is False
    inherited = EvidenceSlot(role=_ROLE_PRODUCT_SPEC, required=True)
    # 空 scope → 继承 resolver 目标 (ne301,);ne503 证据不得顶替
    assert evidence_matches_slot(inherited, SPEC_NE503, resolution_targets=("ne301",)) is False
    assert evidence_matches_slot(inherited, SPEC_NE301, resolution_targets=("ne301",)) is True


@pytest.mark.unit
def test_acceptance_i_case_role_is_cross_product_by_design():
    """I(角色语义):CASE_EVIDENCE 空域 = 跨产品设计(support 案例存于 knowledge 域),
    不继承 resolver 产品域(既有知识桶设计事实)。"""
    from backend.pipeline.evidence_planning import (
        CITATION_BACKGROUND_ALLOWED,
        EvidenceSlot,
    )
    from backend.pipeline.evidence_selection import evidence_matches_slot

    slot = EvidenceSlot(
        role=_ROLE_CASE_EVIDENCE, required=False, citation_requirement=CITATION_BACKGROUND_ALLOWED
    )
    assert evidence_matches_slot(slot, CASE_TICKET, resolution_targets=("ne503",)) is True


@pytest.mark.unit
def test_acceptance_k_missing_optional_slot_keeps_coverage_complete():
    """K:缺失 optional 槽不影响 coverage_complete。"""
    from backend.pipeline.evidence_planning import derive_evidence_plan
    from backend.pipeline.evidence_selection import build_coverage_report
    from backend.pipeline.product_resolver import ProductResolution
    from backend.pipeline.task_understanding import TaskUnderstanding

    u = TaskUnderstanding(
        category="support",
        reason="r",
        confidence=0.9,
        extracted_query="q",
        rewritten_query="q",
    )
    plan = derive_evidence_plan(u, ProductResolution("none", (), "none"))
    assert all(s.required is False for s in plan.slots)
    report = build_coverage_report(plan, [], taxonomy=None)
    assert report.required_total == 0
    assert report.coverage_complete is True


@pytest.mark.unit
def test_acceptance_l_duplicate_identity_not_duplicated():
    """L:同一稳定身份不错误重复——去重权威在既有上游(rrf_fuse 以
    (source_id, chunk_index) 去重、比较合并 seen-set);INC-5 组合是稳定排列,
    构造上不可能新增重复(身份多重集精确保持)。"""
    from backend.pipeline.evidence_planning import derive_evidence_plan
    from backend.pipeline.evidence_selection import order_candidates_for_plan
    from backend.pipeline.product_resolver import ProductResolution
    from backend.pipeline.task_understanding import TaskUnderstanding
    from backend.retrieval.rrf import rrf_fuse

    # 上游权威去重实证:同身份双代表在融合处塌缩为单代表
    dup = _sr(
        SPEC_NE503.source_id,
        SPEC_NE503.source_type,
        "ne503",
        SPEC_NE503.title,
        chunk_index=SPEC_NE503.chunk_index,
    )
    fused = rrf_fuse([SPEC_NE503, dup])
    assert [(r.source_id, r.chunk_index) for r in fused] == [(SPEC_NE503.source_id, 0)]

    # INC-5 组合:身份多重集精确保持(既不复制、也不静默丢弃不同证据)
    u = TaskUnderstanding(
        category="product",
        reason="r",
        confidence=0.9,
        extracted_query="q",
        rewritten_query="q",
    )
    plan = derive_evidence_plan(u, ProductResolution("exact", ("ne503",), "query"))
    other = _sr("site/other", "website", "ne503", "NE503 说明书")
    ordered, _info = order_candidates_for_plan(plan, [SPEC_NE503, other], taxonomy=None)
    assert sorted((r.source_id, r.chunk_index) for r in ordered) == sorted(
        [(SPEC_NE503.source_id, 0), (other.source_id, 0)]
    )


@pytest.mark.unit
def test_acceptance_m_removed_evidence_cannot_count_as_coverage():
    """M:被上下文丢弃(公开源超出可见集)的证据不得计入覆盖。"""
    from backend.pipeline.evidence_planning import EvidenceSlot, derive_evidence_plan
    from backend.pipeline.evidence_selection import build_coverage_report
    from backend.pipeline.product_resolver import ProductResolution
    from backend.pipeline.task_understanding import TaskUnderstanding

    u = TaskUnderstanding(
        category="product",
        reason="r",
        confidence=0.9,
        extracted_query="q",
        rewritten_query="q",
    )
    plan = derive_evidence_plan(u, ProductResolution("exact", ("ne503",), "query"))
    # 候选在,但其身份不在终局上下文(已被丢弃/剪除)
    report = build_coverage_report(
        plan, [SPEC_NE503], taxonomy=None, citable_ids=frozenset(), background_ids=frozenset()
    )
    assert report.slots[0].covered is False
    assert report.coverage_complete is False


@pytest.mark.unit
def test_acceptance_unknown_sensitivity_does_not_exclude_ordinary_evidence():
    """§7 信任修订:sensitivity=unknown(无 internal 标记的普通证据)本身不排除。"""
    from backend.pipeline.evidence_planning import EvidenceSlot
    from backend.pipeline.evidence_selection import evidence_matches_slot

    slot = EvidenceSlot(role=_ROLE_PRODUCT_SPEC, required=True)
    ordinary = _sr(
        "site/ordinary", "website", "ne503", "NE503 说明", channel_visibility=("widget", "api")
    )
    assert evidence_matches_slot(slot, ordinary, resolution_targets=("ne503",)) is True


# --------------------------------------------------------------------------- #
# 选择/组合语义(稳定、有界、不改既有约束)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_selection_prefers_required_slot_evidence_stably():
    """required 槽命中证据稳定前置;组内秩序保持;其余证据保留不删。"""
    from backend.pipeline.evidence_planning import derive_evidence_plan
    from backend.pipeline.evidence_selection import order_candidates_for_plan
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
    # 秩序:无关公开证据在前,方案证据殿后
    noise = _sr("site/noise", "website", "ne503", "NE503 新闻", score=0.99)
    ordered, info = order_candidates_for_plan(
        plan, [noise, SPEC_NE503, SOLUTION_NE503], taxonomy=None
    )
    keys = [(r.source_id, r.chunk_index) for r in ordered]
    assert keys[0] == (SOLUTION_NE503.source_id, 0)
    assert set(keys) == {
        (noise.source_id, 0),
        (SPEC_NE503.source_id, 0),
        (SOLUTION_NE503.source_id, 0),
    }
    assert info["required_matched"] >= 1


@pytest.mark.unit
def test_selection_empty_plan_is_identity():
    """空计划(零检索模式)→ 组合恒等,零行为变更。"""
    from backend.pipeline.evidence_planning import EvidencePlan
    from backend.pipeline.evidence_selection import order_candidates_for_plan

    ordered, info = order_candidates_for_plan(EvidencePlan(), [SPEC_NE503], taxonomy=None)
    assert [(r.source_id, r.chunk_index) for r in ordered] == [(SPEC_NE503.source_id, 0)]
    assert info["reordered"] is False


# --------------------------------------------------------------------------- #
# 覆盖语义补充:有界偏好使 required 证据进入可见集(终局上下文真值)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_selection_pulls_required_evidence_into_visible_context():
    """6 个公开源超可见上限 5:required 证据原排名殿后,组合后进入可见集并计入覆盖。"""
    noises = [
        _sr(f"site/noise-{i}", "website", "ne503", f"NE503 资讯 {i}", score=0.95) for i in range(5)
    ]
    candidates = [*noises, SOLUTION_NE503]
    rag = _rag(_payload("product", "recommendation"), candidates)
    result = await rag.answer(RECO_Q, "widget")
    cov = _coverage(result)
    slots = _slots(cov)
    # 组合偏好使方案证据进入访客可见 5 源 → 覆盖真值为 covered
    assert slots[_ROLE_SOLUTION_GUIDE]["covered"] is True
    assert cov["coverage_complete"] is True
    assert any(s["url"].endswith(SOLUTION_NE503.source_id) for s in result.sources)


# --------------------------------------------------------------------------- #
# O parity / P LLM 预算 / 空计划不产出证据阶段
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_acceptance_o_answer_stream_evidence_parity():
    """O:answer 与 stream 在等价条件下产出等价 selection/coverage 语义。"""
    candidates = [SPEC_NE503, SOLUTION_NE503]
    r1 = await _rag(_payload("product", "recommendation"), candidates).answer(RECO_Q, "widget")
    events = await _collect(_rag(_payload("product", "recommendation"), candidates), RECO_Q)
    complete = [e for e in events if e["type"] == "complete"][-1]
    assert r1.trace_payload["stages"]["evidence"] == complete["trace_payload"]["stages"]["evidence"]
    assert complete["trace_payload"]["stages"]["evidence"]["coverage"]["coverage_complete"] is True


@pytest.mark.unit
async def test_acceptance_p_zero_incremental_llm_calls():
    """P:总 generate 调用 = 1 理解 + 1 生成,选择/覆盖零 LLM。"""
    rag = _rag(_payload("product", "recommendation"), [SPEC_NE503, SOLUTION_NE503])
    await rag.answer(RECO_Q, "widget")
    assert len(rag._llm.generate.call_args_list) == 2


@pytest.mark.unit
async def test_no_evidence_reject_path_carries_honest_coverage():
    """无证据拒答路径携带诚实覆盖(全 uncovered、缺失可观察);无新全局拒答语义
    (既有拒答保持,只补真值)。零检索短路模式(澄清等)在 plan 之前返回,天然无
    evidence 阶段。"""
    rag = _rag(_payload("product", "factual"), [])
    result = await rag.answer(FACTUAL_Q, "widget")
    assert result.is_answered is False
    cov = _coverage(result)
    assert cov["coverage_complete"] is False
    assert cov["required_covered"] == 0
    assert cov["missing_required"], "缺 required 时 missing_required 必须可观察"


@pytest.mark.unit
async def test_acceptance_q_comparison_success_path_order_preserved():
    """Q:比较成功路径既有轮转均衡顺序不被选择器打乱(全部命中时组合恒等)。"""
    from backend.pipeline.evidence_selection import order_candidates_for_plan
    from backend.pipeline.evidence_planning import derive_evidence_plan
    from backend.pipeline.product_resolver import ProductResolution
    from backend.pipeline.task_understanding import TaskUnderstanding

    u = TaskUnderstanding(
        category="product",
        reason="r",
        confidence=0.9,
        extracted_query="q",
        rewritten_query="q",
    )
    plan = derive_evidence_plan(u, ProductResolution("comparison", ("ne301", "ne503"), "query"))
    # 比较证据 = 每 target 自己的规格证据(全部命中各自 required 槽);
    # 第二个 ne301 chunk 用不同 chunk_index(比较轮转合并本就按身份去重)
    spec_ne301_b = _sr(
        "site/ne301-spec",
        "website",
        "ne301",
        "NE301 产品规格书",
        chunk_index=1,
    )
    evidence = [SPEC_NE301, SPEC_NE503, spec_ne301_b]
    ordered, info = order_candidates_for_plan(plan, evidence, taxonomy=None)
    assert [(r.source_id, r.chunk_index) for r in ordered] == [
        (r.source_id, r.chunk_index) for r in evidence
    ]
    assert info["reordered"] is False
