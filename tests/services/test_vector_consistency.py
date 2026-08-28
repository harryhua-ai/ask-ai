"""向量一致性校验单元测试(纯 mock,无真实 DB / Weaviate)。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services import vector_consistency
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


def _make_pipeline(
    *, actual_chunks: int, wv_chunks: dict[str, set[int]] | None = None
) -> MagicMock:
    """构造 mock IngestionPipeline,返回指定 Weaviate 侧计数与 chunk 分布。

    ``wv_chunks``:source_id → 该 doc 在 Weaviate 实际存在的 chunk_index 集合;
    iterator 迭代产出带 ``(source_id, chunk_index)`` 两属性的对象
    (对齐 weaviate v4 真实 API)。
    """
    collection = MagicMock()
    collection.aggregate.over_all.return_value.total_count = actual_chunks
    # iterator mock(v4 iterator 不支持 filters,实现靠客户端前缀过滤)
    collection.iterator.return_value = [
        MagicMock(properties={"source_id": sid, "chunk_index": idx})
        for sid, idxs in sorted((wv_chunks or {}).items())
        for idx in sorted(idxs)
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
    pipeline = _make_pipeline(actual_chunks=10)

    report = await verify_source_vectors(session_factory, pipeline, "wiki-documents-local")

    assert report.is_healthy is True
    assert report.missing_source_ids == []
    assert report.refill_source_ids == []
    assert report.stale_chunk_count == 0
    # 精确级不触发:fetch_objects 未调用
    assert pipeline._client.collections.get.return_value.query.fetch_objects.called is False


@pytest.mark.asyncio
async def test_verify_detects_missing_source_ids_when_counts_differ():
    """汇总级不等 → 深入精确级,差集出 pg 有、Weaviate 无(整篇缺失)的 source_id。"""
    # Postgres:3 篇文档 SUM=6;Weaviate 实际 3(缺 doc-a 全部 3 chunks)
    pg_rows = [("src/doc-a", 3), ("src/doc-b", 2), ("src/doc-c", 1)]
    session_factory = _make_session_factory(scalar=6, rows=pg_rows)
    # Weaviate 只有 doc-b(2 chunks)/ doc-c(1 chunk)
    pipeline = _make_pipeline(actual_chunks=3, wv_chunks={"src/doc-b": {0, 1}, "src/doc-c": {0}})

    report = await verify_source_vectors(session_factory, pipeline, "src")

    assert report.is_healthy is False
    # missing = pg 有而 Weaviate 无的 doc(source_id 完全缺失)
    assert report.missing_source_ids == ["src/doc-a"]
    # 整篇缺失的 doc 需重灌
    assert report.refill_source_ids == ["src/doc-a"]
    # 孤儿(Weaviate 有、pg 无)为 0;整篇缺失不产生多余 chunk
    assert report.orphan_count == 0
    assert report.stale_chunk_count == 0


@pytest.mark.asyncio
async def test_verify_detects_partial_chunk_loss():
    """部分 chunk 丢失:doc 在 Weaviate 但 index 集合 {0,1} 而 pg chunk_count=4。

    该 doc 需整篇重灌;丢失不算"多余",stale_chunk_count 仍为 0
    (仅统计实际 index 超出 0..chunk_count-1 的部分)。
    """
    pg_rows = [("src/doc-x", 4)]
    session_factory = _make_session_factory(scalar=4, rows=pg_rows)
    pipeline = _make_pipeline(actual_chunks=2, wv_chunks={"src/doc-x": {0, 1}})

    report = await verify_source_vectors(session_factory, pipeline, "src")

    assert report.is_healthy is False
    assert report.missing_source_ids == []  # doc 在 Weaviate,不算整篇缺失
    assert report.refill_source_ids == ["src/doc-x"]
    assert report.stale_chunk_count == 0
    assert report.orphan_count == 0


@pytest.mark.asyncio
async def test_verify_detects_extra_chunks():
    """chunk 多余:Weaviate 有 index 0,1,2,3 而 pg chunk_count=2。

    该 doc 需整篇重灌;多余 2 个 chunk 计入 stale_chunk_count(仅统计,不删除)。
    """
    pg_rows = [("src/doc-y", 2)]
    session_factory = _make_session_factory(scalar=2, rows=pg_rows)
    pipeline = _make_pipeline(actual_chunks=4, wv_chunks={"src/doc-y": {0, 1, 2, 3}})

    report = await verify_source_vectors(session_factory, pipeline, "src")

    assert report.is_healthy is False
    assert report.missing_source_ids == []
    assert report.refill_source_ids == ["src/doc-y"]
    assert report.stale_chunk_count == 2
    assert report.orphan_count == 0


@pytest.mark.asyncio
async def test_refill_unions_missing_and_chunk_mismatch_sorted():
    """refill_source_ids = 整篇缺失 ∪ chunk 集合不一致,排序稳定输出。"""
    # src/doc-a 整篇缺失;src/doc-b 多余 1 chunk;src/doc-c 完全一致
    pg_rows = [("src/doc-a", 3), ("src/doc-b", 2), ("src/doc-c", 1)]
    session_factory = _make_session_factory(scalar=6, rows=pg_rows)
    pipeline = _make_pipeline(actual_chunks=3, wv_chunks={"src/doc-b": {0, 1, 2}, "src/doc-c": {0}})

    report = await verify_source_vectors(session_factory, pipeline, "src")

    assert report.is_healthy is False
    assert report.missing_source_ids == ["src/doc-a"]  # 仅整篇缺失
    assert report.refill_source_ids == ["src/doc-a", "src/doc-b"]  # 并集,排序稳定
    assert report.stale_chunk_count == 1  # src/doc-b 的多余 index 2
    assert report.orphan_count == 0


@pytest.mark.asyncio
async def test_orphan_count_only_within_source_prefix(monkeypatch):
    """孤儿计数限本源前缀:iterator 全表遍历后客户端按前缀过滤,跨源孤儿不计数。"""
    # 伪造 Filter:aggregate 的 like(pattern) 记录调用,断言服务端过滤仍在本源
    fake_filter = MagicMock(name="FakeFilter")
    like_patterns: list[str] = []

    def _like(pattern):
        like_patterns.append(pattern)
        return ("like", pattern)

    fake_filter.by_property.return_value.like.side_effect = _like
    monkeypatch.setattr(vector_consistency, "Filter", fake_filter)

    # Weaviate 全库数据:本源 1 正常 + 本源 1 孤儿 + 跨源 1 孤儿
    all_items = [
        MagicMock(properties={"source_id": "src/doc-1", "chunk_index": 0}),
        MagicMock(properties={"source_id": "src/ghost", "chunk_index": 5}),
        MagicMock(properties={"source_id": "other-source/orphan", "chunk_index": 0}),
    ]

    collection = MagicMock()
    collection.aggregate.over_all.return_value.total_count = 3
    collection.iterator.return_value = list(all_items)

    client = MagicMock()
    client.collections.get.return_value = collection
    pipeline = MagicMock()
    pipeline._client = client
    pipeline._class_name = "Document"

    # Postgres SUM=1(仅 src/doc-1);Weaviate 全库 total=3 → 汇总级不等,触发精确级
    session_factory = _make_session_factory(scalar=1, rows=[("src/doc-1", 1)])

    report = await verify_source_vectors(session_factory, pipeline, "src")

    assert report.is_healthy is False
    # 只统计本源前缀内的孤儿(src/ghost);跨源 other-source/orphan 不算
    assert report.orphan_count == 1
    # aggregate 服务端过滤仍为本源前缀
    assert set(like_patterns) == {"src/*"}
    # iterator 取 (source_id, chunk_index) 两属性
    assert collection.iterator.call_args.kwargs["return_properties"] == [
        "source_id",
        "chunk_index",
    ]
