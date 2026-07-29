"""嵌入与重排抽象层。

提供 Embedder / Reranker Protocol、detect_device 设备检测工具,
以及 BGE-m3 / bge-reranker-v2-m3 的具体实现。
"""

from backend.embedder.base import Embedder, Reranker, detect_device
from backend.embedder.bge import BGEEmbedder, BGEReranker

__all__ = [
    "BGEEmbedder",
    "BGEReranker",
    "Embedder",
    "Reranker",
    "detect_device",
]
