# ASK-AI Answer Intelligence Benchmark v1 — Ground Truth Revalidation(41 题)

> **性质**:DISCOVERY / EVALUATION ONLY · READ ONLY(parent:Issue #32;前置:Historical Corpus Migration Gate = FINAL PASS)
> **日期**:2026-09-05 · **状态**:PASS · **REV2 语义修正**:#026 统一 REFINED 口径(消除与 STALE=0 的叙述矛盾);#014 uncertainty_state=NO_OFFICIAL_PRETRAINED_MODEL_LISTED(仅证官方预训练目录无火灾模型,枚举扩展且局限已记录,不表述为『不支持火灾检测』);#013 解冻过早的 prohibited 规则→FINAL_PROHIBITED_ANSWER_CRITERIA=PENDING MARKING CONTRACT REVIEW,凭据值脱敏。聚合计数不变(UNCHANGED22/REFINED17/INSUFFICIENT2;STALE/INCORRECT/CONFLICTED=0;READY 40/1)。SOURCE_EVIDENCE_CHANGED = NO。
> **机读工件**:`docs/evaluation/benchmark_v1/ground_truth_revalidation_41.json`(41 条全字段)

## 1. 选题与证据锚点

选题 = 迁移工件( migration_inventory_117.json,REV1)中 `current_fact_revalidation_required=true` → **恰好 41**(B 32 + C 9:#003/#014/#045/#049/#074/#093/#103/#108/#109)。未因「有 source_file」而扩大集合。

**证据版本锚点(全部只读取证,取证日 2026-09-05)**:

| 锚点 | 标识 |
|---|---|
| 历史源快照 | Knowledge 仓 `d4f7f49b4de211bbaeb8db0501165ef1dc74b322`;语料文件 blob @ `874616d3`(2026-08-19) |
| 官方 wiki | camthink-ai/wiki-documents @ `4ed5b32e304ee09a5e067a464e16c990c6218314` |
| NE101 固件 | camthink-ai/lowpower_camera @ `07150b49`;tags:v1.9(hw-v2.0) 2026-07-20 / v1.8(hw-v2.0) 2026-06-04 / v1.8(hw-v1.2) 2026-05-20 |
| NE301 固件 | camthink-ai/ne301 @ `5611dbe14bf6d3275afc03374ea37aef71d203d5`(Model/weights、stedgeai.mk) |
| AIToolStack | camthink-ai/AIToolStack(backend/utils:dataset_import.py / ne301_export.py / yolo_export.py) |
| 官方 Store | camthink.ai/store/neoeyes-ne101(现价 **$69.00–$112.00** SKU 区间;配件价目在案) |

## 2. 价格冲突裁决(#026 vs #112)

- #026(2026-05):WiFi **$59** / Cat-1 **$109**(样品价);#112(2026-07):WiFi **$69** + 支架 ~$15、Cat-1 +$40。
- **现势权威证据(Store,2026-09-05)**:NE101 相机 **$69.00–$112.00**(按 Connectivity/Lens SKU 区间),直接在线售卖。
- **裁决**:#026 的 $59/$109 为 **2026-05 时限性样品/报价口径**(REFINED:历史真值日期绑定保留,不作为现价);#112 的 $69 与现行 Store 基价一致。**基准真值 = 一律绑定冻结时 Store 快照**,历史数字只作「历史报价」语境;历史与现势差异本身是优质 COMMERCIAL 测试点(历史价 ≠ 现价)。

## 3. 安全敏感(#013,REV2 语义修正)

- **TRUTH**:当前官方 NE301 wiki quick-start 仍记载默认凭据(**值在本报告/工件脱敏,不在此复述**)——事实 UNCHANGED 且权威。
- **SECURITY_REQUIREMENT**:安全处理与『必须修改默认凭据』的行为必须在基准中 addressed。
- **FINAL_PROHIBITED_ANSWER_CRITERIA**:**PENDING MARKING CONTRACT REVIEW**(允许/禁止的回答行为归属后续标记契约/安全政策评审,本真值工件不预设)。

## 4. 逐题真值裁决(41)

| # | 状态 | 真值稳定 | 不确定态 | 现势真值要点(历史→现势) | 证据 |
|---|---|---|---|---|---|
| 1 | REFINED | SNAPSHOT_BOUND | NONE | 转换能力在;历史脚本名已被 dataset_import/ne301_export/yolo_export 取代 | AIToolStack |
| 2 | REFINED | SNAPSHOT_BOUND | NONE | bug 修复为史实;导出路径重构 | AIToolStack |
| 3 | REFINED | SNAPSHOT_BOUND | NONE | AIToolStack 活跃;MQTT 配置细节绑冻结版文档 | AIToolStack |
| 5 | REFINED | SNAPSHOT_BOUND | NONE | 差异不变;固件按硬件分支:hw-v1.2 线最新=v1.8(hw-v1.2) | lowpower_camera tags |
| 12 | UNCHANGED | STABLE | NONE | SD 存储清单与 ne301 仓库一致 | ne301 |
| 13 | UNCHANGED | STABLE | NONE | 默认凭据仍为官方文档记载;安全处理要求见 §3 | wiki |
| 14 | UNCHANGED | SNAPSHOT_BOUND | NO_OFFICIAL_PRETRAINED_MODEL_LISTED | 官方预训练目录无火灾模型;自定义部署能力未证实(NOT_TESTED),不得表述为『不支持火灾检测』 | ne301 |
| 17 | UNCHANGED | SNAPSHOT_BOUND | NONE | releases 以 tag 提供预编译 | lowpower_camera |
| 18 | REFINED | CONTEXTUAL | NOT_TESTED | Morse HaLowLink 官方专篇确认;第三方网关=NOT_TESTED | wiki |
| 22 | UNCHANGED | SNAPSHOT_BOUND | NONE | 无 PlatformIO;esptool+releases 不变 | lowpower_camera |
| 25 | REFINED | SNAPSHOT_BOUND | NONE | 太阳能 10W+7AH 官方页在(路径更新);MOQ 仍 NOT_DOCUMENTED | wiki |
| 26 | REFINED | SNAPSHOT_BOUND | NOT_SUPPORTED | 价格裁决见 §2(历史样品报价日期绑定,不作现价);TELEC=未认证(2026-05 快照,冻结复核) | Store+Knowledge |
| 34 | UNCHANGED | SNAPSHOT_BOUND | NONE | YOLOv8n 预装+AI Tool Stack+无零售专用模型 | ne301+AIToolStack |
| 36 | REFINED | SNAPSHOT_BOUND | NONE | 选型逻辑不变;模块在产状态外部快照复核 | Knowledge |
| 39 | UNCHANGED | STABLE | NONE | IP67/供电匹配矩阵不变 | wiki |
| 40 | UNCHANGED | SNAPSHOT_BOUND | NONE | 近焦/远程触发/JSON 能力不变 | ne301 |
| 41 | UNCHANGED | SNAPSHOT_BOUND | NONE | NE301 规格不变 | wiki |
| 44 | UNCHANGED | STABLE | NONE | 开源+GPIO+HTTP/MQTT 不变 | ne301 |
| 45 | REFINED | SNAPSHOT_BOUND | NONE | 续航基线被现行 wiki 矩阵(电池×通信方式)替代 | wiki |
| 46 | UNCHANGED | STABLE | NONE | JSON/JPEG 耦合存储不变 | ne301 |
| 47 | UNCHANGED | SNAPSHOT_BOUND | NONE | INT8 档/类别容量/OTA 不变 | AIToolStack |
| 48 | REFINED | SNAPSHOT_BOUND | NONE | NE503 已公开发布(专页+wiki+Store);无电池边界确认 | wiki |
| 49 | REFINED | SNAPSHOT_BOUND | NONE | 20 TOPS/功耗官方确认;样品语境作废 | wiki |
| 50 | REFINED | SNAPSHOT_BOUND | NONE | 『未发布』作废;规格(IMX678/4K/变焦)官方确认 | wiki |
| 51 | UNCHANGED | SNAPSHOT_BOUND | NONE | NG4510 20/34、NG4521 100/157 原文一致 | wiki |
| 55 | UNCHANGED | SNAPSHOT_BOUND | NONE | YOLOv8n 预装确认 | ne301 |
| 60 | REFINED | CONTEXTUAL | NOT_TESTED | 同 #18;Blue Iris 集成仍未测 | wiki |
| 61 | REFINED | SNAPSHOT_BOUND | NONE | ACS-04 扩展板现 **9 传感器**(增毫米波雷达+MEMS 麦克风;NE101/NE301 双平台) | wiki |
| 64 | UNCHANGED | SNAPSHOT_BOUND | NONE | 推荐+开源 License 一致 | lowpower_camera |
| 73 | UNCHANGED | SNAPSHOT_BOUND | NONE | 4×AA/6.1μA 官方确认且更细(1 次/天≈13 年) | wiki |
| 75 | UNCHANGED | SNAPSHOT_BOUND | NONE | blazeface 权重现存 Model/weights | ne301 |
| 77 | UNCHANGED | SNAPSHOT_BOUND | NONE | IR 补光 80m 官方确认(白光预留) | wiki |
| 80 | UNCHANGED | SNAPSHOT_BOUND | NONE | GPIO3 版本对冲突诊断;SENSOR_POWER 机制现存 | lowpower_camera |
| 82 | REFINED | SNAPSHOT_BOUND | NONE | v1.8(hw-v1.2) 仍为该线最新(『最新』绑日期) | lowpower_camera |
| 84 | UNCHANGED | STABLE | NONE | 启动/无 IR/无 burst 硬件限制不变 | wiki+ne301 |
| 86 | UNCHANGED | SNAPSHOT_BOUND | NONE | stedgeai VARIANT=4.0 默认不变 | ne301 |
| 93 | REFINED | CONTEXTUAL | NOT_DOCUMENTED | HaLow=868/915 按区域;巴拉圭法规无第一方记载→有界表述 | wiki |
| 103 | INSUFFICIENT | UNKNOWN | NOT_DOCUMENTED | NE301 推荐有据;**Gundi/EarthRanger 集成无第一方证据** | Knowledge(仅销售记录) |
| 108 | UNCHANGED | SNAPSHOT_BOUND | NONE | NE503 Python/C++ SDK+aipc-cli 官方确认 | wiki |
| 109 | INSUFFICIENT | UNKNOWN | NOT_DOCUMENTED | 制造地/BAA-TAA 合规无第一方记载;只能考有界(不虚构)行为 | Store+Knowledge |

## 5. 汇总

- **current_truth_status**:UNCHANGED=22 · REFINED=17 · STALE=0 · INCORRECT=0 · INSUFFICIENT=2 · CONFLICTED=0
- **truth_stability**:SNAPSHOT_BOUND=30 · STABLE=6 · CONTEXTUAL=3 · UNKNOWN=2
- **uncertainty_state**:NONE=34 · NOT_SUPPORTED=2(#14 预训练火灾/#26 TELEC) · NOT_TESTED=2(#18/#60 第三方网关) · NOT_DOCUMENTED=3(#93 巴拉圭法规/#103 集成/#109 合规)
- **benchmark_truth_ready**:**YES=40 · NO=1**(#103)

## 6. 历史真值不得原样存续清单(Benchmark v1 必须按现势/有界改写)

#026 历史样品价不得作现价(REFINED,日期绑定) · #045 旧续航基线 · #050 『未发布』框架 · #061(注:不在 41 内,归迁移 C 修正) · #003/#001/#002 旧脚本名 · #103 集成正面事实 · #109 合规正面事实 · #082 『最新』需绑日期 · #005 『最新兼容 v1』需按硬件分支限定。

## 7. 快照绑定清单(冻结时必须记 version/date)

价格(Store 快照)· NE101 固件 tags · AIToolStack 脚本与文档版本 · NE503 规格/SDK 页 · NG45xx TOPS 表 · 续航矩阵 · ACS-04 传感器清单 · ne301 Model/weights · HaLow 区域频率表。

## 8. 未决阻塞

1. **#103**:Gundi/EarthRanger 集成缺第一方证据(需 Planner 取证,或定位为不确定性案例);
2. **#109**:制造地/BAA-TAA 合规无第一方记载(有界行为可先入基准,正面事实待官方证据);
3. **#026 TELEC**:认证状态绑 2026-05 快照,冻结时需复核认证库;
4. 其余 38 题无阻塞;全部 Store/wiki/仓库引用已可复现(锚点见 §1)。

## 9. 边界声明

未改运行时代码/提示词/检索/重排/意图/Product Resolver;未跑基准评分;未调用生产 /api/ask;未改生产与知识源内容;未写 30 题 C 组完整标记契约(仅 41 题真值与 A/C 简要标记要点);未冻结 Benchmark v1。docs/evaluation-only 提交。
