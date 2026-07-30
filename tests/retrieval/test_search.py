"""HybridSearcher 单元测试。

覆盖:
- brief 基础 case(SearchResult dataclass)
- 空 query 直接返回 [](不调用 embed / weaviate)
- 空结果集合时返回 []
- alpha / limit / product_filter 参数透传
- 缺失 metadata 时不抛错
- distance → score 转换
- embedder 返回空向量列表时 RuntimeError
- Weaviate 异常向上传播
"""

import dataclasses
from unittest.mock import MagicMock

import numpy as np
import pytest

from backend.retrieval.search import HybridSearcher, SearchResult

# --------------------------------------------------------------------------- #
# 测试夹具与辅助
# --------------------------------------------------------------------------- #


def _make_embedder(dim: int = 1024) -> MagicMock:
    """构造返回固定向量的 MagicMock embedder。"""
    emb = MagicMock()
    emb.dimension = dim
    emb.embed.return_value = [np.array([0.1] * dim)]
    return emb


def _make_obj(
    *,
    text: str = "NE503 功耗 2.5W",
    source_id: str = "github-ne503/README.md",
    source_type: str = "github",
    product: str = "ne503",
    title: str = "README",
    url: str = "https://github.com/camthink-ai/ne503-aipc-sdks",
    chunk_index: int = 0,
    distance: float | None = 0.05,
    metadata_is_none: bool = False,
) -> MagicMock:
    """构造一个 Weaviate object(模拟 collection.query.hybrid 返回的单个元素)。"""
    obj = MagicMock()
    obj.properties = {
        "text": text,
        "source_id": source_id,
        "source_type": source_type,
        "product": product,
        "title": title,
        "url": url,
        "chunk_index": chunk_index,
    }
    if metadata_is_none:
        obj.metadata = None
    else:
        obj.metadata = MagicMock(distance=distance)
    return obj


def _make_weaviate_client(objs: list | None = None) -> MagicMock:
    """构造 MagicMock Weaviate client,可控制 hybrid 返回的 objects。"""
    client = MagicMock()
    collection = MagicMock()
    client.collections.get.return_value = collection
    results = MagicMock()
    results.objects = objs if objs is not None else []
    collection.query.hybrid.return_value = results
    return client


# --------------------------------------------------------------------------- #
# brief 基础测试
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_search_result_dataclass():
    """brief 用例:SearchResult 字段赋值与读取。"""
    sr = SearchResult(
        text="NE503 功耗 2.5W",
        source_id="github-ne503/README.md",
        source_type="github",
        product="ne503",
        title="README",
        url="https://github.com/camthink-ai/ne503-aipc-sdks",
        score=0.95,
        chunk_index=0,
    )
    assert sr.product == "ne503"
    assert sr.score == 0.95


@pytest.mark.unit
def test_search_result_is_frozen():
    """SearchResult 为 frozen dataclass,赋值应抛 FrozenInstanceError。"""
    sr = SearchResult(
        text="t",
        source_id="id",
        source_type="github",
        product="ne503",
        title="x",
        url="",
        score=0.1,
        chunk_index=0,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        sr.score = 0.5  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# 空 query 与空结果
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_search_returns_empty_for_empty_query():
    """空 / 纯空白 query 直接返回 [],不触发 embedder / Weaviate。"""
    embedder = _make_embedder()
    client = _make_weaviate_client()

    searcher = HybridSearcher(client, embedder)
    assert searcher.search("") == []
    assert searcher.search("   ") == []

    embedder.embed.assert_not_called()
    client.collections.get.assert_not_called()


@pytest.mark.unit
def test_search_returns_empty_for_no_results():
    """Weaviate 返回空 objects 列表时,search 返回 []。"""
    embedder = _make_embedder()
    client = _make_weaviate_client(objs=[])

    searcher = HybridSearcher(client, embedder)
    results = searcher.search("NE503")

    assert results == []


# --------------------------------------------------------------------------- #
# 参数透传
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_search_passes_alpha_and_limit():
    """alpha / limit 参数应透传到 hybrid 调用。"""
    embedder = _make_embedder()
    client = _make_weaviate_client(objs=[_make_obj()])

    searcher = HybridSearcher(client, embedder)
    searcher.search(query="NE503", alpha=0.7, limit=10)

    collection = client.collections.get.return_value
    _, kwargs = collection.query.hybrid.call_args
    assert kwargs["alpha"] == 0.7
    assert kwargs["limit"] == 10


@pytest.mark.unit
def test_search_applies_product_filter():
    """传 product_filter 时应附加 filters 参数(Filter 非空)。"""
    embedder = _make_embedder()
    client = _make_weaviate_client(objs=[_make_obj()])

    searcher = HybridSearcher(client, embedder)
    searcher.search(query="NE503", product_filter="ne503")

    collection = client.collections.get.return_value
    _, kwargs = collection.query.hybrid.call_args
    assert "filters" in kwargs
    # Filter 对象非 None
    assert kwargs["filters"] is not None


@pytest.mark.unit
def test_search_omits_filter_when_no_product_filter():
    """未传 product_filter 时 kwargs 不应包含 filters 键。"""
    embedder = _make_embedder()
    client = _make_weaviate_client(objs=[_make_obj()])

    searcher = HybridSearcher(client, embedder)
    searcher.search(query="NE503")

    collection = client.collections.get.return_value
    _, kwargs = collection.query.hybrid.call_args
    assert "filters" not in kwargs


# --------------------------------------------------------------------------- #
# metadata / distance 边界
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_search_handles_missing_metadata():
    """obj.metadata 为 None 时不应抛错,score 退化为 0.0。"""
    embedder = _make_embedder()
    client = _make_weaviate_client(
        objs=[_make_obj(metadata_is_none=True)],
    )

    searcher = HybridSearcher(client, embedder)
    results = searcher.search("NE503")

    assert len(results) == 1
    assert results[0].score == 0.0


@pytest.mark.unit
def test_search_score_converts_distance_to_similarity():
    """distance=0.2 → score=0.8(1 - distance)。"""
    embedder = _make_embedder()
    client = _make_weaviate_client(objs=[_make_obj(distance=0.2)])

    searcher = HybridSearcher(client, embedder)
    results = searcher.search("NE503")

    assert len(results) == 1
    assert results[0].score == pytest.approx(0.8)


@pytest.mark.unit
def test_search_handles_none_distance_in_metadata():
    """metadata 存在但 distance=None 时 score 退化为 0.0。"""
    embedder = _make_embedder()
    obj = _make_obj()
    obj.metadata = MagicMock(distance=None)
    client = _make_weaviate_client(objs=[obj])

    searcher = HybridSearcher(client, embedder)
    results = searcher.search("NE503")

    assert results[0].score == 0.0


@pytest.mark.unit
def test_search_maps_all_properties():
    """Weaviate properties 全部字段映射到 SearchResult。"""
    embedder = _make_embedder()
    client = _make_weaviate_client(
        objs=[
            _make_obj(
                text="chunk text",
                source_id="src-1",
                source_type="filesystem",
                product="ask-ai",
                title="Doc",
                url="https://example.com",
                chunk_index=3,
                distance=0.0,
            )
        ]
    )

    searcher = HybridSearcher(client, embedder)
    results = searcher.search("hello")

    assert len(results) == 1
    sr = results[0]
    assert sr.text == "chunk text"
    assert sr.source_id == "src-1"
    assert sr.source_type == "filesystem"
    assert sr.product == "ask-ai"
    assert sr.title == "Doc"
    assert sr.url == "https://example.com"
    assert sr.chunk_index == 3
    assert sr.score == pytest.approx(1.0)


@pytest.mark.unit
def test_search_handles_none_properties():
    """obj.properties 为 None 时所有字段退化为默认值,不抛错。"""
    embedder = _make_embedder()
    obj = MagicMock()
    obj.properties = None
    obj.metadata = MagicMock(distance=0.1)
    client = _make_weaviate_client(objs=[obj])

    searcher = HybridSearcher(client, embedder)
    results = searcher.search("NE503")

    assert len(results) == 1
    sr = results[0]
    assert sr.text == ""
    assert sr.source_id == ""
    assert sr.chunk_index == 0


# --------------------------------------------------------------------------- #
# 错误处理
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_search_raises_when_embedder_returns_empty():
    """embedder 返回空向量列表时 RuntimeError(与 ingestion 风格一致)。"""
    embedder = MagicMock()
    embedder.dimension = 1024
    embedder.embed.return_value = []
    client = _make_weaviate_client()

    searcher = HybridSearcher(client, embedder)
    with pytest.raises(RuntimeError, match="embedder 返回空向量"):
        searcher.search("NE503")

    # 不应调用 Weaviate
    client.collections.get.assert_not_called()


@pytest.mark.unit
def test_search_propagates_weaviate_error():
    """Weaviate 调用失败时异常向上传播(不吞)。"""
    embedder = _make_embedder()
    client = MagicMock()
    collection = MagicMock()
    collection.query.hybrid.side_effect = RuntimeError("weaviate down")
    client.collections.get.return_value = collection

    searcher = HybridSearcher(client, embedder)
    with pytest.raises(RuntimeError, match="weaviate down"):
        searcher.search("NE503")


@pytest.mark.unit
def test_search_passes_custom_class_name():
    """自定义 class_name 应透传到 collections.get。"""
    embedder = _make_embedder()
    client = _make_weaviate_client(objs=[])

    searcher = HybridSearcher(client, embedder, class_name="CustomDoc")
    searcher.search("NE503")

    client.collections.get.assert_called_once_with("CustomDoc")


# --------------------------------------------------------------------------- #
# Phase 2A:SearchResult 新增元数据字段默认值
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_search_result_has_new_fields_default():
    """SearchResult 应包含 chunk_type / doc_section / channel_visibility 字段。"""
    from backend.retrieval.search import SearchResult
    r = SearchResult(
        text="t", source_id="s", source_type="github", product="p",
        title="T", url="u", score=0.5, chunk_index=0,
    )
    assert r.chunk_type == ""
    assert r.doc_section == ""
    assert r.channel_visibility == ("widget", "api")


# --------------------------------------------------------------------------- #
# Phase 2A Task 6:channel 过滤 + 新 property 读取
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_search_passes_channel_filter_to_weaviate():
    """search 应在 channel 参数非空时附加 channel_visibility filter。"""
    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_client.collections.get.return_value = mock_collection
    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [np.array([0.1, 0.2])]

    searcher = HybridSearcher(mock_client, mock_embedder)
    searcher.search("query", channel="widget")

    hybrid_call_kwargs = mock_collection.query.hybrid.call_args.kwargs
    assert "filters" in hybrid_call_kwargs


@pytest.mark.unit
def test_search_reads_new_properties_into_search_result():
    """search 应从 Weaviate properties 读取 chunk_type / doc_section / channel_visibility。"""
    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_client.collections.get.return_value = mock_collection

    mock_obj = MagicMock()
    mock_obj.properties = {
        "text": "content", "source_id": "s", "source_type": "github",
        "product": "p", "title": "T", "url": "u", "chunk_index": 0,
        "chunk_type": "heading", "doc_section": "Intro > Setup",
        "channel_visibility": ["widget", "api"],
    }
    mock_obj.metadata = MagicMock()
    mock_obj.metadata.distance = 0.2
    mock_collection.query.hybrid.return_value = MagicMock(objects=[mock_obj])

    mock_embedder = MagicMock()
    mock_embedder.embed.return_value = [np.array([0.1, 0.2])]

    searcher = HybridSearcher(mock_client, mock_embedder)
    results = searcher.search("query")

    assert len(results) == 1
    r = results[0]
    assert r.chunk_type == "heading"
    assert r.doc_section == "Intro > Setup"
    assert r.channel_visibility == ("widget", "api")
