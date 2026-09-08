# I-002 Evidence Intelligence — Engineering Discovery

> **性质**:只读工程发现(READ-ONLY DISCOVERY)。零实现、零生产触碰、零 Benchmark 运行。
> **基线**:I-001 Answer Intelligence Foundation COMPLETE(9/9,PR #35 / merge `1790909`,main=`a364240`);Benchmark v1 冻结(80.2/100,I-001 前);全部既有契约(INC-1/2a/3)保持,除非证据证明实质不兼容。
> **日期**:2026-09-08。全部结论基于当前仓库代码实证(file:line 可溯),不依赖架构文档记忆。

---

## 1. Executive Conclusion

I-002「证据智能」的三个增量在现有代码上**全部具备确定性实现路径,且默认不需要新增任何 LLM 调用**:

1. **INC-2b(摄取信任边界)** — 机制面已就绪:INC-2a 的 `evidence_sensitivity` 属性、`internal` 可见性标记约定、4 处"只写属性不重嵌入"的 `data.update` 先例均已存在。缺口仅在**判定策略**(什么内容算敏感)与**执行点接线**(检索过滤 + 组合时复核)。工程形态 READY_FOR_CONTRACT;契约需附带 3 个产品级策略决策与一份生产只读聚合证据清单。
2. **INC-4(证据规划 + slot 驱动检索)** — **确定性规划可行且有直接先例**:`TaskUnderstanding`(category/interaction_mode)+ `ProductResolution`(mode/targets)已提供规划全部输入;`INTENT_BOOST_FILTERS`(rag.py:423-427)就是现成的"按源角色检索"机制;比较管线的 per-target 配额是现成的"slot 结构性保障"机制。零新增 LLM 调用即可覆盖产品目标列出的全部 8 类证据需求。READY_FOR_CONTRACT。
3. **INC-5(类别感知选择/组合)** — 组合阶段的类别感知先例已存在:`_merge_per_target_candidates` 的 tier1(官方非代码)/tier2(代码)分层配额(rag.py:199-260)证明确定性类别感知组合在这条管线上可行、已被生产验证。INC-5 = 把该先例从"比较模式专用"推广为"任务槽位驱动"。READY_FOR_CONTRACT,**以 INC-4 的 EvidencePlan 契约冻结为先决接口**。

**核心结构性事实**(贯穿三个增量):INC-2a 的 5 个证据元数据字段已持久化、已读回 SearchResult,但**判定链路零消费**(§3);当前管线在 rerank 之后的全部行为都假设"相关 chunk 即足够"——唯一例外是比较路径的结构性配额。I-002 的本质就是把这个例外一般化。

**依赖图结论**:INC-2b ⊥ INC-4(互相独立,可并行);INC-5 依赖 INC-4 的契约冻结(非实现完成);rag.py 双路径(answer/stream)同位接线是唯一强串行点。

---

## 2. Current Runtime Map(当前运行时真链,代码实证)

### 2.1 主链路(answer 与 stream_answer 双实现同位)

```
product_resolver.resolve(query, history, page_context)        ← 产品身份权威(先于理解)
    → ProductResolution(mode/targets/source)                   rag.py:1277-1310 前置
task_understanding.understand_task(query, history, llm)        单次 LLM 调用
    → TaskUnderstanding(category/reason/confidence/            rag.py:1312(answer)/
      interaction_mode/extracted/rewritten)                    rag.py:1932(stream)
    → resolver 确立目标时 clarification→standard 确定性调和     rag.py:1334-1347
    → off_topic / clarification_required / capability_orientation
      三短路(不检索)                                          rag.py:1367-1446
    → search_query = rewritten(主 hybrid 消费)
      extracted = extracted(符号/boost 桶消费)                 rag.py:1319-1320

_retrieve_and_fuse(extracted, search_query, category,          rag.py:1503(answer)/
    product_filter, channel, product_labels)                   rag.py:2149(stream)
    三路:hybrid(search.py:218-224,过滤器=channel_visibility 探测
          + product 标签 equal/any_of)
         + search_symbols(extracted;symbol BM25)
         + search_bucket(extracted;INTENT_BOOST_FILTERS:       rag.py:423-427
             support→source_type=["filesystem"]
             product→chunk_type= prose 四类
             commercial→source_type=["woocommerce"])
    → rrf_fuse 三路融合(rrf.py)                                rag.py:816
    → _apply_visibility_guard(fail-closed 纵深)                rag.py:821, 846-864
    → candidates 身份表(rank/source_id/chunk_index/score/paths)rag.py:834-843

rerank:search_query × chunk 文本 cross-encoder(bge-reranker-v2-m3),
    chunk_type type_weights 乘性加权                            rag.py:1521
prune(可选):search_query + texts 逐块评估                     pruner.py:20-67
    → prune_decisions 血统(rag.py:1542-1550)
防御性二次过滤(eligible_slugs 兜底出清)                        rag.py:1556-1570
比较路径:per-target 检索 + tier1/tier2 分层配额合并            rag.py:866-1030,
    + 按目标聚焦重排 + 缺侧显式不足语义                         1465-1501, 1582-1627

composition:build_citation_context(reranked, sources,          citation.py:102-180
    taxonomy)——url→编号映射;source_type∈PUBLIC_SOURCE_TYPES
    之外进「背景资料」段;可见集外公开 chunk 丢弃
generation:_build_messages(query, cite_ctx.context, …,         rag.py:1050-1092,
    intent 风格 + product_boundary)                            1692-1700
```

### 2.2 各阶段信息可用性 / 阶段间丢失

| 阶段边界 | 向前传递 | 在此丢失 |
|---|---|---|
| 理解 → 检索 | rewritten/extracted/category/interaction_mode(路由);resolution→product_filter/scope_labels/boundary | **任务类型语义无结构表达**:troubleshooting vs factual vs current-price 在检索侧只剩"查询字符串"差别;interaction_mode 仅作路由不进检索 |
| 检索 → 重排 | SearchResult 全字段(含 evidence_*/chunk_type/doc_section/symbol_*/channel_visibility) | 路径成员(paths)只进 trace 不进决策;RRF 分仅存 score |
| 重排 → 剪枝 | search_query + texts(+chunk_type 权重已在 rerank 用掉) | **evidence_* 全部被忽略**;chunk 间互补性/冗余性无概念 |
| 剪枝 → 组合 | SearchResult 列表原样 | 同上;块级语义在此后彻底消失 |
| 组合 → 生成 | cite_ctx.context 文本(编号=URL 映射;背景段按 **source_type** 规则) | chunk 级证据语义不进 prompt;背景判定键是 source_type 而非 sensitivity/citation_eligibility |

### 2.3 "相关 chunk 即足够"假设的位置

- **rerank 分序即终序**:top_k 截断后直接进组合(rag.py:1521,1573-1576),无任何"这个任务需要什么证据"的覆盖检查;唯一兜底是 rerank 滤光后的 fused top-N 降级(rag.py:1629-1673)。
- **组合只做可见性编排**(编号归属/背景段/丢弃),不做角色/权威/时效/互补编排。
- **显式不足语义已存在两处**:比较缺侧(rag.py:1582-1627)与产品化不足(`_product_insufficient_reply`,rag.py:1637-1665)——INC-5 的"insufficient-evidence signaling"有现成契约形态可推广。

### 2.4 证据角色/类别现在可以寄身的位置

1. `SearchResult` 字段(已含 INC-2a 五元组 + chunk_type/doc_section/source_type/product/symbol_*)——**最自然的载体,已就绪**。
2. `INTENT_BOOST_FILTERS` / `search_bucket`(源角色→检索过滤的既有映射)。
3. `_merge_per_target_candidates` tier 分层(类别感知组合的既有机制)。
4. trace:`retrieve.candidates[]` / `rerank.prune_decisions[]`(INC-1 血统形态,INC-5 coverage 报告可复用此形态)。

---

## 3. INC-2a Metadata Consumption Map(AVAILABLE vs ACTUALLY CONSUMED)

### 3.1 AVAILABLE(已存在)

| 面 | 证据 |
|---|---|
| Schema 属性 | `COLLECTION_PROPERTIES` 19 属性含 5 个 `evidence_*`(ingest.py:96-122,117-121) |
| 摄取写入 | `_build_props` → `**_evidence_props(doc)`(ingest.py:125-143,180);三条写路径 :324/:363/:671 全覆盖 |
| 确定性派生 | `derive_evidence_meta(source_type, channel_visibility)` 纯函数(evidence_meta.py:104-177):authority=恒 unknown(:149-151);sensitivity=仅显式 `internal` 标记(:153-158);citation=镜像 PUBLIC_SOURCE_TYPES(:160-166);temporality=恒 unknown(:168-169);origin=4 字符 A/T/S/C 码 |
| 存量回填 | `migrate_backfill_evidence_meta.py`:`collection.data.update` 只写属性、零重嵌入、幂等、dry-run 默认(:191-213) |
| Schema 迁移 | `migrate_add_evidence_meta_props.py`(`col.config.add_property`,不触对象/向量) |
| 检索读回 | `_to_search_result` 显式 unknown 缺省映射进 SearchResult(search.py:395-430;缺省表 :32-38) |

### 3.2 ACTUALLY CONSUMED(实际被消费)

**判定链路零消费。** grep 全管线:rag.py / citation.py / pruner.py 对 5 个 evidence 字段的引用为 **0 处**。具体:

- 检索过滤:hybrid/symbol/bucket 三路的 Weaviate 过滤器只有 channel_visibility + product 标签(search.py:218-224,263-267,358)——**sensitivity/citation_eligibility 不参与任何过滤**;
- 重排:只看文本相似度 + chunk_type 权重;
- 剪枝:只看文本;
- 组合:`build_citation_context` 用 `r.source_type in PUBLIC_SOURCE_TYPES` 现场重判背景段(citation.py:157-172)——**不用已持久化的 evidence_citation_eligibility**,即存在"镜像语义双权威"漂移面(当前两者恰好一致,因 derive 即镜像);
- trace:连观测都未覆盖——`retrieve.candidates[]` 只有 rank/source_id/chunk_index/score/paths(rag.py:834-843),`rerank.results[]` 只有 source_id/chunk_index/title/score/source_type/product/url/text(rag.py:1032-1049),**evidence_* 不在任何 trace 键里**。

**结论**:INC-2a 交付的是"写+读可用性",消费面 100% 留给 I-002。这是干净的——零消费意味着零历史行为耦合,INC-2b/4/5 接线不会破坏任何既有判定。

### 3.3 冻结语义中与 I-002 相关的两个预留

- `personal-data` sensitivity 值**保留给 INC-2b 内容审查**,当前映射永不赋值(evidence_meta.py:86-88,131)——INC-2b 的判定策略落点已被上游契约预留。
- "missing internal ≠ public"(evidence_meta.py:127-131)——unknown 的安全语义已定调,INC-2b 不得把 unknown 自动升级为 public。

---

## 4. INC-2b Discovery Findings(摄取信任边界)

### 4.1 敏感内容入口(代码实证)

| 入口 | 现状 | 风险面 |
|---|---|---|
| `filesystem` | `path.read_text` 原样入语料(filesystem.py:110);文档明确其为"support 内部案例"载体(rag.py:1148-1150,citation.py:8);闸门仅 file_types/include_dirs/ExclusionPolicy + 技术安全 | **最大暴露面**:内部案例内容可被检索进生成(背景段),仅靠"不展示为来源"隔离 |
| `github` | 支持 private repo(GITHUB_TOKEN 嵌 clone URL,github.py:82,102-111),私有内容无 internal 标记入语料 | 私有仓库内容可进入访客可见生成 |
| attachments | 用户上传 .txt/.log,PII 脱敏后**注入 prompt,不入 Weaviate**(routes.py:612,rag.py:1098-1101) | 已脱敏且不经语料,基本在 chunk 信任边界之外 |
| `woocommerce`/`web_crawl` | 公开商务/官网内容 | 低 |
| `local_git` | 未注册但仍在 PUBLIC_SOURCE_TYPES(citation.py:54-56) | 卫生项 |

### 4.2 现有脱敏与安全闸

- `mask_pii`:regex 双规则(邮箱/中国手机号),**仅查询时与附件时**应用(routes.py:128,612;lead_service.py:64);**摄取路径零脱敏**(ingest.py 无任何 PII 逻辑)。
- `TechnicalSafetyPolicy.check_content`(ingest.py:285,546;safety.py):整文档**拒绝**(二进制伪装/超限/私钥 armor),从不改写——既有先例是 **reject-not-rewrite**。
- `channel_visibility=["internal"]` 是唯一的"内部"约定(源级配置,migrate_channel_visibility.py:11);检索探测渠道永不匹配 `internal`(evidence_meta.py:72-76),即 internal 源天然全渠道不可见。

### 4.3 最小工程形态(发现结论)

1. **脱敏不必先于嵌入**——若 INC-2b 目标是"内部内容不出现在访客答案",正确机制是**标签 + 过滤**而非内容改写:内容不改写 ⇒ **零重嵌入**(改写才需要重嵌)。这与 4 处既有 `data.update` 只写属性先例一致(channel_visibility 回填:172;evidence 回填:205;store metadata:144-146;product migration:138-150)。
2. **判定策略是唯一真缺口**:sensitivity 当前唯一判定 = 显式 internal 标记(E 溯源);`personal-data`(内容审查派生)被预留但无实现。契约需冻结:谁生产 `personal-data` 判定(内容审查工具?管理员标记?),以及 **unknown 的执行语义**。
3. **执行点两个**:
   - 检索过滤:三路 search 增加 sensitivity 约束参数(search.py 最小扩展;fail-closed 方向 = internal/personal-data 对非 internal 探测渠道拒绝);
   - **组合时复核**:metadata 可能滞后(迁移窗口/幽灵对象),`build_citation_context` 入口处按 SearchResult.evidence_sensitivity 复核背景段资格——落点即现行的 source_type 背景规则旁。
4. **citation eligibility 与 sensitivity 的交互**:当前 citation_eligibility 是摄取期镜像(PUBLIC_SOURCE_TYPES),组合期不用它而用 source_type 重判。INC-2b 应把组合判定切到字段权威(evidence_citation_eligibility + evidence_sensitivity 双条件),消除双权威漂移。
5. **迁移/回填含义**:schema 属性已存在(零 DDL);判定结果回填 = 既有 `data.update` 幂等模式;**不触发任何重嵌入**。唯一触达向量的情形是选择"内容改写式脱敏"(见 §4.3-1,不推荐为 v1)。

### 4.4 契约前必须拍板的策略决策(产品级,非工程级)

- **PD-2b-1**:unknown sensitivity 的执行语义——(a) 维持可检索(现状;推荐,与"missing internal ≠ public"一致靠组合复核兜底)或 (b) 对公开渠道 fail-closed(召回成本显著);
- **PD-2b-2**:`personal-data` 判定的生产者与时机(内容审查工具离线批量 vs 摄取时启发式 vs 人工标记);
- **PD-2b-3**:既有 filesystem 内部案例源的处置(整体 internal 标记 vs 逐文档审查)。

### 4.5 PRODUCTION_EVIDENCE_REQUIRED(最小只读清单)

冻结 INC-2b 回填规模需生产**聚合只读**证据(不需要内容级审查授权):

1. 按 `source_type × evidence_sensitivity × channel_visibility` 的 chunk 计数聚合(Weaviate aggregate,零内容读取);
2. 现有 `internal` 标记源的清单与各自 chunk 数;
3. filesystem 源的文档数/chunk 数聚合(规模估计)。

---

## 5. INC-4 Discovery Findings(证据规划 + slot 驱动检索)

### 5.1 规划输入已全部就绪

`TaskUnderstanding`(category/interaction_mode/extracted/rewritten)+ `ProductResolution`(mode/targets/source)+ 比较维度(`_comparison_dimension`,rag.py:356)构成确定性规划的完整输入。**不需要再问 LLM 任何问题**。

### 5.2 确定性规划表示可表达产品目标列出的 8 类需求(映射表候选)

| 任务形态(判定输入) | slot 结构(候选契约) | 检索实现(全部既有机制) |
|---|---|---|
| factual product lookup(product+exact) | slot[spec-doc:product=X] | hybrid + product 标签过滤(既有) |
| comparison(resolver MODE_COMPARISON) | slot[per-target:tier1 官方]×N | `_merge_per_target_candidates` 配额(既有,rag.py:199-260) |
| current commercial truth(commercial) | slot[store-official, currency=prefer-current] | commercial boost 桶(既有);currency 为**偏好**直到时效元数据存在(见 5.4) |
| battery/power evidence(support/product+power 术语) | slot[spec/calculator-doc] | doc_section/url 特征过滤(需小扩展:bucket 过滤器加 doc_section 前缀,或 slot→查询变体) |
| troubleshooting(support) | slot[case-evidence(filesystem), spec-doc] | support boost 桶 = filesystem(既有,rag.py:424)+ hybrid |
| recommendation/solution(product+solution) | slot[spec, solution-doc],多 slot 覆盖 | 多 slot = 多查询变体进 rrf_fuse(既有融合器) |
| capability/orientation(interaction_mode=capability) | **零检索**(已短路,rag.py:1420-1446) | 既有 |
| clarification_required | **零检索**(已短路,rag.py:1393-1419) | 既有 |
| insufficient evidence | 不进规划;由 INC-5 覆盖检查输出 | 既有不足语义形态(rag.py:1582-1665) |

### 5.3 最小规划契约(候选)

```python
@dataclass(frozen=True)
class EvidenceSlot:
    role: str            # 冻结词表:spec_doc / case_evidence / store_official /
                         #   calculator_doc / solution_doc / comparison_target
    product_scope: tuple[str, ...]   # 空 = 继承 resolution 目标
    source_role_pref: tuple[str, ...] # source_type/chunk_type 偏好(软约束)
    required: bool       # required 且未覆盖 → insufficient 信号(INC-5 消费)

@dataclass(frozen=True)
class EvidencePlan:
    slots: tuple[EvidenceSlot, ...]
    strategy: str        # standard / comparison / support_troubleshoot / commercial_current
    derived_from: dict   # category/interaction_mode/resolution.mode(可观测归因)
```

派生函数 `derive_evidence_plan(understanding, resolution, dimension) -> EvidencePlan` 纯确定性、零 LLM、零 IO——可表驱动黄金测试。

### 5.4 是否需要额外 LLM 调用:**NO(实证)**

- understand_task 已单次产出 category+interaction_mode(契约 §7 one_call=True,rag.py:1328);
- 上表 8 类→slot 映射全部可由 (category, interaction_mode, resolution.mode/targets, 维度词) 确定性查表得出;
- 唯一似 LLM 的候选是"从自由文本识别 battery/power 等证据主题"——但 benchmark 契约的 `required_evidence_roles` 词表(WIKI/SPECIFICATION/EXACT_PRODUCT/SOLUTION)与 doc_section/chunk_type/url 特征已提供确定性抓手;若契约测试证明查表召回不足,升级为**修订裁决**而非默认加调用。
- ⚠️ 冻结语义注意:时效槽位(current commercial truth)依赖 temporality,而 INC-2a 冻结 temporality=恒 unknown。**INC-4 契约应包含一条 evidence_meta 确定性扩展裁决**(source_type=woocommerce → temporality=volatile_current 类;仍是 source_type 结构事实派生,不违反"禁 LLM 分类"条款,但构成对 INC-2a 冻结词表的 formal amendment,需 A 授权)。在此之前 currency slot 一律降级为 source_role_pref 软偏好——不阻塞 INC-4 主契约。

### 5.5 检索侧最小扩展(不替换 HybridSearcher)

- slot→检索 = 复用 `_retrieve_and_fuse` 机制:每 required slot 一次 `search_bucket`/带过滤 hybrid(查询变体=extracted 或 slot 限定词),结果并入 rrf_fuse 或按 slot 配额合并(推广 `_merge_per_target_candidates`);
- `search_bucket` 过滤器参数扩展(doc_section 前缀 / source_type 集)——search.py 现有过滤器函数式扩展,零替换;
- INC-2b 的 sensitivity 过滤参数在同一路径落地(见 §9 接口冻结)。

---

## 6. INC-5 Discovery Findings(类别感知选择/组合)

### 6.1 "高相关 chunk" vs "本任务的正确证据集"的区分机制

现有管线唯一做过此区分的位置 = 比较管线 tier1/tier2 配额(rag.py:216-232):**客户面向官方证据(chunk_type≠code)结构性优先于代码证据**,"ne301 路融合前 5 席曾为 4 代码+1 FAQ,官方证据被代码饿死"是 RCA 实证。这就是"相关≠正确"的产品级证据——推广它即 INC-5。

### 6.2 责任落点(发现结论)

**剪枝之后、build_citation_context 之前**,新增确定性选择阶段:

- 输入:reranked(或降级 fused)SearchResult 列表 + EvidencePlan(INC-4);
- SearchResult 已携带全部判定信号(chunk_type/doc_section/source_type/product/symbol_*/evidence_*),**零新读回**;
- 职责:逐 slot 覆盖检查(role 匹配 = source_type/chunk_type/doc_section/url 特征的确定性谓词)→ 权威感知排序(evidence_authority_class;unknown 时按 source_type 既有标签降级)→ 产品隔离(既有 eligible_slugs 谓词,rag.py:1556-1570 同式)→ 冗余消除(同 source_id+doc_section 邻近 chunk 去重;rrf 去重键 (source_id,chunk_index) 之上)→ 输出 selected 集 + **coverage report**(未覆盖 required slot 列表);
- coverage report:required slot 未覆盖 → 推广既有不足语义(rag.py:1582-1665 形态)显式降级/拒答;可选 slot 未覆盖 → 上下文诚实标注段(背景段机制,不加编号);
- `build_citation_context` 消费 selected 集,签名可保持(组合判定切字段权威,见 §4.3-4)。

### 6.3 权威/时效的可执行性现实

- authority:全量 unknown(3.1)→ v1 权威感知 = **source_type 标签**(woocommerce=官方商店/wiki=官方文档——benchmark evidence_manifest 的权威分层即按此类构建);evidence_authority_class 消费留待其派生策略扩展(与 5.4 时效扩展同批裁决);
- temporality:同上,currency 现阶段=store_official slot 软偏好。

### 6.4 answer/stream parity 约束

全部选择逻辑必须 answer(rag.py:~1556-1690)与 stream(rag.py:~2128-2260)两处同位接线——既有 parity 模式(比较管线已示范:共用 `_comparison_evidence_pipeline` 抽象)。INC-5 契约应要求选择器为独立纯函数模块,两路径各一行调用,避免第三份复制。

---

## 7. Trust-Boundary Findings(汇总)

1. 现行信任边界 = 源级二元(internal 标记 × channel_visibility)+ 呈现层白名单(PUBLIC_SOURCE_TYPES,"display-layer, not the trust boundary",citation.py:51-56)+ fail-closed 可见性守卫(rag.py:846-864)。**chunk 级 sensitivity 已持久化但零执行**。
2. filesystem 是主要暴露面(内部案例进背景段可影响生成);github private repo 次之。
3. 脱敏(内容改写)不是 v1 必要路径;标签+过滤+组合复核即可达成产品目标且零重嵌入。
4. 附件路径已 PII 脱敏且不入语料,不在 INC-2b 范围。
5. 组合期复核必要性成立:metadata 滞后窗口(迁移期/幽灵对象)是既有事故模式(S0 幽灵源、prune 误删前科),单一检索闸门不满足纵深原则(与 P0 信任边界交付的 Case A/B/C fail-closed 先例同构)。

---

## 8. Evidence Planning Contract Candidates

见 §5.3(EvidenceSlot/EvidencePlan/derive_evidence_plan)。补充契约边界:

- 规划派生**必须纯确定性**(表驱动),失败回退 = 单 standard slot(类比 understand_task 的 fail-open,永不阻断);
- slot 词表冻结点 = INC-4 契约;INC-5 coverage 谓词消费同一词表;
- plan 进 trace(stages.plan:slots/strategy/derived_from)复用 INC-1 血统形态;
- 性能预算:派生为内存查表,<1ms;不新增任何 LLM/token 成本。

---

## 9. Retrieval Capability / Gap Analysis

| 能力 | 现状 | INC-4/2b 需求 | 缺口大小 |
|---|---|---|---|
| 混合检索+RRF | ✅ 三路融合(rag.py:748-816) | 直接复用 | 无 |
| 渠道/产品过滤 | ✅ contains_any + equal/any_of(search.py:218-224,59-70) | 直接复用 | 无 |
| 源角色检索 | ✅ search_bucket(source_type/chunk_type 过滤) | slot→bucket 参数化 | 小(参数扩展) |
| 查询变体 | ✅ rewritten/extracted 双查询已并存 | slot 限定变体 | 小 |
| per-target 结构保障 | ✅ 比较管线配额 | 推广为 slot 配额 | 中(泛化+回归面) |
| sensitivity 过滤 | ❌ 无 | INC-2b 过滤参数 | 小(search.py 三路 +1 参数) |
| 时效过滤 | ❌ temporality 全 unknown | currency 软偏好(v1) | 依赖 §5.4 裁决 |
| 权威过滤 | ❌ authority 全 unknown | source_type 标签代位(v1) | 无阻断 |

**结论:不需要替换 HybridSearcher/RRF/reranker;全部需求在既有机制上为参数化/组合扩展。**

---

## 10. Evidence Selection / Composition Capability / Gap Analysis

| 需求 | 现状 | 落点 |
|---|---|---|
| 类别感知选择 | ✅ 先例=比较 tier 配额(rag.py:216-232) | 推广为 slot 覆盖选择器 |
| 权威感知 | 标签代位(source_type) | 选择器排序键 |
| 时效/现行性 | 无(currency=store slot 软偏好) | §5.4 裁决后升级 |
| 产品隔离 | ✅ eligible_slugs 谓词(检索硬过滤+防御兜底) | 选择器继承同谓词 |
| 互补源角色 | 部分(INTENT_BOOST_FILTERS 召回侧;组合侧无) | slot 覆盖检查 |
| 覆盖完整性 | ❌ 仅比较缺侧检查 | coverage report(核心新增) |
| 冗余消除 | 仅 (source_id,chunk_index) 去重 + 来源截 5 | 同源邻近去重 |
| unsupported slots | 比较缺侧形态已有 | 推广 |
| insufficient-evidence 信号 | ✅ 两种既有话术契约(rag.py:1596-1627,1637-1665) | coverage 触发同形态 |

---

## 11. Dependency Graph

```
INC-2b(标签策略+检索过滤+组合复核+回填)  ──┐
                                              ├── 互相独立,可并行
INC-4(EvidencePlan 契约+确定性规划+slot 检索)┘
        │ 契约冻结(Slot 词表+EvidencePlan+coverage 形态)
        ▼
INC-5(slot 覆盖选择+冗余消除+insufficient 推广)
```

- **INC-2b 独立执行?是。** 不依赖 plan/selection;其检索过滤参数是 search.py 签名扩展,INC-4/5 不实现也能落地(内部源现状已全渠道不可见,过滤参数主要覆盖 chunk 级 personal-data 与纵深复核)。
- **INC-4 需要 INC-2b?否。** slot 检索消费 source_type/chunk_type/product/doc_section 全部既有;"不得用内部证据支撑公开断言"类约束属组合期,可由 INC-5 或 INC-2b 复核承担,不构成 INC-4 前置。
- **INC-5 需要 INC-4?是(契约级)。** 无 slot 语义则覆盖检查退化为纯类别感知,价值坍缩;依赖的是**契约冻结**而非 INC-4 实现合并。
- **并行前必须冻结的接口**:① EvidenceSlot/EvidencePlan dataclass + role 词表;② coverage report trace 形态;③ `search()`/`search_bucket()` 可选过滤参数位(sensitivity_exclude + doc_section prefix);④ `build_citation_context` 输入仍为 SearchResult 列表(签名不变)。
- **必须串行的**:rag.py 同位接线条目(answer/stream 各自的 plan 接线、选择器调用行)——建议合并序 **INC-2b → INC-4 → INC-5**(或 2b 与 4 换序),每步独立集成门;选择器/规划器本体为独立新模块,冲突面最小化。

---

## 12. Performance / LLM-Call Implications

- **新增 LLM 调用:0**(INC-4 确定性规划;INC-5 确定性选择;INC-2b 判定若走离线工具亦不在请求路径)。
- 请求路径新增成本:slot 多路检索(每 required slot 一次 bucket/hybrid 调用,Weaviate 侧,~ms 级;建议 required slots ≤3 上限入契约);选择器纯内存;组合复核纯内存。
- 对比基线: INC-3 已把理解链 3 次调用合并为 1 次;I-002 三增量不回吐该收益,C6(strategy instability,28 例)预期因 LLM 离散权收缩而改善(§13)。
- TTFT 风险点:slot 多路检索串行叠加可能增加 retrieve ms——契约应要求 slot 检索并发化或复用单次多过滤,并纳入 OPERATIONAL(ttft_e2e)观测。

---

## 13. Benchmark Mapping(映射,不运行)

| Benchmark 面 | 基线证据 | I-002 归属增量 | 比较型 Benchmark 将证明什么 |
|---|---|---|---|
| EVIDENCE 组(权重 0.3,基线 1.4637=最弱组) | BASELINE_V1:39-44 | INC-4+INC-5 主目标 | evidence_coverage/citation_quality/faithfulness 三维提升 |
| **#28** 历史价格纪律(sq-045/026/080,cg-r05/005) | C2 stale 8 例;`numbers_supported` 仅验数字存在(citation.py:248-256,"$59 ⊂ $59.9") | INC-5(citation 组合升级)+ §5.4 时效裁决 | 价格类断言绑定现行/历史语境,family #28 2/3→3/3 |
| **#29** 电池计算器复现(cg-r06/cg-r10) | 2/2 PASS(守住) | INC-4(calculator_doc slot) | slot 化后保持 2/2 且抗查询变体 |
| **#31** 澄清不受罚(cg-r07/sq-101) | INC-3 已修交互路由(C3) | INC-4(不回吐:clarification 零检索短路保持) | 回归守绿 |
| insufficient-evidence(诚实空答 50 runs/20 cases;C1=21) | 零源 32.5%;背景段喂数据但不给编号 | INC-5(coverage+insufficient 推广) | 空答语义一致化、"可引用资料为空"与生成输入一致 |
| 产品隔离/比较(#5 家族 9 例 + COMPARE 类) | 比较配额已修 H1 | INC-4(slot 化推广)+INC-5(隔离继承) | 隔离谓词零回归 |
| C6 策略不稳定(28 例,最大簇) | rev2 PRIMARY=K9 未解 | INC-4+5(LLM 离散权→确定性规划/选择) | run 间策略一致率上升(最大单项预期收益) |
| C4 PII 溯源(3 例 HIGH) | rev2 PRIMARY=K6 组合信任边界 | INC-2b(组合复核) | 背景段敏感内容治理 |

**各增量伴随的 focused 回归测试(契约时冻结)**:
- INC-2b:sensitivity 过滤单元(三路)+ 组合复核 + 回填幂等 + 迁移零向量触碰 + internal 源全渠道不可见守恒;
- INC-4:规划表黄金测试(8 类映射)+ slot 检索 parity(answer/stream)+ 零新增 LLM 调用断言(llm_calls 计数)+ 比较路径零回归(T-COMPARISON 既有用例);
- INC-5:选择器黄金测试(tier 推广/冗余/覆盖)+ insufficient 话术契约 + citation 编号权威零回归(CIT 套件)+ 空答一致性。

---

## 14. Required Migrations / Backfills

| 增量 | 迁移 | 重嵌入? |
|---|---|---|
| INC-2b | 零 DDL(evidence_sensitivity 属性已在 schema);新增**判定结果回填脚本**(模板=既有 evidence 回填 `data.update` 模式,幂等/dry-run 默认/孤儿只报不写);可选 channel_visibility 源级标记调整 | **否**(标签路径);是(仅当选内容改写式脱敏,不推荐 v1) |
| INC-4 | 无(纯运行时);§5.4 时效扩展若裁决 → 第二个 metadata-only 回填(模板同上) | 否 |
| INC-5 | 无 | 否 |

---

## 15. Risks / Unknowns

1. **slot 检索延迟叠加**(§12)——契约需上限+并发要求;
2. **规划查表召回不足**(§5.4 电池/主题类)——升级路径=修订裁决加受限 LLM 规划,默认不加;
3. **sensitivity unknown ≠ 安全的治理空洞**(PD-2b-1 未拍板前,INC-2b 执行语义无法冻结);
4. **比较配额泛化的回归面**——tier 逻辑是 RCA H1 修复,推广时必须保持比较路径字节级行为(T-COMPARISON 用例守卫);
5. **双路径接线遗漏**——answer/stream 两处同位(rag.py 1465↔2128 等),历史已两次因单侧接线产生 parity 缺陷;INC-5 必须以独立模块+双调用行结构化解;
6. **trace 载荷膨胀**——coverage report/slot 明细入 trace 需有界(复用 INC-1 §8 有界元数据约定);
7. **docs/evaluation 为独立仓**——Benchmark 映射的最终核对以该仓冻结件为准,本报告引用其路径在主仓 docs 树下可见但哈希权威在 evaluation 仓。

---

## 16. Production Evidence Still Required

1. INC-2b 回填规模证据:source_type × sensitivity × channel_visibility 聚合计数;internal 源清单;filesystem 文档/chunk 聚合(§4.5,全部只读聚合);
2. §5.4 时效裁决前的佐证:woocommerce 源 chunk 量级(决定 currency 软偏好的收益面)——同为聚合只读;
3. **不需要**内容级审查授权即可冻结 INC-2b 契约骨架;`personal-data` 批量判定工具(若 PD-2b-2 选内容审查路线)另立授权与范围。

---

## 17. Recommended Increment Boundaries

| 增量 | 边界(建议契约范围) | 判定 |
|---|---|---|
| **INC-2b** | sensitivity 判定策略(PD-2b-1/2/3 拍板后)+ search.py 三路过滤参数 + build_citation_context 入口复核 + 回填脚本 + 生产聚合证据门 | **READY_FOR_CONTRACT**(附 3 个 PD + §16.1 证据门) |
| **INC-4** | EvidenceSlot/EvidencePlan 冻结 + derive_evidence_plan 纯函数 + 黄金测试 + slot→检索接线(双路径)+ trace stages.plan + ≤3 slot 上限/延迟预算;§5.4 时效扩展作为**可选条款**(需 INC-2a 词表修订裁决) | **READY_FOR_CONTRACT**(零新增 LLM 调用为契约硬条款) |
| **INC-5** | 独立选择器模块(slot 覆盖/权威代位/隔离继承/冗余/coverage report)+ insufficient 推广 + build_citation_context 字段权威切换 + 双路径接线;**先决条件=INC-4 契约冻结** | **READY_FOR_CONTRACT**(条件:INC-4 接口先行冻结) |

**建议执行序**:INC-2b 与 INC-4 并行(接口冻结会一次性给出);INC-5 随 INC-4 契约冻结后启动;合并序 2b → 4 → 5,每步独立集成门。

---

## 附:证据索引(关键 file:line)

- rag.py:423-427(INTENT_BOOST_FILTERS)/ 199-260(tier 配额)/ 748-844(检索融合+守卫+候选表)/ 846-864(fail-closed 守卫)/ 1312-1446(理解+路由短路)/ 1503-1576(检索→重排→剪枝)/ 1582-1673(不足语义)/ 1684(cite_ctx)/ 1932-1960(stream 同位)
- search.py:32-38(unknown 缺省)/ 218-224,263-267,358(三路过滤器)/ 395-430(evidence 读回)
- ingest.py:96-122,125-181(schema+_build_props)/ 269-399(摄取编排)
- citation.py:51-56(PUBLIC_SOURCE_TYPES)/ 102-180(组合)/ 248-256(numbers_supported)
- evidence_meta.py:104-177(冻结派生)/ 86-88,127-131(personal-data 预留+unknown 语义)
- task_understanding.py:41-51(模式枚举)/ 112-135(TaskUnderstanding)
- pruner.py:20-67(prune 接口)
- scripts/migrate_backfill_evidence_meta.py:191-213 / scripts/migrate_channel_visibility.py:172(data.update 先例)
- docs/evaluation/benchmark_v1/(冻结件;维度/案例/归档由独立仓哈希权威)
