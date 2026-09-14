# V1.6.3 User Acceptance Reconciliation（#52–#67 全量对账）

- 性质：PLANNING ONLY（Role A 委任 reconciliation + r3 planning）。本文档零实现、零 Issue 关闭、零状态宣告。
- 治理正名（冻结）：Product Iteration = **v1.6.3**（唯一迭代名）；Current production release = **v1.6.3-r2**（fd5ca39）；Next corrective release = **v1.6.3-r3**（Release revision ≠ Product Iteration）。v1.6.3 仅在最终 User Acceptance 完成+相关 Issue 满足关闭条件后才可宣告 COMPLETE。
- 基线：fresh main = `94ddb64`；生产身份 = v1.6.3-r2 @ fd5ca39（restarts=0 / ERROR=0）。
- 权威输入：
  - r2 生产符合性报告：`docs/engineering/tasks/v163-r2-production-conformance.md`（功能 ledger A–F、§5 语义不变量、§6 设计 ledger MATCH 26/UADC 4/PSNP 5/DEFECT 0、正交观察 5 条）
  - 152 行权威矩阵：`ask-ai-v163-audit/docs/engineering/tasks/v163-reference-remediation/matrix-{DS-P1,DS-P2,DS-P3-P4,DS-P5-P6-P7,SH,TI}.md`（24+27+20+20+16+45 = 152 行）
  - Role A 已批准 r3 数据源详情页 APPROVED DESIGN INPUT：`/tmp/v163-refs/r3-ds-detail-approved-design.png`（已亲读）
  - 本次 User Acceptance 新发现 Issues **#61–#67**（用户验收产出本身即验收证据）

---

## PHASE 1 — Project Reconciliation 证据

### 1.1 操作记录（Project = `@harryhua-ai's ask-ai project`，PVT_kwHOAgcvyM4Bisg3，number 2）

字段：`Iteration`（PVTIF_lAHOAgcvyM4Bisg3zhhk-sE；iteration v1.6.3 = `4ce642b8`）、`Priority`（PVTSSF_lAHOAgcvyM4Bisg3zhhji3A；选项 P0/P1/P2）。

| Issue | item_id | Iteration before | Priority before | Iteration after | Priority after | Labels before | Labels after | 状态 |
|---|---|---|---|---|---|---|---|---|
| #61 | PVTI_lAHOAgcvyM4Bisg3zg6zLbQ | unset | P1 | **v1.6.3** | P1 | priority:p1, schedule:current | 不变 | OPEN 保持 |
| #62 | PVTI_lAHOAgcvyM4Bisg3zg6zMm8 | unset | P1 | **v1.6.3** | P1 | priority:p1, schedule:current | 不变 | OPEN 保持 |
| #63 | PVTI_lAHOAgcvyM4Bisg3zg6zPDM | unset | P1 | **v1.6.3** | P1 | priority:p1, schedule:current | 不变 | OPEN 保持 |
| #64 | PVTI_lAHOAgcvyM4Bisg3zg6zQzs | unset | P1 | **v1.6.3** | P1 | priority:p1, schedule:current | 不变 | OPEN 保持 |
| #65 | PVTI_lAHOAgcvyM4Bisg3zg6zUHA | unset | P1 | **v1.6.3** | P1 | priority:p1, schedule:current | 不变 | OPEN 保持 |
| #66 | PVTI_lAHOAgcvyM4Bisg3zg6zWec | unset | None | **v1.6.3** | **P1** | （无标签） | **priority:p1, schedule:current** | OPEN 保持 |
| #67 | PVTI_lAHOAgcvyM4Bisg3zg6zdSA | unset | P1 | **v1.6.3** | P1 | priority:p1, schedule:current | 不变 | OPEN 保持 |

- 操作：7 次 `gh project item-edit --iteration-id 4ce642b8`（#66 首次未生效，重试成功）；#66 追加 `priority:p1` 标签（`gh issue edit 66 --add-label priority:p1`）+ Project Priority 字段 P1（option id `0a877460`）；#66 追加 `schedule:current`（对齐兄弟 UA issues 的既有调度标签，属「必要状态对齐」授权范围）。
- 边界遵守：#52–#60 的 Project 状态/字段**零改动**（复核 after-state：全部 OPEN + P1 + v1.6.3，与 before 一致）；全部 16 个 iteration issue 状态保持 OPEN；未关闭任何 Issue；未宣告 v1.6.3 COMPLETE。
- 字段冲突/选项缺失：无（v1.6.3 iteration 与 P1 选项均已在位，未新建任何字段/选项）。

### 1.2 Fresh Project/main 状态快照

- Project：#52–#60（9 项）+ #61–#67（7 项）= **16 个 OPEN issue 全部在 iteration v1.6.3 / Priority P1**。
- main `94ddb64` = R2 发布执行报告 commit；生产树与 main 一致（v1.6.3-r2 @ fd5ca39 部署自该 lineage）。
- 生产健康：backend/sync-cron/sync-executor = v1.6.3-r2 镜像、restarts=0、healthy、PG/Weaviate healthy（本 planning 期间 SSH 只读复核容器列表一致）。

---

## PHASE 2 — Open Issue Reconciliation 分类矩阵（#52–#67）

分类词表：**A** = IMPLEMENTED IN R2 — USER ACCEPTANCE PENDING / **B** = R3 REMEDIATION REQUIRED / **C** = PARTIAL — R3 RESIDUAL REQUIRED / **D** = DUPLICATE/MERGE CANDIDATE / **E** = BLOCKED BY TRUTH AUDIT / **F** = READY TO CLOSE（F 仅代表证据上具备关闭条件；本任务不关闭任何 Issue）。

| Issue | Product Intent（摘要） | 实现与发布证据 | 当前用户验收状态 | 分类 | 理由 | r3 归属 |
|---|---|---|---|---|---|---|
| #52 | Admin Knowledge Ops IA 收敛（KB-OPS-V163-002 修订：废弃 v001 顶层五域模型，在既有 IA 内收敛，导航清单不得增删） | Track A 交付 SH-06（系统 分组）/SH-09/SH-12；v163-wave1-track-a §「满足关闭条件」；integration C-d MATCH；R2 ledger SH-32/33/34/35 MATCH | R2 生产走查 PASS；UA 新发现未指向本项 | **F** | 修订后 scope（IA 分组收敛+既有真相）证据完备；关闭材料齐（仅需 Role A 终签，非 r3 工作面） | 非 r3 范围（终签即闭） |
| #53 | 数据源列表 attention-first 运营摘要 | attention 列/状态徽章/四筛选/异常优先排序（矩阵 DS-P1-13/15/20 MATCH）；R2 ledger #1–#5 | UA #61 指出行操作布局缺陷；#66 重定义列表 IA（扫描→同步记录→详情） | **C** | attention-first 主体已交付；列表 IA/操作呈现层残余由 #61/#66 承接 | Track A（经 #61/#66） |
| #54 | 详情页 operator-first 层级+健康 rollup 解释+人类可读术语 | Track B/C/D 交付：品牌映射（U-6）/类型 disabled（U-5）/知识设置（U-12）/预览（U-13）/修复链（U-8）/next_run_at（U-11）；R2 ledger #7–#16 | UA #67 指出健康面板工程术语直接暴露、#61 指出页头动作过度收纳 | **C** | 呈现语义化未竟（健康五维仍为「连接/覆盖/一致性」内部词）；残余=#67 Phase 1+#61 详情页头 | Track A（经 #67-UX/#61） |
| #55 | Document Inspector 完整真相面（身份/生命周期/版本/serving generation/**citation 有效性**/诊断） | 查看真相=身份+lifecycle+版本+serving+generation（R2 探针 p5 chunk_serving 3/3；R1 E2E-C 修复链）；U-8/U-9/U-10 | UA #64 暴露 citation canonical URL 真相缺陷→citation validity 呈现失去权威输入；#61 行级动作重命名 | **C** | 「Canonical citation target and validity are inspectable」在 canonical 真相修复前无法诚实交付；版本历史列表未独立成面 | Track D（truth）+Track A（呈现）；版本历史面保留迭代残余 |
| #56 | 历史 anomaly-first 时间线+常规压缩+generation 诚实空态 | SyncActivityPanel 异常优先+常规无变更压缩组+逐 run 技术证据展开（代码注释自证 #56 presentation-only；矩阵 DS-P4-07/08 MATCH）；「该源尚无索引生成记录」诚实空态生产在位 | R2 ledger #11–#13 PASS；UA #65/#67 对同面板提出**新增**要求（计数一等位/生成真相审计），不否定 #56 自身验收 | **F** | #56 自身验收项证据完备；r3 对同面板的变更是新 Issue 要求，非 #56 残余 | 非 r3 范围（终签即闭；r3 变更走 #65/#67） |
| #57 | TI 双 Tab 保持共享域（DIRECTION REPLACED 修订） | TI-02/03 MATCH；integration「技术性能/回答缺口 同壳（#57 冻结修订）MATCH」；R2 ledger #17–#29 全 MATCH | R2 PASS；UA 未指向本项 | **F** | 修订方向完整交付+R2 生产复核 | 非 r3 范围（终签即闭） |
| #58 | TI progressive disclosure+事件层级 | TechPerfTab 头注「#58 运营可读优先,raw 证据可展开,critical 优先」+`data-severity`+可展开 raw 证据；R2 ledger #29 MATCH | R2 PASS；UA 未指向本项 | **A** | 已在 R2 实现并生产复核；issue 级用户验收终签未做 | 非 r3 范围（终签即闭） |
| #59 | Knowledge Gaps 趋势/分布/空态一致性（修订=向恢复队列扩展只读面） | 恢复队列完整交付（TI-11–TI-45；U-14/15/16/17/18/19）；旧「暂无缺口数据/聚类刷新」矛盾空态布局已被恢复参考替换（全仓 grep=0 残留）；R2 ledger #5/#13/#15/#18–#28 | R2 PASS；UA 未指向本项 | **F** | 修订 scope（队列+权威 cause+状态+时近+诊断+下钻）全证据；词表 11 项生产在位 | 非 r3 范围（终签即闭） |
| #60 | 视觉层级统一（修订=恢复参考交互/视觉语法为 release-blocking） | 两恢复参考 152 行 reconcile DEFECT 0；R2 设计 ledger MATCH 26/UADC 4/PSNP 5 | UA #61/#66/#67 继续在同一语法内做呈现收敛（证明语法被沿用而非违背） | **C** | 跨面统一语法主体已交付；Document Inspector 独立基线等长尾未冻结；残余与 #54/#55 同源 | Track A（经 #61/#66/#67-UX） |
| #61 | [UA-001] 操作按钮过度收纳：列表页头 ⋯ 仅含「同步全部」、列表行 5 动作入 ⋯、详情页头 ⋯（编辑/知识设置/返回列表）、文档行 ⋯（重新处理/查看真相）；「重新处理」命名违背 repair≠sync 语义 | 修复链（POST repair，RBAC/幂等/审计/验证卡）U-8 已实现且 R1 E2E-C 验证——**按钮能力在位，纯呈现层收纳问题**；代码佐证：DataSources.tsx 页头 ⋯（L300–319）、行 ⋯（L485+）、DataSourceDetail.tsx 页头 ⋯（L363–386 含冗余「返回列表」）、行 ⋯（L723+） | 用户实际验收判定可发现性/点击效率不合格；语义命名误导 | **C** | 底层能力全在位；r3 = 四处布局直出+`重新处理`→`修复此知识` 重命名+tooltip；行 ⋯ 的「查看可观测性」按 #66 更名「同步记录」合并执行 | **Track A** |
| #62 | [UA-002] 配置周期（24h）与实际同步频率（~1h）不一致：调度执行语义 vs 配置真值 | **生产只读实证（2026-09-14）**：15/15 源 `sync_interval=24h`、`next_run_at≈+24h`（UI 真实）；而 sync_runs 中 woo 连续 8 次 cron 间隔 60–72min 全部 `triggered_by=cron`。根因三件套核实：`deploy/prod/docker-compose.yml:137`（sync-cron sleep 3600 循环）+ `scripts/sync.py:147–162`（仅 `enabled.is_(True)` 过滤，**无 due/next_run_at 门**）+ `backend/services/schedule_truth.py`（next_run_at 只计算展示、不约束执行）。U-11 交付的调度**真值投影**正确，但缺**执行语义**（due gate） | 用户验收发现三类真值撕裂（配置/UI/实际） | **B** | 调度语义缺陷（非呈现层）：需 authoritative due 判定 `enabled AND sync-eligible AND no inflight AND next_run_at<=now`；手动/repair 不受门禁；禁把 UI 改成 1h 反向对齐 | **Track B** |
| #63 | [UA-003] 对话审查缺稳定 Conversation ID 呈现 | 后端真值在位：`GET /api/admin/conversations` 与详情响应均返回 `id`；`Conversations.tsx` L284–289 已用 `conv.id`（key/selectedId/详情/trace），但**列表行与详情元信息区均未渲染** | 用户验收：无法从 UI 取得稳定标识用于日志/Trace/DB 排障 | **B** | additive UI observability：禁生成第二套 ID；列表弱化短格式+完整值可取得；详情完整 UUID 可复制；不改 schema/API | **Track C** |
| #64 | [UA-004] Citation canonical URL 无视 Docusaurus frontmatter slug → 断链 | **三层实证**：①代码 `backend/pipeline/canonical_url.py` 纯路径推导（numbered-prefix 剥离/index 折叠/i18n 镜像），零 frontmatter 读取；②源文件 `3-resources.md` 显式 `slug: /neoeyes-ne503-series/application-guide/`；③权威路由真相 wiki sitemap 含 `/docs/neoeyes-ne503-series/application-guide/`（slug+`/docs` routeBasePath）、**不含** mapper 输出的 `.../application-guide/resources`（SPA 壳 200 软 404）。映射点 `rag.py:1200`（citation 构建时统一调用→widget/admin 一致性由构造保证）。既有测试只验证 mapper 自身规则、未验证「最终链接真实可解析」 | 用户实际点击断链（真实会话 NE503 SDK 问题） | **B** | canonical route authority 结构性缺陷：frontmatter slug 为优先真值+fail-safe 回退 provenance URL+linkability contract+存量语料 corpus audit；禁前端 hardcode 单点 | **Track D** |
| #65 | [UA] 同步状态面板缺 本次新增/淘汰 计数 | **后端真相在位**：生产 `sync_log` 四列 `items_new/items_updated/items_deleted/items_unchanged`（integer）实证在位；`scripts/sync.py` 正常同步写 `items_new=len(new_docs)`（文档级；生产佐证 wiki 467/woo 41 与知识数同单位）、tombstone 写 `items_deleted`；前端 `SyncActivityPanel.tsx` L202–226 已在展开区消费，但**未作为一等业务信息** | 用户验收：状态面板答不了「这次同步改变了什么」 | **C** | presentation/aggregation gap（非从零建计数）：一等「本次变化 新增·更新·淘汰」+0 显性显示+无证据显 `—`+单位核实契约（实施前必须正式核验 items_* 单位，禁 chunk 冒充知识） | **Track A（呈现）+Track B（单位核实 audit-lite）** |
| #66 | [UX] 「查看可观测性」收敛为轻量「同步记录」，完整诊断留详情页（已确认产品决策） | 现状核实：`DataSources.tsx` 行内展开 `SourceObservabilityDetails`（L86）=SyncStatusPanel+SyncHistoryPanel+SourceHealthPanel 三件套，与详情页 IA 重复；「可观测性」为工程内部术语 | 用户验收判定 IA 重复+术语失当；Product Decision 已确认三级 IA | **C** | 呈现层+IA 互补：行 ⋯ 更名「同步记录」、轻量 3–5 条（时间/结果/新增/淘汰/耗时）+「查看完整详情」、移除行内完整健康诊断；**与 #65 共享同一 sync run 真值，双面同 run 一致** | **Track A** |
| #67 | [UA] 管理员语义化健康面板（Phase 1）+ Generation Truth 审计（前置冻结） | 前端 `SourceHealthPanel.tsx` 只做本地化不做健康重判（正确）；「本地诊断（健康与生成真相）」直接暴露 connectivity/coverage/consistency 术语。**生产只读实证（2026-09-14）**：`index_generations` 仅 3 行——`*legacy*` ordinal=0 ready **0/0**（创建于迁移日 2026-09-11 12:39:48）、neomind-dashboard-local ordinal=1 **failed 0/0**、website-camthink ordinal=2 ready **0/0**；12000 document_versions.generation_id 全部非空、wiki 文档版本指向 `*legacy*` #0(0/0) → 单文档「7/7 在服 vs Generation #0·0·0」反直觉复现；注意 ordinal=1/2（非 legacy）同样 0/0，**不能轻率归因 legacy**，审计必须回答（含新同步是否产出正常计数 generation） | 用户验收：术语不可读+Generation 反直觉且无解释 | **E** | 双层问题：Phase 1 术语收敛（不新增后端结论，可并行）；Generation Truth 呈现**冻结至审计完成**（与 APPROVED DESIGN 原则「Generation 在审计完成前保持冻结」一致）；禁把 #0/0/0 无证据解释为历史数据、禁 UI 遮盖 | **Track B（审计+建模）+Track A（Phase 1 UX；Generation 区冻结）** |

### 合并候选核查（D 类）

- #61 与 #66 行菜单项重叠（⋯ 内「查看可观测性」）：**不判 D**——#66（后发、已确认产品决策）以更名「同步记录」吸收该菜单项语义；两 Issue 在 Track A 内按单一冻结语义合并执行（#61 布局 + #66 命名/IA），互不取消。
- #65 与 #66 计数真相：同一 sync run 权威计数（`sync_log.items_*`）单一真相源，双面（列表轻记录/详情状态区）一致——在 Track A 合同内冻结为单一读路径，不允许两个口径。
- 其余 #52–#67 无重复/合并候选。

### 分类汇总

| 分类 | Issues |
|---|---|
| A（R2 已实现·用户验收待终签） | #58 |
| B（r3 修复必需） | #62 #63 #64 |
| C（部分实现·r3 残余） | #53 #54 #55 #60 #61 #65 #66 |
| D（重复/合并） | 无 |
| E（Truth 审计阻塞） | #67 |
| F（证据具备关闭条件·本任务不关闭） | #52 #56 #57 #59 |

---

## 与 APPROVED DESIGN INPUT 的衔接

Role A 已批准的 r3 数据源详情页设计（`/tmp/v163-refs/r3-ds-detail-approved-design.png`）与本文分类一致：
- ① 身份区（编辑/知识设置直出）= #61-3；④ 同步状态与活动（本次变化 新增·更新·淘汰；唯一主工作面，与列表「同步记录」互补）= #65/#66；③ 知识内容行 查看真相+修复此知识 = #61-4；② 异常提醒（交互保持）= 既有 U-12/attention 真相；⑤ 健康与诊断（默认折叠+管理员术语 #67-UX；**Generation truth 需先完成数据审计 #67，审计完成前保持冻结**）= #67 双层。
- 设计原则（图内冻结）：保持页面结构 / 优化命名布局而非重新设计 / 呈现前先验证 backend Truth / Generation 在审计完成前保持冻结。

## 边界声明

- 本对账零产品实现、零 backend/frontend 修复、零 merge main、零 deploy、零 Issue 关闭、零 v1.6.3 COMPLETE 宣告、零 v1.6.3-r3 tag/release。
- 生产访问全程只读（SELECT + 容器/路由核验），零写入、零 mutation；凭据零落报告。
