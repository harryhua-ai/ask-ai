"""F-1' 证据角色预留契约测试(计划驱动补位;零 LLM;阈值门控;总量有界)。

冻结语义:
- R1:required 槽 × 目标无「锚定」幸存者(STORE_OFFICIAL = 标题含产品展示名)
  → 从既有池晋升最优阈上锚定候选;证据不存在时 fail-open 不补位;
- R2:锚定 store 页补全至多一页一 chunk;R1 晋升者参与页判定;身份零重复;
- R3:PRODUCT_SPEC 槽零幸存 → 池内阈上直接晋升(R3a,零检索);池内没有才
  做一次锚定聚焦补充检索(R3b);锚定歧义(多产品)不启用;槽已满足不触发;
- 晋升不改既有幸存者及排序;低于阈值者永不晋升;总量 ≤ MAX_PROMOTIONS;
- 全槽已满足 → 零晋升零检索(不做机械配额);零新增 LLM 调用。
"""

from dataclasses import replace as _replace
from types import SimpleNamespace

import pytest

from backend.pipeline.evidence_planning import derive_evidence_plan
from backend.pipeline.evidence_reservation import (
    MAX_PROMOTIONS,
    reserve_plan_evidence,
    reserve_required_slots,
    title_anchored,
)
from backend.retrieval.search import SearchResult


def _sr(
    source_id: str,
    source_type: str,
    product: str,
    title: str,
    text: str = "正文",
    *,
    chunk_index: int = 0,
    score: float = 0.9,
    chunk_type: str = "paragraph",
) -> SearchResult:
    return SearchResult(
        text=text,
        source_id=source_id,
        source_type=source_type,
        product=product,
        title=title,
        url=f"https://example.com/{source_id}",
        score=score,
        chunk_index=chunk_index,
        chunk_type=chunk_type,
        channel_visibility=("widget", "api"),
    )


ACC_N101 = _sr("store/acc-101", "woocommerce", "ne101", "Sensor Expansion Board for NE101 and NE301")
MAIN_N101_1 = _sr("store/319", "woocommerce", "ne101", "NeoEyes NE101 Modular Sensing Camera", chunk_index=1, score=0.78)
MAIN_N101_2 = _sr("store/319", "woocommerce", "ne101", "NeoEyes NE101 Modular Sensing Camera", "变体 $69.00–$112.00", chunk_index=2, score=0.54)
MAIN_N301_1 = _sr("store/2092", "woocommerce", "ne301", "NeoEyes NE301 Wireless Edge AI Camera", chunk_index=1, score=0.75)
MAIN_N301_2 = _sr("store/2092", "woocommerce", "ne301", "NeoEyes NE301 Wireless Edge AI Camera", chunk_index=2, score=0.70)
CASE_N301 = _sr("case/battery", "filesystem", "knowledge", "NE301-电池耗尽与SIM蜂窝选项不显示")
WIKI_N301 = _sr("wiki/battery-page-a", "github", "ne301", "0-overview", "NE301 概览")


class _Taxonomy:
    """最小 taxonomy 桩:canonicalize/extract_products/display_name/is_targetable。"""

    _NAMES = {"ne101": "NeoEye NE101", "ne301": "NeoEye NE301"}

    def canonicalize(self, label):
        if not label:
            return None
        key = str(label).strip().lower()
        return key if key in self._NAMES else None

    def display_name(self, slug):
        return self._NAMES.get(slug, slug)

    def extract_products(self, text):
        low = (text or "").lower()
        return tuple(slug for slug in self._NAMES if slug in low)

    def is_targetable(self, slug):
        return slug in self._NAMES


_TAX = _Taxonomy()


def _plan(category: str, targets, mode: str = "single"):
    """derive_evidence_plan 的鸭子类型输入(与 task_understanding 输出对位)。"""
    understanding = SimpleNamespace(
        category=category,
        interaction_mode="standard",
        evidence_intent=None,
        fallback_used=False,
    )
    resolution = SimpleNamespace(mode=mode, targets=tuple(targets))
    return derive_evidence_plan(understanding, resolution)


_COMMERCIAL_2T = lambda: _plan("commercial", ("ne101", "ne301"))  # noqa: E731


# --------------------------------------------------------------------------- #
# R1:required 槽 × 目标保位
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_r1_promotes_anchored_store_when_only_accessory_survived():
    """cg-r05 形状:ne101 只有配件页幸存(标题非产品名领起)、ne301 无 store
    幸存 → 池内锚定主品页按分晋升(319#1 0.78 > 2092#1 0.75)。"""
    plan = _COMMERCIAL_2T()
    survivors = [ACC_N101]
    pool = [(MAIN_N101_1, 0.78), (MAIN_N301_1, 0.75), (CASE_N301, 0.95), (ACC_N101, 0.94)]
    promoted, fired = reserve_required_slots(
        plan, survivors, pool, taxonomy=_TAX, threshold=0.3
    )
    r1 = [f for f in fired if f["rule"] == "R1_required_slot_target"]
    by_target = {f["target"]: f["source_id"] for f in r1}
    assert by_target == {"ne101": "store/319", "ne301": "store/2092"}
    assert all(p.score >= 0.3 for p in promoted)


@pytest.mark.unit
def test_r1_no_fire_when_anchored_survivor_exists():
    """sq-026 形状:锚定主品页 chunk 已幸存 → R1 不触发(不做机械配额)。"""
    plan = _plan("commercial", ("ne101",))
    survivors = [MAIN_N101_1, CASE_N301]
    pool = [(MAIN_N101_1, 0.92), (CASE_N301, 1.1), (MAIN_N101_2, 0.54)]
    _, fired = reserve_required_slots(plan, survivors, pool, taxonomy=_TAX, threshold=0.3)
    assert not [f for f in fired if f["rule"] == "R1_required_slot_target"]


@pytest.mark.unit
def test_r1_fail_open_without_anchored_pool_candidate():
    """池内无锚定候选(只有配件)→ 不晋升配件凑数(不虚构保位)。"""
    plan = _plan("commercial", ("ne101",))
    survivors = [ACC_N101]
    pool = [(ACC_N101, 0.94)]
    promoted, _ = reserve_required_slots(plan, survivors, pool, taxonomy=_TAX, threshold=0.3)
    assert promoted == []


@pytest.mark.unit
def test_below_threshold_never_promoted():
    plan = _plan("commercial", ("ne101",))
    weak = _sr("store/319-weak", "woocommerce", "ne101", "NeoEyes NE101 Modular Sensing Camera", score=0.1)
    survivors = [ACC_N101]
    pool = [(weak, 0.1)]
    promoted, _ = reserve_required_slots(plan, survivors, pool, taxonomy=_TAX, threshold=0.3)
    assert promoted == []


# --------------------------------------------------------------------------- #
# R2:锚定页补全
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_r2_completes_anchored_page_single_sibling():
    """sq-026 形状:主品页 #1 幸存、#2(变体价表)被截 → 晋升一个最优兄弟。"""
    plan = _plan("commercial", ("ne101",))
    survivors = [MAIN_N101_1, CASE_N301]
    pool = [(MAIN_N101_1, 0.92), (CASE_N301, 1.1), (MAIN_N101_2, 0.54)]
    promoted, fired = reserve_required_slots(plan, survivors, pool, taxonomy=_TAX, threshold=0.3)
    r2 = [f for f in fired if f["rule"] == "R2_page_completion"]
    assert len(r2) == 1
    assert (r2[0]["source_id"], r2[0]["chunk_index"]) == ("store/319", 2)
    assert promoted and promoted[0].chunk_index == 2


@pytest.mark.unit
def test_r2_prefers_best_scoring_page_and_never_repeats():
    """多锚定页取幸存分最高页;R1 晋升者参与页判定;身份零重复。"""
    plan = _COMMERCIAL_2T()
    survivors = [ACC_N101]
    pool = [
        (ACC_N101, 0.94),
        (MAIN_N101_1, 0.78),
        (MAIN_N101_2, 0.54),
        (MAIN_N301_1, 0.75),
        (MAIN_N301_2, 0.70),
    ]
    promoted, fired = reserve_required_slots(plan, survivors, pool, taxonomy=_TAX, threshold=0.3)
    r2 = [f for f in fired if f["rule"] == "R2_page_completion"]
    assert len(r2) == 1  # 只补一页
    assert r2[0]["source_id"] == "store/319"  # R1 晋升 0.78 > 2092 0.75 → 补 319
    ids = [(p.source_id, p.chunk_index) for p in promoted]
    assert len(ids) == len(set(ids))


@pytest.mark.unit
def test_promotion_total_capped():
    promoted, fired = reserve_required_slots(
        _COMMERCIAL_2T(),
        [],
        [(MAIN_N101_1, 0.78), (MAIN_N301_1, 0.75), (MAIN_N101_2, 0.54)],
        taxonomy=_TAX,
        threshold=0.3,
    )
    assert len(promoted) <= MAX_PROMOTIONS
    assert len(fired) == len(promoted)


# --------------------------------------------------------------------------- #
# R3:规格救援
# --------------------------------------------------------------------------- #


@pytest.mark.unit
@pytest.mark.asyncio
async def test_r3a_promotes_from_pool_without_search():
    """support 叙事:规格槽零幸存但池内有阈上 github/wiki → 直接晋升,零检索。"""
    plan = _plan("support", ())
    survivors = [CASE_N301]
    pool = [(CASE_N301, 1.1), (WIKI_N301, 0.42)]
    calls = {"search": 0}

    class _Searcher:
        def search(self, *a, **kw):
            calls["search"] += 1
            return []

    promoted, info = await reserve_plan_evidence(
        plan, survivors, pool, taxonomy=_TAX, threshold=0.3,
        searcher=_Searcher(), reranker=object(),
    )
    assert [(p.source_id, p.chunk_index) for p in promoted] == [("wiki/battery-page-a", 0)]
    assert info["promotions"][0]["rule"] == "R3a_spec_pool"
    assert calls["search"] == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_r3b_scoped_focused_rescue_with_unique_anchor():
    """sq-045 形状:池内无阈上规格 → 唯一产品锚定 + 聚焦查询补充检索。"""
    plan = _plan("support", ())
    survivors = [CASE_N301]
    pool = [(CASE_N301, 1.1)]  # 池内无规格候选
    captured = {}

    class _Searcher:
        def search(self, query, *, limit, product_labels, channel):
            captured["query"] = query
            captured["labels"] = product_labels
            return [WIKI_N301]

    class _Reranker:
        threshold = 0.3

        def rerank_scored(self, query, results, top_k=None):
            surv = [
                _replace(WIKI_N301, score=0.8),
                _replace(_sr("wiki/qs-1", "github", "ne301", "1-quick-start"), score=0.6),
                _replace(_sr("wiki/qs-2", "github", "ne301", "2-quick-start"), score=0.59),
                _replace(_sr("wiki/qs-3", "github", "ne301", "3-quick-start"), score=0.58),
                _replace(_sr("wiki/battery-life", "github", "ne301", "5-ne301-battery-life"), score=0.56),
            ]
            return surv, [(r, r.score) for r in surv]

    promoted, info = await reserve_plan_evidence(
        plan, survivors, pool, taxonomy=_TAX, threshold=0.3,
        searcher=_Searcher(), reranker=_Reranker(),
    )
    assert captured["labels"] == ["ne301"]
    assert "NeoEye NE301" in captured["query"]
    assert "NE301-电池耗尽" in captured["query"]
    assert promoted and promoted[0].source_id == "wiki/battery-page-a"
    assert len({p.source_id for p in promoted}) == 5
    assert "wiki/battery-life" in {p.source_id for p in promoted}  # 维度权威页在座
    assert info["promotions"][-1]["rule"] == "R3b_spec_rescue"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_r3b_skips_when_anchor_ambiguous():
    """多产品锚定歧义 → 不启用(不猜)。"""
    plan = _plan("support", ())
    amb = _sr("case/x", "filesystem", "knowledge", "NE101-NE301 对比案例")
    survivors = [amb]
    pool = [(amb, 1.0)]

    class _Searcher:
        def search(self, *a, **kw):
            raise AssertionError("不应检索")

    promoted, info = await reserve_plan_evidence(
        plan, survivors, pool, taxonomy=_TAX, threshold=0.3,
        searcher=_Searcher(), reranker=object(),
    )
    assert promoted == []
    assert info["promotions"][-1].get("reason") == "no_unique_anchor"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_r3_not_fired_when_slot_met():
    plan = _plan("support", ())
    survivors = [CASE_N301, WIKI_N301]
    pool = [(CASE_N301, 1.1), (WIKI_N301, 0.42)]
    promoted, info = await reserve_plan_evidence(
        plan, survivors, pool, taxonomy=_TAX, threshold=0.3,
        searcher=object(), reranker=object(),
    )
    assert promoted == []
    assert info["promotions"][0] == {
        "rule": "R3_spec_rescue", "fired": False, "reason": "slot_met"
    }


# --------------------------------------------------------------------------- #
# 锚定谓词与全局不变量
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_title_anchored_brand_plural_tolerance():
    assert title_anchored(MAIN_N101_1, _TAX) is True   # NeoEyes ↔ NeoEye 复数容忍
    assert title_anchored(ACC_N101, _TAX) is False     # 配件名领起
    assert title_anchored(
        _sr("x", "woocommerce", "ne301", "Wi-Fi HaLow Communication Board"), _TAX
    ) is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_zero_llm_zero_retrieval_when_all_slots_met():
    """全槽已满足且无锚定页兄弟 → 零晋升、零检索(不做机械配额)。"""
    plan = _plan("commercial", ("ne101",))
    survivors = [MAIN_N101_1, CASE_N301]
    pool = [(MAIN_N101_1, 0.92), (CASE_N301, 1.1)]

    class _Searcher:
        def search(self, *a, **kw):
            raise AssertionError("不应检索")

    promoted, info = await reserve_plan_evidence(
        plan, survivors, pool, taxonomy=_TAX, threshold=0.3,
        searcher=_Searcher(), reranker=object(),
    )
    assert promoted == [] and info["fired"] is False
