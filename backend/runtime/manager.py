"""硬件感知模型管理器(MODEL × WORKLOAD × DEVICE 单一权威)。

职责(执行契约 §4-§15 + REV1 B1-B4):
- 解析持久策略(model_runtime_policies;缺行 = EMBEDDER_DEVICE 引导默认);
- **B1 查询实例恒有**:query_embedding 始终构造并持有运行实例;同模型+同设备
  时 sync 复用同一实例(单一驻留不变量);不同设备 → 各自独立实例;
- **B2 GPU 执行协调**:_GpuGate 保证同卡嵌入批次互斥执行(无未受控并发显存
  峰),在线查询严格优先于后台同步(sync 新批次在有查询等待时不得启动;在飞
  sync 批次粒度有界 ≤ EMBEDDER_BATCH_SIZE,查询至多等待一个在飞批次);
- **B3 驻留计划**:GPU-selected ≠ 永久同时驻留。预算不足以双驻留时,重排模型
  按「瞬态驻留」运行(权重驻留主机内存,仅重排步骤上卡,完成即卸载);模型
  身份/打分语义零变化(同一 FlagReranker 实例,仅 .to(device));
- **B4 预算驱动**:有效 GPU 预算(Auto=实况推导 / Manual=规划上限)决定装配
  计划,不是展示品;UNSAFE 计划下 GPU 侧零装配且如实暴露 UNSAFE;
- **R2-1 fail-closed**:UNSAFE 计划下查询侧工作负载(查询嵌入/查询重排)
  不自动改跑 CPU(未经产品授权)、不上 GPU 冒险执行 —— 拒绝执行
  (UnsafeRuntimePlanError)并给出管理员可操作指引;sync 后台沿用既有
  授权 CPU 路径(显式标注,非静默);
- **R2-2 有界公平**:查询优先保留;已等待的 sync 批次在 SYNC_FAIRNESS_QUOTA
  次让路后获得一次执行权,持续查询压力下不会永久饥饿;
- **#14 保真**:sync 路径 CUDA 失败按既有分类(仅三类)单向回退 CPU(同模型),
  遥测三值 gpu/cpu/gpu_to_cpu 如实;查询路径无自动回退;
- **Configured ≠ Effective**:Admin 保存仅持久化 Configured;Effective 在
  (重)启动落地;重启生效是 V1 的确定性行为。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db.models import ModelRuntimePolicy, ModelRuntimeSetting
from backend.embedder.base import Embedder, Reranker
from backend.embedder.bge import BGEEmbedder, BGEReranker
from backend.embedder.fallback import CpuFallbackError, classify_cuda_failure
from backend.runtime.hardware import (
    GpuMemorySnapshot,
    discover_cpu,
    discover_gpus,
    normalize_gpu_uuid,
    read_gpu_memory,
)

logger = logging.getLogger(__name__)

WORKLOAD_QUERY_EMBEDDING = "query_embedding"
WORKLOAD_SYNC_EMBEDDING = "sync_embedding"
WORKLOAD_QUERY_RERANKER = "query_reranker"
WORKLOADS: tuple[str, ...] = (
    WORKLOAD_QUERY_EMBEDDING,
    WORKLOAD_SYNC_EMBEDDING,
    WORKLOAD_QUERY_RERANKER,
)

#: 查询路径峰值保留(实测:2026-09-04 生产查询嵌入单次分配请求 +490MiB)。
QUERY_PEAK_RESERVE_MB = 512

# ---------------------------------------------------------------------------
# 驻留规划常量(Discovery E1-E10 + 2026-09-03/04 生产实测推导;可调证据值,
# 不是产品「4GB」硬编码:同一公式在 8GB/24GB 卡上自动给出不同计划)。
# - 生产双模型稳态驻留实测 4044MiB;bge-reranker-v2-m3 fp16 权重 ≈1150MiB;
#   两者之差 ≈2894MiB 记为嵌入模型常驻份额(已含其工作区/上下文份额)。
# - 双驻留安全下限 = 嵌入常驻 + 重排常驻 + 查询峰值(嵌入步与重排不重叠的
#   单 Ask 序列 + 跨 Ask 由 B2 闸串行);生产实测口径下 ≈4562MiB > 4096MiB
#   有效预算 → 生产必然落入瞬态计划(这正是 B3 的命题)。
# - 瞬态模式显存峰(构造性上界) = max(嵌入步: 常驻+峰值, 重排步: 常驻+重排)
#   = max(3412, 4050) = 4050MiB ≤ 4096MiB, repeated-Ask 因此可行。
# ---------------------------------------------------------------------------
EMBEDDER_RESIDENT_MB = 2900
RERANKER_RESIDENT_MB = 1150

PLAN_CPU_ONLY = "cpu_only"  # 无任何 GPU 策略,无规划约束
PLAN_UNDECIDED = "undecided"  # 预算不可读:维持 v1.1 双驻留行为,容量如实 unknown
PLAN_DUAL_RESIDENT = "dual_resident"
PLAN_RERANKER_TRANSIENT = "reranker_transient"
PLAN_GPU_INSUFFICIENT = "gpu_insufficient"

CAPACITY_HEALTHY = "HEALTHY"
CAPACITY_LIMITED = "CAPACITY_LIMITED"
CAPACITY_UNSAFE = "UNSAFE"
CAPACITY_UNKNOWN = "unknown"

STATUS_LOADED = "loaded"
STATUS_FALLBACK = "fallback_gpu_to_cpu"
STATUS_PLAN_CPU = "cpu_by_capacity_plan"
STATUS_UNSAFE_NO_PLAN = "unsafe_no_safe_plan"

RESIDENCY_RESIDENT = "resident"
RESIDENCY_TRANSIENT = "transient"

_DEVICE_KIND_GPU = "gpu"
_DEVICE_KIND_CPU = "cpu"

#: R2-2 有界公平性:连续让路给查询的最大批次数;达到后,已等待的 sync 批次
#: 获得一次执行权(查询单元=单个嵌入批次,毫秒级;sync 最坏延迟被此配额界定)。
SYNC_FAIRNESS_QUOTA = 4


class UnsafeRuntimePlanError(RuntimeError):
    """UNSAFE 计划下的 fail-closed 语义(R2-1)。

    配置为 GPU 的查询侧工作负载(查询嵌入/查询重排)在有效预算内无安全
    运行计划时,既不自动改跑 CPU(未经产品授权),也不上 GPU 冒险执行
    (防不安全显存执行),而是拒绝执行并给出管理员可操作指引。
    """


@dataclass(frozen=True)
class DeviceSelection:
    """解析后的目标设备(kind + GPU UUID;cpu 时 uuid 为 None)。"""

    kind: str  # "gpu" | "cpu"
    gpu_uuid: str | None = None

    def key(self) -> tuple[str, str | None]:
        return (self.kind, self.gpu_uuid)


@dataclass
class WorkloadState:
    """单个 workload 的运行时真相(Configured / Effective / Status)。"""

    workload: str
    model_name: str
    configured: DeviceSelection
    effective: DeviceSelection
    status: str = STATUS_LOADED
    shared: bool = False
    residency: str = RESIDENCY_RESIDENT
    fallback_reason: str | None = None
    fallback_detail: str | None = None


@dataclass
class ResidencyPlan:
    """驻留装配计划(B4:由有效预算推导,决定运行时实际装配什么)。"""

    mode: str
    budget_mb: int | None
    floors_mb: dict[str, int] = field(default_factory=dict)
    reason: str = ""


def compute_residency_plan(
    budget_mb: int | None,
    *,
    embedder_gpu: bool,
    reranker_gpu: bool,
) -> ResidencyPlan:
    """按有效预算推导安全驻留计划(B3/B4 的决策核心,纯函数可测)。

    计划阶梯(仅约束 GPU 侧):
    - 预算不可读 → undecided(维持双驻留现状;容量观测如实 unknown);
    - 双驻留下限 = 嵌入常驻 + 重排常驻 + 查询峰值;
    - 瞬态下限 = max(嵌入步: 嵌入常驻 + 查询峰值,
                     重排步: 嵌入常驻 + 重排常驻);
    - 低于瞬态下限 → gpu_insufficient(运行时不得加载 GPU;查询侧 fail-closed
      拒绝执行,sync 后台按计划落 CPU)。
    """
    floors = {
        "dual_resident_mb": EMBEDDER_RESIDENT_MB + RERANKER_RESIDENT_MB + QUERY_PEAK_RESERVE_MB,
        "transient_mb": max(
            EMBEDDER_RESIDENT_MB + QUERY_PEAK_RESERVE_MB,
            EMBEDDER_RESIDENT_MB + RERANKER_RESIDENT_MB,
        ),
        "embedder_only_mb": EMBEDDER_RESIDENT_MB + QUERY_PEAK_RESERVE_MB,
    }
    if not embedder_gpu and not reranker_gpu:
        return ResidencyPlan(PLAN_CPU_ONLY, budget_mb, floors, "无 GPU 策略")
    if budget_mb is None:
        return ResidencyPlan(PLAN_UNDECIDED, budget_mb, floors, "GPU 预算不可读:维持双驻留现状")
    if reranker_gpu and budget_mb >= floors["dual_resident_mb"]:
        return ResidencyPlan(PLAN_DUAL_RESIDENT, budget_mb, floors, "预算可容纳双驻留+查询峰值")
    transient_floor = floors["transient_mb"] if reranker_gpu else floors["embedder_only_mb"]
    if budget_mb >= transient_floor:
        mode = PLAN_RERANKER_TRANSIENT if reranker_gpu else "embedder_only"
        return ResidencyPlan(mode, budget_mb, floors, "预算仅可容纳嵌入常驻;重排瞬态驻留")
    return ResidencyPlan(
        PLAN_GPU_INSUFFICIENT, budget_mb, floors, "预算低于瞬态下限:GPU 侧不装配(按计划落 CPU)"
    )


class _GpuGate:
    """同卡推理准入闸(B2/R2-2):互斥执行 + 查询优先 + 有界公平。

    - 任一时刻至多一个嵌入/瞬态重排批次在 GPU 上执行(无未受控并发显存峰);
    - 查询优先:sync 新批次在「有查询等待」时不得启动;在飞 sync 批次粒度
      有界(≤ EMBEDDER_BATCH_SIZE),查询至多等待一个在飞批次;
    - **有界公平**(R2-2):连续让路给查询的批次达到 SYNC_FAIRNESS_QUOTA 后,
      下一个空档让给已等待的 sync(一次一批);sync 在持续查询压力下最坏
      延迟被配额界定,不会永久饥饿;查询在配额窗口内保持优先;
    - rerank 仅在瞬态计划下入闸(query 优先级),使瞬态显存峰构造性有界。
    """

    def __init__(self, fairness_quota: int = SYNC_FAIRNESS_QUOTA) -> None:
        self._cond = threading.Condition()
        self._busy = False
        self._query_waiting = 0
        self._sync_waiters = 0
        self._sync_priority = False  # 公平性激活:下个空档让已等待的 sync 先行
        self._starvation_credit = 0
        self._fairness_quota = max(1, fairness_quota)

    @property
    def query_waiting(self) -> int:
        with self._cond:
            return self._query_waiting

    @property
    def sync_waiting(self) -> int:
        with self._cond:
            return self._sync_waiters

    @property
    def busy(self) -> bool:
        with self._cond:
            return self._busy

    @property
    def sync_priority_active(self) -> bool:
        with self._cond:
            return self._sync_priority

    @property
    def starvation_credit(self) -> int:
        with self._cond:
            return self._starvation_credit

    @contextmanager
    def query(self):
        with self._cond:
            self._query_waiting += 1
            try:
                # sync_priority 只在有 sync 等待者时拦查询;等待者消失即解除
                while self._busy or (self._sync_priority and self._sync_waiters > 0):
                    self._cond.wait()
                self._busy = True
                # 查询在 sync 等待者存在时抢到空档 → 计入饥饿账本
                if self._sync_waiters > 0:
                    self._starvation_credit += 1
                    if self._starvation_credit >= self._fairness_quota:
                        self._sync_priority = True
            finally:
                self._query_waiting -= 1
        try:
            yield
        finally:
            with self._cond:
                self._busy = False
                if self._sync_waiters == 0:
                    self._sync_priority = False
                    self._starvation_credit = 0
                self._cond.notify_all()

    @contextmanager
    def sync(self):
        with self._cond:
            self._sync_waiters += 1
            try:
                while self._busy or (self._query_waiting > 0 and not self._sync_priority):
                    self._cond.wait()
                self._busy = True
                if self._sync_priority:
                    # 公平配额:一次性执行权,用后即恢复查询优先
                    self._sync_priority = False
                    self._starvation_credit = 0
            finally:
                self._sync_waiters -= 1
        try:
            yield
        finally:
            with self._cond:
                self._busy = False
                if self._sync_waiters == 0:
                    self._sync_priority = False
                    self._starvation_credit = 0
                self._cond.notify_all()


def _is_cuda(kind: str) -> bool:
    return kind == _DEVICE_KIND_GPU


class ModelRuntimeManager:
    """单一 GPU/模型所有权权威;以协议代理暴露给查询与摄取路径。"""

    def __init__(
        self,
        settings,
        *,
        embedder_factory: Callable[..., Embedder] = BGEEmbedder,
        reranker_factory: Callable[..., Reranker] = BGEReranker,
        gpu_memory_reader: Callable[[str | None], GpuMemorySnapshot | None] = read_gpu_memory,
    ) -> None:
        self._settings = settings
        self._embedder_factory = embedder_factory
        self._reranker_factory = reranker_factory
        self._gpu_memory_reader = gpu_memory_reader
        self._gpu_gate = _GpuGate()
        self._lock = threading.Lock()
        # B1:查询嵌入实例始终构造并持有(在线查询是第一优先级)
        self._query_embedder: Embedder | None = None
        self._query_on_gpu: bool = False
        # sync 独立设备实例(仅当 sync 与 query 配置不同设备时存在)
        self._sync_embedder_override: Embedder | None = None
        self._sync_on_gpu: bool = False
        # sync 专用 CPU 回退实例(单向;仅 sync workload 使用)
        self._sync_cpu_embedder: Embedder | None = None
        # 重排:_reranker 为原生实例(双驻留/CPU)或 _TransientGpuReranker(瞬态)
        self._reranker: Reranker | None = None
        self._reranker_transient: bool = False
        self._reranker_gpu_device: str | None = None
        self.states: dict[str, WorkloadState] = {}
        self._budget_mode = "auto"
        self._manual_budget_mb: int | None = None
        self._plan: ResidencyPlan | None = None
        self._executed_plan_mode: str | None = None
        self._loaded = False

    # ------------------------------------------------------------- 启动装配

    async def load(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        """读取持久策略并构造模型(lifespan 调用;语义与既有启动等价)。"""
        async with session_factory() as session:
            policies = await self._read_policies(session)
            await self._read_budget_setting(session)
        self._build(policies)
        self._loaded = True

    async def _read_policies(self, session: AsyncSession) -> dict[str, tuple[str, str | None, str]]:
        rows = (await session.execute(select(ModelRuntimePolicy))).scalars().all()
        return {
            # REV3:历史行可能存有 torch 裸形 uuid(规范化前写入)——读取期归一化
            # 为规范形,与 discover_gpus 的身份表示对齐(向后兼容,§3 身份契约)。
            r.workload: (r.device_kind, normalize_gpu_uuid(r.gpu_uuid), r.model_name)
            for r in rows
            if r.workload in WORKLOADS
        }

    async def _read_budget_setting(self, session: AsyncSession) -> None:
        row = await session.get(ModelRuntimeSetting, "gpu_budget")
        if row is not None:
            self._budget_mode = row.mode if row.mode in {"auto", "manual"} else "auto"
            self._manual_budget_mb = row.manual_budget_mb

    def _default_selection(self) -> DeviceSelection:
        """无持久策略时的引导默认 = EMBEDDER_DEVICE(与 v1.1 之前一致)。"""
        raw = (getattr(self._settings, "embedder_device", "auto") or "auto").strip()
        if raw.lower() == _DEVICE_KIND_CPU:
            return DeviceSelection(kind=_DEVICE_KIND_CPU)
        return DeviceSelection(kind=_DEVICE_KIND_GPU)

    def _configured_for(
        self,
        policies: dict[str, tuple[str, str | None, str]],
        workload: str,
    ) -> DeviceSelection:
        if workload in policies:
            kind, uuid, _ = policies[workload]
            return DeviceSelection(kind=kind, gpu_uuid=uuid)
        return self._default_selection()

    def _build_embedder(self, selection: DeviceSelection) -> Embedder:
        """按设备选择构造嵌入实例(原始设备串直传,由嵌入器自行 detect_device)。"""
        if selection.kind == _DEVICE_KIND_CPU:
            return self._embedder_factory(device=_DEVICE_KIND_CPU)
        if selection.gpu_uuid:
            gpus = {g.uuid: g for g in discover_gpus()}
            gpu = gpus.get(selection.gpu_uuid)
            if gpu is None:
                raise RuntimeError(
                    f"配置的 GPU 不存在或不可见: uuid={selection.gpu_uuid}"
                    "(fail-closed;请核对 model_runtime_policies 或恢复该设备)"
                )
            return self._embedder_factory(device=f"cuda:{gpu.index}")
        return self._embedder_factory(device="cuda")

    def _gpu_device_str(self, selection: DeviceSelection) -> str:
        if selection.gpu_uuid:
            return f"cuda:{self._gpu_index(selection)}"
        return "cuda"

    def _build(self, policies: dict[str, tuple[str, str | None, str]]) -> None:
        model_names = {
            WORKLOAD_QUERY_EMBEDDING: "BAAI/bge-m3",
            WORKLOAD_SYNC_EMBEDDING: "BAAI/bge-m3",
            WORKLOAD_QUERY_RERANKER: "BAAI/bge-reranker-v2-m3",
        }
        configured = {w: self._configured_for(policies, w) for w in WORKLOADS}

        # 单一驻留:同 kind+同 uuid(含同为 cpu)的两个 embedding workload 共享
        share = (
            configured[WORKLOAD_QUERY_EMBEDDING].key() == configured[WORKLOAD_SYNC_EMBEDDING].key()
        )
        query_sel = configured[WORKLOAD_QUERY_EMBEDDING]
        sync_sel = configured[WORKLOAD_SYNC_EMBEDDING]
        reranker_sel = configured[WORKLOAD_QUERY_RERANKER]

        # B4:预算 → 驻留计划(先于任何模型构造;UNSAFE 不许先全量硬载)
        budget_mb = self._effective_budget_mb()
        plan = compute_residency_plan(
            budget_mb,
            embedder_gpu=query_sel.kind == _DEVICE_KIND_GPU or sync_sel.kind == _DEVICE_KIND_GPU,
            reranker_gpu=reranker_sel.kind == _DEVICE_KIND_GPU,
        )
        self._plan = plan
        self._executed_plan_mode = plan.mode
        insufficient = plan.mode == PLAN_GPU_INSUFFICIENT

        # B1 + R2-1:查询实例始终持有;但 UNSAFE 计划下查询侧工作负载
        # fail-closed —— 既不自动改跑 CPU(未经产品授权),也不上 GPU 冒险
        # (防不安全执行),拒绝执行并给出管理员可操作指引(Admin 保持可用)。
        if query_sel.kind == _DEVICE_KIND_GPU and insufficient:
            effective_query = query_sel  # 无实例在执行;effective 不谎报为 CPU
            self._query_embedder = None
            self._query_on_gpu = False
        else:
            effective_query = query_sel
            self._query_embedder = self._build_embedder(query_sel)
            self._query_on_gpu = effective_query.kind == _DEVICE_KIND_GPU

        # sync 是后台工作负载:GPU 不可安全执行时按计划落 CPU(#14 谱系的
        # 既有授权 CPU 路径;显式状态标注,非静默)。与查询实例不共享
        # (查询侧在 UNSAFE 下无实例,共享无从谈起)。
        if share and self._query_embedder is not None:
            self._sync_embedder_override = None
            effective_sync = effective_query
            self._sync_on_gpu = self._query_on_gpu
        elif sync_sel.kind == _DEVICE_KIND_GPU and insufficient:
            effective_sync = DeviceSelection(kind=_DEVICE_KIND_CPU)
            self._sync_embedder_override = self._embedder_factory(device=_DEVICE_KIND_CPU)
            self._sync_on_gpu = False
        else:
            effective_sync = sync_sel
            self._sync_embedder_override = None if share else self._build_embedder(sync_sel)
            self._sync_on_gpu = effective_sync.kind == _DEVICE_KIND_GPU

        # B3:重排装配三态(双驻留 / 瞬态 / 按计划 CPU);模型身份与打分语义零变化
        self._reranker_transient = False
        if reranker_sel.kind == _DEVICE_KIND_GPU:
            if insufficient:
                # R2-1:重排不自动落 CPU(未经产品授权);fail-closed 无实例,
                # rerank() 拒绝执行并给出可操作指引;effective 不谎报为 CPU。
                effective_reranker = reranker_sel
                self._reranker = None
                reranker_residency = RESIDENCY_RESIDENT
            else:
                effective_reranker = reranker_sel
                self._reranker_gpu_device = self._gpu_device_str(reranker_sel)
                if plan.mode == PLAN_RERANKER_TRANSIENT:
                    # 权重驻留主机内存,仅重排步骤上卡(FlagEmbedding compute
                    # 自带 .half()+.to(device);代理负责完成即卸载)
                    self._reranker = _TransientGpuReranker(
                        self,
                        self._reranker_factory(device=self._reranker_gpu_device),
                        self._reranker_gpu_device,
                    )
                    self._reranker_transient = True
                    reranker_residency = RESIDENCY_TRANSIENT
                else:
                    self._reranker = self._reranker_factory(device=self._reranker_gpu_device)
                    reranker_residency = RESIDENCY_RESIDENT
        else:
            effective_reranker = reranker_sel
            self._reranker = self._reranker_factory(device=_DEVICE_KIND_CPU)
            reranker_residency = RESIDENCY_RESIDENT

        self.states = {
            WORKLOAD_QUERY_EMBEDDING: WorkloadState(
                workload=WORKLOAD_QUERY_EMBEDDING,
                model_name=model_names[WORKLOAD_QUERY_EMBEDDING],
                configured=configured[WORKLOAD_QUERY_EMBEDDING],
                effective=effective_query,
                shared=share,
            ),
            WORKLOAD_SYNC_EMBEDDING: WorkloadState(
                workload=WORKLOAD_SYNC_EMBEDDING,
                model_name=model_names[WORKLOAD_SYNC_EMBEDDING],
                configured=sync_sel,
                effective=effective_sync,
                shared=share and self._query_embedder is not None,
            ),
            WORKLOAD_QUERY_RERANKER: WorkloadState(
                workload=WORKLOAD_QUERY_RERANKER,
                model_name=model_names[WORKLOAD_QUERY_RERANKER],
                configured=reranker_sel,
                effective=effective_reranker,
                residency=reranker_residency,
            ),
        }
        # 状态真相:UNSAFE 计划下查询侧 GPU 工作负载显式标注(无实例在执行);
        # sync 后台按计划落 CPU 的既有授权路径显式标注(非静默)。
        if insufficient:
            if query_sel.kind == _DEVICE_KIND_GPU:
                self.states[WORKLOAD_QUERY_EMBEDDING].status = STATUS_UNSAFE_NO_PLAN
            if reranker_sel.kind == _DEVICE_KIND_GPU:
                self.states[WORKLOAD_QUERY_RERANKER].status = STATUS_UNSAFE_NO_PLAN
            if sync_sel.kind == _DEVICE_KIND_GPU:
                self.states[WORKLOAD_SYNC_EMBEDDING].status = STATUS_PLAN_CPU
        for state in self.states.values():
            if (
                state.effective.kind == _DEVICE_KIND_CPU
                and state.configured.kind == _DEVICE_KIND_GPU
            ):
                state.status = STATUS_PLAN_CPU
        logger.info(
            "model runtime 计划:%s(预算=%sMiB);embedding=%s reranker=%s",
            plan.mode,
            budget_mb,
            "GPU" if self._query_on_gpu else "CPU",
            ("GPU/瞬态" if self._reranker_transient else effective_reranker.kind.upper()),
        )

    def _gpu_index(self, selection: DeviceSelection) -> int:
        if selection.gpu_uuid:
            for gpu in discover_gpus():
                if gpu.uuid == selection.gpu_uuid:
                    return gpu.index
        return 0

    # ------------------------------------------------------------- 容量事实

    def _read_gpu_facts(self) -> tuple[str | None, GpuMemorySnapshot | None, int | None]:
        """(gpu_uuid, nvidia-smi 快照, ASK-AI 常驻 MiB);失败项如实 None。"""
        state = self.states.get(WORKLOAD_QUERY_EMBEDDING)
        gpu_uuid = None
        if state is not None and state.effective.kind == _DEVICE_KIND_GPU:
            gpu_uuid = state.effective.gpu_uuid
        gpus = discover_gpus()
        if gpu_uuid is None and gpus:
            gpu_uuid = gpus[0].uuid

        askai_resident_mb: int | None = None
        try:
            import torch

            if torch.cuda.is_available():
                askai_resident_mb = int(
                    max(torch.cuda.memory_reserved(0), torch.cuda.memory_allocated(0))
                    // (1024 * 1024)
                )
        except Exception:  # noqa: BLE001 - 容量观测失败不破坏推理
            askai_resident_mb = None

        # 显存快照始终读取:即便未解析到 GPU UUID 也读默认卡,
        # 避免「已配置 GPU 却因 uuid 缺失而容量永远未知」的观测盲区。
        snapshot = self._gpu_memory_reader(gpu_uuid)
        return gpu_uuid, snapshot, askai_resident_mb

    def _effective_budget_mb(self) -> int | None:
        """有效 GPU 预算:auto=空闲+ASK-AI 驻留(实况);manual=min(手动, 实况)。

        manual 是规划上限而非 cgroup 硬限;观测缺失 → None(计划退化 undecided)。
        """
        _, snapshot, askai_resident_mb = self._read_gpu_facts()
        free_mb = snapshot.free_mb if snapshot else None
        if free_mb is None:
            return None
        if self._budget_mode == "manual" and self._manual_budget_mb:
            return min(self._manual_budget_mb, free_mb + (askai_resident_mb or 0))
        return free_mb + (askai_resident_mb or 0)

    # ------------------------------------------------------------- 推理路径

    def _embedder_for(self, workload: str) -> Embedder | None:
        """返回当前实例;UNSAFE 计划下查询侧可能为 None(由 embed() 拒绝执行)。"""
        if workload == WORKLOAD_QUERY_EMBEDDING:
            return self._query_embedder
        if workload == WORKLOAD_SYNC_EMBEDDING:
            # 回退实例优先:sync 一旦单向落到 CPU,后续批次必须继续走 CPU
            if self._sync_cpu_embedder is not None:
                return self._sync_cpu_embedder
            if self._sync_embedder_override is not None:
                return self._sync_embedder_override
            return self._query_embedder  # 单一驻留:sync 复用查询实例
        raise KeyError(f"unknown embedding workload: {workload}")

    def _raise_unsafe_plan(self, workload: str) -> UnsafeRuntimePlanError:
        return UnsafeRuntimePlanError(
            f"workload={workload}: 无安全运行计划(有效 GPU 预算不足,配置为 GPU 的"
            "查询侧工作负载拒绝自动降级 CPU 或冒险执行)。请管理员在「模型配置 →"
            "模型运行」调整设备策略或提高 GPU 运行预算,或释放 GPU 显存后重启。"
        )

    def embed(self, workload: str, texts: list[str]) -> list[np.ndarray]:
        """workload 嵌入入口(同步阻塞;调用方负责线程池)。

        B2:GPU 执行的嵌入批次经 _GpuGate 互斥入闸;CPU 执行(含回退后)
        不占闸 —— 无显存峰问题,不过度串行化。
        """
        if workload not in (WORKLOAD_QUERY_EMBEDDING, WORKLOAD_SYNC_EMBEDDING):
            raise KeyError(f"unknown embedding workload: {workload}")
        instance = self._embedder_for(workload)
        if instance is None:
            # R2-1:UNSAFE 计划 fail-closed —— 不自动降级 CPU,不上 GPU 冒险
            raise self._raise_unsafe_plan(workload)
        if workload == WORKLOAD_SYNC_EMBEDDING:
            if not self._sync_on_gpu:
                return instance.embed(texts)
            try:
                with self._gpu_gate.sync():
                    return instance.embed(texts)
            except Exception as exc:
                reason = classify_cuda_failure(exc)
                if reason is None or self.states[WORKLOAD_SYNC_EMBEDDING].effective.kind == (
                    _DEVICE_KIND_CPU
                ):
                    raise
                return self._fallback_sync_to_cpu(reason, exc, texts)
        if self._query_on_gpu:
            with self._gpu_gate.query():
                return instance.embed(texts)
        return instance.embed(texts)

    def _fallback_sync_to_cpu(
        self, reason: str, exc: Exception, texts: list[str]
    ) -> list[np.ndarray]:
        """#14 保真:GPU 批次 CUDA 失败单向回退 CPU(同模型;闸已释放)。"""
        state = self.states[WORKLOAD_SYNC_EMBEDDING]
        # 单向 GPU→CPU,仅 sync workload;查询实例不动
        with self._lock:
            if self._sync_cpu_embedder is None:
                logger.warning("sync 嵌入 CUDA 故障(%s),单向回退 CPU(查询实例不受影响)", reason)
                self._sync_cpu_embedder = self._embedder_factory(device=_DEVICE_KIND_CPU)
        self._sync_on_gpu = False
        state.effective = DeviceSelection(kind=_DEVICE_KIND_CPU)
        state.status = STATUS_FALLBACK
        state.fallback_reason = reason
        state.fallback_detail = f"{type(exc).__name__}: {exc}"[:500]
        try:
            return self._sync_cpu_embedder.embed(texts)
        except Exception as cpu_exc:
            raise CpuFallbackError(
                f"CPU fallback failed after {reason}: {cpu_exc}",
                reason=reason,
            ) from cpu_exc

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        """查询重排入口(query_reranker;无自动设备回退,与现状一致)。"""
        if self._reranker is None:
            # R2-1:UNSAFE 计划 fail-closed(不自动降级 CPU,不上 GPU 冒险)
            raise self._raise_unsafe_plan(WORKLOAD_QUERY_RERANKER)
        return self._reranker.rerank(query, documents)

    # ------------------------------------------------------------- 真相面

    @property
    def embedder(self) -> Embedder:
        """查询嵌入协议代理(HybridSearcher 消费;B1 恒有实例)。"""
        return _QueryEmbedderProxy(self)

    @property
    def reranker(self) -> Reranker:
        return _RerankerProxy(self)

    def device_label(self, selection: DeviceSelection) -> str:
        if selection.kind == _DEVICE_KIND_CPU:
            return discover_cpu().label
        for gpu in discover_gpus():
            if selection.gpu_uuid is None or gpu.uuid == selection.gpu_uuid:
                return gpu.label
        return selection.gpu_uuid or "GPU"

    def runtime_plan_snapshot(self) -> dict:
        """B4/R2-1 真相面:当前生效计划 + 预算变化后的待重启计划 + 行动要求。"""
        executed = self._executed_plan_mode
        current = self.current_plan()
        return {
            "mode": executed,
            "budget_mb": self._plan.budget_mb if self._plan else None,
            "floors_mb": self._plan.floors_mb if self._plan else {},
            "reason": self._plan.reason if self._plan else "",
            "action_required": executed == PLAN_GPU_INSUFFICIENT,
            "pending_mode": current.mode,
            "restart_required": executed is not None
            and current.mode not in (None, executed)
            and current.mode != PLAN_UNDECIDED,
        }

    def current_plan(self) -> ResidencyPlan:
        """按「当前预算设置」重算计划(与已执行计划对比暴露 restart_required)。"""
        embedder_gpu = (
            self.states[WORKLOAD_QUERY_EMBEDDING].configured.kind == _DEVICE_KIND_GPU
            or self.states[WORKLOAD_SYNC_EMBEDDING].configured.kind == _DEVICE_KIND_GPU
        )
        reranker_gpu = self.states[WORKLOAD_QUERY_RERANKER].configured.kind == _DEVICE_KIND_GPU
        return compute_residency_plan(
            self._effective_budget_mb(), embedder_gpu=embedder_gpu, reranker_gpu=reranker_gpu
        )

    def snapshot(self) -> dict:
        """Admin 真相面:devices + policies(configured/effective/status)+ plan。"""
        devices = [
            {
                "kind": "gpu",
                "uuid": g.uuid,
                "index": g.index,
                "label": g.label,
                "name": g.name,
                "total_memory_mb": g.total_memory_mb,
            }
            for g in discover_gpus()
        ]
        cpu = discover_cpu()
        devices.append(
            {
                "kind": "cpu",
                "uuid": None,
                "index": None,
                "label": cpu.label,
                "name": cpu.model,
                "logical_cores": cpu.logical_cores,
                "total_memory_mb": cpu.total_memory_mb,
            }
        )
        policies = []
        for workload in WORKLOADS:
            state = self.states[workload]
            policies.append(
                {
                    "workload": workload,
                    "model_name": state.model_name,
                    "configured": {
                        "kind": state.configured.kind,
                        "gpu_uuid": state.configured.gpu_uuid,
                        "label": self.device_label(state.configured),
                    },
                    "effective": {
                        "kind": state.effective.kind,
                        "gpu_uuid": state.effective.gpu_uuid,
                        "label": self.device_label(state.effective),
                    },
                    "status": state.status,
                    "shared": state.shared,
                    "residency": state.residency,
                    "fallback_reason": state.fallback_reason,
                    "fallback_detail": state.fallback_detail,
                    "restart_required": (
                        state.configured.key() != state.effective.key()
                        and state.status not in (STATUS_FALLBACK, STATUS_PLAN_CPU)
                    ),
                }
            )
        shared = (
            self.states[WORKLOAD_QUERY_EMBEDDING].shared
            and self.states[WORKLOAD_SYNC_EMBEDDING].status != STATUS_FALLBACK
        )
        return {
            "devices": devices,
            "policies": policies,
            "shared_embedding_runtime": shared,
            "runtime_plan": self.runtime_plan_snapshot(),
            "capacity": self.capacity(),
        }

    def capacity(self) -> dict:
        """容量真相:预算(auto=硬件实况推导 / manual=规划上限)+ 分级状态。"""
        gpu_uuid, snapshot, askai_resident_mb = self._read_gpu_facts()
        total_mb = snapshot.total_mb if snapshot else None
        used_mb = snapshot.used_mb if snapshot else None
        free_mb = snapshot.free_mb if snapshot else None

        budget_mb: int | None = None
        if free_mb is not None:
            if self._budget_mode == "manual" and self._manual_budget_mb:
                budget_mb = min(self._manual_budget_mb, free_mb + (askai_resident_mb or 0))
            else:
                budget_mb = free_mb + (askai_resident_mb or 0)

        capacity_state = CAPACITY_UNKNOWN
        if free_mb is not None:
            if free_mb < QUERY_PEAK_RESERVE_MB:
                capacity_state = CAPACITY_UNSAFE
            elif budget_mb is not None:
                needed = (askai_resident_mb or 0) + QUERY_PEAK_RESERVE_MB
                capacity_state = CAPACITY_HEALTHY if budget_mb >= needed else CAPACITY_LIMITED
            else:
                capacity_state = CAPACITY_HEALTHY
        # B4:计划不足 = UNSAFE(且运行时未加载 GPU 模型;先拒载后如实报告)
        if self._plan is not None and self._plan.mode == PLAN_GPU_INSUFFICIENT:
            capacity_state = CAPACITY_UNSAFE

        return {
            "state": capacity_state,
            "budget_mode": self._budget_mode,
            "budget_mb": budget_mb,
            "gpu_uuid": gpu_uuid,
            "gpu_total_mb": total_mb,
            "gpu_used_mb": used_mb,
            "gpu_free_mb": free_mb,
            "askai_resident_mb": askai_resident_mb,
            "peak_reserve_mb": QUERY_PEAK_RESERVE_MB,
        }

    async def save_policy(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        workload: str,
        *,
        device_kind: str,
        gpu_uuid: str | None,
    ) -> dict:
        """持久化 Configured Device(重启生效;不触碰 Effective)。"""
        if workload not in WORKLOADS:
            raise ValueError(f"unknown workload: {workload}")
        if device_kind not in (_DEVICE_KIND_GPU, _DEVICE_KIND_CPU):
            raise ValueError(f"unknown device kind: {device_kind}")
        if device_kind == _DEVICE_KIND_GPU:
            if not gpu_uuid:
                raise ValueError("gpu policy requires gpu_uuid")
            known = {g.uuid for g in discover_gpus()}
            if gpu_uuid not in known:
                raise ValueError(f"unknown gpu uuid: {gpu_uuid}")
        else:
            gpu_uuid = None
        state = self.states[workload]
        async with session_factory() as session:
            row = await session.get(ModelRuntimePolicy, workload)
            if row is None:
                row = ModelRuntimePolicy(workload=workload)
                session.add(row)
            row.model_name = state.model_name
            row.device_kind = device_kind
            row.gpu_uuid = gpu_uuid
            await session.commit()
        state.configured = DeviceSelection(kind=device_kind, gpu_uuid=gpu_uuid)
        return self.workload_snapshot(workload)

    async def save_gpu_budget(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        mode: str,
        manual_budget_mb: int | None,
    ) -> dict:
        if mode not in ("auto", "manual"):
            raise ValueError(f"unknown budget mode: {mode}")
        if mode == "manual":
            if manual_budget_mb is None or manual_budget_mb <= 0:
                raise ValueError("manual budget requires positive manual_budget_mb")
        else:
            manual_budget_mb = None
        async with session_factory() as session:
            row = await session.get(ModelRuntimeSetting, "gpu_budget")
            if row is None:
                row = ModelRuntimeSetting(key="gpu_budget")
                session.add(row)
            row.mode = mode
            row.manual_budget_mb = manual_budget_mb
            await session.commit()
        self._budget_mode = mode
        self._manual_budget_mb = manual_budget_mb
        return self.capacity()

    def workload_snapshot(self, workload: str) -> dict:
        state = self.states[workload]
        return {
            "workload": workload,
            "model_name": state.model_name,
            "configured": {
                "kind": state.configured.kind,
                "gpu_uuid": state.configured.gpu_uuid,
                "label": self.device_label(state.configured),
            },
            "effective": {
                "kind": state.effective.kind,
                "gpu_uuid": state.effective.gpu_uuid,
                "label": self.device_label(state.effective),
            },
            "status": state.status,
            "shared": state.shared,
            "residency": state.residency,
            "restart_required": (
                state.configured.key() != state.effective.key()
                and state.status not in (STATUS_FALLBACK, STATUS_PLAN_CPU)
            ),
        }


class _TransientGpuReranker:
    """瞬态驻留重排代理(B3):重排步骤按需上卡,完成即卸载。

    - 模型身份/打分语义零变化:同一 FlagReranker 实例,仅 .to(device);
      FlagEmbedding compute_score_single_gpu 自带 .half()+.to(device),
      本代理在调用后把权重送回主机内存并 empty_cache;
    - 与嵌入批次共用 _GpuGate(query 优先级)入闸,使瞬态模式显存峰
      构造性有界(嵌入常驻 + 重排常驻,见 compute_residency_plan);
    - 串行化取舍:瞬态计划下并发 Ask 的重排步骤排队(生产有效预算 4096MiB
      下双驻留不安全,这是 B3 的最小安全解);双驻留计划下不走本代理。
    """

    def __init__(self, manager: ModelRuntimeManager, underlying: Reranker, gpu_device: str) -> None:
        self._manager = manager
        self._underlying = underlying
        self._gpu_device = gpu_device
        self._lock = threading.Lock()
        self.offload_count = 0

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        with self._manager._gpu_gate.query(), self._lock:
            try:
                return self._underlying.rerank(query, documents)
            finally:
                self._underlying.gpu_residency_offload()
                self.offload_count += 1

    @property
    def underlying(self) -> Reranker:
        return self._underlying


class _QueryEmbedderProxy(Embedder):
    """查询嵌入协议代理(HybridSearcher 消费;转发 B1 恒有实例)。"""

    def __init__(self, manager: ModelRuntimeManager) -> None:
        self._manager = manager

    @property
    def dimension(self) -> int:
        inner = self._manager._embedder_for(WORKLOAD_QUERY_EMBEDDING)
        if inner is None:
            raise self._manager._raise_unsafe_plan(WORKLOAD_QUERY_EMBEDDING)
        return inner.dimension

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        return self._manager.embed(WORKLOAD_QUERY_EMBEDDING, texts)


class _RerankerProxy(Reranker):
    """查询重排协议代理(rag pipeline 消费)。"""

    def __init__(self, manager: ModelRuntimeManager) -> None:
        self._manager = manager

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        return self._manager.rerank(query, documents)
