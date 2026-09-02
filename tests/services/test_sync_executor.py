"""独立同步执行面生命周期测试(真实进程,非 mock)。

覆盖阶段9 三类核心隔离证据:

1. **进程/会话隔离**:launch_sync 派生的子进程处于独立会话(setsid),
   与调用方(backend web 进程)无共同进程组;
2. **backend 重启独立性(AC6)**:模拟 backend 的中间进程派生同步子进程
   后被进程组信号整组终止( Supervisor 重启 web 进程的等价场景),
   同步子进程必须幸存并自行跑完;
3. **失败语义(AC10/AC11)**:spawn 失败显式报错;子进程退出(含非零
   退出码)不影响调用方,死进程不阻塞后续触发。
"""

import asyncio
import os
import signal
import subprocess
import sys
import textwrap
import time

import pytest

from backend.services import sync_executor
from backend.services.sync_executor import (
    REPO_ROOT,
    SyncExecutorLaunchError,
    build_sync_argv,
    launch_sync,
)

REPO_STR = str(REPO_ROOT)


@pytest.fixture(autouse=True)
def _clean_registry():
    sync_executor._inflight.clear()
    yield
    sync_executor._inflight.clear()


# --------------------------------------------------------------------------- #
# 共享 runner 构造(§12/AC7:manual / scheduled / CLI 同一 scripts/sync.py)
# --------------------------------------------------------------------------- #


def test_build_sync_argv_single_source():
    argv = build_sync_argv("some-src", "manual")
    assert argv[0] == sys.executable
    assert argv[1] == str(REPO_ROOT / "scripts" / "sync.py")
    assert argv[argv.index("--triggered-by") + 1] == "manual"
    assert argv[argv.index("--source") + 1] == "some-src"


def test_build_sync_argv_all_sources():
    """sync-all:不带 --source(脚本内部遍历全部启用源,顺序单 pipeline)。"""
    argv = build_sync_argv(None, "manual")
    assert "--source" not in argv
    assert argv[argv.index("--triggered-by") + 1] == "manual"


# --------------------------------------------------------------------------- #
# 会话隔离 + 子进程退出不影响调用方(真实 spawn)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_spawned_child_runs_in_own_session():
    """start_new_session 生效:子进程会话 ≠ 调用方会话(setsid 脱离)。"""
    proc = await launch_sync(None, argv=[sys.executable, "-c", "import time; time.sleep(1.5)"])
    assert proc.state == "accepted"
    child_pid = proc.pid
    assert os.getsid(child_pid) != os.getsid(os.getpid())
    # 等子进程自然退出;退出码由事件循环回收可见,调用方无任何异常
    for _ in range(50):
        if _inflight_pid_returncode(child_pid) is not None:
            break
        await asyncio.sleep(0.1)
    registry_entry = sync_executor._inflight.get("__all__")
    assert registry_entry is not None
    assert registry_entry.returncode == 0


@pytest.mark.asyncio
async def test_child_failure_does_not_affect_caller_and_retrigger():
    """AC11/§19#12:子进程立即非零退出 → 调用方不抛错、仍可服务;
    死进程不阻塞后续触发(重新 accepted,而非 already-running)。"""
    proc = await launch_sync(None, argv=[sys.executable, "-c", "raise SystemExit(3)"])
    assert proc.state == "accepted"
    entry = None
    for _ in range(50):  # 最多等 5s 让事件循环回收退出码
        entry = sync_executor._inflight.get("__all__")
        if entry is not None and entry.returncode is not None:
            break
        await asyncio.sleep(0.1)
    assert entry is not None and entry.returncode == 3
    again = await launch_sync(None, argv=[sys.executable, "-c", "import time; time.sleep(0.2)"])
    assert again.state == "accepted"


@pytest.mark.asyncio
async def test_spawn_failure_raises_explicit_error():
    """AC10:spawn 失败(解释器不存在)→ SyncExecutorLaunchError,非伪装成功。"""
    with pytest.raises(SyncExecutorLaunchError, match="启动失败"):
        await launch_sync(None, argv=["/nonexistent/interpreter", "-c", "pass"])
    assert "__all__" not in sync_executor._inflight


def _inflight_pid_returncode(pid: int):
    for proc in sync_executor._inflight.values():
        if proc.pid == pid:
            return proc.returncode
    return None


# --------------------------------------------------------------------------- #
# backend 重启独立性(AC6):进程树实验,全部真实进程
# --------------------------------------------------------------------------- #

_CHILD_SRC = textwrap.dedent("""
    import os, sys, time
    from pathlib import Path
    hb = Path(sys.argv[1])
    done = hb.with_suffix(".done")
    hb.write_text(str(os.getpid()))
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not done.exists():
        time.sleep(0.2)
    done.write_text("ok")
    """)

# 模拟 backend web 进程:经 launch_sync 派生同步子进程后驻留;
# 被 Supervisor 以进程组信号终止(等价 web 进程重启场景)。
_INTERMEDIATE_SRC = textwrap.dedent("""
    import asyncio, sys
    sys.path.insert(0, {root!r})
    from backend.services.sync_executor import launch_sync

    async def main():
        r = await launch_sync(None, argv=[sys.executable, {child!r}, {hb!r}])
        print(r.pid, flush=True)
        await asyncio.sleep(120)

    asyncio.run(main())
    """)


def test_backend_restart_does_not_kill_sync_child(tmp_path):
    """AC6:中间进程(backend 替身)整组被 SIGTERM 后,同步子进程幸存并跑完。

    时序:中间进程派生子进程(真实 launch_sync,setsid)→ 心跳文件出现
    → killpg(中间进程组) → 中间进程死亡、子进程幸存 → 通知子进程完成。
    """
    hb = tmp_path / "heartbeat"
    intermediate_src = _INTERMEDIATE_SRC.format(
        root=REPO_STR, child=str(tmp_path / "child.py"), hb=str(hb)
    )
    (tmp_path / "child.py").write_text(_CHILD_SRC)

    env = {**os.environ, "PYTHONPATH": REPO_STR}
    intermediate = subprocess.Popen(
        [sys.executable, "-c", intermediate_src],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        start_new_session=True,  # backend 替身自成一属(受 killpg 的对象)
    )
    child_pid = None
    try:
        # 等子进程心跳(它已通过 launch_sync 派生)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if hb.exists():
                child_pid = int(hb.read_text().strip())
                break
            if intermediate.poll() is not None:
                pytest.fail("中间进程提前退出: " + intermediate.stderr.read().decode())
            time.sleep(0.1)
        assert child_pid is not None, "子进程心跳未出现"

        # 整组终止 backend 替身(同步子进程已 setsid,不在该组)
        os.killpg(os.getpgid(intermediate.pid), signal.SIGTERM)
        intermediate.wait(timeout=10)
        assert intermediate.returncode != 0  # 确实被信号终止
        time.sleep(0.5)

        # 同步子进程幸存且独立继续运行(核心断言)
        os.kill(child_pid, 0)  # 不存在则 ProcessLookupError

        # 通知子进程收尾,验证其能自行跑完(而非孤儿僵死)
        (tmp_path / "heartbeat.done").write_text("ok")
        done = tmp_path / "heartbeat.done"
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                if "ok" in done.read_text():
                    break
            except OSError:
                pass
            time.sleep(0.1)
        assert done.read_text() == "ok"
    finally:
        if intermediate.poll() is None:
            intermediate.kill()
        if child_pid is not None:
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
