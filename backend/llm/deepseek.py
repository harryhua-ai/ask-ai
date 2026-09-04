"""Deepseek(OpenAI 兼容协议)LLM 供应商实现。

通过 httpx 调用任何 OpenAI 兼容的 /chat/completions 端点,
支持同步生成与流式生成。
"""

import json
import logging
import time
from collections.abc import AsyncIterator

import httpx

from backend.llm.base import LLMResponse
from backend.llm.registry import LLMRegistry

logger = logging.getLogger(__name__)


# 可重试的瞬时网络异常:连接超时/连接失败/读取超时/远端协议错误。
# 不含 HTTPStatusError(如 401 key 无效,重试无意义)。
_RETRYABLE_EXC: tuple[type[Exception], ...] = (
    httpx.ReadTimeout,
    httpx.ConnectTimeout,
    httpx.ConnectError,
    httpx.RemoteProtocolError,
    httpx.ReadError,
)


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

    def _auth_headers(self) -> dict[str, str]:
        """api_key 为空时不发 Authorization 头。

        `Bearer ` 空值头会被 httpx 拒绝(LocalProtocolError: Illegal
        header value),导致免鉴权自建网关(或未填 token 时)请求必崩。
        """
        if not self._api_key:
            return {}
        return {"Authorization": f"Bearer {self._api_key}"}

    @property
    def provider_id(self) -> str:
        return self._id

    @staticmethod
    def _apply_thinking(payload: dict, kwargs: dict) -> dict:
        """Issue #23(QW-1/QW-2):显式 ``thinking="disabled"`` 注入 provider 开关。

        Discovery 实证(生产同 base/model/key 受控实验):deepseek-v4-flash 为
        混合思考模型,``thinking: {"type": "disabled"}`` 可关且 TTFC 显著下降;
        ``enable_thinking``/``reasoning_effort`` 对本端点无效(禁用)。
        仅在调用方显式传参时注入 —— 缺省行为与基线逐字一致。
        """
        if kwargs.get("thinking") == "disabled":
            payload["thinking"] = {"type": "disabled"}
        return payload

    async def generate(self, messages: list[dict], **kwargs) -> LLMResponse:
        """调用非流式 /chat/completions 并返回 LLMResponse。

        对瞬时网络异常(ReadTimeout/ConnectTimeout/ConnectError 等)重试一次
        (最多 2 次请求)。deepseek-v4-flash 对短 prompt(如 intent 分类)偶发
        超时,单次直接抛会导致上层 fail-open,重试一次可吞掉大多数间歇性
        网络抖动。HTTPStatusError(如 401 key 无效)不重试。
        """
        start = time.monotonic()
        max_attempts = 2
        last_exc: Exception | None = None
        async with httpx.AsyncClient(timeout=90) as client:
            for attempt in range(max_attempts):
                try:
                    resp = await client.post(
                        f"{self._api_base}/chat/completions",
                        headers=self._auth_headers(),
                        json=self._apply_thinking(
                            {
                                "model": kwargs.get("model", self._model),
                                "messages": messages,
                                "max_tokens": kwargs.get("max_tokens", self._max_tokens),
                                "temperature": kwargs.get("temperature", self._temperature),
                                "stream": False,
                            },
                            kwargs,
                        ),
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
                except _RETRYABLE_EXC as exc:
                    last_exc = exc
                    if attempt < max_attempts - 1:
                        logger.warning(
                            "deepseek generate %s (attempt %d/%d), retrying",
                            type(exc).__name__,
                            attempt + 1,
                            max_attempts,
                        )
                        continue
                    raise
        # 理论不可达(async with 内 for 循环必 return 或 raise);防御性兜底
        raise last_exc  # pragma: no cover

    async def stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        """调用流式 /chat/completions,逐块产出文本内容。

        对瞬时网络异常(ReadTimeout/ConnectTimeout/ConnectError 等)重试一次。
        widget SSE 答题走本方法;deepseek 生成阶段偶发 ReadTimeout(90s+),
        单次失败会让整条 SSE 流中断,重试一次可吞掉大多数间歇性抖动。

        重试仅发生在**首个 chunk 到达前** —— 一旦开始向调用方 yield token,
        后续 ReadTimeout 立即抛出不再重试(否则会导致 SSE 重复输出)。这是
        Q32/Q50 生成中途超时的正确处理:与其重发整段请求产生重复内容,不如
        让上层降级返回已生成部分 + 友好提示。
        """
        max_attempts = 2
        last_exc: Exception | None = None
        produced = False  # 本次 attempt 是否已向调用方 yield 过 token
        for attempt in range(max_attempts):
            produced = False  # 每次尝试重置:只看"本次是否已产出"
            try:
                async with (
                    httpx.AsyncClient(timeout=120) as client,
                    client.stream(
                        "POST",
                        f"{self._api_base}/chat/completions",
                        headers=self._auth_headers(),
                        json=self._apply_thinking(
                            {
                                "model": kwargs.get("model", self._model),
                                "messages": messages,
                                "max_tokens": kwargs.get("max_tokens", self._max_tokens),
                                "temperature": kwargs.get("temperature", self._temperature),
                                "stream": True,
                            },
                            kwargs,
                        ),
                    ) as resp,
                ):
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if line.startswith("data: ") and line != "data: [DONE]":
                            chunk = json.loads(line[6:])
                            delta = chunk["choices"][0].get("delta", {})
                            if content := delta.get("content"):
                                produced = True
                                yield content
                return
            except _RETRYABLE_EXC as exc:
                # 已产出 token 后的 ReadTimeout:重试会重复输出,直接抛
                # (Q32/Q50 生成中途超时走这里,由上层 SSE 降级处理)
                if produced:
                    raise
                last_exc = exc
                if attempt < max_attempts - 1:
                    logger.warning(
                        "deepseek stream %s (attempt %d/%d), retrying",
                        type(exc).__name__,
                        attempt + 1,
                        max_attempts,
                    )
                    continue
                raise
        if last_exc:
            raise last_exc  # pragma: no cover

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
                headers=self._auth_headers(),
            )
            resp.raise_for_status()
            data = resp.json().get("data") or []
            return [m["id"] for m in data if isinstance(m, dict) and "id" in m]
