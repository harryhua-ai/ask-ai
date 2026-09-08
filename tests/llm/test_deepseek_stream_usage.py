"""INC-1 — DeepSeekProvider 流式 usage 采集。

- 请求携带 ``stream_options: {include_usage: true}``;
- usage chunk(无 choices)不得进答案流,其 token 数写入遥测上下文;
- 端点不认 stream_options 返回 400 时,首 chunk 前降级重发一次。
"""

import json

import httpx
import pytest

from backend.llm import telemetry
from backend.llm.deepseek import DeepseekProvider

BASE = "https://api.deepseek.com/v1"


def _provider():
    return DeepseekProvider(
        provider_id="deepseek",
        api_base=BASE,
        api_key="fake-key",
        model="deepseek-chat",
    )


class _FakeStreamResp:
    def __init__(self, lines, status_code=200):
        self._lines = lines
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("POST", BASE + "/chat/completions")
            response = httpx.Response(status_code=self.status_code, request=request)
            raise httpx.HTTPStatusError("err", request=request, response=response)

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeStreamCM:
    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self._resp

    async def __aexit__(self, *exc):
        return False


class _FakeClient:
    """可注入的 AsyncClient 替身:记录 payload,按脚本回放 SSE 行。"""

    instances = []

    def __init__(self, script, captured):
        self._script = script  # list of (status, lines)
        self._captured = captured
        _FakeClient.instances.append(self)

    def stream(self, method, url, headers=None, json=None):
        self._captured.append(json)
        status, lines = self._script.pop(0)
        return _FakeStreamCM(_FakeStreamResp(lines, status_code=status))

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _sse(obj):
    return "data: " + json.dumps(obj)


@pytest.mark.unit
async def test_stream_requests_usage_and_records_it(monkeypatch):
    captured = []
    lines = [
        _sse({"choices": [{"delta": {"content": "你好"}}]}),
        _sse({"choices": [{"delta": {"content": "!"}}]}),
        _sse({"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 34}}),
        "data: [DONE]",
    ]

    def _factory(**kwargs):
        return _FakeClient([(_s := 200, lines)], captured)

    monkeypatch.setattr("backend.llm.deepseek.httpx.AsyncClient", _factory)
    telemetry.start_capture()
    chunks = [c async for c in _provider().stream([{"role": "user", "content": "q"}])]
    assert chunks == ["你好", "!"]  # usage chunk 不进答案流
    assert captured[0]["stream_options"] == {"include_usage": True}
    usage = telemetry.pop_stream_usage()
    assert usage == {"tokens_input": 12, "tokens_output": 34}


@pytest.mark.unit
async def test_stream_400_on_stream_options_falls_back_without(monkeypatch):
    captured = []
    ok_lines = [
        _sse({"choices": [{"delta": {"content": "ok"}}]}),
        _sse({"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": 2}}),
        "data: [DONE]",
    ]
    script = [(400, []), (200, ok_lines)]

    def _factory(**kwargs):
        return _FakeClient(script, captured)

    monkeypatch.setattr("backend.llm.deepseek.httpx.AsyncClient", _factory)
    chunks = [c async for c in _provider().stream([{"role": "user", "content": "q"}])]
    assert chunks == ["ok"]
    assert len(captured) == 2
    assert "stream_options" not in captured[1]  # 降级重发不再携带
