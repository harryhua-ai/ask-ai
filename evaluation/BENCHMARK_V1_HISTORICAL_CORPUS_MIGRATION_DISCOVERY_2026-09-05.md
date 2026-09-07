# ASK-AI Answer Intelligence Benchmark v1 — 历史语料迁移 Discovery

> **性质**:DISCOVERY ONLY / READ ONLY(对应 GitHub Issue #32;无任何生产/知识源/Answer Engine 变更)
> **日期**:2026-09-05 · **执行**:Executor(产品窗口授权)· **状态**:DISCOVERY PASS

## 1. 语料来源与 provenance

| 项 | 值 |
|---|---|
| 权威文件 | `/Users/harryhua/Documents/GitHub/Knowledge/知识库/Think/ASK AI/optimize/standard_questions.json` |
| 版本 | **v2.1**(文件内嵌 version 字段;2026-08-07 16:04 最后修改,单一候选版本文件) |
| 案例数 | **117**(与 Issue #32 宣称一致;`questions` 数组) |
| 构建 provenance | 文件内 description:『从 support + sales 知识库梳理的真实客户问题库…expected_answer 由 build_question_bank.py 提取 + support skill』;`generated_from: support/ + sales/` |
| 源可解析性 | 112/117 含 `source_file`,**全部**在 Knowledge 仓 `support/`、`sales/` 下解析成功(MISSING=0);5 题为 off_topic seed(无源文件) |
| 历史评测快照 | `optimize/results/` 6 个快照(2026-08-07~08-11);其中 2026-08-11T10-25 与 T13-30 两份为 **117 题全量**运行;快照为评测输出而非语料分叉,未见其他 117 题版本文件 |
| 活索引 | `support/TS_record.md` 为支持案例活索引(日期/客户/产品/状态),与语料 source_file 一一对应;注意索引中相当部分案例状态为「待确认」 |

**版本歧义结论**:仅存在一个 117 题语料文件(v2.1),未发现分叉版本;results/ 快照内嵌题目为其运行时副本,不构成第二语料。无合并动作。

## 2. 迁移分类汇总

| 迁移态 | 数量 | 含义 |
|---|---|---|
| A CORE | **35** | 可直接/轻度修复后进入活跃基准 |
| B REVERIFY | **32** | 问题有价值;期望事实需对源快照/发布物复核 |
| C REWRITE | **30** | 问题有价值;历史 expected_answer 需重写为标记契约 |
| D ARCHIVE | **20** | 销售侧 CRM 档案(14)、内部商务/报价(4)、空答案(2) |
| NEEDS_REVIEW | **0** | 所有案例均可归入给定交互分类 |

## 3. 交互分类分布(仅基准分析用,不改运行时意图体系)

| 交互类 | 数量 | 交互类 | 数量 |
|---|---|---|---|
| RECOMMEND | 38 | TROUBLESHOOT | 26 |
| FACTUAL | 22 | SOLUTION | 9 |
| COMMERCIAL | 7 | HOW_TO | 5 |
| OFF_TOPIC | 5 | COMPARE | 3 |
| CLARIFY | 1 | ORIENT | 1 |

FOLLOW_UP=0、ABSTAIN(证据不足型拒答)=0、COMPARE 仅 3——与 Issue #32 覆盖契约相比,历史语料天然缺失这些家族,须由生产种子(#26–#31)与补齐合成填充。

## 4. 语言 / 真值稳定性分布

- 语言:zh=110,en=7。**7 个英文案例全部是 D(销售档案)或 off_topic seed——A/B/C 活跃集中英文表征为零**,EN/ZH parity(原则 9)须由新案例补齐,历史语料无法提供。
- 真值稳定性:stable=37,snapshot_bound=46,contextual=34。

## 5. 复核需求计数

- 需事实复核(current_fact_revalidation):**62**(全部 B+C)
- 需源快照复核(source_revalidation):**112**(凡引用源文件的案例,冻结时一并版本化快照)
- 天然不确定性案例(uncertainty):**8** → #14(无火灾模型)、#18/#60(HaLow 网关兼容=实测 vs 理论)、#19(MOQ 未决)、#31(需求模糊须澄清)、#43(BMeters 兼容=推断)、#91(医疗筛查边界)、#104(滚筒/全局快门+待确认)——**仅 6.8%**,远低于 Issue #32 的 15–20% 目标,缺口需补齐。
- 需标记契约重写:**30**(全部 C)

## 6. 重复 / 近似重复组

| 组 | 案例 | 说明 |
|---|---|---|
| 1 | #007/#008 | 同一固件行为(按键 vs 定时补光灯),两客户 |
| 2 | #005/#017 | NE101 HW v1/v1.2 差异与识别 |
| 3 | #025/#106 | Lightbox 建筑监控,sales 显式互链 support 案例 |
| 4 | #082/#096 | Ken Vowels Webhook PUSH FAIL,sales 复制 support |
| 5 | #070/#088/#097 | Maloric 线程(support 8 问/scope 报价/sales 档案) |
| 6 | #079/#081 | 非重复但构成**产品隔离对照对**(NE301 可远程触发 vs NE101 不可) |

相关家族(非重复,建议冻结时同族抽检):#021/#056/#089(PIR)、#016/#029/#062/#063(PwC)、#011/#012/#046(Kajima)、#094/#066(Eco-Counter)。

## 7. 损坏 / 不可恢复案例

- **broken(历史无真实答案)=4**:#066(进水——『等待客户回复』)、#068(NeoMind 上线——『等待测试反馈』)。
- CRM 工作流状态型(expected=『邮件已发出/等待会议』):#016、#062,连同内部报价/会议准备类 #052/#071/#088/#095/#107 全部 D。
- 未发现截断题目;未发现 JSON 结构损坏;未发现「答案与其引用源自相矛盾」案例;1 处**跨案例定价矛盾**:#026(WiFi $59/Cat-1 $109 样品价)vs #112(WiFi $69)——真值必须由 Store 快照裁决,历史答案不得直接当现价。
- 1 处安全敏感:#013 期望答案含默认凭据(`hicamthink`)——冻结前需安全评审是否保留该事实。

## 8. 特殊复核标志分布(快照敏感真值)

- crm_account_record:12
- customer_session:6
- uncertainty_core:5
- seed:5
- firmware:4
- released_vs_planned:4
- commercial:4
- toolchain:3
- moq:3
- price:3
- model_lineup:3
- hw_version:2
- security_sensitive:2
- crm_workflow:2
- certification:2
- device_sn_specific:2
- customization:2
- product_config:2
- no_answer_recorded:2
- multi_part_umbrella:2
- dataset_format:1
- sales_pitch:1
- releases:1
- lead_time:1
- internal_strategy:1
- clarify_core:1
- software_availability:1
- model:1
- orientation:1
- module_lineup:1
- snapshot_demo:1
- specs:1
- multi_part:1
- privacy:1
- model_capacity:1
- internal_pricing_review:1
- third_party_module:1
- scenario_dependent:1
- board_lineup:1
- license:1
- internal_commercial_scope:1
- contradiction_customer_vs_datasheet:1
- misconception_correction:1
- hw_limits:1
- toolchain_version:1
- nre_quote:1
- medical_boundary:1
- halow_region:1
- bacnet_boundary:1
- platform_integration:1
- shutter_boundary:1
- internal_meeting_prep:1
- baa_taa_boundary:1

历史事实一律不得静默成为现价/现状(尤其 price/certification/firmware/released_vs_planned 类)。

## 9. 逐题迁移清单(117)

| # | 语言 | 旧意图→交互类 | 迁移态 | 真值稳定 | 不确定 | 期望答案状态 | 标志/备注 |
|---|---|---|---|---|---|---|---|
| 1 | zh | support→SOLUTION | B | snapshot_bound | N | usable | toolchain,dataset_format |
| 2 | zh | support→SOLUTION | B | snapshot_bound | N | usable | toolchain |
| 3 | zh | support→HOW_TO | C | snapshot_bound | N | partial | toolchain,customer_session;客户会议诉求需剥离 |
| 4 | zh | product→FACTUAL | A | stable | N | usable |  |
| 5 | zh | product→COMPARE | B | snapshot_bound | N | partial | firmware,hw_version;近似重复:{#005,#017} |
| 6 | zh | support→TROUBLESHOOT | A | stable | N | usable |  |
| 7 | zh | support→TROUBLESHOOT | A | stable | N | usable | ;近似重复:{#007,#008} |
| 8 | zh | product→TROUBLESHOOT | C | stable | N | partial | ;近似重复:{#007,#008};两问需拆 |
| 9 | zh | support→TROUBLESHOOT | A | stable | N | usable |  |
| 10 | zh | support→HOW_TO | A | stable | N | usable |  |
| 11 | zh | product→RECOMMEND | C | contextual | N | partial | customer_session |
| 12 | zh | support→SOLUTION | B | snapshot_bound | N | usable |  |
| 13 | zh | support→TROUBLESHOOT | B | snapshot_bound | N | partial | security_sensitive;默认密码出现在期望答案,冻结前需安全评审 |
| 14 | zh | product→RECOMMEND | C | snapshot_bound | Y | stale | released_vs_planned;不确定性核心案例:无火灾预训练模型 |
| 15 | zh | product→RECOMMEND | C | snapshot_bound | N | stale | customer_session;演示视频会话语境剥离 |
| 16 | zh | product→FACTUAL | D | contextual | N | broken | crm_workflow;expected=『邮件已发出等待测试』非答案 |
| 17 | zh | support→TROUBLESHOOT | B | snapshot_bound | N | partial | firmware;近似重复:{#005,#017} |
| 18 | zh | product→RECOMMEND | B | snapshot_bound | Y | usable | uncertainty_core;不确定性:仅Morse网关实测,其他为理论兼容 |
| 19 | zh | product→RECOMMEND | C | contextual | Y | partial | moq,commercial;MOQ事实源内未决 |
| 20 | zh | product→RECOMMEND | C | contextual | N | stale | sales_pitch;LinkedIn推销语境 |
| 21 | zh | product→FACTUAL | A | stable | N | usable | ;家族:{#021,#056,#089}(PIR) |
| 22 | zh | support→HOW_TO | B | snapshot_bound | N | usable | releases |
| 23 | zh | product→SOLUTION | A | stable | N | usable |  |
| 24 | zh | support→TROUBLESHOOT | A | stable | N | usable |  |
| 25 | zh | product→RECOMMEND | B | snapshot_bound | N | partial | moq,commercial;跨源重复:{#025,#106} |
| 26 | zh | commercial→COMMERCIAL | B | snapshot_bound | N | partial | price,certification,lead_time;定价与#112($69)矛盾,需快照裁决 |
| 27 | zh | product→FACTUAL | A | stable | N | usable |  |
| 28 | zh | support→TROUBLESHOOT | A | stable | N | usable |  |
| 29 | zh | support→TROUBLESHOOT | C | contextual | N | partial | device_sn_specific;SN/设备专属;方法论可迁移 |
| 30 | zh | commercial→COMMERCIAL | C | contextual | N | stale | internal_strategy,price;内部销售策略非答案 |
| 31 | zh | product→CLARIFY | C | contextual | Y | stale | clarify_core;需求模糊引导=CLARIFY基准种子 |
| 32 | zh | support→FACTUAL | A | stable | N | usable |  |
| 33 | zh | product→RECOMMEND | C | contextual | N | stale | moq,customization;定制MOQ/费用未决 |
| 34 | zh | product→SOLUTION | B | snapshot_bound | N | usable | software_availability,model |
| 35 | zh | product→ORIENT | C | snapshot_bound | N | stale | orientation;内部销售话术需重写为能力澄清 |
| 36 | zh | product→RECOMMEND | B | snapshot_bound | N | usable | module_lineup |
| 37 | zh | product→FACTUAL | A | stable | N | usable |  |
| 38 | zh | product→FACTUAL | A | stable | N | usable |  |
| 39 | zh | product→RECOMMEND | B | snapshot_bound | N | usable | product_config |
| 40 | zh | product→SOLUTION | B | snapshot_bound | N | usable | snapshot_demo |
| 41 | zh | product→FACTUAL | B | snapshot_bound | N | usable | specs |
| 42 | zh | product→FACTUAL | A | stable | N | usable |  |
| 43 | zh | product→FACTUAL | A | stable | Y | usable | uncertainty_core;BMeters兼容为推断非实测 |
| 44 | zh | support→SOLUTION | B | snapshot_bound | N | usable |  |
| 45 | zh | support→TROUBLESHOOT | C | contextual | N | partial | multi_part;三问混合,电池已耗尽无法取日志 |
| 46 | zh | product→FACTUAL | B | snapshot_bound | N | usable | privacy |
| 47 | zh | product→SOLUTION | B | snapshot_bound | N | usable | model_capacity |
| 48 | zh | product→RECOMMEND | B | snapshot_bound | N | usable | released_vs_planned |
| 49 | zh | product→RECOMMEND | C | contextual | N | stale | customer_session;会约语境 |
| 50 | zh | product→FACTUAL | B | snapshot_bound | N | partial | released_vs_planned;未发布样品,能力以快照为准 |
| 51 | zh | commercial→COMPARE | B | snapshot_bound | N | usable | model_lineup,certification |
| 52 | zh | commercial→COMMERCIAL | D | contextual | N | wrong_task | internal_pricing_review;内部报价审核非知识 |
| 53 | zh | product→TROUBLESHOOT | A | stable | N | usable | third_party_module |
| 54 | zh | support→RECOMMEND | C | contextual | N | partial | scenario_dependent;三场景决策树=推荐标记契约 |
| 55 | zh | product→FACTUAL | B | snapshot_bound | N | usable | model_lineup |
| 56 | zh | support→FACTUAL | A | stable | N | usable | ;家族:{#021,#056,#089};产品页vs实际差异注 |
| 57 | zh | support→TROUBLESHOOT | A | stable | N | usable |  |
| 58 | zh | product→RECOMMEND | A | stable | N | usable |  |
| 59 | zh | support→TROUBLESHOOT | A | stable | N | usable |  |
| 60 | zh | product→RECOMMEND | B | snapshot_bound | Y | usable | uncertainty_core;仅Morse实测;Blue Iris集成未测 |
| 61 | zh | product→FACTUAL | B | snapshot_bound | N | usable | board_lineup |
| 62 | zh | product→COMMERCIAL | D | contextual | N | broken | crm_workflow;expected=『等待确认会议』非答案 |
| 63 | zh | support→TROUBLESHOOT | C | contextual | N | partial | device_sn_specific;SN专属实测数据 |
| 64 | zh | product→RECOMMEND | B | snapshot_bound | N | usable | license,product_config |
| 65 | zh | product→RECOMMEND | C | contextual | N | partial | customer_session;照片专属分析 |
| 66 | zh | support→TROUBLESHOOT | D | contextual | N | broken | no_answer_recorded;expected=『等待客户回复』=空答案 |
| 67 | zh | support→TROUBLESHOOT | A | stable | N | usable |  |
| 68 | zh | support→TROUBLESHOOT | D | contextual | N | broken | no_answer_recorded;expected=『等待测试反馈』=空答案 |
| 69 | zh | support→TROUBLESHOOT | A | stable | N | usable |  |
| 70 | zh | product→COMPARE | C | snapshot_bound | N | partial | multi_part_umbrella;8问伞形需拆解;跨源重复:{#070,#088,#097} |
| 71 | zh | product→COMMERCIAL | D | contextual | N | wrong_task | internal_commercial_scope;内部报价 posture;边界事实(Option2不含ESP32C3)可留档 |
| 72 | zh | commercial→FACTUAL | A | stable | N | usable |  |
| 73 | zh | product→FACTUAL | B | snapshot_bound | N | usable | contradiction_customer_vs_datasheet;客户认知与官网/datasheet矛盾=优质对比点 |
| 74 | zh | product→RECOMMEND | C | contextual | N | stale | customization,commercial;定制可行性表;商业排期语境 |
| 75 | zh | product→RECOMMEND | B | snapshot_bound | N | usable | model_lineup |
| 76 | zh | support→TROUBLESHOOT | A | stable | N | usable |  |
| 77 | zh | commercial→FACTUAL | B | snapshot_bound | N | usable | released_vs_planned |
| 78 | zh | product→FACTUAL | C | snapshot_bound | N | stale | misconception_correction;误解纠正=优质FACTUAL种子 |
| 79 | zh | support→HOW_TO | A | stable | N | usable | ;隔离对照:{#079(NE301可)vs #081(NE101不可)} |
| 80 | zh | support→TROUBLESHOOT | B | snapshot_bound | N | usable | firmware,hw_version |
| 81 | zh | product→FACTUAL | A | stable | N | usable | ;隔离对照:{#081 vs #079} |
| 82 | zh | support→TROUBLESHOOT | B | snapshot_bound | N | usable | firmware;跨源重复:{#082,#096} |
| 83 | zh | support→TROUBLESHOOT | C | contextual | N | partial | customer_session;会话日志专属 |
| 84 | zh | product→RECOMMEND | B | snapshot_bound | N | partial | hw_limits |
| 85 | zh | support→TROUBLESHOOT | A | stable | N | usable |  |
| 86 | zh | support→HOW_TO | B | snapshot_bound | N | usable | toolchain_version |
| 87 | zh | support→TROUBLESHOOT | A | stable | N | usable |  |
| 88 | zh | commercial→COMMERCIAL | D | contextual | N | wrong_task | nre_quote;NRE/BOM内部报价;跨源重复:{#070,#088,#097} |
| 89 | zh | support→FACTUAL | A | stable | N | usable | ;家族:{#021,#056,#089} |
| 90 | zh | support→SOLUTION | C | snapshot_bound | N | partial | multi_part_umbrella;12问伞形需拆解 |
| 91 | zh | product→FACTUAL | C | stable | Y | stale | uncertainty_core,medical_boundary;医疗筛查边界=不确定性核心案例 |
| 92 | zh | support→TROUBLESHOOT | A | stable | N | usable |  |
| 93 | zh | commercial→RECOMMEND | C | snapshot_bound | N | stale | halow_region,commercial |
| 94 | zh | product→RECOMMEND | D | contextual | N | wrong_task | crm_account_record;销售侧客户档案;家族:{#094,#066} |
| 95 | zh | product→RECOMMEND | D | contextual | N | wrong_task | crm_account_record;销售侧跟进日志表 |
| 96 | zh | product→TROUBLESHOOT | D | contextual | N | wrong_task | crm_account_record;跨源重复:{#082,#096} |
| 97 | zh | product→RECOMMEND | D | contextual | N | wrong_task | crm_account_record;跨源重复:{#070,#088,#097} |
| 98 | en | product→RECOMMEND | D | contextual | N | wrong_task | crm_account_record;en;销售侧客户档案 |
| 99 | zh | product→RECOMMEND | D | contextual | N | wrong_task | crm_account_record;销售侧客户档案 |
| 100 | zh | product→RECOMMEND | D | contextual | N | wrong_task | crm_account_record;销售侧客户档案 |
| 101 | zh | product→RECOMMEND | C | snapshot_bound | N | stale | bacnet_boundary;模板化问句;边界事实有价值(无原生BACnet) |
| 102 | en | commercial→RECOMMEND | D | contextual | N | wrong_task | crm_account_record;en;销售侧客户记录 |
| 103 | zh | product→RECOMMEND | C | snapshot_bound | N | stale | platform_integration;模板化问句;EarthRanger/Gundi事实 |
| 104 | zh | product→RECOMMEND | C | snapshot_bound | Y | stale | uncertainty_core,shutter_boundary;模板化问句;滚动vs全局快门边界+需确认客户栈 |
| 105 | zh | product→RECOMMEND | C | contextual | N | stale | ;模板化问句 |
| 106 | zh | product→RECOMMEND | D | snapshot_bound | N | wrong_task | crm_account_record;跨源重复:{#025,#106}(显式互链) |
| 107 | zh | product→RECOMMEND | D | contextual | N | wrong_task | internal_meeting_prep;内部会议准备meta问题 |
| 108 | zh | product→RECOMMEND | C | snapshot_bound | N | stale | ;模板化问句 |
| 109 | zh | product→RECOMMEND | C | snapshot_bound | N | stale | baa_taa_boundary;模板化问句;BAA/TAA边界有价值 |
| 110 | en | product→RECOMMEND | D | contextual | N | wrong_task | crm_account_record;en;销售侧客户档案 |
| 111 | zh | product→RECOMMEND | D | contextual | N | wrong_task | crm_account_record;销售侧客户档案 |
| 112 | zh | product→COMMERCIAL | D | contextual | N | wrong_task | crm_account_record,price;报价事实($69)与#026($59)矛盾;销售侧档案 |
| 113 | en | off_topic→OFF_TOPIC | A | stable | N | usable | seed;seed题库;拒答契约 |
| 114 | en | off_topic→OFF_TOPIC | A | stable | N | usable | seed;seed题库 |
| 115 | en | off_topic→OFF_TOPIC | A | stable | N | usable | seed;seed题库 |
| 116 | zh | off_topic→OFF_TOPIC | A | stable | N | usable | seed;中文拒答话术 |
| 117 | en | off_topic→OFF_TOPIC | A | stable | N | usable | seed,security_sensitive;prompt injection防护契约 |

> 完整字段(题目原文/期望答案状态/标记契约候选/复核要求)见机读工件 `benchmark_v1/migration_inventory_117.json`(117 条,含 corpus provenance)。

## 10. 迁移后推荐活跃历史基准集(不冻结 v1)

- **推荐活跃集 = A+B+C = 97 题**(A 35 直接可用;B 32 复核后可用;C 30 重写后可用)——前提是完成 62 项事实复核与 30 项标记契约重写。
- 轻量先行子集:**A+B = 67 题**(B 完成复核即可进入)。
- 剔除 20 题 D(销售档案 14、内部商务/报价/会议 4、空答案 2);其中 #014/#030/#035/#052/#071/#088/#104 等 D/C 的**底层事实已被其他活跃案例或源文件覆盖**,无覆盖损失。
- 对照 Issue #32 覆盖契约的缺口(需新案例填充,历史语料不提供):FOLLOW_UP(0)、证据不足型 ABSTAIN(0)、COMPARE 仅 3、英文 A/B/C=0、不确定性仅 8(目标 ≈15–20%)。
- 强烈建议纳入的既有生产回归家族(与历史语料合并成 v1):产品隔离/对比正确性(tests/pipeline/test_issue19_comparison.py、test_product_boundary_*、test_product_resolver.py 已有契约)+ 种子 #26–#31。

## 11. 冻结 v1 前仍需的证据

1. B 组 32 题逐题对**版本化源快照**复核(尤其 price/certification/firmware/NE503 未发布能力);
2. 30 题 C 组标记契约重写(每题产出 required/prohibited facts,不写散文金标);
3. #026 vs #112 定价矛盾由 Store/官方快照裁决;#013 默认凭据事实的安全评审;
4. 不确定性案例补齐至 15–20%(生产真实问句优先,候选源:生产对话/支持未决案例);
5. 英文表征案例构造(优先把高价值中文 A 题做英文等价,而非直译);
6. FOLLOW_UP/ABSTAIN/COMPARE 家族补充(生产种子 #26–#31 已给 5 例);
7. 语料快照与知识源快照的版本化机制冻结(原则 8)——需先落 #30 观测底座判断证据可达性。

## 12. 边界声明

本 Discovery 未修改:历史语料文件、Knowledge 源内容、ask-ai 生产代码、任何运行时意图/检索/提示词;未调用生产 /api/ask;未触发同步/重索引。机读工件与报告均落 ask-ai docs(仅本地),未提交 main。