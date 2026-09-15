"""Postgres ↔ Weaviate 向量一致性校验。

用于同步"无变更跳过"分支：源码无变更时，不轻信 documents 表有记录就跳过，
而是核对 Weaviate 是否真有对应向量。两级校验：
  1. 汇总级(O(1))：Postgres SUM(chunk_count) vs Weaviate total_count，相等即健康；
  2. 精确级(仅汇总级不等时)：chunk 级差集 —— 逐 source_id 比对 Weaviate 实际
     chunk_index 集合 vs Postgres chunk_count,整篇缺失与 chunk 集合不一致的
     doc 一并进重灌清单。
只读、不修改任何数据（孤儿向量仅 warning,不删）。

INC-WEB-EMBED-413 口径矫正:在服集合按**现行版本代**过滤
(``generation_ordinal == 现行版本代``,chunk_serving INT-C-01 同款;
无代属性对象不入在服)。旧代/legacy 残留 = 保留窗内预期存在(物理清除仅经
retire/GC),不入在服、不产生 refill —— 旧代无关计数曾使 chunk 集合永不
一致,refill 每轮复现并把修复重放拖入必败循环(生产 website-camthink
2026-09-14 实证:2 篇永久 partial → 混入超契约行后连续 5 代 413 零激活)。
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db.models import Document, DocumentVersion
from backend.services.document_lifecycle import DocLifecycle

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VectorGapReport:
    """Postgres ↔ Weaviate 一致性校验结果。"""

    expected_chunks: int  # Postgres SUM(chunk_count)(仅 SERVING 生命期文档)
    actual_chunks: int  # Weaviate 该源实际 chunk 数(SERVING 文档的对象)
    missing_source_ids: list[str] = field(default_factory=list)  # 整篇缺失(pg 有、Weaviate 无)
    # 需整篇重灌的 doc = 整篇缺失 ∪ chunk 集合不一致;is_healthy 判定不依赖此字段
    refill_source_ids: list[str] = field(default_factory=list)
    # 多余 chunk 计数(实际 index 超出 0..chunk_count-1 的数量,仅统计供日志,不删除)
    stale_chunk_count: int = 0
    orphan_count: int = 0  # Weaviate 有、pg 无(仅 warning 不删)
    # 孤儿明细:source_id → 该孤儿文档在 Weaviate 的实际 chunk_index 集合。
    # 供 sync 生命周期 reconciliation 分类(MISSING_LEGITIMATE /
    # EXTRA_CONFIRMED_RETIRED / EXTRA_UNRESOLVED_ORPHAN);本函数只读不删。
    orphan_chunks: dict[str, set[int]] = field(default_factory=dict)
    # P1:已撤出文档(superseded/deleted 墓碑)的待 GC 对象数——预期存在
    # (RETIRED/墓碑保留窗内物理仍在),不计缺口、不影响健康判定。
    withdrawn_chunk_count: int = 0

    @property
    def is_healthy(self) -> bool:
        """健康 = 汇总相等且无任何缺口(整篇缺失 / chunk 集合不一致 / 孤儿)。

        迭代器口径下 expected/actual 同源相等已蕴含前两者一致;
        显式列出 refill/orphan 条件以保证无「账面一致但存在漂移」的漏判。
        withdrawn(墓碑/被接替待 GC)对象为 P1 保留窗内的预期残留,不入判定。
        """
        return (
            self.expected_chunks == self.actual_chunks
            and not self.refill_source_ids
            and self.orphan_count == 0
        )


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
    # 1) 汇总级:Postgres SUM(chunk_count)(仅 SERVING 生命期;墓碑/被接替
    #    文档的对象为保留窗内预期残留,不进期望,I-1 计数权威 = Postgres)
    async with session_factory() as session:
        result = await session.execute(
            select(func.coalesce(func.sum(Document.chunk_count), 0)).where(
                Document.source_id.like(f"{source_prefix}/%"),
                Document.lifecycle.in_(DocLifecycle.SERVING),
            )
        )
        expected = int(result.scalar() or 0)

    # 3) 精确级:chunk 级差集 —— 先取 PG 侧 (source_id, chunk_count, lifecycle,
    #    现行版本 generation_ordinal),供迭代器按在服代过滤(INT-C-01 同款)
    async with session_factory() as session:
        result = await session.execute(
            select(
                Document.source_id,
                Document.chunk_count,
                Document.lifecycle,
                func.coalesce(DocumentVersion.generation_ordinal, 0),
            )
            .outerjoin(DocumentVersion, DocumentVersion.id == Document.current_version_id)
            .where(Document.source_id.like(f"{source_prefix}/%"))
        )
        pg_rows = result.all()
        pg_chunks: dict[str, int] = {}
        withdrawn_docs: set[str] = set()
        current_ordinal: dict[str, int] = {}
        for sid, cc, lc, ordinal in pg_rows:
            if lc in DocLifecycle.WITHDRAWN:
                withdrawn_docs.add(sid)
                continue  # 墓碑/被接替:对象为待 GC 残留,不计期望
            pg_chunks[sid] = int(cc)
            current_ordinal[sid] = int(ordinal)

    collection = pipeline._client.collections.get(pipeline._class_name)

    # 2) 汇总级 + 精确级统一口径:单次迭代器全扫 + 客户端前缀过滤。
    #    Weaviate TEXT like 按 token 分词匹配,源前缀互相污染(neomind 家族
    #    实证:`neomind-local/*` 聚合计数把整个家族对象都算进来),聚合口径
    #    不可用于计数;一切以迭代器可见对象为准(D4-ACC)。
    #    v4 限制(v4.22 实测):iterator() 不支持 filters 参数。
    #    INC-WEB-EMBED-413:在服判定按现行版本代过滤(chunk_serving INT-C-01
    #    同款;无 generation 属性对象不入在服)。旧代/legacy 残留是保留窗内
    #    预期存在(物理清除仅经 retire/GC),不再计入在服集合 —— 否则残留
    #    使 chunk 集合永不一致,refill 每轮复现(生产 website-camthink 实证)
    #    且把修复重放拖入必败循环。
    wv_chunks: dict[str, set[int]] = {}  # 全代对象(孤儿判定,保持代无关)
    serving_chunks: dict[str, set[int]] = {}  # 现行版本代在服对象
    prefix = f"{source_prefix}/"
    actual = 0
    for item in collection.iterator(
        return_properties=["source_id", "chunk_index", "generation_ordinal"]
    ):
        props = item.properties
        sid = props.get("source_id")
        idx = props.get("chunk_index")
        if sid is None or idx is None:
            continue
        sid = str(sid)
        if not sid.startswith(prefix):
            continue  # 客户端前缀过滤
        wv_chunks.setdefault(sid, set()).add(int(idx))
        if sid in withdrawn_docs:
            continue  # 撤出文档的待 GC 残留不进服务口径统计
        obj_ordinal = props.get("generation_ordinal")
        if obj_ordinal is None:
            continue  # 无代属性对象不入在服(INT-C-01 同款)
        if sid not in current_ordinal:
            continue  # 孤儿 doc(无账本行):不入在服计数
        if int(obj_ordinal) != current_ordinal[sid]:
            continue  # 非现行版本代:保留窗残留,不入在服
        serving_chunks.setdefault(sid, set()).add(int(idx))
        actual += 1

    # 整篇缺失:pg 有、在服集为空(含仅有旧代残留 —— 服务面等价缺失)
    missing = sorted(sid for sid in pg_chunks if not serving_chunks.get(sid))
    # chunk 集合不一致:在服 index 集合 != 期望的 0..chunk_count-1
    refill: set[str] = set(missing)
    stale_total = 0
    for sid, chunk_count in pg_chunks.items():
        actual_indices = serving_chunks.get(sid)
        if actual_indices is None:
            continue  # 整篇缺失,上面已入 refill
        expected_indices = set(range(chunk_count))
        if actual_indices != expected_indices:
            refill.add(sid)
            # 仅统计"多余"部分(超出期望范围的 index);丢失不算多余
            stale_total += len(actual_indices - expected_indices)
    orphans = len(wv_chunks.keys() - pg_chunks.keys() - withdrawn_docs)
    orphan_chunks = {
        sid: set(wv_chunks[sid])
        for sid in sorted(wv_chunks.keys() - pg_chunks.keys() - withdrawn_docs)
    }
    # P1:撤出文档的待 GC 残留对象(预期存在,单列呈现,不入缺口)
    withdrawn_chunk_count = sum(len(wv_chunks[sid]) for sid in withdrawn_docs if sid in wv_chunks)

    if withdrawn_chunk_count:
        logger.info(
            "一致性校验:数据源 %s 有 %d 个待 GC 残留对象(墓碑/被接替保留窗内,预期存在)",
            source_prefix,
            withdrawn_chunk_count,
        )
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
        orphan_chunks=orphan_chunks,
        withdrawn_chunk_count=withdrawn_chunk_count,
    )
