"""Intent 标注服务测试。"""

from unittest.mock import AsyncMock

import pytest

from backend.services.intent_tagger import INTENT_CATEGORIES, tag_single


@pytest.mark.asyncio
async def test_tag_single_returns_valid_category():
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value=type("R", (), {"content": "support"})())
    tag = await tag_single("conv-1", "如何配置 NE503 的网络？", llm)
    assert tag in INTENT_CATEGORIES
    assert tag == "support"


@pytest.mark.asyncio
async def test_tag_single_fallback_on_error():
    llm = AsyncMock()
    llm.generate = AsyncMock(side_effect=Exception("LLM 不可用"))
    tag = await tag_single("conv-2", "test question", llm)
    assert tag == "off_topic"
