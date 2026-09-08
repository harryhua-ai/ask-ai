# INC-3 任务理解合并 — 执行报告

- 契约:INC-3 Frozen Implementation Contract(Task Understanding Consolidation,FROZEN/AUTHORIZED)
- 基线核验:BASELINE_COMMIT = **48b94809287028fb2beef6c3a152feb5ab984915** 存在 ✓(INC-1 a44c61c → INC-2a cdbb234/48b9480 血统完整);从其建立隔离分支,无差异
- 实现分支:ask-ai 主仓 `task/inc3-task-understanding`(已推 origin)
- 自评:**CANDIDATE READY**(待 Agent A 独立审查终验)

---

## 1. STATUS / 提交

- STATUS = **CANDIDATE READY**
- BASELINE_COMMIT = `48b94809287028fb2beef6c3a152feb5ab984915`
- FINAL_COMMIT = `3eb734c`(实现+测试单提交;前序历史未改写;未合并未部署)

## 2. CHANGED_FILES

| 文件 | 变更 |
|---|---|
| `backend/pipeline/task_understanding.py`(新) | `understand_task` 单次结构化调用 + `TaskUnderstanding` + 逐字段 fail-open 校验 + mode↔category 双向一致性修复 |
| `backend/pipeline/rag.py` | answer/stream 两路径接线:单调用替代 intent→extract→rewrite;legacy stages 键派生;`stages.understanding`;clarify/orientation 路由分支(信封+SSE);capture 轮 trace 脱敏;timing 字段更名 |
| `backend/utils/user_messages.py` | 新增 `clarification_required` / `capability_orientation` 冻结文案(zh/en) |
| `config/llm_providers.yaml` | `task_understanding` 独立路由链(deepseek,model=null,非生产默认路径) |
| `backend/pipeline/intent.py` / `query_rewrite.py` | 保留为兼容模块(主路径不再调用;`VALID_CATEGORIES` 仍为 legacy 枚举权威) |
| 测试 | 新 `tests/pipeline/test_task_understanding.py`(21 测);harness 更新 7 文件(task 派发→task_understanding) |

## 3. FINAL_CALL_GRAPH

`start_capture → detect_language/resolve_answer_language(确定性,不变) → override(命中 0 调用)→ social(命中 0 调用)→ Product Resolver(权威不变;AMBIGUOUS/UNSUPPORTED 短路 0 调用)→ **understand_task(单次,task="task_understanding")** → off_topic 门(mode=off_topic 且非 capture/附件豁免)→ clarification_required 路由(澄清信封)→ capability_orientation 路由(导向信封)→ effective_min(不变)→ 检索(extracted=符号/桶路;search_query=hybrid/重排路;比较路径输入不变)→ 后续管线全不变`

## 4. STRUCTURED_UNDERSTANDING_SCHEMA

```json
{"category": "commercial|product|support|off_topic",
 "reason": "有界诊断(≤300 字符)",
 "confidence": 0.0-1.0|null,
 "interaction_mode": "standard|clarification_required|capability_orientation|off_topic",
 "extracted_query": "核心检索问题(用户原语言)",
 "rewritten_query": "自包含查询(用户原语言)"}
```

## 5. INTERACTION_MODE_SEMANTICS

- **standard**:正常 product/commercial/support → 既有检索/作答管线(零行为变化);
- **clarification_required**(#26):大概率属域内但缺关键信息且上下文不可安全补全 → 冻结文案澄清(只问最少必要信息,不猜产品,不以拒答开场);result_key=`clarification_required`,trace type=`task_clarify`,is_answered=False;
- **capability_orientation**(#27):助手能力/范围/用法询问 → welcome→orient→invite 冻结文案(通用平台措辞,无厂商硬编码,如实描述运行时既有能力);result_key=`capability_orientation`,trace type=`capability_orientation`,is_answered=True;
- **off_topic**:仅确证无关 → 既有友好边界不变。
前三者 **绝不** 表现为 off_topic/reject_short/无关闲聊(§16 Admin/trace 真相)。

## 6. LEGACY_INTENT_COMPATIBILITY

四枚举不变;兼容映射(契约 §3):clarification→最贴近域内类(不可区分 fail-open product);capability→product;off_topic→off_topic。下游消费者(off_topic 门/effective_min/boost 桶/lead 门/intent_styles/envelope/intent_tag 分析)经 `IntentResult` 兼容垫片零改动;新路由由 interaction_mode 驱动。mode↔category 双向一致性修复杜绝脏组合。

## 7. FAILURE_FALLBACK

- 整体失败/不可解析 → `product + confidence=0 + reason=有界诊断 + standard + extracted=rewritten=原 query` + `fallback_used=True/parse_ok=False`;**绝不 off_topic**;
- 逐字段非法 → category→product / mode→由 category 推导 / confidence→None / extracted→原 query / rewritten→extracted,`fallback_used=True`;
- 无合格历史(None 或 len<2,与旧 rewrite guard 同判据)→ **强制 rewritten==extracted**(A2,不依赖模型);
- 无重试调用(§6);Router 链内 failover 语义不变;全部回退可观测(stages.understanding.fallback_used)。

## 8. PRODUCT_BOUNDARY_COMPATIBILITY

顺序不变(override/social → resolver → 合并理解);resolver 权威不变;AMBIGUOUS/UNSUPPORTED 短路不变;合并调用输入仅 query+history,不输出产品目标,不覆盖 resolver 决策(§4)。

## 9. ISSUE_26_RESULT / ISSUE_27_RESULT

- **#26**:生产 repro `What is included in the box?` → interaction_mode=clarification_required → 澄清信封(`task_clarify`),非 off_topic 拒答;可安全解析上下文时继续走既有 resolver 路径(既有 trust-boundary 测试保持绿);真无关仍 off_topic(专项测试)。**无 "Which product?" 万能循环、无 box 短语规则、无产品猜测**。
- **#27**:`你会干什么` + `你可以帮我什么`/`怎么用你`/`What can you do?`/`How can you help me?`(语义类,parametrize 测试)→ capability_orientation;intent=product;欢迎/引导信封;文案通用平台化(无 CamThink 硬编码、无单短语补丁、无虚构能力)。

## 10. OBSERVABILITY

- llm_calls:单事件 `task="task_understanding"`(provider/model/latency/tokens/thinking=disabled/success 全保留,INC-1 遥测语义不变);
- `stages.understanding = {ms, interaction_mode, category, confidence, fallback_used, parse_ok, one_call: true}`(全载荷可达);
- legacy 兼容键:`stages.intent{ms,category,reason}` 与 `stages.rewrite{ms,extract_ms=None,rewrite_ms=None,extracted,rewritten,consolidated:true}` 由单次结果派生——**不伪装三段独立计时**(§15);
- 新信封字段 `interaction_mode`(SSE complete)+ result_key 区分真相(§16);capture 轮 extracted/rewritten 在 trace 中脱敏(PII-hard,检索仍用真实查询);
- 历史Trace 不可变、无需重写(§15)。

## 11. ROUTING

`config/llm_providers.yaml` 新增 `task_understanding` 独立链(deepseek/model=null),与 generation/intent/query_rewrite 平行;registry fallback 语义不变(未配置链→generation 链+fallback 标记);配置断言测试在位;生产路由未触碰。

## 12. CALL_COUNT_BEFORE_AFTER / PERFORMANCE_EVIDENCE

| 路径 | BEFORE | AFTER |
|---|---|---|
| 常规多轮 | 3 串行 | **1** |
| 首轮/无历史 | 2 | **1** |
| override/social/product-boundary 短路 | 0 | 0(不变) |

**受控真实模型对照**(本地非生产,deepseek,3 代表用例:单轮 product/单轮 commercial/多轮续航追问):

```
OLD(3 调用串行): 1.46s + 1.30s + 1.94s = 4.70s
NEW(1 调用):      0.92s + 0.95s + 1.73s = 3.60s
```

多轮用例「那续航呢」:OLD intent 对孤立 query 误判 **off_topic**(恰为 #26 类假拒答的活实例);NEW 看到历史 → category=product + rewritten=「NE301 AI相机的续航时间是多少？」(自包含)——**合并本身结构性修复了一类假拒答**。单轮两例 category/extracted 语义等价。以上为实测值,无推算毫秒。

## 13. TESTS

```
HF_HUB_OFFLINE=1 .venv/bin/python -m pytest tests/pipeline/test_task_understanding.py -q
  → 21 passed(黄金集/逐字段回退/整体失败/#26/#27/A2 强制/一致性修复/capture 豁免/单调用/trace 兼容/语言保持/路由链配置)

HF_HUB_OFFLINE=1 .venv/bin/python -m pytest tests/pipeline -q → 546 passed
HF_HUB_OFFLINE=1 .venv/bin/python -m pytest tests/retrieval tests/llm tests/scripts tests/api -q → 全绿
HF_HUB_OFFLINE=1 .venv/bin/python -m pytest tests -q --ignore=tests/e2e
  → 1841 passed / 4 skipped / 0 failed(51.2s;4 skip 均为既有环境态:共享库隔离×1+local_git 注册移除×3,基线即有)
```

harness 更新说明:7 个测试文件的 task 分发 mock 由 intent/query_rewrite 双任务改为 task_understanding 单任务(输出含 extracted/rewritten);INC-1 观测测试断言更新为合并语义(extract_ms/rewrite_ms=None + consolidated + one_call)——非放松,而是 §15「不伪装独立计时」的如实化。

## 14. ACCEPTANCE(A1-A24)

A1 ✓(单调用,mock 计数断言)· A2 ✓(强制等价+测试)· A3 ✓(短路 0 调用保持)· A4 ✓(枚举未动)· A5 ✓(四模式)· A6 ✓(#26 repro 澄清)· A7 ✓(context 可解继续/不可解澄清)· A8 ✓(真无关仍拒)· A9 ✓(#27 ZH/EN 导向)· A10 ✓(通用平台文案+语义类覆盖)· A11 ✓(fail-open 矩阵)· A12 ✓(extracted/rewritten 消费侧不变+语言保持)· A13 ✓(resolver 权威/顺序不变)· A14 ✓(比较/隔离回归绿)· A15 ✓(附件/capture/lead 兼容+trace 脱敏)· A16 ✓(answer/stream 共用抽象)· A17 ✓(INC-1 遥测真实+单调用可观测)· A18 ✓(result_key/interaction_mode 真相)· A19 ✓(零新增理解/planner 调用)· A20 ✓(焦点语料过)· A21 ✓(全量 1841 绿)· A22 ✓(上表实测)· A23 ✓(生产零触碰)· A24 ✓(Benchmark 未动)

## 15. PRODUCTION_MUTATION = NO / BENCHMARK_MUTATION = NO

生产 DB/Weaviate/路由/部署零触碰;Benchmark v1 未动;§20 受控真实模型冒烟仅本地非生产,3 用例小样本。

## 16. SCOPE_DEVIATIONS = NONE

无 INC-2b/INC-4~7 工作;无 resolver/检索/排序/剪枝/证据元数据重设计;无 Admin 重设计;新信封字段(interaction_mode/result_key 扩展)属 §21 授权 supporting work。

## 17. OPEN_RISKS

1. **R1 真实模型分类质量**:受控对照仅 3 用例小样本;clarification vs off_topic 的模型判定边界需更大语料验证(建议集成门跑冻结 Benchmark v1 时观察,A 已保留该授权)。
2. **R2 prompt 语言**:合并 prompt 主体为中文(与既有 intent/extract/rewrite prompt 一致);EN 查询理解经测试覆盖,但极端 EN 口语表述的 mode 判定未见大规模数据。
3. **R3 生产路由生效值**:task_understanding 链已入 yaml,生产 DB llm_routing 无该行时按 yaml 生效;生产部署(需单独授权)时须确认链配置符合预期。
4. **R4 兼容模块弃用**:intent.py/query_rewrite.py 主路径不再调用但保留(含其单测);后续增量可清理。
5. **R5 capability 文案**:当前为保守通用描述(§9 授权);配置化能力文案(站点/助手配置驱动)留待后续增量(契约 §9 "where technically available")。
