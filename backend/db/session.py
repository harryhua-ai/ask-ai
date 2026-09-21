"""异步数据库引擎与会话工厂。

提供:
- get_engine: 创建异步 SQLAlchemy 引擎
- get_session_factory: 创建异步会话工厂
- get_sync_session_factory: 创建同步会话工厂(灌入管道写 documents 表用)
- init_db: 基于模型元数据初始化表结构
"""

from typing import Any

from sqlalchemy import create_engine as _create_sync_engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import text

from backend.db.models import Base

# Issue #102:真缺列时的兼容性 DDL 锁等待上限 —— 与长事务重叠时有界失败
# (55P03 → 可执行错误),绝不无限排队(生产实证:56min+ 三方停摆)。
_DDL_LOCK_TIMEOUT = "5s"


def _is_lock_unavailable(exc: BaseException) -> bool:
    orig = getattr(exc, "orig", None)
    return str(getattr(orig, "sqlstate", "") or getattr(orig, "pgcode", "")) == "55P03"


async def _table_column_exists(conn: Any, table: str, column: str) -> bool:
    """catalog 存在性探测:不申请目标表锁,绝不排队于任何长事务之后(#102 AC3)。"""
    row = await conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    )
    return row.first() is not None


async def _index_exists(conn: Any, table: str, index: str) -> bool:
    row = await conn.execute(
        text(
            "SELECT 1 FROM pg_indexes "
            "WHERE schemaname = current_schema() AND tablename = :t AND indexname = :i"
        ),
        {"t": table, "i": index},
    )
    return row.first() is not None


async def _execute_compat_ddl(conn: Any, statements: tuple[str, ...], *, label: str) -> None:
    """在有界 lock_timeout 下执行真实兼容性 DDL;锁竞争 ⇒ 可执行失败(绝不静默)。"""
    await conn.execute(text(f"SET LOCAL lock_timeout = '{_DDL_LOCK_TIMEOUT}'"))
    try:
        for stmt in statements:
            await conn.execute(text(stmt))
    except DBAPIError as exc:
        if _is_lock_unavailable(exc):
            raise RuntimeError(
                f"#102: schema compatibility DDL could not acquire locks within "
                f"{_DDL_LOCK_TIMEOUT} ({label}); a concurrent long transaction holds the "
                f"table. Bounded failure — the migration retries on the next init round."
            ) from exc
        raise


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

    Issue #102:列已存在 ⇒ 零 DDL(catalog 探测,稳态无阻塞语句);
    真缺列 ⇒ 有界 lock_timeout 下执行,锁竞争时可执行失败。
    """
    async with engine.begin() as conn:
        if await _table_column_exists(conn, "sync_requests", "kind"):
            return
        await _execute_compat_ddl(
            conn,
            ("ALTER TABLE sync_requests ADD COLUMN IF NOT EXISTS kind VARCHAR(20)",),
            label="ensure_sync_request_kind_column",
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

    Issue #102(#102 AC3):**ADDA COLUMN IF NOT EXISTS 在列已存在时仍先取
    ACCESS EXCLUSIVE 再判 no-op** —— 生产死锁源(每轮 init_db 的 no-op DDL
    排队在 repair-all 长事务之后)。因此先做 catalog 存在性探测(只读
    pg_catalog,不申请目标表锁):schema 已兼容 ⇒ **零 DDL 语句**直接返回;
    真缺列 ⇒ 仍执行真实兼容性 DDL,但在有界 ``lock_timeout`` 下,与长事务
    重叠时以可执行错误有界失败(下一轮重试),绝不无限排队、绝不静默跳过。
    """
    statements = (
        "ALTER TABLE documents ADD COLUMN IF NOT EXISTS content_type VARCHAR(30)",
        "ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS next_run_at TIMESTAMPTZ",
        "ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS knowledge_role VARCHAR(20)",
        "ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS freshness_hours INTEGER",
        "CREATE INDEX IF NOT EXISTS ix_documents_content_type ON documents (content_type)",
    )
    async with engine.begin() as conn:
        if (
            await _table_column_exists(conn, "documents", "content_type")
            and await _table_column_exists(conn, "data_sources", "next_run_at")
            and await _table_column_exists(conn, "data_sources", "knowledge_role")
            and await _table_column_exists(conn, "data_sources", "freshness_hours")
            and await _index_exists(conn, "documents", "ix_documents_content_type")
        ):
            return
        await _execute_compat_ddl(conn, statements, label="ensure_track_c_columns")


async def ensure_sync_delta_columns(engine: AsyncEngine) -> None:
    """补齐 #65 SyncLog document-delta 列(加性、幂等、零回填)。

    生产发布仍须先执行 ``scripts/migrate_add_sync_delta_counts.py``；这里
    的启动期守卫只让开发/测试中已经存在的旧表安全加载新读写代码。

    Issue #102:同 ensure_track_c_columns —— 稳态零 DDL;真缺列时有界。
    """
    async with engine.begin() as conn:
        if await _table_column_exists(conn, "sync_log", "delta_counts"):
            return
        await _execute_compat_ddl(
            conn,
            ("ALTER TABLE sync_log ADD COLUMN IF NOT EXISTS delta_counts JSONB",),
            label="ensure_sync_delta_columns",
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
