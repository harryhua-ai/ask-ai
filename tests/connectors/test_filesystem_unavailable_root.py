"""Issue #100 AC2:配置源根目录对执行面不可用/不可读 ⇒ 连接器 fail-closed 报错。

生产事故(2026-09-21,knowledge-support-cases):上传根只存在于 backend 容器
可写层;sync-executor/sync-cron 解析同一相对路径时目录不存在。Python 3.13
pathlib 的 ``rglob`` 对缺失根**静默返回空集**(不抛错),于是执行面把
「根不可见」误判为「无变更成功」,账本行被逐轮政策缺席分类,操作员看到的
actionable-missing 计数是执行面文件系统隔离的伪影而非真实对账真相。

契约:#100 AC2 —— 根缺失/不可读必须显式抛
:class:`backend.connectors.base.SourceRootUnavailable`(可执行的源访问/
拓扑错误),绝不以空全集伪装「成功/无变更」。

边界(AC4):根**存在**但无匹配文件 = 合法空源/合法范围变化,维持既有
no-change 语义,不受本 fail-closed 影响(不弱化既有契约)。
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from backend.connectors.base import SourceRootUnavailable
from backend.connectors.filesystem import FilesystemConnector
from backend.connectors.registry import SourceConfig


def _connector(root: Path, include_dirs: list[str] | None = None) -> FilesystemConnector:
    return FilesystemConnector(
        SourceConfig(
            id="upload-src",
            type="filesystem",
            product="probe",
            enabled=True,
            sync_interval="24h",
            branches=[],
            channel_visibility=("widget", "api"),
            config={
                "root_path": str(root),
                "file_types": [".md"],
                "include_dirs": include_dirs or [],
            },
        )
    )


def test_fetch_all_missing_root_raises_source_unavailable(tmp_path):
    """AC2:根目录不存在 ⇒ fetch_all 显式抛 SourceRootUnavailable。

    RED(现状):Python 3.13 ``rglob`` 对缺失根静默空集 ⇒ 函数正常返回空
    迭代器,「根不可见」被伪装成「合法空源」—— 正是生产事故的执行面
    伪健康来源。
    """
    connector = _connector(tmp_path / "missing-root")
    with pytest.raises(SourceRootUnavailable) as excinfo:
        list(connector.fetch_all())
    # 可执行性:错误必须携带配置根路径,操作员可定位部署挂载缺口
    assert "missing-root" in str(excinfo.value)


def test_fetch_changes_missing_root_raises_source_unavailable(tmp_path):
    """AC2:根目录不存在 ⇒ fetch_changes 同样 fail-closed(增量路径)。

    RED(现状):静默空集 ⇒ ``_sync_one`` 走「无变更」路径,账本缺席
    分类照跑 —— 生产事故中「政策缺席 include_dirs」日志的直接来源。
    """
    connector = _connector(tmp_path / "missing-root", include_dirs=["docs"])
    with pytest.raises(SourceRootUnavailable):
        list(connector.fetch_changes(datetime.now(UTC)))


def test_existing_empty_root_stays_legitimate_no_change(tmp_path):
    """AC4 边界:根存在(空目录/无匹配文件)= 合法空源 ⇒ 不抛错、空集。

    fail-closed 只针对「根不可用」,不把合法空源/范围变化误伤为错误
    (不弱化既有 no-change 契约)。
    """
    root = tmp_path / "real-but-empty"
    root.mkdir()
    connector = _connector(root, include_dirs=["docs"])
    assert list(connector.fetch_all()) == []
    assert list(connector.fetch_changes(datetime.now(UTC))) == []


def test_unreadable_root_raises_source_unavailable(tmp_path):
    """AC2:根存在但执行面不可读(权限)⇒ 同样显式抛错。

    与「根缺失」同族:执行面无法枚举 ⇒ 不得伪装成功。运行环境若
    不受 POSIX 权限约束(如 root),权限维度不可证 ⇒ 跳过(诚实不可证)。
    """
    import os

    root = tmp_path / "locked-root"
    root.mkdir()
    root.chmod(0o000)
    try:
        if os.access(root, os.R_OK):
            pytest.skip("当前运行身份不受目录权限约束,不可读维度不可证")
        connector = _connector(root)
        with pytest.raises(SourceRootUnavailable):
            list(connector.fetch_all())
    finally:
        root.chmod(0o755)
