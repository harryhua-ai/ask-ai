"""Issue #24:site-config 外观字段(授权 Origin 下的响应体增量)。

- 已授权站点返回归一化 launcher_style/launcher_theme(未配置 = current|auto);
- 非法持久值服务端回落(P6);授权路径零变化(G1/G2:403 行为不因外观改变)。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app

STORE_ORIGIN = "https://www.camthink.ai"


def _make_site_row(**overrides) -> MagicMock:
    row = MagicMock()
    row.site_id = overrides.get("site_id", "camthink-store")
    row.enabled = True
    row.allowed_origins = [STORE_ORIGIN]
    row.starters = ["Is NE503 suitable for my project?"]
    row.display_name = "CamThink Store"
    row.welcome = "Shopping for a CamThink device?"
    row.language = "en"
    row.launcher_style = overrides.get("launcher_style")
    row.launcher_theme = overrides.get("launcher_theme")
    return row


def _make_site_factory(site_row: MagicMock | None) -> MagicMock:
    session = AsyncMock()
    session.get = AsyncMock(return_value=site_row)
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=None)
    return factory


async def _fetch(factory, site_id="camthink-store", origin=STORE_ORIGIN):
    app.state.session_factory = factory
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.get(
            "/api/widget/site-config",
            params={"site_id": site_id},
            headers={"Origin": origin} if origin else {},
        )


@pytest.mark.asyncio(loop_scope="session")
async def test_site_config_returns_default_appearance_when_unconfigured():
    factory = _make_site_factory(_make_site_row())
    resp = await _fetch(factory)
    assert resp.status_code == 200
    body = resp.json()
    assert body["launcher_style"] == "current"
    assert body["launcher_theme"] == "auto"


@pytest.mark.asyncio(loop_scope="session")
async def test_site_config_returns_saved_appearance():
    factory = _make_site_factory(
        _make_site_row(launcher_style="assistant-spark", launcher_theme="dark")
    )
    resp = await _fetch(factory)
    assert resp.status_code == 200
    body = resp.json()
    assert body["launcher_style"] == "assistant-spark"
    assert body["launcher_theme"] == "dark"


@pytest.mark.asyncio(loop_scope="session")
async def test_site_config_invalid_persisted_values_fallback_server_side():
    """P6:非法持久值 → 服务端归一化回落(Widget 端无需猜测)。"""
    factory = _make_site_factory(
        _make_site_row(launcher_style="logo1.svg", launcher_theme="sometimes")
    )
    resp = await _fetch(factory)
    assert resp.status_code == 200
    body = resp.json()
    assert body["launcher_style"] == "current"
    assert body["launcher_theme"] == "auto"


@pytest.mark.asyncio(loop_scope="session")
async def test_site_config_denied_origin_stays_denied_with_appearance_fields_absent():
    """G1/G2:未授权 Origin 仍 403;外观不改变授权行为。"""
    factory = _make_site_factory(_make_site_row(launcher_style="chat-bubble"))
    resp = await _fetch(factory, origin="https://evil.test")
    assert resp.status_code == 403
    assert "launcher_style" not in resp.json()
