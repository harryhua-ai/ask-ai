"""RemoteSyncEmbedder 客户端切批矫正(TB-P1 reindex 422 缺陷)RED→GREEN。

生产缺陷(09-11 v1.6.1 验收 §17 实证):``_ingest_doc_batch`` 把 ≤64 doc 的
全部 chunk 拼成单次逻辑 ``embed()``;本地 embedder 内部切批,而
``_RemoteEmbedderClient`` 把整表直发一次 HTTP → 服务端按
``EMBEDDER_BATCH_SIZE``(生产 =16)强制 422(``batch too large: 488 > 16``),
生成重建对全部生产源不可用。

契约(冻结):客户端按配置批界把逻辑请求切成 ≤B 的传输批,串行发送、
按序拼接;输出数=输入数、顺序不变、零丢失零重复;任一批失败即抛出
(fail-closed),绝不以部分聚合冒充成功;空输入保持既有单请求语义。
"""

import json
import urllib.error

import numpy as np
import pytest

from backend.embedder.remote import (
    RemoteSyncEmbedder,
    _RemoteEmbedderClient,
    internal_token,
)


class _FakeResponse:
    def __init__(self, body: dict):
        self._body = json.dumps(body).encode()

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeTransport:
    """记录每个 HTTP 请求载荷并按序应答;可编程批界 422 与指定批次失败。

    应答向量以「全局序号」编码在首维([global_index, 0, 1, 2]),用于断言
    跨批拼接后输出顺序与输入顺序精确一致。``server_batch_limit`` 模拟真实
    服务端行为:载荷超过批界即 422(生产缺陷复现器)。
    """

    def __init__(
        self,
        dimension: int = 4,
        server_batch_limit: int | None = None,
        fail_at_request: int | None = None,
        fail_code: int = 503,
    ):
        self.payloads: list[list[str]] = []
        self.dimension = dimension
        self.server_batch_limit = server_batch_limit
        self.fail_at_request = fail_at_request
        self.fail_code = fail_code

    def __call__(self, req, timeout=None):
        body = json.loads(req.data.decode())
        texts = body["texts"]
        if self.server_batch_limit is not None and len(texts) > self.server_batch_limit:
            raise urllib.error.HTTPError(
                req.full_url,
                422,
                f"batch too large: {len(texts)} > {self.server_batch_limit}",
                hdrs=None,
                fp=None,
            )
        if self.fail_at_request is not None and len(self.payloads) == self.fail_at_request - 1:
            raise urllib.error.HTTPError(
                req.full_url, self.fail_code, "embedding unavailable", hdrs=None, fp=None
            )
        base = sum(len(p) for p in self.payloads)
        self.payloads.append(texts)
        vectors = [[float(base + i), 0.0, 1.0, 2.0] for i in range(len(texts))]
        return _FakeResponse(
            {
                "vectors": vectors,
                "dimension": self.dimension,
                "execution_device": "gpu",
                "fallback_reason": None,
                "fallback_detail": None,
            }
        )


def _make_client(monkeypatch, batch_size, transport: _FakeTransport) -> _RemoteEmbedderClient:
    monkeypatch.setattr("urllib.request.urlopen", transport)
    return _RemoteEmbedderClient("http://b", internal_token("s"), batch_size=batch_size)


def test_single_batch_when_below_limit(monkeypatch):
    """N < B:恰好一次传输请求,载荷与输入逐项一致。"""
    t = _FakeTransport()
    client = _make_client(monkeypatch, 16, t)
    assert len(client.embed(["a", "b", "c", "d", "e"])) == 5
    assert len(t.payloads) == 1
    assert t.payloads[0] == ["a", "b", "c", "d", "e"]


def test_single_batch_when_exactly_limit(monkeypatch):
    """N == B:仍是一次传输请求(不多切)。"""
    t = _FakeTransport()
    client = _make_client(monkeypatch, 16, t)
    texts = [f"t{i}" for i in range(16)]
    assert len(client.embed(texts)) == 16
    assert len(t.payloads) == 1
    assert t.payloads[0] == texts


def test_two_batches_when_one_over_limit(monkeypatch):
    """N == B+1:恰两次传输请求,批尺寸 [B, 1]。"""
    t = _FakeTransport()
    client = _make_client(monkeypatch, 16, t)
    texts = [f"t{i}" for i in range(17)]
    assert len(client.embed(texts)) == 17
    assert [len(p) for p in t.payloads] == [16, 1]


def test_production_scale_488_every_transport_call_bounded(monkeypatch):
    """生产规模复现:488 文本 / B=16 → 每次传输调用 ≤16,总量 488 无丢失。"""
    t = _FakeTransport()
    client = _make_client(monkeypatch, 16, t)
    texts = [f"chunk-{i}" for i in range(488)]
    vectors = client.embed(texts)
    assert len(t.payloads) == 31  # 30×16 + 1×8
    assert all(len(p) <= 16 for p in t.payloads)
    assert sum(len(p) for p in t.payloads) == 488
    assert len(vectors) == 488


def test_order_preserved_across_batch_boundaries(monkeypatch):
    """跨批边界输出顺序与输入顺序精确一致(应答向量编码全局序号)。"""
    t = _FakeTransport()
    client = _make_client(monkeypatch, 16, t)
    texts = [f"t{i}" for i in range(50)]
    vectors = client.embed(texts)
    assert [int(v[0]) for v in vectors] == list(range(50))


def test_output_count_equals_input_count(monkeypatch):
    """输出数 == 输入数(489:B 上方一位,跨三个批)。"""
    t = _FakeTransport()
    client = _make_client(monkeypatch, 16, t)
    texts = [f"t{i}" for i in range(489)]
    assert len(client.embed(texts)) == len(texts) == 489


def test_empty_input_keeps_single_request_semantics(monkeypatch):
    """空输入保持既有行为:不切批,单请求原样到达传输层。"""
    t = _FakeTransport()
    client = _make_client(monkeypatch, 16, t)
    assert client.embed([]) == []
    assert len(t.payloads) == 1
    assert t.payloads[0] == []


def test_first_batch_failure_raises_no_aggregate(monkeypatch):
    """首批失败:抛出既有嵌入失败;fail-fast,不再发起后续批次。"""
    t = _FakeTransport(fail_at_request=1)
    client = _make_client(monkeypatch, 16, t)
    with pytest.raises(RuntimeError, match="HTTP 503"):
        client.embed([f"t{i}" for i in range(40)])
    assert len(t.payloads) == 0  # fail_at=1 在记账前抛出,零成功批


def test_middle_batch_failure_raises_no_partial_success(monkeypatch):
    """中批失败:抛出失败,不返回任何部分聚合结果。"""
    t = _FakeTransport(fail_at_request=2)
    client = _make_client(monkeypatch, 16, t)
    with pytest.raises(RuntimeError, match="HTTP 503"):
        client.embed([f"t{i}" for i in range(40)])
    assert len(t.payloads) == 1  # 仅首批成功,第二批发起即抛


def test_final_short_batch_handled(monkeypatch):
    """末尾短批([16,16,3])正确收尾:计数与顺序均成立。"""
    t = _FakeTransport()
    client = _make_client(monkeypatch, 16, t)
    texts = [f"t{i}" for i in range(35)]
    vectors = client.embed(texts)
    assert [len(p) for p in t.payloads] == [16, 16, 3]
    assert len(vectors) == 35
    assert [int(v[0]) for v in vectors] == list(range(35))


def test_realistic_vector_shapes_concatenate(monkeypatch):
    """真实向量形状(1024 维 float32)跨批拼接正确。"""
    t = _FakeTransport(dimension=1024)
    client = _make_client(monkeypatch, 16, t)
    texts = [f"t{i}" for i in range(33)]
    vectors = client.embed(texts)
    assert len(vectors) == 33
    assert all(isinstance(v, np.ndarray) and v.shape == (1024,) and v.dtype == np.float32 for v in vectors)
    assert [int(v[0]) for v in vectors] == list(range(33))


def test_reindex_caller_needs_no_prechunking(monkeypatch):
    """集成回归(生产缺陷类):>16 chunk 的单次逻辑请求经
    RemoteSyncEmbedder 全链,传输批恒 ≤16 → 不再出现 422;
    调用方(生成重建/_ingest_doc_batch)无需围绕远端批界预切。"""
    t = _FakeTransport(server_batch_limit=16)
    monkeypatch.setattr("urllib.request.urlopen", t)
    client = _RemoteEmbedderClient("http://b", internal_token("s"), batch_size=16)
    handle = RemoteSyncEmbedder(client)
    texts = [f"reindex chunk {i}" for i in range(488)]
    vectors = handle.embed(texts)
    assert len(vectors) == 488
    assert [int(v[0]) for v in vectors] == list(range(488))
    assert len(t.payloads) == 31
    assert all(len(p) <= 16 for p in t.payloads)
    # GPU 路径遥测不受切批影响:零 CPU 批次
    assert handle.cpu_batches == 0
    assert handle.telemetry_execution_device == "gpu"


def test_build_wires_canonical_batch_size(monkeypatch):
    """构造布线:build_remote_sync_embedder 必须以 settings.embedder_batch_size
    (唯一权威配置)实例化客户端,不得第二配置源。"""

    class _Settings:
        jwt_secret = "s"
        internal_api_base_url = "http://b"
        embedder_batch_size = 16

    captured: dict = {}

    def fake_init(self, client, **kwargs):
        captured["client"] = client
        return RemoteSyncEmbedder.__new__(RemoteSyncEmbedder)

    monkeypatch.setattr("backend.embedder.remote.RemoteSyncEmbedder.__init__", fake_init)
    from backend.embedder.remote import build_remote_sync_embedder

    build_remote_sync_embedder(_Settings())
    assert captured["client"].batch_size == 16
