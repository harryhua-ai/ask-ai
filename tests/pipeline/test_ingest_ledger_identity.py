"""Ingest 账本身份语义测试(Issue #13 Stage A,D1/D2)。

覆盖:_upsert_postgres 按 source_id 路径 upsert —— 同内容不同路径各自成行、
禁止行归属抢占、重复灌入幂等、内容变更原位演进;delete_document 删除某路径
不影响同内容兄弟路径(E)。全程零 embed(仅账本路径),不依赖 CUDA。
"""

import hashlib

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from backend.connectors.base import RawDocument
from backend.db.models import Document
from backend.pipeline.ingest import IngestionPipeline, _deterministic_uuid

pytestmark = pytest.mark.asyncio


def _doc(path: str, content: str, branch: str = "main") -> RawDocument:
    return RawDocument(
        source_id=path,
        source_type="github",
        product="p",
        title=path.rsplit("/", 1)[-1],
        content=content,
        url=f"https://example.com/{path}",
        metadata={"path": path},
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        branch=branch,
    )


@pytest.fixture
def sync_factory(db_engine):
    """与 db_engine 同库的同步 sessionmaker(_upsert_postgres 为同步路径)。"""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import os

    engine = create_engine(os.environ["TEST_DATABASE_URL"].replace("+asyncpg", ""))
    try:
        yield sessionmaker(bind=engine)
    finally:
        engine.dispose()


def _pipeline(sync_factory) -> IngestionPipeline:
    return IngestionPipeline(
        embedder=None,  # 本测试不触发 embed(仅账本 upsert/delete 路径)
        weaviate_client=None,
        session_factory=sync_factory,
    )


async def _paths(async_engine, content_hash: str | None = None) -> set[str]:
    factory = async_sessionmaker(async_engine)
    async with factory() as session:
        stmt = select(Document.source_id)
        if content_hash is not None:
            stmt = stmt.where(Document.content_hash == content_hash)
        rows = (await session.execute(stmt)).scalars().all()
    return set(rows)


class _FakeByIdFilter:
    """monkeypatch 替身:捕获 contains_any 收到的 uuid(版本无关)。"""

    def __init__(self, sink: list[str]) -> None:
        self._sink = sink

    def by_id(self):  # Filter.by_id()
        return self

    def contains_any(self, ids):
        self._sink.extend(ids)
        return f"contains_any({len(ids)})"


async def test_c_repeat_ingest_same_doc_idempotent(db_engine, sync_factory):
    """C:同一文档重复灌入 → 幂等,单行原地更新。"""
    pipeline = _pipeline(sync_factory)
    doc = _doc("src/main/a.md", "hello")
    pipeline._upsert_postgres(doc, chunk_count=3)
    pipeline._upsert_postgres(doc, chunk_count=5)

    assert await _paths(db_engine, content_hash=doc.content_hash) == {"src/main/a.md"}
    factory = async_sessionmaker(db_engine)
    async with factory() as session:
        row = (
            await session.execute(select(Document).where(Document.source_id == "src/main/a.md"))
        ).scalar_one()
    assert row.chunk_count == 5


async def test_a_pipeline_same_hash_diff_path_no_hijack(db_engine, sync_factory):
    """A(管道口径):同内容不同路径先后灌入 → 两行;先到行不被抢占改写。

    旧实现:第二次 upsert 会命中 (content_hash, branch) 已存在行并改写其
    source_id(行归属翻转,Issue #13 根因 RC-1)。
    """
    pipeline = _pipeline(sync_factory)
    doc_a = _doc("src/main/dir_a/util.py", "same content")
    doc_b = _doc("src/main/dir_b/util.py", "same content")
    assert doc_a.content_hash == doc_b.content_hash

    pipeline._upsert_postgres(doc_a, chunk_count=2)
    pipeline._upsert_postgres(doc_b, chunk_count=2)

    assert await _paths(db_engine, content_hash=doc_a.content_hash) == {
        "src/main/dir_a/util.py",
        "src/main/dir_b/util.py",
    }


async def test_b_pipeline_same_hash_cross_source(db_engine, sync_factory):
    """B(管道口径):同内容跨数据源各自成行。"""
    pipeline = _pipeline(sync_factory)
    pipeline._upsert_postgres(_doc("s1/main/x.md", "dup"), chunk_count=1)
    pipeline._upsert_postgres(_doc("s2/main/x.md", "dup"), chunk_count=1)
    pipeline._upsert_postgres(_doc("s2/feat/x.md", "dup", branch="feat"), chunk_count=1)

    dup_hash = _doc("s1/main/x.md", "dup").content_hash
    assert len(await _paths(db_engine, content_hash=dup_hash)) == 3


async def test_content_change_updates_row_in_place(db_engine, sync_factory):
    """内容变更:同路径单行原位演进(新 hash 覆写),无旧行残留。"""
    pipeline = _pipeline(sync_factory)
    pipeline._upsert_postgres(_doc("src/main/a.md", "v1"), chunk_count=2)
    pipeline._upsert_postgres(_doc("src/main/a.md", "v2"), chunk_count=4)

    assert await _paths(db_engine) == {"src/main/a.md"}
    factory = async_sessionmaker(db_engine)
    async with factory() as session:
        row = (
            await session.execute(select(Document).where(Document.source_id == "src/main/a.md"))
        ).scalar_one()
    assert row.content_hash == _doc("src/main/a.md", "v2").content_hash
    assert row.chunk_count == 4


async def test_e_delete_one_path_keeps_same_content_sibling(db_engine, sync_factory, monkeypatch):
    """E:删除文档 = 路径级精确删除;同内容兄弟路径账本行与向量零触碰。"""
    deleted: list[str] = []
    fake_filter = _FakeByIdFilter(deleted)
    monkeypatch.setattr("weaviate.classes.query.Filter", fake_filter)

    pipeline = _pipeline(sync_factory)
    doc_a = _doc("src/main/a.md", "same")
    doc_b = _doc("src/main/b.md", "same")
    pipeline._upsert_postgres(doc_a, chunk_count=3)
    pipeline._upsert_postgres(doc_b, chunk_count=3)

    pipeline._ensure_collection = lambda: None
    from types import SimpleNamespace

    pipeline._collection = SimpleNamespace(
        data=SimpleNamespace(delete_many=lambda where=None, **_kw: None)
    )
    pipeline.delete_document("src/main/a.md")

    # 向量点删范围 = 被删文档自己的 uuid5(sid, 0..chunk_count-1)
    assert sorted(deleted) == sorted(_deterministic_uuid("src/main/a.md", i) for i in range(3))
    # 兄弟路径账本行完好(同内容不同路径互不波及)
    assert await _paths(db_engine, content_hash=doc_a.content_hash) == {"src/main/b.md"}
