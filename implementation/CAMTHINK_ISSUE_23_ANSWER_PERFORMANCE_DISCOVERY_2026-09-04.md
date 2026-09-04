# CamThink Issue #23 — Answer Performance Discovery(答案性能发现)

- **日期**: 2026-09-04
- **角色**: Role A(Planner/Discovery)——READ-ONLY DISCOVERY,零实现、零生产变更
- **代码基线**: `0e6a8a3` = origin/main = 生产运行镜像 `ghcr.io/harryhua-ai/ask-ai:v1.0.0`(backend 09-03T16:51:37Z 启动,三服务一致)
- **生产取证方式**: SSH 只读(docker logs / psql SELECT / nvidia-smi)+ 生产 backend 容器内受控 provider 实验(直连 api.deepseek.com,复用容器内环境变量 key,全程不落盘、不打印 key)
- **PRODUCTION_MUTATIONS**: **NONE**(全部 SQL 为 SELECT;实验仅产生外部 provider API 调用;生产零写入)

---

## 1. Executive Summary

用户可感知延迟的真实瓶颈**不是检索、不是上下文长度、也不是应用层缓冲**,而是:

**P0(Dominant)= 生成阶段的首 token 前隐藏思考(hidden thinking)**。
生产 generation 模型为 `deepseek-v4-flash`——一个**混合思考模型**:每次请求先产出 `reasoning_content` 再产出可见 content。后端 `deepseek.py` stream 只读 `delta.content`,思考 delta 被静默丢弃,而 TTFT 计时点在首个 content delta。思考时长随问题复杂度**非确定性伸缩**(同一问题两次运行 reasoning_tok 35 vs 412),直接造成生产 TTFT p50=5.9s / p90=17.5s / max=34s。

**P1(Material)= 前置串行链**:intent(1.4s)+ query extract(1.45s)+ rerank(2.3s)≈ 5.2s,且 intent 存在一个被本 Discovery **新发现的正确性缺陷**——`max_tokens=128` 被 reasoning 耗尽后 content 为空,`classify_intent` 静默 fail-open 成 "product"(已在 anchor 原题上复现)。

**重要否定结论**:上下文裁剪**不是**延迟杠杆(294→6,990 tokens 实测 TTFC 仅 +0.15s,DeepSeek prefill 极快);网络/代理缓冲/重试/连接复用均被证据排除。

**Quick Win 候选**:API 参数 `thinking: {"type": "disabled"}` 实证有效(intent 1.4s→0.6-0.9s 且 JSON 100% 合法;生成 TTFC 3.7s→0.48s)。辅助任务(intent/extract/rewrite)关思考 = **PERFORMANCE_QUICK_WIN_CANDIDATE QW-1**(低风险,顺带修复静默误判缺陷);生成任务关思考 = **QW-2(有条件)**,必须先过正确性门。

## 2. Baseline

| 项 | 值 | 证据 |
|---|---|---|
| BASELINE_COMMIT | `0e6a8a3`(origin/main,v1.0.0) | git log / 生产镜像 tag |
| CURRENT_RELEASE | v1.0.0(生产三服务 = v1.0.0 镜像;backend Up, healthy) | `docker ps` 09-04 |
| CURRENT_MAIN_HEAD | `0e6a8a3` | git fetch 核验 |
| 生产 generation 模型 | **deepseek-v4-flash**(DB 权威,llm_providers.id=deepseek,enabled,updated 08-04) | psql SELECT(config 已脱敏 api_key) |
| 生产 routing | generation/intent/query_rewrite 全部 = flash;lead_qualification=model null(默认) | psql SELECT llm_routing |
| ⚠️ .env 回退雷 | 生产 `.env` `DEEPSEEK_MODEL=deepseek-v4-pro`(08-31 拍板"T4 须同查"**未执行**) | docker exec env(脱敏) |
| nginx | wiki-data.camthink.ai `proxy_buffering off` + `proxy_read_timeout 300s` ✓ | sites-enabled 实读 |
| GPU | 15,111/16,384 MiB(backend 持 3,954 MiB = BGE-m3 + bge-reranker-v2-m3,cuda 已加载) | nvidia-smi + 启动日志 |

生产 `.env` 的 pro 回退值当前**未生效**(DB 优先),但实验实测 pro 同 prompt TTFC=4,107ms(≈flash 的 4 倍):一旦 DB 行丢失/禁用,生产将**静默降级**到慢模型。此为运维待清理项(改生产 .env 属生产变更,不在本门授权内,仅登记)。

## 3. Current Pipeline(实码追痕 @0e6a8a3)

`POST /api/ask`(`backend/api/routes.py:98`)→ SSE `EventSourceResponse`,逐条转发无应用层缓冲:

```
HTTP request
  1 语言检测 / 覆盖答案匹配 / social 短路        本地,~0-35ms
  2 产品边界解析(Issue #5)                    本地,~33ms(clarify 短路实测 33ms)
  3 intent 分类           ← LLM 调用① 串行    p50 1,410ms(max_tokens=128,temp=0)
  4 extract_query         ← LLM 调用② 串行    ┐ stages["rewrite"] p50 1,452ms
    rewrite_query          ← LLM 调用③ 仅多轮 ┘ (首轮仅 extract)
  5 检索:hybrid+symbol+bucket 三路 + RRF + 可见性守卫    p50 69ms / p95 108ms
  6 rerank:bge-reranker-v2-m3,T4 cuda,54 对 × ≤1024tok  p50 2,322ms / p90 2,891ms
  7 yield sources SSE 事件(来源面板此刻可见)
  8 llm.stream            ← LLM 调用④          TTFT p50 5,925ms / p90 17,469ms / max 33,956ms
       └ 内部:网络 TLS ~150ms → prefill(~0.15s/7k tok)→ **隐藏思考(reasoning_content)→ 首个 content delta**
  9 CitationStreamFilter 逐 delta 转发(仅 [N 跨 token 缓冲 ≤4 字符,可忽略)
 10 流式剩余 ~2.4s(p50,输出 ~548 字符)→ complete → 持久化 → done
```

每阶段八问(串行?必要?可并行?……)结论:
- ①②③ **全串行、全无条件**(extract 不消费 intent 结果,数据流上可并行);social/override/clarify/unsupported 已有确定性短路(实测 33-35ms)✓
- 检索必要且快;rerank 串行且为 T4 算力代价(54 对 × 1024 tok ≈ 60+ TFLOP)
- ⑧ 内思考不可见不可关(当前代码未传任何思考控制参数)
- telemetry:`traces.stages` 已完整记录 intent/rewrite/retrieve/rerank/generate.ms/ttft_ms ✓

## 4. Latency Breakdown(生产 7 天,n=129,只读聚合)

| 阶段 | p50 | p90 | p95 | 备注 |
|---|---|---|---|---|
| intent(LLM①) | 1,410ms | 1,937ms | — | 128-token 上限;**含 reasoning 烧尽案例** |
| rewrite 段(LLM②③) | 1,452ms | 4,128ms | — | 首轮=extract 一次调用 |
| retrieve | 69ms | ~95ms | 108ms | 健康 |
| rerank | 2,322ms | 2,891ms | — | T4 算力;GPU 显存 92% 占用背景 |
| **TTFT(LLM④ 首 content)** | **5,925ms** | **17,469ms** | **20,540ms** | max 33,956ms |
| 生成流式剩余 | ~2,400ms | — | — | 输出 p50 548 字符 |
| **端到端 total_ms** | **18,434ms** | — | **35,891ms** | 与 anchor 案例 29,747ms 同量级 |

逐日 p50 TTFT:5,650 / 6,998 / 5,645ms(08-31→09-03)——**系统性,非偶发**。
⚠️ n=129:p50/p90 可靠;**p95 样本约 6-7 个,标记 INSUFFICIENT SAMPLE FOR RELIABLE P95(边缘可信)**。
anchor 案例定位:09-04 00:57:06 CST = v1.0.0 部署(00:51 CST)后 6 分钟的验收冒烟,属正常链路样本,非冷启动异常(其 rerank 1,795ms 与邻样一致)。

短路路径实测(生产):social 34ms / override 35ms / product_clarify 33ms / reject_short(off_topic)~1.2s(=intent LLM 调用一次)。

## 5. TTFT Root Cause(受控实验实证)

在生产 backend 容器内直连 api.deepseek.com(与生产同 base/model/key 环境),共 ~25 次调用:

**实验① prompt 规模敏感性(flash,流式)**
| 场景 | prompt_tok | TTFC(首 content) | TTFB(首 SSE 行) |
|---|---|---|---|
| tiny ×5 | 294 | 640-1,564ms | 144-262ms |
| mid ×2 | 2,650 | 677-2,375ms | 160-171ms |
| large ×2 | 6,990 | 1,045-1,087ms | 257-260ms |

→ **prefill 不是瓶颈**:+6,700 tokens 仅 +~0.15s。连接复用无显著收益(TTFB 恒 ~150ms,T4→DeepSeek 网络快)。

**实验② 真实上下文 + anchor 原题**(NeoRuntime 安装部署,flash 默认):
- run1:TTFC=795ms,reasoning_tok=35
- run2:TTFC=**3,728ms**,reasoning_tok=**412**

→ **TTFC 与 reasoning 长度一一对应,同输入非确定性**(35→412 tok = TTFC 4.7×)。生产 p90 的 17s = 数千 token 思考。生产分布佐证:简单事实题("NE301 典型功耗")TTFT **872ms**,复杂 how-to("NeoRuntime 如何安装部署")**18,111ms**。
- 思考 delta 全程被 `deepseek.py` 丢弃(`delta.get("content")` 只读 content)→ 用户在 sources 面板后 staring at 空屏。
- **成本放大**:复杂问题 completion 中 reasoning 占比 >50%(412/784)——思考同时拖慢 TTFT 且双倍计费。

**实验③ 思考控制参数**(install 原题):
| 参数变体 | 结果 |
|---|---|
| (默认) | reasoning_tok=412,TTFC=3,728ms |
| `enable_thinking: false` | 无效(仍 46 tok) |
| `reasoning_effort: "low"` | 无效(仍 32 tok) |
| **`thinking: {"type": "disabled"}`** | **有效:0 思考 delta,TTFC=477ms,答案长度正常(757 字符 vs 707)** |

**排除项(证据)**:重试放大(96h 日志 0 次 retrying);nginx/应用层缓冲(nginx off + SSE 逐条转发);网络(TTFB 恒 150ms);模型选错(DB 权威=flash);冷启动(逐日稳定)。

**定性**:TTFT ≈ **MODEL THINKING LATENCY(主)+ 可忽略的 prefill/网络(次)**;非"LLM generation 全体慢"。

## 6. Pre-generation Findings

生产实测 + 实验③(intent/extract 任务原 prompt,ON=默认 / OFF=thinking disabled):

| 任务 | ON 延迟 | OFF 延迟 | 正确性 |
|---|---|---|---|
| intent ×3 题 | 1,044-1,881ms | **633-930ms** | OFF 全部 JSON✓;**ON 在 anchor 原题上 JSON✗(空 content)** |
| extract ×3 题 | 675-2,116ms | **455-718ms** | 输出文本逐次等长等义(len 15-20 一致) |

**新发现缺陷(正确性 × 性能双重)**:`classify_intent`(`intent.py`)`max_tokens=128`,flash 默认思考先产出 reasoning——anchor 原题复现 `reasoning_tok=128, completion_tok=128, content=""` → json 解析失败 → **静默 fail-open 为 "product"**。后果:① intent 延迟虚高(整 128 tok 白烧);② support 类 how-to 查询**被静默误判**为 product,丢失 `INTENT_BOOST_FILTERS["support"]` 的 filesystem 桶加权(检索质量语义受损,不违反 #5/#19 但偏离设计意图)。生产 intent p50 1.4s 中相当部分即此模式。

结构机会(仅冻结行为,不冻结实现):intent 与 extract **数据流独立可并行**(省 ~1 次调用壁钟);extract 对短自包含查询恒为恒等输出,存在条件旁路空间(需 eval 佐证不改检索输入);rewrite 已仅多轮触发 ✓。

## 7. Context Findings

- `build_citation_context`(`citation.py`)**无单 chunk 截断、无总量上限**:rerank 保留 10 chunk 全文全量进 prompt(5 sources 由 `_extract_sources` 公开源白名单+去重截 5 形成;"context trimming: true" 为 UI 展示 trace 的 `citation_integrity` 统计语义,非独立裁剪器)。
- 生产真实 prompt ≈ **6-8k tokens**(10 × ~512tok chunk + system 2.3KB + 指令)。
- **否定结论**:TTFC 294→6,990 tok 仅 +0.15s → **"最小充分上下文"/EVIDENCE SUFFICIENCY CAP 对 TTFT 无可测量收益**,仅是 token 成本杠杆(P2,与延迟解耦)。10 chunk 间存在同 README/同页多 chunk 冗余(成本问题,非性能)。

## 8. Provider / Model Findings

- 生产唯一 provider:deepseek(openai_compatible),model=flash,DB 权威(LLMRouter 链);health_check 仅查 key 非空,不做真实探活。
- flash = 混合思考模型:默认必产出 reasoning_content;`thinking.type=disabled` 可关;`enable_thinking`/`reasoning_effort` 对本端点无效。
- pro 对照(同 6,990 tok prompt):TTFC 4,107ms、136 reasoning delta → .env 回退雷的风险量化(若 DB 行失效,TTFT ×4 起步,复杂题更甚)。
- `deepseek.py` 每次调用新建 `httpx.AsyncClient`(4 次/查询):实测 TTFB 无差异(同区网络),P2 卫生项非性能项。

## 9. Streaming Findings

- 服务端→客户端:SSE 逐条转发,nginx `proxy_buffering off` ✓,CitationStreamFilter 缓冲 ≤4 字符 ✓——**应用层无 buffering 缺陷**。
- 流式吞吐:TTFC 后 ~450 字符/s,正常。
- UX 空窗:请求 → sources 事件 ≈ 5.2s(p50 前置链);sources → 首 token ≈ 5.9s(p50)。两段空窗内 widget 仅打字指示器,无阶段反馈。Kapa 类产品用 token 级流式 + 即时开始把"总等待"感知拆散;本系统总等待还叠加了不可见思考。

## 10. Benchmark Results(生产 14 天 trace 普查 + 代表样本,n=153)

| type | n | p50 total | 说明 |
|---|---|---|---|
| rag | 131 | 18,637ms | 本报告主体分布 |
| reject_short(off_topic) | 12 | 1,231ms | =intent 一次调用 |
| social_reply | 5 | 34ms | 确定性短路 ✓ |
| generation_error | 3 | 0 | 2 例同题"NE302 和 NE301 有什么区别?"——与 Issue#19 F1(type B 零内容)互证,归 #19 轨道 |
| product_clarify | 1 | 33ms | #5 短路 ✓ |
| override | 1 | 35ms | ✓ |

按 §10 冻结 **8 类 Benchmark 集**(Executor 验收用,现值=生产真实样本参考):
1. Simple Fact:"NE301 的典型功耗是多少?" — 生产 TTFT 872ms / total 11.9s
2. Installation/How-to:"NeoRuntime 如何安装部署?" — 生产 TTFT 18,111ms / total 29,747ms(anchor)
3. Troubleshooting:"NE101 蜂窝网络注册失败/CEREG 报错"(support intent 样本)
4. Single-product:"NE503 支持哪些接口?"(必须过 #5 产品边界)
5. Comparison:"NE301 和 NE302 有什么区别?"(必须过 #19 契约;注意既有 2 例 generation_error)
6. Ambiguous:"介绍一下ne53"(生产真实样本,total 25.8s)
7. No-evidence/Abstention:"火星上未携带行李的燕子的平均飞行速度…"(生产 reject 样本,total 1.07s)
8. Long grounded:"Compare NE503 and NE301"(EN,输出 2,210 字符,生产 total 30.7s)

测量协议:每题 ≥3 轮,记录 TTFT/total/intent/rewrite/retrieve/rerank/gen/tokens/provider/model;生产低流量(n=129/7d)以受控基准跑补足统计。

## 11. Bottleneck Ranking(p50 口径,总 18.4s)

| 级 | 瓶颈 | 贡献 | 分类 |
|---|---|---|---|
| **P0** | 生成前隐藏思考(TTFT) | 5.9s(p90 17.5s) | QUICK WIN(有条件,QW-2)+ EXPERIMENTAL(思考 UX) |
| P1 | rerank(T4 算力) | 2.3s | STRUCTURAL(候选裁剪需 eval) |
| P1 | intent+extract 串行 LLM 链 | 2.85s | QUICK WIN(QW-1/QW-3) |
| P2 | 流式输出 2.4s / 其他 | 4.5s+ | NOT RECOMMENDED(输出长度有产品语义) |
| P2 | prefill/连接/上下文冗余 | ~0.2s | NOT RECOMMENDED(实证无收益) |

## 12. Quick Win Candidates

**PERFORMANCE_QUICK_WIN_CANDIDATE — QW-1:辅助任务关闭思考**
- Candidate: intent / query_rewrite(extract+rewrite)三个前置 LLM 任务请求体加 `thinking: {"type": "disabled"}`
- Observed cause: flash 混合思考对微任务空烧 reasoning;intent 且因 max_tokens=128 被思考耗尽而静默 fail-open(新发现缺陷)
- Expected gain: 前置 LLM 链 2.85s → ~1.2s(p50,省 ~1.6s);并修复 intent 静默误判
- Change boundary: 仅 LLM 请求参数 + 意图任务的 max_tokens 兜底(防其他模型同类问题);provider 能力探测失败时 fail-open 回退现状
- Correctness risk: 低(结构化微任务;实验 JSON 100% 合法、输出等义);需 eval 复核 intent 分类与 ON 模式一致率
- Verification: 8 题 benchmark ×3 轮,intent JSON 合法率 100%、与基线分类一致率记录、各阶段延迟对比
- Recommended release: **v1.0.1**

**PERFORMANCE_QUICK_WIN_CANDIDATE — QW-2(有条件):生成任务关闭思考**
- Candidate: generation task 请求加 `thinking: {"type": "disabled"}`
- Observed cause: TTFT≈思考时长(§5 实证)
- Expected gain: TTFT p50 5.9s → ~1-1.5s;p90 17.5s → ~2-3s;复杂题 token 成本约减半
- Change boundary: 仅参数;fail-open 能力探测;**不**改 grounding/citation/abstention 任何语义
- Correctness risk: **中——关思考可能降低复杂推理题答案质量,必须先过正确性门**:93 场景验收子集 + 8 题 benchmark 语义核对 + citation 悬空/无据率 + abstention 行为 + #5/#19 契约复验,**全绿才可搭乘**
- Verification: QW-1 同协议 + 完整正确性矩阵;若 eval 不达标 → 回退方案 QW-2b(保留思考 + 诚实进度提示,见 §13-PD-2)
- Recommended release: **v1.0.1(过门)/ v1.1.0(不过门走 2b)**

**QW-3(P1,可选):intent ∥ extract 并行**——数据流独立实证;QW-1 落地后残余收益 ~0.5-0.7s;v1.0.1 或 v1.1.0。

## 13. Structural Optimizations

- **S1 rerank 候选上限**:三路 RRF 融合 54 对全量进 cross-encoder;按 RRF 预截 top-30 可近乎减半 2.3s。质量敏感(候选裁剪影响召回上限),必须 eval;v1.1.0。
- **S2 思考 UX 策略(PD)**:保留生成思考时,以诚实阶段反馈("正在组织答案…")填充空窗;**禁止**伪造流式/假进度(§17 红线)。
- **S3 httpx 客户端复用/连接池**:实测延迟收益 ≈0;作卫生项随其他改动顺带,不单独立项。
- **S4 .env DEEPSEEK_MODEL=pro 清理**:生产运维项(需授权);并在 release 治理上确保 DB provider 行成为唯一权威(与 Issue#10 链路一致)。
- S5 context 总量上限:仅成本杠杆,不建议以延迟名义立项。

## 14. Performance SLO Recommendation(基于证据,待 Planner 拍板)

| 指标 | 生产现状(p50/p90) | v1.0.1 SLO 建议 | v1.1.0 方向 |
|---|---|---|---|
| TTFT(服务端,首 content delta) | 5.9s / 17.5s | **≤2.5s / ≤6s** | ≤2s / ≤4s |
| 前置链(intent→rerank 完成) | ~5.2s / — | ≤3.5s | ≤2.5s |
| E2E total(问答轮) | 18.4s / 35.9s | **≤10s / ≤20s** | ≤8s / ≤15s |
| 短路路径(social/clarify/override) | ≤35ms | 保持 ≤100ms | — |

产品方向锚:普通 grounded 问答应在**数秒级**出现首段可见内容;Kapa 自述典型 ~3s 量级(mcp 文档口径)作竞争参考,不照抄实现。

## 15. Frozen Product Contracts

### PERFORMANCE_CONTRACT(PERF-C1,CamThink V1)

1. **TTFT semantics**:服务端 TTFT = `llm.stream(messages, task="generation")` 发起到**首个 content delta** 到达(现行 `first_token_ms` 口径不变);被丢弃的 reasoning delta 不算 first token。
2. **First useful content**:客户端首个 `token` SSE 事件(经 CitationStreamFilter 放行)到达;`sources` 事件非 first content。
3. **E2E latency**:`complete` 事件 `response_time_ms`(现行口径)。
4. **Telemetry(必须)**:`traces.stages` 继续完整记录五阶段;**新增**每次 LLM 调用记录 `model`、`thinking_mode`(on/off)、TTFT;生成完成后记录 `usage.prompt_tokens/completion_tokens/reasoning_tokens`(stream 侧经 `stream_options.include_usage` 或等价手段)。不可观测的加速一律无效。
5. **Correctness preservation(不可回退)**:#5 产品边界、#19 对比语义、CIT 引用校验(流式+终验)、abstention/no-evidence、语言链路(Stage⑯)、空流守护(PC-01)全部维持现行验收口径。
6. **Provider/model traceability**:每请求可从 trace 复原 provider/model/参数;禁止 hardcode 单一 provider 路径;思考控制参数必须能力探测 + fail-open(老端点行为不变)。
7. **Streaming behavior**:token 逐条转发;禁止 fake streaming / 假进度 / 隐藏 provider 延迟;阶段反馈(若做)必须是真实阶段状态。
8. **SLO**:以 §14 为验收基线(Planner 拍板后冻结数值)。

### PERFORMANCE_ACCEPTANCE_MATRIX(Executor 如何证明 FASTER 且 NOT LESS CORRECT)

| 维度 | 证明方式 | 通过线 |
|---|---|---|
| FASTER-1 TTFT | 8 题 benchmark ×3 轮,前后对照 | p50 改善 ≥50%,且逐题均不劣化 |
| FASTER-2 前置链 | 同上,intent/rewrite/rerank 分阶段 | intent+rewrite 合计 ≤1.5s |
| FASTER-3 E2E | 同上 total_ms | p50 ≤10s |
| CORRECT-1 语义验收 | 93 场景子集(≥30 场景)+ 8 题 | 与 v1.0.0 验收同口径全过 |
| CORRECT-2 引用 | citation 悬空/无据率 | 零回归 |
| CORRECT-3 abstention | 无证据题(题 7)行为 | 保持拒答,禁止硬答 |
| CORRECT-4 产品边界 | 题 4/5(#5/#19 断言) | 全过 |
| CORRECT-5 intent | benchmark intent 分类 vs 现行基线一致率;JSON 合法率 | 记录并报告;JSON 合法率 100%;一致率不显著回退(容差由 Planner 复核) |
| OBS-1 可观测 | trace 含 model/thinking_mode/usage | 100% 覆盖 |

## 16. Change Boundary

允许:LLM 请求参数层(thinking 控制、max_tokens、include_usage)、前置任务编排(并行化)、trace 遥测增强、`deepseek.py` 客户端卫生项、intent 缺陷修复。
不允许(本契约期):检索/重排语义与阈值改动(除非 S1 立项走 eval)、prompt 正文改写、citation/abstention/边界逻辑任何改动、供应商切换或 hardcode、生产 .env/DB 变更。

## 17. Regression Constraints

- 不得回归 #5(Issue#5 契约全量断言)、#19(对比正确性)、CIT 引用完整性、Stage⑯ 语言链路、lead capture 语义。
- 不得以任何形式伪造速度(假流式/假进度/隐藏延迟/盲目截断答案)。
- 全量后端测试 + admin vitest/build 零回归;新增遥测字段向后兼容(trace JSONB)。

## 18. Production Impact

本门零生产变更。QW-1/QW-2 落地为镜像发布,经既有 v1.0.x 发布治理(Issue#10 链路:tag→RELEASE.json→update.sh)上线;无迁移、无数据修复。部署后建议观测 24h TTFT 分布验证 SLO。

## 19. Open Questions(待 Planner/用户)

- **PD-1**:QW-2 生成关思考是否搭乘 v1.0.1(以 CORRECT 矩阵全绿为前提);不搭乘则 v1.1.0 或走 S2 诚实进度提示。
- **PD-2**:是否增加"检索完成/正在组织答案"诚实阶段提示(widget UX,不涉模型)。
- **PD-3**:SLO 数值拍板(§14 建议值)。
- **PD-4(运维,需生产授权)**:生产 `.env` `DEEPSEEK_MODEL=deepseek-v4-pro` 回退雷清理(08-31 拍板遗留)。
- **PD-5**:intent 静默 fail-open 缺陷(本门新发现)随 QW-1 修复;其"分类正确性容差"由 Planner 复核。

## 20. READY / NOT READY Decision

**DISCOVERY PASS —— READY_STATUS = READY**

证据完备:瓶颈已定位到机制级(思考 delta 丢弃 + 思考时长非确定性),修复杠杆已实证有效且可 fail-open,正确性门与验收矩阵已冻结,QW-1 边界清晰、爆炸半径小,可立即起草 Executor contract(建议与 v1.0.1 其余轨道合并评审)。

## 21. Evidence Appendix(实验原始输出摘录)

```
# 实验①(flash,流式,T4→api.deepseek.com)
tiny_run1-5   prompt_tok=294  ttfc=998/1279/887/640/949ms  ttfb=144-262ms
mid20_run1-2  prompt_tok=2650 ttfc=2375/677ms
large55_run1-2 prompt_tok=6990 ttfc=1087/1045ms
tiny_reuse1-3(连接复用) ttfc=984/1564/888ms(无显著差异)
pro_large55_compare ttfc=4107ms reasoning deltas=136

# 实验②(anchor 原题+真实上下文)
install_flash_default_1 ttfc=795ms  reasoning_tok=35
install_flash_default_2 ttfc=3728ms reasoning_tok=412
install_flash_thinking:disabled ttfc=477ms  reasoning_tok=None(0 delta)out=757字符
install_flash_enable_thinking:false   reasoning_tok=46(无效)
install_flash_reasoning_effort:low    reasoning_tok=32(无效)
fact_flash_default_1-2  ttfc=733/1339ms

# 实验③(intent/extract 任务原 prompt,非流式)
intent ON  NeoRuntime…: 1881ms completion_tok=128 reasoning_tok=128 JSON✗(空→fail-open product)
intent OFF 同题:         633ms completion_tok=34  JSON✓(support)
intent ON/OFF NE301功耗: 1087/865ms 双✓(product)
intent ON/OFF 长口语题:  1044/930ms 双✓(product)
extract ON/OFF ×3 题:    675/994/2116 vs 455/602/718ms,输出等长等义
```

生产 SQL 均为只读 SELECT;实验脚本为临时文件,执行后即删,未入仓未落生产盘。
