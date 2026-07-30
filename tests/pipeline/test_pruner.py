# tests/pipeline/test_pruner.py
"""LLMPruner 单元测试。

覆盖:
- 空输入返回空列表
- LLM 返回相关性评分后正确过滤
- min_keep 保底:即使全部低分也保留指定数量
- LLM 返回格式异常时 fail-open(保留全部)
- chunk 数量与评分数量不匹配时 fail-open
"""

from unittest.mock import AsyncMock

import pytest

from backend.llm.base import LLMResponse
from backend.pipeline.pruner import LLMPruner
from backend.retrieval.search import SearchResult


def _make_sr(text: str, idx: int = 0) -> SearchResult:
    return SearchResult(
        text=text,
        source_id=f"s{idx}",
        source_type="github",
        product="ne503",
        title=f"Doc {idx}",
        url=f"https://example.com/{idx}",
        score=0.5,
        chunk_index=idx,
    )


def _make_llm_response(content: str) -> LLMResponse:
    return LLMResponse(
        content=content,
        model="deepseek-v4-flash",
        tokens_input=100,
        tokens_output=20,
        latency_ms=50,
    )


@pytest.mark.unit
async def test_pruner_empty_input():
    """空列表传入时直接返回空列表,不调用 LLM。"""
    llm = AsyncMock()
    pruner = LLMPruner(llm)
    result = await pruner.prune("query", [])
    assert result == []
    llm.generate.assert_not_called()


@pytest.mark.unit
async def test_pruner_filters_low_relevance():
    """LLM 返回 [1, 0, 1] 时,过滤掉第二个 chunk。"""
    chunks = [
        _make_sr("relevant A", 0),
        _make_sr("irrelevant", 1),
        _make_sr("relevant B", 2),
    ]
    llm = AsyncMock()
    llm.generate.return_value = _make_llm_response("[1, 0, 1]")
    pruner = LLMPruner(llm, relevance_threshold=0.5, min_keep=1)

    result = await pruner.prune("NE503 功耗", chunks)

    assert len(result) == 2
    assert result[0].text == "relevant A"
    assert result[1].text == "relevant B"


@pytest.mark.unit
async def test_pruner_min_keep_preserves_top_chunks():
    """全部低分时,按 score 降序保留 min_keep 条(fail-open 防止过度剪枝)。"""
    chunks = [
        _make_sr("low1", 0),
        _make_sr("low2", 1),
        _make_sr("low3", 2),
    ]
    llm = AsyncMock()
    llm.generate.return_value = _make_llm_response("[0, 0, 0]")
    pruner = LLMPruner(llm, relevance_threshold=0.5, min_keep=2)

    result = await pruner.prune("query", chunks)

    assert len(result) == 2


@pytest.mark.unit
async def test_pruner_malformed_response_keeps_all():
    """LLM 返回非 JSON 时 fail-open,保留全部 chunk。"""
    chunks = [_make_sr("a", 0), _make_sr("b", 1)]
    llm = AsyncMock()
    llm.generate.return_value = _make_llm_response("抱歉,我无法理解。")
    pruner = LLMPruner(llm)

    result = await pruner.prune("query", chunks)

    assert len(result) == 2


@pytest.mark.unit
async def test_pruner_score_count_mismatch_keeps_all():
    """LLM 返回的评分数组长度与 chunk 数不匹配时 fail-open。"""
    chunks = [_make_sr("a", 0), _make_sr("b", 1), _make_sr("c", 2)]
    llm = AsyncMock()
    llm.generate.return_value = _make_llm_response("[1, 0]")
    pruner = LLMPruner(llm)

    result = await pruner.prune("query", chunks)

    assert len(result) == 3


@pytest.mark.unit
async def test_pruner_calls_llm_with_pruning_task():
    """LLM 调用时 task 参数应为 'pruning'。"""
    chunks = [_make_sr("a", 0)]
    llm = AsyncMock()
    llm.generate.return_value = _make_llm_response("[1]")
    pruner = LLMPruner(llm)

    await pruner.prune("query", chunks)

    _, kwargs = llm.generate.call_args
    assert kwargs.get("task") == "pruning"
