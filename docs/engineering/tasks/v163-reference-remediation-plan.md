# V1.6.3 Reference Remediation Plan(拓扑 + 冻结合同 + 新终局验收规则 + 旧豁免 reconcile + 执行授权包;Planning 修订 2026-09-13:Role A 裁决冻结;**终轮 review fix 2026-09-13:Wave 0A/0B 拆分 + PREP_BASE_SHA + U-2 能力矩阵 + D/E 依赖合同**)

审计基线:branch `audit/v163-reference-traceability-20260913` @ 794fa55(审计对象 7e3e71c,谱系 34c7d5b→2f0bc06→8fa121a→7e3e71c tip;**7e3e71c 不再被授权发布,仅作审计对象**)。
权威参考:两 PNG(见主审计文档 §0)。权威分类:MATCH / IMPLEMENTATION DEFECT / PRODUCT-FUNCTIONAL GAP / USER-APPROVED DESIGN CHANGE / REFERENCE CONFLICT。
Planning 修订范围:仅本分支 docs/engineering/tasks/v163-reference-* 文档;零产品代码修改、零 merge、零 deploy、零关 issue。

**终轮 review fix(2026-09-13,本轮 planning 修订;U-1..U-19 冻结决定全部不变,零 GAP 改判):**
1. **Wave 0 拆分为 0A/0B**(原「Wave 0 零代码却含结构拆分」矛盾消除):Wave 0A = CONTRACT FREEZE(docs only,IF-1..IF-7);Wave 0B = STRUCTURAL PREP(真实代码但仅限结构 refactor,四零约束+行为等价验收),产出 **PREP_BASE_SHA**(Wave 1 六轨强制共同基线,禁止混合基线)。
2. **U-2 语义适用处具体化**:新增 §3.5「TECHNICAL INSIGHTS WINDOW CAPABILITY MATRIX」(只读仓库审计 8 端点;**Outcome B 冻结**:Track A 后端范围=BC-1/BC-2 参数能力;S3/S4/S6 例外面冻结)。Track A 不再表述为「零后端」。
3. **D/E 依赖澄清**:新增 §3.6「D/E DEPENDENCY CONTRACT」(实现依赖 D→E=NONE;验收依赖=E joined runtime FINAL PASS 需 D candidate)。旧「Track D 先行」表述废止。
4. 11 点一致性核验表见 §8(全部 PASS);**FINAL PLANNING BASELINE FIX 2026-09-13:新增 §3.0.2 WAVE_0B_BASE_SHA=7e3e71c 代码基线契约(8 规则),§3.0.3 PREP_BASE_SHA 合同随之修订,核验表扩至 14 点(12–14 PASS)**。

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

### 3.0 WAVE 0A — CONTRACT FREEZE(docs only)

**性质:纯 planning/合同层冻结;零产品代码、零运行时行为变化、零数据变更、零结构拆分。** 结构拆分一律归 Wave 0B(§3.0.1),本阶段与代码无关。

跨轨共享接口在实现启动前以合同附录形式冻结:

| IF | 内容 | 冻结责任 | 消费方 |
|---|---|---|---|
| IF-1 | `question_clusters.status` 词表(open/observing/resolved)+观察元数据+流转事件形状 | Track E | D/F、投影、前端状态词表 |
| IF-2 | 缺口原因分类词表 v2(6 新类+证据规则 ID 清单) | Track D | GAP-B1-2、TI-09/31/40、E(观察核验依赖分类稳定;E 实现依此冻结合同,不等 D 代码) |
| IF-3 | 修复命令请求/响应+审计事件形状(RBAC/幂等键/验证结果) | Track C | DS-P2/P3 前端、#55 |
| IF-4 | 知识设置策略模型(资格角色/新鲜度)+mutation-preview 请求/响应形状 | Track C | DS-P6/P7 |
| IF-5 | 导出 CSV 列集+隐私字段排除清单+审计行形状 | Track E | TI-34/35/45 |
| IF-6 | 共享文件拆分地图(见 3.2;推荐而非强制 HOW)+ 拆分后**文件内区域所有权**(tech_answer_gaps.py 窗口面=A(BC-1)/分类挂载面=D;analytics.py source-health 窗口面=A(BC-2)/classify_gap_miss_types=D;Analytics.tsx 页面壳/共享窗状态=A(IF-7)) | Integration 轨 | D/E/F、A(BC-1/BC-2) |
| IF-7 | U-2 技术洞察分析窗合同:分析窗词表(today/7d/30d/all/显式起止;默认 7d)+ 单一共享窗状态(三控制面呈现)+ 窗口面绑定 + 例外面冻结(全部见 §3.5 能力矩阵,Outcome B) | Track A(冻结文本随 §3.5) | A(交付 BC-1/BC-2+绑定)、E(导出范围继承队列激活窗)、F(U-17 聚合窗=所选分析窗) |

Wave 0A 冻结产物:IF-1..IF-7 附录 + 六轨合同 + 本 plan;**全部 docs-only**。

### 3.0.1 WAVE 0B — STRUCTURAL PREP(结构集成预备;真实代码,仅限结构 refactor)

**性质:允许真实代码改动,但仅限结构 refactor,且全部满足四零约束:零产品语义变化、零新业务行为、零 API 语义变化、零数据模型语义变化。** 执行者=Integration 轨;必须在 Wave 0A(合同冻结)之后启动。

允许内容(=IF-6 拆分地图的物理落位):

1. `admin/src/pages/Analytics.tsx`(1416 行)按 tab/面板拆组件文件(§3.2 item 1 地图);
2. `backend/api/admin/tech.py`(765 行)拆 router 子模块(§3.2 item 2 地图:tech_answer_gaps.py/tech_observation.py/tech_export.py/tech_evidence.py);
3. 词表常量模块抽取:`gap_taxonomy.py`(既有 4 类词表字面量迁入)、`gap_status.py`(既有 open/resolved 迁入)——**仅迁移既有值;任何新词表条目(observing、6 新类)属 Wave 1 D/E,不得提前写入**;
4. 共享文件所有权预备(拆分后各轨面板文件/文件内区域边界落位)。

禁止内容:任何行为变化;任何新端点/新参数语义(**BC-1/BC-2 属 Wave 1 Track A,不得在 0B 提前实现**);任何词表扩条;任何 UI 文案/视觉/交互变化;任何 fixture/数据写入。

**Wave 0B 验收(全过才可产出 PREP_BASE_SHA):**

- 行为等价测试:既有行为断言逐条不变(既有 vitest 断言与后端 pytest 断言零修改;新增仅限纯结构等价断言);
- 后端 pytest(结构拆分触及面全量)、admin vitest、tsc、build、ruff 全 PASS;
- 既有 runtime smoke(vite 5184/backend 8104 本地栈)零失败;
- 零视觉/功能行为漂移(与 7e3e71c 运行时对照)。

Wave 0B 产出:**PREP_BASE_SHA = Wave 0B 终局提交**(见 §3.0.3;实现基线=WAVE_0B_BASE_SHA,见 §3.0.2)。

### 3.0.2 WAVE_0B_BASE_SHA CONTRACT(代码基线契约;FINAL PLANNING BASELINE FIX 2026-09-13 冻结)

- **WAVE_0B_BASE_SHA = `7e3e71cc1d50a19e8625fffcacbe1c0f7b11af76`**(冻结值,即 152 行追溯审计所评估的 v1.6.3 实现谱系 34c7d5b→2f0bc06→8fa121a→7e3e71c 之 tip)。
- **规则 1**:Wave 0B 必须直接从 WAVE_0B_BASE_SHA 分支(merge-base(Wave0B, 7e3e71c) = 7e3e71c)。
- **规则 2**:planning/docs 提交 `b054d9f`(及其后全部 planning 提交)仅为**合同权威证据**,不是 Wave 0B 的实现父。
- **规则 3**:`origin/main 5c50191` **不是**合法的 Wave 0B 实现基线——152 行追溯审计评估的是止于 7e3e71c 的实现谱系,从 main 开工会丢弃全部已验收 MATCH/UADC 行为。
- **规则 4**:Wave 0B 必须保全 7e3e71c 中已存在的全部 MATCH / UADC 行为(V-1/V-2/V-3 与 105 项 MATCH 呈现)。
- **规则 5**:Wave 0B 验收必须显式核验:(a) `merge-base(Wave0B, 7e3e71c) = 7e3e71c`;(b) `diff(7e3e71c → PREP_BASE_SHA)` 仅含授权的结构 refactor 变更(四零约束;任何产品语义/API 语义/数据模型语义/词表扩展 = 越权)。
- **规则 6**:PREP_BASE_SHA = 行为等价验证全过后的 **Wave 0B 已接受 tip**。
- **规则 7**:Wave 1 A–F 必须全部从该精确 PREP_BASE_SHA 分支(见下方 PREP_BASE_SHA CONTRACT)。
- **规则 8**:Integration 必须拒绝任何祖先不含 PREP_BASE_SHA 作为共同实现基线的 Track(merge-base(track, integration) == PREP_BASE_SHA,不满足 = 交付无效)。

### 3.0.3 PREP_BASE_SHA CONTRACT(Wave 1 强制共同基线)

- **定义**:PREP_BASE_SHA = Wave 0B 终局提交 SHA(= 行为等价验证全过后的已接受 Wave 0B tip;Wave 0B 验收全过后由 Integration 轨冻结填入下方;**填入前 Wave 1 任何轨道不得开工**)。
- **实现父链(冻结)**:`7e3e71c(WAVE_0B_BASE_SHA) → Wave 0B 结构 refactor commits → PREP_BASE_SHA`;planning 分支(`b054d9f`…)与本实现链**并行**,仅提供合同,不是实现祖先。
- **强制规则:Wave 1 六轨 A–F 必须全部从同一 PREP_BASE_SHA 分支,禁止混合基线。** 理由:IF-6 文件互斥只在拆分后的树上成立;混合基线会重新引入 Analytics.tsx/tech.py 争用并使拆分地图与文件内区域所有权失效。
- **合并核验**:Integration 轨合并各轨时必须验证 merge-base(track, integration) == PREP_BASE_SHA;不满足 = 该轨交付无效,回炉 rebase 后重验。
- **基线变更** = planning 修订(不得在执行期临时换基线)。
- **当前值:PREP_BASE_SHA = (待 Wave 0B 完成时由 Integration 轨填入并冻结)。**### 3.1 拓扑与依赖

```
Wave 0A(docs only,合同冻结):IF-1..IF-7 冻结(含 U-2 分析窗能力矩阵 Outcome B=§3.5、IF-6 拆分地图+文件内区域所有权)
Wave 0B(结构预备,Integration 轨;真实代码但仅限结构 refactor,四零约束;**直接分支自 WAVE_0B_BASE_SHA=7e3e71c,§3.0.2**):
  Analytics.tsx 拆分 + tech.py router 拆分 + 词表常量模块抽取(既有值迁移)
  验收:行为等价+pytest/vitest/tsc/build/ruff+既有 runtime smoke+零视觉/功能漂移+§3.0.2 规则 5 双核验
  → 产出 PREP_BASE_SHA(冻结;Wave 1 开工前置)
Wave 1(全并行;六轨 A–F 全部从同一 PREP_BASE_SHA 分支,禁止混合基线):
  Track A(chrome:DEF-A1 + U-2 顶栏范围控件+共享窗绑定 + U-4 收起;后端窗口参数能力 BC-1/BC-2)
       ── 非「零后端」(§3.5 Outcome B:仅参数能力,零新表零新端点)
  Track B(编辑抽屉 DEF-A2/A3/A4,U-5 冻结)            ── 零后端
  Track C(B1 修复/品牌/内容类型/计数/调度/知识设置/预览)── data_sources.py+新模块,与他轨文件互斥
  Track D(原因分类学 U-14)                            ── tech 拆分后独立子模块
  Track E(观察状态机 U-15 + 导出 U-16)                ── tech 拆分后独立子模块;实现不等 D(§3.6:D/E 实现依赖=NONE)
  Track F(用户聚合 U-17/归因 U-18/主题 U-19)          ── tech 拆分后独立子模块;聚合窗=IF-7 所选分析窗
Wave 2(integration 轨,第七轨):
  D candidate → E joined acceptance gate(§3.6:E joined runtime FINAL PASS 需 D candidate)
  backend 合并序:D→E→F(若 IF-6 拆分到位则可任意序,冲突面趋零)
  frontend 合并序:D→E→F→C→B→A(Analytics.tsx 面板文件互斥;A 拥有页面壳/共享窗状态)
  统一跑三门+全矩阵 152 行复核+FINAL PASS 判定
```

### 3.2 共享文件争用解决(D/E/F 在 Analytics.tsx、tech.py、answer-gap 投影/状态/词表)

冻结语义下 D/E/F 争用点与推荐解法(**推荐而非强制 HOW**;若不拆,则按 D→E→F 合并序+integration 仲裁):

1. **`admin/src/pages/Analytics.tsx`(1416 行)按 tab/面板拆组件文件**:页面壳(共享窗状态+顶栏范围接线+TI-10 工具栏窗选择绑定=Track A,IF-7)、工具栏(status/cause filter=D、观察态 filter=E)、队列行(theme chips=D、观察中徽章=E、主题列=F、用户/源卡 meta=F)、诊断侧板(结论=D、CTA/内容补充/历史=E、meta 三计数=F)、导出卡=E。拆分后 D/E/F 各自只改自己面板文件;拆分本身归 **Wave 0B 结构预备**(Integration 轨,零语义变更,产出 PREP_BASE_SHA)。
2. **`backend/api/admin/tech.py`(765 行)拆 router 子模块**:`tech_answer_gaps.py`(投影/过滤,q/status/cause/window 参数;D 词表挂载点;**窗口参数面=A(BC-1,§3.5)**)、`tech_observation.py`(观察命令/转移任务/流转事件投影;E)、`tech_export.py`(CSV 流式+审计;E)、`tech_evidence.py`(用户聚合/归因/topic;F)。状态词表 IF-1、分类词表 IF-2 分别由 E/D 在各自子模块内实现,投影层只消费词表常量。**文件内区域所有权(IF-6 附录冻结)**:同文件跨轨改动按区域互斥——tech_answer_gaps.py 窗口面=A、分类/cause 面=D;analytics.py source-health 窗口面=A(BC-2)、classify_gap_miss_types=D;合并由 Integration 轨仲裁。
3. **answer-gap 投影/状态/词表**:状态常量(`question_clusters.status` 词表)与原因词表各自独立常量模块(如 `backend/services/gap_taxonomy.py`、`gap_status.py`),D/E 各自拥有,投影/前端引用同一常量——禁止各轨复制词表字面量。
4. **导出**:独立模块(E 独有),无争用。

### 3.3 Track 表(精炼)

| Track | 范围(冻结决定) | 前端主要文件 | 后端主要文件 | 文件冲突 | 前置 |
|---|---|---|---|---|---|
| **A 共享 chrome + U-2 分析窗** | DEF-A1;U-2(SH-09,含 BC-1/BC-2);U-4(SH-12);UADC-4 记录 | Sidebar.tsx、Layout.tsx(+顶栏范围控件)、Analytics 页面壳/共享窗状态与三控制面绑定(IF-7) | tech_answer_gaps.py 窗口参数面(BC-1)、analytics.py source-health 窗口面(BC-2)(U-4 仍零后端;§3.5 Outcome B) | Analytics 页面壳/工具栏窗面=本轨(区域互斥);后端两文件窗口面区域互斥(IF-6 附录) | Wave 0A(IF-6/IF-7)+Wave 0B;从 PREP_BASE_SHA 分支 |
| **B 编辑抽屉** | DEF-A2/A3/A4(U-5 冻结) | SourceEditorDrawer.tsx | 无 | 无 | Wave 0A/0B;从 PREP_BASE_SHA 分支 |
| **C B1 产品域** | U-6/7/8/9/10/11/12/13(38 行中 22 行) | DataSourceDetail.tsx、新 KnowledgeSettingsDrawer、新 RiskPreviewModal、SourceEditorDrawer 入口 | data_sources.py、新 knowledge_settings/repair/preview 端点、连接器 content_type | DataSourceDetail.tsx(仅本轨);data_sources.py(仅本轨) | Wave 0A(IF-3/IF-4)+Wave 0B;从 PREP_BASE_SHA 分支 |
| **D 原因分类学** | U-14(TI-09、DS-P2-10) | Analytics 拆分后原因面板文件、DataSourceDetail banner 文案 | analytics.py classify 扩展、tech_answer_gaps.py 投影、gap_taxonomy.py | 拆分后趋零(文件内区域互斥见 IF-6 附录) | Wave 0A(IF-2)+Wave 0B;从 PREP_BASE_SHA 分支;D/E 实现依赖=NONE;D candidate 为 E joined 验收前置(§3.6) |
| **E 观察与导出** | U-15(TI-07/18/36/37/41/42/43)+U-16(TI-34/35/45) | Analytics 拆分后观察/导出/历史面板文件 | tech_observation.py、tech_export.py、gap_status.py、观察服务、导出服务 | 拆分后趋零 | Wave 0A(IF-1/IF-2/IF-5/IF-7)+Wave 0B;从 PREP_BASE_SHA 分支;**实现不等 D**;joined 验收需 D candidate(§3.6) |
| **F 证据聚合** | U-17(TI-27)+U-18(TI-33)+U-19(TI-12) | Analytics 拆分后 meta/源卡/主题列面板文件 | tech_evidence.py、conversations.session_id 聚合投影、topic 派生 | 拆分后趋零 | Wave 0A(IF-6/IF-7:U-17 聚合窗=所选分析窗)+Wave 0B;从 PREP_BASE_SHA 分支(U-17 证据:session_id 已存在) |
| **Integration(第七轨)** | Wave 0B 结构 prep 执行+PREP_BASE_SHA 冻结、合并核验(merge-base==PREP_BASE_SHA)、三门、全矩阵复核 | — | — | — | Wave 1 各轨 |

### 3.4 运行时验收数据要求(每轨)

- 数据仅限本地 docker PG(ask_ai/ask_ai),AUDIT-FIXTURE 标记隔离,SQL 全文记录入交付物。
- Track C 需 fixture:含需处理文档(可修复)、chunk 总数已知源(分数断言)、恢复事件、超期新鲜度源(提醒/过期态)、高风险变更源(预览计数非零)。
- Track D 需 fixture:每个新原因类至少 1 行真实分类证据(会话级证据可回放)。
- Track E 需 fixture:含 open cluster(进入观察)、同步成功事件钩子、观察期满/复现双路径、归属会话(导出内容比对)。
- Track F 需 fixture:含/不含 session_id 的历史会话(unavailable 断言)、多会话同簇(去重断言)、命中源证据(归因断言)。
- 生产验收(最终):生产栈只读复核+真实管理操作链,遵守 FINAL PASS 规则 §1。

### 3.5 TECHNICAL INSIGHTS WINDOW CAPABILITY MATRIX(U-2「语义适用处」具体化;冻结)

**审计性质**:只读仓库审计(READ-ONLY)。审计对象:rem worktree `/Users/harryhua/Documents/GitHub/ask-ai-v163-rem` @ **7e3e71c**(干净树,零改动);文件:`admin/src/pages/Analytics.tsx`(1416 行,当前 UI 全部 TI 读面消费点)、`admin/src/lib/api/techInsight.ts`(258 行,全部导出 fetch 函数逐个盘点)、`backend/api/admin/tech.py`(765 行)、`backend/api/admin/analytics.py`(coverage-gaps/gap-trends/source-health)、`backend/api/admin/sync_runs.py`(GET /sync-runs)、`admin/src/components/observability/TimeFilter.tsx`。

**冻结的分析窗词表(IF-7)**:`{今日 today, 近7天 7d, 近30天 30d, 全部 all, 显式起止 from/to}`;默认 近7天(SH-09 参考即「过去 7 天 2025-09-03→2025-09-09+日历」)。**单一共享窗状态**:SH-09 顶栏范围控件、TI-10 缺口工具栏窗选择、tech tab TimeFilter 为**同一窗状态的三个呈现面**(改动任一 → 整页窗口面真实联动);禁止任何窗口面卡片停留在与共享窗不一致的时间窗。

| # | Surface(当前 UI 消费) | Endpoint | 现有窗口/日期参数 | 现有语义 | 已支持(全词表)? | 所需变化 |
|---|---|---|---|---|---|---|
| S1 | 技术性能:KPI 三卡/阶段 P50/P95/趋势/异常/降级/健康横幅 | GET /tech/performance | `range= today/7d/30d` + `from`/`to` ISO(后端已备;前端 TimeFilter 的 from/to 当前被丢弃未发送) | [start,end] trace 聚合;上一等长窗作基线;响应带 kpi.window/from/to、trace_coverage_from、window 词表外值静默回退 7d | **YES** | 仅前端:共享窗状态接入(from/to 真实发送;all/任意窗以显式起止表达;**禁依赖 range 未知名→静默 7d 回退**) |
| S2 | 数据源健康卡(SourceHealthSummary,tech tab 内渲染) | GET /analytics/source-health | `days=1..365`(仅「近 N 天」);前端**硬编码 days=30**,不随任何窗状态 | 历史可靠性窗(DSH-01:signal=historical_reliability、MIN_SYNC_RUNS、window_days 显式回显;禁当当前态) | **PARTIAL** | 后端 **BC-2**:窗参数表达 IF-7 全词表(显式起止/all);前端:硬编码 30→绑定共享窗;DSH-01 语义原样;响应窗字段=实际评估窗(禁 silent fallback) |
| S3 | 同步级事件流(同步/索引/生成事件 区) | GET /sync-runs?status=failed\|interrupted&size=N | 无窗口参数(source_id/status/page/size) | 跨源最近 N 条终态信号(v1.6.2 #51 复用优先冻结读面) | **NO(例外冻结)** | 无后端改动;声明为例外面(理由见下) |
| S4 | 生成级事件流(同区) | GET /tech/generation-events | 无窗口参数(limit) | 最近 N 条 failed/retired(#51 唯一新增只读读面;event_at 诚实近似) | **NO(例外冻结)** | 无后端改动;声明为例外面 |
| S5 | 回答缺口队列(队列/过滤/miss_type_summary) | GET /tech/answer-gaps | `window=7d/30d/all`(pattern 锁死);last_seen 未知行永不被窗排除 | 窗只约束已知 last_seen;total=过滤后真值 | **PARTIAL** | 后端 **BC-1**:window 表达 IF-7 全词表(今日/显式起止);既有语义(last_seen 未知保留、total 真值)不变;前端:TI-10 窗选择绑定共享窗状态 |
| S6 | 缺口归属会话证据(诊断侧板 相关对话) | GET /tech/answer-gaps/{id}/conversations | 无窗口参数(limit) | gap 范围证据投影(最近在前;深链由 /conversations?q= 承担,#51 冻结参数语法) | **NO(例外冻结)** | 无后端改动;声明为例外面 |
| S7 | (未消费)coverage-gaps 旧读面 | GET /analytics/coverage-gaps | 无窗口参数(status/page/size) | 旧聚类列表;已被 /tech/answer-gaps 权威投影取代 | 非当前 UI 面 | 零要求;techInsight.ts 死导出,标记待清理;Wave 1 不得新增消费 |
| S8 | (未消费)gap-trends | GET /analytics/gap-trends | `days=1..365` | 按天未回答率时序 | 非当前 UI 面 | 零要求;同 S7 |

盘点口径:Analytics.tsx 实际消费的 fetch 函数共 6 个(S1–S6);fetchCoverageGaps/fetchGapTrends 为 techInsight.ts 导出但**零组件消费**(死导出)。跨页深链(/conversations?q=…、/conversations?failure=true)= 导航而非 TI 读面;各页既有 filter 真值零改动(U-2「非全站假全局过滤」即此义)。

**例外面冻结(3 项,理由随冻结)**:
- **S3/S4 事件流**:产品语义=「当前需要关注的最近异常信号」(latest-N 终态流),非时间窗聚合;行级 event_at/started_at 显式呈现,不存在窗口误读面;读面语义经 v1.6.2 #51 复用优先合同冻结;窗化反而会向查看历史窗的操作者隐藏最新 critical 信号(运维安全语义倒退)。故 U-2「语义适用处」在本两面不适用。
- **S6 会话证据**:gap 范围证据(随所选 gap 行),其时间语义=gap 自身 last_seen 跨度;独立开窗无意义;深链语义已由 /conversations?q= 承担。

**Outcome 冻结:Outcome B。** 理由:SH-09 参考要求显式起止日期(日历控件),S2/S5 以现有参数无法表达全词表 → 存在不支持的面。**Track A 不再是「零后端」;其精确后端范围冻结为(仅参数能力:零新表、零新端点、零既有窗口语义变化、不规定 HOW):**
- **BC-1**:`/tech/answer-gaps` 窗口参数表达 IF-7 全冻结词表(今日/显式起止;S5);
- **BC-2**:`/analytics/source-health` 窗口参数表达 IF-7 全冻结词表(显式起止/all;S2),DSH-01 语义原样保留。

验收钩子:S1/S2 响应窗字段=所选窗;S5 请求参数可见+行集=窗权威行集;三控制面任一改窗 → 整页窗口面真实联动(API 参数可见、无卡片停留异窗)。

**跨轨衔接**:Track F U-17 用户聚合「所选分析窗内」= 消费 IF-7 同一词表(tech_evidence.py 投影按共享窗过滤);Track E U-16 导出「所选 gap/query 范围」继承队列激活窗(含窗);Track D 分类与窗正交(分类结果不随窗变)。

### 3.6 D/E DEPENDENCY CONTRACT(冻结;终轮 review fix)

- **实现依赖:D → E = NONE。** Track E 与 Track D 同波并行开工(各自从 PREP_BASE_SHA 分支),E 独立实现 OBSERVING 状态机/转移持久化审计/History/导出/UI 状态/fixtures——全部依 **IF-2 分类词表冻结合同**(Wave 0A 冻结的词表+证据规则 ID),**不得等 D 开工,不得等 D 的任何代码**。
- **验收依赖:E 的 joined runtime FINAL PASS 需要 D candidate 存在。** D candidate = Track D 分支上 IF-2 的实际实现(词表+证据规则)达到 Track D 自身验收就绪态。E 必须对 **D 的实际词表实现**做联测,joined 分类/观察流全过:新原因类过滤 × 观察态共存、队列 chips/诊断分布/banner 同源一致、观察核验读到的分类=IF-2 实装真值。
- 即:**D/E = 并行实现 + D candidate → E joined acceptance gate。** E 的 solo 交付(观察/导出/历史)不因 D 延误而阻塞推进;仅 joined 验收门锚定 D candidate;D 须按合同及时移交 candidate。
- 旧表述「Track D 先行(分类稳定)」**废止**:分类稳定性由 IF-2 冻结合同在 Wave 0A 保证,不再以 D 开工顺序保证。

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

- **Wave 0A(docs only)**:IF-1..IF-7 合同冻结(含 U-2 分析窗能力矩阵 §3.5 Outcome B、IF-6 拆分地图+文件内区域所有权)。零代码。
- **Wave 0B(结构预备,Integration 轨执行)**:Analytics.tsx 按 tab/面板拆组件文件、tech.py 拆 router 子模块、gap_taxonomy.py/gap_status.py 词表常量模块落位(仅既有值迁移)(IF-6 物理落位);**四零约束**(零产品语义/零新业务行为/零 API 语义/零数据模型语义变化);验收=行为等价+pytest/vitest/tsc/build/ruff+既有 runtime smoke+零视觉/功能漂移;产出 **PREP_BASE_SHA**。
- **Wave 1(全并行,六轨)**:A、B、C、D、E、F 各自独立分支+独立合同,**全部从同一 PREP_BASE_SHA 分支(禁止混合基线)**;D/E 实现零依赖并行(§3.6);文件互斥由 §3.2 拆分地图+文件内区域所有权保证。
- **Wave 2(Integration 轨)**:**D candidate → E joined acceptance gate(§3.6)**;backend 合并序 D→E→F(拆分到位后冲突面趋零);frontend 合并序 D→E→F→C→B→A;统一三门+全矩阵 152 行复核+FINAL PASS 判定。

### 6.2 各轨 B 级提示词要点(自包含;启动实现时逐轨下发)

**Track A(`track/v163-a-chrome`;worktree:实现授权树;**分支基线=PREP_BASE_SHA,强制共同基线,禁止混合基线**;branch `track/v163-a-chrome`)**
- 冻结合同:docs/engineering/tasks/v163-reference-remediation/track-a-contract.md(+IF-6/IF-7 附录)
- 范围:SH-06(DEF-A1 系统 分组);SH-09(GAP-SC-1,U-2:顶栏日期范围控件+单一共享分析窗状态+三控制面绑定+窗口面真实联动;语义适用处具体化=§3.5 能力矩阵,**Outcome B:BC-1 `/tech/answer-gaps` 窗参数全词表 + BC-2 `/analytics/source-health` 窗参数全词表,仅参数能力**);SH-12(GAP-SC-3,U-4:纯 Admin shell 折叠,零后端);SH-10/11 按 UADC-4 记录缺席,不实现。
- 验收:vitest 组标签/折叠/范围联动断言;BC-1/BC-2 pytest 参数能力用例(全词表×既有窗口语义回归);真实折叠-展开+范围切换截图(1536×1024@1x);对照 PNG2;#52 导航清单修订记录。
- 禁止捷径:不得发明全站全局过滤语义;不得改动各页内既有 filter 真值;frontend-only fake state 禁止(范围必须真实贯通 API 参数);**不得让任何窗口面卡片停留异窗;S3/S4/S6 例外面不得借例外引入窗口假联动;BC-1/BC-2 禁借机新增端点/新表/改既有语义**。

**Track B(`track/v163-b-drawer`;worktree:实现授权树;**分支基线=PREP_BASE_SHA**;branch `track/v163-b-drawer`)**
- 冻结合同:track-b-contract.md
- 范围:DS-P5-02(名称* label)、DS-P5-04(U-5:edit 禁用/create 可选)、DS-P5-05(自动同步 toggle+说明)。零后端、零 PUT 语义变更。
- 验收:vitest label/toggle/disabled;toggle→保存→PUT enabled 真实生效;截图对照 PNG1 面板5。
- 禁止捷径:CSS 伪装 disabled、改 PUT payload、删新建态类型选择。

**Track C(`track/v163-c-b1-product`;worktree:实现授权树;**分支基线=PREP_BASE_SHA**;branch `track/v163-c-b1-product`)**
- 冻结合同:track-c-contract.md(+IF-3/IF-4 附录)
- 范围:U-6(品牌内建映射)、U-7(content_type connector 所有)、U-8(真实修复工作流:RBAC/幂等/可审计/进度/修复后验证)、U-9(serving 投影,UI 比例=后端真值)、U-10(持久化恢复事件)、U-11(scheduler next_run_at,禁纯派生)、U-12(知识设置:CURRENT/HISTORICAL 资格层+新鲜度政策,不重设计 lifecycle)、U-13(预览:计数后端权威+确认施加完全一致 mutation)。
- 验收:功能 E2E 四链(修复链/知识设置-预览-确认链/新鲜度提醒链/倒计时链)+三角(API=PG=UI)+pytest/vitest/tsc/build;截图面板2/3/4/6/7。
- 禁止捷径:前端算影响计数、修复绕过幂等/审计、资格语义只存不用、UI-only repair、fake next_run_at、fake counts。

**Track D(`track/v163-d-taxonomy`;worktree:实现授权树;**分支基线=PREP_BASE_SHA**;branch `track/v163-d-taxonomy`)**
- 冻结合同:track-d-contract.md(+IF-2 附录)
- 范围:U-14(TI-09 六新类+证据规则;DS-P2-10 banner 文案)。旧 4 类回归零破坏。
- 验收:每新词≥1 行真实分类证据(fixture 经真实 DB→API→UI);过滤=权威行集;诊断分布一致;pytest/vitest;**candidate 及时移交(E joined acceptance 前置,§3.6)**。
- 禁止捷径:keyword-only 前端分类、无证据规则分类上线、映射近义词。

**Track E(`track/v163-e-observation`;worktree:实现授权树;**分支基线=PREP_BASE_SHA**;branch `track/v163-e-observation`)**
- 冻结合同:track-e-contract.md(+IF-1/IF-2/IF-5 附录)
- 范围:U-15(OPEN→OBSERVING→RESOLVED 全状态机:进入=操作者确认+sync/reindex 成功+post-sync 验证成功;7 天观察窗;复现→OPEN;满窗→RESOLVED;中止→OPEN;禁强转 RESOLVED;转移持久化/带时间戳/可审计/History 可见)+U-16(admin-only 导出;最小字段;排除直接个人身份;可审计;CSV=所选范围,继承队列激活窗 IF-7)。**实现依 IF-2 冻结合同,不等 D(§3.6:实现依赖 D→E=NONE)**。
- 验收:E2E 观察双路径(期满/复现)+中止+导出内容=所选范围权威数据+无隐私字段+审计行;pytest/vitest/tsc/build;**joined runtime FINAL PASS 需 D candidate:对 D 实际词表实现联测,joined 分类/观察流全过(§3.6)**。
- 禁止捷径:跳过同步核验进观察、unpersisted OBSERVING transitions、前端造 CSV、export 由当前渲染行构建、无流转记录的经观察转 RESOLVED。

**Track F(`track/v163-f-evidence`;worktree:实现授权树;**分支基线=PREP_BASE_SHA**;branch `track/v163-f-evidence`)**
- 冻结合同:track-f-contract.md(+IF-6 消费;IF-7:U-17 聚合窗=所选分析窗,词表见 §3.5)
- 范围:U-17(去重伪匿名会话计数;session_id;历史 NULL→unavailable)、U-18(归因源自证据/对话/检索真值)、U-19(主题确定性派生优先;LLM 仅另行授权)。
- 验收:三角去重计数;归因外链真实到达且规则可解释;主题稳定(同簇多次拉取不变);隐私聚合无 PII;pytest/vitest。
- 禁止捷径:fake user count、无证据规则归因、hard-coded topic labels、前端估算用户数、LLM 主题未授权上线。

### 6.3 并行组/依赖序/integration 归属

- 并行组:Wave 1 六轨全并行,共同基线 PREP_BASE_SHA(B 零后端最快闭环;A 含 BC-1/BC-2 参数能力;C/D/E/F 由 IF-6 拆分+文件内区域所有权保证文件互斥)。
- 依赖序:**Wave 0A(IF-1..IF-7 冻结)→ Wave 0B(结构预备)→ PREP_BASE_SHA 冻结 → Wave 1(A–F 并行;D/E 实现零依赖,§3.6)→ D candidate → E joined acceptance gate → Integration 合并(backend D→E→F;frontend D→E→F→C→B→A)→ 三门+全矩阵复核 → FINAL PASS 判定。**
- Integration 归属:第七轨(Integration)拥有 Wave 0B 结构 prep 执行与 PREP_BASE_SHA 冻结、合并仲裁(含 merge-base==PREP_BASE_SHA 核验)、全矩阵复核与 FINAL PASS 报告;各轨拥有自己的分支/合同/交付物。

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
- **IMPLEMENTATION_AUTHORIZED = YES(条件生效)**:授权依据=本授权包+六轨冻结合同+IF-1..IF-7;实现启动须按 **Wave 0A→Wave 0B(PREP_BASE_SHA 冻结)→Wave 1(六轨自 PREP_BASE_SHA 分支;D candidate→E joined gate)→Wave 2** 顺序,且各轨不得越合同边界。**本 planning 任务本身不启动实现。**

## 7. 冻结合同

每 Track 合同见 `v163-reference-remediation/track-{a..f}-contract.md`(冻结目标/参考需求/产品语义/变更边界/后端数据要求/前端要求/禁止捷径/验收/运行时状态/视觉证据/功能 E2E/交付物;不规定 HOW)。

## 8. CONSISTENCY AUDIT(终轮 review fix 后全量核验;docs-only;**FINAL PLANNING BASELINE FIX 2026-09-13 增补 12–14**)

核验方式:全量重读本 plan + 六轨合同 + gap-register + matrix-SH/TI 相关节,逐点交叉比对下列位置文本;核验后无遗留矛盾。

| # | 核验点 | 核验位置 | 结果 |
|---|---|---|---|
| 1 | Wave 0A = docs/接口冻结 only | §3.0(零代码/零结构拆分声明);§6.1 Wave 0A;IF-1..IF-7 全冻结 | PASS |
| 2 | Wave 0B = 结构代码预备 only | §3.0.1(允许清单=四项结构 refactor;禁止清单;四零约束;行为等价+五门验收);§6.1 Wave 0B | PASS |
| 3 | PREP_BASE_SHA = A–F 强制共同基线 | §3.0.3(定义/强制规则/合并核验);§3.1 拓扑;§3.3 全部前置列;§6.1/§6.2/§6.3;track-a..f 合同 前置+B 提示词要点 | PASS |
| 4 | Wave 1 A–F 并行实现 | §3.1;§3.3;§6.1;§6.3 并行组 | PASS |
| 5 | D/E 无开工依赖 | §3.6(实现依赖 D→E=NONE);§3.3 D/E 行;§6.2 D/E 提示词;track-d/track-e 合同 前置 | PASS |
| 6 | D candidate 为 E joined acceptance 前置 | §3.6;§3.1 Wave 2;§3.3 E 行;§6.2 D/E 提示词;track-e 合同 验收/前置;track-d 合同 前置 | PASS |
| 7 | Track A 后端范围与 U-2 能力矩阵一致 | §3.5(Outcome B:BC-1/BC-2+S3/S4/S6 例外+IF-7 词表);§3.1/§3.3 A 行;§6.2 A 提示词;track-a 合同 后端数据要求;gap-register GAP-SC-1;matrix-SH SH-09;主审计文档 U-2 行指针 | PASS |
| 8 | 无合同同时写「零后端」与「需后端改动」 | track-a:零后端仅限 U-4,SH-09=Outcome B(不再「零后端」);track-b:真零后端;track-c/d/e/f 各自后端表述一致;plan §3.1/§6.3 措辞已同步 | PASS |
| 9 | 无占位接口语义残留 | IF-1..IF-7 全部有冻结内容+消费方;BC-1/BC-2 语义冻结(HOW 不规定);PREP_BASE_SHA 待填值=执行期字段非接口占位 | PASS |
| 10 | 未决产品决策=0 | §5 U-1..U-19 全冻结;§6.6;主审计文档 ROLE A DECISIONS 章节;本轮零改判 | PASS |
| 11 | 未决参考冲突=0 | §1 规则 4(SH-16 经 U-1 → MATCH);§6.6 分类 RC 0 | PASS |
| 12 | **WAVE_0B_BASE_SHA=7e3e71c 冻结且为 Wave 0B 唯一实现基线** | §3.0.2(规则 1–5:直接分支/merge-base 核验/仅结构 refactor diff);§3.1 拓扑 Wave 0B 行;本轮零产品语义变更核对 | PASS |
| 13 | **planning b054d9f=合同证据、非实现父;origin/main 5c50191=非合法 Wave 0B 基线** | §3.0.2 规则 2–3;§3.0.3 实现父链;track-a..f 合同 前置行(基线措辞已同步) | PASS |
| 14 | **Wave 0B 必须保全 7e3e71c 全部 MATCH/UADC 行为;Integration 拒绝祖先不含 PREP_BASE_SHA 的 Track** | §3.0.2 规则 4 与规则 8;§3.0.3 合并核验 | PASS |
