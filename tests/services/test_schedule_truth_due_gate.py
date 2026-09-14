"""#62 调度 due gate 与成功/失败推进契约测试。"""

from datetime import UTC, datetime, timedelta


def test_due_gate_uses_persisted_next_run_at():
    from backend.services.schedule_truth import is_due

    now = datetime(2026, 9, 14, 10, 0, tzinfo=UTC)
    assert is_due(None, now) is True  # waiting_first:首次调度可执行
    assert is_due(now - timedelta(seconds=1), now) is True
    assert is_due(now + timedelta(seconds=1), now) is False


def test_failed_sync_does_not_advance_last_success_schedule():
    from backend.services.schedule_truth import compute_next_run_at

    finished = datetime(2026, 9, 14, 0, 0, tzinfo=UTC)
    assert compute_next_run_at(
        enabled=True,
        lifecycle_state=None,
        has_inflight=False,
        last_finished_at=finished,
        interval_seconds=24 * 3600,
    ) == finished + timedelta(hours=24)


def test_manual_trigger_can_bypass_due_gate():
    from backend.services.schedule_truth import should_run_source

    now = datetime(2026, 9, 14, 10, 0, tzinfo=UTC)
    future = now + timedelta(hours=12)
    assert should_run_source(next_run_at=future, now=now, triggered_by="cron") is False
    assert should_run_source(next_run_at=future, now=now, triggered_by="manual") is True
