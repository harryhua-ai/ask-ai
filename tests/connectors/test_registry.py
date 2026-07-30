"""ConnectorRegistry 与 SourceConfig 单元测试。

验证注册装饰器、工厂方法以及从 YAML 字典加载配置的能力。
"""

from collections.abc import Iterator
from datetime import datetime

import pytest

from backend.connectors.base import RawDocument
from backend.connectors.registry import ConnectorRegistry, SourceConfig


@pytest.mark.unit
def test_register_and_create_connector():
    """register 装饰器应将类型名绑定到 Connector 类,create 能按配置实例化。"""

    @ConnectorRegistry.register("test_type")
    class TestConnector:
        def __init__(self, config: SourceConfig):
            self._config = config

        @property
        def source_id(self) -> str:
            return self._config.id

        @property
        def product(self) -> str:
            return self._config.product

        def fetch_all(self) -> Iterator[RawDocument]:
            yield RawDocument(
                source_id="test-1",
                source_type="test_type",
                product="test",
                title="Test Doc",
                content="Hello world",
                url="https://example.com/test",
                metadata={},
                content_hash="abc123",
            )

        def fetch_changes(self, since: datetime) -> Iterator[RawDocument]:
            return iter([])

        def fetch_deleted(self, since: datetime) -> list[str]:
            return []

    config = SourceConfig(
        id="test-source",
        type="test_type",
        product="test",
        enabled=True,
        config={},
        sync_interval="1h",
    )

    connector = ConnectorRegistry.create(config)
    assert connector.source_id == "test-source"
    docs = list(connector.fetch_all())
    assert len(docs) == 1
    assert docs[0].title == "Test Doc"


# --------------------------------------------------------------------------- #
# Phase 2A:SourceConfig 新增 channel_visibility 字段
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_source_config_channel_visibility_default():
    """SourceConfig 应包含 channel_visibility 字段,默认 ('widget','api')。"""
    from backend.connectors.registry import SourceConfig
    cfg = SourceConfig(
        id="t", type="github", product="t", enabled=True, config={}, sync_interval="1h",
    )
    assert cfg.channel_visibility == ("widget", "api")


@pytest.mark.unit
def test_load_configs_reads_channel_visibility():
    """load_configs 应从 YAML 字典读取 channel_visibility 字段。"""
    from backend.connectors.registry import ConnectorRegistry
    yaml_data = {
        "sources": [
            {
                "id": "internal", "type": "filesystem", "product": "knowledge",
                "channel_visibility": ["api"],
                "config": {"root_path": "/tmp"},
            }
        ]
    }
    configs = ConnectorRegistry.load_configs(yaml_data)
    assert configs[0].channel_visibility == ("api",)
