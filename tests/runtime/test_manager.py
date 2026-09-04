"""Hardware-Aware Runtime 管理器单元测试(无 GPU;全部注入假工厂/假读数)。

覆盖执行契约验收矩阵(REV1 B1-B5):
- B1 查询实例恒有:混合设备(query GPU+sync CPU / query CPU+sync GPU)下
  query embed() 真实可执行(非 identity-only 断言);
- 单一驻留:同模型+同设备 → 两 workload 仅一个共享实例;
- B2 GPU 执行协调:同卡批次互斥(并发峰=1);在线查询严格优先(排队中的
  sync 不得先于已等待的 query 启动);CPU 执行不入闸(不过度串行化);
- B3/B4 驻留计划:预算驱动装配阶梯(undecided/dual/transient/insufficient),
  预算变化 → 计划变化(restart_required);UNSAFE 不先全量硬载;
  瞬态重排:调用即上卡、完成即卸载(offload 计数);
- #14 回退:sync CUDA OOM 单向回退 CPU,查询实例不动;非 CUDA 故障不回退;
- 容量:free < 查询峰值保留 → UNSAFE;auto/manual 预算推导;不硬编码 4GB。
"""

import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from backend.runtime.hardware import GpuMemorySnapshot
from backend.runtime.manager import (
    CAPACITY_HEALTHY,
    CAPACITY_LIMITED,
    CAPACITY_UNSAFE,
    PLAN_DUAL_RESIDENT,
    PLAN_GPU_INSUFFICIENT,
    PLAN_RERANKER_TRANSIENT,
    PLAN_UNDECIDED,
    RESIDENCY_TRANSIENT,
    STATUS_PLAN_CPU,
    STATUS_UNSAFE_NO_PLAN,
    SYNC_FAIRNESS_QUOTA,
    WORKLOAD_QUERY_EMBEDDING,
    WORKLOAD_QUERY_RERANKER,
    WORKLOAD_SYNC_EMBEDDING,
    ModelRuntimeManager,
    UnsafeRuntimePlanError,
    _TransientGpuReranker,
    compute_residency_plan,
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
    """双驻留/CPU 计划下的假重排器(无驻留面)。"""

    def __init__(self, device: str = "cpu", **kwargs):
        self.device = device

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        return [0.5 for _ in documents]


class FakeResidencyReranker:
    """瞬态计划下的假重排器:暴露 gpu_residency_* 驻留面(BGEReranker 同款)。"""

    def __init__(self, device: str = "cuda", **kwargs):
        self.device = device
        self.residency = "cpu"  # from_pretrained 权重真相:主机内存
        self.offloads = 0
        self.rerank_calls = 0

    def gpu_residency_materialize(self, device: str = "cuda") -> None:
        self.residency = "gpu"

    def gpu_residency_offload(self) -> None:
        self.residency = "cpu"
        self.offloads += 1

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        self.rerank_calls += 1
        return [0.5 for _ in documents]


def _settings(device: str = "cuda"):
    return SimpleNamespace(
        embedder_device=device,
        embedder_batch_size=16,
        embedder_max_length=8192,
        jwt_secret="test-secret",
        internal_api_base_url="http://backend:8000",
    )


def _make_manager(
    device: str = "cuda",
    gpu_snapshot: GpuMemorySnapshot | None = None,
    reranker_cls=FakeReranker,
):
    created: list[FakeEmbedder] = []
    created_rerankers: list = []

    def embedder_factory(device: str = "cpu", **kwargs) -> FakeEmbedder:
        e = FakeEmbedder(device=device)
        created.append(e)
        return e

    def reranker_factory(device: str = "cpu", **kwargs):
        r = reranker_cls(device=device)
        created_rerankers.append(r)
        return r

    manager = ModelRuntimeManager(
        _settings(device),
        embedder_factory=embedder_factory,
        reranker_factory=reranker_factory,
        gpu_memory_reader=(lambda uuid: gpu_snapshot) if gpu_snapshot else (lambda uuid: None),
    )
    return manager, created, created_rerankers


def _torch_oom() -> Exception:
    import torch

    return torch.OutOfMemoryError("CUDA out of memory. Tried to allocate 490.00 MiB")


# ----------------------------------------------- B1:查询实例恒有(混合设备)


def test_query_gpu_sync_cpu_query_embed_executes():
    """B1:query GPU + sync CPU → query embed() 真实执行(非 identity 断言)。"""
    manager, created, _ = _make_manager("cuda")
    manager._build({WORKLOAD_SYNC_EMBEDDING: ("cpu", None, "BAAI/bge-m3")})

    query_instance = manager._embedder_for(WORKLOAD_QUERY_EMBEDDING)
    assert query_instance is not None
    vectors = manager.embed(WORKLOAD_QUERY_EMBEDDING, ["hello", "world"])
    assert len(vectors) == 2
    assert vectors[0].shape == (4,)
    assert query_instance.calls == [["hello", "world"]]  # 真打到了查询实例
    assert query_instance.device == "cuda"  # 查询实例是 GPU 装配的那个
    # sync 独立 CPU 实例同样可执行
    sync_vectors = manager.embed(WORKLOAD_SYNC_EMBEDDING, ["doc"])
    assert len(sync_vectors) == 1
    assert manager._embedder_for(WORKLOAD_SYNC_EMBEDDING).device == "cpu"
    assert {e.device for e in created} == {"cuda", "cpu"}


def test_query_cpu_sync_gpu_query_embed_executes():
    """B1:query CPU + sync GPU → query embed() 真实执行(非 identity 断言)。"""
    manager, created, _ = _make_manager("cpu")
    manager._build({WORKLOAD_SYNC_EMBEDDING: ("gpu", None, "BAAI/bge-m3")})

    vectors = manager.embed(WORKLOAD_QUERY_EMBEDDING, ["hello"])
    assert len(vectors) == 1
    assert vectors[0].shape == (4,)
    query_instance = manager._embedder_for(WORKLOAD_QUERY_EMBEDDING)
    assert query_instance is not None and query_instance.device == "cpu"
    assert query_instance.calls == [["hello"]]
    # sync 独立 GPU 实例同样可执行(B2:走 GPU 闸)
    sync_vectors = manager.embed(WORKLOAD_SYNC_EMBEDDING, ["doc"])
    assert len(sync_vectors) == 1
    assert manager._embedder_for(WORKLOAD_SYNC_EMBEDDING).device == "cuda"
    assert {e.device for e in created} == {"cpu", "cuda"}


# ------------------------------------------------------- 单一驻留(§6/E)


def test_shared_embedding_same_device_single_instance():
    manager, created, _ = _make_manager("cuda")
    manager._build({})
    assert manager.states[WORKLOAD_QUERY_EMBEDDING].shared is True
    assert manager._embedder_for(WORKLOAD_QUERY_EMBEDDING) is manager._embedder_for(
        WORKLOAD_SYNC_EMBEDDING
    )
    # 两个 embedding workload 只构造一个共享嵌入实例(reranker 走独立工厂)
    assert len(created) == 1


def test_different_devices_create_independent_instances_and_both_execute():
    """B5 修正假阳性:不同设备 → 独立实例,且两侧 embed() 都真实执行。"""
    manager, created, _ = _make_manager("cuda")
    manager._build({WORKLOAD_SYNC_EMBEDDING: ("cpu", None, "BAAI/bge-m3")})
    assert manager.states[WORKLOAD_QUERY_EMBEDDING].shared is False

    q_vectors = manager.embed(WORKLOAD_QUERY_EMBEDDING, ["q1"])
    s_vectors = manager.embed(WORKLOAD_SYNC_EMBEDDING, ["s1", "s2"])
    assert len(q_vectors) == 1 and len(s_vectors) == 2
    query_instance = manager._embedder_for(WORKLOAD_QUERY_EMBEDDING)
    sync_instance = manager._embedder_for(WORKLOAD_SYNC_EMBEDDING)
    assert query_instance is not sync_instance
    assert query_instance.calls == [["q1"]]  # 两侧都真实执行
    assert sync_instance.calls == [["s1", "s2"]]
    assert {e.device for e in created} == {"cuda", "cpu"}


def test_cpu_default_policy_shares_cpu_instance():
    manager, _, _ = _make_manager("cpu")
    manager._build({})
    assert manager._embedder_for(WORKLOAD_QUERY_EMBEDDING) is manager._embedder_for(
        WORKLOAD_SYNC_EMBEDDING
    )
    assert manager._query_on_gpu is False and manager._sync_on_gpu is False


# ------------------------------------------------------- #14 回退(F/K)


def test_sync_oom_falls_back_one_way_to_cpu_query_untouched():
    manager, _, _ = _make_manager("cuda")
    manager._build({})
    gpu_instance = manager._embedder_for(WORKLOAD_SYNC_EMBEDDING)
    gpu_instance.fail_plan = [_torch_oom()]

    vectors = manager.embed(WORKLOAD_SYNC_EMBEDDING, ["doc"])

    assert len(vectors) == 1
    state = manager.states[WORKLOAD_SYNC_EMBEDDING]
    assert state.effective.kind == "cpu"
    assert state.status == "fallback_gpu_to_cpu"
    assert state.fallback_reason == "cuda_oom"
    # 后续批次继续走 CPU 实例(单向;不再碰 GPU,也不再占 GPU 闸)
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
    manager, _, _ = _make_manager("cuda")
    manager._build({})
    instance = manager._embedder_for(WORKLOAD_SYNC_EMBEDDING)
    instance.fail_plan = [ValueError("bad payload")]

    with pytest.raises(ValueError):
        manager.embed(WORKLOAD_SYNC_EMBEDDING, ["doc"])
    assert manager.states[WORKLOAD_SYNC_EMBEDDING].effective.kind == "gpu"
    assert manager._sync_cpu_embedder is None


def test_query_path_has_no_auto_fallback():
    manager, _, _ = _make_manager("cuda")
    manager._build({})
    instance = manager._embedder_for(WORKLOAD_QUERY_EMBEDDING)
    instance.fail_plan = [_torch_oom()]

    with pytest.raises(Exception):  # noqa: B017 - 与现状一致:查询无自动回退
        manager.embed(WORKLOAD_QUERY_EMBEDDING, ["q"])
    assert manager._sync_cpu_embedder is None
    assert manager.states[WORKLOAD_QUERY_EMBEDDING].status == "loaded"


# ------------------------------------------- B2:GPU 执行协调(确定性并发)


def _patch_scripted_embed(instance, script):
    """把假嵌入实例的 embed 替换为脚本化实现(记录 start/end、按标签等待)。"""
    lock = threading.Lock()

    def scripted_embed(texts):
        tag = texts[0]
        with lock:
            script["calls"].append(f"{tag}:start")
        event = script.get(tag)
        if event is not None:
            assert event.wait(timeout=10), f"{tag} 等待释放超时"
        time.sleep(0.01)
        with lock:
            script["calls"].append(f"{tag}:end")
        return [np.zeros(4, dtype=np.float32) for _ in texts]

    instance.embed = scripted_embed  # 实例属性遮蔽;manager 经 .embed() 调用


def test_gpu_embed_batches_never_overlap():
    """B2:同卡嵌入批次(query+sync 混合)互斥执行,并发峰恒为 1。"""
    manager, _, _ = _make_manager("cuda")
    manager._build({})
    instance = manager._embedder_for(WORKLOAD_QUERY_EMBEDDING)
    assert manager._query_on_gpu and manager._sync_on_gpu

    lock = threading.Lock()
    state = {"concurrent": 0, "max": 0}

    def probe_embed(texts):
        with lock:
            state["concurrent"] += 1
            state["max"] = max(state["max"], state["concurrent"])
        time.sleep(0.03)
        with lock:
            state["concurrent"] -= 1
        return [np.zeros(4, dtype=np.float32) for _ in texts]

    instance.embed = probe_embed
    threads = [
        threading.Thread(
            target=manager.embed,
            args=(WORKLOAD_QUERY_EMBEDDING if i % 2 else WORKLOAD_SYNC_EMBEDDING, [f"t{i}"]),
        )
        for i in range(8)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)
    assert all(not t.is_alive() for t in threads)
    assert state["max"] == 1  # 无未受控并发 GPU 峰


def test_query_preempts_queued_sync():
    """B2:在线查询严格优先 —— 在飞 sync 批次结束后,已等待的 query 先于
    排队中的 sync 批次执行;sync 无法垄断 GPU。"""
    manager, _, _ = _make_manager("cuda")
    manager._build({})
    instance = manager._embedder_for(WORKLOAD_QUERY_EMBEDDING)

    release_s1 = threading.Event()
    release_s2 = threading.Event()
    script = {
        "calls": [],
        "s1": release_s1,
        "s2": release_s2,
    }
    _patch_scripted_embed(instance, script)

    t_s1 = threading.Thread(target=manager.embed, args=(WORKLOAD_SYNC_EMBEDDING, ["s1"]))
    t_s1.start()
    deadline = time.time() + 10
    while not manager._gpu_gate.busy and time.time() < deadline:
        time.sleep(0.005)
    assert manager._gpu_gate.busy  # s1 在飞

    t_s2 = threading.Thread(target=manager.embed, args=(WORKLOAD_SYNC_EMBEDDING, ["s2"]))
    t_s2.start()
    time.sleep(0.05)  # 给 s2 机会错误地抢入闸(若有缺陷;此时 busy=1,只能等待)
    t_q = threading.Thread(target=manager.embed, args=(WORKLOAD_QUERY_EMBEDDING, ["q"]))
    t_q.start()
    # 确定性:等到 query 已在闸上登记为等待者(而非裸 sleep 猜调度)
    deadline = time.time() + 10
    while manager._gpu_gate.query_waiting < 1 and time.time() < deadline:
        time.sleep(0.005)
    assert manager._gpu_gate.query_waiting == 1
    assert script["calls"] == ["s1:start"], f"s2/q 不应在在飞批次结束前启动: {script['calls']}"

    release_s1.set()
    t_q.join(timeout=10)
    assert not t_q.is_alive(), "查询必须能在一个在飞 sync 批次内得到执行"
    # 排队中的 sync 只能在查询完成之后启动(顺序断言见下方 ends 序列)
    assert script["calls"].index("s2:start") > script["calls"].index("q:end")
    assert t_s2.is_alive()  # s2 已启动但仍在等脚本释放(不构成抢先)

    release_s2.set()
    t_s2.join(timeout=10)
    assert not t_s2.is_alive()
    ends = [c for c in script["calls"] if c.endswith(":end")]
    assert ends == ["s1:end", "q:end", "s2:end"]  # 确定性顺序


def test_r2_2_waiting_sync_eventually_executes_under_query_pressure():
    """R2-2 有界公平:持续查询压力 + 等待中的 sync → sync 终获执行。

    确定性编排(全部用事件+闸状态轮询,无裸 sleep 竞态):
    - s1 先于 q2..q6 排队等待;
    - q2..q5 逐个占用空档(每次获取都计入饥饿账本;每一步都先确保下一个
      查询已登记为等待者再放行前一个,杜绝 sync 提前苏醒的竞态);
    - 计满 SYNC_FAIRNESS_QUOTA 后闸转入公平窗口:仍在排队的 q6 被拦下,
      s1 获得一次执行权;随后配额清零、查询优先恢复, q6 才执行。
    """
    quota = SYNC_FAIRNESS_QUOTA
    manager, _, _ = _make_manager("cuda")
    manager._build({})
    instance = manager._embedder_for(WORKLOAD_QUERY_EMBEDDING)

    events = {f"q{i}": threading.Event() for i in range(1, 7)}
    release_s1 = threading.Event()
    script: dict = {"calls": [], "s1": release_s1, **events}
    _patch_scripted_embed(instance, script)

    def start(tag, workload):
        t = threading.Thread(target=manager.embed, args=(workload, [tag]))
        t.start()
        return t

    def wait_for(predicate, timeout=10):
        deadline = time.time() + timeout
        while not predicate():
            assert time.time() < deadline, "等待闸状态超时"
            time.sleep(0.005)

    t_q1 = start("q1", WORKLOAD_QUERY_EMBEDDING)
    wait_for(lambda: manager._gpu_gate.busy)  # q1 在飞
    start("s1", WORKLOAD_SYNC_EMBEDDING)
    wait_for(lambda: manager._gpu_gate.sync_waiting == 1)  # s1 已登记等待
    assert script["calls"] == ["q1:start"]

    # 连续查询压力:每个查询在下一个启动前已排队(credit 随每次获取递增)
    threads = [t_q1]
    for i in range(2, quota + 2):  # q2..q{quota+1}:quota 次获取
        threads.append(start(f"q{i}", WORKLOAD_QUERY_EMBEDDING))
        wait_for(lambda: manager._gpu_gate.query_waiting == 1)
        events[f"q{i - 1}"].set()  # 放行前一个查询,让当前查询占用空档
        wait_for(lambda tag=f"q{i}": f"{tag}:start" in script["calls"])
    assert manager._gpu_gate.starvation_credit == quota  # 配额已计满
    assert manager._gpu_gate.sync_priority_active  # 公平窗口开启

    # 第 quota+2 个查询到得太晚:被公平窗口拦在 s1 之后
    threads.append(start(f"q{quota + 2}", WORKLOAD_QUERY_EMBEDDING))
    wait_for(lambda: manager._gpu_gate.query_waiting == 1)
    events[f"q{quota + 1}"].set()  # 放行最后一个查询,腾出空档
    wait_for(lambda: "s1:start" in script["calls"])  # ★ 等待中的 sync 终获执行
    assert f"q{quota + 2}:start" not in script["calls"], "公平窗口必须先让已等待的 sync 执行"

    release_s1.set()
    wait_for(lambda: "s1:end" in script["calls"])
    assert not manager._gpu_gate.sync_priority_active  # 一次性配额,用后即恢复查询优先
    assert manager._gpu_gate.starvation_credit == 0

    # 查询优先恢复:被拦的查询随后执行
    events[f"q{quota + 2}"].set()
    wait_for(lambda: f"q{quota + 2}:end" in script["calls"])
    for t in threads:
        t.join(timeout=15)
        assert not t.is_alive()
    ends = [c for c in script["calls"] if c.endswith(":end")]
    assert ends == [
        "q1:end",
        *(f"q{i}:end" for i in range(2, quota + 2)),
        "s1:end",
        f"q{quota + 2}:end",
    ]


def test_cpu_execution_is_not_gated():
    """B2 边界:CPU 执行(无显存峰)不入闸 —— 并发 CPU 批次允许重叠。"""
    manager, _, _ = _make_manager("cpu")
    manager._build({})
    assert manager._query_on_gpu is False and manager._sync_on_gpu is False
    instance = manager._embedder_for(WORKLOAD_QUERY_EMBEDDING)

    barrier = threading.Barrier(2, timeout=10)
    lock = threading.Lock()
    state = {"max": 0, "concurrent": 0}

    def overlap_embed(texts):
        with lock:
            state["concurrent"] += 1
            state["max"] = max(state["max"], state["concurrent"])
        barrier.wait()  # 若被闸串行化,此处的两方汇合将超时失败
        with lock:
            state["concurrent"] -= 1
        return [np.zeros(4, dtype=np.float32) for _ in texts]

    instance.embed = overlap_embed
    t_q = threading.Thread(target=manager.embed, args=(WORKLOAD_QUERY_EMBEDDING, ["q"]))
    t_s = threading.Thread(target=manager.embed, args=(WORKLOAD_SYNC_EMBEDDING, ["s"]))
    t_q.start()
    t_s.start()
    t_q.join(timeout=15)
    t_s.join(timeout=15)
    assert not t_q.is_alive() and not t_s.is_alive()
    assert state["max"] == 2


# --------------------------------------- B3/B4:驻留计划(预算驱动装配)


def test_plan_ladder_is_budget_driven():
    """B4(纯函数):同一硬件形态下,改变预算必须改变计划。"""
    dual = compute_residency_plan(5000, embedder_gpu=True, reranker_gpu=True)
    assert dual.mode == PLAN_DUAL_RESIDENT
    transient = compute_residency_plan(4096, embedder_gpu=True, reranker_gpu=True)
    assert transient.mode == PLAN_RERANKER_TRANSIENT
    insufficient = compute_residency_plan(3800, embedder_gpu=True, reranker_gpu=True)
    assert insufficient.mode == PLAN_GPU_INSUFFICIENT
    undecided = compute_residency_plan(None, embedder_gpu=True, reranker_gpu=True)
    assert undecided.mode == PLAN_UNDECIDED
    cpu_only = compute_residency_plan(4096, embedder_gpu=False, reranker_gpu=False)
    assert cpu_only.mode == "cpu_only"
    embedder_only = compute_residency_plan(4096, embedder_gpu=True, reranker_gpu=False)
    assert embedder_only.mode == "embedder_only"


def test_transient_plan_builds_transient_reranker_and_normal_capacity():
    """B3:4096MiB 有效预算(生产场景)→ 重排瞬态驻留;嵌入双 workload 照常。"""
    manager, _, _ = _make_manager(
        "cuda", gpu_snapshot=GpuMemorySnapshot(used_mb=6000, free_mb=9000, total_mb=15564)
    )
    manager._budget_mode = "manual"
    manager._manual_budget_mb = 4096  # 规划上限:min(4096, 9000+0) = 4096
    manager._build({})

    assert manager._plan.mode == PLAN_RERANKER_TRANSIENT
    # 重排权重真相 = 主机内存(瞬态);执行设备仍是 GPU(策略不静默降级)
    assert isinstance(manager._reranker, _TransientGpuReranker)
    assert manager.states[WORKLOAD_QUERY_RERANKER].residency == RESIDENCY_TRANSIENT
    assert manager.states[WORKLOAD_QUERY_RERANKER].effective.kind == "gpu"
    assert manager.states[WORKLOAD_QUERY_RERANKER].status == "loaded"
    # 嵌入仍 GPU 常驻(共享单实例)
    assert manager._query_on_gpu is True
    assert manager.states[WORKLOAD_QUERY_EMBEDDING].effective.kind == "gpu"
    # 计划不是 UNSAFE(4096 ≥ 瞬态下限);reranker 常驻份额未上卡(不全量硬载)
    assert manager.capacity()["state"] == CAPACITY_HEALTHY


def test_transient_rerank_materializes_and_offloads_per_call():
    """B3:瞬态重排 —— 调用即上卡(library 自动)、完成即卸载;语义不变。"""
    manager, _, _ = _make_manager(
        "cuda",
        gpu_snapshot=GpuMemorySnapshot(used_mb=6000, free_mb=9000, total_mb=15564),
        reranker_cls=FakeResidencyReranker,
    )
    manager._budget_mode = "manual"
    manager._manual_budget_mb = 4096
    manager._build({})
    assert isinstance(manager._reranker, _TransientGpuReranker)
    underlying = manager._reranker.underlying
    assert underlying.residency == "cpu"  # 启动时未上卡(B4:不全量硬载)

    scores = manager.rerank("q", ["a", "b"])
    assert scores == [0.5, 0.5]
    assert underlying.rerank_calls == 1
    assert underlying.offloads == 1  # 每次调用后卸载
    assert underlying.residency == "cpu"  # 卸载后权重回主机内存
    assert manager._reranker.offload_count == 1

    manager.rerank("q2", ["c"])
    assert underlying.offloads == 2


def test_r2_1_insufficient_budget_query_side_fail_closed_never_cpu():
    """R2-1:配置查询 GPU + 预算不足 ≠ Effective CPU 执行。

    查询嵌入/查询重排 fail-closed:不构造 CPU 替身(不自动降级)、不上 GPU
    冒险执行;拒绝执行并给出可操作指引;effective 不谎报为 CPU。
    """
    manager, created, created_rerankers = _make_manager(
        "cuda", gpu_snapshot=GpuMemorySnapshot(used_mb=6000, free_mb=9000, total_mb=15564)
    )
    manager._budget_mode = "manual"
    manager._manual_budget_mb = 3800  # 低于瞬态下限 4050
    manager._build({})

    assert manager._plan.mode == PLAN_GPU_INSUFFICIENT
    # 查询侧:configured=gpu 且 effective=gpu(不谎报为 CPU);状态显式 UNSAFE
    for workload in (WORKLOAD_QUERY_EMBEDDING, WORKLOAD_QUERY_RERANKER):
        state = manager.states[workload]
        assert state.configured.kind == "gpu"
        assert state.effective.kind == "gpu", "R2-1:禁止把查询侧 effective 谎报/改为 CPU"
        assert state.status == STATUS_UNSAFE_NO_PLAN
    # 未构造查询嵌入与重排的任何实例(GPU 不装配,CPU 替身不存在)
    assert manager._query_embedder is None
    assert manager._reranker is None
    assert all(e.device != "cuda" for e in created), "GPU 侧不得构造任何模型"
    assert created_rerankers == []
    # 查询侧执行被拒绝(带可操作指引),绝不悄悄跑 CPU
    with pytest.raises(UnsafeRuntimePlanError, match="调整设备策略"):
        manager.embed(WORKLOAD_QUERY_EMBEDDING, ["q"])
    with pytest.raises(UnsafeRuntimePlanError):
        manager.rerank("q", ["d"])
    # 真相面:UNSAFE + 行动要求;Admin 保持可用(快照完整)
    assert manager.capacity()["state"] == CAPACITY_UNSAFE
    snap = manager.snapshot()
    assert snap["runtime_plan"]["action_required"] is True
    assert len(snap["policies"]) == 3 and "devices" in snap


def test_r2_1_insufficient_budget_sync_background_continues_on_cpu_loud():
    """R2-1:sync 是后台工作负载 —— GPU 不可安全执行时按既有授权 CPU 路径
    继续(显式标注,非静默);查询侧 fail-closed 不受影响。"""
    manager, created, _ = _make_manager(
        "cuda", gpu_snapshot=GpuMemorySnapshot(used_mb=6000, free_mb=9000, total_mb=15564)
    )
    manager._budget_mode = "manual"
    manager._manual_budget_mb = 3800
    manager._build({})

    sync_state = manager.states[WORKLOAD_SYNC_EMBEDDING]
    assert sync_state.effective.kind == "cpu"
    assert sync_state.status == STATUS_PLAN_CPU  # 显式标注(非静默)
    # sync 仍可执行(CPU;created 里唯一的嵌入实例就是 sync 的 CPU 替身)
    vectors = manager.embed(WORKLOAD_SYNC_EMBEDDING, ["doc"])
    assert len(vectors) == 1
    assert [e.device for e in created] == ["cpu"]


def test_budget_change_marks_plan_restart_required():
    """B4:预算不是展示品 —— 改预算改变快照中的待重启计划。"""
    manager, _, _ = _make_manager(
        "cuda", gpu_snapshot=GpuMemorySnapshot(used_mb=6000, free_mb=9000, total_mb=15564)
    )
    manager._build({})  # auto 预算 = 9000+0 = 9000 → 双驻留
    snap = manager.snapshot()
    assert snap["runtime_plan"]["mode"] == PLAN_DUAL_RESIDENT
    assert snap["runtime_plan"]["restart_required"] is False

    manager._budget_mode = "manual"
    manager._manual_budget_mb = 4096  # 降到生产口径 → 待重启计划=瞬态
    snap = manager.snapshot()
    assert snap["runtime_plan"]["pending_mode"] == PLAN_RERANKER_TRANSIENT
    assert snap["runtime_plan"]["restart_required"] is True
    # 已执行计划未变(重启生效语义)
    assert snap["runtime_plan"]["mode"] == PLAN_DUAL_RESIDENT


# ------------------------------------------------------- 容量(§11/L/M)


def test_capacity_unsafe_when_free_below_query_peak():
    manager, _, _ = _make_manager(
        "cuda", gpu_snapshot=GpuMemorySnapshot(used_mb=15510, free_mb=126, total_mb=15564)
    )
    manager._build({})
    cap = manager.capacity()
    assert cap["state"] == CAPACITY_UNSAFE
    assert cap["budget_mb"] == 126  # auto = 当前空闲 + ASK-AI 驻留(此处无 CUDA 读数为 0)
    assert cap["gpu_free_mb"] == 126


def test_capacity_healthy_when_budget_covers_peak():
    manager, _, _ = _make_manager(
        "cuda", gpu_snapshot=GpuMemorySnapshot(used_mb=6000, free_mb=9000, total_mb=15564)
    )
    manager._build({})
    cap = manager.capacity()
    assert cap["state"] == CAPACITY_HEALTHY
    assert cap["budget_mb"] == 9000


def test_manual_budget_is_planning_cap_never_exceeds_hardware():
    manager, _, _ = _make_manager(
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
    manager, _, _ = _make_manager("cuda", gpu_snapshot=None)
    manager._build({})
    cap = manager.capacity()
    assert cap["state"] == "unknown"
    assert cap["gpu_free_mb"] is None


# ------------------------------------------------------- 真相面(§15/J)


def test_snapshot_reports_configured_effective_and_restart_required():
    manager, _, _ = _make_manager("cuda")
    manager._build({WORKLOAD_QUERY_RERANKER: ("cpu", None, "BAAI/bge-reranker-v2-m3")})
    snap = manager.snapshot()
    by_workload = {p["workload"]: p for p in snap["policies"]}
    assert len(snap["policies"]) == 3
    reranker = by_workload[WORKLOAD_QUERY_RERANKER]
    assert reranker["configured"]["kind"] == "cpu"
    assert reranker["restart_required"] is False  # 启动即按策略落地 → 无待重启
    assert reranker["status"] == "loaded"
    assert any(d["kind"] == "cpu" for d in snap["devices"])
    assert "runtime_plan" in snap


def test_gpu_missing_for_configured_uuid_fails_closed():
    manager, _, _ = _make_manager("cuda")
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
    manager, _, _ = _make_manager("cuda")
    manager._build({})
    assert manager.reranker.rerank("q", ["d"]) == [0.5]
