"""真实执行设备发现(CPU / GPU / 稳定身份 / 显存容量观测)。

设计要点(Discovery 报告 §HARDWARE_DISCOVERY;REV3 GPU UUID 归一化):
- GPU 稳定身份采用**规范形(canonical)= ``GPU-<uuid>``**:torch 的
  ``get_device_properties().uuid`` 产出无前缀裸形(如 ``3caad314-…``),
  nvidia-smi 产出/接受规范形(如 ``GPU-3caad314-…``)。discover_gpus() 在
  发现期即归一化为规范形,使 torch 发现、持久化策略、容量观测、Admin 呈现、
  CUDA index 投影共享同一身份;``normalize_gpu_uuid`` 保证旧裸形输入同样可解析
  (向后兼容);非 ``GPU-`` 前缀形态(如 MIG-…)原样保留;
- 显存占用读数:容器内 ``nvidia-smi --query-gpu=... --format=csv`` 结构化字段,
  **单次全卡查询 + 本地身份匹配**(不使用 ``--id``,杜绝驱动对 UUID 形态的
  接受差异);请求了具体身份而该卡不可见 → None(绝不回退到其他物理卡);
- 全部只读,绝不构造模型副本、绝不触碰第三方负载。
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_NVIDIA_SMI_TIMEOUT_SECONDS = 10

_UUID_PREFIX = "GPU-"


def normalize_gpu_uuid(raw: str | None) -> str | None:
    """归一化 GPU 身份为规范形 ``GPU-<uuid>``(REV3 单一稳定身份)。

    同一物理卡的 torch 裸形与 nvidia-smi 规范形归一化后一致;
    空串/None → None;非 ``GPU-`` 前缀形态(如 MIG-…)原样保留。
    """
    if raw is None:
        return None
    bare = raw.strip()
    bare = bare.removeprefix(_UUID_PREFIX)
    if not bare:
        return None
    if bare.startswith("MIG-"):
        return bare  # 非 GPU- 前缀身份(MIG 实例等)不在归一化范围,原样保留
    return f"{_UUID_PREFIX}{bare}"


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
    """GPU 执行设备(uuid 为规范形稳定物理身份;index 为运行期 CUDA 投影)。"""

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
    """发现 NVIDIA GPU(torch;无 GPU/不可用 → 空列表,不抛错)。

    uuid 以规范形(GPU-<uuid>)暴露:与持久化策略、nvidia-smi 观测、Admin
    呈现共用同一身份表示(REV3 身份契约)。
    """
    try:
        import torch
    except ImportError:  # pragma: no cover - torch 缺失属环境错误
        return []
    if not torch.cuda.is_available():
        return []
    devices: list[GpuDevice] = []
    for index in range(torch.cuda.device_count()):
        props = torch.cuda.get_device_properties(index)
        raw_uuid = str(getattr(props, "uuid", "") or "").strip()
        uuid = normalize_gpu_uuid(raw_uuid) or f"index-{index}"
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

    REV3 身份契约:单次**全卡**查询(不使用 ``--id``,驱动不再有机会拒绝
    某种 UUID 形态),随后按 ``normalize_gpu_uuid`` 归一化做**精确身份匹配**:

    - ``uuid=None`` → 默认(第一块)GPU;
    - 规范形(GPU-…)或等价 torch 裸形 → 同一物理卡的快照;
    - 请求了具体身份而卡不可见/未知 → **None(绝不回退到其他物理卡)**;
    - nvidia-smi 不可用/超时 → None(容量未知降级)。

    只读观测:绝不启动 GPU 计算进程。
    """
    canonical = normalize_gpu_uuid(uuid)
    args = [
        "nvidia-smi",
        "--query-gpu=uuid,memory.used,memory.free,memory.total",
        "--format=csv,noheader,nounits",
    ]
    try:
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=_NVIDIA_SMI_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("nvidia-smi 显存读数失败(%s):%s", canonical or "default", exc)
        return None
    if proc.returncode != 0:
        logger.warning(
            "nvidia-smi 显存读数失败(%s):%s", canonical or "default", proc.stderr.strip()[:200]
        )
        return None

    def _bare(value: str) -> str:
        value = value.strip()
        return value.removeprefix(_UUID_PREFIX)

    for line in proc.stdout.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 4:
            continue
        observed_uuid, used, free, total = parts
        if canonical is not None and _bare(observed_uuid) != _bare(canonical):
            continue  # 精确身份匹配:宁可不读,不读错卡
        try:
            return GpuMemorySnapshot(
                used_mb=int(used),
                free_mb=int(free),
                total_mb=int(total),
            )
        except ValueError:
            return None
    if canonical is not None:
        logger.warning("nvidia-smi 未包含请求的 GPU 身份(%s),按不可见降级", canonical)
    return None
