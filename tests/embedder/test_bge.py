"""BGE-m3 嵌入模型与 bge-reranker-v2-m3 重排模型测试。

单元测试覆盖 detect_device 设备检测逻辑(无需下载模型权重);
集成测试验证真实模型推理,首次运行会下载数 GB 权重。
"""

import sys
import types

import numpy as np
import pytest

from backend.embedder.base import Embedder, Reranker, detect_device

# --------------------------------------------------------------------------- #
# 单元测试:detect_device
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_detect_device_explicit_cpu():
    """传入 "cpu" 应直接返回 "cpu",不触发 torch 检测。"""
    assert detect_device("cpu") == "cpu"


@pytest.mark.unit
def test_detect_device_explicit_cuda():
    """传入 "cuda" 应直接返回 "cuda",不触发 torch 检测。"""
    assert detect_device("cuda") == "cuda"


@pytest.mark.unit
def test_detect_device_explicit_mps():
    """传入 "mps" 应直接返回 "mps",不触发 torch 检测。"""
    assert detect_device("mps") == "mps"


@pytest.mark.unit
def test_detect_device_auto_falls_back_to_cpu(monkeypatch):
    """auto 模式下,当 cuda/mps 均不可用时,应回落到 "cpu"。"""

    class FakeCuda:
        @staticmethod
        def is_available():
            return False

    class FakeBackends:
        class mps:
            @staticmethod
            def is_available():
                return False

    fake_torch = types.SimpleNamespace(
        cuda=FakeCuda(),
        backends=FakeBackends(),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    assert detect_device("auto") == "cpu"


@pytest.mark.unit
def test_detect_device_auto_prefers_cuda(monkeypatch):
    """auto 模式下,当 cuda 可用时应返回 "cuda"。"""

    class FakeCuda:
        @staticmethod
        def is_available():
            return True

    class FakeBackends:
        class mps:
            @staticmethod
            def is_available():
                return False

    fake_torch = types.SimpleNamespace(
        cuda=FakeCuda(),
        backends=FakeBackends(),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    assert detect_device("auto") == "cuda"


@pytest.mark.unit
def test_detect_device_auto_uses_mps_when_no_cuda(monkeypatch):
    """auto 模式下,cuda 不可用但 mps 可用时,应返回 "mps"。"""

    class FakeCuda:
        @staticmethod
        def is_available():
            return False

    class FakeBackends:
        class mps:
            @staticmethod
            def is_available():
                return True

    fake_torch = types.SimpleNamespace(
        cuda=FakeCuda(),
        backends=FakeBackends(),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    assert detect_device("auto") == "mps"


# --------------------------------------------------------------------------- #
# 单元测试:Protocol 结构契约
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_embedder_protocol_is_runtime_checkable():
    """Embedder 协议应被 @runtime_checkable 装饰,支持 isinstance 检查。"""
    assert isinstance.__name__ == "isinstance"

    # runtime_checkable Protocol 的 isinstance 仅校验属性存在性,不校验签名。
    # 这里用一个最小 mock 验证 Protocol 装饰生效。
    class FakeEmbedder:
        @property
        def dimension(self) -> int:
            return 1024

        def embed(self, texts: list[str]) -> list[np.ndarray]:
            return []

    assert isinstance(FakeEmbedder(), Embedder)


@pytest.mark.unit
def test_reranker_protocol_is_runtime_checkable():
    """Reranker 协议应被 @runtime_checkable 装饰,支持 isinstance 检查。"""

    class FakeReranker:
        def rerank(self, query: str, documents: list[str]) -> list[float]:
            return []

    assert isinstance(FakeReranker(), Reranker)


# --------------------------------------------------------------------------- #
# 集成测试:真实模型推理(首次运行需下载权重)
# --------------------------------------------------------------------------- #


@pytest.mark.integration
def test_embedder_produces_vectors():
    """BGEEmbedder 应为每个输入文本返回 1024 维 np.ndarray。"""
    from backend.embedder.bge import BGEEmbedder

    embedder = BGEEmbedder(device="cpu")
    vectors = embedder.embed(["Hello world", "NE503 specs"])
    assert len(vectors) == 2
    assert all(isinstance(v, np.ndarray) for v in vectors)
    assert all(v.shape == (1024,) for v in vectors)


@pytest.mark.integration
def test_embedder_dimension_property():
    """BGEEmbedder.dimension 应固定返回 1024。"""
    from backend.embedder.bge import BGEEmbedder

    embedder = BGEEmbedder(device="cpu")
    assert embedder.dimension == 1024


@pytest.mark.integration
def test_reranker_scores_pairs():
    """BGEReranker 应为相关文档打出更高分数。"""
    from backend.embedder.bge import BGEReranker

    reranker = BGEReranker(device="cpu")
    scores = reranker.rerank(
        query="NE503 功耗",
        documents=["NE503 功耗 2.5W", "天气很好今天"],
    )
    assert len(scores) == 2
    assert scores[0] > scores[1]


@pytest.mark.integration
def test_reranker_single_document_returns_list():
    """单文档场景下应返回长度为 1 的列表,而非标量。"""
    from backend.embedder.bge import BGEReranker

    reranker = BGEReranker(device="cpu")
    scores = reranker.rerank(query="test", documents=["only one doc"])
    assert isinstance(scores, list)
    assert len(scores) == 1
