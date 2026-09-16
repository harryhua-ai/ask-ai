# Issue #58 GAP_MATRIX — Technical Insights 事件面 current→target 差距矩阵

- Executor: Trace Executor (harryhua-ai), ght claim `harryhua-ai-20260916T064131-d7d578f2`, mode=investigation, workflow=gap-matrix
- BASELINE: `b338c3c7eeafec9f57176aa82dd743b9f195153d` (origin/main, v1.6.3-r4 production)
- CANDIDATE_BRANCH: `agent/58/d7d578f2`(本提交=唯一证据提交,docs/** only,零代码改动)
- 设计权威: KB-OPS-V163-002 (`DESIGN_RECOVERY_REVIEW_V002.md` @ `docs/v163-design-baseline-20260912`@5593d6be) + Frozen Amendment(Issue 正文) + `v163-b2-technical-insights-contract.md` + Hard reference `references/technical-insights-answer-gaps-original.png`
- 执行契约: `role-a-execution-contract:v1`(Issue #58 评论 4):BATCH 2 / GAP_ONLY_IMPLEMENTATION / YES_AFTER_GAP_MATRIX

## 0. 范围与当前真值概览

Issue #58 的对象 = Technical Insights 页事件面(`admin/src/pages/Analytics.tsx` + `admin/src/pages/analytics/*`)。origin/main 上该面已经过 B2 收敛(b1e1b3a 合入)+ Wave 0B 拆分(c016d50)+ Wave 1 Track A-F,r4 已部署。事件面组件与证据:

- `admin/src/pages/analytics/IncidentSection.tsx`(266 行):同步/索引/生成事件信号区。行模型 `IncidentRow{typeKey,typeLabel,severity,eventAt,operatorNote,evidenceLines}`;排序 `SEVERITY_RANK error(0)<warning(1)<info(2)`,同级时间倒序;`rows.slice(0,10)` 截断;raw 证据(status/attempt/stage/duration/error_summary/fallback_reason/sync_log.error_detail;generation_id/ordinal/doc_count/chunk_count/failure JSON)全部收进默认折叠的 `<details data-incident-evidence>`;行 = `Link → /data-sources/{encodeURIComponent(sourceId)}`。
- `admin/src/pages/analytics/TechPerfTab.tsx`(315 行):PRIMARY `ServiceHealthBanner`(需要介入/服务降级/证据不足/暂无数据,后端确定性推导)→ SECONDARY KPI 三卡(分子/分母脚注)→ `IncidentSection` → DIAGNOSTIC 三列(`data-tech-grid3`:瓶颈在哪/什么异常/降级到什么)→ 趋势+信号关系 → `SourceHealthSummary`。stage 机器名经 `STAGE_LABELS` 转运营词(`data-stage` 保留机器值);anomaly 用 `a.label`(title=机器类型)。
- 测试:`admin/tests/TechInsight.test.tsx`(行聚合/严重度/下钻 href/空态/非重叠)、`admin/tests/TechInsightConvergence.test.tsx`(critical 先于新 info;raw attempt/stage/error 在折叠 details 内且 `open=false`;下钻 href 保留)。
- B2 执行报告 `docs/engineering/tasks/v163-b2-technical-insights-execution.md`:Engineering/Functional/Design 三门 PASS,15 MATCH,12 JUSTIFIED DIFFERENCE(待 Role A),DEFECT=0;下钻实测 F5/F11 MATCH。r4 验收报告(`reports/v163-r4-production-release-acceptance-20260915.md`)仅逐条验收 #71-#80,未含 #52-#60 —— 与 Issue 生命周期评论("r4 未完成本 Issue 完整冻结验收")一致。

## 1. current→target 矩阵(非 SUPERSEDED 验收标准逐条)

| # | 验收标准(Issue 正文 + 执行契约) | 判定 | 当前树证据(current) | 目标态(target,权威条款) |
|---|---|---|---|---|
| A1 | 默认事件行以简洁语言传达 what happened / impact / affected source / severity | **PARTIAL** | what happened=运营词 typeLabel(`lib/generationStatus.ts:33-46` 同步失败/同步中断/生成失败/已退役)✓;affected source=行内 sourceId+`data-source-id` ✓;severity=色点+`data-severity` ✓;**impact=缺失**:syncRunRow `operatorNote: null`(IncidentSection.tsx:233 附近);generationEventRow 仅 retired 上行 reason_summary,failed 行 `operatorNote: isFailed? null : …`;doc_count/chunk_count(生成失败影响面)与 duration/attempt(同步)留在折叠证据内,不在主行 | KB-OPS §7「operator-readable issue/event summary first, technical evidence secondary」+ B2 合同「Make incident rows operator-readable first」。target=失败行主行携带**已取回权威字段的事实性 impact 短语**(生成:影响 N 篇文档/M 块构建产物;同步:第 k 次尝试/耗时 t 秒),零新端点、零重算 |
| A2 | raw HTTP payloads / 内部 stages/classes/codes 移入渐进披露,证据保留 | **SATISFIED** | 全部 raw 收进默认折叠 `<details data-incident-evidence>`(点击翻转不触发导航);TechPerfTab stage/anomaly/degradation 均运营词+data-* 机器值;422 格式化仅存在于 fetch 错误路径(`lib/api.ts` T27),不在默认分析面 | 已达标;保持不回退(B2 合同 Forbidden「Letting raw diagnostics dominate primary hierarchy」) |
| A3 | critical incidents 视觉优先于 routine/low-impact | **SATISFIED** | 严重度优先排序(测试锁死:error 行先于更新的 info 行);severity 色点;PRIMARY 红色横幅(需要介入)+ KPI critical/warning tone;retired=info 不冒充失败(测试断言) | 已达标;保持(KB-OPS §7 exception-first visual priority) |
| A4 | 重复 incidents 可分组且不丢可审计性 | **MISSING** | 无任何分组:failed+interrupted+generation 逐事件铺行 → 排序 → `rows.slice(0,10)`;同源同类重复失败渲染为多条同形行,可挤占其他源的可见位;头部无「共 N 起 · 显示前 M」诚实计数(仅空态文案) | Issue 验收 checkbox 原文(非 superseded)+ 契约「Repeated incidents may be grouped without losing auditability」。target=(sourceId,typeKey) 维度客户端分组:组头=最高严重度+最新时间+「×N」,组内成员逐事件保留各自 evidence details 与下钻 href;可审计性=每事件证据不丢 |
| A5 | 瓶颈在哪 / 什么异常 / 降级到什么 信息层级清晰 | **SATISFIED** | `data-tech-grid3` 三列标题逐字对应;主导瓶颈高亮(`data-dominant-stage`)+基线语义行;异常语义着色(error=红/slow=琥珀,不按计数);降级 NodeFlow from→to+reason;整体层级 PRIMARY 横幅→KPI→事件区→三列→趋势 | 已达标(Issue 验收 checkbox;B2 合同 Expected) |
| A6 | related-source / conversation 下钻与既有深链保持 | **SATISFIED** | 事件行→`/data-sources/{id}`(href 编码测试断言);横幅→`/conversations?failure=true`;异常列→`/conversations`;GapPanel/PanelStats→`/conversations?q=`+相关数据源卡→`/data-sources/{id}`(Wave 1 Track F,解决 B2 J6);SourceHealthSummary→`/data-sources`;B2 F5/F11 实测 MATCH | 已达标;保持(#50 FROZEN INTERFACE 路由字符串不动) |
| A7 | 不重设计 telemetry、不删除诊断证据,仅改呈现层级 | **SATISFIED** | B2 diff 9 文件,后端仅新增只读端点(POST=405 pytest 断言);`failure` JSONB 原样透传进证据;sync 证据字段原样;无 mutation/无持久化变更(B2 §6 Scope audit) | 已达标;r5 实现延续同一边界(仅 admin/src 呈现层) |
| A8 | 截图/设计符合性评审强制 | **PENDING_IMPLEMENTATION**(非代码缺口) | B2 已产 12-JD Difference Ledger(待 Role A 裁决);r4 报告未覆盖 #52-#60 | KB-OPS §11 门:候选树真实渲染+截图+Ledger+DEFECT=0+Role A 接受;hard ref technical-insights-answer-gaps-original.png;r5 实现阶段执行 |
| P1 | focused tests(gap 行) | **PENDING_IMPLEMENTATION** | 既有 TechInsight/TechInsightConvergence 覆盖当前行为 | 随 A1/A4 实现补 focused cases |
| P2 | UI evidence(截图+Ledger) | **PENDING_IMPLEMENTATION** | 同 A8 | 实现阶段 |
| P3 | regression(vitest/tsc/build/pytest) | **PENDING_IMPLEMENTATION** | r4 基线全绿 | 实现阶段 |
| P4 | frozen-reference comparison(KB-OPS §11) | **PENDING_IMPLEMENTATION** | 同 A8 | 实现阶段 |

**SUPERSEDED 行:无。** 非 superseded 验收标准无一映射到被取代的 v001 语义。DESIGN HOLD 评论(评论 1)已被 Frozen Amendment + 生命周期评论(评论 2)取代,不构成实现依据;恢复设计中 观察工作流/OBSERVING 状态/CSV 导出/修复动作 = NEW REQUIREMENT(§5.5/§5.6/§10,v1.6.3 不授权)且属 #59 范围,不属于本 Issue 验收行,**MUST NOT IMPLEMENT**。

**DEPENDENCY 行:无。** A1/A4 的实现不依赖其他 Issue 的 merge。

## 2. 统计

SATISFIED 5(A2,A3,A5,A6,A7) · PARTIAL 1(A1) · MISSING 1(A4) · SUPERSEDED 0 · DEPENDENCY 0 · PENDING_IMPLEMENTATION 5(A8,P1-P4)

## 3. 最小改动边界提案(仅 A1/A4;本阶段零实现)

### B1. A1 — 失败行 impact 短语(PARTIAL→target)

- 文件边界(仅 1 个源文件):`admin/src/pages/analytics/IncidentSection.tsx`
- 改动:扩展 `operatorNote` 构造——
  - `generationEventRow`(failed):用**已取回**的权威字段拼事实短语,如 `影响 ${e.doc_count} 篇文档 / ${e.chunk_count} 块构建产物`(计数>0 才呈现,诚实缺省);
  - `syncRunRow`:如 `第 ${r.attempt ?? 1} 次尝试失败`、`耗时 ${r.duration_seconds}s`(字段存在才呈现);
  - raw 错误串/failure JSON 继续只进 evidenceLines(不回主行)。
- 约束:纯已取回 payload 的呈现投影;零新端点/零新 hook/零健康重算/零后端改动;retired 行为不变。
- 测试:扩展 `admin/tests/TechInsightConvergence.test.tsx`(或在同边界新增 focused 文件):failed 行主行文本含 doc/chunk impact 短语;sync 行含 attempt/duration 短语;retired 行不回归;evidence 折叠行为不变。
- 验收:vitest focused + tsc + build 绿;P2/P4 于 r5 以 hard reference 复核。

### B2. A4 — 重复事件分组、可审计(MISSING→target)

- 文件边界(仅 1 个源文件):`admin/src/pages/analytics/IncidentSection.tsx`(可与 B1 同一提交面)
- 改动:渲染层按 `(sourceId, typeKey)` 分组——组头行=成员最高 severity+最新 eventAt+「×N」徽章+组级下钻 href;组可展开,成员逐事件保留各自 evidence `<details>` 与独立 href;头部诚实计数「共 N 起 · 显示前 M」(数据源:sync.total/generation total 已在 payload)。
- 约束:仅在**已取回 latest-N**上分组(S3/S4 冻结面不变,零窗口参数/零 API 语义变更);分组是呈现聚合,不产生新事件实体、不合并/丢弃任何事件(可审计性=成员级证据完整保留)。
- 测试:focused cases——同源 3 条 sync_failed → 1 组头「×3」+成员可展开且各自 href/data-source-id/evidence 保留;异源不并组;严重度优先排序不回退;空态不变。
- 验收:同 B1;UI 证据经 P2 Ledger + P4 frozen-reference 门。

### CHANGE_BUDGET(建议随实现 claim 冻结)

- expected: `admin/src/pages/analytics/IncidentSection.tsx`、`admin/tests/TechInsightConvergence.test.tsx`(或一个新 focused 测试文件)
- conditional: 无
- forbidden: backend/**、widget/**、admin/src 其余文件(TechPerfTab/AnswerGapsTab/GapPanel/lib)、deploy/**、路由字符串、telemetry 语义
- 若 Role A 对 A1 裁定 JUSTIFIED DIFFERENCE(参考事件行无 impact 列),则 B1 取消,提案退化为仅 B2(或零改动);A4 为独立 MISSING,不受该裁定影响。

## 4. LIMITATIONS

- 本阶段为静态代码真值调查:无实时渲染、无截图(P2/P4 按设计属实现阶段交付)。
- 「运营可读」判断为代码/词表级;最终视觉权威 = Role A(KB-OPS §11)。
- 分组只能在已取回 latest-N 上进行(S3/S4 例外面冻结,本阶段不得引入窗口语义)。
- Hard reference PNG 内容为「回答缺口」Tab;技术性能 Tab 事件面以 §7 视觉语法 + Frozen Amendment 条款为权威。
- ght 单身份单活跃 claim 限制导致 claim 等待 ~35 分钟(并行 lane 轮换占用 #52/#53/#54/#56/#59);调查全程只读,零越权。

## 5. PRODUCTION_ACCESS

none(全程只读;零 SSH、零生产网络访问、零生产写入)

## 6. STATUS

**GAPS_FOUND**(A1 PARTIAL + A4 MISSING → 授权 r5 最小实现 B1+B2;其余 SATISFIED/SUPERSEDED 行零前端改动)
