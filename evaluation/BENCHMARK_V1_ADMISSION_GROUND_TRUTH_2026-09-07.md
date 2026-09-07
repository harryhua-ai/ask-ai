# ASK-AI Answer Intelligence Benchmark v1 — Coverage Additions Admission & Ground Truth

> **性质**:DISCOVERY / EVALUATION ONLY · READ ONLY(GitHub Issue #32;无生产/知识源/Answer Engine 变更)
> **日期**:2026-09-07 · **执行**:Executor · **状态**:ADMISSION_GROUND_TRUTH **PASS**(自评,待 Planner FINAL REVIEW)
> **输入**:`coverage_gap_additions_2026-09-07.json`(24 候选,COUNT_CHECK=PASS)
> **工件**:`admission_ground_truth_24_2026-09-07.json`(逐案裁决,机器可读)
> **声明**:121 仍为**拟议池**,非 Benchmark v1 Freeze;本 Gate 不撰写完整最终标记契约。

---

## 1. 裁决计数

| 准入 | GT 真值 | EN 分类(受理) |
|---|---|---|
| **ADMIT = 8**(r02/r03/r04/r06/r12/r19/r20/s01) | **READY = 23** | ORIGINAL_ENGLISH = **1**(r07 BoschIndia 客户邮件原文逐字存档) |
| **ADMIT_WITH_QUALIFICATION = 16**(r01/r05/r07/r08/r09/r10/r11/r13/r14/r15/r16/r17/r18/r21/r22/r23) | **READY_AS_UNCERTAINTY = 1**(r22:权威源实质冲突=文档 3.11/3.12 vs Dockerfile 3.10,矛盾本身可复现) | PRODUCTION_ENGLISH = **1**(r03 生产 widget 逐字问句) |
| **HOLD = 0** · **REJECT = 0** | **NOT_READY = 0** | ADAPTED_ENGLISH = **11** · TRANSLATED_ENGLISH = **0** |

**ACCEPTED_ADDITIONS = 24** → **PROVISIONAL_ACTIVE_POOL = 121** · **ACCEPTED_ENGLISH_KNOWLEDGE_CASES = 13**

### 独立性说明(为什么 0 HOLD / 0 REJECT)
准入独立于发现 Gate 行使,不是照单全收:①wiki 锚点重验(NE302 系列、NeoRuntime 文档、LPR 应用示例——后者直接改写了 sq-108 调和结论);②语言 provenance 逐案核证,**EN 计数从 18 修正为 13**(cg-r01 语言未验证降为 unverified;r11/r19/r20/r21/r23 因交互语言未留痕不计入 EN;7 案重新归类);③16 案附加显式限定;④PII 匿名化修订(r08/r09/r23 展示问句个人名→角色);⑤cg-r22 从 READY 降为 READY_AS_UNCERTAINTY。24 案全部经过两轮实证(发现 Gate 源文件逐案阅读+本 Gate 锚点重验),无未决实质阻塞,故无 HOLD/REJECT。

## 2. ADAPTED_ENGLISH 的诚实边界

11 个 ADAPTED_ENGLISH = **真实英文往来实证**(英文回复邮件/WhatsApp 存档)+ **问句文本为案例记录重构**(客户原话未逐字保存于案例文件)。它们被如实标注为 ADAPTED,不冒充真实英文用户原话;逐字英文原文恢复属冻结时源快照工作。TRANSLATED_ENGLISH = 0(无中文题翻译充数)。cg-r23 语言为 INFERRED,主动排除在 EN 统计外。

## 3. sq-108 ↔ cg-r12 强制真值调和 = RESOLVED

- **根因判定**:陈旧真值 + 术语/范畴混用。sq-108 契约 T4 于 2026-09-05 取证时以 SDK 事实为锚,未纳入官方应用目录证据;且把「预装/一键应用形态未记载」与「官方无任何 ALPR 应用记载」混为一句。**非产品区分、非版本区分、非真实源冲突**——cg-r12 的 wiki 证据与 sq-108 的 SDK 证据相容。
- **决定性证据**:wiki @4ed5b32e NE503 overview 智慧安防节「应用示例」文档化**车牌识别**:容器化部署车牌识别模型、识别结果经事件总线推送(app-lpr 资源引用);cookbook person-detection 含 person_count。
- **Planner 修订建议**(本 Gate 未改动任何已验收工件):
  - **OLD**:「T4: ALPR / people counting = 须经模型部署实现的分析任务;官方无预装 ALPR/people counting 应用记载;…」
  - **NEW**:「T4: 车牌识别(LPR)与行人检测为官方 overview 文档化的应用能力(容器化部署+事件总线推送);『预装/一键应用』形态与官方预置应用/模型清单未经第一方记载 = NOT_DOCUMENTED;8+ 路并发可行性仍须负载估算或 POC,不得虚构官方路数上限。」
  - **REASON**:官方 overview 已文档化 LPR 应用示例——「无任何记载」分句过强;能力文档化与预装形态须分层。
  - **UNCHANGED CONTRACT SURFACES**:T1/T2/T3、全部评分维度、critical fail、product_scope_safety/citation 语义均不变。
- **调和后状态**:cg-r12 = READY;sq-108 按 NEW 修订后两者一致。SQ108_CGR12_RECONCILIATION = **PASS**(修订落地由 Planner 执行)。

## 4. 生产回归语义保全核验(8/8)

#5(多案:NE302 独立系列/NE503 逐能力盘点/竞品边界/量化升级/检测vs识别+既有 sq-081 反向陷阱)·#19(r01 多目标对比+对比不足路径;Store 元数据/empty-generation 属引擎侧不入真值)·#23(r02 原问句+真值经权威 NeoRuntime 文档验证;阈值未冻结)·#26(r03 域内欠指定→澄清)·#27(r04 能力导向+s01 EN 对等)·#28(r05 变体/现行价+逐组合价有界)·#29(r06 结构化计算器证据)·#31(r07 Solutions/Case/Wiki 组合)——逐案核验记录在工件 `regression_semantic_preserved` 字段,无表面名称映射。

## 5. cg-s01(adapted)单独裁决

**ADMIT**:EN 能力导向问句的语言路由正确性是 #27 缺陷族的实证面(生产 EN 误拒已有先例 #26);`synthetic=true`+`ADAPTED_ENGLISH` 如实标注;非为 EN/ZH 对称而保留——语言行为本身即测试点。

## 6. FOLLOW_UP 核验(cg-r23)

真实前序依赖成立(显式引用 7/14 评估+『已购/测试中』现状;独立问句丢失评估历史与 turnkey 画像适配)。**最小安全上下文已捕获入工件**(minimum_safe_context 字段),不含 CRM/商务历史;客户身份匿名化。

## 7. CASE_BOUNDARY / PRIVACY 建议

- 分类:**CASE_BOUNDARY_ISOLATION + PRIVACY + EVIDENCE_PROVENANCE_ISOLATION**(评测/安全维度,不新增运行时交互类)。
- **现不设专案**:E03/E01/D05 行为族需「内部案例语料在场+相似症状提问者」的受控构造,与基准工件不得内嵌真实客户案例/PII 的边界相抵 → 记录为 REMAINING_GAP(附设计要求,须 Planner 专项授权)。
- **PII 卫生已执行**:本工件展示问句个人名→角色匿名化(r08/r09/r23);24 案逐案标注 privacy 维度;建议 117 语料冻结时同等处理。

## 8. 受理交互/不确定性分布

交互:RECOMMEND 3 · TROUBLESHOOT 5 · FACTUAL 3 · SOLUTION 3 · COMPARE 3 · HOW_TO 2 · ORIENT 2 · COMMERCIAL 1 · CLARIFY 1 · FOLLOW_UP 1(=24)。
不确定性:NONE/行为型 8;中心不确定性语义 16(NOT_SUPPORTED 5 · NOT_DOCUMENTED 5 · CONDITIONALLY_SUPPORTED 3 · PLANNED 3 · UNKNOWN 1 · NOT_TESTED 1 · CONTRADICTORY_EVIDENCE 1;跨案可复合)。无目标数量优化。

## 9. 准入后剩余缺口

真实 OFF_TOPIC 留痕(需授权导出)·CASE_BOUNDARY 受控构造·多轮会话导出·**sq-108 T4 修订落地(Planner)**·#013 安全契约·第三方/竞品证据快照管线·EN 原文回填决策(sq-081/sq-082 等)。

## 10. 非目标合规

不改运行时/提示词/检索/重排;不调生产;不变更生产与 Knowledge;不改写 117 历史语料;不为 24 案撰写完整最终标记契约;不冻结 v1;不建快照服务;未在 Gate 内新增任何案例。

---

**Deliverables**:`admission_ground_truth_24_2026-09-07.json`(24 案 × 21 字段+调和+建议)· 本报告。
