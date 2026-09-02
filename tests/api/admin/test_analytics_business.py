"""业务概览聚合端点测试。"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import BusinessSignal, Conversation, User
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
    # CAMTHINK V1 销售线索口径:独立 sales_leads,不再有 valid(=commercial 对话)混淆
    assert set(j["leads"].keys()) >= {
        "commercial_conversations",
        "potential",
        "qualified",
        "contactable",
        "handed_off",
        "hot_products",
    }
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


async def test_business_overview_prev_total_delta(business_seed):
    """service.prev_total/delta_pct = 上一同等长度时间窗的 total + 环比。"""
    factory = app.state.session_factory
    now = datetime.now(UTC)
    try:
        async with factory() as session:
            # 本窗(最近 7d):3 条
            for i in range(3):
                session.add(
                    Conversation(
                        question=f"biz_test_prev_cur_{i}",
                        channel="widget",
                        is_answered=True,
                        intent_tag="commercial",
                        created_at=now - timedelta(days=1),
                    )
                )
            # 上窗(7-14d 前):2 条
            for i in range(2):
                session.add(
                    Conversation(
                        question=f"biz_test_prev_prev_{i}",
                        channel="widget",
                        is_answered=True,
                        intent_tag="commercial",
                        created_at=now - timedelta(days=10),
                    )
                )
            await session.commit()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/admin/business/overview?range=7d", headers=business_seed
            )
        assert resp.status_code == 200
        svc = resp.json()["service"]
        # prev_total/delta_pct 字段存在
        assert "prev_total" in svc
        assert "delta_pct" in svc
        # 上窗至少 2 条(可能含其他测试残留,但 >=2)
        assert svc["prev_total"] >= 2
        # delta_pct 为数值
        assert isinstance(svc["delta_pct"], (int, float))
    finally:
        async with factory() as session:
            await session.execute(
                Conversation.__table__.delete().where(
                    Conversation.question.like("biz_test_prev_%")
                )
            )
            await session.commit()


async def test_business_overview_signals_overlap_with_query_window(business_seed):
    """场景应用/产品需求在 overview 中按"区间重叠"展示,而非要求信号完全包含在查询窗口内。

    复现:SignalExtractor 默认 30 天窗(period_start=now-30d, period_end=now),
    overview 默认 7d(start=now-7d, end=now)。旧查询条件
    `period_start >= start AND period_end <= end` 要求信号完全包含在查询窗内,
    30 天信号永远不被 7 天窗口包含 → scenes/requirements 永远为空。
    正确语义:信号时间段与查询时间段有重叠即展示。
    """
    factory = app.state.session_factory
    now = datetime.now(UTC)
    try:
        async with factory() as session:
            # 模拟 SignalExtractor 的 30 天窗产出
            session.add(
                BusinessSignal(
                    type="scene",
                    label="biz_test_signal_scene",
                    count=5,
                    pct=10.0,
                    period_start=now - timedelta(days=30),
                    period_end=now,
                )
            )
            session.add(
                BusinessSignal(
                    type="requirement",
                    label="biz_test_signal_req",
                    count=3,
                    pct=6.0,
                    period_start=now - timedelta(days=30),
                    period_end=now,
                )
            )
            await session.commit()
        # 用默认 7d 窗查询——信号 30 天窗与 7 天窗有重叠,应展示
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/admin/business/overview?range=7d", headers=business_seed
            )
        assert resp.status_code == 200
        scenes = resp.json()["scenes"]
        requirements = resp.json()["requirements"]
        assert any(s["label"] == "biz_test_signal_scene" for s in scenes), \
            f"30 天窗信号在 7d 查询中应展示(区间重叠),实际 scenes={scenes}"
        assert any(r["label"] == "biz_test_signal_req" for r in requirements), \
            f"30 天窗信号在 7d 查询中应展示(区间重叠),实际 requirements={requirements}"
    finally:
        async with factory() as session:
            await session.execute(
                BusinessSignal.__table__.delete().where(
                    BusinessSignal.label.like("biz_test_signal_%")
                )
            )
            await session.commit()


async def test_hot_questions_by_intent(business_seed):
    """按 intent 过滤的 Top3 问题(按 question 文本聚合)。"""
    factory = app.state.session_factory
    now = datetime.now(UTC)
    try:
        async with factory() as session:
            # commercial:3 条,其中 "biz_test_hot_A" 2 次
            for _ in range(2):
                session.add(
                    Conversation(
                        question="biz_test_hot_A",
                        channel="widget",
                        is_answered=True,
                        intent_tag="commercial",
                        created_at=now - timedelta(days=1),
                    )
                )
            session.add(
                Conversation(
                    question="biz_test_hot_B",
                    channel="widget",
                    is_answered=True,
                    intent_tag="commercial",
                    created_at=now - timedelta(days=1),
                )
            )
            # product:1 条(不应出现在 commercial 结果)
            session.add(
                Conversation(
                    question="biz_test_hot_product",
                    channel="widget",
                    is_answered=True,
                    intent_tag="product",
                    created_at=now - timedelta(days=1),
                )
            )
            await session.commit()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/admin/business/hot-questions?intent=commercial&range=7d",
                headers=business_seed,
            )
        assert resp.status_code == 200
        j = resp.json()
        assert j["intent"] == "commercial"
        assert len(j["items"]) <= 3
        # biz_test_hot_A 出现 2 次,应排第一
        top = j["items"][0]
        assert top["question"] == "biz_test_hot_A"
        assert top["count"] == 2
        # 不含 product
        assert all("product" not in i["question"] for i in j["items"])
    finally:
        async with factory() as session:
            await session.execute(
                Conversation.__table__.delete().where(
                    Conversation.question.like("biz_test_hot_%")
                )
            )
            await session.commit()
