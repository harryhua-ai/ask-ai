"""sync.py 触发方标记(--triggered-by)契约测试。

阶段9:manual / scheduled / CLI 收敛到同一 runner(scripts/sync.py)。
Admin 独立执行面经 CLI 显式传 --triggered-by manual,使 sync-all
(无 --source)不再被旧规则误记为 cron;默认 auto 保持旧语义不变
(sync-cron 容器无参调用 → cron;显式 --source → manual)。
"""

import pytest

from scripts.sync import _parse_args, _resolve_triggered_by


def test_resolve_auto_without_source_is_cron():
    assert _resolve_triggered_by(None, None) == "cron"


def test_resolve_auto_with_source_is_manual():
    assert _resolve_triggered_by("some-src", None) == "manual"


def test_resolve_explicit_flag_wins():
    """独立执行面显式标记优先:sync-all 经 CLI 传 manual,不因缺 --source 被记 cron。"""
    assert _resolve_triggered_by(None, "manual") == "manual"
    assert _resolve_triggered_by("some-src", "cron") == "cron"


def test_parse_args_default_is_auto():
    args = _parse_args([])
    assert args.triggered_by == "auto"
    assert args.source is None


def test_parse_args_triggered_by_manual_with_source():
    args = _parse_args(["--source", "web-x", "--triggered-by", "manual"])
    assert args.source == "web-x"
    assert args.triggered_by == "manual"


def test_parse_args_rejects_unknown_triggered_by():
    with pytest.raises(SystemExit):
        _parse_args(["--triggered-by", "yolo"])


def test_main_passes_triggered_by_to_run_sync(monkeypatch):
    """main() 把 CLI 标记透传给 run_sync(auto → None 交给旧规则)。"""
    import scripts.sync as sync_mod

    captured: dict = {}

    async def _fake_run_sync(
        settings, source_id=None, *, dry_run=False, reindex=False, triggered_by=None
    ):
        captured["source_id"] = source_id
        captured["triggered_by"] = triggered_by

    monkeypatch.setattr(sync_mod, "load_settings", lambda: object())
    monkeypatch.setattr(sync_mod, "run_sync", _fake_run_sync)

    sync_mod.main(["--source", "web-x", "--triggered-by", "manual"])
    assert captured == {"source_id": "web-x", "triggered_by": "manual"}

    sync_mod.main([])
    assert captured == {"source_id": None, "triggered_by": None}
