"""P1 Three-Site Multilingual Behavior Closure —— ML 门用例(管线层)。

冻结语义(CAMTHINK V1 P1 Three-Site Multilingual Behavior Closure):
- ANSWER_LANGUAGE:请求语言提示(宿主页面/站点默认)作为**默认答案语境**被
  消费(G-L1);文本确定性检出 CJK(显式用户语言表达)时覆盖宿主默认;
  无提示路径与基线逐字一致(detect_language 原值,零回归)。
- UI_LANGUAGE / ANSWER_LANGUAGE 分离:社交/边界/lead 文案跟随答案语言语境。
- Citation Integrity / canonical Wiki URL / Headless 兼容在语言提示下不回归。

WIDGET 侧解析链与 UI 文案门(ML-G003/004 UI 面/005)在 widget vitest
(``widget/src/utils/__tests__/language.test.ts`` 等)承载,本文件不重复。
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.llm.base import LLMResponse
from backend.pipeline.lead_qualify import (
    LEAD_ACK_INSTRUCTION,
    LEAD_INVITE_INSTRUCTION,
    LeadTurnContext,
    detect_contact,
)
from backend.pipeline.rag import OFF_TOPIC_REPLY_ZH, RAGOrchestrator
from backend.pipeline.social import match_social
from backend.retrieval.search import SearchResult
from backend.utils.language import normalize_language, resolve_answer_language

WIKI_BLOB = "https://github.com/camthink-ai/wiki-documents/blob/main"
WIKI_CANONICAL = "https://wiki.camthink.ai/docs/neoeyes-ne301-series/overview"


def _resp(content: str) -> LLMResponse:
    return LLMResponse(content=content, model="t", tokens_input=1, tokens_output=1, latency_ms=1)


def _sr(url: str, source_type: str = "github", text: str = "NE301 概述", score: float = 0.9):
    return SearchResult(
        text=text,
        source_id="src",
        source_type=source_type,
        product="ne301",
        title="T",
        url=url,
        score=score,
        chunk_index=0,
    )


def _gate_llm(*, intent="product", answer="回答内容"):
    """按 task 分发的 mock LLM;记录流式与同步生成 messages(语言指令断言)。"""
    llm = AsyncMock()
    gen_messages: list[list[dict]] = []

    async def _generate(messages, **kwargs):
        task = kwargs.get("task", "generation")
        if task == "intent":
            return _resp(json.dumps({"category": intent, "reason": "r", "confidence": 0.9}))
        if task == "lead_qualification":
            return _resp(json.dumps({"lead_level": "qualified"}, ensure_ascii=False))
        if task == "query_rewrite":
            return _resp("rewritten")
        gen_messages.append(messages)
        return _resp(answer)

    llm.generate = AsyncMock(side_effect=_generate)

    async def _stream(messages, **kwargs):
        gen_messages.append(messages)
        yield "回答"
        yield "内容"

    llm.stream = _stream
    return llm, gen_messages


def _make_rag(llm, results):
    searcher = MagicMock()
    searcher.search.return_value = results
    searcher.search_symbols.return_value = []
    searcher.search_bucket.return_value = []
    reranker = MagicMock()
    reranker.rerank.return_value = results
    return RAGOrchestrator(searcher, reranker, llm, system_prompt="sys", min_results_to_answer=1)


async def _collect(rag, query, **kwargs):
    events = []
    async for chunk in rag.stream_answer(query, "widget", **kwargs):
        events.append(json.loads(chunk))
    return events


def _system_of(messages: list[dict]) -> str:
    return messages[0]["content"]


def _full_text(messages: list[dict]) -> str:
    """全部消息内容拼接(语言指令在 user 模板尾部,不在 system)。"""
    return "\n".join(str(m.get("content", "")) for m in messages)


# --------------------------------------------------------------------------- #
# ML-G001 —— 请求语言提示被消费(G-L1):宿主默认答案语境生效
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_ml_g001_language_hint_consumed_as_default_answer_context():
    # 拉丁问题(检测只能给 en):hint=es 时按 es 生成 —— 基线做不到的能力
    llm, gen_messages = _gate_llm()
    rag = _make_rag(llm, [_sr("https://www.camthink.ai/p", source_type="website")])
    events = await _collect(rag, "¿Qué funciones tiene NE301?", language_hint="es-ES")
    complete = events[-1]
    assert complete["language"] == "es"
    assert "用 es 回答" in _full_text(gen_messages[-1])
    trace_lang = complete["trace_payload"]["stages"]["language"]
    assert trace_lang == {"hint": "es-ES", "detected": "en", "resolved": "es"}

    # 无提示 → 基线行为逐字保留(detect 原值)
    llm2, _ = _gate_llm()
    rag2 = _make_rag(llm2, [_sr("https://www.camthink.ai/p", source_type="website")])
    events2 = await _collect(rag2, "What is NE301?")
    assert events2[-1]["language"] == "en"
    assert (
        "language" not in events2[-1]["trace_payload"]["stages"]
        or events2[-1]["trace_payload"]["stages"].get("language", {}).get("hint") is None
    )


@pytest.mark.unit
async def test_ml_g001_answer_path_parity_with_hint():
    llm, gen_messages = _gate_llm()
    rag = _make_rag(llm, [_sr("https://www.camthink.ai/p", source_type="website")])
    ans = await rag.answer("NE301 specs", "widget", language_hint="fr")
    assert ans.language == "fr"
    assert "用 fr 回答" in _full_text(gen_messages[-1])


# --------------------------------------------------------------------------- #
# ML-G002 —— 显式用户语言覆盖宿主默认(文本 CJK 确定性检出)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_ml_g002_explicit_user_language_overrides_host_default():
    # en 页面上用户显式输入中文 → 中文回答
    assert resolve_answer_language("NE301 是什么产品?", "en") == "zh"
    # zh 页面上用户输入日语(假名确定性)→ 日语回答
    assert resolve_answer_language("NE301とは何ですか", "zh") == "ja"
    # 同族不折腾:zh 提示 + 中文提问 → zh(规范化,不回退 zh-cn)
    assert resolve_answer_language("NE301 是什么产品?", "zh-CN") == "zh"
    # 拉丁文本视为「未定」:host 默认赢(en 页面英文提问 → en)
    assert resolve_answer_language("What is NE301?", "en") == "en"
    # 无效提示 fail-open:交回文本检测,基线不变
    assert resolve_answer_language("hello", "!!!") == "en"


# --------------------------------------------------------------------------- #
# ML-G004 —— en/zh 归一化(后端面;widget 面在 vitest)
# --------------------------------------------------------------------------- #


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("zh-CN", "zh"),
        ("zh_TW", "zh"),
        ("zh-Hans", "zh"),
        ("zh", "zh"),
        ("en-US", "en"),
        ("en-GB", "en"),
        ("en", "en"),
        ("fr-FR", "fr"),
        ("pt", "pt"),
        ("", None),
        (None, None),
        ("   ", None),
        ("not-lang!", None),
    ],
)
def test_ml_g004_language_normalization(raw, expected):
    assert normalize_language(raw) == expected


# --------------------------------------------------------------------------- #
# ML-G006/007 —— 站点文案本地化在服务端承载(管线不感知;API 门见
# tests/api/test_multilingual_gate.py)。此处锁定:语言提示不改变检索/引用
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_ml_g008_hint_does_not_alter_retrieval_or_citation():
    """ML-G008(检索/引用不变式)+ ML-G014 之引用面:hint 只影响语言,不碰证据。"""
    results = [
        _sr(f"{WIKI_BLOB}/docs/5-neoeyes-ne301-series/0-overview.md"),
        _sr("https://www.camthink.ai/products/ne503", source_type="website"),
    ]
    llm, _ = _gate_llm(intent="product")
    rag = _make_rag(llm, results)
    events = await _collect(rag, "NE301 概述", language_hint="zh")

    sources_evt = next(e for e in events if e["type"] == "sources")
    by_type = {s["type"]: s for s in sources_evt["sources"]}
    # canonical + provenance 与无提示时完全一致
    assert by_type["github"]["url"] == WIKI_CANONICAL
    assert by_type["github"]["provenance_url"] == (
        f"{WIKI_BLOB}/docs/5-neoeyes-ne301-series/0-overview.md"
    )
    assert by_type["website"]["url"] == "https://www.camthink.ai/products/ne503"
    assert "provenance_url" not in by_type["website"]
    # 检索确实发生(语言提示不短路检索)
    rag._searcher.search.assert_called()


# --------------------------------------------------------------------------- #
# ML-G011 —— 会话连续性:第二轮 history 贯通 + 每轮独立解析
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_ml_g011_conversation_continuity_per_turn_resolution():
    llm, gen_messages = _gate_llm()
    rag = _make_rag(llm, [_sr("https://www.camthink.ai/p", source_type="website")])
    history = [
        {"role": "user", "content": "What is NE301?"},
        {"role": "assistant", "content": "NE301 is a camera."},
    ]
    events = await _collect(
        rag,
        "它支持哪些接口?",
        conversation_history=history,
        lead_ctx=LeadTurnContext(session_id="sess-ml"),
        language_hint="en",
    )
    assert events[-1]["is_answered"] is True
    msgs = gen_messages[-1]
    # history 贯通(system + 2 history + user)
    assert len(msgs) == 4
    assert msgs[1] == history[0]
    # 用户第二轮显式中文覆盖 en 页面默认 → zh 回答(每轮独立解析)
    assert events[-1]["language"] == "zh"


# --------------------------------------------------------------------------- #
# ML-G012 —— 本地化 smalltalk / off-topic
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_ml_g012_localized_smalltalk_and_off_topic():
    # 社交按文本命中语言回复(与提示无关):en 提示下「你好」仍中文回应
    llm, _ = _gate_llm()
    rag = _make_rag(llm, [])
    events = await _collect(rag, "你好", language_hint="en")
    assert events[-1]["intent"] == "smalltalk"
    assert match_social("你好") is not None and match_social("你好").language == "zh"
    llm2, _ = _gate_llm()
    rag2 = _make_rag(llm2, [])
    events2 = await _collect(rag2, "hello", language_hint="zh")
    assert events2[-1]["intent"] == "smalltalk"
    assert match_social("hello").language == "en"

    # off-topic 边界话术跟随答案语言语境:zh 提示 → 中文边界;en/es → 英文边界
    llm3, _ = _gate_llm(intent="off_topic")
    rag3 = _make_rag(llm3, [])
    events3 = await _collect(rag3, "写一首诗", language_hint="zh")
    assert events3[-1]["answer"] == OFF_TOPIC_REPLY_ZH
    llm4, _ = _gate_llm(intent="off_topic")
    rag4 = _make_rag(llm4, [])
    events4 = await _collect(rag4, "write a poem", language_hint="es")
    assert events4[-1]["answer"] != OFF_TOPIC_REPLY_ZH
    assert events4[-1]["answer"] != "我只能回答与 CamThink 产品相关的问题。"


# --------------------------------------------------------------------------- #
# ML-G013 —— 本地化 Sales Lead 用户可见行为
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_ml_g013_localized_lead_invite_and_ack():
    # qualified + zh 语境:邀请指令内嵌且答案语言指令为 zh(邀请跟随答案语言)
    llm, gen_messages = _gate_llm(intent="commercial")
    rag = _make_rag(llm, [_sr(f"{WIKI_BLOB}/docs/5-neoeyes-ne301-series/0-overview.md")])
    events = await _collect(
        rag,
        "我们要采购 500 台,请报价",
        lead_ctx=LeadTurnContext(session_id="s"),
        language_hint="zh",
    )
    complete = events[-1]
    assert complete["lead"]["invited"] is True
    system = _system_of(gen_messages[-1])
    assert LEAD_INVITE_INSTRUCTION in system
    assert "用 zh 回答" in _full_text(gen_messages[-1])

    # 捕获轮 + zh 语境:确认指令 + zh 答案指令;原文 PII 不入任何消息
    contact = detect_contact("我的邮箱是 john.acme@example-corp.com")
    from backend.utils.pii import mask_pii

    masked = mask_pii("我的邮箱是 john.acme@example-corp.com")
    llm2, gen_messages2 = _gate_llm(intent="off_topic")
    rag2 = _make_rag(llm2, [])
    events2 = await _collect(
        rag2,
        masked,
        lead_ctx=LeadTurnContext(session_id="s", has_lead=True, status="invited", contact=contact),
        language_hint="zh",
    )
    assert events2[-1]["lead"]["ack"] is True
    system2 = _system_of(gen_messages2[-1])
    assert LEAD_ACK_INSTRUCTION in system2
    assert "用 zh 回答" in _full_text(gen_messages2[-1])
    assert "john.acme@example-corp.com" not in json.dumps(gen_messages2, ensure_ascii=False)

    # 无提示基线:英文 qualified 邀请照旧(en 指令)
    llm3, gen_messages3 = _gate_llm(intent="commercial")
    rag3 = _make_rag(llm3, [_sr(f"{WIKI_BLOB}/docs/5-neoeyes-ne301-series/0-overview.md")])
    events3 = await _collect(
        rag3, "We need 500 units, please quote", lead_ctx=LeadTurnContext(session_id="s")
    )
    assert events3[-1]["lead"]["invited"] is True
    assert LEAD_INVITE_INSTRUCTION in _system_of(gen_messages3[-1])
    assert "用 en 回答" in _full_text(gen_messages3[-1])
