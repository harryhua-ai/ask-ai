# CONTRACT PERF-P1 — Issue #23 Performance Patch(v1.0.1 Track D)

- **冻结人**: Planner(Role A)2026-09-04,依据 Discovery 报告 `docs/implementation/CAMTHINK_ISSUE_23_ANSWER_PERFORMANCE_DISCOVERY_2026-09-04.md`(docs a88cad3)
- **执行模式**: PARALLEL — Executor(track-d);**禁止触碰**在跑的三轨道 worktree(`.worktrees/v101-track-a-issue19` / `v101-track-b-reliability` / `v101-track-c-ops-health` 及其分支)
- **BASELINE_COMMIT**: `0e6a8a3`(= origin/main = 生产 v1.0.0;与 A/B/C 三 track 同基线)
- **分支/工作树(新建)**: `v1.0.1/track-d-performance` @ `.worktrees/v101-track-d-performance`
- **与 A/B/C 预期冲突面**: 零(LLM 层文件其三轨未涉);集成门必须实测验证

---

## 1. 授权范围(AUTHORIZED — 全部实现于本 track)

| # | 项 | 冻结要求 |
|---|---|---|
| A1 | **QW-1 辅助任务关思考** | routing task ∈ {`intent`, `query_rewrite`} 的 LLM 请求体携带顶层 `"thinking": {"type": "disabled"}`(已在 api.deepseek.com 实证有效)。**能力门控 + fail-open**:端点拒绝该参数(如 400)时,去掉参数重试一次并记录 `thinking_mode="unsupported"`;provider 配置可显式关停。lead_qualification 任务**不在**范围(保持现状)。 |
| A2 | **INTENT 正确性修复** | `classify_intent` 不得再因 reasoning 耗尽 `max_tokens` 而**静默** fail-open:content 为空/纯空白 → 显式 anomaly 日志 + telemetry 记录 + 结构化 fail-open 理由落 trace。max_tokens 余量(如 256/512)由 Executor 定,须守住延迟预算(intent 链 ≤0.9s p50,见 G2)。 |
| A3 | **QW-2 生成任务思考控制(实现+评测,合并门控)** | generation 请求支持思考关闭,**配置开关控制**(建议 env `LLM_GENERATION_THINKING_DISABLED`,默认 `false`=现状)。评测开启跑验收;**合并进 v1.0.1 集成的唯一条件 = G1×G2×G3 全绿**(FASTER × NOT LESS CORRECT);不过门 → 开关保持默认 false 照常交付 + 报告 RE-PLAN。 |
| A4 | **ENV 回退对齐(repo 侧)** | `.env.example`(现 `DEEPSEEK_MODEL=deepseek-chat`)与 `backend/config.py` 缺省值(现 `"deepseek-chat"`)对齐为 `deepseek-v4-flash`;启动日志输出生效的回退模型。**生产 T4 `.env` 的实际修改 = 发布门事项,Executor 禁止触碰生产。** |
| A5 | **PERF-C1 遥测** | `traces.stages.{intent,rewrite,generate}` 增加 `model` + `thinking_mode`;`generate` 增加 `usage.prompt_tokens/completion_tokens/reasoning_tokens`(流式经 `stream_options: {"include_usage": true}`,provider 拒绝时静默降级为缺失)。不可观测的加速一律无效。 |

## 2. 禁止范围(NOT AUTHORIZED)

上下文裁剪/最小充分上下文(未被授权为延迟修复);rerank 结构性改动(候选预截/设备/阈值);进度提示 UX(PROGRESS UX DEFER);prompt 正文改写;供应商切换或 hardcode;检索/重排语义与阈值;生产部署/生产数据/生产配置变更(含 T4 `.env`);触碰三在跑轨道。

## 3. 验收门(= Discovery 报告 §15 矩阵的实例化)

**FASTER(8 题 benchmark × 3 轮,原始数据逐轮入报告附录)**
- **G1-1 TTFT**:QW-2 开启 vs 基线(同轮次对照),generation TTFT p50 改善 ≥50%,且逐题不劣化
- **G1-2 前置链**:intent+rewrite 合计 p50 ≤1,500ms(现值 ~2,850ms)
- **G1-3 E2E**:benchmark 台架 p50 ≤10s(QW-2 开启;生产侧 SLO 绝对值验证在部署后按 v1 目标复测再校准)

**NOT LESS CORRECT**
- **G2-1 语义**:93 场景验收子集(≥30 场景)+ 8 题 benchmark,v1.0.0 同口径全过(#5 产品边界、#19 对比、CIT、语言链路)
- **G2-2 引用**:悬空/无据剔除率零回归
- **G2-3 abstention**:无证据题保持拒答
- **G2-4 intent**:benchmark intent JSON 合法率 **100%**;与现行基线分类一致率逐题记录(容差由 Planner 复核);静默 fail-open 缺陷不再出现(有 anomaly 遥测证明)
- **G3 回归**:后端全量离线测试(`HF_HUB_OFFLINE=1` + 隔离 `TEST_DATABASE_URL`)零新增失败;admin/widget 若被触碰须 vitest/tsc/build

**SLO(冻结的 v1 目标,部署后生产复测)**:TTFT p50 ≤2.5s / p90 ≤6s;E2E p50 ≤10s / p90 ≤20s。

## 4. Benchmark 台架协议

- 8 题集见 Discovery §10(Simple Fact / Installation / Troubleshooting / Single-product / Comparison / Ambiguous / No-evidence / Long grounded)
- 台架:本地/开发栈 + 已同步语料(**报告必须写明语料 provenance 与新鲜度**);TTFT 与前置 LLM 链为 provider 侧指标与硬件无关,rerank 数值标注硬件特异性(本 track 不优化 rerank)
- 允许辅以生产容器内直连 provider 的受控探针(thinking on/off 对照,同 Discovery §21 方法);API key 绝不入日志/报告/提交
- 每轮记录:TTFT/total/intent/rewrite/retrieve/rerank/gen/tokens/provider/model/thinking_mode

## 5. Worktree Bootstrap(惯例)

物理拷贝 `.env` 与 `models/`(禁止 symlink)、`HF_HUB_OFFLINE=1`、隔离测试库 `TEST_DATABASE_URL`;worktree 后端联调需独立 `.env` 拷贝。

## 6. 交付物

1. `FINAL_COMMIT` 推送 `origin/v1.0.1/track-d-performance`(零生产触碰)
2. 执行报告 `docs/implementation/CAMTHINK_ISSUE_23_PERFORMANCE_PATCH_EXECUTION_2026-09-04.md`(含:变更清单、验收矩阵逐门证据、benchmark 原始 JSONL、thinking 能力门控行为证明、PRODUCTION_MUTATIONS: NONE)
3. 结构化回执:STATUS / BASELINE / FINAL_COMMIT / G1×G2×G3 逐门结果 / QW-2 合并建议 / KNOWN_LIMITATIONS / REPORT_PATH / REPORT_COMMIT / PRODUCTION_MUTATIONS

## Appendix A — Executor 可拷贝提示词(委托时整段复制)

```
Task: CamThink V1 Issue #23 Performance Patch — v1.0.1 Track D(QW-1 + intent 正确性修复 + QW-2 实现与评测 + env 回退对齐 + PERF-C1 遥测)
Mode: PARALLEL Executor(track-d)。BASELINE_COMMIT: 0e6a8a3(origin/main)。新建 worktree .worktrees/v101-track-d-performance,分支 v1.0.1/track-d-performance。
禁止:触碰 .worktrees/v101-track-{a-issue19,b-reliability,c-ops-health} 三轨道及其分支;生产部署/生产数据/生产配置(含 T4 .env);上下文裁剪;rerank 结构改动;进度 UX;prompt 正文改写;供应商 hardcode。
契约:docs/engineering/CONTRACT_ISSUE23_PERFORMANCE_PATCH_20260904.md(权威,逐条遵守)。
核心要求:
1) intent/query_rewrite 任务请求加顶层 "thinking":{"type":"disabled"},400 拒绝时去参重试一次并记 thinking_mode=unsupported(fail-open,provider 配置可关停);lead_qualification 不动。
2) classify_intent 空 content 不再静默 fail-open:显式 anomaly 日志 + trace 结构化理由;max_tokens 余量自定但 intent 链 p50 ≤0.9s。
3) generation 思考开关 LLM_GENERATION_THINKING_DISABLED(默认 false);评测开启执行验收。
4) .env.example 与 backend/config.py 的 deepseek-chat 缺省对齐为 deepseek-v4-flash + 启动日志输出生效回退模型。
5) traces.stages.{intent,rewrite,generate} 增 model+thinking_mode;generate 增 usage(prompt/completion/reasoning tokens,include_usage,失败静默降级)。
验收:契约 §3 全门(8 题 benchmark ×3 轮逐轮原始数据;93 场景子集 ≥30;全量离线回归)。
交付:FINAL_COMMIT 推 origin/v1.0.1/track-d-performance;报告 docs/implementation/CAMTHINK_ISSUE_23_PERFORMANCE_PATCH_EXECUTION_2026-09-04.md;结构化回执含 PRODUCTION_MUTATIONS(必须 NONE)。
STOP after commit/report/push。不合并集成、不部署、不打 tag。
```
