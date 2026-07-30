"""LLM 剪枝器 — 在 rerank 之后、生成之前过滤低相关 chunk。

使用小 LLM(deepseek-v4-flash)批量评估 chunk 与 query 的相关性,
过滤低相关结果以减少噪声、提升答案质量并降低生成 token 成本。
"""

import json
import logging
from typing import Protocol

from backend.llm.base import LLMProvider
from backend.retrieval.search import SearchResult

logger = logging.getLogger(__name__)


class Pruner(Protocol):
    """剪枝器协议 — Phase 3 插入重排与生成之间。"""

    async def prune(self, query: str, chunks: list[SearchResult]) -> list[SearchResult]:
        """过滤低相关 chunk,保留高相关 chunk。

        Args:
            query: 用户查询文本(经 query rewrite 后)。
            chunks: 重排后的 SearchResult 列表。

        Returns:
            过滤后的 SearchResult 列表,长度 <= chunks。
        """
        ...


class LLMPruner:
    """基于 LLM 的批量剪枝器。

    单次 LLM 调用评估所有 chunk 的相关性,按阈值过滤。
    失败时 fail-open(保留全部 chunk),避免过度剪枝导致拒答。
    """

    def __init__(
        self,
        llm: LLMProvider,
        relevance_threshold: float = 0.5,
        min_keep: int = 3,
    ) -> None:
        """初始化剪枝器。

        Args:
            llm: LLM 供应商(通过 task="pruning" 路由到 deepseek-v4-flash)。
            relevance_threshold: 相关性阈值,LLM 返回 1 视为相关,0 视为不相关。
            min_keep: 最少保留的 chunk 数量,防止过度剪枝。
        """
        self._llm = llm
        self._threshold = relevance_threshold
        self._min_keep = min_keep

    async def prune(self, query: str, chunks: list[SearchResult]) -> list[SearchResult]:
        """批量评估 chunk 相关性并过滤。

        Args:
            query: 用户查询文本。
            chunks: 重排后的 SearchResult 列表。

        Returns:
            过滤后的 SearchResult 列表。
        """
        if not chunks:
            return []

        prompt = self._build_prompt(query, chunks)
        messages = [{"role": "user", "content": prompt}]

        try:
            response = await self._llm.generate(
                messages, task="pruning", max_tokens=512, temperature=0.0
            )
        except Exception:
            logger.exception("Pruner LLM 调用失败,fail-open 保留全部 chunk")
            return chunks

        scores = self._parse_scores(response.content, len(chunks))
        if scores is None:
            logger.warning("Pruner LLM 返回格式异常,fail-open 保留全部 chunk")
            return chunks

        relevant = [
            chunk
            for chunk, score in zip(chunks, scores)
            if score >= self._threshold
        ]

        if len(relevant) < self._min_keep:
            ranked = sorted(zip(chunks, scores), key=lambda x: x[1], reverse=True)
            relevant = [chunk for chunk, _ in ranked[: self._min_keep]]

        return relevant

    def _build_prompt(self, query: str, chunks: list[SearchResult]) -> str:
        """构建批量相关性评估 prompt。"""
        passages = "\n".join(
            f"[{i}] {chunk.text[:500]}" for i, chunk in enumerate(chunks)
        )
        return (
            f"你是一个相关性判断器。给定用户问题和一组文本片段,"
            f"判断每个片段是否与回答该问题相关。\n\n"
            f"用户问题: {query}\n\n"
            f"文本片段:\n{passages}\n\n"
            f"请返回一个 JSON 数组,包含 {len(chunks)} 个元素,"
            f"每个元素为 0(不相关)或 1(相关)。\n"
            f"例如: [1, 0, 1, 1, 0]\n\n"
            f"只返回 JSON 数组,不要返回其他内容。"
        )

    def _parse_scores(self, content: str, expected_count: int) -> list[float] | None:
        """解析 LLM 返回的 JSON 评分数组。

        Args:
            content: LLM 返回的原始文本。
            expected_count: 期望的评分数量(等于 chunk 数)。

        Returns:
            评分数组,解析失败时返回 None。
        """
        try:
            stripped = content.strip()
            start = stripped.find("[")
            end = stripped.rfind("]")
            if start == -1 or end == -1:
                return None
            scores = json.loads(stripped[start : end + 1])
            if len(scores) != expected_count:
                return None
            return [float(s) for s in scores]
        except (json.JSONDecodeError, ValueError, TypeError):
            return None
