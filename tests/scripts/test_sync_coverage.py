"""WEB 覆盖任务:sync 层覆盖度真实性 + 孤儿漂移自愈单元测试(patch 隔离)。

契约锚点:
- WEB-G006:单页失败可观测,不得静默伪装成完整成功(SyncLog 记 coverage 行);
- WEB-G007/合同#7:覆盖不完整(<80%)记 partial,绝不记成功;
- 合同#7:一致性缺口必须修因(孤儿漂移全量重灌自愈),不是只发警告。
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.db.models import SyncLog
from scripts.sync import _handle_no_change, _sync_one


def _make_cfg(source_id: str = "website-x") -> MagicMock:
    cfg = MagicMock()
    cfg.id = source_id
    cfg.type = "web_crawl"
    return cfg


def _make_pipeline(chunks: int = 1) -> MagicMock:
    pipeline = MagicMock()
    pipeline.ingest_all.return_value = {f"doc-{i}": chunks for i in range(8)}
    return pipeline


def _connector_with_stats(stats: dict | None) -> MagicMock:
    connector = MagicMock()
    connector.fetch_changes.return_value = iter([])
    connector.fetch_all.return_value = iter([])
    connector.fetch_deleted.return_value = []
    if stats is not None:
        connector.run_stats = stats
    else:
        del connector.run_stats  # MagicMock 默认属性被删 → getattr 返回 None
    return connector


def _commit_capture():
    """构造 session_factory 捕获最终 SyncLog。"""
    saved: dict = {}

    factory = MagicMock()

    class _Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def add(self, obj):
            saved["log"] = obj

        async def commit(self):
            saved["committed"] = True

        async def execute(self, *a, **k):
            return MagicMock()

    factory.return_value = _Session()
    return saved, factory


@pytest.mark.asyncio
async def test_full_crawl_success_records_coverage_line():
    """WEB-G006:覆盖健康(8/9 抽取)→ success,但 error_detail 必须携带 coverage 行。"""
    stats = {
        "full": True,
        "discovered": 12,
        "accepted": 9,
        "extracted": 8,
        "failed": 1,
        "failed_urls": ["https://x/404/"],
        "rejected": {"low_content": 0, "robots": 0, "exclude": 3},
    }
    connector = _connector_with_stats(stats)
    connector.fetch_changes.return_value = iter([])
    docs = [MagicMock() for _ in range(8)]
    connector.fetch_all.return_value = iter(docs)
    pipeline = _make_pipeline()
    pipeline.ingest_all.return_value = {f"d{i}": 3 for i in range(8)}

    log = await _run_sync_one(connector, pipeline, MagicMock())

    assert log is not None
    assert log.status == "success"
    assert "coverage:" in (log.error_detail or "")
    assert "discovered=12" in log.error_detail
    assert "extracted=8" in log.error_detail
    assert "failed=1" in log.error_detail


async def _run_sync_one(connector, pipeline, factory):
    with patch("scripts.sync._count_documents", new_callable=AsyncMock) as mc, patch(
        "scripts.sync._last_success_at", new_callable=AsyncMock
    ) as ml, patch("scripts.sync.ConnectorRegistry.create") as mcr:
        mc.return_value = 0  # 首次同步(existing=0)→ fetch_all 路径
        ml.return_value = None
        mcr.return_value = connector
        saved_holder = {}

        # 捕获 finally 写库的 log_entry:用包装 session_factory
        class _Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            def add(self, obj):
                saved_holder["log"] = obj

            async def commit(self):
                saved_holder["committed"] = True

        factory2 = MagicMock()
        factory2.return_value = _Session()
        await _sync_one(_make_cfg(), pipeline, factory2)
        return saved_holder.get("log")


@pytest.mark.asyncio
async def test_full_crawl_low_coverage_is_partial_not_success():
    """覆盖 <80%(3/10 抽取)→ partial + coverage 行,不得记成功(合同#6/#7)。"""
    stats = {
        "full": True,
        "discovered": 14,
        "accepted": 10,
        "extracted": 3,
        "failed": 4,
        "failed_urls": ["u1", "u2", "u3", "u4"],
        "rejected": {"low_content": 3, "robots": 0, "exclude": 1},
    }
    connector = _connector_with_stats(stats)
    docs = [MagicMock() for _ in range(3)]
    connector.fetch_all.return_value = iter(docs)
    pipeline = _make_pipeline()
    pipeline.ingest_all.return_value = {f"d{i}": 2 for i in range(3)}

    log = await _run_sync_one(connector, pipeline, MagicMock())
    assert log is not None
    assert log.status == "partial"
    assert "coverage:" in (log.error_detail or "")
    assert "extracted=3" in log.error_detail


@pytest.mark.asyncio
async def test_full_crawl_all_pages_failed_is_failed_status():
    """全军覆没(0 抽取)→ failed,不得伪装任何成功形态。"""
    stats = {
        "full": True,
        "discovered": 10,
        "accepted": 10,
        "extracted": 0,
        "failed": 10,
        "failed_urls": ["u"] * 10,
        "rejected": {},
    }
    connector = _connector_with_stats(stats)
    connector.fetch_all.return_value = iter([])
    pipeline = _make_pipeline()

    log = await _run_sync_one(connector, pipeline, MagicMock())
    assert log is not None
    assert log.status == "failed"
    assert "coverage:" in (log.error_detail or "")


@pytest.mark.asyncio
async def test_connector_without_stats_keeps_legacy_semantics():
    """无 run_stats 的连接器(git/fs/woo)不受影响:无 coverage 行,状态语义不变。"""
    connector = _connector_with_stats(None)
    docs = [MagicMock() for _ in range(2)]
    connector.fetch_all.return_value = iter(docs)
    pipeline = _make_pipeline()
    pipeline.ingest_all.return_value = {"a": 1, "b": 2}

    log = await _run_sync_one(connector, pipeline, MagicMock())
    assert log is not None
    assert log.status == "success"
    assert "coverage:" not in (log.error_detail or "")


@pytest.mark.asyncio
@patch("scripts.sync.ConnectorRegistry.create")
async def test_no_change_orphan_only_drift_self_heals_via_full_reingest(mock_create):
    """孤儿漂移(refill 空、orphan>0)→ 全量重灌自愈恢复账本,记 partial+自愈描述。

    修复前行为:「重灌清单为空,未自动补齐,需人工核查」永久循环——警告被
    记录但成因永不修复;本用例锁定修因语义(WEB 合同#7)。
    """
    from backend.services.vector_consistency import VectorGapReport

    report = VectorGapReport(
        expected_chunks=2,
        actual_chunks=821,
        missing_source_ids=[],
        refill_source_ids=[],
        orphan_count=76,
    )
    connector = _connector_with_stats(None)
    docs = [MagicMock() for _ in range(8)]
    connector.fetch_all.return_value = iter(docs)
    connector.fetch_deleted.return_value = []
    mock_create.return_value = connector
    pipeline = _make_pipeline()
    pipeline.ingest_all.return_value = {f"d{i}": 3 for i in range(8)}

    saved, factory = _commit_capture()
    log_entry = SyncLog(source_id="website-x", source_type="web_crawl", status="success")
    started = datetime.now(UTC)

    with patch("scripts.sync.verify_source_vectors", new_callable=AsyncMock) as mv:
        mv.return_value = report
        await _handle_no_change(
            "website-x",
            2,
            connector,
            pipeline,
            factory,
            log_entry,
            start=0.0,
        )

    assert log_entry.status == "partial"
    assert pipeline.ingest_all.called
    assert connector.fetch_all.called  # 自愈必须全量重灌
    assert "自愈" in (log_entry.error_detail or "")
    assert "76" in (log_entry.error_detail or "")
