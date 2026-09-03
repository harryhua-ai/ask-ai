"""sync_runs 表正式迁移(⑪+⑫ Wave-0 共享核心)。

幂等:checkfirst 建表,重复执行无副作用;新环境由 init_db create_all
自举,本脚本是生产纪律下的显式迁移契约(不依赖 create_all 隐式行为)。

用法:
    python scripts/migrate_add_sync_runs.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect

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


async def migrate() -> None:
    """幂等建表 + 列校验;重复执行必须无副作用。"""
    settings = load_settings()
    engine = get_engine(settings.postgres_dsn)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(
                lambda sync_conn: SyncRun.__table__.create(sync_conn, checkfirst=True)
            )
        # 校验:表存在且列齐全
        async with engine.connect() as conn:
            columns = await conn.run_sync(
                lambda sync_conn: {c["name"] for c in inspect(sync_conn).get_columns("sync_runs")}
            )
        missing = EXPECTED_COLUMNS - columns
        if missing:
            raise RuntimeError(f"sync_runs 缺列: {sorted(missing)}")
        print(f"OK: sync_runs 就绪({len(columns)} 列,幂等迁移完成)")
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(migrate())


if __name__ == "__main__":
    main()
