"""Sync runner device telemetry and short-circuit truth tests."""

from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from backend.connectors.registry import SourceConfig
from backend.embedder.fallback import CpuFallbackError, SyncEmbedderHandle
from scripts import sync as sync_mod


class _Embedder:
    dimension = 1024

    def __init__(self, device: str):
        self.device = device

    def embed(self, texts):
        return [object() for _ in texts]


def _cfg(source_id: str = "telemetry-src") -> SourceConfig:
    return SourceConfig(
        id=source_id,
        type="test-device",
        product="test",
        enabled=True,
        config={},
        sync_interval="1h",
    )


def _report():
    return SimpleNamespace(
        is_healthy=True,
        expected_chunks=1,
        actual_chunks=1,
        missing_source_ids=[],
        refill_source_ids=[],
        stale_chunk_count=0,
        orphan_count=0,
        orphan_chunks=[],
    )


class _Connector:
    run_stats = None

    def __init__(self, docs):
        self.docs = docs

    def fetch_changes(self, since):
        return list(self.docs)

    def fetch_all(self):
        return []

    def fetch_deleted(self, since):
        return []


class _Session:
    def add(self, item):
        self.item = item

    async def commit(self):
        return None


@asynccontextmanager
async def _session_factory():
    yield _Session()


async def _noop(*args, **kwargs):
    return None


@pytest.mark.asyncio
async def test_run_telemetry_calls_frozen_w2_record_device_contract(monkeypatch):
    calls = []

    async def record_device(factory, run_id, *, execution_device, fallback_reason, fallback_detail):
        calls.append(
            (factory, run_id, execution_device, fallback_reason, fallback_detail)
        )

    monkeypatch.setattr(sync_mod, "record_device", record_device, raising=False)
    telemetry = sync_mod._RunTelemetry()
    telemetry.run_id = 42

    await telemetry.device(
        _session_factory,
        execution_device="gpu_to_cpu",
        fallback_reason="cuda_oom",
        fallback_detail="CUDA out of memory",
    )

    assert calls == [
        (_session_factory, 42, "gpu_to_cpu", "cuda_oom", "CUDA out of memory")
    ]


@pytest.mark.asyncio
async def test_sync_one_records_gpu_to_cpu_reason_after_real_embedding_activity(monkeypatch):
    gpu = _Embedder("cuda")
    cpu = _Embedder("cpu")
    handle = SyncEmbedderHandle(
        gpu,
        runtime_device="cuda",
        cpu_factory=lambda: cpu,
        cpu_fallback_enabled=True,
    )
    assert handle.fallback_to_cpu("cuda_init_failure", "cuInit=100") is True

    class Pipeline:
        _embedder = handle

        def ingest_all(self, docs, *, progress=None):
            handle.embed(["chunk"])
            return {"doc": 1}

    calls_to_record = []

    async def record_device(factory, run_id, *, execution_device, fallback_reason, fallback_detail):
        calls_to_record.append((execution_device, fallback_reason, fallback_detail))

    async def start(self, *args, **kwargs):
        self.run_id = 99

    monkeypatch.setattr(sync_mod, "record_device", record_device, raising=False)
    monkeypatch.setattr(sync_mod._RunTelemetry, "start", start)
    monkeypatch.setattr(sync_mod._RunTelemetry, "progress", _noop)
    monkeypatch.setattr(sync_mod._RunTelemetry, "counters", _noop)
    monkeypatch.setattr(sync_mod._RunTelemetry, "consistency", _noop)
    monkeypatch.setattr(sync_mod._RunTelemetry, "finish", _noop)
    monkeypatch.setattr(sync_mod.ConnectorRegistry, "create", lambda cfg: _Connector(["doc"]))
    monkeypatch.setattr(sync_mod, "_last_success_at", _noop)
    monkeypatch.setattr(sync_mod, "verify_source_vectors", lambda *a, **k: _report())

    await sync_mod._sync_one(_cfg(), Pipeline(), _session_factory, triggered_by="manual")

    assert calls_to_record == [("gpu_to_cpu", "cuda_init_failure", "cuInit=100")]


@pytest.mark.asyncio
async def test_short_circuit_does_not_claim_healthy_gpu_without_encode(monkeypatch):
    calls = []
    handle = SyncEmbedderHandle(
        _Embedder("cuda"),
        runtime_device="cuda",
        cpu_factory=lambda: _Embedder("cpu"),
        cpu_fallback_enabled=True,
    )

    class Pipeline:
        _embedder = handle

        def ingest_all(self, docs, *, progress=None):
            raise AssertionError("short-circuit must not ingest")

    async def record_device(factory, run_id, *, execution_device, fallback_reason, fallback_detail):
        calls.append((execution_device, fallback_reason, fallback_detail))

    async def start(self, *args, **kwargs):
        self.run_id = 100

    monkeypatch.setattr(sync_mod, "record_device", record_device, raising=False)
    monkeypatch.setattr(sync_mod._RunTelemetry, "start", start)
    monkeypatch.setattr(sync_mod._RunTelemetry, "progress", _noop)
    monkeypatch.setattr(sync_mod._RunTelemetry, "counters", _noop)
    monkeypatch.setattr(sync_mod._RunTelemetry, "consistency", _noop)
    monkeypatch.setattr(sync_mod._RunTelemetry, "finish", _noop)
    monkeypatch.setattr(sync_mod.ConnectorRegistry, "create", lambda cfg: _Connector([]))
    monkeypatch.setattr(sync_mod, "_last_success_at", _noop)
    monkeypatch.setattr(sync_mod, "_count_documents", _noop)
    monkeypatch.setattr(sync_mod, "verify_source_vectors", lambda *a, **k: _report())

    async def existing_count(*args, **kwargs):
        return 1

    monkeypatch.setattr(sync_mod, "_count_documents", existing_count)

    await sync_mod._sync_one(_cfg("short-circuit"), Pipeline(), _session_factory)

    assert calls == []


@pytest.mark.asyncio
async def test_terminal_cpu_fallback_keeps_failed_run_accounting(monkeypatch):
    terminal = CpuFallbackError(
        "CPU fallback failed after cuda_init_failure: CPU model unavailable",
        reason="cuda_init_failure",
        detail="CUDA initialization error; CPU model unavailable",
    )
    handle = SyncEmbedderHandle(
        _Embedder("cpu"),
        runtime_device="cpu",
        cpu_factory=lambda: _Embedder("cpu"),
        cpu_fallback_enabled=False,
        initial_fallback=("cuda_init_failure", terminal.detail),
    )

    class Pipeline:
        _embedder = handle

        def ingest_all(self, docs, *, progress=None):
            handle.embed(["chunk"])
            raise terminal

    calls_to_record = []

    async def record_device(factory, run_id, *, execution_device, fallback_reason, fallback_detail):
        calls_to_record.append((execution_device, fallback_reason, fallback_detail))

    async def start(self, *args, **kwargs):
        self.run_id = 101

    log_session = _Session()

    @asynccontextmanager
    async def session_factory():
        yield log_session

    monkeypatch.setattr(sync_mod, "record_device", record_device, raising=False)
    monkeypatch.setattr(sync_mod._RunTelemetry, "start", start)
    monkeypatch.setattr(sync_mod._RunTelemetry, "progress", _noop)
    monkeypatch.setattr(sync_mod._RunTelemetry, "counters", _noop)
    monkeypatch.setattr(sync_mod._RunTelemetry, "consistency", _noop)
    monkeypatch.setattr(sync_mod._RunTelemetry, "finish", _noop)
    monkeypatch.setattr(sync_mod.ConnectorRegistry, "create", lambda cfg: _Connector(["doc"]))
    monkeypatch.setattr(sync_mod, "_last_success_at", _noop)

    await sync_mod._sync_one(_cfg("terminal"), Pipeline(), session_factory)

    assert log_session.item.status == "failed"
    assert "CPU fallback failed" in log_session.item.error_detail
    assert calls_to_record == [
        (
            "gpu_to_cpu",
            "cuda_init_failure",
            "CUDA initialization error; CPU model unavailable",
        )
    ]
