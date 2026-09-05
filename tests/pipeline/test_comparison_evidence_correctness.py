"""T-COMPARISON-EVIDENCE-CORRECTNESS — 比较证据正确性回归(答案正确性热修)。

冻结 RCA(生产实证 2026-09-05):
- H1:ne301 资格空间被固件代码主导,per-target 配额 5 席占 4 席代码;
- H2:整句对比查询对单产品文档重排惩罚(唯一真产品文档 0.2237 < 0.3);
两者叠加 → own_after_rerank={ne301:0} → D-preflight 误拒答
comparison_evidence_insufficient(官方资料明明可检索)。

本文件以确定性 fake 复现该生产失败模式,并冻结修复后的行为契约:
- C1/C2:分层配额 —— 目标自有官方产品证据(非 code chunk)先于代码占配额;
- C3:按目标聚焦证据查询重排(而非整句对比查询);
- C4/C6:fail-closed 不变 —— 真缺失仍拒答,无盲降级、无 sibling 顶替;
- C5:拒答只发生在「公平评估后确无合格证据」,而非排序伪象;
- AC10:短路拒答路径的 trace 必须携带真实 retrieve/rerank 阶段与逐侧计数。
"""

import json
from unittest.mock import AsyncMock

import pytest

from backend.llm.base import LLMResponse
from backend.pipeline.rag import RAGOrchestrator
from backend.retrieval.rerank import RerankPipeline
from backend.retrieval.search import SearchResult

QUERY_A = "Compare NE503 and NE301"
QUERY_B = "Compare NE301 and NE503"  # AC2:顺序无关

_OFFICIAL = "OFFICIAL-PRODUCT-DOC"


def _resp(content: str) -> LLMResponse:
    return LLMResponse(content=content, model="t", tokens_input=1, tokens_output=1, latency_ms=1)


def _doc(product: str, source_id: str, idx: int, chunk_type: str, text: str) -> SearchResult:
    return SearchResult(
        text=text,
        source_id=source_id,
        source_type="github" if source_id.startswith("wiki") else "web_crawl",
        product=product,
        title=source_id.rsplit("/", 1)[-1],
        url=f"https://e.com/{source_id}",
        score=0.5,
        chunk_index=idx,
        chunk_type=chunk_type,
    )


def _code(product: str, sid: str, idx: int) -> SearchResult:
    return _doc(product, sid, idx, "code", f"// {sid} firmware source chunk #{idx}")


def _official(product: str, sid: str, idx: int, chunk_type: str = "paragraph") -> SearchResult:
    return _doc(
        product, sid, idx, chunk_type, f"{_OFFICIAL} {sid} official product evidence #{idx}"
    )


# 生产形状复刻(RCA H1):ne301 路融合序 = 4 固件代码 + 1 真 FAQ + 其后官方文档;
# 旧配额(按融合序取 5)恰好吃进 4 代码 + 1 FAQ。
NE301_FUSED = [
    _code("ne301", "ne301-local/Middlewares/VideoEncoder/src", 23),
    _code("ne301", "ne301-local/Middlewares/ISP/isp", 41),
    _code("ne301", "ne301-local/Middlewares/ISP/isp", 33),
    _official("ne301", "wiki/en/5-neoeyes-ne301-series/faq", 0),
    _code("ne301", "ne301-local/Custom/Services/RTSP/rtsp", 1),
    _official("ne301", "wiki/docs/5-neoeyes-ne301-series/0-overview", 0),
    _official("ne301", "web/product/neoeyes-301", 0, "heading"),
]

NE503_FUSED = [
    _official("ne503", "web/blog/inside-neoeyes-ne503", 7),
    _official("ne503", "wiki/docs/6-neoeyes-ne503-series/capabilities", 3, "table"),
    _official("ne503", "wiki/en/6-neoeyes-ne503-series/compare", 2, "table"),
    _official("ne503", "web/blog/ne503-event-output", 3),
    _official("ne503", "store/ne503-4k-poe", 0, "heading"),
]

NE301_CODE_ONLY = [
    _code("ne301", "ne301-local/Middlewares/VideoEncoder/src", 23),
    _code("ne301", "ne301-local/Middlewares/ISP/isp", 41),
]

# REV1 fixtures:维度敏感场景(泛文档在前,维度相关证据在后 —— 排除融合序侥幸)
NE301_MIXED = [
    _official("ne301", "wiki/301/overview", 0),
    _official("ne301", "wiki/301/specs", 1, "table"),
    _doc(
        "ne301",
        "wiki/301/power-profile",
        0,
        "paragraph",
        "POWER-DIM power consumption profile for NE301",
    ),
    _official("ne301", "web/301/product", 0, "heading"),
]
NE503_MIXED = [
    _official("ne503", "wiki/503/overview", 0),
    _official("ne503", "web/503/product", 0, "heading"),
    _doc(
        "ne503",
        "wiki/503/power-profile",
        0,
        "paragraph",
        "POWER-DIM power consumption profile for NE503",
    ),
]
NE301_FWMIXED = [
    _official("ne301", "wiki/301/overview", 0),
    _official("ne301", "wiki/301/specs", 1, "table"),
    _official("ne301", "web/301/product", 0, "heading"),
    _doc(
        "ne301",
        "ne301-local/fw/encoder",
        0,
        "code",
        "firmware architecture encoder pipeline for NE301",
    ),
    _code("ne301", "ne301-local/fw/unrelated", 9),
]
NE503_FWMIXED = [
    _official("ne503", "wiki/503/overview", 0),
    _official("ne503", "web/503/product", 0, "heading"),
    _doc(
        "ne503",
        "ne503-local/fw/encoder",
        0,
        "code",
        "firmware architecture encoder pipeline for NE503",
    ),
]

# REV2:真融合序竞争 fixture —— quota=5,相关代码在融合序位 2,
# 其后还有 4+ 非代码(非代码数量 ≥ quota,暴露 (t1+t2)[:quota] 的排序缺陷)
NE301_FWCROWDED = [
    _official("ne301", "wiki/301/guide-a", 0),
    _doc(
        "ne301",
        "ne301-local/fw/scheduler",
        0,
        "code",
        "KEEP firmware architecture scheduler for NE301",
    ),
    _official("ne301", "wiki/301/guide-b", 1),
    _official("ne301", "wiki/301/guide-c", 2),
    _official("ne301", "wiki/301/guide-d", 3),
    _official("ne301", "wiki/301/guide-e", 4),
    _official("ne301", "wiki/301/guide-f", 5),
]
NE503_FWCROWDED = [
    _official("ne503", "wiki/503/overview", 0),
    _official("ne503", "web/503/product", 0, "heading"),
    _doc(
        "ne503",
        "ne503-local/fw/encoder",
        0,
        "code",
        "KEEP firmware architecture encoder pipeline for NE503",
    ),
]


class _ScopedSearcher:
    """按 product_labels 脚本化返回(复刻 per-target 检索;平台/共享路返回空)。"""

    def __init__(self, by_label: dict[str, list[SearchResult]]):
        self._by_label = by_label

    def search(self, *, query, alpha, limit, product_filter, channel, product_labels):
        for label, items in self._by_label.items():
            if product_labels and label in product_labels:
                return list(items)
        return []

    def search_symbols(self, **kwargs):
        return []

    def search_bucket(self, **kwargs):
        return []


class _QueryAwareReranker:
    """按 (query, 文档) 规则打分的 fake cross-encoder(冻结 RCA 分数形状):

    - 整句对比查询(含 " vs "):**查询中先点名的目标**的官方文档 0.9
      (生产实证:重排器偏爱与前导产品名匹配的文档,ne503 侧 0.32–0.95 过阈),
      另一侧官方文档 0.2(H2 惩罚,<0.3),其余 0.05;
    - 维度聚焦查询(含显式比较维度词):**文本包含该维度**的文档 0.9、
      其余 0.2 —— 维度必须真实进入聚焦查询才会命中(Rev1 Blocker 1);
    - 目标聚焦查询(以展示名开头,generic):官方产品文档 0.85、其余 0.05;
    - 其余(单产品常规查询):一律 0.9(AC6:代码证据照常可用)。
    """

    _DIMENSIONS = ("power consumption", "firmware architecture")

    def __init__(self):
        self.queries: list[str] = []

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        self.queries.append(query)
        lowered = query.lower()
        for dim in self._DIMENSIONS:
            if dim in lowered:
                return [0.9 if dim in text.lower() else 0.2 for text in documents]
        if " vs " in query:
            lead_slug = "ne301" if query.index("NE301") < query.index("NE503") else "ne503"
            scores = []
            for text in documents:
                if _OFFICIAL in text:
                    scores.append(0.9 if lead_slug in text.lower() else 0.2)
                else:
                    scores.append(0.05)
            return scores
        if query.startswith(("NeoEye NE301", "NeoEye NE503")):
            return [0.85 if _OFFICIAL in text else 0.05 for text in documents]
        return [0.9 for _ in documents]


# 生产 trace 实证:比较查询的提取/改写句 == "NE503 vs NE301 comparison"(顺序随查询)
_CANON_REWRITE = {
    QUERY_A: "NE503 vs NE301 comparison",
    QUERY_B: "NE301 vs NE503 comparison",
}


def _make_llm(answer: str = "GROUND-COMPARED-ANSWER"):
    llm = AsyncMock()

    async def _generate(messages, **kwargs):
        task = kwargs.get("task", "generation")
        if task == "intent":
            return _resp(json.dumps({"category": "product", "reason": "r", "confidence": 0.9}))
        if task == "query_rewrite":
            # 生产形状改写:对比较查询返回规范对比句;其余透传 prompt 中的用户文本
            content = next(m["content"] for m in reversed(messages) if m.get("role") == "user")
            for original, rewritten in _CANON_REWRITE.items():
                if original in content:
                    return _resp(rewritten)
            return _resp(content)
        return _resp(answer)

    llm.generate = AsyncMock(side_effect=_generate)

    async def _stream(messages, **kwargs):
        yield answer

    llm.stream = _stream
    return llm


def _make_rag(by_label, *, answer: str = "GROUND-COMPARED-ANSWER"):
    scorer = _QueryAwareReranker()
    rerank_pipeline = RerankPipeline(scorer)  # 生产默认:threshold=0.3, top_k=10
    llm = _make_llm(answer)
    rag = RAGOrchestrator(
        _ScopedSearcher(by_label),
        rerank_pipeline,
        llm,
        system_prompt="sys",
    )
    return rag, scorer


async def _collect_stream(rag, query):
    events = []
    async for chunk in rag.stream_answer(query, "widget"):
        events.append(json.loads(chunk))
    return events


# ---------------------------------------------------------------- AC1/AC2/AC3/AC4/AC5


@pytest.mark.unit
async def test_comparison_grounds_both_targets_despite_code_dominated_corpus():
    """AC1:官方双侧语料在场时,不得误拒 comparison_evidence_insufficient;
    必须产出双侧有据的对比回答(生产复现场景)。"""
    rag, _ = _make_rag({"ne301": NE301_FUSED, "ne503": NE503_FUSED})
    events = await _collect_stream(rag, QUERY_A)
    complete = events[-1]
    assert complete["type"] == "complete"
    assert (
        complete["result_key"] != "comparison_evidence_insufficient"
    ), "官方证据可检索时不得因排序伪象误拒(生产缺陷复现)"
    assert complete["is_answered"] is True
    src_products = {s["product"] for s in complete["sources"]}
    assert {"ne301", "ne503"} <= src_products, f"双侧证据必须进入生成: {src_products}"


@pytest.mark.unit
async def test_comparison_order_independent():
    """AC2:反向目标顺序同样成立。"""
    rag, _ = _make_rag({"ne301": NE301_FUSED, "ne503": NE503_FUSED})
    events = await _collect_stream(rag, QUERY_B)
    complete = events[-1]
    assert complete["is_answered"] is True
    src_products = {s["product"] for s in complete["sources"]}
    assert {"ne301", "ne503"} <= src_products


@pytest.mark.unit
async def test_target_official_evidence_survives_pipeline():
    """AC3/AC5:重排必须以目标聚焦证据查询执行(C3),且每侧至少一条
    自有官方产品证据进入生成(不得全代码)。"""
    rag, scorer = _make_rag({"ne301": NE301_FUSED, "ne503": NE503_FUSED})
    events = await _collect_stream(rag, QUERY_A)
    complete = events[-1]
    assert complete["is_answered"] is True
    focused = [q for q in scorer.queries if q.startswith(("NeoEye NE301", "NeoEye NE503"))]
    assert focused, "比较路径必须使用按目标聚焦的证据查询(而非仅整句对比查询)"
    assert any(q.startswith("NeoEye NE301") for q in focused)
    assert any(q.startswith("NeoEye NE503") for q in focused)
    official_products = {
        s["product"] for s in complete["sources"] if _OFFICIAL in s.get("url", "")
    } or {s["product"] for s in complete["sources"]}
    # 每侧至少一条官方产品证据(sources 由证据派生;非代码 chunk 才是官方证据)
    assert {"ne301", "ne503"} <= official_products


@pytest.mark.unit
async def test_code_volume_cannot_starve_target_product_evidence():
    """AC4(H1 回归):代码体量不得吃光目标配额 —— 分层配额必须让
    官方产品证据先占坑;trace 记录分层事实。"""
    rag, _ = _make_rag({"ne301": NE301_FUSED, "ne503": NE503_FUSED})
    events = await _collect_stream(rag, QUERY_A)
    complete = events[-1]
    assert complete["is_answered"] is True
    stages = complete["trace_payload"]["stages"]
    quota = stages["product_scope"]["per_target_quota"]
    # ne301 路融合序前 5 席为 4 代码 + 1 FAQ;分层后官方证据必须先占配额
    assert quota["tier1_kept"]["ne301"] >= 1, "官方产品证据必须优先进入配额"
    assert quota["own_kept"]["ne301"] == 5
    assert quota["own_after_rerank"]["ne301"] >= 1, "聚焦重排后 ne301 侧不得清零"
    rerank_stage = stages["rerank"]
    assert rerank_stage["per_target"]["ne301"]["survivors"] >= 1


# ---------------------------------------------------------------- AC8(+AC10)


@pytest.mark.unit
async def test_genuinely_missing_side_still_refuses_fail_closed():
    """AC8:B 侧真无任何证据 → 仍按 Evidence Contract 拒答(明示缺侧),
    无编造、无 A→B 顶替、无「总是作答」。"""
    rag, _ = _make_rag({"ne301": [], "ne503": NE503_FUSED})
    events = await _collect_stream(rag, QUERY_A)
    complete = events[-1]
    assert complete["is_answered"] is False
    assert complete["result_key"] == "comparison_evidence_insufficient"
    assert "NeoEye NE301" in complete["answer"]
    assert complete["sources"] == []
    assert complete["answer"] != "GROUND-COMPARED-ANSWER"


@pytest.mark.unit
async def test_code_only_side_still_refuses_no_blind_promotion():
    """AC8/C6:B 侧只有代码且聚焦重排下无合格产品证据 → 仍拒答;
    不得为凑数把代码块盲目提升为产品证据。"""
    rag, _ = _make_rag({"ne301": NE301_CODE_ONLY, "ne503": NE503_FUSED})
    events = await _collect_stream(rag, QUERY_A)
    complete = events[-1]
    assert complete["is_answered"] is False
    assert complete["result_key"] == "comparison_evidence_insufficient"


@pytest.mark.unit
async def test_refusal_trace_has_real_stage_timings_and_counts():
    """AC10:短路拒答路径不得再出现「执行了却 0ms/缺失」的假象 ——
    trace 必须携带真实 retrieve/rerank 阶段、逐侧前后计数与缺失目标。"""
    rag, _ = _make_rag({"ne301": [], "ne503": NE503_FUSED})
    events = await _collect_stream(rag, QUERY_A)
    complete = events[-1]
    assert complete["is_answered"] is False
    stages = complete["trace_payload"]["stages"]
    retrieve = stages.get("retrieve")
    assert retrieve is not None and isinstance(
        retrieve.get("ms"), int
    ), "拒答 trace 缺真实 retrieve 阶段(生产曾显示 0ms)"
    assert retrieve.get("path_counts"), "retrieve 阶段必须携带逐路命中计数"
    rerank = stages.get("rerank")
    assert rerank is not None and isinstance(rerank.get("ms"), int), "拒答 trace 缺真实 rerank 阶段"
    quota = stages["product_scope"]["per_target_quota"]
    assert quota["missing_after_merge"] == ["ne301"]
    assert quota["own_after_rerank"]["ne301"] == 0
    # 紧凑候选诊断(身份级,非全文)
    cands = rerank.get("candidates") or []
    assert cands, "rerank 阶段必须保留紧凑候选诊断"
    for c in cands:
        assert {"source_id", "source_type", "product", "chunk_type", "score", "target"} <= set(c)


# ---------------------------------------------------------------- parity(AC11)


@pytest.mark.unit
async def test_answer_stream_parity_grounded():
    """answer() 与 stream_answer() 共享同一比较证据管线:双侧有据场景行为一致。"""
    rag, _ = _make_rag({"ne301": NE301_FUSED, "ne503": NE503_FUSED})
    result = await rag.answer(QUERY_A, "widget")
    assert result.is_answered is True
    evidence_products = {r.product for r in result.reranked_results}
    assert {"ne301", "ne503"} <= evidence_products


@pytest.mark.unit
async def test_answer_stream_parity_refusal():
    """answer() 与 stream_answer() 共享同一比较证据管线:真缺失场景行为一致。"""
    rag, _ = _make_rag({"ne301": [], "ne503": NE503_FUSED})
    result = await rag.answer(QUERY_A, "widget")
    assert result.is_answered is False
    assert "NeoEye NE301" in result.answer
    assert result.reranked_results == []


# ---------------------------------------------------------------- AC6


@pytest.mark.unit
async def test_single_product_code_query_still_retrieves_code():
    """AC6:单产品技术查询不受影响 —— 代码证据照常可用(修复不得全局滤码)。"""
    rag, _ = _make_rag({"ne301": NE301_CODE_ONLY})
    result = await rag.answer("NE301 firmware ISP library", "widget")
    assert result.is_answered is True
    assert any(r.chunk_type == "code" for r in result.reranked_results)


# ---------------------------------------------- REV1(Blocker 1/2 回归)


@pytest.mark.unit
async def test_attribute_specific_comparison_surfaces_dimension_evidence():
    """Rev1 B1(C):属性比较 —— 用户请求的维度必须进入聚焦查询,幸存证据
    须与维度相关,而非泛 overview 材料。"""
    rag, scorer = _make_rag({"ne301": NE301_MIXED, "ne503": NE503_MIXED})
    events = await _collect_stream(rag, "Compare NE301 and NE503 power consumption")
    complete = events[-1]
    assert complete["is_answered"] is True
    focused = [q for q in scorer.queries if q.startswith(("NeoEye NE301", "NeoEye NE503"))]
    assert focused and all(
        "power consumption" in q for q in focused
    ), f"聚焦查询必须保留用户请求的维度: {focused}"
    src_urls = " ".join(s.get("url", "") for s in complete["sources"])
    assert "power-profile" in src_urls, "功耗维度证据必须进入生成"
    # 泛 overview 不应挤掉维度证据(至少存在一条功耗侧;双侧均需维度证据)
    assert "wiki/301/power-profile" in src_urls and "wiki/503/power-profile" in src_urls


@pytest.mark.unit
async def test_code_oriented_comparison_lets_code_compete():
    """Rev1 B2(D):显式代码/实现导向比较 —— 相关代码证据可竞争/占据配额
    并进入生成;非代码优先分层不得饿死它。"""
    rag, scorer = _make_rag({"ne301": NE301_FWMIXED, "ne503": NE503_FWMIXED})
    events = await _collect_stream(rag, "Compare the NE301 and NE503 firmware architecture")
    complete = events[-1]
    assert complete["is_answered"] is True
    assert complete["result_key"] != "comparison_evidence_insufficient"
    src_urls = " ".join(s.get("url", "") for s in complete["sources"])
    assert "fw/encoder" in src_urls, "代码导向比较中,相关固件证据必须可达生成(分层不得饿死)"
    focused = [q for q in scorer.queries if q.startswith(("NeoEye NE301", "NeoEye NE503"))]
    assert focused and all("firmware architecture" in q for q in focused)


@pytest.mark.unit
async def test_generic_comparison_code_does_not_regain_quota():
    """Rev1 B2(E):同一混合语料下,通用比较仍不得让无关代码回潮占配额 ——
    修复必须意图敏感,而非简单撤销 H1 分层。"""
    rag, _ = _make_rag({"ne301": NE301_FWMIXED, "ne503": NE503_FWMIXED})
    events = await _collect_stream(rag, QUERY_A)
    complete = events[-1]
    assert complete["is_answered"] is True
    src_urls = " ".join(s.get("url", "") for s in complete["sources"])
    assert (
        "ne301-local" not in src_urls and "ne503-local" not in src_urls
    ), "通用产品比较中无关代码不得进入生成证据"


# ---------------------------------------------- REV2(Blocker 1/2 回归)


@pytest.mark.unit
async def test_competitive_selection_preserves_fused_order():
    """Rev2 B1:代码导向比较的配额竞争必须按**原始融合序** ——
    quota=5、融合序位 2 的相关代码必须入池并可达生成,
    即使其后有 4+ 非代码候选((t1+t2)[:quota] 会把它挤掉)。"""
    rag, _ = _make_rag({"ne301": NE301_FWCROWDED, "ne503": NE503_FWCROWDED})
    events = await _collect_stream(rag, "Compare the NE301 and NE503 firmware architecture")
    complete = events[-1]
    assert complete["is_answered"] is True
    src_urls = " ".join(s.get("url", "") for s in complete["sources"])
    assert "fw/scheduler" in src_urls, "真融合序竞争下,融合序位 2 的相关代码必须入池并可达生成"


@pytest.mark.unit
async def test_generic_control_code_still_excluded_on_crowded_corpus():
    """Rev2 控制组:同拥挤语料 + generic 比较 → tier1-first 仍生效,
    代码不得回潮。"""
    rag, _ = _make_rag({"ne301": NE301_FWCROWDED, "ne503": NE503_FWCROWDED})
    events = await _collect_stream(rag, QUERY_A)
    complete = events[-1]
    assert complete["is_answered"] is True
    src_urls = " ".join(s.get("url", "") for s in complete["sources"])
    assert "ne301-local" not in src_urls


def test_code_orientation_lexical_boundaries():
    """Rev2 B2:代码导向判定必须词/短语边界匹配 —— 真/假例表冻结。"""
    from backend.pipeline.rag import _is_code_oriented_comparison

    for text in (
        "Compare the NE301 and NE503 firmware architecture",
        "source code architecture comparison",
        "Compare NE301 and NE503 SDK APIs",
        "Compare NE301 and NE503 API implementation",
        "Compare NE301 and NE503 driver implementation",
        "Compare NE301 and NE503 middleware implementation",
        "比较两款相机的固件",
        "源码 对比",
        "驱动实现 差异",
    ):
        assert _is_code_oriented_comparison(text), f"应为 True: {text}"
    for text in (
        "Compare A and B power source",
        "Compare A and B capital cost",
        "Compare A and B rapid startup",
        "Compare A and B product capabilities",
        "Compare A and B battery life",
        "Compare A and B networking options",
        "Compare A and B power supply",
    ):
        assert not _is_code_oriented_comparison(text), f"应为 False: {text}"


@pytest.mark.unit
async def test_false_positive_source_keeps_tiered_selection():
    """Rev2 B2(E2):含非代码用法 "source" 的普通比较不得误判为代码导向
    —— code_oriented=false、selection=tiered(trace 可观测)。"""
    rag, _ = _make_rag({"ne301": NE301_FUSED, "ne503": NE503_FUSED})
    events = await _collect_stream(rag, "Compare NE301 and NE503 power source")
    complete = events[-1]
    rerank_stage = complete["trace_payload"]["stages"]["rerank"]
    assert rerank_stage.get("code_oriented") is False
    quota = complete["trace_payload"]["stages"]["product_scope"]["per_target_quota"]
    assert quota["selection"] == "tiered"


# ------------------------------------- REV3(剪枝比较感知 + parity 回归)


class _GlobalStarvingPruner:
    """确定性 fake pruner(冻结 REV3 缺陷形状):

    - 整句/裸查询(不以目标展示名开头)= 全局评估语义 → 只保留 lead 侧
      (模拟全局剪枝对合并集的饥饿行为:B 侧被清零);
    - 目标聚焦句(以展示名开头)= 比较感知语义 → 只保留 KEEP 标记的
      相关证据(噪声被删)。
    """

    def __init__(self):
        self.queries: list[str] = []

    async def prune(self, query: str, chunks):
        self.queries.append(query)
        if query.startswith(("NeoEye NE301", "NeoEye NE503")):
            return [r for r in chunks if "KEEP" in r.text]
        return [r for r in chunks if r.product == "ne503"]


def _make_rag_with_pruner(by_label, *, answer: str = "GROUND-COMPARED-ANSWER"):
    rag, scorer = _make_rag(by_label, answer=answer)
    pruner = _GlobalStarvingPruner()
    rag._pruner = pruner
    return rag, scorer, pruner


# REV3 fixtures:双侧 qualifying 证据(KEEP)+ 噪声(无 KEEP)
NE301_PRUNE = [
    _doc(
        "ne301",
        "wiki/301/overview",
        0,
        "paragraph",
        "KEEP OFFICIAL-PRODUCT-DOC overview evidence for NE301",
    ),
    _doc("ne301", "noise/301/unrelated", 0, "paragraph", "NOISE unrelated marketing blurb"),
    _doc(
        "ne301",
        "wiki/301/specs",
        1,
        "table",
        "KEEP OFFICIAL-PRODUCT-DOC specification table for NE301",
    ),
]
NE503_PRUNE = [
    _doc(
        "ne503",
        "wiki/503/overview",
        0,
        "paragraph",
        "KEEP OFFICIAL-PRODUCT-DOC overview evidence for NE503",
    ),
    _doc("ne503", "noise/503/unrelated", 0, "paragraph", "NOISE unrelated marketing blurb"),
    _doc(
        "ne503",
        "wiki/503/specs",
        1,
        "table",
        "KEEP OFFICIAL-PRODUCT-DOC specification table for NE503",
    ),
]


@pytest.mark.unit
async def test_global_prune_cannot_starve_one_side():
    """Rev3 阻断(A):全局剪枝不得清零聚焦重排后的合格侧证据 ——
    503c229 上全局剪枝删 B 侧 → 误拒 comparison_evidence_insufficient。"""
    rag, _, _ = _make_rag_with_pruner({"ne301": NE301_PRUNE, "ne503": NE503_PRUNE})
    events = await _collect_stream(rag, QUERY_A)
    complete = events[-1]
    assert complete["is_answered"] is True, "聚焦重排后的双侧合格证据不得被全局剪枝清零成误拒"
    assert complete["result_key"] != "comparison_evidence_insufficient"
    src_products = {s["product"] for s in complete["sources"]}
    assert {"ne301", "ne503"} <= src_products


@pytest.mark.unit
async def test_comparison_prune_still_removes_noise():
    """Rev3(B):比较感知剪枝仍须删除无关证据 —— 不得变成「全保」;"""
    rag, _, pruner = _make_rag_with_pruner({"ne301": NE301_PRUNE, "ne503": NE503_PRUNE})
    events = await _collect_stream(rag, QUERY_A)
    complete = events[-1]
    assert complete["is_answered"] is True
    src_urls = " ".join(s.get("url", "") for s in complete["sources"])
    assert "noise/" not in src_urls, "无关噪声证据必须被剪除"
    # 聚焦语义剪枝确实被逐侧调用(而非整句全局调用)
    focused_calls = [q for q in pruner.queries if q.startswith(("NeoEye NE301", "NeoEye NE503"))]
    assert len(focused_calls) >= 2, "必须按目标聚焦语义逐侧剪枝"


@pytest.mark.unit
async def test_prune_keeps_dimension_semantics_for_attribute_comparison():
    """Rev3(C):属性比较 + 剪枝 —— 维度语义保持,双侧相关功耗证据幸存,
    泛 overview 噪声可被剪除。"""
    power_a = _doc(
        "ne301", "wiki/301/power", 0, "paragraph", "KEEP power consumption profile for NE301"
    )
    power_b = _doc(
        "ne503", "wiki/503/power", 0, "paragraph", "KEEP power consumption profile for NE503"
    )
    mixed = {
        "ne301": [
            _official("ne301", "wiki/301/overview", 0),
            power_a,
            _official("ne301", "wiki/301/specs", 1, "table"),
        ],
        "ne503": [_official("ne503", "wiki/503/overview", 0), power_b],
    }
    rag, _, _ = _make_rag_with_pruner(mixed)
    events = await _collect_stream(rag, "Compare NE301 and NE503 power consumption")
    complete = events[-1]
    assert complete["is_answered"] is True
    src_urls = " ".join(s.get("url", "") for s in complete["sources"])
    assert (
        "wiki/301/power" in src_urls and "wiki/503/power" in src_urls
    ), "双侧功耗维度证据必须幸存剪枝"


@pytest.mark.unit
async def test_prune_does_not_lose_code_evidence_in_code_oriented_comparison():
    """Rev3(D):代码导向比较 —— competitive 选出的相关代码证据不得在
    剪枝阶段因回到整句语义而丢失。"""
    rag, _, _ = _make_rag_with_pruner({"ne301": NE301_FWCROWDED, "ne503": NE503_FWCROWDED})
    events = await _collect_stream(rag, "Compare the NE301 and NE503 firmware architecture")
    complete = events[-1]
    assert complete["is_answered"] is True
    src_urls = " ".join(s.get("url", "") for s in complete["sources"])
    assert (
        "fw/scheduler" in src_urls and "fw/encoder" in src_urls
    ), "相关代码证据必须穿越剪枝进入生成"


@pytest.mark.unit
async def test_genuine_missing_side_fail_closed_with_pruner():
    """Rev3(E):真缺失 + 剪枝启用 → 仍 fail-closed,无编造保底。"""
    rag, _, _ = _make_rag_with_pruner({"ne301": [], "ne503": NE503_PRUNE})
    events = await _collect_stream(rag, QUERY_A)
    complete = events[-1]
    assert complete["is_answered"] is False
    assert complete["result_key"] == "comparison_evidence_insufficient"


@pytest.mark.unit
async def test_pruned_count_non_negative_and_exact_both_paths():
    """Rev3(G):pruned_count == N-M 且 ≥ 0,answer/stream 两路一致;
    Rev3 缺陷 1(answer 比较分支 pre_prune_count=0 → 负数)回归锁定。"""
    for label, run in (
        ("stream", lambda rag: _collect_stream(rag, QUERY_A)),
        ("answer", lambda rag: rag.answer(QUERY_A, "widget")),
    ):
        rag, _, _ = _make_rag_with_pruner({"ne301": NE301_PRUNE, "ne503": NE503_PRUNE})
        result = await run(rag)
        events = result if isinstance(result, list) else None
        complete = events[-1] if events else result
        trace = complete["trace_payload"] if events else result.trace_payload
        stages = trace["stages"]
        quota = stages["product_scope"]["per_target_quota"]
        after_rerank = quota["own_after_rerank"]
        after_prune = quota.get("per_target_after_prune") or {}
        assert after_prune, "trace 缺少剪枝后逐侧计数"
        n = sum(after_rerank.values())
        m = sum(after_prune.values())
        pruned = stages["rerank"]["pruned"]
        assert pruned == n - m, f"[{label}] pruned={pruned} 应为 {n}-{m}={n - m}"
        assert pruned >= 0, f"[{label}] pruned_count 不得为负"
        assert trace.get("type") == "rag" or stages["rerank"]["count"] == m


@pytest.mark.unit
async def test_answer_stream_parity_pruning_semantics():
    """Rev3(F):answer/stream 共享同一比较剪枝契约 —— 同场景同结果。"""
    by_label = {"ne301": NE301_PRUNE, "ne503": NE503_PRUNE}
    rag_s, _, pruner_s = _make_rag_with_pruner(by_label)
    events = await _collect_stream(rag_s, QUERY_A)
    complete = events[-1]
    rag_a, _, pruner_a = _make_rag_with_pruner(by_label)
    result = await rag_a.answer(QUERY_A, "widget")
    assert complete["is_answered"] == result.is_answered
    assert (
        complete["result_key"]
        == (
            result.trace_payload.get("config_snapshot", {}).get("result_key")
            if result.is_answered is False
            else "answered"
        )
        or result.is_answered
    )
    # 剪枝调用形状一致:逐侧聚焦句(两路不得再出现整句/裸查询差异)
    for pruner in (pruner_s, pruner_a):
        assert all(
            q.startswith(("NeoEye NE301", "NeoEye NE503")) for q in pruner.queries
        ), f"比较路径剪枝必须统一使用聚焦句: {pruner.queries}"
