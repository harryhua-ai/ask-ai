# KNOWLEDGE FRESHNESS & RETRIEVAL INTEGRITY — INITIATIVE FREEZE

- 日期:2026-09-11
- 轨道:Trace B(知识完整性实现 / Release 2)
- 性质:**Initiative Freeze** —— 冻结 WHAT / WHY / 不变量 / 阶段所有权 / 验收边界。本文**不实现**任何 Phase,不含 Phase 1 工程 HOW(后者由独立任务《Phase 1 — Lifecycle Foundation Engineering Contract》派生)。
- 事实源(全部已接受,本文不得回退):
  - Discovery:`docs/engineering/discovery/KNOWLEDGE-FRESHNESS-RETRIEVAL-INTEGRITY-DISCOVERY.md`(e94a673 + b8969ca/f73092b 修正)= **FINAL PASS**
  - UX 定义:`docs/product/initiatives/ADMIN-KNOWLEDGE-OPS-UX-DEFINITION.md`(7ce0111 + b8969ca)= **FINAL PASS**
  - Product Review CORRECTION:D-1 / D-4 / D-6 修正 = **ACCEPTED**;U-1 / U-2 = **DECIDED**
  - Role A 复审:NARROW FIX(f73092b,§4C/§5 D-6 残余清除)= **ACCEPTED**
- Trace 状态:Trace A(Release 1 / Bug Fix 生产收口)候选 = main `bb80c389`;Trace B 实现自 Release 2 起独立成列。
- 落点:`docs/product/initiatives/`(仓库 initiative 级产品文档惯例,与 UX 定义同层)。

---

## 1. PRODUCT GOAL(冻结)

ASK-AI 对用户与运营者提供**可持续保鲜、可审计、可运营的知识真相层**,而非单点"更好检索":

1. **持久知识真相**:归一化文档真相持久留存、版本绑定、足以重建全部服务投影;向量索引永不成为唯一副本;
2. **确定性文档身份与版本**:canonical identity 跨内容变更稳定、跨移动可追溯(alias)、版本链可回放;
3. **安全生命周期**:新增/变更/接替/缺失/删除全部沿显式状态机演进,删除必须证据确认,瞬时故障不得变成知识丢失;
4. **新鲜度可见且可执行**:源策略驱动的 FRESH/STALE/OVERDUE/UNKNOWN/ARCHIVE 语义,现势/时效敏感断言受硬门约束;
5. **对账可证明**:源清单 × 账本 × 服务索引三方一致可机读证明,差异显形且有据收敛;
6. **引用有效性**:引用链接是显式生命周期对象(VALID→…→INVALID),独立可观测、可复验;
7. **时态/权威正确**:现势真相与历史真相显式区分,历史不得冒充现势,过期现势不得冒充有效现势;
8. **检索资格**:仅合格知识到达检索;资格由物理主门 + 逻辑副门确定性决定,可解释;
9. **运营可观测/可控**:Admin 能按已接受 UX 定义观察、配置、处置全部知识运营状态,无需理解内部 RAG 机制。

**非目标(显式排除)**:全量 GraphRAG 改造;替换既有检索/重排机制;Trace A 的 Bug Fix 范畴;重开已接受 UX。

---

## 2. AUTHORITATIVE INVARIANTS(冻结;Phase 契约与实现不得违反)

**I-1 持久真相(D-1 修正冻结)**
- 持久化归一化文档真相必须留存;可存于 Postgres **或**关联的持久 content-addressed 存储;
- 内容必须**版本绑定**且**足以重建服务投影**;
- **Weaviate 永远不得成为唯一持久副本**;
- lifecycle / version / identity 元数据的权威 = Postgres;禁止从向量索引反推任何生命周期事实。

**I-2 正交状态模型(A-1)**
- lifecycle(L)/ reachability(R)/ processing·index-generation(P)/ freshness(F)为四条独立状态轴;
- 禁止合并为组合枚举;混合态(如 ACTIVE×UNREACHABLE×FRESH)合法且必须可表达;
- 检索资格 = 派生(L=ACTIVE ∧ 源 enabled ∧ active generation READY),资格解释必须可呈给 Admin(UX §4C 资格行)。

**I-3 时态角色 = 源策略(D-6 修正冻结)**
- 连接器类型**不蕴含**时态/归档角色:`filesystem != HISTORICAL` 且 `filesystem != ARCHIVE`,除非该源策略显式归类;
- 策略显式归类 ARCHIVE 的源可采用归档型新鲜度语义(如 freshness=N/A、永不 STALE);
- 既有/未分类源 = `UNCLASSIFIED` / `ARCHIVE_CANDIDATE`:Admin 必须完成分类,**绝不静默按 HISTORICAL 处理**;激活前 UNCLASSIFIED 维持现状行为(无历史框定、无归档新鲜度),Admin 侧以「待分类」显形(UX §2 Badge);
- 时态角色变更保存前必须给轻量影响预览(U-2 四项最小指标);
- **边界决策(有界,非新增开放问题)**:UNCLASSIFIED 在时态执行激活后的检索/框定语义 = **Phase 3 契约冻结项**(届时必须回到 Product 定夺,禁止实现中发明默认)。

**I-4 新鲜度执行(D-4 修正冻结)**
- 硬新鲜度拒绝仅适用于**显式现势/时效敏感断言**:现价、现货 availability、当前 SDK/发布/版本、当前兼容性、当前产品规格、当前政策/状态;
- 其余 CURRENT 证据 OVERDUE 时降级/标记,不自动硬拒;
- 新鲜度锚 = source_verified_at(完整清单验证成功时间),非文档内容时间。

**I-5 索引生成(D-2 冻结)**
- 双代共存 + `active_generation` 指针原子翻转;失败的新代**不得**破坏在服旧代;RETIRED 旧代按保留窗 GC(D-3:默认 30 天,可配)。

**I-6 删除安全**
- 删除必须证据确认:完整源清单 + 连续缺席宽限 + 源可达探针,任一不满足 → UNREACHABLE/MISSING_CANDIDATE 保留服务;
- 瞬时源故障**绝不**成为删除;墓碑 = 逻辑删除,物理清除仅经 GC 窗口。

**I-7 引用有效性**
- 引用为显式生命周期对象(VALID/REDIRECTED/MOVED/UNREACHABLE/NO_PUBLIC_URL/INVALID),状态独立可观测、可复验;
- INVALID 引用不得继续作为权威最终证据(处置策略按已接受 UX §4D 类 6)。

**I-8 时态真相优先序**
- 现势/时效敏感断言只可引 CURRENT(且受 I-4 约束);HISTORICAL 证据必须带日期框定,不得在现势断言中冒充现势;SUPERSEDED 仅服务变化/历史类问题。

---

## 3. PHASE OWNERSHIP(冻结)

| Phase | 所有权(WHAT) | 明确不吸收 |
|---|---|---|
| **P1 — Lifecycle Foundation** | canonical identity 地基;DocumentVersion 版本模型;content-hash/metadata-hash 变更语义;持久归一化内容契约(I-1);lifecycle 地基(L 轴+墓碑+接替);alias 地基;生成模型+原子激活(I-5);RETIRED 代处理/GC 地基 | 新鲜度策略/SLA(P2);引用探活(P2);全源清单/对账循环(P2);检索资格逻辑门与时态执行(P3);Store 变体摄取(P3);Claim/Graph(P4);Admin Ops 实现(P5) |
| **P2 — Freshness + Reconciliation + Citation Validity** | 源清单/对账(slim 完整枚举,含 woo 分页正确性);freshness 策略与 source_verified_at;coverage/overdue 语义;引用校验/探活(D-7 独立低频作业);源消失确认(缺席宽限+探针);三方对账与不变量报告;上述所需连接器正确性修复 | 时态角色检索执行(P3);变体结构(P3);GC 策略变更(P1 已定基) |
| **P3 — Retrieval Integrity** | 检索资格(逻辑副门);authority/temporal 执行(I-8 硬规则);历史框定;证据角色有界预留扩展(solution/case 桶);content_hash 引用 collapse;**Store 变体摄取与内容结构**;UNCLASSIFIED 激活语义契约(回 Product) | 新排序公式(无证据不预设);Claim/Graph(P4) |
| **P4 — Claim / Graph** | 仅条件触发:Phase 2/3 后仍有多源事实冲突/变体断言缺口时,轻量 claim 表评估。**GraphRAG 不是本 initiative 依赖** | — |
| **P5 — Admin Knowledge Operations Implementation + Operational Rollout** | 按**已冻结** UX 定义实现端点集+Admin SPA+运营落地(GC 默认运营化;基准回归) | **不得重开已接受 UX 定义** |

---

## 4. CROSS-TRACE BOUNDARY(冻结)

| 轨道 | 范围 | 基线/状态 |
|---|---|---|
| **Trace A** | Release 1 / Bug Fix 生产收口(F-1' 矫正等) | 候选 = main `bb80c389`,独立进入 Release 1 |
| **Trace B** | Knowledge Integrity 实现 / **Release 2** | 本 Freeze;实现 NOT STARTED |

- **所有权转移(记录于 P3)**:Trace A #28 排名失效 = **CLOSED by F-1'**;Trace A #28 WooCommerce 变体/源契约残余 = **转移至 Trace B Phase 3**;**Trace A 不得另建变体摄取方案**。
- **隔离纪律**:在 `bb80c38` 作为 Trace A Release 1 候选期间,**未完成的 Trace B 实现不得并入 main**;Trace B 文档类工作同样遵守仓库集成纪律(分支+评审+显式集成闸,本文即以已接受候选 `f73092b` 为基线的分支交付,待 Release 1 收口或 Role A 变更基线后集成);
- Trace B 任何实现不得修改 Trace A 发布代码;两轨共享的连接器/账本改动归属先获集成闸的一方,另一方 rebase 契约化处理。

---

## 5. ACCEPTANCE MODEL(冻结)

**Initiative 级出口(全部满足才可宣告 initiative 完成)**:最终必须能以**运行时证据**(真实部署观测,非仅仓内状态)证明:

1. 服务投影可从持久真相重建(I-1);
2. 单一 canonical identity 不会失控分叉出多个现役版本(版本/接替语义);
3. 失败新代不能摧毁在服旧代(I-5);
4. 已删/缺失/被接替内容沿显式生命周期规则演进(I-6 + §2 状态模型);
5. 瞬时源故障不导致破坏性删除(I-6);
6. 过期/严重过期的现势敏感证据不得静默冒充现势真相(I-4);
7. 历史证据不得静默覆盖现势真相(I-8);
8. 失效引用不得继续作为权威最终证据(I-7);
9. inventory / ledger / serving-index 完整性可对账并可机读证明(Discovery §6 不变量);
10. Admin 可观察已定义的全部运营状态(已接受 UX 定义验收十问);
11. 全程留有审计 AUTO+AUDIT 行为的证据链(UX §5)。

**Per-phase gates**:
- **P1 Gate**:全量重建零服务中断;同文档两现役版本不可共存;FAILED 新代不破坏 ACTIVE 代;墓碑/接替语义符合冻结状态机;投影可重建性首次可证明;真实部署冒烟证据。
- **P2 Gate**:三方可对账且不变量报告机读;瞬时故障注入→UNREACHABLE 保旧代(非删除);引用探活端到端(VALID→INVALID→处置)运行时证据;woo 分页修复实证。
- **P3 Gate**:资格门+时态执行按 I-3/I-4/I-8 生效且可解释(资格行/影响预览 U-2);#28 变体残余收口(commercial 答案端到端);benchmark_v1 回归+新增 freshness/integrity 用例。
- **P4 Gate**:仅当触发条件成立,先回 Product 评审。
- **P5 Gate**:UX 验收十问逐条以真实产品作答;运营 rollout 完成(默认值/告警/手册)。

不预设实现 HOW;Phase 契约任务自行细化工程方案,只要不违反 §2 不变量与本表边界。

---

## 6. OPEN DECISIONS AUDIT(不制造新问题)

**ALREADY DECIDED(不得重开)**:D-1(内容留存,修正版)/ D-2(双代+原子激活)/ D-3(GC 30 天)/ D-4(硬门范围,修正版)/ D-5(别名自动接链可撤销)/ D-6(时态角色=源策略,修正版)/ D-7(探活独立作业)/ U-1(总览分离)/ U-2(影响预览)/ A-1(正交四轴)。

**SAFE TO DEFER(属 Phase 契约的常规工程选择,非产品开放问题)**:
- 持久内容的具体载体(PG 表 vs content-addressed 对象存储位置、压缩/去重策略)→ P1 契约;
- generation UUID 命名空间与 active_generation 过滤的物理实现 → P1 契约;
- 各连接器"清单完整性"判定细则 → P2 契约;
- OVERDUE 硬门的意图/断言映射实现 → P3 契约;
- 别名自动接链的撤销操作面细节 → P5 契约(语义已由 D-5 冻结)。

**MUST DECIDE BEFORE P1 CONTRACT:无。** P1 所需全部产品语义已冻结(I-1/I-2/I-5/I-6 + §7 交接)。
**有界 Phase 决策(已在 §2 I-3 冻结边界)**:UNCLASSIFIED 激活后检索/框定语义 → **P3 契约前必须回 Product**;届时若缺失证据,按本 Freeze 不得实现默认。

无需向 User 升级的实质产品/业务悬案。

---

## 7. PHASE 1 HANDOFF(权威交接;供独立 P1 工程契约任务消费)

- **P1 Goal**:建立知识生命周期地基——canonical identity + 版本模型 + 持久内容契约 + 生成原子性,使"投影可重建、失败不回退、接替可追溯"首次成立。
- **P1 Included**:canonical identity 地基(含 alias 地基);DocumentVersion 版本模型;content-hash / metadata-hash 变更语义;持久归一化内容契约(按 I-1,载体选择=工程决策);lifecycle 地基(L 轴 + 墓碑 + 接替);生成模型 + 原子激活(I-5);RETIRED 代处理 / GC 地基(D-3)。
- **P1 Forbidden**:新鲜度策略/SLA(P2);引用探活(P2);全源清单与对账循环(P2);检索逻辑资格门与时态执行(P3);UNCLASSIFIED 激活语义(P3 契约);Store 变体摄取(P3);Claim/Graph(P4);Admin Ops 端点/面板实现(P5);吸收任何后期行为。
- **Dependencies**:既有 #13 身份冻结契约(source_id 路径 PK + 确定性 UUID 家族);ingest/sync 管道与 Weaviate 集合(工程层);Trace A Release 1 隔离纪律(§4 —— P1 实现分支不得并入 `bb80c38` 主线直至收口或 Role A 变更基线);PG 迁移由 P1 契约定义(Freeze 不创建)。
- **Product Invariants**:I-1、I-2、I-5、I-6(及状态模型 L/P 轴定义);D-1/D-2/D-3/D-5 冻结语义;接替→SUPERSEDED、缺席→墓碑需 P2 确认机制配合(P1 只落地状态与转换原语)。
- **Acceptance Anchors**:§5 P1 Gate 四条 + 运行时证据要求;验收语料锚:发现 §0 案例映射中属生命周期族者(#48 ghost 半径、KNOWLEDGE-STALE-LEDGER 类死账)。
- **Open Decisions**:无阻断项(§6:MUST DECIDE BEFORE P1 CONTRACT = 无)。

---

## 附:与事实源的映射
D-1→I-1;A-1→I-2;D-6→I-3;D-4→I-4;D-2/D-3→I-5;§4B/§6(Discovery)→I-5/I-6;D-7→P2 所有权;UX §2→I-2/I-3 状态与 Badge 词汇;UX §4D→I-7 处置语义;UX §5→验收 11(审计链);Discovery §13→§3 阶段表与 §5 gates;Trace 转移→§4。
