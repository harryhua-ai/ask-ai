"""migration: Hardware-Aware Model Runtime —— 策略/预算两表(建表、幂等、零回填)。

用法:
    uv run python scripts/migrate_add_model_runtime_policy.py

安全:
- 仅 ``CREATE TABLE IF NOT EXISTS`` 两张新表(model_runtime_policies /
  model_runtime_settings),不加列于既有表、不改写任何既有行;
- 缺省(无策略行)= EMBEDDER_DEVICE 引导默认,行为与 v1.1 之前一致,
  现有生产配置不会因部署本迁移而改变模型语义;
- 生产执行窗口:停机 or 低峰执行(标准加表,无长锁)。
"""

import asyncio
import logging

from sqlalchemy import text

from backend.config import load_settings
from backend.db.session import get_engine

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

CREATE_SQL = [
    """
    CREATE TABLE IF NOT EXISTS model_runtime_policies (
        workload VARCHAR(50) PRIMARY KEY,
        model_name VARCHAR(200) NOT NULL,
        device_kind VARCHAR(10) NOT NULL,
        gpu_uuid VARCHAR(100),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS model_runtime_settings (
        key VARCHAR(50) PRIMARY KEY,
        mode VARCHAR(10) NOT NULL DEFAULT 'auto',
        manual_budget_mb INTEGER,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
]


async def main() -> None:
    settings = load_settings()
    engine = get_engine(settings.postgres_dsn)
    async with engine.begin() as conn:
        for sql in CREATE_SQL:
            await conn.execute(text(sql))
    logger.info("✅ model_runtime_policies / model_runtime_settings 表已确保存在")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
