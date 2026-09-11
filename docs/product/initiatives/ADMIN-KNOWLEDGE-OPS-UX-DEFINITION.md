# ADMIN KNOWLEDGE OPERATIONS — Product & UX Definition

- 日期:2026-09-11
- 性质:**产品/UX 定义**(本文只定义语义、信息架构、旅程与线框规格;零实现,零运行时行为变更,零生产触碰)
- 事实源:`discovery/knowledge-freshness-20260911 @ e94a673`(KNOWLEDGE-FRESHNESS-RETRIEVAL-INTEGRITY-DISCOVERY.md)+ Product Review 裁决 D-1..D-7(已回填为 DECIDED,含 D-6 修正)+ 评审指示 A-1(正交状态建模)
- 落点说明:仓库产品文档根为 `docs/product/`(VISION/ROADMAP/STATE;`architecture/`=目标架构;`iterations/`=迭代级规格)。跨迭代的 initiative 级产品定义按任务建议入 `docs/product/initiatives/`,与既有分层互补;工程侧 discovery 仍在 `docs/engineering/discovery/`。

---

## 1. 范围与设计纪律

**回答的产品命题(验收十问的出处)**:一个 Product Owner 不理解 Weaviate/embedding/chunk/RAG 调参,也能回答——知识现在健康吗?哪些源陈旧或坏了?三方计数是否一致?最近变了什么?哪些文档失败、为什么?引用还可点吗?某文档为何有资格作答?系统自动修了什么?什么真正需要人?能否安全恢复/对账?

**设计纪律(承 Discovery P1-P3 + Admin 既有惯例)**
- K1 全部语义用运营词汇(来源/文档/版本/新鲜/生效),技术细节只进可折叠"技术证据"区(沿用 SyncStatusPanel `<details>` 惯例);
- K2 红=当前态失败、黄=降级/风险、灰=信息/历史——沿用 DataSources 页"历史低成功率刻意不用红色"的分层纪律(admin/src/pages/DataSources.tsx:224-230);
- K3 查询失败永不渲染成空表/零 KPI(沿用 LoadError 契约,admin/src/components/LoadError.tsx);
- K4 破坏性动作前置证据 + 两步确认(原生 `window.confirm` 在内嵌浏览器会被吞——ProviderCredentialDialog.tsx:37 已有教训,本文一律规定 in-UI 确认);
- K5 异步动作用"已受理/后台进行中"toast 语义(沿用 useDataSources 惯例);
- K6 不暴露任何低层 RAG 调参(见 §7E)。

---

## 2. 状态模型(权威定义;取代 Discovery §4A 单一枚举,执行评审指示 A-1)

四条**正交状态轴**,各自独立演化,禁止组合成单一 enum:

| 轴 | 状态 | 语义 | 归属层 |
|---|---|---|---|
| **L 文档生命周期** | DISCOVERED / ACTIVE / SUPERSEDED / MISSING_CANDIDATE / DELETED | 知识逻辑存在性与接替关系(DELETED=墓碑,保留元数据+版本链至 GC) | Postgres(账本真相) |
| **R 源可达性** | REACHABLE / UNREACHABLE / PROBE_FAILED | 外部源当前是否可枚举/可取——**源级属性,向下投影到其文档**;UNREACHABLE 时文档保持上一代服务,绝不触发删除 | Policy Engine+探针 |
| **P 处理/索引生成** | PENDING / PROCESSING / READY / FAILED / RETIRED | 每个版本 generations 的处理状态;`active_generation` 指针决定服务代 | Index Generation Manager |
| **F 新鲜度** | FRESH / STALE / OVERDUE / UNKNOWN / ARCHIVE | 相对**每源 SLA 策略**的时间状态,锚=source_verified_at;ARCHIVE=策略声明不适用(历史档案类源) | Policy Engine |

**派生规则(不存储,呈现时计算)**
- 检索资格 `eligible` = (L=ACTIVE) ∧ (源 enabled) ∧ (active generation P=READY)。UNREACHABLE 不取消资格(保上一代),只降 F;
- D-4 硬门:价格/明确现势断言在 F=OVERDUE 的 CURRENT 证据上被拒——这是唯一把 F 变成门的场景,其余 F 只标记/降权;
- 呈现态徽章 = 四轴各自渲染一行小徽章(不合并);健康总评 = 派生(§4A 规则)。
- 合法混合态示例(正交建模的价值):`ACTIVE × UNREACHABLE × FRESH`(源暂时挂但内容刚验证过,正常服务)、`SUPERSEDED × READY`(旧版本向量保留供回滚)、`MISSING_CANDIDATE × OVERDUE`(连续缺席+过期,临近墓碑)。

**标签词汇与 Badge variant 映射(复用 admin Badge 变体集:success/warning/destructive/secondary/outline)**

| 轴.状态 | 中文标签 | variant |
|---|---|---|
| L DISCOVERED / ACTIVE / SUPERSEDED / MISSING_CANDIDATE / DELETED | 待灌入 / 生效中 / 已接替 / 缺失候选 / 已删除 | secondary / success / outline / warning / outline |
| R REACHABLE / UNREACHABLE / PROBE_FAILED | 可达 / 不可达 / 探测失败 | success / destructive / warning |
| P PENDING / PROCESSING / READY / FAILED / RETIRED | 待处理 / 处理中 / 就绪 / 失败 / 已退役 | secondary / warning / success / destructive / outline |
| F FRESH / STALE / OVERDUE / UNKNOWN / ARCHIVE | 新鲜 / 过期 / 严重过期 / 未知 / 归档 | success / warning / destructive / outline / secondary |

authority/temporal role(CURRENT/HISTORICAL/SUPERSEDED/INVALID)= 每源策略属性(D-6:policy 决定,filesystem 无默认),呈现为普通 Badge(current→success、historical→outline+日期框定提示、superseded→secondary、invalid→destructive),不进四轴(它是分类不是状态)。

---

## 3. 信息架构(IA)

现有侧栏两组:运营(业务概览/销售线索/对话审查/技术洞察)、配置(数据源/对话接入/模型配置/答案覆盖/Widget/用户/系统)。**新增一组**:

```
知识(KNOWLEDGE_ITEMS,新组,置于"运营"与"配置"之间)
  /knowledge            知识总览      (Area A;icon: BookOpen)
  /knowledge/issues     知识问题      (Area D;icon: ShieldAlert;含角标计数)
  /knowledge/settings   知识策略      (Area E 全局默认;icon: SlidersHorizontal)
既有 /data-sources 数据源       (Area B——就地增强,不迁移不换名)
面板:Document Inspector(Area C——master-detail 侧栏面板+深链,非新路由,沿用对话审查模式)
```

- 选中即过滤深链沿用 `useSearchParams` 惯例:`/knowledge/issues?class=citation&severity=s1`、`/data-sources?source=xxx`;
- Document Inspector 深链:`/knowledge/issues?doc=<source_id>` 或 `/data-sources?doc=<source_id>` 打开面板(同对话审查的 query-param 驱动);
- RBAC:沿用 canWrite(admin/editor 可写):查看全员;同步/重试/编辑策略=editor+;保留 GC/时态覆盖/整源重灌/禁用源=admin(与用户管理同级谨慎度);
- 角标:侧栏"知识问题"项右侧 `S1` 计数徽章(0 不显示),数据=问题中心聚合,5s 轮询仅在有活动同步/处理时(沿用 DataSources 条件轮询惯例)。

---

## 4. 产品区域定义

### Area A — Knowledge Overview(/knowledge)

回答十问之 Q1/Q3/Q4/Q6。布局自上而下(全部复用既有组件语汇):

```
┌ ServiceHealthBanner 型总横幅(复用 observability/ServiceHealthBanner 模式)──────────┐
│ ● 知识健康:健康 / 降级 / 需处理            窗口:最近对账 2026-09-11 08:00 · 全部 6 源  │
│ 理由行(如"1 源严重过期 · 3 条失效引用 · 三方差异 2 文档")   [查看问题 →]              │
└──────────────────────────────────────────────────────────────────┘
┌ KpiCard ×4(复用 KpiCard tone 语义,脚注必带分子/分母)────────────────────────────┐
│ [三方对账] expected 1,204 · ledger 1,204 · indexed 1,202  tone=warning 差2   →明细    │
│ [新鲜度] FRESH 1,102 / STALE 86 / OVERDUE 12 / UNKNOWN 4    tone=warning    →按源    │
│ [引用健康] VALID 96% · INVALID 14 · UNREACHABLE 31          tone=ok        →引用问题  │
│ [需关注] S1×3 · S2×11(队列计数)                              tone=critical  →问题中心 │
└──────────────────────────────────────────────────────────────────┘
┌ 最近语料变更(表:时间/来源/文档/变更类型[新增|更新|接替|删除|失败]/触发方式)≤20 行 ──┤
┌ 源健康热力条(每源一格:名称+四轴微徽章+健康点,点击深链 /data-sources?source=)────────┤
```

- 总横幅判定规则(前端纯呈现,后端给事实):S1>0 → 需处理(destructive);否则三方差异>0 或 OVERDUE>0 或 INVALID>0 → 降级(warning);否则健康(ok);无对账数据 → 证据不足(outline)。理由行必须列具体计数(沿用 ServiceHealthBanner reasons 模式)。
- 三方对账 KPI 即 Discovery §6 不变量报告的呈现:`inventory_expected == ledger_active == indexed_active`,差异行给出 **按源/按文档可点击明细**(不是裸百分比——KpiCard 契约)。

### Area B — Sources(/data-sources 就地增强)

保留现有 8 列表与展开行模式,增量:

1. 列调整:`同步间隔` 列升级为 **节奏/SLA** 双值(`24h · SLA 24h`,SLA 超期整格染 warn 色);新增 `文档` 列(`expected/ledger/indexed`,差异时数字染 warn + title 提示);`最新同步` 列旁新增对账时间(`对账 08:00`,失败染红)。
2. 展开行(SOURCE_OBSERVABILITY_DETAILS 模式)增两面板:
   - **对账历史**(新,复用 SyncHistoryPanel 骨架):每轮 `INVENTORY→DIFF` 结果卡(完整/不完整、new/updated/unchanged/missing、墓碑决定、UNREACHABLE 事件);
   - **源策略面板**(见 §7E 抽屉规格,只读摘要在此)。
3. 行操作增:`对账`(仅验证不重嵌)、`策略`(打开策略抽屉);现有 同步/编辑/删除/重试删除 保留,语义不变。
4. 源健康卡(SourceHealthPanel 五维)升级:新鲜度维改为 SLA 相对状态(FRESH/STALE/OVERDUE/UNKNOWN/ARCHIVE),一致性维链接到三方明细。

### Area C — Document Inspector(文档检查器,侧栏面板)

打开方式:问题行"查看文档"、源展开行文档数、总览变更行、深链 query。布局复用对话审查 master-detail 右侧面板:

```
┌ 文档检查器(右面板 flex-1 rounded-lg border bg-card p-4)───────────────────────┐
│ 标题:文档标题                                        [关闭]                        │
│ 身份区:source_id(font-mono text-xs break-all)· 源类型 Badge · 产品线            │
│ 状态区:四轴徽章行  [生效中][可达][就绪·gen#7][新鲜]  + 时态角色 [CURRENT]         │
│ 资格行:检索资格 ✅ 有资格作答 / ❌ 无资格——原因(哪条轴不满足,人话)             │
│ ├ 版本history表:seq / 内容哈希(短) / 源版本(git sha·lastmod·date_modified)      │
│ │               / 生效起止 / 接替者 / 状态徽章 — 当前版本行高亮                     │
│ ├ 当前索引生成:gen#7 READY(服务中)· gen#6 RETIRED(保留至 10-11)· gen#8 FAILED   │
│ ├ 引用与链接:canonical URL(可点)+ 有效性徽章 VALID/REDIRECTED/…/最后探活时间     │
│ │             provenance URL(折叠)                                                │
│ ├ 别名/改名链:v1 hailo_ipc_sdk/… ──09-08──► v2 neoruntime_ipc_sdk/…  [撤销接链](admin)│
│ └ 诊断证据(可折叠 details):最近 DocFailure、对账缺席轮数、探针记录、chunk/哈希计数  │
│ 面板底部操作条:重试灌入(FAILED 时)· 重新验证引用 · 标记接替/解除(admin)· 对账此文档 │
└──────────────────────────────────────────────────────────────────┘
```

十问之 Q7("为何有资格")由**资格行**直接回答:逐轴列出 满足/不满足 + 人话原因(如"无资格:该文档为 DELETED 墓碑,且无接替版本");技术细节(hashes、generation id、chunk 计数)全部收进诊断证据折叠区。

### Area D — Knowledge Issues(/knowledge/issues)

问题中心 = 八类问题的统一队列。页首类目 ToggleFilter chips(复用,带计数);表列:严重度 / 类别 / 对象(源或文档,可点开 Inspector)/ 摘要 / 系统已自动做 / 需要你做什么 / 首次发现。深度过滤:severity、source、time(deep-link params)。

**八类问题契约表**(每类:发生了什么/严重度/系统自动行为/是否需人/允许动作/破坏前必呈证据):

| # | 类别 | 发生了什么 | 严重度 | 系统自动行为 | 需人? | 允许的管理动作 | 破坏/人工动作前必呈证据 |
|---|---|---|---|---|---|---|---|
| 1 | 过期/陈旧 | 源或文档超过 SLA(F=STALE/OVERDUE)或从未验证(UNKNOWN) | OVERDUE=S1(价格类)/S2;STALE=S2;UNKNOWN=S2 | 按节奏自动重同步;OVERDUE 触发探针;价格类现势断言被硬门(D-4) | 节奏内不需;持续 OVERDUE 需查源 | 编辑节奏/SLA;立即对账;查看文档 | 源最近成功验证时间、连续失败次数、探针结果 |
| 2 | 灌入失败 | 文档级 DocFailure(#45 契约:stage/分类/可重试) | S1(可重试耗尽后)/S2 | 分类内自动重试(413 类永久失败不重试) | 是(永久失败或重试耗尽) | 重试此文档;查看 Inspector;编辑源配置 | 失败 stage+分类+原始错误、历史尝试计数、上一代状态 |
| 3 | 缺失候选 | 完整清单中文档缺席(连续 N 轮) | S2 | 计缺席轮数;宽限期内保上一代服务;满足条件自动墓碑(AUTO+AUDIT) | 仅当对自动墓碑有异议 | 保留(撤销候选);立即墓碑;查看对账证据 | 缺席轮数、清单完整性证据、探针结果、当前是否仍在服务 |
| 4 | 已删除/已接替 | 墓碑生效或版本被新版本接替 | S3(信息) | 墓碑保留 30 天(D-3)后 AUTO GC;接替链自动建 | 否(默认) | GC 前撤销墓碑/恢复版本(admin);立即 GC | 版本链、接替者、GC 倒计时、影响 chunk 数 |
| 5 | 索引不一致/孤儿 | 三方计数差异:缺失 chunk/孤儿向量/RETIRED 残留 | S2(差异=1 文档)~S1(批量) | 只读发现;complete 清单据下 AUTO 修复(refill/retire);不确定必 KEEP+REPORT | 批量或反复出现时 | 定向 refill;查看三方明细;触发对账 | 差异清单(哪些 source_id/chunk)、对账轮完整性与时间 |
| 6 | 失效引用 | 探活 404/超时(UNREACHABLE/INVALID)或别名给出新址(MOVED) | S2(UNREACHABLE/INVALID);S3(MOVED/REDIRECTED 已自动改写) | REDIRECTED/MOVED AUTO 改写 canonical;UNREACHABLE 重探退避;INVALID 默认标记不排除(D-4 语义外) | INVALID 的"是否从证据排除"策略变更需人 | 改写 URL;标记排除/恢复;立即复验;别名裁决 | 探活历史(时间/状态码)、别名候选、该引用被哪些答案使用(近 30 天) |
| 7 | 重复/冲突 | 跨路径同内容簇;跨 authority 同事实冲突 | S3(重复)/S2(冲突) | 重复簇 AUTO collapse 引用(选 authority 高者,记录在案) | 冲突需人裁;重复不需 | 冲突裁决(指定权威源);合并/拆分簇(admin) | 簇成员清单、各自 source/authority/最后验证、引用选择历史 |
| 8 | 歧义别名 | 改名/改链无法唯一映射(多候选或无候选) | S2 | 不自动接链,挂起等裁决(唯一默认 ADMIN DECISION 类) | **是** | 人工选定映射或标记无解 | 新旧身份两侧证据、候选清单含相似度依据、影响引用数 |

### Area E — Configuration(知识策略)

两层:**每源策略抽屉**(Sources 行"策略"打开,Drawer=右滑面板,复用 Dialog 原语侧位变体)+ **全局默认**(/knowledge/settings)。

可暴露(仅运营语义):

| 配置 | 层级 | 控件 | 默认 |
|---|---|---|---|
| 同步节奏 cadence | 源 | select(1h/6h/12h/24h/72h/手动) | 沿用源现状(24h) |
| 新鲜度 SLA | 源 | select + "≈2×节奏"快捷 | 2×cadence |
| 时态角色 temporal role | 源 | select(CURRENT/HISTORICAL/ARCHIVE 源级)| **无默认,必选(D-6)**;fs 源同样手配 |
| 对账宽限 | 源 | 数字(缺席轮数 N,1-7) | 2 |
| 引用校验 | 全局+源 | 开关 + 失效策略(标记/排除)| 开;标记 |
| 保留/GC | 全局 | 天数(墓碑/旧版本/RETIRED 代,分列)| 30/30/30 |
| 源启停 | 源 | 沿用现 Badge 点击切换 | — |

**明令不暴露**(K6,与 Discovery §10 一致):chunk 大小/重叠、embedding 模型与批量参数、hybrid alpha、RRF k、rerank 阈值与 chunk_type 权重、boost bucket 构成、pruner 阈值、Weaviate 原生参数。理由:无运维语义,归 benchmark_v1 质量治理;运维面出现这些只会诱发无据改动。

---

## 5. Automation Policy(AUTO / AUTO+AUDIT / ADMIN DECISION)

判定准则:**确定性维护 → 自动;语义歧义或破坏性知识判断 → 人。**

| 级别 | 判据 | 操作清单 |
|---|---|---|
| **AUTO**(静默) | 结果确定性可验证、可逆或 GC 到期 | content-hash 短路;版本接替链;生成验证通过后激活;RETIRED 代/到期墓碑 GC;complete 清单据下的孤儿 retire/refill;REDIRECTED 跟随改写 |
| **AUTO+AUDIT**(自动但必须留痕可撤销) | 影响服务内容或删除语义,但有客观证据链 | 墓碑生效(完整清单×N+探针);别名自动接链(D-5);UNREACHABLE 判定与恢复;重复簇引用 collapse;UNCHANGE 跳过嵌入的账本记录 |
| **ADMIN DECISION**(必须人) | 语义歧义、跨源知识冲突、破坏性或策略越权 | 歧义别名裁决;重复冲突的权威裁决;INVALID 引用排除策略;禁用源;整源重灌;GC 立即执行;时态角色覆盖(D-6);删除源 |

UI 呈现:问题行"系统已自动做"列即 AUTO+AUDIT 的审计出口(点击展开证据);AUTO 本身不入问题队列,只进"最近语料变更"信息流;所有 ADMIN DECISION 入口在无 S1 竞争时才可点(避免处理中并发)。

---

## 6. 用户旅程(五条主旅程)

1. **晨检(PO,2 分钟)**:开 `/knowledge` → 横幅绿:扫一眼变更流关页;横幅黄/红:看理由行 → 点进问题中心对应过滤 → 逐条处置或派发。
2. **源处置**:总览热力条红格 → `/data-sources?source=x` → 健康卡看新鲜度维 → 编辑节奏/SLA 或 `对账` → 对账历史卡确认收敛。
3. **文档追查**:问题行 → Document Inspector → 资格行看"为何无资格" → 重试灌入/查看版本链 → 折叠区核对技术证据。
4. **引用修复**:引用问题过滤 → INVALID 行 → Inspector 看探活历史与别名候选 → 确认映射(或标记无解)→ `重新验证引用` → 徽章转 VALID。
5. **安全恢复(对账)**:三方差异 KPI → 明细(按源)→ `对账此源`(仅验证)→ 差异清单 → 定向 refill(前置证据:差异清单+对账完整性)→ 复核 KPI 归零。全程无 Weaviate/chunk 词汇出现在动作文案(K1)。

---

## 7. UX 规格

### 7A. 组件复用与新增

复用(零新增语义):Badge 五变体、Button 变体、Card、Table+展开行、KpiCard(tone + 脚注契约)、ServiceHealthBanner(总横幅)、ToggleFilter(类目 chips)、TimeFilter、LoadError(compact 变体用于轮询失败保旧数据)、Pagination、sonner toast(受理语义)、`<details>` 技术证据折叠、native select、master-detail 面板模式(对话审查)、data-* 测试锚惯例(新增 `data-axis-*`、`data-issue-class`、`data-severity`)。
新增(均为既有原语组合):`StateBadgeGroup`(四轴徽章行,纯组合)、`IssueRow`(表行,含"系统已自动做"弹出证据)、`PolicyDrawer`(Dialog 侧位变体+表单区惯例 grid-cols-2/space-y-1/border-t)、`ConfirmPanel`(见 7D)、`CountBadge`(侧栏角标)。
沿用"缺省不做":不引入排序表格、Tooltip 组件、i18n、Tabs 组件、路由级详情页(与现状一致,避免先行扩库)。

### 7B. 状态语义(页面四态)

| 态 | 规格 |
|---|---|
| Loading | 首载 `加载中…` 文本(现状惯例;Skeleton 原语存在但页面未用,不破例);轮询失败=旧数据+LoadError compact 顶条 |
| Empty | 双文案区分"从无数据"与"过滤无命中"(沿用 Conversations data-empty-state 惯例);总览无对账数据=横幅"证据不足"+引导触发首次对账 |
| Degraded | 部分源 UNREACHABLE/探针失败:横幅降级+理由行;KPI 分母缺失时脚注显式"N 源未参与" |
| Error | LoadError(role=alert,重试按钮);mutation 失败 sonner toast;401/403 走全局契约 |

### 7C. 深钻关系图

```
Overview 横幅/KPI ──► Issues(按类过滤)──► Inspector(文档面板)
        │                     │                   │
        └─ 热力条 ──► Sources 展开行 ──► 对账历史/策略抽屉 ──► Inspector
                                     └──────────► 全局策略 /knowledge/settings
Inspector 引用区 ──► 对话审查(/conversations?q=)近 30 天引用使用(六号问题证据链)
```

### 7D. 破坏性动作确认行为

统一 `ConfirmPanel`(in-UI,弃 window.confirm——内嵌浏览器吞原生确认,ProviderCredentialDialog 实证):
- 两步:主按钮第一次点 → 面板展开后果行 + 「确认执行」变 destructive;再点才发;
- 前置证据区(按 §4D 表"破坏前必呈证据"逐类渲染,不可折叠跳过);
- 高危三动作(`整源重灌`、`立即 GC`、`禁用源`)加**输入源名确认**(type-to-confirm);
- 全部异步动作后 toast「已受理,后台进行中」+ 行内状态徽章转 PROCESSING(5s 条件轮询既有惯例)。

### 7E. 策略抽屉线框(Sources 行内)

```
┌ 策略:<source-name> ────────────────────────────[×] ┐
│ 同步节奏   [24h ▾]      新鲜度 SLA  [48h ▾](≈2×节奏)│
│ 时态角色   [CURRENT ▾]  ※改动影响引用形态,需 admin  │
│ 对账宽限   [2 轮 ▾]     引用校验  [✓] 失效策略[标记▾] │
│ ──────────────────────────────────────────────── │
│ ▸ 高级(保留/GC 覆盖、探针退避——admin)              │
│                    [取消]  [保存](受理 toast)      │
└─────────────────────────────────────────────────┘
```

### 7F. 页面线框(信息密度关键三张)

Overview/A/Issues/D/Inspector/C 的线框已在 §4 各区给出(ASCII 即实现规格:容器层级、栅格、组件名、Badge variant、数据锚),此处不重复。补充全局:页面骨架一律 `space-y-6 p-4 md:p-6` + `h1 text-2xl font-bold` + 右侧动作按钮行(DataSources 惯例)。

### 7G. 原型决策

**不建独立 HTML 原型。** 判断依据:十问均可由本文线框+组件映射+状态表作答,且全部 UI 元素是既有组件的组合(无新视觉语言需要验证);若 Product 评审后仍需视觉验证,再以**隔离静态页**(admin 仓外独立 artifact,不进构建)补做——列为可选后续,非本任务范围。

---

## 8. 验收十问 → 设计映射

| # | 问题 | 回答面 |
|---|---|---|
| 1 | 知识现在健康吗? | Overview 总横幅 + 理由行(判定规则 §4A) |
| 2 | 哪些源陈旧/坏了? | 热力条 + Sources 新鲜度/节奏列 + Issues 类 1 |
| 3 | inventory==ledger==indexed? | 三方对账 KPI + 按源/文档明细(§4A;Discovery §6 不变量) |
| 4 | 最近变了什么? | 最近语料变更流(AUTO 也可见,§5) |
| 5 | 哪些文档失败、为什么? | Issues 类 2(DocFailure stage/分类)+ Inspector 诊断证据 |
| 6 | 引用还有效/可点吗? | 引用健康 KPI + Issues 类 6 + Inspector 引用区(VALID 徽章+最后探活) |
| 7 | 某文档为何有资格作答? | Inspector 资格行逐轴人话解释(§4C) |
| 8 | 系统自动修了什么? | 问题行"系统已自动做"证据弹出 + 变更流(AUTO+AUDIT 审计,§5) |
| 9 | 什么真正需要人? | Issues 默认视图按"需人"排序;侧栏角标=需人计数;§5 ADMIN DECISION 清单 |
| 10 | 不懂 Weaviate 能安全对账吗? | 五旅程之 5:全程运营词汇,技术细节只进折叠区,破坏动作有前置证据+两步确认(7D) |

---

## 9. 未决实质问题(仅列真需 Product 定夺的)

- **U-1 知识总览是否并入业务 KPI**(回答量/满意度)还是严格知识健康?本文默认后者(与业务概览分工);若 Product 要合并需重排 IA。
- **U-2 时态角色改动的影响范围提示强度**:改 CURRENT↔HISTORICAL 会改变答案引用形态(D-6 后每源可配);本文给 admin 级+行内警示,是否需要"改动前预览受影响文档数"由工程契约评估成本后定。

(非实质、已按默认处理的取舍:不建 HTML 原型 §7G;RBAC 分级 §3;SLA 默认=2×节奏 §4E。)

## 10. 建议下一闸

**Product 评审本文 → 冻结 IA 与问题契约表(§4D)→ 两个后续工程任务候选:(a) Admin Ops API 端点集(Discovery §10 清单为契约输入);(b) 知识运营前端实现(以本文为规格,挂 Phase 5)。** 前置小修(widget 徽章白名单、woo 分页)维持可独立先行授权。

---

### 附:Admin 既有模式引用索引
Sidebar 分组/NavLink/Sidebar.tsx:25-68;Badge 变体 ui/badge.tsx:4-19;KpiCard tone/脚注契约 observability/KpiCard.tsx:10-70;ServiceHealthBanner observability/ServiceHealthBanner.tsx:15-135;master-detail Conversations.tsx:148-151,433-435;展开行 DataSources.tsx:438-479,1530-1687;健康徽章分层纪律 DataSources.tsx:212-258;LoadError 契约 components/LoadError.tsx;轮询惯例 DataSources.tsx:482-514;window.confirm 内嵌浏览器问题 ProviderCredentialDialog.tsx:37;受理 toast 语义 hooks/useDataSources.ts:162-195;data-* 惯例各组件。
