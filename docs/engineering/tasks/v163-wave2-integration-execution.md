# V1.6.3 WAVE 2 INTEGRATION — 阶段 1 执行报告(合并+义务+接线+迁移+工程门)

- 分支:`integration/v163-wave2`(worktree ask-ai-v163-int2);基线 HEAD=d613e6aab787110e6c7839f92dbc28611b79ee7e(FINAL_PREP_BASE,编排者 Fresh Gate:DRIFT=NONE)
- 阶段 1 tip:**见 §2 拓扑末行 Integration candidate SHA**
- 证据目录:`ask-ai-acceptance/v163-wave2-20260914/`(阶段 1:全量 pytest 日志 + 迁移 JSON×3)
- 六个 accepted candidates(origin 核验 tip 精确一致、零改写):
  - A=49d37e2963dbe7066bea47eeaee161399ae27e26(共享 chrome+分析窗)
  - B=bb6c492528d70293df7eff3df56b4e2df33beca5(编辑抽屉呈现一致性)
  - C=f8781cbc6d5c6726bf76cfb0e73de60705db7b5d(B1 产品域,4-commit 链 6a0beb3→8eddbf6→a4e21cc→f8781cb)
  - D=ebcf07956b4e6a1cfa6d2b9fe3ad6dd40a4ea6f0(原因词表)
  - E=5a18c8a319d6298eb92fc868c818bb3b14b899df(观察状态机+导出)
  - F=d8a6bf7d75d14a18a921e623d8dc2834f2f50be5(证据聚合)
- STOP 确认:未 merge origin/main(5c50191 未动)、未 deploy、未关 issue、未动六候选分支、零 symlink 提交、零历史改写(全部 --no-ff 真合并)。

---

## 1. Fresh Gate(复核)

- worktree 干净起步于 d613e6a;`git log 7e3e71c..d613e6a` = 实现父链 c016d50→acc6756→f83740c→d613e6a,与编排者核验一致。
- 六候选 SHA 全部 `git cat-file -t`=commit 且 parent 关系核验:A/B/D/E/F 一阶父=d613e6a;C 一阶父链经 a4e21cc 回 d613e6a(merge-base=d613e6a)。

## 2. 合并拓扑(语义序 D→E→F→C→B→A,全部 --no-ff)

| # | Track | Merge SHA | Parents(第一=累计树,第二=候选) | 冲突 |
|---|---|---|---|---|
| 1 | D | `8a316ea` | d613e6a + ebcf079 | 无(D 基=FINAL_PREP_BASE) |
| 2 | E | `714dc7f` | 8a316ea + 5a18c8a | 1 处:admin/src/lib/gapCause.ts(注释块) |
| 3 | F | `aace078` | 714dc7f + d8a6bf7 | 无(TechInsightConvergence.test.tsx ort 自动合并成功) |
| 4 | C | `c4517d6` | aace078 + f8781cb | 无(backend/db/models.py ort 自动合并成功) |
| 5 | B | `0f14095` | c4517d6 + bb6c492 | 无 |
| 6 | A | `ec23695` | 0f14095 + 49d37e2 | 无(techInsight.ts/analytics.py ort 自动合并成功) |

**Integration candidate SHA(阶段 1 tip,义务批次提交后)= 见分支 HEAD**:
`0a7e377`(feat(v163-wave2-int): 阶段1 六项收口义务 + 接线收尾)ↆ 父 = `ec23695`(六合并拓扑完成点)。

### 2.1 Overlap Resolution Register(6 登记文件逐个 resolution)

| 文件 | 重叠轨 | 合并点 | resolution(精确) |
|---|---|---|---|
| `admin/src/lib/api/techInsight.ts` | A+E | merge6(ec23695) | ort 机械自动合并成功:保留 E 观察状态/导出 API 面(GapObservationMeta/GapObservationState/fetchGapObservation* 等)与 A 窗口参数面(AnswerGapQuery.window/AnalysisWindowSerialized/window params),二者区域不相交(additive 双方保留);合并后 tsc 0+vitest 全量证实 |
| `admin/src/lib/gapCause.ts` | D+E | merge2(714dc7f) | 唯一真实冲突(头部 doc-comment 块):D 侧「状态词表=open|resolved;OBSERVING NOT authorized」为 D 撰写时现实,E 已授权实现 observing → 取 E 语义行(open\|observing\|resolved,IF-1/gap_status.py),同时保留 D 的 Ownership 注记(cause 面=Track D/status 面=Track E);函数体双方零冲突(D 六新类 label/tone/conclusion/options + E gapStatusLabel observing) |
| `admin/src/lib/gapCause.test.ts` | D+E | merge2(714dc7f) | ort 自动合并成功:D 六新类选项全集断言 + E observing→观察中/未知透传断言双方保留 |
| `admin/tests/TechInsightConvergence.test.tsx` | E+F | merge3(aace078) | ort 自动合并成功:保留 F 的 U-17 修订(「无 个用户」→「涉及 \d+ 个用户 不编造 + data-panel-users 证据不可用」);「无 导出/开始观察/内容补充」断言(时为 F 撰写时现实)在阶段 1 INT-E-01 批次按授权现实修订(见 §4 INT-E-01) |
| `backend/api/admin/analytics.py` | A+D | merge6(ec23695) | ort 机械自动合并成功:A 的 source-health 窗口参数(_parse_window_bound/from/to/window echo)与 D 的 classify 证据规则扩展(gap_taxonomy import/逐会话分类)区域隔离,双方保留;合并后 obligation 相邻子集 pytest 全绿 |
| `backend/db/models.py` | C+E | merge4(c4517d6) | ort 自动合并成功:C 三新表(DocumentRepairTask/DocumentRecoveryEvent/KnowledgeSettingsPreview)与 E 两新表(GapObservation/GapObservationEvent)双方保留(additive 不同区域) |

**结论:零未知语义冲突,零产品语义发明;6/6 登记重叠全部 MECHANICAL-REGION-ISOLATED 落地。**

### 2.2 合并后快速冒烟(冲突最先暴露处)

- `npx tsc -b` = 0;vitest 重叠子集(gapCause/TechInsightConvergence/GapObservationLifecycle/GapCauseTaxonomy/TrackFEvidence)70/70;pytest 重叠子集(track_a_window_params+gap_taxonomy_causes+gap_observation+data_sources_track_c)74/74。

## 3. 六项义务 closure(Integration 收口授权:INT-E-01 改 GapPanel;INT-SYS-01 改 analytics resolve 区;INT-C-01..04 修 C-owned 缺陷,最小 diff 零新语义)

### 3.1 INT-E-01 — GapPanel 概览挂点(option a)— **CLOSED**

- 挂载(参考 PNG 侧板概览:推荐操作 导出相关对话卡+内容补充完成后段+开始观察大按钮):
  - `admin/src/pages/analytics/GapPanel.tsx`:概览 Tab 推荐操作区 = 查看相关对话(既有)→ `GapExportCard`(heading=null 避免重复区块标题)→ `GapObservationSection`(内容补充完成后段+▷ 内容已补充,开始观察 大按钮,副文案逐字「系统将验证数据同步状态，通过后进入观察中。」)。
  - `admin/src/pages/analytics/PanelHistory.tsx`:回归**纯流转时间线**(移除其内临时组合挂载的观察区/导出卡)→ 概览与历史**零重复动作**(测试断言:历史 tab 无 CTA/无导出卡)。
  - E 组件自包含保持:`GapExportCard` 新增可选 `heading?: string | null` 形参(缺省自带「推荐操作」标题,独立挂载不破坏);观察/导出后端语义零改动(消费真实 E API)。
- 壳过时缺席断言清理:`GapPanel.tsx` 头注 v1.6.3 Forbidden 清单(无导出/无开始观察)按授权现实移除并改写为 INT-E-01 挂载说明;`AnswerGapsTab.tsx` 头注「观察态 filter/导出卡=将来区域」更新。
- 证据:`admin/tests/TechInsightConvergence.test.tsx`(概览含 导出相关对话/▷ 内容已补充,开始观察/内容补充完成后/隐私条逐字 + 历史 tab 零重复 + U-17 unavailable 诚实)22/22;`admin/tests/GapObservationLifecycle.test.tsx` 11/11。

### 3.2 INT-C-01(BLOCKING)— generation-correct repair — **CLOSED**

- 修复(`backend/services/document_repair.py`):
  - 回写目标 = 该文档**现行版本在服代命名空间**:`chunk_uuids_for_version(doc_source_id, gen_id, gen_ordinal, n)`(ordinal=0→legacy 寻址;>0→`generation_uuid` 命名空间,与 gap-heal/GenerationBuilder.repair_documents 同款语义;评审授权「冻结边界=行为不变量非 HOW」,按最小 diff 保留 plan→apply→verify 逐缺失回放结构,未切换为整文档新代重物化);
  - 强制 `generation_id`/`generation_ordinal` props(账本权威,持久副本过期代归属不可覆盖);
  - plan/verify 复验口径同步在服代:`chunk_serving_for_doc(..., generation_ordinals=(gen_ordinal,))`(`backend/services/chunk_serving.py` 新增可选参数;**既有 U-9 调用方默认 None 口径逐字不变**);
  - 禁把 legacy/非在服 chunk 计为成功修复:plan 投影在服代过滤后 legacy 残片不计在服;verify 一致性只承认在服代命名空间完整覆盖;幂等保持(重复执行=no-op 0 重灌+复验通过)。
- 硬性回归(`tests/api/admin/test_int_wave2_obligations.py`,替身 GenerationAwareCollection 带 uuid 寻址+generation props=真实语义同构,非无 generation fake):
  - `test_int_c01_repair_targets_serving_generation`:before → 在服代过滤检索 miss 全部 12 目标(10 个 legacy 残片不可见);after → 同一过滤检索命中 0..11;回写对象 uuid=`generation_uuid(...)` 命名空间且带 generation props;legacy 命名空间未被写触碰;任务 consistency=passed。
  - `test_int_c01_legacy_objects_not_counted_as_success`(legacy 残片≠serving=0)、`test_int_c01_repair_idempotent_rerun`(no-op 零写)。

### 3.3 INT-C-02 — channel_visibility 持久 props — **CLOSED**

- 修复(`backend/services/document_repair.py` props 构造):去除 `["widget","api"]` 硬编码与 `if k not in props` overlay 跳过 → 持久 chunk props(灌入时完整快照)为底,账本身份字段权威覆写。
- 回归:`test_int_c02_channel_visibility_from_persisted_props_not_expanded` — 受限渠道源(api-only 持久真值)修复后 12 chunk 均 `channel_visibility=["api"]`,不扩权。

### 3.4 INT-C-03 — freshness_hours 冻结词表 — **CLOSED**

- 修复:`backend/api/admin/schemas.py` `KnowledgeSettingsUpdate`/`KnowledgePreviewRequest` `field_validator` 收敛 `FRESHNESS_CHOICES_HOURS=(6,12,24,72,168)`,非法值 → ValidationError(422 fail-loud);`knowledge_policy.effective_freshness_hours` 非空非法值 raise(禁静默回落 24);NULL→默认 24h 与 CURRENT/HISTORICAL 语义零变化。
- 回归:`test_int_c03_freshness_vocabulary_rejects_illegal_values`(词表内过/词表外 1/5/7/25/48/100/169/10000 双模型 422)、`test_int_c03_effective_freshness_fail_loud_on_corrupt_row`(NULL=24 语义不变;25 raise)。

### 3.5 INT-C-04 — LIKE/ILIKE 通配符转义 — **CLOSED**

- 修复:`knowledge_policy.policy_impact_counts`/`ledger_fingerprint` 前缀 LIKE 经 `_escape_like`(%/_/\\ 转义,escape="\\",与 data_sources._document_scope 同语义)。
- 回归:`test_int_c04_wildcard_source_id_does_not_expand_scope` — 含 `_` 的 source_id(`intwave2-*-a_b`)影响计数=1(未转义会命中相邻 `*-aXb` 源=2)、双源指纹独立。

### 3.6 INT-SYS-01(BLOCKING)— 遗留 resolve 端点收敛 — **CLOSED**

- 选择与理由:**收敛为 U-15 状态机 thin-wrapper(委托/拒绝混合)**,非 410/409 全拒 —— 保留基线调用方兼容(open 幂等读、observing→open 的旧能力),同时冻结不变量全部成立:
  - `status=resolved`:非 observing → 409 `resolve_not_allowed`(禁止直接强转;open 态即基线最常用路径亦拒);observing → 触发权威窗口评估 `evaluate_observation`(复现→OPEN/满窗→RESOLVED,判定持久化+事件留痕),未转移则 409。RESOLVED 唯一进入 = 满窗评估(不绕过前置/评估)。
  - `status=open`:observing → 委托 `abort_observation`(actor=user.email;观察行关闭 ended_reason=aborted + abort 事件,不留悬挂 active observation);resolved → 409 `reopen_not_allowed`(终态,复现走状态机);open → 幂等 no-op(无转移不伪造事件)。
  - 全部实际转移经 `backend/services/gap_observation.py` 落 gap_observations/gap_observation_events,可审计。
- 回归(6 例,`tests/api/admin/test_int_wave2_obligations.py`):open 强转 409+状态零变化+零 observation/事件;observing 未满窗强转 409+active observation 仍在窗(无悬挂);满窗 resolve → 真实 RESOLVED+window_elapsed+resolve 审计行;resolved 双向 409( reopen_not_allowed);observing→open 委托 abort+aborted+留痕;open 幂等 no-op 零事件。
- 基线测试修订(授权范围内):`tests/api/admin/test_analytics.py::test_resolve_gap_normal` 原断言 open→resolved 直接写(即本次消除的缺陷行为)→ 修订为 409+状态零变化;双树证据:候选树 ec23695 同测试断言 200/`status=="resolved"`(git show 可复现),基线行为=缺陷本体,分类=REGRESSION-BY-DESIGN(收敛即义务)。

## 4. 接线收尾

- 壳编排核对:`AnswerGapsTab`(D 词表 GapCauseFilter/E GapStatusFilter/A AnalyticsWindowControl/F GapTopicCell 全在位)→ `GapPanel`(A 窗口状态贯通:AnswerGapsTab.window → GapPanel.window prop → `toStatsWindow` 映射(预设直通 today/7d/30d/all;`range:f/t` 拆 from/to)→ PanelStats `window/from/to` props(评审留的 F 接线点,fetchGapUsers 全参透传);D DiagnosisConclusion/E 观察+导出(概览)/F PanelStats+GapTopicCell;E PanelHistory(历史)= 纯时间线)。
- 过时缺席断言修订(F 保留面,INT-E-01 所有权义务):TechInsightConvergence「v1.6.3 未授权能力不出现:无 导出相关对话/开始观察/内容已补充」→ 按 Wave 1 授权现实修订为「概览挂点存在 + 历史 tab 零重复 + U-17 权威不编造」;GapObservationLifecycle 挂点面 PanelHistory→组件直测 + 纯历史断言;TrackFEvidence fetchGapUsers 断言补 from/to 形参(机械);`test_data_sources_track_c._FakeCollection`/`vector_stack` 补 generation 语义(评审禁无 generation fake;10/12 场景意图保留)。
- 合并树类型全编译:`npx tsc -b` = **0**(admin+widget 依赖齐全)。

## 5. 迁移验证(证据:migration-*.json ×3)

| 场景 | 库 | 结果 |
|---|---|---|
| fresh DB(init_db = create_all + ensure_track_c_columns + ensure_recovery_columns) | `ask_ai_fresh_int`(新建空库) | 32 表全建;C 新表 document_repair_tasks/document_recovery_events/knowledge_settings_previews + E 新表 gap_observations/gap_observation_events + index_generations/document_version_chunks 在位;documents.content_type、data_sources.next_run_at/knowledge_role/freshness_hours、sync_requests 4 recovery 列、document_versions.generation_id/ordinal 在位;索引 ix_documents_content_type/idx_document_versions_generation/uq_version_chunks_version_index 在位 |
| 既有 DB 升级(真旧 schema:剥离 C/E 增量后升级) | `ask_ai_legacy_int2`(本地 ask_ai 副本去列/去表) | 27→32 表(5 新表全建);4 加性列全补;数据无损(1228 documents/10 sources/24 clusters/104 conversations/12 sync_runs/3 users 前后一致);默认值不伪造语义:content_type 全 NULL(存量不可用零回填)、knowledge_role/freshness_hours 全 NULL(=默认 CURRENT/24h 语义)、question_clusters 仅 open/resolved(零伪造 observing)、gap_observations/repair_tasks 空 |
| 既有 DB 升级(已是新 schema 的本地 ask_ai 副本) | `ask_ai_migrate_int2` | init_db 幂等 no-op;数据无损同上;E/C 运行时验收数据保留(gap_observations=3/repair_tasks=5);content_type 分布 page 1208/document 12/product 8(连接器真值非回填);policy 列 NULL 语义保持 |

## 6. 工程门(全量;最终树单次运行)

| 门 | 结果 |
|---|---|
| pytest 全量(串行,TEST_DATABASE_URL=ask_ai_test_int,HF_HUB_OFFLINE=1) | **2630 passed / 0 failed / 7 skipped**(128.75s;基线 2500/0/8 + 六候选测试 + INT 义务回归 13;日志 `pytest-full-run1.log`) |
| PA(tests/project_automation) | **114/114** |
| admin vitest 全量 | **63 文件 540/540**(含修订后断言;63=基线 54+E/F/D/C/B/A 新增) |
| `npx tsc -b` | **0 error** |
| `npm run build` | ✓ built(2.18s) |
| ruff(本次改动 8 后端/测试文件) | **All checks passed**(顺带修复 C 候选继承的 3 处基线项:I001×2+F841×2 于本次改动文件内;全仓其余未触碰) |
| flaky 分类 | 一次通过,零失败零复跑;无 REGRESSION/BASELINE/ENVIRONMENT 分类项 |

## 7. 阶段 2 交接(功能 E2E + 152 行参考符合性,可直接开工)

- **树**:`/Users/harryhua/Documents/GitHub/ask-ai-v163-int2`,branch `integration/v163-wave2`,阶段 1 tip 见 §2(义务批次=0a7e377);工作树干净、已 push origin。
- **runtime 栈**(阶段 2 复用):
  - 数据层:`./scripts/dev-local.sh --data`(本地 PG 容器 ask-ai-local-postgres-1 已在跑;Weaviate 同 compose);
  - 后端:`cd /Users/harryhua/Documents/GitHub/ask-ai-v163-int2 && ASKAI_API_PORT=8130 HF_HUB_OFFLINE=1 .venv/bin/python -m backend.main`;
  - admin:`cd admin && VITE_API_TARGET=http://localhost:8130 npx vite --port 5230`;
  - 登录:`admin@camthink.ai / v163review`(本地 users 表已有)。
- **seed 状态**:本地 PG `ask_ai` = 既有真实 seed(1228 documents/10 sources/24 clusters/104 conversations)+ Wave1 各轨验收残留(源 `we-src-e-runtime`、`WB_TRACKB_20260913-*`、gap_observations=3、repair_tasks=5);阶段 2 新 seed 须 `INT2_` 前缀标记并留 SQL 全文于证据目录。隔离库:`ask_ai_test_int`(pytest)/`ask_ai_fresh_int`(迁移)/`ask_ai_legacy_int2`+`ask_ai_migrate_int2`(迁移证据,可删)。
- **INT 项复验入口**(阶段 2 E2E 时核对):
  - INT-E-01:技术洞察→回答缺口→点行→概览 tab 推荐操作区(导出卡/内容补充完成后/开始观察);历史 tab 仅时间线;
  - INT-C-01:数据源→文档行「处理」修复→验证卡 consistency=passed;在服代过滤口径(回归 `tests/api/admin/test_int_wave2_obligations.py`);
  - INT-SYS-01:`PATCH /api/admin/analytics/gaps/{id}/resolve` open 态 → 409;
  - INT-C-03:知识设置新鲜度非法值(如 25)→ 422。
- **测试命令**:`HF_HUB_OFFLINE=1 TEST_DATABASE_URL="postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test_int" .venv/bin/python -m pytest tests/ -q`;`cd admin && npx vitest run && npx tsc -b && npm run build`。

## 8. 阶段 1 diff 盘点

- 合并拓扑 6 commits(§2)+ 义务/接线批次 1 commit(17 文件:+1190/−117;backend 5 文件修复 + 前端 6 文件挂载接线 + 测试 5 文件修订/新增 + 新增 test_int_wave2_obligations.py 13 例)+ 本报告(add -f)。
- 六候选分支未动;候选提交零改写(merge --no-ff 原样保留)。

---

# V1.6.3 WAVE 2 INTEGRATION — 阶段 2 执行报告(组合树功能 E2E + 152 行参考符合性收口)

- 起点复核:worktree `ask-ai-v163-int2`,branch `integration/v163-wave2`,HEAD=5dcbd7b(阶段 1 tip),工作树干净。
- 参考真值亲读:`/tmp/v163-audit-refs/{data-source-operations,technical-insights-answer-gaps}-original.png`(SHA-256 bdcaa879…/3aea88a2…,1536×1024),与本报告全部对照一致。
- 证据目录:`ask-ai-acceptance/v163-wave2-20260914/phase2/`(screenshots 35 张 @1536×1024 @1x、e2e/ 三角 JSON+seed SQL+CSV、logs/)。
- runtime 栈:backend :8130(`EMBEDDER_DEVICE=cpu`)+ admin vite :5230(`VITE_API_TARGET=:8130`)+ 本地 PG ask_ai(既有 seed 完好)+ Weaviate(经 §P2.1 环境修复后)。

## P2.0 环境就绪修复披露(零产品语义;全为部署面/环境面)

1. **Weaviate P1 生命周期地基属性补齐**(`phase2/logs/env-fix-weaviate-generation-props.log`):本地 Document collection 缺 `generation_ordinal`(INT)/`generation_id`(TEXT)属性(P1 地基迁移 `scripts/migrate_p1_lifecycle_foundation.py` 在该环境从未执行),修复链写路径必需。修复 = 调用**树内迁移脚本同一 `ensure_weaviate_schema` helper**(加性补 property)+ 对 70,580 个存量对象补 `generation_ordinal=0`(LEGACY_GENERATION_ORDINAL 语义,与迁移步骤 4 同款)。零 text/vector/uuid/PG 行改动。
2. **后端重启参数**:`EMBEDDER_DEVICE=cpu`(本机 torch 无 CUDA;`auto` 使修复嵌入阶段失败"Torch not compiled with CUDA enabled"——环境参数问题,非产品缺陷,首次失败任务 error 如实留痕于 document_repair_tasks)。
3. 本地 fixture 语义残留说明:store-woo 文档版本 generation_ordinal=900001 为 Wave 1 Track C 验收 fixture 真值,本阶段按真值消费(在服代=900001)。

## P2.1 功能 E2E(组合树真实验收;不继承轨 PASS;每项 UI→API→持久化三角)

### A — 分析窗三面同窗联动(PASS)
- 顶栏控制面(data-topbar-window)= TI 工具栏窗选择 = 同一共享窗状态(IF-7)。
- **S1** `/tech/performance`:7d→`range=7d&from&to`;30d→`range=30d…`;今日→`range=today&from=00:00:00`;显式起止→仅 `from=2026-09-01T00:00:00.000&to=2026-09-13T23:59:59.999`(不发送 range 名,符合"禁未知名静默回退");响应 `kpi.window` 回显=请求窗。UI 值一致变化:7d 样本 58 trace/真实失败 7% ↔ 今日 样本 0 trace/诚实空态(截图 05/06)。
- **S2** `/analytics/source-health`:from/to 随窗联动;响应窗字段回显=请求(`{"from":"2026-09-01T00:00:00+00:00","to":"2026-09-13T23:59:59.999000+00:00"}`)。
- **S5** `/tech/answer-gaps`:`window=30d`、`window=range:2026-09-10/2026-09-14` 全词表序列化;同参直调 API 200 total=22。
- 例外面 S3/S4/S6 未借例外引入窗口假联动(事件流/会话证据读面无窗口参数注入)。
- 证据:`e2e/e2e-a-window.json`;截图 05/06/07/08/09。

### B — 源编辑一致性(PASS)
- API 建源 201(`int2e2-b-src`,INT2E2 标记)→ UI 编辑抽屉:**类型 select 真 disabled**(真值属性非 CSS 伪装;U-5)、label「名称 *」(DEF-A2 收敛)、「自动同步」Switch + 逐字说明「开启后，系统将按设定周期自动同步。」。
- 改名 `INT2E2_B_源名A→源名B` + Switch off → 保存:PUT 200;**API GET** product=INT2E2_B_源名B/enabled=false/type 不变(woocommerce,immutable);**DB 行** `INT2E2_B_源名B | f | woocommerce`;**reload 后行可见**、重开抽屉三真值一致。
- 证据:`e2e/e2e-b-editor.json`;截图 10/11/12。create 态类型可选复核:添加抽屉 #ds-type disabled=false(截图 35,U-5 双侧)。

### C — 行级修复全链(INT-C-01 组合树回归,PASS)
- before:在服代过滤检索(source_id 精确 ∧ generation_ordinal=900001)命中 **0**(miss;legacy 残片不可见)。
- UI:详情页需处理桶 → 行「处理」点击 → POST `/documents/repair`(RBAC 内)→ 任务 succeeded:`consistency=passed, repaired_indices=[0,1,2,3], generation_id=8f9d…, generation_ordinal=900001`(**在服代权威写**:写入 uuid 族 77959ad6/d5661673/24a96d1b/0db22edb = `uuid5(NAMESPACE_URL,"doc#gen#i")` 确定性在服代命名空间,legacy 家族 0 命中=旧对象未被触碰)。
- after:同一过滤检索命中 **4**、generation_ordinal 全=900001;验证卡 = `当前有效版本 v1 / 当前服务 4/4 / 一致性验证 ✓ 通过`(=后端 result 真值);U-9 分数 4/4、U-10 恢复注记「已自动尝试恢复 1 次,未成功」同屏(=DB recovery_attempts_failed=1)。
- 证据:`e2e/e2e-c-repair.json`;截图 13/14。

### C-settings — 知识设置 CURRENT↔HISTORICAL(PASS)
- UI 抽屉(15)改时态角色 → 高风险门禁:RiskPreviewModal(16)预计影响 **受影响知识 8 / 当前资格变化 5 / 历史资格变化 3**,与预览端点 `{"affected_documents":8,"current_eligibility_change":5,"historical_eligibility_change":3}` **逐数一致**(后端权威);CURRENT→HISTORICAL 红色 diff、「不会删除持久知识。」「变更后系统将重新验证服务状态。」齐备。
- apply→**持久化**:GET knowledge-settings role=historical;DB `data_sources.knowledge_role='historical'`。
- **检索资格真实变化**:`excluded_source_prefixes_sync`(HybridSearcher 排除注入 provider,main.py 装配点)HISTORICAL 后 = `['store-woo']`,恢复 CURRENT 后 = `[]`(双向真实)。
- **drift 保护**:preview → 真实账本变更(fixture 文档行插入并保留)→ 携原 token confirm → **409**「账本已变化(影响计数 drift),预览失效」且角色零变化;无 drift 的干净 confirm = 200(保护只对真实变更触发)。
- **INT-C-03**:freshness=25 → **422**(冻结词表 [6,12,24,72,168]);UI 词表 select 仅五值。
- 证据:`e2e/e2e-c-settings.json`、`e2e/e2e-c-settings-part2.json`;截图 15/16/17。

### D — 六新原因类(PASS)
- seed(全文 `e2e/seed-e2e-d-causes.sql`,INT2E2_ 标记):每类 1 聚类 × 1 会话 × 最新 trace × 被引文档,逐类对应 IF-2 冻结证据规则(生成异常=Trace.type=generation_error;内容缺失=未回答+零源+hybrid_count=0;引用异常=[3] 越界;内容冲突=superseded 与接替者同引;内容过期=400 天>180 阈值;检索异常=min_results_met=false)。
- 后端分类(API 实测):生成异常/内容缺失/引用异常/内容冲突/内容过期/检索异常 **6/6 逐字命中**。
- UI:原因筛选词表 = 全部原因+知识缺失/服务知识不完整/拒答/低相关+**六新类**+未分类;筛选真实生效(生成异常→INT2E2 行含徽章);行点击 → 诊断结论「生成异常」因果转述。
- 证据:`e2e/e2e-d-causes.log`;截图 18/19/20。

### E — 观察状态机全链 + legacy 不绕过 + Export(PASS)
- **INT-SYS-01**:open 态 legacy resolve(status=resolved)→ **409 `resolve_not_allowed`** + 状态零变化;observing 未满窗强转 → **409**;RESOLVED 后 reopen → **409 `reopen_not_allowed`** + 仍 resolved。
- 门禁:无同步证据开始观察 → **409 `gate_failed`,gates 机器真值 `{"sync":{"INT2E2_D_new-doc":"no_sync_evidence"}}`** 且 UI 如实呈现(22);补 completed+healthy consistency 的 sync_runs 真值后(全文 SQL 见 e2e-run.log 记录)→ 开始观察成功。
- OPEN→OBSERVING:队列行「观察中」徽章(23);观察状态 API `window_days=7, window_ends_at=+7d`;**History tab 纯时间线**(导出卡/开始观察 CTA 零可见,24)。
- 复现→OPEN:观察开始后新归属会话 → evaluate → status=open,事件 `recurrence:observing→open`。
- 满窗→RESOLVED:重进观察后窗口到期(fixture 回写 window_ends_at;评估逻辑真实执行)→ evaluate → **resolved**,事件 `resolve:observing→resolved`;全事件轨迹 `start:open→observing → recurrence:observing→open → start:open→observing → resolve:observing→resolved` 全持久化可审计。
- Export(UI 点击):真实下载 `gap-conversations-00000000.csv`,headers `conversation_id,created_at,question,answer,is_answered,sources`,rows=2(=该 gap 全部归属会话,权威范围),含 fixture 问句,无 email/ip/姓名/电话列(无 PII);**审计行**:API export-audits=1(admin,window=all,row_count=2)= PG gap_export_audits count=1。
- 证据:`e2e/e2e-e-part2.json`、`e2e/export-gap-conversations.csv`;截图 21/22/23/24×2/25。

### F — 用户/源归因/主题(PASS)
- **受影响用户**(U-17):users API `users=2, distinct_sessions=2, users_available=true`(伪匿名 session_id 去重,零姓名/邮箱/IP);UI「涉及 2 个用户」(26)。诚实不可用:session_id 全 NULL 簇 → `users=null, users_available=false, unavailable_reason=session_identity_missing`,UI 不编造(27)。
- **源归因**(U-18):证据规则 `conversation_citation_identity_match`(会话引用真值 (type,product) × data_sources 精确匹配)→ items=[store-woo];UI「相关数据源」源卡(wo 品牌块)+外链深链真实到达 `/admin/data-sources/store-woo`。
- **主题**(U-19):确定性派生 `cross_question_common_factor` → 「INT2E2_D 生成异常」,3 次拉取恒同;单问句簇诚实回退代表问句(fallback 字段);UI GapTopicCell 主题式标题行 + 副行代表问句(26)。
- 证据:`e2e/e2e-f.log`、`e2e/seed-e2e-f-evidence.sql`;截图 26/27。

## P2.2 152 行参考符合性 reconcile(终局)

规则执行:REFERENCE CONFLICT=0;IMPLEMENTATION DEFECT=0(4 行原判全部实现+运行时证据后升 MATCH);PRODUCT-FUNCTIONAL GAP=0(38 行原判全部实现+运行时证据后升 MATCH);UADC 仅 4 项精确范围(6 行承载)。**终分类:MATCH 146 / USER-APPROVED DESIGN CHANGE 6 行(=UADC-1/2/3/4)。**

### SH-* 共享 chrome(16 行)
| ID | 终分类 | 证据(组合树) | 备注 |
|---|---|---|---|
| SH-01 | MATCH | 01 | 品牌=PNG1 语法,记录在案 |
| SH-02 | MATCH | 01 | 运营 组 |
| SH-03 | MATCH | 01 | 配置 组 |
| SH-04 | MATCH | 01/33 + 路由实测 | 9 项齐全可跳转 |
| SH-05 | MATCH | 01/26 | 选中态随路由 |
| SH-06 | **MATCH**(原 ID) | 33 | 系统 组含 用户管理/系统信息,/users 实测 |
| SH-07 | MATCH | 01 | 顶栏身份区 |
| SH-08 | MATCH | 阶段1 vitest + 本阶段登录会话 | 登出链未回归 |
| SH-09 | **MATCH**(原 GAP,U-2) | E2E A 三角;05/06/08/09 | 顶栏范围=共享分析窗,S1/S2/S5 真实联动 |
| SH-10 | UADC(UADC-4) | 32 | 帮助中心推迟,批准缺席 |
| SH-11 | UADC(UADC-4) | 32 | 同上(底部入口) |
| SH-12 | **MATCH**(原 GAP,U-4) | 28/29 | 折叠/展开实测 |
| SH-13 | UADC(UADC-1) | FAB 探针:三面 false,conversations/leads true | V-2 精确范围 |
| SH-14 | MATCH | 01 | 主蓝 token |
| SH-15 | MATCH | 02 | ›三级面包屑 |
| SH-16 | MATCH | 01–35 全部 | LIGHT 权威(U-1 关闭) |

### DS-P1 列表(24 行)
| ID | 终分类 | 证据 | 备注 |
|---|---|---|---|
| P1-01/02/03 | MATCH | 01 | 面包屑/标题/描述 |
| P1-04 | MATCH | 01/35 | 添加按钮+create 抽屉(U-5 create 侧类型可选) |
| P1-05 | MATCH | B 链(API 201)+既有 F 链+vitest | 创建能力真实 |
| P1-06/07/08/09/10 | MATCH | 34/35 + vitest | 搜索 11→1、状态过滤 2 行、类型过滤 vitest+运行时 |
| P1-11–P1-18 | MATCH | 01 | 列集/徽章/千分位/红数字/相对时间/⋯/下钻 |
| P1-19 | MATCH | B 保存 PUT + 阶段1 vitest | 动作真实执行 |
| P1-20 | MATCH | 01 | 异常优先排序(参考行序=板面示意,记录在案) |
| P1-21 | MATCH | 01 | 共 N 个数据源 |
| P1-22 | MATCH(带外) | 03 | 运行态面板为超出参考的真值呈现 |
| P1-23 | UADC(UADC-2) | 01 | 41px 行高(V-1) |
| P1-24 | MATCH(带外) | vitest | 空态诚实 |

### DS-P2 详情(27 行)
| ID | 终分类 | 证据 | 备注 |
|---|---|---|---|
| P2-01/03/04/05 | MATCH | 02 | 面包屑/身份/类型/最后同步 |
| P2-02 | **MATCH**(原 GAP,U-6) | 02 | 内建品牌映射「W」方块,零远程 logo_url |
| P2-06 | UADC(UADC-3) | 03 | 页内同步证据区(V-3) |
| P2-07/08/09 | MATCH | 02 | 计数行/⋯/banner |
| P2-10 | **MATCH**(原 GAP,U-14) | 02 | 逐原因行=权威桶(缺席宽限期/现行版本缺失)+证据规则 |
| P2-11/12 | MATCH | E2E C(查看需处理点击→桶过滤)/02 | |
| P2-13/14/15/17/18 | MATCH | 02 | 工作区标题/搜索/状态过滤/计数/排序 |
| P2-16/20 | **MATCH**(原 GAP,U-7) | 14 | 逐文档类型列=后端 content_type 真值(商品),类型过滤 select 在位;零前端推断 |
| P2-19 | MATCH | E2E C 展开 | chevron+名称 |
| P2-21/22/23/24 | MATCH | 14 | 状态/版本 v1/服务 正常/更新时间 |
| P2-25 | **MATCH**(原 GAP,U-8) | E2E C 全链 | 处理=真实修复工作流(RBAC/幂等/审计/进度/验证) |
| P2-26 | **MATCH**(原 GAP,U-8) | 14(重新处理/查看真相) | 行 ⋯ 收纳 |
| P2-27 | MATCH | 02 | 分页 |

### DS-P3 展开异常行(9 行)
| ID | 终分类 | 证据 | 备注 |
|---|---|---|---|
| P3-01/02/03/04 | MATCH | 14 | 展开/问题/源内容状态/当前有效版本 |
| P3-05 | **MATCH**(原 GAP,U-9) | 14 + API chunk_serving=4/4 | UI 比例=后端真值 |
| P3-06 | **MATCH**(原 GAP,U-10) | 14 + DB recovery_attempts_failed=1 | 恢复注记=持久事件投影 |
| P3-07/08/09 | **MATCH**(原 GAP,U-8) | E2E C + 14 | 重新处理→验证卡→一致性 ✓ 通过 4/4 |

### DS-P4 同步状态与活动(11 行)
| ID | 终分类 | 证据 | 备注 |
|---|---|---|---|
| P4-01 | UADC(UADC-3) | 03 | 页内 section(V-3) |
| P4-02/04/05/06 | MATCH | 03 | 最近成功/部分成功/98.7%/每 6 小时 |
| P4-03 | **MATCH**(原 GAP,U-11) | 03「下次同步: 已到期待调度」 | scheduler 权威 next_run_at,到期诚实态,零派生倒计时 |
| P4-07/08 | MATCH | 03 | 时间线+四色点 |
| P4-09 | MATCH | 03 + Wave1 F1 事件链 | triggered_by 事件 |
| P4-10 | MATCH(带内) | 03/14 | run 级恢复粒度并入 U-10 |
| P4-11 | MATCH | 03 同步按钮 | POST 受理 |

### DS-P5 编辑抽屉(9 行)
| ID | 终分类 | 证据 | 备注 |
|---|---|---|---|
| P5-01 | MATCH | 10 | Sheet 抽屉 |
| P5-02 | **MATCH**(原 ID) | B:label「名称 *」 | DEF-A2 收敛 |
| P5-03 | MATCH | 10 | 类型化连接地址字段 |
| P5-04 | **MATCH**(原 ID,U-5) | B:edit disabled=true;35:create 可选 | 双侧实测 |
| P5-05 | **MATCH**(原 ID) | B:Switch+逐字说明+toggle 持久化 | DEF-A4 |
| P5-06/07/08/09 | MATCH | 10/B 链 | 周期/取消/保存 PUT/上下文保持 |

### DS-P6 知识设置(5 行)——原 5 GAP(U-12)全部升 MATCH
| ID | 终分类 | 证据 | 备注 |
|---|---|---|---|
| P6-01 | **MATCH** | 15/17 + API+DB | 抽屉真实读写,政策列加性持久 |
| P6-02 | **MATCH** | C-settings 检索资格双向 | CURRENT/HISTORICAL 资格贯通检索(HybridSearcher 排除 provider) |
| P6-03 | **MATCH** | 15 词表五值 + 02/14 过期提醒条 | 新鲜度后端权威、过期态 Admin 可见 |
| P6-04 | **MATCH** | 16 确认→DB | 取消/保存持久化 |
| P6-05 | **MATCH** | excluded_prefixes before/after | 策略→服务一致 |

### DS-P7 高风险预览(6 行)——原 6 GAP(U-13)全部升 MATCH
| ID | 终分类 | 证据 | 备注 |
|---|---|---|---|
| P7-01 | **MATCH** | 16 | 高风险变更门禁 Modal |
| P7-02 | **MATCH** | 16 | CURRENT→HISTORICAL 红色 diff |
| P7-03 | **MATCH** | 16 计数=预览端点逐数(8/5/3) | 影响计数后端权威 |
| P7-04 | **MATCH** | 16 | 不会删除持久知识 说明条 |
| P7-05 | **MATCH** | drift 409 + 干净 200 | 确认施加与预览一致 mutation;drift 失效 |
| P7-06 | **MATCH** | 16 | 取消/确认变更(红) |

### TI-* 技术洞察·回答缺口(45 行)
32 行原 MATCH 全部以组合树新鲜证据复核保持:TI-01–06/08/10/11/13–17/19–26/28–32/38–40/44(证据=26/18/19/07/20/24/25 + 本阶段 API 实测:相关提问/影响回答计数、深链、q/状态/原因/窗口过滤、分页/页大小)。要点复核:TI-30 问题描述、TI-31 诊断结论红盒+chip、TI-32 典型问题示例+查看全部、TI-38 全量清单、TI-39 相关对话+深链、TI-40 原因分布、TI-44 已解决绿态(26/23)。
| ID | 终分类 | 证据 | 备注 |
|---|---|---|---|
| TI-07/18/42 | **MATCH**(原 GAP,U-15) | 23 观察中徽章;队列/侧板/过滤三面 | OBSERVING 词表+呈现 |
| TI-09 | **MATCH**(原 GAP,U-14) | E2E D | 六新类权威分类+筛选+徽章,禁 keyword-only |
| TI-12 | **MATCH**(原 GAP,U-19) | 26 + topic API 3 拉恒同 | 确定性派生,回退诚实 |
| TI-27 | **MATCH**(原 GAP,U-17) | 26 涉及 2 个用户;27 诚实不可用 | 伪匿名去重,零身份追踪 |
| TI-33 | **MATCH**(原 GAP,U-18) | 26 源卡 + 深链实测 | 归因源自引用真值 |
| TI-34/35/45 | **MATCH**(原 GAP,U-16) | E 导出链 + 21/25/26 | admin-only CSV、最小字段、无 PII、可审计 |
| TI-36/37 | **MATCH**(原 GAP,U-15) | 21/26 + E 链 | 补充完成后段 + 开始观察三道门 |
| TI-41 | MATCH(Tab)/GAP 归 TI-37 | 24 | 纯时间线 + 全转移可见 |
| TI-43 | **MATCH**(原 GAP,U-15) | E 事件轨迹 + 409×2 | 复现→OPEN/满窗→RESOLVED/禁强转 |

**合计:MATCH 146 / UADC 6 行(4 项:UADC-1 V-2 FAB 抑制、UADC-2 V-1 行高、UADC-3 V-3 同步结构、UADC-4 Help Center 推迟)/ IMPLEMENTATION DEFECT 0 / PRODUCT-FUNCTIONAL GAP 0 / REFERENCE CONFLICT 0。**

## P2.3 截图 manifest(phase2/screenshots/,1536×1024 @1x)
01-ds-list / 02-ds-detail-top / 03-sync-status-activity / 05-tech-performance-7d / 06-tech-performance-today / 07-answer-gaps-explicit-window / 08-topbar-explicit-range / 09-topbar-window-open / 10-edit-drawer-before / 11-after-reload-renamed / 12-edit-drawer-reopened / 13-attention-bucket-before-repair / 14-verification-card-after-repair / 15-knowledge-settings-drawer / 16-risk-preview-modal / 17-after-apply-settings / 18-cause-filter-generation / 19-cause-filter-citation / 20-gap-panel-generation-conclusion / 21-gap-panel-overview-int-e01 / 22-observation-gate-blocked / 23-observing-badge / 24-history-timeline-observing / 24-history-timeline / 25-export-downloaded / 26-panel-stats-users-sources-topic / 27-panel-users-unavailable / 28-sidebar-collapsed / 29-sidebar-expanded / 30-fab-contrast-conversations / 31-fab-suppression-ds-analytics / 32-help-center-absent-uadc4 / 33-users-page-system-group / 34-ds-list-status-filter / 35-add-source-drawer-create(35 张)。
三角记录:phase2/e2e/(e2e-a-window.json、e2e-b-editor.json、e2e-c-repair.json、e2e-c-settings.json、e2e-c-settings-part2.json、e2e-e-part2.json、export-gap-conversations.csv、seed-e2e-d-causes.sql、seed-e2e-f-evidence.sql、各 log);日志:phase2/logs/(e2e-run.log、env-fix-weaviate-generation-props.log)。

## P2.4 残留风险
1. 本地环境 Weaviate generation 属性为本阶段补齐(§P2.0);生产部署仍必须正式执行 `scripts/migrate_p1_lifecycle_foundation.py`(树内迁移,fail-closed 幂等)——本阶段为环境就绪修复,不替代部署程序。
2. `EMBEDDER_DEVICE=cpu` 为本机环境参数;部署环境应显式配置嵌入设备。
3. 1271 条存量文档版本 generation_ordinal=900001/900003 为历史 fixture 注入值(Wave 1 验收残留);索引代真值治理(index_generations 6 行)留待真实数据环境,不影响矩阵语义。
4. 观察窗 7 天满窗判定以 fixture 回写 window_ends_at 触发(评估逻辑真实执行);自然到期路径由同一 evaluate 代码承载(pytest 已覆盖)。
5. 24-history-timeline-observing.png 中 History tab 首次检查误报"导出卡可见"系 body.innerText 含隐藏 Tab 文本;以可见性探测复核 pureTimeline=true(报告已修正口径)。

## P2.5 最终三门结论建议
- **Engineering Gate = PASS**(阶段 1:pytest 2630/0/7、PA 114/114、vitest 540/540、tsc 0、build ✓、ruff 0;见 §6,佐引)。
- **Functional Gate = PASS**(本阶段:A/B/C/C-settings/D/E/legacy 不绕过/Export/F 九链全 PASS,三角证据齐)。
- **Reference Design Gate = PASS**(152 行 reconcile:MATCH 146 / UADC 4 项(6 行)/ DEFECT 0 / GAP 0 / RC 0)。
