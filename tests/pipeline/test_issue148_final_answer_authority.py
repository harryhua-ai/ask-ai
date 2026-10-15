"""Issue #148 — 方案类答案终局证据保留与引用正确归因(RED→GREEN)。

生产取证出处(#145 只读脱敏报告,2026-10-14,v1.6.4-r2 冻结会话):

- ZH 形态:官方 Solution 页 pre-pool rank 4(role:solution)、第一方 Case
  rank 10(role:case)均已入池;最终 selection 10 块双双缺席 ——
  SOLUTION_GUIDE required 槽被普通 Wiki 片段的泛化 "solution" 字样满足
  (R1 槽位已覆盖零动作),first-party Case 的 R1 晋升被组合截断逐出且无
  回填(CASE_EVIDENCE 槽被内部支持案例独占)。
- EN 形态:第一方 Case 已在终局上下文内(coverage CASE_EVIDENCE/
  PRODUCT_SPEC 均匹配)却没有引用编号 —— 可见 source 槽位(≤5)按位置
  分配被 Wiki + 内部知识案例占满,该页 chunk 按 dropped_public 丢弃,
  部署证明类 claim 的引用落在内部支持案例上(claim-to-authority 错误归因)。

修复语义(本文件钉 WHAT;机制 HOW 由实现决定):

- AC1:相关合规的第一方公开 Solution 页已入池且回答需要方案/架构指导时,
  终局上下文保留该一手方案证据;普通 Wiki 的泛化 solution 字样不得虚假
  替代;真实无匹配时零动作(fail-open,不强宣称)。
- AC2:第一方公开 Case 与内部支持案例同时入池且回答含已验证部署/实施
  证明时,终局证据与可见引用保留并优先该第一方公开 Case;EN/ZH 同类任务
  等价;内部案例仍按 #28 语义合法参与(标题呈现、不外泄路径、不冒充)。
- AC3:终局选择、可见 source 集、同步回答、流式 sources/complete、最终
  [N] 引用一致。

夹具纪律:非水表 solution-domain(冷链监测场景)、通用结构信号
(/solutions/、/case-studies/ URL 段 + 公开连接器类型)、语言无关 ——
无 exact-URL、无专有客户、无指定语言命中;权威页阈下形态与生产实证一致。
"""

import json

import pytest

from backend.pipeline.evidence_planning import (
    CITATION_BACKGROUND_ALLOWED,
    EvidenceSlot,
    ROLE_CASE_EVIDENCE,
    ROLE_SOLUTION_GUIDE,
)
from backend.pipeline.evidence_reservation import reserve_required_slots
from backend.pipeline.evidence_selection import (
    is_first_party_authority_page,
    is_first_party_solution_page,
)
from backend.pipeline.rag import RAGOrchestrator
from backend.retrieval.rerank import RerankPipeline
from backend.retrieval.search import SearchResult

pytestmark = pytest.mark.unit

QUERY_ZH = "我们是做冷链物流的,请推荐一套适合我们的温度监测 OCR 解决方案"
QUERY_EN = "We run cold-chain logistics. Recommend a temperature-monitoring OCR solution for us."


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


#: 第一方官方 Solution 页(/solutions/ 段结构信号;生产形态:阈下落榜)
OFFICIAL_SOLUTION = _sr(
    "iot-site/solutions/cold-chain-monitoring",
    "web_crawl",
    "tl300",
    "Cold Chain Monitoring Solution",
    "SOLUTION-PAGE: scheduled capture, edge OCR, MQTT/HTTP output, reference architecture.",
    url="https://www.example-iot.com/solutions/cold-chain-monitoring/",
    chunk_type="heading",
)

#: 第一方公开 case-study 页(已证部署证明;生产形态:阈下或幸存但零引用。
#: 标题不带 solution 词表信号 —— 与生产形态一致:权威身份只由 case-studies
#: URL 段结构事实承载)。
FIRST_PARTY_CASE = _sr(
    "iot-site/case-studies/freshlink-cold-chain-ocr",
    "web_crawl",
    "tl300",
    "Cold Chain OCR: How FreshLink Runs TL300",
    "CASE-PAGE: TL300 scheduled cold-chain capture, 4G upload, OCR processing, live deployment.",
    url="https://www.example-iot.com/case-studies/freshlink-cold-chain-ocr/",
)

#: 普通 Wiki 方案描述片段(合法方案证据,但非第一方官方 Solution 页;
#: 生产形态:凭泛化 solution 字样幸存并满足 SOLUTION_GUIDE 槽)
WIKI_SOLUTION_DESC = _sr(
    "github-docs/wiki-documents/4-edge-ai-solutions/1-monitoring/solution-description",
    "github",
    "tl300",
    "Solution Description",
    "WIKI: 方案描述正文(普通技术 wiki 片段)。",
    url="https://github.com/example-iot/wiki-documents/blob/main/4-edge-ai-solutions/1-monitoring/solution-description.md",
)

#: URL 携带 solution 字样但无方案语义的页(不得冒充官方 Solution 页)
IMPOSTOR_PAGE = _sr(
    "iot-site/blog/our-solution-to-delivery",
    "web_crawl",
    "tl300",
    "Delivery Logistics Notes",
    "BLOG: 无方案语义的普通博文。",
    url="https://www.example-iot.com/blog/our-solution-to-delivery/",
)


def _knowledge_case(i: int) -> SearchResult:
    return _sr(
        f"kb/ticket-cold-chain-{i:02d}",
        "filesystem",
        "knowledge",
        f"案例:冷库温度监测接入咨询 {i}",
        f"TICKET-{i}: 历史内部支持工单正文。",
    )


def _spec_chunk(i: int) -> SearchResult:
    return _sr(
        f"site/tl300-spec-{i:02d}",
        "website",
        "tl300",
        f"TL300 Datasheet Part {i}",
        "SPEC-DOC: TL300 hardware specification facts.",
    )


#: ZH 形态:10 个阈上幸存者占满 top_k(wiki + 内部知识案例为主,生产形态),
#: 两个第一方权威页阈下在池
#: (#145 ZH:Solution rank4 / Case rank10 入池,终局双双落榜)。
def _zh_pool() -> list[SearchResult]:
    return (
        [WIKI_SOLUTION_DESC]
        + [_knowledge_case(i) for i in range(4)]
        + [_spec_chunk(i) for i in range(5)]
        + [
            _sr(OFFICIAL_SOLUTION.source_id, OFFICIAL_SOLUTION.source_type,
                OFFICIAL_SOLUTION.product, OFFICIAL_SOLUTION.title,
                OFFICIAL_SOLUTION.text, url=OFFICIAL_SOLUTION.url,
                chunk_type=OFFICIAL_SOLUTION.chunk_type, score=0.20),
            _sr(FIRST_PARTY_CASE.source_id, FIRST_PARTY_CASE.source_type,
                FIRST_PARTY_CASE.product, FIRST_PARTY_CASE.title,
                FIRST_PARTY_CASE.text, url=FIRST_PARTY_CASE.url, score=0.20),
        ]
    )


#: EN 形态:第一方 Case 阈上幸存(#145 EN:rank1 入池进上下文但零引用),
#: 官方 Solution 页仍阈下在池。
def _en_pool() -> list[SearchResult]:
    return (
        [WIKI_SOLUTION_DESC]
        + [_knowledge_case(i) for i in range(4)]
        + [_spec_chunk(i) for i in range(4)]
        + [
            _sr(FIRST_PARTY_CASE.source_id, FIRST_PARTY_CASE.source_type,
                FIRST_PARTY_CASE.product, FIRST_PARTY_CASE.title,
                FIRST_PARTY_CASE.text, url=FIRST_PARTY_CASE.url, score=0.76),
            _sr(OFFICIAL_SOLUTION.source_id, OFFICIAL_SOLUTION.source_type,
                OFFICIAL_SOLUTION.product, OFFICIAL_SOLUTION.title,
                OFFICIAL_SOLUTION.text, url=OFFICIAL_SOLUTION.url,
                chunk_type=OFFICIAL_SOLUTION.chunk_type, score=0.20),
        ]
    )


def _make_llm(payload: dict):
    from unittest.mock import AsyncMock, MagicMock

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


class _Searcher:
    """Weaviate 边界脚本:返回固定 hybrid 池(#106 缺口已在 pre-pool 修复,
    本文件钉最终保留/引用层,池内成员即已入池形态)。"""

    def __init__(self, pool: list[SearchResult]):
        self._pool = list(pool)

    def search(self, **kw):
        return list(self._pool)

    def search_symbols(self, **kw):
        return []

    def search_bucket(self, **kw):
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


def _rag(pool: list[SearchResult], scores: dict[str, float]) -> RAGOrchestrator:
    return RAGOrchestrator(
        _Searcher(pool),
        RerankPipeline(_ScriptedInner(scores)),
        _make_llm(_payload("product", "recommendation")),
        system_prompt="sys",
        min_results_to_answer=1,
    )


#: 阈下权威页形态的脚本分数(幸存者全部阈上占满 top_k;内部知识案例分
#: 高于通用规格页 —— 生产 ZH 形态:终局证据面以 wiki+内部案例为主)。
_SUB_THRESHOLD_SCORES = {
    "SPEC-DOC": 0.78,
    "WIKI": 0.85,
    "TICKET": 0.82,
    "SOLUTION-PAGE": 0.20,
    "CASE-PAGE": 0.20,
}

#: EN 形态:case 页阈上(幸存者末位),官方 Solution 页仍阈下。
_EN_SCORES = {
    "SPEC-DOC": 0.78,
    "WIKI": 0.85,
    "TICKET": 0.83,
    "CASE-PAGE": 0.76,
    "SOLUTION-PAGE": 0.20,
}


def _final_ids(result) -> set[tuple[str, int]]:
    return {(r.source_id, r.chunk_index) for r in result.reranked_results}


def _source_urls(result) -> set[str]:
    return {s.get("url", "") for s in result.sources}


def _evidence_slots(result) -> dict[str, dict]:
    stages = (result.trace_payload or {}).get("stages", {})
    coverage = stages.get("evidence", {}).get("coverage", {})
    return {s["role"]: s for s in coverage.get("slots", [])}


# --------------------------------------------------------------------------- #
# AC1+AC2 — ZH 形态:入池的一手 Solution/Case 必须终局保留并获得可见引用
# --------------------------------------------------------------------------- #


async def test_zh_official_solution_and_first_party_case_retained_and_cited():
    """#145 ZH 形态 GREEN 面:两个权威页在池内时终局上下文与可见引用保留。"""
    rag = _rag(_zh_pool(), dict(_SUB_THRESHOLD_SCORES))
    result = await rag.answer(QUERY_ZH, "widget")
    assert result.is_answered
    ids = _final_ids(result)
    assert (OFFICIAL_SOLUTION.source_id, OFFICIAL_SOLUTION.chunk_index) in ids, (
        "AC1: a recalled, compliant first-party Solution page must survive "
        "final selection; a generic wiki fragment carrying the word 'solution' "
        "must not falsely substitute for it in the SOLUTION_GUIDE slot"
    )
    assert (FIRST_PARTY_CASE.source_id, FIRST_PARTY_CASE.chunk_index) in ids, (
        "AC2: a pool-available first-party published case must not be evicted "
        "by post-selection composition while internal support cases occupy "
        "the case-evidence slot"
    )
    urls = _source_urls(result)
    assert OFFICIAL_SOLUTION.url in urls, (
        "AC1: the retained official Solution page must be visitor-citable "
        "(visible source), not a dropped-public chunk"
    )
    assert FIRST_PARTY_CASE.url in urls, (
        "AC2: the first-party published case must hold a visible numbered "
        "source slot so deployment-proof claims can cite it"
    )
    slots = _evidence_slots(result)
    assert slots.get("SOLUTION_GUIDE", {}).get("covered") is True
    assert slots.get("CASE_EVIDENCE", {}).get("covered") is True


async def test_zh_internal_case_stays_citable_without_impersonation():
    """AC2:内部知识案例保留合法可引用参与(#28 语义零回退),且以标题
    呈现、不外泄文件系统路径 —— 不被一手权威页晋升挤出全部槽位后冒充。"""
    rag = _rag(_zh_pool(), dict(_SUB_THRESHOLD_SCORES))
    result = await rag.answer(QUERY_ZH, "widget")
    kb_sources = [s for s in result.sources if (s.get("source_id") or "").startswith("kb/")]
    assert kb_sources, (
        "#28: internal knowledge cases keep legitimate citable participation "
        "when no first-party authority competes for their slot"
    )
    for s in kb_sources:
        assert s.get("url") == "", "internal case must not leak filesystem paths"
        assert s.get("link_state") == "none"


# --------------------------------------------------------------------------- #
# AC2 — EN 形态:在上下文内的一手 Case 必须获得可见引用(不被内部案例顶替)
# --------------------------------------------------------------------------- #


async def test_en_in_context_first_party_case_receives_citation():
    """#145 EN 形态 GREEN 面:第一方 Case 幸存进终局上下文时必须进入可见
    source 集(编号可引用),不能按位置被 Wiki+内部案例占满的 5 槽挤出。"""
    rag = _rag(_en_pool(), dict(_EN_SCORES))
    result = await rag.answer(QUERY_EN, "widget")
    assert result.is_answered
    ids = _final_ids(result)
    assert (FIRST_PARTY_CASE.source_id, FIRST_PARTY_CASE.chunk_index) in ids, (
        "control: the first-party case survives selection in the EN shape "
        "(#145 production evidence)"
    )
    urls = _source_urls(result)
    assert FIRST_PARTY_CASE.url in urls, (
        "AC2: an in-context first-party published case must hold a visible "
        "source slot; positional allocation must not let internal cases crowd "
        "it into dropped-public while the deployment claim cites them instead"
    )
    slots = _evidence_slots(result)
    assert slots.get("CASE_EVIDENCE", {}).get("covered") is True


async def test_en_official_solution_page_also_retained_and_cited():
    """AC1 EN 侧:官方 Solution 页 EN 形态同样保留+可见(语言不丢权威)。"""
    rag = _rag(_en_pool(), dict(_EN_SCORES))
    result = await rag.answer(QUERY_EN, "widget")
    ids = _final_ids(result)
    assert (OFFICIAL_SOLUTION.source_id, OFFICIAL_SOLUTION.chunk_index) in ids
    assert OFFICIAL_SOLUTION.url in _source_urls(result)


async def test_en_zh_equivalent_tasks_keep_first_party_authorities():
    """AC2:同类方案任务不因语言不同丢失一手 Case/Solution 的可见引用。"""
    zh = await _rag(_zh_pool(), dict(_SUB_THRESHOLD_SCORES)).answer(QUERY_ZH, "widget")
    en = await _rag(_en_pool(), dict(_EN_SCORES)).answer(QUERY_EN, "widget")
    for result in (zh, en):
        urls = _source_urls(result)
        assert OFFICIAL_SOLUTION.url in urls
        assert FIRST_PARTY_CASE.url in urls


# --------------------------------------------------------------------------- #
# AC3 — 同步/流式一致:流式 sources 与同步 sources 同权威集
# --------------------------------------------------------------------------- #


async def test_stream_sources_parity_with_sync_authorities():
    """AC3:流式 sources 事件与同步路径保留同一权威来源集(complete 一致)。"""
    rag = _rag(_zh_pool(), dict(_SUB_THRESHOLD_SCORES))
    sync = await rag.answer(QUERY_ZH, "widget")
    streamed_sources = None
    complete = None
    async for event in rag.stream_answer(QUERY_ZH, "widget"):
        payload = json.loads(event)
        if payload.get("type") == "sources":
            streamed_sources = payload.get("sources")
        elif payload.get("type") == "complete":
            complete = payload
    assert streamed_sources is not None
    assert complete is not None and complete.get("is_answered") is True
    assert {s.get("url", "") for s in streamed_sources} == _source_urls(sync), (
        "AC3: streaming sources must carry the same first-party authority set "
        "as the synchronous path"
    )
    assert OFFICIAL_SOLUTION.url in {s.get("url", "") for s in streamed_sources}
    assert FIRST_PARTY_CASE.url in {s.get("url", "") for s in streamed_sources}


# --------------------------------------------------------------------------- #
# AC1 负面边界 — 真实无匹配时不强宣称(fail-open 零动作)
# --------------------------------------------------------------------------- #


async def test_no_authority_pages_in_pool_means_no_fabricated_sources():
    """AC1:池内确无官方 Solution/Case 页时零晋升、零伪造引用;Wiki 片段
    合法满足方案槽,内部案例继续合法参与。"""
    pool = [_spec_chunk(i) for i in range(4)] + [WIKI_SOLUTION_DESC] + [
        _knowledge_case(i) for i in range(4)
    ]
    rag = _rag(pool, dict(_SUB_THRESHOLD_SCORES))
    result = await rag.answer(QUERY_ZH, "widget")
    assert result.is_answered
    urls = _source_urls(result)
    assert not any("/solutions/" in u for u in urls)
    assert not any("case-stud" in u for u in urls)
    slots = _evidence_slots(result)
    assert slots.get("SOLUTION_GUIDE", {}).get("covered") is True, (
        "wiki solution fragment legitimately covers the slot when no official "
        "solution page exists (honest coverage, no false substitution claim)"
    )


async def test_threshold_qualified_authorities_stay_retained():
    """对照:权威页阈上时既有机制已保留 —— 修复不得破坏合格晋升路径。"""
    pool = (
        [_spec_chunk(i) for i in range(4)]
        + [WIKI_SOLUTION_DESC]
        + [_knowledge_case(i) for i in range(2)]
        + [OFFICIAL_SOLUTION, FIRST_PARTY_CASE]
    )
    scores = {"SPEC-DOC": 0.82, "WIKI": 0.85, "TICKET": 0.81,
              "SOLUTION-PAGE": 0.90, "CASE-PAGE": 0.89}
    rag = _rag(pool, scores)
    result = await rag.answer(QUERY_ZH, "widget")
    ids = _final_ids(result)
    assert (OFFICIAL_SOLUTION.source_id, OFFICIAL_SOLUTION.chunk_index) in ids
    assert (FIRST_PARTY_CASE.source_id, FIRST_PARTY_CASE.chunk_index) in ids
    assert OFFICIAL_SOLUTION.url in _source_urls(result)
    assert FIRST_PARTY_CASE.url in _source_urls(result)


async def test_impostor_solution_url_never_promoted_or_prioritized():
    """authority integrity:URL 带 solution 字样但无方案语义的页不得凭新
    规则晋升或抢占可见 source 槽位。"""
    pool = (
        [_spec_chunk(i) for i in range(4)]
        + [WIKI_SOLUTION_DESC]
        + [_knowledge_case(i) for i in range(4)]
        + [_sr(IMPOSTOR_PAGE.source_id, IMPOSTOR_PAGE.source_type,
               IMPOSTOR_PAGE.product, IMPOSTOR_PAGE.title, IMPOSTOR_PAGE.text,
               url=IMPOSTOR_PAGE.url, score=0.20)]
    )
    rag = _rag(pool, dict(_SUB_THRESHOLD_SCORES))
    result = await rag.answer(QUERY_ZH, "widget")
    ids = _final_ids(result)
    assert (IMPOSTOR_PAGE.source_id, IMPOSTOR_PAGE.chunk_index) not in ids
    assert IMPOSTOR_PAGE.url not in _source_urls(result)


# --------------------------------------------------------------------------- #
# 单元级 — R1 SOLUTION_GUIDE 角色槽互补性(泛化字样不虚假替代)
# --------------------------------------------------------------------------- #


def _solution_slot() -> EvidenceSlot:
    return EvidenceSlot(role=ROLE_SOLUTION_GUIDE, required=True)


def _case_slot(*, required: bool = False) -> EvidenceSlot:
    return EvidenceSlot(
        role=ROLE_CASE_EVIDENCE,
        required=required,
        citation_requirement=CITATION_BACKGROUND_ALLOWED,
    )


class _PlanStub:
    def __init__(self, slots):
        self.slots = slots
        self.resolution_targets = ()


def test_r1_promotes_official_solution_page_despite_generic_wiki_survivor():
    """泛化 wiki "solution" 字样幸存 + 官方 Solution 页池内阈下可得 →
    晋升官方页(正相关下限;普通 wiki 不得虚假替代)。"""
    promoted, fired = reserve_required_slots(
        _PlanStub([_solution_slot()]),
        survivors=[WIKI_SOLUTION_DESC],
        pool_scores=[(WIKI_SOLUTION_DESC, 0.85), (OFFICIAL_SOLUTION, 0.20)],
        taxonomy=None,
        threshold=0.3,
    )
    ids = {(r.source_id, r.chunk_index) for r in promoted}
    assert (OFFICIAL_SOLUTION.source_id, OFFICIAL_SOLUTION.chunk_index) in ids
    assert any(f.get("rule") == "R1_official_solution_page" for f in fired)


def test_r1_solution_zero_action_when_official_page_already_survives():
    """官方页已幸存 → 零动作(不重复晋升、不改既有排序)。"""
    promoted, fired = reserve_required_slots(
        _PlanStub([_solution_slot()]),
        survivors=[OFFICIAL_SOLUTION, WIKI_SOLUTION_DESC],
        pool_scores=[(OFFICIAL_SOLUTION, 0.75), (WIKI_SOLUTION_DESC, 0.85)],
        taxonomy=None,
        threshold=0.3,
    )
    assert promoted == []
    assert not any(f.get("rule") == "R1_official_solution_page" for f in fired)


def test_r1_solution_zero_action_when_no_official_page_in_pool():
    """官方页不存在 → 既有语义零变化(wiki 幸存者合法满足槽;fail-open)。"""
    promoted, fired = reserve_required_slots(
        _PlanStub([_solution_slot()]),
        survivors=[WIKI_SOLUTION_DESC],
        pool_scores=[(WIKI_SOLUTION_DESC, 0.85)],
        taxonomy=None,
        threshold=0.3,
    )
    assert promoted == []
    assert not any(f.get("rule") == "R1_official_solution_page" for f in fired)


def test_r1_solution_impostor_url_page_not_promoted():
    """URL 带 solution 字样但非方案语义的页不构成官方 Solution 页。"""
    promoted, fired = reserve_required_slots(
        _PlanStub([_solution_slot()]),
        survivors=[WIKI_SOLUTION_DESC],
        pool_scores=[(WIKI_SOLUTION_DESC, 0.85), (IMPOSTOR_PAGE, 0.20)],
        taxonomy=None,
        threshold=0.3,
    )
    ids = {(r.source_id, r.chunk_index) for r in promoted}
    assert IMPOSTOR_PAGE.source_id not in {sid for sid, _ in ids}
    assert not any(f.get("rule") == "R1_official_solution_page" for f in fired)


# --------------------------------------------------------------------------- #
# 单元级 — 权威形态谓词(通用结构信号;语言无关)
# --------------------------------------------------------------------------- #


def test_first_party_authority_predicates_structural_matrix():
    assert is_first_party_solution_page(OFFICIAL_SOLUTION) is True
    assert is_first_party_solution_page(WIKI_SOLUTION_DESC) is False, (
        "wiki blob path carrying 'solutions' as a hyphenated directory name "
        "is not the /solutions/ segment authority form"
    )
    assert is_first_party_solution_page(IMPOSTOR_PAGE) is False
    assert is_first_party_authority_page(OFFICIAL_SOLUTION) is True
    assert is_first_party_authority_page(FIRST_PARTY_CASE) is True
    assert is_first_party_authority_page(_knowledge_case(0)) is False, (
        "internal filesystem cases are legitimate knowledge-case sources but "
        "not first-party public authority pages"
    )
    assert is_first_party_authority_page(_spec_chunk(0)) is False


def test_case_slot_predicate_still_matches_first_party_case_page():
    """既有资格保真(#31 B2-4):权威页仍必须经槽位谓词匹配才可保位。"""
    assert (
        reserve_required_slots(
            _PlanStub([_case_slot()]),
            survivors=[_knowledge_case(0)],
            pool_scores=[(_knowledge_case(0), 0.85), (FIRST_PARTY_CASE, 0.20)],
            taxonomy=None,
            threshold=0.3,
        )[0][0].source_id
        == FIRST_PARTY_CASE.source_id
    )
