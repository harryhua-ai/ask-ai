"""OverrideMatcher 单元测试。

覆盖:
- keyword 匹配(子串包含)
- regex 匹配
- semantic 匹配(余弦相似度 >= 阈值)
- semantic 匹配低于阈值返回 None
- 无活跃 override 时返回 None
- refresh 加载新 override
"""

from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest

from backend.db.models import AnswerOverride
from backend.services.override_matcher import OverrideMatcher


def _make_override(
    match_pattern: str = "NE503 功耗",
    match_type: str = "semantic",
    override_answer: str = "NE503 功耗为 2.5W",
    is_active: bool = True,
) -> AnswerOverride:
    return AnswerOverride(
        id=None,
        match_pattern=match_pattern,
        match_type=match_type,
        override_answer=override_answer,
        override_sources=[],
        created_by="admin",
        is_active=is_active,
    )


def _mock_embedder(embeddings: dict[str, np.ndarray]) -> MagicMock:
    """构造 mock embedder,按文本返回预设 embedding。"""
    embedder = MagicMock()
    embedder.embed = lambda texts: [embeddings.get(t, np.random.rand(1024)) for t in texts]
    return embedder


def _mock_session_factory(overrides: list[AnswerOverride]) -> AsyncMock:
    """构造 mock session_factory,返回指定 overrides。"""
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = overrides
    session.execute = AsyncMock(return_value=result)
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=None)
    factory = MagicMock()
    factory.return_value = ctx
    return factory


@pytest.mark.unit
async def test_keyword_match():
    """keyword 类型:query 包含 match_pattern 时命中。"""
    override = _make_override(match_pattern="保修", match_type="keyword")
    factory = _mock_session_factory([override])
    embedder = _mock_embedder({})

    matcher = OverrideMatcher(factory, embedder)
    await matcher.refresh()

    result = await matcher.match("产品保修期多久?")

    assert result is not None
    assert result.override_answer == "NE503 功耗为 2.5W"


@pytest.mark.unit
async def test_keyword_no_match():
    """keyword 类型:query 不包含 match_pattern 时不命中。"""
    override = _make_override(match_pattern="保修", match_type="keyword")
    factory = _mock_session_factory([override])
    embedder = _mock_embedder({})

    matcher = OverrideMatcher(factory, embedder)
    await matcher.refresh()

    result = await matcher.match("产品价格是多少?")

    assert result is None


@pytest.mark.unit
async def test_regex_match():
    """regex 类型:正则匹配命中。"""
    override = _make_override(
        match_pattern=r"NE\d{3}\s*固件",
        match_type="regex",
        override_answer="固件下载链接",
    )
    factory = _mock_session_factory([override])
    embedder = _mock_embedder({})

    matcher = OverrideMatcher(factory, embedder)
    await matcher.refresh()

    result = await matcher.match("NE503 固件在哪里下载?")

    assert result is not None
    assert result.override_answer == "固件下载链接"


@pytest.mark.unit
async def test_semantic_match_above_threshold():
    """semantic 类型:余弦相似度 >= 阈值时命中。"""
    pattern_vec = np.ones(1024)
    query_vec = np.ones(1024)
    override = _make_override(match_pattern="产品功耗", match_type="semantic")
    factory = _mock_session_factory([override])
    embedder = _mock_embedder({
        "产品功耗": pattern_vec,
        "产品功耗是多少": query_vec,
    })

    matcher = OverrideMatcher(factory, embedder, threshold=0.85)
    await matcher.refresh()

    result = await matcher.match("产品功耗是多少")

    assert result is not None


@pytest.mark.unit
async def test_semantic_match_below_threshold():
    """semantic 类型:余弦相似度 < 阈值时不命中。"""
    pattern_vec = np.ones(1024)
    query_vec = np.ones(1024)
    query_vec[:512] = -1.0  # 反转半数维度使余弦相似度趋近 0
    override = _make_override(match_pattern="产品功耗", match_type="semantic")
    factory = _mock_session_factory([override])
    embedder = _mock_embedder({
        "产品功耗": pattern_vec,
        "完全不同的问题": query_vec,
    })

    matcher = OverrideMatcher(factory, embedder, threshold=0.99)
    await matcher.refresh()

    result = await matcher.match("完全不同的问题")

    assert result is None


@pytest.mark.unit
async def test_no_active_overrides():
    """无活跃 override 时始终返回 None。"""
    factory = _mock_session_factory([])
    embedder = _mock_embedder({})

    matcher = OverrideMatcher(factory, embedder)
    await matcher.refresh()

    result = await matcher.match("anything")

    assert result is None


@pytest.mark.unit
async def test_refresh_loads_new_overrides():
    """refresh 后新创建的 override 可被匹配。"""
    factory = _mock_session_factory([])
    embedder = _mock_embedder({})

    matcher = OverrideMatcher(factory, embedder)
    await matcher.refresh()
    assert await matcher.match("保修") is None

    # 模拟新增 override
    override = _make_override(match_pattern="保修", match_type="keyword")
    factory2 = _mock_session_factory([override])
    matcher._factory = factory2
    await matcher.refresh()

    result = await matcher.match("保修期多久?")
    assert result is not None
