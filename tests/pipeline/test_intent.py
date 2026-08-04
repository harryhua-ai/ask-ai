"""意图识别模块的单元测试(4 分类:commercial/product/support/off_topic)。"""

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
    """短产品查询识别为 product。"""
    llm = _make_llm(json.dumps({"category": "product", "reason": "产品咨询"}))
    result = await classify_intent("NE301怎么配置WiFi", llm)
    assert result.category == "product"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_classify_product_question_long_email():
    """长邮件(电池监控案例)识别为 product。"""
    email = (
        "Dear Dave, Thank you for your message. "
        "We have validated the NE301 as the core platform. "
        "The main remaining technical point is battery monitoring. "
        "Is the battery voltage available through the NE301 firmware? "
        "Does the Solar SKU include a fuel-gauge IC?"
    )
    llm = _make_llm(json.dumps({"category": "product", "reason": "NE301 电池监控技术问题"}))
    result = await classify_intent(email, llm)
    assert result.category == "product"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_classify_support():
    """故障排查/报错 → support。"""
    llm = _make_llm(json.dumps({"category": "support", "reason": "故障排查"}))
    result = await classify_intent("NE101 蜂窝网络注册失败 CEREG 报错", llm)
    assert result.category == "support"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_classify_commercial():
    """纯价格/采购 → commercial。"""
    llm = _make_llm(json.dumps({"category": "commercial", "reason": "价格咨询"}))
    result = await classify_intent("NE301的价格是多少?批量采购有折扣吗?", llm)
    assert result.category == "commercial"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_classify_product_capability_not_commercial():
    """能力/方案/选型 → product(非 commercial)。#15/#20 关键边界。"""
    llm = _make_llm(json.dumps({"category": "product", "reason": "方案咨询"}))
    result = await classify_intent("NE301 支持热成像入侵检测吗?有演示视频吗?", llm)
    assert result.category == "product"


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
    """LLM 异常时 fail-open 为 product。"""
    llm = MagicMock()
    llm.generate = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
    result = await classify_intent("NE301 配置", llm)
    assert result.category == "product"
    assert "failed" in result.reason


@pytest.mark.unit
@pytest.mark.asyncio
async def test_classify_fail_open_on_malformed_json():
    """LLM 返回畸形 JSON 时 fail-open 为 product。"""
    llm = _make_llm("这不是 JSON")
    result = await classify_intent("NE301 配置", llm)
    assert result.category == "product"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_classify_unknown_category_falls_back():
    """LLM 返回未知类别时回退为 product。"""
    llm = _make_llm(json.dumps({"category": "unknown_type", "reason": "test"}))
    result = await classify_intent("test", llm)
    assert result.category == "product"


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
    llm = _make_llm(json.dumps({"category": "product", "reason": ""}))
    await classify_intent("NE301", llm)
    llm.generate.assert_awaited_once()
    _, kwargs = llm.generate.call_args
    assert kwargs.get("task") == "intent"
