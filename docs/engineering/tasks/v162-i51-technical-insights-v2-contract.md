# FROZEN TASK CONTRACT — #51 Technical Insights V2(B2)

Iteration:v1.6.2;owner=B2;依赖:**FROZEN INTERFACE ← #50 = 路由字符串
`/data-sources/{source_id}` 本身**(Role A 已裁定:无代码级依赖,B2 自
origin/main 全并行开工);下钻端到端验收在 **Integration B 组合树**解析;
候选分支基于 origin/main;报告:docs/engineering/tasks/
v162-i51-technical-insights-v2-execution.md(B2 产出)。

## Objective

运营员在 `技术洞察` 完成两类回答,且**每条症状都能下钻到归因面**:
1. ASK-AI 技术上健康吗(性能/延迟/错误/降级)?
2. 同步/索引/生成/重建失败在哪里,是否影响回答质量?
3. 哪些回答缺口需要调查,证据链指向哪个对话/证据/源?

## Product Semantics

- 技术性能 = Trace/性能权威聚合(既有 /tech/performance 语义保持);
  事件信号 = sync_runs(failed/interrupted/stage/error/fallback)+
  index_generations(status/failure)权威表。**复用优先**:既有
  `/sync-runs`/`/sync-health` 读面能权威表达的(跨源同步失败/降级)
  直接消费;仅当既有端点无法权威表达(如 generation 级事件)才新增
  只读读面(新端点或 /tech 扩展;所有权冻结,不得复制 #50 逐源清单)。
- 回答缺口 = 既有权威证明(coverage-gaps miss_type 四类/gap-trends/
  conversations.is_answered/sources JSONB/Trace generation_error);
  不新增正确性契约、不虚构指标。
- 与数据源的分工(冻结):洞察页**零源清单/零源配置**;源事实一律
  下钻到 `/data-sources/{source_id}`(FROZEN INTERFACE)。

## UX Intent

- 保持双 tab 骨架(技术性能 / 知识缺口),重聚焦而非推倒:
  - TechPerf:现有面板保留;新增"同步/索引/生成事件"信号区(最近 N 条
    聚合事件,含源归属与严重度),事件行可下钻;
  - KnowledgeGaps:覆盖缺口行 → 对话核查面深链(既有 /conversations 路由
    + 既有过滤参数,B2 冻结具体参数语法);代表问题/缺口类型/数量/open-
    resolved 保留;
  - 全页下钻语义统一:症状 → 对话(/conversations)/ 源
    (/data-sources/{id})/ 追问核查面,用 react-router Link 深链 +
    既有查询参数,不新建弹窗式重复真相。
- 主操作:查看、过滤、下钻;**零新增写操作**(resolve/refresh 不在本合同)。

## Current Truth

V1 已有:TechPerf 全套(KPI/瓶颈/异常/降级链/健康横幅→失败对话深链)+
KnowledgeGaps(趋势/miss_type/缺口表);ServiceHealthBanner→
/conversations?failure=true 深链在案。
缺失:生成/同步事件信号区;缺口行→对话深链;事件→源详情深链(路由
尚不存在,来自 #50);resolve/refresh/top-questions hooks 零消费(本合同
不接线)。

## Change Boundary

- **EXPECTED**:事件信号区(优先复用既有读面;缺口面才新增只读读模型,
  B2 设计)+ 信号区 UI;缺口行/事件行下钻链接(路由字符串已冻结);
  必要的只读后端扩展测试;前端 vitest。
- **REQUIRED SUPPORTING**:生成状态(P 轴)→ 运营标签映射由 B2 自有
  (P 轴词汇与 #50 的 L 轴映射本就不同;若 B1 的映射模块已可用亦可复用);
  既有面板回归保护。
- **FORBIDDEN**:知识概览/源清单/源配置复刻;虚构指标;检索/排序/引用
  语义变更;gap resolve/refresh 与 top-questions UI 接线(显式推迟);
  重复 #50 详情真相;等待 B1 实现完成才开工(并行权已被授权)。
- **BEHAVIORAL**:既有 TechPerf/KnowledgeGaps 展示语义零回归;新端点
  只读;RBAC 不变。

## Dependencies

- inbound:#50 FROZEN INTERFACE = 路由字符串
  `/data-sources/{source_id}`(+ source_id 编码);**无代码级依赖**;
  下钻端到端验收在 Integration B 组合树执行。
- outbound:NONE。

## Acceptance Criteria

1. 事件信号区:展示最近同步/索引/生成失败与降级事件(源、类型、时间、
   原因摘要、严重度),数据全部来自权威表;空态显式;后端测试覆盖。
2. 下钻链路:事件行 → `/data-sources/{source_id}`(#50 面;链接实现于
   本任务,端到端点击验收在 Integration B 组合树执行);缺口行 →
   对话核查面(冻结参数语法);健康横幅既有深链保持。
3. 非重叠检查:洞察页不出现源清单/内容列表/源配置控件(测试或代码
   审查可证)。
4. 既有面板零回归(既有 TechInsight 测试全绿 + 新增覆盖);新端点只读。
5. 全量回归绿;ruff 0 error;admin vitest 全绿。

## Runtime / Real-World Acceptance(强制,Phase 5)

真实全栈伺服面上运营员走查(截图/转写):
- 从一个真实回答缺口簇 → 点达对话核查面(看到该对话的证据/来源);
- 从一个真实技术事件(如生产 index_generations failed ordinal=1 或任一
  failed sync_run)→ 点达归属数据源详情面;
- 确认技术洞察与数据源两页主职责 visibly 不重叠;
Issue 关闭前置:部署后生产可见面与本合同语义一致。
