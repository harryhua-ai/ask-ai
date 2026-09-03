# Issue #18 非阻塞数据源删除 — Executor #3 实现报告

- 日期:2026-09-03
- 仓库:harryhua-ai/ask-ai
- Execution Mode:PARALLEL — Executor #3
- STATUS:**CANDIDATE READY(待 Planner 验收)**
- AUTHORITATIVE_BASELINE:`ce52af421cd201fa64daf01c3f0e6fd32ac48a70`
- FINAL_COMMIT:`8eb1e9d`(单一实现提交,报告隔离于 docs 仓)
- BRANCH:`worktree-exec/issue18-async-delete-20260903`(已推 origin)
- WORKTREE:`/Users/harryhua/Documents/GitHub/ask-ai/.worktrees/issue18-async-delete`

---

## 1. 交付摘要

把 Admin 数据源删除从**阻塞式**(DELETE 请求内等待完整 Weaviate purge,大语料下
Admin 长时间挂起、进程重启即状态丢失)升级为 **durable asynchronous deletion**:

```
ACTIVE ──DELETE 202──▶ DELETE_REQUESTED ──worker CAS 认领──▶ DELETING
                              │                              │
                     (重启 sweep 重驱)                 成功 │    │ 失败
                                                            ▼    ▼
                                              (整行删除,无 tombstone)  DELETE_FAILED ──retry──▶ DELETING
```

核心不变量(冻结契约逐条落点):

| 冻结契约 | 实现 |
|---|---|
| 1. Admin 不等 purge | `DELETE /{id}` 只做行锁校验+碰撞检查+持久 `DELETE_REQUESTED`,**202 立即返回**,请求内 purge 零调用(测试断言 `fake_purge == []`) |
| 2. 持久 lifecycle,刷新可恢复 | 状态写在 `data_sources` 行(S0 三列:`lifecycle_state/since/error`),`DataSourceOut` 透出三字段,列表端点即恢复 |
| 3. DELETING 禁 sync / 禁 pending / 其他功能可用 | 手动 sync 端点 `is_sync_eligible` deny-by-default 409;`sync-all` 过滤非 eligible;`scripts/sync.py::_load_configs_from_db` WHERE 接线 `sync_eligible_condition()`(执行面第二防线);其余 Admin 端点零触碰 |
| 4. DELETE_FAILED 明确显示+安全 retry | 失败落 `DELETE_FAILED`+`lifecycle_error`(截断 2000 字符);UI 红徽章+错误明细+「重试删除」按钮;`POST /{id}/delete/retry`(仅 DELETE_FAILED)+ DELETE 重发双通道,同一受理管道 |
| 5. 成功删行,无 tombstone | purge 收敛后**同一事务**删 DataSource+Document 账本行 |
| 6. 无「DB 删了但 purge 未知」半态 | 顺序 = 先 purge(残留验证段必须为 0)后删行;purge 任何异常 → 行保留 DELETE_FAILED;测试用同步 engine 在 purge 内读行证明「purge 时行仍在」 |
| 7. S0 deny-by-default | 复用 `source_lifecycle.is_sync_eligible`/`sync_eligible_condition()`,零词汇表改动;未知状态实测 409/被过滤 |
| 8. 保留安全/一致性检查 | purge 函数**原样迁移**(账本确定性 UUID 点删+孤儿边界兜底+残留验证;G2/P0-A 禁令:删侧只点名对象 UUID),逻辑零改动,静态禁令测试原样通过 |

## 2. 关键文件

- `backend/services/source_deletion.py`(新增):受理管道 `request_deletion`(行锁+碰撞+持久转移)、执行管道 `_claim_and_delete_one`(CAS 认领→线程池 purge→同事务删行)、`_mark_delete_failed`、`process_pending_deletions`(sweep,即重启恢复入口)、`SourceDeletionWorker`(事件唤醒+30s 周期 sweep,`_active` 防同进程重入)、`purge_source_corpus_sync`(自 data_sources.py 原样迁移)。
- `backend/api/admin/data_sources.py`:DELETE 重写为 202 受理;新增 retry 端点;sync/sync-all lifecycle 拒绝;`_to_out`/schemas 透出 lifecycle 三字段。
- `backend/main.py`:lifespan 启动 worker(启动即 sweep = 崩溃恢复),关闭先于 weaviate/engine 释放。
- `scripts/sync.py`:`_load_configs_from_db` 增加 `sync_eligible_condition()`(S0 docstring 预留的 #18 接线点)。
- Admin 前端:`types/api.ts`(lifecycle 字段+`isDeletionInFlight`/`isSyncEligible` 谓词)、`useDataSources.ts`(retry hook;delete 返回 202 body)、`DataSources.tsx`(三态徽章+错误明细、删除流程禁同步/编辑/重复删除、失败行「重试删除」、删除在途自动 5s 轮询)。

## 3. DELETE_LIFECYCLE(状态机与持久化)

- `ACTIVE`(NULL)→ `DELETE_REQUESTED`:行锁(`SELECT … FOR UPDATE`)下校验,`accepted=True` 202;commit 即持久,进程随即崩溃也不丢受理。
- `DELETE_REQUESTED` → `DELETING`:worker CAS(`UPDATE … WHERE lifecycle_state IN in_flight`,rowcount=1 胜出),跨进程重复认领由 CAS 裁决。
- `DELETING` → 成功:线程池 purge → 同事务删配置行+账本行(无 tombstone)。
- `DELETING` → `DELETE_FAILED`:CAS WHERE state=DELETING 落 `lifecycle_error`。
- retry:`DELETE_FAILED` → `DELETE_REQUESTED`(清 error),retry 端点仅接受该状态,否则 409。
- 重复 DELETE:在途态幂等返回 `accepted=false` 202,不重复执行。

## 4. RACE_HANDLING(冻结竞态逐条)

| 竞态 | 处理 | 测试 |
|---|---|---|
| active sync vs delete | 该源 `SyncRun(status=running)` → 409 | `test_delete_blocked_by_running_sync_run` |
| pending sync vs delete | 该源 `SyncRequest(pending/running)` → 409;**sync-all NULL 批量在途同样 409**(保守:执行面可能已按受理前快照装载批量配置) | `test_delete_blocked_by_pending_sync_request` / `…running…` / `…_sync_all_batch` |
| 碰撞解除后 | 请求终态即可正常删除(瞬时阻断,非永久锁) | `test_sync_allowed_again_after_collision_cleared` |
| repeated delete click | 行锁串行化+在途幂等 202;最终只执行一次 purge | `test_repeated_delete_click_is_idempotent` |
| process restart during deletion | 见 §5 恢复 | `test_orphan_deleting_row_recovered_by_sweep` |
| purge partial failure | 残留>0 → RuntimeError → DELETE_FAILED,行/账本保留 | `test_delete_failure_marks_failed_and_retry_succeeds`、半态防护测试 |
| retry after failure | retry 端点/DELETE 重发 → 清错误重新入队,purge 幂等 | 同上 + `test_delete_retry_endpoint_only_from_failed` |
| 源间隔离 | 全部操作按 source_id 前缀边界;A 在途不阻塞 B 的 sync/删除 | `test_delete_keeps_unrelated_source`、`test_unrelated_source_unaffected_during_deletion` |
| delete→sync 复活竞态 | 手动端点 409 + sync.py WHERE + sync-all 过滤三层 deny-by-default(含未知状态) | `test_sync_denied_by_lifecycle[4态]`、`test_sync_config_universe_excludes_non_eligible` |

## 5. RECOVERY_BEHAVIOR(重启/崩溃恢复)

- worker 首轮 sweep 扫描**全部在途行**(`DELETE_REQUESTED` 已受理未启动 + `DELETING` 执行中崩溃孤儿),逐个 CAS 认领后重驱;purge 幂等(UUID 点删+孤儿兜底+残留验证),重复执行安全收敛。
- 受理先于执行持久化:202 返回后进程立即崩溃,重启后 sweep 照常完成删除。
- 30s 周期 sweep 兜底事件唤醒丢失;worker 循环内异常捕获不终结(下轮重试)。
- 运行拓扑假设:V1 单 backend 容器单 worker;跨进程并发时 CAS 保证认领唯一,孤儿 DELETING 双执行者亦收敛(幂等 purge+验证段不假报成功)——已在模块 docstring 声明。

## 6. TESTS(实证)

环境:一次性隔离库 `ask_ai_test_e18`(用后已 DROP,不碰共享 ask_ai_test);`HF_HUB_OFFLINE=1`;worktree 自有 models 物理克隆(APFS `cp -Rc`,非软链;6.4G 秒级)+ offline load verify(tokenizer/config 本地加载 OK)。

- 新增 `tests/api/admin/test_data_source_deletion_lifecycle.py`:碰撞×5、deny-by-default(4 态参数化+sync-all+配置宇宙)、孤儿恢复、半态防护(purge 内同步 engine 读行)、源间隔离、worker smoke。
- 重写 `tests/api/admin/test_data_source_delete.py`:非阻塞受理断言(purge 零调用/202/持久状态)、全生命周期完成、失败→retry、幂等、列表透出 lifecycle、purge 边界安全(G2 原样)。
- 适配:`test_data_source_delete_wildcards.py`(202+sweep 驱动;**补 fixture 清理卫生**:幸存 B 源行泄漏到同会话后续模块是基线既有隔离缺陷,借本任务修复)、`test_unified_v1_admin_gate.py` G008、`test_data_source_delete_document_local.py`(指向迁移后 purge 模块)。
- **定向批次:51 passed / 0 failed**。
- **全量:1233 passed / 5 skipped / 0 failed(40.12s)**;基线(ce52af4,S0 集成门)= 1213/0,净增 20 测试零回归。
- S0 既有 `tests/services/test_source_lifecycle.py` 18/18 原样通过(词汇表/谓词零改动)。

## 7. BUILD / STATIC

- admin build:`tsc -b && vite build` **PASS**(worktree node_modules 为物理克隆,非软链)。
- ruff(全部改动 py 文件):**All checks passed**(7 项可自动修复项已 --fix,含从基线测试拷贝来的 3 项历史噪音)。
- `git diff --check`:**PASS**(无空白错误)。

## 8. KNOWN_LIMITATIONS(诚实边界)

1. **NULL 批量碰撞为保守语义**:任一 sync-all 批量 pending/running 期间,任何源的删除都 409。这是"安全阻止"的字面执行(执行面可能按受理前快照装载批量);代价是执行面停摆期间删除被暂时挡住。若 Planner 认为过宽,可改为"仅 source-specific 请求+running run 阻断+batch 循环内逐源复查 eligibility",需要动 sync.py 主循环,本任务未纳入(最小变更)。
2. `lifecycle_since`/`lifecycle_error` 尚无 Admin 独立审计视图,仅徽章 tooltip+错误行呈现(可观测性深链属 W3/后续)。
3. PATCH/上传端点在 DELETING 态未显式禁止(契约仅要求禁 sync/新 pending;行终将被删除,配置改动无复活通道),未做额外闸门。
4. 孤儿 `SyncRun(running)` 行(执行面崩溃遗留且未跑对账)会阻断该源删除直至执行面重启盖章——阶段⑩恢复语义既定行为,未在本任务改变。
5. `DELETING` 超时无 watchdog:worker 单轮 purge 失败即落 DELETE_FAILED;不存在"purge 卡死 N 分钟自动判失败"的定时器(purge 在线程池,卡死属 weaviate 客户端超时范畴)。

## 9. 边界遵守声明

- 未实现 #16/#17;未改 corpus semantics;未跑 production purge;未做任何生产数据变更;未用 shell/background hack(全部状态在 DB 行上,worker 是进程内 asyncio 任务+持久 lifecycle);未移除任何一致性验证(验证段原样)。
- `.env`/models/node_modules 物理复制(禁软链/禁下载),均不入库;模型 offline load verify 在测试前完成。
- 隔离测试库用后已 DROP;共享 ask_ai_test 全程零触碰。

## 10. PRODUCTION_MUTATIONS

**NONE**(零生产触碰;所有验证在本地隔离环境)。
