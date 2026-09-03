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

MESSAGE_KEYS = frozenset({SERVICE_UNAVAILABLE_KEY, BUDGET_DECLINED_KEY, NO_EVIDENCE_KEY})

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
}


def localized_message(key: str, language: str) -> str:
    """按解析语言取冻结文案。

    Args:
        key: MESSAGE_KEYS 之一(未知键 fail-safe 回落 service_unavailable)。
        language: ``resolve_answer_language`` 的解析值(zh-cn/zh/en/ja/…);
            zh 族 → 中文,其余 → 英文。

    Returns:
        str: 本地化后的用户可见文案。
    """
    table = _MESSAGES.get(key, _MESSAGES[SERVICE_UNAVAILABLE_KEY])
    return table["zh"] if language.startswith("zh") else table["en"]
