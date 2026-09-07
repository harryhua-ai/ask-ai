"""INC-1 可观测基线 — LLMRouter 调用事件遥测单测。

契约(见 docs/engineering/tasks/INC-1-ANSWER-OBSERVABILITY-execution.md):
- 每次 generate/stream 尝试产生一条结构化事件(task/provider/model/
  generation_chain_fallback/attempt/latency_ms/tokens/thinking/success/complete);
- 事件只含标量元数据,不含 prompt/响应内容;
- 流式 usage 由 provider 经 telemetry 上下文报告,router 收尾回填事件;
- 既有故障切换/produced 守卫语义不变。
"""

from unittest.mock import AsyncMock

import pytest

from backend.llm import telemetry
from backend.llm.base import LLMResponse
from backend.llm.registry import LLMRouter


def _provider(model: str = "fake-model"):
    p = AsyncMock()
    p.health_check = AsyncMock(return_value=True)
    p.model = model
    p.generate = AsyncMock(
        return_value=LLMResponse(
            content="ok", model=model, tokens_input=11, tokens_output=22, latency_ms=3
        )
    )
    return p


@pytest.mark.unit
async def test_generate_success_event_fields():
    router = LLMRouter(
        providers={"p1": _provider()},
        routing={"intent": [{"provider": "p1", "model": "intent-model"}]},
    )
    telemetry.start_capture()
    await router.generate([{"role": "user", "content": "q"}], task="intent")
    events = telemetry.current_calls()
    assert len(events) == 1
    ev = events[0]
    assert ev["task"] == "intent"
    assert ev["provider"] == "p1"
    assert ev["model"] == "intent-model"
    assert ev["generation_chain_fallback"] is False
    assert ev["success"] is True
    assert ev["thinking"] == "provider-default"
    assert isinstance(ev["latency_ms"], int)
    assert ev["tokens_input"] == 11
    assert ev["tokens_output"] == 22


@pytest.mark.unit
async def test_generate_generation_chain_fallback_flagged():
    """任务无专属链路 → 回退 generation 链,事件必须标记。"""
    router = LLMRouter(providers={"p1": _provider()}, routing={"generation": [{"provider": "p1"}]})
    telemetry.start_capture()
    await router.generate([{"role": "user", "content": "q"}], task="intent")
    ev = telemetry.current_calls()[0]
    assert ev["generation_chain_fallback"] is True


@pytest.mark.unit
async def test_generate_failover_records_failed_attempt():
    ok = _provider()
    bad = _provider()
    bad.generate = AsyncMock(side_effect=RuntimeError("boom"))
    router = LLMRouter(
        providers={"p1": bad, "p2": ok},
        routing={"generation": [{"provider": "p1"}, {"provider": "p2"}]},
    )
    telemetry.start_capture()
    await router.generate([{"role": "user", "content": "q"}], task="generation")
    events = telemetry.current_calls()
    assert [e["success"] for e in events] == [False, True]
    assert events[0]["error"] == "RuntimeError"
    assert events[1]["attempt"] == 2


@pytest.mark.unit
async def test_generate_all_fail_records_terminal_event():
    bad = _provider()
    bad.generate = AsyncMock(side_effect=RuntimeError("boom"))
    router = LLMRouter(providers={"p1": bad}, routing={"generation": [{"provider": "p1"}]})
    telemetry.start_capture()
    with pytest.raises(RuntimeError):
        await router.generate([{"role": "user", "content": "q"}], task="generation")
    events = telemetry.current_calls()
    assert events[-1]["success"] is False
    assert "complete" not in events[-1]


@pytest.mark.unit
async def test_stream_records_provider_usage_and_complete():
    class _P:
        provider_id = "p1"

        async def health_check(self):
            return True

        async def stream(self, messages, **kwargs):
            yield "Hel"
            yield "lo"
            telemetry.record_stream_usage(7, 22)

    router = LLMRouter(providers={"p1": _P()}, routing={"generation": [{"provider": "p1"}]})
    telemetry.start_capture()
    chunks = [c async for c in router.stream([{"role": "user", "content": "q"}], task="generation")]
    assert chunks == ["Hel", "lo"]
    ev = telemetry.current_calls()[0]
    assert ev["success"] is True
    assert ev["complete"] is True
    assert ev["tokens_input"] == 7
    assert ev["tokens_output"] == 22


@pytest.mark.unit
async def test_stream_abort_records_incomplete():
    class _P:
        provider_id = "p1"

        async def health_check(self):
            return True

        async def stream(self, messages, **kwargs):
            yield "partial"
            yield "more"

    router = LLMRouter(providers={"p1": _P()}, routing={"generation": [{"provider": "p1"}]})
    telemetry.start_capture()
    gen = router.stream([{"role": "user", "content": "q"}])
    async for chunk in gen:
        break  # 模拟客户端断开
    await gen.aclose()  # 显式关闭:GeneratorExit 在当前上下文内送达
    ev = telemetry.current_calls()[0]
    assert ev["complete"] is False
    assert ev["success"] is True  # 已产出内容,非失败


@pytest.mark.unit
async def test_stream_failover_semantics_unchanged():
    """既有契约:首 chunk 前失败切换供应商;事件同时如实记录失败尝试。"""

    async def _fail(messages, **kwargs):
        raise RuntimeError("connect timeout")
        yield  # pragma: no cover

    async def _ok(messages, **kwargs):
        yield "second provider answer"

    p1 = AsyncMock()
    p1.health_check = AsyncMock(return_value=True)
    p1.stream = _fail
    p2 = AsyncMock()
    p2.health_check = AsyncMock(return_value=True)

    def _ok_stream(messages, **kwargs):
        return _ok(messages, **kwargs)

    p2.stream = _ok_stream
    router = LLMRouter(
        providers={"p1": p1, "p2": p2},
        routing={"generation": [{"provider": "p1"}, {"provider": "p2"}]},
    )
    telemetry.start_capture()
    chunks = [c async for c in router.stream([{"role": "user", "content": "q"}])]
    assert chunks == ["second provider answer"]
    events = telemetry.current_calls()
    assert [e["success"] for e in events] == [False, True]
