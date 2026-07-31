"""本地 Git 仓库数据源 Connector(多分支 checkout 读)。

支持对同一仓库的多个分支执行 ``git checkout`` 后逐文件遍历,产出
``RawDocument``(``branch`` 字段已填,``source_id`` 格式为
``{cfg.id}/{branch}/{rel}``)。

Plan 1 简化:
- ``fetch_changes`` 全量回退(Plan 2/后续补 ``git diff`` 增量);
- ``fetch_deleted`` 始终返回空列表。
"""

import hashlib
import logging
import subprocess
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

from backend.connectors.base import DataSourceConnector, RawDocument
from backend.connectors.exclusion import ExclusionPolicy
from backend.connectors.registry import ConnectorRegistry, SourceConfig

logger = logging.getLogger(__name__)


@ConnectorRegistry.register("local_git")
class LocalGitConnector(DataSourceConnector):
    """基于本地 Git 仓库的多分支数据源 Connector。

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
            ext = path.suffix.lower()
            if ext not in self._file_types:
                continue
            rel = str(path.relative_to(self._repo))
            try:
                size = path.stat().st_size
            except OSError as e:
                logger.warning("无法 stat 文件 %s: %s", path, e)
                continue
            if self._policy.should_exclude(rel, size):
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                logger.warning("无法读取文件 %s: %s", path, e)
                continue
            yield RawDocument(
                source_id=f"{self._config.id}/{branch}/{rel}",
                source_type="local_git",
                product=self.product,
                title=path.stem,
                content=content,
                url=f"file://{path.absolute()}",
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
        """增量抓取(Plan 1 简化:全量回退)。

        Plan 2 / 后续迭代再用 ``git diff`` 做真正的增量。

        Args:
            since: UTC 时间戳(Plan 1 未使用)。
        """
        yield from self.fetch_all()

    def fetch_deleted(self, since: datetime) -> list[str]:
        """删除检测(Plan 1 简化:始终返回空列表)。

        Args:
            since: UTC 时间戳(Plan 1 未使用)。
        """
        return []
