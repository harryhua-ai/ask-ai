"""#7 host_runtime 采集器单元测试(纯 mock,零真实 GPU / 零 /proc 依赖)。

合同语义(冻结 contract):
- 每项观测 = {available, value, reason, as_of};不可得 → available=False +
  非空 reason,value 恒 None(绝不虚构/占位);
- 全结构含 as_of;顶层键精确锁定;
- 无 GPU 环境 → accelerator 显式 unavailable(非错误、非空壳)。

测试通过 monkeypatch 采集器 seam(_read_file / _run_readonly / discover_gpus /
_hostname / _platform_facts / _loadavg / _disk_usage / _now_iso)注入两态:
真实采集全量事实(Linux+NVIDIA)与完全降级(无 proc / 无 nvidia-smi)。
"""

import os
from unittest import mock

import pytest

from backend.runtime.hardware import GpuDevice
from backend.services import host_runtime

FAKE_NOW = "2026-09-12T00:00:00+00:00"

# ---- canned Linux /proc facts -------------------------------------------------

PROC_CPUINFO = "model name\t: Intel(R) Xeon(R) Silver 4210 CPU @ 2.20GHz\nprocessor\t: 0\n"

PROC_MEMINFO = (
    "MemTotal:       16384000 kB\n"
    "MemAvailable:    8192000 kB\n"
    "SwapTotal:       2048000 kB\n"
    "SwapFree:        1024000 kB\n"
)

PROC_STAT_T1 = (
    "cpu  100 0 100 700 0 0 0 0 0 0\n"  # idle=700 iowait=0 total=900
    "cpu0 100 0 100 700 0 0 0 0 0 0\n"
)
PROC_STAT_T2 = (
    "cpu  100 0 200 800 0 0 0 0 0 0\n"  # Δidle=100 Δtotal=200 → util=50.0%
    "cpu0 100 0 200 800 0 0 0 0 0 0\n"
)

PROC_UPTIME = "2678400.50 5300000.25\n"  # 31 天

NVIDIA_SMI_QUERY_CSV = (
    "0, 3caad314-1c9e-4c1e-a0de-0e04b1d0c3f9, NVIDIA Tesla T4, 535.104.05, "
    "12, 1234, 14126, 15360, 41\n"
)

NVIDIA_SMI_HEADER = (
    "+-----------------------------------------------------------------------------+\n"
    "| NVIDIA-SMI 535.104.05   Driver Version: 535.104.05   CUDA Version: 12.2     |\n"
    "|-------------------------------+----------------------+----------------------+\n"
)


# ---- fixture helpers -----------------------------------------------------------


class _FakeSmi:
    """可编程 _run_readonly 替身:按 args[1] 前缀分流 query/header 两条命令。"""

    def __init__(self, query_ok=True, header_ok=True, query_out=NVIDIA_SMI_QUERY_CSV):
        self.query_ok = query_ok
        self.header_ok = header_ok
        self.query_out = query_out

    def __call__(self, args):
        if len(args) > 1 and "query-gpu" in args[1]:
            if not self.query_ok:
                return host_runtime._CmdResult(ok=False, error="nvidia-smi 不可执行(未安装)")
            return host_runtime._CmdResult(ok=True, stdout=self.query_out)
        if not self.header_ok:
            return host_runtime._CmdResult(ok=False, error="nvidia-smi 不可执行(未安装)")
        return host_runtime._CmdResult(ok=True, stdout=NVIDIA_SMI_HEADER)


class _StubModelRuntime:
    """ModelRuntimeManager.snapshot() 形状桩(仅 contract 承诺的五个键)。"""

    def snapshot(self):
        return {
            "devices": [{"kind": "gpu", "uuid": "GPU-x", "label": "Tesla T4 · GPU 0"}],
            "policies": [
                {
                    "workload": "query_embedding",
                    "status": "loaded",
                    "effective": {"kind": "gpu", "label": "Tesla T4 · GPU 0"},
                }
            ],
            "shared_embedding_runtime": True,
            "runtime_plan": {"mode": "GPU_RESIDENT", "generation": 1},
            "capacity": {"state": "HEALTHY", "gpu_free_mb": 14126},
        }


@pytest.fixture
def full_linux_env(monkeypatch):
    """注入「Linux + NVIDIA GPU」全量可得事实(两态之一:可得)。"""
    monkeypatch.setattr(host_runtime, "_now_iso", lambda: FAKE_NOW)
    proc_files = {
        "/proc/cpuinfo": PROC_CPUINFO,
        "/proc/meminfo": PROC_MEMINFO,
        "/proc/uptime": PROC_UPTIME,
    }
    stat_samples = iter([PROC_STAT_T1, PROC_STAT_T2])

    def fake_read_file(path):
        if path == "/proc/stat":
            return next(stat_samples)
        return proc_files.get(path)

    monkeypatch.setattr(host_runtime, "_read_file", fake_read_file)
    monkeypatch.setattr(host_runtime, "_run_readonly", _FakeSmi())
    monkeypatch.setattr(
        host_runtime,
        "discover_gpus",
        lambda: [
            GpuDevice(
                index=0,
                uuid="GPU-3caad314-1c9e-4c1e-a0de-0e04b1d0c3f9",
                name="NVIDIA Tesla T4",
                total_memory_mb=15360,
            )
        ],
    )
    monkeypatch.setattr(host_runtime, "_hostname", lambda: "prod-gpu-host-1")
    monkeypatch.setattr(host_runtime, "_platform_facts", lambda: ("Linux", "5.15.0-107-generic", "x86_64"))
    monkeypatch.setattr(host_runtime, "_loadavg", lambda: (0.42, 0.35, 0.30))
    usage = mock.Mock(total=100 * 2**30, used=40 * 2**30, free=60 * 2**30)
    monkeypatch.setattr(host_runtime, "_disk_usage", lambda _path: usage)
    monkeypatch.setattr(host_runtime, "_sleep", lambda _s: None)


@pytest.fixture
def degraded_no_gpu_env(monkeypatch):
    """注入「macOS 开发机」全不可得事实(两态之二:不可得)。"""
    monkeypatch.setattr(host_runtime, "_now_iso", lambda: FAKE_NOW)
    monkeypatch.setattr(host_runtime, "_read_file", lambda _path: None)
    monkeypatch.setattr(
        host_runtime,
        "_run_readonly",
        lambda _args: host_runtime._CmdResult(ok=False, error="nvidia-smi 不可执行(未安装)"),
    )
    monkeypatch.setattr(host_runtime, "discover_gpus", list)
    monkeypatch.setattr(host_runtime, "_hostname", lambda: "dev-macbook")

    def _no_platform():
        return ("Darwin", "24.6.0", "arm64")

    monkeypatch.setattr(host_runtime, "_platform_facts", _no_platform)

    def _no_loadavg():
        raise OSError("load average 不可得")

    monkeypatch.setattr(host_runtime, "_loadavg", _no_loadavg)

    def _no_disk(_path):
        raise OSError("statvfs failed")

    monkeypatch.setattr(host_runtime, "_disk_usage", _no_disk)


# ---- helpers -------------------------------------------------------------------


def iter_observations(node):
    """递归产出全部观测四元组(available/value/reason/as_of 形状的 dict)。"""
    if isinstance(node, dict):
        if set(node.keys()) == {"available", "value", "reason", "as_of"}:
            yield node
            return
        for v in node.values():
            yield from iter_observations(v)
    elif isinstance(node, list):
        for v in node:
            yield from iter_observations(v)


def test_full_facts_top_level_keys_locked(full_linux_env):
    result = host_runtime.collect_system_runtime(model_runtime=_StubModelRuntime())
    assert set(result.keys()) == {"as_of", "host", "resources", "accelerator", "service"}
    assert result["as_of"] == FAKE_NOW


def test_full_facts_host_section(full_linux_env):
    host = host_runtime.collect_system_runtime(model_runtime=None)["host"]
    assert set(host.keys()) == {"as_of", "hostname", "os", "kernel", "uptime_seconds"}
    assert host["hostname"] == {
        "available": True,
        "value": "prod-gpu-host-1",
        "reason": None,
        "as_of": FAKE_NOW,
    }
    assert host["os"]["value"] == "Linux 5.15.0-107-generic x86_64"
    assert host["kernel"]["value"] == "5.15.0-107-generic"
    assert host["uptime_seconds"]["available"] is True
    assert host["uptime_seconds"]["value"] == 2678400


def test_full_facts_resources_section(full_linux_env):
    resources = host_runtime.collect_system_runtime(model_runtime=None)["resources"]
    assert resources["cpu_model"]["value"] == "Intel(R) Xeon(R) Silver 4210 CPU @ 2.20GHz"
    assert resources["cpu_logical_cores"]["value"] == os.cpu_count()
    # 双采样 /proc/stat:Δidle=100 / Δtotal=200 → util = 1 - 100/200 = 50.0%
    assert resources["cpu_utilization_percent"]["available"] is True
    assert resources["cpu_utilization_percent"]["value"] == 50.0
    assert resources["loadavg_1m"]["value"] == 0.42
    assert resources["memory_total_mb"]["value"] == 16384000 // 1024
    assert resources["memory_used_mb"]["value"] == (16384000 - 8192000) // 1024
    assert resources["memory_available_mb"]["value"] == 8192000 // 1024
    assert resources["swap_total_mb"]["value"] == 2048000 // 1024
    assert resources["swap_used_mb"]["value"] == (2048000 - 1024000) // 1024
    assert resources["disk_total_gb"]["value"] == 100.0
    assert resources["disk_used_gb"]["value"] == 40.0
    assert resources["disk_free_gb"]["value"] == 60.0
    assert resources["disk_used_percent"]["value"] == 40.0
    assert resources["disk_path"]["available"] is True


def test_full_facts_accelerator_section(full_linux_env):
    accel = host_runtime.collect_system_runtime(model_runtime=None)["accelerator"]
    assert set(accel.keys()) == {
        "as_of",
        "available",
        "reason",
        "driver_version",
        "cuda_version",
        "gpus",
        "nvidia_smi_error",
    }
    assert accel["available"] is True
    assert accel["reason"] is None
    assert accel["driver_version"]["value"] == "535.104.05"
    assert accel["cuda_version"]["value"] == "12.2"
    assert len(accel["gpus"]) == 1
    gpu = accel["gpus"][0]
    # nvidia-smi 裸 uuid 与 torch 规范形身份匹配后融合为单卡条目
    assert gpu["uuid"] == "GPU-3caad314-1c9e-4c1e-a0de-0e04b1d0c3f9"
    assert gpu["name"] == "NVIDIA Tesla T4"
    assert gpu["index"] == 0
    assert gpu["utilization_percent"] == 12
    assert gpu["memory_used_mb"] == 1234
    assert gpu["memory_free_mb"] == 14126
    assert gpu["memory_total_mb"] == 15360
    assert gpu["temperature_c"] == 41
    assert gpu["as_of"] == FAKE_NOW


def test_full_facts_service_section(full_linux_env):
    service = host_runtime.collect_system_runtime(model_runtime=_StubModelRuntime())["service"]
    assert set(service.keys()) == {"as_of", "health", "release", "model_runtime"}
    assert service["health"]["available"] is True
    assert service["health"]["value"] == "ok"
    assert service["release"]["available"] is True
    assert set(service["release"]["value"].keys()) == {
        "version",
        "git_sha",
        "built_at",
        "app_mode",
        "image",
        "ci_run_id",
        "source",
    }
    assert service["model_runtime"]["available"] is True
    snap = service["model_runtime"]["value"]
    assert set(snap.keys()) == {
        "devices",
        "policies",
        "shared_embedding_runtime",
        "runtime_plan",
        "capacity",
    }
    assert snap["capacity"]["state"] == "HEALTHY"


def test_every_observation_has_shape_and_as_of(full_linux_env, degraded_no_gpu_env):
    for env in (full_linux_env, degraded_no_gpu_env):
        result = host_runtime.collect_system_runtime(model_runtime=None)
        obs = list(iter_observations(result))
        assert obs, "必须产出观测四元组"
        for o in obs:
            assert set(o.keys()) == {"available", "value", "reason", "as_of"}
            assert o["as_of"] == FAKE_NOW
            if o["available"]:
                assert o["value"] is not None and o["reason"] is None
            else:
                assert o["value"] is None
                assert isinstance(o["reason"], str) and o["reason"]


def test_degraded_no_gpu_accelerator_explicit_unavailable(degraded_no_gpu_env):
    accel = host_runtime.collect_system_runtime(model_runtime=None)["accelerator"]
    assert accel["available"] is False
    assert isinstance(accel["reason"], str) and accel["reason"]
    assert accel["gpus"] == []
    assert accel["driver_version"]["available"] is False
    assert accel["driver_version"]["reason"]
    assert accel["cuda_version"]["available"] is False
    # 非 200 错误、非空壳:整段结构仍完整(合同:非错误、非空壳)
    assert accel["as_of"] == FAKE_NOW


def test_degraded_platform_items_unavailable_with_reason(degraded_no_gpu_env):
    result = host_runtime.collect_system_runtime(model_runtime=None)
    resources = result["resources"]
    for key in (
        "cpu_model",
        "cpu_utilization_percent",
        "loadavg_1m",
        "memory_total_mb",
        "memory_used_mb",
        "swap_total_mb",
        "disk_total_gb",
        "disk_used_percent",
    ):
        assert resources[key]["available"] is False, key
        assert resources[key]["value"] is None, key
        assert resources[key]["reason"], f"{key} 必须给出原因"
    assert result["host"]["uptime_seconds"]["available"] is False
    assert result["host"]["uptime_seconds"]["reason"]
    # 逻辑核数与主机名属平台基础事实,任何平台都可得
    assert result["host"]["hostname"]["available"] is True
    assert resources["cpu_logical_cores"]["available"] is True


def test_degraded_model_runtime_none_is_explicit_unavailable(degraded_no_gpu_env):
    service = host_runtime.collect_system_runtime(model_runtime=None)["service"]
    assert service["model_runtime"]["available"] is False
    assert service["model_runtime"]["value"] is None
    assert "模型运行时" in service["model_runtime"]["reason"]


def test_model_runtime_snapshot_error_degrades_not_raises(monkeypatch):
    class _Broken:
        def snapshot(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(host_runtime, "_now_iso", lambda: FAKE_NOW)
    service = host_runtime.collect_system_runtime(model_runtime=_Broken())["service"]
    assert service["model_runtime"]["available"] is False
    assert service["model_runtime"]["value"] is None
    assert service["model_runtime"]["reason"]


def test_torch_gpu_without_nvidia_smi_still_reports_devices(monkeypatch):
    """容器缺 nvidia-smi 但 torch 可见 CUDA 设备:设备存在是事实 → available=True,
    利用率/温度/驱动等 nvidia-smi 专属字段如实不可得(None)。"""
    monkeypatch.setattr(host_runtime, "_now_iso", lambda: FAKE_NOW)
    monkeypatch.setattr(host_runtime, "_read_file", lambda _p: None)
    monkeypatch.setattr(
        host_runtime,
        "_run_readonly",
        lambda _args: host_runtime._CmdResult(ok=False, error="nvidia-smi 不可执行(未安装)"),
    )
    monkeypatch.setattr(
        host_runtime,
        "discover_gpus",
        lambda: [
            GpuDevice(
                index=0,
                uuid="GPU-3caad314-1c9e-4c1e-a0de-0e04b1d0c3f9",
                name="NVIDIA Tesla T4",
                total_memory_mb=15360,
            )
        ],
    )
    accel = host_runtime.collect_system_runtime(model_runtime=None)["accelerator"]
    assert accel["available"] is True
    assert len(accel["gpus"]) == 1
    gpu = accel["gpus"][0]
    assert gpu["uuid"] == "GPU-3caad314-1c9e-4c1e-a0de-0e04b1d0c3f9"
    assert gpu["name"] == "NVIDIA Tesla T4"
    assert gpu["memory_total_mb"] == 15360  # torch 侧事实
    assert gpu["utilization_percent"] is None  # nvidia-smi 专属事实不可得 → 不虚构
    assert gpu["temperature_c"] is None
    assert accel["nvidia_smi_error"]


def test_release_identity_failure_degrades_not_raises(monkeypatch):
    monkeypatch.setattr(host_runtime, "_now_iso", lambda: FAKE_NOW)
    monkeypatch.setattr(
        host_runtime,
        "get_release_identity",
        mock.Mock(side_effect=RuntimeError("manifest broken")),
    )
    service = host_runtime.collect_system_runtime(model_runtime=None)["service"]
    assert service["release"]["available"] is False
    assert service["release"]["reason"]
    # release 失败不拖垮 health / 其余 section
    assert service["health"]["available"] is True
    assert host_runtime.collect_system_runtime(model_runtime=None)["host"]["as_of"] == FAKE_NOW


# ---- Role A 窄加固:Integration B 补的两处微测试缺口 ------------------------------


def test_platform_facts_raise_degrades_not_raises(monkeypatch):
    """`_platform_facts` 抛错时端点采集面整体仍完整返回(200 形状),
    仅 platform/kernel 两项显式不可得,其余 section 不受牵连。"""

    def _boom():
        raise RuntimeError("platform probe exploded")

    monkeypatch.setattr(host_runtime, "_now_iso", lambda: FAKE_NOW)
    monkeypatch.setattr(host_runtime, "_read_file", lambda _path: None)
    monkeypatch.setattr(
        host_runtime,
        "_run_readonly",
        lambda _args: host_runtime._CmdResult(ok=False, error="nvidia-smi 不可执行(未安装)"),
    )
    monkeypatch.setattr(host_runtime, "discover_gpus", list)
    monkeypatch.setattr(host_runtime, "_hostname", lambda: "some-host")
    monkeypatch.setattr(host_runtime, "_platform_facts", _boom)

    def _no_loadavg():
        raise OSError("load average 不可得")

    monkeypatch.setattr(host_runtime, "_loadavg", _no_loadavg)

    def _no_disk(_path):
        raise OSError("statvfs failed")

    monkeypatch.setattr(host_runtime, "_disk_usage", _no_disk)

    result = host_runtime.collect_system_runtime(model_runtime=None)

    # 整体形状仍完整(根级 as_of + 四组键全在),as_of 正常
    assert set(result.keys()) == {"as_of", "host", "resources", "accelerator", "service"}
    assert result["host"]["as_of"] == FAKE_NOW
    # platform 信息观测显式不可得(available=False + 非空 reason + value=None;
    # platform 三元组折入 os 观测,kernel 独立)
    for key in ("os", "kernel"):
        obs = result["host"][key]
        assert obs["available"] is False, key
        assert obs["value"] is None and obs["reason"], key
    # 其余组不受牵连:accelerator 段为 {available: bool, reason, ...} 分节形状
    assert result["accelerator"]["available"] is False  # 无 GPU 环境显式不可得,但形状完整
    assert result["service"]["release"]["available"] is False or isinstance(
        result["service"]["release"]["value"], dict
    )


def test_smi_int_not_supported_field_is_none():
    """`[Not Supported]` 等 nvidia-smi 字段值 → 该字段如实不可得(None),不虚构。"""
    assert host_runtime._smi_int("[Not Supported]") is None
    assert host_runtime._smi_int("N/A") is None
    assert host_runtime._smi_int("") is None
    assert host_runtime._smi_int("42") == 42
    assert host_runtime._smi_int("-7") == -7
