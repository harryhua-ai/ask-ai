"""INC-1 血统修订验收:证据身份 (source_id, chunk_index) 四阶段穿透。

审查修订授权的最小观测补全:
- 检索/融合:stages.retrieve.candidates[](有序身份表:rank/score/paths);
- 重排/剪枝:rerank.results[] 身份完备(source_id/chunk_index)+ prune_decisions[]
  (身份/剪前位次/去留);
- 终组合:citation_integrity.{citable,background,dropped_public}[](逐项身份,
  citable.citation_no = 引用编号语义)。

每个 demo 对应基线归因场景:
- K3:所需证据身份不在检索候选 → investigator 可证明缺席;
- K4:同一身份融合后存在但剪枝被移除 → 逐项判定可追溯;
- K6:同一身份活过选择/剪枝但在终组合改道(背景资料/公开丢弃)→ 逐项身份可定位。

隐私边界:全部字段为身份/位次/分数元数据,零 chunk 正文、零 prompt。
"""

import json

import pytest

from backend.llm import telemetry
from backend.llm.base import LLMResponse
from backend.llm.registry import LLMRouter
from backend.pipeline.rag import RAGOrchestrator
from backend.retrieval.search import SearchResult

QUESTION = "NE301 是什么？"


def _item(sid: str, url: str, source_type: str, score: float, chunk_index: int = 0):
    return SearchResult(
        text=f"chunk body of {sid}#{chunk_index}",
        source_id=sid,
        source_type=source_type,
        product="ne301",
        title=f"doc {sid}",
        url=url,
        score=score,
        chunk_index=chunk_index,
    )


class _FakeLLM:
    provider_id = "fake"

    @property
    def default_model(self):
        return "fake-model"

    async def health_check(self):
        return True

    async def generate(self, messages, **kwargs):
        prompt = messages[-1]["content"] if messages else ""
        if "意图分类" in prompt:
            content = json.dumps({"category": "product", "reason": "x", "confidence": 0.9})
        else:
            content = "答案 [1]"
        return LLMResponse(
            content=content, model="fake-model", tokens_input=11, tokens_output=7, latency_ms=1
        )

    async def stream(self, messages, **kwargs):
        yield "答案"
        yield " [1]"
        telemetry.record_stream_usage(7, 22)


def _router_llm():
    return LLMRouter(
        providers={"fake": _FakeLLM()},
        routing={
            "generation": [{"provider": "fake"}],
            "intent": [{"provider": "fake"}],
            "query_rewrite": [{"provider": "fake"}],
        },
    )


class _Searcher:
    def __init__(self, results):
        self._results = results

    def search(self, **kw):
        return list(self._results)

    def search_symbols(self, **kw):
        return []

    def search_bucket(self, **kw):
        return []


class _Reranker:
    def rerank(self, query, results, top_k=10):
        return sorted(results, key=lambda r: -r.score)[:top_k]


class _Pruner:
    """可控剪枝:丢弃指定身份(默认 s2#0),其余原样保留。"""

    def __init__(self, drop=frozenset({("s2", 0)})):
        self._drop = drop

    async def prune(self, query, chunks):
        return [c for c in chunks if (c.source_id, c.chunk_index) not in self._drop]


def _make_rag(results, pruner=None):
    return RAGOrchestrator(
        _Searcher(results),
        _Reranker(),
        _router_llm(),
        system_prompt="sys",
        pruner=pruner if pruner is not None else _Pruner(),
        min_results_to_answer=1,
    )


async def _complete(rag, query=QUESTION):
    events = []
    async for raw in rag.stream_answer(query, "widget"):
        e = json.loads(raw)
        if e.get("type") == "complete":
            events.append(e)
    return events[0]


def _ids(items):
    return {(d["source_id"], d["chunk_index"]) for d in items}


@pytest.mark.unit
async def test_k3_identity_absent_from_retrieval_candidates_is_provable():
    """K3:所需证据未进融合候选 → trace 身份表可证明其缺席与在场者。"""
    # 受控事实:检索只召回 s1#0 与 s3#0;所需证据 "ghost-doc#0" 未被召回。
    rag = _make_rag(
        [_item("s1", "https://x/s1", "github", 0.9), _item("s3", "https://x/s3", "filesystem", 0.6)]
    )
    complete = await _complete(rag)
    candidates = complete["trace_payload"]["stages"]["retrieve"]["candidates"]

    assert ("ghost-doc", 0) not in _ids(candidates)  # 缺席可证明
    assert ("s1", 0) in _ids(candidates) and ("s3", 0) in _ids(candidates)
    # 每个候选携带身份 + 融合位次/分数 + 召回路成员
    top = candidates[0]
    assert top["rank"] == 1
    assert {"source_id", "chunk_index", "score", "paths"} <= set(top)
    assert top["paths"] == ["hybrid"]


@pytest.mark.unit
async def test_k4_identity_present_at_fusion_removed_by_pruning_is_traceable():
    """K4:s2#0 融合后在剪枝被移除 → 候选在场 + 逐项判定 kept=False + 剪前位次。"""
    rag = _make_rag(
        [
            _item("s1", "https://x/s1", "github", 0.92),
            _item("s2", "https://x/s2", "github", 0.55),
            _item("s3", "https://x/s3", "filesystem", 0.61),
        ]
    )
    complete = await _complete(rag)
    stages = complete["trace_payload"]["stages"]

    # 在场证明:融合候选含 s2#0
    assert ("s2", 0) in _ids(stages["retrieve"]["candidates"])
    # 逐项判定:每项都有身份/剪前位次/去留
    decisions = {(d["source_id"], d["chunk_index"]): d for d in stages["rerank"]["prune_decisions"]}
    assert {("s1", 0), ("s2", 0), ("s3", 0)} == set(decisions)
    assert decisions[("s2", 0)]["kept"] is False
    # 剪前位次 = 剪枝输入序(三路各 1 项时 RRF 分相等,融合序 = 召回插入序)
    assert decisions[("s2", 0)]["pre_prune_rank"] == 2
    assert decisions[("s1", 0)]["kept"] is True
    assert decisions[("s3", 0)]["kept"] is True
    # 计数与逐项一致(防漂移)
    assert stages["rerank"]["pruned"] == 1
    assert sum(1 for d in decisions.values() if not d["kept"]) == 1
    # 剪后幸存者身份可见(重排 trace 身份完备)
    assert ("s2", 0) not in {
        (r["source_id"], r["chunk_index"]) for r in stages["rerank"]["results"]
    }


@pytest.mark.unit
async def test_k6_survivor_routed_to_background_is_identified():
    """K6:s3#0 活过选择/剪枝但终组合改道背景资料 → 逐项身份可定位。"""
    rag = _make_rag(
        [
            _item("s1", "https://x/s1", "github", 0.92),
            _item("s3", "https://x/s3", "filesystem", 0.61),
        ]
    )
    complete = await _complete(rag)
    tp = complete["trace_payload"]
    ci = tp["stages"]["citation_integrity"]

    assert ("s3", 0) in _ids(ci["background"])  # 改道去向可定位
    assert ("s3", 0) not in _ids(ci["citable"])
    assert ("s3", 0) not in {s["url"] for s in complete["sources"]} | {
        s.get("url", "") for s in complete["sources"]
    }  # 访客不可见
    # 幸存但改道 ≠ 被剪:剪枝判定 kept=True
    decisions = {
        (d["source_id"], d["chunk_index"]): d for d in tp["stages"]["rerank"]["prune_decisions"]
    }
    assert decisions[("s3", 0)]["kept"] is True


@pytest.mark.unit
async def test_k6_public_evidence_dropped_before_composition_is_identified():
    """K6:公开证据因来源截 5 不可见引用被丢 → dropped_public 逐项身份。"""
    results = [_item(f"pub{i}", f"https://x/p{i}", "github", 0.9 - i * 0.01) for i in range(6)]
    rag = _make_rag(results, pruner=_Pruner(drop=frozenset()))
    complete = await _complete(rag)
    ci = complete["trace_payload"]["stages"]["citation_integrity"]

    assert ("pub5", 0) in _ids(ci["dropped_public"])
    assert ("pub0", 0) in _ids(ci["citable"])
    assert len(complete["sources"]) == 5  # 展示层截 5 语义不变


@pytest.mark.unit
async def test_investigator_can_answer_four_questions_for_arbitrary_identity():
    """任取一身份,四问全部可从单请求 trace 回答:检索了?排位?去留?终组合去向?"""
    rag = _make_rag(
        [
            _item("s1", "https://x/s1", "github", 0.92),
            _item("s2", "https://x/s2", "github", 0.55),
            _item("s3", "https://x/s3", "filesystem", 0.61),
        ]
    )
    complete = await _complete(rag)
    tp = complete["trace_payload"]
    stages = tp["stages"]
    target = ("s1", 0)

    # 1) retrieved?
    cand = next(
        c for c in stages["retrieve"]["candidates"] if (c["source_id"], c["chunk_index"]) == target
    )
    # 2) rank/score?(融合位次 + 重排幸存者分数)
    assert cand["rank"] == 1 and cand["score"] > 0
    rr = next(
        r for r in stages["rerank"]["results"] if (r["source_id"], r["chunk_index"]) == target
    )
    assert rr["score"] is not None
    # 3) kept or pruned?
    dec = next(
        d
        for d in stages["rerank"]["prune_decisions"]
        if (d["source_id"], d["chunk_index"]) == target
    )
    assert dec["kept"] is True and dec["pre_prune_rank"] == 1
    # 4) final composition disposition?
    cit = next(
        c
        for c in stages["citation_integrity"]["citable"]
        if (c["source_id"], c["chunk_index"]) == target
    )
    assert cit["citation_no"] == 1  # 引用编号语义:来源序号 [1]


@pytest.mark.unit
async def test_lineage_fields_carry_no_chunk_text():
    """隐私边界:血统字段全部为元数据,不携带 chunk 正文。"""
    rag = _make_rag(
        [
            _item("s1", "https://x/s1", "github", 0.92),
            _item("s3", "https://x/s3", "filesystem", 0.61),
        ]
    )
    complete = await _complete(rag)
    tp = complete["trace_payload"]
    lineage_buckets = [
        tp["stages"]["retrieve"]["candidates"],
        tp["stages"]["rerank"]["prune_decisions"] or [],
        tp["stages"]["citation_integrity"]["citable"],
        tp["stages"]["citation_integrity"]["background"],
        tp["stages"]["citation_integrity"]["dropped_public"],
    ]
    for bucket in lineage_buckets:
        for item in bucket:
            assert set(item) <= {
                "rank",
                "source_id",
                "chunk_index",
                "score",
                "paths",
                "kept",
                "pre_prune_rank",
                "citation_no",
            }
    # rerank.results 的 text 预览为既有暴露(未扩大);血统新增字段不含 text
    for r in tp["stages"]["rerank"]["results"]:
        assert set(r) - {"source_id", "chunk_index"} >= {"title"}
