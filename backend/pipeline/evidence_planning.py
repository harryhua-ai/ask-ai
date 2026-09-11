"""确定性证据规划(INC-4:Evidence Planning)。

把**已完成的**任务理解(TaskUnderstanding)与产品解析(ProductResolution)
确定性转换为显式 :class:`EvidencePlan`——回答需要什么证据。

冻结架构边界(契约 §3):
- 产品身份权威在 Product Resolver(先于理解,本模块只消费其输出);
- 任务理解权威在既有单次 ``understand_task`` 调用(INC-3),本模块零 LLM;
- 规划是纯本地确定性查表:零 IO、零 LLM、零网络往返,失败全 fail-open;
- 本增量只产出"需要什么证据"的计划;证据的最终选择/组合/拒答裁决属 INC-5;
- comparison 模式下既有比较证据管线保持冻结执行,plan 仅为其语义投影。

四角色词表(冻结,与 I-002 契约收口 §7 一致):
- ``PRODUCT_SPEC``    产品规格/功能/参数证据(公开文档);
- ``SOLUTION_GUIDE``  方案/选型指南证据(推荐/方案设计类任务的目标证据);
- ``CASE_EVIDENCE``   支持案例证据(filesystem 内部案例;背景参与,不公开引用);
- ``STORE_OFFICIAL``  官方商店证据(commercial 现行商务真相当局;
  wiki 价格不得静默替代 Store 真相——缺失经 planning/coverage 语义可观察)。

引用要求词表(冻结):
- ``CITABLE_REQUIRED``   该槽位证据必须可公开编号引用;
- ``BACKGROUND_ALLOWED`` 允许背景参与生成(不可公开引用,如内部案例)。

sensitivity 边界(I-002 v1 冻结):unknown 不抑制证据;internal 可见性由既有
检索/可见性语义保护;personal-data 保留无生产者。本模块不做任何敏感度判定。
"""

from dataclasses import dataclass

from backend.pipeline.product_resolver import MODE_COMPARISON
from backend.pipeline.task_understanding import (
    EVIDENCE_INTENT_FACTUAL,
    EVIDENCE_INTENT_RECOMMENDATION,
    MODE_CAPABILITY,
    MODE_CLARIFICATION,
    MODE_OFF_TOPIC,
)

# --------------------------------------------------------------------------- #
# 冻结词表
# --------------------------------------------------------------------------- #

ROLE_PRODUCT_SPEC = "PRODUCT_SPEC"
ROLE_SOLUTION_GUIDE = "SOLUTION_GUIDE"
ROLE_CASE_EVIDENCE = "CASE_EVIDENCE"
ROLE_STORE_OFFICIAL = "STORE_OFFICIAL"
EVIDENCE_ROLES = (
    ROLE_PRODUCT_SPEC,
    ROLE_SOLUTION_GUIDE,
    ROLE_CASE_EVIDENCE,
    ROLE_STORE_OFFICIAL,
)

CITATION_CITABLE_REQUIRED = "CITABLE_REQUIRED"
CITATION_BACKGROUND_ALLOWED = "BACKGROUND_ALLOWED"
CITATION_REQUIREMENTS = (CITATION_CITABLE_REQUIRED, CITATION_BACKGROUND_ALLOWED)

# 零检索交互模式:合法交互结果,不进入证据检索(F/G/H 冻结语义)
_ZERO_RETRIEVAL_MODES = frozenset({MODE_CLARIFICATION, MODE_CAPABILITY, MODE_OFF_TOPIC})


# --------------------------------------------------------------------------- #
# 值对象(frozen,可哈希,可安全进 trace/日志)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class EvidenceSlot:
    """单条证据需求(语义契约,不含检索实现参数)。

    Attributes:
        role: 证据角色(四角色词表)。
        product_scope: 产品 slug 域;空元组 = 继承 resolver 解析的目标域
            (产品身份权威始终在 resolver)。
        required: 覆盖义务。v1 执行语义 = trace/coverage 信号,不改变既有
            拒答路径(零基线回归);执行收严属 INC-5 裁决。
        citation_requirement: 引用要求(CITABLE_REQUIRED / BACKGROUND_ALLOWED)。
    """

    role: str
    product_scope: tuple[str, ...] = ()
    required: bool = False
    citation_requirement: str = CITATION_CITABLE_REQUIRED


@dataclass(frozen=True)
class EvidencePlan:
    """确定性证据计划(有界归因,无思维链)。

    Attributes:
        slots: 有序证据槽位(零槽位 = 该任务形态不需要证据检索)。
        evidence_intent: 产生计划的证据意图(factual / recommendation)。
        category / interaction_mode / resolution_mode / resolution_targets:
            产生计划所依据的既有任务/解析事实(bounded trace attribution)。
        fallback_used: 输入是否处于回退态(透传理解回退,供归因)。
    """

    slots: tuple[EvidenceSlot, ...] = ()
    evidence_intent: str = EVIDENCE_INTENT_FACTUAL
    category: str = ""
    interaction_mode: str = ""
    resolution_mode: str = "none"
    resolution_targets: tuple[str, ...] = ()
    fallback_used: bool = False


def _spec(required: bool) -> EvidenceSlot:
    return EvidenceSlot(role=ROLE_PRODUCT_SPEC, required=required)


def derive_evidence_plan(understanding, resolution) -> EvidencePlan:
    """把任务理解 + 产品解析确定性映射为证据计划(纯函数,冻结语义表)。

    Args:
        understanding: :class:`~backend.pipeline.task_understanding.TaskUnderstanding`
            (鸭子类型:category / interaction_mode / evidence_intent / fallback_used)。
        resolution: ProductResolution(mode / targets;产品身份唯一权威)。

    Returns:
        :class:`EvidencePlan`。对任意输入全总、确定性、不抛错;输入回退态
        透传至 ``fallback_used``;非法 evidence_intent 一律 fail-open 为
        factual(检索保持可用)。
    """
    evidence_intent = getattr(understanding, "evidence_intent", None)
    if evidence_intent not in (EVIDENCE_INTENT_FACTUAL, EVIDENCE_INTENT_RECOMMENDATION):
        evidence_intent = EVIDENCE_INTENT_FACTUAL

    category = getattr(understanding, "category", None)
    mode = getattr(understanding, "interaction_mode", None)
    res_mode = getattr(resolution, "mode", None)
    res_targets = tuple(getattr(resolution, "targets", ()) or ())
    input_fallback = bool(getattr(understanding, "fallback_used", False))

    def _plan(slots) -> EvidencePlan:
        return EvidencePlan(
            slots=tuple(slots),
            evidence_intent=evidence_intent,
            category=str(category or ""),
            interaction_mode=str(mode or ""),
            resolution_mode=str(res_mode or "none"),
            resolution_targets=res_targets,
            fallback_used=input_fallback,
        )

    # F/G/H:零检索交互模式(澄清/能力导向/真无关)→ 无证据检索计划。
    # 先于一切 intent/category 判定:畸形输入不得把零检索任务变成检索计划。
    if mode in _ZERO_RETRIEVAL_MODES:
        return _plan(())

    # E:comparison → 每 resolver 目标一个 PRODUCT_SPEC(语义投影;
    # 既有比较证据管线执行行为保持冻结,本模块不触碰)
    if res_mode == MODE_COMPARISON:
        return _plan(
            [
                EvidenceSlot(
                    role=ROLE_PRODUCT_SPEC,
                    product_scope=(target,),
                    required=True,
                    citation_requirement=CITATION_CITABLE_REQUIRED,
                )
                for target in res_targets
            ]
        )

    # 支撑槽:PRODUCT_SPEC optional(除 factual 主槽外的公共伴生槽)
    _support = _spec(False)

    if category == "support":
        # C:案例证据背景参与(不公开可引用),规格证据支撑
        return _plan(
            [
                EvidenceSlot(
                    role=ROLE_CASE_EVIDENCE,
                    required=False,
                    citation_requirement=CITATION_BACKGROUND_ALLOWED,
                ),
                _support,
            ]
        )

    if category == "commercial":
        # D:Store 当局证据 required;规格证据可选。
        # Store 缺失不静默以 wiki 价格替代——由 coverage 语义可观察。
        return _plan(
            [
                EvidenceSlot(
                    role=ROLE_STORE_OFFICIAL,
                    required=True,
                    citation_requirement=CITATION_CITABLE_REQUIRED,
                ),
                _support,
            ]
        )

    if category == "product":
        if evidence_intent == EVIDENCE_INTENT_RECOMMENDATION:
            # B:方案/选型指南为目标证据,规格证据支撑;#31:案例证据
            # (第一方落地案例)作为可选背景槽参与覆盖 —— 方案推荐应综合
            # Product/Solution/Case/Wiki 证据类,案例缺失由 coverage 诚实呈现
            return _plan(
                [
                    EvidenceSlot(
                        role=ROLE_SOLUTION_GUIDE,
                        required=True,
                        citation_requirement=CITATION_CITABLE_REQUIRED,
                    ),
                    _support,
                    EvidenceSlot(
                        role=ROLE_CASE_EVIDENCE,
                        required=False,
                        citation_requirement=CITATION_BACKGROUND_ALLOWED,
                    ),
                ]
            )
        # A:普通产品事实查询
        return _plan([_spec(True)])

    # 未知/畸形 category:fail-open 单 required 规格槽(检索可用性保持)
    return _plan([_spec(True)])
