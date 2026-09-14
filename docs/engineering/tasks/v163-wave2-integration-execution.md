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
