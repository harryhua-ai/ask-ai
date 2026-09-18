"""#68 AC3-AC5:Conversation Review Country/Entry 权威投影 + 服务端过滤测试。

语义基线(CONVERSATION-REVIEW-PRODUCT-UI-CONTRACT-20260917):
- 投影:country 仅在携带可信来源(country_source 非空)时呈现为地理事实;
  legacy 启发式值不呈现;entry = site_id → SiteExperience.display_name 权威投影,
  站点配置缺失 → Unknown,绝无 URL/transport 猜测;
- 过滤:country / entry 服务端在分页与计数之前执行,与既有过滤器组合;
  UNKNOWN 是一等可筛值;
- 隐私:响应不暴露 raw IP(也不新增保留)。
"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, text

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import Conversation, SiteExperience, User
from backend.main import app

pytestmark = pytest.mark.asyncio(loop_scope="session")

_Q = "conv-country-entry-"


@pytest_asyncio.fixture(loop_scope="session")
async def geo_env():
    """管理员 + 站点配置 + 四种 (country, source, site) 组合对话。"""
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    site_a = f"site-a-{uuid.uuid4().hex[:8]}"
    site_b = f"site-b-{uuid.uuid4().hex[:8]}"
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email="admin-conv-geo@test.com",
                role="admin",
                password_hash=hash_password("pass"),
            )
        )
        session.add(
            SiteExperience(
                site_id=site_a,
                display_name="官网",
                allowed_origins=["https://www.example.com"],
                enabled=True,
            )
        )
        session.add(
            SiteExperience(
                site_id=site_b,
                display_name="Wiki",
                allowed_origins=["https://wiki.example.com"],
                enabled=True,
            )
        )
        rows = [
            # (question, country, country_source, site_id, channel)
            (f"{_Q}trusted-us-siteA", "US", "ingress", site_a, "widget"),
            (f"{_Q}trusted-de-siteB", "DE", "geoip", site_b, "widget"),
            (f"{_Q}legacy-us-nosource", "US", None, site_a, "widget"),  # 启发式遗留
            (f"{_Q}unknown-null", None, None, None, "discord"),  # 全未知
        ]
        for question, country, source, site_id, channel in rows:
            session.add(
                Conversation(
                    question=question,
                    channel=channel,
                    is_answered=True,
                    country=country,
                    country_source=source,
                    site_id=site_id,
                )
            )
        await session.commit()
    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {
        "headers": {"Authorization": f"Bearer {token}"},
        "site_a": site_a,
        "site_b": site_b,
    }
    async with factory() as session:
        await session.execute(delete(Conversation).where(Conversation.question.like(f"{_Q}%")))
        await session.execute(delete(SiteExperience).where(SiteExperience.site_id.in_([site_a, site_b])))
        await session.execute(delete(User).where(User.id == user_id))
        await session.commit()


async def _list(client, headers, **params):
    resp = await client.get("/api/admin/conversations", headers=headers, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _detail(client, headers, conversation_id):
    resp = await client.get(f"/api/admin/conversations/{conversation_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.unit
async def test_list_projects_country_only_with_trusted_source(geo_env):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        data = await _list(client, geo_env["headers"], q=_Q)
    by_q = {item["question"]: item for item in data["items"]}
    # 权威值呈现 + 来源
    assert by_q[f"{_Q}trusted-us-siteA"]["country"] == "US"
    assert by_q[f"{_Q}trusted-us-siteA"]["country_source"] == "ingress"
    assert by_q[f"{_Q}trusted-de-siteB"]["country"] == "DE"
    assert by_q[f"{_Q}trusted-de-siteB"]["country_source"] == "geoip"
    # legacy 启发式值不得呈现为地理事实
    assert by_q[f"{_Q}legacy-us-nosource"]["country"] is None
    assert by_q[f"{_Q}legacy-us-nosource"]["country_source"] is None
    # 未知呈现为 None(前端渲染 Unknown 态)
    assert by_q[f"{_Q}unknown-null"]["country"] is None


@pytest.mark.unit
async def test_list_projects_entry_from_site_config(geo_env):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        data = await _list(client, geo_env["headers"], q=_Q)
    by_q = {item["question"]: item for item in data["items"]}
    assert by_q[f"{_Q}trusted-us-siteA"]["entry"] == {
        "site_id": geo_env["site_a"],
        "display_name": "官网",
    }
    assert by_q[f"{_Q}trusted-de-siteB"]["entry"]["display_name"] == "Wiki"
    # 无站点(legacy 嵌入)→ Unknown,而非从 channel/URL 猜测
    assert by_q[f"{_Q}unknown-null"]["entry"] is None
    assert by_q[f"{_Q}unknown-null"]["channel"] == "discord"  # transport 独立保留


@pytest.mark.unit
async def test_country_filter_server_side_with_unknown(geo_env):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        us = await _list(client, geo_env["headers"], q=_Q, country="US")
        unknown = await _list(client, geo_env["headers"], q=_Q, country="UNKNOWN")
    us_qs = {i["question"] for i in us["items"]}
    assert us_qs == {f"{_Q}trusted-us-siteA"}  # legacy US 不得因 country=US 命中
    assert us["total"] == 1
    unknown_qs = {i["question"] for i in unknown["items"]}
    assert unknown_qs == {f"{_Q}legacy-us-nosource", f"{_Q}unknown-null"}
    assert unknown["total"] == 2


@pytest.mark.unit
async def test_country_filter_rejects_invalid_code(geo_env):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/admin/conversations", headers=geo_env["headers"], params={"country": "usa"}
        )
    assert resp.status_code == 422


@pytest.mark.unit
async def test_entry_filter_by_site_and_unknown(geo_env):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        site_a = await _list(client, geo_env["headers"], q=_Q, entry=geo_env["site_a"])
        unknown = await _list(client, geo_env["headers"], q=_Q, entry="UNKNOWN")
    assert {i["question"] for i in site_a["items"]} == {
        f"{_Q}trusted-us-siteA",
        f"{_Q}legacy-us-nosource",
    }
    assert {i["question"] for i in unknown["items"]} == {f"{_Q}unknown-null"}


@pytest.mark.unit
async def test_filters_compose_with_existing_and_counts_align(geo_env):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        composed = await _list(
            client,
            geo_env["headers"],
            q=_Q,
            country="UNKNOWN",
            entry="UNKNOWN",
            channel="discord",
        )
    assert composed["total"] == 1
    assert {i["question"] for i in composed["items"]} == {f"{_Q}unknown-null"}


@pytest.mark.unit
async def test_detail_exposes_same_truth(geo_env):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        data = await _list(client, geo_env["headers"], q=_Q, country="DE")
        assert data["total"] == 1
        detail = await _detail(client, geo_env["headers"], data["items"][0]["id"])
    assert detail["country"] == "DE"
    assert detail["country_source"] == "geoip"
    assert detail["entry"]["display_name"] == "Wiki"


@pytest.mark.unit
async def test_entry_options_lists_site_projection(geo_env):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/conversations/entry-options", headers=geo_env["headers"])
    assert resp.status_code == 200
    options = {o["site_id"]: o["display_name"] for o in resp.json()}
    assert options[geo_env["site_a"]] == "官网"
    assert options[geo_env["site_b"]] == "Wiki"


@pytest.mark.unit
async def test_country_options_lists_distinct_trusted_codes(geo_env):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/admin/conversations/country-options", headers=geo_env["headers"]
        )
        assert resp.status_code == 200
        codes = resp.json()["countries"]
        # 只收集可信来源值(legacy 行不得借 options 复活为候选事实):
        # country=US 只命中权威 US 行,说明 legacy US 未进入事实空间
        legacy_rows = await _list(client, geo_env["headers"], q=_Q, country="US")
    assert "US" in codes and "DE" in codes
    assert codes == sorted(codes)
    assert legacy_rows["total"] == 1
