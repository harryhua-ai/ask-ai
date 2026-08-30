# 意图 4 分类迁移 + 场景路由 设计文档

- **日期**:2026-08-04(Rev2,按双路评审修订:stream_answer parity / RRF 公式 / tagger 8→4 迁移)
- **状态**:待双路评审 → 通过后 orchestrator 实现
- **关联**:`2026-07-27-ask-ai-design.md` §5(意图分流)/ §10 Phase 1.5
- **目标 P0 项**:P0#1(修 e2e #6/#15/#20,提升 support/product 召回质量)

---

## 1. 背景与目标

### 1.1 触发原因

真实案例 e2e(20 问,从 support 案例文档提取客户原话)暴露 3 类问题:

| 案例 | 现象 | 根因 |
|---|---|---|
| **#6 NE101 蜂窝网络注册被拒** | AI 编造"恢复出厂清除 APN 配置",真实根因是 SIM/运营商不匹配(Verizon SIM 驻留 AT&T,CEREG=3) | support 案例文档未进入召回 top-8,LLM 从泛 NE101 文档编造 |
| **#15 ModularX 热成像入侵检测演示视频** | 误拒为 business_inquiry | 方案/能力咨询被旧分类器吞进 business |
| **#20 Evercam 建筑工地 demo 方案** | 误拒为 business_inquiry | 选型/方案咨询被旧分类器吞进 business |

### 1.2 决定性事实(Weaviate 实测,2026-08-04)

```
source_type 分布:  local_git  579,688 (98%+)   filesystem  481
chunk_type 分布:   code  568,494 (98%)   paragraph 7,321  heading 2,235  list 1,299  table 820
product 分布:      ne301 475,731  ne101 83,746  neomind 15,489  wiki 3,931  knowledge 481  ...
```

- **代码 chunk 占 98%**,文档 chunk(paragraph+heading+list+table)约 11,675 条
- `filesystem` 481 含 `support/`(技术案例)+ `wiki-en/`(widget 可见)+ `sales/硬件/经验`(api-only,widget 不可见);widget 渠道实际可见的 filesystem chunk < 481(具体数待 `channel_visibility` 实测,实现时核定)
- `HybridSearcher.search()` 仅支持 `product_filter` + `channel` 过滤,**无 source_type / chunk_type 路由能力**
- 旧 3 类意图 `business_inquiry` 一刀切拒答 → 吞掉方案/选型/能力咨询

> **注**:support boost 桶(`source_type=filesystem`)在 widget 渠道会召回 `support/` + `wiki-en/` 混合(均 widget 可见);`sales/硬件/经验` 因 channel_visibility 不含 widget 被自动排除。

### 1.3 目标

1. **意图分类迁移**:3 类 → 4 类(`commercial / product / support / off_topic`),对齐设计文档 §5
2. **场景路由**:按意图引导召回到不同知识子集(软路由,不硬过滤),修 #6(support 案例浮出)
3. **分类器修正**:`business_inquiry` 拆分,方案/选型 → `product`(答),纯价格/采购 → `commercial`(暂拒),修 #15/#20
4. **分风格 prompt**:按意图叠加回答风格(§5)
5. **stream_answer parity**(评审发现):stream_answer 当前缺符号检索+RRF(仅 answer() 有),生产路径从未跑符号检索 → 抽共享 helper 一并补齐

### 1.4 非目标(本次不做)

- WooCommerce commercial 数据接入(P1#5,commercial 暂无数据,继续拒答)
- hard filter 召回(会丢 wiki/代码,伤害 #5/#9 等产品咨询)
- 答案缓存、多渠道适配器(独立 P2)
- 8 类细粒度 analytics 标签(若后续 Coverage Gaps 需要更细粒度,另加独立字段,不混入 intent_tag)

---

## 2. 现状分析

### 2.1 意图分类(`backend/pipeline/intent.py`)

```python
VALID_CATEGORIES = ("product_question", "business_inquiry", "off_topic")
```

- `product_question` → 进管线,`effective_min=1`(低阈值作答)
- `business_inquiry` → **检索前拒答**(REJECT_BUSINESS)
- `off_topic` → 检索前拒答(REJECT_OFF_TOPIC)
- fail-open → `product_question`

**问题**:无 `support` 类(故障排查/代码/调试与产品咨询混在 product_question);`business_inquiry` 过宽(吞方案/选型)。

### 2.2 RAG 编排(`backend/pipeline/rag.py`)— ⚠️ 评审发现 parity 缺口

**两条路径检索逻辑不一致**:

- `answer()`(rag.py:289-370):有意图识别 + `extract_query` + `rewrite_query` + `search` + `search_symbols` + `rrf_fuse` + rerank(**完整,含符号检索**)
- `stream_answer()`(rag.py:372-535,检索段 456-485):有意图识别 + `extract_query` + `rewrite_query` + `search` + rerank(**❌ 无 search_symbols / 无 rrf_fuse**)

**生产端点 `routes.py:104` 用 `stream_answer()`** → **符号检索代码(9 commit)从未在生产路径生效**。e2e #6/#15/#20 均跑在无符号检索的 stream_answer 上。

本次必须抽共享检索 helper,让两条路径走同一套(符号 + boost 桶 + RRF),消除 parity 缺口。

### 2.3 检索(`backend/retrieval/search.py`)

- `search(query, alpha, limit, product_filter, channel)`:hybrid,Filter 仅 product + channel_visibility
- `search_symbols(query, limit, product_filter, channel)`:BM25 on `symbol_tokens`,绕过 rewrite
- **无** source_type / chunk_type 过滤入口

### 2.4 RRF 融合(`backend/retrieval/rrf.py`)

- `rrf_fuse(hybrid, symbol, k=60)`:固定 **2 个位置参数**,按 `source_id + chunk_index` 去重
- 公式:`score += 1.0 / (k + rank + 1)`,rank 从 0 起(rrf.py:38,43)

### 2.5 system_prompt(`config/system_prompt.yaml` + `main.py:252-296`)

- 单套 base prompt,从 Customization 表按 **channel**(非 intent)绑定
- `_build_messages(query, context, language, history, channel)`:按 channel 选 prompt

### 2.6 intent 落库(`backend/api/routes.py:144` + `backend/services/intent_tagger.py`)— ⚠️ 两套独立 taxonomy

- `routes.py:144-153` 写 Conversation 时**不带 intent_tag**
- `intent_tagger.py` 有**独立的 8 类 taxonomy**(与 intent.py 的 3 类完全不同):
  ```
  product_spec / tech_support / getting_started / pricing /
  comparison / api_reference / documentation / other
  ```
  异步批量回填 `intent_tag IS NULL` 的历史行(intent_tagger.py:84)
- admin Conversations 页按 intent_tag 过滤(`backend/api/admin/conversations.py:49`)

**迁移影响**:本次改 intent.py 为 4 类;intent_tagger.py 需同步改 4 类(8→4 迁移);DB 历史 8 类标签需一次性映射到 4 类,否则 intent_tag 字段混杂两套标签。

---

## 3. 方案设计

### 3.1 意图 4 分类迁移

#### 3.1.1 新分类

| 标识符 | 中文 | 覆盖 | 处置 |
|---|---|---|---|
| `commercial` | 商务咨询 | 价格/采购/渠道/库存/促销/合作 | **暂拒答**(无 mall 数据;P1#5 接入后改为从 WooCommerce 作答) |
| `product` | 产品方案咨询 | 功能/参数/规格/选型/方案/竞品/适配/演示能力 | 答(effective_min=1,docs boost) |
| `support` | 技术支持 | 故障排查/集成/二次开发/代码/调试(L1–L3) | 答(effective_min=1,filesystem boost) |
| `off_topic` | 无关 | 闲聊/天气/非产品域/纯竞品 | 检索前拒答 |

```python
VALID_CATEGORIES = ("commercial", "product", "support", "off_topic")
# fail-open → "product"(最常见、最安全)
```

#### 3.1.2 分类器 prompt(关键:few-shot 区分 business 拆分)

分类器核心难点是 **commercial vs product(方案/选型)** 的边界。few-shot 明确:

- "NE301 价格多少 / 怎么采购 / 报价" → `commercial`
- "NE301 支持热成像入侵检测吗 / 有演示视频吗 / 太阳能场景怎么选型" → `product`(能力/方案/选型,**非** commercial)
- "NE101 蜂窝网络注册失败 / 怎么集成 SDK / 这个报错什么意思" → `support`
- "今天天气 / Python 语法 / 竞品 XX 怎么样" → `off_topic`

完整 prompt 见 §6.1(实现时落 `intent.py`)。温度 0.0,max_tokens 128,JSON 输出 `{"category","reason"}`(契约不变)。

#### 3.1.3 commercial 过渡期处置

无 WooCommerce 数据前,`commercial` → 检索前 REJECT_BUSINESS(保留现有话术)。

**P1#5 启用 commercial 作答需要的代码改动(非"仅改配置")**:
1. 删除 / 改造 `if intent.category == "commercial": → REJECT_BUSINESS` 分支(rag.py answer + stream_answer 两处)
2. `effective_min` 条件加入 `"commercial"`(`1 if intent.category in ("product","support","commercial") else ...`)
3. INTENT_BOOST_FILTERS 加 `"commercial": {"source_types": ["woocommerce"]}`(§3.2.3)
4. (可选)移除 REJECT_BUSINESS 常量

本 spec 预留钩子(§3.2.3 commercial 行注释),但上述 ~3 处代码改动属 P1#5 范畴。

### 3.2 Per-intent 召回路由(boost bucket + RRF)

#### 3.2.1 核心思路:软路由

**不硬过滤**(硬过滤 source_type 会丢 wiki/代码,伤害 #5/#9 产品咨询)。改为**追加一路 boost 桶召回**,与主 hybrid + symbol 三路单次 RRF 融合,intent 相关 source 获得"第二次浮出机会"。

#### 3.2.2 新检索方法 `search_bucket`

`HybridSearcher` 新增(结构与 `search_symbols` 相似,BM25,复用 `_to_search_result`;channel 默认对齐 `search()`):

```python
def search_bucket(
    self,
    query: str,                              # 用 extract_query 输出(绕 rewrite,保关键词)
    source_types: list[str] | None = None,   # 如 ["filesystem"](support 案例)
    chunk_types: list[str] | None = None,    # 如 ["paragraph","heading","list","table"](docs)
    limit: int = 30,
    product_filter: str | None = None,
    channel: str | None = None,              # 与 search() 一致,None 不过滤
) -> list[SearchResult]:
    """BM25 召回(对 text 字段),按 source_type / chunk_type 过滤。
    与主 hybrid 融合后,让 intent 相关 source 获得 RRF 加权。"""
```

- BM25 on `text`(无 embed,低成本,与 search_symbols 一致)
- Filter 组合:`source_type` / `chunk_type` 是 **TEXT 标量属性**(非数组,见 ingest.py:171,181),用 `equal` 而非 `contains_any`(后者对多 token 值如 `local_git` 会因分词静默失效)。多值时构造 `Filter.by_property("source_type").equal(v)` 列表,用 `Filter.any_of([...])` 合并(OR 语义);单值直接 `equal`。`channel_visibility` 是 TEXT_ARRAY,仍用 `contains_any`。`product` 用 `equal`(与 search.py:160 一致)
- 空 query / `source_types` 和 `chunk_types` 都为 None → 返回 `[]`(无过滤条件的桶无意义)
- `channel` 默认 `None`(与 `search()` 一致;调用方按需传 channel)

#### 3.2.3 意图 → boost 桶路由表

| 意图 | boost 桶过滤 | 用途 |
|---|---|---|
| `support` | `source_types=["filesystem"]` | 故障/排查案例 + wiki-en 浮出(修 #6;widget 渠道自动排除 sales/硬件/经验) |
| `product` | `chunk_types=["paragraph","heading","list","table"]` | 产品文档优先(去 code 噪声) |
| `commercial` | 暂无桶;过渡期**检索前 REJECT_BUSINESS**(P1#5 后启用 `source_types=["woocommerce"]`) | — |
| `off_topic` | 不检索 | 检索前拒答 |

路由表落地为模块级常量(可配置):

```python
INTENT_BOOST_FILTERS: dict[str, dict] = {
    "support": {"source_types": ["filesystem"]},
    "product": {"chunk_types": ["paragraph", "heading", "list", "table"]},
    # "commercial": {"source_types": ["woocommerce"]},  # P1#5 启用
}
```

> **注**:`product` 桶 `chunk_types` 过滤会排除 `chunk_type=""` 的未标注 chunk(SearchResult 默认空串)。影响有限——boost 仅做 RRF 加权,主 hybrid 仍召回全部;未标注产品文档 chunk 少且仍走主路。P0#2 后观察是否需补。
> **注**:`support` 桶本质**跨产品**(support 案例存为 `product="knowledge"`,非 `ne101` 等)。helper 内 bucket 路不透传 `product_filter`(见 §6.4),否则 `product_filter="ne101"` + `source_type=filesystem` 会返回空。

#### 3.2.4 RRF 扩展为变长(单次 N 路)

`rrf_fuse` 扩展为接受任意多个列表(`*result_lists`),**公式不变**:`score = Σ 1/(k + rank + 1)`(rank 从 0 起,与现有 rrf.py:38 完全一致),按 `source_id + chunk_index` 去重。空列表跳过。全空 → `[]`。

```python
def rrf_fuse(*result_lists: list[SearchResult], k: int = 60) -> list[SearchResult]:
    """N 路 RRF 融合(变长参数)。空列表自动跳过。全空 → []。
    公式 1/(k+rank+1) 与原 2 参版本逐位一致(向后兼容语义,非仅语法)。"""
```

调用点(rag.py,**单次三路**):`fused = rrf_fuse(results, symbol_results, bucket_results, k=60)`(空列表由 variadic 内部跳过,三路退化为二路或单路均安全)。

#### 3.2.5 boost 桶用 extract_query(绕 rewrite)

与 search_symbols 一致,boost 桶用 `extract_query` 输出(未 rewrite),保关键词(蜂窝/SIM/CEREG)。这同时**缓解 #6 的 rewrite 漂移**(rewrite 强调 reset,extract 保留 蜂窝网络)。P0#4(rewrite 漂移)由此部分缓解,剩余改写 prompt 微调见 P0#4 独立任务。

### 3.3 Per-intent system_prompt 风格(§5 分风格)

#### 3.3.1 配置驱动(落 yaml,非模块常量)

`config/system_prompt.yaml` 新增 `intent_styles` 段:

```yaml
intent_styles:
  commercial: |
    ## 回答风格(商务)
    聚焦价格/采购/渠道/库存;引导联系销售;不展开技术细节。
  product: |
    ## 回答风格(产品方案)
    选型/比对给推荐+理由;方案类给组合建议;参数规格精确引用。
  support: |
    ## 回答风格(技术支持)
    保留代码/寄存器/接口/错误码细节;故障排查给分步;定位链路完整。
  # off_topic 不生成
```

`main.py` 加载 `intent_styles` dict,传给 `RAGOrchestrator.__init__(intent_styles=...)`。模块内无常量(纯配置驱动,便于运营调风格不改代码)。

#### 3.3.2 `_build_messages` 改造

`RAGOrchestrator.__init__` 新增参数 `intent_styles: dict[str, str] | None = None`(`self._intent_styles = intent_styles or {}`)。`_build_messages` 签名加 `intent: str`:

```python
def _build_messages(self, query, context, language, history, channel="widget", intent="product"):
    base = self._channel_customizations.get(channel, self._system_prompt)
    style = self._intent_styles.get(intent, "")
    system_prompt = f"{base}\n\n{style}" if style else base
    ...
```

channel 选 base prompt(保持 Phase 2B 不变量),intent 风格叠加在其后,正交解耦。

### 3.4 effective_min + 拒答策略

| 意图 | effective_min | 拒答 |
|---|---|---|
| `product` / `support` | 1(低阈值,积极作答) | 结果不足 → REJECT_ANSWER |
| `commercial` | — | 检索前 REJECT_BUSINESS(过渡期) |
| `off_topic` | — | 检索前 REJECT_OFF_TOPIC |

### 3.5 intent 落库 + tagger 8→4 迁移

**实时落库(answer 路径)**:`RAGAnswer` 新增 `intent: str` 字段;answer() 返回时填入。

**实时落库(stream_answer 路径,生产端点)**:stream_answer 产 JSON 事件非 RAGAnswer,需补 intent 透传链路:
1. `stream_answer` 的 `complete` 事件 JSON 加 `"intent": intent.category`(rag.py:519-535,所有 complete 事件分支含拒答)
2. `routes.py` 解析 complete 事件处加 `intent = data.get("intent")`(routes.py:123-127 区域)
3. `Conversation(..., intent_tag=intent)` 写入(routes.py:144)

按现 spec 实现后,**生产路径(stream_answer)intent_tag 实时落库 4 类**,消除双重分类。

**intent_tagger.py 改 4 类**:重写 `INTENT_CATEGORIES` 与 prompt,对齐 intent.py 的 4 类(commercial/product/support/off_topic)。tagger 仅回填 `intent_tag IS NULL` 的历史行(仍只处理 NULL,不触碰非 NULL)。

**历史 8 类标签迁移(一次性脚本)** `scripts/migrate_intent_tag_8to4.py`:

| 旧 8 类 | 新 4 类 |
|---|---|
| product_spec / getting_started / comparison / documentation | product |
| tech_support / api_reference | support |
| pricing | commercial |
| other | off_topic |

脚本 `UPDATE conversations SET intent_tag=<映射> WHERE intent_tag IN (旧 8 类)`,幂等(已映射的行不再命中)。迁移后 intent_tag 字段全为 4 类,admin 过滤面板(`conversations.py:49`)统一显示 4 标签。

---

## 4. 数据流(改造后,answer 与 stream_answer 共用)

```
[访客提问]
  │
  ├─ classify_intent(4 类) ── off_topic → REJECT_OFF_TOPIC
  │                          ── commercial → REJECT_BUSINESS(过渡期)
  │                          ── product/support → 继续
  │
  ├─ extract_query ──→ extracted
  │                      │
  │                      ├─→ search_bucket(boost 桶,按 intent 路由,BM25,用 extracted)
  │                      └─→ search_symbols(BM25 符号,用 extracted)
  │
  ├─ rewrite_query(extracted) ──→ search_query
  │                                  │
  │                                  └─→ searcher.search(主 hybrid,全量,用 search_query)
  │
  ├─ rrf_fuse(hybrid, symbol, bucket)   ← 单次三路融合(变长,空路自动跳过)
  │
  ├─ rerank(chunk_type 加权,已有)
  ├─ (可选 pruner)
  ├─ effective_min(=1 for product/support)检查 → 不足 REJECT_ANSWER
  │
  ├─ _build_messages(intent → 风格叠加)
  └─ LLM 生成 → RAGAnswer(intent 落库)
```

> extract_query 先于 rewrite_query(extracted 喂 rewrite);search_symbols 与 search_bucket 用 extracted,search 用 rewrite 后的 search_query。
> **intent 落库**:answer() 填 `RAGAnswer.intent`;stream_answer() 的 complete 事件带 `"intent"`,routes.py 提取后写 `Conversation.intent_tag`(见 §3.5)。

---

## 5. 影响范围(文件)

| 文件 | 改动 | 风险 |
|---|---|---|
| `backend/pipeline/intent.py` | 4 类 + 新 prompt(few-shot)+ VALID_CATEGORIES + fail-open→product | 中(prompt 质量决定 #15/#20) |
| `backend/retrieval/search.py` | 新增 `search_bucket` 方法 | 低(新增,不改现有 search) |
| `backend/retrieval/rrf.py` | `rrf_fuse` 扩展变长 `*result_lists: list[SearchResult]` | 低(公式不变,2 参调用仍兼容) |
| `backend/pipeline/rag.py` | **抽 `_retrieve_and_fuse()` 共享 helper**(修 stream_answer parity + 加 boost 桶)+ 意图路由 + 风格叠加 + RAGAnswer.intent + stream complete 事件加 intent + 拒答逻辑 | **高**(核心编排,parity 修复是关键) |
| `config/system_prompt.yaml` | 新增 `intent_styles` 段 | 低 |
| `backend/main.py` | 加载 intent_styles + 传 RAGOrchestrator(`intent_styles=...`) | 低 |
| `backend/api/routes.py` | complete 事件提取 intent + Conversation 写入 intent_tag(stream 路径) | 低(加 2 行:解析 + 透传) |
| `backend/services/intent_tagger.py` | INTENT_CATEGORIES + prompt 改 4 类(8→4) | 中(taxonomy 迁移,影响 admin 标签集) |
| `scripts/migrate_intent_tag_8to4.py` | 新增:历史 8 类 → 4 类一次性迁移 | 低(幂等 UPDATE) |
| `admin/src/pages/Conversations.tsx` | intent 过滤选项改 4 类标签 | 低 |
| 测试 | intent/search_bucket/rrf/rag 单测 + **stream_answer/answer parity 回归** + e2e #6/#10/#14/#15/#20 回归 | — |

---

## 6. 详细实现约定

### 6.1 intent.py 新 prompt(骨架)

```python
VALID_CATEGORIES = ("commercial", "product", "support", "off_topic")

_INTENT_PROMPT = """你是 CamThink 意图分类助手。判断用户输入属于以下哪类:

- commercial: 纯价格/采购/报价/渠道/库存/促销/商务合作(不涉及技术方案)
- product: CamThink 产品功能/参数/规格/选型/方案/竞品对比/适配/演示能力咨询
  (含"能否做 XX""XX 场景怎么选""有没有 XX 能力/视频"等方案选型问题)
- support: 故障排查/报错/集成/二次开发/代码/调试/寄存器/固件(L1–L3,含开发者)
- off_topic: 与 CamThink 产品无关的闲聊/天气/通用知识/纯竞品咨询

## 示例
- "NE301 多少钱 / 怎么采购" → commercial
- "NE301 支持热成像入侵检测吗 / 有演示视频吗" → product
- "建筑工地太阳能场景怎么选型" → product
- "NE101 蜂窝网络注册失败 / CEREG 报错" → support
- "Python 怎么读串口(与 CamThink 无关)" → off_topic

只输出 JSON: {{"category": "类别名", "reason": "简短理由"}}

## 用户输入
{query}
"""
```

fail-open 异常分支返回 `IntentResult(category="product", reason="classification failed")`。

### 6.2 search_bucket 实现约定

- 与 `search_symbols` 结构对称:`if not query.strip(): return []` → 组合 Filter → `collection.query.bm25(query=query, query_properties=["text"], ...)` → `_to_search_result`
- `query_properties=["text"]`(BM25 限定 text 字段;不加 boost 符号,让 RRF 自然加权)
- Filter 组合逻辑复用 search_symbols 的 `filters_list` 模式,新增 source_type / chunk_type 的 `Filter.by_property("source_type").contains_any(...)` / `Filter.by_property("chunk_type").contains_any(...)`
- **source_types 和 chunk_types 都为 None 时返回 `[]`**(无过滤的桶等价于主路,无意义)
- `channel: str | None = None`(与 search() 一致;调用方按需传 channel,组合 `channel_visibility contains_any`)

### 6.3 rrf_fuse 变长签名

```python
def rrf_fuse(*result_lists: list[SearchResult], k: int = 60) -> list[SearchResult]:
    """N 路 RRF 融合(变长)。公式 1/(k+rank+1),rank 从 0(与原 2 参逐位一致)。"""
    scores: dict[tuple[str, int], float] = defaultdict(float)
    rep: dict[tuple[str, int], SearchResult] = {}
    for lst in result_lists:
        for rank, r in enumerate(lst):
            key = (r.source_id, r.chunk_index)
            scores[key] += 1.0 / (k + rank + 1)   # ← 与 rrf.py:38 完全一致
            if key not in rep:
                rep[key] = r
    if not scores:
        return []
    ordered = sorted(scores, key=lambda kk: -scores[kk])
    return [dataclasses.replace(rep[kk], score=scores[kk]) for kk in ordered]
```

向后兼容:现有 `rrf_fuse(a, b, k=60)` 仍工作(positional 进 `*result_lists`),且分数逐位不变(语义兼容)。

### 6.4 rag.py:抽 `_retrieve_and_fuse()` 共享 helper(关键:修 parity)

**问题**:answer() 有符号检索,stream_answer() 没有 → 生产路径缺符号检索。

**方案**:抽共享异步方法,answer/stream_answer 都调它,保证 parity:

```python
async def _retrieve_and_fuse(
    self,
    extracted: str,            # extract_query 输出(符号 + boost 桶用)
    search_query: str,         # rewrite_query 输出(主 hybrid 用)
    intent_category: str,
    *,
    product_filter: str | None,
    channel: str,
) -> list[SearchResult]:
    """统一检索 + 三路 RRF 融合(answer / stream_answer 共用,保证 parity)。

    主 hybrid(search_query) + 符号 BM25(extracted) + intent boost 桶(extracted)
    → 单次 rrf_fuse 三路融合。任一路异常 / 为空均降级,不中断主流程。
    """
    results = self._searcher.search(
        query=search_query, alpha=self._alpha, limit=self._recall_limit,
        product_filter=product_filter, channel=channel,
    )
    symbol_results: list[SearchResult] = []
    try:
        symbol_results = self._searcher.search_symbols(
            query=extracted, limit=self._recall_limit,
            product_filter=product_filter, channel=channel,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("符号召回失败,降级:%s", str(exc)[:200])

    bucket_results: list[SearchResult] = []
    bucket_cfg = INTENT_BOOST_FILTERS.get(intent_category)
    if bucket_cfg:
        try:
            # boost 桶跨产品(support 案例存为 product="knowledge"),不透传 product_filter
            bucket_results = self._searcher.search_bucket(
                query=extracted, limit=self._recall_limit,
                channel=channel, **bucket_cfg,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("boost 桶召回失败,降级:%s", str(exc)[:200])

    # 单次三路 RRF(空路由 variadic 自动跳过)
    from backend.retrieval.rrf import rrf_fuse
    try:
        return rrf_fuse(results, symbol_results, bucket_results, k=60)
    except Exception as exc:  # noqa: BLE001
        logger.warning("RRF 融合失败,降级 hybrid 单路:%s", str(exc)[:200])
        return results
```

answer() 与 stream_answer() 改为:

```python
intent = await classify_intent(query, self._llm)
if intent.category == "off_topic": ...REJECT_OFF_TOPIC
if intent.category == "commercial": ...REJECT_BUSINESS  # 过渡期
effective_min = 1 if intent.category in ("product", "support") else self._min_results

extracted = await extract_query(query, self._llm)
search_query = await rewrite_query(extracted, conversation_history, self._llm)

fused = await self._retrieve_and_fuse(
    extracted, search_query, intent.category,
    product_filter=product_filter, channel=channel,
)

reranked = self._reranker.rerank(search_query, fused, top_k=self._top_k)
...
messages = self._build_messages(query, context, language, conversation_history, channel, intent=intent.category)
```

`RAGAnswer` 加 `intent: str` 字段;拒答分支也填 intent(便于统计)。

### 6.5 intent_tagger.py 4 类改造

```python
INTENT_CATEGORIES = ["commercial", "product", "support", "off_topic"]
# prompt 改为输出 4 类之一;tag_single 的 task 仍用 "query_decomposition"
# tag_batch 逻辑不变(仅回填 intent_tag IS NULL 的行)
```

### 6.6 历史迁移脚本 `scripts/migrate_intent_tag_8to4.py`

```python
MAPPING = {
    "product_spec": "product", "getting_started": "product",
    "comparison": "product", "documentation": "product",
    "tech_support": "support", "api_reference": "support",
    "pricing": "commercial", "other": "off_topic",
}
# UPDATE conversations SET intent_tag = :new WHERE intent_tag = :old(逐对执行,幂等)
```

---

## 7. 测试策略

### 7.1 单元测试

- `tests/pipeline/test_intent.py`:4 类各 1 正例 + commercial/product 边界(#15/#20 原话作为 product 正例);fail-open → product
- `tests/retrieval/test_search.py::test_search_bucket`:source_type / chunk_type 过滤生效;双 None → [];空 query → []
- `tests/retrieval/test_rrf.py::test_rrf_fuse_variadic`:3 列表融合;空列表跳过;全空 → [];**2 参向后兼容 + 分数与原实现逐位一致**(对同一输入,`rrf_fuse(a,b)` == 改造前后同结果)
- `tests/pipeline/test_rag.py`:
  - `_retrieve_and_fuse` 三路融合(search + symbol + bucket 都被调)
  - **stream_answer 与 answer 检索 parity**:同一输入两入口 fuse 结果一致(防再次漂移)
  - support 意图 → search_bucket(filesystem)被调
  - commercial → 检索前拒答,不调 searcher
  - off_topic → 检索前拒答
  - product → chunk_type 文档类型桶(paragraph/heading/list/table)被调
  - RAGAnswer.intent 字段正确;system_prompt 含 intent 风格段
  - **stream complete 事件含 `"intent"` 字段**(routes.py 提取并写入 intent_tag)

### 7.2 e2e 回归(scripts/e2e_real.py)

实现后重跑 20 问,重点核验:
- **#6**:AI 答案根因应含 SIM/运营商/CEREG(非"reset 清除 APN");support 案例文档出现在 sources
- **#15/#20**:不再误拒,作为 product 给出能力/方案回答(或基于现有资料的合理拒答,**而非** REJECT_BUSINESS)
- **#10/#14**:零回归(答案质量不降;#10 答案原本基本正确,#14 原本拒答)
- **#1–#9/#11–#13/#16–#19**:零回归(答案质量不降)

### 7.3 手工核验

- Weaviate 实测:对 #6 原话,`search_bucket(query, source_types=["filesystem"], channel="widget")` 是否召回 `2026-04/NE101-蜂窝网络注册被拒.md` 对应 chunk

---

## 8. 风险与回滚

| 风险 | 缓解 |
|---|---|
| 分类器 commercial/product 边界仍误判 | few-shot 强化;fail-open → product(宁可答不可误拒) |
| boost 桶引入噪声(BM25 关键词漂移) | RRF 自然加权(不替换主路);rerank 兜底;product 用 docs 桶较保守 |
| rrf_fuse 变长改造破坏现有符号检索 | 向后兼容 2 参 + 公式不变;单测验证分数逐位一致 |
| **stream_answer parity 重构引入回归** | 抽共享 helper 后两入口走同一代码;parity 回归测试;先跑 answer 单测再验证 stream |
| intent_tagger 8→4 taxonomy 迁移 | 一次性幂等迁移脚本;tagger 仅回填 NULL;迁移后 admin 标签集统一 |
| 商务问题过渡期仍拒答(用户体验) | 设计如此(commercial 数据未就绪);P1#5 解锁 |
| symbol 数据未回填时三路融合 | variadic rrf_fuse 对空列表自动跳过,退化为二路/单路,安全(依赖 P0#2 回填) |

**回滚**:改动文件见 §5(8 个 .py + 1 yaml + 1 .tsx + 1 迁移脚本),git revert 单 commit 即可;Weaviate schema 不变(无新 Property);DB intent_tag 4 类值向后兼容旧 8 类(迁移脚本可逆)。

---

## 9. 验收标准

- [ ] `VALID_CATEGORIES = ("commercial","product","support","off_topic")`,fail-open → product
- [ ] #15/#20 原话分类为 `product`(非 commercial)
- [ ] `support` 意图触发 `search_bucket(source_types=["filesystem"])`,结果经 RRF 融合
- [ ] `product` 意图触发 `search_bucket(chunk_types=["paragraph","heading","list","table"])`
- [ ] `commercial`/`off_topic` 检索前拒答,不调 searcher
- [ ] `rrf_fuse` 支持 ≥2 列表,2 参向后兼容,分数与原实现逐位一致
- [ ] **stream_answer 与 answer 走同一 `_retrieve_and_fuse`,parity 测试通过**(符号检索首次在生产路径生效)
- [ ] system_prompt 按 intent 叠加风格段(yaml `intent_styles` 驱动)
- [ ] `RAGAnswer.intent` 落库(answer 路径)+ stream complete 事件带 intent → routes.py 提取 → conversations.intent_tag(stream 路径)
- [ ] intent_tagger 改 4 类;历史 8 类标签迁移脚本执行后 intent_tag 全为 4 类
- [ ] e2e #6 根因正确(SIM/运营商)+ #15/#20 不误拒 + #10/#14 + 其余零回归
- [ ] 单测全绿,coverage ≥ 80%(改动文件)

---

## 10. 后续衔接

- **P0#2(符号数据回填)**:依赖——symbol_* 字段回填后,`_retrieve_and_fuse` 的符号路才真正有数据(否则退化为 hybrid+bucket 两路)。回填与本 spec 代码改动独立,可并行
- **P0#4(rewrite 漂移)**:boost 桶用 extract_query 已部分缓解;剩余 rewrite prompt 微调(保关键词)独立做
- **P1#5(WooCommerce)**:commercial 启用作答需 ~3 处代码改动(§3.1.3)+ 路由表加 woocommerce source_type
- **P1#6(camthink-site)**:product 桶可扩展加 website source_type

---

<!-- 以上为文档正文,以下为双路审核修复记录 -->

---

## 🔍 Dual Review Log

### Round 1 — 2026-08-04

| # | 级别 | 来源 | 位置 | 问题 | 修复动作 |
|---|------|------|------|------|---------|
| 1 | CRITICAL | 内容 | §2.2/§6.4 | stream_answer 缺符号检索+RRF,生产路径从未跑符号检索 | §2.2 标注 parity 缺口;§6.4 抽 `_retrieve_and_fuse` 共享 helper;§5 rag.py 风险上调高;§7 加 parity 测试;§1.3 增目标 5 |
| 2 | HIGH | 内容+结构 | §3.2.4/§4/§6.4 | 串行两步 RRF ≠ 单次三路 RRF(数学不等价) | 统一为单次三路 `rrf_fuse(results, symbol, bucket)`;§4 数据流图改单次三路;§6.4 helper 单次调用 |
| 3 | HIGH | 内容 | §6.3 | RRF 公式 `1/(k+rank)` 与现有 `1/(k+rank+1)` 不一致 | §6.3 改 `1.0/(k+rank+1)`;§3.2.4 公式标注 rank 从 0 |
| 4 | MEDIUM | 内容 | §2.6/§3.5/§5 | intent_tagger 有独立 8 类 taxonomy(非"调 classify") | §2.6 列 8 类;§3.5 tagger 改 4 类;§5 风险上调中;§6.5 改造约定 |
| 5 | MEDIUM | 内容 | §3.5/§8 | 历史 8 类标签残留导致 intent_tag 混杂 | §3.5 增 8→4 迁移脚本;§6.6 脚本骨架;§5 加文件 |
| 6 | MEDIUM | 内容 | §3.1.3/§10 | "P1#5 仅改配置"不成立 | §3.1.3 列 ~3 处代码改动;§10 同步 |
| 7 | MEDIUM | 内容 | §1.2/§3.2.3 | filesystem 481 ≠ support 案例(含 wiki-en/api-only) | §1.2 拆解组成;§3.2.3 注 support 桶返 support+wiki-en 混合 |
| 8 | MEDIUM | 结构 | §3.3.1/§3.3.2 | INTENT_STYLES 模块常量 vs self._intent_styles 冲突 | §3.3.1 改纯配置驱动(yaml);§3.3.2 加 __init__ intent_styles 参数;§5 main.py 补注 |
| 9 | MEDIUM | 结构 | §4 数据流图 | search_symbols 挂错分支;extract/rewrite 画成并行 | §4 search_symbols 移到 extract 分支;标注 extract→rewrite 顺序 |
| 10 | LOW | 结构 | §9 | `chunk_types=[docs]` 简写非字面值 | §9 改字面 `["paragraph","heading","list","table"]` |
| 11 | LOW | 结构 | §3.2.3 | commercial"走主路"措辞矛盾 | 改"检索前 REJECT_BUSINESS" |
| 12 | LOW | 内容+结构 | §3.2.4/§6.3 | rrf_fuse 签名注解不一致 | 统一 `*result_lists: list[SearchResult]` |
| 13 | LOW | 结构 | §3.2.2/§6.2 | contains any / contains_any 格式不一 | 统一 `contains_any` |
| 14 | LOW | 结构 | §7.2 | 零回归跳 #10/#14 未说明 | §7.2 补 #10/#14 |
| 15 | LOW | 内容 | §7 | 缺 stream/answer parity 测试 | §7.1 增 parity 回归 |
| 16 | LOW | 内容 | §3.2.2 | search_bucket channel 默认与 search() 不一致 | 改 `channel: str | None = None` |

**本轮修复**:16 个 | **累计修复**:16 个

---

### Round 2 — 2026-08-04

| # | 级别 | 来源 | 位置 | 问题 | 修复动作 |
|---|------|------|------|------|---------|
| R2-1 | MEDIUM | 内容 | §3.5/§6.4/§5/§4 | stream_answer intent 落库链路未定义(生产用 stream,complete 事件无 intent → intent_tag 恒 NULL) | §3.5 拆 answer/stream 两路径,stream 补 complete 事件加 intent + routes.py 提取 + Conversation 写入;§5 routes.py 详述;§4 注;§6.4 注;§9 验收分两条;§7.1 补测试 |
| R2-2 | LOW | 内容 | §3.2.2/§6.2 | contains_any 用于 TEXT 标量属性(source_type/chunk_type),多 token 值会静默失效 | 改 `equal` + `Filter.any_of` 合并(与 product 模式对齐);channel_visibility 仍 contains_any |
| R2-3 | LOW | 内容 | §6.4 | helper 未将 rrf_fuse 包 try/except,抛错中断主管线 | 包入 try/except,失败 return results(hybrid 单路降级,与现 answer() 语义对齐) |
| R2-4 | LOW | 内容 | §3.2.2 | "与 search_symbols 同构"在 channel 默认值修复后不严谨 | 改"结构与 search_symbols 相似(channel 默认对齐 search())" |
| R2-5 | LOW | 内容 | §2.2 | stream_answer 行号 421-485 不精确(漏 streaming 段) | 改"rag.py:372-535(检索段 456-485)" |
| R2-6 | LOW | 内容 | §6.4/§3.2.3 | bucket 路透传 product_filter,support 桶(product=knowledge)遇 ne101 filter 返回空 | helper 内 bucket 路不透传 product_filter;§3.2.3 注跨产品 |
| R2-7 | LOW | 内容 | §6.4/§5 | stream_answer 计时可观测性(helper 打包后 search_ms 不再隔离) | 留作实现时处理(helper 内分段子计时),不阻塞 spec |
| R2-8 | LOW | 内容 | §3.2.3 | product 桶 chunk_types 排除 chunk_type="" 未标注 chunk | §3.2.3 注影响有限(boost 仅加权,主路仍召回),P0#2 后观察 |
| R2-N1 | LOW | 结构 | §7.1 | "docs" 简写(同 Round 1 #10 残留) | §7.1 改"文档类型桶(paragraph/heading/list/table)" |

**本轮修复**:9 个 | **累计修复**:25 个

---

### 汇总

- **收敛轮次**:2
- **累计修复**:25 个问题(CRITICAL: 1, HIGH: 2, MEDIUM: 6, LOW: 16)
- **内容审核**:Round 1 不通过 → Round 2 有条件通过(MEDIUM×1 + LOW×7)→ 已全部修复 → **收敛**
- **结构审核**:Round 1 不通过 → Round 2 **通过**(LOW×1)→ 已修复 → **收敛**
- **完成时间**:2026-08-04

> Round 2 两路均无 HIGH/CRITICAL;内容审核新发现的 MEDIUM(intent 落库链路)已补全。按 dual-review 收敛规则(MEDIUM/LOW 最后一轮清扫即收敛),不再开 Round 3,spec 进入实现。
