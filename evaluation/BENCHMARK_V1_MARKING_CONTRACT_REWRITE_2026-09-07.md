# ASK-AI Answer Intelligence Benchmark v1 — 30-Case Marking Contract Rewrite

> **性质**:DISCOVERY / EVALUATION DESIGN ONLY · READ ONLY(GitHub Issue #32;无生产/知识源/Answer Engine 变更)
> **日期**:2026-09-07 · **执行**:Executor · **状态**:MARKING_CONTRACT_REWRITE **PASS**(自评,待 Planner FINAL REVIEW)
> **工件**:`docs/evaluation/benchmark_v1/marking_contracts_c30.json`(机器可读,30 契约)

---

## 1. 选择验证

| 项 | 值 |
|---|---|
| 选择源 | `migration_inventory_117.json`(REV1) |
| 过滤条件 | `migration_state = C` |
| 选中 | **30**(与期望一致,SELECTION_CHECK = PASS,未改动 inventory) |
| GT 重叠(9) | sq-003 / sq-014 / sq-045 / sq-049 / sq-074 / sq-093 / sq-103 / sq-108 / sq-109 |
| 非重叠(21) | 真值权威 = 迁移 Discovery 证据 + 冻结源材料(各契约 `truth_reference.stable_fact_anchors`) |

## 2. 真值权威执行

- 历史 expected_answer 一律**非权威**,仅在 provenance 层保留;逐案例程序化校验了 question/seq/interaction_class/language 与 inventory 零偏差。
- 9 个 GT 重叠案例真值以 `ground_truth_revalidation_41.json @54f9c9d` 为权威(程序化断言 current_truth_status / uncertainty_state / benchmark_truth_ready 三字段逐案一致)。
- 本轮未发现新的实质性事实矛盾 → **TRUTH_REVALIDATION_REQUIRED = 0**(未静默修复任何真值)。

## 3. 契约模型与评分语义

每契约 8 层:USER TASK / INTERACTION REQUIREMENT / REQUIRED TRUTH(原子化+criticality)/ EVIDENCE ROLES(语义角色,不冻结检索实现)/ UNCERTAINTY / PROHIBITED / CITATION(支撑判定,非存在判定)/ COMPLETENESS(任务覆盖,非篇幅)。

评分:10 个语义维度逐案定义 A/B/C 语义;`interaction_correctness` 统一 PASS/FAIL(真二值);**逐维度结果为权威,无单一 opaque overall boolean**。OPERATIONAL 维度(TTFT/E2E、LLM calls/tokens)列入维度集但本 Gate 不设 case 级阈值(无既有冻结要求,不发明性能阈值)。

## 4. 计数

| 项 | 值 |
|---|---|
| SELECTED / PROCESSED | 30 / 30 |
| READY / NOT_READY | **30 / 0** |
| SECURITY_POLICY_DECISION_REQUIRED | 0 |
| TRUTH_REVALIDATION_REQUIRED | 0 |
| 交互类分布 | RECOMMEND 17 · TROUBLESHOOT 5 · FACTUAL 2 · HOW_TO 1 · COMMERCIAL 1 · CLARIFY 1 · ORIENT 1 · COMPARE 1 · SOLUTION 1 |
| critical-fail 覆盖 | 30/30 案例均有显式 critical-fail 条件(仅实质正确性/安全失败,不含风格) |
| 证据角色使用 | EXACT_PRODUCT 24 · SPECIFICATION 23 · WIKI 14 · MODEL_CATALOG 11 · SOLUTION 11 · SDK 7 · FIRMWARE 7 · CURRENT_COMMERCIAL 5 · COMPATIBILITY 4 · CALCULATOR 2 · STORE 1 · SUPPORT_CASE 1 · SECURITY_DOCUMENTATION 1 |

## 5. 特殊案例处理

### #014(火灾模型)— 按 GT 保持
契约保留 `NO_OFFICIAL_PRETRAINED_MODEL_LISTED`:官方名录无火灾/烟雾预训练模型(COCO80 仅 fire hydrant)≠「平台不支持火灾检测」;自定义部署路径 = NOT_TESTED 有界表述(POC/合作验证)。双向越界均入 prohibited + critical-fail。

### #103(Gundi/EarthRanger 未决真值)— 不确定性转换判定:**可成立**
- 判定:**YES**,问句可成立为不确定性/证据不足型契约。理由:问句文本仅要求产品推荐(野生动物监测+AI 识别+蜂窝上传);产品侧推荐有历史源快照依据(绑 Knowledge @d4f7f49b);集成话题只需有界不确定性语义即可正确回答,无需正面集成真值。
- 契约形态:正确行为本身 = 「第一方文档未见 Gundi/EarthRanger 记载」的如实表达 + 官方确认路由;**断言集成存在 = critical fail**(历史期望答案正是此模式 → 按新契约必须 FAIL)。
- GT 正面真值仍按 GT 工件保持 NOT_READY/INSUFFICIENT;转换判定与理由已写入工件 `uncertainty_contract_conversion_decision` 字段。

### #013(安全敏感)— **ESCALATED,未发明政策**
核查发现 **sq-013 的 migration_state = B(非 C),不在本 Gate 30 案例选择集内**。按「恰好 30 个 C 案例」硬约束执行,未扩选第 31 案例。已应用其全局实质:凭证值零出现规则(工件+报告程序化扫描 0 出现)。**#013 的专用基准安全契约推导需 B 轨契约 Gate 或明确范围扩展授权** — 上报 Planner 裁决(SECURITY_CONTRACT_DEFERRED)。

### #026(定价)— 转写为跨案例规则
核查发现 **sq-026 的 migration_state = B(非 C)**。未扩选;其 GT 已裁决语义(历史 $59/$109 = 带日期样本/报价;现价 = Store 快照)已转写为跨案例规则 **R1 商业快照绑定**,作用于 C 集商业内容案例(sq-030/sq-093/sq-019 等):把历史/内部价当现价 = critical fail;不冻结无时效数字 Store 价,现价评估绑基准源快照。

## 6. 跨案例一致性审计(CROSS_CASE_CONSISTENCY = PASS)

工件固化 14 条跨案例规则(R1–R14),审计确认无矛盾:

| 审计项 | 结果 |
|---|---|
| 同一产品事实跨案 grading 一致 | PASS(MLX90642 定性 R3 三案一致;PIR R4 四案一致;续航基线 R2 三案一致) |
| 快照绑定事实带日期/版本语义一致 | PASS(R1/R2;GT9 案例全部携带 snapshot 绑定) |
| NOT_DOCUMENTED 不当 NOT_SUPPORTED | PASS(R5,双向禁止) |
| NOT_TESTED 不当不可能 | PASS(R6) |
| 兄弟产品证据不作本产品证据 | PASS(逐案 product_scope_safety;sq-020/sq-105/sq-014 critical fail 化) |
| 推荐标准不编码历史销售偏好 | PASS(R14 + R11 语境剥离) |
| 引用存在≠grounding | PASS(R12,30/30 显式声明) |
| 缺参澄清不惩罚 | PASS(R13,sq-031 核心 + 三案参数请求要件) |
| 未知真值不确定性不惩罚 | PASS(sq-103 契约的正确行为即有界不确定性) |

## 7. 历史假通过防御(HISTORICAL_FALSE_PASS_DEFENSE = PASS)

七类历史假通过模式逐一映射到新契约的失败路径(工件含完整 demonstration):

1. **非空回答即过** → `interaction_correctness` 任务绑定 PASS/FAIL:sq-031 不澄清直接推销=FAIL;sq-035 认同错误前提=FAIL;sq-078 未纠正误解=FAIL。
2. **未拒答即过** → sq-109 自信给出 BAA/TAA 结论(任一方向)= uncertainty C + critical fail;反之 sq-031 错误拒答同样 FAIL。
3. **n_sources>0 / 存在 [1] 即过** → R12:sq-014 用概览页支撑模型目录断言(来源错配)= citation C;30/30 案例显式「引用存在不构成 grounding」。
4. **看起来合理即过** → factuality 锚冻结证据:sq-078 编造 cloud URL / sq-101 原生 BACnet / sq-091 医疗适用 = critical fail。
5. **提到相关产品即过** → 兄弟产品替代禁令:sq-020 NE301 证据答 NE101 = critical fail。
6. **旧评测器判 correct 即过** → sq-103 历史答案(断言 Gundi/EarthRanger 集成)在新契约下 critical fail;sq-014 历史无界「支持自定义部署」降 B/C。
7. **推荐与历史销售记录一致即过** → R14:不同推荐只要满足已验证真值与证据契约即为正确;sq-030 内部策略泄漏=C;sq-054 无约束绝对化推荐=critical fail。

## 8. 实质性契约模式发现

1. **不确定性双向界是 C 集最大的系统性语义**(30 案中 10+ 案核心):NOT_DOCUMENTED(R5)与 NOT_TESTED(R6)需要分开的双向禁令;历史语料的失败模式多为单向(只防虚构、不防「宣称不可能」的过度否定,或反之)。
2. **「部署侧逻辑 vs 产品自带」分界**(sq-015 越线判定、sq-105/sq-108 people counting、sq-090 keypoint MQTT 路径、sq-101 BACnet 转换层):历史答案倾向把集成/部署层方案说成产品能力,新契约全部要求显式分层。
3. **无设备/无站点数据时的结论纪律**(R8+R13):SN 级根因、站点约束缺失下的推荐,正确行为=假设标注+方法论+数据请求,而非编造结论——TROUBLESHOOT 三案(sq-029/063/083)与 RECOMMEND 条件化案(sq-054/104)的共同骨架。
4. **商务运营事实与知识边界**(R9):订单状态/MOQ/折扣/排期一律 UNKNOWN+路由;知识库不冒充 ERP/CRM。
5. **伞形问句可拆性**(R10):multi_part 案例按源快照冻结子问清单后可逐问评分,sq-090 证明了 12 问级伞形的可评分形态。

## 9. 未决 Product/Security/Truth 决策(上报 Planner)

| # | 事项 | 性质 |
|---|---|---|
| 1 | **sq-013 专用安全契约**:B 态不在本 Gate 范围;需 B 轨契约 Gate 或范围扩展授权;是否允许合法支持答案中字面披露凭证值 = SECURITY_POLICY_DECISION(本 Gate 未发明政策,凭证值全程零出现) | Security/Product |
| 2 | **sq-026 本体契约**:B 态;其定价语义已作 R1 全局规则,其自身 B 轨标记契约仍属 B 批次工作 | Product |
| 3 | **sq-103 正面集成真值**:若未来要考「集成存在」的正向事实,需第一方 EarthRanger/Gundi 证据取证(Planner 另行授权);当前不确定性契约形态不需要 | Truth |
| 4 | **sq-014 自定义部署能力**:如需从 NOT_TESTED 升级为已验证能力,需官方取证(当前有界表述不依赖) | Truth |

## 10. 不冻结声明

本 Gate 通过**不等于** Benchmark v1 冻结或就绪:剩余前置 = 32 个 B 案例的快照复核与标记、B/A 批次契约覆盖、EN/ZH parity 与 uncertainty/FOLLOW_UP/ABSTAIN 缺口获取(获取顺序=真实生产证据→既有证据→合成)、#013 安全契约决策、TELEC 等认证类事实冻结前复查。

## 11. 边界合规

PRODUCTION_MUTATION = NO · KNOWLEDGE_SOURCE_MUTATION = NO · ANSWER_ENGINE_IMPLEMENTATION = NO · inventory/GT 工件零改动 · 生产 /api/ask 零调用 · 运行基准零执行 · interaction_class 为基准专用标签,不构成运行时意图体系实现要求。

---

**Deliverables**:
- 工件:`docs/evaluation/benchmark_v1/marking_contracts_c30.json`(30 契约,程序化校验通过:30/30 字段完整、GT9 真值三字段逐案一致、inventory 对齐零偏差、凭证模式 0 出现)
- 本报告:`docs/evaluation/BENCHMARK_V1_MARKING_CONTRACT_REWRITE_2026-09-07.md`
