# T25A-DS-HEALTH-OWNERSHIP Execution Contract(数据源健康度归属搬迁,Task #25 归属部分)

- **Task ID**:t25a-ds-health-ownership | **Parent Initiative**:Task #25(D-9 已拍板拆分的执行)
- **Baseline Commit**:待定——**前置:C8B(web_crawl 表单)合入 main 后开工**(同文件 `DataSources.tsx`,串行防碰撞)
- **Risk Level**:**L2**(纯 admin 前端搬迁,零后端改动)
- **Contract Authorization**:**AUTHORIZED**(2026-08-31,Role A 签发)——D-9 已拍板(2026-08-28):接入健康归数据源页 / 来源质量归因归技术洞察;用户 2026-08-31 再次确认现状不合理。无新产品语义。
- **UX 决策(Role A)**:健康度**融入数据源主表三列**(文档数/同步成功率/健康徽标),不另立第二张表(避免同页双表列同一批源)。

## 1. Objective

按 D-9 把接入健康呈现归还数据源页:技术洞察页删除"数据源健康度"表;数据源主表新增三列。技术洞察聚焦查询侧(性能 + 知识缺口/来源质量归因)。

## 2. Current State / Evidence(Inspect @ bbfaa6a)

| # | 事实 | 级别 |
|---|---|---|
| E1 | "数据源健康度"表在 `Analytics.tsx:270-315`(技术洞察页技术性能 tab):列=数据源/产品/文档数/同步成功率/健康徽标(healthy/degraded/critical),数据来自既有健康度 API | FACT |
| E2 | 数据源页主表现无健康度信息(仅同步触发/状态操作) | FACT |
| E3 | D-9(2026-08-28):接入健康(同步/一致性)归数据源页;来源质量归因归技术洞察(配合 eval) | FACT(决策记录) |

## 3. Scope

- `Analytics.tsx`:删除"数据源健康度"整节(含不再使用的导入/查询,若有他用则保留 hook);
- `DataSources.tsx` 主表:新增三列——文档数、同步成功率(%)、健康徽标(健康/降级/严重,沿用现有 Badge 语义);数据取自同一健康度 API;
- 测试:两页相应用例更新/新增(健康列渲染 + Analytics 不再渲染该节)。

## 4. Non-goals

后端/API/健康度计算逻辑零改动;eval 来源质量归因(未来 B4)不在本任务;主表现有列与操作(同步/编辑/删除)行为不变;Task #25 的"内容审查"部分不在本任务(范围待后续定义)。

## 5. Change Boundary

**Product**:允许 = 数据源页出现三列健康信息、技术洞察页移除该表;必须不变 = 两页其余全部内容与交互、健康度 API 口径。
**Code EXPECTED**:`admin/src/pages/Analytics.tsx`、`admin/src/pages/DataSources.tsx`、`admin/tests/*`。
**CONDITIONAL**:健康度 hook 文件小改(若需挪位置/解除仅 Analytics 依赖)。
**FORBIDDEN**:`backend/**`、`widget/**`、健康度计算后端逻辑、其他页面。
**System**:无后端/API/schema 变更。
**Regression**:Analytics 性能 KPI/降级链路/知识缺口零变化;两页 vitest 全绿 + tsc。

## 6. Frozen Contract

1. 技术洞察页不再含"数据源健康度"节;
2. 数据源主表每行含文档数/同步成功率/健康徽标,与 API 数据一致;
3. 健康徽标三态语义与原表一致(健康/降级/严重);
4. 后端零改动。

## 7. Acceptance Criteria

| # | 验收 | 标准 |
|---|---|---|
| AC1 | 数据源页 | 真实 UI:主表三列渲染正确,抽样 3 源与 API 原始值一致 |
| AC2 | 技术洞察页 | 真实 UI:该节已移除,其余(KPI/降级/知识缺口 tab)原样 |
| AC3 | 回归 | admin vitest 全绿 + tsc 干净;Analytics 既有用例仅移除健康度部分断言,不得削弱其余 |

Real-World Gate:AC1/AC2 真实浏览器查看(协议 §10)。

## 8. Required Verification

TDD(新列渲染先红后绿);全量 vitest + tsc;真实 UI 两页查看;前置检查:C8B 已在 main。

---

## 执行提示词(C8B 合入后复制给执行端)

```text
# 任务:T25A-DS-HEALTH-OWNERSHIP(数据源健康度归属搬迁)

先读权威契约:
- /Users/harryhua/Documents/GitHub/ask-ai/docs/engineering/tasks/t25a-ds-health-ownership-plan.md

前置检查:C8B(web_crawl 表单)已合入 main(同文件串行);git log 确认后开独立 worktree。

要点:
1. Analytics.tsx 删除"数据源健康度"整节(:270-315 一带,含仅其使用的导入/查询);
2. DataSources.tsx 主表新增三列:文档数 / 同步成功率(%) / 健康徽标
   (健康=default/降级=secondary/严重=destructive,与原表语义一致),
   数据取自同一健康度 API;不另立第二张表;
3. 后端零改动;
4. 验证:TDD + admin vitest 全量 + tsc;真实 UI 两页查看
   (数据源页三列与 API 抽样一致;技术洞察该节已移除且其余原样);
5. 报告:docs/engineering/tasks/t25a-ds-health-ownership-execution.md(v2.0 §77 字段),
   回复给报告路径 + commit + 状态。

红线:backend/**、widget/** 零改动;不 push;docs/ 不进主仓;
Analytics 其余断言不得削弱。
```
