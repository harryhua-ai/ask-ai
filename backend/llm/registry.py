"""LLM 供应商注册表与路由器。

LLMRegistry 提供"类型名 -> 供应商类"的注册机制;
LLMRouter 基于任务类型按优先级链路尝试多个供应商,实现故障切换。
"""

from typing import ClassVar

from backend.llm.base import LLMProvider


class LLMRegistry:
    """供应商注册表(类级存储)。

    通过装饰器语法注册供应商类,运行期按 provider_type 名称查找并实例化。
    """

    _providers: ClassVar[dict[str, type]] = {}

    @classmethod
    def register(cls, provider_type: str):
        """注册装饰器:将供应商类绑定到指定类型名。"""

        def decorator(provider_cls):
            cls._providers[provider_type] = provider_cls
            return provider_cls

        return decorator

    @classmethod
    def create(cls, provider_type: str, **kwargs) -> LLMProvider:
        """按类型名实例化已注册的供应商。"""
        provider_cls = cls._providers[provider_type]
        return provider_cls(**kwargs)


class LLMRouter:
    """多供应商路由器。

    按任务类型选取有序供应商链路,依次尝试 health_check + generate,
    首个成功者返回结果;全部失败时抛出 RuntimeError。
    """

    def __init__(self, providers: dict[str, LLMProvider], routing: dict[str, list[str]]):
        self._providers = providers
        self._routing = routing

    def _get_chain(self, task: str) -> list[str]:
        """根据任务名返回对应供应商 ID 链路,缺省回退到 generation。"""
        return self._routing.get(task, self._routing.get("generation", []))

    async def generate(self, messages: list[dict], task: str = "generation", **kwargs):
        """按链路顺序尝试各供应商的同步生成。"""
        chain = self._get_chain(task)
        last_error = None
        for provider_id in chain:
            provider = self._providers.get(provider_id)
            if provider is None:
                continue
            try:
                if await provider.health_check():
                    return await provider.generate(messages, **kwargs)
            except Exception as e:  # noqa: BLE001 - 故障切换需捕获所有异常
                last_error = e
                continue
        raise RuntimeError(f"All LLM providers unavailable: {last_error}")

    async def stream(self, messages: list[dict], task: str = "generation", **kwargs):
        """按链路顺序尝试各供应商的流式生成。"""
        chain = self._get_chain(task)
        for provider_id in chain:
            provider = self._providers.get(provider_id)
            if provider is None:
                continue
            try:
                if await provider.health_check():
                    async for chunk in provider.stream(messages, **kwargs):
                        yield chunk
                    return
            except Exception:  # noqa: BLE001, S112 - 故障切换需捕获所有异常
                continue
        raise RuntimeError("All LLM providers unavailable")
