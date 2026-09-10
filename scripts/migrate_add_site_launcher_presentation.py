"""migration: I-UX-001 矫正 —— site_experiences.launcher_presentation 列(幂等、零回填)。

用法:
    uv run python scripts/migrate_add_site_launcher_presentation.py

安全:
- 仅 ``ADD COLUMN IF NOT EXISTS`` 一个 nullable 列(launcher_presentation
  VARCHAR(10)),不改写任何既有行;
- 迁移契约(V2.3 矫正):既有站点 NULL = 未配置 → 紧凑图标(legacy 行为,
  不静默换装);新建站点 seed 缺省 pill 只发生在**新建行**;Admin 显式配置
  永远权威,seed 绝不覆写本列;
- 不触碰既有列、allowed_origins 与 seed 语义。

生产执行窗口:停机 or 低峰执行。
"""

import asyncio
import logging

from sqlalchemy import text

from backend.config import load_settings, resolve_migration_dsn
from backend.db.session import get_engine

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

ALTER_SQL = [
    "ALTER TABLE site_experiences ADD COLUMN IF NOT EXISTS launcher_presentation VARCHAR(10)",
]


async def migrate() -> None:
    settings = load_settings()
    engine = get_engine(resolve_migration_dsn(settings))
    async with engine.begin() as conn:
        for stmt in ALTER_SQL:
            await conn.execute(text(stmt))
    await engine.dispose()
    logger.info("site_experiences.launcher_presentation 迁移完成(幂等,零回填)")


if __name__ == "__main__":
    asyncio.run(migrate())
