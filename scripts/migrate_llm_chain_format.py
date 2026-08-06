"""LLM chain 格式迁移脚本（幂等）。

将：
1. llm_providers.config.available_models 为空 → 从 config.model 初始化
2. llm_routing.chain 旧字符串格式 → {provider, model} 对象格式
3. 删除 query_decomposition 路由（历史命名错误）
4. 补建 intent / query_rewrite 路由（从 generation 复制）

用法:
    python scripts/migrate_llm_chain_format.py --dry-run   # 预览
    python scripts/migrate_llm_chain_format.py             # 执行
"""

import argparse
import asyncio
import logging

from sqlalchemy import select

from backend.config import load_settings
from backend.db.models import LLMProviderModel, LLMRouting
from backend.db.session import get_engine, get_session_factory

logger = logging.getLogger(__name__)


def _normalize_chain_for_storage(item) -> dict:
    """chain 元素归一化为 {provider, model} 对象（供存储）。"""
    if isinstance(item, str):
        return {"provider": item, "model": None}
    return {"provider": item["provider"], "model": item.get("model")}


async def migrate_providers_available_models(factory, dry_run: bool) -> list[str]:
    """步骤 1:available_models 为空 → 从 config.model 初始化。

    config.model 不在 available_models 中则强制纳入作默认；两者皆空 skip。
    """
    changed: list[str] = []
    async with factory() as session:
        providers = (await session.execute(select(LLMProviderModel))).scalars().all()
        for prov in providers:
            cfg = dict(prov.config)
            avail = cfg.get("available_models") or []
            default_model = cfg.get("model")
            if not avail and not default_model:
                logger.warning("跳过 %s:available_models 与 config.model 均为空", prov.id)
                continue
            if not avail:
                cfg["available_models"] = [default_model]
            elif default_model and default_model not in avail:
                # 强制纳入作默认（放首位）
                cfg["available_models"] = [default_model] + [m for m in avail if m != default_model]
            else:
                continue  # 无需变更
            logger.info("[%s] available_models → %s", prov.id, cfg["available_models"])
            if not dry_run:
                prov.config = cfg
            changed.append(prov.id)
        if changed and not dry_run:
            await session.commit()
    return changed


async def migrate_routing_chain_format(factory, dry_run: bool) -> list[str]:
    """步骤 2:chain 字符串 → 对象格式。返回变更的 task 列表。"""
    changed: list[str] = []
    async with factory() as session:
        routes = (await session.execute(select(LLMRouting))).scalars().all()
        for route in routes:
            had_string = any(isinstance(item, str) for item in route.chain)
            if had_string:
                new_chain = [_normalize_chain_for_storage(item) for item in route.chain]
                logger.info("[%s] chain 格式升级 → 对象", route.task)
                if not dry_run:
                    route.chain = new_chain
                changed.append(route.task)
        if changed and not dry_run:
            await session.commit()
    return changed


def _normalize(chain: list) -> list[dict]:
    """归一化 chain 元素（旧字符串格式 → 对象格式），用于语义比较。"""
    return [
        {"provider": c, "model": None} if isinstance(c, str) else dict(c) for c in (chain or [])
    ]


async def cleanup_query_decomposition(factory, dry_run: bool) -> list[str]:
    """步骤 3:删除 query_decomposition 路由（历史命名错误）。"""
    removed: list[str] = []
    async with factory() as session:
        route = await session.execute(
            select(LLMRouting).where(LLMRouting.task == "query_decomposition")
        )
        route = route.scalar_one_or_none()
        if route:
            # 若 query_decomposition 有自定义 chain（与 generation 语义不同），
            # 删除会丢弃自定义配置——dry-run 时显式提示，让管理员知情
            gen = await session.execute(select(LLMRouting).where(LLMRouting.task == "generation"))
            gen_chain = gen.scalar_one_or_none()
            if gen_chain is not None and _normalize(route.chain) != _normalize(gen_chain.chain):
                logger.warning(
                    "query_decomposition 存在自定义 chain（与 generation 不同），"
                    "删除后将丢弃: %s",
                    route.chain,
                )
            logger.info("删除 query_decomposition 路由（历史命名错误）")
            if not dry_run:
                await session.delete(route)
                await session.commit()
            removed.append("query_decomposition")
    return removed


async def ensure_routing_exists(factory, task: str, dry_run: bool) -> str:
    """步骤 4/5:确保 task 路由存在，不存在则从 generation 复制。

    返回 created/copied/skipped。
    """
    async with factory() as session:
        existing = await session.execute(select(LLMRouting).where(LLMRouting.task == task))
        if existing.scalar_one_or_none():
            return "exists"
        gen = await session.execute(select(LLMRouting).where(LLMRouting.task == "generation"))
        gen = gen.scalar_one_or_none()
        if gen is None:
            logger.warning("补建 %s 失败:generation 路由不存在，skip", task)
            return "skipped"
        logger.info("从 generation 复制 chain → %s", task)
        if not dry_run:
            session.add(LLMRouting(task=task, chain=list(gen.chain)))
            await session.commit()
        return "copied"


async def main(dry_run: bool) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    mode = "DRY-RUN" if dry_run else "EXECUTE"
    logger.info("=== LLM chain 格式迁移（%s）===", mode)

    settings = load_settings()
    engine = get_engine(settings.postgres_dsn)
    factory = get_session_factory(engine)

    p_changed = await migrate_providers_available_models(factory, dry_run)
    r_changed = await migrate_routing_chain_format(factory, dry_run)
    removed = await cleanup_query_decomposition(factory, dry_run)
    intent_status = await ensure_routing_exists(factory, "intent", dry_run)
    qr_status = await ensure_routing_exists(factory, "query_rewrite", dry_run)

    logger.info("=== 完成 ===")
    logger.info("providers 变更:%s", p_changed)
    logger.info("routing chain 升级:%s", r_changed)
    logger.info("删除路由:%s", removed)
    logger.info("intent 路由:%s, query_rewrite 路由:%s", intent_status, qr_status)

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LLM chain 格式迁移")
    parser.add_argument("--dry-run", action="store_true", help="只预览不写入")
    args = parser.parse_args()
    asyncio.run(main(args.dry_run))
