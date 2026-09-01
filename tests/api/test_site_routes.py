"""MSW:/api/ask 站点门禁 + GET /api/widget/site-config + site_id 持久化。

冻结语义:
- 显式 site_id 必须通过「站点存在且 enabled + Origin 精确命中」,否则 403
  (统一文案,fail-safe;rag 不被调用,对话不落库);
- legacy(无 site_id)不触发站点校验,行为与基线一致;
- channel 恒为传输渠道(widget),site_id 不改变可见性授权链(P0)。
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app
from backend.utils.budget import BudgetConfig, BudgetLimiter
from tests.api.test_routes import _parse_sse_events

STORE_ORIGIN = "https://store.camthink.ai"


def _make_site_row(
    *,
    site_id: str = "camthink-store",
    enabled: bool = True,
    origins: list | None = None,
    starters: list | None = None,
    display_name: str = "CamThink Store",
    welcome: str | None = "Shopping for a CamThink device?",
    language: str | None = "en",
) -> MagicMock:
    row = MagicMock()
    row.site_id = site_id
    row.enabled = enabled
    row.allowed_origins = origins if origins is not None else [STORE_ORIGIN]
    row.starters = starters if starters is not None else ["Is NE503 suitable for my project?"]
    row.display_name = display_name
    row.welcome = welcome
    row.language = language
    return row


def _make_site_factory(site_row: MagicMock | None) -> tuple[MagicMock, AsyncMock]:
    session = AsyncMock()
    session.add = MagicMock()
    session.get = AsyncMock(return_value=site_row)
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory, session


def _capture_rag(events: list[dict], captured: dict):
    async def stream_answer(*args, **kwargs):
        captured.update(kwargs)
        for evt in events:
            yield json.dumps(evt)

    rag = AsyncMock()
    rag.stream_answer = stream_answer
    return rag


_EVENTS = [
    {"type": "sources", "sources": [{"url": "https://x/b", "title": "B", "type": "github", "product": "ne503"}]},
    {"type": "token", "content": "answer"},
    {"type": "complete", "answer": "answer", "sources": [], "is_answered": True,
     "language": "en", "response_time_ms": 5},
]


@pytest.fixture(autouse=True)
def _budget_state():
    app.state.budget = BudgetLimiter(
        BudgetConfig(daily_request_limit=10_000, daily_token_limit=10_000_000)
    )


@pytest.fixture(autouse=True)
def _reset_ask_rate_limit():
    """每条用例前清空 /ask 的 slowapi 内存计数(20/minute 按 127.0.0.1 累计,
    全量回归时会被套件内其他 ask 用例挤爆 → 假 429)。"""
    from backend.api.routes import limiter

    limiter.reset()


# --------------------------------------------------------------------------- #
# POST /api/ask 站点门禁
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_ask_authorized_site_persists_site_id_and_threads_context():
    captured: dict = {}
    factory, session = _make_site_factory(_make_site_row())
    app.state.rag = _capture_rag(_EVENTS, captured)
    app.state.session_factory = factory

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/ask",
            json={
                "message": "Is NE503 suitable?",
                "site_id": "camthink-store",
                "page_context": {"product": "NE503", "page_type": "product"},
            },
            headers={"Origin": STORE_ORIGIN},
        )

    assert resp.status_code == 200
    assert [e["event"] for e in _parse_sse_events(resp.text)] == ["sources", "token", "done"]
    # 上下文贯通:site_name + 消毒后 page_context + channel 恒为 widget(P0)
    assert captured["site_name"] == "CamThink Store"
    assert captured["page_context"] == {"product": "NE503", "page_type": "product"}
    assert captured["channel"] == "widget"
    # 持久化:conversation.site_id 落值
    session.add.assert_called_once()
    conv = session.add.call_args.args[0]
    assert conv.site_id == "camthink-store"
    assert conv.channel == "widget"


@pytest.mark.unit
async def test_ask_spoofed_origin_denied_403_and_no_side_effects():
    captured: dict = {}
    factory, session = _make_site_factory(_make_site_row())
    app.state.rag = _capture_rag(_EVENTS, captured)
    app.state.session_factory = factory

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/ask",
            json={"message": "hi", "site_id": "camthink-store"},
            headers={"Origin": "https://evil.example"},
        )

    assert resp.status_code == 403
    assert captured == {}  # rag 未被调用
    session.add.assert_not_called()  # 对话不落库


@pytest.mark.unit
async def test_ask_unknown_site_denied_403():
    captured: dict = {}
    factory, session = _make_site_factory(None)
    app.state.rag = _capture_rag(_EVENTS, captured)
    app.state.session_factory = factory

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/ask",
            json={"message": "hi", "site_id": "ghost-site"},
            headers={"Origin": STORE_ORIGIN},
        )
    assert resp.status_code == 403
    assert captured == {}


@pytest.mark.unit
async def test_ask_site_without_origin_denied_403():
    """非浏览器客户端不带 Origin:显式 site_id 无法验证来源 → fail-safe 403。"""
    captured: dict = {}
    factory, _session = _make_site_factory(_make_site_row())
    app.state.rag = _capture_rag(_EVENTS, captured)
    app.state.session_factory = factory

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/ask", json={"message": "hi", "site_id": "camthink-store"}
        )
    assert resp.status_code == 403
    assert captured == {}


@pytest.mark.unit
async def test_ask_disabled_site_denied_403():
    captured: dict = {}
    factory, _session = _make_site_factory(_make_site_row(enabled=False))
    app.state.rag = _capture_rag(_EVENTS, captured)
    app.state.session_factory = factory

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/ask",
            json={"message": "hi", "site_id": "camthink-store"},
            headers={"Origin": STORE_ORIGIN},
        )
    assert resp.status_code == 403


@pytest.mark.unit
async def test_ask_legacy_without_site_id_skips_site_validation():
    """G006:legacy 请求不查站点表,conversation.site_id 为 NULL。"""
    captured: dict = {}
    factory, session = _make_site_factory(None)
    app.state.rag = _capture_rag(_EVENTS, captured)
    app.state.session_factory = factory

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/ask", json={"message": "NE503 功耗"})
    assert resp.status_code == 200
    session.get.assert_not_awaited()
    conv = session.add.call_args.args[0]
    assert conv.site_id is None
    assert captured.get("page_context") is None


# --------------------------------------------------------------------------- #
# GET /api/widget/site-config
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_site_config_returns_experience_for_authorized_origin():
    factory, _session = _make_site_factory(_make_site_row())
    app.state.session_factory = factory

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/widget/site-config",
            params={"site_id": "camthink-store"},
            headers={"Origin": STORE_ORIGIN},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["site_id"] == "camthink-store"
    assert body["display_name"] == "CamThink Store"
    assert body["starters"] == ["Is NE503 suitable for my project?"]
    assert body["welcome"] == "Shopping for a CamThink device?"
    assert body["language"] == "en"
    # 内部配置不外泄:allowed_origins 不出现在公开响应
    assert "allowed_origins" not in body


@pytest.mark.unit
async def test_site_config_mismatched_origin_denied():
    factory, _session = _make_site_factory(_make_site_row())
    app.state.session_factory = factory

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/widget/site-config",
            params={"site_id": "camthink-store"},
            headers={"Origin": "https://evil.example"},
        )
    assert resp.status_code == 403


@pytest.mark.unit
async def test_site_config_unknown_site_denied():
    factory, _session = _make_site_factory(None)
    app.state.session_factory = factory

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/widget/site-config",
            params={"site_id": "ghost"},
            headers={"Origin": STORE_ORIGIN},
        )
    assert resp.status_code == 403


@pytest.mark.unit
async def test_site_config_missing_origin_denied():
    factory, _session = _make_site_factory(_make_site_row())
    app.state.session_factory = factory

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/widget/site-config", params={"site_id": "camthink-store"})
    assert resp.status_code == 403


@pytest.mark.unit
async def test_site_config_requires_site_id_param():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/widget/site-config", headers={"Origin": STORE_ORIGIN})
    assert resp.status_code == 422
