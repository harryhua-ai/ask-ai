"""用户意图识别模块。

在 RAG 管线的检索之前执行,用 LLM 判断用户查询属于哪类意图:
- product_question: CamThink 产品技术问题 → 进入 RAG 管线
- business_inquiry: 商务/价格/采购 → 直接拒绝
- off_topic: 无关闲聊/竞品/通用知识 → 直接拒绝

分类失败时 fail-open 为 product_question,不阻塞主管线。
"""

import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

VALID_CATEGORIES = ("product_question", "business_inquiry", "off_topic")

_INTENT_PROMPT = """你是意图分类助手。判断用户输入属于以下哪个类别:

- product_question: CamThink 产品技术问题(NE101/NE301/NE503/NeoMind/AIToolStack 等产品的硬件、固件、SDK、配置、故障排查)
- business_inquiry: 商务合作、价格、采购、销售、渠道相关
- off_topic: 与 CamThink 产品无关的闲聊、竞品咨询、通用知识问题

只输出 JSON,不要输出其他内容。格式: {{"category": "类别名", "reason": "简短理由"}}

## 用户输入

{query}
"""


@dataclass(frozen=True)
class IntentResult:
    """意图识别结果。"""

    category: str
    reason: str


async def classify_intent(query: str, llm: Any) -> IntentResult:
    """用 LLM 分类用户意图。

    Args:
        query: 用户查询文本。
        llm: LLMProvider / LLMRouter 实例。

    Returns:
        意图分类结果。LLM 异常或返回畸形数据时 fail-open 返回 product_question。
    """
    try:
        prompt = _INTENT_PROMPT.format(query=query[:2000])
        response = await llm.generate(
            [{"role": "user", "content": prompt}],
            task="intent",
            max_tokens=128,
            temperature=0.0,
        )
        raw = response.content.strip()
        # 兼容 LLM 可能包裹 markdown code fence 的情况
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        data = json.loads(raw)
        category = data.get("category", "product_question")
        if category not in VALID_CATEGORIES:
            category = "product_question"
        reason = data.get("reason", "")
        logger.info("意图识别: %r → %s (%s)", query[:100], category, reason)
        return IntentResult(category=category, reason=reason)
    except Exception:  # noqa: BLE001
        logger.warning("意图识别失败,fail-open 为 product_question", exc_info=True)
        return IntentResult(category="product_question", reason="classification failed")
