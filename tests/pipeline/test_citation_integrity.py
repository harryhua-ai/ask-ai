"""P1 Citation Integrity 测试(CIT-01 引用索引完整性 + CIT-02 主张↔证据完整性)。

覆盖 Frozen Contract Golden 场景 CIT-G001..G010:

- CIT-01(确定性保证):
  - LLM 上下文编号与访客可见 sources 是同一权威集合(公开白名单 + 去重 + 截 5);
  - 内部(filesystem)chunk 进背景资料段,无 [N] 编号,不可被引用;
  - 流式 token 中悬空 / 越界 / [0] 标记在下行前被确定性剔除;
  - 跨 token 拆分的标记、代码块、Markdown 链接均正确处理;
  - 多轮之间过滤状态隔离,无陈旧映射。
- CIT-02(V1 边界):
  - 精确数值主张必须能在所引来源文本中找到(归一化数字匹配),
    否则该引用标记被剔除(移除虚假引用权威,不删主张文本);
  - 有据的精确回答不受影响(G005 不过度拦截)。

同步路径 ``answer()`` 用 ``validate_citations`` 做同样的幂等终验。
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.llm.base import LLMResponse
from backend.pipeline.citation import (
    build_citation_context,
    validate_citations,
)
from backend.pipeline.rag import EmptyGenerationError, RAGOrchestrator
from backend.retrieval.search import SearchResult

# --------------------------------------------------------------------------- #
# 测试辅助
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


def _make_llm_response(content: str = "answer") -> LLMResponse:
    return LLMResponse(
        content=content,
        model="test-model",
        tokens_input=10,
        tokens_output=5,
        latency_ms=50,
    )


def _build_orchestrator(
    *,
    reranked_results: list[SearchResult],
    stream_chunks: list[str] | None = None,
    llm_content: str = "answer",
):
    """构造预填 mock 的 RAGOrchestrator,返回 (rag, searcher, reranker, llm)。"""
    searcher = MagicMock()
    searcher.search.return_value = list(reranked_results)
    searcher.search_symbols.return_value = []
    searcher.search_bucket.return_value = []

    reranker = MagicMock()
    reranker.rerank.return_value = list(reranked_results)

    llm = AsyncMock()
    llm.generate.return_value = _make_llm_response(llm_content)

    if stream_chunks is not None:
        captured: dict = {}

        def _fake_stream(messages, task=None):
            captured["messages"] = messages

            async def _gen():
                for c in stream_chunks:
                    yield c

            return _gen()

        llm.stream = _fake_stream
        llm.captured = captured

    rag = RAGOrchestrator(
        searcher=searcher,
        reranker=reranker,
        llm=llm,
        system_prompt="You are helpful.",
        min_results_to_answer=1,
    )
    return rag, searcher, reranker, llm


async def _collect_stream(rag, query="question"):
    """跑 stream_answer,返回 (events, messages_seen)。"""
    events = []
    async for raw in rag.stream_answer(query):
        events.append(json.loads(raw))
    return events


# --------------------------------------------------------------------------- #
# 单元:build_citation_context — 权威编号集合(CIT-01 根治)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
class TestBuildCitationContext:
    def test_numbering_matches_visible_sources(self):
        """CIT-G003:编号只来自访客可见集合;filesystem 进背景段无编号。

        rerank 序 = [公开B, 内部F, 公开C] → 可见 sources=[B, C],
        上下文编号必须为 [1]=B、[2]=C,F 出现在背景段且不带 [3]。
        """
        b = _make_sr(
            text="B 内容",
            source_type="github",
            title="Pub B",
            url="https://example.com/b",
            source_id="b",
        )
        f = _make_sr(
            text="F 内部案例",
            source_type="filesystem",
            title="Int F",
            url="file:///f",
            source_id="f",
        )
        c = _make_sr(
            text="C 内容",
            source_type="website",
            title="Pub C",
            url="https://example.com/c",
            source_id="c",
        )
        sources = [
            {"url": b.url, "title": b.title, "type": b.source_type, "product": b.product},
            {"url": c.url, "title": c.title, "type": c.source_type, "product": c.product},
        ]
        ctx = build_citation_context([b, f, c], sources)
        # [1] 紧邻 B,[2] 紧邻 C;B 先于 C(保持 rerank 顺序压缩编号)
        assert ctx.context.index("[1] ") < ctx.context.index("Pub B")
        assert ctx.context.index("[2] ") < ctx.context.index("Pub C")
        assert ctx.context.index("Pub B") < ctx.context.index("Pub C")
        # F 不拿编号,进背景段
        assert "[3]" not in ctx.context
        assert "F 内部案例" in ctx.context
        assert "背景资料" in ctx.context
        assert ctx.stats["background_chunks"] == 1

    def test_public_pages_beyond_five_dropped_from_context(self):
        """第 6 个公开页的 chunk 不可进入编号上下文(否则可被引用但不可见)。"""
        results = [
            _make_sr(
                text=f"page{i} 内容",
                title=f"P{i}",
                url=f"https://example.com/p{i}",
                source_id=f"p{i}",
            )
            for i in range(6)
        ]
        sources = [
            {"url": r.url, "title": r.title, "type": r.source_type, "product": r.product}
            for r in results[:5]
        ]
        ctx = build_citation_context(results, sources)
        assert "page5 内容" not in ctx.context
        assert ctx.stats["dropped_public_chunks"] >= 1

    def test_source_texts_map_for_support_check(self):
        """编号 → 该源全部 chunk 文本的映射(数值支持校验的数据基础)。"""
        a1 = _make_sr(
            text="温度 -20 到 50",
            url="https://example.com/a",
            source_id="a",
            title="A",
        )
        a2 = _make_sr(
            text="补充:IP67",
            url="https://example.com/a",
            source_id="a",
            title="A",
            chunk_index=1,
        )
        sources = [
            {"url": a1.url, "title": a1.title, "type": a1.source_type, "product": a1.product}
        ]
        ctx = build_citation_context([a1, a2], sources)
        assert len(ctx.source_texts[1]) == 2
        assert any("IP67" in t for t in ctx.source_texts[1])

    def test_duplicate_translation_chunks_share_one_number(self):
        """同文档多 chunk(同 URL)共享同一编号,不产生 1..N 假编号集。"""
        a1 = _make_sr(text="中文版内容", url="https://e.com/d", source_id="d", title="D")
        a2 = _make_sr(
            text="english content",
            url="https://e.com/d",
            source_id="d",
            title="D",
            chunk_index=1,
        )
        sources = [
            {"url": a1.url, "title": a1.title, "type": a1.source_type, "product": a1.product}
        ]
        ctx = build_citation_context([a1, a2], sources)
        assert ctx.context.count("[1] ") >= 1
        assert "[2] " not in ctx.context


# --------------------------------------------------------------------------- #
# 单元:CitationStreamFilter — 流式确定性校验
# --------------------------------------------------------------------------- #


@pytest.mark.unit
class TestCitationStreamFilter:
    def _filter(self, n=2, texts=None):
        from backend.pipeline.citation import CitationStreamFilter

        return CitationStreamFilter(n_sources=n, source_texts=texts or {})

    def test_valid_marker_passes(self):
        f = self._filter()
        out = f.feed("这是答案[1]")
        out += f.finish()
        assert out == "这是答案[1]"
        assert f.stats["markers_seen"] == 1
        assert f.stats["dangling_dropped"] == 0

    def test_dangling_marker_dropped(self):
        """CIT-G001/G002:[n] 超出可见集合 → 剔除,不透传给访客。"""
        f = self._filter(n=1)
        out = f.feed("有据[1] 幻觉[2] 幻觉[3]")
        out += f.finish()
        assert "[2]" not in out
        assert "[3]" not in out
        assert "[1]" in out
        assert f.stats["dangling_dropped"] == 2

    def test_zero_and_multi_digit_not_markers(self):
        """[0] 属悬空剔除;[1234](如年份)不按引用标记处理,原样透传。"""
        f = self._filter(n=1)
        out = f.feed("见 [0] 与 [1234]")
        out += f.finish()
        assert "[0]" not in out
        assert "[1234]" in out

    def test_marker_split_across_chunks(self):
        """跨 token 拆分(如 '[' 与 '2]' 分属两个 chunk)仍被正确解析。"""
        f = self._filter(n=2)
        parts = []
        for chunk in ["答案[", "2", "]继续"]:
            parts.append(f.feed(chunk))
        parts.append(f.finish())
        out = "".join(parts)
        assert out == "答案[2]继续"

    def test_markdown_link_not_treated_as_citation(self):
        """[1](url) 是 Markdown 链接,不是引用标记,原样保留。"""
        f = self._filter(n=1)
        out = f.feed("详见 [1](https://example.com/a)")
        out += f.finish()
        assert out == "详见 [1](https://example.com/a)"
        assert f.stats["markers_seen"] == 0

    def test_code_fence_bypassed(self):
        """代码块内的 [9] 不是引用标记(即使越界也不改写代码)。"""
        f = self._filter(n=1)
        text = '```json\n{"arr": [9]}\n```'
        out = f.feed(text)
        out += f.finish()
        assert out == text
        assert f.stats["dangling_dropped"] == 0

    def test_unsupported_number_drops_marker(self):
        """CIT-G004:主张数字不在所引来源 → 剔除标记(移除虚假权威)。"""
        f = self._filter(n=1, texts={1: ["价格区间 $69–112,覆盖多数型号"]})
        out = f.feed("WiFi 样品价格 $59[1]")
        out += f.finish()
        assert out == "WiFi 样品价格 $59"
        assert f.stats["unsupported_dropped"] == 1

    def test_supported_number_keeps_marker(self):
        """CIT-G005:有据精确回答不受影响(归一化匹配 ℃/°C、波浪号等)。"""
        f = self._filter(n=1, texts={1: ["工作温度:-20℃~+50℃(_ip67)"]})
        out = f.feed("工作温度为 -20°C 至 +50°C[1]")
        out += f.finish()
        assert out == "工作温度为 -20°C 至 +50°C[1]"
        assert f.stats["unsupported_dropped"] == 0

    def test_single_digit_with_unit_checked(self):
        """单位相邻的单数字(7V/5V)参与校验;无单位的小数字不误伤。"""
        f = self._filter(n=1, texts={1: ["供电 5V USB-C 输入"]})
        out = f.feed("支持 7V 输入[1]")
        out += f.finish()
        assert "[1]" not in out
        f2 = self._filter(n=1, texts={1: ["供电 5V USB-C 输入"]})
        out2 = f2.feed("采用 5V 输入[1]")
        out2 += f2.finish()
        assert "[1]" in out2

    def test_window_resets_after_marker(self):
        """CIT-G007:逐段归因——段1 数字只对 [1] 校验,段2 只对 [2]。"""
        f = self._filter(n=2, texts={1: ["A 价 $59"], 2: ["B 价 $79"]})
        out = f.feed("A 型 $59[1]\n\nB 型 $79[2]")
        out += f.finish()
        assert out == "A 型 $59[1]\n\nB 型 $79[2]"

    def test_number_boundary_matching(self):
        """59 不得匹配 1590;59 可匹配 $59.9(容忍截断,防过度拦截)。"""
        f = self._filter(n=1, texts={1: ["型号 1590 系列"]})
        out = f.feed("价格 $59[1]")
        out += f.finish()
        assert "[1]" not in out

        f2 = self._filter(n=1, texts={1: ["售价 $59.9 起"]})
        out2 = f2.feed("售价 $59[1]")
        out2 += f2.finish()
        assert "[1]" in out2

    def test_finish_flushes_pending_literal(self):
        """流在半截标记处结束:未成形标记按字面量冲刷,不吞内容。"""
        f = self._filter(n=1)
        out = f.feed("文本 [")
        out += f.finish()
        assert out == "文本 ["

    def test_thousands_separator_normalized(self):
        """1,200 与 1200 互相匹配(千分位归一化)。"""
        f = self._filter(n=1, texts={1: ["容量 1,200 mAh"]})
        out = f.feed("电池容量 1200mAh[1]")
        out += f.finish()
        assert "[1]" in out


# --------------------------------------------------------------------------- #
# 单元:validate_citations — 同步路径幂等终验
# --------------------------------------------------------------------------- #


@pytest.mark.unit
class TestValidateCitations:
    def test_valid_answer_unchanged(self):
        answer = "段落一[1]\n\n段落二[2]"
        repaired, stats = validate_citations(answer, 2, {})
        assert repaired == answer
        assert stats["dangling_dropped"] == 0

    def test_dangling_repaired(self):
        repaired, stats = validate_citations("答案[1][4]", 1, {})
        assert repaired == "答案[1]"
        assert stats["dangling_dropped"] == 1

    def test_unsupported_number_repaired(self):
        repaired, stats = validate_citations("价格 $59[1]", 1, {1: ["价格 $69-112"]})
        assert repaired == "价格 $59"
        assert stats["unsupported_dropped"] == 1

    def test_idempotent(self):
        once, _ = validate_citations("A[1] B[9]", 1, {})
        twice, _ = validate_citations(once, 1, {})
        assert once == twice


# --------------------------------------------------------------------------- #
# 集成:RAGOrchestrator.stream_answer(CIT Golden 场景)
# --------------------------------------------------------------------------- #


@pytest.mark.integration
class TestStreamCitationGolden:
    async def test_cit_g002_g003_filtering_and_numbering(self):
        """CIT-G002/G003:公开+内部候选 → 编号压缩;幻影 [3] 不透传。"""
        b = _make_sr(
            text="B 公开内容",
            source_type="github",
            title="Pub B",
            url="https://example.com/b",
            source_id="b",
        )
        f = _make_sr(
            text="F 内部案例",
            source_type="filesystem",
            title="Int F",
            url="file:///f",
            source_id="f",
        )
        c = _make_sr(
            text="C 公开内容",
            source_type="website",
            title="Pub C",
            url="https://example.com/c",
            source_id="c",
        )
        rag, _, _, llm = _build_orchestrator(
            reranked_results=[b, f, c],
            stream_chunks=["X[1] Y[2] 幻[3]"],
        )
        events = await _collect_stream(rag)

        src_evt = next(e for e in events if e["type"] == "sources")
        assert [s["title"] for s in src_evt["sources"]] == ["Pub B", "Pub C"]

        # LLM 上下文编号 = 访客编号:[1]=B、[2]=C,F 在背景段
        user_msg = llm.captured["messages"][-1]["content"]
        assert user_msg.index("[1] ") < user_msg.index("Pub B") < user_msg.index("[2] ")
        assert "[3]" not in user_msg
        assert "F 内部案例" in user_msg
        assert "背景资料" in user_msg

        answer = "".join(e["content"] for e in events if e["type"] == "token")
        assert answer == "X[1] Y[2] 幻"

        comp = next(e for e in events if e["type"] == "complete")
        assert comp["answer"] == "X[1] Y[2] 幻"
        assert comp["is_answered"] is True
        assert comp["trace_payload"]["stages"]["citation_integrity"]["dangling_dropped"] == 1

    async def test_cit_g001_all_markers_map(self):
        """CIT-G001:全部标记均映射到可见源 → 原样透传,stats 零剔除。"""
        a = _make_sr(text="A", title="A", url="https://e.com/a", source_id="a")
        b = _make_sr(text="B", title="B", url="https://e.com/b", source_id="b")
        rag, _, _, _ = _build_orchestrator(reranked_results=[a, b], stream_chunks=["甲[1] 乙[2]"])
        events = await _collect_stream(rag)
        answer = "".join(e["content"] for e in events if e["type"] == "token")
        assert answer == "甲[1] 乙[2]"

    async def test_cit_g004_unsupported_price_number(self):
        """CIT-G004:$59 不在来源($69–112)→ 标记剔除,主张文本保留。"""
        a = _make_sr(text="价格区间 $69–112", title="A", url="https://e.com/a", source_id="a")
        rag, _, _, _ = _build_orchestrator(reranked_results=[a], stream_chunks=["WiFi 样品 $59[1]"])
        events = await _collect_stream(rag)
        answer = "".join(e["content"] for e in events if e["type"] == "token")
        assert answer == "WiFi 样品 $59"
        comp = next(e for e in events if e["type"] == "complete")
        assert comp["answer"] == "WiFi 样品 $59"
        assert comp["trace_payload"]["stages"]["citation_integrity"]["unsupported_dropped"] == 1

    async def test_cit_g005_supported_temperature_answer(self):
        """CIT-G005:有据温度回答正常成功,不过度拦截。"""
        a = _make_sr(text="工作温度:-20℃~+50℃", title="A", url="https://e.com/a", source_id="a")
        rag, _, _, _ = _build_orchestrator(
            reranked_results=[a], stream_chunks=["工作温度 -20°C 至 +50°C[1]"]
        )
        events = await _collect_stream(rag)
        comp = next(e for e in events if e["type"] == "complete")
        assert comp["is_answered"] is True
        answer = "".join(e["content"] for e in events if e["type"] == "token")
        assert answer == "工作温度 -20°C 至 +50°C[1]"

    async def test_cit_g009_multi_turn_isolation(self):
        """CIT-G009:第二轮编号集合更新,无第一轮陈旧映射。"""
        a = _make_sr(text="A", title="A", url="https://e.com/a", source_id="a")
        b = _make_sr(text="B", title="B", url="https://e.com/b", source_id="b")
        rag, _, reranker, _ = _build_orchestrator(
            reranked_results=[a, b], stream_chunks=["第一轮[1][2]"]
        )
        first = await _collect_stream(rag)
        first_answer = "".join(e["content"] for e in first if e["type"] == "token")
        assert first_answer == "第一轮[1][2]"

        # 第二轮:只剩一个可见源,同样的回答文本 [2] 变悬空
        reranker.rerank.return_value = [a]

        def _fake_stream2(messages, task=None):
            async def _gen():
                yield "第二轮[1][2]"

            return _gen()

        rag._llm.stream = _fake_stream2
        second = await _collect_stream(rag)
        second_answer = "".join(e["content"] for e in second if e["type"] == "token")
        assert second_answer == "第二轮[1]"

    async def test_cit_g010_zero_content_still_raises(self):
        """CIT-G010(Issue #19 修订):标记耗尽 → 不足语义 complete,绝伪装成功。

        旧合约:零可用内容抛 EmptyGenerationError。Issue #19(Empty-
        Generation Contract)将 C 型(资格耗尽:唯一内容是被剔除标记)映射
        为显式不足语义(complete is_answered=False + result_key),与
        B 型(模型零内容,无剔除→仍抛 EmptyGenerationError)分型。
        安全不变量不变:绝不伪装成功。"""
        a = _make_sr(text="A", title="A", url="https://e.com/a", source_id="a")
        # 流唯一内容是悬空标记 [99] → 被校验层剔除后零可用内容 → C 型不足语义
        rag, _, _, _ = _build_orchestrator(reranked_results=[a], stream_chunks=["[99]"])
        events = await _collect_stream(rag)
        completes = [e for e in events if e["type"] == "complete"]
        assert len(completes) == 1
        assert completes[0]["is_answered"] is False
        assert completes[0]["result_key"] == "no_evidence"  # 无产品边界 → 既有拒答键
        assert not any(e["type"] == "token" for e in events)

    async def test_prompt_contract_carries_evidence_binding(self):
        """CIT-02 prompt 契约:证据绑定与禁止编造数值的要求进入用户消息。"""
        a = _make_sr(text="A", title="A", url="https://e.com/a", source_id="a")
        rag, _, _, llm = _build_orchestrator(reranked_results=[a], stream_chunks=["ok"])
        await _collect_stream(rag)
        user_msg = llm.captured["messages"][-1]["content"]
        assert "可引用资料" in user_msg
        assert "背景资料" in user_msg
        assert "严禁编造" in user_msg


# --------------------------------------------------------------------------- #
# 集成:同步 answer() 路径
# --------------------------------------------------------------------------- #


@pytest.mark.integration
class TestSyncAnswerCitation:
    async def test_sync_answer_repairs_dangling_and_unsupported(self):
        """同步路径:悬空 + 无据数值标记在终验中被剔除。"""
        a = _make_sr(text="价格 $69–112", title="A", url="https://e.com/a", source_id="a")
        rag, _, _, _ = _build_orchestrator(reranked_results=[a], llm_content="价格 $59[1] 幻[2]")
        result = await rag.answer("价格多少")
        assert result.answer == "价格 $59 幻"
        assert result.is_answered is True
        assert result.trace_payload["stages"]["citation_integrity"]["dangling_dropped"] == 1
        assert result.trace_payload["stages"]["citation_integrity"]["unsupported_dropped"] == 1

    async def test_cit_g008_reject_path_unchanged(self):
        """CIT-G008:真无召回 → 拒答不变,不产生引用。"""
        rag, _, _, _ = _build_orchestrator(reranked_results=[])
        rag._searcher.search.return_value = []
        rag._searcher.search_symbols.return_value = []
        rag._searcher.search_bucket.return_value = []
        result = await rag.answer("不存在的东西")
        assert result.is_answered is False
        assert result.sources == []
