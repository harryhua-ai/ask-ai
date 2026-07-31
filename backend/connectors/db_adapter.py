"""DataSource ORM -> SourceConfig 适配器。

DB 层存的是 :class:`backend.db.models.DataSource`(SQLAlchemy ORM,config 列
为 JSONB),而 Connector / sync 管道消费的是
:class:`backend.connectors.registry.SourceConfig`(frozen dataclass)。
本模块提供单向无副作用转换函数,把 JSONB ``config`` 中的 list 字段
(``branches`` / ``channel_visibility``)转成不可变 tuple 以匹配 dataclass 契约。
"""

from backend.connectors.registry import SourceConfig
from backend.db.models import DataSource


def to_source_config(ds: DataSource) -> SourceConfig:
    """DataSource(ORM) -> SourceConfig(frozen dataclass)。

    ``config`` JSONB 列原样透传(list 字段转换为不可变 tuple)。不修改入参。

    Args:
        ds: ORM 行。``config`` 中可选键:
            - ``branches``: list[str] 多分支(默认空 tuple = 单分支)
            - ``channel_visibility``: list[str] 渠道白名单
              (默认 ``("widget", "api")``)

    Returns:
        与 ``ds`` 等价的 :class:`SourceConfig`(不可变)。
    """
    return SourceConfig(
        id=ds.id,
        type=ds.type,
        product=ds.product,
        enabled=ds.enabled,
        config=ds.config,
        sync_interval=ds.sync_interval,
        branches=tuple(ds.config.get("branches", ())),
        channel_visibility=tuple(ds.config.get("channel_visibility", ("widget", "api"))),
    )
