# CamThink V1 — Issue #13 Data Integrity Reconciliation — Implementation Stage A

- 日期:2026-09-03
- 模式:SINGLE EXECUTOR — IMPLEMENTATION(Stage A;D1/D2/D3 冻结契约已由 Planner Review 批准)
- 前序:`CAMTHINK_V1_DATA_INTEGRITY_RECONCILIATION_DISCOVERY_2026-09-03.md`(docs 仓 a896764)

## STATUS: CANDIDATE_READY

| 项 | 值 |
|---|---|
| BASELINE | `1d6f6b5fe697b5f7a1b8decef1c29f51afcda937`(main) |
| FINAL_COMMIT | `7e410e0`(worktree 分支;14 files,+1861/−82) |
| BRANCH | `worktree-exec/issue13-data-integrity-20260903`(已推 origin) |
| WORKTREE | `/Users/harryhua/Documents/GitHub/ask-ai/.worktrees/issue13-data-integrity` |
| MIGRATION | `scripts/migrate_documents_path_identity.py`(幂等 + 可回滚 + 守卫合并;**未对生产执行**) |
| IDENTITY_MODEL | documents PK = `(source_id)` 路径身份;content_hash 降级为指纹索引(D1/D2) |
| RECONCILIATION_FIX | 重建分支按路径身份插入,同内容兄弟孤儿不再 UniqueViolation;IntegrityError 显式上报不吞错 |
| REPAIR_TOOL | `backend/services/corpus_repair.py` + `scripts/repair_corpus.py`(dry-run 默认/apply 显式) |
| DRY_RUN_PROOF | 见 §7 端到端演示(隔离库;零变更→精确执行→幂等收敛) |
| TESTS | **全量 1136 passed / 6 skipped / 4 errors**(隔离库 `ask_ai_test_issue13`;4 errors=tests/embedder/test_bge 真权重加载,基线既有,无 CUDA 依赖)。新增 25 例覆盖任务 A-K 全项 |
| PRODUCTION_MUTATIONS | NONE(零生产 DB/向量/容器/同步触碰) |

---

## 1. MIGRATION(Requirement 1)

`scripts/migrate_documents_path_identity.py`(风格对齐 migrate_add_sync_runs):

- **正向**:校验旧 PK=(content_hash, branch) → `DROP CONSTRAINT documents_pkey` → `ADD CONSTRAINT documents_pkey PRIMARY KEY (source_id)` → 删冗余 `ix_documents_source_id` → `CREATE INDEX ix_documents_content_hash`。
- **守卫**:同 source_id 多行(旧 PK 下同路径内容变更的历史遗留)迁移前合并,保留 `updated_at` 最新行,逐行报告;测试实证 2 行 → 1 行。
- **幂等**:PK 已为 source_id 时 no-op(仅确保指纹索引)。
- **回滚**(`--rollback`):恢复旧 PK;存在同 (content_hash, branch) 多行(新契约合法共存)时**拒绝回滚并明确报错**,不静默丢数据。
- **零回填、向量零迁移**:source_id 列本就承载完整路径串 `<source>/<branch>/<path>`,与向量 uuid5(source_id#i) 同一寻址 —— 无新增列、无数据搬运。
- 兼容:init_db create_all 自举的新环境直接获得新 PK,迁移 no-op;`tests/db/test_migration_path_identity.py` 以真实 Postgres DDL 演练旧形态表(正向/幂等/回滚/回滚拒绝四场景)。

## 2. IDENTITY_MODEL(Requirement 1/2)

`backend/db/models.py` Document:source_id(String 200)为主键;content_hash(String 64)降级为可索引指纹;branch 保留普通索引。语义冻结:

- **两个不同 source/path + 同 branch + 同 content_hash → 两行并存**(测试 A/B:`test_documents_pk.py`、`test_ingest_ledger_identity.py`);
- **禁止行归属抢占**:`_upsert_postgres` 改为按 source_id 查行 —— 行存在则原位更新(content_hash/chunk_count 等六字段),不存在则插入;**废除旧逻辑**(按 (content_hash,branch) 查行后改写 `existing.source_id`,即 Discovery RC-1 的翻转缺陷);`tests/pipeline/test_ingest.py` 两例重写:单 execute 无遗留 DELETE + 命中行绝不按内容哈希抢占(断言 WHERE 仅含 source_id);
- 重复灌入幂等(C)、内容变更单行原位演进(无旧行残留)各有一测。

## 3. RECONCILIATION_FIX(Requirement 3)

`scripts/sync.py::_reconcile_orphan_vectors`:

- **重建分支适配路径身份**:同内容兄弟孤儿(如生产实锤的 ne301 cJSON.c,其行被 ne503-apic 同内容路径占据)重建 INSERT 不再撞 (content_hash, branch) → `test_d_rebuild_same_content_sibling_orphan_no_unique_violation` RED→GREEN 契约;
- **不吞错**:IntegrityError 单独捕获 → 显式记 `EXTRA_UNRESOLVED_ORPHAN` + 警告「身份约束冲突…保留待人工核查」(`test_d2`,竞态注入验证);missing/refill/stale/orphan 四分类语义零变化(G001-G004e 既有生命周期测试全绿);
- 新增 `chunk_totals` 可选出参:退休/重建 chunk 数供共享遥测(`test_d3`)。

## 4. HISTORICAL POLLUTION DETECTION(Requirement 4)

`backend/connectors/safety.py` 新增两原语(零词表复制):

- `rel_path_from_source_id()`:复合键 → 相对路径(退化输入取尾段);
- `historical_artifact_verdict()`:**直接调用现行 `TechnicalSafetyPolicy.check_path`**(同一份 MODEL_ARTIFACT_EXTS + 尺寸词表)判定存量文档是否 invalid artifact —— .hef/.so/.bin/.onnx/.pt 等当前禁止类型全数命中,合法文本不误伤(`test_f2`);安全词表未来演进时检测自动跟随,不会漂移。

## 5. REPAIR TOOL(Requirement 5)

`backend/services/corpus_repair.py`(核心)+ `scripts/repair_corpus.py`(CLI):

- **四类操作**:RETIRE_UNSAFE_ARTIFACT(账本行+向量 / 仅孤儿向量)、REBUILD_ORPHAN_LEDGER_ROW(零 embed,按向量存量属性)、RETIRE_DELETED_DOCUMENT(仅在有权威 membership 证据时生成,与 sync reconciliation 同一证据标准)、REPORT_DUPLICATE_IDENTITY(D2 下合法共存,仅事实呈现零变更);
- **输出字段**(每条):source / path / reason / document_count / chunk_count / action / detail;
- **安全不变量**:DRY RUN DEFAULT(CLI 缺省 dry-run,`--apply` 显式);确定性(entries 按 action+path 排序、uuid 升序);幂等(行已删 → skipped "already absent";行已建 → skipped);source-scoped(`'{prefix}/%'` + 客户端前缀);只按确定性 UUID 点删(批次 500),无任何 collection 级操作;`--output` 持久化可审计 JSON;CLI 不加载 BGE(`_NoEmbedEmbedder` 让任何误入 embed 路径显式炸出);
- 工具仅本地/测试使用;对生产执行属生产写,需 `PROD_MUTATION_AUTHORIZATION_REQUIRED`。

## 6. SHARED CONSISTENCY TELEMETRY(Requirement 6)

`_consistency_facts`(scripts/sync.py)增量五键,**全部收敛进 Wave-0 既有 `SyncRun.consistency` jsonb,无第二套 observability model**:

- `duplicate_doc_count` / `polluted_artifact_chunks`:新 helper `_ledger_identity_facts` 查得(GROUP BY hash HAVING>1;按 `historical_artifact_verdict` 累计污染 chunks);
- `retired_chunks` / `repaired_ledger_rows`:reconciliation chunk_totals 出参 + 重建行数;无 reconciliation 的调用点**键省略,不伪造 0**;
- `repair_required`:恒推导 = 非健康 ∨ 存在污染;
- Wave-0 既有六键逐字节不变(`test_consistency_facts_v2.py` 三例);身份事实查询失败时**降级省键**,绝不阻塞业务同步(Wave-0「遥测尽力而为」契约,`_handle_no_change`/`_sync_one` 双点守卫)。

## 7. DRY_RUN_PROOF(隔离库 `ask_ai_issue13_demo` 端到端演示,用后已 DROP)

播种:合法 README ×2(demo+other,同内容跨源)+ 历史 x.hef 账本行(40 chunks)+ 安全路径孤儿 new.md + .onnx 孤儿向量:

```
== DRY RUN plan ==  total_entries=3, total_chunks=45
  REBUILD_ORPHAN_LEDGER_ROW  demo/main/new.md        (orphan_no_ledger_row, 2 chunks)
  RETIRE_UNSAFE_ARTIFACT     demo/main/models/x.hef  (model_artifact_ext, 1 doc, 40 chunks)
  RETIRE_UNSAFE_ARTIFACT     demo/main/old/art.onnx  (model_artifact_ext, 0 doc, 3 chunks)
after dry-run ledger 不变 | deleted uuids = 0            ← H:零变更
== APPLY ==  applied: [rebuild new.md, x.hef ledger-row, x.hef vectors(40), art.onnx vectors(3)]
after apply ledger = {new.md:1, README.md(demo):1, README.md(other):1}   ← .hef 消失;D2 共存保留;孤儿重建
== RE-PLAN after apply ==  retire entries left: 0        ← 幂等收敛
retry failed: []                                          ← J
```

单元级证明:`test_h_dry_run_zero_mutation`(零 DB/向量变更+计划确定性)、`test_i_apply_touches_only_planned_objects`(点删 uuid 集合精确断言+兄弟文档零触碰)、`test_j_apply_retry_idempotent`、`test_i2`(重建不删向量;artifact 孤儿绝不建行)。

## 8. TESTS(Requirement 7,A-K 对账)

| 项 | 测试 | 结果 |
|---|---|---|
| A | test_a_same_hash_same_branch_diff_paths_coexist + 管道口径 no_hijack | ✓ |
| B | test_b_same_hash_across_sources_coexist(+管道口径) | ✓ |
| C | test_c_repeat_ingest_same_doc_idempotent | ✓ |
| D | test_d_rebuild_same_content_sibling_orphan_no_unique_violation(+D2 竞态不吞错/D3 chunk_totals) | ✓ |
| E | test_e_delete_one_path_keeps_same_content_sibling | ✓ |
| F | test_f_historical_hef_detected_unsafe + f2 词表共享 | ✓ |
| G | test_g_safety_wins_over_admin_file_types(真 filesystem connector,.hef/.bin 白名单仍被拦,源文件零触碰) | ✓ |
| H | test_h_dry_run_zero_mutation | ✓ |
| I | test_i_apply_touches_only_planned_objects + i2 | ✓ |
| J | test_j_apply_retry_idempotent | ✓ |
| K | 迁移 3 例 + 既有回归全量(隔离库) | ✓ |

回归规模:全量 `pytest tests/` = **1136 passed / 6 skipped / 4 errors**(4 errors = tests/embedder/test_bge 真模型加载,OSError 无权重缓存 —— 基线既有,与本次改动无关,亦不依赖 CUDA)。旧契约测试处置:`tests/db/test_documents_pk.py` 重写为新身份契约(保留跨分支共存正确部分);`tests/pipeline/test_ingest.py` 旧"删旧行"断言重写为新契约两例。

执行纪律说明:验证期检测到并行会话对共享 `ask_ai_test` 全量跑测(交叉 drop_all 扰动,记忆中已有记录的已知现象),故全量回归改用一次性隔离库 `ask_ai_test_issue13`(用后即删),结果稳定复现两轮(黑格式化前后一致)。

## 9. KNOWN_LIMITATIONS

1. **迁移未对生产执行**(需独立授权窗口);生产执行前必须按 Discovery §8 快照核对各源 expected/actual 基线。
2. source_id varchar(200) 成为主键后,路径超长文档仍受 200 字符上限(与现状同界,未放宽)。
3. `_ledger_identity_facts` 的 duplicate/polluted 统计为**账本面**口径;Weaviate 侧孤儿 artifact 的检测依赖 verify_source_vectors 迭代器(每轮 O(源对象数)),未做持久化视图。
4. repair CLI 的 `--check-source` 对 git 类连接器以 fetch_all 抽取集为成员证据(与 sync reconciliation 同口径),web_crawl 用 authoritative_source_ids。
5. 并行写竞态:修复窗口必须与在线同步/人工 Admin 操作互斥(Discovery §16 风险项,本轮未实现锁)。

## 10. STAGE_B_REQUIREMENTS(移交 #14 / runtime recovery)

1. GPU/CUDA 恢复(容器级可见性 + 共享显存治理 —— 宿主运维面,非本仓代码);
2. 按本工具 dry-run 产物执行生产 repair(授权单:R1 artifact 退休 → R2 迁移 → R3 重复身份收敛,见 Discovery §13);
3. 补灌:neomind-local 12 篇 + neoruntime-sdks 新源首灌(当前 3 连败)。

## 11. FINAL VERDICT: CANDIDATE_READY

D1/D2/D3 全部落地;任务 7 项 Required Work 全部交付并有测试实证;零 CUDA 依赖;零生产触碰。待 Planner FINAL REVIEW。

**PRODUCTION_MUTATIONS: NONE**
