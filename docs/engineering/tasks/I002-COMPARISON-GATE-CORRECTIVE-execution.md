# I-002 Corrective — Comparison Gate False Activation · Execution Report

**STATUS**: **CANDIDATE READY**(实现+测试+工程验证完成;待 A 独立评审,非最终产品接受)
**Date**: 2026-09-09

| 项 | 值 |
|---|---|
| BASELINE_COMMIT | `26de2b6e4b713e0e23ebf80fecfd6b045adeff66`(生产 v1.2.1) |
| BRANCH | `worktree-exec/i002-comparison-gate-20260909`(worktree `.worktrees/i002-comparison-gate`) |
| CANDIDATE_COMMIT | `273a885726bd1bcf359ab970e73a002aa75057f2` |
| LINEAGE | main=`fbbf653` →(trace-parity 矫正)→ `26de2b6`(v1.2.1 生产)→ `273a885`(本候选)。**main 未触碰**,26de2b6 非 main 祖先,基线即生产源,无静默基于 main |

## ROOT_CAUSE_CONFIRMED
成立。本任务在 resolver 层行为级复现:基线 26de2b6 对三类集成/兼容问句(zh HOW_TO / EN connect / EN compatibility)全部返回 `mode=comparison`(RED 实证),与 EVAL_V1C RCA RC2(sq-003 三 runs 3 源指南→81 字模板零源)一致。

## ACTIVATION_RULE
- **BEFORE**: `extract_products(query) ≥ 2` → `MODE_COMPARISON`(无条件,实体共现即比较)
- **AFTER**: `≥2 实体` **且** 确定性比较意图正证据(`has_comparison_intent`:zh 对比/相比/区别/差别/差异/哪个/哪种/哪一个/还是 + en vs/versus/compare/comparison/difference between/distinguish/which is better…,整串小写匹配,纯函数零 I/O 零 LLM);无正证据 → `MODE_EXACT` 多目标作用域(detail={"multi_entity": True})

## WHY_MULTI_ENTITY_WAS_FALSE_POSITIVE
HOW_TO/兼容/部署类问句的 Product→Platform/Product→Tool 关系(NE101 接入 AI ToolStack)不是对比关系;旧规则仅凭共现即进比较专用管线,单侧(per-target own)缺证即 `COMPARISON_EVIDENCE_INSUFFICIENT` 整答拒答。intent 分类器(VALID_CATEGORIES=commercial/product/support/off_topic)无独立 comparison 类别,故正证据取确定性比较语——不新增 LLM(§9)。

## IMPLEMENTATION_SUMMARY
`product_resolver.py`:新增 `_COMPARISON_INTENT_MARKERS` + `has_comparison_intent()`;`resolve_products` 的 `len≥2` 分支加意图门。**比较专用管线的触发消费方零改动**:rag.py:1515(`mode==COMPARISON` 才进比较证据管线)、response_strategy.py:106、evidence_planning.py:152、Issue#19 per-target 契约全部原样。多目标 EXACT 沿既有语义:双侧/多侧实体保留 eligible_slugs 作用域检索(rag.py:156/179),证据不足走既有 normal 证据语义(§13 不制造证据)。

## CHANGED_FILES
`backend/pipeline/product_resolver.py`(+32/-2)、`tests/pipeline/test_product_resolver.py`(+80/-1)。共 2 文件,112 insertions/3 deletions。(INTEGRATION-GATE §6 授权修正:+79 为 executor 笔误,git numstat 实证 +80/-1)

## 六类验收结果
- **SQ003_CLASS_RESULT**: "NE101 如何接入 AI ToolStack？" → exact,targets=("ne101","aitoolstack") 保真,detail.multi_entity=True,不进比较管线 ✓
- **EXPLICIT_COMPARISON_RESULT**: Compare NE101 and NE503 / NE101 vs NE503 which is better / 有什么区别 / 哪个更适合 / 选…还是 → 全部 comparison ✓
- **INTEGRATION_RESULT**: EN connect / deploy using → exact ✓
- **COMPATIBILITY_RESULT**: "Does NE101 work with AI ToolStack?" → exact ✓
- **MULTILINGUAL_RESULT**: zh+en 对称覆盖(词轮双语,抽取与门控均语言无关) ✓

## 契约与路径保持
- **ISSUE19_CONTRACT_RESULT**: 存量比较测试全绿(test_issue19_comparison/test_comparison_evidence_correctness 等 focused 193/193);§5 边界(per-target 证据要求/充足性/拒答/引用语义)零修改
- **ENTITY_RESOLUTION_RESULT**: 实体抽取未动,aitoolstack 仍被识别(仅不再授权比较) ✓
- **NORMAL_RAG_RESULT**: exact 多目标沿用既有 eligible 作用域与证据不足语义,无证据制造 ✓
- **ANSWER_STREAM_PARITY**: 单一解析点 `_resolve_product_boundary`(rag.py:146)被 `answer()`(1296) 与 `stream_answer()`(1964) 共用——结构性同 parity ✓
- **NEW_LLM_CALLS**: **0**

## 验证
- **RED_TEST_RESULT**: 行为级——stash 实现后基线对三类集成/兼容问句全部 `mode=comparison`(取证输出留存);新测试在无实现时 ImportError(结构性证明新增)
- **GREEN_TEST_RESULT**: test_product_resolver 26/26(含新 TestComparisonIntentGate 12 测:六类+变体+实体保真+单实体不受影响+词轮精度)
- **FOCUSED_TEST_RESULT**: 193 passed(比较契约/边界矩阵/边界检索/引用资格/INC-4/5/7/流 parity/resolver)
- **FULL_TEST_RESULT_1**: **1974 passed / 6 skipped / 0 failed**(2260.87s)
- **FULL_TEST_RESULT_2**: **1974 passed / 6 skipped / 0 failed**(65.98s;账目闭合=基线 1962+新测 12)

## 合规
- **SCOPE_AUDIT**: 仅比较激活逻辑+focused 测试;无 taxonomy/检索/重排/prompt/INC-5/6/7 语义改动
- **PRODUCTION_MUTATION**: 无(零部署、零生产接触)
- **BENCHMARK_RUN**: 未运行 121×3;EVAL_V1C/EVAL_V2 未触碰

## UNRESOLVED / RISKS
1. RCA 已声明的 UNKNOWN 保持:比较门触发面在基线期已扩大的运行时 taxonomy/语料数据态差异未查(本修复使激活不再依赖该数据态,缺陷免疫);生产库访问仍超授权。
2. 风险(低):"还是/哪个"在双实体非取舍问句中的罕见误正(如"NE101 和 NE503 的说明书哪个部分讲 MQTT")——后果为落入真比较管线,双侧有证时正常作答,单侧缺证才拒答;词轮可按需窄化。
3. intent 分类器无 comparison 类别,词轮是当前最小可靠正证据;若未来需要语义级判定,属 EVAL_V2/产品语义工作,本任务未授权。

## 停止边界(§21)
已停止:未部署、未并 main、未跑 Benchmark、未动 EVAL_V2、未开 I-003/I-004、未关 issue。候选证据交 A 评审。

REPORT_PATH: docs/engineering/tasks/I002-COMPARISON-GATE-CORRECTIVE-execution.md
