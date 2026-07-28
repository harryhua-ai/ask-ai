"""pytest 全局 fixtures。"""

import os
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import load_settings
from backend.db.models import Base
from backend.db.session import get_engine, get_session_factory, init_db


@pytest.fixture
def config_dir() -> Path:
    """返回项目 config 目录路径。"""
    return Path(__file__).parent.parent / "config"


@pytest.fixture
async def db_engine():
    """创建测试用异步 Postgres 引擎并初始化表结构。

    依赖环境变量配置 Postgres 连接(参见 .env.example)。
    测试完成后清理所有表并销毁引擎,保证测试隔离。需要 Postgres 实例运行。

    环境变量:
        TEST_DATABASE_URL: 覆盖默认 DSN(便于 CI 注入测试数据库)。

    Yields:
        AsyncEngine: 已初始化表结构的异步引擎。
    """
    dsn = os.environ.get(
        "TEST_DATABASE_URL",
        load_settings(config_dir=Path(__file__).parent.parent / "config").postgres_dsn,
    )
    engine = get_engine(dsn)
    try:
        await init_db(engine)
        yield engine
    finally:
        # 测试结束后清理所有表,避免跨测试数据污染
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest.fixture
async def db_session(db_engine) -> AsyncSession:
    """基于 db_engine 提供一个异步会话,测试结束后关闭。

    Args:
        db_engine: 已初始化表结构的异步引擎。

    Yields:
        AsyncSession: ``expire_on_commit=False`` 的异步会话。
    """
    factory = get_session_factory(db_engine)
    async with factory() as session:
        yield session
