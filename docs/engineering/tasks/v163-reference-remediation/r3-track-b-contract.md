# R3 Track B Contract — Data Source Runtime Truth（冻结）

- Reference（权威）：①Issue #62（全部，含工程事实与预期行为）、#67（Truth Audit 部分+Phase-2 边界）、#65（单位核实边界）；②`v163-r3-data-source-design-contract.md` §G-1/G-3/G-4；③生产只读 Truth 实证（2026-09-14，planning 期已核）。
- Issue IDs：**#62**（全部）、**#67**（R3-67-AUDIT/GENFIX）、**#65**（R3-65-UNIT 签收）。
- 基线：fresh main `94ddb64`。

## 1. Product Semantics（冻结）

1. 唯一不变量（#62 原文）：`Configured sync_interval = scheduler due semantics = next_run_at truth = actual automatic sync cadence`。
2. cron tick 频率（保持 3600s wake-up）≠ 源同步频率；每次 tick 只执行 due 源：`enabled AND sync-eligible AND no inflight sync AND next_run_at <= now`（或等价单一权威判定，实现内唯一）。
3. 显式触发即时执行、不受 due gate 限制：单源同步/同步全部/repair/recovery/CLI 指定源；「同步全部」保持显式人工动作语义，不得被 due gate 静默跳过。
4. disabled/deleting/inflight 既有调度约束保持；triggered_by 区分 cron/manual。
5. 禁止反向对齐：不得把 UI 24h 改成 1h 迁就现状。
6. #67：Generation truth 呈现审计完成前冻结（Track A 侧）；禁把 #0/0/0 无证据解释为「历史数据」；禁 UI 遮盖；禁 Weaviate object count 反向伪造账本。
7. #65 单位契约：`items_new/items_deleted` 单位必须与 UI 文案一致（知识/文档 vs chunk）；不一致时先修真值/加文档级权威计数，再放行文案。

## 2. 变更边界（文件所有权）

- 可改：`scripts/sync.py`（due gate）、`backend/services/schedule_truth.py`（due 语义单一权威化/reconcile 对齐）、`backend/pipeline/generation_builder.py`（审计裁决涉及的建模修正）、`backend/api/admin/data_sources.py`（generations 读面如实建模）、新增迁移脚本（如 GENFIX 裁决需要，命名沿 `migrate_*.py` 幂等惯例）+ pytest。
- 禁改：`deploy/prod/docker-compose.yml`（cron tick 结构不在本轨范围；如需变更另行走 G6 迁移桥授权）；admin/src 任何文件；连接器（Track D）。
- 审计=只读生产核验（SELECT）+ 隔离数据态确定性验证运行；**生产零 mutation**。

## 3. Backend/Data 要求

- due 判定单一权威：与 `schedule_truth.compute_next_run_at/reconcile_next_run_at` 同源（禁两套语义）；tick 内先 due 过滤再逐源执行；inflight 判定复用既有 sync_requests 谓词。
- `next_run_at` 语义升级：run 完成/配置变更后 reconcile 保持既有幂等；新增「真实下次自动执行」等价性测试。
- Generation 审计 10 问（#67 原文）逐项回答并出报告（含：API 空根因、#0 根因、是否迁移产物、pre-generation 语料范围、新同步 generation 计数确定性验证、sentinel 建模 or migration/backfill 裁决建议）。
- 生产实证输入（planning 已核，执行期复核）：15/15 源 `sync_interval=24h`、`next_run_at≈+24h`、woo cron 实际间隔 60–72min（sync_runs 连续 8 次 triggered_by=cron）；`index_generations` 仅 3 行（`*legacy*` #0 ready 0/0 @2026-09-11 迁移日 / ordinal=1 failed 0/0 / ordinal=2 ready 0/0）；12000 document_versions.generation_id 非空、wiki 文档→`*legacy*` #0。

## 4. Frontend 要求

无（本轨零 frontend 文件）。

## 5. Forbidden shortcuts（r2 冻结清单沿用）

- fake counts / keyword-only 分类 / 前端兜底掩盖后端缺口；**禁用「把 UI 改成 1h」对齐错误执行**；禁无审计证据的 legacy 归因；禁把真实 0 改横杠掩盖账本；禁仅 UI 隐藏 Generation 区域；禁 Weaviate 计数反推；审计未完成不得宣告 Generation 面完成或解除 A 轨冻结。

## 6. Acceptance（验收门）

- 验收矩阵 Track B 全行证据填充。
- pytest：**时间推进测试**（1h/6h/24h 三源同一 cron tick 序列只在到期运行；手动触发 due 未到仍执行；24h 源 1h 后无 cron run；disabled/inflight 约束回归）；单位契约断言（fixture 源 N 文档→items_new=N）。
- G7 生产只读复核：24h 源 next_run_at 前无新 cron run；1h 源（如设）正常；restarts=0/ERROR=0。
- 审计报告作为 R3-67-AUDIT Runtime evidence 输入；GENFIX 如涉迁移，走 G6 迁移桥（幂等+镜像身份断言）。

## 7. Runtime states（必须覆盖）

due 到期/未到期/inflight 占用/disabled 四态 × cron tick；1h/6h/24h 三源混合序列；generation：legacy-sentinel 源/新同步源/审计后建模态（如实施）。

## 8. E2E

- 同一 cron tick 序列端到端（隔离数据态）：仅 due 源产生 run；`next_run_at` 与实际执行一致（G5）。

## 9. Deliverables

分支 + due-gate 实现 + pytest（时间推进）+ Generation Truth 审计报告（`docs/engineering/tasks/v163-r3-generation-truth-audit.md`，`git add -f`）+（如裁决）迁移脚本与建模变更 + 单位签收记录 + 执行报告（`v163-r3-track-b-execution.md`）。
