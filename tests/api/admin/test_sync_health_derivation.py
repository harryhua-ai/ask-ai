"""⑫ /sync-health 端点集成测试(场景化;读时派生,无 SourceHealthSnapshot)。

场景:
- STALE:同步率高但最近一次成功超出 2×sync_interval;无 run 证据的维度如实 unknown;
- EMPTY_UNEXPECTED:启用 REQUIRED + 零文档 + 从未成功;
- EXCLUDED:禁用源,overlay 不可改写;
- config.expected_state 显式覆盖(DISCOVERY × 0 文档 → EMPTY_EXPECTED)。
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import DataSource, SyncLog, SyncRun, User
from backend.main import app

pytestmark = pytest.mark.asyncio(loop_scope="session")

NOW = datetime.now(UTC)

H_STALE, H_EMPTY, H_OFF = "w2h-stale", "w2h-empty", "w2h-off"


@pytest_asyncio.fixture(scope="session", loop_scope="session", autouse=True)
async def _migrate_columns():
    """共享测试库补 W2 运行时事实列(端点 SELECT sync_runs 全列,先迁移)。"""
    import os

    from backend.config import load_settings
    from backend.db.session import get_engine
    from scripts.migrate_add_sync_run_runtime_facts import migrate

    dsn = os.environ.get("TEST_DATABASE_URL", load_settings().postgres_dsn)
    engine = get_engine(dsn)
    try:
        await migrate(engine)
    finally:
        await engine.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def health_env():
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email="w2health@test.com",
                role="viewer",
                password_hash=hash_password("pass123"),
            )
        )
        # STALE:同步率高但最近一次成功超出 2×1h
        session.add(
            DataSource(
                id=H_STALE, type="github", product="p", enabled=True, config={}, sync_interval="1h"
            )
        )
        # EMPTY_UNEXPECTED:启用 REQUIRED、零文档、从未成功
        session.add(
            DataSource(
                id=H_EMPTY,
                type="web_crawl",
                product="p",
                enabled=True,
                config={},
                sync_interval="24h",
            )
        )
        # EXCLUDED:禁用
        session.add(
            DataSource(
                id=H_OFF, type="github", product="p", enabled=False, config={}, sync_interval="24h"
            )
        )
        for _ in range(3):
            session.add(
                SyncLog(
                    source_id=H_STALE,
                    source_type="github",
                    status="success",
                    finished_at=NOW - timedelta(hours=3),
                    started_at=NOW - timedelta(hours=3),
                )
            )
        await session.commit()
    token = create_access_token(str(user_id), "viewer", app.state.settings.jwt_secret)
    headers = {"Authorization": f"Bearer {token}"}
    yield headers
    async with factory() as session:
        for sid in (H_STALE, H_EMPTY, H_OFF):
            await session.execute(SyncLog.__table__.delete().where(SyncLog.source_id == sid))
            await session.execute(SyncRun.__table__.delete().where(SyncRun.source_id == sid))
            await session.execute(DataSource.__table__.delete().where(DataSource.id == sid))
        await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.commit()


async def test_1_health_endpoint_scenarios(health_env):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/sync-health", headers=health_env)
    assert resp.status_code == 200, resp.text
    items = {i["source_id"]: i for i in resp.json()["items"]}

    stale = items[H_STALE]
    assert stale["overall"] == "STALE"
    assert stale["freshness"]["state"] == "stale"
    assert stale["sync"]["state"] == "healthy"
    assert stale["expected_state"] == "REQUIRED"
    assert stale["connectivity"]["state"] == "unknown"  # 无 run 证据,不猜

    empty = items[H_EMPTY]
    assert empty["overall"] == "EMPTY_UNEXPECTED"
    assert empty["document_count"] == 0

    off = items[H_OFF]
    assert off["overall"] == "EXCLUDED"
    assert off["expected_state"] == "EXCLUDED"

    # 每维五元结构完整
    for dim in ("connectivity", "sync", "coverage", "freshness", "consistency"):
        assert set(stale[dim].keys()) == {"state", "evidence", "as_of"}


async def test_2_health_expected_state_config_override(health_env):
    factory = app.state.session_factory
    async with factory() as session:
        row = (
            await session.execute(select(DataSource).where(DataSource.id == H_EMPTY))
        ).scalar_one()
        row.config = {"expected_state": "DISCOVERY"}
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/sync-health", headers=health_env)
    items = {i["source_id"]: i for i in resp.json()["items"]}
    assert items[H_EMPTY]["expected_state"] == "DISCOVERY"
    # DISCOVERY×0 文档 → EMPTY_EXPECTED
    assert items[H_EMPTY]["overall"] == "EMPTY_EXPECTED"


async def test_3_polluted_facts_drive_action_required(health_env):
    """Correction Gate(#13→#11):账本污染事实 → Consistency degraded → overall ACTION_REQUIRED。

    端到端链路:SyncRun.consistency(#13 facts v2)→ /sync-health 读时派生 →
    既有 overall precedence(consistency==degraded → ACTION_REQUIRED)。
    同源 fresh 成功记录在场,证明升级不依赖 STALE/其他维度。
    """
    factory = app.state.session_factory
    sid = "w2h-polluted"
    async with factory() as session:
        session.add(
            DataSource(
                id=sid, type="github", product="p", enabled=True, config={}, sync_interval="1h"
            )
        )
        session.add(
            SyncLog(
                source_id=sid,
                source_type="github",
                status="success",
                started_at=NOW,
                finished_at=NOW,
            )
        )
        session.add(
            SyncRun(
                source_id=sid,
                status="completed",
                stage="DONE",
                consistency={
                    "missing": 0,
                    "orphan_count": 0,
                    "polluted_artifact_chunks": 3,
                    "repair_required": True,
                    "duplicate_doc_count": 2,
                    "expected_chunks": 10,
                    "actual_chunks": 10,
                },
                started_at=NOW - timedelta(minutes=5),
                finished_at=NOW,
            )
        )
        await session.commit()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/admin/sync-health", headers=health_env)
        assert resp.status_code == 200, resp.text
        item = next(i for i in resp.json()["items"] if i["source_id"] == sid)
        assert item["consistency"]["state"] == "degraded"
        assert "polluted_artifact_chunks=3" in item["consistency"]["evidence"]
        assert item["freshness"]["state"] == "fresh"  # 升级不依赖 STALE
        assert item["overall"] == "ACTION_REQUIRED"
    finally:
        async with factory() as session:
            await session.execute(SyncLog.__table__.delete().where(SyncLog.source_id == sid))
            await session.execute(SyncRun.__table__.delete().where(SyncRun.source_id == sid))
            await session.execute(DataSource.__table__.delete().where(DataSource.id == sid))
            await session.commit()
