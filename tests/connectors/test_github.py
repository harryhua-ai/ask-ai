"""GitHubConnector 测试(统一 git 类型 + clone/fetch/reset + API SHA 感知)。

设计:
- mock subprocess(git CLI)+ httpx(GitHub API),不触真实 GitHub。
- Real-Run clone/fetch/reset 链路验证(Task 6)用本地 git 仓库模拟,
  不在此文件(避免网络/真实 GitHub 依赖)。

覆盖的决策(spec 收敛):
- 1A/2A:github 为唯一 git 源类型(local_git 降为实现细节)。
- 3A:fetch+reset --hard 修 staleness bug(非 checkout)。
- 4A:clone 不可用报错不降级。
- API SHA 感知:远端 SHA == 本地 → 跳过 fetch;API 故障 → 降级 True。
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

import backend.connectors.github  # noqa: F401 — 触发 @register("github")
from backend.connectors.registry import ConnectorRegistry, SourceConfig


@pytest.fixture(autouse=True)
def _isolate_github_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """每个测试前清理 GITHUB_TOKEN,避免真实 env 泄漏影响断言。"""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)


def _make_config(**overrides: object) -> SourceConfig:
    """构造默认 GitHub SourceConfig(new schema: repo_url / branches / clone_path)。"""
    config: dict[str, object] = {
        "repo_url": "https://github.com/camthink-ai/ne301.git",
        "branches": ["main"],
        "file_types": [".py", ".md"],
        "clone_path": "/tmp/fake-clone",
    }
    config.update(overrides)  # type: ignore[arg-type]
    return SourceConfig(
        id="ne301",
        type="github",
        product="ne301",
        enabled=True,
        config=config,  # type: ignore[arg-type]
        sync_interval="1h",
    )


# ====================  注册与 repo_url 解析  ====================


@pytest.mark.unit
def test_github_registered() -> None:
    """@register 应将 "github" 绑定到 ConnectorRegistry。"""
    assert "github" in ConnectorRegistry._connectors


@pytest.mark.unit
def test_github_repo_url_parsing() -> None:
    """repo_url → (owner, repo) 解析(支持可选 .git 后缀)。"""
    conn = ConnectorRegistry.create(_make_config())
    assert conn._owner == "camthink-ai"
    assert conn._repo == "ne301"


@pytest.mark.unit
def test_github_repo_url_parsing_no_git_suffix() -> None:
    """repo_url 不带 .git 后缀也应正确解析。"""
    conn = ConnectorRegistry.create(
        _make_config(repo_url="https://github.com/camthink-ai/wiki-documents")
    )
    assert conn._owner == "camthink-ai"
    assert conn._repo == "wiki-documents"


# ====================  clone 管理(全新能力)  ====================


@pytest.mark.unit
def test_github_ensure_cloned_first_time(tmp_path) -> None:
    """clone_path 不存在 → git clone 被调。"""
    clone_path = str(tmp_path / "new-clone")
    conn = ConnectorRegistry.create(_make_config(clone_path=clone_path))
    with patch("backend.connectors.github.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        conn._ensure_cloned("main")
    assert any("clone" in str(call.args[0]) for call in mock_run.call_args_list)


@pytest.mark.unit
def test_github_ensure_cloned_exists_no_op(tmp_path) -> None:
    """clone_path 已存在 → 不 clone(no-op)。"""
    conn = ConnectorRegistry.create(_make_config(clone_path=str(tmp_path)))
    with patch("backend.connectors.github.subprocess.run") as mock_run:
        conn._ensure_cloned("main")
    mock_run.assert_not_called()


@pytest.mark.unit
def test_github_ensure_cloned_failure_raises(tmp_path) -> None:
    """clone 失败 → 报 RuntimeError(token 脱敏 + stderr 摘要),不降级逐文件 API。"""
    conn = ConnectorRegistry.create(_make_config(clone_path=str(tmp_path / "fail")))
    with patch(
        "backend.connectors.github.subprocess.run",
        side_effect=subprocess.CalledProcessError(1, "git"),
    ), pytest.raises(RuntimeError):
        conn._ensure_cloned("main")


@pytest.mark.unit
def test_github_clone_failure_redacts_token_and_reports_stderr(monkeypatch, tmp_path) -> None:
    """clone 失败错误信息:含 stderr 真因、不含明文 token(C10 A2 安全断言)。"""
    from subprocess import CalledProcessError

    token = "ghp_SECRET123"
    monkeypatch.setenv("GITHUB_TOKEN", token)
    stderr_text = (
        "Cloning into 'demo'...\n"
        "fatal: could not read Username for "
        f"'https://x-access-token:{token}@github.com': terminal prompts disabled"
    )

    def _boom(*args, **kwargs):
        raise CalledProcessError(128, args[0], stderr=stderr_text)

    conn = ConnectorRegistry.create(_make_config(clone_path=str(tmp_path / "c10")))
    monkeypatch.setattr("backend.connectors.github.subprocess.run", _boom)

    with pytest.raises(RuntimeError) as exc_info:
        conn._ensure_cloned("main")

    msg = str(exc_info.value)
    assert "fatal: could not read Username" in msg  # stderr 真因保留
    assert token not in msg  # 明文 token 必须脱敏
    assert "x-access-token:***@" in msg  # 鉴权 URL 保留脱敏形态(可诊断)



# ====================  fetch + reset 同步(修 staleness bug)  ====================


@pytest.mark.unit
def test_github_git_sync_branch_fetch_and_reset(tmp_path) -> None:
    """_git_sync_branch = git fetch + git reset --hard(非 checkout,修 staleness)。"""
    conn = ConnectorRegistry.create(_make_config(clone_path=str(tmp_path)))
    with patch("backend.connectors.github.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        conn._git_sync_branch("main")
    cmds = [str(call.args[0]) for call in mock_run.call_args_list]
    assert any("fetch" in c for c in cmds)
    assert any("reset" in c and "--hard" in c for c in cmds)
    # 不应使用 checkout(旧 local_git 方式,有 staleness bug)
    assert all("checkout" not in c for c in cmds), f"unexpected checkout in {cmds}"


# ====================  API SHA 感知  ====================


@pytest.mark.unit
def test_github_remote_has_updates_sha_diff(tmp_path) -> None:
    """API SHA != 本地 HEAD → True(需 fetch)。"""
    conn = ConnectorRegistry.create(_make_config(clone_path=str(tmp_path)))
    with (
        patch.object(conn, "_api_get_latest_sha", return_value="remote-abc"),
        patch.object(conn, "_git_local_sha", return_value="local-xyz"),
    ):
        assert conn._remote_has_updates("main") is True


@pytest.mark.unit
def test_github_remote_has_updates_sha_same(tmp_path) -> None:
    """API SHA == 本地 HEAD → False(跳过 fetch)。"""
    conn = ConnectorRegistry.create(_make_config(clone_path=str(tmp_path)))
    with (
        patch.object(conn, "_api_get_latest_sha", return_value="same-sha"),
        patch.object(conn, "_git_local_sha", return_value="same-sha"),
    ):
        assert conn._remote_has_updates("main") is False


@pytest.mark.unit
def test_github_remote_has_updates_api_failure_degrade(tmp_path) -> None:
    """API 异常 → True(降级触发 fetch,不阻断同步)。"""
    conn = ConnectorRegistry.create(_make_config(clone_path=str(tmp_path)))
    with (
        patch.object(conn, "_api_get_latest_sha", side_effect=RuntimeError("API down")),
        patch.object(conn, "_git_local_sha", return_value="any"),
    ):
        assert conn._remote_has_updates("main") is True


# ====================  私有仓库 token  ====================


@pytest.mark.unit
def test_github_private_repo_token_in_url(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """私有仓库:clone URL 内嵌 x-access-token:{token}@。

    token 在 __init__ 时从 env 固化到 self._token,故需在 create 前 setenv。
    """
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test123")
    conn = ConnectorRegistry.create(_make_config(clone_path=str(tmp_path / "priv")))
    url = conn._authed_url()
    assert "x-access-token:ghp_test123@" in url


@pytest.mark.unit
def test_github_public_repo_no_token(tmp_path) -> None:
    """无 token:URL 原样(不加 x-access-token)。"""
    conn = ConnectorRegistry.create(_make_config(clone_path=str(tmp_path / "pub")))
    url = conn._authed_url()
    assert "x-access-token" not in url
    assert url == "https://github.com/camthink-ai/ne301.git"


# ====================  RawDocument 字段 + channel_visibility 透传  ====================


@pytest.mark.unit
def test_github_make_document_fields_and_visibility(tmp_path) -> None:
    """_make_document:source_type='github'(统一) + branch + channel_visibility 透传。"""
    conn = ConnectorRegistry.create(_make_config(clone_path=str(tmp_path)))
    doc = conn._make_document("src/main.py", "print('hi')\n", "main")
    assert doc.source_type == "github"  # 统一类型,非 local_git
    assert doc.branch == "main"
    assert doc.source_id == "ne301/main/src/main.py"
    assert doc.channel_visibility == ("widget", "api")  # SourceConfig 默认透传
    assert doc.url == "https://github.com/camthink-ai/ne301/blob/main/src/main.py"
    assert len(doc.content_hash) == 64


@pytest.mark.unit
def test_github_make_document_custom_visibility(tmp_path) -> None:
    """SourceConfig 指定 channel_visibility 时,_make_document 应透传。"""
    cfg = _make_config(clone_path=str(tmp_path))
    # 直接用 SourceConfig 构造带自定义 channel_visibility的配置
    from backend.connectors.github import GitHubConnector

    custom_cfg = SourceConfig(
        id="ne301",
        type="github",
        product="ne301",
        enabled=True,
        config={
            "repo_url": "https://github.com/camthink-ai/ne301.git",
            "branches": ["main"],
            "file_types": [".py"],
            "clone_path": str(tmp_path),
        },
        sync_interval="1h",
        channel_visibility=("api",),
    )
    conn = GitHubConnector(custom_cfg)
    doc = conn._make_document("a.py", "x", "main")
    assert doc.channel_visibility == ("api",)


# ====================  local_git 不再注册(决策 2A)  ====================


@pytest.mark.unit
def test_local_git_not_registered() -> None:
    """决策 2A:local_git 移除 @register 后不应出现在 ConnectorRegistry。

    显式 import local_git 模块,确保即便有人误加回 @register 也会被本测试拦截。
    """
    import backend.connectors.local_git  # noqa: F401
    assert "local_git" not in ConnectorRegistry._connectors

