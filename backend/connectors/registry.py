"""数据源 Connector 注册表与配置。

ConnectorRegistry 提供"类型名 -> Connector 类"的注册机制;
SourceConfig 描述单个数据源实例的配置(从 YAML 加载)。
"""

from dataclasses import dataclass
from typing import Any, ClassVar

from backend.connectors.base import DataSourceConnector


@dataclass(frozen=True)
class SourceConfig:
    """数据源配置(不可变)。

    由 YAML 配置文件加载,描述单个数据源实例的身份、类型、
    同步策略与供应商特定参数。

    Attributes:
        id: 数据源实例的唯一标识(用于数据库 source_id 字段)。
        type: Connector 类型名,用于在注册表中查找实现类。
        product: 所属产品线(如 ask_ai、ne503)。
        enabled: 是否启用该数据源(禁用的源不会被同步)。
        config: 供应商特定参数(如 GitHub token、文件路径)。
        sync_interval: 同步间隔表达式(如 "1h"、"24h")。
    """

    id: str
    type: str
    product: str
    enabled: bool
    config: dict[str, Any]
    sync_interval: str


class ConnectorRegistry:
    """Connector 注册表(类级存储)。

    通过装饰器语法注册 Connector 类,运行期按 config.type 名称查找并实例化。
    """

    _connectors: ClassVar[dict[str, type]] = {}

    @classmethod
    def register(cls, connector_type: str):
        """注册装饰器:将 Connector 类绑定到指定类型名。

        Args:
            connector_type: 类型名(与 SourceConfig.type 对应)。

        Returns:
            装饰器函数,原样返回被装饰的类。
        """

        def decorator(connector_cls):
            cls._connectors[connector_type] = connector_cls
            return connector_cls

        return decorator

    @classmethod
    def create(cls, config: SourceConfig) -> DataSourceConnector:
        """按配置实例化已注册的 Connector。

        Args:
            config: 数据源配置实例。

        Returns:
            实现了 DataSourceConnector 协议的实例。

        Raises:
            KeyError: 当 config.type 未注册时。
        """
        connector_cls = cls._connectors[config.type]
        return connector_cls(config)

    @classmethod
    def load_configs(cls, yaml_data: dict) -> list[SourceConfig]:
        """从 YAML 字典加载多个数据源配置。

        期望的 YAML 结构:

            sources:
              - id: ...
                type: ...
                product: ...
                enabled: true        # 可选,默认 True
                config: {...}        # 可选,默认 {}
                sync_interval: "24h" # 可选,默认 "24h"

        Args:
            yaml_data: 已解析的 YAML 字典。

        Returns:
            SourceConfig 列表(保留输入顺序)。
        """
        configs: list[SourceConfig] = []
        for src in yaml_data.get("sources", []):
            configs.append(
                SourceConfig(
                    id=src["id"],
                    type=src["type"],
                    product=src["product"],
                    enabled=src.get("enabled", True),
                    config=src.get("config", {}),
                    sync_interval=src.get("sync_interval", "24h"),
                )
            )
        return configs
