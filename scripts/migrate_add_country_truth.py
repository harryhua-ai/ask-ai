"""Issue #68:Country Truth 迁移(幂等)。

三步语义:
1. 补加性加列 ``conversations.country_source``(权威来源标记:ingress|geoip);
   全新库由 create_all 建出目标 schema → no-op。
2. 补加索引 ``idx_conversations_country``(Country 筛选服务端化,#68 契约
   「Conversation Review 规模下保持可运营」);已存在 → no-op。
3. legacy 处置(契约 AC3 等价项):Accept-Language 启发式时代的存量
   ``country`` 值不是地理事实 —— ``country_source IS NULL 且 country IS NOT NULL``
   的行一律转换 ``country = NULL``(Unknown);**禁止 silent grandfathering**。
   语句天然幂等:权威新行(source 非空)不受影响,转换后无遗留可匹配行。

生产执行窗口:任意(加列/建索引/批量 UPDATE 均为在线安全量级)。
"""

import asyncio
import os
import sys

from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_COLUMN = "country_source"
_INDEX = "idx_conversations_country"


def _column_exists(sync_conn, table: str, column: str) -> bool:
    row = sync_conn.execute(
        text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).scalar()
    return row == 1


def _index_exists(sync_conn, index: str) -> bool:
    row = sync_conn.execute(
        text("SELECT 1 FROM pg_indexes WHERE indexname = :i"), {"i": index}
    ).scalar()
    return row == 1


def migrate_sync(sync_conn) -> list[str]:
    """幂等迁移(同步连接面;测试与部署桥共用)。返回实际执行的步骤列表。"""
    applied: list[str] = []
    if not _column_exists(sync_conn, "conversations", _COLUMN):
        sync_conn.execute(
            text("ALTER TABLE conversations ADD COLUMN country_source VARCHAR(20)")
        )
        applied.append("conversations.country_source")
    if not _index_exists(sync_conn, _INDEX):
        sync_conn.execute(
            text(f"CREATE INDEX {_INDEX} ON conversations (country)")
        )
        applied.append(_INDEX)
    result = sync_conn.execute(
        text(
            "UPDATE conversations SET country = NULL "
            "WHERE country_source IS NULL AND country IS NOT NULL"
        )
    )
    if result.rowcount:
        applied.append(f"legacy_country_nullified({result.rowcount})")
    return applied


async def migrate(engine) -> list[str]:
    """asyncpg 面入口(deploy/prod/migrations.json 清单执行形态)。"""
    applied: list[str] = []
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: applied.extend(migrate_sync(sync_conn)))
    return applied


async def _main() -> None:
    from backend.config import load_settings
    from backend.db.session import get_engine

    engine = get_engine(load_settings().postgres_dsn)
    try:
        applied = await migrate(engine)
        if applied:
            print(f"OK: {'; '.join(applied)}")
        else:
            print("OK: country truth 迁移幂等 no-op")
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
