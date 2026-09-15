"""Issue #76 — Admin 引导凭证 fail-closed 契约测试。

生产缺陷(基线 f4e6751):Admin 引导在 ADMIN_PASSWORD 缺失时回退固定口令
"admin123" 创建 Admin → 缺失 secret 不是配置失败,而是可预测默认凭证。

冻结语义(本文件即契约):
- 已存在 Admin → 保留(password_hash 不变,不要求 ADMIN_PASSWORD);
- 缺失 Admin + 已配置 ADMIN_PASSWORD → 以配置口令创建;
- 缺失 Admin + 缺失/空 ADMIN_PASSWORD → fail-closed:显式报错、零写入、
  绝不回退任何默认口令。

DB 隔离:全部用例运行在同服务器一次性专用库(每用例 drop→create→init_db,
用毕删除),绝不触碰开发库/生产库。服务器凭 TEST_DATABASE_URL(CI 注入)
或 settings.postgres_dsn(本地 .env)解析,仅替换库名;要求连接用户具备
CREATEDB(本地容器与 CI 测试用户均满足)。
"""

import os
import re
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.auth.jwt import hash_password, verify_password
from backend.config import load_settings
from backend.db.models import DataSource, User
from backend.db.session import get_engine, get_session_factory, init_db
from backend.main import _ensure_admin_user

_BOOT_DB = "ask_ai_issue76_boot"
_ADMIN_EMAIL = "boot-admin@issue76.test"


def _scoped_dsn(db: str) -> str:
    """把服务器 DSN 的库名段替换为 db(其余 user/host/port 原样)。"""
    base = os.environ.get("TEST_DATABASE_URL") or load_settings().postgres_dsn
    scoped, n = re.subn(r"/([^/?]+)(\?.*)?$", rf"/{db}\2", base)
    assert n == 1, f"DSN 缺少库名段,无法隔离: {base}"
    return scoped


def _maintain_db(target: str, create: bool) -> None:
    """维护连接上 drop|create 目标库(先终止残留连接,幂等)。"""
    import psycopg2

    admin_dsn = _scoped_dsn("postgres")
    scheme, _, rest = admin_dsn.partition("://")
    admin_dsn = f"{scheme.split('+')[0]}://{rest}"  # 剥 SQLAlchemy driver 段(+asyncpg 等)
    conn = psycopg2.connect(admin_dsn)
    try:
        conn.autocommit = True  # CREATE/DROP DATABASE 不能在事务块内执行
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (target,),
            )
            cur.fetchall()  # 消费结果集,避免悬挂游标污染事务状态
            if create:
                cur.execute(f'CREATE DATABASE "{target}"')
            else:
                cur.execute(f'DROP DATABASE IF EXISTS "{target}"')
    finally:
        conn.close()


@pytest_asyncio.fixture(loop_scope="session")
async def boot_factory():
    """一次性隔离库:drop→create→init_db→yield session 工厂→dispose→drop。"""
    _maintain_db(_BOOT_DB, create=False)
    _maintain_db(_BOOT_DB, create=True)
    engine = get_engine(_scoped_dsn(_BOOT_DB))
    await init_db(engine)
    yield get_session_factory(engine)
    await engine.dispose()
    _maintain_db(_BOOT_DB, create=False)


async def _list_users(factory) -> list[User]:
    async with factory() as session:
        return (await session.execute(select(User))).scalars().all()


async def _seed_admin(factory, email: str, password: str) -> str:
    """预置一个已存在 Admin,返回其 password_hash(供逐字节比对)。"""
    seeded_hash = hash_password(password)
    async with factory() as session:
        session.add(User(email=email, role="admin", password_hash=seeded_hash))
        await session.commit()
    return seeded_hash


# --------------------------------------------------------------------------- #
# RED-1:缺失 Admin + 缺失 secret → fail-closed(报错 + 零写入)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio(loop_scope="session")
async def test_red1_missing_admin_missing_secret_fails_closed(boot_factory, monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", _ADMIN_EMAIL)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

    with pytest.raises(RuntimeError, match="ADMIN_PASSWORD"):
        async with boot_factory() as session:
            await _ensure_admin_user(session)
            await session.commit()

    users = await _list_users(boot_factory)
    assert users == [], "fail-closed 路径不得创建任何 Admin 行"


@pytest.mark.asyncio(loop_scope="session")
async def test_red1b_empty_admin_password_treated_as_missing(boot_factory, monkeypatch):
    """空串 ADMIN_PASSWORD 不是有效引导密钥,与缺失同语义(fail-closed)。"""
    monkeypatch.setenv("ADMIN_EMAIL", _ADMIN_EMAIL)
    monkeypatch.setenv("ADMIN_PASSWORD", "")

    with pytest.raises(RuntimeError, match="ADMIN_PASSWORD"):
        async with boot_factory() as session:
            await _ensure_admin_user(session)
            await session.commit()

    assert await _list_users(boot_factory) == []


# --------------------------------------------------------------------------- #
# RED-2:缺失 Admin + 已配置 secret → 正常创建,且配置口令可验证
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio(loop_scope="session")
async def test_red2_missing_admin_configured_secret_creates_admin(boot_factory, monkeypatch):
    configured = "StrongConfiguredSecret-#76"
    monkeypatch.setenv("ADMIN_EMAIL", _ADMIN_EMAIL)
    monkeypatch.setenv("ADMIN_PASSWORD", configured)

    async with boot_factory() as session:
        action = await _ensure_admin_user(session)
        await session.commit()

    assert action == "created"
    users = await _list_users(boot_factory)
    assert len(users) == 1
    admin = users[0]
    assert admin.role == "admin"
    assert admin.email == _ADMIN_EMAIL
    assert verify_password(configured, admin.password_hash), "必须以配置口令创建"
    assert not verify_password("admin123", admin.password_hash), "默认口令不得通过验证"


# --------------------------------------------------------------------------- #
# RED-3 / RED-4:已存在 Admin → 保留现状,启动继续
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio(loop_scope="session")
async def test_red3_existing_admin_missing_secret_preserved(boot_factory, monkeypatch):
    monkeypatch.setenv("ADMIN_EMAIL", _ADMIN_EMAIL)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    seeded_hash = await _seed_admin(boot_factory, _ADMIN_EMAIL, "OriginalSecret-#76")

    async with boot_factory() as session:
        action = await _ensure_admin_user(session)
        await session.commit()

    assert action == "preserved"
    users = await _list_users(boot_factory)
    assert len(users) == 1, "已存在 Admin 不得被重建"
    assert users[0].password_hash == seeded_hash, "password_hash 必须逐字节不变"


@pytest.mark.asyncio(loop_scope="session")
async def test_red4_existing_admin_configured_secret_not_reset(boot_factory, monkeypatch):
    """已存在 Admin + 不同的 ADMIN_PASSWORD → 不得隐式重置/轮换既有账号。"""
    monkeypatch.setenv("ADMIN_EMAIL", _ADMIN_EMAIL)
    monkeypatch.setenv("ADMIN_PASSWORD", "DifferentRotateAttempt-#76")
    seeded_hash = await _seed_admin(boot_factory, _ADMIN_EMAIL, "OriginalSecret-#76")

    async with boot_factory() as session:
        action = await _ensure_admin_user(session)
        await session.commit()

    assert action == "preserved"
    users = await _list_users(boot_factory)
    assert len(users) == 1
    assert users[0].password_hash == seeded_hash
    assert verify_password("OriginalSecret-#76", users[0].password_hash), (
        "原口令必须仍然有效(禁止隐式轮换)"
    )


# --------------------------------------------------------------------------- #
# RED-5:静态守卫 —— 生产源码不得再含固定 Admin 凭证
# --------------------------------------------------------------------------- #


def test_red5_no_fixed_admin_credential_in_production_source():
    backend_root = Path(__file__).resolve().parents[2] / "backend"
    offenders = [
        path.relative_to(backend_root).as_posix()
        for path in sorted(backend_root.rglob("*.py"))
        if "admin123" in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"生产源码出现固定 Admin 凭证: {offenders}"


# --------------------------------------------------------------------------- #
# RED-6:事务安全 —— fail-closed 无部分提交,无关既有状态不受损
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio(loop_scope="session")
async def test_red6_bootstrap_failure_leaves_no_partial_state(boot_factory, monkeypatch):
    """与真实 lifespan 同序:同事务内先 seed DataSource 再引导 Admin。

    引导 fail-closed 时:Admin 行零写入、同事务先行 seed 整体回滚、
    引导前已提交的无关行(普通用户)原样保留。
    """
    monkeypatch.setenv("ADMIN_EMAIL", _ADMIN_EMAIL)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

    unrelated_hash = hash_password("ViewerPass-#76")
    async with boot_factory() as session:
        session.add(
            User(email="plain-user@issue76.test", role="viewer", password_hash=unrelated_hash)
        )
        await session.commit()

    with pytest.raises(RuntimeError, match="ADMIN_PASSWORD"):
        async with boot_factory() as session:
            session.add(
                DataSource(
                    id="website-camthink",
                    type="web_crawl",
                    product="website",
                    enabled=True,
                    config={"base_url": "https://www.camthink.ai", "crawl_delay_ms": 500},
                    sync_interval="24h",
                )
            )
            await _ensure_admin_user(session)
            await session.commit()

    users = await _list_users(boot_factory)
    assert [u.email for u in users] == ["plain-user@issue76.test"], (
        "只允许保留引导前既有行,不得出现部分提交的 Admin"
    )
    assert users[0].password_hash == unrelated_hash, "无关既有行不得被改写"

    async with boot_factory() as session:
        assert await session.get(DataSource, "website-camthink") is None, (
            "同事务先行 seed 必须随 fail-closed 整体回滚"
        )
