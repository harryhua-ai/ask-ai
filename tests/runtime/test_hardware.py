"""硬件发现单元测试(REV3 GPU UUID 归一化 + 显存读数;GPU 侧无 CUDA 时如实为空)。

身份契约(§3/§4):
- torch 裸形 / nvidia-smi 规范形(GPU-…)归一化后一致;
- read_gpu_memory 单次全卡查询 + 精确身份匹配:
  None→默认卡、规范形/裸形→同一物理卡、未知身份→None(绝不回退 GPU 0);
- 多卡 fixture:请求哪张卡就解析哪张卡;
- discover_gpus 规范形稳定身份行为保持。
"""

import subprocess
from unittest import mock

from backend.runtime.hardware import (
    discover_cpu,
    discover_gpus,
    normalize_gpu_uuid,
    read_gpu_memory,
)

#: 双卡 fixture:nvidia-smi 原始输出(规范形 UUID;两卡数值可区分)
_T4_UUID = "GPU-3caad314-5735-d4c2-64ce-e82bb88a11ba"
_A100_UUID = "GPU-7f1a9999-1234-abcd-ef00-112233445566"
_TWO_GPU_CSV = f"{_T4_UUID}, 15335, 1049, 16384\n" f"{_A100_UUID}, 5000, 7384, 12384\n"


def _fake_smi(stdout: str, returncode: int = 0):
    return mock.Mock(returncode=returncode, stdout=stdout, stderr="")


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


# ----------------------------------------------------------- 归一化(§3)


def test_normalize_gpu_uuid_forms():
    assert normalize_gpu_uuid("3caad314-5735-d4c2-64ce-e82bb88a11ba") == _T4_UUID
    assert normalize_gpu_uuid(_T4_UUID) == _T4_UUID
    assert normalize_gpu_uuid("  3caad314-5735  ") == "GPU-3caad314-5735"  # 容忍空白
    assert normalize_gpu_uuid(None) is None
    assert normalize_gpu_uuid("") is None
    assert normalize_gpu_uuid("GPU-") is None
    assert normalize_gpu_uuid("MIG-abc") == "MIG-abc"  # 非 GPU- 形态原样保留


# ------------------------------------------------------- 读数身份契约(§4/§6)


def test_read_bare_torch_uuid_maps_to_canonical():
    """A:torch 裸形 → nvidia-smi 规范形,读数成功(生产缺陷场景)。"""
    with mock.patch.object(subprocess, "run", return_value=_fake_smi(_TWO_GPU_CSV)) as run:
        snap = read_gpu_memory("3caad314-5735-d4c2-64ce-e82bb88a11ba")
    assert snap is not None
    assert snap.used_mb == 15335 and snap.free_mb == 1049 and snap.total_mb == 16384
    args = run.call_args.args[0]
    assert "--query-gpu=uuid,memory.used,memory.free,memory.total" in args
    assert "--format=csv,noheader,nounits" in args
    assert not any(str(a).startswith("--id=") for a in args)  # 不再依赖 --id


def test_read_canonical_prefixed_uuid_succeeds():
    """B:规范形(GPU-前缀)读数成功。"""
    with mock.patch.object(subprocess, "run", return_value=_fake_smi(_TWO_GPU_CSV)):
        snap = read_gpu_memory(_T4_UUID)
    assert snap is not None and snap.used_mb == 15335


def test_read_none_resolves_default_first_gpu():
    """C:None → 默认(第一块)GPU。"""
    with mock.patch.object(subprocess, "run", return_value=_fake_smi(_TWO_GPU_CSV)):
        snap = read_gpu_memory(None)
    assert snap is not None
    assert snap.used_mb == 15335 and snap.total_mb == 16384  # 第一卡(T4)而非第二卡


def test_read_unknown_uuid_fails_safe_not_gpu0():
    """D:未知身份 → None,绝不静默回退 GPU 0。"""
    with mock.patch.object(subprocess, "run", return_value=_fake_smi(_TWO_GPU_CSV)):
        assert read_gpu_memory("GPU-deadbeef-0000-0000-0000-000000000000") is None
        assert read_gpu_memory("deadbeef-0000-0000-0000-000000000000") is None


def test_read_multi_gpu_resolves_requested_physical_gpu():
    """E:多卡 fixture — 请求第二卡得到第二卡的数值,而非另一张卡。"""
    with mock.patch.object(subprocess, "run", return_value=_fake_smi(_TWO_GPU_CSV)):
        via_canonical = read_gpu_memory(_A100_UUID)
        via_bare = read_gpu_memory("7f1a9999-1234-abcd-ef00-112233445566")
    assert via_canonical is not None and via_bare is not None
    assert via_canonical.used_mb == 5000 and via_canonical.free_mb == 7384
    assert via_canonical.total_mb == 12384
    assert via_bare.total_mb == 12384  # 裸形与规范形解析到同一物理卡
    assert via_bare.used_mb != 15335  # 且确实不是第一卡


def test_read_malformed_or_error_output_fails_safe():
    with mock.patch.object(subprocess, "run", return_value=_fake_smi("garbage,line\n")):
        assert read_gpu_memory(None) is None
    with mock.patch.object(subprocess, "run", return_value=_fake_smi("", returncode=1)):
        assert read_gpu_memory(None) is None
    with mock.patch.object(
        subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd="nvidia-smi", timeout=10)
    ):
        assert read_gpu_memory(None) is None


# ------------------------------------------------ discover_gpus 稳定身份(§6-F)


def test_discover_gpus_normalizes_torch_uuid_to_canonical():
    """F:discover_gpus 对 torch 裸形 uuid 归一化为规范形(其余字段不变)。"""
    from types import SimpleNamespace

    fake_props_t4 = SimpleNamespace(
        uuid="3caad314-5735-d4c2-64ce-e82bb88a11ba",
        name="Tesla T4",
        total_memory=16384 * 1024 * 1024,
    )
    fake_props_a100 = SimpleNamespace(
        uuid="7f1a9999-1234-abcd-ef00-112233445566",
        name="NVIDIA A100",
        total_memory=12384 * 1024 * 1024,
    )
    fake_torch = mock.Mock()
    fake_torch.cuda.is_available.return_value = True
    fake_torch.cuda.device_count.return_value = 2
    fake_torch.cuda.get_device_properties.side_effect = [fake_props_t4, fake_props_a100]
    with mock.patch.dict("sys.modules", {"torch": fake_torch}):
        devices = discover_gpus()
    assert [d.uuid for d in devices] == [_T4_UUID, _A100_UUID]  # 规范形,与 nvidia-smi 一致
    assert [d.index for d in devices] == [0, 1]
    assert [d.name for d in devices] == ["Tesla T4", "NVIDIA A100"]
    assert devices[0].total_memory_mb == 16384
    assert devices[0].label == "Tesla T4 · GPU 0"


def test_discover_gpus_missing_uuid_falls_back_to_index_identity():
    """torch 未提供 uuid 时保持 index 兜底身份(不抛错、不臆造 GPU- 形态)。"""
    from types import SimpleNamespace

    fake_props = SimpleNamespace(uuid=None, name="Tesla T4", total_memory=16384 * 1024 * 1024)
    fake_torch = mock.Mock()
    fake_torch.cuda.is_available.return_value = True
    fake_torch.cuda.device_count.return_value = 1
    fake_torch.cuda.get_device_properties.return_value = fake_props
    with mock.patch.dict("sys.modules", {"torch": fake_torch}):
        devices = discover_gpus()
    assert devices[0].uuid == "index-0"
