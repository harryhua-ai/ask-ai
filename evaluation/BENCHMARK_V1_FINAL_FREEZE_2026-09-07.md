# ASK-AI Answer Intelligence Benchmark v1 — FINAL FREEZE REPORT

> **性质**:EVALUATION GOVERNANCE / ARTIFACT FREEZE(GitHub Issue #32;对运行时/生产/Knowledge 只读;Docs/evaluation 工件写入已授权)
> **日期**:BENCHMARK_AS_OF = **2026-09-07** · **执行**:Executor · **状态**:BENCHMARK_FREEZE **PASS**(自评,待 Planner FINAL REVIEW)
> **基线纪律**:**BASELINE_EXECUTED = NO**——本 Gate 未运行当前 ASK-AI、未调生产 /api/ask、未检视任何新基准输出;Freeze 先于测量。

---

## 1. 冻结结论

**ASK-AI Answer Intelligence Benchmark v1 已冻结**:121 案全部独立证明 Freeze-ready;7 份权威工件(可执行语料/冻结契约/证据清单/评测契约/评分聚合规范/匿名化映射/基准清单)已落盘并取 SHA-256;此后任何语义变更(案集/真值/契约/评分/致命失败语义/可执行问句)需新 Benchmark 版本或基线执行前显式修正案;基线执行开始后一律需新版本。

## 2. 案集与逐案 Freeze-Ready 证明

- **121/121 唯一 case_id**,零缺失/零重复/零未审新增(POOL CHECK)。
- 逐案十项核验(可执行问句存在/真值指针/证据可复现/契约完整/评分维度/不确定性语义/动态快照绑定/PII/凭据/无未决阻塞)全部通过 → **FREEZE_READY = 121 · NOT_FREEZE_READY = 0**。

## 3. A35 FREEZE_SNAPSHOT_VERIFY = PASS

30 个非种子 A 案逐一验证:源文件存在性 + SHA-256(16) 指纹 + 逐 claim 词元支持度(内容词元化)。

- **SUPPORTED 27** · **复核后支持 3** · **BEHAVIORAL_SEED_DEFINITIONAL 5** · **STALE 0**。
- 复核明细:sq-010/sq-087 的 T4 为已支持 claim 的紧凑转述(词元假阴性);**sq-085 触发 TRUTH_AMENDMENT_REQUIRED(已应用)**:代码级标识符(MODEL_PACKAGE_MAGIC 'N6M1'/stedgeai.mk 引文)未复现于固件仓锚 @07150b49(全仓 grep 零命中)→ 真值收敛为「stedgeai 编译+.bin 打包上传(Wiki §4.2+案例记录)/分区限制/切换激活」,OLD/NEW/REASON/UNCHANGED 全文见 `contracts_frozen_v1.json` sq-085.truth_amendment;非静默修复。

## 4. 动态事实重验证 = PASS

绑定 **BENCHMARK_V1_AS_OF = 2026-09-07**,证据清单逐族记录 snapshot_date + 重验时点:固件 releases 经 gh api 当日复核(v1.9(hw-v2.0) 2026-07-20 / v1.8(hw-v2.0) 2026-06-04 / v1.8(hw-v1.2) 2026-05-20);wiki 家族当日本地克隆复核(NE302 全系列/NeoRuntime/LPR 应用示例/HaLow/电池矩阵);Store/计算器页绑 2026-09-05/07 已接受静态快照(下次 Freeze 重验);竞品/第三方绑案例内存档日期。无时间无关断言。

## 5. 证据清单 = PASS

`evidence_manifest_v1.json`:11 个证据对象(EV-WIKI/EV-NE301/EV-LPC/EV-AITOOLSTACK/EV-NEORUNTIME/EV-KB-A35/EV-KB-NEW24/EV-STORE/EV-CALC/EV-COMPETITOR/EV-DOCS-CHAIN),含 authority/source_type/repository/commit_sha/blob(git hash)/sha256/snapshot_date/cases_using_evidence;关键 wiki 文件含 git blob hash;工件链 6 份 docs commit 全记录。

## 6. 隐私 / 凭据审计 = PASS

- **PRIVACY_AUDIT = PASS**:121 条可执行问句中 52 条完成数据最小化(个人名/客户组织/SN/站点代号→角色或 [已匿名];区域/行业/部署约束/第三方网关产品名等任务必要语境保留);残留标识扫描 = 0;映射仅存于 `anonymization_map_v1.json`(执行语料外)。
- **CREDENTIAL_AUDIT = PASS**:可执行语料字面凭据 **0** 出现(`hicamthink`/admin123/password 赋值全零);唯一命中为 sq-013 的脱敏占位符 `[默认凭据-已脱敏]`(fixture 语义,预期存在,非可复用凭据材料)。报告不打印任何凭据值。

## 7. 致命失败语义审计 = PASS

158 条 critical-fail 规则逐条分类:**VALID_OVERRIDE 158 · DOWNGRADE_TO_NORMAL_CRITERION 0**(无措辞/风格/可选细节类规则混入)。**CASES_WITH_VALID_CRITICAL_OVERRIDE = 121 · CASES_WITHOUT = 0**——此为审计结果(每案皆承载可捏造核心真值或专项交互测试点),非机械复制;评测时 CRITICAL_FAIL 独立单列,不改写维度分。

## 8. 语言出处规范化 = PASS

正交枚举(语言单列字段):**ORIGINAL_USER 1**(r07 BoschIndia 客户邮件原文)·**PRODUCTION_USER 5**(r03 EN 生产问句 + r02/r04/r05/r06 ZH 生产问句)·**ADAPTED 102**(92 ZH_CORPUS_NORMALIZED + 10 ADAPTED_ENGLISH)·**BEHAVIORAL_SEED 5** ·**SYNTHETIC 1**(cg-s01)·**UNVERIFIED 7**(r01/r11/r15/r19/r20/r21/r23)。原始证据描述串保留于每案 `language_provenance_evidence`。无重构/翻译冒充原始英文。

## 9. 评测契约与聚合 = PASS

`evaluator_contract_v1.json`(EVAL_V1):judge 输入/禁入、逐案判据(C30 专案定义+其余契约派生)、致命失败独立处理、引用支撑语义、七分类不确定性评分、缺答策略、n=3 重跑、人工校准(≥10%+全部 CRITICAL_FAIL+B/C 分歧)、judge 元数据记录;**不绑定供应商**。
`scoring_aggregation_spec_v1.json`(SCORE_V1):四组独立(HARD/EVIDENCE/EXPERIENCE/OPERATIONAL);A/B/C→2/1/0、PASS/FAIL→1/0 编码;组分权威、逐维分布必报;可选合成 COMPOSITE=0.5·HARD+0.3·EVIDENCE+0.2·EXPERIENCE(公式显式、分量同屏、OPERATIONAL 不入);**无任何性能阈值**(#23 计时仅 provenance)。

## 10. 已知局限(FUTURE_BENCHMARK_EXPANSION,不阻塞 v1)

真实生产 OFF_TOPIC 留痕 · CASE_BOUNDARY_ISOLATION 受控污染测试 · 更丰富多轮链 · 更多 ORIGINAL_USER 英文案 · cg-r11 第三方核验升级 · Store/计算器下次 Freeze 重验。

## 11. 工件与哈希

| 工件 | SHA-256 |
|---|---|
| executable_corpus_v1.json | `a1f920c0972d74cf8a6bbd4c46fc36e2b1bfaed0a5b3600f80e2a8ada4680f50` |
| contracts_frozen_v1.json | `5a436f053804f9cd1ac1252f9815fd6cdb655e3d938138e1fc2e56dfc28e9946` |
| evidence_manifest_v1.json | `d638685fc621b4d9be7811e193dbbb76e9cab8c6c1e8c578f833b673b1fa8a5b` |
| evaluator_contract_v1.json | `c5898b07f74b740ef3201d0b9460bcf6…`(全文见文件) |
| scoring_aggregation_spec_v1.json | `5afda9c2554a7ea9c714ba80455fcbc2…` |
| anonymization_map_v1.json | `28b7e31c0fd8ac6dae7f411ad82095c1…` |
| benchmark_manifest_v1.json | `d820d3d96062e709c9b4a21eafef5caac536cb94fb066cbf1b957fd67366d096` |
| case_set_hash(121 有序 id) | `8685e198cb6b41abbd3b3edef667c090435a8090323307f5a320df943f73283a` |

完整哈希与来源工件链见 `benchmark_manifest_v1.json`。

## 12. 非目标合规

未运行当前 ASK-AI / 未调生产 / 未改运行时·提示词·检索 / 未变更产与 Knowledge / 未实现 Issue #30 / 未建快照管线 / 冻结中未增删案例 / **不因当前 ASK-AI 表现调整任何基准语义**。

---

**Benchmark v1 语义自本 Gate 通过起不可变;基线比较以本清单哈希为准。**
