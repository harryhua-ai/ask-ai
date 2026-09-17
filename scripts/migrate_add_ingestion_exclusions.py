"""Issue #91:新增 ingestion_exclusions 表(幂等加性迁移)。

永久性灌入排除的权威登记面(#91 Final Acceptance Contract AC2/AC4 +
Role A REVIEW_2 修正):确定性技术安全排除在原子 eligible 生成代之前分区
—— 本表是「排除可审计 + 有界压制 + 确定性重评估」的持久化原语。

每身份恰一行(PK = source_id):行 = 对该身份当前权威内容的判定;
``content_hash`` 为判定属性列(内容变更由 builder 重判后原位更新)。
压制窗口与重评估语义见 backend/services/ingestion_exclusions.py。
表结构由 backend/db/models.py IngestionExclusion 权威定义;此处 CREATE
TABLE IF NOT EXISTS 与模型逐列一致(全新库由 init_db create_all 覆盖,
本迁移对存量库补表)。纯加性,零回填,生产执行窗口任意。
"""

import asyncio
import os
import sys

from sqlalchemy import text

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_DDL = """
CREATE TABLE IF NOT EXISTS ingestion_exclusions (
    source_id VARCHAR(500) NOT NULL PRIMARY KEY,
    content_hash VARCHAR(64) NOT NULL,
    reason VARCHAR(50) NOT NULL,
    detail TEXT NOT NULL,
    stage VARCHAR(50) NOT NULL,
    actor VARCHAR(100) NOT NULL,
    times_confirmed INTEGER NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_confirmed_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""

_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_ingestion_exclusions_source "
    "ON ingestion_exclusions (source_id)"
)


async def migrate(engine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(_DDL))
        await conn.execute(text(_INDEX))


async def _main() -> None:
    from backend.config import load_settings
    from backend.db.session import get_engine

    engine = get_engine(load_settings().postgres_dsn)
    try:
        await migrate(engine)
        print("OK: ingestion_exclusions 就绪(幂等迁移完成)")
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
