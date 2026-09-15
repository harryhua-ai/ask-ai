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


async def ensure_recovery_columns(engine: AsyncEngine) -> None:
    """阶段⑩ 恢复字段幂等迁移:sync_requests 补 attempt_count/failure_kind/next_retry_at。

    init_db(create_all)只建缺失表、不补已有表的新列,故已有部署(stage⑨ 落地过
    sync_requests)需要本迁移。幂等:列已存在时 ADD COLUMN IF NOT EXISTS 为 no-op;
    旧行安全默认(attempt_count=0 / failure_kind=NULL / next_retry_at=NULL)。
    生产执行窗口:任意(纯加列,不改既有数据)。
    """
    from sqlalchemy import text

    statements = (
        "ALTER TABLE sync_requests ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE sync_requests ADD COLUMN IF NOT EXISTS failure_kind VARCHAR(20)",
        "ALTER TABLE sync_requests ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ",
        "ALTER TABLE sync_requests ADD COLUMN IF NOT EXISTS attempt_started_at TIMESTAMPTZ",
    )
    async with engine.begin() as conn:
        for stmt in statements:
            await conn.execute(text(stmt))


async def ensure_sync_request_kind_column(engine: AsyncEngine) -> None:
    """INC-WEB-EMBED-413 REMEDIATION:sync_requests 补 kind 列(幂等加性)。

    NULL = 既有增量同步语义;"rebuild" = 源全量生成重建(执行面透传
    --reindex)。旧行安全默认 NULL,零回填。生产执行窗口:任意(纯加列)。
    """
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(
            text("ALTER TABLE sync_requests ADD COLUMN IF NOT EXISTS kind VARCHAR(20)")
        )


async def ensure_track_c_columns(engine: AsyncEngine) -> None:
    """v1.6.3 Track C 加性列幂等迁移(U-7/U-11/U-12)。

    - documents.content_type(U-7 逐文档内容类型;NULL = 存量行不可用);
    - data_sources.next_run_at(U-11 调度器权威下次执行时间);
    - data_sources.knowledge_role / data_sources.freshness_hours
      (U-12 证据资格政策层 + 新鲜度政策;NULL = 默认 CURRENT / 24h)。

    幂等:列已存在时 ADD COLUMN IF NOT EXISTS 为 no-op;旧行安全默认
    (全 NULL,零回填)。新表(document_repair_tasks / document_recovery_events /
    knowledge_settings_previews)由 init_db create_all 补齐。生产执行窗口:任意。
    """
    from sqlalchemy import text

    statements = (
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_type VARCHAR(30)",
        "ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS next_run_at TIMESTAMPTZ",
        "ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS knowledge_role VARCHAR(20)",
        "ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS freshness_hours INTEGER",
        "CREATE INDEX IF NOT EXISTS ix_documents_content_type ON documents (content_type)",
    )
    async with engine.begin() as conn:
        for stmt in statements:
            await conn.execute(text(stmt))


async def ensure_sync_delta_columns(engine: AsyncEngine) -> None:
    """补齐 #65 SyncLog document-delta 列(加性、幂等、零回填)。

    生产发布仍须先执行 ``scripts/migrate_add_sync_delta_counts.py``；这里
    的启动期守卫只让开发/测试中已经存在的旧表安全加载新读写代码。
    """
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(
            text("ALTER TABLE sync_log ADD COLUMN IF NOT EXISTS delta_counts JSONB")
        )


async def init_db(engine: AsyncEngine) -> None:
    """根据模型元数据创建所有表。

    主要用于开发/测试环境;生产环境应使用 Alembic 迁移。

    v1.6.3 Track C:create_all 只建缺失表、不补已有表新列,故随后幂等补齐
    Track C 加性列(documents.content_type / data_sources.next_run_at /
    knowledge_role / freshness_hours;ADD COLUMN IF NOT EXISTS,零回填)。

    Args:
        engine: 已配置好的异步引擎。
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await ensure_track_c_columns(engine)
    await ensure_sync_delta_columns(engine)
    await ensure_sync_request_kind_column(engine)
