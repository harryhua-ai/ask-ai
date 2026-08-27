"""sync._sync_one 无变更跳过分支的自愈逻辑单元测试(patch 隔离)。"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.db.models import SyncLog
from scripts.sync import _sync_one


def _make_cfg(source_id: str = "src") -> MagicMock:
    cfg = MagicMock()
    cfg.id = source_id
    cfg.type = "local_git"
    return cfg


def _make_pipeline() -> MagicMock:
    pipeline = MagicMock()
    pipeline.ingest_all.return_value = {"doc-a": 3}
    return pipeline


@pytest.mark.asyncio
@patch("scripts.sync._count_documents", new_callable=AsyncMock)
@patch("scripts.sync._last_success_at", new_callable=AsyncMock)
@patch("scripts.sync.verify_source_vectors", new_callable=AsyncMock)
@patch("scripts.sync.ConnectorRegistry.create")
async def test_no_change_but_vector_gap_triggers_heal_and_partial(
    mock_create, mock_verify, mock_last_success, mock_count
):
    """无变更 + 一致性校验发现缺口 → fetch_all 过滤缺口补灌,记 partial。"""
    mock_last_success.return_value = datetime(2026, 8, 18, 15, 39, tzinfo=UTC)
    mock_count.return_value = 500           # documents 已有记录(非首次)
    from backend.services.vector_consistency import VectorGapReport
    mock_verify.return_value = VectorGapReport(
        expected_chunks=500, actual_chunks=480, missing_source_ids=["doc-a"]
    )

    connector = MagicMock()
    # fetch_changes 空(无变更);fetch_all 返回缺口文档
    connector.fetch_changes.return_value = iter([])
    from backend.connectors.base import RawDocument
    connector.fetch_all.return_value = iter([
        RawDocument(
            source_id="doc-a", source_type="github", product="x",
            title="a", content="A", url="http://a", metadata={},
            content_hash="h1",
        ),
        RawDocument(  # 非缺口文档,应被过滤掉
            source_id="doc-keep", source_type="github", product="x",
            title="b", content="B", url="http://b", metadata={},
            content_hash="h2",
        ),
    ])
    connector.fetch_deleted.return_value = []
    mock_create.return_value = connector

    pipeline = _make_pipeline()
    session_factory = MagicMock()
    session_factory.return_value.__aenter__.return_value.commit = AsyncMock()
    pipeline._session_factory = None

    await _sync_one(_make_cfg(), pipeline, session_factory, triggered_by="manual")

    # 只对缺口文档重灌(非缺口被过滤)
    called_docs = pipeline.ingest_all.call_args[0][0]
    assert [d.source_id for d in called_docs] == ["doc-a"]
    # SyncLog 写入 partial + error_detail
    written = session_factory.return_value.__aenter__.return_value.add.call_args[0][0]
    assert isinstance(written, SyncLog)
    assert written.status == "partial"
    assert "缺口" in (written.error_detail or "")


@pytest.mark.asyncio
@patch("scripts.sync._count_documents", new_callable=AsyncMock)
@patch("scripts.sync._last_success_at", new_callable=AsyncMock)
@patch("scripts.sync.verify_source_vectors", new_callable=AsyncMock)
@patch("scripts.sync.ConnectorRegistry.create")
async def test_no_change_and_healthy_keeps_success_skip(
    mock_create, mock_verify, mock_last_success, mock_count
):
    """无变更 + 校验健康 → 维持 success + unchanged,不触发 fetch_all。"""
    mock_last_success.return_value = datetime(2026, 8, 18, 15, 39, tzinfo=UTC)
    mock_count.return_value = 500
    from backend.services.vector_consistency import VectorGapReport
    mock_verify.return_value = VectorGapReport(
        expected_chunks=500, actual_chunks=500, missing_source_ids=[]
    )

    connector = MagicMock()
    connector.fetch_changes.return_value = iter([])
    connector.fetch_all.return_value = iter([])  # 不应被调用
    connector.fetch_deleted.return_value = []
    mock_create.return_value = connector

    pipeline = _make_pipeline()
    session_factory = MagicMock()
    session_factory.return_value.__aenter__.return_value.commit = AsyncMock()

    await _sync_one(_make_cfg(), pipeline, session_factory, triggered_by="manual")

    assert not pipeline.ingest_all.called
    written = session_factory.return_value.__aenter__.return_value.add.call_args[0][0]
    assert written.status == "success"
    assert written.items_unchanged == 500
