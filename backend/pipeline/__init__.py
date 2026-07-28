"""文档处理管道。

- chunk_document: 把 RawDocument 按结构切成多个 Chunk。
- IngestionPipeline: chunk → embed → Weaviate(+ 可选 Postgres)灌入管道。
"""

from backend.pipeline.chunk import Chunk, chunk_document
from backend.pipeline.ingest import IngestionPipeline

__all__ = [
    "Chunk",
    "IngestionPipeline",
    "chunk_document",
]
