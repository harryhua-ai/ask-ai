"""向量一致性校验单元测试(纯 mock,无真实 DB / Weaviate)。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.vector_consistency import verify_source_vectors


def _make_session_factory(*, scalar=None, rows=None) -> MagicMock:
    """构造 mock 异步 session 工厂。

    ``async with factory() as session:`` → session 为 MagicMock;
    ``await session.execute(...)`` → AsyncMock 返回配置的 scalar/all。
    注意 factory 本身必须是 **MagicMock**(同步调用返回 context manager),
    AsyncMock 的调用返回 coroutine 会破坏 ``async with`` 协议。
    """
    session = MagicMock()
    exec_result = MagicMock()
    if scalar is not None:
        exec_result.scalar.return_value = scalar
    if rows is not None:
        exec_result.all.return_value = rows
    session.execute = AsyncMock(return_value=exec_result)
    session.commit = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = session
    return factory


def _make_pipeline(*, actual_chunks: int, wv_source_ids: set[str]) -> MagicMock:
    """构造 mock IngestionPipeline,返回指定 Weaviate 侧计数与 source_id 集合。"""
    collection = MagicMock()
    collection.aggregate.over_all.return_value.total_count = actual_chunks
    # 精确级:iterator 迭代产出对象(.properties 属性访问,对齐 weaviate v4 真实 API)
    collection.iterator.return_value = [
        MagicMock(properties={"source_id": sid}) for sid in wv_source_ids
    ]
    client = MagicMock()
    client.collections.get.return_value = collection
    pipeline = MagicMock()
    pipeline._client = client
    pipeline._class_name = "Document"
    return pipeline


@pytest.mark.asyncio
async def test_verify_healthy_when_counts_match():
    """汇总级相等 → is_healthy=True,不深入精确级(iterator 不被调用)。"""
    # Postgres SUM(chunk_count) == Weaviate total == 10
    session_factory = _make_session_factory(scalar=10)
    pipeline = _make_pipeline(actual_chunks=10, wv_source_ids=set())

    report = await verify_source_vectors(session_factory, pipeline, "wiki-documents-local")

    assert report.is_healthy is True
    assert report.missing_source_ids == []
    # 精确级不触发:iterator 未调用
    assert pipeline._client.collections.get.return_value.iterator.called is False


@pytest.mark.asyncio
async def test_verify_detects_missing_source_ids_when_counts_differ():
    """汇总级不等 → 深入精确级,差集出 pg 有、Weaviate 无的 source_id。"""
    # Postgres:3 篇文档 SUM=6;Weaviate 实际 3(缺 doc-a 全部 3 chunks)
    pg_rows = [("doc-a",), ("doc-b",), ("doc-c",)]
    session_factory = _make_session_factory(scalar=6, rows=pg_rows)
    # Weaviate 只有 doc-b / doc-c
    pipeline = _make_pipeline(actual_chunks=3, wv_source_ids={"doc-b", "doc-c"})

    report = await verify_source_vectors(session_factory, pipeline, "src")

    assert report.is_healthy is False
    # missing = pg 有而 Weaviate 无的 doc(source_id 完全缺失)
    assert report.missing_source_ids == ["doc-a"]
    # 孤儿(Weaviate 有、pg 无)为 0
    assert report.orphan_count == 0
