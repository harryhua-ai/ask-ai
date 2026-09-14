"""Add the persisted #65 SyncLog document-delta contract.

The migration is additive and idempotent.  Existing rows retain NULL, which
means their legacy ``items_updated`` unit is unknown to the administrator
read model; no historical values are guessed or backfilled.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import inspect, text

from backend.config import load_settings
from backend.db.models import SyncLog
from backend.db.session import get_engine


async def migrate(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(lambda sc: SyncLog.__table__.create(sc, checkfirst=True))
        await conn.execute(
            text("ALTER TABLE sync_log ADD COLUMN IF NOT EXISTS delta_counts JSONB")
        )
    async with engine.connect() as conn:
        columns = await conn.run_sync(
            lambda sc: {c["name"] for c in inspect(sc).get_columns("sync_log")}
        )
    if "delta_counts" not in columns:
        raise RuntimeError("sync_log 缺少 delta_counts 列")
    print("OK: sync_log.delta_counts 就绪(幂等迁移完成)")


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
