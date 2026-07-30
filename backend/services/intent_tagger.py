"""LLM Intent 自动标注服务。

用现有的 LLM 基础设施对对话问题做意图分类。
"""

import logging
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db.models import Conversation

logger = logging.getLogger(__name__)

INTENT_CATEGORIES = [
    "product_spec",  # 产品规格咨询
    "tech_support",  # 技术支持/故障排查
    "getting_started",  # 入门/快速开始
    "pricing",  # 价格/购买
    "comparison",  # 产品对比
    "api_reference",  # API/SDK 参考
    "documentation",  # 文档查询
    "other",  # 其他
]

INTENT_PROMPT = f"""请分析以下用户问题，从这些意图类别中选择最合适的一个：
{chr(10).join(f"- {c}" for c in INTENT_CATEGORIES)}

只返回类别名称（不解释、不加引号）。

用户问题：{{question}}"""


async def tag_single(
    conversation_id: str,
    question: str,
    llm: Any,
) -> str:
    """对单个问题做意图标注。

    Args:
        conversation_id: 对话 ID（用于日志）。
        question: 用户问题文本。
        llm: LLMProvider 或 LLMRouter 实例。

    Returns:
        意图标签字符串。
    """
    messages = [
        {"role": "system", "content": "你是一个意图分类器，只输出类别名称。"},
        {"role": "user", "content": INTENT_PROMPT.format(question=question)},
    ]
    try:
        resp = await llm.generate(
            messages, task="query_decomposition", max_tokens=20, temperature=0.0
        )
        tag = resp.content.strip().lower().replace(" ", "_")
        if tag not in INTENT_CATEGORIES:
            tag = "other"
        return tag
    except Exception:
        logger.exception("Intent 标注失败 conversation_id=%s", conversation_id)
        return "other"


async def tag_batch(
    factory: async_sessionmaker[AsyncSession],
    llm: Any,
    batch_size: int = 50,
) -> int:
    """批量标注未标注的对话。

    Args:
        factory: 异步会话工厂。
        llm: LLM 实例。
        batch_size: 每批处理数量。

    Returns:
        成功标注的对话数。
    """
    async with factory() as session:
        result = await session.execute(
            select(Conversation).where(Conversation.intent_tag.is_(None)).limit(batch_size)
        )
        untagged = result.scalars().all()

    count = 0
    for conv in untagged:
        tag = await tag_single(str(conv.id), conv.question, llm)
        async with factory() as session:
            await session.execute(
                update(Conversation).where(Conversation.id == conv.id).values(intent_tag=tag)
            )
            await session.commit()
        count += 1
    logger.info("批量标注完成：%d 条对话", count)
    return count
