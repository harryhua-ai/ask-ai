# CamThink V1.1 — Source Center Completion
# Shared Discovery(Product / Architecture Contract Freeze)

- **日期**:2026-09-04
- **执行模式**:READ-ONLY DISCOVERY(CODE_MUTATION = NONE,PRODUCTION_MUTATIONS = NONE)
- **角色**:Product & Engineering Advisor / Planner(A)
- **仓库**:harryhua-ai/ask-ai(主仓 `/Users/harryhua/Documents/GitHub/ask-ai`);报告入 docs 独立本地仓
- **覆盖 Issue**:#9 / #11 / #12 / #15 / #16 / #17 / #18 / #22(八件套,按统一 Source Center 域模型处理,不作为八个独立需求)
- **前置地位**:v1.0.1 Production Stabilization 由另一执行流并行推进中(v101-track-a/b/c 三个 worktree 已建于 0e6a8a3);本报告不参与 v1.0.1,只为其完成后立即并行进入 v1.1 冻结契约

---

## 1. Executive Summary

**结论:READY(v1.1 = 单一治理波 #22;八件套中 7 件已随 v1.0.0 交付并在生产运行,唯一 OPEN 项 #22 的修复爆炸半径 = 纯 discovery/preview 层 + Admin 面板,连接器/同步/摄入链零触碰,零 schema 迁移)。**

核心事实:

1. **派发单的隐含前提需要纠正**:八个 issue 中 #9/#11/#12/#15/#16/#17/#18 已全部 **CLOSED** 并随 **v1.0.0(tag 已打,生产三服务 = 0e6a8a3)交付**;唯一 OPEN 的是 **#22 统一发现治理(最小人工评审)**。因此 v1.1 不是"八线并进",而是**一条治理收口波** + 对已交付七件契约的守卫性重申。Task §17 的 TRACK A/B/C 提议按历史语境成立,但按当前仓库证据已被 v1.0.0 交付**整体吸收**(§19)。
2. **#22 的两个病根已在 v1.0.0 代码中定位到行级**,且都位于 discovery/preview 层,**不在** ingestion 链上:
   - **Website 66/128 待确认根因** = `classify_url` 对未知路径的保守默认(`website_discovery.py:257-271`:命中排除清单 → exclude;命中优先类别 → include;**其余一律 `(technical_doc, review)`**)。CamThink 官网的 /blog/、/company/、/news/、/case 等路径不命中任何 hint → 整批落入待人工确认。该函数**仅被 preview 消费**(`website_discovery.py:375`),同步链路从不读取它。
   - **GitHub components 案件机制** = `summarize_candidates` 分组规则(`source_discovery.py:148-153`):组内**同时含 include 与 exclude 成员 → 整组 review**;平票时 `max(counts, key=(counts[r], r))` 字典序偏向 review。`components/` 13 个文件逐个"建议纳入",但组内只要混入 1 个 exclude 成员(如组件目录里常见的 .png 预览图 → binary → exclude),整组被抬进待人工确认——这正是 #22 指控的"建议纳入却要求确认"的自相矛盾。精确触发成员需在实现窗对 neomind-dashboard 做 preview 复现(实现期 D 项,非本 Discovery 网络取证)。
   - 伴生缺陷:组 rec=review 时,`compile_recommended_config` 的 `exclude_dirs` 不收 review 组(`repo_discovery.py:110-115`)、`file_types` 按逐文件 include 收(`103-109`)——所以**采用推荐策略后 components 实际会被摄入**(扩展名在白名单、目录不在排除表),但 UI 层面管理员既无法对该组做决策,也无法确信它会进范围:**矛盾在信任层,不在摄取层**。
3. **最小而稳健的 #22 设计已冻结**(§9-§11):决策三层(L1 确定性安全 / L2 高置信推断 / L3 真歧义评审)+ 分组聚合修正(混合组不再整组 review)+ **持久化 Source Policy = config JSONB 新键 `discovery_rules`**(规则是治理记忆,**不是第二套摄取权威**——编译桥仍是唯一通道,PD-2 纪律保持)+ 逐组 `scope_confirmed` 有效范围确认(机械可测地封死"显示纳入、实际不进"的缺口)。零新表、零新列、零新端点,preview wire 只增字段。
4. **v1.1 的其余部分是"验收矩阵复核"而非新开发**:任务 §21 的 18 项验收中 15 项已由 v1.0.0 交付并有实证(§21 逐项给出证据),v1.1 新增测试面全部集中在 #22 治理函数与两块面板。
5. **与 v1.0.1 三 track 的关系**:零契约依赖;v1.1 实现必须 rebase 在 v1.0.1 集成结果之上;按当前文件面预估碰撞≈0(track-a=#19 检索、track-b=W1 GPU 回退、track-c=运维健康,均不触碰 discovery 文件),但 v1.1 bootstrap 时必须以 `git log` 复核(track-c 若扩 Admin 面板可能与 DataSources.tsx 相邻)。

---

## 2. Baseline

```
BASELINE_COMMIT   = 0e6a8a3 (= origin/main = tag v1.0.0 = 生产三服务运行版, 2026-09-04 部署)
CURRENT_RELEASE   = v1.0.0(仓库首个 tag;RELEASE.json 权威链随 #10 落地;release-notes/v1.0.0.md 在主仓)
CURRENT_MAIN_HEAD = 0e6a8a3(origin/main 已核验一致;主仓工作树 checkout 在 codex/issue-14-w1 分支属 v1.0.1 并行流,与本 Discovery 无关)
```

- 候选血统已全部收敛:ce52af4(S0)→ 272f570(#16/#17/#18)→ 855b88a(W2 REV2)→ 0e6a8a3(Final RC + #5/#10),v1.0.0 生产部署报告见 docs 仓 `CAMTHINK_V1_V1_0_0_PRODUCTION_MUTATION_DEPLOYMENT_2026-09-04.md`。
- 证据方法:0e6a8a3(worktree `final-rc-20260903`)源码通读 + GitHub issue 原文(#22 含 2026-09-04 neomind-dashboard 案件全文)+ docs 既有发现/实现/集成/部署报告交叉引用。**零代码改动、零生产接触、零网络抓取**;生产证据全部引用既有报告(#22 的 128/66 与 components 数字即来自 issue 原文的生产观察)。

---

## 3. Current Architecture(v1.0.0 交付后的真实链路)

### 3.1 存储(全部已存在,v1.1 零新增)

| 表/载体 | 职责 | 关键列/键 | 证据(0e6a8a3) |
|---|---|---|---|
| `data_sources` | 源配置唯一权威 + 生命周期状态 | `config(JSONB)`、`lifecycle_state/since/error` | `db/models.py`、`source_lifecycle.py:30-37` |
| `documents` | 文档账本(成员身份/一致性) | `(content_hash, branch)` 复合 PK | `db/models.py` |
| `sync_requests` | 执行交接(backend→executor) | pending 领用,FOR UPDATE SKIP LOCKED | `services/sync_requests.py` |
| `sync_runs` | 运行遥测单表(ONE SOURCE × ONE ATTEMPT) | `request_id/attempt/recovery/triggered_by/status/stage/stage_current/stage_total/counters(JSONB)/consistency(JSONB)/error_summary/sync_log_id/execution_device/fallback_reason/fallback_detail` | `db/models.py`(W2 列全在) |
| `sync_log` | 业务历史结局 | `items_new/items_updated/items_deleted/items_unchanged/error_detail/triggered_by/duration_ms` | `db/models.py` |
| `config JSONB` | **摄取策略唯一权威**(file_types/exclude_dirs/exclude_patterns/branches/base_url/…) | 服务端零 schema 校验(维持) | `db_adapter.py:14-40` |

### 3.2 Admin API 面(Source Center 相关,全部已存在)

`backend/api/admin/data_sources.py`:`GET/POST/PATCH /data-sources`、`DELETE 202`(399)、`POST /{id}/delete/retry`(426)、`POST /discover-repo`(529,#16)、`POST /preview-website`(580,#17)、`POST /{id}/sync 202`(608,lifecycle deny-by-default 631)、`POST /sync-all 202`(655,674 同过滤);`backend/api/admin/sync_runs.py`:`GET /sync-status`(95,#9/#12 活动恢复)、`GET /sync-runs`(171,#15 历史)、`GET /sync-health`(420,#11 五维)。

### 3.3 前端(`admin/src/pages/DataSources.tsx` 1511 行 + 4 面板组件)

`dataSources/RepoDiscoveryPanel.tsx`(#16 分组直呈 + PolicyChips 原词表微调 + 唯一「采用推荐策略」按钮 266-272)、`SyncStatusPanel.tsx`(#9/#12)、`SyncHistoryPanel.tsx`(#15)、`SourceHealthPanel.tsx`(#11 直呈视图,注释明文"前端不做任何健康重判")。Website preview 内嵌于 DataSources.tsx(699 `handleWebsiteDiscover`,1129 检测站点内容,1188 分组 slice(0,10))。

### 3.4 摄取链(v1.1 不触碰)

`scripts/sync.py`(`_load_configs_from_db` 带 lifecycle 过滤)→ connectors(github/web_crawl/filesystem/woocommerce)→ `pipeline/ingest.py`(Layer 1 check_content)。三层准入不变式:**最终准入 = TECHNICALLY_SAFE ∧ KNOWLEDGE_ELIGIBLE ∧ SOURCE_POLICY_ALLOWED**。

---

## 4. Current Truth Map

| 用户可见状态 | 权威源 | 派生 | 短暂 | UI-only | 判定 |
|---|---|---|---|---|---|
| 同步中/排队/已完成/失败/中断 | `sync_requests` + `sync_runs`(持久化) | `/sync-status` 聚合 `_pick_active_request` | — | 无 | ✅ #9/#12 已闭环(刷新恢复同 run,不重复触发) |
| 运行进度(stage/counter/百分比) | `sync_runs.stage/stage_*` + 实时落笔 | `/sync-status` | 轮询窗口 ≤5s | 无 | ✅ 无可信 total 不显百分比(契约保留) |
| 每次Run历史与增删变更 | `sync_runs` + `sync_log` | `/sync-runs` | — | 无 | ✅ #15 闭环;⚠️ `items_updated` 语义含混(§23 DEFER) |
| 当前知识健康 | `sync_runs/consistency` facts 读时派生 | `/sync-health` 五维 | — | 无(前端零重判) | ✅ #11 闭环(RECOVERING=活动overlay;#13→#11 修正已并入) |
| 删除进行中/失败 | `data_sources.lifecycle_*` 3 列 | `DataSourceOut` | — | 无 | ✅ #18 闭环(202 + retry + deny-by-default) |
| **发现推荐/待确认/组决策** | **preview 响应即弃(无持久化)** | 前端分组渲染 | preview 会话内 | **组决策状态事实上 UI-only** | ❌ **#22 缺口:推荐无记忆,同歧义反复出现;组决策无控件** |

"UI 猜测状态"审计结论:七件已交付 issue 的状态面**全部**已从 React 内存迁到后端持久事实(W2/W3 集成门 + v1.0.0 生产冒烟背书);唯一残留的 UI-only 状态就是 #22 的发现决策——这不是渲染 bug,而是**缺一个持久化治理模型**,即 v1.1 的全部新增持久化内容。

---

## 5. Shared Domain Model(16 概念逐一裁决)

| 概念 | 裁决 | 承载 |
|---|---|---|
| SOURCE | 已有,单表 | `data_sources` |
| SOURCE POLICY | 已有,**唯一摄取权威** = config 词表 | `config JSONB` |
| DISCOVERY ITEM | 已有 | `FileAdmission`(文件)/URL 候选(网站),preview 会话内 |
| DISCOVERY DECISION | **v1.1 新增(唯一新概念)** | `config.discovery_rules`(§9.4) |
| SYNC REQUEST vs SYNC RUN vs SYNC LOG | 已有,语义冻结(请求=交接,run=attempt 遥测,log=业务结局) | 三表现状,零改动 |
| SYNC STAGE | 已有,canonical 9 阶段词表 | `sync_runs.stage` |
| SYNC PROGRESS | 已有(stage+counters;可信 total 才有百分比) | `sync_runs` |
| SYNC RESULT | 已有 | `status + consistency + error_summary` |
| DOCUMENT DELTA | 已有 | `sync_log.items_*` |
| VECTOR DELTA | 已有 | `counters.chunks_deleted` + `sync_log.chunks_written` |
| CURRENT KNOWLEDGE HEALTH | 已有(读时派生,无快照表) | `/sync-health` 五维 |
| HISTORICAL RELIABILITY | 已有(run 级统计,与 Current Health 分离呈现) | `/sync-runs` + health sync 维 |
| SOURCE LIFECYCLE | 已有(四态,deny-by-default) | `lifecycle_state` |
| DELETION OPERATION | 已有(202 + worker + 启动对账) | `source_deletion.py` |
| HUMAN REVIEW | **v1.1 重定义范围**(从"常态"收缩为"例外路径") | §14 |

**不新增抽象**。除 `discovery_rules` 一个 JSONB 键外,v1.1 不引入任何新模型/表/服务;治理层是 discovery producer 与 Admin 面板之间的**语义层**,不是新子系统。

---

## 6. Sync Truth Contract(#9/#12)— SHIPPED,守卫性重申

已冻结并交付(v1.0.0 生产实证,部署报告 A+B+C 三相 + 13 例语义验收):

- `SyncRequest`(交接)≠ `SyncRun`(attempt 遥测,ONE SOURCE × ONE ATTEMPT)≠ `SyncLog`(业务结局);`request_id=NULL` 是 cron 合法路径。
- 状态族 running/completed/failed/interrupted + stage 词表 DISCOVER→…→DONE;`attempt_started_at` 复检锚 + 上限闸门 + 首启中断 F16 旁路(阶段⑩)。
- ** survives refresh/relogin/restart**:活动 run 从 DB 恢复;同一活动 run 存在时重复触发不产生 duplicate request(W2 REV2 集成门验收项)。
- V1 polling;进度只在 `stage_total` 可信时显示 current/total;否则 stage+counters。**No fake progress** 不变式保留。
- **v1.1 守卫**:#22 只改 preview 层,禁触碰 `sync_requests/sync_runs/sync_log` 与 `/sync-status`。

## 7. Health Contract(#11)— SHIPPED,守卫性重申

- Current Health ≠ Historical Reliability:五维(connectivity/sync/coverage/freshness/consistency)读时纯派生,`/sync-health` 唯一权威;`SourceHealthPanel` 直呈、前端零重判(W3 Health Authority correction)。
- 状态族含 EMPTY_EXPECTED/EMPTY_UNEXPECTED/RECOVERING(活动 overlay,不把旧成功显示成 HEALTHY)/ACTION_REQUIRED(消费 #13 修复事实,855b88a Correction Gate);无证据 → INSUFFICIENT_DATA。
- expected_state(REQUIRED/OPTIONAL/DISCOVERY/EXCLUDED)已接 `expected_state_of`(sync_runs.py:367)。
- **v1.1 守卫**:discovery_rules 不得成为健康维度输入(推荐是准入 UX,不是运行事实)。

## 8. History Contract(#15)— SHIPPED,一项语义挂账

- `/sync-runs` 按 source 时间倒序:起止/触发/终态/时长/`items_new|deleted|unchanged`/`chunks_written`/`counters.chunks_deleted`/consistency/error_summary,全部来自持久 run facts,前端零差分推测。
- ⚠️ 唯一挂账:`items_updated` 的文档 vs 分块语义在 W0 发现期已标记含混(`#15 items_updated 实为 chunks` 线索)。**v1.1 不修**(与 #22 无依赖),列入 §23 DEFER,由 v1.0.1/v1.2 追认词表或在面板加语义说明。

---

## 9. Discovery Governance Contract(#22 核心,本轮主冻结)

### 9.1 现状审计结论(为什么"一半待确认")

| 层 | v1.0.0 行为 | 实证 | #22 裁决 |
|---|---|---|---|
| 技术安全(L1) | unsafe → exclude,不可翻转 | `safety.py` admission | **保持不动**(红线) |
| 角色→推荐 | 7 角色 include / 5 角色 exclude / BINARY 落 review;词表冻结 | `safety.py:230-247` | **词表零改动** |
| 网站 URL 分类 | 未知路径一律 review(`classify_url` 兜底) | `website_discovery.py:257-271`,消费面仅 preview:375 | **默认改 include**(PD-1) |
| 仓库逐文件 review 带 | 1MB–64MB 尺寸带、`.example/.sample` 密钥模板 | safety 阈值 + S0 §5.4 | **保留 review**(PD-2) |
| 分组聚合 | include+exclude 混合 → 整组 review;平票字典序偏 review | `source_discovery.py:148-153` | **改为多数决 + 组内明细**(§9.2) |
| 组决策控件 | 无(分组只读直呈;唯一按钮=采用推荐策略) | `RepoDiscoveryPanel.tsx:266-272` | **加逐组决策控件**(§14) |
| 推荐持久化 | 无(preview 即弃) | S0 §15 当时裁决 | **新增 discovery_rules**(§9.4,推翻"即弃"仅就决策记忆而言;preview 快照仍不落库) |

### 9.2 决策三层(冻结词表)

```
L1 DETERMINISTIC_SAFE   系统自动决定,不可翻转:
                        Technical Safety 全部结论 / URL_EXCLUDE_PATTERNS(22 条含 /store/)/
                        二进制资产后缀 / secret 文件 / 白名单不可能形态(仓库无扩展名、
                        未知扩展名 → 按构造不可能被 file_types 匹配 → exclude + 能力注记)
L2 HIGH_CONFIDENCE      系统自动决定,展示理由,管理员可覆盖:
                        角色词表映射(冻结不动)/ 网站同域 HTML 页默认 include(含
                        未知路径——正文质量由 sync 期 min_content_chars 兜底,preview
                        不因路径陌生而假模假样要求确认)
L3 TRULY_AMBIGUOUS      唯一进入待人工确认的例外集:
                        尺寸 review 带(1MB–64MB)/ .example 密钥模板 /
                        分组平票 / 持久规则与新证据冲突(规则说 include、本轮 L2 证据
                        转 exclude 等)/ 发现异常(截断、空结果)
```

待确认收缩目标(验收口径):**同构健康站点 preview 待确认组数 ≤ 2(L3 词表命中类);neomind-dashboard 的 components 直呈「建议纳入」**。

### 9.3 分组聚合修正(冻结规则,替换 `summarize_candidates` 现行混合规则)

```
组内计数 include_count / exclude_count / review_count(仅 L3 成员)
decision := review_count>0 且 include+exclude=0      → REVIEW(整组真歧义)
          │ include>0 且 exclude>0 且 include≠exclude → 多数决(不再整组 review;
          │                                            少数派成员在组内明细区展示
          │                                            "n 个已排除:原因",编译层保证
          │                                            其确实不进范围)
          │ include == exclude(平票)                → REVIEW
          │ 其余                                     → 唯一多数派
```

关键放行理由(安全论证,写入实现测试):include 组内的 exclude 少数派**天然不可能被摄入**——`compile_recommended_config` 的 file_types 白名单只收 include 成员扩展名、exclude_dirs 收 exclude 组;即混合组提升为 include 后,少数派排除由**既有编译语义机械保证**,无需人工确认背书。

### 9.4 Persisted Source Policy(唯一新增持久化;冻结形态)

```jsonc
// data_sources.config JSONB 新键(v1.1 起合法;旧源无此键 = 零行为变化)
"discovery_rules": [
  { "pattern": "components/",  "kind": "github",    "decision": "include", "origin": "admin", "decided_at": "...", "note": null },
  { "pattern": "/blog/",       "kind": "web_crawl", "decision": "include", "origin": "admin", "decided_at": "..." }
]
```

- **匹配语义(冻结)**:github = 首段目录前缀(对齐 `top_level_group`);web = 路径子串前缀(对齐 `classify_url` 匹配风格);有序列表**先匹配先胜**;**L1 永远压过任何规则**(与技术安全高于管理员 policy 的 D3 冻结一致:规则说 include、本轮判 unsafe → 仍 exclude)。
- **单一权威链(本契约的脊柱,不可违背)**:
  `discovery(preview)` →(规则继承:命中组标记"已按策略"并不再进待确认)→ `管理员决策/采用推荐策略` → **编译** → `config 词表(file_types/exclude_dirs/exclude_patterns)` → **唯一摄取权威** → connectors/sync **零改动**。
  规则是**治理记忆 + 编译输入**,绝不是连接器直接消费的第二套摄取语义(PD-2"不建第二套 ingestion authority"纪律原样保持;git 与 web 共用同一模型,#22 的 cross-connector 要求由此满足,未来 Drive/Confluence 只需新 producer + pattern 匹配器)。
- **结构变化生命周期(冻结)**:站点/仓库结构漂移时,命中旧规则的组自动继承决策(不再重复问);未命中任何规则的新组走 L1/L2/L3 全新分类;失配规则无害滞留(零副作用),不自动清理(v1.1 不做规则 GC,§23)。

### 9.5 preview wire 增量(additive-only,冻结)

```
DiscoveryGroupOut  += { "admin_decision": "include"|"exclude"|null,     // 规则继承的既有决策
                        "scope_confirmed": bool,                          // §11 有效范围确认
                        "member_excluded": int }                          // 组内被排除少数派数
DiscoveryResultOut.target += { "inherited_rules": int }                   // 命中规则数(透明度)
```

请求 schema、端点集合、错误语义全部不变;旧前端可忽略新字段。

---

## 10. Recommendation Contract(冻结)

- 三态词表不变:`include | exclude | review`;reason 文案继续走 `source_discovery.reason_text` 冻结枚举(Stage⑯ 文案纪律)。
- **推荐 ≠ 待批**:L1/L2 产出的 include/exclude 直接参与「采用推荐策略」;review 仅 L3(§9.2 词表)。
- `RECOMMENDED_INCLUDE_ROLES / RECOMMENDED_EXCLUDE_ROLES` 与 `KnowledgeRole` 13 值**零改动**——本轮全部语义修正发生在分类默认值与聚合层,不重写安全词表(这是"最小架构"的落点,也是回归面最小的原因)。
- UI 分桶规则(两处:RepoDiscoveryPanel、DataSources 网站区)冻结为:组 rec=include → 建议纳入;exclude → 自动排除/建议排除;review → 待人工确认(仅 L3);admin_decision 命中时加「已按策略」徽章。

## 11. Apply Strategy Contract(「采用推荐策略」冻结)

调用即:
1. 全部 L1/L2 include/exclude 组 + 既有 admin 规则 **编译进持久化词表**(现行 `compile_recommended_config` 扩展:组决策含 admin 覆盖;网站侧 exclude_patterns 照旧);
2. L3 未决组**保持未决**并单独呈现(不静默吞掉,PD-4);
3. **逐组 `scope_confirmed` 机械确认**:对每个 include 组,按编译产物逐成员执行 `member_in_scope(path, compiled_config)`(github:扩展名∈file_types ∧ 目录段∉exclude_dirs ∧ 不中 exclude_regex ∧ technical_safe;web:不中 URL_EXCLUDE∪用户 exclude_patterns ∧ 同域 ∧ 非二进制后缀),任一 include 成员不在范围 → preview 显式告警。**"显示建议纳入却静默不进范围"由此变为不可通过测试的缺陷**;
4. UI 立即如实呈现生效策略 = 表单词表现状(现行字段即 effective policy)+ 组级徽章;管理员不需要手工翻译 glob/路径,除非进 Advanced(Expert 模式保留,非必经)。

## 12. Repository Contract(#16 as-built + v1.1 增量)

已交付:trees API 单调用无 clone 发现(MAX_TREE_ENTRIES=20000 截断告警)、顶层目录分组、`discover-repo` 端点、PolicyChips 高级微调、克隆路径系统管理(主表单不再暴露)。v1.1 增量 = §9 全部适用;**neomind-dashboard 验收案件**(#22 原文 5 步)列为实现期首要 E2E:components 在建议纳入 → 采用推荐策略后 scope_confirmed=true → 后续 sync 实际摄入(以 run counters/账本行验证,不用 UI 自证)。

## 13. Website Contract(#17 as-built + v1.1 增量)

已交付:robots Sitemap: 指令 → 显式覆盖 → 通用回退 → 索引全子表展开的四层发现(冻结顺序)、`/store/` C8 对齐、22 条 URL 排除词表、零发现显式告知、能力注记、Preview 三态。v1.1 增量 = classify_url 兜底 review→include(PD-1,preview-only 行为变化)+ discovery_rules 继承(`/blog/** → INCLUDE` 一次决定永久生效)。能力诚实矩阵(无 JS 渲染/无 PDF/OCR/单主域)不变;`groups.slice(0,10)` 的"前 10 组"呈现与"其余同规则处理"文案保留。

## 14. Human Review Contract(冻结)

- 评审以**组/规则**为单位,不逐 URL/逐文件;组内展示代表样本 + 冻结 reason;
- 管理员一次决定 = 写入 `discovery_rules`(§9.4)→ 后续发现自动继承,**同一歧义不再反复出现**(验收:二次 preview 该组不进待确认、带「已按策略」);
- 待确认必须可操作:每组分「纳入 / 排除 / 恢复推荐」控件(现行 RepoDiscoveryPanel 无任何组级控件——#22 指控实证,本轮补齐);
- 待确认数为 0 是**合法且常见**终态,不是异常;UI 不再制造确认仪式感。

## 15. Source Lifecycle Contract(#18 as-built,零改动)

四态 `active/delete_requested/deleting/delete_failed` 持久化于源行;sync 资格 deny-by-default(`is_sync_eligible` 仅 ACTIVE;`sync_eligible_condition` 接进调度 WHERE);DELETE 202 + retry + 启动对账。**与 #22 零交集**:preview 端点无源身份(创建前发现),rules 存于 config 随源生死,删除即随行消亡——无孤儿规则清理问题。v1.1 守卫:不新增生命周期状态(词表冻结注释已声明新增值须过 sync 资格评审)。

## 16. Persistence / Schema Decision

| 项 | 决定 | WHY REQUIRED / 理由 |
|---|---|---|
| 发现决策持久化 | `config.discovery_rules` JSONB 键(JSONB 无需迁移) | #22 明文要求"persist decision as Source Policy;future discovery inherits";config 已是策略唯一权威载体、随源生命周期、随 list API 天然可达。**被否方案**:新表 `discovery_decisions`(需迁移 + 第二真相源 + 与 config 编译链脱节)、独立 policy 服务(V1 过度设计) |
| schema 迁移 | **零**(无新表/无新列) | JSONB 键 additive;旧源无键 = 无规则 = 行为不变 |
| preview 快照 | 仍不落库(S0 §15 裁决保留) | 中间态无审计价值;决策记忆由 rules 承担 |
| 回滚 | 删除键即回滚;代码回滚 = 分支 revert,旧代码忽略未知 JSONB 键 | 零数据风险 |

## 17. API / Interface Boundaries(为并行冻结的最小面)

- 端点集合零变化:`discover-repo` / `preview-website` 语义扩展(继承规则 + 新字段),wire 只增字段(§9.5);
- 无新端点、无新查询参数、无破坏性变更;
- 服务层函数签名(冻结):`summarize_candidates(candidates, group_key)` → 聚合规则 §9.3(签名不变,语义升级);新增纯函数 `apply_discovery_rules(result, rules) -> result`(producer 级,双连接器共用)、`member_in_scope(path|url, compiled_config, kind) -> bool`、`compile_recommended_config(candidates, group_decisions)`(扩展第二参,默认 None 向后兼容);
- 前端接口:两面板消费新字段;`useDataSources` 的 discovery mutation 响应类型扩展。

## 18. Cross-Issue Dependencies

| 关系 | 分类(任务 §16 词表) | 说明 |
|---|---|---|
| #9/#11/#12/#15/#18 → #22 | **NONE** | 全部已交付且层正交(运行真相 vs 准入治理);#22 守卫其不变式即可 |
| #16/#17 → #22 | **FROZEN_INTERFACE**(已由 v1.0.0 实现,本轮语义升级) | #22 消费两 producer 的 DiscoveryResult;修正发生在共享层 `source_discovery.py` + `classify_url`,producer 文件改动各 ≤ 数行 |
| #22 → 未来连接器 | FROZEN_INTERFACE | producer + pattern 匹配器两件套即接入,治理语义共用 |
| #22 ↔ #13(历史污染) | NONE | D3 冻结"Technical Safety 高于 policy"被 #22 规则继承,无代码交集 |
| v1.1 ↔ v1.0.1 tracks | **COMMIT_DEPENDENCY(单向 rebase)** | v1.1 bootstrap 必须基于 v1.0.1 集成结果;按文件面预估零冲突,bootstrap 时复核 |

## 19. Recommended Parallel Execution Topology

**任务 §17 提议的 TRACK A(#11+#12+#9)/ TRACK B(#15+#18)/ TRACK C(#22+#16+#17)三分法:按仓库证据已被 v1.0.0 整体吸收——A、B 全部 SHIPPED(§6-§8、§15),C 中 #16/#17 已 SHIPPED。** 保留该提议的"历史正确性",但 v1.1 不再按它执行。

```
PARALLEL_RECOMMENDATION: TWO_WAY(可选降级 SINGLE;禁三 worktree)
  Wave-0(先合,半天):source_discovery.py 聚合规则 §9.3 + apply_discovery_rules/
                      member_in_scope 纯函数 + classify_url 兜底翻转(PD-1 批准后)
                      + wire 字段 + 全部后端测试  →  其余文件零触碰
  Track-1:RepoDiscoveryPanel 组决策控件 + 已按策略徽章 + scope_confirmed 呈现(OWN 该组件文件)
  Track-2:DataSources.tsx 网站 preview 区同等控件 + 采用推荐策略接线(OWN 行区 477-525/699-760/1100-1230)
  集成序:Wave-0 → Track-1 ∥ Track-2 → 集成门(全量离线 + admin vitest + build + neomind-dashboard E2E)
```

理由:治理语义横跨两 producer 共享层,先后端定型 wire 再并行前端是唯一不产生语义漂移的分法;三个 coding worktree 的上限由 v1.0.1 三 track 占用,v1.1 不与之争抢(§18 rebase 纪律)。

## 20. Change Boundaries(文件所有权矩阵)

| 文件 | v1.1 处置 |
|---|---|
| `backend/services/source_discovery.py` | **OWN**(§9.3 聚合规则 + rules/ scope 纯函数 + wire 字段) |
| `backend/services/website_discovery.py` | **HUNK**(classify_url 兜底翻转 + preview 组装接 rules;≤30 行) |
| `backend/services/repo_discovery.py` | **HUNK**(compile 第二参 + producer 接 rules) |
| `backend/api/admin/source_center_schemas.py` | **HUNK**(GroupOut/target 增字段) |
| `admin/src/components/dataSources/RepoDiscoveryPanel.tsx` | **OWN**(Track-1) |
| `admin/src/pages/DataSources.tsx` | **HUNK**(Track-2 冻结行区) |
| `admin/src/hooks/useDataSources.ts` | **HUNK**(类型) |
| `tests/services/test_source_discovery.py` 等 | **OWN/HUNK**(增量) |
| `backend/connectors/**`(github/web_crawl/exclusion/safety) | **✗ 禁触碰**(摄取权威与安全词表零改动) |
| `scripts/sync.py` / `pipeline/ingest.py` / `sync_requests/sync_runs/sync_logs` / `models.py` / 迁移脚本 | **✗ 禁触碰** |
| `source_lifecycle.py` / `source_deletion.py` / `sync_runs.py`(api) | **✗ 禁触碰** |

红线:任一 HUNK 扩散出冻结行区 = RE-PLAN REQUIRED(双仓协议)。

## 21. Acceptance Matrix(任务 §21 十八项逐一落位)

| 验收项 | 状态 | 证据 / v1.1 测试 |
|---|---|---|
| REFRESH DURABILITY | ✅ SHIPPED | /sync-status 活动恢复;v1.0.0 生产冒烟 |
| RELOGIN DURABILITY | ✅ SHIPPED | 同上(状态全在 DB) |
| NO DUPLICATE SYNC | ✅ SHIPPED | W2 REV2 集成门验收项 |
| TRUTHFUL PROGRESS | ✅ SHIPPED | 可信 total 才显百分比(契约保留) |
| CURRENT HEALTH CORRECTNESS | ✅ SHIPPED | 五维权威 + RECOVERING overlay;生产实证 |
| HISTORICAL RELIABILITY SEPARATION | ✅ SHIPPED | health sync 维 vs /sync-runs 分离 |
| SYNC HISTORY DELTAS | ✅ SHIPPED(items_updated 语义挂账 §23) | SyncHistoryPanel 直呈 |
| REPOSITORY AUTO-DISCOVERY | ✅ SHIPPED | discover-repo;trees API 无 clone |
| WEBSITE AUTO-DISCOVERY | ✅ SHIPPED | 四层发现顺序;www.camthink.ai 128 页冒烟 |
| RECOMMENDED INCLUDE 直呈 | 🔶 v1.1 | components 案件 E2E(#22 五步原文) |
| RECOMMENDED EXCLUDE 直呈 | 🔶 v1.1 | 分桶规则测试 |
| GENUINE NEEDS REVIEW | 🔶 v1.1 | L3 词表命中类 ≤2 组口径 |
| APPLY RECOMMENDED STRATEGY | 🔶 v1.1 | 编译含 admin 覆盖;L3 不被吞(PD-4) |
| PERSISTED EFFECTIVE POLICY | 🔶 v1.1 | config 词表 + scope_confirmed 机械确认 |
| SUBSEQUENT SYNC FOLLOWS POLICY | 🔶 v1.1 | components 摄入以账本行/run counters 验证 |
| NON-BLOCKING DELETE | ✅ SHIPPED | DELETE 202;#18 AC 全过 |
| DELETE REFRESH RECOVERY | ✅ SHIPPED | lifecycle 列持久化 |
| CONNECTOR-GENERIC GOVERNANCE | 🔶 v1.1 | git/web 共用 rules+聚合;producer 两件套接入契约 |

## 22. Regression Constraints

1. **preview 行为翻转必须显式**:classify_url 未知路径 review→include 会翻转既有测试预期(本 Discovery 期 #17 的 preview 测试组含 zero-discovery/generic mode/理由文案断言)——实现期**逐条有意更新**,不许顺手改;S0 冻结测试(reason 文案枚举、FileAdmission 结构、URL_EXCLUDE 词表、`/store/` 对齐)必须保持绿。
2. 摄取链回归口径:全量离线套件绿(HF_HUB_OFFLINE=1 纪律)+ admin vitest + build;#22 不引入任何 connector/sync 侧 diff(`git diff --stat` 按文件矩阵审计,§20 禁触碰文件出现即 FAIL)。
3. v1.0.0 生产场景不回退:www.camthink.ai preview 仍 128 页/18 include/44 exclude 级别的确定性(排除词表与去重不动,只有 review 桶迁移);Yoast fixture、空 urlset、零发现显式告知用例保持绿。
4. 文案纪律:新增用户可见文案走冻结枚举/固定串(Stage⑯ 纪律),不做自由文本生成。

## 23. Deferred Scope

- `items_updated` 文档/分块语义追认与面板语义说明(W0 挂账,与 #22 零依赖);
- 规则 GC/失配规则清理 UI(失配无害,v1.1 不做);
- preview 抽样正文嗅探增强(S0 可选项,继续搁置);
- 尺寸 review 带自动决议(PD-2 否决自动化,维持人工);
- 未来连接器(Drive/Confluence/Notion/SharePoint)producer 实现(接口已冻结,§17/§18);
- website 组slice(0,10) 之外的完整分组翻页 UI(文案已声明"其余同规则处理",暂不动)。

## 24. Product Decisions Required

| PD | 议题 | 建议 |
|---|---|---|
| **PD-1(实现前置)** | 网站未知路径默认 review→include(L2 化;preview-only,摄取零变化,sync 期 min_content_chars 兜底) | **批准**(这是 66/128 → ≤2 的唯一主杠杆;保守 review 默认已被生产数据证伪为常态摩擦) |
| PD-2 | 尺寸 review 带(1MB–64MB)与 .example 模板是否也自动化 | **维持 L3 人工**(错误纳入大文件/密钥模板的代价不对称) |
| PD-3 | 规则持久化位置 = config JSONB `discovery_rules`(无迁移) | **批准**(否决新表/独立服务,理由 §16) |
| PD-4 | 「采用推荐策略」不吞 L3 未决组(保持未决可见) | **批准**(吞掉 = 新型静默,违背可验证原则) |

## 25. READY / NOT READY

```
READY_STATUS = READY(READY_FOR_PARALLEL_IMPLEMENTATION,TWO_WAY @ Wave-0 先行)
```

- 共享真相无歧义:八件套现状逐项有 0e6a8a3 行级证据;唯一开放语义 = 4 项 PD(全部附建议;**PD-1 为实现启动前置**,PD-2/3/4 可在 Wave-0 期间并行拍板);
- 执行端不会各自发明模型:新概念仅 `discovery_rules` 一个,形态/匹配/权威链/聚合规则全部冻结(§9);
- 边界清晰:§20 禁触碰面把 #22 锁死在 discovery/preview + 两块面板;
- 持久化归属清晰:治理记忆=config 键,摄取权威=词表,运行真相=三表+sync_runs(互不越权);
- 验收可测:§21 每行有既有证据或可写测试;#22 原文五步案件 + scope_confirmed 机械确认闭环"显示纳入却不进范围"类缺陷;
- 并行安全:TWO_WAY 有 Wave-0 先行与文件矩阵背书。

---

## 附:证据索引(0e6a8a3 行级汇总)

- 角色词表与推荐映射:`backend/connectors/safety.py:211-226(13 roles)、230-247(include/exclude sets)、468-473(recommendation_for)`
- #22 病根:`backend/services/website_discovery.py:224-246(URL_EXCLUDE_PATTERNS 22 条)、248-261(_PRIORITY_ROLE_HINTS)、257-271(classify_url 兜底 review)、375(唯一消费点)`;`backend/services/source_discovery.py:113-125(组推荐文档)、141-153(混合组→review + 平票字典序)`
- #16 编译桥:`backend/services/repo_discovery.py:44-47(ROOT_GROUP_KEY/MAX_TREE_ENTRIES)、70-72(top_level_group)、93-116(compile:file_types 只收逐文件 include/exclude_dirs 只收 exclude 组)、119-189(discover_repository)`
- 生命周期:`backend/services/source_lifecycle.py:30-37(四态词表)、62-68(deny-by-default)、71-84(SQL 条件)`
- 读端点:`backend/api/admin/sync_runs.py:95(/sync-status)、171(/sync-runs)、235-322(五维派生)、367(expected_state)、420(/sync-health)`;`backend/api/admin/data_sources.py:399(DELETE 202)、426(retry)、529(discover-repo)、580(preview-website)、608-674(sync 202 + eligibility)`
- 运行列:`backend/db/models.py(SyncRun:request_id/attempt/recovery/triggered_by/status/stage/stage_current/stage_total/counters/consistency/error_summary/sync_log_id/execution_device/fallback_*;SyncLog:items_new/updated/deleted/unchanged)`
- 前端:`admin/src/components/dataSources/RepoDiscoveryPanel.tsx(组直呈无控件;PolicyChips;apply 266-272)、SourceHealthPanel.tsx(直呈无重判)、SyncHistoryPanel.tsx(items_*/chunks_*)`;`admin/src/pages/DataSources.tsx:699/1129/1160-1206(网站 preview 区)`
- 既有契约链:docs 仓 `CAMTHINK_V1_DATA_SOURCE_CENTER_SHARED_DISCOVERY_2026-09-03.md`(S0,#16/#17/#18)、`…DATA_SOURCE_RELIABILITY_OBSERVABILITY_SHARED_DISCOVERY…`(W0)、`…S0_INTEGRATION_BASELINE…`、`…SOURCE_CENTER_16_17_18_INTEGRATION_GATE…`、`…SYNC_TRUTH_DATA_INTEGRITY_INTEGRATION_GATE…`、`…FINAL_RELEASE_CANDIDATE_ASSEMBLY…`、`…V1_0_0_PRODUCTION_MUTATION_DEPLOYMENT_2026-09-04.md`

---

```
STATUS: DISCOVERY PASS — READY FOR PLANNER REVIEW
READY_STATUS: READY(READY_FOR_PARALLEL_IMPLEMENTATION,TWO_WAY @ Wave-0 先行;PD-1 为实现前置)
BASELINE: 0e6a8a3 = origin/main = tag v1.0.0 = 生产(2026-09-04)
SHARED MODEL: 零新表/零新列/零新端点;唯一新概念 = config.discovery_rules(治理记忆,非摄取权威);
              其余 15 概念全部复用既有持久真相
TRACK A(#11+#12+#9): SHIPPED in v1.0.0(依赖:NONE;ready:不适用)
TRACK B(#15+#18): SHIPPED in v1.0.0(依赖:NONE;ready:不适用;items_updated 语义挂账 DEFER)
TRACK C(#22+#16+#17): #16/#17 SHIPPED;#22 OPEN = v1.1 全部增量(依赖:FROZEN_INTERFACE 已定型;
          ready:READY,Wave-0→Track-1∥Track-2)
SCHEMA IMPACT: NONE(JSONB 键 additive,零迁移,删键即回滚)
PRODUCT DECISION REQUIRED: PD-1(未知路径默认 include,建议批准,实现前置)/ PD-2(尺寸带维持人工,
          建议维持)/ PD-3(rules 存 config JSONB,建议批准)/ PD-4(采用策略不吞 L3,建议批准)
DEFERRED: items_updated 语义追认/规则 GC/正文抽样嗅探/未来连接器 producer/分组翻页
REPORT_PATH: docs/implementation/CAMTHINK_V1_1_SOURCE_CENTER_SHARED_DISCOVERY_2026-09-04.md
REPORT_COMMIT: (见本仓提交)
PRODUCTION_MUTATIONS: NONE
NEXT: Planner Review → PD-1~4 拍板 → v1.0.1 集成落定后按 §19 拓扑派发 Wave-0
```

---

## 26. Planner Review Verdict(REV 1,2026-09-04)

> 本节为 Planner 裁决层,追加于 DISCOVERY PASS 之后;原文冻结不改,冲突处以本节为准。

```
VERDICT        DISCOVERY REVIEW PASS
READY_STATUS   READY
PD-1           APPROVED WITH MODIFICATION — Unknown path ≠ automatic include;
               use evidence-based INCLUDE / EXCLUDE / NEEDS_REVIEW
PD-2/3/4       APPROVED(按 §24 建议原样生效)
TOPOLOGY       ONE PRIMARY WORKTREE,#22 only(取代 §19 的 TWO_WAY 建议)
DEPENDENCY     实现启动前必须 rebase 到已验收的 v1.0.1 集成基线
SCHEMA         无迁移;仅 config.discovery_rules additive 键
HARD BOUNDARY  Discovery/preview 治理 + Admin discovery UI;
               connectors / sync runtime / ingestion / safety.py / sync 持久化模型
               = FORBIDDEN UNLESS NEW EVIDENCE REQUIRES
GOVERNANCE     本报告(含本节)镜像入主仓 Source-of-Truth 仓并推 origin——
               本地无 remote docs 提交单独不足以作为持久执行授权
NEXT           v1.0.1 基线落定后冻结 #22 Execution Contract,再以单一治理波执行 v1.1.0
```

### PD-1 修正对冻结契约的影响(约束 #22 Execution Contract 起草)

1. **§9.2 L2 中「网站同域 HTML 页默认 include(含未知路径)」作废**;`classify_url` 现行兜底 `(technical_doc, review)` 保留为**最后落点**,不翻转兜底本身。
2. **证据化分类取代默认翻转**:INCLUDE / EXCLUDE 必须给出 preview 可得的证据信号(非穷尽,清单由 #22 Execution Contract 冻结),例如:同域 sitemap 归属与站点级一致性、**路径族群多数决策**(同前缀家族内已判定页面的归票)、既有 `discovery_rules` 继承、优先类别 hint 命中、页面族群抽样证据;**无证据支持任一方向 → NEEDS_REVIEW**。
3. **§21 验收口径改写**:「待确认收缩」由"词表机械收缩"改为"**证据覆盖驱动的收缩**"——`128 → auto-handle ~all` 的达成路径 = 族群证据 + 规则继承,而非兜底翻转;NEEDS_REVIEW 数量是证据覆盖面的诚实函数,不得用默认值美化,也不得为凑数制造弱证据。
4. §13(v1.1 增量)与 §19(Wave-0 的 classify_url 翻转项)按本节同步修订;§9.3-§9.5、§11、§16、§17(分组聚合、rules、scope_confirmed、wire)不受影响,原样生效。
