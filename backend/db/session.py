"""异步数据库引擎与会话工厂。

提供:
- get_engine: 创建异步 SQLAlchemy 引擎
- get_session_factory: 创建异步会话工厂
- get_sync_session_factory: 创建同步会话工厂(灌入管道写 documents 表用)
- init_db: 基于模型元数据初始化表结构
"""

from sqlalchemy import create_engine as _create_sync_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

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


def get_sync_session_factory(engine_or_dsn: "AsyncEngine | str") -> sessionmaker[Session]:
    """从 AsyncEngine 或 DSN 创建同步 sessionmaker。

    灌入管道(``IngestionPipeline._upsert_postgres``)使用同步 SQLAlchemy
    sessionmaker 写 ``documents`` 表(Weaviate-client v4 本身也是同步 SDK)。
    本函数接受异步 DSN(``postgresql+asyncpg://``)或 AsyncEngine,自动把 driver
    替换为 ``psycopg2`` 后创建同步引擎。

    DSN 转换:``postgresql+asyncpg://`` → ``postgresql+psycopg2://``。
    若 DSN 已是同步 driver(如 ``postgresql+psycopg2://``、``postgresql://``),
    原样使用。

    Args:
        engine_or_dsn: AsyncEngine 对象(取其 ``url``)或 DSN 字符串。

    Returns:
        sessionmaker[Session]: ``expire_on_commit=False`` 的同步会话工厂。
        调用方负责在进程生命周期内复用,连接池由底层 engine 管理。
    """
    if hasattr(engine_or_dsn, "url"):
        dsn = str(engine_or_dsn.url)
    else:
        dsn = str(engine_or_dsn)
    sync_dsn = dsn.replace("+asyncpg", "+psycopg2")
    sync_engine = _create_sync_engine(sync_dsn, pool_pre_ping=True)
    return sessionmaker(sync_engine, expire_on_commit=False)


async def init_db(engine: AsyncEngine) -> None:
    """根据模型元数据创建所有表。

    主要用于开发/测试环境;生产环境应使用 Alembic 迁移。

    Args:
        engine: 已配置好的异步引擎。
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
