"""人工答案覆盖匹配服务。

支持三种匹配策略:
- keyword: 简单子串包含(大小写不敏感)
- regex: 正则表达式匹配
- semantic: BGE-m3 embedding 余弦相似度

语义匹配的 embedding 在 refresh() 时预计算并缓存,
运行时只需 embed query 一次,与缓存的 override embedding 比对。
"""

import asyncio
import logging
import re
from uuid import UUID

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db.models import AnswerOverride
from backend.embedder.base import Embedder

logger = logging.getLogger(__name__)


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """计算两个向量的余弦相似度。"""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


class OverrideMatcher:
    """人工答案覆盖匹配器。

    缓存活跃 override 列表及其 semantic embedding,
    提供 match(query) 方法检查是否命中任意覆盖规则。
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        embedder: Embedder,
        threshold: float = 0.85,
    ) -> None:
        """初始化匹配器。

        Args:
            session_factory: Postgres 异步会话工厂。
            embedder: BGE-m3 嵌入模型(用于 semantic 匹配)。
            threshold: semantic 匹配的余弦相似度阈值。
        """
        self._factory = session_factory
        self._embedder = embedder
        self._threshold = threshold
        self._overrides: list[AnswerOverride] = []
        self._embeddings: dict[UUID, np.ndarray] = {}
        self._lock = asyncio.Lock()

    async def refresh(self) -> None:
        """从 DB 重新加载活跃 override,并为新增项计算 semantic embedding。"""
        async with self._lock:
            async with self._factory() as session:
                result = await session.execute(
                    select(AnswerOverride).where(AnswerOverride.is_active.is_(True))
                )
                overrides = result.scalars().all()

            for ov in overrides:
                if ov.match_type == "semantic" and ov.id not in self._embeddings:
                    try:
                        emb = self._embedder.embed([ov.match_pattern])
                        self._embeddings[ov.id] = emb[0]
                    except Exception:
                        logger.exception("Override embedding 计算失败,跳过: %s", ov.id)

            active_ids = {ov.id for ov in overrides}
            stale_ids = set(self._embeddings.keys()) - active_ids
            for sid in stale_ids:
                del self._embeddings[sid]

            self._overrides = overrides
            logger.info("OverrideMatcher 已加载 %d 条活跃覆盖", len(overrides))

    async def match(self, query: str) -> AnswerOverride | None:
        """检查 query 是否命中任意活跃覆盖规则。

        匹配优先级:keyword → regex → semantic。

        Args:
            query: 用户查询文本。

        Returns:
            命中的 AnswerOverride,未命中返回 None。
        """
        overrides = self._overrides
        if not overrides:
            return None

        for ov in overrides:
            if ov.match_type == "keyword":
                if ov.match_pattern.lower() in query.lower():
                    return ov

        for ov in overrides:
            if ov.match_type == "regex":
                if re.search(ov.match_pattern, query):
                    return ov

        semantic_overrides = [ov for ov in overrides if ov.match_type == "semantic"]
        if not semantic_overrides:
            return None

        try:
            query_emb = self._embedder.embed([query])[0]
        except Exception:
            logger.exception("Query embedding 计算失败,跳过 semantic 匹配")
            return None

        best_score = 0.0
        best_match: AnswerOverride | None = None
        for ov in semantic_overrides:
            emb = self._embeddings.get(ov.id)
            if emb is None:
                continue
            score = _cosine_similarity(query_emb, emb)
            if score > best_score:
                best_score = score
                best_match = ov

        if best_match is not None and best_score >= self._threshold:
            return best_match

        return None
