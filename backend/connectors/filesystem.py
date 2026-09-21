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

from backend.connectors.base import DataSourceConnector, RawDocument, SourceRootUnavailable
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

    v1.6.4 Track A(Issue #25)生命周期契约:
    - ``DECLARES_DELETIONS = False``:本地 FS 无删除事件日志,本连接器不能
      自证删除;账本行退休由 sync 侧完整权威发现差集 + 两次连续缺席确认
      驱动(A-1/A-2),``fetch_deleted`` 维持诚实空实现;
    - ``policy_absence_reason``:按既有过滤策略逐维分类「范围外缺席」
      (A-3:政策缺席绝不确认为源删除)。
    """

    # 不能自证删除事件 → 账本侧缺席确认负责退休(Track A A-1)
    DECLARES_DELETIONS = False

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

    def _ensure_root_enumerable(self) -> None:
        """Issue #100 AC2:根对执行面不可用 ⇒ fail-closed,绝不静默空集。

        Python 3.13 ``Path.rglob`` 对缺失根**静默返回空**(不抛错),会把
        「配置根不可见(容器拓扑/挂载缺失/路径配错)」伪装成「合法空源」
        —— 上传权威对 sync 执行面不可见的生产事故正源于此。根缺失/不可读
        必须显式抛 :class:`SourceRootUnavailable`(携带配置值与解析后的
        绝对路径,操作员可据此定位部署挂载缺口);根存在但无匹配文件 =
        合法空源,不受此限。
        """
        if not self._root.is_dir():
            raise SourceRootUnavailable(
                f"数据源 {self._config.id} 根目录对执行面不可用: "
                f"root_path={self._config.config.get('root_path')!r} "
                f"(解析为 {self._root.resolve()})不存在或不是目录 —— "
                f"检查该执行面的共享上传卷挂载/路径配置"
            )
        if not os.access(self._root, os.R_OK):
            raise SourceRootUnavailable(
                f"数据源 {self._config.id} 根目录对执行面不可读: "
                f"root_path={self._config.config.get('root_path')!r} "
                f"(解析为 {self._root.resolve()})无读权限 —— "
                f"检查挂载卷权限"
            )

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
            # U-7:文件系统源对象=文档文件(结构化真值)
            content_type="document",
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

    def policy_absence_reason(self, source_id: str) -> str | None:
        """按当前管理员策略判定该身份是否「范围外」(A-3;Track A)。

        与 :meth:`fetch_all` 的过滤视野同一判定来源(``file_types`` →
        ``include_dirs`` → 技术安全 → ``ExclusionPolicy``;尺寸维度无法对
        已消失文件回放,不参与分类 —— 尺寸排除是技术安全的硬上限,历史行
        由 corpus repair 的 unsafe-artifact 面负责)。

        Returns:
            范围外缺席的固定 reason 词表(``"file_types"`` / ``"include_dirs"`` /
            ``"technical_safety"`` / ``"exclusion_policy"``);范围内(即若文件
            在盘就会被摄取)→ None,其缺席可进入 A-2 退休确认。
        """
        prefix = f"{self._config.id}/{self._branch}/"
        if not source_id.startswith(prefix):
            # 异形身份(非本连接器产出的复合路径):保守视为范围内
            # (宁可走确认流程,也不静默豁免)。
            return None
        rel = source_id[len(prefix) :]
        ext = os.path.splitext(rel)[1]
        if ext not in self._file_types:
            return "file_types"
        if self._include_dirs and not any(
            rel.startswith(d.rstrip("/")) or rel == d for d in self._include_dirs
        ):
            return "include_dirs"
        verdict = self._safety.check_path(rel, 0)
        if not verdict.safe:
            return "technical_safety"
        if self._policy.should_exclude(rel, 0):
            return "exclusion_policy"
        return None

    def fetch_all(self) -> Iterator[RawDocument]:
        """全量抓取:递归遍历根目录,yield 所有符合过滤条件的文件。

        过滤顺序:``file_types`` + ``include_dirs``(``_should_include``)→
        ``ExclusionPolicy``(构建目录 / 二进制 / 测试数据 / 非源码超大文件)。
        单文件读取失败(``PermissionError`` / ``FileNotFoundError`` /
        断裂符号链接等)记录 warning 后跳过,不阻断整体抓取;
        与 ``GitHubConnector`` 的单文件 try/except 模式一致。
        """
        self._ensure_root_enumerable()
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
        self._ensure_root_enumerable()
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
        因此本方法始终返回空列表(诚实降级)。

        v1.6.4 Track A(Issue #25):fs 文档的退休不再依赖本方法 —— sync
        侧以完整权威发现(``fetch_all`` 差集)做账本侧缺席确认(A-1/A-2:
        两次连续完整发现 → missing_candidate → RETIRED),本实现保持 ``[]``
        语义不变。
        """
        return []
