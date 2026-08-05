"""/api/ask 附件归属校验测试(403 越权 / 422 未知)。"""
import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from backend.db.models import Attachment
from backend.main import app


def _set_state():
    """注入 mock budget + rag(归属校验在 stream_answer 之前,rag 不会被调用)。"""
    from backend.utils.budget import BudgetConfig, BudgetLimiter

    app.state.budget = BudgetLimiter(
        BudgetConfig(daily_request_limit=10_000, daily_token_limit=10_000_000)
    )
    app.state.rag = AsyncMock()


@pytest.fixture
async def _ask_session_factory(db_engine):
    from backend.db.session import get_session_factory

    factory = get_session_factory(db_engine)
    app.state.session_factory = factory
    yield factory


@pytest.mark.integration
async def test_ask_attachment_wrong_owner_403(_ask_session_factory):
    """att 属于 session-B,用 session-A 调 /api/ask → 403。"""
    _set_state()

    # 直接在 DB 插一条属于 session-B 的附件
    att = Attachment(
        id=uuid.uuid4(),
        owner_type="widget_anon",
        owner_id="session-B",
        filename="b.log",
        mime_type="text/x-log",
        kind="log",
        size_bytes=10,
        extracted_text="some log",
    )
    async with _ask_session_factory() as s:
        s.add(att)
        await s.commit()
    att_id = str(att.id)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/ask",
            json={
                "message": "analyze",
                "channel": "widget",
                "session_id": "session-A",
                "attachments": [att_id],
            },
        )
    assert resp.status_code == 403, resp.text


@pytest.mark.integration
async def test_ask_attachment_unknown_422(_ask_session_factory):
    _set_state()
    fake_id = str(uuid.uuid4())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/ask",
            json={
                "message": "analyze",
                "channel": "widget",
                "session_id": "session-A",
                "attachments": [fake_id],
            },
        )
    assert resp.status_code == 422, resp.text


@pytest.mark.integration
async def test_ask_widget_attachments_require_session_id(_ask_session_factory):
    """widget 渠道带附件但缺 session_id → 422。"""
    _set_state()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/ask",
            json={
                "message": "analyze",
                "channel": "widget",
                "attachments": [str(uuid.uuid4())],
            },
        )
    assert resp.status_code == 422, resp.text
