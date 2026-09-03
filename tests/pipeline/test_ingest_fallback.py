"""Ingestion batch GPU→CPU fallback tests."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from backend.connectors.base import RawDocument
from backend.embedder.fallback import CpuFallbackError, SyncEmbedderHandle
from backend.pipeline.ingest import IngestionPipeline


def _doc(source_id: str = "src/doc") -> RawDocument:
    return RawDocument(
        source_id=source_id,
        source_type="test",
        product="test",
        title=source_id,
        content="document content",
        url="https://example.test",
        metadata={"path": "README.md"},
        content_hash=f"hash-{source_id}",
    )


def _chunk():
    return SimpleNamespace(
        text="chunk",
        chunk_index=0,
        channel_visibility=("public",),
        doc_section=None,
        chunk_type="text",
        symbol_name=None,
        symbol_signature=None,
        symbol_node_type=None,
        symbol_tokens=None,
    )


def _client():
    client = MagicMock()
    client.collections.exists.return_value = True
    collection = MagicMock()
    collection.data.insert_many.return_value = SimpleNamespace(errors={})
    client.collections.get.return_value = collection
    return client


class _Embedder:
    dimension = 1024

    def __init__(self, device: str, error: BaseException | None = None):
        self.device = device
        self.error = error
        self.calls: list[int] = []

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        self.calls.append(len(texts))
        if self.error is not None:
            raise self.error
        return [np.zeros(1024) for _ in texts]


@pytest.mark.unit
def test_cuda_oom_batch_falls_back_once_and_keeps_accounting():
    gpu = _Embedder("cuda", RuntimeError("CUDA out of memory"))
    cpu = _Embedder("cpu")
    cpu_creations: list[int] = []

    def make_cpu():
        cpu_creations.append(1)
        return cpu

    handle = SyncEmbedderHandle(
        gpu,
        runtime_device="cuda",
        cpu_factory=make_cpu,
        cpu_fallback_enabled=True,
    )
    pipeline = IngestionPipeline(handle, _client())
    docs = [_doc(f"src/{i}") for i in range(65)]

    with patch("backend.pipeline.ingest.chunk_document_semantic", return_value=[_chunk()]):
        results = pipeline.ingest_all(docs)

    assert len(results) == 65
    assert all(value == 1 for value in results.values())
    assert gpu.calls == [64]
    assert cpu.calls == [64, 1]
    assert cpu_creations == [1]
    assert handle.cpu_batches == 2
    assert handle.cpu_docs == 65
    assert handle.telemetry_execution_device == "gpu_to_cpu"
    assert handle.fallback_reason == "cuda_oom"


@pytest.mark.unit
def test_cuda_init_failure_cpu_encode_failure_is_terminal_without_doc_retry():
    gpu = _Embedder("cuda", RuntimeError("CUDA error: initialization error"))
    cpu = _Embedder("cpu", RuntimeError("CPU encode failed"))
    handle = SyncEmbedderHandle(
        gpu,
        runtime_device="cuda",
        cpu_factory=lambda: cpu,
        cpu_fallback_enabled=True,
    )
    pipeline = IngestionPipeline(handle, _client())
    pipeline.ingest_document = MagicMock()  # type: ignore[method-assign]

    with (
        patch("backend.pipeline.ingest.chunk_document_semantic", return_value=[_chunk()]),
        pytest.raises(CpuFallbackError, match="CPU fallback failed.*CPU encode failed"),
    ):
        pipeline.ingest_all([_doc("src/one")])

    pipeline.ingest_document.assert_not_called()
    assert cpu.calls == [1]
    assert handle.cpu_batches == 0


@pytest.mark.unit
def test_terminal_cpu_fallback_error_is_not_retried_per_document():
    error = RuntimeError("CPU model unavailable")
    handle = SyncEmbedderHandle(
        _Embedder("cuda"),
        runtime_device="cuda",
        cpu_factory=lambda: (_ for _ in ()).throw(error),
        cpu_fallback_enabled=True,
    )
    pipeline = IngestionPipeline(handle, _client())
    pipeline.ingest_document = MagicMock()  # type: ignore[method-assign]

    with (
        patch("backend.pipeline.ingest.chunk_document_semantic", return_value=[_chunk()]),
        patch.object(handle.embedder, "embed", side_effect=RuntimeError("CUDA error: initialization error")),
        pytest.raises(CpuFallbackError, match="CPU fallback failed"),
    ):
        pipeline.ingest_all([_doc("src/one")])

    pipeline.ingest_document.assert_not_called()


@pytest.mark.unit
def test_unrelated_batch_error_never_constructs_cpu():
    gpu = _Embedder("cuda", ValueError("bad document"))
    cpu_creations: list[int] = []
    handle = SyncEmbedderHandle(
        gpu,
        runtime_device="cuda",
        cpu_factory=lambda: cpu_creations.append(1) or _Embedder("cpu"),
        cpu_fallback_enabled=True,
    )
    pipeline = IngestionPipeline(handle, _client())

    with (
        patch("backend.pipeline.ingest.chunk_document_semantic", return_value=[_chunk()]),
        pytest.raises(RuntimeError, match="src/one"),
    ):
        pipeline.ingest_all([_doc("src/one")])

    assert cpu_creations == []
    assert handle.fallback_reason is None
