"""504 黄金事故回归(2026-09-02 生产事故)。

事故链(已实证):Admin 手动同步 → ``asyncio.create_task(_run())`` →
同步 ingest_all(CPU/GPU 重活,同步 Weaviate SDK + BGE embed)直接占用
uvicorn event loop → /health timeout → nginx upstream timeout → Admin/API 504。

本文件以三组实验形成证据链:

A(事故类别可检测性,旧行为对照组)
   同一 uvicorn 进程内 inline 阻塞 event loop 3s(事故同构),
   /health 1s 预算内必然超时 —— 证明 harness 能捕获「event loop 饥饿」
   这一 504 事故类别,而非只能测 trigger 端点快。

B(新执行面)
   同样的 CPU burn(真实单核打满 ~4s 子进程,非 sleep 桩)经
   ``launch_sync`` 交给独立执行面后,在线面 /health × 15 与轻量
   Admin 路由全部在 1s 预算内 200 —— NO TIMEOUT / NO EVENT LOOP
   STARVATION / NO 504 CLASS BEHAVIOR。

C(真实 backend app 面)
   对真实 ``backend.main.app`` 的 /health,在真实 burn 子进程运行期间
   反复探测,全部 200 且有界延迟。

约束:CPU burn 用时间盒循环(hashlib 单核),不依赖外部服务,
也不会把开发机打挂(单核、秒级)。
"""

import asyncio
import hashlib
import os
import socket
import sys
import textwrap
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.services import sync_executor
from backend.services.sync_executor import launch_sync

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
    """线程内 uvicorn 真实网络服务:/health + 旧行为路由 + 新执行面路由。"""
    burn_script = tmp_path / "burn_child.py"
    burn_script.write_text(_BURN_CHILD)

    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/admin/lightweight")
    async def lightweight():
        return {"items": []}  # 轻量 Admin API 代表路由(不触 DB/LLM)

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

    @app.post("/new-sync")
    async def new_sync():
        result = await launch_sync(
            None, argv=[sys.executable, str(burn_script), str(_BURN_SECONDS), str(tmp_path / "b")]
        )
        return {"status": result.state, "pid": result.pid}

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


def _wait_marker(marker: Path, want_done: bool, timeout: float) -> bool:
    target = Path(str(marker) + ".done") if want_done else marker
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if target.exists():
            return True
        time.sleep(0.05)
    return False


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


def test_new_executor_plane_keeps_online_plane_responsive(tiny_server, tmp_path):
    """实验 B:同样的 CPU burn 在独立执行面子进程运行时,
    在线面 /health × 15 与轻量 Admin 路由全部 200 且延迟有界。"""
    base = tiny_server
    marker = tmp_path / "b"

    # launch_sync 需要事件循环;asyncio.run 上下文内完成提交
    async def _submit():
        return await launch_sync(
            None,
            argv=[
                sys.executable,
                str(_burn_path(tmp_path)),
                str(_BURN_SECONDS),
                str(marker),
            ],
        )

    proc_info = asyncio.run(_submit())
    assert proc_info.state == "accepted"
    assert _wait_marker(marker, want_done=False, timeout=5), "burn 子进程未启动"
    # 子进程仍在跑(独立执行面真实承载重活,而非瞬时退出)
    os.kill(proc_info.pid, 0)  # 进程存活(不存在则 ProcessLookupError)

    latencies: list[float] = []
    with httpx.Client(timeout=2) as c:
        for _ in range(15):
            t0 = time.monotonic()
            r = c.get(f"{base}/health", timeout=1.0)
            latencies.append(time.monotonic() - t0)
            assert r.status_code == 200
        r = c.get(f"{base}/api/admin/lightweight", timeout=1.0)
        assert r.status_code == 200
    assert max(latencies) < 1.0  # NO TIMEOUT,有界延迟

    # 子进程跑完退出后,在线面仍然健康(执行面退出不波及在线面)。
    # 提交用的 asyncio.run 循环已关闭,Process 句柄的退出码不再更新,
    # 完成证据用 done marker(burn 脚本最后一步写入),并清登记防串扰。
    assert _wait_marker(marker, want_done=True, timeout=10)
    sync_executor._inflight.pop("__all__", None)
    assert httpx.get(f"{base}/health", timeout=2.0).status_code == 200


def _burn_path(tmp_path: Path) -> Path:
    p = tmp_path / "burn_child2.py"
    p.write_text(_BURN_CHILD)
    return p


@pytest.mark.asyncio
async def test_real_backend_app_responsive_during_executor_burn(tmp_path):
    """实验 C:真实 backend.main.app 的 /health 在真实 burn 子进程运行
    期间(经 launch_sync 真实派生)全部 200 且延迟有界。"""
    from backend.main import app as backend_app

    marker = tmp_path / "rb"
    burn = tmp_path / "burn_real.py"
    burn.write_text(_BURN_CHILD)
    proc_info = await launch_sync(
        None, argv=[sys.executable, str(burn), str(_BURN_SECONDS), str(marker)]
    )
    assert proc_info.state == "accepted"
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not marker.exists():
        await asyncio.sleep(0.05)
    assert marker.exists()

    transport = ASGITransport(app=backend_app)
    latencies: list[float] = []
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(15):
            t0 = time.monotonic()
            resp = await client.get("/health", timeout=1.0)
            latencies.append(time.monotonic() - t0)
            assert resp.status_code == 200
    assert max(latencies) < 1.0

    # 收尾:等子进程退出,不留孤儿
    entry = sync_executor._inflight.get("__all__")
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if entry is not None and entry.returncode is not None:
            break
        await asyncio.sleep(0.1)
    assert entry is not None and entry.returncode == 0
    sync_executor._inflight.clear()
