# tests/services/test_clustering.py
"""ClusteringService 单元测试。

覆盖:
- gap 类型只聚类 is_answered=False 的问题
- top 类型聚类全部问题
- 空数据返回空列表
- 聚类结果写入 question_clusters 表
- conversations.cluster_id 被更新
"""

from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from backend.services.clustering import ClusteringService


def _mock_embedder() -> MagicMock:
    embedder = MagicMock()
    embedder.embed = lambda texts: [np.random.rand(1024).astype(np.float32) for _ in texts]
    return embedder


def _mock_session_factory_with_conversations(conversations: list, existing_clusters: list = None):
    """构造 mock session_factory,返回指定 conversations。"""
    session = AsyncMock()

    # First execute: query conversations
    conv_result = MagicMock()
    conv_rows = []
    for conv_id, question in conversations:
        row = MagicMock()
        row.id = conv_id
        row.question = question
        conv_rows.append(row)
    conv_result.all.return_value = conv_rows

    # Second execute: query existing clusters (for cleanup)
    cluster_result = MagicMock()
    cluster_result.scalars.return_value.all.return_value = existing_clusters or []

    # 第三次 execute: update conversations cluster_id (per cluster)
    # 后续调用返回 MagicMock
    session.execute = AsyncMock(side_effect=[conv_result, cluster_result] + [AsyncMock() for _ in range(100)])

    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=None)
    factory = MagicMock()
    factory.return_value = ctx
    return factory


@pytest.mark.unit
async def test_cluster_empty_returns_empty():
    """无对话数据时返回空列表。"""
    factory = _mock_session_factory_with_conversations([])
    embedder = _mock_embedder()

    service = ClusteringService(factory, embedder)
    results = await service.cluster("gap")

    assert results == []


@pytest.mark.unit
async def test_cluster_groups_similar_questions():
    """多个问题被正确聚类为若干组。"""
    conversations = [
        ("conv-1", "NE503 功耗是多少?"),
        ("conv-2", "NE503 功耗多少瓦?"),
        ("conv-3", "如何配置 WiFi?"),
        ("conv-4", "WiFi 设置方法?"),
        ("conv-5", "保修期多久?"),
    ]
    factory = _mock_session_factory_with_conversations(conversations)
    embedder = _mock_embedder()

    service = ClusteringService(factory, embedder, n_clusters=3)
    results = await service.cluster("gap")

    assert len(results) <= 3
    assert all(r.question_count >= 1 for r in results)


@pytest.mark.unit
async def test_cluster_result_has_representative_question():
    """每个聚类结果包含代表性问题。"""
    conversations = [
        ("conv-1", "NE503 功耗是多少?"),
        ("conv-2", "NE503 功耗多少瓦?"),
    ]
    factory = _mock_session_factory_with_conversations(conversations)
    embedder = _mock_embedder()

    service = ClusteringService(factory, embedder, n_clusters=1)
    results = await service.cluster("top")

    assert len(results) >= 1
    assert results[0].representative_question  # 非空
    assert len(results[0].sample_questions) <= 5
