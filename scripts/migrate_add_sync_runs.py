"""sync_runs 表正式迁移(⑪+⑫ Wave-0 共享核心)。

幂等:checkfirst 建表 + CREATE UNIQUE INDEX IF NOT EXISTS,重复执行无副作用;
新环境由 init_db create_all 自举,本脚本是生产纪律下的显式迁移契约
(不依赖 create_all 隐式行为——create_all 不会给**已存在**的表补索引)。

FINAL REVIEW CORRECTION C:身份不变量 DB 级强制——
    UNIQUE (request_id, source_id, attempt) WHERE request_id IS NOT NULL
请求托管运行三元组确定至多一行;NULL 直跑(cron/CLI)不受约束。

用法:
    python scripts/migrate_add_sync_runs.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text

from backend.config import load_settings
from backend.db.models import SyncRun
from backend.db.session import get_engine

EXPECTED_COLUMNS = {
    "id",
    "request_id",
    "source_id",
    "attempt",
    "recovery",
    "triggered_by",
    "status",
    "stage",
    "stage_current",
    "stage_total",
    "counters",
    "consistency",
    "error_summary",
    "sync_log_id",
    "started_at",
    "updated_at",
    "finished_at",
}

IDENTITY_INDEX = "uq_sync_runs_request_source_attempt"
IDENTITY_INDEX_DDL = (
    f"CREATE UNIQUE INDEX IF NOT EXISTS {IDENTITY_INDEX} "
    "ON sync_runs (request_id, source_id, attempt) "
    "WHERE request_id IS NOT NULL"
)


async def migrate(engine) -> None:
    """幂等建表 + 身份唯一索引 + 校验;重复执行必须无副作用。"""
    async with engine.begin() as conn:
        await conn.run_sync(lambda sc: SyncRun.__table__.create(sc, checkfirst=True))
        await conn.execute(text(IDENTITY_INDEX_DDL))
    # 校验:表列齐全 + 身份索引在位
    async with engine.connect() as conn:
        columns = await conn.run_sync(
            lambda sc: {c["name"] for c in inspect(sc).get_columns("sync_runs")}
        )
        indexes = await conn.run_sync(
            lambda sc: {i["name"] for i in inspect(sc).get_indexes("sync_runs")}
        )
    missing = EXPECTED_COLUMNS - columns
    if missing:
        raise RuntimeError(f"sync_runs 缺列: {sorted(missing)}")
    if IDENTITY_INDEX not in indexes:
        raise RuntimeError(f"身份唯一索引缺失: {IDENTITY_INDEX}")
    print(f"OK: sync_runs 就绪({len(columns)} 列,身份索引在位,幂等迁移完成)")


async def _main() -> None:
    settings = load_settings()
    engine = get_engine(settings.postgres_dsn)
    try:
        await migrate(engine)
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
