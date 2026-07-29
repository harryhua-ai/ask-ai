"""BudgetLimiter 单元测试。"""

from datetime import date

import pytest

from backend.utils.budget import BudgetConfig, BudgetLimiter


@pytest.mark.unit
def test_allows_within_budget() -> None:
    lim = BudgetLimiter(BudgetConfig(daily_request_limit=5, daily_token_limit=1_000_000))
    assert lim.check_and_reserve(estimated_tokens=100) is True
    assert lim.snapshot()["requests"] == 1


@pytest.mark.unit
def test_blocks_when_request_limit_hit() -> None:
    lim = BudgetLimiter(BudgetConfig(daily_request_limit=2, daily_token_limit=1_000_000))
    lim.check_and_reserve(10)
    lim.check_and_reserve(10)
    assert lim.check_and_reserve(10) is False


@pytest.mark.unit
def test_blocks_when_token_limit_hit() -> None:
    lim = BudgetLimiter(BudgetConfig(daily_request_limit=100, daily_token_limit=100))
    assert lim.check_and_reserve(60) is True
    assert lim.check_and_reserve(50) is False  # 60+50 > 100


@pytest.mark.unit
def test_resets_on_new_day() -> None:
    today = {"d": date(2026, 7, 28)}
    lim = BudgetLimiter(
        BudgetConfig(daily_request_limit=1, daily_token_limit=1_000_000),
        _now=lambda: today["d"],
    )
    assert lim.check_and_reserve(10) is True
    assert lim.check_and_reserve(10) is False
    today["d"] = date(2026, 7, 29)  # 跨天
    assert lim.check_and_reserve(10) is True  # 计数重置
