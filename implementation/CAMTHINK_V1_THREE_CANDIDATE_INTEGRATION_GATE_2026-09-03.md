# CAMTHINK V1 — THREE-CANDIDATE INTEGRATION GATE 报告

- 日期:2026-09-03
- 执行:SINGLE EXECUTOR(集成门,零新功能)
- **STATUS: CANDIDATE READY**
- **BASELINE: `269cadb0ce6a3ce47059e0f4b074f356e41612eb`**(执行前实测 origin/main 一致)
- **FINAL_INTEGRATION_COMMIT: `1d6f6b5fe697b5f7a1b8decef1c29f51afcda937`**
- INTEGRATION_BRANCH: `integration/camthink-v1-accepted-candidates-20260903`(已推 origin,远端哈希核验一致)
- WORKTREE: `.worktrees/integration-camthink-v1-20260903`
- **PRODUCTION_ACCESS: NONE**

## Candidates(三个独立 FINAL PASS 血统)

| 候选 | tip(全 SHA) | 内容 |
| --- | --- | --- |
| A Wave-0 共享可观测核心 | `21db533dee75fb078baf65a6c28a49b7117861a6`(269cadb→6715e2c→21db533) | SyncRun=ONE SOURCE×ONE ATTEMPT;请求→运行→日志确定性链路;身份部分唯一索引;SAFETY_FILTER 可观测;终局一致性事实;retention 30d |
| B Stage⑯ 生成失败/本地化 | `65e57ebe96f04e5408a2d0fdcfe79fd22b6f7504`(269cadb→7912ccc→65e57eb) | 权威应答语言解析(zh/en);本地化失败/拒答/无证据文案;Budget Declined 真实持久化且失败不下发幽灵 id;complete 缺 language 回退权威前置值;Admin outcome 分类;widget SSE 本地化 |
| C 测试隔离与夹具性能闭环 | `1af2708e555001571600c724f624102c772aa57a`(269cadb→edcf98d→1af2708;1af2708 全 SHA 已解析) | HF env 精确恢复(函数级+module 级);无不受控下载;真实 BGE 保持真实;bcrypt 优化不 mock 语义;crawl/filesystem 时间确定性;module 级 BGE 实例复用;无 xdist、零覆盖缩减 |

## TOPOLOGY / OVERLAP / CONFLICTS

- 三候选均为 269cadb 的 2 提交线性血统;文件数 A=8 / B=18 / C=6;
- **文件级交集 = 空**(两两 uniq -d 无输出);函数/迁移/import 面无隐藏重叠(B 改 routes/rag/utils+前端,A 改 sync 域,C 只改 tests);
- 集成方法:**三次 `git merge --no-ff`**(458cee3 吸收 A → 895a3fe 吸收 B → 1d6f6b5 吸收 C),完整保留三段已验收提交与 lineage,零 squash、零 cherry-pick 重写;
- **CONFLICTS: NONE;CONFLICT_RESOLUTIONS: 不适用**(零冲突,无需任何语义裁决)。

## Gate 结果

### Gate 1 Commit/Scope Integrity — PASS
集成 tip 为 269cadb 后代(merge 链);三 tip 全部为祖先(`git merge-base --is-ancestor`);diff 组成恰为三候选文件并集(8+18+6,零额外文件);无任何被回退的已验收改动、无无关功能引入。

### Gate 2 Wave-0 Regression — PASS
SyncRun 核心+集成 28 绿;身份唯一索引(重复三元组 IntegrityError、NULL 直跑多次合法)绿;迁移幂等+索引在位绿;request→run→log 链路绿;阶段⑩ recovery 全文件、F16 golden、W6 golden、Technical Safety(ingest_safety+safety)、504 Golden 全绿(含于定向电池 725 passed/3 skipped)。

### Gate 3 Stage⑯ Regression — PASS
`test_failure_localization.py`+`test_reliability.py`+`test_unified_v1_gate.py`+`test_rag.py` 全绿(含于定向电池);Admin outcome 分类与 widget SSE 本地化行为由前端测试覆盖(Admin 190/190、Widget 72/72,含 `outcome.test.ts` 与 `useSSE.test.ts`)。

### Gate 4 Test Isolation / Performance — PASS(含环境证据分类)
HF 函数级/module 级隔离、bare-env sentinel、filesystem/crawl 确定性时序、auth hash/verify 全绿(含于定向电池+全量);真实 BGE 用既有本地缓存(models/ 6.4G,含 bge-m3 与 bge-reranker-v2-m3 仓)。**性能实证:全量套件 82s→31s(C 的夹具闭环兑现)**。
**环境证据(如实分类)**:`tests/embedder/test_bge.py` 4 用例离线 ERROR(reranker 仓虽在缓存但离线解析不可用)——已在两处独立复现:①冻结基线 269cadb 同环境同 4 失败;②**Candidate C 已验收 tip 1af2708 同环境 20 passed/4 errors(临时 detached worktree 实测后即删)**。非集成引入;按任务纪律未下载权重、未隐藏。

### Gate 5 Frontend — PASS
Admin: `vitest run` 36 文件 **190/190**;`npm run build`(tsc -b && vite build)成功。Widget: **72/72**;`vite build` 成功(dist/widget.js 253.41 kB)。依赖经 `npm ci` 确定性安装于集成 worktree(不共享主仓 node_modules)。

### Gate 6 Backend Broad Regression — PASS
**1112 passed / 6 skipped / 4 errors / 31.46s**(离线隔离:`TEST_DATABASE_URL` 指本地测试库,`HF_HOME=<repo>/models + HF_HUB_OFFLINE=1 + TRANSFORMERS_OFFLINE=1`,venv Python,无 xdist)。4 errors=Gate 4 环境证据(基线与 C tip 双重复现)。相对基线/候选证据**零新增失败**;测试总数 1112+4+6=1122=基线 1072+A 25+B/C 增量 25。

### Gate 7 Static Quality — PASS(基线债如实分类)
- ruff:候选**新增** 7 个 py 文件 **All checks passed**;16 个两树共有文件 23 项发现与基线 269cadb **逐项一致**(基线既有,不扩 scope 清理);
- black:3 文件(conversations.py / conftest.py / test_rag.py)不合规——**三者在不合规状态于基线即存在**(基线同验复现),候选与集成均未新引入。

## MIGRATION_VERIFICATION

本地测试库实测(显式脚本):`migrate(engine)` 连续两次 → `OK: sync_runs 就绪(17 列,身份索引在位,幂等迁移完成)`;部分唯一索引在位;重复 (request,source,attempt) 插入被 IntegrityError 拒绝;NULL 直跑两次合法。**未触生产**(PRODUCTION_ACCESS=NONE)。

## BASELINE_EXISTING_FAILURES / NEW_REGRESSIONS

- 基线既有:embedder 4 errors(离线缺 reranker 解析,双重复现取证,见 Gate 4);ruff 23 项与 black 3 文件(基线即然);
- **NEW_REGRESSIONS: NONE**。

## KNOWN_LIMITATIONS

1. embedder 4 用例在本机离线环境不可跑绿;要绿需补齐本地缓存中 reranker 仓的完整快照或联网(=不受控下载,被本门禁止)——留环境治理项,非集成缺陷;
2. 集成树 frontend 依赖以 `npm ci` 装于 worktree 本地(node_modules 不入库不共享);
3. 集成分支未合 main、未打 tag、未部署——等待 Planner 裁决。

## PRODUCTION_ACCESS

**NONE。** 无 SSH、无生产 DB/迁移/部署/流量/语料/密钥触碰。
