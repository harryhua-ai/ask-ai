"""Sync-only GPU-first embedding fallback.

The online API owns its BGE and reranker lifecycles.  This module is used by
the sync runner only: it selects the configured device, probes a CUDA model
once, and permits at most one transition from CUDA to a freshly constructed
CPU embedder.
"""

from __future__ import annotations

import gc
import logging
import os
from collections.abc import Callable
from typing import Literal

import numpy as np

from backend.embedder.base import Embedder, detect_device
from backend.embedder.bge import BGEEmbedder

logger = logging.getLogger(__name__)

FailureCode = Literal["cuda_init_failure", "cuda_oom", "cuda_runtime_error"]

CUDA_INIT_FAILURE: FailureCode = "cuda_init_failure"
CUDA_OOM: FailureCode = "cuda_oom"
CUDA_RUNTIME_ERROR: FailureCode = "cuda_runtime_error"
ELIGIBLE_FAILURE_CODES = frozenset(
    {CUDA_INIT_FAILURE, CUDA_OOM, CUDA_RUNTIME_ERROR}
)

DEVICE_GPU = "gpu"
DEVICE_CPU = "cpu"
DEVICE_GPU_TO_CPU = "gpu_to_cpu"

_GPU_PROBE_TEXT = "sync embedding device probe"
_MAX_DETAIL_LENGTH = 500


def _exception_chain(exc: BaseException):
    """Yield an exception and its short explicit cause/context chain."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _exception_detail(exc: BaseException) -> str:
    """Return bounded diagnostic text without changing the original error."""
    return f"{type(exc).__name__}: {exc}"[:_MAX_DETAIL_LENGTH]


def _exception_text(exc: BaseException) -> str:
    return " ".join(
        f"{type(item).__module__}.{type(item).__name__} {item}".lower()
        for item in _exception_chain(exc)
    )


def _is_cuda_oom(exc: BaseException, text: str) -> bool:
    for item in _exception_chain(exc):
        module = type(item).__module__.lower()
        name = type(item).__name__.lower()
        if name in {"outofmemoryerror", "cudaoutofmemoryerror"} and (
            "torch" in module or "cuda" in module or "gpu" in module
        ):
            return True
    return (
        "out of memory" in text
        and ("cuda" in text or "gpu" in text)
    ) or "cuda memoryerror" in text


def _is_cuda_init_failure(exc: BaseException, text: str) -> bool:
    if "cuda error" in text and any(
        marker in text for marker in ("initialization", "initialise", "initialize")
    ):
        return True
    if any(
        marker in text
        for marker in (
            "cuinit",
            "cuda initialization",
            "cuda init",
            "initialize cuda",
            "initializing cuda",
            "cuda driver initialization",
            "no cuda-capable device",
            "no nvidia driver",
            "driver version is insufficient",
            "cuda is not available",
            "cuda unavailable",
            "nvml",
        )
    ):
        return True
    return any(
        "initial" in type(item).__name__.lower()
        and "cuda" in f"{type(item).__module__}.{type(item).__name__}".lower()
        for item in _exception_chain(exc)
    )


def _is_cuda_runtime_error(exc: BaseException, text: str) -> bool:
    if any(
        marker in text
        for marker in (
            "cuda error",
            "cuda runtime",
            "cuda driver",
            "cublas",
            "cudnn",
            "nccl",
            "device-side assert",
            "illegal memory access",
            "no kernel image is available",
            "launch failure",
        )
    ):
        return True
    return any(
        "cuda" in f"{type(item).__module__}.{type(item).__name__}".lower()
        and "error" in type(item).__name__.lower()
        for item in _exception_chain(exc)
    )


def classify_cuda_failure(exc: BaseException) -> FailureCode | None:
    """Classify only explicit CUDA runtime/resource failures.

    ``None`` is intentional: parsing, connector, vector-store, validation,
    and application errors must remain on the existing failure path and must
    never select a CPU model.
    """
    text = _exception_text(exc)
    if _is_cuda_oom(exc, text):
        return CUDA_OOM
    if _is_cuda_init_failure(exc, text):
        return CUDA_INIT_FAILURE
    if _is_cuda_runtime_error(exc, text):
        return CUDA_RUNTIME_ERROR
    return None


def _is_cuda_device(device: str) -> bool:
    normalized = device.strip().lower()
    return normalized == "cuda" or normalized.startswith("cuda:")


def _cpu_fallback_enabled() -> bool:
    value = os.environ.get("EMBEDDER_CPU_FALLBACK", "on").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _release_cuda_resources() -> None:
    """Best-effort cleanup before constructing the CPU model.

    Cleanup errors do not make a non-CUDA exception eligible for fallback; the
    caller has already made that decision using :func:`classify_cuda_failure`.
    """
    gc.collect()
    try:
        import torch

        empty_cache = getattr(getattr(torch, "cuda", None), "empty_cache", None)
        if callable(empty_cache):
            empty_cache()
    except Exception as exc:  # noqa: BLE001 - cleanup is best effort only
        logger.debug("CUDA cache cleanup failed before CPU fallback: %s", exc)


class CpuFallbackError(RuntimeError):
    """Terminal error for a disabled or unsuccessful CPU fallback."""

    def __init__(
        self,
        message: str,
        *,
        reason: FailureCode | None = None,
        detail: str | None = None,
    ) -> None:
        self.reason = reason
        self.detail = detail[:_MAX_DETAIL_LENGTH] if detail is not None else None
        super().__init__(message)


class _TerminalEmbedder(Embedder):
    """Protocol adapter that preserves a setup failure until a source run.

    The sync process constructs one model before iterating over sources.  If
    the GPU failed and the one permitted CPU construction also failed, this
    adapter lets each affected source create its normal failed SyncLog instead
    of losing the error before ``_sync_one`` starts.
    """

    dimension = 1024

    def __init__(self, error: CpuFallbackError) -> None:
        self._error = error

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        raise self._error


class SyncEmbedderHandle(Embedder):
    """Own the sync runner's current embedder and one-way fallback state."""

    def __init__(
        self,
        embedder: Embedder,
        *,
        runtime_device: str,
        cpu_factory: Callable[[], Embedder],
        cpu_fallback_enabled: bool,
        initial_fallback: tuple[FailureCode, str] | None = None,
    ) -> None:
        self._embedder: Embedder = embedder
        self._runtime_device = runtime_device
        self._cpu_factory = cpu_factory
        self._cpu_fallback_enabled = cpu_fallback_enabled
        self._fallback_attempted = initial_fallback is not None
        self._fallback_reason: FailureCode | None = (
            initial_fallback[0] if initial_fallback else None
        )
        self._fallback_detail: str | None = (
            initial_fallback[1][:_MAX_DETAIL_LENGTH] if initial_fallback else None
        )
        self._embedding_attempts = 0
        self._cpu_batches = 0
        self._cpu_docs = 0

    @property
    def embedder(self) -> Embedder:
        """Return the current model for callers that need the raw protocol."""
        return self._embedder

    @property
    def dimension(self) -> int:
        return self._embedder.dimension

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        """Delegate one real ingestion encode and remember that it happened."""
        self._embedding_attempts += 1
        return self._embedder.embed(texts)

    @property
    def runtime_device(self) -> str:
        return self._runtime_device

    @property
    def execution_device(self) -> str:
        """Return the current execution class (``gpu`` or ``cpu``)."""
        return DEVICE_CPU if self._runtime_device == "cpu" else DEVICE_GPU

    @property
    def telemetry_execution_device(self) -> str:
        """Return W2's three-valued final device fact."""
        if self._fallback_attempted:
            return DEVICE_GPU_TO_CPU
        return self.execution_device

    @property
    def fallback_reason(self) -> FailureCode | None:
        return self._fallback_reason

    @property
    def fallback_detail(self) -> str | None:
        return self._fallback_detail

    @property
    def cpu_batches(self) -> int:
        return self._cpu_batches

    @property
    def cpu_docs(self) -> int:
        return self._cpu_docs

    @property
    def embedding_attempts(self) -> int:
        return self._embedding_attempts

    def record_cpu_batch(self, doc_count: int) -> None:
        """Count a successfully CPU-encoded batch after automatic fallback."""
        if self._fallback_reason is None or self._runtime_device != "cpu":
            return
        if doc_count < 0:
            raise ValueError("doc_count must be non-negative")
        self._cpu_batches += 1
        self._cpu_docs += doc_count

    def activity_snapshot(self) -> tuple[int, int, int, int]:
        """Return counters used to isolate one source's telemetry."""
        return (
            self._embedding_attempts,
            self._cpu_batches,
            self._cpu_docs,
            int(self._fallback_attempted),
        )

    def has_activity_since(self, snapshot: tuple[int, int, int, int]) -> bool:
        current = self.activity_snapshot()
        return any(now > before for now, before in zip(current, snapshot, strict=True))

    def cpu_counters_since(self, snapshot: tuple[int, int, int, int]) -> dict[str, int]:
        return {
            "cpu_batches": self._cpu_batches - snapshot[1],
            "cpu_docs": self._cpu_docs - snapshot[2],
        }

    def fallback_to_cpu(self, reason: FailureCode, detail: str) -> bool:
        """Perform at most one CUDA→CPU transition.

        A false return is terminal for the caller: it means fallback is
        disabled or already attempted.  It is never permission to retry on
        CUDA or to start a CPU→GPU loop.
        """
        if reason not in ELIGIBLE_FAILURE_CODES:
            raise ValueError(f"unsupported CPU fallback reason: {reason!r}")
        if (
            self._fallback_attempted
            or not self._cpu_fallback_enabled
            or not _is_cuda_device(self._runtime_device)
        ):
            return False

        self._fallback_attempted = True
        self._fallback_reason = reason
        self._fallback_detail = detail[:_MAX_DETAIL_LENGTH]
        old_embedder = self._embedder
        self._embedder = None  # type: ignore[assignment]
        del old_embedder
        _release_cuda_resources()
        try:
            cpu_embedder = self._cpu_factory()
        except Exception as exc:
            self._fallback_detail = (
                f"{self._fallback_detail}; CPU fallback failed: {_exception_detail(exc)}"
            )[:_MAX_DETAIL_LENGTH]
            raise CpuFallbackError(
                f"CPU fallback failed after {reason}: {_exception_detail(exc)}",
                reason=reason,
                detail=self._fallback_detail,
            ) from exc
        self._embedder = cpu_embedder
        self._runtime_device = "cpu"
        return True


def _make_embedder_factory(settings, embedder_cls) -> Callable[[str], Embedder]:
    batch_size = settings.embedder_batch_size
    max_length = settings.embedder_max_length

    def make(device: str) -> Embedder:
        return embedder_cls(
            device=device,
            batch_size=batch_size,
            max_length=max_length,
        )

    return make


def _cpu_after_gpu_failure(
    make_embedder: Callable[[str], Embedder],
    *,
    reason: FailureCode,
    detail: str,
    fallback_enabled: bool,
) -> SyncEmbedderHandle:
    _release_cuda_resources()
    bounded_detail = detail[:_MAX_DETAIL_LENGTH]
    try:
        cpu_embedder = make_embedder("cpu")
    except Exception as exc:
        bounded_detail = f"{bounded_detail}; CPU fallback failed: {_exception_detail(exc)}"[
            :_MAX_DETAIL_LENGTH
        ]
        raise CpuFallbackError(
            f"CPU fallback failed after {reason}: {_exception_detail(exc)}",
            reason=reason,
            detail=bounded_detail,
        ) from exc
    return SyncEmbedderHandle(
        cpu_embedder,
        runtime_device="cpu",
        cpu_factory=lambda: make_embedder("cpu"),
        cpu_fallback_enabled=fallback_enabled,
        initial_fallback=(reason, bounded_detail),
    )


def _build_sync_embedder(settings, embedder_cls) -> SyncEmbedderHandle:
    selected_device = detect_device(settings.embedder_device)
    make_embedder = _make_embedder_factory(settings, embedder_cls)
    fallback_enabled = _cpu_fallback_enabled()

    if not _is_cuda_device(selected_device):
        return SyncEmbedderHandle(
            make_embedder(selected_device),
            runtime_device=selected_device,
            cpu_factory=lambda: make_embedder("cpu"),
            cpu_fallback_enabled=False,
        )

    try:
        gpu_embedder = make_embedder(selected_device)
    except Exception as exc:
        reason = classify_cuda_failure(exc)
        if reason is None or not fallback_enabled:
            raise
        return _cpu_after_gpu_failure(
            make_embedder,
            reason=reason,
            detail=_exception_detail(exc),
            fallback_enabled=fallback_enabled,
        )

    handle = SyncEmbedderHandle(
        gpu_embedder,
        runtime_device=selected_device,
        cpu_factory=lambda: make_embedder("cpu"),
        cpu_fallback_enabled=fallback_enabled,
    )
    try:
        # FlagEmbedding may lazily initialize CUDA during its first encode;
        # this probe moves that failure to a classified setup point.
        gpu_embedder.embed([_GPU_PROBE_TEXT])
    except Exception as exc:
        reason = classify_cuda_failure(exc)
        if reason is None:
            raise
        # Do not keep a second reference to the failed GPU model while the
        # handle releases it and constructs the CPU model in this process.
        del gpu_embedder
        if not handle.fallback_to_cpu(reason, _exception_detail(exc)):
            if not fallback_enabled:
                raise
            raise CpuFallbackError(
                f"CPU fallback disabled or already attempted after {reason}: "
                f"{_exception_detail(exc)}",
                reason=reason,
                detail=_exception_detail(exc),
            ) from exc
    return handle


def build_sync_embedder(settings) -> SyncEmbedderHandle:
    """Build the sync runner's GPU-first embedder handle."""
    return _build_sync_embedder(settings, BGEEmbedder)


def _terminal_sync_embedder(error: CpuFallbackError) -> SyncEmbedderHandle:
    """Defer a terminal setup error until the source run has started."""
    if error.reason is None:
        raise ValueError("terminal CPU fallback error must have a CUDA reason")
    return SyncEmbedderHandle(
        _TerminalEmbedder(error),
        runtime_device="cpu",
        cpu_factory=lambda: _TerminalEmbedder(error),
        cpu_fallback_enabled=False,
        initial_fallback=(error.reason, error.detail or str(error)),
    )
