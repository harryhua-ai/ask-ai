"""GPU-first sync embedder fallback contract tests."""

from types import SimpleNamespace

import numpy as np
import pytest

from backend.embedder import fallback


def _settings(device: str) -> SimpleNamespace:
    return SimpleNamespace(
        embedder_device=device,
        embedder_batch_size=4,
        embedder_max_length=128,
    )


class _FakeEmbedder:
    dimension = 1024

    def __init__(self, device: str, *, fail_on_embed: BaseException | None = None, calls=None):
        self.device = device
        self.fail_on_embed = fail_on_embed
        self.calls = calls if calls is not None else []

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        self.calls.append((self.device, list(texts)))
        if self.fail_on_embed is not None:
            raise self.fail_on_embed
        return [np.zeros(1024) for _ in texts]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (RuntimeError("CUDA error: initialization error"), "cuda_init_failure"),
        (RuntimeError("cuInit failed with error code 100"), "cuda_init_failure"),
        (RuntimeError("NVML error 999 while initializing CUDA"), "cuda_init_failure"),
        (RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB"), "cuda_oom"),
        (RuntimeError("CUDA error: out of memory"), "cuda_oom"),
        (
            RuntimeError("CUDA error: CUBLAS_STATUS_EXECUTION_FAILED"),
            "cuda_runtime_error",
        ),
        (ValueError("bad document"), None),
        (RuntimeError("vector database unavailable"), None),
        (RuntimeError("application bug"), None),
    ],
)
def test_classify_cuda_failure_is_narrow(exc, expected):
    assert fallback.classify_cuda_failure(exc) == expected


@pytest.mark.unit
def test_healthy_gpu_factory_is_gpu_first_and_runs_probe(monkeypatch):
    calls: list[str] = []

    class FakeBGE(_FakeEmbedder):
        def __init__(self, *, device: str, **kwargs):
            calls.append(device)
            super().__init__(device, calls=[])

    monkeypatch.setattr(fallback, "BGEEmbedder", FakeBGE)
    monkeypatch.setenv("EMBEDDER_CPU_FALLBACK", "on")

    handle = fallback.build_sync_embedder(_settings("cuda"))

    assert calls == ["cuda"]
    assert handle.execution_device == "gpu"
    assert handle.telemetry_execution_device == "gpu"
    assert handle.fallback_reason is None
    assert len(handle.embed(["document"])) == 1


@pytest.mark.unit
def test_explicit_cpu_factory_never_constructs_gpu_or_fallback(monkeypatch):
    calls: list[str] = []

    class FakeBGE(_FakeEmbedder):
        def __init__(self, *, device: str, **kwargs):
            calls.append(device)
            super().__init__(device, calls=[])

    monkeypatch.setattr(fallback, "BGEEmbedder", FakeBGE)

    handle = fallback.build_sync_embedder(_settings("cpu"))

    assert calls == ["cpu"]
    assert handle.execution_device == "cpu"
    assert handle.telemetry_execution_device == "cpu"
    assert handle.fallback_reason is None


@pytest.mark.unit
def test_cuda_initialization_failure_builds_cpu_once(monkeypatch):
    calls: list[str] = []

    class FakeBGE(_FakeEmbedder):
        def __init__(self, *, device: str, **kwargs):
            calls.append(device)
            if device == "cuda":
                raise RuntimeError("CUDA error: initialization error")
            super().__init__(device, calls=[])

    monkeypatch.setattr(fallback, "BGEEmbedder", FakeBGE)

    handle = fallback.build_sync_embedder(_settings("cuda"))

    assert calls == ["cuda", "cpu"]
    assert handle.execution_device == "cpu"
    assert handle.telemetry_execution_device == "gpu_to_cpu"
    assert handle.fallback_reason == "cuda_init_failure"


@pytest.mark.unit
def test_cuda_oom_probe_failure_switches_to_cpu(monkeypatch):
    calls: list[str] = []

    class FakeBGE(_FakeEmbedder):
        def __init__(self, *, device: str, **kwargs):
            calls.append(device)
            error = RuntimeError("CUDA out of memory") if device == "cuda" else None
            super().__init__(device, fail_on_embed=error, calls=[])

    monkeypatch.setattr(fallback, "BGEEmbedder", FakeBGE)

    handle = fallback.build_sync_embedder(_settings("cuda"))

    assert calls == ["cuda", "cpu"]
    assert handle.execution_device == "cpu"
    assert handle.telemetry_execution_device == "gpu_to_cpu"
    assert handle.fallback_reason == "cuda_oom"
    assert len(handle.embed(["document"])) == 1


@pytest.mark.unit
def test_gpu_constructor_cpu_failure_keeps_failure_reason_on_terminal_error(monkeypatch):
    class FakeBGE(_FakeEmbedder):
        def __init__(self, *, device: str, **kwargs):
            if device == "cuda":
                raise RuntimeError("CUDA error: initialization error")
            raise RuntimeError("CPU model unavailable")

    monkeypatch.setattr(fallback, "BGEEmbedder", FakeBGE)

    with pytest.raises(fallback.CpuFallbackError) as caught:
        fallback.build_sync_embedder(_settings("cuda"))

    assert caught.value.reason == "cuda_init_failure"
    assert "CPU model unavailable" in caught.value.detail


@pytest.mark.unit
def test_unrelated_gpu_constructor_error_is_not_retried_on_cpu(monkeypatch):
    calls: list[str] = []

    class FakeBGE(_FakeEmbedder):
        def __init__(self, *, device: str, **kwargs):
            calls.append(device)
            raise RuntimeError("model download failed")

    monkeypatch.setattr(fallback, "BGEEmbedder", FakeBGE)

    with pytest.raises(RuntimeError, match="model download failed"):
        fallback.build_sync_embedder(_settings("cuda"))

    assert calls == ["cuda"]


@pytest.mark.unit
def test_fallback_is_single_direction_and_bounded():
    gpu = _FakeEmbedder("cuda")
    cpu = _FakeEmbedder("cpu")
    cpu_creations: list[int] = []

    def make_cpu():
        cpu_creations.append(1)
        return cpu

    handle = fallback.SyncEmbedderHandle(
        gpu,
        runtime_device="cuda",
        cpu_factory=make_cpu,
        cpu_fallback_enabled=True,
    )

    assert handle.fallback_to_cpu("cuda_oom", "first failure") is True
    assert handle.fallback_to_cpu("cuda_init_failure", "second failure") is False
    assert cpu_creations == [1]
    assert handle.execution_device == "cpu"
    assert handle.telemetry_execution_device == "gpu_to_cpu"
    assert handle.fallback_reason == "cuda_oom"


@pytest.mark.unit
def test_cpu_fallback_constructor_failure_is_terminal():
    handle = fallback.SyncEmbedderHandle(
        _FakeEmbedder("cuda"),
        runtime_device="cuda",
        cpu_factory=lambda: (_ for _ in ()).throw(RuntimeError("CPU model failed")),
        cpu_fallback_enabled=True,
    )

    with pytest.raises(fallback.CpuFallbackError, match="CPU model failed"):
        handle.fallback_to_cpu("cuda_init_failure", "CUDA failed")

    assert handle.fallback_to_cpu("cuda_oom", "must not retry") is False


@pytest.mark.unit
def test_fallback_can_be_disabled_without_constructing_cpu(monkeypatch):
    calls: list[str] = []

    class FakeBGE(_FakeEmbedder):
        def __init__(self, *, device: str, **kwargs):
            calls.append(device)
            raise RuntimeError("CUDA error: initialization error")

    monkeypatch.setattr(fallback, "BGEEmbedder", FakeBGE)
    monkeypatch.setenv("EMBEDDER_CPU_FALLBACK", "off")

    with pytest.raises(RuntimeError, match="CUDA error: initialization error"):
        fallback.build_sync_embedder(_settings("cuda"))

    assert calls == ["cuda"]
