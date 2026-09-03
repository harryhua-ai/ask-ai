"""产品元数据迁移工具(契约 §4)单元测试。

- source-scoped:只触及指定源(客户端侧 source_id 首段精确匹配,不做
  TEXT 分词过滤——P0-A 教训);
- deterministic:同输入同映射;规则/canonical/unknown 三态可复算;
- dry-run first:plan 零写入;
- in-place property update:仅 ``product`` 属性更新,不触向量(零 re-embed);
- 报告 old→new 计数 + unknown 明确列出,无静默丢文档。
"""

from dataclasses import dataclass, field

from backend.product_taxonomy import get_taxonomy
from backend.services.product_migration import apply_migration, plan_migration

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
        assert include_vector is False  # 迁移不取向量(零 re-embed 的读侧证据)
        yield from self.objects


class FakeCollections:
    def __init__(self, collection: FakeCollection):
        self._collection = collection

    def get(self, _name):
        return self._collection


class FakeClient:
    """对齐 weaviate v4:``client.collections.get(name)`` 返回 collection。"""

    def __init__(self, collection: FakeCollection):
        self.collection = collection
        self.collections = FakeCollections(collection)


def _client(objects):
    return FakeClient(FakeCollection(objects))


def _wiki_chunk(source_id, product, uuid=None):
    return FakeObj(
        uuid=uuid or f"u-{source_id}",
        properties={"source_id": source_id, "product": product, "url": ""},
    )


class TestPlanMigration:
    def test_dry_run_writes_nothing_and_reports_mapping(self):
        objects = [
            _wiki_chunk("wiki-documents-local/main/docs/6-neoeyes-ne503-series/a.md", "wiki", "u1"),
            _wiki_chunk("wiki-documents-local/main/docs/5-neoeyes-ne301-series/b.md", "wiki", "u2"),
            _wiki_chunk("ne301-local/main/README.md", "ne301", "u3"),
        ]
        client = _client(objects)
        report = plan_migration(
            client, class_name="Document", source_ids=["wiki-documents-local", "ne301-local"], taxonomy=TAX
        )
        assert client.collection.data.updates == []  # dry-run 零写入
        assert report.total_scanned == 3
        assert report.total_changed == 2  # 两条 wiki 规则命中
        wiki = next(s for s in report.sources if s.source_id == "wiki-documents-local")
        assert wiki.mapping["wiki"] == {"ne503": 1, "ne301": 1}

    def test_unknown_listed_not_silently_dropped(self):
        objects = [
            _wiki_chunk("wiki-documents-local/main/.image-upload/README.md", "wiki", "u1"),
        ]
        client = _client(objects)
        report = plan_migration(
            client, class_name="Document", source_ids=["wiki-documents-local"], taxonomy=TAX
        )
        assert report.total_unknown == 1
        wiki = report.sources[0]
        assert wiki.unknown_count == 1
        assert wiki.unknown_samples == ["wiki-documents-local/main/.image-upload/README.md"]
        assert wiki.mapping["wiki"] == {"unknown": 1}

    def test_source_scoping_excludes_other_sources(self):
        objects = [
            _wiki_chunk("ne301-local/main/README.md", "ne301", "u1"),
            _wiki_chunk("wiki-documents-local/main/docs/6-neoeyes-ne503-series/a.md", "wiki", "u2"),
        ]
        client = _client(objects)
        report = plan_migration(
            client, class_name="Document", source_ids=["wiki-documents-local"], taxonomy=TAX
        )
        assert report.total_scanned == 1  # ne301-local 未被触及

    def test_legacy_label_canonicalized(self):
        objects = [
            _wiki_chunk("meta-hailo-os-local/main/README.md", "meta-hailo-os", "u1"),
        ]
        client = _client(objects)
        report = plan_migration(
            client, class_name="Document", source_ids=["meta-hailo-os-local"], taxonomy=TAX
        )
        assert report.total_changed == 1
        assert report.sources[0].mapping["meta-hailo-os"] == {"ne503": 1}


class TestApplyMigration:
    def test_apply_updates_only_changed_products_in_place(self):
        objects = [
            _wiki_chunk("wiki-documents-local/main/docs/6-neoeyes-ne503-series/a.md", "wiki", "u1"),
            _wiki_chunk("ne301-local/main/README.md", "ne301", "u2"),  # 已 canonical,不变
        ]
        client = _client(objects)
        report = apply_migration(
            client, class_name="Document", source_ids=["wiki-documents-local", "ne301-local"], taxonomy=TAX
        )
        assert client.collection.data.updates == [("u1", {"product": "ne503"})]
        assert report.total_changed == 1
        assert report.total_unchanged == 1

    def test_apply_is_idempotent(self):
        objects = [
            _wiki_chunk("wiki-documents-local/main/docs/6-neoeyes-ne503-series/a.md", "ne503", "u1"),
        ]
        client = _client(objects)
        report = apply_migration(
            client, class_name="Document", source_ids=["wiki-documents-local"], taxonomy=TAX
        )
        assert client.collection.data.updates == []  # 已是 canonical → 零写入
        assert report.total_changed == 0
