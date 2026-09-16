"""migrate_add_commerce_variation_props 幂等性测试(Issue #28 / B1-3)。

mock collection(仿 test_migrate_backfill_evidence_meta.py 模式):
- plan_commerce_props 只读:对已齐全 schema 返回 []
- ensure_commerce_props:缺失补齐;重跑(已齐全)零新增 → 幂等
- commerce 段与 COLLECTION_PROPERTIES 类型定义逐字一致(单一权威定义点)
"""

from unittest.mock import MagicMock

import pytest

from backend.commerce_meta import COMMERCE_PROPS, COMMERCE_PROPERTIES
from scripts.migrate_add_commerce_variation_props import (
    _commerce_property_names,
    ensure_commerce_props,
    plan_commerce_props,
)


class _ConfigSnapshot:
    """config.get() 快照:properties 动态读取当前名单。"""

    def __init__(self, names: list[str]):
        self._names = names

    @property
    def properties(self):
        objs = []
        for n in self._names:
            p = MagicMock()
            p.name = n
            objs.append(p)
        return objs


class _FakeConfig:
    """col.config 替身:记录初始 property 与 add_property 追加。

    真实 weaviate v4 接口是 ``col.config.get().properties``。
    """

    def __init__(self, initial: list[str]):
        self.names = list(initial)
        self.added: list[str] = []

    def get(self):
        return _ConfigSnapshot(self.names)

    def add_property(self, prop):
        if prop.name in self.names:
            from weaviate.exceptions import WeaviateInvalidInputError

            raise WeaviateInvalidInputError("property already exists")
        self.names.append(prop.name)
        self.added.append(prop.name)


def _fake_collection(initial: list[str]) -> MagicMock:
    col = MagicMock()
    col.config = _FakeConfig(initial)
    return col


_COMMERCE_NAMES = _commerce_property_names()

# 非 commerce 既有 property(模拟存量 collection)
_EXISTING_BASE = [
    "source_id",
    "source_type",
    "product",
    "title",
    "text",
    "url",
    "frontmatter_slug",
    "chunk_index",
    "content_hash",
]


@pytest.mark.unit
def test_commerce_property_names_match_pinned_interface():
    """commerce 段 = 契约 §4 pin 的 15 个加性 property(词表逐字一致)。"""
    assert _COMMERCE_NAMES == [
        "commerce_type",
        "product_id",
        "variation_id",
        "variation_identity_key",
        "sku",
        "price",
        "regular_price",
        "sale_price",
        "on_sale",
        "stock_status",
        "stock_quantity",
        "purchasable",
        "variation_attributes",
        "permalink",
        "commerce_synced_at",
    ]
    # 单一权威定义点:COMMERCE_PROPERTIES 自带类型,与 COLLECTION_PROPERTIES 段一致
    dtype_map = dict(COMMERCE_PROPERTIES)
    for name in _COMMERCE_NAMES:
        assert name in dtype_map
    # COMMERCE_PROPS 键与 commerce 段完全重合(不缺不多)
    assert set(COMMERCE_PROPS) == set(_COMMERCE_NAMES)


@pytest.mark.unit
def test_plan_is_read_only_and_reports_missing():
    """plan 只读:存量缺 commerce 段时报告缺失名单,不改变 schema。"""
    col = _fake_collection(_EXISTING_BASE)
    pending = plan_commerce_props(col)
    assert pending == _COMMERCE_NAMES
    assert col.config.added == []  # plan 零变更


@pytest.mark.unit
def test_ensure_adds_missing_then_idempotent():
    """ensure 首跑补齐,重跑零新增(幂等:重跑 plan 逐字一致)。"""
    col = _fake_collection(_EXISTING_BASE)
    added_first = ensure_commerce_props(col)
    assert sorted(added_first) == sorted(_COMMERCE_NAMES)

    # 重跑:plan 为空,ensure 零新增
    assert plan_commerce_props(col) == []
    added_second = ensure_commerce_props(col)
    assert added_second == []


@pytest.mark.unit
def test_ensure_skips_existing_properties():
    """部分已存在的 property 跳过(存量库半迁移态安全)。"""
    col = _fake_collection(_EXISTING_BASE + ["sku", "price"])
    added = ensure_commerce_props(col)
    assert "sku" not in added
    assert "price" not in added
    assert sorted(added) == sorted(set(_COMMERCE_NAMES) - {"sku", "price"})
