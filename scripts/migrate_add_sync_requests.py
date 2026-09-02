"""migration: 阶段⑨ 同步执行交接表 sync_requests(容器级隔离交接面)。

用法:
    uv run python scripts/migrate_add_sync_requests.py

安全:幂等 —— 表结构经 ``init_db``(create_all)补齐 ``sync_requests``,
已存在则跳过;纯加表,不动既有数据。生产执行窗口:任意(无锁风险)。

背景:backend 触发手动同步改为向本表写入 pending 请求,由独立
sync-executor 容器领用执行(scripts/sync_executor_loop.py),使
backend 容器重启/重建不再终止同步任务(阶段⑨ AC6)。
"""

import asyncio
import logging

from backend.config import load_settings
from backend.db.session import get_engine, init_db

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


async def main() -> None:
    settings = load_settings()
    engine = get_engine(settings.postgres_dsn)
    await init_db(engine)  # create_all:新建 sync_requests(已存在则跳过)
    await engine.dispose()
    logger.info("✅ sync_requests 交接表已确保存在")


if __name__ == "__main__":
    asyncio.run(main())
