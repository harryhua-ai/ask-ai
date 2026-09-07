# ASK-AI Answer Intelligence Benchmark v1 — Unified Contract Normalization

> **性质**:DISCOVERY / EVALUATION DESIGN ONLY · READ ONLY(GitHub Issue #32;不做当前 ASK-AI 评分)
> **日期**:2026-09-07 · **执行**:Executor · **状态**:NORMALIZATION **PASS**(自评,待 Planner FINAL REVIEW)
> **工件**:`unified_benchmark_contracts_121_2026-09-07.json`(121 案)· `unified_schema_v1_2026-09-07.json`(schema)
> **声明**:本 Gate 规范化评估契约;**不冻结 Benchmark v1**;121 仍为拟议池。

---

## 1. 池与来源

| 组 | 数 | 真值权威(复用,不重做) |
|---|---|---|
| HISTORICAL_A | 35 | 迁移 Discovery 稳定真值 + 语料 provenance(claims 标 FREEZE_SNAPSHOT_VERIFY) |
| HISTORICAL_B | 32 | GT 复核工件(41 案工作复用) |
| HISTORICAL_C | 30 | C30 语义契约(逐案十维定义原样保留)+ GT9 权威 |
| COVERAGE_ADDITION | 24 | 准入 & 真值工件 |
| **合计** | **121**(POOL CHECK PASS,未增删) | |

## 2. 冻结 Planner 修正案落地

1. **sq-108 LPR**:T4 已替换为修正案文本(官方 overview 文档化 LPR 应用能力;预装/一键形态=NOT_DOCUMENTED;并发仍须估算);OLD 文本仅存 `historical_provenance.sq108_t4_old`;四项不推断(预装/一键/每台含/并发已验证)写入修正记录。**SQ108_AMENDMENT_APPLIED = YES**。
2. **#013 默认凭据**:ALLOWED_WITH_SECURITY_CONTEXT 政策应用于 sq-013(可提及/必要时提供官方文档化默认凭据,但须标识默认+建议立即更换+不常态化+不必要不暴露+不泛化);凭据值以 **DEFAULT_CREDENTIAL_FIXTURE** 语义引用。**DEFAULT_CREDENTIAL_POLICY_APPLIED = YES**。
3. **第三方快照语义**:cg-r11 第三方事实限「不虚构+有界」评分(第一方事实正常评分,升级路径已记录);cg-r16 外部竞品事实须快照支撑。未建快照管线。

## 3. 重要规范化发现

1. **⚠️ 字面默认凭据泄漏(已修复)**:迁移 inventory 的 sq-013 问句含字面默认凭据(GT 工件已脱敏而 inventory 未脱敏)——规范化语料程序化 scrub,占位符与 GT 一致;inventory 本体(已验收输入)未改动,建议 Planner 知悉并在冻结快照中脱敏。
2. **深度分层**:C30 保留逐案十维专案定义(已验收工作保全);A/B/new24 用同一冻结维度集 + CASE_CONTRACT_DERIVED 判据(按各案 claims/prohibited/behavior 评分)——schema 一致≠语义均匀(Gate 明示允许);审计确认 C30 无评分特权(第 13 项检查)。
3. **cg-r11 第三方真值限定**:比较性第三方事实未经外部核验→真值限定为第一方评分+第三方不虚构/有界;冻结前完成外部快照可升级。
4. **sq-013 解冻**:原「PENDING MARKING CONTRACT REVIEW」阻塞由冻结政策解除 → contract READY。
5. **A35 claims 认识论**:claims 由历史 expected_answer(provenance 假设来源)+稳定分类派生,逐条标 `FREEZE_SNAPSHOT_VERIFY`——冻结时对源快照校验后方为评分真值;历史答案本身不是权威。

## 4. 分布

**交互**:RECOMMEND 30 · TROUBLESHOOT 28 · FACTUAL 24 · SOLUTION 12 · OFF_TOPIC 5 · COMPARE 6 · HOW_TO 7 · COMMERCIAL 3 · CLARIFY 2 · ORIENT 3 · FOLLOW_UP 1(=121)
**语言**:zh 97 · en 18(4 种子+13 受理 EN+1 INFERRED) · unverified 5 · ja 1
**语言出处**:ZH_CORPUS_NORMALIZED 92 · ADAPTED_ENGLISH 11 · EN_SEED 4 · PRODUCTION_CHINESE 4 · UNVERIFIED 5 · ZH_BEHAVIORAL_SEED 1 · EN_BEHAVIORAL_SEED 1(o004 修正为 ZH_BEHAVIORAL_SEED 后:EN_SEED 4= o001/002/003/x001)· ORIGINAL_ENGLISH 1 · PRODUCTION_ENGLISH 1 · INFERRED 1 · UNVERIFIED_EN_CHANNEL 1
**真值稳定性**:SNAPSHOT_BOUND 55 · STABLE 47 · CONTEXTUAL 19
**真值状态**:UNCHANGED 22 · REFINED 17 · ESTABLISHED 23 · ESTABLISHED_PER_MIGRATION_DISCOVERY 56 · INSUFFICIENT 2 · ESTABLISHED_AS_UNCERTAINTY 1
**不确定性(主标签)**:NONE_OR_STANDARD 94 · NOT_DOCUMENTED 12 · NOT_SUPPORTED 5 · NOT_TESTED 4 · CONDITIONALLY_SUPPORTED 3 · UNKNOWN 3(部分案为复合语义,如 NOT_SUPPORTED+PLANNED;未设配额)
**证据角色**:SPECIFICATION 102 · EXACT_PRODUCT 96 · WIKI 87 · SOLUTION 41 · FIRMWARE 32 · MODEL_CATALOG 16 · SDK 16 · COMMERCIAL_CURRENT 6 · SUPPORT_CASE 6 · COMPATIBILITY 4(语义扩展,已记录) · CALCULATOR 5 · STORE 4 · COMPARISON_TARGET_A/B 各 3 · SECURITY_DOCUMENTATION 2 · CASE_STUDY 1——全为语义角色,零检索实现编码
**致命失败审计**:with=121 / without=0——逐案审计结论(非机械复制):每案均存在实质致命面(核心事实捏造/交互性错误/不安全指导/注入顺从);零风格类致命项;OFF_TOPIC 种子的致命项=把注入/无关内容当产品咨询作答。

## 5. 跨语料一致性审计 = PASS(14/14)

同事实同评分 · 定价语义一致 · 能力真值兼容 · sq-108 修正案已应用 · #013 政策已应用 · NOT_DOCUMENTED≠NOT_SUPPORTED · NOT_TESTED≠不可能 · PLANNED≠已发布 · 兄弟≠本产品证据 · 引用存在≠grounding · EN 出处如实 · PII 不泄漏 · C30 无评分特权 · 零运行时 HOW。(逐项见工件 `cross_corpus_consistency.checks`)

## 6. 排除建议 / 未决阻塞

- **EXCLUSION_RECOMMENDATIONS = 无**:规范化未发现应剔除案;5 个 OFF_TOPIC 种子保留(唯一显式 off-topic 覆盖);疑似冗余对(sq-006↔cg-r17、sq-031↔cg-r03)复核为反差对/新形态。
- **TRUTH_REVIEW_REQUIRED = 0** · **POLICY_REVIEW_REQUIRED = 0**(#013 已由冻结政策解决)。

## 7. Freeze-Readiness

**READY_FOR_FREEZE = 121 · NOT_READY_FOR_FREEZE = 0**。
判据:schema 完整+真值可复现(stable / GT 已复核 / 快照源具名)+出处充分。
**冻结执行义务**(工件 `freeze_readiness.freeze_execution_obligations`):A35 claims 的 FREEZE_SNAPSHOT_VERIFY;全语料版本化源快照;动态事实重验清单(Store 价/固件状态/SDK 分发/模型目录/外部竞品);PII 匿名化(个人名→角色);sq-108 修订生效核验。READY 指**契约就绪**,冻结 Gate 仍须执行上述义务。

## 8. 非目标合规

不调生产 / 不评分当前 ASK-AI / 不改运行时与提示词 / 不变更高产与 Knowledge / 不实现 Issue #30 / 不建快照管线 / 未增删案例 / **不声明 v1 冻结**。

---

**Deliverables**:`unified_benchmark_contracts_121_2026-09-07.json` · `unified_schema_v1_2026-09-07.json` · 本报告
