# V1.6.3 Reference Remediation Plan(拓扑 + 冻结合同准备 + 新终局验收规则 + 旧豁免 reconcile)

审计基线:branch `audit/v163-reference-traceability-20260913` @ 7e3e71c(审计对象谱系 34c7d5b→2f0bc06→8fa121a→7e3e71c tip;**7e3e71c 不再被授权发布,仅作审计对象**)。
权威参考:两 PNG(见主审计文档 §0)。权威分类:MATCH / IMPLEMENTATION DEFECT / PRODUCT-FUNCTIONAL GAP / USER-APPROVED DESIGN CHANGE / REFERENCE CONFLICT。

---

## 1. 新终局验收规则(FINAL PASS 定义,冻结)

**FINAL PASS 当且仅当全部成立:**

1. 三门 PASS:Engineering(pytest 全量+vitest 全量+tsc+build+ruff)、Functional(真实 UI→API→DB 三角,写链真实执行)、Visual(逐矩阵 MATCH 行对照权威 PNG)。
2. IMPLEMENTATION DEFECT = 0(矩阵内 A 类全部闭合)。
3. PRODUCT-FUNCTIONAL GAP = 0(矩阵内 B 类全部交付或逐条获得 USER-APPROVED DESIGN CHANGE)。
4. UNRESOLVED REFERENCE CONFLICT = 0(SH-16 侧栏明暗获 User 裁决并落实)。
5. USER-APPROVED DESIGN CHANGE 逐条有 User 明确决定记录;**agent 解释、惯例、带内推定均不算批准**。当前有效 UADC 仅 3 条(UADC-1/2/3)。
6. 截图不能独立证明功能 MATCH:功能控件以真实 UI→API→持久化三角验证;代码不能独立证明运行时 MATCH:以真实运行栈复核。
7. 验收数据仅限本地 docker PG(AUDIT-FIXTURE 标记隔离,SQL 全文记录);禁止触碰生产。

任何偏离 = 对应矩阵行保持 FAIL;V1.6.3 CONFORMANCE = FAIL,IMPLEMENTATION_AUTHORIZED = NO。

## 2. 当前状态结论

V1.6.3 CONFORMANCE = **FAIL**:IMPLEMENTATION DEFECT 4、PRODUCT-FUNCTIONAL GAP 40 行(18 族)、REFERENCE CONFLICT 1 未决。7e3e71c 不满足 FINAL PASS,不得发布。

## 3. 执行拓扑提案(从仓库现实推导;Track A–F)

依赖序与并行关系:

```
Track B(呈现缺陷,独立)      ──────────────► 可立即并行
Track A(chrome;A2/A3 需 User)───────────────► 部分并行(User 裁后闭环)
Track D(原因分类学)          ──► GAP-B1-2 依赖它
Track E(观察状态机)          ──► 依赖 D(分类稳定后转观察核验);TI-41 历史随 E
Track F(证据聚合:用户/归因)  ──► 独立;隐私评估先行
Track C(B1 修复/知识设置域)   ──► C 内部依赖:修复命令→验证卡;知识设置→预览 Modal
```

| Track | 范围(GAP 族) | 前端主要文件 | 后端主要文件 | 共享文件冲突 | 前置 |
|---|---|---|---|---|---|
| **A 共享 chrome** | DEF-A1;GAP-SC-1/2/3(后三者需 User 决定,未裁前只做 DEF-A1) | Sidebar.tsx、Layout.tsx | 无(除非帮助中心选路由方案) | Sidebar.tsx(与无他轨冲突) | User 裁 SH-09..12 |
| **B B1 呈现缺陷** | DEF-A2/A3/A4 | SourceEditorDrawer.tsx | 无 | SourceEditorDrawer.tsx(仅本轨) | DEF-A3 需 User 裁;其余可立即 |
| **C B1 修复与知识设置域** | GAP-B1-1/3/4/5/6/7/8/9/10 | DataSourceDetail.tsx、SourceEditorDrawer/新 KnowledgeSettingsDrawer、新 RiskPreviewModal | data_sources.py(修复命令/调度真值/预览)、新 knowledge_settings 端点、连接器 content_type | DataSourceDetail.tsx(仅本轨);backend data_sources.py(与无他轨冲突) | 修复契约+时态/新鲜度契约+预览契约冻结;GAP-B1-1/3/6/8 需 User 决定 |
| **D 原因分类学** | GAP-B2-1(+GAP-B1-2 呈现) | Analytics.tsx(选项/徽章)、DataSourceDetail banner 文案 | analytics.py classify_gap_miss_types 扩展、tech.py 投影 | analytics.py/tech.py(**与 E/F 冲突:tech.py 三轨共享→按 合并序 D→E→F 或拆模块**) | User 授权分类学扩展 |
| **E 观察与导出闭环** | GAP-B2-2/3 | Analytics.tsx GapPanel(CTA/观察态/历史)、新导出卡 | tech.py(观察命令/转移/导出)、新观察服务+导出服务 | Analytics.tsx(与 D/F)、tech.py(与 D/F) | D 先行;观察契约+导出/隐私契约冻结 |
| **F 证据聚合** | GAP-B2-4/5/6 | Analytics.tsx GapPanel(meta/源卡/主题) | tech.py 投影扩展(用户聚合/归因/主题)、conversations 用户标识真相 | Analytics.tsx、tech.py(同上) | 隐私评估;归因/主题规则冻结 |

**冻结接口(跨轨,先行冻结后并行):**
1. `question_clusters.status` 词表(open/observing/resolved)+观察元数据形状(E 定义,D/F 消费)。
2. 缺口原因分类词表 v2(D 定义,B1-2/B2 消费)。
3. 修复命令+审计事件形状(C 定义,P3/P2 消费)。
4. 知识设置策略模型(时态角色/新鲜度)+mutation-preview 请求/响应形状(C 内先冻结)。
5. 导出 CSV 列集+隐私字段排除清单(E 先冻结,User 批)。
6. tech.py 拆分建议:answer_gaps 投影独立模块,降低 D/E/F 合并冲突。

**integration 归属:** 每轨独立分支+合同;integration 轨(第七轨)按 D→E→F→C→B→A 序合入 candidate,统一跑三门+全矩阵复核。共享文件(Analytics.tsx、tech.py)改动轨在 integration 时由 integration 轨仲裁。

## 4. Previous exemption reconciliation(旧豁免 → 新分类,全量映射)

旧材料:组合树 34c7d5b `docs/engineering/tasks/v163-integration-execution.md`(23 JD)、`DESIGN-ACCEPTANCE-AUDIT.md`(A20/B6/C23/D0)、`v163-design-remediation-execution.md`(20 A 类闭环+附录 B)、MANIFEST(7e3e71c)。**旧 PASS/EXEMPT 一律不继承;以下为逐项重定性。**

### 4.1 旧 A 类 20 项(修复后曾判 MATCH)→ 本轮复核

A-P1-01..08、A-P2-01..05、A-P3-01/02、A-P4-01、A-B2-01..04 → **全部维持 MATCH**(本轮代码+运行时双重复核:RT/01..07 + admin/tests)。无回退。

### 4.2 旧 B 类 6 组 fixture 族 → 本轮复验

FX-1(六源/1,204)、FX-2(98.7%=77+1/78)、FX-3(近因)、FX-4(五原因×两态+第2页)、FX-5/6(正常行)、既有 B1 seed(banner 3 项)→ **全部有效并经本轮 API=PG=UI 三角重新核验**(主文档 §5)。数据漂移记录:本地库含此前功能链残留(ne301 源、排队态),不影响断言族,验收前建议 fixture 重放清理。

### 4.3 旧 C 类 23 项 → 新分类(核心 reconcile 清单)

| 旧 ID(JD) | 旧分类(作废) | 新分类 | 新矩阵行/Gap |
|---|---|---|---|
| C-01(J-C1) 顶栏日期范围 | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | SH-09 / GAP-SC-1 |
| C-02(J-C2) 帮助中心/收起菜单/系统分组 | APPROVED ABSENCE | **拆分**:系统分组=**IMPLEMENTATION DEFECT**(SH-06/DEF-A1);帮助中心=**PFG**(SH-10/11);收起菜单=**PFG**(SH-12) | GAP-SC-2/3 |
| C-03(J-C3) 侧栏明暗 | REFERENCE CONFLICT(Role A 裁) | **REFERENCE CONFLICT(维持;两 PNG 直接读取确认真冲突;仍待 User 裁)** | SH-16/CONFLICT-1 |
| C-B1-01(JD5) 品牌图 | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | DS-P2-02 / GAP-B1-1 |
| C-B1-02 banner 引用重验文案 | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | DS-P2-10 / GAP-B1-2 |
| C-B1-03(JD8) 逐文档内容类型 | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | DS-P2-16/20 / GAP-B1-3 |
| C-B1-04(JD9) 10/12 分数 | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | DS-P3-05 / GAP-B1-5 |
| C-B1-05(JD10) 行级处理/重新处理 | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | DS-P2-25/26、DS-P3-07 / GAP-B1-4 |
| C-B1-06(JD12) 恢复注记 | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | DS-P3-06 / GAP-B1-6 |
| C-B1-07(JD13) 修复验证卡 | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | DS-P3-08/09 / GAP-B1-7 |
| C-B1-08(JD15) 下次同步 | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | DS-P4-03 / GAP-B1-8 |
| C-B1-09(JD17/18) Drawer 字段集 | APPROVED ABSENCE(编辑器超集) | **拆分 3 条 IMPLEMENTATION DEFECT**:名称 label(DS-P5-02)、类型禁用(DS-P5-04,需 User 裁)、自动同步 toggle(DS-P5-05) | DEF-A2/A3/A4 |
| C-B1-10(JD19) 知识设置 Drawer | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | DS-P6-01..05 / GAP-B1-9 |
| C-B1-11(JD20) 高风险预览 Modal | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | DS-P7-01..06 / GAP-B1-10 |
| C-B2-01(J1/J12) 原因词表超集 | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | TI-09 / GAP-B2-1 |
| C-B2-02(J2) 观察中 | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | TI-07/18/42 / GAP-B2-2 |
| C-B2-03(J3) 导出 CSV | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | TI-34/45 / GAP-B2-3 |
| C-B2-04(J4) 开始观察 | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | TI-36/37 / GAP-B2-2 |
| C-B2-05(J5) 涉及 N 用户 | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | TI-27 / GAP-B2-4 |
| C-B2-06(J6) 相关数据源 | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | TI-33 / GAP-B2-5 |
| C-B2-07(J7) 问题描述叙事 | APPROVED ABSENCE | **MATCH(升级)**:运行时复核 RT/07——问题描述+诊断结论两 section 合计完整覆盖 depicted 语义(事实 voice 记录在案,因果归诊断结论承担) | TI-30/31 |
| C-B2-08(J8) 主题式短语 | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP** | TI-12 / GAP-B2-6 |
| C-B2-09(J12) depicted 重演边界 | APPROVED ABSENCE | **PRODUCT-FUNCTIONAL GAP**(并入 GAP-B2-1) | TI-09 |

### 4.4 旧 23 JD(组合树)其余项

旧 JD 中已被 Integration 收敛为 MATCH 的(J-C 顶栏身份、主操作蓝、选中态等)本轮全部复核维持 MATCH;旧 JD 与上表同源的按上表重定性;其余(如 JD5/8/9/10/12/13/15/17/18/19/20)即上表 C-B1 系列,已逐条映射。

### 4.5 结论

**PREVIOUSLY EXEMPTED → NEW CLASSIFICATION 汇总:** 旧 23 项 APPROVED ABSENCE/待裁中 → PRODUCT-FUNCTIONAL GAP 18 族(40 矩阵行)、IMPLEMENTATION DEFECT 4 行(自 C-02/C-B1-09 拆出)、MATCH 1 行升级(C-B2-07)、REFERENCE CONFLICT 1 项维持待裁。旧 A20/B6 维持。**无任何旧豁免被继承为 PASS。**

## 5. User decisions required(阻塞清单)

| # | 决定 | 影响行 | 选项 |
|---|---|---|---|
| U-1 | 侧栏明暗(SC-7) | SH-16 | 浅色维持/深色/双主题 |
| U-2 | 全局日期范围语义 | SH-09 | 授权全局窗口 / 接受页内局部 filter(转 UADC) |
| U-3 | 帮助中心目标语义 | SH-10/11 | 授权目标(路由/外链)/ 批准缺席(转 UADC) |
| U-4 | 侧栏收起控件 | SH-12 | 授权实现 / 批准缺席(转 UADC) |
| U-5 | 编辑抽屉类型字段 | DS-P5-04 | 禁用匹配参考 / 批准维持超集(转 UADC) |
| U-6 | 品牌资产字段 | DS-P2-02 | 授权 logo 字段 / 批准字母块(转 UADC) |
| U-7 | 逐文档内容类型契约 | DS-P2-16/20 | 授权抽取契约 / 批准源级(转 UADC) |
| U-8 | 行级修复契约 | DS-P2-25/26、DS-P3-07/08/09 | 冻结契约并实现 / 批准只读(转 UADC) |
| U-9 | chunk 级服务分数 | DS-P3-05 | 授权投影 / 批准二值(转 UADC) |
| U-10 | 逐文档恢复计数 | DS-P3-06 | 授权 / 批准缺席(转 UADC) |
| U-11 | 调度真值(下次同步) | DS-P4-03 | 授权端点 / 批准周期承载(转 UADC) |
| U-12 | 知识设置域(时态角色+新鲜度) | DS-P6 全部 | 冻结契约并实现 / 批准缺席(转 UADC) |
| U-13 | 高风险预览域 | DS-P7 全部 | 冻结预览契约并实现 / 批准缺席(转 UADC) |
| U-14 | 原因分类学扩展 | TI-09、DS-P2-10 | 授权六新类 / 批准权威子集(转 UADC) |
| U-15 | 观察状态机 | TI-07/18/36/37/41/42/43 | 冻结观察契约并实现 / 批准两态(转 UADC) |
| U-16 | 导出+隐私契约 | TI-34/35/45 | 冻结并实现 / 批准深链替代(转 UADC) |
| U-17 | 用户聚合(隐私评估) | TI-27 | 授权 / 批准缺席(转 UADC) |
| U-18 | gap→源归因 | TI-33 | 授权归因规则 / 批准缺席(转 UADC) |
| U-19 | 主题短语生成(可能 LLM) | TI-12 | 授权生成契约 / 批准代表问句(转 UADC) |

## 6. 冻结合同

每 Track 合同见 `v163-reference-remediation/track-{a..f}-contract.md`(冻结目标/参考需求/产品语义/变更边界/后端数据要求/前端要求/禁止捷径/验收/运行时状态/视觉证据/功能 E2E/交付物;不规定 HOW)。
