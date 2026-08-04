"""RRF(Reciprocal Rank Fusion)融合。

把任意多路检索结果(hybrid / 符号 BM25 / intent boost 桶 ...)按
``source_id + chunk_index`` 去重,用 RRF 公式 ``score = Σ 1/(k + rank + 1)``
累加得分后排序。``k=60`` 是 RRF 经验默认值,对 rank 量级相近的场景鲁棒。
"""

import dataclasses
from collections import defaultdict

from backend.retrieval.search import SearchResult


def rrf_fuse(
    *result_lists: list[SearchResult],
    k: int = 60,
) -> list[SearchResult]:
    """N 路 RRF 融合(变长参数),按 ``source_id + chunk_index`` 去重。

    对每路结果按出现顺序赋 rank(从 0 起),累加 ``1/(k + rank + 1)`` 到对应
    chunk 的融合分;同 chunk 出现在多路时分数相加(去重,保留首次出现的
    :class:`SearchResult` 作为代表)。空列表自动跳过。最终按融合分降序返回,
    代表结果的 ``score`` 更新为融合分(便于调试;rerank 用 ``text`` 不依赖 score)。

    Args:
        *result_lists: 任意多路检索结果(hybrid / symbol / boost bucket ...)。
        k: RRF 平滑常数(默认 60);越大对 rank 差异越不敏感。

    Returns:
        融合去重后的 :class:`SearchResult` 列表(按融合分降序);所有路均空返回 ``[]``。
    """
    scores: dict[tuple[str, int], float] = defaultdict(float)
    rep: dict[tuple[str, int], SearchResult] = {}
    for lst in result_lists:
        for rank, r in enumerate(lst):
            key = (r.source_id, r.chunk_index)
            scores[key] += 1.0 / (k + rank + 1)
            if key not in rep:
                rep[key] = r
    if not scores:
        return []
    ordered = sorted(scores, key=lambda kk: -scores[kk])
    return [dataclasses.replace(rep[kk], score=scores[kk]) for kk in ordered]
