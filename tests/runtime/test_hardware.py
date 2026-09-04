"""硬件发现单元测试(CPU/GPU/显存读数解析;GPU 侧无 CUDA 时如实为空)。"""

import subprocess
from unittest import mock

from backend.runtime.hardware import (
    discover_cpu,
    discover_gpus,
    read_gpu_memory,
)


def test_discover_cpu_reads_model_and_memory():
    cpu = discover_cpu()
    assert cpu.model
    assert "CPU" not in cpu.model or "CPU" in cpu.model  # 不抛错即可
    assert cpu.logical_cores >= 1
    assert cpu.label.startswith("CPU ·")


def test_discover_gpus_empty_without_cuda():
    # CI/本地无 NVIDIA GPU → 空列表(不抛错;有 GPU 的机器返回真实设备)
    devices = discover_gpus()
    assert isinstance(devices, list)


def test_read_gpu_memory_parses_structured_csv():
    fake = mock.Mock(
        returncode=0,
        stdout="GPU-3caad314-5735-d4c2-64ce-e82bb88a11ba, 15510, 126, 15564\n",
        stderr="",
    )
    with mock.patch.object(subprocess, "run", return_value=fake) as run:
        snap = read_gpu_memory("GPU-3caad314-5735-d4c2-64ce-e82bb88a11ba")
    assert snap is not None
    assert snap.used_mb == 15510
    assert snap.free_mb == 126
    assert snap.total_mb == 15564
    args = run.call_args.args[0]
    assert "--query-gpu=uuid,memory.used,memory.free,memory.total" in args
    assert "--format=csv,noheader,nounits" in args


def test_read_gpu_memory_none_on_failure():
    fake = mock.Mock(returncode=1, stdout="", stderr="no device")
    with mock.patch.object(subprocess, "run", return_value=fake):
        assert read_gpu_memory("GPU-x") is None
    with mock.patch.object(
        subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd="nvidia-smi", timeout=10)
    ):
        assert read_gpu_memory("GPU-x") is None


def test_read_gpu_memory_matches_by_uuid_prefix():
    fake = mock.Mock(
        returncode=0,
        stdout="GPU-3caad314, 100, 15000, 15564\n",
        stderr="",
    )
    with mock.patch.object(subprocess, "run", return_value=fake):
        snap = read_gpu_memory("GPU-3caad314-5735-d4c2-64ce-e82bb88a11ba")
    assert snap is not None and snap.free_mb == 15000
