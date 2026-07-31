"""DataSource ORM -> SourceConfig 转换器单元测试。

验证从 DataSource(JSONB config)到 SourceConfig(frozen dataclass)的映射,
特别是 branches 多分支字段的解析与默认值兼容性。
"""

from dataclasses import FrozenInstanceError

import pytest

from backend.connectors.db_adapter import to_source_config
from backend.connectors.registry import SourceConfig
from backend.db.models import DataSource


@pytest.mark.unit
def test_to_source_config_maps_branches():
    """to_source_config 应从 config.branches 解析多分支并透传基础字段。"""

    ds = DataSource(
        id="ne301",
        type="local_git",
        product="ne301",
        enabled=True,
        config={
            "repo_path": "/x/ne301",
            "branches": ["main", "halow"],
            "file_types": [".c", ".h"],
        },
        sync_interval="1h",
    )
    cfg = to_source_config(ds)
    assert cfg.id == "ne301"
    assert cfg.type == "local_git"
    assert cfg.product == "ne301"
    assert cfg.enabled is True
    assert cfg.sync_interval == "1h"
    assert cfg.branches == ("main", "halow")
    assert cfg.config["repo_path"] == "/x/ne301"
    assert cfg.config["file_types"] == [".c", ".h"]


@pytest.mark.unit
def test_to_source_config_branches_default_empty():
    """config 无 branches 键时,branches 应为空 tuple(单分支兼容)。"""

    ds = DataSource(
        id="docs",
        type="filesystem",
        product="ask_ai",
        enabled=True,
        config={"root_path": "/tmp/docs"},
        sync_interval="24h",
    )
    cfg = to_source_config(ds)
    assert cfg.branches == ()


@pytest.mark.unit
def test_to_source_config_channel_visibility_default():
    """config 无 channel_visibility 时,默认 ('widget','api')。"""

    ds = DataSource(
        id="docs",
        type="filesystem",
        product="ask_ai",
        enabled=True,
        config={"root_path": "/tmp"},
        sync_interval="24h",
    )
    cfg = to_source_config(ds)
    assert cfg.channel_visibility == ("widget", "api")


@pytest.mark.unit
def test_to_source_config_returns_frozen():
    """to_source_config 返回的 SourceConfig 应为不可变(frozen)。"""

    ds = DataSource(
        id="x",
        type="filesystem",
        product="p",
        enabled=True,
        config={},
        sync_interval="1h",
    )
    cfg = to_source_config(ds)
    assert isinstance(cfg, SourceConfig)
    with pytest.raises(FrozenInstanceError):
        cfg.branches = ("main",)  # type: ignore[misc]


@pytest.mark.unit
def test_source_config_branches_default_empty():
    """SourceConfig 直接构造时,branches 默认应为空 tuple。"""

    cfg = SourceConfig(
        id="x",
        type="filesystem",
        product="p",
        enabled=True,
        config={},
        sync_interval="1h",
    )
    assert cfg.branches == ()
