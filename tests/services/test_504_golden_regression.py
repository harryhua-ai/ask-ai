"""504 黄金事故回归(2026-09-02 生产事故)。

事故链(已实证):Admin 手动同步 → ``asyncio.create_task(_run())`` →
同步 ingest_all(CPU/GPU 重活)直接占用 uvicorn event loop → /health
timeout → nginx upstream timeout → Admin/API 504。

本文件两组实验形成证据链:

A(事故类别可检测性,旧行为对照组)
   同一 uvicorn 进程内 inline 阻塞 event loop(事故同构),/health 1s
   预算内必然超时 —— 证明 harness 能捕获「event loop 饥饿」这一 504
   事故类别,而非只能测 trigger 端点快。

B(新执行面,真实链路)
   真实 backend.main.app + 真实 ``sync_requests`` 交接(POST /sync)+
   真实执行面循环(``scripts/sync_executor_loop.py`` 的 claim/drain/
   落账,runner 子进程为受控 CPU burn ~4s)在独立**进程**运行期间:
   - POST /sync 立即 202(accepted,无阻塞);
   - 交接行被真实领用置 running;
   - 真实 /health × 15 与真实 Admin API(GET /data-sources,DB 落地)
     全部 200 且延迟有界 —— NO TIMEOUT / NO EVENT LOOP STARVATION /
     NO 504 CLASS BEHAVIOR;
   - burn 结束后交接行落账 done(退出码 0),在线面依旧健康。
   容器级生命周期验收由真实 Docker compose 实验单独执行(见报告)。

约束:CPU burn 用时间盒循环(hashlib 单核),不依赖外部服务,不把
开发机打挂(单核、秒级)。
"""

import asyncio
import hashlib
import os
import socket
import sys
import textwrap
import threading
import time
import uuid

import httpx
import pytest
import pytest_asyncio
import uvicorn
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.auth.jwt import create_access_token, hash_password
from backend.config import load_settings
from backend.db.models import DataSource, SyncRequest, User
from backend.db.session import get_engine, get_session_factory, init_db
from backend.main import app

# burn 子进程:单核 hash 循环 burn N 秒(真实 CPU 负载,可观察启动/结束)
_BURN_CHILD = textwrap.dedent("""
    import hashlib, sys, time
    from pathlib import Path
    seconds, marker = float(sys.argv[1]), sys.argv[2]
    Path(marker).write_text("burning")
    n = 0
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        for _ in range(50_000):
            n = (n + int(hashlib.sha256(str(n).encode()).hexdigest()[:8], 16)) % (2**32)
    Path(marker + ".done").write_text("ok")
    """)

_BURN_SECONDS = 4.0
_OLD_BLOCK_SECONDS = 3.0


@pytest.fixture()
def tiny_server(tmp_path):
    """线程内 uvicorn 真实网络服务:/health + 旧行为路由(实验 A 专用)。"""
    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/old-sync")
    async def old_sync():
        # 2026-09-02 事故同构:trigger 立即返回,重型工作随后 inline
        # 阻塞同一 event loop(call_soon 回调在 selector 轮询前执行)。
        def _block() -> None:
            end = time.monotonic() + _OLD_BLOCK_SECONDS
            n = 0
            while time.monotonic() < end:
                for _ in range(50_000):
                    n = (n + int(hashlib.sha256(str(n).encode()).hexdigest()[:8], 16)) % (2**32)

        asyncio.get_running_loop().call_soon(_block)
        return {"status": "syncing"}

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    with httpx.Client(timeout=2) as c:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                if c.get(f"{base}/health").status_code == 200:
                    break
            except Exception:  # noqa: BLE001 - 就绪轮询吞传输异常后重试
                time.sleep(0.05)
        else:
            pytest.fail("tiny server 未就绪")
    yield base
    server.should_exit = True
    thread.join(timeout=5)


def test_old_inline_pattern_starves_event_loop(tiny_server):
    """实验 A:旧行为(inline 阻塞 loop)下 /health 1s 预算内必超时
    —— harness 对 504 事故类别具备检测能力(对照组)。"""
    base = tiny_server
    with httpx.Client(timeout=10) as c:
        r = c.post(f"{base}/old-sync")
        assert r.status_code == 200  # trigger 本身快速返回(与事故一致)
        with pytest.raises(httpx.TimeoutException):
            c.get(f"{base}/health", timeout=1.0)
    # loop 恢复后 /health 恢复正常(阻塞是暂态,非服务死亡)
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{base}/health", timeout=1.0).status_code == 200:
                return
        except Exception:  # noqa: BLE001 - 恢复轮询吞传输异常后重试
            time.sleep(0.2)
    pytest.fail("阻塞结束后 /health 未恢复")


# --------------------------------------------------------------------------- #
# 实验 B:真实交接队列 + 真实执行面循环 + 真实 backend app
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture()
async def _real_app_state():
    """ASGITransport 不触发 lifespan:手动初始化 /health 与 Admin 端点所需
    的 app.state(测试库)。"""
    app.state.settings = load_settings()
    dsn = os.environ.get("TEST_DATABASE_URL", app.state.settings.postgres_dsn)
    engine = get_engine(dsn)
    await init_db(engine)
    app.state.session_factory = get_session_factory(engine)
    return app.state.session_factory


async def _get_row(factory, request_id: int) -> SyncRequest:
    async with factory() as session:
        row = (
            await session.execute(select(SyncRequest).where(SyncRequest.id == request_id))
        ).scalar_one()
        session.expunge(row)
    return row


async def test_new_execution_plane_keeps_real_backend_responsive(
    _real_app_state, tmp_path, monkeypatch
):
    """实验 B:真实 POST /sync(交接)+ 真实执行面领用/落账 + 真实 CPU burn
    子进程独立进程运行期间,真实 backend 的 /health 与真实 Admin API 全部
    有界响应;交接行 running → done(退出码 0)。"""
    import scripts.sync_executor_loop as loop_mod
    from scripts.sync_executor_loop import drain_once

    factory = _real_app_state
    marker = tmp_path / "burn"

    # 执行面的 runner argv 指向受控 burn 子进程(claim/drain/落账逻辑全真实)
    def _fake_argv(source_id, triggered_by):
        return [sys.executable, "-c", _BURN_CHILD, str(_BURN_SECONDS), str(marker)]

    monkeypatch.setattr(loop_mod, "build_runner_argv", _fake_argv)

    # 前置清理 + Admin 用户 + 数据源
    user_id = uuid.uuid4()
    async with factory() as session:
        await session.execute(SyncRequest.__table__.delete())
        await session.commit()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email="burn@test.com",
                role="admin",
                password_hash=hash_password("pass123"),
            )
        )
        session.add(
            DataSource(
                id="burn-src",
                type="filesystem",
                product="test",
                enabled=True,
                config={"root_path": "/tmp"},
                sync_interval="24h",
            )
        )
        await session.commit()
    headers = {
        "Authorization": "Bearer "
        + create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    }

    async def _drive_until_done(timeout: float = 20.0) -> SyncRequest:
        """执行面驱动:领用并执行请求直到落账(真实 drain_once)。"""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            row = await _get_row(factory, request_id)
            if row.status in ("done", "failed"):
                return row
            await drain_once(factory)
            await asyncio.sleep(0.05)
        pytest.fail("执行面未在时限内完成请求")

    transport = ASGITransport(app=app)
    try:
        # 1) 触发:立即 202(在线面无任何重活,只写交接行)
        t0 = time.monotonic()
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/admin/data-sources/burn-src/sync", headers=headers, timeout=2.0
            )
        trigger_elapsed = time.monotonic() - t0
        assert resp.status_code == 202
        assert resp.json()["status"] == "accepted"
        assert trigger_elapsed < 0.5, f"trigger 耗时 {trigger_elapsed:.3f}s,不满足快速返回"
        request_id = resp.json()["request_id"]

        # 2) 启动执行面驱动任务;等 burn 子进程真正跑起来(burn 在独立进程)
        driver = asyncio.create_task(_drive_until_done())
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not marker.exists():
            await asyncio.sleep(0.05)
        assert marker.exists(), "burn 子进程未启动"
        row = await _get_row(factory, request_id)
        assert row.status == "running"  # 真实领用语义(claim_next 置位)

        # 3) burn 运行期间:真实 /health × 15 + 真实 Admin API × 5 全部有界
        latencies: list[float] = []
        admin_latencies: list[float] = []
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            for _ in range(15):
                t0 = time.monotonic()
                r = await client.get("/health", timeout=1.0)
                latencies.append(time.monotonic() - t0)
                assert r.status_code == 200
            for _ in range(5):
                t0 = time.monotonic()
                r = await client.get("/api/admin/data-sources", headers=headers, timeout=1.0)
                admin_latencies.append(time.monotonic() - t0)
                assert r.status_code == 200
        assert max(latencies) < 1.0, f"/health max={max(latencies):.3f}s(event loop 被占?)"
        assert max(admin_latencies) < 1.0, f"Admin API max={max(admin_latencies):.3f}s"

        # 4) burn 结束 → 真实落账 done(退出码 0),在线面依旧健康
        final_row = await driver
        assert final_row.status == "done"
        assert final_row.runner_exit_code == 0
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.get("/health", timeout=2.0)).status_code == 200
    finally:
        async with factory() as session:
            await session.execute(SyncRequest.__table__.delete())
            await session.execute(DataSource.__table__.delete().where(DataSource.id == "burn-src"))
            await session.execute(User.__table__.delete().where(User.id == user_id))
            await session.commit()
