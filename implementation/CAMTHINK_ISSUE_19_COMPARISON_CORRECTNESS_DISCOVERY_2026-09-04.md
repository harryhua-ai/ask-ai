# CamThink Issue #19 — Comparison Query Correctness Discovery(DISCOVERY ONLY)

- 日期:2026-09-04(UTC)
- Baseline:v1.0.0 = **0e6a8a3bb72932b26fcf500954aacfe109373133**(= origin/main;全部代码引用均取自该树)
- 模式:DISCOVERY ONLY——零实现、零生产变更(**PRODUCTION_MUTATIONS = NONE**,未重放 /ask:生产写入 0;生产证据全部复用 v1.0.0 部署验收门已存证的 SSE/日志/trace)
- Worktree(§10):无需新建——resolver/taxonomy 为纯函数,本地 /tmp scratch 目录按 v1.0.0 文件原样重组后确定性重放;未运行测试套件、未改任何仓库文件
- **READY_STATUS:READY**(无未决 material Product Decision;可选后续决策见 §7-PD)

---

## 1. 完整真实路径追痕(§2)

对生产复现查询 `NE302 和 NE301 有什么区别?`(conversation `6313e61d` / `82b00e3d`,SSE 与日志存证于 v1.0.0 部署门):

| 环节 | 真实实现(文件:行为) | F1 实测 |
| --- | --- | --- |
| 意图识别 | `pipeline/intent.py`:LLM 分类,**无独立 comparison 意图**(「竞品对比」仅是 product 意图的描述词) | `→ product confidence=1.0` |
| 目标解析 | `pipeline/product_resolver.py:resolve_products`(纯函数):≥2 显式型号 → **MODE_COMPARISON** | 本地确定性重放(同码同配置):`mode=comparison targets=(ne302, ne301)` ✓ **解析层正确** |
| 资格集合 | `taxonomy.eligible_slugs(targets)` = 目标 ∪ 共享(ai-common/hardware-common/knowledge/release-notes)∪ 平台桶(**aitoolstack**/neomind) | `{ai-common, aitoolstack, hardware-common, knowledge, ne301, ne302, neomind, release-notes}` |
| 检索 | `rag.py` 单查询三路 RRF 融合;`search.py:_product_labels_filter` = 资格标签 **OR any_of** 硬过滤;**无 per-target 检索、无 per-target 配额** | 融合 top-3 = ne302 overview + ne302 dev-env + **store/ne301 页(product=aitoolstack,过 OR 过滤)**;**ne301 标注证据 0 条进入上下文** |
| 重排 | 单列表 rerank + pruner(F1 例 pruner fail-open 保留全部) | Compute Scores 0/2 |
| 生成上下文 | `boundary_prompt`(taxonomy 冻结):**comparison 感知**——按产品分节、归属引用、严禁跨产品填充、单侧不足须明示 | 模型只有 2×ne302 + 1×aitoolstack(商店页)**无任何 ne301 标注可引用** |
| 流式资格校验 | `pipeline/citation.py:CitationStreamFilter`:**只剔标记**(悬空/无据/产品不合格的 `[N]`),**绝不改写散文** | 非全剔机制(C 型全滤在架构上不可能,除非模型只吐标记) |
| PC-01 | `rag.py`:`if not full_answer.strip(): raise EmptyGenerationError`;`llm/deepseek.py:stream` **只 yield `delta.content`**(reasoning_content 按设计丢弃);provider 异常走 `provider_error/stream_interrupted` | `kind=empty_generation,llm_ms≈30s`——30 秒内**零 content delta**(流正常打开、正常结束)= **type B:模型零内容**(若 v4-flash 为混合推理型,内容进了 reasoning 通道;客户端侧不可分辨,provider 机制开放) |
| 兜底/消息 | `routes.py`:empty_generation → 补发 `localized_message(SERVICE_UNAVAILABLE_KEY)` token + error 事件 `message_key=service_unavailable` | 用户见「服务暂时不可用,请稍后再试。」 |

**单目标假设清单(where comparison semantics are lost)**:
1. `intent.py` 无 comparison 意图(仅影响 boost 桶/观测,不致错误);
2. **检索层:comparison 复用单目标融合检索**——并集 OR 过滤 + 单列表 rerank,无 per-target 召回/配额/归属(主因 RC1);
3. 引用校验:合格性按「源的产品 ∈ 资格集」判定,**无 per-section/per-claim 归属校验**(归属正确性完全依赖 boundary_prompt 约定,未强制);
4. PC-01 消息:B 型(模型零内容)与「资格耗尽」共用 `service_unavailable` 通用文案,无确定性分型;
5. `AskRequest.product` 为单字符串——显式 hint 无法表达双目标(comparison 只能经查询文本触发)。

## 2. ROOT CAUSE(§7,按因果序)

- **RC1 检索架构(主)**:comparison 模式无 per-target 证据获取。单查询语义「A 和 B 有什么区别」的 top-k 天然偏向一侧;F1 实证 ne301 侧仅由一条**错误标注**的商店页代表。
- **RC2 商店元数据粒度**: woo 分类→产品映射**按列表序先命中先赢**,且广品线类别(`"ai cameras"→"aitoolstack"`)排在设备类别之前——NE301 相机(categories=["AI Cameras","NE301"])被抢注为 aitoolstack。
- **RC3 空生成语义**: PC-01 把「模型零内容(B)」与一切零可用输出统一降级为通用 `service_unavailable`;既有的 `product_evidence_insufficient` 键只可能在**检索层零资格证据**分支触达,生成期证据饥饿/模型空流不可达。用户在确定性可解释的场景收到误导性的「稍后再试」(重试无效)。
- RC4(开放、非阻塞): v4-flash 对该 prompt 形态零内容输出的 provider 侧机制(混合推理通道/安全空回)——客户端按设计只读 `content`,无法进一步归因;不阻塞合约。
- 单目标假设的 #5 边界本身**工作正常且未被削弱**:F1 中无任何污染内容触达用户(fail-closed),01/09/10/11 等单产品语义全部正确。

## 3. MULTI-TARGET PRODUCT CONTRACT(§3)

冻结语义(对 `resolve_products` 已产的 `MODE_COMPARISON` 下游补全,不改 resolver):

1. `requested_targets = {T1, T2, …}` 为本轮权威目标集(现状:仅支持查询文本显式型号触发;`AskRequest.product` 单 hint 维持现状);
2. 证据按目标**分别可归属**:每个 target 侧须有**带该 target 标注**的证据进入上下文(检索层保证,见 §5-AC);
3. 系统**可以**:为每个 target 分别检索;使用显式合格的共享/平台证据(现资格集语义不变,#5 不削弱);仅比较双侧均有证据支持的属性;
4. 系统**不可**:把 T1 证据记到 T2 名下;用 T2 数据填补 T1 缺失;引入 requested_targets 之外的兄弟产品证据(现 OR 过滤已保证,保持);**静默把 comparison 降级为单目标**(降级必须显式可见,见 §6);
5. 单侧无证据:答案须明确「哪一侧有支持、哪一侧缺官方资料」(boundary_prompt 已约定,检索层须提供可归属证据使该约定可执行);
6. 双侧均不足:返回**比较专属的真实不足语义**(新键,§6),而非 `service_unavailable`。

## 4. EVIDENCE ATTRIBUTION CONTRACT

- **V1(本 Issue 范围)**:归属在**检索层结构性保证**(per-target 召回配额:每 target 至少 N 条带自身标注的证据进入候选,不足即触发 §6-D 语义)+ 生成层 boundary_prompt(既有冻结文案)+ 流式校验(既有标记级)。
- **V1 明确不做**:per-claim/per-section 机器归属强制校验(现校验器只验「源产品 ∈ 资格集」;逐句归属判定无确定性算法,引入即破坏 CIT 系列的确定性边界)。残余风险(模型把 B 侧句子挂 A 侧引用)由 prompt 契约约束——与 #5 单产品模式同一信任级别,已在 #5 验收中接受。
- 语义等价不变式:**任何 target 侧的标注证据缺失 ⇒ 必走显式不足语义,禁止静默降级单目标**。

## 5. STORE IDENTITY CONTRACT(§4)

**结论 = 方案 B:两个正交维度。** 商业/知识角色已由 `source_type=woocommerce` + 广品线桶承载;设备身份需独立按页面确定性派生,**不得与商业角色混同**。

现状审计(生产 101 chunk 只读全量,2026-09-04):
- `aitoolstack`×57:含**整设备产品页**——NE301 Wireless Edge AI Camera(id 2092,5ch)、NE301 PoE(4271,4ch)、NE503 4K PoE(5110,4ch)、NE101 Modular Sensing Camera(319,4ch)、NE101 Dev Kit(1984,3ch)、NG4500 AI Box(320,3ch)、NG4500-CB01(419,4ch)、NE301 STM32N6 Dev Board(4546,3ch)、NE101 ESP32-S3 Board(418)等;另含配件(标题自名宿主:"M12 Optical Lens **for NeoEyes NE301**"、"SC200AI USB Camera Module **for NE101**"、Wi-Fi HaLow Board、Sensor Expansion Board **for NE101 and NE301**…)
- `commercial`×44:真通用件(线材/电池/喇叭/杜邦线/Order Adjustment Fee 等)——**现状正确,不动**
- 根因代码:`connectors/woocommerce.py:_CATEGORY_MAP`(`"ai cameras"→"aitoolstack"`)+ `_category_to_product` 列表序先命中先胜(docstring 自证「AI Cameras 通常排在 NE 前故归 aitoolstack」)
- **无 NE302 商店页**(NE302 商店在售=0),NG4500/NeoMind/AI ToolStack 自有页身份正确

**冻结规则(V1 迁移范围 = 仅无歧义设备产品页)**:
1. 设备身份派生:woo `name`+`slug` 经 `taxonomy.extract_products` 取**首个可 canonicalize 且 targetable 的设备 slug**(ne101/ne301/ne302/ne503/ng4500)→ 该页 product=设备 slug;派生失败 → 维持现标签(不猜,沿用 #5 保守原则);
2. 配件页(标题含宿主设备):**V1 不重标**(维持 aitoolstack/commercial 现状——其已经由平台桶对全部目标合格,不影响 comparison 正确性);配件是否应继承宿主设备身份 = **可选后续 Product Decision(PD-1,非阻塞)**;
3. 迁移形态:**Weaviate product 属性原位更新,零 re-embed**(完全复用 #5 `migrate_product_metadata` 机制/dry-run 默认;预计受影响 ≤40 chunk,精确清单迁移前 dry-run 产出);
4. ingest 侧同步修 `_category_to_product` 排序/派生(防新增页面复发)。

## 6. EMPTY-GENERATION CONTRACT(§5)

现状分型(`routes.py` PC-06 failure_kind)与目标:

| 型 | 现状 | 契约 |
| --- | --- | --- |
| A provider/服务失败 | provider_error / stream_interrupted → service_unavailable | **不变**(真是服务问题,重试合理) |
| B 模型零内容 | empty_generation → **service_unavailable**(通用,误导) | **保持 service_unavailable 文案但 kind 细分**:empty_generation 属真模型异常,重试语义成立;增加 `reason="model_empty_stream"` 进 error payload(观测用,不改用户文案) |
| C 资格校验耗尽 | 与 B 混同(架构上仅「模型只吐标记」可达) | 检测:`CitationStreamFilter.stats` 全为剔除且 prose=0 → **禁用 service_unavailable**;映射 `product_evidence_insufficient`(单目标)/ `comparison_evidence_insufficient`(comparison) |
| D 比较证据不足 | **不存在该语义** | **新增强制前置检查**(生成前,确定性):comparison 模式下任一 target 无自身标注证据 → 直接走不足语义(不发 error 事件,`complete(is_answered=false)` + result_key),**绝不进入必然失败的生成** |

**新冻结消息键**(复用阶段⑯架构:`MESSAGE_KEYS` + `_MESSAGES` zh/en + `localized_message` 纯函数,零新框架):
- `comparison_evidence_insufficient`,占位符 `{products}`(双侧展示名)与 `{missing}`(缺侧展示名);文案最终措辞属产品文案冻结流程(Discovery 不任意定稿),语义要求:明示哪侧有支持、哪侧缺官方资料、不建议重试。

## 7. CHANGE BOUNDARY(§7 最小变更面,不冻结实现 HOW)

| 组件 | 变更 |
| --- | --- |
| `pipeline/rag.py` | comparison 分支 per-target 检索(或检索后 per-target 配额融合)+ D 前置检查 + C/B 分型管道 |
| `retrieval/search.py` | per-target 查询扇出(复用既有 `product_labels` 单标签过滤,exact 路径不动) |
| `connectors/woocommerce.py` | 设备身份派生(name/slug 规则)+ 类别映射排序修正 |
| `utils/user_messages.py` | 新键 `comparison_evidence_insufficient`(冻结文案入表) |
| `pipeline/citation.py` | 无必须变更(stats 已可供 C 检测) |
| `scripts/`(新) | 商店设备页元数据迁移工具(复用 #5 dry-run 默认/原位更新模式) |
| 不动 | resolver(已正确)、taxonomy、#5 检索硬边界、schema、Weaviate schema |

## 8. ACCEPTANCE MATRIX(§6,确定性验收)

| # | 案例 | 期望 |
| --- | --- | --- |
| 1 | NE302 vs NE301(双侧有证据) | comparison targets=(ne302,ne301);上下文含双侧标注证据;答案按产品分节且引用可归属;不触发不足语义 |
| 2 | 仅 NE301 侧有证据 | 完成生成:明示 NE301 有支持、NE302 缺官方资料;不虚构 NE302 侧 |
| 3 | 仅 NE302 侧有证据 | 对称案例 2 |
| 4 | 双侧证据均不足 | `complete(is_answered=false)` + `comparison_evidence_insufficient`;**非** service_unavailable |
| 5 | A vs B 且存在共享证据 | 共享证据可用于双侧,但须标注共享归属;不得记为某侧独有规格 |
| 6 | A vs B,存在第三兄弟 C | C 的标注证据不出现在上下文(OR 过滤保持);模型引用 C 侧内容被标记级校验剔除 |
| 7 | 单产品 NE302 查询 | #5 行为逐字不变(exact 模式回归约束) |
| 8 | 比较含不支持产品(hint/文本不可 canonicalize) | `product_not_supported`(现语义保持) |
| 9 | 比较含歧义别名(deixis) | `product_ambiguous` 澄清(现语义保持) |
| 10 | Store 设备页正例(NE301/NE101/NE503/NG4500 相机/主机页) | 迁移后 product=设备 slug;对该设备的 exact/comparison 检索可命中;迁移 dry-run 清单=冻结规则可重放 |
| 11 | Store 非产品/通用商业页负例(cable/battery/Order Fee) | product 维持 commercial;不进入任何设备资格集 |
| 12 | 全过滤生成(标记耗尽) | 返回真实不足语义(product/comparison_evidence_insufficient),**绝不** service_unavailable |

验证方式:§2/§3/§8-9 用本地纯函数重放;§1-6/12 用隔离库集成测试(假 LLM 流可控注入 B/C 型);§10-11 用迁移 dry-run 报告断言;上线后生产只读冒烟(新 Gate 授权)。

## 9. REGRESSION CONSTRAINTS / 数据与生产影响(§8)

- #5 单产品边界**零削弱**:exact 模式检索/校验/文案路径逐字保持;资格集语义(含 aitoolstack 平台桶)不变;
- 单目标问答(现生产行为)零回归;`empty_generation` kind 名保留(消费方兼容),仅增 payload reason;
- 旧客户端:新消息键走既有 token/error 通道,降级安全;
- **数据迁移**:仅商店设备页 product 属性原位更新(≤40 chunk 量级,dry-run 定稿精确清单),**零 re-embed/零 reindex/零 schema 变更**;
- **发布形态**:代码发布(backend)+ 一次小规模元数据迁移(先于/独立于代码皆可——旧代码对新标签向后兼容:设备 slug 本就是 taxonomy 合法值);
- 迁移与 #5 同纪律:dry-run 默认、人工核对清单、`--apply` 显式。

## 10. PRODUCT DECISIONS REQUIRED

**无阻塞决策(READY)**。记录一项**可选后续**决策供 Product Owner 择机裁定(不属本 Issue 范围):
- **PD-1 商店配件设备归属**:配件页(标题含单一宿主设备,如 "M12 Lens for NE301")是否应继承宿主设备 slug?推荐默认:V1 不重标(维持商业/广品线桶);若未来要更精细的设备域检索可重访。

---

## 返回字段

```
STATUS                            = DISCOVERY PASS
BASELINE                          = v1.0.0 / 0e6a8a3bb72932b26fcf500954aacfe109373133(= origin/main)
PRODUCTION_REPRO                  = 复用 v1.0.0 部署门 F1 存证(SSE/日志/trace:2/2 empty_generation,30s 零 content delta,sources=3 含 store/ne301(aitoolstack));本门零重放零写入
ROOT_CAUSE                        = RC1 comparison 无 per-target 检索/配额(主);RC2 woo 类别映射先命中先胜+广品线前置致设备页误标 aitoolstack;RC3 PC-01 把 B/C/D 混同 service_unavailable;RC4(开放)v4-flash 零内容 provider 侧机制
CURRENT_SINGLE_TARGET_ASSUMPTIONS = intent 无 comparison 语义;检索单融合列表无归属;引用校验无 per-claim 归属;空生成单键;AskRequest.product 单串
COMPARISON_PRODUCT_CONTRACT       = §3(requested_targets 权威;分别可归属;共享可用;四不可;单侧/双侧不足语义)
EVIDENCE_ATTRIBUTION_CONTRACT     = §4(V1 检索层结构保证+prompt 契约;不做逐句机器归属;缺失⇒显式不足禁静默降级)
STORE_METADATA_FINDINGS           = §5 审计:101 chunk=aitoolstack 57+commercial 44;57 内含整设备页(NE301 相机×5ch/NE503×4/NE101×7+/NG4500×7);根因=_CATEGORY_MAP 排序先命中先胜(docstring 自证)
STORE_IDENTITY_CONTRACT           = §5 方案 B 双正交维度;V1 仅无歧义设备页派生(name+slug→taxonomy 首个 targetable 设备 slug),失败不猜;配件 V1 不重标
EMPTY_GENERATION_FINDINGS         = 校验器只剔标记不改散文(C 型全滤架构不可达);PC-01=full_answer.strip() 空;deepseek client 只读 delta.content(reasoning_content 丢弃);provider 异常走 provider_error → F1 确证 type B
EMPTY_GENERATION_CONTRACT         = §6 A/B 保持 service_unavailable(B 增 reason 观测字段);C 映射产品不足键;D 新前置检查→新键 comparison_evidence_insufficient(复用阶段⑯冻结键架构)
ACCEPTANCE_MATRIX                 = §8 十二例(含验证方式)
CHANGE_BOUNDARY                   = rag.py/search.py/woocommerce.py/user_messages.py + 新迁移脚本;citation.py 无必须变更;schema 零变更
DATA_MIGRATION_REQUIREMENT        = 是:商店设备页 product 属性原位更新(≤40 chunk,dry-run 定稿),零 re-embed
PRODUCTION_IMPACT                 = 代码发布 + 一次小规模元数据迁移(旧代码对新标签向后兼容,顺序无关);无 reindex/rebuild
REGRESSION_CONSTRAINTS            = #5 exact 路径逐字保持;资格集语义不变;empty_generation kind 名保留;单目标问答零回归
PRODUCT_DECISIONS_REQUIRED        = 无阻塞;可选 PD-1(商店配件是否继承宿主设备身份,非本 Issue 范围)
READY_STATUS                      = READY
REPORT_PATH                       = docs/implementation/CAMTHINK_ISSUE_19_COMPARISON_CORRECTNESS_DISCOVERY_2026-09-04.md
REPORT_COMMIT                     = <见 docs 仓提交>
PRODUCTION_MUTATIONS              = NONE
```

**STOP。未实现修复;未部署;未变更生产。**
