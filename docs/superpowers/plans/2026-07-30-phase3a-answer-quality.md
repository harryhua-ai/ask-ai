# Phase 3A: 答案质量优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 通过 LLM 剪枝(Pruner)和人工答案覆盖(Improve This Answer)两个模块提升 RAG 系统的答案质量。

**Architecture:** Pruner 插入现有 RAG 管线的 rerank→generate 之间,用 deepseek-v4-flash 批量评估 chunk 相关性并过滤低相关结果。Improve This Answer 在管线最前端检查人工覆盖规则(keyword/regex/semantic 三种匹配),命中则跳过整个 RAG 管线直接返回覆盖答案。

**Tech Stack:** Python 3.14 / FastAPI / SQLAlchemy / BGE-m3 embedder / deepseek-v4-flash / React 19 + Vite 6 + shadcn/ui

## Global Constraints

- Python 3.14,PEP 8,所有函数签名使用 type annotations
- black + isort + ruff 格式化
- pytest 测试框架,`@pytest.mark.unit` / `@pytest.mark.integration` 分类
- 不可变数据模式(dataclass frozen / spread operator)
- 函数 <50 行,文件 <800 行
- 所有代码注释和文档使用中文(简体)
- secret 全走 env,不硬编码
- LLM 输出不视为可信内容,渲染前必须清洗
- Pruner 调用 LLM 使用 `task="pruning"` 路由,模型为 `deepseek-v4-flash`
- OverrideMatcher 语义匹配使用内存余弦比对(BGE-m3 已加载),不引入 pgvector
- 现有 pipeline 插入点已预留:`rag.py:113` (`pruner=None`)、`rag.py:280` / `rag.py:360` (pruner hooks)

---

## File Structure

| 文件 | 职责 | 动作 |
|------|------|------|
| `backend/pipeline/pruner.py` | Pruner Protocol + LLMPruner 实现 | 创建 |
| `backend/services/override_matcher.py` | 人工覆盖匹配服务(keyword/regex/semantic) | 创建 |
| `backend/api/admin/answer_overrides.py` | 答案覆盖 CRUD 端点 | 创建 |
| `backend/pipeline/rag.py` | RAG 编排器:接入 pruner async + override 前置检查 | 修改 |
| `backend/api/admin/schemas.py` | 新增 AnswerOverride Pydantic 模型 | 修改 |
| `backend/api/admin/router.py` | 注册 answer_overrides 子路由 | 修改 |
| `backend/main.py` | lifespan 中初始化 Pruner + OverrideMatcher | 修改 |
| `admin/src/pages/AnswerOverrides.tsx` | 答案覆盖管理页面 | 创建 |
| `admin/src/hooks/useAnswerOverrides.ts` | 答案覆盖 React Query hooks | 创建 |
| `admin/src/types/api.ts` | 新增 AnswerOverride 类型 | 修改 |
| `admin/src/App.tsx` | 新增路由 | 修改 |
| `admin/src/components/Sidebar.tsx` | 新增导航项 | 修改 |
| `admin/src/pages/Conversations.tsx` | 对话详情加"改进此答案"按钮 | 修改 |
| `tests/pipeline/test_pruner.py` | Pruner 单元测试 | 创建 |
| `tests/services/test_override_matcher.py` | OverrideMatcher 单元测试 | 创建 |
| `tests/api/admin/test_answer_overrides.py` | 答案覆盖 API 测试 | 创建 |
| `tests/pipeline/test_rag.py` | RAGOrchestrator pruner/override 集成测试 | 修改 |

---

## Task 1: Pruner Protocol + LLMPruner 实现

**Files:**
- Create: `backend/pipeline/pruner.py`
- Test: `tests/pipeline/test_pruner.py`

**Interfaces:**
- Consumes: `backend.llm.base.LLMProvider`(通过 `LLMRouter.generate(messages, task="pruning")` 调用)
- Consumes: `backend.retrieval.search.SearchResult`
- Produces: `Pruner` Protocol(`async def prune(query, chunks) -> list[SearchResult]`)、`LLMPruner` 类

- [ ] **Step 1: 写 Pruner Protocol + LLMPruner 的失败测试**

```python
# tests/pipeline/test_pruner.py
"""LLMPruner 单元测试。

覆盖:
- 空输入返回空列表
- LLM 返回相关性评分后正确过滤
- min_keep 保底:即使全部低分也保留指定数量
- LLM 返回格式异常时 fail-open(保留全部)
- chunk 数量与评分数量不匹配时 fail-open
"""

import json
from unittest.mock import AsyncMock

import pytest

from backend.llm.base import LLMResponse
from backend.pipeline.pruner import LLMPruner
from backend.retrieval.search import SearchResult


def _make_sr(text: str, idx: int = 0) -> SearchResult:
    return SearchResult(
        text=text,
        source_id=f"s{idx}",
        source_type="github",
        product="ne503",
        title=f"Doc {idx}",
        url=f"https://example.com/{idx}",
        score=0.5,
        chunk_index=idx,
    )


def _make_llm_response(content: str) -> LLMResponse:
    return LLMResponse(content=content, model="deepseek-v4-flash", tokens_input=100, tokens_output=20, latency_ms=50)


@pytest.mark.unit
async def test_pruner_empty_input():
    """空列表传入时直接返回空列表,不调用 LLM。"""
    llm = AsyncMock()
    pruner = LLMPruner(llm)
    result = await pruner.prune("query", [])
    assert result == []
    llm.generate.assert_not_called()


@pytest.mark.unit
async def test_pruner_filters_low_relevance():
    """LLM 返回 [1, 0, 1] 时,过滤掉第二个 chunk。"""
    chunks = [_make_sr("relevant A", 0), _make_sr("irrelevant", 1), _make_sr("relevant B", 2)]
    llm = AsyncMock()
    llm.generate.return_value = _make_llm_response("[1, 0, 1]")
    pruner = LLMPruner(llm, relevance_threshold=0.5, min_keep=1)

    result = await pruner.prune("NE503 功耗", chunks)

    assert len(result) == 2
    assert result[0].text == "relevant A"
    assert result[1].text == "relevant B"


@pytest.mark.unit
async def test_pruner_min_keep_preserves_top_chunks():
    """全部低分时,按 score 降序保留 min_keep 条(fail-open 防止过度剪枝)。"""
    chunks = [
        _make_sr("low1", 0),
        _make_sr("low2", 1),
        _make_sr("low3", 2),
    ]
    llm = AsyncMock()
    llm.generate.return_value = _make_llm_response("[0, 0, 0]")
    pruner = LLMPruner(llm, relevance_threshold=0.5, min_keep=2)

    result = await pruner.prune("query", chunks)

    assert len(result) == 2


@pytest.mark.unit
async def test_pruner_malformed_response_keeps_all():
    """LLM 返回非 JSON 时 fail-open,保留全部 chunk。"""
    chunks = [_make_sr("a", 0), _make_sr("b", 1)]
    llm = AsyncMock()
    llm.generate.return_value = _make_llm_response("抱歉,我无法理解。")
    pruner = LLMPruner(llm)

    result = await pruner.prune("query", chunks)

    assert len(result) == 2


@pytest.mark.unit
async def test_pruner_score_count_mismatch_keeps_all():
    """LLM 返回的评分数组长度与 chunk 数不匹配时 fail-open。"""
    chunks = [_make_sr("a", 0), _make_sr("b", 1), _make_sr("c", 2)]
    llm = AsyncMock()
    llm.generate.return_value = _make_llm_response("[1, 0]")
    pruner = LLMPruner(llm)

    result = await pruner.prune("query", chunks)

    assert len(result) == 3


@pytest.mark.unit
async def test_pruner_calls_llm_with_pruning_task():
    """LLM 调用时 task 参数应为 'pruning'。"""
    chunks = [_make_sr("a", 0)]
    llm = AsyncMock()
    llm.generate.return_value = _make_llm_response("[1]")
    pruner = LLMPruner(llm)

    await pruner.prune("query", chunks)

    _, kwargs = llm.generate.call_args
    assert kwargs.get("task") == "pruning"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/pipeline/test_pruner.py -v`
Expected: FAIL — `ImportError: No module named 'backend.pipeline.pruner'`

- [ ] **Step 3: 实现 Pruner Protocol + LLMPruner**

```python
# backend/pipeline/pruner.py
"""LLM 剪枝器 — 在 rerank 之后、生成之前过滤低相关 chunk。

使用小 LLM(deepseek-v4-flash)批量评估 chunk 与 query 的相关性,
过滤低相关结果以减少噪声、提升答案质量并降低生成 token 成本。
"""

import json
import logging
from typing import Protocol

from backend.llm.base import LLMProvider
from backend.retrieval.search import SearchResult

logger = logging.getLogger(__name__)


class Pruner(Protocol):
    """剪枝器协议 — Phase 3 插入重排与生成之间。"""

    async def prune(self, query: str, chunks: list[SearchResult]) -> list[SearchResult]:
        """过滤低相关 chunk,保留高相关 chunk。

        Args:
            query: 用户查询文本(经 query rewrite 后)。
            chunks: 重排后的 SearchResult 列表。

        Returns:
            过滤后的 SearchResult 列表,长度 <= chunks。
        """
        ...


class LLMPruner:
    """基于 LLM 的批量剪枝器。

    单次 LLM 调用评估所有 chunk 的相关性,按阈值过滤。
    失败时 fail-open(保留全部 chunk),避免过度剪枝导致拒答。
    """

    def __init__(
        self,
        llm: LLMProvider,
        relevance_threshold: float = 0.5,
        min_keep: int = 3,
    ) -> None:
        """初始化剪枝器。

        Args:
            llm: LLM 供应商(通过 task="pruning" 路由到 deepseek-v4-flash)。
            relevance_threshold: 相关性阈值,LLM 返回 1 视为相关,0 视为不相关。
            min_keep: 最少保留的 chunk 数量,防止过度剪枝。
        """
        self._llm = llm
        self._threshold = relevance_threshold
        self._min_keep = min_keep

    async def prune(self, query: str, chunks: list[SearchResult]) -> list[SearchResult]:
        """批量评估 chunk 相关性并过滤。

        Args:
            query: 用户查询文本。
            chunks: 重排后的 SearchResult 列表。

        Returns:
            过滤后的 SearchResult 列表。
        """
        if not chunks:
            return []

        prompt = self._build_prompt(query, chunks)
        messages = [{"role": "user", "content": prompt}]

        try:
            response = await self._llm.generate(
                messages, task="pruning", max_tokens=512, temperature=0.0
            )
        except Exception:
            logger.exception("Pruner LLM 调用失败,fail-open 保留全部 chunk")
            return chunks

        scores = self._parse_scores(response.content, len(chunks))
        if scores is None:
            logger.warning("Pruner LLM 返回格式异常,fail-open 保留全部 chunk")
            return chunks

        relevant = [
            (chunk, score)
            for chunk, score in zip(chunks, scores)
            if score >= self._threshold
        ]

        if len(relevant) < self._min_keep:
            ranked = sorted(zip(chunks, scores), key=lambda x: x[1], reverse=True)
            relevant = ranked[: self._min_keep]

        return [chunk for chunk, _ in relevant]

    def _build_prompt(self, query: str, chunks: list[SearchResult]) -> str:
        """构建批量相关性评估 prompt。"""
        passages = "\n".join(
            f"[{i}] {chunk.text[:500]}" for i, chunk in enumerate(chunks)
        )
        return (
            f"你是一个相关性判断器。给定用户问题和一组文本片段,"
            f"判断每个片段是否与回答该问题相关。\n\n"
            f"用户问题: {query}\n\n"
            f"文本片段:\n{passages}\n\n"
            f"请返回一个 JSON 数组,包含 {len(chunks)} 个元素,"
            f"每个元素为 0(不相关)或 1(相关)。\n"
            f"例如: [1, 0, 1, 1, 0]\n\n"
            f"只返回 JSON 数组,不要返回其他内容。"
        )

    def _parse_scores(self, content: str, expected_count: int) -> list[float] | None:
        """解析 LLM 返回的 JSON 评分数组。

        Args:
            content: LLM 返回的原始文本。
            expected_count: 期望的评分数量(等于 chunk 数)。

        Returns:
            评分数组,解析失败时返回 None。
        """
        try:
            stripped = content.strip()
            start = stripped.find("[")
            end = stripped.rfind("]")
            if start == -1 or end == -1:
                return None
            scores = json.loads(stripped[start : end + 1])
            if len(scores) != expected_count:
                return None
            return [float(s) for s in scores]
        except (json.JSONDecodeError, ValueError, TypeError):
            return None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/pipeline/test_pruner.py -v`
Expected: 6 PASSED

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/pruner.py tests/pipeline/test_pruner.py
git commit -m "feat: 添加 LLMPruner 剪枝器(deepseek-v4-flash 批量评估 chunk 相关性)"
```

---

## Task 2: RAGOrchestrator 接入 async Pruner

**Files:**
- Modify: `backend/pipeline/rag.py` (pruner hook 改为 async)
- Modify: `tests/pipeline/test_rag.py` (新增 pruner 集成测试)
- Modify: `backend/main.py` (lifespan 中创建 LLMPruner)

**Interfaces:**
- Consumes: `backend.pipeline.pruner.LLMPruner`、`backend.pipeline.pruner.Pruner`
- Produces: `RAGOrchestrator.__init__` 新增 `pruner` 参数已存在(改为 async 调用)

- [ ] **Step 1: 写 Pruner 集成的失败测试**

在 `tests/pipeline/test_rag.py` 末尾追加:

```python
@pytest.mark.unit
async def test_rag_calls_async_pruner():
    """RAGOrchestrator 应以 await 方式调用 pruner.prune()。"""
    from backend.pipeline.pruner import LLMPruner

    sr = _make_sr(text="relevant", url="https://example.com/a")
    rag, searcher, reranker, llm = _build_orchestrator(
        searcher_results=[sr], reranked_results=[sr]
    )

    pruner = AsyncMock()
    pruner.prune.return_value = [sr]
    rag._pruner = pruner

    await rag.answer("query", "widget")

    pruner.prune.assert_awaited_once()


@pytest.mark.unit
async def test_rag_pruner_filters_reflected_in_answer():
    """Pruner 过滤掉的 chunk 不应出现在最终 sources 中。"""
    sr1 = _make_sr(text="keep", source_id="s1", url="https://example.com/keep")
    sr2 = _make_sr(text="drop", source_id="s2", url="https://example.com/drop")

    rag, searcher, reranker, llm = _build_orchestrator(
        searcher_results=[sr1, sr2], reranked_results=[sr1, sr2]
    )

    pruner = AsyncMock()
    pruner.prune.return_value = [sr1]  # 只保留 sr1
    rag._pruner = pruner

    result = await rag.answer("query", "widget")

    assert result.is_answered is True
    urls = [s["url"] for s in result.sources]
    assert "https://example.com/keep" in urls
    assert "https://example.com/drop" not in urls
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/pipeline/test_rag.py::test_rag_calls_async_pruner tests/pipeline/test_rag.py::test_rag_pruner_filters_reflected_in_answer -v`
Expected: FAIL — `pruner.prune` 未被 await(sync 调用不会触发 `assert_awaited_once`)

- [ ] **Step 3: 修改 rag.py — pruner hook 改为 async**

在 `backend/pipeline/rag.py` 的 `answer()` 方法中(line 280):

```python
# 修改前:
if self._pruner:
    reranked = self._pruner.prune(search_query, reranked)

# 修改后:
if self._pruner:
    reranked = await self._pruner.prune(search_query, reranked)
```

在 `stream_answer()` 方法中(line 360-361):

```python
# 修改前:
if self._pruner:
    reranked = self._pruner.prune(query, reranked)

# 修改后:
if self._pruner:
    reranked = await self._pruner.prune(query, reranked)
```

- [ ] **Step 4: 修改 main.py — 创建 LLMPruner 并传入 RAGOrchestrator**

在 `backend/main.py` 的 lifespan 中,在创建 `RAGOrchestrator` 之前(line ~201):

```python
# Pruner(Phase 3A):检查 routing 中是否有 "pruning" task
pruner = None
routing_for_pruning = routing_dict.get("pruning", [])
if routing_for_pruning and any(pid in providers for pid in routing_for_pruning):
    from backend.pipeline.pruner import LLMPruner

    pruner = LLMPruner(router_llm)
    logger.info("Pruner 已启用(task=pruning)")
```

然后在 `RAGOrchestrator` 构造时传入:

```python
app.state.rag = RAGOrchestrator(
    searcher=searcher,
    reranker=rerank_pipeline,
    llm=router_llm,
    system_prompt=system_prompt,
    channel_customizations=channel_customizations,
    pruner=pruner,
)
```

- [ ] **Step 5: 运行全部 rag 测试确认通过**

Run: `pytest tests/pipeline/test_rag.py -v`
Expected: ALL PASSED (原有测试 + 2 新测试)

- [ ] **Step 6: Commit**

```bash
git add backend/pipeline/rag.py backend/main.py tests/pipeline/test_rag.py
git commit -m "feat: RAGOrchestrator 接入 async Pruner(task=pruning 路由)"
```

---

## Task 3: OverrideMatcher 服务实现

**Files:**
- Create: `backend/services/override_matcher.py`
- Test: `tests/services/test_override_matcher.py`

**Interfaces:**
- Consumes: `backend.embedder.base.Embedder`(`embed(texts) -> list[np.ndarray]`)、`backend.db.models.AnswerOverride`、`async_sessionmaker`
- Produces: `OverrideMatcher` 类(`async def refresh()` + `async def match(query) -> AnswerOverride | None`)

- [ ] **Step 1: 写 OverrideMatcher 的失败测试**

```python
# tests/services/test_override_matcher.py
"""OverrideMatcher 单元测试。

覆盖:
- keyword 匹配(子串包含)
- regex 匹配
- semantic 匹配(余弦相似度 >= 阈值)
- semantic 匹配低于阈值返回 None
- 无活跃 override 时返回 None
- refresh 加载新 override
"""

import re
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
    query_vec[0] = -1.0  # 反转一个维度降低相似度
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/services/test_override_matcher.py -v`
Expected: FAIL — `ImportError: No module named 'backend.services.override_matcher'`

- [ ] **Step 3: 实现 OverrideMatcher**

```python
# backend/services/override_matcher.py
"""人工答案覆盖匹配服务。

支持三种匹配策略:
- keyword: 简单子串包含(大小写不敏感)
- regex: 正则表达式匹配
- semantic: BGE-m3 embedding 余弦相似度

语义匹配的 embedding 在 refresh() 时预计算并缓存,
运行时只需 embed query 一次,与缓存的 override embedding 比对。
"""

import asyncio
import logging
import re
from uuid import UUID

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db.models import AnswerOverride
from backend.embedder.base import Embedder

logger = logging.getLogger(__name__)


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """计算两个向量的余弦相似度。"""
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a, b) / (norm_a * norm_b))


class OverrideMatcher:
    """人工答案覆盖匹配器。

    缓存活跃 override 列表及其 semantic embedding,
    提供 match(query) 方法检查是否命中任意覆盖规则。
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        embedder: Embedder,
        threshold: float = 0.85,
    ) -> None:
        """初始化匹配器。

        Args:
            session_factory: Postgres 异步会话工厂。
            embedder: BGE-m3 嵌入模型(用于 semantic 匹配)。
            threshold: semantic 匹配的余弦相似度阈值。
        """
        self._factory = session_factory
        self._embedder = embedder
        self._threshold = threshold
        self._overrides: list[AnswerOverride] = []
        self._embeddings: dict[UUID, np.ndarray] = {}
        self._lock = asyncio.Lock()

    async def refresh(self) -> None:
        """从 DB 重新加载活跃 override,并为新增项计算 semantic embedding。"""
        async with self._lock:
            async with self._factory() as session:
                result = await session.execute(
                    select(AnswerOverride).where(AnswerOverride.is_active.is_(True))
                )
                overrides = result.scalars().all()

            for ov in overrides:
                if ov.match_type == "semantic" and ov.id not in self._embeddings:
                    try:
                        emb = self._embedder.embed([ov.match_pattern])
                        self._embeddings[ov.id] = emb[0]
                    except Exception:
                        logger.exception("Override embedding 计算失败,跳过: %s", ov.id)

            active_ids = {ov.id for ov in overrides}
            stale_ids = set(self._embeddings.keys()) - active_ids
            for sid in stale_ids:
                del self._embeddings[sid]

            self._overrides = overrides
            logger.info("OverrideMatcher 已加载 %d 条活跃覆盖", len(overrides))

    async def match(self, query: str) -> AnswerOverride | None:
        """检查 query 是否命中任意活跃覆盖规则。

        匹配优先级:keyword → regex → semantic。

        Args:
            query: 用户查询文本。

        Returns:
            命中的 AnswerOverride,未命中返回 None。
        """
        overrides = self._overrides
        if not overrides:
            return None

        for ov in overrides:
            if ov.match_type == "keyword":
                if ov.match_pattern.lower() in query.lower():
                    return ov

        for ov in overrides:
            if ov.match_type == "regex":
                if re.search(ov.match_pattern, query):
                    return ov

        semantic_overrides = [ov for ov in overrides if ov.match_type == "semantic"]
        if not semantic_overrides:
            return None

        try:
            query_emb = self._embedder.embed([query])[0]
        except Exception:
            logger.exception("Query embedding 计算失败,跳过 semantic 匹配")
            return None

        best_score = 0.0
        best_match: AnswerOverride | None = None
        for ov in semantic_overrides:
            emb = self._embeddings.get(ov.id)
            if emb is None:
                continue
            score = _cosine_similarity(query_emb, emb)
            if score > best_score:
                best_score = score
                best_match = ov

        if best_match is not None and best_score >= self._threshold:
            return best_match

        return None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/services/test_override_matcher.py -v`
Expected: 7 PASSED

- [ ] **Step 5: Commit**

```bash
git add backend/services/override_matcher.py tests/services/test_override_matcher.py
git commit -m "feat: 添加 OverrideMatcher 人工答案覆盖匹配服务(keyword/regex/semantic)"
```

---

## Task 4: RAGOrchestrator 接入 Override 前置检查

**Files:**
- Modify: `backend/pipeline/rag.py` (新增 override_matcher 参数 + 前置检查)
- Modify: `tests/pipeline/test_rag.py` (新增 override 集成测试)

**Interfaces:**
- Consumes: `backend.services.override_matcher.OverrideMatcher`
- Produces: `RAGOrchestrator.__init__` 新增 `override_matcher` 参数

- [ ] **Step 1: 写 Override 前置检查的失败测试**

在 `tests/pipeline/test_rag.py` 末尾追加:

```python
@pytest.mark.unit
async def test_rag_returns_override_when_matched():
    """OverrideMatcher 命中时,直接返回覆盖答案,跳过 search/rerank/generate。"""
    from backend.db.models import AnswerOverride

    override = AnswerOverride(
        id=None,
        match_pattern="保修",
        match_type="keyword",
        override_answer="保修期为 2 年",
        override_sources=[{"url": "https://example.com/warranty", "title": "Warranty"}],
        created_by="admin",
        is_active=True,
    )

    matcher = AsyncMock()
    matcher.match.return_value = override

    rag, searcher, reranker, llm = _build_orchestrator()
    rag._override_matcher = matcher

    result = await rag.answer("保修期多久?", "widget")

    assert result.is_answered is True
    assert result.answer == "保修期为 2 年"
    assert len(result.sources) == 1
    assert result.sources[0]["url"] == "https://example.com/warranty"
    searcher.search.assert_not_called()
    llm.generate.assert_not_called()


@pytest.mark.unit
async def test_rag_skips_override_when_no_match():
    """OverrideMatcher 未命中时,正常执行 RAG 管线。"""
    matcher = AsyncMock()
    matcher.match.return_value = None

    rag, searcher, reranker, llm = _build_orchestrator()
    rag._override_matcher = matcher

    await rag.answer("query", "widget")

    searcher.search.assert_called_once()


@pytest.mark.unit
async def test_rag_stream_answer_emits_override():
    """流式模式下 override 命中时,发出 sources → token → complete 事件。"""
    from backend.db.models import AnswerOverride

    override = AnswerOverride(
        id=None,
        match_pattern="保修",
        match_type="keyword",
        override_answer="保修期为 2 年",
        override_sources=[{"url": "https://example.com/warranty", "title": "Warranty"}],
        created_by="admin",
        is_active=True,
    )

    matcher = AsyncMock()
    matcher.match.return_value = override

    rag, _, _, llm = _build_orchestrator()
    rag._override_matcher = matcher

    events = []
    async for evt in rag.stream_answer("保修期?", "widget"):
        events.append(json.loads(evt))

    assert len(events) == 3
    assert events[0]["type"] == "sources"
    assert events[1]["type"] == "token"
    assert events[1]["content"] == "保修期为 2 年"
    assert events[2]["type"] == "complete"
    assert events[2]["is_answered"] is True
    assert events[2]["answer"] == "保修期为 2 年"
    llm.stream.assert_not_called()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/pipeline/test_rag.py::test_rag_returns_override_when_matched -v`
Expected: FAIL — `RAGOrchestrator` 没有 `_override_matcher` 属性

- [ ] **Step 3: 修改 rag.py — 新增 override_matcher 参数 + 前置检查**

在 `RAGOrchestrator.__init__` 中新增参数(line ~113 之后):

```python
override_matcher: Any = None,  # Phase 3A: OverrideMatcher
```

在 `__init__` body 中保存:

```python
self._override_matcher = override_matcher
```

在 `answer()` 方法开头(start = time.monotonic() 之后、extract_query 之前)插入 override 检查:

```python
# Phase 3A: 人工答案覆盖前置检查
if self._override_matcher:
    override = await self._override_matcher.match(query)
    if override:
        elapsed = int((time.monotonic() - start) * 1000)
        return RAGAnswer(
            answer=override.override_answer,
            sources=override.override_sources or [],
            is_answered=True,
            reranked_results=[],
            language=language,
            response_time_ms=elapsed,
        )
```

在 `stream_answer()` 方法开头(rewrite_ms 计算之前)插入 override 检查:

```python
# Phase 3A: 人工答案覆盖前置检查
if self._override_matcher:
    override = await self._override_matcher.match(query)
    if override:
        sources = override.override_sources or []
        yield json.dumps({"type": "sources", "sources": sources})
        yield json.dumps({"type": "token", "content": override.override_answer})
        elapsed = int((time.monotonic() - start) * 1000)
        yield json.dumps({
            "type": "complete",
            "answer": override.override_answer,
            "sources": sources,
            "is_answered": True,
            "language": language,
            "response_time_ms": elapsed,
        })
        return
```

- [ ] **Step 4: 运行全部 rag 测试确认通过**

Run: `pytest tests/pipeline/test_rag.py -v`
Expected: ALL PASSED (原有测试 + 3 新测试)

- [ ] **Step 5: Commit**

```bash
git add backend/pipeline/rag.py tests/pipeline/test_rag.py
git commit -m "feat: RAGOrchestrator 接入 OverrideMatcher 前置检查"
```

---

## Task 5: 答案覆盖 Admin CRUD 端点

**Files:**
- Create: `backend/api/admin/answer_overrides.py`
- Modify: `backend/api/admin/schemas.py` (新增 override schemas)
- Modify: `backend/api/admin/router.py` (注册子路由)
- Test: `tests/api/admin/test_answer_overrides.py`

**Interfaces:**
- Consumes: `backend.db.models.AnswerOverride`、`backend.auth.dependencies`
- Produces: `GET/POST/PATCH/DELETE /api/admin/answer-overrides`

- [ ] **Step 1: 新增 Pydantic schemas**

在 `backend/api/admin/schemas.py` 末尾追加:

```python
class AnswerOverrideOut(BaseModel):
    """答案覆盖输出 schema。"""

    id: str
    match_pattern: str
    match_type: str
    override_answer: str
    override_sources: list = Field(default_factory=list)
    created_by: str | None
    is_active: bool
    created_at: str
    updated_at: str


class AnswerOverrideCreate(BaseModel):
    """答案覆盖创建 schema。"""

    match_pattern: str = Field(..., min_length=1)
    match_type: str = Field(default="semantic", pattern="^(semantic|keyword|regex)$")
    override_answer: str = Field(..., min_length=1)
    override_sources: list = Field(default_factory=list)


class AnswerOverrideUpdate(BaseModel):
    """答案覆盖更新 schema(仅非 None 字段会被写入)。"""

    match_pattern: str | None = None
    match_type: str | None = Field(default=None, pattern="^(semantic|keyword|regex)$")
    override_answer: str | None = None
    override_sources: list | None = None
    is_active: bool | None = None
```

- [ ] **Step 2: 写 CRUD 端点的失败测试**

```python
# tests/api/admin/test_answer_overrides.py
"""答案覆盖 Admin CRUD API 测试。"""

import pytest


@pytest.mark.integration
class TestAnswerOverridesCRUD:
    """覆盖 CRUD 全流程 + 权限校验。"""

    async def test_create_and_list_override(self, admin_client):
        """admin 创建覆盖后,list 中可见。"""
        resp = await admin_client.post("/api/admin/answer-overrides", json={
            "match_pattern": "保修期",
            "match_type": "keyword",
            "override_answer": "保修期为 2 年",
            "override_sources": [{"url": "https://example.com/w", "title": "Warranty"}],
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["match_pattern"] == "保修期"
        assert data["is_active"] is True

        resp = await admin_client.get("/api/admin/answer-overrides")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert any(o["match_pattern"] == "保修期" for o in items)

    async def test_update_override(self, admin_client):
        """admin 更新覆盖内容。"""
        create = await admin_client.post("/api/admin/answer-overrides", json={
            "match_pattern": "test",
            "match_type": "keyword",
            "override_answer": "old answer",
        })
        oid = create.json()["id"]

        resp = await admin_client.patch(f"/api/admin/answer-overrides/{oid}", json={
            "override_answer": "new answer",
        })
        assert resp.status_code == 200
        assert resp.json()["override_answer"] == "new answer"

    async def test_delete_override(self, admin_client):
        """admin 删除覆盖。"""
        create = await admin_client.post("/api/admin/answer-overrides", json={
            "match_pattern": "delete me",
            "match_type": "keyword",
            "override_answer": "temp",
        })
        oid = create.json()["id"]

        resp = await admin_client.delete(f"/api/admin/answer-overrides/{oid}")
        assert resp.status_code == 204

        resp = await admin_client.get("/api/admin/answer-overrides")
        items = resp.json()["items"]
        assert not any(o["id"] == oid for o in items)

    async def test_viewer_cannot_create(self, viewer_client):
        """viewer 角色不能创建覆盖。"""
        resp = await viewer_client.post("/api/admin/answer-overrides", json={
            "match_pattern": "test",
            "match_type": "keyword",
            "override_answer": "answer",
        })
        assert resp.status_code == 403
```

- [ ] **Step 3: 运行测试确认失败**

Run: `pytest tests/api/admin/test_answer_overrides.py -v`
Expected: FAIL — 404 (路由未注册)

- [ ] **Step 4: 实现 CRUD 端点**

```python
# backend/api/admin/answer_overrides.py
"""答案覆盖 CRUD 端点(admin/editor 可写,viewer 只读)。"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.admin.schemas import (
    AnswerOverrideCreate,
    AnswerOverrideOut,
    AnswerOverrideUpdate,
)
from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import AnswerOverride

router = APIRouter(prefix="/answer-overrides", tags=["答案覆盖"])
ViewerDep = Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))]
EditorDep = Annotated[CurrentUser, Depends(require_role("admin", "editor"))]


def _to_out(ov: AnswerOverride) -> AnswerOverrideOut:
    return AnswerOverrideOut(
        id=str(ov.id),
        match_pattern=ov.match_pattern,
        match_type=ov.match_type,
        override_answer=ov.override_answer,
        override_sources=ov.override_sources or [],
        created_by=ov.created_by,
        is_active=ov.is_active,
        created_at=ov.created_at.isoformat() if ov.created_at else "",
        updated_at=ov.updated_at.isoformat() if ov.updated_at else "",
    )


@router.get("")
async def list_overrides(
    _: ViewerDep,
    request: Request,
    is_active: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """查询覆盖列表(viewer+ 可访问)。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        q = select(AnswerOverride)
        count_q = select(func.count()).select_from(AnswerOverride)
        if is_active is not None:
            q = q.where(AnswerOverride.is_active == is_active)
            count_q = count_q.where(AnswerOverride.is_active == is_active)

        total = (await session.execute(count_q)).scalar() or 0
        result = await session.execute(
            q.order_by(AnswerOverride.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        overrides = result.scalars().all()

    return {
        "items": [_to_out(o).model_dump() for o in overrides],
        "total": total,
        "page": page,
        "size": size,
    }


@router.post("", status_code=201)
async def create_override(
    body: AnswerOverrideCreate,
    user: EditorDep,
    request: Request,
) -> dict[str, Any]:
    """创建覆盖(admin/editor),触发 OverrideMatcher refresh。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        ov = AnswerOverride(
            match_pattern=body.match_pattern,
            match_type=body.match_type,
            override_answer=body.override_answer,
            override_sources=body.override_sources,
            created_by=user.email,
            is_active=True,
        )
        session.add(ov)
        await session.commit()
        await session.refresh(ov)

    _refresh_matcher(request)
    return _to_out(ov).model_dump()


@router.patch("/{override_id}")
async def update_override(
    override_id: UUID,
    body: AnswerOverrideUpdate,
    _: EditorDep,
    request: Request,
) -> dict[str, Any]:
    """更新覆盖(admin/editor),触发 OverrideMatcher refresh。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        ov = await session.execute(
            select(AnswerOverride).where(AnswerOverride.id == override_id)
        )
        ov = ov.scalar_one_or_none()
        if ov is None:
            raise HTTPException(status_code=404, detail="覆盖不存在")

        update_data = body.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(ov, key, value)
        await session.commit()
        await session.refresh(ov)

    _refresh_matcher(request)
    return _to_out(ov).model_dump()


@router.delete("/{override_id}", status_code=204)
async def delete_override(
    override_id: UUID,
    _: EditorDep,
    request: Request,
) -> None:
    """删除覆盖(admin/editor),触发 OverrideMatcher refresh。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        ov = await session.execute(
            select(AnswerOverride).where(AnswerOverride.id == override_id)
        )
        ov = ov.scalar_one_or_none()
        if ov is None:
            raise HTTPException(status_code=404, detail="覆盖不存在")
        await session.delete(ov)
        await session.commit()

    _refresh_matcher(request)


def _refresh_matcher(request: Request) -> None:
    """触发 OverrideMatcher 刷新缓存(如果已初始化)。"""
    matcher = getattr(request.app.state, "override_matcher", None)
    if matcher is not None:
        import asyncio

        asyncio.create_task(matcher.refresh())
```

- [ ] **Step 5: 注册路由**

在 `backend/api/admin/router.py` 中添加:

```python
from backend.api.admin.answer_overrides import router as answer_overrides_router

# 在 admin_router.include_router 列表中添加:
admin_router.include_router(answer_overrides_router)
```

- [ ] **Step 6: 运行测试确认通过**

Run: `pytest tests/api/admin/test_answer_overrides.py -v`
Expected: 4 PASSED

- [ ] **Step 7: Commit**

```bash
git add backend/api/admin/answer_overrides.py backend/api/admin/schemas.py backend/api/admin/router.py tests/api/admin/test_answer_overrides.py
git commit -m "feat: 答案覆盖 Admin CRUD 端点 + OverrideMatcher refresh 触发"
```

---

## Task 6: main.py 接入 OverrideMatcher

**Files:**
- Modify: `backend/main.py`

**Interfaces:**
- Consumes: `backend.services.override_matcher.OverrideMatcher`、`backend.embedder.base.Embedder`
- Produces: `app.state.override_matcher`、`RAGOrchestrator` 获得.override_matcher

- [ ] **Step 1: 修改 main.py — 初始化 OverrideMatcher**

在 `backend/main.py` lifespan 中,创建 RAGOrchestrator 之前(line ~201 之后):

```python
# OverrideMatcher(Phase 3A):人工答案覆盖匹配
from backend.services.override_matcher import OverrideMatcher

override_matcher = OverrideMatcher(app.state.session_factory, embedder)
await override_matcher.refresh()
app.state.override_matcher = override_matcher
logger.info("OverrideMatcher 已加载(%d 条覆盖)", len(override_matcher._overrides))
```

在 `RAGOrchestrator` 构造时传入:

```python
app.state.rag = RAGOrchestrator(
    searcher=searcher,
    reranker=rerank_pipeline,
    llm=router_llm,
    system_prompt=system_prompt,
    channel_customizations=channel_customizations,
    pruner=pruner,
    override_matcher=override_matcher,
)
```

- [ ] **Step 2: 验证启动正常**

Run: `python -c "import asyncio; from backend.main import app; print('OK')"`
Expected: 无报错(仅 import 检查,不触发 lifespan)

- [ ] **Step 3: Commit**

```bash
git add backend/main.py
git commit -m "feat: main.py lifespan 接入 OverrideMatcher + Pruner"
```

---

## Task 7: Admin 前端 — 答案覆盖管理页面

**Files:**
- Create: `admin/src/pages/AnswerOverrides.tsx`
- Create: `admin/src/hooks/useAnswerOverrides.ts`
- Modify: `admin/src/types/api.ts`
- Modify: `admin/src/App.tsx`
- Modify: `admin/src/components/Sidebar.tsx`

**Interfaces:**
- Consumes: `/api/admin/answer-overrides` REST API
- Produces: `/admin/answer-overrides` 页面

- [ ] **Step 1: 新增 TypeScript 类型**

在 `admin/src/types/api.ts` 末尾追加:

```typescript
export interface AnswerOverride {
  id: string;
  match_pattern: string;
  match_type: "semantic" | "keyword" | "regex";
  override_answer: string;
  override_sources: unknown[];
  created_by: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface AnswerOverrideList {
  items: AnswerOverride[];
  total: number;
  page: number;
  size: number;
}
```

- [ ] **Step 2: 新增 React Query hooks**

```typescript
// admin/src/hooks/useAnswerOverrides.ts
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/lib/api";
import type { AnswerOverride, AnswerOverrideList } from "@/types/api";

export function useAnswerOverrides() {
  return useQuery({
    queryKey: ["answer-overrides"],
    queryFn: () => apiFetch<AnswerOverrideList>("/answer-overrides"),
  });
}

export function useCreateOverride() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      match_pattern: string;
      match_type: string;
      override_answer: string;
      override_sources?: unknown[];
    }) => apiFetch<AnswerOverride>("/answer-overrides", { method: "POST", body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["answer-overrides"] }),
  });
}

export function useUpdateOverride() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...data }: { id: string } & Partial<AnswerOverride>) =>
      apiFetch<AnswerOverride>(`/answer-overrides/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["answer-overrides"] }),
  });
}

export function useDeleteOverride() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => apiFetch<void>(`/answer-overrides/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["answer-overrides"] }),
  });
}
```

- [ ] **Step 3: 实现 AnswerOverrides 页面**

参照 `admin/src/pages/DataSources.tsx` 的模式创建 `admin/src/pages/AnswerOverrides.tsx`:

- 表格展示:match_pattern / match_type / is_active / created_at
- 创建对话框:match_pattern(input) + match_type(select: semantic/keyword/regex) + override_answer(textarea) + override_sources(可选)
- 编辑对话框:同创建,预填已有值
- 删除按钮(带确认)
- 启用/禁用 toggle(is_active)
- 响应式:桌面表格 + 移动卡片

- [ ] **Step 4: 注册路由**

在 `admin/src/App.tsx` 中添加:

```typescript
import AnswerOverrides from "@/pages/AnswerOverrides";

// 在 Routes 中添加:
<Route path="/answer-overrides" element={<AnswerOverrides />} />
```

- [ ] **Step 5: 添加导航项**

在 `admin/src/components/Sidebar.tsx` 的 `NAV_ITEMS` 中添加:

```typescript
import { CheckSquare } from "lucide-react";

// 在 conversations 之前添加:
{ to: "/answer-overrides", icon: CheckSquare, label: "答案覆盖", roles: ["admin", "editor", "viewer"] },
```

- [ ] **Step 6: 验证前端编译**

Run: `cd admin && npm run build`
Expected: 构建成功,无 TypeScript 错误

- [ ] **Step 7: Commit**

```bash
git add admin/src/pages/AnswerOverrides.tsx admin/src/hooks/useAnswerOverrides.ts admin/src/types/api.ts admin/src/App.tsx admin/src/components/Sidebar.tsx
git commit -m "feat: Admin 答案覆盖管理页面(CRUD + 启用/禁用)"
```

---

## Task 8: 对话审查详情页"改进此答案"按钮

**Files:**
- Modify: `admin/src/pages/Conversations.tsx`

**Interfaces:**
- Consumes: `react-router-dom` 的 `useNavigate`、`AnswerOverride` 创建 API

- [ ] **Step 1: 在 Conversations.tsx 详情对话框中添加"改进此答案"按钮**

在对话详情视图中(展示 question/answer 的区域),添加一个按钮:

```typescript
import { useNavigate } from "react-router-dom";
import { Lightbulb } from "lucide-react";

// 在详情区域添加:
<Button
  variant="outline"
  size="sm"
  onClick={() => {
    // 把问题和答案传到答案覆盖页面
    navigate("/answer-overrides", {
      state: {
        prefill: {
          match_pattern: conversation.question,
          override_answer: conversation.answer || "",
        },
      },
    });
  }}
>
  <Lightbulb className="h-4 w-4" />
  改进此答案
</Button>
```

- [ ] **Step 2: AnswerOverrides 页面读取 prefill state**

在 `AnswerOverrides.tsx` 中,从 `useLocation().state` 读取 prefill:

```typescript
import { useLocation } from "react-router-dom";

const location = useLocation();
const prefill = (location.state as { prefill?: { match_pattern?: string; override_answer?: string } } | null)?.prefill;

// 如果有 prefill,自动打开创建对话框并预填
useEffect(() => {
  if (prefill) {
    setCreateOpen(true);
    setForm({
      match_pattern: prefill.match_pattern || "",
      match_type: "semantic",
      override_answer: prefill.override_answer || "",
    });
  }
}, [prefill]);
```

- [ ] **Step 3: 验证前端编译**

Run: `cd admin && npm run build`
Expected: 构建成功

- [ ] **Step 4: Commit**

```bash
git add admin/src/pages/Conversations.tsx admin/src/pages/AnswerOverrides.tsx
git commit -m "feat: 对话审查详情页添加'改进此答案'按钮(prefill 到覆盖页面)"
```

---

## Task 9: 端到端验证

- [ ] **Step 1: 运行全部测试**

Run: `pytest tests/ -v --tb=short`
Expected: ALL PASSED

- [ ] **Step 2: 手动验证 Pruner**

1. 在 Admin LLM 供应商页面添加 deepseek-v4-flash provider
2. 在 LLM 路由页面配置 `pruning` task 指向该 provider
3. 重启后端,确认日志显示 "Pruner 已启用"
4. 在 Widget 提问,观察后端日志中是否有 pruning LLM 调用
5. 对比 Pruner 启用前后的答案质量

- [ ] **Step 3: 手动验证 Improve This Answer**

1. 在 Admin 答案覆盖页面创建一条 keyword 覆盖
2. 在 Widget 提问匹配的问题
3. 确认直接返回覆盖答案(后端日志无 search/rerank/generate)
4. 从对话审查详情页点击"改进此答案",确认跳转到覆盖页面且预填
5. 禁用覆盖后重新提问,确认恢复正常 RAG 流程

- [ ] **Step 4: Commit**

```bash
git commit --allow-empty -m "test: Phase 3A 端到端验证通过"
```
