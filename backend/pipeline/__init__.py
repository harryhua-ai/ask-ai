"""文档分段管道(chunking pipeline)。

提供 chunk_document 入口,把 RawDocument 按结构切成多个 Chunk。
"""

from backend.pipeline.chunk import Chunk, chunk_document

__all__ = [
    "Chunk",
    "chunk_document",
]
