# CamThink V1 — Sync Truth + Data Integrity Integration Gate 报告

**Gate**: #11 Real Knowledge Health × #12 Persistent Realtime Sync Progress × #13 Data Integrity Stage A × #14 GPU→CPU Sync Runtime Fallback × #15 Per-source Sync History(#9 由 #12 吸收)
**日期**: 2026-09-03
**Executor**: SINGLE EXECUTOR(本窗口)
**STATUS**: **CANDIDATE READY**(待 Planner FINAL REVIEW;未合 main、未部署、零生产触碰)

---

## 1. STATUS

CANDIDATE READY。五个已验收能力(#11/#12/#13/#14/#15)整合为单一集成候选,全部冻结语义保留、四 merge 零语义丢失、全量离线回归 1359/5/0 零失败、Admin 240 全绿、双构建绿、三迁移幂等 ×2 直跑实证。

## 2. AUTHORITATIVE_BASELINE

**`272f570ad5194f36c05146a9a06f5b35be872be8`** = `origin/integration/source-center-16-17-18-20260903` tip(Source Center #16+#17+#18 集成候选,已验收)。

拓扑核验:
- `272f570` 血统 = `ce52af4`(S0 集成基线 = `c83d214`+`2a6edce`)⊃ `c83d214`(= origin/main)⊃ `1d6f6b5`(三候选集成)。
- 四个 Sync Truth 候选分支**全部直接基于 `1d6f6b5`**,即 `272f570` 的祖先——拓扑上无分叉风险,merge 无需 rebase。
- 分支本地=远端核验:五分支(`#13`/`#14`/W2/W3/SC)`git rev-parse` 本地与 origin 全部 SAME。

## 3. SOURCE_COMMITS(逐个核验,无一凭提示词猜测)

| 能力 | FINAL_COMMIT | 分支 | 基线 | 核验证据 |
|---|---|---|---|---|
| #13 Data Integrity Stage A | `7e410e0` | `origin/worktree-exec/issue13-data-integrity-20260903`(单提交) | `1d6f6b5` | 报告 docs `624a51a`;提交标题"路径寻址(D1/D2 冻结契约)" |
| #14 GPU→CPU Fallback | `88375b7`(**实现**;`bb45dd7`=其上 docs 提交,**不合入**) | `origin/codex/issue-14-w1-sync-runtime-reliability` | `1d6f6b5` | 任务给定 hash 全字匹配;报告在嵌套 docs 仓 |
| #12+#15 backend(W2 Sync Truth) | `a99788f` | `origin/worktree-exec/w2-sync-truth-backend-20260903`(单提交) | `1d6f6b5` | 报告标题即 "Issues #9/#11/#12/#15 — Shared Contract Owner" |
| #11+#15 frontend+#9(W3) | `6ad0cdd`(7 提交链 `564d479..6ad0cdd`) | `origin/worktree-exec/w3-admin-data-source-observability-20260903` | `1d6f6b5` | 报告 docs `11a3d29`(correction 闭环) |
| Source Center 集成 | `272f570` | `origin/integration/source-center-16-17-18-20260903` | `ce52af4` | 本门基线;报告 docs `23bc654` |

**#15 归属核验**:W2 报告标题即声明 #15 共管——后端历史读端点(`/sync-runs`,duration/chunks/consistency/device)在 W2;前端 SyncHistoryPanel 在 W3。**#9 归属**:W2 `/sync-status` active 判定=后端事实源("前端零启发式")+ W3 消费。**无缺环、无重复实现。**

**裁决记录:为什么不合 `bb45dd7`**:该提交把 #14 报告 force-add 进主仓 `docs/implementation/`;报告已在嵌套 docs 仓(本门报告同处),合入只会给主仓引入游离 docs 提交。任务指名实现提交=`88375b7`,照此执行。

## 4. FINAL_COMMIT / BRANCH / WORKTREE

- **FINAL_COMMIT**: `285f19a47d0f2a4b2482e83bb28d7e6f764a2b1c`
- **BRANCH**: `integration/sync-truth-data-integrity-20260903`(已推 origin,远端 hash 本地一致核验)
- **WORKTREE**: `.worktrees/sync-truth-integration`(新建,保留)

## 5. TOPOLOGY_AUDIT(集成线)

```
272f570 (SC 集成候选,基线)
  └─9a4906d  merge #13(7e410e0)      —— 零冲突
  └─029ba76  merge #14(88375b7)      —— 零冲突
  └─ef3b551  merge W2(a99788f)       —— 1 冲突文件(scripts/sync.py)已裁
  └─a7d7577  merge W3(6ad0cdd)       —— 2 冲突文件(前端)3 处已裁
  └─285f19a  style:black py312 sync.py 合并区格式对齐
```
全部 `--no-ff`,血统线性保留;`git diff --check 272f570 HEAD` 干净。

## 6. INTEGRATION_METHOD

1. **拓扑审计先行**(§2/§3),零猜测;
2. **热点重叠分析**:`git diff --name-only` 交叉——`scripts/sync.py` 四方重叠(SC+#13+#14+W2)、`backend/db/models.py` 三方(SC+#13+W2)、`backend/pipeline/ingest.py` 两方(#13+#14)、`backend/api/admin/schemas.py` 两方(SC+W2)、Admin 三文件两方(SC+W3);
3. **顺序 merge**(identity→runtime→transport→frontend):#13→#14→W2→W3,依赖方向=设备遥测消费 W2 通道、前端消费 W2 端点;
4. **语义裁决**(§7),全部记录在 merge commit message;
5. **auto-merge 区人工语义核验**(不只看无冲突标志):`_sync_one` 终局区/`_handle_no_change` 并集/`finally` 路径覆盖。

## 7. CONFLICTS & CONFLICT_RESOLUTIONS(全部语义裁决,非文本取舍)

### C1 `scripts/sync.py` `_RunTelemetry.device()`(W2 merge 时,唯一后端冲突)
- **冲突**:#14 的 nullable 适配器版(`try import record_device except ImportError`+`if record_device is None: return`)vs W2 的正主直连版(方法体内 `from ... import record_device`)。
- **裁决**:**W2 拥有 record_device 冻结通道**——取 W2 方法体与文档串;#14 适配器退役(W2 已在场,`ImportError` 分支成死代码),`record_device` 并入模块级主 import 块。
- **关键细节(避免静默破坏 #14 测试)**:#14 测试用 `monkeypatch.setattr(sync_mod, "record_device", ...)` 打**模块级属性**;W2 方法体内的局部 import 会绕过该接缝。解法=方法体引用**模块级全局名**(Python 调用期全局解析)——W2 契约(调 backend.services.sync_runs.record_device)与 #14 测试接缝同时成立。保留 #14 的 `_do` 协程关闭修复(run_id=None 时 close 协程防 RuntimeWarning)。
- **实证**:`tests/scripts/test_sync_device.py` 8 测合入后全绿。

### C2 `admin/src/hooks/useDataSources.ts` import(并集)
类型 import 并集:SC 的 `RepoDiscoveryResult` × W3 的 `SyncHealthResponse/SyncRunList/SyncStatusResponse`;W3 全部新增函数(fetchSyncStatus/fetchSyncHealth/useSyncHealth/fetchSyncRuns/useSyncStatus/useSyncRuns)保留。

### C3 `DataSources.tsx` 轮询模型(#9 闭包裁决,本门最重要前端裁决)
- **冲突**:SC 侧本地乐观态(`syncingIds`/`triggeredAt` useState,刷新即丢——恰是 #9 要消灭的启发式)vs W3 后端真值(`useSyncStatus`+`activeStatusMap`)。
- **裁决**:**active 判定唯一事实源 = W2 `/sync-status`**(W3 结构胜出);**#18 删除在途轮询并入**同一 `refetchInterval`(函数式:`hasActiveSyncs || deleting ? 5000 : false`);`syncingIds`/`triggeredAt` **退役**(W3 已重写 `handleSync`=`triggerSync.mutate` 纯净版,全文件零残留引用,grep 实证)。
- **附**:W3 的 `useSyncStatus` hook 自带"无 active 条目即停轮询"守卫(items 空时 refetchInterval 返回 false),静态 5s 不会空转。

### C4 `DataSources.tsx` 同步按钮 disabled(并集)
`isActive`(W3 后端真值)∨ `isTriggerPending` ∨ `!ds.enabled` ∨ `!isSyncEligible(ds)`(#18 删除流程闸门);title 提示保留 #18 文案。

## 8. 各能力冻结语义保留核验

### PRESERVED_11(Real Knowledge Health)
- 健康读时派生自持久事实,零 V1 快照权威:W2 `/sync-health` 五维(Connectivity/Sync/Coverage/Freshness/Consistency)代码核验(backend/api/admin/sync_runs.py:263-339);
- `expected_state` REQUIRED/OPTIONAL/DISCOVERY/EXCLUDED、九态词汇、无证据→INSUFFICIENT_DATA、Job Success≠Knowledge Health、不解析 error_detail 自由文本、RECOVERING overlay、Freshness≈2×interval——W2 实现原样,未动;
- **W3 correction(6ad0cdd)语义保留**:五维权威收归 `/sync-health`,前端只直呈不重判(前端推导净 -152 行的成果在位,本门未重新引入任何前端健康推导);
- 冻结语义注记(见 §16 KNOWN_LIMITATIONS #1):Consistency 维度消费键=missing/orphan_count/verification_failed;#13 新增键(repair_required/duplicate_doc_count/polluted_artifact_chunks)已持久化+历史可见,但不翻转健康维度。

### PRESERVED_12(Persistent Sync Progress)
- sync_runs 持久真值:stage/current/total/counters/consistency/error_summary/request_id/attempt/sync_log_id 全列在位(models 核验 20 列);
- 九阶段词汇 DISCOVER→…→DONE 未动;`stage_total NULL` 禁假百分比(`progress_fraction` None 透传)在位;
- W2 实时落笔(ingest `asyncio.to_thread`+1s 防抖 flush——504 修复)与 SC 生命周期闸门(`sync_eligible_condition`)、#13 reconciliation 在 `_sync_one`/`_handle_no_change` 并存(逐区人工核验);
- cron `request_id=NULL` 合法、刷新恢复 active run、终态稳定、per-source 独立:W2 API 测试全绿(§13)。

### PRESERVED_13(Data Integrity Stage A)
- 文档身份=source/path 寻址(D1/D2):Document PK=`source_id`,`content_hash`=指纹索引非全局身份——`tests/db/test_documents_pk.py`(同 hash 不同路径共存)绿;
- ingest 按 source 身份 upsert、兄弟 reconciliation 零 PK 碰撞、Technical Safety 压过 Admin allowlist、历史 unsafe artifact=repair 目标、repair/迁移默认 DRY RUN、facts v2 五键——#13 六测试文件全绿(§13);
- 迁移 `migrate_documents_path_identity.py` 幂等 ×2 直跑实证(`noop: already migrated (PK=source_id)`);
- **零生产 repair**(本门零生产触碰)。

### PRESERVED_14(GPU→CPU Runtime Fallback)
- GPU 优先、显式 CPU 配置保持 CPU、白名单仅 `cuda_init_failure/cuda_oom/cuda_runtime_error`、有界单向(无返 GPU/无重试环)、GPU 先释放再建 CPU、CPU 构建失败=终态——`backend/embedder/fallback.py` 原样合入,`tests/embedder/test_fallback.py`+`test_pipeline/test_ingest_fallback.py` 全绿;
- telemetry 词表 gpu/cpu/gpu_to_cpu 双侧强制(W2 服务 ValueError 越界拒绝+#14 handle 计算);
- **SHA 短路不伪造 GPU 健康**:`_record_runtime_facts` 位于 `_sync_one` 的 `finally`(覆盖全部终态路径含 no-change 早退),零活动且零回退→no-op 不落设备事实(逐行核验 scripts/sync.py:879-899,1107-1125);
- 仅 sync executor 适用;在线问答 BGE/reranker 生命周期零触碰(diff 证据:`backend/embedder/bge.py` 不在变更集)。

### PRESERVED_15(Per-source Sync History)
- `/sync-runs?source_id=` 逐 run 暴露 trigger/status/duration/documents/chunks(chunks_written=items_updated 真实语义)/vector changes/consistency facts/execution_device/fallback 三元组——W2 端点原样;
- `ingestion_skipped` 只来自 run-local 可证明事实;无全局假 delta;SHA 短路=零新增+真实一致性/运行时事实(W2+#13 在 `_handle_no_change` 的并集:counters+report2 复验+identity facts);
- W3 SyncHistoryPanel 前端呈现保留。

## 9. ISSUE_9_ABSORPTION_RESULT

**ABSORBED,BY DESIGN(无独立 #9 实现,核验通过)**。证据链:
1. W2 `/sync-status` active 判定=`sync_requests ∈ {pending,running}` ∨ `sync_runs.status=running`(含 cron NULL 直跑)——**后端唯一事实源**,刷新后重读即恢复;
2. W3 前端 `useSyncStatus`(5s 轮询,自停守卫)+`activeStatusMap` 驱动行内进度与轮询节奏;
3. 本门 C3 裁决把 SC 侧遗留的刷新即丢乐观态(`syncingIds`)**退役**——这是 #9 闭包的最后一块:刷新后 active 状态、进度、按钮态全部由持久事实恢复;
4. 测试:W2 API test_2/3/4/5/7(active/refresh recovery)+ Admin DataSources.test.tsx W3 用例全绿。

## 10. 跨契约不变量核验(1-8 逐条)

1. **同一持久事实源**:progress(W2 flusher→sync_runs)/history(/sync-runs 读同表)/health(/sync-health 派生自同表+sync_log+documents)✓ 无竞争真值(executor 只在 reconcile 后盖章=服从而非第二权威,504 golden 30 测绿);
2. **GPU 遥测入 run/history 不改健康语义**:execution_device/fallback_* 只出现在 status/runs 序列化(:158,:205-207),健康派生零消费(grep 实证)✓;
3. **#13 一致性结果入持久 consistency facts**:telemetry.consistency(facts v2)→SyncRun.consistency→history 原样暴露 ✓(健康消费面见 §16 注记);
4. **SHA 短路四方真实**:progress(阶段照走+无灌入)/history(ingestion_skipped=1+unchanged)/device(no-op)/consistency(report2+identity facts)✓;
5. **GPU 失败→CPU 成功=成功 sync+gpu_to_cpu 证据**:业务成败归 sync_log(log_entry.status=success),设备三元组独立落 run ✓ 非伪 GPU 成功、不自动降健康;
6. **reconciliation 失败不因 fetch/embed 成功被隐藏**:`_reconcile_orphan_vectors` 异常→捕获→`unresolved=全部保留`+error 上报,绝不静默(scripts/sync.py 核验)✓;
7. **cron/manual 兼容**:SC `sync_eligible_condition` 只作用于源宇宙;`--request-id/--attempt` argv 与 NULL 直跑双路径在位;504 golden+Wave-0 core 30 测绿 ✓;
8. **SC #16/#17/#18 零回归**:164 项 SC focused+Admin 240(含 discovery/delete 用例)全绿 ✓。

## 11. SYNC_PERSISTENCE_RESULT

PASS。九阶段+实时落笔+刷新恢复+终态稳定+cron NULL,代码级并集核验+46 项 sync 脚本测试(设备/核心/运行时事实/实时)全绿。

## 12. GPU_FALLBACK_RESULT / DATA_INTEGRITY_RESULT / HEALTH_RESULT / HISTORY_RESULT

- **GPU_FALLBACK**:PASS(白名单/单向/词表/SHA 真实;#14 三测试文件 27 测合入树全绿)。
- **DATA_INTEGRITY**:PASS(路径身份+幂等迁移 noop 实证+repair DRY RUN;#13 六测试文件全绿)。
- **HEALTH**:PASS(五维权威端点+前端只直呈;W2 健康三测试文件+W3 面板测试全绿)。
- **HISTORY**:PASS(per-run 15 字段+sync_log 联表+设备三元组;W2 API 测试全绿)。

## 13. 组合测试(D 项矩阵映射)

| D 项 | 覆盖测试(合入树实测) | 结果 |
|---|---|---|
| normal GPU sync | test_sync_device(gpu 路径)+test_sync_run_runtime_facts | ✓ |
| GPU→CPU 成功回退 | test_fallback+test_ingest_fallback(classify/一次界/CPU 构建) | ✓ |
| explicit CPU | test_fallback(显式 CPU 保持) | ✓ |
| SHA short-circuit | W2 realtime test_3/4+#13 no-change 组+test_8(ingestion_skipped 仅可证事实) | ✓ |
| consistency 成功/失败 | test_consistency_facts_v2+Wave-0 core(terminal success/failure) | ✓ |
| duplicate-content sibling | test_documents_pk A+test_ingest_ledger_identity+test_reconcile_rebuild_identity | ✓ |
| refresh during active sync | W2 API test_2/3/4/5/7(derive 矩阵 RUNNING/RECOVERING/WAITING/QUEUED) | ✓ |
| terminal refresh | W2 API(终态稳定)+history semantics test_8 | ✓ |
| cron run request_id NULL | W2 API test_6/test_8 | ✓ |
| per-source history | W2 /sync-runs API 测试组 | ✓ |
| health while active/recovering | test_sync_health_derivation(RECOVERING overlay) | ✓ |
| no-evidence health | test_sync_health_pure(INSUFFICIENT_DATA/unknown 不拖低) | ✓ |

全部在**合入树**(五能力共存)执行——组合语义即"同一树上全部通过",无单分支漏验。

## 14. 测试与构建汇总

| 项 | 结果 |
|---|---|
| BACKEND_TESTS(全量离线) | **1359 passed / 5 skipped / 0 failed**(49.36s;HF 隔离环境) |
| 对账 | SC 门 1275+本门新增 84(#13+#14+W2 focused 计数)=**1359 精确并集**;skip 6→5(#14 的 `pragma: no cover` ImportError 适配器分支随适配器退役,不再产生跳过) |
| focused(#13+#14+W2) | 84 passed(首跑 1 失败=共享 ask_ai_test 瞬态污染,隔离复跑通过+全量复跑通过——W2 报告 §8.7 已知基线卫生项,非本门引入) |
| SC 回归 | 164 passed |
| Wave-0+阶段⑨⑩ | test_sync_run_core+test_504_golden_regression:30 passed |
| ADMIN_TESTS | **42 files / 240 tests 全绿**(SC 37/203+W3 5/37=精确并集) |
| BUILD | admin `vite build` ✓(1.95s);`tsc -b` 0 错误(含 ../widget/src) |
| MIGRATION_TESTS | 三迁移(runtime_facts/path_identity/lifecycle)双跑幂等 ✓(直跑 ask_ai_test) |
| REGRESSIONS | 零失败;风格=black py312 增量+ ruff 全过 |
| git diff --check 272f570..HEAD | 干净 |

## 15. Worktree Bootstrap 硬边界遵守

新建 `.worktrees/sync-truth-integration`;`.env` 物理拷贝自 SC 门验证过的拷贝(追加 `EMBEDDER_CPU_FALLBACK=on` 显式声明,与 #14 缺省一致);`models/` 6.4G 物理拷贝(APFS clonefile,零 symlink);**离线加载预验通过**(BGE-m3 SentenceTransformer 1024 维,HF_HUB_OFFLINE=1);node_modules(root/admin/widget)物理拷贝;零模型重下载(全量 49s 实证);零 runtime 资产入 git(diff 集内无 models/.env)。

## 16. KNOWN_LIMITATIONS(如实上报)

1. **健康 Consistency 维度 vs #13 facts v2 的消费面缺口(交 Planner 裁决)**:W2 冻结的 Consistency 派生只消费 `missing/orphan_count/verification_failed`;#13 的 `repair_required/duplicate_doc_count/polluted_artifact_chunks` 已持久化且经 /sync-runs 历史完整可见,但**不会翻转健康维度**。这不是矛盾或静默丢弃(两契约各自语义完好、事实全暴露),但"账本污染存在"时健康可能仍显示 HEALTHY。若 Planner 要求污染可见于健康,需一次**显式的语义扩展裁决**(属 Product 语义变化,本门按"Integration only"原则不擅自扩展)。
2. **共享 ask_ai_test 顺序瞬态**(基线既有,W2 报告 §8.7 已记):focused 首跑 test_documents_pk 1 失败,隔离复跑+全量复跑均绿。权威数字以全量离线跑为准。
3. **`bb45dd7`(#14 docs 提交)未合入**:见 §3 裁决记录;#14 报告以嵌套 docs 仓为权威。
4. **生产 .env 需在部署窗口补 `EMBEDDER_CPU_FALLBACK`**(缺省=on,不补也不改变行为;显式声明便于运维审计)。
5. sync_executor_loop.py:281 SAWarning(基线遗留小修候选,与本门无关)。

## 17. PRODUCTION_FOLLOWUP_PLAN(工程验收通过后的只读生产验收步骤——**本门未执行任何一步**)

1. **迁移(按序,均可幂等重跑)**:
   a. `migrate_add_sync_run_runtime_facts.py`(sync_runs +3 列);
   b. `migrate_documents_path_identity.py`(**先 DRY RUN 看 actions 预览**,再决定;默认即 dry-run 安全语义);
   c. `migrate_add_data_source_lifecycle.py`(若生产已跑可跳过,幂等 noop);
2. **#13 repair dry-run 命令**:`python scripts/repair_corpus.py --dry-run`(默认 DRY RUN;预期 mutation 预览=historical unsafe artifact 账本行清单+污染 chunk 计数;**未见预览前绝不落真跑**);
3. **健康 expected-state 证据采集**:为 REQUIRED 源核对 config.expected_state 显式覆盖 vs 缺省 enabled→REQUIRED 推导;记录五维 as_of 基线快照(只读 `/sync-health?days=30`);
4. **runtime/device 证据**:部署后跑一次受控手动同步,核对 sync_runs.execution_device ∈ {gpu,cpu,gpu_to_cpu} 与 fallback_reason 白名单词表;GPU 健康时 SHA 短路轮应**无**设备事实(真实性检查);
5. **镜像**:CI 出 sha-<FINAL_COMMIT> 全包含 GPU 镜像;**backend+sync-cron+sync-executor 三服务必须同 tag**(update.sh 不含 sync-executor,须显式 `ASKAI_IMAGE_TAG=<tag> docker compose up -d sync-executor`);
6. **回滚锚**:sha-1d6f6b5(当前生产)或最近已验证生产 tag;迁移均为 additive(+列/索引),回滚镜像不需迁移回退。

## 18. 交付物

- 分支:`origin/integration/sync-truth-data-integrity-20260903` = `285f19a`(本地远端 hash 一致核验)
- Worktree:`.worktrees/sync-truth-integration`(保留供 Planner 复核)
- 本报告:docs 仓 `docs/implementation/CAMTHINK_V1_SYNC_TRUTH_DATA_INTEGRITY_INTEGRATION_GATE_2026-09-03.md`

## 19. PRODUCTION_MUTATIONS

**NONE。** 本门全程零生产触碰:无部署、无生产迁移、无 corpus/vector 变更、无 repair、无源变更、无 CUDA 故障注入、无 force-recreate。§17 为纯文档计划。
