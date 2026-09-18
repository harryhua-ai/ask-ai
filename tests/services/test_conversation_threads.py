"""#87:Thread 确定性边界算法单元测试(纯函数,无 DB)。

冻结语义(CONVERSATION-REVIEW-PRODUCT-UI-CONTRACT-20260917 §Thread boundary):
- 同 session_id + 同 site/Entry(存在时)+ 兼容 transport + 不活动间隔 <=30min
  + 无显式 reset ⇒ 同一 Thread;
- >30min 间隔、site/Entry 变化、transport 变化 ⇒ 分裂;
- 仅跨零点不分裂;session_id 缺失的历史行 = 诚实 singleton,不猜测归组。
"""

from datetime import datetime, timedelta, timezone

from backend.services.conversation_threads import build_threads

_T0 = datetime(2026, 9, 18, 10, 0, 0, tzinfo=timezone.utc)


class Turn:
    """轻量行仿真(与 API 层传参字段对齐)。"""

    def __init__(self, id, created_at, session_id=None, site_id=None, channel="widget"):
        self.id = id
        self.created_at = created_at
        self.session_id = session_id
        self.site_id = site_id
        self.channel = channel


def test_same_session_within_gap_groups_into_one_thread():
    rows = [
        Turn("t1", _T0, session_id="s1"),
        Turn("t2", _T0 + timedelta(minutes=10), session_id="s1"),
        Turn("t3", _T0 + timedelta(minutes=25), session_id="s1"),
    ]
    threads = build_threads(rows)
    assert len(threads) == 1
    assert threads[0].turn_ids == ("t1", "t2", "t3")


def test_gap_over_30_minutes_splits():
    rows = [
        Turn("t1", _T0, session_id="s1"),
        Turn("t2", _T0 + timedelta(minutes=31), session_id="s1"),
    ]
    assert len(build_threads(rows)) == 2


def test_gap_exactly_30_minutes_does_not_split():
    rows = [
        Turn("t1", _T0, session_id="s1"),
        Turn("t2", _T0 + timedelta(minutes=30), session_id="s1"),
    ]
    threads = build_threads(rows)
    assert len(threads) == 1 and threads[0].turn_ids == ("t1", "t2")


def test_midnight_alone_does_not_split():
    rows = [
        Turn("t1", datetime(2026, 9, 17, 23, 55, tzinfo=timezone.utc), session_id="s1"),
        Turn("t2", datetime(2026, 9, 18, 0, 5, tzinfo=timezone.utc), session_id="s1"),
    ]
    threads = build_threads(rows)
    assert len(threads) == 1 and threads[0].turn_ids == ("t1", "t2")


def test_site_change_splits_within_gap():
    rows = [
        Turn("t1", _T0, session_id="s1", site_id="site-a"),
        Turn("t2", _T0 + timedelta(minutes=5), session_id="s1", site_id="site-b"),
    ]
    threads = build_threads(rows)
    assert len(threads) == 2
    assert {t.site_id for t in threads} == {"site-a", "site-b"}


def test_transport_change_splits_within_gap():
    rows = [
        Turn("t1", _T0, session_id="s1", channel="widget"),
        Turn("t2", _T0 + timedelta(minutes=5), session_id="s1", channel="discord"),
    ]
    threads = build_threads(rows)
    assert len(threads) == 2


def test_legacy_rows_without_session_id_are_singletons():
    rows = [
        Turn("t1", _T0, session_id=None),
        Turn("t2", _T0 + timedelta(minutes=1), session_id=None),
    ]
    threads = build_threads(rows)
    assert len(threads) == 2
    assert {t.turn_ids for t in threads} == {("t1",), ("t2",)}


def test_same_session_id_across_different_sessions_of_origin_never_merges():
    """不同 (site,channel) 键的同名 session 各自独立成组(键隔离)。"""
    rows = [
        Turn("t1", _T0, session_id="s1", site_id="a", channel="widget"),
        Turn("t2", _T0 + timedelta(minutes=1), session_id="s1", site_id="b", channel="widget"),
        Turn("t3", _T0 + timedelta(minutes=2), session_id="s1", site_id="a", channel="discord"),
    ]
    assert len(build_threads(rows)) == 3


def test_unordered_input_is_sorted_internally():
    rows = [
        Turn("t2", _T0 + timedelta(minutes=5), session_id="s1"),
        Turn("t1", _T0, session_id="s1"),
    ]
    threads = build_threads(rows)
    assert threads[0].turn_ids == ("t1", "t2")


def test_thread_identity_is_stable_and_short():
    rows = [Turn("t1", _T0, session_id="s1")]
    a = build_threads(rows)[0]
    b = build_threads(list(rows))[0]
    assert a.thread_id == b.thread_id
    assert a.thread_id.startswith("thread_") and len(a.thread_id) <= 20
    assert a.started_at == a.last_activity_at == _T0


def test_explicit_reset_rotated_session_splits_within_gap():
    """#87 REPLAN(a):「新对话」显式轮换 session_id ⇒ reset 前后两个 Turn
    即使同 site/channel 且间隔 <=30min,也分属两个 Thread(AC2 澄清:
    Thread 重构由持久化 session_id 确定性导出,无需边界列)。"""
    rows = [
        Turn("t1", _T0, session_id="s-before", site_id="site-1", channel="widget"),
        Turn(
            "t2",
            _T0 + timedelta(minutes=10),
            session_id="s-after",
            site_id="site-1",
            channel="widget",
        ),
    ]
    threads = build_threads(rows)
    assert {t.turn_ids for t in threads} == {("t1",), ("t2",)}


def test_reset_within_same_session_does_not_split_without_rotation():
    """对照组:未轮换 session_id 时,同 site/channel + <=30min 仍是一个 Thread
    (reset 语义 = 轮换本身,不存在其它隐式分裂源)。"""
    rows = [
        Turn("t1", _T0, session_id="s1", site_id="site-1", channel="widget"),
        Turn(
            "t2",
            _T0 + timedelta(minutes=10),
            session_id="s1",
            site_id="site-1",
            channel="widget",
        ),
    ]
    threads = build_threads(rows)
    assert len(threads) == 1
    assert threads[0].turn_ids == ("t1", "t2")
