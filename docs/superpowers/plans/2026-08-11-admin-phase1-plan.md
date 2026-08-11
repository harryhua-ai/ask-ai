# Admin 三页设计稿对齐 Phase 1(快赢层)实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐管理后台三页(业务概览/对话审查/技术洞察)的可视化与数据维度,用现有 shadcn + 纯 Tailwind/内联 SVG 自定义组件对齐设计稿的信息密度与叙事因果,不引第三方图表库。

**Architecture:** 后端仅暴露已有数据(Trace.confidence / geo.pct / 90d / KPI.count+delta / anomaly.pct),不新增表、不改采集层。前端新建 7 个纯展示可视化组件 + 复用 2 个既有组件(StageBar/TraceLanes),放入既有 `admin/src/components/observability/`(与现有 KpiCard/StageBar/TraceLanes/TrendChart 同目录,避免与 spec 提议的 `components/viz/` 双目录碎片化)。三页分别接线,保持现有 vitest 测试套件全绿(含 1 个当前失败的澄清漏斗占位测试)。

**Tech Stack:** React 19 + TypeScript + Vite + Tailwind + shadcn/Radix + @tanstack/react-query + vitest + @testing-library/react;后端 Python 3.12 + FastAPI + SQLAlchemy async + pytest(测试库隔离 `TEST_DATABASE_URL`)。

## Global Constraints

- **语言**:对话、回复、代码注释、docstring 用中文简体。
- **可视化组件**:纯 Tailwind + 内联 SVG,**禁止**引入 recharts/chart.js/d3 等第三方图表库。
- **颜色**:用 `index.css` 已定义的 CSS 变量 `--acc`/`--acc-t`/`--warn`/`--err`/`--ok`/`--t1`/`--t2`/`--t3`/`--bd`/`--panel`,不硬编码 hex。
- **组件规范**:每个 viz 组件 < 80 行,props 驱动,无内部状态(纯展示),配 1 个 vitest 测试验证 props → DOM。
- **不可变更新**:前端用 spread 不可变更新,后端 `Settings` 用 `@dataclass(frozen=True)`(本计划不动 Settings)。
- **新组件目录**:放 `admin/src/components/observability/`(spec 提议的 `components/viz/` 经审计与既有目录冲突,改用既有目录避免碎片化——这是对 spec 的执行期调整,已记录)。
- **后端测试**:必设 `TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test`(`tests/conftest.py` 的 `drop_all` 在未隔离时会清空开发库)。
- **前端测试**:`cd admin && npx vitest run <path>` 单测,`cd admin && npx vitest run` 全量。
- **阶段映射**(列表 4 段 vs 详情 5 段,来源 spec §1.1 映射表):
  - 列表 4 段:前置(intent+rewrite)/ 检索(retrieve+rerank)/ 生成(generate)/ 输出(output)
  - 详情 5 段:前置(rewrite)/ 路由(intent)/ 检索(retrieve+rerank)/ 生成(generate)/ 输出(output)
  - "路由" lane 无独立计时段:boost 桶执行计入 retrieve.ms,Phase 1 固定 `ms: 0`(不估算),items 从 intent.category/reason + retrieve.effective_min 派生;精确 routing 计时留 Phase 2 在 rag.py 新增 `stages.routing` 采集点。
- **不做**:客户信息、来源准确率、澄清漏斗真实数据、多轮消息正文存储(Phase 3);stage_ratios、markers、prev 环比、hot-questions 端点、双色条(Phase 2)。

---

## File Structure

```
admin/src/components/observability/
├── KpiCard.tsx              # 既有,本计划不动(Phase 1.3 复用)
├── StageBar.tsx             # 既有,Task 9 复用(列表 4 段比例条)
├── TraceLanes.tsx           # 既有,Task 13 改造为横向泳道(详情 5 段)
├── TrendChart.tsx           # 既有,本计划不动
├── TimeFilter.tsx           # 既有,本计划不动
├── StackedBar.tsx           # 新建 Task 5(意图堆叠条)
├── MiniTrend.tsx            # 新建 Task 6(迷你柱图)
├── ProgressBar.tsx          # 新建 Task 7(横条进度)
├── IntentColumn.tsx         # 新建 Task 8(意图深入列,复用 MiniTrend)
├── LanesBar.tsx             # 新建 Task 10(Trace 总比例条)
├── NodeFlow.tsx             # 新建 Task 11(降级链路节点流)
└── ContainmentDiagram.tsx  # 新建 Task 12(异常⊃重试⊃失败包含图)

admin/src/components/observability/__tests__/  # 既有测试目录(admin/tests/observability/)
# 注:既有测试放在 admin/tests/observability/,本计划沿用

admin/tests/observability/
├── KpiCard.test.tsx         # 既有
├── StageBar.test.tsx        # 既有
├── TraceLanes.test.tsx      # 既有,Task 13 扩展
├── TimeFilter.test.tsx      # 既有
├── TrendChart.test.tsx      # 既有
├── StackedBar.test.tsx      # 新建 Task 5
├── MiniTrend.test.tsx       # 新建 Task 6
├── ProgressBar.test.tsx     # 新建 Task 7
├── IntentColumn.test.tsx    # 新建 Task 8
├── LanesBar.test.tsx        # 新建 Task 10
├── NodeFlow.test.tsx        # 新建 Task 11
└── ContainmentDiagram.test.tsx # 新建 Task 12

admin/src/
├── types/api.ts             # 修改 Task 2(Conversation 补 trace_summary)
├── pages/BusinessOverview.tsx # 修改 Task 15
├── pages/Conversations.tsx  # 修改 Task 14
└── pages/Analytics.tsx      # 修改 Task 16

backend/api/admin/
├── conversations.py         # 修改 Task 1(trace_map 补 confidence)
├── business.py              # 修改 Task 3(geo pct + 90d)
└── tech.py                  # 修改 Task 4(KPI count+delta + anomaly pct)
```

---

## Task 1: 后端对话审查 trace_map 补 confidence + 修复最新 trace 选择

**Files:**
- Modify: `backend/api/admin/conversations.py:70-86`(注释 + trace_q 排序 + trace_map 字典)
- Test: `tests/api/admin/test_conversations.py`

**Interfaces:**
- Consumes: `Trace.confidence`(backend/db/models.py:129,`Mapped[float | None]` 已有)、`Trace.turn_index`(L124)
- Produces: `trace_map[conversation_id]["confidence"]` 字段;trace_map 取每条对话**最新一轮**(turn_index 最大)的 trace,而非最早一轮

**Analysis Gate 发现**:conversations.py:70 注释写"每条对话最新一条 trace",但 L77 `order_by(Trace.turn_index)` 升序 + L81 `if t.conversation_id not in trace_map` 取首次出现 = 实际取**最早一轮**。与注释矛盾,且对多轮对话会显示错误轮次的 confidence/stages。本 Task 一并修复,使其与注释和产品语义一致(列表应反映对话最新状态)。

- [ ] **Step 1: 写失败测试(含多轮 trace 选择)**

在 `tests/api/admin/test_conversations.py` 末尾追加。注意 `select` 需在文件顶部 import(若已有则跳过),`Trace` 需加到 `from backend.db.models import Conversation, User`:

```python
async def test_list_conversations_trace_summary_latest_turn_and_confidence(auth_headers):
    """trace_summary 取最新一轮(turn_index 最大)的 trace,且含 confidence。"""
    from sqlalchemy import select

    from backend.db.models import Trace

    factory = app.state.session_factory
    async with factory() as session:
        conv = await session.execute(
            select(Conversation).where(Conversation.question == "test question")
        )
        conv = conv.scalar_one()
        # 先建 turn 0(低置信),再建 turn 1(高置信,应被选中)
        session.add(
            Trace(
                conversation_id=conv.id,
                turn_index=0,
                type="rag",
                stages={"intent": {"ms": 50}},
                total_ms=100,
                intent="commercial",
                confidence=0.30,
                config_snapshot={},
            )
        )
        session.add(
            Trace(
                conversation_id=conv.id,
                turn_index=1,
                type="rag",
                stages={"intent": {"ms": 60}},
                total_ms=200,
                intent="commercial",
                confidence=0.85,
                config_snapshot={},
            )
        )
        await session.commit()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/admin/conversations?q=test%20question", headers=auth_headers
        )
    items = resp.json()["items"]
    target = [c for c in items if c["question"] == "test question"][0]
    ts = target["trace_summary"]
    assert ts is not None
    # 取最新轮次(turn 1)
    assert ts["confidence"] == 0.85
    assert ts["total_ms"] == 200
    # 清理本次创建的 trace
    async with factory() as session:
        await session.execute(Trace.__table__.delete().where(Trace.conversation_id == conv.id))
        await session.commit()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test uv run pytest tests/api/admin/test_conversations.py::test_list_conversations_trace_summary_latest_turn_and_confidence -v`
Expected: FAIL(`assert 0.30 == 0.85` —— 当前代码取 turn_index=0 的 trace;或 `KeyError: 'confidence'`,取决于 trace_map 是否已含 confidence)

- [ ] **Step 3: 最小实现(改排序 + 补 confidence)**

修改 `backend/api/admin/conversations.py:70-86`。把 trace_q 的 `order_by(Trace.turn_index)` 改为 `desc()`,这样循环中"首次出现"= turn_index 最大(最新)。注释已对齐,无需改:

```python
        # 批量获取 trace 摘要(每条对话最新一条 trace 的 stages)
        conv_ids = [c.id for c in convs]
        trace_map: dict = {}
        if conv_ids:
            from sqlalchemy import desc

            trace_q = (
                select(Trace)
                .where(Trace.conversation_id.in_(conv_ids))
                .order_by(desc(Trace.turn_index))
            )
            trace_rows = (await session.execute(trace_q)).scalars().all()
            for t in trace_rows:
                if t.conversation_id not in trace_map:
                    trace_map[t.conversation_id] = {
                        "type": t.type,
                        "stages": t.stages or {},
                        "total_ms": t.total_ms,
                        "confidence": t.confidence,
                    }
```

> 注:`desc` 也可在文件顶部与既有 `select`/`func` 一起 import(`from sqlalchemy import desc, func, select`),避免函数内 import。两种风格任选,保持与文件既有 import 习惯一致。

- [ ] **Step 4: 运行测试确认通过**

Run: `TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test uv run pytest tests/api/admin/test_conversations.py -v`
Expected: PASS(含新测试 + 既有 2 个)

- [ ] **Step 5: 提交**

```bash
git add backend/api/admin/conversations.py tests/api/admin/test_conversations.py
git commit -m "fix(admin): 对话审查 trace_map 取最新轮次 + 补 confidence 字段"
```

---

## Task 2: 前端 Conversation 类型补 trace_summary

**Files:**
- Modify: `admin/src/types/api.ts:112-124`
- Test: 无独立测试(类型声明,由页面测试间接覆盖)

**Interfaces:**
- Consumes: Task 1 后端返回的 `trace_summary` 结构
- Produces: `Conversation.trace_summary?: { type: string; stages: Record<string, TraceStageData>; total_ms: number | null; confidence: number | null }`

- [ ] **Step 1: 修改类型**

在 `admin/src/types/api.ts` 的 `Conversation` 接口(L112-124)补 `trace_summary` 字段。先在文件顶部 import `TraceStageData`(从 `@/lib/api/traces`):

```typescript
import type { TraceStageData } from "@/lib/api/traces";

export interface TraceSummary {
  type: string;
  stages: Record<string, TraceStageData>;
  total_ms: number | null;
  confidence: number | null;
}

export interface Conversation {
  id: string;
  question: string;
  answer: string | null;
  channel: string;
  language: string | null;
  sources: unknown[];
  is_answered: boolean;
  feedback: string | null;
  response_time_ms: number | null;
  created_at: string;
  intent_tag: string | null;
  trace_summary?: TraceSummary | null;
}
```

- [ ] **Step 2: 运行类型检查 + 既有测试**

Run: `cd admin && npx tsc -b --noEmit && npx vitest run tests/ConversationsReview.test.tsx`
Expected: PASS(tsc 无报错,ConversationsReview 既有测试仍绿——它 mock 的 trace_summary 已含 stages)

- [ ] **Step 3: 提交**

```bash
git add admin/src/types/api.ts
git commit -m "feat(admin): Conversation 类型补 trace_summary 声明"
```

---

## Task 3: 后端业务概览补 geo pct + 90d

**Files:**
- Modify: `backend/api/admin/business.py:50`(`days` 字典)、`backend/api/admin/business.py:213-230`(geo 聚合)
- Test: `tests/api/admin/test_analytics_business.py`

**Interfaces:**
- Consumes: 无新依赖
- Produces: `geo: [{ name: str, count: int, pct: float }]`;`days` 支持 `range=90d`(90 天窗)

- [ ] **Step 1: 写失败测试**

在 `tests/api/admin/test_analytics_business.py` 末尾追加:

```python
async def test_business_overview_geo_pct_and_90d(business_seed):
    """geo 项含 pct(占比),range=90d 接受。"""
    # 补一条带 country 的对话(business_seed 创建的对话无 country)
    factory = app.state.session_factory
    async with factory() as session:
        session.add(
            Conversation(
                question="biz_test_geo",
                channel="widget",
                is_answered=True,
                intent_tag="commercial",
                country="CN",
            )
        )
        await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/admin/business/overview?range=90d", headers=business_seed
        )
    assert resp.status_code == 200
    j = resp.json()
    # 90d 窗口应包含测试数据
    assert j["service"]["total"] > 0
    # geo 每项含 pct
    for g in j["geo"]:
        assert "pct" in g
        assert 0 <= g["pct"] <= 100
    # 清理
    async with factory() as session:
        await session.execute(
            Conversation.__table__.delete().where(Conversation.question == "biz_test_geo")
        )
        await session.commit()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test uv run pytest tests/api/admin/test_analytics_business.py::test_business_overview_geo_pct_and_90d -v`
Expected: FAIL(`"pct" in g` 断言失败,geo 当前只有 name/count)

- [ ] **Step 3: 实现**

修改 `backend/api/admin/business.py:50` 的 `days` 字典加 `90d`:

```python
    days = {"today": 1, "7d": 7, "30d": 30, "90d": 90}.get(range, 7)
```

修改 `backend/api/admin/business.py:213-230` 的 geo 聚合,先算总数再算 pct:

```python
        # 地域分布(从 country 字段聚合)
        geo_q = (
            select(
                Conversation.country,
                func.count().label("cnt"),
            )
            .where(
                Conversation.created_at >= start,
                Conversation.created_at <= end,
                Conversation.country.is_not(None),
            )
            .group_by(Conversation.country)
            .order_by(func.count().desc())
            .limit(10)
        )
        geo_rows = (await session.execute(geo_q)).all()
        geo_total = sum(r.cnt for r in geo_rows) or 1
        geo = [
            {"name": row.country, "count": row.cnt, "pct": round(row.cnt / geo_total * 100, 1)}
            for row in geo_rows
            if row.country
        ]
        geo_note = "地域分布" if geo else "暂无地域数据(新对话将自动捕获)"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test uv run pytest tests/api/admin/test_analytics_business.py -v`
Expected: PASS(3 个测试含新测试)

- [ ] **Step 5: 同步前端类型**

修改 `admin/src/lib/api/businessOverview.ts` 的 `BusinessOverviewData.geo` 类型(L54):

```typescript
  geo: { name: string; count: number; pct: number }[];
```

- [ ] **Step 6: 提交**

```bash
git add backend/api/admin/business.py tests/api/admin/test_analytics_business.py admin/src/lib/api/businessOverview.ts
git commit -m "feat(admin): 业务概览 geo 补 pct + days 补 90d"
```

---

## Task 4: 后端技术洞察 KPI 补 count + delta + 异常补 pct

**Files:**
- Modify: `backend/api/admin/tech.py:225-238`(KPI 返回)、`backend/api/admin/tech.py:68-74`(prev trace 读取)、`backend/api/admin/tech.py:213-217`(anomalies)
- Test: `tests/api/admin/test_tech_perf.py`

**Interfaces:**
- Consumes: `prev_traces`(已读取 L71-74,用于 P95 环比)
- Produces: KPI 补 `anomaly_count`/`retry_count`/`fail_count`/`anomaly_delta`/`retry_delta`/`fail_delta`;`anomalies: [{ type, count, pct }]`

- [ ] **Step 1: 写失败测试**

在 `tests/api/admin/test_tech_perf.py` 末尾追加:

```python
async def test_tech_perf_kpi_count_and_delta(tech_perf_seed):
    """KPI 补 count(绝对数)+ delta(环比);anomalies 补 pct。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/api/admin/tech/performance?range=7d", headers=tech_perf_seed
        )
    j = resp.json()
    kpi = j["kpi"]
    # count 字段
    assert "anomaly_count" in kpi
    assert "retry_count" in kpi
    assert "fail_count" in kpi
    assert isinstance(kpi["anomaly_count"], int)
    # delta 字段(环比,浮点)
    assert "anomaly_delta" in kpi
    assert "retry_delta" in kpi
    assert "fail_delta" in kpi
    # anomalies 每项含 pct
    for a in j["anomalies"]:
        assert "pct" in a
        assert 0 <= a["pct"] <= 100
```

- [ ] **Step 2: 运行测试确认失败**

Run: `TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test uv run pytest tests/api/admin/test_tech_perf.py::test_tech_perf_kpi_count_and_delta -v`
Expected: FAIL(`"anomaly_count" in kpi` 断言失败)

- [ ] **Step 3: 实现 KPI count + delta**

修改 `backend/api/admin/tech.py`。先在 prev_traces 读取后(L74 之后)算 prev 的 anomaly/retry/fail count。然后在返回的 `kpi` 字典(L225-233)补字段。

在 L74 `prev_traces = prev_rows.scalars().all()` 之后,空 trace 早返回之前,插入 prev 统计函数。先定义一个复用统计函数(在 `_percentile` 函数之后,`tech_performance` 之前):

```python
def _count_flags(traces: list) -> tuple[int, int, int]:
    """统计 traces 的 anomaly/retry/fail 计数(复用主循环逻辑)。"""
    anomaly = 0
    retry = 0
    fail = 0
    for t in traces:
        stages = t.stages or {}
        is_anomaly = False
        for sname in STAGE_NAMES:
            sd = stages.get(sname)
            if isinstance(sd, dict):
                if sd.get("ms", 0) > NORMAL_MAX.get(sname, 999999):
                    is_anomaly = True
                if sd.get("error"):
                    is_anomaly = True
        if is_anomaly:
            anomaly += 1
        has_retry = any(
            isinstance(sd, dict) and (sd.get("error") or sd.get("retry_count"))
            for sd in stages.values()
        )
        if has_retry:
            retry += 1
        has_persistent = any(
            isinstance(sd, dict) and sd.get("error") and not sd.get("recovered")
            for sd in stages.values()
        )
        if has_persistent:
            fail += 1
    return anomaly, retry, fail
```

然后在主循环之后(L170 `n = len(traces)` 附近),计算 prev count + delta:

```python
    n = len(traces)
    prev_anomaly, prev_retry, prev_fail = _count_flags(prev_traces)
    prev_n = len(prev_traces) or 1

    def _delta(cur: int, cur_n: int, prev: int, prev_n: int) -> float:
        cur_rate = cur / cur_n if cur_n else 0.0
        prev_rate = prev / prev_n if prev_n else 0.0
        return round(cur_rate - prev_rate, 4)
```

修改 KPI 返回(L225-233)补字段:

```python
    return {
        "kpi": {
            "p95_ms": int(p95_total),
            "anomaly_rate": round(anomaly_count / n, 4) if n else 0.0,
            "retry_rate": round(retry_count / n, 4) if n else 0.0,
            "fail_rate": round(fail_count / n, 4) if n else 0.0,
            "anomaly_count": anomaly_count,
            "retry_count": retry_count,
            "fail_count": fail_count,
            "anomaly_delta": _delta(anomaly_count, n, prev_anomaly, prev_n),
            "retry_delta": _delta(retry_count, n, prev_retry, prev_n),
            "fail_delta": _delta(fail_count, n, prev_fail, prev_n),
            "baseline": baseline_p95,
            "comparison": comparison,
        },
```

同时修改空 trace 早返回(L82-99)的 `kpi` 也补这些字段(值为 0):

```python
    if not traces:
        return {
            "kpi": {
                "p95_ms": 0,
                "anomaly_rate": 0.0,
                "retry_rate": 0.0,
                "fail_rate": 0.0,
                "anomaly_count": 0,
                "retry_count": 0,
                "fail_count": 0,
                "anomaly_delta": 0.0,
                "retry_delta": 0.0,
                "fail_delta": 0.0,
                "baseline": 0,
                "comparison": 0.0,
            },
```

- [ ] **Step 4: 实现 anomalies pct**

修改 `backend/api/admin/tech.py:213-217` 的 anomalies 列表,加 pct(各类型占异常总数比例):

```python
    # 异常分布列表(含 pct)
    anomaly_total = sum(anomaly_type_count.values()) or 1
    anomalies = [
        {"type": atype, "count": count, "pct": round(count / anomaly_total * 100, 1)}
        for atype, count in sorted(anomaly_type_count.items(), key=lambda x: -x[1])
    ]
```

- [ ] **Step 5: 运行测试确认通过**

Run: `TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test uv run pytest tests/api/admin/test_tech_perf.py -v`
Expected: PASS(3 个测试含新测试)

- [ ] **Step 6: 同步前端类型**

修改 `admin/src/lib/api/techInsight.ts` 的 `TechKpi`(L4-11)和 `AnomalyItem`(L25-29):

```typescript
export interface TechKpi {
  p95_ms: number;
  anomaly_rate: number;
  retry_rate: number;
  fail_rate: number;
  anomaly_count: number;
  retry_count: number;
  fail_count: number;
  anomaly_delta: number;
  retry_delta: number;
  fail_delta: number;
  baseline: number;
  comparison: number;
}

export interface AnomalyItem {
  type: string;
  count: number;
  pct?: number;
  detail?: string;
}
```

- [ ] **Step 7: 提交**

```bash
git add backend/api/admin/tech.py tests/api/admin/test_tech_perf.py admin/src/lib/api/techInsight.ts
git commit -m "feat(admin): 技术洞察 KPI 补 count+delta,异常补 pct"
```

---

## Task 5: StackedBar 组件(意图堆叠条)

**Files:**
- Create: `admin/src/components/observability/StackedBar.tsx`
- Test: `admin/tests/observability/StackedBar.test.tsx`

**Interfaces:**
- Consumes: 无
- Produces: `StackedBar({ segments: { label: string; value: number; color: string }[] })` — 单行横向堆叠条 + 图例

- [ ] **Step 1: 写失败测试**

创建 `admin/tests/observability/StackedBar.test.tsx`:

```tsx
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import StackedBar from "@/components/observability/StackedBar";

afterEach(cleanup);

describe("StackedBar", () => {
  it("渲染各段及图例", () => {
    render(
      <StackedBar
        segments={[
          { label: "销售咨询", value: 30, color: "var(--acc)" },
          { label: "产品方案", value: 50, color: "var(--ok)" },
          { label: "技术支持", value: 20, color: "var(--warn)" },
        ]}
      />,
    );
    expect(screen.getByText("销售咨询")).toBeInTheDocument();
    expect(screen.getByText("产品方案")).toBeInTheDocument();
    expect(screen.getByText("技术支持")).toBeInTheDocument();
  });

  it("value 全 0 时不渲染段(避免除零)", () => {
    const { container } = render(
      <StackedBar segments={[{ label: "空", value: 0, color: "var(--acc)" }]} />,
    );
    expect(container.querySelector("[data-seg]")).toBeNull();
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd admin && npx vitest run tests/observability/StackedBar.test.tsx`
Expected: FAIL(组件不存在)

- [ ] **Step 3: 实现**

创建 `admin/src/components/observability/StackedBar.tsx`:

```tsx
type Segment = { label: string; value: number; color: string };

export default function StackedBar({ segments }: { segments: Segment[] }) {
  const total = segments.reduce((s, x) => s + x.value, 0);
  return (
    <div className="space-y-2">
      <div className="flex h-4 rounded overflow-hidden border border-[var(--bd)]">
        {total > 0 &&
          segments.map((seg) => (
            <div
              key={seg.label}
              data-seg={seg.label}
              style={{ width: `${(seg.value / total) * 100}%`, background: seg.color }}
              className="h-full"
              title={`${seg.label} ${seg.value}`}
            />
          ))}
      </div>
      <div className="flex flex-wrap gap-3 text-[12px] text-[var(--t2)]">
        {segments.map((seg) => (
          <span key={seg.label} className="flex items-center gap-1">
            <span
              className="inline-block w-2.5 h-2.5 rounded-sm"
              style={{ background: seg.color }}
            />
            {seg.label}
            <span className="text-[var(--t3)]">{seg.value}</span>
          </span>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd admin && npx vitest run tests/observability/StackedBar.test.tsx`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add admin/src/components/observability/StackedBar.tsx admin/tests/observability/StackedBar.test.tsx
git commit -m "feat(admin): 新建 StackedBar 意图堆叠条组件"
```

---

## Task 6: MiniTrend 组件(迷你柱图)

**Files:**
- Create: `admin/src/components/observability/MiniTrend.tsx`
- Test: `admin/tests/observability/MiniTrend.test.tsx`

**Interfaces:**
- Consumes: 无
- Produces: `MiniTrend({ data: number[]; color?: string })` — n 根单色柱,无坐标轴

- [ ] **Step 1: 写失败测试**

创建 `admin/tests/observability/MiniTrend.test.tsx`:

```tsx
import { describe, it, expect, afterEach } from "vitest";
import { render, cleanup } from "@testing-library/react";
import MiniTrend from "@/components/observability/MiniTrend";

afterEach(cleanup);

describe("MiniTrend", () => {
  it("渲染 7 根柱", () => {
    const { container } = render(<MiniTrend data={[1, 2, 3, 4, 3, 2, 1]} />);
    expect(container.querySelectorAll("[data-bar]").length).toBe(7);
  });

  it("空数据不渲染柱", () => {
    const { container } = render(<MiniTrend data={[]} />);
    expect(container.querySelectorAll("[data-bar]").length).toBe(0);
  });

  it("全 0 数据柱高为 0(minHeight 不触发)", () => {
    const { container } = render(<MiniTrend data={[0, 0, 0]} />);
    const bars = container.querySelectorAll("[data-bar]");
    bars.forEach((b) => {
      const inner = b.querySelector("[data-bar-fill]");
      expect(inner).toBeTruthy();
    });
    expect(bars.length).toBe(3);
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd admin && npx vitest run tests/observability/MiniTrend.test.tsx`
Expected: FAIL

- [ ] **Step 3: 实现**

创建 `admin/src/components/observability/MiniTrend.tsx`:

```tsx
export default function MiniTrend({
  data,
  color = "var(--acc)",
}: {
  data: number[];
  color?: string;
}) {
  const max = Math.max(...data, 1);
  return (
    <div className="flex items-end gap-0.5 h-10" data-trend>
      {data.map((v, i) => (
        <div
          key={i}
          data-bar
          className="flex-1 flex flex-col justify-end h-full"
          title={`${v}`}
        >
          <div
            data-bar-fill
            className="w-full rounded-t"
            style={{
              height: `${(v / max) * 100}%`,
              background: color,
              minHeight: v > 0 ? "2px" : "0",
            }}
          />
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd admin && npx vitest run tests/observability/MiniTrend.test.tsx`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add admin/src/components/observability/MiniTrend.tsx admin/tests/observability/MiniTrend.test.tsx
git commit -m "feat(admin): 新建 MiniTrend 迷你柱图组件"
```

---

## Task 7: ProgressBar 组件(横条进度)

**Files:**
- Create: `admin/src/components/observability/ProgressBar.tsx`
- Test: `admin/tests/observability/ProgressBar.test.tsx`

**Interfaces:**
- Consumes: 无
- Produces: `ProgressBar({ label: string; value: number; pct: number; color?: string })` — 横条 + 百分比

- [ ] **Step 1: 写失败测试**

创建 `admin/tests/observability/ProgressBar.test.tsx`:

```tsx
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import ProgressBar from "@/components/observability/ProgressBar";

afterEach(cleanup);

describe("ProgressBar", () => {
  it("渲染标签、计数、百分比", () => {
    render(
      <ProgressBar label="中国" value={120} pct={45.5} />,
    );
    expect(screen.getByText("中国")).toBeInTheDocument();
    expect(screen.getByText("120")).toBeInTheDocument();
    expect(screen.getByText(/45\.5%/)).toBeInTheDocument();
  });

  it("填充宽度对应 pct", () => {
    const { container } = render(<ProgressBar label="美国" value={80} pct={30} />);
    const fill = container.querySelector("[data-fill]");
    expect(fill).toHaveStyle("width: 30%");
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd admin && npx vitest run tests/observability/ProgressBar.test.tsx`
Expected: FAIL

- [ ] **Step 3: 实现**

创建 `admin/src/components/observability/ProgressBar.tsx`:

```tsx
export default function ProgressBar({
  label,
  value,
  pct,
  color = "var(--acc)",
}: {
  label: string;
  value: number;
  pct: number;
  color?: string;
}) {
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-[13px]">
        <span className="text-[var(--t1)]">{label}</span>
        <span className="text-[var(--t2)]">
          {value} · {pct}%
        </span>
      </div>
      <div className="h-2 rounded-full bg-[var(--bd)] overflow-hidden">
        <div
          data-fill
          className="h-full rounded-full"
          style={{ width: `${Math.min(pct, 100)}%`, background: color }}
        />
      </div>
    </div>
  );
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd admin && npx vitest run tests/observability/ProgressBar.test.tsx`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add admin/src/components/observability/ProgressBar.tsx admin/tests/observability/ProgressBar.test.tsx
git commit -m "feat(admin): 新建 ProgressBar 横条进度组件"
```

---

## Task 8: IntentColumn 组件(意图深入列)

**Files:**
- Create: `admin/src/components/observability/IntentColumn.tsx`
- Test: `admin/tests/observability/IntentColumn.test.tsx`

**Interfaces:**
- Consumes: `MiniTrend`(Task 6)
- Produces: `IntentColumn({ name: string; count: number; pct: number; trend: number[]; drillTo: string; color?: string })` — 意图名 + 计数 + 百分比 + mini-trend + 下钻链接

- [ ] **Step 1: 写失败测试**

创建 `admin/tests/observability/IntentColumn.test.tsx`:

```tsx
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import IntentColumn from "@/components/observability/IntentColumn";

afterEach(cleanup);

function renderCol() {
  return render(
    <MemoryRouter>
      <IntentColumn
        name="销售咨询"
        count={120}
        pct={45}
        trend={[3, 5, 8, 6, 10, 12, 9]}
        drillTo="/conversations?intent=commercial"
      />
    </MemoryRouter>,
  );
}

describe("IntentColumn", () => {
  it("渲染意图名、计数、百分比", () => {
    renderCol();
    expect(screen.getByText("销售咨询")).toBeInTheDocument();
    expect(screen.getByText("120")).toBeInTheDocument();
    expect(screen.getByText(/45%/)).toBeInTheDocument();
  });

  it("下钻链接指向 drillTo", () => {
    renderCol();
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute(
      "href",
      expect.stringContaining("/conversations?intent=commercial"),
    );
  });

  it("渲染 7 根 mini-trend 柱", () => {
    const { container } = renderCol();
    expect(container.querySelectorAll("[data-bar]").length).toBe(7);
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd admin && npx vitest run tests/observability/IntentColumn.test.tsx`
Expected: FAIL

- [ ] **Step 3: 实现**

创建 `admin/src/components/observability/IntentColumn.tsx`:

```tsx
import { Link } from "react-router-dom";
import MiniTrend from "@/components/observability/MiniTrend";

export default function IntentColumn({
  name,
  count,
  pct,
  trend,
  drillTo,
  color = "var(--acc)",
}: {
  name: string;
  count: number;
  pct: number;
  trend: number[];
  drillTo: string;
  color?: string;
}) {
  return (
    <Link
      to={drillTo}
      className="block rounded-lg border p-4 hover:shadow-soft transition"
      style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
    >
      <div className="flex items-center justify-between mb-2">
        <span className="text-[14px] font-medium text-[var(--t1)]">{name}</span>
        <span className="text-[12px] text-[var(--t3)]">{pct}%</span>
      </div>
      <div className="text-2xl font-semibold text-[var(--t1)] mb-3">{count}</div>
      <MiniTrend data={trend} color={color} />
    </Link>
  );
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd admin && npx vitest run tests/observability/IntentColumn.test.tsx`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add admin/src/components/observability/IntentColumn.tsx admin/tests/observability/IntentColumn.test.tsx
git commit -m "feat(admin): 新建 IntentColumn 意图深入列组件"
```

---

## Task 9: 扩展既有 StageBar 支持 4 色

**Files:**
- Modify: `admin/src/components/observability/StageBar.tsx`(既有,加可选 `color` prop)
- Test: `admin/tests/observability/StageBar.test.tsx`(既有,需扩展)

**Interfaces:**
- Consumes: 无
- Produces: `StageBar({ stages: { key: string; ms: number; over?: boolean; color?: string }[] })` — 既有签名加可选 color;有 color 用 color,无则沿用 over 逻辑

- [ ] **Step 1: 扩展测试**

在 `admin/tests/observability/StageBar.test.tsx` 追加:

```tsx
  it("color prop 指定时段使用指定色", () => {
    const { container } = render(
      <StageBar
        stages={[
          { key: "前置", ms: 130, color: "var(--acc)" },
          { key: "检索", ms: 320, color: "var(--ok)" },
          { key: "生成", ms: 550, color: "var(--warn)" },
          { key: "输出", ms: 5, color: "var(--err)" },
        ]}
      />,
    );
    const segs = container.querySelectorAll("[data-seg]");
    expect(segs.length).toBe(4);
    expect(segs[0]).toHaveStyle("background: var(--acc)");
    expect(segs[1]).toHaveStyle("background: var(--ok)");
  });
```

注:既有 StageBar 段无 `data-seg` 属性,本步实现时补上。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd admin && npx vitest run tests/observability/StageBar.test.tsx`
Expected: FAIL(无 `data-seg` 或 color 未生效)

- [ ] **Step 3: 实现**

替换 `admin/src/components/observability/StageBar.tsx` 全部内容(保留既有 `data-over` 属性以维持向后兼容):

```tsx
type Stage = { key: string; ms: number; over?: boolean; color?: string };

export default function StageBar({ stages }: { stages: Stage[] }) {
  const total = stages.reduce((s, x) => s + x.ms, 0) || 1;
  return (
    <div className="flex h-5 rounded overflow-hidden border">
      {stages.map((st) => (
        <div
          key={st.key}
          data-seg={st.key}
          data-over={st.over ?? false}
          style={{
            width: `${(st.ms / total) * 100}%`,
            background: st.color ?? (st.over ? "var(--warn)" : "var(--acc-t)"),
          }}
          className={
            "flex items-center justify-center text-[11px] " +
            (st.color || st.over ? "text-white" : "text-[var(--acc)]")
          }
        >
          <span>{st.key}</span>
          <span className="ml-1">{st.ms}ms</span>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd admin && npx vitest run tests/observability/StageBar.test.tsx`
Expected: PASS(既有 2 个 + 新 1 个)

- [ ] **Step 5: 提交**

```bash
git add admin/src/components/observability/StageBar.tsx admin/tests/observability/StageBar.test.tsx
git commit -m "feat(admin): StageBar 加可选 color prop 支持 4 色段"
```

---

## Task 10: LanesBar 组件(Trace 总比例条)

**Files:**
- Create: `admin/src/components/observability/LanesBar.tsx`
- Test: `admin/tests/observability/LanesBar.test.tsx`

**Interfaces:**
- Consumes: 无
- Produces: `LanesBar({ lanes: { label: string; ms: number; color: string }[] })` — 单行横向比例条,按各阶段耗时占比着色

- [ ] **Step 1: 写失败测试**

创建 `admin/tests/observability/LanesBar.test.tsx`:

```tsx
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import LanesBar from "@/components/observability/LanesBar";

afterEach(cleanup);

describe("LanesBar", () => {
  it("渲染各 lane 段及标签", () => {
    render(
      <LanesBar
        lanes={[
          { label: "前置", ms: 130, color: "var(--acc)" },
          { label: "路由", ms: 0, color: "var(--t3)" },
          { label: "检索", ms: 320, color: "var(--ok)" },
          { label: "生成", ms: 550, color: "var(--warn)" },
          { label: "输出", ms: 5, color: "var(--err)" },
        ]}
      />,
    );
    expect(screen.getByText("前置")).toBeInTheDocument();
    expect(screen.getByText("检索")).toBeInTheDocument();
    expect(screen.getByText("生成")).toBeInTheDocument();
  });

  it("ms=0 的 lane 不渲染段(跳过阶段)", () => {
    const { container } = render(
      <LanesBar
        lanes={[{ label: "路由", ms: 0, color: "var(--t3)" }]}
      />,
    );
    expect(container.querySelector("[data-lane-seg]")).toBeNull();
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd admin && npx vitest run tests/observability/LanesBar.test.tsx`
Expected: FAIL

- [ ] **Step 3: 实现**

创建 `admin/src/components/observability/LanesBar.tsx`:

```tsx
type Lane = { label: string; ms: number; color: string };

export default function LanesBar({ lanes }: { lanes: Lane[] }) {
  const total = lanes.reduce((s, x) => s + x.ms, 0) || 1;
  return (
    <div className="space-y-1.5">
      <div className="flex h-3 rounded overflow-hidden border border-[var(--bd)]">
        {lanes.map((lane) =>
          lane.ms > 0 ? (
            <div
              key={lane.label}
              data-lane-seg={lane.label}
              style={{
                width: `${(lane.ms / total) * 100}%`,
                background: lane.color,
              }}
              className="h-full"
              title={`${lane.label} ${lane.ms}ms`}
            />
          ) : null,
        )}
      </div>
      <div className="flex flex-wrap gap-3 text-[11px] text-[var(--t3)]">
        {lanes.map((lane) => (
          <span key={lane.label}>
            {lane.label} {lane.ms}ms
          </span>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd admin && npx vitest run tests/observability/LanesBar.test.tsx`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add admin/src/components/observability/LanesBar.tsx admin/tests/observability/LanesBar.test.tsx
git commit -m "feat(admin): 新建 LanesBar Trace 总比例条组件"
```

---

## Task 11: NodeFlow 组件(降级链路节点流)

**Files:**
- Create: `admin/src/components/observability/NodeFlow.tsx`
- Test: `admin/tests/observability/NodeFlow.test.tsx`

**Interfaces:**
- Consumes: 无
- Produces: `NodeFlow({ nodes: { label: string; tone: "ok" | "warn" | "err" }[] })` — 节点-箭头横向流,色块按 tone

- [ ] **Step 1: 写失败测试**

创建 `admin/tests/observability/NodeFlow.test.tsx`:

```tsx
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import NodeFlow from "@/components/observability/NodeFlow";

afterEach(cleanup);

describe("NodeFlow", () => {
  it("渲染节点 + 箭头连接", () => {
    render(
      <NodeFlow
        nodes={[
          { label: "正常 RAG", tone: "ok" },
          { label: "单路检索", tone: "warn" },
          { label: "拒答", tone: "err" },
        ]}
      />,
    );
    expect(screen.getByText("正常 RAG")).toBeInTheDocument();
    expect(screen.getByText("单路检索")).toBeInTheDocument();
    expect(screen.getByText("拒答")).toBeInTheDocument();
    // 2 个箭头(3 节点间)
    expect(document.querySelectorAll("[data-arrow]").length).toBe(2);
  });

  it("tone 映射 data-tone 属性", () => {
    render(
      <NodeFlow nodes={[{ label: "降级", tone: "warn" }]} />,
    );
    expect(screen.getByText("降级").closest("[data-tone]")).toHaveAttribute(
      "data-tone",
      "warn",
    );
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd admin && npx vitest run tests/observability/NodeFlow.test.tsx`
Expected: FAIL

- [ ] **Step 3: 实现**

创建 `admin/src/components/observability/NodeFlow.tsx`:

```tsx
type Tone = "ok" | "warn" | "err";
type Node = { label: string; tone: Tone };

const TONE_BG: Record<Tone, string> = {
  ok: "var(--ok)",
  warn: "var(--warn)",
  err: "var(--err)",
};

export default function NodeFlow({ nodes }: { nodes: Node[] }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {nodes.map((node, i) => (
        <div key={i} className="flex items-center gap-2">
          <span
            data-tone={node.tone}
            className="px-2.5 py-1 rounded text-[12px] text-white font-medium"
            style={{ background: TONE_BG[node.tone] }}
          >
            {node.label}
          </span>
          {i < nodes.length - 1 && (
            <span data-arrow className="text-[var(--t3)]">
              →
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd admin && npx vitest run tests/observability/NodeFlow.test.tsx`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add admin/src/components/observability/NodeFlow.tsx admin/tests/observability/NodeFlow.test.tsx
git commit -m "feat(admin): 新建 NodeFlow 降级链路节点流组件"
```

---

## Task 12: ContainmentDiagram 组件(异常包含图)

**Files:**
- Create: `admin/src/components/observability/ContainmentDiagram.tsx`
- Test: `admin/tests/observability/ContainmentDiagram.test.tsx`

**Interfaces:**
- Consumes: 无
- Produces: `ContainmentDiagram({ anomaly: number; retry: number; fail: number })` — 三层嵌套框(异常 ⊃ 重试 ⊃ 失败),各带计数

- [ ] **Step 1: 写失败测试**

创建 `admin/tests/observability/ContainmentDiagram.test.tsx`:

```tsx
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import ContainmentDiagram from "@/components/observability/ContainmentDiagram";

afterEach(cleanup);

describe("ContainmentDiagram", () => {
  it("渲染三层标签及计数", () => {
    render(<ContainmentDiagram anomaly={100} retry={30} fail={10} />);
    expect(screen.getByText(/异常/)).toBeInTheDocument();
    expect(screen.getByText(/重试/)).toBeInTheDocument();
    expect(screen.getByText(/失败/)).toBeInTheDocument();
    expect(screen.getByText("100")).toBeInTheDocument();
    expect(screen.getByText("30")).toBeInTheDocument();
    expect(screen.getByText("10")).toBeInTheDocument();
  });

  it("外层 data-level=anomaly,内层 data-level=fail", () => {
    const { container } = render(
      <ContainmentDiagram anomaly={100} retry={30} fail={10} />,
    );
    expect(container.querySelector("[data-level='anomaly']")).toBeTruthy();
    expect(container.querySelector("[data-level='fail']")).toBeTruthy();
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd admin && npx vitest run tests/observability/ContainmentDiagram.test.tsx`
Expected: FAIL

- [ ] **Step 3: 实现**

创建 `admin/src/components/observability/ContainmentDiagram.tsx`:

```tsx
export default function ContainmentDiagram({
  anomaly,
  retry,
  fail,
}: {
  anomaly: number;
  retry: number;
  fail: number;
}) {
  return (
    <div
      data-level="anomaly"
      className="rounded-lg border-2 border-[var(--warn)] p-4"
    >
      <div className="flex items-center justify-between mb-2">
        <span className="text-[13px] font-medium text-[var(--warn)]">异常</span>
        <span className="text-lg font-semibold text-[var(--warn)]">{anomaly}</span>
      </div>
      <div
        data-level="retry"
        className="rounded-lg border-2 border-[var(--acc)] p-3"
      >
        <div className="flex items-center justify-between mb-2">
          <span className="text-[12px] font-medium text-[var(--acc)]">重试</span>
          <span className="text-base font-semibold text-[var(--acc)]">{retry}</span>
        </div>
        <div
          data-level="fail"
          className="rounded border-2 border-[var(--err)] p-2"
        >
          <div className="flex items-center justify-between">
            <span className="text-[12px] font-medium text-[var(--err)]">失败</span>
            <span className="text-sm font-semibold text-[var(--err)]">{fail}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd admin && npx vitest run tests/observability/ContainmentDiagram.test.tsx`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add admin/src/components/observability/ContainmentDiagram.tsx admin/tests/observability/ContainmentDiagram.test.tsx
git commit -m "feat(admin): 新建 ContainmentDiagram 异常包含图组件"
```

---

## Task 13: 改造 TraceLanes 为横向泳道 + 适配详情 5 段

**Files:**
- Modify: `admin/src/components/observability/TraceLanes.tsx`(既有)
- Test: `admin/tests/observability/TraceLanes.test.tsx`(既有,需扩展)

**Interfaces:**
- Consumes: 无
- Produces: `TraceLanes({ lanes: { key: string; label: string; ms: number; status: "ok" | "warn" | "err" | "skip"; items?: string[] }[] })` — 5 阶段横向泳道,每阶段左色块 + items + 耗时,跳过阶段标灰

- [ ] **Step 1: 扩展测试**

修改 `admin/tests/observability/TraceLanes.test.tsx`,既有测试用旧 `stages` prop 会改,先替换为新的 `lanes` prop 测试:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import TraceLanes from "@/components/observability/TraceLanes";

describe("TraceLanes", () => {
  it("渲染 5 泳道标签、ms 和状态", () => {
    render(
      <TraceLanes
        lanes={[
          { key: "pre", label: "前置", ms: 130, status: "ok" },
          { key: "route", label: "路由", ms: 0, status: "skip" },
          { key: "retrieve", label: "检索", ms: 320, status: "ok" },
          { key: "generate", label: "生成", ms: 550, status: "ok" },
          { key: "output", label: "输出", ms: 5, status: "ok" },
        ]}
      />,
    );
    expect(screen.getByText("前置")).toBeInTheDocument();
    expect(screen.getByText("路由")).toBeInTheDocument();
    expect(screen.getByText("检索")).toBeInTheDocument();
    expect(screen.getByText("生成")).toBeInTheDocument();
    expect(screen.getByText("输出")).toBeInTheDocument();
    expect(screen.getByText("检索").closest("[data-status]")).toHaveAttribute(
      "data-status",
      "ok",
    );
  });

  it("显示每条泳道的诊断 items", () => {
    render(
      <TraceLanes
        lanes={[
          { key: "pre", label: "前置", ms: 130, status: "ok", items: ["意图 commercial"] },
          { key: "retrieve", label: "检索", ms: 320, status: "ok", items: ["召回 15 条"] },
          { key: "generate", label: "生成", ms: 550, status: "ok", items: ["输出 120 token"] },
          { key: "output", label: "输出", ms: 5, status: "ok", items: ["来源 3 条"] },
        ]}
      />,
    );
    expect(screen.getByText("召回 15 条")).toBeInTheDocument();
    expect(screen.getByText("输出 120 token")).toBeInTheDocument();
    expect(screen.getByText("来源 3 条")).toBeInTheDocument();
  });

  it("skip 状态标灰(data-status=skip)", () => {
    render(
      <TraceLanes
        lanes={[{ key: "route", label: "路由", ms: 0, status: "skip" }]}
      />,
    );
    expect(screen.getByText("路由").closest("[data-status]")).toHaveAttribute(
      "data-status",
      "skip",
    );
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd admin && npx vitest run tests/observability/TraceLanes.test.tsx`
Expected: FAIL(既有组件用 `stages` prop,新测试用 `lanes`)

- [ ] **Step 3: 重写组件**

替换 `admin/src/components/observability/TraceLanes.tsx` 全部内容:

```tsx
type LaneStatus = "ok" | "warn" | "err" | "skip";
type Lane = {
  key: string;
  label: string;
  ms: number;
  status: LaneStatus;
  items?: string[];
};

const STATUS_COLOR: Record<LaneStatus, string> = {
  ok: "var(--ok)",
  warn: "var(--warn)",
  err: "var(--err)",
  skip: "var(--t3)",
};

export default function TraceLanes({ lanes }: { lanes: Lane[] }) {
  return (
    <div className="flex flex-col gap-1.5">
      {lanes.map((lane) => {
        const color = STATUS_COLOR[lane.status] ?? STATUS_COLOR.ok;
        return (
          <div
            key={lane.key}
            data-status={lane.status}
            className="flex items-stretch gap-2 border border-[var(--bd)] rounded overflow-hidden"
          >
            <div
              className="w-10 flex items-center justify-center text-[11px] text-white font-medium"
              style={{ background: color }}
            >
              {lane.label}
            </div>
            <div className="flex-1 px-3 py-1.5">
              <div className="flex items-center justify-between text-[12px]">
                <span className="text-[var(--t3)]">{lane.label}</span>
                <span style={{ color }} className="tabular-nums">
                  {lane.ms}ms
                </span>
              </div>
              {lane.items && lane.items.length > 0 && (
                <div className="flex flex-col gap-0.5 mt-0.5">
                  {lane.items.map((d, i) => (
                    <span key={i} className="text-[11px] text-[var(--t3)]">
                      {d}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd admin && npx vitest run tests/observability/TraceLanes.test.tsx`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add admin/src/components/observability/TraceLanes.tsx admin/tests/observability/TraceLanes.test.tsx
git commit -m "feat(admin): TraceLanes 改造为横向泳道 5 段 + skip 标灰"
```

---

## Task 14: 对话审查页接线(列表 StageBar + 详情 TraceLanes/LanesBar + 置信度)

**Files:**
- Modify: `admin/src/pages/Conversations.tsx`
- Test: `admin/tests/ConversationsReview.test.tsx`(既有,需保持绿)

**Interfaces:**
- Consumes: `StageBar`(Task 9)、`TraceLanes`(Task 13)、`LanesBar`(Task 10)、`Conversation.trace_summary`(Task 2)
- Produces: 列表行加 4 段 StageBar + 置信度;详情改 TraceLanes 5 段泳道 + LanesBar + 多轮按钮类型标注

- [ ] **Step 1: 读既有测试确认契约**

读 `admin/tests/ConversationsReview.test.tsx`。既有 8 个测试的契约(必须在接线后保持绿):
- L98-105: 列表显示 `NE503 价格`、意图标签 `/commercial|商务/`、总耗时 `/1,?000/`
- L107-115: 点击行展开 trace,显示 `意图分类` + `输出构建`(精确文本)
- L117-124: commercial 对话显示 `/联系销售/`
- L126-136: trace 显示 `/召回 15 条/`、`/top分 0\.820/`、`/输出 120 token/`、`/来源 3 条/`
- L138-173: 多轮可切换,按钮 `getByText("轮 2")` 精确匹配,切换后 `/召回 5 条/`
- L175-178: 搜索框 placeholder `/搜索问题/`
- L180-185: `[data-feedback="up"]`
- L187-194: 类型 badge `RAG 生成`

**关键约束**:
1. "意图分类" 测试(L112)是 `getByText("意图分类")` 精确匹配——若改为 `getByText(/意图分类/)` 则 substring 也行。Plan 采用:更新测试为正则匹配 `/意图分类/`,并在前置 lane 的 item 里保留 "意图分类" 文本(如 `意图分类 commercial`)。
2. "输出构建" 测试(L113)同理——Plan 保留 "输出构建" 作为输出 lane 的 label,更新测试为 `/输出构建/`。
3. 多轮按钮测试(L169)是 `getByText("轮 2")`——若按钮文本改为 `轮 2 RAG` 则 `getByText("轮 2")` 失败(默认精确匹配)。Plan 采用:按钮文本保持 `轮 N`,类型标注用独立 `<Badge>` 而非拼进按钮文本,避免破坏精确匹配。
4. L102 `/commercial|商务/` —— Conversations.tsx 有自己的 `INTENT_LABELS`(L18-23,需确认是否独立)。本任务不改 Conversations.tsx 的 INTENT_LABELS(命名对齐只在 Task 15 BusinessOverview 做),故 L102 不会因重命名失效。

**需更新的既有测试**(Task 14 一起改,而非改组件签名):
- L112 `getByText("意图分类")` → `getByText(/意图分类/)`
- L113 `getByText("输出构建")` → `getByText(/输出构建/)`
- L131 `getByText(/召回 15 条/)` 仍是正则,不受影响
- L169 `getByText("轮 2")` 保持精确(按钮文本不变)

- [ ] **Step 2: 更新既有测试契约**

修改 `admin/tests/ConversationsReview.test.tsx`:
- L112: `expect(screen.getByText("意图分类"))` → `expect(screen.getByText(/意图分类/))`
- L113: `expect(screen.getByText("输出构建"))` → `expect(screen.getByText(/输出构建/))`

其他断言保持不变(按钮 `轮 2` 精确、`/召回 15 条/` 正则、`RAG 生成` 精确、`/联系销售/` 正则)。

- [ ] **Step 3: 修改列表行加 StageBar + 置信度**

在 `admin/src/pages/Conversations.tsx` 顶部 import 补:

```tsx
import StageBar from "@/components/observability/StageBar";
import TraceLanes from "@/components/observability/TraceLanes";
import LanesBar from "@/components/observability/LanesBar";
```

列表行结构:L208-253 是 `<div className="flex items-start justify-between gap-4">...</div>`,L254 是闭合 `</div>`。在 L253 之后、L254 之前(即 `flex items-start justify-between` div 闭合后,行容器 div 闭合前)插入 StageBar + 置信度:

```tsx
                  {conv.trace_summary && conv.trace_summary.stages && (
                    <div className="mt-2 space-y-1">
                      <StageBar
                        stages={[
                          {
                            key: "前置",
                            ms: (conv.trace_summary.stages.intent?.ms ?? 0) +
                              (conv.trace_summary.stages.rewrite?.ms ?? 0),
                            color: "var(--acc)",
                          },
                          {
                            key: "检索",
                            ms: (conv.trace_summary.stages.retrieve?.ms ?? 0) +
                              (conv.trace_summary.stages.rerank?.ms ?? 0),
                            color: "var(--ok)",
                          },
                          {
                            key: "生成",
                            ms: conv.trace_summary.stages.generate?.ms ?? 0,
                            color: "var(--warn)",
                          },
                          {
                            key: "输出",
                            ms: conv.trace_summary.stages.output?.ms ?? 0,
                            color: "var(--err)",
                          },
                        ]}
                      />
                      {conv.trace_summary.confidence != null && (
                        <div
                          className={
                            "text-[11px] " +
                            (conv.trace_summary.confidence < 0.6
                              ? "text-[var(--warn)]"
                              : "text-[var(--t3)]")
                          }
                        >
                          置信 {(conv.trace_summary.confidence * 100).toFixed(0)}%
                        </div>
                      )}
                    </div>
                  )}
```

- [ ] **Step 4: 改造详情 trace 为 TraceLanes + LanesBar**

替换 L391-492 的 6 个 `TraceStageCard` 块为 `LanesBar` + `TraceLanes`。保留 L346-370 的 Badge/confidence/总耗时 头部不变,保留 L372-389 的轮次选择器不变。从 L391(`<TraceStageCard label="意图分类"...`)到 L492(最后一个 `</TraceStageCard>`)整段替换为:

```tsx
                {/* LanesBar 总比例条 */}
                <LanesBar
                  lanes={[
                    { label: "前置", ms: rewriteSt?.ms ?? 0, color: "var(--acc)" },
                    { label: "路由", ms: 0, color: "var(--t3)" },
                    {
                      label: "检索",
                      ms: (retrieveSt?.ms ?? 0) + (rerankSt?.ms ?? 0),
                      color: "var(--ok)",
                    },
                    { label: "生成", ms: genSt?.ms ?? 0, color: "var(--warn)" },
                    { label: "输出", ms: outSt?.ms ?? 0, color: "var(--err)" },
                  ]}
                />

                {/* 5 段横向泳道 */}
                <TraceLanes
                  lanes={[
                    {
                      key: "pre",
                      label: "前置",
                      ms: rewriteSt?.ms ?? 0,
                      status: "ok",
                      items: [
                        ...(intentSt?.category ? [`意图分类 ${intentSt.category}`] : []),
                        ...(intentSt?.reason ? [intentSt.reason] : []),
                        ...(rewriteSt?.extracted ? [`提取 ${rewriteSt.extracted}`] : []),
                        ...(rewriteSt?.rewritten ? [`改写 ${rewriteSt.rewritten}`] : []),
                      ],
                    },
                    {
                      key: "route",
                      label: "路由",
                      ms: 0,
                      status: "skip",
                      items: [
                        ...(intentSt?.category ? [`路由 ${intentSt.category}`] : []),
                        ...(retrieveSt?.effective_min !== undefined
                          ? [`阈值 ${retrieveSt.effective_min}`]
                          : []),
                      ],
                    },
                    {
                      key: "retrieve",
                      label: "检索",
                      ms: (retrieveSt?.ms ?? 0) + (rerankSt?.ms ?? 0),
                      status: "ok",
                      items: [
                        ...(retrieveSt?.hybrid_count !== undefined
                          ? [`召回 ${retrieveSt.hybrid_count} 条`]
                          : []),
                        ...(retrieveSt?.path_counts
                          ? [
                              `hybrid ${retrieveSt.path_counts.hybrid} · symbol ${retrieveSt.path_counts.symbol} · boost ${retrieveSt.path_counts.boost}`,
                            ]
                          : []),
                        ...(rerankSt?.top_score != null
                          ? [`top分 ${rerankSt.top_score.toFixed(3)}`]
                          : []),
                        ...(rerankSt?.count !== undefined
                          ? [`rerank ${rerankSt.count} 条`]
                          : []),
                      ],
                    },
                    {
                      key: "generate",
                      label: "生成",
                      ms: genSt?.ms ?? 0,
                      status: "ok",
                      items: [
                        ...(genSt?.ttft_ms != null
                          ? [`TTFT ${genSt.ttft_ms.toLocaleString()}ms`]
                          : []),
                        ...(genSt?.tokens_output != null
                          ? [`输出 ${genSt.tokens_output} token`]
                          : []),
                      ],
                    },
                    {
                      key: "output",
                      label: "输出构建",
                      ms: outSt?.ms ?? 0,
                      status: "ok",
                      items: [
                        ...(outSt?.sources_count !== undefined
                          ? [`来源 ${outSt.sources_count} 条`]
                          : []),
                      ],
                    },
                  ]}
                />
```

**文本对齐测试**:前置 lane item 含 "意图分类" → `/意图分类/` 匹配 ✅;输出 lane label 是 "输出构建" → `/输出构建/` 匹配 ✅;检索 lane item 含 "召回 15 条" → `/召回 15 条/` ✅;检索 lane item 含 "top分 0.820" → `/top分 0\.820/` ✅;生成 lane item 含 "输出 120 token" → `/输出 120 token/` ✅;输出 lane item 含 "来源 3 条" → `/来源 3 条/` ✅。

注意:既有 `TraceStageCard` 函数(L33-?)定义保留(不删,后续可清理),但使用处全部移除。

- [ ] **Step 5: 多轮按钮标注类型(独立 Badge,不改按钮文本)**

修改 L374-387 的轮次按钮,按钮文本保持 `轮 {t.turn_index + 1}`,在按钮内追加独立 `<Badge>` 类型标注(不拼进文本节点,保持 `getByText("轮 2")` 精确匹配):

```tsx
                    {traces.map((t) => (
                      <button
                        key={t.id}
                        onClick={() => setTurnIndex(t.turn_index)}
                        className={
                          "h-6 rounded px-2 text-xs border " +
                          (turnIndex === t.turn_index
                            ? "bg-primary text-primary-foreground"
                            : "bg-card")
                        }
                      >
                        <span>轮 {t.turn_index + 1}</span>
                        {(t.type === "clarify" || t.type === "reject_short") && (
                          <Badge variant="outline" className="ml-1 text-[9px] px-1 py-0">
                            {t.type === "clarify" ? "澄清" : "拒答"}
                          </Badge>
                        )}
                      </button>
                    ))}
```

说明:`getByText("轮 2")` 匹配 `<span>轮 2</span>` 文本节点,Badge 是独立子元素不影响。rag 类型不加 Badge(默认),避免噪声。

- [ ] **Step 6: 运行既有测试确认绿**

Run: `cd admin && npx vitest run tests/ConversationsReview.test.tsx`
Expected: PASS(8 个测试全绿。若 "意图分类"/"输出构建" 匹配失败,检查 Step 2 测试是否改为正则;若 "轮 2" 失败,检查按钮文本是否被拆成独立 span。)

- [ ] **Step 7: 提交**

```bash
git add admin/src/pages/Conversations.tsx admin/tests/ConversationsReview.test.tsx
git commit -m "feat(admin): 对话审查列表加 StageBar+置信度,详情改 TraceLanes 泳道+LanesBar"
```

---

## Task 15: 业务概览页接线(StackedBar + 三列 IntentColumn + ProgressBar + 命名对齐)

**Files:**
- Modify: `admin/src/pages/BusinessOverview.tsx`
- Test: `admin/tests/BusinessOverview.test.tsx`(既有,需保持绿 + 扩展)

**Interfaces:**
- Consumes: `StackedBar`(Task 5)、`IntentColumn`(Task 8)、`ProgressBar`(Task 7)、`BusinessOverviewData`(Task 3 同步的 geo.pct)
- Produces: 服务总览卡加 StackedBar;新建三列意图卡替换扁平意图分布;地域加 ProgressBar;命名 "商务咨询"→"销售咨询"、"产品咨询"→"产品方案"

- [ ] **Step 1: 更新 mock 数据 + 既有断言**

修改 `admin/tests/BusinessOverview.test.tsx`。既有 mock(L7-37)缺 `unknown_intent_count`、`up_count`/`down_count`、geo 无 pct、timeseries 为空。先补全 mock 让新组件可渲染:

```tsx
vi.mock("@/lib/api/businessOverview", () => ({
  fetchBusinessOverview: vi.fn().mockResolvedValue({
    service: {
      total: 120,
      intent_dist: { commercial: 30, product: 50, support: 35, off_topic: 5 },
      unknown_intent_count: 2,
      north_star: 18,
      satisfaction: 85,
      up_count: 10,
      down_count: 1,
    },
    leads: {
      valid: 12,
      potential: 8,
      hot_products: [
        { name: "NE503", count: 10 },
        { name: "NE301", count: 6 },
      ],
    },
    scenes: [
      { label: "工业视觉", count: 15, pct: 50 },
      { label: "安防", count: 8, pct: 27 },
    ],
    requirements: [
      { label: "4K 录制", count: 9, pct: 30 },
      { label: "开放 API", count: 6, pct: 20 },
    ],
    top_questions: [
      { question: "NE503 价格", count: 8 },
      { question: "SDK 怎么接入", count: 5 },
    ],
    geo: [
      { name: "中国", count: 60, pct: 50 },
      { name: "美国", count: 30, pct: 25 },
    ],
    geo_note: "地域分布",
    timeseries: [
      { date: "08-04", total: 5, commercial: 2, product: 2, support: 1, off_topic: 0 },
      { date: "08-05", total: 8, commercial: 3, product: 3, support: 2, off_topic: 0 },
      { date: "08-06", total: 6, commercial: 2, product: 2, support: 2, off_topic: 0 },
      { date: "08-07", total: 10, commercial: 4, product: 3, support: 3, off_topic: 0 },
      { date: "08-08", total: 7, commercial: 3, product: 2, support: 2, off_topic: 0 },
      { date: "08-09", total: 9, commercial: 3, product: 4, support: 2, off_topic: 0 },
      { date: "08-10", total: 11, commercial: 4, product: 4, support: 3, off_topic: 0 },
    ],
  }),
}));
```

既有断言 L60 `expect(screen.getByText(/销售咨询/))` —— 改造后 "销售咨询" 出现在 KpiCard label(L67 既有)+ StackedBar 图例 + IntentColumn 名,共 3 处,`getByText` 抛 "multiple elements"。改为:

```tsx
      expect(screen.getAllByText(/销售咨询/).length).toBeGreaterThan(0);
```

- [ ] **Step 2: 追加新测试**

在 `admin/tests/BusinessOverview.test.tsx` 的 describe 块末尾追加:

```tsx
  it("三列意图卡渲染产品方案和技术支持", async () => {
    renderWithProviders(<BusinessOverview />);
    await waitFor(() => {
      // 销售咨询已多处,用 getAllByText;产品方案/技术支持首现于三列卡
      expect(screen.getAllByText(/产品方案/).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/技术支持/).length).toBeGreaterThan(0);
    });
  });

  it("地域分布渲染 ProgressBar 填充条", async () => {
    renderWithProviders(<BusinessOverview />);
    await waitFor(() => {
      expect(document.querySelector("[data-fill]")).toBeInTheDocument();
    });
  });
```

- [ ] **Step 3: 运行测试确认失败**

Run: `cd admin && npx vitest run tests/BusinessOverview.test.tsx`
Expected: 部分 FAIL(三列卡 IntentColumn 未渲染,`/产品方案/` 不存在;ProgressBar 未渲染,`[data-fill]` 不存在)

- [ ] **Step 4: 实现**

修改 `admin/src/pages/BusinessOverview.tsx`。顶部 import 补:

```tsx
import StackedBar from "@/components/observability/StackedBar";
import IntentColumn from "@/components/observability/IntentColumn";
import ProgressBar from "@/components/observability/ProgressBar";
```

修改 `INTENT_LABELS` 常量(L333-338)对齐设计稿命名:

```tsx
const INTENT_LABELS: Record<string, string> = {
  commercial: "销售咨询",
  product: "产品方案",
  support: "技术支持",
  off_topic: "无关闲聊",
};

const INTENT_COLORS: Record<string, string> = {
  commercial: "var(--acc)",
  product: "var(--ok)",
  support: "var(--warn)",
  off_topic: "var(--t3)",
};
```

替换 "三意图分布" 区块(L89-123)为两块:服务总览 StackedBar + 三列 IntentColumn。把 L89-123 整块替换为:

```tsx
          {/* 服务总览意图堆叠条 */}
          <div
            className="rounded-lg border p-4"
            style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
          >
            <h2 className="text-[14px] font-medium text-[var(--t1)] mb-3">
              意图分布
            </h2>
            <StackedBar
              segments={[
                { label: "销售咨询", value: data.service.intent_dist.commercial, color: INTENT_COLORS.commercial },
                { label: "产品方案", value: data.service.intent_dist.product, color: INTENT_COLORS.product },
                { label: "技术支持", value: data.service.intent_dist.support, color: INTENT_COLORS.support },
                { label: "无关闲聊", value: data.service.intent_dist.off_topic, color: INTENT_COLORS.off_topic },
              ]}
            />
          </div>

          {/* 三列意图深入卡 */}
          <div className="grid grid-cols-3 gap-4">
            {(["commercial", "product", "support"] as const).map((intent) => {
              const total = data.service.intent_dist.commercial +
                data.service.intent_dist.product + data.service.intent_dist.support +
                data.service.intent_dist.off_topic || 1;
              const count = data.service.intent_dist[intent];
              const pct = Math.round((count / total) * 100);
              // mini-trend:最近 7 天该意图日分量(TimeseriesDay 已有 commercial/product/support 字段)
              const trend = data.timeseries.slice(-7).map((d) => d[intent]);
              return (
                <IntentColumn
                  key={intent}
                  name={INTENT_LABELS[intent]}
                  count={count}
                  pct={pct}
                  trend={trend}
                  drillTo={`/conversations?intent=${intent}`}
                  color={INTENT_COLORS[intent]}
                />
              );
            })}
          </div>

          {/* 未识别意图小计数(off_topic + unknown 不入三列卡) */}
          {(data.service.intent_dist.off_topic > 0 || data.service.unknown_intent_count > 0) && (
            <div className="flex gap-4 text-[12px] text-[var(--t3)]">
              {data.service.intent_dist.off_topic > 0 && (
                <span>无关闲聊 {data.service.intent_dist.off_topic}</span>
              )}
              {data.service.unknown_intent_count > 0 && (
                <span className="text-[var(--warn)]">
                  未识别意图 {data.service.unknown_intent_count}
                </span>
              )}
            </div>
          )}
```

替换地域分布区块(L311-326)用 ProgressBar:

```tsx
          {/* 地域分布 */}
          <div
            className="rounded-lg border p-4"
            style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
          >
            <h2 className="text-[14px] font-medium text-[var(--t1)] mb-3">
              地域分布
            </h2>
            {data.geo.length > 0 ? (
              <div className="space-y-2">
                {data.geo.map((g) => (
                  <ProgressBar
                    key={g.name}
                    label={g.name}
                    value={g.count}
                    pct={g.pct}
                  />
                ))}
              </div>
            ) : (
              <div className="text-[12px] text-[var(--t3)]">{data.geo_note}</div>
            )}
          </div>
```

- [ ] **Step 5: 运行测试确认通过**

Run: `cd admin && npx vitest run tests/BusinessOverview.test.tsx`
Expected: PASS(4 个测试含 2 新测试)

- [ ] **Step 6: 提交**

```bash
git add admin/src/pages/BusinessOverview.tsx admin/tests/BusinessOverview.test.tsx
git commit -m "feat(admin): 业务概览加 StackedBar+三列 IntentColumn+地域 ProgressBar,命名对齐设计稿"
```

---

## Task 16: 技术洞察页接线(KPI count+delta + ContainmentDiagram + NodeFlow + 异常圆点 pct)

**Files:**
- Modify: `admin/src/pages/Analytics.tsx`
- Test: `admin/tests/TechInsight.test.tsx`(既有,含 1 个失败测试需修复)

**Interfaces:**
- Consumes: `ContainmentDiagram`(Task 12)、`NodeFlow`(Task 11)、`KpiCard`(既有)、`TrendChart`(既有)、`TechKpi`(Task 4:count+delta)、`AnomalyItem.pct`(Task 4)
- Produces: KPI 卡补 count 副数据 + delta 环比;加 ContainmentDiagram;异常分布加彩色圆点 + pct;降级链路改 NodeFlow;知识缺口 tab 加澄清漏斗占位(修复既有失败测试)

- [ ] **Step 1: 读既有失败测试确认契约**

读 `admin/tests/TechInsight.test.tsx`:5 个测试,其中第 5 个(L114-121)"澄清漏斗显示暂无数据" 当前失败,因 KnowledgeGapsTab 无澄清漏斗块。需补占位文本 "澄清漏斗" + "暂无数据" 或 "待接入"。

既有 mock(L16-32)的 `kpi` 只有 6 字段(p95_ms/anomaly_rate/retry_rate/fail_rate),缺 count/delta;`anomalies` 缺 pct。接线后 KpiCard 读 `anomaly_count` 会得 undefined。必须补 mock。

- [ ] **Step 2: 补 mock 数据**

修改 `admin/tests/TechInsight.test.tsx` 的 `mockTechPerf.mockResolvedValue`(L16-32)补 count/delta,anomalies 补 pct:

```tsx
mockTechPerf.mockResolvedValue({
  kpi: {
    p95_ms: 1200,
    anomaly_rate: 0.1,
    retry_rate: 0.05,
    fail_rate: 0.02,
    anomaly_count: 12,
    retry_count: 6,
    fail_count: 2,
    anomaly_delta: 0.03,
    retry_delta: -0.01,
    fail_delta: 0.0,
    baseline: 3000,
    comparison: 0.0,
  },
  stages: {
    intent: { p50: 50, p95: 80, normal_max: 500 },
    rewrite: { p50: 200, p95: 400, normal_max: 2000 },
    retrieve: { p50: 500, p95: 800, normal_max: 3000 },
    rerank: { p50: 300, p95: 600, normal_max: 2000 },
    generate: { p50: 3000, p95: 5000, normal_max: 2000 },
  },
  trends: Array.from({ length: 7 }, (_, i) => ({
    date: `08-0${i + 1}`,
    p50: 300,
    p95: 1000,
  })),
  anomalies: [{ type: "LLM 超时", count: 3, pct: 60.0 }],
  degradations: [],
});
```

- [ ] **Step 3: 实现 KPI count + delta**

修改 `admin/src/pages/Analytics.tsx`。KPI 4 卡区(L75-108)给异常率/重试率/失败率卡补 `baseline`(count 副数据)和 `delta`(环比):

```tsx
        <KpiCard
          label="异常率"
          value={Math.round(data.kpi.anomaly_rate * 100)}
          unit="%"
          alarm={data.kpi.anomaly_rate > 0.1}
          baseline={`异常 ${data.kpi.anomaly_count}`}
          delta={
            data.kpi.anomaly_delta !== 0
              ? {
                  value: Math.round(data.kpi.anomaly_delta * 100),
                  dir: data.kpi.anomaly_delta > 0 ? "up" : "down",
                }
              : undefined
          }
        />
        <KpiCard
          label="重试率"
          value={Math.round(data.kpi.retry_rate * 100)}
          unit="%"
          baseline={`重试 ${data.kpi.retry_count}`}
          delta={
            data.kpi.retry_delta !== 0
              ? {
                  value: Math.round(data.kpi.retry_delta * 100),
                  dir: data.kpi.retry_delta > 0 ? "up" : "down",
                }
              : undefined
          }
        />
        <KpiCard
          label="失败率"
          value={Math.round(data.kpi.fail_rate * 100)}
          unit="%"
          alarm={data.kpi.fail_rate > 0.05}
          baseline={`失败 ${data.kpi.fail_count}`}
          delta={
            data.kpi.fail_delta !== 0
              ? {
                  value: Math.round(data.kpi.fail_delta * 100),
                  dir: data.kpi.fail_delta > 0 ? "up" : "down",
                }
              : undefined
          }
        />
```

- [ ] **Step 4: 加 ContainmentDiagram**

顶部 import 补:

```tsx
import ContainmentDiagram from "@/components/observability/ContainmentDiagram";
import NodeFlow from "@/components/observability/NodeFlow";
```

在 KPI 4 卡区之后(trace 覆盖提示之前)加 ContainmentDiagram:

```tsx
      {/* 异常包含关系图 */}
      <div className="max-w-xs">
        <ContainmentDiagram
          anomaly={data.kpi.anomaly_count}
          retry={data.kpi.retry_count}
          fail={data.kpi.fail_count}
        />
      </div>
```

- [ ] **Step 5: 技术性能三列 grid3 并排(慢在哪/什么异常/降级到什么)+ NodeFlow + 异常圆点 pct**

把现有独立的"阶段表"(L129-166)、"异常分布"(L169-197)、"降级链路"(L199-219)三块整段删除,替换为单个 grid3 容器,三列并排,各列加 `data-col`。异常列加彩色圆点 + pct,降级列用 NodeFlow:

```tsx
      {/* 技术性能三列并排:慢在哪 / 什么异常 / 降级到什么 */}
      <div data-tech-grid3 className="grid grid-cols-3 gap-4">
        {/* 慢在哪:阶段表 */}
        <div
          data-col="slow"
          className="rounded-lg border p-4"
          style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
        >
          <h2 className="text-[14px] font-medium text-[var(--t1)] mb-3">
            慢在哪(阶段 P50/P95)
          </h2>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>阶段</TableHead>
                <TableHead>P50</TableHead>
                <TableHead>P95</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {Object.entries(data.stages).map(([stage, s]) => {
                const over = s.p95 > s.normal_max;
                return (
                  <TableRow key={stage}>
                    <TableCell
                      data-over={over}
                      className={over ? "text-[var(--warn)] font-medium" : ""}
                    >
                      {stage}
                    </TableCell>
                    <TableCell>{s.p50.toLocaleString()}</TableCell>
                    <TableCell>{s.p95.toLocaleString()}</TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>

        {/* 什么异常:异常分布 */}
        <div
          data-col="anomaly"
          className="rounded-lg border p-4"
          style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
        >
          <h2 className="text-[14px] font-medium text-[var(--t1)] mb-3">
            什么异常
          </h2>
          {data.anomalies.length > 0 ? (
            <div className="space-y-1">
              {data.anomalies.map((a, i) => (
                <div key={i} className="flex items-center justify-between text-[13px]">
                  <span className="flex items-center gap-2">
                    <span
                      className="inline-block w-2 h-2 rounded-full"
                      style={{
                        background:
                          a.count > 5 ? "var(--err)" : a.count > 2 ? "var(--warn)" : "var(--t3)",
                      }}
                    />
                    {a.type}
                  </span>
                  <span className="text-[var(--t2)]">
                    {a.count}
                    {a.pct != null && (
                      <span className="text-[var(--t3)] ml-1">({a.pct}%)</span>
                    )}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-[12px] text-[var(--t3)]">暂无异常</div>
          )}
        </div>

        {/* 降级到什么:降级链路 */}
        <div
          data-col="degrade"
          className="rounded-lg border p-4"
          style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
        >
          <h2 className="text-[14px] font-medium text-[var(--t1)] mb-3">
            降级到什么
          </h2>
          {data.degradations.length > 0 ? (
            <div className="space-y-2">
              {data.degradations.map((d, i) => (
                <NodeFlow
                  key={i}
                  nodes={[
                    { label: d.from, tone: "ok" },
                    { label: d.to, tone: "warn" },
                  ]}
                />
              ))}
            </div>
          ) : (
            <div className="text-[12px] text-[var(--t3)]">无降级</div>
          )}
        </div>
      </div>
```

**测试对齐**:L92-103 阶段表 `generate`/`intent` + `data-over` 仍渲染于 `data-col="slow"` 列 ✅;L114-121 澄清漏斗在 Step 6 补 ✅。原 L169-219 三块已删除,无重复渲染。

- [ ] **Step 6: 知识缺口 tab 加澄清漏斗占位**

在 `KnowledgeGapsTab` 函数(L276 开始)的 "缺口类型分布" 区块之后,加澄清漏斗占位(修复既有失败测试):

```tsx
      {/* 澄清漏斗占位(Phase 3 真实数据) */}
      <div
        className="rounded-lg border p-4"
        style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
      >
        <h2 className="text-[14px] font-medium text-[var(--t1)] mb-3">
          澄清漏斗
        </h2>
        <div className="text-[12px] text-[var(--t3)]">暂无数据(待接入)</div>
      </div>
```

- [ ] **Step 7: 扩展测试(grid3 + ContainmentDiagram)**

在 `admin/tests/TechInsight.test.tsx` 的 describe 块末尾追加:

```tsx
  it("技术性能三列并排 grid3", async () => {
    renderWithProviders(<Analytics />);
    await waitFor(() => {
      const grid = document.querySelector("[data-tech-grid3]");
      expect(grid).toBeTruthy();
      expect(grid!.querySelectorAll("[data-col]").length).toBe(3);
    });
  });
```

- [ ] **Step 8: 运行测试确认通过**

Run: `cd admin && npx vitest run tests/TechInsight.test.tsx`
Expected: PASS(6 个测试全绿,含原失败的"澄清漏斗"测试 + 新 grid3 测试)

- [ ] **Step 9: 提交**

```bash
git add admin/src/pages/Analytics.tsx admin/tests/TechInsight.test.tsx
git commit -m "feat(admin): 技术洞察 KPI count+delta+ContainmentDiagram+grid3 三列+NodeFlow+异常pct+澄清漏斗占位"
```

---

## Task 17: 全量测试 + 类型检查 + 构建收尾

**Files:**
- 无新文件,验证全绿

- [ ] **Step 1: 前端全量测试(固定文件清单)**

Run: `cd admin && npx vitest run`
Expected: 全部 PASS。涉及 15 个测试文件:
- 既有 9 个:`tests/ConversationsReview.test.tsx`、`tests/BusinessOverview.test.tsx`、`tests/TechInsight.test.tsx`、`tests/observability/KpiCard.test.tsx`、`tests/observability/StageBar.test.tsx`、`tests/observability/TraceLanes.test.tsx`、`tests/observability/TrendChart.test.tsx`、`tests/observability/TimeFilter.test.tsx`、其余非本计划文件(`DataSources`/`ChainChip`/`AddToTaskDialog`/`ProviderEditDialog`/`ProviderCredentialDialog`/`Sidebar`/`useLLMProviders`/`useTriggerSync`)全绿
- 新增 6 个组件测试:`tests/observability/StackedBar.test.tsx`、`tests/observability/MiniTrend.test.tsx`、`tests/observability/ProgressBar.test.tsx`、`tests/observability/IntentColumn.test.tsx`、`tests/observability/LanesBar.test.tsx`、`tests/observability/NodeFlow.test.tsx`、`tests/observability/ContainmentDiagram.test.tsx`

- [ ] **Step 2: 前端类型检查**

Run: `cd admin && npx tsc -b --noEmit`
Expected: 无报错

- [ ] **Step 3: 后端 admin 测试**

Run: `TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test uv run pytest tests/api/admin/test_conversations.py tests/api/admin/test_analytics_business.py tests/api/admin/test_tech_perf.py -v`
Expected: 全部 PASS(含 Task 1 新增 trace 选择测试 + Task 3 新增 geo/90d 测试 + Task 4 新增 KPI count/delta/pct 测试)

- [ ] **Step 4: 前端构建验证**

Run: `cd admin && npm run build`
Expected: 构建成功(产物到 admin/dist;无类型错误、无 import 解析失败)

- [ ] **Step 5: 提交(如有修复)**

```bash
# 仅 add 本次修复涉及的文件,不盲目 git add -A
git add admin/src admin/tests backend/api/admin
git commit -m "test(admin): Phase 1 全量测试通过" || echo "无变更需提交"
```

---

## Task 18: Real-Run Gate(真实运行验证)

> 本计划终端目标是 **implementation**(测试通过的分支,不部署)。Real-Run Gate 在此层级验证:真实后端服务能启动并通过 ASGI 路由返回新字段;前端 build 产物真实可加载。如果环境不可用(postgres 未起 / 模型未加载),如实报告并给出命令,不伪造通过。

**Files:**
- 无新文件,验证真实运行

- [ ] **Step 1: 后端 import + 启动冒烟**

Run: `uv run python -c "from backend.main import app; print('import ok')"`
Expected: 输出 `import ok`,无 ImportError/AttributeError(确认 conversations.py 的 `desc` import、business.py 的 geo pct、tech.py 的 count/delta 改动不破坏 app 构造)

如果本地有 postgres(见 Task 18 Step 2 条件),继续启动服务:
Run: `uv run python -m backend.main`(后台或独立终端)
Expected: `Uvicorn running on http://localhost:8000`,无启动崩溃

- [ ] **Step 2: 真实 API 响应验证(需 postgres + 测试库有数据)**

前置:postgres 运行中 + `ask_ai_test` 库可访问 + 至少有 1 条 conversation/trace。

Run(需 admin JWT;若无,先 `uv run python scripts/create_admin_user.py`):
```bash
TOKEN="<admin jwt>"
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/admin/conversations | python -m json.tool | head -30
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/admin/business/overview?range=90d | python -m json.tool | grep -A5 '"geo"'
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8000/api/admin/tech/performance?range=7d | python -m json.tool | grep -E 'anomaly_count|anomaly_delta|pct'
```

Expected(真实输出,非 mock):
- `/conversations` 的 `items[].trace_summary` 含 `confidence` 字段(number 或 null),且多轮对话取最新轮次
- `/business/overview?range=90d` 不报错(90d 键已支持),`geo[].pct` 字段存在
- `/tech/performance` 的 `kpi` 含 `anomaly_count`/`retry_count`/`fail_count`/`anomaly_delta`/`retry_delta`/`fail_delta`,`anomalies[].pct` 存在

把真实输出关键行粘贴到本 Task 作为证据。如果字段在真实数据中为 null/0(因测试库无对应数据),说明值来源并确认结构存在即可。

- [ ] **Step 3: 前端 build 产物可加载(已由 Task 17 Step 4 覆盖)**

`npm run build` 成功即证明产物完整。如需浏览器 Real-Run:
Run: `cd admin && npm run preview`(或 `npm run dev`)
打开 http://localhost:4173 (preview) 或 :5174 (dev),切到三页,确认:
- 对话审查:列表行显示 4 色 StageBar + 置信度;详情打开显示泳道
- 业务概览:意图堆叠条 + 三列意图卡 + 地域进度条
- 技术洞察:KPI 含 count/delta + 包含图 + 三列 grid + 降级链路 NodeFlow

截图存为本 Task 证据(可选)。

- [ ] **Step 4: 记录 Real-Run 结果**

在本 Task 末尾记录:实际运行的命令、真实输出关键行(非 mock)、截图路径(如有)、字段存在确认。如果某步因环境不可用无法运行,如实标注 "未运行 — 环境 X 不可用,待部署后在 prod 验证",不伪造通过。

---

## Self-Review 记录

### Spec 覆盖核对(Phase 1 三页 + 组件库)

| Spec 要求 | 对应 Task | 状态 |
|-----------|----------|------|
| 1.1 后端 trace_map 补 confidence | Task 1 | ✅ |
| 1.1 前端 Conversation 接口补 trace_summary | Task 2 | ✅ |
| 1.1 列表行加 StageBar(4 色阶段比例条) | Task 14 Step 2 | ✅ |
| 1.1 列表行加置信度(低置信<0.6 标橙) | Task 14 Step 2 | ✅ |
| 1.1 详情面板 Trace 改横向泳道 5 阶段 | Task 14 Step 3(Task 13 改造组件) | ✅ |
| 1.1 Trace 顶部加 LanesBar | Task 14 Step 3 | ✅ |
| 1.1 多轮按钮标注类型 | Task 14 Step 4 | ✅ |
| 1.2 后端 geo 补 pct | Task 3 | ✅ |
| 1.2 后端 days 补 90d | Task 3 | ✅ |
| 1.2 服务总览卡加 StackedBar | Task 15 Step 3 | ✅ |
| 1.2 新建三列意图卡(IntentColumn) | Task 8 + Task 15 | ✅ |
| 1.2 地域分布加 ProgressBar | Task 7 + Task 15 | ✅ |
| 1.2 意图命名对齐(销售咨询/产品方案) | Task 15 Step 3 | ✅ |
| 1.2 off_topic/未识别意图不入三列卡 | Task 15 Step 3 | ✅ |
| 1.3 后端 KPI 补 count | Task 4 | ✅ |
| 1.3 后端 KPI 补 delta | Task 4 | ✅ |
| 1.3 异常分布补 pct | Task 4 | ✅ |
| 1.3 KPI 卡补 count + delta | Task 16 Step 2 | ✅ |
| 1.3 加 ContainmentDiagram | Task 12 + Task 16 | ✅ |
| 1.3 异常分布加彩色圆点 + 百分比 | Task 16 Step 4 | ✅ |
| 1.3 降级链路改 NodeFlow | Task 11 + Task 16 | ✅ |
| 组件库 StackedBar | Task 5 | ✅ |
| 组件库 MiniTrend | Task 6 | ✅ |
| 组件库 ProgressBar | Task 7 | ✅ |
| 组件库 IntentColumn | Task 8 | ✅ |
| 组件库 StageBar(既有复用) | Task 9 | ✅ |
| 组件库 TraceSwimlane(改造 TraceLanes) | Task 13 | ✅ |
| 组件库 LanesBar | Task 10 | ✅ |
| 组件库 NodeFlow | Task 11 | ✅ |
| 组件库 ContainmentDiagram | Task 12 | ✅ |
| 1.3 技术性能 tab 三列 grid3 并排 | Task 16 Step 5 | ✅(合并进 Task 16,避免与异常/降级改造分两步重复编辑同区域) |

### 说明

Task 18 原计划单独覆盖 grid3,但 self-review 发现 Task 16(异常圆点 + 降级 NodeFlow)与 Task 18(三列网格)编辑 Analytics.tsx 同一区域(L129-219),分两步会产生重复渲染/删除冲突。已合并:Task 16 Step 5 一次性把阶段表 + 异常分布 + 降级链路重构为 grid3 三列,异常列含圆点+pct,降级列含 NodeFlow。

---

## Phase 1 完成标准

- [ ] 后端 3 个测试文件全绿(`test_conversations.py` + `test_analytics_business.py` + `test_tech_perf.py`)
- [ ] 前端全量 vitest 全绿(15 个测试文件:9 既有 + 6 新组件测试;扩展的 3 个页面测试含 StackedBar/IntentColumn/StageBar 改造/TraceLanes 改造断言)
- [ ] `cd admin && npx tsc -b --noEmit` 无报错
- [ ] `cd admin && npm run build` 成功
- [ ] Task 18 Real-Run Gate:后端 import/启动冒烟通过 + 真实 API 响应含新字段(`confidence`/`geo.pct`/90d/`anomaly_count`/`anomaly_delta`/`anomalies.pct`);如环境不可用则如实报告
- [ ] 三页视觉对齐设计稿 B 方案(信息密度 + 叙事因果,样式允许合理偏差)
- [ ] 无第三方图表库引入(纯 Tailwind + 内联 SVG)
- [ ] 所有新组件 < 80 行,props 驱动,无内部状态