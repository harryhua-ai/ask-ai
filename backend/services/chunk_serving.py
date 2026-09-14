"""v1.6.3 Track C(U-9):chunk 级 serving 投影(权威口径复用)。

冻结语义:投影必须源自**权威 chunk serving 口径**——与
``verify_source_vectors`` 同一判定方式(Weaviate 迭代器全扫 + 客户端
source_id 精确匹配;TEXT 属性过滤/聚合口径一律不可用于计数),UI 呈现
比例(serving/total)必须等于后端真值。

单文档口径:``total`` = 现行版本持久 chunk 数(document_version_chunks
行数,与 version.chunk_count 同账本),``serving`` = Weaviate 中该文档
实际存在的 chunk_index 集合与期望集合(0..total-1)的交集基数。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import DocumentVersionChunk


@dataclass(frozen=True)
class ChunkServing:
    """单文档 chunk 级 serving 投影真值。"""

    doc_source_id: str
    serving_chunks: int  # Weaviate 实际在服 chunk 数(∩ 期望集合)
    total_chunks: int  # 期望 chunk 总数(现行版本持久 chunk 数)
    missing_indices: tuple[int, ...]  # 期望存在但不在服的 index(升序)
    stale_indices: tuple[int, ...]  # 超出期望范围的存量 index(升序,仅呈现)

    @property
    def consistent(self) -> bool:
        """一致性判定 = 在服集合与期望集合精确相等(verify 口径)。"""
        return self.total_chunks == 0 or (
            self.serving_chunks == self.total_chunks and not self.stale_indices
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "serving_chunks": self.serving_chunks,
            "total_chunks": self.total_chunks,
            "missing_indices": list(self.missing_indices),
            "stale_indices": list(self.stale_indices),
            "consistent": self.consistent,
        }


async def expected_chunk_total(session: AsyncSession, version_id: Any) -> int:
    """现行版本持久 chunk 总数(document_version_chunks 行数口径)。"""
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(DocumentVersionChunk)
                .where(DocumentVersionChunk.version_id == version_id)
            )
        ).scalar()
        or 0
    )


def chunk_serving_for_doc(
    weaviate_client: Any,
    class_name: str,
    doc_source_id: str,
    total_chunks: int,
) -> ChunkServing:
    """单文档 chunk serving 投影(verify_source_vectors 同口径:迭代器全扫)。

    Args:
        weaviate_client: Weaviate v4 client(与 ingestion/校验同一实例)。
        class_name: Document collection 名。
        doc_source_id: 复合文档身份(精确匹配,非前缀)。
        total_chunks: 期望 chunk 总数(现行版本持久 chunk 数)。

    Returns:
        ChunkServing 真值。Weaviate 不可达时异常向上传播(调用方决定
        503 诚实降级,绝不伪造 12/12)。
    """
    collection = weaviate_client.collections.get(class_name)
    present: set[int] = set()
    for item in collection.iterator(return_properties=["source_id", "chunk_index"]):
        props = item.properties
        sid = props.get("source_id")
        idx = props.get("chunk_index")
        if sid is None or idx is None:
            continue
        if str(sid) != doc_source_id:
            continue  # 精确匹配本文档(verify 口径:客户端侧过滤,计数才权威)
        present.add(int(idx))
    expected = set(range(max(total_chunks, 0)))
    missing = tuple(sorted(expected - present))
    stale = tuple(sorted(present - expected))
    return ChunkServing(
        doc_source_id=doc_source_id,
        serving_chunks=len(expected & present),
        total_chunks=max(total_chunks, 0),
        missing_indices=missing,
        stale_indices=stale,
    )
