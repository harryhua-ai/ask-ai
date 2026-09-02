"""migration: 多站点 Widget(MSW)—— site_experiences 表 + conversations.site_id + 站点 seed。

用法:
    uv run python scripts/migrate_add_site_experiences.py

安全:幂等 ——
- 表结构经 ``init_db``(create_all)补齐 ``site_experiences``;
- ``conversations.site_id`` 用 ``ADD COLUMN IF NOT EXISTS`` 补列;
- 站点 seed 按 ``config/sites.yaml``(env ``SITES_CONFIG_PATH`` 可覆盖)幂等 upsert。
生产执行窗口:停机 or 低峰执行;只加列/加表,不动既有数据。
"""

import asyncio
import logging
import os
from pathlib import Path

from sqlalchemy import text

from backend.config import load_settings
from backend.db.session import get_engine, get_session_factory, init_db
from backend.services.site_experiences import seed_default_sites

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

ALTER_SQL = "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS site_id VARCHAR(100)"


async def main() -> None:
    settings = load_settings()
    engine = get_engine(settings.postgres_dsn)
    await init_db(engine)  # create_all:新建 site_experiences(已存在则跳过)
    factory = get_session_factory(engine)
    async with factory() as session:
        await session.execute(text(ALTER_SQL))
        await session.commit()
    logger.info("✅ conversations.site_id 列已确保存在")
    sites_path = os.environ.get("SITES_CONFIG_PATH")
    await seed_default_sites(factory, Path(sites_path) if sites_path else None)
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
