"""GitHubConnector 测试。

单元测试验证注册;集成测试验证对真实 GitHub API 的拉取能力
(需要 ``GITHUB_TOKEN`` 与网络,缺则跳过)。
"""

import os

import pytest

from backend.connectors.github import GitHubConnector  # noqa: F401  # 触发注册
from backend.connectors.registry import ConnectorRegistry, SourceConfig


@pytest.mark.unit
def test_github_connector_registered():
    """注册装饰器应将 "github" 类型绑定到 ConnectorRegistry。"""
    assert "github" in ConnectorRegistry._connectors


@pytest.mark.unit
def test_github_connector_construct_and_filter(monkeypatch):
    """构造器应正确解析 config,过滤逻辑应遵循 file_types/include_dirs。"""
    # 避免 GITHUB_TOKEN 泄漏到测试环境
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    config = SourceConfig(
        id="github-test",
        type="github",
        product="test",
        enabled=True,
        config={
            "owner": "octocat",
            "repo": "Hello-World",
            "branch": "main",
            "file_types": [".md"],
            "include_dirs": ["docs", "README.md"],
        },
        sync_interval="1h",
    )
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


@pytest.mark.integration
def test_github_fetch_wiki_docs():
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
