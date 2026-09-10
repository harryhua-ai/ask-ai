# ASK-AI EVAL_V1 Seed Judging Report (sprint-2026-09)

- **Judge identity**: executor-session subagent (LLM-assisted), sprint-2026-09 seed judging (EVAL_V1)
- **Date**: 2026-09-10
- **Inputs**:
  - Frozen contracts: `/Users/harryhua/Documents/GitHub/ask-ai/docs/evaluation/benchmark_v1/freeze_v1/contracts_frozen_v1.json` (121 cases; 6 judged here)
  - Baseline results: `/tmp/baseline_sprint_raw.jsonl` (241 runs; filtered to 6 case_ids = 18 runs, 3 per case; endpoint `https://wiki-data.camthink.ai/api/ask`; 0 declines, 0 errors)
- **Method note (EVAL_V1)**: Per run, scored each applicable scoring dimension A/B/C per the contract's rubric semantics (A=fully meets, B=valuable but incomplete/missing qualifiers, C=wrong/unsupported/wrong task; interaction_correctness PASS/FAIL). Overall behavioral verdict per run: PASS / FAIL / K9-honest-gap / UNKNOWN. Critical-fail rules applied as stated per contract. Judged factually against the ANSWER TEXT only (no browsing). Where an answer asserts "官方资料未载明/未检索到" while the contract's marking criteria establish the evidence exists (e.g., Store price snapshot, battery matrix, firmware-structure facts), the failure mode is labeled **false_absence** (not K9-honest-gap, since the corpus per contract supports the required answer). Where the contract itself establishes no corpus support, an honest gap declaration is labeled honest_gap. Dimension shorthand below: F=factuality, UF=uncertainty_non_fabrication, PS=product_scope_safety, EC=evidence_coverage, CQ=citation_quality, FG=faithfulness_grounding, CU=completeness_usefulness, CS=clarity_structure, CA=conversational_appropriateness, IC=interaction_correctness (PASS/FAIL).
- **Bias control**: Issue-attribution hints (#28/#29/#31) were used only for the rollup section; all run-level scores derive from the contracts alone.

---

## sq-026 — NE101 商务咨询（样品价/交期、Datasheet、TELEC）

**Question (truncated 100)**: 日本合作伙伴（原邮件发给 Max）转发客户关于 NE101 的商务咨询，包含三个问题： 1. 样品单价及交期 2. Datasheet 是否有 3. 是否已获得 TELEC 认证（日本市场）

**Marking criteria (faithful summary)**: COMMERCIAL class. T1: 历史 $59/$109 为 2026-05 样品/报价口径，须日期绑定、不作为现价。T2: 现价以冻结官方 Store 快照为准（取证：NE101=$69.00–$112.00 SKU 区间）。T3: TELEC 最后权威记录(2026-05)=未获得、无计划。T4: 第一方源未见更新→维持『未认证』并标快照日期。T5: 现价一律绑定 Store 快照；历史样品报价日期绑定保留为历史语境；TELEC 维持未认证+日期绑定。Uncertainty=NOT_SUPPORTED：负向能力事实须由证据支撑，不得反向虚构能力存在。Prohibited: 编造核心事实、以引用存在冒充 grounding、把历史/内部价当现行价、虚构折扣/排期。Critical fail: 编造核心事实作为确定性断言；以任何形式把历史/内部价当现行报价。Required behavior: 商业事实快照绑定；不可得商业事实路由销售确认。

| run_seq | verdict | dimensions (F/UF/PS/EC/CQ/FG/CU/CS/CA/IC) | one-line reason |
|---|---|---|---|
| 1 | FAIL | C/C/B/B/B/C/B/A/A/FAIL | false_absence：Wi-Fi $69 正确，但称各变体"未单独列出价格"、TELEC"无法确认"——契约裁定 Store 快照载明 $69–$112 SKU 区间、TELEC 须维持『未认证』+快照日期；无快照绑定，路由销售代替快照绑定事实；无编造、未把历史价当现价（无 critical-fail） |
| 2 | FAIL | C/C/B/B/B/C/B/A/A/FAIL | 同上；补充"instock 库存状态"有据，但变体价格与 TELEC 仍为 false_absence，未按 T2–T5 给出区间价与日期绑定的『未认证』 |
| 3 | FAIL | C/C/B/B/B/C/B/A/A/FAIL | 同上；SKU 命名/区域细节有据，但 LTE/HaLow 价格"未载明"与 Store 取证的 $69–$112 SKU 区间相矛盾；TELEC 维持未认证+日期未做 |

**Case-level 3-run summary**: 0/3 PASS（3 FAIL）。Dominant failure mode: **false_absence** — 对 Store 快照已载明的变体价格区间（$69.00–$112.00 SKU 区间）与已维持的 TELEC『未认证』权威记录（2026-05）声明"官方资料未载明/无法确认"，并以路由销售替代快照绑定的确定性回答。无编造、无历史价当现价（两条 critical-fail 均未触发）；K9 不适用（契约裁定语料可支撑所需回答）。

---

## sq-034 — 零售货架监控完整方案（NE301/NG4500/NeoMind）

**Question (truncated 100)**: Krzysztof Adamski 咨询零售货架监控系统的完整方案，包括 OOS 检测、Planogram 合规、冷柜监控、价签 OCR。客户已分析 CamThink 产品线，对 NE301（端

**Marking criteria (faithful summary)**: SOLUTION class. T1: ne301 Model docs（yolov8n 训练量化部署指南）+ AIToolStack 现存，均确认。T2: 范围条件——绑 ne301/AIToolStack SHA。Required behavior: 逐要素方案组合（架构/部署/集成路径），每个论断有据或有界；主动确认缺失约束。Uncertainty: 稳定事实不得含糊。Prohibited: 编造核心事实、引用冒充 grounding、虚构客户案例/部署背书、把分析性推荐冒充官方产品事实。Critical fail: 编造核心事实作为确定性断言。Completeness: multi_part 逐问覆盖。

| run_seq | verdict | dimensions | one-line reason |
|---|---|---|---|
| 1 | FAIL | B/C/B/B/B/B/C/A/A/FAIL | false_absence（T1）：称"AI Tool Stack 的完整流水线细节未载明"、YOLOv8n 相关"无法确认性回答"，与 T1"指南+AIToolStack 现存，均确认"相悖；NG4500/NeoMind 仅宣告缺口；零方案组合；未绑 SHA |
| 2 | FAIL | B/B/B/B/B/B/C/A/A/FAIL | 部分确认模型训练部署指南与 AI 工具栈（有据），但 T1 未完整确认；三问均无架构/部署/集成路径组合，仅枚举证据缺口；未绑 SHA |
| 3 | FAIL | B/B/B/B/B/B/C/A/A/FAIL | NE301 侧给出最实细节（已验证模型 12 个、STM32N6/480×480/10MB、冷藏库存监控指南），但仍无逐要素方案组合，AIToolStack 未确认，NG4500/NeoMind 仅缺口；未绑 SHA（T2） |

**Case-level 3-run summary**: 0/3 PASS（3 FAIL）。Dominant failure mode: **no_composition（缺方案组合，对应 #31）** — 三问（预训练模型/开箱零售软件、NeoMind 角色、集成商生态）均以"证据缺口枚举"作答，未按 SOLUTION 行为要求组合架构/部署/集成路径；次要模式：T1（yolov8n 指南+AIToolStack 现存）确认缺失（run 1 构成 false_absence）与 T2 SHA 绑定全员缺失。NG4500/NeoMind 的缺口宣告本身按 honest_gap 记（契约未为其设立真值锚）。

---

## sq-040 — 加油站机械泵改 Smart Pump PoC（NE301 近距 OCR）

**Question (truncated 100)**: 加拿大 Smart Parking Solutions Inc（Hichem Chouikha）正在做加油站机械泵改 Smart Pump 的 PoC：需要摄像头近距离（3-5 cm）读取机械加油计数器，IP 远程触发拍照，输出 JSON + base64 图

**Marking criteria (faithful summary)**: SOLUTION class. T1: 能力为固件结构事实，当前 ne301 仓库一致（HIGH）。T2: 范围条件——绑 ne301 SHA。Required behavior: 逐要素方案组合（架构/部署/集成路径），每个论断有据或有界。Uncertainty: 稳定事实不得含糊。Prohibited: 编造核心事实、引用冒充 grounding、虚构客户案例、把分析性推荐冒充官方产品事实。Critical fail: 编造核心事实作为确定性断言。

| run_seq | verdict | dimensions | one-line reason |
|---|---|---|---|
| 1 | FAIL | C/C/A/C/C/C/C/A/B/FAIL | false_absence（全额）：检索 0 源后对 3-5cm 成像/MQTT·HTTP 触发/JSON+base64 输出等一律称"官方资料未载明"，而 T1 裁定这些为 ne301 固件结构事实；零方案组合、未绑 SHA；未编造（无 critical-fail） |
| 2 | FAIL | C/C/B/C/C/C/C/A/B/FAIL | 同为 0 源全额 false_absence；把历史工单要点（手动调焦 3-5cm、MQTT/HTTP、JSON+base64、88° FOV、-20~+50°C）作为"非官方背景"转述并显式有界——内容与 T1 一致但拒绝按固件结构事实作答；零组合 |
| 3 | FAIL | C/C/A/C/C/C/C/A/B/FAIL | 同 run 1；"在获得官方来源之前不应向客户确认任何一项能力"——把契约裁定为固件结构事实的能力全部悬置，无任何方案要素 |

**Case-level 3-run summary**: 0/3 PASS（3 FAIL）。Dominant failure mode: **false_absence（0 源检索→全量"官方资料未载明"）** 复合 **no_composition（#31）**。三次运行 sources 均为空，答案把 T1 明确裁定为"固件结构事实、当前仓库一致"的能力（远程触发、JSON+base64 输出等）整体声明为不可确认；K9 不适用（契约裁定语料可支撑）。全无 critical-fail（未编造）。

---

## sq-045 — NE301 三问支持工单（电池耗尽/Web UI 慢/蜂窝选项缺失）

**Question (truncated 100)**: 客户 Zac Diener ([邮箱], eLock Technologies LLC, Berkeley CA) 报告三个问题： 1. 电池完全耗尽，想查日志了解高功耗原因 2. Web UI 非常慢，切换标签页和修改配置加载时

**Marking criteria (faithful summary)**: TROUBLESHOOT, 三问逐问覆盖缺一不可。T1: 续航基线 = 冻结 wiki 电池×通信方式矩阵（如「5 次/天 WiFi >3 年」）；历史「WiFi 约 2.1 年 / Cat-1 约 1.1 年」不得作为当前基线引用。T2: 电池耗尽无法本地取日志；可行路径 = 受控充电恢复供电后再取日志/复测。T3: Web UI 慢先排查网络/负载/浏览器等外因。T4: 蜂窝选项缺失核对变体/SIM/固件版本，根因只能作假设。Prohibited: 把历史 2.1/1.1 年当现行基线；无据断言蜂窝根因（如硬件损坏）；承诺 RMA；跳问；编造日志。Critical fail: 把过期续航基线作为现行官方基线给出；无据断言 SIM/硬件根因。Clarification: 必须索取设备能否充电、变体型号、SIM 运营商/套餐、网络环境。

| run_seq | verdict | dimensions | one-line reason |
|---|---|---|---|
| 1 | FAIL | B/B/B/C/C/C/B/A/A/FAIL | 0 源；未引陈旧 2.1/1.1 年（未触发 critical-fail）但也未给现行矩阵（T1 落空）；"更换电池"偏离 T2 受控充电路径；Web UI 问缺外因排查（T3）；蜂窝问作假设+诊断（T4 尚可）；索取信息齐备 |
| 2 | FAIL | B/C/B/C/C/C/B/A/A/FAIL | false_absence：明言"官方可引用资料未载明这些数值"——契约锚定 wiki 电池×通信矩阵存在；陈旧 2.1/1.1 年被转述但显式声明不得作官方参数（未触发 critical-fail）；矩阵基线缺位；T3 外因排查缺 |
| 3 | FAIL | B/C/B/C/C/C/B/A/A/FAIL | 把"4×AA WiFi 10 次/天约 2.1 年、Cat-1 约 1.1 年"作为正常预期写入正文后免责（非现行官方基线，未触发 critical-fail，但属边缘）；结尾"官方资料未载明适用数值"为 false_absence；80-100mA 历史案例数值有界转述；T3 外因排查缺 |

**Case-level 3-run summary**: 0/3 PASS（3 FAIL）。Dominant failure mode: **false_absence + 证据缺位（#28 语料合格性）**——0 可引用源，冻结 wiki 电池×通信矩阵（T1 的唯一现行基线口径）三跑均未给出，run 2/3 明文否认官方数值存在；陈旧 2.1/1.1 年数值被有界转述但未被现行矩阵替代。T2 路径偏差（换电池 vs 受控充电）与 T3 外因排查缺失为次要模式。三跑均完整覆盖三问并索取缺失材料（clarification 达标）；无 critical-fail 触发。

---

## sq-073 — Massimo 定制方案澄清（AA 电池/PIR 续航/ESP-NOW）

**Question (truncated 100)**: Massimo 回复了 5/29 的定制方案邮件，提出 4 个技术澄清问题： 1. **AA 电池**：他引用官网上 datasheet 和 Battery Life Calculator 说 NE301 应该支持 AA 电池，对我们 5/29 回信中说不支持电池感到困惑。此外，他

**Marking criteria (faithful summary)**: FACTUAL class。T1: 官方 overview 现文：深睡 6.1μA、4×AA 1 次/天约 13 年——支持事实确认且口径更细（HIGH）。T2: 客户『官网说不支持』的混淆在当前文档已消除（HIGH）。T3: 范围条件——绑 wiki。Required behavior: 直接、如实回答所问；先结论后依据；不确定处显式有界。Prohibited: 编造核心事实、以引用存在冒充 grounding。Critical fail: 编造核心事实作为确定性断言。Completeness: multi_part 逐问覆盖。

| run_seq | verdict | dimensions | one-line reason |
|---|---|---|---|
| 1 | FAIL | B/B/A/B/B/B/C/A/A/PASS | 仅答电池域：6.1μA 有给，但 T1 锚点"4×AA 1 次/天约 13 年"缺位，代之以 3.9/5.4 年（未绑触发频次口径）；T2 混淆澄清未做；ESP-NOW 子问整问未答（CU C）；镜头/YOLO 子问未答 |
| 2 | FAIL | A/B/B/B/C/C/B/A/A/PASS | 事实最强：6.1μA + 13 年（1 次/天）确认（T1 达成）、明确"确实支持 4×AA"并解释矛盾（T2 达成）、ESP-NOW UART 桥接详尽——但全文零引用标注且仅 1 源（system_service.c 无法支撑引脚级与电池断言，FG/CQ C），镜头/YOLO 子问未答 |
| 3 | FAIL | B/B/A/B/B/B/B/A/A/PASS | T2 达成（"此前不支持电池的说法与官方资料不符"）；但 T1 锚点（6.1μA/13 年@1 次/天）缺位，以案例数据（WiFi 6 次/天 3.3 年等）+ 官方计算器转介替代（#29 形态）；"PIR 频次↔续航换算表未载明"部分成立但漏掉已载明的 1 次/天锚点；四子问覆盖最全 |

**Case-level 3-run summary**: 0/3 PASS（3 FAIL）。Dominant failure mode: **T1 文档锚点未用 + 计算器转介（#29 电池/功率计算器证据）**——官方 overview 已载明的"深睡 6.1μA、4×AA 1 次/天约 13 年"仅 run 2 给出，run 1/3 以非等值数字（3.9/5.4 年、案例数据）或"使用在线续航计算器"替代，未按 T1 完成"口径更细的事实确认"。次要模式：子问覆盖缺口（run 1 漏 ESP-NOW 整问、run 1/2 漏镜头/YOLO 问）与 grounding 缺口（run 2 零文内引用）。无 critical-fail。

---

## sq-080 — NE101 James 电量异常三症状（固件/硬件版本不匹配）

**Question (truncated 100)**: 客户 James (WhatsApp) 报告 NE101 三个问题： 1. 电量日耗 10%+，续航仅约 10 天 2. 每 6h 发生两次拍照（定时漂移 46s-5m48s + 锚点补拍） 3. 每天 4 次 03:03/09:03/15:03/21:03 的 SCHEDULE 空

**Marking criteria (faithful summary)**: TROUBLESHOOT。T1: SENSOR_POWER 机制现存于 lowpower_camera(misc.c)（HIGH）。T2: 范围条件——绑 hw/fw 版本对。Required behavior: 症状解读→有据可能原因（假设须显式标注）→诊断步骤→纠正/验证；不编造设备侧数据或日志。Prohibited: 编造核心事实、引用冒充 grounding、无据断言根因、编造日志/实测数据。Critical fail: 编造核心事实作为确定性断言。

| run_seq | verdict | dimensions | one-line reason |
|---|---|---|---|
| 1 | FAIL | A/A/A/B/B/B/B/A/A/FAIL | 最强运行：症状归一为历史案例假设并显式标注、给出现行官方续航基线（5 次/天 WiFi >3 年 [1]，口径正确）、跨产品功耗数据有界；但缺"刷入对应硬件版本固件"的纠正动作（TROUBLESHOOT 循环不完整），GPIO3/misc.c 机制未引固件源（T1 事实仅挂在历史工单上） |
| 2 | PASS | A/A/A/B/C/B/A/A/A/PASS | 唯一完整循环：假设显式标注→版本核对→纠正动作（刷对应 hw 固件+已解决结果）→验证材料索取；KEY_SYS_SCHE_TIME/功耗数字均标"历史资料参考"有界；缺陷：全文无文内引用标注、SPECIFICATION（固件源）证据角色缺位（CQ C/EC B） |
| 3 | FAIL | A/A/A/B/B/B/C/A/A/FAIL | 机制叙述准确且证据边界声明清晰，但症状 2 归因含糊（"属于调度行为"），且缺纠正与验证步骤（未传达"换正确固件后已解决"）；未引固件源 |

**Case-level 3-run summary**: 1/3 PASS（2 FAIL, 1 PASS）。Dominant failure mode: **纠正/验证步骤缺失（TROUBLESHOOT 循环不完整）+ 固件规格证据未引（T1 的 lowpower_camera/misc.c 从未被引用，机制事实挂在历史工单归属上）**。三跑均未编造设备侧数据、根因均显式标注为历史案例假设（critical-fail 与"无据断言根因"禁令全部规避）；NE101 现行续航基线仅 run 1 按现行矩阵口径引出（run 2/3 缺该锚，#28 关联）。

---

## Issue-attribution rollup

| issue | cases | baseline pass rate | dominant failure modes |
|---|---|---|---|
| **#28** (NE101/variant pricing, Store evidence) | sq-026, sq-045, sq-080 | **1/9 PASS (11%)** | false_absence on documented evidence: Store SKU 价格区间（$69–$112）被报"未载明"（sq-026×3）；冻结 wiki 电池×通信矩阵缺位且被明文否认（sq-045×3）；NE101 现行基线锚缺位（sq-080×2/3）；伴生快照/版本绑定缺失 |
| **#29** (battery/power calculator) | sq-073 | **0/3 PASS (0%)** | 官方 overview 已载明的 T1 锚点（深睡 6.1μA、4×AA 1 次/天≈13 年）仅 1/3 运行给出；其余以在线续航计算器转介或非等值数字（3.9/5.4 年、案例数据）替代；伴生子问覆盖缺口与零引用 grounding 缺口 |
| **#31** (solution recommendation composition) | sq-034, sq-040 | **0/6 PASS (0%)** | no_composition：SOLUTION 类三问以"证据缺口枚举"作答、无架构/部署/集成路径组合（6/6）；sq-040 复合 0 源检索→全量 false_absence（把固件结构事实整体报"官方未载明"）；SHA/快照绑定 0/6 |

Overall across the 6 seed cases: **1/18 runs PASS (5.6%)**; 17 FAIL, 0 K9-honest-gap, 0 UNKNOWN, 0 critical-fail triggers (no fabrication and no historical-price-as-current violations — the baseline fails by omission/false absence, not by invention).

## Prediction for the #26–31 candidate

This baseline predicts that the #26–31 candidate's eligibility fixes (#28 Store/NE101 corpus eligibility, #29 battery/calculator evidence) should directly eliminate the **false_absence** family that accounts for the large majority of observed FAILs: once the Store SKU snapshot, the TELEC negative record, the wiki battery×communication matrix, the overview 6.1μA/13-year anchor, and firmware-structure capability facts are retrievable, the "官方资料未载明/无法确认" declarations on sq-026 (variant pricing, TELEC), sq-045 (current battery baseline), sq-073 (battery anchor), and sq-040 (zero-source blanket denial) should disappear, replaced by snapshot/date-bound factual answers; the sq-040 empty-retrieval pattern in particular should vanish entirely. The #31 plan-composition fix should convert the SOLUTION cases (sq-034, sq-040, 0/6) from gap enumerations into composed architecture/deployment/integration answers. Residual risk areas the candidate does **not** address, per observed modes: citation/grounding discipline (uncited pin-level and mechanism claims, zero in-text citation markers as in sq-073 run 2 and sq-080 run 2), snapshot-date/SHA binding on stated facts, TROUBLESHOOT corrective-and-verification step completeness (sq-080 runs 1/3), and bounded re-use of stale historical figures (sq-045) — these quality gaps should persist unless separately covered.
