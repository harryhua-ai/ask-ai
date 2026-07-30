# backend/services/clustering.py
"""问题聚类服务。

使用 BGE-m3 embedding + K-Means 将对话问题按语义聚类。
Coverage Gaps(type='gap')聚类未回答问题;Top Questions(type='top')聚类全部问题。
聚类为手动触发,结果存入 question_clusters 表并更新 conversations.cluster_id。
"""

import logging
import math
import uuid
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import numpy as np
from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db.models import Conversation, QuestionCluster
from backend.embedder.base import Embedder

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClusterResult:
    """单个聚类结果。"""

    cluster_id: UUID
    cluster_type: str
    representative_question: str
    sample_questions: list[str]
    question_count: int


class ClusteringService:
    """K-Means 问题聚类服务。"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        embedder: Embedder,
        n_clusters: int | None = None,
        max_samples: int = 5,
    ) -> None:
        """初始化聚类服务。

        Args:
            session_factory: Postgres 异步会话工厂。
            embedder: BGE-m3 嵌入模型。
            n_clusters: 固定聚类数。None 时自动取 sqrt(n/2)。
            max_samples: 每个聚类保留的示例问题数。
        """
        self._factory = session_factory
        self._embedder = embedder
        self._n_clusters = n_clusters
        self._max_samples = max_samples

    async def cluster(
        self,
        cluster_type: str,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[ClusterResult]:
        """执行聚类并存储结果。

        Args:
            cluster_type: 'gap'(仅未回答)或 'top'(全部)。
            date_from: 时间范围开始(可选)。
            date_to: 时间范围结束(可选)。

        Returns:
            聚类结果列表,按 question_count 降序。
        """
        questions = await self._fetch_questions(cluster_type, date_from, date_to)
        if len(questions) < 2:
            return []

        embeddings = self._embed([q[1] for q in questions])
        k = self._determine_k(len(questions))
        labels = self._kmeans(embeddings, k)

        results = self._build_clusters(questions, embeddings, labels, cluster_type)
        await self._persist(results, labels, questions, cluster_type, date_from, date_to)

        return sorted(results, key=lambda r: r.question_count, reverse=True)

    async def _fetch_questions(
        self,
        cluster_type: str,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> list[tuple[UUID, str]]:
        """从 DB 查询问题列表。"""
        async with self._factory() as session:
            q = select(Conversation.id, Conversation.question)
            if cluster_type == "gap":
                q = q.where(Conversation.is_answered.is_(False))
            if date_from:
                q = q.where(Conversation.created_at >= date_from)
            if date_to:
                q = q.where(Conversation.created_at <= date_to)
            result = await session.execute(q)
            return [(row.id, row.question) for row in result.all()]

    def _embed(self, texts: list[str]) -> np.ndarray:
        """批量计算 embedding 并 L2 归一化。"""
        vectors = self._embedder.embed(texts)
        matrix = np.array(vectors, dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return matrix / norms

    def _determine_k(self, n: int) -> int:
        """自动确定聚类数:sqrt(n/2),范围 [1, 20]。"""
        if self._n_clusters is not None:
            return min(self._n_clusters, n)
        return max(1, min(20, int(math.sqrt(n / 2))))

    def _kmeans(self, embeddings: np.ndarray, k: int) -> np.ndarray:
        """执行 K-Means 聚类,返回标签数组。"""
        from sklearn.cluster import KMeans

        kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
        return kmeans.fit_predict(embeddings)

    def _build_clusters(
        self,
        questions: list[tuple[UUID, str]],
        embeddings: np.ndarray,
        labels: np.ndarray,
        cluster_type: str,
    ) -> list[ClusterResult]:
        """根据 K-Means 标签构建聚类结果。"""
        results: list[ClusterResult] = []
        for cluster_idx in range(labels.max() + 1):
            mask = labels == cluster_idx
            indices = np.where(mask)[0]
            if len(indices) == 0:
                continue

            cluster_embeddings = embeddings[indices]
            centroid = cluster_embeddings.mean(axis=0)
            distances = np.linalg.norm(cluster_embeddings - centroid, axis=1)
            representative_idx = indices[np.argmin(distances)]

            sample_indices = indices[np.argsort(distances)[: self._max_samples]]
            sample_questions = [questions[i][1] for i in sample_indices]

            results.append(
                ClusterResult(
                    cluster_id=uuid.uuid4(),
                    cluster_type=cluster_type,
                    representative_question=questions[representative_idx][1],
                    sample_questions=sample_questions,
                    question_count=len(indices),
                )
            )
        return results

    async def _persist(
        self,
        results: list[ClusterResult],
        labels: np.ndarray,
        questions: list[tuple[UUID, str]],
        cluster_type: str,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> None:
        """存储聚类结果到 DB 并更新 conversations.cluster_id。"""
        async with self._factory() as session:
            await session.execute(
                delete(QuestionCluster).where(QuestionCluster.cluster_type == cluster_type)
            )

            cluster_db_ids: list[tuple[UUID, int]] = []
            for cluster_idx, result in enumerate(results):
                db_cluster = QuestionCluster(
                    cluster_type=cluster_type,
                    representative_question=result.representative_question,
                    sample_questions=result.sample_questions,
                    question_count=result.question_count,
                    status="open",
                    period_start=date_from,
                    period_end=date_to,
                )
                session.add(db_cluster)
                await session.flush()
                cluster_db_ids.append((db_cluster.id, cluster_idx))

            for conv_idx, (conv_id, _) in enumerate(questions):
                label = int(labels[conv_idx])
                db_id = next(cid for cid, cidx in cluster_db_ids if cidx == label)
                await session.execute(
                    update(Conversation)
                    .where(Conversation.id == conv_id)
                    .values(cluster_id=str(db_id))
                )

            await session.commit()
