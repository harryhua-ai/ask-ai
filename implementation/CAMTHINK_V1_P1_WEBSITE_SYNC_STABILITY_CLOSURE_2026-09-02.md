# CAMTHINK_V1_P1_WEBSITE_SYNC_STABILITY_CLOSURE_2026-09-02

- Gate: P1 — Website Sync 生命周期稳定性闭环(ghost/retirement/no-op)
- 执行窗口: 2026-09-02(本地;**PRODUCTION_ACCESS = NO / PRODUCTION_MUTATION = NO**)
- 工作树: `.worktrees/technical-insights`,branch `release/camthink-v1-rc-2026-09-01`,baseline `81312df`(P0-B2 tip),worktree clean,无冲突工作
- 结论: **PASS**(根因自源码实证;生命周期语义落地;G001–G010 全覆盖;相关回归 501 passed / 3 skipped)

---

## 1. Baseline / Repository State

- `git status` clean;`git branch --show-current` = `release/camthink-v1-rc-2026-09-01`;HEAD = `81312dfdcc2de311cefc19ae2946ff8419bf7e3d`(含 P0-A fix `7c535d3` 与 P0-B2 报告)。
- 生产现态(仅作为输入事实,本 Gate 未访问):sha-3bf945b 已部署;web_crawl 371 = 账本 361 + 10 ghost;SYNC_RUNTIME_STATUS = PARTIAL。

## 2. Root Cause(自当前源码实证,AC-01)

**永久 PARTIAL 循环的机制链**(`backend/services/vector_consistency.py` + `scripts/sync.py::_handle_no_change`):

1. `verify_source_vectors` 的 `is_healthy` 要求 `orphan_count == 0`;10 个 ghost(存量文档无账本行)使 report 永不健康;
2. 47 篇 refill(P0-B2 恢复)收敛后 `refill_source_ids = []` → 进入 `_handle_no_change` 的 **else 分支:「refill 为空 = 账本漂移 → fetch_all() + ingest_all(全源)」** —— 即每轮对全站**重新抓取并重新 embedding**;
3. 全量重灌对 ghost **无收敛作用**(ghost 不在 fetch_all 的当前文档集中,确定性 UUID 覆盖不触碰它们)→ 复验仍 371/361 → 永远 partial → 窗口永不推进 → 下轮重复;
4. 根因定性:**系统缺少「退休(RETIREMENT)」生命周期** —— 没有任何代码路径能把「源已不存在此文档」表达出来,也没有 ghost 分类;一致性校验只会在「全量重灌」与「警告保留」之间二选一,于是 honest-keep 数据变成了永久的收敛失败信号;
5. 另:web_crawl 爬取每次内容/抽取波动会让 `run_stats` coverage 变化,若发现本身不完整,旧分支还会把「爬取失败」误当「需全量重灌」——双重不稳。

## 3. Lifecycle Semantics(实现,冻结语义逐条落地)

**`vector_consistency.py`**:`VectorGapReport` 新增 `orphan_chunks: dict[str, set[int]]`(孤儿 source_id → 实际存量 chunk_index 集合,来自迭代器全扫的精确事实)。只读,不删。

**`scripts/sync.py`**:
- `_discover_source_docs(connector) -> (docs, complete)`:fetch_all 成功 + (web_crawl 合同)coverage ≥ 80% 才算**完整发现**;任何异常/不完整 → `complete=False`。
- `_reconcile_orphan_vectors(source_id, connector, pipeline, report) -> (retired, repaired, unresolved)`:逐孤儿分类(**零 embedding**):
  - 按孤儿自己的确定性 UUID(`uuid5(source_id#i)`,来自扫描事实)`by_id.contains_any` 精确读回对象(不使用任何 TEXT 过滤);读回数与扫描不符 → 保留;
  - **EXTRA_CONFIRMED_RETIRED**(完整发现中源已无此文档)→ 仅删除该文档自己的存量 UUID(结构上不可能触及兄弟);
  - **源仍在(账本行丢失)** → 用存量对象属性(content_hash/source_type/…)**零 embedding 重建账本行**(chunk_count=max+1;若与实际 index 集不合,后续一致性校验会再以 targeted refill 定向修复——诚实且最小);
  - **发现失败/不完整/属性缺失** → `EXTRA_UNRESOLVED_ORPHAN`:KEEP DATA + REPORT。
- `_handle_no_change` 重构:refill(仅缺口文档,embed)与 orphan reconciliation 互相独立;**移除「refill 空即全量重灌自愈」分支**;处置后**复验**(`verify` 第二次):收敛 → `success`(窗口推进,稳态达成);未收敛 → `partial` + 三分类计数(MISSING_LEGITIMATE / EXTRA_CONFIRMED_RETIRED / EXTRA_UNRESOLVED_ORPHAN / 账本重建数)写入 error_detail。`items_deleted`=退休篇数、`items_new`=账本重建篇数。

**稳态**(合同 §5):源不变 → 账本一致 → 向量一致 → 无 refill、无重灌、无 embedding → success/no-op;仅当存在真实缺失/变更文档时才产生 embed 工作;ghost 只产生廉价 discovery(爬取,无 embed)。

## 4. Tests(G001–G010)与精确结果

新套件 `tests/pipeline/test_sync_lifecycle.py`(11 例,含 1 例真实 Weaviate 1.28 集成):

| 契约 | 用例 | 结果 |
|---|---|---|
| G001 稳定 no-op | `test_g001_healthy_source_is_stable_noop`(success、零 fetch_all/ingest/delete) | PASS |
| G002 变更文档只动自己 | `test_g002_changed_doc_refill_touches_only_that_doc` | PASS |
| G003 源确认退休精确删除 | `test_g003_confirmed_retirement_deletes_exact_uuids_only` | PASS |
| G004 发现失败/覆盖不足不退休 | `test_g004a_*` / `test_g004b_partial_crawl_coverage_cannot_retire` | PASS |
| G005 历史 ghost 分类处置 | `test_g005_ledger_lost_active_doc_repaired_without_embedding`(源仍在→账本重建,不删) | PASS |
| G006 ghost 不触发全量重灌 | `test_g006_ghosts_alone_never_trigger_full_refill`(ingest_all 未调用) | PASS |
| G007 真实缺失仍修复 | `test_g007_missing_legitimate_chunk_still_repaired` | PASS |
| G008 混合态三分类独立处置 | `test_g008_mixed_state_classes_handled_independently` | PASS |
| G009 幂等 | `test_g009_repeated_healthy_sync_idempotent` | PASS |
| 集成(真实 Weaviate) | `test_integration_ghost_retired_exactly_on_real_weaviate`(ghost 精确消失,合法对象原样) | PASS |
| 校验器明细 | `test_sync_lifecycle` 内隐式 + 既有 vector_consistency 套件回归 | PASS |

`tests/scripts/test_sync_coverage.py`:`test_no_change_orphan_only_drift_self_heals_via_full_reingest` **重写**为 `test_no_change_orphan_only_drift_reconciles_without_full_reingest`(76 ghost → 零 embed、精确退休 76、复验收敛 success)。旧断言(全量重灌+永久 partial)即本 Gate 根因,按合同 §12 负清单废弃;「修因而非告警」精神保留并强化。

## 5. 回归与验证(AC-12;真实执行记录)

| 命令 | 结果 |
|---|---|
| `pytest tests/pipeline tests/scripts tests/services tests/db` | **353 passed, 3 skipped**(RED→GREEN:新套件先 10 failed/1 skipped 后全绿) |
| `pytest tests/connectors tests/retrieval tests/utils tests/auth` | **173 passed**(G010 跨源:fs/github/woo 语义零变化) |
| black(scripts/sync.py、vector_consistency.py、2 个测试文件) | 通过(已格式化) |
| 合计相关回归 | **501 passed / 3 skipped,0 failed** |
| tests/embedder | 环境受限(本地 HF 模型加载超时),与本改动无关(未触碰 embedder) |

## 6. AC-01..AC-13

| AC | 结果 | 证据 |
|---|---|---|
| AC-01 根因自源码 | PASS | §2(else 分支全量重灌 + is_healthy orphan==0) |
| AC-02 无 token/宽泛删除 | PASS | 删除仅 `by_id contains_any(自己 uuid)`;仓库中已无 source_id 过滤删除路径 |
| AC-03 PRUNE DOCUMENT-LOCAL | PASS | P0-A 机制未动;retirement 同构(uuid 点删) |
| AC-04 SOURCE-CONFIRMED(修订) | PASS | 退休证据=权威成员集 `authoritative_source_ids`,非抽取集合(§10);完整发现门保留 |
| AC-05 部分发现/瞬时失败不退休(修订) | PASS | G004a/G004b + 新增 G004-C/D(任意聚合覆盖率下单页瞬时失败不退休) |
| AC-06 ghost 不触发全量 refill | PASS | G006 + 覆盖率守卫 |
| AC-07 真实缺失仍检出修复 | PASS | G007(refill 路径原样保留) |
| AC-08 健康源稳定 success/no-op | PASS | G001/G003/G006/G008(处置后复验收敛 → success,窗口推进) |
| AC-09 幂等 | PASS | G009 |
| AC-10 无跨源回归 | PASS | G010 套件 173 passed |
| AC-11 零生产访问 | PASS | 全程本地(一次性 Weaviate 容器已销毁) |
| AC-12 测试全过 | PASS | 501/3 skipped |
| AC-13 三分类诊断 | PASS | error_detail 输出 MISSING_LEGITIMATE / EXTRA_CONFIRMED_RETIRED / EXTRA_UNRESOLVED_ORPHAN + 账本重建数;logger 逐篇分类行 |

## 7. Changed Files

- `backend/services/vector_consistency.py`(+`orphan_chunks` 明细);
- `scripts/sync.py`(`_discover_source_docs`、`_reconcile_orphan_vectors` 新增;`_handle_no_change` 重构:移除全量重灌自愈,加入处置后复验与三分类诊断);
- `tests/pipeline/test_sync_lifecycle.py`(新,11 例);
- `tests/scripts/test_sync_coverage.py`(1 例重写到新契约,历史注记保留)。

## 8. Unresolved Risks

1. 10 个真实 ghost 的**具体退休裁决**在生产执行(见 §9):语义上它们将被自动精确退休;执行后 web_crawl 应回到 361、下一轮 success/no-op;
2. 账本重建行使用存量 `chunk_count=max+1`,若存量 index 不连续,会进入下一轮 targeted refill(embed 单篇)——诚实代价,量级极小;
3. `fetch_objects(by_id)` 与 `delete_many(by_id)` 均为精确 UUID 语义,若未来 Weaviate 变更 by_id 行为,守卫测试会暴露;
4. GPU 容量本身(PA-0F P1)不在本 Gate 范围:本 Gate 已把「ghost 存在」从 GPU 触发因素中剔除,但真实新内容仍需 embed 通道决策。

## 9. Production Follow-up Decision

- **PRODUCTION_RECONCILIATION_REQUIRED = YES**:
  需一个部署+验证 Gate:① 将本修复构建/发布为候选镜像(P0-B1 同款 CI 路径)并按 P0-B2 模式部署 backend+sync-cron;② 观察下一轮 cron:website-camthink 应 `EXTRA_CONFIRMED_RETIRED=10` → 复验 361/361 → **success**(窗口推进);③ 抽样验证 10 ghost 对象消失、361 合法块原样;④ 冒烟一条检索。
- **EXPECTED_REAL_GHOST_OUTCOME = AUTO_SAFE_RETIREMENT**
  (10 ghost 均为旧 URL 文档:完整 sitemap 发现中确认不存在 → 语义自动精确退休;无需人工逐条裁决。)
- **GPU_SYNC_RUNTIME_POLICY_STATUS = PARTIALLY_RESOLVED**:
  「ghost 触发无谓全量重灌/embed」这一成因已消除(稳态零 embed);但真实新内容仍需 GPU/CPU embed 通道的容量决策(PA-0F P1 独立残留),故不算 RESOLVED。

---

## 10. Planner FINAL REVIEW Correction:Retirement Safety(2026-09-02 追加)

**Planner 对 `7599e8a` 的 FINAL REVIEW = PARTIAL**,发现一个安全缺陷(已确认成立并修正):

### 10.1 缺陷(Planner 发现,本次实现自证)

旧 `_discover_source_docs` 以「抽取覆盖率 ≥80%」判定发现完整,而
`_reconcile_orphan_vectors` 以「不在 fetch_all 产出的 source_id 集合」为退休证据。
`WebCrawlConnector.fetch_all()` 的 `accepted` **先于单页抓取记账**:一个仍在
sitemap/权威源中的页面可能因 HTTP 失败/超时/抽取失败/薄内容被拒而产不出
RawDocument;只要整体覆盖 ≥80%,该页即被误判「源确认退休」→ 精确但**错误**的删除
(例:100 accepted / 90 extracted,失败的 10 页中含现存文档 A → A 被误删)。
精确 UUID 范围不改变「删除对象本身不该删」的性质。

### 10.2 修正(最小实现,基于真实 connector 架构)

**权威源成员资格 ≠ 抽取成功**:
- `WebCrawlConnector`:新增 `_accepted_urls` 记账(robots 通过即记,先于抓取)+
  `authoritative_source_ids()`(全量轮返回 accepted URL 的 source_id 集合 ——
  与 `fetch_deleted` 同一 URL→source_id 推导;增量轮返回 None);
- `_discover_source_docs` → 返回 `(docs, complete, membership)`;coverage<80% 的
  完整性门保持不变(不完整 → 一律不退休);
- `_reconcile_orphan_vectors` 退休判定改用**成员集**:
  - 孤儿 ∈ 成员集:仍在权威源 → **绝不退休**;若本轮抽取成功 → 账本重建分支
    (原样);若仅成员(临时失败,G004-C/D)→ `EXTRA_UNRESOLVED_ORPHAN` 保留;
  - 孤儿 ∉ 成员集且 complete → `EXTRA_CONFIRMED_RETIRED`(proven absent from
    the successfully enumerated authoritative source set);
  - 无该原语的连接器(git/fs/woo:抽取即枚举)回退抽取集合,语义不变。

### 10.3 新增负测试(RED→GREEN)

| 用例 | 场景 | 断言 |
|---|---|---|
| `test_g004c_member_page_fetch_failure_never_retires` | A 在成员集,页面抓取失败,覆盖 90% | A 不被删除,partial + UNRESOLVED |
| `test_g004d_member_page_low_content_rejection_never_retires` | A 被薄内容拒绝,覆盖 90% | 同上 |
| `test_g004e_incomplete_enumeration_never_retires_even_with_membership` | 枚举覆盖率 50% | 任何缺席文档不退休 |
| `test_g003b_membership_confirmed_absence_still_retires_exactly` | 成员集确认缺席 | 仍按精确 UUID 退休 |
| `test_authoritative_source_ids_include_failed_and_rejected_pages`(connector 级) | 失败/被拒页 ∈ 成员集 | 原语语义锁定 |
| `test_authoritative_source_ids_none_on_incremental_round`(connector 级) | 增量轮 | 返回 None |

RED 实证:G004-C/D 在修正前代码上失败(delete_many 被调用 = 误删路径真实存在)。

### 10.4 修订验收证据

- **AC-04(修订)= PASS**:退休证据 = `authoritative_source_ids()` 权威成员集
  (枚举成员),非抽取成功集合;G003/G003b 正向 + G004-C/D 反向。
- **AC-05(修订)= PASS**:G004-C/D 证明单页瞬时失败在任意聚合覆盖率(90%)
  下均不触发退休;G004-E + 既有 G004a/G004b 覆盖枚举失败/低覆盖。

### 10.5 修正后回归(真实执行)

| 命令 | 结果 |
|---|---|
| `pytest tests/pipeline/test_sync_lifecycle.py tests/scripts/test_sync_coverage.py tests/services/test_vector_consistency.py` | 27 passed |
| `pytest tests/connectors/test_web_crawl.py` | 18 passed(含 2 例新原语测试) |
| `pytest tests/pipeline tests/scripts tests/services tests/db tests/connectors tests/retrieval tests/utils tests/auth` | **532 passed / 3 skipped** |
| black(sync.py / web_crawl.py / vector_consistency.py / 2 测试文件) | 通过 |

修正涉及文件:`backend/connectors/web_crawl.py`、`scripts/sync.py`、
`tests/pipeline/test_sync_lifecycle.py`、`tests/connectors/test_web_crawl.py`。
CORRECTION_COMMIT 见交付。

**FINAL STATUS = PASS(含 Planner 修正)**
