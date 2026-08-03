"""RRF 融合单元测试。"""

import pytest

from backend.retrieval.rrf import rrf_fuse
from backend.retrieval.search import SearchResult


def _sr(text: str, source_id: str, chunk_index: int = 0, score: float = 0.9) -> SearchResult:
    return SearchResult(
        text=text, source_id=source_id, source_type="local_git", product="p",
        title="T", url="", score=score, chunk_index=chunk_index,
    )


@pytest.mark.unit
def test_rrf_dedup_by_source_id_chunk_index():
    """同 source_id+chunk_index 合并;不同 chunk 保留;按 RRF 分排序。"""
    a = _sr("a", "s1", chunk_index=0, score=0.9)
    b = _sr("a", "s1", chunk_index=0, score=0.8)  # 同 chunk,去重
    c = _sr("c", "s2", chunk_index=0, score=0.7)
    out = rrf_fuse([a], [b, c], k=60)
    assert len(out) == 2  # a/b 合并 + c
    # a 同时在 hybrid(rank0)与 symbol(rank0):1/61 + 1/61 ≈ 0.0328
    # c 仅 symbol(rank1):1/62 ≈ 0.0161 → a 融合分更高
    assert out[0].source_id == "s1"
    assert out[1].source_id == "s2"


@pytest.mark.unit
def test_rrf_empty_inputs():
    """两路均空返回空列表。"""
    assert rrf_fuse([], [], k=60) == []


@pytest.mark.unit
def test_rrf_score_updated_to_fusion():
    """代表结果的 score 更新为 RRF 融合分(便于调试)。"""
    a = _sr("a", "s1", score=0.9)
    out = rrf_fuse([a], [], k=60)
    assert len(out) == 1
    assert out[0].score == 1.0 / (60 + 0 + 1)


@pytest.mark.unit
def test_rrf_symbol_only_promotes_symbol_hit():
    """仅 symbol 路命中的结果仍保留(hybrid 未命中不丢失)。"""
    b = _sr("b", "s2")
    out = rrf_fuse([], [b], k=60)
    assert len(out) == 1
    assert out[0].source_id == "s2"


@pytest.mark.unit
def test_rrf_dedup_keeps_distinct_chunks_same_doc():
    """同 doc 不同 chunk_index 不合并(各为独立结果)。"""
    a0 = _sr("a0", "s1", chunk_index=0)
    a1 = _sr("a1", "s1", chunk_index=1)
    out = rrf_fuse([a0, a1], [], k=60)
    assert len(out) == 2
    chunks = {r.chunk_index for r in out}
    assert chunks == {0, 1}