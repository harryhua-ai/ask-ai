"""B1 模块级 fixture 边界回归·step1(污染方)。

Planner FINAL REVIEW PARTIAL 修正(2026-09-03):function 级 autouse 守卫
(tests/conftest.py::_hf_env_isolation)不覆盖 module 级 fixture 的
setup/teardown 生命周期——真实模型构造(real_embedder/real_reranker)发生在
模块 fixture 中时,生产 _ensure_hf_cache 的进程级 setdefault 变更会存活到
模块之外,污染后续测试的 HF 缓存路由。

本文件用**模块级 fixture** 复刻该生命周期:fixture 内先强制「变量原本缺失」,
再经真实生产构造器(BGEEmbedder + fake FlagEmbedding,不加载权重)触发
_ensure_hf_cache(tmp) 的真实进程环境变更,并在测试内断言污染确实活跃。
恢复边界(本 fixture 的 finally)与跨模块恢复断言见
test_hf_module_scope_step2_restored.py(按文件名字母序在本文件之后收集)。

可执行证明的性质:这不是函数到函数的又一次变更,而是真被测的
fixture-scope 边界——若模块级 fixture 缺少精确恢复,step2 必失败。
"""

import os
import sys
import types

import pytest

from backend.embedder.bge import BGEEmbedder

_HF_VARS = ("HF_HOME", "HF_HUB_CACHE", "TRANSFORMERS_CACHE")


def _fake_flagembedding_module() -> types.ModuleType:
    """构造不加载权重的假 FlagEmbedding(仅记录构造调用)。"""

    class _FakeModel:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    mod = types.ModuleType("FlagEmbedding")
    mod.BGEM3FlagModel = _FakeModel
    mod.FlagReranker = _FakeModel
    return mod


@pytest.fixture(scope="module")
def module_scope_hf_pollution(tmp_path_factory):
    """模块级 fixture:在其生命周期内经生产构造器变更进程 HF 环境。

    与 real_embedder 的关键共性:真实 BGEEmbedder.__init__ 在模块级 fixture
    的 setup 中执行,_ensure_hf_cache 的 setdefault 直接写 os.environ——
    function 级守卫对该变更无恢复边界。finally 块即「被测的模块级恢复边界」。
    """
    probe_dir = tmp_path_factory.mktemp("hf-module-scope-probe") / "models"
    pre = {var: os.environ.get(var) for var in _HF_VARS}
    mp = pytest.MonkeyPatch()
    try:
        mp.setitem(sys.modules, "FlagEmbedding", _fake_flagembedding_module())
        for var in _HF_VARS:
            os.environ.pop(var, None)  # 强制「变量原本缺失」的变更前置态
        # 真实生产构造器路径:__init__ 内 _ensure_hf_cache(probe_dir) 真实变更进程 env
        BGEEmbedder(device="cpu", cache_dir=probe_dir)
        yield {
            "expected_hf_home": str(probe_dir),
            "pre": pre,
        }
    finally:
        # ★ 被测边界:模块级 fixture 生命周期结束时的精确恢复
        # (缺失→缺失;存在→原值)。修复缺失时 step2 必失败。
        for var in _HF_VARS:
            if pre[var] is not None:
                os.environ[var] = pre[var]
            else:
                os.environ.pop(var, None)
        mp.undo()


def test_module_scope_fixture_pollution_is_active_within_lifetime(
    module_scope_hf_pollution,
):
    """模块 fixture 生命周期内:变更确实发生(否则本回归无从谈起)。"""
    info = module_scope_hf_pollution
    expected_home = info["expected_hf_home"]
    assert os.environ["HF_HOME"] == expected_home
    assert os.environ["HF_HUB_CACHE"] == os.path.join(expected_home, "hub")
    assert os.environ["TRANSFORMERS_CACHE"] == os.path.join(expected_home, "hub")
    # 会话基线值在本模块生命周期内被临时替换(与基线的差异即污染本身)
    for var in _HF_VARS:
        if info["pre"][var] is not None:
            assert os.environ[var] != info["pre"][var]
