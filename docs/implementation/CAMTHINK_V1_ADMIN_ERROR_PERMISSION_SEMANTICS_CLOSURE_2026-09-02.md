# CAMTHINK V1 — AFP-CLOSURE-01 Admin Error & Permission Semantics Final Closure 执行报告

- 日期:2026-09-02
- 模式:SINGLE CODEX 实现
- 仓库:`harryhua-ai/ask-ai`
- 分支:`worktree-exec/afp-closure-01`
- 工作树:`/Users/harryhua/Documents/GitHub/ask-ai/.worktrees/afp-closure-01`

---

## A. STATUS

**STATUS = PASS(Executor 实现验证通过;不声明 Product FINAL ACCEPTANCE,等 Planner FINAL REVIEW)**

## B. REPOSITORY STATE

| 项 | 值 |
| --- | --- |
| BASELINE_COMMIT | `f32b3f4e3a95af0b5965b35f8971019158fdfd05`(精确起点,worktree 干净) |
| FINAL_COMMIT | `eb3b899724b8f4bf67154e18b6c3e197bf15eb63` |
| REPORT_COMMIT | 见文末交付字段(force-add) |
| BRANCH | `worktree-exec/afp-closure-01` |
| DISCOVERY 参照 | `667815d675ecc2f7e78af23f39c250eb33dbb9e2`(仅证据,未消费其提交) |

## C. ROOT CAUSE

1. **查询失败为何长得像空数据**:各页 react-query 消费只解构 `{ data, isLoading }`,`isError/error` 被丢弃;失败时 `data === undefined`,页面于是走「无数据」分支(空表文案/零值 KPI)或渲染空白——REQUEST_FAILURE 与 EMPTY_DATA 在呈现层完全同形。全局 `QueryClient` 也没有 QueryCache/MutationCache 错误兜底。
2. **mutation 失败为何静默**:全仓 mutation 钩子中仅 5 处自带 `onError` toast(useTriggerSync/useTriggerSyncAll/handoff/LLMProviders reload/ProviderEditDialog 内联),其余(annotations、overrides CRUD、customizations 全部、users 全部、providers 其余)**失败即无任何反馈**;且无全局兜底架构。
3. **Customizations 为何与众不同**:Final Polish 给其余页补 `canWrite` 门禁时,该页(绑定矩阵 + 接入配置)被遗漏——它没有任何 `useAuth` 引用,viewer 看到编辑/保存/绑定 select 全部可交互;后端 `EditorDep` 会 403,但该页 mutation 钩子无 onError → 403 被静默吞掉。

## D. IMPLEMENTATION

- **查询失败语义**:共享组件 `admin/src/components/LoadError.tsx`(`data-load-error`、`role="alert"`、错误 detail、可选**重试**按钮接 query `refetch`)。接入 9 个数据面:BusinessOverview(主概览)、Conversations(列表)、SalesLeads(列表)、Analytics(TechPerfTab + KnowledgeGapsTab 两个主查询)、Users、DataSources、Customizations、AnswerOverrides。呈现规则:`isError && !data` → 整态 LoadError;`isError && data`(refetchInterval 轮询页的最后已知数据)→ `compact` 横幅提示 + 内容保留;`isLoading` 期间**绝不**出现失败态(6.3)。
- **错误呈现架构**:不引入依赖;复用既有视觉原语与 NoPermission 同款样式语言。LLMProviders 既有失败处理**未动**(AC-11)。
- **mutation 失败架构**:`admin/src/lib/queryClient.ts::createQueryClient()` 挂 `MutationCache.onError` 全局兜底——mutation **自带 onError**(sync/sync-all/handoff/LLMProviders reload 等)则跳过(防重复 toast);**401** 不 toast(apiFetch 既有清 token + 跳登录即反馈);其余 toast `formatMutationError`(403 → 权限文案;其余 `操作失败:{detail}`)。`main.tsx` 改用该工厂。
- **403 语义**:`apiFetch` 对 403 固定抛「无权限执行此操作」(admin 面 403 = RBAC 角色不足;不透出框架 prose,6.7)。
- **401**:既有行为逐字未动(6.8)。
- **Customizations 角色**:页内 `canWrite = admin|editor`——「编辑」按钮 viewer 不渲染(viewer 因此不可达编辑/保存表单);渠道绑定 select `disabled` + `title` 说明「只读账号(viewer)不可修改渠道绑定」(6.5 的 hidden/clearly-disabled 双路径);admin/editor 能力不变(AC-14)。
- **空态保留**(6.4):「暂无销售线索 / 无匹配对话 / 暂无对话数据 / 暂无答案覆盖 / 暂无数据源」全部原样保留,只对成功空结果呈现(G003/G005 测试锁定)。

## E. FILES CHANGED

| 文件 | 变更 |
| --- | --- |
| `admin/src/components/LoadError.tsx` | 新增:共享失败态组件 |
| `admin/src/lib/queryClient.ts` | 新增:createQueryClient + MutationCache 全局兜底 + formatMutationError |
| `admin/src/lib/api.ts` | 403 固定权限文案 |
| `admin/src/main.tsx` | 改用 createQueryClient |
| `admin/src/pages/{BusinessOverview,Conversations,SalesLeads,Analytics,Users,DataSources,Customizations,AnswerOverrides}.tsx` | isError/error/refetch 解构 + LoadError 分支;Customizations 加 useAuth/canWrite 门禁 |
| `admin/tests/AfpClosure.test.tsx` | 新增:黄金场景 13 用例 |

零后端文件改动(`git diff f32b3f4 --stat -- backend/` 为空)。

## F. GOLDEN SCENARIOS

| 场景 | 结果 |
| --- | --- |
| AFP-G001 BusinessOverview 查询失败 | PASS(加载失败呈现;服务对话数 KPI 不出现) |
| AFP-G002 Conversations 查询失败 | PASS(失败态;「无匹配对话」「暂无对话数据」不顶替) |
| AFP-G003 SalesLeads 查询失败 | PASS(「暂无销售线索」留给成功空结果) |
| AFP-G004 Analytics 查询失败 | PASS(显式失败态,非静默空白) |
| AFP-G005 DataSources / AnswerOverrides | PASS(失败 vs「暂无数据源」/「暂无答案覆盖」可辨;成功空结果仍走空文案) |
| AFP-G006 Users(admin 失败显式;viewer 直达 → NoPermission) | PASS |
| AFP-G007 Customizations viewer 只读(admin 控件保留) | PASS(编辑不可见、select disabled;admin 反向断言) |
| AFP-G008 Customizations 绑定失败 403 | PASS(toast「无权限执行此操作」,不静默) |
| AFP-G009 全局 mutation 契约 | PASS(无 onError 的 mutation → 全局 toast;自带 onError 的 useTriggerSync 只出定制文案、toHaveBeenCalledTimes(1)) |

附加:AC-02 loading 不闪失败(挂起请求仅 loading)、AC-17 401 不 toast、成功空态保留断言。

## G. ACCEPTANCE

| AC | 结果 | 证据 |
| --- | --- | --- |
| AC-01 失败≠空 | PASS | G001~G006 |
| AC-02 loading≠failure | PASS | 附加测试(挂起 promise 仅 loading) |
| AC-03~AC-10 八页查询失败显式 | PASS | G001~G006 + Customizations/AnswerOverrides 用例 |
| AC-11 LLMProviders 不回归 | PASS | 既有 LLMProviders.test/useLLMProviders.test 全绿,代码未动 |
| AC-12 空态保留 | PASS | G003/G005 成功空分支 + 既有全量绿 |
| AC-13 viewer 无 Customizations 写能力 | PASS | G007 viewer 断言 |
| AC-14 admin/editor 能力保留 | PASS | G007 admin 断言 + 既有 Customizations 相关绿 |
| AC-15 mutation 失败可见 | PASS | G008/G009(全局架构) |
| AC-16 403 权限语义 | PASS | G008(apiFetch 固定文案断言) |
| AC-17 401 行为不变 | PASS | 附加断言 + api.ts 401 块未动 |
| AC-18 后端 RBAC 不变 | PASS | `git diff f32b3f4 -- backend/` 为空;RBAC 测试绿 |
| AC-19 AFP-006 即写语义不变 | PASS | 绑定 select onChange 即 mutate 未改(仅 disabled 门禁 + 失败 toast) |
| AC-20 删除生命周期未触碰 | PASS | data_sources.py 未改;test_data_source_delete* 全绿 |
| AC-21 全量回归/build 绿 | PASS | 185 admin vitest + tsc 0 + vite build ✓;后端 admin 套件绿(见 H) |
| AC-22 无越权扩展 | PASS | 变更清单即 §11 授权范围 |
| AC-23 无生产接触 | PASS | 全程本地 |

## H. TESTS(实际命令与结果)

| 命令 | 结果 |
| --- | --- |
| `vitest run tests/AfpClosure.test.tsx` | 13 passed |
| `vitest run`(admin 全量) | **185 passed(34+1 文件)**;基线 172 无一削弱 |
| `tsc -b --force`(admin) | exit 0 |
| `vite build`(admin) | ✓ built |
| `pytest tests/api/admin/ tests/test_lifespan_smoke.py tests/api/test_site_routes.py`(ask_ai_test) | 182 passed + 1 环境抖动(见 I) |
| `pytest test_auth + test_data_source_delete* + test_users + test_leads + test_ask_lead_flow` | 24 passed |
| `scripts/migrate_site_experiences_i18n.py`(对 ask_ai_test 测试库) | 补 i18n 两列 [ok](修复共享测试库 schema 陈旧,见 I) |

## I. REGRESSION EVIDENCE 与两次环境失败的处理(任务书 §13 纪律)

后端在本工作树与基线 **逐字节一致**(`git diff f32b3f4 --stat -- backend/` 为空),故任何后端失败必为环境性。实际遇到两例,均按「基线复现→记录→单列分类」处理:

1. `test_lifespan_smoke` 失败:`column site_experiences.welcome_i18n does not exist`——共享 `ask_ai_test` 库 schema 建于多语言闭环**之前**(缺 i18n 两列),lifespan seed 按 YAML 写入新列失败。属共享测试库 schema 漂移。处置:用仓库现成的幂等迁移脚本对 **测试库**(非生产)补列后,该测试转绿。基线证据:backend 零 diff。
2. `test_analytics_business::test_business_overview_geo_pct_and_90d` 偶发失败:共享 ask_ai_test 库并行会话数据注入(90 天窗口统计对共享行数敏感);隔离重跑 6/6 passed。属已知共享库抖动(项目记忆有档)。

其余 RBAC/Users/删除生命周期/Sales Leads/LLMProviders/登录行为全部绿(见 H)。

## J. PRODUCTION BOUNDARY

PRODUCTION_ACCESS = NO / PRODUCTION_MUTATION = NO(全程本地;测试库操作仅 ask_ai_test schema 对齐,不涉生产)。

## K. RESIDUAL RISKS

1. **未做真实浏览器走查**(§14 允许的替代):以确定性组件测试(renderToString/render + mock 网络)覆盖四类代表场景(查询失败/成功空/viewer 只读/mutation 失败);真实浏览器冒烟留给 Planner 验收或下一门。
2. `refetchInterval` 轮询页(DataSources)在「有旧数据 + 刷新失败」时呈现 compact 横幅 + 保留最后已知数据——横幅可见但数据为快照,操作者需知悉时间戳语义(既有列已展示 last_sync 时间)。
3. 全局 MutationCache 兜底未来新增 mutation 时**自动覆盖**;若某 mutation 需要定制文案,必须自带 onError(否则双路径不冲突但文案泛化)——已在 queryClient.ts 头注释注明。
4. 共享 ask_ai_test 库的 schema/数据漂移仍会偶发(本次已把 i18n 列对齐;并发抖动无法根治)。

## L. FOLLOW-UP(FUTURE,不挡 Final Unified Integration)

- AFP-006 渠道绑定草稿态(产品拍板后再议);
- SalesLeads「已移交销售」badge 的 destructive 红色语义复核;
- 真实浏览器 E2E 冒烟(与生产激活门合并做即可)。
