"""sync 从 DB 读配置 + 多分支索引的集成测试(用 ask_ai_test 库)。"""

import os
import subprocess
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select

from backend.db.models import DataSource, Document, SyncLog
from backend.db.session import get_engine, get_sync_session_factory, init_db

pytestmark = pytest.mark.integration


@pytest.fixture
def tiny_repo(tmp_path):
    """建微型 git repo,2 分支各含一个独有 .py 文件。

    ``hw-v1.2`` 从 ``main`` 分出,两边共享 ``main_only.py``(同内容,触发
    content_hash 去重);另各自加一个独有文件,确保两个分支在 documents
    表中都有 branch 字段非空的行。
    """
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=r, check=True)
    (r / "main_only.py").write_text("a = 1\n")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    subprocess.run(["git", "add", ".", "-A"], cwd=r, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=r, check=True, env=env)
    subprocess.run(["git", "checkout", "-q", "-b", "hw-v1.2"], cwd=r, check=True)
    (r / "hw.py").write_text("b = 2\n")
    subprocess.run(["git", "add", ".", "-A"], cwd=r, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "hw"], cwd=r, check=True, env=env)
    subprocess.run(["git", "checkout", "-q", "main"], cwd=r, check=True)
    # main 独有文件(确保 main 分支在 documents 表留下 branch=main 的行,
    # 不被 hw-v1.2 同内容去重覆盖)
    (r / "main_unique.py").write_text("c = 3\n")
    subprocess.run(["git", "add", ".", "-A"], cwd=r, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "main-unique"], cwd=r, check=True, env=env)
    return r


# 决策 2A(github 统一为唯一 git 源类型)移除了 LocalGitConnector 的
# @register,以下 3 个测试经 ConnectorRegistry.create(type="local_git")
# 必然 KeyError,自该决策起失效。待用 github connector + 本地路径重写;
# skip/fallback 的 mock 路径已由 tests/pipeline/test_sync.py 覆盖。
_LEGACY_LOCAL_GIT = pytest.mark.skip(
    reason="local_git 已移除 registry 注册(决策 2A),待迁移 github connector"
)


@_LEGACY_LOCAL_GIT
async def test_run_sync_reads_db_and_writes_documents_with_branch(tiny_repo, monkeypatch):
    """seed DataSource(local_git,多分支) → run_sync → documents 表有多分支行,branch 非空。"""
    from unittest.mock import MagicMock, patch

    import numpy as np

    import backend.connectors.local_git  # 触发 @register  # noqa: F401
    from backend.config import load_settings
    from scripts.sync import run_sync

    # 强制用测试库:Settings 是 frozen dataclass,通过 env 覆盖 POSTGRES_DB
    monkeypatch.setenv("POSTGRES_DB", "ask_ai_test")
    settings = load_settings()
    test_dsn = settings.postgres_dsn
    assert "ask_ai_test" in test_dsn

    engine = get_engine(test_dsn)
    try:
        await init_db(engine)
        # seed DataSource
        sync_factory = get_sync_session_factory(test_dsn)
        with sync_factory() as s:
            s.add(
                DataSource(
                    id="ne301-code",
                    type="local_git",
                    product="ne301",
                    enabled=True,
                    config={
                        "repo_path": str(tiny_repo),
                        "file_types": [".py"],
                        "branches": ["main", "hw-v1.2"],
                    },
                    sync_interval="1h",
                )
            )
            s.commit()

        # mock weaviate + embedder,用真实 IngestionPipeline 写 documents 表
        mock_collection = MagicMock()
        mock_client = MagicMock()
        mock_client.collections.exists.return_value = True
        mock_client.collections.get.return_value = mock_collection
        mock_embedder = MagicMock()
        mock_embedder.embed.side_effect = lambda texts: [np.array([0.1] * 8) for _ in texts]

        with (
            patch("scripts.sync.weaviate.connect_to_local", return_value=mock_client),
            patch("scripts.sync.BGEEmbedder", return_value=mock_embedder),
        ):
            await run_sync(settings)

        # 断言 documents 表有多分支行
        with sync_factory() as s:
            docs = list(
                s.execute(select(Document).where(Document.source_id.like("ne301-code/%"))).scalars()
            )
            branches = {d.branch for d in docs}
            assert "main" in branches
            assert "hw-v1.2" in branches
            # 清理
            for d in docs:
                s.delete(d)
            s.execute(DataSource.__table__.delete().where(DataSource.id == "ne301-code"))
            s.commit()
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(
                __import__("backend.db.models", fromlist=["Base"]).Base.metadata.drop_all
            )
        await engine.dispose()


# ---------------------------------------------------------------------------
# Task 3: _sync_one 在 fetch_changes 空时的"首次 vs 无变更"判断
# ---------------------------------------------------------------------------

# 共用 git 身份环境(避免 git commit 触发 user.name/email 缺失错误)
_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}
# commits 标到 2000 年 → fetch_changes(now-24h) 必返回空(真增量)
_GIT_OLD_ENV = {
    **_GIT_ENV,
    "GIT_AUTHOR_DATE": "2000-01-01T00:00:00",
    "GIT_COMMITTER_DATE": "2000-01-01T00:00:00",
}


@pytest.fixture
def backdated_repo(tmp_path):
    """commits 全标 2000 年的 git repo → fetch_changes(近 24h) 返回空。

    与 ``tiny_repo`` 不同,这里把 commit 日期强制设为 2000-01-01,使得
    ``fetch_changes(datetime.now(UTC) - timedelta(hours=24))`` 在
    ``git log --since`` 过滤后**必然返回空**——这是 Task 3 新逻辑的关键
    触发条件。
    """
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=r, check=True)
    (r / "main_only.py").write_text("a = 1\n")
    subprocess.run(["git", "add", ".", "-A"], cwd=r, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=r, check=True, env=_GIT_OLD_ENV)
    return r


_TEST_DSN = "postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test"


@pytest.mark.integration
@_LEGACY_LOCAL_GIT
async def test_sync_skips_when_documents_exist_and_no_changes(backdated_repo):
    """fetch_changes 空 + documents 表已有记录 → 不回退 fetch_all,不 ingest_all。

    场景:数据源之前已全量同步过(documents 表有行),本次窗口期无新变更
    → 应"跳过",不调 ingest_all,SyncLog.items_unchanged >= 1, items_new == 0。
    """
    from unittest.mock import MagicMock

    import backend.connectors.local_git  # noqa: F401 - 触发 @register
    from backend.connectors.registry import SourceConfig
    from backend.db.session import get_session_factory
    from scripts.sync import _sync_one

    engine = get_engine(_TEST_DSN)
    try:
        await init_db(engine)
        async_factory = get_session_factory(engine)
        sync_factory = get_sync_session_factory(_TEST_DSN)

        cfg = SourceConfig(
            id="ne301-skip",
            type="local_git",
            product="ne301",
            enabled=True,
            config={"repo_path": str(backdated_repo), "file_types": [".py"]},
            sync_interval="1h",
        )

        # 预先在 documents 表 seed 一行(模拟之前已全量同步过)
        with sync_factory() as s:
            s.add(
                Document(
                    content_hash="a" * 64,
                    source_id="ne301-skip/main/main_only.py",
                    source_type="local_git",
                    product="ne301",
                    title="main_only",
                    url="file:///x",
                    branch="main",
                    chunk_count=1,
                )
            )
            s.commit()

        mock_pipeline = MagicMock()
        mock_pipeline.ingest_all.return_value = {}

        await _sync_one(cfg, mock_pipeline, async_factory, triggered_by="test")

        # 核心断言:没有 ingest_all 调用 = 没有回退全量
        assert not mock_pipeline.ingest_all.called, (
            "documents 表已有记录时,fetch_changes 空不应回退 fetch_all"
        )

        # SyncLog 应记录 items_unchanged >= 1, items_new == 0
        with sync_factory() as s:
            logs = list(
                s.execute(select(SyncLog).where(SyncLog.source_id == "ne301-skip")).scalars()
            )
            assert logs, "应至少有一条 SyncLog"
            latest = max(logs, key=lambda x: x.started_at)
            assert latest.items_unchanged >= 1
            assert latest.items_new == 0
            # 清理本测试 seed 的行
            s.execute(delete(Document).where(Document.source_id.like("ne301-skip/%")))
            s.execute(delete(SyncLog).where(SyncLog.source_id == "ne301-skip"))
            s.commit()
    finally:
        await engine.dispose()


@pytest.mark.integration
@_LEGACY_LOCAL_GIT
async def test_sync_falls_back_when_no_documents(backdated_repo):
    """fetch_changes 空 + documents 表无记录 → 首次同步,回退 fetch_all(ingest_all 被调)。

    场景:数据源从未同步过(documents 表无行),即使 fetch_changes 空(所有
    commits 都早于 since),也应回退 fetch_all 进行首次全量灌入。
    """
    from unittest.mock import MagicMock

    import backend.connectors.local_git  # noqa: F401 - 触发 @register
    from backend.connectors.registry import SourceConfig
    from backend.db.session import get_session_factory
    from scripts.sync import _sync_one

    engine = get_engine(_TEST_DSN)
    try:
        await init_db(engine)
        async_factory = get_session_factory(engine)
        sync_factory = get_sync_session_factory(_TEST_DSN)

        cfg = SourceConfig(
            id="ne301-first",
            type="local_git",
            product="ne301",
            enabled=True,
            config={"repo_path": str(backdated_repo), "file_types": [".py"]},
            sync_interval="1h",
        )

        # 保证 documents 表无该源的残留行(防止前置测试污染)
        with sync_factory() as s:
            s.execute(delete(Document).where(Document.source_id.like("ne301-first/%")))
            s.execute(delete(SyncLog).where(SyncLog.source_id == "ne301-first"))
            s.commit()

        mock_pipeline = MagicMock()
        mock_pipeline.ingest_all.return_value = {}

        await _sync_one(cfg, mock_pipeline, async_factory, triggered_by="test")

        # 核心断言:回退全量 → ingest_all 被调用
        assert mock_pipeline.ingest_all.called, (
            "documents 表无记录时,fetch_changes 空应回退 fetch_all 并调用 ingest_all"
        )

        # 清理本测试产生的行
        with sync_factory() as s:
            s.execute(delete(Document).where(Document.source_id.like("ne301-first/%")))
            s.execute(delete(SyncLog).where(SyncLog.source_id == "ne301-first"))
            s.commit()
    finally:
        await engine.dispose()


# --------------------------------------------------------------------------- #
# 增量窗口改造(2026-08-17):since = 上次成功时间,而非固定 now-24h
# --------------------------------------------------------------------------- #


@pytest.mark.integration
async def test_last_success_at_prefers_latest_success_ignores_failed():
    """_last_success_at 取最近一条 success 的 finished_at,跳过 failed 行。

    finished_at 为空时回退 started_at(dry_run/异常路径可能缺失)。
    """
    from scripts.sync import _last_success_at

    now = datetime.now(UTC)
    from backend.db.session import get_session_factory

    engine = get_engine(_TEST_DSN)
    try:
        await init_db(engine)
        async_factory = get_session_factory(engine)
        sync_factory = get_sync_session_factory(_TEST_DSN)
        sid = "win-lookup-src"

        with sync_factory() as s:
            s.execute(delete(SyncLog).where(SyncLog.source_id == sid))
            # 三条:旧 success、更新的 failed、最新 success(finished_at 空)
            s.add(
                SyncLog(
                    source_id=sid,
                    source_type="local_git",
                    status="success",
                    started_at=now - timedelta(hours=10),
                    finished_at=now - timedelta(hours=10),
                )
            )
            s.add(
                SyncLog(
                    source_id=sid,
                    source_type="local_git",
                    status="failed",
                    started_at=now - timedelta(hours=6),
                    finished_at=now - timedelta(hours=6),
                )
            )
            newest = SyncLog(
                source_id=sid,
                source_type="local_git",
                status="success",
                started_at=now - timedelta(hours=2),
                finished_at=None,
            )
            s.add(newest)
            s.commit()

        got = await _last_success_at(async_factory, sid)

        assert got is not None
        assert got == newest.started_at  # 最近 success 的 started_at 回退

        with sync_factory() as s:
            s.execute(delete(SyncLog).where(SyncLog.source_id == sid))
            s.commit()
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_sync_one_uses_last_success_as_window():
    """_sync_one 应把上次成功的 finished_at 作为 fetch_changes 的 since。

    seed:documents 有行(触发 skip 路径)+ success SyncLog(5h 前)
    → 记录型 connector 收到的 since == seeded finished_at。
    """
    from unittest.mock import MagicMock

    from backend.connectors.registry import ConnectorRegistry, SourceConfig
    from scripts.sync import _sync_one

    now = datetime.now(UTC)
    from backend.db.session import get_session_factory

    engine = get_engine(_TEST_DSN)
    try:
        await init_db(engine)
        async_factory = get_session_factory(engine)
        sync_factory = get_sync_session_factory(_TEST_DSN)
        sid = "win-pass-src"
        last_success = now - timedelta(hours=5)

        with sync_factory() as s:
            s.execute(delete(SyncLog).where(SyncLog.source_id == sid))
            s.execute(delete(Document).where(Document.source_id.like(f"{sid}/%")))
            s.add(
                Document(
                    content_hash="w" * 64,
                    source_id=f"{sid}/main/x.py",
                    source_type="local_git",
                    product="ne301",
                    title="x",
                    url="file:///x",
                    branch="main",
                    chunk_count=1,
                )
            )
            s.add(
                SyncLog(
                    source_id=sid,
                    source_type="local_git",
                    status="success",
                    started_at=last_success,
                    finished_at=last_success,
                )
            )
            s.commit()

        recorded: dict[str, object] = {}

        class _RecordingConnector:
            def fetch_changes(self, since):
                recorded["since"] = since
                return iter([])  # 空变更 → skip 路径

            def fetch_deleted(self, since):
                return []

        cfg = SourceConfig(
            id=sid,
            type="local_git",
            product="ne301",
            enabled=True,
            config={"repo_path": "/nonexistent"},
            sync_interval="1h",
        )
        orig_create = ConnectorRegistry.create
        ConnectorRegistry.create = staticmethod(lambda c: _RecordingConnector())
        try:
            await _sync_one(cfg, MagicMock(), async_factory, triggered_by="test")
        finally:
            ConnectorRegistry.create = orig_create

        assert recorded["since"] == last_success

        # skip 路径仍记 success → 下次窗口继续推进
        with sync_factory() as s:
            latest = (
                s.execute(
                    select(SyncLog)
                    .where(SyncLog.source_id == sid)
                    .order_by(SyncLog.started_at.desc())
                    .limit(1)
                )
                .scalars()
                .one()
            )
            assert latest.status == "success"
            s.execute(delete(SyncLog).where(SyncLog.source_id == sid))
            s.execute(delete(Document).where(Document.source_id.like(f"{sid}/%")))
            s.commit()
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_sync_one_marks_failed_when_ingest_raises():
    """ingest_all 抛错(全零守卫/OOM 模式)→ SyncLog 记 failed + error_detail。"""
    from unittest.mock import MagicMock

    from backend.connectors.base import RawDocument
    from backend.connectors.registry import ConnectorRegistry, SourceConfig
    from backend.db.session import get_session_factory
    from scripts.sync import _sync_one

    engine = get_engine(_TEST_DSN)
    try:
        await init_db(engine)
        async_factory = get_session_factory(engine)
        sync_factory = get_sync_session_factory(_TEST_DSN)
        sid = "win-fail-src"

        with sync_factory() as s:
            s.execute(delete(SyncLog).where(SyncLog.source_id == sid))

        doc = RawDocument(
            source_id=f"{sid}/p/1",
            source_type="woocommerce",
            product="commercial",
            title="p",
            content="NE301 Kit",
            url="https://x",
            metadata={},
            content_hash="f" * 64,
        )

        class _FailingConnector:
            def fetch_changes(self, since):
                return iter([doc])

            def fetch_deleted(self, since):
                return []

        cfg = SourceConfig(
            id=sid,
            type="woocommerce",
            product="commercial",
            enabled=True,
            config={},
            sync_interval="1h",
        )
        pipeline = MagicMock()
        pipeline.ingest_all.side_effect = RuntimeError(
            "2 个文档灌入失败(可能 embed/写库故障): woo/p/1"
        )

        orig_create = ConnectorRegistry.create
        ConnectorRegistry.create = staticmethod(lambda c: _FailingConnector())
        try:
            await _sync_one(cfg, pipeline, async_factory, triggered_by="test")
        finally:
            ConnectorRegistry.create = orig_create

        with sync_factory() as s:
            latest = (
                s.execute(
                    select(SyncLog)
                    .where(SyncLog.source_id == sid)
                    .order_by(SyncLog.started_at.desc())
                    .limit(1)
                )
                .scalars()
                .one()
            )
            assert latest.status == "failed"
            assert "灌入失败" in (latest.error_detail or "")
            s.execute(delete(SyncLog).where(SyncLog.source_id == sid))
            s.commit()
    finally:
        await engine.dispose()
