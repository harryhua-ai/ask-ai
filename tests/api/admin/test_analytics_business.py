"""业务概览聚合端点测试。"""

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import Conversation, User
from backend.main import app

pytestmark = pytest.mark.asyncio(loop_scope="session")

_USER_EMAIL = "biz@test.com"


@pytest_asyncio.fixture(loop_scope="session")
async def business_seed():
    factory = app.state.session_factory
    # 预清理
    async with factory() as session:
        await session.execute(User.__table__.delete().where(User.email == _USER_EMAIL))
        await session.execute(
            Conversation.__table__.delete().where(Conversation.question.like("biz_test_%"))
        )
        await session.commit()

    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email=_USER_EMAIL,
                role="admin",
                password_hash=hash_password("pass"),
            )
        )
        for intent in ("commercial", "product", "support"):
            session.add(
                Conversation(
                    question=f"biz_test_{intent}",
                    channel="widget",
                    is_answered=True,
                    intent_tag=intent,
                )
            )
        await session.commit()
    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}
    # 后清理
    async with factory() as session:
        await session.execute(User.__table__.delete().where(User.email == _USER_EMAIL))
        await session.execute(
            Conversation.__table__.delete().where(Conversation.question.like("biz_test_%"))
        )
        await session.commit()


async def test_business_overview(business_seed):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/admin/business/overview?range=7d", headers=business_seed
        )
    assert resp.status_code == 200
    j = resp.json()
    assert j["service"]["total"] > 0
    assert len(j["service"]["intent_dist"]) >= 3
    assert j["service"]["north_star"] >= 0
    assert "geo" in j
    # leads 字段契约(前端 BusinessOverview 依赖,曾因字段名不匹配导致白屏)
    assert set(j["leads"].keys()) >= {"valid", "potential", "hot_products"}
    assert isinstance(j["leads"]["hot_products"], list)
    # intent_dist 四意图键补全(前端 KpiCard 直接读 .commercial 等)
    assert set(j["service"]["intent_dist"].keys()) == {
        "commercial",
        "product",
        "support",
        "off_topic",
    }


async def test_business_overview_custom_range(business_seed):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/admin/business/overview?from=2026-08-01&to=2026-08-05",
            headers=business_seed,
        )
    assert resp.status_code == 200


async def test_business_overview_geo_pct_and_90d(business_seed):
    """geo 项含 pct(占比),range=90d 接受。"""
    factory = app.state.session_factory
    async with factory() as session:
        # 补两条带 country 的对话(business_seed 创建的对话无 country)
        session.add(
            Conversation(
                question="biz_test_geo_cn",
                channel="widget",
                is_answered=True,
                intent_tag="commercial",
                country="CN",
            )
        )
        session.add(
            Conversation(
                question="biz_test_geo_us",
                channel="widget",
                is_answered=True,
                intent_tag="commercial",
                country="US",
            )
        )
        await session.commit()

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/admin/business/overview?range=90d", headers=business_seed
            )
        assert resp.status_code == 200
        j = resp.json()
        assert j["service"]["total"] > 0
        # geo 项含 pct
        assert len(j["geo"]) > 0
        for g in j["geo"]:
            assert "pct" in g
            assert 0 <= g["pct"] <= 100
        # 含 CN/US 两条,占比相等(各 50%,因 fixture 只加这两条带 country)
        cn = [g for g in j["geo"] if g["name"] == "CN"]
        us = [g for g in j["geo"] if g["name"] == "US"]
        assert cn and us
        assert cn[0]["pct"] == us[0]["pct"]
    finally:
        async with factory() as session:
            await session.execute(
                Conversation.__table__.delete().where(
                    Conversation.question.in_(["biz_test_geo_cn", "biz_test_geo_us"])
                )
            )
            await session.commit()
