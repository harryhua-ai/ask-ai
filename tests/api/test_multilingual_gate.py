"""P1 Three-Site Multilingual Behavior Closure —— ML 门用例(API 层)。

- ML-G001/ML-G010:/api/ask 消费请求 language 提示(端到端);显式 site_id
  未带提示时回落站点默认语言(宿主默认语境);
- ML-G006/ML-G007:site-config 按语言返回本地化 welcome/starters,无变体回落默认;
- ML-G008:三站 YAML 双语内容齐备(内容决策落地);
- ML-G009:site_id 独立于语言 —— 语言参数不影响站点授权/身份。
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from backend.main import app
from backend.services.site_experiences import load_sites_config
from backend.utils.budget import BudgetConfig, BudgetLimiter
from tests.api.test_site_routes import STORE_ORIGIN, _make_site_factory, _make_site_row

_EN_WELCOME = "Shopping for a CamThink device? Ask me before you order."
_ZH_WELCOME = "正在选购 CamThink 设备?下单前可以先问我。"
_EN_STARTERS = ["Is NE503 suitable for my project?", "Compare NE503 with NE301"]
_ZH_STARTERS = ["NE503 适合我的项目吗?", "NE503 和 NE301 有什么区别?"]


def _make_site_row_i18n(**kw) -> MagicMock:
    row = _make_site_row(
        **{
            k: v
            for k, v in kw.items()
            if k in ("site_id", "welcome", "language", "starters", "display_name")
        }
    )
    row.welcome_i18n = kw.get("welcome_i18n")
    row.starters_i18n = kw.get("starters_i18n")
    return row


_EVENTS = [
    {"type": "token", "content": "answer"},
    {
        "type": "complete",
        "answer": "answer",
        "sources": [],
        "is_answered": True,
        "language": "en",
        "response_time_ms": 5,
    },
]


def _capture_rag(events: list[dict], captured: dict):
    async def stream_answer(*args, **kwargs):
        captured.update(kwargs)
        for evt in events:
            yield json.dumps(evt)

    rag = AsyncMock()
    rag.stream_answer = stream_answer
    return rag


@pytest.fixture(autouse=True)
def _budget_state():
    app.state.budget = BudgetLimiter(
        BudgetConfig(daily_request_limit=10_000, daily_token_limit=10_000_000)
    )


@pytest.fixture(autouse=True)
def _reset_ask_rate_limit():
    from backend.api.routes import limiter

    limiter.reset()


# --------------------------------------------------------------------------- #
# ML-G001 / ML-G010 —— ask 端到端消费语言提示;站点默认语言兜底
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_ml_g001_ask_consumes_language_hint_end_to_end():
    captured: dict = {}
    factory, _session = _make_site_factory(_make_site_row())
    app.state.rag = _capture_rag(_EVENTS, captured)
    app.state.session_factory = factory

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/ask",
            json={
                "message": "¿Qué funciones tiene?",
                "site_id": "camthink-store",
                "language": "es-MX",
            },
            headers={"Origin": STORE_ORIGIN},
        )

    assert resp.status_code == 200
    # 归一化(es-MX→es)后作为答案语境传入管线
    assert captured["language_hint"] == "es"


@pytest.mark.unit
async def test_ml_g010_site_default_language_fallback_when_hint_missing():
    captured: dict = {}
    factory, _session = _make_site_factory(_make_site_row(language="en"))
    app.state.rag = _capture_rag(_EVENTS, captured)
    app.state.session_factory = factory

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/ask",
            json={"message": "Is NE503 suitable?", "site_id": "camthink-store"},
            headers={"Origin": STORE_ORIGIN},
        )

    assert resp.status_code == 200
    # 宿主未带页面语言 → 站点默认语言(en)作为默认答案语境
    assert captured["language_hint"] == "en"

    # legacy(无 site_id、无提示)→ hint 为 None,管线走文本检测(基线零回归)
    captured2: dict = {}
    factory2, _s2 = _make_site_factory(None)
    app.state.rag = _capture_rag(_EVENTS, captured2)
    app.state.session_factory = factory2
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp2 = await client.post("/api/ask", json={"message": "hello"})
    assert resp2.status_code == 200
    assert captured2["language_hint"] is None


# --------------------------------------------------------------------------- #
# ML-G006 / ML-G007 —— site-config 本地化 welcome / starters
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_ml_g006_site_config_localized_welcome_with_fallback():
    factory, _session = _make_site_factory(
        _make_site_row_i18n(
            welcome=_EN_WELCOME,
            welcome_i18n={"zh": _ZH_WELCOME},
            starters=_EN_STARTERS,
            starters_i18n={"zh": _ZH_STARTERS},
        )
    )
    app.state.session_factory = factory

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ok = await client.get(
            "/api/widget/site-config",
            params={"site_id": "camthink-store", "language": "zh-CN"},
            headers={"Origin": STORE_ORIGIN},
        )
        fallback = await client.get(
            "/api/widget/site-config",
            params={"site_id": "camthink-store", "language": "fr"},
            headers={"Origin": STORE_ORIGIN},
        )

    assert ok.status_code == 200
    body = ok.json()
    assert body["welcome"] == _ZH_WELCOME
    # fr 无变体 → 回落站点默认(默认语言 en 的内容)
    assert fallback.json()["welcome"] == _EN_WELCOME


@pytest.mark.unit
async def test_ml_g007_site_config_localized_starters_with_fallback():
    factory, _session = _make_site_factory(
        _make_site_row_i18n(
            welcome=_EN_WELCOME,
            welcome_i18n={"zh": _ZH_WELCOME},
            starters=_EN_STARTERS,
            starters_i18n={"zh": _ZH_STARTERS},
        )
    )
    app.state.session_factory = factory

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        zh = await client.get(
            "/api/widget/site-config",
            params={"site_id": "camthink-store", "language": "zh"},
            headers={"Origin": STORE_ORIGIN},
        )
        en = await client.get(
            "/api/widget/site-config",
            params={"site_id": "camthink-store"},
            headers={"Origin": STORE_ORIGIN},
        )

    assert zh.json()["starters"] == _ZH_STARTERS
    assert en.json()["starters"] == _EN_STARTERS


# --------------------------------------------------------------------------- #
# ML-G008 —— 三站双语内容齐备(YAML 权威源内容决策落地)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_ml_g008_three_sites_localized_content_present():
    sites = {s["site_id"]: s for s in load_sites_config()}
    assert set(sites) == {"camthink-website", "camthink-wiki", "camthink-store"}
    for site_id, site in sites.items():
        # 默认语言 = en,默认文案存在
        assert site.get("language") == "en", site_id
        assert site.get("welcome"), site_id
        assert isinstance(site.get("starters"), list) and site["starters"], site_id
        # zh 变体齐备(G-L5:含 wiki 原中文文案的对齐迁移)
        assert site.get("welcome_i18n", {}).get("zh"), site_id
        zh_starters = site.get("starters_i18n", {}).get("zh")
        assert isinstance(zh_starters, list) and zh_starters, site_id
        # 变体数量与默认一致(逐条对应,不缺项)
        assert len(zh_starters) == len(site["starters"]), site_id


# --------------------------------------------------------------------------- #
# ML-G009 —— site_id 独立于语言
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_ml_g009_site_identity_independent_of_language():
    factory, _session = _make_site_factory(
        _make_site_row_i18n(
            welcome=_EN_WELCOME,
            welcome_i18n={"zh": _ZH_WELCOME},
        )
    )
    app.state.session_factory = factory

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        en = await client.get(
            "/api/widget/site-config",
            params={"site_id": "camthink-store"},
            headers={"Origin": STORE_ORIGIN},
        )
        zh = await client.get(
            "/api/widget/site-config",
            params={"site_id": "camthink-store", "language": "zh"},
            headers={"Origin": STORE_ORIGIN},
        )
        fr = await client.get(
            "/api/widget/site-config",
            params={"site_id": "camthink-store", "language": "fr"},
            headers={"Origin": STORE_ORIGIN},
        )

    # 身份字段跨语言恒等;语言只切换体验文案
    for resp in (en, zh, fr):
        assert resp.json()["site_id"] == "camthink-store"
        assert resp.json()["display_name"] == "CamThink Store"
        assert resp.json()["language"] == "en"
    assert en.json()["welcome"] != zh.json()["welcome"]
    assert fr.json()["welcome"] == en.json()["welcome"]

    # 授权链与语言无关:错误 Origin 一律 403(带/不带语言参数同结果)
    app.state.rag = _capture_rag(_EVENTS, {})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r1 = await client.get(
            "/api/widget/site-config",
            params={"site_id": "camthink-store"},
            headers={"Origin": "https://evil.example"},
        )
        r2 = await client.get(
            "/api/widget/site-config",
            params={"site_id": "camthink-store", "language": "zh"},
            headers={"Origin": "https://evil.example"},
        )
    assert r1.status_code == r2.status_code == 403
