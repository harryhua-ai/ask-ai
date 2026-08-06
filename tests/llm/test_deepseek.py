"""DeepseekProvider 单元测试。

使用 monkeypatch mock httpx,避免真实网络调用。
"""

import asyncio

import pytest

from backend.llm.base import LLMResponse
from backend.llm.deepseek import DeepseekProvider
from backend.llm.registry import LLMRegistry


@pytest.mark.unit
def test_deepseek_provider_registered():
    """注册装饰器应将 openai_compatible 类型绑定到 DeepseekProvider。"""
    assert "openai_compatible" in LLMRegistry._providers


@pytest.mark.unit
def test_deepseek_generate_returns_llm_response(monkeypatch):
    """generate 应返回包含 mock 内容的 LLMResponse。"""

    provider = DeepseekProvider(
        provider_id="deepseek",
        api_base="https://api.deepseek.com/v1",
        api_key="fake-key",
        model="deepseek-chat",
    )

    async def fake_post(self, url, **kwargs):
        class FakeResponse:
            status_code = 200

            def json(self):
                return {
                    "choices": [{"message": {"content": "NE503 功耗 2.5W"}}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 10},
                }

            def elapsed(self):
                return 0.5

            def raise_for_status(self):
                """mock:模拟 httpx.Response.raise_for_status 的空实现。"""

        return FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
    result = asyncio.run(
        provider.generate(messages=[{"role": "user", "content": "test"}])
    )
    assert isinstance(result, LLMResponse)
    assert "2.5W" in result.content


# ---- list_models 测试 ----

from unittest.mock import AsyncMock, patch  # noqa: E402
import httpx  # noqa: E402


def _make_provider() -> DeepseekProvider:
    return DeepseekProvider(
        provider_id="test",
        api_base="https://api.test.com/v1",
        api_key="sk-test",
        model="m1",
    )


@pytest.mark.asyncio
async def test_list_models_returns_ids():
    """/models 返回的 data[].id 被提取为列表。"""
    payload = {"data": [{"id": "m1"}, {"id": "m2"}, {"id": "m3"}]}
    resp = httpx.Response(200, json=payload, request=httpx.Request("GET", "https://api.test.com/v1/models"))
    with patch("backend.llm.deepseek.httpx.AsyncClient") as mock_client_cls:
        client = AsyncMock()
        client.get = AsyncMock(return_value=resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = client
        result = await _make_provider().list_models()
    assert result == ["m1", "m2", "m3"]


@pytest.mark.asyncio
async def test_list_models_strips_api_base_trailing_slash():
    """api_base 末尾斜杠被 rstrip，不会变成 //models。"""
    prov = DeepseekProvider("t", api_base="https://api.test.com/v1/", api_key="k", model="m")
    payload = {"data": []}
    resp = httpx.Response(200, json=payload, request=httpx.Request("GET", "https://api.test.com/v1/models"))
    with patch("backend.llm.deepseek.httpx.AsyncClient") as mock_client_cls:
        client = AsyncMock()
        client.get = AsyncMock(return_value=resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = client
        await prov.list_models()
    # 断言请求 URL 不含双斜杠
    called_url = client.get.call_args[0][0]
    assert "//models" not in called_url
    assert called_url == "https://api.test.com/v1/models"


@pytest.mark.asyncio
async def test_list_models_raises_on_http_error():
    """非 2xx 响应抛 httpx.HTTPStatusError(由调用方捕获脱敏)。"""
    from httpx import HTTPStatusError, Request, Response

    req = Request("GET", "https://api.test.com/v1/models")
    resp = Response(401, request=req)
    with patch("backend.llm.deepseek.httpx.AsyncClient") as mock_client_cls:
        client = AsyncMock()
        client.get = AsyncMock(return_value=resp)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = client
        with pytest.raises(HTTPStatusError):
            await _make_provider().list_models()
