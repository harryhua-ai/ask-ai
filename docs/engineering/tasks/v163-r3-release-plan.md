# v1.6.3-r3 Release Plan（Contract Preparation）

- 性质：PLANNING ONLY。本文是 r3 修正发布的授权合同底稿；执行需 Role A 另行放行（IMPLEMENTATION_AUTHORIZED=NO）。
- 治理正名（冻结）：Product Iteration = **v1.6.3**；Current production release = **v1.6.3-r2**（fd5ca39）；Next corrective release = **v1.6.3-r3**（Release revision ≠ Product Iteration）。r3 完成不等于 v1.6.3 COMPLETE——后者仅在最终 User Acceptance 完成+相关 Issue 满足关闭条件后由 Role A 宣告。
- 基线：fresh main = `94ddb64`；生产 = v1.6.3-r2 @ fd5ca39（restarts=0/ERROR=0）。
- 输入：`v163-user-acceptance-reconciliation.md`（#52–#67 分类矩阵）、`v163-r3-data-source-design-contract.md`（Approved Design traceability）、`v163-r3-acceptance-matrix.md`、四轨合同 `v163-reference-remediation/r3-track-{a,b,c,d}-contract.md`、152 行权威矩阵、R2 生产符合性报告。

---

## 1. Objective（冻结）

**关闭 r2 真实用户验收（#61–#67）发现的产品可用性、Truth 与交互缺口，使 Product Iteration v1.6.3 达到最终 User Acceptance 条件。**

非目标（显式排除）：零散功能堆叠；Service Readiness/新健康算法（#67 Phase 2 另立需求）；Knowledge Operations 顶层五域 IA（#52 修订已废弃）；跨域视觉重设计；任何 lifecycle/sync/retirement/GC 业务语义变更。

## 2. Final Track Topology（最小 4 轨 + Integration）

真实所有权依据 = Wave 0B §9.6/§10 ownership map + main@94ddb64 现状文件归属 + r2 后现状（Track C/B/D/A 拥有面延续）。

| Track | 名 | Issues | 范围（Requirement IDs） | 文件所有权 | 并行性 |
|---|---|---|---|---|---|
| **A** | Data Source Admin UX | #61 全部、#65 呈现、#66 全部、#67 Phase-1 UX | R3-61-LH/LR/DH/DR、R3-65-DELTA/HONEST/STATES(呈现面)、R3-66-RENAME/LIGHT/NOHEALTH/DEEPLINK/CONSIST、R3-67-IA/DIM/ADV/UNK | `admin/src/pages/DataSources.tsx`、`admin/src/pages/DataSourceDetail.tsx`、`admin/src/components/dataSources/SyncActivityPanel.tsx`、`admin/src/components/dataSources/SourceHealthPanel.tsx`、新组件（SyncRecordPanel / AdvancedDiagnostics / 管理员健康面板重构件）+ vitest | 与 B/C/D 全并行启动；**Generation 真相呈现区冻结至 B 审计完成**；#65 呈现依赖 B 的单位核实签收（见 §3） |
| **B** | Data Source Runtime Truth | #62 全部、#67 Truth 审计+建模、#65 单位核实（audit-lite） | R3-62-DUE/NRT/MAN/TBY/TST、R3-67-AUDIT/GENFIX、R3-65-UNIT | `scripts/sync.py`、`backend/services/schedule_truth.py`、`backend/pipeline/generation_builder.py`、`backend/api/admin/data_sources.py`（generations 读面）、新增迁移脚本（如审计裁决需要）、`pytest`（时间推进测试）+ 审计报告 | 与 A/C/D 全并行启动；**审计完成 = A 的 Generation 呈现解冻门** |
| **C** | Conversation Review | #63 全部 | R3-63-LIST/DET/COPY/REG | `admin/src/pages/Conversations.tsx` + vitest（零 backend） | 完全独立，无依赖 |
| **D** | Citation Integrity | #64 全部 | R3-64-FM/FAILSAFE/LINKVAL/CORPUS/CONSIST/E2E | `backend/pipeline/canonical_url.py`、wiki 文档 ingestion 连接器（`backend/connectors/github.py` / `local_git.py` / `filesystem.py` 中 wiki 源实际走行者——执行首日前置调查确认）、`backend/pipeline/rag.py`（仅测试触达）、新 fixture 语料测试 + corpus audit 测试 | 完全独立（backend-only）；E2E（NE503 真实问题）在 Integration 阶段执行 |
| **Integration** | 第七轨 | — | 装配仲裁、Visual Gate、E2E、发布执行 | `tech.py` 式装配入口惯例（frontend 共享壳如需触达）；冲突仲裁 | 收尾 |

**#67 审计归属裁决（任务书问题，判定如下）**：Generation Truth 审计是 **Track B 的交付物**，不是前置调查项——理由：①审计产出直接决定 backend 建模变更（sentinel/legacy 显式状态 vs migration/backfill），两者必须同一所有权才能 fail-closed 落地；②审计含确定性验证（新同步产出的 generation 计数正常写入），需要 Track B 的 sync/generation 代码执行权做最小验证运行（授权的隔离数据态，非生产 mutation）；③但它内含一个**门禁语义**：审计未完成前，A 的 Generation 呈现冻结、任何人不得宣告该面完成。审计报告本身是 r3 验收矩阵的 Runtime evidence 输入。

## 3. Dependencies（冻结）

```
D ────────────────────────────────┐
C ────────────────────────────────┤
B(#62 due gate) ──────────────────┤
B(#65 UNIT 核实) ──→ A(#65/#66 计数呈现) │
B(#67 AUDIT 完成) ─→ A 解冻 Generation 呈现（#67-GEN 呈现面）
A ────────────────────────────────┤
                                  ▼
                          Integration（Visual Gate + E2E + 发布）
```

- **A→B**（数据依赖，非排程依赖）：#65 单位核实（`items_new` 当前为文档级——代码 `scripts/sync.py` `items_new=len(new_docs)`+生产佐证 wiki 467/woo 41 与知识数同单位——但按 #65 边界，实施前必须由 B 以测试正式签收单位契约，A 才可渲染「新增知识/淘汰知识」文案）。
- **A←B**（解冻门）：#67 审计完成前，A 对 Generation truth 区域**保持现状诚实呈现**（不改、不遮、不新解释）；审计完成后 A 才可按后端建模（如 legacy/untracked 显式状态）渲染。
- **D→#55**：canonical 真相修复后，#55 残余「citation 有效性可查验」获得权威输入（本轮仅要求 truth + 一致性，Inspector 呈现扩展属迭代残余，不在 r3 最小范围）。
- **C**：无依赖。
- 跨轨文件接触点：无共享实现文件（A 纯 admin/src，B 纯 backend+scripts，C 单文件，D 纯 backend pipeline/connectors）；若 A 需要读面缺口（如 latest-run 计数聚合），走 B 只读读面微扩，禁止 A 自建聚合口径。

## 4. Truth Gaps / Blockers（冻结）

| # | Gap/Blocker | 类型 | 归属 | 状态语义 |
|---|---|---|---|---|
| 1 | 调度 due gate：`next_run_at` 是权威投影但不约束 cron 执行（15/15 源 24h 配置 vs ~63min 实际 cron 实证） | 需新 Truth（调度执行语义） | B | r3 必须交付；`next_run_at` 从「UI 预测值」升级为「真实下次自动执行」 |
| 2 | citation canonical route truth：mapper 不读 frontmatter slug；权威 sitemap 无 `.../application-guide/resources` 路由（软 404 断链实证） | 需新 Truth（route authority）+ fail-safe | D | r3 必须交付；不确定即回退 provenance URL，禁猜测性 canonical |
| 3 | `items_*` 计数单位（知识 vs chunk）未正式签收 | Truth 审计-lite | B（供 A） | 实施前签收；UI 文案必须与真实单位一致 |
| 4 | Generation truth：`*legacy*` #0(0/0) 哨兵 + ordinal=1 failed 0/0 + ordinal=2 ready 0/0；generations API 源级空 vs 单文档 #0 并存；新同步是否产出正常计数 generation 未验证 | Truth 审计（E 类阻塞） | B | **审计完成前 Generation 呈现冻结**；禁无证据归因 legacy；禁 UI 遮盖；禁 Weaviate 计数反推账本 |
| 5 | #61/#63/#66 呈现面 | 无 Truth gap（后端真值全部在位：repair 链、conversation.id、sync_log.items_*） | A/C | 直接可实施 |

## 5. 验收模型 §6（七门，r3 全序列）

| 门 | 名称 | 内容 | 证据 |
|---|---|---|---|
| G1 | Contract freeze 门 | 本五件套经 Role A 批准冻结；各轨分支自冻结基线（fresh main SHA）拉出；merge-base 校验 | 本文档 SHA + 各轨 branch base |
| G2 | Ownership 门 | 逐 commit 文件所有权审计：越权文件=0；共享文件触达需 Integration 仲裁记录 | git diff --name-only per track |
| G3 | Engineering 门 | pytest 全量 0 fail（含 B 轨 1h/6h/24h 时间推进测试、D 轨 fixture+corpus audit）；vitest 全量+tsc 0（含 A/C 轨回归测试）；ruff 全仓指纹=基线；build ✓ | CI run + 本地台账 |
| G4 | **Visual 门** | 规则（冻结）：**1536×1024 @1x**；逐状态 reference crop ↔ candidate 对照（Approved Design 五区逐元素 + DS 列表/对话审查面）；每一 RUNTIME STATE 一张候选截图入 manifest；**FINAL PASS = Role A independent review only，执行 agent 无权自授**（执行 agent 只提交候选+对照表，不得在报告中标注 VISUAL PASS） | 截图 manifest + 对照表 + Role A 签发 FINAL PASS |
| G5 | Integration/E2E 门 | 跨轨 E2E：NE503 真实问题引用可解析（D）；1h/6h/24h 源同一 cron 序列只在到期运行（B）；对话 ID 复制→trace/DB 排障链路可用（C）；数据源列表→同步记录→详情三面同 run 计数一致（A）；修复此知识不触发上游抓取（A） | E2E 台账 |
| G6 | Release/deploy 门 | tag `v1.6.3-r3` + Release；CI 双 PASS；镜像 lineage（RELEASE.json version/git_sha）；迁移桥（如 GENFIX 产出迁移）按序+镜像身份断言；部署 SUCCESS；/health 双断言 | Release URL + run id |
| G7 | Production acceptance+regression 门 | 生产只读走查（r3 验收矩阵逐行 Runtime evidence）；§5 类语义探针（due gate 生效：24h 源 next_run_at 前无 cron run；断链不再产生；ID 呈现；计数一致）；restarts=0/ERROR=0；RELEASE REGRESSION=0；零未授权 mutation 逐条登记 | 生产验收 ledger（r2 报告同构） |

## 6. 边界与 STOP（planning 期）

- 本计划阶段（CONTRACT PREPARATION）：未实现任何产品代码、未建 r3 执行分支、未 merge main、未 deploy、未关闭任何 Issue、未建 tag/release、未宣告 v1.6.3 COMPLETE。
- IMPLEMENTATION_AUTHORIZED = NO。
- Forbidden shortcuts（沿 r2 冻结清单，四轨合同逐条重申）：fake counts / frontend-only state / keyword-only 分类 / 前端自算健康与业务影响 / 纯派生倒计时 / UI-only repair / 静默省略（设计所需而 backend 无真值时必须标 PRODUCT/FUNCTIONAL GAP，禁前端猜测）/ 把 UI 配置反向「对齐」错误执行行为。
