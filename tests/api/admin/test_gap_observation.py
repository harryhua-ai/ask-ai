"""V1.6.3 Wave 1 Track E — U-15 观察状态机 OPEN→OBSERVING→RESOLVED 端点测试。

冻结合同(track-e-contract.md / U-15 / IF-1):
- 进入 OBSERVING 三前置:操作者确认修复完成 + 相关源 sync/reindex 成功
  (真实读 sync_runs)+ post-sync 验证成功(sync_runs.consistency 结构化事实);
- 观察窗默认 7 天;OBSERVING 期间同一 gap 证据失败复现 → 回 OPEN;
  满窗无复现 → RESOLVED(评估机制 lazy-on-read / 显式 evaluate,判定必须持久化);
- 操作者可中止 OBSERVING → OPEN;禁止直接手动 RESOLVED;
- 全部转移持久化(gap_observations 元数据 + gap_observation_events 流转事件,
  带时间戳、actor、可审计、History 可见);
- status 词表扩展 observing(GAP_STATUS_PATTERN 消费方零 diff 自动生效)。
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import (
    Conversation,
    DataSource,
    GapExportAudit,
    GapObservation,
    GapObservationEvent,
    QuestionCluster,
    SyncRun,
    User,
)
from backend.main import app

pytestmark = pytest.mark.asyncio(loop_scope="session")

_ADMIN_EMAIL = "we-obs-admin@test.com"
_EDITOR_EMAIL = "we-obs-editor@test.com"
_VIEWER_EMAIL = "we-obs-viewer@test.com"
_RQ_PREFIX = "WEOBS"
# Track E 固定 UUID 段(共享测试库避让;与 B2GAP 0xAAAA 段、D 段互不重叠)
_SEG = 0xEBEB0000000040008000000000000000

_SRC = "we-src-e-obs"  # 相关数据源 id(gap 会话引用 source_id 前缀)

_NOW = datetime(2026, 9, 13, 12, 0, 0, tzinfo=UTC)


def _uid(i: int) -> uuid.UUID:
    return uuid.UUID(int=_SEG + i)


async def _cleanup(factory):
    async with factory() as session:
        clusters = (
            await session.execute(
                select(QuestionCluster).where(
                    QuestionCluster.representative_question.like(f"{_RQ_PREFIX}%")
                )
            )
        ).scalars().all()
        ids = [str(c.id) for c in clusters]
        if ids:
            await session.execute(
                delete(GapObservationEvent).where(GapObservationEvent.cluster_id.in_(ids))
            )
            await session.execute(
                delete(GapExportAudit).where(GapExportAudit.cluster_id.in_(ids))
            )
            await session.execute(
                delete(GapObservation).where(GapObservation.cluster_id.in_(ids))
            )
            await session.execute(delete(Conversation).where(Conversation.cluster_id.in_(ids)))
            await session.execute(
                delete(QuestionCluster).where(QuestionCluster.id.in_([c.id for c in clusters]))
            )
        await session.execute(delete(SyncRun).where(SyncRun.source_id == _SRC))
        await session.execute(delete(DataSource).where(DataSource.id == _SRC))
        await session.execute(delete(User).where(User.email.in_(
            [_ADMIN_EMAIL, _EDITOR_EMAIL, _VIEWER_EMAIL]
        )))
        await session.commit()


@pytest_asyncio.fixture(loop_scope="session")
async def obs_seed():
    """seed:1 个 open gap(2 条未回答会话,引用 _SRC 源)+ 相关源已完成同步
    (latest sync_run:completed + healthy consistency 事实)。"""
    factory = app.state.session_factory
    await _cleanup(factory)
    headers = await _seed_users_real(factory)

    gap_id = _uid(1)
    async with factory() as session:
        session.add(
            DataSource(
                id=_SRC,
                type="wiki",
                product="NE101",
                enabled=True,
                config={},
            )
        )
        session.add(
            SyncRun(
                source_id=_SRC,
                attempt=1,
                triggered_by="cron",
                status="completed",
                consistency={
                    "expected_chunks": 12,
                    "actual_chunks": 12,
                    "missing": 0,
                    "refill": 0,
                    "stale_chunk_count": 0,
                    "orphan_count": 0,
                },
                started_at=_NOW - timedelta(days=1),
                finished_at=_NOW - timedelta(days=1) + timedelta(minutes=9),
            )
        )
        session.add(
            QuestionCluster(
                id=gap_id,
                cluster_type="gap",
                representative_question=f"{_RQ_PREFIX}-A NE101 PoE 支持信息缺失?",
                sample_questions=[f"{_RQ_PREFIX}-A NE101 是否支持 PoE?"],
                question_count=3,
                status="open",
            )
        )
        await session.flush()
        for i, (q, hrs) in enumerate(
            [("NE101 是否支持 PoE?", 3), ("PoE 供电上限是多少?", 2)]
        ):
            session.add(
                Conversation(
                    question=q,
                    is_answered=False,
                    cluster_id=str(gap_id),
                    sources=[
                        {"source_id": f"{_SRC}/doc-{i}", "title": f"NE101 手册 {i}", "url": ""}
                    ],
                    session_id=f"sess-we-{i}",
                    country="US",
                    created_at=_NOW - timedelta(hours=hrs),
                )
            )
        await session.commit()

    yield {"headers": headers, "gap_id": str(gap_id)}
    await _cleanup(factory)


async def _seed_users_real(factory) -> dict[str, str]:
    """seed 三角色并以 user_id 为 subject 签发 token(get_current_user 按 id 查库)。"""
    ids: dict[str, uuid.UUID] = {}
    async with factory() as session:
        for email, role in (
            (_ADMIN_EMAIL, "admin"),
            (_EDITOR_EMAIL, "editor"),
            (_VIEWER_EMAIL, "viewer"),
        ):
            uid = uuid.uuid4()
            ids[role] = uid
            session.add(
                User(
                    id=uid,
                    email=email,
                    role=role,
                    password_hash=hash_password("pass"),
                )
            )
        await session.commit()
    secret = app.state.settings.jwt_secret
    return {
        role: {"Authorization": f"Bearer {create_access_token(str(uid), role, secret)}"}
        for role, uid in ids.items()
    }


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _start_url(gap_id: str) -> str:
    return f"/api/admin/tech/answer-gaps/{gap_id}/observation/start"


def _abort_url(gap_id: str) -> str:
    return f"/api/admin/tech/answer-gaps/{gap_id}/observation/abort"


def _obs_url(gap_id: str) -> str:
    return f"/api/admin/tech/answer-gaps/{gap_id}/observation"


def _events_url(gap_id: str) -> str:
    return f"/api/admin/tech/answer-gaps/{gap_id}/observation/events"


_EVALUATE_URL = "/api/admin/tech/answer-gaps/observation/evaluate"


async def _db_gap(session_or_factory, gap_id: str) -> QuestionCluster:
    """读取 gap 聚类。传入活跃 session 时复用之(变更随调用方 commit 持久化);
    传入 factory 时开新 session(只读断言用)。"""
    if isinstance(session_or_factory, async_sessionmaker):
        async with session_or_factory() as session:
            return await _db_gap(session, gap_id)
    session = session_or_factory
    return (
        await session.execute(
            select(QuestionCluster).where(QuestionCluster.id == uuid.UUID(gap_id))
        )
    ).scalar_one()


# --------------------------------------------------------------------------- #
# 三前置门(进入 OBSERVING)
# --------------------------------------------------------------------------- #


async def test_start_requires_operator_confirmation(obs_seed):
    """前置①:未携带操作者确认(confirmed=false/缺省)→ 409,状态保持 open。"""
    headers, gap_id = obs_seed["headers"], obs_seed["gap_id"]
    async with _client() as client:
        resp = await client.post(
            _start_url(gap_id), json={"confirmed": False}, headers=headers["admin"]
        )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "gate_failed"
    assert resp.json()["detail"]["gates"]["confirmation"] is False
    assert (await _db_gap(app.state.session_factory, gap_id)).status == "open"


async def test_start_requires_related_source_sync_success(obs_seed):
    """前置②:相关源 sync/reindex 成功(真实读 sync_runs)。
    latest run=failed → 409 gate_failed;无任何 run → 409 no_sync_evidence。"""
    factory = app.state.session_factory
    headers, gap_id = obs_seed["headers"], obs_seed["gap_id"]
    # 把唯一 completed run 改为 failed
    async with factory() as session:
        run = (
            await session.execute(select(SyncRun).where(SyncRun.source_id == _SRC))
        ).scalar_one()
        run.status = "failed"
        await session.commit()
    async with _client() as client:
        resp = await client.post(
            _start_url(gap_id), json={"confirmed": True}, headers=headers["admin"]
        )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["code"] == "gate_failed"
    assert detail["gates"]["sync"][_SRC] == "last_sync_not_completed"

    # 无任何 run → no_sync_evidence
    async with factory() as session:
        await session.execute(delete(SyncRun).where(SyncRun.source_id == _SRC))
        await session.commit()
    async with _client() as client:
        resp = await client.post(
            _start_url(gap_id), json={"confirmed": True}, headers=headers["admin"]
        )
    assert resp.status_code == 409
    assert resp.json()["detail"]["gates"]["sync"][_SRC] == "no_sync_evidence"
    assert (await _db_gap(factory, gap_id)).status == "open"


async def test_start_requires_post_sync_verification_healthy(obs_seed):
    """前置③:post-sync 验证成功 = latest completed run 的 consistency 结构化
    事实存在且健康(missing=0/refill=0/orphan=0);NULL=未知 → 拒绝(不推断)。"""
    factory = app.state.session_factory
    headers, gap_id = obs_seed["headers"], obs_seed["gap_id"]
    async with factory() as session:
        run = (
            await session.execute(select(SyncRun).where(SyncRun.source_id == _SRC))
        ).scalar_one()
        run.consistency = {"expected_chunks": 12, "actual_chunks": 9, "missing": 3,
                           "refill": 3, "stale_chunk_count": 0, "orphan_count": 0}
        await session.commit()
    async with _client() as client:
        resp = await client.post(
            _start_url(gap_id), json={"confirmed": True}, headers=headers["admin"]
        )
    assert resp.status_code == 409
    assert resp.json()["detail"]["gates"]["verification"][_SRC] == "consistency_unhealthy"

    async with factory() as session:
        run = (
            await session.execute(select(SyncRun).where(SyncRun.source_id == _SRC))
        ).scalar_one()
        run.consistency = None
        await session.commit()
    async with _client() as client:
        resp = await client.post(
            _start_url(gap_id), json={"confirmed": True}, headers=headers["admin"]
        )
    assert resp.status_code == 409
    assert resp.json()["detail"]["gates"]["verification"][_SRC] == "no_consistency_evidence"


async def test_start_success_transitions_to_observing_persisted(obs_seed):
    """三前置全过 → open→observing;gap_observations 元数据 + start 流转事件
    (带时间戳/actor/from→to)持久化。"""
    factory = app.state.session_factory
    headers, gap_id = obs_seed["headers"], obs_seed["gap_id"]
    async with _client() as client:
        resp = await client.post(
            _start_url(gap_id), json={"confirmed": True}, headers=headers["admin"]
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "observing"
    assert body["observation"]["window_days"] == 7
    assert body["observation"]["ended_at"] is None

    async with factory() as session:
        cluster = await _db_gap(factory, gap_id)
        assert cluster.status == "observing"
        obs = (
            await session.execute(
                select(GapObservation).where(
                    GapObservation.cluster_id == uuid.UUID(gap_id),
                    GapObservation.is_active.is_(True),
                )
            )
        ).scalar_one()
        assert obs.window_days == 7
        assert obs.ended_at is None
        ev = (
            await session.execute(
                select(GapObservationEvent)
                .where(
                    GapObservationEvent.cluster_id == uuid.UUID(gap_id),
                    GapObservationEvent.event_type == "start",
                )
                .order_by(GapObservationEvent.created_at.desc())
            )
        ).scalars().first()
        assert ev is not None
        assert ev.from_status == "open"
        assert ev.to_status == "observing"
        assert ev.actor == _ADMIN_EMAIL
        assert ev.created_at is not None


async def test_start_rejected_from_non_open_states(obs_seed):
    """状态机:仅 OPEN 可进 OBSERVING;重复 start → 409。"""
    headers, gap_id = obs_seed["headers"], obs_seed["gap_id"]
    async with _client() as client:
        ok = await client.post(
            _start_url(gap_id), json={"confirmed": True}, headers=headers["admin"]
        )
        assert ok.status_code == 200
        again = await client.post(
            _start_url(gap_id), json={"confirmed": True}, headers=headers["admin"]
        )
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "invalid_state"


# --------------------------------------------------------------------------- #
# 观察期评估:复现回 OPEN / 满窗转 RESOLVED / 中止→OPEN(判定全部持久化)
# --------------------------------------------------------------------------- #


def _mk_obs_row(gap_id: str, started_at: datetime) -> GapObservation:
    return GapObservation(
        cluster_id=uuid.UUID(gap_id),
        started_at=started_at,
        window_days=7,
        window_ends_at=started_at + timedelta(days=7),
        is_active=True,
    )


async def _age_base_evidence(factory, gap_id: str, hours_ago: int) -> None:
    """把基础归属会话证据挪到 started_at 之前(真实时间线:观察开始于
    既有失败证据之后;窗口评估只关心 started_at 之后的新增证据)。"""
    from sqlalchemy import update

    async with factory() as session:
        await session.execute(
            update(Conversation)
            .where(Conversation.cluster_id == gap_id)
            .values(created_at=_NOW - timedelta(hours=hours_ago))
        )
        await session.commit()


async def test_recurrence_returns_gap_to_open(obs_seed):
    """OBSERVING 期间同一 gap 证据失败复现(归属会话新增于 started_at 之后)
    → 评估回 OPEN + recurrence 事件持久化。"""
    factory = app.state.session_factory
    headers, gap_id = obs_seed["headers"], obs_seed["gap_id"]
    started = _NOW - timedelta(hours=1)
    await _age_base_evidence(factory, gap_id, hours_ago=3)
    async with factory() as session:
        cluster = await _db_gap(session, gap_id)
        cluster.status = "observing"
        session.add(_mk_obs_row(gap_id, started))
        # 复现证据:观察开始后新归属的失败会话
        session.add(
            Conversation(
                question="PoE 还是不能用了?",
                is_answered=False,
                cluster_id=gap_id,
                created_at=_NOW - timedelta(minutes=30),
            )
        )
        await session.commit()

    async with _client() as client:
        resp = await client.post(_EVALUATE_URL, headers=headers["admin"])
    assert resp.status_code == 200, resp.text
    transitions = resp.json()["transitions"]
    assert any(t["gap_id"] == gap_id and t["to_status"] == "open" for t in transitions)
    assert (
        await _db_gap(factory, gap_id)
    ).status == "open"
    async with factory() as session:
        obs = (
            await session.execute(
                select(GapObservation).where(
                    GapObservation.cluster_id == uuid.UUID(gap_id),
                    GapObservation.is_active.is_(False),
                )
            )
        ).scalar_one()
        assert obs.ended_reason == "recurrence"
        ev = (
            await session.execute(
                select(GapObservationEvent).where(
                    GapObservationEvent.cluster_id == uuid.UUID(gap_id),
                    GapObservationEvent.event_type == "recurrence",
                )
            )
        ).scalar_one()
        assert ev.to_status == "open"
        assert ev.detail["new_evidence_count"] == 1


async def test_window_elapsed_without_recurrence_resolves(obs_seed):
    """满窗(7 天)无复现 → 评估转 RESOLVED + resolve 事件持久化
    (唯一的 RESOLVED 进入路径;判定持久化,非内存推导)。"""
    factory = app.state.session_factory
    headers, gap_id = obs_seed["headers"], obs_seed["gap_id"]
    started = _NOW - timedelta(days=8)
    await _age_base_evidence(factory, gap_id, hours_ago=24 * 9)
    async with factory() as session:
        cluster = await _db_gap(session, gap_id)
        cluster.status = "observing"
        session.add(_mk_obs_row(gap_id, started))
        await session.commit()

    async with _client() as client:
        resp = await client.post(_EVALUATE_URL, headers=headers["admin"])
    assert resp.status_code == 200
    transitions = resp.json()["transitions"]
    assert any(t["gap_id"] == gap_id and t["to_status"] == "resolved" for t in transitions)

    async with factory() as session:
        assert (await _db_gap(factory, gap_id)).status == "resolved"
        obs = (
            await session.execute(
                select(GapObservation).where(
                    GapObservation.cluster_id == uuid.UUID(gap_id),
                    GapObservation.is_active.is_(False),
                )
            )
        ).scalar_one()
        assert obs.ended_reason == "window_elapsed"
        ev = (
            await session.execute(
                select(GapObservationEvent).where(
                    GapObservationEvent.cluster_id == uuid.UUID(gap_id),
                    GapObservationEvent.event_type == "resolve",
                )
            )
        ).scalar_one()
        assert ev.from_status == "observing"
        assert ev.to_status == "resolved"


async def test_window_not_elapsed_no_recurrence_noop(obs_seed):
    """窗内无复现 → 评估不转移(observing 保持)。"""
    factory = app.state.session_factory
    headers, gap_id = obs_seed["headers"], obs_seed["gap_id"]
    await _age_base_evidence(factory, gap_id, hours_ago=25)
    async with factory() as session:
        cluster = await _db_gap(session, gap_id)
        cluster.status = "observing"
        session.add(_mk_obs_row(gap_id, _NOW - timedelta(days=1)))
        await session.commit()

    async with _client() as client:
        resp = await client.post(_EVALUATE_URL, headers=headers["admin"])
    assert resp.status_code == 200
    assert resp.json()["transitions"] == []
    assert (await _db_gap(factory, gap_id)).status == "observing"


async def test_abort_returns_to_open(obs_seed):
    """操作者中止 OBSERVING → OPEN(非 resolved)+ abort 事件持久化。"""
    factory = app.state.session_factory
    headers, gap_id = obs_seed["headers"], obs_seed["gap_id"]
    async with factory() as session:
        cluster = await _db_gap(session, gap_id)
        cluster.status = "observing"
        session.add(_mk_obs_row(gap_id, _NOW - timedelta(days=2)))
        await session.commit()

    async with _client() as client:
        resp = await client.post(_abort_url(gap_id), headers=headers["editor"])
    assert resp.status_code == 200
    assert resp.json()["status"] == "open"

    async with factory() as session:
        assert (await _db_gap(factory, gap_id)).status == "open"
        obs = (
            await session.execute(
                select(GapObservation).where(
                    GapObservation.cluster_id == uuid.UUID(gap_id),
                    GapObservation.is_active.is_(False),
                )
            )
        ).scalar_one()
        assert obs.ended_reason == "aborted"
        ev = (
            await session.execute(
                select(GapObservationEvent).where(
                    GapObservationEvent.cluster_id == uuid.UUID(gap_id),
                    GapObservationEvent.event_type == "abort",
                )
            )
        ).scalar_one()
        assert ev.actor == _EDITOR_EMAIL
        assert ev.to_status == "open"


async def test_abort_rejected_when_not_observing(obs_seed):
    headers, gap_id = obs_seed["headers"], obs_seed["gap_id"]
    async with _client() as client:
        resp = await client.post(_abort_url(gap_id), headers=headers["admin"])
    assert resp.status_code == 409


async def test_no_direct_manual_resolve_path(obs_seed):
    """禁止直接手动 RESOLVED:OpenAPI 无任何 answer-gaps resolve 端点;
    既有 gap 写面无 PATCH/PUT;唯一 RESOLVED 进入路径 = 满窗评估。"""
    headers, gap_id = obs_seed["headers"], obs_seed["gap_id"]
    async with _client() as client:
        spec = (await client.get("/openapi.json")).json()
        resolve_paths = [
            p for p in spec["paths"]
            if p.startswith("/api/admin/tech/answer-gaps") and "resolve" in p.lower()
        ]
        assert resolve_paths == []
        for method in ("patch", "put"):
            resp = await client.request(
                method, f"/api/admin/tech/answer-gaps/{gap_id}", headers=headers["admin"]
            )
            assert resp.status_code in (404, 405)


# --------------------------------------------------------------------------- #
# 读面:lazy 评估持久化 + History 事件投影
# --------------------------------------------------------------------------- #


async def test_observation_read_lazy_evaluates_and_persists(obs_seed):
    """lazy-on-read:GET observation 对满窗 observing 聚类评估并持久化
    RESOLVED 判定(读 = 权威评估机制之一)。"""
    factory = app.state.session_factory
    headers, gap_id = obs_seed["headers"], obs_seed["gap_id"]
    await _age_base_evidence(factory, gap_id, hours_ago=24 * 10)
    async with factory() as session:
        cluster = await _db_gap(session, gap_id)
        cluster.status = "observing"
        session.add(_mk_obs_row(gap_id, _NOW - timedelta(days=9)))
        await session.commit()

    async with _client() as client:
        resp = await client.get(_obs_url(gap_id), headers=headers["viewer"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "resolved"
    assert body["observation"]["ended_reason"] == "window_elapsed"
    assert (await _db_gap(factory, gap_id)).status == "resolved"


async def test_events_history_projection(obs_seed):
    """流转事件全量可读(时间升序;History Tab 数据源):
    start → abort 两段历史,均带时间戳与 actor。"""
    headers, gap_id = obs_seed["headers"], obs_seed["gap_id"]
    async with _client() as client:
        r1 = await client.post(
            _start_url(gap_id), json={"confirmed": True}, headers=headers["admin"]
        )
        assert r1.status_code == 200
        r2 = await client.post(_abort_url(gap_id), headers=headers["admin"])
        assert r2.status_code == 200
        resp = await client.get(_events_url(gap_id), headers=headers["viewer"])
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert [ev["event_type"] for ev in items] == ["start", "abort"]
    assert items[0]["from_status"] == "open" and items[0]["to_status"] == "observing"
    assert items[1]["to_status"] == "open"
    assert all(ev["actor"] == _ADMIN_EMAIL for ev in items)
    assert all(ev["created_at"] for ev in items)


async def test_observation_404_unknown_gap(obs_seed):
    headers = obs_seed["headers"]
    async with _client() as client:
        resp = await client.get(
            _obs_url(str(uuid.uuid4())), headers=headers["admin"]
        )
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# RBAC
# --------------------------------------------------------------------------- #


async def test_observation_rbac(obs_seed):
    """转移命令 = 操作者(admin/editor);viewer 只读 403;未认证 401;
    读面 viewer+ 可访问(History 面与侧板一致)。"""
    headers, gap_id = obs_seed["headers"], obs_seed["gap_id"]
    async with _client() as client:
        assert (
            await client.post(_start_url(gap_id), headers=headers["viewer"])
        ).status_code == 403
        assert (
            await client.post(_start_url(gap_id), json={"confirmed": True})
        ).status_code == 401
        assert (
            await client.post(_EVALUATE_URL, headers=headers["viewer"])
        ).status_code == 403
        # editor 可执行操作者转移
        ok = await client.post(
            _start_url(gap_id), json={"confirmed": True}, headers=headers["editor"]
        )
        assert ok.status_code == 200
        assert (
            await client.get(_obs_url(gap_id), headers=headers["viewer"])
        ).status_code == 200
        assert (
            await client.get(_events_url(gap_id), headers=headers["viewer"])
        ).status_code == 200


# --------------------------------------------------------------------------- #
# IF-1 词表贯通:既有投影 status 过滤零 diff 接受 observing
# --------------------------------------------------------------------------- #


async def test_answer_gaps_projection_accepts_observing_filter(obs_seed):
    """GET /tech/answer-gaps?status=observing 经 gap_status 词表扩展零 diff
    返回观察中聚类(GAP_STATUS_PATTERN 消费方自动生效)。"""
    factory = app.state.session_factory
    headers, gap_id = obs_seed["headers"], obs_seed["gap_id"]
    async with factory() as session:
        cluster = await _db_gap(session, gap_id)
        cluster.status = "observing"
        await session.commit()
    async with _client() as client:
        resp = await client.get(
            "/api/admin/tech/answer-gaps?status=observing", headers=headers["viewer"]
        )
    assert resp.status_code == 200
    items = [it for it in resp.json()["items"] if it["id"] == gap_id]
    assert len(items) == 1
    assert items[0]["status"] == "observing"
