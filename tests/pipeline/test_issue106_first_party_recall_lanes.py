"""Issue #106 — first-party Solution/Case 页 role-aware pre-pool recall lane。

生产实证(v1.6.3-r9 #31 Production Acceptance Wave,#31 comment 5771555940):

- AD1:官方 Solution 页 ``solutions/infrastructure-monitoring/`` indexed+active,
  但 EN 0/78、ZH 0/85 融合池缺席 —— 三路召回(主 hybrid / 符号 / intent
  boost)全部是查询相似度竞争,弱相关权威页整页落榜;已接受的
  ``SOLUTION_RETENTION_FLOOR`` 保位只能作用于**池内**成员,上游 recall
  缺失使其无从发力。缺陷在 **pre-pool**。
- AD2/AD9:EN 融合池含 NexAscent first-party case(rank 6);ZH 等价查询
  0/85 无 case 页,内部历史支持工单占据 case 证据位 —— EN/ZH 证据类
  系统性分裂。
- AC5:NeoMind 模型 OCR 权威文档不在生产账本(独立诊断,见执行报告)。

修复语义(本文件钉 WHAT):

- role-recall lane:证据计划含 SOLUTION_GUIDE / CASE_EVIDENCE 槽时,
  first-party Solution / Case-study 页凭 URL 段结构信号获得类内确定性
  准入(语言无关、非 exact-URL、有界预算),成员须通过与 post-pool 同源
  的 authority 谓词校验;
- first-party case 优先:CASE_EVIDENCE 槽在 first-party 页池内可得而
  幸存者中无 first-party 形态时,内部票不得独占 case 证明位(晋升最优
  first-party;first-party 不存在时既有语义零变化);
- EN/ZH 等价查询获得语义等价的 authority-role coverage。
"""

import json

import pytest

from backend.pipeline.evidence_planning import (
    CITATION_BACKGROUND_ALLOWED,
    EvidenceSlot,
    ROLE_CASE_EVIDENCE,
)
from backend.pipeline.evidence_reservation import reserve_required_slots
from backend.pipeline.evidence_selection import evidence_matches_slot
from backend.pipeline.rag import RAGOrchestrator
from backend.retrieval.rerank import RerankPipeline
from backend.retrieval.search import SearchResult

pytestmark = pytest.mark.unit

QUERY_ZH = "我是做水表业务的,请推荐适合我的一套 OCR 抄表解决方案"
QUERY_EN = "We run a water utility. Recommend an OCR meter-reading solution for us."

#: role lane 预算上限(#106:有界;每 lane 一次检索、limit ≤ 10)
LANE_BUDGET_LIMIT = 10


# --------------------------------------------------------------------------- #
# 夹具(结构性事实:source_type / product / title / url 决定角色语义)
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


#: 第一方官方 Solution 页(生产索引已核验;与查询主题弱相关 → 全局落榜)
SOLUTION_PAGE = _sr(
    "camthink-site/solutions/infrastructure-monitoring",
    "web_crawl",
    "ne101",
    "Infrastructure Monitoring Solution",
    "SOLUTION-PAGE: scheduled visual capture, edge OCR, MQTT/HTTP output, proven deployment.",
    url="https://www.camthink.ai/solutions/infrastructure-monitoring/",
    chunk_type="heading",
)

#: 第一方公开 case-study 页(生产索引已核验;EN 可入池 ZH 落榜的生产不对称面)
CASE_PAGE = _sr(
    "camthink-site/case-studies/nexascent-water-meter-ocr-ne101",
    "web_crawl",
    "ne101",
    "Non-Contact Water Meter OCR: How NexAscent Uses NE101",
    "CASE-PAGE: NE101 scheduled non-contact capture, 4G LTE upload, MeterOCR processing.",
    url="https://www.camthink.ai/case-studies/nexascent-water-meter-ocr-ne101/",
)

#: 内部历史支持工单(合法 case 证据,但非 first-party 落地证明)
INTERNAL_TICKET = _sr(
    "kb/ticket-water-meter-ocr",
    "filesystem",
    "knowledge",
    "案例:水表 OCR 方案咨询",
    "TICKET: 历史工单正文。",
)

#: URL 携带 solution 段信号但 title/章节无 solution 信号的页(不得冒充)
IMPOSTOR_PAGE = _sr(
    "camthink-site/blog/our-solution-to-delivery",
    "web_crawl",
    "ne101",
    "Delivery Logistics Notes",
    "BLOG: 无方案语义的普通博文。",
    url="https://www.camthink.ai/blog/our-solution-to-delivery/",
)


def _spec_chunk(i: int) -> SearchResult:
    return _sr(
        f"site/ne101-spec-{i:02d}",
        "website",
        "ne101",
        f"NE101 Datasheet Part {i}",
        "SPEC-DOC: NE101 hardware specification facts.",
    )


class _Searcher:
    """Weaviate 边界脚本:hybrid 池 + 桶调用记录 + URL 段 lane 分发。

    ``lane_pages`` 模拟真实 Weaviate 行为:URL 段过滤后的类内检索在**小类内**
    排序 —— 权威段页面必然在座(这正是 lane 准入与全局相似度竞争解耦的
    机制化)。lane 检索异常可注入(fail-open 归因用)。
    """

    def __init__(
        self,
        pool: list[SearchResult],
        lane_pages: dict[str, list[SearchResult]] | None = None,
        lane_error: Exception | None = None,
    ):
        self._pool = list(pool)
        self._lane_pages = lane_pages or {}
        self._lane_error = lane_error
        self.bucket_calls: list[dict] = []

    def search(self, **kw):
        return list(self._pool)

    def search_symbols(self, **kw):
        return []

    def search_bucket(self, **kw):
        self.bucket_calls.append(kw)
        if self._lane_error is not None and kw.get("url_substrings"):
            raise self._lane_error
        for signal, pages in self._lane_pages.items():
            if any(signal in s for s in (kw.get("url_substrings") or [])):
                return list(pages)
        return []


class _ScriptedInner:
    """真实 RerankPipeline 内层:按文本标记给确定性分。"""

    def __init__(self, scores: dict[str, float]):
        self._scores = scores

    def rerank(self, query, documents):
        return [
            next((v for k, v in self._scores.items() if k in d), 0.1)
            for d in documents
        ]


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


def _make_llm(payload: dict):
    from unittest.mock import AsyncMock, MagicMock

    llm = AsyncMock()
    llm.generate.return_value = MagicMock(content=json.dumps(payload, ensure_ascii=False))

    async def _stream(messages, **kwargs):
        yield "答案 [1]"

    llm.stream = _stream
    return llm


def _rag(
    pool: list[SearchResult],
    scores: dict[str, float],
    *,
    lane_pages: dict[str, list[SearchResult]] | None = None,
    lane_error: Exception | None = None,
    payload: dict | None = None,
) -> RAGOrchestrator:
    return RAGOrchestrator(
        _Searcher(pool, lane_pages=lane_pages, lane_error=lane_error),
        RerankPipeline(_ScriptedInner(scores)),
        _make_llm(payload or _payload("product", "recommendation")),
        system_prompt="sys",
        min_results_to_answer=1,
    )


def _lane_calls(searcher: _Searcher) -> list[dict]:
    return [c for c in searcher.bucket_calls if c.get("url_substrings")]


def _final_ids(result) -> set[tuple[str, int]]:
    return {(r.source_id, r.chunk_index) for r in result.reranked_results}


#: 方案查询夹具:hybrid/boost 全局竞争不召回 Solution/Case 页(生产形状),
#: 两页只能经 role lane 准入;rerank 阈下(生产实证形态)。
def _production_shape_rag(*, query_payload: dict | None = None, lane_pages: dict[str, list[SearchResult]] | None = None) -> RAGOrchestrator:
    pool = [_spec_chunk(i) for i in range(6)] + [INTERNAL_TICKET]
    return _rag(
        pool,
        {"SPEC-DOC": 0.92, "TICKET": 0.80, "SOLUTION-PAGE": 0.20, "CASE-PAGE": 0.20},
        lane_pages=lane_pages or {"solution": [SOLUTION_PAGE], "case-stud": [CASE_PAGE]},
        payload=query_payload,
    )


# --------------------------------------------------------------------------- #
# AC1/AC2:官方 Solution 页 pre-pool 准入(ZH 生产形状)
# --------------------------------------------------------------------------- #


async def test_solution_page_admitted_for_zh_solution_query():
    """AD1 GREEN 面:方案查询的终局上下文必须含 first-party Solution 页。"""
    rag = _production_shape_rag()
    result = await rag.answer(QUERY_ZH, "widget")
    assert result.is_answered
    assert (SOLUTION_PAGE.source_id, SOLUTION_PAGE.chunk_index) in _final_ids(result), (
        "AC2: an indexed, active first-party Solution page must have a "
        "deterministic pre-pool admission opportunity for solution queries; "
        "post-pool retention alone cannot restore evidence that never enters "
        "the fused pool (production: EN 0/78, ZH 0/85)"
    )


async def test_solution_lane_recorded_in_trace_attribution():
    """出账:role lane 的调用/预算/命中随检索阶段可归因。"""
    rag = _production_shape_rag()
    await rag.answer(QUERY_ZH, "widget")
    calls = _lane_calls(rag._searcher)
    names = [c for c in calls if "solution" in (c.get("url_substrings") or [])]
    assert names, "solution lane must be exercised for solution queries"
    assert all((c.get("limit") or 0) <= LANE_BUDGET_LIMIT for c in calls), (
        "cost guard: role lane budget must stay bounded"
    )


# --------------------------------------------------------------------------- #
# AC3:first-party Case 准入 + 内部票不得独占(ZH 生产不对称面)
# --------------------------------------------------------------------------- #


async def test_first_party_case_admitted_for_zh_query_despite_internal_tickets():
    """AD2/AD9 GREEN 面:ZH 方案查询终局须含 first-party case 页。"""
    rag = _production_shape_rag()
    result = await rag.answer(QUERY_ZH, "widget")
    ids = _final_ids(result)
    assert (CASE_PAGE.source_id, CASE_PAGE.chunk_index) in ids, (
        "AC3: matching first-party Case evidence must have a deterministic "
        "recall/admission opportunity across equivalent queries; internal "
        "tickets surviving in the context must not be the only case-shaped "
        "evidence while a first-party case page exists"
    )
    assert (INTERNAL_TICKET.source_id, INTERNAL_TICKET.chunk_index) in ids, (
        "internal case evidence remains eligible for the roles it truthfully "
        "proves; first-party admission must not evict it"
    )


async def test_lane_member_without_authority_signal_is_not_admitted():
    """authority integrity:URL 段信号命中但无 solution 语义的页不得入池。"""
    rag = _rag(
        [_spec_chunk(i) for i in range(4)],
        {"SPEC-DOC": 0.92, "BLOG": 0.10},
        lane_pages={"solution": [IMPOSTOR_PAGE]},
    )
    result = await rag.answer(QUERY_ZH, "widget")
    assert (IMPOSTOR_PAGE.source_id, IMPOSTOR_PAGE.chunk_index) not in _final_ids(
        result
    ), "authority integrity: URL-signal hits must still pass the same "
    "solution-authority predicate as post-pool matching"


# --------------------------------------------------------------------------- #
# AC4:EN/ZH 语义等价 authority-role coverage
# --------------------------------------------------------------------------- #


async def test_en_zh_equivalent_queries_equivalent_role_coverage():
    """AC4:等价意图的两语言查询获得等价的 role coverage(不要求候选全同)。

    coverage 面 = Solution + first-party Case + Product/Wiki 规格证据。
    model/use-case authority 按执行报告 AC5 裁决 = EXTERNAL_CONTENT_GAP
    (上游无该文档),不在断言面内。
    """
    zh = await _production_shape_rag().answer(QUERY_ZH, "widget")
    en = await _production_shape_rag().answer(QUERY_EN, "widget")
    zh_ids = _final_ids(zh)
    en_ids = _final_ids(en)
    assert (SOLUTION_PAGE.source_id, 0) in zh_ids
    assert (SOLUTION_PAGE.source_id, 0) in en_ids, (
        "AC4: EN equivalent query must admit the official Solution page too"
    )
    assert (CASE_PAGE.source_id, 0) in zh_ids
    assert (CASE_PAGE.source_id, 0) in en_ids, (
        "AC4: EN/ZH must not systematically diverge by evidence class"
    )
    assert any(sid.startswith("site/ne101-spec") for sid, _ in zh_ids)
    assert any(sid.startswith("site/ne101-spec") for sid, _ in en_ids), (
        "AC4: Product/Wiki evidence role stays covered in both languages"
    )


# --------------------------------------------------------------------------- #
# 负面边界 / 对抗矩阵
# --------------------------------------------------------------------------- #


async def test_factual_queries_trigger_no_role_lane():
    """negative boundary:非方案/选型意图零 lane 触发,召回面不扩大。"""
    rag = _production_shape_rag(query_payload=_payload("product", "factual"))
    await rag.answer("NE101 的防护等级是多少?", "widget")
    assert _lane_calls(rag._searcher) == [], (
        "negative boundary: factual spec queries must not widen recall with "
        "role lanes"
    )


async def test_support_queries_trigger_no_role_lane():
    """negative boundary(#78 契约冻结):support 查询零 lane 触发。"""
    rag = _production_shape_rag(query_payload=_payload("support", "factual"))
    await rag.answer("NE101 蜂窝网络注册失败怎么排查?", "widget")
    assert _lane_calls(rag._searcher) == [], (
        "negative boundary: support queries must keep the frozen #78 bucket "
        "contract without role-lane widening"
    )


async def test_lane_failure_fails_open_without_breaking_answer():
    """fail-closed 纪律:lane 检索异常降级(与既有 boost 桶同纪律),不伪造证据。"""
    rag = _production_shape_rag()
    rag._searcher._lane_error = RuntimeError("weaviate lane boom")
    result = await rag.answer(QUERY_ZH, "widget")
    assert result.is_answered, "lane failure must degrade, not break the answer path"


async def test_repeated_answer_is_idempotent():
    """idempotency:同查询重复执行不产生状态漂移。"""
    rag = _production_shape_rag()
    first = await rag.answer(QUERY_ZH, "widget")
    second = await rag.answer(QUERY_ZH, "widget")
    assert _final_ids(first) == _final_ids(second)


# --------------------------------------------------------------------------- #
# R1 first-party case 优先(单元级;直接钉保留语义)
# --------------------------------------------------------------------------- #


def _case_slot(*, required: bool = False) -> EvidenceSlot:
    return EvidenceSlot(
        role=ROLE_CASE_EVIDENCE,
        required=required,
        citation_requirement=CITATION_BACKGROUND_ALLOWED,
    )


def test_r1_promotes_first_party_case_when_only_internal_ticket_survives():
    """内部票幸存 + first-party 池内可得 → 晋升 first-party(阈下正相关即可)。"""
    ticket = INTERNAL_TICKET
    promoted, fired = reserve_required_slots(
        EvidencePlanStub([_case_slot()]),
        survivors=[ticket],
        pool_scores=[(ticket, 0.80), (CASE_PAGE, 0.20)],
        taxonomy=None,
        threshold=0.3,
    )
    ids = {(r.source_id, r.chunk_index) for r in promoted}
    assert (CASE_PAGE.source_id, CASE_PAGE.chunk_index) in ids, (
        "AC3: when a first-party case is pool-available, an internal ticket "
        "must not silently substitute for it in the deployment-proof role"
    )
    assert any(f.get("rule") == "R1_first_party_case" for f in fired)


def test_r1_case_stays_unpromoted_when_no_first_party_page_exists():
    """first-party 不存在 → 既有语义零变化(optional 槽零动作)。"""
    ticket = INTERNAL_TICKET
    promoted, fired = reserve_required_slots(
        EvidencePlanStub([_case_slot()]),
        survivors=[ticket],
        pool_scores=[(ticket, 0.80)],
        taxonomy=None,
        threshold=0.3,
    )
    assert promoted == []
    assert not any(f.get("rule") == "R1_first_party_case" for f in fired)


def test_r1_case_zero_action_when_first_party_already_survives():
    """first-party 已幸存 → 零动作(不改既有排序;不重复晋升)。"""
    ticket = INTERNAL_TICKET
    promoted, fired = reserve_required_slots(
        EvidencePlanStub([_case_slot()]),
        survivors=[CASE_PAGE, ticket],
        pool_scores=[(CASE_PAGE, 0.75), (ticket, 0.80)],
        taxonomy=None,
        threshold=0.3,
    )
    assert promoted == []
    assert not any(f.get("rule") == "R1_first_party_case" for f in fired)


def test_case_slot_matching_predicate_still_gates_first_party_page():
    """既有资格保真(#31 B2-4):published case 页匹配 CASE_EVIDENCE 槽。"""
    slot = _case_slot()
    assert evidence_matches_slot(slot, CASE_PAGE, resolution_targets=("ne101",)) is True


class EvidencePlanStub:
    """reserve_required_slots 的最小计划入参(槽位 + 空 resolution)。"""

    def __init__(self, slots):
        self.slots = slots
        self.resolution_targets = ()
