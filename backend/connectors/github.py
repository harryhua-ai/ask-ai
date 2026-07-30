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

from backend.connectors.base import DataSourceConnector, RawDocument
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
class GitHubConnector(DataSourceConnector):
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
        # 不可变构造:用 spread 一次性合并 headers,避免后续 mutation
        self._headers: dict[str, str] = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            **({"Authorization": f"Bearer {self._token}"} if self._token else {}),
        }
        self._exclude_pattern: re.Pattern[str] | None = (
            re.compile(self._exclude_regex) if self._exclude_regex else None
        )
        # Phase 2A:透传 channel_visibility 到每条 RawDocument
        self._channel_visibility: tuple[str, ...] = config.channel_visibility

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
        """递归拉取分支的 git tree,返回 tree 节点列表。

        GitHub 在结果集过大时会设置 ``truncated=true`` 并截断 tree。
        本方法检测到截断时仅记录 warning;如需完整覆盖,后续可改为
        递归展开子目录。
        """
        url = (
            f"https://api.github.com/repos/{self._owner}/{self._repo}"
            f"/git/trees/{self._branch}?recursive=1"
        )
        with httpx.Client(timeout=30, headers=self._headers) as client:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()
            if data.get("truncated"):
                logger.warning(
                    "Git tree for %s/%s (%s) was truncated by GitHub; "
                    "some files may be missing from fetch_all",
                    self._owner,
                    self._repo,
                    self._branch,
                )
            return data.get("tree", [])

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
        # 使用 os.path.splitext 提取扩展名,正确处理 dotfile 和含点的目录
        ext = os.path.splitext(path)[1]
        return ext in self._file_types

    def _fetch_file_content(self, path: str, client: httpx.Client | None = None) -> str:
        """通过 Contents API 拉取单个文件内容(自动处理 base64 解码)。

        限制:GitHub Contents API 对 >1 MB 的文件返回 403/422 错误,
        message 中含 "too large" 或 "1 MB"。本方法检测到该场景时
        抛出 ``ValueError``,由上层 try/except 捕获后跳过该文件;
        如需支持大文件,后续应切换到 Blobs API。

        Args:
            path: 仓库内相对路径。
            client: 可选的复用连接;为 ``None`` 时新建短生命周期 Client。
        """
        url = self._api_url(path)

        def _do(c: httpx.Client) -> str:
            resp = c.get(url)
            # 检测文件过大场景(GitHub Contents API >1 MB 限制)
            if resp.status_code in (403, 422):
                try:
                    msg = resp.json().get("message", "")
                except Exception:  # noqa: BLE001 - 响应体非 JSON 时忽略
                    msg = ""
                low = msg.lower()
                if "too large" in low or "1 mb" in low:
                    raise ValueError(
                        f"file {path} exceeds 1 MB (Contents API limit); "
                        "use Blobs API for larger files"
                    )
            resp.raise_for_status()
            data = resp.json()
            if data.get("encoding") == "base64":
                return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
            return data.get("content", "")

        if client is not None:
            return _do(client)
        with httpx.Client(timeout=30, headers=self._headers) as new_client:
            return _do(new_client)

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
            channel_visibility=self._channel_visibility,
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

    def _list_commit_shas(self, client: httpx.Client, since: datetime) -> list[str]:
        """调用 List Commits API 获取 since 之后所有 commit 的 sha。

        限制:当前仅取首页 ``per_page=100`` 条;未跟随 Link 头分页,
        超过 100 commits 的大变更窗口会漏取。Phase 2 可加分页循环。
        """
        url = f"https://api.github.com/repos/{self._owner}/{self._repo}/commits"
        params = {"since": since.isoformat(), "sha": self._branch, "per_page": 100}
        resp = client.get(url, params=params)
        resp.raise_for_status()
        return [c["sha"] for c in resp.json() if c.get("sha")]

    def _get_commit_files(self, client: httpx.Client, sha: str) -> list[dict]:
        """调用单 commit 详情 API 获取 files 字段。

        GitHub List Commits API 响应**不含** files 字段(只有 sha/commit/
        parents 等),必须额外调用 ``GET /repos/{owner}/{repo}/commits/{sha}``
        才能拿到每个 commit 修改的文件列表。

        限制:单 commit 详情的 files 字段最多 300 项,超过会被 GitHub 截断
        (此时响应体 ``truncated=true``,但 GitHub REST 不暴露该字段,
        只能依赖 commit 文件数 < 300 的假设)。
        """
        url = f"https://api.github.com/repos/{self._owner}/{self._repo}/commits/{sha}"
        resp = client.get(url)
        resp.raise_for_status()
        return resp.json().get("files", [])

    def fetch_changes(self, since: datetime) -> Iterator[RawDocument]:
        """增量抓取:基于 commits 列表收集变更文件,逐个拉取最新内容。

        实现策略(修复 list commits 不含 files 字段的 bug):

        1. 调用 ``GET /repos/{owner}/{repo}/commits?since=...`` 获取 sha 列表。
        2. 对每个 sha 调用 ``GET /repos/{owner}/{repo}/commits/{sha}`` 拉取
           commit 详情中的 files 数组(含 filename/status 字段)。
        3. 累积所有 ``added`` / ``modified`` / ``renamed`` 的文件路径,
           过滤后逐个调 Contents API 拉取最新内容。

        限制:
        - 仅取最近 100 commits(见 ``_list_commit_shas`` 的分页说明)。
        - 单 commit files 数组上限 300 项,超过会被截断。
        - renamed 文件取新 filename;旧路径的删除事件由 ``fetch_deleted`` 处理。
        """
        changed_paths: set[str] = set()
        with httpx.Client(timeout=30, headers=self._headers) as client:
            for sha in self._list_commit_shas(client, since):
                for f in self._get_commit_files(client, sha):
                    status = f.get("status")
                    if status in ("added", "modified", "renamed", "changed"):
                        filename = f.get("filename", "")
                        if filename:
                            changed_paths.add(filename)

        for path in sorted(changed_paths):
            if not self._should_include(path):
                continue
            try:
                content = self._fetch_file_content(path)
                yield self._make_document(path, content)
            except Exception as e:  # noqa: BLE001 - 单文件失败不应阻断整体抓取
                logger.warning("Failed to fetch changed %s: %s", path, e)

    def fetch_deleted(self, since: datetime) -> list[str]:
        """返回自 ``since`` 起被删除的文档 source_id 列表。

        实现策略(同 ``fetch_changes``,需调用单 commit 详情 API):

        1. List Commits 获取 sha 列表。
        2. 对每个 sha 调用 commit 详情 API,过滤 ``status == "removed"``。
        3. 将命中的文件名拼装成 source_id 列表返回。

        限制:同 ``fetch_changes``,100 commits / 300 files-per-commit 上限。
        """
        deleted: list[str] = []
        seen: set[str] = set()
        with httpx.Client(timeout=30, headers=self._headers) as client:
            for sha in self._list_commit_shas(client, since):
                for f in self._get_commit_files(client, sha):
                    if f.get("status") == "removed":
                        filename = f.get("filename", "")
                        if not filename or not self._should_include(filename):
                            continue
                        source_id = f"{self._owner}/{self._repo}/{filename}"
                        if source_id not in seen:
                            deleted.append(source_id)
                            seen.add(source_id)
        return deleted


# ---------------------------------------------------------------------------
# S4: GITHUB_TOKEN 最小权限校验(模块级函数,启动时由 lifespan 调用)
# ---------------------------------------------------------------------------

# classic token 写权限前缀(命中即视为违反最小权限)
_WRITE_SCOPE_PREFIXES: tuple[str, ...] = ("repo", "write:", "delete:", "admin:")
# classic token 只读 scope 白名单(``""`` 用于 fine-grained token 无 x-oauth-scopes 头的情况)
_READONLY_SCOPES: frozenset[str] = frozenset({"repo:read", "public_repo", ""})


def validate_github_token(token: str, *, strict: bool = False) -> None:
    """启动时校验 GITHUB_TOKEN 为只读最小权限。

    classic token:检查 ``X-OAuth-Scopes`` 不含写权限(``repo`` / ``write:`` /
                   ``delete:`` / ``admin:``),``repo:read`` 与 ``public_repo``
                   视为只读放行。
    fine-grained token:响应头无 ``x-oauth-scopes``,视为有效(权限粒度在 token
                       配置层保证)。
    无 token:warn(私有仓库将拉取失败)。
    写权限命中:``strict=True``(prod)抛 :class:`RuntimeError` 阻断启动;
              ``strict=False``(dev)仅 warn。

    Args:
        token: GitHub Personal Access Token。
        strict: 是否严格模式(生产)。严格模式下写权限会抛错阻断启动。
    """
    if not token:
        logger.warning("GITHUB_TOKEN 未设置:私有仓库将无法拉取")
        return
    try:
        with httpx.Client(
            timeout=10,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
            },
        ) as client:
            resp = client.get("https://api.github.com/user")
            resp.raise_for_status()
            scopes = resp.headers.get("x-oauth-scopes", "")
            found_write = [
                s.strip()
                for s in scopes.split(",")
                if s.strip() not in _READONLY_SCOPES
                and any(s.strip().startswith(p) for p in _WRITE_SCOPE_PREFIXES)
            ]
            if found_write:
                msg = f"GITHUB_TOKEN 含写权限 scope {found_write},违反最小权限原则"
                if strict:
                    raise RuntimeError(msg)
                logger.warning(msg)
    except httpx.HTTPError as e:
        logger.warning("GITHUB_TOKEN 校验失败(网络或无效 token):%s", e)
