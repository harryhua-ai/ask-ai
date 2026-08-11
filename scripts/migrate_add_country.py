"""migration: 为 conversations 表添加 country 列(地域分布)。

用法:
    uv run python scripts/migrate_add_country.py

安全:幂等 — 列已存在时跳过。
"""

import asyncio
import logging

from sqlalchemy import text

from backend.db.session import init_db, session_factory

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

ALTER_SQL = "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS country VARCHAR(10)"


async def main() -> None:
    await init_db()
    async with session_factory() as session:
        await session.execute(text(ALTER_SQL))
        await session.commit()
    logger.info("✅ conversations.country 列已确保存在")


if __name__ == "__main__":
    asyncio.run(main())
