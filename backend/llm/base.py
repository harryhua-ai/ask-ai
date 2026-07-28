"""LLM 供应商抽象基类。

定义 LLMProvider Protocol 和 LLMResponse 不可变数据类。
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class LLMResponse:
    """LLM 响应(不可变)。

    封装生成内容、所用模型、token 用量与端到端延迟。
    """

    content: str
    model: str
    tokens_input: int
    tokens_output: int
    latency_ms: int


class LLMProvider(Protocol):
    """LLM 供应商协议。

    所有具体供应商必须实现该协议,以支持同步生成、流式生成与健康检查。
    """

    @property
    def provider_id(self) -> str: ...

    async def generate(self, messages: list[dict], **kwargs) -> LLMResponse: ...

    async def stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]: ...

    async def health_check(self) -> bool: ...
