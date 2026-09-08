# I-002 Evidence Intelligence — Contract Closure

> **性质**:只读契约收口(READ-ONLY / CONTRACT CLOSURE)。零实现、零生产触碰、零 Benchmark 触碰。
> **输入**:I-002 Engineering Discovery(docs 仓 c0d29bc)+ 本报告对当前代码的再核验(全部 file:line 可溯)。
> **目标**:为 Planner A 冻结首批 I-002 实现契约补齐剩余证据——仅三件事:① INC-2b 信任边界语义与"脱敏/重嵌入"冲突消解;② INC-4 EvidenceSlot/EvidencePlan 接口冻结候选;③ INC-5 最小依赖契约。
> **日期**:2026-09-08。

---

## 1. Trust-Boundary State Model(六态模型,不可折叠)

 Discovery 的教训先行:把"过滤"当一个状态会掩盖真实不变量。以下六态各自独立判定;
 每一格都是代码实证的当前真相,不是设计意图。

 状态链:`STORED → RETRIEVED → COMPOSED → SENT_TO_LLM → CITED → USER_VISIBLE`

### 1.1 当前真相表(逐内容类别,当前代码行为)

| 内容类别 | STORED | RETRIEVED | COMPOSED | SENT_TO_LLM | CITED | USER_VISIBLE | 代码证据 |
|---|---|---|---|---|---|---|---|
| 公开第一方文档(wiki/github 公库/官网/web_crawl/woocommerce) | ✅ | ✅ | ✅ 可引用段 | ✅ | ✅ [N] | ✅ 来源列表 | citation.py:54-56(PUBLIC_SOURCE_TYPES);citation.py:157-160 |
| **filesystem 内部案例**(未标 internal,默认可见性 widget,api) | ✅ | ✅ **进入候选** | ✅ 背景资料段 | ✅ **按设计参与生成** | ❌ | ❌ 不进来源列表 | registry.py:42(默认可见性);citation.py:8,1147-1150,172-180;rag.py:424(support 桶=filesystem) |
| 标记 `internal` 的源(任意类型) | ✅ | ❌ 探测渠道不匹配,检索即排除 | ❌ | ❌ | ❌ | ❌ | evidence_meta.py:72-76;search.py:41-56,218-224 |
| **github 私有仓库内容**(若存在此类源) | ✅ | ✅ | ✅ 可引用段 | ✅ | ✅ | ✅ **可成为访客可见引用** | github.py:82,102-111(私库支持);github ∈ PUBLIC_SOURCE_TYPES,**无 internal 标记路径** |

### 1.2 关键结构性事实

1. **sensitivity 派生永不赋 `public`**:SENSITIVITY_CLASSES 含 `public`,但 `derive_evidence_meta` 唯一赋值路径 = 显式 `internal` 标记→`internal`,**其余全部→`unknown`**(evidence_meta.py:153-158)。即:**unknown ≈ 除 internal 标记源外的全部语料**,包括全部公开文档。
2. **SENT_TO_LLM ≠ CITED**:filesystem 案例证据按设计进入 LLM prompt(背景段)但永不编号。C4 归因簇(sq-008/sq-040/cg-r18,rev2 PRIMARY=K6)实证 SENT_TO_LLM 内容可泄入**答案正文**(非引用形态的用户可见泄漏)——这是六态必须分开看的实证。
3. **无中间态存在**:当前元数据没有任何取值能表达"内部性质但可作背景参与生成"——internal 标记=全渠道检索排除;不标记(unknown)=完全自由检索。**这是 PD-2b-3 的核心结构缺口**。

---

## 2. MODEL A vs MODEL B(信任模型对比)

### MODEL A — Metadata Enforcement(元数据执行)

敏感/内部内容**保持索引**;策略通过确定性元数据过滤(检索期)+ 组合期复核执行。

- **达成的安全属性**:CITED=❌、USER_VISIBLE(作为来源)=❌(对 background 类);internal 标记类 RETRIEVED=❌;personal-data(一旦有标签)检索+组合双闸可排除。
- **残余泄漏面**:① SENT_TO_LLM 对 background-eligible 内容保持开启(按设计);答案正文回声风险不消除(C4 实证);② **索引泄露=全量暴露**(敏感原文持久在 Weaviate);③ 迁移窗口/幽灵对象的元数据滞后(既有纵深守卫模式可压缩,不归零)。
- **运维成本**:≈0(过滤参数+组合复核,均内存/查询侧);零重嵌入。
- **迁移要求**:metadata-only `data.update` 回填(4 处生产先例:channel_visibility:172 / evidence 回填:205 / store metadata:144-146 / product migration:138-150)。
- **是否符合 Target Architecture 信任边界意图**:**符合**。P0 信任边界交付(channel_visibility + SourceVisibilityGuard fail-closed)就是 MODEL A 方向;架构意图是"选择正确可信的证据",不是存储消毒。
- **是否引入静默数据损失**:**否**(内容原样保留;行为变化只在执行点;support 背景能力保留)。

### MODEL B — Content Redaction(摄取期内容脱敏)

敏感内容在嵌入/索引前删除/改写。

- **达成的安全属性**:全链闭环——敏感原文不 STORED ⇒ 六态全 ❌(含 SENT_TO_LLM 与存储泄露面)。
- **残余泄漏面**:迁移前存量 + 未来摄取漏网;**脱敏假阴性被静默接受**(无报警面)。
- **运维成本**:摄取管线新增改写步骤 + 全量受影响语料重嵌入 + 持续脱敏规则维护。
- **迁移要求**:**必须重嵌入**(文本变→向量失效)。无 metadata-only 捷径。
- **是否符合 Target Architecture 意图**:**超出**——是存储卫生目标,不是证据智能目标;与既有 reject-not-rewrite 先例(TechnicalSafetyPolicy,ingest.py:285)相逆;mask_pii 之所以只在查询时/附件时应用(routes.py:128,612)正是为了避免改写知识语料。
- **是否引入静默数据损失**:**是(风险实质)**——案例证据改写后诊断价值退化,support 答案质量静默下降;对内部知识语料做 PII 式改写会破坏其效用。

### 结论不变量(供 A 裁决,非成本驱动)

| 不变量 | 决定的模型 |
|---|---|
| **存储不变量**(敏感原文可否持久在索引) | 仅 **personal-data 类有此不变量**(个人数据不应原文持久);internal/unknown 类**无**此不变量 |
| **使用不变量**(可否参与生成/引用) | internal/unknown 类的全部产品关切都在此——MODEL A 完全覆盖 |

**RECOMMENDED_TRUST_MODEL = HYBRID**:MODEL A 作为 internal/unknown 的执行架构(v1);MODEL B 保留给 **personal-data 类的存储不变量**(且以 PD-2b-2 的标签生产者存在为前提)。这不是实现成本折中,而是不变量分工:两类内容对应两类不变量。

---

## 3. PD-2b-1 证据(unknown sensitivity 语义)

**候选规则**:"unknown = 对生成证据 fail-closed"(可存储/可索引,但分类前不得进入生成上下文或引用)。

**决定性代码事实**:unknown 派生覆盖面 = 除 internal 标记源外的**全部语料**(§1.2-1)。其中:
- 公开文档类 unknown chunk 携带 `citation=citable-numbered`(derive 镜像 PUBLIC_SOURCE_TYPES,evidence_meta.py:160-166)——INC-2a 冻结语义已对它们做出**结构性可引用断言**;
- filesystem 案例类 unknown chunk 是 support 意图的专属 boost 桶内容(rag.py:424)与背景证据主体。

**若按字面冻结该规则的后果(影响量化,基于冻结派生 + 基线事实)**:
- 生成上下文失去**除 internal 标记源外的 100% 语料**——每条检索路径必然 insufficient → 产品级答案黑屏;
- 基线佐证:零源运行已占 32.5%(118/363,BASELINE_V1:131),C1 簇 21 例 → 将趋近 100%;
- 与 INC-2a 冻结语义自相矛盾(citable-numbered 的 chunk 不得进入引用上下文)。

**两条自洽的冻结路径(证据 + 影响,规则本身未改,交 A 拍板)**:

| 选项 | 语义 | 前提 | 语料影响 |
|---|---|---|---|
| **①(推荐)v1** | fail-closed 仅作用于 `personal-data`;`unknown` 维持现行行为(可检索;引用资格按既有 citation 字段/来源规则) | 无 | **零影响**;与 INC-2a 冻结完全兼容 |
| ② | unknown fail-closed | 须先做**public 派生扩展**(见下) | 残余 unknown=filesystem 类 → support 背景能力丢失,C1 恶化 |

**选项 ② 的前置修订(若 A 选它)**:给 derive 增加确定性 public 派生——`source_type ∈ PUBLIC_SOURCE_TYPES ∧ "internal" ∉ channel_visibility → sensitivity=public(origin=D)`。词表不变(public 已在 SENSITIVITY_CLASSES),仅派生函数扩展 = **对 INC-2a 冻结派生的 formal amendment**,需按修订流程授权。该修订同时是 MODEL A 下"public 可判定"的一般前提(不止服务 PD-2b-1)。

---

## 4. PD-2b-2 证据(personal-data 判定生产者)

逐一检查现有摄取/配置边界能否**无新增 LLM 调用**地确定产出四值:

| 值 | 现有确定性生产边界 | 结论 |
|---|---|---|
| `internal` | ✅ **已存在**:管理员源配置 `channel_visibility=["internal"]`(registry.py:42 字段;scripts/migrate_channel_visibility.py:11 约定) | 可直接用 |
| `public` | ✅ 可确定性派生:`(source_type, channel_visibility)` 纯函数(§3 选项②的修订) | 需 INC-2a 派生修订授权 |
| `user-provided` | 词表已预留(evidence_meta.py:44);当前附件路径**不入 Weaviate**(routes.py:612,rag.py:1098-1101),无语料消费者 | 保留,无当前语料语义 |
| `personal-data` | ❌ **不存在**。filesystem/github 内容任意;摄取侧唯一内容闸是 reject 式 TechnicalSafetyPolicy(不改写、不分类);无任何内容审查边界;源元数据(source_type/channel_visibility)对内容敏感性零判别力 | **明确判定:不可靠的确定性推断不存在** |

**明确声明(不做启发式补齐)**:personal-data 无法从当前源元数据/配置确定推断。要生产该标签只有两条路:
(a) **管理员显式标记**(新配置面,确定性;推荐为指定生产者);
(b) 离线内容审查工具(独立授权 + 独立系统;非请求路径 LLM,但也不是确定性元数据派生)。

**v1 契约含义**:personal-data 维持 INC-2a 的预留状态(derive 永不赋值,evidence_meta.py:86-88 已预留);PD-2b-2 的冻结 = 指定 (a) 为未来生产者 + v1 不依赖该标签。MODEL B(HYBRID 中的 B 侧)随 (a)/(b) 落地才生效。

---

## 5. PD-2b-3 证据(存量 filesystem 源)

(全部源码/元数据级证据,零内容审查。)

- **概念角色**:内部支持案例知识——"filesystem 内部案例参与生成不对外展示"是代码注释明示的设计(citation.py:8;rag.py:1147-1150);support 意图 boost 桶专指 source_type=filesystem(rag.py:423-427)。
- **当前 sensitivity**:全部 filesystem 源 = `unknown`(无 internal 标记路径;默认可见性 (widget,api),registry.py:42)。
- **"unknown=fail-closed"字面执行时**:support 意图失去专属桶内容与背景证据主体 → support 答案退化为纯公开文档;C1 型零源恶化(§3)。
- **显式 internal 标记时**:检索全渠道排除(§1.1 第三行)→ support 案例证据**完全消失**,损失同一能力,只是换了机制。**即:现有元数据没有能同时保住信任与 support 能力的状态(§1.2-3 结构缺口)**。
- **迁移可否 metadata-only**:可——整体标记(任方向)都是一轮 `data.update` 回填,零重嵌入。
- **何时才需要内容级脱敏(MODEL B)**:仅当 ① personal-data 类内容必须离开索引(存储不变量,HYBRID 的 B 侧),或 ② 产品要求案例文本消毒且保留背景效用。
- **处置选项(供 A 拍板,附建议)**:
  - (a) **v1 保持 unknown + 不对 unknown 执行 fail-closed**(=§3 选项①)——能力零损失,SENT_TO_LLM 暴露面如实保留;
  - (b) 全量标 internal——最大封锁,support 案例证据归零(行为回退,C1 恶化);
  - (c) **新增角色门控处置**(background-eligible-for-support 语义)——恰好是 INC-5 的 CASE_EVIDENCE slot(BACKGROUND_ALLOWED)语义,建议作为 I-002 原生后续而非 INC-2b 前置。
  - **建议:(a) for v1 + (c) 作为 INC-5 语义的自然延伸**。

---

## 6. INC-2b Readiness(收口判定)

**POLICY_DECISION_REQUIRED**——机制面全部就绪(schema 属性已在、回填模式 4 处先例、执行点两个落位明确),但契约冻结被三个 PD 阻塞,且本报告已给出每个 PD 的完整证据 + 建议:

| PD | 一句话状态 | 本报告建议 |
|---|---|---|
| PD-2b-1 | 两条自洽路径(§3) | 选项①:fail-closed 仅限 personal-data;unknown 维持现行 |
| PD-2b-2 | personal-data 无确定性生产者(§4) | 指定管理员显式标记为未来生产者;v1 维持预留 |
| PD-2b-3 | 现有元数据无中间态(§5) | (a) v1 + (c) INC-5 原生后续 |

三个 PD 拍板后 INC-2b 即 READY_FOR_CONTRACT,无剩余工程发现项。

---

## 7. EvidencePlan / EvidenceSlot 冻结候选(语义契约,非实现)

### 7.1 EvidenceSlot(冻结候选)

```
EvidenceSlot:
  role:                 冻结枚举 {PRODUCT_SPEC, SOLUTION_GUIDE, CASE_EVIDENCE, STORE_OFFICIAL}
  product_scope:        tuple[slug, ...]     # 空 = 继承 resolution 目标(resolver 仍是产品身份唯一权威)
  required:             bool                 # 覆盖义务;v1 执行语义 = trace 信号,不改既有拒答路径(零回归)
  citation_requirement: 枚举 {CITABLE_REQUIRED, BACKGROUND_ALLOWED}
                                             # 公开断言类槽位必须可引用;案例类槽位允许背景参与
```

**逐字段必要性论证(不加无运行时/验收需求的字段)**:

| 候选字段 | 判定 | 理由 |
|---|---|---|
| role | ✅ 必须 | 覆盖谓词与 role→检索过滤表的 join 键;benchmark `required_evidence_roles` 的对应物 |
| required | ✅ 必须 | insufficient 信号(既有不足语义 rag.py:1582-1665 形态)的触发输入 |
| citation_requirement | ✅ 必须 | 组合不变量(§1)需要区分"必须可编号"与"背景即可";CASE_EVIDENCE=BACKGROUND_ALLOWED 正是 filesystem 语义 |
| product_scope | ✅ 必须 | 槽位可显式收窄/继承;维持 resolver 权威 |
| min_coverage | ❌ 不加 | required ⇒ ≥1;比较配额已是结构性保障;额外旋钮无验收需求 |
| authority_requirement | ❌ 不加 | authority 全量 unknown(冻结派生)——死字段;v1 权威代位 = role 语义(source_type 标签) |
| temporality_requirement | ❌ 不加 | 见 §8(currentness 由 STORE_OFFICIAL role 语义承担) |
| 检索过滤参数 | ❌ 不进契约 | 实现细节:INC-4 拥有 role→过滤映射表(扩展 INTENT_BOOST_FILTERS,rag.py:423-427) |

### 7.2 EvidencePlan(冻结候选)

```
EvidencePlan:
  slots:        tuple[EvidenceSlot, ...]
  derived_from: 冻结 dict {category, interaction_mode, resolution_mode, resolution_targets[, dimension]}
                                     # 归因/trace(INC-1 血统形态);strategy 字段不加——可由 resolution_mode 派生
构造器 derive_evidence_plan(understanding, resolution, dimension) -> EvidencePlan:
  纯函数 / 全总 / 零 LLM / 零 IO;任何不一致 → 回退单个 optional PRODUCT_SPEC slot(fail-open,类比 understand_task)
```

### 7.3 规划覆盖表(8 类任务形态 → 确定性映射,全部由现有 Task Understanding 输出驱动)

| 任务形态 | 判定输入(现有字段) | Plan |
|---|---|---|
| factual lookup | standard + product + exact/none | [PRODUCT_SPEC(required, CITABLE_REQUIRED, scope=目标)] |
| comparison | standard + product + **MODE_COMPARISON** | 每 target 一个 PRODUCT_SPEC(**镜像既有 per-target 配额管线** rag.py:199-260——v1 比较路径继续走既有管线,plan 为其语义投影,不双轨) |
| troubleshooting | standard + support | [CASE_EVIDENCE(optional, BACKGROUND_ALLOWED), PRODUCT_SPEC(optional)] |
| recommendation/solution | standard + product(solution 语义) | [SOLUTION_GUIDE(required, CITABLE_REQUIRED), PRODUCT_SPEC(optional)] |
| commercial/pricing | standard + commercial + exact | [STORE_OFFICIAL(required, CITABLE_REQUIRED, scope=目标), PRODUCT_SPEC(optional)] |
| clarification-required | interaction_mode=clarification_required | **零检索**(显式;运行时该路径在 plan 构造前已短路 rag.py:1393-1419) |
| capability/orientation | interaction_mode=capability_orientation | **零检索**(显式;已短路 rag.py:1420-1446) |
| true off-topic | interaction_mode=off_topic | **零检索**(显式;已短路 rag.py:1367-1390;resolver 歧义/不支持更在理解之前短路 rag.py:1279-1310) |

派生输入完备性:上表每行只消费 (category, interaction_mode, resolution.mode/targets, 维度)——**全部是 understand_task 单次调用与 resolver 的既有输出**(task_understanding.py:112-135;rag.py:1312-1347)。"insufficient evidence"不是规划输入,是 INC-5 覆盖检查的输出。

### 7.4 LLM 边界

**NEW_LLM_CALL_REQUIRED = NO。** 覆盖表对 (category × interaction_mode × resolution.mode) 全总且确定性;推翻默认需要具体运行时证据证明某必需产品行为无法确定性满足——当前不存在该证据。唯一曾疑似需要 LLM 的"自由文本证据主题识别"有确定性抓手(doc_section/chunk_type/url 特征 + benchmark required_evidence_roles 词表)。

---

## 8. Temporality Amendment Determination

**TEMPORALITY_AMENDMENT_REQUIRED = NO(对本契约冻结而言)。**

- INC-2a 冻结保持原样:TEMPORALITY_STATES 词表与"恒 unknown"派生均不触碰;
- commercial current-truth(产品目标 + #28 历史价格纪律)由 **STORE_OFFICIAL role 的组合语义**确定性承担:价格/采购类 required 槽位未被 store-official 证据覆盖 → insufficient/澄清,而非引用过时 wiki 价格——无需任何 temporality 元数据即可获得 #28 的行为约束;
- OLD/NEW/REASON:不适用(无修订);UNCHANGED CONTRACT SURFACES:evidence_meta.py 全部(词表 + derive + origin 编码)与 INC-2a 两个迁移脚本;
- 未来路径(备案,不阻塞):若 post-I-002 Benchmark 证明需要 chunk 级时效过滤,再按修订流程提出 source_type 结构事实派生(如 woocommerce→volatile-current)——那是独立裁决,不进本契约。

---

## 9. INC-4 Readiness

**READY_FOR_CONTRACT。** 依据:§7 冻结候选(字段级必要性论证完备)、§7.3 覆盖表(8 类全确定)、§7.4 零 LLM、§8 无修订依赖。契约需附带的工程条款:派生纯函数 + 黄金表测试;slot 检索双路径 parity;≤3 required slots 上限 + 检索延迟预算;零新增 llm_calls 断言;比较路径字节级零回归(T-COMPARISON 既有用例守卫)。

---

## 10. INC-5 Interface Dependency(最小依赖契约,不设计实现)

1. **INC-5 从 EvidencePlan 接收什么**:冻结的 slots(role / required / citation_requirement / product_scope)——仅此;derived_from 仅供 trace 透传。
2. **选择/组合必须返回什么**:
   - 选中集 = **同一 SearchResult 类型的有序子集**(插入点:剪枝/防御过滤之后、`build_citation_context` 之前——answer rag.py:~1576→1684 与 stream 同位);
   - CoverageReport 值对象:`{covered: [{role, evidence_ids: [(source_id, chunk_index)]}], uncovered_required: [role], uncovered_optional: [role]}` → trace stages.selection(有界,INC-1 §8 形态)+ 可选组合期诚实标注;generation 与 citations 消费面不变。
3. **哪些既有签名保持不变**(已核验):`build_citation_context(reranked, sources, taxonomy)`(citation.py:102)、`HybridSearcher.search/search_symbols/search_bucket`(search.py:150+)、`Reranker.rerank`、`Pruner.prune`(pruner.py:20)、`_build_messages`(rag.py:1050)。选择器只消费 SearchResult 已携带字段(INC-2a 读回已就绪),零新读回。
4. **INC-5 启动前必须冻结的接口**:EvidenceSlot/EvidencePlan dataclass + role 枚举 + citation_requirement 枚举 + CoverageReport 形态 + 选择器函数签名(纯函数 `(reranked, plan) -> (selected, coverage)`)+ INC-4 独有的 role→检索过滤映射表归属。
5. **能否在 INC-4 实现完成前并行**:选择器逻辑与测试对着冻结 dataclass 独立开发,唯一等待点是两个一行接线 call site(随 INC-4 落地或集成门并解)。

**INC5_PARALLEL_AFTER_INTERFACE_FREEZE = YES。**

---

## 11. Required Production Evidence

**契约冻结本身:不需要生产访问**——本报告全部判定基于仓库代码与冻结派生的结构性事实(尤其 §1.2-1 的"unknown≈全语料"由派生函数直接导出)。

**实现门(回填规模/上线分寸)仍需以下只读聚合(零内容转储、零变更)**:

```sql
-- ① Postgres 源配置清单(元数据级,零文档内容)
SELECT source_type, channel_visibility, count(*)
FROM data_sources GROUP BY 1, 2;
```

```text
② Weaviate 聚合:Document 按 evidence_sensitivity 分值计数(回填状态核验)
③ Weaviate 聚合:where source_type=filesystem 的 chunk 总数(PD-2b-3 影响面定量)
④ 对 ① 中 "internal" ∈ channel_visibility 的源逐个 where source_id=<id> 聚合 chunk 数
   (internal 语料占比 → MODEL A 内部类规模)
```

---

## 12. Remaining Product Decisions

| # | 决策 | 状态 | 建议 |
|---|---|---|---|
| PD-2b-1 | unknown 执行语义(§3) | 待拍板(证据已备) | 选项①:fail-closed 仅限 personal-data |
| PD-2b-2 | personal-data 生产者(§4) | 待拍板(证据已备) | 管理员显式标记为指定生产者;v1 维持预留 |
| PD-2b-3 | filesystem 处置(§5) | 待拍板(证据已备) | (a) v1 + (c) 作为 INC-5 原生后续 |
| INC-4 | 无剩余产品决策 | — | — |
| INC-5 | 无剩余产品决策 | — | — |

---

## 附:证据索引(本报告新增核验)

- evidence_meta.py:38-55(四词表精确值;SENSITIVITY_CLASSES 含 public/personal-data/user-provided 但派生不赋)
- rag.py:1279-1310(resolver 歧义/不支持先于理解短路)/ 1367-1446(off_topic/clarify/capability 短路)/ 423-427(support 桶=filesystem)/ 199-260(比较 tier 配额)/ 1582-1665(既有不足语义)
- citation.py:8,51-56,102-180(背景段设计意图与 PUBLIC_SOURCE_TYPES)/ search.py:41-56,218-224(探测渠道)/ registry.py:42(默认可见性)/ github.py:82,102-111(私库支持)
- routes.py:128,612 + rag.py:1098-1101(附件:PII 脱敏、不入语料)/ ingest.py:285(reject-not-rewrite 先例)
- 回填先例 ×4:scripts/migrate_channel_visibility.py:172 / migrate_backfill_evidence_meta.py:205 / migrate_store_device_metadata.py:144-146 / services/product_migration.py:138-150
- 主仓 docs/ 子路径 track 先例:git ls-files docs(19 个 implementation/integration 报告文件与嵌套 docs 仓共存)
