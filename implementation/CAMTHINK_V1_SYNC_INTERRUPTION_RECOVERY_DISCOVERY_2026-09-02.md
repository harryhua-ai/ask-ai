# CAMTHINK V1 — 阶段⑩ 同步中断后的自动恢复 · Recovery Semantics Discovery

- 日期:2026-09-02
- Gate:⑩ Recovery Semantics Discovery(DISCOVERY / CONTRACT PREPARATION,**非实现 Gate**)
- 执行模式:Single Codex
- BASELINE_COMMIT:`2933118`(阶段⑨ FINAL,worktree `worktree-exec/sync-isolation-20260902` HEAD,工作区干净,工程源码零改动)
- 报告性质:事实(fact)/ 推断(inference)/ 建议(recommendation) 三类标注;所有事实均给真实文件/函数锚点

---

## 1. Executive Summary

**结论:阶段⑩应采用「检测中断 → source 级幂等重跑 → 既有对账收敛」的最小正确恢复,不建 item 级 checkpoint resume(NOT WORTH IMPLEMENTING)。**

支撑这一结论的四个代码/实验事实:

1. **单文档灌入天然幂等**(fact):向量写按确定性 UUID `uuid5(source_id#chunk_index)` 覆盖(`backend/pipeline/ingest.py::_deterministic_uuid`,insert_many→replace 回退),账本按 `(content_hash, branch)` 主键 upsert(`_upsert_postgres`)。重跑同一文档不产生重复 chunk、不产生重复索引(E3/E4/E5-rerun 实验证实:kill 后重跑,Weaviate 对象数=账本行数=6,零重复)。
2. **对账引擎已存在且生产验证过**(fact):`backend/services/vector_consistency.py::verify_source_vectors`(只读缺口报告)+ `scripts/sync.py::_handle_no_change`(refill 重灌 + `_reconcile_orphan_vectors` 三分类孤儿处置)+ 复验。中断留下的任何账本↔向量分歧都在它的检测范围内。
3. **两个真实恢复盲区不在「重跑」本身,而在 runner 的前置状态**(fact,均有代码锚点):GitHub SHA 短路盲区(§9.6)与 web_crawl 状态文件覆写窗口(§9.5)。「无脑重跑」对这两类不收敛或收敛得晚,Stage⑩ Contract 必须处理。
4. **现行交接面只有「诚实失败」,没有恢复,且存在假阴性风险**(fact + 实验):执行面重启把一切遗留 running 标 failed(`scripts/sync_executor_loop.py::fail_stale_running`),不查 sync_log 实际结果——E1 端到端实验证明:执行面被杀后孤儿 runner 继续跑完(sync_log success、corpus 完全一致),交接行却永久卡 running,下一次重启会把它错标为「中断失败」。

## 2. Baseline

- 工程基线:`2933118`(阶段⑨ FINAL ACCEPTANCE CORRECTION 提交;本 Discovery 全程工作区干净,HEAD 未变,CODE_MUTATION=NONE)。
- 实验环境:一次性 Postgres 库 `sync_recovery_exp`(已 DROP)+ 本地 Weaviate 专用 class `RecoveryExpDoc`(已删除)+ 真实 `IngestionPipeline`/`scripts.sync.run_sync`/`sync_executor_loop`(仅嵌入函数用确定性 stub 替换——嵌入计算非持久化路径;§13/§16)。
- main 上的 Widget Hotfix lineage 未触碰、未合并(遵 Gate §1)。

## 3. Current Sync Lifecycle(fact)

```
Admin POST /data-sources/{id}/sync|sync-all(backend 容器)
  └ 校验(404/400/github 分支预检)→ submit_sync_request() INSERT pending
      backend/services/sync_requests.py:同 key 已有 pending/running → already-running,不重复入队
      写库失败 → SyncRequestSubmitError → HTTP 502
  ▼
sync_requests 表(pending)
  ▼ scripts/sync_executor_loop.py::claim_next()(sync-executor 容器)
      UPDATE ... WHERE id = (最旧 pending ... FOR UPDATE SKIP LOCKED) → running + picked_at
  ▼ execute_request() → 子进程 python scripts/sync.py --triggered-by manual [--source X]
  ▼ run_sync()(scripts/sync.py)
      _load_configs_from_db()(执行时点重新读 DB,enabled only)
      逐 cfg:_sync_one()(异常全捕获 → SyncLog failed,不向上传播,不影响后续源)
  ▼ mark_finished():runner 退出码 0 → done;非零/启动失败 → failed(+error)
```

状态归属(fact):
| 状态 | 谁写 | 何时 commit |
| --- | --- | --- |
| pending | backend 端点 | 请求时 |
| running | executor `claim_next` | 领用时 |
| done/failed | executor `mark_finished` | runner 退出后 |
| SyncLog(per-source) | `_sync_one` finally 块 | 每源结束时(异常也写,`dry_run` 除外) |

## 4. Current Persistence Semantics(fact)

| 存储职守 | 谁在同步中写 | 键/身份 | 中断敏感点 |
| --- | --- | --- | --- |
| Weaviate `Document` collection | IngestionPipeline(索引/覆盖/prune/delete) | 确定性 UUID `uuid5(source_id#chunk_index)` | 覆盖语义→中断天然幂等;prune/delete 是删除性操作 |
| PG `documents`(账本) | `_upsert_postgres`(逐文档独立 commit)/`_delete_postgres` | `(content_hash, branch)` PK;行含 source_id+chunk_count | 逐文档提交→批内可停在任意中间态;账本是「期望态」权威 |
| PG `sync_log` | `_sync_one` finally | 逐源逐 run;status/coverage/error_detail | **per-source 完成与否的唯一权威**;失败/中断不推进增量窗口 |
| PG `sync_requests`(交接) | backend/executor | 自增 id;pending/running/done/failed | 只反映**进程级**交接结果,≠ 业务健康 |
| 本地文件系统 | github clone 工作区(`~/ask-ai-corpus/<repo>`);web_crawl `data/crawl-state/<id>.json` | 工作区 HEAD / 状态 JSON | **跨 run 持久**:先于 ingest 推进即可造成恢复盲区(§9.5/§9.6) |

## 5. Current Atomicity Model(fact)

单文档灌入的真实步骤序(`ingest.py::ingest_document` / `_ingest_doc_batch`,两路径同构):

```
safety 嗅探 → chunk → embed
→ previous_count = 账本读旧 chunk_count(覆盖前读,P0-A)
→ Weaviate insert_many(128/块;失败对象 replace 回退;确定性 UUID 覆盖)
→ 账本 upsert(单文档独立事务;内容变更=同事务先删旧版本行再加新行)
→ 若 success_count == total:_prune_stale_chunks(文档局部确定性 UUID 点删)
   (success_count < total 时故意不 prune,留待下轮)
```

原子性判定:**document 级非原子,但每一步要么幂等可重放、要么 fail-safe**:
- 向量写:幂等覆盖(同 UUID replace),不会重复;
- 账本:per-doc 事务,批内可部分提交(实验 E5 实证 1/6 行中间态);
- prune:`previous_count is None → 不删`(fail-safe);只点删本档自己 UUID(阶段⑧冻结,`_prune_stale_chunks` docstring 内 P0-A 不变量);
- `_upsert_postgres` 失败被吞(error 日志,不 raise,`ingest.py:585-586`)→ 账本可静默落后,由 no-change 校验路径兜底(§9)。

`scripts/sync.py` 退出码语义(fact):`main()` 从不对源级失败返回非零——**exit 0 ≠ 源健康**;仅初始化级故障(建表/连库/连 Weaviate)向上抛导致非零退出。per-source 真相只在 `sync_log`(status + coverage + error_detail;失败/partial 不推进 `_last_success_at` 窗口,`_compute_since`)。

## 6. Current Interruption Behavior(各击杀点实测,fact,§16)

| 击杀点 | sync_requests | sync_log | documents | Weaviate | 恢复现状 |
| --- | --- | --- | --- | --- | --- |
| executor 死于 claim 前 | pending 原样 | 无 | 无 | 无 | 重启后正常领用(队列天然持久) |
| executor 死于 claim 后(E2≡E6 终态) | running 悬挂 | 无 | — | — | **无自动处理**;下次 executor 重启 → 一律标 failed |
| runner 死于 fetch(E3) | (交接面未接,行 pending) | 无 | 无 | 无(collection 都未建) | 零副作用;重跑全量收敛 |
| runner 死于向量写后/账本前(E4,W1) | 同上 | 无 | **0 行** | **6 对象** | 重跑收敛(幂等覆盖+账本补齐),无重复 |
| runner 死于批内部分账本提交(E5) | 同上 | 无 | **1/6 行** | 6 对象 | 重跑收敛 |
| runner 死于 sync_log 落库前(E5 窗口) | — | 无 | 完整 | 完整 | 重跑重灌同内容(idempotent)后补 log |
| executor 死于 runner 运行中、runner 幸存(E1 端到端) | **running 永久悬挂** | **success(工作实际完成!)** | 完整 | 完整 | 无人在场收尾;下次重启把它错标「中断失败」(**假阴性实证**) |
| executor 重启遇遗留 running(E6) | failed(诚实) | — | — | — | 现行终点;**不查 sync_log,不自动恢复** |

## 7. Failure Taxonomy

判定语义(fact 基础上的分类,recommendation 标注处置):
- **Can Detect?** 当前系统能否检测;
- **Auto(建议)**:Stage⑩ 是否应自动恢复;**BOUND**:有界次数;**MANUAL**:人工。

| # | 类别 | Observed State(真实落点) | Can Detect | 建议 Recovery | 说明 |
| --- | --- | --- | --- | --- | --- |
| F1 | executor 进程 crash | running 悬挂(在跑 runner 成孤儿**继续跑完**——E1 实证) | ✅ 重启边界(fail_stale_running) | 查 sync_log:已完成→补 done;未完成→有界重试(BOUND) | 孤儿 runner 与重试并发→必须先判完成再重试 |
| F2 | runner 进程 crash | 交接行 running 悬挂;sync_log 无行;corpus 落在击杀点中间态(E3/E4/E5) | ✅ 同上 | 有界重试 source 级重跑(BOUND) | 重跑幂等已证 |
| F3 | 容器重启/宿主重启 | 同 F1(compose restart 不杀独立 sync-executor 容器;宿主重启三容器全停) | ✅ | 有界重试(BOUND) | restart: unless-stopped 拉起执行面 |
| F4 | Postgres 暂时不可用 | executor 循环 try/except 继续轮询(`run_forever`);runner 初始化失败 exit≠0→handoff failed | ✅ | 有界重试+退避(BOUND) | 账本/交接都在 PG,恢复以 PG 可用为前提 |
| F5 | Weaviate 暂时不可用 | `_ensure_collection`/写入异常→ingest_all raise→sync_log failed(exit 0!);或 init 抛→exit≠0 | ✅(sync_log/exit) | 有界重试+退避(BOUND) | partial 不推进窗口,天然重覆盖 |
| F6 | 嵌入/GPU OOM | embed 异常→ingest_all raise(RuntimeError)→sync_log failed | ✅ | 有界重试+退避(BOUND);连续 N 次 OOM → MANUAL | 禁止无限重试(Gate §11) |
| F7 | GitHub/网络 fetch 失败 | connector 内部重试(web_crawl `_http_get` 3 次);最终失败→sync_log failed / 全部失败 raise | ✅ | 有界重试(BOUND) | 增量窗口未推进,重试覆盖缺口 |
| F8 | web_crawl 部分页失败 | run_stats 记账→coverage 行;≥80% 记 success 行仍留明细,<80% partial,0 抽取 failed | ✅(coverage) | 既有窗口机制自愈,无需恢复动作 | partial 不推进窗口 |
| F9 | 单条目解析失败 | 单文件/单页 skip+记账(github `_read_local_changes` warning;web_crawl failed_urls) | ✅ | 不恢复(设计如此:bad item ≠ source 后果) | 呈现在 coverage/error_detail |
| F10 | sync-all 中单源失败 | `_sync_one` 捕获→该源 failed,后续源继续 | ✅ | 该源按 F7/F6 有界重试;其余源不受牵连 | sync_log per-source 判定 |
| F11 | 索引中途被杀 | E4/E5 中间态 | ✅(重启边界) | 有界重试(BOUND) | 幂等已证 |
| F12 | prune/delete 中途被杀 | delete_document:Weaviate 先删→账本后删;中间被杀=「向量已删账本还在」→ verify 整篇缺失→refill 拉不到(源已无)→partial 循环 | ✅(verify/partial) | 重跑同源:github/web_crawl 的 fetch_deleted 会重报删除(窗口未推进)→补删收敛 | fs/woo 无 fetch_deleted,删除本就只走全量对账 |
| F13 | 向量写后、账本前被杀 | E4:6 向量/0 账本 | ✅(verify orphan→账本零 embedding 重建;或 rerun upsert) | 有界重试即收敛 | 无需新对账机制 |
| F14 | 账本后、sync_log 前被杀 | 账本完整、无 log | ✅(重启边界+sync_log 缺行) | 有界重试;若源无变更,no-change 校验直接 success | 重跑 idempotent |
| F15 | 恢复期间远端已变化 | 增量窗口=上次成功→重跑覆盖「since 以来全部变更」,与「中断期间的新变更」合流一次拉齐 | ✅(设计使然) | 无需特判 | 合流语义安全:确定性 UUID+content_hash 去重 |
| **F16** | **GitHub SHA 短路恢复盲区(NEW,本 Discovery 发现)** | clone 已 fetch+reset(HEAD 推进)后 ingest 被中断→下轮 `_remote_has_updates`(API SHA==本地 HEAD,github.py)→yield 空→no-change verify(旧 corpus 一致)→**success,窗口推进,该批变更永久静默丢失** | ❌ 当前不可检测! | **MANUAL/必须特殊处理**(§9.6) | 现状即使无恢复也存在;Recovery 若「盲目重跑」会踩入并给假 success |

## 8. Connector-specific Recovery Differences(fact)

| connector | Discovery 确定性 | Fetch 可重放性 | 删除判据 | 恢复特殊性 |
| --- | --- | --- | --- | --- |
| github | clone+glob 确定性 | **增量有 SHA 短路盲区(F16)**;全量 fetch_all 幂等可重放 | `git log --diff-filter=D`(窗口内,可重放) | 恢复必须绕过/补偿 SHA 短路 |
| filesystem | rglob 确定性 | mtime>since 可重放(窗口未推进) | **fetch_deleted 恒 []**(代码注释明示);删除只靠全量对账 | 中断重试天然安全;无删除重放需求 |
| web_crawl | sitemap+BFS,`max_pages` 上限内确定;远端内容随时可变(F15 合流) | 增量=lastmod≥since 可重放;全量=重爬幂等 | 全量轮状态文件差集;**增量轮恒 [] 且不覆写状态**(防 BFS 误删) | 状态覆写窗口(§9.5);discovered==0 保护(G3)继续封印不完整发现的删除 |
| woocommerce | API 分页确定 | modified_after 可重放 | fetch_deleted 恒 [](诚实降级,代码注释) | 同 fs;删除靠全量对账(若有) |

## 9. Partial Write / Divergence Windows(§9 核心问题:PG 账本=A 而 Weaviate=B 的窗口全景)

每个窗口五问:现状自愈?/ 重跑修复?/ 重跑恶化?/ 需要专门对账?/ Stage⑩ 最小集是否必须处理?

| # | 窗口 | 触发(代码锚点) | 自愈/重跑/恶化/专门对账/Stage⑩ | 证据 |
| --- | --- | --- | --- | --- |
| W1 | 向量已写、账本未写(或 `_upsert_postgres` 被吞) | kill 于 insert_many 后、账本 commit 前(E4 实证) | verify→orphan→零 embedding 账本重建 自愈;重跑 upsert 修复;不恶化;无需新对账;**Stage⑩ 无需新增**(既有机制覆盖) | E4+E4-rerun |
| W2 | 账本已写、stale 尾 chunk 未 prune | kill 于账本后 prune 前(代码序) | verify chunk 集合不一致→refill 重灌(重写+补 prune)自愈;不恶化;无需新对账;否 | 代码路径 `_handle_no_change`;E5 亦覆盖 |
| W3 | 批内部分文档账本提交 | kill 于批中间(E5:1/6) | 重跑逐文档 upsert 补齐;不恶化;否 | E5+E5-rerun |
| W4 | delete_document:向量已删、账本行未删 | kill 于 delete 中段 | github/web_crawl:重跑 fetch_deleted 重报(窗口未推进)补删收敛;verify 会持续报缺失→partial(诚实暴露);否(重跑即可) | 代码序 `delete_document` |
| W5 | sync_log 未落(工作已完成) | kill 于 finally 前 | 重跑补 log;不恶化;否 | E5 窗口 + E1 孤儿完成场景 |
| **W6** | **web_crawl 状态文件已覆写、删除循环未完成** | kill 于 `fetch_deleted`(全量轮,内含 `_save_state`)与 delete_document 循环之间 | 状态差集被覆写→删除意图**永久丢失**;残留=账本+向量双全的 ghost,**verify 不可见、orphan 对账不可见**(它只查 Weaviate-有/账本-无);当前不自愈;重跑不修复也不恶化;**需要专门对账或写序修正;Stage⑩ 必须处理** | `web_crawl.py::fetch_deleted`(`_save_state(current_ids)` 先于 sync.py 的 delete 循环) |
| **W7** | **GitHub clone 已推进、ingest 未完成** | kill 于 `_git_sync_branch` 后、ingest 完成前 | 下轮 SHA 短路(F16)→假 success+窗口推过,**不可自愈、不可检测**;重跑(普通)不修复且**恶化**(推进窗口坐丢变更);**需要恢复机制特殊处理;Stage⑩ 必须处理** | github.py `_remote_has_updates`/`_git_sync_branch` |
| W8 | 账本静默落后(非中断:`_upsert_postgres` 吞错) | ingest.py:585-586 | no-change verify 兜底(orphan 重建/refill);否 | 代码路径 |

## 10. Retry Safety Matrix(fact+recommendation)

| connector × 模式 | 盲重试(RETRY_SAME)安全性 | 说明 |
| --- | --- | --- |
| github 增量 | **不安全(假 success 风险,F16)** | 需「上次 run 未完成→强制绕过短路」补偿 |
| github 全量 | 安全 | fetch_all 幂等 |
| filesystem 增量/全量 | 安全 | mtime 重读;删除不依赖重试 |
| web_crawl 增量 | 安全 | lastmod 窗口重放 |
| web_crawl 全量 | 安全(但 W6 需写序修正) | 重爬幂等;G3/Guard 继续生效 |
| woo 增量/全量 | 安全 | modified_after 重放 |

## 11. Recovery Mode Matrix(recommendation)

| Failure Class | Detection | Recovery Mode | Safety Condition | Auto? | Escalation |
| --- | --- | --- | --- | --- | --- |
| F1/F2/F3/F11(执行面/runner 中断,infra 无恙) | executor 重启边界:stale running + sync_log 无该源完成行 | **RESTART_SOURCE**(同一请求行回 pending,attempt+1) | attempt < MAX(建议 3);恢复前查 sync_log 防孤儿已完成 | ✅ | 超限→failed(recoverable 标记)→MANUAL |
| F1 变体(孤儿 runner 已完成) | stale running + **sync_log 有完成行** | **标记 done**(仅收尾,不重跑) | sync_log status=success 且 finished_at > picked_at | ✅ | — |
| F4/F5/F6(依赖暂不可用/OOM) | runner failed(exit≠0 或 sync_log failed) | **RETRY with backoff**(有界) | 分类可重试;连续 OOM/连错 N 次 → MANUAL | ✅ | 3 次退避后 MANUAL |
| F7/F8/F10(抓取类失败) | sync_log failed/partial | **既有窗口机制**(partial 不推进,下轮自覆盖)+ 有界重试 | — | ✅(经正常轮询/重试) | 持续 partial → 健康维度(阶段⑪) |
| F9(单条目) | coverage/error_detail | **不恢复** | bad item ≠ source 后果 | — | — |
| F12(delete 中断) | verify 缺失/partial;fetch_deleted 重报 | **RESTART_SOURCE**(窗口未推进→重报删除) | fs/woo 不适用 | ✅ | ghost 持续 → MANUAL(阶段⑬治理) |
| F16(GitHub SHA 盲区) | 「上次 run 未完成」标志(picked_at > last completed) | **RECONCILE_THEN_RETRY**:重试前强制 fetch+reset(绕过短路)重读 git log(since=last success) | 仅对 github 增量恢复路径 | ✅ | — |
| W6(web_crawl 状态覆写丢失删除意图) | 当前不可检测 | **写序修正**(Stage⑩ contract:仅删除循环完成后覆写状态)使窗口消失;存量窗口期间靠全量对账 | — | ✅(修正后) | — |
| 非法配置/鉴权失败/不支持内容 | sync_log failed + error 分类 | **MANUAL_ACTION_REQUIRED** | 非瞬态 | ❌ | Admin 呈现(阶段⑬) |

## 12. Recommended Minimal Recovery Semantics(§8 关键产品问题回答)

**问:是否需要「精确从中断 chunk 继续」?**
**答:不需要,明确 NOT WORTH IMPLEMENTING。** 依据(fact):
1. 重放粒度已是「源内全量/增量重拉」,成本=一次 connector fetch+幂等覆盖写;中断节省的只是「已成功文档的重写」,而这些重写本就是廉价覆盖(无 GPU 重嵌入的内容仅当内容未变——但 embed 是恢复路径的主要成本,chunk 级 resume 仍需重新判断内容是否变化,等于重建 entire diff);
2. chunk/item 级 resume 需要新增持久 checkpoint(文档→chunk 游标),引入新的分歧面,违背 Minimum Correct Recovery;
3. 现有对账(verify→refill→reconcile)已保证最终一致(阶段⑨前生产验证);
4. 真正的恢复难点不在 resume 粒度,而在 F16/W6 两个「重跑不收敛」盲区——Stage⑩ 资源应集中于此。

**恢复语义最小集(recommendation)**:
1. **检测**:executor 启动边界(现有 `fail_stale_running` 位置)判定 stale running;按 sync_log 有无完成行分流:「已完成→补 done」/「未完成→可重试」/「spawn 失败→按类别」。
2. **重试**:同一请求行回 pending(attempt_count+1),上限 3 次;infra 类失败加退避(30s/120s/600s 封顶);超限→failed+MANUAL 语义。
3. **盲区补偿**:github 恢复重试强制绕过 SHA 短路(重读 since=last success 的变更);web_crawl 状态覆写移到删除循环完成后(写序修正)。
4. **对账**:复用既有 verify→refill→reconcile,不新建;恢复重跑天然经过它(no-change 路径)或被幂等覆盖吸收(有变更路径)。

## 13. Recommended State Machine(§10:避免状态爆炸)

fact:Product Contract 高层 RUN STATES(IDLE/QUEUED/RUNNING/WAITING/RECOVERING/COMPLETED/FAILED/INTERRUPTED)是**呈现层**概念;DB 需要的是**持久执行状态**最小集。

recommendation:**持久状态保持 4 个不变**(pending/running/done/failed),零迁移即可起步:
- `INTERRUPTED` = 派生呈现态:「failed(或 running-stale)且 error/failure_kind=中断、attempt<max」——由 Admin/查询层推导,不落新状态;
- `RECOVERING/RETRYING/WAITING` = 同理派生(pending+attempt>0 即「重试等待/恢复中」),不落库;
- 新增**字段**(非状态):`attempt_count int default 0`、`next_retry_at timestamptz null`(退避用;可选)、「失败种类」可由 error 前缀分类(interrupted/spawn_failed/runner_failed)或加 `failure_kind` 一列——倾向后者,查询/呈现更干净。

状态转移(全部既有+一条回边):
```
pending → running(领用)
running → done(退出码 0 且无 error)
running → failed(非零/spawn 失败/中断标记)
failed → pending(attempt<max 且 failure_kind 可重试)  ← Stage⑩ 新增唯一回边
done 终态;failed(attempt≥max 或不可重试类)终态
```

## 14. Request Retry Lineage Recommendation(§12)

三个候选:
- (a) 复用同一行回 pending+attempt++(**推荐**);
- (b) 新建 retry 子行(parent_request_id 血统);
- (c) A 保持 running + B 新行(明确排除:双活重复同步,违反 dedupe)。

**推荐 (a)**,理由:
- Stage⑨ already-running 去重语义(同 key pending/running 查重)无需任何改动,天然防 A/B 双活(§12 的核心担忧被结构消除);
- 审计性由两层承担:attempt_count 表达次数,sync_log 天然是逐 run 权威史(每 attempt 一行,含 triggered_by/coverage/error)——血缘通过「同 source_id+时间序」可完整重建;
- 简单性:无新表、无新外键、无 lineage 清理问题。
- 代价(诚实声明):单行看不到 per-attempt 细分,需 join sync_log;对 Admin 排障足够(阶段⑫进度模型再增强)。

## 15. Crash Experiment Design(fact,已执行)

- 环境:一次性 PG 库 + 专用 Weaviate class(实验后均删除)+ 真实 `scripts.sync.run_sync` 全链(真实 `_sync_one`/SyncLog/verify/no-change 对账/确定性 UUID/insert_many/replace 回退/账本/prune)。
- 受控注入:确定性 stub connector(expstub,6 docs)+ 确定性 stub embedder(仅嵌入计算;**持久化/索引路径全真实**)+ checkpoint sleep(FETCH/EMBED/LEDGER/PRUNE/DELETED)+ marker 文件确认击杀落点;`kill -9` 定点击杀。
- E1 端到端:真执行面 + 真 runner(真 BGE)+ kill + 重启,观察交接行/孤儿 runner/收敛。
- 资产:实验脚本位于 `/tmp/syncexp/`(一次性,不入仓);源码零改动(Gate §17)。

## 16. Crash Experiment Results(fact,全部实测)

| 实验 | 击杀点 | 击杀后状态(sync_requests / sync_log / documents / Weaviate) | 收敛重跑结果 |
| --- | --- | --- | --- |
| E1 端到端 | 执行面 running 中被 kill(timeout) | **running 悬挂**;孤儿 runner 幸存**继续跑完**:sync_log success、6/6 一致 | 执行面重启后现行行为=错标 failed(假阴性);无人补 done → **Stage⑩ 动机实证** |
| E2 | claim 后即刻(构造) | running、零副作用(代码事实:drain_once 领用→spawn 间无任何持久化) | ≡E6 |
| E3 | FETCH 中 | 全零副作用(collection 未建) | 6 docs 全一致、1 success |
| E4 | 向量写后/账本前(W1) | **6 向量 / 0 账本 / 0 log** | 6/6 一致、1 success、**零重复对象**(幂等覆盖实证) |
| E5 | 批内部分账本提交后 | **6 向量 / 1 账本行 / 0 log**(部分提交中间态) | 6/6 一致、1 success |
| E6 | 重启遇遗留 running | 现行:诚实标 failed「执行面进程重启:上次运行中断」,**无自动恢复** | —(即 Stage⑩ 要补的行为) |

附注(诚实):E3-E5 首轮曾因 driver 的子 shell `$!` 未杀中 python 而出现「原 runner 幸存+重跑并发」场景——该意外反而实证了**并发双跑下终态仍完全收敛**(幂等覆盖);修复后以上表为准。

## 17. Frozen Safety Invariants(恢复不得破坏,全部继续成立)

- **PRUNE IS DOCUMENT-LOCAL**:任何恢复动作不得引入 TEXT 属性过滤删除;prune/delete 仅确定性 UUID 点删(ingest.py 不变量);
- **阶段⑧ Technical Safety Boundary**:恢复重跑走同一 runner→二进制/模型工件过滤、硬尺寸、pre-read 过滤、G3 discovered==0 守卫全部继续生效;
- **不完整发现不删除**:中断后的 incomplete discovery 不得参与退休——代码证明:`web_crawl.fetch_changes` 增量轮 `_last_run_full=False` → `authoritative_source_ids()=None` → `_reconcile_orphan_vectors` 中 `complete=False` → 全部 `EXTRA_UNRESOLVED_ORPHAN` 保留(scripts/sync.py `_discover_source_docs`/`_reconcile_orphan_vectors`);G3 discovered==0 守卫继续封印;
- **保守失败行为**:失败/partial 不推进增量窗口——恢复重跑自动重覆盖缺口,这是整个恢复安全性的基石;
- Recovery 不得以 disable safety/skip guards/force delete/blind reset 换取「成功」。

## 18. Risks

1. **F16 修复的回归风险**:绕过 SHA 短路若实现为「恢复轮无条件 fetch」,会放大对 GitHub API 的调用;建议仅对「上次未完成」的恢复轮触发(以 attempt/上次 run 状态为条件);
2. **W6 写序修正的状态一致性**:覆写移到删除循环后,若删除循环被 kill,状态文件保持旧值→下轮重报删除(幂等收敛);但多次失败会累积重报,无害但需日志可观测;
3. **孤儿 runner 与恢复重试并发**(E1 实证场景):恢复前必须以 sync_log 判定孤儿是否已完成,否则双跑(虽幂等无害,但浪费 GPU 且日志混淆);
4. **attempt 退避与 sync-cron 相互作用**:cron 每小时自然重试 = 隐式恢复通道;Stage⑩ 的显式重试需避免与 cron 轮形成叠加风暴(同 key 去重已防,但退避窗口设计需知悉);
5. **假阴性修复的语义变更**:fail_stale_running 从「一律 failed」改为「查 sync_log 分流」,是对阶段⑨已验收行为的修订,需在 Stage⑩ contract 中显式声明并回归 E6 场景。

## 19. Non-goals(Stage⑩ 不做)

五维健康(⑪)、实时进度/统计(⑫)、Admin 治理中心(⑬)、资源调度/分布式锁终态/GPU scheduler(⑭)、最终 Corpus Integrity 验收(⑮)、item 级 checkpoint resume、heartbeat/lease 持久化(单副本部署下无必要——inference,部署假设变更时重议)、无限重试。

## 20. Suggested Stage⑩ Implementation Boundary(recommendation)

**做**:
1. 交接面恢复语义:`fail_stale_running` → 查 sync_log 分流(完成→done;未完成→可重试)+ `attempt_count`(+可选 `failure_kind`)+ failed→pending 有界回边(退避);
2. F16 补偿:github 恢复轮绕过 SHA 短路(条件:该请求为恢复重试);
3. W6 写序修正:web_crawl 状态覆写移至删除循环完成后;
4. 恢复可观测:交接行 error/attempt 呈现 + backend/executor 日志(阶段⑫前的最小诊断面);
5. 回归:全部既有测试 + E1-E6 场景固化为自动化测试(disposable 环境)。

**不做**:§19 全部;以及不改 sync.py 业务逻辑本身(恢复全部发生在交接面/连接器前置状态层,runner 保持「一次诚实执行」语义)。

## 21. Suggested Acceptance Criteria(recommendation,供 Planner 冻结)

- AC1 kill 执行面于任意阶段(pending/running),重启后按 sync_log 事实收敛:已完成→done,未完成→有界重试至完成;
- AC2 恢复重跑后 corpus 一致(账本=向量,零重复 chunk)——E3/E4/E5 场景自动化;
- AC3 github 恢复轮重放不踩 SHA 短路(F16 场景:clone 推进后中断→恢复轮补齐变更→无假 success);
- AC4 web_crawl 删除意图不因中断丢失(W6:kill 于删除循环中→重启后删除收敛);
- AC5 attempt 上限与退避生效;永久失败类不重试;无无限重试;
- AC6 同 key 去重不退化(A 中断→恢复期间新触发→already-running);
- AC7 阶段⑧安全/PRUNE IS DOCUMENT-LOCAL/G3 全量回归绿;
- AC8 现行「诚实失败」语义修订后,E6 场景仍对真失败标 failed,对孤儿已完成标 done;
- AC9 手工类失败呈现在交接行/Admin 可见;
- AC10 无 production 接触;工程实现走独立分支+worktree 纪律。

## 22. Open Questions(供 Planner 冻结 Contract 时裁决)

1. MAX_ATTEMPTS=3 与退避曲线(30s/120s/600s)是否合意?cron 隐式重试与显式重试的叠加是否需要专门节流?
2. `failure_kind` 落列 vs error 前缀约定?
3. F16 补偿的实现位置:连接器内(感知「恢复轮」)vs runner 参数(如 `--force-fetch`)?倾向后者(连接器保持无状态,恢复语义在交接面表达);
4. E1 场景的孤儿 runner:执行面重启后是否需要等待/检测旧 runner 进程(单容器内可 pgrep,跨容器不可)——建议 V1 不做进程级检测,仅靠 sync_log 结果分流(已覆盖正确性;并发双跑幂等无害);
5. 手工类失败的 Admin 呈现放本 Gate 还是顺延阶段⑬?

## 23. Final Discovery Verdict

**PASS(Discovery 自评)。**

- 调查完整覆盖 Gate §5 A-E 五条链路 + §9 全部分歧窗口 + §13 六组崩溃实验(真实持久化路径);
- 核心产出:恢复语义最小集(source 级 RESTART + 既有对账 + 两个盲区的针对性修正 + sync_log 分流收尾),明确否定 item 级 resume;
- 关键新发现:F16(GitHub SHA 短路恢复盲区,现状即存在且不可检测)、W6(web_crawl 删除意图丢失窗口)、E1 假阴性(现行 fail_stale_running 不查实际结果);
- 工程源码保持 `2933118` 零改动;实验环境已全部清理(DB DROP/class 删除/进程零残留)。

**NEXT:Planner 基于本报告冻结 Stage⑩ Implementation Contract。**
