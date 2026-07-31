"""LocalGitConnector 单元测试。

覆盖:
- 多分支 checkout 全量抓取(main + hw-v1.2 各自独有的文件)
- source_id 格式 ``{cfg.id}/{branch}/{rel}``
- RawDocument.branch 字段被正确填充
- file_types 白名单过滤
- ExclusionPolicy 接入(.git 目录、构建目录被排除)
- channel_visibility 透传
- fetch_changes 全量回退 / fetch_deleted 返回空
- 注册装饰器绑定 ``local_git``
"""

import os
import subprocess

import pytest

from backend.connectors.local_git import LocalGitConnector
from backend.connectors.registry import ConnectorRegistry, SourceConfig

_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def _git(args, cwd):
    """在 cwd 执行 git 子命令,断言成功。"""
    subprocess.run(["git", *args], cwd=cwd, check=True, env=_GIT_ENV)


@pytest.fixture
def tiny_repo(tmp_path):
    """构造微型 git 仓库:main 分支有 main_only.py,hw-v1.2 分支额外有 hw.py。

    最终留在 main 分支上,留给 connector 自己 checkout。
    """
    r = tmp_path / "repo"
    r.mkdir()
    _git(["init", "-q", "-b", "main"], r)
    (r / "main_only.py").write_text("a=1\n")
    _git(["add", "-A"], r)
    _git(["commit", "-q", "-m", "init"], r)
    _git(["checkout", "-q", "-b", "hw-v1.2"], r)
    (r / "hw.py").write_text("b=2\n")
    _git(["add", "-A"], r)
    _git(["commit", "-q", "-m", "hw"], r)
    _git(["checkout", "-q", "main"], r)
    return r


@pytest.fixture
def cfg_factory(tiny_repo):
    """构造默认 LocalGit SourceConfig 的工厂。"""

    def _make(*, config: dict | None = None, **overrides: object) -> SourceConfig:
        base_config: dict = {
            "repo_path": str(tiny_repo),
            "file_types": [".py"],
        }
        if config is not None:
            base_config.update(config)
        kwargs: dict[str, object] = {
            "id": "ne301",
            "type": "local_git",
            "product": "ne301",
            "enabled": True,
            "config": base_config,
            "sync_interval": "1h",
            "branches": ("main", "hw-v1.2"),
        }
        kwargs.update(overrides)
        return SourceConfig(**kwargs)  # type: ignore[arg-type]

    return _make


# ====================  单元测试  ====================


@pytest.mark.unit
def test_local_git_connector_registered():
    """注册装饰器应将 "local_git" 类型绑定到 ConnectorRegistry。"""
    assert "local_git" in ConnectorRegistry._connectors


@pytest.mark.unit
def test_fetch_all_multi_branch(cfg_factory):
    """``fetch_all`` 应 checkout 每个分支并 yield 各自的文件,branch 字段正确。"""
    cfg = cfg_factory()
    docs = list(LocalGitConnector(cfg).fetch_all())

    branches_seen = {d.branch for d in docs}
    assert branches_seen == {"main", "hw-v1.2"}

    source_ids = {d.source_id for d in docs}
    assert "ne301/main/main_only.py" in source_ids
    assert "ne301/hw-v1.2/hw.py" in source_ids
    # hw-v1.2 分支也包含 main_only.py(分支从 main 分出)
    assert "ne301/hw-v1.2/main_only.py" in source_ids


@pytest.mark.unit
def test_fetch_all_branches_tuple_order(cfg_factory):
    """``fetch_all`` 应按 branches tuple 顺序 checkout,先 main 后 hw-v1.2。"""
    cfg = cfg_factory()
    docs = list(LocalGitConnector(cfg).fetch_all())
    # 第一个文档应在 main 分支(branches[0])
    assert docs[0].branch == "main"


@pytest.mark.unit
def test_fetch_all_file_types_filter(cfg_factory, tiny_repo):
    """非白名单后缀的文件应被过滤掉。"""
    (tiny_repo / "notes.md").write_text("# notes")
    # notes.md 未 commit,但 checkout 时工作区会清掉未跟踪文件?不会,untracked 保留。
    # 为避免 untracked 干扰,改用已 commit 的非白名单文件。
    # 先回到 main,add 一个 .md,commit,再回到 hw-v1.2 让测试干净。
    _git(["checkout", "-q", "main"], tiny_repo)
    (tiny_repo / "README.md").write_text("# readme")
    _git(["add", "-A"], tiny_repo)
    _git(["commit", "-q", "-m", "readme"], tiny_repo)
    _git(["checkout", "-q", "hw-v1.2"], tiny_repo)

    cfg = cfg_factory()
    docs = list(LocalGitConnector(cfg).fetch_all())
    suffixes = {os.path.splitext(d.metadata["path"])[1] for d in docs}
    assert ".md" not in suffixes
    assert all(s == ".py" for s in suffixes)


@pytest.mark.unit
def test_fetch_all_excludes_git_dir(cfg_factory):
    """``.git`` 目录内的文件不应被 yield(ExclusionPolicy 排除)。"""
    cfg = cfg_factory()
    docs = list(LocalGitConnector(cfg).fetch_all())
    for d in docs:
        assert ".git" not in d.metadata["path"]
        assert "ne301/" in d.source_id


@pytest.mark.unit
def test_channel_visibility_passthrough(cfg_factory):
    """SourceConfig.channel_visibility 应透传到每条 RawDocument。"""
    cfg = cfg_factory(channel_visibility=("api",))
    docs = list(LocalGitConnector(cfg).fetch_all())
    assert docs  # 非空
    assert all(d.channel_visibility == ("api",) for d in docs)


@pytest.mark.unit
def test_source_id_and_product_properties(cfg_factory):
    """``source_id`` / ``product`` 属性应返回 config 对应字段。"""
    cfg = cfg_factory()
    c = LocalGitConnector(cfg)
    assert c.source_id == "ne301"
    assert c.product == "ne301"


@pytest.mark.unit
def test_fetch_changes_full_fallback(cfg_factory):
    """Plan 1 简化:``fetch_changes`` 全量回退。"""
    from datetime import UTC, datetime

    cfg = cfg_factory()
    c = LocalGitConnector(cfg)
    all_docs = list(c.fetch_all())
    changed = list(c.fetch_changes(datetime(2020, 1, 1, tzinfo=UTC)))
    assert len(changed) == len(all_docs)


@pytest.mark.unit
def test_fetch_deleted_returns_empty(cfg_factory):
    """``fetch_deleted`` 始终返回空列表(Plan 1 简化)。"""
    from datetime import UTC, datetime

    cfg = cfg_factory()
    c = LocalGitConnector(cfg)
    assert c.fetch_deleted(datetime.now(tz=UTC)) == []


@pytest.mark.unit
def test_default_branch_when_branches_empty(cfg_factory):
    """branches 为空时,默认取 config.branch 或 'main'。"""
    cfg = cfg_factory(branches=(), config={"branch": "hw-v1.2"})
    docs = list(LocalGitConnector(cfg).fetch_all())
    branches_seen = {d.branch for d in docs}
    assert branches_seen == {"hw-v1.2"}


@pytest.mark.unit
def test_content_hash_is_sha256(cfg_factory):
    """content_hash 应为 64 字符的 SHA256。"""
    cfg = cfg_factory()
    docs = list(LocalGitConnector(cfg).fetch_all())
    assert all(len(d.content_hash) == 64 for d in docs)
