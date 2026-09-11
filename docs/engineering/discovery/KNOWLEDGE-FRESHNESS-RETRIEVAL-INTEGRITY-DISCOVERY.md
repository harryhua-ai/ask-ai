# KNOWLEDGE FRESHNESS & RETRIEVAL INTEGRITY — Discovery / Architecture Definition

- 日期:2026-09-11
- 角色:Role A — Product / Architecture Discovery(READ-ONLY,零实现,零生产触碰)
- 审计基线:origin/main = `d0230f9ac16c`(含 #45+#34 集成;#45 的文档级失败契约已入本基线)
- 证据方式:实际代码逐文件审读(models / sync.py / connectors / services / retrieval / pipeline / admin API / widget)+ 5 个线上失败案例(#45/#48/#28/#31/#29)+ 外部机制核对(Onyx/LlamaIndex/Ragie/Kapa 官方文档级检索验证)
- 报告落点:仓库既有 discovery 惯例为 `docs/engineering/discovery/*-DISCOVERY.md`(I002 系列、INTELLIGENT_ANSWER_ENGINE 等 8 篇均在此),本报告沿用该惯例,未新建 `docs/product/initiatives/`。

---

## 0. FAILURE-CASE EVIDENCE(本提案的问题锚)

五组线上失败,**不共享单一根因**;逐一映射到机制缺口:

| 案例 | 现象(实证) | 机制缺口(代码级根因) |
|---|---|---|
| #45(已修,入库) | run 2647 两文档灌入失败,错误文案只说"可能 embed/写库故障" | 字符契约错位(chunker 600 token vs embedder 1024 **char** → 413 永久失败)+ 失败无文档级结构化诊断 → #45 交付 DocFailure 结构化 + 413/422 永久 vs 传输可重试分类 + 零成功写不覆盖账本。**残余缺口:文档级重试的运维入口仍是 CLI/整源重跑,无 per-doc 端点** |
| #48(OPEN) | 答案引用 5 条 `github/Dockerfile、github/build` 等,链接失效 | 三因叠加:① 仓库重构 `hailo_ipc_sdk→neoruntime_ipc_sdk` 改名滑出删除窗口 → 旧路径 corpus 变 ghost(d11 生产实证);② 引用 URL = 灌入时存进 Weaviate 的 `url` 属性,**全链路无存活校验**(canonical_url.py:20-23 自认部署滞后软 404 out of scope);③ widget 徽章 `<a href>` 未过 `isAllowedUrl` 主机白名单(sanitize.ts:103-105),`url=""` 渲染空链接 |
| #28(OPEN) | NE101 各配置价格答不出,只给 $69–$112 区间 | woo 连接器 identity=`{source}/{product_id}`,**variations 维度零摄取**(woocommerce.py 无任何 variation 处理);STORE_OFFICIAL 预留(R1/R2/R3)只保证 store 页存活,不解决变体结构化缺失;价格无 source_version/时点 → "价格基准日"只是 prompt 级要求 |
| #31(OPEN) | 方案推荐漏官方 Solutions/Wiki 证据 | SOLUTION_GUIDE 结构谓词假阴性已修(信号词表)+ 计划含 required SOLUTION_GUIDE;**但 solution/case 桶无 reservation 类保障**,存活仍靠 top-k 竞争;wiki 页需经 web_crawl 摄取,受薄内容过滤(`MIN_CONTENT_CHARS=200`)与全量爬取节奏制约 |
| #29(OPEN) | NE101 功耗续航答不出,Battery Calculator 页面证据缺失 | 页面为交互式 JS 渲染 + "Lab Test Data" 表格 → 爬取提取薄/空 → 覆盖缺口。**freshness 策略对"从未成功提取"的内容无感知**(源存在 ≠ 内容可检索) |
| 历史当现势(TELEC 等) | 内部案例历史数字被当现势事实引用(验收 corpus A01 实证) | 检索/排序**无任何时间性/权威性感知**:`evidence_authority_class/temporality` 属性存在但运行期恒 `unknown` 且被显式冻结不参与决策(evidence_meta.py:5-7);仅生成期 prompt 两处纪律(rag.py:1156-1160;response_strategy.py:168-178) |

---

## 1. CURRENT-STATE ARCHITECTURE(实测管道图)

```
Source(GitHub/Website/Wiki/WooCommerce/Filesystem)
  → data_sources 注册表(enabled/sync_interval/config/lifecycle_state)
  → connector.fetch_changes(since) / fetch_all() / fetch_deleted(since)   ← 时间窗变更检测
  → RawDocument{source_id, title, content, url, metadata, content_hash,
                channel_visibility, branch}
  → ingest:chunk(600tok/50overlap 语义 + tree-sitter 代码块)
  → embed(bge-m3@1024,经内部 /api/internal/embeddings,GPU→CPU 粘性回退)
  → Weaviate 单集合 "Document":deterministic UUID5(source_id#chunk_index)
  → Postgres documents 账本 upsert(source_id PK, content_hash, chunk_count)
  → 同步:sync_log(业务结果)/ sync_requests(执行交接,MAX 4 次退避重试)
          / sync_runs(运行遥测+consistency 事实);verify_source_vectors 只读对账
  → 检索:hybrid(alpha .5)+symbol BM25+intent boost bucket → RRF
          → bge-reranker-v2-m3 ×chunk_type 权重 → 阈值0.3 → top_k10
          → LLM pruner → F-1' 证据预留(R1/R2/R3)→ 排序 → 引用上下文(5源可见帽)
  → 生成 → validate_citations + claim_validation(INC-6 四态)
  → API → Widget(徽章链接)/ Admin
```

逐段现状表(Source of Truth / 身份 / 变更检测 / 增删改 / 失败 / 重试 / 陈旧 / 重复 / 可观测 / 删除内容可检索? / 移动保身份? / 引用溯源?):

| 阶段 | SoT | 关键事实(证据) |
|---|---|---|
| 源清单 | Postgres `data_sources` | id/type/product/enabled/config/sync_interval;lifecycle_state 仅删除族(NULL=active/delete_requested/deleting/delete_failed)(models.py:198-213) |
| discovery/inventory | 各连接器自行枚举 | 无统一 slim 清单;web_crawl 有成员快照 `data/crawl-state/{id}.json`(全量轮 diff 用);git 用本地 clone;**woo 单页 per_page=100,超 100 商品静默截断**(woocommerce.py:129-132) |
| fetch | 外部源=成员权威 | github:远端 HEAD SHA 短路 + `git log --since AMR`;web:全量轮 + sitemap lastmod(无 lastmod 的 URL 永不进增量);woo:`modified_after`;fs:`mtime` |
| normalize | connector 契约 RawDocument | ExclusionPolicy + TechnicalSafety 预读(知识角色分类/historical_artifact_verdict 已存在,safety.py:405-544) |
| document identity | Postgres documents.source_id PK | `{source}/{branch}/{rel}` 或 `{source}/{url_path}` 或 `{source}/{product_id}`;**身份冻结契约 #13**(models.py:44-55);content_hash 降级为指纹非身份 |
| persistence | PG=对账权威("哪些文档已灌入/何时/多少 chunk") | documents 单行 upsert;**无 deleted_at/last_seen_at/source_version/etag/状态列**(models.py:53-67) |
| chunking/identity | 位置型 (source_id, chunk_index) | UUID5 确定性;语义块 doc_section/chunk_type;symbol 字段 |
| embedding | bge-m3 | 同 UUID 覆盖写(insert 失败逐对象 `data.replace()`),重复不可能来自重嵌入(ingest.py:321-355) |
| index | Weaviate=服务投影 | 单集合无 tenant;**属性无任何时间戳**;5 个 evidence_* 元数据字段存在但运行期冻结 |
| sync/reconciliation | sync_log=业务结果权威 | 失败不推增量窗口(防跳缺口);空 fetch→verify→定向 refill→孤儿对账(仅完整枚举才删);#45 后文档级 DocFailure 入账 |
| retrieval | — | 预检索过滤仅 3 类:product equal / 分类学标签 any_of / channel_visibility contains_any;**无 lifecycle/freshness/authority 门** |
| rerank/evidence | EvidencePlan 四角色 | 谓词结构匹配;required 槽前置重排(不增删);比较模式分层配额;预留 R1/R2/R3(帽 4/30/5);5 源可见帽 |
| citation | Weaviate url 属性 → wiki 规范化改写 | `provenance_url` 保留原始;first-party url="";**无存活校验**;widget 徽章 href 未过白名单 |
| Admin 可观测 | /api/admin/* | sources CRUD/同步触发/sync-status·runs·logs/五维 sync-health(connectivity/sync/coverage/freshness 2×interval/consistency)/analytics;**缺:per-doc 检查/重试端点、vector-consistency 与 corpus-repair HTTP 端点(CLI only)、引用健康** |

三问直答:
- **删除源内容可残留可检索?** 会。fs/woo `fetch_deleted` 恒 `[]`;git 删除仅窗口内可见(改名滑窗=永久 ghost,d11 实证);禁用/删源配置不动向量;consistency 只读不删;对账删除需"完整枚举确认"否则 KEEP+REPORT(此设计是对的,但覆盖面不全)。
- **移动/改名保身份?** 否。git R 状态被处理为旧路径 delete+新路径 add(github.py:300-330,352),无别名链;URL 变更同理。
- **引用 URL 溯源端到端存活?** 否。url 属性灌入时定格;wiki 有规范化改写(github blob→wiki.camthink.ai);无校验、无失效状态、widget 端徽章绕过白名单。

---

## 2. CURRENT DATA MODEL / IDENTITY AUDIT

任务七问(逐条,证据见 §1 表与 file:line):

1. **文档身份跨内容变更稳定?** 是。source_id 路径串 PK 原地 upsert;UUID5 命名空间不变。仅路径变更产生新身份且旧身份成 ghost。
2. **chunk 身份冒充文档身份?** Weaviate 内是:文档=同 source_id 的 chunk 集合,无文档级对象;所有文档级向量操作靠"枚举 chunk UUID"寻址。PG 侧是文档粒度(chunk_count)。这是刻意设计(确定性 UUID 家族的根基),不是缺陷本身,但要求"文档级状态"必须活在 PG,Weaviate 永远只是投影。
3. **同文档两版本可共存检索?** 同路径:正常否(确定性覆盖+成功后裁剪超量 chunk);部分失败时短暂可(裁剪延后,靠下轮/一致性修复);**跨路径同内容:合法共存且双双可检索**(D2 duplicate_doc_count 只报不并)。
4. **源消失向量残留?** 会(§1 三问第一条;KNOWLEDGE-STALE-LEDGER 生产修复实证 26 行死账)。
5. **重复如何表示?** 三种:跨路径同内容(独立行+独立 chunk 集,report-only);同路径超量旧 chunk(stale_chunk_count,成功后裁剪);账本零行但向量在(orphan,verify 报告)。**无摄入期内容级去重**(fetch 到即重嵌)。
6. **#48 的 canonical GitHub repo/ref/path 身份可重建?** 部分可:source_id 含 branch+rel,url 属性含 blob 链接,可解析出 repo/ref/path 三元组;**缺的是"移动"语义**(改名→别名→URL 重写)与失效探测,不是身份字段本身。
7. **哪个 store 是权威?** 三层:外部源=成员/事实权威;PG documents=摄入对账权威;Weaviate=检索投影。业务结果权威=sync_log;执行交接权威=sync_requests。**分歧检测只读(refill/repair 闭环),删除侧收敛仅在 #18 purge 有验证段。**

已存在 vs 缺失的生命周期字段:
- 已有:`documents{source_id,content_hash,chunk_count,branch,url,created_at,updated_at}`、`data_sources{enabled,sync_interval,lifecycle_state,lifecycle_since,lifecycle_error}`、`sync_log{status,items_new/updated/deleted/unchanged,error_detail,…}`、`sync_requests{attempt_count,failure_kind,next_retry_at,…}`、`sync_runs{stage,counters,consistency,execution_device,…}`、Weaviate per-chunk `content_hash`+5 evidence_* 字段。
- 缺失:per-doc `last_seen_at/source_version/source_updated_at/etag/commit_sha`、`deleted_at`/tombstone(刻意:删=整行删,无史)、per-doc 状态枚举(#45 的 DocFailure 只在 sync 日志,不在文档状态)、版本历史/生成表、Weaviate 时间戳属性。

---

## 3. EXTERNAL BENCHMARK FINDINGS(机制级,不换框架)

检索验证过的事实 + 机制级结论。每项给 REUSE DIRECTLY / ADAPT / NOT NEEDED / DEFER。

| 系统 | 机制(已核验) | 对 ASK-AI 的结论 |
|---|---|---|
| **Kapa** | 全连接器自动同步、持续跟踪源更新;源型引用(citation-backed);源健康/破损由平台托管 | **ADAPT**:per-source 节奏+新鲜度 SLA 的产品语义(我们已有 sync_interval,升级为 SLA 策略);"答案永不过期"的承诺靠策略+对账,不是靠全局 TTL |
| **Unstructured** | record_id/record_version 确定性元素身份、增量替换 | **ADAPT**:per-doc source-native version 字段(git=commit_sha+blob hash;web=lastmod/etag;woo=date_modified;fs=mtime+size)。我们的确定性 UUID 已解决身份稳定,缺的是**版本字段** |
| **Onyx** | Load(全量)/Poll(增量)/**Slim(轻量枚举全部 doc id,用于删除对账)** 三连接器范式;索引器用 slim 清单 diff 做删除 | **ADAPT(核心)**:把"完整清单枚举"提升为一等连接器能力(现在只有 web_crawl 有成员快照,woo/germ fs 无);这是安全删除对账的最小充分机制 |
| **Ragie** | 文档生命周期 created/updated/deleted/error 事件 + 签名 webhook | **ADAPT 事件模型**(文档状态机+变更事件入账);webhook 本身 **NOT NEEDED**(内部批处理,无外部订阅方) |
| **LlamaIndex** | `refresh_ref_docs` 按 content-hash 差异化 upsert;`delete_ref_doc` 显式删节点;**官方已知坑:refresh 不删已移除文档的节点,必须显式删** | **ADAPT**:摄入期 content-hash 短路(UNCHANGED 不重嵌)+ 显式删除不可省——与我们"成功后裁剪+refill"互证;其坑就是我们 #48 ghost 的同型风险 |
| **Microsoft GraphRAG** | entities/relationships/claims + local/global/DRIFT 多模检索 | **DEFER**(见 §8) |
| **LightRAG** | 增量图更新+选择性删除+双级检索 | **DEFER**(同上) |
| **Haystack** | 检索前置 MetadataFilter(检索器级 where 过滤) | **REUSE DIRECTLY**:Weaviate where-filter 已在用;补 lifecycle/generation/authority 字段即得,不动融合机制 |

不采用任何框架整体替换;Onyx Slim 与 Ragie 状态机是**机制借用**,落地在既有 connector/service 体系内。

---

## 4. PRODUCT SEMANTICS(目标语义提案)

**总原则(从本仓 DNA 归纳,三条全链纪律):**
- P1 删除必须源确认:无完整清单证据不得删(fail-closed,现有 sync.py 纪律升为全源契约);
- P2 服务索引永远有上一代好版本:处理中不覆盖、失败不回退、验证不过不激活(现状 `--reindex` 先删后灌违反此条);
- P3 账本即真相:生命周期/新鲜度/引用有效性只读 Postgres,永远不读向量索引反推(现状基本如此,固化为不变量)。

### A. DOCUMENT LIFECYCLE(文档生命周期)

状态机(6 态,命名有据,非照抄任务草案):

```
DISCOVERED ──ingest ok──► ACTIVE ──content change──► ACTIVE(新版本,旧版本→SUPERSEDED)
    │                        │
    │ ingest fail            ├─完整清单缺席×N 轮──► MISSING_CANDIDATE ──探针确认源缺失──► DELETED
    ▼                        │                            └─重新出现──► ACTIVE
  FAILED(→重试→ACTIVE)      ├─源不可达/传输失败──► UNREACHABLE(保上一代,恢复后回 ACTIVE)
                              └─手动禁用源(可选)──► RETIRED(保留向量,退出检索资格)
DELETED:逻辑墓碑(保留元数据+历史 N 天)──GC──►物理清除(行删+向量删)
```

- 转换触发:ingest 结果(成功/失败/部分失败按 DocFailure)、对账 diff(完整清单缺席轮数)、源探针(可达性)、管理员动作。
- 检索资格:仅 **ACTIVE**(及 UNREACHABLE 宽限期内降级可检索,见 C/Freshness)。SUPERSEDED/DELETED/FAILED 不可检索。
- 历史保留:document_versions 保留版本链(§5);DELETED 墓碑保留 `identity+版本史+墓碑时间`,默认保留 30 天后 GC(决策点 D-3)。
- 移动/改名:旧 identity 记 `superseded_by=新 identity`(别名链,github R 状态与 URL 归一化触发),引用经别名解析到新 canonical URL——#48 的直接解药。
- 回滚/恢复:索引生成模型(B)保证上一代完好;生命周期回滚=墓碑撤销+重激活版本行。

### B. INDEX LIFECYCLE(索引生命周期)

需要:每文档索引生成状态 `PENDING / PROCESSING / READY / FAILED / RETIRED` + **生成原子激活**。

- 写入新版本 → 新 chunk 带 `generation_id`(UUID5 命名空间扩展为 `source_id#generation#chunk_index`,或等价实现)→ `READY` 前旧代持续服务;
- 激活 = 单事务翻转 PG `documents.active_generation` + 检索侧只查 active 代(或仅 active 代物理在索引,二选一,决策点 D-2);
- 验证(块数/哈希/抽样)不过 → 新代标 FAILED,旧代不动;激活后旧代转 RETIRED → GC。
- 直接后果:`--reindex` 先删后灌被废除,替换为"新代重建+原子激活"(全量重建=每源一个新代)。

### C. FRESHNESS(新鲜度,源策略驱动,无全局 TTL)

状态:`FRESH / STALE / OVERDUE / UNKNOWN`(语义明确:SLA=源策略字段)。

- 计算锚:**source_verified_at**(最近一次"完整清单验证成功"时间,不是 document.updated_at——后者是内容变更时间)。
- 策略示例(默认值待 Planner 定,机制上按源类型):
  - WooCommerce/Store:SLA 24h(价格敏感),OVERDUE 时商务类答案必须声明价格时点或拒答现势价格;
  - GitHub:SLA 24h(非 push 驱动,轮询语义);
  - Wiki:SLA 48h;
  - Website:SLA 72h(全量爬取节奏);覆盖失败(OVERDUE+coverage<阈值)→ 源级 DEGRADED 告警;
  - Filesystem/历史档案:**ARCHIVE 语义,freshness=N/A(永不 STALE)**,历史型内容天然免疫新鲜度。
- UNKNOWN:从未成功验证/探针失败——检索侧不因 UNKNOWN 拒答,Admin 侧必须显形。
- OVERDUE 的检索语义是**标记+降权候选**,不是硬删除(硬门仅在价格类现势断言,见 E)。

### D. CITATION VALIDITY(引用有效性)

状态:`VALID / REDIRECTED / MOVED / UNREACHABLE / NO_PUBLIC_URL / INVALID`。

- 产生机制:引用校验器(批量、离线、挂在对账循环,非请求时)逐 canonical URL 探活:2xx=VALID;3xx=REDIRECTED(更新 canonical,保留可点);清单/别名给出新位置=MOVED(改写 URL,保留可点);探针 404/超时=UNREACHABLE;first-party 无公开 URL=NO_PUBLIC_URL(渲染为不可点徽章——现 url="" 行为的正式化);连续 N 次探针 404 且别名无解=INVALID。
- 渲染策略:VALID/REDIRECTED/MOVED 可点;UNREACHABLE 保留文字不可点(答案其余部分不因此作废);INVALID 证据**从最终证据集中排除**(并在 coverage 报告显形);NO_PUBLIC_URL 不可点(现状保持)。
- widget 修复项(小,独立可先行):徽章 href 过 `isAllowedUrl`,不通过渲染为非链接徽章。

### E. AUTHORITY / TEMPORAL TRUTH(权威/时态真相)

四类:`CURRENT / HISTORICAL / SUPERSEDED / INVALID`。

- 赋值=源角色 × 内容类型的策略表(不加 LLM):
  - woocommerce → CURRENT(且价格断言必须带 price-basis/record-date——把现有 prompt 纪律升为结构化字段);
  - github/website/wiki 产品与文档页 → CURRENT;
  - filesystem 案例/内部材料 → **HISTORICAL(默认)**;safety.py 已有 historical_artifact_verdict,直接复用为初始赋值器;
  - 被 SUPERSEDED 版本链接替的旧版本 → SUPERSEDED;
  - 校验失败 → INVALID。
- 检索行为:证据谓词已按角色分桶(evidence_planning 四角色),补一条硬规则:**现势类问题(commercial/现价/现规格)的 truth-bearing 断言只允许引 CURRENT**;历史型问题可引 HISTORICAL(强制日期框定:"截至 case 记录时点")。SUPERSEDED 仅回答"变化/历史"类问题。
- 排序:authority/freshness 仅作 tie-break 与资格门,不引入新排序公式(无证据支持前不预设计分)。

---

## 5. CANONICAL IDENTITY / VERSIONING(目标身份模型)

```
CanonicalDocumentIdentity = (source_id, source_native_key)
  source_native_key 按源类:
    github    : repo / ref / resolved_path   (R 重命名 → alias 链 old→new)
    website   : canonical_url(已有归一化)     (3xx 跟随 → alias)
    wiki      : 规范公开 URL(canonical_url.py 已有映射)
    woocommerce: product_id(variation 属内容结构,不拆身份)
    filesystem: path(ARCHIVE 语义,无移动概念)

DocumentVersion(新表,提议):
  identity_ref, version_seq, content_hash, source_version(git sha/lastmod/date_modified/mtime),
  metadata_hash, generation_id, lifecycle_state, valid_from, valid_to, superseded_by,
  failure(DocFailure 结构), created_at
```

- 同文档新版本:同 identity,version_seq+1,旧版本 SUPERSEDED(链保留);
- 精确重复内容(跨路径):**合法共存,不删源**(冻结原则);检索引用层做 canonical collapse(同一 content_hash 簇引一个代表,authority 高者优先),Admin 报告重复簇;
- 语义重叠 ≠ 删除许可(显式冻结,防误伤 Store vs Wiki 价格互证);
- 元数据变更(标题/URL/分类)不改 content_hash → metadata_hash 单独追踪,触发属性更新而非重嵌。

---

## 6. RECONCILIATION MODEL(对账循环)

```
INVENTORY(每源 slim 完整枚举,新连接器能力)
  → DIFF(ledger × inventory × index 三向)
  → NEW / CHANGED / UNCHANGED / MISSING
  → FETCH(仅 NEW/CHANGED;UNCHANGED 靠 content-hash 短路跳过嵌入)
  → NORMALIZE → VERSION(写入 DocumentVersion,generation 建 PENDING)
  → PROCESS(chunk/embed → PROCESSING)→ VALIDATE(块数/哈希/计数)
  → ACTIVATE(active_generation 原子翻转;旧代 RETIRED)
  → TOMBSTONE(MISSING 确认→DELETED 墓碑;版本接替→SUPERSEDED)
  → GC(保留窗后物理清除墓碑+RETIRED 代)
```

安全答案(任务六问):
- **删除如何安全确认?** 三条件齐备才可删:① 该轮清单为 complete(web_crawl 快照语义推广到全部连接器;git=tree 枚举;woo=**分页全量修复 100 上限截断**;fs=walk);② 连续 N 轮(默认 2)缺席;③ 源可达探针通过(排除"源挂了"假象)。任一不满足 → UNREACHABLE/MISSING_CANDIDATE,保留服务。
- **临时源故障会误删?** 不会:清单不完整/探针失败都判 UNREACHABLE(P1 纪律);现状 sync.py 的 complete-gate 思路全源化。
- **失败索引保上一代?** 是:生成模型(P2);FAILED 新代不影响 ACTIVE 旧代;`--reindex` 语义替换为"新代全量重建+原子激活"。
- **孤儿向量如何检测?** 三向 diff 已有只读实现(verify_source_vectors 聚合+精确集合差);新增:对账循环内**有据执行**(RETIRE 仅在 complete 清单下,复用现有 RETIREMENT MUST BE SOURCE-CONFIRMED 纪律)。
- **inventory == ledger_active == indexed_active 可证明?** 对账产物 = 机读不变量报告(每源:expected_active(inventory∩eligible) vs ledger_active vs indexed_active,含差异清单)——现有 VectorGapReport 升级为三方对账,Admin 直接呈现;该报告同时是 Admin"知识健康"的数学底座。

---

## 7. RETRIEVAL INTEGRITY MODEL(检索完整性)

原则:**资格在进入索引前与检索前双重收敛;检索内只做排序/组合,不做生命周期判断。**

- **主门(物理)**:只有 ACTIVE 代的 chunk 物理存在于索引(生成模型保证)→ DELETED/SUPERSEDED/FAILED 天然不可检索,不加过滤成本;
- **副门(逻辑)**:Weaviate where-filter 追加 `lifecycle`(UNREACHABLE 宽限/RETIRED 保留类)与 `evidence_authority_class`(现势断言门)——Haystack 式前置过滤,不扰动 hybrid 融合;
- **证据角色**:四角色计划保持;把预留(R1/R2/R3)的"槽位保障"思想**推广到 SOLUTION_GUIDE/CASE_EVIDENCE 桶**(#31 残余:存活靠竞争 → 有界预留),不引入裸配额公式;
- **authority/freshness 感知**:tie-break + 现势硬门(§4E);HISTORICAL 证据强制日期框定;
- **重复抑制**:引用层 content_hash 簇 collapse(cite-one),保多样性;
- **多样性/配额**:比较模式分层配额保留;多产品答案的 per-target 配额泛化;
- **现机制兼容性**:全部过滤发生在 Weaviate 查询构造处,不触 alpha/RRF/reranker;
- **claim/graph 位置**:未来 claim 层挂在 Evidence Planner 之后做跨源事实核对(§8),本提案不依赖它。

#28/#31 在此模型下的路径:store 变体身份+结构化变体内容(§5)解决"每个配置多少钱"的证据缺失;store 桶预留已上线,变体补齐后 R2 兄弟页补全即覆盖变体页;solution/case 桶有界预留 + wiki 覆盖策略(C 节)解决 #31 类缺口。

---

## 8. CLAIM / GRAPH LAYER DECISION

**结论:LATER / PHASE 3 之后,证据门控启动;现在不引入。**

理由:五个失败案例全部是**覆盖/资格/新鲜度/身份**缺口,没有一个需要实体关系推理才能修。#28 的变体价格缺口是摄取结构问题(woo variations 零摄取),不是"product↔SDK 关系"问题。GraphRAG/LightRAG 全家桶(实体抽取/社区汇总/图索引)成本(抽取 LLM 成本、图维护、增量删除复杂度)远超当前问题规模 → NOT JUSTIFIED NOW。

例外种子(Phase 3+ 可评估的轻量形态):**claim 表**(subject/predicate/object/basis/sources[],例:NE101-L01GL has_price $X as-of date, sources=[store])——仅当 Phase 2 落地后仍出现"多源事实冲突/变体级断言无法定位"的残余案例时启动;product↔SDK/protocol/compatibility 关系不建图,用结构化元数据标签即可。

---

## 9. SOURCE OF TRUTH ARCHITECTURE(实态校验后)

| 层 | 权威内容 | 不可做 |
|---|---|---|
| 外部源系统 | 事实+成员权威(存在性/内容/删除) | 不可被本系统状态覆盖 |
| **Postgres** | 生命周期真相:documents+DocumentVersion+lifecycle 状态+freshness 簿记(source_verified_at/SLA)+citation canonical URL 真相+全部 sync 账本 | 不可从 Weaviate 反推任何上述字段 |
| **Weaviate** | 服务投影:向量+文本+检索元数据。**可丢弃可重建**(对账+重建管线) | 永不作为生命周期/删除/计数/引用有效性的真相 |

**关键开放点(D-1)**:当前 PG **不存文档内容**(documents 只有元数据),Weaviate 的 text 属性是唯一内容驻留 → Weaviate 并非"纯可重建投影"(重建必须重新 fetch 外部源)。建议(Phase 1 评审决断):文档提取内容(或压缩归档)入 PG(content-addressed),使"PG+源=完全可重建"成立;代价是存储与写入放大,收益是投影真正可丢弃、审计可回放。

---

## 10. ADMIN OPERATIONS REQUIREMENTS(能力清单,不做 UI)

**OBSERVE(必须可见)**
- 知识健康总览:每源 freshness 状态 vs SLA、expected_active vs ledger vs indexed 三方计数、最近对账时间与结论、整体 HEALTHY/DEGRADED/STALE;
- 变更流水:最近 N 次对账的 new/updated/unchanged/deleted/failed(已有 sync_log,补 per-doc 维度);
- 失败灌入:#45 DocFailure 列表(source/stage/分类/可重试)——补 **per-doc 端点**;
- 陈旧文档清单(OVERDUE/UNKNOWN 源下属文档);
- 孤儿/多余索引条目(三向对账差异);
- 重复/冲突知识簇(content_hash 簇 + 跨 authority 冲突对);
- 引用健康:INVALID/UNREACHABLE 引用计数与文档清单(#48 运维闭环);
- 每文档生命周期/版本检查器(identity、version 链、generation、lifecycle 状态、来源版本);
- 检索/证据诊断:给定 query 的证据计划/命中/被排除原因(coverage 报告已有底子,补"为什么没检回"侧)。

**CONFIGURE(必须可配)**
- 每源同步频率(已有)+ 新鲜度 SLA 策略(新);
- 对账策略(宽限轮数 N、探针开关);
- 重试策略(执行器已有 4 次退避,显形可配);
- 保留/GC 窗口(墓碑/RETIRED 代);
- 源启停(已有)+ 源角色覆盖(如把某源标为 HISTORICAL/ARCHIVE);
- 引用校验行为(探活开关、失效策略:标记 vs 排除)。

**ACT(必须可操作)**
- 重试失败文档(per-doc,新);
- 立即对账某源(已有 sync 触发,补"仅验证不重嵌"模式);
- 检查文档/版本(新端点);
- 裁决身份异常(别名确认:改名/改链的 old→new 映射审批);
- 触发引用安全复验(批量探活指定源/文档);
- 标记/解除 SUPERSEDED(人工裁决通道)。

**明确不暴露给 Admin**(无运维语义的底层调参,留在配置/代码):chunk 大小/重叠、embedding 模型参数、rerank 阈值与 chunk_type 权重、hybrid alpha、RRF k、pruner 阈值、boost bucket 构成。这些是质量调参,归基准评测(benchmark_v1)管辖,不给运维面。

---

## 11. TARGET ARCHITECTURE(目标组件与五条路径)

新增/升级组件(全部落在既有分层内):

1. **Source Inventory Registry**(连接器 slim 枚举能力,全源统一)
2. **Document Ledger + DocumentVersion**(PG;身份/版本/墓碑/别名)
3. **Policy Engine**(freshness SLA / citation 策略 / authority 角色表——配置驱动)
4. **Index Generation Manager**(generation 生命周期+原子激活+RETIRED GC)
5. **Reconciler**(三向 diff 循环+不变量报告+有据删除执行)
6. **Eligibility Gate**(检索前置资格过滤,物理主门+逻辑副门)
7. **Evidence Planner / Reservation**(既有,桶保障推广)
8. **Citation Validator**(批量探活+canonical 维护+状态回写 PG)
9. **Admin Ops API**(§10 能力的端点集)

```
写路径:  源 → INVENTORY → DIFF → FETCH → NORMALIZE → VERSION(PENDING)
         → PROCESS(PROCESSING) → VALIDATE → ACTIVATE(READY) → 旧代 RETIRED → GC
对账路径: Reconciler 周期:INVENTORY → 三向 DIFF → 不变量报告 → 有据 TOMBSTONE/REPAIR
读路径:  query → Gate(lifecycle/gen/visibility/authority 门) → hybrid+symbol+boost
         → RRF → rerank → Plan/Reservation → Citation(canonical+状态) → 答案
失败路径: 传输失败→UNREACHABLE(保旧代);部分失败→DocFailure 账本(per-doc 重试入口);
         验证失败→新代 FAILED(旧代持续服务);清单不完整→本轮无删除
删除/接替: 完整清单×N 轮缺席+探针 → DELETED 墓碑 → GC;
         版本接替 → SUPERSEDED(链) ;移动 → alias 链(URL 重写)
```

---

## 12. GAP ANALYSIS(EXISTS / PARTIAL / MISSING / CONFLICTING)

| 目标能力 | 现状 | 缺口/爆炸半径/依赖 |
|---|---|---|
| 文档身份稳定 | **EXISTS**(#13 冻结契约,确定性 UUID) | 缺"移动"语义;加 alias 链,半径:connectors+PG 小迁移 |
| 版本/变更检测 | **PARTIAL**(时间窗+重嵌一切) | content-hash 短路+source_version 字段;半径:ingest+connectors;依赖 PG 迁移 |
| 文档级失败诊断 | **EXISTS**(#45 已入 main) | 缺 per-doc 运维端点(小);依赖 Admin Ops API |
| 生成原子激活 | **CONFLICTING**(`--reindex` 先删后灌,服务中断窗口) | 生成模型重写该路径;半径:ingest+sync+weaviate UUID 方案;**Phase 1 最大工程项** |
| 删除对账 | **PARTIAL**(web 快照+complete-gate;woo/fs 无;窗口滑失 ghost) | Onyx-Slim 式全源清单+宽限+探针;含 woo 分页修复(数据正确性 bug);半径:connectors+sync |
| 禁用源退出检索 | **MISSING**(禁用仍可检索) | RETIRED 语义+资格门;半径小 |
| 新鲜度 | **PARTIAL**(sync-health 只报 2×interval,不进检索/策略) | Policy Engine+source_verified_at;半径:sync+admin |
| 引用有效性 | **MISSING**(零探活;widget 徽章绕白名单) | Citation Validator+#48 别名重写+widget 小修;widget 修复可独立先行 |
| 权威/时态 | **CONFLICTING**(evidence_* 字段存在但冻结 unknown;prompt 纪律代偿) | 策略表激活字段+谓词/门;半径:evidence_meta+planning+selection;不加排序公式 |
| Store 变体身份 | **MISSING**(woo variations 零摄取) | #28 核心;半径:woo connector+内容结构 |
| 资格门(检索) | **MISSING**(预过滤仅 3 类) | 依赖生成模型(物理主门)+字段(逻辑副门) |
| 桶保障(solution/case) | **PARTIAL**(计划含槽,无预留) | R 机制推广;半径:evidence_reservation |
| 三方对账证明 | **PARTIAL**(两向只读报告) | 升级三向+有据执行+Admin 呈现;半径:vector_consistency+sync |
| Admin 知识运维 | **PARTIAL**(源/同步/健康/分析有;per-doc/repair/citation 端点缺) | §10 清单;依赖上述数据底座 |
| Claim/图 | **NOT STARTED** | DEFER(§8),无近期依赖 |

---

## 13. PHASED DELIVERY PLAN(默认假设评估后:维持五相,微调两项)

**Phase 1 — Lifecycle Foundation(身份/版本/变更/删除/接替 + 生成原子化)**
PG:DocumentVersion/lifecycle 字段/别名表;ingest:content-hash 短路+generation 写入+验证后激活;废除 `--reindex` 先删后灌;DELETED 墓碑语义。**验收锚:全量重建零服务中断;同文档两版本不可共存;失败不回退。**
> 微调理由:生成原子化原本隐含在"重建"话题里,但它是 P2 纪律的硬前提且改动面最大,必须最先行;citation 别名数据(§4D MOVED)依赖别名表,同相铺设字段、Phase 2 启用消费。

**Phase 2 — Freshness + Reconciliation + Citation Validity**
全源 slim 清单(含 woo 分页修复);三向对账+宽限/探针;Policy Engine(SLA/角色表)+source_verified_at;Citation Validator 批量探活+canonical 回写+**#48 ghost 修复(存量 corpus 清理走 corpus_repair 有据通道)**;widget 徽章白名单小修(可独立 hotfix 先行)。

**Phase 3 — Retrieval Integrity**
资格门(物理主门已在 Phase 1);authority/temporal 激活(现势硬门+HISTORICAL 框定);solution/case 桶有界预留;content_hash 引用 collapse;**Store 变体摄取与结构化变体内容(#28 收口)**;#29 类覆盖策略(JD 渲染页提取策略归 Phase 2 的连接器策略,残余在 3 评测)。
> 微调理由:#28 变体摄取跨连接器+内容结构,放 Phase 3 与资格门同期验收(commercial 答案端到端),避免 Phase 2 过重。

**Phase 4 — Claim/Graph(证据门控)** 仅当 Phase 2/3 后仍有多源事实冲突/变体断言缺口 → 轻量 claim 表;不引 GraphRAG。

**Phase 5 — Admin Knowledge Operations UX + 运营 rollout**
§10 端点集+Admin SPA 面板(该任务独立做 UX/原型);GC 默认值运营化;基准回归(benchmark_v1 冻结语料+新增 freshness/integrity 用例)。

每相入工程施工前须过 Planner 契约冻结(本提案不拆工程契约)。

---

## 14. PRODUCT DECISIONS(2026-09-11 Product Review 裁决,已回填为 DECIDED)

> 来源:Product Review 2026-09-11 接受本 Discovery(仓库内无独立评审记录;依后续任务指令回填推荐值为裁决,D-6 为评审修正、A-1 为评审指示)。

- **D-1 内容入库 = DECIDED:是。** 文档提取内容入 PG(content-addressed),"PG+外部源 = 完全可重建",Weaviate 成为纯可丢弃投影。
- **D-2 生成激活机制 = DECIDED:双代共存 + `active_generation` 属性过滤。** 激活 = 单事务翻转指针;RETIRED 旧代到期 GC。
- **D-3 GC 保留窗 = DECIDED:默认 30 天**(墓碑/被接替旧版本/RETIRED 代,与 sync_runs 保留一致;策略可配)。
- **D-4 OVERDUE 硬门边界 = DECIDED:仅价格与明确"现势"类断言**(现价/现货规格)。其余 OVERDUE 降级为标记+候选降权,不硬拒答。
- **D-5 别名裁决模式 = DECIDED:自动接链 + Admin 可见可撤销**,不阻塞摄取。
- **D-6 filesystem 时态 = DECIDED(修正):filesystem 不自动等于 HISTORICAL;temporal role 由 source policy 决定。** safety `historical_artifact_verdict` 降级为策略建议值,不作为默认赋值器;每源在 Policy Engine 显式配置 temporal role。
- **D-7 引用探活基础设施 = DECIDED:独立低频周期作业**,不与灌入执行器争 GPU/CPU。

**A-1(评审指示,取代 §4A 单一状态枚举):lifecycle / reachability / processing(index generation)/ freshness 建模为四条正交状态轴**,不设计成组合枚举;混合态(如 ACTIVE×UNREACHABLE×FRESH、SUPERSEDED×READY 旧代保留)为合法且有信息量的状态。**正交状态模型的权威定义落在 `docs/product/initiatives/ADMIN-KNOWLEDGE-OPS-UX-DEFINITION.md` §2**(Admin 语义与呈现词汇以其为准);§4A 的 6 态视图降级为 lifecycle 轴的参考叙述。

运营产品化(Admin Knowledge Operations)的完整定义见 `docs/product/initiatives/ADMIN-KNOWLEDGE-OPS-UX-DEFINITION.md`。

## 15. RECOMMENDED NEXT GATE

**Product/Planner 评审本提案 → 裁决 D-1..D-7 → 冻结 Phase 1 目标语义 → 另行任务拆工程契约(INGESTION-LIFECYCLE-P1)。**
前置小项可立即授权(独立于本提案审批):widget 徽章 href 白名单修复(缺陷级,一行策略接入)、woo 分页截断修复(数据正确性)。

---

### 附:证据文件索引(主要)
backend/db/models.py:44-317;scripts/sync.py:425-1269;backend/pipeline/ingest.py:48-829;backend/pipeline/{chunk,chunk_code,evidence_planning,evidence_selection,evidence_reservation,citation,canonical_url,evidence_meta(../),response_strategy,claim_validation,rag}.py;backend/retrieval/{search,rrf,rerank}.py;backend/connectors/{github,web_crawl,woocommerce,filesystem,base}.py;backend/services/{source_lifecycle,source_deletion,vector_consistency,corpus_repair,source_visibility,sync_runs,sync_requests}.py;backend/api/admin/*;widget/src/utils/{sanitize,urlPolicy}.ts;docs/engineering/tasks/{d11-sync-consistency-prod-acceptance-execution,KNOWLEDGE-STALE-LEDGER-PROD-REPAIR-execution,BUG-FIX-SPRINT-REVIEW-MANIFEST}.md;issues #45/#48/#28/#31/#29。

外部机制核验:Onyx connectors README(load/poll/slim);LlamaIndex Document Management(refresh_ref_docs/delete_ref_doc 及"refresh 不删节点"已知坑);Ragie changelog(签名 webhook 文档生命周期事件);Kapa docs/blog(全源自动同步/持续跟踪)。

**KNOWLEDGE FRESHNESS & RETRIEVAL INTEGRITY DISCOVERY = READY FOR PRODUCT REVIEW**
