"""真实执行设备发现(CPU / GPU / 稳定身份 / 显存容量观测)。

设计要点(Discovery 报告 §HARDWARE_DISCOVERY):
- GPU 稳定身份 = torch 提供的 UUID(零新增依赖);CUDA index 仅为运行期投影;
- 显存占用读数:容器内 ``nvidia-smi --query-gpu=... --format=csv`` 结构化字段
  (镜像内已存在;NVML/pynvml 为后续可选升级,本模块接口不变);
- 全部只读,绝不构造模型副本、绝不触碰第三方负载。
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_NVIDIA_SMI_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class CpuDevice:
    """CPU 执行设备(足以呈现有意义的设备名)。"""

    model: str
    logical_cores: int
    total_memory_mb: int

    @property
    def label(self) -> str:
        return f"CPU · {self.model}"


@dataclass(frozen=True)
class GpuDevice:
    """GPU 执行设备(UUID 为稳定物理身份;index 为运行期 CUDA 投影)。"""

    index: int
    uuid: str
    name: str
    total_memory_mb: int

    @property
    def label(self) -> str:
        return f"{self.name} · GPU {self.index}"


@dataclass(frozen=True)
class GpuMemorySnapshot:
    """单卡显存快照(MiB;used 含进程外全部占用)。"""

    used_mb: int
    free_mb: int
    total_mb: int


def discover_cpu() -> CpuDevice:
    """发现 CPU:型号(/proc/cpuinfo)、逻辑核数、总内存。"""
    model = "CPU"
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("model name") and ":" in line:
                    model = line.split(":", 1)[1].strip()
                    break
    except OSError:
        logger.debug("/proc/cpuinfo 不可读,使用默认 CPU 标识")
    cores = os.cpu_count() or 1
    total_memory_mb = 0
    try:
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    total_memory_mb = int(line.split()[1]) // 1024
                    break
    except (OSError, ValueError):
        logger.debug("/proc/meminfo 不可读,内存留空")
    return CpuDevice(model=model, logical_cores=cores, total_memory_mb=total_memory_mb)


def discover_gpus() -> list[GpuDevice]:
    """发现 NVIDIA GPU(torch;无 GPU/不可用 → 空列表,不抛错)。"""
    try:
        import torch
    except ImportError:  # pragma: no cover - torch 缺失属环境错误
        return []
    if not torch.cuda.is_available():
        return []
    devices: list[GpuDevice] = []
    for index in range(torch.cuda.device_count()):
        props = torch.cuda.get_device_properties(index)
        uuid = str(getattr(props, "uuid", "") or f"index-{index}")
        devices.append(
            GpuDevice(
                index=index,
                uuid=uuid,
                name=props.name,
                total_memory_mb=int(props.total_memory // (1024 * 1024)),
            )
        )
    return devices


def read_gpu_memory(uuid: str | None = None) -> GpuMemorySnapshot | None:
    """读显存快照(nvidia-smi 结构化字段;失败 → None,不臆造数值)。

    uuid 为 None 时读默认(第一块)GPU。只读观测:绝不启动 GPU 计算进程。
    nvidia-smi 不可用/超时/无此卡一律返回 None,由调用方按「容量未知」降级。
    """
    args = [
        "nvidia-smi",
        "--query-gpu=uuid,memory.used,memory.free,memory.total",
        "--format=csv,noheader,nounits",
    ]
    if uuid:
        args.append(f"--id={uuid}")
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=_NVIDIA_SMI_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("nvidia-smi 显存读数失败(%s):%s", uuid or "default", exc)
        return None
    if proc.returncode != 0:
        logger.warning(
            "nvidia-smi 显存读数失败(%s):%s", uuid or "default", proc.stderr.strip()[:200]
        )
        return None
    for line in proc.stdout.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 4:
            continue
        observed_uuid, used, free, total = parts
        # 指定 uuid 时做身份匹配(完整或前缀形态);未指定时接受第一行
        if uuid and not (
            observed_uuid == uuid or uuid.startswith(observed_uuid) or observed_uuid.endswith(uuid)
        ):
            continue
        try:
            return GpuMemorySnapshot(
                used_mb=int(used),
                free_mb=int(free),
                total_mb=int(total),
            )
        except ValueError:
            return None
    return None
