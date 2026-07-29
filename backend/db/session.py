"""异步数据库引擎与会话工厂。

提供:
- get_engine: 创建异步 SQLAlchemy 引擎
- get_session_factory: 创建异步会话工厂
- init_db: 基于模型元数据初始化表结构
"""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.db.models import Base


def get_engine(dsn: str) -> AsyncEngine:
    """根据 DSN 创建异步引擎。

    Args:
        dsn: PostgreSQL 异步 DSN,例如 ``postgresql+asyncpg://user:pwd@host/db``。

    Returns:
        AsyncEngine: 启用了 pool_pre_ping 的异步引擎。
    """
    return create_async_engine(dsn, echo=False, pool_pre_ping=True)


def get_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """根据引擎创建异步会话工厂。

    Args:
        engine: 已配置好的异步引擎。

    Returns:
        async_sessionmaker[AsyncSession]: ``expire_on_commit=False`` 的会话工厂。
    """
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(engine: AsyncEngine) -> None:
    """根据模型元数据创建所有表。

    主要用于开发/测试环境;生产环境应使用 Alembic 迁移。

    Args:
        engine: 已配置好的异步引擎。
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
