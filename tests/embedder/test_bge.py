"""BGE-m3 嵌入模型与 bge-reranker-v2-m3 重排模型测试。

单元测试覆盖 detect_device 设备检测逻辑(无需下载模型权重);
集成测试验证真实模型推理,首次运行会下载数 GB 权重。
"""

import os
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
# B1 隔离回归:HF 环境变量不得跨测试泄漏(test-isolation closure 2026-09-03)
#
# 契约(全局守卫 tests/conftest.py::_hf_env_isolation 提供 teardown 精确恢复):
#   - 变量原本缺失 → 下一测试看到缺失;
#   - 变量原本存在 → 下一测试看到原值(逐字节);
#   - 构造器把缓存指向 tmp 的测试,不得把后续真实 BGE 测试重定向进死 tmp 缓存。
# 两个 step 测试按定义顺序执行(pytest 文件内保序),构成跨测试泄漏哨兵。
# --------------------------------------------------------------------------- #

_HF_VARS = ("HF_HOME", "HF_HUB_CACHE", "TRANSFORMERS_CACHE")

# 模块会话开始时的环境基线(无论开发者 shell 是否预设 HF 变量都成立)
_SESSION_HF_BASELINE: dict[str, str | None] = {}


@pytest.fixture(scope="module", autouse=True)
def _capture_hf_baseline():
    for var in _HF_VARS:
        _SESSION_HF_BASELINE[var] = os.environ.get(var)
    yield


@pytest.mark.unit
def test_hf_env_leak_step1_pollutes_via_ensure_hf_cache(tmp_path):
    """step1:模拟旧缺陷路径——不设变量时 _ensure_hf_cache 把 HF 变量写进 tmp。"""
    probe_dir = tmp_path / "models"
    for var in _HF_VARS:
        os.environ.pop(var, None)  # 模拟「变量原本缺失」的裸环境
    from backend.embedder.bge import _ensure_hf_cache

    _ensure_hf_cache(probe_dir)
    assert os.environ["HF_HOME"] == str(probe_dir)
    assert os.environ["HF_HUB_CACHE"] == str(probe_dir / "hub")
    assert os.environ["TRANSFORMERS_CACHE"] == str(probe_dir / "hub")


@pytest.mark.unit
def test_hf_env_leak_step2_next_test_sees_exact_restoration():
    """step2:守卫必须已把 step1 的 tmp 污染恢复为模块基线(AC1/AC2)。

    若守卫缺失或恢复不精确,本测试失败——即测试顺序可以把后续真实 BGE
    集成测试重定向进已销毁的 tmp 缓存导致重新下载数 GB 权重。
    """
    for var in _HF_VARS:
        assert os.environ.get(var) == _SESSION_HF_BASELINE[var], (
            f"{var} 跨测试泄漏: 期望 {var}={_SESSION_HF_BASELINE[var]!r}, "
            f"实际 {os.environ.get(var)!r}"
        )


@pytest.mark.unit
def test_hf_env_present_values_survive_ensure_hf_cache(tmp_path, monkeypatch):
    """B1 契约·存在情形:预设值在调用前后逐字节保留(setdefault 不覆盖)。"""
    presets = {
        "HF_HOME": "/preset/hf-home",
        "HF_HUB_CACHE": "/preset/hf-hub",
        "TRANSFORMERS_CACHE": "/preset/tf-cache",
    }
    for var, value in presets.items():
        monkeypatch.setenv(var, value)

    from backend.embedder.bge import _ensure_hf_cache

    _ensure_hf_cache(tmp_path / "models")

    import os

    for var, value in presets.items():
        assert os.environ[var] == value


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


def _load_with_exact_hf_env_guard(factory):
    """模块级 fixture 生命周期的 HF 环境精确守卫(B1 契约在更高作用域的延伸)。

    function 级 autouse 守卫(tests/conftest.py::_hf_env_isolation)不覆盖
    module 级 fixture 的 setup/teardown 边界:真实模型构造发生在模块 fixture
    中时,生产 _ensure_hf_cache 的 setdefault 变更会存活到模块之外,重定向
    后续测试的 HF 缓存路由(Planner FINAL REVIEW PARTIAL 修正点)。任何在
    function 作用域之外调用 _ensure_hf_cache 的 fixture 必须在其生命周期内
    以精确快照/finally 恢复:缺失→缺失;存在→原值。

    推理期不读 HF 环境变量,构造一结束即恢复不影响已加载实例;
    构造抛异常时同样恢复(finally)。
    """
    snapshot = {var: os.environ[var] for var in _HF_VARS if var in os.environ}
    try:
        return factory()
    finally:
        for var in _HF_VARS:
            if var in snapshot:
                os.environ[var] = snapshot[var]
            else:
                os.environ.pop(var, None)


@pytest.fixture(scope="module")
def real_embedder():
    """模块级共享真实 BGE-m3 实例(B5)。

    encode 是无状态推理,生产环境同样是单实例常驻(app.state.rag);
    模块内复用一次热加载,省去逐测试重复加载(~1.6s×2)且不改变断言语义。
    """
    from backend.embedder.bge import BGEEmbedder

    return _load_with_exact_hf_env_guard(lambda: BGEEmbedder(device="cpu"))


@pytest.fixture(scope="module")
def real_reranker():
    """模块级共享真实 bge-reranker 实例(同 real_embedder)。"""
    from backend.embedder.bge import BGEReranker

    return _load_with_exact_hf_env_guard(lambda: BGEReranker(device="cpu"))


@pytest.mark.integration
def test_embedder_produces_vectors(real_embedder):
    """BGEEmbedder 应为每个输入文本返回 1024 维 np.ndarray。"""
    vectors = real_embedder.embed(["Hello world", "NE503 specs"])
    assert len(vectors) == 2
    assert all(isinstance(v, np.ndarray) for v in vectors)
    assert all(v.shape == (1024,) for v in vectors)


@pytest.mark.integration
def test_embedder_dimension_property(real_embedder):
    """BGEEmbedder.dimension 应固定返回 1024。"""
    assert real_embedder.dimension == 1024


@pytest.mark.integration
def test_reranker_scores_pairs(real_reranker):
    """BGEReranker 应为相关文档打出更高分数。"""
    scores = real_reranker.rerank(
        query="NE503 功耗",
        documents=["NE503 功耗 2.5W", "天气很好今天"],
    )
    assert len(scores) == 2
    assert scores[0] > scores[1]


@pytest.mark.integration
def test_reranker_single_document_returns_list(real_reranker):
    """单文档场景下应返回长度为 1 的列表,而非标量。"""
    scores = real_reranker.rerank(query="test", documents=["only one doc"])
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
