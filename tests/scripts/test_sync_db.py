"""sync 从 DB 读配置 + 多分支索引的集成测试(用 ask_ai_test 库)。"""

import os
import subprocess

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
                s.execute(
                    select(Document).where(Document.source_id.like("ne301-code/%"))
                ).scalars()
            )
            branches = {d.branch for d in docs}
            assert "main" in branches
            assert "hw-v1.2" in branches
            # 清理
            for d in docs:
                s.delete(d)
            s.execute(
                DataSource.__table__.delete().where(DataSource.id == "ne301-code")
            )
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
    subprocess.run(
        ["git", "commit", "-q", "-m", "init"], cwd=r, check=True, env=_GIT_OLD_ENV
    )
    return r


_TEST_DSN = "postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test"


@pytest.mark.integration
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
                s.execute(
                    select(SyncLog).where(SyncLog.source_id == "ne301-skip")
                ).scalars()
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
