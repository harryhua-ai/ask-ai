# Review Report: d4-ingest-accounting-and-consistency-calibration

> **Reviewer**:Planner / Reviewer Authority · **日期**:2026-08-30
> **契约**:`docs/engineering/contracts/d4-ingest-accounting-and-consistency-calibration.md`
> **Executor 报告**:`docs/engineering/tasks/d4-acc-execution.md`
> **Baseline**:`5ca3dfe` · **Final**:`fe98ca2`(`ce59b15` Task1 + `fe98ca2` Task2,未 push)

## 独立重查

| 要素 | 核验 | 结论 |
|---|---|---|
| Frozen Contract | 要素齐全;唯一 Deviation(test_sync_db mock 适配)依协议记录 | ✅ |
| Baseline → Final Diff | 6 文件 +243/-63;Task1 两处 `all_responses`→`result.errors`(键=原始下标)+ 块偏移映射 `_ws + _i`,最小正确;Task2 删 like 聚合快路径、单次迭代器统一口径、`is_healthy` 语义增强;`VectorGapReport` 字段与签名不变(契约约束满足) | ✅ |
| Tests | Task1 红 3 failed(假成功/replace 不触发/计数)→绿;Task2 污染场景红→绿;**A4 三缺口回归原断言零削弱全过**;全量 512 passed 3 skipped(CI 口径);ruff 78=78 零新增;Dep020 归零 | ✅ |
| Runtime Evidence | Task 3 五源清理:615/3125 与契约逐源数字精确吻合,删除 3125 对象失败 0,清后 5/5 源迭代器口径 pg_sum==wv_sum、残留孤儿 0 | ✅ |
| Acceptance | A1-A6 全过 | ✅ |

**边界案例裁定(Deviation 1)**:`test_sync_db.py` 窗口用例——断言改动经逐行比对为**纯格式重排,语义零变化**;mock 改动为**场景自洽化**(旧 mock 裸 pipeline 靠聚合假数据偶然判健康,新口径下诚实判缺失;补种子向量使 mock 反映真实场景)。**合法适配,非断言削弱。**

**机制确认(执行端补充,有价值)**:废弃的 `all_responses` 仅保留末尾 `MAX_STORED_RESULTS` 条、超限丢最旧——不止属性缺失,截断还会导致 `failed_idx` 错位,假成功机制比契约 [FACT] 记载的更隐蔽。

## 最终判定:**PASS**(协议时代首个完整 PASS)

- Task 1/2 **放行 push**(`ce59b15`+`fe98ca2` → origin main)
- Task 3 数据闭环,无遗留
- **任务关闭**。发布与部署后观察项(契约外,另行执行):`5ca3dfe + D4-ACC` 同窗一次性发布 T4 → 观察① ne503-sdk 假成功文档自愈收敛 ② 五源 partial→success 翻转 ③ admin 聊天检索恢复(P1 生效)

*docs 本地仓;下一 contract:C8(官网爬取)+ C9(上传文件夹)+ C10(github 表单/可诊断性)三合一窗口。*
