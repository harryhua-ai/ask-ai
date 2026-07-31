"""sync 从 DB 读配置 + 多分支索引的集成测试(用 ask_ai_test 库)。"""

import os
import subprocess

import pytest
from sqlalchemy import select

from backend.db.models import DataSource, Document
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
