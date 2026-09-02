"""Admin 手动同步触发契约(阶段9 — Sync Execution Isolation from Online Services)。

P4 冻结合同:POST sync 只做校验 + 提交独立同步执行面(detached
``scripts/sync.py`` 子进程),立即返回;绝不在 backend event loop 内执行
ingest(2026-09-02 生产 504 黄金事故回归防线)。

- accepted ≠ success:触发不写 sync_log,结果由子进程按既有约定落库;
- 执行面启动失败 → 502 明确错误,不伪装 accepted;
- source_id 以 argv 逐元素传给子进程,无 shell 解释面;
- 同 key 已有存活子进程 → already-running,不重复派生(§11 最低安全)。
"""

import sys
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import DataSource, SyncLog, User
from backend.main import app
from backend.services import sync_executor

# 与 admin API 测试共享 session 级事件循环(conftest 的 session fixture 对齐)
pytestmark = pytest.mark.asyncio(loop_scope="session")


class _FakeProc:
    """spawn 假句柄:returncode=None 视为存活。"""

    def __init__(self, pid: int = 4242):
        self.pid = pid
        self.returncode = None


@pytest_asyncio.fixture(loop_scope="session")
async def auth_headers():
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email="sync-iso@test.com",
                role="admin",
                password_hash=hash_password("pass123"),
            )
        )
        await session.commit()
    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}
    async with factory() as session:
        await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.commit()


@pytest_asyncio.fixture(autouse=True)
async def _clean_registry():
    """进程登记是模块级状态,测试前后清空防串扰。"""
    sync_executor._inflight.clear()
    yield
    sync_executor._inflight.clear()


def _patch_spawn(monkeypatch) -> list:
    """替换 spawn 点,记录每次调用;返回调用记录 [(argv, kwargs)]。"""
    spawned: list[tuple[list[str], dict]] = []

    async def _fake(*argv, **kwargs):
        spawned.append((list(argv), kwargs))
        return _FakeProc()

    monkeypatch.setattr(sync_executor, "_spawn", _fake)
    return spawned


async def _seed_source(source_id: str, enabled: bool = True) -> None:
    factory = app.state.session_factory
    async with factory() as session:
        await session.execute(DataSource.__table__.delete().where(DataSource.id == source_id))
        await session.commit()
    async with factory() as session:
        session.add(
            DataSource(
                id=source_id,
                type="filesystem",
                product="test",
                enabled=enabled,
                config={"root_path": "/tmp"},
                sync_interval="24h",
            )
        )
        await session.commit()


async def _drop_source(source_id: str) -> None:
    factory = app.state.session_factory
    async with factory() as session:
        await session.execute(DataSource.__table__.delete().where(DataSource.id == source_id))
        await session.execute(SyncLog.__table__.delete().where(SyncLog.source_id == source_id))
        await session.commit()


async def _sync_log_count(source_id: str) -> int:
    factory = app.state.session_factory
    async with factory() as session:
        result = await session.execute(
            select(func.count()).select_from(SyncLog).where(SyncLog.source_id == source_id)
        )
        return int(result.scalar() or 0)


async def test_trigger_spawns_detached_subprocess_not_inprocess_ingest(auth_headers, monkeypatch):
    """AC1/AC2:单源触发派生 detached sync 子进程并 202 accepted;
    进程内绝不执行 _sync_one(置雷防线);argv 与 start_new_session 正确。"""
    import scripts.sync as sync_mod

    def _boom(*a, **k):
        raise AssertionError("单源触发不得在 backend 进程内执行同步业务逻辑")

    monkeypatch.setattr(sync_mod, "_sync_one", _boom)
    spawned = _patch_spawn(monkeypatch)
    await _seed_source("iso-src")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/admin/data-sources/iso-src/sync", headers=auth_headers)
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "accepted"
        assert data["source_id"] == "iso-src"
        assert data["pid"] == 4242
        # 一次派生,argv 逐元素;同 runner + 显式 manual 标记 + start_new_session
        assert len(spawned) == 1
        argv, kwargs = spawned[0]
        assert argv[0] == sys.executable
        assert argv[1].endswith("scripts/sync.py")
        assert argv[argv.index("--triggered-by") + 1] == "manual"
        assert argv[argv.index("--source") + 1] == "iso-src"
        assert kwargs.get("start_new_session") is True
    finally:
        await _drop_source("iso-src")


async def test_trigger_launch_failure_returns_explicit_error(auth_headers, monkeypatch):
    """AC10:执行面启动失败 → 502 明确错误,不伪装 accepted/success。"""

    async def _broken(*argv, **kwargs):
        raise OSError("spawn failed: interpreter missing")

    monkeypatch.setattr(sync_executor, "_spawn", _broken)
    await _seed_source("iso-fail")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/admin/data-sources/iso-fail/sync", headers=auth_headers)
        assert resp.status_code == 502
        assert "启动失败" in resp.json()["detail"]
        # 失败不进登记,不留下任何"已接受"痕迹
        assert sync_executor._inflight.get("iso-fail") is None
    finally:
        await _drop_source("iso-fail")


async def test_trigger_duplicate_returns_already_running(auth_headers, monkeypatch):
    """§11 最低并发安全:同源存活子进程期间重复触发 → already-running,
    不二次派生;子进程退出后可再次触发。"""
    spawned = _patch_spawn(monkeypatch)
    await _seed_source("iso-dup")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r1 = await client.post("/api/admin/data-sources/iso-dup/sync", headers=auth_headers)
            assert r1.json()["status"] == "accepted"
            r2 = await client.post("/api/admin/data-sources/iso-dup/sync", headers=auth_headers)
        assert r2.status_code == 202
        assert r2.json()["status"] == "already-running"
        assert len(spawned) == 1  # 未重复派生
        # 子进程退出(句柄被回收)后允许再次触发
        sync_executor._inflight["iso-dup"].returncode = 0
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r3 = await client.post("/api/admin/data-sources/iso-dup/sync", headers=auth_headers)
        assert r3.json()["status"] == "accepted"
        assert len(spawned) == 2
    finally:
        await _drop_source("iso-dup")


async def test_trigger_source_id_passed_verbatim_without_shell(auth_headers, monkeypatch):
    """AC13:含 shell 元字符的 source_id 原样作为单个 argv 元素传递;
    spawn 参数是列表(非字符串命令),无 shell 解释面。"""
    spawned = _patch_spawn(monkeypatch)
    # 含 $()/;&|` 等 shell 元字符但不含 "/"(路径段约束),足以证明无 shell 解释面
    hostile = "iso$(reboot);touch&|`x`"
    await _seed_source(hostile)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/admin/data-sources/{hostile}/sync", headers=auth_headers
            )
        assert resp.status_code == 202
        argv, kwargs = spawned[0]
        assert argv[argv.index("--source") + 1] == hostile  # 原样,未被 shell 展开
        assert "shell" not in kwargs
        assert isinstance(argv, list)
    finally:
        await _drop_source(hostile)


async def test_trigger_requires_auth(auth_headers, monkeypatch):
    """AC12:匿名请求被既有 Admin auth 边界拒绝,且不派生任何子进程。"""
    spawned = _patch_spawn(monkeypatch)
    await _seed_source("iso-anon")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/admin/data-sources/iso-anon/sync")
        assert resp.status_code in (401, 403)
        assert spawned == []
    finally:
        await _drop_source("iso-anon")


async def test_accepted_does_not_write_sync_log(auth_headers, monkeypatch):
    """AC3/§16:accepted ≠ success —— 触发瞬间不写任何 sync_log 行。"""
    _patch_spawn(monkeypatch)
    await _seed_source("iso-log")
    try:
        before = await _sync_log_count("iso-log")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/admin/data-sources/iso-log/sync", headers=auth_headers)
        assert resp.status_code == 202
        assert await _sync_log_count("iso-log") == before
    finally:
        await _drop_source("iso-log")


async def test_sync_all_launch_failure_returns_explicit_error(auth_headers, monkeypatch):
    """AC10(sync-all 面):整批触发在执行面启动失败时同样 502 显式报错。"""

    async def _broken(*argv, **kwargs):
        raise OSError("spawn failed")

    monkeypatch.setattr(sync_executor, "_spawn", _broken)
    await _seed_source("iso-all-fail")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/admin/data-sources/sync-all", headers=auth_headers)
        assert resp.status_code == 502
        assert "启动失败" in resp.json()["detail"]
    finally:
        await _drop_source("iso-all-fail")


async def test_sync_all_noop_when_no_enabled_sources(auth_headers, monkeypatch):
    """无启用源 → noop,不派生子进程。"""
    spawned = _patch_spawn(monkeypatch)
    factory = app.state.session_factory
    async with factory() as session:
        count = (
            await session.execute(
                select(func.count()).select_from(DataSource).where(DataSource.enabled.is_(True))
            )
        ).scalar()
    if count:
        pytest.skip("测试库存在其他启用源,noop 语义需干净库,跳过")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/admin/data-sources/sync-all", headers=auth_headers)
    assert resp.status_code == 202
    data = resp.json()
    assert data["status"] == "noop"
    assert data["count"] == 0
    assert spawned == []
