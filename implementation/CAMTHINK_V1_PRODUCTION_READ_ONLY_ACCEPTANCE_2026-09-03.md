# CamThink V1 — Production READ-ONLY Acceptance Gate 报告

**Gate 性质**: 生产只读验收(最终写入前的事实基线 + mutation preview)。非部署、非迁移、非修复。
**STATUS**: **READ_ONLY_PASS** — 生产事实充分采集,后续 mutation 可被精确授权。
**PRODUCTION_MUTATIONS**: **NONE**

---

## 0. Observation Window

- 观察窗口: 2026-09-03T13:47:31Z — 14:10Z(主机 `date -u` 实测)
- 观察者: Executor(单执行窗口;SSH 只读)
- 生产在窗口内持续服务(backend healthy,小时级 cron 正常运转;观察期间恰逢 13:17-13:21Z 的一轮 cron 完成——本轮观察**未触发**任何同步)

## 1. PRODUCTION_IDENTITY

| 项 | 事实 |
|---|---|
| 主机 | VM-0-4-ubuntu(腾讯云,`ssh tesla-t4` 别名) |
| 内核/uptime | Linux 5.15.0-151-generic, up 393 天 |
| 部署目录 | `~/ask-ai/deploy/prod` |
| GPU | Tesla T4 16GB(共享:2×root python(17d/4h)、llama-server(15d)、neomind-extensi) |

## 2. CURRENT_RELEASE / CURRENT_SERVICE_TAGS

- **三服务统一 `ghcr.io/harryhua-ai/ask-ai:sha-c83d214`**(backend / sync-cron / sync-executor,容器 2026-09-03 17:52 CST 创建,healthy)
- 镜像五级溯源: label `org.opencontainers.image.revision = c83d21443732499313cb1dc3870e6ec186f24f64` = main `c83d214` 精确匹配(Issue #8 Store Origin 发布)
- 无 RELEASE.json;compose 备份链:`docker-compose.yml.bak-ebe10b8-3site`(8-31 三站授权)→ 现行(9-3 11:43)
- **判定: 生产仍在上次已验收的 Issue #8 发布(c83d214),此后未变更;未运行 272f570、也未运行 855b88a**(两者均为 c83d214 的未合入后代——ce52af4=S0 merge、272f570=+Source Center、855b88a=+Sync Truth/修正)
- backend env(只读键,secret 未读取): `EMBEDDER_DEVICE=cuda`、`APP_MODE=prod`;**无 `EMBEDDER_CPU_FALLBACK`**(c83d214 先于 #14 → **生产现无任何 GPU 回退能力**,实证)
- `/health` → `{"status":"ok"}`

## 3. READ_ONLY_BOUNDARY_PROOF

全部命令属以下类,逐类可证只读:
1. `hostname/uname/date/uptime/ls/cat(配置)/readlink` — 文件系统读
2. `docker ps / docker inspect(labels,env 白名单键)` — 元数据读(secret 键未读取,环境仅取 EMBEDDER_*/APP_MODE/ASKAI_* 非敏感键)
3. `docker logs --since/--tail` — 日志读
4. `curl GET /health` — 只读 HTTP
5. `psql -At`(仅 SELECT;information_schema/pg_constraint/pg_indexes/业务表 SELECT)——无 INSERT/UPDATE/DELETE/DDL
6. 容器内 Python 只读脚本 ×2:
   - Weaviate 扫描:`collection.iterator(include_vector=False)`,纯属性读
   - 一致性校验:生产镜像自带 `verify_source_vectors`(模块 docstring 自证"只读、不修改任何数据(孤儿向量仅 warning,不删)";日志实输出"不删除");污染谓词=8 行移植(#13 `rel_path_from_source_id`+`historical_artifact_verdict` 逐字引用,复用生产镜像自带 `TechnicalSafetyPolicy`),纯函数零 I/O
7. `nvidia-smi`(查询态)
8. **未执行**任何 `--apply`/迁移/repair/sync 触发/重启/recreate/pull;未跑 `--check-source`(需外源枚举,超出纯读边界,留授权门)

#5 元数据 dry-run 方法论(零移植漂移):容器内导出 distinct (source_id, product, url)×count 三元组(11,940 组/208,009 chunks)→ **本地以 #5 候选原版 `backend.product_taxonomy.get_taxonomy()`+`derive_product()`+`_scan` 同一计数语义**复算(映射函数与工具同一代码路径,逐 chunk 等价)。

## 4. SCHEMA_STATE(生产清单,2026-09-03)

| 表 | 列清单关键结论 |
|---|---|
| `documents` | 11 列(content_hash,source_id,…,branch,chunk_count,…);**PK=(content_hash, branch)=旧内容寻址身份**;索引:documents_pkey(PK)/ix_documents_branch/**ix_documents_source_id**;无 content_hash 独立索引(PK 前缀覆盖) |
| `data_sources` | 8 列;**无 lifecycle_state/lifecycle_since/lifecycle_error(S0 三列缺)**;无 expected_state 值(config 内亦无) |
| `sync_runs` | 17 列=**Wave-0 版**(stage/stage_current/stage_total/counters/consistency/error_summary/sync_log_id 俱在);**缺 W2 三列 execution_device/fallback_reason/fallback_detail**;`uq_sync_runs_request_source_attempt` 部分唯一索引在位 ✓ |
| `sync_requests` | Stage⑨⑩ 全列(attempt_count/failure_kind/attempt_started_at)在位 ✓ |
| `sync_log` | 13 列(单数表名);125,268 行(历史量,未深查,不阻塞) |
| `conversations` | **session_id 在位 ✓**(销售线索期迁移已应用);141 行中 111 行 session_id NULL=合法历史 |

## 5. DATA_SOURCE_STATE(15 源,全 enabled=t,全部 24h,零 expected_state 覆盖)

| 源 | 类型 | product(源标签) | 账本 docs | 向量 chunks | 末次成功 |
|---|---|---|---|---|---|
| aitoolstack-local | github | AI-ToolStack | 37 | 955 | 09-03 13:15Z |
| knowledge-support-cases | filesystem | knowledge | 179 | 481 | 09-03 13:15Z |
| lowpower-camera-local | github | ne101 | 2421 | 36841 | 09-03 13:15Z |
| meta-hailo-os-local | github | meta-hailo-os | 27 | 93(文档标 ne503) | 09-03 13:15Z |
| ne301-local | github | ne301 | 5454 | 67413 | 09-03 03:35Z |
| ne503-apic-69d3594b | github | neoruntime | 1291 | 20198 | 09-02 08:56Z |
| neomind-dashboard-local | github | neomind | 17 | 231 | 09-03 13:16Z |
| neomind-devicetypes-local | github | neomind-devicetype | 132 | 826 | 09-03 13:17Z |
| neomind-extensions-local | github | neomind-extensions | 489 | 3665 | 09-03 13:17Z |
| neomind-local | github | neomind | 873 | 10953 | 09-03 13:17Z |
| neoruntime-apps-1eea74dd | github | neoruntime-apps | 61 | 60675 | **从未成功** |
| neoruntime-sdks-67cbac8f | github | neoruntime-sdks | 190 | 1320 | 09-03 09:57Z |
| website-camthink | web_crawl | website | 123 | 366 | 09-01 17:10Z |
| wiki-documents-local | github | wiki | 467 | 3891 | 09-03 13:21Z |
| woocommerce-mall | woocommerce | online-store | 40 | 101 | 09-03 13:21Z |

- 账本合计 11,801 行;Weaviate 合计 **208,009** objects(class=Document)
- **同 source_id 多行 = 0**(→ #13 迁移守卫零合并)
- **同 content_hash 两行 = 1 组**(D2 兄弟标本):littlefs `LICENSE.md` 同内容,`lowpower-camera-local/hw-v1.2/.../littlefs/LICENSE.md`(ne101)× `ne301-local/main/.../littlefs/LICENSE.md`(ne301)——路径身份下合法共存,零动作
- sync_requests 无 pending/running(观察时静止)
- sync_runs 合计 149(144 completed/5 failed);近 5 条全 `request_id=NULL` cron 直跑(合法);失败 5 条全在 07:32–09:46Z CUDA 事故窗口(§9)
- 历史幽灵源(仅 sync_log 残留、无现行 data_sources 行):`ne503-aipc-apps-20e0886a`(09-02)、`ne503-sdk-local`(已删重建为 neoruntime-sdks-67cbac8f)

## 6. ISSUE_13_DRY_RUN(只读等价,零 apply)

### 6.1 身份迁移预览(`migrate_documents_path_identity` 等价 SELECT)
- 现 PK=(content_hash,branch) → 目标 PK=(source_id);**待合并重复行=0**;动作=drop PK→add PK(source_id)→drop ix_documents_source_id(冗余)→ensure ix_documents_content_hash;回滚=--rollback(现数据集合法;迁移后新增同(hash,branch)兄弟将使回滚被拒——如实风险)
- Weaviate 零迁移(uuid5(source_id#i) 寻址不变,设计使然)

### 6.2 一致性事实(生产镜像 verify_source_vectors 逐源实测)
- **missing=0(全源零整篇缺失;refill=0;stale=0)**
- **孤儿(Weaviate 有/PG 无)5 源 139 篇**:ne301=21(+287 chunks)、ne503-apic=108(+4,556)、neoruntime-apps=3(+21,521)、neoruntime-sdks=2(+15)、website=5(+5);其余 10 源 expected==actual 健康
- **5 源陷每小时 unresolved-orphan partial 循环**(sync_log 实证,ne503-apic 13:16/12:09/11:02/09:54 连续 partial `20198/15642`;website 同型 `366/361`):EXTRA_CONFIRMED_RETIRED=0、账本重建=0、EXTRA_UNRESOLVED 保留 → P1 合同诚实行为,窗口不推进,直到人工裁决/修复
- neoruntime-apps **从未成功**(61 行账本 vs 60,675 向量)

### 6.3 污染 artifact(谓词逐字移植,生产自带策略)
- **neoruntime-apps 3 行 .hef 模型文件 = 38,874 chunks**(账本内):
  `examples/person-detection/models/person-detection.hef`、`showcases/gym-ops/models/hailo_yolov8n_384_640.hef`、`showcases/gym-ops/models/yolov8s_pose.hef`(reason=model_artifact_ext)
- 其余 14 源零污染。**repair_required 证据确凿**(#13 语义:6 源非健康 ∨ 污染>0)

### 6.4 repair_corpus.py dry-run 等价计数(工具 plan() 三类事实)
| 类别 | 计数 |
|---|---|
| RETIRE_UNSAFE_ARTIFACT | 3 条目 / 38,874 chunks(neoruntime-apps) |
| same_content_multiple_paths(仅呈现,零变更) | 1 条目 / 2 行(littlefs LICENSE) |
| 孤儿向量(待 --check-source 成员证据分类) | 139 docs / 5 源(RETIRE 仅限 EXTRA_CONFIRMED;UNRESOLVED 保留) |
| missing/refill | 0 |
| 账本重建候选 | 0(孤儿方向是"向量多",不是"账本缺") |

工具 dry-run 可证性:CLI 缺省 dry-run(无 --apply)+ `CorpusRepairTool.plan()` 代码块零写动词(awk 审计);生产镜像无该模块 → 本门以等价只读复刻取证,数字与 plan() 同源同口径。

## 7. ISSUE_5_METADATA_DRY_RUN(本地原版复算,零写入)

**方法**: 11,940 distinct 三元组(覆盖 208,009 chunks)× #5 候选原版 taxonomy+derive_product(与工具 `_scan` 同一映射/计数代码)。

**old → proposed 总账**: scanned=208,009 | **changed=67,251** | unchanged=140,758 | **unknown=2,560**

| 源 | 判定 | 映射明细(chunks) |
|---|---|---|
| aitoolstack-local | 迁移 | `AI-ToolStack`→aitoolstack(955,仅大小写 canonical) |
| neoruntime-apps-1eea74dd | 迁移 | `neoruntime-apps`→neoruntime(60,675) |
| neoruntime-sdks-67cbac8f | 迁移 | `neoruntime-sdks`→neoruntime(1,320) |
| website-camthink | 迁移+**unknown** | `website`→ne101:35/ne301:25/ne503:31/neomind:7/ng4500:3 + **unknown:265**(博客页) |
| wiki-documents-local | 迁移+**unknown** | `wiki`→neomind:697/ne301:240/ne503:192/ne101:112/ng4500:157/hardware-common:97/ai-common:43/ne302:33/release-notes:25 + **unknown:2,295**(通用页/.image-upload 等) |
| woocommerce-mall | 迁移 | `accessories`→commercial(44);`aitoolstack`→aitoolstack(57,不变) |
| knowledge-support-cases/lowpower/meta-hailo/ne301/ne503-apic/neomind×4 | CLEAN | 已是 canonical(140,758 chunks 不动) |

- PG 账本侧同分布(woocommerce accessories 19/aitoolstack 21 docs 双标签在账本与向量一致);**元数据迁移目标=Weaviate 原位属性更新,PG 不动**(工具语义)
- **确认:#5 元数据迁移必须先于消费产品边界的服务发布**(其实现报告冻结 Gate 顺序:taxonomy 部署→dry-run→apply→服务发布→冒烟→回归)。#5 服务代码(7123f73)**不在** 272f570/855b88a 内——本两候选部署**不依赖** #5 迁移;#5 走独立发布列车
- unknown 人群=NEEDS PRODUCT DECISION:2,560 chunks(1.23%)落 unknown slug 是设计语义(不可作目标),接受或扩 taxonomy 由产品拍板

## 8. EXPECTED_STATE_VALIDATION(15 源逐源;默认 enabled→REQUIRED/disabled→EXCLUDED;零显式覆盖)

| 源 | derived | 文档/末次成功/新鲜度(阈值48h) | 一致性证据 | 建议与产品解读 |
|---|---|---|---|---|
| aitoolstack-local | REQUIRED | 37 / 13:15Z / fresh | 健康 | 默认正确 |
| knowledge-support-cases | REQUIRED | 179 / 13:15Z / fresh | 健康 | ⚠️ **NEEDS PRODUCT DECISION**:#5 taxonomy 定性 support 桶(背景证据、永不可引用)——作 REQUIRED 保留供检索 vs 降 OPTIONAL,需拍板 |
| lowpower-camera-local | REQUIRED | 2421 / fresh | 健康 | 默认正确(ne101) |
| meta-hailo-os-local | REQUIRED | 27 / fresh | 健康 | 默认正确(文档已标 ne503) |
| ne301-local | REQUIRED | 5454 / 03:35Z / fresh | **degraded:21 孤儿→小时 partial 循环** | 默认正确;修复属 #13 repair |
| ne503-apic-69d3594b | REQUIRED | 1291 / 09-02 08:56Z / fresh(28.8h) | **degraded:108 孤儿(+4,556)循环** | 默认正确;⚠️ 若持续不修,~09-04 09Z 后越 48h 转 STALE |
| neomind-dashboard/devicetypes/extensions/local | REQUIRED | 各 / fresh | 健康 | 默认正确 |
| neoruntime-apps-1eea74dd | REQUIRED | 61 / **从未成功** | **degraded:3 孤儿+38,874 污染 chunks** | 默认正确;候选语义下=ACTION_REQUIRED(consistency 最重) |
| neoruntime-sdks-67cbac8f | REQUIRED | 190 / 09:57Z / fresh | **degraded:2 孤儿循环** | 默认正确 |
| website-camthink | REQUIRED | 123 / 09-01 17:10Z / **44.6h 逼近阈值** | **degraded:5 孤儿循环**(伴既有 5 页抽取失败) | 默认正确;⚠️ 若循环不解,~09-03 17:10Z 越阈转 STALE |
| wiki-documents-local | REQUIRED | 467 / fresh | 健康 | 默认正确 |
| woocommerce-mall | REQUIRED | 40 / fresh | 健康 | ⚠️ **NEEDS PRODUCT DECISION**:store 桶(#5 语义不作产品事实证据,但商城价格问答确有消费)——REQUIRED vs OPTIONAL 需拍板 |

**候选语义推演(非生产现状)**:一旦部署 855b88a,`/sync-health` 将呈现 **10 源 HEALTHY + 5 源 ACTION_REQUIRED**(ne301/ne503-apic/neoruntime-apps/neoruntime-sdks/website;apps 因 #13 修正 polluted+repair_required 双重 degraded,其余孤儿 degraded)——与既有 DSH"运行成功率"口径完全不同的真值呈现,产品侧应预知。

## 9. SYNC_TRUTH_STATE / GPU_RUNTIME_STATE

**Sync truth(CURRENT PRODUCTION)**:
- sync_runs=Wave-0 schema,executor+sync.py 双写者在写(149 行/24h;启动对账日志 `finalized_done:0...` 在位);request→run→log 链路在位(request-backed 期史+现 cron NULL 直跑并存)
- **读侧三端点(/sync-status /sync-runs /sync-health)不存在**(W2 未部署)——当前健康可见性=DSH 运行成功率口径(30 天 run 级),非知识健康
- retention: purge_expired_sync_runs(30d) 由 executor loop 执行(Wave-0 行为);无陈旧/interrupted 残留(启动对账清过)

**ACCEPTED CANDIDATE BEHAVIOR(差异,未部署)**: +W2 三列与三读端点+实时进度落笔(to_thread 防抖)+#14 受控回退+#13 身份/一致性+修正后的 #11 健康(§8 推演)

**GPU/runtime**:
- Tesla T4 16GB: **15,787/16,384 MiB 已用,144 MiB 空闲**(常态饱和;4 个他方进程)
- backend BGE 常驻(root python,4h=随容器重建);sync executor 空闲间隙健康
- 历史 CUDA/OOM 证据: 09-03 07:32–09:46Z 事故窗口 5 failed runs(neomind 12 篇 OOM;neoruntime-sdks 前身 192 篇×4 cuInit-100)——**全部失败、无回退**(EMBEDDER_CPU_FALLBACK 不存在)→ 17:52 CST 容器重建后零 CUDA 错误,最近 cron 全绿
- **当前生产零回退能力**;⚠️ 部署 #14 后行为变化:144 MiB 空闲下新建 CUDA 上下文大概率 OOM→白名单回退 CPU 将成为常态路径(sync 变慢但有界)——**这是 #14 的设计目的,但应向产品明示"同步将常态走 CPU"的预期**

## 10. MIGRATION_MATRIX

| 能力 | 生产现状 | 候选要求 | 需迁移? | 工具 | dry-run | 预期行数 | 风险 | 回滚 |
|---|---|---|---|---|---|---|---|---|
| S0 data_sources lifecycle 三列 | 缺 | 需(272f570 ORM) | **YES** | migrate_add_data_source_lifecycle.py | 幂等 additive(N/A) | 15 源×NULL 列 | 低 | drop 三列(未提供,additive 可留) |
| #13 documents 路径身份 PK | (content_hash,branch) | PK=source_id(855b88a ORM) | **YES** | migrate_documents_path_identity.py | 守卫预览=0 合并(本门已证) | 11,801 行 DDL 重 PK;0 数据变更 | 中:换 PK 期间表锁+旧镜像并跑语义漂移 → **须与镜像切换同窗口** | --rollback(现数据合法;迁移后新增同 hash 兄弟将拒绝回滚) |
| W2 sync_runs 三列 | 缺 | 需(855b88a record_device) | **YES** | migrate_add_sync_run_runtime_facts.py | 幂等 | 149 行得 NULL 设备事实(诚实 unknown) | 低 | drop 三列 |
| #5 product 元数据 | 旧标签(67,251 非canonical) | #5 服务要求 canonical | **独立列车**(不阻塞本两候选) | migrate_product_metadata.py(原位属性) | **本门已完成**(§7) | 67,251 chunks 更新;2,560→unknown | 低(不触向量) | 重跑工具反向(或保持,纯元数据) |
| conversations.session_id | 在位 | — | NO | — | — | — | — | — |
| 其余 855b88a schema 依赖 | 无(三迁移外零新增表列;W0/Wave-0 表已在) | — | NO | — | — | — | — | — |

## 11. MUTATION_PREVIEW(未来计划,本门零执行)

**A. SCHEMA**(可先于镜像,expand 阶段):①lifecycle 三列→②sync_runs 三列(均 additive 幂等,旧镜像无知觉)
**B. SCHEMA(窗口内)**:③documents PK 切换——**必须**与新镜像同维护窗口(先停 executor/cron 待机→迁移→三服务同 tag 起→冒烟);严禁旧镜像长跑新 PK(旧 upsert 语义按 hash 寻址,PK=source_id 下可产生双行)
**C. CORPUS/LEDGER**(#13 repair,新镜像内执行):先 `repair_corpus.py --source X --check-source`(成员证据分类 139 孤儿)→dry-run 复核→`--apply` 逐源:3 .hef 行退休(账本+其 38,874 向量);EXTRA_CONFIRMED 孤儿精确删除;UNRESOLVED 保留待裁决;D2 兄弟零动作。**顺序:必须在 PK 迁移之后**(Stage A 设计)
**D. VECTOR(#5,独立列车)**:#5 镜像内 `migrate_product_metadata.py --dry-run`(复核 §7)→`--apply`(67,251 原位更新)→#5 服务发布;**先于 #5 服务、后于 taxonomy 配置在镜像内就位**
**E. DATA_SOURCE CONFIG**:expected_state 覆盖=NEEDS PRODUCT DECISION 项(support/store 两桶);本门零写入
**F. RELEASE**:RC 镜像→**三服务同 tag**(update.sh 不含 sync-executor,须显式 `ASKAI_IMAGE_TAG=<tag> docker compose up -d sync-executor`)→SMOKE→回滚锚=sha-c83d214(+迁移回滚按 §10)

**HALF_STATE_RISKS(显式)**:
1. 新镜像(855b88a)+旧 PK → ORM 身份错配→**ingest 全灭**(最重,窗口纪律防)
2. PK 切换+旧镜像长跑 → 同内容异路径双行/抢占复活(RC-1 复辟)
3. 新镜像+W2 列缺 → record_device best-effort 静默降级(设备遥测全 NULL,健康/历史失真但不崩)——expand 先行可免
4. repair 先于 PK 迁移 → 工具按路径寻址,身份未切换=修复语义悬空
5. #5 apply 先于 #5 镜像/taxonomy → 无处执行或映射漂移;#5 服务先于 apply → 检索闸门大面积 unknown 拒答
6. 三服务 tag 不齐(尤其 sync-executor 漏更)→ 双行为并存(request/run 设备事实断链)
7. .env 未显式 EMBEDDER_CPU_FALLBACK → 缺省 on=行为隐式变化(常态 CPU 同步)——建议发布单显式声明而非隐式

## 12. UNKNOWNS / PRODUCTION_BLOCKERS

**UNKOWNS(如实)**:
1. 2,560 unknown chunks(#5)的归属=产品决策(接受 unknown 或扩 taxonomy)
2. support/store 两源 expected_state=产品决策
3. 139 孤儿的 EXTRA_CONFIRMED vs UNRESOLVED 分类需 --check-source(外源权威枚举,留授权门)
4. ne301 21 孤儿的产生事件(疑 07:32 CUDA 窗口半程 embed;未 forensic)
5. website 5 页抽取失败根因(既有遗留,持续 partial)
6. sync_log 125,268 行历史量级(未深查,无阻塞)

**PRODUCTION_BLOCKERS(对本门=无;对后续发布的顺序性硬约束)**:①PK 迁移必须与镜像同窗口;②#13 repair 必须后于 PK 迁移;③#5 apply 必须夹在 taxonomy 就位与 #5 服务发布之间;④sync-executor 必须显式更新。

## 13. RELEASE_READINESS / NEXT_GATE

- **READ_ONLY_PASS**:事实充分,mutations 可精确授权(计数、工具、顺序、回滚全在案)
- **推荐下一门**:「Production Mutation Authorization & Deployment Gate」按 §11 顺序分四批授权执行——批1(additive 迁移×2,可先行)→批2(PK 切换+三服务 RC 上线+SMOKE,维护窗口)→批3(#13 repair:check-source→dry-run→apply 逐源)→批4(#5 独立列车:镜像→apply→服务→93 回归);每批独立授权、独立回滚锚

---
PRODUCTION_MUTATIONS: **NONE**(全窗口零写入;§11 为纯计划)
