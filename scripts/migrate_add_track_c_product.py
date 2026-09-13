"""migration: v1.6.3 Track C 产品域加性迁移(U-7/U-11/U-12)。

用法:
    uv run python scripts/migrate_add_track_c_product.py

安全:幂等 —— 新表(document_repair_tasks / document_recovery_events /
knowledge_settings_previews)经 ``init_db``(create_all)补齐,已存在则跳过;
加性列经 ``ensure_track_c_columns``(ADD COLUMN IF NOT EXISTS)补齐:
    - documents.content_type(U-7;NULL = 存量行不可用,前端诚实呈现)
    - data_sources.next_run_at(U-11 调度器权威)
    - data_sources.knowledge_role / freshness_hours(U-12 政策层)
纯加性,不动既有数据;生产执行窗口:任意(无锁风险)。
"""

import asyncio
import logging

from backend.config import load_settings
from backend.db.session import ensure_track_c_columns, get_engine, init_db

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = load_settings()
    engine = get_engine(settings.postgres_dsn)
    await init_db(engine)  # create_all:新建 Track C 三表(已存在则跳过)
    await ensure_track_c_columns(engine)  # 幂等补加性列
    await engine.dispose()
    logger.info(
        "✅ Track C 加性迁移完成:documents.content_type + data_sources."
        "next_run_at/knowledge_role/freshness_hours + document_repair_tasks/"
        "document_recovery_events/knowledge_settings_previews"
    )


if __name__ == "__main__":
    asyncio.run(main())
