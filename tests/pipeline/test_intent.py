"""意图识别模块的单元测试。"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.pipeline.intent import IntentResult, classify_intent


def _make_llm(response_text: str) -> MagicMock:
    llm = MagicMock()
    llm.generate = AsyncMock(return_value=MagicMock(content=response_text))
    return llm


@pytest.mark.unit
@pytest.mark.asyncio
async def test_classify_product_question_short():
    """短产品查询识别为 product_question。"""
    llm = _make_llm(json.dumps({"category": "product_question", "reason": "NE301 产品问题"}))
    result = await classify_intent("NE301怎么配置WiFi", llm)
    assert result.category == "product_question"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_classify_product_question_long_email():
    """长邮件(电池监控案例)识别为 product_question。"""
    email = (
        "Dear Dave, Thank you for your message. "
        "We have validated the NE301 as the core platform. "
        "The main remaining technical point is battery monitoring. "
        "Is the battery voltage available through the NE301 firmware? "
        "Does the Solar SKU include a fuel-gauge IC?"
    )
    llm = _make_llm(json.dumps({"category": "product_question", "reason": "NE301 电池监控技术问题"}))
    result = await classify_intent(email, llm)
    assert result.category == "product_question"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_classify_business_inquiry():
    """价格咨询识别为 business_inquiry。"""
    llm = _make_llm(json.dumps({"category": "business_inquiry", "reason": "价格咨询"}))
    result = await classify_intent("NE301的价格是多少?批量采购有折扣吗?", llm)
    assert result.category == "business_inquiry"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_classify_off_topic():
    """闲聊识别为 off_topic。"""
    llm = _make_llm(json.dumps({"category": "off_topic", "reason": "天气闲聊"}))
    result = await classify_intent("今天天气怎么样?", llm)
    assert result.category == "off_topic"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_classify_fail_open_on_exception():
    """LLM 异常时 fail-open 为 product_question。"""
    llm = MagicMock()
    llm.generate = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
    result = await classify_intent("NE301 配置", llm)
    assert result.category == "product_question"
    assert "failed" in result.reason


@pytest.mark.unit
@pytest.mark.asyncio
async def test_classify_fail_open_on_malformed_json():
    """LLM 返回畸形 JSON 时 fail-open。"""
    llm = _make_llm("这不是 JSON")
    result = await classify_intent("NE301 配置", llm)
    assert result.category == "product_question"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_classify_unknown_category_falls_back():
    """LLM 返回未知类别时回退为 product_question。"""
    llm = _make_llm(json.dumps({"category": "unknown_type", "reason": "test"}))
    result = await classify_intent("test", llm)
    assert result.category == "product_question"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_classify_handles_code_fenced_json():
    """LLM 返回 markdown code fence 包裹的 JSON 时正确解析。"""
    llm = _make_llm('```json\n{"category": "off_topic", "reason": "闲聊"}\n```')
    result = await classify_intent("讲个笑话", llm)
    assert result.category == "off_topic"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_classify_uses_intent_task():
    """LLM 调用使用 task='intent' 路由。"""
    llm = _make_llm(json.dumps({"category": "product_question", "reason": ""}))
    await classify_intent("NE301", llm)
    llm.generate.assert_awaited_once()
    _, kwargs = llm.generate.call_args
    assert kwargs.get("task") == "intent"
