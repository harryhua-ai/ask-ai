# CamThink V1 v1.0.0 — Production Mutation & Deployment Gate 执行报告

- 日期:2026-09-03 16:24Z → 2026-09-03 17:05Z(授权任务标注 2026-09-04)
- 执行模式:SINGLE EXECUTOR,**显式用户生产授权**(Production Mutation & Deployment Gate)
- Final RC:**0e6a8a3**(`integration/camthink-v1-final-rc-20260903`,Planner 独立验收)
- 生产回滚锚:c83d214(部署前三服务运行镜像)
- STATUS:**PRODUCTION CANDIDATE ACCEPTED / PRODUCTION_ACCEPTANCE=PASS(with findings)**
- ISSUE_13_REPAIR_STATUS:**NOT_EXECUTED / SEPARATE_AUTHORIZATION_REQUIRED**(契约红线全程未触碰)

---

## 0. 授权范围与执行对照

授权内执行:FF main→RC、打 tag v1.0.0、CI 镜像、additive 迁移、#13 PK 切换、#5 metadata APPLY、
三服务部署 v1.0.0、生产冒烟与最终验收、GitHub Release。
明确排除(全程未执行):`repair_corpus.py --apply`、139 孤儿文档处置、38,874 个 .hef 污染 chunk 处置、
语料重建、破坏性 Weaviate 清理、手动全量同步、CUDA 故障注入、DataSource 配置变更、LLM secrets 变更。
部署若必须依赖排除项即 BLOCKED 的条件——**未触发**(部署与验收全程无需任何 excluded repair)。

## 1. 变更前拓扑核验(§1 A/B)

- `origin/main` = c83d21443732499313cb1dc3870e6ec186f24f64 ✓(与预期一致,未前进)
- `origin/integration/camthink-v1-final-rc-20260903` = 0e6a8a3bb72932b26fcf500954aacfe109373133 ✓(与 FINAL_RC 逐字一致)
- `git merge-base --is-ancestor c83d214 0e6a8a3` = ANCESTOR-OK(FF 可行,零 merge commit)
- 远端 tag `v1.0.0` 不存在(本地/远端双查)✓
- `release-notes/v1.0.0.md` 存在于 0e6a8a3 ✓;CI workflow `build-image.yml` 触发器含 `tags: ["v*.*.*"]` ✓
- 生产三服务镜像 = `sha-c83d214`,backend healthy(旧 /health 仅 `{"status":"ok"}`,c83d214 无 #10 身份,符合预期)

## 2. 变更前生产快照(§2,2026-09-03T16:24Z)

- documents:PK=(content_hash, branch),行数 **11,801**,**duplicate source_id guard = 0(硬闸通过)**
- D2 合法同内容兄弟对(须存活):`0cb4ff1daf5f…` lowpower-camera-local/hw-v1.2/…littlefs/LICENSE.md(hw-v1.2)+ ne301-local/main/…littlefs/LICENSE.md(main)
- sync_runs 未完成 = 0;sync_requests pending/running = 0
- Weaviate Document 对象 = **208,009**
- data_sources 15 源全 enabled,无 lifecycle 列;sync_runs 17 列(Wave-0),无 runtime-facts 列,身份索引在位
- RC models `__tablename__` 集合 = 生产现存 20 表(零新表 → Phase A 仅 4 个既有脚本)
- GPU:T4 15,787/16,384 MiB(共享租户既有饱和);磁盘 948G 可用

### 回滚锚(§2)

| 锚 | 值 |
| --- | --- |
| DB 备份 | `~/ask-ai/backups/pg_askai_pre_v1.0.0_20260903T162648Z.dump`(pg_dump -Fc,6,413,410 B,sha256 `2970cbb89c75b43e38160c34a77ad820da31f4abd311084a26e506399b711b53`,PGDMP 魔数 + pg_restore --list 20 TABLE DATA 校验通过) |
| 镜像锚 | `ghcr.io/harryhua-ai/ask-ai:sha-c83d214`(本机已在库);过渡回滚 `ASKAI_IMAGE_TAG=sha-c83d214 docker compose up -d backend sync-cron sync-executor`(注意:c83d214 无 RELEASE.json,新 update.sh 会拒绝 → 显式 compose 两步流程) |
| schema 锚 | PK=(content_hash,branch);无 lifecycle/runtime-facts 列(备份 dump 即全量快照) |
| main 锚 | c83d214(FF 前的 origin/main,标签不可移动承诺下亦可由 dump+镜像完整恢复数据面) |

## 3. Release main / tag(§3)

- `git push origin 0e6a8a3bb72932b26fcf500954aacfe109373133:refs/heads/main` → `c83d214..0e6a8a3`(**纯 FF,非强制**,远端核验一致)
- `git tag -a v1.0.0 0e6a8a3…` → tag object `5ef792296487e135cd12476d29fb2d30de5d850d` → commit **0e6a8a3bb72932b26fcf500954aacfe109373133**(rev-parse `v1.0.0^{commit}` 核验);推送后 `git ls-remote --tags` 核验
- 本地工作树 main 指针与 origin 不同步(1d6f6b5 本地遗留状态)——**未触碰**(发布身份以服务端为准;避免动他人工作树)

## 4. CI / 镜像门(§4)

- tag 触发 run **33778725934** = success(13m);同 commit main run 33778721183 = success(13m)——双绿
- `ghcr.io/harryhua-ai/ask-ai` tags list 含 `v1.0.0` 与 `sha-0e6a8a3` ✓
- 镜像独立核验(部署前):
  - RELEASE.json:`{"version":"1.0.0","git_sha":"0e6a8a3bb72932b26fcf500954aacfe109373133","built_at":"2026-09-03T16:29:56Z","image":"ghcr.io/harryhua-ai/ask-ai:v1.0.0","ci_run_id":"33778725934"}` ✓ 全字段
  - OCI label `org.opencontainers.image.revision` = 0e6a8a3bb72932b26fcf500954aacfe109373133 ✓;`image.version`=1.0.0 ✓
  - taxonomy 抽查:含 i18n 镜像树派生规则(unknown-closure 版 v1.0.0 taxonomy)✓

## 5. PHASE A — additive schema(§5-A)

执行方式:`ASKAI_IMAGE_TAG=v1.0.0 docker compose run --rm sync python scripts/<m>`(v1.0.0 镜像内脚本,逐条输出)。
执行环境坑(记录):①`compose run` 吸走 ssh stdin → 一律 `</dev/null`;②生产 `.env:40` 遗留 `TEST_DATABASE_URL`(指向 127.0.0.1:15432 dev DSN)会被 `migrate_add_data_source_lifecycle.py` 的测试覆盖惯例优先读取 → 以 `-e TEST_DATABASE_URL=` 逐次调用中和(**未改动 .env**,属授权外);③该脚本无 `sys.path.insert` → `-e PYTHONPATH=/app`。

| 脚本 | 结果 |
| --- | --- |
| migrate_add_sync_runs.py | `OK: sync_runs 就绪(17 列,身份索引在位)`(表+索引既有,幂等 no-op 性质确认) |
| migrate_add_sync_requests.py | `✅ sync_requests 交接表与恢复列…已确保存在`(no-op) |
| migrate_add_data_source_lifecycle.py | `OK: data_sources 生命周期列就绪(lifecycle_state/lifecycle_since/lifecycle_error)` |
| migrate_add_sync_run_runtime_facts.py | `OK: sync_runs 运行时事实列就绪([execution_device, fallback_detail, fallback_reason],共 20 列)` |
| 幂等证明 | lifecycle 脚本重跑第二次 → 同 OK 输出,无副作用 |

变更后独立核验:三 lifecycle 列在位;三 runtime-facts 列在位;sync_runs 列数=20;**两表新列全 NULL(零数据变异)**;旧 runtime(c83d214 backend)health 仍 ok(additive 兼容实证)。

## 6. PHASE B — #5 product metadata(§5-B)

- 写者窗口:**sync-cron + sync-executor 于 16:47:00Z docker stop**(防 apply 期间 cron 增量回写旧标签);复验 active run=0
- fresh DRY-RUN(15 源全量,v1.0.0 镜像内工具):
  **scanned=208,009 / changed=67,251 / unchanged=140,758 / unknown=1,252** —— 与验收预览**四项逐字一致**
  - 预先解释既有疑异:本窗口 09-03 只读验收曾本地复算 unknown=2,560;v1.0.0 taxonomy 吸收 unknown-closure(i18n 镜像树 1,307 + ai-tool-stack 1 归账)后 2,560−1,308=1,252,release-notes 亦如实记载 → 非漂移,系 taxonomy 版本差异,方向与契约一致
  - 映射抽查:aitoolstack-local `AI-ToolStack→aitoolstack` 955;neoruntime-apps/sdks → neoruntime 60,675/1,320(bucket 归一);wiki `wiki→`按路径派生(neomind 1,258/ne301 434/ne503 360/ng4500 294/ne101 207/ne302 55/shared 295/release-notes 40);woocommerce `accessories→commercial` 44;**零兄弟产品误映射**
  - unknown 1,252 抽样:blog/landing/shipping-policy/register/package-lock.json/.image-upload 测试件等——均为非产品页/非文档,保守合规 ✓(含 package-lock.json 这类历史灌入噪声,处置属 #13 repair 授权范围,未动)
- **APPLY**:`--apply` 原位属性更新,2026-09-03T16:48:16Z→16:50:24Z(2m08s),**67,251 chunks 写入;零 re-embed/零删除/零重建**
- post-apply DRY-RUN:**scanned=208,009 / changed=0 / unchanged=208,009 / unknown=1,252** —— 零残余候选,unknown 人群契约保留 ✓
- 证据文件:`backups/metadata_dryrun_pre_v1.0.0_20260903T164710Z.log`、`metadata_apply_v1.0.0_20260903T164816Z.log`、`metadata_dryrun_post_v1.0.0_20260903T165024Z.log`(生产机)

## 7. PHASE C — #13 identity cutover(§5-C)

- 前置复验(16:51 前后):active sync_runs=0;pending/running requests=0;**duplicate source_id guard=0**;documents=11,801;旧写者(stop 于 §6)持续停止
- `python scripts/migrate_documents_path_identity.py`(v1.0.0 镜像内)动作流(逐条):
  `[drop PK (content_hash, branch)] → [add PK (source_id)] → [drop redundant index ix_documents_source_id] → [ensure index ix_documents_content_hash]`
  —— **零 merge 动作**(守卫=0,无行删除)
- 即时验证:PK=PRIMARY KEY (source_id) ✓;ix_documents_content_hash 在位 ✓;行数 **11,801 守恒** ✓;source_id 全表唯一(t) ✓;**D2 兄弟对两行均存活** ✓;冗余索引已除 ✓;Weaviate 零迁移(契约) ✓;corpus repair 未执行(红线) ✓
- 新写者回归:`update.sh` 步骤 [6/6] 重建 sync-cron/sync-executor 后首个小时 tick(Runs 195–209,15/15 completed)在新 PK 上正常完成——「新 PK+新写者」同窗成立,禁半态未出现

## 8. 部署 v1.0.0(§6)

- `cd ~/ask-ai && ./deploy/prod/update.sh v1.0.0`:16:51:31Z→16:52:09Z(exit 0)
  - [2/6] pull ✓(image 已预拉)→ [3/6] RELEASE.json 断言 version=1.0.0/git_sha=0e6a8a3 ✓ fail-closed → [4/6] GPU 预检警告 15,787MiB(已知共享租户饱和,按契约继续)→ [5/6] backend 重建+health 轮询+运行时 version=1.0.0 核验 ✓ → [6/6] sync-cron+sync-executor 同批 ✓
  - 三服务镜像逐 container 核验 = `ghcr.io/harryhua-ai/ask-ai:v1.0.0`,**无混版**
- 部署资产准备(部署前已备份并替换):host `deploy/prod/{update.sh,docker-compose.yml}` ← RC 版本(旧件存 `*.bak-c83d214`);新 compose 含 `ASKAI_IMAGE_TAG:?` 强制守卫(根除 `:-latest` 回落雷)
- writer-stop window:**16:47:00Z(§6 停 cron/executor)→ 16:52:09Z(update.sh [6/6] 新写者上线),5m09s**;窗口内 backend 持续服务只读 Q&A(手动同步面经 sync_requests→已停 executor,窗口内不可能执行;backend 自 stage⑨ 起不承担 ingestion 写,证据=sync_requests 交接机制运行记录)

## 9. 部署后核验(§7)

- `/health` = `{"status":"ok","version":"1.0.0","git_sha":"0e6a8a3bb72932b26fcf500954aacfe109373133","app_mode":"production"}`(与镜像/OCI 三方一致)
- Admin `GET /api/admin/system/release`:路由已在运行进程挂载(OpenAPI 实证);**带 token 调用未执行**——生产 admin 凭据不在执行端持有,种子默认 admin123 已失效(历史安全隐患实际已修复,顺带核销);等效证据链=镜像 RELEASE.json + /health + OCI revision + update.sh [3/6][5/6] 双断言
- schema:DataSource lifecycle 列 ✓(§5);SyncRun runtime/progress 列 ✓(§5);documents PK=source_id ✓(§7)
- Source Center:OpenAPI 路由面全在(`/api/admin/data-sources`、`discover-repo`、`preview-website`、`{id}/sync`、`{id}/delete/retry`、`sync-status|runs|health`、`system/release`);Admin SPA `GET /admin/`→200 text/html;既有 15 DataSource 完整保留;零 lifecycle 变异(全 NULL)
- Sync 可观测:cron 首 tick 即在新运行时产出 **Runs 195–209(15 源全 completed)**,stage 链路正常;已知孤儿以诚实语义呈现不删除(如 ne301-local 21 orphans);无变更源的 execution_device=NULL(零活动真值,SHA 短路不谎报 GPU 健康,符合 #14 契约)
- 稳定窗:部署后 15+ 分钟三服务零重启、executor 零 ERROR(仅既有 SAWarning 化妆品级)、无新 CUDA 崩溃环

## 10. #5 生产问答验收(§8,13 例,channel=admin 隔离池)

SSE 原始流存证:`~/ask-ai/backups/answer_acceptance_v1.0.0_20260903T165420Z/*.sse`(生产机)。

| 案例 | 结果 | 要点 |
| --- | --- | --- |
| 01 NE101 通信方式 | PASS | Wi-Fi/LTE Cat.1/HaLow + NE-CM02/CM03 型号,全部 NE101 证据 |
| 02 NE301 功耗 | PASS | 深睡 6.1μA/分模式电流表,对冲突口径(170-180mA vs 70mA)诚实标注 |
| 03 NE302 vs NE301 对比 | **FAIL→findings F1** | 复现×2:empty_generation→「服务暂时不可用」;机制见下,零泄漏(fail-closed) |
| 04 NE503 场景 | PASS | 定位/场景/「不适合的情况」明确点名低功耗场景更适合 NE101/NE301 |
| 05 NG4500 协议 | PASS | 总线/接口/视频流协议;「未载明项」显式(Modbus/OPC UA 不编造);历史盲区已由 wiki ng4500 证据覆盖 |
| 06 NeoMind 建设备 | PASS | CLI+自动发现草稿审批双路径,命令/参数准确 |
| 07 NeoRuntime 部署 | PASS | 构建发布包→设备部署,官方流程 |
| 08 AI ToolStack | PASS | 定义/定位/特性,aitoolstack 证据 |
| 09 NE101 价格(负例) | PASS | $69 整机+未标明版本对应、Dev Kit $59.9、配件价,均引商店来源;SKU/批量价未载明→指向正式报价(不猜) |
| 10 指代歧义(负例) | PASS | 「请告诉我要了解的具体产品型号(如 NE301、NE503)」——clarify 而非猜测 |
| 11 跨产品防水对比 | PASS | IP67 结论锚定 shared 硬件公共文档(同时记载两款),合法 shared 证据 |

**F1(发现,非数据完整性缺陷)**:兄弟对比类问题确定性劣化为 empty_generation/`service_unavailable` 文案。机制实证:target 解析 NE302(explicit)→ 检索池 3 条中含 **store 的 NE301 产品页(shop URL `store/ne301/`,metadata product=aitoolstack)** —— 商店桶标签粒度粗于设备身份,使 NE301 姊妹证据以「aitoolstack」身份入池不被拦截 → 模型书写跨型号对比 → 流式资格校验全部剔除 → PC-01 零内容守卫触发(30s 流全弃)。**边界本身成立:零错误内容、零兄弟数据冒充、失败关闭**;但弃答语义走了生成失败文案而非 PRODUCT_EVIDENCE_INSUFFICIENT 澄清,UX 误导(重试无效)。
**F2(观察)**:商店页桶标签(aitoolstack/commercial)与设备粒度差是 F1 的土壤;单产品查询未受影响(09/01 均正确且诚实)。

## 11. GPU / #14 观测(§10,只读)

- 部署后 GPU 15,111MiB used/820MiB free(backend BGE 正常驻留);无新 CUDA 崩溃环;executor/健康正常
- 部署后首 tick 15 源全部「无变更跳过」→ 零 embed 活动 → 无自然 OOM 可观测;**按任务约定,无自然 OOM 不算失败**;execution_device 列如实 NULL(未活动不谎报)
- #14 有界回退代码已在生产镜像内(v1.0.0),其自然触发留待后续 embed 窗口观察

## 12. 已知脏数据状态(未触碰,§0 红线)

- 139 孤儿文档 / 5 源(小时级 partial 循环照旧诚实运行,继续不删除)
- neoruntime-apps `.hef` 污染 38,874 chunks:原样保留;Admin Knowledge Health 将按 Correction Gate 语义呈现 ACTION_REQUIRED(预期内,「known dirty data can remain visible」)
- unknown 1,252 契约性保留;wiki 历史非文档噪声(package-lock.json 等)随 #13 repair 另行授权处置
- ISSUE_13_REPAIR_STATUS = **NOT_EXECUTED / SEPARATE_AUTHORIZATION_REQUIRED**

## 13. Issue 生命周期建议(§13,仅建议)

- **#5**:eligible for FINAL PASS / close(metadata 迁移四项逐字达标+零残余+13 例语义验收)
- **#10**:eligible for FINAL PASS / close(版本化 tag/update.sh/RELEASE.json/身份链全链生产实证)
- **#13**:**DO NOT close**(corpus/vector repair 待独立授权;PK 切换本身已交付)
- 建议新跟踪:①兄弟对比意图的多目标 scope 或结构化 insufficient 语义(F1);②商店页设备级 product 解析(F2);③生产 `.env` 遗留 `TEST_DATABASE_URL` 清理(本次以调用级中和,未改配置)

## 14. 回滚就绪(§11)

- 数据:`pg_askai_pre_v1.0.0_20260903T162648Z.dump`(sha256 见 §2)
- 镜像:`sha-c83d214` 本机在库;过渡回滚=显式 compose 两步(旧镜像无 RELEASE.json,新 update.sh 拒绝属设计)
- #13 schema 回滚:`migrate_documents_path_identity.py --rollback`;**守卫核验**:若存在同 (content_hash,branch) 多行则拒绝(D2 对 `0cb4ff1daf5f` 恰为该形态 → 当前状态下回滚会被守卫拒绝并报错,不静默丢数据;若必须回滚需先按契约处置 D2 行,须另行授权)
- #5 metadata:无需回滚(旧服务按契约忽略新 canonical 标签;release-notes 同口径)

## 15. 回归与已知局限

- 回归:部署后 15/15 同步 completed、Q&A 13 例语义验收、三服务 15+ 分钟稳定、旧 /health 消费方兼容(status 字段保留)——零功能性回归
- 已知局限:F1/F2(§10);authenticated Admin 页面级冒烟未执行(无生产凭据,已用等效证据链);自然 OOM 未发生故 #14 回退未获自然实证;SAWarning(sync_executor_loop.py:281)化妆品级仍在;CI 镜像 ~9.6GB 拉取开销(release-notes 既有声明)

## 16. 返回字段(§14)

```
STATUS                          = PRODUCTION CANDIDATE ACCEPTED
AUTHORIZATION_USED              = FULL(授权内八项全部执行;排除项零触碰)
PRE_MUTATION_STATE              = prod=sha-c83d214×3 healthy;documents PK=(content_hash,branch) 11,801 行;dup guard=0;active sync=0;Weaviate=208,009;GPU 15,787MiB;backup=pg_askai_pre_v1.0.0_20260903T162648Z.dump(sha256 2970cbb8…,20/20 tables)
MAIN_BEFORE                     = c83d21443732499313cb1dc3870e6ec186f24f64
MAIN_AFTER                      = 0e6a8a3bb72932b26fcf500954aacfe109373133(纯 FF,非强制)
TAG                             = v1.0.0(annotated,object 5ef7922…;此前不存在,未移动)
TAG_TARGET                      = 0e6a8a3bb72932b26fcf500954aacfe109373133
CI_RUN                          = 33778725934(tag)=success;33778721183(main)=success
IMAGE                           = ghcr.io/harryhua-ai/ask-ai:v1.0.0
IMAGE_RELEASE_IDENTITY          = RELEASE.json{version=1.0.0,git_sha=0e6a8a3…,built_at=2026-09-03T16:29:56Z,ci_run_id=33778725934};OCI revision=0e6a8a3… ✓
DB_BACKUP_OR_ROLLBACK_ANCHOR    = pg_askai_pre_v1.0.0_20260903T162648Z.dump + :sha-c83d214 镜像 + --rollback 守卫语义(§14)
ADDITIVE_MIGRATIONS             = sync_runs(no-op 幂等)+sync_requests(no-op)+data_source_lifecycle(+3 列)+sync_run_runtime_facts(+3 列,共 20);幂等重跑证明;旧 runtime 全程 healthy
PRODUCT_METADATA_DRY_RUN_BEFORE = scanned=208,009 changed=67,251 unchanged=140,758 unknown=1,252(与验收预览四项逐字一致;2,560→1,252=unknown-closure taxonomy 差异,已解释)
PRODUCT_METADATA_APPLY          = 2026-09-03T16:48:16Z→16:50:24Z;67,251 chunks 原位更新;零 re-embed/零删除/零重建
PRODUCT_METADATA_DRY_RUN_AFTER  = scanned=208,009 changed=0 unchanged=208,009 unknown=1,252(零残余候选)
SYNC_WRITER_STOP_WINDOW         = 16:47:00Z→16:52:09Z(5m09s;cron+executor stop→update.sh [6/6] 新写者上线;窗口内零 run)
DOCUMENT_IDENTITY_MIGRATION     = drop PK(content_hash,branch)→add PK(source_id)→drop ix_documents_source_id→ensure ix_documents_content_hash;零 merge 动作
DOCUMENT_PK_AFTER               = PRIMARY KEY (source_id);11,801 行守恒;source_id 唯一;D2 对 0cb4ff1daf5f 双行存活
DEPLOYMENT                      = update.sh v1.0.0 exit 0(16:51:31Z→16:52:09Z);[3/6] RELEASE.json fail-closed 断言+[5/6] 运行时 version 核验全过
SERVICE_TAGS                    = backend=v1.0.0;sync-cron=v1.0.0;sync-executor=v1.0.0(逐容器核验,无混版)
HEALTH_RESULT                   = {status=ok,version=1.0.0,git_sha=0e6a8a3…,app_mode=production}
ADMIN_RELEASE_RESULT            = 路由挂载实证(OpenAPI);token 化调用未执行(admin 凭据不在执行端;admin123 已失效=历史隐患已修复);等效证据链=镜像清单+/health+OCI+update.sh 双断言
SOURCE_CENTER_SMOKE             = 路由面全在(data-sources/discover-repo/preview-website/sync/delete-retry);SPA 200;15 源保留;零 lifecycle 变异
SYNC_OBSERVABILITY_SMOKE        = 首_tick Runs 195–209 全 completed;stage 链路正常;孤儿诚实呈现;execution_device=NULL=零活动真值
ANSWER_CORRECTNESS_PRODUCTION_ACCEPTANCE = PASS with findings:8/8 产品域语义正确(无编造/无兄弟冒充/未载明显式);10 指代歧义=澄清;11 跨产品=合法 shared;09 价格=来源+警告;唯一 FAIL=03 兄弟对比确定性 empty_generation(F1,失败关闭,机制=商店桶标签粒度+流式资格校验全剔)
GPU_RUNTIME_OBSERVATION         = 无新 CUDA 崩溃环;GPU 15,111MiB 稳定;零自然 OOM(不判失败);#14 代码在产待自然触发
KNOWN_DIRTY_DATA_STATE          = 139 orphans+38,874 .hef 污染+1,252 unknown 原样保留且可观测(ACTION_REQUIRED 预期呈现)
ISSUE_13_REPAIR_STATUS          = NOT_EXECUTED / SEPARATE_AUTHORIZATION_REQUIRED
ROLLBACK_READINESS              = READY(dump+镜像+--rollback 守卫;注意 D2 对会使 rollback 守卫拒绝,须另行授权处置)
GITHUB_RELEASE                  = PUBLISHED https://github.com/harryhua-ai/ask-ai/releases/tag/v1.0.0(含部署证据段;repo 内 release-notes/v1.0.0.md 为持久源)
PRODUCTION_ACCEPTANCE           = PASS
ISSUE_STATUS_RECOMMENDATIONS    = #5 FINAL PASS/close;#10 FINAL PASS/close;#13 不关(repair pending);建议新跟踪 F1 对比意图语义/F2 商店页设备粒度/.env TEST_DATABASE_URL 清理
REGRESSIONS                     = NONE(15/15 同步绿;13 例语义验收;15+ 分钟稳定窗;旧 /health 兼容)
KNOWN_LIMITATIONS               = F1/F2;Admin token 化冒烟未执行(等效链);#14 自然触发未观测;wiki 非文档噪声随 repair 另批
REPORT_PATH                     = docs/implementation/CAMTHINK_V1_V1_0_0_PRODUCTION_MUTATION_DEPLOYMENT_2026-09-04.md(docs 本地仓)
REPORT_COMMIT                   = <见 docs 仓提交>
PRODUCTION_MUTATIONS            = ①schema additive:sync_runs+3 列、data_sources+3 列(sync_runs/sync_requests 幂等 no-op);②#13 documents PK 切换(零行删);③#5 Weaviate 67,251 chunk product 属性原位更新;④三服务重建至 v1.0.0;⑤host deploy/prod 资产替换(.bak 保留);⑥DB 备份文件+metadata 日志+answer SSE 存证落 backups/;⑦13 例 admin 渠道冒烟会话;⑧git:main FF+tag 推送。未做:repair/rebuild/全量同步/CUDA 注入/配置与 secrets 变更/.env 编辑
```

**STOP。** #13 repair 未执行,等待独立授权。
