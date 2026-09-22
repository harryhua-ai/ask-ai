"""Issue #106 — 迁移工具对 label 固化行的重推导能力(label_override)。

生产实证(v1.6.4-r1 回填):``derive_product`` 的规则组 key = **chunk 现存
标签**;官方 Solution 页 chunk 在历史规则缺失时代已固化为 ``unknown``,
迁移扫描把 ``unknown`` 当作组 key —— website 组规则(含新的
``/solutions/`` → solutions)对 unknown 固化行**永不适用**,changed=0。

修复(工具面,保持既有 fail-safe 契约):plan/apply 增加显式
``label_override`` —— 以调用方声明的源标签为规则组 key 重推导。仍沿用
dry-run → 人工核对 unknown 明细 → apply 的门序;override 是显式人工
决策,不做任何自动猜测。
"""

from dataclasses import dataclass, field

import pytest

from backend.product_taxonomy import get_taxonomy
from backend.services.product_migration import apply_migration, plan_migration

pytestmark = pytest.mark.unit

TAX = get_taxonomy()


@dataclass
class FakeObj:
    uuid: str
    properties: dict


@dataclass
class FakeData:
    updates: list = field(default_factory=list)

    def update(self, *, uuid, properties):
        self.updates.append((uuid, dict(properties)))


@dataclass
class FakeCollection:
    objects: list
    data: FakeData = field(default_factory=FakeData)

    def iterator(self, *, include_vector=False, return_properties=None):
        assert include_vector is False
        yield from self.objects


class FakeCollections:
    def __init__(self, collection):
        self._collection = collection

    def get(self, _name):
        return self._collection


class FakeClient:
    def __init__(self, collection):
        self.collection = collection
        self.collections = FakeCollections(collection)


def _chunk(source_id, product, url, uuid):
    return FakeObj(
        uuid=uuid,
        properties={"source_id": source_id, "product": product, "url": url},
    )


SOLUTION_PAGE = _chunk(
    "website-camthink/solutions/infrastructure-monitoring",
    "unknown",
    "https://www.camthink.ai/solutions/infrastructure-monitoring/",
    "u-sol",
)
BLOG_PAGE = _chunk(
    "website-camthink/blog/zone-intrusion",
    "unknown",
    "https://www.camthink.ai/blog/zone-intrusion-detection-camera-system-guide/",
    "u-blog",
)


def test_override_rederives_frozen_unknown_solution_page():
    """unknown 固化的方案段页面,以源标签 website 重推导 → solutions。"""
    client = FakeClient(FakeCollection([SOLUTION_PAGE, BLOG_PAGE]))
    report = plan_migration(
        client,
        class_name="Document",
        source_ids=["website-camthink"],
        taxonomy=TAX,
        label_override="website",
    )
    assert report.total_changed == 1, (
        "with an explicit source-label override, the frozen-unknown "
        "solutions page must be re-derived through the website rule group "
        "(the /solutions/ shared-bucket rule); without the override the "
        "frozen label itself is used as the rule-group key and the rule "
        "can never apply"
    )

    applied = apply_migration(
        client,
        class_name="Document",
        source_ids=["website-camthink"],
        taxonomy=TAX,
        label_override="website",
    )
    assert applied.total_changed == 1
    assert client.collection.data.updates == [
        ("u-sol", {"product": "solutions"})
    ], "only the solutions page changes; the unmapped blog page stays unknown"


def test_without_override_frozen_unknown_stays_frozen():
    """无 override:既有语义零变化(unknown 是组 key,规则不适用)。"""
    client = FakeClient(FakeCollection([SOLUTION_PAGE]))
    report = plan_migration(
        client,
        class_name="Document",
        source_ids=["website-camthink"],
        taxonomy=TAX,
    )
    assert report.total_changed == 0
    assert client.collection.data.updates == []
