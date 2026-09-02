"""P1 生成可靠性 — RAGOrchestrator.stream_answer 零内容生成守护。

旧缺陷:llm.stream 正常结束但零内容 chunk 时,stream_answer 仍发
``complete(answer="", is_answered=True)``,上层把零内容当成功转发。
契约:零内容生成 = 异常完成,必须抛出 ``EmptyGenerationError`` 交给
SSE 层统一降级为用户可见失败。
"""

import json
from unittest.mock import MagicMock

import pytest

from backend.pipeline.rag import EmptyGenerationError
from tests.pipeline.test_rag import _build_orchestrator


@pytest.mark.unit
async def test_stream_answer_raises_on_zero_token_generation():
    """llm.stream 正常结束但零内容 → 抛 EmptyGenerationError,不发伪成功 complete。"""
    rag, _, _, llm = _build_orchestrator()

    async def _empty_stream(messages, task=None):
        return
        yield  # pragma: no cover — 使其为异步生成器

    llm.stream = MagicMock()
    llm.stream.return_value = _empty_stream([], task="generation")

    events = []
    with pytest.raises(EmptyGenerationError):
        async for evt in rag.stream_answer("query", "widget"):
            events.append(json.loads(evt))

    # sources 已发出(检索真实发生了),但绝不允许出现 is_answered=True 的伪成功 complete
    assert all(evt["type"] != "complete" for evt in events)


@pytest.mark.unit
async def test_stream_answer_raises_on_whitespace_only_generation():
    """llm.stream 仅产空白内容 → 同样视为零可用内容,抛 EmptyGenerationError。"""
    rag, _, _, llm = _build_orchestrator()

    async def _blank_stream(messages, task=None):
        yield "   "
        yield "\n"

    llm.stream = MagicMock()
    llm.stream.return_value = _blank_stream([], task="generation")

    with pytest.raises(EmptyGenerationError):
        async for _evt in rag.stream_answer("query", "widget"):
            pass


@pytest.mark.unit
async def test_stream_answer_normal_generation_still_emits_complete():
    """守护:正常生成仍发 complete(is_answered=True),守护逻辑不误伤。"""
    rag, _, _, llm = _build_orchestrator()

    async def _ok_stream(messages, task=None):
        yield "answer"

    llm.stream = MagicMock()
    llm.stream.return_value = _ok_stream([], task="generation")

    events = [json.loads(evt) async for evt in rag.stream_answer("query", "widget")]
    complete = [e for e in events if e["type"] == "complete"]
    assert len(complete) == 1
    assert complete[0]["is_answered"] is True
    assert complete[0]["answer"] == "answer"
