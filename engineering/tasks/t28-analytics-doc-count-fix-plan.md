# T28-ANALYTICS-DOC-COUNT-FIX Execution Contract(数据源健康度文档数恒 0)

- **Task ID**:t28-analytics-doc-count-fix | **Parent Initiative**:数据源健康度(D-9 归属体系)
- **Baseline Commit**:`bbfaa6a`(main = origin/main)
- **Risk Level**:**L1**(单端点聚合修正,纯后端只读口径,无 schema/写入变更)
- **Contract Authorization**:**AUTHORIZED**(2026-08-31,Role A 签发)——用户本地自测报告"analytics 文档数都是 0",经代码+本地库实证为后端聚合缺陷;与 T25A(该表 UI 迁移)分层互补,本任务只修数字。

## 1. Objective

`GET /api/admin/analytics/source-health` 的 `doc_count` / `chunk_count` 按**数据源 id 前缀**聚合 documents,修复"复合键精确匹配纯 id 永远 miss → 恒 0"的缺陷,并补齐该端点缺失的测试覆盖。

## 2. Current State / Evidence(Inspect @ bbfaa6a,已实证)

| # | 事实 | 级别 |
|---|---|---|
| E1 | `documents.source_id` 为复合键 `{数据源id}/{路径}`,五个 connector 一致:`github.py:217` / `local_git.py:135` / `filesystem.py:107` / `woocommerce.py:233` / `web_crawl.py:405` 均 `f"{id}/{...}"` | FACT |
| E2 | `source_health`(`analytics.py:392-405`)按**完整 source_id** 分组生成 `doc_map`,再用 `sync_log.source_id`(纯数据源 id)精确查找 → 键形如 `website-camthink` vs `website-camthink/blog/xxx`,永不命中 → `doc_count/chunk_count` 恒 `(0, 0)` | FACT |
| E3 | 本地库实证:documents 371 行、全部复合键(如 `website-camthink/feed`、`local-db326229/main/...`、`knowledge-1db4e151/main/...`);sync_log.source_id 全为纯 id → 页面全 0 | FACT |
| E4 | `/source-health` **零测试覆盖**(grep tests/ 无一处引用);test_analytics.py 仅 1 个 coverage_gaps 用例 | FACT |
| E5 | 其余 `Document.source_id` 消费方(pipeline/ingest.py:583/:622 去重与 prune)用完整复合键、语义正确,不受影响 | FACT |
| E6 | 同一份代码跑在 T4 生产 → 生产 analytics 页同样全 0(随下次发布一并修复) | FACT |

## 3. Scope

- `source_health` 端点内 `doc_q` 聚合键改为数据源 id 前缀(复合键首段;无斜杠时整串即 id),`doc_map` 键随之对齐 sync_log 口径;`chunk_count` 同口径;
- 新增 `/source-health` 回归测试(夹具必须用**真实复合键**形态,杜绝再次用纯 id 掩盖缺陷):多源计数、无文档源为 0、chunk 求和、无斜杠 source_id、sync_log 有而 documents 无的源为 0;
- 其余字段(sync_success_rate/health/last_sync)语义不变。

## 4. Non-goals

表结构/写入链路/connector 的 source_id 约定;sync_log 聚合口径与 30 天窗口;无 sync 记录的源是否入表(现语义:仅 sync 窗口内源入表,维持);前端(Analytics.tsx 及 T25A 迁移);ingest/prune。

## 5. Change Boundary

**Product**:允许 = 端点内聚合键修正 + 新增测试;必须不变 = 响应字段结构与其余字段值语义、复合键存储约定。
**Code EXPECTED**:`backend/api/admin/analytics.py`、`tests/api/admin/test_analytics.py`(或新增测试文件)。
**FORBIDDEN**:其余 backend/**(尤其 pipeline/ingest、connectors)、admin/**、widget/**、DB schema。
**Regression**:CI 口径 pytest(443+)全绿 + tests/api/admin 全绿(需 ENCRYPTION_KEY/TEST_DATABASE_URL)。

## 6. Frozen Contract

1. `doc_count` = 该数据源 id 前缀下 documents 行数,`chunk_count` = 同口径 `chunk_count` 求和(无文档 → 0/0);
2. 响应 JSON 字段集合与既有完全一致(前端零改动);
3. documents.source_id 复合键约定与写入链路零改动;
4. 新增测试以复合键夹具锁定行为。

## 7. Acceptance Criteria

- **AC1**:本地真实库(371 篇复合键文档)调端点:有文档的 sync 源 `doc_count>0` 且与 SQL 前缀聚合对账一致(website-camthink / local-db326229 / knowledge-* 抽查 ≥3 源,对账 SQL 附报告);
- **AC2**:无文档源与无斜杠 source_id 用例通过;空 documents 表不报错;
- **AC3**:CI 口径 + tests/api/admin 全绿,新增用例 ≥4;
- **AC4**:报告落 `docs/engineering/tasks/t28-analytics-doc-count-fix-execution.md`,CANDIDATE READY,不 push。

## 8. Parallel / 依赖

纯后端单文件域,与 C8B / T25A / T26 / T27 全部互斥可并行;T25A(UI 迁移)依赖本任务修复后的正确数字才有意义,建议同批发布。

---

## 9. Executor Prompt(可拷贝)

```markdown
# Role B 执行任务:T28-ANALYTICS-DOC-COUNT-FIX(数据源健康度文档数恒 0)

先完整阅读:
1. /Users/harryhua/Documents/GitHub/ask-ai/docs/engineering/DUAL_AGENT_PROTOCOL.md
2. /Users/harryhua/Documents/GitHub/ask-ai/docs/engineering/role-B.md
3. 契约:/Users/harryhua/Documents/GitHub/ask-ai/docs/engineering/tasks/t28-analytics-doc-count-fix-plan.md

## 任务
修复 GET /api/admin/analytics/source-health 的 doc_count/chunk_count 恒 0 缺陷:documents.source_id 是复合键
"{数据源id}/{路径}"(五个 connector 一致),现按完整键分组后用纯数据源 id 精确查找永不命中(analytics.py:392-405)。
改为按复合键首段(数据源 id 前缀)聚合;无斜杠时整串即 id。响应字段结构与其余字段语义不变。
并补齐该端点零测试覆盖:夹具必须用真实复合键形态。

## 环境与边界
- 主仓:/Users/harryhua/Documents/GitHub/ask-ai(baseline = main = origin/main = bbfaa6a,开工前自行核实)
- worktree:/Users/harryhua/Documents/GitHub/ask-ai-t28-doc-count,分支 worktree-exec/t28-analytics-doc-count-fix
- Change Boundary 以契约 §5 为准:EXPECTED 仅 analytics.py + 测试;FORBIDDEN 含 pipeline/ingest、connectors、admin、DB schema
- 测试红线:export TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test;tests/api/admin 需 ENCRYPTION_KEY 注入(参考既有注释)
- 不 push、不部署、不碰生产

## 验证(全部实际执行,给证据)
1. 新增用例 ≥4:多源复合键计数 / 无文档源为 0 / chunk 求和 / 无斜杠 source_id;两口径 pytest 全绿
2. 本地真实库对账:起本地后端(或测试内直连)调端点,website-camthink / local-db326229 / knowledge-* 抽查 ≥3 源,doc_count 与 SQL 前缀聚合结果一致,对账 SQL 与输出附报告
3. 回归:CI 口径 pytest(443+)全绿

## 交付
- 报告:docs/engineering/tasks/t28-analytics-doc-count-fix-execution.md(协议模板:Worktree/Branch、Baseline/Final Commit、Files Changed、Implementation、Verification actually executed、Runtime/Self-Check、Deviations/Risks、Status)
- 最终回复必须含:报告路径 + final commit + 状态(仅 CANDIDATE READY / PARTIAL / FAIL / BLOCKED)
- Gate 停等:本任务不 push,等 A Review 放行
```
