"""社交对话确定性识别(寒暄 / 致谢 / 身份 / 能力 / 告别)。

产品语义(OFFTOPIC Contract):社交对话与 off-topic 必须区分——
「你好 / hello / 谢谢 / thanks / 你是谁 / 你能做什么」这类轻量社交
交互要自然回应(并在适当时候介绍 CamThink Assistant 能力),不能
机械拒答;真正的领域外请求仍走 off_topic 边界,不进 RAG。

设计约束:
- 确定性整串匹配(锚定 ^$),只命中纯社交输入;带任何实质内容的
  输入(如「你好,NE301 支持热成像吗」)一律不命中,交给意图分类,
  保证产品问题零误吞(OFFTOPIC-G006)。
- 不调 LLM:命中即在 RAG 编排器内短路,省一次意图分类调用。
- 不把任何输入交给 unrestricted LLM:回复全部来自本模块固定模板。
"""

import re
from dataclasses import dataclass
from enum import Enum


class SocialKind(str, Enum):
    """社交输入类别(供 trace / 统计使用)。"""

    GREETING = "greeting"
    THANKS = "thanks"
    IDENTITY = "identity"
    CAPABILITY = "capability"
    GOODBYE = "goodbye"


# 回复模板:产品语义示例,非硬编码话术冻结(产品窗口可随时润色)。
_ZH_REPLIES: dict[SocialKind, str] = {
    SocialKind.GREETING: (
        "你好!我是 CamThink 助手,可以帮你了解 CamThink 的产品选型、"
        "功能参数、解决方案和使用配置。有什么想了解的?"
    ),
    SocialKind.THANKS: ("不客气!如果还有 CamThink 产品相关的问题,随时问我。"),
    SocialKind.IDENTITY: (
        "我是 CamThink 助手,专注于解答 CamThink 产品相关的问题,"
        "包括产品选型、功能参数、解决方案、使用配置和技术支持。"
    ),
    SocialKind.CAPABILITY: (
        "我可以帮你解决 CamThink 相关的问题,包括产品选型、产品功能、"
        "解决方案、使用配置和技术支持。比如可以问我「NE301 支持热成像"
        "入侵检测吗」或「建筑工地太阳能场景怎么选型」。"
    ),
    SocialKind.GOODBYE: ("再见!有 CamThink 相关问题欢迎随时回来。"),
}

_EN_REPLIES: dict[SocialKind, str] = {
    SocialKind.GREETING: (
        "Hello! I'm the CamThink Assistant. I can help you with CamThink "
        "product selection, features, solutions, and configuration. "
        "What would you like to know?"
    ),
    SocialKind.THANKS: (
        "You're welcome! Feel free to ask if you have any other " "CamThink questions."
    ),
    SocialKind.IDENTITY: (
        "I'm the CamThink Assistant. I focus on CamThink topics — product "
        "selection, features, solutions, configuration, and technical "
        "support."
    ),
    SocialKind.CAPABILITY: (
        "I can help you with CamThink topics, including product selection, "
        "features, solutions, configuration, and technical support. For "
        'example, ask me "Does the NE301 support thermal intrusion '
        'detection?" or "Which product fits a solar-powered construction '
        'site?"'
    ),
    SocialKind.GOODBYE: ("Goodbye! Come back anytime with CamThink questions."),
}

_REPLIES: dict[str, dict[SocialKind, str]] = {"zh": _ZH_REPLIES, "en": _EN_REPLIES}

# 尾部允许的标点/语气符号(整串锚定匹配的一部分)
_ZH_TAIL = r"[!！?？。,，~～\s]*"
_EN_TAIL = r"[!?.~\s]*"

# (kind, language, pattern);先匹配者优先。整串锚定,纯社交输入才命中。
_PATTERNS: tuple[tuple[SocialKind, str, re.Pattern[str]], ...] = (
    # 问候
    (
        SocialKind.GREETING,
        "zh",
        re.compile(rf"^(你好呀|你好|您好呀|您好|嗨|哈喽|哈罗|在吗){_ZH_TAIL}$"),
    ),
    (
        SocialKind.GREETING,
        "en",
        re.compile(
            rf"^(hello( there)?|hi( there)?|hey|good (morning|afternoon|evening)){_EN_TAIL}$",
            re.IGNORECASE,
        ),
    ),
    # 致谢
    (
        SocialKind.THANKS,
        "zh",
        re.compile(rf"^(谢谢(你|啦)?|多谢(啦)?|感谢(你)?|辛苦了){_ZH_TAIL}$"),
    ),
    (
        SocialKind.THANKS,
        "en",
        re.compile(rf"^(thanks|thank you( very much)?|thx|many thanks){_EN_TAIL}$", re.IGNORECASE),
    ),
    # 身份
    (
        SocialKind.IDENTITY,
        "zh",
        re.compile(rf"^(你是谁|你是做什么的|你是干什么的|你叫什么名字?|介绍一下你自己){_ZH_TAIL}$"),
    ),
    (
        SocialKind.IDENTITY,
        "en",
        re.compile(
            rf"^(who are you|what are you|tell me about yourself){_EN_TAIL}$", re.IGNORECASE
        ),
    ),
    # 能力
    (
        SocialKind.CAPABILITY,
        "zh",
        re.compile(
            rf"^(你能做什么|你能干什么|你会什么|你能帮我做什么|你能帮我什么|"
            rf"你有什么功能|你能提供什么帮助|你能提供什么服务|有什么能帮到我){_ZH_TAIL}$"
        ),
    ),
    (
        SocialKind.CAPABILITY,
        "en",
        re.compile(
            rf"^(what can you do|what can you help( me)? with|how can you help( me)?){_EN_TAIL}$",
            re.IGNORECASE,
        ),
    ),
    # 告别
    (SocialKind.GOODBYE, "zh", re.compile(rf"^(再见|拜拜(啦)?|下次见){_ZH_TAIL}$")),
    (
        SocialKind.GOODBYE,
        "en",
        re.compile(rf"^(bye(bye)?|goodbye|see you( later)?){_EN_TAIL}$", re.IGNORECASE),
    ),
)

# 社交输入必然极短;超长输入直接跳过(防御性,锚定匹配本已保证)
_MAX_SOCIAL_LEN = 30


@dataclass(frozen=True)
class SocialReply:
    """社交命中结果:类别 + 语言化回复。"""

    kind: SocialKind
    reply: str
    language: str


def match_social(query: str) -> SocialReply | None:
    """识别纯社交输入并给出自然回复;不命中返回 None(交回意图分类)。

    Args:
        query: 用户原始输入。

    Returns:
        :class:`SocialReply`(kind / reply / language),或 ``None``。
    """
    text = query.strip()
    if not text or len(text) > _MAX_SOCIAL_LEN:
        return None
    for kind, lang, pattern in _PATTERNS:
        if pattern.match(text):
            return SocialReply(kind=kind, reply=_REPLIES[lang][kind], language=lang)
    return None
