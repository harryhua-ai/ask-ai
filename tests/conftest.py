"""pytest 全局 fixtures。"""

import os
from functools import lru_cache
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import backend.auth.jwt
from backend.auth.jwt import hash_password as _real_hash_password
from backend.config import load_settings
from backend.db.models import Base
from backend.db.session import get_engine, get_session_factory, init_db

# --------------------------------------------------------------------------- #
# B1 测试隔离契约:HuggingFace 缓存环境变量每测试精确快照/恢复
#
# 生产代码 backend/embedder/bge.py::_ensure_hf_cache 通过 os.environ.setdefault
# 直接写进程级 HF_HOME / HF_HUB_CACHE / TRANSFORMERS_CACHE(生产语义,本任务不改)。
# 任何测试触发该路径(真实 BGE 集成测试 / 传 cache_dir 的构造器单测)都会把变量
# 留在本进程;若指向已销毁的 tmp_path,后续真实 BGE 测试会命中死缓存而重新下载数 GB
# 权重。此 autouse 守卫保证每个测试结束后这些变量恢复到测试前的精确状态
# (原本缺失 → 恢复缺失;原本存在 → 恢复原值),测试顺序无关。
# --------------------------------------------------------------------------- #

_HF_ENV_VARS = ("HF_HOME", "HF_HUB_CACHE", "TRANSFORMERS_CACHE")

# 会话起点基线:conftest 导入早于全部测试模块与任何 fixture 执行,是跨模块
# 边界回归(hf_session_baseline)唯一可靠的「原始环境」权威参照点。
_HF_SESSION_BASELINE: dict[str, str | None] = {
    var: os.environ.get(var) for var in _HF_ENV_VARS
}


@pytest.fixture(scope="session")
def hf_session_baseline() -> dict[str, str | None]:
    """会话起点 HF 环境基线(不可变 dict)。

    供模块级 fixture 边界回归断言「模块生命周期结束后,后续独立测试上下文
    看到与会话起点逐字节一致的环境」。在 conftest 模块导入时捕获,不受任何
    测试/fixture 期间变更影响。
    """
    return dict(_HF_SESSION_BASELINE)


@pytest.fixture(autouse=True)
def _hf_env_isolation():
    """HF 缓存环境变量隔离守卫(见模块级契约注释)。"""
    snapshot = {var: os.environ[var] for var in _HF_ENV_VARS if var in os.environ}
    yield
    for var in _HF_ENV_VARS:
        if var in snapshot:
            os.environ[var] = snapshot[var]
        else:
            os.environ.pop(var, None)


# --------------------------------------------------------------------------- #
# B2 bcrypt 成本收敛:进程内按明文缓存真实哈希
#
# admin 测试的每个 fixture 都调用 hash_password 建测试用户(bcrypt cost 12,
# 每次 ~250ms,整轮 ~40s)。此处把 backend.auth.jwt.hash_password 替换为
# lru_cache 包装:同一明文整个 pytest 会话只做一次真实 bcrypt 计算,产物即
# 真实哈希;认证端 verify_password / 登录失败路径零改动,行为 coverage 不变。
# conftest 模块级生效(import 早于全部测试模块的 from-import 绑定)。
# 真实 hash+verify 回归保留于 tests/auth/test_jwt.py(经同一包装,仍是真实
# bcrypt 算法;wrong-password 断言验证真实 verify 语义)。
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=None)
def _cached_hash_password(plain: str) -> str:
    return _real_hash_password(plain)


backend.auth.jwt.hash_password = _cached_hash_password


@pytest.fixture
def config_dir() -> Path:
    """返回项目 config 目录路径。"""
    return Path(__file__).parent.parent / "config"


@pytest.fixture
async def db_engine():
    """创建测试用异步 Postgres 引擎并初始化表结构。

    依赖环境变量配置 Postgres 连接(参见 .env.example)。
    测试完成后清理所有表并销毁引擎,保证测试隔离。需要 Postgres 实例运行。

    环境变量:
        TEST_DATABASE_URL: 覆盖默认 DSN(便于 CI 注入测试数据库)。

    Yields:
        AsyncEngine: 已初始化表结构的异步引擎。
    """
    dsn = os.environ.get(
        "TEST_DATABASE_URL",
        load_settings(config_dir=Path(__file__).parent.parent / "config").postgres_dsn,
    )
    engine = get_engine(dsn)
    try:
        await init_db(engine)
        yield engine
    finally:
        # 测试结束后清理所有表,避免跨测试数据污染
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest.fixture
async def db_session(db_engine) -> AsyncSession:
    """基于 db_engine 提供一个异步会话,测试结束后关闭。

    Args:
        db_engine: 已初始化表结构的异步引擎。

    Yields:
        AsyncSession: ``expire_on_commit=False`` 的异步会话。
    """
    factory = get_session_factory(db_engine)
    async with factory() as session:
        yield session
