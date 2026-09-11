"""GenerationBuilder 门测试(真实 Postgres + 真实 Weaviate;不可达时 skip)。

契约锚点(docs/engineering/tasks/tb-p1-lifecycle-foundation-plan.md):
- P1-B 生成物理表示:content 变更 → 新代 + 生成命名空间确定性 UUID
  (uuid5(source_id#generation#index));旧代对象原位不动(失败隔离);
- P1-C 失败安全:任一文档失败 → IngestFailures + 零激活 + 在服代分毫不动;
  失败代 GC 即时资格;已写对象本文档局部清理(P0-A);
- P1-D 原子激活:Current Truth 恰一次切换;前任 superseded 留痕;服务集
  即时换代(撤出 ≤1 天的强形态:激活提交即撤出);
- FC-5:metadata-only 零重嵌、零版本分叉;UNCHANGED 零 embed;
- --reindex(force_rebuild):对 UNCHANGED 文档仍强制新代重建(非原位覆写);
- 真值修复:repair_documents 从 PG 持久 chunk 副本重建对象(零源抓取)。
"""

import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import weaviate
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.connectors.base import RawDocument
from backend.db.models import (
    Base,
    Document,
    DocumentVersion,
    DocumentVersionChunk,
    IndexGeneration,
)
from backend.pipeline.generation_builder import GenerationBuilder
from backend.pipeline.ingest import (
    IngestFailures,
    generation_chunk_uuids,
    legacy_chunk_uuids,
)
from backend.services import document_lifecycle as lifecycle

TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test",
)
# 默认打本机主 Weaviate(生产同构 compose);P1_WEAVIATE_PORT 可覆盖。
# 注:21100(p1b)容器上 insert_many 对象对 REST PATCH 不可见(容器特有
# 状态),metadata-only 自愈语义须在 production-equivalent 实例上验证。
WEAVIATE_PORT = int(os.environ.get("P1_WEAVIATE_PORT", "8080"))
CLASS_NAME = "P1GenProbe"
SRC = "p1gb-probe-src"
PREFIX = "p1gb-probe/"


class _FakeEmbedder:
    """确定性假嵌入器:记录调用;可注入失败(Phase 2 整代失败路径)。"""

    dimension = 8

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.fail = False

    def embed(self, texts):
        if self.fail:
            raise RuntimeError("fake embedder boom")
        self.calls.append(list(texts))
        return [[0.1] * self.dimension for _ in texts]


def _doc(sid: str, *, content: str, content_hash: str, title: str = "probe-title") -> RawDocument:
    return RawDocument(
        source_id=PREFIX + sid,
        source_type="github",
        product="probe",
        title=title,
        content=content,
        url=f"https://x/{PREFIX}{sid}",
        metadata={"commit_sha": "abc123"},
        content_hash=content_hash,
    )


TWO_PARAS = (
    "alpha paragraph about connectors and sync.\n\n"
    "beta paragraph about retrieval and ranking.\n\n"
    "gamma paragraph about lifecycle and generations.\n\n"
    "delta paragraph about activation and versions."
)


def _fetch_count(collection, uuids: list[str]) -> int:
    from weaviate.classes.query import Filter

    found = 0
    for start in range(0, len(uuids), 500):
        resp = collection.query.fetch_objects(
            filters=Filter.by_id().contains_any(uuids[start : start + 500]),
            limit=len(uuids[start : start + 500]),
        )
        found += len(resp.objects)
    return found


@pytest.fixture()
def stack():
    # v4 client 连接失败是 raise 而非返回 None;CI/本地无 Weaviate → 跳过集成门
    try:
        client = weaviate.connect_to_local("localhost", WEAVIATE_PORT)
    except Exception:  # noqa: BLE001 - 不可达即跳过(与其他真 Weaviate 集成套件同模式)
        pytest.skip(f"local Weaviate 不可达(port={WEAVIATE_PORT})")
    sync_engine = create_engine(TEST_DSN.replace("+asyncpg", "+psycopg2"))
    Base.metadata.create_all(sync_engine)
    sync_factory = sessionmaker(sync_engine, expire_on_commit=False)

    with sync_factory() as s:
        _purge(s)
    if client.collections.exists(CLASS_NAME):
        client.collections.delete(CLASS_NAME)

    embedder = _FakeEmbedder()
    from backend.pipeline.ingest import IngestionPipeline

    pipeline = IngestionPipeline(
        embedder,
        client,
        class_name=CLASS_NAME,
        max_tokens=40,
        overlap=0,
        session_factory=sync_factory,
        max_chunk_chars=2000,
    )
    builder = GenerationBuilder(pipeline, sync_factory)

    yield SimpleNamespace(
        client=client,
        sync_factory=sync_factory,
        pipeline=pipeline,
        builder=builder,
        embedder=embedder,
    )

    with sync_factory() as s:
        _purge(s)
    if client.collections.exists(CLASS_NAME):
        client.collections.delete(CLASS_NAME)
    client.close()
    sync_engine.dispose()


def _purge(s) -> None:
    for row in s.execute(
        select(Document).where(Document.source_id.like(f"{PREFIX}%"))
    ).scalars():
        s.delete(row)
    for row in s.execute(
        select(DocumentVersion).where(DocumentVersion.source_id.like(f"{PREFIX}%"))
    ).scalars():
        s.delete(row)
    for row in s.execute(
        select(IndexGeneration).where(IndexGeneration.source_id == SRC)
    ).scalars():
        s.delete(row)
    s.commit()


def _current_version(sf, sid: str) -> tuple[Document, DocumentVersion]:
    with sf() as s:
        doc, ver = lifecycle.load_document_and_current_version(s, PREFIX + sid)
        assert doc is not None and ver is not None
        s.expunge(doc)
        s.expunge(ver)
    return doc, ver


# --------------------------------------------------------------------------- #
# P1-B:首灌 = 新代 + 生成命名空间对象 + 持久副本
# --------------------------------------------------------------------------- #


def test_first_build_creates_generation_version_and_namespace_objects(stack):
    builder = stack.builder
    accounting = builder.build_generation([_doc("d1", content=TWO_PARAS, content_hash="v1")], source_id=SRC)

    sid = PREFIX + "d1"
    assert accounting.new_docs == [sid]
    assert accounting.generation_status == "ready"

    doc, ver = _current_version(stack.sync_factory, "d1")
    assert doc.current_version_id == ver.id
    assert ver.status == "active"
    assert ver.generation_ordinal == accounting.generation_ordinal
    assert ver.chunk_count == accounting.chunks_written

    with stack.sync_factory() as s:
        chunks = s.execute(
            select(DocumentVersionChunk)
            .where(DocumentVersionChunk.version_id == ver.id)
            .order_by(DocumentVersionChunk.chunk_index)
        ).scalars().all()
    assert len(chunks) == ver.chunk_count  # I-1:持久内容副本落库

    collection = stack.pipeline._collection
    gen_uuids = generation_chunk_uuids(sid, str(ver.generation_id), ver.chunk_count)
    assert _fetch_count(collection, gen_uuids) == ver.chunk_count
    # 生成命名空间:legacy 寻址(uuid5(sid#i))不得出现(P1-B 红线)
    assert _fetch_count(collection, legacy_chunk_uuids(sid, ver.chunk_count)) == 0
    # 对象携带 generation 属性(INT 精确过滤的物理基础)
    from weaviate.classes.query import Filter

    resp = collection.query.fetch_objects(
        filters=Filter.by_id().contains_any(gen_uuids[:1]), limit=1
    )
    assert resp.objects[0].properties["generation_ordinal"] == ver.generation_ordinal


# --------------------------------------------------------------------------- #
# P1-D:content 变更 = 新版本激活 + 前任 superseded + 前任代退休(§8a)
# --------------------------------------------------------------------------- #


def test_content_change_activates_new_version_and_switches_serving_once(stack):
    builder = stack.builder
    builder.build_generation([_doc("d2", content=TWO_PARAS, content_hash="v1")], source_id=SRC)
    _doc1, v1 = _current_version(stack.sync_factory, "d2")
    old_gen_id = str(v1.generation_id)
    old_uuids = generation_chunk_uuids(PREFIX + "d2", old_gen_id, v1.chunk_count)

    accounting = builder.build_generation(
        [_doc("d2", content=TWO_PARAS + " extra tail.", content_hash="v2")], source_id=SRC
    )
    assert accounting.updated_docs == [PREFIX + "d2"]

    doc2, v2 = _current_version(stack.sync_factory, "d2")
    assert doc2.current_version_id == v2.id
    assert v2.id != v1.id and v2.version_seq == v1.version_seq + 1
    # Current Truth 恰一个
    with stack.sync_factory() as s:
        actives = s.execute(
            select(DocumentVersion).where(
                DocumentVersion.source_id == PREFIX + "d2",
                DocumentVersion.status == "active",
            )
        ).scalars().all()
        v1_row = s.execute(
            select(DocumentVersion).where(DocumentVersion.id == v1.id)
        ).scalar_one()
        gen1_row = s.execute(
            select(IndexGeneration).where(IndexGeneration.id == v1.generation_id)
        ).scalar_one()
        serving = lifecycle.active_generation_ordinals_sync(s)
    assert [v.id for v in actives] == [v2.id]
    # 前任 superseded 留痕(FC-6 接替动词)
    assert v1_row.status == "superseded"
    assert v1_row.valid_to is not None
    assert v1_row.superseded_by_version_id == v2.id
    # 前任代:撤出完成 → RETIRED,+7 天 GC 资格(§8a)
    assert gen1_row.status == "retired"
    assert gen1_row.withdrawn_at is not None
    assert gen1_row.gc_eligible_at >= (
        datetime.now(UTC).replace(tzinfo=UTC) + timedelta(days=7) - timedelta(minutes=5)
    )
    # 服务集即时换代(激活提交 = 撤出,≤1 天上限的强形态)
    assert serving == [v2.generation_ordinal]
    # 旧代对象原位保留(失败隔离 / 非破坏重建;物理清除仅经 GC)
    assert _fetch_count(stack.pipeline._collection, old_uuids) == v1.chunk_count


# --------------------------------------------------------------------------- #
# FC-5:UNCHANGED / metadata-only
# --------------------------------------------------------------------------- #


def test_unchanged_doc_skips_embed_and_generation(stack):
    builder = stack.builder
    builder.build_generation([_doc("d3", content=TWO_PARAS, content_hash="v1")], source_id=SRC)
    _, v1 = _current_version(stack.sync_factory, "d3")
    stack.embedder.calls.clear()
    with stack.sync_factory() as s:
        gens_before = len(
            s.execute(select(IndexGeneration)).scalars().all()
        )

    accounting = builder.build_generation(
        [_doc("d3", content=TWO_PARAS, content_hash="v1")], source_id=SRC
    )
    assert accounting.unchanged_docs == [PREFIX + "d3"]
    assert stack.embedder.calls == []  # 零 embed
    _, v2 = _current_version(stack.sync_factory, "d3")
    assert v2.id == v1.id  # 无版本分叉
    with stack.sync_factory() as s:
        assert len(s.execute(select(IndexGeneration)).scalars().all()) == gens_before


def test_metadata_only_updates_props_without_reembed_or_fork(stack):
    builder = stack.builder
    builder.build_generation([_doc("d4", content=TWO_PARAS, content_hash="v1")], source_id=SRC)
    _, v1 = _current_version(stack.sync_factory, "d4")
    stack.embedder.calls.clear()

    accounting = builder.build_generation(
        [_doc("d4", content=TWO_PARAS, content_hash="v1", title="new-title-✦")],
        source_id=SRC,
    )
    assert accounting.metadata_docs == [PREFIX + "d4"]
    assert stack.embedder.calls == []  # 零重嵌
    _, v2 = _current_version(stack.sync_factory, "d4")
    assert v2.id == v1.id  # 零版本分叉
    assert v2.title == "new-title-✦"
    assert v2.metadata_hash != v1.metadata_hash
    # 对象文档级 props 原位更新(向量不动);持久副本 props 同步
    uuids = generation_chunk_uuids(PREFIX + "d4", str(v2.generation_id), v2.chunk_count)
    from weaviate.classes.query import Filter

    resp = stack.pipeline._collection.query.fetch_objects(
        filters=Filter.by_id().contains_any(uuids), limit=len(uuids)
    )
    assert {o.properties["title"] for o in resp.objects} == {"new-title-✦"}
    with stack.sync_factory() as s:
        chunks = s.execute(
            select(DocumentVersionChunk).where(DocumentVersionChunk.version_id == v2.id)
        ).scalars().all()
    assert all(c.props["title"] == "new-title-✦" for c in chunks)


# --------------------------------------------------------------------------- #
# P1-C:失败隔离(整代失败 = 零激活 + 在服代不动 + 失败代即时 GC 资格)
# --------------------------------------------------------------------------- #


def test_embed_failure_means_zero_activation_and_serving_unchanged(stack):
    builder = stack.builder
    builder.build_generation([_doc("d5", content=TWO_PARAS, content_hash="v1")], source_id=SRC)
    _, v1 = _current_version(stack.sync_factory, "d5")
    old_uuids = generation_chunk_uuids(PREFIX + "d5", str(v1.generation_id), v1.chunk_count)

    stack.embedder.fail = True
    with pytest.raises(IngestFailures):
        builder.build_generation(
            [_doc("d5", content="totally different", content_hash="v2")], source_id=SRC
        )

    _doc_row_d5, ver = _current_version(stack.sync_factory, "d5")
    assert ver.id == v1.id  # 零激活:Current Truth 未变
    with stack.sync_factory() as s:
        versions = s.execute(
            select(DocumentVersion).where(
                DocumentVersion.source_id == PREFIX + "d5"
            )
        ).scalars().all()
        assert len(versions) == 1
        # 失败代证据 + 即时 GC 资格
        failed_gens = s.execute(
            select(IndexGeneration).where(
                IndexGeneration.status == "failed",
                IndexGeneration.source_id == SRC,
            )
        ).scalars().all()
        # 在服代未被失败波及:服务集仍 = 旧代
        assert lifecycle.active_generation_ordinals_sync(s) == [v1.generation_ordinal]
    assert len(failed_gens) == 1
    assert failed_gens[0].failure and "embed" in str(failed_gens[0].failure)
    assert failed_gens[0].gc_eligible_at is not None
    # 在服代对象分毫不动;失败代新命名空间对象已清理(不入服务集)
    assert _fetch_count(stack.pipeline._collection, old_uuids) == v1.chunk_count
    new_uuids = generation_chunk_uuids(
        PREFIX + "d5", str(failed_gens[0].id), ver.chunk_count
    )
    assert _fetch_count(stack.pipeline._collection, new_uuids) == 0


def test_validation_failure_zero_activation(stack, monkeypatch):
    builder = stack.builder
    builder.build_generation([_doc("d6", content=TWO_PARAS, content_hash="v1")], source_id=SRC)
    _, v1 = _current_version(stack.sync_factory, "d6")

    def _invalid(collection, gen_id, written):
        return {PREFIX + "d6": (written[PREFIX + "d6"].__len__(), 0)}

    monkeypatch.setattr(builder, "_validate_written", _invalid)
    with pytest.raises(IngestFailures):
        builder.build_generation(
            [_doc("d6", content="changed content", content_hash="v2")], source_id=SRC
        )
    _, ver = _current_version(stack.sync_factory, "d6")
    assert ver.id == v1.id  # 验证先于激活(I-5):零激活


# --------------------------------------------------------------------------- #
# --reindex 语义:force_rebuild 对 UNCHANGED 文档仍强制新代重建
# --------------------------------------------------------------------------- #


def test_force_rebuild_creates_new_generation_not_inplace_overwrite(stack):
    builder = stack.builder
    builder.build_generation([_doc("d7", content=TWO_PARAS, content_hash="v1")], source_id=SRC)
    _, v1 = _current_version(stack.sync_factory, "d7")
    old_uuids = generation_chunk_uuids(PREFIX + "d7", str(v1.generation_id), v1.chunk_count)

    accounting = builder.build_generation(
        [_doc("d7", content=TWO_PARAS, content_hash="v1")], source_id=SRC, force_rebuild=True
    )
    assert accounting.updated_docs == [PREFIX + "d7"]
    _, v2 = _current_version(stack.sync_factory, "d7")
    assert v2.id != v1.id and v2.generation_ordinal > v1.generation_ordinal
    # 新代对象已写;旧代对象原位保留(重建 ≠ 原位覆写)
    new_uuids = generation_chunk_uuids(PREFIX + "d7", str(v2.generation_id), v2.chunk_count)
    assert _fetch_count(stack.pipeline._collection, new_uuids) == v2.chunk_count
    assert _fetch_count(stack.pipeline._collection, old_uuids) == v1.chunk_count
    with stack.sync_factory() as s:
        assert lifecycle.active_generation_ordinals_sync(s) == [v2.generation_ordinal]


# --------------------------------------------------------------------------- #
# 真值修复(P1-A 投影重建共用原语)
# --------------------------------------------------------------------------- #


def test_repair_documents_rebuilds_from_persisted_truth(stack):
    builder = stack.builder
    sid_full = PREFIX + "d8"
    builder.build_generation([_doc("d8", content=TWO_PARAS, content_hash="v1")], source_id=SRC)
    _, v1 = _current_version(stack.sync_factory, "d8")

    # 模拟投影损坏:按本文档自身确定性 UUID 清除全部对象
    old_uuids = generation_chunk_uuids(sid_full, str(v1.generation_id), v1.chunk_count)
    from weaviate.classes.query import Filter

    stack.pipeline._collection.data.delete_many(
        where=Filter.by_id().contains_any(old_uuids)
    )
    assert _fetch_count(stack.pipeline._collection, old_uuids) == 0

    stack.embedder.calls.clear()
    repaired, unrepairable, chunks_repaired = builder.repair_documents(
        [sid_full], source_id_scope=SRC
    )
    assert repaired == [sid_full]
    assert unrepairable == []
    assert chunks_repaired == v1.chunk_count

    # 版本身份不变(修复 ≠ 新版本),代归属原子切换
    _, v2 = _current_version(stack.sync_factory, "d8")
    assert v2.id == v1.id
    assert v2.generation_id != v1.generation_id
    # 对象已按新代命名空间重物化;结构 = PG 持久真值(逐 chunk 文本一致)
    new_uuids = generation_chunk_uuids(sid_full, str(v2.generation_id), v2.chunk_count)
    resp = stack.pipeline._collection.query.fetch_objects(
        filters=Filter.by_id().contains_any(new_uuids), limit=len(new_uuids)
    )
    by_index = {o.properties["chunk_index"]: o.properties for o in resp.objects}
    assert len(by_index) == v2.chunk_count
    with stack.sync_factory() as s:
        persisted = s.execute(
            select(DocumentVersionChunk)
            .where(DocumentVersionChunk.version_id == v2.id)
            .order_by(DocumentVersionChunk.chunk_index)
        ).scalars().all()
    for c in persisted:
        assert by_index[c.chunk_index]["text"] == c.text
    # 零源抓取(签名无 connector);embed 仅由存储文本再生
    flat = [t for call in stack.embedder.calls for t in call]
    assert flat == [c.text for c in persisted]
