"""F16 GitHub 恢复重放 golden 回归(阶段⑩,真实 git 仓)。

危险窗口(Discovery F16):git fetch/reset 推进本地 HEAD 后 ingest 被中断 →
下轮 `_remote_has_updates`(API SHA == 本地 HEAD)短路 → 不读 since 变更 →
假 no-change success,变更永久丢失。

冻结行为(Contract §9):恢复触发的 GitHub 增量必须绕过该短路 ——
ensure clone → fetch/reset → **始终**读 ``git log --since=<last success>``,
即使 remote SHA == local HEAD。API 边界(``_api_get_latest_sha``,纯网络)
可 stub;git 历史行为必须真实。
"""

import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from backend.connectors.github import GitHubConnector
from backend.connectors.registry import SourceConfig

_BACKDATE = "2026-09-01T10:00:00+00:00"
_SINCE = datetime(2026, 9, 2, tzinfo=UTC)


def _git(args: list[str], cwd: Path, env_extra: dict | None = None) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    if env_extra:
        env.update(env_extra)
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=env)


@pytest.fixture()
def repo_pair(tmp_path):
    """origin(带 backdate 的 A 提交)+ 本地 clone;返回 (origin, clone)。"""
    origin = tmp_path / "origin"
    origin.mkdir()
    back = {"GIT_AUTHOR_DATE": _BACKDATE, "GIT_COMMITTER_DATE": _BACKDATE}
    _git(["init", "-b", "main", "."], cwd=origin)
    (origin / "a.md").write_text("# A v1\n")
    _git(["add", "."], cwd=origin)
    _git(["commit", "-m", "A"], cwd=origin, env_extra=back)
    clone = tmp_path / "clone"
    _git(["clone", str(origin), str(clone)], cwd=tmp_path)
    return origin, clone


def _cfg(clone: Path, recovery: bool) -> SourceConfig:
    config = {
        "repo_url": "https://github.com/o/r.git",
        "clone_path": str(clone),
        "file_types": [".md"],
        "branches": ["main"],
    }
    if recovery:
        config["recovery_replay"] = True
    return SourceConfig(
        id="f16-src", type="github", product="p", config=config, enabled=True, sync_interval="24h"
    )


def _connector(clone: Path, recovery: bool, api_sha: str) -> GitHubConnector:
    """api_sha 模拟 GitHub API 返回值(纯网络边界 stub);
    git fetch/reset/log 行为全部走真实仓库。"""
    conn = GitHubConnector(_cfg(clone, recovery))
    import types

    conn._api_get_latest_sha = types.MethodType(lambda self, branch: api_sha, conn)
    return conn


def test_f16_recovery_replay_reads_git_history_despite_sha_shortcircuit(repo_pair):
    """Golden:clone HEAD 已推进到 B、API 短路成立时 ——
    普通 run 不读变更(bug 条件复现);恢复重放必须读出 B 并灌入。"""
    origin, clone = repo_pair

    # 上次成功同步以来的远端变更:commit B(当前时间)
    (origin / "b.md").write_text("# B new\n")
    _git(["add", "."], cwd=origin)
    _git(["commit", "-m", "B"], cwd=origin)
    # 模拟被中断的上一轮:fetch+reset 已把本地 HEAD 推进到 B,ingest 未完成
    _git(["fetch", "origin", "main"], cwd=clone)
    _git(["reset", "--hard", "origin/main"], cwd=clone)
    assert (clone / "b.md").exists()  # 工作区已是 B

    # 普通 run:API 已见 B、本地 HEAD 也已推进到 B → SHA 相等短路成立 → 空
    # (这正是要被恢复关闭的危险行为;真实事故面)
    origin_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=origin, check=True, capture_output=True, text=True
    ).stdout.strip()
    assert list(_connector(clone, recovery=False, api_sha=origin_sha).fetch_changes(_SINCE)) == []

    # 恢复重放:必须仍按 last-success 边界读 git 历史 → 补齐 b.md
    docs = list(_connector(clone, recovery=True, api_sha=origin_sha).fetch_changes(_SINCE))
    names = [d.metadata["path"] for d in docs]
    assert names == ["b.md"]
    assert docs[0].content == "# B new\n"


def test_f16_normal_run_unaffected_by_flag(repo_pair):
    """无恢复标记的普通 run 语义不变:API SHA ≠ 本地 HEAD 时照常读变更。"""
    origin, clone = repo_pair
    (origin / "b.md").write_text("# B new\n")
    _git(["add", "."], cwd=origin)
    _git(["commit", "-m", "B"], cwd=origin)
    # 不推进 clone(HEAD 停在 A)→ API(=origin HEAD)≠ 本地 → 正常读变更
    origin_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=origin, check=True, capture_output=True, text=True
    ).stdout.strip()
    docs = list(_connector(clone, recovery=False, api_sha=origin_sha).fetch_changes(_SINCE))
    assert [d.metadata["path"] for d in docs] == ["b.md"]
