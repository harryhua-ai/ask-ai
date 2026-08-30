# Execution Contract: d4-ingest-accounting-and-consistency-calibration

> **任务代号**:D4-ACC
> **签发**:Planner / Reviewer Authority(2026-08-30,三项拍板同日:D4 立项 + 口径统一同包 + 孤儿全清)
> **本契约自包含,Executor 无需读取规划会话历史**

## 1. BASELINE_COMMIT

`5ca3dfe`(= P1-RES Task 1 push 后的 main)。**前置**:执行端先完成 P1-RES Task 1 的 push(`worktree-exec/admin-visibility` → main),确认 main = `5ca3dfe` 再开 worktree。

## 2. Objective

1. 修复 **D4 缺陷**:ingest 批量写入的成功记账依赖已废弃的 `all_responses` 属性,失败被静默记成功——恢复真实记账,使一致性自愈体系的数据根基可信。
2. 修复**校验器口径假阳性**:汇总级聚合使用 Weaviate TEXT `like` 分词匹配,源前缀 token 互相污染(neomind 家族实证),产生永久假 partial。
3. 清理 **615 篇真孤儿**(5 源,已拍板全清)。

## 3. Current State / Evidence

**[FACT]** `backend/pipeline/ingest.py:251` 与 `:482`:`getattr(result, "all_responses", [])` ——属性废弃后静默返回空 → `failed_idx` 恒空 → 失败全部计成功、replace 回退不触发、`_upsert_postgres` 按假数落账。生产实证:ne503-sdk `README.md` 日志 `7/7 chunk 成功`但确定性 UUID(`uuid5(NAMESPACE_URL, "{sid}#{idx}")`)探针 #3..#6 缺失;refill 震荡(568→605→639 vs expected 冻结 592)。
**[FACT]** `backend/services/vector_consistency.py:70-72`:汇总级 `Filter.by_property("source_id").like(f"{prefix}/*")` 聚合 `total_count` ——Weaviate TEXT `like` 按 token 分词匹配(`neomind-local/*` 匹配整个 neomind 家族;D-11 已实证 `*/._*` 误中全库 12.9 万)。假阳性实证:neomind-dashboard 359/231、neomind-local 16983/10953,而精确级(`:93` 迭代器全表 + 客户端前缀过滤)完全一致(231/231、10953/10953)。
**[FACT]** 615 篇孤儿分布(迭代器口径,2026-08-30 清单):ne301-local 523/2822 chunks、wiki-documents-local 42/99、neomind-extensions-local 38/38、lowpower-camera-local 10/160、neomind-devicetypes-local 2/6;性质均为分支旧版/已删文件残留(纯 orphan,pg 无对应行)。
**[FACT]** dashboard 与 neomind-local 两源**无需任何数据清理**(迭代器口径已一致)。
**[UNKNOWN]** D4 修复部署后 ne503-sdk 假成功文档能否完全自愈收敛——部署后观察项,不入本契约硬验收。

## 4. Product / Architecture Contract(冻结 WHAT)

**Task 1|代码(worktree)**:ingest 写入记账改用 Weaviate v4 官方返回(`result.errors` / `result.uuids`,消除 Dep020),两处(`:251`/`:482`)一致迁移;失败检测恢复后,既有 replace 回退、`failed` 列表、`_upsert_postgres` 计数链路自然回到真实值。**不改变** prune 逻辑与幂等 UUID 设计。

**Task 2|代码(同包)**:校验器消除 `like` 分词假阳性——汇总级不得依赖 TEXT `like` 分词语义(与精确级口径一致;具体实现 HOW 自定:如汇总级改用迭代器/客户端过滤口径,或废弃不可靠的 fast-path)。**约束**:真缺口检测能力不得下降(构造 missing/orphan/chunk 差的回归测试必须仍全检出)。

**Task 3|T4 数据**:615 篇孤儿按迭代器/UUID 口径点名清理(仅 wv 对象删除,pg 本无行),5 源前后计数留证;清理后以**迭代器口径**复验 5 源 expected=actual。

## 5. Non-goals

- 不部署(合入后随下次常规发布;ne503 自愈收敛为部署后观察项)
- 不改 prune 删除条件、不动幂等 UUID 机制
- 不修"源里消失文档"盲区(候选池另立)
- 不动 dashboard / neomind-local 两源数据(它们无病)
- 不改 `channel_visibility`/检索行为(P1-RES 已完成)

## 6. Acceptance Criteria

| # | 验收 |
|---|---|
| A1 | TDD:模拟"部分对象失败"(含 all_responses 缺失场景)→ `failed_idx` 正确检出、replace 回退触发、failed 计数真实——先红后绿 |
| A2 | 既有成功路径测试不回归(全量 pytest 排除 embedder/e2e 与 CI 同口径全绿;ruff 全仓与 main 同集合零新增) |
| A3 | TDD:构造 like 分词污染场景(如 neomind 家族前缀)→ 修复后汇总级不再误计;先红后绿 |
| A4 | 回归:构造 missing / orphan / chunk 差三种真缺口 → 精确级全部仍检出 |
| A5 | 615 篇清理佐证:5 源逐源前后计数(615/3125 → 0);清理后迭代器口径 5 源 expected=actual |
| A6 | 汇报:execution report 至 `docs/engineering/tasks/d4-acc-execution.md`,给证据不给形容词,四态自评 |

## 7. Required Verification

- Task 1/2 在 worktree(`worktree-exec/ingest-accounting`,基线 `5ca3dfe`)内 TDD;`TEST_DATABASE_URL` 必设;**push 前回报,经 Review 放行**
- Task 3 在 T4:删除仅限 615 篇点名清单;盘点/删除一律迭代器/UUID 口径(禁 like/Equal 点名)
- 红线:绝不 `--reindex`;提交不含 docs/;ruff/black/isort;line-length=100;中文提交信息

## 8. Regression Constraints

- 成功路径的写入行为与计数**语义不变**(只修失败检测)
- 校验器对外接口(`VectorGapReport` 字段、`verify_source_vectors` 签名)不变
- prune 触发条件、确定性 UUID、增量窗口逻辑零改动

*契约冻结。变更须 Reviewer 显式 RE-PLAN。*
