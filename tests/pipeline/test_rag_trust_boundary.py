"""P0 知识信任边界 — RAGOrchestrator 层边界测试(PC-01/PC-04/AC-04)。

行为契约:
- visibility_guard 判定为不可见的候选,必须在进入 rerank / LLM 上下文**之前**被丢弃
  (安全发生在生成前,而非仅隐藏返回的 sources —— NA-01/NA-04 反例)。
- guard 对 admin 渠道必须按 widget(访客等价)探测(AC-06)。
- guard 自身故障时 fail-open(降级依赖 chunk 级 channel_visibility 过滤这一主防线),
  不得让整条检索链路不可用。
- PC-04:用户模板必须携带历史案例归因护栏(硬编码于代码模板,不受 DB customization 覆盖)。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml

from backend.pipeline.rag import RAGOrchestrator
from tests.pipeline.test_rag import _make_llm_response, _make_sr

RESTRICTED_SR = _make_sr(
    text="历史工单:客户 ICCID 8901xxxx 已更换 SIM,APN data641003 修复注册问题。",
    source_id="knowledge-cases/support/NE101-cellular.md",
    source_type="filesystem",
    title="内部支持案例",
    url="",
)
PUBLIC_SR = _make_sr(
    text="NE101 由 USB-C 5V/1A 供电。",
    source_id="github-wiki/neoeyes-ne101/power.md",
    source_type="github",
)


class FakeGuard:
    """注入式 guard:按 source_id 前缀判定,记录 probe channel。"""

    def __init__(self, forbidden_prefixes: set[str], *, error: Exception | None = None):
        self.forbidden_prefixes = forbidden_prefixes
        self.error = error
        self.seen: list[tuple[str, str | None]] = []

    async def allows(self, source_id: str, channel: str | None) -> bool:
        if self.error:
            raise self.error
        self.seen.append((source_id, channel))
        prefix = source_id.split("/")[0]
        return prefix not in self.forbidden_prefixes


def _build(searcher_results, *, guard=None) -> tuple[RAGOrchestrator, MagicMock, AsyncMock]:
    """构造预填 mock 的 orchestrator(rerank 原样透传,llm 捕获 messages)。"""
    searcher = MagicMock()
    searcher.search.return_value = list(searcher_results)
    searcher.search_symbols.return_value = []
    searcher.search_bucket.return_value = []

    reranker = MagicMock()
    reranker.rerank.side_effect = lambda query, results, top_k: list(results)

    llm = AsyncMock()
    llm.generate.return_value = _make_llm_response(content="answer")

    rag = RAGOrchestrator(
        searcher=searcher,
        reranker=reranker,
        llm=llm,
        system_prompt="base",
        min_results_to_answer=1,
        visibility_guard=guard,
    )
    return rag, reranker, llm


@pytest.mark.asyncio
async def test_restricted_candidate_never_reaches_rerank_or_context():
    """PC-01:restricted 候选必须在 rerank 前被丢弃,不得进入 LLM 上下文。"""
    guard = FakeGuard({"knowledge-cases"})
    rag, reranker, llm = _build([PUBLIC_SR, RESTRICTED_SR], guard=guard)

    await rag.answer(query="我的 NE101 传不上云怎么办", channel="widget")

    reranked_inputs = [r for call in reranker.rerank.call_args_list for r in call.args[1]]
    assert RESTRICTED_SR.source_id not in {r.source_id for r in reranked_inputs}
    assert PUBLIC_SR.source_id in {r.source_id for r in reranked_inputs}

    user_msg = llm.generate.call_args.args[0][-1]["content"]
    assert "8901xxxx" not in user_msg
    assert "NE101 由 USB-C 5V/1A 供电" in user_msg


@pytest.mark.asyncio
async def test_stream_answer_also_enforces_boundary():
    """AC-04:stream_answer 与 answer 共用检索收口,restricted 同样不进上下文。"""
    guard = FakeGuard({"knowledge-cases"})
    rag, reranker, _llm = _build([RESTRICTED_SR], guard=guard)

    chunks = [c async for c in rag.stream_answer(query="SIM 注册被拒", channel="widget")]

    reranked_inputs = [r for call in reranker.rerank.call_args_list for r in call.args[1]]
    assert RESTRICTED_SR.source_id not in {r.source_id for r in reranked_inputs}
    # 全部候选被拦 → 无候选可依据 → 拒答而非凭空作答
    assert not any(
        c.get("content") and "8901xxxx" in c["content"] for c in chunks if isinstance(c, dict)
    )


@pytest.mark.asyncio
async def test_admin_channel_probes_as_widget_visitor_equivalent():
    """AC-06:admin 渠道按 widget 探针判定,不得因 admin 身份获得内部知识。"""
    guard = FakeGuard({"knowledge-cases"})
    rag, _, llm = _build([RESTRICTED_SR], guard=guard)

    await rag.answer(query="SIM 注册问题", channel="admin")

    assert guard.seen, "guard 应被调用"
    assert all(ch == "admin" for _, ch in guard.seen)  # guard 收原始渠道
    user_msg = llm.generate.call_args.args[0][-1]["content"]
    assert "8901xxxx" not in user_msg


@pytest.mark.asyncio
async def test_guard_failure_fails_open_relying_on_chunk_filter():
    """guard 故障时 fail-open:主防线是 chunk 级 channel_visibility 过滤,不得整体不可用。"""
    guard = FakeGuard({"knowledge-cases"}, error=RuntimeError("db down"))
    rag, reranker, _ = _build([RESTRICTED_SR], guard=guard)

    result = await rag.answer(query="SIM 注册问题", channel="widget")

    reranked_inputs = [r for call in reranker.rerank.call_args_list for r in call.args[1]]
    assert RESTRICTED_SR.source_id in {r.source_id for r in reranked_inputs}
    assert result.answer == "answer"


@pytest.mark.asyncio
async def test_public_knowledge_unaffected_by_guard():
    """AC-05:guard 在场时公开知识照常进入上下文(无检索塌陷)。"""
    guard = FakeGuard({"knowledge-cases"})
    rag, _, llm = _build([PUBLIC_SR], guard=guard)

    await rag.answer(query="NE101 供电要求", channel="widget")

    user_msg = llm.generate.call_args.args[0][-1]["content"]
    assert "5V/1A" in user_msg


def test_user_template_carries_attribution_guardrail():
    """PC-04:归因护栏硬编码在代码用户模板中(不受 DB customization 覆盖)。"""
    rag, _, _llm = _build([PUBLIC_SR], guard=None)
    messages = rag._build_messages(
        query="q",
        context="[1] [GitHub] doc\ncontent",
        language="zh-cn",
        history=None,
        channel="widget",
        intent="support",
    )
    user_content = messages[-1]["content"]
    assert "历史案例" in user_content
    assert "当前用户" in user_content
    assert "ICCID" in user_content


def test_system_prompt_yaml_carries_attribution_guardrail(config_dir):
    """PC-04:yaml guardrails/system_prompt 同步携带归因护栏。"""
    cfg = yaml.safe_load((config_dir / "system_prompt.yaml").read_text(encoding="utf-8"))
    guardrails = cfg["guardrails"]
    assert "历史案例" in guardrails
    assert "当前用户" in guardrails
    assert "ICCID" in guardrails
