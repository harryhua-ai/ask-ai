"""本地文件系统数据源 Connector。

递归遍历指定根目录,将符合条件的文件封装为 ``RawDocument``:
- 全量抓取(基于 ``rglob`` 递归列举)
- 增量抓取(基于文件 ``mtime`` 过滤)
- 删除检测:本地文件系统无法可靠重建删除事件,``fetch_deleted`` 返回空列表

过滤规则:
- 文件后缀白名单(默认 ``[".md", ".txt"]``)
- 可选 ``include_dirs`` 白名单(仅保留指定前缀的相对路径)
"""

import hashlib
import logging
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from backend.connectors.base import DataSourceConnector, RawDocument
from backend.connectors.exclusion import ExclusionPolicy
from backend.connectors.registry import ConnectorRegistry, SourceConfig
from backend.connectors.safety import (
    TechnicalSafetyPolicy,
    new_safety_stats,
    record_safety_exclusion,
)

logger = logging.getLogger(__name__)


@ConnectorRegistry.register("filesystem")
class FilesystemConnector(DataSourceConnector):
    """基于本地文件系统的数据源 Connector。

    通过 ``SourceConfig.config`` 提供以下参数:

    - ``root_path`` (str, 必填): 要递归扫描的根目录(支持 ``~`` 展开)。
    - ``file_types`` (list[str], 可选): 文件后缀白名单,默认 ``[".md", ".txt"]``。
    - ``include_dirs`` (list[str], 可选): 相对路径前缀白名单;为空表示不限制。

    P8 多分支契约:filesystem 为单分支源,分支名取 ``SourceConfig.branches[0]``
    (若提供)或 ``config.branch`` / 默认 ``"main"``;``source_id`` 格式为
    ``{cfg.id}/{branch}/{rel}``,``RawDocument.branch`` 透传该分支名。
    过滤策略:``file_types`` 白名单 + ``include_dirs`` 前缀 + ``ExclusionPolicy``
    (排除构建目录、二进制、测试数据等)共同生效。
    """

    def __init__(self, config: SourceConfig) -> None:
        self._config = config
        root = Path(config.config["root_path"]).expanduser()
        self._root: Path = root
        # 不可变构造:用 spread 创建新集合,避免引用 config 内部可变对象
        self._file_types: set[str] = {*config.config.get("file_types", [".md", ".txt"])}
        self._include_dirs: list[str] = [*config.config.get("include_dirs", [])]
        # Phase 2A:透传 channel_visibility 到每条 RawDocument
        self._channel_visibility: tuple[str, ...] = config.channel_visibility
        # P8 多分支契约:filesystem 为单分支,取 branches[0] 或 config.branch / main
        self._branch: str = (
            config.branches[0] if config.branches else config.config.get("branch", "main")
        )
        # P8:接入通用排除策略(构建目录 / 二进制 / 测试数据 / 非源码超大文件)
        self._policy = ExclusionPolicy(config.config)
        # 技术安全边界(Layer 1):独立于 file_types/include_dirs,管理员配置不可绕过(G1)
        self._safety = TechnicalSafetyPolicy(config.config)
        self.safety_stats = new_safety_stats()

    @property
    def source_id(self) -> str:
        return self._config.id

    @property
    def product(self) -> str:
        return self._config.product

    def _should_include(self, path: Path) -> bool:
        """判断给定路径是否应被纳入抓取范围。

        使用 ``os.path.splitext`` 提取扩展名,与 GitHubConnector 保持一致,
        正确处理 dotfile(如 ``.gitignore``)与含点目录。

        已知限制(Phase 2 待优化):``include_dirs`` 采用字符串前缀匹配,
        ``"docs"`` 会误匹配到 ``docs_old/``。如需精确目录匹配,应在末尾
        加 ``/``(如 ``"docs/"``);此行为与 ``GitHubConnector`` 保持一致。
        """
        rel = path.relative_to(self._root)
        # 使用 os.path.splitext 提取扩展名,正确处理 dotfile 和含点的目录
        ext = os.path.splitext(str(path))[1]
        if ext not in self._file_types:
            return False
        if self._include_dirs:
            rel_str = str(rel)
            if not any(
                # include_dirs 既支持目录前缀,也支持精确文件路径
                rel_str.startswith(d.rstrip("/")) or rel_str == d
                for d in self._include_dirs
            ):
                return False
        return True

    def _make_document(self, path: Path) -> RawDocument:
        """根据路径构造 ``RawDocument``。

        使用 ``errors="replace"`` 读取,二进制或非 UTF-8 文件不会抛出异常,
        但可能产生乱码内容(由下游管道决定是否过滤)。``source_id`` 采用
        ``{cfg.id}/{branch}/{rel}`` 格式以与 ``LocalGitConnector`` 保持一致;
        ``branch`` 取构造期确定的单分支名。
        """
        # encoding="utf-8" + errors="replace":二进制/非 utf-8 文件不报错
        content = path.read_text(encoding="utf-8", errors="replace")
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        rel = str(path.relative_to(self._root))
        title = path.stem
        return RawDocument(
            source_id=f"{self._config.id}/{self._branch}/{rel}",
            source_type="filesystem",
            product=self.product,
            title=title,
            content=content,
            url=f"file://{path.absolute()}",
            metadata={"path": rel, "root": str(self._root), "branch": self._branch},
            content_hash=content_hash,
            channel_visibility=self._channel_visibility,
            branch=self._branch,
        )

    def _is_excluded(self, path: Path) -> bool:
        """按 ``ExclusionPolicy`` 判定文件是否应被排除。

        ``stat()`` 失败(权限/IO)记录 warning 并视为不排除,交由后续
        ``_make_document`` 的读取处理统一跳过,避免重复 stat 容错逻辑。

        Args:
            path: 绝对路径。

        Returns:
            True 表示应排除,False 表示保留。
        """
        rel = str(path.relative_to(self._root))
        try:
            size = path.stat().st_size
        except OSError as e:
            logger.warning("无法 stat 文件 %s: %s", path, e)
            return False
        return self._policy.should_exclude(rel, size)

    def _is_technically_safe(self, path: Path) -> bool:
        """技术安全边界(Layer 1):模型工件类扩展名 + 硬尺寸上限,读内容**前**拦截(G1)。

        与 file_types/include_dirs(管理员策略)正交:即使管理员把 .hef 加入
        白名单,本检查仍会拒绝——产品合同「管理员配置不得绕过 Technical Safety」。
        """
        rel = str(path.relative_to(self._root))
        try:
            size = path.stat().st_size
        except OSError as exc:
            logger.warning("无法 stat 文件 %s: %s", path, exc)
            return False
        verdict = self._safety.check_path(rel, size)
        if not verdict.safe:
            record_safety_exclusion(self.safety_stats, rel, verdict.reason, verdict.detail)
            return False
        return True

    def fetch_all(self) -> Iterator[RawDocument]:
        """全量抓取:递归遍历根目录,yield 所有符合过滤条件的文件。

        过滤顺序:``file_types`` + ``include_dirs``(``_should_include``)→
        ``ExclusionPolicy``(构建目录 / 二进制 / 测试数据 / 非源码超大文件)。
        单文件读取失败(``PermissionError`` / ``FileNotFoundError`` /
        断裂符号链接等)记录 warning 后跳过,不阻断整体抓取;
        与 ``GitHubConnector`` 的单文件 try/except 模式一致。
        """
        for path in sorted(self._root.rglob("*")):
            if not (path.is_file() and self._should_include(path)):
                continue
            if not self._is_technically_safe(path):
                continue
            if self._is_excluded(path):
                continue
            try:
                yield self._make_document(path)
            except (OSError, UnicodeDecodeError) as e:
                # OSError 覆盖 PermissionError/FileNotFoundError 等
                logger.warning("无法读取文件 %s: %s", path, e)

    def fetch_changes(self, since: datetime) -> Iterator[RawDocument]:
        """增量抓取:yield ``mtime`` 晚于 ``since`` 的文件。

        过滤顺序同 ``fetch_all``。单文件 ``stat()`` 或读取失败(权限、IO、
        解码等)记录 warning 后跳过,不阻断整体抓取。``_is_excluded`` 内的
        ``stat()`` 与 ``_make_document`` 内的读取已在各自 try 块中容错。

        Args:
            since: UTC 时间戳;文件 ``mtime`` 早于等于该时刻的文件会被跳过。
        """
        for path in sorted(self._root.rglob("*")):
            if not (path.is_file() and self._should_include(path)):
                continue
            if not self._is_technically_safe(path):
                continue
            if self._is_excluded(path):
                continue
            try:
                mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
                if mtime > since:
                    yield self._make_document(path)
            except (OSError, UnicodeDecodeError) as e:
                # stat() 与 read_text() 均可能抛 OSError
                logger.warning("无法读取文件 %s: %s", path, e)

    def fetch_deleted(self, since: datetime) -> list[str]:
        """返回自 ``since`` 起被删除的文档 source_id 列表。

        本地文件系统无法可靠重建删除事件(无 commit/事件日志),
        因此本方法始终返回空列表。如需删除检测,应由调用方维护
        快照对比逻辑(记录上次同步的文件列表,与当前列表求差集)。
        """
        return []
