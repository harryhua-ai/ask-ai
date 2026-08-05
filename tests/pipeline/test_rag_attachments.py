"""附件上下文注入 + 有附件绕过拒答门(评审 C1)。"""
import json
from unittest.mock import MagicMock

import pytest

# _build_orchestrator 是 tests/pipeline/test_rag.py 的普通函数,import 复用
from tests.pipeline.test_rag import _build_orchestrator


@pytest.mark.unit
def test_build_messages_includes_log_text():
    """log_text 非空 → user_content 含 ## 用户上传的日志 段。"""
    rag, _, _, _ = _build_orchestrator(searcher_results=[], reranked_results=[])
    msgs = rag._build_messages(
        query="why crash",
        context="retrieved docs",
        language="en",
        history=[],
        channel="widget",
        intent="support",
        log_text="2026-08-05 ERROR segfault at 0x1234",
        image_context="",
    )
    user_content = msgs[-1]["content"]
    assert "## 用户上传的日志" in user_content
    assert "segfault" in user_content


@pytest.mark.unit
def test_build_messages_no_log_section_when_empty():
    """log_text 空 → 不出现 ## 用户上传的日志 段(保留原模板)。"""
    rag, _, _, _ = _build_orchestrator(searcher_results=[], reranked_results=[])
    msgs = rag._build_messages(
        query="q",
        context="ctx",
        language="en",
        history=[],
        channel="widget",
        intent="support",
        log_text="",
        image_context="",
    )
    assert "## 用户上传的日志" not in msgs[-1]["content"]


@pytest.mark.asyncio
@pytest.mark.unit
async def test_attachments_bypass_reject_when_search_empty():
    """有附件但检索为空 → 不拒答,走正常生成(附件作 fallback context)。评审 C1。"""
    rag, _, _, llm = _build_orchestrator(searcher_results=[], reranked_results=[])

    # mock llm.stream 产 token(classify_intent 走 generate fail-open → product)
    async def _fake_stream(messages, task=None):
        yield "based on your log: "

    llm.stream = MagicMock()
    llm.stream.return_value = _fake_stream([], task="generation")

    class FakeAtt:
        kind = "log"
        extracted_text = "ERROR segfault backtrace..."

    events = []
    async for ev in rag.stream_answer(query="analyze log", channel="widget",
                                       attachments=[FakeAtt()]):
        events.append(json.loads(ev))
    types = [e.get("type") for e in events]
    assert "token" in types  # 真生成,非直接 REJECT_ANSWER return
