"""⑫ /sync-health 五维健康派生:纯函数矩阵(无 DB)。

冻结断言(Frozen Discovery §11):
- Freshness 阈值 = 2 × sync_interval;enabled 且从未成功 → stale(不猜 healthy);
- missing 与 extra/orphan 是不同事实,分别呈现;
- EXCLUDED 最权威(overlay 不可改写);RECOVERING 是 active-run overlay;
- unknown 维度不参与 worst-of(缺证据 ≠ 不健康);
- expected_state:config 显式覆盖 > enabled→REQUIRED / disabled→EXCLUDED。
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from backend.api.admin.sync_runs import (
    _connectivity_dim,
    _consistency_dim,
    _expected_state_of,
    _freshness_dim,
    _overall_health,
    _parse_interval_seconds,
    _sync_dim,
)
from backend.db.models import DataSource, SyncRun

NOW = datetime.now(UTC)


def test_1_interval_parsing():
    assert _parse_interval_seconds("1h") == 3600.0
    assert _parse_interval_seconds("30m") == 1800.0
    assert _parse_interval_seconds("24h") == 86400.0
    assert _parse_interval_seconds("abc") is None
    assert _parse_interval_seconds(None) is None
    assert _parse_interval_seconds("") is None


def _run(status="completed", stage=None, consistency=None, **kw):
    return SyncRun(
        source_id=kw.pop("source_id", "s"),
        status=status,
        stage=stage,
        consistency=consistency,
        **kw,
    )


def test_2_connectivity_from_failure_phase():
    assert _connectivity_dim(None).state == "unknown"
    failed_at_fetch = _run(status="failed", stage="FETCH")
    assert _connectivity_dim(failed_at_fetch).state == "failed"
    failed_at_parse = _run(status="failed", stage="PARSE")
    assert _connectivity_dim(failed_at_parse).state == "degraded"
    # 资源/内容期失败不属于 Connectivity 维度(由 Sync/设备遥测承载)
    failed_at_embed = _run(status="failed", stage="EMBED")
    assert _connectivity_dim(failed_at_embed).state == "ok"
    completed = _run(status="completed", stage="DONE")
    assert _connectivity_dim(completed).state == "ok"


def test_3_sync_dim_window_semantics():
    rows = [SimpleNamespace(status="success", started_at=NOW)] * 3
    assert _sync_dim(rows, 30).state == "healthy"
    mixed = [SimpleNamespace(status="success", started_at=NOW)] * 2 + [
        SimpleNamespace(status="failed", started_at=NOW)
    ]
    assert _sync_dim(mixed, 30).state == "degraded"
    mostly_failed = [SimpleNamespace(status="failed", started_at=NOW)] * 2 + [
        SimpleNamespace(status="success", started_at=NOW)
    ]
    assert _sync_dim(mostly_failed, 30).state == "critical"
    assert _sync_dim(rows[:1], 30).state == "insufficient_data"  # <3 次不猜


def test_4_freshness_threshold_is_two_intervals():
    dim = _freshness_dim(False, "1h", None, NOW)
    assert dim.state == "unknown"  # 禁用源 EXCLUDED,维度不猜
    never = _freshness_dim(True, "1h", None, NOW)
    assert never.state == "stale"  # enabled 且从未成功 → stale
    recent = _freshness_dim(True, "1h", NOW - timedelta(minutes=90), NOW)
    assert recent.state == "fresh"  # 1.5h < 2×1h
    stale = _freshness_dim(True, "1h", NOW - timedelta(hours=3), NOW)
    assert stale.state == "stale"  # 3h > 2×1h
    # 解析失败 → 默认 24h 阈值(2×24h=48h);10h < 48h → fresh
    fallback = _freshness_dim(True, "bogus", NOW - timedelta(hours=10), NOW)
    assert fallback.state == "fresh"


def test_5_consistency_missing_and_orphan_distinct():
    assert _consistency_dim(None).state == "unknown"
    failed_verify = _run(consistency={"verification_failed": "weaviate down"})
    dim = _consistency_dim(failed_verify)
    assert dim.state == "unknown"
    missing_only = _run(consistency={"missing": 3, "orphan_count": 0})
    dim = _consistency_dim(missing_only)
    assert dim.state == "degraded" and "missing=3" in dim.evidence
    orphan_only = _run(consistency={"missing": 0, "orphan_count": 4})
    dim = _consistency_dim(orphan_only)
    assert dim.state == "degraded" and "extra_orphan=4" in dim.evidence
    both = _run(consistency={"missing": 1, "orphan_count": 2})
    dim = _consistency_dim(both)
    assert "missing=1" in dim.evidence and "extra_orphan=2" in dim.evidence
    healthy = _run(consistency={"missing": 0, "orphan_count": 0})
    assert _consistency_dim(healthy).state == "ok"


def test_6_expected_state_resolution():
    assert (
        _expected_state_of(DataSource(id="a", type="github", product="p", enabled=True, config={}))
        == "REQUIRED"
    )
    assert (
        _expected_state_of(DataSource(id="a", type="github", product="p", enabled=False, config={}))
        == "EXCLUDED"
    )
    assert (
        _expected_state_of(
            DataSource(
                id="a",
                type="github",
                product="p",
                enabled=True,
                config={"expected_state": "OPTIONAL"},
            )
        )
        == "OPTIONAL"
    )
    # 非法值忽略,回退默认
    assert (
        _expected_state_of(
            DataSource(
                id="a", type="github", product="p", enabled=True, config={"expected_state": "MAYBE"}
            )
        )
        == "REQUIRED"
    )


def test_7_overall_aggregation_matrix():
    base = dict(
        expected_state="REQUIRED",
        recovering=False,
        document_count=10,
        has_success=True,
        connectivity="ok",
        sync_state="healthy",
        coverage="ok",
        freshness="fresh",
        consistency="ok",
    )
    assert _overall_health(**base) == "HEALTHY"
    # EXCLUDED 最权威:任何 overlay 不可改写
    assert (
        _overall_health(**{**base, "expected_state": "EXCLUDED", "recovering": True}) == "EXCLUDED"
    )
    # RECOVERING overlay 优先于维度色(旧成功不掩盖在途恢复)
    assert _overall_health(**{**base, "recovering": True}) == "RECOVERING"
    # EMPTY_*
    assert (
        _overall_health(**{**base, "document_count": 0, "has_success": False}) == "EMPTY_UNEXPECTED"
    )
    assert (
        _overall_health(**{**base, "expected_state": "OPTIONAL", "document_count": 0})
        == "EMPTY_EXPECTED"
    )
    # worst-of 有序:ACTION_REQUIRED > STALE > DEGRADED > PARTIAL
    assert _overall_health(**{**base, "connectivity": "failed"}) == "ACTION_REQUIRED"
    assert _overall_health(**{**base, "consistency": "degraded"}) == "ACTION_REQUIRED"
    assert _overall_health(**{**base, "sync_state": "critical"}) == "ACTION_REQUIRED"
    assert _overall_health(**{**base, "freshness": "stale"}) == "STALE"
    assert _overall_health(**{**base, "sync_state": "degraded"}) == "DEGRADED"
    assert _overall_health(**{**base, "coverage": "partial"}) == "PARTIAL"
    # unknown 维度不拖低;仅证据不足时 INSUFFICIENT_DATA
    unknown = {**base, "connectivity": "unknown", "coverage": "unknown", "consistency": "unknown"}
    assert _overall_health(**unknown) == "HEALTHY"
    assert (
        _overall_health(**{**base, "sync_state": "insufficient_data", "freshness": "fresh"})
        == "INSUFFICIENT_DATA"
    )
