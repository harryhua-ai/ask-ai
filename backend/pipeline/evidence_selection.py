"""确定性证据选择与组合(INC-5:Evidence Selection & Composition)。

把 INC-4 的 :class:`EvidencePlan` 变为可执行语义:在**既有**检索/重排/剪枝
管线的产出之上,做角色匹配、诚实覆盖计算与有界组合——零新增 LLM、零 IO、
零二次检索(契约 §9/§12)。

职责边界(冻结):
- 产品身份权威始终在 Product Resolver(本模块只消费 plan 已携带的目标域);
- 信任/可见性语义保持既有防线(chunk 级 channel_visibility 检索过滤 +
  SourceVisibilityGuard 纵深 + 引用组合白名单),本模块不新增敏感度判定,
  **不读取 sensitivity**(unknown 不抑制普通证据,I-002 v1 信任修订);
- 不增删证据总量:选择只做**稳定定序**(required 槽位命中证据前置);移除
  仍由既有 prune/不足语义门负责,组合始终保留全部有效证据。去重职责归属
  既有上游(融合 rrf_fuse 按 ``(source_id, chunk_index)`` 去重、比较合并
  seen-set),本组合是稳定排列,构造上不可能新增重复。

角色匹配只用**已持久化的结构事实**(与 INC-2a 元数据纪律一致:不做 LLM
分类、不做正文审查):

- ``PRODUCT_SPEC``    可公开引用的产品文档证据(PUBLIC_SOURCE_TYPES);
- ``SOLUTION_GUIDE``  方案/选型证据 = 可公开引用 **且** 标题/章节携带方案
  信号(冻结词表)。通用规格页无信号 → 不得虚假满足(假阴性方向安全:
  真方案未识别 = 诚实 uncovered,可观察;假阳性 = 虚假覆盖,禁止);
- ``CASE_EVIDENCE``   filesystem 内部案例(跨产品设计,存于 knowledge 域
  ——既有知识桶结构事实),背景参与,永不进入公开编号引用权威;
- ``STORE_OFFICIAL``  woocommerce(官方商店)专属。wiki/官网提及同价格、
  同产品也不得冒充 Store 商务真相(角色即权威,内容不转正);
- 未知角色:无可验证语义 → 不匹配(宁可诚实 uncovered,不可虚假覆盖)。

引用/信任语义:
- ``CITABLE_REQUIRED`` 槽只能被**结构上可公开编号引用**的证据满足,且
  覆盖判定以终局上下文的可引用集合为准(超可见上限被丢弃的公开证据
  不得计入);
- ``BACKGROUND_ALLOWED`` 槽可被背景证据满足,但背景资格**永不升格**为
  公开引用权威(组合期既有语义,本模块不改变分节规则)。

覆盖真值(契约核心不变量):covered = 匹配证据 **确实进入终局生成上下文**
(可引用段或背景段)。请求被拒/证据被剪/被可见上限截断 → 一律不得继续
计入覆盖;matched 仍如实保留候选面语义匹配(诊断:证据存在但未达生成)。
"""

from dataclasses import dataclass

from backend.pipeline.citation import PUBLIC_SOURCE_TYPES
from backend.pipeline.evidence_planning import (
    CITATION_CITABLE_REQUIRED,
    ROLE_CASE_EVIDENCE,
    ROLE_PRODUCT_SPEC,
    ROLE_SOLUTION_GUIDE,
    ROLE_STORE_OFFICIAL,
    EvidencePlan,
    EvidenceSlot,
)

# --------------------------------------------------------------------------- #
# 冻结参数
# --------------------------------------------------------------------------- #

#: 方案/选型结构信号(对 title + doc_section 做小写包含匹配;保守词表:
#: 假阴性=诚实 uncovered,假阳性=虚假覆盖,故只收强信号)
_SOLUTION_SIGNALS: tuple[str, ...] = ("选型", "方案", "solution")

#: 案例证据连接器类型(support 案例存为 filesystem,product=knowledge)
_SOURCE_CASE = "filesystem"

#: 官方商店连接器类型(STORE_OFFICIAL 唯一结构权威来源)
_SOURCE_STORE = "woocommerce"

#: 单槽 matched 身份上限(trace 有界,§12;超出以 matched_truncated 标记)
_MAX_MATCHED_PER_SLOT = 8

# --------------------------------------------------------------------------- #
# 值对象(frozen,可安全进 trace)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SlotCoverage:
    """单槽覆盖真值。

    Attributes:
        role / product_scope / required / citation_requirement: 槽位契约原样
            (product_scope 为**解析后**的生效域:显式域或继承 resolver 目标;
            CASE_EVIDENCE 恒为空域=跨产品设计)。
        covered: 匹配证据是否确实进入终局生成上下文(含引用资格处置)。
        matched: 语义匹配该槽的候选稳定身份 (source_id, chunk_index)
            (候选面真相;covered 与之解耦——存在但未达生成时不计覆盖)。
        matched_truncated: matched 是否超出有界上限。
    """

    role: str
    product_scope: tuple[str, ...]
    required: bool
    citation_requirement: str
    covered: bool
    matched: tuple[tuple[str, int], ...] = ()
    matched_truncated: bool = False


@dataclass(frozen=True)
class CoverageReport:
    """计划级覆盖报告(契约 §6)。

    coverage_complete 当且仅当每个 required 槽都被**终局上下文内**的证据
    覆盖;缺失 optional 槽不影响完整性。
    """

    slots: tuple[SlotCoverage, ...]
    required_total: int
    required_covered: int
    coverage_complete: bool
    missing_required: tuple[str, ...]


# --------------------------------------------------------------------------- #
# 角色匹配(纯谓词;全 total、不抛错)
# --------------------------------------------------------------------------- #


def _product_slug(result, taxonomy) -> str:
    """候选产品 slug:taxonomy 可用时权威 canonicalize,否则保守小写。"""
    raw = (result.product or "").strip().lower()
    if taxonomy is None:
        return raw
    try:
        return taxonomy.canonicalize(result.product) or raw
    except Exception:  # noqa: BLE001 — 匹配谓词永不抛错(fail-open 至 raw)
        return raw


def resolved_scope(slot: EvidenceSlot, resolution_targets: tuple[str, ...]) -> tuple[str, ...]:
    """槽位生效产品域:显式域优先;空域按角色语义继承。

    CASE_EVIDENCE 空域 = 任意产品(support 案例跨产品设计,存于 knowledge
    域——既有知识桶结构事实),不继承 resolver 目标;其余角色空域继承
    resolver 目标(身份权威链:plan.resolution_targets 来自 resolver)。
    """
    if slot.product_scope:
        return slot.product_scope
    if slot.role == ROLE_CASE_EVIDENCE:
        return ()
    return tuple(resolution_targets or ())


def _has_solution_signal(result) -> bool:
    hay = f"{result.title or ''}\n{result.doc_section or ''}".lower()
    return any(signal in hay for signal in _SOLUTION_SIGNALS)


def evidence_matches_slot(
    slot: EvidenceSlot,
    candidate,
    *,
    resolution_targets: tuple[str, ...] = (),
    taxonomy=None,
) -> bool:
    """候选证据是否**语义匹配**槽位(结构事实谓词;不含上下文可用性)。

    Args:
        slot: 证据槽位(INC-4 冻结词表)。
        candidate: :class:`~backend.retrieval.search.SearchResult`。
        resolution_targets: resolver 目标域(空 scope 槽的继承来源)。
        taxonomy: 产品 taxonomy(None 时退化为原始 product 小写匹配)。

    Returns:
        bool。对任意输入 total、确定性;未知角色/非法输入一律 False
        (不虚假覆盖),绝不抛错。
    """
    source_type = candidate.source_type or ""

    # 角色谓词(仅持久化结构事实)
    if slot.role == ROLE_PRODUCT_SPEC:
        if source_type not in PUBLIC_SOURCE_TYPES:
            return False
    elif slot.role == ROLE_SOLUTION_GUIDE:
        if source_type not in PUBLIC_SOURCE_TYPES or not _has_solution_signal(candidate):
            return False
    elif slot.role == ROLE_CASE_EVIDENCE:
        if source_type != _SOURCE_CASE:
            return False
    elif slot.role == ROLE_STORE_OFFICIAL:
        if source_type != _SOURCE_STORE:
            return False
    else:
        # 未知角色:无可验证语义,不得虚假覆盖
        return False

    # 引用资格:CITABLE_REQUIRED 只接受结构上可公开编号引用的证据
    if slot.citation_requirement == CITATION_CITABLE_REQUIRED and (
        source_type not in PUBLIC_SOURCE_TYPES
    ):
        return False

    # 产品隔离:生效域非空时,域外证据一律不匹配
    scope = resolved_scope(slot, resolution_targets)
    if scope and _product_slug(candidate, taxonomy) not in scope:
        return False

    return True


# --------------------------------------------------------------------------- #
# 选择/组合(稳定定序 + 身份去重;不增删证据)
# --------------------------------------------------------------------------- #


def order_candidates_for_plan(
    plan: EvidencePlan,
    candidates: list,
    *,
    taxonomy=None,
) -> tuple[list, dict]:
    """按计划对候选做确定性组合定序(required 槽命中证据稳定前置)。

    - 稳定:各分区内部保持既有排序(排名/重排约束不被重写);
    - 有界:不增删证据(移除仍归既有 prune/不足语义门);
    - 去重职责归属既有上游:融合 ``rrf_fuse`` 以 ``(source_id, chunk_index)``
      去重、比较合并以 seen-set 去重——到达本函数的候选身份已结构性唯一
      (同键重复在上游即塌缩)。本函数是**稳定排列**,构造上不可能新增重复;
      在此再按身份去重反而会把「测试夹具/异常数据中的同身份不同证据」静默
      丢弃(契约 §9-L 的"不错误重复"由上游唯一性 + 本函数不复制保证);
    - 空 plan(零检索模式)或无 required 槽 → 恒等(零行为变更)。

    Returns:
        (定序后的候选列表, selection info:
         ``{"reordered": bool, "required_matched": int, "total": int}``)
    """
    info = {"reordered": False, "required_matched": 0, "total": len(candidates)}
    if not plan.slots or not candidates:
        return list(candidates), info

    required_slots = [s for s in plan.slots if s.required]
    if not required_slots:
        return list(candidates), info

    targets = tuple(plan.resolution_targets or ())
    primary: list = []
    secondary: list = []
    for r in candidates:
        if any(
            evidence_matches_slot(s, r, resolution_targets=targets, taxonomy=taxonomy)
            for s in required_slots
        ):
            primary.append(r)
            info["required_matched"] += 1
        else:
            secondary.append(r)
    ordered = primary + secondary
    info["reordered"] = [(r.source_id, r.chunk_index) for r in ordered] != [
        (r.source_id, r.chunk_index) for r in candidates
    ]
    return ordered, info


# --------------------------------------------------------------------------- #
# 覆盖计算(终局上下文真值)
# --------------------------------------------------------------------------- #


def context_id_sets(citation_stats: dict) -> tuple[frozenset, frozenset]:
    """从 ``build_citation_context`` 的 stats 提取终局上下文身份集合。

    Returns:
        (可引用段身份集, 背景段身份集);dropped_public(超可见上限被丢弃)
        **不在**任何集合中——它们未进入生成上下文,不得计入覆盖。
    """
    citable = frozenset(
        (c.get("source_id"), c.get("chunk_index")) for c in citation_stats.get("citable", ())
    )
    background = frozenset(
        (c.get("source_id"), c.get("chunk_index")) for c in citation_stats.get("background", ())
    )
    return citable, background


def build_coverage_report(
    plan: EvidencePlan,
    candidates: list,
    *,
    taxonomy=None,
    citable_ids: frozenset = frozenset(),
    background_ids: frozenset = frozenset(),
) -> CoverageReport:
    """计算计划级诚实覆盖报告(纯函数,total)。

    Args:
        plan: INC-4 证据计划。
        candidates: 终局候选(经既有 prune/纵深过滤/组合定序后的证据面)。
        citable_ids / background_ids: 终局生成上下文的可引用段/背景段身份集
            (:func:`context_id_sets`);空集(如生成被拒)⇒ 全部 uncovered。

    覆盖语义:matched = 候选面语义匹配(诊断真相);covered = 匹配证据以
    符合槽位引用资格的处置**实际进入**终局上下文。
    """
    targets = tuple(plan.resolution_targets or ())
    slot_coverages: list[SlotCoverage] = []
    for slot in plan.slots:
        matched: list[tuple[str, int]] = []
        truncated = False
        in_context = 0
        require_citable = slot.citation_requirement == CITATION_CITABLE_REQUIRED
        for r in candidates:
            if not evidence_matches_slot(slot, r, resolution_targets=targets, taxonomy=taxonomy):
                continue
            key = (r.source_id, r.chunk_index)
            available = key in citable_ids or (not require_citable and key in background_ids)
            if available:
                in_context += 1
            if len(matched) < _MAX_MATCHED_PER_SLOT:
                matched.append(key)
            else:
                truncated = True
        slot_coverages.append(
            SlotCoverage(
                role=slot.role,
                product_scope=resolved_scope(slot, targets),
                required=slot.required,
                citation_requirement=slot.citation_requirement,
                covered=in_context > 0,
                matched=tuple(matched),
                matched_truncated=truncated,
            )
        )

    required = [s for s in slot_coverages if s.required]
    required_total = len(required)
    required_covered = sum(1 for s in required if s.covered)
    missing = tuple(
        f"{s.role}" + (f"({','.join(s.product_scope)})" if s.product_scope else "")
        for s in slot_coverages
        if s.required and not s.covered
    )
    return CoverageReport(
        slots=tuple(slot_coverages),
        required_total=required_total,
        required_covered=required_covered,
        coverage_complete=required_covered == required_total,
        missing_required=missing,
    )


# --------------------------------------------------------------------------- #
# 有界 trace(§12:稳定身份 + 元数据,零 chunk 正文)
# --------------------------------------------------------------------------- #


def build_evidence_stage(report: CoverageReport, selection_info: dict | None = None) -> dict:
    """把覆盖报告(与可选选择信息)序列化为有界 trace 阶段。"""
    coverage = {
        "coverage_complete": report.coverage_complete,
        "required_total": report.required_total,
        "required_covered": report.required_covered,
        "missing_required": list(report.missing_required),
        "slots": [
            {
                "role": s.role,
                "product_scope": list(s.product_scope),
                "required": s.required,
                "citation_requirement": s.citation_requirement,
                "covered": s.covered,
                "matched": [{"source_id": sid, "chunk_index": cidx} for sid, cidx in s.matched],
                "matched_truncated": s.matched_truncated,
            }
            for s in report.slots
        ],
    }
    stage: dict = {"coverage": coverage}
    if selection_info is not None:
        stage["selection"] = dict(selection_info)
    return stage
