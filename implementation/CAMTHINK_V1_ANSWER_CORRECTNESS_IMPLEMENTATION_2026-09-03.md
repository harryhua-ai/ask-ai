# CamThink V1 Answer Correctness / Product Boundary — Implementation 报告

- **日期**: 2026-09-03
- **Issue**: harryhua-ai/ask-ai #5(Discovery 报告 = 本仓 `CAMTHINK_V1_ANSWER_CORRECTNESS_PRODUCT_BOUNDARY_DISCOVERY_2026-09-03.md`,Planner Review 已过)
- **执行模式**: SINGLE EXECUTOR
- **FINAL_COMMIT**: ask-ai `7123f73` @ `origin/worktree-exec/answer-correctness-20260903`(基线 main `1d6f6b5`,**未合 main**)
- **WORKTREE**: `.worktrees/answer-correctness`
- **CODE_MUTATION**: 实现 commit 内(见 FINAL_COMMIT)
- **PRODUCTION_MUTATIONS**: **NONE**(零部署/零生产配置/零生产迁移/零生产 Weaviate 写入/零 sync 触发;迁移工具仅本地交付,默认 dry-run)

---

## 1. Executive Summary

按 Planner 冻结契约 12 条全部落地,状态 **CANDIDATE_READY**:

- **Canonical Product Identity**:`config/product_taxonomy.yaml`(数据权威)+ `backend/product_taxonomy.py`(加载/解析/推导/资格集/边界提示)。5 产品(NE101/NE301/NE302/NE503/NG4500)+ 3 平台(NeoMind/NeoRuntime/AIToolStack)+ shared/support/store 桶 + 9 条历史标签 canonicalize(`AI-ToolStack`→aitoolstack、`meta-hailo-os`→ne503、`neomind-dashboard/devicetype/extensions`→neomind、`neoruntime-apps/sdks`→neoruntime、`online-store/accessories`→commercial)。业务代码零产品名 if/else。
- **Target Product Resolution**(`backend/pipeline/product_resolver.py`):explicit hint → 查询显式型号 → page_context → 会话回指(仅指代词在场)→ ambiguous(文本澄清)/unsupported;零 LLM、确定性、低置信度不猜。`AskRequest.product` 可选字段(消毒规则同 page_context,向后兼容)。
- **Document Product Derivation**(ingest.py):`_build_props` 与 PG 账本统一走 `derive_product()`——wiki 系列目录规则、官网产品页 URL 规则(生产 366 chunk 全量 URL 清单实证)、woo category canonicalize、不可判定=unknown;ingest 与迁移共用同一代码路径。
- **Retrieval Boundary**(search.py + rag.py):三路检索(hybrid/符号/boost 桶)新增 `product_labels` = any_of(equal) 硬过滤(TEXT 标量沿用既有 equal+any_of 约定,规避 contains_any 分词陷阱);fused 兜底前二次防御过滤——闸门缺陷也不得让 sibling 回流;support 桶同样受资格约束(不得成为跨产品后门);channel_visibility 原样保留。
- **Generation Boundary**:上下文每条可引用资料带 `产品: {展示名}` 归属行;system 追加产品边界冻结规则(单目标:严禁 sibling 规格/接口/步骤/兼容性/能力冒充 + 不足即明示;比较:按产品分节归属 + 单侧不足不得填位)。
- **CIT-03**(citation.py):`CitationStreamFilter`/`validate_citations` 增加 `source_products + eligible_slugs`——编号所属产品不在资格集 → 剔除标记 + `ineligible_product_dropped` 记账;只剔标记不改写正文;参数缺省时与 CIT-01/02 基线逐字节一致。
- **Structured Insufficient Evidence**(user_messages + 事件):complete 事件新增机器可读 `result_key`:`answered` / `no_evidence` / `product_ambiguous` / `product_evidence_insufficient`(文案携带目标产品展示名)/ `product_not_supported` / `off_topic` / `smalltalk` / `override`;result_key 同步写入 Trace.config_snapshot(零表结构变更);既有 no-evidence 拒答文案逐字未动。
- **Migration Tooling**(`backend/services/product_migration.py` + `scripts/migrate_product_metadata.py`):plan(dry-run 零写入)/ apply(**原位 property update,不触向量、零 re-embed、零 collection 重建**);source-scoped = source_id 首段客户端精确匹配(禁 TEXT 分词过滤,P0-A 教训);报告逐源 old→new 计数、unknown 计数+样本列出(上限 20 条)、无静默丢文档;**脚本默认 dry-run,`--apply` 才写**。
- **Eval Matrix**:A–K 11 场景 ID 一一对应的确定性测试(`test_product_boundary_eval_matrix.py`),E/A/C 为发布阻断项。

## 2. 关键设计裁决(Planner 复核锚点)

1. **迁移前 eligibility 展开**:检索资格标签集 = canonical slugs + 历史标签(meta-hailo-os 等)。迁移未跑时 NE503 问题仍可命中 meta-hailo-os 标签 chunk(不过度拒答);wiki 混合标签**故意不展开**——宁诚实拒答不冒充(`test_premigration_wiki_label_excluded_over_refusal_not_contamination`)。迁移后自然收敛为 canonical 标签。
2. **页面上下文优先级裁决**:`product_resolver.py` 实现顺序为 explicit hint → **查询显式型号** → page_context → 会话回指。与契约字面顺序的偏差(查询型号排在 page_context 前)由两点依据:①用户亲口在问题里点名的产品属于「explicit user product」语义;②本系统 page_context 是 MSW 冻结的**非信任元数据**(G008),不能覆写用户明示文本。已留测试锚定(`test_query_mention_outranks_page_context`)。
3. **会话回指仅限指代词**:无指代的历史产品不收窄(避免「你们公司在哪」被历史产品误拒);指代 + 多历史产品冲突 = ambiguous。
4. **capture/附件轮豁免**:lead capture 轮不启用产品边界(联系方式确认必须生成,与 off_topic 捕获豁免同构);clarify/unsupported 短路发生在意图分类前(省一次 LLM)。
5. **历史标签兼作查询别名**(仅可作目标的 slug):用户会直接输入仓库名 `meta-hailo-os`;映射在 taxonomy 冻结,非猜测。
6. **CIT-03 的 V1 边界**:不做自然语言定理证明(契约 §7);两层执行——①rag 在拼上下文前对候选做资格出清(不变量:编号集合恒合格)②流式/终验对标记做资格校验(防御纵深 + 记账)。

## 3. Eval / Regression 结果(全绿实证)

| 套件 | 结果 |
|---|---|
| 后端全量 `pytest tests/`(HF_HUB_OFFLINE=1 + TEST_DATABASE_URL=ask_ai_test) | **1252 passed, 6 skipped**(34.8s;基线 1112 + 本次新增 ~140) |
| 新增:taxonomy 56 / resolver 14 / derivation 4 / message keys 6 / search product_labels 5 / CIT-03 12 / 检索+生成边界 15 / eval 矩阵 A–K 23 例(11 场景 ID) / 迁移 6 | 全绿(各模块 RED→GREEN) |
| widget vitest | **72 passed(8 files)** |
| ruff(全部新增/重写文件) | 0 error(仓库存量文件不在此列) |
| 迁移 CLI 冒烟 | `--help`/语法通过;dry-run 为默认路径 |

既有测试数据修正(6 处,断言意图全部保留,仅语料产品标签按迁移后语义对齐):`test_rag.py` 4 处、`test_rag_page_context.py` 1 处(DocA 改共享平台标签以保留软加分翻转断言)、`test_rag_trust_boundary.py` 1 处、`test_unified_v1_gate.py` PAGE_CONTEXT fixture 页面产品与语料对齐 + G003 同步断言、`test_accepted_changes_integration_gate.py` G005/G008 查询产品与语料对齐。**这些不是放宽断言,而是旧语料在无产品边界时代遗留的标签错位**;新契约下它们恰好构成边界正确生效的证据。

## 4. Production Acceptance Checklist(未执行;未来 Gate 顺序)

> 前置:GPU 修复窗口后补灌 meta-hailo-os / neoruntime-sdks(NE503 第 2 层证据真实化)。

1. **Gate-1 taxonomy/config 部署**:`config/product_taxonomy.yaml` 随镜像进生产(PD-1 内容如需调整只改此文件)。
2. **Gate-2 metadata migration(dry-run → apply)**:
   - `migrate_product_metadata.py --source-ids wiki-documents-local,website-camthink --json report.json`(dry-run,零写入);
   - 人工核对 old→new 计数与 unknown 明细;unknown 预期 ≈ wiki `.image-upload` 工具文档 + 官网非产品页(全部 366+3891 内逐条入账);
   - 确认后同源 `--apply`(原位属性更新;可在旧服务运行期执行——旧服务不消费 product,零影响窗口)。
3. **Gate-3 service release**:backend(+sync-executor/sync-cron 同 sha,CI 镜像含 config/)升级;此后新入库文档自动带 canonical product。
4. **Gate-4 scoped corpus metadata/reindex**:仅当 Gate-2 报告存在缺口时对指定源重灌(既有幂等通道);本方案默认**不需要 re-embed**。
5. **Gate-5 11-case smoke**:A–K 场景真栈冒烟(重点 E:NE503 问题在 NE301 强证据在场时必须 insufficient)。
6. **Gate-6 93-scenario regression**:09-01 验收基线重跑对照;量化「正确收窄」vs「误伤」,误伤清单回灌 taxonomy 共享声明。
7. **Gate-7 production observation**:trace `product_scope` stage / `result_key` 分布 / `ineligible_product_dropped` / 拒答率对比窗。
8. **Gate-8 FINAL ACCEPTANCE**:Planner 按上述证据终验。

**半态红线(Discovery §21.3 继承)**:Gate-2 完成前不得发布开启边界的新服务(闸门开、推导没灌 = wiki/website 全域不可命中的过拒答窗口)。迁移在旧服务运行期先行是安全的。

## 5. Known Limitations(诚实边界)

1. **NeoMind/AIToolStack 的 applies_to(全系列)**与 **neoruntime→[ne503]** 为 corpus 结构推定 + Discovery 草案基线,taxonomy 数据可随时修正(不涉代码)。
2. **官网非产品页(blog/campaign)与 wiki `.image-upload` 工具文档**推导为 unknown → 产品问题下不可用;它们本就不是产品事实来源。
3. **产品页上的泛问**(如站点上下文确立 NE503 后问「你们公司在哪」)会被收窄后拒答——off_topic 意图拦截了大部分;残余为诚实过拒,已知取舍。
4. **CIT-03 是 product-boundary semantic guard**,不证明语义等价(契约 §7 明示);非数值主张的最终防线是 prompt 冻结规则 + eval。
5. **product_labels 的 TEXT equal 过滤**沿用 Weaviate 分词语义;当前标签集内唯一碰撞(neoruntime 匹配 neoruntime-apps 等)坍缩向同 canonical 实体,无害;迁移完成后标签面收敛。
6. **Clarify 为文本轮**(complete is_answered=false + 文案),无结构化候选按钮 UI(PD-2 拍板项)。

## 6. 交付物清单

**ask-ai @ `7123f73`(origin/worktree-exec/answer-correctness-20260903)**

| 类别 | 文件 |
|---|---|
| 配置 | `config/product_taxonomy.yaml`(新增) |
| 新模块 | `backend/product_taxonomy.py`、`backend/pipeline/product_resolver.py`、`backend/services/product_migration.py` |
| 修改 | `backend/pipeline/rag.py`(解析/闸门/防御过滤/不足语义/边界 prompt/result_key)、`backend/pipeline/citation.py`(CIT-03 + 归属行)、`backend/retrieval/search.py`(product_labels 三路)、`backend/pipeline/ingest.py`(文档级推导)、`backend/utils/user_messages.py`(3 新键 + 占位填充)、`backend/api/schemas.py`(`product` 字段)、`backend/api/routes.py`(product_hint 透传) |
| 脚本 | `scripts/migrate_product_metadata.py`(默认 dry-run) |
| 测试(新增 9 文件) | taxonomy 56 / resolver 14 / derivation 4 / message keys 6 / product_labels 5 / CIT-03 12 / 边界 15 / eval 矩阵 23 / 迁移 6 |
| 测试(对齐 6 文件) | 见 §3 说明 |

---

*STATUS: CANDIDATE_READY。未合 main、未部署、未触生产。等待 Planner 独立 FINAL REVIEW。*
