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

from backend.config import load_settings
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
    app.state.session_factory = get_session_factory(engine)
    yield
    await engine.dispose()
