# T26-CONV-LIST-UX Execution Contract(对话审查列表降噪)

- **Task ID**:t26-conv-list-ux | **Parent Initiative**:对话可观测体系(运营三页)/ 对话质量
- **Baseline Commit**:`bbfaa6a`(main = origin/main)
- **Risk Level**:**L1**(单页纯前端删减,后端零改动,无数据面)
- **Contract Authorization**:**AUTHORIZED**(2026-08-31,Role A 签发)——用户产品报告("每个对话记录显示一堆花花绿绿的进度条,显示效果很差…是否应该并入到详情,或者详情里面已有?");经查详情侧栏已有更全链路(E3),列表分段条属冗余中间层,删除+单行化无产品语义损失,在 A 的 UX 权限内。

## 1. Objective

对话审查列表行去掉四色分段耗时条,行内信号收敛为"扫描异常"所需(意图徽标 / markers 圆点 / 置信 / 状态 / 总耗时);阶段耗时诊断归详情侧栏(已有全链路)。

## 2. Current State / Evidence(Inspect @ bbfaa6a)

| # | 事实 | 级别 |
|---|---|---|
| E1 | 列表行渲染 `StageBar`(`Conversations.tsx:312` 起):四段聚合——前置(intent+rewrite,`--acc`)/ 检索(retrieve+rerank,`--ok`)/ 生成(generate,`--warn`)/ 输出(output,`--err`),容器 `max-w-[280px]` | FACT |
| E2 | `StageBar` 组件每段内嵌 11px `{key}{ms}ms` 文字;窄段放不下即溢出/截断(用户截图实证:出现 "b7n3216" 类乱码);四饱和色 × 每页 20 行 = 高视觉噪音;且颜色语义错位(输出段=红、检索段=绿,阶段非好坏) | FACT |
| E3 | 详情侧栏已有全链路:`TraceStageCard` × 6(意图分类/查询改写/路由检索/rerank/生成/输出,各含 ms+占比+进度条+阶段内部数据)+ 轮次选择器 + config snapshot + 总耗时——信息严格覆盖列表四段条 | FACT |
| E4 | 列表行右侧已有 `response_time_ms` 总耗时,三档着色(>10s err / >5s warn / 其他 ok)——列表的"耗时"扫描信号已存在 | FACT |
| E5 | 聚合层"哪个阶段慢"已有归属:技术洞察-技术性能「慢在哪(阶段 P50/P95)」`DualStageBar`(`Analytics.tsx:187`) | FACT |
| E6 | `StageBar` 唯一消费方即 `Conversations.tsx`(grep 实证);`Analytics` 用的是独立组件 `DualStageBar`;无任何测试引用 StageBar / data-seg | FACT |

## 3. Scope

- 删除列表行的 `StageBar` 渲染与 stages 聚合代码;
- 置信 % 保留,低置信(<0.6)着色逻辑不变;排布可调整至与问题同排(HOW 归 B;设计意图 = 行尽量单行化、信号不丢、不新增视觉元素);
- `admin/src/components/observability/StageBar.tsx` 组件与 import 一并删除(死代码清理);
- markers 圆点(重试/澄清/短路拒答/降级)保留不动。

## 4. Non-goals

详情侧栏任何改动;Analytics / DualStageBar;后端 / `trace_summary` 数据结构;置信与耗时的阈值调整;筛选与分页逻辑。

## 5. Change Boundary

**Product**:允许 = 列表行去掉分段条并收敛排布;必须不变 = 全部列表扫描信号、详情全链路、筛选/分页。
**Code EXPECTED**:`admin/src/pages/Conversations.tsx`、`admin/src/components/observability/StageBar.tsx`(删除)。
**CONDITIONAL**:构建/lint 层若存在对 StageBar 的残留引用(如 barrel export)同步清理。
**FORBIDDEN**:`admin/src/pages/Analytics.tsx`、`DualStageBar.tsx`、`backend/**`、`widget/**`、`Conversations.tsx` 内详情侧栏渲染段(selectedId 分支)。
**System**:无后端 / API / schema 变更。
**Regression**:admin vitest 全量 + `tsc --noEmit`;真实浏览器渲染验证。

## 6. Frozen Contract

1. 列表行不再渲染任何分段耗时条(无 `data-seg` DOM);
2. 每行保留信号:问题文本 + 意图徽标 + markers 圆点 + 置信 %(<0.6 黄,不变)+ 已回答/拒答 + 踩赞 + 总耗时(三档阈值不变);
3. 详情侧栏(全链路 trace / 轮次 / 置信 / 总耗时)行为与渲染不变;
4. 仓库无 `StageBar` 死引用。

## 7. Acceptance Criteria

- **AC1**:对话审查列表 ≥1 页真实数据渲染:无分段条、无截断乱码,行视觉降噪明显(截图证据,改动前后对照);
- **AC2**:详情侧栏选中任一行:6 张 TraceStageCard 正常渲染,抽查 2 条与改动前 ms 数值一致;
- **AC3**:快速筛选 4 toggle(低置信/重试/反馈/澄清)+ 意图/channel/关键词筛选 + 分页回归正常;
- **AC4**:admin vitest 全量绿 + `tsc --noEmit` 干净(grep 无 StageBar 残留引用);
- **AC5**:执行报告落 `docs/engineering/tasks/t26-conv-list-ux-execution.md`,状态 CANDIDATE READY(不 push、不部署)。

## 8. Verification 口径

本地:admin `npx vitest run` 全量、`tsc --noEmit`;真实浏览器(mac 本地 admin dev server)对话审查页操作 AC1-AC3。Playwright 可用既有 CLI 经验。

## 9. Parallel / 依赖

与 C8B(web_crawl 表单)/ T25A(健康度归属)文件域互斥(Conversations.tsx vs DataSources.tsx/Analytics.tsx),基线同为 `bbfaa6a`,可并行,合并无冲突预期。T25A 前置仍为 C8B 先并入 main。

---

## 10. Executor Prompt(可拷贝)

```markdown
# Role B 执行任务:T26-CONV-LIST-UX(对话审查列表降噪)

先完整阅读:
1. /Users/harryhua/Documents/GitHub/ask-ai/docs/engineering/DUAL_AGENT_PROTOCOL.md
2. /Users/harryhua/Documents/GitHub/ask-ai/docs/engineering/role-B.md
3. 契约:/Users/harryhua/Documents/GitHub/ask-ai/docs/engineering/tasks/t26-conv-list-ux-plan.md

## 任务
按契约删除对话审查列表行的四色分段耗时条并收敛行内排布;阶段耗时诊断归详情侧栏(已有全链路,不动)。删除 StageBar 组件及全部引用。

## 环境与边界
- 主仓:/Users/harryhua/Documents/GitHub/ask-ai(baseline = main = origin/main = bbfaa6a,开工前自行核实)
- worktree:/Users/harryhua/Documents/GitHub/ask-ai-t26-conv-list,分支 worktree-exec/t26-conv-list-ux
- Change Boundary 以契约 §5 为准:EXPECTED 仅 Conversations.tsx + 删除 StageBar.tsx;FORBIDDEN 含 Analytics.tsx / DualStageBar / backend / widget / 详情侧栏渲染段
- 测试红線:TEST_DATABASE_URL 仅用于后端测试(本任务纯前端,不涉及);不 push、不部署、不碰数据

## 实施要点
- 删列表 StageBar 渲染段(Conversations.tsx:309-343 附近的 trace_summary 分支)时保留置信 %(<0.6 黄)与 markers,勿动筛选/分页
- 置信 % 新排布 HOW 自定,设计意图:行尽量单行化、不新增视觉元素、信号不丢
- StageBar.tsx 删除后 grep 全仓确认零残留(admin/src 内)
- 如需本地渲染验证:admin dev server(vite,自有端口,勿占 5174 若被主仓占用);对话数据可用主仓本地后端 :8000

## 验证(全部实际执行,给证据)
1. admin `npx vitest run` 全量 + `tsc --noEmit`
2. 真实浏览器对话审查页:≥1 页数据渲染截图(AC1);选中 2 条对比详情 6 卡 ms 数值(AC2);4 toggle + 筛选 + 分页操作验证(AC3)
3. grep -rn "StageBar" admin/src 结果为空(AC4)

## 交付
- 报告:docs/engineering/tasks/t26-conv-list-ux-execution.md(按协议模板:Worktree/Branch、Baseline/Final Commit、Files Changed、Implementation、Verification actually executed、Runtime/Self-Check、Deviations/Risks、Status)
- 最终回复必须含:报告路径 + final commit + 状态(仅 CANDIDATE READY / PARTIAL / FAIL / BLOCKED)
- Gate 停等:本任务不 push,等 A Review 放行
```
