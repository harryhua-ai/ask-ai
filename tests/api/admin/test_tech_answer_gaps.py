"""v1.6.3 B2 技术洞察收敛 — Answer Gaps 只读投影端点测试。

契约依据(v163-b2-technical-insights-contract.md / KB-OPS-V163-002 §5.2/§10):
- Answer Gaps 是既有权威真相之上的只读操作者投影,不是新持久化模型;
- 相关提问数 = question_count(聚类权威);受影响回答数 = 归属会话计数
  (conversations.cluster_id 权威);最近发生 = 归属会话 MAX(created_at);
- 原因分类必须与 GET /analytics/coverage-gaps 的权威 miss_type 分类同源
  (同一 helper),无证据 → 未分类;
- 状态词表 = 权威 open/resolved;无 OBSERVING;
- 只读(GET-only)、RBAC 不变(viewer+,未认证 401);
- 时间窗过滤只作用于 last_seen 已知的聚类;last_seen 未知(时间不可用)
  不因窗口被排除(不可用 ≠ 窗口外,诚实四态纪律)。
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import Conversation, QuestionCluster, User
from backend.main import app

pytestmark = pytest.mark.asyncio(loop_scope="session")

_USER_EMAIL = "b2-gaps@test.com"
# 共享测试库避让:固定 UUID 段(0xAAAA...)生成主键,按代表问题前缀清理
_RQ_PREFIX = "B2GAP"

_NOW = datetime(2026, 9, 13, 12, 0, 0, tzinfo=UTC)


def _uid(i: int) -> uuid.UUID:
    return uuid.UUID(int=(0xAAAAAAAA000040008000000000000000 + i))


async def _cleanup(factory):
    async with factory() as session:
        rows = (
            await session.execute(
                select(QuestionCluster).where(
                    QuestionCluster.representative_question.like(f"{_RQ_PREFIX}%")
                )
            )
        ).scalars().all()
        ids = [str(r.id) for r in rows]
        if ids:
            await session.execute(
                delete(Conversation).where(Conversation.cluster_id.in_(ids))
            )
            await session.execute(
                delete(QuestionCluster).where(
                    QuestionCluster.id.in_([r.id for r in rows])
                )
            )
        await session.execute(delete(User).where(User.email == _USER_EMAIL))
        await session.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def gaps_seed():
    """seed:3 个 gap 聚类覆盖权威投影的关键形状。

    - A(open):2 条归属会话,均未回答 → miss_type=reject;
      最近会话 created_at=NOW-1h → last_seen 权威。
    - B(resolved):1 条归属会话,answered + 无 sources → miss_type=召回空;
      最近会话 created_at=NOW-30d → window=7d 应排除、window=all 应包含。
    - C(open):0 条归属会话 → impacted=0 / last_seen=None / miss_type=未分类;
      任何窗口都包含(时间不可用不被窗口排除)。
    """
    factory = app.state.session_factory
    await _cleanup(factory)

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

        id_a, id_b, id_c = _uid(1), _uid(2), _uid(3)

        session.add(
            QuestionCluster(
                id=id_a,
                cluster_type="gap",
                representative_question=f"{_RQ_PREFIX}-A 电池续航?",
                sample_questions=[f"{_RQ_PREFIX}-A 电池续航?", "续航多久?"],
                question_count=5,
                status="open",
            )
        )
        session.add(
            QuestionCluster(
                id=id_b,
                cluster_type="gap",
                representative_question=f"{_RQ_PREFIX}-B PoE 支持?",
                sample_questions=[f"{_RQ_PREFIX}-B PoE 支持?"],
                question_count=2,
                status="resolved",
            )
        )
        session.add(
            QuestionCluster(
                id=id_c,
                cluster_type="gap",
                representative_question=f"{_RQ_PREFIX}-C APN 配置?",
                sample_questions=[f"{_RQ_PREFIX}-C APN 配置?"],
                question_count=1,
                status="open",
            )
        )
        await session.flush()

        # A:2 条未回答会话(reject);最近 NOW-1h
        session.add(
            Conversation(
                question=f"{_RQ_PREFIX}-A 电池续航?",
                is_answered=False,
                cluster_id=str(id_a),
                created_at=_NOW - timedelta(hours=2),
            )
        )
        session.add(
            Conversation(
                question="续航多久?",
                is_answered=False,
                cluster_id=str(id_a),
                created_at=_NOW - timedelta(hours=1),
            )
        )
        # B:1 条 answered 无 sources(召回空);NOW-30d(旧,7d 窗外)
        session.add(
            Conversation(
                question=f"{_RQ_PREFIX}-B PoE 支持?",
                answer="抱歉,暂时无法回答。",
                is_answered=True,
                sources=[],
                cluster_id=str(id_b),
                created_at=_NOW - timedelta(days=30),
            )
        )
        await session.commit()

    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}
    await _cleanup(factory)


async def _get(headers, query: str = ""):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/admin/tech/answer-gaps{query}", headers=headers)
    return resp


async def _items(headers, query: str = ""):
    resp = await _get(headers, query)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _by_rq(j, suffix: str):
    for it in j["items"]:
        if it["representative_question"].startswith(f"{_RQ_PREFIX}-{suffix}"):
            return it
    return None


async def test_answer_gaps_projection_counts_and_recency(gaps_seed):
    """相关提问=question_count;受影响回答=归属会话计数;最近发生=MAX(created_at)。"""
    j = await _items(gaps_seed)
    a = _by_rq(j, "A")
    assert a is not None
    assert a["question_count"] == 5
    assert a["impacted_answer_count"] == 2
    assert a["status"] == "open"
    # miss_type 与 /analytics/coverage-gaps 权威分类同源:均未回答 → reject
    assert a["miss_type"] == "reject"
    # last_seen = 归属会话 MAX(created_at)
    assert a["last_seen_at"] == (_NOW - timedelta(hours=1)).isoformat()


async def test_answer_gaps_zero_evidence_is_unclassified_not_invented(gaps_seed):
    """无归属会话 → impacted=0 / last_seen=None / miss_type=未分类(不虚构)。"""
    j = await _items(gaps_seed)
    c = _by_rq(j, "C")
    assert c is not None
    assert c["impacted_answer_count"] == 0
    assert c["last_seen_at"] is None
    assert c["miss_type"] == "未分类"
    # B:answered 无 sources → 权威分类 召回空
    b = _by_rq(j, "B")
    assert b["miss_type"] == "召回空"
    assert b["impacted_answer_count"] == 1
    assert b["status"] == "resolved"


async def test_answer_gaps_filters_status_and_cause(gaps_seed):
    j = await _items(gaps_seed, "?status=resolved")
    assert [it["status"] for it in j["items"]] == ["resolved"]

    j = await _items(gaps_seed, "?cause=召回空")
    items = j["items"]
    assert len(items) == 1
    assert items[0]["representative_question"].startswith(f"{_RQ_PREFIX}-B")


async def test_answer_gaps_search_matches_representative_and_samples(gaps_seed):
    j = await _items(gaps_seed, f"?q={_RQ_PREFIX}-A")
    assert len(j["items"]) == 1
    assert j["items"][0]["representative_question"].startswith(f"{_RQ_PREFIX}-A")

    # 样例问句「续航多久?」(非代表问题)也可命中 —— 搜索问题/主题语义
    j = await _items(gaps_seed, "?q=续航多久")
    assert len(j["items"]) == 1
    assert j["items"][0]["representative_question"].startswith(f"{_RQ_PREFIX}-A")


async def test_answer_gaps_window_honest_four_states(gaps_seed):
    """时间窗纪律:7d 排除旧 last_seen;all 全包含;last_seen 未知不被窗口排除。"""
    j = await _items(gaps_seed, "?window=7d")
    rqs = {it["representative_question"] for it in j["items"]}
    assert f"{_RQ_PREFIX}-A 电池续航?" in rqs
    assert f"{_RQ_PREFIX}-B PoE 支持?" not in rqs  # 30 天前 → 窗外
    assert f"{_RQ_PREFIX}-C APN 配置?" in rqs  # 时间不可用 ≠ 窗口外

    j = await _items(gaps_seed, "?window=all")
    assert len(j["items"]) == 3


async def test_answer_gaps_ordering_and_pagination(gaps_seed):
    """默认 last_seen 降序且 NULL 最后;order=questions 按 question_count 降序。"""
    j = await _items(gaps_seed)
    order = [it["representative_question"] for it in j["items"]]
    assert order == [
        f"{_RQ_PREFIX}-A 电池续航?",
        f"{_RQ_PREFIX}-B PoE 支持?",
        f"{_RQ_PREFIX}-C APN 配置?",
    ]

    j = await _items(gaps_seed, "?order=questions")
    counts = [it["question_count"] for it in j["items"]]
    assert counts == sorted(counts, reverse=True)

    j = await _items(gaps_seed, "?size=2&page=2")
    assert j["total"] == 3
    assert j["page"] == 2
    assert len(j["items"]) == 1


async def test_answer_gaps_summary_counts(gaps_seed):
    j = await _items(gaps_seed)
    assert j["miss_type_summary"]["reject"] == 1
    assert j["miss_type_summary"]["召回空"] == 1
    assert j["miss_type_summary"]["未分类"] == 1


async def test_answer_gap_conversations_subresource(gaps_seed):
    """聚类归属会话证据:仅本聚类会话,含 question/is_answered/created_at。"""
    j = await _items(gaps_seed)
    a = _by_rq(j, "A")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            f"/api/admin/tech/answer-gaps/{a['id']}/conversations", headers=gaps_seed
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert all(it["is_answered"] is False for it in body["items"])
    times = [it["created_at"] for it in body["items"]]
    assert times == sorted(times, reverse=True)


async def test_answer_gap_conversations_404_unknown(gaps_seed):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            f"/api/admin/tech/answer-gaps/{uuid.uuid4()}/conversations", headers=gaps_seed
        )
    assert resp.status_code == 404


async def test_answer_gaps_requires_auth():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/admin/tech/answer-gaps")
    assert resp.status_code == 401


async def test_answer_gaps_get_only(gaps_seed):
    """只读投影:POST 被拒绝(405),无任何 mutation 面。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/admin/tech/answer-gaps", headers=gaps_seed)
    assert resp.status_code == 405
