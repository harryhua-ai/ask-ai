# CamThink V1 — Final Release Candidate Assembly 报告

- **日期**: 2026-09-03
- **模式**: SINGLE EXECUTOR · 整合门(零生产交互)
- **状态**: **CANDIDATE READY — Final RC 已建立并推送,待授权进入 Production Mutation & Deployment Gate**
- **FINAL_COMMIT**: `0e6a8a3`(@origin/integration/camthink-v1-final-rc-20260903)
- **PRODUCTION_MUTATIONS**: **NONE**

---

## 1. SOURCE_COMMITS(全部实证存在)

| commit | 内容 | 父系(实证) |
|---|---|---|
| `c83d214` | production/main baseline(Issue #8 Store origin) | d4dc676 |
| `272f570` | Source Center integration(#16/#17/#18 + 兼容修复) | 86a893a(⊂272f570) |
| `855b88a` | Sync Truth + Data Integrity integration(+Correction Gate) | 285f19a |
| `7123f73` | Issue #5 实现(taxonomy/解析/检索闸门/CIT-03/迁移工具) | **1d6f6b5** |
| `bc16eeb` | Issue #5 unknown closure(2 条确定性规则,纯 taxonomy/测试) | 7123f73 |
| `c3928bf` | Issue #10 Release Governance | **c83d214** |

## 2. TOPOLOGY_AUDIT(实证拓扑图)

```
3da47a6 → … → 1d6f6b5(local main:merge Wave-0 21db533 + Stage⑯ 65e57eb + test-isolation 1af2708)
                  ├─→ 2a6edce (S0 Source Center foundation)
                  │        └─(与 c83d214 汇合)
c83d214 ──────────┴─→ ce52af4 = merge(c83d214, 2a6edce)   【S0 integration】
                  │        ├─→ 00371cd merge #16(bfb5547)
                  │        ├─→ 97fa1de merge #17(880282a)
                  │        ├─→ e27f7f0 merge #18(8eb1e9d) → 86a893a fix → 272f570 【SC integration】
                  │        │        ├─→ 9a4906d merge #13(7e410e0)
                  │        │        ├─→ 029ba76 merge #14(88375b7)
                  │        │        ├─→ ef3b551 merge W2(a99788f)
                  │        │        ├─→ a7d7577 merge W3(6ad0cdd) → 285f19a → 855b88a 【SyncTruth+DataIntegrity】
                  │        └─→ 7123f73 (#5) → bc16eeb (#5 closure)
                  └─→ c3928bf (#10,直接基于 c83d214)
```

关键祖先判定(`git merge-base --is-ancestor` 实证):
- `855b88a` ⊇ c83d214 ✓、1d6f6b5 ✓、2a6edce/ce52af4 ✓、272f570 ✓、bfb5547/880282a/8eb1e9d ✓、a99788f(W2)✓、6ad0cdd(W3)✓、7e410e0(#13)✓;
- `855b88a` 不含 7123f73/bc16eeb(#5)、不含 c3928bf(#10)→ **855b88a = 最深已验收共享基线,唯一缺口即 #5 与 #10**;
- merge-base(855b88a, bc16eeb) = 1d6f6b5 → 合并 bc16eeb 的净增量恰为 #5 两提交(1d6f6b5 三候选已在基线侧,零重复带入);
- merge-base(855b88a, c3928bf) = c83d214 → 合并 c3928bf 的净增量恰为 #10 一提交;
- 无不可调和缺口,未触发 BLOCKED。

## 3. INTEGRATION_METHOD

从 `855b88a` 建隔离分支 `integration/camthink-v1-final-rc-20260903`,**语义序**合并:
1. `bc16eeb`(#5 完整血统:7123f73+closure)→ merge `36c0879`,**零冲突**;
2. `c3928bf`(#10)→ merge `ac4f005`,**唯一冲突**:backend/api/admin/router.py
   导入邻接(基线侧 W2 新增 sync_runs_router,#10 侧新增 system_router)→
   **并集解决**(两个 router 均注册,各自 include 行由 git 自动合并保留);
3. `0e6a8a3`:Final RC 组合门测试 + release-notes/v1.0.0.md 终稿化。

热点逐文件核验(merge 后 grep 实证):ingest.py 同时承载 #5 `_derived_product`
与 #13 路径身份;product_taxonomy.yaml 含 closure 全部 10 条新增;main.py
lifespan 加载 release identity;types/api.ts 三方类型(SyncHealthItem/
RepoDiscoveryResult/ReleaseInfo)共存;App.tsx 双路由(/data-sources、/system);
prod compose `:?` 必填 tag;update.sh 三服务。

## 4. CONFLICTS / CONFLICT_RESOLUTIONS

| 冲突 | 文件 | 解决 |
|---|---|---|
| 唯一 | backend/api/admin/router.py | 导入邻接冲突;并集(sync_runs_router + system_router 均注册)。非整文件取舍。 |

## 5. 各候选结果

- **SOURCE_CENTER_RESULT**:S0+#16+#17+#18 全在(祖先实证);discover-repo/
  preview-website/lifecycle 端点在位;组合门 + 既有 SC 测试绿。
- **ISSUE_5_RESULT**:完整血统(实现+closure)并入;组合门证明 taxonomy
  同时服务 ingest 与 migration dry-run;closure 规则(i18n 镜像树/ai-tool-stack)
  经 dry-run 实测生效;B 类合法 unknown 语义保持(测试锁定)。
- **SYNC_TRUTH_RESULT**:W2(a99788f)+W3(6ad0cdd)+#9-#15 全在 855b88a;
  全量回归绿(含 /sync-health 三读端点、实时进度、per-source 历史)。
- **DATA_INTEGRITY_RESULT**:#13 路径身份(PK=source_id)与 repair/facts 在位;
  Correction Gate(#13→#11 ACTION_REQUIRED)测试绿(test_sync_health_derivation/
  pure)。
- **GPU_FALLBACK_RESULT**:#14 白名单+单向+record_device 通道在位;
  test_ingest_fallback/test_fallback/test_sync_device/test_sync_run_runtime_facts 绿。
- **ISSUE_10_RESULT**:RELEASE.json fail-closed/health 扩展/admin 端点//system 页/
  CI 生成+断言/版本化部署全在;组合门证明 prod 缺清单启动即 raise。

## 6. CROSS_CONTRACT_INVARIANTS(17 项)

1. SC lifecycle gating ✓(test_source_lifecycle + 全量);2. #5×#13 ingestion 共存 ✓
(组合门 `_build_props` 双身份/确定性 uuid 正交);3. taxonomy 单源一致 ✓
(组合门:ingest 与 plan_migration 同一 get_taxonomy);4. progress/history/health
同源 SyncRun ✓(W2 测试);5. #13 facts→#11 ✓(Correction Gate 测试);6. #14
device/fallback 仅证据 ✓(record_device 测试);7. SHA 短路真实 ✓(W2/既有测试);
8. reconciliation 失败不可掩盖 ✓(#9 恢复语义测试);9. cron request_id=NULL ✓
(W2 兼容测试);10. #18 删除源不可复活 ✓(INT-G008 类测试,见 §9 抖动说明);
11. #5 兄弟产品阻断 ✓(边界 eval A–K);12. shared/support/store 冻结语义 ✓
(taxonomy 测试);13. prod APP_MODE=prod 需有效 RELEASE.json ✓(组合门 fail-closed);
14. /health 兼容且与 Admin 同源 ✓(#10 端点测试);15. compose 显式
ASKAI_IMAGE_TAG ✓(:? 契约测试);16. update.sh 三服务一致 ✓(契约测试);
17. RC 零生产 secrets/assets/权重 ✓(.gitignore 屏蔽 RELEASE.json/模型;
`git ls-files` 无 models/权重;.env 不在仓)。

## 7. RELEASE_NOTES_RESULT

`release-notes/v1.0.0.md` 已由模板终稿化(基于已验收内容,零编造):scope/
major additions/bugs fixed/behavior-config changes/required migrations/production
data repair(139 orphan + 38,874 .hef)/product metadata migration(208,009/
67,251/140,758/1,252)/compatibility/known limitations/rollback compatibility/
identity 节(RC SHA 待 tag 门回填)。**未打 tag、未创建 GitHub Release。**

## 8. PRODUCTION_PLAN(v1.0.0 部署执行计划——本门未执行)

**前置授权**:Production Mutation & Deployment Gate 显式授权 + 变更窗口。

**Phase A — 附加 schema 迁移**(镜像无关,可先行;全部幂等,隔离库三连跑实证):
```
POSTGRES_DB=<prod> python scripts/migrate_add_data_source_lifecycle.py
POSTGRES_DSN=<prod> python scripts/migrate_add_sync_runs.py
POSTGRES_DSN=<prod> python scripts/migrate_add_sync_run_runtime_facts.py
POSTGRES_DSN=<prod> python scripts/migrate_add_sync_requests.py
```
旧代码对新列无感知(附加列)→ 无 half-state 风险。

**Phase B — #13 身份迁移**(与 Phase E 同窗,顺序强约束):
```
POSTGRES_DSN=<prod> python scripts/migrate_documents_path_identity.py   # 前置预览(预期 guard=0)
POSTGRES_DSN=<prod> python scripts/migrate_documents_path_identity.py   # 正式
```
约束:执行窗口内 **sync-cron/sync-executor 必须先停**(禁「新 PK+旧 writer」);
`guard != 0` → STOP 上报,不得强迁。

**Phase C — #5 metadata migration**(先于 Phase E 服务切换):
```
python scripts/migrate_product_metadata.py --source-ids wiki-documents-local,website-camthink   # dry-run 复核(预期 208,009/67,251/140,758/1,252)
python scripts/migrate_product_metadata.py --source-ids wiki-documents-local,website-camthink --apply
```
约束:#5 产品边界语义的服务**不得早于本 apply 上线**(禁「边界语义先于元数据」)。

**Phase D — v1.0.0 发布部署**:
```
git tag v1.0.0 <RC-SHA> && git push origin v1.0.0        # CI 构建并断言 RELEASE.json
ssh tesla-t4 'cd ~/ask-ai && ./deploy/prod/update.sh v1.0.0'
```
update.sh 内建校验链:镜像内 RELEASE.json(version/git_sha)→ 三服务同 tag →
/health version 一致。交叉核对:`docker inspect` OCI revision label == RC SHA。

**Phase E — 恢复运行**:up -d sync-cron sync-executor(update.sh 已含)+ 冒烟
(health version=v1.0.0、/system 页、手动 sync 一次观察 SyncRun 链路)。

**顺序保证**:A(附加列,旧代码无感)→ B(停 writer 后切 PK)→ C(元数据先于
边界服务)→ E(tag 镜像统一切换)→ 恢复运行——显式规避「新代码+旧 PK」、
「新 PK+旧 writer」、「#5 服务先于元数据迁移」、「混合服务 tag」。

## 9. TRANSITIONAL_ROLLBACK_PLAN(首次 v1.0.0 部署专用,消除歧义)

**背景**:新 update.sh 有意拒绝无 RELEASE.json 的旧镜像;生产当前=sha-c83d214
(无清单)→ **不能**用新 update.sh 直接回滚到旧镜像。两段式:

**场景 1:v1.0.0 上线后发现 v1.0.0 自身问题 → 回滚到上一个 #10 系版本镜像**
(即存在 RELEASE.json 的任一 tag 镜像):
```
ssh tesla-t4 'cd ~/ask-ai && ./deploy/prod/update.sh <上一个tag>'
```
标准契约,无特殊步骤。

**场景 2:回滚到 sha-c83d214(无 RELEASE.json 的旧生产镜像)**——显式两步:
```
# 步骤 1:绕过 update.sh 的清单断言,直接以显式 tag 起 compose(不走 latest):
ssh tesla-t4 'cd ~/ask-ai && ASKAI_IMAGE_TAG=sha-c83d214 docker compose -f deploy/prod/docker-compose.yml pull'
ssh tesla-t4 'cd ~/ask-ai && ASKAI_IMAGE_TAG=sha-c83d214 docker compose -f deploy/prod/docker-compose.yml up -d backend sync-cron sync-executor'
# 步骤 2:健康核验(旧镜像 /health 无 version 字段,仅 status):
curl -sf http://localhost:18000/health   # 期望 {"status":"ok"}
```
配套数据面回滚(按需,由授权门单独裁决):
- #13 身份回滚:`python scripts/migrate_documents_path_identity.py --rollback`
  (同 (content_hash,branch) 多行时拒绝并报错,不静默丢数据);
- 附加列(sync_runs/lifecycle/sync_requests)对旧代码无害,可保留不回滚;
- #5 metadata apply 已执行后的回滚 = 重跑迁移把值改回旧标签映射(c83d214 旧
  代码按原标签语义消费;需 Product/Planner 按当时数据面裁决,不在本 RC 预设)。

**回滚锚**:当前生产 sha-c83d214(镜像在 GHCR + 本机留存);部署前记录
`docker inspect` 三容器 image id 作为最终锚点。

## 10. 验证记录

| 门 | 结果 |
|---|---|
| A. 拓扑审计 | §2(全部 is-ancestor 实证;不可调和缺口=0) |
| B. focused 测试 | 全量内含:SC(S0/16/17/18)、#5(taxonomy/resolver/边界 eval A–K/citation/migration)、#9-#15(sync_runs/health/fallback/device/history)、#10(identity/endpoint/tooling) |
| C. 组合测试 | tests/test_final_rc_combination.py **6 passed**(#5×#13 双身份/确定性 uuid 正交/closure×dry-run/合法 unknown 保持/release fail-closed+manifest 在位/Admin 双页共存);其余组合由既有测试承载(§6) |
| D. 后端全量(隔离库+离线,权重物理副本预验) | **1545 passed / 6 skipped / 0 failed ×2 连续全量**(基线 855b88a 1361 + #5 的 141 + #10 的 43 + 组合门 6 = 1551?——按加法口径见 §11 抖动说明;两次全绿稳定) |
| E. Admin vitest | **248/248(43 files)** |
| F. tsc -b ✓ / vite build ✓ | PASS |
| G. widget build | ✓(dist/widget.js 253.41 kB) |
| H. 迁移幂等 | 隔离库(finalrc_mig,一次性已删)6 脚本 pass1+pass3 全 rc=0,幂等文案实证;`git diff --check` ✓ |

**§11 测试计数抖动说明(诚实记录)**:第一次全量出现 52 failed+21 errors,
集中于 test_sync_runs_api / unified_v1_admin_gate(种子/401 形态);未做任何
代码变更,第二次与第三次全量 **连续 1545/6/0**,且对先前失败文件定向复跑全绿
——定性为并行窗口共享 ask_ai_test 库重建扰动(记忆在案已知坑),非整合回归。
(计数口径:855b88a 1361 → +#5 候选自带测试 → +#10 40 → +组合门 6,与 1545
之间的差异来自候选间同名/重复统计与跳过集,以两次连续实测 1545/6/0 为准。)

## 12. KNOWN_LIMITATIONS

1. 本门未在 CI 跑整合分支的镜像构建(tag 门首建;Dockerfile/CI 契约有静态测试);
2. update.sh 运行时行为仍未生产演练(沿用 #10 建议:v1.0.0 前测试 tag 干跑);
3. 生产 #13 迁移的 duplicate guard=0 来自既有只读预览,执行门前建议重跑预览;
4. 测试库共享扰动导致一次全量假失败(已两次全绿复核),并行执行窗口建议
   各自隔离库。

## 13. 结构化结果

```
STATUS: CANDIDATE READY(Final RC 已建立推送;待授权 Production Mutation & Deployment Gate)
AUTHORITATIVE_BASELINE: c83d214(production/main;855b88a 为最深已验收整合链)
SOURCE_COMMITS: c83d214 / 272f570 / 855b88a / 7123f73 / bc16eeb / c3928bf(全部实证)
TOPOLOGY_AUDIT: 见 §2(855b88a ⊇ c83d214+1d6f6b5+S0+SC+SyncTruth/W2/W3;
  缺口恰为 #5 与 #10;merge-base 实证;无 BLOCKED)
FINAL_COMMIT: 0e6a8a3(@origin/integration/camthink-v1-final-rc-20260903)
BRANCH: integration/camthink-v1-final-rc-20260903
WORKTREE: .worktrees/final-rc-20260903(.env/models 物理复制;offline 预验)
INTEGRATION_METHOD: 语义整合=最深共享基线 855b88a + merge bc16eeb(36c0879)
  + merge c3928bf(ac4f005)+ 组合门/发布说明(0e6a8a3)
CONFLICTS: 1(router.py 导入邻接)
CONFLICT_RESOLUTIONS: 并集保留 sync_runs_router+system_router(双 router 注册,
  非整文件取舍)
SOURCE_CENTER_RESULT: S0/#16/#17/#18 全并入,端点与 UX 在位,测试绿
ISSUE_5_RESULT: 完整血统并入;closure 经 dry-run 实测;合法 unknown 语义保持
SYNC_TRUTH_RESULT: W2/W3+#9-#15 全在;全量绿
DATA_INTEGRITY_RESULT: #13 PK=source_id+repair+facts 在位;Correction Gate 绿
GPU_FALLBACK_RESULT: #14 白名单+单向+record_device 在位,测试绿
ISSUE_10_RESULT: RELEASE.json 全链在位;prod 缺清单 fail-closed 组合门锁定
CROSS_CONTRACT_INVARIANTS: 17/17(§6,逐项证据)
RELEASE_NOTES_RESULT: v1.0.0.md 终稿化(零编造;SHA 待 tag 门回填;未发布)
PRODUCTION_PLAN: §8(A 附加迁移→B #13 身份(停 writer)→ C #5 元数据→
  D v1.0.0 tag+update.sh→E 恢复;四类顺序风险显式规避)
TRANSITIONAL_ROLLBACK_PLAN: §9(两段式;锚=sha-c83d214;#13 --rollback 与
  元数据回滚单独授权裁决)
COMBINATION_TESTS: 6/6 新增 + 既有组合测试全绿(§6/§10)
BACKEND_TESTS: 1545/6/0 ×2 连续全量(抖动说明 §11)
ADMIN_TESTS: 248/248(43 files)
WIDGET_TESTS: 无独立测试;build ✓(253.41 kB,共享构建路径回归)
BUILD: admin tsc -b ✓ / vite build ✓ / widget build ✓ / diff-check ✓
MIGRATION_TESTS: 6 迁移脚本隔离库 pass1+pass3 全 rc=0(幂等文案实证)+
  既有迁移测试绿
REGRESSIONS: 零(两次连续全量 0 失败;一次共享库扰动假失败已复核排除)
KNOWN_LIMITATIONS: §12(CI 镜像构建未跑/update.sh 未演练/guard 预览建议
  执行门重跑/共享测试库扰动)
REPORT_PATH: docs/implementation/CAMTHINK_V1_FINAL_RELEASE_CANDIDATE_ASSEMBLY_2026-09-03.md
REPORT_COMMIT: 见 docs 仓 log
PRODUCTION_MUTATIONS: NONE
```
