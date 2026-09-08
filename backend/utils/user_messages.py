"""用户可见消息本地化(阶段⑯ 生成失败/本地化闭环)。

最小方案(Discovery §9 定案,不引入 i18n framework):
- 冻结产品文案(不自行改写):service_unavailable / budget_declined / no_evidence;
- zh → 中文文案;其余语言(zh 之外的 en/ja/ko/fr/…)统一回落英文,
  与 ``_off_topic_reply`` / UI_LANGUAGE(非 zh 即 en)既有语义一致;
- 纯函数、无 I/O、无资源文件加载。
"""

from __future__ import annotations

# 冻结消息键(SSE error/declined 事件的 ``message_key`` 结构化身份)
SERVICE_UNAVAILABLE_KEY = "service_unavailable"
BUDGET_DECLINED_KEY = "budget_declined"
NO_EVIDENCE_KEY = "no_evidence"
# 产品边界结构化键(Issue #5 契约 §8;SSE complete 事件 result_key 同值)
PRODUCT_AMBIGUOUS_KEY = "product_ambiguous"
PRODUCT_EVIDENCE_INSUFFICIENT_KEY = "product_evidence_insufficient"
PRODUCT_NOT_SUPPORTED_KEY = "product_not_supported"
# Issue #19(Evidence Contract):比较模式下单侧/双侧目标证据缺失的专属键;
# 与 product_evidence_insufficient 的区别:按 target 明示缺侧,语义为
# 「无法完成完整对比」而非「单产品无资料」。
COMPARISON_EVIDENCE_INSUFFICIENT_KEY = "comparison_evidence_insufficient"
# INC-3 交互模式路由(#26/#27):澄清与能力导向是合法交互结果,
# 结构化 result_key 与 off_topic 拒答严格区分(Admin/trace 真相)。
CLARIFICATION_REQUIRED_KEY = "clarification_required"
CAPABILITY_ORIENTATION_KEY = "capability_orientation"

MESSAGE_KEYS = frozenset(
    {
        SERVICE_UNAVAILABLE_KEY,
        BUDGET_DECLINED_KEY,
        NO_EVIDENCE_KEY,
        PRODUCT_AMBIGUOUS_KEY,
        PRODUCT_EVIDENCE_INSUFFICIENT_KEY,
        PRODUCT_NOT_SUPPORTED_KEY,
        COMPARISON_EVIDENCE_INSUFFICIENT_KEY,
        CLARIFICATION_REQUIRED_KEY,
        CAPABILITY_ORIENTATION_KEY,
    }
)

# 冻结文案(Product Contract,逐字;zh 与既有用户可见行为一致)
_MESSAGES: dict[str, dict[str, str]] = {
    SERVICE_UNAVAILABLE_KEY: {
        "zh": "服务暂时不可用,请稍后再试。",
        "en": "The service is temporarily unavailable. Please try again later.",
    },
    BUDGET_DECLINED_KEY: {
        "zh": "服务繁忙,请稍后再试。",
        "en": "The service is busy right now. Please try again shortly.",
    },
    NO_EVIDENCE_KEY: {
        "zh": "暂未在官方资料中找到相关信息。",
        "en": "I couldn't find relevant information in the official sources.",
    },
    # 产品边界(Issue #5 契约 §8):{product} 为目标产品展示名,调用方 fill
    PRODUCT_AMBIGUOUS_KEY: {
        "zh": "请告诉我要了解的具体产品型号(如 NE301、NE503),我再为您查询。",
        "en": "Could you tell me which product model you're asking about (e.g. NE301, NE503)?",
    },
    PRODUCT_EVIDENCE_INSUFFICIENT_KEY: {
        "zh": "官方资料中暂未找到 {product} 的相关说明,建议联系技术支持获取帮助。",
        "en": "I couldn't find relevant information about {product} in the official "
        "sources. Please contact technical support for further help.",
    },
    PRODUCT_NOT_SUPPORTED_KEY: {
        "zh": "您询问的产品暂不在支持范围内,请尝试询问 CamThink 产品相关问题。",
        "en": "The product you asked about is not in my supported scope. "
        "Please ask about CamThink products.",
    },
    # Issue #19(Evidence Contract):{products}=本轮全部目标展示名,
    # {missing}=缺官方资料侧展示名;明示哪侧缺、哪侧已有支持,不建议重试。
    COMPARISON_EVIDENCE_INSUFFICIENT_KEY: {
        "zh": "官方资料中暂未找到 {missing} 的相关说明,暂时无法完成 {products} "
        "的完整对比;已就其余产品提供现有资料。",
        "en": "I couldn't find official information about {missing}, so I can't "
        "complete a full comparison of {products} yet. Information is available "
        "for the other product(s).",
    },
    # INC-3(#26):plausibly in-domain 但缺关键信息 → 澄清(只问最少必要信息,
    # 不猜产品、不以拒答开场)
    CLARIFICATION_REQUIRED_KEY: {
        "zh": "这个问题我可以帮你解答。为了更准确地定位,请告诉我具体的产品型号或使用场景。",
        "en": "I can help with that. To point you to the right answer, "
        "could you tell me which product or scenario this is about?",
    },
    # INC-3(#27):能力/导向 → welcome → orient(如实、通用平台措辞)→ invite;
    # 不硬编码特定厂商身份,不虚构能力
    CAPABILITY_ORIENTATION_KEY: {
        "zh": "你好!我可以协助你解决产品相关的问题,包括:产品选型与功能参数咨询、"
        "价格与采购信息、技术支持与二次开发等。请直接告诉我你想了解的内容,我会尽力帮忙。",
        "en": "Hi! I can help with product-related questions, including product "
        "selection and features, pricing and purchasing information, and technical "
        "support or integration. Just tell me what you'd like to know and I'll do my best.",
    },
}


def localized_message(key: str, language: str, **kwargs: str) -> str:
    """按解析语言取冻结文案。

    Args:
        key: MESSAGE_KEYS 之一(未知键 fail-safe 回落 service_unavailable)。
        language: ``resolve_answer_language`` 的解析值(zh-cn/zh/en/ja/…);
            zh 族 → 中文,其余 → 英文。
        **kwargs: 文案占位符填充(如 ``product="NeoEye NE503"``);
            文案无占位符时忽略。

    Returns:
        str: 本地化后的用户可见文案。
    """
    table = _MESSAGES.get(key, _MESSAGES[SERVICE_UNAVAILABLE_KEY])
    text = table["zh"] if language.startswith("zh") else table["en"]
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text
