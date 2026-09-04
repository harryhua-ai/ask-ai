"""Hardware-Aware Runtime 管理器单元测试(无 GPU;全部注入假工厂/假读数)。

覆盖执行契约验收矩阵(§33 C/E/F/G/H/J/K/L/M 的本地可测子集):
- 单一驻留:同模型+同 GPU(或同 CPU)→ Query/Sync 共享同一实例;
- 不同设备 → 独立实例(§9);
- sync CUDA OOM → 单向 CPU 回退(同模型),查询实例不动,#14 遥测如实;
- 非 CUDA 故障不触发回退;
- 容量:free < 查询峰值保留 → UNSAFE;auto/manual 预算推导;不硬编码 4GB。
"""

from types import SimpleNamespace

import numpy as np
import pytest

from backend.runtime.hardware import GpuMemorySnapshot
from backend.runtime.manager import (
    CAPACITY_HEALTHY,
    CAPACITY_LIMITED,
    CAPACITY_UNSAFE,
    WORKLOAD_QUERY_EMBEDDING,
    WORKLOAD_QUERY_RERANKER,
    WORKLOAD_SYNC_EMBEDDING,
    ModelRuntimeManager,
)


class FakeEmbedder:
    """可编程假嵌入器:记录 device 与调用;可按计划抛错。"""

    dimension = 4

    def __init__(self, device: str = "cpu", **kwargs):
        self.device = device
        self.calls: list[list[str]] = []
        self.fail_plan: list[BaseException | None] = []

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        self.calls.append(list(texts))
        if self.fail_plan:
            exc = self.fail_plan.pop(0)
            if exc is not None:
                raise exc
        return [np.zeros(4, dtype=np.float32) for _ in texts]


class FakeReranker:
    def rerank(self, query: str, documents: list[str]) -> list[float]:
        return [0.5 for _ in documents]


def _settings(device: str = "cuda"):
    return SimpleNamespace(
        embedder_device=device,
        embedder_batch_size=16,
        embedder_max_length=8192,
        jwt_secret="test-secret",
        internal_api_base_url="http://backend:8000",
    )


def _make_manager(device: str = "cuda", gpu_snapshot: GpuMemorySnapshot | None = None):
    created: list[FakeEmbedder] = []

    def embedder_factory(device: str = "cpu", **kwargs) -> FakeEmbedder:
        e = FakeEmbedder(device=device)
        created.append(e)
        return e

    manager = ModelRuntimeManager(
        _settings(device),
        embedder_factory=embedder_factory,
        reranker_factory=lambda **kwargs: FakeReranker(),
        gpu_memory_reader=(lambda uuid: gpu_snapshot) if gpu_snapshot else (lambda uuid: None),
    )
    return manager, created


def _torch_oom() -> Exception:
    import torch

    return torch.OutOfMemoryError("CUDA out of memory. Tried to allocate 490.00 MiB")


# ----------------------------------------------------------- 单一驻留(§6/E)


def test_shared_embedding_same_device_single_instance():
    manager, created = _make_manager("cuda")
    manager._build({})
    assert manager.states[WORKLOAD_QUERY_EMBEDDING].shared is True
    assert manager._embedder_for(WORKLOAD_QUERY_EMBEDDING) is manager._embedder_for(
        WORKLOAD_SYNC_EMBEDDING
    )
    # 两个 embedding workload 只构造一个共享嵌入实例(reranker 走独立工厂)
    assert len(created) == 1


def test_different_devices_create_independent_instances():
    manager, created = _make_manager("cuda")
    # sync 显式配置 CPU(不同设备 → 允许独立实例,§9)
    manager._build({WORKLOAD_SYNC_EMBEDDING: ("cpu", None, "BAAI/bge-m3")})
    assert manager.states[WORKLOAD_QUERY_EMBEDDING].shared is False
    assert manager._embedder_for(WORKLOAD_QUERY_EMBEDDING) is not manager._embedder_for(
        WORKLOAD_SYNC_EMBEDDING
    )
    devices = {e.device for e in created}
    assert devices == {"cuda", "cpu"}


def test_cpu_default_policy_shares_cpu_instance():
    manager, _ = _make_manager("cpu")
    manager._build({})
    assert manager._embedder_for(WORKLOAD_QUERY_EMBEDDING) is manager._embedder_for(
        WORKLOAD_SYNC_EMBEDDING
    )


# ----------------------------------------------------------- #14 回退(F/K)


def test_sync_oom_falls_back_one_way_to_cpu_query_untouched():
    manager, created = _make_manager("cuda")
    manager._build({})
    gpu_instance = manager._embedder_for(WORKLOAD_SYNC_EMBEDDING)
    gpu_instance.fail_plan = [_torch_oom()]

    vectors = manager.embed(WORKLOAD_SYNC_EMBEDDING, ["doc"])

    assert len(vectors) == 1
    state = manager.states[WORKLOAD_SYNC_EMBEDDING]
    assert state.effective.kind == "cpu"
    assert state.status == "fallback_gpu_to_cpu"
    assert state.fallback_reason == "cuda_oom"
    # 后续批次继续走 CPU 实例(单向;不再碰 GPU)
    cpu_instance = manager._embedder_for(WORKLOAD_SYNC_EMBEDDING)
    assert cpu_instance is not gpu_instance
    assert cpu_instance.device == "cpu"
    manager.embed(WORKLOAD_SYNC_EMBEDDING, ["doc2"])
    assert cpu_instance.calls == [["doc"], ["doc2"]]
    assert gpu_instance.calls == [["doc"]]
    # 查询实例(共享 GPU)不受影响
    assert manager._embedder_for(WORKLOAD_QUERY_EMBEDDING) is gpu_instance
    assert manager.states[WORKLOAD_QUERY_EMBEDDING].status == "loaded"


def test_non_cuda_error_does_not_fallback():
    manager, _ = _make_manager("cuda")
    manager._build({})
    instance = manager._embedder_for(WORKLOAD_SYNC_EMBEDDING)
    instance.fail_plan = [ValueError("bad payload")]

    with pytest.raises(ValueError):
        manager.embed(WORKLOAD_SYNC_EMBEDDING, ["doc"])
    assert manager.states[WORKLOAD_SYNC_EMBEDDING].effective.kind == "gpu"
    assert manager._sync_cpu_embedder is None


def test_query_path_has_no_auto_fallback():
    manager, _ = _make_manager("cuda")
    manager._build({})
    instance = manager._embedder_for(WORKLOAD_QUERY_EMBEDDING)
    instance.fail_plan = [_torch_oom()]

    with pytest.raises(Exception):  # noqa: B017 - 与现状一致:查询无自动回退
        manager.embed(WORKLOAD_QUERY_EMBEDDING, ["q"])
    assert manager._sync_cpu_embedder is None
    assert manager.states[WORKLOAD_QUERY_EMBEDDING].status == "loaded"


# ----------------------------------------------------------- 容量(§11/L/M)


def test_capacity_unsafe_when_free_below_query_peak():
    manager, _ = _make_manager(
        "cuda", gpu_snapshot=GpuMemorySnapshot(used_mb=15510, free_mb=126, total_mb=15564)
    )
    manager._build({})
    cap = manager.capacity()
    assert cap["state"] == CAPACITY_UNSAFE
    assert cap["budget_mb"] == 126  # auto = 当前空闲 + ASK-AI 驻留(此处无 CUDA 读数为 0)
    assert cap["gpu_free_mb"] == 126


def test_capacity_healthy_when_budget_covers_peak():
    manager, _ = _make_manager(
        "cuda", gpu_snapshot=GpuMemorySnapshot(used_mb=6000, free_mb=9000, total_mb=15564)
    )
    manager._build({})
    cap = manager.capacity()
    assert cap["state"] == CAPACITY_HEALTHY
    assert cap["budget_mb"] == 9000


def test_manual_budget_is_planning_cap_never_exceeds_hardware():
    manager, _ = _make_manager(
        "cuda", gpu_snapshot=GpuMemorySnapshot(used_mb=6000, free_mb=9000, total_mb=15564)
    )
    manager._build({})
    manager._budget_mode = "manual"
    manager._manual_budget_mb = 300  # 低于查询峰值保留(512)
    cap = manager.capacity()
    assert cap["state"] == CAPACITY_LIMITED
    assert cap["budget_mb"] == 300  # 手动预算 < 硬件可用 → 按手动(规划上限)
    # 手动预算超过硬件可用时,按硬件实况封顶(Effective ≤ 实况)
    manager._manual_budget_mb = 99999
    cap = manager.capacity()
    assert cap["budget_mb"] == 9000
    assert cap["state"] == CAPACITY_HEALTHY


def test_capacity_unknown_when_gpu_unreadable():
    manager, _ = _make_manager("cuda", gpu_snapshot=None)
    manager._build({})
    cap = manager.capacity()
    assert cap["state"] == "unknown"
    assert cap["gpu_free_mb"] is None


# ----------------------------------------------------------- 真相面(§15/J)


def test_snapshot_reports_configured_effective_and_restart_required():
    manager, _ = _make_manager("cuda")
    manager._build({WORKLOAD_QUERY_RERANKER: ("cpu", None, "BAAI/bge-reranker-v2-m3")})
    snap = manager.snapshot()
    by_workload = {p["workload"]: p for p in snap["policies"]}
    assert len(snap["policies"]) == 3
    reranker = by_workload[WORKLOAD_QUERY_RERANKER]
    assert reranker["configured"]["kind"] == "cpu"
    assert reranker["restart_required"] is False  # 启动即按策略落地 → 无待重启
    assert reranker["status"] == "loaded"
    assert any(d["kind"] == "cpu" for d in snap["devices"])


def test_gpu_missing_for_configured_uuid_fails_closed():
    manager, _ = _make_manager("cuda")
    with pytest.raises(RuntimeError, match="配置的 GPU 不存在"):
        manager._build(
            {
                WORKLOAD_QUERY_EMBEDDING: (
                    "gpu",
                    "00000000-0000-0000-0000-000000000000",
                    "BAAI/bge-m3",
                )
            }
        )


def test_reranker_proxy_delegates():
    manager, _ = _make_manager("cuda")
    manager._build({})
    assert manager.reranker.rerank("q", ["d"]) == [0.5]
