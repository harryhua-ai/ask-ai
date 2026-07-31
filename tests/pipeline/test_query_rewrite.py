"""extract_query 和 rewrite_query 的单元测试。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.pipeline.query_rewrite import extract_query, rewrite_query


def _make_llm(response_text: str) -> MagicMock:
    llm = MagicMock()
    llm.generate = AsyncMock(return_value=MagicMock(content=response_text))
    return llm


@pytest.mark.unit
@pytest.mark.asyncio
async def test_extract_query_short_query_calls_llm():
    """短查询也会经过 LLM 提取。"""
    llm = _make_llm("NE301 配置")
    result = await extract_query("NE301怎么配置", llm)
    assert result == "NE301 配置"
    llm.generate.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_extract_query_long_query_calls_llm():
    """长查询经过 LLM 提取。"""
    long_text = "你好，我想问一下关于NE301这款产品的配置方法。" * 20
    llm = _make_llm("NE301 配置方法")
    result = await extract_query(long_text, llm)
    assert result == "NE301 配置方法"
    llm.generate.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_extract_query_fallback_on_error():
    """LLM 调用失败时回退到原始查询。"""
    llm = MagicMock()
    llm.generate = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
    result = await extract_query("NE301 配置", llm)
    assert result == "NE301 配置"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_extract_query_empty_llm_response_fallback():
    """LLM 返回空字符串时回退到原始查询。"""
    llm = _make_llm("  ")
    result = await extract_query("NE301 配置", llm)
    assert result == "NE301 配置"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rewrite_query_no_history():
    """无对话历史时直接返回原始查询。"""
    llm = _make_llm("改写结果")
    result = await rewrite_query("NE301 配置", None, llm)
    assert result == "NE301 配置"
    llm.generate.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rewrite_query_short_history():
    """对话历史不足时直接返回原始查询。"""
    llm = _make_llm("改写结果")
    history = [{"role": "user", "content": "你好"}]
    result = await rewrite_query("NE301 配置", history, llm)
    assert result == "NE301 配置"
    llm.generate.assert_not_awaited()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rewrite_query_with_history():
    """有足够对话历史时用 LLM 改写查询。"""
    llm = _make_llm("NE301 的 WiFi 配置方法")
    history = [
        {"role": "user", "content": "我在配置 NE301"},
        {"role": "assistant", "content": "好的,请问有什么问题?"},
        {"role": "user", "content": "WiFi 怎么设置"},
    ]
    result = await rewrite_query("WiFi 怎么设置", history, llm)
    assert result == "NE301 的 WiFi 配置方法"
    llm.generate.assert_awaited_once()
