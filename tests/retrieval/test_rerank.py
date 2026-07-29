"""RerankPipeline 单元测试。

覆盖:
- brief 基础 case(按分数排序、阈值过滤)
- 空 results 短路返回 [](不调 reranker)
- 重排后非 score 字段保持不变(immutable replace)
- 单结果低于阈值返回 []
- 不传 top_k 时使用构造函数 default
- 验证 reranker.rerank 调用参数(query + documents)
- reranker 返回 scores 长度与 results 不匹配 → RuntimeError
- top_k=0 时不应 fallback 到 default(0 falsy 陷阱)
"""

from unittest.mock import MagicMock

import pytest

from backend.retrieval.rerank import RerankPipeline
from backend.retrieval.search import SearchResult

# --------------------------------------------------------------------------- #
# 测试夹具与辅助
# --------------------------------------------------------------------------- #


def _make_sr(
    *,
    text: str = "text",
    source_id: str = "s",
    source_type: str = "github",
    product: str = "ne503",
    title: str = "T",
    url: str = "https://example.com",
    score: float = 0.5,
    chunk_index: int = 0,
) -> SearchResult:
    """构造测试用 SearchResult。"""
    return SearchResult(
        text=text,
        source_id=source_id,
        source_type=source_type,
        product=product,
        title=title,
        url=url,
        score=score,
        chunk_index=chunk_index,
    )


# --------------------------------------------------------------------------- #
# brief 基础测试
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_rerank_orders_by_score():
    """brief 用例:按 reranker 分数降序排序,并限制 top_k。"""
    results = [
        _make_sr(text="text A", source_id="s1", title="A", score=0.8),
        _make_sr(text="text B", source_id="s2", title="B", score=0.6),
        _make_sr(text="text C", source_id="s3", title="C", score=0.9),
    ]
    reranker = MagicMock()
    reranker.rerank.return_value = [0.3, 0.95, 0.7]  # B > C > A

    pipeline = RerankPipeline(reranker)
    reranked = pipeline.rerank("query", results, top_k=2)

    assert len(reranked) == 2
    assert reranked[0].source_id == "s2"  # B 分数最高
    assert reranked[1].source_id == "s3"  # C 第二


@pytest.mark.unit
def test_rerank_threshold_rejects_low_scores():
    """brief 用例:低于 threshold 的结果被过滤。"""
    results = [
        _make_sr(text="text A", source_id="s1", title="A", score=0.8),
    ]
    reranker = MagicMock()
    reranker.rerank.return_value = [0.1]  # 远低于阈值

    pipeline = RerankPipeline(reranker, threshold=0.3)
    reranked = pipeline.rerank("query", results, top_k=5)

    assert len(reranked) == 0


# --------------------------------------------------------------------------- #
# 空输入与字段保持
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_rerank_empty_results_returns_empty():
    """空 results 直接返回 [],不调用 reranker。"""
    reranker = MagicMock()
    pipeline = RerankPipeline(reranker)

    assert pipeline.rerank("query", []) == []
    reranker.rerank.assert_not_called()


@pytest.mark.unit
def test_rerank_preserves_search_result_fields_except_score():
    """重排后非 score 字段应保持不变(immutable replace)。"""
    original = _make_sr(
        text="NE503 功耗 2.5W",
        source_id="github-ne503/README.md",
        source_type="github",
        product="ne503",
        title="README",
        url="https://github.com/camthink-ai/ne503-aipc-sdks",
        score=0.5,
        chunk_index=3,
    )
    reranker = MagicMock()
    reranker.rerank.return_value = [0.95]

    pipeline = RerankPipeline(reranker)
    reranked = pipeline.rerank("NE503", [original], top_k=5)

    assert len(reranked) == 1
    sr = reranked[0]
    # score 应被更新
    assert sr.score == 0.95
    # 其余字段保持不变
    assert sr.text == original.text
    assert sr.source_id == original.source_id
    assert sr.source_type == original.source_type
    assert sr.product == original.product
    assert sr.title == original.title
    assert sr.url == original.url
    assert sr.chunk_index == original.chunk_index


@pytest.mark.unit
def test_rerank_handles_single_result_below_threshold():
    """单条结果低于阈值时返回 [](不抛错)。"""
    results = [_make_sr(source_id="s1")]
    reranker = MagicMock()
    reranker.rerank.return_value = [0.2]  # 低于默认阈值 0.3

    pipeline = RerankPipeline(reranker)  # threshold=0.3 default
    reranked = pipeline.rerank("query", results, top_k=5)

    assert reranked == []


# --------------------------------------------------------------------------- #
# 默认 top_k 与调用参数
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_rerank_default_top_k_used_when_not_passed():
    """不传 top_k 时使用构造函数 default(10)。"""
    # 构造 15 条结果,reranker 给所有结果都打高分(过阈值),应只返回 default 10 条
    results = [_make_sr(source_id=f"s{i}") for i in range(15)]
    reranker = MagicMock()
    reranker.rerank.return_value = [0.9] * 15

    pipeline = RerankPipeline(reranker, threshold=0.3, top_k=10)
    reranked = pipeline.rerank("query", results)

    assert len(reranked) == 10


@pytest.mark.unit
def test_rerank_passes_query_and_documents_to_reranker():
    """reranker.rerank 应接收原始 query 与 results 中提取的 text 列表。"""
    results = [
        _make_sr(text="text A", source_id="s1"),
        _make_sr(text="text B", source_id="s2"),
    ]
    reranker = MagicMock()
    reranker.rerank.return_value = [0.5, 0.6]

    pipeline = RerankPipeline(reranker)
    pipeline.rerank("my query", results, top_k=5)

    reranker.rerank.assert_called_once_with("my query", ["text A", "text B"])


# --------------------------------------------------------------------------- #
# top_k=0 边界(避免 falsy 陷阱)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_rerank_top_k_zero_does_not_fallback_to_default():
    """top_k=0 应返回空列表,不应因 0 falsy 而 fallback 到 default。

    防止 ``top_k or self._default_top_k`` 写法引入的回归。
    """
    results = [_make_sr(source_id="s1"), _make_sr(source_id="s2")]
    reranker = MagicMock()
    reranker.rerank.return_value = [0.9, 0.8]

    pipeline = RerankPipeline(reranker, top_k=10)
    reranked = pipeline.rerank("query", results, top_k=0)

    assert reranked == []


# --------------------------------------------------------------------------- #
# 错误处理:reranker 返回长度不匹配
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_rerank_raises_when_scores_length_mismatches_results():
    """reranker 返回 scores 数量与 results 不一致时 RuntimeError。

    与 Task 10/12 风格一致:不掩盖下游模型的契约违约。
    """
    results = [_make_sr(source_id="s1"), _make_sr(source_id="s2")]
    reranker = MagicMock()
    reranker.rerank.return_value = [0.5]  # 缺一个 score

    pipeline = RerankPipeline(reranker)
    with pytest.raises(RuntimeError, match="scores 长度"):
        pipeline.rerank("query", results, top_k=5)


# --------------------------------------------------------------------------- #
# threshold property
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_rerank_threshold_property_exposed():
    """threshold property 应暴露当前阈值,便于调试 / 监控。"""
    reranker = MagicMock()
    pipeline = RerankPipeline(reranker, threshold=0.45)
    assert pipeline.threshold == 0.45
