"""Integration Checkpoint Gate — INT-CHK-001/002 组合契约持久回归(全 mock,零 Weaviate)。

INT-CHK-001(Citation + P0):受限/幽灵候选被 P0 拦截后,citation 编号上下文只可能
来自公开源;对外 sources 与编号集合保持紧凑有效。
INT-CHK-002(Citation + Generation Reliability):零内容 / 仅悬空引用的生成必须仍是
显式失败(EmptyGenerationError),引用过滤不得把空/无效答案救成成功。
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.pipeline.rag import EmptyGenerationError, RAGOrchestrator
from backend.services.source_visibility import SourceVisibilityGuard
from tests.pipeline.test_rag import _make_llm_response, _make_sr

PUBLIC_SR = _make_sr(
    text="NE301 工作温度为 -20°C 至 +50°C。",
    source_id="website-camthink/product/neoeyes-301",
    source_type="web_crawl",
)
RESTRICTED_SR = _make_sr(
    text="内部工单:ICCID 8901xxxx,APN data641003,内部参考价 $55。",
    source_id="knowledge-cases/support/case.md",
    source_type="filesystem",
)
UNKNOWN_SR = _make_sr(
    text="幽灵 chunk:内部跟进记录。",
    source_id="ghost-legacy/notes.md",
    source_type="filesystem",
)


class MappingGuard(SourceVisibilityGuard):
    def __init__(self, mapping: dict[str, tuple[str, ...]]):
        async def _load():
            return mapping

        super().__init__(loader=_load, ttl=60)


class FakeLLM:
    def __init__(self, stream_chunks):
        self.generate = AsyncMock(return_value=_make_llm_response(content="answer"))
        self.stream_chunks = stream_chunks
        self.stream_messages: list | None = None

    async def stream(self, messages, task=None, **kwargs):
        self.stream_messages = messages
        for c in self.stream_chunks:
            yield c


def _build(searcher_results, *, mapping, stream_chunks):
    searcher = MagicMock()
    searcher.search.return_value = list(searcher_results)
    searcher.search_symbols.return_value = []
    searcher.search_bucket.return_value = []
    reranker = MagicMock()
    reranker.rerank.side_effect = lambda query, results, top_k: list(results)
    llm = FakeLLM(stream_chunks)
    rag = RAGOrchestrator(
        searcher=searcher,
        reranker=reranker,
        llm=llm,
        system_prompt="base",
        min_results_to_answer=1,
        visibility_guard=MappingGuard(mapping),
    )
    return rag, llm


async def _collect(rag, query="工作温度"):
    return [json.loads(e) async for e in rag.stream_answer(query, "widget")]


@pytest.mark.asyncio
async def test_int_chk_001_citation_numbering_only_over_public_after_p0():
    """INT-CHK-001:受限/幽灵源被 P0 拦截 → 不产生可见引用;编号紧凑有效。"""
    mapping = {
        "website-camthink": ("widget", "api"),
        "knowledge-cases": ("internal",),
    }
    rag, llm = _build(
        [PUBLIC_SR, RESTRICTED_SR, UNKNOWN_SR],
        mapping=mapping,
        stream_chunks=["NE301 工作温度为 -20°C 至 +50°C。[1]"],
    )

    events = await _collect(rag)
    complete = next(e for e in events if e["type"] == "complete")
    assert complete["is_answered"] is True
    # 可见 sources 只剩公开源
    assert len(complete["sources"]) == 1
    assert "example.com" in complete["sources"][0]["url"]
    # 生成上下文无受限内容;引用编号 1 且不超过可见源数
    user_msg = llm.stream_messages[-1]["content"]
    assert "8901xxxx" not in user_msg and "内部跟进记录" not in user_msg
    assert "[1]" in complete["answer"]
    assert "[2]" not in complete["answer"]  # 编号紧凑:只有 1 个可见源
    # 受限值也不曾作为 token 外发
    tokens = "".join(e["content"] for e in events if e["type"] == "token")
    assert "8901xxxx" not in tokens and "$55" not in tokens


@pytest.mark.asyncio
async def test_int_chk_002a_zero_generation_still_explicit_failure():
    """INT-CHK-002a:零内容生成在引用过滤在场时仍为显式失败。"""
    rag, _ = _build([PUBLIC_SR], mapping={"website-camthink": ("widget", "api")}, stream_chunks=[])

    with pytest.raises(EmptyGenerationError):
        async for _ in rag.stream_answer("工作温度", "widget"):
            pass


@pytest.mark.asyncio
async def test_int_chk_002b_citation_only_generation_with_all_dangling_is_failure():
    """INT-CHK-002b(Issue #19 修订):生成内容只有被剔除的悬空引用 → 不许伪装成功。

    旧合约断言抛 EmptyGenerationError;Issue #19 Empty-Generation Contract
    将该 C 型(资格耗尽)映射为显式不足语义 —— 失败属性不变
    (is_answered=False + result_key=no_evidence),只是不再谎报服务故障。"""
    rag, _ = _build(
        [PUBLIC_SR],
        mapping={"website-camthink": ("widget", "api")},
        stream_chunks=["[9] [7]"],  # 只有 1 个可见源 → 全部悬空被剔
    )

    completes = []
    async for raw in rag.stream_answer("工作温度", "widget"):
        e = json.loads(raw)
        if e.get("type") == "complete":
            completes.append(e)
    assert len(completes) == 1
    assert completes[0]["is_answered"] is False
    assert completes[0]["result_key"] == "no_evidence"
