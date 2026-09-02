# CAMTHINK V1 — 阶段9:同步任务与在线服务隔离 执行报告

- 日期:2026-09-02
- Gate:⑨ Sync Execution Isolation from Online Services(IMPLEMENTATION + VERIFICATION)
- 执行模式:Single Codex
- 基线(阶段⑧ accepted):`f481f943cf702c3fc9c5bafbc67126b2fc7af2db`
- 实现分支:`worktree-exec/sync-isolation-20260902`(worktree `.worktrees/ingest-safety`,基于 f481f94 直接续接,已推 origin)
- 实现提交:`8c27add`(8 files,+1026/−87)

---

## 1. Executive Result

**PASS(自评,待 Planner 独立 FINAL REVIEW)。**

Admin 手动同步(单源/全量)从「backend web 进程内 `asyncio.create_task` 同步执行 ingest」改为「提交给独立同步执行面:detached `scripts/sync.py` 子进程」。重型 ingest 不再触碰 backend event loop;backend 进程重启不级联终止同步;触发与执行生命周期解耦;manual / scheduled / CLI 三个触发方收敛到同一业务 runner。零新增基础设施(无 Celery/Redis/新容器);阶段⑧全部安全能力在子进程中原样生效。

## 2. Baseline / Final Commit

| 项 | 值 |
| --- | --- |
| SOURCE BASELINE | `f481f94`(阶段⑧ accepted implementation) |
| IMPLEMENTATION_COMMIT | `8c27add`(本 Gate 全部实现+测试,单提交) |
| FINAL_COMMIT | `8c27add`(报告不进入代码仓) |
| 分支/远端 | `worktree-exec/sync-isolation-20260902` → `origin` 同名分支 |

## 3. Current Architecture Investigation(实现前真实链路调查)

按 Gate §4 要求,先调查后动手。证据均来自基线 f481f94 源码与部署定义:

**Manual Sync**(`backend/api/admin/data_sources.py:612-696`,基线):
- `POST /{source_id}/sync` → DB 校验(404/禁用 400/github 分支预检)→ **`asyncio.create_task(_run())`** → `_run()` 在 **backend uvicorn 进程内**构造 `IngestionPipeline`,且**共享 backend 自身的 `app.state.embedder` 与 `app.state.weaviate_client`**,直接 `await _sync_one(...)`(基线 `:648`);
- `POST /sync-all` → 同模式 `:695`,顺序跑全部启用源。

`_sync_one` 内部的 connector fetch、`pipeline.ingest_all`(BGE embed + Weaviate v4 **同步 SDK**)全部是阻塞调用 —— 在 `asyncio.create_task` 里执行 = 占死 uvicorn event loop。**Golden incident 根因在基线原样存在**(阶段⑧只修了进入昂贵管线的内容安全,未动执行位置)。

**Scheduled Sync**:prod compose `sync-cron` 服务,`sh -c "while true; do python3 scripts/sync.py || true; sleep 3600; done"` —— **已经是独立执行面**:`run_sync()` 自建 engine / Weaviate client / BGE embedder / pipeline,与 backend 进程零共享。

**CLI**:`python scripts/sync.py [--source X] [--dry-run] [--reindex]`,同 `run_sync`。

**关键事实**:业务逻辑(连接器/安全/灌入/删除/一致性/SyncLog)**本就只有一份**(`scripts/sync.py::_sync_one`),manual 端点也在调用它。缺陷**仅是执行位置**,不是逻辑复制。

**容器拓扑**(deploy/prod/docker-compose.yml):`backend` / `sync` / `sync-cron` 三服务共用 YAML anchor `x-backend-base` —— **同一镜像、同一 env_file+environment、同一卷、同一 GPU 预留(nvidia count: all)**;差异只有 command 与 restart 策略。即:backend 容器内具备运行 `scripts/sync.py` 的**全部**条件,且与 cron 环境逐项等价。

## 4. Confirmed Root Cause(504 黄金事故)

```
Admin 点击同步
  → POST /data-sources/{id}/sync
  → asyncio.create_task(_run())          # backend 进程内
  → _sync_one():fetch + ingest_all       # BGE embed(CPU/GPU)+ 同步 Weaviate SDK
  → uvicorn event loop 被独占             # 大文件解析期单核 100%(.hef 184.8MB)
  → /health 无响应 → nginx upstream timeout → Admin/API 504
```

伴随事实(2026-09-02 生产实测):GPU ~95% util、VRAM 15.6/16.4 GiB。阶段⑧已切断「binary/.hef 进入管线」;本 Gate 切断「合法重同步拖死在线面」。

## 5. Chosen Execution Architecture

**Detached subprocess launcher(进程级隔离),零新增基础设施。**

新模块 `backend/services/sync_executor.py`:

- `launch_sync(source_id, triggered_by)` → `asyncio.create_subprocess_exec(sys.executable, <repo>/scripts/sync.py, --triggered-by manual, [--source X], start_new_session=True)`,`cwd=仓库根`,环境继承 backend 进程;
- `start_new_session=True`(POSIX setsid):子进程脱离 backend 进程组/会话 —— web 进程重启、被 supervisor 按进程组终止,都不级联杀同步;
- 进程登记 `_inflight[key]`(key=source_id 或 `"__all__"`):同 key 已有存活子进程 → `already-running`,不重复派生(§11 最低防 duplicate-storm;进程退出后 returncode 由事件循环回收,可再触发);
- spawn 失败(OSError)→ `SyncExecutorLaunchError` → 调用方必须显式报错;
- 子进程 stdout/stderr 继承 backend 输出(docker logs / nohup 日志可见),同步结果按既有约定写 `sync_log`。

`scripts/sync.py` 扩展 `--triggered-by {auto,manual,cron}`(默认 auto = 旧语义:带 `--source` 记 manual,否则记 cron);独立执行面的 sync-all 显式传 manual,不再被误记 cron。

## 6. Why This HOW Was Chosen

1. **最小正确**:零新容器/服务/中间件/依赖。隔离所缺的只是一个「不在 web 进程内跑」的执行位置,而 `scripts/sync.py` 本身就是现成的、cron 已验证的执行面。
2. **环境等价性免费获得**:backend 与 sync-cron 共用 anchor(同镜像/env/卷/GPU),backend 容器内派生的子进程与 sync-cron 执行语义**逐项一致**(AC14),不存在「两套 env」风险;不需要为 dev-only 架构做生产适配。
3. **生命周期解耦直接满足**:setsid 是 OS 标准答案,进程组信号打不到子进程(有真实进程树实验证据,见 §10)。
4. **不削弱冻结合同**:子进程运行的就是 `scripts/sync.py`,阶段⑧安全逻辑结构性包含(TechnicalSafetyPolicy / Safe Delete / G3 守卫 / PRUNE IS DOCUMENT-LOCAL 全在同一条代码路径)。
5. **为后续阶段留好接缝**:阶段⑩(中断恢复)可在此进程登记/`sync_log` 之上加 heartbeat persistence;阶段⑭(调度/并发)可把进程登记升级为 DB 分布式锁 —— 本 Gate 不预建。

否决项:Celery/Redis/RabbitMQ(引入全新基础设施,现有规模无证据必要);DB-backed 队列 worker(需要新常驻服务+轮询协议,阶段⑩⑭再议);专用 sync-worker 容器长驻(与 sync-cron 重复)。

## 7. Before / After Architecture Diagram

```
BEFORE(2026-09-02 生产 504 事故链)

Admin Request
  ↓
Backend / Uvicorn(单进程单 loop)
  ↓ asyncio.create_task(_run())          ← 共享 backend embedder/weaviate client
  ↓ sync ingest(fetch + BGE embed + 同步 Weaviate SDK)
  ↓ BLOCK event loop
/health timeout → nginx 504

AFTER(本 Gate)

ONLINE PLANE(backend / uvicorn 进程)
  ├─ POST /data-sources/{id}/sync ─┐
  ├─ POST /data-sources/sync-all ─┤ trigger only(校验 + 派生,立即 202)
  ├─ /health、Ask/Chat、Admin API  │ ← event loop 全程不被同步代码触碰
  └──────────────────────────────┘
                 │ launch_sync():create_subprocess_exec(start_new_session=True)
                 ▼
SYNC EXECUTION PLANE(detached 子进程,backend 容器内)
  scripts/sync.py(同一业务 runner)
  ├─ 自建 engine / Weaviate client / BGE embedder(生命周期自持)
  ├─ Connector → TechnicalSafetyPolicy(阶段⑧)→ Ingestion → Weaviate/PG
  └─ 结果写 sync_log(前端 5s 轮询既有契约)

Scheduled:sync-cron 容器 ── python3 scripts/sync.py ──▶ 同一执行面/同一 runner
CLI:      python scripts/sync.py ────────────────────▶ 同一执行面/同一 runner
```

## 8. Manual Sync Trigger Changes

| 维度 | BEFORE | AFTER |
| --- | --- | --- |
| 执行位置 | backend 进程内 `asyncio.create_task` | detached `scripts/sync.py` 子进程 |
| embedder/Weaviate | 共享 `app.state` 实例 | 子进程自建自释放 |
| 响应 | `200 {"status":"syncing"}`(触发即等于开跑,无失败语义) | `202 {"status":"accepted","source_id","pid"}` / `{"status":"already-running",...}` |
| spawn 失败 | 无此路径(进程内必成功) | `502 {"detail":"同步执行器进程启动失败: …"}`,登记不留痕 |
| 与 sync success 关系 | 模糊 | **accepted ≠ success**:触发不写 sync_log;结果由子进程落 sync_log |
| 前置校验 | 404/400/github 分支预检 | 原样保留(校验失败不派生) |
| 前端契约 | 单源响应不消费;sync-all 消费 `source_ids`/`count` | 两键保留,零前端改动 |

## 9. Scheduled / CLI Path

- sync-cron 容器命令**一字未改**(`python3 scripts/sync.py` 无参 → `triggered_by=cron`,auto 语义不变);
- CLI 不变;`--triggered-by` 为可选新旗标,显式优先于旧规则(`_resolve_triggered_by` 纯函数,7 个单测覆盖矩阵);
- **ONE EXECUTION PATH 达成**:manual(sync.py 子进程)/ scheduled(sync-cron)/ CLI 三方入口不同、runner 相同,无第二套同步业务实现(§12)。

## 10. Backend Restart Independence

`tests/services/test_sync_executor.py::test_backend_restart_does_not_kill_sync_child` —— **真实进程树实验,非 mock**:

1. 中间进程(backend 替身,自成一会话)经真实 `launch_sync` 派生同步子进程(stub 业务:心跳文件 + 收尾标记);
2. 心跳出现(子进程已派生)→ `os.killpg(中间进程组, SIGTERM)`(等价 supervisor 重启 web 进程的整组终止);
3. 断言:中间进程被信号终止;**子进程幸存**(`os.kill(pid,0)` 通过);
4. 通知收尾 → 子进程自行跑完写 done 标记(孤儿不僵死)。

另有直接断言:子进程 `getsid ≠ 调用方 getsid`(setsid 生效)。

**边界(诚实声明)**:`docker restart backend` 属容器级生命周期,CRI 会连带容器内全部进程 —— 这属于「同步子进程自身被 kill 后的恢复」,是阶段⑩的显式范围,本 Gate 合同(P4 第 4 条)限定的是 **web 进程**重启,已满足并留证。

## 11. 504 Golden Incident Regression

`tests/services/test_504_golden_regression.py`,三组实验:

- **A(对照:事故类别可检测)**:tiny uvicorn 真实网络服务,复刻事故模式(trigger 立即返回,`call_soon` 随后 inline 阻塞 loop 3s)→ `/health` 1s 预算内**必然超时** —— 证明 harness 能捕获 event loop 饥饿,不是只会测「trigger 端点 10ms 返回」。
- **B(新执行面)**:同量级 CPU burn(真实单核打满 ~4s 的 hash 循环子进程,非 sleep 桩)经 `launch_sync` 交给独立执行面 → burn 期间 `/health` × 15 与轻量 Admin 路由全部 200,`max(latency) < 1.0s`;burn 结束后在线面依旧健康。
- **C(真实 app)**:真实 `backend.main.app` 的 `/health`,在真实 burn 子进程运行期间探测 × 15 全 200 有界延迟。

结论:**NO TIMEOUT / NO EVENT LOOP STARVATION / NO 504 CLASS BEHAVIOR**。因果链被切断的证据:`Admin Trigger → 202 accepted(立即)→ 独立子进程承载全部重活 → backend /health 全程有界响应`。

## 12. Failure Semantics

| 状态 | 语义 | 载体 |
| --- | --- | --- |
| TRIGGER ACCEPTED | 202 `accepted` + pid;不写 sync_log | 端点响应 |
| ALREADY RUNNING | 同 key 存活子进程在跑;不重复派生 | 端点响应 |
| EXECUTOR START FAILED | 502 显式 detail;登记不留痕、不伪装 accepted | 端点响应 |
| SYNC PROCESS STARTED | backend 日志记录 key/pid/triggered_by/argv | 结构化日志 |
| SYNC EXITED SUCCESS/FAILED | 子进程按既有约定写 sync_log(status/coverage/error_detail);stdout 继承 backend 输出 | sync_log + 容器日志 |

明确不做(合同边界):heartbeat persistence / SyncRun stage counters / 自动重试 —— 阶段⑩⑫。

## 13. Security Review

- Admin auth/permission 零退化:两端点保留 `_: EditorDep`,匿名触发测试断言 401/403 且零派生(AC12);
- **无 shell**:`create_subprocess_exec` argv 列表逐元素传参,无 `shell=True`、无 `os.system`、无字符串拼命令;含 `$()/;&|\`` 元字符的 source_id 以单元素原样到达子进程(专项测试);不引入任意命令执行入口(AC13);
- 子进程只运行仓库内固定脚本 `scripts/sync.py`(路径由 `REPO_ROOT` 推导,非用户可控);用户输入仅作为 `--source` 参数值,由 sync.py 与 DB 校验消费;
- 无新匿名端点、无新鉴权绕过面。

## 14. Deployment Composition

- **compose 零修改**:`deploy/{prod,dev,local}/docker-compose.yml` 原样 —— 隔离不需要新服务:backend 容器与 sync-cron 共用 anchor(同镜像含 scripts/.venv、同 env、同 corpus/models 卷、同 GPU 预留),子进程在 backend 容器内即可获得与 cron 完全一致的执行条件;
- 三份 compose `docker compose config` 校验 **PASS**;
- GPU:backend 服务本就预留 nvidia all(ask 查询 embed 需要),手动同步子进程同容器共享该预留;生产 VRAM 紧张时可能出现 embed 变慢 —— 属 **B 类共享硬件争用**,与 A 类进程阻塞已在测试与本报告中分离,B 类记录到阶段⑭;
- 本 Gate **未构建镜像、未触生产**;下次 RC 镜像自然包含本改动,无需额外部署步骤。

## 15. Files Changed

| 文件 | 变更 |
| --- | --- |
| `backend/services/sync_executor.py` | **新增**(120 行):独立执行面 launcher + 进程登记 + 显式失败 |
| `backend/api/admin/data_sources.py` | 两端点重写:create_task 内联执行 → launch_sync 提交;202/502 语义;移除死导入 |
| `scripts/sync.py` | `--triggered-by` 旗标 + `_resolve_triggered_by` 纯函数 + run_sync 参数透传 |
| `tests/api/admin/test_sync_trigger_isolation.py` | **新增** 8 测:触发契约 |
| `tests/services/test_sync_executor.py` | **新增** 6 测:argv 构造/会话隔离/子进程失败/spawn 失败/重启独立(真实进程树) |
| `tests/services/test_504_golden_regression.py` | **新增** 3 测:504 三组实验 |
| `tests/scripts/test_sync_triggered_by.py` | **新增** 7 测:触发方标记矩阵 |
| `tests/api/admin/test_data_sources.py` | 重写 sync-all 测试为新契约(置雷防线:进程内执行 `_sync_one` 即断言失败) |

## 16. Tests Added(24 新增 + 1 重写)

- 触发契约(8):detached 派生+202 accepted / spawn 失败 502 / 重复触发 already-running(含死进程回收后再触发)/ 恶意 source_id 原样传参 / 匿名 401·403 零派生 / accepted 不写 sync_log / sync-all spawn 失败 502 / 无启用源 noop 零派生;
- 执行器生命周期(6):argv 构造×2(单源/全量)/ 子进程独立会话 / 子进程非零退出不影响调用方且可再触发 / spawn 失败显式异常 / **backend 重启独立(真实进程树 killpg 实验)**;
- 504 黄金回归(3):实验 A/B/C(§11);
- triggered_by(7):解析矩阵 + CLI 旗标 + main() 透传;
- 重写(1):sync-all 返回启用源跳禁用 + 单子进程派生 + `start_new_session` 断言。

## 17. Tests Actually Executed

| 套件 | 结果 |
| --- | --- |
| 本 Gate 新增/重写(5 文件) | **30 passed** |
| 阶段⑧安全回归(safety/ingest_safety/discovery/delete×3/c10/scripts) | **84 passed, 3 skipped** |
| 更广回归(pipeline+connectors+api+services+scripts) | **871 passed, 4 skipped** |
| **全仓完整套件**(tests/,37 分钟) | **1018 passed, 6 skipped,0 失败** |
| `docker compose config` ×3(prod/dev/local) | PASS |
| ruff(新文件)| 0 违规(基线既有 3 处债务未动,见 §21) |
| black(新文件 + 我改的两个既有文件)| 全部 clean(基线既有区域不重排,只植增量) |

skips 均为真实 Weaviate 门控用例(未设 `P0A_WEAVIATE_PORT`),仓库既有约定。

## 18. Acceptance Criteria 逐项

| AC | 判定 | 证据 |
| --- | --- | --- |
| AC1 重型同步不在 backend 进程内执行 | **PASS** | 端点唯一副作用=launch_sync;测试内置 `_sync_one` 置雷;504 实验 B/C |
| AC2 trigger 只提交、快速返回 | **PASS** | 202 立即返回;校验+spawn 外无任何重活 |
| AC3 accepted ≠ success | **PASS** | 触发零 sync_log 写入(专项测试);结果仅由子进程落库 |
| AC4 heavy sync 期间 /health 不超时 | **PASS** | 实验 B/C:真实 CPU burn 子进程运行期 /health ×15 全 200、max<1s;实验 A 证明 harness 可检出事故类别 |
| AC5 期间 Admin/API 可响应 | **PASS** | 实验 B 轻量 Admin 路由 200;真实 app 面实验 C |
| AC6 backend restart 不终止独立 sync | **PASS** | §10 真实进程树实验(setsid + killpg) |
| AC7 Manual/Scheduled/CLI 同一 runner | **PASS** | 三方均为 `scripts/sync.py`;cron 命令未改;build_sync_argv 测试 |
| AC8 阶段⑧ Technical Safety 仍生效 | **PASS** | 子进程运行同一分支同一脚本(结构性包含);safety/ingest_safety 测试绿 |
| AC9 Safe Delete / Discovery guard 无回归 | **PASS** | delete×3 + discovery_completeness 测试绿(84 回归集内) |
| AC10 launch 失败不假报成功 | **PASS** | 单源/sync-all 两面 502 测试;executor 层显式异常测试 |
| AC11 子进程失败可诊断 | **PASS** | sync_log 既有落库 + stdout 继承 + backend 日志 pid/argv;非零退出测试 |
| AC12 Admin auth 边界不退化 | **PASS** | EditorDep 未动;匿名测试 401/403 零派生 |
| AC13 无 shell injection / 任意命令执行 | **PASS** | argv 列表传参;恶意元字符 source_id 原样到达;无 shell=True/os.system |
| AC14 部署组合可真实运行 | **PASS** | 三份 compose config OK;backend 容器=cron 等价环境(anchor 同源) |
| AC15 无提前实现⑩/⑪/⑫/⑭ | **PASS** | §20 Scope Audit |
| AC16 无 production access/mutation/deployment | **PASS** | 全程本地 worktree;PRODUCTION_ACCESS: NONE |

## 19. Regression

- 阶段⑧安全回归 84 passed / 3 skipped(G1 技术安全边界、G2 删除 UUID 化、G3 发现完整性守卫、真实 Weaviate 门控用例按约定 skip);
- 既有 admin API 套件(conftest 全 fixture 面)、c10、sync_logs、上传/编辑流等全绿(并入 871/1018 统计);
- 既有 scripts 套件(sync_db/window/coverage/gap_heal/discovery)全绿;
- 唯一动过语义的既有断言:`test_sync_all_...` 的 `status=="syncing"` → `"accepted"`(产品语义按本 Gate 合同有意变更);c10 的 400 分支预检用例未动且仍绿(校验先于派生)。

## 20. Scope Audit(非目标逐条核对)

未实现、未引入:production 访问/部署/触发;neoruntime-apps 恢复;interrupted sync recovery(阶段⑩);heartbeat persistence;full Sync Run model;health 五维;progress UI;Admin 页面重设计;per-source 调度节奏;分布式并发锁(阶段⑭);GPU 资源调度(阶段⑭);System Runtime 页;Answer Correctness;production eval;genericize ASK-AI;无关重构(compose 未改、无新依赖)。

## 21. Follow-ups / Tech Debt

1. **进程登记为 backend 单进程内存**(§11 允许):backend 多 worker/多副本下去重失效 → 阶段⑭ 分布式锁/DB run 表;
2. **容器级重启终止子进程**:docker restart backend 会连带容器内进程 → 阶段⑩ 中断恢复(heartbeat + 补同步)正式覆盖;本 Gate 已保证 web 进程级独立;
3. **GPU 双份 BGE 常驻窗口**:同步子进程自建 embedder,与 backend embedder 短暂并存(~1-2GB VRAM)→ B 类共享硬件争用,记录至阶段⑭(生产 VRAM 紧张时段需关注);
4. **already-running 只按 key 去重**:单源触发与 sync-all 可并行(与基线语义一致);全量+单源并发 GPU 争用同属 3;
5. ruff 基线既有 3 处债务(`data_sources.py` I001/RUF100、`sync.py` I001)沿用阶段⑧清单,本 Gate 不扩面;
6. 阶段⑩可复用资产:`_inflight` 登记、`SyncLaunch`、backend 日志的 pid/argv 行 —— 无需返工即可挂 heartbeat。

## 22. Production Access Statement

**NONE。** 全程在本地 worktree(`.worktrees/ingest-safety`)与本地测试栈完成;未 SSH 生产、未触生产 DB/Weaviate、未构建/推送镜像、未触发任何生产同步。

## 23. Final Status

**STATUS: PASS(Executor 自评)。**
等待 Planner 独立 FINAL REVIEW(真实 diff / 测试 / 架构边界 / 报告)后判定 FINAL PASS / PARTIAL / FAIL。本报告不进入代码仓;下一阶段(⑩ 同步中断后的自动恢复)须待 Planner PASS 后方可开始。
