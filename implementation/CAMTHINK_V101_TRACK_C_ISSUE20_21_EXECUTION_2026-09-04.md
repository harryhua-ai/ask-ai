# v1.0.1 Track C — Issues #20 + #21 执行报告

- baseline:0e6a8a3;branch/worktree:`v1.0.1/track-c-ops-health` @ `.worktrees/v101-track-c-ops-health`
- **STATUS:CANDIDATE READY**;commit:**54100d8**(已推 origin)

## Issue #20 — 迁移工具生产 DSN 安全(永久守卫)

根因确认:`scripts/migrate_add_data_source_lifecycle.py` 以 `os.environ.get("TEST_DATABASE_URL") or load_settings().postgres_dsn` 直读环境(v1.0.0 门曾以逐调用 `TEST_DATABASE_URL=` 中和)。生产 .env 残留该变量时,无守卫调用会静默指向 127.0.0.1:15432 测试库。

实现(最小面 + 防复发):
1. `backend/config.py` 新增 `resolve_migration_dsn(settings=None)`:`APP_MODE=prod` 且环境携带 `TEST_DATABASE_URL` → **RuntimeError 硬拒绝**(误路由生产迁移 > 任何静默回退,恢复=取消变量);非 prod 沿用测试库对齐惯例;未设置回落权威生产 DSN。与既有 `_validate_prod_secrets` 同一 APP_MODE 判定惯例。
2. 上述脚本改为经守卫解析(唯一裸读者;其余迁移脚本本就走 load_settings,已安全)。
3. **grep 级守卫测试**:任何 `scripts/migrate_*.py` 出现 `TEST_DATABASE_URL` 而未经 `resolve_migration_dsn` → 测试失败(防未来脚本重引裸读)。
4. 行为测试矩阵:prod+TEST=拒 / dev+TEST=测试 DSN / 无 TEST=stub 权威 DSN / prod 无 TEST=正常。
5. 生产 .env 残留变量本身的移除:**不在本 track**(需独立生产配置变更门,见集成报告 Prerequisites);守卫使该残留不再危险。

## Issue #21 — CURRENT Knowledge Health ≠ Historical Reliability

根因(实码):`_overall_health` 将 30 天历史成功率(sync_state,critical→ACTION_REQUIRED/degraded→DEGRADED)纳入 worst-of —— cuda_oom 时代失败把已恢复源钉死在 Severe;同时 `_connectivity_dim` 把最新 run 在非连接相位(EMBED 等)的失败读成 `ok`(当前性失败漏报)。

实现(语义分离,不删历史):
1. `_overall_health`:移除 sync_state 对 ACTION_REQUIRED/DEGRADED 的驱动;30 天率保留为**参考维度**(evidence 注「历史参考」);当前性失败仍由 connectivity(latest run)/consistency(latest facts)如实呈现;insufficient_data(证据不足)映射保持。
2. `_connectivity_dim`:latest run 失败于非连接相位(如 EMBED 资源)→ `degraded`(细分由 fallback_reason/error_summary 承载);DISCOVER/FETCH=failed、PARSE=degraded 不变。
3. GPU→CPU 成功回退=业务成功运行 → connectivity ok → 不影响当前健康(符合冻结语义)。

## 测试(实跑)
- pure 矩阵:恢复源历史 critical → **HEALTHY**;回退成功 → HEALTHY;connectivity failed / consistency degraded → ACTION_REQUIRED 不变;EMBED 失败 → degraded;sync 维 evidence 含「历史参考」。
- DB-backed derivation 套件 + 全 admin:**245 passed**;DSN 守卫 5/5;focused 14/14;ruff clean(自有文件)。

## Scope audit / 生产影响
admin 前端零变更(W3 起健康权威在后端响应,维度渲染泛化);无 schema/无迁移;生产效果:neoruntime-apps/website 等已修复源在最新成功运行下将不再显示 Severe,历史失败率仍在维度中可见。
