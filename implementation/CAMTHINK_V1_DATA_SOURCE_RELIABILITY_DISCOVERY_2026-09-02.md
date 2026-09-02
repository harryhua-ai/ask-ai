# CAMTHINK V1 — DATA SOURCE RELIABILITY & GOVERNANCE DISCOVERY

- 日期:2026-09-02
- 角色:Senior Engineering Investigator / Execution Agent(Discovery,非实现)
- 基线:`193f206a3d0e8695f1c40766a1ba54667fcba2fb`(main HEAD = 生产镜像 `sha-193f206` 冻结源)
- 生产部署报告:docs 仓 `8eff989` `implementation/CAMTHINK_V1_PRODUCTION_DEPLOYMENT_2026-09-02.md`
- 边界:只读调查;无生产访问 / 无生产变更 / 无产品代码修改;未做破坏性测试
- 证据标注:CONFIRMED(代码/配置/历史实证)/ INFERRED(推断,已注明)/ UNKNOWN / REQUIRES_RUNTIME_EVIDENCE / REQUIRES_READ_ONLY_PRODUCTION_EVIDENCE

---

## 1. Executive Summary

冻结原则"JOB SUCCESS != KNOWLEDGE HEALTH"在代码层面**结构性成立**,且当前实现没有任何机制能纠正这一点:

1. **健康 = 任务结果,与知识无关(CONFIRMED)**。`health` 由 30 天窗口内 `sync_log` 的 status 占比算出(`backend/api/admin/analytics.py` `_health`:≥0.9 healthy / ≥0.5 degraded / <0.5 critical / <3 次 insufficient_data / 禁用 disabled)。它不包含:语料数量、新鲜度、覆盖完整性、账本↔向量一致性。一个"每轮成功同步 0 篇"的源永远 healthy。
2. **系统没有"期望态"概念(CONFIRMED)**。EXPECTED EMPTY 与 UNEXPECTED EMPTY 不可区分:0 篇账本 + 0 向量在一致性校验里是 `is_healthy=True`。healthy + content=0 不是 bug,是当前语义下的"合法状态"——这正是管理员看不懂的根因。
3. **同步路径的删除安全不变量(PRUNE IS DOCUMENT-LOCAL)成立(CONFIRMED)**:ingest prune / delete_document / 孤儿 reconciliation 三类全部只按确定性 UUID 点删(`uuid5(source_id#chunk_index)`),结构上不可能触及兄弟文档(P0-A 修复 7c535d3 后,含生产复现回归测试)。
4. **但删除面存在两个残留风险(CONFIRMED 代码路径,未在生产观测到)**:
   - Admin 删除源的 Weaviate 清理段仍用 TEXT 属性 `equal` 过滤(`backend/api/admin/data_sources.py:408`)——与 P0-A 生产误删事故同款分词过匹配原语;
   - web_crawl "空发现"被判为**完整发现**:sitemap 返回 200 + 空/畸形 XML 时 `discovered=0/accepted=0`,覆盖率门被跳过,权威成员集=空集,已有孤儿在 no-change 轮 reconciliation 会被全部 `EXTRA_CONFIRMED_RETIRED`(G004"不完整发现不得退休"防线被空集绕过,`scripts/sync.py:346-391` + `:498-510`)。
5. **无重试/退避机制(CONFIRMED)**:除 web_crawl 单页 HTTP 3 次重试外,源级/条目级零重试。恢复依赖"失败不推进增量窗口 + 下轮重试"和 no-change 轮的一致性自愈;增量轮永远不触发一致性校验(见 §12)。
6. **可观测性:后端已记录大量诊断,UI 几乎全部不展示(CONFIRMED)**。coverage 行(成功轮也写)、三分类孤儿处置、一致性复验全部写入 `sync_log.error_detail`;`GET /sync-logs` 端点已存在但前端**零调用**(无"查看日志"入口)。管理员今天只能看到:最新一次同步的单字徽章 + 180px 截断的错误文本 + 30 天成功率 + "N 篇"。
7. **"内容 N 篇" = PG 账本行数(CONFIRMED)**(`documents` 表按 `split_part(source_id,'/',1)` 聚合),不是 Weaviate 实际对象数,也不是 chunk 数(chunk 数仅在 hover title 里)。账本↔向量漂移时该数字可以与真实知识量背离——历史上已多次发生。

结论:**PASS**——Planner 已可基于本报告定义 Reliability Closure 的 Product Contract;两处删除面残留风险建议列为阻断级(Gate A 先行)。精确的 per-source 零内容根因需要一次只读生产取证(§25)。

---

## 2. Investigated Baseline

| 项 | 值 | 证据 |
|---|---|---|
| 源码基线 | `193f206`(main,与冻结 SOURCE_COMMIT 一致) | `git rev-parse HEAD` |
| 调查方式 | 主 worktree 只读(`git worktree list` 确认主树即基线,未新建 worktree,符合 §19) | — |
| 生产 | `ghcr.io/harryhua-ai/ask-ai:sha-193f206`,deploy report 8eff989,FINAL PASS | docs 仓 |
| docs 仓注意 | 部署报告文件在工作区被删除(未提交),本报告证据取自 `git show HEAD:...`;工作区另有他窗未跟踪文件,本任务提交时不触碰 | `git status` |
| neoruntime 配置 | 主仓零引用(grep 全仓无命中)→ 是 DB 内 Admin 创建的源,配置不在仓内 | REQUIRES_READ_ONLY_PRODUCTION_EVIDENCE |

---

## 3. Current Data Source Architecture

组件(CONFIRMED):

- **配置权威**:`data_sources` 表(`backend/db/models.py:194-204`:id/type/product/enabled/config JSONB/sync_interval/created_at/updated_at)。`config/data_sources.yaml` 是 YAML 时代遗留,**运行时不可达**(仅 `scripts/migrate_yaml_to_db.py` 引用),且内容陈旧(无 website/neoruntime 系源,含 mac 本地路径)。
- **同步器**:`scripts/sync.py`(独立进程,cron 容器);Admin 手动同步在 backend 进程内 `asyncio.create_task` 调同一 `_sync_one`(`backend/api/admin/data_sources.py:575,615`)。
- **调度**:生产 `deploy/prod/docker-compose.yml:122` —— sync-cron 容器 `while true; do python3 scripts/sync.py || true; sleep 3600; done`(每小时全源顺序)。
- **账本**:PG `documents` 表(主键 `(content_hash, branch)`,含 source_id/source_type/product/chunk_count;`models.py:41-66`)。
- **向量库**:Weaviate 单 collection `Document`,全部源共用;chunk 属性含 source_id/chunk_index/content_hash/channel_visibility/branch/symbol_*(`backend/pipeline/ingest.py:145-192`)。
- **运行日志**:PG `sync_log` 表(`models.py:176-191`:status/started_at/finished_at/duration_ms/items_new/updated/deleted/unchanged/error_detail/triggered_by)。
- **持久化 vs 动态**:DataSource 表只存配置与 enabled;last_sync*/健康/doc_count 全部**运行时从 sync_log/documents 聚合**,不落列。

---

## 4. Supported Source Types

注册于 `ConnectorRegistry`(CONFIRMED,`backend/connectors/`):

| type | 文件 | 增量 | 删除检测 | 覆盖记账 | 权威成员集 | 特有行为 |
|---|---|---|---|---|---|---|
| `github` | github.py | API SHA 感知 → fetch+reset → `git log --since AMR` | `git log --diff-filter=D`(**受 30 天窗口上限约束**,超窗删除证据永久丢失,`_compute_since` MAX_INCREMENTAL_LOOKBACK) | 无 | 无(抽取集回退) | 无 429/rate-limit 处理;API 故障降级为"有更新"→整分支重拉;clone 失败报错不降级 |
| `filesystem` | filesystem.py | mtime > since | **恒返回 `[]`**(182-189 行诚实降级) | 无 | 无 | 根目录缺失:`rglob` 行为随 Python 版本可能是空产出而非报错(INFERRED,未测);二进制 `errors="replace"` 静默读入 |
| `web_crawl` | web_crawl.py | sitemap lastmod ≥ since(无 lastmod 永不进增量) | 仅全量轮状态文件差集 | `run_stats` full 轮全记账 | **有** `authoritative_source_ids()`(robots 通过即记,先于抓取) | 单页 HTTP 3 次重试(1s/2s 退避);薄内容 <200 chars 拒收;robots Disallow 遵从(robots 抓取失败=全允许);增量轮单页失败→异常→整轮 failed |
| `woocommerce` | woocommerce.py | `modified_after` | 恒返回 `[]` | 无 | 无 | **单页拉取 ≤100 商品**(超 100 静默截断,docstring 自认);HTTP 错误向上抛=整轮 failed |
| (local_git) | local_git.py | — | — | — | — | **未注册**,仅承载历史测试(决策 2A) |

五类差异要点:只有 web_crawl 有"发现完整性"与"权威成员资格"原语;git/fs/woo 的"抽取成功即枚举",其删除安全完全依赖 no-change 轮 reconciliation(抽取集回退)。

---

## 5. End-to-End Pipeline Map

CONFIRMED(全部文件/函数已核对):

```
配置        data_sources 表 → _load_configs_from_db (scripts/sync.py:99) → to_source_config (connectors/db_adapter.py)
触发        sync-cron 容器每小时 run_sync (sync.py:664) | Admin POST /data-sources/{id}/sync、/sync-all (data_sources.py:575,615,asyncio.create_task)
实例化      ConnectorRegistry.create (registry.py:73)
增量判断    fetch_changes(since) → 空则: _count_documents(sync.py:119,LIKE 前缀) → 有账本→_handle_no_change(:220) / 无账本→首次回退 fetch_all
since 窗口  _last_success_at(:193,失败不推进) → _compute_since(:174,缺省 24h,上限 30 天)
fetch       各 connector(§4)
过滤        github/fs: file_types+include_dirs+ExclusionPolicy(connectors/exclusion.py) | web_crawl: exclude_patterns/robots/薄内容 | woo: status=publish
分块        _is_code → chunk_code / chunk_document_semantic (pipeline/chunk.py, chunk_code.py);空内容→[]→计 0(合法空文档)
嵌入        BGEEmbedder.embed (embedder/bge.py),跨 doc 聚合批(64 doc,_ingest_doc_batch)
索引        insert_many(128/块)→ 失败对象 replace 回退 → replace 也失败计 failed → ingest_all 尾部统一 raise RuntimeError (ingest.py:384-428)
账本        _upsert_postgres(ingest.py:622,(content_hash,branch) 去重 + 同 source_id 旧版本行清理)
删除        fetch_deleted → pipeline.delete_document(ingest.py:575,UUID 点删+账本行删除)
覆盖门      仅 full 轮 run_stats:extracted==0→failed;<80%→partial,窗口不推进 (sync.py:606-628)
一致性      仅 no-change 轮:verify_source_vectors (services/vector_consistency.py:54) → 缺口 refill 定向重灌 + 孤儿三分类 reconciliation (sync.py:220-343, 394-515)
持久化      SyncLog finally 落库(失败隔离,commit 失败吞掉只打日志)
呈现        GET /data-sources(最新一次尝试) + GET /analytics/source-health(30 天窗口) → Admin UI (admin/src/pages/DataSources.tsx)
```

---

## 6. Scheduler / Trigger Model

CONFIRMED:

- **节奏**:生产固定每小时(sync-cron 死循环);`sync_interval` 字段有存储、有校验(`^\d+[hm]$`)、有 UI 表单,**但调度器从不读取**——纯死配置。管理员设 "1h/24h" 无任何效果(grep 全仓:无消费方)。
- **顺序单线程**:一次 run_sync 顺序同步全部 enabled 源,共享一个 Weaviate client + pipeline(sync-all 注释明确:避免并发 BGE embed 导致 T4 GPU OOM)。
- **重叠保护:无**。cron 容器与 backend 手动触发是**两个进程**,无任何锁/flock/互斥;backend 内单源 sync 与 sync-all 也可并发(create_task 无守卫)。同源并发双跑可能:双份 SyncLog、GPU OOM、账本 MAX(chunk_count) 读与 prune 的竞态(后果未测,UNKNOWN)。
- **启动行为**:sync-cron 容器启动立即跑一轮;backend 重启会丢失进行中的手动同步任务(客户端 5 分钟超时提示是唯一兜底)。
- **取消:不存在**。timeout:HTTP 层 20-30s;同步整体无超时。
- **`--reindex`**:删整个 collection 后全量重灌(期间服务不可用;ask-ai-eval skill 明文记录历史上曾误删 560k chunk 的教训)。`--dry-run` 只列举。

---

## 7. Source Membership / Identity Model

CONFIRMED:

- **source_id 格式**(文档级):github/fs = `{src_id}/{branch}/{rel}`;web_crawl = `{src_id}/{url_path}`(canonical);woo = `{src_id}/{product_id}`。数据源级前缀 = `split_part(source_id,'/',1)`。
- **chunk 身份**:`uuid5(NAMESPACE_URL, f"{source_id}#{chunk_index}")`(ingest.py:35)——确定性、幂等、可点删。
- **账本**:documents 主键 `(content_hash, branch)`;内容变更时清理同 source_id 旧 hash 行(_upsert_postgres:642-648)。
- **"谁属于这个源"**:
  - web_crawl 全量轮:`authoritative_source_ids()`(robots 通过即入集,含本轮抓取/抽取失败页)= 权威成员;增量轮返回 None(无证据)。
  - github/fs/woo:无原语,reconciliation 回退"本轮抽取成功集合"。rename → 新 source_id 出现,旧 id 靠下一轮 no-change reconciliation 按抽取集缺席退休(仅当 fetch_all 成功)。
- **删除事件面**:web_crawl 仅全量轮差集(增量轮视野只有 sitemap,会误删 BFS 发现页——已修);github 窗口内 D-filter(**30 天窗口上限 → 长期宕机后删除证据丢失**,INFERRED:行为=删除不被发现,残留变孤儿待 reconciliation);fs/woo 恒无删除事件。

---

## 8. Fetch / Filter / Parse Behavior

CONFIRMED(与 §4 表互补):

- **web_crawl**:重试 3 次(退避 1s/2s)后 RuntimeError;单页失败跳过并记账(不拖垮整轮);`successes==0 && failures>0` → 生成器收尾 raise(整轮 failed)。**畸形/空 sitemap(200 状态)不 raise**,见 §11 风险。fetch_success+parse_zero 与"源真空"的可区分性:full 轮靠 run_stats(discovered/accepted/extracted/failed/rejected)可区分;**增量轮不可区分**(run_stats 只记 extracted,单页异常直接炸整轮)。
- **薄内容**:web_crawl <200 chars → rejected.low_content(计入 run_stats,可观测);fs 二进制 `errors="replace"` 乱码入语料(无最低内容门槛,INFERRED 可产生垃圾 chunk);woo 空 description 拼出仅价格/SKU 的短文档(无门槛)。
- **github**:clone 失败=整源 failed(4A 决策,不降级逐文件 API);API SHA 故障降级"有更新"→多余 fetch(可用性优先);token 最小权限启动校验(github.py:341)。
- **FILTER-OUT 可观测性**:github/fs 的"全部文件被过滤→0 篇"**不可观测**(无任何计数,SyncLog 记 success/0);web_crawl 的 rejected 有计数。这直接支撑 §16 的零内容成因分类。

---

## 9. Chunk / Embed / Index Behavior

CONFIRMED(ingest.py):

- 分块:语义分块(600 tokens/50 overlap,##/### 结构切分+硬切滑窗)或代码 AST 分块;**空内容→0 chunk→计 0,视为合法空文档**(218-220 行),与"分块失败"不可区分(但分块异常会进 failed)。
- 嵌入失败:批量 embed 异常→逐 doc 回退→仍失败进 failed 清单→ingest_all 统一 raise→**整轮 failed**(384-428 行,契约:计 0 ≠ 失败)。
- 索引:insert_many(128/块)→ 对象级失败 replace 回退(预计算向量,不重 embed)→ replace 也失败=该 doc 彻底失败。**部分失败已写入的对象保留**(幂等 UUID),整轮标 failed,窗口不推进。
- GPU 资源失败:BGE OOM 会以 embed 异常形态出现→同上;无分级处理。
- PARSED>0 但 INDEXED=0:可能(doc 级全部写失败),表现为 SyncLog failed + error_detail 异常文本;**部分 doc 失败同样整轮 failed**(全有或全无的轮级语义)。

---

## 10. Corpus Integrity Model

CONFIRMED:

- **期望**:PG `SUM(chunk_count)`(按源前缀 LIKE);**实际**:Weaviate 全 collection **迭代器全扫 + 客户端前缀过滤**(vector_consistency.py:87-99;TEXT like/like 分词污染历史教训,迭代器是权威口径)。**每次校验扫全库**(O(全库) per source;当前 126k chunks×每小时×15 源=可接受但随语料线性恶化,性能观察项)。
- **缺口分类**:整篇缺失(pg 有 wv 无)/ chunk 集合不一致 / 多余 chunk(stale,仅计数)/ 孤儿(wv 有 pg 无,orphan_chunks 明细)。
- **Admin "内容" = doc_count = 账本行数**(analytics.py source-health,`split_part` 首段聚合,cc09cce 修复);chunk_count 仅 hover 可见。**该数字度量的是账本,不是知识**——账本↔向量漂移时失真(历史:Weaviate 821 chunks vs PG 2 行;web_crawl 359→163 等)。
- 跨源类型可比性:同为"账本文档数",但文档语义不同(一个页面/一个文件/一个商品),可比但需注明口径;重复检测无(重复 URL 已由 canonical_url 防住,重复内容文件未防——不同路径同内容 = 两行账本,by design)。

---

## 11. Prune / Delete Safety(关键安全调查)

**同步路径:不变量成立(CONFIRMED)**。全部删除点:

| 删除点 | 机制 | 证据 |
|---|---|---|
| ingest `_prune_stale_chunks` | 只删本文档 `uuid5(source_id, current..previous-1)`;上界=写前账本 MAX(chunk_count);账本不可读→**fail-safe 不删** | ingest.py:345-382;P0-A 事故根因(TEXT equal 分词过匹配,生产 359→163)已由 7c535d3 消除+真实 Weaviate 复现回归测试 |
| ingest `delete_document` | 账本计数有界 UUID 点删;无账本行→跳过 Weaviate 删除(残留交一致性校验) | ingest.py:575-616 |
| reconciliation 退休 | `EXTRA_CONFIRMED_RETIRED` 仅当 ①fetch_all 成功 ②覆盖率≥80% ③**不在权威成员集**;逐 UUID delete_many;读失败/计数不一致/成员集内/发现不完整→一律保留 | sync.py:394-515 |
| Admin 删除源 | 见下风险 ① | data_sources.py:387-482 |
| `--reindex` | 删整个 collection(显式运维动作) | sync.py:701-714 |
| web_crawl fetch_deleted 差集 | 状态文件差集→delete_document(文档局部) | web_crawl.py:674-686 |

**瞬时失败→删除?** 同步路径已防御:fetch_changes 异常→整轮 failed(不到删除);reconciliation 发现失败→complete=False→保留;权威成员资格≠抽取成功(9bbf587 修正)。**两个残留缺口**:

1. **[P0 候选] Admin 删除源仍用 TEXT equal 删除**(`data_sources.py:408`):
   `collection.data.delete_many(where=Filter.by_property("source_id").equal(sid))`。
   P0-A 已实证 TEXT equal 是分词语义(`equal("site/blog")` 命中 `site/blog/ai-species`)。删除源 "neoruntime" 时,账本内 sid 如 `neoruntime/main/README.md` 的 equal 匹配可命中**其他源**共享 token 的对象(如 `neoruntime-apps/main/README.md` 共享 main/README.md token),造成跨源误删。后续孤儿兜底段是迭代器+UUID(安全),但被 equal 误删的他源对象**不在兜底范围**(前缀边界外)。账本还在→他源下轮 no-change reconciliation 可自愈(INFERRED),但期间检索静默缺知识。**建议与 P0-A 同款修复(UUID 点删)作为 Gate A 一部分**。
2. **[P0 候选] 空发现=完整发现**(sync.py:346-391 + web_crawl.py:597-645):
   sitemap 请求 200 但返回畸形/空 XML → `parse_sitemap_index/parse_urlset` 返回空(不抛错)→ `discovered=0, accepted=0` → 覆盖率检查 `if accepted > 0 and ...` 跳过 → `complete=True`;`authoritative_source_ids()` 返回**空集**(非 None)→ no-change 轮若存在任何孤儿(当前生产 web_crawl 就有 5 个 unresolved 孤儿),`complete and sid not in membership_ids(∅)` 全部成立→**批量 EXTRA_CONFIRMED_RETIRED**。账本在册文档不删账本行,但向量被删的孤儿需源恢复后重灌;账本在册文档此刻不受影响(它们不是孤儿)。G004E 测试覆盖"枚举不完整的退休抑制",**未覆盖"空枚举被判完整"**(测试代理同样点名此为最危险未测行为)。触发前置条件:恰好该轮一致性报告不健康(存在孤儿/缺口)——生产现状满足。WAF/CDN 以 200 返回挑战页是真实世界常见形态。
   缓解建议(供 Planner):full 轮 `discovered==0`(或 accepted==0)→ 视为 incomplete(keep+report)。

LIKE 通配符家族(sync.py:136 `_count_documents`、vector_consistency.py 前缀查询)未 autoescape——AC-FIX-01(262c1fc)只修了 Admin 删除路径;源 id 含 `%/_` 时可过匹配(P3,低概率,同类未清)。

---

## 12. Retry / Recovery Model

CONFIRMED:

- **自动重试:不存在**(除 web_crawl 单页 HTTP 3 次)。无 backoff、无 item 级重试、无 resume。隐式重试=「失败不推进增量窗口 → 下一轮 cron 覆盖缺口」(e15a187)。
- **自愈**(仅 no-change 轮触发!):`_handle_no_change` → verify → 缺口 refill 定向重灌 + 孤儿三分类 → 复验收敛 success / 不收敛 partial。7599e8a 废除了"refill 空即全量重灌"旧自愈(不收敛空转根因)。
- **关键盲区(CONFIRMED,结构性)**:**增量轮(有变更)永不触发一致性校验**——校验只在 `fetch_changes` 返回空时发生。一个"每次都有 ≥1 页 lastmod 变更"的活跃源,其账本↔向量漂移**永远不被检验**;只有静默源(多数 git 源常态)才有自愈机会。website-camthink 属于"经常有变更"类,其间漂移不可见。
- 崩溃中途:已写入对象幂等保留;SyncLog 该轮缺失(该源本轮无记录);下轮按旧窗口重试。容器重启:同上+当轮剩余源顺延到下小时。
- 幂等性:确定性 UUID+content_hash 去重 ⇒ 重跑安全(CONFIRMED,含回归测试 G009)。
- 手动恢复手段:`POST /{id}/sync`(=增量)、`--reindex`(全量重灌,危险级)、Admin 删除重建源。无"单源一致性修复"按钮(自愈被动触发)。

---

## 13. Current Health Semantics

CONFIRMED(analytics.py `_health` + UI 映射):

| 状态 | 语义 | 计算 |
|---|---|---|
| healthy 正常 | 30 天窗口成功率 ≥90%(**partial 计入分母不计入成功**) | sync_log 计数 |
| degraded 不稳定 | ≥50% | 同上 |
| critical 严重 | <50% | 同上 |
| insufficient_data 样本不足 | 窗口内 <3 次 | MIN_SYNC_RUNS=3 |
| disabled 已禁用 | 不评价 | enabled=false |
| 最新同步徽章 | 成功/失败/**补齐(partial)**/从未同步 | 最近一次**尝试** |

- **"补齐(partial)"一词混装三种语义**(error_detail 文本才区分,而 UI 成功轮不显示 error_detail、partial 轮 180px 截断):①全量覆盖 <80%(知识不完整);②一致性校验自愈未收敛(账本↔向量缺口);③三分类孤儿待裁决(SAFE BUT INCOMPLETE)。UI 层面 **SAFE BUT INCOMPLETE / UNSAFE / TRANSIENT 不可区分**(§17 结论)。
- **健康不含**:语料量(0 篇可 healthy)、新鲜度(last_success 90 天前仍可 healthy,只要还在跑且成功)、覆盖完整性、一致性。健康=纯任务执行史。
- 阈值/窗口/分母语义仅存在于 hover tooltip(近30天 N 次:M 成功/P 补齐/F 失败);无文档化 UI。

---

## 14. Current Admin API Semantics

CONFIRMED:

| 端点 | 内容 |
|---|---|
| GET /data-sources | 全表+每源最新一次尝试(started_at/status/error_detail);**无内容计数** |
| GET /analytics/source-health?days | 窗口计数四元组+health+doc_count/chunk_count+当前态;幽灵行(product=unknown)可见 |
| GET /sync-logs | **最丰富的诊断端点**(per-run duration/items_*/error_detail/triggered_by,可按 source/status 过滤分页)——**前端零调用,死端点** |
| POST /data-sources/{id}/sync、/sync-all | 后台 create_task,立即返回;enabled 校验;github 分支校验;**无并发锁** |
| POST /{id}/upload、preview-* | C9 上传/目录树/分支/文件类型预览 |
| PATCH /{id} | 任意字段含 enabled;无类型变更防护 |
| DELETE /{id} | 502 fail-safe(清理失败保留全部状态可重试);同事务删配置+账本;**Weaviate 清理段见 §11 风险①** |

后端已有而 UI 未用:全部 sync-logs 字段;成功轮 coverage 行;`items_unchanged`(模型有、schema 甚至没透出);created_at/updated_at。

---

## 15. Current Admin UI Semantics

CONFIRMED(DataSources.tsx / useDataSources.ts / techInsight.ts):

- 页面=表格:类型/产品/启用徽章/健康(30 天)/最新同步/内容("N 篇")/同步按钮;行内编辑表单;window.confirm 删除。
- 完整"后端字段→UI 显示/忽略"映射与 12 条信息缺口见 UI 调查附录(§15.1 摘要)。核心缺口:
  1. 无同步历史页(sync-logs 死端点);2. 成功轮隐藏覆盖降级证据;3. 成功率≠内容完整性(无 doc_count 趋势/期望值/最近灌入时间);4. 一致性细节(缺口 X/Y、孤儿三分类)不可见;5. chunk_count 仅 hover;无文档清单;6. 样本不足陷阱(<3 次永不评价);7. 错误文本 180px 截断不可复制;8. "同步中"是客户端推断,刷新即丢;9. duration/finished_at 不透出;10. 幽灵源在数据源页不可见(join 丢弃);11. created_at/updated_at 隐藏;12. 阈值无解释。
- 管理员今天**无法**从 UI 回答:该源完整吗/为什么 0 篇/什么失败了/失败多少/现存知识安全吗/在重试吗/需要我做什么——与产品观察一致。

---

## 16. Zero-Content Source Investigation(neoruntime / neoruntime-apps)

主仓零引用 → 两源是 DB 内 Admin 创建(github 类,依产品族命名习惯)。其 config/账本/日志不在仓内,精确根因 **REQUIRES_READ_ONLY_PRODUCTION_EVIDENCE**(§25)。代码支持的成因分类(按可能性排序,全部 CONFIRMED 代码路径):

| 类 | 机制 | 同步表现 | 健康表现 |
|---|---|---|---|
| B/C | **repo 无命中 file_types 的文件**(或全部被 ExclusionPolicy/include 规则滤掉)→ fetch 成功产出 0 篇 | 首次回退 fetch_all=0 篇→success;以后每轮 fetch_changes 空→existing=0→再回退→success | success 记录→healthy+0 篇(完全自洽) |
| A | 源真空(空仓/空分支) | 同上 | 同上 |
| G | **计数口径漂移**:source_id 复合前缀与数据源 id 不一致(如源 id 改名,旧语料挂旧前缀)→ doc_map 查 0 | 每轮按"首次"回退全量灌入**新**前缀(应能长出来);若 fetch 恒失败则 failed | 取决于 fetch 结果 |
| E/F | 0 chunk/embed 失败 | 失败会 raise→failed,**不会 healthy** | 排除(与 observed healthy 矛盾) |
| H | 账本行被清+向量在:0 行 0 期望→is_healthy→success/unchanged | no-change 路径 | healthy+0,但孤儿向量存在(reconciliation 只在不健康时才跑——0 期望 0 实际"健康"→**永不自愈**,INFERRED) |

结论:healthy+0 在当前语义下是结构合法状态;最可能是 **B/C(过滤后零合格文件)**,精确到每个源需只读取证:①`data_sources` 两行 config;②`documents` 前缀计数;③最近 sync_log.error_detail;④对照上游 repo 文件树与 file_types。

---

## 17. website-camthink Partial Analysis

以部署报告(8eff989)+ 代码实证(CONFIRMED):

- **为何 partial**:5 个页面仍在权威成员集(robots 通过)但持续抽取失败——`/shop/`(404 重试耗尽)、`/register/`、`/tools/`、`/product/`(404)、`/solutions/infrastructure-monitoring/`(薄内容)→ 每轮 `EXTRA_UNRESOLVED_ORPHAN=5` 保留 → 复验 expected=361 vs actual=366 → 不收敛 → partial。**保守设计产物,非不安全行为**。
- **为何 5 个退休是安全的**:company、product-category/ai-cameras(+/feed)、ne101-cameras、ne301-cameras 已不在完整权威枚举 → `EXTRA_CONFIRMED_RETIRED` 按各自确定性 UUID 精确删除(各 1 chunk)。删除范围=文档自身 UUID,结构上不可能误伤。
- **为何 MISSING_LEGITIMATE=0 重要**:账本在册文档零缺失=现存知识无损失;126,418→126,413 的差值恰等于 5 个退休 ghost 的 chunk 数——**有账可查的精确收缩,非腐蚀**。
- **366/361 不是损坏**:361=账本期望;366=实际存量(=361 期望 + 5 个账本行已无的失败页存量);多出的 5 个正是"保留待裁决"的 unresolved。数学自洽。
- **当前健康模型能否区分 SAFE BUT INCOMPLETE / UNSAFE / TRANSIENT?不能。** 三者都塌缩成同一个"补齐"徽章;区分信息在 error_detail 文本里,而 UI:成功轮不显示、partial 轮 180px 截断 + hover。语义区分目前**只存在于后端文本协议**,不存在于产品呈现层。

---

## 18. Reliability Failure Taxonomy

基于真实代码(确认存在的类;severity 判据见任务书):

| # | 类别 | 失败模式 | 现有检测 | 现行为 | 语料风险 | 自动恢复 | 可观测 | 严重度 |
|---|---|---|---|---|---|---|---|---|
| 1 | PRUNE(Admin 删除) | TEXT equal 分词过匹配跨源删除 | 无(静默) | 误删他源 chunk | **跨源丢失**(账本可自愈) | 间接(下轮 reconciliation) | 无 | **P0** |
| 2 | DISCOVERY/MEMBERSHIP | 空/畸形 sitemap 判"完整发现"→空成员集退休孤儿 | 无 | 批量 EXTRA_CONFIRMED_RETIRED | web_crawl 孤儿批量删+账本文档向量缺口 | 源恢复后 refill | partial 文本(不显示) | **P0** |
| 3 | MEMBERSHIP(github) | 删除证据受 30 天窗口上限,超窗丢证据 | 无 | 删除不被发现,残留孤儿 | 陈旧知识滞留(不丢失) | reconciliation 可清 | 孤儿计数 | P2 |
| 4 | FETCH(web_crawl) | 增量轮单页失败→整轮 failed | SyncLog failed | 窗口不推进,下轮重试 | 无 | 下轮 | 最新同步徽章 | P3 |
| 5 | FETCH(woo) | >100 商品静默截断(单页拉取) | 无 | 第 2 页起商品永久缺席 | **持续性知识缺口** | 无 | 无 | **P1** |
| 6 | FETCH(github) | 无 429 处理;API 故障降级全量 fetch | 无 | 限流期反复全量重拉 | 无(GPU/带宽浪费) | 自限 | 无 | P2 |
| 7 | FILTER | github/fs 全过滤→0 篇不可观测 | 无 | success/0 | 知识缺口伪装健康 | 无 | **无** | **P1**(与 §16 直接相关) |
| 8 | PARSE | fs 二进制 replace 乱码入语料 | 无 | 垃圾 chunk 入库 | 检索噪声 | 无 | 无 | P2 |
| 9 | INDEX | 部分 doc 写失败→整轮 failed;已写部分保留 | SyncLog failed | 窗口不推进 | 无 | 下轮幂等 | failed 徽章 | P3 |
| 10 | LEDGER | 账本↔向量漂移(历史多起) | no-change 轮校验 | refill/三分类 | 有缺口时检索缺失 | **仅 no-change 轮** | partial 文本 | **P1**(校验触发面缺口) |
| 11 | CONSISTENCY | 增量活跃源永不校验(§12 盲区) | 无 | 漂移无限累积 | 同上 | 无 | 无 | **P1** |
| 12 | SCHEDULER | cron 与手动同步无锁并发 | 无 | 双跑(GPU OOM/竞态未测) | 竞态 UNKNOWN | 无 | 无 | P1 |
| 13 | RETRY | 无退避/无 item 重试 | — | 轮级隐式重试 | 无 | 隐式 | failed 徽章 | P2 |
| 14 | RECOVERY | `--reindex` 全库删除重建,无零停机路径 | — | 服务中断窗口 | 操作风险高 | — | 无 | P2 |
| 15 | OBSERVABILITY | 成功轮覆盖证据/三分类/时长不透出;sync-logs 死端点 | — | — | 无(看不见) | — | **核心缺口** | **P1**(产品目标主战场) |
| 16 | ADMIN_SEMANTICS | healthy+0 合法;partial 一词三义;样本不足陷阱 | — | 管理员无法决策 | — | — | **核心缺口** | **P1** |
| 17 | EXPECTED-STATE | 无期望态概念,EXPECTED/UNEXPECTED EMPTY 不可分 | — | — | — | — | 无 | **P1**(语义地基) |

不存在的类:CONNECTIVITY(连接失败如实 failed)、CONFIGURATION(分支校验/clone 冲突校验已建)、CHUNK(空块合法、异常 failed)。

---

## 19. Expected-State / Coverage Gap

CONFIRMED:**不存在任何"该源应有知识"的概念**。enabled 只决定"跑不跑";product 只是标签。EXPECTED EMPTY 与 UNEXPECTED EMPTY 完全同构(0 期望+0 实际=healthy)。现有字段可承载未来语义的:DataSource.config(JSONB 自由)、enabled、product、sync_interval(死配置,可复活为调度语义)。REQUIRED/OPTIONAL/DISCOVERY/EXCLUDED 等概念需新增配置与一套 health 语义(**Planner 决策项,本任务不实现**)。工程上最小充要:per-source「期望文档数下限/期望非空」+ 校验点(no-change 轮 verify 已有挂点)+ health 融合规则。

---

## 20. Observability Gap Analysis

对照目标漏斗 DISCOVERY→FETCH→FILTER→PARSE→CHUNK→INDEX→CORPUS:

| 漏斗段 | web_crawl full 轮 | 其他源/其他轮 | 缺口 |
|---|---|---|---|
| discovered | run_stats.discovered✓(error_detail) | 无 | github/fs/woo 无发现计数 |
| accepted(过滤后合格) | ✓(rejected 三因计数) | 无 | FILTER 段盲区(§18#7) |
| fetched/failed | ✓(+failed_urls 前 5 预览) | github/fs 单文件 warning 仅日志 | 无 item 级持久化 |
| parsed/parse_failed | extracted/failed✓ | 无 | — |
| chunked | **无**(未记账) | 无 | 全源盲区 |
| embedded/indexed(index_failed) | 无(仅 items_new/updated=成功 chunk 总和聚合) | 同 | 失败仅整轮 failed |
| pruned/retired | items_deleted+三分类文本✓ | items_deleted(github 窗口内) | reconciliation 计数在文本不在字段 |
| CORPUS | doc_count/chunk_count(账本口径) | 同 | 非向量实盘口径;无趋势 |

结论:漏斗**骨架已存在**(web_crawl run_stats+SyncLog),但 ①仅覆盖 web_crawl full 轮;②chunked/embedded/indexed 全源缺失;③持久化形态是文本 error_detail 而非结构化字段(UI 无法消费);④"管理员定位内容在哪一段消失"今天只有 web_crawl 部分可答。架构上可干净支撑:SyncLog 加 JSONB run_stats 列 + connector 统一 stats 协议(供 Planner 参考,不实现)。

---

## 21. Recovery Capability Matrix

| 故障 | 现行为 | 恢复能力 | 现存语料安全? |
|---|---|---|---|
| GitHub 暂时不可用 | clone/fetch 异常→整轮 failed | RETRY ONLY(下轮) | 安全 |
| GitHub 429 限流 | 无处理→反复全量 fetch | RETRY ONLY(可能循环) | 安全 |
| 网页 404 | full 轮:计数跳过;增量轮:整轮 failed | full:记 rejected;增量:RETRY ONLY | 安全 |
| 网页超时 | 3 次重试后同上 | RETRY ONLY | 安全 |
| 薄内容 | rejected.low_content 永久拒收 | **NO RECOVERY**(需产品调阈值) | 安全 |
| sitemap 畸形(200) | **静默空发现→§11#2 风险** | UNKNOWN | **孤儿有风险** |
| filesystem 根目录消失 | rglob 空(INFERRED)/或异常 | UNKNOWN(未测) | 安全方向(不删) |
| 解析器错误 | 单 doc failed→整轮 failed | RETRY ONLY | 安全 |
| 嵌入错误/GPU OOM | 整轮 failed | RETRY ONLY | 安全(幂等) |
| Weaviate 写错误 | 对象级回退→doc failed→整轮 failed | RETRY ONLY | 安全 |
| 部分批失败 | 已写保留,整轮 failed | RETRY ONLY | 安全 |
| 同步进程崩溃 | 该轮无 SyncLog;部分写入保留 | 幂等重跑 = AUTO RECOVER(下轮) | 安全 |
| 容器重启(中途) | 同上+剩余源顺延 | AUTO(下小时) | 安全 |
| 账本不一致(行丢) | no-change 轮零 embedding 重建账本行 | AUTO(有条件,见 §12 盲区) | 安全 |
| 期望/实际不匹配 | refill 定向重灌+三分类 | AUTO(仅 no-change 轮) | 安全 |
| **Admin 删除源(§11#1)** | equal 过匹配误删他源 | 间接自愈(他源下轮 reconciliation) | **临时不安全** |

---

## 22. Existing Test Coverage / Missing Tests

概览(详表见调查底稿;此处为高风险缺口,全部经代理逐文件核实):

**覆盖良好(CONFIRMED)**:P0-A 文档局部 prune(18 用例含真实 Weaviate 复现,但 ⚠️ 真实 Weaviate 用例在无 21100 端口环境静默 skip——CI 只跑 mock 层);三分类生命周期(G003/G004a-e/G005/G006/G009,454 行);web_crawl 覆盖记账/robots/薄内容/增量删除安全;一致性校验 like 污染;健康语义(分母口径/阈值/disabled/样本不足);Admin 删除生命周期(502 fail-safe/通配符/复活防护)。

**危险未测(TOP)**:
1. **空枚举"完整发现"→批量退休**(§11#2)——零覆盖;
2. Admin 删除源 Weaviate equal 段——mock 测试不触真实分词语义(与 P0-A 同款盲区);
3. `POST /{id}/sync` 成功路径零测试;
4. PATCH enabled 切换语义零测试;
5. cron×手动并发双跑零测试(锁也不存在);
6. crash mid-sync(写库/账本/SyncLog 三窗口)零测试;
7. woo 分页截断(>100)零测试;
8. filesystem 根目录缺失零测试;
9. github 429/repo-deleted 零测试;
10. robots.txt 抓取失败语义未定义未测试;
11. CLI `_parse_args/main` 零测试;
12. `_health` 边界值(恰 0.9/0.5)未测。
测试基建:TEST_DATABASE_URL 指向真实 PG;`_LEGACY_LOCAL_GIT` skip 使 DB 驱动 github 端到端部分停摆;共享 ask_ai_test 库并行期会被反复重建(既有记忆)。

---

## 23. Relationship to Answer Correctness

NE503 固件下载案例(不修复,仅归因):数据源失败类中可贡献「知识缺口→检索空→LLM 用兄弟产品内容补位」的:**#5 woo 截断、#7 过滤不可见、#10/#11 一致性盲区、#3 陈旧滞留**,以及最根本的**源本身没有该文档**(ne503-aipc-sdks/meta-hailo-os 是否含固件下载页 = 取证项)。检索侧:search.py 的 product_filter 是可选精确过滤,rag.py 的 product_hint 是**软加权非硬过滤**(rag.py:131-164)→ 兄弟产品串扰主要属 **Answer Correctness Gate**(检索策略/提示词),数据源侧的义务是把"缺口存在且可定位"变成可观测事实。

---

## 24. ask-ai-eval Capability Assessment

已定位 `~/.zcode/skills/ask-ai-eval/SKILL.md`(CONFIRMED,未修改未运行):

- 能力:SSE `/api/ask` 回归评估(精准答率/有据率/拒答率/延迟 p50-p99,按意图分桶)、并发压测、15 项边界、从 conversations 收集新题、调优建议;数据存 Knowledge 知识库;默认打**生产** `wiki-data.camthink.ai`。
- 与 Corpus/Answer 验收的关系:它是**答案层**验收器,不直接测语料;但「数据源变更后跑回归对比」是其显式设计场景,可作未来 Corpus Closure 的下游验收(知识缺口会表现为拒答率/有据率劣化)。
- 边界记录:skill 自带警告"勿用 --reindex 做评估前刷新"(历史误删 560k chunk);本任务未获生产评估授权,**未运行**。

---

## 25. Required Read-Only Production Evidence

REQUIRES_READ_ONLY_PRODUCTION_EVIDENCE(仓库证据不足的原因:两源配置仅存生产 DB):

1. neoruntime / neoruntime-apps 零内容根因:
   - `SELECT id,type,product,enabled,config FROM data_sources WHERE id LIKE 'neoruntime%';`(看 type/file_types/repo_url)
   - `SELECT split_part(source_id,'/',1), count(*), sum(chunk_count) FROM documents GROUP BY 1;`(账本口径)
   - `SELECT source_id,status,error_detail,started_at FROM sync_log WHERE source_id LIKE 'neoruntime%' ORDER BY started_at DESC LIMIT 10;`
   - 对照上游 repo 文件树 vs file_types(可用 GitHub API 只读,不需要 SSH)
2. (可选)验证 §11#2 触发面:生产 web_crawl 最近 error_detail 中 discovered/accepted 值(部署报告已有 371→366 记录,基本充分)。
3. (可选)`sync_log` 中 `triggered_by` 分布验证 cron/手动重叠频率。

上述全部只读 SQL/API;无需 SSH 生产、无需 Weaviate 写。

---

## 26. Recommended Engineering Boundaries for future Closure

依据证据建议的 Gate 拓扑(名称示意,Planner 定夺):

- **Gate A — 删除安全与发现完整性(P0,建议阻塞后续)**:`data_sources.py` 删除清理段 UUID 化;空枚举(.discovered==0/accepted==0)判 incomplete;LIKE autoescape 同类清理;对应回归测试(真实 Weaviate 门)。文件面:sync.py、data_sources.py、web_crawl.py。**先行,独立可验收**。
- **Gate B — 健康语义与期望态**:EXPECTED-STATE 配置+health 融合(healthy+0 治理);partial 拆义(SAFE-INCOMPLETE/DEGRADED/UNSAFE);sync_interval 处置(生效或移除)。文件面:analytics.py、schemas、models(迁移)。依赖 Gate A(语义建立在安全上)。
- **Gate C — 可观测性落地**:run_stats 结构化(JSONB)+ chunked/embedded/indexed 记账 + sync-logs UI(死端点复活)+ 错误全文展示。文件面:sync.py、analytics.py、admin UI。与 B 可并行(B 供语义,C 供证据)。
- **Gate D — 恢复与调度**:并发锁/单源互斥;一致性校验触发面扩展(增量轮抽样或定期);(可选)item 重试策略。文件面:sync.py、data_sources.py。依赖 A。
- **Gate E — Admin 诊断与处置动作**:文档清单/差距视图/建议动作(重灌/修复指引)。依赖 B+C 的数据。

重叠热点:scripts/sync.py 出现在 A/B/C/D(串行化或分契约);admin UI 集中在 C/E 可并行。是否并行:A 单独先行;B∥C;D 在 A 后;E 最后。

---

## 27. Open Product Decisions for Planner

1. 零内容源(neoruntime 系):期望态语义前,先只读取证;然后裁决 修配置 / 保留为 EXPECTED EMPTY / 禁用退休。
2. 「内容 0 篇但正常」是否允许存在(EXPECTED EMPTY 语义与配置形态)。
3. partial 拆义后的产品呈现(SAFE BUT INCOMPLETE vs TRANSIENT vs UNSAFE 的命名与动作指引)。
4. 5 个 unresolved 页面(/shop/、/register/ 等)的产品处置(修源站内容 vs 调 min_content_chars vs 排除),部署报告已挂起待裁。
5. sync_interval:复活为真实调度语义,还是删除字段(UI 诚实话)。
6. woo >100 商品:立项分页修复(小改动可并入 Gate A/D)。
7. 健康阈值/窗口/样本数(0.9/0.5/3/30d)是否随新语义调整。
8. `--reindex` 的替代(零停机双 collection 切换)是否立项。

---

## 28. Risks / Unknowns

- 生产 DB 中两源真实配置未知(§25 可解)。
- Weaviate TEXT equal 过匹配的确切分词规则随版本可能不同——但 P0-A 生产实证已足够定级(保守假设可过匹配)。
- cron×手动并发的实际竞态后果未测(UNKNOWN;锁缺失本身 CONFIRMED)。
- filesystem rglob 在生产 Python 版本对缺失根目录的行为(空 vs 异常)未在目标环境验证。
- 空 sitemap 触发概率未知,但 WAF/CDN 200 挑战页是常见形态;且生产**现在**就存在 5 个孤儿(触发前置条件已满足)。
- ask_ai_test 共享库并行重建问题会持续干扰并行 Gate 的测试稳定性(既有记忆)。

---

## 29. Final Discovery Status

**PASS**

判据:AC1-AC17 全部满足——全生命周期已映射(§3-§15);健康语义/内容计数口径已从代码确立(§10/§13);删除面安全已逐路径核查并锁定两个残留缺口(§11);恢复/重试已建模(§12/§21);零内容与 website-partial 已解释到仓库证据边界并注明取证项(§16/§17/§25);taxonomy/可观测缺口/测试缺口/ask-ai-eval/未来 Gate 拆分齐备(§18-§24/§26);零生产访问、零实现(全程只读)。

---

## 附:交付信息

- STATUS: PASS
- BASELINE_COMMIT: 193f206a3d0e8695f1c40766a1ba54667fcba2fb
- REPORT_PATH: docs/implementation/CAMTHINK_V1_DATA_SOURCE_RELIABILITY_DISCOVERY_2026-09-02.md
- REPORT_COMMIT: (见 docs 仓提交记录)
- BRANCH: docs 本地仓当前分支
- PRODUCT_CODE_CHANGED: NO
- PRODUCTION_ACCESS: NO
- PRODUCTION_MUTATION: NO
