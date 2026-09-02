"""P1 生成可靠性 — /api/ask SSE 失败路径金样回归。

冻结产品契约(CAMTHINK V1 Launch Closure G1):
- PC-01: 零内容完成禁止伪装成功(禁止 sources → done 无 answer/error)。
- PC-02: 失败必须成为用户可见、可恢复的状态(既有文案「服务暂时不可用,请稍后再试。」)。
- PC-03: 流中途失败不得静默伪装为正常完成。
- PC-04: 拒答(off_topic / 证据不足 / 预算熔断)是有意的可见结果,不是生成失败。
- PC-06: 持久化须可区分 正常成功 / 拒答 / 生成失败,不因 UI 显示了文本就一律记成功。

金样场景:
- REL-G001 零 token 正常结束 → 显式可恢复失败,绝不静默空白 + done
- REL-G002 首 token 前供应商异常 → 显式失败
- REL-G003 部分 token 后异常 → 非普通成功(部分内容保留,无重复兜底 token)
- REL-G004 正常流式语义不变(精确事件序列在 test_routes.py 已锚定)
- REL-G005 拒答与预算熔断保持既有可见结果,不转通用错误
"""

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app
from backend.utils.budget import BudgetConfig, BudgetLimiter

SERVICE_UNAVAILABLE = "服务暂时不可用,请稍后再试。"


@pytest.fixture(autouse=True)
def _ensure_budget_state() -> None:
    """默认高额度预算,避免触发熔断(熔断专项测试内自行注入低额度)。"""
    app.state.budget = BudgetLimiter(
        BudgetConfig(daily_request_limit=10_000, daily_token_limit=10_000_000)
    )


def _parse_sse_events(body: str) -> list[dict[str, Any]]:
    """解析 SSE 响应体为事件列表(与 test_routes.py 同协议)。"""
    events: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    for raw_line in body.split("\n"):
        line = raw_line.rstrip("\r")
        if line == "":
            if current:
                events.append(current)
                current = {}
            continue
        if line.startswith("event:"):
            current["event"] = line[len("event:") :].strip()
        elif line.startswith("data:"):
            current["data"] = line[len("data:") :].strip()
    if current:
        events.append(current)
    return events


def _make_mock_session_factory() -> tuple[MagicMock, AsyncMock]:
    """构造 mock session_factory:(factory, session),session.add 为同步 MagicMock。"""
    session = AsyncMock()
    session.add = MagicMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory, session


def _make_streaming_rag(
    events: list[dict[str, Any]] | None = None,
    *,
    exc: Exception | None = None,
    exc_after_events: bool = False,
) -> AsyncMock:
    """构造 mock RAGOrchestrator。

    - events: 依次 yield 的内部 JSON 事件;
    - exc: 流中抛出的异常;exc_after_events=True 时先发完 events 再抛。
    """
    rag = AsyncMock()

    async def _fake_stream(*args, **kwargs) -> AsyncIterator[str]:
        for evt in events or []:
            yield json.dumps(evt)
        if exc is not None:
            raise exc

    rag.stream_answer = _fake_stream
    return rag


def _persisted_objects(session: AsyncMock) -> list[Any]:
    """提取 session.add 收到的全部持久化对象。"""
    return [call.args[0] for call in session.add.call_args_list]


def _ask_request(rag: Any, factory: MagicMock) -> AsyncClient:
    """装配 app.state 并返回指向 app 的 AsyncClient 上下文管理器。"""
    app.state.rag = rag
    app.state.session_factory = factory
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# --------------------------------------------------------------------------- #
# REL-G001 — 零 token 正常结束:不得静默成功
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_rel_g001_zero_token_completion_cannot_silently_succeed() -> None:
    """PC-01/AC-01:流正常结束但零可用内容 → 兜底 token + error 事件 + done。

    复现验收基线 A05/E04-t2 签名:supplier 返回 200、流正常关闭、零内容 chunk。
    旧实现此路径输出 sources → done,用户看到空白且系统记成功。
    """
    rag = _make_streaming_rag(
        [
            {"type": "sources", "sources": []},
            {
                "type": "complete",
                "answer": "",
                "sources": [],
                "is_answered": True,  # 旧实现:零内容也标成功
                "language": "en",
                "response_time_ms": 47_500,
            },
        ]
    )
    factory, session = _make_mock_session_factory()

    async with _ask_request(rag, factory) as client:
        resp = await client.post("/api/ask", json={"message": "NE503 有哪些接口?"})

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    event_types = [e["event"] for e in events]

    # 绝不允许 sources → done 无 answer/error 的静默空白
    assert event_types == ["sources", "token", "error", "done"]

    # 用户看到显式可恢复的失败文案(PC-02)
    fallback_token = json.loads(events[1]["data"])
    assert fallback_token["content"] == SERVICE_UNAVAILABLE

    # error 事件:结构化失败信号(旧客户端忽略不崩,新客户端可高亮)
    error_data = json.loads(events[2]["data"])
    assert error_data["kind"] == "empty_generation"
    assert error_data["message"] == SERVICE_UNAVAILABLE

    # done 恰好一次,conversation_id 与 sources 一致(AC-04)
    sources_data = json.loads(events[0]["data"])
    done_data = json.loads(events[3]["data"])
    assert done_data["conversation_id"] == sources_data["conversation_id"]
    assert event_types.count("done") == 1

    # 持久化反映现实(AC-06):is_answered 强制 False,不记成功
    persisted = _persisted_objects(session)
    conv = persisted[0]
    assert conv.is_answered is False
    assert conv.answer == SERVICE_UNAVAILABLE

    # trace 区分生成失败与拒答(PC-06):type=generation_error
    traces = [p for p in persisted if type(p).__name__ == "Trace"]
    assert len(traces) == 1
    assert traces[0].type == "generation_error"


# --------------------------------------------------------------------------- #
# REL-G002 — 首 token 前供应商异常:显式失败
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_rel_g002_provider_error_before_first_token_visible() -> None:
    """PC-02/AC-02:生成开始前异常 → 兜底 token + error 事件,无静默空白。"""
    rag = _make_streaming_rag(exc=RuntimeError("All LLM providers unavailable"))
    factory, session = _make_mock_session_factory()

    async with _ask_request(rag, factory) as client:
        resp = await client.post("/api/ask", json={"message": "NE101 蜂窝注册失败"})

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    event_types = [e["event"] for e in events]
    assert event_types == ["token", "error", "done"]

    assert json.loads(events[0]["data"])["content"] == SERVICE_UNAVAILABLE
    error_data = json.loads(events[1]["data"])
    assert error_data["kind"] == "provider_error"
    # 异常细节不得泄漏给客户端,只给固定文案
    assert "providers unavailable" not in resp.text

    persisted = _persisted_objects(session)
    conv = persisted[0]
    assert conv.is_answered is False
    traces = [p for p in persisted if type(p).__name__ == "Trace"]
    assert len(traces) == 1
    assert traces[0].type == "generation_error"


# --------------------------------------------------------------------------- #
# REL-G003 — 部分 token 后异常:非普通成功
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_rel_g003_error_after_partial_tokens_not_ordinary_success() -> None:
    """PC-03/AC-03:部分内容后流中断 → 保留部分内容 + error 事件,无重复兜底。

    中断的答案不得与正常完成不可区分:必须携带结构化 error 信号,
    且不得重复补发兜底 token(NA-04)。
    """
    rag = _make_streaming_rag(
        [{"type": "token", "content": "请先检查电源供电:"}],
        exc=httpx_timeout_like(),
        exc_after_events=True,
    )
    factory, session = _make_mock_session_factory()

    async with _ask_request(rag, factory) as client:
        resp = await client.post("/api/ask", json={"message": "NE101 无法开机"})

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    event_types = [e["event"] for e in events]

    # 部分 token 原样保留;中断信号独立;不以普通 done 收尾伪装成功
    assert event_types == ["token", "error", "done"]
    assert json.loads(events[0]["data"])["content"] == "请先检查电源供电:"

    error_data = json.loads(events[1]["data"])
    assert error_data["kind"] == "stream_interrupted"
    assert error_data["message"] == SERVICE_UNAVAILABLE

    # 恰好 1 个 token:无重复兜底文本(NA-04)
    assert event_types.count("token") == 1

    persisted = _persisted_objects(session)
    conv = persisted[0]
    assert conv.is_answered is False  # 中断不记成功(NA-05)
    assert conv.answer == "请先检查电源供电:"  # 部分内容如实落库
    traces = [p for p in persisted if type(p).__name__ == "Trace"]
    assert len(traces) == 1
    assert traces[0].type == "generation_error"


def httpx_timeout_like() -> Exception:
    """模拟 deepseek.stream 产出部分 token 后的 ReadTimeout(Q32/Q50 路径)。"""
    import httpx

    return httpx.ReadTimeout("timed out")


# --------------------------------------------------------------------------- #
# REL-G005 — 拒答 / 预算熔断:有意可见结果,不转通用错误
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_rel_g005_intentional_refusal_stays_refusal() -> None:
    """PC-04/AC-05:证据不足拒答 → 补发拒答文本 token,不产生 error 事件。"""
    refusal = "暂未在官方资料中找到相关信息。"
    rag = _make_streaming_rag(
        [
            {
                "type": "complete",
                "answer": refusal,
                "sources": [],
                "is_answered": False,
                "language": "zh-cn",
                "response_time_ms": 5,
            }
        ]
    )
    factory, session = _make_mock_session_factory()

    async with _ask_request(rag, factory) as client:
        resp = await client.post("/api/ask", json={"message": "今天天气怎么样"})

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    event_types = [e["event"] for e in events]
    assert event_types == ["token", "done"]  # 无 error 事件
    assert json.loads(events[0]["data"])["content"] == refusal

    persisted = _persisted_objects(session)
    conv = persisted[0]
    assert conv.is_answered is False
    # 拒答不写 generation_error trace(拒答有自己的 reject_short trace_payload)
    traces = [p for p in persisted if type(p).__name__ == "Trace"]
    assert all(t.type != "generation_error" for t in traces)


@pytest.mark.unit
async def test_rel_g005_budget_decline_stays_declined() -> None:
    """PC-04/AC-05:预算熔断 → declined + done 既有形状不变,无 error 事件。"""
    app.state.budget = BudgetLimiter(BudgetConfig(daily_request_limit=0, daily_token_limit=0))
    rag = _make_streaming_rag()
    factory, _ = _make_mock_session_factory()

    async with _ask_request(rag, factory) as client:
        resp = await client.post("/api/ask", json={"message": "NE503 参数"})

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    event_types = [e["event"] for e in events]
    assert event_types == ["declined", "done"]
    declined_data = json.loads(events[0]["data"])
    assert "reason" in declined_data
    # 熔断路径不触碰 RAG
    json.loads(events[1]["data"])["conversation_id"]
    uuid.UUID(json.loads(events[1]["data"])["conversation_id"])


# --------------------------------------------------------------------------- #
# 边界:空白 token + 零内容兜底不重复
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_whitespace_only_stream_treated_as_empty_generation() -> None:
    """仅空白内容(如全空格 delta)等价零可用内容 → 走 empty_generation 兜底。"""
    rag = _make_streaming_rag(
        [
            {"type": "token", "content": "   "},
            {
                "type": "complete",
                "answer": "   ",
                "sources": [],
                "is_answered": True,
                "language": "en",
                "response_time_ms": 10,
            },
        ]
    )
    factory, session = _make_mock_session_factory()

    async with _ask_request(rag, factory) as client:
        resp = await client.post("/api/ask", json={"message": "test"})

    events = _parse_sse_events(resp.text)
    event_types = [e["event"] for e in events]
    # 空白 token 已发出,追加兜底 token + error;不得只发 done 伪装成功
    assert event_types == ["token", "token", "error", "done"]
    assert json.loads(events[1]["data"])["content"] == SERVICE_UNAVAILABLE
    assert json.loads(events[2]["data"])["kind"] == "empty_generation"

    persisted = _persisted_objects(session)
    assert persisted[0].is_answered is False


@pytest.mark.unit
async def test_normal_stream_emits_no_error_event() -> None:
    """AC-04 守护:正常完成不得引入 error 事件或重复 done(与旧语义逐字节兼容)。"""
    rag = _make_streaming_rag(
        [
            {"type": "sources", "sources": []},
            {"type": "token", "content": "Hello"},
            {
                "type": "complete",
                "answer": "Hello",
                "sources": [],
                "is_answered": True,
                "language": "en",
                "response_time_ms": 42,
            },
        ]
    )
    factory, session = _make_mock_session_factory()

    async with _ask_request(rag, factory) as client:
        resp = await client.post("/api/ask", json={"message": "test"})

    events = _parse_sse_events(resp.text)
    assert [e["event"] for e in events] == ["sources", "token", "done"]
    persisted = _persisted_objects(session)
    assert persisted[0].is_answered is True
