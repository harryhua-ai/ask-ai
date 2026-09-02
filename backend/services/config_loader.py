"""从 Postgres 加载运行时配置（LLM 供应商、Customization）。

启动时调用，优先从 DB 读取；DB 没有任何供应商记录时返回 None。
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
        providers = (await session.execute(select(LLMProviderModel))).scalars().all()
        if not providers:
            return None
        enabled_providers = [p for p in providers if p.enabled]
        routing_rows = (await session.execute(select(LLMRouting))).scalars().all()

    providers_list = [
        {"id": p.id, "type": p.type, "enabled": p.enabled, "config": p.config}
        for p in enabled_providers
    ]
    routing = {r.task: [_normalize_chain_item(item) for item in r.chain] for r in routing_rows}
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


async def refresh_runtime_customizations(state: Any) -> None:
    """DB 持久化成功后,原子刷新运行时定制快照(RAGOrchestrator)。

    Admin 定制变更(CRUD/绑定)提交后调用:重新从 DB 加载绑定与定制,
    以**整体引用替换**的方式更新 RAGOrchestrator 快照 —— 并发请求只会
    观察到旧或新完整态,不存在半建状态。

    - state 无 ``rag``(部分测试环境)→ no-op;
    - state.settings 用于回退 yaml(全部绑定被删时)。
    - 失败向上抛出:调用方必须显式上报(持久化已成功,运行时保持
      上一份有效快照),不得静默吞掉造成「已保存」的假象。
    """
    rag = getattr(state, "rag", None)
    if rag is None:
        return
    channel_custs = await load_customizations_from_db(state.session_factory)
    from backend.config import load_yaml_config

    prompt_config = load_yaml_config(state.settings.config_dir / "system_prompt.yaml")
    if channel_custs:
        mapping = {ch: c["system_prompt"] for ch, c in channel_custs.items()}
        default = mapping.get("widget", prompt_config["system_prompt"])
    else:
        mapping = {}
        default = prompt_config["system_prompt"]
    rag.set_customization_snapshot(mapping, default)
