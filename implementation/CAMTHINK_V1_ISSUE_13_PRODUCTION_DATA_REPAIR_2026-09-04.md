# CamThink V1 — Issue #13 Production Data Repair Mutation Gate 执行报告

- 日期:2026-09-03T23:53Z → 2026-09-04T00:10Z(UTC)
- 生产版本:v1.0.0 / 0e6a8a3bb72932b26fcf500954aacfe109373133(全程未变)
- 授权:显式用户授权,frozen 范围 = A(neoruntime-apps .hef 退休)+ B(website-camthink 5 行收养),仅此两源
- **STATUS:PRODUCTION REPAIR ACCEPTED**
- **UNAUTHORIZED_MUTATIONS:NONE**

---

## 0. 授权对照

| 冻结项 | 实际执行 | 一致 |
| --- | --- | --- |
| A. apps 退休 5 个 .hef / 60,394 vectors / 删 3 账本行 / 2 孤儿无行可删 | plan 5 条/60,394ch(3 ledger-bearing + 2 orphan-only);applied 8 动作 = 5 向量批(10,760+10,760+10,760+7,590+20,524)+3 行删除;0 skipped 0 failed | ✓ |
| B. website 收养 5 行 / 零向量删 / 零 embed | applied 5 ledger-row INSERT,0 failed;向量零触碰(前缀 366 与总数前后不变);无 embed 调用(_NoEmbedEmbedder 在场) | ✓ |
| 不动 105 对 D2 / 其它 13 源 / 不 reindex / 不迁移 / 不部署 | final dry-run:apic 103 REPORT + sdks 2 REPORT 原样;13 源 0 条目;全流程无 reindex/sync/DDL/重启 | ✓ |

## 1. PRE-MUTATION GUARDS(§1 全过,2026-09-03T23:53Z)

- 三服务 image=`ghcr.io/harryhua-ai/ask-ai:v1.0.0` 且 /health={ok,1.0.0,0e6a8a3…,production};运行中 backend OCI revision=0e6a8a3 精确
- documents PK=PRIMARY KEY (source_id);duplicate source_id=0;ledger=11,933
- active sync_runs=0;pending/running sync_requests=0(23:38 tick 已于 Run 299 完成,处于 tick 间空闲)
- fresh dry-run(镜像内官方 CLI):
  - apps:`RETIRE_UNSAFE_ARTIFACT=5,total=60,394,ledger-bearing=3(person-detection 10,760/hailo_yolov8n 7,590/yolov8s_pose 20,524),orphan-only=2(person_vehicle_v1 10,760/person_v1 10,760),路径逐条与冻结集一致`
  - website:`REBUILD_ORPHAN_LEDGER_ROW=5,total=5(product、product/ne301、register、solutions/infrastructure-monitoring、tools),无 retire 条目`
  - **与冻结授权语义相等,零漂移 → 放行**
- pre-repair 向量计数:apps 前缀=60,675;website=366;全库=208,009

## 2. BACKUP / RECOVERY ANCHOR(§2)

- DB 备份:`~/ask-ai/backups/pg_askai_pre_repair13_20260903T235340Z.dump`(pg_dump -Fc,6,455,608 B,**sha256 `be2e86e110aa62582fdf11041c331d69c8b94cbbeedc2e0aa73186a685bc08cf`**,PGDMP 魔数 OK,pg_restore --list 20/20 TABLE DATA)
- 计划存证:`backups/repair_apply13_20260903T235354Z/` = fresh_*.json(两源冻结 plan)、**targets_with_uuids.json**(authentic `CorpusRepairTool.plan()`+`_deterministic_uuid` 逐条 chunk_indices+uuid 样例,60,394 个目标全枚举)、apply_*.json(双 JSON:plan+apply-result)、final_*.json(15 源 post-apply)
- Weaviate 快照:未创建(生产无既有安全快照流程,按授权不作新风险引入);向量侧回收证据 = 计划 JSON + 前缀计数 delta(§4)

## 3. WRITER-STOP WINDOW(§3)

- **stop:2026-09-03T23:53:29Z**(sync-cron + sync-executor;backend 未停,持续服务)
- 复验:active runs=0、pending requests=0、dup=0、ledger=11,933(与复核门一致,写者冻结期内零漂移)
- **resume:2026-09-04T00:06:20Z**(12m51s;`docker start` 同容器同镜像,非 recreate)

## 4. APPLY — neoruntime-apps(§4)

- 命令:`python scripts/repair_corpus.py --source neoruntime-apps-1eea74dd --apply`(v1.0.0 镜像内;无 --check-source;同进程 plan→apply)
- 23:57:04Z→23:57:40Z(36s);apply 时进程内 plan = 5 条/60,394ch(=冻结)
- 结果:**applied=8(5 向量批 + 3 ledger-row),skipped=0,failed=0**;本源无 D2 条目(0 skip 属预期)
- 独立核验:
  - apps 前缀向量 60,675→**281(Δ=−60,394 精确)**;website 前缀 366 不变;全库 208,009→**147,615(Δ=−60,394 精确)**
  - 3 个 ledger-bearing .hef 行 absent;2 个 orphan-only .hef 路径 ledger 零行(从未有)
  - ledger 11,933→**11,930(Δ=−3 精确)**
  - 非目标零误伤:全库 delta 恰等于授权目标数,无其它前缀变化

## 5. APPLY — website-camthink(§5)

- 命令:`python scripts/repair_corpus.py --source website-camthink --apply`;23:58:53Z→23:59:07Z(14s)
- 结果:**applied=5 ledger-row,skipped=0,failed=0**;无 delete_many、无 embed(_NoEmbedEmbedder 兜底)
- 核验:5 行落地(product、product/ne301、register、solutions/infrastructure-monitoring、tools;chunk_count=1;content_hash/product 均自向量 props 派生,`product/ne301` 正确派生 product=ne301,其余 unknown=契约保守);Weaviate 总数前后不变;ledger→**11,935**;dup=0
- repeat dry-run:该 5 路径不再出现 orphan 候选(仅余 D2 REPORT,见 §6)

## 6. D2 SAFETY PROOF(§6)

- 已知跨前缀对 `0cb4ff1daf5f…`:**2 行均在**
- ne503-apic:ledger 1,399 行原样;final dry-run 仍= **103 REPORT_DUPLICATE_IDENTITY**(零变异)
- neoruntime-sdks:ledger 192 行原样;**2 REPORT** 原样
- **合计 105 对 D2 接收零变异**;无任何 duplicate-content cleanup 发生
- 新呈现(合法、非变异):website 收养后出现 2 组 REPORT——`8d9bbcfe…`×5 行(product/product-ne301/register/tools 与既有 product-category/ai-cameras/ne503 同内容,通用模板型页面)+ `7ee4989a…`×2 行(infrastructure-monitoring 与既有 security-monitoring 同内容)。REPORT-only,按 D2 合法共存保留。

## 7. POST-REPAIR CONSISTENCY(§7)

Authentic `verify_source_vectors` 全 15 源矩阵(写者停窗内执行):

```
15/15 源:missing=0 | orphan_docs=0 | orphan_chunks=0 | polluted(pending verdict)=0
TOTAL:missing=0 orphan_docs=0
```

- Weaviate:**208,009 → 147,615**(=冻结预期);website 收养不改向量数(✓ 前后 147,615)
- ledger:**11,933 → 11,935**(−3 +5,=冻结预期)
- 零未解释 delta

## 8. KNOWLEDGE HEALTH ACCEPTANCE(§8)

恢复写者后首个自然 tick(00:06:20 起,~3 分钟完成,15/15 completed、无变更跳过)刷新的 per-source consistency facts:

- **neoruntime-apps:orphan_count=0、polluted_artifact_chunks 字段不再出现(零污染)、repair_required=false** —— 不再因污染 ACTION_REQUIRED
- **website-camthink:orphan_count=0、repair_required=false** —— 不再因孤儿一致性 ACTION_REQUIRED
- 其余 13 源全 0/false;无任何源获得 missing
- 残余 D2 事实(105+2+2 组)按 Correction Gate 语义为信息性,**不产生 degraded**
- 唯一非活跃残留:已退源 `ne503-sdk-local` 的陈旧 sync_runs 行(orphan=1)——该源不在 data_sources、账本/向量双侧无残留,纯历史记录,零健康影响
- (Admin token 化页面核验不可行同前:凭据不在执行端;以上为 health 派生的权威输入事实)

## 9. RESTORE WRITERS / FINAL STATE(§9/§10)

- resume 00:06:20Z;executor 启动对账干净(finalized_done=0,无 interrupted);首个自然 tick 全 completed
- 服务:`tesla-t4-{backend,sync-cron,sync-executor}-1` 全部 `v1.0.0`,无混版;backend healthy(**连续 up 7h+,全程未被重启/重建**);/health 身份精确
- final dry-run(15 源):**apps=0 条目;website=2 组 REPORT(合法);apic=103 REPORT;sdks=2 REPORT;其余 11 源 0** —— 无任何 actionable 修复条目残留

## 10. ISSUE #13 完成契约(§11)

- 精确范围已执行 ✓;missing=0 ✓;actionable orphan=0 ✓;polluted artifact=0 ✓;repair_required=false ✓;D2 合法共存保全 ✓;自然同步健康 ✓;零回归 ✓;零未授权变异 ✓
- **ISSUE_13_COMPLETION_RECOMMENDATION = READY_TO_CLOSE**(Planner 拥有最终 closure;执行端不自行关单)

## 11. 返回字段(§12)

```
STATUS                              = PRODUCTION REPAIR ACCEPTED
AUTHORIZATION_USED                  = FULL(仅 A+B 两源;冻结集外零触碰;无扩权)
PRODUCTION_RELEASE                  = v1.0.0 / 0e6a8a3bb72932b26fcf500954aacfe109373133(全程未变)
PRE_REPAIR_STATE                    = PK=source_id;ledger 11,933;dup=0;active sync=0;Weaviate 208,009(apps 60,675/website 366);fresh plan=冻结集零漂移
FRESH_PLAN_APPS                     = RETIRE_UNSAFE_ARTIFACT×5 / 60,394ch(3 ledger-bearing+2 orphan-only,路径逐条相等)
FRESH_PLAN_WEBSITE                  = REBUILD_ORPHAN_LEDGER_ROW×5 / 5ch(product,product/ne301,register,solutions/infrastructure-monitoring,tools)
BACKUP_ANCHOR                       = pg_askai_pre_repair13_20260903T235340Z.dump(sha256 be2e86e1…,20/20 表)+ repair_apply13_20260903T235354Z/(fresh plans+targets_with_uuids.json 60,394 目标枚举+apply results+final 15 源)
WRITER_STOP_WINDOW                  = 2026-09-03T23:53:29Z → 2026-09-04T00:06:20Z(12m51s;含 apply+验证+final dry-run;backend 未停)
APPS_REPAIR_RESULT                  = applied 8(5 向量批+3 行删),skipped 0,failed 0;36s
APPS_VECTOR_DELTA                   = −60,394(前缀 60,675→281 精确;全库 208,009→147,615 精确)
APPS_LEDGER_DELTA                   = −3(11,933→11,930)
WEBSITE_REPAIR_RESULT               = applied 5 ledger-row,skipped 0,failed 0;14s;零向量操作零 embed
WEBSITE_VECTOR_DELTA                = 0(前缀 366、全库 147,615 前后不变)
WEBSITE_LEDGER_DELTA                = +5(11,930→11,935)
D2_PRESERVATION                     = 已知对 2 行在;apic 1,399 行+103 REPORT、sdks 192 行+2 REPORT 零变异;合计 105 对零触碰;新增 website 2 组 REPORT(收养伴生,REPORT-only)
MISSING_AFTER                       = 0(15/15 源)
ORPHANS_AFTER                       = 0(docs 与 chunks 双口径;15/15 源)
POLLUTED_AFTER                      = 0(.hef 全清;无 .so/.bin)
REPAIR_REQUIRED_AFTER               = false(全源;apps/website 已转 false)
WEAVIATE_COUNT_BEFORE               = 208,009
WEAVIATE_COUNT_AFTER                = 147,615
LEDGER_COUNT_BEFORE                 = 11,933
LEDGER_COUNT_AFTER                  = 11,935
KNOWLEDGE_HEALTH_AFTER              = 恢复写者后首 tick 刷新:全源 consistency 0/0/-/false;apps 与 website 不再 ACTION_REQUIRED;D2 不产生 degraded
FINAL_DRY_RUN                       = 15 源全跑:apps 0 条;website/apic/sdks 仅 REPORT(2/103/2);其余 11 源 0;无 actionable 条目
NATURAL_SYNC_OBSERVATION            = 恢复后首 tick(00:06:20 起)15/15 completed 全部无变更跳过;未人工触发任何 sync
SERVICE_STATE                       = 三服务 v1.0.0 无混版;backend healthy 连续 up 7h+(全程零重启);sync 两容器同镜像 start(非 recreate)
REGRESSIONS                         = NONE
UNAUTHORIZED_MUTATIONS              = NONE
ISSUE_13_COMPLETION_RECOMMENDATION  = READY_TO_CLOSE(Planner 拥有 closure)
REPORT_PATH                         = docs/implementation/CAMTHINK_V1_ISSUE_13_PRODUCTION_DATA_REPAIR_2026-09-04.md
REPORT_COMMIT                       = <见 docs 仓提交>
PRODUCTION_MUTATIONS                = ①Weaviate −60,394 vectors(5 个 .hef,uuid5 确定性 delete_many)②PG −3 ledger 行(apps .hef)③PG +5 ledger 行(website 零 embed 收养)④sync-cron/sync-executor stop→start(同镜像非重建)⑤backups/ 证据文件落盘。除此之外零变更:无 reindex/全量同步/迁移/部署/配置改动/backend 重启
```

**STOP。未开始 #19/#20。**
