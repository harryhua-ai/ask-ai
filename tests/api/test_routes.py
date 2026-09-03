"""FastAPI 路由测试。

覆盖:
- ``GET /health`` 集成测试(brief Step 4 原始用例)
- ``POST /api/ask`` 单元测试:
  - 正常流式(sources → token(s) → done)
  - 空结果拒答(仍输出 token + done)
  - 输入校验(空消息 422)
- ``POST /api/feedback`` 单元测试
- ``POST /api/click`` 单元测试
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

# --------------------------------------------------------------------------- #
# 辅助工具
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _ensure_budget_state() -> None:
    """为所有路由测试提供默认 app.state.budget(Task 21 S2 新增依赖)。

    ask 端点的 ``get_budget`` 依赖从此处读取;测试中默认给高额度避免触发熔断。
    """
    app.state.budget = BudgetLimiter(BudgetConfig(daily_request_limit=10_000, daily_token_limit=10_000_000))


def _parse_sse_events(body: str) -> list[dict[str, Any]]:
    """解析 SSE 响应体为事件列表。

    SSE 格式:每条事件由若干行 ``key: value`` 组成,事件间以空行分隔。
    仅提取 ``event`` 与 ``data`` 字段。

    Args:
        body: SSE 响应文本。

    Returns:
        事件字典列表,每项包含 ``event`` 与 ``data`` 键。
    """
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
    """构造 mock session_factory,返回 (factory, session)。

    factory 支持以 ``async with session_factory() as session`` 方式使用。
    session.add 为同步 MagicMock(对齐 AsyncSession.add 的真实签名);
    session.commit / session.execute 为 AsyncMock。
    """
    session = AsyncMock()
    # AsyncSession.add 是同步方法,覆写为 MagicMock 避免返回协程
    session.add = MagicMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory, session


def _make_streaming_rag(events: list[dict[str, Any]]) -> AsyncMock:
    """构造 mock RAGOrchestrator,其 stream_answer 产出指定事件列表。

    Args:
        events: 事件字典列表(每个字典应包含 ``type`` 键)。

    Returns:
        AsyncMock 实例,``stream_answer`` 方法返回异步生成器。
    """
    rag = AsyncMock()

    async def _fake_stream(*args, **kwargs) -> AsyncIterator[str]:
        for evt in events:
            yield json.dumps(evt)

    rag.stream_answer = _fake_stream
    return rag


# --------------------------------------------------------------------------- #
# 健康检查
# --------------------------------------------------------------------------- #


@pytest.mark.integration
async def test_health() -> None:
    """健康检查:``status`` 保持兼容;#10 扩展发布身份字段(与 authority 同源)。"""
    from backend.release import get_release_identity

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    rid = get_release_identity()
    assert body["status"] == "ok"
    assert body["version"] == rid.version
    assert body["git_sha"] == rid.git_sha
    assert body["app_mode"] == rid.app_mode


# --------------------------------------------------------------------------- #
# POST /api/ask —— 正常流式
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_ask_streams_sources_tokens_done() -> None:
    """正常流程:SSE 事件序列为 sources → token(s) → done。

    mock RAGOrchestrator 产出 sources + 2 个 token + complete 事件,
    验证 SSE 响应中包含对应数量的 sources / token / done 事件。
    """
    sources_payload = [
        {
            "url": "https://example.com/wiki",
            "title": "NE503 Wiki",
            "type": "wiki",
            "product": "ne503",
        }
    ]
    rag = _make_streaming_rag(
        [
            {"type": "sources", "sources": sources_payload},
            {"type": "token", "content": "Hello"},
            {"type": "token", "content": " world"},
            {
                "type": "complete",
                "answer": "Hello world",
                "sources": sources_payload,
                "is_answered": True,
                "language": "en",
                "response_time_ms": 42,
            },
        ]
    )
    factory, session = _make_mock_session_factory()
    app.state.rag = rag
    app.state.session_factory = factory

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/ask", json={"message": "NE503 功耗"})

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)

    event_types = [e["event"] for e in events]
    # 期望:sources, token, token, done
    assert event_types == ["sources", "token", "token", "done"]

    # sources 事件携带 conversation_id
    sources_data = json.loads(events[0]["data"])
    assert "conversation_id" in sources_data
    assert sources_data["sources"] == sources_payload
    # UUID 格式校验
    uuid.UUID(sources_data["conversation_id"])

    # token 事件内容
    assert json.loads(events[1]["data"])["content"] == "Hello"
    assert json.loads(events[2]["data"])["content"] == " world"

    # done 事件携带 conversation_id
    done_data = json.loads(events[3]["data"])
    assert done_data["conversation_id"] == sources_data["conversation_id"]

    # 验证 Postgres 写入
    session.add.assert_called_once()
    session.commit.assert_awaited_once()


@pytest.mark.unit
async def test_ask_empty_result_still_emits_token_and_done() -> None:
    """空结果(拒答)时仍输出 token + done 事件。

    RAGOrchestrator 仅产一条 complete(is_answered=False),路由应补发
    拒答文本作为 token 事件,并正常发 done 事件。
    """
    rejection = "暂未在官方资料中找到相关信息。"
    rag = _make_streaming_rag(
        [
            {
                "type": "complete",
                "answer": rejection,
                "sources": [],
                "is_answered": False,
                "language": "zh-cn",
                "response_time_ms": 5,
            }
        ]
    )
    factory, session = _make_mock_session_factory()
    app.state.rag = rag
    app.state.session_factory = factory

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/ask", json={"message": "完全不相关的问题"})

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)

    event_types = [e["event"] for e in events]
    # 空结果:无 sources,补发 1 个 token + done
    assert event_types == ["token", "done"]

    # token 内容为拒答文本
    token_data = json.loads(events[0]["data"])
    assert token_data["content"] == rejection

    # done 携带 conversation_id
    done_data = json.loads(events[1]["data"])
    assert "conversation_id" in done_data

    # Postgres 仍被写入(is_answered=False)
    session.add.assert_called_once()
    session.commit.assert_awaited_once()


@pytest.mark.unit
async def test_ask_persistence_failure_does_not_break_sse() -> None:
    """持久化(commit)失败时不应阻断 SSE 流,done 事件仍须发出。

    注入 session_factory 其 commit() 抛 RuntimeError,验证:
    - HTTP 200(不是 500)
    - SSE body 仍以 done 事件结尾
    """
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
                "response_time_ms": 1,
            },
        ]
    )
    factory, session = _make_mock_session_factory()
    session.commit.side_effect = RuntimeError("Postgres 不可用")
    app.state.rag = rag
    app.state.session_factory = factory

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/ask", json={"message": "test"})

    assert resp.status_code == 200
    events = _parse_sse_events(resp.text)
    event_types = [e["event"] for e in events]
    # 持久化失败不应影响 token / done 事件
    assert "token" in event_types
    assert event_types[-1] == "done"


# --------------------------------------------------------------------------- #
# POST /api/ask —— 输入校验
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_ask_rejects_empty_message() -> None:
    """空消息应触发 Pydantic 校验 422。"""
    rag = AsyncMock()
    factory, _ = _make_mock_session_factory()
    app.state.rag = rag
    app.state.session_factory = factory

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/ask", json={"message": ""})

    assert resp.status_code == 422
    rag.stream_answer.assert_not_called()


@pytest.mark.unit
async def test_ask_pii_masking_applied() -> None:
    """用户消息中的邮箱 / 手机号在传给 RAG 前应被脱敏。"""
    captured_query: list[str] = []

    async def _capture_stream(*args, **kwargs):
        captured_query.append(kwargs.get("query", args[0] if args else ""))
        yield json.dumps(
            {
                "type": "complete",
                "answer": "ok",
                "sources": [],
                "is_answered": True,
                "language": "en",
                "response_time_ms": 1,
            }
        )

    rag = AsyncMock()
    rag.stream_answer = _capture_stream
    factory, _ = _make_mock_session_factory()
    app.state.rag = rag
    app.state.session_factory = factory

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/ask",
            json={"message": "联系我:user@example.com 或 13812345678"},
        )

    assert resp.status_code == 200
    # 脱敏后的文本不应包含原始邮箱 / 手机号
    assert "[邮箱已脱敏]" in captured_query[0]
    assert "[电话已脱敏]" in captured_query[0]
    assert "user@example.com" not in captured_query[0]
    assert "13812345678" not in captured_query[0]


# --------------------------------------------------------------------------- #
# POST /api/feedback
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_feedback_updates_conversation() -> None:
    """feedback 端点应执行 UPDATE 并返回 ``{"status": "ok"}``。"""
    factory, session = _make_mock_session_factory()
    # execute 返回值不影响逻辑,保留默认 AsyncMock
    app.state.session_factory = factory
    # rag 不参与此端点,但 app.state.rag 必须存在以避免 Depends 报错
    app.state.rag = AsyncMock()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/feedback",
            json={"conversation_id": str(uuid.uuid4()), "feedback": "up"},
        )

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    session.execute.assert_awaited_once()
    session.commit.assert_awaited_once()


@pytest.mark.unit
async def test_feedback_rejects_invalid_value() -> None:
    """feedback 非 up/down 时应 422。"""
    app.state.session_factory = _make_mock_session_factory()[0]
    app.state.rag = AsyncMock()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/feedback",
            json={"conversation_id": str(uuid.uuid4()), "feedback": "sideways"},
        )

    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# POST /api/click
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_click_logs_source_click() -> None:
    """click 端点应插入 SourceClick 并返回 ``{"status": "ok"}``。"""
    factory, session = _make_mock_session_factory()
    app.state.session_factory = factory
    app.state.rag = AsyncMock()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/click",
            json={
                "conversation_id": str(uuid.uuid4()),
                "source_url": "https://example.com/wiki",
                "source_type": "wiki",
                "product": "ne503",
            },
        )

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    session.add.assert_called_once()
    session.commit.assert_awaited_once()


@pytest.mark.unit
async def test_click_requires_source_url_and_type() -> None:
    """缺省 source_url / source_type 时应 422。"""
    app.state.session_factory = _make_mock_session_factory()[0]
    app.state.rag = AsyncMock()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/click",
            json={"conversation_id": str(uuid.uuid4())},
        )

    assert resp.status_code == 422
