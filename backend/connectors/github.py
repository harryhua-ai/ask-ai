"""GitHub 数据源 Connector。

通过 GitHub REST API 拉取指定仓库的文件,支持:
- 全量抓取(基于 git tree 递归列举)
- 增量抓取(基于 commits 增量列表)
- 删除检测(基于 commits 中 status == "removed" 的文件)

过滤规则:
- 文件后缀白名单(默认 ``.md``)
- 自动排除常见无关目录(node_modules、.git、__pycache__ 等)
- 可选 ``include_dirs`` 白名单(仅保留指定前缀的路径)
- 可选 ``exclude_regex`` 黑名单(自定义正则)
"""

import base64
import hashlib
import logging
import os
import re
from collections.abc import Iterator
from datetime import datetime

import httpx

from backend.connectors.base import RawDocument
from backend.connectors.registry import ConnectorRegistry, SourceConfig

logger = logging.getLogger(__name__)

# 支持的文件后缀白名单(覆盖常见文档与代码文件)
SUPPORTED_FILE_TYPES: set[str] = {
    ".md",
    ".mdx",
    ".txt",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".rs",
    ".c",
    ".h",
    ".cpp",
    ".hpp",
    ".go",
    ".java",
    ".json",
    ".yaml",
    ".yml",
    ".sh",
    ".ipynb",
}

# 默认排除的目录正则(匹配路径片段即跳过)
AUTO_EXCLUDE = re.compile(
    r"(node_modules|\.next|\.git|__pycache__|venv|\.venv|\.tox|dist|build)/",
    re.IGNORECASE,
)


@ConnectorRegistry.register("github")
class GitHubConnector:
    """基于 GitHub REST API 的数据源 Connector。

    通过 ``SourceConfig.config`` 提供以下参数:

    - ``owner`` (str, 必填): 仓库所有者(用户或组织)。
    - ``repo`` (str, 必填): 仓库名称。
    - ``branch`` (str, 可选): 分支名,默认 ``main``。
    - ``file_types`` (list[str], 可选): 文件后缀白名单,默认 ``[".md"]``。
    - ``include_dirs`` (list[str], 可选): 路径前缀白名单;为空表示不限制。
    - ``exclude_regex`` (str, 可选): 自定义排除正则。

    GitHub Token 从 ``GITHUB_TOKEN`` 环境变量读取;未设置时以匿名方式调用
    (受 GitHub 速率限制约束)。
    """

    def __init__(self, config: SourceConfig) -> None:
        self._config = config
        self._owner: str = config.config["owner"]
        self._repo: str = config.config["repo"]
        self._branch: str = config.config.get("branch", "main")
        self._file_types: set[str] = set(config.config.get("file_types", [".md"]))
        self._include_dirs: list[str] = config.config.get("include_dirs", [])
        self._exclude_regex: str | None = config.config.get("exclude_regex")
        self._token: str = os.environ.get("GITHUB_TOKEN", "")
        self._headers: dict[str, str] = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            self._headers["Authorization"] = f"Bearer {self._token}"
        self._exclude_pattern: re.Pattern[str] | None = (
            re.compile(self._exclude_regex) if self._exclude_regex else None
        )

    @property
    def source_id(self) -> str:
        return self._config.id

    @property
    def product(self) -> str:
        return self._config.product

    def _api_url(self, path: str) -> str:
        """构造 GitHub Contents API URL(指定分支)。"""
        return (
            f"https://api.github.com/repos/{self._owner}/{self._repo}"
            f"/contents/{path}?ref={self._branch}"
        )

    def _fetch_tree(self) -> list[dict]:
        """递归拉取分支的 git tree,返回 tree 节点列表。"""
        url = (
            f"https://api.github.com/repos/{self._owner}/{self._repo}"
            f"/git/trees/{self._branch}?recursive=1"
        )
        with httpx.Client(timeout=30, headers=self._headers) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.json().get("tree", [])

    def _should_include(self, path: str) -> bool:
        """判断给定路径是否应被纳入抓取范围。"""
        if AUTO_EXCLUDE.search(path):
            return False
        if self._exclude_pattern and self._exclude_pattern.search(path):
            return False
        if self._include_dirs and not any(
            # include_dirs 既支持目录前缀,也支持精确文件路径
            path.startswith(d.rstrip("/")) or path == d
            for d in self._include_dirs
        ):
            return False
        ext = "." + path.rsplit(".", 1)[-1] if "." in path else ""
        return ext in self._file_types

    def _fetch_file_content(self, path: str) -> str:
        """通过 Contents API 拉取单个文件内容(自动处理 base64 解码)。"""
        with httpx.Client(timeout=30, headers=self._headers) as client:
            resp = client.get(self._api_url(path))
            resp.raise_for_status()
            data = resp.json()
            if data.get("encoding") == "base64":
                return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
            return data.get("content", "")

    def _make_document(self, path: str, content: str) -> RawDocument:
        """根据路径与内容构造 RawDocument。"""
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        title = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        url = f"https://github.com/{self._owner}/{self._repo}" f"/blob/{self._branch}/{path}"
        return RawDocument(
            source_id=f"{self._owner}/{self._repo}/{path}",
            source_type="github",
            product=self.product,
            title=title,
            content=content,
            url=url,
            metadata={
                "repo": f"{self._owner}/{self._repo}",
                "branch": self._branch,
                "path": path,
            },
            content_hash=content_hash,
        )

    def fetch_all(self) -> Iterator[RawDocument]:
        """全量抓取:遍历 git tree,逐个拉取符合条件的 blob 文件。"""
        tree = self._fetch_tree()
        for item in tree:
            if item["type"] != "blob":
                continue
            path = item["path"]
            if not self._should_include(path):
                continue
            try:
                content = self._fetch_file_content(path)
                yield self._make_document(path, content)
            except Exception as e:  # noqa: BLE001 - 单文件失败不应阻断整体抓取
                logger.warning("Failed to fetch %s: %s", path, e)

    def fetch_changes(self, since: datetime) -> Iterator[RawDocument]:
        """增量抓取:基于 commits 列表收集变更文件,逐个拉取最新内容。"""
        url = f"https://api.github.com/repos/{self._owner}/{self._repo}/commits"
        params = {"since": since.isoformat(), "sha": self._branch, "per_page": 100}
        changed_paths: set[str] = set()
        with httpx.Client(timeout=30, headers=self._headers) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            for commit in resp.json():
                for f in commit.get("files", []):
                    changed_paths.add(f["filename"])

        for path in changed_paths:
            if not self._should_include(path):
                continue
            try:
                content = self._fetch_file_content(path)
                yield self._make_document(path, content)
            except Exception as e:  # noqa: BLE001 - 单文件失败不应阻断整体抓取
                logger.warning("Failed to fetch changed %s: %s", path, e)

    def fetch_deleted(self, since: datetime) -> list[str]:
        """返回自 ``since`` 起被删除的文档 source_id 列表。"""
        url = f"https://api.github.com/repos/{self._owner}/{self._repo}/commits"
        params = {"since": since.isoformat(), "sha": self._branch, "per_page": 100}
        deleted: list[str] = []
        with httpx.Client(timeout=30, headers=self._headers) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            for commit in resp.json():
                for f in commit.get("files", []):
                    if f["status"] == "removed" and self._should_include(f["filename"]):
                        deleted.append(f"{self._owner}/{self._repo}/{f['filename']}")
        return deleted
