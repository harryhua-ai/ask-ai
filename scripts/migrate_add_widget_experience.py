"""migration: I-UX-001 —— site_experiences experience 列 + site_trusted_actions 表(幂等、零回填)。

用法:
    uv run python scripts/migrate_add_widget_experience.py

安全:
- 仅 ``ADD COLUMN IF NOT EXISTS`` 十个 nullable 体验列(entry_mode /
  proactive_timing / launcher_motion / launcher_size / launcher_brand /
  launcher_color / chat_theme / chat_accent_color / chat_size /
  greeting_override),不改写任何既有行;
- 迁移契约(冻结):既有站点 experience 列 NULL = 未配置 → 保持 legacy
  入口行为;新站点缺省 mini_entry 由 seed 只在**新建行**时写入;
- 新建 ``site_trusted_actions`` 表(CREATE TABLE IF NOT EXISTS),site_id
  级联删除;零数据回填;
- 不触碰既有 launcher_* 列与 seed 语义(YAML 权威字段集合不变)。
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
    "ALTER TABLE site_experiences ADD COLUMN IF NOT EXISTS entry_mode VARCHAR(20)",
    "ALTER TABLE site_experiences ADD COLUMN IF NOT EXISTS proactive_timing VARCHAR(10)",
    "ALTER TABLE site_experiences ADD COLUMN IF NOT EXISTS launcher_motion VARCHAR(20)",
    "ALTER TABLE site_experiences ADD COLUMN IF NOT EXISTS launcher_size VARCHAR(10)",
    "ALTER TABLE site_experiences ADD COLUMN IF NOT EXISTS launcher_brand VARCHAR(10)",
    "ALTER TABLE site_experiences ADD COLUMN IF NOT EXISTS launcher_color VARCHAR(20)",
    "ALTER TABLE site_experiences ADD COLUMN IF NOT EXISTS chat_theme VARCHAR(10)",
    "ALTER TABLE site_experiences ADD COLUMN IF NOT EXISTS chat_accent_color VARCHAR(20)",
    "ALTER TABLE site_experiences ADD COLUMN IF NOT EXISTS chat_size VARCHAR(10)",
    "ALTER TABLE site_experiences ADD COLUMN IF NOT EXISTS greeting_override VARCHAR(200)",
]

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS site_trusted_actions (
    id UUID PRIMARY KEY,
    site_id VARCHAR(100) NOT NULL REFERENCES site_experiences(site_id) ON DELETE CASCADE,
    action_type VARCHAR(40) NOT NULL,
    label VARCHAR(60) NOT NULL,
    query VARCHAR(500) NOT NULL,
    state VARCHAR(10) NOT NULL DEFAULT 'draft',
    sort_order INTEGER NOT NULL DEFAULT 0,
    last_tested_at TIMESTAMPTZ,
    last_verified_at TIMESTAMPTZ,
    last_test_result JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

CREATE_INDEX_SQL = [
    "CREATE INDEX IF NOT EXISTS ix_site_trusted_actions_site_id ON site_trusted_actions (site_id)",
]


async def main() -> None:
    settings = load_settings()
    engine = get_engine(resolve_migration_dsn(settings))
    async with engine.begin() as conn:
        for sql in ALTER_SQL:
            await conn.execute(text(sql))
        await conn.execute(text(CREATE_TABLE_SQL))
        for sql in CREATE_INDEX_SQL:
            await conn.execute(text(sql))
    logger.info("✅ site_experiences experience 列 + site_trusted_actions 表已确保存在")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
