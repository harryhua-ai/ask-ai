"""FilesystemConnector 测试。

单元测试覆盖:
- 注册装饰器绑定
- 全量抓取 + 后缀过滤
- ``_should_include`` 对 ``include_dirs`` 的过滤
- ``fetch_changes`` 的 mtime 过滤
- 二进制/非 utf-8 文件不报错
- ``fetch_deleted`` 返回空列表(本地文件系统无法检测删除)
- 单文件 ``PermissionError`` 不阻断整体抓取 + logger.warning 被调用
"""

import logging
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from backend.connectors.filesystem import FilesystemConnector  # 触发 @register 副作用
from backend.connectors.registry import ConnectorRegistry, SourceConfig


def _make_config(root_path: str, **overrides: object) -> SourceConfig:
    """构造默认 Filesystem SourceConfig,允许测试覆盖字段。"""
    config: dict[str, object] = {
        "root_path": root_path,
        "file_types": [".md", ".txt"],
    }
    config.update(overrides)  # type: ignore[arg-type]
    return SourceConfig(
        id="test-fs",
        type="filesystem",
        product="test",
        enabled=True,
        config=config,  # type: ignore[arg-type]
        sync_interval="1h",
    )


# ====================  单元测试  ====================


@pytest.mark.unit
def test_filesystem_connector_registered() -> None:
    """注册装饰器应将 "filesystem" 类型绑定到 ConnectorRegistry。"""
    assert "filesystem" in ConnectorRegistry._connectors


@pytest.mark.unit
def test_filesystem_fetch_local_files(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """``fetch_all`` 应按 ``file_types`` 过滤,yield 出正确的 RawDocument。"""
    (tmp_path / "doc1.md").write_text("# NE503\n功耗 2.5W")
    (tmp_path / "doc2.txt").write_text("Hello")
    (tmp_path / "ignore.log").write_text("nope")

    config = _make_config(str(tmp_path))
    connector = ConnectorRegistry.create(config)
    docs = list(connector.fetch_all())

    assert len(docs) == 2
    titles = {d.title for d in docs}
    assert "doc1" in titles
    assert "doc2" in titles

    # 校验 RawDocument 关键字段
    md_doc = next(d for d in docs if d.title == "doc1")
    assert md_doc.source_type == "filesystem"
    assert md_doc.product == "test"
    assert md_doc.source_id == "test-fs/doc1.md"
    assert md_doc.content == "# NE503\n功耗 2.5W"
    assert md_doc.url.startswith("file://")
    assert md_doc.metadata["path"] == "doc1.md"
    assert md_doc.metadata["root"] == str(tmp_path)
    # SHA256 哈希长度
    assert len(md_doc.content_hash) == 64


@pytest.mark.unit
def test_filesystem_should_include_with_include_dirs(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """``_should_include`` 应按 ``include_dirs`` 前缀白名单过滤相对路径。"""
    # 构造目录结构:
    #   docs/intro.md     <- 命中 include_dirs "docs"
    #   notes/a.md        <- 不在 include_dirs 内
    #   README.md         <- 精确文件路径命中
    #   other/b.txt       <- 不在 include_dirs 内
    (tmp_path / "docs").mkdir()
    (tmp_path / "notes").mkdir()
    (tmp_path / "other").mkdir()
    (tmp_path / "docs" / "intro.md").write_text("intro")
    (tmp_path / "notes" / "a.md").write_text("notes")
    (tmp_path / "README.md").write_text("readme")
    (tmp_path / "other" / "b.txt").write_text("other")

    config = _make_config(
        str(tmp_path),
        include_dirs=["docs", "README.md"],
    )
    connector = ConnectorRegistry.create(config)
    docs = list(connector.fetch_all())

    paths = {d.metadata["path"] for d in docs}
    assert paths == {"docs/intro.md", "README.md"}


@pytest.mark.unit
def test_filesystem_fetch_changes_mtime_filter(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """``fetch_changes`` 应仅返回 ``mtime`` 晚于 ``since`` 的文件。

    实现:写文件后 sleep 1s 记录 ``now``,再 sleep 1s 后写第二个文件;
    用 ``now`` 作为 since,应只取到第二个文件。
    """
    old_file = tmp_path / "old.md"
    old_file.write_text("old")
    # 让 old.md 的 mtime 落在 sleep 前
    time.sleep(1.1)
    since = datetime.now(tz=UTC)
    time.sleep(1.1)
    new_file = tmp_path / "new.md"
    new_file.write_text("new")

    config = _make_config(str(tmp_path))
    connector = ConnectorRegistry.create(config)
    changed = list(connector.fetch_changes(since))

    titles = {d.title for d in changed}
    assert "new" in titles
    assert "old" not in titles


@pytest.mark.unit
def test_filesystem_reads_binary_without_error(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """二进制/非 utf-8 文件不应抛异常,内容以 ``errors="replace"`` 方式返回。"""
    binary = bytes(range(256))  # 含非 utf-8 字节
    (tmp_path / "bin.md").write_bytes(binary)

    config = _make_config(str(tmp_path))
    connector = ConnectorRegistry.create(config)
    docs = list(connector.fetch_all())

    assert len(docs) == 1
    # 内容非空(具体字符不关心,只要不抛异常即可)
    assert len(docs[0].content) > 0


@pytest.mark.unit
def test_filesystem_fetch_deleted_returns_empty(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """本地文件系统无法可靠检测删除,``fetch_deleted`` 应返回空列表。"""
    (tmp_path / "doc.md").write_text("hello")
    config = _make_config(str(tmp_path))
    connector = ConnectorRegistry.create(config)

    deleted = connector.fetch_deleted(datetime.now(tz=UTC))
    assert deleted == []


@pytest.mark.unit
def test_filesystem_explicit_protocol_implementation(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """``FilesystemConnector`` 应显式继承 ``DataSourceConnector`` 协议。

    ``DataSourceConnector`` 未使用 ``@runtime_checkable``,``isinstance``/``issubclass``
    无法用于校验;改为直接检查 ``__bases__`` 中是否包含该 Protocol。
    """
    from backend.connectors.base import DataSourceConnector

    # 显式继承:DataSourceConnector 应出现在 __bases__ 中
    assert DataSourceConnector in FilesystemConnector.__bases__

    config = _make_config(str(tmp_path))
    connector = ConnectorRegistry.create(config)
    # 实例上验证所需属性/方法均已实现
    assert hasattr(connector, "source_id")
    assert hasattr(connector, "product")
    assert callable(connector.fetch_all)
    assert callable(connector.fetch_changes)
    assert callable(connector.fetch_deleted)


@pytest.mark.unit
def test_filesystem_init_does_not_mutate_config(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """构造器不应 mutate 传入 config 的可变字段。"""
    file_types = [".md"]
    include_dirs = ["docs"]
    config = SourceConfig(
        id="test-fs",
        type="filesystem",
        product="test",
        enabled=True,
        config={
            "root_path": str(tmp_path),
            "file_types": file_types,
            "include_dirs": include_dirs,
        },
        sync_interval="1h",
    )
    connector = FilesystemConnector(config)

    # 构造后修改原列表,不应影响 connector 内部状态
    file_types.append(".txt")
    include_dirs.append("notes")

    assert connector._file_types == {".md"}
    assert connector._include_dirs == ["docs"]


@pytest.mark.unit
def test_filesystem_skips_unreadable_file(
    tmp_path, monkeypatch, caplog
) -> None:  # type: ignore[no-untyped-def]
    """单文件读取异常不应中断整个抓取。

    使用 monkeypatch 让 ``bad.md`` 的 ``read_text`` 抛 ``PermissionError``
    (避免 chmod 000 方案在 CI 以 root 运行时失效)。

    验证三点:
    1. ``fetch_all()`` 不抛异常;
    2. 其他正常文件仍能 yield 出来;
    3. ``logger.warning`` 被调用(caplog 捕获到包含 "无法读取" 的记录)。
    """
    (tmp_path / "good.md").write_text("good content")
    (tmp_path / "bad.md").write_text("bad content")

    config = _make_config(str(tmp_path))
    connector = ConnectorRegistry.create(config)

    original_read_text = Path.read_text

    def fake_read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self.name == "bad.md":
            raise PermissionError(f"mocked permission denied: {self}")
        return original_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", fake_read_text)

    with caplog.at_level(logging.WARNING, logger="backend.connectors.filesystem"):
        docs = list(connector.fetch_all())

    # 只 yield 出 good.md,坏文件被跳过
    assert len(docs) == 1
    assert docs[0].title == "good"
    assert docs[0].content == "good content"
    # logger.warning 被调用,消息含 "无法读取"
    warning_messages = [r.getMessage() for r in caplog.records]
    assert any("无法读取" in msg for msg in warning_messages)
    # 错误信息中包含坏文件名,确认是正确的文件被跳过
    assert any("bad.md" in msg for msg in warning_messages)

    # 同样验证 fetch_changes 不会因单文件异常中断
    caplog.clear()
    since = datetime(2020, 1, 1, tzinfo=UTC)  # 让所有文件都命中 mtime > since
    with caplog.at_level(logging.WARNING, logger="backend.connectors.filesystem"):
        changed_docs = list(connector.fetch_changes(since))

    assert len(changed_docs) == 1
    assert changed_docs[0].title == "good"
    fetch_changes_messages = [r.getMessage() for r in caplog.records]
    assert any("无法读取" in msg for msg in fetch_changes_messages)


# --------------------------------------------------------------------------- #
# Phase 2A:RawDocument 新增 channel_visibility 字段
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_raw_document_has_channel_visibility_default():
    """RawDocument 应包含 channel_visibility 字段,默认 ('widget','api')。"""
    from backend.connectors.base import RawDocument
    doc = RawDocument(
        source_id="t/1", source_type="t", product="t", title="T",
        content="x", url="u", metadata={}, content_hash="h",
    )
    assert doc.channel_visibility == ("widget", "api")
