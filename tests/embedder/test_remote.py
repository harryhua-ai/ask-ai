"""共享嵌入运行时 sync 侧客户端验收(遥测镜像/有界错误语义)。"""

import json
import urllib.error

import numpy as np
import pytest

from backend.embedder.remote import (
    RemoteSyncEmbedder,
    _RemoteEmbedderClient,
    internal_token,
)
from backend.runtime.internal_auth import internal_api_token


class _Settings:
    jwt_secret = "shared-secret"
    internal_api_base_url = "http://backend:8000"


def test_internal_token_matches_backend_derivation():
    assert internal_token("shared-secret") == internal_api_token("shared-secret")


class _FakeResponse:
    def __init__(self, body: dict, status: int = 200):
        self._body = json.dumps(body).encode()
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_remote_embedder_mirrors_server_fallback_telemetry(monkeypatch):
    captured: dict = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["token"] = req.headers.get("X-internal-token")
        captured["body"] = json.loads(req.data.decode())
        return _FakeResponse(
            {
                "vectors": [[0.0, 0.0, 0.0, 0.0], [0.1, 0.0, 0.0, 0.0]],
                "dimension": 4,
                "execution_device": "cpu",
                "fallback_reason": "cuda_oom",
                "fallback_detail": "CUDA out of memory",
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = _RemoteEmbedderClient("http://backend:8000", internal_token("shared-secret"))
    handle = RemoteSyncEmbedder(client)

    vectors = handle.embed(["a", "b"])

    assert len(vectors) == 2 and isinstance(vectors[0], np.ndarray)
    assert captured["url"] == "http://backend:8000/api/internal/embeddings"
    assert captured["token"] == internal_token("shared-secret")
    assert captured["body"] == {"texts": ["a", "b"]}
    # 遥测镜像:服务端单向回退如实反映(W2 三值 + cpu 计数)
    assert handle.telemetry_execution_device == "gpu_to_cpu"
    assert handle.fallback_reason == "cuda_oom"
    assert handle.runtime_device == "cpu"
    assert handle.cpu_batches == 1 and handle.cpu_docs == 2
    assert handle.has_activity_since((0, 0, 0, 0))


def test_remote_embedder_gpu_path_keeps_gpu_telemetry(monkeypatch):
    def fake_urlopen(req, timeout=None):
        return _FakeResponse(
            {
                "vectors": [[1.0, 0.0, 0.0, 0.0]],
                "dimension": 4,
                "execution_device": "gpu",
                "fallback_reason": None,
                "fallback_detail": None,
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    handle = RemoteSyncEmbedder(_RemoteEmbedderClient("http://b", internal_token("s")))
    handle.embed(["x"])
    assert handle.telemetry_execution_device == "gpu"
    assert handle.fallback_reason is None
    assert handle.cpu_batches == 0


def test_remote_embedder_native_cpu_is_not_reported_as_fallback(monkeypatch):
    """原生 CPU 部署(CPU 策略,无回退事实)不得被遥测误报为 gpu_to_cpu。"""

    def fake_urlopen(req, timeout=None):
        return _FakeResponse(
            {
                "vectors": [[0.5, 0.0, 0.0, 0.0]],
                "dimension": 4,
                "execution_device": "cpu",
                "fallback_reason": None,
                "fallback_detail": None,
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    handle = RemoteSyncEmbedder(_RemoteEmbedderClient("http://b", internal_token("s")))
    handle.embed(["x"])
    # 如实按 CPU 常驻记录;不臆造 cuda_oom、不计回退批次
    assert handle.telemetry_execution_device == "cpu"
    assert handle.fallback_reason is None
    assert handle.cpu_batches == 0
    assert handle.runtime_device == "cpu"


def test_remote_embedder_http_error_raises_runtime_error(monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 503, "embedding unavailable", hdrs=None, fp=None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    handle = RemoteSyncEmbedder(_RemoteEmbedderClient("http://b", internal_token("s")))
    with pytest.raises(RuntimeError, match="HTTP 503"):
        handle.embed(["x"])


def test_remote_embedder_vector_count_mismatch_is_error(monkeypatch):
    def fake_urlopen(req, timeout=None):
        return _FakeResponse({"vectors": [[0.0] * 4], "dimension": 4, "execution_device": "gpu"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    handle = RemoteSyncEmbedder(_RemoteEmbedderClient("http://b", internal_token("s")))
    with pytest.raises(RuntimeError, match="expected 2"):
        handle.embed(["x", "y"])
