# Admin 三页设计稿对齐 — 设计文档

> **状态**: Phase 1-2 待实施 · Phase 3 待优先级评审
> **方案**: B(功能对齐,视觉合理偏差)
> **设计稿**: `.superpowers/brainstorm/33664-1786325139/content/` 下三份 HTML 效果图

## 背景与目标

ask-ai 管理后台三个核心页面(业务概览、对话审查、技术洞察)的实现与设计稿存在系统性差距。经审计,差距分为三层:

- **第一层(可视化 + 数据暴露)**: 后端已有数据但 API 未返回,或前端未渲染。快赢,1-2 天/页。
- **第二层(后端聚合逻辑)**: 数据在 DB 但需新查询/计算。中等,3-5 天/页。
- **第三层(基础设施)**: 需新表、pipeline 采集层改造、eval 管道。重,1-2 周,独立立项。

### 目标

采用 **B 方案(功能对齐,视觉合理偏差)**: 不追求像素级复刻设计稿,而是补齐核心可视化(堆叠条/泳道/漏斗/mini-trend)和数据维度(客户信息/来源归因/环比/标记点),用现有 shadcn 体系 + 少量自定义 SVG/进度条组件实现。信息密度和叙事因果对齐设计稿,样式细节允许合理偏差。

### 非目标

- 不替换现有 shadcn/Radix 组件体系
- 不做暗色模式(现有体系未覆盖)
- Phase 3 的客户信息模型、来源 eval 管道不在本轮实施,仅设计定义

---

## Phase 1: 快赢层

数据已有(在 DB 或 API 返回结构里),只需暴露 + 画组件。三页同步推进,目标 1 周。

### 1.1 对话审查

**后端(暴露已有数据)**:
- `/api/admin/conversations` list 端点的 `trace_map` 补 `confidence`(Trace.confidence 已有,trace_map L82-86 当前只存 type/stages/total_ms)
- 前端 `types/api.ts` 的 `Conversation` 接口(L112-124)补 `trace_summary` 类型声明(trace_summary 已在 conversations.py L101 返回,但前端 TS 类型未含)

**前端(画组件)**:
- 列表行加 `StageBar` — 4 色阶段比例条(把现有 6 段 stages 合并成 4 段: 前置/检索/生成/输出)
- 列表行加 `置信度` 数值(低置信 < 0.6 标橙)
- 详情面板 Trace 改为**横向泳道布局**: 5 阶段(前置/路由/检索/生成/输出),每阶段左色块 + items + 耗时,跳过阶段标灰
- Trace 顶部加 `LanesBar`(按各阶段耗时占比着色)
- 多轮按钮标注类型(`轮N 澄清` / `轮N RAG`)

**阶段映射规则**(列表 4 段 vs 详情 5 段,映射来源不同):

| 设计稿阶段 | 列表 4 段映射 | 详情 5 段映射 | 数据源(rag.py stages) |
|-----------|-------------|-------------|----------------------|
| 前置 | intent + rewrite | rewrite | intent.category/reason + rewrite.extracted/rewritten |
| 路由 | — (列表不显示) | intent | intent 路由决策(数据源选择 + 阈值放行),ms 含在 intent 段内 |
| 检索 | retrieve + rerank | retrieve + rerank | retrieve.hybrid_count/path_counts + rerank.top_score |
| 生成 | generate | generate | generate.latency_ms/tokens_output |
| 输出 | output | output | output.sources_count |

> **⚠️ "路由" lane 数据源说明**: 设计稿的"路由"lane(路由→数据源 + 阈值放行)在 rag.py 中**没有独立计时段**——路由决策发生在 intent 阶段内部(数据源选择 + 阈值判断是 intent classification 的一部分)。Phase 1 采用折衷: "路由"lane 的 items 从 intent.reason + config_snapshot 派生,ms 显示 0 或从 intent 段拆分(估算)。如需精确计时,Phase 2 在 rag.py 新增 `stages.routing` 采集点(后端改动)。

**不做**: 客户信息、标记点(Phase 2/3)。

### 1.2 业务概览

**后端**:
- `geo` 返回补 `pct`(前端算也可,但后端算更稳)
- `days` 字典补 `90d` 键
- timeseries 数据已有每意图日分量,前端派生 mini-trend

**前端**:
- 服务总览卡加 `StackedBar`(意图堆叠条 + 图例,单行横向,三色段)
- **新建三列意图卡**(销售咨询/产品方案/技术支持) — 每列含: 意图名 + 计数 + 百分比 + mini-trend(7 日柱图) + 下钻链接。当前实现缺失,被压缩成扁平"意图分布"数字块。
- 地域分布加 `ProgressBar`(现有纯文本数字 → 横条)
- 意图命名对齐设计稿: "商务咨询" → "销售咨询"(前端常量)

**不做**: 三列意图卡的热门问题 Top3、环比(Phase 2)。

**区块对齐**: 实现现有 8 个区块(KPI 行/意图分布/每日趋势/销售线索/场景应用/产品需求/热门问题/地域),设计稿 8 个视觉块(服务总览/三列意图深入 × 3/销售线索/产品需求/场景应用/地域)。差距不在数量而在结构: 实现把三意图压成扁平"意图分布"单块(1 块),设计稿是三列意图深入卡(3 块),净差 2 块;实现独有的"每日趋势"和"热门问题"设计稿无。Phase 1 把扁平意图分布替换为三列意图卡(净增 2),对齐设计稿结构。

### 1.3 技术洞察

**后端**:
- KPI 端点补返回 `count`(异常/retry/失败条数,内部已算)
- KPI 端点补返回 `delta`(异常/retry/失败的环比,现仅 P95 有)
- 异常分布补 `pct`
- 阶段命名对齐: 6 段(intent/rewrite/retrieve/rerank/generate/output)映射到设计稿 5 段(前置/路由/检索/生成/输出),完整映射规则见 §1.1 的阶段映射表

**前端**:
- KPI 卡补 `count` 副数据 + `delta` 环比(↑↓ 着色)
- 加 `ContainmentDiagram`(异常 ⊃ retry ⊃ 失败,带计数)
- 异常分布行加彩色圆点 + 百分比
- 技术性能 tab 三列改为 `grid3 并排`(慢在哪 / 什么异常 / 降级到什么)
- 降级链路改为 `NodeFlow`(节点-箭头 flow,绿/黄红色块,不再是纯文字)

**不做**: 澄清漏斗、来源准确率(Phase 3);阶段表双色条(Phase 2 可做也可不做)。

### 1.4 跨页面共享组件

Phase 1 需要新建的可视化组件,三页复用,放 `admin/src/components/viz/` 下。

---

## Phase 2: 聚合层

数据在 DB,但需要新的后端查询/聚合逻辑。三页同步,目标 1 周。Phase 2 依赖 Phase 1 的组件库(复用 mini-trend、stage bar 等)。

### 2.1 对话审查

**后端(新聚合)**:
- `trace_summary` 补 `stage_ratios`: 把 6 段 stages 聚合成 4 段比例(前置= intent+rewrite / 检索= retrieve+rerank / 生成= generate / 输出= output),返回百分比数组。4 段映射不含"路由"(路由是详情 5 段特有,列表 mini-bar 用 4 段)
- list 端点补 `markers` 对象: 从 trace 数据推断标记
  - `retry`: 同一 conversation 下有多条 trace 且 type 含重试特征 → 计数
  - `clarify`: trace type = clarify → 标记
  - `reject_short`: trace type = reject_short → 标记
  - `degraded`: trace stages 里检索/rerank 路径异常(path_counts 非正常)→ 标记(Phase 3 落库后改为读字段)

**前端**:
- 列表行加 `标记点`(彩色圆点: 重试红/澄清橙/短路灰/降级紫),从 markers 渲染
- 4 个快速 toggle 筛选(置信<0.6 / 异常重试 / 有反馈 / 触发澄清),toggle 联动 list 查询参数

**不做**: 客户信息、降级标记的真实事件源(Phase 3)。

### 2.2 业务概览

**后端(新查询)**:
- `service` 补 `prev` 环比: 查询上一同等长度时间窗的 total,返回 `prev_total` + `delta_pct`
- 新端点 `GET /business/overview/hot-questions?intent={intent}&range={range}`: 按意图过滤 cluster,返回 Top3(问题 + 计数)。复用现有 `top_questions` 查询逻辑,加 intent 过滤条件

**前端**:
- 服务总览加 `环比标签`(↑12% vs 上期 / ↓5% vs 上期,涨跌着色)
- 三列意图卡填入 `热门问题 Top3`(Phase 1 建的壳,这里填数据)

### 2.3 技术洞察

**后端(新聚合)**:
- 阶段表双色条: stages 端点补 `p50_pct` + `p95_pct`(各阶段占最大 P95 的比例),前端据此画双色水平条
- 趋势柱图补 `p50_inner`: trends 每天补 p50 值,前端画双段柱(P95 外柱 + P50 内柱)
- 缺口聚类类型扩展: `coverage-gaps` 端点的 miss_type 增加 `reject`(拒答)和 `low`(低相关),从 conversations 表的 intent_tag + 是否拒答推断

**前端**:
- 阶段表改 `DualStageBar`(浅紫 P50 + 深紫 P95) + 正常区间标注
- 趋势柱图改 `DualTrendBar`(双段柱 + 告警基线虚线 + y 轴)
- 缺口聚类按类型标色(拒答灰 / 召回空红 / 低相关橙)

**不做**: 来源准确率、澄清漏斗(Phase 3)。

### 2.4 Phase 2 依赖说明

- 对话审查的 `degraded` 标记在 Phase 2 是"推断版"(从 path_counts 推测),Phase 3 改为"真实事件版"(Trace 落库字段)。API 契约不变,后端实现升级。
- 技术洞察的缺口类型在 Phase 2 是"推断版"(从 intent_tag 推断拒答),Phase 3 可升级为更精确的分类。

---

## Phase 3: 基础设施层(待优先级评审)

需要新表、pipeline 采集层改造、eval 管道。这是结构性投资,1-2 周。**本轮只写设计定义,不实施**。待 Phase 1+2 落地后,根据实际价值评估是否启动。

### 3.1 客户信息模型 + widget 表单

**问题**: DB 无 customer/contact 实体,设计稿对话审查的"客户信息行"(姓名/邮箱/公司/备注/线索标记)完全无数据源。

**设计定义**:
- 新表 `conversation_contacts`:
  ```
  id, conversation_id(FK), name, email, company, note, is_lead,
  created_at
  ```
  一对一关联 conversation,widget 端可选填写。
- widget 端表单: 对话前或对话后,展示"留个联系方式?(可选)"轻量表单,字段 name/email/company/note。不强制,不阻断对话。
- 线索标记 `is_lead`: 由后端规则推断(commercial 意图 + 含购买关键词)或 admin 手动标注。
- admin API: `/conversations/{id}/contact` GET/PATCH。
- 对话审查前端: 详情面板加"客户信息行",从 contact 渲染。

**待评审点**: widget 表单会不会降低对话转化?线索标记规则是否够准?

### 3.2 Trace 采集层修复

**问题**: `rag.py` 无专门 `degraded`/`error_flags`/`retry_count` 字段落库。retrieve 阶段降级(符号/boost/RRF)通过 `path_counts` 间接反映(tech.py 靠它推断"单路检索"),但 LLM retry 信息完全丢失(deepseek.py retry 只 log 不回写)。tech.py 的异常/retry/降级统计全是推断,不准。

**设计定义**:
- `Trace` 模型加列: `error_flags`(JSONB)、`retry_count`(int)、`degraded`(bool)、`recovered`(bool)。
- `rag.py` 采集点:
  - LLM 超时重试 → 写 `retry_count`、`error_flags.llm_timeout`
  - rerank 跳过/降级纯 hybrid → 写 `degraded=true`、`error_flags.rerank_skip`
  - 向量库超时降级 BM25 → 写 `degraded=true`、`error_flags.vector_timeout`
  - 恢复成功 → 写 `recovered=true`
- `llm/deepseek.py` 的 retry 回调写回 Trace(目前丢失)。
- tech.py 统计改读真实字段,废弃阈值推断。

**待评审点**: 历史 trace 数据无这些字段,迁移策略?降级检测的边界条件?

### 3.3 多轮消息正文存储

**问题**: Trace 只存执行诊断,不存轮级 q/ans 文本。设计稿多轮切换要看每轮的完整对话。

**设计定义**:
- 方案 A(扩列): `Trace` 加 `user_message`、`assistant_message` 列。轻,但 trace 表语义变重。
- 方案 B(新表): `conversation_turns`(id, conversation_id, turn_index, user_message, assistant_message, sources, trace_id FK)。语义清晰,但多一张表。
- **推荐 B**,trace 保持纯诊断,消息正文独立。多轮 API `/conversations/{id}/turns` 返回。

**待评审点**: 历史多轮 conversation 的消息正文能否回填?

### 3.4 来源准确率 eval 管道

**问题**: 设计稿"来源质量归因"(来源名 + 命中数 + 准确率 + 三级判色)需要 eval 判定,完全无采集。

**设计定义**:
- 复用 `ask-ai-eval` skill 的 eval_runner 判定逻辑(已有),建离线 eval 管道:
  - 定期(每日/手动)抽样 conversations,对每条 source 判定"被引用且答案通过 eval"
  - 写入 `source_quality`(source_name, date, hits, accuracy_rate, grade)
- tech.py `/source-health` 端点改读 `source_quality` 表。
- 前端来源质量表渲染三级判色(≥70% 正常 / 60-70% 偏低 / <60% 差)。

**待评审点**: eval 管道跑全量还是抽样?准确率定义是否需要人工校验?

### 3.5 澄清漏斗

**问题**: 无 clarify trace 类型(只有 rag/reject_short/override),无澄清漏斗聚合。

**设计定义**:
- 依赖 3.2 的 pipeline 改造: rag.py 触发澄清追问时,写 `trace.type = 'clarify'`(目前不写 trace)。
- 新端点 `GET /tech/clarify-funnel?range={range}`: 5 级聚合
  1. 进入意图分类(总对话数)
  2. 置信 < 0.6
  3. 触发澄清追问
  4. 补充后命中(澄清后下一轮 trace.type=rag)
  5. 最终未命中(澄清后仍拒答/低相关)
- 前端澄清漏斗组件(5 级留存率横条)。

**待评审点**: 3.2 不做则 3.5 无法做,强依赖。

### 3.6 Phase 3 依赖图

```
3.1 客户信息     ──独立──> 对话审查客户信息行
3.2 Trace采集层  ─┬─> 技术洞察真实统计
                  └─> 对话审查降级标记(升级推断版)
3.3 多轮消息    ──独立──> 对话审查多轮正文
3.4 来源eval    ──独立──> 技术洞察来源质量
3.5 澄清漏斗    ──依赖3.2──> 技术洞察澄清漏斗
```

---

## 可视化组件库

Phase 1-2 需要的可视化组件统一放 `admin/src/components/viz/`,三页复用。用现有 Tailwind + 少量内联 SVG,不引第三方图表库。

### 组件清单

| 组件 | 用途 | 使用页 | Phase |
|------|------|--------|-------|
| `StackedBar` | 意图占比横条(三色段 + 图例) | 业务概览 | 1 |
| `MiniTrend` | 迷你柱图(n 根柱,单色) | 业务概览三列卡 | 1 |
| `ProgressBar` | 横条进度(带百分比) | 业务概览地域 | 1 |
| `IntentColumn` | 意图深入列(名+计数+mini-trend+下钻) | 业务概览三列 | 1 |
| `StageBar` | 阶段比例条(4 色横条,列表行内) | 对话审查列表 | 1 |
| `TraceSwimlane` | Trace 横向泳道(5 阶段,色块+items+耗时+跳过标灰) | 对话审查详情 | 1 |
| `LanesBar` | Trace 总比例条(按阶段耗时占比着色) | 对话审查详情 | 1 |
| `NodeFlow` | 节点-箭头链路图(绿/黄红色块) | 技术洞察降级链路 | 1 |
| `ContainmentDiagram` | 包含关系图示(A ⊃ B ⊃ C 带计数) | 技术洞察 KPI 下方 | 1 |
| `DualStageBar` | 双色水平条(浅 P50 + 深 P95) | 技术洞察阶段表 | 2 |
| `DualTrendBar` | 双段柱(P95 外柱 + P50 内柱 + 基线) | 技术洞察趋势 | 2 |
| `ToggleFilter` | 快速 toggle 筛选按钮(布尔快筛) | 对话审查 | 2 |
| `GapTypeBadge` | 缺口类型标签(拒答灰/召回空红/低相关橙) | 技术洞察缺口 | 2 |

### 设计原则

- **纯 Tailwind + 内联 SVG**,不引 recharts/chart.js/d3。这些组件都是简单几何形状(矩形段+柱状),SVG 手写比图表库更轻更可控。
- **每个组件 < 80 行**,props 驱动,无内部状态(纯展示组件)。
- **颜色用 CSS 变量**,复用现有 `--acc`/`--warn`/`--err`/`--ok` 体系,不硬编码 hex。
- **暗色模式不处理**(现有体系未覆盖,后续统一做)。
- 每个组件配一个 vite 单元测试(vitest),验证 props → DOM 结构。

### 文件结构

```
admin/src/components/viz/
├── StackedBar.tsx
├── MiniTrend.tsx
├── ProgressBar.tsx
├── IntentColumn.tsx
├── StageBar.tsx
├── TraceSwimlane.tsx
├── LanesBar.tsx
├── NodeFlow.tsx
├── ContainmentDiagram.tsx
├── DualStageBar.tsx
├── DualTrendBar.tsx
├── ToggleFilter.tsx
├── GapTypeBadge.tsx
└── __tests__/
    ├── StackedBar.test.tsx
    └── ...
```

---

## 实施节奏

| 阶段 | 内容 | 周期 | 前置 |
|------|------|------|------|
| Phase 1 | 快赢层: 三页数据暴露 + 可视化组件库 | 1 周 | 无 |
| Phase 2 | 聚合层: 三页后端新查询 + 前端组件升级 | 1 周 | Phase 1 |
| Phase 3 评审 | 评估第三层是否值得做 | Phase 2 完成后 | Phase 2 |
| Phase 3 | 基础设施层(如评审通过) | 1-2 周 | 评审通过 |

<!-- 以上为文档正文,以下为审核修复记录 -->

---

## 🔍 Dual Review Log

### Round 1 — 2026-08-11 · 单路两阶段(独立 sub-agent)

| # | 级别 | 阶段 | 标准性质 | 位置 | 问题 | 修复动作 |
|---|------|------|---------|------|------|---------|
| 1 | HIGH | P1 | 事实核查 | Phase 1.2 区块对齐 | "实现现有 6 个"与代码不符,BusinessOverview.tsx 实际有 8 个区块(KPI行/意图分布/每日趋势/销售线索/场景应用/产品需求/热门问题/地域) | 重写区块对齐段,列出实际 8 区块 vs 设计稿 8 视觉块,明确差距在结构不在数量 |
| 2 | MEDIUM | P1 | 事实核查 | Phase 1.2 区块对齐 | "补齐到 8/8"数字逻辑不通 | 重写为"扁平意图分布(1块)替换为三列意图卡(3块),净增2" |
| 3 | MEDIUM | P1 | 事实核查 | Phase 1.1 trace_summary | "补返回 trace_summary"与代码矛盾(conversations.py L101 已返回) | 改为"trace_summary 已返回;前端 types/api.ts Conversation 接口补类型声明;trace_map 补 confidence" |
| 4 | MEDIUM | P1 | 事实核查 | Phase 1.3 阶段映射 | 映射不完整(只给2条);设计稿"路由"lane 在 rag.py 无数据源 | 加完整阶段映射表(4段列表 vs 5段详情);加⚠️说明"路由"lane 数据源折衷方案(从 intent 派生,精确计时留 Phase 2) |
| 5 | MEDIUM | P2 | 机械检测 | Phase 1.3 vs 2.1 | 4段/5段映射 intent 归类不一致(4段归前置,5段隐含归路由) | 映射表统一:intent 在4段归前置(intent+rewrite),在5段归路由 lane;Phase 1.3 和 2.1 交叉引用映射表 |
| 6 | LOW | P1 | 事实核查 | Phase 3.2 logger.warning | "只 logger.warning 不落库"不精确(retrieve 降级 path_counts 间接落库) | 改为"无专门 degraded/error_flags/retry_count 字段落库;retrieve 降级通过 path_counts 间接反映;LLM retry 完全丢失" |
| 7 | LOW | P2 | 主观意见 | Phase 1.2 区块计数 | "8个区块"口径模糊 | 在修复 #1 时明确定义"8视觉块 = 服务总览 + 三列意图 × 3 + 业务三列 × 3 + 地域" |

**本轮修复**: 7 个 | **累计修复**: 7 个
