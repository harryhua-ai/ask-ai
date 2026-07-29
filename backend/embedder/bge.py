"""基于 BAAI/bge-m3 与 BAAI/bge-reranker-v2-m3 的嵌入与重排实现。

- BGEEmbedder:1024 维 dense 向量,适用于语义检索。
- BGEReranker:cross-encoder 重排,用于精排提升 Top-K 质量。

两者均通过 FlagEmbedding 库加载,首次实例化时可能触发模型权重下载
(数 GB)。模型权重缓存在项目本地 `MODEL_CACHE_DIR`(默认 `<repo>/models/`),
避免污染用户主目录且便于跨环境迁移。
"""

import logging
import os
from pathlib import Path

import numpy as np

from backend.embedder.base import Embedder, Reranker, detect_device

logger = logging.getLogger(__name__)


def _ensure_hf_cache(model_cache_dir: Path) -> None:
    """把 HuggingFace 缓存目录指向项目本地路径。

    必须在 import FlagEmbedding / transformers 之前调用,否则
    `from_pretrained` 仍会用默认 `~/.cache/huggingface/hub/`。

    Args:
        model_cache_dir: 项目内缓存目录(如 `<repo>/models/`)。
            实际 HuggingFace hub 缓存位于其下的 `hub/` 子目录。
    """
    hub_dir = model_cache_dir / "hub"
    hub_dir.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", str(model_cache_dir))
    os.environ.setdefault("HF_HUB_CACHE", str(hub_dir))
    os.environ.setdefault("TRANSFORMERS_CACHE", str(hub_dir))


class BGEEmbedder(Embedder):
    """基于 BAAI/bge-m3 的嵌入模型实现。

    输出 1024 维 dense 向量,适用于 OpenAI 兼容的向量库(如 Weaviate)。
    """

    def __init__(
        self,
        device: str = "auto",
        model_name: str = "BAAI/bge-m3",
        cache_dir: Path | None = None,
    ):
        """加载 BGE-m3 模型权重。

        Args:
            device: 推理设备偏好。"auto" 自动检测,其他值(如 "cpu")强制指定。
            model_name: HuggingFace 模型标识,默认 BAAI/bge-m3。
            cache_dir: 模型权重本地缓存目录。为 None 时取环境变量
                `MODEL_CACHE_DIR`,默认 `<repo>/models/`。
        """
        self._device = detect_device(device)
        self._dimension = 1024
        resolved_cache = cache_dir or Path(
            os.environ.get("MODEL_CACHE_DIR", Path(__file__).resolve().parents[2] / "models")
        )
        _ensure_hf_cache(resolved_cache)
        logger.info("加载 BGE-m3 嵌入模型(device=%s, cache=%s)...", self._device, resolved_cache)
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
        cache_dir: Path | None = None,
    ):
        """加载 bge-reranker-v2-m3 模型权重。

        Args:
            device: 推理设备偏好。"auto" 自动检测,其他值(如 "cpu")强制指定。
            model_name: HuggingFace 模型标识,默认 BAAI/bge-reranker-v2-m3。
            cache_dir: 模型权重本地缓存目录。为 None 时取环境变量
                `MODEL_CACHE_DIR`,默认 `<repo>/models/`。
        """
        self._device = detect_device(device)
        resolved_cache = cache_dir or Path(
            os.environ.get("MODEL_CACHE_DIR", Path(__file__).resolve().parents[2] / "models")
        )
        _ensure_hf_cache(resolved_cache)
        logger.info("加载 bge-reranker-v2-m3(device=%s, cache=%s)...", self._device, resolved_cache)
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
