"""INC-7 自然响应层( Natural Response Layer)。

把**已完成的**任务理解与证据真值(INC-3/4/5 冻结输出)确定为恰当的自然
响应策略,在既有唯一 generation 调用之前编译进消息构造(NEW_LLM_CALLS = 0)。

冻结契约(docs/engineering/discovery/I002-INC7-CONTRACT-CLOSURE.md +
I002-INC7 冻结实现合同):

- **职责边界**:ResponseStrategy 只拥有「任务/证据真值 → 响应行为」的决策
  (帧/深度/覆盖诚实帧);Generation 拥有「响应行为 → 自然语言实现」。
  不拥有任务分类、检索、证据选择、覆盖真值(只读)、主张校验(INC-6)、
  引用强制、语言权威、散文模板;不引入第二真值源。
- **四字段值对象**(恰好四个语义字段,不新增投机字段):
  response_frame / directness / coverage_framing / gap_labels。
  引用期望**不是**本层字段——既有 [N] 契约与 INC-6 校验保持唯一权威。
- **部分证据不变量**(PARTIAL EVIDENCE POLICY):``partial_supported`` 只能
  来自 CoverageReport 真值;覆盖不完整绝不构成拒答理由;无证据权威保留在
  既有拒答门(先于本层,永不达策略推导点);绝不虚构缺失证据。
- **所有权抑制**:比较路径(Issue #19 契约)与零检索交互模式(澄清/能力
  导向/无关)推导返回 None——编译回落今日行为;lead 轮由编译侧让位。
- **fail-open**:推导对任意畸形输入返回 None(= 今日行为,逐字节),绝不
  抛错;编译对畸形策略返回空串;策略故障绝不转化为请求失败/误拒/伪造。
- **多轮承接**:编译级确定性规则(有对话历史 ⇒ 追加承接指令),不新增
  记忆状态/摘要/解析器/LLM 调用。
"""

import logging
from dataclasses import dataclass

from backend.pipeline.intent import VALID_CATEGORIES  # noqa: E402 枚举唯一权威定义点
from backend.pipeline.product_resolver import MODE_COMPARISON
from backend.pipeline.task_understanding import (
    EVIDENCE_INTENT_RECOMMENDATION,
    MODE_STANDARD,
)

logger = logging.getLogger(__name__)

# 冻结枚举(v1 语义空间;缺口=未来 PD,不预置)
FRAME_FACTUAL_LOOKUP = "factual_lookup"
FRAME_RECOMMENDATION = "recommendation"
FRAME_TROUBLESHOOTING = "troubleshooting"
FRAME_COMMERCIAL = "commercial"

DIRECTNESS_CONCISE = "concise_direct"
DIRECTNESS_GUIDED = "guided_expansion"

FRAMING_NONE = "none"
FRAMING_PARTIAL_SUPPORTED = "partial_supported"

# category → (frame, directness);product 的 evidence_intent 分叉单列。
# 非比较 standard 路径到达此表前已由守卫过滤(未知/短路模式 ⇒ None)。
_FRAME_BY_CATEGORY = {
    "support": (FRAME_TROUBLESHOOTING, DIRECTNESS_GUIDED),
    "commercial": (FRAME_COMMERCIAL, DIRECTNESS_CONCISE),
}


@dataclass(frozen=True)
class ResponseStrategy:
    """确定性响应策略(四语义字段;只决定行为,不产生散文)。

    Attributes:
        response_frame: 实现帧(factual_lookup / recommendation /
            troubleshooting / commercial)。
        directness: 实现深度方向(concise_direct / guided_expansion)。
        coverage_framing: 覆盖诚实帧(none / partial_supported);
            partial_supported 只来自 CoverageReport 真值。
        gap_labels: 缺失的 required 槽标签(CoverageReport.missing_required
            原样透传,不重算不改写)。
    """

    response_frame: str = FRAME_FACTUAL_LOOKUP
    directness: str = DIRECTNESS_CONCISE
    coverage_framing: str = FRAMING_NONE
    gap_labels: tuple[str, ...] = ()


def derive_response_strategy(
    understanding,
    resolution,
    plan,
    coverage_report,
):
    """确定性推导响应策略(纯函数,全 total,零 IO/零 LLM)。

    Args:
        understanding: INC-3 TaskUnderstanding(category/interaction_mode)。
        resolution: ProductResolution(产品身份唯一权威;仅读 mode)。
        plan: INC-4 EvidencePlan(evidence_intent 为归一化权威副本)。
        coverage_report: INC-5 CoverageReport(证据真值唯一权威,只读;
            None = 计划无槽位)。

    Returns:
        :class:`ResponseStrategy`;或 None(= 维持今日已接受行为的回退哨兵):
        畸形输入 / 零检索交互模式(短路所有权)/ 比较模式(Issue #19 契约
        独占)/ 未知 category。任何异常一律吞掉并返回 None——策略故障绝不
        成为请求失败。
    """
    try:
        mode = getattr(understanding, "interaction_mode", None)
        if mode != MODE_STANDARD:
            # 零检索模式属冻结短路所有权(正常流不可达,防御性回退)
            return None
        res_mode = getattr(resolution, "mode", None)
        if res_mode == MODE_COMPARISON:
            # Issue #19 比较证据契约独占比较轮诚实语义;通用策略不叠加
            return None
        category = getattr(understanding, "category", None)
        if category not in VALID_CATEGORIES:
            # 未知 category:今日行为 = 无 intent 风格段 ⇒ 回退 None
            return None
        evidence_intent = getattr(plan, "evidence_intent", None)
        if evidence_intent not in ("factual", "recommendation"):
            return None
        if category == "off_topic":
            # 真 off_topic 由冻结模板短路;防御性回退
            return None
        if category == "product":
            if evidence_intent == EVIDENCE_INTENT_RECOMMENDATION:
                frame, directness = FRAME_RECOMMENDATION, DIRECTNESS_GUIDED
            else:
                frame, directness = FRAME_FACTUAL_LOOKUP, DIRECTNESS_CONCISE
        else:
            frame, directness = _FRAME_BY_CATEGORY[category]

        framing = FRAMING_NONE
        gaps: tuple[str, ...] = ()
        if coverage_report is not None and not getattr(coverage_report, "coverage_complete", True):
            framing = FRAMING_PARTIAL_SUPPORTED
            gaps = tuple(getattr(coverage_report, "missing_required", ()) or ())
        return ResponseStrategy(
            response_frame=frame,
            directness=directness,
            coverage_framing=framing,
            gap_labels=gaps,
        )
    except Exception:  # noqa: BLE001 — fail-open:策略推导绝不致请求失败
        logger.debug("response strategy derivation failed; fail-open to None", exc_info=True)
        return None


# 编译指令文本(固定确定性文案;真值行/引用契约/语言行不在本层——
# 它们由既有 user 骨架与 _build_messages 原样持有)
_FRAME_DIRECTIVES = {
    (FRAME_FACTUAL_LOOKUP, DIRECTNESS_CONCISE): (
        "## 回答风格(产品事实)\n"
        "- 直答问题:先给结论,再给必要的支撑细节,保持简洁\n"
        "- 参数/规格精确引用,不做无关展开"
    ),
    (FRAME_RECOMMENDATION, DIRECTNESS_GUIDED): (
        "## 回答风格(选型/方案)\n"
        "- 围绕用户需求给出推荐与理由,可给出组合或配置建议\n"
        "- 每个推荐结论都必须有检索资料支撑并标注来源编号\n"
        "- 用户约束不足时,按资料中各产品的适配性给出建议并说明依据"
    ),
    (FRAME_TROUBLESHOOTING, DIRECTNESS_GUIDED): (
        "## 回答风格(技术支持)\n"
        "- 保留代码/寄存器/接口/错误码等原始细节\n"
        "- 故障排查给出可执行的排查步骤与定位链路\n"
        "- 每个判断都必须落在检索资料上,不做无据猜测"
    ),
    (FRAME_COMMERCIAL, DIRECTNESS_CONCISE): (
        "## 回答风格(商务)\n" "- 聚焦价格/采购/渠道/库存,保持简洁,引导联系销售\n" "- 不展开技术细节"
    ),
}

_PARTIAL_DIRECTIVE = (
    "## 证据缺口说明\n"
    "- 本次检索到的资料未覆盖回答所需的全部证据类型(缺失:{gaps})\n"
    "- 只回答已有资料支撑的部分,并如实说明尚缺的部分;"
    "不要用无关内容填补,不要暗示问题已完整解决"
)

_CONTINUATION_DIRECTIVE = (
    "- 这是多轮对话的后续追问:承接上文已确认的信息直接作答," "不要复述上文已给出的内容"
)


def compile_strategy_instructions(strategy, *, has_history: bool) -> str:
    """把策略编译为 system 风格段指令文本(纯函数,固定确定性文案)。

    Args:
        strategy: :class:`ResponseStrategy`(或畸形对象 → 空串安全回退)。
        has_history: 本轮是否有对话历史(多轮承接编译规则)。

    Returns:
        指令文本;畸形/异常 ⇒ 空串(调用方回落今日 intent_styles 路径)。
    """
    try:
        directive = _FRAME_DIRECTIVES.get(
            (strategy.response_frame, strategy.directness)  # type: ignore[attr-defined]
        )
        if directive is None:
            # 畸形帧/深度组合(不可能由 derive 产出)⇒ 安全空段
            return ""
        parts = [directive]
        if strategy.coverage_framing == FRAMING_PARTIAL_SUPPORTED:  # type: ignore[attr-defined]
            gaps = ", ".join(dict.fromkeys(strategy.gap_labels)) or "所需证据"  # type: ignore[attr-defined]
            parts.append(_PARTIAL_DIRECTIVE.format(gaps=gaps))
        if has_history:
            parts.append(_CONTINUATION_DIRECTIVE)
        return "\n".join(parts)
    except Exception:  # noqa: BLE001 — 编译级 fail-open
        logger.debug("response strategy compile failed; fail-open to empty", exc_info=True)
        return ""


def build_response_strategy_stage(strategy) -> dict:
    """有界 trace 阶段(稳定枚举 + 标签列表;零证据正文/零生成文本)。"""
    return {
        "response_frame": strategy.response_frame,
        "directness": strategy.directness,
        "coverage_framing": strategy.coverage_framing,
        "gap_labels": list(strategy.gap_labels),
    }
