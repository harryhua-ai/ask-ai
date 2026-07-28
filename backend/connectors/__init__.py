"""数据源 Connector 抽象层。

提供 DataSourceConnector Protocol、RawDocument 数据类、
SourceConfig 配置类与 ConnectorRegistry 注册表。
"""

from backend.connectors.base import DataSourceConnector, RawDocument
from backend.connectors.registry import ConnectorRegistry, SourceConfig

__all__ = [
    "ConnectorRegistry",
    "DataSourceConnector",
    "RawDocument",
    "SourceConfig",
]
