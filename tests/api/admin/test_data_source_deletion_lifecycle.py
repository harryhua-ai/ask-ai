"""#18 删除生命周期:竞态碰撞 / deny-by-default / 重启恢复语义测试。

覆盖冻结契约中的 Critical Race Conditions:
- active sync vs delete / pending sync vs delete → 409 安全阻止;
- DELETING / DELETE_FAILED / 未来未知状态 → sync 资格 deny-by-default
  (手动端点 + sync.py 配置宇宙两层);
- 孤儿 DELETING 行(进程崩溃遗留)→ sweep 重驱完成(重启恢复语义);
- purge 先于删行(防「配置行已删但 purge 未知」静默半态);
- 删除在途不影响无关源的同步与删除(源间隔离)。
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import DataSource, Document, SyncRequest, SyncRun, User
from backend.main import app

pytestmark = pytest.mark.asyncio(loop_scope="session")

_USER_EMAIL = "e18-lifecycle@test.com"


@pytest_asyncio.fixture(loop_scope="session")
async def lc_seed():
    factory = app.state.session_factory
    async with factory() as session:
        await session.execute(User.__table__.delete().where(User.email == _USER_EMAIL))
        await session.execute(
            DataSource.__table__.delete().where(DataSource.id.like("e18-%"))
        )
        await session.execute(Document.__table__.delete().where(Document.source_id.like("e18-%")))
        await session.commit()

    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email=_USER_EMAIL,
                role="admin",
                password_hash=hash_password("pass"),
            )
        )
        await session.commit()

    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}

    async with factory() as session:
        # 精确清理:只删本模块打标(triggered_by='e18')的交接请求与 e18 源的运行行,
        # 绝不清全表(共享测试库,其他模块的行不是我们的)
        await session.execute(SyncRequest.__table__.delete().where(SyncRequest.triggered_by == "e18"))
        await session.execute(SyncRun.__table__.delete().where(SyncRun.source_id.like("e18-%")))
        await session.execute(User.__table__.delete().where(User.email == _USER_EMAIL))
        await session.execute(DataSource.__table__.delete().where(DataSource.id.like("e18-%")))
        await session.execute(Document.__table__.delete().where(Document.source_id.like("e18-%")))
        await session.commit()


async def _seed_source(sid: str, *, lifecycle_state: str | None = None) -> None:
    factory = app.state.session_factory
    async with factory() as session:
        await session.execute(DataSource.__table__.delete().where(DataSource.id == sid))
        session.add(
            DataSource(
                id=sid,
                type="github",
                product="p",
                enabled=True,
                config={"repo_url": f"https://example.com/{sid}.git"},
                sync_interval="24h",
                lifecycle_state=lifecycle_state,
            )
        )
        await session.commit()


async def _lifecycle_of(source_id: str) -> str | None:
    factory = app.state.session_factory
    async with factory() as session:
        ds = (
            await session.execute(select(DataSource).where(DataSource.id == source_id))
        ).scalar_one_or_none()
        return None if ds is None else ds.lifecycle_state


@pytest.fixture
def ok_purge(monkeypatch):
    calls: list[str] = []

    def _fake(weaviate_url, class_name, prefix, ledger):
        calls.append(prefix)
        return {"ledger_docs": len(ledger), "orphans": 0, "residue": 0}

    monkeypatch.setattr(
        "backend.services.source_deletion.purge_source_corpus_sync", _fake
    )
    return calls


async def _process_deletions() -> list[str]:
    from backend.services.source_deletion import process_pending_deletions

    settings = app.state.settings
    return await process_pending_deletions(
        app.state.session_factory, settings.weaviate_url, settings.weaviate_class_name
    )


# --------------------------------------------------------------------------- #
# 碰撞:pending / active sync vs delete
# --------------------------------------------------------------------------- #


async def test_delete_blocked_by_pending_sync_request(lc_seed, ok_purge):
    """该源有 pending 交接请求 → 删除 409,状态零改变。"""
    await _seed_source("e18-a")
    factory = app.state.session_factory
    async with factory() as session:
        session.add(SyncRequest(source_id="e18-a", status="pending", triggered_by="e18"))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete("/api/admin/data-sources/e18-a", headers=lc_seed)
    assert resp.status_code == 409
    assert await _lifecycle_of("e18-a") is None  # 状态未被推进


async def test_delete_blocked_by_running_sync_request(lc_seed, ok_purge):
    """该源 running 交接请求 → 删除 409。"""
    await _seed_source("e18-a")
    factory = app.state.session_factory
    async with factory() as session:
        session.add(SyncRequest(source_id="e18-a", status="running", triggered_by="e18"))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete("/api/admin/data-sources/e18-a", headers=lc_seed)
    assert resp.status_code == 409


async def test_delete_blocked_by_pending_sync_all_batch(lc_seed, ok_purge):
    """sync-all 批量(source_id IS NULL)在途 → 任何源删除都 409(保守安全)。"""
    await _seed_source("e18-a")
    factory = app.state.session_factory
    async with factory() as session:
        session.add(SyncRequest(source_id=None, status="pending", triggered_by="e18"))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete("/api/admin/data-sources/e18-a", headers=lc_seed)
    assert resp.status_code == 409


async def test_delete_blocked_by_running_sync_run(lc_seed, ok_purge):
    """该源有 running SyncRun(实际执行中)→ 删除 409。"""
    await _seed_source("e18-a")
    factory = app.state.session_factory
    async with factory() as session:
        session.add(SyncRun(source_id="e18-a", status="running", triggered_by="e18"))
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.delete("/api/admin/data-sources/e18-a", headers=lc_seed)
    assert resp.status_code == 409


async def test_sync_allowed_again_after_collision_cleared(lc_seed, ok_purge):
    """碰撞解除(请求终态)后删除可正常受理——阻止是瞬时的,不是永久锁。"""
    await _seed_source("e18-a")
    factory = app.state.session_factory
    async with factory() as session:
        session.add(SyncRequest(source_id="e18-a", status="pending", triggered_by="e18"))
        await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        blocked = await client.delete("/api/admin/data-sources/e18-a", headers=lc_seed)
    assert blocked.status_code == 409

    async with factory() as session:
        req = (
            await session.execute(select(SyncRequest).where(SyncRequest.source_id == "e18-a"))
        ).scalar_one()
        req.status = "done"
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ok = await client.delete("/api/admin/data-sources/e18-a", headers=lc_seed)
    assert ok.status_code == 202
    assert await _lifecycle_of("e18-a") == "delete_requested"


# --------------------------------------------------------------------------- #
# deny-by-default:删除流程中的源不得启动新 sync
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("state", "label"),
    [
        ("delete_requested", "删除已受理"),
        ("deleting", "删除执行中"),
        ("delete_failed", "删除失败"),
        ("some_future_state", "未来未知状态"),
    ],
)
async def test_sync_denied_by_lifecycle(lc_seed, ok_purge, state, label):
    """非 ACTIVE 持久化状态(含未知)→ 手动 sync 409。"""
    await _seed_source("e18-a", lifecycle_state=state)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/admin/data-sources/e18-a/sync", headers=lc_seed)
    assert resp.status_code == 409, f"state={state} 必须拒绝手动同步"


async def test_sync_all_excludes_non_eligible_sources(lc_seed, ok_purge):
    """sync-all 批量不含删除在途/失败/未知状态源;正常源保留。"""
    await _seed_source("e18-ok")
    await _seed_source("e18-del", lifecycle_state="deleting")
    await _seed_source("e18-fail", lifecycle_state="delete_failed")
    await _seed_source("e18-future", lifecycle_state="some_future_state")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/admin/data-sources/sync-all", headers=lc_seed)
    assert resp.status_code == 202
    ids = set(resp.json()["source_ids"])
    assert "e18-ok" in ids
    assert "e18-del" not in ids
    assert "e18-fail" not in ids
    assert "e18-future" not in ids

    # 测试收尾:把本测试创建的 NULL 批量请求置终态,避免在途行污染
    # 同库后续测试的删除碰撞检查(NULL 批量会 409 任何源的删除)
    await _close_request(resp.json().get("request_id"))


async def _close_request(request_id: int | None) -> None:
    """把本测试产生的交接请求标记终态(测试卫生,不影响生产代码)。"""
    if request_id is None:
        return
    factory = app.state.session_factory
    async with factory() as session:
        req = await session.get(SyncRequest, request_id)
        if req is not None:
            req.status = "done"
            await session.commit()


async def test_sync_config_universe_excludes_non_eligible(lc_seed, ok_purge):
    """sync.py 配置宇宙(_load_configs_from_db)排除非 ACTIVE 生命周期状态。"""
    from scripts.sync import _load_configs_from_db

    await _seed_source("e18-ok")
    await _seed_source("e18-del", lifecycle_state="deleting")
    await _seed_source("e18-future", lifecycle_state="some_future_state")

    configs = await _load_configs_from_db(app.state.session_factory)
    ids = {c.id for c in configs}
    assert "e18-ok" in ids
    assert "e18-del" not in ids
    assert "e18-future" not in ids


# --------------------------------------------------------------------------- #
# 恢复语义 + 半态防护 + 源间隔离
# --------------------------------------------------------------------------- #


async def test_orphan_deleting_row_recovered_by_sweep(lc_seed, ok_purge):
    """崩溃恢复:行处于 DELETING(进程执行中崩溃遗留)→ sweep 重驱完成。

    这就是重启恢复语义:lifespan 启动 worker 后首轮 sweep 扫描全部在途行
    (DELETE_REQUESTED 与 DELETING),幂等 purge 收敛后删行。
    """
    await _seed_source("e18-a", lifecycle_state="deleting")
    factory = app.state.session_factory
    async with factory() as session:
        session.add(
            Document(
                content_hash=uuid.uuid4().hex,
                source_id="e18-a/doc1",
                source_type="github",
                product="p",
                title="t",
                url="https://example.com",
                metadata_={},
                branch="",
                chunk_count=2,
            )
        )
        await session.commit()

    processed = await _process_deletions()
    assert processed == ["e18-a"]
    assert await _lifecycle_of("e18-a") is None  # 行已移除


async def test_purge_runs_before_row_delete_no_silent_half_state(lc_seed, monkeypatch):
    """半态防护:purge 执行时配置行仍在(先 purge 后删行);
    purge 失败 → 行保留 DELETE_FAILED(可重试),不是静默半态。"""
    import os

    import backend.services.source_deletion as sd

    await _seed_source("e18-a", lifecycle_state="delete_requested")

    row_seen_during_purge: list[str | None] = []

    def _purge_observes_then_fails(weaviate_url, class_name, prefix, ledger):
        # 线程池内(无事件循环):开独立同步 engine 读配置行,
        # 证明 purge 先于删行执行
        dsn = os.environ.get(
            "TEST_DATABASE_URL", app.state.settings.postgres_dsn
        ).replace("+asyncpg", "")
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        from backend.db.models import DataSource as DS

        eng = create_engine(dsn)
        try:
            with Session(eng) as s:
                row = s.get(DS, "e18-a")
                row_seen_during_purge.append(None if row is None else row.lifecycle_state)
        finally:
            eng.dispose()
        raise RuntimeError("purge 后仍有 3 个残留向量对象(source=e18-a)")

    monkeypatch.setattr(sd, "purge_source_corpus_sync", _purge_observes_then_fails)

    processed = await _process_deletions()
    assert processed == ["e18-a"]  # 认领了,失败落 DELETE_FAILED
    assert row_seen_during_purge == ["deleting"]  # purge 时行仍在(已认领)
    state = await _lifecycle_of("e18-a")
    assert state == "delete_failed"  # 行保留可重试,绝不假报成功


async def test_unrelated_source_unaffected_during_deletion(lc_seed, ok_purge):
    """源间隔离:A 删除在途不阻塞 B 的同步;C 的删除正常受理。

    (B 同步受理后自身处于 pending-sync 碰撞窗,此时删 B 会被 409 ——
    那是 pending sync vs delete 的正确语义,与 A 无关,故删除用 C 验证。)
    """
    await _seed_source("e18-a", lifecycle_state="deleting")
    await _seed_source("e18-b")
    await _seed_source("e18-c")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        sync_b = await client.post("/api/admin/data-sources/e18-b/sync", headers=lc_seed)
        del_c = await client.delete("/api/admin/data-sources/e18-c", headers=lc_seed)
    assert sync_b.status_code == 202
    assert del_c.status_code == 202
    processed = await _process_deletions()
    assert set(processed) == {"e18-a", "e18-c"}
    assert await _lifecycle_of("e18-a") is None
    assert await _lifecycle_of("e18-c") is None
    # B 的 pending 同步请求不受 A/C 删除影响(仍持久在交接队列)
    factory = app.state.session_factory
    async with factory() as session:
        req = (
            await session.execute(
                select(SyncRequest).where(SyncRequest.source_id == "e18-b")
            )
        ).scalar_one()
        assert req.status == "pending"
    # 测试卫生:置终态,不让在途请求泄漏给后续模块的碰撞检查
    await _close_request(req.id)


async def test_worker_sweep_and_lifecycle_smoke(lc_seed, ok_purge):
    """SourceDeletionWorker:_sweep 处理在途行;start/stop 幂等安全。"""
    import asyncio

    from backend.services.source_deletion import SourceDeletionWorker

    await _seed_source("e18-a", lifecycle_state="delete_requested")
    settings = app.state.settings
    worker = SourceDeletionWorker(
        app.state.session_factory, settings.weaviate_url, settings.weaviate_class_name
    )
    await worker._sweep()
    assert await _lifecycle_of("e18-a") is None

    # start/stop 生命周期:stop 未启动 worker 安全;启动后可取消
    await worker.stop()  # 未启动 → no-op
    worker.start()
    assert worker._task is not None
    await asyncio.sleep(0)
    await worker.stop()
    assert worker._task is None
