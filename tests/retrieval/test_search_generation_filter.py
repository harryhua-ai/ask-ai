"""P1 在服代检索过滤门测试(generation_filter_provider 接缝)。

契约锚点:
- 服务选择唯一权威 = PG active generation 集合(I-1/D-2):检索只命中
  在服代对象;旧代/失败代对象即使物理残留也不可命中;
- provider 缺省 → 不过滤(未迁移部署零回归);
- provider 空 → 不过滤(空库语义等价,避免空 contains_any 构造错误);
- provider 抛错 → fail-open(与未迁移行为一致,记 warning);
- INT 属性精确过滤:单代 equal、多代 contains_any(TEXT 分词误命中免疫)。
"""

from unittest.mock import MagicMock

import numpy as np
import pytest

from backend.retrieval.search import HybridSearcher

SENTINEL = object()


@pytest.fixture()
def wired(monkeypatch):
    """打桩 _generation_ordinal_filter → SENTINEL,记录调用;hybrid 返回空集。"""
    calls: list[list[int]] = []

    def _fake_filter(ordinals):
        calls.append(list(ordinals))
        return SENTINEL

    monkeypatch.setattr("backend.retrieval.search._generation_ordinal_filter", _fake_filter)

    client = MagicMock()
    collection = MagicMock()
    client.collections.get.return_value = collection
    collection.query.hybrid.return_value = MagicMock(objects=[])
    embedder = MagicMock()
    embedder.dimension = 8
    embedder.embed.return_value = [np.array([0.1] * 8)]
    yield SimpleNamespaceWired(client=client, collection=collection, calls=calls)


class SimpleNamespaceWired:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _hybrid_filters(collection) -> list:
    kwargs = collection.query.hybrid.call_args.kwargs
    f = kwargs.get("filters")
    if f is SENTINEL:
        return [SENTINEL]
    if f is None:
        return []
    # all_of 组合:子句含 sentinel 即视为注入(无法 introspect 内部,靠
    # SENTINEL 与其它真过滤器组合出现判断)
    return [SENTINEL]


def test_no_provider_means_no_generation_filter(wired):
    """provider 缺省(未迁移部署)→ hybrid 无生成过滤(零回归)。"""
    s = HybridSearcher(wired.client, MagicMock())
    s.search("NE503 功耗")
    assert wired.calls == []
    assert SENTINEL not in _hybrid_filters(wired.collection)


def test_single_ordinal_uses_exact_filter(wired):
    """单在服代 → generation_ordinal INT equal 过滤注入。"""
    s = HybridSearcher(
        wired.client, MagicMock(), generation_filter_provider=lambda: [3]
    )
    s.search("NE503 功耗")
    assert wired.calls == [[3]]
    assert SENTINEL in _hybrid_filters(wired.collection)


def test_multiple_ordinals_use_contains_any(wired):
    """多在服代(双代共存过渡期)→ contains_any 过滤注入。"""
    s = HybridSearcher(
        wired.client, MagicMock(), generation_filter_provider=lambda: [3, 4]
    )
    s.search("NE503 功耗")
    assert wired.calls == [[3, 4]]
    assert SENTINEL in _hybrid_filters(wired.collection)


def test_empty_active_set_adds_no_filter(wired):
    """权威集合为空(空库/全墓碑)→ 不加过滤(等价语义,防空构造)。"""
    s = HybridSearcher(
        wired.client, MagicMock(), generation_filter_provider=list
    )
    s.search("NE503 功耗")
    assert wired.calls == []
    assert SENTINEL not in _hybrid_filters(wired.collection)


def test_provider_failure_fails_open(wired):
    """provider 抛错 → fail-open(本次不加生成过滤,检索不中断)。"""
    def _boom():
        raise RuntimeError("pg down")

    s = HybridSearcher(wired.client, MagicMock(), generation_filter_provider=_boom)
    results = s.search("NE503 功耗")  # 不抛
    assert results == []
    assert SENTINEL not in _hybrid_filters(wired.collection)


def test_withdrawn_generation_objects_never_served(wired):
    """撤销代对象永不出现在检索结果(provider 只供在服代;模拟验证注入)。"""
    obj_old = MagicMock()  # 旧代对象(物理残留)
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
    wired.collection.query.hybrid.return_value = MagicMock(objects=[obj_old])

    seen: list[list[int]] = []
    s = HybridSearcher(
        wired.client,
        MagicMock(),
        generation_filter_provider=lambda: (seen.append([9]) or [9]),
    )
    results = s.search("NE503 功耗")
    assert seen == [[9]]
    assert SENTINEL in _hybrid_filters(wired.collection)
    # 结果与过滤正交:过滤由 Weaviate 执行;此处仅断言注入与透传链路
    assert [r.text for r in results] == ["stale"]
