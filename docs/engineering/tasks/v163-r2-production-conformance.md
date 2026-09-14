# v1.6.3-r2 生产 Conformance 报告

- 发布身份：Product iteration = **v1.6.3** / Release = **v1.6.3-r2**（取代更早的 v1.6.3 生产 UI 实现）
- 冻结 commit：`fd5ca39d7ee1097abe10de513ce7e595f159270a`（tag `v1.6.3-r2`）
- 执行记录（R1 全量证据）：`docs/engineering/tasks/v163-wave2-integration-execution.md` § R1
- 本文件职责：发布/迁移/身份 = R1 已填充；**生产 UI 验收 ledger = 下一 agent 填充**

## 1. Release（已填充）

| 项 | 值 | 证据 |
|---|---|---|
| Clean-tree 门 | pytest 2630/0/7（=基线逐字）· PA 114/114 · planner 31/31 · vitest 540/540 · tsc 0 · build ✓ · ruff 全仓指纹=基线 | R1 §R1.1 |
| 部署契约扩展 | `-rN` 重转后缀最小扩展（授权），commit `801676a`；fail-closed 语义零弱化 | R1 §R1.2 |
| Tag / Release | `v1.6.3-r2` → fd5ca39；Release URL https://github.com/harryhua-ai/ask-ai/releases/tag/v1.6.3-r2 | R1 §R1.3 |
| CI / lineage | run 34803619956 test PASS + build PASS；镜像内 RELEASE.json `version=1.6.3-r2, git_sha=fd5ca39…`；镜像 `ghcr.io/harryhua-ai/ask-ai:v1.6.3-r2` | R1 §R1.4 |

## 2. Production Migration（已填充）

- 部署 run **34804523307** SUCCESS（3m37s）；GitHub Deployment id=6430201280 state=success
- 迁移桥按序 3 条（冻结镜像内执行,每条前镜像身份断言 ✅；PLAN SOURCE=manifest@fd5ca39d7ee1）：
  1. `migrate_add_site_launcher_presentation.py` → 完成（幂等,零回填）
  2. `migrate_p1_lifecycle_foundation.py` → 完成（PG documents 加列 + P1 三表；Weaviate 147999 legacy 对象验证全过）
  3. `migrate_add_track_c_product.py` → 完成（content_type 回填 **12000** 行 + data_sources 三列 + 三新表）
- Schema 在位（SSH 只读核验）：`documents.content_type`、`data_sources.next_run_at/knowledge_role/freshness_hours`、`document_repair_tasks/document_recovery_events/knowledge_settings_previews`、`gap_observations/gap_observation_events`、`documents` 生命周期五列、`site_experiences.launcher_presentation` —— 全部 ✓；三新表 0 行（加性）
- 回填诚实性：12000/12000 全部非空（document:11818 / page:141 / product:41），权威 `derive_content_type` 派生,零 NULL、零猜测值

## 3. Production Identity（已填充）

- `/health`：`{"status":"ok","version":"1.6.3-r2","git_sha":"fd5ca39d7ee1097abe10de513ce7e595f159270a","app_mode":"production"}`（workflow 双断言 + SSH 独立复核一致）
- 容器：backend/sync-cron/sync-executor = `ghcr.io/harryhua-ai/ask-ai:v1.6.3-r2`；backend restarts=0 / healthy；PG、Weaviate healthy
- backend 启动以来 ERROR 计数 = 0
- 生产 admin 凭据位置：`backend/main.py:253`（种子回退字面量,值不复述）+ 主机 `~/ask-ai/.env ADMIN_PASSWORD`（仓内仅占位符）+ `deploy/prod/RC-2026-09-01-ACTIVATION.md:43` 处置勾选项

## 4. 生产 UI 验收 Ledger（下一 agent 填充）

> 登录前置：确认 RC-2026-09-01-ACTIVATION §阶段3 admin 口令处置状态；凭据来源=主机 `.env`（见 §3）

| # | 验收项（参考需求映射） | 入口/路径 | 结果 | 证据 |
|---|---|---|---|---|
| 1 | 数据源修复工作流 | 待填 | 待验收 | 待填 |
| 2 | 知识设置 CURRENT-HISTORICAL | 待填 | 待验收 | 待填 |
| 3 | 高风险预览确认流 | 待填 | 待验收 | 待填 |
| 4 | 权威 content_type / serving score / 恢复计数 / 下次同步 | 待填 | 待验收 | 待填 |
| 5 | 扩展原因词表 | 待填 | 待验收 | 待填 |
| 6 | OBSERVING 状态机 | 待填 | 待验收 | 待填 |
| 7 | CSV 导出 | 待填 | 待验收 | 待填 |
| 8 | 受影响用户聚合 | 待填 | 待验收 | 待填 |
| 9 | gap→源归因 | 待填 | 待验收 | 待填 |
| 10 | 确定性主题 | 待填 | 待验收 | 待填 |
| 11 | 全参考对齐 Admin UX（152 reconcile 抽样） | 待填 | 待验收 | 待填 |

## 5. 边界声明

- 本发布**不宣称 iteration v1.6.3 COMPLETE**
- R1 期间零 force push / 零历史改写 / 零 issue 关闭 / 六候选与已 tag 历史未动 / 生产仅授权部署 + 只读核验（数据零 mutation）
