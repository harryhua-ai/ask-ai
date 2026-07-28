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
from backend.connectors.registry import ConnectorRegistry, SourceConfig

logger = logging.getLogger(__name__)


@ConnectorRegistry.register("filesystem")
class FilesystemConnector(DataSourceConnector):
    """基于本地文件系统的数据源 Connector。

    通过 ``SourceConfig.config`` 提供以下参数:

    - ``root_path`` (str, 必填): 要递归扫描的根目录(支持 ``~`` 展开)。
    - ``file_types`` (list[str], 可选): 文件后缀白名单,默认 ``[".md", ".txt"]``。
    - ``include_dirs`` (list[str], 可选): 相对路径前缀白名单;为空表示不限制。
    """

    def __init__(self, config: SourceConfig) -> None:
        self._config = config
        root = Path(config.config["root_path"]).expanduser()
        self._root: Path = root
        # 不可变构造:用 spread 创建新集合,避免引用 config 内部可变对象
        self._file_types: set[str] = {*config.config.get("file_types", [".md", ".txt"])}
        self._include_dirs: list[str] = [*config.config.get("include_dirs", [])]

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
        但可能产生乱码内容(由下游管道决定是否过滤)。
        """
        # encoding="utf-8" + errors="replace":二进制/非 utf-8 文件不报错
        content = path.read_text(encoding="utf-8", errors="replace")
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        rel = str(path.relative_to(self._root))
        title = path.stem
        return RawDocument(
            source_id=f"{self._config.id}/{rel}",
            source_type="filesystem",
            product=self.product,
            title=title,
            content=content,
            url=f"file://{path.absolute()}",
            metadata={"path": rel, "root": str(self._root)},
            content_hash=content_hash,
        )

    def fetch_all(self) -> Iterator[RawDocument]:
        """全量抓取:递归遍历根目录,yield 所有符合过滤条件的文件。

        单文件读取失败(``PermissionError`` / ``FileNotFoundError`` /
        断裂符号链接等)记录 warning 后跳过,不阻断整体抓取;
        与 ``GitHubConnector`` 的单文件 try/except 模式一致。
        """
        for path in sorted(self._root.rglob("*")):
            if path.is_file() and self._should_include(path):
                try:
                    yield self._make_document(path)
                except (OSError, UnicodeDecodeError) as e:
                    # OSError 覆盖 PermissionError/FileNotFoundError 等
                    logger.warning("无法读取文件 %s: %s", path, e)

    def fetch_changes(self, since: datetime) -> Iterator[RawDocument]:
        """增量抓取:yield ``mtime`` 晚于 ``since`` 的文件。

        单文件 ``stat()`` 或读取失败(权限、IO、解码等)记录 warning 后跳过,
        不阻断整体抓取。``stat()`` 与 ``_make_document`` 放入同一 try 块,
        避免出现半成功状态。

        Args:
            since: UTC 时间戳;文件 ``mtime`` 早于等于该时刻的文件会被跳过。
        """
        for path in sorted(self._root.rglob("*")):
            if path.is_file() and self._should_include(path):
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
