"""社交对话识别与 off-topic 友好边界测试(OFFTOPIC Contract)。

产品语义:
- 社交/寒暄(你好/hello/谢谢/thanks/你是谁/你能做什么)→ 自然回应,
  不机械拒答,适当介绍 CamThink Assistant 能力,不进 RAG。
- 真正领域外请求(写诗/法国首都/贪吃蛇)→ 不进 RAG,但回应是友好边界
  + 能力引导,而非 system-style rejection。
- CamThink 产品问题不受影响(主流程零回归)。
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.llm.base import LLMResponse
from backend.pipeline.rag import RAGOrchestrator
from backend.pipeline.social import SocialKind, match_social
from backend.retrieval.search import SearchResult

# --------------------------------------------------------------------------- #
# match_social 单元测试
# --------------------------------------------------------------------------- #


@pytest.mark.unit
class TestMatchSocial:
    def test_greeting_zh(self):
        """OFFTOPIC-G003:你好 → 问候回应(zh)。"""
        hit = match_social("你好")
        assert hit is not None
        assert hit.kind is SocialKind.GREETING
        assert hit.reply

    def test_greeting_zh_with_punctuation(self):
        hit = match_social("你好呀!")
        assert hit is not None
        assert hit.kind is SocialKind.GREETING

    def test_greeting_en(self):
        """OFFTOPIC-G003+G008:hello → 英文自然问候。"""
        hit = match_social("Hello")
        assert hit is not None
        assert hit.kind is SocialKind.GREETING
        assert hit.language == "en"

    def test_thanks_zh_and_en(self):
        """OFFTOPIC-G004:谢谢/thanks → 自然回应。"""
        for text in ("谢谢", "多谢啦", "Thanks", "thank you"):
            hit = match_social(text)
            assert hit is not None, text
            assert hit.kind is SocialKind.THANKS

    def test_identity_introduces_assistant(self):
        """OFFTOPIC-G005:你是谁 → 正确介绍 CamThink Assistant。"""
        hit = match_social("你是谁")
        assert hit is not None
        assert hit.kind is SocialKind.IDENTITY
        assert "CamThink" in hit.reply

    def test_capability_introduces_scope(self):
        """OFFTOPIC-G005:你能做什么 → 介绍能力范围。"""
        hit = match_social("你能做什么")
        assert hit is not None
        assert hit.kind is SocialKind.CAPABILITY
        # 能力介绍须覆盖产品语义方向:选型/功能/方案/配置/支持 至少命中两项
        scope_words = ("选型", "功能", "方案", "配置", "支持")
        assert sum(w in hit.reply for w in scope_words) >= 2

    def test_capability_en(self):
        hit = match_social("What can you do?")
        assert hit is not None
        assert hit.kind is SocialKind.CAPABILITY
        assert hit.language == "en"

    def test_goodbye(self):
        hit = match_social("再见")
        assert hit is not None
        assert hit.kind is SocialKind.GOODBYE

    def test_product_question_with_greeting_prefix_not_social(self):
        """OFFTOPIC-G006 守门:带寒暄前缀的产品问题绝不能被社交匹配吞掉。"""
        assert match_social("你好,NE301 支持热成像入侵检测吗?") is None

    def test_product_question_not_social(self):
        assert match_social("NE301 多少钱") is None

    def test_domain_external_request_not_social(self):
        """领域外创作请求走 off_topic 边界(非 social),不进社交模板。"""
        assert match_social("帮我写一首关于秋天的诗") is None


# --------------------------------------------------------------------------- #
# 编排器行为测试
# --------------------------------------------------------------------------- #


def _make_llm_response(content: str = "answer") -> LLMResponse:
    return LLMResponse(
        content=content,
        model="test-model",
        tokens_input=10,
        tokens_output=5,
        latency_ms=50,
    )


def _intent_llm(category: str) -> tuple[MagicMock, MagicMock, AsyncMock]:
    """构造 searcher/reranker/llm,llm.generate 对 intent 任务返回指定分类。"""

    async def _generate(messages, **kwargs):
        task = kwargs.get("task", "")
        if task == "intent":
            return _make_llm_response(
                json.dumps({"category": category, "reason": "test", "confidence": 0.9})
            )
        return _make_llm_response("generated answer")

    searcher = MagicMock()
    searcher.search.return_value = [
        SearchResult(
            text="t",
            source_id="s",
            source_type="github",
            product="ne301",
            title="T",
            url="https://example.com",
            score=0.9,
            chunk_index=0,
        )
    ]
    reranker = MagicMock()
    reranker.rerank.return_value = searcher.search.return_value
    llm = AsyncMock()
    llm.generate.side_effect = _generate
    return searcher, reranker, llm


def _build_rag(category: str) -> tuple[RAGOrchestrator, MagicMock, MagicMock, AsyncMock]:
    searcher, reranker, llm = _intent_llm(category)
    rag = RAGOrchestrator(
        searcher=searcher,
        reranker=reranker,
        llm=llm,
        system_prompt="You are helpful.",
        min_results_to_answer=1,
    )
    return rag, searcher, reranker, llm


@pytest.mark.unit
async def test_off_topic_creative_request_gets_friendly_boundary():
    """OFFTOPIC-G001:无关创作请求 → 友好边界 + 能力引导,非 system-style 拒绝。"""
    rag, searcher, _, llm = _build_rag("off_topic")
    result = await rag.answer("帮我写一首关于秋天的诗", "widget")

    assert result.is_answered is False
    assert result.intent == "off_topic"
    assert "CamThink" in result.answer
    # 能力引导:告知可以帮什么
    assert ("选型" in result.answer) or ("功能" in result.answer) or ("方案" in result.answer)
    # 旧生硬话术必须退役
    assert result.answer != "我只能回答与 CamThink 产品相关的问题。"
    # short-circuit 保持:不进检索、不进生成
    searcher.search.assert_not_called()
    generate_calls = [c for c in llm.generate.call_args_list if c.kwargs.get("task") != "intent"]
    assert generate_calls == []


@pytest.mark.unit
async def test_off_topic_general_question_gets_friendly_boundary_en():
    """OFFTOPIC-G002+G008:英文领域外问题 → 英文友好边界。"""
    rag, _, _, _ = _build_rag("off_topic")
    result = await rag.answer("What is the capital of France?", "widget")

    assert result.is_answered is False
    assert result.intent == "off_topic"
    assert "CamThink" in result.answer


@pytest.mark.unit
async def test_greeting_short_circuits_before_intent_llm():
    """OFFTOPIC-G003:你好 → 自然问候;确定性短路,连 intent LLM 都不调。"""
    rag, searcher, _, llm = _build_rag("off_topic")
    result = await rag.answer("你好", "widget")

    assert "CamThink" in result.answer
    assert result.intent == "smalltalk"
    assert result.sources == []
    searcher.search.assert_not_called()
    llm.generate.assert_not_called()


@pytest.mark.unit
async def test_identity_reply_introduces_assistant():
    """OFFTOPIC-G005:你是谁 → 介绍 CamThink Assistant 能力,非拒答。"""
    rag, _, _, _ = _build_rag("off_topic")
    result = await rag.answer("你是谁", "widget")

    assert "CamThink" in result.answer
    assert result.intent == "smalltalk"
    assert result.is_answered is True


@pytest.mark.unit
async def test_product_question_still_enters_rag():
    """OFFTOPIC-G006/G007:产品问题正常走完整 RAG,零回归。"""
    rag, searcher, _, llm = _build_rag("product")
    result = await rag.answer("你好,NE301 支持热成像入侵检测吗?", "widget")

    assert result.is_answered is True
    assert result.intent == "product"
    assert result.answer == "generated answer"
    searcher.search.assert_called_once()
    assert result.sources  # 正常产出引用


@pytest.mark.unit
async def test_stream_greeting_yields_smalltalk_reply():
    """流式路径 parity:问候 → 单一 complete 事件,intent=smalltalk。"""
    rag, searcher, _, llm = _build_rag("off_topic")
    events = [json.loads(evt) async for evt in rag.stream_answer("hello", "widget")]

    assert len(events) == 1
    evt = events[0]
    assert evt["type"] == "complete"
    assert evt["intent"] == "smalltalk"
    assert "CamThink" in evt["answer"]
    assert evt["sources"] == []
    searcher.search.assert_not_called()
    llm.generate.assert_not_called()


@pytest.mark.unit
async def test_stream_off_topic_friendly_boundary():
    """流式路径 parity:off_topic → 友好边界话术。"""
    rag, _, _, _ = _build_rag("off_topic")
    events = [json.loads(evt) async for evt in rag.stream_answer("帮我写 Python 贪吃蛇", "widget")]

    assert len(events) == 1
    evt = events[0]
    assert evt["type"] == "complete"
    assert evt["intent"] == "off_topic"
    assert "CamThink" in evt["answer"]
