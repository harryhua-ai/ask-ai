"""增量加 commerce/variation 商业真值 Property 到 Weaviate Document collection(不删数据)。

Issue #28 / v1.6.4 Track B1(契约 §4 pin 2026-09-16):变体真值结构化 schema
增量,仅加 property,不动任何对象、不重嵌入。Weaviate v4 支持
``collection.config.add_property(prop)`` 增量加 property,存量老对象该字段
缺失(读取按显式缺省解释,见 ``backend.pipeline.ingest._commerce_props`` 与
``_to_search_result`` 兼容缺省)。property 已存在时抛
``WeaviateInvalidInputError``,脚本捕获并跳过(幂等:重跑零新增、plan 逐字一致)。

用法:
    python scripts/migrate_add_commerce_variation_props.py [--plan]

    --plan  只打印将新增的 property(计划),不执行任何变更(幂等验证:
            连续两次 plan 输出逐字一致)。

环境变量(与 scripts/sync.py 一致):
    WEAVIATE_URL — Weaviate 端点(默认 http://localhost:8080)
    WEAVIATE_CLASS_NAME — collection 名(默认 Document)

登记:deploy/prod/migrations.json(发布冻结树部署编排逐条执行;生产 schema
迁移随部署路径执行,本脚本不在调查/实现阶段对生产运行)。
"""

import logging
import os
import sys
from pathlib import Path

import weaviate
from weaviate.classes.config import DataType, Property
from weaviate.exceptions import WeaviateInvalidInputError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.commerce_meta import COMMERCE_PROPS, COMMERCE_PROPERTIES  # noqa: E402

logger = logging.getLogger(__name__)

# 单一权威定义点 = COLLECTION_PROPERTIES(契约:ingest 建表与增量迁移共用);
# 本迁移只加 commerce 段(本次新增),类型映射与 _ensure_collection 的 _DT 一致。
_DT = {
    "text": DataType.TEXT,
    "int": DataType.INT,
    "text[]": DataType.TEXT_ARRAY,
    "bool": DataType.BOOL,
}


def _commerce_property_names() -> list[str]:
    """本迁移负责的 property 名(= COMMERCE_PROPERTIES 单一权威词表)。"""
    return [name for name, _dtype in COMMERCE_PROPERTIES]


def plan_commerce_props(col) -> list[str]:
    """返回 collection 尚缺失、本迁移将新增的 commerce property 名(只读)。"""
    existing = {p.name for p in col.config.get().properties}
    return [name for name in _commerce_property_names() if name not in existing]


def ensure_commerce_props(col) -> list[str]:
    """向 collection 增量补齐缺失的 commerce property,返回实际新增名单。

    幂等:已存在的 property 跳过;只动 schema,不写任何对象数据。
    """
    added: list[str] = []
    dtypes = dict(COMMERCE_PROPERTIES)
    for name in plan_commerce_props(col):
        dtype = dtypes[name]
        try:
            col.config.add_property(Property(name=name, data_type=_DT[dtype]))
            added.append(name)
            logger.info("property %s 已新增(%s)", name, dtype)
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
    plan_only = "--plan" in sys.argv
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
        if plan_only:
            pending = plan_commerce_props(col)
            print("PLAN add_commerce_variation_props:", ",".join(pending) or "(none)")
            return 0
        added = ensure_commerce_props(col)
        logger.info("完成:新增 %d 个 property%s", len(added), f": {added}" if added else "")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
