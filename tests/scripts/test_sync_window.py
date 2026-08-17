"""sync.py 增量窗口计算单元测试(纯函数,无 DB / 无外部依赖)。

窗口语义(2026-08-17 改造):``since`` 优先取 sync_log 中该源最近一次
成功同步的 finished_at,使窗口精确覆盖上次成功以来的变更;无成功记录
时保守回看 24h;过旧(超过 MAX_INCREMENTAL_LOOKBACK)或未来时间
(时钟漂移)分别被上限 / now 夹紧。
"""

from datetime import UTC, datetime, timedelta

import pytest

from scripts.sync import (
    DEFAULT_INCREMENTAL_WINDOW,
    MAX_INCREMENTAL_LOOKBACK,
    _compute_since,
)


@pytest.mark.unit
def test_no_last_success_falls_back_to_default_window():
    """无成功记录(首次运行)→ 保守回看默认窗口(24h,保持旧行为)。"""
    now = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    since = _compute_since(None, now)
    assert since == now - DEFAULT_INCREMENTAL_WINDOW


@pytest.mark.unit
def test_recent_last_success_used_directly():
    """最近一次成功在回看上限内 → 窗口起点即该时间(精确覆盖缺口)。"""
    now = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    last_success = now - timedelta(hours=5)
    assert _compute_since(last_success, now) == last_success


@pytest.mark.unit
def test_stale_last_success_capped_at_lookback():
    """上次成功太久远(源长期停摆/同步长期失败)→ 窗口被上限夹住,防无界拉取。"""
    now = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    last_success = now - timedelta(days=90)
    assert _compute_since(last_success, now) == now - MAX_INCREMENTAL_LOOKBACK


@pytest.mark.unit
def test_future_last_success_clamped_to_now():
    """上次成功时间在未来(时钟漂移)→ 夹回 now,避免窗口为空区间。"""
    now = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    last_success = now + timedelta(hours=2)
    assert _compute_since(last_success, now) == now
