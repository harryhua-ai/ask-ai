"""B1 模块级 fixture 边界回归·step2(恢复断言,跨模块可执行证明)。

依赖收集顺序:pytest 在 tests/embedder/ 内按文件名字母序收集,
test_hf_module_scope_step1_polluter.py 先于本文件执行——即本文件的所有
测试上下文位于 step1 模块级 fixture 的生命周期**之后**。

断言:当前进程 HF 环境 == 会话起点基线(tests/conftest.py 在模块导入期捕获,
早于任何测试/fixture)。覆盖两种语义:
- 变量原本缺失(裸环境/CI)→ 缺失;
- 变量原本存在(本地 warm-cache 预设)→ 逐字节原值。

若模块级 fixture(真实模型构造 real_embedder/real_reranker,或 step1 的
构造器探针)缺少精确恢复边界,本文件失败——这就是可执行的 scope 边界证明,
不依赖测试顺序注释。
"""

import os

_HF_VARS = ("HF_HOME", "HF_HUB_CACHE", "TRANSFORMERS_CACHE")


def test_hf_env_equals_session_baseline_after_module_scope_lifetime(
    hf_session_baseline,
):
    """模块级 fixture 生命周期结束后,环境与会话起点逐字节一致。"""
    for var in _HF_VARS:
        expected = hf_session_baseline[var]
        actual = os.environ.get(var)
        assert actual == expected, (
            f"HF 环境跨模块边界泄漏: {var} 期望 {expected!r}(会话起点), "
            f"实际 {actual!r}"
        )
