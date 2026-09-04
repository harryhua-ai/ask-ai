"""migration: Issue #24 REV1 —— site_experiences launcher_icon/launcher_shape 两列(加列、幂等、零回填)。

用法:
    uv run python scripts/migrate_add_site_launcher_icon_shape.py

安全:
- 仅 ``ADD COLUMN IF NOT EXISTS`` 两个 nullable 列(launcher_icon/launcher_shape);
- 不改写任何既有行(NULL = 未配置 → 兼容默认 current | rounded-square);
- launcher_style / launcher_theme 列(REV0)零触碰:回滚到旧应用时按遗留
  launcher_style 渲染,行为保真;
- 不触碰 seed 语义(YAML 权威字段集合不变,Admin 外观值跨重启存续)。
前置:REV0 迁移(migrate_add_site_launcher_appearance.py)或等效 schema。
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
    "ALTER TABLE site_experiences ADD COLUMN IF NOT EXISTS launcher_icon VARCHAR(50)",
    "ALTER TABLE site_experiences ADD COLUMN IF NOT EXISTS launcher_shape VARCHAR(20)",
]


async def main() -> None:
    settings = load_settings()
    engine = get_engine(settings.postgres_dsn)
    async with engine.begin() as conn:
        for sql in ALTER_SQL:
            await conn.execute(text(sql))
    logger.info("✅ site_experiences.launcher_icon / launcher_shape 列已确保存在")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
