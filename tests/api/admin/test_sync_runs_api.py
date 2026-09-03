"""⑫ Sync Truth 读侧 API 契约测试(§19):/sync-status、/sync-runs。

冻结断言:
- #9 刷新恢复:active 状态完全来自 request + run 持久化事实(前端零启发式);
- request_id NULL(cron 直跑)与 request 托管路径同等呈现;
- sync-all 串行队列:已处理切片如实呈现终态,未开始切片呈现 QUEUED;
- stage_total IS NULL 原样透传(禁止假百分比);counters/设备字段透传;
- /sync-runs:chunks_written 真实语义命名;duration 读侧计算;
  ingestion_skipped 只来自可证明事实;分页/过滤生效。
"""

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import DataSource, SyncLog, SyncRequest, SyncRun, User
from backend.main import app
from backend.services import sync_runs as sr

pytestmark = pytest.mark.asyncio(loop_scope="session")

S1, S2 = "w2api-a", "w2api-b"


@pytest_asyncio.fixture(scope="session", loop_scope="session", autouse=True)
async def _migrate_columns():
    """共享测试库补 W2 运行时事实列(正式迁移契约,幂等)。"""
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
async def env():
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(
                id=user_id,
                email="w2api@test.com",
                role="admin",
                password_hash=hash_password("pass123"),
            )
        )
        session.add(
            DataSource(
                id=S1, type="github", product="p", enabled=True, config={}, sync_interval="24h"
            )
        )
        session.add(
            DataSource(
                id=S2, type="web_crawl", product="p", enabled=True, config={}, sync_interval="1h"
            )
        )
        await session.commit()
    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}
    async with factory() as session:
        await session.execute(SyncRun.__table__.delete().where(SyncRun.source_id.in_([S1, S2])))
        await session.execute(SyncLog.__table__.delete().where(SyncLog.source_id.in_([S1, S2])))
        await session.execute(
            SyncRequest.__table__.delete().where(
                (SyncRequest.source_id.in_([S1, S2])) | (SyncRequest.error == "w2api-cleanup")
            )
        )
        await session.execute(DataSource.__table__.delete().where(DataSource.id.in_([S1, S2])))
        await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.commit()


async def _add(factory, **kw) -> None:
    async with factory() as session:
        session.add(kw["run"] if "run" in kw else kw["request"])
        await session.commit()


def _run(source_id: str, **kw) -> SyncRun:
    started = kw.pop("started_at", datetime.now(UTC) - timedelta(seconds=kw.pop("age_seconds", 30)))
    return SyncRun(source_id=source_id, started_at=started, **kw)


def _find(items: list[dict], source_id: str) -> dict:
    matches = [i for i in items if i["source_id"] == source_id]
    assert matches, f"{source_id} 不在 sync-status 响应中"
    return matches[0]


async def _get(headers, path: str, **params) -> dict:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(path, headers=headers, params=params or None)
    assert resp.status_code == 200, resp.text
    return resp.json()


# --------------------------------------------------------------------------- #
# /sync-status
# --------------------------------------------------------------------------- #


async def test_1_status_requires_auth():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/sync-status")
    assert resp.status_code == 401


async def test_2_status_idle_for_sources_without_evidence(env):
    data = await _get(env, "/api/admin/sync-status")
    item = _find(data["items"], S1)
    assert item["state"] == "IDLE"
    assert item["request_id"] is None and item["stage"] is None
    assert item["recovering"] is False and item["execution_device"] is None
    # 禁 fake active:无请求无运行行绝不显示同步中
    assert item["state"] != "RUNNING"


async def test_3_status_pending_request_is_queued(env):
    factory = app.state.session_factory
    await _add(factory, request=SyncRequest(source_id=S1, status="pending", attempt_count=0))
    data = await _get(env, "/api/admin/sync-status")
    item = _find(data["items"], S1)
    assert item["state"] == "QUEUED"
    assert item["request_id"] is not None
    assert item["recovering"] is False


async def test_4_status_running_run_telemetry_passthrough(env):
    factory = app.state.session_factory
    req = SyncRequest(source_id=S1, status="running", attempt_count=1)
    async with factory() as session:
        session.add(req)
        await session.commit()
        await session.refresh(req)
    await _add(
        factory,
        run=_run(
            S1,
            request_id=req.id,
            attempt=1,
            status=sr.RUN_RUNNING,
            stage="EMBED",
            stage_current=3,
            stage_total=10,
            counters={"docs_total": 10, "discovered": 12},
            execution_device="gpu",
            triggered_by="manual",
        ),
    )
    data = await _get(env, "/api/admin/sync-status")
    item = _find(data["items"], S1)
    assert item["state"] == "RUNNING"
    assert item["stage"] == "EMBED"
    assert item["stage_current"] == 3 and item["stage_total"] == 10
    assert item["counters"]["discovered"] == 12
    assert item["execution_device"] == "gpu"
    assert item["attempt"] == 1 and item["request_id"] == req.id
    assert item["recovering"] is False
    assert item["started_at"] is not None and item["updated_at"] is not None


async def test_5_status_recovering_overlay(env):
    factory = app.state.session_factory
    req = SyncRequest(source_id=S1, status="running", attempt_count=2, failure_kind="runner_failed")
    async with factory() as session:
        session.add(req)
        await session.commit()
        await session.refresh(req)
    await _add(
        factory,
        run=_run(S1, request_id=req.id, attempt=2, status=sr.RUN_RUNNING, stage="FETCH"),
    )
    data = await _get(env, "/api/admin/sync-status")
    item = _find(data["items"], S1)
    assert item["state"] == "RECOVERING"
    assert item["recovering"] is True


async def test_6_status_cron_null_request_path_and_unknown_denominator(env):
    """cron 直跑:request_id=NULL 合法;分母未知 stage_total=NULL 原样透传。"""
    factory = app.state.session_factory
    await _add(
        factory,
        run=_run(
            S1,
            request_id=None,
            attempt=1,
            status=sr.RUN_RUNNING,
            stage="FETCH",
            stage_total=None,
            triggered_by="cron",
        ),
    )
    data = await _get(env, "/api/admin/sync-status")
    item = _find(data["items"], S1)
    assert item["state"] == "RUNNING"
    assert item["request_id"] is None  # cron 直跑路径
    assert item["stage_total"] is None  # 分母未知 → 前端禁止百分比
    assert item["attempt"] == 1


async def test_7_status_sync_all_slice_truth(env):
    """sync-all:已处理切片如实呈现终态,未开始切片 QUEUED,互不污染。"""
    factory = app.state.session_factory
    req = SyncRequest(source_id=None, status="running", attempt_count=1, error="w2api-cleanup")
    async with factory() as session:
        session.add(req)
        await session.commit()
        await session.refresh(req)
    await _add(
        factory,
        run=_run(
            S1,
            request_id=req.id,
            attempt=1,
            status=sr.RUN_COMPLETED,
            stage="DONE",
            stage_current=0,
            stage_total=0,
        ),
    )
    data = await _get(env, "/api/admin/sync-status")
    done = _find(data["items"], S1)
    queued = _find(data["items"], S2)
    assert done["state"] == "COMPLETED"
    assert queued["state"] == "QUEUED"
    assert queued["request_id"] == req.id


# --------------------------------------------------------------------------- #
# /sync-runs
# --------------------------------------------------------------------------- #


async def test_8_runs_history_contract(env):
    factory = app.state.session_factory
    started = datetime.now(UTC) - timedelta(seconds=120)
    finished = started + timedelta(seconds=90)
    log = SyncLog(
        source_id=S1,
        source_type="github",
        status="success",
        items_new=0,
        items_updated=42,
        items_deleted=1,
        items_unchanged=7,
        triggered_by="cron",
    )
    run = _run(
        S1,
        request_id=None,
        attempt=3,
        recovery=True,
        status=sr.RUN_COMPLETED,
        stage="DONE",
        counters={"ingestion_skipped": 1, "docs_total": 0},
        consistency={"missing": 2, "orphan_count": 5, "expected_chunks": 100},
        execution_device="gpu_to_cpu",
        fallback_reason="cuda_oom",
        fallback_detail="VRAM exhausted at batch 4",
        error_summary=None,
        started_at=started,
        triggered_by="cron",
    )
    async with factory() as session:
        session.add(log)
        await session.flush()
        run.sync_log_id = log.id
        run.finished_at = finished
        session.add(run)
        await session.commit()

    data = await _get(env, "/api/admin/sync-runs", source_id=S1)
    assert data["total"] >= 1
    item = data["items"][0]
    assert item["request_id"] is None  # cron 合法
    assert item["attempt"] == 3 and item["recovery"] is True
    assert item["status"] == "completed"
    assert item["duration_seconds"] == 90.0  # 读侧计算
    assert item["ingestion_skipped"] is True  # 可证明事实
    assert item["execution_device"] == "gpu_to_cpu"
    assert item["fallback_reason"] == "cuda_oom"
    assert item["consistency"]["orphan_count"] == 5
    assert item["sync_log"]["chunks_written"] == 42  # 真实语义:写入 chunk 数
    assert item["sync_log"]["items_unchanged"] == 7
    assert item["sync_log"]["items_deleted"] == 1
    assert "chunks_written" in item["sync_log"] and "items_updated" not in item["sync_log"]


async def test_9_runs_filter_status_and_no_log_run(env):
    factory = app.state.session_factory
    await _add(
        factory,
        run=_run(
            S2,
            request_id=None,
            attempt=1,
            status=sr.RUN_FAILED,
            stage="FETCH",
            error_summary="boom",
        ),
    )
    data = await _get(env, "/api/admin/sync-runs", source_id=S2, status="failed")
    assert data["total"] == 1
    item = data["items"][0]
    assert item["sync_log"] is None  # 无业务结局行 → null,不伪造
    assert item["ingestion_skipped"] is False
    assert item["duration_seconds"] is None  # 未终态不猜 duration(此处 failed 带终态时间缺省)

    data_all = await _get(env, "/api/admin/sync-runs", source_id=S2, status="completed")
    assert data_all["total"] == 0


async def test_10_sync_logs_exposes_items_unchanged(env):
    factory = app.state.session_factory
    async with factory() as session:
        session.add(
            SyncLog(
                source_id=S1,
                source_type="github",
                status="success",
                items_unchanged=9,
            )
        )
        await session.commit()
    data = await _get(env, "/api/admin/sync-logs", source_id=S1)
    assert data["total"] >= 1
    assert any(item["items_unchanged"] == 9 for item in data["items"])
