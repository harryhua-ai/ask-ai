"""业务信号 LLM 提取 pipeline 测试。"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.llm.base import LLMResponse
from backend.pipeline.business_signals import extract_business_signals


def _build_mock_llm(*, scenes=None, requirements=None) -> MagicMock:
    """构造 mock LLM,根据 task 返回不同 payload。"""
    llm = MagicMock()

    def _side_effect(messages, **kwargs):
        task = kwargs.get("task", "generation")
        if task == "scene":
            payload = [
                {"type": "scene", "label": label, "count": count, "conv_ids": []}
                for label, count in (scenes or [])
            ]
        elif task == "requirement":
            payload = [
                {"type": "requirement", "label": label, "count": count, "conv_ids": []}
                for label, count in (requirements or [])
            ]
        else:
            payload = []
        return LLMResponse(
            content=json.dumps(payload, ensure_ascii=False),
            model="test",
            tokens_input=10,
            tokens_output=20,
            latency_ms=100,
        )

    llm.generate = AsyncMock(side_effect=_side_effect)
    return llm


@pytest.mark.asyncio
async def test_extract_scene_signals():
    """LLM 给 5 条 commercial/product 对话打场景标签,pipeline 聚合成 BusinessSignal。"""
    llm = _build_mock_llm(scenes=[("工业视觉", 3), ("安防", 2)])
    conversations = [
        MagicMock(
            id=f"conv-{i}",
            question=f"问题{i}",
            answer=f"答案{i}",
            intent_tag="product" if i < 3 else "commercial",
        )
        for i in range(5)
    ]
    signals = await extract_business_signals(llm, conversations, period_days=7)
    scenes = [s for s in signals if s["type"] == "scene"]
    assert any(s["label"] == "工业视觉" and s["count"] == 3 for s in scenes)
    assert any(s["label"] == "安防" and s["count"] == 2 for s in scenes)


@pytest.mark.asyncio
async def test_extract_product_requirements():
    """产品需求(4K录制/开放API/低功耗)提取并计数。"""
    llm = _build_mock_llm(requirements=[("4K 录制", 3), ("开放 API", 2)])
    conversations = [
        MagicMock(
            id=f"conv-{i}",
            question=f"问题{i}",
            answer=f"答案{i}",
            intent_tag="product",
        )
        for i in range(5)
    ]
    signals = await extract_business_signals(llm, conversations, period_days=7)
    reqs = [s for s in signals if s["type"] == "requirement"]
    assert len(reqs) == 2
    assert any(r["label"] == "4K 录制" and r["count"] == 3 for r in reqs)
    assert any(r["label"] == "开放 API" and r["count"] == 2 for r in reqs)


@pytest.mark.asyncio
async def test_extract_empty_conversations():
    """无对话时返回空列表。"""
    llm = _build_mock_llm()
    signals = await extract_business_signals(llm, [], period_days=7)
    assert signals == []
