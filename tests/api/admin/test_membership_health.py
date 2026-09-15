"""#71 Authoritative-currency truth — Admin health API acceptance tests.

Requirements 10-12:

- Admin reads PERSISTED reconciliation truth (no live enumeration to render);
- sources with unresolved membership drift must not present as healthy;
- PG↔Weaviate consistency stays a separate dimension.
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import DataSource, SyncLog, User
from backend.main import app

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(scope="session", loop_scope="session", autouse=True)
async def _migrate_membership_columns():
    """共享测试库补 #71 成员货币真值列(正式迁移契约,幂等)。"""
    from backend.config import load_settings
    from backend.db.session import get_engine
    from scripts.migrate_add_membership_currency import migrate

    dsn = os.environ.get("TEST_DATABASE_URL", load_settings().postgres_dsn)
    engine = get_engine(dsn)
    try:
        await migrate(engine)
    finally:
        await engine.dispose()


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture(loop_scope="session")
async def env():
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email="m71api@test.com",
                role="admin",
                password_hash=hash_password("pass123"),
            )
        )
        await session.commit()
    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}
    async with factory() as session:
        rows = (
            await session.execute(
                select(DataSource.id).where(DataSource.id.like("m71-%"))
            )
        ).scalars().all()
        for sid in rows:
            await session.execute(
                SyncLog.__table__.delete().where(SyncLog.source_id == sid)
            )
        await session.execute(
            DataSource.__table__.delete().where(DataSource.id.like("m71-%"))
        )
        await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.commit()


async def _seed(source_id: str, *, sync_rounds: int = 3, **membership) -> None:
    factory = app.state.session_factory
    async with factory() as session:
        session.add(
            DataSource(
                id=source_id,
                type=membership.pop("type", "github"),
                product="wiki",
                enabled=True,
                config={},
                sync_interval="24h",
                **membership,
            )
        )
        # ≥3 轮成功同步 → sync(历史)维脱离 insufficient_data,overall 可达 HEALTHY
        from datetime import UTC, datetime, timedelta

        base = datetime.now(UTC) - timedelta(hours=sync_rounds + 1)
        for i in range(sync_rounds):
            session.add(
                SyncLog(
                    source_id=source_id,
                    source_type="github",
                    status="success",
                    started_at=base + timedelta(hours=i),
                )
            )
        await session.commit()


async def _get_json(headers, path: str) -> dict:
    async with _client() as client:
        resp = await client.get(path, headers=headers)
        assert resp.status_code == 200, resp.text
        return resp.json()


def _find(items: list[dict], source_id: str) -> dict:
    matches = [i for i in items if i["source_id"] == source_id]
    assert matches, f"{source_id} 不在响应中"
    return matches[0]


async def test_h1_drifted_source_is_degraded_and_never_healthy(env):
    await _seed(
        "m71-drift",
        membership_status="stale",
        membership_stale_detected=24,
        membership_stale_retired=0,
    )
    sources = await _get_json(env, "/api/admin/data-sources")
    row = next(r for r in sources if r["id"] == "m71-drift")
    assert row["membership_status"] == "stale"
    assert row["membership_stale_detected"] == 24
    assert row["membership_checked_at"] is None

    health = await _get_json(env, "/api/admin/sync-health")
    item = _find(health["items"], "m71-drift")
    assert item["currency"]["state"] == "degraded"
    assert item["currency"] is not item["consistency"]  # separate dimensions
    assert item["overall"] in {"ACTION_REQUIRED", "DEGRADED", "STALE", "PARTIAL"}


async def test_h2_current_source_stays_healthy(env):
    await _seed("m71-current", membership_status="current")
    health = await _get_json(env, "/api/admin/sync-health")
    item = _find(health["items"], "m71-current")
    assert item["currency"]["state"] == "ok"
    assert item["overall"] == "HEALTHY"


async def test_h3_legacy_null_truth_reads_unknown_and_does_not_drag(env):
    await _seed("m71-legacy")
    health = await _get_json(env, "/api/admin/sync-health")
    item = _find(health["items"], "m71-legacy")
    assert item["currency"]["state"] == "unknown"
    assert item["overall"] == "HEALTHY"


async def test_h4_failed_reconciliation_is_degraded(env):
    await _seed("m71-reconfail", membership_status="failed")
    health = await _get_json(env, "/api/admin/sync-health")
    item = _find(health["items"], "m71-reconfail")
    assert item["currency"]["state"] == "degraded"
    assert item["overall"] != "HEALTHY"


async def test_h5_unsupported_connector_truth_is_neutral(env):
    factory = app.state.session_factory
    async with factory() as session:
        session.add(
            DataSource(
                id="m71-fs",
                type="filesystem",
                product="knowledge",
                enabled=True,
                config={},
                sync_interval="24h",
                membership_status="unsupported",
            )
        )
        from datetime import UTC, datetime, timedelta

        base = datetime.now(UTC) - timedelta(hours=4)
        for i in range(3):
            session.add(
                SyncLog(
                    source_id="m71-fs",
                    source_type="filesystem",
                    status="success",
                    started_at=base + timedelta(hours=i),
                )
            )
        await session.commit()
    sources = await _get_json(env, "/api/admin/data-sources")
    row = next(r for r in sources if r["id"] == "m71-fs")
    assert row["membership_status"] == "unsupported"
    health = await _get_json(env, "/api/admin/sync-health")
    item = _find(health["items"], "m71-fs")
    assert item["currency"]["state"] == "unsupported"
    assert item["overall"] == "HEALTHY"
