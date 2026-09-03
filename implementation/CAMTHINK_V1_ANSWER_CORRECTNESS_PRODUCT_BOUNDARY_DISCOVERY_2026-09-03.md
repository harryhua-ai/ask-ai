# CamThink V1 Answer Correctness / Product Boundary — Discovery 报告

- **日期**: 2026-09-03
- **Issue**: harryhua-ai/ask-ai #5(prevent cross-product contamination in product-specific answers)
- **执行模式**: SINGLE EXECUTOR — DISCOVERY ONLY
- **CODE_MUTATION**: NONE
- **PRODUCTION_MUTATIONS**: NONE(生产访问仅为只读 SELECT/GraphQL Aggregate,零写入)
- **基线**: ask-ai 主仓 `main = 1d6f6b5`(与生产 sha-1d6f6b5 一致);docs 仓本报告为唯一新增 commit

---

## 1. Executive Summary

**结论先行:ASK-AI 当前不存在任何一条产品边界约束。** 系统在数据层三级持久化了 `product` 标签(data_sources 表 → documents 账本 → Weaviate chunk property),检索 API 也预留了 `product_filter` 精确过滤参数——但这条链在问答路径上是**断头路**:

1. **`/api/ask` 是 `stream_answer` 的唯一生产调用方,从不传 `product_filter`**(routes.py:271-284);请求契约 `AskRequest` 根本没有 product 字段(schemas.py:82-153)。生产检索恒为全域跨产品。
2. **chunk 级 `product` 是"源级出处标签",不是"每文档产品身份"**。生产实证:NE503 的权威 wiki 文档(目录 `docs/6-neoeyes-ne503-series/`)全部打 `product="wiki"`,与 NE301/NE302/NG4500/NeoMind 的 wiki 内容(共 3,891 chunks)结构上不可区分;`ne503` 标签在全库仅 93 个 chunk(全部来自商城 category 映射)。
3. **生成提示词零产品语义**:无 target product 声明、无逐证据产品归属、无 sibling 冒充禁令(config/system_prompt.yaml);引用校验只做「编号有效 + 数值支持」(citation.py),对「NE301 事实冒充 NE503 结论」结构性失明。

因此「NE503 怎么升级固件」在 NE503 证据不足时,检索/重排/生成/引用四层**没有任何机制**阻止 NE301 证据被当作 NE503 事实输出。这是 Issue #5 的直接根因。

**同时,系统的既有架构为修复提供了完整挂载点**:`product` 已是 Weaviate 结构化属性(可过滤、已过单测);语料本身产品分区清晰(wiki 目录、woo category、独立产品 repo);阶段⑯已建立 message_key 本地化拒答通道可承载「证据不足」语义。**修复不需要新 collection、不需要改 channel_visibility、不需要动站点契约**——需要的是:①每文档产品身份推导(ingest 侧,需重灌 wiki/website 两源);②taxonomy 配置驱动的产品注册表(替代 if/else);③检索硬约束 + 重排偏置 + 生成归属契约 + 引用产品校验四级闭环;④cross-product eval 矩阵。

**Final Verdict: NEEDS_PRODUCT_DECISION**(§23)。根因与实现边界已冻结;产品 taxonomy 内容(§18 PD-1)、澄清/升级 UX(PD-2/PD-4)须产品负责人拍板后方可进入实现。

---

## 2. Baseline

| 项 | 值 |
|---|---|
| 代码基线 | ask-ai `main = 1d6f6b5`(三候选集成后的 authoritative main,生产运行 sha-1d6f6b5) |
| 生产运行时 | tesla-t4:backend / sync-cron / sync-executor 三容器 = sha-1d6f6b5(本日部署 PASS) |
| 生产语料 | Weaviate `Document` collection,**206,689 chunks**(只读 Aggregate 实证) |
| 生产数据源 | 15 个启用源(只读 SELECT 实证,§5) |
| 发现方式 | 全代码链路通读 + 生产只读取证(SSH SELECT + 容器内 GraphQL Aggregate)+ 既有测试/验收报告比对 |
| 已知相关历史 | 09-01 验收基线已记录症状「E06-t2 检索源跨产品误中(内容仍对)」;P1 引用完整性(CIT-01/02)与 P0 信任边界(channel_visibility)已交付但均与产品边界正交 |

边界遵守:零代码修改、零配置修改、零 reindex、零生产写入。生产只读查询共 3 次(data_sources SELECT、Weaviate product Aggregate、wiki chunk 抽样 3 条)。

---

## 3. Current Query Architecture(端到端查询链路)

完整路径(exact files/functions):

```
Widget 前端(widget/src/App.tsx → widget/src/hooks/useSSE.ts:147 POST /api/ask)
  └─ page_context 由 widget/src/utils/pageContext.ts 收集:
       自动收集仅 url/title/language;product/product_id/sku 只能由宿主
       显式提供(window.AskAIConfig.pageContext)——三站接入包未要求宿主提供
Admin 内嵌聊天(channel="admin",同一端点)
  │
  ▼
backend/api/routes.py:ask()(L98-419)
  ├─ resolve_site() 站点门禁(MSW:site_id + Origin 精确匹配;L146-150)
  ├─ mask_pii → lead 上下文 → S2 预算熔断(declined 事件;L170-228)
  ├─ 附件加载/归属校验(L231-249)
  ├─ resolve_answer_language 阶段⑯ 语言前置解析(L165-167)
  └─ rag.stream_answer(...)(L271-284)——【实参无 product_filter,契约无 product 字段】
      │
      ▼
backend/pipeline/rag.py:RAGOrchestrator.stream_answer()(L882-1341;answer() 同构 L636-880)
  ├─ OverrideMatcher.match(backend/services/override_matcher.py)
  │    keyword/regex/semantic 三策略,全部 product-blind;命中即绕过整个 RAG(L924-950)
  ├─ match_social 确定性寒暄短路(backend/pipeline/social.py;L953-968)
  ├─ classify_intent(backend/pipeline/intent.py)
  │    LLM 4 分类:commercial/product/support/off_topic ——【无产品身份抽取】
  ├─ extract_query → rewrite_query(backend/pipeline/query_rewrite.py)
  │    LLM 提取/改写为自包含查询;prompt 要求「保留产品型号」但仅为文本约定,无结构化输出
  ├─ _retrieve_and_fuse(L398-465)三路检索 + RRF 融合:
  │    ① HybridSearcher.search(backend/retrieval/search.py:118)
  │       Weaviate hybrid,alpha=0.5,limit=recall_limit=30;
  │       product_filter=None(生产恒空)→ 无 product 过滤;
  │       channel_visibility.contains_any [channel](唯一硬元数据过滤)
  │    ② search_symbols(符号 BM25,symbol_tokens^3)——product_filter 同样恒 None
  │    ③ search_bucket(intent boost 桶 BM25)
  │       support → source_types=["filesystem"](即 product="knowledge" 内部案例桶)
  │       product → chunk_types 正文四类
  │       commercial → source_types=["woocommerce"]
  │       【support 桶设计上故意跨产品,rag.py:438 注释明示"不透传 product_filter"】
  │    → backend/retrieval/rrf.py:rrf_fuse(k=60,按 source_id+chunk_index 去重)
  │    → SourceVisibilityGuard.allows(backend/services/source_visibility.py)
  │       按源最新 channel_visibility 复核,fail-closed【渠道维度,非产品维度】
  ├─ RerankPipeline.rerank(backend/retrieval/rerank.py:67)
  │    bge-reranker cross-encoder,threshold=0.3,top_k=10,chunk_type 乘性加权
  │    【输入仅 query text + chunk text,product/source_type 不参与打分】
  ├─ 兜底:rerank 滤光但 fused 非空 → 用 fused top-N 继续生成(L1059-1142)
  │    【阈值旁路:低分跨产品候选可借兜底直接进入上下文】
  ├─ apply_page_context_boost ×1.2 软加分(L1144-1150;G009 冻结:仅排序不过滤;
  │    匹配为双向包含式模糊匹配 rag.py:174,`hint in product or product in hint`)
  ├─ _extract_sources(L589-634)公开源白名单(PUBLIC_SOURCE_TYPES)→ canonical URL
  │    → 归一化去重 → 截 5;**每条 source 已携带 product 字段下发给前端**(仅展示)
  ├─ build_citation_context(backend/pipeline/citation.py:95)
  │    可见源 = 权威编号 [1..5];非公开源(filesystem 案例)进「背景资料」禁引用段
  │    【编号条目 = "[N] [标签] 标题 URL + 正文",无产品归属字段】
  ├─ _build_messages(L504-587)system(channel 定制 + intent_styles)→ history → user
  │    user 消息「要求」段:只依据资料/引用编号规则/数值一致/案例非本人事实/…
  │    【无 target product、无 sibling 禁令、无证据不足即拒答的产品语义】
  ├─ llm.stream(task="generation")(backend/llm/registry.py LLMRouter)
  ├─ CitationStreamFilter(citation.py:223)流式确定性校验
  │    剔除悬空/越界/[0] 标记 + 窗口数值支持校验;EmptyGenerationError 兜底(L1233-1240)
  └─ complete 事件(sources/is_answered/language/intent/trace_payload/lead)
      │
      ▼
routes.py 持久化 Conversation(question/answer/sources/is_answered/site_id/session_id)
  + Trace(stages 全链路计时与 rerank 摘要)
```

**意图与产品的关系(§9 原则验证)**:当前 `classify_intent` 只决定 boost 桶与回答风格(intent_styles),完全不知道产品;`product_filter` 参数在编排器内部贯通但入口恒空。架构上「intent 决定 retrieval strategy,product identity 决定 evidence scope」的正交分层**可以**成立——检索三路签名都已带 `product_filter` 形参,只是没人喂值。真实架构支持该原则,缺的是产品身份的抽取与注入。

---

## 4. Current Product Identity Model(产品身份持久化现状)

### 4.1 已持久化的三级 product 标签

| 层 | 位置 | 写入方 | 语义 |
|---|---|---|---|
| 数据源级 | PG `data_sources.product`(String(50), NOT NULL;db/models.py:199) | Admin 建源时自由填写(无枚举校验) | 该**源**归属的产品(声明值) |
| 文档账本级 | PG `documents.product`(db/models.py:55) | 灌入管道从 `RawDocument.product` 透传(ingest.py:697) | 与源级一致(除 woo) |
| chunk 级 | Weaviate `Document.product`(TEXT property;ingest.py:188, `_build_props` ingest.py:96) | 同上 | **检索期唯一可过滤的产品字段** |

写入链:connector 构造 `RawDocument(product=…)`(base.py:37)→ `_build_props`(ingest.py:79-110)→ Weaviate + PG 账本。

### 4.2 每文档产品推导的现状(仅 WooCommerce 一家)

| connector | product 取值 | 粒度 |
|---|---|---|
| github(local_git/filesystem 同构) | `self._config.product`(github.py:97)——**整个源一个值** | 源级 |
| web_crawl | `config.product or "website"`(web_crawl.py:380)——整站一个值 | 源级 |
| filesystem | `config.product`("knowledge") | 源级 |
| woocommerce | `_category_to_product()` 按 doc 的 category 逐个映射:ne101/ne301/ne503/accessories/aitoolstack(commercial 兜底;woocommerce.py:175-192) | **文档级(唯一)** |

### 4.3 系统在哪里知道"这个 chunk 属于 NE503"?

**答案:几乎没有。** 按源逐一判定:

- `ne301-local` 等独立产品 repo:源级标签 ≈ 产品身份(可信,repo 与产品 1:1)。
- `wiki-documents-local`:**不可信**。wiki 是多产品文档库,生产实证全部 3,891 chunks 打 `product="wiki"`。NE503 权威文档在语料目录 `docs/6-neoeyes-ne503-series/`、NE301 在 `5-neoeyes-ne301-series/`、NE302 在 `8-neoeyes-ne302-series/`(本地 clone `~/ask-ai-corpus/wiki-documents` 实证)——**产品身份在语料目录结构中完全可恢复,但 ingest 时不推导,标签坍缩为 "wiki"**。
- chunk 的 `doc_section` = 文档内标题路径(如 "安装 > 依赖";chunk.py:348-357),**不含文件路径**;文件路径只存在于 `source_id` 字符串(`wiki-documents-local/main/docs/6-neoeyes-ne503-series/...`,生产抽样实证)。即:身份可通过对 source_id 做字符串解析恢复,但它不是结构化可过滤字段——且 P0-A 事故已证明 Weaviate TEXT 属性过滤是分词语义,`equal` 前缀匹配不可靠(生产曾误删 359→163),**禁止**把 source_id 前缀解析当作运行时过滤方案。
- `website-camthink`:366 chunks 全打 "website";官网页面常常一页多产品(NG4500/NE 系列/NeoMind 同页),无逐页产品推导。
- `knowledge-support-cases`:481 chunks 打 "knowledge"——**设计上就是跨产品桶**(内部支持案例混含全部产品)。
- woocommerce:文档级 category 映射可给 ne503/ne301 等,但生产实证 `ne503` 仅 93 chunks。

### 4.4 判定

> **系统当前没有稳定的产品身份模型。** 存在的是"数据源出处标签"。对独立产品 repo 它碰巧等于产品身份;对 wiki/website/knowledge 这三个恰恰承载最多产品问答内容的源,单 chunk 的产品身份**未被持久化、不可结构化检索、不可校验**。若不先补每文档产品身份,任何检索硬过滤/生成归属契约都无从落地。

---

## 5. Source→Product Mapping(生产实证)

只读 `SELECT id, type, product, enabled FROM data_sources`(tesla-t4,2026-09-03):

| source_id | type | product(生产实际值) | enabled |
|---|---|---|---|
| aitoolstack-local | github | **AI-ToolStack** | t |
| knowledge-support-cases | filesystem | **knowledge** | t |
| meta-hailo-os-local | github | **meta-hailo-os** | t |
| lowpower-camera-local | github | **ne101** | t |
| ne301-local | github | **ne301** | t |
| neomind-local | github | **neomind** | t |
| neomind-dashboard-local | github | **neomind-dashboard** | t |
| neomind-devicetypes-local | github | **neomind-devicetype** | t |
| neomind-extensions-local | github | **neomind-extensions** | t |
| ne503-apic-69d3594b | github | **neoruntime** | t |
| neoruntime-apps-1eea74dd | github | **neoruntime-apps** | t |
| neoruntime-sdks-67cbac8f | github | **neoruntime-sdks** | t |
| woocommerce-mall | woocommerce | **online-store** | t |
| website-camthink | web_crawl | **website** | t |
| wiki-documents-local | github | **wiki** | t |

生产 Weaviate chunk 级 product 分布(Aggregate,206,689 chunks):

```
ne301 67413 | neoruntime-apps 60675 | ne101 36841 | neoruntime 20198
neomind 15675 | wiki 3891 | AI-ToolStack 955 | knowledge 481 | website 366
ne503 93 | aitoolstack 57 | accessories 44        TOTAL 206689
```

**关键判定(必须验证的部分,已验证):**

1. **source_id 不足以作为 product boundary**——同一 product 标签下混多产品(wiki 3,891 chunks 含 NE101/NE301/NE302/NE503/NG4500/NeoMind 六条产品线 + 共享区),同一逻辑产品又散在多个标签(NE503 的硬件文档=wiki、OS 层=meta-hailo-os、软件平台=neoruntime、商城分类=ne503)。
2. **生产标签与 repo `config/data_sources.yaml` 漂移**:yaml 中 meta-hailo-os→`ne503`、4 个 neomind 源→统一 `neomind`、woocommerce→`commercial`;生产实际为 `meta-hailo-os`、4 个互不相同的 neomind-* 标签、`online-store`。标签是建源人自由文本,**无 canonical taxonomy、无别名表、无大小写归一(AI-ToolStack 955 vs aitoolstack 57 并存)**。
3. **`ne503` 在生产数据源 product 列中根本不存在**;NE503 自身的固件权威 repo(meta-hailo-os-local)生产 chunk 数为 0(未成功入库;与 09-03 GPU 事故期间 neoruntime-sdks 删建 192 篇全败一致)。当前 NE503 硬件/固件知识实际只存在于 wiki 源(3,891 混合 chunks 的一部分)。
4. product="knowledge" 的内部案例桶(filesystem,channel_visibility=["api"])按设计跨产品。

---

## 6. Retrieval Boundary

| 检查项 | 现状 | 产品边界含义 |
|---|---|---|
| query filters | extract_query/rewrite_query 纯文本 LLM 改写,产品型号只是文本 token,改写可能丢失/泛化(无结构化保护) | 唯一的产品信号可能被改写稀释 |
| metadata filters | **仅 channel_visibility**(渠道白名单)。`product_filter` 三路检索签名均支持且实现正确(`Filter.by_property("product").equal`,search.py:181/232/309,含单测),**但生产入口恒不传** | 产品维度零硬约束 |
| hybrid/vector search | Weaviate hybrid alpha=0.5,全库单 collection | 跨产品语义近邻直接互串(NE301/NE503 同系列文档向量高度相近) |
| candidate pool | recall_limit=30,三路 RRF 融合(k=60) | sibling chunks 天然进入候选池 |
| score threshold | rerank threshold=0.3 | 见 §7 |
| reranker | bge cross-encoder,仅文本对 | 见 §7 |
| fallback | rerank 滤光但 fused 非空 → fused top-N 直接进上下文(rag.py:1059-1142) | **阈值旁路**:低相关跨产品候选可绕过 0.3 阈值 |
| cross-source retrieval | support boost 桶固定检索 product="knowledge" 桶(rag.py:99-103,438);commercial 桶固定 woo | 设计性跨产品(案例/商城),无产品归属输出约束 |
| site boundary | site_id 只做授权与统计,**不做知识范围过滤**;三站点共享同一全局语料 | 站点 ≠ 产品范围 |

**污染可发生阶段**:改写(信号稀释)→ 召回(无过滤)→ 融合(sibling 入池)→ 兜底(旁路阈值)→ boost 桶(设计性跨源)。**每一层都放行 sibling evidence,且无一层记录"该候选属于哪个产品"供下游使用。**

---

## 7. Reranking Boundary

`RerankPipeline.rerank`(rerank.py:67-124)输入 = `(search_query, [r.text])`,打分要素只有 cross-encoder 文本相似度与 chunk_type 权重(heading 1.2/paragraph 1.0/code 1.1/list 0.9/table 1.1)。

- `SearchResult.product/source_type/source_id` 全部不参与打分与排序;
- NE301 与 NE503 的同主题章节(如 "升级固件"、"电池续航"、"PoE 配置")在文本层面高度相似,cross-encoder **无法也不试图**区分;
- page_context 软加分(×1.2)是唯一产品相关信号,但:①仅当宿主显式提供 pageContext.product(三站接入包未要求);②模糊双向包含匹配(rag.py:174,"ne" 这类 hint 会误命中);③只重排不过滤(G009 冻结),sibling 照常入围;
- rerank 滤光后的 fused top-N 兜底(§6)让阈值对 sibling 污染进一步失效。

**判定:rerank 层当前对串台不仅不设防,兜底路径还会放大。**

---

## 8. Generation Boundary

`_build_messages`(rag.py:504-587)+ `config/system_prompt.yaml`:

- **无 target product 声明**:system/user 消息均无「用户在问 NE503」的任何表述;模型对目标产品的唯一感知来自问题文本本身;
- **无证据产品归属**:可引用资料条目格式为 `[N] [GitHub|Wiki|官网] 标题\nURL: …\n正文`(citation.py:142-144),`SearchResult.product` 在此处**被丢弃**,LLM 看不到每条证据属于哪个产品;
- **无 sibling 冒充禁令**:guardrails 覆盖「不编造参数」「案例≠本人事实」「数值须原文一致」,但没有任何「不得把 A 产品资料当作 B 产品事实」「证据不足须明示而非借同系列产品补位」条款;
- **证据不足语义只有全局形态**:「暂未在官方资料中找到相关信息」(阶段⑯本地化冻结文案,user_messages)由**检索为空**触发(rag.py:1062-1133 拒答门)——触发条件是"完全没召回",不是"没有目标产品召回"。sibling 强证据在场时永远不触发;
- 后果:模型面对「NE503 怎么升级固件」+ 上下文里 NE301 固件步骤,唯一阻力是自身语言模型的谨慎,**系统层面零约束**;答案会带 [N] 合法引用(编号校验通过、数值支持通过——NE301 的数字当然支持 NE301 的事实),输出一个看起来完全合规的串台答案。

---

## 9. Citation Boundary

`backend/pipeline/citation.py` 三组件(CIT-01/02):

- `build_citation_context`:编号权威 = 访客可见 sources;非公开源进禁引用背景段;
- `CitationStreamFilter` / `validate_citations`:①标记 ∈ [1..N] 否则剔除;②窗口内显著数字须在所引源文本中存在,否则剔除标记(只删标记不改写正文)。

**只验证「回答引用了某个 chunk」,完全不验证「chunk 属于用户问的产品」。** 现有校验的两个维度(编号存在性、数值支持性)对产品边界双双失效:串台引用的编号合法、数字有据。`sources[]` 虽已把 `product` 字段下发前端(routes 侧原样透传),但校验层从不消费它。

**冻结 product-aware citation requirement(CIT-03 候选)**:

> 每个被保留的 `[N]` 标记,其所属证据的产品范围必须与「本轮目标产品范围」兼容(目标产品 / 显式共享平台 / 用户明确要求的多产品);不兼容的标记必须剔除或强制带归属表述。校验的判定输入 = 编号 → chunk product 标签(需 §18 元数据变更先行);执行方式沿用确定性剔标记语义,不改写正文。

---

## 10. Cross-product Contamination Root Causes(根因清单)

| # | 根因 | 层 | 证据 |
|---|---|---|---|
| RC-1 | **产品身份从不参与检索约束**:`AskRequest` 无 product 字段,`product_filter` 生产恒 None | API/检索 | routes.py:271-284;schemas.py:82-153 |
| RC-2 | **chunk 级 product 是源级出处标签而非每文档产品身份**;wiki/website/knowledge 三大多产品源标签坍缩 | ingest/元数据 | §4.2/§4.3;生产 Aggregate |
| RC-3 | **无 canonical 产品 taxonomy/别名注册表**;标签自由文本、与 yaml 漂移、大小写并存 | 配置/治理 | §5 生产 SELECT |
| RC-4 | **生成契约无产品语义**:无目标产品声明、无逐证据归属、无 sibling 禁令、不足语义只在全空召回触发 | 生成 | §8 |
| RC-5 | **引用校验产品盲**:编号+数值双校验均放行串台 | 引用 | §9 |
| RC-6 | **重排产品盲 + 兜底旁路**:cross-encoder 仅文本;fused top-N 绕过阈值;support 桶设计性跨源 | 重排/检索 | §6/§7 |
| RC-7 | **零 cross-product eval**:无任何「NE503 问题 + NE301 强证据在场 → 不得以 NE301 事实作答」的自动化断言;历史症状(E06-t2)未转成回归用例 | 测试 | tests/ 全查;09-01 基线报告 |

因果链:RC-3(RC-2 的上游)→ RC-2 → RC-1/RC-6(检索放行)→ RC-4(生成合并)→ RC-5(校验放行)→ RC-7(无人发现)。

---

## 11. Frozen Correctness Contract(CamThink V1)

> 原则:**Exact-model evidence first. Insufficient exact-model evidence ≠ permission to fabricate confidence from sibling products.**
> 术语:`Target Scope` = 本轮允许作为「目标产品事实」引用的证据集合;`Attributed Sibling Evidence` = 明确标注归属的 sibling 证据(仅比较/多产品场景)。

| 场景 | 定义 | Allowed evidence | Forbidden evidence | 澄清/拒答 | 引用行为 |
|---|---|---|---|---|---|
| **A. Exact product question**(「NE503 怎么升级固件」) | 问题明确指向单一产品 | Target Scope 内证据(wiki NE503 区推导后、ne503 专属源、显式共享平台) | 一切 sibling 产品证据(wiki NE301/NE302 区、其他产品 repo、其他产品 woo 页) | Target Scope 证据不足 → INSUFFICIENT_EVIDENCE(§14),**禁止**以 sibling 补位 | `[N]` 全部落在 Target Scope;不足时无引用且走拒答文案 |
| **B. Product-family question**(「NeoEye 系列支持哪些告警推送」) | 问题指向产品族 | 族内全部产品证据 + 共享平台 | 族外证据(NeoMind 等,除非问题涉及) | 族证据不足 → INSUFFICIENT | `[N]` 可跨族内产品,答案须逐产品分节归属 |
| **C. Multi-product comparison**(「NE301 vs NE503 续航」) | 用户明确比较 ≥2 产品 | 所涉产品的 Target Scope 并集 + 对比类共享文档 | 所涉产品之外的证据 | 单边证据缺失 → 就该产品明示不足,**不得**用另一产品数据填位 | `[N]` 按产品归属分节;每节引用限定本产品证据 |
| **D. Ambiguous product name**(「这个怎么升级固件」/「NE5xx」) | 无法唯一解析目标产品 | (先澄清前)仅共享平台可引用 | 一切猜测性绑定到某具体产品 | **CLARIFY**(§13):列出候选请用户确认;V1 无澄清 UI 时降级为「请说明具体型号」文本提问 | 澄清轮零引用;不产生答案 |
| **E. No exact-product evidence**(NE503 问题 + NE503 证据零命中、NE301 强证据在场) | 目标产品证据完全缺失 | 无 | **一切 sibling 证据——这是本契约的核心负例** | INSUFFICIENT_EVIDENCE / SUPPORT_ESCALATION(PD-4);**MUST NOT** answer | 零引用;is_answered=false |
| **F. Exact evidence + conflicting sibling evidence**(NE503 步骤在场,NE301 数值更高) | 目标证据充分但 sibling 更"好看" | 仅 Target Scope | sibling 不得参与事实合成、不得作为数值来源、不得"补充"步骤 | 不拒答(证据足) | `[N]` 仅 Target Scope;sibling 数字混入 = 契约违约(引用校验应剔除其标记) |
| **G. Generic fact shared by multiple products**(「用 Type-C 充电」/硬件外设通用文档) | 事实本身跨产品成立 | 显式共享平台文档(hardware-dev-resources、ai-application、平台 repo) | 来源不明、无法判定共享性的 sibling 单品文档 | 共享性无法确证 → 按目标产品证据不足处理 | 引用共享文档;若仅有 sibling 单品文档背书,按 E 处理 |
| **H. Product renamed/versioned**(NE302 是 NE301 的迭代;未来 NE60x) | 名称演进/新版本 | 新版本 Target Scope;旧版证据仅在问题明确问旧版时可用 | 不得把旧版事实当作新版事实(反之亦然) | 版本歧义 → CLARIFY(确认问的是 NE301 还是 NE302) | 引用须与用户所指版本一致;taxonomy 含 supersede 关系(PD-1) |
| **I. Website page mentions several products**(官网一页多产品) | 单一文档内混合多产品内容 | 该页中目标产品所属段落(需逐段产品归属,见 §18 推导边界) | 同页其他产品的段落不得为目标产品背书 | 目标产品在页内无实质内容 → 按 E | 引用该页时答案须限定其目标产品段落;跨产品句子不得充当目标产品事实 |
| **J. Shared SDK/runtime docs**(neoruntime-sdks/meta-hailo-os/AIToolStack 服务多硬件) | 平台文档天然跨产品 | 声明为共享平台的源(taxonomy 标注 `shared_platform=true`)+ 与目标产品明确相关章节 | 平台文档中**其他硬件型号专属**的内容不得冒充目标产品事实 | 目标产品相关章节缺失 → 按 E | 引用共享源合法;涉具体参数须该参数与目标产品绑定(文档内出现目标型号或 taxonomy 声明适配) |

**契约实现总纲**(与 §17 实现边界对应):Target Scope 由三要素决定——①查询侧解析的目标产品集(含 page_context/site 提示);②taxonomy 声明的证据归属(源绑定/共享平台/推理映射);③引用校验的范围一致性检查。三层缺一即契约不可执行。

---

## 12. Evidence Hierarchy(CamThink V1,按真实源架构定制)

按「可信度 × 产品绑定强度」排序(V1 检索/重排偏置参考,不作为硬性互斥):

1. **Exact-product authoritative docs**:独立产品 repo(ne301-local、lowpower-camera-local)与 wiki/官网中**推导出**目标产品的专属文档(wiki 系列目录、woo category、官网产品页)。
2. **Exact-product technical/API docs**:产品的 SDK/OS/驱动层仓库中,经 taxonomy 声明绑定该产品的部分(如 meta-hailo-os ↔ NE503,neoruntime-sdks ↔ NE503 软件栈——**绑定关系本身是 PD-1 拍板内容**)。
3. **Explicitly shared platform docs**:taxonomy 标注 `shared_platform` 的源(AIToolStack、NeoMind 平台、wiki `3-hardware-dev-resources`、`4-ai-application`、`7-release-notes`)。
4. **General CamThink docs**:官网营销/通用内容(website)、wiki 未分区内容。
5. **Attributed sibling product docs**:仅在 B/C 场景可用,且必须逐条归属标注。
6. **Internal support cases**(product="knowledge",channel=api):继续作为「背景资料」参与生成但**永不可引用**(现状保持);严禁其中的历史设备标识/结论迁移为目标产品事实(既有 guardrails + CIT 体系已覆盖此点,与产品边界叠加)。

> 不采用 prompt 建议的机械顺序的说明:CamThink 真实架构中「专属 repo」与「wiki 专属区」证据质量同级(同一 wiki 是 NE503 最全的中文权威),故 1 合并两者;共享平台被显式提级为第 3 层而非兜底,因为 NeoRuntime/AIToolStack 是 NE 系列回答的合法事实来源。

---

## 13. Ambiguity Contract(歧义契约)

**触发**:查询中的产品指代无法唯一映射到 taxonomy 节点(型号缺失:「这个/它怎么升级」;部分型号:「NE5」「NE 系列」;未知型号:「NE999」;版本歧义:H)。

**行为(V1 冻结)**:
1. **禁止猜测绑定**:不得把歧义指代解析为任一具体产品后按 A 场景作答(这是 sibling 冒充的最高危入口——用户没问 NE301,系统替他选了 NE301)。
2. **解析输入优先级**:查询显式型号 > page_context.product/sku(宿主提供,消毒后)> site 上下文 > 会话历史(rewrite 后的自包含查询)。前三者冲突时视为歧义。
3. **CLARIFY 输出形态**:一轮文本提问,列出候选(≤3)请用户选择;is_answered=false 的新 outcome(复用拒答通道 + 新 message_key,见 PD-2/PD-3)。
4. **降级路径**:V1 若拍板不做交互澄清,歧义一律按 §14 INSUFFICIENT 处理(宁可拒答,不可猜产品)。
5. **NE 系列 4 兄弟现状**(NE101/NE301/NE302/NE503 同为 NeoEye 相机):任何「只提系列不提型号」的问题默认歧义——现有验收已见同系列串台风险,这是最高频触发场景。

---

## 14. Insufficient Evidence Contract(证据不足契约)

**触发定义(冻结)**:按 §12 层级 1→2→3 依次判定后,Target Scope 内可用证据仍不满足「回答该问题所需的最小证据」(具体阈值属实现参数,由 eval 标定;**判定对象是 Target Scope,不是全库**)。

**四种失败语义与现有 API/UI 的兼容映射**:

| 语义 | 触发 | 现有通道 | 差距 |
|---|---|---|---|
| `ANSWER` | Target Scope 证据充分 | complete 事件 is_answered=true | 无(行为不变,仅证据范围收窄) |
| `CLARIFY` | §13 歧义 | 无现成 outcome;复用 complete(is_answered=false) + 文本提问 + 新 message_key | PD-2(要否做)/PD-3(文案) |
| `ABSTAIN / INSUFFICIENT_EVIDENCE` | 证据不足但指代明确 | **复用既有拒答通道**(complete is_answered=false + 阶段⑯ `localized_message`;流式为单 complete 事件) | 文案须产品化:「官方资料中暂未找到 NE503 的固件升级说明」——需要新 message_key + 携带解析出的产品名(阶段⑯ message_key 机制可直接扩展);trace 需记 `target_product` + `scope_hit_count` 供观测 |
| `SUPPORT_ESCALATION` | 不足且(用户语义=排障 或 连续不足) | 无现成通道(sales lead 是唯一升级先例,不可复用其表结构) | PD-4:V1 是否做;最小形态=拒答文案附「联系技术支持」引导语(零新表) |

**红线(不可协商)**:证据不足时**绝不输出 false certainty**——不得静默降级到 sibling 证据、不得把「相似产品」内容改写为目标产品口吻、不得在 is_answered=true 的回答里夹带未归属 sibling 数值。现有兜底路径(fused top-N、support 桶、off-topic 放行附件轮)在产品边界语义下须重审:它们提升召回率的每一处,都是 sibling 污染的入口(见 §21 回归风险)。

---

## 15. Comparison Contract(比较契约)

1. **准入**:仅当解析出 ≥2 个显式产品目标(「NE301 和 NE503 哪个续航长」),或 taxonomy 识别出明确比较句式。**「NE503 怎么升级固件,NE301 的也行吗?」不算比较**——目标仍是 NE503,NE301 分句是干扰,按 A 场景处理。
2. **允许证据**:各产品的 Target Scope 并集;两侧证据不对称时,**不得**用单侧证据补齐另一侧结论——缺失侧明示「官方资料未载明 NE301 续航数据」。
3. **归属标注(冻结格式方向,措辞 PD-7)**:答案按产品分节;每节 `[N]` 限定本产品证据;涉及跨产品对比句时,数值两侧的引用编号必须分别落在对应产品证据上(引用校验可确定性检查:对比句窗口两侧数字须分别被两侧产品的源文本支持——CIT-02 数值窗口机制可扩展复用)。
4. **禁则**:不得以「同系列产品通常…」类推替缺失侧背书;不得引用 comparison 无关的第三产品。

---

## 16. Shared-platform Evidence Contract(共享平台契约)

1. **声明制**:一个源/文档区是否为「共享平台」由 taxonomy 显式声明(`shared_platform: true` + 适配产品列表),不允许运行时推测。初始声明(草案,随 PD-1 拍板):AIToolStack、NeoMind 四仓、wiki `3-hardware-dev-resources`/`4-ai-application`/`7-release-notes`、neoruntime 系(适配 NE 系列)、meta-hailo-os(绑定 NE503,实为 1:1,应归第 2 层)。
2. **可引用性**:共享平台证据可进入任意适配产品的 Target Scope,但引用呈现须保持其平台身份(SOURCE_LABELS 现状已按类型标注,产品归属依赖 taxonomy 而非猜测)。
3. **平台内的产品专属内容**:平台文档中明确写明「仅适用于 NE301」的段落,对 NE503 问题按 sibling 证据处理(禁止)。平台级参数(如 AIToolStack 的通用 API 行为)对所有适配产品可引用。
4. **J 场景裁决示例**:「NE503 上如何调用推理服务」→ neoruntime 文档(共享平台,适配 NE503)允许作答并引用;「NE503 的 Hailo 固件怎么刷」→ meta-hailo-os 生产 0 chunk(§5),Target Scope 实际为空 → 按 §14 INSUFFICIENT,而**不是**拿 neoruntime 应用文档或 NE301 的刷机文档充数。
5. **平台源的产品标签策略**:共享平台源保持其自身标签(neoruntime 等),**不**改写为目标产品标签;归属由 taxonomy 适配表在检索/校验时展开。这避免了「一个 chunk 一个产品」模型对平台文档的破坏,也是 metadata 变更最小化的关键(§18)。

---

## 17. Implementation Boundary(实现边界,REQUIRED / OPTIONAL / NOT REQUIRED)

| 层 | 判定 | 内容 |
|---|---|---|
| **metadata/indexing** | **REQUIRED** | ①taxonomy 配置(config 或 DB 表,数据驱动,**禁止**产品名 if/else 堆);②ingest 每文档产品推导:wiki 按系列目录映射、woo 已有、website 按 URL 路径映射(PD-5 定范围);③chunk `product` 写推导值;新增(或复用 metadata JSONB)**不改 Weaviate schema**——`product` property 已存在,只改赋值来源 |
| **retrieval** | **REQUIRED** | ①查询侧结构化产品解析(建议与 classify_intent 合并为一次 LLM 结构化调用,输出 `{intent, products[]}`;输入含 query/page_context/history);②Target Scope → 三路检索注入(product 过滤采用**层级闸门**:Scope 内有命中→约束在 Scope;Scope 内零命中→**不得**展开到 sibling,直接走 §14;共享平台通过适配表 OR 展开);③trace 记录 target_products/scope 决策 |
| **reranking** | **REQUIRED(轻量)** | Target Scope 内候选加分 / Scope 外(仅共享平台经适配进入的)中性;**不做** Scope 外 sibling 的「降分保留」——契约要求 sibling 不入围(比较场景 Scope 本身含双产品) |
| **prompt** | **REQUIRED** | system 增补产品边界段:目标产品声明、逐证据产品归属标签进入上下文(`[N]` 行增加 `产品:` 字段——taxonomy 显示名)、sibling 冒充禁令、不足即明示;guardrails 同步 |
| **citation validation** | **REQUIRED** | CIT-03:编号→chunk product →Target Scope 兼容性校验;不兼容剔除标记(比较场景按归属窗口校验);stats 增 `cross_product_dropped` 入 trace |
| **API** | **OPTIONAL** | `AskRequest` 增加 optional `product` 显式字段(供宿主/未来 API 调用方传权威目标);V1 可不做(查询解析已覆盖),做了须与解析结果做冲突=歧义处理 |
| **eval** | **REQUIRED** | §19/§20 矩阵 |
| **UI(widget)** | **OPTIONAL** | sources[].product 徽章展示(数据已在 payload);澄清 UI(PD-2) |
| **vector schema / 新 collection / channel_visibility / 站点契约 / lead 体系 / override_matcher** | **NOT REQUIRED** | 单 collection + 元数据在 20 万 chunk 量级足够;渠道与产品正交;override 命中即人工意志,保持现状(但在其 Admin 表单提示产品边界自负) |

**明确禁止的实现形态**(任务边界重申):不得以 `if "NE503" in question` 式产品名硬编码实现解析——一切产品知识必须落在 taxonomy 数据(taxonomy 变更 = 改配置,不改代码)。同时**不过度 genericize**:V1 taxonomy 只服务 CamThink 产品树,不做通用本体。

---

## 18. Required Metadata Changes(元数据变更清单)

1. **新增 taxonomy 配置**(建议 `config/product_taxonomy.yaml` 起步,热重载复用 customization 快照机制;量大后迁 DB):
   ```yaml
   products:
     - slug: ne503
       display_name: "NeoEye NE503"
       aliases: ["NE503", "ne503", "NeoEye NE503"]     # 查询解析与显示共用
       series: neoeye
       supersedes: null                                  # H 场景
   shared_platforms:
     - slug: neoruntime
       source_ids: ["ne503-apic-69d3594b", "neoruntime-apps-1eea74dd", "neoruntime-sdks-67cbac8f"]
       applies_to: [ne503]        # 适配产品 = PD-1 拍板
   source_bindings:               # 独立产品 repo 的源绑定(替代自由文本标签的权威)
     - source_id: meta-hailo-os-local
       product: ne503
   doc_scopes:                    # 多产品源内的文档区映射(ingest 推导规则)
     - source_id: wiki-documents-local
       rules:
         - {path_prefix: "docs/6-neoeyes-ne503-series/", product: ne503}
         - {path_prefix: "docs/5-neoeyes-ne301-series/", product: ne301}
         - {path_prefix: "docs/8-neoeyes-ne302-series/", product: ne302}
         - {path_prefix: "docs/2-neoeyes-ne101-series/", product: ne101}
         - {path_prefix: "docs/1-neoedge-ng4500-series/", product: ng4500}
         - {path_prefix: "docs/0-neomind/", product: neomind}
         - {path_prefix: "docs/3-hardware-dev-resources/", shared_platform: hardware-common}
         - {path_prefix: "docs/4-ai-application/", shared_platform: ai-common}
         - {path_prefix: "docs/7-release-notes/", shared_platform: release-notes}
   ```
   (目录前缀为本地 clone 实证;完整清单以生产 wiki 全路径核验为准——实现期任务)
2. **ingest 侧**:RawDocument.product 赋值接入 doc_scopes 推导(web_crawl 同理按 URL 规则,PD-5);未命中规则的文档回退源级标签并**记账**(run_stats 计 unscoped,复用 ⑪⑫ 可观测)。
3. **PG documents 表**:`product` 列继续存推导值;**无需**新列/新表(层内 metadata 已够;若 taxonomy 入 DB 则新配置表一张)。
4. **Weaviate**:**零 schema 变更**(`product` property 已存在)。
5. **重灌范围(=REINDEX REQUIRED)**:`wiki-documents-local`(3,891 chunks)、`website-camthink`(366,若 PD-5 纳入);其余源标签不变不重灌。重灌走既有幂等通道(确定性 UUID 覆盖写),零风险窗口,但须避开 GPU 修复窗口与 sync 运行期(09-03 事故教训)。
6. **生产标签治理**(OPTIONAL 但强烈建议):data_sources.product 自由文本与 taxonomy 对齐(meta-hailo-os→ne503、neomind-* 收敛、AI-ToolStack 大小写)——此为 Admin 操作非迁移,可与 PD-1 同批。

---

## 19. Required Tests(必须新增的测试面)

1. **taxonomy/解析层**:别名归一(NE503/ne503/NeoEye NE503→ne503);歧义判定(D);比较句式解析(C 准入);page_context/历史与显式型号的冲突仲裁。
2. **ingest 推导层**:wiki 路径→product 映射表驱动单测;未命中回退+记账;woo category 既有映射回归;`channel_visibility` 与推导正交性。
3. **检索闸门层**:Scope 内有命中→过滤生效(Weaviate filter 组合);**Scope 内零命中→候选为空**(断言不展开 sibling,这是 E 场景检索级 RED→GREEN 的核心断言);共享平台经适配表展开;三路检索(hybrid/symbol/bucket)过滤一致性;兜底路径(fused top-N)在 Scope 约束下不引入 Scope 外 sibling。
4. **生成层**:prompt 含目标产品与归属标签(golden messages 断言);insufficient 时走拒答分支且文案含产品名(message_key 机制单测,阶段⑯同构)。
5. **citation 层(CIT-03)**:串台标记剔除(答案引 [N] 且 N 属 sibling → dropped,stats.cross_product_dropped+1);比较场景双侧数字窗口校验;共享平台引用放行;不误伤共享文档合法引用。
6. **端到端(§20 E2E 级)**:隔离库种子双产品语料(NE503 少量 + NE301 同主题强证据),断言回答不含 NE301 事实/引用;比较场景双侧归属。
7. **回归面**:现 1112 绿基线全量保持;特别盯既有兜底/boost 桶/off-topic-附件轮语义不因 Scope 收窄而意外拒答(需 §21 的缓冲设计)。

## 20. Eval Matrix(cross-product 评测矩阵,自动化最小集)

| ID | 场景 | 种子条件 | 断言(自动化可验) | 级别 |
|---|---|---|---|---|
| XM-R1(负例) | NE503 问题 + NE503 证据零命中 + NE301 同主题强证据 | 隔离库 | 检索候选 ⊆ Target Scope(=空);**候选中出现 NE301 chunk = FAIL** | retrieval |
| XM-R2 | NE503 问题 + NE503 证据在场 | 同上 | top-k 全部 Scope 内;共享平台 chunk 仅限适配表 | retrieval |
| XM-R3 | 比较问题 | 双产品证据 | 双产品候选均在场 | retrieval |
| XM-G1(负例) | XM-R1 条件继续走到生成 | 同上 | is_answered=false;文案含「NE503」+不足语义;**MUST NOT** 出现 NE301 型号/其数值 | generation |
| XM-G2 | NE503 问题,Scope 内证据充分,上下文混入 NE301(闸门关闭注入) | 混合上下文 | 答案事实全部有 Scope 内 [N] 支持 | generation |
| XM-G3 | 比较问题单侧缺失 | NE301 证据足/NE503 无 | NE503 侧明示不足;不得以 NE301 数值填 NE503 | generation |
| XM-C1(负例) | 闸门关闭状态下 LLM 输出串台 [N](对抗 prompt) | 构造答案 | 引用校验剔除 sibling 标记;stats.cross_product_dropped≥1 | citation |
| XM-C2 | 合法共享平台引用 | 平台证据 | 标记保留不误伤 | citation |
| XM-E1 | E2E:真栈问「NE503 怎么升级固件」 | 生产镜像语料 | 无 sibling 冒充(关键词+引用审计);不足时文案正确本地化 | e2e |
| XM-E2 | E2E:「对比 NE301 和 NE503 续航」 | 同上 | 双侧归属;双侧数字各有其源 | e2e |
| XM-E3 | E2E:「这个怎么升级固件」无上下文 | 同上 | 澄清或拒答,**不得**猜型号作答 | e2e |

判定规则:XM-R1/XM-G1/XM-C1 为**发布阻断项**(回归防线的存在证明);矩阵全部可离线隔离库运行(TEST_DATABASE_URL 既有约定),不依赖 GPU(重排可用 fake reranker 单测层覆盖,E2E 级再上真模型)。

---

## 21. Regression Risks(回归风险)

1. **拒答率上升(最高风险)**:任何产品问答现在都有全域语料兜底;收窄 Scope 后,当前靠 sibling 内容「碰巧答对」的场景会转为拒答。09-01 验收 93 场景中 P52 通过场景可能部分翻拒答。**缓解**:上线前用 93 场景集重跑对照,量化「正确收窄」vs「误伤」,误伤清单反馈 taxonomy 补共享声明(多数应为共享平台缺声明,而非产品边界错误)。
2. **兜底/boost 语义冲突**:support 桶(product="knowledge" 跨产品设计)、fused top-N 兜底、附件轮 min=0 三处既有放行逻辑与新 Scope 闸门的叠加顺序须在实现期显式冻结(建议:闸门先行,knowledge 桶结果仅进背景资料——与现状一致的禁引用语义,避免行为漂移)。
3. **wiki 重灌窗口**:重灌期间检索可能短暂缺 wiki 证据(增量幂等可分文档滚动);须避开 sync 运行期与 GPU 故障窗口(09-03 cuInit/OOM 事故教训),且生产未部署前 wiki 推导值与查询闸门不得单独上线(半态:闸门开了、推导没灌=全拒答)。
4. **查询解析误判**:产品解析是新的 LLM 步骤,误判会把 NE503 问题绑到 NE301(比现状更糟——现状至少还看文本相似度)。缓解:解析置信度低→歧义路径;解析与检索 Scope 冲突时(fail-safe)放行检索但靠 CIT-03 兜底;eval 矩阵覆盖。
5. **排序行为漂移**:重排 Scope 加分改变既有 top-k 组成,可能触发 rerank 滤光兜底更频繁——trace 已有 fallback 标记,观察窗口纳入部署验收。
6. **override_matcher 旁路**:人工覆盖答案不受新契约约束(设计使然),但 Admin 侧需知晓:覆盖答案若本身串台,系统不再有下游拦截(PD 侧知会即可)。

---

## 22. Recommended Execution Mode(建议执行模式)

- **模式**:单 Executor 实现 + Planner 双审(FINAL REVIEW),沿用 contract→handoff→独立 worktree 协议;**契约冻结后允许独立实现,无需再次 Discovery**。
- **顺序建议**(可切两波):
  - **Wave-1(契约核心,先行)**:taxonomy 配置机制 → ingest wiki/website 推导(本地隔离库验证)→ 查询产品解析(与 intent 合并一次 LLM 调用,控延迟)→ 检索 Scope 闸门(三路一致)→ §19.3 检索级测试(含 XM-R1 RED→GREEN)。
  - **Wave-2(语义闭环)**:prompt 归属段 + CIT-03 + message_key 扩展(§14)+ eval 矩阵全量 + 93 场景对照报告。
- **部署耦合**:实现合入 ≠ 生产生效;生产生效 = ①taxonomy 部署 ②wiki/website 重灌完成 ③服务升级**三者同窗**(§21.3 半态红线);纳入下一轮部署 runbook 作为 REQUIRED 步骤。
- **前置依赖**:PD-1~PD-7(§23)拍板;GPU 修复窗口(meta-hailo-os/neoruntime-sdks 入库后 NE503 第 2 层证据才真实存在,eval 的 XM-E1 才能反映终态)。

---

## 23. Final Verdict

### Verdict: **NEEDS_PRODUCT_DECISION**

理由:架构挂载点全部确认存在(product property 可过滤、拒答/message_key 通道现成、语料身份可恢复),实现边界与契约已冻结到可派发粒度;**但以下拍板项是实现的直接输入,缺项不可开工**。Discovery 侧无 BLOCKED 事项。

**待产品拍板清单(均附建议)**:

| PD | 决策项 | 建议 |
|---|---|---|
| PD-1 | **canonical 产品 taxonomy 内容**:产品清单/别名/系列关系(H)/共享平台声明与适配表(meta-hailo-os→ne503?neoruntime 适配哪些?) | 按本报告 §5/§16 草案为基线,产品负责人确认后冻结;这是 Wave-1 第一行的输入 |
| PD-2 | 歧义时是否做**交互式澄清**(新 outcome + widget UI)vs V1 一律按证据不足拒答 | V1 先做文本澄清(复用 complete 通道+新 message_key,零 UI 改动);交互 UI 延后 |
| PD-3 | INSUFFICIENT 文案与 message_key(产品化措辞:「暂未找到 NE503 的…」) | 沿阶段⑯冻结文案机制,建议 V1 用「官方资料中暂未找到 {product} 的相关说明,建议联系技术支持」双语一对 |
| PD-4 | SUPPORT_ESCALATION 是否进 V1(现在无支持通道) | V1 仅文案引导(PD-3 内嵌),不建表不建流程 |
| PD-5 | website-camthink(366 chunks)是否纳入本轮逐页产品推导(官网一页多产品,推导规则较 wiki 脆弱) | 建议纳入但只做**产品页**(URL 模式明确者),未识别页保持 general 层级 |
| PD-6 | 内部案例桶(product="knowledge")在产品边界下维持「背景禁引用」现状 | 维持现状(与 P0 信任边界一致),不额外放开 |
| PD-7 | 比较场景归属标注的展示格式 | 分节 + 每节产品名标题;sources[].product 徽章(数据已有)为加强项 |

**给 Planner 的核验锚点**:routes.py:271-284(product_filter 缺失)、schemas.py:82-153(无 product 字段)、rag.py:438(support 桶跨产品)、rag.py:1059-1142(兜底旁路)、citation.py 全文(零产品语义)、config/system_prompt.yaml(零边界条款)、§5 两份生产只读取证、§4.3 wiki 本地 clone 目录实证、tests/ 无 cross-product 用例。

---

*DISCOVERY ONLY — 本报告零代码/配置/生产变更。生产只读访问:SSH SELECT data_sources(1 次)、Weaviate GraphQL Aggregate(2 次成功 + 4 次语法试探失败)、Get 抽样(1 次,3 条)。等待 Planner 独立 Review。*
