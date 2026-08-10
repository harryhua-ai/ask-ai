"""业务信号提取调度入口。

手动触发:
    python -c "import asyncio; from backend.pipeline.business_signals_runner import run; asyncio.run(run('7d'))"
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db.models import BusinessSignal, Conversation
from backend.pipeline.business_signals import extract_business_signals

logger = logging.getLogger(__name__)


async def run(
    period: str,
    session_factory: async_sessionmaker[AsyncSession],
    llm: object,
) -> int:
    """执行业务信号提取 pipeline。

    Args:
        period: 周期标识(如 "7d"/"30d")。
        session_factory: 数据库会话工厂。
        llm: LLM provider 实例。

    Returns:
        提取的信号条数。
    """
    days = int(period.rstrip("d")) if period.endswith("d") else 7
    end = datetime.now(UTC)
    start = end - timedelta(days=days)

    async with session_factory() as session:
        rows = await session.execute(
            select(Conversation)
            .where(
                Conversation.created_at >= start,
                Conversation.created_at <= end,
                Conversation.intent_tag.in_(["commercial", "product"]),
            )
            .order_by(Conversation.created_at.desc())
            .limit(500)
        )
        conversations = rows.scalars().all()

    if not conversations:
        logger.info("业务信号提取:无符合条件的对话,跳过")
        return 0

    signals = await extract_business_signals(llm, conversations, period_days=days)

    # 覆盖同 period 旧记录(先删后插)
    async with session_factory() as session:
        await session.execute(
            BusinessSignal.__table__.delete().where(
                BusinessSignal.period_start >= start,
                BusinessSignal.period_end <= end,
            )
        )
        for sig in signals:
            session.add(
                BusinessSignal(
                    type=sig["type"],
                    label=sig["label"],
                    count=sig["count"],
                    pct=sig["pct"],
                    sample_conversation_ids=sig["sample_conversation_ids"],
                    period_start=start,
                    period_end=end,
                )
            )
        await session.commit()

    logger.info("业务信号提取完成: %d 条信号(%d 条对话)", len(signals), len(conversations))
    return len(signals)
