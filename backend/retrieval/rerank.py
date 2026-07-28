"""Reranking 管道。

对 :class:`backend.retrieval.search.HybridSearcher` 返回的 top-N 候选
使用 bge-reranker(实现 :class:`backend.embedder.base.Reranker` 协议)做
cross-encoder 精排,过滤低于阈值的结果并截断到 ``top_k``。

关键设计:
- 候选 ``SearchResult`` 为 ``frozen=True`` dataclass,使用
  :func:`dataclasses.replace` 生成新实例(只改 ``score``),保持不变量。
- 空 ``results`` 短路返回 ``[]``,不调用 reranker,节省成本。
- reranker 返回 scores 长度与 results 不一致时抛 ``RuntimeError``(与
  :mod:`backend.retrieval.search` / :mod:`backend.pipeline.ingest` 一致)。
- ``top_k=None`` 时使用构造函数 default;``top_k=0`` 显式返回空列表,
  避免 ``top_k or self._default_top_k`` 写法的 0 falsy 陷阱。
"""

import logging
from dataclasses import replace

from backend.embedder.base import Reranker
from backend.retrieval.search import SearchResult

logger = logging.getLogger(__name__)


class RerankPipeline:
    """重排管道(bge-reranker + 阈值过滤 + top_k 截断)。

    Attributes:
        _reranker: 实现 :class:`backend.embedder.base.Reranker` 协议的模型实例。
        _threshold: 分数阈值,低于此值的结果被丢弃。默认 0.3。
        _default_top_k: ``rerank`` 未显式传 ``top_k`` 时使用的默认上限。默认 10。
    """

    def __init__(
        self,
        reranker: Reranker,
        threshold: float = 0.3,
        top_k: int = 10,
    ) -> None:
        """初始化重排管道。

        Args:
            reranker: 实现 Reranker Protocol 的模型实例。
            threshold: 重排分数阈值,默认 0.3。
            top_k: 默认返回结果数上限,默认 10。
        """
        self._reranker = reranker
        self._threshold = threshold
        self._default_top_k = top_k

    def rerank(
        self,
        query: str,
        results: list[SearchResult],
        top_k: int | None = None,
    ) -> list[SearchResult]:
        """对候选结果做 cross-encoder 精排。

        流程:
            1. 空 ``results`` 直接返回 ``[]``,不调用 reranker。
            2. 提取 ``text`` 列表传入 reranker;返回 scores 长度与
               ``results`` 不匹配时抛 ``RuntimeError``。
            3. 按 reranker 分数降序排序。
            4. 过滤掉低于 ``threshold`` 的结果。
            5. 截断到 ``top_k``(显式传入则用传入值,否则用构造函数 default)。

        Args:
            query: 用户查询文本。
            results: 候选 ``SearchResult`` 列表(通常来自 hybrid 检索)。
            top_k: 返回结果数上限。``None`` 时使用构造函数 default;
                ``0`` 视为显式 0(返回空列表)。

        Returns:
            重排后的 ``SearchResult`` 列表(score 字段被更新为 reranker 分数)。

        Raises:
            RuntimeError: reranker 返回 scores 长度与 ``results`` 不匹配。
        """
        # 防御:空候选直接返回,避免不必要的 reranker 调用
        if not results:
            logger.info("空候选列表,跳过重排")
            return []

        # 注意:用 `is not None` 而非 `or`,避免 top_k=0 时 falsy 误 fallback
        k = top_k if top_k is not None else self._default_top_k

        documents = [r.text for r in results]
        scores = self._reranker.rerank(query, documents)

        # 长度一致性校验,防止下游模型契约违规被静默掩盖
        if len(scores) != len(results):
            raise RuntimeError(
                f"reranker 返回 scores 长度({len(scores)})与 results" f"({len(results)})不匹配"
            )

        # 降序排序 → 阈值过滤 → 截断 top_k
        scored = sorted(zip(results, scores), key=lambda x: x[1], reverse=True)
        filtered = [replace(r, score=s) for r, s in scored if s >= self._threshold]
        return filtered[:k]

    @property
    def threshold(self) -> float:
        """当前重排分数阈值。"""
        return self._threshold
