"""远程嵌入客户端切批契约(Issue #72 矫正;RED→GREEN 见报告)。

服务端契约:POST /api/internal/embeddings 单请求 texts 条数 ≤
embedder_batch_size(生产 compose = 16),越界显式 422 —— 服务端保持防御。
矫正缝隙:_RemoteEmbedderClient.embed 必须按与 sync 运行时同一 Settings
权威(settings.embedder_batch_size)切片,顺序请求、按输入序拼接:
78 → 16 + 16 + 16 + 16 + 14。服务端错误如实透传并附切片上下文;
任一片失败 = 整体失败(无部分结果、无客户端重试);遥测一次公共调用
仍记一次 attempt。
"""

import io
import json
import urllib.error

import numpy as np
import pytest

from backend.embedder.remote import (
    RemoteSyncEmbedder,
    _RemoteEmbedderClient,
    build_remote_sync_embedder,
    internal_token,
)

BATCH = 16  # 生产契约(deploy/prod/docker-compose.yml EMBEDDER_BATCH_SIZE)


class _FakeResponse:
    def __init__(self, body: dict):
        self._body = json.dumps(body).encode()

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeInternalEndpoint:
    """模拟内部嵌入端点:记录每次请求的 texts 切片;可编程设备/故障。

    - max_batch 给定时按生产契约拒绝越界请求(422,响应体同服务端格式);
    - failures: {第 n 次请求(1 起): (status, detail)} 注入故障;
    - devices: {第 n 次请求: "gpu" | ("cpu", fallback_reason)} 逐片编程;
    - 向量按文本内置序号返回:t"i" → [float(i) * dim 语义],全端点单调,
      由此证明跨切片顺序保持、无丢失、无重复。
    """

    def __init__(self, *, dimension: int = 1, max_batch: int | None = None):
        self.dimension = dimension
        self.max_batch = max_batch
        self.requests: list[list[str]] = []
        self.failures: dict[int, tuple[int, str]] = {}
        self.devices: dict[int, object] = {}

    def __call__(self, req, timeout=None):
        texts = json.loads(req.data.decode())["texts"]
        self.requests.append(list(texts))
        index = len(self.requests)
        if self.max_batch is not None and len(texts) > self.max_batch:
            raise urllib.error.HTTPError(
                req.full_url,
                422,
                "batch too large",
                hdrs=None,
                fp=io.BytesIO(
                    json.dumps({"detail": f"batch too large: {len(texts)} > {self.max_batch}"}).encode()
                ),
            )
        if index in self.failures:
            status, detail = self.failures[index]
            raise urllib.error.HTTPError(
                req.full_url, status, "error", hdrs=None, fp=io.BytesIO(json.dumps({"detail": detail}).encode())
            )
        device, reason = self.devices.get(index, "gpu"), None
        if isinstance(device, tuple):
            device, reason = device
        vectors = [[float(int(t[1:]))] * self.dimension for t in texts]
        return _FakeResponse(
            {
                "vectors": vectors,
                "dimension": self.dimension,
                "execution_device": device,
                "fallback_reason": reason,
                "fallback_detail": None,
            }
        )

    def sizes(self) -> list[int]:
        return [len(r) for r in self.requests]


def _client(endpoint, *, batch_size: int = BATCH) -> _RemoteEmbedderClient:
    return _RemoteEmbedderClient("http://b", internal_token("s"), batch_size=batch_size)


def _texts(n: int) -> list[str]:
    return [f"t{i}" for i in range(n)]


# --------------------------------------------------------------------------- #
# 请求切分:1/16/17/35/78(生产契约边界)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("count", "expected"),
    [(1, [1]), (16, [16]), (17, [16, 1]), (35, [16, 16, 3]), (78, [16, 16, 16, 16, 14])],
)
def test_request_partitioning(monkeypatch, count, expected):
    endpoint = _FakeInternalEndpoint()
    monkeypatch.setattr("urllib.request.urlopen", endpoint)
    vectors = _client(endpoint).embed(_texts(count))
    assert endpoint.sizes() == expected
    assert len(vectors) == count


def test_production_class_78_enforced_endpoint_succeeds(monkeypatch):
    """生产级复现:端点强制 ≤16 时,78 文本必须经切批成功(矫正前 = 422)。"""
    endpoint = _FakeInternalEndpoint(max_batch=BATCH)
    monkeypatch.setattr("urllib.request.urlopen", endpoint)
    vectors = _client(endpoint).embed(_texts(78))
    assert endpoint.sizes() == [16, 16, 16, 16, 14]
    assert len(vectors) == 78


def test_default_batch_size_matches_settings_default(monkeypatch):
    """未显式传参 = Settings 缺省权威(config.py embedder_batch_size=12)。"""
    endpoint = _FakeInternalEndpoint()
    monkeypatch.setattr("urllib.request.urlopen", endpoint)
    _client(endpoint, batch_size=12).embed(_texts(35))
    assert endpoint.sizes() == [12, 12, 11]


# --------------------------------------------------------------------------- #
# 顺序 / 完整性 / 输入不可变
# --------------------------------------------------------------------------- #


def test_order_preserved_no_loss_no_duplicates(monkeypatch):
    endpoint = _FakeInternalEndpoint()
    monkeypatch.setattr("urllib.request.urlopen", endpoint)
    vectors = _client(endpoint).embed(_texts(35))
    # 全端点单调序号:t"i" → [float(i)];顺序保持 + 无丢失 + 无重复
    assert [float(v[0]) for v in vectors] == [float(i) for i in range(35)]
    assert all(isinstance(v, np.ndarray) for v in vectors)


def test_input_list_not_mutated(monkeypatch):
    endpoint = _FakeInternalEndpoint()
    monkeypatch.setattr("urllib.request.urlopen", endpoint)
    texts = _texts(35)
    snapshot = list(texts)
    _client(endpoint).embed(texts)
    assert texts == snapshot


def test_empty_input_returns_empty_without_request(monkeypatch):
    endpoint = _FakeInternalEndpoint()
    monkeypatch.setattr("urllib.request.urlopen", endpoint)
    assert _client(endpoint).embed([]) == []
    assert endpoint.requests == []


# --------------------------------------------------------------------------- #
# 失败语义:中间片失败 = 整体失败;服务端错误如实透传 + 切片上下文
# --------------------------------------------------------------------------- #


def test_middle_slice_failure_fails_whole_call(monkeypatch):
    endpoint = _FakeInternalEndpoint()
    endpoint.failures[2] = (422, "batch too large: 21 > 16")
    monkeypatch.setattr("urllib.request.urlopen", endpoint)
    # embed 必须 raise(无部分向量列表逃逸 —— raise 即无返回值)
    with pytest.raises(RuntimeError, match="HTTP 422") as excinfo:
        _client(endpoint).embed(_texts(35))
    # 第三片不再发送(无客户端重试)
    assert endpoint.sizes() == [16, 16]
    # 切片上下文可诊断 + 服务端 detail 如实透传
    assert "slice 2/3" in str(excinfo.value)
    assert "batch too large: 21 > 16" in str(excinfo.value)


def test_unreachable_slice_error_carries_slice_context(monkeypatch):
    def unreachable(req, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", unreachable)
    # 传输级失败自然落在第一片;错误必须携带切片上下文供诊断
    with pytest.raises(RuntimeError, match=r"unreachable.*slice 1/3"):
        _client(_FakeInternalEndpoint()).embed(_texts(35))


# --------------------------------------------------------------------------- #
# 设备/回退真相:跨切片单向 GPU→CPU,绝不回退 GPU
# --------------------------------------------------------------------------- #


def test_cpu_fallback_state_across_slices(monkeypatch):
    endpoint = _FakeInternalEndpoint()
    endpoint.devices = {1: "gpu", 2: ("cpu", "cuda_oom"), 3: "cpu"}
    monkeypatch.setattr("urllib.request.urlopen", endpoint)
    handle = RemoteSyncEmbedder(_client(endpoint))
    vectors = handle.embed(_texts(35))  # 3 片:16+16+3
    assert len(vectors) == 35
    assert handle.telemetry_execution_device == "gpu_to_cpu"
    assert handle.fallback_reason == "cuda_oom"
    assert handle.runtime_device == "cpu"
    # 遥测一次公共调用仍记一次 attempt;cpu 批次按公共调用计
    assert handle.activity_snapshot()[0] == 1
    assert handle.cpu_batches == 1 and handle.cpu_docs == 35


def test_no_gpu_regression_after_fallback(monkeypatch):
    endpoint = _FakeInternalEndpoint()
    endpoint.devices = {1: "gpu", 2: ("cpu", "cuda_oom"), 3: "gpu"}
    monkeypatch.setattr("urllib.request.urlopen", endpoint)
    client = _client(endpoint)
    client.embed(_texts(35))
    # 第三片(异常地)报告 gpu 也不得把真相拉回 GPU —— 服务端回退单向
    assert client.execution_device == "cpu"
    assert client.fallback_reason == "cuda_oom"


# --------------------------------------------------------------------------- #
# 工厂:batch_size 来自同一 Settings 权威
# --------------------------------------------------------------------------- #


def test_factory_passes_settings_batch_size(monkeypatch):
    class _Settings:
        jwt_secret = "s"
        internal_api_base_url = "http://b"
        embedder_batch_size = 2

    endpoint = _FakeInternalEndpoint()
    monkeypatch.setattr("urllib.request.urlopen", endpoint)
    handle = build_remote_sync_embedder(_Settings())
    handle.embed(_texts(5))
    assert endpoint.sizes() == [2, 2, 1]


def test_invalid_batch_size_rejected_at_construction():
    with pytest.raises(ValueError, match="batch_size"):
        _RemoteEmbedderClient("http://b", internal_token("s"), batch_size=0)
