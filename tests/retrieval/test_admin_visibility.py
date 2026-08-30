"""admin 渠道检索可见性映射测试(P1-RES Task 1)。

契约语义:admin 为管理后台测试环境,**所见 = 访客(widget)所见**——
检索的 channel_visibility 过滤须把 admin 映射为 widget 视角;
widget / api / discord / mcp 等其他渠道行为零变化。

覆盖三处过滤点(行为必须一致):
- HybridSearcher.search(hybrid 主检索)
- HybridSearcher.search_symbols(符号 BM25)
- HybridSearcher.search_bucket(boost 桶 BM25)
"""

import pytest

from backend.retrieval.search import HybridSearcher, _visibility_probe_channel


def _make_embedder():
    from unittest.mock import MagicMock

    embedder = MagicMock()
    import numpy as np

    embedder.embed.return_value = [np.zeros(1024)]
    return embedder


def _make_client(objs=None):
    from unittest.mock import MagicMock

    client = MagicMock()
    collection = MagicMock()
    client.collections.get.return_value = collection
    results = MagicMock()
    results.objects = objs if objs is not None else []
    collection.query.hybrid.return_value = results
    collection.query.bm25.return_value = results
    return client, collection


def _collect_filter_values(obj) -> str:
    """递归收集过滤器对象(含 AND 嵌套)里全部 _FilterValue 的 repr。"""
    from weaviate.collections.classes.filters import _FilterValue

    if isinstance(obj, _FilterValue):
        return repr(obj)
    parts = []
    for attr in ("filters", "_filters", "target"):
        child = getattr(obj, attr, None)
        if isinstance(child, (list, tuple)):
            parts.extend(_collect_filter_values(c) for c in child)
        elif child is not None and not isinstance(child, str):
            parts.append(_collect_filter_values(child))
    return " ".join(p for p in parts if p)


def _hybrid_filters_repr(collection):
    _, kwargs = collection.query.hybrid.call_args
    return _collect_filter_values(kwargs.get("filters")) or repr(kwargs.get("filters", ""))


def _bm25_filters_repr(collection):
    _, kwargs = collection.query.bm25.call_args
    return _collect_filter_values(kwargs.get("filters")) or repr(kwargs.get("filters", ""))


# --------------------------------------------------------------------------- #
# 映射函数单元语义
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_probe_channel_maps_admin_to_widget():
    """admin → widget:管理员所见 = 访客所见。"""
    assert _visibility_probe_channel("admin") == "widget"


@pytest.mark.unit
def test_probe_channel_identity_for_other_channels():
    """widget/api/discord/mcp 原样透传(零回归基线);None 保持 None。"""
    for ch in ("widget", "api", "discord", "mcp"):
        assert _visibility_probe_channel(ch) == ch
    assert _visibility_probe_channel(None) is None


# --------------------------------------------------------------------------- #
# 三处过滤点行为一致:admin 均按 widget 视角过滤
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_search_admin_uses_widget_visibility():
    """hybrid 主检索:channel="admin" 时过滤目标为 widget(默认与显式 (widget) 配置源均可命中)。"""
    client, collection = _make_client(objs=[])
    HybridSearcher(client, _make_embedder()).search(query="NE503", channel="admin")
    repr_filters = _hybrid_filters_repr(collection)
    assert "value=['widget']" in repr_filters
    assert "admin" not in repr_filters


@pytest.mark.unit
def test_search_symbols_admin_uses_widget_visibility():
    """符号检索:与 hybrid 行为一致,admin → widget。"""
    client, collection = _make_client(objs=[])
    HybridSearcher(client, _make_embedder()).search_symbols(query="BatteryReadI2C", channel="admin")
    repr_filters = _bm25_filters_repr(collection)
    assert "value=['widget']" in repr_filters
    assert "admin" not in repr_filters


@pytest.mark.unit
def test_search_bucket_admin_uses_widget_visibility():
    """boost 桶:与 hybrid 行为一致,admin → widget(第三处过滤点,与契约两处保持一致语义)。"""
    client, collection = _make_client(objs=[])
    HybridSearcher(client, _make_embedder()).search_bucket(
        query="NE503", source_types=["filesystem"], channel="admin"
    )
    repr_filters = _bm25_filters_repr(collection)
    assert "value=['widget']" in repr_filters
    assert "admin" not in repr_filters


# --------------------------------------------------------------------------- #
# 回归等价:其他渠道过滤目标 = 渠道本身(与基线一致)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_search_other_channels_filter_unchanged():
    """widget/api/discord/mcp 的 hybrid 过滤目标 = 渠道本身(回归等价)。"""
    for ch in ("widget", "api", "discord", "mcp"):
        client, collection = _make_client(objs=[])
        HybridSearcher(client, _make_embedder()).search(query="NE503", channel=ch)
        assert f"value=['{ch}']" in _hybrid_filters_repr(collection), ch


@pytest.mark.unit
def test_search_symbols_other_channels_filter_unchanged():
    """符号检索其他渠道回归等价。"""
    for ch in ("widget", "api", "discord", "mcp"):
        client, collection = _make_client(objs=[])
        HybridSearcher(client, _make_embedder()).search_symbols(query="BatteryReadI2C", channel=ch)
        assert f"value=['{ch}']" in _bm25_filters_repr(collection), ch


@pytest.mark.unit
def test_search_bucket_other_channels_filter_unchanged():
    """boost 桶其他渠道回归等价。"""
    for ch in ("widget", "api", "discord", "mcp"):
        client, collection = _make_client(objs=[])
        HybridSearcher(client, _make_embedder()).search_bucket(
            query="NE503", source_types=["filesystem"], channel=ch
        )
        assert f"value=['{ch}']" in _bm25_filters_repr(collection), ch
