"""GitHub 仓库数据源 Connector(唯一 git 源类型)。

统一 github / local_git 双类型(决策 2A:local_git 降为实现细节,
``@register`` 在 local_git.py 移除)。全新实现 git clone + fetch + reset
(代码库原无 git 操作能力)。修 local_git 数据陈旧 bug —— 从不 fetch 改为
API SHA 智能触发 fetch + reset --hard。

config 新 schema:
- ``repo_url`` (str, 必填): HTTPS URL,如 ``https://github.com/camthink-ai/ne301.git``
- ``branches`` (list, 可选): 多分支,默认 ``["main"]``
- ``file_types`` (list, 可选): 后缀白名单,默认 ``[".py"]``
- ``clone_path`` (str, 可选): 本地 clone 路径,默认 ``~/ask-ai-corpus/<repo>``
- ``exclude_dirs`` / ``exclude_regex`` / ``max_file_size`` (可选): ExclusionPolicy

决策:
- 3A:``_git_sync_branch`` = ``git fetch`` + ``git reset --hard origin/<branch>``
  (fetch 只更 ref,reset 才更工作区 —— 修 staleness;非 checkout)。
- 4A:clone 不可用(首次 clone 失败 / 磁盘满 / 无访问)报错跳过该源,**不降级逐文件 API**。
- API SHA 感知:远端 HEAD SHA == 本地 → 跳过 fetch;API 故障 → 降级 True(触发 fetch)。
"""

import hashlib
import logging
import os
import re
import subprocess
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx

from backend.connectors.base import DataSourceConnector, RawDocument
from backend.connectors.exclusion import ExclusionPolicy
from backend.connectors.registry import ConnectorRegistry, SourceConfig

logger = logging.getLogger(__name__)

# https://github.com/{owner}/{repo}[.git] —— 兼容带 / 不带 .git 后缀
_REPO_URL_RE = re.compile(r"github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", re.IGNORECASE)


@ConnectorRegistry.register("github")
class GitHubConnector(DataSourceConnector):
    """GitHub 仓库数据源(clone + fetch+reset + API SHA 感知)。

    config 见模块 docstring。``GITHUB_TOKEN`` 从环境变量读(私有仓库内嵌到
    clone URL,API 请求带 Bearer);未设置时匿名访问(受 GitHub 速率限制)。
    """

    def __init__(self, config: SourceConfig) -> None:
        self._config = config
        self._repo_url: str = config.config["repo_url"]
        self._owner, self._repo = self._parse_repo_url(self._repo_url)
        # branches:SourceConfig.branches(复数字段,空 tuple 表示未指定)优先,
        # 回退到 config.branches(兼容旧单数字段),最终默认 ["main"]。
        self._branches: tuple[str, ...] = (
            config.branches
            or tuple(config.config.get("branches", ["main"]) or ["main"])
        )
        # 不可变构造:spread 创建新集合,避免引用 config 内部可变对象
        self._file_types: set[str] = {*config.config.get("file_types", [".py"])}
        self._clone_path: Path = Path(
            config.config.get("clone_path")
            or f"~/ask-ai-corpus/{self._repo}"
        ).expanduser()
        self._channel_visibility: tuple[str, ...] = config.channel_visibility
        self._policy = ExclusionPolicy(config.config)
        self._token: str = os.environ.get("GITHUB_TOKEN", "")

    @staticmethod
    def _parse_repo_url(repo_url: str) -> tuple[str, str]:
        """repo_url → (owner, repo)。支持 ``https://github.com/{owner}/{repo}[.git]``。"""
        m = _REPO_URL_RE.search(repo_url)
        if not m:
            raise ValueError(f"无法解析 repo_url(期望 github.com/<owner>/<repo>): {repo_url}")
        return m.group(1), m.group(2)

    @property
    def source_id(self) -> str:
        return self._config.id

    @property
    def product(self) -> str:
        return self._config.product

    # ---------------- git 操作(全新能力) ----------------

    def _authed_url(self) -> str:
        """私有仓库:HTTPS URL 内嵌 token(无 token 则原样)。

        ``https://github.com/...`` → ``https://x-access-token:{token}@github.com/...``
        """
        if not self._token:
            return self._repo_url
        return self._repo_url.replace(
            "https://", f"https://x-access-token:{self._token}@"
        )

    def _ensure_cloned(self, branch: str) -> None:
        """首次 clone(clone_path 不存在时)。失败报错,不降级(决策 4A)。

        Args:
            branch: 首次 clone 指定的分支(--branch)。
        Raises:
            subprocess.CalledProcessError: clone 失败(网络 / 鉴权 / 磁盘)。
        """
        if self._clone_path.exists():
            return
        self._clone_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--branch", branch, self._authed_url(), str(self._clone_path)],
            check=True,
            capture_output=True,
        )

    def _git_sync_branch(self, branch: str) -> None:
        """fetch + reset 工作区到远端最新(修 staleness bug,决策 3A)。

        fetch 只更新 remote-tracking ref,不碰工作区;``reset --hard origin/<branch>``
        才把工作区同步到远端最新(clone 副本只读,reset 安全)。非 checkout ——
        checkout 在本地分支与远端分叉时会遗留旧内容(staleness root cause)。
        """
        subprocess.run(
            ["git", "fetch", "origin", branch],
            cwd=self._clone_path,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "reset", "--hard", f"origin/{branch}"],
            cwd=self._clone_path,
            check=True,
            capture_output=True,
        )

    def _git_local_sha(self, branch: str) -> str:
        """本地 HEAD commit SHA(``git rev-parse HEAD``)。"""
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self._clone_path,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def _api_get_latest_sha(self, branch: str) -> str:
        """GitHub API:``GET /repos/{owner}/{repo}/commits/{branch}`` → 最新 SHA。"""
        url = f"https://api.github.com/repos/{self._owner}/{self._repo}/commits/{branch}"
        headers: dict[str, str] = {"Accept": "application/vnd.github+json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        with httpx.Client(timeout=30, headers=headers) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.json()["sha"]

    def _remote_has_updates(self, branch: str) -> bool:
        """API SHA vs 本地 HEAD。API 故障 → True(降级触发 fetch,不阻断同步)。"""
        try:
            return self._api_get_latest_sha(branch) != self._git_local_sha(branch)
        except Exception as exc:  # noqa: BLE001 - 降级而非阻断
            logger.warning(
                "API SHA 感知失败,降级直接 fetch: branch=%s err=%s",
                branch,
                str(exc)[:200],
            )
            return True

    # ---------------- 文件遍历(吸收 local_git 的 checkout+遍历) ----------------

    def _should_include_path(self, rel: str) -> bool:
        """file_types + ExclusionPolicy 过滤(沿用 local_git 逻辑)。"""
        p = self._clone_path / rel
        if p.suffix.lower() not in self._file_types:
            return False
        try:
            size = p.stat().st_size
        except OSError as exc:
            logger.warning("无法 stat 文件 %s: %s", p, exc)
            return False
        return not self._policy.should_exclude(rel, size)

    def _make_document(self, rel: str, content: str, branch: str) -> RawDocument:
        """构造 RawDocument(``source_type='github'`` 统一类型,branch 已填)。"""
        return RawDocument(
            source_id=f"{self._config.id}/{branch}/{rel}",
            source_type="github",
            product=self.product,
            title=Path(rel).stem,
            content=content,
            url=f"https://github.com/{self._owner}/{self._repo}/blob/{branch}/{rel}",
            metadata={"path": rel, "branch": branch, "repo_url": self._repo_url},
            content_hash=hashlib.sha256(content.encode()).hexdigest(),
            channel_visibility=self._channel_visibility,
            branch=branch,
        )

    def _iter_files(self, branch: str) -> Iterator[RawDocument]:
        """遍历 clone 副本(吸收 local_git._iter_files,用 reset 替代 checkout)。"""
        for path in sorted(self._clone_path.rglob("*")):
            if not path.is_file() or ".git" in path.parts:
                continue
            rel = str(path.relative_to(self._clone_path))
            if not self._should_include_path(rel):
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                logger.warning("无法读取文件 %s: %s", rel, exc)
                continue
            yield self._make_document(rel, content, branch)

    # ---------------- DataSourceConnector 协议 ----------------

    def fetch_all(self) -> Iterator[RawDocument]:
        """全量抓取:每分支 ensure_cloned + git_sync_branch + 遍历。"""
        for branch in self._branches:
            self._ensure_cloned(branch)
            self._git_sync_branch(branch)
            yield from self._iter_files(branch)

    def fetch_changes(self, since: datetime) -> Iterator[RawDocument]:
        """增量抓取:API SHA 有更新才 fetch+reset,再读 since 后变更的文件。

        SHA 相同的分支跳过(无变更)。API 故障降级为直接 fetch(见
        ``_remote_has_updates``)。
        """
        for branch in self._branches:
            self._ensure_cloned(branch)
            if self._remote_has_updates(branch):
                self._git_sync_branch(branch)
                yield from self._read_local_changes(branch, since)

    def _read_local_changes(self, branch: str, since: datetime) -> Iterator[RawDocument]:
        """``git log --since`` 拿变更文件(沿用 local_git 逻辑,AMR + rename)。"""
        since_iso = since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
        result = subprocess.run(
            [
                "git", "log", f"--since={since_iso}",
                "--name-only", "--pretty=format:",
                "--diff-filter=AMR", "-M",
            ],
            cwd=self._clone_path,
            capture_output=True,
            text=True,
            check=True,
        )
        seen: set[str] = set()
        for line in result.stdout.splitlines():
            rel = line.strip()
            if not rel or rel in seen:
                continue
            if not self._should_include_path(rel):
                continue
            seen.add(rel)
            try:
                content = (self._clone_path / rel).read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                logger.warning("无法读取变更文件 %s: %s", rel, exc)
                continue
            yield self._make_document(rel, content, branch)

    def fetch_deleted(self, since: datetime) -> list[str]:
        """``git log --since --diff-filter=D`` 拿删除文件(沿用 local_git 逻辑)。

        被删文件在工作区已不存在,无法 ``stat`` 取 size,故用内联路径级过滤
        (后缀白名单 + ExclusionPolicy.should_exclude(rel, 0))。size=0 仅让
        "非源码超大文件"规则失效,源码文件本不受 size 限制。
        """
        since_iso = since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
        deleted: list[str] = []
        seen: set[str] = set()
        for branch in self._branches:
            result = subprocess.run(
                [
                    "git", "log", f"--since={since_iso}",
                    "--name-only", "--pretty=format:",
                    "--diff-filter=D",
                ],
                cwd=self._clone_path,
                capture_output=True,
                text=True,
                check=True,
            )
            for raw in result.stdout.splitlines():
                rel = raw.strip()
                if not rel:
                    continue
                if Path(rel).suffix.lower() not in self._file_types:
                    continue
                if self._policy.should_exclude(rel, 0):
                    continue
                sid = f"{self._config.id}/{branch}/{rel}"
                if sid not in seen:
                    deleted.append(sid)
                    seen.add(sid)
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
