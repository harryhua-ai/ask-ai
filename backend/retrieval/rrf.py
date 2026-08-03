"""RRF(Reciprocal Rank Fusion)融合。

把 hybrid 检索与独立符号 BM25 召回两路结果按 ``source_id + chunk_index`` 去重,
用 RRF 公式 ``score = Σ 1/(k + rank)`` 累加得分后排序。``k=60`` 是 RRF 经验默认值,
对两路 rank 量级相近的场景鲁棒。
"""

import dataclasses
from collections import defaultdict

from backend.retrieval.search import SearchResult


def rrf_fuse(
    hybrid: list[SearchResult],
    symbol: list[SearchResult],
    k: int = 60,
) -> list[SearchResult]:
    """RRF 融合两路结果,按 ``source_id + chunk_index`` 去重。

    对每路结果按出现顺序赋 rank(从 0 起),累加 ``1/(k + rank + 1)`` 到对应
    chunk 的融合分;同 chunk 出现在两路时分数相加(去重,保留首次出现的
    :class:`SearchResult` 作为代表)。最终按融合分降序返回,代表结果的
    ``score`` 更新为融合分(便于调试;rerank 用 ``text`` 不依赖 score)。

    Args:
        hybrid: hybrid 检索结果(语义 + BM25 融合路)。
        symbol: 独立符号 BM25 召回结果。
        k: RRF 平滑常数(默认 60);越大对 rank 差异越不敏感。

    Returns:
        融合去重后的 :class:`SearchResult` 列表(按融合分降序);两路均空返回 ``[]``。
    """
    scores: dict[tuple[str, int], float] = defaultdict(float)
    rep: dict[tuple[str, int], SearchResult] = {}
    for rank, r in enumerate(hybrid):
        key = (r.source_id, r.chunk_index)
        scores[key] += 1.0 / (k + rank + 1)
        if key not in rep:
            rep[key] = r
    for rank, r in enumerate(symbol):
        key = (r.source_id, r.chunk_index)
        scores[key] += 1.0 / (k + rank + 1)
        if key not in rep:
            rep[key] = r
    ordered = sorted(scores, key=lambda kk: -scores[kk])
    return [dataclasses.replace(rep[kk], score=scores[kk]) for kk in ordered]