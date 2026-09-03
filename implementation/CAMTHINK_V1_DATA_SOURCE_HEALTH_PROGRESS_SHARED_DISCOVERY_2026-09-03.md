# CAMTHINK V1 — ⑪+⑫ 数据源真实健康 & 同步实时进度 共享 Discovery 报告

- 日期:2026-09-03
- 角色:Engineering Discovery Agent / WINDOW A(并行发现)
- **BASELINE_COMMIT: `1b8572abd74145bac5727688a957a2c37370c7ec`**(阶段⑩ FINAL_CORRECTION,origin/worktree-exec/sync-isolation-20260902)
- CODE_MUTATION: **NONE**(全程只读;唯一动作=本报告入 docs 仓)
- PRODUCTION_ACCESS: **NONE**
- 上游验收不变量引用:阶段⑧(数据导入安全)/⑨(执行面隔离)/⑩(恢复语义,1b8572a)

---

## 1. Baseline

基线 `1b8572a` 上与本报告相关的事实面:

| 域 | 事实 |
| --- | --- |
| 触发面 | Admin `POST /data-sources/{id}/sync`、`POST /data-sources/sync-all` → `sync_requests` 交接行(data_sources.py:610-679);sync-cron 容器每小时直跑 `scripts/sync.py`(compose:130-137,**无 SyncRequest**);手动一次性 `docker compose run sync`(compose:106-112) |
| 执行面 | `sync-executor` 容器 `scripts/sync_executor_loop.py`:对账(reconcile_stale_running 三分支)→ claim(领用不递增)→ spawn `scripts/sync.py` 子进程(MAX_TOTAL_ATTEMPTS=4,退避 30/120/600s,attempt_started_at 证据锚) |
| 业务面 | `scripts/sync.py` run_sync:逐源 `_sync_one` → fetch → ingest → delete → W6 快照提交 → **结束时写一行 SyncLog**(finally) |
| 呈现面 | Admin `/data-sources` 列表 + `/analytics/source-health`(30 天 run 成功率口径)+ `/sync-logs`(只读查询,前端未接 UI) |

## 2. Current Architecture(与 ⑪/⑫ 相关的部分)

```
Admin 前端(5s refetchInterval 轮询,无 WS/SSE)
   │ GET /data-sources            → 最近一次尝试时间+状态(error_detail)
   │ GET /analytics/source-health → 30天run成功率 health + doc_count(PG账本)
   │ POST /data-sources/{id}/sync → 202 accepted(≠ success)
   ▼
backend 容器 ── INSERT pending ──▶ sync_requests(交接/恢复队列,进程级语义)
                                        │ claim FOR UPDATE SKIP LOCKED
                                        ▼
                     sync-executor 容器 ──▶ scripts/sync.py 子进程(逐源)
                                        │   ↳ 结束时写 sync_log(每源一行/每次attempt)
                                        ▼
                     Postgres documents(账本) + Weaviate(向量真相)
```

关键结构性事实:

1. **三个触发入口,两种链路**:手动走 SyncRequest 交接;cron **绕过** SyncRequest 直跑 sync.py(sync_log.triggered_by 默认 "cron")。任何"运行状态"模型必须同时覆盖无请求行的 cron 路径。
2. **runner 与请求无标识关联**:`scripts/sync.py` 的 argv 无 `--request-id`(_parse_args,sync.py:814-856);SyncRequest↔SyncLog 只能按 source_id+时间窗猜。这是 ⑪/⑫ 共享核心必须先解决的接口。
3. **进程级/业务级双层结果**(冻结语义,scripts 层 docstring 明示):SyncRequest.status=done 只表示 runner 退出码 0;`_sync_one` 吞掉单源异常(sync.py:588-589 注释,except 不上播),**全部源 failed 时 runner 照样 exit 0、请求照样 done**。业务真相只在 sync_log。
4. **SyncLog 只在运行结束时落一行**(_sync_one finally,sync.py:677-688):运行中 DB 无该 run 任何行 → "running/进度"在现状下**没有持久事实可读**。
5. **sync_log.status 是历史日志语义**,阶段⑩恢复把它当**完成事实证据**(terminal sync_log ≥ 证据锚 → done)。HARD BOUNDARY #1(不得改名/不得挪用为 Health)有硬技术理由:恢复对账依赖它的谓词。

## 3. Current Truth Inventory(逐项盘点)

标注:**EXISTS** 有持久事实 / **PARTIAL** 有但不完整或只在内存 / **MISSING** 无 / **MISLEADING** 有但语义易误读。

| # | 事实项 | 状态 | 证据与说明 |
| --- | --- | --- | --- |
| 1 | source enabled/config/type/product | EXISTS | data_sources 表(models.py:194-205);config JSONB 含 channel_visibility/channel 白名单 |
| 2 | expected state(REQUIRED/OPTIONAL/DISCOVERY/EXCLUDED) | **MISSING** | 只有 `enabled` 布尔;无"该源按产品语义应不应该有内容"的概念 → 空-source 判定无依据 |
| 3 | latest attempt(含运行中) | PARTIAL | SyncLog 仅结束态;**运行中无行**。SyncRequest 有 pending/running 但 sync-all 是单行(非 per-source) |
| 4 | latest successful sync | EXISTS(派生) | `_last_success_at`(sync.py:196-222):最近 status=success 的 sync_log;**partial 不推进窗口**(no-change 复验失败记 partial) |
| 5 | sync_log start/end/status | EXISTS | models.py:176-192;started_at/finished_at/status∈{success,partial,failed}/duration_ms |
| 6 | source item/document counts | EXISTS(MISLEADING 风险) | documents 账本按 `split_part(source_id,"/",1)` 聚合(analytics.py:443-447);是 **PG 账本数,不是向量数**(历史实证:Weaviate 821 chunks vs PG 2 行漂移) |
| 7 | chunk counts | EXISTS | Document.chunk_count(账本口径);向量口径需 verify_source_vectors 全扫 |
| 8 | vector counts | PARTIAL | 无持久记录;verify_source_vectors(vector_consistency.py:54-165)只读现算,仅在**无变更同步路径**被调用(_handle_no_change,sync.py:269),结果只进 error_detail 自由文本 |
| 9 | authoritative source membership | PARTIAL | 仅 web_crawl:`_accepted_urls` 全量轮权威成员(web_crawl.py:399)+ crawl-state 快照(W6:fetch_deleted 报差集、commit_membership_snapshot 推进)。其余 connector 无成员集持久化 |
| 10 | discovered/accepted/rejected/extracted | PARTIAL | 仅 web_crawl run_stats(web_crawl.py:457-467:discovered/accepted/extracted/failed/rejected{exclude,robots,low_content});**内存态**,运行结束即丢,仅全量轮以 coverage 文本行进 error_detail(sync.py:161-174,649-651) |
| 11 | safety filter excluded | PARTIAL | `record_safety_exclusion`(safety.py:394-396)内存 dict,不持久化(仅 web_crawl 的 low_content 计数间接入 run_stats.rejected) |
| 12 | deleted/pruned | EXISTS | SyncLog.items_deleted;prune 是 DOCUMENT-LOCAL(冻结) |
| 13 | bytes | MISSING | 无任何字节数持久化(仅上传单文件 20MB 上限护栏) |
| 14 | current stage | **MISSING** | 无任何阶段概念持久化;SyncRequest docstring 明示"本表不是 SyncRun 模型:无 stage 计数/心跳/进度统计"(models.py:216-218) |
| 15 | embed/index counters | PARTIAL | ingest_all 返回 `{source_id: chunk_count}` 仅在结束(ingest.py:401-445,batch=64);过程计数不持久化 |
| 16 | retry/recovery state | EXISTS | SyncRequest.attempt_count/failure_kind/next_retry_at/attempt_started_at(models.py:233-246);前端零消费(见 §4) |
| 17 | consistency check | PARTIAL | verify_source_vectors 报告(expected/actual/missing/refill/stale_chunk/orphan)结构化但**不落库**;处置结果三分类进 error_detail 文本(sync.py:296-306);孤儿 reconciliation EXTRA_CONFIRMED_RETIRED/账本重建/UNRESOLVED(sync.py:414+) |
| 18 | orphan count | PARTIAL | 同上,仅校验时现算,不持久 |
| 19 | freshness basis | PARTIAL | 只有"上次成功同步时间"(_last_success_at);无上游内容时间(github commit time/woo modified 有但未存);Document.updated_at=灌入时间非上游修改时间 |
| 20 | coverage denominator | PARTIAL | web_crawl 全量轮 accepted 为分母(COVERAGE_PARTIAL_RATIO=0.8,extracted/accepted<0.8 → partial,sync.py:655-664);其余 connector 无分母概念 |
| 21 | last healthy time | **MISSING** | 无"最近一次确认健康时刻"持久化(可从 sync_log success+无缺口推导但无现成字段) |
| 22 | Run↔Log 关联 | **MISSING** | sync.py 无 --request-id;SyncRequest↔SyncLog↔attempt 无外键/令牌 |
| 23 | 运行中可见性(QUEUED/RUNNING/WAITING) | PARTIAL | SyncRequest 可推 QUEUED(pending)/WAITING(pending+next_retry_at 未来)/RECOVERING(failure_kind=interrupted+attempt>1);RUNNING 有(executor 置 running)但 **per-source 维度缺失**(sync-all 一行) |

## 4. Misleading Semantics(现语义误导点,Admin 实证)

1. **「健康(近30天)」= run 成功率,不是知识健康**。`_health`:enabled→disabled;窗口 runs<3 → insufficient_data;成功率 ≥0.9 healthy / ≥0.5 degraded / else critical(analytics.py:460-467)。**一个 doc_count=0 的空源,只要同步任务次次成功,照样绿色「正常」**——前端两徽章独立,内容列只写「0 篇」,无任何告警(DataSources.tsx:1130-1137,agent 实证"无 0 篇告警逻辑")。这正是 FROZEN PRINCIPLE「JOB SUCCESS ≠ KNOWLEDGE HEALTH」的现行反例,也是验收基线 P0(静默空回答/内部案例)的呈现层根源。
2. **`last_sync_status` 无运行态**。取值仅 success/failed/partial(sync_logs.py:22 同 pattern);前端 map 缺 running → 运行中显示「未知」灰徽章(DataSources.tsx:1104-1129);QUEUED/WAITING/RECOVERING 完全不可见。`last_sync` = MAX(started_at) 的**最近一次尝试**(data_sources.py:288-314),running 期间不更新。
3. **「内容」列的数字是 PG 账本 doc_count**,不是向量数、不是"可检索知识量";账本↔向量漂移史有前科(P1 官网覆盖:"2 文档"根因即账本漂移)。tooltip 里的 chunk_count 同为账本口径。
4. **error_detail 是三合一字符串字段**:错误信息 + coverage 行(全量轮)+ 一致性缺口明细。机器可读性差,任何 Health 维度想从这里取数都要解析自然语言——不可持续,必须结构化。
5. **`accepted`/`202` ≠ success**(data_sources.py:622-623 显式注释,前端靠 5s 轮询 last_sync 推进判定完成,超 5 分钟报"同步超时")。语义有意为之,但前端**完成判定是启发式**(比对 last_sync 时间戳 > 触发时刻),sync-all 场景下多源陆续落 log,任一源推进即误判"完成"。
6. **SyncRequest done ≠ 业务成功**:全源 failed 时 runner exit 0 → 请求 done(§2.3)。若 ⑪ 直接读请求状态推 Health,会把全红源显示成完成——必须以 sync_log/sync_run 为业务事实。
7. **阶段⑩恢复字段对前端完全不可见**:next_retry_at/attempt_count/failure_kind 零消费(agent grep 实证);"正在等待自动重试"在管理员眼里=什么都不发生。

## 5. Shared Data Model Options

需求:⑪(Health)与 ⑫(Progress)共享同一套**持久事实**,不得各自造数。

| 选项 | 内容 | 判定 |
| --- | --- | --- |
| O-1 扩展 SyncRequest 成 SyncRun | 在交接行上加 stage/进度/心跳列 | **否**。docstring 冻结其为进程级交接语义;sync-all 一行请求 vs per-source 进度,基数不对;把队列语义和运行遥测搅在一起,破坏阶段⑨/⑩已验收谓词(claim 过滤、对账分支都查询该表) |
| O-2 扩展 SyncLog(开始时插行,过程中 UPDATE) | 复用历史表当进度载体 | **否**。sync_log 的"结束态一行"是阶段⑩恢复的完成事实谓词(`terminal sync_log ≥ 锚`);改成可变行会让"什么是 terminal"变模糊;且历史日志表被高频 UPDATE 污染 |
| O-3 新建 SyncRunProgress(stage 行表) | 每 stage 一行 | **否**。行churn 大、写入方复杂;stage 是单维枚举,列/JSON 足矣,不为进度建第二张表 |
| O-4 新建 **SyncRun**(每源×每次 attempt 一行,sync.py 单写者) | 运行真相 + 进度 + attempt 关联 | **推荐(⑫ 主载体,⑪ 的事实源)** |
| O-5 新建 SourceHealthSnapshot(定期快照表) | 周期性物化健康 | **否(V1)**。源数量级 ~10,按读时派生即可(§7);先建快照表=为缓存建表,违背"不为建表而建表" |
| O-6 扩展 DataSource(加 last_health JSONB 列) | 把派生结论写回配置行 | **否**。写者混乱(runner 写配置表)、配置行语义被污染 |

## 6. Recommended Model(最小共享事实模型)

**一张新表 `sync_runs` + 一条贯穿 argv 的关联令牌。其余全部读时派生。**

### 6.1 SyncRun(新,唯一新持久化)

```python
class SyncRun(Base):
    __tablename__ = "sync_runs"
    id: int (PK autoincrement)
    request_id: int | None          # 关联 sync_requests.id;cron/CLI 直跑为 NULL
    source_id: str                  # 本行只属于一个源(sync-all 逐源展开 N 行)
    attempt: int                    # 第几次启动(与 SyncRequest.attempt_count 同刻度)
    triggered_by: str               # manual/cron
    recovery: bool                  # 是否恢复重放(--force-incremental-replay)
    status: str                     # running/done/failed/interrupted(见 §8 Run states)
    stage: str | None               # DISCOVER/SAFETY_FILTER/FETCH/PARSE/CHUNK/EMBED/INDEX/CONSISTENCY/DONE
    stage_current: int | None       # 当前 stage 计数
    stage_total: int | None         # 总数;None=未知(禁止算百分比)
    counters: JSONB                 # {discovered,accepted,rejected{...},extracted,
                                    #  failed,excluded_safety,docs_done,docs_total,
                                    #  chunks_written,deleted} 全可空
    consistency: JSONB | None       # verify_source_vectors 报告结构化落库
                                    # (expected/actual/refill/orphan/stale_chunk/处置三分类)
    error_summary: Text | None      # 失败摘要(机器可读 failure_class + 信息)
    sync_log_id: UUID | None        # 结束时回填,1—1 关联历史日志
    started_at / updated_at / finished_at
```

- **authoritative owner**:sync.py 进程(单写者;stage/counters 只有它写)。
- **lifecycle**:spawn 前 executor 插行(running)→ sync.py 过程 UPDATE stage/counters → 结束 UPDATE 终态 + sync_log_id。
- **cardinality**:SyncRequest 1—N SyncRun(sync-all 展开;单源 1—1);SyncRun 1—1 SyncLog(每源每次 attempt)。
- **crash behavior**:kill 后行停留 running——与 SyncRequest 的 reconcile 同源处置:executor 启动对账时**同事务**把孤儿 running SyncRun 置 interrupted(复用既有 reconcile_stale_running 的锚与上限逻辑,不加新机制)。
- **retention**:建议保留 30 天(定期清理可后置到阶段⑭;V1 不删)。
- **migration compatibility**:全新表;`init_db` create_all 自愈(session.py:95-104),生产按预检纪律加显式迁移脚本(纯 additive,无锁风险)。

### 6.2 关联令牌(共享核心的唯一接口改动)

`sync_executor_loop.build_runner_argv` 增加 `--request-id <id>`(和可选 `--run-id <id>`),`scripts/sync.py` 接收并写入 SyncRun。**这是 ⑪/⑫ 一起依赖、且只有它能打通"请求→运行→日志"的证据链**——先冻结此处,再谈并行。

### 6.3 明确不建

- 不建 SyncRunProgress 表(O-3);不建 SourceHealthSnapshot 表(O-5);不动 sync_log/sync_requests 的既有列与谓词(HARD BOUNDARY #6)。

## 7. Health Derivation Contract Draft(⑪ 推导契约草案)

**Hybrid:事实持久(SyncRun/SyncLog/documents/config),状态读时派生(纯函数),V1 不物化。** 铁律:**任一维度无证据 → 该维度 UNKNOWN;整体无证据 → INSUFFICIENT_DATA;禁止"没有证据就 HEALTHY"。**

| 维度 | 输入事实(全部已持久) | UNKNOWN 语义 |
| --- | --- | --- |
| Connectivity | 最近 SyncRun.error_summary 分类(spawn_failed=执行面问题;连接类异常=源不可达);连续失败计数 | 从未运行 → UNKNOWN(不猜) |
| Sync | 最近 N 次 SyncLog/SyncRun 结局(沿用 30 天窗口口径但以 SyncRun 为准,cron 行 request_id=NULL 照样入表) | 窗口内 <3 次 → INSUFFICIENT_DATA(沿用 MIN_SYNC_RUNS=3) |
| Coverage | counters.accepted vs extracted(全量轮);doc_count vs **expected_state**;EMPTY 判定 | 无全量轮/无分母 → UNKNOWN |
| Freshness | now - last_success_at vs k×sync_interval(建议 k=2 起步);STALE 不改数据只报告 | 从未成功 → UNKNOWN(非 STALE——从未有过就谈不上"变陈") |
| Consistency | consistency JSONB 最近一次校验 + **校验时刻衰减**(超过阈值视为 UNKNOWN,防止拿一年前的校验当健康) | 无校验记录/过旧 → UNKNOWN |

派生状态映射(候选集→判定输入):HEALTHY(五维全绿)/ EMPTY_EXPECTED(expected=预期为空且真为空)/ EMPTY_UNEXPECTED(**expected=应有内容但 doc_count=0——现行最危险的静默态**)/ PARTIAL(最近 run partial 或 coverage<1.0)/ DEGRADED(Sync 维度中带或 Connectivity 抖动)/ STALE(Freshness 超阈)/ RECOVERING(活跃恢复中——**建议归 Run 态呈现,Health 只在 attempt 用尽后转 ACTION_REQUIRED**)/ ACTION_REQUIRED(attempt 用尽终态失败、UNRESOLVED_ORPHAN>0、EMPTY_UNEXPECTED)/ INSUFFICIENT_DATA。每维度输出 {state, evidence, as_of},前端可下钻——单维结论不许掩盖证据。

**明确反模式**(写进 ⑪ 冻结边界):不从 error_detail 文本解析事实;不把 SyncRequest.status 当业务结局;不用「最近一次 success」覆盖「一致性/覆盖缺口」。

## 8. Progress Contract Draft(⑫ 进度真值契约)

阶段真值表(核心问题:总数何时可知、未知如何表示):

| Stage | 何时开始/结束 | total 何时可知 | 不可知表示 |
| --- | --- | --- | --- |
| DISCOVER | connector 开始枚举(sitemap 解析/文件树/git diff);结束=候选集定型 | web_crawl 全量轮:sitemap 解析后 discovered 即总数(web_crawl.py:607);github/filesystem:枚举完成即知;woo:单页返回即知(≤100) | stage_total=NULL |
| SAFETY_FILTER | 随 ingest 逐 doc 执行 | =docs_total(materialize 后已知) | — |
| FETCH | fetch_changes/fetch_all 迭代 | **materialize 前不可知**(`list()` 消费完才知道);全量轮 crawl 以 discovered 预估 | stage_total=NULL(增量 materialize 前) |
| PARSE | 抽取内嵌于 fetch(web_crawl extracted 计数) | =accepted(web_crawl)/=docs_total | stage_total=NULL |
| CHUNK/EMBED/INDEX | ingest_all 批处理(batch=64) | docs_total 已知 → 以 **docs_done/docs_total** 为进度轴;chunks_written 做次级计数(embed 总数=chunk 数,chunking 完才知,不拿它当百分比分母) | — |
| CONSISTENCY | 删除后/无变更路径 verify_source_vectors | 不适用百分比;输出 counts(expected/actual/gap) | percentage 禁止 |
| DONE | 终态落账 | — | — |

规则:
1. **percentage 仅在 stage_total 非 NULL 时可计算**;total 未知一律显示计数(current)或不显示,禁止假进度条(HARD BOUNDARY #2/#3)。
2. 写入节奏:批界更新(每 64-doc 批 / crawl 每页),UPDATE 单行,无需心跳列(V1;心跳属⑭资源治理,本轮明确不设计)。
3. 读路径:新端点 `GET /data-sources/{id}/run`(或 `/sync-runs?active=true`)返回活跃 SyncRun(stage/current/total/updated_at);前端沿用 TanStack refetchInterval 轮询(基建已有,queryClient 参数化),**不引入 WS/SSE**(现有零基建,不属本轮)。
4. Run states 派生(⑫ 读模型):IDLE(无活跃请求+无 running run)/ QUEUED(SyncRequest pending, next_retry_at NULL)/ WAITING(pending+next_retry_at 未来)/ RUNNING(执行中,首启)/ RECOVERING(attempt>1 或 recovery=true)/ COMPLETED/FAILED(终态)/ INTERRUPTED(对账置为 interrupted)。全部由 SyncRequest+SyncRun 现有字段派生,**不改恢复语义**(HARD BOUNDARY #6)。

connector 矩阵:github(clone/fetch 为进程黑盒,阶段粒度粗:DISCOVER=diff 解析,后直接进 ingest;可接受)/ filesystem(同 github,枚举快)/ web_crawl(最细:discovered/accepted/extracted 三计数齐全)/ woocommerce(单页,阶段几乎瞬完)/ embed-index(所有 connector 共用)。**进度粒度因 connector 而异是诚实行为,不许为齐整而伪造。**

## 9. Crash/Recovery Semantics(新模型与阶段⑩共存)

1. **SyncLog 谓词不变**:恢复对账仍以 sync_log terminal 行为完成事实(阶段⑩ 1b8572a 语义原样)。SyncRun 是新增遥测,**不参与**任何恢复判定。
2. kill 场景:SyncRun 停留 running + SyncRequest 被 reconcile 置 interrupted/pending → executor 处理请求时**顺带**把同 request 的孤儿 SyncRun 行置 interrupted(同一次 reconcile 决策,不引入第二套对账)。
3. 重试:新 attempt = 新 SyncRun 行(attempt 递增),旧行保留为历史——进度天然按 attempt 分段,RECOVERING 状态可见。
4. sync.py 崩在 stage UPDATE 中途:单行 UPDATE 幂等,重启后由新 attempt 覆盖真相;updated_at 兼作事实新鲜度。
5. cron 直跑(request_id=NULL)照样写 SyncRun:Health 的事实面完整覆盖三条触发链。

## 10. Migration Impact

- 新表 sync_runs:纯 additive;dev/test 由 init_db create_all 自愈;生产按预检纪律(M0x)加显式幂等迁移(参照 ensure_recovery_columns/migrate_add_sync_requests.py 模式),**本轮不执行**。
- argv 增加 `--request-id`:向后兼容(旧 cron 命令不带该参 → NULL,行为不变)。
- 无既有列改动、无数据回灌、无锁风险;部署顺序:镜像统一升级(backend+sync-executor+sync-cron 同 sha,CI 单镜像纪律)。
- 回滚:新表可整体弃用(代码回退即停写),零数据损失风险。

## 11. ⑪/⑫ File Conflict Matrix

| 文件 | ⑪ Health | ⑫ Progress | 冲突 |
| --- | --- | --- | --- |
| backend/db/models.py(SyncRun 定义) | 读 | 读 | **共享核心:Wave-0 一次定型** |
| scripts/sync.py(--request-id/run 生命周期/终局落账) | 依赖写者 | 依赖写者 | **共享核心:Wave-0** |
| scripts/sync_executor_loop.py(argv 传 id + 对账顺带孤儿 run 置态) | 依赖 | 依赖 | **共享核心:Wave-0** |
| backend/services/sync_runs.py(新:写者/查询助手) | 读 | 读写 | **共享核心:Wave-0** |
| 迁移脚本(新) | 共享 | 共享 | **共享核心:Wave-0** |
| backend/api/admin/tech.py 或新 health 端点文件 | **独占** | — | 无 |
| backend/api/admin/sync_runs.py(新读端点)+ schemas.py 新 Out 模型 | — | **独占**(schemas 各加各的类,mergeable) | 低 |
| admin DataSources.tsx | 健康/空内容/维度徽章列 | 进度/Run 态列 + 活跃轮询 | **同文件双写=主要碰撞点**(列定义数组、join 逻辑同区) |
| admin lib/api 客户端 | health API 函数 | run API 函数 | 低(不同文件或同文件不同段) |
| tests | health 派生单测 | progress 写读+stage 单测 | 低(不同文件) |

## 12. Parallelization Decision

**PARALLEL_SAFE —— 前提是先执行 Wave-0 共享核心(约 0.5 天量级):**

1. **Wave-0(先行,独立小工作流,单工作树)**:SyncRun 模型+迁移、sync_runs.py 读写助手、`--request-id` argv 贯通、sync.py run 生命周期钩子(run_start/stage_update/run_finish 三个调用点)、executor 对账顺带置态、compose 无改动。交付即冻结接口(SyncRun 列集 + 助手函数签名 + argv 契约)。
2. **Wave-1 ⑪(WINDOW A)**:只读 SyncRun/documents/config,新 health 派生服务+端点+前端健康列(独立组件文件 `DataSourceHealthCell`,DataSources.tsx 只加一行 import+一列)。
3. **Wave-1 ⑫(WINDOW B)**:只写 stage/counters 调用点(_sync_one 内部 stage 埋点)+ run 读端点+前端进度列(独立组件 `SyncProgressCell`)。

碰撞面收窄为:**DataSources.tsx 列数组一行 + schemas.py 各自追加**——可 merge。若不做 Wave-0 而让 ⑪/⑫ 同时动 sync.py/models.py → **SEQUENTIAL_REQUIRED**(⑪ 先,⑫ 后)。推荐 Wave-0 方案,理由:两任务的真正共享依赖(运行真相+关联令牌)本来就必须先行一次成型,拆中做必然撞车。

## 13. Risks

1. **写放大**:crawl 大站每页一次 UPDATE × 每小时——量级 ~百行/小时,可忽略;但 stage UPDATE 必须容错(DB 抖动不得让同步失败,写失败仅 log)。
2. **SyncRun 与 SyncLog 双真相漂移**:终局必须 sync_log_id 回填 + 测试断言两表一致;Health 读数优先 SyncRun(结构化),历史审计仍以 sync_log 为准。
3. **对账复杂化**:reconcile_stale_running 加置态逻辑后,阶段⑩黄金测试必须全量回归(尤其 B1-B3/A1-A4)。
4. **前端轮询风暴**:⑫ 上线后若 admins 多开页面,5s 轮询 ×N;沿用现有 queryClient 去重即可,V1 不做推送。
5. **expected_state 缺失期**:EMPTY_UNEXPECTED 判定在产品拍板前只能全按"应有内容"保守处理 → 会把 DISCOVERY 类源误报 ACTION_REQUIRED;故 expected_state 是 §14 首个 Product Decision。
6. **connector 粒度不齐**:github 进度粗(阶段少、百分比时间段为 NULL)——产品预期要管理(诚实粗粒度 > 伪造细粒度)。

## 14. Open Product Decisions(仅列 material 语义,其余不升级)

1. **每源 expected_state(REQUIRED/OPTIONAL/DISCOVERY/EXCLUDED)**:新建源时配置。直接决定 EMPTY_EXPECTED vs EMPTY_UNEXPECTED vs 不评价。**⑪ 状态机完整性依赖它**;若暂不拍板,V1 只能实现"全部按 REQUIRED"的保守版(会误报探索源)。
2. **Freshness 阈值 k×sync_interval 的 k**(建议 2)与"STALE 是否阻断该源参与检索"(建议 V1 不阻断,只报告)。
3. **Health 呈现粒度**:单徽章+下钻 vs 五维并列(建议后者,与现 DSH 双徽章布局连续;具体 UI 归阶段⑬)。
4. **RECOVERING 归属**:建议仅 Run 态呈现(进度列),Health 列在 attempt 用尽前不降级、用尽后 ACTION_REQUIRED。请产品确认。
5. **SyncRun 保留期**(建议 30 天,清理机制可归⑭)——低危,默认即可。

## 15. Recommended Frozen Boundaries(建议冻结令,供 Planner 采纳)

1. sync_log 与 sync_requests 的既有列、谓词、状态机**零改动**;sync_log.status 语义保持 {success,partial,failed} 历史日志(HARD #1)。
2. SyncRun 单写者=sync.py 进程;executor 只在 reconcile 时置 interrupted;backend 只读。
3. 阶段进度 stage_total 不可知时**禁止**百分比/假进度(HARD #2/#3);进度事实只出自 SyncRun 持久字段。
4. Health 派生禁用 error_detail 文本解析;无证据维度=UNKNOWN,整体无证据=INSUFFICIENT_DATA(HARD:不许无证据 HEALTHY)。
5. 不建心跳/租约/item 级 checkpoint/推送通道(WS/SSE)/⑬ UI 全案/⑭ 调度治理。
6. 阶段⑧安全(G2 文档局部删/G3 discovered==0 守卫/incomplete discovery 不可退休)、失败 partial 不推进窗口、channel_visibility 检索边界——原样保留,新模型只观察不干预。
7. 生产访问零;迁移只写脚本不执行。

---

## 附:证据文件清单(全部只读核验)

backend/db/models.py:41-67,176-246 · backend/api/admin/data_sources.py:276-333,610-679 · backend/api/admin/sync_logs.py:17-60 · backend/api/admin/analytics.py:368,371-558 · backend/services/sync_requests.py:34,63-101 · backend/services/vector_consistency.py:23-165 · backend/services/source_visibility.py:17-108 · scripts/sync.py:158,161-176,196-222,223-347,414+,538-688,716-856 · scripts/sync_executor_loop.py:90-108,238-251,337+(阶段⑩) · backend/pipeline/ingest.py:362,401-470,599 · backend/connectors/web_crawl.py:372-467,595-675 · backend/connectors/github.py(fetch/_remote_has_updates/recovery_replay) · backend/connectors/woocommerce.py:98-119,257-288 · backend/connectors/safety.py:232-396 · backend/db/session.py:95-104 · deploy/prod/docker-compose.yml:106-137 · admin/src/pages/DataSources.tsx:143-177,348-695,1036-1137 · admin/src/hooks/useDataSources.ts:64-84 · admin/src/lib/api/techInsight.ts:83-130 · admin/src/lib/queryClient.ts:34 · admin/src/types/api.ts:49-81
