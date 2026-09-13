"""Track F 证据聚合端点测试(RED→GREEN)— U-17/U-18/U-19。

冻结合同(track-f-contract.md / matrix-TI TI-12/TI-27/TI-33 / remediation
plan §3.5 IF-7 跨轨衔接):

- U-17(TI-27)GET /tech/answer-gaps/{gap_id}/users:
  定义 = 所选分析窗内去重的伪匿名会话(conversations.session_id,零姓名/
  邮箱/IP,隐私保持聚合 DISTINCT 计数投影);窗口词表 = IF-7 全词表
  (today/7d/30d/all + 显式起止 from/to);历史行 session_id NULL →
  身份真值不足 → 诚实 unavailable(不得编造计数);无会话证据 → 0
  (空集去重真值,非编造)。
- U-18(TI-33)GET /tech/answer-gaps/{gap_id}/sources:
  归因必须派生自真实证据链 —— gap 归属会话的引用真值(conversations.sources)
  与数据源身份 (type, product) 匹配;零前端猜测;无匹配 → 诚实空 +
  unmatched 明细(可解释);只读投影,零新持久化。
- U-19(TI-12)GET /tech/answer-gaps/{gap_id}/topic:
  确定性主题派生(backend/services/gap_topic.py,纯函数),同簇多次
  拉取稳定不变;不可派生 → topic=null(UI 回退代表问句)。

只读(GET-only)、RBAC 不变(viewer+,未认证 401)、未知 gap → 404。
测试库隔离:固定 UUID 段(0xF000...) + 代表问句/源 ID 前缀清理(WFEV/wf-)。
"""

import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import Conversation, DataSource, QuestionCluster, User
from backend.main import app

pytestmark = pytest.mark.asyncio(loop_scope="session")

_USER_EMAIL = "wf-evidence@test.com"
_RQ_PREFIX = "WFEV"
_DS_PREFIX = "wf-ev-"

_NOW = datetime.now(UTC)


def _uid(i: int) -> uuid.UUID:
    return uuid.UUID(int=(0xF0000000000040008000000000000000 + i))


async def _cleanup(factory):
    async with factory() as session:
        # 固定 UUID 段清理(0xF000...):不依赖代表问句前缀,幂等可重入
        ids = [str(_uid(i)) for i in range(1, 8)]
        await session.execute(delete(Conversation).where(Conversation.cluster_id.in_(ids)))
        await session.execute(delete(QuestionCluster).where(QuestionCluster.id.in_(ids)))
        rows = (
            await session.execute(
                select(QuestionCluster).where(
                    QuestionCluster.representative_question.like(f"{_RQ_PREFIX}%")
                )
            )
        ).scalars().all()
        if rows:
            rids = [str(r.id) for r in rows]
            await session.execute(delete(Conversation).where(Conversation.cluster_id.in_(rids)))
            await session.execute(delete(QuestionCluster).where(QuestionCluster.id.in_(rids)))
        await session.execute(delete(DataSource).where(DataSource.id.like(f"{_DS_PREFIX}%")))
        await session.execute(delete(User).where(User.email == _USER_EMAIL))
        await session.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def evidence_seed():
    """seed:覆盖 U-17/U-18/U-19 关键形状的 4 个 gap 聚类 + 数据源。

    - U_OPEN(open):4 条归属会话 / 3 个不同 session_id(同会话复访×2),
      全部含身份 → 去重权威计数 = 3;会话跨窗分布(今日/7d 内/30d 内/40d 外);
      引用 woocommerce/ne101(+一条 github/ne999 无主引用)。
    - U_LEGACY(open):2 条归属会话,session_id 全 NULL(历史行)→
      身份真值不足 → 诚实 unavailable。
    - U_MIXED(open):1 条有身份 + 1 条 NULL → 部分真值不足 → unavailable。
    - U_EMPTY(open):0 条归属会话 → users=0(空集真值)/ topic 单问句 None。
    - U_TOPIC(open):3 条不同问句共享 NE101/PoE 公共因子 → 确定性主题。
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

        id_open, id_legacy, id_mixed, id_empty, id_topic = (
            _uid(1),
            _uid(2),
            _uid(3),
            _uid(4),
            _uid(5),
        )

        session.add(
            QuestionCluster(
                id=id_open,
                cluster_type="gap",
                representative_question=f"{_RQ_PREFIX}-open NE101 是否支持 PoE",
                sample_questions=[
                    f"{_RQ_PREFIX}-open NE101 是否支持 PoE",
                    "NE101 PoE 标准是什么",
                    "NE101 PoE 最大功率是多少",
                ],
                question_count=7,
                status="open",
            )
        )
        session.add(
            QuestionCluster(
                id=id_legacy,
                cluster_type="gap",
                representative_question=f"{_RQ_PREFIX}-legacy 电池续航",
                sample_questions=[f"{_RQ_PREFIX}-legacy 电池续航", "续航多久"],
                question_count=4,
                status="open",
            )
        )
        session.add(
            QuestionCluster(
                id=id_mixed,
                cluster_type="gap",
                representative_question=f"{_RQ_PREFIX}-mixed APN 配置",
                sample_questions=[f"{_RQ_PREFIX}-mixed APN 配置", "APN 怎么设"],
                question_count=2,
                status="open",
            )
        )
        session.add(
            QuestionCluster(
                id=id_empty,
                cluster_type="gap",
                representative_question=f"{_RQ_PREFIX}-empty 固件升级",
                sample_questions=[f"{_RQ_PREFIX}-empty 固件升级"],
                question_count=1,
                status="open",
            )
        )
        session.add(
            QuestionCluster(
                id=id_topic,
                cluster_type="gap",
                representative_question="NE101 支持哪些 PoE 标准",
                sample_questions=["NE101 的 PoE 标准是什么", "NE101 PoE 标准与功率"],
                question_count=3,
                status="open",
            )
        )
        await session.flush()

        cid = str(id_open)
        # U_OPEN:4 条会话 / 3 个不同 session_id(sess-a 复访 ×2);时间跨窗分布
        session.add(
            Conversation(
                question=f"{_RQ_PREFIX}-open NE101 是否支持 PoE",
                is_answered=False,
                cluster_id=cid,
                session_id="sess-a",
                sources=[{"url": "https://store.example/p/1", "title": "P1", "type": "woocommerce", "product": "ne101"}],
                created_at=_NOW - timedelta(minutes=30),
            )
        )
        session.add(
            Conversation(
                question="NE101 PoE 标准是什么",
                is_answered=False,
                cluster_id=cid,
                session_id="sess-a",
                sources=[{"url": "https://store.example/p/2", "title": "P2", "type": "woocommerce", "product": "ne101"}],
                created_at=_NOW - timedelta(hours=2),
            )
        )
        session.add(
            Conversation(
                question="NE101 PoE 最大功率是多少",
                is_answered=True,
                cluster_id=cid,
                session_id="sess-b",
                sources=[
                    {"url": "https://github.com/x/y", "title": "Y", "type": "github", "product": "ne999"},
                    {"url": "https://s.example/c/1", "title": "案例", "type": "filesystem", "product": "knowledge"},
                ],
                created_at=_NOW - timedelta(days=3),
            )
        )
        session.add(
            Conversation(
                question="NE101 PoE 供电距离",
                is_answered=True,
                cluster_id=cid,
                session_id="sess-c",
                sources=[{"url": "https://store.example/p/3", "title": "P3", "type": "woocommerce", "product": "ne101"}],
                created_at=_NOW - timedelta(days=10),
            )
        )
        # 40 天前会话(all 可见 / 30d 窗外;引用 woocommerce/ne101)
        session.add(
            Conversation(
                question="NE101 PoE 老款兼容",
                is_answered=True,
                cluster_id=cid,
                session_id="sess-d",
                sources=[{"url": "https://store.example/p/4", "title": "P4", "type": "woocommerce", "product": "ne101"}],
                created_at=_NOW - timedelta(days=40),
            )
        )

        # U_LEGACY:2 条历史行,session_id 全 NULL
        session.add(
            Conversation(
                question=f"{_RQ_PREFIX}-legacy 电池续航",
                is_answered=False,
                cluster_id=str(id_legacy),
                session_id=None,
                sources=[],
                created_at=_NOW - timedelta(hours=5),
            )
        )
        session.add(
            Conversation(
                question="续航多久",
                is_answered=False,
                cluster_id=str(id_legacy),
                session_id=None,
                sources=[],
                created_at=_NOW - timedelta(hours=1),
            )
        )

        # U_MIXED:1 条有身份 + 1 条 NULL(部分真值不足)
        session.add(
            Conversation(
                question=f"{_RQ_PREFIX}-mixed APN 配置",
                is_answered=False,
                cluster_id=str(id_mixed),
                session_id="sess-m",
                sources=[],
                created_at=_NOW - timedelta(hours=6),
            )
        )
        session.add(
            Conversation(
                question="APN 怎么设",
                is_answered=False,
                cluster_id=str(id_mixed),
                session_id=None,
                sources=[],
                created_at=_NOW - timedelta(hours=2),
            )
        )

        # 数据源:woocommerce/ne101(归因命中) + github/ne101(同身份第二行)
        session.add(
            DataSource(
                id=f"{_DS_PREFIX}woo-ne101",
                type="woocommerce",
                product="ne101",
                enabled=True,
                config={"store_url": "https://store.example"},
            )
        )
        session.add(
            DataSource(
                id=f"{_DS_PREFIX}woo-ne101-b",
                type="woocommerce",
                product="ne101",
                enabled=False,
                config={"store_url": "https://store2.example"},
            )
        )
        await session.commit()

    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}
    await _cleanup(factory)


async def _get(headers, path: str):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/admin/tech/answer-gaps/{path}", headers=headers)
    return resp


def _gap_id(i: int) -> str:
    return str(_uid(i))


# ==========================================================================
# U-17 用户去重聚合(伪匿名会话;隐私保持聚合)
# ==========================================================================


async def test_users_dedup_authoritative_count(evidence_seed):
    """全部会话含身份 → 去重 DISTINCT 计数 = 权威值(3 个会话/4 条对话)。"""
    resp = await _get(evidence_seed, f"{_gap_id(1)}/users?window=all")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["conversations_in_window"] == 5
    assert body["conversations_with_session_identity"] == 5
    assert body["conversations_without_session_identity"] == 0
    assert body["distinct_sessions"] == 4
    assert body["users"] == 4
    assert body["users_available"] is True
    assert body["unavailable_reason"] is None
    # 隐私:聚合投影不外泄任何 session_id 原值
    assert "sess-" not in resp.text


async def test_users_window_7d_and_30d_filtering(evidence_seed):
    """聚合窗=所选分析窗(IF-7):7d/30d 去重计数随窗真实变化。"""
    resp_7d = await _get(evidence_seed, f"{_gap_id(1)}/users?window=7d")
    assert resp_7d.status_code == 200
    body_7d = resp_7d.json()
    # 7d 内:30min/2h/3d 三条会话(sess-a、sess-b);10d/40d 窗外
    assert body_7d["conversations_in_window"] == 3
    assert body_7d["users"] == 2

    resp_30d = await _get(evidence_seed, f"{_gap_id(1)}/users?window=30d")
    body_30d = resp_30d.json()
    # 30d 内:+10d 会话(sess-c);40d 仍窗外
    assert body_30d["conversations_in_window"] == 4
    assert body_30d["users"] == 3


async def test_users_window_today(evidence_seed):
    """today 预设:仅今日(UTC 零点起)会话计入。"""
    resp = await _get(evidence_seed, f"{_gap_id(1)}/users?window=today")
    assert resp.status_code == 200
    body = resp.json()
    # 今日窗内:30min 一条(sess-a);2h 可能在昨日(UTC 界)——断言不早于全窗
    assert body["conversations_in_window"] >= 1
    assert body["conversations_in_window"] <= 2
    assert body["users_available"] is True
    assert body["users"] == body["distinct_sessions"]


async def test_users_explicit_from_to_range(evidence_seed):
    """显式起止(from/to):ISO 起止过滤聚合窗。"""
    frm = quote((_NOW - timedelta(days=5)).isoformat(), safe="")
    to = quote((_NOW + timedelta(hours=1)).isoformat(), safe="")
    resp = await _get(
        evidence_seed,
        f"{_gap_id(1)}/users?window=all&from={frm}&to={to}",
    )
    assert resp.status_code == 200
    body = resp.json()
    # [now-5d, now]:30min/2h/3d 三条
    assert body["conversations_in_window"] == 3
    assert body["users"] == 2


async def test_users_explicit_from_only(evidence_seed):
    frm = quote((_NOW - timedelta(days=15)).isoformat(), safe="")
    resp = await _get(evidence_seed, f"{_gap_id(1)}/users?from={frm}")
    assert resp.status_code == 200
    body = resp.json()
    # now-15d 起:30min/2h/3d/10d 四条(sess-a/b/c)
    assert body["conversations_in_window"] == 4
    assert body["users"] == 3


async def test_users_null_identity_honest_unavailable(evidence_seed):
    """历史行 session_id 全 NULL → 身份真值不足 → 诚实 unavailable,禁编造。"""
    resp = await _get(evidence_seed, f"{_gap_id(2)}/users?window=all")
    assert resp.status_code == 200
    body = resp.json()
    assert body["conversations_in_window"] == 2
    assert body["conversations_without_session_identity"] == 2
    assert body["distinct_sessions"] == 0
    assert body["users"] is None
    assert body["users_available"] is False
    assert body["unavailable_reason"] == "session_identity_insufficient"


async def test_users_partial_identity_honest_unavailable(evidence_seed):
    """部分会话缺身份 → 去重计数是下界,不得伪称权威 → unavailable。"""
    resp = await _get(evidence_seed, f"{_gap_id(3)}/users?window=all")
    assert resp.status_code == 200
    body = resp.json()
    assert body["conversations_in_window"] == 2
    assert body["conversations_with_session_identity"] == 1
    assert body["conversations_without_session_identity"] == 1
    assert body["users"] is None
    assert body["users_available"] is False
    assert body["unavailable_reason"] == "session_identity_insufficient"


async def test_users_zero_conversations_true_zero(evidence_seed):
    """无归属会话 → 空集去重真值 0(非编造、非 unavailable)。"""
    resp = await _get(evidence_seed, f"{_gap_id(4)}/users?window=all")
    assert resp.status_code == 200
    body = resp.json()
    assert body["conversations_in_window"] == 0
    assert body["users"] == 0
    assert body["users_available"] is True


async def test_users_window_param_validation(evidence_seed):
    """窗口词表外值 → 422(禁静默回退)。"""
    resp = await _get(evidence_seed, f"{_gap_id(1)}/users?window=90d")
    assert resp.status_code == 422


async def test_users_unknown_gap_404(evidence_seed):
    resp = await _get(evidence_seed, f"{uuid.uuid4()}/users")
    assert resp.status_code == 404


# ==========================================================================
# U-18 gap→源归因(引用真值 × 数据源身份匹配;零前端猜测)
# ==========================================================================


async def test_sources_attribution_identity_match(evidence_seed):
    """归因=会话引用真值 (type,product) 与数据源身份匹配;证据规则可解释。"""
    resp = await _get(evidence_seed, f"{_gap_id(1)}/sources")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["conversations_total"] == 5
    # 引用会话:5 条均含公开引用
    assert body["citing_conversations_total"] == 5

    items = body["items"]
    # woocommerce/ne101:两条同身份源行全部命中(均为真实候选证据身份)
    woo = [it for it in items if it["source_type"] == "woocommerce"]
    assert {it["source_id"] for it in woo} == {
        f"{_DS_PREFIX}woo-ne101",
        f"{_DS_PREFIX}woo-ne101-b",
    }
    for it in woo:
        assert it["product"] == "ne101"
        # 4 条会话引用了 woocommerce/ne101 身份(每会话去重计数)
        assert it["citing_conversations"] == 4
        assert it["evidence_rule"] == "conversation_citation_identity_match"

    # 无主引用(github/ne999、filesystem/knowledge 知识案例)→ 不归因,透明列出
    unmatched = {(u["source_type"], u["product"]) for u in body["unmatched_citations"]}
    assert ("github", "ne999") in unmatched
    assert ("filesystem", "knowledge") in unmatched


async def test_sources_attribution_sorted_deterministic(evidence_seed):
    """多命中按引用会话数降序 + source_id 升序(确定性呈现)。"""
    resp = await _get(evidence_seed, f"{_gap_id(1)}/sources")
    body = resp.json()
    ids = [it["source_id"] for it in body["items"]]
    assert ids == sorted(ids)


async def test_sources_attribution_no_evidence_honest_empty(evidence_seed):
    """无会话/无引用 → 归因诚实为空(不猜)。"""
    resp = await _get(evidence_seed, f"{_gap_id(4)}/sources")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["citing_conversations_total"] == 0
    assert body["conversations_total"] == 0


async def test_sources_unknown_gap_404(evidence_seed):
    resp = await _get(evidence_seed, f"{uuid.uuid4()}/sources")
    assert resp.status_code == 404


# ==========================================================================
# U-19 主题短语投影(确定性派生;稳定性)
# ==========================================================================


async def test_topic_deterministic_projection(evidence_seed):
    resp = await _get(evidence_seed, f"{_gap_id(5)}/topic")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["derivation"] == "cross_question_common_factor"
    # 公共因子:NE101 + PoE(拉丁交集)+ 标准(CJK 极大公共子串)
    assert body["topic"] == "NE101 PoE 标准"
    assert body["fallback"] == "NE101 支持哪些 PoE 标准"


async def test_topic_stability_across_repeated_requests(evidence_seed):
    """同簇多次拉取稳定不变(合同 E2E 验收钩子)。"""
    payload = None
    for _ in range(5):
        resp = await _get(evidence_seed, f"{_gap_id(5)}/topic")
        assert resp.status_code == 200
        body = resp.json()
        if payload is None:
            payload = body
        assert body == payload


async def test_topic_unavailable_honest_null(evidence_seed):
    """单问句簇(无跨问句公共因子)→ topic=null,UI 回退代表问句。"""
    resp = await _get(evidence_seed, f"{_gap_id(4)}/topic")
    assert resp.status_code == 200
    body = resp.json()
    assert body["topic"] is None
    assert body["derivation"] is None
    assert body["fallback"] == f"{_RQ_PREFIX}-empty 固件升级"


async def test_topic_unknown_gap_404(evidence_seed):
    resp = await _get(evidence_seed, f"{uuid.uuid4()}/topic")
    assert resp.status_code == 404


# ==========================================================================
# 只读/RBAC(与既有 /tech 读面纪律一致)
# ==========================================================================


async def test_evidence_requires_auth():
    for suffix in ("users", "sources", "topic"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/admin/tech/answer-gaps/{_gap_id(1)}/{suffix}")
        assert resp.status_code == 401


async def test_evidence_get_only(evidence_seed):
    """只读投影:POST 被拒绝(405),零 mutation 面。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for suffix in ("users", "sources", "topic"):
            resp = await client.post(
                f"/api/admin/tech/answer-gaps/{_gap_id(1)}/{suffix}", headers=evidence_seed
            )
            assert resp.status_code == 405
