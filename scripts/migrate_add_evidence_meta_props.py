"""增量加 evidence_* 证据语义 Property 到 Weaviate Document collection(不删数据)。

INC-2a 冻结契约 §6/§8/§16:元数据 schema 增量,仅加 property,不动任何对象、
不重嵌入。Weaviate v4 支持 ``collection.config.add_property(prop)`` 增量加
property,存量老对象该字段缺失(读取按显式 unknown 解释,见
``backend.evidence_meta`` 与 ``_to_search_result`` 兼容缺省)。property 已存在
时抛 ``WeaviateInvalidInputError``,脚本捕获并跳过(幂等)。

用法:
    python scripts/migrate_add_evidence_meta_props.py

环境变量(与 scripts/sync.py 一致):
    WEAVIATE_URL — Weaviate 端点(默认 http://localhost:8080)
    WEAVIATE_CLASS_NAME — collection 名(默认 Document)
"""

import logging
import os
import sys
from pathlib import Path

import weaviate
from weaviate.classes.config import DataType, Property
from weaviate.exceptions import WeaviateInvalidInputError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.evidence_meta import EVIDENCE_PROPERTIES  # noqa: E402

logger = logging.getLogger(__name__)


def ensure_evidence_props(col) -> list[str]:
    """向 collection 增量补齐缺失的 evidence_* property,返回实际新增名单。

    幂等:已存在的 property 跳过。只动 schema,不写任何对象数据。
    """
    added: list[str] = []
    existing = {p.name for p in col.config.get().properties}
    for name in EVIDENCE_PROPERTIES:
        if name in existing:
            logger.info("property %s 已存在,跳过", name)
            continue
        try:
            col.config.add_property(Property(name=name, data_type=DataType.TEXT))
            added.append(name)
            logger.info("property %s 已新增", name)
        except WeaviateInvalidInputError as exc:
            logger.warning("property %s 新增失败(跳过):%s", name, str(exc)[:200])
    return added


def _parse_weaviate_endpoint(weaviate_url: str) -> tuple[str, int]:
    url = weaviate_url
    if "://" not in url:
        url = f"http://{url}"
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return parsed.hostname or "localhost", parsed.port or 8080


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
        added = ensure_evidence_props(col)
        logger.info("完成:新增 %d 个 property %s", len(added), added or "(无)")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
