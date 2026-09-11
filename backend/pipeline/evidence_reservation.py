"""F-1' 证据角色预留 —— 计划驱动的 rerank 截断补位。

RCA(2026-09-11 只读实测,probe_f1p):

- rerank ``top_k`` 截断是候选到上下文的唯一转换点,计划 **required** 槽
  没有保留权:cg-r05 实测 NE101 产品页 chunk 加权 0.7878,距 rank-10 截断线
  0.7934 差 0.0057,一位于阈上被截;同 query 下 NE301 商品格同样在阈上落榜
  (0.7537/0.7018),而 commercial 计划的 STORE_OFFICIAL 是 required 槽,
  幸存的却是配件页 chunk(标题不以产品名领起,不含变体价)。
- sq-026:主品页 chunk(含变体价表)#1 幸存但 #2 被截 —— 同页证据被截断
  撕裂,答案只见基础价不见变体区间。
- sq-045(support 叙事,查询不含产品名):规格证据从未进入候选池
  (电池 wiki 在 hybrid 深度 69-96 才出现;池内截断下候选全部 <0.3)。

机制(三规则,全部计划驱动、阈值门控、零 LLM 调用、总量有界):

- **R1 required 槽 × 目标保位**:required 槽在某目标上没有「锚定」幸存者
  (STORE_OFFICIAL 的锚定 = 标题含该目标展示名,容忍品牌词复数 —— 官方
  商品格以产品名领起,配件页以配件名领起)→ 从**既有池**按加权分晋升
  最优锚定候选。非 STORE 角色退化为「该目标无任何匹配幸存者」即晋升。
- **R2 锚定页补全**:锚定 store 页已有幸存 chunk(含 R1 刚晋升者)→ 晋升
  该页**一个**最优阈上兄弟 chunk(变体/价表常被按块切分,截断把同页证据
  撕裂)。
- **R3 规格救援**:PRODUCT_SPEC 槽零幸存者时 —— 池内有阈上匹配先直接晋升
  (R3a);池内也没有才做**至多一次**补充检索:锚定产品取自幸存案例标题
  (唯一产品才启用),聚焦查询 = ``<展示名> <案例标题>``,晋升聚焦重排
  阈上 top-6 页(每页最优 chunk;维度权威页在产品名密集的池中常排 4-6 位;
  R3b;与比较管线的聚焦重排同一先例:整句叙事把官方文档压到阈下
  0.2237,聚焦句式 0.7230,冻结 RCA)。

不做的事:不全局抬 top_k;不做按 source-type 机械配额;不改动既有幸存者
及其排序;比较管线(自有逐目标聚焦重排)不触碰;任何规则在证据不存在时
fail-open 不补位(不虚构)。
"""

from dataclasses import replace
import re
import time
from typing import Any, Awaitable, Callable

from backend.pipeline.evidence_planning import (
    ROLE_PRODUCT_SPEC,
    ROLE_STORE_OFFICIAL,
    EvidencePlan,
    EvidenceSlot,
)
from backend.pipeline.evidence_selection import (
    _product_slug,
    evidence_matches_slot,
    resolved_scope,
)

#: R1+R2 晋升总量上限(含跨槽;预留是保位,不是扩容)。
MAX_PROMOTIONS = 4
#: R3b 补充检索的候选深度(聚焦 + 产品过滤 + 渠道过滤后的小池)。
RESCUE_POOL_LIMIT = 30
#: R3b 晋升页数上限(不同页各取最优 chunk;维度权威页常排 4-6 位)。
RESCUE_MAX_PAGES = 6
#: R3 锚定推断所考察的最大幸存者数(标题推断,仅取唯一产品)。
ANCHOR_SCAN_LIMIT = 3

_PATTERN_CACHE: dict[str, re.Pattern[str] | None] = {}


def _display_name_pattern(display_name: str) -> re.Pattern[str] | None:
    """展示名 → 容忍品牌词复数的标题匹配模式(``NeoEye``↔``NeoEyes``)。

    仅对 ≥4 字符的纯字母词允许尾随 ``s``(型号数字词不变形);词间允许
    单个空格/连字符;两侧数字边界防 ``NE1010`` 类误命中。
    """
    key = display_name.strip().lower()
    if key in _PATTERN_CACHE:
        return _PATTERN_CACHE[key]
    tokens = [t for t in key.split() if t]
    pattern: re.Pattern[str] | None = None
    if tokens:
        parts = []
        for tok in tokens:
            esc = re.escape(tok)
            if len(tok) >= 4 and tok.isalpha():
                esc += "s?"
            parts.append(esc)
        pattern = re.compile(r"(?<![a-z0-9])" + r"[\s-]?".join(parts) + r"(?![a-z0-9])")
    _PATTERN_CACHE[key] = pattern
    return pattern


def title_anchored(result: Any, taxonomy: Any) -> bool:
    """chunk 标题是否含其产品展示名(容忍品牌词复数;产品身份不换页)。"""
    title = (getattr(result, "title", None) or "").strip().lower()
    if not title:
        return False
    slug = _product_slug(result, taxonomy)
    if not slug:
        return False
    pattern = _display_name_pattern(taxonomy.display_name(slug))
    return pattern is not None and bool(pattern.search(title))


def _for_target(result: Any, target: str | None, taxonomy: Any) -> bool:
    return target is None or _product_slug(result, taxonomy) == target


def _matching(
    slot: EvidenceSlot,
    candidates: list[Any],
    *,
    plan: EvidencePlan,
    taxonomy: Any,
    target: str | None,
) -> list[Any]:
    return [
        r
        for r in candidates
        if evidence_matches_slot(
            slot, r, resolution_targets=plan.resolution_targets, taxonomy=taxonomy
        )
        and _for_target(r, target, taxonomy)
    ]


def reserve_required_slots(
    plan: EvidencePlan,
    survivors: list[Any],
    pool_scores: list[tuple[Any, float]],
    *,
    taxonomy: Any,
    threshold: float,
    is_eligible: Callable[[Any], bool] | None = None,
    max_total: int = MAX_PROMOTIONS,
) -> tuple[list[Any], list[dict[str, Any]]]:
    """R1+R2:required 槽保位与锚定页补全(纯函数;零检索零 LLM)。

    Args:
        plan: 证据计划(仅 required 槽参与)。
        survivors: 重排幸存者(当前终态,不含将晋升的候选)。
        pool_scores: ``RerankPipeline.rerank_scored`` 的全量加权分数表。
        taxonomy: 产品 taxonomy。
        threshold: rerank 分数阈值(晋升候选必须同阈达标)。
        is_eligible: 产品资格谓词(产品边界启用时传入;None = 不另过滤)。
        max_total: 晋升总量上限。

    Returns:
        (晋升候选列表 —— 按 score=加权分 replace 过,晋升记录列表 —— 供
        trace/审计)。
    """
    score_by_id: dict[tuple[str, int], float] = {}
    for r, sc in pool_scores:
        score_by_id[(r.source_id, r.chunk_index)] = sc
    current = list(survivors)  # 含本函数晋升者,后续判定/R2 看实时终态
    taken = {(s.source_id, s.chunk_index) for s in current}
    promoted: list[Any] = []
    fired: list[dict[str, Any]] = []

    def _eligible(r: Any) -> bool:
        return is_eligible is None or is_eligible(r)

    def _promote(
        rule: str,
        slot: EvidenceSlot,
        target: str | None,
        candidates: list[Any],
    ) -> None:
        avail = [
            (r, score_by_id[(r.source_id, r.chunk_index)])
            for r in candidates
            if score_by_id.get((r.source_id, r.chunk_index), float("-inf")) >= threshold
            and (r.source_id, r.chunk_index) not in taken
            and _eligible(r)
        ]
        if not avail:
            return
        avail.sort(key=lambda p: p[1], reverse=True)
        r, sc = avail[0]
        promoted.append(replace(r, score=sc))
        current.append(promoted[-1])
        taken.add((r.source_id, r.chunk_index))
        fired.append(
            {
                "rule": rule,
                "role": slot.role,
                "target": target,
                "source_id": r.source_id,
                "chunk_index": r.chunk_index,
                "score": round(sc, 4),
            }
        )

    # R1:required 槽 × 目标保位
    for slot in plan.slots:
        if len(fired) >= max_total:
            break
        if not slot.required:
            continue
        scope = resolved_scope(slot, plan.resolution_targets)
        for target in scope if scope else (None,):
            surv_m = _matching(
                slot, current, plan=plan, taxonomy=taxonomy, target=target
            )
            if slot.role == ROLE_STORE_OFFICIAL:
                met = any(title_anchored(s, taxonomy) for s in surv_m)
            else:
                met = bool(surv_m)
            if met:
                continue
            pool_m = _matching(
                slot,
                [r for r, _ in pool_scores],
                plan=plan,
                taxonomy=taxonomy,
                target=target,
            )
            if slot.role == ROLE_STORE_OFFICIAL:
                pool_m = [r for r in pool_m if title_anchored(r, taxonomy)]
            _promote("R1_required_slot_target", slot, target, pool_m)

    # R2:锚定 store 页补全(至多一页;取幸存分最高的锚定页)
    for slot in plan.slots:
        if len(fired) >= max_total:
            break
        if not (slot.required and slot.role == ROLE_STORE_OFFICIAL):
            continue
        scope = resolved_scope(slot, plan.resolution_targets)
        pages: dict[str, tuple[float, str | None]] = {}
        for target in scope if scope else (None,):
            for s in _matching(
                slot, current, plan=plan, taxonomy=taxonomy, target=target
            ):
                if title_anchored(s, taxonomy) and (s.score or 0) > pages.get(
                    s.source_id, (-1.0, None)
                )[0]:
                    pages[s.source_id] = (s.score or 0, target)
        if not pages:
            continue
        for page, (_sc, target) in sorted(pages.items(), key=lambda kv: -kv[1][0]):
            before = len(fired)
            _promote(
                "R2_page_completion",
                slot,
                target,
                [r for r, _ in pool_scores if r.source_id == page],
            )
            if len(fired) > before:
                break

    return promoted, fired


def _infer_anchor(survivors: list[Any], taxonomy: Any) -> str | None:
    """从幸存者标题推断唯一目标产品(多产品/无命中 = 不启用,不猜)。"""
    for s in survivors[:ANCHOR_SCAN_LIMIT]:
        slugs = [
            slug
            for slug in taxonomy.extract_products(s.title or "")
            if taxonomy.is_targetable(slug)
        ]
        if len(slugs) == 1:
            return slugs[0]
    return None


async def reserve_support_spec(
    plan: EvidencePlan,
    survivors: list[Any],
    pool_scores: list[tuple[Any, float]],
    *,
    taxonomy: Any,
    threshold: float,
    is_eligible: Callable[[Any], bool] | None = None,
    searcher: Any = None,
    guard_fn: Callable[[list[Any]], Awaitable[list[Any]]] | None = None,
    reranker: Any = None,
    channel: str | None = None,
) -> tuple[list[Any], list[dict[str, Any]]]:
    """R3:PRODUCT_SPEC 槽零幸存时的规格救援(池内优先,补充检索兜底)。

    触发即「计划声明了规格证据需求而终局上下文一条都没有」—— 与
    required 与否无关(coverage 语义同样追踪 optional 槽);rescue 至多
    晋升 6 页(每页最优 chunk),锚定/聚焦失败一律 fail-open 不补位。

    Returns:
        (晋升候选列表, 记录列表 —— 含未触发原因,供 trace 归因)。
    """
    fired: list[dict[str, Any]] = []
    promoted: list[Any] = []
    spec_slots = [s for s in plan.slots if s.role == ROLE_PRODUCT_SPEC]
    if not spec_slots or not survivors:
        return [], fired
    slot = spec_slots[0]
    if _matching(slot, survivors, plan=plan, taxonomy=taxonomy, target=None):
        fired.append({"rule": "R3_spec_rescue", "fired": False, "reason": "slot_met"})
        return [], fired
    taken = {(s.source_id, s.chunk_index) for s in survivors}

    def _eligible(r: Any) -> bool:
        return is_eligible is None or is_eligible(r)

    # R3a:池内阈上匹配直接晋升(零新增检索)
    pool_m = [
        (r, sc)
        for r, sc in pool_scores
        if sc >= threshold
        and (r.source_id, r.chunk_index) not in taken
        and evidence_matches_slot(
            slot, r, resolution_targets=plan.resolution_targets, taxonomy=taxonomy
        )
        and _eligible(r)
    ]
    if pool_m:
        pool_m.sort(key=lambda p: p[1], reverse=True)
        r, sc = pool_m[0]
        promoted.append(replace(r, score=sc))
        fired.append(
            {
                "rule": "R3a_spec_pool",
                "source_id": r.source_id,
                "chunk_index": r.chunk_index,
                "score": round(sc, 4),
            }
        )
        return promoted, fired

    # R3b:锚定 + 聚焦补充检索(唯一产品锚定才启用)
    if searcher is None or reranker is None:
        return [], fired
    anchor = _infer_anchor(survivors, taxonomy)
    if anchor is None:
        fired.append(
            {"rule": "R3b_spec_rescue", "fired": False, "reason": "no_unique_anchor"}
        )
        return [], fired
    focused_query = f"{taxonomy.display_name(anchor)} {(survivors[0].title or '').strip()}".strip()
    try:
        results = searcher.search(
            focused_query,
            limit=RESCUE_POOL_LIMIT,
            product_labels=[anchor],
            channel=channel,
        )
    except Exception:  # noqa: BLE001 — 补充检索失败不阻断主流程(fail-open)
        fired.append({"rule": "R3b_spec_rescue", "fired": False, "reason": "search_error"})
        return [], fired
    if guard_fn is not None:
        results = await guard_fn(results)
    if not results:
        fired.append(
            {"rule": "R3b_spec_rescue", "fired": False, "reason": "empty_rescue_pool"}
        )
        return [], fired
    rescue_survivors, _ = reranker.rerank_scored(
        focused_query, results, top_k=max(len(results), 1)
    )
    threshold_pass = [r for r in rescue_survivors if (r.score or 0) >= threshold]
    # 晋升至多 3 条且来自不同页:聚焦重排的榜首可能被产品名密集的页面占据,
    # 而维度权威页(如规格矩阵)紧随其后 —— 多页晋升保证维度证据在座。
    picks: list[Any] = []
    seen_pages: set[str] = set()
    for r in threshold_pass:
        if r.source_id in seen_pages:
            continue
        picks.append(r)
        seen_pages.add(r.source_id)
        if len(picks) >= RESCUE_MAX_PAGES:
            break
    if not picks:
        fired.append(
            {"rule": "R3b_spec_rescue", "fired": False, "reason": "below_threshold"}
        )
        return [], fired
    promoted.extend(picks)
    fired.append(
        {
            "rule": "R3b_spec_rescue",
            "anchor": anchor,
            "focused_query": focused_query,
            "promoted": [
                {"source_id": p.source_id, "chunk_index": p.chunk_index,
                 "score": round(p.score, 4)}
                for p in picks
            ],
        }
    )
    return promoted, fired


async def reserve_plan_evidence(
    plan: EvidencePlan,
    survivors: list[Any],
    pool_scores: list[tuple[Any, float]],
    *,
    taxonomy: Any,
    threshold: float,
    is_eligible: Callable[[Any], bool] | None = None,
    searcher: Any = None,
    guard_fn: Callable[[list[Any]], Awaitable[list[Any]]] | None = None,
    reranker: Any = None,
    channel: str | None = None,
) -> tuple[list[Any], dict[str, Any]]:
    """F-1' 预留总入口:R1+R2(纯函数)+ R3(异步救援)。

    返回的候选**追加**在幸存者之后(定序由既有
    ``order_candidates_for_plan`` 按槽命中前置,此处不改既有排序);
    ``info`` 为 ``{"fired": bool, "promotions": [...], "ms": int}``。
    """
    t0 = time.monotonic()
    promoted_r12, fired_r12 = reserve_required_slots(
        plan,
        survivors,
        pool_scores,
        taxonomy=taxonomy,
        threshold=threshold,
        is_eligible=is_eligible,
    )
    promoted: list[Any] = list(promoted_r12)
    fired: list[dict[str, Any]] = list(fired_r12)
    if promoted:
        survivors = survivors + promoted  # R3 的「零幸存」判定看含 R1/R2 后终态
    promoted_r3, fired_r3 = await reserve_support_spec(
        plan,
        survivors,
        pool_scores,
        taxonomy=taxonomy,
        threshold=threshold,
        is_eligible=is_eligible,
        searcher=searcher,
        guard_fn=guard_fn,
        reranker=reranker,
        channel=channel,
    )
    promoted.extend(promoted_r3)
    fired.extend(fired_r3)
    info = {
        "fired": bool(promoted),
        "promotions": fired,
        "ms": int((time.monotonic() - t0) * 1000),
    }
    return promoted, info
