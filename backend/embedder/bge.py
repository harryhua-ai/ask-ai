"""基于 BAAI/bge-m3 与 BAAI/bge-reranker-v2-m3 的嵌入与重排实现。

- BGEEmbedder:1024 维 dense 向量,适用于语义检索。
- BGEReranker:cross-encoder 重排,用于精排提升 Top-K 质量。

两者均通过 FlagEmbedding 库加载,首次实例化时可能触发模型权重下载
(数 GB),生产环境建议预热。
"""

import logging

import numpy as np

from backend.embedder.base import Embedder, Reranker, detect_device

logger = logging.getLogger(__name__)


class BGEEmbedder(Embedder):
    """基于 BAAI/bge-m3 的嵌入模型实现。

    输出 1024 维 dense 向量,适用于 OpenAI 兼容的向量库(如 Weaviate)。
    """

    def __init__(self, device: str = "auto", model_name: str = "BAAI/bge-m3"):
        """加载 BGE-m3 模型权重。

        Args:
            device: 推理设备偏好。"auto" 自动检测,其他值(如 "cpu")强制指定。
            model_name: HuggingFace 模型标识,默认 BAAI/bge-m3。
        """
        self._device = detect_device(device)
        self._dimension = 1024
        logger.info("加载 BGE-m3 嵌入模型(device=%s)...", self._device)
        try:
            from FlagEmbedding import BGEM3FlagModel
        except ImportError as exc:  # pragma: no cover - 依赖缺失分支
            raise ImportError(
                "FlagEmbedding 未安装,请在虚拟环境中执行 "
                "`uv pip install FlagEmbedding` 或 `pip install FlagEmbedding`"
            ) from exc
        self._model = BGEM3FlagModel(model_name, use_fp16=self._device != "cpu")
        logger.info("BGE-m3 加载完成")

    @property
    def dimension(self) -> int:
        """返回嵌入维度(BGE-m3 固定 1024)。"""
        return self._dimension

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        """批量生成嵌入向量。

        Args:
            texts: 待嵌入的文本列表。

        Returns:
            与 texts 等长的 np.ndarray 列表,每个数组形状为 (1024,)。
        """
        embeddings = self._model.encode(
            texts,
            batch_size=12,
            max_length=8192,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )
        return [np.asarray(v) for v in embeddings["dense_vecs"]]


class BGEReranker(Reranker):
    """基于 BAAI/bge-reranker-v2-m3 的 cross-encoder 重排实现。

    对 (query, document) 对打分并归一化,分数越高表示越相关。
    """

    def __init__(
        self,
        device: str = "auto",
        model_name: str = "BAAI/bge-reranker-v2-m3",
    ):
        """加载 bge-reranker-v2-m3 模型权重。

        Args:
            device: 推理设备偏好。"auto" 自动检测,其他值(如 "cpu")强制指定。
            model_name: HuggingFace 模型标识,默认 BAAI/bge-reranker-v2-m3。
        """
        self._device = detect_device(device)
        logger.info("加载 bge-reranker-v2-m3(device=%s)...", self._device)
        try:
            from FlagEmbedding import FlagReranker
        except ImportError as exc:  # pragma: no cover - 依赖缺失分支
            raise ImportError(
                "FlagEmbedding 未安装,请在虚拟环境中执行 "
                "`uv pip install FlagEmbedding` 或 `pip install FlagEmbedding`"
            ) from exc
        self._model = FlagReranker(model_name, use_fp16=self._device != "cpu")
        logger.info("bge-reranker 加载完成")

    def rerank(self, query: str, documents: list[str]) -> list[float]:
        """对每个文档相对 query 计算相关性分数。

        Args:
            query: 查询文本。
            documents: 候选文档列表。

        Returns:
            与 documents 等长的 float 列表,分数已归一化到 [0, 1]。
            当仅传入一个文档时,FlagEmbedding 会返回标量,此处统一转换为列表。
        """
        pairs = [[query, doc] for doc in documents]
        scores = self._model.compute_score(pairs, normalize=True)
        if isinstance(scores, float):
            scores = [scores]
        return list(scores)
