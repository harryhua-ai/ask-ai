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
    result = asyncio.get_event_loop().run_until_complete(
        provider.generate(messages=[{"role": "user", "content": "test"}])
    )
    assert isinstance(result, LLMResponse)
    assert "2.5W" in result.content
