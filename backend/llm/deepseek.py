"""Deepseek(OpenAI 兼容协议)LLM 供应商实现。

通过 httpx 调用任何 OpenAI 兼容的 /chat/completions 端点,
支持同步生成与流式生成。
"""

import json
import logging
import time

import httpx

from backend.llm.base import LLMResponse
from backend.llm.registry import LLMRegistry

logger = logging.getLogger(__name__)


@LLMRegistry.register("openai_compatible")
class DeepseekProvider:
    """OpenAI 兼容协议供应商实现。

    通过 httpx 调用任何兼容 OpenAI /chat/completions 的端点
    (Deepseek、OpenRouter、Together、本地 vLLM 等)。
    """

    def __init__(
        self,
        provider_id: str,
        api_base: str,
        api_key: str,
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ):
        self._id = provider_id
        self._api_base = api_base.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._max_tokens = max_tokens
        self._temperature = temperature

    @property
    def provider_id(self) -> str:
        return self._id

    async def generate(self, messages: list[dict], **kwargs) -> LLMResponse:
        """调用非流式 /chat/completions 并返回 LLMResponse。"""
        start = time.monotonic()
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self._api_base}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": kwargs.get("model", self._model),
                    "messages": messages,
                    "max_tokens": kwargs.get("max_tokens", self._max_tokens),
                    "temperature": kwargs.get("temperature", self._temperature),
                    "stream": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        elapsed_ms = int((time.monotonic() - start) * 1000)
        return LLMResponse(
            content=data["choices"][0]["message"]["content"],
            model=data.get("model", self._model),
            tokens_input=data["usage"]["prompt_tokens"],
            tokens_output=data["usage"]["completion_tokens"],
            latency_ms=elapsed_ms,
        )

    async def stream(self, messages: list[dict], **kwargs):
        """调用流式 /chat/completions,逐块产出文本内容。"""
        async with (
            httpx.AsyncClient(timeout=120) as client,
            client.stream(
                "POST",
                f"{self._api_base}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={
                    "model": kwargs.get("model", self._model),
                    "messages": messages,
                    "max_tokens": kwargs.get("max_tokens", self._max_tokens),
                    "temperature": kwargs.get("temperature", self._temperature),
                    "stream": True,
                },
            ) as resp,
        ):
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    chunk = json.loads(line[6:])
                    delta = chunk["choices"][0].get("delta", {})
                    if content := delta.get("content"):
                        yield content

    async def health_check(self) -> bool:
        """仅校验 API Key 是否已配置,不发起实际请求。"""
        return bool(self._api_key)

    async def list_models(self) -> list[str]:
        """调 GET {api_base}/models 拉取可用模型 id 列表。

        供 admin "从 API 拉取"功能使用。调用方负责异常脱敏。

        Returns:
            模型 id 字符串列表(如 ["deepseek-v4-pro", "deepseek-v4-flash"])。

        Raises:
            httpx.HTTPStatusError: 非 2xx(如 key 无效 401)。
            httpx.RequestError: 网络错误。
        """
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self._api_base}/models",
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
            resp.raise_for_status()
            return [m["id"] for m in resp.json()["data"]]
