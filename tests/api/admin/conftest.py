"""Admin API 测试公共 fixture。

ASGITransport 不触发 FastAPI lifespan，因此手动初始化 app.state
中测试所需的属性（settings / session_factory）。
session 级 autouse，在所有 admin API 测试前执行一次。

注意：session 级 async fixture 需要 loop_scope="session"，否则
pytest-asyncio 默认按 function 创建事件循环，导致 engine 跨 loop 报错。
所有 admin API 测试通过 pytestmark 共享 session 级事件循环。
"""

import os

import pytest_asyncio
from sqlalchemy import select

from backend.auth.crypto import encrypt_api_key
from backend.config import load_settings, load_yaml_config
from backend.db.models import Customization, CustomizationBinding, LLMProviderModel, LLMRouting
from backend.db.session import get_engine, get_session_factory, init_db


@pytest_asyncio.fixture(scope="session", loop_scope="session", autouse=True)
async def _setup_app_state():
    """手动初始化 app.state，绕过 ASGITransport 不触发 lifespan 的问题。

    DB 连接优先用 TEST_DATABASE_URL（CI 注入的测试库），回退到
    settings.postgres_dsn（本地 .env）。否则 CI 里 admin 测试会用 .env 的
    ask_ai:changeme 连不上 test service 的 test:test。
    """
    from backend.main import app

    settings = load_settings()
    app.state.settings = settings

    dsn = os.environ.get("TEST_DATABASE_URL", settings.postgres_dsn)
    engine = get_engine(dsn)
    await init_db(engine)
    factory = get_session_factory(engine)
    app.state.session_factory = factory

    # Seed：在测试库中灌入 LLM 供应商 + 路由基线数据。
    # 现有 admin 测试(test_list_providers_includes_deepseek_and_masks_key /
    # test_list_routing_includes_migrated)依赖 deepseek 供应商 +
    # generation / query_decomposition 路由存在。生产环境这些数据由
    # main.py lifespan 首启 seed，测试库无人 seed，故在此补齐。
    # 只在缺失时插入（幂等），chain 保持旧字符串格式以匹配现有断言
    # （list_routing 端点原样返回 DB 值，不经过归一化）。
    async with factory() as session:
        if not (await session.execute(
            select(LLMProviderModel).where(LLMProviderModel.id == "deepseek")
        )).scalar_one_or_none():
            session.add(LLMProviderModel(
                id="deepseek",
                type="openai_compatible",
                enabled=True,
                config={
                    "api_base": "https://api.deepseek.com/v1",
                    "api_key": encrypt_api_key("sk-test-seed", settings.encryption_key),
                    "model": "deepseek-chat",
                    "max_tokens": 4096,
                    "temperature": 0.3,
                },
            ))
        for task, chain in (
            ("generation", [{"provider": "deepseek", "model": None}]),
            ("query_decomposition", [{"provider": "deepseek", "model": None}]),
        ):
            existing_route = (await session.execute(
                select(LLMRouting).where(LLMRouting.task == task)
            )).scalar_one_or_none()
            if existing_route is None:
                session.add(LLMRouting(task=task, chain=chain))
            else:
                existing_route.chain = chain  # 强制刷新为对象格式

        # default customization + widget 绑定（test_customizations 依赖）
        if not (await session.execute(
            select(Customization).where(Customization.id == "default")
        )).scalar_one_or_none():
            prompt_cfg = load_yaml_config(settings.config_dir / "system_prompt.yaml")
            session.add(Customization(
                id="default",
                name="默认配置",
                system_prompt=prompt_cfg["system_prompt"],
                language=prompt_cfg.get("language", "auto"),
                assistant_name=prompt_cfg.get("assistant_name", "CamThink 助手"),
            ))
            session.add(CustomizationBinding(channel="widget", customization_id="default"))
        await session.commit()

    yield
    await engine.dispose()
