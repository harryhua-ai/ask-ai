"""本地 Git 仓库数据源 Connector(多分支 checkout 读)。

支持对同一仓库的多个分支执行 ``git checkout`` 后逐文件遍历,产出
``RawDocument``(``branch`` 字段已填,``source_id`` 格式为
``{cfg.id}/{branch}/{rel}``)。

增量策略:
- ``fetch_changes(since)``:对每个分支 ``git checkout`` 后用
  ``git log --since=<since_iso> --name-only --diff-filter=AMR -M`` 拿变更
  文件名,去重 + 过滤后 yield(只返回 since 之后 added/modified/renamed 的文件)。
- ``fetch_deleted(since)``:对每个分支 ``git checkout`` 后用
  ``git log --since=<since_iso> --name-only --pretty=format: --diff-filter=D``
  拿被删文件名,去重 + 路径级过滤(后缀白名单 + ExclusionPolicy)后返回
  source_id 列表(``{cfg.id}/{branch}/{rel}``)。
"""

import hashlib
import logging
import subprocess
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from backend.connectors.base import DataSourceConnector, RawDocument
from backend.connectors.exclusion import ExclusionPolicy
from backend.connectors.registry import SourceConfig

logger = logging.getLogger(__name__)


class LocalGitConnector(DataSourceConnector):
    """基于本地 Git 仓库的多分支数据源 Connector(实现细节,不再 @register)。

    决策 2A:``github`` 已统一为唯一 git 源类型,本类不再注册到 ConnectorRegistry;
    保留类定义以承载历史测试覆盖(LocalGitConnector 直接构造,不经过 registry),
    并作为 GitHubConnector 的 checkout+遍历逻辑参考 —— 新 github connector 用
    fetch+reset 替代 checkout,修复了 staleness bug。

    通过 ``SourceConfig.config`` 提供以下参数:

    - ``repo_path`` (str, 必填): Git 仓库本地路径(支持 ``~`` 展开)。
    - ``file_types`` (list[str], 可选): 文件后缀白名单,默认 ``[".py"]``。
    - ``branch`` (str, 可选): 单分支模式下的分支名;``branches`` 为空时生效,
      默认 ``"main"``。

    多分支列表由 ``SourceConfig.branches`` 提供(优先级高于 ``config.branch``)。
    过滤策略:``file_types`` 白名单 + ``ExclusionPolicy``(排除构建目录、
    二进制、测试数据等)共同生效。
    """

    def __init__(self, config: SourceConfig) -> None:
        self._config = config
        self._repo: Path = Path(config.config["repo_path"]).expanduser()
        # 不可变构造:spread 创建新集合,避免引用 config 内部可变对象
        self._file_types: set[str] = {*config.config.get("file_types", [".py"])}
        self._policy = ExclusionPolicy(config.config)
        # branches 为空 → 单分支(取 config.branch 或 "main")
        self._branches: tuple[str, ...] = config.branches or (config.config.get("branch", "main"),)
        self._channel_visibility: tuple[str, ...] = config.channel_visibility

    @property
    def source_id(self) -> str:
        return self._config.id

    @property
    def product(self) -> str:
        return self._config.product

    def _checkout(self, branch: str) -> None:
        """切换仓库工作区到指定分支。

        Args:
            branch: 目标分支名。
        Raises:
            subprocess.CalledProcessError: 分支不存在或工作区脏导致 checkout 失败。
        """
        subprocess.run(
            ["git", "checkout", "-q", branch],
            cwd=self._repo,
            check=True,
        )

    def _iter_files(self, branch: str) -> Iterator[RawDocument]:
        """遍历当前工作区,yield 所有通过过滤的文件作为 ``RawDocument``。

        单文件 ``stat()`` / 读取失败记录 warning 后跳过,不阻断整体抓取,
        与 ``FilesystemConnector`` 的单文件 try/except 模式一致。

        Args:
            branch: 当前 checkout 的分支名(用于 source_id / metadata / branch)。
        """
        for path in sorted(self._repo.rglob("*")):
            if not path.is_file() or ".git" in path.parts:
                continue
            rel = str(path.relative_to(self._repo))
            if not self._should_include_path(rel):
                continue
            yield from self._fetch_one(branch, rel)

    def _should_include_path(self, rel: str) -> bool:
        """对相对路径做 file_types + ExclusionPolicy 过滤。

        Args:
            rel: 相对仓库根的路径(POSIX 风格)。

        Returns:
            True 表示保留,False 表示排除。
        """
        p = self._repo / rel
        if p.suffix.lower() not in self._file_types:
            return False
        try:
            size = p.stat().st_size
        except OSError as e:
            logger.warning("无法 stat 文件 %s: %s", p, e)
            return False
        return not self._policy.should_exclude(rel, size)

    def _fetch_one(self, branch: str, rel: str) -> Iterator[RawDocument]:
        """fetch 单个文件 → RawDocument(branch 字段已填)。

        读取失败记录 warning 后跳过,不阻断整体抓取。

        Args:
            branch: 当前 checkout 的分支名。
            rel: 相对仓库根的路径(POSIX 风格)。
        """
        p = self._repo / rel
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            logger.warning("无法读取文件 %s: %s", p, e)
            return
        yield RawDocument(
            source_id=f"{self._config.id}/{branch}/{rel}",
            source_type="local_git",
            product=self.product,
            title=p.stem,
            content=content,
            url=f"file://{p.absolute()}",
            metadata={
                "repo": str(self._repo),
                "branch": branch,
                "path": rel,
            },
            content_hash=hashlib.sha256(content.encode()).hexdigest(),
            channel_visibility=self._channel_visibility,
            branch=branch,
        )

    def fetch_all(self) -> Iterator[RawDocument]:
        """全量抓取:对每个分支执行 checkout 后遍历文件。

        按 ``self._branches`` 的顺序依次切换分支,yield 该分支下所有
        通过过滤的文件(分支名透传到 ``RawDocument.branch``)。
        """
        for branch in self._branches:
            self._checkout(branch)
            yield from self._iter_files(branch)

    def fetch_changes(self, since: datetime) -> Iterator[RawDocument]:
        """增量抓取:对每个分支 ``git log --since`` 变更文件(AMR),过滤后 yield。

        对每个分支执行 ``git checkout`` 后,用
        ``git log --since=<since_iso> --name-only --pretty=format: --diff-filter=AMR -M``
        拿变更文件名,去重,经 ``_should_include_path`` 过滤,经 ``_fetch_one``
        构造 RawDocument。只 yield since 之后 added/modified/renamed 的文件。

        Args:
            since: UTC 时间戳,只抓该时间之后变更的文件。
        """
        since_iso = since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
        for branch in self._branches:
            self._checkout(branch)
            result = subprocess.run(
                [
                    "git", "log", f"--since={since_iso}",
                    "--name-only", "--pretty=format:",
                    "--diff-filter=AMR", "-M",
                ],
                cwd=self._repo,
                capture_output=True,
                text=True,
                check=True,
            )
            changed = {ln.strip() for ln in result.stdout.splitlines() if ln.strip()}
            for rel in sorted(changed):
                if not self._should_include_path(rel):
                    continue
                yield from self._fetch_one(branch, rel)

    def fetch_deleted(self, since: datetime) -> list[str]:
        """增量删除检测:对每分支 ``git log --diff-filter=D --since``,返回 source_id 列表。

        对每个分支执行 ``git checkout`` 后,用
        ``git log --since=<since_iso> --name-only --pretty=format: --diff-filter=D``
        拿被删文件名,去重,经路径级过滤(后缀白名单 + ExclusionPolicy)后返回。

        注意:被删文件在当前工作区已不存在,无法 ``stat`` 取 size,因此不复用
        ``_should_include_path``(它会因 ``OSError`` 返回 False),改为内联路径级
        过滤,``ExclusionPolicy.should_exclude`` 的 ``size`` 参数传 ``0`` —— 这只
        会让"非源码超大文件"规则失效,源码文件(.py/.ts/.go 等)本就不受 size 限制。

        Args:
            since: UTC 时间戳,只查该时间之后被删除(deleted)的文件。

        Returns:
            被删文件的 source_id 列表(``{cfg.id}/{branch}/{rel}``),去重。
        """
        since_iso = since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
        deleted: list[str] = []
        seen: set[str] = set()
        for branch in self._branches:
            self._checkout(branch)
            result = subprocess.run(
                [
                    "git", "log", f"--since={since_iso}",
                    "--name-only", "--pretty=format:",
                    "--diff-filter=D",
                ],
                cwd=self._repo,
                capture_output=True,
                text=True,
                check=True,
            )
            for raw in result.stdout.splitlines():
                rel = raw.strip()
                if not rel:
                    continue
                # 文件已删除无法 stat;用路径级过滤(后缀白名单 + ExclusionPolicy),
                # size 传 0 让 size-based 规则不生效,源码文件不受影响。
                p = self._repo / rel
                if p.suffix.lower() not in self._file_types:
                    continue
                if self._policy.should_exclude(rel, 0):
                    continue
                sid = f"{self._config.id}/{branch}/{rel}"
                if sid not in seen:
                    deleted.append(sid)
                    seen.add(sid)
        return deleted
