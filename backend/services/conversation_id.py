"""Conversation ID 的单一生成与配置真相。"""

from __future__ import annotations

import inspect
import logging
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db.models import ConversationIdPolicy

logger = logging.getLogger(__name__)

POLICY_KEY = "default"
DEFAULT_STRATEGY = "uuid4"
SUPPORTED_STRATEGIES = ("uuid4", "uuid7")


@dataclass(frozen=True)
class ConversationIdPolicyView:
    strategy: str
    label: str
    description: str
    example: str
    updated_at: datetime | None


def validate_strategy(strategy: str) -> str:
    value = str(strategy or "").strip().lower()
    if value not in SUPPORTED_STRATEGIES:
        raise ValueError("Conversation ID 生成规则仅支持 uuid4 或 uuid7")
    return value


def _uuid7() -> uuid.UUID:
    """生成 RFC 9562 UUIDv7,兼容 Python 3.12+。"""
    timestamp_ms = int(time.time() * 1000)
    if timestamp_ms >= 2**48:
        raise RuntimeError("UUIDv7 时间戳超出可表示范围")
    random_a = secrets.randbits(12)
    random_b = secrets.randbits(62)
    value = (
        (timestamp_ms << 80)
        | (0x7 << 76)
        | (random_a << 64)
        | (0b10 << 62)
        | random_b
    )
    return uuid.UUID(int=value)


def generate_conversation_id(strategy: str = DEFAULT_STRATEGY) -> uuid.UUID:
    """按已校验策略生成一个新的 UUID 主键。"""
    value = validate_strategy(strategy)
    if value == "uuid4":
        return uuid.uuid4()
    return _uuid7()


def strategy_label(strategy: str) -> str:
    return "随机 UUID(v4)" if strategy == "uuid4" else "时间有序 UUID(v7)"


def strategy_description(strategy: str) -> str:
    if strategy == "uuid4":
        return "使用随机 UUID 生成新对话 ID,保持当前默认兼容语义。"
    return "使用时间有序 UUID 生成新对话 ID,仍保持 UUID 主键与唯一性。"


def policy_view(strategy: str, updated_at: datetime | None = None) -> ConversationIdPolicyView:
    value = validate_strategy(strategy)
    return ConversationIdPolicyView(
        strategy=value,
        label=strategy_label(value),
        description=strategy_description(value),
        example=str(generate_conversation_id(value)),
        updated_at=updated_at,
    )


async def load_strategy(session: AsyncSession) -> str:
    result = await session.execute(
        select(ConversationIdPolicy).where(ConversationIdPolicy.key == POLICY_KEY)
    )
    row = result.scalar_one_or_none()
    # 兼容极简测试替身将结果方法定义为 async;真实 SQLAlchemy Result 为同步方法。
    if inspect.isawaitable(row):
        row = await row
    if row is None:
        return DEFAULT_STRATEGY
    try:
        return validate_strategy(row.strategy)
    except ValueError:
        # 历史/人工异常配置不应让新对话获得不稳定身份;安全回退到原有 uuid4,
        # 同时 API 写入侧不允许继续保存非法值。
        return DEFAULT_STRATEGY


async def new_conversation_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> uuid.UUID:
    try:
        async with session_factory() as session:
            strategy = await load_strategy(session)
    except Exception:
        # 保持旧 uuid4 行为作为最小故障面;后续 Conversation 持久化仍决定
        # 是否允许把该 ID 对外下发,不会把数据库不可用伪装成成功。
        logger.warning("Conversation ID 策略读取失败,回退 uuid4", exc_info=True)
        strategy = DEFAULT_STRATEGY
    return generate_conversation_id(strategy)


async def get_policy(
    session_factory: async_sessionmaker[AsyncSession],
) -> ConversationIdPolicyView:
    async with session_factory() as session:
        row = (
            await session.execute(
                select(ConversationIdPolicy).where(ConversationIdPolicy.key == POLICY_KEY)
            )
        ).scalar_one_or_none()
        if row is None:
            return policy_view(DEFAULT_STRATEGY)
        try:
            strategy = validate_strategy(row.strategy)
        except ValueError:
            strategy = DEFAULT_STRATEGY
        return policy_view(strategy, row.updated_at)


async def save_policy(
    session_factory: async_sessionmaker[AsyncSession], strategy: str
) -> ConversationIdPolicyView:
    value = validate_strategy(strategy)
    async with session_factory() as session:
        row = (
            await session.execute(
                select(ConversationIdPolicy).where(ConversationIdPolicy.key == POLICY_KEY)
            )
        ).scalar_one_or_none()
        if row is None:
            row = ConversationIdPolicy(key=POLICY_KEY, strategy=value)
            session.add(row)
        else:
            row.strategy = value
        await session.commit()
        await session.refresh(row)
        return policy_view(value, row.updated_at)
