# CAMTHINK_V1_P0A_WEBSITE_CORPUS_INTEGRITY_ROOT_CAUSE_SAFE_FIX_2026-09-02

- Gate: P0-A — web_crawl 语料完整性根因定位 + 最小安全修复
- 执行窗口: 2026-09-02(本地;**PRODUCTION_ACCESS = NO**,全程零生产访问)
- 分支/工作树: `release/camthink-v1-rc-2026-09-01` @ `.worktrees/technical-insights`
- 结论: **PASS**(根因实证复现;修复最小化;18 例新回归 + 250 例 pipeline + 8 例 db + 251 例相邻套件全绿)

---

## 1. P0A-G001 Exact Root Cause(实证,非假设)

**PA-0F 的猜想正确,且已升级为可复现的实证根因。**

`Filter.by_property("source_id").equal(A)` 在 Weaviate(TEXT 属性)上是**分词语义**而非字符串全等:查询 `site/blog` 被 token 化为 `{site, blog}`,凡 source_id **包含这些 token** 的对象全部命中 —— 包括 `site/blog/ai-species`、`site/blog/5-things` 等兄弟/子路径文档。

因此旧 `_prune_stale_chunks(source_id, N)`(`equal(source_id) & chunk_index >= N`)在**文档收缩**(新 chunk 数 < 旧 chunk 数)时,会把「token 包含本文档 token 的所有兄弟文档」的 `chunk_index >= N` 对象一并删除。

**本地实证**(一次性容器 `p0a-weaviate`,Weaviate 1.28.0 + 仓库锁定 client 4.22.0 + 仓库真实代码,种子 = 确定性 UUID 方案 `uuid5(NAMESPACE_URL, f"{source_id}#{i}")`):

```
seed: site/blog×4, site/blog/ai-species×4, site/blog/5-things×3, site/index×2
fetch_objects(equal("site/blog"))  →  命中 11 个对象,横跨 3 个文档
pipe._prune_stale_chunks("site/blog", 1)   # 仓库真实方法
survivors:
  site/blog:            [0]          (预期)
  site/blog/ai-species: [0]          ← 4 → 1,与生产症状逐字一致
  site/blog/5-things:   [0]          ← 3 → 1
  site/index:           [0, 1]       (不含 blog token → 幸免)
```

**触发时序解释**(与生产时间线完全吻合):原始 C8 全量爬取时各文档均为新建,收缩条件不成立 → 无破坏;只有当**重抽取使文档收缩**(2026-09-02T01:23 管理端人工同步对全站重灌,listing 页 `website-camthink/blog` 新抽取仅 1 chunk,而兄弟文档存量 3-4 chunks)时,listing 的 prune 才连带删光兄弟 chunks。

**逐项排除(contract 要求的区分)**:
1. *合法 chunk 减少(重抽取/内容变化)*:存在但极小 —— 账本证据:01:23 重灌后 touched 110 篇合计 **348 chunks** = 新抽取的成功写入数(`_upsert_postgres` 写 `success_count`),即新抽取本身产出 ~348 chunks,与旧 359 仅差 −11(合理内容漂移);
2. *应删的 stale chunks*:收缩文档自身的 #N..#old-1 是合法删除目标(新实现仍删,但只删这些);
3. *跨文档删除*:实证如上,是主体(185 chunks 被误删);
4. *PG↔Weaviate 记账缺陷*:记账本身正确(账本 348 = 写入成功数);背离(361 vs 163)是删除缺陷的**结果**而非原因;
5. *确定性 UUID 交互*:uuid5 全等字符串映射,与事故无关,反而是修复的基础;
6. *TEXT 分词语义*:是,核心机制(本地 fetch_objects 实证 11/11 命中跨文档)。

## 2. P0A-G002 Old Failure Mode Regression(旧破坏行为回归)

两个层面固化:
- `test_old_prune_filter_destructive_repro_real_weaviate`:用**旧过滤表达式**在真实 Weaviate 上重演事故(收缩文档 prune → 兄弟仅剩 chunk 0),断言事故症状可复现;
- `test_weaviate_text_equal_is_tokenized_semantics_guard`:固化「TEXT equal 分词过匹配」平台语义 —— 将来 client/server 升级若改变该语义,守卫测试会揭示,防止隐式假设漂移。

## 3. P0A-G003..G006 修复设计:PRUNE IS DOCUMENT-LOCAL

**实现**(`backend/pipeline/ingest.py`,最小变更):
- `_prune_stale_chunks(source_id, current_count, previous_count)`:删除对象集 = `{uuid5(NAMESPACE_URL, f"{source_id}#{i}") | i ∈ [current_count, previous_count)}`,经 `Filter.by_id().contains_any(...)` 按 **UUID 点删**(500/批);**不出现任何 TEXT 属性过滤**。uuid5 是全等字符串的确定性映射,`A ≠ B ⇒ uuid5(A#i) ≠ uuid5(B#j)`,文档局部性是**结构性保证**(「A 前缀/A 后缀/相似路径/同 token/同产品/同源类型」一律不可达)。
- `previous_count` = 写前读账本 `MAX(chunk_count)`(`_get_stored_chunk_count`,新函数);**None(无账本/读数失败)→ fail-safe 不删**,残留交由一致性校验披露(绝不猜测删除范围)。读取必须在 `_upsert_postgres` 覆盖账本**之前**(两条写路径均已调整)。
- `delete_document`(增量同步删文件路径,同一缺陷面):同样改为 uuid 点删 `uuid5(source_id, 0..stored_count-1)`;账本无行 → fail-safe 跳过 Weaviate 删除并告警。

**不变量证明**:删除谓词只依赖本文档自己的 `(source_id, index)` 对;任何其他文档 B 的对象 uuid = `uuid5(B#j)`,与 A 的列表无交(哈希碰撞概率可忽略),故「删 A 永不触 B」。

## 4. 回归覆盖(P0A-G002..G008 对应)

新套件 `tests/pipeline/test_ingest_prune_document_local.py`(18 例) + 重写 `tests/pipeline/test_ingest.py` 中 3 例固化旧行为的用例:

| 契约要求 | 用例 |
|---|---|
| 1 精确收缩 prune | `test_prune_uses_only_own_deterministic_uuids`、`..._shrink_prunes_only_own_stale_chunks` |
| 2/3/4 兄弟/同 token/路径型 | `test_prune_uuid_list_is_document_local_by_construction`(5 类兄弟全枚举)、真实 Weaviate `test_prune_document_local_real_weaviate` |
| 5 收缩 N→M | 单元 + 真实 Weaviate 端到端 `test_full_ingest_shrink_real_weaviate` |
| 6 增长 M→N | `test_ingest_document_grow_updates_ledger_without_prune` |
| 7 幂等重灌 | `test_repeated_identical_ingest_is_idempotent_no_prune` |
| 8 prune A 不触 B(含 uuid/属性/向量) | 真实 Weaviate 局部性用例(survivors 全表断言) |
| 9 账本↔实际一致 | shrink/grow/idempotent 用例内断言 ledger==surviving |
| 10 部分失败不 prune | `test_batch_partial_failure_no_prune`、`test_ingest_document_skips_prune_when_partial_failure`(旧有,保留) |
| fail-safe | `test_prune_unknown_previous_count_is_fail_safe_noop`、`test_delete_document_without_ledger_is_fail_safe` 等 |

## 5. 测试与结果(P0A-G009)

| 套件 | 结果 |
|---|---|
| 新回归套件(RED→GREEN) | RED:15 failed / 3 passed(by-design)→ **GREEN:18/18** |
| tests/pipeline(含重写 3 例) | **250/250** |
| tests/db | 8/8 |
| tests/connectors + services + scripts + retrieval + utils | 251 passed / 3 skipped |
| black | 3 文件格式通过 |
| tests/embedder | 环境受限(本地真实 HF 模型加载超时;与本修复无关,代码零涉及 embedder) |

合计相关回归 **509+ passed,0 failed**。

## 6. Production Corpus Interpretation(359→163 归因,纯仓库逻辑,零生产访问)

- **新抽取本身健康**:PA-0F 账本证据(touched 110 篇/348 chunks = `_upsert_postgres` 写入的成功写入数)表明 01:23 重抽取共产出 ~348 chunks ≈ 旧 359(−11 合理漂移);
- **因此 359→163 不能由合法重抽取解释**:合法重抽取应留下 ~348,实际只剩 163,~185 chunks 在写入成功后**被删除**;
- 逐篇实锤(PA-0F):`ai-species` 账本 4 + 日志 4/4 成功 vs 存量 1;
- 精确逐对象法证(196 个对象的删除清单/顺序)需要生产 Weaviate 检查:**NOT_VERIFIED_REQUIRES_PRODUCTION_RECOVERY_GATE**(本 Gate 已给出机制级定论,法证级归因留待恢复 Gate)。

## 7. P0A-G001..G010

| 验收 | 结果 |
|---|---|
| G001 根因实证 | PASS(§1,真实代码+锁定版本+同 server 版本复现) |
| G002 旧失败模式回归 | PASS(§2 两层守卫) |
| G003 DOCUMENT-LOCAL 不变量 | PASS(结构性保证 + 结构断言 + 真实 Weaviate 断言) |
| G004 收缩只删自身 stale | PASS |
| G005 兄弟/路径/token 兄弟不受影响 | PASS |
| G006 幂等重灌 | PASS |
| G007 账本↔实际一致 | PASS |
| G008 部分失败不破坏性 prune | PASS |
| G009 既有回归套件 | PASS(pipeline 250 + db 8 + 相邻 251) |
| G010 零生产访问 | PASS(全程本地一次性容器 `p0a-weaviate`,报告后销毁) |

## 8. Changed Files / FINAL_COMMIT

- `backend/pipeline/ingest.py`:`_get_stored_chunk_count`(新)、`_prune_stale_chunks` 重写(uuid 点删 + fail-safe)、`ingest_document`/`_ingest_doc_batch` 读账本时机前移、`delete_document` 重写;
- `tests/pipeline/test_ingest_prune_document_local.py`(新,18 例);
- `tests/pipeline/test_ingest.py`(3 例重写到新契约)。

FIX COMMIT: `7c535d3`(分支 `release/camthink-v1-rc-2026-09-01`);REPORT_COMMIT 见交付。

## 9. Residual Risks / Production Recovery 可行性

**残留风险**:
1. 账本行丢失的文档(幽灵)其存量 chunk 不再被 prune(旧实现「能删但会误删」)→ 由一致性校验以 orphan/mismatch 显式披露,人工/自愈路径处理 —— 安全换取覆盖,已在代码 docstring 冻结;
2. 生产仍运行未修复镜像(RC `sha-1ed84bb`):在部署修复镜像前,**任何对 website-camthink 的再次重灌都可能重复收缩删除**;cron 侧 GPU OOM(PA-0F P1)独立存在,不在本 Gate 范围;
3. `uuid5` 全等映射是文档局部性的根基,若未来改 chunk 身份方案必须同步改 prune 并重跑本套件。

**PRODUCTION_RECOVERY_READY = YES(条件)**:本修复使「对 website-camthink 全量重灌」在语料安全性上可授权(重灌只会重建/覆盖/精确清自身 stale,不再可能跨文档删除)。恢复执行前置条件(均为独立 Gate):① 修复进新镜像并完成部署 Gate;② 同步 embed 运行通道决策(GPU 容量 / CPU / 后端内联);③ 恢复后跑账本↔实际收敛验收(163→~348,账本一致,trust-boundary 分布复核)。

## 10. STOP 声明

本 Gate 无生产访问、无部署、无语料恢复、无 GPU 策略变更。本地一次性 Weaviate 容器 `p0a-weaviate` 已于验证后销毁。

**STATUS = PASS**
