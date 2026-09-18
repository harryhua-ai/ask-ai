"""#87 AC3-AC5:会话(Thread)列表/详情 API 测试——服务端聚合、过滤、分页。

语义基线(CONVERSATION-REVIEW-PRODUCT-UI-CONTRACT-20260917):
- 聚合/搜索/过滤/计数/分页全部服务端在分页前完成;禁止页内 groupBy;
- 命中任一 Turn 即晋升其所在 Thread(完整 transcript,不裁剪);
- session_id 缺失的历史行 = 诚实 singleton;
- 仅呈现可真实派生的字段(首问/轮数/时间范围/入口/国家/异常信号),
  无 LLM 标题/推断解决态/客户身份/质量分。
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import Conversation, SiteExperience, Trace, User
from backend.main import app

pytestmark = pytest.mark.asyncio(loop_scope="session")

_Q = "conv-threads-"
_T0 = datetime(2026, 9, 18, 8, 0, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture(loop_scope="session")
async def thread_env():
    """管理员 + 三条线程 + 两条 legacy singleton + 站点配置。"""
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    site_a = f"thread-site-a-{uuid.uuid4().hex[:6]}"
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email="admin-threads@test.com",
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

        async def conv(question, minutes, session_id=None, site_id=site_a, channel="widget",
                       answer="回复", intent="support", country=None, source=None):
            return Conversation(
                question=f"{_Q}{question}",
                answer=answer if answer is None else f"{answer}",
                channel=channel,
                is_answered=True,
                intent_tag=intent,
                country=country,
                country_source=source,
                site_id=site_id,
                session_id=session_id,
                created_at=_T0 + timedelta(minutes=minutes),
            )

        rows = [
            # Thread T1(s1@siteA/widget):3 轮,间隔 10min;第二问供晋升匹配
            await conv("T1 第一问", 0, session_id="s1"),
            await conv("T1 第二问", 10, session_id="s1", answer="NE503 特有答案"),
            await conv("T1 第三问", 20, session_id="s1"),
            # Thread T2(s2@siteA/widget):1 轮,与 T1 同 session 不同会话键
            await conv("T2 唯一问", 30, session_id="s2"),
            # Thread T3(s3, 无站点):1 轮,带权威国家
            await conv("T3 唯一问", 35, session_id="s3", site_id=None, country="DE",
                       source="ingress"),
            # legacy singletons:无 session_id,绝不互并
            await conv("legacy 一", 40, session_id=None),
            await conv("legacy 二", 41, session_id=None),
        ]
        session.add_all(rows)
        await session.commit()
        ids = {r.question: r.id for r in rows}

    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {
        "headers": {"Authorization": f"Bearer {token}"},
        "site_a": site_a,
        "t1_turn2_id": str(ids[f"{_Q}T1 第二问"]),
        "t1_first_q": f"{_Q}T1 第一问",
    }
    async with factory() as session:
        await session.execute(delete(Conversation).where(Conversation.question.like(f"{_Q}%")))
        await session.execute(delete(SiteExperience).where(SiteExperience.site_id == site_a))
        await session.execute(delete(User).where(User.id == user_id))
        await session.commit()


async def _threads(client, headers, **params):
    resp = await client.get("/api/admin/conversations/threads", headers=headers, params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.unit
async def test_threads_group_count_and_turn_counts(thread_env):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        data = await _threads(client, thread_env["headers"], q=_Q)
    by_first = {i["first_question"]: i for i in data["items"]}
    # 3 threads(T1/T2/T3)+ 2 legacy singleton = 5
    assert data["total"] == 5
    assert by_first[thread_env["t1_first_q"]]["turn_count"] == 3
    assert by_first[f"{_Q}T2 唯一问"]["turn_count"] == 1
    # legacy singleton:各自 1 轮
    assert by_first[f"{_Q}legacy 一"]["turn_count"] == 1
    assert by_first[f"{_Q}legacy 二"]["turn_count"] == 1


@pytest.mark.unit
async def test_matching_turn_promotes_whole_thread(thread_env):
    """q 命中 T1 第二轮 → 整条 Thread 晋升,turn_count 仍为完整 3。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        data = await _threads(client, thread_env["headers"], q="NE503 特有答案")
    assert data["total"] == 1
    assert data["items"][0]["turn_count"] == 3
    assert data["items"][0]["first_question"] == thread_env["t1_first_q"]


@pytest.mark.unit
async def test_thread_pagination_is_server_side(thread_env):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        page1 = await _threads(client, thread_env["headers"], q=_Q, page=1, size=2)
        page2 = await _threads(client, thread_env["headers"], q=_Q, page=2, size=2)
        page3 = await _threads(client, thread_env["headers"], q=_Q, page=3, size=2)
    assert page1["total"] == 5 and len(page1["items"]) == 2
    assert page2["total"] == 5 and len(page2["items"]) == 2
    assert page3["total"] == 5 and len(page3["items"]) == 1
    all_ids = [i["thread_id"] for i in page1["items"] + page2["items"] + page3["items"]]
    assert len(set(all_ids)) == 5  # 无重叠、无遗漏 = 服务端全量分页


@pytest.mark.unit
async def test_thread_filter_by_entry_any_turn_semantics(thread_env):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        data = await _threads(client, thread_env["headers"], q=_Q, entry=thread_env["site_a"])
    # T1/T2 + 两条 legacy(种子默认 site_a)= 4;T3 无站点 → 不命中
    assert data["total"] == 4
    assert all(i["site_id"] == thread_env["site_a"] for i in data["items"])


@pytest.mark.unit
async def test_thread_country_projection_and_filter(thread_env):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        de = await _threads(client, thread_env["headers"], q=_Q, country="DE")
        unknown = await _threads(client, thread_env["headers"], q=_Q, country="UNKNOWN")
    assert de["total"] == 1 and de["items"][0]["country"] == "DE"
    assert de["items"][0]["country_source"] == "ingress"
    # T1/T2/legacy 无权威国家 → UNKNOWN 一等可筛
    assert unknown["total"] == 4


@pytest.mark.unit
async def test_thread_truthful_fields_no_inference(thread_env):
    """卡片字段仅真实派生:首问/轮数/时间范围/入口;无标题推断/解决态/评分。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        data = await _threads(client, thread_env["headers"], q=_Q)
    t1 = next(i for i in data["items"] if i["first_question"] == thread_env["t1_first_q"])
    assert t1["entry"]["display_name"] == "官网"
    assert t1["last_activity_at"] >= t1["started_at"]
    for key in ("title", "resolved", "quality_score", "summary"):
        assert key not in t1


@pytest.mark.unit
async def test_thread_id_stable_across_requests(thread_env):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await _threads(client, thread_env["headers"], q=_Q)
        second = await _threads(client, thread_env["headers"], q=_Q)
    ids1 = {i["thread_id"] for i in first["items"]}
    ids2 = {i["thread_id"] for i in second["items"]}
    assert ids1 == ids2


@pytest.mark.unit
async def test_thread_detail_transcript_chronological(thread_env):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        listing = await _threads(client, thread_env["headers"], q="NE503 特有答案")
        thread_id = listing["items"][0]["thread_id"]
        resp = await client.get(
            f"/api/admin/conversations/threads/{thread_id}", headers=thread_env["headers"]
        )
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["thread_id"] == thread_id
    assert detail["turn_count"] == 3
    assert [t["question"] for t in detail["turns"]] == [
        thread_env["t1_first_q"],
        f"{_Q}T1 第二问",
        f"{_Q}T1 第三问",
    ]
    assert detail["turns"][1]["answer"] == "NE503 特有答案"
    assert detail["entry"]["display_name"] == "官网"


@pytest.mark.unit
async def test_thread_detail_unknown_or_malformed_id_404(thread_env):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        malformed = await client.get(
            "/api/admin/conversations/threads/not-a-thread-id", headers=thread_env["headers"]
        )
        unknown = await client.get(
            "/api/admin/conversations/threads/thread_00000000", headers=thread_env["headers"]
        )
    assert malformed.status_code == 404
    assert unknown.status_code == 404


@pytest.mark.unit
async def test_abnormal_signal_from_unanswered_turn(thread_env):
    """异常信号真实派生:任一轮 is_answered=False → has_abnormal=True。"""
    factory = app.state.session_factory
    async with factory() as session:
        session.add(
            Conversation(
                question=f"{_Q}异常线程问",
                answer=None,
                channel="widget",
                is_answered=False,
                session_id="s-abnormal",
                site_id=thread_env["site_a"],
                created_at=_T0 + timedelta(hours=2),
            )
        )
        await session.commit()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            data = await _threads(client, thread_env["headers"], q=f"{_Q}异常线程问")
        assert data["total"] == 1
        assert data["items"][0]["has_abnormal"] is True
    finally:
        async with factory() as session:
            await session.execute(
                delete(Conversation).where(Conversation.question == f"{_Q}异常线程问")
            )
            await session.commit()
