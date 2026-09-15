"""#71 权威成员货币真值列迁移(加性;幂等;NULL 保全历史行)。

为 ``data_sources`` 增加五列(见 backend/db/models.py DataSource):

- membership_status      VARCHAR(20)  current/stale/failed/unsupported;NULL=未对账
- membership_checked_at  TIMESTAMPTZ  最近一次权威对账完成时间
- membership_stale_detected  INTEGER  本轮发现陈旧成员数(文档)
- membership_stale_retired   INTEGER  本轮实际退休数(文档)
- membership_detail      JSONB        审计采样(枚举/在服规模 + 清单样例)

迁移为纯加性(ALTER TABLE ADD COLUMN IF NOT EXISTS),不触碰既有行
(NULL = 尚未对账,读面呈现 unknown,不降级健康)。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv

load_dotenv()

from sqlalchemy import text

from backend.db.models import DataSource

_STATEMENTS = (
    "ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS membership_status VARCHAR(20)",
    "ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS membership_checked_at TIMESTAMPTZ",
    "ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS membership_stale_detected INTEGER",
    "ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS membership_stale_retired INTEGER",
    "ALTER TABLE data_sources ADD COLUMN IF NOT EXISTS membership_detail JSONB",
)

_EXPECTED_COLUMNS = (
    "membership_status",
    "membership_checked_at",
    "membership_stale_detected",
    "membership_stale_retired",
    "membership_detail",
)


async def migrate(engine) -> None:
    """加性迁移 + 幂等验证(列缺失即 RuntimeError,绝不静默)。"""
    async with engine.begin() as conn:
        for stmt in _STATEMENTS:
            await conn.execute(text(stmt))
        # 同一事务内建表(空库首启幂等)
        await conn.run_sync(
            lambda sc: DataSource.__table__.create(sc, checkfirst=True)
        )
    # 验证
    from sqlalchemy import inspect

    def _has_columns(sync_conn):
        insp = inspect(sync_conn)
        cols = {c["name"] for c in insp.get_columns("data_sources")}
        missing = [c for c in _EXPECTED_COLUMNS if c not in cols]
        if missing:
            raise RuntimeError(f"#71 迁移验证失败: data_sources 缺列 {missing}")
        return True

    async with engine.connect() as conn:
        await conn.run_sync(_has_columns)
    print("OK: data_sources membership currency columns present")


def _main() -> None:
    import asyncio

    from backend.config import load_settings, resolve_migration_dsn
    from backend.db.session import get_engine

    settings = load_settings()
    dsn = resolve_migration_dsn(settings)
    engine = get_engine(dsn)

    async def _run():
        try:
            await migrate(engine)
        finally:
            await engine.dispose()

    asyncio.run(_run())


if __name__ == "__main__":
    _main()
