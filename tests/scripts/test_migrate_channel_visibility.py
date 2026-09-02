"""migrate_channel_visibility 规划核心测试(AC-07 存量索引兼容)。

行为契约:
- 每个对象的 target = 其源 config 的 channel_visibility;config 缺失该键 → 默认
  ["widget", "api"](公开,零回归)。
- 语义等价(current 缺失视为默认公开)时跳过,不产生无谓写。
- 前缀不在 source_map 的对象(幽灵/测试 chunk)不动,单列 reported。
- only_sources 过滤时,范围外对象不参与规划。
"""

from scripts.migrate_channel_visibility import DEFAULT_VISIBILITY, compute_changes


def test_restricted_source_objects_target_internal():
    records = [
        ("knowledge-cases/a.md", ["widget", "api"]),
        ("knowledge-cases/b.md", None),
    ]
    changes, skipped, unknown = compute_changes(records, {"knowledge-cases": ["internal"]})
    assert changes == [
        ("knowledge-cases/a.md", ["internal"]),
        ("knowledge-cases/b.md", ["internal"]),
    ]
    assert skipped == [] and unknown == []


def test_public_default_applied_when_config_lacks_key():
    records = [("gh-src/readme.md", ["internal"])]
    changes, _, _ = compute_changes(records, {"gh-src": {}})
    assert changes == [("gh-src/readme.md", DEFAULT_VISIBILITY)]


def test_semantically_equal_objects_skipped():
    records = [
        ("gh-src/readme.md", ["widget", "api"]),
        ("gh-src/other.md", None),  # 缺失属性按默认公开解释 → 语义相等,跳过
    ]
    changes, skipped, _ = compute_changes(records, {"gh-src": {}})
    assert changes == []
    assert len(skipped) == 2


def test_duplicate_source_ids_yield_single_change():
    """同 source_id 多份对象(重复入库):任一不匹配 → 只产一条 change(去重)。"""
    records = [
        ("k-src/a.md", None),
        ("k-src/a.md", ["internal"]),  # 已是 internal 的孪生对象
        ("k-src/a.md", ["widget", "api"]),  # 漏更新的孪生对象
    ]
    changes, skipped, unknown = compute_changes(records, {"k-src": ["internal"]})
    assert changes == [("k-src/a.md", ["internal"])]
    assert skipped == [] and unknown == []
