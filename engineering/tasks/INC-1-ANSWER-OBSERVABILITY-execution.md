# INC-1 应答管线可观测基座 — 执行报告

- 契约:增量式工程发现(dfe104a6)INC-1 冻结条款 + 派发令补充 REQUIRED 观测项
- 基线锚:生产 cdbcad38(PB-V1-20260907-CDBCAD3 实测基线)
- 实现分支:ask-ai 主仓 `task/inc1-answer-observability`,实现提交 **f7ac3a7**(基于 cdbcad3)
- 自评:**CANDIDATE READY**(待 Agent A 验收)

---

## 1. 契约范围确认

**做过的**:应答路径每次 LLM 调用保留结构化遥测(task/解析 provider/解析 model/generation 链回退标志/latency/输入输出 token(供应商上报时)/thinking 模式/success-failure/条件跳过);修复流式 `tokens_output` 字符数冒充 token 缺陷;extract 与 rewrite 计时分离;剪枝独立计时;归因演示;开销测量。

**未动的(不变面承诺)**:0 个新 LLM 调用;不改任何应答行为/prompt/检索/重排/剪枝/应答策略;不改访客可见 Sources;零生产触碰;不做 INC-2a/INC-3;不重跑 363 请求基线。

**红线遵守**:遥测只含元数据,零 prompt/内部证据/敏感上下文持久化(§3)。

## 2. 变更面(4 实现 + 3 测试,927 insertions / 27 deletions)

| 文件 | 变更 |
|---|---|
| `backend/llm/telemetry.py`(新) | ContextVar 请求级采集器:`start_capture / current_calls / record_call / record_skipped / record_stream_usage / pop_stream_usage`;MAX_EVENTS=64;仅元数据 |
| `backend/llm/registry.py` | `generate()` 逐尝试事件;`stream()` 结束/中断/故障切换事件;`_get_chain_with_fallback` 回退标志;`default_model` 解析回退 |
| `backend/llm/deepseek.py` | `stream_options.include_usage`(400 自动降级重试,不耗重试预算);usage chunk 记录后 `continue`(绝不入答案流);`default_model` 属性 |
| `backend/pipeline/rag.py` | `tel.start_capture()` 进 stream_answer/answer 入口;11 处 trace_payload 顶层 `llm_calls`(成功/全部 reject/off-topic/override/social/比较不足);8 类短路 `record_skipped`;extract/rewrite 分离计时;`prune_ms` 独立(成功/拒绝/比较三路);流式 generate 阶段改用 provider usage + 新增 `answer_chars` |
| `tests/llm/test_inc1_router_telemetry.py`(新) | 路由遥测 8 测:成功事件字段/回退标志/故障切换失败尝试/全灭终局/流式 usage/流式中断 complete=False/语义不变 |
| `tests/llm/test_deepseek_stream_usage.py`(新) | usage chunk 剔离内容+入遥测;400 → 降级重试 |
| `tests/pipeline/test_inc1_observability.py`(新) | 管线级 7 测:llm_calls+usage+分离计时/仅内部证据仍留痕/空检索 skip/off_topic/social 全 skip/answer 路径/**K3-K7 归因演示** |

## 3. 遥测 Schema

**调用事件**(`trace_payload.llm_calls[]`,11 处短路/成功路径全覆盖):

```
{ task, provider, model(链路钉住优先,否则 provider default_model),
  generation_chain_fallback(bool), attempt, latency_ms,
  tokens_input?, tokens_output?(供应商上报才出现;流式来自 include_usage),
  thinking(显式传入或 "provider-default"), success, complete?, error? }
```

**跳过事件**(同列表,`{task, skipped: true, reason}`):pruning=no_candidates;generation=off_topic_short_circuit / social_short_circuit / product_boundary / comparison_insufficient / insufficient_evidence_reject / no_lead_context / qualify_gate_not_met;query_extraction / query_rewrite 随对应短路。

**零内容保证**:事件字段全部为标量元数据;`record_call` 过滤 None;无 prompt、无检索文本、无答案正文。流式字符数另存 `stages.generate.answer_chars`(仅长度)。

## 4. 三项 REQUIRED 缺陷修复证据

1. **流式 tokens_output 字符数冒充** → deepseek `include_usage` 真 completion_tokens 进 `stages.generate.tokens_output`(测试:fake usage(7,22) 断言 22;400 降级重试另测)。
2. **extract/rewrite 合并计时** → `stages.rewrite` 新增 `extract_ms` / `rewrite_ms`,原 `ms` 语义为两者之和(保持向后兼容)。
3. **剪枝无独立计时** → `stages.rerank.prune_ms`(pruner 未跑=None,空候选=skip 事件),成功/无证据拒绝/比较拒绝三路一致。

## 5. 归因演示(基线 K9→可区分)

`test_inc1_attribution_demo` 单请求断言:`stages.retrieve.path_counts`(K3)、`stages.rerank.{pruned,prune_ms}`(K4)、`stages.citation_integrity.{public_chunks,background_chunks}`(K6)、`llm_calls` generation 事件 `{provider,model,latency_ms,tokens_output,success}`(K7)。基线 73 观测中 49 个 K9-with-candidates 自此具备最小判别字段。

## 6. 开销测量(本机 micro-bench,3000 轮)

| 项 | 数值 |
|---|---|
| generate 路由+遥测包装增量 | **+0.002 ms/调用** |
| stream 包装增量(12 chunks) | **+0.009 ms/流** |
| record_call 单事件 | 0.21 μs |
| 占生产 generate P50(12.5 s)份额 | **0.00002%** |

结论:开销在 μs 量级,相对 TTFT 10.1 s / E2E 13.0 s 不可测量;ContextVar 复制随 asyncio task 继承已实证(asyncgen 可见性有专项测试)。

## 7. 验证矩阵

- 新增测试:17(8+2+7)全绿
- 触碰面回归:tests/llm 35 绿;pipeline 定向 193 绿;rag 家族 74 绿
- **全量离线套件:1737 passed / 3 skipped / 0 failed(55.26 s, HF_HUB_OFFLINE=1)** — 零回归

## 8. 残余边界(诚实声明)

- 供应商未上报 usage 时 token 字段缺省(record_call 过滤 None)——如实缺席,不造数。
- `thinking` 在未显式传参时记 `"provider-default"`,非供应商真实推理开关状态(V1 边界)。
- 流式 complete=False 覆盖客户端中断(GeneratorExit)与失败切换;已产出后失败仍按 fail-no-replay 抛出,不切链路(语义与 INC-1 前一致,有专项测试)。
- `include_usage` 400 降级路径下该次调用无 token 用量(供应商不支持),记 None。

## 9. 提交

- 主仓:`f7ac3a7` @ `task/inc1-answer-observability`(实现+测试,单提交,未触碰 74ffb53e/81482fc0/7a535449/dfe104a6)
- 文档仓:本报告(独立提交)
