# CamThink V1 — Sync Truth Backend Implementation (W2)
# Issues #9/#11/#12/#15 — Shared Contract Owner

- **日期**:2026-09-03
- **执行模式**:PARALLEL IMPLEMENTATION — W2(独立 worktree,未合 main,未部署)
- **Frozen Discovery**:`docs/implementation/CAMTHINK_V1_DATA_SOURCE_RELIABILITY_OBSERVABILITY_SHARED_DISCOVERY_2026-09-03.md`(docs 仓 161b76d)
- **状态**:**CANDIDATE READY(自评 PASS,待 Planner FINAL REVIEW)**

---

## 1. Baseline

```
BASELINE = 1d6f6b5fe697b5f7a1b8decef1c29f51afcda937(三候选集成后的 authoritative main)
```

- 基线核验:`git status`(主仓仅既有 `.gitignore` 外来未暂存改动,零触碰)、`git log -10`、`git rev-parse HEAD`、`git worktree list`(10 棵,未触碰他树)。
- `origin/main` 在执行窗口内前进(87328dd→d4dc676,`x` + `revert: remove accidental planner probe file`),**净 tree 与 1d6f6b5 仍完全一致**;未 rebase/未追改,按契约以 1d6f6b5 为基。
- Worktree:`.worktrees/w2-sync-truth`(branch `worktree-exec/w2-sync-truth-backend-20260903`),独立 `.env`/测试纪律遵循既有工程记忆。

## 2. Final Commit

- 主仓实现:`a99788f` @ `origin/worktree-exec/w2-sync-truth-backend-20260903`(已推送,13 files,+2250/−10)
- 本报告:docs 本地仓 `<REPORT_COMMIT>`(见文件尾)

## 3. Changed Files(13)

| 文件 | 变更 | 说明 |
|---|---|---|
| `backend/db/models.py` | M(+8) | SyncRun +3 可空列(execution_device/fallback_reason/fallback_detail) |
| `scripts/migrate_add_sync_run_runtime_facts.py` | **A** | 幂等迁移:ADD COLUMN IF NOT EXISTS ×3 + 20 列校验 |
| `backend/services/sync_runs.py` | M(+243) | 设备词表 + `record_device()` + 5 个读侧查询 + `derive_source_state` + `is_ingestion_skipped` |
| `scripts/sync.py` | M(+79/−9) | `_RunTelemetry.device()` 冻结通道;HUNK-B:to_thread + 防抖实时落笔;no-change 落 `ingestion_skipped` |
| `backend/api/admin/sync_runs.py` | **A** | 新路由:`GET /sync-status`、`GET /sync-runs`、`GET /sync-health`(viewer+) |
| `backend/api/admin/schemas.py` | M(+105) | §19 响应 schema + SyncLogOut.items_unchanged |
| `backend/api/admin/sync_logs.py` | M(+1) | 暴露 items_unchanged |
| `backend/api/admin/router.py` | M(+2) | 挂载 sync_runs router |
| `tests/scripts/test_sync_run_runtime_facts.py` | **A** | 9 测:迁移幂等/词表拒绝/截断/派生矩阵/读侧查询 |
| `tests/scripts/test_sync_progress_realtime.py` | **A** | 5 测:实时落笔并发观测/失败契约/short-circuit/missing-vs-orphan |
| `tests/api/admin/test_sync_runs_api.py` | **A** | 10 测:sync-status 8 场景 + sync-runs 契约 + auth |
| `tests/api/admin/test_sync_health_derivation.py` | **A** | 2 测:五维端点场景(STALE/EMPTY_*/EXCLUDED/覆盖) |
| `tests/api/admin/test_sync_health_pure.py` | **A** | 7 测:健康纯函数矩阵 |

## 4. Migration

- `scripts/migrate_add_sync_run_runtime_facts.py`:幂等(checkfirst 建表 + `ADD COLUMN IF NOT EXISTS`)、重复执行无副作用、期望 20 列校验;新环境由 `init_db` create_all 自举。
- **生产纪律**:目标镜像一次性容器跑迁移 → 三服务切同 sha 镜像(沿用 193f206/1d6f6b5 先例);`up -d` 必带 `ASKAI_IMAGE_TAG`;本动作**未执行**(不在授权内)。
- 无数据回填(NULL=未知是合法语义);无 Weaviate/向量触碰。

## 5. API Contract(§19 逐字落地)

### GET /api/admin/sync-status(viewer+)
```
{ items: [ { source_id, state, request_id, attempt, recovering,
             stage, stage_current, stage_total, counters, execution_device,
             started_at, updated_at } ] }
```
- 主题集 = enabled 源 ∪ 在途请求源 ∪ running 运行源 ∪(sync-all 展开到 enabled);
- active 判定 = `sync_requests.status ∈ {pending,running}`(含 `source_id IS NULL` sync-all)**或** `sync_runs.status=running`(覆盖 cron NULL 直跑)——**#9 刷新恢复的唯一事实源,前端零启发式**;
- 状态 = `derive_source_state()`(新纯函数):sync-all 串行队列中**已处理切片如实呈现终态、未开始切片呈现 QUEUED**(多源互不污染);恢复语义(attempt_count>1 或 failure_kind)→ RECOVERING;无证据 → IDLE(禁 fake active);
- `stage_total IS NULL` 原样透传(分母未知 → 前端禁百分比);attempt = 在途请求 attempt_count,否则最近 run 的 attempt。

### GET /api/admin/sync-runs?source_id=&status=&page=&size=(viewer+)
```
{ items: [ { id, source_id, triggered_by, request_id, attempt, recovery, status,
             started_at, finished_at, duration_seconds, stage, counters, consistency,
             execution_device, fallback_reason, fallback_detail, error_summary,
             ingestion_skipped, sync_log: { id, status, items_new, chunks_written,
             items_deleted, items_unchanged, error_detail } | null } ], total, page, size }
```
- `chunks_written` = sync_log.items_updated(**真实语义命名**,如实暴露"写入 chunk 总数"而非"更新文档数");
- `duration_seconds` 读侧计算(finished−started);未终态 → null;
- `ingestion_skipped` 只来自 run-local 可证明事实:counters.ingestion_skipped(新)或历史行推导(unchanged>0 ∧ new=0 ∧ written=0);refill/孤儿处置等真实灌入绝不误标;
- `request_id IS NULL`(cron 直跑)合法呈现;无 sync_log 的 run → `sync_log: null` 不伪造。

### GET /api/admin/sync-health?days=30(viewer+)——**§19 之外的 additive 扩展**
```
{ items: [ { source_id, source_type, enabled, expected_state, overall, recovering,
             document_count, connectivity, sync, coverage, freshness, consistency } ] }
每维 = { state, evidence, as_of }
```
- **为何加此端点**:任务第 6 项要求"为 W3 提供足够 Health backend derivation support";若只在 python 服务层实现派生,W3(纯前端)无法消费,将被迫在后端补活=跨 scope 碰撞。放 W2 独占的新路由文件内(additive、零存量改动),Planner 可裁决去留。
- 五维派生(Discovery §11 逐条):Connectivity=最近 run 失败相位(DISCOVER/FETCH=failed,PARSE=degraded,其余失败不诬连接性);Sync=30 天窗口成功率(MIN 3,<3=insufficient_data);Coverage=仅结构化 counters(accepted/extracted)可证明,缺→unknown;Freshness=2×`sync_interval`(解析失败降级 24h 默认阈值),enabled 且从未成功=stale;Consistency=missing 与 extra/orphan **分别呈现**,任一>0=degraded,verification_failed=unknown;
- 聚合:EXCLUDED(最权威,overlay 不可改写)→ RECOVERING(active-run overlay)→ EMPTY_UNEXPECTED/EMPTY_EXPECTED(0 文档 × expected_state)→ worst-of(ACTION_REQUIRED>STALE>DEGRADED>PARTIAL)→ INSUFFICIENT_DATA → HEALTHY;**unknown 维度不拖低**(缺证据≠不健康),但每维如实呈现 unknown;
- `expected_state`:config.expected_state 显式覆盖(REQUIRED/OPTIONAL/DISCOVERY/EXCLUDED)> 缺省 enabled→REQUIRED / disabled→EXCLUDED。

### GET /api/admin/sync-logs
- 响应补 `items_unchanged`(additive,既有断言零破坏)。

## 6. Tests(实测证据)

| 套件 | 结果 |
|---|---|
| W2 新增 33 测(5 文件) | **33/33 绿**(连续 ≥3 轮稳定) |
| 相关回归(tests/scripts+api/admin+services+pipeline+db,已验证顺序) | **798 passed / 4 skipped / 0 failed** |
| 全量离线(HF_HUB_OFFLINE=1,TEST_DATABASE_URL) | **1145 passed / 6 skipped / 4 errors** |
| 基线对账 | 提交基线 1d6f6b5 收集数 1122=1155−33;基线绿 1112+新增 33=1145 ✓ 与 Wave-0 记忆「1112 绿/4 基线既有」吻合 |

- **4 个 embedder errors = 基线既有**(worktree 无真实 BGE 权重缓存所致;记忆在案「embedder 4 失败=基线既有测试隔离缺陷」),与本次改动无关。
- 必测项逐条:迁移幂等 ✓(双跑+列校验)、sync_runs 服务 ✓、request/run/log 关联 ✓、cron NULL ✓(test_6/test_8)、active/refresh recovery API ✓(test_2/3/4/5/7)、unknown denominator/no fake % ✓(stage_total NULL 透传断言)、history semantics ✓(test_8)、short-circuit ✓(realtime test_3/4)、consistency missing vs orphan ✓(pure test_5 + realtime test_5)、interrupted/recovery ✓(derive 矩阵 + API test_5)、realtime persistence while ingest active ✓(test_1:ingest 阻塞在工作线程期间并发轮询读到 EMBED 相位)。

## 7. Acceptance Results(对照任务要求)

1. ✅ 3 列 nullable/机器词表/自由文本拒绝(ValueError 测试在案)
2. ✅ `record_device(session_factory, run_id, *, execution_device, fallback_reason, fallback_detail)` 冻结签名;W1 未实现(不越界)
3. ✅ ingest 工作线程化+防抖落笔(1s)+中断保留已持久化事实;**顺带消除手动同步阻塞 backend 事件循环的 504 病根**(09-02 事故根因)
4. ✅ 两端点严格 §19;不要求前端猜 last_sync
5. ✅ counters 词表冻结:既有 7 键 + 新 ingestion_skipped;cpu_batches/cpu_docs/chunks_deleted 词表就绪留 W1/W2-P2 写点
6. ✅ 五维派生 + 无 Snapshot + 无证据不猜;REQUIRED 默认前置复核=**见 §8 discrepancy**
7. ✅ short-circuit 读侧可区分(counters.ingestion_skipped),不用 GPU/chunks 推断

## 8. Known Limitations & Discrepancies(如实上报)

1. **REQUIRED 默认的生产源清单复核未完成(Discrepancy,主动上报)**:Discovery §11 要求"实现首步复核 CamThink 已启用生产源清单后才能采默认 REQUIRED"。本轮未获生产读取授权,仅完成**代码级语义复核**(enabled/EXCLUDED 语义自洽、config.expected_state 覆盖通道就绪、channel_visibility 与健康语义正交);**生产行清单复核仍开放**——未静默硬编码:任何例外源可经 `config.expected_state` 覆盖,零迁移;请 Planner 裁决该 Gate 何时/由谁在生产只读完成。
2. `/sync-health` 为 §19 外 additive 端点(§5 理由),Planner 可裁。
3. sync-all 运行中、某源切片尚未开始时呈现 QUEUED(而非 RUNNING)——是**设计改进**(切片真相),但与旧 UI"点同步全部立刻全源同步中"预期不同,W3 呈现文案需知情。
4. `derive_source_state` 在请求终态后回退最近 run:若源在请求 done 后又有 cron 直跑行,呈现 cron 行终态(单一真相=最新事实,合理)。
5. 手动同步 runner exit 0(即使业务 failed)→ 无自动重试的既有契约**未改**(W1 CPU 回退落地后自然收窄);阶段⑩谓词零触碰。
6. 防抖间隔 1s 为模块常量(测试 monkeypatch 注入 0.05s);未 env 化(P2 候选)。
7. 共享 ask_ai_test 库存在**既有**顺序陷阱(function 级 `db_engine` drop 全表 vs admin session 级种子):以 `tests/scripts → tests/api/admin → tests/services → tests/pipeline → tests/db` 顺序稳定全绿;乱序(先 admin 后 scripts)会触发 85 errors——**基线既有,非本次引入**,建议 Planner 立项卫生修。
8. ⚠️ **跨窗口观察(需 Planner 知晓)**:主仓工作树(`~/Documents/GitHub/ask-ai`,非 worktree)存在**未提交的 W1 进行中代码**(`backend/embedder/fallback.py`、`tests/embedder/test_fallback.py`、`tests/pipeline/test_ingest_fallback.py` 等 25 用例)。W1 似乎直接占用了主仓工作区——与「独立 worktree」纪律冲突,存在与主仓其它活动(如生产热修)互踩的风险。本 W2 全程未触碰这些文件;本报告的"基线对照"曾误在该被污染工作树上跑过一次,已作废,改用提交级收集数对账(§6)。

## 9. W1 / W3 Integration Interface

**W1 消费(已就绪,零等待)**:
```python
from backend.services.sync_runs import record_device, EXECUTION_DEVICES  # gpu/cpu/gpu_to_cpu
await record_device(session_factory, run_id, execution_device="gpu_to_cpu",
                    fallback_reason="cuda_oom", fallback_detail="...")   # reason≤32, detail≤500
# 或 runner 内经遥测句柄(best-effort,失败不阻断业务):
await tel.device(session_factory, execution_device=..., fallback_reason=..., fallback_detail=...)
# counters 词表就绪:cpu_batches / cpu_docs(update_counters 直接合并写)
```

**W3 消费(契约冻结)**:§5 三端点响应形状;呈现纪律——`stage_total IS NULL` 禁百分比;`ingestion_skipped=true` → 文案"无上游变更,跳过灌入";execution_device NULL → "—";health 各维 unknown 原样呈现;recovering=true → RECOVERING 徽章(不改底层健康色);chunks_written 按"写入块数"措辞,勿称"更新文档"。

## 10. Production Boundary

- **PRODUCTION_MUTATIONS: NONE**——零生产读取/写入/部署;迁移脚本仅本地测试库验证。
- 上线前置(届时授权):迁移执行 → backend + sync-executor + sync-cron 三服务同 sha 切换 → 冒烟(sync-status 刷新恢复/历史/健康)。W2 独立上线无阻塞(W1 未合时 execution_device 恒 NULL,UI 呈现"—",完全向后兼容)。

## Final Verdict

**CANDIDATE READY** — 待 Planner FINAL REVIEW(重点裁决:§8.1 REQUIRED 生产清单 Gate、§8.2 additive 端点、§8.7 套件顺序卫生项、§8.8 主仓工作树 W1 占用)。
