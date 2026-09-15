# V163_R4_MAIN_PROMOTION_AND_PRE_RELEASE_GATE — Release Integration Report

- 任务:V163_R4_MAIN_PROMOTION_AND_PRE_RELEASE_GATE(Release Integration Executor)
- 日期:2026-09-15
- Role A 组合树终审:**FINAL PASS**(已具备)

## 1–3. 主干晋升与独立远端验证

| 项 | 值 |
|---|---|
| PRE-PROMOTION MAIN(实测 origin/main) | `f4e67515af810840aa10fa800f0203c2ba290df0` |
| ACCEPTED INTEGRATION TIP(origin/integration/v1.6.3-r4-20260915) | `f64397795c7ac4ff84bb2c306c2da238af72db3f` |
| 基线漂移 | 无(fetch 后逐 SHA 相等;ancestry `f4e6751 ⊂ f643977` PASS) |
| 晋升方式 | 专用干净 main worktree(工作树 0 脏项)→ `git merge --ff-only f643977` → 纯快进 |
| push 结果 | `f4e6751..f643977 main -> main`(普通推送,exit 0;无 force/merge commit/squash/rebase) |
| MAIN_AFTER_PROMOTION | `f64397795c7ac4ff84bb2c306c2da238af72db3f`(本地=远端) |

独立远端验证(双通道,不信赖 push 输出):
1. `git ls-remote --heads origin main` → `f64397795c7ac4ff84bb2c306c2da238af72db3f`
2. `gh api repos/harryhua-ai/ask-ai/branches/main --jq .commit.sha` → `f64397795c7ac4ff84bb2c306c2da238af72db3f`
3. `804f98b654e9e8c2d44408ca53bb079672f804ea` is-ancestor of origin/main → **PASS**(另证 `f4e6751 ⊂ origin/main`;本次晋升共快进 38 commits)

## 4. PRE-RELEASE MIGRATION GATE(final main,PLAN VALIDATION ONLY)

`scripts/release_migration_plan.py --tag v1.6.3-r4 --sha f643977…`:

- **exit 0**;manifest JSON 解析正常
- **恰 9 条**:既有 6 条原序原样保留(site_launcher_presentation、p1_lifecycle_foundation、track_c_product、sync_delta_counts、frontmatter_slug_property、conversation_id_policy)+ 3 条新登记
- `migrate_add_membership_currency.py`(#71)= 恰 1 次;`migrate_remove_contaminated_version_chunks.py` 与 `migrate_add_sync_request_kind.py`(#75)= 各恰 1 次
- 无意外条目、无缺失登记;9 个脚本文件全部在树内
- **未执行任何迁移**(组合树阶段已在本地 scratch 库实证三新迁移 upgrade+重跑幂等,见集成报告)

MIGRATION_PLAN = **PASS**

## 5. #76 ADMIN BOOTSTRAP PRE-FLIGHT(READ-ONLY 生产检查)

方法:SSH 只读进入生产(host 43.132.189.162);从 `tesla-t4-backend-1` 容器环境读取 ADMIN_EMAIL 配置态(未回显值);对 `tesla-t4-postgres-1` 仅执行 SELECT 计数;未创建/重置任何账号、未打印任何凭证。

- 生产 ADMIN_EMAIL:容器未显式配置 → 代码缺省身份生效(`backend/main.py:204`)
- 该身份用户存在数 = **1**,且 role = admin;全库 admin 总数 = 1
- 生产现运行 `ghcr.io/harryhua-ai/ask-ai:v1.6.3-r3`(healthy)——r4 未部署,r4 上线时 `_ensure_admin_user` 将走"已存在 → preserved,不动凭证"分支

**ADMIN_EXISTS = YES**
**ADMIN_BOOTSTRAP_SECRET_REQUIRED = NO**(既有 Admin 原样保留,启动不要求 ADMIN_PASSWORD;亦不得配置弱回退)

## 6. PROJECT AUTOMATION PRE-FLIGHT(#79,READ-ONLY)

`gh project field-list 2 --owner harryhua-ai`(Project 2,PVT_kwHOAgcvyM4Bisg3):

- **Sprint 字段:不存在 = ACCEPTED**(#79 冻结语义;绝不恢复)
- **Iteration:存在**(ProjectV2IterationField)✓
- **Priority:存在**(SingleSelect)✓
- **Status:存在**(SingleSelect)✓
- main 已含接受实现:`tests/project_automation/test_sprint_dependency_removed.py`、`test_schedule_iteration_boundary.py` 在树;`scripts/project_automation/model.py` sprint 提及 = 0
- 本任务未做任何 live sync/reconcile 写操作

PROJECT_SCHEMA = **PASS**

## 7. #77 生产运营 RUNBOOK(PLAN ONLY — 本任务不执行)

前置授权:以下第 1 步涉及生产数据源配置变更、第 5 步涉及矫正写,均须部署完成后另行授权。

1. **排除目录变更**(授权后):neomind-local 连接器 `exclude_dirs += ["eval"]`(Admin 数据源详情页配置面)。
2. **权威成员枚举**:触发/等待下一轮 GitHub 同步——r4 后成员对账以 GitHub 权威成员集为准,eval/** 不再入库(fetch 排除)+ 已在服者成为"账本在服成员 − 权威成员"的陈旧项。
3. **CorpusRepair plan**:`CorpusRepairTool.plan`(membership 口径)→ 产出 `RETIRE_DELETED_DOCUMENT` 操作清单(目标 = neomind-local 下 eval/** 陈旧在服对象)。
4. **人工只读评审**:逐条核对 plan 清单 = 预期 eval 文件集合,且不包含任何非 eval 路径(此步骤为冻结的 human gate,不得跳过)。
5. **apply**(授权后):执行退休;墓碑提交,不物理删除。
6. **验证**(只读):
   - Weaviate/PG:source_id 前缀 `neomind-local` 下 `eval` 路径的在服 chunk 数 = 0;
   - 邻接有效内容仍 SERVING(neomind-local 非 eval 文档的 chunk 数与退休前一致);
   - Admin 数据源健康面显示成员货币真值更新,无未解决漂移残留。

## 8. #71 POST-DEPLOY ACCEPTANCE PLAN(只读检查,部署后执行)

1. 下一轮 GitHub 源同步(或显式授权的一次 reconcile)后,只读 SQL:
   - `SELECT membership_status, membership_checked_at, membership_stale_detected, membership_stale_retired FROM data_sources WHERE type='github'` —— 各 GitHub 源真值已持久化且 checked_at 为新轮时间;
   - 与 `gh api` 实时枚举的该源成员集比对:无成员漂移时 `membership_status=current`;人为构造漂移仅在测试库做,生产不注入。
2. 陈旧退休:对存在"账本在服 − 权威"差的源,验证退休墓碑计数 = `membership_stale_retired`,且在服集合收敛到权威集。
3. 持久化失败不谎报 current(代码契约,生产只读验证其表现):若某源对账事务失败,其 `membership_status ≠ current` 且 Admin SourceHealthPanel 呈现未解决/降级真值(不显示 current)。
4. Admin 只读面:DataSourceDetail 健康分区显示货币真值与上述 SQL 一致(截图留证)。

## 9. #72/#75 POST-DEPLOY RUNTIME PROBES(PLAN ONLY — 部署后按授权执行)

A. **422 族(客户端切批)**:选一文档量 ≥ 60 的源执行授权重建;期望嵌入请求序列恰为 `16+16+16+16+14`(78 chunks 代表值;批大小 = Settings 缺省);backend 日志零 `422`,嵌入遥测 attempts=1/文档代;嵌入端点对 >16 的服务端拒绝契约不受影响(测试库已证,生产不注入)。
B. **413 族(超契约残留)**:对存在超限持久 legacy chunk 的源触发修复轮;期望:超契约 chunk 不被截断重放,修复面路由 `unrepairable → 源重建`(sync_requests `kind=rebuild`,任务终态 `rebuild_requested`);日志零 `413`。
C. **交互(413 修复 × 422 切批)**:force-rebuild / repair 路径 >16 chunks:经 `--reindex` P1-E 路径重建成功,既无 413 亦无 422;`test_generation_builder.py` A/B/C 三路径为同款契约回归锚。

## 10. #78/#77 POST-DEPLOY RECALL/EVIDENCE ACCEPTANCE PLAN

只读真实查询(生产问答面只读探测,延后至 post-deploy gate 执行):

1. **权威用户面召回**(原双锚点失败案例):shipping/support 类问题(如运费政策、contact us)→ 期望权威用户面 chunk 进入召回并胜出(此前 control chunk rank29 不入池)。
2. **company/contact/support**:company 站问答返回官方权威内容,引用为 wiki 面。
3. **code-oriented 保序**: Woo/symbol 等代码向查询仍返回代码证据(code 竞争序,#77 R2-B1 门控)。
4. **普通问题证据优先级**:非代码问题证据组合以用户面权威类优先,兜底序不覆写 rerank 拒答裁决。
5. **fixture 排除**:#77 运营 runbook(第 7 节)执行后,eval/** 不再出现在任何证据/召回结果。

执行边界:全部只读;真实流量观测优先,注入式探针不在生产执行。

## 11. #80 BOUNDARY

- main(f643977)文件差集中 **无任何** GTM/GA4/analytics/CTA 文件(逐名 grep 实证)
- 未 cherry-pick 任何 #80 分支内容;#80 保持独立(DISCOVERY PARTIAL / implementation authorized = NO)
- r4 核心树冻结于 f643977;#80 late-add 须 Role A 另行显式授权

## 12. PRE-RELEASE VERDICT

| 门 | 结果 |
|---|---|
| 主干晋升(精确 + 独立双通道验证) | PASS |
| 基线漂移 | 无 |
| 迁移计划门 | PASS |
| #76 Admin 预检 | 已知且安全(YES/NO 态) |
| Project schema 预检 | PASS |
| 部署后验收/runbook | 已备(第 7–10 节) |
| 未授权生产变更 | 无 |

**V163_R4_PRE_RELEASE_GATE = PASS**(本判定不授权创建 tag)

## 13. MUTATION BOUNDARY CONFIRMATION

- TAG_CREATED = NO;RELEASE_CREATED = NO;DEPLOYED = NO;PRODUCTION_MUTATION = NO
- 生产仅只读 SSH SELECT 与容器状态查看;GitHub Project 仅 field-list 读取
- 本报告提交为 main 上唯一的后续 commit(docs-only);**MAIN_AFTER_REPORT 见下**(若与本节上方 tip 不同)
- 不为报告 commit 创建任何 tag
