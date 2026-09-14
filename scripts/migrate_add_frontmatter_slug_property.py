"""Add the additive ``frontmatter_slug`` property to the Weaviate collection."""

import logging
import os
import sys
from pathlib import Path

import weaviate
from weaviate.classes.config import DataType, Property
from weaviate.exceptions import WeaviateInvalidInputError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logger = logging.getLogger(__name__)


def ensure_frontmatter_slug_property(collection) -> bool:
    """补齐 schema property；已存在时 no-op，不改对象。"""
    existing = {p.name for p in collection.config.get().properties}
    if "frontmatter_slug" in existing:
        return False
    try:
        collection.config.add_property(
            Property(name="frontmatter_slug", data_type=DataType.TEXT)
        )
    except WeaviateInvalidInputError as exc:
        logger.warning("frontmatter_slug 新增失败(跳过): %s", str(exc)[:200])
        return False
    return True


def _endpoint(raw: str) -> tuple[str, int]:
    from urllib.parse import urlparse

    value = raw if "://" in raw else f"http://{raw}"
    parsed = urlparse(value)
    return parsed.hostname or "localhost", parsed.port or 8080


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    host, port = _endpoint(os.environ.get("WEAVIATE_URL", "http://localhost:8080"))
    class_name = os.environ.get("WEAVIATE_CLASS_NAME", "Document")
    client = weaviate.connect_to_local(host=host, port=port)
    try:
        if not client.collections.exists(class_name):
            logger.error("collection %s 不存在,先运行 sync.py 创建", class_name)
            return 1
        added = ensure_frontmatter_slug_property(client.collections.get(class_name))
        logger.info("frontmatter_slug %s", "已新增" if added else "已存在/未变更")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
