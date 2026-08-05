"""从 Postgres 加载运行时配置(LLM 供应商、Customization)。

启动时调用,优先从 DB 读取;DB 为空时回退到 YAML(Phase 1 兼容)。
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db.models import Customization, CustomizationBinding, LLMProviderModel, LLMRouting


async def load_llm_config_from_db(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[list[dict], dict[str, list[dict]]] | None:
    """从 DB 加载 LLM 供应商和路由配置。

    Returns:
        (providers_list, routing_dict) 或 None(DB 为空时)。
        providers_list 格式与 llm_providers.yaml 的 providers 字段一致。
        routing_dict 的 chain 元素已归一化为 {"provider", "model"} 对象
        (兼容旧字符串格式数据)。
    """
    async with factory() as session:
        providers = (
            (await session.execute(select(LLMProviderModel).where(LLMProviderModel.enabled)))
            .scalars()
            .all()
        )
        if not providers:
            return None
        routing_rows = (await session.execute(select(LLMRouting))).scalars().all()

    providers_list = [
        {"id": p.id, "type": p.type, "enabled": p.enabled, "config": p.config} for p in providers
    ]
    routing = {
        r.task: [_normalize_chain_item(item) for item in r.chain]
        for r in routing_rows
    }
    return providers_list, routing


def _normalize_chain_item(item: Any) -> dict:
    """将 chain 元素归一化为 {provider, model} 对象。

    旧格式(字符串)→ {provider: str, model: None};
    新格式(对象)→ 补全缺失的 model key。

    保证 LLMRouter 消费方拿到的永远是 dict，不受 DB 中历史字符串数据影响。
    """
    if isinstance(item, str):
        return {"provider": item, "model": None}
    return {"provider": item["provider"], "model": item.get("model")}


async def load_customizations_from_db(
    factory: async_sessionmaker[AsyncSession],
) -> dict[str, dict[str, Any]] | None:
    """从 DB 加载 Customization 配置,按 channel 绑定组织。

    Returns:
        {channel: {system_prompt, style_tone, guardrails, assistant_name, language, id}}
        或 None(DB 为空时)。
    """
    async with factory() as session:
        bindings = (await session.execute(select(CustomizationBinding))).scalars().all()
        if not bindings:
            return None
        result: dict[str, dict[str, Any]] = {}
        for b in bindings:
            cust = await session.execute(
                select(Customization).where(Customization.id == b.customization_id)
            )
            cust = cust.scalar_one_or_none()
            if cust and cust.is_active:
                full_prompt = cust.system_prompt
                if cust.style_tone:
                    full_prompt += f"\n\n## 风格语气\n{cust.style_tone}"
                if cust.guardrails:
                    full_prompt += f"\n\n## 边界规则\n{cust.guardrails}"
                result[b.channel] = {
                    "id": cust.id,
                    "system_prompt": full_prompt,
                    "assistant_name": cust.assistant_name,
                    "language": cust.language,
                }
    return result


def load_data_sources_from_yaml(yaml_data: dict) -> list[dict]:
    """从 YAML 字典读取数据源列表(用于迁移)。

    返回格式与 data_sources 表行结构一致。
    """
    sources = []
    for src in yaml_data.get("sources", []):
        sources.append(
            {
                "id": src["id"],
                "type": src["type"],
                "product": src["product"],
                "enabled": src.get("enabled", True),
                "config": src.get("config", {}),
                "sync_interval": src.get("sync_interval", "24h"),
            }
        )
    return sources
