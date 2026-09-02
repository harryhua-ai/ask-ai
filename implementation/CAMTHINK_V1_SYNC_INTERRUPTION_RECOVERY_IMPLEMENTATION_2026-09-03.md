# CAMTHINK V1 — 阶段⑩ 同步中断后的自动恢复 · 实施报告

- 日期:2026-09-03(以执行时真实日期为准)
- Gate:⑩ SYNC INTERRUPTION RECOVERY V1(IMPLEMENTATION,TDD / Superpowers 工作流)
- 执行模式:Single Codex
- BASELINE_COMMIT:`2933118`(阶段⑨ FINAL,分支 `worktree-exec/sync-isolation-20260902`,未 squash,已推 origin)
- AUTHORITATIVE_DISCOVERY:docs 仓 `3e82391`(RECOVERY DISCOVERY 2026-09-02,Planner FINAL REVIEW = PASS / CLOSED)
- FINAL_IMPLEMENTATION_COMMIT:`dd399dd`(单提交,含实现+测试+迁移,已推 origin)

---

## 1. Discovery Findings Addressed(逐条对账)

| Discovery 结论 | 本 Gate 处置 |
| --- | --- |
| 恢复 = source 级幂等重跑 + 既有对账;否定 item 级 resume | 采纳为冻结策略(§3);无任何 chunk/item cursor 代码 |
| F16 GitHub SHA 短路盲区 | `--force-incremental-replay` 恢复上下文 + connector 短路旁路(§6)+ 真 git 仓 golden 回归(§12) |
| W6 web_crawl 快照覆写窗口 | 成员快照提交序重构:`fetch_deleted` 不落盘,`commit_membership_snapshot()` 在删除循环完成后推进(§7)+ golden 回归 |
| E1 假阴性(孤儿已完成被错标 failed) | `fail_stale_running` 一律 failed → `reconcile_stale_running` 按 sync_log 执行事实分流(§5) |
| 状态爆炸风险 | 持久状态保持四态;仅加 3 个最小恢复字段(§4) |
| 去重不退化 | `find_active_request` 零改动;retry 等待期仍在途 → already-running(测试固化) |

## 2. Architecture(实现后)

```
backend 容器(ONLINE PLANE,零改动)
    └ INSERT pending(同 key pending/running → already-running,含 retry 等待期)
          ▼
sync_requests(pending / running / done / failed + attempt_count/failure_kind/next_retry_at)
    ▼ claim_next():最旧到期 pending(next_retry_at IS NULL OR <= now),
      FOR UPDATE SKIP LOCKED,领用即 attempt_count+1
    ▼
sync-executor 容器(SYNC EXECUTION PLANE)
    ├ 启动:reconcile_stale_running() —— 遗留 running 按 sync_log 事实分流(§5)
    ├ execute_request():
    │    attempt>1 且 interrupted → 先复检 sync_log(孤儿已完成→done,不二次执行)
    │    runner 退出 0        → done
    │    退出非零             → failure_kind=runner_failed → 有界重试/终态
    │    spawn OSError        → failure_kind=spawn_failed → 有界重试/终态
    └ 恢复重试(attempt>1)以 argv 注入 --force-incremental-replay(F16)
          ▼
scripts/sync.py(唯一业务实现;--force-incremental-replay → run_sync(force_replay)
    → _inject_recovery_replay()(dataclasses.replace,不改 DB)→ GitHubConnector
      增量关闭 remote-SHA 短路,按 last-success 边界重读 git 历史)
```

## 3. State Semantics(§4)

- 持久状态仍是 `pending / running / done / failed`;INTERRUPTED/RETRYING 等为派生呈现态,不入库;
- 新增字段(`backend/db/models.py::SyncRequest`):
  - `attempt_count INTEGER NOT NULL DEFAULT 0`:实际启动过的 runner 次数,首次启动=1,由 `claim_next` 领用时递增(对账不递增);
  - `failure_kind VARCHAR(20)`:`interrupted / spawn_failed / runner_failed`(机器可判断,状态机不解析自然语言);
  - `next_retry_at TIMESTAMPTZ`:恢复重试到期时间,非空未到不可领取。
- 终态语义:`attempt_count >= MAX_TOTAL_ATTEMPTS(4)` 仍失败 → status=failed 且 next_retry_at=NULL(不再自动启动);done 时清空 retry/failure 痕迹。

## 4. Retry / Backoff Semantics(§15)

- `MAX_TOTAL_ATTEMPTS = 4`(initial + 3 recoveries);
- 退避:retry#1→30s、#2→120s、#3→600s(`DEFAULT_BACKOFF_SECONDS`);
- 测试/本地 harness 可经 `SYNC_RETRY_BACKOFF_SECONDS="3,4,5"` 注入短值;生产默认不变;
- 无限重试/tight loop 不存在:每次失败必经 `_schedule_retry`,达上限即 terminal;
- 范围冻结(§14):仅 stale-running/interrupted、spawn_failed、runner_failed(进程级)三类进入恢复;业务级 sync_log failed/partial(runner 正常退出)不做自动调度,继续依赖「不推进窗口 + 后续 sync 覆盖」。

## 5. Stale-Running Reconciliation(§6,AC1/AC4)

`reconcile_stale_running()`(执行面启动时,替代原「一律 failed」):
- 单源(source_id ≠ NULL)且 picked_at 之后存在 terminal sync_log(success/partial/failed)→ 本次执行实际完成 → **done**(E1 假阴性正式修复;业务失败不重跑,§14);
- 无 terminal 事实 → interrupted:status=pending + failure_kind=interrupted + next_retry_at(≥ 一个退避)——不立即派生第二个 runner,且**重试到期启动前再复检一次 sync_log**(等待期孤儿已完成→done,不二次执行;双跑窗口最小化);
- sync-all(source_id = NULL)→ 保守按中断整批有界重跑,不做部分完成推断(幂等正确性 > completion inference);
- 对账失败不阻断执行面启动(降级为原循环,日志留痕)。

## 6. F16 Fix(GitHub,AC6)

- `scripts/sync.py`:新 CLI 旗标 `--force-incremental-replay` → `run_sync(force_replay=True)` → `_inject_recovery_replay()` 以 `dataclasses.replace` 向每个 SourceConfig 注入 `recovery_replay=True`(SourceConfig 为 frozen dataclass;只改本次执行内存配置,不触碰 DB);
- `backend/connectors/github.py::fetch_changes`:`if self._recovery_replay or self._remote_has_updates(branch):` —— 恢复重放轮**无条件 fetch+reset 并按 last-success 边界读 git 历史**,即使 remote SHA == local HEAD;普通 run 语义零变化;
- 注入点在执行上下文层,queue DB 细节零耦合进 connector;未采用 full-sync 降级(保持 incremental replay,delete/prune/coverage 语义不变)。

## 7. W6 Fix(web_crawl,AC7)

- `backend/connectors/web_crawl.py`:`fetch_deleted`(全量轮)只计算差集并把当前成员集挂入 `_pending_snapshot`,**不再落盘**;新方法 `commit_membership_snapshot()` 在删除效应安全完成后由 sync 层调用推进快照;增量轮不排队不推进;
- `scripts/sync.py::_sync_one`:删除循环完成后调用 `commit_membership_snapshot()`(无该能力的 connector no-op);
- 效果:删除循环中途被 kill → 快照保持旧值 → 下轮重新报告同一差集 → 重复删除幂等(PRUNE IS DOCUMENT-LOCAL 不变);删除阶段异常 → sync_log failed 且快照不推进;
- G3 discovered==0 / incomplete discovery protection / authoritative membership 语义原样保留。

## 8. Migration(§17)

- `backend/db/session.py::ensure_recovery_columns(engine)`:`ADD COLUMN IF NOT EXISTS` ×3,幂等,旧行安全默认(0/NULL/NULL);
- `scripts/migrate_add_sync_requests.py` 更新:先 `init_db`(建缺失表)再 `ensure_recovery_columns`(补列);执行面主循环启动时亦自愈调用;
- **未执行 production migration**(PRODUCTION_ACCESS: NONE);上线窗口执行该脚本(任意时刻可跑,纯加列)。

## 9. E1/E3/E4/E5/E6 Evidence

- **E1 真实端到端 acceptance**(§11,`/tmp/syncexp/run_stage10_acceptance.sh`,输出留档 `/tmp/syncexp/acceptance_final.log`):真 pending → 真执行面领用(attempt=1)→ kill executor + 孤儿 runner(真中断,无完成事实)→ 重启 → 对账 interrupted→pending(next_retry_at≈3s,短退避注入)→ attempt=2 恢复 runner(**带 --force-incremental-replay**,日志留痕)→ sync_log success → **done**;终态:documents=6 = Weaviate 6,零重复,退避 3/4/5s(生产默认 30/120/600);ACCEPTANCE PASS=4 FAIL=0。
- **E6 固化**:`test_reconcile_interrupted_schedules_retry_only` + `test_stale_running_without_log_schedules_delayed_retry`(真中断→有界延迟恢复,非「一律 failed」)。
- **E3/E4/E5 自动化回归**(`tests/pipeline/test_recovery_convergence.py`,参数化 4 场景,确定性常跑):before/vector-written-ledger-not(W1)/partial-ledger(1/6)各中断后,全新 pipeline 源级重放 → **账本行数==向量对象数、UUID 全局唯一(零重复)、逐文档 chunk_count 一致**。
- **孤儿完成复检固化**:`test_retry_due_rechecks_orphan_completion_before_spawn`(done、runner_exit_code=None=未二次执行)+ 反向 `test_retry_due_with_no_completion_runs_recovery_runner`(exit=0=真启动)。

## 10. Tests Added/Updated(TDD:全部先看 RED 再实现)

| 文件 | 内容 |
| --- | --- |
| `tests/scripts/test_recovery_semantics.py`(新,15 测) | 模型字段默认/迁移幂等、claim 过滤+attempt 递增、stale 对账五分支(success 事实→done、无事实→interrupted、failed 事实→done、picked_at 前旧 log 不误判、sync-all 保守)、退避窗口断言(30s/120s)、attempt 用尽终态、success 清态、重试到期孤儿复检(正/反)、retry 等待期去重 |
| `tests/connectors/test_github_recovery_replay.py`(新,2 测) | F16 golden:真 git 仓(origin+clone,backdate commit A + 新 commit B + 手工推进 clone HEAD + API stub=origin HEAD);普通 run 短路复现空结果(bug 条件),恢复重放读出 b.md;普通 run 在真有更新时语义不变 |
| `tests/connectors/test_web_crawl_w6_snapshot.py`(新,6 测) | W6 golden:fetch_deleted 不推进快照、未提交快照跨重启可再发现、commit 后推进、无 pending 时 no-op、增量轮不触碰;`_sync_one` 集成:commit 在删除循环后、删除阶段失败不推进+sync_log failed |
| `tests/pipeline/test_recovery_convergence.py`(新,4 参数化) | E3/E4/E5 + 基线:中断后重放收敛(账本=向量、零重复 UUID) |
| `tests/scripts/test_sync_executor_loop.py`(改) | fail_stale_running 旧断言→reconcile 新语义;child failure→有界重试+到期收敛;spawn failure→spawn_failed 重试;fixture 补 ensure_recovery_columns |
| `tests/scripts/test_sync_triggered_by.py`(改) | fake run_sync 兼容 force_replay;新增 frozen SourceConfig 注入测试(dataclasses.replace) |
| `tests/services/test_504_golden_regression.py`(改) | fake argv 兼容 recovery kwarg(修复本 Gate 引入的回归) |

## 11. Full Regression(§20-H)

- **全量套件第 2 轮**:1049 passed / 6 skipped / 2 failed —— 2 个失败均为 `tests/connectors/test_web_crawl.py` 的**被 W6 新契约取代的旧断言**(fetch_deleted 内落盘快照),非生产行为回归;已按冻结语义更新这两个用例(更新后零生产代码改动)。
- **修复后复核**:受影响五目录(connectors/scripts/pipeline/services/api)904 passed / 4 skipped;`tests/connectors/test_web_crawl.py` 连跑 3 次稳定(18 passed)。
- **诚实声明**:上述 2 处为测试断言的历史语义更替,全仓第 3 轮完整重跑未执行(增量仅 2 个测试函数);Planner 如需完整绿线证据可复跑 `pytest tests`。
- 阶段⑧ 安全回归:全部包含于全量绿(safety/ingest_safety/discovery/delete×3)。
- 阶段⑨ 回归(§20-G):504 isolation 两实验 + trigger contract + 执行面隔离全绿(504-B 已随修复转绿)。

## 12. Compose Validation(§20-I)

`docker compose config --quiet` ×3(prod/dev/local)全部 PASS(本 Gate 未改 compose;prod/dev 的 sync-executor 服务自阶段⑨ FINAL 已在)。

## 13. Scope Audit(§22)

改动仅限:sync_requests 持久化/迁移/助手、sync_executor_loop、GitHub 恢复重放上下文、web_crawl 快照提交序、sync.py 调用上下文(--force-incremental-replay + W6 commit 调用)、恢复测试。未实现:Health(⑪)/progress(⑫)/Admin 治理(⑬)/调度统一与 GPU scheduler(⑭)/corpus 终验(⑮)/item checkpoint/heartbeat/lease/Celery/Redis/RabbitMQ/Kafka。业务级失败调度未扩权(§14)。

## 14. Residual Risks

1. 恢复重试与 sync-cron 理论可短暂重叠:靠幂等 ingest/document-local prune/incomplete-discovery 保守语义保证正确性(合同 §16);资源争用归阶段⑭;
2. 孤儿 runner 双跑窗口已最小化(延迟复检),但未做跨容器进程检测(V1 不要求,Discovery §22-4);
3. `failure_kind` 分类为封闭小集合;更细分类归阶段⑪ Health;
4. W6 per-doc 删除失败(被 delete_document 吞掉的部分失败)不阻断快照推进——与既有 per-doc 错误隔离语义一致,残留由 verify/对账披露(记录为已知边界);
5. `SYNC_RETRY_BACKOFF_SECONDS` 环境钩子仅应测试/本地使用,生产误设低值会加速重试(有上限保护,最多 4 次)。

## 15. Production Access Statement

**PRODUCTION_ACCESS: NONE。** 全程本地 worktree + 一次性实验库(已 DROP)+ 本地 Weaviate 专用 class(已删除);未 SSH 生产、未触生产 DB/Weaviate、未触发生产同步、未执行生产迁移、未部署。

## 16. Final Status

**STATUS: PASS(Executor 自评)。** 等待 Planner 独立检查 baseline→final diff、恢复状态机、F16/W6 golden、崩溃证据、安全不变量、测试证据与 scope 后裁决;阶段⑪(数据源真实健康状态)待 PASS 后方可开始。

## 17. Commits

- FINAL_IMPLEMENTATION_COMMIT:见最终响应(实现+测试+迁移,单提交推 origin)
- REPORT_COMMIT:见最终响应(docs 仓,单独提交,不夹带其他窗口变更)
