"""admin 内嵌聊天 channel 数据边界测试。

回归背景(2026-08-28 交接):admin 内嵌聊天复用 widget App 组件,
历史上一律传 channel="widget",管理员测试对话与真实访客对话混在同一
数据池,污染 T1 上线后的意图分布北极星裁决。

本文件锁定:
1. AskRequest schema 接受独立渠道值 ``admin``(白名单内);
2. POST /api/ask 携带 channel="admin" 时,落库 Conversation.channel="admin";
3. admin 与 widget 对话落库后 channel 值互不混淆(可区分)。
"""

import json
import uuid
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from backend.api.schemas import AskRequest
from backend.db.models import Conversation
from backend.main import app
from backend.utils.budget import BudgetConfig, BudgetLimiter

# --------------------------------------------------------------------------- #
# 辅助工具(与 test_routes.py 同风格的最小本地实现,保持用例自包含)
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _ensure_budget_state() -> None:
    """给 ask 端点提供高额度预算熔断器,避免测试触发限流。"""
    app.state.budget = BudgetLimiter(
        BudgetConfig(daily_request_limit=10_000, daily_token_limit=10_000_000)
    )


def _make_mock_session_factory() -> tuple[MagicMock, AsyncMock]:
    """构造 mock session_factory,返回 (factory, session)。

    session.add 为同步 MagicMock(对齐 AsyncSession.add 真实签名)。
    """
    session = AsyncMock()
    session.add = MagicMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory, session


def _make_streaming_rag(events: list[dict]) -> AsyncMock:
    """构造 mock RAGOrchestrator,stream_answer 产出指定事件列表。"""
    rag = AsyncMock()

    async def _fake_stream(*args, **kwargs) -> AsyncIterator[str]:
        for evt in events:
            yield json.dumps(evt)

    rag.stream_answer = _fake_stream
    return rag


# --------------------------------------------------------------------------- #
# 1. schema 白名单接受 admin
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_ask_request_accepts_admin_channel() -> None:
    """channel="admin" 应通过 AskRequest 白名单校验(独立渠道值)。"""
    req = AskRequest(message="测试问题", channel="admin")
    assert req.channel == "admin"


# --------------------------------------------------------------------------- #
# 2. /api/ask 携带 channel=admin 时落库携带该值
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_ask_admin_channel_persisted() -> None:
    """POST /api/ask channel="admin" → 落库 Conversation.channel == "admin"。

    数据边界核心断言:管理员在 admin 内嵌聊天的测试对话必须能从
    真实访客(widget)对话中剥离,避免北极星意图分布失真。
    """
    rag = _make_streaming_rag(
        [
            {"type": "token", "content": "回答"},
            {
                "type": "complete",
                "answer": "回答",
                "sources": [],
                "is_answered": True,
                "language": "zh",
                "response_time_ms": 10,
            },
        ]
    )
    factory, session = _make_mock_session_factory()
    app.state.rag = rag
    app.state.session_factory = factory

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/ask", json={"message": "测试问题", "channel": "admin"})

    assert resp.status_code == 200
    session.add.assert_called_once()
    conv = session.add.call_args.args[0]
    assert isinstance(conv, Conversation)
    assert conv.channel == "admin"


# --------------------------------------------------------------------------- #
# 3. admin 与 widget 对话落库互不混淆(锁定行为)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_admin_and_widget_conversations_distinguishable(db_session) -> None:
    """两种渠道各落一条对话,channel 值各自保真、互不覆盖。

    生产侧经 idx_conversations_channel 索引支持按渠道过滤;
    此处用主键取回验证两行数据边界(测试库不构造额外查询语句)。
    """
    admin_id = uuid.uuid4()
    widget_id = uuid.uuid4()
    db_session.add(
        Conversation(
            id=admin_id,
            question="管理员测试",
            answer="答",
            channel="admin",
            language="zh",
            sources=[],
            is_answered=True,
        )
    )
    db_session.add(
        Conversation(
            id=widget_id,
            question="访客提问",
            answer="答",
            channel="widget",
            language="zh",
            sources=[],
            is_answered=True,
        )
    )
    await db_session.commit()

    admin_row = await db_session.get(Conversation, admin_id)
    widget_row = await db_session.get(Conversation, widget_id)

    assert admin_row.channel == "admin"
    assert admin_row.question == "管理员测试"
    assert widget_row.channel == "widget"
    assert widget_row.question == "访客提问"
