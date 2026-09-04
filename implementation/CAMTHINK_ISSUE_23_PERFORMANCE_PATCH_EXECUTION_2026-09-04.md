# ASK-AI v1.0.1 — Issue #23 Performance Patch 执行报告

- 日期:2026-09-04;Executor:B
- Baseline:**3cf42da**(v1.0.1 integration candidate;origin 实查逐字一致)
- branch/worktree:`v1.0.1/issue23-performance` @ `.worktrees/v101-issue23-perf`
- **PATCH_COMMIT:ba90450**(已推 origin)
- 最终:**FINAL PATCH STATUS = CANDIDATE READY**(未部署、未合 main、未动生产)

## 1. Baseline / 2. Changed Files

Baseline 3cf42da = origin `v1.0.1/integration-candidate` ✓。变更文件:
`backend/llm/deepseek.py`、`backend/llm/registry.py`、`backend/pipeline/intent.py`、
`backend/pipeline/query_rewrite.py`、`backend/pipeline/rag.py`、`backend/api/routes.py`(无;#19 已带)、
`.env.example`、`tests/pipeline/test_intent.py`、`tests/llm/test_deepseek.py`、
`tests/pipeline/{test_citation_integrity,test_checkpoint_gate,test_integration_gate,test_product_boundary_retrieval,test_product_boundary_eval_matrix}.py`、`tests/api/test_unified_v1_gate.py`(后者 6 文件 = 假 LLM 签名 `**kwargs` 适配)。

## 3. QW-1(intent/extract/rewrite thinking disabled)

`deepseek.py::_apply_thinking`:仅调用方显式 `thinking="disabled"` 时注入 provider 认可的
`{"type":"disabled"}`(Discovery §5 实证;`enable_thinking`/`reasoning_effort` 无效 → 不支持变体一律不注入)。
缺省 payload 与基线逐字一致。三个调用点(intent.py:117 / query_rewrite.py:68,117)携带该选项。
provider/model 路由未动(DB 权威 deepseek-v4-flash)。

## 4. Intent Correctness Fix

`intent.py` fail-open 语义:`IntentResult(category="product", confidence=0.0, reason="classification failed (fail-open: empty/malformed response)")` —— 空/畸形/异常不再伪装为可信分类;桶语义保持(不发明新分类);boost 行为不变。
确定性回归(`tests/pipeline/test_intent.py`):空 content / 截断 JSON / LLM 异常三例(锚题 `NeoRuntime 如何安装部署?`)断言 confidence==0.0 + fail-open 原因;另断言 intent 请求必须携带 `thinking="disabled"`。
生产容器定量复现(真实 _INTENT_PROMPT,max_tokens=128):default **2/3 content 为空**(128 reasoning deltas 吞尽)、1/3 89 字符;disabled **3/3 全部 86 字符有效 JSON**,total 0.82-1.36s vs 1.64-1.79s。

## 5. QW-2 Implementation

generation 两调用点(rag.py stream/generate)携带 `thinking="disabled"`;trace `generate.thinking_mode` +
`config_snapshot.llm_generation`(provider/model,`LLMRouter.describe_chain`,防御式不影响主流程)。

## 6. QW-2 Correctness Evaluation(A–J)

**方法一:本地双栈全管线对照**(baseline 3cf42da @18001 vs patch @18002,同本地 weaviate(70,575 chunks)/PG,
零生产接触;SSE 逐事件解析):A 简单事实 / B how-to 锚题 / C 排障 / D 单产品(#5)/ E 对比(#19)/
F 歧义 / G 无证据 / H 长技术 / J 证据不足。

结果:
- 本地语料仅含 ne101/ne301/website 注册源,故 A-J 中多数两版**逐字一致地走弃答/不足语义**——
  弃答(no_evidence)、歧义澄清(F)、比较不足(E,Track A 缺侧命名语义)在两版**完全一致**,无幻觉、无越权;
- **G(唯一有真实证据样例):BASE TTFT 11.05s/E2E 11.98s → PATCH 5.51s/6.19s(−50%),事实集合一致
  (整机 24 个月/板卡配件 12 个月)、引用 [1] 合法、内容更精炼 —— FASTER × NOT LESS CORRECT 直接实证**;
- D(J-insuff 单侧无证据)、F:contract 语义分毫不差。

**方法二:t4 生产容器 provider 直连锚题评测**(Discovery 同法:与生产同 base/model/key,只读拉取生产
neoruntime 真实上下文 22 chunks/24k chars 组装生成式 prompt;default n=4 vs disabled n=4,有界共 ~28 次 provider 调用):
- TTFC:default 1.08/1.10/1.25/**4.71s**(p50≈1.18)→ disabled **0.52/0.60/0.87/0.97s**(p50≈0.72),
  **重尾消除**;reasoning 字符 default 69-1,095 → disabled 恒 0;
- 输出:disabled 144-202 字符 **恒长于** default 33-139(默认把预算烧进思考、可见内容反而更薄)——正确性无回退迹象。

## 7. Performance Benchmark(汇总)

| 段 | baseline | patch | 来源 |
| --- | --- | --- | --- |
| generation TTFC(锚题,真实上下文) | p50≈1.18s,max 4.71s | p50≈0.72s,max 0.97s | t4 provider 直连 n=4+4 |
| intent(真实 prompt,128 tok) | 0.85-1.79s,2/3 空内容 | 0.82-1.36s,3/3 有效 | t4 provider 直连 n=3+3 |
| 本地全管线 E2E(有证据样例 G) | 11.98s(TTFT 11.05) | 6.19s(TTFT 5.51) | 本地双栈 |
| extract/rewrite | Discovery §6:OFF 等义更快 | 同 | 冻结 Discovery |

**INSUFFICIENT SAMPLE FOR RELIABLE P95**(provider 直连 n=4/n=3 每变体;生产 7 天 trace 普查不可复现于本 patch——禁止部署)。

## 8. SLO Result

目标 TTFT p50≤2.5/p90≤6.0、E2E p50≤10/p90≤20。** achieved:方向与幅度符合(material improvement 实证),
生产口径 p50/p90 达标判定需部署后 7 天 trace 观测 → 本门 SLO = PARTIAL(不以 SLO 未证否 QW-1/QW-2)。**

## 9. Regression

patch worktree 全量离线:**1568 passed / 4 skipped / 0 failed(42.7s)**;ruff:触及文件无新增违规
(8 项 noqa/F841/I001 为基线既有,仅行号漂移,最小 diff 纪律未动)。

## 10. Scope Audit

仅 LLM 请求选项/三预处理调用配置/intent 失败处理/generation 配置/最小遥测/.env.example 模板/测试。
未动:检索架构、Weaviate/PG schema、sync、woo 元数据、taxonomy、Admin UI、#22、rerank(54→30 不做)、
context 裁剪(不做)、进度 UX(不做)、httpx 复用(不做)、生产(只读)。

## 11. Production Config Action

**PRODUCTION_CONFIG_ACTION_REQUIRED**:生产 `~/ask-ai/.env` 的 `DEEPSEEK_MODEL=deepseek-v4-pro`
(DB 权威为 deepseek-v4-flash;Discovery §8 量化 pro 回退 = TTFC ×4 起)。需独立配置变更门移除或改
`deepseek-v4-flash`。仓库侧已备:`.env.example` 归一 `deepseek-v4-flash`(本 patch 内,模板所有权);
`deploy/prod/.env.example` 本就正确。

## 12. Risks / Deferred

- thinking disabled 后答案风格更简短(信息密度不降,评测未见事实缺失);长期需产品口径确认答案详尽度偏好;
- provider 侧 B 型零内容机制仍开放(v4-flash 行为,与本 patch 正交);
- intent/extract 可并行化、extract 条件旁路、rerank 54→30、context 成本裁剪 —— 均 DEFERRED(Discovery §13/任务边界);
- 部署后需观测验证生产 TTFT SLO 与 intent fail-open 率下降。

## 13. Final Candidate Decision

**QW-2 = CANDIDATE READY**(correctness 门过)→ 已包含于 patch commit ba90450。
新 v1.0.1 RELEASE CANDIDATE = `v1.0.1/issue23-performance` **ba90450**(血统含 3cf42da 全部已接受内容)。

## 返回字段

```
PATCH_COMMIT   = ba90450(branch v1.0.1/issue23-performance,已推 origin)
REPORT_PATH    = docs/implementation/CAMTHINK_ISSUE_23_PERFORMANCE_PATCH_EXECUTION_2026-09-04.md
REPORT_COMMIT  = <见 docs 仓提交>
QW-1               = PASS
INTENT CORRECTNESS = PASS
QW-2               = CANDIDATE READY
CORRECTNESS GATE   = PASS
PERFORMANCE GATE   = PARTIAL(material improvement 实证;生产 SLO 达标判定需部署后观测)
REGRESSION         = PASS(1568/4/0)
FINAL PATCH STATUS = CANDIDATE READY
```

**STOP。未合 main;未打 tag;未部署;未跑生产迁移;未改生产环境。**
