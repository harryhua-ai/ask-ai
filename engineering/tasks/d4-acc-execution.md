# Execution Report: D4-ACC(ingest 记账修复 + 校验器口径统一 + 孤儿清理)

> **契约**:`docs/engineering/contracts/d4-ingest-accounting-and-consistency-calibration.md`(冻结)
> **执行日期**:2026-08-30 | **执行者**:Engineering Executor
> **状态总评**:**PASS**(A1-A6 全过;待 Review 判定)

## 1. Baseline Commit

`5ca3dfe`(= origin/main,执行前复核一致)

## 2. Final Commit(worktree `worktree-exec/ingest-accounting`,**未 push,等 Review 放行**)

| Commit | 内容 |
|---|---|
| `ce59b15` | Task 1:fix(ingest) 写入记账迁移 result.errors/uuids |
| `fe98ca2` | Task 2:fix(services) 校验器汇总级弃用 like 聚合,统一迭代器口径 |

## 3. Files Changed

| 文件 | 变更 |
|---|---|
| `backend/pipeline/ingest.py` | 2 处记账迁 `result.errors`(键=原始下标);零逻辑外改动 |
| `backend/services/vector_consistency.py` | 汇总级弃用 like 聚合;单次迭代器统一口径;`is_healthy` 升级全一致语义;签名/字段不变 |
| `tests/pipeline/test_ingest_accounting.py` | 新增 4 测试(先红后绿) |
| `tests/services/test_vector_consistency.py` | 新增污染场景测试;healthy/孤儿 2 测随口径更新 |
| `tests/pipeline/test_ingest.py` | 幂等测试 mock 迁新 API(all_responses → errors) |
| `tests/scripts/test_sync_db.py` | 窗口用例 mock pipeline 补种子向量(见 Deviation 1) |

## 4. Task 1:ingest 记账迁移 —— **PASS**

**根因机制(契约 [FACT] 实证补充)**:`all_responses` 仅保留末尾 `MAX_STORED_RESULTS` 条,超限**丢弃最旧条目**→ `failed_idx` 恒空或错位 → 失败静默计成功、replace 回退不触发。

**迁移**:两处一致改为 `result.errors`(官方 `Dict[原始下标, ErrorObject]`,完整且键即 insert_many 内原始下标);跨 doc 块路径加块偏移映射。成功路径语义不变(errors 空 → 计数不变、replace 不触发);prune 条件与幂等 UUID 零改动(契约回归约束)。

**TDD 证据(A1)**:
- 红:`test_partial_failure_triggers_replace_and_real_count` / `test_replace_failure_counts_real_failure_not_false_success` / `test_ingest_all_block_offset_accounting` **3 failed, 1 passed**(成功路径守卫用例红前即绿)
- 绿:4 passed;关键断言:errors 检出 → `replace.assert_called_once()` 且 `uuid == uuid5("test/1#0")`(块偏移映射正确);replace 也失败 → `count == 0`(真实失败计数,不虚报)
- Dep020 复查:0 处;`all_responses` 残留仅注释

## 5. Task 2:校验器口径统一 —— **PASS**

**实现**:删除聚合(like)快路径;汇总级与精确级统一为**单次迭代器全扫 + 客户端前缀过滤**,一次遍历同时产出 `actual` 与逐文档 chunk 集合;`is_healthy` 升级为全一致语义(汇总相等 且 无缺失/无不一致/无孤儿)。`VectorGapReport` 字段与 `verify_source_vectors` 签名不变(契约约束)。

**TDD 证据**:
- A3 红:`test_summary_level_not_fooled_by_like_token_pollution`(pg=3/迭代器=3/聚合污染值=16983 → 旧实现 `is_healthy=False` FAIL)→ 绿:healthy=True、actual=3、refill/孤儿空
- A4 回归:missing(`test_verify_detects_missing_source_ids_when_counts_differ`)/ chunk 差(`test_verify_detects_partial_chunk_loss`、`test_verify_detects_extra_chunks`)/ orphan(`test_orphan_count_only_within_source_prefix`)+ 并集排序(`test_refill_unions_missing_and_chunk_mismatch_sorted`)**全部原断言通过,零削弱**

## 6. Task 3:五源孤儿点名清 —— **PASS**

迭代器口径判定孤儿(wv 有、pg 无);逐对象确定性 UUID `uuid5(NAMESPACE_URL, f"{sid}#{idx}")` 删除;禁用 like/Equal 点名。

| 源 | 清理前 orphan docs/chunks | 删除对象 | 清理后 pg_sum vs wv | 残留孤儿 |
|---|---|---|---|---|
| ne301-local | 523 / 2822 | 2822 | 67411 = 67411 | 0 |
| wiki-documents-local | 42 / 99 | 99 | 3892 = 3892 | 0 |
| neomind-extensions-local | 38 / 38 | 38 | 3665 = 3665 | 0 |
| lowpower-camera-local | 10 / 160 | 160 | 36841 = 36841 | 0 |
| neomind-devicetypes-local | 2 / 6 | 6 | 826 = 826 | 0 |
| **合计** | **615 / 3125** | **3125(失败 0)** | **5/5 一致(A5 ✅)** | 0 |

dashboard 与 neomind-local 未触碰(Non-goal;两源本就迭代器口径一致)。删除明细清单:`tesla-t4:backend容器 /tmp/d4acc_deleted.json`。

## 7. Required Verification 实际执行

- 全量回归(排除 embedder/e2e,CI 口径,TEST_DATABASE_URL 已设):**512 passed, 3 skipped**(基线 507 + 新增 5 测试)
- ruff 全仓:worktree 78 行 = main 78 行,零新增;black/isort 改动文件全过(SIM118/F401 两条新增即改)
- 红线:无 --reindex;Task 3 删除仅限 615 篇点名清单;prune/UUID/窗口逻辑零改动;提交不含 docs/;中文提交信息

## 8. Acceptance Self-assessment

| # | 验收 | 自评 |
|---|---|---|
| A1 | 记账 TDD 先红后绿(部分失败 + all_responses 缺失) | **PASS** |
| A2 | 全量绿 + ruff 零新增 | **PASS** |
| A3 | like 污染场景先红后绿 | **PASS** |
| A4 | 三种真缺口仍全检出 | **PASS** |
| A5 | 615 篇清理佐证 + 迭代器口径 5 源一致 | **PASS** |
| A6 | 本报告 | **PASS** |

**Overall: PASS**(待 Review 判定)

## 9. Deviations

1. `test_sync_db.py::test_sync_one_uses_last_success_as_window` 的 mock pipeline 原为裸 MagicMock——旧实现下聚合 `int(MagicMock)=1` 与种子恰好相等而"偶然健康";新口径诚实检出种子文档无向量 → refill → 记录型 connector 无 fetch_all → failed。修正:mock weaviate 补种子文档向量(场景自洽),窗口断言不变。属测试随口径的正确维护,非削弱。
2. Task 1 新测试初版 embedder mock 固定返回 1 向量,暴露跨 doc 批嵌入前提后改为按请求数量返回(用例自身修正,未改产品代码)。

## 10. Remaining Risks

1. 修复在生产生效需随下次常规发布(Non-goal:不部署);ne503-sdk 假成功文档的自愈收敛为部署后观察项(契约 [UNKNOWN])
2. 五源下次同步(手动或 cron)起应转 success;sync_log 中历史 partial 行为既录,不清
3. 校验器逐源全扫的性能成本(本地/单实例量级 ~13 万对象,单源秒级)已在可接受范围;如未来库规模数量级增长可再议分桶
