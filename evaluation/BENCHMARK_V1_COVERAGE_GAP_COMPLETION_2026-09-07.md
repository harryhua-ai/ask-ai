# ASK-AI Answer Intelligence Benchmark v1 — Coverage Gap Completion Discovery

> **性质**:DISCOVERY / EVALUATION DESIGN ONLY · READ ONLY(GitHub Issue #32;无生产/知识源/Answer Engine 变更)
> **日期**:2026-09-07 · **执行**:Executor · **状态**:COVERAGE_GAP_COMPLETION **PASS**(自评,待 Planner FINAL REVIEW)
> **工件**:`docs/evaluation/benchmark_v1/coverage_gap_additions_2026-09-07.json`(候选清单+BEFORE/AFTER 矩阵,机器可读)
> **范围澄清**:#013 与 #026 为 migration_state **B**,不属于 C30 选择集;本 Gate 不扩选、不重释。

---

## 1. 结论一句话

97 个历史活跃案例之外,以**规定的真实证据获取顺序**盘点出 **23 个真实候选 + 1 条 adapted 合成候选**(共 24,无数量目标),拟将活跃池扩至 **121**;8 个生产回归家族全部显式映射;EN 知识载案 **0 → 18**;不确定性七分类全部获得真实载体;0 DUPLICATE / 0 NEAR_DUPLICATE 入选。**不冻结 Benchmark v1。**

## 2. 真实证据获取顺序执行记录

| 序 | 源 | 产出 |
|---|---|---|
| 1 | 生产回归 evidence(8 个 issue 全文) | #26/#27/#23/#28/#29 含**逐字生产问句**;#5/#19/#31 家族证据 |
| 2 | 历史评测材料(optimize/results/ 6 快照) | 题库=同一 117 → 无新问句家族,**视为穷尽**;旧评测器语义(「有据率=[n] 引用比例」、117/117 满分)记录为假通过防御证据 |
| 3 | TS_record/support(247 行索引+全目录) | **175 个未入库真实案例文件**(NFC 规范化 diff;首轮 NFD 假阳性已修正——sq-004/005/006/009/038/080/081/082 实为已入库),逐案筛选 |
| 4 | sales 知识 | 问句型销售记录已被 117 收割;其余为 CRM 档案/冷开发 → 排除 |
| 5 | 权威源真实会话语料 | 生产 widget 真实会话仅经 issue 留痕(#26/#27);生产对话库不可本机只读导出 → 记为剩余缺口 |
| 6 | 其他已验证真实问句 | wiki 快照只读复核(2026-09-07 浅克隆 @4ed5b32e):**NE302 全系列文档存在**、**NeoRuntime 于 NE503 文档在载**(neoruntime-apps/sdks/OpenAPI) |
| 7 | 合成(仅剩余缺口) | 仅 1 条 adapted(cg-s01 ORIENT×EN),附 `reason_real_case_unavailable` |

## 3. 计数

| 项 | 值 |
|---|---|
| REAL / SYNTHETIC / 总新增 | **23 / 1 / 24** |
| 拟活跃池 | 97 → **121** |
| recommended_for_v1 | 24/24 |
| 关系分布 | NEW_COVERAGE 12 · COMPLEMENTARY_CONTRAST 5 · USEFUL_VARIANT 6 · DUPLICATE/NEAR_DUPLICATE 入选 **0** |
| 多角色证据需求(≥3 roles) | 新增 21/24 |
| EN 知识载案 | **0 → 18**(全部源自英文客户邮件/会话存档;cg-r01 为生产上下文推定语言,冻结时核对;无中文题翻译充数) |
| 不确定性案 | **8 → 25**(七分类全有真实载体;**CONTRADICTORY_EVIDENCE 首获真实实例 cg-r22**;PLANNED=r14/r15/r18) |

## 4. BEFORE → AFTER 覆盖矩阵(摘要;全量见工件)

| 维度 | BEFORE(97) | AFTER(拟 121) |
|---|---|---|
| 交互类 | RECOMMEND 27 · TROUBLESHOOT 23 · FACTUAL 21 · SOLUTION 9 · HOW_TO 5 · OFF_TOPIC 5(种子) · COMPARE 3 · COMMERCIAL 2 · CLARIFY 1 · ORIENT 1 · FOLLOW_UP **0** | RECOMMEND 30 · TROUBLESHOOT 28 · FACTUAL 24 · SOLUTION 12 · HOW_TO 7 · OFF_TOPIC 5 · COMPARE **6** · COMMERCIAL 3 · CLARIFY **2** · ORIENT **3** · FOLLOW_UP **1** |
| 语言 | zh 93 / en 4(全为种子) | zh 93 / en 4+18(真实知识载案)/ vi 1 / ja 1 |
| 产品/主题 | NE301 44 · NE101 34 · NE503 7 · NG4500 6 · NE300-MB01 1 · 种子 5 | 新增主题:**NE302 产品线、NeoRuntime 运行时、NeoMind 服务器软件、ne301-model-converter 开源工具链、竞品(Milesight X1)、第三方 VMS 生态(Frigate/DeepStream)、车载外设集成** |
| 已载/无载真值 | uncertainty_required 8 + GT INSUFFICIENT 2 + 边界标志簇 | +17 条中心不确定性语义候选(见 §7) |
| 单源 vs 多角色 | 仅 C30 已表征(28/30 多角色);A/B 待 B 轨 | 新增 21/24 多角色;深化 CASE_STUDY/COMPARISON_TARGET_A·B/CALCULATOR/STORE |
| 产品隔离 | 无专门隔离案(分散于 scope_safety 维度) | NE302 独立系列、NE503 逐能力盘点、竞品边界、量化升级推荐、HDR 对照对、检测/识别之辨 |
| 对比行为 | 3 | 6(多目标/第三方生态/竞品 三分) |
| 推荐/方案 | 27 / 9 | 30 / 12(+Solutions·Case·规模化 TCO 组合) |
| 商业快照 | 2(+标志簇) | 3(#28 变体/逐组合价+Store 快照绑定) |
| 澄清 | 1 | 2(域内欠指定 + 需求模糊 双形态) |
| 导向 | 1 | 3(ZH+EN 路由对等) |
| FOLLOW_UP | 0 | 1(真实前序上下文依赖案 cg-r23) |
| 显式 off-topic | 5(全为注入种子) | 不变 → **剩余缺口**(真实留痕缺失) |

不做均匀数字分布优化;语义盲区判定见 §9。

## 5. 生产回归映射(8/8 全覆盖;一家族可映射多案)

| 家族 | 映射 |
|---|---|
| **#5** 精确产品隔离 | 既有:sq-081(NE101 远程抓拍 vs NE301 指令接口=反向兄弟陷阱)·sq-080(hw/fw 错配)·sq-005(v1/v1.2 PIR 缺位)·sq-009(板卡产品);新增:cg-r01(NE302 独立系列)·cg-r12(NE503 逐能力盘点)·cg-r16(竞品边界)·cg-r10(量化升级推荐)·cg-r21(检测/识别之辨) |
| **#19** 显式对比/多目标 | cg-r01(NE302 vs NE301;多目标证据范围+真实对比不足路径) |
| **#23** 性能案例 | **cg-r02「NeoRuntime 如何安装部署?」原问句纳入**;29,747ms/TTFT 18,111ms 仅作 provenance,**不冻结 TTFT/E2E 阈值**;NeoRuntime 为 wiki 在载的 NE503 运行时平台(neoruntime-apps/sdks/OpenAPI),安装真值可复现 |
| **#26** 域内欠指定 | cg-r03「What is included in the box?」(逐字生产问句;澄清/上下文解析,不塌缩 off-topic) |
| **#27** 能力导向 | cg-r04「你会干什么」(真实)+cg-s01「What can you do?」(adapted,EN 对等);与 #26 不合并 |
| **#28** 变体/价格 | cg-r05(逐字问句;变体维度+区间快照+逐组合价有界)+既有 sq-005/sq-080 版本变体 |
| **#29** 电池/计算器 | cg-r06(逐字问句;Battery Life Calculator 结构化证据)+cg-r10(像素预算计算) |
| **#31** 方案组合 | cg-r07(BoschIndia:6 仓/1000 路,Solutions+Case+Wiki 组合,TCO)+既有 sq-101(OCR+BACnet 路径已覆盖) |

## 6. EN 覆盖映射

- BEFORE:活跃池 EN 知识载案 = **0**(4 个 EN 全为 off_topic 种子)。
- AFTER:+18(cg-r01/03/07/08/09/10/11/12/13/14/16/17/18/19/21/22/23 + cg-s01),全部为英文客户往来存档或生产英文问句;cg-r20=vi、cg-r15=ja(非 EN 但增语言多样性)。
- **不翻译充数声明**:无任何中文题翻译冒充真实 EN 案;唯一 adapted(cg-s01)显式 `synthetic=true` + 理由(#27 的 EN 实例无留痕会话)。
- 既有已入库案(sq-081/sq-082 等)的真实英文原文将随冻结源快照恢复,但其语料问句仍为中文规范化形态——这一「语料语言≠客户语言」现象已记录,冻结时由 Planner 决定是否回填英文原问。

## 7. 不确定性语义映射(不设配额;15–20% 仅为方法论参考)

七分类全部获得真实载体:

| 语义 | 真实载体(新增) |
|---|---|
| NOT_SUPPORTED | cg-r14(hostname 缺陷)·cg-r18(config 无强制超时)·cg-r20(第三方 RTSP 抓帧)·cg-r21(本地人脸识别不存在;检测≠识别)·cg-r08(无自动 failover)·cg-r09(NE301 无 HDR) |
| NOT_DOCUMENTED | cg-r09(镜头畸变无标定)·cg-r11(第三方栈外部事实)·cg-r15(PyPI/sdist 未上线)·cg-r16(竞品能力以核查快照为准)·cg-r12(无预置异常检测应用) |
| NOT_TESTED | cg-r23(失败点推断未经客户环境验证)·cg-r08(client cert/retry 待验证) |
| PLANNED | cg-r14/cg-r18(修复上报工程,不承诺时点)·cg-r15(roadmap 项) |
| CONDITIONALLY_SUPPORTED | cg-r05(逐组合价依赖 Store 交互)·cg-r07(方案依赖确认项)·cg-r10(像素预算) |
| CONTRADICTORY_EVIDENCE | **cg-r22(文档 3.11/3.12 vs Dockerfile 3.10——首个真实实例)** |
| UNKNOWN/INSUFFICIENT | cg-r17(新固件可用性随版本变化) |

## 8. 去重与拒绝审计

- **方法**:候选 vs 97 池逐案语义对比;文件级 diff 以 Unicode NFC 规范化执行(修正了 macOS NFD 造成的假阳性——sq-004/005/006/009/038/080/081/082 曾被误判未入库)。
- **入选**:DUPLICATE=0,NEAR_DUPLICATE=0(USEFUL_VARIANT 6 条均带不重复的行为语义:25 问伞形 EN 形态、CEREG denied/timeout 反差对、HDR 对照对等)。
- **拒绝**(完整清单见工件 §rejected_candidates,要点):MuditaCARE(隐藏 CRM 画像)·Sauter-2026-07 支持版(sq-101 近重复,冻结时作其源快照)·抄表 OCR 簇 8 案(近重复)·PIR 簇 4 案·询价簇 3 案·伞形冗余 3 案·内部分析/会议准备/开发信/CRM 档案 ~100 案(非用户问句)·OV5640-ESP32S3+OS04C10 寄存器级(超 v1 核心行为面,范围边界留 Planner)。

## 9. 新增后仍存在的实质缺口

1. **真实 OFF_TOPIC utterance 留痕缺失**(现 5 案全为种子;需授权的生产会话导出)。
2. **多轮有状态对话链**(现有 FOLLOW_UP 仅单级前序依赖;生产存在真实多轮排障会话未导出)。
3. **CASE_BOUNDARY_ATTRIBUTION 评测家族**(新发现,上报):E03 跨客户误诊/F03·C10 案例嫁接/E01·D05 PII 泄漏(基线实证的真实行为族)。作为公平评测案需「内部案例语料在场+相似症状提问者」的受控构造,属评测设计决策,本 Gate 不构造,请 Planner 裁决是否单列。
4. **sq-108 T4 ↔ cg-r12 真值调和**:cg-r12 证据(wiki/商店预置 LPR 应用)与 sq-108 契约 T4(官方无预装 ALPR 应用记载)存在张力——不静默修改已验收工件,请 Planner 于快照核对后裁决 sq-108 措辞。
5. #013 安全契约(B 轨,上 Gate 已升级);EN 覆盖仍为少数(持续按获取顺序补真实,不设配额);第三方/竞品证据快照管线(cg-r11/r16 冻结前置)。

## 10. 非目标合规

不改 Answer Engine/提示词/检索/重排/剪枝/运行时分类体系;不调用生产 /api/ask;不变更生产与 Knowledge;不生成基线分;不撰写目标架构;**不冻结 Benchmark v1**;不设任意总数目标与不确定性百分比配额;不实现 Issue #30。

---

**Deliverables**:`coverage_gap_additions_2026-09-07.json`(24 候选全字段+矩阵+映射+审计)· 本报告。
