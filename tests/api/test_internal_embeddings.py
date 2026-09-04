"""内部嵌入端点验收(HMAC 认证/有界性/共享运行时/回退遥测透传)。"""

from types import SimpleNamespace

import numpy as np
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.main import app
from backend.runtime.internal_auth import internal_api_token
from backend.runtime.manager import ModelRuntimeManager
from backend.runtime.hardware import GpuMemorySnapshot

pytestmark = pytest.mark.asyncio(loop_scope="session")


class _FakeEmbedder:
    dimension = 4

    def __init__(self, device: str = "cpu", **kwargs):
        self.device = device
        self.fail_plan: list[BaseException | None] = []

    def embed(self, texts):
        if self.fail_plan:
            exc = self.fail_plan.pop(0)
            if exc is not None:
                raise exc
        return [np.zeros(4, dtype=np.float32) for _ in texts]


class _FakeReranker:
    def rerank(self, query, documents):
        return [0.5 for _ in documents]


@pytest_asyncio.fixture(loop_scope="session")
async def runtime_setup():
    settings = SimpleNamespace(
        jwt_secret="internal-test-secret",
        embedder_device="cuda",
        embedder_batch_size=16,
        embedder_max_length=8192,
        internal_api_base_url="http://backend:8000",
    )
    manager = ModelRuntimeManager(
        settings,
        embedder_factory=lambda device="cpu", **kwargs: _FakeEmbedder(device=device),
        reranker_factory=lambda **kwargs: _FakeReranker(),
        # free 9000 → auto 预算 9000 ≥ 双驻留下限 → sync 以 GPU 计划装配,
        # 服务端单向回退路径才能被本测试触达(REV1 B3/B4 计划语义)。
        gpu_memory_reader=lambda uuid: GpuMemorySnapshot(
            used_mb=6564, free_mb=9000, total_mb=15564
        ),
    )
    manager._build({})
    # 保存并还原共享 app.state,避免泄漏到同 loop 的其他测试文件
    saved = {
        k: app.state.__dict__[k] for k in ("settings", "model_runtime") if k in app.state.__dict__
    }
    app.state.settings = settings
    app.state.model_runtime = manager
    token = internal_api_token(settings.jwt_secret)
    yield manager, token
    for k, v in saved.items():
        setattr(app.state, k, v)
    for k in ("settings", "model_runtime"):
        if k not in saved:
            try:
                delattr(app.state, k)
            except AttributeError:
                pass


def _headers(token):
    return {"X-Internal-Token": token}


@pytest.mark.asyncio(loop_scope="session")
async def test_internal_embeddings_requires_valid_token(runtime_setup):
    manager, token = runtime_setup
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.post("/api/internal/embeddings", json={"texts": ["a"]})
        wrong = await client.post(
            "/api/internal/embeddings",
            json={"texts": ["a"]},
            headers=_headers("wrong-token"),
        )
        ok = await client.post(
            "/api/internal/embeddings",
            json={"texts": ["a", "b"]},
            headers=_headers(token),
        )
    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert ok.status_code == 200
    body = ok.json()
    assert len(body["vectors"]) == 2
    assert body["dimension"] == 4
    assert body["execution_device"] in {"gpu", "cpu"}
    assert body["fallback_reason"] is None


@pytest.mark.asyncio(loop_scope="session")
async def test_internal_embeddings_bounds(runtime_setup):
    manager, token = runtime_setup
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        too_many = await client.post(
            "/api/internal/embeddings",
            json={"texts": ["x"] * 17},
            headers=_headers(token),
        )
        too_long = await client.post(
            "/api/internal/embeddings",
            json={"texts": ["x" * 9000]},
            headers=_headers(token),
        )
    assert too_many.status_code == 422
    assert too_long.status_code == 413


@pytest.mark.asyncio(loop_scope="session")
async def test_internal_embeddings_server_side_fallback_telemetry(runtime_setup):
    manager, token = runtime_setup
    gpu_instance = manager._embedder_for("sync_embedding")
    gpu_instance.fail_plan = [_torch_oom()]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/internal/embeddings",
            json={"texts": ["doc"]},
            headers=_headers(token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["execution_device"] == "cpu"
        assert body["fallback_reason"] == "cuda_oom"
        assert manager.states["sync_embedding"].status == "fallback_gpu_to_cpu"
        # 后续批次继续 CPU(单向)
        resp2 = await client.post(
            "/api/internal/embeddings", json={"texts": ["doc2"]}, headers=_headers(token)
        )
        assert resp2.json()["execution_device"] == "cpu"


def _torch_oom() -> Exception:
    import torch

    return torch.OutOfMemoryError("CUDA out of memory")
