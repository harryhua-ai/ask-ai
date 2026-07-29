"""数据源 Connector 抽象层。

提供 DataSourceConnector Protocol、RawDocument 数据类。
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class RawDocument:
    """从数据源抓取的原始文档(不可变)。

    封装文档内容与元数据,作为 Connector 输出与分段管道输入的统一契约。

    Attributes:
        source_id: 文档在源系统内的唯一标识。
        source_type: 数据源类型(如 github、filesystem)。
        product: 所属产品线(如 ask_ai、ne503)。
        title: 文档标题。
        content: 文档正文。
        url: 文档可访问 URL(便于溯源)。
        metadata: 扩展元数据(如标签、语言、MIME 类型)。
        content_hash: 内容哈希,用于变更检测与去重。
    """

    source_id: str
    source_type: str
    product: str
    title: str
    content: str
    url: str
    metadata: dict[str, Any]
    content_hash: str


class DataSourceConnector(Protocol):
    """数据源 Connector 协议。

    所有具体 Connector 必须实现该协议,以提供全量抓取、增量变更抓取
    与已删除文档 ID 查询能力。
    """

    @property
    def source_id(self) -> str: ...

    @property
    def product(self) -> str: ...

    def fetch_all(self) -> Iterator[RawDocument]: ...

    def fetch_changes(self, since: datetime) -> Iterator[RawDocument]: ...

    def fetch_deleted(self, since: datetime) -> list[str]: ...
