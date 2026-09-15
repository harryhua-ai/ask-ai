"""Issue #77 — evidence eligibility / composition (Role B RED→GREEN).

冻结意图(见 Issue #77 正文 §9 + Role A 授权):
- B 普通问句证据组合:阈上「用户面」(非 code)证据不得被 code 凭分数挤出证据面;
- D 兜底资格:兜底路径必须服从同一类资格边界(类组合,不重引被正确拒绝者);
- E 槽位覆盖类真实:code 不得满足 PRODUCT_SPEC/SOLUTION_GUIDE 用户面文档槽;
- A fixture 排除:既有 ``ExclusionPolicy.exclude_dirs`` 机制可阻止 eval/fixtures
  入库,且相邻正常内容不受影响。

边界保真度:被测代码全部真实 —— ``RAGOrchestrator.answer``(含兜底/组合/槽位
覆盖全链)、``evidence_matches_slot``、``ExclusionPolicy``;脚本只出现在
LLM(仓库既有 ``LLMRouter`` 假体模式)与 Weaviate 边界(检索返回脚本)。
基线(f4e6751)预期:RED-1/2/3/4 FAIL,CONTROL-1/2/3 PASS。
"""

import json

import pytest

from backend.connectors.exclusion import ExclusionPolicy
from backend.llm.base import LLMResponse
from backend.llm.registry import LLMRouter
from backend.pipeline.citation import PUBLIC_SOURCE_TYPES
from backend.pipeline.evidence_planning import (
    CITATION_CITABLE_REQUIRED,
    EvidenceSlot,
    ROLE_PRODUCT_SPEC,
)
from backend.pipeline.evidence_selection import evidence_matches_slot
from backend.pipeline.rag import RAGOrchestrator
from backend.retrieval.rerank import RerankPipeline
from backend.retrieval.search import SearchResult

OFFICIAL = ("wiki-documents-local/main/docs/5-neoeyes-ne301-series/1-quick-start.md", 0)


def _code_chunk(i: int) -> SearchResult:
    return SearchResult(
        text=f"firmware module {i}: usb request head parser, dma address register",
        source_id=f"ne301-local/main/src/module_{i:02d}.c",
        source_type="github",
        product="ne301",
        title=f"module_{i:02d}.c",
        url=f"https://github.com/camthink-ai/ne301/blob/main/src/module_{i:02d}.c",
        score=0.5,
        chunk_index=0,
        chunk_type="code",
    )


def _official_chunk() -> SearchResult:
    """权威用户面文档(wiki = github 类 + heading chunk,词法弱但合格)。"""
    return SearchResult(
        text="OFFICIAL-DOC: NE301 quick start — battery install, first capture, default setup.",
        source_id=OFFICIAL[0],
        source_type="github",
        product="ne301",
        title="NE301 Quick Start",
        url="https://wiki.camthink.ai/docs/neoeyes-ne301-series/quick-start",
        score=0.0,
        chunk_index=0,
        chunk_type="heading",
    )


class _ScriptedRerankerInner:
    """真实 RerankPipeline 的内层:code/official 分数可配(确定性)。"""

    def __init__(self, official_score: float, code_score: float = 0.9):
        self._official = official_score
        self._code = code_score

    def rerank(self, query, documents):
        return [
            self._official if "OFFICIAL-DOC" in d else self._code
            for d in documents
        ]


class _Searcher:
    """Weaviate 边界脚本:hybrid 返回固定池(code 11 + official 1);记录调用。"""

    def __init__(self, pool: list[SearchResult]):
        self._pool = list(pool)
        self.bucket_calls: list[dict] = []

    def search(self, **kw):
        return list(self._pool)

    def search_symbols(self, **kw):
        return [c for c in self._pool if c.chunk_type == "code"][:10]

    def search_bucket(self, **kw):
        self.bucket_calls.append(kw)
        return []


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


def _router_llm():
    return LLMRouter(
        providers={"fake": _FakeLLM()},
        routing={
            "generation": [{"provider": "fake"}],
            "intent": [{"provider": "fake"}],
            "query_rewrite": [{"provider": "fake"}],
        },
    )


def _pool(official: bool = True) -> list[SearchResult]:
    pool = [_code_chunk(i) for i in range(11)]
    if official:
        pool.append(_official_chunk())
    return pool


def _make_rag(official_score: float, official: bool = True, code_score: float = 0.9):
    return RAGOrchestrator(
        _Searcher(_pool(official)),
        RerankPipeline(_ScriptedRerankerInner(official_score, code_score=code_score)),
        _router_llm(),
        system_prompt="sys",
        min_results_to_answer=1,
    )


def _ids(items) -> set:
    return {(r.source_id, r.chunk_index) for r in items}


QUERY = "NE301 battery specification"


# --------------------------------------------------------------------------- #
# RED-1:普通问句 —— 阈上用户面证据被 code 挤出证据面
# --------------------------------------------------------------------------- #
@pytest.mark.unit
async def test_red1_official_evidence_not_displaced_by_code():
    """official 阈上(0.25×1.2=0.30 ≥ 0.3)但截断线外;code 凭分占满证据面。"""
    rag = _make_rag(official_score=0.25)
    result = await rag.answer(QUERY, channel="widget")

    evidence_ids = _ids(result.reranked_results)
    assert OFFICIAL in evidence_ids, (
        "threshold-passing official user-facing evidence must not be displaced "
        f"from the evidence set by code chunks (evidence={len(evidence_ids)})"
    )
    # code 仍占证据面多数(非全局抑制)
    code_in_evidence = [r for r in result.reranked_results if r.chunk_type == "code"]
    assert len(code_in_evidence) >= 9


# --------------------------------------------------------------------------- #
# RED-2:兜底路径 —— 全员阈下时兜底证据面必须服从同类组合边界
# --------------------------------------------------------------------------- #
@pytest.mark.unit
async def test_red2_fallback_respects_same_class_boundary():
    """全部候选低于重排阈值 → 兜底激活;official 不得被兜底的原始顺序淹没。"""
    rag = _make_rag(official_score=0.1, code_score=0.2)
    result = await rag.answer(QUERY, channel="widget")

    assert result.is_answered, "兜底场景仍应生成(既有 Q98/Q104 语义)"
    evidence_ids = _ids(result.reranked_results)
    assert OFFICIAL in evidence_ids, (
        "fallback must apply the same class composition boundary — the "
        "user-facing chunk in the pool must not be buried by raw fused order "
        f"(evidence={len(evidence_ids)})"
    )


# --------------------------------------------------------------------------- #
# RED-3:类真实槽位覆盖 —— code 不得满足 PRODUCT_SPEC 用户面文档槽
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_red3_code_candidate_cannot_satisfy_product_spec_slot():
    slot = EvidenceSlot(
        role=ROLE_PRODUCT_SPEC,
        citation_requirement=CITATION_CITABLE_REQUIRED,
    )
    code_candidate = _code_chunk(0)

    # 前置事实:github ∈ PUBLIC_SOURCE_TYPES(组合引用白名单),故基线按
    # 连接器类放行 code —— 这正是要修正的类盲点。
    assert "github" in PUBLIC_SOURCE_TYPES
    assert evidence_matches_slot(slot, code_candidate) is False, (
        "code/firmware evidence must not satisfy a user-facing PRODUCT_SPEC slot"
    )
    # 非代码文档证据不受影响(CONTROL-2 的谓词面)
    assert evidence_matches_slot(slot, _official_chunk()) is True


# --------------------------------------------------------------------------- #
# RED-4:fixture 入库 —— 既有 exclude_dirs 机制是唯一授权边界
# --------------------------------------------------------------------------- #
_FIXTURE_REL = "eval/fixtures/scenario-agriculture-solution.json"
_NEIGHBORS = (
    "crates/neomind-core/src/lib.rs",
    "web/src/main.tsx",
    "README.md",
    "src/pipeline.rs",
)


@pytest.mark.unit
def test_red4_fixture_paths_excludable_via_existing_exclude_dirs():
    """生产现状(无 eval 边界)下 fixture 可入库 = 缺口;补 eval 后被排除,
    相邻仓库/代码内容不受影响。"""
    # 现状配置镜像(production neomind-local:exclude_dirs=[".github","docs"])
    current = ExclusionPolicy({"exclude_dirs": [".github", "docs"]})
    assert current.should_exclude(_FIXTURE_REL, 10) is False, (
        "pre-condition: without the eval boundary the fixture path is ingestible"
    )

    # 授权边界 = 既有机制追加 eval(配置级;零新分类器/零词汇)
    fixed = ExclusionPolicy({"exclude_dirs": [".github", "docs", "eval"]})
    assert fixed.should_exclude(_FIXTURE_REL, 10) is True
    assert fixed.should_exclude("eval/cases/zh/scenario-agriculture-solution/deploy.json", 10) is True
    # CONTROL-3:相邻正常内容保持可入库
    for rel in _NEIGHBORS:
        assert fixed.should_exclude(rel, 10) is False, rel


# --------------------------------------------------------------------------- #
# CONTROL-1:代码导向查询 —— 全 code 池组合恒等(code 不被抑制)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
async def test_control1_code_only_pool_composition_is_identity():
    rag = _make_rag(official_score=0.25, official=False)
    result = await rag.answer(QUERY, channel="widget")

    evidence_ids = _ids(result.reranked_results)
    assert all(sid.startswith("ne301-local/") for sid, _ in evidence_ids)
    assert len(evidence_ids) == 10  # top_k 不变,全 code 保留


# --------------------------------------------------------------------------- #
# CONTROL-2:合格用户面证据保持资格(谓词面)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_control2_qualified_official_evidence_stays_eligible():
    slot = EvidenceSlot(role=ROLE_PRODUCT_SPEC, citation_requirement=CITATION_CITABLE_REQUIRED)
    official = _official_chunk()
    assert official.source_type in PUBLIC_SOURCE_TYPES
    assert evidence_matches_slot(slot, official) is True


# --------------------------------------------------------------------------- #
# CONTROL-4(谓词面):#78 桶配置/归因不被 #77 触碰(机械校验在 stacked 树)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
async def test_control4_recall_path_unchanged_by_issue77():
    """#77 只动证据组合/资格;召回路径(桶配置消费)保持不变:
    product 意图仍然恰好一次 search_bucket,且主 hybrid 照常。"""
    searcher = _Searcher(_pool(True))
    rag = RAGOrchestrator(
        searcher,
        RerankPipeline(_ScriptedRerankerInner(0.25)),
        _router_llm(),
        system_prompt="sys",
        min_results_to_answer=1,
    )
    await rag.answer(QUERY, channel="widget")
    assert searcher.bucket_calls, "bucket path must still run for product intent"
    assert (
        len(searcher.bucket_calls) == 1
    ), f"#77 must not alter recall configuration (calls={len(searcher.bucket_calls)})"


# --------------------------------------------------------------------------- #
# R2 RED-B1:显式 code-oriented 查询 —— code 保持竞争序(不得被类组合重排)
# --------------------------------------------------------------------------- #
@pytest.mark.unit
async def test_red_b1_code_oriented_query_keeps_relevance_order():
    """显式 SDK/API/firmware 查询 + 混合池:code 按既有相关序竞争,
    组合不得把非 code 自动前置(复用既有 _is_code_oriented_* 判定)。"""
    code_query = "How do I integrate the SDK API in firmware driver code?"
    rag = _make_rag(official_score=0.25)
    result = await rag.answer(code_query, channel="widget")

    evidence = result.reranked_results
    assert evidence, "evidence must exist"
    # B 语义:#77 组合在 code-oriented 查询上恒等(证据面 = 既有相关序)。
    # 证据中 code 块必须连续、按池序、零丢失(10/10);唯一可能的非 code 前置
    # 来自既有 INC-5 required 槽前置(类真实匹配后的既有策略),至多 1 席。
    code_positions = [i for i, r in enumerate(evidence) if r.chunk_type == "code"]
    code_in_pool_order = [
        (r.source_id, r.chunk_index) for r in evidence if r.chunk_type == "code"
    ] == [(_code_chunk(i).source_id, 0) for i in range(len(code_positions))]
    assert len(code_positions) == 10 and code_in_pool_order, (
        "code must retain all 10 positions in existing relevance order "
        f"(positions={code_positions})"
    )
    assert code_positions == list(
        range(min(code_positions), min(code_positions) + 10)
    ), f"code block must be contiguous (positions={code_positions})"
    assert len(code_positions) == len(evidence) - (
        1 if len(evidence) > 10 else 0
    ) or len(evidence) == 10


# --------------------------------------------------------------------------- #
# R2 RED-B2:code-oriented 兜底 —— 兜底证据面保持竞争序
# --------------------------------------------------------------------------- #
@pytest.mark.unit
async def test_red_b2_code_oriented_fallback_keeps_raw_order():
    code_query = "How do I integrate the SDK API in firmware driver code?"
    rag = _make_rag(official_score=0.1, code_score=0.2)
    result = await rag.answer(code_query, channel="widget")

    assert result.is_answered
    evidence = result.reranked_results
    assert evidence[0].chunk_type == "code", (
        "code-oriented fallback must keep raw competitive order "
        f"(first evidence = {evidence[0].chunk_type})"
    )
