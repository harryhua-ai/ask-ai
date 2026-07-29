"""文档处理与 RAG 管道。

- chunk_document: 把 RawDocument 按结构切成多个 Chunk。
- IngestionPipeline: chunk → embed → Weaviate(+ 可选 Postgres)灌入管道。
- RAGOrchestrator: 检索 → 重排 → (裁剪) → 拒答/生成的 RAG 编排器。
"""

from backend.pipeline.chunk import Chunk, chunk_document
from backend.pipeline.ingest import IngestionPipeline
from backend.pipeline.rag import RAGAnswer, RAGOrchestrator

__all__ = [
    "Chunk",
    "IngestionPipeline",
    "RAGAnswer",
    "RAGOrchestrator",
    "chunk_document",
]
