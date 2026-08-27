"""Postgres ↔ Weaviate 向量一致性校验。

用于同步"无变更跳过"分支：源码无变更时，不轻信 documents 表有记录就跳过，
而是核对 Weaviate 是否真有对应向量。两级校验：
  1. 汇总级(O(1))：Postgres SUM(chunk_count) vs Weaviate total_count，相等即健康；
  2. 精确级(仅汇总级不等时)：逐 source_id 差集，找出 pg 有、Weaviate 无的缺口。
只读、不修改任何数据（孤儿向量仅 warning，不删）。
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
    missing_source_ids: list[str] = field(default_factory=list)  # pg 有、Weaviate 无
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
        VectorGapReport。is_healthy=True 表示无需补齐。
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
    agg = collection.aggregate.over_all(
        total_count=True,
        filters=Filter.by_property("source_id").like(f"{source_prefix}/*"),
    )
    actual = int(getattr(agg, "total_count", 0) or 0)

    if expected == actual:
        return VectorGapReport(expected_chunks=expected, actual_chunks=actual)

    # 2) 精确级:差集(pg 有、Weaviate 无)
    async with session_factory() as session:
        result = await session.execute(
            select(Document.source_id).where(Document.source_id.like(f"{source_prefix}/%"))
        )
        pg_ids = {row[0] for row in result.all()}

    wv_ids: set[str] = set()
    for item in collection.iterator(return_properties=["source_id"]):
        sid = item.properties.get("source_id")
        if sid:
            wv_ids.add(sid)

    missing = sorted(pg_ids - wv_ids)
    orphans = len(wv_ids - pg_ids)
    if orphans:
        logger.warning(
            "一致性校验:数据源 %s 发现 %d 个孤儿向量(Weaviate 有、Postgres 无),不删除",
            source_prefix,
            orphans,
        )
    return VectorGapReport(
        expected_chunks=expected,
        actual_chunks=actual,
        missing_source_ids=missing,
        orphan_count=orphans,
    )
