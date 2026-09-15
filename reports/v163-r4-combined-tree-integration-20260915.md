# V163_R4_COMBINED_TREE_INTEGRATION — Integration Report

- 任务:V163_R4_COMBINED_TREE_INTEGRATION(Integration B,Role B)
- 日期:2026-09-15
- 集成分支:`integration/v1.6.3-r4-20260915`
- **最终集成 SHA:`804f98b654e9e8c2d44408ca53bb079672f804ea`**
- 判定:**CANDIDATE READY**(待 Role A 组合树终审)

---

## 1. Baseline

- 预期 origin/main:`f4e67515af810840aa10fa800f0203c2ba290df0`
- 实际 origin/main(fetch 后独立记录):`f4e67515af810840aa10fa800f0203c2ba290df0` — **完全一致,BASELINE DRIFT = 无**。
- 集成树自该 SHA 全新独立 worktree 检出(`ask-ai-r4-integration`,非任何候选分支/他人 worktree),检出即 clean,分支起点 = 精确 origin/main。

## 2. 候选谱系矩阵(集成前审计)

全部候选 merge-base(origin/main)= `f4e6751`,behind=0(均直接派生自基线,互相独立或显式叠放):

| 候选 | tip SHA | ahead | 谱系证明 |
|---|---|---|---|
| #71 Membership Reconciliation | 196cf4b | 4 | 独立 |
| #75 Repair/Embed 413 | b46252c | 2 | 独立 |
| #72 Embedding Batch 422 | 808d2f4 | 1 | 独立;与 #75 无祖先关系(实测排除) |
| #76 Admin Credential Fail-Closed | 0a32fe9 | 3 | 独立 |
| #78 Authoritative Recall | bd98bcc(树 tip;含实现 e936587) | 3 | e936587 ∈ bd98bcc(is-ancestor 实测) |
| #77 Evidence Eligibility | f5ffa4a(含实现 07d1308) | 4 | 07d1308 ∈ f5ffa4a;#78/#77 互不包含(实测) |
| Iteration Drift R2 | 361b067 | 8 | 独立 |
| #79 Sprint Dependency Removal | 241881e | 12 | **361b067 ∈ 241881e(is-ancestor 实测)— R2 谱系由 #79 携带,未重复集成** |

重叠文件簇(集成前识别):
1. #71 × #75:`backend/api/admin/data_sources.py`、`backend/api/admin/schemas.py`、`backend/db/models.py`、`deploy/prod/migrations.json`、`scripts/sync.py`
2. #75 × #72:`tests/pipeline/test_generation_builder.py`(既知 tests-only 尾部)
3. #78 × #77:`backend/pipeline/rag.py`(依依赖序 #78 → #77)

## 3. 集成顺序与方法

依赖感知顺序,`git merge --no-ff <accepted-sha>`(零 squash、零改写、保留候选提交史):

1. #71 `196cf4b` → merge `c012298`
2. #75 `b46252c` → merge `294afc5`
3. #72 `808d2f4` → merge `610a430`
4. #76 `0a32fe9` → merge `3689680`
5. #78 `bd98bcc`(携带 e936587)→ merge `b2d0a23`
6. #77 `f5ffa4a`(携带 07d1308;在 #78 之后)→ merge `0f156a2`
7. #79 `241881e`(携带 Iteration Drift R2 361b067 谱系)→ merge `6429ae7`

顺序与任务书第 4 节一致,无偏离,无需机械性重排。

## 4. 冲突清单与逐项处置

### 冲突 1(TYPE 1 — 机械):`deploy/prod/migrations.json`(#71 × #75)
- 双方均在清单数组末尾追加登记。处置 = 双方登记全部保留、各恰好一次(共 3 条新增:`migrate_add_membership_currency.py`、`migrate_remove_contaminated_version_chunks.py`、`migrate_add_sync_request_kind.py`),既有 6 条原序原样;JSON 解析 + 无重复断言通过;#71 清单登记契约测试绿。

### 冲突 2(TYPE 1 — 机械):`tests/pipeline/test_generation_builder.py`(#75 × #72)
- 即任务书 3.C 强制复核项:既知"tests-only 尾部冲突",本次在本集成树重新证实(非沿用旧 scratch 结论)。HEAD 侧 = #75 修复重放嵌入契约测试块;另一侧 = #72 三条远程切批暴露路径测试块。处置 = 两个已验收测试块逐字全保,按原排版缝合(分隔线 + 空行),AST 解析通过。

### 冲突 3(TYPE 2 — 语义但可由冻结契约唯一裁决,集成提交 `804f98b`):`tests/scripts/test_sync_db.py`(#71 测试 × #75 INT-C-01 在服语义)
- **发现路径**:Gate C 扩展套件(admin + test_sync_db + embedder)中 `test_sync_one_uses_last_success_as_window` 红。逐层取证:① 该文件与 #71 验收树字节一致(diff=0),排除集成文本冲突;② 清库后确定性复现为 `'>' not supported between instances of 'MagicMock' and 'int'`,sync_log.error_detail 实证;③ 根因 = #75 对 `vector_consistency.py` 的在服判定(INT-C-01:无 generation_ordinal 的对象不入在服)使 #71 测试的无代 Weaviate mock 被判"整篇缺失"→ 触发 refill → 撞上测试的 MagicMock pipeline。#71 验收时旧版校验器不按代过滤,故彼时绿。
- **裁决依据**:两个冻结契约无产品行为竞争 —— #75 的"按现行代过滤"语义权威;#71 测试意图是"向量一致的源走 skip 路径"。组合树唯一正确表述 = mock 对象须携带 `generation_ordinal=0`(种子文档无 current_version,coalesce 缺省 0)即代表现行代在服对象。
- **处置**:仅改测试夹具一行(mock properties 增 `generation_ordinal: 0`)+ 补齐该测试既有的种子清理模式(新增 DataSource 种子行同 SyncLog/Document 同款 start-cleanup,消除自中毒复跑冲突);断言零改动、产品代码零改动。
- **复验**:test_sync_db.py 全文件连续两轮 3 passed / 3 skipped。

其余 #71 × #75 重叠文件(`data_sources.py`/`schemas.py`/`models.py`/`sync.py`)与 #78 × #77 的 `rag.py` 均 git 自动合并成功;逐一语义抽查:`scripts/sync.py` 上 #75 相对 #71 的 delta 仅为一行日志文案;`rag.py` 的 #78 admission 与 #77 eligibility 位于不同区域,并以 Gate B #78×#77 管线组合测试实证协同。

无 TYPE 3 冲突,未触发 INTEGRATION BLOCKED。

## 5. 最终变更文件归属(scope audit)

origin/main..最终树共 **87 个文件**(全量逐文件归属,无未解释文件):

- **#71(196cf4b)**:admin/src/*(6)+ admin/tests 新增 1、backend/api/admin/{data_sources,sync_runs}.py、backend/api/admin/schemas.py(共)、backend/connectors/github.py、backend/db/models.py(共)、backend/services/{membership_currency(新),sync_delta}.py、deploy/prod/migrations.json(共)、docs/engineering/tasks/issue71-* (2)、scripts/{migrate_add_membership_currency(新),reconcile_membership(新),sync(共)}.py、tests/{api/admin/conftest,conftest}(共)、tests 之 membership/sync_delta/sync_coverage/sync_gap_heal/sync_lifecycle/test_membership_migration_manifest 等
- **#75(b46252c)**:backend/api/admin/data_sources.py+schemas.py(共)、backend/db/models.py(共)、backend/db/session.py、backend/pipeline/generation_builder.py、backend/services/{document_repair,sync_requests,vector_consistency}.py、deploy/prod/migrations.json(共)、scripts/{migrate_p1_lifecycle_foundation(M:ghost 归属按代解析),migrate_add_sync_request_kind(新),migrate_remove_contaminated_version_chunks(新),sync(共,一行日志),sync_executor_loop}.py、reports/inc-web-embed-413-*(2)、tests 之 generation_builder(共)、vector_consistency、sync_executor_loop、db 三迁移测试、data_sources_track_c
- **#72(808d2f4)**:backend/embedder/remote.py、reports/inc-web-embed-422-remediation、tests/embedder/test_remote_batching(新)、tests/pipeline/test_generation_builder(共)
- **#76(0a32fe9)**:backend/main.py、reports/issue-76-*、tests/auth/test_admin_bootstrap_failclosed(新)、tests/test_lifespan_smoke
- **#78(bd98bcc)**:backend/pipeline/rag.py(共)、backend/retrieval/search.py、reports/issue-78-*(2)、tests/pipeline/test_issue78_*(新)、tests/pipeline/test_rag
- **#77(f5ffa4a)**:backend/pipeline/{evidence_selection,rag(共)}.py、reports/issue-77-*(2)、tests/pipeline/test_issue77_*(新)、tests/services/test_corpus_repair
- **Iteration Drift R2 + #79(241881e 携带)**:scripts/project_automation/*(7)、docs/engineering/project-automation.md、reports/{project-automation-remove-sprint-dependency,v163-project-iteration-drift-fix}(2)、tests/project_automation/*(8,含删除 test_sprint_sync.py = #79 Sprint 移除语义)

负面清单(全部实证为否):无 #80 实现(无任何 CTA/analytics/GTM/GA4 文件)、无 Wiki/内容修改、无 widget/www 改动、无生产配置/.env/凭证提交、无 Sprint 兼容逻辑恢复、无新 Iteration 清除语义、无新产品特性、无生成产物误提交(`.env`、`models` 符号链接、`node_modules` 符号链接均保持 untracked,工作树 0 脏项)。deploy/ 下仅 migrations.json;.github/ 零变更。

## 6. 测试证据

环境:全新 worktree + `uv sync --frozen --extra dev` + 依赖清单零变更证明;`HF_HUB_OFFLINE=1` 防 lifespan smoke xet 假死;主仓 models 缓存符号链接;`.env` 复制自主仓(与 #76 已知良好环境逐键一致)。

### Gate A — 候选焦点套件(全部绿)

| 套件 | 结果 |
|---|---|
| #71 membership 全焦点(10 文件) | 65 passed |
| #72+#75 embed/builder/repair(8 文件) | 94 passed |
| #76 bootstrap fail-closed + lifespan smoke | 15 passed |
| #78+#77 rag/evidence/corpus_repair | 55 passed |
| R2 + #79 project_automation 全套 | 139 passed |

### Gate B — 跨候选组合(全部实证)

- **#75 × #72**:`test_generation_builder.py` 双块共存,#72 三条暴露路径(正常轮/修复代/force_rebuild)>16 chunks 远程切批)与 #75 修复重放契约同文件同树绿(94 内)。
- **#78 × #77**:admission → rerank → eligibility 组合树 55 passed(#78 RED 契约 + #77 eligibility + corpus_repair 同树绿)。
- **R2 × #79**:Sprint-less schema + 持久 Iteration 语义(project_automation 139 passed;含 test_schedule_iteration_boundary、test_sprint_dependency_removed、test_release_iteration_boundary)。
- **#71 × migration planner**:见第 7 节。
- **#76 × real lifespan/bootstrap**:lifespan smoke 8 用例在 offline-HF 环境 15 passed 内含(bootstrap fail-closed 契约绿;CI fixture 以 monkeypatch 显式提供 ADMIN_PASSWORD)。

### Gate C — 广谱回归(最终树 `804f98b`,单跑无并发争用)

- **CI 等价后端**(`pytest tests/ -q --ignore=tests/api/admin --ignore=tests/scripts/test_sync_db.py --ignore=tests/embedder --ignore=tests/e2e`):**2264 passed / 0 failed / 2 skipped,exit 0**(2:12)。
- **扩展套件**(CI ignore 但属候选契约面):admin API + test_sync_db + embedder:**537 passed / 0 failed / 4 skipped,exit 0**。
- **后端合计:2801 passed / 0 failed / 6 skipped。**
- **前端(admin)**:vitest **67 文件 / 553 tests 全绿**(含 #71 新增 dataSourceOpsMembership 测试;553 − 548 基线 = +5);`tsc -b` exit 0。
- 仓库静态检查:CI 无独立 lint 门(build-image.yml 仅 pytest 门);前端 tsc 即类型静态门,已过。

## 7. 迁移 / 发布审计

- 解析器实跑:`scripts/release_migration_plan.py --tag v1.6.3-r4 --sha 804f98b…` → **exit 0**,输出 9 条 = 既有 6 条原序完好 + 3 条新登记各恰一次。
- scratch-DB 幂等实证(本地一次性库 `ask_ai_r4_scratch`,已建→验→删,非生产):以组合树模型 init 后剥离新列模拟"前候选存量库",三条新迁移各自连跑两轮:
  - `migrate_add_membership_currency.py`:exit 0 ×2("OK: data_sources membership currency columns present")
  - `migrate_add_sync_request_kind.py`:exit 0 ×2
  - `migrate_remove_contaminated_version_chunks.py`:exit 0 ×2
- 登记契约测试(#71):exactly-once + 列覆盖面对齐,绿。
- 注(正交观察,非缺陷):#75 两条迁移脚本经 `settings.postgres_dsn` 取 DSN(不读 TEST_DATABASE_URL),#71 迁移经 `resolve_migration_dsn`(prod+TEST_DATABASE_URL 硬失败)。两者在 prod 均无静默测试库误路由,符合 #20 守卫哲学;部署编排经生产 env 容器执行,语义正确。
- **未执行任何生产迁移。**

## 8. 失败分类与 A/B 证据(过程中出现的每一次红)

1. `test_execute_request_child_failure_schedules_bounded_retry`(tests/scripts/test_sync_executor_loop.py,#75 新增):全量套件上下文出现 2 红,隔离复跑 5/5 绿、组合树分组复跑 94/94 绿、第二次全量绿。逐合并点 bisect(294afc5/610a430/3689680/b2d0a23/0f156a2)全绿;该测试与 `sync_executor_loop.py` 相对 #75 验收树字节一致(diff=0)→ **非集成回归**。机理:测试用宿主时钟写 `next_retry_at`,claim 以 DB `now()` 比较,宿主×DB 时钟差毫秒级波动构成竞态(实测当时 skew +1.5ms;负载下波动),属环境性/候选既有顺序 flake(与 #71 评审记录的"双基线各 4 顺序 flake"同类)。**分类:baseline-existing/environmental(候选继承),零代码改动。**
2. `test_migration_p1_corrective.py` 等迁移类 setup/teardown ERROR(组合树 3 个 / #75 基线树 14 个):直接原因 = 我并行跑两套全量套件,两树迁移测试共用同名 scratch 库 `ask_ai_p1fix_test`(`ObjectInUse: database is being accessed by other users`)——**自致并发争用,非树缺陷**;隔离复跑 10/10 绿;单独跑(首轮全量)ERROR=0。**分类:environmental(测试方法学),已修正为单跑终验。**
3. `test_sync_one_uses_last_success_as_window`:见第 4 节冲突 3。**分类:跨候选测试夹具干涉(TYPE 2),已按冻结契约裁决修复(804f98b),修后全文件连续两轮绿。**

## 9. 生产动作确认(全部为否)

无 merge to main / 无 push main / 无 tag / 无 GitHub Release / 无部署 / 无生产迁移 / 无生产 DB 变更(仅本地一次性 scratch 库建删)/ 无生产对账 / 无生产 resync-reindex / 无生产 Project 变更 / 无生产配置变更 / 无 GTM-GA4 变更 / 无 Wiki 内容变更 / 无凭证轮换。产物 = 已推送的集成分支候选,终点即候选交付。

## 10. 交付

- 分支:`integration/v1.6.3-r4-20260915` @ `804f98b654e9e8c2d44408ca53bb079672f804ea`(push 至 origin)
- 报告:本文件(reports/v163-r4-combined-tree-integration-20260915.md)
- **STOP:待 Role A 组合树终审。不部署、不合并。**
