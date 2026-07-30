"""YAML 配置 → Postgres 一次性迁移脚本。

将 config/ 目录下的 data_sources.yaml、llm_providers.yaml、system_prompt.yaml
中的配置迁移到对应的 Postgres 表。

用法：python scripts/migrate_yaml_to_db.py
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from sqlalchemy import select

from backend.auth.crypto import encrypt_api_key
from backend.config import load_settings, load_yaml_config
from backend.db.models import (
    Customization,
    CustomizationBinding,
    DataSource,
    LLMProviderModel,
    LLMRouting,
)
from backend.db.session import get_engine, get_session_factory, init_db
from backend.services.config_loader import load_data_sources_from_yaml

load_dotenv()
logger = logging.getLogger(__name__)


async def migrate_data_sources(factory) -> None:
    yaml_data = load_yaml_config(Path("config/data_sources.yaml"))
    sources = load_data_sources_from_yaml(yaml_data)
    async with factory() as session:
        for s in sources:
            existing = await session.execute(select(DataSource).where(DataSource.id == s["id"]))
            if existing.scalar_one_or_none():
                continue
            session.add(DataSource(**s))
        await session.commit()
    logger.info("迁移 %d 个数据源", len(sources))


async def migrate_llm_providers(factory, encryption_key: str) -> None:
    yaml_data = load_yaml_config(Path("config/llm_providers.yaml"))
    sensitive_keys = {"api_key", "secret", "token", "password"}
    async with factory() as session:
        for prov in yaml_data.get("providers", []):
            existing = await session.execute(
                select(LLMProviderModel).where(LLMProviderModel.id == prov["id"])
            )
            if existing.scalar_one_or_none():
                continue
            cfg = dict(prov.get("config", {}))
            for k in sensitive_keys:
                if cfg.get(k):
                    cfg[k] = encrypt_api_key(str(cfg[k]), encryption_key)
            session.add(
                LLMProviderModel(
                    id=prov["id"],
                    type=prov["type"],
                    enabled=prov.get("enabled", True),
                    config=cfg,
                )
            )
        for task, cfg in yaml_data.get("routing", {}).items():
            chain = cfg.get("chain", []) if isinstance(cfg, dict) else cfg
            existing = await session.execute(select(LLMRouting).where(LLMRouting.task == task))
            if existing.scalar_one_or_none():
                continue
            session.add(LLMRouting(task=task, chain=chain))
        await session.commit()
    logger.info("迁移 LLM 供应商和路由配置")


async def migrate_customizations(factory) -> None:
    yaml_data = load_yaml_config(Path("config/system_prompt.yaml"))
    cust_id = "default"
    async with factory() as session:
        existing = await session.execute(select(Customization).where(Customization.id == cust_id))
        if existing.scalar_one_or_none():
            return
        session.add(
            Customization(
                id=cust_id,
                name="默认配置",
                system_prompt=yaml_data["system_prompt"],
                style_tone=yaml_data.get("response_style"),
                guardrails=yaml_data.get("guardrails"),
                language=yaml_data.get("language", "auto"),
                assistant_name=yaml_data.get("assistant_name", "CamThink 助手"),
            )
        )
        session.add(CustomizationBinding(channel="widget", customization_id=cust_id))
        await session.commit()
    logger.info("迁移默认 Customization 配置")


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    settings = load_settings()
    engine = get_engine(settings.postgres_dsn)
    await init_db(engine)
    factory = get_session_factory(engine)
    await migrate_data_sources(factory)
    await migrate_llm_providers(factory, settings.encryption_key)
    await migrate_customizations(factory)
    await engine.dispose()
    logger.info("迁移完成")


if __name__ == "__main__":
    asyncio.run(main())
