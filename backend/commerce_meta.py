"""变体商业真值 property 词表(Issue #28 / v1.6.4 Track B1,契约 §4 pin)。

单一权威定义点(与 :mod:`backend.evidence_meta` 同范式):ingest 建表
(``COLLECTION_PROPERTIES``)、检索投影(search.py return_properties)、增量
迁移(scripts/migrate_add_commerce_variation_props.py)三方共用本词表,
保证 schema/投影/迁移零漂移。本模块必须是叶模块(不 import backend 其他
业务模块),避免检索 ↔ 管线循环导入。

契约 §4 pin(2026-09-16):
- variation_identity_key = "{product_id}:{variation_id}"
- commerce_type ∈ {"product", "variation"};variation_id=0 表示父产品
- 非 woo 文档不投影(键缺省 = 空值,诚实缺席)
"""

from __future__ import annotations

from typing import Any

# commerce 段 property 定义(名, Weaviate 类型)——COLLECTION_PROPERTIES 的
# commerce 子段;类型词表与 ingest._ensure_collection._DT 一致。
COMMERCE_PROPERTIES: list[tuple[str, str]] = [
    ("commerce_type", "text"),
    ("product_id", "int"),
    ("variation_id", "int"),
    ("variation_identity_key", "text"),
    ("sku", "text"),
    ("price", "text"),
    ("regular_price", "text"),
    ("sale_price", "text"),
    ("on_sale", "bool"),
    ("stock_status", "text"),
    ("stock_quantity", "int"),
    ("purchasable", "bool"),
    ("variation_attributes", "text[]"),
    ("permalink", "text"),
    ("commerce_synced_at", "text"),
]

# commerce 投影词表:prop 名 → (Weaviate 类型, doc.metadata 键, 缺省值)。
# 仅对 source_type="woocommerce" 投影;metadata 缺键用缺省(诚实空值,
# 不伪造)。stock_quantity None = 端点未管理库存 → 整键省略(不写 0 伪装)。
COMMERCE_PROPS: dict[str, tuple[str, str, Any]] = {
    "commerce_type": ("text", "commerce_type", "product"),
    "product_id": ("int", "product_id", 0),
    "variation_id": ("int", "variation_id", 0),
    "variation_identity_key": ("text", "variation_identity_key", ""),
    "sku": ("text", "sku", ""),
    "price": ("text", "price", ""),
    "regular_price": ("text", "regular_price", ""),
    "sale_price": ("text", "sale_price", ""),
    "on_sale": ("bool", "on_sale", False),
    "stock_status": ("text", "stock_status", ""),
    "stock_quantity": ("int", "stock_quantity", None),
    "purchasable": ("bool", "purchasable", False),
    "variation_attributes": ("text[]", "variation_attributes", []),
    "permalink": ("text", "permalink", ""),
    "commerce_synced_at": ("text", "date_modified", ""),
}

assert set(COMMERCE_PROPS) == {name for name, _ in COMMERCE_PROPERTIES}, (
    "COMMERCE_PROPS 与 COMMERCE_PROPERTIES 词表漂移(契约 §4 单一词表)"
)
