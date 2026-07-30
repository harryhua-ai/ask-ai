"""GitHubConnector 测试。

单元测试验证注册、过滤逻辑与核心抓取路径(基于 fake httpx.Client);
集成测试验证对真实 GitHub API 的拉取能力
(需要 ``GITHUB_TOKEN`` 与网络,缺则跳过)。
"""

import base64
import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Self

import httpx
import pytest

from backend.connectors.github import GitHubConnector  # 触发 @register 副作用
from backend.connectors.registry import ConnectorRegistry, SourceConfig

# 测试用固定内容
CONTENT_RAW = "# Hello World\nThis is a test doc."
CONTENT_B64 = base64.b64encode(CONTENT_RAW.encode()).decode()


class _FakeResponse:
    """httpx.Response 的最小替身。"""

    def __init__(self, data: Any = None, status_code: int = 200) -> None:
        self._data = data
        self.status_code = status_code

    def json(self) -> Any:
        if self._data is None:
            raise ValueError("no JSON body")
        return self._data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("GET", "https://fake.local"),
                response=httpx.Response(self.status_code),
            )


# 路由谓词签名:(url, params) -> bool
RouteMatcher = Callable[[str, dict | None], bool]
# 路由三元组:(matcher, response_data, status_code)
Route = tuple[RouteMatcher, Any, int]


class _FakeClient:
    """httpx.Client 的最小替身,按路由表匹配 URL 返回预设响应。"""

    def __init__(self, routes: list[Route]) -> None:
        self._routes = routes
        self.calls: list[tuple[str, dict | None]] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def get(self, url: str, params: dict | None = None) -> _FakeResponse:
        self.calls.append((url, params))
        for matcher, data, status in self._routes:
            if matcher(url, params):
                return _FakeResponse(data, status)
        raise AssertionError(f"Unexpected GET {url} params={params}")


class _FakeClientFactory:
    """替代 ``httpx.Client`` 构造器,每次实例化返回共享路由表的 fake client。"""

    def __init__(self, routes: list[Route]) -> None:
        self.routes = routes

    def __call__(self, **_kwargs: object) -> _FakeClient:
        # 忽略 timeout/headers 等真实参数,测试不依赖传输层
        return _FakeClient(self.routes)


@pytest.fixture
def fake_httpx(monkeypatch: pytest.MonkeyPatch) -> list[Route]:
    """注入 fake httpx.Client,返回可填充的路由表。"""
    routes: list[Route] = []
    monkeypatch.setattr("backend.connectors.github.httpx.Client", _FakeClientFactory(routes))
    return routes


def _make_config(**overrides: object) -> SourceConfig:
    """构造默认 GitHub SourceConfig,允许测试覆盖字段。"""
    config: dict[str, object] = {
        "owner": "octocat",
        "repo": "Hello-World",
        "branch": "main",
        "file_types": [".md"],
        "include_dirs": ["docs", "README.md"],
    }
    config.update(overrides)  # type: ignore[arg-type]
    return SourceConfig(
        id="github-test",
        type="github",
        product="test",
        enabled=True,
        config=config,  # type: ignore[arg-type]
        sync_interval="1h",
    )


# --- URL 匹配谓词(便于测试声明路由)---


def _matches_tree(url: str, _params: dict | None) -> bool:
    return "/git/trees/" in url


def _matches_list_commits(url: str, params: dict | None) -> bool:
    # list commits 调用带 params(since/sha/per_page),URL 以 /commits 结尾
    return url.endswith("/commits") and params is not None


def _make_commit_detail_matcher(sha: str) -> RouteMatcher:
    def _m(url: str, _params: dict | None) -> bool:
        return url.endswith(f"/commits/{sha}")

    return _m


def _make_contents_matcher(path: str) -> RouteMatcher:
    def _m(url: str, _params: dict | None) -> bool:
        return f"/contents/{path}?" in url or url.endswith(f"/contents/{path}")

    return _m


# ====================  单元测试  ====================


@pytest.mark.unit
def test_github_connector_registered() -> None:
    """注册装饰器应将 "github" 类型绑定到 ConnectorRegistry。"""
    assert "github" in ConnectorRegistry._connectors


@pytest.mark.unit
def test_github_connector_construct_and_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """构造器应正确解析 config,过滤逻辑应遵循 file_types/include_dirs。"""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    config = _make_config()
    connector = ConnectorRegistry.create(config)

    assert connector.source_id == "github-test"
    assert connector.product == "test"

    # 命中 include_dirs 中的目录前缀
    assert connector._should_include("docs/intro.md") is True
    # 命中 include_dirs 中的精确文件路径
    assert connector._should_include("README.md") is True
    # 后缀不在白名单
    assert connector._should_include("docs/intro.txt") is False
    # 不在 include_dirs 范围内
    assert connector._should_include("src/main.py") is False
    # AUTO_EXCLUDE 命中
    assert connector._should_include("node_modules/foo.md") is False


@pytest.mark.unit
def test_github_connector_splitext_for_dotfiles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_should_include`` 应使用 os.path.splitext,正确处理 dotfile 与含点目录。"""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    # 不限制 include_dirs,只校验后缀逻辑
    config = _make_config(include_dirs=[], file_types=[".md"])
    connector = ConnectorRegistry.create(config)

    # dotfile 无扩展名 → 不应误判为 .md
    assert connector._should_include(".gitignore") is False
    # 目录名含点但文件是 .md → 应保留
    assert connector._should_include("docs/v1.2/intro.md") is True
    # 路径末段无扩展名
    assert connector._should_include("Makefile") is False


@pytest.mark.unit
def test_github_connector_headers_immutable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """无 token 时 headers 不应包含 Authorization 键(不可变构造验证)。"""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    config = _make_config()
    connector = ConnectorRegistry.create(config)

    assert "Authorization" not in connector._headers
    assert connector._headers["Accept"] == "application/vnd.github+json"
    assert connector._headers["X-GitHub-Api-Version"] == "2022-11-28"

    # 有 token 时 Authorization 出现一次
    monkeypatch.setenv("GITHUB_TOKEN", "fake-token-abc")
    connector2 = GitHubConnector(_make_config())
    assert connector2._headers["Authorization"] == "Bearer fake-token-abc"


@pytest.mark.unit
def test_fetch_all_yields_documents(
    fake_httpx: list[Route], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``fetch_all`` 应基于 tree + contents API yield 出正确的 RawDocument。"""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    connector = ConnectorRegistry.create(_make_config())

    # 路由 1:git tree 返回 1 个 blob
    fake_httpx.append(
        (
            _matches_tree,
            {
                "tree": [
                    {"type": "blob", "path": "README.md"},
                    {"type": "tree", "path": "docs"},  # 非 blob,跳过
                    {"type": "blob", "path": "docs/skip.txt"},  # 后缀不符
                ],
                "truncated": False,
            },
            200,
        )
    )
    # 路由 2:README.md 内容
    fake_httpx.append(
        (
            _make_contents_matcher("README.md"),
            {"content": CONTENT_B64, "encoding": "base64"},
            200,
        )
    )

    docs = list(connector.fetch_all())
    assert len(docs) == 1
    doc = docs[0]
    assert doc.source_type == "github"
    assert doc.product == "test"
    assert doc.title == "README"
    assert doc.content == CONTENT_RAW
    assert doc.source_id == "octocat/Hello-World/README.md"
    assert doc.url == "https://github.com/octocat/Hello-World/blob/main/README.md"
    assert doc.metadata["repo"] == "octocat/Hello-World"
    assert doc.metadata["branch"] == "main"
    assert doc.metadata["path"] == "README.md"
    # SHA256 哈希长度
    assert len(doc.content_hash) == 64


@pytest.mark.unit
def test_fetch_all_truncated_warns(
    fake_httpx: list[Route],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``_fetch_tree`` 检测到 truncated=true 时应记 warning。"""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    connector = ConnectorRegistry.create(_make_config())

    fake_httpx.append(
        (
            _matches_tree,
            {"tree": [], "truncated": True},
            200,
        )
    )

    with caplog.at_level("WARNING", logger="backend.connectors.github"):
        list(connector.fetch_all())

    assert any("truncated" in r.message.lower() for r in caplog.records)


@pytest.mark.unit
def test_fetch_changes_returns_changed(
    fake_httpx: list[Route], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``fetch_changes`` 应通过 list commits + commit detail 收集变更文件。

    覆盖修复路径:GitHub List Commits API 响应**不含** files 字段,
    必须额外调用单 commit 详情 API。
    """
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    connector = ConnectorRegistry.create(_make_config())

    # 路由 1:list commits(响应不含 files 字段,模拟真实 GitHub 行为)
    fake_httpx.append(
        (
            _matches_list_commits,
            [{"sha": "abc123", "commit": {"message": "update"}}],
            200,
        )
    )
    # 路由 2:commit detail,files 字段含 modified 状态
    fake_httpx.append(
        (
            _make_commit_detail_matcher("abc123"),
            {
                "sha": "abc123",
                "files": [
                    {"filename": "docs/intro.md", "status": "modified"},
                    {"filename": "src/skip.py", "status": "added"},  # 后缀不符
                    {"filename": "docs/removed.md", "status": "removed"},
                ],
            },
            200,
        )
    )
    # 路由 3:docs/intro.md 内容
    fake_httpx.append(
        (
            _make_contents_matcher("docs/intro.md"),
            {"content": CONTENT_B64, "encoding": "base64"},
            200,
        )
    )

    since = datetime(2026, 1, 1, tzinfo=UTC)
    docs = list(connector.fetch_changes(since))
    assert len(docs) == 1
    doc = docs[0]
    assert doc.source_id == "octocat/Hello-World/docs/intro.md"
    assert doc.content == CONTENT_RAW
    assert doc.title == "intro"


@pytest.mark.unit
def test_fetch_deleted_returns_removed(
    fake_httpx: list[Route], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``fetch_deleted`` 应返回 status=='removed' 文件的 source_id 列表。"""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    connector = ConnectorRegistry.create(_make_config())

    fake_httpx.append(
        (
            _matches_list_commits,
            [{"sha": "deadbeef"}],
            200,
        )
    )
    fake_httpx.append(
        (
            _make_commit_detail_matcher("deadbeef"),
            {
                "files": [
                    {"filename": "docs/old.md", "status": "removed"},
                    {"filename": "docs/keep.md", "status": "modified"},
                    {"filename": "src/old.py", "status": "removed"},  # 后缀不符
                ],
            },
            200,
        )
    )

    since = datetime(2026, 1, 1, tzinfo=UTC)
    deleted = connector.fetch_deleted(since)
    assert deleted == ["octocat/Hello-World/docs/old.md"]


@pytest.mark.unit
def test_fetch_changes_handles_no_files(
    fake_httpx: list[Route], monkeypatch: pytest.MonkeyPatch
) -> None:
    """关键回归:list commits 与 commit detail 响应均不含 files 字段时不应报错。

    模拟修复前的 bug 触发条件(GitHub List Commits API 永远不返回 files),
    断言 fetch_changes 不抛异常且 yield 为空。
    """
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    connector = ConnectorRegistry.create(_make_config())

    # list commits 响应不含 files 字段(真实 GitHub 行为)
    fake_httpx.append(
        (
            _matches_list_commits,
            [{"sha": "abc", "commit": {"message": "x"}}],
            200,
        )
    )
    # commit detail 响应也无 files 字段(例如空 merge commit)
    fake_httpx.append(
        (
            _make_commit_detail_matcher("abc"),
            {"sha": "abc", "commit": {"message": "x"}},
            200,
        )
    )

    since = datetime(2026, 1, 1, tzinfo=UTC)
    docs = list(connector.fetch_changes(since))
    assert docs == []


@pytest.mark.unit
def test_fetch_file_content_handles_large_file(
    fake_httpx: list[Route], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``_fetch_file_content`` 检测到 >1 MB 错误时应抛 ValueError 跳过。"""
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    connector = ConnectorRegistry.create(_make_config())

    # 模拟 GitHub 对 >1 MB 文件的 403 响应
    fake_httpx.append(
        (
            _make_contents_matcher("README.md"),
            {"message": "This API returns blobs up to 1 MB in size"},
            403,
        )
    )

    with pytest.raises(ValueError, match="exceeds 1 MB"):
        connector._fetch_file_content("README.md")


# ====================  集成测试  ====================


@pytest.mark.integration
def test_github_fetch_wiki_docs() -> None:
    """集成测试:拉取 camthink-ai/wiki-documents 的 README。"""
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        pytest.skip("GITHUB_TOKEN not set")

    config = SourceConfig(
        id="github-wiki-test",
        type="github",
        product="wiki",
        enabled=True,
        config={
            "owner": "camthink-ai",
            "repo": "wiki-documents",
            "branch": "main",
            "file_types": [".md"],
            "include_dirs": ["README.md"],
        },
        sync_interval="1h",
    )
    connector = ConnectorRegistry.create(config)
    docs = list(connector.fetch_all())
    assert len(docs) > 0
    assert all(d.source_type == "github" for d in docs)


# --------------------------------------------------------------------------- #
# Phase 2A Task 5: GitHubConnector 透传 channel_visibility
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_github_connector_passes_channel_visibility():
    """GitHubConnector 应把 SourceConfig.channel_visibility 透传到 RawDocument。"""
    from backend.connectors.github import GitHubConnector

    cfg = SourceConfig(
        id="test", type="github", product="test", enabled=True,
        config={"owner": "o", "repo": "r", "branch": "main"},
        sync_interval="1h",
        channel_visibility=("api",),
    )
    connector = GitHubConnector(cfg)
    doc = connector._make_document("path/to/file.md", "content")
    assert doc.channel_visibility == ("api",)


@pytest.mark.unit
def test_github_connector_default_channel_visibility():
    """SourceConfig 未指定 channel_visibility 时,RawDocument 默认 ('widget','api')。"""
    from backend.connectors.github import GitHubConnector

    cfg = SourceConfig(
        id="test", type="github", product="test", enabled=True,
        config={"owner": "o", "repo": "r"},
        sync_interval="1h",
    )
    connector = GitHubConnector(cfg)
    doc = connector._make_document("file.md", "content")
    assert doc.channel_visibility == ("widget", "api")
