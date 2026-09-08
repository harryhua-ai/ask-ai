"""Issue #34A 多分支变更检测正确性(真实本地 git 仓,零外网)。

RCA(2026-09 只读取证)确认的缺陷:``_remote_has_updates`` 把远端分支 SHA 与
**单一移动 HEAD** 比较 —— 处理完分支 A 后 HEAD 停在 A 的提交,分支 B 的远端
SHA 必然 ≠ 该 HEAD → 未变更分支被恒判"有更新" → 多分支源每轮对每个分支执行
真实 git fetch/reset(Issue #34 网络事故的暴露放大器:2026-09-07 生产 3 个
多分支源吸收了全部 21 次连接失败,单分支源零失败)。

冻结合同(#34A):变更检测必须**分支特定** —— 分支 B 的远端状态只能与
B 自己的本地状态比较;B 的判定不得依赖先前处理过哪个分支、也不得依赖
当前 HEAD 归属。

网络操作验证:spy ``_run_git`` 计数真实 ``git fetch`` 次数(git 全部走本地
origin 仓,零外网;fetch 次数 = 网络操作次数的确定性代理)。reset 为本地
操作,不计入。
"""

import os
import subprocess
import types
from datetime import UTC, datetime
from pathlib import Path

import pytest

from backend.connectors.github import GitHubConnector
from backend.connectors.registry import SourceConfig

# 宽窗口:任何被读到的提交都落在窗口内(本文件的断言对象是 fetch 决策,不是窗口)
_SINCE = datetime(2020, 1, 1, tzinfo=UTC)


def _git(args: list[str], cwd: Path) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=env)


def _sha(ref: str, cwd: Path) -> str:
    out = subprocess.run(
        ["git", "rev-parse", ref], cwd=cwd, check=True, capture_output=True, text=True
    )
    return out.stdout.strip()


@pytest.fixture()
def origin_repo(tmp_path: Path) -> Path:
    """origin:main 与 release 两分支、tip 不同(跨分支污染可观测的前提)。"""
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(["init", "-b", "main", "."], cwd=origin)
    (origin / "main.md").write_text("# main v1\n")
    _git(["add", "."], cwd=origin)
    _git(["commit", "-m", "m1"], cwd=origin)
    _git(["branch", "release"], cwd=origin)
    _git(["checkout", "release"], cwd=origin)
    (origin / "rel.md").write_text("# rel v1\n")
    _git(["add", "."], cwd=origin)
    _git(["commit", "-m", "r1"], cwd=origin)
    _git(["checkout", "main"], cwd=origin)
    return origin


def _make_clone(origin: Path, tmp_path: Path, name: str) -> Path:
    clone = tmp_path / name
    _git(["clone", str(origin), str(clone)], cwd=tmp_path)
    return clone


def _tips(origin: Path) -> dict[str, str]:
    return {"main": _sha("refs/heads/main", origin), "release": _sha("refs/heads/release", origin)}


def _connector(clone: Path, branches: list[str], tips: dict[str, str]) -> GitHubConnector:
    """API 边界 stub(纯网络,返回 tips[branch]);git 行为全部走真实仓库。"""
    cfg = SourceConfig(
        id="mb-src",
        type="github",
        product="p",
        config={
            "repo_url": "https://github.com/o/r.git",
            "clone_path": str(clone),
            "file_types": [".md"],
            "branches": branches,
        },
        enabled=True,
        sync_interval="1h",
    )
    conn = GitHubConnector(cfg)
    conn._api_get_latest_sha = types.MethodType(lambda self, branch: tips[branch], conn)
    return conn


def _spy_fetch(conn: GitHubConnector) -> list[tuple[str, ...]]:
    """计数真实 git fetch 调用(网络操作代理),不拦截执行。"""
    ops: list[tuple[str, ...]] = []
    original = conn._run_git

    def spy(args: list[str], cwd=None):  # noqa: ANN001 - 测试 spy
        if args and args[0] == "fetch":
            ops.append(tuple(args))
        return original(args, cwd=cwd)

    conn._run_git = spy
    return ops


# ====================  A. 全分支未变更 → 零 fetch  ====================


def test_a_all_branches_unchanged_no_fetch(origin_repo, tmp_path):
    """所有配置分支都与远端一致 → 不因另一分支的 HEAD 而误判任何分支。"""
    clone = _make_clone(origin_repo, tmp_path, "clone_a")
    conn = _connector(clone, ["main", "release"], _tips(origin_repo))
    fetches = _spy_fetch(conn)

    assert list(conn.fetch_changes(_SINCE)) == []
    assert fetches == [], f"unchanged branches must not fetch, got {fetches}"

    # 第二轮(模拟整点常规扫描):仍然零 fetch
    assert list(conn.fetch_changes(_SINCE)) == []
    assert fetches == [], f"second cycle must not fetch either, got {fetches}"


# ====================  B. 单分支变更 → 只有它 fetch  ====================


def test_b_only_changed_branch_fetches(origin_repo, tmp_path):
    """仅 main 上游推进 → 只有 main 走同步路径;release 保持未变更判定。"""
    clone = _make_clone(origin_repo, tmp_path, "clone_b")
    (origin_repo / "main.md").write_text("# main v2\n")
    _git(["add", "."], cwd=origin_repo)
    _git(["commit", "-m", "m2"], cwd=origin_repo)
    tips = _tips(origin_repo)

    conn = _connector(clone, ["main", "release"], tips)
    fetches = _spy_fetch(conn)
    docs = list(conn.fetch_changes(_SINCE))

    assert [op[2] for op in fetches] == ["main"], f"only main should fetch, got {fetches}"
    assert any(d.metadata["path"] == "main.md" and d.branch == "main" for d in docs)


# ====================  C. 多分支同时变更 → 全部检出  ====================


def test_c_multiple_changed_branches_all_detected(origin_repo, tmp_path):
    """main 与 release 同时推进 → 两个分支都走同步路径。"""
    clone = _make_clone(origin_repo, tmp_path, "clone_c")
    _git(["checkout", "main"], cwd=origin_repo)
    (origin_repo / "main.md").write_text("# main v2\n")
    _git(["add", "."], cwd=origin_repo)
    _git(["commit", "-m", "m2"], cwd=origin_repo)
    _git(["checkout", "release"], cwd=origin_repo)
    (origin_repo / "rel.md").write_text("# rel v2\n")
    _git(["add", "."], cwd=origin_repo)
    _git(["commit", "-m", "r2"], cwd=origin_repo)
    _git(["checkout", "main"], cwd=origin_repo)
    tips = _tips(origin_repo)

    conn = _connector(clone, ["main", "release"], tips)
    fetches = _spy_fetch(conn)
    list(conn.fetch_changes(_SINCE))

    assert sorted(op[2] for op in fetches) == ["main", "release"]


# ====================  D. 分支顺序无关  ====================


def test_d_branch_order_independence(origin_repo, tmp_path):
    """配置顺序反转不得改变任何分支的 changed/unchanged 判定。"""
    # 先建 clone(旧上游状态),再推进 main —— 否则 clone 天生最新,零 fetch 才是正确行为
    clone_a = _make_clone(origin_repo, tmp_path, "clone_order_1")
    clone_b = _make_clone(origin_repo, tmp_path, "clone_order_2")
    (origin_repo / "main.md").write_text("# main v2\n")
    _git(["add", "."], cwd=origin_repo)
    _git(["commit", "-m", "m2"], cwd=origin_repo)
    tips = _tips(origin_repo)

    conn_a = _connector(clone_a, ["main", "release"], tips)
    fetches_a = _spy_fetch(conn_a)
    list(conn_a.fetch_changes(_SINCE))

    conn_b = _connector(clone_b, ["release", "main"], tips)
    fetches_b = _spy_fetch(conn_b)
    list(conn_b.fetch_changes(_SINCE))

    assert sorted(op[2] for op in fetches_a) == ["main"]
    assert sorted(op[2] for op in fetches_b) == ["main"]


# ====================  E. HEAD 归属无关(缺陷直接复现)  ====================


def test_e_checkout_state_independence(origin_repo, tmp_path):
    """把 clone HEAD 挪到 release 分支后:未变更的 main 不得因 HEAD≠main 被误判。

    这正是被修缺陷的直接复现:旧实现以 rev-parse HEAD 为基准,HEAD 停在
    release → main 的远端 SHA ≠ HEAD → 无变更的 main 被真实 fetch。
    """
    clone = _make_clone(origin_repo, tmp_path, "clone_e")
    _git(["checkout", "release"], cwd=clone)  # HEAD 归属:release
    tips = _tips(origin_repo)

    conn = _connector(clone, ["main", "release"], tips)
    fetches = _spy_fetch(conn)

    assert list(conn.fetch_changes(_SINCE)) == []
    assert fetches == [], f"HEAD ownership must not cause fetch, got {fetches}"


# ====================  F. 首同步 / 缺失本地分支状态 → 安全同步  ====================


def test_f_missing_tracking_ref_safe_sync(origin_repo, tmp_path):
    """本地无该分支远端跟踪状态(首同步语义)→ 安全 fetch;之后恢复短路。"""
    clone = _make_clone(origin_repo, tmp_path, "clone_f")
    _git(["update-ref", "-d", "refs/remotes/origin/release"], cwd=clone)
    tips = _tips(origin_repo)

    conn = _connector(clone, ["main", "release"], tips)
    fetches = _spy_fetch(conn)
    list(conn.fetch_changes(_SINCE))

    assert [op[2] for op in fetches] == [
        "release"
    ], f"missing local branch state must trigger safe sync, got {fetches}"

    # 第二轮:跟踪 ref 已由该次 fetch 重建 → 恢复零 fetch
    assert list(conn.fetch_changes(_SINCE)) == []
    assert [op[2] for op in fetches] == ["release"]


# ====================  G. 远端检视失败 → 既有降级语义  ====================


def test_g_api_failure_degrades_to_fetch_per_branch(origin_repo, tmp_path):
    """API 感知异常 → 降级为每分支直接 fetch(既有安全行为,不阻断)。"""
    clone = _make_clone(origin_repo, tmp_path, "clone_g")
    conn = _connector(clone, ["main", "release"], _tips(origin_repo))
    conn._api_get_latest_sha = types.MethodType(
        lambda self, branch: (_ for _ in ()).throw(RuntimeError("API down")), conn
    )
    fetches = _spy_fetch(conn)
    list(conn.fetch_changes(_SINCE))

    assert sorted(op[2] for op in fetches) == ["main", "release"]


# ====================  H. fetch 失败错误语义不回归  ====================


def test_h_fetch_failure_raises_runtime_error(origin_repo, tmp_path):
    """fetch 网络失败 → RuntimeError(脱敏摘要)向上传播,由 sync_one 捕获。

    前提:main 有真实变更(否则未变更分支被正确跳过,不会触发 fetch)。
    """
    clone = _make_clone(origin_repo, tmp_path, "clone_h")
    (origin_repo / "main.md").write_text("# main v2\n")
    _git(["add", "."], cwd=origin_repo)
    _git(["commit", "-m", "m2"], cwd=origin_repo)
    _git(["remote", "set-url", "origin", "/nonexistent-repo-xyz"], cwd=clone)
    conn = _connector(clone, ["main", "release"], _tips(origin_repo))

    with pytest.raises(RuntimeError, match="fetch origin main"):
        list(conn.fetch_changes(_SINCE))
