# ASK-AI v1.0.1 — Production Stabilization Integration Report

- 日期:2026-09-04;Executor:B(Senior Engineering Executor)
- baseline:v1.0.0 = **0e6a8a3bb72932b26fcf500954aacfe109373133**(origin/main 实查一致,未前进,无 reset 需要)
- **v1.0.1 RELEASE CANDIDATE:`v1.0.1/integration-candidate` = 3cf42da**(已推 origin)
  - merge 2a99b2a = Track A(#19)9bc7ea2
  - merge 3cf42da = Track C(#20+#21)54100d8
  - Track B(#13+#14)= verification-only 零提交(证据报告另附)

## 依赖分类(Phase 1 审计结论)

| 组合 | 分类 | 依据 |
| --- | --- | --- |
| A×B | NONE | A 独占 rag.py/search.py/woocommerce.py/user_messages.py;B 面在 embedder/*/scripts/sync.py(rag.py 无 embedder 引用,实查) |
| A×C | NONE | C 面在 config.py/api/admin/sync_runs.py/迁移脚本;与 A 无交集 |
| B×C | **FROZEN INTERFACE** | W2 `record_device` 受控词表(execution_device/fallback_reason)与 sync 维事实:B 为写方、C 为读方,双方均未改词表(只改健康聚合),接口冻结保持 |
| 测试设施 | 共享只读 | 各 worktree 独立跑,无交叉写 |

三次合并(2×--no-ff)**零冲突**。

## 组合回归(实跑,集成树 3cf42da)

- 全量后端:`pytest tests/ --ignore=tests/e2e` → **1563 passed,3 skipped,0 failed(46.5s,离线 HF)**
- 覆盖对照任务清单:①各 track 验收套件 ✓(781/64+42/245 分项见 track 报告)②既有回归全量 ✓ ③#5 exact 正确性回归 ✓(boundary/retrieval/taxonomy 全绿)④#19 comparison 用例 ✓(新增 12 断言面)⑤ingest 一致性回归 ✓(ledger_identity/reconcile/repair)⑥低资源/GPU 回退回归 ✓(embedder 42)⑦Knowledge Health 语义回归 ✓(pure 矩阵+derivation)⑧迁移/配置安全 ✓(DSN 守卫+grep 守卫)⑨应用构建/启动 ✓(1563 含 lifespan smoke;另 `import backend.main` FastAPI 构建通过)
- lint:ruff/black 于三 track 自有变更文件 clean(基线既有 B008/F841 不动,最小 diff 纪律)

## Known risks

1. comparison 查询检索成本 ×n(n=目标数,当前≤2)——正确性优先,延迟回 #23;
2. D-preflight 文案在「prune 剔净某侧」极小概率场景表述为「暂未找到」(与最终上下文一致);
3. B 型模型零内容的 provider 侧机制未定(v4-flash 混合推理?);已可观测(reason=model_empty_stream),若复发走 provider 观测/换模型链路;
4. 商店元数据迁移执行前,store/ne301 页仍为 aitoolstack 旧标 —— comparison 在迁移前已可用(per-target 检索下该页属平台桶仍可入 NE301 侧候选),迁移只是收紧设备身份精度。

## Production migration/config actions required(独立授权门)

| 项 | 内容 | 时机 |
| --- | --- | --- |
| A. 商店设备身份元数据迁移 | `scripts/migrate_store_device_metadata.py --source-ids woocommerce-mall`(dry-run→人工核对映射→--apply;原位属性,零 re-embed,预计 ≤40 chunk) | v1.0.1 部署后任意窗口(向后兼容) |
| B. 生产 .env 移除 `TEST_DATABASE_URL`(行 40) | 显式生产配置变更门;守卫已使残留无害化,移除属卫生收尾 | 独立配置变更授权 |
| schema 迁移 | **无**(v1.0.1 零 schema 变更) | — |

## Deployment prerequisites / Rollback / Smoke plan

- 部署:CI tag 出镜像 → `deploy/prod/update.sh v1.0.1`(既有 #10 契约:RELEASE.json 断言+三服务同 tag);sync-executor 必随 update.sh 同批(该脚本已含)。
- 回滚:`update.sh v1.0.0`(同一契约整体回退;#20/#21 为纯代码语义,#19 的商店迁移在回滚后亦向后兼容——旧代码按现标签过滤,aitoolstack 平台桶仍合格)。
- 部署后 smoke(建议清单):①对比查询 NE302 vs NE301(期望 comparison 分节答案/双侧 sources;若商店页未迁移仍不得 service_unavailable)②单产品 #5 回归组(NE101/NE301/NE503/NG4500)③歧义指代→澄清 ④Admin Source Health:neoruntime-apps/website 最新成功运行下非 Severe、30 天率显示为历史参考 ⑤生产 .env 含 TEST_DATABASE_URL 时迁移脚本拒绝(负例冒烟,可选)。
- Issue 生命周期建议:#19/#20/#21 待 Planner 据本候选 FINAL REVIEW 后 close;#13/#14 已 CLOSED,本 track 证据报告归档即可。

## PERFORMANCE_QUICK_WIN_CANDIDATE(§7)

本轮未发现满足全部门槛(强证据/小改动/实质降 TTFT/零契约风险)的候选。观察一项供 #23 通道参考:comparison per-target 检索使检索成本 ×n(本 release 正确性设计使然,非可回退项)。
