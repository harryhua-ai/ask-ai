"""P0+P1 Integration Gate — 组合契约回归(harness 全 mock,零 Weaviate 依赖)。

证明在同一棵 committed tree 上同时成立:
- P0 信任边界(可见性守卫 fail-closed、未知源拒、授权失败≠旁路、历史案例归因护栏)
- P1 生成可靠性(零内容=显式失败、部分中断不复播、正常流不误伤、拒答≠generation_error)

关键交叉场景(INT-G001..005,合同 §8):
- INT-G001 restricted-only → P0 拒答发生在 LLM 调用之前,P1 不得误分类为 empty_generation
- INT-G002 混合候选 → 仅公开源进入生成上下文,正常作答
- INT-G003 授权上下文 + 零 token → EmptyGenerationError(P1),错误路径不含受限内容
- INT-G004 部分 token 后中断 → token 已发出、异常向上传播(SSE 层按 stream_interrupted 处理)
- INT-G005 guard 崩溃 → 候选 fail-closed → 安全拒答,LLM 不被调用
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.pipeline.rag import REJECT_ANSWER, EmptyGenerationError, RAGOrchestrator
from backend.services.source_visibility import SourceVisibilityGuard
from tests.pipeline.test_rag import _make_llm_response, _make_sr

PUBLIC_SR = _make_sr(
    text="NE301 工作温度为 -20°C 至 +50°C。",
    source_id="website-camthink/product/neoeyes-301",
    source_type="web_crawl",
)
RESTRICTED_SR = _make_sr(
    text="内部工单:客户 ICCID 8901xxxx,APN data641003,报价 $268/市价 $30。",
    source_id="knowledge-cases/support/NE101-cellular.md",
    source_type="filesystem",
)
UNKNOWN_SR = _make_sr(
    text="幽灵 chunk:疑似内部跟进记录。",
    source_id="ghost-legacy/notes.md",
    source_type="filesystem",
)


class MappingGuard(SourceVisibilityGuard):
    """用确定性 mapping 驱动的真实守卫(继承生产语义,便于组合测试)。"""

    def __init__(self, mapping: dict[str, tuple[str, ...]]):
        super().__init__(loader=_loader_from(mapping), ttl=60)


def _loader_from(mapping):
    async def _load():
        return mapping

    return _load


class FakeLLM:
    """generate(意图)走 AsyncMock;stream(生成)可脚本化。"""

    def __init__(
        self, stream_chunks: list[str] | None = None, stream_error: Exception | None = None
    ):
        self.generate = AsyncMock(return_value=_make_llm_response(content="answer"))
        self.stream_chunks = stream_chunks
        self.stream_error = stream_error
        self.stream_messages: list | None = None

    async def stream(self, messages, task=None):
        self.stream_messages = messages
        for c in self.stream_chunks or []:
            yield c
        if self.stream_error:
            raise self.stream_error


def _build(searcher_results, *, guard=None, llm=None):
    searcher = MagicMock()
    searcher.search.return_value = list(searcher_results)
    searcher.search_symbols.return_value = []
    searcher.search_bucket.return_value = []
    reranker = MagicMock()
    reranker.rerank.side_effect = lambda query, results, top_k: list(results)
    llm = llm or FakeLLM()
    rag = RAGOrchestrator(
        searcher=searcher,
        reranker=reranker,
        llm=llm,
        system_prompt="base",
        min_results_to_answer=1,
        visibility_guard=guard,
    )
    return rag, llm


def _guard(mapping: dict[str, tuple[str, ...]] | None, *, error=None):
    if error:

        class _Boom:
            async def allows(self, source_id, channel):
                raise error

        return _Boom()
    if mapping is None:
        return None
    return MappingGuard(mapping)


def _events(rag, query="NE301 工作温度是多少"):
    async def _collect():
        out = []
        async for evt in rag.stream_answer(query, "widget"):
            out.append(json.loads(evt))
        return out

    return _collect()


# ---------------- INT-G001: restricted-only → 干净拒答,LLM 不被调用 ----------------


async def test_int_g001_restricted_only_yields_clean_refusal():
    rag, llm = _build([RESTRICTED_SR], guard=_guard({"knowledge-cases": ("internal",)}))

    events = [json.loads(e) async for e in rag.stream_answer("SIM 问题", "widget")]

    completes = [e for e in events if e["type"] == "complete"]
    assert len(completes) == 1 and completes[0]["is_answered"] is False
    assert REJECT_ANSWER in completes[0]["answer"]
    assert all(e["type"] != "sources" for e in events)  # 无可依据来源
    assert llm.stream_messages is None  # LLM 未被调用(理想拒答路径)
    # P1 不得把拒答误分类:无 error 事件
    assert all(e["type"] != "error" for e in events)


# ---------------- INT-G002: 混合候选 → 仅公开源入上下文,正常作答 ----------------


async def test_int_g002_mixed_candidates_only_public_enters_generation():
    mapping = {
        "website-camthink": ("widget", "api"),
        "knowledge-cases": ("internal",),
        # ghost-legacy 故意不配置(unknown → deny)
    }
    llm = FakeLLM(stream_chunks=["按资料回答"])
    rag, _ = _build([PUBLIC_SR, RESTRICTED_SR, UNKNOWN_SR], guard=_guard(mapping), llm=llm)

    events = [json.loads(e) async for e in rag.stream_answer("工作温度", "widget")]

    complete = next(e for e in events if e["type"] == "complete")
    assert complete["is_answered"] is True
    user_msg = llm.stream_messages[-1]["content"]
    assert "-20°C 至 +50°C" in user_msg
    assert "8901xxxx" not in user_msg and "内部跟进记录" not in user_msg
    sources = next(e for e in events if e["type"] == "sources")["sources"]
    # SSE sources 契约字段为 url/title/type/product;只允许公开源进入
    assert len(sources) == 1 and PUBLIC_SR.url in sources[0]["url"]


# ---------------- INT-G003: 授权上下文 + 零 token → 显式可靠性失败 ----------------


async def test_int_g003_authorized_context_with_zero_token_llm_raises_empty_generation():
    mapping = {
        "website-camthink": ("widget", "api"),
        "knowledge-cases": ("internal",),
    }
    llm = FakeLLM(stream_chunks=[])  # 200 但零 delta
    rag, _ = _build([PUBLIC_SR, RESTRICTED_SR], guard=_guard(mapping), llm=llm)

    events = []
    with pytest.raises(EmptyGenerationError):
        async for evt in rag.stream_answer("工作温度", "widget"):
            events.append(json.loads(evt))  # (保持)

    # 错误路径中的 messages 只含公开内容(受限源从未入上下文)
    user_msg = llm.stream_messages[-1]["content"]
    # 断言泄漏"值"而非"ICCID"字样——归因护栏模板本身合法地提到该词
    assert "-20°C 至 +50°C" in user_msg
    assert "8901xxxx" not in user_msg and "data641003" not in user_msg
    assert all(e["type"] != "complete" for e in events)  # 无伪成功


# ---------------- INT-G004: 部分 token 后中断 → 已发 token + 异常向上 ----------------


async def test_int_g004_partial_stream_failure_keeps_tokens_and_propagates():
    llm = FakeLLM(stream_chunks=["温度是 -20"], stream_error=RuntimeError("connection reset"))
    rag, _ = _build([PUBLIC_SR], guard=_guard({"website-camthink": ("widget", "api")}), llm=llm)

    events = []
    with pytest.raises(RuntimeError):
        async for evt in rag.stream_answer("工作温度", "widget"):
            events.append(json.loads(evt))  # (保持)

    tokens = [e["content"] for e in events if e["type"] == "token"]
    assert tokens == ["温度是 -20"]  # 部分内容保留(不复播、不吞)
    assert all(e["type"] != "complete" for e in events)  # 不伪装成功


# ---------------- INT-G005: guard 崩溃 → fail-closed → 安全拒答 ----------------


async def test_int_g005_guard_crash_fails_closed_to_refusal():
    rag, llm = _build(
        [PUBLIC_SR, RESTRICTED_SR],
        guard=_guard(None, error=RuntimeError("db down")),
    )

    events = [json.loads(e) async for e in rag.stream_answer("SIM 问题", "widget")]

    completes = [e for e in events if e["type"] == "complete"]
    assert len(completes) == 1 and completes[0]["is_answered"] is False
    assert REJECT_ANSWER in completes[0]["answer"]
    assert llm.stream_messages is None  # 原始候选绝不被放行进生成
    assert all(e["type"] != "error" for e in events)  # 拒答 ≠ generation_error


# ---------------- 组合黄金:真实守卫 + 陈旧快照(SEC-H003 集成级) ----------------


async def test_stale_snapshot_continues_to_authorize_within_contract():
    calls = {"n": 0}
    mapping = {"website-camthink": ("widget", "api")}

    async def flaky_loader():
        calls["n"] += 1
        if calls["n"] == 1:
            return mapping
        raise RuntimeError("refresh failed")

    llm = FakeLLM(stream_chunks=["ok"])
    rag, _ = _build([PUBLIC_SR], guard=SourceVisibilityGuard(flaky_loader, ttl=0), llm=llm)

    first = [json.loads(e) async for e in rag.stream_answer("q", "widget")]
    second = [json.loads(e) async for e in rag.stream_answer("q", "widget")]

    assert any(e["type"] == "complete" and e["is_answered"] for e in first)
    assert any(e["type"] == "complete" and e["is_answered"] for e in second)  # 陈旧快照沿用


# ---------------- CASE-G001: 模板护栏在组合树上仍然在场 ----------------


def test_attribution_guardrail_present_in_combined_tree():
    rag, _ = _build([PUBLIC_SR], guard=None)
    messages = rag._build_messages(
        query="q",
        context="[1] doc",
        language="zh-cn",
        history=None,
        channel="widget",
        intent="support",
    )
    assert "历史案例" in messages[-1]["content"]
