"""HybridSearcher 产品资格标签过滤(product_labels)测试(契约 §5)。

``product_labels`` = 目标产品的原始标签资格集合;三路检索(hybrid / 符号 /
boost 桶)都必须把该集合作为 ``product.equal`` 的 any_of 组合过滤 AND 进
既有过滤链(channel_visibility 等),这是 sibling 污染的检索级硬闸门。
"""

from unittest.mock import MagicMock

from backend.retrieval.search import HybridSearcher


def _searcher() -> tuple[HybridSearcher, MagicMock]:
    client = MagicMock()
    collection = MagicMock()
    client.collections.get.return_value = collection
    embedder = MagicMock()
    import numpy as np

    embedder.embed.return_value = [np.array([0.1] * 4)]
    return HybridSearcher(client, embedder), collection


def test_search_product_labels_builds_any_of_filter():
    searcher, collection = _searcher()
    searcher.search("NE503 固件", product_labels=["ne503", "meta-hailo-os"])
    kwargs = collection.query.hybrid.call_args.kwargs
    assert "filters" in kwargs


def test_search_without_labels_omits_product_filter():
    searcher, collection = _searcher()
    searcher.search("NE503 固件")
    kwargs = collection.query.hybrid.call_args.kwargs
    assert "filters" not in kwargs


def test_search_symbols_applies_product_labels():
    searcher, collection = _searcher()
    searcher.search_symbols("BatteryReadI2C", product_labels=["ne503"])
    kwargs = collection.query.bm25.call_args.kwargs
    assert "filters" in kwargs


def test_search_bucket_applies_product_labels():
    searcher, collection = _searcher()
    searcher.search_bucket("无法开机", source_types=["filesystem"], product_labels=["ne503", "knowledge"])
    kwargs = collection.query.bm25.call_args.kwargs
    assert "filters" in kwargs


def test_search_bucket_without_labels_unchanged():
    searcher, collection = _searcher()
    searcher.search_bucket("无法开机", source_types=["filesystem"])
    kwargs = collection.query.bm25.call_args.kwargs
    assert "filters" in kwargs  # source_types 本身就是过滤
