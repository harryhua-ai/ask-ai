# CAMTHINK_V1_PA0E_PRODUCTION_SYNC_CORPUS_ACTIVATION_2026-09-02

- Gate: PA-0E — 生产 sync-cron 升级至 RC 镜像 + 最小必要 corpus 激活
- 执行窗口: 2026-09-01T16:55Z ~ 17:15Z(UTC)
- 生产主机: tesla-t4(43.132.189.162 / VM-0-4-ubuntu)
- 授权: PRODUCTION_ACCESS / PRODUCTION_SYNC_CRON_UPGRADE / PRODUCTION_CORPUS_MUTATION / PRODUCTION_WEAVIATE_MUTATION = AUTHORIZED(仅限本 Gate;明确禁止 full reindex)
- 结论: **PASS**(PE-G001~G011 全过;增量只写 +4 净对象;信任边界完整;backend 零触碰)

## 0. 冻结输入现场核验

| 输入 | 现场值 | 一致性 |
|---|---|---|
| Application RC | `1ed84bb…` | sync-cron 容器内 `/app/.git-sha` 实测一致 |
| Accepted image | `ghcr.io/harryhua-ai/ask-ai:sha-1ed84bb`(ID `05f7d396…`) | 宿主机本地在位 |
| Deployment tooling | `41a7a2d` | `/home/ubuntu/ask-ai-src` HEAD 一致 |
| PA-0C / PA-0D | `077c489` / `70fe9c1` | — |

## 1. PE-G001 Freshness — PASS(零漂移)

- backend:`Image=sha256:05f7d396…`、`git_sha=1ed84bb…`、healthy、Restarts=0(= PA-0D 验收态,未动)。
- sync-cron(升级前):`Image=sha256:0c4b2c32…`(bbfaa6a 时代)、running、StartedAt 2026-08-28T12:24:19Z、Restarts=0。
- postgres / weaviate:Up 2 weeks,未动。
- tooling:`41a7a2d`,无漂移。
- 无 BLOCKED 级漂移。

## 2. PE-G002 Corpus Before-State(变更前基线)

- Weaviate class `Document`,**总对象 126,396**。
- `channel_visibility` 分布:**api=126,396 且 widget=126,396**(数组属性,每对象同时含两值 = 全库默认公开)。
- `source_type` 分布:github 125,459 / filesystem 481 / web_crawl 357 / woocommerce 99。
- `data_sources` 注册表:15 个源全部 enabled;**config 中无任何 `channel_visibility` 键**(即按权威语义全部默认公开;无源被标记受限)。类型构成:github×12、filesystem×1(knowledge-support-cases)、web_crawl×1(website-camthink)、woocommerce×1(woocommerce-mall)。凭证值未读取/未入报告。
- `sync_log` 共 124,532 行;升级前最后一轮(旧镜像,16:41:46Z 起)结果:
  - 14 源 success(无变更)/ 5 源 **partial**「一致性校验发现缺口…重灌清单为空」(ne301-local 67892/67411、neomind-local 16933/10953 等)——**后被证伪,系旧聚合计数的分词前缀污染假缺口(见 §3)**;
  - website-camthink **failed** `'web_crawl'`(旧镜像无该 connector,KeyError,每小时必败);
  - woocommerce-mall **failed** 4 文档灌入失败(4920/4054/3873/3075,自 09-01T01:25 起窗口未推进反复重试)。
- 未读取任何文档正文,仅结构/元数据。

## 3. PE-G003 Sync 行为调查(基于 RC 代码实证,非旧版假设)

**执行命令与启动即改语义**:
- compose `sync-cron` command = `sh -c "while true; do python3 scripts/sync.py || true; sleep 3600; done"` → **容器启动即执行第一轮 sync(SYNC_IMMEDIATE_ON_START=YES),升级动作本身=corpus 变更,已按此对待**。
- 每源:增量窗口 = 上次**成功**时间(失败不推进窗口);`fetch_changes(since)` 无变更 → `_handle_no_change` 一致性校验;有变更 → 幂等 upsert + 增量删除(源内被移除文件)。

**RC 相对旧生产镜像(bbfaa6a)的关键语义变化**(`git diff bbfaa6a 1ed84bb`):
1. **一致性计数口径修复(D4-ACC)**:旧实现用 Weaviate TEXT `like` 聚合计数,分词导致源前缀互相污染(neomind 家族实证)→ 产生 §2 的 5 个假 partial;RC 改为**迭代器全扫 + 客户端前缀过滤的精确计数**。本轮 RC 运行实测:5 个假缺口全部消失、判健康、零写入。
2. **孤儿/账本漂移自愈**:refill 清单为空但仍有缺口时,`fetch_all + ingest_all` 幂等自愈(重建 Postgres 账本行、确定性 UUID 覆盖、per-doc `_prune_stale_chunks` 仅删 `chunk_index >= current_count` 的越界对象)。本轮未触发(无真实缺口)。
3. **web_crawl connector(C8)**:RC 新增;sitemap 全量发现(85 URL,排除后)+ 增量窗口 + coverage 记账(≥80% 抽取成功=success,不足=partial,0=failed)。
4. **可见性传播**:ingest 逐 chunk 写 `channel_visibility`,值 = `SourceConfig.channel_visibility`(**缺省默认 `["widget","api"]`=公开**;权威配置在 `data_sources.config`)。生产 15 源均未配置覆盖 → 新写对象全部默认公开。
5. 破坏性语义:无 `--reindex` 不删 collection;`--reindex` 仅手动;删除仅限增量检测到的被移除文件与 per-doc 越界 chunk。**因果链:升级容器 → 立即第一轮增量 → 各源无/小变更 → 仅 website(+2 文档)与 woo(4 文档重试)产生写入。**

## 4. PE-G004 Impact Decision = **B(CONTROLLED INVESTIGATED INCREMENTAL SYNC)**

- 排除 A:website/woo 存在真实待同步内容(2 新 blog + 4 重试产品)。
- 排除 C/D:无需 full reindex(无 schema 变更、无 collection 级漂移;旧"缺口"系假阳性);行为完全可预测 → 非 UNSAFE。
- 计划:G005 升级 cron(其启动轮即受控增量)→ 若 GPU 受限致 embed 失败,用现有一次性 `sync` 服务 + **仅本次运行的** `-e EMBEDDER_DEVICE=cpu` 覆盖完成最小同步(不改任何文件/工具)。

## 5. PE-G005 Sync-Cron Upgrade — PASS

| 项 | 值 |
|---|---|
| BEFORE_SYNC_IMAGE | `sha256:0c4b2c32b628…`(bbfaa6a 时代) |
| AFTER_SYNC_IMAGE | `sha256:05f7d3961162…` = `sha-1ed84bb`(config 先证 `image: …:sha-1ed84bb`) |
| AFTER_SYNC_GIT_SHA | `1ed84bbfcad08224c8c322f7c7a7a817b8916147` |
| STARTED_AT | 2026-09-01T17:01:47.875772589Z |
| 命令 | `cd /home/ubuntu/ask-ai && ASKAI_IMAGE_TAG=sha-1ed84bb docker compose -f deploy/prod/docker-compose.yml up -d sync-cron`(未用 latest,未触 backend/sync 一次性服务) |

backend 完全未动(Image/Health/Restarts 与 PA-0D 验收态逐项一致)。

## 6. PE-G006 Controlled Synchronization — PASS

**第一轮(RC cron 启动轮,17:02:07–17:04:08)**:12 源无变更跳过(0 写入);2 个空壳源(ne503-aipc-apps/ne503-apic,clone_path 空)全量拉取=0 文档,success;**website-camthink:爬取正常(sitemap 85 URL,增量抓到 2 篇新 blog),但 embed CUDA OOM → failed(窗口不推进)**;**woocommerce-mall:4 文档重试,同因 CUDA OOM → failed**。
> OOM 根因(GPU 容量,环境性、先于本 Gate 存在):常驻 root server.py 3.41G + llama-server 5.77G + neomind 2.41G + backend(RC)3.78G = 15.37G / 15.56G,sync embedder(~2.5G)无位。旧镜像时代 woo 4 文档的反复失败同为此因(当时报「可能 embed/写库故障」,本轮 RC 留下完整 OOM 栈首次定性)。失败路径干净:逐文档记账、无半写、窗口不推进。

**受控补齐(17:08:51–17:11:12,现有 `sync` 一次性服务,`-e EMBEDDER_DEVICE=cpu` 仅本次运行生效,无文件/工具改动)**:
- website-camthink:**success,2 新 / 2 更 / 0 删**(1+1 chunk;该源有史以来首次 success,旧镜像下 KeyError 永败);
- woocommerce-mall:**success,4 新 / 12 更 / 0 删**(4×3 chunk;自 09-01T01:25 挂起的 4 文档全部落地);
- 其余 12 源:无变更,0 写入。
- SYNC_CREATED=6 文档(14 chunk) SYNC_UPDATED=14(计 chunk 口径 2+12) SYNC_SKIPPED=12 源 SYNC_DELETED=0 SYNC_FAILED=0(补齐后)。

## 7. PE-G007 Trust Boundary Verification — PASS(硬验收)

- **权威配置面**:`data_sources.config` 15 源均无 `channel_visibility` 键 → 按 RC 冻结语义(known source 缺省=公开)全库本即全公开;**不存在被标记受限的源,故无「内部→公开」泄漏面,也无「公开→受限」意外降级面**。
- **chunk 属性面(主防线)**:同步后聚合 `channel_visibility`:**api=126,400 / widget=126,400** —— 含本轮 +4 新对象在内,全库每对象双值,与权威配置一致;可见性写入路径(ingest→SourceConfig 默认)实测正确。
- **纵深防线**:RC backend `SourceVisibilityGuard` 已启用(PA-0D 启动日志),fail-closed(ghost 源/无快照一律 DENY)。
- **检索面佐证**:G009 冒烟引用 5 条全部为 camthink.ai 公开 blog(web_crawl),无任何内部源出现。
- 未暴露敏感内容;本 Gate 未引入也未消除任何 visibility 状态(标记内部源=产品决策,超出本 Gate 授权,见 §13 残留)。

## 8. PE-G008 Corpus Delta — PASS(每一项 delta 可解释)

| 维度 | BEFORE | AFTER | Δ |
|---|---|---|---|
| 总对象 | 126,396 | **126,400** | +4 |
| web_crawl | 357 | 359 | +2(2 篇新 blog,1 chunk/篇) |
| woocommerce | 99 | 101 | +2 净(12 chunk 写入,其中 10 为覆盖既往部分失败残留的同 UUID 对象) |
| github / filesystem | 125,459 / 481 | 不变 | 0 |
| 可见性 | api/widget 全量 | api/widget 全量 | 语义零变化 |

- 无删除(SYNC_DELETED=0)、无复制膨胀(deterministic UUID upsert)、无 collection/schema 变更;Weaviate 健康(聚合/Get/对象读取全通)。

## 9. PE-G009 Backend / Retrieval — PASS

- backend 升级全程未动:`Image=sha256:05f7d396…`、healthy、Restarts=0;`/health`=200。
- 受控检索冒烟(17:13:19Z,admin 渠道,1 次):`"How do I size an edge AI box for multiple CCTV cameras?"` → HTTP 200 / 15.0s / 321 token / `sources`+`done`,**无 error/declined**。
- 引用 5 条全部为 `www.camthink.ai/blog/*` 公开页,其中 **`/blog/validate-existing-cctv-footage-edge-ai-poc/` 正是本 Gate 数分钟前新灌入的文档** —— 新 corpus 经生产 backend(含可见性过滤)端到端可检索。
- 持久化:conversations/traces 105→**106/106**;新行 `is_answered=t`、`sources=5`、trace `type=rag, total_ms=14988`。

## 10. PE-G010 Sync Runtime Stability — PASS

- `tesla-t4-sync-cron-1`:running、**Restarts=0**、Image `05f7d396…`、git_sha `1ed84bb…`。
- 架构即「活跃一轮 + sleep 3600」:首轮 17:01:47–17:04:08(~2.3min),随后休眠;**下一轮 ≈ 18:04Z**(此后每小时)。无连续重同步环。
- 17:04 轮的两条 OOM failed 已由 17:10 受控补齐闭环(窗口已推进),下一轮预期全源无变更 success。残留风险见 §13。

## 11. PE-G011 Rollback / Recovery Assessment

- **SYNC_CRON_ROLLBACK**(容器面):`cd /home/ubuntu/ask-ai && ASKAI_IMAGE_TAG=latest docker compose -f deploy/prod/docker-compose.yml up -d sync-cron`(latest=`c87518e1`=bbfaa6a;旧镜像一直在位)。未执行。
- **CORPUS_RECOVERY**:**不需要** —— 本轮变更加性/幂等(净 +4 对象,0 删除,可见性语义零变化),无破坏性突变;若未来需要回退 corpus,冻结镜像为「本报告 §8 的 delta 记录 + sync_log 行 17:02–17:11」,不存在需要抢救的损伤。

## 12. Hard Acceptance 对照

| 项 | 值 |
|---|---|
| PE-G001~G011 | 全 PASS(G004=B) |
| BACKEND_CHANGED | **NO**(镜像/健康/重启计数逐项与 PA-0D 一致) |
| DB_SCHEMA_CHANGED | **NO**(仅数据行:sync_log +30、documents +6、conversations +1、traces +1) |
| SECRETS_CHANGED | **NO**(未读取/未修改;woo 凭证仅 DB 内在位,未入报告) |
| UNRELATED_GPU_SERVICES_CHANGED | **NO**(root/llama-server/neomind 进程与显存全程不变) |
| FULL_REINDEX_EXECUTED | **NO**(增量;未用 --reindex;未删 collection) |
| UNAUTHORIZED_PUBLIC_ACTIVATION | **NO**(未触 CORS/embed/nginx/DNS/站点) |

## 13. 残留与建议(非本 Gate 范围,供后续 Gate/运维裁决)

1. **GPU 容量是 sync embed 的常驻约束**:15.56G 中常驻占 15.37G,未来任何源内容变更的 embed 都会 OOM(本轮 17:04 两次 failed 已实证;旧镜相同)。建议专项裁决:释放显存(如 llama-server 驻留策略)或为 sync 配置 CPU/低显存 embed 通道。
2. **内部源标记尚未做**:信任边界机制已激活且 fail-closed,但 15 源均默认公开;若产品决定 firmware/support 等内部源不对 widget 透出,需(1)admin PATCH 源 config `channel_visibility`,(2)跑 `scripts/migrate_channel_visibility.py --apply` 回填存量 —— 属独立产品/实施决策。
3. woocommerce 4 文档曾在旧镜像下反复失败、根因(GPU OOM)直到本轮 RC 才留痕定性 —— RC 的错误留痕改进本身是一次验证收益。

## 14. Evidence 汇总

| 字段 | 值 |
|---|---|
| PRODUCTION_HOST | tesla-t4 (VM-0-4-ubuntu) |
| BACKEND_IMAGE / BACKEND_HEALTH | sha256:05f7d396…(git_sha 1ed84bb)/ healthy,Restarts=0 |
| BEFORE_SYNC_IMAGE / AFTER_SYNC_IMAGE | sha256:0c4b2c32… / sha256:05f7d396…(sha-1ed84bb) |
| AFTER_SYNC_GIT_SHA | 1ed84bbfcad08224c8c322f7c7a7a817b8916147 |
| SYNC_IMMEDIATE_ON_START | YES(while 循环首跑;已按变更对待) |
| IMPACT_DECISION | B(CONTROLLED INCREMENTAL SYNC) |
| CORPUS_COUNT_BEFORE / AFTER | 126,396 / 126,400 |
| SOURCE_DISTRIBUTION | github 125,459→同;filesystem 481→同;web_crawl 357→359;woocommerce 99→101 |
| VISIBILITY_BEFORE / AFTER | api=126,396 & widget=126,396 → api=126,400 & widget=126,400(语义零变化) |
| SYNC_CREATED / UPDATED / SKIPPED / DELETED / FAILED | 6 文档(14 chunk)/ 14 / 12 源 / 0 / 0(补齐后;首轮 OOM 2 源已闭环) |
| WEAVIATE_HEALTH | 健康(聚合/读取/写入全通,无 schema 变更) |
| TRUST_BOUNDARY_STATUS | PASS(与权威配置一致,全库默认公开,guard fail-closed 在位,无泄漏/降级) |
| POST_SYNC_RETRIEVAL_STATUS | PASS(HTTP 200,5 公开 blog 引用,含本 Gate 新灌文档;conv 持久化 is_answered=t) |
| SYNC_CRON_ROLLBACK | 可用未用(ASKAI_IMAGE_TAG=latest) |
| CORPUS_RECOVERY_REQUIRED | NO |

**STATUS = PASS**

## 15. STOP 声明

按合同止于本 Gate:未触 PA-0F、Multi-Site 激活、公开 embed/CORS 激活、最终上线验收。任何后续动作需新的显式授权。
