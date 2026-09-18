"""Issue #94:零语义分块确定性分类表(幂等迁移)。

补加性建表 ``zero_semantic_chunks``(零分块登记;语义见
backend/services/zero_semantic_chunks.py 与 #94 ght-contract):
- 每身份恰一行(PK = source_id,VARCHAR(500) 与 #92 同批容量);
- content_fingerprint / chunker_policy_fingerprint 双轴指纹 + 审计时间戳;
- 索引 idx_zero_semantic_chunks_confirmed(last_confirmed_at)支撑对账
  窗口过滤(membership 压制面)。

幂等:按 information_schema/pg_indexes 判定,已存在即 no-op。全新库由
create_all 建出目标 schema,本迁移 no-op。
"""

import asyncio
import os
import sys

from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TABLE = "zero_semantic_chunks"
_INDEX = "idx_zero_semantic_chunks_confirmed"

_DDL = """
CREATE TABLE IF NOT EXISTS zero_semantic_chunks (
    source_id VARCHAR(500) PRIMARY KEY,
    content_fingerprint VARCHAR(64) NOT NULL,
    chunker_policy_fingerprint VARCHAR(64) NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    times_confirmed INTEGER NOT NULL DEFAULT 1,
    first_seen_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    last_confirmed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
)
"""


def _table_exists(sync_conn, table: str) -> bool:
    row = sync_conn.execute(
        text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_name = :t"
        ),
        {"t": table},
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
    if not _table_exists(sync_conn, _TABLE):
        sync_conn.execute(text(_DDL))
        applied.append(_TABLE)
    if not _index_exists(sync_conn, _INDEX):
        sync_conn.execute(
            text(
                f"CREATE INDEX {_INDEX} ON {_TABLE} (last_confirmed_at)"
            )
        )
        applied.append(_INDEX)
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
        print(f"OK: {'; '.join(applied)}" if applied else "OK: 幂等 no-op")
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
