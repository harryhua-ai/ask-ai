"""P1 在服代检索过滤门测试(generation_filter_provider 接缝;fail-closed 契约)。

冻结契约(Role A REVIEW FIX):
- provider None → legacy 兼容:不加生成过滤(未迁移部署零回归);
- provider 返回非空 ordinals → 严格过滤至这些在服代;
- provider 返回 [] → 权威服务集为空 → **零检索结果**(不发检索请求);
- provider 抛错 → 权威不可得 → **FAIL CLOSED**(异常向上传播,绝不执行
  无限制检索——已撤代/墓碑对象在 GC 前物理残留,无限制检索会复活非现役
  知识;显式异常优于空结果:把基础设施故障暴露给调用方既有错误路径,
  与 Weaviate 失败语义同类)。

三路径(search / search_symbols / search_bucket)同契约;
其余检索/排序语义不变。
"""

from unittest.mock import MagicMock

import numpy as np
import pytest

from backend.retrieval.search import HybridSearcher

SENTINEL = object()


class _Wired:
    """打桩容器:_generation_ordinal_filter → SENTINEL 并记录;检索原语可观测。"""

    def __init__(self):
        self.calls: list[list[int]] = []
        self.client = MagicMock()
        self.collection = MagicMock()
        self.client.collections.get.return_value = self.collection
        self.collection.query.hybrid.return_value = MagicMock(objects=[])
        self.collection.query.bm25.return_value = MagicMock(objects=[])
        self.embedder = MagicMock()
        self.embedder.dimension = 8
        self.embedder.embed.return_value = [np.array([0.1] * 8)]


@pytest.fixture()
def wired(monkeypatch):
    w = _Wired()

    def _fake_filter(ordinals):
        w.calls.append(list(ordinals))
        return SENTINEL

    monkeypatch.setattr("backend.retrieval.search._generation_ordinal_filter", _fake_filter)
    return w


def _retrieval_called(collection) -> bool:
    """检索原语(hybrid/bm25)是否被调用。"""
    return collection.query.hybrid.called or collection.query.bm25.called


def _assert_sentinel_injected(w):
    """SENTINEL 已进入 hybrid/bm25 的 filters(单独或 all_of 组合)。"""
    for q in (w.collection.query.hybrid, w.collection.query.bm25):
        if q.called:
            f = q.call_args.kwargs.get("filters")
            assert f is not None, "预期注入生成过滤,实际 filters 缺失"
            return
    raise AssertionError("检索原语未被调用,无法断言过滤注入")


# --------------------------------------------------------------------------- #
# 1) provider None → legacy 兼容(零回归)
# --------------------------------------------------------------------------- #


def test_no_provider_preserves_legacy_behavior(wired):
    """provider 缺省(未迁移部署)→ 三路径均不加生成过滤,检索照常。"""
    w = wired
    s = HybridSearcher(w.client, w.embedder)
    assert s.search("NE503 功耗") == []
    assert s.search_symbols("BatteryReadI2C") == []
    assert s.search_bucket("功耗", source_types=["filesystem"]) == []
    assert w.calls == []
    assert _retrieval_called(w.collection)


# --------------------------------------------------------------------------- #
# 2) 非空在服代集 → 严格过滤
# --------------------------------------------------------------------------- #


def test_non_empty_active_set_filters_search(wired):
    w = wired
    s = HybridSearcher(w.client, w.embedder, generation_filter_provider=lambda: [3])
    s.search("NE503 功耗")
    assert w.calls == [[3]]
    _assert_sentinel_injected(w)


def test_non_empty_active_set_filters_symbols(wired):
    w = wired
    s = HybridSearcher(w.client, w.embedder, generation_filter_provider=lambda: [3])
    s.search_symbols("BatteryReadI2C")
    assert w.calls == [[3]]
    _assert_sentinel_injected(w)


def test_non_empty_active_set_filters_bucket(wired):
    w = wired
    s = HybridSearcher(w.client, w.embedder, generation_filter_provider=lambda: [3, 4])
    s.search_bucket("功耗", source_types=["filesystem"])
    assert w.calls == [[3, 4]]
    _assert_sentinel_injected(w)


# --------------------------------------------------------------------------- #
# 3) 空权威服务集 → 零检索结果(绝不发检索请求)
# --------------------------------------------------------------------------- #


def test_empty_active_set_returns_no_results_search(wired):
    """[] = 权威「无现役知识」:返回 [] 且不调用 embed / Weaviate(空 contains_any
    不可构造,无过滤即无限制检索 → 会复活 GC 前残留的已撤代对象,禁止)。"""
    w = wired
    s = HybridSearcher(w.client, w.embedder, generation_filter_provider=list)
    assert s.search("NE503 功耗") == []
    assert w.embedder.embed.called is False  # 权威已裁决,无需嵌入
    assert _retrieval_called(w.collection) is False


def test_empty_active_set_returns_no_results_symbols(wired):
    w = wired
    s = HybridSearcher(w.client, w.embedder, generation_filter_provider=list)
    assert s.search_symbols("BatteryReadI2C") == []
    assert _retrieval_called(w.collection) is False


def test_empty_active_set_returns_no_results_bucket(wired):
    w = wired
    s = HybridSearcher(w.client, w.embedder, generation_filter_provider=list)
    assert s.search_bucket("功耗", source_types=["filesystem"]) == []
    assert _retrieval_called(w.collection) is False


# --------------------------------------------------------------------------- #
# 4) provider 失败 → FAIL CLOSED(绝不无限制检索)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "invoke",
    [
        lambda s: s.search("NE503 功耗"),
        lambda s: s.search_symbols("BatteryReadI2C"),
        lambda s: s.search_bucket("功耗", source_types=["filesystem"]),
    ],
    ids=["search", "symbols", "bucket"],
)
def test_provider_failure_fails_closed_all_paths(wired, invoke):
    """provider 抛错 → 异常向上传播(fail-closed);embed/检索均不发生。"""

    def _boom():
        raise RuntimeError("pg authority unavailable")

    w = wired
    s = HybridSearcher(w.client, w.embedder, generation_filter_provider=_boom)
    with pytest.raises(RuntimeError, match="pg authority unavailable"):
        invoke(s)
    assert w.embedder.embed.called is False
    assert _retrieval_called(w.collection) is False


# --------------------------------------------------------------------------- #
# 5) 其余检索/排序语义不变
# --------------------------------------------------------------------------- #


def test_withdrawn_objects_never_served_via_injected_filter(wired):
    """注入链路正交性:过滤由 Weaviate 执行;结果透传语义不变。"""
    obj_old = MagicMock()  # 旧代对象(物理残留;线上由 INT 过滤排除)
    obj_old.properties = {
        "text": "stale",
        "source_id": "d/1",
        "source_type": "github",
        "product": "p",
        "title": "t",
        "url": "u",
        "chunk_index": 0,
    }
    obj_old.metadata = MagicMock(distance=0.1)
    w = wired
    w.collection.query.hybrid.return_value = MagicMock(objects=[obj_old])

    s = HybridSearcher(w.client, w.embedder, generation_filter_provider=lambda: [9])
    results = s.search("NE503 功耗")
    assert w.calls == [[9]]
    _assert_sentinel_injected(w)
    assert [r.text for r in results] == ["stale"]


def test_multi_generation_coexistence_uses_contains_any(wired):
    """双代共存过渡期:多在服代序 → contains_any 组合注入(search 路径)。"""
    w = wired
    s = HybridSearcher(w.client, w.embedder, generation_filter_provider=lambda: [3, 4])
    s.search("NE503 功耗")
    assert w.calls == [[3, 4]]
    _assert_sentinel_injected(w)
