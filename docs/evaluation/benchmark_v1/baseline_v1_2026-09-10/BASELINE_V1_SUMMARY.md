# Benchmark v1 — Sprint 基线(2026-09-10,矫正前)

- run_id: `BF-SPRINT-V1-20260910-V140-41278F0`;target = 生产 v1.4.0(`41278f07`,identity verified)
- 与 main `03e6c57` 答案管线语义等价(#47/#4/#21 不触 answer path)→ 即矫正前 main 基线
- 执行:121 案例 × 3 = **363 runs,0 传输错误**;runner=`scripts/benchmark_v1/run_benchmark.py`(本次入库)
- 判分:EVAL_V1 LLM-assisted(executor session subagents);范围=种子案例(13 case × 3);全量机械结果已落库

## 种子判分基线(矫正前)

| Issue | 案例 | 基线通过 | 主失败模式 |
| --- | --- | --- | --- |
| #26 | cg-r03 | **3/3 PASS**(INC-3 已修:CLARIFY 逐字复现) | — |
| #27 | cg-r04+cg-s01 | **6/6 PASS**(INC-3 已修:ORIENT 欢迎导向) | — |
| #28 | cg-r05 + sq-026/045/080 | cg-r05 0/3;sq 族 1/9 | **false_absence**:Store 变体价格($69–$112,5 SKU 族)在库却答「未载明」 |
| #29 | cg-r06 + sq-073 | 0/6 | CALCULATOR 角色不可达;NE101 数据被低估 + 假性缺失 |
| #31 | cg-r07 + cg-r09 + sq-034/040 | 0/12 | no_composition:方案塌缩成证据缺口罗列;cg-r07 前检索期误路由 clarify(~160ms);cg-r09 零源 → 一刀切拒答 |

总计:9/21 PASS(cg 种子),全部 PASS 均为 CLARIFY/ORIENT;全部 FAIL 均为
**证据动员失败**(commercial/factual/solution),零 fabrication-critical。

## 对候选的预测(判分报告全文见 seed_judging_*.md)

- #28/#29(资格展开 + tools 推导):应消灭 false_absence 族(12 个失败 run 中的 6 个,最高价值);
- #31(案例槽 + 组合指令 + cg-r07 场景充分性 guard):应恢复方案组合与标准作答路由;
- cg-r03/r04/s01 必须保持 9/9(回归红线);cg-r09(弱索引模型目录)最不确定 —— 组合指令可约束表述,不能凭空造证据。
