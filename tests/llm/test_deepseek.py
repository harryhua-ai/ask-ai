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

from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402
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


# ---- generate 重试测试(B1: ReadTimeout 重试一次)----

@pytest.mark.asyncio
async def test_generate_retries_once_on_read_timeout():
    """generate 遇 ReadTimeout 应重试一次;第二次成功则返回 LLMResponse。

    场景:deepseek-v4-flash 对 intent 请求偶发超时,单次 timeout=60s 直接抛
    导致 intent 识别 45% fail-open。加一次重试把间歇性超时吞掉。
    """
    import httpx

    provider = DeepseekProvider(
        provider_id="deepseek",
        api_base="https://api.deepseek.com/v1",
        api_key="fake-key",
        model="deepseek-v4-flash",
    )

    call_count = {"n": 0}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [{"message": {"content": "support"}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 5},
                "model": "deepseek-v4-flash",
            }

        def raise_for_status(self):
            pass

    async def fake_post(url, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise httpx.ReadTimeout("simulated read timeout", request=httpx.Request("POST", url))
        return FakeResponse()

    with patch("backend.llm.deepseek.httpx.AsyncClient") as mock_client_cls:
        client = AsyncMock()
        client.post = AsyncMock(side_effect=fake_post)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = client
        result = await provider.generate(messages=[{"role": "user", "content": "test"}])

    assert call_count["n"] == 2, f"应重试一次(共 2 次调用),实际 {call_count['n']}"
    assert isinstance(result, LLMResponse)
    assert result.content == "support"


@pytest.mark.asyncio
async def test_generate_raises_after_retry_exhausted():
    """两次都 ReadTimeout 则抛 ReadTimeout(不无限重试)。"""
    import httpx

    provider = DeepseekProvider(
        provider_id="deepseek",
        api_base="https://api.deepseek.com/v1",
        api_key="fake-key",
        model="deepseek-v4-flash",
    )

    async def fake_post(url, **kwargs):
        raise httpx.ReadTimeout("persistent timeout", request=httpx.Request("POST", url))

    with patch("backend.llm.deepseek.httpx.AsyncClient") as mock_client_cls:
        client = AsyncMock()
        client.post = AsyncMock(side_effect=fake_post)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = client
        with pytest.raises(httpx.ReadTimeout):
            await provider.generate(messages=[{"role": "user", "content": "test"}])


# ---- generate 重试覆盖 ConnectTimeout/ConnectError(B2: P0 修复)----


@pytest.mark.asyncio
async def test_generate_retries_on_connect_timeout():
    """generate 遇 ConnectTimeout 也应重试一次。

    场景:生产评估 Q22/Q48/Q61 在 10s 快速失败(ConnectTimeoutError),
    当前只重试 ReadTimeout,ConnectTimeout 直接抛导致 fail-open。
    """
    import httpx

    provider = DeepseekProvider(
        provider_id="deepseek",
        api_base="https://api.deepseek.com/v1",
        api_key="fake-key",
        model="deepseek-v4-flash",
    )

    call_count = {"n": 0}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [{"message": {"content": "product"}}],
                "usage": {"prompt_tokens": 50, "completion_tokens": 5},
                "model": "deepseek-v4-flash",
            }

        def raise_for_status(self):
            pass

    async def fake_post(url, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise httpx.ConnectTimeout(
                "simulated connect timeout", request=httpx.Request("POST", url)
            )
        return FakeResponse()

    with patch("backend.llm.deepseek.httpx.AsyncClient") as mock_client_cls:
        client = AsyncMock()
        client.post = AsyncMock(side_effect=fake_post)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = client
        result = await provider.generate(messages=[{"role": "user", "content": "test"}])

    assert call_count["n"] == 2, f"ConnectTimeout 应触发重试(共 2 次),实际 {call_count['n']}"
    assert result.content == "product"


@pytest.mark.asyncio
async def test_generate_retries_on_connect_error():
    """generate 遇 ConnectError(连接被拒/DNS 失败)也应重试一次。"""
    import httpx

    provider = DeepseekProvider(
        provider_id="deepseek",
        api_base="https://api.deepseek.com/v1",
        api_key="fake-key",
        model="deepseek-v4-flash",
    )

    call_count = {"n": 0}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 1},
                "model": "deepseek-v4-flash",
            }

        def raise_for_status(self):
            pass

    async def fake_post(url, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise httpx.ConnectError(
                "simulated connect error", request=httpx.Request("POST", url)
            )
        return FakeResponse()

    with patch("backend.llm.deepseek.httpx.AsyncClient") as mock_client_cls:
        client = AsyncMock()
        client.post = AsyncMock(side_effect=fake_post)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = client
        result = await provider.generate(messages=[{"role": "user", "content": "test"}])

    assert call_count["n"] == 2


# ---- stream 重试测试(B2: P0 修复,Q32/Q50 读取超时)----


@pytest.mark.asyncio
async def test_stream_retries_on_read_timeout():
    """stream 遇 ReadTimeout 应重试一次。

    场景:widget SSE 答题走 stream,Q32/Q50 生成超时(90s+),
    当前 stream 完全无重试,一次超时直接失败。
    """

    import httpx

    provider = DeepseekProvider(
        provider_id="deepseek",
        api_base="https://api.deepseek.com/v1",
        api_key="fake-key",
        model="deepseek-v4-flash",
    )

    call_count = {"n": 0}

    class FakeStreamResp:
        status_code = 200

        def raise_for_status(self):
            pass

        async def aiter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"hello"}}]}'
            yield "data: [DONE]"

    class FakeStreamCM:
        """模拟 httpx 的 stream() 返回的 async context manager。

        生产代码用 `async with client.stream(...) as resp:`,
        client.stream(...) 需返回一个 async context manager,
        其 __aenter__ 返回 response 对象。
        """

        def __init__(self, resp):
            self._resp = resp

        async def __aenter__(self):
            return self._resp

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def fake_stream(method, url, **kwargs):
        # httpx 的 client.stream() 是同步方法,返回 async context manager
        # (不是 async 方法)。用普通函数返回 FakeStreamCM,避免 AsyncMock 把
        # 返回值包成 coroutine。
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise httpx.ReadTimeout(
                "simulated stream timeout", request=httpx.Request("POST", url)
            )
        return FakeStreamCM(FakeStreamResp())

    with patch("backend.llm.deepseek.httpx.AsyncClient") as mock_client_cls:
        client = AsyncMock()
        client.stream = MagicMock(side_effect=fake_stream)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = client
        chunks = []
        async for chunk in provider.stream(messages=[{"role": "user", "content": "test"}]):
            chunks.append(chunk)

    assert call_count["n"] == 2, f"stream ReadTimeout 应重试,实际 {call_count['n']}"
    assert chunks == ["hello"]


@pytest.mark.asyncio
async def test_stream_no_retry_after_first_chunk():
    """已产出首个 token 后的 ReadTimeout 不应重试(防止 SSE 重复输出)。

    场景:Q32/Q50 生成中途超时 —— deepseek 已经开始 yield token,
    此时若重试会重新生成整段内容,导致 widget SSE 重复输出。
    正确行为:首个 chunk 到达后的 ReadTimeout 直接抛,由上层降级
    返回已生成部分 + 友好提示,而非重发请求。
    """

    import httpx

    provider = DeepseekProvider(
        provider_id="deepseek",
        api_base="https://api.deepseek.com/v1",
        api_key="fake-key",
        model="deepseek-v4-flash",
    )

    call_count = {"n": 0}

    class FakeStreamResp:
        status_code = 200

        def raise_for_status(self):
            pass

        async def aiter_lines(self):
            # 先产出一个 chunk,再在中途抛 ReadTimeout
            yield 'data: {"choices":[{"delta":{"content":"hello"}}]}'
            raise httpx.ReadTimeout(
                "mid-stream timeout", request=httpx.Request("POST", "https://api.deepseek.com/v1")
            )

    class FakeStreamCM:
        def __init__(self, resp):
            self._resp = resp

        async def __aenter__(self):
            return self._resp

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def fake_stream(method, url, **kwargs):
        call_count["n"] += 1
        return FakeStreamCM(FakeStreamResp())

    with patch("backend.llm.deepseek.httpx.AsyncClient") as mock_client_cls:
        client = AsyncMock()
        client.stream = MagicMock(side_effect=fake_stream)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = client
        chunks = []
        with pytest.raises(httpx.ReadTimeout):
            async for chunk in provider.stream(messages=[{"role": "user", "content": "test"}]):
                chunks.append(chunk)

    # 关键断言:已产出 token 后的超时只调用一次,不重试(否则重复输出)
    assert call_count["n"] == 1, f"已产出后不应重试,实际调用 {call_count['n']} 次"
    # 已产出的 token 仍应被调用方收到
    assert chunks == ["hello"]
