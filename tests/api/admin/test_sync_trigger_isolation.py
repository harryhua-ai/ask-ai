"""Admin 手动同步触发契约(阶段9 — TRUE 容器级生命周期隔离)。

P4 冻结合同:POST sync 只做校验 + 向 ``sync_requests`` 交接表写入持久
pending 请求,立即返回;**绝不**在 backend 进程/容器内执行 ingest
(2026-09-02 生产 504 黄金事故回归防线)。执行由独立 sync-executor
容器领用(``scripts/sync_executor_loop.py`` → 子进程 ``scripts/sync.py``)。

- accepted = 请求已持久进入执行面交接队列 ≠ sync success(触发零
  sync_log 写入;结果由执行面按既有约定落 sync_log);
- 同 key 已有 pending/running 请求 → already-running,不重复入队;
- 交接写库失败 → 502 明确错误,不伪装 accepted;
- source_id 是数据参数(存入行字段),不构成命令字符串;
- 匿名请求被 Admin auth 边界拒绝,且不写任何交接行。
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import DataSource, SyncLog, SyncRequest, User
from backend.main import app

# 与 admin API 测试共享 session 级事件循环(conftest 的 session fixture 对齐)
pytestmark = pytest.mark.asyncio(loop_scope="session")


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


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def _clean_handoff():
    """交接表是共享测试库状态,用例前后清空防串扰。"""
    factory = app.state.session_factory
    async with factory() as session:
        await session.execute(SyncRequest.__table__.delete())
        await session.commit()
    yield
    async with factory() as session:
        await session.execute(SyncRequest.__table__.delete())
        await session.commit()


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


async def _active_requests() -> list[SyncRequest]:
    factory = app.state.session_factory
    async with factory() as session:
        rows = (
            (
                await session.execute(
                    select(SyncRequest)
                    .where(SyncRequest.status.in_(["pending", "running"]))
                    .order_by(SyncRequest.id)
                )
            )
            .scalars()
            .all()
        )
    return list(rows)


async def test_trigger_writes_pending_request_and_returns_accepted(auth_headers, monkeypatch):
    """AC1/AC2:单源触发写入持久交接行并 202 accepted;进程内绝不执行
    _sync_one(置雷防线);行内 source_id/triggered_by 正确。"""
    import scripts.sync as sync_mod

    def _boom(*a, **k):
        raise AssertionError("单源触发不得在 backend 进程内执行同步业务逻辑")

    monkeypatch.setattr(sync_mod, "_sync_one", _boom)
    await _seed_source("iso-src")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/admin/data-sources/iso-src/sync", headers=auth_headers)
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "accepted"
        assert data["source_id"] == "iso-src"
        assert isinstance(data["request_id"], int)
        # 交接行已持久存在(pending,等待独立执行面领用)
        factory = app.state.session_factory
        async with factory() as session:
            row = (
                await session.execute(
                    select(SyncRequest).where(SyncRequest.id == data["request_id"])
                )
            ).scalar_one()
        assert row.status == "pending"
        assert row.source_id == "iso-src"
        assert row.triggered_by == "manual"
    finally:
        await _drop_source("iso-src")


async def test_trigger_duplicate_active_returns_already_running(auth_headers):
    """§11 最低并发安全:同源已有 pending 请求 → already-running,不重复入队。"""
    await _seed_source("iso-dup")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r1 = await client.post("/api/admin/data-sources/iso-dup/sync", headers=auth_headers)
            assert r1.json()["status"] == "accepted"
            r2 = await client.post("/api/admin/data-sources/iso-dup/sync", headers=auth_headers)
        assert r2.status_code == 202
        assert r2.json()["status"] == "already-running"
        assert r2.json()["request_id"] == r1.json()["request_id"]
        factory = app.state.session_factory
        async with factory() as session:
            count = (await session.execute(select(func.count()).select_from(SyncRequest))).scalar()
        assert count == 1  # 只有一行,无重复入队
    finally:
        await _drop_source("iso-dup")


async def test_trigger_running_row_blocks_same_source(auth_headers):
    """执行面领用后(status=running)同源重复触发同样 already-running。"""
    await _seed_source("iso-run")
    factory = app.state.session_factory
    async with factory() as session:
        session.add(SyncRequest(source_id="iso-run", status="running", triggered_by="manual"))
        await session.commit()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/admin/data-sources/iso-run/sync", headers=auth_headers)
        assert resp.status_code == 202
        assert resp.json()["status"] == "already-running"
    finally:
        await _drop_source("iso-run")


async def test_submit_failure_returns_explicit_error_not_accepted(auth_headers, monkeypatch):
    """AC10:交接写库失败 → 502 明确错误,不伪装 accepted/success。"""
    from backend.services.sync_requests import SyncRequestSubmitError

    async def _broken(session, source_id, *, triggered_by="manual"):
        raise SyncRequestSubmitError("交接请求写入失败: db unavailable")

    # 端点函数内延迟导入,patch 源模块属性即可命中
    monkeypatch.setattr("backend.services.sync_requests.submit_sync_request", _broken)
    await _seed_source("iso-fail")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/admin/data-sources/iso-fail/sync", headers=auth_headers)
        assert resp.status_code == 502
        assert "写入失败" in resp.json()["detail"]
    finally:
        await _drop_source("iso-fail")


async def test_trigger_source_id_stored_as_data_verbatim(auth_headers):
    """AC13/§10:含 shell 元字符的 source_id 作为**数据**原样存入行字段;
    交接链路无命令构造面(执行面以 argv 数据参数消费)。"""
    hostile = "iso$(reboot);touch&|`x`"
    await _seed_source(hostile)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/admin/data-sources/{hostile}/sync", headers=auth_headers
            )
        assert resp.status_code == 202
        factory = app.state.session_factory
        async with factory() as session:
            row = (
                await session.execute(select(SyncRequest).where(SyncRequest.status == "pending"))
            ).scalar_one()
        assert row.source_id == hostile  # 原样数据,未被解释
    finally:
        await _drop_source(hostile)


async def test_trigger_requires_auth_and_writes_nothing(auth_headers):
    """AC12:匿名请求被既有 Admin auth 边界拒绝,且不写任何交接行。"""
    await _seed_source("iso-anon")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/admin/data-sources/iso-anon/sync")
        assert resp.status_code in (401, 403)
        factory = app.state.session_factory
        async with factory() as session:
            count = (
                await session.execute(
                    select(func.count())
                    .select_from(SyncRequest)
                    .where(SyncRequest.source_id == "iso-anon")
                )
            ).scalar()
        assert count == 0
    finally:
        await _drop_source("iso-anon")


async def test_accepted_does_not_write_sync_log(auth_headers):
    """AC3/§16:accepted ≠ success —— 触发瞬间不写任何 sync_log 行。"""
    await _seed_source("iso-log")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/admin/data-sources/iso-log/sync", headers=auth_headers)
        assert resp.status_code == 202
        factory = app.state.session_factory
        async with factory() as session:
            count = (
                await session.execute(
                    select(func.count()).select_from(SyncLog).where(SyncLog.source_id == "iso-log")
                )
            ).scalar()
        assert count == 0
    finally:
        await _drop_source("iso-log")


async def test_sync_all_writes_null_source_request_keeps_contract(auth_headers):
    """sync-all:一个 NULL source_id 交接行(执行面单 runner 顺序跑);
    响应保留 source_ids/count 前端契约;NULL 键去重。"""
    await _seed_source("iso-all-a")
    await _seed_source("iso-all-b", enabled=False)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            r1 = await client.post("/api/admin/data-sources/sync-all", headers=auth_headers)
            assert r1.status_code == 202
            data = r1.json()
            assert data["status"] == "accepted"
            assert "iso-all-a" in data["source_ids"]
            assert "iso-all-b" not in data["source_ids"]  # 跳过禁用
            assert data["count"] == len(data["source_ids"]) >= 1
            r2 = await client.post("/api/admin/data-sources/sync-all", headers=auth_headers)
        assert r2.json()["status"] == "already-running"  # NULL 键去重
        factory = app.state.session_factory
        async with factory() as session:
            rows = (await session.execute(select(SyncRequest))).scalars().all()
        assert len(rows) == 1
        assert rows[0].source_id is None
    finally:
        await _drop_source("iso-all-a")
        await _drop_source("iso-all-b")


async def test_sync_all_submit_failure_returns_502(auth_headers, monkeypatch):
    """AC10(sync-all 面):交接写库失败同样 502 显式报错。"""
    from backend.services.sync_requests import SyncRequestSubmitError

    async def _broken(session, source_id, *, triggered_by="manual"):
        raise SyncRequestSubmitError("交接请求写入失败: db unavailable")

    monkeypatch.setattr("backend.services.sync_requests.submit_sync_request", _broken)
    await _seed_source("iso-all-fail")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/admin/data-sources/sync-all", headers=auth_headers)
        assert resp.status_code == 502
        assert "写入失败" in resp.json()["detail"]
    finally:
        await _drop_source("iso-all-fail")


async def test_sync_all_noop_when_no_enabled_sources(auth_headers):
    """无启用源 → noop,不写交接行。"""
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
    factory = app.state.session_factory
    async with factory() as session:
        rows = (await session.execute(select(SyncRequest))).scalars().all()
    assert rows == []
