"""data_sources 源生命周期列迁移(S0 Foundation;#18 非阻塞删除前置)。

幂等:``ADD COLUMN IF NOT EXISTS`` ×3,重复执行无副作用;新环境由
init_db create_all 自举(models.DataSource 已含三列),本脚本是生产
纪律下的显式迁移契约——create_all 不会给**已存在**的表补列。

词汇表与判定原语见 ``backend/services/source_lifecycle.py``:
    lifecycle_state  NULL(=active)/ delete_requested / deleting / delete_failed
    lifecycle_since  删除受理时间
    lifecycle_error  DELETE_FAILED 的失败摘要

既有行零回填(NULL 即 ACTIVE 语义),无数据改写,可随时执行。

用法:
    python scripts/migrate_add_data_source_lifecycle.py
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text

from backend.config import load_settings, resolve_migration_dsn
from backend.db.session import get_engine

COLUMN_DDL = (
    "ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS lifecycle_state VARCHAR(20)",
    ("ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS lifecycle_since " "TIMESTAMP WITH TIME ZONE"),
    "ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS lifecycle_error TEXT",
)

# 迁移后 data_sources 期望列(既有列 ∪ 本轮三列;既有列做存在性校验防手误删表)
EXPECTED_COLUMNS = {
    "id",
    "type",
    "product",
    "enabled",
    "config",
    "sync_interval",
    "created_at",
    "updated_at",
    "lifecycle_state",
    "lifecycle_since",
    "lifecycle_error",
}


async def migrate(engine) -> None:
    """幂等补列 + 校验;重复执行必须无副作用。"""
    async with engine.begin() as conn:
        for ddl in COLUMN_DDL:
            await conn.execute(text(ddl))
    async with engine.connect() as conn:
        columns = await conn.run_sync(
            lambda sc: {c["name"] for c in inspect(sc).get_columns("data_sources")}
        )
    missing = EXPECTED_COLUMNS - columns
    if missing:
        raise RuntimeError(f"data_sources 缺列: {sorted(missing)}")
    print(
        "OK: data_sources 生命周期列就绪"
        "(lifecycle_state/lifecycle_since/lifecycle_error,幂等迁移完成)"
    )


async def _main() -> None:
    # TEST_DATABASE_URL 覆盖(与 tests/conftest.py 同惯例):ask_ai_test 的
    # data_sources 表由首次 create_all 定型且 create_all 不补列,测试库
    # schema 漂移同样靠本脚本对齐(先例:i18n 迁移对齐 ask_ai_test)。
    # Issue #20:经 resolve_migration_dsn 统一守卫 —— APP_MODE=prod 时
    # 携带 TEST_DATABASE_URL 直接拒绝,绝不静默把生产迁移指向测试库。
    dsn = resolve_migration_dsn(load_settings())
    engine = get_engine(dsn)
    try:
        await migrate(engine)
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
