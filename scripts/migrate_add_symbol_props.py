"""增量加 symbol_* Property 到 Weaviate Document collection(不删数据)。

Weaviate v4 支持 ``collection.config.add_property(prop)`` 增量加 property,
老 chunk 的 symbol_* 字段为空(后续重索引补)。若 property 已存在会抛
``WeaviateInvalidInputError``,脚本捕获并跳过(幂等)。

用法:
    python scripts/migrate_add_symbol_props.py

环境变量(与 scripts/sync.py 一致):
    WEAVIATE_URL — Weaviate 端点(默认 http://localhost:8080)
    WEAVIATE_CLASS_NAME — collection 名(默认 Document)

注意:此脚本只加 schema property,不回填已有 chunk 的 symbol_* 值。
要回填 symbol_* 需要对代码文档重索引(drop + sync,或后续增量 fetch_changes
触发 chunk_code 重切分)。本脚本不 drop collection,57.97 万 chunk 数据安全。
"""

import logging
import os
import sys

import weaviate
from weaviate.classes.config import DataType, Property
from weaviate.exceptions import WeaviateInvalidInputError

logger = logging.getLogger(__name__)

_SYMBOL_PROPS: list[tuple[str, DataType]] = [
    ("symbol_name", DataType.TEXT),
    ("symbol_signature", DataType.TEXT),
    ("symbol_node_type", DataType.TEXT),
    ("symbol_tokens", DataType.TEXT),
]


def _parse_weaviate_endpoint(weaviate_url: str) -> tuple[str, int]:
    """从 weaviate_url 解析 (host, port);缺省端口取 8080。"""
    url = weaviate_url
    if "://" not in url:
        url = f"http://{url}"
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 8080
    return host, port


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    weaviate_url = os.environ.get("WEAVIATE_URL", "http://localhost:8080")
    class_name = os.environ.get("WEAVIATE_CLASS_NAME", "Document")

    host, port = _parse_weaviate_endpoint(weaviate_url)
    logger.info("连接 Weaviate %s:%d, collection=%s", host, port, class_name)
    client = weaviate.connect_to_local(host=host, port=port)
    try:
        if not client.collections.exists(class_name):
            logger.error("collection %s 不存在,先运行 sync.py 创建", class_name)
            return 1
        col = client.collections.get(class_name)
        existing = {p.name for p in col.config.get().properties}
        added = 0
        for name, dtype in _SYMBOL_PROPS:
            if name in existing:
                logger.info("property %s 已存在,跳过", name)
                continue
            try:
                col.config.add_property(Property(name=name, data_type=dtype))
                logger.info("已加 property %s(%s)", name, dtype)
                added += 1
            except WeaviateInvalidInputError as exc:
                # 并发 / 已存在场景,幂等跳过
                logger.warning("add_property %s 跳过(已存在或无效输入): %s", name, str(exc)[:200])
        logger.info("迁移完成:新增 %d 个 symbol property", added)
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())