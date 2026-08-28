"""Postgres ↔ Weaviate 向量一致性校验。

用于同步"无变更跳过"分支：源码无变更时，不轻信 documents 表有记录就跳过，
而是核对 Weaviate 是否真有对应向量。两级校验：
  1. 汇总级(O(1))：Postgres SUM(chunk_count) vs Weaviate total_count，相等即健康；
  2. 精确级(仅汇总级不等时)：chunk 级差集 —— 逐 source_id 比对 Weaviate 实际
     chunk_index 集合 vs Postgres chunk_count,整篇缺失与 chunk 集合不一致的
     doc 一并进重灌清单。
只读、不修改任何数据（孤儿向量仅 warning,不删）。
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from weaviate.classes.query import Filter

from backend.db.models import Document

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VectorGapReport:
    """Postgres ↔ Weaviate 一致性校验结果。"""

    expected_chunks: int  # Postgres SUM(chunk_count)
    actual_chunks: int  # Weaviate 该源实际 chunk 数
    missing_source_ids: list[str] = field(default_factory=list)  # 整篇缺失(pg 有、Weaviate 无)
    # 需整篇重灌的 doc = 整篇缺失 ∪ chunk 集合不一致;is_healthy 判定不依赖此字段
    refill_source_ids: list[str] = field(default_factory=list)
    # 多余 chunk 计数(实际 index 超出 0..chunk_count-1 的数量,仅统计供日志,不删除)
    stale_chunk_count: int = 0
    orphan_count: int = 0  # Weaviate 有、pg 无(仅 warning 不删)

    @property
    def is_healthy(self) -> bool:
        """汇总级相等即视为健康(不深入精确级)。"""
        return self.expected_chunks == self.actual_chunks


async def verify_source_vectors(
    session_factory: async_sessionmaker[AsyncSession],
    pipeline,
    source_prefix: str,
) -> VectorGapReport:
    """校验某数据源在 Postgres 与 Weaviate 间的向量一致性。

    Args:
        session_factory: 异步会话工厂(写 SyncLog / documents 用,与 sync.py 同款)。
        pipeline: IngestionPipeline,经其 ``_client`` / ``_class_name`` 访问 Weaviate。
        source_prefix: 数据源 ID(如 ``"wiki-documents-local"``)。内部按
            ``'{prefix}/%'``(SQL)与 ``'{prefix}/*'``(Weaviate like)前缀匹配。

    Returns:
        VectorGapReport。is_healthy=True 表示无需补齐;refill_source_ids 为需
        重灌的 doc 清单(整篇缺失 ∪ chunk 集合不一致)。
    """
    # 1) 汇总级:Postgres SUM(chunk_count)
    async with session_factory() as session:
        result = await session.execute(
            select(func.coalesce(func.sum(Document.chunk_count), 0)).where(
                Document.source_id.like(f"{source_prefix}/%")
            )
        )
        expected = int(result.scalar() or 0)

    collection = pipeline._client.collections.get(pipeline._class_name)
    source_filter = Filter.by_property("source_id").like(f"{source_prefix}/*")
    agg = collection.aggregate.over_all(total_count=True, filters=source_filter)
    actual = int(getattr(agg, "total_count", 0) or 0)

    if expected == actual:
        return VectorGapReport(expected_chunks=expected, actual_chunks=actual)

    # 2) 精确级:chunk 级差集
    #    Postgres 侧取 (source_id, chunk_count)
    async with session_factory() as session:
        result = await session.execute(
            select(Document.source_id, Document.chunk_count).where(
                Document.source_id.like(f"{source_prefix}/%")
            )
        )
        pg_chunks: dict[str, int] = {sid: int(cc) for sid, cc in result.all()}

    #    Weaviate 侧拉 (source_id, chunk_index)。两个 v4 限制(v4.22 实测):
    #    - iterator() 不支持 filters 参数;
    #    - fetch_objects 的 after 游标与 where 过滤互斥(cursor api 限制)。
    #    故只能 iterator 全表遍历 + 客户端前缀过滤(orphan 计数仍限本源)。
    wv_chunks: dict[str, set[int]] = {}
    prefix = f"{source_prefix}/"
    for item in collection.iterator(return_properties=["source_id", "chunk_index"]):
        props = item.properties
        sid = props.get("source_id")
        idx = props.get("chunk_index")
        if sid is None or idx is None:
            continue
        sid = str(sid)
        if not sid.startswith(prefix):
            continue  # 客户端前缀过滤
        wv_chunks.setdefault(sid, set()).add(int(idx))

    # 整篇缺失:pg 有、Weaviate 完全没有
    missing = sorted(sid for sid in pg_chunks if sid not in wv_chunks)
    # chunk 集合不一致:doc 在 Weaviate 但实际 index 集合 != 期望的 0..chunk_count-1
    refill: set[str] = set(missing)
    stale_total = 0
    for sid, chunk_count in pg_chunks.items():
        actual_indices = wv_chunks.get(sid)
        if actual_indices is None:
            continue  # 整篇缺失,上面已入 refill
        expected_indices = set(range(chunk_count))
        if actual_indices != expected_indices:
            refill.add(sid)
            # 仅统计"多余"部分(超出期望范围的 index);丢失不算多余
            stale_total += len(actual_indices - expected_indices)
    orphans = len(wv_chunks.keys() - pg_chunks.keys())

    if stale_total:
        logger.warning(
            "一致性校验:数据源 %s 发现 %d 个多余 chunk(index 超出 0..chunk_count-1),不删除",
            source_prefix,
            stale_total,
        )
    if orphans:
        logger.warning(
            "一致性校验:数据源 %s 发现 %d 个孤儿向量(Weaviate 有、Postgres 无),不删除",
            source_prefix,
            orphans,
        )
    if missing:
        logger.warning(
            "一致性校验:数据源 %s 有 %d 篇整篇缺失(如 %s)",
            source_prefix,
            len(missing),
            missing[:3],
        )
    mismatched = len(refill) - len(missing)
    if mismatched:
        logger.warning(
            "一致性校验:数据源 %s 有 %d 篇 chunk 集合不一致(部分丢失或多余)",
            source_prefix,
            mismatched,
        )
    return VectorGapReport(
        expected_chunks=expected,
        actual_chunks=actual,
        missing_source_ids=missing,
        refill_source_ids=sorted(refill),
        stale_chunk_count=stale_total,
        orphan_count=orphans,
    )
