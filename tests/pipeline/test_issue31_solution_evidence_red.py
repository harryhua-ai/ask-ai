"""Issue #31 — solution 查询证据组合与 truthful absence(Track B2 表征性 RED)。

冻结语义出处:docs/v164-iteration-contracts-20260913
(docs/engineering/tasks/v164-track-b-evidence-authority-commercial-truth-contract.md §B2):

- B2-2 truthful absence:「官方资料未载明 X」类主张必须对照 X 的合格权威类评估,
  而非仅看当前检索上下文;合格权威类存在于知识域但未进当前上下文时,不得断言
  官方缺席,只能按既有 coverage/gap 语义表达不足。原 context-scoped 指令
  (契约锚点 rag.py:1156-1157,r4 main 漂移至生成 user 骨架「资料未载明时,
  明确说明"官方资料未载明该数值"」)必须被替换。
- B2-4 Case 角色:第一方公开 case-study 页(website 爬取类)是合格
  CASE_EVIDENCE;「已证落地证明」必须可与内部历史支持工单区分。
- B2-5 Solution retention:solution 类查询对官方 Solution 页有定义的保留路径
  (检索桶或等价保证),而非仅标题信号匹配。

生产实证(2026-09-07 会话 5fcad09e,只读核验,2026-09-16):
- 生产索引已收录 /solutions/infrastructure-monitoring/(web_crawl)、
  /case-studies/nexascent-water-meter-ocr-ne101/(web_crawl, product=ne101)、
  NE101 wiki overview(IP67 在 overview chunk 内,github/ne101)、
  NeoMind camera-ocr 用例页(github/neomind);
- 该 solution 查询终局证据面 = 1 条无关 dev-guide + 4 条内部历史工单
  (filesystem/knowledge,rerank 分 0.015-0.016),官方 Solution/Case/
  Wiki/模型页全部缺席,而答案仍发出「官方资料未载明 NE101 的具体电池续航
  时长、防护等级数值及价格」类官方缺席断言。

基线(r4 main b338c3c)预期:RED-1/2/3 FAIL,CONTROL-1/2/3 PASS。
本文件只做表征(RED 证据),不实现修复;修复属 Track B2 冻结语义的
RESTORATION,机制(桶/晋升/提示语义)由实现决定,本测试只钉 WHAT。
"""

import json

import pytest

from backend.pipeline.citation import is_first_party_case_source
from backend.pipeline.evidence_planning import (
    CITATION_BACKGROUND_ALLOWED,
    EvidenceSlot,
    ROLE_CASE_EVIDENCE,
)
from backend.pipeline.evidence_selection import evidence_matches_slot
from backend.pipeline.rag import RAGOrchestrator
from backend.retrieval.rerank import RerankPipeline
from backend.retrieval.search import SearchResult

pytestmark = pytest.mark.unit

SOLUTION_Q = "我是做水表业务的,请推荐适合我的一套 OCR 抄表解决方案"


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


#: 第一方公开 case-study 页(website 爬取类;生产索引已核验存在)
CASE_PAGE = _sr(
    "camthink-site/case-studies/nexascent-water-meter-ocr-ne101",
    "web_crawl",
    "ne101",
    "Non-Contact Water Meter OCR: How NexAscent Uses NE101",
    "CASE-PAGE: NE101 scheduled non-contact capture, 4G LTE upload, MeterOCR processing.",
    url="https://www.camthink.ai/case-studies/nexascent-water-meter-ocr-ne101/",
)

#: 第一方官方 Solution 页(website 爬取类;生产索引已核验存在)
SOLUTION_PAGE = _sr(
    "camthink-site/solutions/infrastructure-monitoring",
    "web_crawl",
    "ne101",
    "Infrastructure Monitoring Solution",
    "SOLUTION-PAGE: scheduled visual capture, edge OCR, MQTT/HTTP output, proven deployment.",
    url="https://www.camthink.ai/solutions/infrastructure-monitoring/",
    chunk_type="heading",
)

#: 内部历史支持工单(#28 第一方知识案例,非 internal 标记)
KNOWLEDGE_CASE = _sr(
    "kb/ticket-water-meter-ocr",
    "filesystem",
    "knowledge",
    "案例:水表 OCR 方案咨询",
    "历史工单正文。",
)

#: internal 显式标记的内部工单(必须保持排除)
INTERNAL_CASE = _sr(
    "kb/ticket-internal",
    "filesystem",
    "knowledge",
    "案例:内部工单",
    "内部工单正文。",
    channel_visibility=("internal",),
)


# --------------------------------------------------------------------------- #
# RED-1(B2-4):第一方公开 case-study 页是合格 CASE_EVIDENCE
# --------------------------------------------------------------------------- #


async def test_red1_website_case_study_is_eligible_case_evidence():
    slot = EvidenceSlot(
        role=ROLE_CASE_EVIDENCE,
        required=False,
        citation_requirement=CITATION_BACKGROUND_ALLOWED,
    )
    assert evidence_matches_slot(slot, CASE_PAGE, resolution_targets=("ne101",)) is True, (
        "B2-4: first-party published case-study pages (website crawl class) are "
        "eligible CASE_EVIDENCE; the predicate currently admits only "
        "filesystem+knowledge internal support cases, so published deployment "
        "proof (e.g. a /case-studies/ page) can never cover the case role"
    )


async def test_control1_knowledge_case_still_matches_case_evidence():
    """既有资格保真:#28 第一方知识案例(非 internal)仍匹配 CASE_EVIDENCE。"""
    slot = EvidenceSlot(
        role=ROLE_CASE_EVIDENCE,
        required=False,
        citation_requirement=CITATION_BACKGROUND_ALLOWED,
    )
    assert evidence_matches_slot(slot, KNOWLEDGE_CASE, resolution_targets=()) is True


async def test_control2_internal_marked_case_stays_excluded():
    """既有边界保真:显式 internal 标记的知识案例仍不得作为可引用案例。"""
    assert is_first_party_case_source("filesystem", "knowledge", ("internal",)) is False


# --------------------------------------------------------------------------- #
# RED-2(B2-2):生成骨架不得再携带 context-scoped 官方缺席指令
# --------------------------------------------------------------------------- #


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
    """Weaviate 边界脚本;记录桶调用(保留路径归因用)。"""

    def __init__(self, pool: list[SearchResult]):
        self._pool = list(pool)
        self.bucket_calls: list[dict] = []

    def search(self, **kw):
        return list(self._pool)

    def search_symbols(self, **kw):
        return []

    def search_bucket(self, **kw):
        self.bucket_calls.append(kw)
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


def _spec_chunk(i: int) -> SearchResult:
    return _sr(
        f"site/ne101-spec-{i:02d}",
        "website",
        "ne101",
        f"NE101 Datasheet Part {i}",
        "SPEC-DOC: NE101 hardware specification facts.",
    )


def _solution_rag(scores: dict[str, float], pool: list[SearchResult]) -> RAGOrchestrator:
    return RAGOrchestrator(
        _Searcher(pool),
        RerankPipeline(_ScriptedInner(scores)),
        _make_llm(_payload("product", "recommendation")),
        system_prompt="sys",
        min_results_to_answer=1,
    )


async def test_red2_generation_skeleton_must_not_instruct_context_scoped_official_absence():
    spec_pool = [_spec_chunk(i) for i in range(10)]
    rag = _solution_rag({"SPEC-DOC": 0.92}, spec_pool)
    result = await rag.answer(SOLUTION_Q, "widget")
    assert result.is_answered

    generation_prompts = []
    for call in rag._llm.generate.call_args_list:
        messages = call.kwargs.get("messages") or (call.args[0] if call.args else None)
        if not messages:
            continue
        user_content = messages[-1]["content"]
        if "## 检索到的资料" in user_content:
            generation_prompts.append(user_content)

    assert generation_prompts, "generation user prompt must be captured"

    for user_content in generation_prompts:
        assert "资料未载明时" not in user_content, (
            "B2-2: the generation skeleton still carries the context-scoped "
            "absence directive (资料未载明时,明确说明\"官方资料未载明该数值\"), "
            "which asserts official absence from the current context alone; it "
            "must be replaced by semantics that assess eligible authoritative "
            "source classes for the claim type"
        )
        assert "官方资料未载明该数值" not in user_content, (
            "B2-2: legacy official-absence phrasing must not be instructed "
            "against the current context alone"
        )


# --------------------------------------------------------------------------- #
# RED-3(B2-5):官方 Solution 页在语料中且被召回,solution 查询必须保留
# --------------------------------------------------------------------------- #


async def test_red3_official_solution_page_retained_for_solution_query():
    pool = [_spec_chunk(i) for i in range(10)] + [SOLUTION_PAGE]
    # Solution 页被召回入池,但 cross-encoder 分 0.20 < 阈值 0.3
    # (生产实证:solution 类页面在词法/语义全局竞争中常落在阈下)
    rag = _solution_rag({"SPEC-DOC": 0.92, "SOLUTION-PAGE": 0.20}, pool)
    result = await rag.answer(SOLUTION_Q, "widget")
    final_ids = {(r.source_id, r.chunk_index) for r in result.reranked_results}
    assert (SOLUTION_PAGE.source_id, SOLUTION_PAGE.chunk_index) in final_ids, (
        "B2-5: solution queries must have a defined retention path for official "
        "Solution pages (retrieval bucket or equivalent guarantee), not "
        "title-signal-only matching; a recalled, slot-matching official Solution "
        "page below the rerank threshold is silently dropped while the required "
        "SOLUTION_GUIDE slot goes uncovered"
    )


async def test_control3_threshold_qualified_solution_page_is_promoted_today():
    """同夹具对照:Solution 页阈上时今日机制(R1 池内晋升)即可保留 —— 证明
    RED-3 失败精确钉在阈下保留缺口,而非槽位匹配缺口。"""
    pool = [_spec_chunk(i) for i in range(10)] + [SOLUTION_PAGE]
    rag = _solution_rag({"SPEC-DOC": 0.92, "SOLUTION-PAGE": 0.85}, pool)
    result = await rag.answer(SOLUTION_Q, "widget")
    final_ids = {(r.source_id, r.chunk_index) for r in result.reranked_results}
    assert (SOLUTION_PAGE.source_id, SOLUTION_PAGE.chunk_index) in final_ids
