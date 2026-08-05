"""LLMRouter 的 reconfigure + chain 对象解析测试。"""

import pytest

from backend.llm.base import LLMProvider, LLMResponse
from backend.llm.registry import LLMRouter


class _FakeProvider(LLMProvider):
    """记录调用参数的假 provider，用于断言 model 是否透传。"""

    def __init__(self, pid: str, healthy: bool = True):
        self._id = pid
        self._healthy = healthy
        self.last_kwargs: dict | None = None

    @property
    def provider_id(self) -> str:
        return self._id

    async def generate(self, messages, **kwargs):
        self.last_kwargs = kwargs
        return LLMResponse(
            content="ok",
            model=kwargs.get("model", "default"),
            tokens_input=1,
            tokens_output=1,
            latency_ms=10,
        )

    async def stream(self, messages, **kwargs):
        self.last_kwargs = kwargs
        yield "ok"

    async def health_check(self) -> bool:
        return self._healthy


@pytest.mark.asyncio
async def test_generate_passes_model_from_chain_item():
    """chain 对象的 model 字段透传给 provider.generate。"""
    prov = _FakeProvider("deepseek")
    router = LLMRouter(
        providers={"deepseek": prov},
        routing={"generation": [{"provider": "deepseek", "model": "v4-pro"}]},
    )
    await router.generate([{"role": "user", "content": "hi"}], task="generation")
    assert prov.last_kwargs["model"] == "v4-pro"


@pytest.mark.asyncio
async def test_generate_omits_model_when_none():
    """chain item model 为 None 时不传 model(让 provider 用默认)。"""
    prov = _FakeProvider("deepseek")
    router = LLMRouter(
        providers={"deepseek": prov},
        routing={"generation": [{"provider": "deepseek", "model": None}]},
    )
    await router.generate([{"role": "user", "content": "hi"}])
    assert "model" not in prov.last_kwargs  # None → 不传


@pytest.mark.asyncio
async def test_reconfigure_swaps_providers_and_routing():
    """reconfigure 后 generate 用新 providers/routing。"""
    old = _FakeProvider("old")
    new = _FakeProvider("new")
    router = LLMRouter(
        providers={"old": old},
        routing={"generation": [{"provider": "old", "model": None}]},
    )
    router.reconfigure(
        providers={"new": new},
        routing={"generation": [{"provider": "new", "model": "v4-flash"}]},
    )
    await router.generate([{"role": "user", "content": "hi"}])
    assert old.last_kwargs is None  # 旧的没被调用
    assert new.last_kwargs["model"] == "v4-flash"


@pytest.mark.asyncio
async def test_generate_falls_back_to_generation_task():
    """未知 task 回退 generation 链(现有行为保留)。"""
    prov = _FakeProvider("deepseek")
    router = LLMRouter(
        providers={"deepseek": prov},
        routing={"generation": [{"provider": "deepseek", "model": None}]},
    )
    await router.generate([{"role": "user", "content": "hi"}], task="unknown_task")
    assert prov.last_kwargs is not None  # 回退到 generation 被调用了


@pytest.mark.asyncio
async def test_generate_all_fail_raises_with_last_error():
    """所有 provider 失败时 RuntimeError 带 last_error。"""
    prov = _FakeProvider("deepseek", healthy=False)
    router = LLMRouter(
        providers={"deepseek": prov},
        routing={"generation": [{"provider": "deepseek", "model": None}]},
    )
    with pytest.raises(RuntimeError, match="unavailable"):
        await router.generate([{"role": "user", "content": "hi"}])
