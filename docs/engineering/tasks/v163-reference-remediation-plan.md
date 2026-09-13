# V1.6.3 Reference Remediation Plan(拓扑 + 冻结合同 + 新终局验收规则 + 旧豁免 reconcile + 执行授权包;Planning 修订 2026-09-13:Role A 裁决冻结)

审计基线:branch `audit/v163-reference-traceability-20260913` @ 794fa55(审计对象 7e3e71c,谱系 34c7d5b→2f0bc06→8fa121a→7e3e71c tip;**7e3e71c 不再被授权发布,仅作审计对象**)。
权威参考:两 PNG(见主审计文档 §0)。权威分类:MATCH / IMPLEMENTATION DEFECT / PRODUCT-FUNCTIONAL GAP / USER-APPROVED DESIGN CHANGE / REFERENCE CONFLICT。
Planning 修订范围:仅本分支 docs/engineering/tasks/v163-reference-* 文档;零产品代码修改、零 merge、零 deploy、零关 issue。

---

## 1. 新终局验收规则(FINAL PASS 定义,冻结)

**FINAL PASS 当且仅当全部成立:**

1. 三门 PASS:Engineering(pytest 全量+vitest 全量+tsc+build+ruff)、Functional(真实 UI→API→DB 三角,写链真实执行)、Visual(逐矩阵 MATCH 行对照权威 PNG)。
2. IMPLEMENTATION DEFECT = 0(矩阵内 A 类全部闭合)。
3. PRODUCT-FUNCTIONAL GAP = 0(矩阵内 B 类全部交付;本批无新增待批项——全部 38 行方向已获 Role A 授权冻结)。
4. UNRESOLVED REFERENCE CONFLICT = 0 —— **已达成(SH-16 经 U-1 解决:LIGHT=权威方向,SH-16 → MATCH)**。
5. USER-APPROVED DESIGN CHANGE 逐条有明确决定记录;当前有效 UADC 共 4 条(UADC-1/2/3 既有 User 决定 + UADC-4 帮助中心推迟,Role A U-3 冻结)。
6. 截图不能独立证明功能 MATCH:功能控件以真实 UI→API→持久化三角验证;代码不能独立证明运行时 MATCH:以真实运行栈复核。
7. 验收数据仅限本地 docker PG(AUDIT-FIXTURE 标记隔离,SQL 全文记录);禁止触碰生产。

任何偏离 = 对应矩阵行保持 FAIL;V1.6.3 CONFORMANCE = FAIL。

## 2. 当前状态结论(Planning 修订后)

V1.6.3 CONFORMANCE = **FAIL**:IMPLEMENTATION DEFECT 4、PRODUCT-FUNCTIONAL GAP 38 行(17 族)。全部产品裁决(U-1..U-19)已冻结、REFERENCE CONFLICT 已清零(0),产品决策阻塞解除;剩余 FAIL 完全由**实现+运行时验收未完成**构成。7e3e71c 不满足 FINAL PASS,不得发布。

## 3. 执行拓扑(精炼版,基于冻结语义重评 Track A–F)

### 3.0 冻结接口先行(IF,Wave 0)

跨轨共享接口在实现启动前以合同附录形式冻结(IF 冻结属 planning/合同层,零代码):

| IF | 内容 | 冻结责任 | 消费方 |
|---|---|---|---|
| IF-1 | `question_clusters.status` 词表(open/observing/resolved)+观察元数据+流转事件形状 | Track E | D/F、投影、前端状态词表 |
| IF-2 | 缺口原因分类词表 v2(6 新类+证据规则 ID 清单) | Track D | GAP-B1-2、TI-09/31/40、E(观察核验依赖分类稳定) |
| IF-3 | 修复命令请求/响应+审计事件形状(RBAC/幂等键/验证结果) | Track C | DS-P2/P3 前端、#55 |
| IF-4 | 知识设置策略模型(资格角色/新鲜度)+mutation-preview 请求/响应形状 | Track C | DS-P6/P7 |
| IF-5 | 导出 CSV 列集+隐私字段排除清单+审计行形状 | Track E | TI-34/35/45 |
| IF-6 | 共享文件拆分地图(见 3.2;推荐而非强制 HOW) | Integration 轨 | D/E/F |

### 3.1 拓扑与依赖

```
Wave 0(合同/接口冻结,零代码):IF-1..IF-6 + 共享文件拆分地图冻结
Wave 1(全并行;各轨独立分支+合同,文件互斥由 IF-6 拆分保证):
  Track A(chrome:DEF-A1 + U-2 顶栏范围 + U-4 收起)   ── 零后端
  Track B(编辑抽屉 DEF-A2/A3/A4,U-5 冻结)            ── 零后端
  Track C(B1 修复/品牌/内容类型/计数/调度/知识设置/预览)── data_sources.py+新模块,与他轨文件互斥
  Track D(原因分类学 U-14)                            ── tech 拆分后独立子模块
  Track E(观察状态机 U-15 + 导出 U-16)                ── tech 拆分后独立子模块
  Track F(用户聚合 U-17/归因 U-18/主题 U-19)          ── tech 拆分后独立子模块
Wave 2(integration 轨,第七轨):
  backend 合并序:D→E→F(若 IF-6 拆分到位则可任意序,冲突面趋零)
  frontend 合并序:D→E→F→C→B→A(Analytics.tsx 面板文件互斥)
  统一跑三门+全矩阵 152 行复核+FINAL PASS 判定
```

### 3.2 共享文件争用解决(D/E/F 在 Analytics.tsx、tech.py、answer-gap 投影/状态/词表)

冻结语义下 D/E/F 争用点与推荐解法(**推荐而非强制 HOW**;若不拆,则按 D→E→F 合并序+integration 仲裁):

1. **`admin/src/pages/Analytics.tsx`(1416 行)按 tab/面板拆组件文件**:工具栏(status/cause filter=D、观察态 filter=E)、队列行(theme chips=D、观察中徽章=E、主题列=F、用户/源卡 meta=F)、诊断侧板(结论=D、CTA/内容补充/历史=E、meta 三计数=F)、导出卡=E。拆分后 D/E/F 各自只改自己面板文件;拆分本身归 Wave 0/Integration prep(一个独立前置提交,零语义变更)。
2. **`backend/api/admin/tech.py`(765 行)拆 router 子模块**:`tech_answer_gaps.py`(投影/过滤,q/status/cause/window 参数;D 词表挂载点)、`tech_observation.py`(观察命令/转移任务/流转事件投影;E)、`tech_export.py`(CSV 流式+审计;E)、`tech_evidence.py`(用户聚合/归因/topic;F)。状态词表 IF-1、分类词表 IF-2 分别由 E/D 在各自子模块内实现,投影层只消费词表常量。
3. **answer-gap 投影/状态/词表**:状态常量(`question_clusters.status` 词表)与原因词表各自独立常量模块(如 `backend/services/gap_taxonomy.py`、`gap_status.py`),D/E 各自拥有,投影/前端引用同一常量——禁止各轨复制词表字面量。
4. **导出**:独立模块(E 独有),无争用。

### 3.3 Track 表(精炼)

| Track | 范围(冻结决定) | 前端主要文件 | 后端主要文件 | 文件冲突 | 前置 |
|---|---|---|---|---|---|
| **A 共享 chrome** | DEF-A1;U-2(SH-09);U-4(SH-12);UADC-4 记录 | Sidebar.tsx、Layout.tsx(+顶栏范围控件) | 无(零后端语义,U-4 冻结) | 无 | IF 无;可立即 |
| **B 编辑抽屉** | DEF-A2/A3/A4(U-5 冻结) | SourceEditorDrawer.tsx | 无 | 无 | 无;可立即 |
| **C B1 产品域** | U-6/7/8/9/10/11/12/13(38 行中 22 行) | DataSourceDetail.tsx、新 KnowledgeSettingsDrawer、新 RiskPreviewModal、SourceEditorDrawer 入口 | data_sources.py、新 knowledge_settings/repair/preview 端点、连接器 content_type | DataSourceDetail.tsx(仅本轨);data_sources.py(仅本轨) | IF-3/IF-4 冻结;可立即 |
| **D 原因分类学** | U-14(TI-09、DS-P2-10) | Analytics 拆分后原因面板文件、DataSourceDetail banner 文案 | analytics.py classify 扩展、tech_answer_gaps.py 投影、gap_taxonomy.py | 拆分后趋零 | IF-2;Analytics.tsx 拆分先行 |
| **E 观察与导出** | U-15(TI-07/18/36/37/41/42/43)+U-16(TI-34/35/45) | Analytics 拆分后观察/导出/历史面板文件 | tech_observation.py、tech_export.py、gap_status.py、观察服务、导出服务 | 拆分后趋零 | IF-1/IF-5;IF-2(分类稳定后观察核验);Analytics.tsx 拆分先行 |
| **F 证据聚合** | U-17(TI-27)+U-18(TI-33)+U-19(TI-12) | Analytics 拆分后 meta/源卡/主题列面板文件 | tech_evidence.py、conversations.session_id 聚合投影、topic 派生 | 拆分后趋零 | IF-6;可立即(U-17 证据:session_id 已存在) |
| **Integration(第七轨)** | 共享文件拆分 prep(Analytics.tsx/tech.py,零语义变更)、合并、三门、全矩阵复核 | — | — | — | Wave 1 各轨 |

### 3.4 运行时验收数据要求(每轨)

- 数据仅限本地 docker PG(ask_ai/ask_ai),AUDIT-FIXTURE 标记隔离,SQL 全文记录入交付物。
- Track C 需 fixture:含需处理文档(可修复)、chunk 总数已知源(分数断言)、恢复事件、超期新鲜度源(提醒/过期态)、高风险变更源(预览计数非零)。
- Track D 需 fixture:每个新原因类至少 1 行真实分类证据(会话级证据可回放)。
- Track E 需 fixture:含 open cluster(进入观察)、同步成功事件钩子、观察期满/复现双路径、归属会话(导出内容比对)。
- Track F 需 fixture:含/不含 session_id 的历史会话(unavailable 断言)、多会话同簇(去重断言)、命中源证据(归因断言)。
- 生产验收(最终):生产栈只读复核+真实管理操作链,遵守 FINAL PASS 规则 §1。

## 4. Previous exemption reconciliation(旧豁免 → 新分类,全量映射)

旧材料:组合树 34c7d5b `docs/engineering/tasks/v163-integration-execution.md`(23 JD)、`DESIGN-ACCEPTANCE-AUDIT.md`(A20/B6/C23/D0)、`v163-design-remediation-execution.md`(20 A 类闭环+附录 B)、MANIFEST(7e3e71c)。**旧 PASS/EXEMPT 一律不继承;以下为逐项重定性。**

### 4.1 旧 A 类 20 项(修复后曾判 MATCH)→ 本轮复核

A-P1-01..08、A-P2-01..05、A-P3-01/02、A-P4-01、A-B2-01..04 → **全部维持 MATCH**(本轮代码+运行时双重复核:RT/01..07 + admin/tests)。无回退。

### 4.2 旧 B 类 6 组 fixture 族 → 本轮复验

FX-1(六源/1,204)、FX-2(98.7%=77+1/78)、FX-3(近因)、FX-4(五原因×两态+第2页)、FX-5/6(正常行)、既有 B1 seed(banner 3 项)→ **全部有效并经本轮 API=PG=UI 三角重新核验**(主文档 §5)。数据漂移记录:本地库含此前功能链残留(ne301 源、排队态),不影响断言族,验收前建议 fixture 重放清理。

### 4.3 旧 C 类 23 项 → 新分类(核心 reconcile 清单;Planning 修订后含冻结决定)

| 旧 ID(JD) | 旧分类(作废) | 新分类 | 新矩阵行/Gap | 冻结决定 |
|---|---|---|---|---|
| C-01(J-C1) 顶栏日期范围 | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | SH-09 / GAP-SC-1 | U-2(实现;范围=技术洞察分析窗) |
| C-02(J-C2) 帮助中心/收起菜单/系统分组 | APPROVED ABSENCE | **拆分**:系统分组=**IMPLEMENTATION DEFECT**(SH-06/DEF-A1);帮助中心=**UADC**(SH-10/11/UADC-4);收起菜单=**PFG**(SH-12) | GAP-SC-2 已移出;GAP-SC-3 | 帮助中心 U-3(获批缺席);收起 U-4(实现) |
| C-03(J-C3) 侧栏明暗 | REFERENCE CONFLICT | **已解决(U-1)→ MATCH** | SH-16 | U-1(LIGHT=权威方向) |
| C-B1-01(JD5) 品牌图 | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | DS-P2-02 / GAP-B1-1 | U-6(source-type 内建映射) |
| C-B1-02 banner 引用重验文案 | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | DS-P2-10 / GAP-B1-2 | U-14 |
| C-B1-03(JD8) 逐文档内容类型 | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | DS-P2-16/20 / GAP-B1-3 | U-7 |
| C-B1-04(JD9) 10/12 分数 | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | DS-P3-05 / GAP-B1-5 | U-9 |
| C-B1-05(JD10) 行级处理/重新处理 | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | DS-P2-25/26、DS-P3-07/08/09 / GAP-B1-4/7 | U-8 |
| C-B1-06(JD12) 恢复注记 | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | DS-P3-06 / GAP-B1-6 | U-10 |
| C-B1-07(JD13) 修复验证卡 | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | DS-P3-08/09 / GAP-B1-7 | U-8 |
| C-B1-08(JD15) 下次同步 | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | DS-P4-03 / GAP-B1-8 | U-11 |
| C-B1-09(JD17/18) Drawer 字段集 | APPROVED ABSENCE(编辑器超集) | **拆分 3 条 IMPLEMENTATION DEFECT**:名称 label(DS-P5-02)、类型禁用(DS-P5-04)、自动同步 toggle(DS-P5-05) | DEF-A2/A3/A4 | DS-P5-04:U-5(edit 禁用) |
| C-B1-10(JD19) 知识设置 Drawer | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | DS-P6-01..05 / GAP-B1-9 | U-12 |
| C-B1-11(JD20) 高风险预览 Modal | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | DS-P7-01..06 / GAP-B1-10 | U-13 |
| C-B2-01(J1/J12) 原因词表超集 | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | TI-09 / GAP-B2-1 | U-14 |
| C-B2-02(J2) 观察中 | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | TI-07/18/42 / GAP-B2-2 | U-15 |
| C-B2-03(J3) 导出 CSV | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | TI-34/45 / GAP-B2-3 | U-16 |
| C-B2-04(J4) 开始观察 | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | TI-36/37 / GAP-B2-2 | U-15 |
| C-B2-05(J5) 涉及 N 用户 | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | TI-27 / GAP-B2-4 | U-17 |
| C-B2-06(J6) 相关数据源 | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | TI-33 / GAP-B2-5 | U-18 |
| C-B2-07(J7) 问题描述叙事 | APPROVED ABSENCE | **MATCH(升级)**:运行时复核 RT/07 | TI-30/31 | N/A |
| C-B2-08(J8) 主题式短语 | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | TI-12 / GAP-B2-6 | U-19 |
| C-B2-09(J12) depicted 重演边界 | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP**(并入 GAP-B2-1) | TI-09 | U-14 |

### 4.4 旧 23 JD(组合树)其余项

旧 JD 中已被 Integration 收敛为 MATCH 的(J-C 顶栏身份、主操作蓝、选中态等)本轮全部复核维持 MATCH;旧 JD 与上表同源的按上表重定性;其余(如 JD5/8/9/10/12/13/15/17/18/19/20)即上表 C-B1 系列,已逐条映射。

### 4.5 结论(Planning 修订后)

**PREVIOUSLY EXEMPTED → NEW CLASSIFICATION 汇总:** 旧 23 项 APPROVED ABSENCE/待裁中 → PRODUCT-FUNCTIONAL GAP 16 族(38 矩阵行;帮助中心 2 行经 U-3 转 UADC)、IMPLEMENTATION DEFECT 4 行(自 C-02/C-B1-09 拆出)、MATCH 2 行升级(C-B2-07 叙事;C-03 侧栏经 U-1 解决)、USER-APPROVED DESIGN CHANGE 1 条新增(UADC-4)。旧 A20/B6 维持。**无任何旧豁免被继承为 PASS。**

## 5. User decisions(已全部关闭;保留台账)

| # | 决定 | 影响行 | 裁决(冻结) | 性质 |
|---|---|---|---|---|
| U-1 | 侧栏明暗 | SH-16 | **LIGHT=权威方向;无双主题**;SH-16 → MATCH | Role A 定 |
| U-2 | 全局日期范围语义 | SH-09 | **实现;范围=技术洞察分析窗(非全站假全局过滤);TI 相关 API 语义适用处必须遵守所选窗口** | Role A 定 |
| U-3 | 帮助中心目标语义 | SH-10/11 | **批准缺席(UADC-4):Help Center 入口推迟至存在权威目的地** | §2 默认 |
| U-4 | 侧栏收起控件 | SH-12 | **实现;纯 Admin shell 交互,零后端语义** | Role A 定 |
| U-5 | 编辑抽屉类型字段 | DS-P5-04 | **create 可选;edit 既有源 immutable/disabled;匹配参考** | Role A 定 |
| U-6 | 品牌资产字段 | DS-P2-02 | **实现;source-type/品牌呈现内建映射;禁任意远程 logo_url 作产品真值** | Role A 定 |
| U-7 | 逐文档内容类型契约 | DS-P2-16/20 | **实现;结构化后端真值,connector/ingestion 所有;前端禁文件名/文本推断** | Role A 定 |
| U-8 | 行级修复契约 | DS-P2-25/26、DS-P3-07/08/09 | **实现真实修复工作流:RBAC/幂等/可审计/进度/修复后验证;禁 UI-only repair** | Role A 定 |
| U-9 | chunk 级服务分数 | DS-P3-05 | **实现;权威 chunk serving 投影;UI 比例=后端真值** | Role A 定 |
| U-10 | 逐文档恢复计数 | DS-P3-06 | **实现;源自持久化权威恢复事件;禁前端计数器** | Role A 定 |
| U-11 | 调度真值 | DS-P4-03 | **实现 scheduler 权威 next_run_at;禁纯派生倒计时** | Role A 定 |
| U-12 | 知识设置域 | DS-P6 全部 | **实现;CURRENT=有资格支撑当前事实型回答(新鲜度政策约束,过期诚实浮现);HISTORICAL=仅历史/溯源/证据链,不得支撑当前价格/规格/可用性/运行状态;新鲜度按 source/policy 域可配置、后端权威、过期态 Admin 可见、资格消费真值;不重设计 lifecycle** | §2 默认 |
| U-13 | 高风险预览域 | DS-P7 全部 | **实现;影响计数后端权威;确认施加与预览完全一致的 mutation,drift 时失效/重算** | Role A 定 |
| U-14 | 原因分类学扩展 | TI-09、DS-P2-10 | **实现参考要求扩展词表;每类证据规则;禁 keyword-only 前端分类** | Role A 定 |
| U-15 | 观察状态机 | TI-07/18/36/37/41/42/43 | **实现 OPEN→OBSERVING→RESOLVED;进入需确认+sync/reindex 成功+post-sync 验证成功;观察期 7 天;复现→OPEN;满窗→RESOLVED;可中止;禁强转 RESOLVED;转移持久化/带时间戳/可审计/History 可见** | §2 默认 |
| U-16 | 导出+隐私契约 | TI-34/35/45 | **实现 admin-only 导出;最小必要字段;排除直接个人身份;可审计;CSV=所选 gap/query 范围精确对应** | Role A 定 |
| U-17 | 用户聚合 | TI-27 | **实现;不引入真人身份追踪;去重伪匿名会话;历史不可回填诚实 unavailable;仓库证据:conversations.session_id 已存在** | §2 默认 |
| U-18 | gap→源归因 | TI-33 | **实现;归因源自证据/对话/检索真值;禁前端猜** | Role A 定 |
| U-19 | 主题短语生成 | TI-12 | **实现;确定性派生优先;LLM 仅另行授权;稳定且忠实 cluster 内容** | Role A 定 |

**§2 默认冻结四项(U-3/U-12/U-15/U-17)仓库可行性复核全部通过,升级回 User 项:无。** 证据:U-17 conversations.session_id(String(64))已存在;U-15 question_clusters.status 可扩展+sync_runs(status/finished_at/consistency)/sync_log/verify_source_vectors 钩子齐备;U-12 data_sources 加性策略列与现行 lifecycle 真值(documents.lifecycle 词表)正交;U-3 无权威目的地证据确凿。

---

## ROLE A PRODUCT DECISIONS — FROZEN(2026-09-13)

19 项产品裁决(U-1..U-19)**全部冻结,不得再升给 User**。完整逐项表(裁决+理由+性质)见主审计文档 `v163-reference-traceability-audit.md`「ROLE A PRODUCT DECISIONS — FROZEN」章节与本 plan §5 台账。要点:

- **全部 GAP 行方向已获授权,但方向获授权 ≠ 变 MATCH**:IMPLEMENTATION DEFECT 4、PRODUCT-FUNCTIONAL GAP 38 保持原分类,直到实现+运行时验收完成。
- **按 §2 默认冻结**:U-3(帮助中心 → UADC-4,本批唯一获批缺席)、U-12(知识设置语义)、U-15(观察状态机)、U-17(伪匿名用户聚合);四项仓库可行性复核通过,**无升级回 User 项**。
- SH-16 经 U-1 解决 → MATCH;UNRESOLVED REFERENCE CONFLICT = 0。
- 禁止捷径(合同级,全轨适用):frontend-only fake state、fake counts、fake next_run_at、fake source attribution、fake user count、hard-coded topic labels、UI-only repair、unpersisted OBSERVING transitions、export 由当前渲染行而非权威范围数据构建、无证据合同的 keyword-only 原因分类。

## 6. IMPLEMENTATION AUTHORIZATION PACKAGE(执行授权包;本节为授权依据,**不启动实现**)

### 6.1 最终拓扑(授权版)

- **Wave 0(前置,零语义代码)**:Integration prep——Analytics.tsx 按 tab/面板拆组件文件、tech.py 拆 router 子模块、gap_taxonomy.py/gap_status.py 词表常量模块落位(IF-6);六轨合同附录 IF-1..IF-5 冻结。
- **Wave 1(全并行,六轨)**:A、B、C、D、E、F 各自独立分支+独立合同;文件互斥由 §3.2 拆分地图保证。
- **Wave 2(Integration 轨)**:backend 合并序 D→E→F(拆分到位后冲突面趋零);frontend 合并序 D→E→F→C→B→A;统一三门+全矩阵 152 行复核+FINAL PASS 判定。

### 6.2 各轨 B 级提示词要点(自包含;启动实现时逐轨下发)

**Track A(`track/v163-a-chrome`;基线 candidate 7e3e71c 谱系;worktree:实现树基于 origin/main 5c50191 之后的授权发布谱系,启动时以 integration 轨指定的发布基线为准)**
- 冻结合同:docs/engineering/tasks/v163-reference-remediation/track-a-contract.md
- 范围:SH-06(DEF-A1 系统 分组);SH-09(GAP-SC-1,U-2:顶栏日期范围=技术洞察分析窗,TI 相关 API 语义适用处遵守窗口);SH-12(GAP-SC-3,U-4:纯 Admin shell 折叠);SH-10/11 按 UADC-4 记录缺席,不实现。
- 验收:vitest 组标签/折叠/范围联动断言;真实折叠-展开+范围切换截图(1536×1024@1x);对照 PNG2;#52 导航清单修订记录。
- 禁止捷径:不得发明全站全局过滤语义;不得改动各页内既有 filter 真值;frontend-only fake state 禁止(范围必须真实贯通 API 参数)。

**Track B(`track/v163-b-drawer`)**
- 冻结合同:track-b-contract.md
- 范围:DS-P5-02(名称* label)、DS-P5-04(U-5:edit 禁用/create 可选)、DS-P5-05(自动同步 toggle+说明)。零后端、零 PUT 语义变更。
- 验收:vitest label/toggle/disabled;toggle→保存→PUT enabled 真实生效;截图对照 PNG1 面板5。
- 禁止捷径:CSS 伪装 disabled、改 PUT payload、删新建态类型选择。

**Track C(`track/v163-c-b1-product`)**
- 冻结合同:track-c-contract.md(+IF-3/IF-4 附录)
- 范围:U-6(品牌内建映射)、U-7(content_type connector 所有)、U-8(真实修复工作流:RBAC/幂等/可审计/进度/修复后验证)、U-9(serving 投影,UI 比例=后端真值)、U-10(持久化恢复事件)、U-11(scheduler next_run_at,禁纯派生)、U-12(知识设置:CURRENT/HISTORICAL 资格层+新鲜度政策,不重设计 lifecycle)、U-13(预览:计数后端权威+确认施加完全一致 mutation)。
- 验收:功能 E2E 四链(修复链/知识设置-预览-确认链/新鲜度提醒链/倒计时链)+三角(API=PG=UI)+pytest/vitest/tsc/build;截图面板2/3/4/6/7。
- 禁止捷径:前端算影响计数、修复绕过幂等/审计、资格语义只存不用、UI-only repair、fake next_run_at、fake counts。

**Track D(`track/v163-d-taxonomy`)**
- 冻结合同:track-d-contract.md(+IF-2 附录)
- 范围:U-14(TI-09 六新类+证据规则;DS-P2-10 banner 文案)。旧 4 类回归零破坏。
- 验收:每新词≥1 行真实分类证据(fixture 经真实 DB→API→UI);过滤=权威行集;诊断分布一致;pytest/vitest。
- 禁止捷径:keyword-only 前端分类、无证据规则分类上线、映射近义词。

**Track E(`track/v163-e-observation`)**
- 冻结合同:track-e-contract.md(+IF-1/IF-5 附录)
- 范围:U-15(OPEN→OBSERVING→RESOLVED 全状态机:进入=操作者确认+sync/reindex 成功+post-sync 验证成功;7 天观察窗;复现→OPEN;满窗→RESOLVED;中止→OPEN;禁强转 RESOLVED;转移持久化/带时间戳/可审计/History 可见)+U-16(admin-only 导出;最小字段;排除直接个人身份;可审计;CSV=所选范围)。
- 验收:E2E 观察双路径(期满/复现)+中止+导出内容=所选范围权威数据+无隐私字段+审计行;pytest/vitest/tsc/build。
- 禁止捷径:跳过同步核验进观察、unpersisted OBSERVING transitions、前端造 CSV、export 由当前渲染行构建、无流转记录的经观察转 RESOLVED。

**Track F(`track/v163-f-evidence`)**
- 冻结合同:track-f-contract.md(+IF-6 消费)
- 范围:U-17(去重伪匿名会话计数;session_id;历史 NULL→unavailable)、U-18(归因源自证据/对话/检索真值)、U-19(主题确定性派生优先;LLM 仅另行授权)。
- 验收:三角去重计数;归因外链真实到达且规则可解释;主题稳定(同簇多次拉取不变);隐私聚合无 PII;pytest/vitest。
- 禁止捷径:fake user count、无证据规则归因、hard-coded topic labels、前端估算用户数、LLM 主题未授权上线。

### 6.3 并行组/依赖序/integration 归属

- 并行组:Wave 1 六轨全并行(A/B 零后端最快闭环;C/D/E/F 由 IF-6 拆分保证文件互斥)。
- 依赖序:IF-1..IF-6 冻结 → Wave 1 → Integration(D→E→F backend;D→E→F→C→B→A frontend)→ 三门+全矩阵复核 → FINAL PASS 判定。
- Integration 归属:第七轨(Integration)拥有共享文件 prep、合并仲裁、全矩阵复核与 FINAL PASS 报告;各轨拥有自己的分支/合同/交付物。

### 6.4 运行时与生产验收数据要求

- 运行时:每轨本地真实栈(vite/backend/PG)全链复核;fixture 要求见 §3.4;AUDIT-FIXTURE 隔离+SQL 全文。
- 生产:最终生产验收按 FINAL PASS §1(生产栈只读复核+真实管理操作链;零 fixture 残留)。

### 6.5 Issue 映射(各轨落地后关闭;本 planning 不关任何 issue)

| Track | 关闭/主要贡献 |
|---|---|
| A | **#52**(IA 收敛:系统 分组+导航清单修订)、#60 共享 chrome 部分 |
| B | **#53/#54** 编辑抽屉字段范围 |
| C | **#54**(详情:品牌/类型/修复/知识设置/预览)、**#55**(检查器:serving 分数/恢复计数/验证卡)、**#56**(历史:下次同步) |
| D | **#59** 原因词表/分布部分、#54 banner 原因部分 |
| E | **#58**(观察生命周期/事件层级)、**#59**(gap 状态机/导出部分) |
| F | **#59**(用户/归因/主题部分)、#57(TI IA 稳定性贡献) |
| Integration | #60(视觉层级统一收口)、全矩阵复核报告 |

### 6.6 授权判定

- 产品决策:全部冻结(U-1..U-19),无遗留待批项。
- 分类现状:MATCH 105 / ID 4 / PFG 38 / UADC 5 / RC 0 → 剩余工作全部为已授权实现+验收。
- **IMPLEMENTATION_AUTHORIZED = YES(条件生效)**:授权依据=本授权包+六轨冻结合同+IF-1..IF-6;实现启动须按 Wave 0→1→2 顺序,且各轨不得越合同边界。**本 planning 任务本身不启动实现。**

## 7. 冻结合同

每 Track 合同见 `v163-reference-remediation/track-{a..f}-contract.md`(冻结目标/参考需求/产品语义/变更边界/后端数据要求/前端要求/禁止捷径/验收/运行时状态/视觉证据/功能 E2E/交付物;不规定 HOW)。
