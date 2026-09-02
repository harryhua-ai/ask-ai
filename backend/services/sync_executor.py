"""独立同步执行面(SYNC EXECUTION PLANE)。

阶段9 冻结(P4 — Sync Must Not Block Online,2026-09-02 生产 504 事故):

    ONLINE PLANE(backend / uvicorn 进程)
        │  POST /data-sources/{id}/sync → trigger only,立即返回
        ▼
    launch_sync() ── create_subprocess_exec ──▶ SYNC EXECUTION PLANE
                                                scripts/sync.py 子进程
                                    (自带 engine / Weaviate client /
                                     BGE embedder 生命周期,与 sync-cron
                                     同一业务 runner)

设计要点
--------
- **detached 子进程**:`start_new_session=True`(POSIX setsid)使子进程
  脱离 backend 进程组/会话 —— backend web 进程重启、被 supervisor 以
  进程组信号终止,都不会级联杀掉已派生的同步任务(AC6)。
  同步子进程自身被 kill 后的自动恢复属于阶段⑩,不在本 Gate 范围。
- **无 shell**:参数以 argv 列表传递,source_id 不经 shell 解释,
  不引入注入面(AC13)。
- **环境继承**:子进程继承 backend 进程环境(POSTGRES_DSN / WEAVIATE_URL /
  HF 缓存 / GPU 设备),工作目录固定为仓库根(与 cron 入口一致,让
  ``load_dotenv()`` 与相对路径行为相同)。生产 compose 中 backend 与
  sync-cron 本就共用同一镜像 + 同一 anchor(同 env / 同卷 / 同 GPU 预留),
  因此 backend 容器内派生的子进程与 sync-cron 执行语义完全一致(AC14),
  无需新增部署面。
- **同一业务实现**:子进程运行 ``scripts/sync.py``,manual / scheduled /
  CLI 三个触发方收敛到同一 runner(§12 ONE BUSINESS SYNC IMPLEMENTATION)。
- **最低触发并发安全**(§11):同 key(单源 id 或 "__all__")已有存活
  子进程时返回 already-running,不重复派生,防止明显 duplicate-storm。
  进程登记在 backend 进程内存中 —— backend 重启后登记丢失、多副本部署
  的分布式去重属于阶段⑭,不在本 Gate。
- **可诊断性**(§17):派生时记录 trigger 时间 / source / pid / argv 到
  backend 日志;子进程 stdout/stderr 继承 backend 输出(docker logs /
  nohup 日志可见);同步结果按既有约定写 sync_log(前端 5s 轮询)。
"""

import asyncio
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# 仓库根(scripts/sync.py 所在);backend 以仓库布局运行(dev / 容器 WORKDIR 均如此)
REPO_ROOT = Path(__file__).resolve().parents[2]
SYNC_SCRIPT = REPO_ROOT / "scripts" / "sync.py"

# spawn 点提为模块属性,便于测试替换(不 patch 全局 asyncio)
_spawn = asyncio.create_subprocess_exec

# 全部启用的源(sync-all)。单源触发以 source_id 本身为 key。
_ALL_KEY = "__all__"

# key → 子进程句柄(仅存活意义;进程退出后 returncode 由事件循环回收更新)
_inflight: dict[str, asyncio.subprocess.Process] = {}


class SyncExecutorLaunchError(RuntimeError):
    """同步执行器进程启动失败(明确失败,绝不伪装成 accepted)。"""


@dataclass
class SyncLaunch:
    """launch_sync 结果:state ∈ {"accepted", "already-running"}。"""

    state: str
    pid: int | None
    argv: list[str]


def _registry_key(source_id: str | None) -> str:
    return source_id if source_id is not None else _ALL_KEY


def build_sync_argv(source_id: str | None, triggered_by: str = "manual") -> list[str]:
    """构造 sync 子进程 argv(列表逐元素传递,无 shell)。

    与 cron(``python3 scripts/sync.py``)、CLI 共用同一脚本入口;manual
    通过 ``--triggered-by manual`` 保留 sync_log 触发方语义(不带 --source
    的 sync-all 若不显式标记会被旧规则误记为 cron)。
    """
    argv = [sys.executable, str(SYNC_SCRIPT), "--triggered-by", triggered_by]
    if source_id is not None:
        argv += ["--source", source_id]
    return argv


async def launch_sync(
    source_id: str | None,
    *,
    triggered_by: str = "manual",
    argv: list[str] | None = None,
) -> SyncLaunch:
    """把一次同步提交给独立执行面:派生 detached sync 子进程,立即返回。

    Args:
        source_id: 单源同步的源 ID;``None`` 表示同步全部启用源(sync-all)。
        triggered_by: 写入 sync_log.triggered_by 的标记("manual"/"cron")。
        argv: 仅测试用 —— 注入 stub 子进程命令以验证隔离/生命周期属性;
            生产路径恒为 None(真实 argv 见 :func:`build_sync_argv`)。

    Returns:
        SyncLaunch(accepted 携带 pid;already-running 携带在跑 pid)。

    Raises:
        SyncExecutorLaunchError: 进程无法启动(spawn 失败)—— 调用方必须
            把它作为明确错误返回,不得伪装成 accepted。
    """
    key = _registry_key(source_id)
    prev = _inflight.get(key)
    if prev is not None and prev.returncode is None:
        logger.warning("同步已在独立执行面运行,跳过重复触发: key=%s pid=%s", key, prev.pid)
        return SyncLaunch(state="already-running", pid=prev.pid, argv=[])

    real_argv = argv if argv is not None else build_sync_argv(source_id, triggered_by)
    try:
        proc = await _spawn(
            *real_argv,
            cwd=str(REPO_ROOT),
            start_new_session=True,
        )
    except OSError as exc:
        raise SyncExecutorLaunchError(f"同步执行器进程启动失败: {exc}") from exc
    _inflight[key] = proc
    logger.warning(
        "同步任务已交独立执行面: key=%s pid=%d triggered_by=%s argv=%s",
        key,
        proc.pid,
        triggered_by,
        " ".join(real_argv),
    )
    return SyncLaunch(state="accepted", pid=proc.pid, argv=real_argv)
