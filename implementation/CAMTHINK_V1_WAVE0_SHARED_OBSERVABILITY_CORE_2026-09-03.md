# CAMTHINK V1 — ⑪+⑫ Wave-0 共享可观测核心 实施报告

- 日期:2026-09-03
- 窗口:PARALLEL — WINDOW A(Single Codex)
- **BASELINE_COMMIT: `269cadb0ce6a3ce47059e0f4b074f356e41612eb`**(origin/main 实测核验一致)
- **IMPLEMENTATION_COMMIT: `6715e2c`**(origin/worktree-exec/wave0-observability-20260903,线性单提交,远端哈希核验一致)
- WORKTREE: `.worktrees/wave0-observability`
- **PRODUCTION_ACCESS: NONE**

## 1. 交付概览

新增持久 **SyncRun** 概念:一行 = **ONE SOURCE × ONE ATTEMPT** 的运行真相。
不实现 Health UI / Progress UI / Health 派生(明确 out of scope);只建立
可靠的 persistent runtime truth,供 ⑪(读时派生 Health)与 ⑫(Progress)
共用。JOB SUCCESS ≠ KNOWLEDGE HEALTH 原则落到表级语义:SyncRun 终态只表达
"这次 attempt 是否跑完",业务结局永远以 sync_log 为准(经 sync_log_id 链接)。

## 2. Schema(`sync_runs`,models.py 新增)

| 字段 | 语义 |
| --- | --- |
| id | PK autoincrement |
| request_id(int,可空,索引) | 关联 sync_requests.id;**cron/CLI 直跑 NULL=合法**(AC4) |
| source_id(str,索引) | 本行只属于一个源(sync-all 逐源展开 N 行) |
| attempt(int,默认 1) | 第几次启动,与 SyncRequest.attempt_count 同刻度 |
| recovery(bool) | 是否恢复重放(与 --force-incremental-replay 同源) |
| triggered_by(str) | manual/cron |
| status(索引) | **仅真实运行四态**:running/completed/failed/interrupted;QUEUED/WAITING/RECOVERING/IDLE 为派生态(不持久化虚假行) |
| stage / stage_current / stage_total | canonical 九阶段词表 + 计数;**stage_total=NULL=分母未知** |
| counters(JSONB) | 事实计数:discovered/accepted/extracted/failed/rejected/docs_total/docs_done/deleted… |
| consistency(JSONB,可空) | verify_source_vectors 结构化落库(expected/actual/missing/refill/stale/orphan) |
| error_summary(Text,可空) | 失败摘要,≤500 字符截断 |
| sync_log_id(UUID,可空) | 终局回填,request→run→log 链路终点 |
| started_at / updated_at / finished_at | 生命周期时间戳 |

**假百分比不可表达(AC6)**:`progress_fraction(total, current)` 仅在
total 非 None 且 >0 且 current 非 None 时返回 0..1,否则 None——分母未知时
只能呈现真实计数(如 "FETCH: 37 documents")。

**派生态词表(纯函数 `derive_run_state`,支持全部八态)**:在途请求权威优先——
running+attempt>1/failure_kind→RECOVERING;pending+恢复语义→RECOVERING;
pending+next_retry_at 未来→WAITING;pending→QUEUED;无在途请求→最近 run 行
终态 COMPLETED/FAILED/INTERRUPTED;遗留 running→RUNNING(待对账盖章瞬态);
两者皆无→IDLE。RECOVERING 归属 Run state ✓。

## 3. Migration(AC11)

- `scripts/migrate_add_sync_runs.py`:checkfirst 幂等建表 + 17 列完备性校验,
  重复执行无副作用(测试两次执行断言);生产纪律下的显式迁移契约。
- 新环境 bootstrap:`init_db` create_all 自愈自举,行为不变。
- 未执行任何生产迁移(PRODUCTION_ACCESS=NONE)。

## 4. SyncRun Lifecycle(AC2)

attempt **启动即落行**(不等同步结束——与 SyncLog 只在结尾落一行互补):

```
executor claim → 递增 attempt → spawn(runner 携带 --request-id/--attempt)
  └─ sync.py _sync_one: start_run(running, stage=DISCOVER)
       → FETCH(materialize 后 total 可信才写 total)
       → PARSE(run_stats discovered/accepted/extracted/failed/rejected 计数;
               非全量轮 total 保持 NULL)
       → CHUNK/EMBED/INDEX(ingest_all 批界回调缓冲,批后统一落笔)
       → CONSISTENCY(无变更路径:verify 报告结构化落库,处置后复验再更新)
       → 终局 finish(completed/failed + sync_log_id 回填)
```

- 遥测**尽力而为**:`_RunTelemetry` 全路径 try/except,DB 抖动只降级无遥测,
  绝不影响业务同步(测试:遥测工厂抛错时 SyncLog 照常落库)。
- dry_run 不落 run 行(与不写 SyncLog 同语义)。
- 异常退出不假 RUNNING:进程 kill 后,executor 启动对账把该 request 的
  running 行盖章 **interrupted**(finished_at 落);孤儿实际完成(有 terminal
  sync_log 证据)则盖章 **completed + sync_log 链接**(实际完成优先,AC12 前置)。

## 5. Request → Run → Log Linkage(AC3)

- executor:`build_runner_argv/run_runner` 增加 `request_id/attempt` 透传 →
  `--request-id N --attempt M`;`execute_request` 以递增后的 attempt 传入。
- sync.py:CLI 新参 → run_sync → _sync_one 逐源 start_run 落行;终局回填
  `sync_log_id`(确定性 (request, source, attempt) 定位唯一行,测试断言)。
- cron/CLI 直跑:两参缺省 → request_id=NULL、attempt=1,行为合法(测试断言)。

## 6. Stage⑩ Recovery Compatibility(AC7/AC8/AC9)

**sync_requests 仍是唯一恢复权威;SyncRun 零参与恢复判定。**

- `reconcile_stale_running` 三分支裁决逻辑**逐字未动**(完成事实→done /
  cap 用尽→终态 failed / 否则 interrupted+退避+证据锚);仅在每支裁决
  **之后**调用 `_stamp_runs_finalized` 同步遥测:有证据→completed+log 链,
  其余 running→interrupted(服从而非第二权威,AC9)。
- B1 孤儿吸收路径:pre-spawn 复检发现完成事实 → 请求 done + 遥测 completed
  (复用 `_latest_terminal_log_id`,原 `_has_terminal_sync_log_after` 改为
  其布尔包装,谓词语义不变)。
- attempt cap / attempt_started_at 证据锚 / F16 重放旁路 / W6 快照提交序
  **零改动**;⑩全文件回归绿(见 §8)。

## 7. Retention(AC10)

`purge_expired_sync_runs(days=30)`:删 started_at 早于保留期的**非 running**行;
running 行绝不清理。挂载点=executor 启动(reconcile 之后,失败不阻断);
无调度器/框架。测试:过期清、running 留、fresh 留、now 可注入。

## 8. Tests(AC 覆盖)

新增 `tests/scripts/test_sync_run_core.py` **25 测**:创建/身份三元组/请求
链接/NULL 请求/阶段流转/counters 合并/未知分母禁百分比(含持久层)/终态
成功+失败(截断)/中断盖章/恢复 attempt/孤儿完成吸收/cap 盖章幂等/sync_log
链接可查/retention/派生态矩阵/迁移幂等/一致性结构化落库 + 集成:argv 贯穿、
对账三分支盖章(裁决与遥测双断言)、`_sync_one` 端到端(ingest 完成前行已在、
确定性链路、业务失败、遥测降级)。

兼容更新:`tests/services/test_504_golden_regression.py` argv 桩 `**_w0`
(新透传参数,claim/drain/落账逻辑全真实不变)。

## 9. Regressions

- **定向(⑨+⑩+受影响面)**:164 passed / 3 skipped(scripts 全目录、⑨
  trigger_isolation、data_sources/delete 双套、504 golden、收敛、F16 golden、
  W6 golden、safety 双套);格式化后复核 115+613 全绿。
- **全量(离线隔离环境)**:**1087 passed / 6 skipped / 4 failed(81 秒)**。
  4 failed = `tests/embedder/test_bge.py`(reranker×3+dimension×1):
  **基线既有缺陷**——纯净 `269cadb` 树同环境复现完全相同的 4 失败(本地缓存
  无 reranker 模型,离线必挂);联网环境全绿是以下载模型为代价(恰为本任务
  明令禁止的不受控下载)。与既有集成门记录「embedder 4 失败=基线既有测试
  隔离缺陷」一致。与 Wave-0 改动无关(改动面不含 embedder)。
- 诚实声明:本窗口首次全量曾未带隔离环境启动(触发基线 embedder 测试重下
  模型),发现后立即终止并以离线隔离环境重跑;上一节全量数据以隔离轮为准。

## 10. Known Limitations

1. CHUNK/EMBED/INDEX 进度为**批界缓冲、批后统一落笔**(ingest 阻塞事件循环
   期间无法逐批写 DB);阶段边界事实完整,EMBED 相位内粒度归 ⑫ 如需更细
   须引入同步侧遥测通道(明确不在 Wave-0)。
2. web_crawl 全量轮 crawl 中段(discover→逐页)无过程计数——connector 内部
   埋点属 ⑫ 范畴;DISCOVER 阶段的 accepted/extracted 终值已可事实呈现。
3. SyncRun retention 无后台调度,依赖 executor 重启时机执行清理(低频清理
   可接受;调度归 ⑭)。
4. 遗留 running 的 SyncRun(进程被 kill -9 且 executor 未重启)在派生态中
   呈现 RUNNING 直至下次对账——诚实瞬态,不伪造终局。

## 11. Scope Audit

改动仅限:SyncRun 模型、sync_runs 服务、sync.py 贯穿与遥测句柄、executor
argv/盖章/retention、ingest_all 可选回调(默认零行为变化)、迁移脚本、
新增测试与 504 桩兼容。**未实现**:Health 派生/UI、Progress UI、WebSocket/SSE、
SourceHealthSnapshot、expected_state、调度治理、生产部署。未合 main、未部署。

## 12. Production Access Statement

**PRODUCTION_ACCESS: NONE。** 全程本地 worktree + 本地测试库;未 SSH 生产、
未触生产 DB/Weaviate、未执行生产迁移、未部署、未触发生产同步。
