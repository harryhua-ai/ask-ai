"""P1-A 持久真理投影重建门测试(真实 Postgres + 真实 Weaviate)。

Gate P1-A(契约):向量索引是**派生投影**——整集合清空后,必须能仅凭
Postgres 持久真值(document_versions + document_version_chunks)完整重建
服务投影,且与真值结构等价(逐 (source_id, chunk_index, text) 一致;
向量由存储文本再生,非比特相等)。绝不以 Weaviate 残存对象为内容来源。
"""

import os
from types import SimpleNamespace

import pytest
import weaviate
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.connectors.base import RawDocument
from backend.db.models import Base, DocumentVersion, DocumentVersionChunk
from backend.pipeline.generation_builder import GenerationBuilder
from backend.pipeline.ingest import IngestionPipeline
from backend.services import document_lifecycle as lifecycle

TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test",
).replace("+asyncpg", "+psycopg2")
WEAVIATE_PORT = int(os.environ.get("P1_WEAVIATE_PORT", "8080"))
CLASS_NAME = "P1ProjProbe"
SRC = "p1proj-probe-src"
PREFIX = "p1proj-probe/"


class _FakeEmbedder:
    def __init__(self):
        self.texts: list[str] = []

    def embed(self, texts):
        self.texts.extend(texts)
        return [[0.2] * 8 for _ in texts]


def _doc(sid: str, paras: int, content_hash: str) -> RawDocument:
    content = "\n\n".join(
        f"paragraph {i} about topic {i} with enough words to chunk properly." for i in range(paras)
    )
    return RawDocument(
        source_id=PREFIX + sid,
        source_type="github",
        product="probe",
        title=sid,
        content=content,
        url=f"https://x/{sid}",
        metadata={},
        content_hash=content_hash,
    )


@pytest.fixture()
def stack():
    # v4 client 连接失败是 raise 而非返回 None;CI/本地无 Weaviate → 跳过集成门
    try:
        client = weaviate.connect_to_local("localhost", WEAVIATE_PORT)
    except Exception:  # noqa: BLE001 - 不可达即跳过(与其他真 Weaviate 集成套件同模式)
        pytest.skip(f"local Weaviate 不可达(port={WEAVIATE_PORT})")
    sync_engine = create_engine(TEST_DSN)
    Base.metadata.create_all(sync_engine)
    sync_factory = sessionmaker(sync_engine, expire_on_commit=False)

    with sync_factory() as s:
        _purge(s)
    if client.collections.exists(CLASS_NAME):
        client.collections.delete(CLASS_NAME)

    embedder = _FakeEmbedder()
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
        select(DocumentVersionChunk)
        .where(
            DocumentVersionChunk.version_id.in_(
                select(DocumentVersion.id).where(
                    DocumentVersion.source_id.like(f"{PREFIX}%")
                )
            )
        )
    ).scalars():
        s.delete(row)
    for row in s.execute(
        select(DocumentVersion).where(DocumentVersion.source_id.like(f"{PREFIX}%"))
    ).scalars():
        s.delete(row)
    from backend.db.models import Document, IndexGeneration

    for row in s.execute(
        select(Document).where(Document.source_id.like(f"{PREFIX}%"))
    ).scalars():
        s.delete(row)
    for row in s.execute(
        select(IndexGeneration).where(IndexGeneration.source_id == SRC)
    ).scalars():
        s.delete(row)
    s.commit()


def _pg_truth(sync_factory) -> dict[str, dict[int, str]]:
    """持久真值:{source_id: {chunk_index: text}}(自 document_version_chunks)。"""
    truth: dict[str, dict[int, str]] = {}
    with sync_factory() as s:
        rows = s.execute(
            select(DocumentVersion.source_id, DocumentVersionChunk.chunk_index, DocumentVersionChunk.text)
            .join(DocumentVersionChunk, DocumentVersionChunk.version_id == DocumentVersion.id)
            .where(DocumentVersion.status == "active")
        ).all()
    for sid, idx, text in rows:
        truth.setdefault(sid, {})[idx] = text
    return truth


def _weaviate_projection(pipeline) -> dict[str, dict[int, str]]:
    out: dict[str, dict[int, str]] = {}
    for item in pipeline._collection.iterator(return_properties=["source_id", "chunk_index", "text"]):
        p = item.properties
        out.setdefault(p["source_id"], {})[int(p["chunk_index"])] = p["text"]
    return out


def test_projection_wipe_and_rebuild_from_persisted_truth_only(stack):
    """整集合清空 → repair_documents 全量重建 → 结构等价 + 版本身份不变。"""
    builder = stack.builder
    docs = [
        _doc("doc-a", paras=4, content_hash="ha"),
        _doc("doc-b", paras=6, content_hash="hb"),
        _doc("doc-c", paras=2, content_hash="hc"),
    ]
    accounting = builder.build_generation(docs, source_id=SRC)
    assert accounting.new_docs and len(accounting.new_docs) == 3

    truth_before = _pg_truth(stack.sync_factory)
    assert set(truth_before) == {PREFIX + d for d in ("doc-a", "doc-b", "doc-c")}
    projection_before = _weaviate_projection(stack.pipeline)
    assert projection_before == truth_before  # 初始投影 = 真值

    # 灾难模拟:collection 整体删除(P1-A 的极端损坏形态)
    stack.client.collections.delete(CLASS_NAME)
    stack.pipeline._collection = None
    stack.pipeline._ensure_collection()
    assert _weaviate_projection(stack.pipeline) == {}

    # 仅凭 PG 真值重建(repair 零源抓取;签名无 connector)
    sids = sorted(truth_before)
    stack.embedder.texts.clear()
    repaired, unrepairable, chunks = builder.repair_documents(sids, source_id_scope=SRC)

    assert repaired == sids
    assert unrepairable == []
    assert chunks == sum(len(v) for v in truth_before.values())
    # 结构等价:重建投影与持久真值逐 chunk 一致(非比特向量,结构等价)
    assert _weaviate_projection(stack.pipeline) == truth_before
    # 重建 embed 仅由存储文本驱动
    assert sorted(stack.embedder.texts) == sorted(
        t for per_doc in truth_before.values() for t in per_doc.values()
    )
    # 版本身份不变(修复不产生新版本;代归属已切换到新代)
    with stack.sync_factory() as s:
        versions = s.execute(
            select(DocumentVersion).where(DocumentVersion.status == "active")
        ).scalars().all()
        serving = lifecycle.active_generation_ordinals_sync(s)
    assert {v.source_id for v in versions} == set(truth_before)
    assert serving and all(isinstance(o, int) for o in serving)


def test_repair_unrepairable_reports_migration_gap_without_source(stack):
    """无持久副本(迁移缺口)的文档 → unrepairable 如实上报,不假装修复。"""
    builder = stack.builder
    builder.build_generation([_doc("doc-x", paras=4, content_hash="hx")], source_id=SRC)
    # 摧毁持久副本(极端账本损伤)→ 只能如实上报 unrepairable
    with stack.sync_factory() as s:
        rows = s.execute(
            select(DocumentVersionChunk)
            .join(DocumentVersion, DocumentVersion.id == DocumentVersionChunk.version_id)
            .where(DocumentVersion.source_id == PREFIX + "doc-x")
        ).scalars().all()
        for r in rows:
            s.delete(r)
        s.commit()

    repaired, unrepairable, chunks = builder.repair_documents(
        [PREFIX + "doc-x"], source_id_scope=SRC
    )
    assert repaired == []
    assert unrepairable == [PREFIX + "doc-x"]
    assert chunks == 0
