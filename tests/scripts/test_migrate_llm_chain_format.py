"""迁移脚本测试:幂等、dry-run、旧数据正确升级。

适配 tests/scripts 既有惯例：直接用 TEST_DATABASE_URL 构造 engine/factory，
不依赖 app.state（tests/scripts 没有 admin conftest 的 session 级 fixture）。
"""

import os

import pytest
from sqlalchemy import select

from backend.config import load_settings
from backend.db.models import LLMProviderModel, LLMRouting
from backend.db.session import get_engine, get_session_factory, init_db
from scripts.migrate_llm_chain_format import (
    _normalize_chain_for_storage,
    migrate_providers_available_models,
    migrate_routing_chain_format,
)

pytestmark = pytest.mark.integration

_TEST_IDS = ("test-mig-prov",)
_TEST_TASKS = ("test-mig-task", "test-mig-idem")


@pytest.fixture
async def factory():
    """在 ask_ai_test 库上构造 session factory（与 test_sync_db 同惯例）。"""
    settings = load_settings()
    dsn = os.environ.get("TEST_DATABASE_URL", settings.postgres_dsn)
    assert "ask_ai_test" in dsn, "迁移脚本测试必须在 ask_ai_test 库上运行"
    engine = get_engine(dsn)
    await init_db(engine)
    fac = get_session_factory(engine)
    try:
        yield fac
    finally:
        # 清理本测试创建的数据
        async with fac() as s:
            await s.execute(
                LLMProviderModel.__table__.delete().where(
                    LLMProviderModel.id.in_(_TEST_IDS)
                )
            )
            await s.execute(
                LLMRouting.__table__.delete().where(LLMRouting.task.in_(_TEST_TASKS))
            )
            await s.commit()
        await engine.dispose()


def test_normalize_chain_for_storage_string_to_object():
    """旧字符串 chain 元素 → 对象格式。"""
    assert _normalize_chain_for_storage("deepseek") == {
        "provider": "deepseek",
        "model": None,
    }
    assert _normalize_chain_for_storage({"provider": "x", "model": "m"}) == {
        "provider": "x",
        "model": "m",
    }


@pytest.mark.asyncio
async def test_migrate_providers_inits_available_models_from_config_model(factory):
    """available_models 为空时从 config.model 初始化。"""
    async with factory() as session:
        prov = LLMProviderModel(
            id="test-mig-prov",
            type="openai_compatible",
            enabled=True,
            config={"api_base": "", "api_key": "", "model": "default-model"},
        )
        session.add(prov)
        await session.commit()

    changed = await migrate_providers_available_models(factory, dry_run=False)
    assert "test-mig-prov" in changed

    async with factory() as session:
        result = await session.get(LLMProviderModel, "test-mig-prov")
        assert result.config["available_models"] == ["default-model"]


@pytest.mark.asyncio
async def test_migrate_routing_converts_string_chain(factory):
    """旧字符串 chain → 对象 chain。"""
    async with factory() as session:
        session.add(LLMRouting(task="test-mig-task", chain=["deepseek", "openrouter"]))
        await session.commit()

    changed = await migrate_routing_chain_format(factory, dry_run=False)
    assert "test-mig-task" in changed

    async with factory() as session:
        result = await session.execute(
            select(LLMRouting).where(LLMRouting.task == "test-mig-task")
        )
        route = result.scalar_one()
        assert route.chain == [
            {"provider": "deepseek", "model": None},
            {"provider": "openrouter", "model": None},
        ]


@pytest.mark.asyncio
async def test_migrate_is_idempotent(factory):
    """跑两次结果一致（第二次不产生变更）。"""
    async with factory() as session:
        session.add(LLMRouting(task="test-mig-idem", chain=["deepseek"]))
        await session.commit()

    await migrate_routing_chain_format(factory, dry_run=False)
    changed2 = await migrate_routing_chain_format(factory, dry_run=False)
    assert "test-mig-idem" not in changed2  # 第二次无变更
