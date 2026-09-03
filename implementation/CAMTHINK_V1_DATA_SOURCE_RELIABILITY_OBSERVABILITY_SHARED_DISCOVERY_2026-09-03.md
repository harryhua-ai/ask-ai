# CamThink V1 — Data Source Reliability & Observability
# W0 Shared Discovery / Contract Freeze

- **日期**:2026-09-03
- **执行模式**:SINGLE EXECUTOR — DISCOVERY ONLY(CODE_MUTATION = NONE,PRODUCTION_MUTATIONS = NONE)
- **仓库**:harryhua-ai/ask-ai(本地 `/Users/harryhua/Documents/GitHub/ask-ai`)
- **覆盖 Issue**:#9 / #11 / #12 / #14 / #15(#13 orphan 修复仅预留 telemetry 接口,不在本轮)
- **用途**:为下一轮 W1/W2/W3 三 worktree 并行实现冻结统一 Engineering Contract

---

## 1. Executive Summary

**结论:READY_FOR_PARALLEL_IMPLEMENTATION(THREE_WAY,附文件级所有权与 hunk 级冻结)。**

核心事实:

1. **Wave-0 已把运行真相落库,但只写不读**。`sync_runs`(一行 = ONE SOURCE × ONE ATTEMPT)已在生产运行,9 个 canonical stage、`stage_current/stage_total`(NULL=分母未知,禁止假百分比)、`counters/consistency/error_summary/sync_log_id/request_id/attempt` 全部存在(`backend/db/models.py:248-300`)。**但整个读侧(API+前端)零消费**——`derive_run_state`(`backend/services/sync_runs.py:264-293`)目前只有测试引用。#9/#11/#12/#15 的后端工作 = 补读侧 + 补少量事实列,不是重建状态体系。
2. **#9 根因实证**:"同步中"是 `DataSources.tsx:345-346` 的两个 React `useState`(`syncingIds`/`triggeredAt`),刷新即失;后端 202 响应里的 `request_id` 被前端丢弃(`backend/api/admin/data_sources.py:642-646` 返回,`admin/src` 零引用);完成判定靠 `last_sync` 时间戳推进的启发式(`DataSources.tsx:637-695`)。**不存在任何读取 active request/run 的 API**。
3. **#14 边界清晰且结构性有利**:sync runner 是 executor 每次 spawn 的**全新子进程**(`scripts/sync_executor_loop.py:290-309`),BGE 模型每 run 新载、进程退出即释放——**进程边界已天然存在**,same-process GPU→CPU 降级(重建 embedder 实例)在此边界内可靠。当前代码**零回退**:`detect_device` 显式值原样放行(`backend/embedder/base.py:25-26`),批量 embed 失败的"逐 doc 回退"是**同设备重试**(`backend/pipeline/ingest.py:518-534`),CUDA 故障(A/B 两类)必然全灭。两类故障(`cuda_init_failure` / `cuda_oom`)已按 09-03 生产 RCA 区分,词表冻结。
4. **唯一三路交叉文件是 `scripts/sync.py`**(W1 两小 hunk vs W2 一中 hunk,不同行区、不同函数)与 `backend/pipeline/ingest.py`(可完全划归 W1,若 W2 砍掉 V1 记账扩展)。已给出 hunk 级所有权图与集成顺序(W2→W1→W3)。
5. **数据模型增量极小**:3 个可空列(`execution_device`/`fallback_reason`/`fallback_detail`)+ counters 词表冻结;无 SourceHealthSnapshot(读时派生,理由见 §11);一条幂等迁移。

---

## 2. Discovery Baseline

```
DISCOVERY_BASELINE = 1d6f6b5fe697b5f7a1b8decef1c29f51afcda937(本地 main HEAD)
```

- 本地 `main` = `1d6f6b5`(三候选集成门 PROMOTE 后的 authoritative main)。
- `origin/main` = `87328dd`,本地落后 4 提交,**但 `git diff HEAD origin/main --stat` 为空**——净 tree 完全一致:
  - `804e2b3` 改 `config/sites.yaml`(+3/-2)→ `325d984` 原样 revert;`dbd4a70`、`87328dd` 为零文件变更的治理提交(即 prompt 预警的两个误操作提交)。
  - **Discovery 以 `1d6f6b5` 的 tree 为准,未做任何 reset/rebase/pull。**
- 工作区:`.gitignore` 有一处未暂存修改(外来改动,本轮未触碰)。
- Worktrees(9 个,`git worktree list`):main + `ask-ai-llm-provider` + `.worktrees/{generation-localization, integration-camthink-v1-20260903, preflight-report, test-isolation-performance, v1-integration-checkpoint, wave0-observability, widget-handoff}`——均为历史交付留存,本轮零触碰。
- 生产当前运行 sha-1d6f6b5 对应镜像(见 docs 仓 4f06d81),与本次 discovery 基线同源。

---

## 3. Current Sync Runtime Truth(A)

### 3.1 完整调用链(实证)

```
Admin「同步」按钮 (admin/src/pages/DataSources.tsx:608 handleSync)
  → POST /api/admin/data-sources/{id}/sync   (backend/api/admin/data_sources.py:610-646, 202)
  → submit_sync_request                       (backend/services/sync_requests.py:63-101)
      INSERT sync_requests(status=pending, triggered_by=manual, attempt_count=0)
      活跃去重 = 应用层 find_active_request (:49-60,同 source 或同 NULL 键)
      → 返回 {status: accepted|already-running, request_id}  ← 前端丢弃 request_id
  → sync-executor 容器 (deploy/prod/docker-compose.yml:119-128)
      scripts/sync_executor_loop.py 轮询 POLL_INTERVAL=2s (:66)
      claim_next: UPDATE ... FOR UPDATE SKIP LOCKED → status=running, picked_at (:257-287)
      _increment_attempt: attempt_count+1(真实 spawn 前原子递增,:381-392)
      run_runner: asyncio.create_subprocess_exec(python, scripts/sync.py,
          --triggered-by X [--force-incremental-replay] [--source ID]
          --request-id N --attempt M)                            (:90-119, 290-309)
  → scripts/sync.py run_sync
      BGEEmbedder 预先构造(每 runner 进程一次,:966-970,构造即载模型)
      → _sync_one(cfg, ...)  每源:
          SyncLog 行(status=success 默认,:680-685)
          tel.start → INSERT sync_runs(status=running, stage=DISCOVER)   (:687-696)
          增量窗口 = 上次 success 的 finished_at(:701-703)
          connector.fetch_changes(since) → docs materialize
          tel.progress(FETCH, len(docs), len(docs))                     (:713-715)
          [git 源 SHA 未变 → docs 空 → _handle_no_change(:327-456)]
          connector.run_stats(web_crawl)→ counters 合并                  (:738-747)
          tel.progress(PARSE, extracted, accepted?)                     (:748-754)
          tel.progress(SAFETY_FILTER, NULL, NULL)                       (:766)
          pipeline.ingest_all(docs, progress=回调仅缓冲)                (:774)
              └─ ingest.py:408-464 SAFETY_FILTER/CHUNK/EMBED/INDEX 批界回调(64 doc/批)
                 批量 embed(ingest.py:519)失败→逐 doc 同设备回退(:520-534)
                 任一 doc 失败 → RuntimeError(:457-463)
          四 stage 落笔(ingest_all 返回后一次性,:775-777)             ← 实时性缺口
          counters docs_total/docs_done(:778)
          fetch_deleted → pipeline.delete_document 逐条(:779-781)
          commit_membership_snapshot(crawl,:784-787)
          tel.progress(CONSISTENCY) + verify_source_vectors
              → consistency JSONB(:793-803;失败→verification_failed)
          SyncLog items_new/updated/deleted(:805-807)+ coverage 降级(:813-831)
          tel.progress(DONE, n, n)(仅成功路径,:833)
      finally: commit SyncLog → tel.finish(status= failed?failed:completed,
                error_summary, sync_log_id)                              (:856-873)
  → runner 退出码 = 进程级语义(sync_executor_loop.py:34-36 契约原文:
      "JOB SUCCESS ≠ KNOWLEDGE HEALTH")
      exit 0 → request done;非 0 → _schedule_retry("runner_failed") 有界重试
  → executor 启动时 reconcile_stale_running(:167-254)+ purge_expired_sync_runs(30d)
```

cron 路径:`sync-cron` 容器每小时直跑 `python3 scripts/sync.py`(`deploy/prod/docker-compose.yml:130-137`),**不建 sync_requests 行**,`SyncRun.request_id=NULL`(合法路径,`scripts/sync.py:1040-1046`),`triggered_by=cron`(`:876-885`)。`DataSource.sync_interval` 字段存在(`models.py:202`,默认 24h)**但无任何调度代码消费**——每 tick 同步全部 enabled 源,增量窗口靠 `_compute_since` 兜底(24h 默认,上限 30d)。

### 3.2 状态归属清单

| 状态 | 归属 | 位置 |
|---|---|---|
| 交接/恢复权威(request 状态、attempt、退避) | **持久化** | `sync_requests`(阶段⑨/⑩;`models.py:207-245`) |
| 运行真相(stage/current/total/counters/consistency/终态) | **持久化** | `sync_runs`(Wave-0;`models.py:248-300`) |
| 业务结局(success/partial/failed + items_*) | **持久化** | `sync_log`(`models.py:176-191`) |
| 文档账本(content_hash/branch/chunk_count) | **持久化** | `documents`(`models.py:41-66`) |
| ingest 期间四 stage 的批界进度 | **仅内存**(`_ingest_seen`,`sync.py:767-773`,ingest_all 返回后才落库) | |
| stage 间活性/心跳 | **不存在**(stage 只在转移时写;`updated_at` 随写跳动) | |
| connector run_stats / safety_stats | 仅进程内对象 | |
| 前端"同步中" | 仅 React state | `DataSources.tsx:345-346` |
| QUEUED/WAITING/RECOVERING/IDLE 呈现态 | 读时派生,不持久化 | `derive_run_state`(`sync_runs.py:264-293`) |

### 3.3 request_id / attempt / 终态 / 退出码

- **request_id**:API 响应返回→前端丢弃;executor 经 argv 传入 runner→落 `sync_runs.request_id`;`sync_log` 无此列(经 `sync_log_id` 反链)。身份唯一性:`uq_sync_runs_request_source_attempt` 部分唯一索引(`models.py:291-300`,仅 request_id 非空生效;NULL 直跑不受约束)。
- **attempt**:`sync_requests.attempt_count` 真实 spawn 前递增;上限闸门 `MAX_TOTAL_ATTEMPTS=4`(`:70`),退避 30/120/600s(env `SYNC_RETRY_BACKOFF_SECONDS` 可覆写);孤儿完成复检锚 `attempt_started_at`(回退 `picked_at`,`:434-456`);首启即中断 F16 旁路 `--force-incremental-replay`(`:459` + `sync.py:888-899` + `connectors/github.py:77-81,277-285`)。
- **终态双 layers**:SyncRun = `running/completed/failed/interrupted`(写入在 `_sync_one` finally;`interrupted` 仅由 executor 启动对账盖章 `sync_runs.py:219-234`);SyncLog = `success/partial/failed`(业务)。**业务 partial → SyncRun completed**(attempt 跑完了)。
- **退出码 ≠ 业务成败**:runner 捕获一切单源异常后正常 exit 0(`sync.py:844-854`)→ request `done`、**无自动重试**。CUDA 全灭的手动同步因此不会重试(cron 每小时自然重试)。W1 的 CPU 回退使"合法文档尽可能完成"后,此缺口大幅收窄;V1 不改该契约。

---

## 4. Current Persistence Model(B)

### 4.1 `sync_runs` 现有 17 列(verbatim,`models.py:266-286`)

`id, request_id(nullable, idx), source_id(not null, idx), attempt(default 1), recovery(bool), triggered_by(default "cron"), status(default "running", idx), stage(nullable), stage_current(nullable), stage_total(nullable), counters(JSONB default dict), consistency(JSONB nullable), error_summary(Text, finish 时截 500), sync_log_id(UUID nullable), started_at, updated_at(onupdate), finished_at(nullable)`。

**prompt 清单逐项判定**:

| 候选字段 | 现状 | 判定 |
|---|---|---|
| stage | ✅ 已有(9 值冻结词表,`sync_runs.py:28-36`) | 不动 |
| current / total | ✅ 已有,名 `stage_current`/`stage_total`;NULL=分母未知(`progress_fraction` 禁假百分比,`:57-63`) | 不动 |
| counters | ✅ JSONB;今日实写键:`discovered/accepted/extracted/failed/rejected`(connector web_crawl,`sync.py:738-747`)+ `docs_total/docs_done`(`:778`) | **词表冻结 + 扩展**(§8) |
| consistency | ✅ JSONB,键 `expected_chunks/actual_chunks/missing/refill/stale_chunk_count/orphan_count` + `verification_failed` | 不动;missing 与 orphan(=extra)已可区分表达 |
| error_summary | ✅(≤500) | 不动 |
| request_id / attempt / sync_log_id | ✅ 全有 | 不动 |
| **execution_device** | ❌ 不存在 | **新增**(W2 迁移,W1 写) |
| **fallback_reason** | ❌ 不存在 | **新增** + 伴生 `fallback_detail` |
| duration | ❌ 无列 | **不加列**:读侧 `finished_at - started_at` 可靠可算 |

**execution_device 结构判定**:不用自由文本,采用**受控枚举列 + 独立原因码列**:

```sql
ALTER TABLE sync_runs ADD COLUMN IF NOT EXISTS execution_device VARCHAR(16);  -- 'gpu'|'cpu'|'gpu_to_cpu'
ALTER TABLE sync_runs ADD COLUMN IF NOT EXISTS fallback_reason   VARCHAR(32);  -- code 词表,见 §13
ALTER TABLE sync_runs ADD COLUMN IF NOT EXISTS fallback_detail   TEXT;         -- 人类可读,写侧截 500
```

- `gpu` = 全程 GPU;`cpu` = 起 CPU(env 显式/探测无 GPU);`gpu_to_cpu` = **本次运行发生过自动降级**、最终 CPU 完成(三值同时表达"最终设备"与"是否降级",避免两列组合歧义)。
- NULL = 历史行/未记录 → UI 呈现"—",禁止推断。
- 写者:仅 `scripts/sync.py` 单写者(既有冻结边界),经新增 `record_device()`(§18/§19 冻结签名)。

### 4.2 相邻表现状

- `sync_requests`(`models.py:207-245`):交接/恢复权威;`status pending/running/done/failed` + 恢复列(attempt_count/failure_kind/next_retry_at/attempt_started_at)+ runner_exit_code/error。**无唯一索引(应用层去重)**。
- `sync_log`(`models.py:176-191`):`status success/failed/partial`,`items_new/items_updated/items_deleted/items_unchanged`,duration_ms,error_detail(兼载 web coverage 行)。**语义陷阱:`items_updated = sum(results.values())` = 写入 chunk 总数,非"更新文档数"**(`sync.py:806`);`items_new` = 有 ≥1 chunk 的文档数;`items_unchanged` 仅 no-change 路径写。API 未暴露 items_unchanged(`schemas.py:81-95`)。
- `documents`:复合主键 (content_hash, branch);`source_id` 前缀形 `{data_source_id}/{path}`;`chunk_count` 为一致性校验的账本分母。**added/updated 的逐 doc 区分信号在 `_upsert_postgres` 前的 `_get_stored_chunk_count`(previous_count)已存在但未上浮**(`ingest.py:601-605` 批路径逐 doc 读)。
- 迁移体系:**无 Alembic**;幂等脚本 `scripts/migrate_*.py` + `init_db` create_all(`backend/db/session.py:95-104`)+ `ensure_recovery_columns` ALTER 模式(`:74-92`)。`sync_runs` 由 `scripts/migrate_add_sync_runs.py` 建立(生产已跑,幂等)。

---

## 5. Current API / Frontend Contract

### 5.1 后端(Admin,`/api/admin` 前缀)

| 端点 | 位置 | 现状 |
|---|---|---|
| `GET /data-sources` | `data_sources.py:276-335` | `DataSourceOut`(schemas.py:48-59)含 last_sync/last_sync_status/last_sync_error(join 最新 sync_log);**无 active 状态、无 request_id** |
| `POST /data-sources/{id}/sync` | `:610-646` | 202 `{status, source_id, request_id}` |
| `POST /data-sources/sync-all` | `:649-679` | 单行 `source_id=NULL` 交接;返回 source_ids 种子 |
| `GET /sync-logs` | `sync_logs.py:17-60` | 已有分页+source_id/status 过滤;**前端零消费**;不暴露 items_unchanged |
| `GET /analytics/source-health` | `analytics.py:371-515` | **30 天 run-success 统计**(sync_log 口径):`healthy(≥0.9)/degraded(≥0.5)/critical/insufficient_data(<3 次)/disabled`;partial 计分母不计分子 |
| `GET /tech/performance` | `tech.py:252-475` | 服务级五态健康(Trace 口径),非数据源级 |
| **读 sync_runs / sync_requests 的端点** | — | **不存在**(grep 实证:SyncRun 仅被 sync_runs.py/sync.py/sync_executor_loop.py/ingest.py:37-41 引用) |
| SSE/WebSocket(admin) | — | 不存在;SSE 仅 `/api/ask` 聊天流 |

### 5.2 前端(React 19 + TS + Vite + TanStack Query v5)

- 数据源页 = 单文件 `admin/src/pages/DataSources.tsx`(1175 行):`syncingIds`/`triggeredAt` 本地 state 驱动 5s 条件轮询(`:347-354`)与按钮态(`:1141-1148`);完成判定 = `last_sync > triggeredAt` 启发式 + 5 分钟超时(`:637-695`)。
- 健康列:5 态徽章 + "X% 成功 · 近30天 N 次"副行(`:150-177`),数据来自 `/analytics/source-health`。
- 同步历史 UI:**不存在**(死类型 `SyncLog`@`types/api.ts:68-81` 零引用)。
- i18n:admin 无框架,内联中文常量(Stage⑯ message_key 模式仅 widget)。测试:vitest + RTL,`admin/tests/DataSources.test.tsx` 已覆盖 per-row 同步/完成/失败分类/sync-all 种子/DSH 语义(为 W3 提供脚手架)。

---

## 6. Current GPU / Embedding Runtime Truth(F 输入)

- **设备选择**:`detect_device(preference)`(`backend/embedder/base.py:12-33`):非 "auto" **原样返回**——`EMBEDDER_DEVICE=cuda`(生产 anchor env,`deploy/prod/docker-compose.yml:42`)即硬绑 GPU,无任何回退;auto 路径 cuda>mps>cpu。
- **模型载入**:`BGEEmbedder`(`backend/embedder/bge.py:39-109`)构造即载 `BGEM3FlagModel(use_fp16=device!="cpu", devices=[device])`(显式 devices 防 FlagEmbedding 自选 GPU,`:81-83` 注释引 2026-08-17 OOM 教训);**无单例/缓存/卸载**——每个构造都是完整加载。维度硬编码 1024。
- **进程拓扑(关键)**:
  - **backend(在线)**:lifespan 启动即载 embedder+reranker 各一份(`backend/main.py:306-314`),构造失败 = 容器起不来(无回退);查询 embed(`retrieval/search.py:160`)与 rerank(`pipeline/rag.py:773,1047`)异常直穿 SSE error(`api/routes.py:310-317`)。**在线进程与 sync 无共享模型**。
  - **sync runner**:executor 每 request spawn 新子进程 → 每 run 新载 BGE(~16s)→ 进程退出全释放 → 每 run 新建 CUDA 上下文。**reranker 不参与 sync**(grep 零命中)。批 embed 粒度:64 doc/批拼平全部 chunk 一次 `embed()`(embedder 内部再按 `EMBEDDER_BATCH_SIZE=16` 切,`ingest.py:433,511-519`)。
- **CUDA 异常今日传播路径**:批量 embed 抛(ingest.py:519)→ 逐 doc 同设备重嵌再抛(:520-534)→ `RuntimeError`(=:457-463)→ 该源 SyncLog failed / SyncRun failed(`sync.py:844-871`)→ runner exit 0 → request `done` **无重试**。cuInit=100 类故障中"模型加载完成"日志是惰性构造假象,首个 encode 才暴露(RCA docs 8bfde33 §)。
- **实测资源画像**(docs 证据):BGE-m3 fp16 ≈2.3G + 批激活 ≈490MiB;含 reranker 的 GPU 路径需 ≥5-6G 空闲;生产 16G 卡多进程共享,OOM 是 VRAM 彩票。
- **测试资产**:`tests/embedder/test_bge.py`(fake FlagEmbedding 断言 devices/use_fp16 传递、HF env 隔离)、`tests/pipeline/test_ingest.py`(MagicMock embedder)、`tests/scripts/test_sync_executor_loop.py` / `test_recovery_semantics.py`(真实 DB + stub runner)。**无任何 CUDA 故障测试(产品代码亦无此路径)**。

---

## 7. Gap Analysis per Issue

### #9(sync status 刷新消失)
- 缺:读侧 active-state API(连表 sync_requests + sync_runs);前端挂载恢复;request_id 消费。
- 有:持久化事实完备(request/run 都在),`derive_run_state` 纯函数就绪;前端测试脚手架就绪。
- 判定:**被 #12 进度模型吸收**(W2 端点 + W3 恢复),不建前端 workaround。

### #11(真实知识健康)
- 缺:五维(Connectivity/Sync/Coverage/Freshness/Consistency)派生器;`source-health` 现口径 = run-success(且历史出现 run count 虚高);ghost sync_log 行 product=unknown;freshness 无 expected interval 消费(`sync_interval` 无人读);consistency 事实已落 `sync_runs.consistency` 但未读。
- 有:全部输入事实已持久化;`progress_fraction`/`derive_run_state` 已立"无证据=UNKNOWN"先例。
- 判定:读时派生,无 Snapshot 表(§11)。

### #12(实时进度跨刷新)
- 缺:**读侧 API**;**写侧实时性**——ingest 阻塞事件循环,四 stage 批界回调仅缓冲、ingest_all 返回后一次性落笔(`sync.py:767-777`),kill 即卡在 SAFETY_FILTER;无心跳。
- 有:stage 词表/字段/终态/身份唯一全冻结;#12 的 polling 方向已定(V1 不做 SSE)。
- 判定:W2 补 `asyncio.to_thread(ingest_all)` + 防抖落笔(顺带修复手动同步阻塞 /health 的 504 病根)+ 两个读端点。

### #14(GPU-first + CPU 回退)
- 缺:全部——eligible 故障分类、设备切换、遥测、防循环、防"GPU 退化 CPU-by-default"。
- 有:子进程边界天然存在;`EMBEDDER_DEVICE=cpu` 静态路径已受支持(含 use_fp16 联动);fake 测试基建。
- 判定:W1,边界见 §12。

### #15(per-source 同步历史 + deltas)
- 缺:运行级历史 API(sync_runs join sync_log);chunks_deleted 未记账;docs added/updated 未区分(items_updated 实为 chunks);items_unchanged 未暴露;前端零 UI。
- 有:`GET /sync-logs` 后端就绪未消费;`sync_log_id` 反链;consistency/device 字段(后者 W1/W2 落地)。
- 判定:W2 历史 API + W3 UI;delta 全部 run 内产生,**禁止 `after_total - before_total` 假差分**(并发下必然错)。

---

## 8. Frozen Shared Data Model Recommendation

**原则:sync_runs 是唯一运行真相核心;只加不改;机器真值受控词表,禁止自由文本。**

1. 新列 3 个(§4.1 DDL;迁移脚本 `scripts/migrate_add_sync_run_runtime_facts.py`,幂等 ADD COLUMN IF NOT EXISTS + 期望列校验,复刻 `migrate_add_sync_runs.py` 模式):`execution_device` / `fallback_reason` / `fallback_detail`。**Owner:W2 建列,W1 写值。**
2. `counters` 键词表冻结(JSONB,免迁移,读侧未知键必须容忍):

   | 键 | 语义 | 写点 | 现状 |
   |---|---|---|---|
   | discovered/accepted/extracted/failed/rejected | connector 抓取侧 | fetch 后 | 已有(web_crawl) |
   | docs_total / docs_done | 本轮待灌/完成 doc 数 | ingest 后 | 已有 |
   | **cpu_docs** / **cpu_batches** | CPU 回退后完成的批/文档数 | 回退点 | 新(W1) |
   | **chunks_deleted** | prune + 删除路径 chunk 数 | ingest 删除路径 | 新(W2,V1 可选) |

   `docs_added`/`docs_updated` 拆分(P2,需 ingest.py 记账 hunk)——**V1 不做**,历史呈现以 `items_new`(触及文档)+ `items_updated→更名暴露为 chunks_written` 表达,UI 文案如实。
3. **不加**:SourceHealthSnapshot 表(读时派生,§11)、duration 列、stage_current_label、SyncLog 新列(items_unchanged 已有,仅需 API 暴露)。
4. 身份/保留:沿用 `uq_sync_runs_request_source_attempt` 与 30 天 purge(executor 启动时);**历史深度=30 天**,产品如实告知。
5. **写者边界不变**:sync.py 单写者;executor 只在对账后盖章;record_device 同为 best-effort(遥测失败不阻断业务,与 `_RunTelemetry._do` 语义一致)。

---

## 9. Frozen Progress Contract(#12)

1. **stage 转移**:严格按 `DISCOVER → SAFETY_FILTER → FETCH → PARSE → CHUNK → EMBED → INDEX → CONSISTENCY → DONE` 写 `sync_runs.stage`(`sync_runs.py:28-36` 冻结词表,禁止新值)。转移点即今日写点(§3.1),W2 仅把 CHUNK/EMBED/INDEX/SAFETY_FILTER 四 stage 从"ingest 后一次性"升级为**批界实时落笔**(64 doc/批粒度)。
2. **current/total 语义**:`stage_current`=该 stage 已处理真实条数;`stage_total`=该 stage 可靠分母;**分母未知必须 NULL**,`progress_fraction` 为唯一百分比入口(NULL→无百分比,HARD BOUNDARY 既有)。
3. **无百分比 stage**:DISCOVER、SAFETY_FILTER(过滤在 ingest 内部,仅批界计数)、CONSISTENCY(校验无分母);PARSE/CHUNK/EMBED/INDEX 有 `docs_total` 分母(web_crawl 的 PARSE 用 accepted)。
4. **short-circuit 语义**:git SHA 未变 → docs 空 + existing>0 → `_handle_no_change`:stage 链 FETCH→CONSISTENCY→DONE、counters `docs_total=0`、SyncLog `items_unchanged=existing`、status success。**UI 必须呈现"无上游变更,跳过灌入",禁止暗示完整 ingestion**;且 short-circuit 成功**不得**作为 GPU 路径健康证据(模型仍载但零 encode,prompt 第 16 条与 RCA 一致)。
5. **终态**:run `completed/failed/interrupted`(interrupted 仅 executor 对账);业务 `success/partial/failed` 归 sync_log;呈现态 8 词表(IDLE/QUEUED/WAITING/RUNNING/RECOVERING/COMPLETED/FAILED/INTERRUPTED)读时派生。
6. **retry/attempt**:attempt 上限 4 + 退避 + 孤儿复检锚不变(阶段⑩冻结,本轮零触碰);每 attempt 一行 SyncRun(部分唯一索引保证)。
7. **refresh recovery**:active 判定 = `sync_requests.status ∈ {pending,running}`(该源或 sync-all NULL 键)**或** 该源存在 `sync_runs.status=running`(覆盖 cron 直跑);后端无可证明 active 时,前端**禁止**显示"同步中"。刷新零副作用(纯 GET)。
8. **并发源语义**:每源独立 SyncRun 行;sync-all 每 attempt 每源各一行、共享 request_id;单 executor 串行执行是特性(单 GPU 保护,`sync_executor_loop.py:32-33`);进度按 source_id 隔离,互不污染。
9. **传输**:V1 polling(5s 保持);payload 见 §19 W2 接口。

---

## 10. Frozen Sync History Contract(#15)

一条 completed SyncRun(+join sync_log)必须能回答:

| 问题 | 来源 | 判定 |
|---|---|---|
| 何时开始/结束 | `started_at`/`finished_at`(duration 读侧计算) | ✅ |
| 谁/什么触发 | `triggered_by`(manual/cron)+ `request_id`(NULL=cron 直跑)+ `attempt`/`recovery` | ✅ |
| 最终状态 | run `status` + join sync_log `status`(success/partial/failed) | ✅ 双层都出 |
| discovered | counters.discovered(web)/docs_total(git) | ✅ |
| added(文档) | sync_log.items_new(≥1 chunk 的文档) | ✅(语义=触及文档) |
| updated(文档) | **V1 不可证明**——如实呈现 chunks_written,不伪造 updated doc 数 | ❌→honest |
| deleted/退休 | sync_log.items_deleted(fetch_deleted + orphan 退休合并) | ✅ |
| unchanged | sync_log.items_unchanged(仅 no-change 路径;**API 需补暴露**) | ✅(W2) |
| skipped/失败 | counters.rejected(safety)/ connector failed;ingest 失败数 = failed 时 error_summary + docs_total−docs_done | 部分(W2 补 failed_ingest 推导,标注推导属性) |
| chunks 新增 | sync_log.items_updated(即写入 chunk 总数,**API 更名 chunks_written 防误读**) | ✅ |
| chunks 删除 | counters.chunks_deleted(V1 可选;未记=UNKNOWN 不伪造) | W2 |
| chunks unchanged | **不可证明**(重嵌覆盖写无 diff)→ 禁止呈现 | ❌→honest |
| consistency | `consistency` JSONB(missing/refill/stale/orphan/expected/actual;verification_failed=校验不可用) | ✅;**missing 与 orphan(extra)是不同事实,分别呈现** |
| 执行设备 | execution_device/fallback_reason(W1 落地后) | 新 |

**产生点纪律**:一切 delta 在 run 内部产生(逐 doc/逐批写时计数);`after_global_total − before_global_total` **绝对禁止**(多源并发 + 删除路径下必然错误)。#13 预留:consistency 的 orphan_count/orphan 明细已足以支撑未来修复 evidence,本轮不加字段。

---

## 11. Frozen Health Contract(#11)

**判定:V1 不建 SourceHealthSnapshot,读时纯派生。** 依据:`derive_run_state` 已证明读时派生模式可行;数据源数量级 ~10(全表扫无压力);五维输入全部已持久化;Snapshot 会引入第三真相体(违反 prompt 第 5 条)。

### 维度 → 证据 → 状态(每维输出 `{state, evidence, as_of}`)

| 维度 | state 词表 | evidence(来源) | as_of |
|---|---|---|---|
| Connectivity | ok / degraded / failed / unknown | 最近 run 失败相位:`sync_runs.stage` 停留点 + error_summary 分类(FETCH/DISCOVER 期失败=连接性;EMBED 期=资源;PARSE=内容)+ connector counters.failed | 最近一次 run 的 finished_at |
| Sync | healthy / degraded / critical / insufficient_data / disabled | 30 天窗口 sync_log success 率(沿用现 `/analytics/source-health` 语义,MIN 3 次) | 窗口内最新 log |
| Coverage | ok / partial / unknown | web_crawl:counters extracted/accepted;git:items_new+unchanged vs discovered;**无 run_stats 的类型=unknown** | 最近成功 run |
| Freshness | fresh / stale / unknown | 最近**成功** sync_log.finished_at vs 阈值 = 2× `sync_interval`(解析 `^\d+[hm]$`,schemas.py:68 既有校验);enabled 且从未成功=stale | now |
| Consistency | ok / degraded / unknown | 最新 sync_runs.consistency:missing>0 或 orphan_count>0 → degraded;verification_failed → unknown;missing 与 orphan 分别呈现 | 最新 run |

### 关键裁决

- **expected-state 来源**:V1 派生——`enabled=true` → **REQUIRED**(默认);`enabled=false` → **EXCLUDED**;可选逐源覆盖走 `data_sources.config` JSONB 键 `expected_state`(OPTIONAL/DISCOVERY,**免迁移**)。**实现首步必须复核 CamThink 已启用生产源清单后才能采默认 REQUIRED**(issue #11 明示;列为 W2 实现前置 Gate,非本轮拍板)。
- **Freshness 阈值**:`2 × expected interval`(issue #11 冻结方向);`sync_interval` 无调度消费者不影响其作为期望间隔语义。
- **RECOVERING**:仅 active-run overlay(derive_run_state 已定义:attempt>1 或 failure_kind 非空);**不改变底层健康色**,旧成功不得因此显示 HEALTHY。
- **无证据 → UNKNOWN/INSUFFICIENT_DATA**:全维 unknown → INSUFFICIENT_DATA;**禁止默认 HEALTHY**(绿色假健康禁令)。
- **聚合**:worst-of 非 unknown 维度 + active overlay;Consistency 的 missing 优先于 orphan 呈现(缺数比多余更伤答案质量)。
- 状态族对齐 issue #11:HEALTHY/EMPTY_EXPECTED/EMPTY_UNEXPECTED/PARTIAL/DEGRADED/STALE/RECOVERING/ACTION_REQUIRED/INSUFFICIENT_DATA——映射:EMPTY_* 由 Coverage×expected-state 派生(disabled 源 0 文档=EMPTY_EXPECTED;enabled REQUIRED 源 0 文档且无成功 run=EMPTY_UNEXPECTED)。

---

## 12. GPU→CPU Fallback Engineering Boundary(#14,W1)

**产品契约回顾**:GPU-first;仅 eligible CUDA 故障触发有界自动 CPU 回退;尽可能完成合法文档;在线 Q&A 优先;回退可观测(gpu/cpu/gpu_to_cpu + 原因);回退是可靠性机制非无限重试;正常时**不得**退化为 CPU-by-default。

逐问冻结:

1. **哪些 GPU 故障可安全触发回退**(分类词表 = `fallback_reason`,与生产两类 RCA 对齐):
   - `cuda_init_failure` —— A 类:上下文/运行时初始化失败(cuInit=100 / NVML=999 / torch.cuda.is_available()=False / encode 抛 CUDA 不可用类)。模型可能已"加载成功"(惰性),首个 encode 才暴露。
   - `cuda_oom` —— B 类:`torch.cuda.OutOfMemoryError`(VRAM 耗尽,运行时本身健康)。
   - `cuda_runtime_error` —— 其余显式白名单 CUDA 运行时异常(词表实现期以 fake 注入测试固化;**禁止** broad `except Exception` 触发回退——Weaviate/PG/文档级异常不得换设备)。
2. **same-process 回退可靠性**:**可靠,且结构上已被保护**——sync runner 是每 run 新子进程、模型每 run 新载、进程退出即全释放。回退动作 = 丢弃旧实例引用 + `gc.collect()` + `torch.cuda.empty_cache()` + 新建 `BGEEmbedder(device="cpu")`(A 类无上下文可清;B 类清 VRAM 后 CPU 张量不受残留 CUDA 上下文影响;重建实例规避 FlagEmbedding 内部状态)。**残余风险**:FlagEmbedding devices 内部行为差异 → 以 fake 注入测试 + 生产观察兜底。
3. **需要的边界**:**已存在**(executor→runner 子进程),无需新 worker/容器。**V1 明确不改 backend 在线进程**(启动 fail-fast、查询路径零触碰——保护 Q&A,满足 prompt 第 14 条)。
4. **回退粒度**:**batch 级**。触发点 = `ingest.py` 批量 embed 失败处(:518-534):分类 eligible → 重建 CPU embedder → **该 64-doc 批重嵌**(复用既有逐 doc 回退结构)→ 后续批**粘性 CPU**(run 内单向)→ run 级 `execution_device=gpu_to_cpu`。不做 doc 级设备切换(抖动)、不整 run 重跑(丢弃已完成批)。
5. **防循环**:run 内**单向 gpu→cpu,至多一次**;CPU 再失败走既有 failed 契约(该源失败、批次继续);run 间受既有 attempt cap(4)+ cron 周期约束;**绝无 cpu→gpu 回切**。env `EMBEDDER_CPU_FALLBACK=on|off`(默认 on,仅 sync runner 代码路径消费;backend 不经该工厂故 inert)可紧急关闭。
6. **记录**:`tel.device(...)` → execution_device/fallback_reason/fallback_detail + counters(cpu_batches/cpu_docs);W3 徽章呈现(gpu/cpu/已回退+原因)。
7. **不退化**:`detect_device` 语义不动(显式值原样放行);正常路径唯一变化是**前置 1-token encode 冒烟探针**(模型载入后立即最小 encode,把惰性 CUDA 失败提前到 ingestion 前分类,探针失败按 eligible 分类进入回退决策)——GPU 健康时探针开销可忽略。
8. **V1 latency/resource boundary**:CPU embed 显著慢于 GPU(生产 T4 实测 BGE-m3 CPU 量级差)——V1 **接受 run 拉长**(小时级 cron 窗=天然上界;手动 run 用户可见设备徽章),**记录 duration + cpu counters 但不设超时 kill**;batch 自适应缩小(OOM 软缓解)列 P2。在线 Q&A 影响 = 零(不同进程,backend 驻留 GPU 不受 sync runner CPU 回退影响;反之 sync 回退后**让出** VRAM,对在线只有利好)。

**工程落点**(详见 §16):`backend/embedder/` 新回退工厂 + 故障分类器;`ingest.py` embed 异常路径 hunk;`scripts/sync.py` 构造点换工厂 + 每源 `tel.device` 落笔。

---

## 13. Failure Classification(统一词表)

| code | 类 | 生产证据 | 处置 |
|---|---|---|---|
| `cuda_init_failure` | GPU A 类:上下文初始化被拒 | 09-03 RCA cuInit=100/NVML=999,主机健康、老上下文存活 | W1:eligible → CPU 回退 |
| `cuda_oom` | GPU B 类:VRAM 耗尽 | 09-03 neomind 12 篇失败(415MiB 剩余) | W1:eligible → 释放+CPU 回退 |
| `cuda_runtime_error` | 其他白名单 CUDA 运行时异常 | 词表实现期固化 | W1:eligible(保守) |
| `device_probe_failed` | 前置探针失败(分类失败但 GPU 不可用征兆) | — | W1:按探测结果直 CPU(execution_device=cpu,非回退) |
| (无 code,NULL) | 文档级/连接级/写库级 | 既有路径 | 既有契约,禁止换设备 |
| `verification_failed`(consistency 键) | 校验器不可用 | `sync.py:797-803` | Consistency 维度 UNKNOWN |
| `interrupted` / `runner_failed` / `spawn_failed`(failure_kind) | 请求层 | 阶段⑩ | 不变 |

**呈现纪律**:OOM 不得伪装成文档质量错误(issue #14 边界);设备事实进 execution_device/fallback_reason,错误原文仍进 error_summary。

---

## 14. Migration Boundary

- **本轮零迁移**。实现轮仅一条:`scripts/migrate_add_sync_run_runtime_facts.py`(W2 拥有)——幂等 `ADD COLUMN IF NOT EXISTS ×3` + 列存在校验;新环境由 `init_db` create_all 自动获得;**生产部署模式沿用既有**:目标镜像一次性容器跑迁移 → 切镜像(参照 193f206/1d6f6b5 部署先例)。
- 无数据回fill(NULL=未知是合法语义);无 Weaviate/向量触碰;无 compose 结构变更(W1 新 env 走 anchor 追加,不改拓扑)。
- 上线红线(既有记忆重申):backend + sync-executor + sync-cron **三服务同 sha 镜像**(同镜像跑多角色);sync-executor `up -d` 必带 `ASKAI_IMAGE_TAG` 否则回落 :latest。

---

## 15. Backward Compatibility

- 全部 schema 变更 = 可空新列/JSONB 新键:旧读者零破坏;新读者遇 NULL/缺键必须降级为"未知"呈现。
- API 全部新增端点/新增响应字段(additive);`GET /data-sources` 与 `/analytics/source-health` 响应形状不删不改(W3 只叠加消费)。
- 前端对旧后端(字段缺席)需容忍(W3 按 optional 处理新字段)。
- `detect_device`/embedder 构造签名不变;`ingest_all` progress 回调签名不变;阶段⑨/⑩谓词零改动(executor/requests 逻辑不动)。
- env:新增 `EMBEDDER_CPU_FALLBACK`(缺省 on);`EMBEDDER_DEVICE=cuda` 语义不变(GPU-first 保持)。

---

## 16. Exact File Ownership Matrix

图例:**OWN**=独占;**HUNK**=共享文件内的冻结行区;✗=禁止。

| 文件/目录 | W1(#14) | W2(#12+#15 后端) | W3(#9+#11 前端) |
|---|---|---|---|
| `backend/embedder/**`(base/bge/新 fallback 模块) | **OWN** | ✗ | ✗ |
| `backend/pipeline/ingest.py` | **OWN**(embed 异常路径/设备回退 hunks:448-456、518-534;V1 不做记账扩展则整文件归 W1) | 仅 P2 记账 hunk(V1 建议不做) | ✗ |
| `scripts/sync.py` | **HUNK-A**:966-976(构造→工厂+探针);`_sync_one` tel.start 后 device 落笔(~696 邻域,≤5 行) | **HUNK-B**:766-778(ingest 回调实时落笔:to_thread+防抖+counters);§3.1 其余不动 | ✗ |
| `backend/db/models.py`(SyncRun 新列) | ✗(只写值) | **OWN** | ✗ |
| `backend/services/sync_runs.py`(record_device+读侧查询;既有函数签名冻结只增不改) | 消费(调用) | **OWN** | ✗ |
| `scripts/migrate_add_sync_run_runtime_facts.py`(新) | ✗ | **OWN** | ✗ |
| `backend/api/admin/sync_runs.py`(新端点文件,推荐新文件零碰撞) | ✗ | **OWN** | ✗ |
| `backend/api/admin/schemas.py` / `data_sources.py` / `sync_logs.py` | ✗ | **OWN**(sync-status 挂载+items_unchanged 补露) | ✗ |
| `backend/services/sync_requests.py` / `scripts/sync_executor_loop.py` | ✗(预计零触碰) | ✗(预计零触碰;仅当 status 端点需 request 视图时加只读查询——放入新端点文件则免) | ✗ |
| `deploy/prod|dev/docker-compose.yml`、`.env.example`(EMBEDDER_CPU_FALLBACK env) | **OWN**(仅 env 行) | ✗ | ✗ |
| `admin/src/**`(`DataSources.tsx`、hooks、types、lib/api) | ✗ | ✗ | **OWN** |
| `tests/embedder/**`、`tests/pipeline/test_ingest.py` | **OWN** | ✗ | ✗ |
| `tests/scripts/**`(新 test_sync_device.py 归 W1 新建;既有 test_sync_run_core 等归 W2) | 新文件 | **OWN**(既有+新 API 测试) | ✗ |
| `admin/tests/**` | ✗ | ✗ | **OWN** |
| `backend/main.py`(在线 lifespan) | **✗ 红线** | ✗ | ✗ |

**接口消费/生产**:
- W2 **生产**:迁移+3 列;`record_device(session_factory, run_id, *, execution_device, fallback_reason=None, fallback_detail=None)`(best-effort,签名冻结);`GET /api/admin/sync-status`(bulk active);`GET /api/admin/sync-runs?source_id=&status=&page=&size=`(历史);sync-logs 补 items_unchanged。
- W1 **生产**:故障分类器 + 回退工厂 + 探针;**消费** record_device 与 3 列。
- W3 **消费**:上述两 API;**生产**:刷新恢复、进度呈现、历史 UI、健康五维展示。

---

## 17. Parallelization Recommendation

```
PARALLEL_RECOMMENDATION: THREE_WAY(有条件三路,条件如下)
```

**理由**:唯一实质交叉 = `scripts/sync.py`(W1 HUNK-A vs W2 HUNK-B,相距 ~70 行、不同关注点、总变更 ~30 行,git 三方合并可解析概率高)+ `ingest.py`(V1 建议全归 W1 即消除)。数据层交叉已通过"W2 建列、W1 写值、W3 只读"单向化。**集成顺序冻结:W2 先合(main)→ W1 rebase 于 W2(解 sync.py hunk,基线裁决=W2)→ W3 合入(纯前端,无后端冲突)。** 若实现中 W2 决定做 ingest.py 记账(P2),则该 hunk 冲突风险上升——届时降级为 W1 完成后再做记账,**不为并行而并行**。

不选 TWO_WAY/SERIAL 的原因:三路关注点(设备可靠性/持久化+API/前端)在代码上天然分层,强合并反而放大单 worktree 面积与评审负担。

---

## 18. W1 Frozen Interface(Runtime Reliability,#14)

**Scope**:sync runner 的 GPU-first + 有界自动 CPU 回退 + 设备遥测。**不改** backend 在线进程、阶段⑨/⑩谓词、detect_device 语义。

```
# backend/embedder/fallback.py(新,W1 拥有)——形状冻结,实现自定
classify_cuda_failure(exc) -> FailureCode | None      # None=不 eligible,禁止换设备
build_sync_embedder(settings) -> SyncEmbedderHandle    # GPU-first 构造 + 1-token 探针
SyncEmbedderHandle.embedder                             # 满足既有 Embedder 协议
SyncEmbedderHandle.execution_device                     # 'gpu'|'cpu'
SyncEmbedderHandle.fallback_reason/detail               # 回退后填充
SyncEmbedderHandle.fallback_to_cpu(reason, detail) -> bool  # 单向一次性;False=不可回退
```

- `scripts/sync.py` HUNK-A:构造点改用 `build_sync_embedder`;`_sync_one` 在 `tel.start` 后调用一次 `tel.device(handle.execution_device, ...)`(handle 回退后由 ingest 路径回调补写 `gpu_to_cpu`+reason——补写通道 = `_RunTelemetry.device`,W2 冻结签名,W1 调用)。
- `ingest.py`:批量 embed except(:518-534)先 `classify_cuda_failure` → eligible 则 `fallback_to_cpu` → 该批重嵌 → 后续批粘性 CPU;非 eligible 走既有逐 doc 回退(零行为变化)。
- env:`EMBEDDER_CPU_FALLBACK=on|off`(默认 on;backend 不消费)。
- 验收证据:fake FlagEmbedding 注入 `cuda_oom`/`cuda_init_failure` → 回退成功、execution_device=gpu_to_cpu、counters.cpu_* 落库、无二次回退、lifespan/在线路径零 diff;非 CUDA 异常(Weaviate 错误)不触发回退(RED 用例);GPU 正常路径除探针外零开销。

## 19. W2 Frozen Interface(Sync Truth Backend,#12+#15)

**Scope**:持久化扩展 + 全部读侧 API + 进度实时落笔。**不改**执行面谓词、embedder。

```
record_device(session_factory, run_id, *, execution_device: str,
              fallback_reason: str | None = None, fallback_detail: str | None = None) -> None

GET /api/admin/sync-status
  → { items: [ { source_id, state,            # 8 词表派生态
                 request_id, attempt, recovering,
                 stage, stage_current, stage_total,   # total=NULL ⇒ UI 禁百分比
                 counters, execution_device,
                 started_at, updated_at } ] }         # active=有 pending/running 请求
                                                     # 或 running run(含 cron NULL 路径)
GET /api/admin/sync-runs?source_id=&status=&page=&size=
  → { items: [ { id, source_id, triggered_by, request_id, attempt, recovery,
                 status,                          # run 终态
                 started_at, finished_at, duration_seconds,   # 读侧计算
                 stage, counters, consistency, execution_device,
                 fallback_reason, fallback_detail, error_summary,
                 sync_log: { status, items_new, chunks_written,   # =旧 items_updated 更名暴露
                             items_deleted, items_unchanged, error_detail } | null } ],
      total, page, size }
```

- HUNK-B:`_sync_one` 内 `await asyncio.to_thread(pipeline.ingest_all, docs, progress=...)` + 周期防抖落笔(≥1s 或每批)——**顺带消除手动同步阻塞事件循环致 /health 504 的病根**(09-02 事故);行为等价承诺:落笔内容与今日一次性行相同,仅时机提前。
- sync-logs 响应补 `items_unchanged`;`/data-sources` 响应形状不删不改。
- 验收证据:迁移幂等二跑;to_thread 后 stage 批界推进可被并发读者观测(轮询测试);`stage_total=NULL` 全链无百分比;sync-status 覆盖 cron NULL 路径与 sync-all;历史 join 正确;全量离线回归零损。

## 20. W3 Frozen Interface(Admin Health & Sync UX,#9+#11+#12/#15 前端)

**Scope**:`admin/src/**` + `admin/tests/**`。**消费** §19 API;后端零触碰。

- **#9 闭环**:挂载即调 `GET /sync-status` 恢复每源真实 active 态(替代 `syncingIds` 启发式;本地 Set 仅作乐观即时反馈);轮询保持 5s(仅 active 存在时);完成后切终态;刷新零请求副作用、零重复触发;无可证明 active 不显示"同步中"(issue #9 验收 1-8 全映射)。
- **进度呈现**:stage 徽章(9 词表);`stage_total` 非空才显示 `current/total`/百分比;NULL 显示 stage+counters;short-circuit 文案"无上游变更,跳过灌入"。
- **历史 UI(#15)**:数据源行展开/抽屉 → `GET /sync-runs?source_id=` 倒序;单条:时间/触发/状态/耗时/文档变化(`+items_new / -items_deleted / =items_unchanged / !失败推导`)/向量变化(`+chunks_written`、删除仅在有 counters.chunks_deleted 时)/consistency(missing 与 orphan 分列)/设备徽章(gpu/cpu/已回退+原因)。
- **健康(#11)**:五维 state+evidence+as_of 呈现;无证据=UNKNOWN;RECOVERING=overlay;聚合 worst-of;替换现"近30天健康"列语义(保留 run-success 为 Sync 维度)。
- i18n:沿用 admin 内联中文常量模式;新文案集中 label-map 常量便于审校。

---

## 21. Integration Order

```
0. Planner 终审本合同 → 派发三 worktree(同一基线 1d6f6b5 或届时 main)
1. W2 合入 main(迁移+列+record_device+API+实时落笔)——共享基座先行
2. W1 基于 W2 后的 main rebase(sync.py HUNK-A 与 HUNK-B 相邻不同区,冲突以 W2 为基线裁决)
3. W3 合入(纯前端;期间已可基于 W2 API 并行开发,合入在 W1 后仅为发布节奏)
4. 集成门:全量离线测试(HF_HUB_OFFLINE 隔离,当前基线 1112 绿为参照)+
   admin vitest + 本地真实栈冒烟(同步按钮→刷新恢复→历史→设备徽章)
5. 生产:迁移 → 三服务同 sha 上线(ASKAI_IMAGE_TAG 显式)→ 冒烟
```

## 22. Required Tests / Acceptance Evidence

- **W1**:分类器单测(异常矩阵:OOM/init/非 CUDA 各型);fake 注入回退集成(成功/二次失败/关闭开关);`devices=[cpu]` 与 `use_fp16=False` 断言(既有测试模式延伸);探针单测;在线路径零改动 diff 证据。
- **W2**:迁移幂等;sync-status 八态映射表驱动测试(cron NULL/sync-all/等待重试);sync-runs 契约(join/分页/duration/chunks_written 更名);实时落笔并发观测;无假百分比 gate(复用 progress_fraction 测试模式);`ask_ai_test` 隔离库纪律(既有记忆:并行重建问题)。
- **W3**:刷新恢复 8 场景(对应 issue #9 验收);无伪造 active;多源独立;历史渲染(含 NULL 字段降级);健康 UNKNOWN 语义;既有 DataSources 测试零回归。
- **共性**:CI 双绿;`full` 离线两轮稳定;报告入 docs 仓。

## 23. Risks / Unknowns

1. FlagEmbedding 对 `devices` 参数与 CUDA 故障的异常形态多样性——词表需实现期以注入测试固化,首批生产观察校准(中)。
2. CPU 回退后大源(如 192 篇 neomind)run 时长显著拉长——V1 接受并可见化(duration+徽章);若影响 cron 窗再议 batch 自适应(中)。
3. 生产 CUDA 事故(force-recreate 待授权)未修复前部署 W1:sync 将**常态走 CPU 回退**——可用性升但事故被遮蔽,故设备徽章必须显性、且事故修复独立推进(已知,运营注意事项)。
4. `scripts/sync.py` 双 hunk 合并风险——集成顺序+基线裁决已缓解;实现中若 HUNK-B 扩散立即上报(低-中)。
5. `DataSources.tsx` 1175 行单文件——W3 限增量修改+抽取 hook,不做大重构(低)。
6. 30 天 sync_runs 保留期限制历史深度——产品如实告知,不加长(V1)。
7. counters JSONB 键纪律靠约定——词表冻结+读侧容错+测试断言键集合(低)。
8. 卫生候选(非本轮):`sync_executor_loop.py:281` SAWarning;POLL_INTERVAL 非 env 化;`sync_interval` 无调度消费者(健康用)与真实调度语义漂移。

## 24. Production Boundary

- **本轮:PRODUCTION_MUTATIONS = NONE**(零生产读取亦未执行;全部证据来自本地源码 @1d6f6b5 + 既有 docs 报告)。
- 实现轮生产动作清单(均需届时授权):迁移执行、三服务镜像统一、冒烟;**禁止**在 CUDA 事故修复授权前以 W1 上线替代 force-recreate 修复决策。
- corpus/vector 清理、orphan 修复(#13)、GPU 运行时变更、容器 recreate:全部不在本轮与本包授权内。

## 25. Final Discovery Verdict

```
READY_FOR_PARALLEL_IMPLEMENTATION
```

(THREE_WAY;条件与集成顺序见 §16-§17;唯一待实现期复核项 = CamThink 生产源 expected-state 默认 REQUIRED 清单复核,已列为 W2 前置 Gate。)

---

## 附:证据索引(关键 file:line 汇总)

- 同步链:`backend/api/admin/data_sources.py:610-679`、`backend/services/sync_requests.py:63-101`、`scripts/sync_executor_loop.py:66,90-119,257-309,381-485,512-526`、`scripts/sync.py:183-262,648-873,955-1002`
- 持久化:`backend/db/models.py:41-66,176-191,194-204,207-245,248-300`、`backend/services/sync_runs.py:28-75,78-166,174-256,264-293`、`scripts/migrate_add_sync_runs.py`
- ingest:`backend/pipeline/ingest.py:408-464,466-536,601-605,618-659,665-728`
- GPU:`backend/embedder/base.py:12-33`、`backend/embedder/bge.py:39-109`、`backend/main.py:306-314`、`backend/retrieval/search.py:160`、`backend/pipeline/rag.py:773,1047`、`deploy/prod/docker-compose.yml:32-63,100-137`
- 读侧现状:`backend/api/admin/analytics.py:371-515`、`backend/api/admin/sync_logs.py:17-60`、`admin/src/pages/DataSources.tsx:345-354,607-636,637-695,1141-1148`、`admin/src/hooks/useDataSources.ts:8-27,64-102`
- 一致性:`backend/services/vector_consistency.py:40-51,54-165`、`scripts/sync.py:171-180,327-456,524-645,789-803`
