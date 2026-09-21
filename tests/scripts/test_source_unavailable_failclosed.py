"""Issue #100 AC2:源根对执行面不可用 ⇒ sync fail-closed,绝不伪装成功/无变更。

生产事故(2026-09-21,knowledge-support-cases):上传根只在 backend 容器可
写层;sync-executor/sync-cron 解析同一相对路径时目录不存在。Python 3.13
``rglob`` 对缺失根**静默空集**,``_sync_one`` 走「无变更」路径:

- SyncLog 记 ``success``(伪健康);窗口照常推进;
- ``_reconcile_source_absence`` 对全部账本行做政策缺席分类
  (事故日志「政策缺席: … include_dirs」),范围内行每轮 +1,
  两次后即被「退休」—— 根不可见被当成权威缺席。

契约(#100 AC2/AC4):

- 根不可用 ⇒ SyncLog ``failed`` 且 error_detail 可执行(携带配置根路径,
  指向部署挂载缺口);
- 账本行**零**缺席计数、零政策缺席分类、零退休推进(根不可见 ≠ 权威
  缺席,更 ≠ 管理员范围变化);
- 真实 FilesystemConnector(真实缺失根)+ 真实 Postgres 账本;零
  Weaviate/零 embed(verify 与 builder patch,沿用 Track A 门测试约定)。
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.connectors.filesystem import FilesystemConnector
from backend.connectors.registry import SourceConfig
from backend.db.models import Base, DataSource, Document, DocumentVersion, SyncLog
from backend.services import document_lifecycle as lifecycle
from scripts.sync import _sync_one

pytestmark = pytest.mark.asyncio

SRC = "upload100"
# 行 1:在 include_dirs 范围内(若缺席会被 +1,两轮即退休 —— 正是必须
# fail-closed 阻止的伪退休);
DOC_IN_SCOPE = f"{SRC}/main/docs/inside.md"
# 行 2:范围外(现状会被政策缺席分类刷「政策缺席」日志 —— 伪影)
DOC_OUT_SCOPE = f"{SRC}/main/other/outside.md"


def _doc(sid: str) -> Document:
    return Document(
        content_hash=f"hash-{sid}",
        source_id=sid,
        source_type="filesystem",
        product="probe",
        title=sid.rsplit("/", 1)[-1],
        url=f"file:///{sid}",
        metadata_={},
        branch="main",
        chunk_count=1,
    )


@pytest.fixture()
def sync_factory(db_engine):
    from backend.db.session import get_session_factory

    sync_engine = create_engine(
        os.environ["TEST_DATABASE_URL"].replace("+asyncpg", "+psycopg2")
    )
    Base.metadata.create_all(sync_engine)
    try:
        yield (
            sessionmaker(bind=sync_engine, expire_on_commit=False),
            get_session_factory(db_engine),
        )
    finally:
        sync_engine.dispose()


def _wipe(sync_factory) -> None:
    sync_sf, _ = sync_factory
    with sync_sf() as session:
        session.execute(SyncLog.__table__.delete().where(SyncLog.source_id == SRC))
        session.execute(
            DocumentVersion.__table__.delete().where(
                DocumentVersion.source_id.like(f"{SRC}/%")
            )
        )
        session.execute(
            Document.__table__.delete().where(Document.source_id.like(f"{SRC}/%"))
        )
        session.execute(DataSource.__table__.delete().where(DataSource.id == SRC))
        session.commit()


@pytest.fixture(autouse=True)
def _seed_ledger(sync_factory):
    """种子:源行 + 范围内/外各一行 active(带初始版本,可服务口径)。"""
    _wipe(sync_factory)
    sync_sf, _ = sync_factory
    with sync_sf() as session:
        session.add(
            DataSource(
                id=SRC,
                type="filesystem",
                product="probe",
                config={
                    "root_path": "data/uploads/data-sources/upload100",
                    "file_types": [".md"],
                    "include_dirs": ["docs"],
                },
            )
        )
        inside, outside = _doc(DOC_IN_SCOPE), _doc(DOC_OUT_SCOPE)
        session.add(inside)
        session.add(outside)
        session.flush()
        lifecycle.ensure_initial_version(session, inside)
        lifecycle.ensure_initial_version(session, outside)
        session.commit()
    yield
    _wipe(sync_factory)


def _real_connector(missing_root: Path) -> FilesystemConnector:
    """真实 FilesystemConnector,根指向**不存在**的路径(执行面不可见)。"""
    return FilesystemConnector(
        SourceConfig(
            id=SRC,
            type="filesystem",
            product="probe",
            enabled=True,
            sync_interval="24h",
            branches=[],
            channel_visibility=("widget", "api"),
            config={
                "root_path": str(missing_root),
                "file_types": [".md"],
                "include_dirs": ["docs"],
            },
        )
    )


async def _run_sync(sync_factory, connector, monkeypatch) -> SyncLog | None:
    """经稳定 seam ``_sync_one`` 驱动一轮同步,返回落库的 SyncLog。"""
    from backend.services.vector_consistency import VectorGapReport

    sync_sf, async_sf = sync_factory

    pipeline = MagicMock()
    pipeline._session_factory = sync_sf

    healthy = VectorGapReport(
        expected_chunks=2,
        actual_chunks=2,
        missing_source_ids=[],
        refill_source_ids=[],
        stale_chunk_count=0,
        orphan_count=0,
    )
    builder = MagicMock()
    builder.repair_documents.return_value = ([], [], 0)
    builder.build_generation.return_value = MagicMock(
        chunks_written=0,
        new_docs=[],
        updated_docs=[],
        metadata_docs=[],
        unchanged_docs=[],
    )

    monkeypatch.setattr("scripts.sync.ConnectorRegistry.create", lambda cfg: connector)
    monkeypatch.setattr("scripts.sync.verify_source_vectors", _async_const(healthy))
    monkeypatch.setattr("scripts.sync.GenerationBuilder", lambda *a, **k: builder)

    cfg = MagicMock()
    cfg.id = SRC
    cfg.type = "filesystem"

    await _sync_one(cfg, pipeline, async_sf, triggered_by="cron")

    with sync_sf() as session:
        return session.execute(
            select(SyncLog)
            .where(SyncLog.source_id == SRC)
            .order_by(SyncLog.started_at.desc())
            .limit(1)
        ).scalar_one_or_none()


def _async_const(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner


def _absence_of(sync_factory, sid: str) -> dict | None:
    sync_sf, _ = sync_factory
    with sync_sf() as session:
        row = session.execute(
            select(Document).where(Document.source_id == sid)
        ).scalar_one()
        return lifecycle.get_absence_state(row)


async def test_unavailable_root_fails_closed_not_pseudo_success(
    sync_factory, monkeypatch, tmp_path
):
    """AC2:根不可见 ⇒ SyncLog failed + 可执行错误,绝非 success/无变更。"""
    log = await _run_sync(
        sync_factory, _real_connector(tmp_path / "not-there"), monkeypatch
    )
    assert log is not None
    assert log.status == "failed", (
        "根目录对执行面不可用时同步必须 fail-closed 记 failed;"
        "现状(Python 3.13 rglob 静默空集)伪装成 success —— 生产事故主缺陷"
    )
    detail = str(log.error_detail or "")
    assert "not-there" in detail, (
        "失败详情必须可执行:携带配置根路径,操作员可据此定位部署挂载缺口"
    )


async def test_unavailable_root_never_advances_absence_or_policy_classification(
    sync_factory, monkeypatch, tmp_path
):
    """AC2/AC4:根不可见 ≠ 权威缺席,更 ≠ 范围变化。

    - 范围内行:缺席计数必须保持 0(现状会被 +1,两轮伪退休);
    - 范围外行:不得产生政策缺席分类(现状刷「政策缺席 include_dirs」);
    - 两轮同一不可见根:零退休推进(AC2 「must not retire existing
      documents merely because the root is inaccessible」)。
    """
    unavailable = tmp_path / "not-there"
    for _ in range(2):
        await _run_sync(sync_factory, _real_connector(unavailable), monkeypatch)

    inside_absence = _absence_of(sync_factory, DOC_IN_SCOPE)
    outside_absence = _absence_of(sync_factory, DOC_OUT_SCOPE)
    assert not inside_absence or int(inside_absence.get("confirmations", 0)) == 0, (
        "根不可见时范围内行的缺席确认计数必须为 0 —— 根不可见绝不推进退休"
    )
    assert not outside_absence or not outside_absence.get("policy_reason"), (
        "根不可见时不得输出政策缺席分类(执行面隔离伪影)"
    )

    sync_sf, _ = sync_factory
    with sync_sf() as session:
        lifecycles = {
            row.source_id: row.lifecycle
            for row in session.execute(
                select(Document).where(Document.source_id.like(f"{SRC}/%"))
            ).scalars()
        }
    assert lifecycles[DOC_IN_SCOPE] == lifecycle.DocLifecycle.ACTIVE
    assert lifecycles[DOC_OUT_SCOPE] == lifecycle.DocLifecycle.ACTIVE


async def test_unavailable_root_does_not_advance_success_window(
    sync_factory, monkeypatch, tmp_path
):
    """AC2:失败轮不得推进增量窗口(``_last_success_at`` 只认 success)。"""
    from scripts.sync import _last_success_at

    _, async_sf = sync_factory
    before = await _last_success_at(async_sf, SRC)
    await _run_sync(sync_factory, _real_connector(tmp_path / "not-there"), monkeypatch)
    after = await _last_success_at(async_sf, SRC)
    assert before == after, "fail-closed 轮绝不推进 _last_success_at 窗口"
