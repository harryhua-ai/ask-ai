"""创建 Conversation ID 策略表并写入兼容默认值。

幂等、加性、无历史 ID 改写。部署前由 release migrations manifest 调用。
"""

import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import load_settings
from backend.db.session import get_engine

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS conversation_id_policies (
    key VARCHAR(50) PRIMARY KEY,
    strategy VARCHAR(20) NOT NULL DEFAULT 'uuid4',
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""
SEED_DEFAULT = """
INSERT INTO conversation_id_policies (key, strategy)
VALUES ('default', 'uuid4')
ON CONFLICT (key) DO NOTHING
"""


async def migrate(dsn: str) -> None:
    engine = get_engine(dsn)
    async with engine.begin() as conn:
        await conn.execute(text(CREATE_TABLE))
        await conn.execute(text(SEED_DEFAULT))
    await engine.dispose()


if __name__ == "__main__":
    dsn = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_DSN")
    if not dsn:
        dsn = load_settings().postgres_dsn
    asyncio.run(migrate(dsn))
