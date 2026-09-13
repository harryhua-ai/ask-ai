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

from sqlalchemy import select

from backend.config import load_settings
from backend.db.session import ensure_track_c_columns, get_engine, init_db

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


async def backfill_content_type(engine) -> int:
    """U-7 存量行一次性推导回填(仅 NULL 行;幂等)。

    依据 = 矩阵 DS-P2-16「documents 需类型列/推导规则」:存量行按**同一
    后端权威函数**(content_taxonomy.derive_content_type,与 connector/ingestion
    写入链零漂移)补齐结构化真值;无结构化信号的行保持 NULL(诚实不可用,
    绝不猜测)。前端零参与。
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from backend.db.models import Document
    from backend.services.content_taxonomy import derive_content_type

    updated = 0
    # 走会话工厂逐行推导(函数级一致性;行数=存量账本,本地量级完全可接受)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        rows = (
            (
                await session.execute(
                    select(Document).where(Document.content_type.is_(None))
                )
            )
            .scalars()
            .all()
        )
        for doc in rows:
            doc.content_type = (
                derive_content_type(doc.source_type, doc.url, doc.metadata_) or None
            )
            if doc.content_type is not None:
                updated += 1
        await session.commit()
    return updated


async def main() -> None:
    settings = load_settings()
    engine = get_engine(settings.postgres_dsn)
    await init_db(engine)  # create_all:新建 Track C 三表(已存在则跳过)
    await ensure_track_c_columns(engine)  # 幂等补加性列
    backfilled = await backfill_content_type(engine)  # U-7 存量行推导(仅 NULL)
    await engine.dispose()
    logger.info(
        "✅ Track C 加性迁移完成:documents.content_type(回填 %d 行)+ data_sources."
        "next_run_at/knowledge_role/freshness_hours + document_repair_tasks/"
        "document_recovery_events/knowledge_settings_previews",
        backfilled,
    )


if __name__ == "__main__":
    asyncio.run(main())
