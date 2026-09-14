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

    ``rows``:``(source_id, chunk_count, lifecycle, current_generation_ordinal)``
    四元组(INC-WEB-EMBED-413 起校验器按现行版本代过滤在服对象)。
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
    *,
    actual_chunks: int,
    wv_chunks: dict[str, set[int]] | None = None,
    wv_objects: dict[str, list[tuple[int, int | None]]] | None = None,
    wv_default_ordinal: int = 0,
) -> MagicMock:
    """构造 mock IngestionPipeline,返回指定 Weaviate 侧计数与 chunk 分布。

    ``wv_chunks``:source_id → 该 doc 在 Weaviate 实际存在的 chunk_index 集合;
    iterator 迭代产出带 ``(source_id, chunk_index)`` 两属性的对象
    (对齐 weaviate v4 真实 API)。便捷形态:对象统一打 ``wv_default_ordinal``
    (默认 0 = legacy;旧行为世界)。

    ``wv_objects``:source_id → [(chunk_index, generation_ordinal | None)] 精确
    形态(None = 无 generation 属性对象),供混代场景(INT-C-01 口径)。
    """
    collection = MagicMock()
    collection.aggregate.over_all.return_value.total_count = actual_chunks
    items: list = []
    if wv_objects:
        for sid, objs in sorted(wv_objects.items()):
            for idx, ordinal in objs:
                props = {"source_id": sid, "chunk_index": idx}
                if ordinal is not None:
                    props["generation_ordinal"] = ordinal
                items.append(MagicMock(properties=props))
    else:
        for sid, idxs in sorted((wv_chunks or {}).items()):
            for idx in sorted(idxs):
                items.append(
                    MagicMock(
                        properties={
                            "source_id": sid,
                            "chunk_index": idx,
                            "generation_ordinal": wv_default_ordinal,
                        }
                    )
                )
    collection.iterator.return_value = items
    client = MagicMock()
    client.collections.get.return_value = collection
    pipeline = MagicMock()
    pipeline._client = client
    pipeline._class_name = "Document"
    return pipeline


@pytest.mark.asyncio
async def test_summary_level_not_fooled_by_like_token_pollution():
    """neomind 家族 like 前缀污染场景:聚合口径虚高不得影响健康判定(D4-ACC)。

    旧实现:汇总级 total_count 用 TEXT like 计数,`neomind-local/*` 会把
    dashboard/extensions/devicetypes 的对象一并算进来(生产实测聚合 16983
    vs 迭代器 10953),造成永久假 partial。新实现:汇总级与精确级同为
    迭代器口径 → 迭代器一致即健康。
    """
    pg_rows = [("neomind-local/main/a.md", 2, "active", 0), ("neomind-local/main/b.md", 1, "active", 0)]
    session_factory = _make_session_factory(scalar=3, rows=pg_rows)
    # 真实对象仅 3 个(与 pg 一致);聚合口径被污染成 16983(模拟 like 虚高)
    pipeline = _make_pipeline(
        actual_chunks=16983,
        wv_chunks={"neomind-local/main/a.md": {0, 1}, "neomind-local/main/b.md": {0}},
    )

    report = await verify_source_vectors(session_factory, pipeline, "neomind-local")

    assert report.is_healthy is True
    assert report.actual_chunks == 3  # 迭代器口径,非聚合污染值
    assert report.missing_source_ids == []
    assert report.refill_source_ids == []
    assert report.orphan_count == 0


@pytest.mark.asyncio
async def test_verify_healthy_when_counts_match():
    """迭代器口径一致 → is_healthy=True;汇总级不再使用 like 聚合(D4-ACC)。"""
    # Postgres SUM(chunk_count) == Weaviate 迭代器可见 chunks == 10
    pg_rows = [("wiki-documents-local/main/a.md", 3, "active", 0), ("wiki-documents-local/main/b.md", 7, "active", 0)]
    session_factory = _make_session_factory(scalar=10, rows=pg_rows)
    pipeline = _make_pipeline(
        actual_chunks=10,  # 旧聚合口径的 mock 值,新实现不再读取
        wv_chunks={
            "wiki-documents-local/main/a.md": {0, 1, 2},
            "wiki-documents-local/main/b.md": set(range(7)),
        },
    )

    report = await verify_source_vectors(session_factory, pipeline, "wiki-documents-local")

    assert report.is_healthy is True
    assert report.actual_chunks == 10
    assert report.missing_source_ids == []
    assert report.refill_source_ids == []
    assert report.stale_chunk_count == 0
    # 汇总级不再依赖 TEXT like 聚合(D4-ACC 口径统一)
    collection = pipeline._client.collections.get.return_value
    assert collection.aggregate.over_all.called is False


@pytest.mark.asyncio
async def test_verify_detects_missing_source_ids_when_counts_differ():
    """汇总级不等 → 深入精确级,差集出 pg 有、Weaviate 无(整篇缺失)的 source_id。"""
    # Postgres:3 篇文档 SUM=6;Weaviate 实际 3(缺 doc-a 全部 3 chunks)
    pg_rows = [("src/doc-a", 3, "active", 0), ("src/doc-b", 2, "active", 0), ("src/doc-c", 1, "active", 0)]
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
    pg_rows = [("src/doc-x", 4, "active", 0)]
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
    pg_rows = [("src/doc-y", 2, "active", 0)]
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
    pg_rows = [("src/doc-a", 3, "active", 0), ("src/doc-b", 2, "active", 0), ("src/doc-c", 1, "active", 0)]
    session_factory = _make_session_factory(scalar=6, rows=pg_rows)
    pipeline = _make_pipeline(actual_chunks=3, wv_chunks={"src/doc-b": {0, 1, 2}, "src/doc-c": {0}})

    report = await verify_source_vectors(session_factory, pipeline, "src")

    assert report.is_healthy is False
    assert report.missing_source_ids == ["src/doc-a"]  # 仅整篇缺失
    assert report.refill_source_ids == ["src/doc-a", "src/doc-b"]  # 并集,排序稳定
    assert report.stale_chunk_count == 1  # src/doc-b 的多余 index 2
    assert report.orphan_count == 0


@pytest.mark.asyncio
async def test_orphan_count_only_within_source_prefix():
    """孤儿计数限本源前缀:iterator 全表遍历后客户端按前缀过滤,跨源孤儿不计数。

    D4-ACC:汇总级已弃用 like 聚合,孤儿计数仍限本源前缀(客户端过滤)。
    """
    # Weaviate 全库数据:本源 1 正常 + 本源 1 孤儿 + 跨源 1 孤儿
    all_items = [
        MagicMock(properties={"source_id": "src/doc-1", "chunk_index": 0, "generation_ordinal": 0}),
        MagicMock(properties={"source_id": "src/ghost", "chunk_index": 5, "generation_ordinal": 0}),
        MagicMock(properties={"source_id": "other-source/orphan", "chunk_index": 0, "generation_ordinal": 0}),
    ]

    collection = MagicMock()
    collection.aggregate.over_all.return_value.total_count = 3  # 不再被读取
    collection.iterator.return_value = list(all_items)

    client = MagicMock()
    client.collections.get.return_value = collection
    pipeline = MagicMock()
    pipeline._client = client
    pipeline._class_name = "Document"

    # Postgres SUM=1(仅 src/doc-1);迭代器可见 actual=2(ghost 计入)→ 不健康
    session_factory = _make_session_factory(scalar=1, rows=[("src/doc-1", 1, "active", 0)])

    report = await verify_source_vectors(session_factory, pipeline, "src")

    assert report.is_healthy is False
    # 只统计本源前缀内的孤儿(src/ghost);跨源 other-source/orphan 不算
    assert report.orphan_count == 1
    # 汇总级不再使用 like 聚合(D4-ACC 口径统一)
    assert collection.aggregate.over_all.called is False
    # iterator 取 (source_id, chunk_index, generation_ordinal) 三属性
    assert collection.iterator.call_args.kwargs["return_properties"] == [
        "source_id",
        "chunk_index",
        "generation_ordinal",
    ]


# --------------------------------------------------------------------------- #
# INC-WEB-EMBED-413:在服代过滤口径(与 chunk_serving INT-C-01 对齐)
#
# 生产事实(2026-09-14 website-camthink):verify 旧口径对全部代对象计数,
# legacy/旧代残留使 chunk 集合永不一致 → 每轮 sync 进 refill → 修复重放
# 撞 413。在服真值 = 现行版本代命名空间(chunk_serving_for_doc 同款);
# 旧代残留不入在服、不入计数、不产生 refill(物理清除仅经 retire/GC)。
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_verify_ignores_other_generation_residue():
    """旧代残留(legacy 寻址)不入在服集:现行代对象完整 → 健康,零 refill。"""
    pg_rows = [("src/doc-r", 1, "active", 5)]
    session_factory = _make_session_factory(scalar=1, rows=pg_rows)
    pipeline = _make_pipeline(
        actual_chunks=1,
        wv_objects={"src/doc-r": [(0, 5), (0, 0), (1, 0)]},  # 在服 {0} + 旧代残留 {0,1}
    )

    report = await verify_source_vectors(session_factory, pipeline, "src")

    assert report.is_healthy is True
    assert report.actual_chunks == 1  # 仅在服代计数
    assert report.missing_source_ids == []
    assert report.refill_source_ids == []
    assert report.stale_chunk_count == 0
    assert report.orphan_count == 0


@pytest.mark.asyncio
async def test_verify_flags_missing_in_current_generation():
    """在服代缺 chunk(idx 1):即使旧代有同名 index 残留,也必须 refill。"""
    pg_rows = [("src/doc-m", 2, "active", 5)]
    session_factory = _make_session_factory(scalar=1, rows=pg_rows)
    pipeline = _make_pipeline(
        actual_chunks=1,
        wv_objects={"src/doc-m": [(0, 5), (0, 0), (1, 0)]},  # 在服仅 {0},缺 idx 1
    )

    report = await verify_source_vectors(session_factory, pipeline, "src")

    assert report.is_healthy is False
    assert report.missing_source_ids == []  # doc 有在服对象,非整篇缺失
    assert report.refill_source_ids == ["src/doc-m"]
    assert report.actual_chunks == 1
    assert report.stale_chunk_count == 0  # 旧代 idx 1 不算在服多余


@pytest.mark.asyncio
async def test_verify_whole_doc_only_old_generation_is_missing():
    """在服集为空(仅旧代残留)= 整篇缺失(pg 有、在服无)→ refill。"""
    pg_rows = [("src/doc-g", 2, "active", 5)]
    session_factory = _make_session_factory(scalar=1, rows=pg_rows)
    pipeline = _make_pipeline(
        actual_chunks=0,
        wv_objects={"src/doc-g": [(0, 0), (1, 0)]},
    )

    report = await verify_source_vectors(session_factory, pipeline, "src")

    assert report.is_healthy is False
    assert report.missing_source_ids == ["src/doc-g"]
    assert report.refill_source_ids == ["src/doc-g"]
    assert report.actual_chunks == 0
    assert report.orphan_count == 0  # 有账本行,非孤儿


@pytest.mark.asyncio
async def test_verify_propless_objects_not_serving():
    """无 generation_ordinal 属性的对象不入在服集(chunk_serving INT-C-01 同款)。"""
    pg_rows = [("src/doc-p", 1, "active", 5)]
    session_factory = _make_session_factory(scalar=1, rows=pg_rows)
    pipeline = _make_pipeline(
        actual_chunks=0,
        wv_objects={"src/doc-p": [(0, None)]},
    )

    report = await verify_source_vectors(session_factory, pipeline, "src")

    assert report.is_healthy is False
    assert report.missing_source_ids == ["src/doc-p"]
    assert report.refill_source_ids == ["src/doc-p"]
    assert report.actual_chunks == 0
