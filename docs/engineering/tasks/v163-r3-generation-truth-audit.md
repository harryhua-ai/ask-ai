# V1.6.3-R3 PRE-IMPLEMENTATION TRUTH GATE — #67 Generation Truth Audit

- 性质：**PLANNING ONLY / READ-ONLY INVESTIGATION + CONTRACT AMENDMENT**。
- 审计日期：2026-09-14（Asia/Shanghai；生产容器时间以 UTC 记录）。
- 结论边界：本报告没有产品实现、schema mutation、生产写入、repair、sync trigger、generation 创建、部署、merge、tag/release 或 Issue 关闭。
- 审计对象：fresh `origin/main=94ddb64825ae873eac0a4bd2d45377172fd355e2`、规划基线 `c1ffd83cfd3d3c58f7d3ee077b5972f3f6e2765a`、生产 `v1.6.3-r2`。

## 1. Fresh main SHA

`origin/main = 94ddb64825ae873eac0a4bd2d45377172fd355e2`（`94ddb64`）。

验证动作：fresh `git fetch origin --prune` 后在独立审计工作树解析远端 ref；没有使用旧本地 ref 代替远端状态。

## 2. Planning baseline verification

- 规划基线：`planning/v163-r3-20260914 = c1ffd83cfd3d3c58f7d3ee077b5972f3f6e2765a`（`c1ffd83`）。
- 本工作树：`audit/v163-r3-truth-gate-20260914`，HEAD 起于 `c1ffd83`。
- 原有规划工作树 `/Users/harryhua/Documents/GitHub/ask-ai-v163-plan` 未复用。
- 初始和当前产品源状态均为 clean；本提交只包含 planning/docs。
- GitHub 公共 Issue 页面在本审计时仍将 #61–#67 显示为 Open；公共未登录页面不显示 Project V2 item 字段，且本机 `gh` token 已失效，所以 Project V2 的字段值仅采用规划基线中已记录的 Project 身份/Iteration 快照，不宣称本次重新写入或刷新了 Project 元数据。
- 规划基线记录的 Project 身份：`@harryhua-ai's ask-ai project`，PVT `PVT_kwHOAgcvyM4Bisg3`，number `2`；Iteration field `PVTIF_lAHOAgcvyM4Bisg3zhhk-sE`，v1.6.3 option `4ce642b8`。该信息用于识别范围，不产生任何 Project mutation。

## 3. Production identity

只读探针在 `tesla-t4` 上确认：

- backend、sync-cron、sync-executor 镜像均为 `ghcr.io/harryhua-ai/ask-ai:v1.6.3-r2`。
- `/health`：`status=ok`、`version=1.6.3-r2`、`git_sha=fd5ca39d7ee1097abe10de513ce7e595f159270a`、`app_mode=production`。
- backend、sync-cron、sync-executor running/healthy；PostgreSQL、Weaviate healthy；未执行写操作。
- 生产读取时间锚：host UTC `2026-09-14T07:42:52Z` 附近；Weaviate/PG 统计为同一审计窗口读取。

## 4. #67 root truth model

### 4.1 真实实体语义

`DataSource` 是配置/调度源身份，不是知识内容本身。`Document` 是 `<data_source_id>/<branch>/<rel_path>` 的路径身份，一条真实源文档一行。`DocumentVersion` 是该路径的版本链节点；`current_version_id` 是现行版本关系。`DocumentVersionChunk` 是现行/历史版本的持久 chunk 副本，不含向量，但足以重建向量投影。

`IndexGeneration` 是一次构建单元的 P 轴状态行；`ready` 不等于在服，是否在服由 current version 关系决定。迁移初始代 ordinal 0 是确定性 `*legacy*` sentinel，用于保持既有 Weaviate 对象寻址。`Vector object` 是 Weaviate `Document` collection 中一条 chunk 对象。`Serving` 是当前 lifecycle + current version 的服务账本，并由 Weaviate chunk 投影核验。`Retrieval` 使用 PostgreSQL 派生的 active generation ordinal 过滤 Weaviate 检索。

### 4.2 已证实的根因分解

1. **ordinal 0 / 0 / 0：迁移初始代的 bookkeeping 语义，不是内容为空。** `ensure_legacy_generation()` 创建 `source_id="*legacy*"`、`ordinal=0`、`ready` 的行，但不填 `doc_count/chunk_count`；迁移随后把现有文档版本和 Weaviate 对象归到 ordinal 0。迁移 verify 比对的是版本 chunk 总和与 Weaviate 对象数，不要求 generation 行计数回填。
2. **ordinal 1 / failed / 0 / 0：embedding 阶段真实失败。** 生产 `sync_run=3117`（`neomind-dashboard-local`）记录 `生成 1 构建失败(embed)`，失败证据为 `internal embeddings HTTP 422: batch too large: 488 > 16`；没有版本激活。
3. **ordinal 2 / ready / 0 / 0：一个 fetched candidate 进入空 prepared 集合的可达代码路径。** 生产 `sync_run=3130`（`website-camthink`）为 `docs_total=1/docs_done=1/extracted=1`，该 run 的 `sync_log` 为 `items_new=1/items_updated=0/items_deleted=0/items_unchanged=0`，但 generation #2 为 ready 0/0；对应 16:20–16:40 UTC 窗口没有新 `documents` 或 `document_versions` 行。源码显示：切分为空时跳过该文档；`all_texts=[]` 时不做 embedding；Phase 5 仍可对空 `prepared` 集合标记 ready 0/0；`accounting.new_docs` 又按原始 `rebuild_docs` 计入 1。因此这里不是“已激活 1 篇但计数漏写”，而是“候选计入变化量但没有形成可激活的文档/版本”。具体为空的内容切分原因未由保留日志证明，不能再细归因。

### 4.3 结论

当前 PostgreSQL 版本/持久 chunk 账本和 Weaviate 实际对象足以解释实际 serving/retrieval；generation 行计数对迁移 sentinel 和空构建并非完整性账本。问题是 Generation/覆盖/一致性在 Admin 中的表达契约，不需要新 Generation subsystem。Generation 历史仍只能作为技术证据，不能作为管理员的默认健康结论或 serving 数量。

## 5. DataSource→Document→Version→Generation→Chunk→Vector→Serving→Retrieval trace

| Entity | Authoritative store / identity | Cardinality / lifecycle / creation and retirement | Production use / admin actionability |
|---|---|---|---|
| DataSource | PostgreSQL `data_sources.id`；source config 一行 | 当前 15 个 enabled source；`sync_interval`、`next_run_at`、enabled 是调度事实；删除走 source lifecycle | 调度、同步设置、源级操作；管理员可编辑/同步/删除 |
| Document | PostgreSQL `documents.source_id`，复合路径身份 | 一条真实路径一行；`active/missing_candidate/superseded/deleted/discovered`；同步构建或账本修复创建，tombstone/接替退出 serving | 知识数量、状态、需处理/修复；管理员可查看真相/修复此知识 |
| DocumentVersion | PostgreSQL `document_versions.id`；`(source_id,version_seq)` 唯一 | 一路径多版本；恰一 current active 版本；内容变化新版本，旧版 superseded，保留至 GC | 当前版本、变更链、代归属；管理员只需在查看真相/技术证据中核查 |
| Generation | PostgreSQL `index_generations.id`；全局唯一 ordinal；source-scoped build rows + `*legacy*` sentinel | pending→processing→ready/failed；ready 只有被 current version 引用才有服务意义；无引用后 retired/GC | 构建失败/技术关联有用；默认不支持管理员决策，不能直接显示为完整知识数 |
| Chunk | PostgreSQL `document_version_chunks(version_id,chunk_index)` | 一个版本的归一化正文副本；随版本保留；可重建 serving projection | 持久 chunk 总数是一致性分母；一般不作为业务主数量 |
| Vector object | Weaviate `Document`；对象 properties 含 `source_id/chunk_index/generation_id/generation_ordinal` | 通常一 chunk 一对象；generation-specific UUID；旧代对象待 GC，不以 Weaviate 反推 PG 账本 | 只读实际 serving 观察、修复核验；不直接作为知识总数 authority |
| Serving | PostgreSQL `documents.current_version_id` + lifecycle `SERVING`；Weaviate 对象交叉核验 | current version 关系翻转即切换；superseded/deleted 退出服务集合；chunk serving 为 expected indices 与实际对象交集 | 管理员最关心的“当前在服/不完整”；支持修复/判断是否需要处理 |
| Retrieval | PostgreSQL active generation ordinal provider → Weaviate filter；`main.py` wiring | 当前 active ordinals 由 current version/lifecycle distinct 派生；空集 fail-closed 为零结果 | 支持回答可用性边界；管理员需要“检索一致性”结果，不需要 generation ID |

源码指针：`backend/db/models.py:41-208,318-368,412-471`；`backend/services/document_lifecycle.py:63-99,171-221,269-302,340-385,458-508`；`backend/pipeline/generation_builder.py:135-197,203-215,249-299,372-443`；`backend/services/chunk_serving.py:1-11,24-114`；`backend/services/vector_consistency.py:1-10,24-56,59-190`；`backend/retrieval/search.py:139-178,222-252`；`backend/main.py:364-403`。

## 6. Production distribution/evidence

### 6.1 Generation and ledger distribution

| Fact | Read-only production result |
|---|---:|
| enabled DataSource | 15 |
| `index_generations` rows | 3 |
| current `documents` | 12,000 |
| `document_versions` | 12,000; all current active versions point to generation id `2862ac48-e00f-57d5-a834-cd8bd0a4a562`, ordinal 0 |
| `document_version_chunks` | 147,999 |
| current docs without `current_version_id` | 0 |
| dangling current version / current not active / current without generation | 0 / 0 / 0 |
| Weaviate `Document` objects | 147,999 |
| Weaviate objects missing `generation_ordinal` | 0 |
| Weaviate ordinal distribution | `0: 147,999` |

Generation rows：

| Ordinal | Source | Status | doc_count/chunk_count | Evidence |
|---:|---|---|---:|---|
| 0 | `*legacy*` | ready | 0 / 0 | id `2862ac48-e00f-57d5-a834-cd8bd0a4a562`; created 2026-09-11 12:39:47 UTC; migration sentinel |
| 1 | `neomind-dashboard-local` | failed | 0 / 0 | id `69ff50ef-86fe-4f13-b7e5-162601f7d093`; EMBED HTTP 422 |
| 2 | `website-camthink` | ready | 0 / 0 | id `79b343db-b962-4296-9825-5b5d977c3901`; no version/object activated |

### 6.2 Source distribution

| Source | Current docs | Weaviate chunks |
|---|---:|---:|
| `aitoolstack-local` | 37 | 955 |
| `knowledge-support-cases` | 179 | 481 |
| `lowpower-camera-local` | 2,421 | 36,841 |
| `meta-hailo-os-local` | 27 | 93 |
| `ne301-local` | 5,534 | 67,714 |
| `ne503-apic-69d3594b` | 1,399 | 20,198 |
| `neomind-dashboard-local` | 17 | 231 |
| `neomind-devicetypes-local` | 132 | 826 |
| `neomind-extensions-local` | 489 | 3,665 |
| `neomind-local` | 873 | 10,953 |
| `neoruntime-apps-1eea74dd` | 59 | 281 |
| `neoruntime-sdks-67cbac8f` | 195 | 1,353 |
| `website-camthink` | 130 | 381 |
| `wiki-documents-local` | 467 | 3,913 |
| `woocommerce-mall` | 41 | 114 |
| **Total** | **12,000** | **147,999** |

### 6.3 #62 cadence and #65 counter evidence

- All 15 production sources read `sync_interval=24h`; `next_run_at` lies around the next UTC day.
- On 2026-09-11, automatic runs for the source set repeat approximately hourly; for example the all-source sequence advances at 05:06, 06:09, 07:12, 08:14, 09:17, 10:19, 11:22 UTC. These rows are `triggered_by=cron`; they are not a 24-hour due schedule.
- The 2026-09-11 16:29 website run is an explicit counter-unit warning: `items_new=1`, while the generation produced no persisted document/version and `items_updated` is written from `chunks_written + len(metadata_docs)`.
- Latest 2026-09-14 no-change runs report `items_new/items_updated/items_deleted=0` and `items_unchanged=document count`; consistency facts report `missing=0`, `orphan_count=0`, `actual_chunks=expected_chunks` per source.

## 7. Explanation of the current Generation #0 / documents 0 / chunks 0 phenomenon

The three numbers are fields on the `IndexGeneration` row, not a live serving count. `ensure_legacy_generation()` inserts the migration sentinel with default zero counters. `migrate_p1_lifecycle_foundation.py` then creates 12,000 initial versions in that generation and copies 147,999 Weaviate objects into 147,999 persistent chunk rows, while its verification compares version chunk sum to Weaviate ordinal-0 object count rather than backfilling the sentinel counters.

Therefore the truthful interpretation is:

`Generation #0 = migration-initial sentinel; generation counters unavailable/not a completeness measure; current serving is established by current-version relations and chunk/object consistency.`

The current UI renders `generation.doc_count` and `generation.chunk_count` as if they described the knowledge’s complete build. That presentation is misleading. The fix is a semantic display correction and explicit technical-evidence labeling; no generation subsystem or production backfill is authorized by this audit.

## 8. Coverage semantic verdict

**Verdict: AMBIGUOUS (narrow calculation valid; current label over-broad).**

`_coverage_dim()` only calculates `extracted / accepted` when the latest `SyncRun.counters` has structured connector counters and `accepted > 0`. This is a denominator for accepted candidate items in a qualifying connector run. It is not a denominator for the complete source universe, all persisted documents, all routes, or all knowledge expected by an administrator.

Required presentation:

- label the dimension `知识覆盖` only with a description such as “本次全量候选抽取覆盖”；
- if `accepted/extracted` is absent, show `暂不可评估` and explain that no authoritative denominator exists for this source/run;
- never derive a percentage from `documents` count, previous total, Weaviate count, or UI arithmetic;
- keep raw `accepted/extracted/run_id` under `高级诊断`.

Source: `backend/api/admin/sync_runs.py:299-314`; UI currently labels the card only `覆盖` in `admin/src/components/dataSources/SourceHealthPanel.tsx:53-75`.

## 9. Retrieval-consistency semantic verdict

**Verdict: VALID after wording correction to `检索一致性`.**

The current consistency calculation validates the latest run’s PostgreSQL expected chunk ledger against actual Weaviate object observation for the source: missing chunks, extra/orphan objects, stale indices, polluted artifacts, and `repair_required`. It does not validate generation row counters, source-universe coverage, answer quality, recall, ranking, or citation URL correctness.

Production currently provides `actual_chunks=expected_chunks`, `missing=0`, `orphan_count=0`, `repair_required=false`, and `stale_chunk_count=0` in the latest no-change runs. This supports “current indexed chunk projection matches the PG serving ledger,” not “the generation is complete” or “AI answers are semantically complete.”

Sources: `backend/api/admin/sync_runs.py:334-376`; `backend/services/vector_consistency.py:24-56,59-190`; `admin/src/components/dataSources/SourceHealthPanel.tsx:53-75`.

## 10. Current misleading/unsupported UI semantics

| UI concept / current label | Frontend field | Backend/DB source | Classification | Finding and required meaning |
|---|---|---|---|---|
| `生成真相` | `generation.ordinal/status/doc_count/chunk_count` | `DataSourceDocumentTruth.generation` → `index_generations` | **MISLEADING** | fields are real but #0 0/0 is sentinel bookkeeping, not serving completeness; #2 proves ready 0/0 can be an empty build artifact |
| `文档` / `共 N 条(账本 N 篇)` | documents list `total/ledger_total/items` | `documents` source prefix and lifecycle | **VALID** | path-identity document count and lifecycle are authoritative |
| `chunk` / `serving_chunks / total_chunks` | `chunk_serving` | persistent version chunks + Weaviate exact object/index set | **VALID** | valid current-version chunk serving projection; unavailable must remain unavailable |
| `覆盖` | health `coverage.state/evidence` | `accepted/extracted` only when present | **AMBIGUOUS** | real candidate-extraction ratio, not full-source coverage; denominator must be named or result unknown |
| `索引生成` | generations `items/total/serving_ordinals` | `index_generations where source_id == source_id` | **MISLEADING** | `*legacy*` ordinal 0 is excluded from source-specific list, so “该源尚无索引生成记录” can coexist with serving docs |
| `一致性` / intended `检索一致性` | health `consistency.state/evidence` | latest SyncRun consistency from PG↔Weaviate | **AMBIGUOUS** | calculation is valid but current one-word label does not state the validated relation or its limits |
| `在服` / `正常` | document `serving` | lifecycle SERVING + resolvable current version | **VALID** | document serving status is ledger truth; chunk projection is a separate consistency observation |
| Generation ID/history | ID is returned in API; history table shows ordinal/status/times | PostgreSQL generation rows | **VALID** | the fields are valid technical correlation evidence, but not an admin decision surface; keep them secondary/technical and never invent user action from them |

Every row above uses exactly one of the required four-way verdicts; `TECHNICAL EVIDENCE` is a disposition, not a substitute verdict.

## 11. Administrator actionability matrix

| Item | What admin understands / decision | Action | Disposition |
|---|---|---|---|
| Source identity, enabled state, sync cycle, next due | Which source is being operated and when automatic sync is expected | Edit settings, sync source, inspect schedule | **PRIMARY** |
| Current document count and lifecycle buckets | How many knowledge documents exist and which need attention | Filter, inspect, repair a document, adjust source | **PRIMARY** |
| Latest sync result and added/updated/retired delta | What the latest completed source sync changed | Investigate failed/partial result; follow up on source | **PRIMARY** once units are signed |
| Sync reliability (30d) | Whether automatic sync history is reliable enough as historical context | Escalate recurring failure or inspect activity | **PRIMARY** |
| Data freshness | Whether last successful sync is within configured policy | Adjust freshness policy or trigger sync | **PRIMARY** |
| Knowledge coverage | Whether a qualifying full-run candidate extraction ratio is known | Investigate source/run when degraded; no action when unknown beyond inspect evidence | **SECONDARY** with explanation; no fake percentage |
| Retrieval consistency | Whether current PG chunk ledger and vector projection agree | Use `修复此知识` for a document or inspect run evidence | **PRIMARY** as operator health, with precise description |
| Generation ordinal/status/counters | Which technical build row or failure is correlated with an incident | Correlate logs; do not infer serving completeness | **TECHNICAL EVIDENCE** |
| Generation ID and full history | Exact incident/DB correlation key and lifecycle history | Copy/use in engineering investigation only | **TECHNICAL EVIDENCE** |
| Service readiness, answer recall, true source-universe coverage, recommended business action | Not currently supported by the five dimensions | Requires separate product/backend contract | **UNAVAILABLE / out of #67 Phase 1** |

An administrator does not need Generation ID/history in the default interface. The default decision loop is source schedule → latest sync → current knowledge/lifecycle → retrieval consistency → repair or inspect. Generation identifiers remain valuable only when a technical incident needs cross-system correlation.

## 12. Final Health & Diagnostics information architecture

Keep the approved five-zone page and make zone ⑤ `健康与诊断` default-collapsed below the main work surface. Inside zone ⑤:

1. `数据源健康`：连接状态、同步可靠性、知识覆盖、数据新鲜度、检索一致性；backend state/evidence/as_of are passed through, with no frontend health re-judgment.
2. `高级诊断`：raw evidence, thresholds, run ID, expected/actual, missing/orphan, generation ordinal, and coverage denominator facts; collapsed by default.
3. `索引生成记录`：technical evidence only. A migration sentinel must be explicitly labeled `迁移初始代`; its zero counters must be labeled `计数不可用于完整性判断`, not presented as current knowledge count. Source-specific empty history must say `没有该源的独立构建记录；当前服务状态请看文档/版本/检索一致性`, not “该源没有索引”。
4. Document truth remains in the knowledge table’s `查看真相` expansion. `serving` and `chunk serving` remain distinct facts.

No new navigation level, Service Readiness inference, answer-quality health, or full-source coverage algorithm is authorized by #67.

## 13. #67 product verdict: B

**B. EXISTING TRUTH SUFFICIENT WITH PRESENTATION CORRECTION**

Reasoning:

- The production serving set is deterministically derivable from current version/lifecycle relations and is cross-checked against persistent chunks and Weaviate objects.
- Retrieval consumes active generation ordinals derived from that serving relation; generation row counters are not the retrieval authority.
- The migration sentinel and empty-build row expose a presentation/contract mismatch, but not a missing store for the administrator’s primary decisions.
- The source-specific generations API’s exclusion of `*legacy*` means generation history is incomplete as a default business surface; relegating it to technical evidence and labeling absence accurately resolves the product semantic issue without inventing a subsystem.
- A non-empty post-migration generation should still be verified in an authorized isolated test state during Track B implementation; this audit did not create one because generation creation and all production mutation are forbidden here. That deferred test is an acceptance requirement, not an unresolved reason to invent backend truth now.

## 14. Exact contract amendments

The following appendices are added to the existing planning package:

- `v163-r3-data-source-design-contract.md` — supersedes the old “Generation frozen until audit” gate with the post-audit technical-evidence semantics; fixes coverage and retrieval-consistency wording; records #0/#2 evidence and B verdict.
- `v163-r3-acceptance-matrix.md` — adds R3-67-TRUTH, legacy sentinel display, coverage denominator, retrieval-consistency boundary, and deferred isolated non-empty-generation verification; keeps all evidence cells PENDING until execution.
- `v163-reference-remediation/r3-track-a-contract.md` — unfreezes only the Generation presentation contract after this audit; keeps generation technical-only and keeps #65 blocked on unit signoff.
- `v163-reference-remediation/r3-track-b-contract.md` — records no GENFIX migration/backfill in the current scope; retains #62 due-gate work, #65 unit audit, and isolated non-empty-generation test as independent implementation obligations.
- `v163-r3-release-plan.md` — updates the dependency wording so #67 audit is complete, A’s Generation presentation may be implemented under the corrected contract, and B still owns due-gate/unit verification.

Track C and Track D contracts are intentionally untouched.

## 15. Track A final scope

Track A may implement the approved UX scopes for #61/#66 and the #67 Phase-1 health language/layout. The Generation subsection is now permitted to:

- label `*legacy*` ordinal 0 as `迁移初始代`;
- never use `doc_count/chunk_count` from that row as a serving or source knowledge total;
- show “计数不可用于完整性判断” beside sentinel zero counters;
- keep generation rows under technical evidence/secondary diagnostics;
- state when source-specific generation history excludes the migration sentinel;
- label the health card `检索一致性` and describe PG expected chunks vs Weaviate observed chunks;
- label coverage as candidate-extraction coverage and show `暂不可评估` when no denominator exists.

Track A may not calculate counts, coverage, health, serving status, or business impact in the frontend. #65 delta copy remains gated by Track B’s unit signoff.

## 16. Track B final scope

Track B remains responsible for:

- #62 authoritative automatic due gate: `enabled AND sync-eligible AND no inflight AND next_run_at <= now`; manual/sync-all/repair/recovery/explicit CLI semantics remain immediate;
- #62 time-advance tests and `next_run_at` equals the real next automatic execution;
- #65 audit-lite and a corrected authoritative unit contract for each `items_*` field;
- #67 isolated deterministic test with a non-empty prepared generation, proving `doc_count=len(prepared)` and `chunk_count=sum(prepared chunks)` are persisted and aligned with versions/objects; no production mutation;
- retaining the migration sentinel as technical evidence unless a later approved product requirement proves a backend model gap;
- no production migration/backfill from this audit. Any future GENFIX must be separately authorized through the migration bridge.

## 17. Confirmation whether #62/#65 remain implementation-ready

- **#62: YES — independently implementation-ready.** Fresh production evidence confirms 24h config/next-run projection versus approximately hourly cron runs. It is a scheduling execution defect and does not depend on Generation.
- **#65: NO for immediate implementation, YES as an independent workstream.** Current code writes `items_new=len(accounting.new_docs)`, `items_deleted=tombstoned`, `items_unchanged=len(accounting.unchanged_docs)`, but `items_updated=accounting.chunks_written + len(accounting.metadata_docs)`. Thus updated is not one stable knowledge/document unit. Track B must sign or repair the unit contract before Track A renders “新增/更新/淘汰知识”. This is not a Generation blocker.

## 18. Remaining blockers / Product decisions required

1. Role A must approve this B verdict and the exact technical-evidence language before implementation.
2. Track B must complete the #62 due-gate tests.
3. Track B must complete #65 unit signoff; until then, no knowledge-unit delta labels.
4. Track B must run the non-empty generation test in an isolated data state; this audit intentionally did not create a generation.
5. If the product later requires per-source generation history including migration provenance as an operational object, that is a new backend/product-model decision. It is not required for the current admin operator loop.
6. All seven acceptance gates remain open; this audit is not an implementation or final acceptance pass.

## 19. Contract paths

- `docs/engineering/tasks/v163-r3-generation-truth-audit.md` (this report)
- `docs/engineering/tasks/v163-r3-data-source-design-contract.md`
- `docs/engineering/tasks/v163-r3-acceptance-matrix.md`
- `docs/engineering/tasks/v163-reference-remediation/r3-track-a-contract.md`
- `docs/engineering/tasks/v163-reference-remediation/r3-track-b-contract.md`
- `docs/engineering/tasks/v163-r3-release-plan.md`

## 20. Planning branch + exact candidate SHA

Candidate branch: `audit/v163-r3-truth-gate-20260914`.

The planning baseline remains `planning/v163-r3-20260914@c1ffd83`; it was not rewritten from its existing worktree. After the documentation-only commit, this candidate branch will be pushed as the reviewable planning candidate and its exact SHA will be recorded in the handoff response. No product source commit is included.

## 21. Product-source diff audit

Required audit result after commit:

- product source directories (`backend/`, `admin/src/`, `scripts/`, `deploy/`) changed: **0**;
- changed paths are planning documents only;
- `git diff --check`: required clean;
- baseline test attempt: root `pytest -q` is environment-blocked before collection by missing `sqlalchemy`; `admin/node_modules` is absent, so frontend tests/build were not run; no dependency installation or source mutation was performed.

### Evidence boundary

Production evidence was collected by read-only host/container health reads, PostgreSQL `SELECT` queries, Weaviate schema/object iteration, and log reads. No `POST`, `PUT`, `DELETE`, sync trigger, repair, generation creation, schema change, or data repair was executed.

### Final governance state

This report is a **Truth Gate / contract-preparation artifact**, not a product implementation, not a release, not an Issue closure, and not a declaration that Product Iteration v1.6.3 is complete.
