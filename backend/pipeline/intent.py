"""用户意图识别模块。

在 RAG 管线的检索之前执行,用 LLM 判断用户查询属于以下 4 类意图之一:
- commercial: 价格/采购/报价/渠道/库存/商务合作(过渡期拒答,P1#5 接 WooCommerce 后作答)
- product: CamThink 产品功能/参数/规格/选型/方案/竞品对比/适配/演示能力咨询
- support: 故障排查/报错/集成/二次开发/代码/调试/寄存器/固件(L1-L3,含开发者)
- off_topic: 与 CamThink 产品无关的闲聊/天气/通用知识/纯竞品咨询

分类失败时 fail-open 为 product(最常见、最安全),不阻塞主管线。
"""

import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

VALID_CATEGORIES = ("commercial", "product", "support", "off_topic")

_INTENT_PROMPT = """你是 CamThink 意图分类助手。判断用户输入属于以下哪类:

- commercial: 纯价格/采购/报价/渠道/库存/促销/商务合作(不涉及技术方案)
- product: CamThink 产品功能/参数/规格/选型/方案/竞品对比/适配/演示能力咨询
  (含"能否做 XX""XX 场景怎么选""有没有 XX 能力/视频"等方案选型问题)
- support: 故障排查/报错/集成/二次开发/代码/调试/寄存器/固件(L1-L3,含开发者)
- off_topic: 与 CamThink 产品无关的闲聊/天气/通用知识/纯竞品咨询

## 示例
- "NE301 多少钱 / 怎么采购" → commercial
- "NE301 支持热成像入侵检测吗 / 有演示视频吗" → product
- "建筑工地太阳能场景怎么选型" → product
- "NE101 蜂窝网络注册失败 / CEREG 报错" → support
- "Python 怎么读串口(与 CamThink 无关)" → off_topic

只输出 JSON: {{"category": "类别名", "reason": "简短理由"}}

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
        意图分类结果。LLM 异常或返回畸形数据时 fail-open 返回 product。
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
        category = data.get("category", "product")
        if category not in VALID_CATEGORIES:
            category = "product"
        reason = data.get("reason", "")
        logger.info("意图识别: %r → %s (%s)", query[:100], category, reason)
        return IntentResult(category=category, reason=reason)
    except Exception:  # noqa: BLE001
        logger.warning("意图识别失败,fail-open 为 product", exc_info=True)
        return IntentResult(category="product", reason="classification failed")
