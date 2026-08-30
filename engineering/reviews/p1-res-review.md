# Review Report: p1-admin-visibility-and-data-residuals

> **Reviewer**:产品规划/审查窗口(依 `docs/planner-reviewer-protocol.md`)
> **日期**:2026-08-30 · **契约**:`docs/engineering/contracts/p1-admin-visibility-and-data-residuals.md`(冻结)
> **Executor 报告**:`docs/engineering/tasks/p1-res-execution.md` · **Baseline**:`88a4c9f` · **Task 1 Final**:`5ca3dfe`(未 push)

## 1. 独立重查

| 要素 | 核验 | 结论 |
|---|---|---|
| Frozen Contract | 契约要素齐全;执行端 5 项 Deviation 全部依协议记录,无静默 | ✅ |
| Baseline → Final Diff | `88a4c9f..5ca3dfe` 仅 2 文件(+218/-42:search.py + 新测试);Non-goal 遵守(sync.py 零改动);3 处 black 基线格式重排为格式性,已声明且全量测试覆盖 | ✅ |
| Tests | TDD 红(ImportError)→绿(8 tests);断言经 Filter repr 渲染实际过滤值,强度足够;回归四渠道 × 三过滤点等价断言;全量 507 passed 3 skipped(排除口径与 CI 一致);ruff 全仓 78=78 零新增;首跑 1-2 例 analytics flaky 有基线对照排除,处理规范 | ✅ |
| Runtime Evidence | Task 2 全链留证(rename 提交定位、49 行窗口压回、470 灌入、15 篇清理前后计数、3 轮收敛观察);Task 4 只读扫描零删除 | ✅ |
| Acceptance | T1-1/2/3、T2-2、T3-1、T4-1 = PASS;**T2-1 = PARTIAL**(items=470 ✅,终态 partial 走契约预留"如实报因"分支) | 见判定 |

**Reviewer 独立代码核验**:
- **D1 复核成立**:`search.py:291`(`search_bucket`,boost 桶)确为第三处过滤点——**Planner 契约 Inspect 遗漏,记为 Planner 失误**;执行端三处同改正确(不改则 admin 意图软路由桶零命中,Objective 不成立)。
- **D4 复核成立(关键)**:`ingest.py:251/:482` 的 `getattr(result, "all_responses", [])` 在属性废弃后**静默返回空** → `failed_idx` 恒空 → 失败全部记成功、replace 回退不触发、pg 按假数落账。与实证(README 7/7 假成功 + uuid5 #3-#6 缺失 + refill 震荡)闭环吻合。**定性:真实产品缺陷,影响面 = 全部 github 源的 replace 写入记账**。
- 实现 diff:`_VISIBILITY_CHANNEL_ALIAS` 模块级映射 + None 透传,语义最小、注释到位;search_symbols 的 channel 有默认值(`"widget"`)不受 None 传染。质量合格。

## 2. Discrepancy 裁定(5 项全部接受)

| # | 内容 | 裁定 |
|---|---|---|
| D1 | 第三处过滤点同改 | 接受;Planner 契约修正记录在案 |
| D2 | 窗口重置配对 clone 回退(SHA 短路);host clone 误操作已恢复 | 接受;配对操作是正确工程判断 |
| D3 | D-11 "10 partial" 口误 → 9 | 接受;基线历史表述已随本次更新 |
| D5 | "8 源"实为 7 源;dashboard/neomind-local 为聚合口径假阳性 | 接受;**改写决策基础**:两源无需清理,真孤儿 615/5 源 |

## 3. 最终判定:**PARTIAL**(与自评一致)

- **Task 1 = PASS,放行 push**(`5ca3dfe` → origin main;部署仍按契约 Non-goal 不做,随下次常规发布)
- **Task 2 = PARTIAL**:契约动作全部完成且留证(470 灌入、15 篇清理残留 0),终态 partial 根因 = D4 缺陷 + 两口径差,均超契约范围且如实上报——不降 contract,判 PARTIAL
- **Task 3 / Task 4 = PASS**
- 任务关闭条件:Task 1 push 完成。**遗留正式分流**:D4 修复、口径统一、615 孤儿拍板(见 §4)

## 4. 遗留处置(Reviewer 立项建议,待产品负责人拍板)

1. **D4 `fix(ingest)` 记账迁移(建议高优,与 T1a 并行)**:`all_responses` → `result.errors`/`uuids`(Dep020 本就要求迁移);它侵蚀一致性自愈的记账根基,ne503 终态收敛依赖它;改动小。
2. **校验器口径统一(建议与 D4 同包)**:汇总级(聚合,含无 chunk_index 历史对象)vs 精确级(迭代器,跳过)两口径差已实证产生假阳性 partial(dashboard/neomind-local 常驻黄标);统一口径或输出专门标记。
3. **615 篇孤儿(5 源)逐源拍板**:清单已交付;建议全清(纯孤儿 pg 无行、零风险、防过时内容被检索命中)。

*Review artifact(docs 本地仓);下一 Review 对象:D4 修复任务(若立项)或 T1a。*
