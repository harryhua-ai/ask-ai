# CAMTHINK V1 — Admin Final Polish Re-triage(只读 Discovery)报告

- 日期:2026-09-02
- 模式:READ-ONLY DISCOVERY(无实现提交;仅本报告入仓)
- 仓库:`harryhua-ai/ask-ai`
- 基线:`f32b3f4e3a95af0b5965b35f8971019158fdfd05`(多语言闭环实现,Planner FINAL REVIEW = PASS/CLOSED)
- 工作树:`/Users/harryhua/Documents/GitHub/ask-ai/.worktrees/admin-retriage`(分支 `discovery/admin-polish-retriage-2026-09-02`,干净)
- 结论速览:**11 项旧发现中 9 项 SUPERSEDED、1 项 FUTURE、1 项 KEEP(部分残留,与 AFP-002 残留合并为一个共享收口项);无 NEW-V1;目标批次 = 1 项**

---

## 1. 当前 Admin 表面盘点(以 f32b3f4 代码为准,不沿用旧页数)

路由(`admin/src/App.tsx`)+ 侧栏(`Sidebar.tsx`)实存 9 个认证页 + 登录页:

| 页面 | 路由 | 可见角色(侧栏) | 写门禁 |
| --- | --- | --- | --- |
| BusinessOverview 业务概览 | `/` | admin/editor/viewer | 只读 |
| SalesLeads 销售线索 | `/leads` | admin/editor/viewer | `canHandoff`(admin/editor) |
| Conversations 对话审查 | `/conversations` | admin/editor/viewer | `canWrite`(批量标注) |
| Analytics 技术洞察 | `/analytics` | admin/editor/viewer | 只读 |
| Users 用户管理 | `/users` | **仅 admin** | NonAdmin → `NoPermission` 显式态 |
| DataSources 数据源 | `/data-sources` | admin/editor/viewer | `canWrite` |
| Customizations 对话接入 | `/customizations` | admin/editor/viewer | **⚠️ 无客户端门禁(残留,见 AFP-002/008)** |
| LLMProviders 模型配置 | `/llm-providers` | admin/editor/viewer | `canWrite` + isError 处理 |
| AnswerOverrides 答案覆盖 | `/answer-overrides` | admin/editor/viewer | `canWrite` |
| Login 登录 | `/admin/login` | 公开 | — |

后端 RBAC:逐端点 `require_role(...)` 三角色依赖(`backend/auth/dependencies.py`),viewer 侧 `ViewerDep` 覆盖全部只读端点;写端点 `EditorDep`/`AdminDep`。

## 2. 重审矩阵(RETRIAGE MATRIX)

### AFP-001 — 删除源残留陈旧语料

- **CURRENT_STATE**:删除端点(`backend/api/admin/data_sources.py::delete_data_source`,代码内显式标注「AFP-001 生命周期契约」)现为三步失败安全流:①按 `source_id` 字面前缀(`startswith(autoescape=True)`,AC-FIX-01:杜绝 LIKE 通配符越界)枚举账本文档;②清 Weaviate 向量——两段式:账本段对每个已知 source_id 做 Equal 精确删除,兜底段以 `prefix + "/"` 为严格边界迭代器全扫收集孤儿 chunk 后**逐 UUID 点删**;失败 → 502 + 配置与账本原样保留(可重试,绝不假报成功);③同一事务删 documents 账本行 + 配置行。
- **EVIDENCE**:`_purge_source_corpus_sync`/`delete_data_source` 源码;测试 `tests/api/admin/test_data_source_delete.py`(purge+行删除/不吸他源/502 可观察且状态保留/404/前缀边界安全)+ `test_data_source_delete_wildcards.py`(通配 id 字面量删除);AC-FIX-01/02 注释(262c1fc)。
- **CLASSIFICATION**:**SUPERSEDED**
- **V1_IMPACT**:无(旧框架下无遗留问题)
- **RECOMMENDED_NEXT_ACTION**:不要实现旧提议的宽前缀清理——它会重新引入 P0-A 的 TEXT 分词过匹配毁灭性删除模式。现行实现已与 sync 生命周期契约兼容:**Equal 精确删除走账本已知 source_id(非抽取缺席推断)**,孤儿兜底经迭代器边界收集后逐 UUID 点删(非宽 bulk);operator 显式删除(operator intent)与 sync 抽取缺席退休(SOURCE-CONFIRMED,权威成员集)是两条语义不同的路径,当前解耦是正确设计。仅存的可选冻结点(部分失败重试语义)已由「502 + 保留全部状态」实现并被测试锁定。

### AFP-002 — Viewer 写控件可见 + 403 被吞为空表

- **CURRENT_STATE**:①写控件门禁:`canWrite`/`canHandoff` 已遍布 DataSources/LLMProviders/AnswerOverrides/Conversations/SalesLeads;后端逐端点 require_role。②403 语义:`apiFetch` 401 跳登录、非 2xx 抛 `ApiError`(detail 经 T27 扁平化为可读文本);`NoPermission` 组件(标注「AFP-002/008」)用于 /users 非 admin 直达。**残留一点**:`Customizations.tsx` 无 `useAuth`/`canWrite` 门禁——viewer 可见编辑/保存/渠道绑定 select 全部交互控件;且该页 mutation 钩子(`useCustomizations.ts` 三个 hook)**无 onError** → 失败(含 403)无任何 toast,静默无反馈;全局 `QueryClient` 亦无 MutationCache/QueryCache onError 兜底。
- **EVIDENCE**:五页 canWrite/canHandoff grep 实证;`NoPermission.tsx`;`require_role` 定义;viewer RBAC 测试(test_answer_overrides viewer fixture 等);Customizations 全文无 useAuth;useCustomizations 三 hook 仅 onSuccess。
- **CLASSIFICATION**:**SUPERSEDED**(残留一点并入 AFP-008 的共享收口项,不重复立项)
- **V1_IMPACT**:残留点影响权限语义可感知性(viewer 误以为可写、失败无反馈)
- **RECOMMENDED_NEXT_ACTION**:见 V1 批次 AFP-CLOSURE-01

### AFP-003 — 登录页透出原始校验/错误文本

- **CURRENT_STATE**:`Login.tsx` 顶部显式「AFP-003:登录失败文案映射 —— 不透出后端/Pydantic 原始校验 prose」,所有失败统一映射为「登录失败,请稍后再试」类安全文案。
- **EVIDENCE**:`admin/src/pages/Login.tsx:8-13`。
- **CLASSIFICATION**:**SUPERSEDED**
- **V1_IMPACT**:无
- **RECOMMENDED_NEXT_ACTION**:无

### AFP-004 —「总服务客户」指标名实不符

- **CURRENT_STATE**:KPI 现为「服务对话数 / 销售咨询 / 销售线索 / 满意度」;Sales Lead 集成后口径显式分离——`business.py` 注释「独立 sales_leads 口径,不再把 commercial 对话(意图口径)当作线索」,前端「销售咨询」(意图分布)与「销售线索」(leads 表)是两个独立 KPI。
- **EVIDENCE**:`BusinessOverview.tsx:90-110`(KPI 标签)、`backend/api/admin/business.py:137-139`(口径注释);test_analytics_business.py 已随 Sales Lead 更新。
- **CLASSIFICATION**:**SUPERSEDED**
- **V1_IMPACT**:无
- **RECOMMENDED_NEXT_ACTION**:无

### AFP-005 — Retry 过滤器疑似失效

- **CURRENT_STATE**:过滤器已接线:前端「重试」toggle → `has_retry` 参数 → 后端标记语义(`conversations.py::_derive_markers`,OBS-03 调查定案):retry 仅认显式 `retry_count` 字段(生产 trace 无此字段;error 是错误证据不是重试证据,不虚标)。空结果为诚实反映数据现状,非死过滤器。
- **EVIDENCE**:`Conversations.tsx:99-119,247-249`;`backend/api/admin/conversations.py:20-35`;`tests/api/admin/test_conversations.py::test_list_conversations_has_retry_filter`。
- **CLASSIFICATION**:**SUPERSEDED**
- **V1_IMPACT**:无(生产数据暂无 retry_count,过滤器合法返回空——语义已文档化)
- **RECOMMENDED_NEXT_ACTION**:无

### AFP-006 — 渠道绑定即写无暂存

- **CURRENT_STATE**:行为确认未变——绑定 select `onChange` 即 `updateBinding.mutate`(自动提交模式),无草稿/暂存态;select 值经缓存失效即时回显,失败时有 Toast 吗?——无(useUpdateBinding 无 onError,与 AFP-002 残留同根,已并入批次项的错误反馈要求)。
- **EVIDENCE**:`Customizations.tsx:58-66,143`;`useCustomizations.ts:58-75`。
- **CLASSIFICATION**:**FUTURE**
- **V1_IMPACT**:低——单选自动提交是常见设置模式,有即时视觉回显;无正确性风险。是否改草稿态属产品偏好。
- **RECOMMENDED_NEXT_ACTION**:V1 不动;若未来做,可与「绑定操作失败 toast」(已含在批次项)一并评估。

### AFP-007 — 澄清漏斗占位/不完整

- **CURRENT_STATE**:澄清漏斗占位 UI 已在 Final Polish(占位移除项)中移除,现 BusinessOverview/Analytics 均无 clarify/funnel 残留渲染——不展示即不误导。
- **EVIDENCE**:两页全文 grep `澄清|clarify|funnel` 零命中。
- **CLASSIFICATION**:**SUPERSEDED**
- **V1_IMPACT**:无
- **RECOMMENDED_NEXT_ACTION**:无

### AFP-008 — 空态/无权限/失败不可分辨

- **CURRENT_STATE**:三分之二已收口——**EMPTY ✓**(显式空文案,如对话审查「无匹配对话:当前筛选…」、线索「暂无销售线索 —— 达到合格资格…」、覆盖「暂无答案覆盖」);**NO_PERMISSION ✓**(NoPermission 组件 + RBAC 真相:viewer 可读全部其可见页,读路径不再产生 403)。**REQUEST_FAILURE ✗ 残留**:除 LLMProviders(isError=2)外,所有数据页 useQuery 均不处理 error——后端 500/网络失败渲染为**零值 KPI 卡/空表**,与「没有数据」不可辨;无全局 QueryCache/MutationCache onError。本次全页面盘 empirico:isError 计数 Analytics=0/BusinessOverview=0/Conversations=0/SalesLeads=0/DataSources=0/AnswerOverrides=0。
- **EVIDENCE**:各页 isError grep 统计;`main.tsx` QueryClient 仅配 retry;Conversations 空文案 `:273`;NoPermission 组件;useCustomizations 无 onError。
- **CLASSIFICATION**:**KEEP**(P2)——与 AFP-002 残留为**同一个共享 Admin 错误语义收口**(任务书预期的一类合并,不立两项)
- **V1_IMPACT**:影响正确解释与生产可支持性:后端瞬时失败时,运营/支持人员会把「加载失败」误读为「今日 0 对话/无线索」。
- **RECOMMENDED_NEXT_ACTION**:见 V1 批次 AFP-CLOSURE-01

### AFP-009 — P50/P95 图表过度告警红

- **CURRENT_STATE**:配色已语义化——P50/P95 条默认 `--acc`(accent),仅当日 `p95 > baseline`(越限)才 `--err`(红);配告警基线虚线 + 逐柱 tooltip(`日期: P50 x / P95 y`)与 y 轴刻度。红=真实越限告警,非装饰性全红。
- **EVIDENCE**:`DualTrendBar.tsx`(over 条件 + title)、`DualStageBar.tsx`(同款 over 语义)、`Analytics.tsx:117-118`(基线口径注释)。
- **CLASSIFICATION**:**SUPERSEDED**
- **V1_IMPACT**:无(现配色承载真实告警语义,不应改回中性色)
- **RECOMMENDED_NEXT_ACTION**:无

### AFP-010 — Trace 状态点无图例

- **CURRENT_STATE**:状态点(marker dots)现带逐点 `title` 提示(「生成失败」「重试」「触发澄清」等),且正上方过滤栏有同语义中文标签 toggle(失败/重试/触发澄清)互为图例;T26 对话审查列表降噪有意保留 markers/徽标(决策记录在提交 90dff34)。
- **EVIDENCE**:`Conversations.tsx:297-323`(title 属性)、`:241-259`(标签 toggle)。
- **CLASSIFICATION**:**SUPERSEDED**
- **V1_IMPACT**:无
- **RECOMMENDED_NEXT_ACTION**:无

### AFP-011 — 用户生命周期管理

- **CURRENT_STATE**:基础用户生命周期已实现——Users 页(admin 独占,非 admin 显式 NoPermission)支持创建用户(邮箱+密码+角色)、列表;后端 `users.py` 提供 list/create/update/delete(UserUpdate/UserDelete,AdminDep)。
- **EVIDENCE**:`admin/src/pages/Users.tsx:22-71`;`backend/api/admin/users.py:20-78`;`tests/api/admin/test_users.py`。
- **CLASSIFICATION**:**SUPERSEDED**(超出旧 FUTURE 预期——基础能力已交付)
- **V1_IMPACT**:无 V1 blocker
- **RECOMMENDED_NEXT_ACTION**:密码找回邮件流/操作审计等增强留待 V1 后评估(不另立条目)

## 3. NEW 发现扫描(高门槛)

- **NEW-V1:无。** 残留错误语义问题已由 AFP-008 KEEP 项承载,不重复立项;其余表面未发现可复现的、实质影响 V1 的新问题。
- **NEW-FUTURE(仅登记,不进批次):** ①SalesLeads「已移交销售」Badge 用 `variant="destructive"`(红=危险语义)表达完成态,视觉语义存疑;②全局 `MutationCache.onError` 兜底可作为架构级改进(本批次项已要求每 mutation 可见反馈,达同等效果)。

## 4. V1_ADMIN_CLOSURE_BATCH(目标 0-3,实际 1 项)

### AFP-CLOSURE-01 — Admin 错误语义显式化收口(REQUEST_FAILURE ≠ EMPTY ≠ NO_PERMISSION)

- **TASK_ID**:AFP-CLOSURE-01(承载 AFP-002 残留 + AFP-008 残留)
- **OBJECTIVE**:任一管理页面上,「没有数据」「无权限」「加载失败」三种状态全局可辨,全部写操作失败有可见反馈。
- **FROZEN_PRODUCT_BEHAVIOR**:
  1. 数据页任一读取失败(4xx/5xx/网络)→ 页面级**显式失败态**(含可读错误信息;与空数据态视觉可分);不得以零值 KPI/空表呈现失败;
  2. `Customizations` 对 viewer 隐藏/禁用全部写控件(编辑/保存/渠道绑定),与 DataSources 等页 `canWrite` 同语义;
  3. 全部 mutation 失败必须有可见反馈(toast,含后端 detail);403 呈现权限语义;
  4. 401 跳登录既有行为不变;既有 RBAC/后端语义零改动。
- **NON_GOALS**:不改后端 RBAC;不做渠道绑定草稿态(AFP-006 FUTURE);不改 P50/P95 配色;不做登录页/用户生命周期扩展;不引入新依赖。
- **ACCEPTANCE_CRITERIA**:
  - AC-A:mock 任一数据页查询 reject → 渲染显式失败态 DOM(且非空表/非零值),BusinessOverview/Conversations/SalesLeads/Analytics/DataSources/AnswerOverrides 覆盖;
  - AC-B:viewer 角色渲染 `/customizations` → 无可交互写控件(或明确禁用+说明);
  - AC-C:Customizations 保存/绑定失败 → 错误 toast 含后端 detail(403 场景断言权限文案);
  - AC-D:既有 admin vitest 172 项 + 后端 RBAC/删除生命周期套件零回归;tsc/build 绿。
- **REQUIRED_REGRESSION**:admin vitest 全量、admin `tsc -b --force` + vite build、后端 `tests/api/admin/`(RBAC/删除生命周期/leads)、`tests/test_lifespan_smoke.py`。
- **RISK**:低——纯前端呈现层;唯一注意点:失败态不得在 loading 期间闪现(isLoading 与 isError 互斥处理)。

## 5. 下一步执行拓扑建议

**RECOMMENDED_EXECUTION_MODE = SINGLE CODEX**
理由:仅 1 项;改动集中于共享错误态组件 + Customizations 单页 + mutation hooks;并行只会增加集成开销。

## 6. 只读验证记录(TESTS_AND_CHECKS)

| 检查 | 结果 |
| --- | --- |
| admin `tsc -b --force` | exit 0 |
| admin vitest 全量 | 172 passed(34 文件) |
| 后端 RBAC/删除生命周期/用户/线索测试(test_auth/test_data_source_delete*/test_users/test_leads) | 21 passed |
| 静态盘点 | 9 页路由+侧栏、10 个 AFP 相关源文件、isError 全页统计、空态文案实证 |

(执行环境:工作树内 node_modules 以软链复用主仓依赖;未修改任何源码/测试。)

## 7. 生产边界

PRODUCTION_ACCESS = NO / PRODUCTION_MUTATION = NO(全程仅仓库源码、测试与本地工具链)
