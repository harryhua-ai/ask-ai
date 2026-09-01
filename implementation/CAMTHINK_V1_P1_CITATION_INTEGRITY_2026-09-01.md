# CAMTHINK V1 — P1 Citation Integrity 执行报告

TASK_ID = CAMTHINK_V1_P1_CITATION_INTEGRITY
日期 = 2026-09-01
执行模式 = SINGLE CODEX(执行端)
最终状态 = **PARTIAL**(CIT-01 全量确定性解决;CIT-02 达成最强合理 V1 边界,语义蕴含残余局限显式声明——符合合同 §11 预期路径,未伪装完整性)

---

## 1. Executive Result

- **CIT-01(引用索引完整性):完全解决,全确定性保证。** LLM 生成上下文的编号集合与访客可见 sources 现在是**同一个权威集合**;流式下行前对每个 `[N]` 标记做确定性校验,悬空/越界/[0] 标记在到达用户前被剔除。结构性根因(两套独立编号集)从源头消除。
- **CIT-02(主张↔证据完整性):最强合理 V1 边界落地,无二次 LLM 调用。** 精确数值主张逐段做确定性支持校验(所引来源文本中找不到该数字 → 剔除该引用标记,移除虚假引用权威,不改写正文);prompt 契约加入证据绑定与"未载明须明示"要求。生产实测中该网真实拦截(见 §11 PE-CIT-04,unsupported_dropped=2)。**非数值能力类主张的语义蕴含无法在无二次 LLM 调用前提下确定性保证——残余局限显式声明(§14)。**
- P0 信任边界与 P1 生成可靠性契约零回归(点名回归 73 用例 + 全量 639 用例全绿)。
- 性能影响:流式过滤器 0.228 ms/答案、终验 0.215 ms/答案(对比 LLM 生成 8,000–25,000 ms,开销 ~0.003%),无新增 LLM 调用。

## 2. Baseline

- BASELINE_COMMIT = `84a68b9bc828687386d147b266d3b5952f871a8a`(CAMTHINK_V1_P0_P1_INTEGRATION_GATE,含 P0 信任边界 + P1 生成可靠性 + 组合回归门)
- WORKTREE = `/Users/harryhua/Documents/GitHub/ask-ai-citation-integrity`
- BRANCH = `worktree-exec/p1-citation-integrity`
- 未在 main 或 integration/camthink-v1-p0-p1 直接工作;未重写 P0/P1 历史。

## 3. Root Cause — CIT-01

调查覆盖 §4 全部边界(rag.py / routes.py / SSE 事件 / widget 渲染 / prompts / P0 guard / P1 流语义)。根因是**三个独立缺陷叠加**,非单一缺陷:

- **RC1(结构性主因):两套互不相干的编号集。** `RAGOrchestrator._build_context` 对全部重排候选(含 filesystem 内部源 chunk、同文档重复页 chunk、最多 top_k=10 条)统一编号 `[1..N]` 喂给 LLM;而 `_extract_sources` 独立派生访客列表 = 公开白名单过滤(PUBLIC_SOURCE_TYPES)+ 归一化路径去重 + `[:5]` 截断。只要出现任一情况——重排中有内部源、同一文档多 chunk、公开源超过 5 个——LLM 的 `[k]` 与访客列表第 k 项就是**不同的来源**。
- **RC2(零执行):生成后无任何校验。** 模型可发任意 `[n]`,原样透传;`routes.py` 将含悬空标记的答案与不含该来源的 `sources` 一起持久化(Conversation 自身就不一致)。
- **RC3(展示层掩盖 + 错位归因):** widget `renderMarkdownSafe` 逐行吞掉所有 `[n]` 文本,只对能定位到 sources 的标记渲染徽标——悬空标记被静默吞掉(掩盖缺陷而非防止),存活标记**按另一套编号**定位 → 系统性错位归因(假信心)。新增发现:引用处理连 `<pre><code>` 代码块内的 `[9]`(数组下标)也吞掉,破坏代码内容。

对 §4 十问的要点回答:编号在 `_build_context` 赋予;LLM 可见集 ≠ 访客可见集(RC1);P0 过滤发生在编号之前但白名单/去重/截断过滤发生在编号之后;编号在生成与渲染间不再漂移(同一 `sources` 列表同时用于 SSE `sources`/`complete` 事件)但语义错位(RC3);模型可引用任意数字(RC2);机制=上下文 chunk 带 `[i]` 头+prompt"每段末尾 [N]";来源以 chunk 级全文提供,蕴含验证的 provenance 充分;此前无任何生成后校验;CIT-01 可确定性解决(已证明);CIT-02 数值级可确定性筛查、语义级不可(§14)。

## 4. Root Cause — CIT-02

- 上下文编号是唯一的"主张↔证据"机制,来源以 chunk 全文提供(provenance 充足),但:(a) prompt 只说"不编造",未把**具体数值**绑定到**具体来源**;(b) 无任何校验,模型可合成数字($59)并挂最近的引用($69–112 的来源)制造假权威。验收基线 A01($59 vs 商店 $69–112)即此模式。

## 5. Existing Citation Architecture

- 检索→RRF 融合→P0 可见性守卫→rerank(top_k=10)→(P1 兜底 fused top-N)→`_build_context`(旧:全体编号)→ LLM → SSE `sources`(先)→ `token` 流 → `complete`(持久化权威答案)。
- `routes.py` 不向客户端转发 `complete`;widget 以 token 累积为展示、`sources` 事件为徽标数据源,每轮消息各自持有 sources(多轮隔离的展示层基础已具备)。
- 同步 `answer()` 无外部调用方,但保持同等校验以维持 parity。

## 6. Implemented Design

新增 `backend/pipeline/citation.py`(唯一权威定义点),三层确定性防线:

1. **`build_citation_context(reranked, sources)`** —— 以访客可见 `sources`(公开白名单+去重+截5,复用原 `_extract_sources`)为**唯一权威编号集**拼装 LLM 上下文:每个来源一个 `[i]` 头,其全部 chunk 归组在该编号下;授权参与生成但不可见的内容(filesystem 内部案例)进**「背景资料(禁止引用,严禁标注 [N])」**段——保留 P0 已接受的"内部案例可参考但须注明历史案例"行为,同时使其不可被引用;第 5 个公开页之外的 chunk 丢弃(保留即可被引用但不可见);丢弃量计入 stats。
2. **`CitationStreamFilter`** —— token 流逐字符状态机:holdback 缓冲容忍跨 token 拆分(`[` / `2` / `]`);`[n]` 后紧跟 `(` 视为 Markdown 链接不按引用处理;``` 代码围栏内不做标记处理;悬空(n 越界/为 0)标记直接剔除;合法标记解析时对**当前段文本窗口**(自上一标记/段界以来)做数值支持校验,无据则剔除该标记。只剔除标记,不删改正文。
3. **`validate_citations(answer, n, texts)`** —— 对完整答案跑同一规则的幂等终验:同步 `answer()` 主用 + 流式 `complete` 事件防御纵深。

接入:`rag.py` 两路径共用权威上下文;`_build_messages` 要求段新增证据绑定契约(引用标记只能用「可引用资料」编号;精确数值必须与所引资料原文一致,未载明须明示,严禁相近数值+[N] 冒充有据);`stages.citation_integrity` 统计(markers_seen / dangling_dropped / unsupported_dropped / public_chunks / background_chunks / dropped_public_chunks)入 trace 落库可观测。`_build_context` 删除;`SOURCE_LABELS`/`PUBLIC_SOURCE_TYPES`/`normalize_source_path` 迁入 citation.py(rag 反向引用,无外部引用受影响)。

Widget:`sanitize.ts` 引用处理跳过 `<pre><code>` 块(修复代码内容被吞缺陷);其余展示层行为(悬空吞掉、编号徽标)以回归钉固化。

## 7. P0 Compatibility

零回归。`tests/services/test_source_visibility.py`、`tests/pipeline/test_rag_trust_boundary.py`、`tests/scripts/test_migrate_channel_visibility.py`、`tests/pipeline/test_integration_gate.py` 全过。P0 的 chunk 级检索过滤+守卫发生在编号之前,本任务未触碰授权链路;可见性守卫 fail-closed 语义原样保留(授权失败→候选清空→拒答门兜底,不产生引用)。

## 8. P1 Compatibility

零回归。`tests/api/test_reliability.py`、`tests/llm/test_router_stream_failover.py`、`tests/pipeline/test_rag_reliability.py` 全过。零可用内容(含"唯一内容是被剔除的悬空标记"的边界)仍抛 `EmptyGenerationError` → 结构化 error 事件,不被引用校验伪装成功(CIT-G010,含专项测试)。意图不足/拒答语义未动。

## 9. CIT-G001..G010

| 场景 | 结果 | 证据 |
|---|---|---|
| G001 每个标记存在 | PASS | `test_valid_marker_passes`、`test_cit_g001_all_markers_map` |
| G002 受限/内部源不可产生引用 | PASS | `test_cit_g002_g003_filtering_and_numbering`(filesystem 进背景段无编号;幻影 [3] 剔除) |
| G003 过滤后编号压缩 | PASS | 同上([1]=B、[2]=C,非 [2]/[3])+ `test_numbering_matches_visible_sources` |
| G004 无据数字 | PASS | `test_unsupported_number_drops_marker`、`test_cit_g004_unsupported_price_number`($59 对 $69–112 → 标记剔除) |
| G005 有据数字不过度拦截 | PASS | `test_supported_number_keeps_marker`(℃/°C 归一)、`test_cit_g005_supported_temperature_answer` + 生产 PE-CIT-03 |
| G006 无据能力主张 | PASS(Prompt 契约层) | `test_prompt_contract_carries_evidence_binding` + 生产 PE-CIT-05(安全拒答);确定性执行不可行性见 §14 |
| G007 多源映射保持 | PASS | `test_window_resets_after_marker`(逐段归因)+ 生产 PE-CIT-06 Turn1(接口[2] 与供电[1] 分段映射) |
| G008 无证据 | PASS | `test_cit_g008_reject_path_unchanged`(拒答不变、sources=[]) |
| G009 多轮隔离 | PASS | `test_cit_g009_multi_turn_isolation`(过滤器按次实例化,无陈旧映射)+ 生产 PE-CIT-06 |
| G010 P1 失败交互 | PASS | `test_cit_g010_zero_content_still_raises`(悬空标记剔除后零内容仍抛 EmptyGenerationError) |

## 10. RED → GREEN Evidence

- RED:`tests/pipeline/test_citation_integrity.py` 先行落地(30 用例),首跑 `ModuleNotFoundError: backend.pipeline.citation`(接口缺失的预期失败);widget 侧 `leaves [N] inside code blocks untouched` 先红后绿,抓出并修复 `<pre><code>` 内容被吞的真实缺陷。
- GREEN:`citation.py` 实现后 30/30 过;`black` 增量格式化后复跑 70/70 过(rag/reliability/citation)。
- 全程未在无失败测试状态下写生产行为。

## 11. Product Evidence

实测环境:独立 worktree 后端 :8029(PID 隔离,未触碰 :8000 主后端与 :8023 上他人进程),真实 LLM(DeepSeek)+ 真实共享语料(Weaviate 只读,未写入)。探针完整记录存 `/tmp/pe_results/*.json`。

- **PE-CIT-01** ✓ PASS — "设备激活时 ICCID 注册失败怎么排查?"(support 意图):可见 sources 仅公开类型(`wp-json`/`wp-json/wp/v2/pages/5865`,均 web_crawl),答案标记 [1][2] 全部映射,dangling=[];模型显式回答"官方资料未包含……排查内容"。trace 落库:`citation_integrity={markers_seen:4, public_chunks:2, dangling_dropped:0, background_chunks:0}`。
- **PE-CIT-02** ✓ PASS — 确定性层:CIT-G002/G003 集成测试证明过滤/内部源存在时编号压缩重排;真实流量:PE-CIT-01 trace `public_chunks=2` ↔ SSE sources=2 ↔ 标记紧致,无编号断层。
- **PE-CIT-03** ✓ PASS — "NE301 的工作温度范围是多少?":答案"−20°C 至 +50°C [1][2][3]",3 源全公开、标记全有效,有据精确数字正常作答未过度拦截。
- **PE-CIT-04** ✓ PASS — "NE301 的电池容量是多少 mAh?":语料存在两个矛盾值(1,750 vs 2,500 mAh),模型**显式披露矛盾并声明无法确认**,按来源归因,未编造单一数字;trace:`markers_seen=4, unsupported_dropped=2` —— 模型实际发出 4 个标记,2 个无据标记被数值网在生产路径真实剔除,用户只看到有据引用。
- **PE-CIT-05** ✓ PASS — "NE301 支持卫星通信吗?":安全拒答"暂未在官方资料中找到相关信息。",零引用。
- **PE-CIT-06** ✓ PASS — 多轮:Turn1(NE503 接口,5 源,接口[2]/供电[1] 逐段正确映射)→ Turn2(功耗,权威集合更新为 1 新源),Turn2 标记 [1] 有效且无 Turn1 陈旧 [2]..[5];并再次展示无据数值的明示不足("官方资料未载明该数值")。
- **PE-CIT-07** ✓ PASS(回归层)— 真实供应商零 token 无法稳定激发;由确定性回归覆盖:`test_cit_g010_zero_content_still_raises` + `tests/api/test_reliability.py` 全量(结构化 error 事件 + is_answered=False 不被引用校验改写)。

## 12. Regression Tests

- 后端全量(CI 等价):**639 passed, 5 skipped, 0 failed, 0 errors**(35:07;首跑曾现 1F+10E,定位为 ask_ai_test 测试库环境瞬态——涉事 12 用例隔离重跑全过、全量净重跑 0F,非代码回归)。
- P0/P1/CIT 点名:73 passed(source_visibility / rag_trust_boundary / migrate_channel_visibility / integration_gate / api reliability / router_stream_failover / rag_reliability / citation_integrity)。
- Widget:vitest **39/39**(新增 CIT-01 展示层 5 钉)、`tsc --noEmit` ✓、`npm run build` ✓。
- Admin:`tsc --noEmit` ✓、build ✓。
- Lint:black 增量格式化;ruff 对改动文件 2 处告警(SIM102/F841)经基线对照确认为**既有**,按最小变更未动。
- 测试断言均为可观察引用行为(标记透传/剔除结果、SSE 事件、trace 统计),无"仅断言 prompt 文本"的用例(prompt 契约测试仅作 G006 的合同钉,行为层由 PE-CIT-05 生产证据补足)。

## 13. Performance Impact

- **SECOND_LLM_CALL = NO**;校验全确定性(正则/状态机/字符串匹配)。
- 微基准(424 字符、6 段、8 字符 token 粒度、2000 次平均):流式过滤器 **0.228 ms/答案**,终验 **0.215 ms/答案**;对比 LLM 生成 8,000–25,000 ms,引入开销 ~0.003%,TTFT 影响 ~0(过滤器仅对含 `[` 的字符做 holdback,最长延迟 5 字符)。
- 上下文构建变化:第 5 公开页之外 chunk 从上下文剔除(最坏情形略减上下文);换取编号权威一致性,为合同强制要求。真实流量未见答案质量劣化(PE 全部场景回答质量正常)。

## 14. Residual Risks

1. **CIT-02 语义蕴含未完全保证(声明的 V1 边界)**:数值级必要条件筛查强(数字不在来源→必然无据),但 (a) 数字在来源中≠该主张被该来源支持($59 存在于来源但属另一型号价格的情形不会被拦);(b) 非数值能力/兼容性主张仅由 prompt 契约约束,无确定性执行。按合同 §11 未伪装完整性,状态 PARTIAL。后续可选:NLI 小模型本地校验 / 生成后单次复核调用(需延迟预算拍板)。
2. 单位换算形数字(0.5A vs 500mA)可能误判为无据 → 误剔标记(主张保留、无假权威);生产 PE 未观察到。
3. 模型可不发标记规避数值网(标记是引用权威的载体,无标记即无假权威,可接受)。
4. `complete.answer` 为持久化权威;widget 以 token 累积展示——流式校验已保证两者一致(幂等终验兜底),但旧版本 widget 配新后端时行为同样正确(修复在后端下行侧)。

## 15. Changed Files

- `backend/pipeline/citation.py`(新增,496 行:权威上下文构建 / 流式过滤器 / 终验 / 数值支持)
- `backend/pipeline/rag.py`(接入两路径 + prompt 证据绑定契约 + trace 统计;删除 `_build_context`;常量迁至 citation.py)
- `tests/pipeline/test_citation_integrity.py`(新增,30 用例,G001–G010 + 单测 + 集成)
- `widget/src/utils/sanitize.ts`(引用处理跳过代码块)
- `widget/src/utils/__tests__/sanitize.test.ts`(CIT-01 展示层回归钉 5 用例)

## 16. Final Commit

`e3c83b2` — fix(citation): P1 引用完整性 — 权威编号统一 + 流式确定性校验 + 数值支持网(CIT-01/CIT-02)

## 17. Branch

`worktree-exec/p1-citation-integrity` @ `/Users/harryhua/Documents/GitHub/ask-ai-citation-integrity`(基线 84a68b9 线性 +1 提交)

## 18. Deployment Status

- PRODUCTION_DEPLOYED = **NO**(未部署、未迁移、未触碰生产)
- SHARED_WEAVIATE_WRITTEN = **NO**(仅只读检索;Weaviate :8080 零写入)
- 主后端 :8000 未动;:8023 上非本任务进程未动;实测后端(:8029)已停。
