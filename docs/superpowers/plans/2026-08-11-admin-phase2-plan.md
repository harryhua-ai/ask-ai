# Admin 三页 Phase 2(聚合层)实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Phase 2 聚合层 — 三页(对话审查/业务概览/技术洞察)后端新增聚合查询 + 前端组件升级,补齐环比、标记点、Top3、双色条、缺口分类。终端目标 = implementation(测试通过的分支,不部署)。

**Architecture:** 后端在现有 `backend/api/admin/{conversations,business,tech,analytics}.py` 扩展聚合逻辑(无新表、无迁移,纯查询派生);前端在 `admin/src/components/observability/` 新增 `DualStageBar`/`DualTrendBar`/`ToggleFilter`/`GapTypeBadge` 4 个组件,升级三页消费新字段。复用 Phase 1 已建组件库(StackedBar/MiniTrend/ProgressBar/IntentColumn/StageBar/LanesBar/NodeFlow/ContainmentDiagram/TrendChart)。

**Tech Stack:** Python 3.12 + FastAPI + SQLAlchemy async + PostgreSQL(JSONB 查询);React 19 + TypeScript + Vite + Tailwind + @tanstack/react-query + vitest。

## Global Constraints

- **语言**:对话、回复、代码注释用中文简体。docstring 中文。
- **纯 Tailwind + 内联 SVG**,不引 recharts/chart.js/d3(Phase 1 约束延续)。
- **每个新组件 < 80 行**,props 驱动,无内部状态。
- **颜色用 CSS 变量**,复用 `--acc`/`--acc-t`/`--warn`/`--err`/`--ok`/`--t1`/`--t2`/`--t3`/`--bd`/`--panel`,不硬编码 hex。
- **不可变**:`Settings` 用 `@dataclass(frozen=True)`;前端用 spread 不可变更新。
- **测试库隔离**:后端测试必设 `TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test`(CLAUDE.md 踩坑)。
- **不碰**:`--reindex`、weaviate collection、源码挂载热更新、prod 部署。本计划纯本地实现。
- **格式**:Python `black` + `isort` + `ruff`,line-length=100。前端 Prettier + tsc。

---

## Analysis Gate Delta(Phase 2 spec vs 真实代码)

Phase 1 已落地(commit `0ea8bd3`..`794e23e`),Phase 2 在其基础上扩展。以下为 spec §2.1-2.3 假设与真实代码的差距,本计划据此调整:

| # | Spec 假设 | 真实代码 | 本计划处理 |
|---|---|---|---|
| D1 | 组件放 `components/viz/` | Phase 1 实际放在 `components/observability/`(已落地 9 组件) | Phase 2 新组件也放 `observability/`,保持一致,不新建 `viz/` |
| D2 | Phase 1 TrendChart 单段,Phase 2 改双段柱 | `TrendChart.tsx` 已是双段(`data-seg="p95"` 外柱 + `data-seg="p50"` 内柱,Phase 1 Task 10 落地) | Phase 2 Task 12 升级为独立 `DualTrendBar`:加告警基线虚线 + y 轴刻度 + 正常/超标着色;`TrendChart` 保留向后兼容或原地替换 |
| D3 | `markers.degraded` 从 `path_counts` 推断 | `path_counts` 在 `trace.stages.retrieve.path_counts = {hybrid, symbol, boost}`(`rag.py:238-241`);`tech.py:202-209` 已有降级推断(`symbol==0 && boost==0`→单路检索) | markers 推断复用 tech.py 同款逻辑:读最新 trace 的 `stages.retrieve.path_counts`,两路皆 0 → degraded |
| D4 | `miss_type` 加 reject/low 从 intent_tag 推断 | `analytics.py:98-118` 当前基于 `sources` 有无:召回空/召回不足。拒答对话(`is_answered=false`)通常 sources 空→已被"召回空"覆盖,无法区分 | Task 14 重新定义四态:`reject`(`is_answered=false`,拒答)/ `low`(answered 但 sources 非空且疑似低相关,Phase 2 用 trace confidence<0.6 作近似)/ `召回空`(answered 且 sources 空)/ `召回不足`(answered 且 sources 非空)。需关联 Trace 表读 confidence |
| D5 | 新端点 `hot-questions?intent=` | `business.py:140-156` 现有 `top_questions` 查 `QuestionCluster`(cluster_type=top),**无 intent 字段**,无法按意图过滤 | Task 7 新端点 `/business/hot-questions`:不查 QuestionCluster(无 intent),改查 Conversation 表按 `intent_tag` 过滤 + 按 question 文本 `GROUP BY` 聚合 Top3(未走 clustering,粗糙但满足"按意图的 Top3")。文档注明:精度升级留 Phase 3(接 clustering) |
| D6 | `stages` 补 `p50_pct`/`p95_pct` | `tech.py:216-223` `stage_result` 有 `p50`/`p95`/`normal_max`,无 pct | Task 10 在 stage_result 加 `p50_pct`(p50/最大P95) + `p95_pct`(p95/最大P95) |
| D7 | list 端点补 `markers` | `conversations.py:70-87` trace_map 已取最新 trace 的 type/stages/total_ms/confidence | Task 1 在 trace_map 构建时顺带推断 markers(retry/clarify/reject_short/degraded),注入 item |
| D8 | 4 个 toggle 筛选 | `conversations.py:19-32` 现有 channel/is_answered/feedback/intent_tag/q/date 过滤 | Task 5 新增 4 toggle:置信<0.6(后端无法高效过滤 JSONB confidence,改前端客户端过滤现有页内 items)/ 异常重试(后端加 `has_retry` 查询参数)/ 有反馈(feedback 非空,后端加)/ 触发澄清(trace type=clarify,后端加)。置信<0.6 客户端过滤的理由:confidence 在 trace JSONB,SQL 过滤需每行 JSON 解析,列表查询性能差;且列表已限 20 条,客户端过滤足够 |

**已知约束**(CLAUDE.md,影响数据可信度):
- Trace 降级/retry 目前是**推断版**(无专门字段落库,Phase 3 才修)。Phase 2 markers 的 degraded/retry 准确度受此限制 — spec §2.4 已明示"推断版",Phase 3 升级真实事件版时 API 契约不变。
- `QuestionCluster` 无 intent 字段 → hot-questions 按 intent 走 Conversation 直查(D5)。

---

## File Structure

### 后端(扩展,无新文件除非必要)

```
backend/api/admin/
├── conversations.py      # Task 1: trace_map 补 markers 推断;Task 5: 加 has_retry/has_feedback/has_clarify 查询参数
├── business.py           # Task 6: service 补 prev 环比;Task 7: 新端点 /hot-questions
├── tech.py               # Task 10: stage_result 补 p50_pct/p95_pct
└── analytics.py          # Task 14: coverage-gaps miss_type 四态重定义
```

### 前端

```
admin/src/
├── components/observability/
│   ├── DualStageBar.tsx      # Task 11(新): 双色水平条(浅 P50 + 深 P95 + 正常区间标注)
│   ├── DualTrendBar.tsx      # Task 12(新): 双段柱 + 告警基线虚线 + y 轴
│   ├── ToggleFilter.tsx      # Task 4(新): 单 toggle 按钮(active/inactive)
│   ├── GapTypeBadge.tsx      # Task 15(新): 缺口类型标签(拒答灰/召回空红/低相关橙/召回不足黄)
│   └── __tests__/
│       ├── DualStageBar.test.tsx
│       ├── DualTrendBar.test.tsx
│       ├── ToggleFilter.test.tsx
│       └── GapTypeBadge.test.tsx
├── pages/
│   ├── Conversations.tsx     # Task 5: 标记点 + 4 toggle 筛选栏
│   ├── BusinessOverview.tsx  # Task 8: 环比标签;Task 9: 三列意图卡填 Top3
│   └── Analytics.tsx         # Task 13: 阶段表用 DualStageBar;Task 12 Step 3: 趋势用 DualTrendBar;Task 16: 缺口标色
├── lib/api/
│   ├── businessOverview.ts   # Task 3: BusinessOverviewData.service 补 prev;fetchHotQuestions
│   ├── techInsight.ts        # Task 2: StagePercentile 补 p50_pct/p95_pct;ClusterItem miss_type 类型
│   └── conversations.ts(或 useConversations.ts)  # Task 3: ConversationFilters 补 has_retry/has_feedback/has_clarify;Conversation.markers 类型
└── types/api.ts              # Task 2: Conversation 接口补 markers
```

### 测试

```
tests/api/admin/
├── test_conversations.py     # Task 1+5: markers 推断 + 新查询参数
├── test_analytics_business.py # Task 6+7: prev 环比 + hot-questions
├── test_tech_perf.py         # Task 10: p50_pct/p95_pct
└── test_analytics.py         # Task 14: miss_type 四态
```

---

## Task 依赖与执行姿态

| Task | 标题 | 姿态 | 依赖 |
|---|---|---|---|
| 1 | 后端:conversations markers 推断 | serial_only(编辑 conversations.py + 测试) | 无 |
| 2 | 前端类型:markers + p50_pct + miss_type | parallel_safe(类型声明,独立) | 无 |
| 3 | 前端 API 客户端:filters + hot-questions + service.prev | parallel_safe | Task 2 |
| 4 | 组件:ToggleFilter | parallel_safe | 无 |
| 5 | 后端+前端:conversations 4 toggle 筛选 | serial_only(后端查询参数 + 前端栏,Task 1 数据) | Task 1, 3, 4 |
| 6 | 后端:business service prev 环比 | parallel_safe(独立查询) | 无 |
| 7 | 后端:hot-questions 端点 | parallel_safe(独立端点) | 无 |
| 8 | 前端:BusinessOverview 环比标签 | parallel_safe | Task 3, 6 |
| 9 | 前端:三列意图卡 Top3 | parallel_safe | Task 3, 7 |
| 10 | 后端:tech stage_result p50_pct/p95_pct | parallel_safe | 无 |
| 11 | 组件:DualStageBar | parallel_safe | 无 |
| 12 | 组件 + 页面:DualTrendBar + 替换 TrendChart | serial_only(新组件 + 页面替换同区域) | Task 10 |
| 13 | 前端:Analytics 阶段表用 DualStageBar | parallel_safe | Task 10, 11 |
| 14 | 后端:coverage-gaps miss_type 四态 | serial_only(改聚合逻辑,需关联 Trace) | 无 |
| 15 | 组件:GapTypeBadge | parallel_safe | 无 |
| 16 | 前端:Analytics 缺口标色 | parallel_safe | Task 14, 15 |
| 17 | 全量验证 | serial_only | 全部 |
| 18 | Real-Run Gate | serial_only | 17 |

**并行批次建议**(Tier 1 直接执行,但仍可逻辑分批):
- 批 A(后端独立扩展):Task 1, 6, 7, 10, 14(互不编辑同文件)
- 批 B(前端组件):Task 4, 11, 15
- 批 C(前端类型/API):Task 2, 3
- 批 D(前端页面消费):Task 5, 8, 9, 12, 13, 16
- 批 E:Task 17, 18

---

## Task 1: 后端 conversations list 补 markers 推断

**Files:**
- Modify: `backend/api/admin/conversations.py:70-105`
- Test: `tests/api/admin/test_conversations.py`

**Interfaces:**
- Produces: list 端点 item 新增 `markers: {retry: bool, clarify: bool, reject_short: bool, degraded: bool}` 字段;`markers` 为 null 当无 trace

- [ ] **Step 1: 写失败测试**

在 `tests/api/admin/test_conversations.py` 末尾加:

```python
@pytest.mark.asyncio
async def test_list_conversations_markers_inferred(client, admin_token, db_session):
    """markers 从最新 trace 推断:retry/clarify/reject_short/degraded。"""
    conv_id = uuid.uuid4()
    conv = Conversation(
        id=conv_id,
        question="测试 markers",
        answer="答",
        is_answered=True,
    )
    db_session.add(conv)
    # 最新 trace:clarify 类型 + retrieve 降级(path_counts 全 0)
    trace = Trace(
        conversation_id=conv_id,
        turn_index=0,
        type="clarify",
        stages={
            "intent": {"ms": 10, "category": "product"},
            "rewrite": {"ms": 5},
            "retrieve": {"ms": 100, "path_counts": {"hybrid": 5, "symbol": 0, "boost": 0}},
            "rerank": {"ms": 50, "retry_count": 1},
            "generate": {"ms": 200},
            "output": {"ms": 1},
        },
        total_ms=366,
        confidence=0.55,
    )
    db_session.add(trace)
    await db_session.commit()

    resp = await client.get(
        "/api/admin/conversations?size=5",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    target = [i for i in items if i["id"] == str(conv_id)][0]
    m = target["trace_summary"]["markers"]
    assert m["clarify"] is True          # trace type = clarify
    assert m["degraded"] is True         # symbol==0 and boost==0
    assert m["retry"] is True            # rerank.retry_count=1
    assert m["reject_short"] is False    # type != reject_short
```

- [ ] **Step 2: 运行测试验证失败**

Run: `TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test uv run pytest tests/api/admin/test_conversations.py::test_list_conversations_markers_inferred -xvs`
Expected: FAIL(KeyError 'markers' 或 AttributeError)

- [ ] **Step 3: 实现 markers 推断**

修改 `backend/api/admin/conversations.py` 的 trace_map 构建循环(L80-87 区域),在写入 trace_map 时顺带推断 markers:

```python
def _infer_markers(trace_type: str, stages: dict) -> dict:
    """从 trace type + stages 推断标记(retry/clarify/reject_short/degraded)。

    推断版(spec §2.4):Phase 3 升级为真实事件字段时 API 契约不变。
    """
    retry = any(
        isinstance(sd, dict) and (sd.get("error") or sd.get("retry_count"))
        for sd in stages.values()
    )
    retrieve_sd = stages.get("retrieve", {})
    path_counts = retrieve_sd.get("path_counts", {}) if isinstance(retrieve_sd, dict) else {}
    symbol_count = path_counts.get("symbol", 0) if isinstance(path_counts, dict) else 0
    boost_count = path_counts.get("boost", 0) if isinstance(path_counts, dict) else 0
    degraded = symbol_count == 0 and boost_count == 0
    return {
        "retry": retry,
        "clarify": trace_type == "clarify",
        "reject_short": trace_type == "reject_short",
        "degraded": degraded,
    }
```

在 trace_map 写入处补 markers:

```python
for t in trace_rows:
    if t.conversation_id not in trace_map:
        stages = t.stages or {}
        trace_map[t.conversation_id] = {
            "type": t.type,
            "stages": stages,
            "total_ms": t.total_ms,
            "confidence": t.confidence,
            "markers": _infer_markers(t.type or "rag", stages),
        }
```

- [ ] **Step 4: 运行测试验证通过**

Run: `TEST_DATABASE_URL=... uv run pytest tests/api/admin/test_conversations.py::test_list_conversations_markers_inferred -xvs`
Expected: PASS

- [ ] **Step 5: 跑全量 conversations 测试确认无回归**

Run: `TEST_DATABASE_URL=... uv run pytest tests/api/admin/test_conversations.py -q`
Expected: 全绿(既有 + 新测试)

- [ ] **Step 6: 提交**

```bash
git add backend/api/admin/conversations.py tests/api/admin/test_conversations.py
git commit -m "feat(admin): conversations list 补 markers 推断(retry/clarify/reject_short/degraded)"
```

---

## Task 2: 前端类型声明(markers + p50_pct + miss_type)

**Files:**
- Modify: `admin/src/types/api.ts:121-135`(Conversation 接口)
- Modify: `admin/src/lib/api/techInsight.ts:19-23`(StagePercentile)+ ClusterItem miss_type
- Modify: `admin/src/lib/api/businessOverview.ts`(BusinessOverviewData.service 补 prev)

**Interfaces:**
- Produces: `Conversation.trace_summary.markers`、`StagePercentile.p50_pct/p95_pct`、`BusinessOverviewData.service.prev_total/delta_pct`

- [ ] **Step 1: types/api.ts Conversation 补 markers**

读 `admin/src/types/api.ts` 的 TraceSummary 接口(约 L121-135),补 markers 字段:

```typescript
export interface TraceMarkers {
  retry: boolean;
  clarify: boolean;
  reject_short: boolean;
  degraded: boolean;
}

export interface TraceSummary {
  type: string;
  stages: Record<string, Record<string, unknown>>;
  total_ms: number | null;
  confidence: number | null;
  markers?: TraceMarkers | null;
}
```

(保留既有字段名,仅加 markers。如 TraceSummary 已有其他字段定义,在末尾加 markers 行。)

- [ ] **Step 2: techInsight.ts StagePercentile 补 pct 字段**

```typescript
export interface StagePercentile {
  p50: number;
  p95: number;
  normal_max: number;
  p50_pct?: number;  // Phase 2: p50 占最大 P95 的比例
  p95_pct?: number;  // Phase 2: p95 占最大 P95 的比例
}
```

并在 ClusterList/ClusterItem 接口补 `miss_type?: string`(若已有则跳过)。

- [ ] **Step 3: businessOverview.ts service 补 prev**

```typescript
export interface BusinessOverviewData {
  service: {
    total: number;
    intent_dist: IntentDist;
    unknown_intent_count: number;
    north_star: number;
    satisfaction: number | null;
    up_count: number;
    down_count: number;
    prev_total?: number;       // Phase 2: 上一同等长度时间窗总量
    delta_pct?: number;        // Phase 2: 环比百分比
  };
  // ... 其余不变
}
```

- [ ] **Step 4: tsc 验证**

Run: `cd admin && npx tsc --noEmit 2>&1 | grep -v TS6310 | head -20`
Expected: 无新增报错(TS6310 是 pre-existing,非本计划引入)

- [ ] **Step 5: 提交**

```bash
git add admin/src/types/api.ts admin/src/lib/api/techInsight.ts admin/src/lib/api/businessOverview.ts
git commit -m "feat(admin): 前端类型补 markers/p50_pct/miss_type/service.prev(Phase 2)"
```

---

## Task 3: 前端 API 客户端(filters + hot-questions)

**Files:**
- Modify: `admin/src/hooks/useConversations.ts:5-14`(ConversationFilters)
- Modify: `admin/src/lib/api/businessOverview.ts`(加 fetchHotQuestions)

- [ ] **Step 1: ConversationFilters 补 3 个布尔筛选**

```typescript
export interface ConversationFilters {
  channel?: string;
  is_answered?: boolean;
  feedback?: string;
  intent_tag?: string;
  q?: string;
  date_from?: string;
  date_to?: string;
  page?: number;
  has_retry?: boolean;      // Phase 2: 异常重试
  has_feedback?: boolean;   // Phase 2: 有反馈
  has_clarify?: boolean;    // Phase 2: 触发澄清
}
```

- [ ] **Step 2: businessOverview.ts 加 fetchHotQuestions**

```typescript
export function fetchHotQuestions(
  intent: string,
  range: string = "7d",
): Promise<{ items: TopQuestionItem[]; intent: string }> {
  return apiFetch(`/business/hot-questions?intent=${intent}&range=${range}`);
}
```

- [ ] **Step 3: tsc 验证**

Run: `cd admin && npx tsc --noEmit 2>&1 | grep -v TS6310 | head`
Expected: 无新增报错

- [ ] **Step 4: 提交**

```bash
git add admin/src/hooks/useConversations.ts admin/src/lib/api/businessOverview.ts
git commit -m "feat(admin): API 客户端补 conversation filters + hot-questions(Phase 2)"
```

---

## Task 4: 组件 ToggleFilter

**Files:**
- Create: `admin/src/components/observability/ToggleFilter.tsx`
- Test: `admin/src/components/observability/__tests__/ToggleFilter.test.tsx`

- [ ] **Step 1: 写失败测试**

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import ToggleFilter from "@/components/observability/ToggleFilter";

describe("ToggleFilter", () => {
  it("active 态有 data-active=true 且点击触发 onToggle", () => {
    const onToggle = vi.fn();
    render(<ToggleFilter label="异常重试" active={true} onToggle={onToggle} />);
    const btn = screen.getByText("异常重试").closest("button")!;
    expect(btn).toHaveAttribute("data-active", "true");
    fireEvent.click(btn);
    expect(onToggle).toHaveBeenCalled();
  });

  it("inactive 态 data-active=false", () => {
    render(<ToggleFilter label="有反馈" active={false} onToggle={() => {}} />);
    expect(
      screen.getByText("有反馈").closest("button"),
    ).toHaveAttribute("data-active", "false");
  });
});
```

- [ ] **Step 2: 运行验证失败**

Run: `cd admin && npx vitest run src/components/observability/__tests__/ToggleFilter.test.tsx`
Expected: FAIL(模块不存在)

- [ ] **Step 3: 实现 ToggleFilter**

```tsx
/** 单 toggle 按钮(active/inactive 两态,Phase 2 快速筛选栏用)。 */
export default function ToggleFilter({
  label,
  active,
  onToggle,
  color = "var(--acc)",
}: {
  label: string;
  active: boolean;
  onToggle: () => void;
  color?: string;
}) {
  return (
    <button
      type="button"
      data-active={active}
      data-toggle={label}
      onClick={onToggle}
      className="h-8 rounded-md border px-3 text-[12px] transition"
      style={{
        background: active ? color : "var(--panel)",
        borderColor: active ? color : "var(--bd)",
        color: active ? "#fff" : "var(--t2)",
      }}
    >
      {label}
    </button>
  );
}
```

- [ ] **Step 4: 运行验证通过**

Run: `cd admin && npx vitest run src/components/observability/__tests__/ToggleFilter.test.tsx`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add admin/src/components/observability/ToggleFilter.tsx admin/src/components/observability/__tests__/ToggleFilter.test.tsx
git commit -m "feat(admin): ToggleFilter 组件(Phase 2 快速筛选)"
```

---

## Task 5: 后端 conversations toggle 查询参数 + 前端筛选栏

**Files:**
- Modify: `backend/api/admin/conversations.py:19-62`(加 3 查询参数 + 过滤)
- Modify: `admin/src/pages/Conversations.tsx:69-79, 135-193`(筛选栏 + 客户端置信过滤)
- Test: `tests/api/admin/test_conversations.py`

**Interfaces:**
- Consumes: Task 1 markers(Task 5 的 `has_retry`/`has_clarify` 在后端基于 trace 推断,与 markers 同源逻辑)
- Produces: list 端点支持 `has_retry`/`has_feedback`/`has_clarify` 查询参数

> **设计说明(D8):** 置信<0.6 toggle 走**前端客户端过滤**(列表已限 20 条/页,trace confidence 在 JSONB,SQL 过滤需每行 JSON 解析,性能差)。其余 3 toggle 走后端查询参数(数据库高效)。

- [ ] **Step 1: 后端写失败测试**

```python
@pytest.mark.asyncio
async def test_list_conversations_has_clarify_filter(client, admin_token, db_session):
    """has_clarify=true 只返回最新 trace type=clarify 的对话。"""
    # 对话 A:最新 trace clarify
    conv_a = Conversation(id=uuid.uuid4(), question="A", answer="a", is_answered=True)
    conv_b = Conversation(id=uuid.uuid4(), question="B", answer="b", is_answered=True)
    db_session.add_all([conv_a, conv_b])
    db_session.add(Trace(
        conversation_id=conv_a.id, turn_index=0, type="clarify",
        stages={"intent": {"ms": 5}}, total_ms=5,
    ))
    db_session.add(Trace(
        conversation_id=conv_b.id, turn_index=0, type="rag",
        stages={"intent": {"ms": 5}}, total_ms=5,
    ))
    await db_session.commit()

    resp = await client.get(
        "/api/admin/conversations?has_clarify=true",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    ids = [i["id"] for i in resp.json()["items"]]
    assert str(conv_a.id) in ids
    assert str(conv_b.id) not in ids
```

- [ ] **Step 2: 运行验证失败**

Run: `TEST_DATABASE_URL=... uv run pytest tests/api/admin/test_conversations.py::test_list_conversations_has_clarify_filter -xvs`
Expected: FAIL(参数未识别 / 返回所有)

- [ ] **Step 3: 后端实现 has_clarify/has_retry/has_feedback 过滤**

在 `conversations.py` list 端点加查询参数 + 过滤逻辑。由于 has_clarify/has_retry 需要 trace 关联(Conversation 表无这些字段),用半连接子查询:

```python
from sqlalchemy import exists, select as sa_select

@router.get("")
async def list_conversations(
    _: ViewerDep,
    request: Request,
    # ... 既有参数 ...
    has_retry: bool | None = Query(default=None),
    has_feedback: bool | None = Query(default=None),
    has_clarify: bool | None = Query(default=None),
) -> dict[str, Any]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        stmt = select(Conversation)
        count_q = select(func.count()).select_from(Conversation)
        # ... 既有过滤 ...

        if has_feedback is True:
            stmt = stmt.where(Conversation.feedback.is_not(None))
            count_q = count_q.where(Conversation.feedback.is_not(None))

        # trace 派生过滤:用最新 trace(turn_index 最大)
        if has_clarify is not None or has_retry is not None:
            # 子查询:每 conversation 最新 trace 的 type + stages
            latest_trace_subq = (
                sa_select(
                    Trace.conversation_id,
                    Trace.type,
                    Trace.stages,
                    func.max(Trace.turn_index).over(
                        partition_by=Trace.conversation_id
                    ).label("max_turn"),
                )
            ).subquery()
            # 简化:直接用 EXISTS 关联最新 trace
            if has_clarify is True:
                stmt = stmt.where(
                    exists().where(
                        Trace.conversation_id == Conversation.id,
                        Trace.type == "clarify",
                    )
                )
                count_q = count_q.where(
                    exists().where(
                        Trace.conversation_id == Conversation.id,
                        Trace.type == "clarify",
                    )
                )
            if has_retry is True:
                # retry: stages 任一段含 error/retry_count(JSONB 查询)
                stmt = stmt.where(
                    exists().where(
                        Trace.conversation_id == Conversation.id,
                        Trace.stages.op("->>")("any").is_not(None),  # 占位,实际见下
                    )
                )
                # JSONB retry 检测较复杂,改用 retrieve.rerank.generate 段的 retry_count OR error
                # 简化:stages 文本包含 '"retry_count"' 或 '"error"'(粗糙但够过滤)
                stmt = stmt.where(
                    exists().where(
                        Trace.conversation_id == Conversation.id,
                        Trace.stages.cast(Text).like('%"retry_count":%'),
                    )
                )
                count_q = count_q.where(
                    exists().where(
                        Trace.conversation_id == Conversation.id,
                        Trace.stages.cast(Text).like('%"retry_count":%'),
                    )
                )
        # ... 其余既有逻辑 ...
```

> **注意:** `has_retry` 用 `stages.cast(Text).like('%"retry_count":%')` 是粗糙推断(与 markers/retry 同源:stages 任一段含 retry_count/error)。若性能成问题,Phase 3 落库后改读真实字段。测试需覆盖。

- [ ] **Step 4: 运行后端测试通过**

Run: `TEST_DATABASE_URL=... uv run pytest tests/api/admin/test_conversations.py -q`
Expected: 全绿

- [ ] **Step 5: 前端 Conversations.tsx 加筛选栏**

在 `admin/src/pages/Conversations.tsx` 过滤栏(L135-193 区域)末尾加 4 个 ToggleFilter + 客户端置信过滤:

```tsx
import ToggleFilter from "@/components/observability/ToggleFilter";

// 在组件内,与 filters 同级:
const [toggles, setToggles] = useState<{
  lowConf: boolean;
  retry: boolean;
  feedback: boolean;
  clarify: boolean;
}>({ lowConf: false, retry: false, feedback: false, clarify: false });

// 同步 toggle 到 filters(后端查询参数)
useEffect(() => {
  setFilters((f) => ({
    ...f,
    has_retry: toggles.retry || undefined,
    has_feedback: toggles.feedback || undefined,
    has_clarify: toggles.clarify || undefined,
    page: 1,
  }));
}, [toggles.retry, toggles.feedback, toggles.clarify]);

// 置信<0.6 客户端过滤(D8)
const visibleItems = toggles.lowConf
  ? (data?.items ?? []).filter(
      (c) => c.trace_summary?.confidence != null && c.trace_summary.confidence < 0.6,
    )
  : (data?.items ?? []);
```

在过滤栏 JSX 末尾加:

```tsx
<div className="flex gap-2 flex-wrap" data-toggle-bar>
  <ToggleFilter
    label="置信<0.6"
    active={toggles.lowConf}
    onToggle={() => setToggles((t) => ({ ...t, lowConf: !t.lowConf }))}
    color="var(--warn)"
  />
  <ToggleFilter
    label="异常重试"
    active={toggles.retry}
    onToggle={() => setToggles((t) => ({ ...t, retry: !t.retry }))}
    color="var(--err)"
  />
  <ToggleFilter
    label="有反馈"
    active={toggles.feedback}
    onToggle={() => setToggles((t) => ({ ...t, feedback: !t.feedback }))}
    color="var(--acc)"
  />
  <ToggleFilter
    label="触发澄清"
    active={toggles.clarify}
    onToggle={() => setToggles((t) => ({ ...t, clarify: !t.clarify }))}
    color="var(--ok)"
  />
</div>
```

把列表渲染从 `data?.items.map(...)` 改为 `visibleItems.map(...)`。

- [ ] **Step 6: 前端加标记点圆点**

在列表行(conv.intent_tag Badge 旁,L215-219 区域)加 markers 圆点:

```tsx
{conv.trace_summary?.markers && (
  <div className="flex items-center gap-1" data-markers>
    {conv.trace_summary.markers.retry && (
      <span data-marker="retry" title="异常重试"
        className="inline-block w-2 h-2 rounded-full" style={{ background: "var(--err)" }} />
    )}
    {conv.trace_summary.markers.clarify && (
      <span data-marker="clarify" title="触发澄清"
        className="inline-block w-2 h-2 rounded-full" style={{ background: "var(--warn)" }} />
    )}
    {conv.trace_summary.markers.reject_short && (
      <span data-marker="reject_short" title="短路拒答"
        className="inline-block w-2 h-2 rounded-full" style={{ background: "var(--t3)" }} />
    )}
    {conv.trace_summary.markers.degraded && (
      <span data-marker="degraded" title="检索降级"
        className="inline-block w-2 h-2 rounded-full" style={{ background: "var(--acc)" }} />
    )}
  </div>
)}
```

- [ ] **Step 7: 前端测试验证(更新 Conversations 既有测试或新增)**

确认 `admin/tests/` 下 Conversations 测试对新 toggle + markers 不报错。如无 Conversations.test.tsx,跑全量确认无回归。

Run: `cd admin && npx vitest run --exclude='**/.claude/**' 2>&1 | tail -20`
Expected: 全绿

- [ ] **Step 8: tsc + 提交**

Run: `cd admin && npx tsc --noEmit 2>&1 | grep -v TS6310 | head`
Expected: 无新增报错

```bash
git add backend/api/admin/conversations.py admin/src/pages/Conversations.tsx tests/api/admin/test_conversations.py
git commit -m "feat(admin): conversations 4 toggle 筛选 + markers 圆点(Phase 2)"
```

---

## Task 6: 后端 business service prev 环比

**Files:**
- Modify: `backend/api/admin/business.py:59-67, 241-250`
- Test: `tests/api/admin/test_analytics_business.py`

- [ ] **Step 1: 写失败测试**

```python
@pytest.mark.asyncio
async def test_business_overview_prev_total_delta(client, admin_token, db_session):
    """service.prev_total/delta_pct = 上一同等长度时间窗的 total + 环比。"""
    now = datetime.now(UTC)
    # 本窗(最近 7d):3 条
    for i in range(3):
        db_session.add(Conversation(
            question=f"本窗{i}", answer="a", is_answered=True,
            created_at=now - timedelta(days=1),
        ))
    # 上窗(7-14d 前):2 条
    for i in range(2):
        db_session.add(Conversation(
            question=f"上窗{i}", answer="a", is_answered=True,
            created_at=now - timedelta(days=10),
        ))
    await db_session.commit()

    resp = await client.get(
        "/api/admin/business/overview?range=7d",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    svc = resp.json()["service"]
    assert svc["total"] == 3
    assert svc["prev_total"] == 2
    # delta_pct = (3-2)/2 * 100 = 50.0
    assert svc["delta_pct"] == 50.0
```

- [ ] **Step 2: 运行验证失败**

Run: `TEST_DATABASE_URL=... uv run pytest tests/api/admin/test_analytics_business.py::test_business_overview_prev_total_delta -xvs`
Expected: FAIL(KeyError prev_total)

- [ ] **Step 3: 实现环比查询**

在 `business.py` business_overview 函数内,`total` 查询后加上一时间窗查询:

```python
# 上一同等长度时间窗(环比)
prev_end = start
prev_start = start - timedelta(days=days)
prev_total_q = (
    select(func.count())
    .select_from(Conversation)
    .where(Conversation.created_at >= prev_start, Conversation.created_at < prev_end)
)
prev_total = (await session.execute(prev_total_q)).scalar() or 0
delta_pct = round((total - prev_total) / prev_total * 100, 1) if prev_total else 0.0
```

> **注意 date_from/date_to 自定义范围:** 当用户传 from/to 时,days 从 (end-start) 推导:`days = (end - start).days or 7`。需在 prev_start 计算前补此推导。

在 return 的 service 块加:

```python
"service": {
    "total": total,
    # ... 既有字段 ...
    "prev_total": prev_total,
    "delta_pct": delta_pct,
},
```

- [ ] **Step 4: 运行测试通过**

Run: `TEST_DATABASE_URL=... uv run pytest tests/api/admin/test_analytics_business.py -q`
Expected: 全绿

- [ ] **Step 5: 提交**

```bash
git add backend/api/admin/business.py tests/api/admin/test_analytics_business.py
git commit -m "feat(admin): business service 补 prev_total/delta_pct 环比(Phase 2)"
```

---

## Task 7: 后端 hot-questions 端点

**Files:**
- Modify: `backend/api/admin/business.py`(新端点)
- Test: `tests/api/admin/test_analytics_business.py`

> **设计(D5):** QuestionCluster 无 intent 字段,新端点查 Conversation 按 intent_tag 过滤 + 按 question 文本 GROUP BY 取 Top3。粗糙但满足"按意图 Top3";精度升级留 Phase 3。

- [ ] **Step 1: 写失败测试**

```python
@pytest.mark.asyncio
async def test_hot_questions_by_intent(client, admin_token, db_session):
    """按 intent 过滤的 Top3 问题(按 question 文本聚合)。"""
    now = datetime.now(UTC)
    # commercial:3 条,其中 "价格" 问 2 次
    for q in ["NE503 价格", "NE503 价格", "NE301 经销商"]:
        db_session.add(Conversation(
            question=q, answer="a", is_answered=True,
            intent_tag="commercial", created_at=now - timedelta(days=1),
        ))
    # product:1 条(不应出现在 commercial 结果)
    db_session.add(Conversation(
        question="SDK 接入", answer="a", is_answered=True,
        intent_tag="product", created_at=now - timedelta(days=1),
    ))
    await db_session.commit()

    resp = await client.get(
        "/api/admin/business/hot-questions?intent=commercial&range=7d",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) <= 3
    top = items[0]
    assert top["question"] == "NE503 价格"
    assert top["count"] == 2
    assert all(i["question"] != "SDK 接入" for i in items)  # 不含 product
```

- [ ] **Step 2: 运行验证失败**

Run: `TEST_DATABASE_URL=... uv run pytest tests/api/admin/test_analytics_business.py::test_hot_questions_by_intent -xvs`
Expected: FAIL(404 端点不存在)

- [ ] **Step 3: 实现端点**

在 `business.py` 加:

```python
@router.get("/hot-questions")
async def hot_questions(
    _: ViewerDep,
    request: Request,
    intent: str = Query(..., pattern="^(commercial|product|support|off_topic)$"),
    range: str = Query(default="7d"),
) -> dict[str, Any]:
    """按意图过滤的 Top3 问题(Phase 2 推断版:按 question 文本聚合)。

    Phase 3 升级:接 clustering 精度更高。当前按精确 question GROUP BY。
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    days = {"today": 1, "7d": 7, "30d": 30, "90d": 90}.get(range, 7)
    end = datetime.now(UTC)
    start = end - timedelta(days=days)

    async with factory() as session:
        q = (
            select(
                Conversation.question,
                func.count().label("cnt"),
            )
            .where(
                Conversation.created_at >= start,
                Conversation.created_at <= end,
                Conversation.intent_tag == intent,
            )
            .group_by(Conversation.question)
            .order_by(func.count().desc())
            .limit(3)
        )
        rows = (await session.execute(q)).all()

    return {
        "items": [{"question": r.question, "count": r.cnt} for r in rows],
        "intent": intent,
    }
```

- [ ] **Step 4: 运行测试通过**

Run: `TEST_DATABASE_URL=... uv run pytest tests/api/admin/test_analytics_business.py -q`
Expected: 全绿

- [ ] **Step 5: 提交**

```bash
git add backend/api/admin/business.py tests/api/admin/test_analytics_business.py
git commit -m "feat(admin): business/hot-questions 按意图过滤 Top3 端点(Phase 2)"
```

---

## Task 8: 前端 BusinessOverview 环比标签

**Files:**
- Modify: `admin/src/pages/BusinessOverview.tsx:68-90`(KPI 行 总服务客户 卡)

- [ ] **Step 1: 总服务客户 KpiCard 加 delta**

在 BusinessOverview.tsx 的"总服务客户"KpiCard(L68-69 区域),补 delta prop:

```tsx
<KpiCard
  label="总服务客户"
  value={data.service.total}
  delta={
    data.service.prev_total != null && data.service.prev_total > 0
      ? {
          value: data.service.delta_pct ?? 0,
          dir: (data.service.delta_pct ?? 0) >= 0 ? "up" : "down",
        }
      : undefined
  }
/>
```

> **注意:** 确认 KpiCard 的 delta prop 签名(Phase 1 已有)。读 `admin/src/components/observability/KpiCard.tsx` 确认 `{value: number; dir: "up"|"down"}` 格式。

- [ ] **Step 2: 更新 BusinessOverview 测试**

`admin/tests/BusinessOverview.test.tsx` 的 mock 数据补 `prev_total`/`delta_pct`:

```tsx
service: {
  total: 120,
  // ... 既有 ...
  prev_total: 100,
  delta_pct: 20.0,
},
```

加测试断言环比显示:

```tsx
it("总服务客户显示环比 delta", async () => {
  renderWithProviders(<BusinessOverview />);
  await waitFor(() => {
    expect(screen.getByText(/20|↑/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: 运行测试通过**

Run: `cd admin && npx vitest run src/pages/__tests__/BusinessOverview.test.tsx admin/tests/BusinessOverview.test.tsx 2>/dev/null; npx vitest run --exclude='**/.claude/**' tests/BusinessOverview.test.tsx 2>&1 | tail -20`
Expected: 全绿

- [ ] **Step 4: 提交**

```bash
git add admin/src/pages/BusinessOverview.tsx admin/tests/BusinessOverview.test.tsx
git commit -m "feat(admin): 总服务客户 KPI 加环比标签(Phase 2)"
```

---

## Task 9: 前端三列意图卡填 Top3

**Files:**
- Modify: `admin/src/components/observability/IntentColumn.tsx`(加 topQuestions prop)
- Modify: `admin/src/pages/BusinessOverview.tsx`(传 Top3 数据)

- [ ] **Step 1: IntentColumn 加 topQuestions prop**

读 IntentColumn.tsx,加可选 prop:

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
  topQuestions,
}: {
  name: string;
  count: number;
  pct: number;
  trend: number[];
  drillTo: string;
  color?: string;
  topQuestions?: { question: string; count: number }[];
}) {
  return (
    <Link
      to={drillTo}
      data-intent-column={name}
      className="block rounded-lg border p-3 hover:opacity-80 transition"
      style={{ background: "var(--panel)", borderColor: "var(--bd)" }}
    >
      <div className="flex items-center justify-between">
        <span className="text-[14px] font-medium text-[var(--t1)]">{name}</span>
        <span className="text-[12px] text-[var(--t3)]">{pct}%</span>
      </div>
      <div className="text-2xl font-semibold text-[var(--t1)] mt-1">{count}</div>
      <div className="mt-2">
        <MiniTrend data={trend} color={color} />
      </div>
      {topQuestions && topQuestions.length > 0 && (
        <div className="mt-2 space-y-0.5" data-top-questions>
          {topQuestions.map((q, i) => (
            <div key={i} className="flex justify-between text-[12px]">
              <span className="truncate flex-1 mr-2">{q.question}</span>
              <span className="text-[var(--t3)]">{q.count}</span>
            </div>
          ))}
        </div>
      )}
    </Link>
  );
}
```

- [ ] **Step 2: BusinessOverview 拉 Top3 并传入**

在 BusinessOverview.tsx,为每个意图拉 hot-questions:

```tsx
import { fetchHotQuestions } from "@/lib/api/businessOverview";

// 组件内:
const commercialHot = useQuery({
  queryKey: ["hot-questions", "commercial", timeRange.range],
  queryFn: () => fetchHotQuestions("commercial", timeRange.range ?? "7d"),
});
const productHot = useQuery({
  queryKey: ["hot-questions", "product", timeRange.range],
  queryFn: () => fetchHotQuestions("product", timeRange.range ?? "7d"),
});
const supportHot = useQuery({
  queryKey: ["hot-questions", "support", timeRange.range],
  queryFn: () => fetchHotQuestions("support", timeRange.range ?? "7d"),
});

const hotMap: Record<string, { question: string; count: number }[] | undefined> = {
  commercial: commercialHot.data?.items,
  product: productHot.data?.items,
  support: supportHot.data?.items,
};
```

在三列 IntentColumn 渲染处(L115-124 区域),补 topQuestions:

```tsx
<IntentColumn
  key={intent}
  name={INTENT_LABELS[intent]}
  count={data.service.intent_dist[intent]}
  pct={Math.round((data.service.intent_dist[intent] / total) * 100)}
  trend={trend}
  drillTo={`/conversations?intent=${intent}`}
  color={INTENT_COLORS[intent]}
  topQuestions={hotMap[intent]}
/>
```

- [ ] **Step 3: 更新 BusinessOverview 测试**

在 BusinessOverview.test.tsx 的 vi.mock 加 `fetchHotQuestions` mock:

```tsx
vi.mock("@/lib/api/businessOverview", () => ({
  fetchBusinessOverview: vi.fn().mockResolvedValue({ /* 既有 */ }),
  fetchBusinessOverviewRange: vi.fn().mockResolvedValue({ /* 既有 */ }),
  refreshBusinessSignals: vi.fn().mockResolvedValue({ scene_count: 0, requirement_count: 0 }),
  fetchHotQuestions: vi.fn().mockResolvedValue({
    items: [{ question: "NE503 价格", count: 5 }],
    intent: "commercial",
  }),
}));
```

加测试断言三列意图卡含 Top 问题:

```tsx
it("三列意图卡含热门问题 Top3", async () => {
  renderWithProviders(<BusinessOverview />);
  await waitFor(() => {
    const cols = document.querySelectorAll("[data-intent-column]");
    expect(cols.length).toBe(3);
    // 至少 commercial 列含 top question(fetchHotQuestions mock 返回)
    expect(screen.getByText("NE503 价格")).toBeInTheDocument();
  });
});
```

- [ ] **Step 4: 运行测试通过**

Run: `cd admin && npx vitest run tests/BusinessOverview.test.tsx`
Expected: 全绿

- [ ] **Step 5: 提交**

```bash
git add admin/src/components/observability/IntentColumn.tsx admin/src/pages/BusinessOverview.tsx admin/tests/BusinessOverview.test.tsx
git commit -m "feat(admin): 三列意图卡填热门问题 Top3(Phase 2)"
```

---

## Task 10: 后端 tech stage_result 补 p50_pct/p95_pct

**Files:**
- Modify: `backend/api/admin/tech.py:216-223, 133`(stage_result + 空态)
- Test: `tests/api/admin/test_tech_perf.py`

- [ ] **Step 1: 写失败测试**

```python
@pytest.mark.asyncio
async def test_tech_perf_stage_pct(client, admin_token, db_session):
    """stages 各段含 p50_pct/p95_pct(相对最大 P95 的比例)。"""
    now = datetime.now(UTC)
    for ms_gen, ms_ret, ms_rer in [(100, 200, 50), (300, 400, 150)]:
        db_session.add(Trace(
            conversation_id=uuid.uuid4(), turn_index=0, type="rag",
            stages={
                "intent": {"ms": 10}, "rewrite": {"ms": 5},
                "retrieve": {"ms": ms_ret}, "rerank": {"ms": ms_rer},
                "generate": {"ms": ms_gen}, "output": {"ms": 1},
            },
            total_ms=ms_gen + ms_ret + ms_rer + 16,
            created_at=now - timedelta(days=1),
        ))
    await db_session.commit()

    resp = await client.get(
        "/api/admin/tech/performance?range=7d",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    stages = resp.json()["stages"]
    # generate P95 = 300(两值线性插值 0.95 近似),max P95 = max 各段 P95
    max_p95 = max(s["p95"] for s in stages.values())
    for sname, sd in stages.items():
        assert "p50_pct" in sd
        assert "p95_pct" in sd
        if max_p95 > 0:
            assert abs(sd["p95_pct"] - round(sd["p95"] / max_p95 * 100, 1)) < 0.5
```

- [ ] **Step 2: 运行验证失败**

Run: `TEST_DATABASE_URL=... uv run pytest tests/api/admin/test_tech_perf.py::test_tech_perf_stage_pct -xvs`
Expected: FAIL(KeyError p50_pct)

- [ ] **Step 3: 实现 pct 计算**

在 `tech.py` 的 stage_result 构建处(L216-223)改造:先收集所有 p95,算 max,再补 pct:

```python
# 阶段 P50/P95 + pct(相对最大 P95)
stage_result: dict[str, dict[str, Any]] = {}
for sname in STAGE_NAMES:
    vals = sorted(stage_ms[sname])
    stage_result[sname] = {
        "p50": int(_percentile(vals, 0.50)) if vals else 0,
        "p95": int(_percentile(vals, 0.95)) if vals else 0,
        "normal_max": NORMAL_MAX.get(sname, 0),
    }
# 补 pct:相对各段最大 P95
max_p95 = max((s["p95"] for s in stage_result.values()), default=0)
for sname in STAGE_NAMES:
    sd = stage_result[sname]
    sd["p50_pct"] = round(sd["p50"] / max_p95 * 100, 1) if max_p95 else 0.0
    sd["p95_pct"] = round(sd["p95"] / max_p95 * 100, 1) if max_p95 else 0.0
```

空态(L132-134)也补 p50_pct/p95_pct:

```python
"stages": {
    s: {
        "p50": 0, "p95": 0, "normal_max": NORMAL_MAX.get(s, 0),
        "p50_pct": 0.0, "p95_pct": 0.0,
    } for s in STAGE_NAMES
},
```

- [ ] **Step 4: 运行测试通过**

Run: `TEST_DATABASE_URL=... uv run pytest tests/api/admin/test_tech_perf.py -q`
Expected: 全绿

- [ ] **Step 5: 提交**

```bash
git add backend/api/admin/tech.py tests/api/admin/test_tech_perf.py
git commit -m "feat(admin): tech stages 补 p50_pct/p95_pct(Phase 2)"
```

---

## Task 11: 组件 DualStageBar

**Files:**
- Create: `admin/src/components/observability/DualStageBar.tsx`
- Test: `admin/src/components/observability/__tests__/DualStageBar.test.tsx`

- [ ] **Step 1: 写失败测试**

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import DualStageBar from "@/components/observability/DualStageBar";

describe("DualStageBar", () => {
  it("渲染 P50(浅)+ P95(深)双段 + 超标 data-over=true", () => {
    render(
      <DualStageBar
        stage="generate"
        p50={100}
        p95={3000}
        normalMax={2000}
        p50Pct={5}
        p95Pct={15}
      />,
    );
    expect(screen.getByText("generate")).toBeInTheDocument();
    const p50 = document.querySelector("[data-seg='p50']");
    const p95 = document.querySelector("[data-seg='p95']");
    expect(p50).toBeTruthy();
    expect(p95).toBeTruthy();
    // P95 超 normalMax → over
    expect(screen.getByText("generate").closest("[data-over]")).toHaveAttribute(
      "data-over", "true",
    );
  });

  it("未超标 data-over=false", () => {
    render(
      <DualStageBar stage="intent" p50={50} p95={80} normalMax={500} p50Pct={3} p95Pct={4} />,
    );
    expect(screen.getByText("intent").closest("[data-over]")).toHaveAttribute(
      "data-over", "false",
    );
  });
});
```

- [ ] **Step 2: 运行验证失败**

Run: `cd admin && npx vitest run src/components/observability/__tests__/DualStageBar.test.tsx`
Expected: FAIL(模块不存在)

- [ ] **Step 3: 实现 DualStageBar**

```tsx
/** 双色水平条:浅 P50 + 深 P95 + 正常区间标注。技术洞察阶段表用。 */
export default function DualStageBar({
  stage,
  p50,
  p95,
  normalMax,
  p50Pct,
  p95Pct,
}: {
  stage: string;
  p50: number;
  p95: number;
  normalMax: number;
  p50Pct: number;
  p95Pct: number;
}) {
  const over = p95 > normalMax;
  const max = Math.max(p95, normalMax, 1);
  return (
    <div data-over={over} className="space-y-1">
      <div className="flex items-center gap-2 text-[12px]">
        <span className="w-20 text-[var(--t2)]">{stage}</span>
        <div className="flex-1 h-4 rounded overflow-hidden border relative" style={{ borderColor: "var(--bd)" }}>
          {/* P95 外条 */}
          <div
            data-seg="p95"
            className="absolute top-0 left-0 h-full rounded"
            style={{
              width: `${(p95 / max) * 100}%`,
              background: over ? "var(--err)" : "var(--acc)",
              opacity: 0.4,
            }}
          />
          {/* P50 内条(叠加) */}
          <div
            data-seg="p50"
            className="absolute top-0 left-0 h-full rounded"
            style={{
              width: `${(p50 / max) * 100}%`,
              background: over ? "var(--err)" : "var(--acc)",
            }}
          />
          {/* normalMax 标线 */}
          <div
            data-mark="normal-max"
            className="absolute top-0 h-full w-px"
            style={{ left: `${(normalMax / max) * 100}%`, background: "var(--t3)" }}
          />
        </div>
        <span className={"tabular-nums " + (over ? "text-[var(--err)] font-medium" : "text-[var(--t2)]")}>
          {p95.toLocaleString()}ms
          <span className="text-[var(--t3)] ml-1">({p95Pct}%)</span>
        </span>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: 运行测试通过**

Run: `cd admin && npx vitest run src/components/observability/__tests__/DualStageBar.test.tsx`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add admin/src/components/observability/DualStageBar.tsx admin/src/components/observability/__tests__/DualStageBar.test.tsx
git commit -m "feat(admin): DualStageBar 组件(Phase 2 双色阶段条)"
```

---

## Task 12: 组件 DualTrendBar + Analytics 趋势替换

**Files:**
- Create: `admin/src/components/observability/DualTrendBar.tsx`
- Modify: `admin/src/pages/Analytics.tsx:147-155`(替换 TrendChart)
- Test: `admin/src/components/observability/__tests__/DualTrendBar.test.tsx`
- Test: `admin/tests/TechInsight.test.tsx`

> **注意(D2):** TrendChart 已是双段柱(Phase 1)。DualTrendBar 在其基础上加:告警基线虚线、y 轴刻度、超标日柱着色。

- [ ] **Step 1: 写 DualTrendBar 失败测试**

```tsx
import { describe, it, expect } from "vitest";
import { render } from "@testing-library/react";
import DualTrendBar from "@/components/observability/DualTrendBar";

describe("DualTrendBar", () => {
  it("渲染双段柱 + 基线虚线 + y 轴刻度", () => {
    const data = [
      { date: "08-01", p50: 300, p95: 1000 },
      { date: "08-02", p50: 400, p95: 6000 },  // 超 baseline
    ];
    render(<DualTrendBar data={data} baseline={3000} />);
    const bars = document.querySelectorAll("[data-bar]");
    expect(bars.length).toBe(2);
    bars.forEach((b) => {
      expect(b.querySelectorAll("[data-seg='p95']").length).toBe(1);
      expect(b.querySelectorAll("[data-seg='p50']").length).toBe(1);
    });
    // 基线虚线存在
    expect(document.querySelector("[data-baseline]")).toBeTruthy();
    // y 轴刻度存在
    expect(document.querySelector("[data-y-axis]")).toBeTruthy();
    // 超标日(P95 > baseline)有 data-over=true
    expect(bars[1].getAttribute("data-over")).toBe("true");
    expect(bars[0].getAttribute("data-over")).toBe("false");
  });
});
```

- [ ] **Step 2: 运行验证失败**

Run: `cd admin && npx vitest run src/components/observability/__tests__/DualTrendBar.test.tsx`
Expected: FAIL(模块不存在)

- [ ] **Step 3: 实现 DualTrendBar**

```tsx
/** 双段趋势柱(P95 外 + P50 内)+ 告警基线虚线 + y 轴刻度。 */
export default function DualTrendBar({
  data,
  baseline,
}: {
  data: { date: string; p50: number; p95: number }[];
  baseline: number;
}) {
  const max = Math.max(...data.map((d) => d.p95), baseline, 1);
  const yAxisTicks = [0, Math.round(max * 0.5), max];
  return (
    <div className="flex gap-2">
      {/* y 轴 */}
      <div data-y-axis className="flex flex-col justify-between text-[10px] text-[var(--t3)] h-40 pb-4 text-right pr-1">
        {yAxisTicks.map((t) => <span key={t}>{t}</span>)}
      </div>
      <div className="flex-1 relative">
        <div className="flex items-end gap-1 h-40 border-b border-[var(--bd)] pb-1 relative">
          {/* 基线虚线 */}
          <div
            data-baseline
            className="absolute left-0 right-0 border-t border-dashed border-[var(--warn)] z-10"
            style={{ bottom: `${(baseline / max) * 100}%` }}
          />
          {data.map((d) => {
            const over = d.p95 > baseline;
            return (
              <div
                key={d.date}
                data-bar
                data-over={over}
                className="flex-1 flex flex-col items-center justify-end relative"
                style={{ height: "100%" }}
              >
                <div className="w-full flex flex-col justify-end" style={{ height: "100%" }}>
                  <div
                    data-seg="p95"
                    style={{ height: `${(d.p95 / max) * 100}%` }}
                    className="w-full rounded-t"
                    style={{ background: over ? "var(--err)" : "var(--acc)" } as React.CSSProperties}
                  />
                  <div
                    data-seg="p50"
                    style={{ height: `${(d.p50 / max) * 100}%` }}
                    className="w-full"
                  />
                </div>
              </div>
            );
          })}
        </div>
        <div className="flex gap-1 mt-1">
          {data.map((d) => (
            <div key={d.date} className="flex-1 text-[9px] text-[var(--t3)] text-center">{d.date}</div>
          ))}
        </div>
      </div>
    </div>
  );
}
```

> **注意:** 上面的 `style` 写了两遍(React 会警告)。实现时合并为单一 style 对象。修正版:

```tsx
<div
  data-seg="p95"
  className="w-full rounded-t"
  style={{ height: `${(d.p95 / max) * 100}%`, background: over ? "var(--err)" : "var(--acc)" }}
/>
```

- [ ] **Step 4: 运行组件测试通过**

Run: `cd admin && npx vitest run src/components/observability/__tests__/DualTrendBar.test.tsx`
Expected: PASS

- [ ] **Step 5: Analytics.tsx 替换 TrendChart 为 DualTrendBar**

在 Analytics.tsx L147-155,把 `<TrendChart data={data.trends} baseline={3000} />` 改为:

```tsx
<DualTrendBar data={data.trends} baseline={3000} />
```

并更新 import(`TrendChart` → `DualTrendBar`)。baseline 改用动态值(数据 kpi.baseline 或固定 3000)。

- [ ] **Step 6: 更新 TechInsight.test.tsx 趋势断言**

`admin/tests/TechInsight.test.tsx` 第 93-103 行的"P50/P95 趋势图渲染 7 柱"测试,断言 `data-bar` + `data-seg` 仍存在(DualTrendBar 保留这些 data 属性)。补 `data-baseline` 断言:

```tsx
it("P50/P95 趋势图渲染 7 柱 + 基线虚线", async () => {
  renderWithProviders(<Analytics />);
  await waitFor(() => {
    const bars = document.querySelectorAll("[data-bar]");
    expect(bars.length).toBe(7);
    bars.forEach((b) => {
      expect(b.querySelectorAll("[data-seg='p95']").length).toBe(1);
      expect(b.querySelectorAll("[data-seg='p50']").length).toBe(1);
    });
    expect(document.querySelector("[data-baseline]")).toBeTruthy();
  });
});
```

- [ ] **Step 7: 运行页面测试通过**

Run: `cd admin && npx vitest run tests/TechInsight.test.tsx`
Expected: PASS(5/5)

- [ ] **Step 8: 提交**

```bash
git add admin/src/components/observability/DualTrendBar.tsx admin/src/components/observability/__tests__/DualTrendBar.test.tsx admin/src/pages/Analytics.tsx admin/tests/TechInsight.test.tsx
git commit -m "feat(admin): DualTrendBar 组件 + Analytics 趋势替换(基线虚线+y轴+超标着色)"
```

---

## Task 13: 前端 Analytics 阶段表用 DualStageBar

**Files:**
- Modify: `admin/src/pages/Analytics.tsx`(阶段表区域,L173-207)

- [ ] **Step 1: 阶段表渲染改用 DualStageBar**

在 Analytics.tsx 的"慢在哪"阶段表区域,把 Table 替换为 DualStageBar 列表:

```tsx
import DualStageBar from "@/components/observability/DualStageBar";

// 在阶段表 div 内:
<div data-col="slow" className="rounded-lg border p-4" style={{ background: "var(--panel)", borderColor: "var(--bd)" }}>
  <h2 className="text-[14px] font-medium text-[var(--t1)] mb-3">慢在哪(阶段 P50/P95)</h2>
  <div className="space-y-2">
    {Object.entries(data.stages).map(([stage, s]) => (
      <DualStageBar
        key={stage}
        stage={stage}
        p50={s.p50}
        p95={s.p95}
        normalMax={s.normal_max}
        p50Pct={s.p50_pct ?? 0}
        p95Pct={s.p95_pct ?? 0}
      />
    ))}
  </div>
</div>
```

- [ ] **Step 2: 更新 TechInsight.test.tsx 阶段表断言**

原测试(L105-117)断言 `screen.getByText("generate").closest("[data-over]")` — DualStageBar 保留 `data-over` 属性,断言不变。但阶段表现在不再是 Table,确认测试仍通过。如断言依赖 TableRow/TableCell,改为查询 DualStageBar 的 `data-over`:

```tsx
it("阶段表超标阶段 data-over=true", async () => {
  renderWithProviders(<Analytics />);
  await waitFor(() => {
    expect(screen.getByText("generate").closest("[data-over]")).toHaveAttribute("data-over", "true");
    expect(screen.getByText("intent").closest("[data-over]")).toHaveAttribute("data-over", "false");
  });
});
```

(断言不变,DualStageBar 渲染的 stage 名仍为文本节点)

- [ ] **Step 3: 运行测试通过**

Run: `cd admin && npx vitest run tests/TechInsight.test.tsx`
Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add admin/src/pages/Analytics.tsx admin/tests/TechInsight.test.tsx
git commit -m "feat(admin): Analytics 阶段表用 DualStageBar 双色条(Phase 2)"
```

---

## Task 14: 后端 coverage-gaps miss_type 四态

**Files:**
- Modify: `backend/api/admin/analytics.py:96-118`(miss_type 推断逻辑)
- Test: `tests/api/admin/test_analytics.py`

> **设计(D4):** 重新定义四态。需关联 Trace 表读 confidence 判断 `low`。

- [ ] **Step 1: 写失败测试**

```python
@pytest.mark.asyncio
async def test_coverage_gaps_miss_type_four_types(client, admin_token, db_session):
    """miss_type 四态:reject/low/召回空/召回不足。"""
    now = datetime.now(UTC)
    # cluster 关联 4 种对话
    cluster = QuestionCluster(
        id=uuid.uuid4(), cluster_type="gap",
        representative_question="测试", question_count=4, status="open",
    )
    db_session.add(cluster)
    await db_session.commit()

    # 1. reject:is_answered=False
    conv1 = Conversation(
        id=uuid.uuid4(), question="q1", answer=None, is_answered=False,
        cluster_id=str(cluster.id), created_at=now - timedelta(days=1),
    )
    # 2. low:answered, sources 非空, 最新 trace confidence<0.6
    conv2 = Conversation(
        id=uuid.uuid4(), question="q2", answer="a", is_answered=True,
        sources=[{"url": "x"}], cluster_id=str(cluster.id),
        created_at=now - timedelta(days=1),
    )
    # 3. 召回空:answered, sources 空
    conv3 = Conversation(
        id=uuid.uuid4(), question="q3", answer="a", is_answered=True,
        sources=[], cluster_id=str(cluster.id),
        created_at=now - timedelta(days=1),
    )
    # 4. 召回不足:answered, sources 非空, confidence>=0.6
    conv4 = Conversation(
        id=uuid.uuid4(), question="q4", answer="a", is_answered=True,
        sources=[{"url": "y"}], cluster_id=str(cluster.id),
        created_at=now - timedelta(days=1),
    )
    db_session.add_all([conv1, conv2, conv3, conv4])
    # conv2 的 trace(confidence=0.3)
    db_session.add(Trace(
        conversation_id=conv2.id, turn_index=0, type="rag",
        stages={"intent": {"ms": 5}}, total_ms=5, confidence=0.3,
        created_at=now - timedelta(days=1),
    ))
    # conv4 的 trace(confidence=0.8)
    db_session.add(Trace(
        conversation_id=conv4.id, turn_index=0, type="rag",
        stages={"intent": {"ms": 5}}, total_ms=5, confidence=0.8,
        created_at=now - timedelta(days=1),
    ))
    await db_session.commit()

    resp = await client.get(
        "/api/admin/analytics/coverage-gaps",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    items = resp.json()["items"]
    target = [i for i in items if i["id"] == str(cluster.id)][0]
    # 主导 miss_type 为 4 种中数量最多者(各 1 票,取首个 max)
    assert target["miss_type"] in ("reject", "low", "召回空", "召回不足")
    summary = resp.json()["miss_type_summary"]
    # 四态各至少 1
    for t in ("reject", "low", "召回空", "召回不足"):
        assert summary.get(t, 0) >= 1
```

- [ ] **Step 2: 运行验证失败**

Run: `TEST_DATABASE_URL=... uv run pytest tests/api/admin/test_analytics.py::test_coverage_gaps_miss_type_four_types -xvs`
Expected: FAIL(当前只有"召回空"/"召回不足"两态)

- [ ] **Step 3: 实现四态分类**

修改 `analytics.py` list_coverage_gaps 的 miss_type 推断(L96-118)。需关联 Trace 表读最新 confidence:

```python
from backend.db.models import Trace as TraceModel

# 在 cluster_ids 查询后,补 trace confidence 批量查询
conv_q = select(
    Conversation.cluster_id,
    Conversation.sources,
    Conversation.is_answered,
    Conversation.id,
).where(Conversation.cluster_id.in_(cluster_ids))
conv_rows = (await session.execute(conv_q)).all()

# 批量查最新 trace confidence
conv_ids_for_trace = [row.id for row in conv_rows]
conf_map: dict = {}
if conv_ids_for_trace:
    trace_q = (
        select(TraceModel.conversation_id, TraceModel.confidence, TraceModel.turn_index)
        .where(TraceModel.conversation_id.in_([str(c) for c in conv_ids_for_trace]))
        .order_by(TraceModel.turn_index.desc())
    )
    for row in (await session.execute(trace_q)).all():
        cid = str(row.conversation_id)
        if cid not in conf_map:
            conf_map[cid] = row.confidence

cluster_stats: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
for row in conv_rows:
    cid = str(row.cluster_id) if row.cluster_id else ""
    sources = row.sources if isinstance(row.sources, list) else []
    conf = conf_map.get(str(row.id))
    # 四态分类
    if not row.is_answered:
        miss = "reject"
    elif sources and conf is not None and conf < 0.6:
        miss = "low"
    elif not sources:
        miss = "召回空"
    else:
        miss = "召回不足"
    cluster_stats[cid][miss] += 1
```

- [ ] **Step 4: 运行测试通过**

Run: `TEST_DATABASE_URL=... uv run pytest tests/api/admin/test_analytics.py -q`
Expected: 全绿

- [ ] **Step 5: 提交**

```bash
git add backend/api/admin/analytics.py tests/api/admin/test_analytics.py
git commit -m "feat(admin): coverage-gaps miss_type 四态(reject/low/召回空/召回不足)"
```

---

## Task 15: 组件 GapTypeBadge

**Files:**
- Create: `admin/src/components/observability/GapTypeBadge.tsx`
- Test: `admin/src/components/observability/__tests__/GapTypeBadge.test.tsx`

- [ ] **Step 1: 写失败测试**

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import GapTypeBadge from "@/components/observability/GapTypeBadge";

describe("GapTypeBadge", () => {
  it("reject 类型渲染灰色 badge", () => {
    render(<GapTypeBadge type="reject" />);
    const badge = screen.getByText("拒答").closest("[data-gap-type]");
    expect(badge).toHaveAttribute("data-gap-type", "reject");
    expect(badge).toHaveStyle({ background: "var(--t3)" });
  });

  it("low 类型渲染橙色 badge", () => {
    render(<GapTypeBadge type="low" />);
    expect(screen.getByText("低相关")).toBeInTheDocument();
  });

  it("召回空 渲染红色", () => {
    render(<GapTypeBadge type="召回空" />);
    const badge = screen.getByText("召回空").closest("[data-gap-type]");
    expect(badge).toHaveStyle({ background: "var(--err)" });
  });
});
```

- [ ] **Step 2: 运行验证失败**

Run: `cd admin && npx vitest run src/components/observability/__tests__/GapTypeBadge.test.tsx`
Expected: FAIL

- [ ] **Step 3: 实现 GapTypeBadge**

```tsx
/** 缺口类型标签:拒答灰/召回空红/低相关橙/召回不足黄。 */
const GAP_CONFIG: Record<string, { label: string; color: string }> = {
  reject: { label: "拒答", color: "var(--t3)" },
  "召回空": { label: "召回空", color: "var(--err)" },
  low: { label: "低相关", color: "var(--warn)" },
  "召回不足": { label: "召回不足", color: "var(--acc)" },
};

export default function GapTypeBadge({ type }: { type: string }) {
  const cfg = GAP_CONFIG[type] ?? { label: type, color: "var(--t3)" };
  return (
    <span
      data-gap-type={type}
      className="inline-flex items-center rounded px-1.5 py-0.5 text-[11px] text-white"
      style={{ background: cfg.color }}
    >
      {cfg.label}
    </span>
  );
}
```

- [ ] **Step 4: 运行测试通过**

Run: `cd admin && npx vitest run src/components/observability/__tests__/GapTypeBadge.test.tsx`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add admin/src/components/observability/GapTypeBadge.tsx admin/src/components/observability/__tests__/GapTypeBadge.test.tsx
git commit -m "feat(admin): GapTypeBadge 组件(Phase 2 缺口标色)"
```

---

## Task 16: 前端 Analytics 缺口标色

**Files:**
- Modify: `admin/src/pages/Analytics.tsx`(KnowledgeGapsTab 缺口表,L460-484)

- [ ] **Step 1: 缺口表类型列用 GapTypeBadge**

在 Analytics.tsx KnowledgeGapsTab 的覆盖缺口表(L460-484),类型列从 Badge 改为 GapTypeBadge:

```tsx
import GapTypeBadge from "@/components/observability/GapTypeBadge";

// TableCell 类型列:
<TableCell>
  {cluster.miss_type && <GapTypeBadge type={cluster.miss_type} />}
</TableCell>
```

删除原 Badge variant 逻辑(cluster.miss_type === "召回空" ? "destructive" : "secondary")。

- [ ] **Step 2: 更新 TechInsight.test.tsx 缺口测试**

原测试(L119-125)"切换到知识缺口 tab 显示覆盖缺口" — 确认 GapTypeBadge 渲染不破坏断言(仍查"如何接入 SDK"文本)。如 mock 数据 miss_type 为"召回空",加断言:

```tsx
// 在 mockCoverageGaps mock 数据补 miss_type:
mockCoverageGaps.mockResolvedValue({
  items: [
    {
      id: "g1",
      cluster_type: "gap",
      representative_question: "如何接入 SDK",
      sample_questions: ["如何接入 SDK"],
      question_count: 5,
      status: "open",
      miss_type: "召回空",  // 补
      period_start: null, period_end: null, created_at: "2026-08-10T10:00:00Z",
    },
  ],
  total: 1, page: 1, size: 20,
});

it("切换到知识缺口 tab 显示覆盖缺口 + 类型 badge", async () => {
  renderWithProviders(<Analytics />);
  fireEvent.click(await screen.findByText("知识缺口"));
  await waitFor(() => {
    expect(screen.getByText("如何接入 SDK")).toBeInTheDocument();
    expect(document.querySelector("[data-gap-type='召回空']")).toBeTruthy();
  });
});
```

- [ ] **Step 3: 运行测试通过**

Run: `cd admin && npx vitest run tests/TechInsight.test.tsx`
Expected: PASS

- [ ] **Step 4: 提交**

```bash
git add admin/src/pages/Analytics.tsx admin/tests/TechInsight.test.tsx
git commit -m "feat(admin): Analytics 缺口表用 GapTypeBadge 标色(Phase 2)"
```

---

## Task 17: 全量验证

**Files:** 无(仅运行验证)

- [ ] **Step 1: 后端全量 admin 测试**

Run: `TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test uv run pytest tests/api/admin/ -q`
Expected: 全绿(既有 + Phase 2 新增:markers/has_clarify/prev_total/hot-questions/p50_pct/miss_type 四态)

- [ ] **Step 2: 前端全量 vitest**

Run: `cd admin && npx vitest run --exclude='**/.claude/**' 2>&1 | tail -30`
Expected: 全绿(Phase 1 既有 + Phase 2 新增 4 组件测试 + 更新的页面测试)

- [ ] **Step 3: tsc 类型检查**

Run: `cd admin && npx tsc --noEmit 2>&1 | grep -v TS6310 | head`
Expected: 无新增报错

- [ ] **Step 4: 前端 build**

Run: `cd admin && npm run build`
Expected: 成功

- [ ] **Step 5: 后端 import 冒烟**

Run: `uv run python -c "from backend.main import app; print('import ok')"`
Expected: `import ok`

- [ ] **Step 6: ruff/black lint**

Run: `ruff check backend/api/admin/ && ruff format --check backend/api/admin/`
Expected: 无报错(如有自动修复 `ruff check --fix` + `ruff format`)

- [ ] **Step 7: 记录验证结果**

在 Task 18 末尾记录:测试计数、build 产物大小、tsc 结果。

---

## Task 18: Real-Run Gate

**Files:** 无(运行真实 ASGI app)

> **Gate 标准:** 真实 ASGI app + 真实 Postgres + 真实 lifespan 加载,验证 Phase 2 新字段在真实 API 响应中存在。dev 库数据稀疏(可能无 trace/conversation),字段存在性由集成测试证明,Real-Run 证明端点不 500 + 新字段键存在。

- [ ] **Step 1: TestClient 验证 conversations markers**

```python
# scripts/verify_phase2.py(临时验证脚本,不提交)
import os
os.environ.setdefault("TEST_DATABASE_URL", "")
from starlette.testclient import TestClient
from backend.main import app
from backend.config import load_settings

s = load_settings()
from backend.auth.jwt import create_access_token
token = create_access_token("admin-test", "admin", s.jwt_secret)

client = TestClient(app)
resp = client.get(
    "/api/admin/conversations?size=3",
    headers={"Authorization": f"Bearer {token}"},
)
print(f"conversations: {resp.status_code}")
print(f"  total={resp.json().get('total')}")
if resp.json()["items"]:
    item = resp.json()["items"][0]
    ts = item.get("trace_summary")
    if ts:
        print(f"  markers keys: {sorted((ts.get('markers') or {}).keys())}")

resp = client.get(
    "/api/admin/business/overview?range=7d",
    headers={"Authorization": f"Bearer {token}"},
)
print(f"business overview: {resp.status_code}")
svc = resp.json().get("service", {})
print(f"  prev_total={svc.get('prev_total')} delta_pct={svc.get('delta_pct')}")

resp = client.get(
    "/api/admin/business/hot-questions?intent=commercial&range=7d",
    headers={"Authorization": f"Bearer {token}"},
)
print(f"hot-questions: {resp.status_code}, items={len(resp.json().get('items', []))}")

resp = client.get(
    "/api/admin/tech/performance?range=7d",
    headers={"Authorization": f"Bearer {token}"},
)
print(f"tech performance: {resp.status_code}")
stages = resp.json().get("stages", {})
if stages:
    sample = next(iter(stages.values()))
    print(f"  stage keys: {sorted(sample.keys())}")

resp = client.get(
    "/api/admin/analytics/coverage-gaps",
    headers={"Authorization": f"Bearer {token}"},
)
print(f"coverage-gaps: {resp.status_code}")
print(f"  miss_type_summary: {resp.json().get('miss_type_summary')}")
```

Run: `uv run python scripts/verify_phase2.py`
Expected:
- conversations: 200,markers keys 含 retry/clarify/reject_short/degraded(若 dev 库有 trace;无 trace 则 trace_summary=null,正常)
- business overview: 200,prev_total/delta_pct 键存在(值可能 0)
- hot-questions: 200,items 数组(dev 库可能空)
- tech performance: 200,stage keys 含 p50_pct/p95_pct
- coverage-gaps: 200,miss_type_summary 键存在

- [ ] **Step 2: 证明 active version(新字段在响应中)**

从 Step 1 输出确认:conversations items 含 markers 键(或 trace_summary=null 当无 trace);service 含 prev_total/delta_pct;stages 含 p50_pct/p95_pct;coverage-gaps 含 miss_type_summary。**这些键的存在即证明新代码在运行**(旧代码无这些键)。

- [ ] **Step 3: 记录 Real-Run 结果**

在本 Task 末尾记录:实际命令、HTTP 状态码、关键字段存在确认。如 dev 库无数据导致字段值为 0/空,注明"字段存在性由 Task X 集成测试证明(真实 Postgres、非 mock)"。

- [ ] **Step 4: 删除临时验证脚本**

```bash
rm -f scripts/verify_phase2.py
```

- [ ] **Step 5: 提交 plan 完成记录**

```bash
git add docs/superpowers/plans/2026-08-11-admin-phase2-plan.md
git commit -m "docs(plan): Phase 2 完成 — 全量验证 + Real-Run Gate"
```

---

## Phase 2 完成标准

- [x] 后端 4 个测试文件全绿(test_conversations + test_analytics_business + test_tech_perf + test_analytics)— Task 17 Step 1: `pytest tests/api/admin/ -q` → 75 passed
- [x] 前端全量 vitest 全绿(Phase 1 既有 + Phase 2 新增 4 组件测试 + 更新的 3 页面测试)— Task 17 Step 2: `npx vitest run` → 27 files / 88 tests passed
- [x] `cd admin && npx tsc --noEmit` 无新增报错(TS6310 pre-existing 豁免)— Task 17 Step 3: `tsc -b` clean (exit 0)
- [x] `cd admin && npm run build` 成功 — Task 17 Step 4: dist/assets/index-CulACmI_.js 767.79 kB, 2025 modules
- [x] Real-Run Gate:5 个端点 HTTP 200 + 新字段键存在(markers/prev_total/delta_pct/p50_pct/p95_pct/miss_type_summary)— Task 18 Step 1-2: 见下方 Real-Run 结果
- [x] 三页视觉对齐设计稿 B 方案(Phase 2 聚合层:环比/标记点/Top3/双色条/缺口标色)— 代码层面完成;真实数据视觉验证待 prod
- [x] 无第三方图表库引入
- [x] 所有新组件 < 80 行,props 驱动
- [x] Playwright 浏览器 E2E 验证(补做,2026-08-11)— 三页导航 + tab/toggle/range 交互全程 0 console error;发现并修复 stale 后端(hot-questions 404)+ DualTrendBar 空数据 key 冲突(commit `acc3c1c`)。截图 `e2e-business-overview.png` / `e2e-knowledge-gaps.png`。**局限**:dev 库空态,真实数据视觉待 prod。

---

## Self-Review 记录(完成后填写)

### Spec 覆盖核对(Phase 2 三页 + 组件库)

| Spec 要求 | 对应 Task | 状态 |
|---|---|---|
| 2.1 trace_summary 补 stage_ratios | (Phase 1 已通过 StageBar 4 段映射实现,前端从 stages 派生;后端 stage_ratios 冗余无其他消费者) | ✅ 关闭(前端派生) |
| 2.1 list 补 markers | Task 1 | ✅ |
| 2.1 前端标记点 | Task 5 Step 6 | ✅ |
| 2.1 4 toggle 筛选 | Task 5 | ✅ |
| 2.2 service 补 prev 环比 | Task 6 | ✅ |
| 2.2 hot-questions 端点 | Task 7 | ✅ |
| 2.2 前端环比标签 | Task 8 | ✅ |
| 2.2 三列意图卡 Top3 | Task 9 | ✅ |
| 2.3 stages 补 p50_pct/p95_pct | Task 10 | ✅ |
| 2.3 trends 补 p50_inner | (Phase 1 已有 p50,D2 确认) | ✅ |
| 2.3 miss_type 扩展 reject/low | Task 14 | ✅ |
| 2.3 阶段表 DualStageBar | Task 11 + 13 | ✅ |
| 2.3 趋势 DualTrendBar | Task 12 | ✅ |
| 2.3 缺口标色 | Task 15 + 16 | ✅ |
| 组件库 DualStageBar | Task 11 | ✅ |
| 组件库 DualTrendBar | Task 12 | ✅ |
| 组件库 ToggleFilter | Task 4 | ✅ |
| 组件库 GapTypeBadge | Task 15 | ✅ |

### Real-Run 结果(完成后填写)

**命令:** `uv run python scripts/verify_phase2.py`(脚本已按 Step 4 删除)

**执行日期:** 2026-08-11

**实际输出:**

```
conversations: 200, total=0
business overview: 200
  prev_total=0 delta_pct=0.0
hot-questions: 200, items=0
tech performance: 200
  stage keys: ['normal_max', 'p50', 'p50_pct', 'p95', 'p95_pct']
coverage-gaps: 200
  miss_type_summary: {}
```

**字段存在确认(Step 2):**
- ✅ `tech performance` stages 含 `p50_pct` / `p95_pct`(Phase 1 旧代码无此键 → 新代码在运行)
- ✅ `business overview` service 含 `prev_total` / `delta_pct`(Phase 1 旧代码无此键 → 新代码在运行)
- ✅ `coverage-gaps` 含 `miss_type_summary` 键(Phase 1 旧代码无此键 → 新代码在运行)
- ⚠️ `conversations` markers 键:dev 库无 trace 数据(total=0),trace_summary=null。**markers 字段存在性由 Task 1 集成测试 `test_conversations_markers` 证明**(真实 Postgres、非 mock,断言 markers 含 retry/clarify/reject_short/degraded 四键)
- ⚠️ `hot-questions` items=0:dev 库无 conversation 数据。**端点存在性 + 响应结构由 Task 7 集成测试证明**
- ⚠️ `miss_type_summary={}`:dev 库无 QuestionCluster。**四态分类由 Task 14 集成测试 `test_coverage_gaps_miss_type_four_types` 证明**

**结论:** 5 个端点全部 HTTP 200(不 500),3 个新字段键(p50_pct/p95_pct/prev_total/delta_pct/miss_type_summary)在真实响应中确认存在。其余字段因 dev 库数据稀疏,由对应集成测试证明。Real-Run Gate 通过。

### 说明

- **stage_ratios**:spec 2.1 要求 trace_summary 补 stage_ratios(4 段百分比数组)。但 Phase 1 Task 14 已在列表行用 StageBar 直接从 `stages` 派生 4 段(intent+rewrite/retrieve+rerank/generate/output),前端计算比例。后端补 stage_ratios 是冗余 — 除非其他消费者需要。Self-review 时核实:若无其他消费者,标记为"前端派生,无需后端字段",Task 关闭。
- **ToggleFilter 置信<0.6 客户端过滤(D8)**:因 trace confidence 在 JSONB,SQL 过滤性能差。列表限 20 条/页,客户端过滤足够。如未来需跨页过滤,改后端加 has_low_confidence 参数(需 JSONB 查询优化)。

---

## 执行姿态说明

本计划为 **Tier 1**(可逆本地变更:前端组件 + 后端查询扩展,无部署/迁移/计划)。直接执行 + Real-Run Gate,跳过 orchestrator delegation 和 Plan Review Gate。

**并行批次**(逻辑分批,主 agent 直接执行):
- 批 A 后端独立扩展:Task 1, 6, 7, 10, 14
- 批 B 前端组件:Task 4, 11, 15
- 批 C 前端类型/API:Task 2, 3
- 批 D 前端页面消费:Task 5, 8, 9, 12, 13, 16
- 批 E 验证:Task 17, 18
