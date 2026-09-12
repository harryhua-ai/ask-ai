"""#7 主机 / 系统运行时只读采集(Admin「系统运行时」分区唯一数据源)。

合同(frozen contract v162-i7)核心语义:
- **真实采集**:每项来自进程内只读收集(stdlib:/proc、platform、socket、
  shutil.disk_usage、os.getloadavg)或既有只读命令(nvidia-smi 结构化查询,
  与 backend.runtime.hardware.read_gpu_memory 同权限同方式),外加既有
  model-runtime 快照与 release 身份复用;**零写操作、零命令注入面**
  (nvidia-smi 参数为编译期字面量列表,subprocess 无 shell)。
- **显式不可得**:平台不可得的项(无 GPU、非 Linux 无 /proc、命令缺失)
  一律 available=False + 非空 reason,value 恒 None —— **绝不虚构/占位**;
  整段结构恒完整返回(HTTP 200),不因局部不可得降级为错误。
- **as_of**:每个观测四元组与每个 section 均携带采集时间(UTC ISO 8601)。
- **边界**:不暴露 env/secrets;不改变 /model-runtime 管理面语义(此处
  仅按需读 snapshot() 的真相面五键,只读直呈)。

测试 seam(全部模块级函数/常量,monkeypatch 即可,无需真实 GPU/proc):
``_read_file`` / ``_run_readonly`` / ``_hostname`` / ``_platform_facts`` /
``_loadavg`` / ``_disk_usage`` / ``_sleep`` / ``_now_iso`` / ``discover_gpus``。
"""

from __future__ import annotations

import logging
import os
import platform
import re
import shutil
import socket
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.release import get_release_identity
from backend.runtime.hardware import discover_gpus, normalize_gpu_uuid

logger = logging.getLogger(__name__)

_NVIDIA_SMI_TIMEOUT_SECONDS = 10
_CPU_SAMPLE_INTERVAL_SECONDS = 0.1  # /proc/stat 双采样间隔(只读,轻量)

# 部署卷 = backend 包所在卷(生产镜像 WORKDIR=/app → 观测 /app 部署卷)。
_DISK_TARGET = Path(__file__).resolve().parent.parent

# 单次全卡结构化查询(不使用 --id,同 hardware.py REV3 身份契约;全部只读字段)
_NVIDIA_SMI_QUERY_ARGS = [
    "nvidia-smi",
    (
        "--query-gpu=index,uuid,name,driver_version,utilization.gpu,"
        "memory.used,memory.free,memory.total,temperature.gpu"
    ),
    "--format=csv,noheader,nounits",
]
_NVIDIA_SMI_HEADER_ARGS = ["nvidia-smi"]


# ================================ 观测原语 ================================


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def _obs(value: Any, *, as_of: str, reason: str | None = None) -> dict[str, Any]:
    """观测四元组:available/value/reason/as_of。不可得 → value 恒 None。"""
    available = reason is None
    return {
        "available": available,
        "value": value if available else None,
        "reason": reason,
        "as_of": as_of,
    }


def _unavail(reason: str, *, as_of: str) -> dict[str, Any]:
    return _obs(None, as_of=as_of, reason=reason)


# ============================ 采集 seam(可 mock) ============================


def _read_file(path: str) -> str | None:
    """只读文件;不可读 → None(不抛出)。"""
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def _run_readonly(args: list[str]) -> _CmdResult:
    """运行只读命令(无 shell、固定参数列表、带超时);失败封装为不 OK 结果。"""
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=_NVIDIA_SMI_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        return _CmdResult(ok=False, error=f"{args[0]} 不可执行(未安装)")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _CmdResult(ok=False, error=f"{args[0]} 执行失败({exc.__class__.__name__})")
    if proc.returncode != 0:
        return _CmdResult(
            ok=False,
            error=f"{args[0]} 退出码 {proc.returncode}:{proc.stderr.strip()[:200]}",
        )
    return _CmdResult(ok=True, stdout=proc.stdout)


def _hostname() -> str:
    return socket.gethostname()


def _loadavg() -> tuple[float, float, float]:
    return os.getloadavg()


def _disk_usage(path: Path):
    return shutil.disk_usage(path)


def _platform_facts() -> tuple[str, str, str]:
    """(system, kernel_release, machine)——pytest seam,tests 打此处。"""
    return platform.system(), platform.release(), platform.machine()


class _CmdResult:
    """只读命令结果封装(ok=False 时 error 说明原因,绝不抛出)。"""

    __slots__ = ("error", "ok", "stdout")

    def __init__(self, *, ok: bool, stdout: str = "", error: str | None = None):
        self.ok = ok
        self.stdout = stdout
        self.error = error


# ================================ host 段 ================================


def _collect_host(*, as_of: str) -> dict[str, Any]:
    hostname = _try_hostname(as_of)
    system, release, machine = _platform_facts_safe()
    return {
        "as_of": as_of,
        "hostname": hostname,
        "os": _obs(
            " ".join(x for x in (system, release, machine) if x) or None,
            as_of=as_of,
            reason=None if (system or release) else "平台信息不可得(platform 为空)",
        ),
        "kernel": _kernel_obs(release, as_of),
        "uptime_seconds": _collect_uptime(as_of=as_of),
    }


def _try_hostname(as_of: str) -> dict[str, Any]:
    try:
        value = _hostname().strip()
    except OSError as exc:
        return _unavail(f"hostname 采集失败({exc.__class__.__name__})", as_of=as_of)
    if not value:
        return _unavail("hostname 为空", as_of=as_of)
    return _obs(value, as_of=as_of)


def _platform_facts_safe() -> tuple[str, str, str]:
    try:
        return _platform_facts()
    except Exception:  # noqa: BLE001 - platform 兜底:采集面永不抛错,只显式不可得
        return ("", "", "")


def _kernel_obs(release: str, as_of: str) -> dict[str, Any]:
    if not release:
        return _unavail("内核版本不可得(platform.release 为空)", as_of=as_of)
    # Linux:release 即内核版本;Darwin:release 亦为内核版本(xnu)
    return _obs(release, as_of=as_of)


def _collect_uptime(*, as_of: str) -> dict[str, Any]:
    # 首选 Linux /proc/uptime;其余平台尽力而为(sysctl boottime),再不可得 → 显式不可得
    data = _read_file("/proc/uptime")
    if data:
        try:
            return _obs(int(float(data.split()[0])), as_of=as_of)
        except (ValueError, IndexError):
            logger.debug("/proc/uptime 解析失败,回退 sysctl")
    boot = _run_readonly(["sysctl", "-n", "kern.boottime"])
    if boot.ok:
        m = re.search(r"sec\s*=\s*(\d+)", boot.stdout)
        if m:
            return _obs(max(0, int(time.time()) - int(m.group(1))), as_of=as_of)
    return _unavail("uptime 不可得(需 Linux /proc/uptime,当前平台无此接口)", as_of=as_of)


# ============================== resources 段 ==============================


def _parse_meminfo_kb(data: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for line in data.splitlines():
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        parts = rest.split()
        if parts and parts[0].isdigit():
            out[key.strip()] = int(parts[0])
    return out


def _cpu_times(data: str) -> tuple[int, int] | None:
    """解析 /proc/stat 首行 → (idle_all=idle+iowait, total)。"""
    for line in data.splitlines():
        if line.startswith("cpu "):
            parts = line.split()[1:]
            try:
                values = [int(x) for x in parts]
            except ValueError:
                return None
            if len(values) < 5:
                return None
            return values[3] + values[4], sum(values)
    return None


def _collect_cpu_utilization(*, as_of: str) -> dict[str, Any]:
    reason = "CPU 利用率需 Linux /proc/stat 双采样(当前平台不可得)"
    raw1 = _read_file("/proc/stat")
    t1 = _cpu_times(raw1) if raw1 else None
    if t1 is None:
        return _unavail(reason, as_of=as_of)
    _sleep(_CPU_SAMPLE_INTERVAL_SECONDS)
    raw2 = _read_file("/proc/stat")
    t2 = _cpu_times(raw2) if raw2 else None
    if t2 is None:
        return _unavail(reason, as_of=as_of)
    d_idle = t2[0] - t1[0]
    d_total = t2[1] - t1[1]
    if d_total <= 0 or d_idle < 0:
        return _unavail("CPU 利用率采样增量无效(/proc/stat 计数器异常)", as_of=as_of)
    return _obs(round(100.0 * (1 - d_idle / d_total), 1), as_of=as_of)


def _collect_memory(*, as_of: str) -> dict[str, Any]:
    data = _read_file("/proc/meminfo")
    if not data:
        reason = "内存水位需 Linux /proc/meminfo(当前平台不可得)"
        return {
            "memory_total_mb": _unavail(reason, as_of=as_of),
            "memory_used_mb": _unavail(reason, as_of=as_of),
            "memory_available_mb": _unavail(reason, as_of=as_of),
            "swap_total_mb": _unavail(reason, as_of=as_of),
            "swap_used_mb": _unavail(reason, as_of=as_of),
        }
    info = _parse_meminfo_kb(data)
    total_kb = info.get("MemTotal")
    avail_kb = info.get("MemAvailable")
    if total_kb is None or avail_kb is None:
        reason = "/proc/meminfo 缺少 MemTotal/MemAvailable 字段"
        return {
            "memory_total_mb": _unavail(reason, as_of=as_of),
            "memory_used_mb": _unavail(reason, as_of=as_of),
            "memory_available_mb": _unavail(reason, as_of=as_of),
            "swap_total_mb": _unavail(reason, as_of=as_of),
            "swap_used_mb": _unavail(reason, as_of=as_of),
        }
    swap_total_kb = info.get("SwapTotal", 0)
    swap_free_kb = info.get("SwapFree", 0)
    return {
        "memory_total_mb": _obs(total_kb // 1024, as_of=as_of),
        # used = total - available(Linux 惯例,含可回收缓存口径)
        "memory_used_mb": _obs((total_kb - avail_kb) // 1024, as_of=as_of),
        "memory_available_mb": _obs(avail_kb // 1024, as_of=as_of),
        # swap 未启用是事实(SwapTotal=0),不是不可得
        "swap_total_mb": _obs(swap_total_kb // 1024, as_of=as_of),
        "swap_used_mb": _obs(max(0, swap_total_kb - swap_free_kb) // 1024, as_of=as_of),
    }


def _collect_disk(*, as_of: str) -> dict[str, Any]:
    path_obs = _obs(str(_DISK_TARGET), as_of=as_of)
    try:
        usage = _disk_usage(_DISK_TARGET)
    except OSError as exc:
        reason = f"磁盘用量采集失败({exc.__class__.__name__}:{_DISK_TARGET})"
        return {
            "disk_path": path_obs,
            "disk_total_gb": _unavail(reason, as_of=as_of),
            "disk_used_gb": _unavail(reason, as_of=as_of),
            "disk_free_gb": _unavail(reason, as_of=as_of),
            "disk_used_percent": _unavail(reason, as_of=as_of),
        }
    total_gb = round(usage.total / 2**30, 1)
    used_gb = round(usage.used / 2**30, 1)
    free_gb = round(usage.free / 2**30, 1)
    used_percent = round(100.0 * usage.used / usage.total, 1) if usage.total > 0 else None
    if used_percent is None:
        pct_obs = _unavail("磁盘总量为 0,占比不可计算", as_of=as_of)
    else:
        pct_obs = _obs(used_percent, as_of=as_of)
    return {
        "disk_path": path_obs,
        "disk_total_gb": _obs(total_gb, as_of=as_of),
        "disk_used_gb": _obs(used_gb, as_of=as_of),
        "disk_free_gb": _obs(free_gb, as_of=as_of),
        "disk_used_percent": pct_obs,
    }


def _collect_resources(*, as_of: str) -> dict[str, Any]:
    data = _read_file("/proc/cpuinfo")
    cpu_model: dict[str, Any]
    if data:
        model = None
        for line in data.splitlines():
            if line.startswith("model name") and ":" in line:
                model = line.split(":", 1)[1].strip()
                break
        cpu_model = (
            _obs(model, as_of=as_of)
            if model
            else _unavail("/proc/cpuinfo 无 model name 字段", as_of=as_of)
        )
    else:
        cpu_model = _unavail("CPU 型号需 Linux /proc/cpuinfo(当前平台不可得)", as_of=as_of)
    cores = os.cpu_count()
    # Role A 窄加固:os.cpu_count() 理论可返回 None(文档允许),此时按
    # 不可得语义表达,维持 available=True ⇒ value 非空 的形状不变量。
    cpu_cores_obs = (
        _obs(cores, as_of=as_of)
        if cores is not None
        else _unavail("无法确定逻辑核数(os.cpu_count() 返回 None)", as_of=as_of)
    )
    loadavg: dict[str, Any]
    try:
        l1, l5, l15 = _loadavg()
        loadavg = {
            "loadavg_1m": _obs(l1, as_of=as_of),
            "loadavg_5m": _obs(l5, as_of=as_of),
            "loadavg_15m": _obs(l15, as_of=as_of),
        }
    except (OSError, AttributeError):
        reason = "load average 在当前平台不可得"
        loadavg = {
            "loadavg_1m": _unavail(reason, as_of=as_of),
            "loadavg_5m": _unavail(reason, as_of=as_of),
            "loadavg_15m": _unavail(reason, as_of=as_of),
        }
    return {
        "as_of": as_of,
        "cpu_model": cpu_model,
        "cpu_logical_cores": cpu_cores_obs,
        "cpu_utilization_percent": _collect_cpu_utilization(as_of=as_of),
        **loadavg,
        **_collect_memory(as_of=as_of),
        **_collect_disk(as_of=as_of),
    }


# ============================= accelerator 段 =============================

_SMI_FIELDS_PER_LINE = 9  # index,uuid,name,driver_version,util,used,free,total,temp


def _smi_int(raw: str) -> int | None:
    try:
        return int(raw)
    except ValueError:
        return None  # 如 "[Not Supported]" → 该字段如实不可得,不虚构


def _parse_smi_gpus(stdout: str, *, as_of: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != _SMI_FIELDS_PER_LINE:
            continue
        entries.append(
            {
                "index": _smi_int(parts[0]),
                "uuid": normalize_gpu_uuid(parts[1]) or None,
                "name": parts[2] or None,
                "driver_version": parts[3] or None,
                "utilization_percent": _smi_int(parts[4]),
                "memory_used_mb": _smi_int(parts[5]),
                "memory_free_mb": _smi_int(parts[6]),
                "memory_total_mb": _smi_int(parts[7]),
                "temperature_c": _smi_int(parts[8]),
                "as_of": as_of,
            }
        )
    return entries


def _merge_torch_gpus(entries: list[dict[str, Any]], *, as_of: str) -> list[dict[str, Any]]:
    """nvidia-smi 缺失时以 torch 发现结果兜底(设备存在是事实;
    利用率/温度/显存占用等 nvidia-smi 专属字段如实置 None,不虚构)。"""
    try:
        torch_gpus = discover_gpus()
    except Exception as exc:  # noqa: BLE001 - torch 缺失/异常不拖垮端点,只降级
        logger.debug("torch GPU 发现失败(%s)", exc)
        return entries
    if not torch_gpus:
        return entries
    by_uuid = {e["uuid"]: e for e in entries if e["uuid"]}
    merged = list(entries)
    for g in torch_gpus:
        if g.uuid in by_uuid:
            existing = by_uuid[g.uuid]
            if existing["memory_total_mb"] is None:
                existing["memory_total_mb"] = g.total_memory_mb
            continue
        merged.append(
            {
                "index": g.index,
                "uuid": g.uuid,
                "name": g.name,
                "driver_version": None,
                "utilization_percent": None,
                "memory_used_mb": None,
                "memory_free_mb": None,
                "memory_total_mb": g.total_memory_mb,
                "temperature_c": None,
                "as_of": as_of,
            }
        )
    return merged


def _collect_accelerator(*, as_of: str) -> dict[str, Any]:
    query = _run_readonly(_NVIDIA_SMI_QUERY_ARGS)
    header = _run_readonly(_NVIDIA_SMI_HEADER_ARGS)
    gpus = _parse_smi_gpus(query.stdout, as_of=as_of) if query.ok else []

    driver = _unavail("驱动版本需 nvidia-smi(当前不可得)", as_of=as_of)
    cuda = _unavail("CUDA 版本需 nvidia-smi(当前不可得)", as_of=as_of)
    if header.ok:
        m_driver = re.search(r"Driver Version:\s*(\S+)", header.stdout)
        m_cuda = re.search(r"CUDA Version:\s*(\S+)", header.stdout)
        if m_driver:
            driver = _obs(m_driver.group(1), as_of=as_of)
        if m_cuda:
            cuda = _obs(m_cuda.group(1), as_of=as_of)

    gpus = _merge_torch_gpus(gpus, as_of=as_of)
    smi_error = query.error or header.error
    if gpus:
        return {
            "as_of": as_of,
            "available": True,
            "reason": None,
            "driver_version": driver,
            "cuda_version": cuda,
            "gpus": gpus,
            "nvidia_smi_error": smi_error,
        }
    # 无任何 GPU 证据:按证据链合成显式原因(非错误、非空壳)
    if not query.ok and not header.ok:
        reason = f"未发现 NVIDIA GPU(nvidia-smi 不可用:{smi_error};torch CUDA 亦不可见)"
    elif query.ok:
        reason = "nvidia-smi 可用但未报告任何 GPU,torch CUDA 亦不可见"
    else:
        reason = f"未发现 NVIDIA GPU(查询失败:{smi_error};torch CUDA 亦不可见)"
    return {
        "as_of": as_of,
        "available": False,
        "reason": reason,
        "driver_version": driver,
        "cuda_version": cuda,
        "gpus": [],
        "nvidia_smi_error": smi_error,
    }


# =============================== service 段 ===============================

_MODEL_RUNTIME_SNAPSHOT_KEYS = (
    "devices",
    "policies",
    "shared_embedding_runtime",
    "runtime_plan",
    "capacity",
)


def _collect_service(*, model_runtime: Any, as_of: str) -> dict[str, Any]:
    # release 身份复用(与 /system/release、/health 同一进程级权威)
    try:
        rid = get_release_identity()
        release = _obs(
            {
                "version": rid.version,
                "git_sha": rid.git_sha,
                "built_at": rid.built_at,
                "app_mode": rid.app_mode,
                "image": rid.image,
                "ci_run_id": rid.ci_run_id,
                "source": rid.source,
            },
            as_of=as_of,
        )
    except Exception as exc:  # noqa: BLE001 - release 兜底:身份缺失显式不可得,不 500
        release = _unavail(f"release 身份加载失败({exc.__class__.__name__})", as_of=as_of)

    # health:本端点可响应即进程存活事实,与 /health 的 status="ok" 同源语义
    health = _obs("ok", as_of=as_of)

    if model_runtime is None:
        model_runtime_obs = _unavail(
            "模型运行时未就绪(本进程未初始化 model runtime)", as_of=as_of
        )
    else:
        try:
            snap = model_runtime.snapshot()
        except Exception as exc:  # noqa: BLE001 - 快照失败显式不可得,不 500
            model_runtime_obs = _unavail(
                f"模型运行时快照失败({exc.__class__.__name__})", as_of=as_of
            )
        else:
            model_runtime_obs = _obs(
                {k: snap.get(k) for k in _MODEL_RUNTIME_SNAPSHOT_KEYS}, as_of=as_of
            )
    return {"as_of": as_of, "health": health, "release": release, "model_runtime": model_runtime_obs}


# ================================ 聚合入口 ================================

def collect_system_runtime(*, model_runtime: Any = None) -> dict[str, Any]:
    """系统运行时只读快照(GET /api/admin/system/runtime 响应)。

    ``model_runtime``:``request.app.state.model_runtime``(可为 None,
    此时 service.model_runtime 显式 unavailable)。全程只读、恒 200 可序列化。
    """
    as_of = _now_iso()
    return {
        "as_of": as_of,
        "host": _collect_host(as_of=as_of),
        "resources": _collect_resources(as_of=as_of),
        "accelerator": _collect_accelerator(as_of=as_of),
        "service": _collect_service(model_runtime=model_runtime, as_of=as_of),
    }
