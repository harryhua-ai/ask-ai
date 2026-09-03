"""sync_runs 运行时事实列迁移(W2 Sync Truth Backend)。

新增三列(全部可空,NULL=未知,读侧禁止推断):
    execution_device VARCHAR(16)  -- gpu / cpu / gpu_to_cpu(受控词表,机器真值)
    fallback_reason  VARCHAR(32)  -- 机器可读原因码(W1 写入)
    fallback_detail  TEXT         -- 人类可读补充,绝不作为状态判断依据

幂等:表不存在则建表(create_all 语义),已存在则 ALTER TABLE ADD COLUMN
IF NOT EXISTS 逐列补齐;重复执行无副作用。新环境由 init_db create_all
自举全部列,本脚本是生产纪律下的显式迁移契约。

用法:
    python scripts/migrate_add_sync_run_runtime_facts.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text

from backend.config import load_settings
from backend.db.models import SyncRun
from backend.db.session import get_engine

# 本迁移负责新增的运行时事实列(列名 → DDL 类型)
RUNTIME_FACT_COLUMNS: dict[str, str] = {
    "execution_device": "VARCHAR(16)",
    "fallback_reason": "VARCHAR(32)",
    "fallback_detail": "TEXT",
}

# 迁移完成后 sync_runs 必须齐全的列(Wave-0 17 列 + 本迁移 3 列)
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
} | set(RUNTIME_FACT_COLUMNS)


async def migrate(engine) -> None:
    """幂等补列 + 校验;重复执行必须无副作用。"""
    async with engine.begin() as conn:
        await conn.run_sync(lambda sc: SyncRun.__table__.create(sc, checkfirst=True))
        for name, ddl in RUNTIME_FACT_COLUMNS.items():
            await conn.execute(text(f"ALTER TABLE sync_runs ADD COLUMN IF NOT EXISTS {name} {ddl}"))
    # 校验:列齐全
    async with engine.connect() as conn:
        columns = await conn.run_sync(
            lambda sc: {c["name"] for c in inspect(sc).get_columns("sync_runs")}
        )
    missing = EXPECTED_COLUMNS - columns
    if missing:
        raise RuntimeError(f"sync_runs 缺列: {sorted(missing)}")
    print(
        f"OK: sync_runs 运行时事实列就绪"
        f"({sorted(RUNTIME_FACT_COLUMNS)},共 {len(columns)} 列,幂等迁移完成)"
    )


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
