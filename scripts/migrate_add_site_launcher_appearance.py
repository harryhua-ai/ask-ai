"""migration: Issue #24 —— site_experiences launcher 外观两列(加列、幂等、零回填)。

用法:
    uv run python scripts/migrate_add_site_launcher_appearance.py

安全:
- 仅 ``ADD COLUMN IF NOT EXISTS`` 两个 nullable 列(launcher_style/launcher_theme);
- 不改写任何既有行(NULL = 未配置 → Widget 侧兼容默认 current|auto);
- 不触碰 seed 语义(YAML 权威字段集合不变,Admin 外观值跨重启存续)。
生产执行窗口:停机 or 低峰执行。
"""

import asyncio
import logging

from sqlalchemy import text

from backend.config import load_settings
from backend.db.session import get_engine

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

ALTER_SQL = [
    "ALTER TABLE site_experiences ADD COLUMN IF NOT EXISTS launcher_style VARCHAR(50)",
    "ALTER TABLE site_experiences ADD COLUMN IF NOT EXISTS launcher_theme VARCHAR(10)",
]


async def main() -> None:
    settings = load_settings()
    engine = get_engine(settings.postgres_dsn)
    async with engine.begin() as conn:
        for sql in ALTER_SQL:
            await conn.execute(text(sql))
    logger.info("✅ site_experiences.launcher_style / launcher_theme 列已确保存在")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
