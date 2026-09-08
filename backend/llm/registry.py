"""LLM 供应商注册表与路由器。

LLMRegistry 提供"类型名 -> 供应商类"的注册机制;
LLMRouter 基于任务类型按优先级链路尝试多个供应商,实现故障切换。
"""

import time
from typing import ClassVar

from backend.llm import telemetry
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

    按任务类型选取有序供应商链路，依次尝试 health_check + generate，
    首个成功者返回结果；全部失败时抛出 RuntimeError。

    chain 元素为 {"provider": str, "model": str | None} 对象：
    - provider: 供应商 id
    - model: 该任务使用的 model，None = 用 provider 默认 model

    通过 reconfigure() 整体替换内部 providers/routing 字典，
    使启动时锁住 router 引用的组件(RAG/Pruner)也能看到新配置。
    """

    def __init__(self, providers: dict[str, LLMProvider], routing: dict[str, list[dict]]):
        self._providers = providers
        self._routing = routing

    def reconfigure(
        self, providers: dict[str, LLMProvider], routing: dict[str, list[dict]]
    ) -> None:
        """整体替换 providers/routing(整 dict 引用替换，不改旧 dict 内容)。

        每次内部读 self._providers.get() 原子无损坏；异步单线程下，
        reconfigure 落在两次迭代 await 间隙时，单次 generate 可能跨
        新旧 providers 快照(无数据损坏，仅 provider 可能中途变化)，
        窗口极短，风险可忽略。
        """
        self._providers = providers
        self._routing = routing

    def _get_chain(self, task: str) -> list[dict]:
        """根据任务名返回对应链路，缺省回退到 generation。"""
        return self._get_chain_with_fallback(task)[0]

    def _get_chain_with_fallback(self, task: str) -> tuple[list[dict], bool]:
        """返回 (链路, 是否动用了 generation 回退链)。

        INC-1 可观测:任务未配置专属链路(或配置为空)而落到 generation 链时,
        调用事件需标记 ``generation_chain_fallback=True``。task 本身就是
        generation 时不视为回退。
        """
        chain = self._routing.get(task)
        if chain:
            return chain, False
        return self._routing.get("generation", []), task != "generation"

    @staticmethod
    def _scalar(value: object) -> object:
        """事件字段归一为 JSON 标量(防御测试替身/异常对象混入)。"""
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return str(value)

    def describe_chain(self, task: str = "generation") -> dict:
        """返回任务链路首选项的静态描述(Issue #23 最小遥测;不发请求)。"""
        chain = self._get_chain(task)
        item = chain[0] if chain else {}
        return {"provider": item.get("provider"), "model": item.get("model")}

    async def generate(self, messages: list[dict], task: str = "generation", **kwargs):
        """按链路顺序尝试各供应商的同步生成。

        INC-1 可观测:每次尝试向请求级采集器追加结构化事件
        (task/provider/model/回退/latency/tokens/thinking/success),
        仅元数据,不含 prompt 与响应内容。
        """
        chain, fallback = self._get_chain_with_fallback(task)
        last_error = None
        attempts = 0
        t0 = time.perf_counter()
        for item in chain:
            pid, model = item["provider"], item.get("model")
            provider = self._providers.get(pid)
            if provider is None:
                continue
            attempts += 1
            try:
                if await provider.health_check():
                    call_kwargs = {**kwargs, "model": model} if model else kwargs
                    resp = await provider.generate(messages, **call_kwargs)
                    telemetry.record_call(
                        {
                            "task": task,
                            "provider": pid,
                            "model": self._scalar(model or getattr(resp, "model", None)),
                            "generation_chain_fallback": fallback,
                            "attempt": attempts,
                            "latency_ms": int((time.perf_counter() - t0) * 1000),
                            "tokens_input": self._scalar(getattr(resp, "tokens_input", None)),
                            "tokens_output": self._scalar(getattr(resp, "tokens_output", None)),
                            "thinking": self._scalar(kwargs.get("thinking", "provider-default")),
                            "success": True,
                        }
                    )
                    return resp
            except Exception as e:  # noqa: BLE001 - 故障切换需捕获所有异常
                last_error = e
                telemetry.record_call(
                    {
                        "task": task,
                        "provider": pid,
                        "model": self._scalar(model or getattr(provider, "default_model", None)),
                        "generation_chain_fallback": fallback,
                        "attempt": attempts,
                        "latency_ms": int((time.perf_counter() - t0) * 1000),
                        "thinking": self._scalar(kwargs.get("thinking", "provider-default")),
                        "success": False,
                        "error": type(e).__name__,
                    }
                )
                continue
        telemetry.record_call(
            {
                "task": task,
                "provider": None,
                "model": None,
                "generation_chain_fallback": fallback,
                "attempt": attempts,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "thinking": self._scalar(kwargs.get("thinking", "provider-default")),
                "success": False,
                "error": type(last_error).__name__ if last_error else "no_provider",
            }
        )
        raise RuntimeError(f"All LLM providers unavailable for task={task}: {last_error}")

    async def stream(self, messages: list[dict], task: str = "generation", **kwargs):
        """按链路顺序尝试各供应商的流式生成。

        与供应商层的 produced 守卫语义一致:仅允许在**首个 chunk 产出前**
        切换下一供应商;已向调用方产出 token 后再失败必须立即抛出 ——
        此时切换供应商会从头重放整段答案,导致 SSE 已发出内容重复。

        INC-1 可观测:流结束时(正常/异常/中断)向请求级采集器追加一次事件;
        provider 流式 usage(若有)经 :mod:`backend.llm.telemetry` 上下文
        回填进事件,仍不含任何内容性数据。
        """
        chain, fallback = self._get_chain_with_fallback(task)
        last_error = None
        attempts = 0
        t0 = time.perf_counter()
        for item in chain:
            pid, model = item["provider"], item.get("model")
            provider = self._providers.get(pid)
            if provider is None:
                continue
            produced = False  # 本次尝试是否已向调用方 yield 过 chunk
            attempts += 1
            finished = False
            try:
                if await provider.health_check():
                    call_kwargs = {**kwargs, "model": model} if model else kwargs
                    async for chunk in provider.stream(messages, **call_kwargs):
                        produced = True
                        yield chunk
                    finished = True
                    usage = telemetry.pop_stream_usage() or {}
                    telemetry.record_call(
                        {
                            "task": task,
                            "provider": pid,
                            "model": self._scalar(
                                model or getattr(provider, "default_model", None)
                            ),
                            "generation_chain_fallback": fallback,
                            "attempt": attempts,
                            "latency_ms": int((time.perf_counter() - t0) * 1000),
                            "tokens_input": self._scalar(usage.get("tokens_input")),
                            "tokens_output": self._scalar(usage.get("tokens_output")),
                            "thinking": self._scalar(kwargs.get("thinking", "provider-default")),
                            "success": True,
                            "complete": True,
                        }
                    )
                    return
            except GeneratorExit:
                # 调用方中断消费(客户端断开):如实记录 complete=False 后放行
                telemetry.record_call(
                    {
                        "task": task,
                        "provider": pid,
                        "model": self._scalar(model or getattr(provider, "default_model", None)),
                        "generation_chain_fallback": fallback,
                        "attempt": attempts,
                        "latency_ms": int((time.perf_counter() - t0) * 1000),
                        "thinking": self._scalar(kwargs.get("thinking", "provider-default")),
                        "success": produced,
                        "complete": False,
                    }
                )
                raise
            except Exception as e:  # noqa: BLE001, S112 - 故障切换需捕获所有异常
                telemetry.record_call(
                    {
                        "task": task,
                        "provider": pid,
                        "model": self._scalar(model or getattr(provider, "default_model", None)),
                        "generation_chain_fallback": fallback,
                        "attempt": attempts,
                        "latency_ms": int((time.perf_counter() - t0) * 1000),
                        "thinking": self._scalar(kwargs.get("thinking", "provider-default")),
                        "success": False,
                        "complete": False,
                        "error": type(e).__name__,
                    }
                )
                if produced:
                    raise
                last_error = e
                continue
        telemetry.record_call(
            {
                "task": task,
                "provider": None,
                "model": None,
                "generation_chain_fallback": fallback,
                "attempt": attempts,
                "latency_ms": int((time.perf_counter() - t0) * 1000),
                "thinking": self._scalar(kwargs.get("thinking", "provider-default")),
                "success": False,
                "complete": False,
                "error": type(last_error).__name__ if last_error else "no_provider",
            }
        )
        raise RuntimeError(f"All LLM providers unavailable for task={task}: {last_error}")
