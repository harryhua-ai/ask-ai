# Issue #54 GAP_MATRIX — current→target 差距矩阵与最小改动边界提案

- **Phase:** GAP_MATRIX（零代码改动;本阶段只产出矩阵 + 边界提案）
- **BASELINE:** b338c3c7eeafec9f57176aa82dd743b9f195153d（origin/main,当前真值树）
- **CANDIDATE_BRANCH:** agent/54/52290664（lane-2,investigation）
- **CANDIDATE_SHA:** 本阶段仅 docs/** 证据提交（见 preserve 后分支 tip）
- **SOURCE_OF_TRUTH:** KB-OPS-V163-002（DESIGN_RECOVERY_REVIEW_V002.md,冻结）+ 硬参考 `docs/product/design/admin-knowledge-ops/references/data-source-operations-original.png` + Issue #54 非 SUPERSEDED 验收标准 + role-a-execution-contract:v1
- **DEPENDENCY 基准:** `agent/83/e9436e81`@ad81119（lifecycle authority ⊨ repair authority,fail-closed,已验收未并 main）;`agent/84/d5000899`@9aa24e8（withdrawn-identity serving eligibility,backend-only,已验收未并 main）
- **PRODUCTION_ACCESS:** none
- **STATUS:** GAPS_FOUND

---

## 1. current→target 矩阵（13 行;统计:SATISFIED 5 / PARTIAL 4 / MISSING 0 / DEPENDENCY 2 / PENDING_IMPLEMENTATION 2 / SUPERSEDED 0）

| # | 验收标准 | 判定 | 当前树证据 | 目标态（恢复参考条款） |
| --- | --- | --- | --- | --- |
| 1 | Primary UI 使用 human-readable 运营语言 | **SATISFIED** | `admin/src/lib/dataSourceOps.ts` operatorStateOf（正常/需处理/降级/恢复中/过期/待分类/已禁用/同步失败/成员漂移/对账失败）;`admin/src/lib/dataSourceLifecycle.ts` lifecycle/generation 标签;`admin/src/pages/DataSourceDetail.tsx` 状态徽章/部分成功蓝链接/成功·失败词表;`SyncActivityPanel.tsx` 最近成功/最近结果/同步可靠性/同步周期/下次同步全部本地化。生产示例 `last run #3449 completed@DONE` 已不在默认视图(仅存于折叠证据串,见 #3/#6) | KB-OPS-V163-002 §4.2「lifecycle/version/generation/health 数据为工作流背后的证据」;§7「technical evidence secondary」 |
| 2 | Raw IDs/enums/thresholds/字段名/诊断码 移入可展开技术证据 | **SATISFIED** | DataSourceDetail.tsx L1019-1107 本地诊断整体 `<details>`(默认折叠);SyncActivityPanel 逐 run「技术证据」`<details>`(run_id/request_id/duration/fallback/业务结果);FailureEvidence 标注「后端 failure 原文」;source id/doc_source_id 收进 title(L350/L374/L671);生命周期 raw enum 仅存于 title=「技术过滤(生命周期词表)」的次级过滤器 | §4.2「Raw evidence remains available but is secondary」;§7 exception-first/normal-compact |
| 3 | Overall health 显式解释各组件健康如何汇入 rollup | **PARTIAL** | `admin/src/components/dataSources/SourceHealthPanel.tsx`:overall 徽章 + 六维徽章并排,维度级仅 `healthStateLabel` 本地化 + evidence 原文直呈;**无任何 overall↔维度贡献解释**。后端 `backend/api/admin/sync_runs.py:_overall_health` 的文档化优先级(EXCLUDED→RECOVERING→EMPTY_*→worst-of;unknown 不拖低;#21 sync=30天历史参考不驱动 overall;#71 currency 同级驱动 ACTION_REQUIRED)未在 UI 呈现任何一处 | §4.2 恢复层级要求健康数据作为「工作流背后的证据」并被解释;Issue 验收 3 |
| 4 | 「健康」不得与 degraded/unknown 组件自相矛盾(无解释时) | **PARTIAL** | 同 #3 位置:`/sync-health` 允许 overall=HEALTHY 且 sync=degraded(历史窗口)/coverage=unknown(有文档化理由),面板呈现「健康」徽章与「降级(历史30天)」「未知」徽章并置,**无 because 行**——Issue 生产反例(健康 vs 同步=降级+覆盖=未知)在折叠面板内仍可复现。页头操作者状态徽章(operatorStateOf)已消除顶层矛盾(HEALTHY→正常 前有需处理/中间态/成员漂移拦截),残余矛盾仅在健康面板内 | Issue 验收 4;§5.3「无统一分类不得推断」同纪律:解释须复述后端文档化优先级,禁止前端重判 |
| 5 | 时间戳 relative/local 为主,精确时间次级 | **PARTIAL** | SATISFIED 面:`RelativeTime`(相对+ISO title)覆盖行更新时间/last_sync/生成四时点/真相 created·updated·superseded;`formatSyncTime`(本地 "MM-DD HH:mm")覆盖活动时间线;valid_from 已人类化(A-P3-02)。**残余 2 处 raw ISO 作主呈现**:(a) SourceHealthPanel DimensionCard `截至 {dimension.as_of}`;(b) DataSourceDetail 修复验证卡 `完成于 {latest_repair_task.finished_at}`(L933)。notServingReason 内接替/墓碑时间为有意原样(psql 抽查口径,存于展开真相,可接受) | Issue 验收 5;§7 相对时间语法 |
| 6 | Freshness 以可理解单位表达「最近成功 + 允许阈值」 | **PARTIAL** | SATISFIED 面:freshness_overdue 琥珀横幅「已超过新鲜度要求(N 小时)」(DataSourceDetail L450-473,canWrite);健康面板新鲜度维状态词已本地化(新鲜/过期)。**残余**:阈值真值(threshold=2×sync_interval,`sync_runs.py:_freshness_dim`)仅以 raw 证据串「last success Xs ago (threshold=172800s)」呈现——即 Issue 生产示例 `threshold=172800s` 的现存出处;默认视图「同步周期 每 X 小时」是 cadence 而非 freshness 阈值;横幅仅在已过期且 Admin 可见时出现 | Issue 验收 6;§4.2 sync 摘要可理解化;禁令:不得在前端重推 2× 规则(后端权威),只允许对权威证据值做呈现层单位换算/本地化 |
| 7 | 技术证据保留可得且不主导默认视图 | **SATISFIED** | 默认视图=页头+横幅+知识工作区+同步活动;本地诊断(健康六维+索引生成)与逐 run 技术证据均为显式展开;索引生成表标注「仅用于技术核证;迁移哨兵不代表在服数量」 | §4.2/§7 |
| 8 | Design screenshot parity 为硬门 | **PENDING_IMPLEMENTATION** | 实现阶段门:KB-OPS-V163-002 §11(候选树真实渲染→约定视口截图→与 in-repo 硬参考并排→差异账本 MATCH/JUSTIFIED DIFFERENCE/DEFECT→DEFECT=0);B1 期账本见 `docs/engineering/tasks/v163-b1-data-source-operations-execution.md` §4(历史证据,非本阶段门) | §11 Release-blocking Design Conformance Gate |
| 9 | 层级恢复 identity→operator state→latest sync summary→total knowledge+needs-attention→attention banner→knowledge-content workspace→local diagnosis | **SATISFIED** | DataSourceDetail.tsx 注释 L59-64 + 结构:L316-448 页头(身份/品牌块+操作者状态徽章+最后同步相对时间+结果词表+账本总数+需处理数)→L450-473 U-12 新鲜度横幅(条件)→L475-535 红色 attention banner(权威原因逐类摘要+查看需处理)→L537-990 知识内容工作区(搜索/桶/生命周期/类型/排序/分页/行展开本地诊断)→L992-1016 同步状态与活动→L1018-1107 本地诊断(折叠) | KB-OPS-V163-002 §4.2 恢复层级 1-7;§4.4 sync 状态与活动 |
| 10 | 消费 #83 修正后 lifecycle/repair 真值 | **DEPENDENCY** | `agent/83/e9436e81`@ad81119(已验收,未并 main):isRetiredLifecycle 呈现层守卫+后端受理/执行 fail-closed+验证卡不宣称退役文档「已进入当前服务」。当前 main 的 DataSourceDetail 对 superseded/deleted 行仍提供「修复此知识/重新处理」入口(已知错误语义)。**契约禁止 #54 对其做表面重排;不计为 #54 前端 gap;#54 实现必须落在 #83 合入之后(或同树包含)** | role-a-execution-contract ISSUE-SPECIFIC;#83 RCA 裁决 |
| 11 | 消费 #84 修正后 serving 真值 | **DEPENDENCY** | `agent/84/d5000899`@9aa24e8(已验收,未并 main):backend-only(withdrawn identity 检索资格,fail-closed);前端 serving/chunk_serving 显示全部读权威端点(/documents、truth、verify_source_vectors 口径),合入后 UI 自动反映修正真值,**零前端改动需求** | 同上 |
| 12 | 无新 mutation/remediation 语义 | **SATISFIED（约束行）** | 本提案零新增 mutation;现存修复/调度/知识设置/预览均为既有权威契约(U-8/U-11/U-12/U-13,Track C 冻结语义,非 #54 引入);行级修复入口可用性变更属 #83 DEPENDENCY,非 #54 语义新增 | KB-OPS-V163-002 §10「NOT authorized:新 row-level reprocess/remediation semantics」 |
| 13 | focused tests + UI evidence + regression + frozen-reference comparison | **PENDING_IMPLEMENTATION** | 实现阶段验收(vitest 聚焦用例、渲染截图并排、回归、对照冻结参考) | §11;contract GLOBAL_GATES |

SUPERSEDED 记录:首条评论「DESIGN HOLD」已被 Issue 正文 KB-OPS-V163-002 Frozen Amendment 与第二条评论显式取代(KB-OPS-V163-001 语义禁止复活);无验收标准行映射为 SUPERSEDED。

---

## 2. 最小改动边界提案(仅 PARTIAL 非 DEPENDENCY 行;**本阶段不实现**)

**CHANGE_BUDGET:** admin/** 仅 4 个实现文件 + 3 个测试文件;backend 0 diff;零新组件/路由/mutation/依赖。实现授权后须以 #83+#84 合入后的树为基。

### R3+R4(overall rollup 解释 + 消除「健康」矛盾)— 1 个逻辑改动
- **边界:** `admin/src/lib/dataSourceObservability.ts` 新增纯函数 `overallRollupExplanation(item: SyncHealthItem): string[]`(呈现层:将 `_overall_health` 文档化优先级复述为操作者语言——如「整体=健康:连接/一致性/新鲜度/覆盖当前无异常;同步可靠性为近30天历史参考;覆盖证据不足按未知单维呈现,不拖低整体」;ACTION_REQUIRED/STALE/DEGRADED/RECOVERING/EMPTY_*/EXCLUDED 各给对应主因句;**零重判**:解释仅由 overall+维度权威 state 组合映射,未知组合→「按当前证据…」透传,不得派生第二健康态)。
- `admin/src/components/dataSources/SourceHealthPanel.tsx`:在 overall 徽章下渲染该解释行(次级样式),徽章/维度卡不动。
- **测试:** 扩展 `admin/tests/dataSources/SourceHealthPanel.test.tsx`(HEALTHY+sync degraded+coverage unknown 组合必须出现解释行;ACTION_REQUIRED/STALE 主因句)+ `dataSourceOps.test.ts`(纯函数表驱动)。
- **验收:** RED→GREEN vitest;§11 截图并排(本地诊断展开态)差异账本;`tsc -b` 0;零后端 diff。

### R5(残余 raw ISO 时间戳)
- **边界:** `SourceHealthPanel.tsx` DimensionCard `as_of` 与 `DataSourceDetail.tsx` 修复验证卡 `finished_at` 两处:主呈现改 `relativeTime`/`formatSyncTime`,原样 ISO 收进 `title`。`servingTimestamp` 保持原样(展开真相内 psql 核对口径,不属默认视图)。
- **测试:** `SourceHealthPanel.test.tsx`、`DataSourceDetailConvergence.test.tsx` 断言无裸 ISO 文本节点(有 title)。

### R6(freshness 阈值可理解化)
- **边界:** `admin/src/lib/dataSourceObservability.ts` 新增 `humanizeHealthEvidence(dim)`:仅对 freshness 维**已知权威证据格式**(`last success Xs ago (threshold=Ns)`、`no successful sync on record`、`source disabled` 等)做呈现层本地化(「最近成功 N 前;要求 N 小时内有成功同步」),原文整串收进 title;未知模式逐字透传(与 healthStateLabel 同纪律,不解析业务值、不重推 2× 规则)。DimensionCard 消费之。
- **测试:** `dataSourceOps.test.ts`/observability 单测(格式命中/未命中透传)+ `SourceHealthPanel.test.tsx`(freshness 卡呈现人类可读阈值)。
- **备选(不推荐本迭代):** 后端 /sync-health additive 只读 humanized 字段——超出最小前端边界,除非 Role A 裁决呈现层本地化不可接受。

### 依赖护栏(实现阶段)
- #83 合入前禁止触碰修复入口条件/验证卡呈现语义(其正确修法在 `agent/83/e9436e81`);#84 无前端行。
- 本提案零后端 diff、零 mutation、不合并 main、不关 Issue、不部署。

---

## 3. LIMITATIONS
- 静态代码证据(GIT 显示的 origin/main=b338c3c7 树),本阶段无运行时渲染/截图;§11 视觉门留待实现阶段。
- 第三条评论(2026-09-15)称「shipped r4 未完成本 Issue 冻结验收」;本矩阵按任务指定以 origin/main b338c3c7 为当前真值实测:层级/主语言/技术证据收纳确已在树内(B1+Wave1 已合),**健康 rollup 解释、freshness 阈值单位、2 处 raw ISO 为实测残余 gap**,与该评论「full frozen acceptance 未完成」结论相容。
- 候选分支 #83/#84 为「已验收未并 main」状态,DEPENDENCY 行不构成 #54 前端工作量。
