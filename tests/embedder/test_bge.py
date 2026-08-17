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
# 单元测试:HuggingFace 本地缓存路由
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_ensure_hf_cache_sets_env_vars(tmp_path, monkeypatch):
    """_ensure_hf_cache 应设置 HF_HOME/HF_HUB_CACHE/TRANSFORMERS_CACHE 指向项目目录。"""
    monkeypatch.delenv("HF_HOME", raising=False)
    monkeypatch.delenv("HF_HUB_CACHE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_CACHE", raising=False)

    from backend.embedder.bge import _ensure_hf_cache

    cache_dir = tmp_path / "models"
    _ensure_hf_cache(cache_dir)

    import os

    assert os.environ["HF_HOME"] == str(cache_dir)
    assert os.environ["HF_HUB_CACHE"] == str(cache_dir / "hub")
    assert os.environ["TRANSFORMERS_CACHE"] == str(cache_dir / "hub")
    assert (cache_dir / "hub").is_dir()


@pytest.mark.unit
def test_ensure_hf_cache_does_not_override_existing(tmp_path, monkeypatch):
    """已存在的 HF_HOME 不应被覆盖(setdefault 语义)。"""
    monkeypatch.setenv("HF_HOME", "/preconfigured")
    cache_dir = tmp_path / "models"

    from backend.embedder.bge import _ensure_hf_cache

    _ensure_hf_cache(cache_dir)

    import os

    assert os.environ["HF_HOME"] == "/preconfigured"


# --------------------------------------------------------------------------- #
# 单元测试:构造参数 devices 透传(防 FlagEmbedding 自选 GPU 回归)
# --------------------------------------------------------------------------- #


def _make_fake_flagembedding() -> tuple[types.ModuleType, list, list]:
    """构造记录调用参数的假 FlagEmbedding 模块(不加载真实权重)。

    Returns:
        (fake 模块, BGEM3FlagModel 调用记录列表, FlagReranker 调用记录列表)
    """
    bgem3_calls: list[dict] = []
    reranker_calls: list[dict] = []

    class BGEM3FlagModel:
        def __init__(self, *args, **kwargs):
            bgem3_calls.append({"args": args, "kwargs": kwargs})

    class FlagReranker:
        def __init__(self, *args, **kwargs):
            reranker_calls.append({"args": args, "kwargs": kwargs})

    mod = types.ModuleType("FlagEmbedding")
    mod.BGEM3FlagModel = BGEM3FlagModel
    mod.FlagReranker = FlagReranker
    return mod, bgem3_calls, reranker_calls


@pytest.mark.unit
@pytest.mark.parametrize("device,use_fp16", [("cpu", False), ("cuda", True)])
def test_embedder_passes_device_to_flagembedding(monkeypatch, tmp_path, device, use_fp16):
    """BGEEmbedder 构造必须显式传 devices,否则 FlagEmbedding 检测到
    cuda 后会无视 EMBEDDER_DEVICE 自行上 GPU(共享 T4 显存满时 sync
    embed OOM,2026-08-17 踩过:cpu 模式实际以 fp32 加载上 GPU)。"""

    from backend.embedder.bge import BGEEmbedder

    mod, bgem3_calls, _ = _make_fake_flagembedding()
    monkeypatch.setitem(sys.modules, "FlagEmbedding", mod)

    BGEEmbedder(device=device, cache_dir=tmp_path)

    assert bgem3_calls[0]["kwargs"]["devices"] == [device]
    assert bgem3_calls[0]["kwargs"]["use_fp16"] is use_fp16


@pytest.mark.unit
@pytest.mark.parametrize("device,use_fp16", [("cpu", False), ("cuda", True)])
def test_reranker_passes_device_to_flagembedding(monkeypatch, tmp_path, device, use_fp16):
    """BGEReranker 构造必须显式传 devices(同 BGEEmbedder,防自选 GPU)。"""

    from backend.embedder.bge import BGEReranker

    mod, _, reranker_calls = _make_fake_flagembedding()
    monkeypatch.setitem(sys.modules, "FlagEmbedding", mod)

    BGEReranker(device=device, cache_dir=tmp_path)

    assert reranker_calls[0]["kwargs"]["devices"] == [device]
    assert reranker_calls[0]["kwargs"]["use_fp16"] is use_fp16


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


def test_bge_embedder_accepts_batch_max_length():
    """BGEEmbedder 接受 batch_size/max_length(GPU 大 batch 配置化)。"""
    import inspect

    from backend.embedder.bge import BGEEmbedder

    sig = inspect.signature(BGEEmbedder.__init__)
    assert "batch_size" in sig.parameters
    assert "max_length" in sig.parameters
    src = inspect.getsource(BGEEmbedder.embed)
    assert "self._batch_size" in src and "self._max_length" in src
