# v1.6.2 Iteration Plan — Operator-Visible Knowledge & Runtime Truth(统一规划/合同冻结)

状态:**CONTRACT READY**(待 Role A 复审;零实现授权)
日期:2026-09-12;基线:origin/main `57717ea`(生产 v1.6.1 @ `98ab795`)
范围:#50 + #51 + #7 联合 intake;Iteration = v1.6.2(既有,不新建)

---

## 1. v1.6.2 Goal(一句话)

让 v1.6.x 已交付的后端知识/生命周期/运行时真相**运营可见**:管理员在
`配置 → 数据源` 单一详情工作面回答"这个源里有什么知识、这条现在可用吗、
不可用为什么",在 `技术洞察` 从症状下钻到对话/证据/源/生成事实,在
`系统信息` 只读看到主机/硬件运行时——全程无需 SSH/SQL/Weaviate。

## 2. Fresh Truth 摘要(Phase 1 证据)

### 2.1 已实现且可直接复用的骨架(无需新建)
- Admin IA 双组导航(Sidebar.tsx:25-40):运营(业务概览/销售线索/对话审查/**技术洞察**/)+ 配置(**数据源**/对话接入/模型配置/答案覆盖/Widget/用户管理/**系统信息**)——§8b 接受的 IA 分工**已作为壳存在**,本轮是填充真相,不是重构导航。
- API 客户端/状态模式:apiFetch + TanStack Query + hooks 分层 + LoadError 三态纪律 + badge 语义变体(success/warning/destructive)+ 分页组件 —— 全部复用。
- 数据源页现有三面板(SyncStatusPanel/SyncHistoryPanel/SourceHealthPanel:8 态同步状态、run 历史、五维健康)可直接搬进详情工作面。
- 技术洞察 V1 已有:TechPerf(KPI/瓶颈 P50P95/异常/降级链/健康横幅→`/conversations?failure=true` 深链)+ KnowledgeGaps(未回答趋势/miss_type 分布/覆盖缺口表);后端 `/tech/performance`、`/analytics/coverage-gaps(+refresh)`、`/gaps/{id}/resolve`、`/gap-trends`、`/top-questions(+refresh)`、`/source-health` 全部在案。
- `/system` 页 = 仅发布身份(版本/SHA/构建/镜像/CI);其组件注释**预留**硬件追加段;`system.py` 模块注释**预留** #7 端点挂载。

### 2.2 缺失(本轮要交付的真相层)
- **零内容清单**:无任何 admin 端点列出单文档;`documents` 表本身携带全部 canonical 身份(title/url/source_type/product/branch/content_hash/chunk_count/L 轴 lifecycle/current_version_id/superseded_*/deleted_at/created_at/updated_at,models.py:66-90,声明为对账权威)但从未暴露。
- **零生成可见性**:index_generations(ordinal/status/doc_count/chunk_count/failure JSONB/activated/retired 时间戳)无任何 admin 读端点。
- **零版本/项目级真相暴露**:document_versions(version_seq/generation_ordinal/status/source_version/title/url/chunk_count/valid_from-to)与 document_version_chunks(全量文本真值+props)无读端点。
- **零主机观测**:无 psutil/hostname/OS/uptime/disk/CPU 利用率/GPU 利用率·温度采集;GPU 仅内存事实(manager snapshot/hardware.py/nvidia-smi memory-only)。
- **未接线的既有能力**:gap resolve/refresh、top-questions、per-source citation analytics 的 hooks 存在但**零页面消费**。

### 2.3 Stale / Missing / Conflicting 假设裁定
| Issue 假设 | 真相 | 裁定 |
| --- | --- | --- |
| #50 "product/content-role metadata where authoritative" | **无 content_role 列**;metadata_ JSONB 携连接器原始元数据 | 仅展示权威存在的字段;**禁止虚构 content-role** |
| #50 "discovered/last-seen timestamps" | 仅有 created_at/updated_at(+version.source_version 原生元数据) | 展示 created/updated 为权威时间戳;禁止虚构 discovered/last-seen 语义 |
| #50 "exclusion/failure/retirement reason" | L 轴状态 + superseded/deleted 时间 + generation.failure JSONB + sync_log error_detail + sync_runs.consistency —— 逐项原因部分可证 | 只呈现可证原因;不可证处显式"后端无此记录",不得编造 |
| #51 "system can prove 的证据/覆盖问题" | miss_type 四类(reject/low/召回空/召回不足)+ conversations.sources JSONB + Trace(generation_error/failure_kind)+ coverage-gaps 聚类 | 充分;不新增正确性契约 |
| #7 "GPU utilization/temperature where available" | 现采集仅显存(nvidia-smi memory query) | 利用率/温度属实现 HOW(B 决定扩展只读查询);不可得时显式"不可用"态 |
| #7 Priority | 正文 P1 vs 标签 priority:p2 冲突 | 以标签为准 → 正文对齐 P2(随本轮 Issue 更新修正) |
| #30 关系 | iteration:v1.6.0 标签已 stale;#50 自声明为其 UI 交付轨 | #30 本轮**不改标签**(治理面另行处理);其内容清单需求由 #50 承接;**retention 设置 UI 与变体级 Store 清单深度 = #30 残余,不在 v1.6.2**(retention 运营化=Freeze P5;Woo 变体粒度=F-1' 已知 Scope Expansion 候选)——显式推迟,不静默携带 |

## 3. Dependency Graph(Phase 3,证据裁定)

```
#50(B1)── FROZEN INTERFACE:详情路由 /data-sources/{source_id}
│           (+ lifecycle 标签模块 COMMIT 级共享)
│           ──> #51(B2)下钻目标
#7 (B3)── NONE(完全独立,任意时间可并行)
共享基础(已存在,零新建):导航壳/API 客户端/查询模式/LoadError/badge/分页/三面板
```

- **#50 → #51 = FROZEN INTERFACE**:数据源详情路由路径 `/data-sources/{source_id}`(source_id 为 DataSource.id,单段无斜杠,evidence:`data_sources.py` PK 语义 + 前端现有 `/data-sources` 平铺列表)。B2 据此冻结下钻链接;下钻**验收**依赖 B1 集成。
- **#50 → #51 lifecycle 标签模块 = COMMIT**(非冻结接口):B1 产出 `admin/src/lib/lifecycleLabels.ts`(L 轴 + 生成状态 → 运营标签/badge 语义);B2 可选用,不阻塞。
- **#51 → #50 反向零依赖**:技术洞察的跨源事件聚合读模型由 B2 自有(直接读 sync_runs/index_generations 权威表),**不得**复制 #50 的逐源清单端点(以链接代替)。
- **#7 = NONE**:挂载点(/system 页 + /system router)已预留,无 inbound/outbound。

### 后端读模型所有权矩阵(防重复契约)
| 读模型 | owner | 说明 |
| --- | --- | --- |
| 逐源文档清单 / 单文档真相 / 逐源生成列表 | **#50 B1** | 新只读端点,形状由 B1 工程设计 |
| 跨源技术事件聚合(sync/index/generation/rebuild incidents) | **#51 B2** | 新只读端点或 /tech 扩展,B2 设计 |
| 主机/硬件运行时 | **#7 B3** | 新只读 GET /api/admin/system/* 端点 |
| 既有端点(tech/performance、coverage-gaps、gap-trends、sync-*、source-health、model-runtime、system/release) | 不变 | 三方仅消费 |

## 4. Execution Topology(Prioritize)

```
B1(#50)──────┬──> Integration B(组合候选,owner=Role B 集成代理)
B3(#7)───────┤        │
B2(#51,基于 B1 候选树,   └──> Role A 组合复审 → 授权合并
    接口冻结后即可开发)──┘
```

- **并行**:B1 ∥ B3 立即可并行;B2 的 TechPerf 重聚焦部分在接口冻结后即可开发。
- **串行**:B2 的下钻验收必须等 B1 详情面落地;B2 候选分支基于 B1 候选树。
- **Integration owner**:Integration B(组合 #50→#51→#7,回归+组合验收,零生产部署)。
- 每 B 独立走 Role A 评审(CANDIDATE READY → FINAL PASS)后进组合。

## 5. Phase 5 治理:防止"后端交付 ≠ 产品交付"

本 Iteration 三合同均设 **Runtime / Real-World Acceptance** 强制项:
1. 验收必须针对**真实伺服的全栈 Admin 面**(生产或生产等价部署),不是单测/API green;
2. 每合同附**运营员走查脚本**(真实数据点,含一个"不可用/失败"样例),证据 = 截图/转写 + 与 DB 真值抽查一致;
3. Issue 关闭前置条件含"生产可见面与接受语义一致"(部署后核验),仅 backend tests/migration/版本升级不构成关闭依据。
历史教训锚点:v1.6.1 P1 后端能力上线而 Admin 面维持旧观(验收报告 §17/§22);本轮以合同条款封死该缺口。

## 6. Iteration Exit Criteria(v1.6.2 = COMPLETE 当且仅当)

1. #50 accepted(含 runtime/real-world acceptance);
2. #51 accepted(含下钻链路 runtime 证据);
3. #7 accepted(含 GPU 主机 + 无 GPU 降级两态 runtime 证据);
4. 共享/集成回归绿(组合树全量 + project automation + admin vitest + ruff);
5. 组合候选 Role A 验收绿;
6. 必需 runtime/real-world acceptance 绿(§5 三走查);
7. 生产可见面与接受产品语义一致(部署后核验,非仅版本号);
8. 零未解释 scope 变更(#30 残余/resolve-refresh/top-questions 等推迟项全部显式在案);
9. GitHub Issue / Project 状态反映实际接受真相(#50/#51/#7 关闭或随部署推进,#30 残余显式留在其自身 scope)。

## 7. 显式 Out-of-Scope(防偷带)

- retention/lifecycle 时长设置 UI(#30 残余;GC 运营化 = Freeze P5);
- WooCommerce 变体级清单粒度(F-1' Scope Expansion 候选,独立拍板);
- gap resolve/refresh 与 top-questions 的 UI 接线(hooks 已在,产品未要求,留待后续);
- 任何检索/排序/引用语义变更;任何 GC 执行策略变更;任何写操作类控件(#7 V1 边界、#50 无破坏性控件)。

## 8. Exact B Prompts(自包含,逐字使用)

### B1 prompt(#50)

```
Task — B1:#50 Admin Data Source Workspace V2(v1.6.2)。仓库 harryhua-ai/ask-ai。
基线:origin/main(先 fetch 确认;当前 57717ea 谱系)。冻结合同:
docs/engineering/tasks/v162-i50-data-source-workspace-v2-contract.md(逐字遵守,
含 Change Boundary 四类与 FORBIDDEN 面);迭代上下文:
docs/engineering/tasks/v162-iteration-plan.md。候选分支
b1/data-source-workspace-v2-20260912(自主 main 创建)。
交付:单一详情工作面路由 /data-sources/{source_id}(此路径为对 #51 的
FROZEN INTERFACE,不得更改);新增只读端点族(逐源文档清单[分页/过滤/
搜索]、单文档真相、逐源生成列表——工程设计与形状由你拥有);新建
admin/src/lib/lifecycleLabels.ts 并消费;现有三面板与列表页复用/零回归。
纪律:对新增端点与 UI 先 RED 测试后实现;真实原因只来自权威账本
(documents/document_versions/index_generations/sync_*),后端无记录显示
"后端无此记录",禁止虚构 content-role/discovered 等不存在字段;零破坏性
per-item 控件;零检索/排序/引用语义变更;docs/ 提交需 add -f。
回归:新增后端 pytest + admin vitest;全量后端回归;ruff 改动文件。
报告:docs/engineering/tasks/v162-i50-data-source-workspace-v2-execution.md
(三桶逐态映射设计记录在案)。
最终态:仅 B1-DATA-SOURCE-WORKSPACE-V2 = CANDIDATE READY|PARTIAL|BLOCKED
之一;然后 STOP 待 Role A。不 merge main,不部署,不触碰生产。
Runtime/Real-World Acceptance(合同强制项)在本任务只准备走查脚本与
数据点清单;实际执行在部署验收阶段。
```

### B2 prompt(#51)

```
Task — B2:#51 Technical Insights V2(v1.6.2)。仓库 harryhua-ai/ask-ai。
基线:B1 候选分支 b1/data-source-workspace-v2-20260912(等其 CANDIDATE
READY 后开工;下钻验收依赖 B1 详情面)。冻结合同:
docs/engineering/tasks/v162-i51-technical-insights-v2-contract.md;迭代
上下文:docs/engineering/tasks/v162-iteration-plan.md。候选分支
b2/technical-insights-v2-20260912(基于 B1 候选树)。
交付:技术洞察双 tab 重聚焦——跨源 sync/index/generation 事件信号区
(只读聚合读模型由你设计,所有权归 #51,不得复制 #50 逐源清单端点);
下钻链路:事件行→/data-sources/{source_id}(冻结接口),缺口行→既有
/conversations 核查面(冻结参数语法);零源清单/源配置复刻;gap
resolve/refresh 与 top-questions UI 接线为 FORBIDDEN(显式推迟)。
纪律:RED→GREEN;新端点只读;既有 TechPerf/KnowledgeGaps 零回归;
lifecycleLabels 可复用(COMMIT 级);docs/ 提交 add -f。
回归:新增后端 pytest + admin vitest;全量后端回归;ruff 改动文件。
报告:docs/engineering/tasks/v162-i51-technical-insights-v2-execution.md
(下钻参数语法与事件聚合设计在案)。
最终态:仅 B2-TECHNICAL-INSIGHTS-V2 = CANDIDATE READY|PARTIAL|BLOCKED;
STOP 待 Role A。不 merge main,不部署,不触碰生产。Runtime 走查脚本
随报告产出,实际执行在部署验收阶段。
```

### B3 prompt(#7)

```
Task — B3:#7 Admin Read-Only System & Hardware Runtime Observability
(v1.6.2)。仓库 harryhua-ai/ask-ai。基线:origin/main(与 B1 完全并行,
无依赖)。冻结合同:
docs/engineering/tasks/v162-i7-system-runtime-observability-contract.md;
迭代上下文:docs/engineering/tasks/v162-iteration-plan.md。候选分支
b3/system-runtime-observability-20260912(自主 main 创建)。
交付:新只读 GET 端点(挂 /api/admin/system router,形状由你设计):
主机身份/OS/内核/uptime、CPU、内存、磁盘(部署卷)、GPU(利用率/显存/
温度可得时;不可得显式 unavailable+原因)、服务状态(/health +
model-runtime 快照复用),每项 as_of;SystemInfo 页新增"系统运行时"
只读分区(该组件注释已预留)。V1 安全边界(冻结):零操作控制、零写
端点、零 env/secrets 暴露;只读扩展 nvidia-smi 查询字段允许;如引入
采集库(如 psutil)在执行报告记录 pyproject 变更。平台可移植:非 Linux/
无 GPU 环境必须优雅降级(测试覆盖)。
纪律:RED→GREEN;model-runtime 管理面零回归;docs/ 提交 add -f。
回归:新增后端 pytest + admin vitest;全量后端回归;ruff 改动文件。
报告:docs/engineering/tasks/v162-i7-system-runtime-observability-execution.md
(含 GPU 主机 + 无 GPU 两态 runtime 走查脚本与取证比对清单)。
最终态:仅 B3-SYSTEM-RUNTIME-OBSERVABILITY = CANDIDATE READY|PARTIAL|
BLOCKED;STOP 待 Role A。不 merge main,不部署,不触碰生产。
```

### Integration B prompt(组合候选 owner)

```
Task — Integration B:v1.6.2 组合候选。前提:B1/B2/B3 各自 Role A FINAL
PASS。按 #50→#51→#7 顺序组合候选树(零改写已接受提交);跑组合树全量
后端回归 + project automation + admin vitest + ruff;执行三合同 Runtime
走查(全栈伺服面,真实数据点,证据落 ask-ai-acceptance 谱系目录);对账
GitHub Issue 验收项;零部署零生产触碰。产出组合验收报告与
INTEGRATION-B-V162 = READY-FOR-DEPLOY-REVIEW|PARTIAL|BLOCKED;STOP。
(部署为独立授权任务;关闭 #50/#51/#7 需部署后生产可见面核验。)
```
