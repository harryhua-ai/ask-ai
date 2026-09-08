# I-002 / INC-4 — Deterministic Evidence Planning 执行报告

> **角色**:Engineering Executor | **模式**:IMPLEMENT / TEST / VERIFY(零生产部署、零生产变更、零 Benchmark 变更)
> **日期**:2026-09-08 | **状态**:CANDIDATE READY

---

## 1. Baseline

- **基线 SHA**:`origin/main = 203eec5a0712cbcaa8381141ef01f99c7c5c856e`(执行前 fetch)
- **契约在场核验**:`backend/pipeline/task_understanding.py`(INC-3,末次变更 820734f)✅;`backend/evidence_meta.py`(INC-2a)✅;`backend/retrieval/search.py` evidence_* 读回 18 处引用 ✅ —— 与接受契约无实质分歧,未触发 BLOCKED
- **执行树**:`.worktrees/inc4-evidence-planning`(branch `worktree-exec/inc4-evidence-planning`,基于 origin/main)

## 2. RED 证据(实现前建立)

1. **模块缺失**:`tests/pipeline/test_inc4_evidence_planning.py` 收集期
   `ModuleNotFoundError: No module named 'backend.pipeline.evidence_planning'` —— 证据规划层不存在;
2. **字段缺失**(对基线代码直接取证):
   `TaskUnderstanding` 字段表 `[category, reason, confidence, interaction_mode, extracted_query, rewritten_query, fallback_used, parse_ok]` 无 `evidence_intent`;
   `TaskUnderstanding(evidence_intent='factual')` → `TypeError: unexpected keyword argument`。
   ⇒ 事实任务与推荐任务**今天无法产生不同的结构化证据需求**(契约缺口实证)。

## 3. INC-3 Additive Amendment 实现(evidence_intent)

`backend/pipeline/task_understanding.py`(同一 `understand_task` 调用,零新增 LLM):

- 词表:`EVIDENCE_INTENT_FACTUAL="factual"` / `EVIDENCE_INTENT_RECOMMENDATION="recommendation"` / `EVIDENCE_INTENTS`;
- **不是第五个 legacy category**(`VALID_CATEGORIES` 不变,测试钉住);interaction_mode 语义零触碰;产品身份权威零移动;
- prompt:导语「四件事→五件事」;新增「第五步:证据意图判定」(中英文语义等价描述,禁关键词启发式为主分类器;非 product 类一律 factual);JSON schema 追加 `"evidence_intent": "factual|recommendation"`;
- 解析器(**向后兼容关键裁决**):
  - 字段**缺失** = legacy INC-3 合法兼容形态 → `factual`,**不改 `fallback_used`**(避免把全部 INC-3 形态响应打上退化噪声,且不改既有黄金测试);
  - 字段**非法值**(如 `"design"`)→ `factual` + `fallback_used=True`(可观测);
  - **整体畸形/LLM 异常** → 总回退(`_total_fallback`)携带缺省 `factual`,`parse_ok=False`;单次调用,零重试(`llm.generate.await_count == 1` 断言)。

## 4. EvidenceSlot / EvidencePlan 最终接口

`backend/pipeline/evidence_planning.py`(新模块,纯函数,零 IO/零 LLM):

```python
EvidenceSlot:  role: PRODUCT_SPEC|SOLUTION_GUIDE|CASE_EVIDENCE|STORE_OFFICIAL
               product_scope: tuple[str,...](空=继承 resolver 解析域)
               required: bool(v1=trace/coverage 信号,不改既有拒答路径)
               citation_requirement: CITABLE_REQUIRED|BACKGROUND_ALLOWED
EvidencePlan:  slots: tuple[EvidenceSlot,...]
               evidence_intent / category / interaction_mode /
               resolution_mode / resolution_targets   # bounded trace attribution
               fallback_used: bool                    # 透传理解回退态
derive_evidence_plan(understanding, resolution) -> EvidencePlan
```

无 speculative 字段(min_coverage/authority_requirement/temporality_requirement/检索参数均未加——frozen 契约无需修订即满足,未触发 CONTRACT AMENDMENT REQUIRED)。frozen+可哈希,可安全进 trace。

## 5. 确定性映射表(实现即契约)

| 输入(既有事实) | slots | 语义 |
|---|---|---|
| `interaction_mode ∈ {clarification_required, capability_orientation, off_topic}` | **零槽位** | 合法交互,不产证据检索计划(先于一切 intent/category 判定) |
| resolver `MODE_COMPARISON` | 每 target 一条 `PRODUCT_SPEC(required, CITABLE, scope=(target,))` | 语义投影;既有比较管线执行**冻结不触** |
| `category=support` | `CASE_EVIDENCE(optional, BACKGROUND_ALLOWED)` + `PRODUCT_SPEC(optional, CITABLE)` | 案例证据不因被选而公开可引用 |
| `category=commercial` | `STORE_OFFICIAL(required, CITABLE)` + `PRODUCT_SPEC(optional)` | Store 缺失可观察,不静默以 wiki 替代 |
| `product` + `evidence_intent=recommendation` | `SOLUTION_GUIDE(required, CITABLE)` + `PRODUCT_SPEC(optional)` | 方案/选型目标证据 |
| `product` + `evidence_intent=factual` | `PRODUCT_SPEC(required, CITABLE)` | 普通事实查询 |
| 未知/畸形 category | 单 `PRODUCT_SPEC(required)` | fail-open,检索可用性保持 |

**零检索模式检查先于 intent 有效性**:畸形输入不得把澄清/导向任务变成检索计划。

## 6. RAG 集成与 Trace(answer/stream 同位)

- `rag.py` 双路径在**三个交互短路之后**、检索分支之前同位接线:
  `plan = derive_evidence_plan(understanding, resolution)`;`stages["plan"] = {evidence_intent, slots[{role, product_scope, required, citation_requirement}], derived_from{category, interaction_mode, resolution_mode, resolution_targets}, fallback_used}` —— 有界、无思维链;
- **stream 特有修复**:stream 终态(成功/不足拒绝/比较拒绝/CIT 耗尽)的 `stages` 为内联选择性重建,共享 dict 的 plan 键不自动可见 → 三处内联补 `"plan": stages.get("plan")`(2337/2423/2732 行),保证 J parity;
- 检索执行行为零改变(HybridSearcher/RRF/reranker/pruner/citation builder/generation 零触碰);INC-5 选择/组合未实现(契约边界)。

## 7. 验收矩阵 A-L → 测试证据

`tests/pipeline/test_inc4_evidence_planning.py`(22 测,全绿):

| 矩阵 | 测试 | 结果 |
|---|---|---|
| A factual | `test_a_factual_lookup_product_spec_required` | ✅ PRODUCT_SPEC required+CITABLE,scope 继承 |
| B recommendation | `test_b_recommendation_solution_guide_plus_support` | ✅ SOLUTION_GUIDE required + PRODUCT_SPEC 支撑 |
| C troubleshooting | `test_c_support_case_evidence_background_not_citable` | ✅ CASE_EVIDENCE BACKGROUND_ALLOWED(不公开可引用) |
| D commercial | `test_d_commercial_store_official_required` | ✅ STORE_OFFICIAL required |
| E comparison | `test_e_comparison_per_target_spec_from_resolver` + 既有比较套件 | ✅ per-target 语义;执行管线零回归 |
| F/G/H 零检索 | `test_fgh_zero_retrieval_modes_have_no_plan`(参数化) | ✅ 三模式零槽位 |
| I 畸形 fail-open | `test_i_degraded_understanding_falls_open_to_factual_plan` / `test_i_unknown_category_never_raises` / `test_i_pipeline_…`(管线级) | ✅ factual 计划,零重试 |
| J parity | `test_j_answer_stream_plan_parity` | ✅ answer/stream `stages.plan` 逐字段相等 |
| K resolver 权威 | `test_k_plan_never_reads_product_identity_from_understanding` | ✅ 身份仅来自 resolution(结构断言:理解无产品字段) |
| L 零增量调用 | `test_amendment_total_fallback_is_factual_no_retry`(await_count==1)、`test_l_zero_incremental_llm_calls_in_pipeline`(总 generate==2=理解+生成)、`test_l_planner_is_local_and_llm_free`(签名无 llm) | ✅ |

## 8. LLM 调用计数证明

- 单元级:`understand_task` 恰 1 次 `generate(task="task_understanding")`(异常路径 `await_count==1` 不重试);
- 管线级:检索成功路径 `llm.generate.call_args_list` 总数 == **2**(1 理解 + 1 生成)——与 INC-3 基线相同,**零增量**;
- 流路径生成走 `llm.stream`(既有),规划器无 LLM/IO(签名级断言)。

## 9. Answer/Stream Parity 证明

`test_j_answer_stream_plan_parity`:同 payload(standard+recommendation)+ 同 page_context,`r1.trace_payload["stages"]["plan"] == complete["trace_payload"]["stages"]["plan"]` 逐字段相等,且 stream 侧 SOLUTION_GUIDE required 在场。接线同位(两路径同一推导调用+同一 trace 形态)。

## 10. 比较回归证明

- `test_comparison_evidence_correctness.py` + `test_issue19_comparison.py` 全绿(执行管线字节级行为不变:plan 仅为语义投影,`_comparison_evidence_pipeline`/配额/聚焦重排零触碰);
- `test_product_resolver.py` 全绿(resolver 权威不受影响)。

## 11. 变更文件

| 文件 | 变更 |
|---|---|
| `backend/pipeline/task_understanding.py` | +evidence_intent 词表/prompt 第五步+schema/解析(缺失兼容·非法回退)/dataclass 字段(+36 −2 行级) |
| `backend/pipeline/evidence_planning.py` | **新增**:EvidenceSlot/EvidencePlan/derive_evidence_plan(冻结映射表) |
| `backend/pipeline/rag.py` | +import;answer/stream 双路径 plan 接线+trace;stream 三处内联 stages 补 plan 键(+48) |
| `tests/pipeline/test_inc4_evidence_planning.py` | **新增**:22 契约测试(A-L 全覆盖) |

## 12. 测试结果

- 新契约测试:22/22 ✅(black 重排后复跑亦绿);
- focused 邻域回归:task_understanding / inc3_context_amendment / product_resolver / comparison×2 / inc1_observability / inc1_evidence_lineage / evidence_ingest_propagation / rag_trace / rag_reliability / multilingual_gate / intent / citation_integrity —— **175/175 ✅**(唯一历史波及=INC-3 黄金用例,经向后兼容裁决后原断言零修改通过);
- **全量离线套件 ×2 轮:`1876 passed, 6 skipped, 0 failed`(48.46s / 46.92s)**,环境 `HF_HUB_OFFLINE=1` + `TEST_DATABASE_URL=…ask_ai_test`;
- black 仅作用于 4 个变更文件,未波及无关文件。

## 13. 敏感度/时效边界(契约遵从声明)

- **SENSITIVITY_POLICY_CHANGED = NO**:未实现 unknown fail-closed;unknown 不抑制任何证据;internal 可见性由既有检索/可见性语义保护;personal-data 保留无生产者;无 PII 分类、无脱敏、零重嵌入、无 Admin 敏感度配置(INC-2b DEFERRED);
- **TEMPORALITY_AMENDMENT = NO**:INC-2a 词表与派生零触碰;STORE_OFFICIAL 仅为证据规划角色,**不声称产生 chunk 级新鲜度保证**。

## 14. 剩余风险

1. plan 目前为**可观测语义层**:检索执行尚未消费 slot(最小 role→检索映射留待 INC-5 首个消费点);本增量契约即如此划界;
2. `evidence_intent` 依赖模型遵守新 JSON 字段;缺失=兼容不罚、非法才罚——若生产观测缺失率高,可后续把「缺失」升格为可观测信号(需修订本报告 §3 裁决);
3. comparison 路径 plan 与既有配额管线并存,INC-5 接管选择时须保持本次冻结的零回归基线(T-COMPARISON 套件守卫);
4. stream 终态内联 stages 重建模式(本次补 3 处)是既有结构的重复税——未来 INC-5 接线时建议收敛为共享构造,降低 parity 漂移面。

## 15. Final Candidate

- **FINAL_CANDIDATE = `84f5f2b`**(branch `worktree-exec/inc4-evidence-planning`,已推 origin;基线 `203eec5` 线性后代,4 文件 +756 −2)
- 报告:本文档(docs 仓 + 分支内 `docs/engineering/tasks/I002-INC4-EVIDENCE-PLANNING-execution.md`)
