"""#34 git 传输失败证据化分类 + 有界恢复退出码契约回归。

生产事故(RCA 2026-09-07/09-10):github.com:443 间歇性连接失败(~130s=
OS SYN 重试耗尽,git 子进程无任何超时),attempt=1/recovery=false 无有界
恢复 —— 业务失败被 sync.py 吞掉、runner 恒 0 退出,executor 重试面
(冻结契约 §14:只管进程级)永不触发。本文件锁定矫正:
1. ``_run_git`` 显式超时 + 传输类 stderr 证据模式 → ``GitTransportError``;
2. 非传输类 git 失败维持原 RuntimeError(分类不误伤);
3. runner 退出码契约:仅传输失败 → 2(落 executor 有界重试),业务失败 → 0;
4. token 脱敏在 GitTransportError 中保留。
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from backend.connectors.github import (
    GitTransportError,
    GitHubConnector,
    _git_timeout_seconds,
    _is_transport_failure,
)
from backend.connectors.registry import SourceConfig


def _connector() -> GitHubConnector:
    return GitHubConnector(
        SourceConfig(
            id="gh-x",
            type="github",
            product="p",
            enabled=True,
            config={
                "repo_url": "https://github.com/camthink-ai/x.git",
                "branches": ["main"],
                "clone_path": "/tmp/fake-clone-34",
            },
            sync_interval="1h",
        )
    )


# --------------------------------------------------------------------------- #
# 证据化分类
# --------------------------------------------------------------------------- #


class TestTransportClassification:
    def test_production_connect_failure_pattern_is_transport(self):
        # 2026-09-07 生产实测原文(run 1573)
        summary = (
            "fatal: unable to access 'https://github.com/camthink-ai/meta-hailo-os.git': "
            "Failed to connect to github.com port 443 after 130072 ms: Couldn't connect to server"
        )
        assert _is_transport_failure(summary) is True

    @pytest.mark.parametrize(
        "summary",
        [
            "fatal: unable to access '...': Could not resolve host: github.com",
            "fatal: unable to access '...': Connection timed out",
            "fatal: unable to access '...': gnutls_handshake() failed: TLS connection was not properly terminated",
            "error: RPC failed; curl 28 Operation timed out",
        ],
    )
    def test_transport_patterns(self, summary: str):
        assert _is_transport_failure(summary) is True

    @pytest.mark.parametrize(
        "summary",
        [
            "fatal: couldn't find remote ref v99",  # ref 不存在=契约失败
            "fatal: Authentication failed for 'https://github.com/'",  # 鉴权失败
            "fatal: not a git repository (or any of the parent directories)",  # 本地状态
        ],
    )
    def test_non_transport_failures(self, summary: str):
        assert _is_transport_failure(summary) is False


class TestGitTimeoutKnob:
    def test_default_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("GITHUB_GIT_TIMEOUT_SECONDS", raising=False)
        assert _git_timeout_seconds() == 900.0

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("GITHUB_GIT_TIMEOUT_SECONDS", "60")
        assert _git_timeout_seconds() == 60.0

    def test_nonpositive_disables(self, monkeypatch):
        monkeypatch.setenv("GITHUB_GIT_TIMEOUT_SECONDS", "0")
        assert _git_timeout_seconds() is None


# --------------------------------------------------------------------------- #
# _run_git 行为(subprocess 打桩,不触网)
# --------------------------------------------------------------------------- #


class TestRunGit:
    def test_transport_stderr_raises_git_transport_error(self):
        conn = _connector()
        with patch(
            "backend.connectors.github.subprocess.run",
            return_value=MagicMock(
                returncode=128,
                stderr=(
                    "fatal: unable to access 'https://github.com/camthink-ai/x.git': "
                    "Failed to connect to github.com port 443 after 130072 ms"
                ),
                stdout="",
            ),
        ):
            with pytest.raises(GitTransportError) as ei:
                conn._run_git(["fetch", "origin", "main"])
        assert "Failed to connect" in str(ei.value)

    def test_non_transport_stderr_raises_plain_runtime_error(self):
        conn = _connector()
        with patch(
            "backend.connectors.github.subprocess.run",
            return_value=MagicMock(
                returncode=128,
                stderr="fatal: couldn't find remote ref v99",
                stdout="",
            ),
        ):
            with pytest.raises(RuntimeError) as ei:
                conn._run_git(["fetch", "origin", "v99"])
        assert not isinstance(ei.value, GitTransportError)

    def test_timeout_expired_raises_transport_error(self):
        conn = _connector()
        with patch(
            "backend.connectors.github.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd=["git", "fetch"], timeout=900),
        ):
            with pytest.raises(GitTransportError) as ei:
                conn._run_git(["fetch", "origin", "main"])
        assert "传输超时" in str(ei.value)

    def test_token_redaction_preserved_in_transport_error(self):
        conn = _connector()
        conn._token = "ghp_secret_token_value"
        stderr = (
            "fatal: unable to access 'https://x-access-token:ghp_secret_token_value@github.com/': "
            "Failed to connect to github.com port 443"
        )
        with patch(
            "backend.connectors.github.subprocess.run",
            return_value=MagicMock(returncode=128, stderr=stderr, stdout=""),
        ):
            with pytest.raises(GitTransportError) as ei:
                conn._run_git(["fetch", "origin", "main"])
        message = str(ei.value)
        assert "ghp_secret_token_value" not in message
        assert "Failed to connect" in message


# --------------------------------------------------------------------------- #
# 退出码契约(main 层:传输失败=2,业务失败=0)
# --------------------------------------------------------------------------- #


def test_transport_failure_signals_nonzero_runner_exit(monkeypatch):
    """run_sync 报告传输失败 → main 以退出码 2 结束(落 executor 有界重试)。"""
    import scripts.sync as sync_mod

    async def fake_run_sync(settings, source_id=None, **kw):
        return True  # ≥1 源传输失败

    monkeypatch.setattr(sync_mod, "run_sync", fake_run_sync)
    with pytest.raises(SystemExit) as ei:
        sync_mod.main(["--source", "gh-broken"])
    assert ei.value.code == 2


def test_business_failure_still_exits_zero(monkeypatch):
    """纯业务失败(非传输)→ run_sync False → main 正常返回(契约 §14 不变)。"""
    import scripts.sync as sync_mod

    async def fake_run_sync(settings, source_id=None, **kw):
        return False

    monkeypatch.setattr(sync_mod, "run_sync", fake_run_sync)
    sync_mod.main([])  # 不抛 SystemExit = 退出码 0
