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
- **Configured ≠ Effective + 显式 Apply**:Admin 保存仅持久化 Configured;
  Effective 在(重)启动落地,或由管理员显式「应用更改」(apply)在本生命周期内
  落地。apply = 候选装配 + 原子换装:先按最新持久配置完整装配候选运行时
  (UNSAFE 计划/GPU 缺失/模型加载失败 → 拒绝且当前运行时零改动),成功才在
  锁内原子提交;差量重建(设备未变的 workload 复用既有实例,不产生同卡
  双驻留),换装后被替换实例由在飞调用自然用完再回收。
"""

from __future__ import annotations

import asyncio
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


class ApplyRejectedError(RuntimeError):
    """Apply 候选装配被拒绝(fail-before-mutate;当前 Effective Runtime 未改变)。

    触发面(契约:T-MODEL-RUNTIME-APPLY):
    - ``capacity_unsafe``:候选计划为 gpu_insufficient(先拒装配,不先全量硬载);
    - ``build_failed``:配置 GPU 不存在/不可见,或模型加载失败;
    - ``not_loaded``:运行时尚未完成启动装配。
    失败路径保证旧运行时完整可用(构造期零 self 突变,提交是最后一步)。
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


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


@dataclass
class _RuntimeAssembly:
    """一次完整装配的候选产物(先构造后提交,支撑 Apply 的原子换装)。

    ``built_from`` 记录本装配的输入选择,供下次 Apply 做差量重建:
    设备未变的 workload 复用既有实例(避免同卡双驻留与无谓重载)。
    """

    query_embedder: Embedder | None
    query_on_gpu: bool
    sync_embedder_override: Embedder | None
    sync_on_gpu: bool
    reranker: Reranker | None
    reranker_transient: bool
    reranker_gpu_device: str | None
    states: dict[str, WorkloadState]
    plan: ResidencyPlan
    built_from: dict[str, DeviceSelection]


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
        # Apply 串行锁(覆盖 读取现状→候选装配→提交 全程;与 _lock 分离,
        # 候选装配不阻塞在线查询的实例捕获读)
        self._apply_lock = threading.Lock()
        # 配置纪元:save_policy / save_gpu_budget 在 DB 提交后同锁推进;
        # Apply 在读快照时捕获、提交时校验——旧快照的 Apply 一律拒决
        # (REV1 Save/Apply 竞态守卫:持久 Configured 是唯一权威,永不被
        # 旧快照覆盖或隐藏)。由 self._lock 保护。
        self._config_version = 0
        # 装配纪元:每次提交(启动 load / Apply)递增;Admin/日志证据用
        self._generation = 0
        # 当前装配的输入选择(Apply 差量重建的对比基准)
        self._built_from: dict[str, DeviceSelection] = {}
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
            budget_mode, manual_budget_mb = await self._read_budget_setting(session)
        self._budget_mode = budget_mode
        self._manual_budget_mb = manual_budget_mb
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

    async def _read_budget_setting(self, session: AsyncSession) -> tuple[str, int | None]:
        """读取 GPU 预算设置(纯读;由调用方决定提交时机,Apply 失败不污染色)。"""
        row = await session.get(ModelRuntimeSetting, "gpu_budget")
        if row is None:
            return "auto", None
        mode = row.mode if row.mode in {"auto", "manual"} else "auto"
        return mode, row.manual_budget_mb

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
        """装配并立即提交(启动路径;Apply 走 _apply_policies 的候选-提交两段)。"""
        asm = self._assemble(policies, self._budget_mode, self._manual_budget_mb)
        self._commit(asm, self._budget_mode, self._manual_budget_mb)

    def _assemble(
        self,
        policies: dict[str, tuple[str, str | None, str]],
        budget_mode: str,
        manual_budget_mb: int | None,
    ) -> _RuntimeAssembly:
        """候选装配(纯构造,失败即抛,零 self 突变)。

        与上一装配差量对比(_built_from):设备未变的 workload 复用既有
        实例 —— Apply 不产生同卡双驻留,也不无谓重载模型。UNSAFE 计划下
        查询侧 GPU 工作负载不构造实例(R2-1;启动路径可达,Apply 已先行拒绝)。
        """
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
        budget_mb = self._effective_budget_mb(budget_mode, manual_budget_mb)
        plan = compute_residency_plan(
            budget_mb,
            embedder_gpu=query_sel.kind == _DEVICE_KIND_GPU or sync_sel.kind == _DEVICE_KIND_GPU,
            reranker_gpu=reranker_sel.kind == _DEVICE_KIND_GPU,
        )
        insufficient = plan.mode == PLAN_GPU_INSUFFICIENT

        # 差量重建判定(对比当前装配的输入选择)
        prev = self._built_from or {}
        prev_query_sel = prev.get(WORKLOAD_QUERY_EMBEDDING)
        prev_sync_sel = prev.get(WORKLOAD_SYNC_EMBEDDING)
        prev_reranker_sel = prev.get(WORKLOAD_QUERY_RERANKER)
        prev_share = (
            prev_query_sel is not None
            and prev_sync_sel is not None
            and prev_query_sel.key() == prev_sync_sel.key()
        )
        query_rebuild = (
            prev_query_sel is None
            or configured[WORKLOAD_QUERY_EMBEDDING].key() != prev_query_sel.key()
        )
        # sync 重建面:自身选择变化 / 共享关系变化 / 历史一次性回退待重置
        # (Apply=重新物化,与重启语义一致;实例缺失的退化装配同样触发)
        sync_rebuild = (
            prev_sync_sel is None
            or configured[WORKLOAD_SYNC_EMBEDDING].key() != prev_sync_sel.key()
            or share != prev_share
            or self._sync_cpu_embedder is not None
        )
        reranker_rebuild = (
            prev_reranker_sel is None
            or reranker_sel.key() != prev_reranker_sel.key()
            or plan.mode != self._executed_plan_mode
            or self._reranker is None
        )
        # 历史一次性回退待重置(Apply=重新物化):共享模式下被 OOM 过的正是
        # 共享实例本身 → 连带重建 query,换得全新共享运行时(与重启语义一致)
        fallback_reset = self._sync_cpu_embedder is not None
        if fallback_reset and share:
            query_rebuild = True

        # B1 + R2-1:查询实例始终持有;但 UNSAFE 计划下查询侧工作负载
        # fail-closed —— 既不自动改跑 CPU(未经产品授权),也不上 GPU 冒险
        # (防不安全执行),拒绝执行并给出管理员可操作指引(Admin 保持可用)。
        if query_sel.kind == _DEVICE_KIND_GPU and insufficient:
            effective_query = query_sel  # 无实例在执行;effective 不谎报为 CPU
            query_embedder = None
            query_on_gpu = False
        elif query_rebuild:
            effective_query = query_sel
            query_embedder = self._build_embedder(query_sel)
            query_on_gpu = effective_query.kind == _DEVICE_KIND_GPU
        else:
            effective_query = query_sel
            query_embedder = self._query_embedder
            query_on_gpu = self._query_on_gpu

        # sync 是后台工作负载:GPU 不可安全执行时按计划落 CPU(#14 谱系的
        # 既有授权 CPU 路径;显式状态标注,非静默)。与查询实例不共享
        # (查询侧在 UNSAFE 下无实例,共享无从谈起)。
        if share and query_embedder is not None:
            sync_embedder_override = None
            effective_sync = effective_query
            sync_on_gpu = query_on_gpu
        elif sync_sel.kind == _DEVICE_KIND_GPU and insufficient:
            effective_sync = DeviceSelection(kind=_DEVICE_KIND_CPU)
            sync_embedder_override = self._embedder_factory(device=_DEVICE_KIND_CPU)
            sync_on_gpu = False
        elif sync_rebuild:
            effective_sync = sync_sel
            sync_embedder_override = self._build_embedder(sync_sel)
            sync_on_gpu = effective_sync.kind == _DEVICE_KIND_GPU
        else:
            effective_sync = sync_sel
            sync_embedder_override = self._sync_embedder_override
            sync_on_gpu = self._sync_on_gpu

        # B3:重排装配三态(双驻留 / 瞬态 / 按计划 CPU);模型身份与打分语义零变化
        reranker_transient = False
        reranker_gpu_device = self._reranker_gpu_device  # 复用分支保持现值
        if reranker_sel.kind == _DEVICE_KIND_GPU:
            if insufficient:
                # R2-1:重排不自动落 CPU(未经产品授权);fail-closed 无实例,
                # rerank() 拒绝执行并给出可操作指引;effective 不谎报为 CPU。
                effective_reranker = reranker_sel
                reranker = None
                reranker_residency = RESIDENCY_RESIDENT
            else:
                effective_reranker = reranker_sel
                reranker_gpu_device = self._gpu_device_str(reranker_sel)
                if plan.mode == PLAN_RERANKER_TRANSIENT:
                    # 权重驻留主机内存,仅重排步骤上卡(FlagEmbedding compute
                    # 自带 .half()+.to(device);代理负责完成即卸载)
                    reranker = (
                        _TransientGpuReranker(
                            self,
                            self._reranker_factory(device=reranker_gpu_device),
                            reranker_gpu_device,
                        )
                        if reranker_rebuild
                        else self._reranker
                    )
                    reranker_transient = True
                    reranker_residency = RESIDENCY_TRANSIENT
                else:
                    reranker = (
                        self._reranker_factory(device=reranker_gpu_device)
                        if reranker_rebuild
                        else self._reranker
                    )
                    reranker_residency = RESIDENCY_RESIDENT
        else:
            effective_reranker = reranker_sel
            reranker = (
                self._reranker_factory(device=_DEVICE_KIND_CPU)
                if reranker_rebuild
                else self._reranker
            )
            reranker_residency = RESIDENCY_RESIDENT

        states = {
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
                shared=share and query_embedder is not None,
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
                states[WORKLOAD_QUERY_EMBEDDING].status = STATUS_UNSAFE_NO_PLAN
            if reranker_sel.kind == _DEVICE_KIND_GPU:
                states[WORKLOAD_QUERY_RERANKER].status = STATUS_UNSAFE_NO_PLAN
            if sync_sel.kind == _DEVICE_KIND_GPU:
                states[WORKLOAD_SYNC_EMBEDDING].status = STATUS_PLAN_CPU
        for state in states.values():
            if (
                state.effective.kind == _DEVICE_KIND_CPU
                and state.configured.kind == _DEVICE_KIND_GPU
            ):
                state.status = STATUS_PLAN_CPU
        logger.info(
            "model runtime 候选装配:%s(预算=%sMiB);embedding=%s reranker=%s",
            plan.mode,
            budget_mb,
            "GPU" if query_on_gpu else "CPU",
            ("GPU/瞬态" if reranker_transient else effective_reranker.kind.upper()),
        )
        return _RuntimeAssembly(
            query_embedder=query_embedder,
            query_on_gpu=query_on_gpu,
            sync_embedder_override=sync_embedder_override,
            sync_on_gpu=sync_on_gpu,
            reranker=reranker,
            reranker_transient=reranker_transient,
            reranker_gpu_device=reranker_gpu_device,
            states=states,
            plan=plan,
            built_from=dict(configured),
        )

    def _commit(
        self,
        asm: _RuntimeAssembly,
        budget_mode: str,
        manual_budget_mb: int | None,
        expected_config_version: int | None = None,
    ) -> None:
        """原子提交候选装配(锁内整组赋值;读侧经 _lock 捕获一致快照)。

        REV1 Save/Apply 竞态守卫:``expected_config_version`` 非空时(Apply
        路径),若读快照后有新的配置保存落地(设备策略或 GPU 预算),整体
        拒决 —— 旧快照候选绝不覆盖/隐藏更新的持久 Configured。
        """
        with self._lock:
            if (
                expected_config_version is not None
                and self._config_version != expected_config_version
            ):
                raise ApplyRejectedError(
                    "config_changed",
                    "应用更改期间检测到新的配置保存(设备策略或 GPU 预算)。"
                    "当前运行配置未改变,线上查询不受影响;"
                    "请重新点击「应用更改」以应用最新保存的配置。",
                )
            self._query_embedder = asm.query_embedder
            self._query_on_gpu = asm.query_on_gpu
            self._sync_embedder_override = asm.sync_embedder_override
            self._sync_on_gpu = asm.sync_on_gpu
            # 历史一次性回退实例随换装作废(Apply=重新物化;重建判定已保证
            # 回退过的 sync 必被重建,此处只清指针不留悬空状态)
            self._sync_cpu_embedder = None
            self._reranker = asm.reranker
            self._reranker_transient = asm.reranker_transient
            self._reranker_gpu_device = asm.reranker_gpu_device
            self.states = asm.states
            self._plan = asm.plan
            self._executed_plan_mode = asm.plan.mode
            self._built_from = asm.built_from
            self._budget_mode = budget_mode
            self._manual_budget_mb = manual_budget_mb
            self._generation += 1
            self._loaded = True  # 至少完成一次装配提交;Apply 由此放行
        logger.info(
            "model runtime 已提交(generation=%s,plan=%s)",
            self._generation,
            asm.plan.mode,
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

    def _effective_budget_mb(
        self,
        budget_mode: str | None = None,
        manual_budget_mb: int | None = None,
    ) -> int | None:
        """有效 GPU 预算:auto=空闲+ASK-AI 驻留(实况);manual=min(手动, 实况)。

        manual 是规划上限而非 cgroup 硬限;观测缺失 → None(计划退化 undecided)。
        参数缺省 = 当前已提交设置(Apply 传候选值,做「假如应用」的预演)。
        """
        mode = budget_mode if budget_mode in ("auto", "manual") else self._budget_mode
        manual = manual_budget_mb if manual_budget_mb is not None else self._manual_budget_mb
        _, snapshot, askai_resident_mb = self._read_gpu_facts()
        free_mb = snapshot.free_mb if snapshot else None
        if free_mb is None:
            return None
        if mode == "manual" and manual:
            return min(manual, free_mb + (askai_resident_mb or 0))
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
        换装一致性:在锁内一次性捕获(实例 + 设备事实),执行在锁外 ——
        Apply 原子换装后,在飞批次用完旧实例,新批次即用新装配。
        """
        if workload not in (WORKLOAD_QUERY_EMBEDDING, WORKLOAD_SYNC_EMBEDDING):
            raise KeyError(f"unknown embedding workload: {workload}")
        with self._lock:
            instance = self._embedder_for(workload)
            sync_on_gpu = self._sync_on_gpu
            query_on_gpu = self._query_on_gpu
        if instance is None:
            # R2-1:UNSAFE 计划 fail-closed —— 不自动降级 CPU,不上 GPU 冒险
            raise self._raise_unsafe_plan(workload)
        if workload == WORKLOAD_SYNC_EMBEDDING:
            if not sync_on_gpu:
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
        if query_on_gpu:
            with self._gpu_gate.query():
                return instance.embed(texts)
        return instance.embed(texts)

    def _fallback_sync_to_cpu(
        self, reason: str, exc: Exception, texts: list[str]
    ) -> list[np.ndarray]:
        """#14 保真:GPU 批次 CUDA 失败单向回退 CPU(同模型;闸已释放)。"""
        state = self.states[WORKLOAD_SYNC_EMBEDDING]
        # 单向 GPU→CPU,仅 sync workload;查询实例不动(锁内完成状态突变,
        # 与 Apply 换装的提交互斥)
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
        with self._lock:
            reranker = self._reranker
        if reranker is None:
            # R2-1:UNSAFE 计划 fail-closed(不自动降级 CPU,不上 GPU 冒险)
            raise self._raise_unsafe_plan(WORKLOAD_QUERY_RERANKER)
        return reranker.rerank(query, documents)

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
        """B4/R2-1 真相面:当前生效计划 + 预算变化后的待生效计划 + 行动要求。"""
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
            # 装配纪元:启动 load=1,每次成功 Apply +1;Admin/日志据其确认
            # 「应用更改」确实落到了当前进程的运行时
            "generation": self._generation,
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

    def _commit_saved_config(self, workload: str, selection: DeviceSelection) -> None:
        """save_policy 的内存侧(DB 提交成功后调用)。

        REV1 契约:内存 configured 与配置纪元同锁原子推进 —— 纪元不变
        ⇔ 无新保存落地;Apply 以此在提交时检出旧快照。
        """
        with self._lock:
            self.states[workload].configured = selection
            self._config_version += 1

    def _commit_saved_budget(self, mode: str, manual_budget_mb: int | None) -> None:
        """save_gpu_budget 的内存侧(DB 提交成功后调用;同上原子推进纪元)。"""
        with self._lock:
            self._budget_mode = mode
            self._manual_budget_mb = manual_budget_mb
            self._config_version += 1

    async def save_policy(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        workload: str,
        *,
        device_kind: str,
        gpu_uuid: str | None,
    ) -> dict:
        """持久化 Configured Device(「应用更改」或重启生效;不触碰 Effective)。

        顺序契约:DB 提交成功 → 同锁推进配置纪元 + 内存 configured;
        进行中的 Apply 在提交时检出纪元变化即整体拒决(旧快照不覆盖新保存)。
        """
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
        self._commit_saved_config(workload, DeviceSelection(kind=device_kind, gpu_uuid=gpu_uuid))
        return self.workload_snapshot(workload)

    async def apply(self, session_factory: async_sessionmaker[AsyncSession]) -> dict:
        """显式生效(「应用更改」):重读持久配置 → 候选装配 → 原子换装。

        契约(T-MODEL-RUNTIME-APPLY):
        - 成功:Effective == Configured,restart_required 归零,本生命周期内生效;
        - 失败(ApplyRejectedError):当前 Effective Runtime 零改动,线上查询
          完整可用(候选构造期不碰任何 self 突变,提交是最后一步);
        - Save/Apply 顺序契约(REV1):读快照时捕获配置纪元,提交时校验;
          读快照后落地的保存 → 本轮拒决(config_changed),持久 Configured
          保持权威且 pending 可见,管理员重试即应用最新配置;
        - 不经 Docker/进程重启;模型装载走独立线程,不阻塞事件循环
          (生产 504 教训:进程内长阻塞 = /health 全超时)。
        """
        if not self._loaded:
            raise ApplyRejectedError("not_loaded", "模型运行时尚未完成启动装配,暂不能应用更改")
        async with session_factory() as session:
            policies = await self._read_policies(session)
            budget_mode, manual_budget_mb = await self._read_budget_setting(session)
        with self._lock:
            config_version_at_read = self._config_version
        return await asyncio.to_thread(
            self._apply_policies,
            policies,
            budget_mode,
            manual_budget_mb,
            config_version_at_read,
        )

    def _apply_policies(
        self,
        policies: dict[str, tuple[str, str | None, str]],
        budget_mode: str,
        manual_budget_mb: int | None,
        config_version_at_read: int | None = None,
    ) -> dict:
        """Apply 同步核心(独立线程内执行;_apply_lock 串行化多次 Apply)。"""
        if not self._loaded:
            raise ApplyRejectedError("not_loaded", "模型运行时尚未完成启动装配,暂不能应用更改")
        with self._apply_lock:
            # 1) 候选计划预演:UNSAFE 先拒(先拒装配,不先全量硬载,R2-1 谱系)
            embedder_gpu = (
                self._configured_for(policies, WORKLOAD_QUERY_EMBEDDING).kind == _DEVICE_KIND_GPU
                or self._configured_for(policies, WORKLOAD_SYNC_EMBEDDING).kind == _DEVICE_KIND_GPU
            )
            reranker_gpu = (
                self._configured_for(policies, WORKLOAD_QUERY_RERANKER).kind == _DEVICE_KIND_GPU
            )
            plan = compute_residency_plan(
                self._effective_budget_mb(budget_mode, manual_budget_mb),
                embedder_gpu=embedder_gpu,
                reranker_gpu=reranker_gpu,
            )
            if plan.mode == PLAN_GPU_INSUFFICIENT:
                raise ApplyRejectedError(
                    "capacity_unsafe",
                    "应用更改被拒绝:候选配置无安全运行计划"
                    f"(有效 GPU 预算 {plan.budget_mb}MiB 低于瞬态下限 "
                    f"{plan.floors_mb.get('transient_mb', 0)}MiB)。"
                    "当前运行配置未改变,线上查询不受影响;"
                    "请提高 GPU 运行预算、释放显存,或将部分工作负载改为 CPU 后重试。",
                )
            # 2) 候选装配:GPU 缺失/模型加载失败在此抛出(fail-before-mutate)
            try:
                asm = self._assemble(policies, budget_mode, manual_budget_mb)
            except ApplyRejectedError:
                raise
            except Exception as exc:
                raise ApplyRejectedError(
                    "build_failed",
                    f"应用更改失败:候选运行时装配出错({exc})。"
                    "当前运行配置未改变,线上查询不受影响;"
                    "请核对设备策略与 GPU 可见性后重试。",
                ) from exc
            # 3) 原子提交(锁内整组赋值;含 REV1 配置纪元守卫:读快照后有
            #    新保存落地 → 整体拒决,旧快照不覆盖持久 Configured)
            self._commit(
                asm,
                budget_mode,
                manual_budget_mb,
                expected_config_version=config_version_at_read,
            )
        # 4) 被替换实例回收(在飞调用持有自身引用,自然用完;此处仅加速
        #    循环引用回收与显存归还,best-effort 不影响正确性)
        self._release_superseded_models()
        logger.info(
            "model runtime Apply 完成:rebuilt 差量见上方候选装配日志(generation=%s)",
            self._generation,
        )
        return self.snapshot()

    def _release_superseded_models(self) -> None:
        """换装后被替换模型的确定性回收(best-effort;不触碰在飞调用)。"""
        try:
            import gc

            gc.collect()
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:  # 回收失败不影响运行时正确性
            logger.debug("superseded model release best-effort failed", exc_info=True)

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
        self._commit_saved_budget(mode, manual_budget_mb)
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
        with self._manager._lock:
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
