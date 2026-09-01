"""P1 生成可靠性 — LLMRouter.stream 中途失败禁止故障切换重放。

旧缺陷:LLMRouter.stream 对所有异常一律 ``continue`` 切换下一供应商。
当当前供应商已产出 token 后中途超时(Q32/Q50 路径),切换下一供应商会
从头重放整段答案 → 已发出的 SSE token 重复输出。

契约:与 DeepseekProvider.stream 的 produced 守卫语义对齐 ——
- 首 chunk 前失败:允许切换下一供应商(故障切换语义保留);
- 已产出 token 后失败:立即向上抛出,由 SSE 层降级为用户可见中断。
"""

from unittest.mock import AsyncMock

import pytest

from backend.llm.registry import LLMRouter


def _provider(stream_factory, healthy: bool = True):
    """构造带 health_check / stream 的 mock 供应商。"""
    p = AsyncMock()
    p.health_check = AsyncMock(return_value=healthy)

    def _stream(messages, **kwargs):
        return stream_factory(messages, **kwargs)

    p.stream = _stream
    return p


@pytest.mark.unit
async def test_router_stream_failover_before_first_token():
    """首 chunk 前失败 → 切换下一供应商(既有故障切换语义保留)。"""

    async def _fail_immediately(messages, **kwargs):
        raise RuntimeError("connect timeout")
        yield  # pragma: no cover

    async def _ok(messages, **kwargs):
        yield "second provider answer"

    router = LLMRouter(
        providers={"p1": _provider(_fail_immediately), "p2": _provider(_ok)},
        routing={"generation": [{"provider": "p1"}, {"provider": "p2"}]},
    )
    chunks = [c async for c in router.stream([{"role": "user", "content": "q"}], task="generation")]
    assert chunks == ["second provider answer"]


@pytest.mark.unit
async def test_router_stream_no_restart_after_partial_output():
    """已产出 token 后失败 → 立即抛出,不得切换供应商重放(防重复输出)。"""

    async def _partial_then_timeout(messages, **kwargs):
        yield "partial "
        raise RuntimeError("read timeout mid-stream")

    async def _ok(messages, **kwargs):
        yield "REPLAYED FULL ANSWER"

    router = LLMRouter(
        providers={"p1": _provider(_partial_then_timeout), "p2": _provider(_ok)},
        routing={"generation": [{"provider": "p1"}, {"provider": "p2"}]},
    )
    collected = []
    with pytest.raises(RuntimeError, match="read timeout"):
        async for chunk in router.stream([{"role": "user", "content": "q"}], task="generation"):
            collected.append(chunk)

    # 已产出内容不被下一供应商重放覆盖
    assert collected == ["partial "]


@pytest.mark.unit
async def test_router_stream_all_fail_before_token_raises():
    """全部供应商首 chunk 前失败 → 维持既有 RuntimeError 语义。"""

    async def _fail(messages, **kwargs):
        raise RuntimeError("down")
        yield  # pragma: no cover

    router = LLMRouter(
        providers={"p1": _provider(_fail), "p2": _provider(_fail)},
        routing={"generation": [{"provider": "p1"}, {"provider": "p2"}]},
    )
    with pytest.raises(RuntimeError, match="All LLM providers unavailable"):
        async for _chunk in router.stream([{"role": "user", "content": "q"}], task="generation"):
            pass
