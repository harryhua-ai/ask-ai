"""硬件感知模型运行时管理器(MODEL × WORKLOAD × DEVICE 单一权威)。

职责(执行契约 §4-§15):
- 解析持久策略(model_runtime_policies;缺行 = EMBEDDER_DEVICE 引导默认,
  行为与 v1.1 之前逐字节一致);
- **单一驻留**:query_embedding 与 sync_embedding 同模型+同 GPU 时共享同一
  嵌入实例(§6 不变量);不同设备 → 允许独立实例;
- **在线优先**:sync_embedding 的 GPU 并发被信号量有界(≤1 批),批粒度
  让路在线查询;队列/重试沿用既有 sync_requests 上限,本模块不加新队列;
- **#14 保真**:sync 路径 CUDA 失败按既有分类(仅三类)单向回退 CPU(同
  模型),遥测三值 gpu/cpu/gpu_to_cpu 如实;查询路径无自动回退(与现状
  一致,是否补齐属独立产品决策);
- **Configured ≠ Effective**:Admin 保存仅持久化 Configured;Effective 在
  (重)启动落地;重启生效是 V1 的确定性行为;
- **容量**:预算默认 Automatic(硬件实况推导),Manual 为规划上限;Effective
  可用容量永不超过硬件实况;状态 HEALTHY / CAPACITY_LIMITED / UNSAFE /
  unknown,阈值由实测证据推导(查询峰值保留 512MiB ≈ 生产实测 490MiB),
  不硬编码任何「4GB 产品常量」。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db.models import ModelRuntimePolicy, ModelRuntimeSetting
from backend.embedder.base import Embedder, Reranker
from backend.embedder.bge import BGEEmbedder, BGEReranker
from backend.embedder.fallback import CpuFallbackError, classify_cuda_failure
from backend.runtime.hardware import discover_cpu, discover_gpus, read_gpu_memory

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

CAPACITY_HEALTHY = "HEALTHY"
CAPACITY_LIMITED = "CAPACITY_LIMITED"
CAPACITY_UNSAFE = "UNSAFE"
CAPACITY_UNKNOWN = "unknown"

STATUS_LOADED = "loaded"
STATUS_FALLBACK = "fallback_gpu_to_cpu"
STATUS_PENDING_RESTART = "pending_restart"

_DEVICE_KIND_GPU = "gpu"
_DEVICE_KIND_CPU = "cpu"


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
    fallback_reason: str | None = None
    fallback_detail: str | None = None


@dataclass
class CapacitySnapshot:
    """容量真相(全部证据字段;未知项显式 None,不臆造)。"""

    state: str
    budget_mode: str
    budget_mb: int | None
    gpu_uuid: str | None
    gpu_total_mb: int | None
    gpu_used_mb: int | None
    gpu_free_mb: int | None
    askai_resident_mb: int | None
    peak_reserve_mb: int


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
        gpu_memory_reader: Callable[[str], object] = read_gpu_memory,
        sync_gpu_concurrency: int = 1,
    ) -> None:
        self._settings = settings
        self._embedder_factory = embedder_factory
        self._reranker_factory = reranker_factory
        self._gpu_memory_reader = gpu_memory_reader
        self._sync_semaphore = threading.Semaphore(max(1, sync_gpu_concurrency))
        self._lock = threading.Lock()
        # 单一驻留嵌入实例(同模型+同设备的两个 embedding workload 共享)
        self._shared_embedder: Embedder | None = None
        self._shared_device: DeviceSelection | None = None
        # sync 独立设备实例(仅当 sync 与 query 配置不同设备时存在)
        self._sync_embedder_override: Embedder | None = None
        self._sync_device_override: DeviceSelection | None = None
        # sync 专用 CPU 回退实例(单向;仅 sync workload 使用)
        self._sync_cpu_embedder: Embedder | None = None
        self._reranker: Reranker | None = None
        self.states: dict[str, WorkloadState] = {}
        self._budget_mode = "auto"
        self._manual_budget_mb: int | None = None
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
            r.workload: (r.device_kind, r.gpu_uuid, r.model_name)
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

        # 查询实例始终构造(在线查询是第一优先级);共享时 sync 复用同一实例,
        # 不共享时 sync 另建独立实例(§9 不同设备允许独立驻留)。
        query_embedder = self._build_embedder(query_sel)
        self._shared_embedder = query_embedder if share else None
        self._shared_device = query_sel if share else None
        self._sync_device_override = None if share else sync_sel
        if not share:
            self._sync_embedder_override = self._build_embedder(sync_sel)
        self._reranker = self._reranker_factory(
            device=(
                f"cuda:{self._gpu_index(reranker_sel)}"
                if reranker_sel.kind == _DEVICE_KIND_GPU
                else _DEVICE_KIND_CPU
            )
        )

        self.states = {
            WORKLOAD_QUERY_EMBEDDING: WorkloadState(
                workload=WORKLOAD_QUERY_EMBEDDING,
                model_name=model_names[WORKLOAD_QUERY_EMBEDDING],
                configured=configured[WORKLOAD_QUERY_EMBEDDING],
                effective=query_sel,
                shared=share,
            ),
            WORKLOAD_SYNC_EMBEDDING: WorkloadState(
                workload=WORKLOAD_SYNC_EMBEDDING,
                model_name=model_names[WORKLOAD_SYNC_EMBEDDING],
                configured=sync_sel,
                effective=sync_sel,
                shared=share,
            ),
            WORKLOAD_QUERY_RERANKER: WorkloadState(
                workload=WORKLOAD_QUERY_RERANKER,
                model_name=model_names[WORKLOAD_QUERY_RERANKER],
                configured=reranker_sel,
                effective=reranker_sel,
            ),
        }

    def _gpu_index(self, selection: DeviceSelection) -> int:
        if selection.gpu_uuid:
            for gpu in discover_gpus():
                if gpu.uuid == selection.gpu_uuid:
                    return gpu.index
        return 0

    # ------------------------------------------------------------- 推理路径

    def _embedder_for(self, workload: str) -> Embedder:
        if workload == WORKLOAD_QUERY_EMBEDDING:
            return self._shared_embedder
        if workload == WORKLOAD_SYNC_EMBEDDING:
            # 回退实例优先:sync 一旦单向落到 CPU,后续批次必须继续走 CPU
            if self._sync_cpu_embedder is not None:
                return self._sync_cpu_embedder
            if self._shared_embedder is not None:
                return self._shared_embedder
            return self._sync_embedder_override
        raise KeyError(f"unknown embedding workload: {workload}")

    def embed(self, workload: str, texts: list[str]) -> list[np.ndarray]:
        """workload 嵌入入口(同步阻塞;调用方负责线程池)。"""
        if workload not in (WORKLOAD_QUERY_EMBEDDING, WORKLOAD_SYNC_EMBEDDING):
            raise KeyError(f"unknown embedding workload: {workload}")
        if workload == WORKLOAD_SYNC_EMBEDDING:
            with self._sync_semaphore:
                return self._embed_sync(texts)
        return self._embedder_for(workload).embed(texts)

    def _embed_sync(self, texts: list[str]) -> list[np.ndarray]:
        instance = self._embedder_for(WORKLOAD_SYNC_EMBEDDING)
        try:
            return instance.embed(texts)
        except Exception as exc:
            reason = classify_cuda_failure(exc)
            state = self.states[WORKLOAD_SYNC_EMBEDDING]
            if reason is None or state.effective.kind == _DEVICE_KIND_CPU:
                raise
            # #14 保真:单向 GPU→CPU(同模型),仅 sync workload;查询实例不动
            with self._lock:
                if self._sync_cpu_embedder is None:
                    logger.warning(
                        "sync 嵌入 CUDA 故障(%s),单向回退 CPU(查询实例不受影响)",
                        reason,
                    )
                    self._sync_cpu_embedder = self._embedder_factory(device=_DEVICE_KIND_CPU)
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
        return self._reranker.rerank(query, documents)

    # ------------------------------------------------------------- 真相面

    @property
    def embedder(self) -> Embedder:
        """查询嵌入协议代理(HybridSearcher 消费;单一驻留实例)。"""
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

    def snapshot(self) -> dict:
        """Admin 真相面:devices + policies(configured/effective/status)+ shared。"""
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
                    "fallback_reason": state.fallback_reason,
                    "fallback_detail": state.fallback_detail,
                    "restart_required": state.configured.key() != state.effective.key()
                    and state.status != STATUS_FALLBACK,
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
            "capacity": self.capacity(),
        }

    def capacity(self) -> dict:
        """容量真相:预算(auto=硬件实况推导 / manual=规划上限)+ 分级状态。"""
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
        total_mb = snapshot.total_mb if snapshot else None
        used_mb = snapshot.used_mb if snapshot else None
        free_mb = snapshot.free_mb if snapshot else None

        budget_mb: int | None = None
        if self._budget_mode == "manual" and self._manual_budget_mb:
            budget_mb = self._manual_budget_mb
            if free_mb is not None:
                budget_mb = min(budget_mb, free_mb + (askai_resident_mb or 0))
        elif free_mb is not None:
            budget_mb = free_mb + (askai_resident_mb or 0)

        capacity_state = CAPACITY_UNKNOWN
        if free_mb is not None:
            if free_mb < QUERY_PEAK_RESERVE_MB:
                capacity_state = CAPACITY_UNSAFE
            elif budget_mb is not None and state is not None:
                needed = (askai_resident_mb or 0) + QUERY_PEAK_RESERVE_MB
                capacity_state = CAPACITY_HEALTHY if budget_mb >= needed else CAPACITY_LIMITED
            else:
                capacity_state = CAPACITY_HEALTHY

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
            "restart_required": state.configured.key() != state.effective.key()
            and state.status != STATUS_FALLBACK,
        }


class _QueryEmbedderProxy(Embedder):
    """查询嵌入协议代理(HybridSearcher 消费;转发单一驻留实例)。"""

    def __init__(self, manager: ModelRuntimeManager) -> None:
        self._manager = manager

    @property
    def dimension(self) -> int:
        inner = self._manager._embedder_for(WORKLOAD_QUERY_EMBEDDING)
        return inner.dimension

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        return self._manager.embed(WORKLOAD_QUERY_EMBEDDING, texts)


class _RerankerProxy(Reranker):
    """查询重排协议代理(rag pipeline 消费)。"""

    def __init__(self, manager: ModelRuntimeManager) -> None:
        self._manager = manager

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        return self._manager.rerank(query, documents)
