# 对话可观测体系实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 ask-ai admin 的"运营"三页(业务概览 / 对话审查 / 技术洞察)从空壳/简单列表重做成"业务情报 → 单条诊断 → 系统洞察"闭环,建立 trace 数据层支撑诊断与 eval skill。

**Architecture:** 新建 `traces` 表(1 conversation : N trace,记 RAG 各阶段耗时/异常/降级/config_snapshot),RAG pipeline `answer()` 全量插桩写 trace;后端新增聚合 API(业务概览/技术性能/知识缺口);前端三页按设计稿重做(Linear 风格,共享设计 token),复用现有 `/conversations`、`/analytics` 路由,新增 `/`(业务概览填充空壳)。

**Tech Stack:** FastAPI + SQLAlchemy 2.0(async)+ PostgreSQL JSONB(后端);React + TypeScript + Tailwind + shadcn/ui(前端);pytest(后端测试)+ Vitest + Playwright(前端测试)。

## Global Constraints

- **语言**:所有对话/回复/代码注释用中文简体(用户全局规则)。
- **建表**:用 `Base.metadata.create_all`(`backend/db/session.py:init_db`),**无 alembic**——新模型加到 `backend/db/models.py` 即在启动时自动建表,不写迁移脚本。
- **测试隔离**:后端测试必须设 `TEST_DATABASE_URL=ask_ai_test`,否则 conftest 的 `drop_all` 清开发库(曾出事,见 memory `test-db-isolation`)。
- **禁止向量库操作**:实现过程**绝不**触发 reindex 或向量删除(`--source X --reindex` 会删整个 collection,曾误删 560k chunk,见 memory `reindex-deletes-entire-collection`)。
- **tesla-t4 约束**:GPU 共享生产服务,部署阶段不停止 locate-anything/llama-server/neomind;`EMBEDDER_BATCH_SIZE ≤16`(见 memory `tesla-t4-deployment`)。
- **commit 风格**:中文 conventional commits(`feat:`/`fix:`/`refactor:` 等),**禁** "Generated with Claude" 署名(全局 settings 已关)。
- **设计 token**(三页统一,已在原型验证):`--bg:#fafafa --panel:#fff --bd:#ececec --t1:#111827 --t2:#6b7280 --t3:#9ca3af --acc:#4f46e5 --acc-t:#eef2ff --warn:#b45309 --err:#dc2626 --ok:#059669`;字体 12/13/14/17(基础)+ 18/20/24/28(KPI 大数字);`.wrap` max-width 1100px / padding 16px / 卡片圆角 8px。

## 范围决策(已与用户确认)

1. **trace 数据层**:建 `traces` 表 + **全量记**(每个对话都建 trace 行,不抽样)。
2. **业务信号源**:Phase 1 含 LLM 提取 pipeline(场景应用/产品需求用 LLM 后处理批跑)。
3. **技术性能数据**:从 `traces.stages` jsonb 聚合 P50/P95/异常/retry/失败。

---

## 文件结构

**后端新建/修改:**
- 修改 `backend/db/models.py` — 新增 `Trace` 模型(1 conversation : N trace)。
- 新建 `backend/api/admin/traces.py` — trace 数据 API(list traces by conversation / 聚合技术性能)。
- 修改 `backend/api/admin/analytics.py` — 新增业务概览聚合端点(销售线索/场景/产品需求/地域)。
- 修改 `backend/api/admin/conversations.py` — list 端点补 trace 摘要(迷你阶段条数据)。
- 修改 `backend/api/admin/router.py` — 注册 traces_router。
- 修改 `backend/api/admin/schemas.py` — Trace / 技术性能 / 业务概览 Pydantic schema。
- 修改 `backend/pipeline/rag.py` — `answer()` / `stream_answer()` 插桩写 trace。
- 新建 `backend/pipeline/business_signals.py` — LLM 后处理提取场景/产品需求(批跑)。
- 新建 `backend/pipeline/business_signals_runner.py` — 调度入口(按周期/手动触发)。
- 修改 `backend/main.py` — 注册 business_signals 调度(lifespan)。

**前端新建/修改:**
- 新建 `admin/src/pages/BusinessOverview.tsx` — 业务概览页。
- 重写 `admin/src/pages/Conversations.tsx` — 对话审查(列表 + trace 5 泳道详情)。
- 重写 `admin/src/pages/Analytics.tsx` — 技术洞察(技术性能 + 知识缺口双 tab)。
- 修改 `admin/src/App.tsx` — `/` 改为 BusinessOverview(不再重定向)、`/analytics` 路由保留(改名技术洞察)。
- 重写 `admin/src/components/Sidebar.tsx` — 分两组:**运营组**(业务概览 / 对话审查 / 技术洞察)、**配置组**(数据源 / 对话接入 / 模型配置 / 答案覆盖 / 用户管理);"概览"→"业务概览"、"分析仪表盘"→"技术洞察"。
- 新建 `admin/src/lib/api/businessOverview.ts` / `techInsight.ts` / `traces.ts` — API 客户端。
- 新建 `admin/src/components/observability/` — 共享组件(KpiCard / StageBar / TrendChart / TraceLanes / TimeFilter)。

**测试:**
- 后端:`tests/api/test_traces.py`、`tests/api/test_analytics_business.py`、`tests/pipeline/test_rag_trace.py`、`tests/pipeline/test_business_signals.py`。
- 前端:`admin/tests/BusinessOverview.test.tsx`、`admin/tests/ConversationsReview.test.tsx`、`admin/tests/TechInsight.test.tsx`。

---

## Task 1: Trace 数据模型

**Files:**
- Modify: `backend/db/models.py`(新增 `Trace` 类,约 66-97 行附近,Conversation 之后)
- Test: `tests/test_models_trace.py`(新建)

**Interfaces:**
- Produces: `Trace` ORM 模型,字段见下;`Conversation.traces` relationship(反向 `trace.conversation`)。

- [ ] **Step 1: 写失败测试 — Trace 模型字段与关系**

```python
# tests/test_models_trace.py
import pytest
from sqlalchemy import inspect
from backend.db.models import Trace, Conversation

@pytest.mark.asyncio
async def test_trace_model_columns():
    """Trace 模型有所需字段,且 conversation_id 外键到 conversations。"""
    mapper = inspect(Trace)
    cols = {c.key for c in mapper.columns}
    expected = {"id", "conversation_id", "prev_trace_id", "turn_index",
                "type", "stages", "total_ms", "intent", "confidence",
                "config_snapshot", "created_at"}
    assert expected.issubset(cols), f"缺少字段: {expected - cols}"

@pytest.mark.asyncio
async def test_trace_conversation_relationship():
    """Conversation.traces 反向关系存在,1:N。"""
    mapper = inspect(Conversation)
    assert "traces" in mapper.relationships, "Conversation 缺 traces relationship"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_models_trace.py -v`
Expected: FAIL — `Trace` 未定义

- [ ] **Step 3: 实现 Trace 模型**

**先补 import**:在 `backend/db/models.py` 的 `from sqlalchemy import(...)` 块中加 `Float`(当前无)。

在 `backend/db/models.py` 的 `Conversation` 类之后、`SourceClick` 之前插入:

```python
class Trace(Base):
    """单轮 RAG/澄清/拒答的执行 trace,1 conversation : N trace。"""

    __tablename__ = "traces"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    prev_trace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("traces.id", ondelete="SET NULL"), nullable=True
    )
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # rag: 正常生成 / clarify: 触发澄清追问 / reject_short: off_topic 或 <min 短路
    type: Mapped[str] = mapped_column(String(20), nullable=False, default="rag")
    # 各阶段: {intent, rewrite, retrieve, rerank, generate, output} 各含 ms/详情/异常
    stages: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    total_ms: Mapped[int | None] = mapped_column(Integer)
    intent: Mapped[str | None] = mapped_column(String(100))
    confidence: Mapped[float | None] = mapped_column(Float)
    # 阈值/model 版本快照,改配置后老 trace 仍可对照
    config_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped["Conversation"] = relationship(back_populates="traces")
    prev_trace: Mapped["Trace | None"] = relationship(
        remote_side="Trace.id", foreign_keys=[prev_trace_id]
    )
```

在 `Conversation` 类补反向关系(与 `clicks`/`attachments` 并列):

```python
    traces: Mapped[list["Trace"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan",
        foreign_keys="Trace.conversation_id",
    )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `TEST_DATABASE_URL=ask_ai_test pytest tests/test_models_trace.py -v`
Expected: PASS

- [ ] **Step 5: 冒烟验证建表**

Run: `TEST_DATABASE_URL=ask_ai_test python -c "import asyncio; from backend.db.session import init_db, get_engine; asyncio.run(init_db(get_engine('ask_ai_test')))"` 
Expected: 无报错,`traces` 表建出(用 `\d traces` 或 information_schema 验证)

- [ ] **Step 6: Commit**

```bash
git add backend/db/models.py tests/test_models_trace.py
git commit -m "feat: 新增 Trace 数据模型(1 conversation : N trace)"
```

---

## Task 2: RAG pipeline trace 插桩

**Files:**
- Modify: `backend/pipeline/rag.py`(`answer()` 354 行起、`stream_answer()` 同文件)
- Test: `tests/pipeline/test_rag_trace.py`(新建)

**Interfaces:**
- Consumes: `Trace` 模型(Task 1)、`RAGAnswer`(rag.py:65)、`classify_intent`/`extract_query`/`rewrite_query` 阶段函数。
- Produces: `answer()` / `stream_answer()` 返回的 `RAGAnswer` 多带 `trace_payload: dict`(含各阶段 ms/详情/异常/type/config_snapshot),由 API 端点层(Task 3)落库。

- [ ] **Step 1: 写失败测试 — answer() 产出 trace_payload**

```python
# tests/pipeline/test_rag_trace.py
"""RAG trace 插桩测试。

answer() 签名: answer(query, channel='widget', conversation_history=None, product_filter=None)
—— 第一个位置参数是 query,无 language 参数(语言在内部 detect_language 检测)。
IntentResult 只有 category + reason,无 confidence。

mock 策略:mock searcher/reranker/llm 的最小契约,让 answer() 全流程跑通。
参考 tests/pipeline/ 现有测试的 mock 模式(若有 fixture 复用)。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.pipeline.rag import RAGOrchestrator
from backend.pipeline.intent import IntentResult
from backend.llm.base import LLMResponse


def _build_test_orchestrator(*, intent_category="commercial") -> RAGOrchestrator:
    """构造 mock 依赖的 orchestrator。intent_category 控制意图分类返回。"""
    llm = MagicMock()
    llm.generate = AsyncMock(return_value=LLMResponse(
        content="答案", model="test", tokens_input=10, tokens_output=5, latency_ms=100))
    # classify_intent 调 llm.generate(task='intent')
    def _generate_side_effect(messages, **kwargs):
        task = kwargs.get("task", "generation")
        if task == "intent":
            return LLMResponse(
                content=f'{{"category":"{intent_category}","reason":"test"}}',
                model="test", tokens_input=5, tokens_output=5, latency_ms=20)
        return LLMResponse(content="答案文本", model="test",
                           tokens_input=10, tokens_output=5, latency_ms=100)
    llm.generate = AsyncMock(side_effect=_generate_side_effect)

    searcher = MagicMock()
    searcher.search = MagicMock(return_value=[])
    searcher.search_symbols = MagicMock(return_value=[])
    searcher.search_bucket = MagicMock(return_value=[])

    reranker = MagicMock()
    # 返回足够结果越过 effective_min(=1 for commercial/product/support)
    reranker.rerank = MagicMock(return_value=[MagicMock(
        url="http://x", title="t", text="ctx", source_type="github",
        product="NE503", score=0.9)])

    return RAGOrchestrator(
        searcher=searcher, reranker=reranker, llm=llm,
        system_prompt="test", min_results_to_answer=1)


@pytest.mark.asyncio
async def test_answer_produces_trace_payload():
    """正常 RAG 流程,answer() 返回的 RAGAnswer 带 trace_payload,含 5 阶段 ms。"""
    orch = _build_test_orchestrator(intent_category="commercial")
    result = await orch.answer("NE503 价格", channel="widget")
    assert result.trace_payload is not None
    tp = result.trace_payload
    assert tp["type"] == "rag"
    for stage in ("intent", "rewrite", "retrieve", "rerank", "generate"):
        assert stage in tp["stages"]
        assert "ms" in tp["stages"][stage]
    assert tp["total_ms"] > 0
    assert tp["intent"] == "commercial"


@pytest.mark.asyncio
async def test_answer_off_topic_trace_type():
    """off_topic 短路:trace_payload type=reject_short,只含 intent 阶段。"""
    orch = _build_test_orchestrator(intent_category="off_topic")
    result = await orch.answer("今天天气", channel="widget")
    assert result.trace_payload["type"] == "reject_short"
    assert "intent" in result.trace_payload["stages"]
    assert "generate" not in result.trace_payload["stages"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `TEST_DATABASE_URL=ask_ai_test pytest tests/pipeline/test_rag_trace.py -v`
Expected: FAIL — `trace_payload` 不存在

- [ ] **Step 3: 给 RAGAnswer 加 trace_payload 字段**

`backend/pipeline/rag.py` 的 `RAGAnswer` dataclass(65 行)加:

```python
    trace_payload: dict | None = None  # 各阶段耗时/异常,供端点层落 trace 表
```

- [ ] **Step 4: answer() 插桩**

`answer()`(354 行)改造:把 `start = time.monotonic()` 拆成各阶段计时,记 `stages` dict。

**注意真实代码约束(Analysis Gate delta)**:
- `IntentResult` 无 `confidence` 字段(只有 `category`+`reason`)→ trace_payload 的 confidence 用 `None`,不要写 `intent.confidence`(会 AttributeError)。
- `LLMResponse` 无 `ttft_ms`/`token_count`(字段为 `latency_ms`/`tokens_output`)→ generate 阶段记 `latency_ms` + `tokens_output`,用 `getattr` 兜底。
- `answer()` 签名是 `answer(query, channel, conversation_history, product_filter)` — 传入的第一个位置参数是 `query`(无 `language` 参数,语言在内部检测)。
- off_topic 短路 / <min_results 短路 / override 命中 三条早返回路径都要填 `trace_payload`。

```python
# 在 answer() 内
stages: dict[str, Any] = {}
t_intent = time.monotonic()
intent = await classify_intent(query, self._llm)
stages["intent"] = {"ms": int((time.monotonic() - t_intent) * 1000),
                    "category": intent.category, "reason": intent.reason}
if intent.category == "off_topic":
    elapsed = int((time.monotonic() - start) * 1000)
    return RAGAnswer(
        answer=REJECT_OFF_TOPIC, sources=[], is_answered=False,
        reranked_results=[], language=language, response_time_ms=elapsed,
        intent=intent.category,
        trace_payload={"type": "reject_short", "stages": stages, "total_ms": elapsed,
                       "intent": intent.category, "confidence": None,
                       "config_snapshot": self._config_snapshot()})

t_rewrite = time.monotonic()
extracted = await extract_query(query, self._llm)
search_query = await rewrite_query(extracted, conversation_history, self._llm)
stages["rewrite"] = {"ms": int((time.monotonic() - t_rewrite) * 1000),
                     "extracted": extracted, "rewritten": search_query}

t_ret = time.monotonic()
fused = await self._retrieve_and_fuse(
    extracted, search_query, intent.category,
    product_filter=product_filter, channel=channel)
stages["retrieve"] = {"ms": int((time.monotonic() - t_ret) * 1000),
                      "hybrid_count": len(fused), "min_results_met": len(fused) >= effective_min}

t_rr = time.monotonic()
reranked = self._reranker.rerank(search_query, fused, top_k=self._top_k)
if self._pruner:
    reranked = await self._pruner.prune(search_query, reranked)
stages["rerank"] = {"ms": int((time.monotonic() - t_rr) * 1000),
                    "top_score": reranked[0].score if reranked else None,
                    "count": len(reranked)}

if len(reranked) < effective_min:
    elapsed = int((time.monotonic() - start) * 1000)
    return RAGAnswer(
        answer=REJECT_ANSWER, sources=[], is_answered=False,
        reranked_results=[], language=language, response_time_ms=elapsed,
        intent=intent.category,
        trace_payload={"type": "reject_short", "stages": stages, "total_ms": elapsed,
                       "intent": intent.category, "confidence": None,
                       "config_snapshot": self._config_snapshot()})

context = self._build_context(reranked)
messages = self._build_messages(query, context, language, conversation_history, channel, intent=intent.category)
t_gen = time.monotonic()
llm_response = await self._llm.generate(messages, task="generation")
stages["generate"] = {"ms": int((time.monotonic() - t_gen) * 1000),
                      "latency_ms": getattr(llm_response, "latency_ms", None),
                      "tokens_output": getattr(llm_response, "tokens_output", None)}
sources = self._extract_sources(reranked)
stages["output"] = {"ms": 0, "sources_count": len(sources)}

elapsed = int((time.monotonic() - start) * 1000)
return RAGAnswer(
    answer=llm_response.content, sources=sources, is_answered=True,
    reranked_results=reranked, language=language, response_time_ms=elapsed,
    intent=intent.category,
    trace_payload={"type": "rag", "stages": stages, "total_ms": elapsed,
                   "intent": intent.category, "confidence": None,
                   "config_snapshot": self._config_snapshot()})
```

新增私有方法 `_config_snapshot()` 返回当前阈值/top_k/model 等配置:

```python
def _config_snapshot(self) -> dict[str, Any]:
    return {
        "alpha": self._alpha,
        "recall_limit": self._recall_limit,
        "top_k": self._top_k,
        "min_results": self._min_results,
        "has_pruner": self._pruner is not None,
    }
```

- [ ] **Step 5: stream_answer() 插桩(复用已有 timing)**

`stream_answer()` **已有** per-stage 计时(`rewrite_ms`/`search_ms`/`rerank_ms`/`first_token_ms`/`llm_ms`,见 rag.py 547-611)。**不要重写计时逻辑**——在最终 `complete` 事件前,把已有计时 + intent 阶段(需新增 `t_intent`/`intent_ms`)重组为 `trace_payload` 结构,注入到 `complete` 事件 payload 中(`data["trace_payload"] = ...`)。

关键:在 `classify_intent` 前后加 `t_intent = time.monotonic()` / `intent_ms = int((time.monotonic()-t_intent)*1000)`。然后在 `complete` 事件 dict 中加:

```python
trace_payload = {
    "type": "rag",
    "stages": {
        "intent": {"ms": intent_ms, "category": intent.category, "reason": intent.reason},
        "rewrite": {"ms": rewrite_ms, "extracted": extracted, "rewritten": search_query},
        "retrieve": {"ms": search_ms, "hybrid_count": len(fused)},
        "rerank": {"ms": rerank_ms, "count": len(reranked)},
        "generate": {"ms": llm_ms, "ttft_ms": first_token_ms},
        "output": {"ms": 0, "sources_count": len(sources)},
    },
    "total_ms": elapsed,
    "intent": intent.category,
    "confidence": None,
    "config_snapshot": self._config_snapshot(),
}
```

在 off_topic / <min_results 短路分支的 `complete` 事件中也注入对应的 `trace_payload`(type=reject_short,stages 只含已执行的阶段)。API 层(Task 3)从 `complete` 事件提取 `trace_payload` 落库。

- [ ] **Step 5b: clarify 分支插桩(澄清追问)**

**当前 RAG pipeline 无 clarify 分支**(不会触发澄清追问)。跳过本步,在 CHECKPOINT.md 注明"clarify 分支待后续接入"。Task 10 澄清漏斗降级为:API 返回空结构 + 前端标"暂无数据"。

- [ ] **Step 6: 运行测试确认通过**

Run: `TEST_DATABASE_URL=ask_ai_test pytest tests/pipeline/test_rag_trace.py -v`
Expected: PASS

- [ ] **Step 7: 回归现有 RAG 测试**

Run: `TEST_DATABASE_URL=ask_ai_test pytest tests/pipeline/ -v`
Expected: 全 PASS(现有测试不应因加 trace_payload 失败,因为它是新字段默认 None)

- [ ] **Step 8: Commit**

```bash
git add backend/pipeline/rag.py tests/pipeline/test_rag_trace.py
git commit -m "feat: RAG pipeline 全量插桩,产出 trace_payload(各阶段耗时/异常)"
```

---

## Task 3: API 端点层落 trace 表

**Files:**
- Modify: `backend/api/routes.py`(`/ask` 64 行、流式 123 行)
- Modify: `backend/api/admin/traces.py`(新建)
- Modify: `backend/api/admin/schemas.py`
- Modify: `backend/api/admin/router.py`
- Test: `tests/api/test_traces.py`(新建)

**Interfaces:**
- Consumes: `RAGAnswer.trace_payload`(Task 2)、`Trace` 模型(Task 1)、`Conversation` 模型。
- Produces: `POST /api/admin/traces` 内部由 `/ask` 调用落库;`GET /api/admin/conversations/{id}/traces` 返回该对话所有 trace(按 turn_index 排序)。

- [ ] **Step 1: 写失败测试 — /ask 落 trace,GET traces 返回**

**注意**:`/ask` 是 SSE 流式端点,返回 `EventSourceResponse`(非普通 JSON)。测试需用 `httpx` 的 SSE 模式或直接调 `stream_answer()` + 手动落库验证。更简单的策略:直接测 `GET /conversations/{id}/traces` 端点(先 seed Trace 行到 DB,再 GET 验证)。`/ask`→trace 落库的 E2E 留给 Real-Run Gate。

```python
# tests/api/test_traces.py
"""trace 查询端点测试。

模式参照 tests/api/admin/test_conversations.py:用 app.state.session_factory seed 数据,
ASGITransport + AsyncClient 请求,精准清理。
"""
import uuid
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import Conversation, Trace, User
from backend.main import app

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def trace_auth_and_seed():
    """seed 1 条 conversation + 1 条 trace,返回 (headers, conversation_id)。"""
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    conv_id = uuid.uuid4()
    async with factory() as session:
        session.add(User(id=user_id, email="trace-test@test.com", role="admin",
                         password_hash=hash_password("pass")))
        session.add(Conversation(id=conv_id, question="NE503 价格", channel="widget",
                                 is_answered=True, intent_tag="commercial"))
        session.add(Trace(
            conversation_id=conv_id, turn_index=0, type="rag",
            stages={"intent": {"ms": 50}, "generate": {"ms": 500}},
            total_ms=800, intent="commercial", config_snapshot={}))
        await session.commit()
    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}, str(conv_id)
    async with factory() as session:
        await session.execute(Trace.__table__.delete().where(Trace.conversation_id == conv_id))
        await session.execute(Conversation.__table__.delete().where(Conversation.id == conv_id))
        await session.execute(User.__table__.delete().where(User.id == user_id))
        await session.commit()


async def test_list_traces(trace_auth_and_seed):
    auth_headers, conv_id = trace_auth_and_seed
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(f"/api/admin/conversations/{conv_id}/traces", headers=auth_headers)
    assert resp.status_code == 200
    traces = resp.json()
    assert len(traces) >= 1
    t = traces[0]
    assert t["type"] == "rag"
    assert "generate" in t["stages"]
    assert t["intent"] == "commercial"
```

- [ ] **Step 2: 运行确认失败**

Run: `TEST_DATABASE_URL=ask_ai_test pytest tests/api/test_traces.py -v`
Expected: FAIL — `/traces` 端点不存在(404)

- [ ] **Step 3: 新建 traces API + schema**

`backend/api/admin/schemas.py` 加(Pydantic v2 写法):

```python
from datetime import datetime
from pydantic import BaseModel, ConfigDict

class TraceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    conversation_id: str
    prev_trace_id: str | None
    turn_index: int
    type: str
    stages: dict
    total_ms: int | None
    intent: str | None
    confidence: float | None
    config_snapshot: dict
    created_at: datetime
```

`backend/api/admin/traces.py`(**用 `request.app.state.session_factory`**,不用 `Depends(get_session)`):

```python
"""trace 查询 + 技术性能聚合端点。"""
from uuid import UUID
from typing import Any
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from backend.api.admin.schemas import TraceOut
from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import Trace

traces_router = APIRouter(prefix="/conversations", tags=["trace"])
ViewerDep = Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))]

@traces_router.get("/{conversation_id}/traces")
async def list_traces(
    conversation_id: UUID,
    _: ViewerDep,
    request: Request,
) -> list[dict[str, Any]]:
    """返回该对话所有 trace(按 turn_index 排序)。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        rows = await session.execute(
            select(Trace).where(Trace.conversation_id == conversation_id)
            .order_by(Trace.turn_index))
        traces = rows.scalars().all()
    return [
        {"id": str(t.id), "conversation_id": str(t.conversation_id),
         "prev_trace_id": str(t.prev_trace_id) if t.prev_trace_id else None,
         "turn_index": t.turn_index, "type": t.type, "stages": t.stages,
         "total_ms": t.total_ms, "intent": t.intent, "confidence": t.confidence,
         "config_snapshot": t.config_snapshot,
         "created_at": t.created_at.isoformat() if t.created_at else ""}
        for t in traces
    ]
```

`router.py` 加 `from backend.api.admin.traces import traces_router` 和 `admin_router.include_router(traces_router)`。(Task 4 的技术性能聚合用**独立的** `tech_router`,prefix `/tech`,不要与本 router 共用前缀。)

- [ ] **Step 4: /ask 端点落库 trace(SSE complete 事件提取)**

**`/ask` 是 SSE-only**,调 `stream_answer()`。trace_payload 在 `complete` 事件中(Task 2 Step 5 注入)。在 `backend/api/routes.py` 的 `event_generator()` 内,已有 `data = json.loads(chunk)` / `evt_type = data["type"]`。在 `elif evt_type == "complete":` 分支中提取 `trace_payload` 并存到局部变量,然后在 conversation 落库段(已有 `async with session_factory() as session:`)一并写 Trace:

```python
# 在 event_generator() 内,complete 分支中:
elif evt_type == "complete":
    ...
    elapsed = data.get("response_time_ms", 0)
    intent = data.get("intent")
    trace_payload = data.get("trace_payload")  # Task 2 Step 5 注入

# 在持久化段(已有 conv = Conversation(...); session.add(conv))后加:
if trace_payload:
    trace = Trace(
        conversation_id=uuid.UUID(conversation_id),
        turn_index=0,  # 当前每次 /ask 建新 conversation,turn_index 恒 0
        type=trace_payload.get("type", "rag"),
        stages=trace_payload.get("stages", {}),
        total_ms=trace_payload.get("total_ms"),
        intent=trace_payload.get("intent"),
        confidence=trace_payload.get("confidence"),
        config_snapshot=trace_payload.get("config_snapshot", {}),
    )
    session.add(trace)
```

`turn_index` 当前恒 0(每次 `/ask` `uuid.uuid4()` 建新 conversation)。多轮 trace 需后续接入 session 续接。

- [ ] **Step 5: 运行测试确认通过**

Run: `TEST_DATABASE_URL=ask_ai_test pytest tests/api/test_traces.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/api/routes.py backend/api/admin/traces.py backend/api/admin/schemas.py backend/api/admin/router.py tests/api/test_traces.py
git commit -m "feat: /ask 落 trace 表 + GET /conversations/{id}/traces 端点"
```

---

## Task 4: 技术性能聚合 API

**Files:**
- Modify: `backend/api/admin/traces.py` — 新增聚合端点
- Modify: `backend/api/admin/schemas.py`
- Test: `tests/api/test_tech_perf.py`(新建)

**Interfaces:**
- Consumes: `Trace.stages` JSONB(Task 3)。
- Produces: `GET /api/admin/tech/performance?from=&to=` 返回:
  - KPI:P95 总耗时 / 异常率 / retry 率 / 失败率 + 环比 + 基线
  - 阶段 P50/P95 表(每阶段 normal_range 超标标橙)
  - P50/P95 趋势(按天/按小时)
  - 异常分布(LLM 超时/降级/其他)
  - 降级链路

- [ ] **Step 1: 写失败测试 — 聚合正确性**

**测试模式参照 Task 3**:seed Trace 行到 DB,ASGITransport 请求。seed fixture 创建多条 trace(含 rag/reject_short),然后断言聚合结果。

```python
# tests/api/test_tech_perf.py
import uuid, pytest, pytest_asyncio
from httpx import ASGITransport, AsyncClient
from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import Conversation, Trace, User
from backend.main import app

pytestmark = pytest.mark.asyncio(loop_scope="session")

@pytest_asyncio.fixture(loop_scope="session")
async def tech_perf_seed():
    """seed: 10 条 rag trace(total_ms 各不同), 2 条 reject_short。"""
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(User(id=user_id, email="tech-perf@test.com", role="admin",
                         password_hash=hash_password("pass")))
        for i in range(10):
            conv_id = uuid.uuid4()
            session.add(Conversation(id=conv_id, question=f"q{i}", channel="widget",
                                     is_answered=True, intent_tag="product"))
            session.add(Trace(conversation_id=conv_id, turn_index=0, type="rag",
                              stages={"intent": {"ms": 50}, "generate": {"ms": 100 * (i + 1)}},
                              total_ms=200 + i * 100, intent="product", config_snapshot={}))
        for i in range(2):
            conv_id = uuid.uuid4()
            session.add(Conversation(id=conv_id, question=f"off{i}", channel="widget",
                                     is_answered=False, intent_tag="off_topic"))
            session.add(Trace(conversation_id=conv_id, turn_index=0, type="reject_short",
                              stages={"intent": {"ms": 30}}, total_ms=50,
                              intent="off_topic", config_snapshot={}))
        await session.commit()
    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}
    # 清理略(测试库 session 结束 drop_all 会清)

async def test_tech_perf_returns_kpi(tech_perf_seed):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/admin/tech/performance?range=7d", headers=tech_perf_seed)
    assert resp.status_code == 200
    j = resp.json()
    assert j["kpi"]["p95_ms"] > 0
    # 失败 ⊂ retry ⊂ 异常 包含关系
    assert j["kpi"]["fail_rate"] <= j["kpi"]["retry_rate"] <= j["kpi"]["anomaly_rate"]

async def test_tech_perf_stage_percentiles(tech_perf_seed):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/admin/tech/performance?range=7d", headers=tech_perf_seed)
    stages = resp.json()["stages"]
    for s in ("intent", "retrieve", "rerank", "generate"):
        assert stages[s]["p50"] > 0
        assert stages[s]["p95"] >= stages[s]["p50"]
        assert "normal_max" in stages[s]
```

- [ ] **Step 2: 运行确认失败**

Run: `TEST_DATABASE_URL=ask_ai_test pytest tests/api/test_tech_perf.py -v`
Expected: FAIL — `/tech/performance` 端点不存在(404)

- [ ] **Step 3: 实现聚合端点**

**新建独立文件 `backend/api/admin/tech.py`**(不与 `traces.py` 的 `/conversations` prefix 混),`prefix="/tech"`,用 `request.app.state.session_factory`(不用 `Depends(get_session)`):

```python
"""技术性能聚合端点。"""
from datetime import datetime, timedelta
from typing import Annotated, Any
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import Trace

tech_router = APIRouter(prefix="/tech", tags=["技术性能"])
ViewerDep = Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))]

# 每阶段正常上限基线(超过标橙),可后续从 config 读取
NORMAL_MAX = {"intent": 500, "rewrite": 2000, "retrieve": 3000, "rerank": 2000,
              "generate": 10000, "output": 100}

@tech_router.get("/performance")
async def tech_performance(
    _: ViewerDep,
    request: Request,
    range: str = Query(default="7d"),
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
) -> dict[str, Any]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    # 解析时间范围
    days = {"today": 1, "7d": 7, "30d": 30}.get(range, 7)
    end = datetime.utcnow()
    start = end - timedelta(days=days)
    # ...从 Trace 表聚合 stages JSONB 各阶段 ms 数组,Python 算 P50/P95(手写 percentile 或用 statistics)
    # 异常定义:stages.generate.ms > NORMAL_MAX['generate'] 或 stages 含 error
    # retry:stages 含 retry_count>0
    # 失败:retry 后仍 error 且 is_answered=False
    # 趋势:按 created_at::date 分组算每日 P50/P95
    # 返回 {kpi: {p95_ms, anomaly_rate, retry_rate, fail_rate, baseline, comparison},
    #       stages: {stage: {p50, p95, normal_max}}, trends: [{date, p50, p95}],
    #       anomalies: [...], degradations: [...]}
    ...
```

`router.py` 注册:`from backend.api.admin.tech import tech_router` + `admin_router.include_router(tech_router)`。

- [ ] **Step 4: 运行测试确认通过 + Commit**

```bash
TEST_DATABASE_URL=ask_ai_test pytest tests/api/test_tech_perf.py -v
git add backend/api/admin/traces.py backend/api/admin/schemas.py tests/api/test_tech_perf.py
git commit -m "feat: 技术性能聚合 API(P50/P95/异常/retry/失败 + 阶段表 + 趋势)"
```

---

## Task 5: 业务信号 LLM 提取 pipeline

**Files:**
- New: `backend/pipeline/business_signals.py`
- New: `backend/pipeline/business_signals_runner.py`
- Modify: `backend/db/models.py` — `BusinessSignal` 模型(场景/产品需求聚类)
- Modify: `backend/main.py` — 调度
- Test: `tests/pipeline/test_business_signals.py`(新建)

**Interfaces:**
- Consumes: `Conversation`(question/answer/intent_tag)、`llm.generate`。
- Produces: `BusinessSignal` 表(`type=scene|requirement`, `label`, `count`, `period`, `sample_conversation_ids`)。

- [ ] **Step 1: 写失败测试**

```python
# tests/pipeline/test_business_signals.py
@pytest.mark.asyncio
async def test_extract_scene_signals(mock_llm):
    """LLM 给 5 条 commercial/product 对话打场景标签,pipeline 聚合成 BusinessSignal。"""
    mock_llm.generate.return_value = _scenes_payload([("工业视觉",3),("安防",2)])
    signals = await run_business_signals_extraction(period="7d")
    scenes = [s for s in signals if s.type=="scene"]
    assert any(s.label=="工业视觉" and s.count==3 for s in scenes)

@pytest.mark.asyncio
async def test_extract_product_requirements(mock_llm):
    """产品需求(4K录制/开放API/低功耗)提取并计数。"""
    mock_llm.generate.return_value = _reqs_payload([("4K 录制",3),("开放 API",2)])
    signals = await run_business_signals_extraction(period="7d")
    reqs = [s for s in signals if s.type=="requirement"]
    assert len(reqs) == 2
```

- [ ] **Step 2: 运行确认失败**

Run: `TEST_DATABASE_URL=ask_ai_test pytest tests/pipeline/test_business_signals.py -v`

- [ ] **Step 3: 实现 BusinessSignal 模型**

`models.py` 加:

```python
class BusinessSignal(Base):
    """业务信号聚类(场景应用/产品需求),LLM 后处理批跑产出。"""
    __tablename__ = "business_signals"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # scene | requirement
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pct: Mapped[float] = mapped_column(Float, default=0.0)  # 占比
    sample_conversation_ids: Mapped[list[Any]] = mapped_column(JSONB, default=[])
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 4: 实现提取 pipeline**

`business_signals.py`:
- 取近 N 天 commercial+product intent 的 conversation question+answer。
- 批量喂 LLM,prompt 要求输出 JSON:`[{"type":"scene|requirement","label":"...","conv_ids":[...]}]`。
- 聚合同 label 计数 + 占比,落 `BusinessSignal` 表(覆盖同 period 旧记录)。
- `business_signals_runner.py`:提供 `run_business_signals_extraction(period)` 供 main.py lifespan 调度(每日)和手动触发。

- [ ] **Step 5: main.py 调度(可选,保守接入)**

**当前 lifespan 无后台调度任务**。如果接入,用 `asyncio.create_task` + try/except guard,不阻塞启动。**更安全的做法**:只提供手动入口(scripts/ 或 admin 端点),不接 lifespan 自动调度——避免启动失败。先不接 lifespan,手动跑 `python -c "import asyncio; from backend.pipeline.business_signals_runner import run; asyncio.run(run('7d'))"` 验证。

- [ ] **Step 6: 运行测试 + Commit**

```bash
TEST_DATABASE_URL=ask_ai_test pytest tests/pipeline/test_business_signals.py -v
git add backend/pipeline/business_signals.py backend/pipeline/business_signals_runner.py backend/db/models.py tests/pipeline/test_business_signals.py
git commit -m "feat: 业务信号 LLM 提取 pipeline(场景应用/产品需求批跑)"
```

---

## Task 6: 业务概览聚合 API

**Files:**
- **New: `backend/api/admin/business.py`** — 新建 router prefix=`/business`(**不要**加到 analytics.py,因 analytics router prefix=`/analytics`,路径不匹配)
- Modify: `backend/api/admin/router.py` — 注册 business_router
- Test: `tests/api/test_analytics_business.py`(新建)

**Interfaces:**
- Consumes: `Conversation`(intent_tag/feedback)、`QuestionCluster`(top_questions)、`BusinessSignal`(Task 5)。
- Produces: `GET /api/admin/business/overview?range=7d` 返回:服务总览(总量/三意图分布/北极星/满意度)、销售线索(有效/潜在/热门产品)、场景应用、产品需求、热门问题、地域分布(空+pending 标注)、时间序列。

- [ ] **Step 1: 写失败测试**

**测试模式参照 Task 3/4**(seed + ASGITransport)。`geo` 字段无数据源 → 断言结构存在即可,不断言 `len > 0`。

```python
# tests/api/test_analytics_business.py
import uuid, pytest, pytest_asyncio
from httpx import ASGITransport, AsyncClient
from backend.auth.jwt import create_access_token, hash_password
from backend.db.models import Conversation, User
from backend.main import app

pytestmark = pytest.mark.asyncio(loop_scope="session")

@pytest_asyncio.fixture(loop_scope="session")
async def business_seed():
    factory = app.state.session_factory
    user_id = uuid.uuid4()
    async with factory() as session:
        session.add(User(id=user_id, email="biz@test.com", role="admin",
                         password_hash=hash_password("pass")))
        for intent in ("commercial", "product", "support"):
            session.add(Conversation(question=f"q_{intent}", channel="widget",
                                     is_answered=True, intent_tag=intent))
        await session.commit()
    token = create_access_token(str(user_id), "admin", app.state.settings.jwt_secret)
    yield {"Authorization": f"Bearer {token}"}

async def test_business_overview(business_seed):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/admin/business/overview?range=7d", headers=business_seed)
    assert resp.status_code == 200
    j = resp.json()
    assert j["service"]["total"] > 0
    assert len(j["service"]["intent_dist"]) == 3
    assert j["service"]["north_star"] >= 0
    # geo 无数据源,返回空数组或 {pending: true}
    assert "geo" in j

async def test_business_overview_custom_range(business_seed):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/admin/business/overview?from=2026-08-01&to=2026-08-05",
                                headers=business_seed)
    assert resp.status_code == 200
```

- [ ] **Step 2: 运行确认失败 → Step 3: 实现端点 → Step 4: 通过 → Step 5: Commit**

新建 `backend/api/admin/business.py`,prefix=`/business`,ViewerDep,`request.app.state.session_factory`:

```python
"""业务概览聚合端点。"""
from datetime import datetime, timedelta
from typing import Annotated, Any
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import BusinessSignal, Conversation, QuestionCluster

router = APIRouter(prefix="/business", tags=["业务概览"])
ViewerDep = Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))]

@router.get("/overview")
async def business_overview(
    _: ViewerDep, request: Request,
    range: str = Query(default="7d"),
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
) -> dict[str, Any]:
    factory = request.app.state.session_factory
    days = {"today": 1, "7d": 7, "30d": 30}.get(range, 7)
    end = datetime.utcnow(); start = end - timedelta(days=days)
    # ... 聚合 Conversation/BusinessSignal/QuestionCluster
    # geo 无数据源 → return {"geo": [], "geo_note": "地域字段待接入"}
    # north_star = intent_tag='commercial' 且 is_answered 的计数(占位,购买信号待业务方确认)
    ...
```

`router.py` 注册:`from backend.api.admin.business import router as business_router` + `admin_router.include_router(business_router)`。

```bash
git add backend/api/admin/business.py backend/api/admin/router.py tests/api/test_analytics_business.py
git commit -m "feat: 业务概览聚合 API(服务总览/线索/场景/需求/地域)"
```

---

## Task 7: 前端设计 token + 共享组件

**Files:**
- Modify: `admin/src/index.css`(加 `:root` token)
- New: `admin/src/components/observability/KpiCard.tsx`
- New: `admin/src/components/observability/StageBar.tsx`(迷你阶段耗时条)
- New: `admin/src/components/observability/TrendChart.tsx`(P50/P95 双段柱)
- New: `admin/src/components/observability/TimeFilter.tsx`(今天/7d/30d/自定义日历)
- New: `admin/src/components/observability/TraceLanes.tsx`(5 泳道)
- Test: `admin/tests/observability/KpiCard.test.tsx` 等

**Interfaces:**
- Produces: 上述组件,三页共用,props 见原型 HTML 行为。

- [ ] **Step 1: index.css 注入设计 token**

`admin/src/index.css` 加(确保不与现有 Tailwind 主题冲突,用 CSS 变量):

```css
:root {
  --bg: #fafafa; --panel: #fff; --bd: #ececec; --bd2: #f0f0f0;
  --t1: #111827; --t2: #6b7280; --t3: #9ca3af;
  --acc: #4f46e5; --acc-t: #eef2ff;
  --warn: #b45309; --err: #dc2626; --ok: #059669;
  --mono: ui-monospace, "SF Mono", Menlo, monospace;
}
```

- [ ] **Step 2: 写 KpiCard 测试(失败)**

```tsx
// admin/tests/observability/KpiCard.test.tsx
import { render, screen } from "@testing-library/react";
import KpiCard from "@/components/observability/KpiCard";

test("renders label, value, delta and baseline chip", () => {
  render(<KpiCard label="P95 耗时" value={1200} unit="ms"
    delta={{ value: -8, dir: "down" }} baseline="基线 1000ms" />);
  expect(screen.getByText("P95 耗时")).toBeInTheDocument();
  expect(screen.getByText("1,200")).toBeInTheDocument();
  expect(screen.getByText(/-8%/)).toBeInTheDocument();
  expect(screen.getByText(/基线/)).toBeInTheDocument();
});

test("anomaly class applies warn color when value over baseline", () => {
  render(<KpiCard label="异常率" value={12} unit="%" alarm />);
  expect(screen.getByText("12%").closest("[data-alarm]")).toHaveAttribute("data-alarm", "true");
});
```

Run: `cd admin && npm test -- KpiCard` → FAIL(组件未定义)

- [ ] **Step 3: 实现 KpiCard**

```tsx
// admin/src/components/observability/KpiCard.tsx
type Props = {
  label: string; value: number; unit?: string;
  delta?: { value: number; dir: "up" | "down" };
  baseline?: string; alarm?: boolean;
};
export default function KpiCard({ label, value, unit = "", delta, baseline, alarm }: Props) {
  const fmt = value.toLocaleString();
  return (
    <div className="rounded-lg border p-4 bg-[var(--panel)]" data-alarm={alarm ?? false}>
      <div className="text-[13px] text-[var(--t2)]">{label}</div>
      <div className="text-2xl font-semibold mt-1 text-[var(--t1)]">
        {fmt}{unit}
      </div>
      {delta && (
        <div className={"text-[12px] mt-1 " + (delta.dir === "down" ? "text-[var(--ok)]" : "text-[var(--err)]")}>
          {delta.value > 0 ? "+" : ""}{delta.value}%
        </div>
      )}
      {baseline && <div className="text-[12px] text-[var(--t3)] mt-1">{baseline}</div>}
    </div>
  );
}
```

Run: `cd admin && npm test -- KpiCard` → PASS

- [ ] **Step 4: 写 StageBar 测试 + 实现**

```tsx
// admin/tests/observability/StageBar.test.tsx
import { render, screen } from "@testing-library/react";
import StageBar from "@/components/observability/StageBar";

test("renders 5 stage segments with proportional widths and ms labels", () => {
  render(<StageBar stages={[
    { key: "intent", ms: 50 }, { key: "rewrite", ms: 80 },
    { key: "retrieve", ms: 200 }, { key: "rerank", ms: 120 },
    { key: "generate", ms: 550 },
  ]} />);
  expect(screen.getByText("intent")).toBeInTheDocument();
  expect(screen.getByText("550ms")).toBeInTheDocument(); // generate 标 ms
});

test("over-baseline stage gets warn class", () => {
  render(<StageBar stages={[{ key: "generate", ms: 3000, over: true }]} />);
  expect(screen.getByText("generate").closest("[data-over]")).toHaveAttribute("data-over", "true");
});
```

```tsx
// admin/src/components/observability/StageBar.tsx
type Stage = { key: string; ms: number; over?: boolean };
export default function StageBar({ stages }: { stages: Stage[] }) {
  const total = stages.reduce((s, x) => s + x.ms, 0) || 1;
  return (
    <div className="flex h-5 rounded overflow-hidden border" >
      {stages.map(st => (
        <div key={st.key} style={{ width: `${(st.ms / total) * 100}%` }}
             data-over={st.over ?? false}
             className={"flex items-center justify-center text-[11px] " +
               (st.over ? "bg-[var(--warn)]/15 text-[var(--warn)]" : "bg-[var(--acc-t)] text-[var(--acc)]")}>
          <span>{st.key}</span><span className="ml-1">{st.ms}ms</span>
        </div>
      ))}
    </div>
  );
}
```

Run: `cd admin && npm test -- StageBar` → PASS

- [ ] **Step 5: 写 TrendChart 测试 + 实现(P50/P95 双段柱)**

```tsx
// admin/tests/observability/TrendChart.test.tsx
import { render, screen } from "@testing-library/react";
import TrendChart from "@/components/observability/TrendChart";

test("renders 7 day bars each with p95 full + p50 bottom segment", () => {
  render(<TrendChart data={[
    { date: "08-04", p50: 400, p95: 1200 },
    { date: "08-05", p50: 350, p95: 900 },
  ]} />);
  expect(screen.getByText("08-04")).toBeInTheDocument();
  // 每柱有两个段(用 data-seg 标识)
  const bars = document.querySelectorAll("[data-bar]");
  expect(bars.length).toBe(2);
  bars.forEach(b => {
    expect(b.querySelectorAll("[data-seg='p95']").length).toBe(1);
    expect(b.querySelectorAll("[data-seg='p50']").length).toBe(1);
  });
});

test("renders baseline dashed line marker", () => {
  render(<TrendChart data={[{ date: "08-04", p50: 400, p95: 1200 }]} baseline={1000} />);
  expect(screen.getByText(/基线/)).toBeInTheDocument();
});
```

```tsx
// admin/src/components/observability/TrendChart.tsx
type Day = { date: string; p50: number; p95: number };
export default function TrendChart({ data, baseline }: { data: Day[]; baseline?: number }) {
  const max = Math.max(...data.map(d => d.p95), baseline ?? 0) || 1;
  return (
    <div className="flex items-end gap-1 h-40 border-b border-[var(--bd)] pb-1">
      {data.map(d => (
        <div key={d.date} data-bar className="flex-1 flex flex-col items-center">
          <div className="w-full flex flex-col justify-end" style={{ height: "100%" }}>
            <div data-seg="p95" style={{ height: `${(d.p95 / max) * 100}%` }}
                 className="bg-[var(--acc)]/30 w-full rounded-t" />
            <div data-seg="p50" style={{ height: `${(d.p50 / max) * 100}%` }}
                 className="bg-[var(--acc)] w-full" />
          </div>
          <span className="text-[10px] text-[var(--t3)] mt-1">{d.date}</span>
        </div>
      ))}
      {baseline && (
        <div className="text-[10px] text-[var(--t3)]">基线 {baseline}ms(虚线)</div>
      )}
    </div>
  );
}
```

Run: `cd admin && npm test -- TrendChart` → PASS

- [ ] **Step 6: 写 TimeFilter 测试 + 实现(今天/7d/30d/自定义日历)**

```tsx
// admin/tests/observability/TimeFilter.test.tsx
import { render, screen, fireEvent } from "@testing-library/react";
import TimeFilter from "@/components/observability/TimeFilter";

test("renders 今天 / 近7天 / 30天 quick buttons and calls onChange with range", () => {
  const onChange = vi.fn();
  render(<TimeFilter onChange={onChange} />);
  fireEvent.click(screen.getByText("近 7 天"));
  expect(onChange).toHaveBeenCalledWith({ range: "7d" });
});

test("custom date inputs produce from/to", () => {
  const onChange = vi.fn();
  render(<TimeFilter onChange={onChange} />);
  fireEvent.change(screen.getByLabelText("开始"), { target: { value: "2026-08-01" } });
  fireEvent.change(screen.getByLabelText("结束"), { target: { value: "2026-08-05" } });
  fireEvent.click(screen.getByText("应用"));
  expect(onChange).toHaveBeenCalledWith({ from: "2026-08-01", to: "2026-08-05" });
});
```

```tsx
// admin/src/components/observability/TimeFilter.tsx
import { useState } from "react";
type Change = { range?: string; from?: string; to?: string };
export default function TimeFilter({ onChange }: { onChange: (c: Change) => void }) {
  const [from, setFrom] = useState(""); const [to, setTo] = useState("");
  return (
    <div className="flex items-center gap-2 text-[13px]">
      {["今天", "近 7 天", "30 天"].map((label, i) => (
        <button key={label} onClick={() => onChange({ range: ["today","7d","30d"][i] })}
          className="px-2.5 py-1 rounded border border-[var(--bd)] hover:bg-[var(--acc-t)]">
          {label}
        </button>
      ))}
      <input type="date" aria-label="开始" value={from}
             onChange={e => setFrom(e.target.value)}
             className="border border-[var(--bd)] rounded px-2 py-1" />
      <input type="date" aria-label="结束" value={to}
             onChange={e => setTo(e.target.value)}
             className="border border-[var(--bd)] rounded px-2 py-1" />
      <button onClick={() => onChange({ from, to })}
        className="px-2.5 py-1 rounded bg-[var(--acc)] text-white">应用</button>
    </div>
  );
}
```

Run: `cd admin && npm test -- TimeFilter` → PASS

- [ ] **Step 7: 写 TraceLanes 测试 + 实现(5 泳道)**

```tsx
// admin/tests/observability/TraceLanes.test.tsx
import { render, screen } from "@testing-library/react";
import TraceLanes from "@/components/observability/TraceLanes";

test("renders 5 lanes with stage label, ms and status", () => {
  render(<TraceLanes stages={{
    intent: { ms: 50, status: "ok" },
    rewrite: { ms: 80, status: "ok" },
    retrieve: { ms: 200, status: "ok" },
    rerank: { ms: 120, status: "warn" },
    generate: { ms: 550, status: "ok" },
  }} />);
  expect(screen.getByText("前置")).toBeInTheDocument();
  expect(screen.getByText("路由")).toBeInTheDocument();
  expect(screen.getByText("检索")).toBeInTheDocument();
  expect(screen.getByText("生成")).toBeInTheDocument();
  expect(screen.getByText("输出")).toBeInTheDocument();
  // rerank 标 warn
  expect(screen.getByText("检索").closest("[data-status]")).toHaveAttribute("data-status", "warn");
});
```

```tsx
// admin/src/components/observability/TraceLanes.tsx
type Stages = Record<string, { ms: number; status: "ok" | "warn" | "err"; detail?: string }>;
const LANE = [
  { key: "intent+rewrite", label: "前置" },
  { key: "retrieve", label: "路由" },
  { key: "rerank", label: "检索" },
  { key: "generate", label: "生成" },
  { key: "output", label: "输出" },
];
export default function TraceLanes({ stages }: { stages: Stages }) {
  return (
    <div className="flex flex-col gap-2">
      {LANE.map(lane => {
        const s = stages[lane.key] ?? { ms: 0, status: "ok" };
        const color = s.status === "ok" ? "var(--ok)" : s.status === "warn" ? "var(--warn)" : "var(--err)";
        return (
          <div key={lane.key} data-status={s.status}
               className="flex items-center gap-3 text-[13px] border border-[var(--bd)] rounded px-3 py-2">
            <span className="w-12 text-[var(--t2)]">{lane.label}</span>
            <span style={{ color }}>{s.ms}ms</span>
            {s.detail && <span className="text-[12px] text-[var(--t3)]">{s.detail}</span>}
          </div>
        );
      })}
    </div>
  );
}
```

Run: `cd admin && npm test -- TraceLanes` → PASS

- [ ] **Step 8: 回归全部共享组件测试 + Commit**

Run: `cd admin && npm test -- observability` → 全 PASS

```bash
git add admin/src/components/observability/ admin/src/index.css admin/tests/observability/
git commit -m "feat: 可观测性共享组件(KpiCard/StageBar/TrendChart/TimeFilter/TraceLanes)+ 设计 token"
```

---

## Task 8: 业务概览页前端

**Files:**
- New: `admin/src/pages/BusinessOverview.tsx`
- New: `admin/src/lib/api/businessOverview.ts`
- Modify: `admin/src/App.tsx`(`/` 改为 `<BusinessOverview />`,不再重定向)
- Modify: `admin/src/components/Sidebar.tsx`(分运营组/配置组,"概览"→"业务概览")
- Test: `admin/tests/BusinessOverview.test.tsx`

**Interfaces:**
- Consumes: `GET /api/admin/business/overview?range=`(Task 6)、共享组件(Task 7)。
- Produces: 业务概览页(对照 `overview-real-v1.html` 原型:服务总览 + 三意图列 + 销售线索/产品需求/场景应用 + 热门问题 + 地域 + 时间筛选 + 下钻到对话审查)。

- [ ] **Step 1: 写失败测试 — 渲染 + 数据加载**

```tsx
// admin/tests/BusinessOverview.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import { BrowserRouter } from "react-router-dom";
import BusinessOverview from "@/pages/BusinessOverview";

test("renders service overview with total and intent dist", async () => {
  render(<BrowserRouter><BusinessOverview /></BrowserRouter>);
  await waitFor(() => {
    expect(screen.getByText(/总服务客户/)).toBeInTheDocument();
    expect(screen.getByText(/销售咨询/)).toBeInTheDocument();
    expect(screen.getByText(/有效线索/)).toBeInTheDocument();
  });
});

test("drill-down link navigates to conversations with filter", async () => {
  render(<BrowserRouter><BusinessOverview /></BrowserRouter>);
  const link = await screen.findByText(/查看销售对话/);
  expect(link.closest("a")).toHaveAttribute("href", expect.stringContaining("/conversations?intent=commercial"));
});
```

- [ ] **Step 2-5: 实现 → 通过 → 回归 → Commit**

API 客户端 `businessOverview.ts` 封装 fetch;`BusinessOverview.tsx` 按原型结构用共享组件渲染;时间筛选切换重新 fetch;下钻链接带 intent 参数到 `/conversations`。

```bash
git add admin/src/pages/BusinessOverview.tsx admin/src/lib/api/businessOverview.ts admin/src/App.tsx admin/src/components/Sidebar.tsx admin/tests/BusinessOverview.test.tsx
git commit -m "feat: 业务概览页前端(服务总览/线索/场景/需求/地域/时间筛选/下钻)"
```

---

## Task 9: 对话审查页前端(重写)

**Files:**
- Modify: `admin/src/pages/Conversations.tsx`(重写,从 270 行的简单列表改为 master-detail + trace)
- New: `admin/src/lib/api/traces.ts`
- Modify: `backend/api/admin/conversations.py`(list 端点补 trace 摘要字段)
- Test: `admin/tests/ConversationsReview.test.tsx`

**Interfaces:**
- Consumes: `GET /api/admin/conversations`(补 trace 摘要)、`GET /api/admin/conversations/{id}/traces`(Task 3)、共享组件(Task 7)。
- Produces: 对话审查页(对照 `conversation-review-v1.html`:筛选栏 + 列表摘要 + 详情对话内容 + trace 5 泳道 + 多轮切换 + 联系信息卡)。

- [ ] **Step 1: 写失败测试**

> **CRITICAL(Analysis Gate delta,覆盖下方 msw 代码片段)**:
> - **前端未装 msw**。下方测试代码用 `import { http, HttpResponse } from "msw"` **不可直接使用**。改用 `vi.mock` mock API 客户端模块(`@/lib/api/traces`)或 `vi.stubGlobal("fetch", vi.fn())`。
> - **Conversation 无 `is_lead` / `contact` 字段**。contact info card 测试去掉或降级为"commercial 对话显示联系销售提示文案"。
> - **conversations list 返回 `{items, total, page, size}` 信封**(非裸 list)。mock 需匹配。
> - **`confidence` 字段不存在**于 trace/conversation(IntentResult 无 confidence)。列表不显示 confidence,或显示 trace 的 intent reason。

```tsx
// admin/tests/ConversationsReview.test.tsx
// 用 vi.mock 模式(替代 msw):
import { vi } from "vitest";
const mockFetchConversations = vi.fn();
const mockFetchTraces = vi.fn();
vi.mock("@/lib/api/conversations", () => ({ fetchConversations: mockFetchConversations }));
vi.mock("@/lib/api/traces", () => ({ fetchTraces: mockFetchTraces }));
// 或 mock hooks 层:vi.mock("@/hooks/useConversations", ...)

import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Conversations from "@/pages/Conversations";

beforeEach(() => {
  mockFetchConversations.mockResolvedValue({
    items: [{ id: "c1", question: "NE503 价格", intent_tag: "commercial",
      is_answered: true, response_time_ms: 1000, channel: "widget",
      created_at: "2026-08-10T10:00:00Z",
      trace_summary: { stages: { intent:{ms:50}, rewrite:{ms:80},
        retrieve:{ms:200}, rerank:{ms:120}, generate:{ms:550} } } }],
    total: 1, page: 1, size: 20,
  });
  mockFetchTraces.mockResolvedValue([
    { id: "t1", conversation_id: "c1", turn_index: 0, type: "rag",
      stages: { intent:{ms:50}, rewrite:{ms:80}, retrieve:{ms:200},
        rerank:{ms:120}, generate:{ms:550}, output:{ms:5} },
      total_ms: 1000 },
  ]);
});

it("list shows question, intent tag, mini-bar, total time", async () => {
  render(<MemoryRouter><Conversations /></MemoryRouter>);
  await waitFor(() => {
    expect(screen.getByText("NE503 价格")).toBeInTheDocument();
    expect(screen.getByText(/commercial|商务/)).toBeInTheDocument();
    expect(screen.getByText(/1,?000/)).toBeInTheDocument();
    expect(document.querySelectorAll("[data-bar-seg]").length).toBeGreaterThan(0);
  });
});

it("click row expands trace 5 lanes", async () => {
  render(<MemoryRouter><Conversations /></MemoryRouter>);
  const row = await screen.findByText("NE503 价格");
  fireEvent.click(row);
  await waitFor(() => {
    expect(screen.getByText("前置")).toBeInTheDocument();
    expect(screen.getByText("输出")).toBeInTheDocument();
  });
});

// contact info card 测试:Conversation 无 is_lead/contact 字段 → 去掉此测试
```

```bash
git add admin/src/pages/Conversations.tsx admin/src/lib/api/traces.ts backend/api/admin/conversations.py admin/tests/ConversationsReview.test.tsx
git commit -m "feat: 对话审查页重写(列表摘要+trace 5 泳道+多轮+联系信息)"
```

---

## Task 10: 技术洞察页前端(重写)

**Files:**
- Modify: `admin/src/pages/Analytics.tsx`(重写为技术洞察,双 tab)
- New: `admin/src/lib/api/techInsight.ts`
- Modify: `admin/src/components/Sidebar.tsx`(并入运营组,"分析仪表盘"→"技术洞察")
- Test: `admin/tests/TechInsight.test.tsx`

**Interfaces:**
- Consumes: `GET /api/admin/tech/performance`(Task 4)、现有 `/api/admin/coverage-gaps`、`/api/admin/top-questions`、共享组件。
- Produces: 技术洞察页(对照 `tech-insight-v1.html`:KPI 4 卡 + 技术性能 tab(P50/P95 趋势 + 阶段表 + 异常分布 + 降级链路)+ 知识缺口 tab(覆盖缺口 + 来源归因 + 澄清漏斗 + 缺口趋势))。

- [ ] **Step 1: 写失败测试**

> **CRITICAL(Analysis Gate delta,覆盖下方 msw 代码片段)**:
> - **前端未装 msw**。用 `vi.mock` mock `@/lib/api/techInsight`。
> - **`coverage-gaps` 真实返回 `{items, total, page, size}` 信封**(非裸 list),真实路径是 `/api/admin/analytics/coverage-gaps`(prefix=`/analytics`)。
> - **澄清漏斗**:当前无 clarify trace → API 返回空结构,前端标"暂无数据"。

```tsx
// admin/tests/TechInsight.test.tsx
import { vi } from "vitest";
const mockTechPerf = vi.fn();
const mockCoverageGaps = vi.fn();
vi.mock("@/lib/api/techInsight", () => ({
  fetchTechPerformance: mockTechPerf,
  fetchCoverageGaps: mockCoverageGaps,
}));

import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Analytics from "@/pages/Analytics";

beforeEach(() => {
  mockTechPerf.mockResolvedValue({
    kpi: { p95_ms: 1200, anomaly_rate: 0.1, retry_rate: 0.05, fail_rate: 0.02 },
    stages: { intent: { p50: 50, p95: 80, normal_max: 100 },
              generate: { p50: 3000, p95: 5000, normal_max: 2000 } },
    trends: Array.from({ length: 7 }, (_, i) => ({ date: `08-0${i+1}`, p50: 300, p95: 1000 })),
    anomalies: [], degradations: [],
  });
  mockCoverageGaps.mockResolvedValue({
    items: [{ id: "g1", cluster_type: "gap", representative_question: "如何接入 SDK",
      question_count: 5, status: "open" }],
    total: 1, page: 1, size: 20,
  });
});

it("KPI cards show P95, anomaly, retry, fail rates", async () => {
  render(<MemoryRouter><Analytics /></MemoryRouter>);
  await waitFor(() => {
    expect(screen.getByText(/P95/)).toBeInTheDocument();
    expect(screen.getByText(/1,?200/)).toBeInTheDocument();
    expect(screen.getByText(/异常率/)).toBeInTheDocument();
    expect(screen.getByText(/重试|retry/i)).toBeInTheDocument();
    expect(screen.getByText(/失败率/)).toBeInTheDocument();
  });
});

it("P50/P95 trend chart renders 7 bars with double segments", async () => {
  render(<MemoryRouter><Analytics /></MemoryRouter>);
  await waitFor(() => {
    const bars = document.querySelectorAll("[data-bar]");
    expect(bars.length).toBe(7);
    bars.forEach(b => {
      expect(b.querySelectorAll("[data-seg='p95']").length).toBe(1);
      expect(b.querySelectorAll("[data-seg='p50']").length).toBe(1);
    });
  });
});

it("stage table highlights over-baseline (data-over=true)", async () => {
  render(<MemoryRouter><Analytics /></MemoryRouter>);
  await waitFor(() => {
    expect(screen.getByText("generate").closest("[data-over]")).toHaveAttribute("data-over", "true");
    expect(screen.getByText("intent").closest("[data-over]")).toHaveAttribute("data-over", "false");
  });
});

it("switching to 知识缺口 tab shows gap clusters", async () => {
  render(<MemoryRouter><Analytics /></MemoryRouter>);
  fireEvent.click(await screen.findByText("知识缺口"));
  await waitFor(() => {
    expect(screen.getByText("如何接入 SDK")).toBeInTheDocument();
  });
});

it("澄清漏斗 shows pending when no clarify data", async () => {
  mockCoverageGaps.mockResolvedValue({ funnel: { asked: 0, clarified: 0, unresolved: 0 }, pending: true });
  render(<MemoryRouter><Analytics /></MemoryRouter>);
  fireEvent.click(await screen.findByText("知识缺口"));
  await waitFor(() => {
    expect(screen.getByText(/澄清漏斗/)).toBeInTheDocument();
    expect(screen.getByText(/暂无数据|待接入/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2-5: 重写 → 通过 → Commit**

后端需补:
- `coverage-gaps` 端点(现有)扩返或新增 `/api/admin/clarify-funnel` 聚合 `traces` 表 `type='clarify'` 的 trace(问清楚数 / 澄清后命中数 / 尾部未命中数)。
- `tech/performance` 的 `stages` 每阶段带 `normal_max`,前端据此标橙。

```bash
git add admin/src/pages/Analytics.tsx admin/src/lib/api/techInsight.ts admin/src/components/Sidebar.tsx admin/tests/TechInsight.test.tsx
git commit -m "feat: 技术洞察页重写(技术性能+知识缺口双 tab,主信号→因果分层)"
```

---

## Task 11: 真实运行验证(Real-Run Gate)

**Files:** 无新文件,验证现有系统。

- [ ] **Step 1: 本地后端启动 + 建表**

Run: `python -m backend.main`(确认 `traces`/`business_signals` 表建出,`init_db` 无报错)

- [ ] **Step 2: 真实 `/ask` 调用落 trace**

用 curl 或 widget 真实问"NE503 价格",查 `traces` 表有 1 行,type=rag,stages JSONB 有 5 阶段 ms。问"今天天气" → type=reject_short。

- [ ] **Step 3: 业务信号 pipeline 手动跑一次**

Run: `python -c "import asyncio; from backend.pipeline.business_signals_runner import run; asyncio.run(run('7d'))"` → 查 `business_signals` 表有 scene/requirement 行。

- [ ] **Step 4: 前端 build + 三页真实访问**

Run: `cd admin && npm run build` → serve dist → 浏览器开 `/`(业务概览)、`/conversations`(对话审查,点开看 trace 5 泳道)、`/analytics`(技术洞察,切 tab)。

- [ ] **Step 5: 读真实输出核对**

三页都加载真实数据(非 mock),trace 5 泳道显示真实阶段耗时,技术性能 P50/P95 显示真实聚合值。

- [ ] **Step 6: 回归现有 admin 测试**

Run: `cd admin && npm test` + `TEST_DATABASE_URL=ask_ai_test pytest tests/ -v`
Expected: 全 PASS,无回归

- [ ] **Step 7: Commit checkpoint**

```bash
git add -A
git commit -m "test: 对话可观测体系真实运行验证通过"
```

---

## Task 12(可选): 部署到 tesla-t4

> 仅当用户要求部署时执行。遵守 tesla-t4 约束(不停止生产 GPU 服务、EMBEDDER_BATCH_SIZE≤16)。

- [ ] 同步代码到 tesla-t4:`ask-ai-git pull 最新 main`
- [ ] 本地 `npm run build` 重建 dist → 同步到 tesla-t4
- [ ] 重启 ask-ai 容器(不动 locate-anything/llama-server/neomind)
- [ ] 浏览器验证三页

## Self-Review

- **Spec 覆盖**:业务概览(Task 6+8,含热门问题)、对话审查(Task 3+9)、技术洞察(Task 4+10,含澄清漏斗)、trace 数据层(Task 1-3)、LLM 提取 pipeline(Task 5)全覆盖。trace 数据层 spec 的 5 字段全在 Task 1。sidebar 两组结构(运营组/配置组)在 Task 8/10 + 文件结构体现。北极星占位实现(spec 开放问题#4 待业务方确认)。
- **Placeholder 扫描**:Task 7 5 个共享组件各带真实测试 + 实现 + commit;Task 9/10 测试带 msw mock + 真实断言;无 `{...}`/TBD/TODO。Task 2 clarify 分支给了条件实现 + 降级说明。
- **类型一致性**:`RAGAnswer.trace_payload`(Task 2)→ `/ask` 落库(Task 3,引用已修正为 Task 3 非 Task 16)→ 聚合 API(Task 4,独立 `tech_router` prefix `/tech`,与 `/conversations` router 分离)→ 前端 traces API(Task 9)字段链一致;`BusinessSignal`(Task 5)→ 业务概览 API(Task 6)→ 前端(Task 8)一致;clarify trace type(Task 2)→ 漏斗聚合(Task 10)一致。
- **真实运行**:Task 11 Real-Run Gate 覆盖建表/真实 ask 落 trace/pipeline/前端三页/回归。

### 本轮自审修复记录(对照 spec + writing-plans No-Placeholders)

| # | 级别 | 问题 | 修复 |
|---|---|---|---|
| 1 | CRITICAL | Task 2 Produces 引用"Task 16"落库,无 Task 16 | 改为"Task 3" |
| 2 | CRITICAL | Task 4 `/tech/performance` 挂在 `/conversations` router 上,路径变 `/conversations/tech/performance` | 拆独立 `tech_router` prefix `/tech`,router.py 双注册 |
| 3 | HIGH | Task 7 整 task 描述性,无真实测试/实现 | 5 组件各给完整 TDD step + 测试代码 + 实现骨架 |
| 4 | HIGH | Task 9/10 测试 `{...}` 占位 | 补 msw mock + 真实断言(列表/点开 trace/多轮/联系信息/KPI/趋势柱/超基线标橙/tab 切换/漏斗) |
| 5 | MEDIUM | 热门问题归业务概览,Task 6 Produces 漏 | 补进 Produces + 聚合步骤(复用 top-questions) |
| 6 | MEDIUM | sidebar 两组结构 spec 要,plan 只改名 | Task 8/10 + 文件结构改为"运营组/配置组"分组 |
| 7 | MEDIUM | 澄清漏斗数据源(type=clarify trace)无来源 | Task 2 加 clarify 分支插桩 + 条件降级说明;Task 10 漏斗测试对应 |

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-08-10-conversation-observability.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**

---

## Analysis Gate Delta（实施前以真实代码为准，2026-08-10 核对）

以下 delta 是对照真实代码逐文件核对得出的，实施时**必须以此修正计划代码片段**：

1. **`IntentResult` 无 `confidence` 字段**（`backend/pipeline/intent.py`，只有 `category` + `reason`）。trace_payload 的 `confidence` 用 `None`（不伪造），或后续给 IntentResult 加字段。Task 2 测试不应断言 confidence 具体值。
2. **`LLMResponse` 无 `ttft_ms` / `token_count`**（`backend/llm/base.py`，字段为 `content/model/tokens_input/tokens_output/latency_ms`）。generate 阶段记 `latency_ms` + `tokens_output`，用 `getattr` 兜底。
3. **`stream_answer()` 已有 per-stage timing**：`complete` 事件已带 `timing = {rewrite_ms, search_ms, rerank_ms, first_token_ms, llm_ms}`。Task 2 插桩应**复用**这些已有计时，重组成 `stages` 格式（intent/rewrite/retrieve/rerank/generate/output），而非重写计时逻辑。`answer()` 无 per-stage 计时，需补。
4. **`/ask` 是 SSE-only**，只调 `stream_answer()`，不调 `answer()`。trace 落库发生在 `event_generator()` 拿到 `complete` 事件后（已有 `intent`/`elapsed`/`timing`），与 conversation 写入同段。`answer()` 方法的 trace_payload 仅供测试/其他调用方，`/ask` 走 stream 路径。
5. **`Conversation` 无 `contact` / `is_lead` / 地域字段**（`backend/db/models.py`）。联系信息卡 + 地域分布返回空/`{pending: true}`，不伪造。
6. **admin 端点用 `request.app.state.session_factory`**，**无 `get_session` 依赖**。Task 3/4 的 `Depends(get_session)` 改为 `request: Request` + `factory = request.app.state.session_factory`（照 `conversations.py` 模式）。
7. **前端未装 `msw`**（`admin/package.json` 无 msw）。Task 9/10 测试用 `vi.mock` mock API 客户端模块（`@/lib/api/traces` 等）或 `vi.stubGlobal("fetch", ...)`，不引入 msw 依赖。
8. **`main.py` lifespan 无后台调度任务**。Task 5 接入 business_signals 调度用 `asyncio.create_task` + try/except guard，不阻塞启动；或仅提供手动入口不接 lifespan（更安全）。
9. **`analytics` router prefix=`/analytics`**。`/business/overview` 路径不匹配，**新建 `backend/api/admin/business.py` router prefix=`/business`**，在 `router.py` 注册。Task 4 的 `/tech` 独立 router 不变。
10. **Pydantic v2**：`TraceOut` 等用 `model_config = ConfigDict(from_attributes=True)`，不用 `class Config`。
11. **`models.py` 需补 `Float` import**（当前无）。Trace/BusinessSignal 用到。
12. **Trace 自引用关系**：`prev_trace` 用 `relationship(remote_side="Trace.id", foreign_keys=[prev_trace_id])`，去掉 `post_init=True`（验证可用性）。
13. **admin list 端点返回 `{items, total, page, size}` 信封**（非裸 list）。Task 3 的 `GET /conversations/{id}/traces` 可返回裸 list（单 conversation 的 trace 量小），但保持风格一致即可。
14. **前端 API 客户端**：`apiFetch<T>(path)` 自动拼 `/api/admin` 前缀。`businessOverview.ts` 调 `apiFetch("/business/overview?range=7d")`。
15. **Task 9 后端部分**（conversations.py list 补 trace_summary）归后端 agent，前端 agent 只动 `admin/src/`。