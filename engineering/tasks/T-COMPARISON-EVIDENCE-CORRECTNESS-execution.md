# T-COMPARISON-EVIDENCE-CORRECTNESS 执行报告

- **任务**:P0 答案正确性热修 —— 双产品比较在双侧官方证据在场时被误拒(`comparison_evidence_insufficient`)
- **基线**:073f262(= main = v1.1.1 = 生产)
- **候选提交**:`64c43c5893096a431840159acfcd94bdd00720a9` @ `origin/worktree-exec/comparison-evidence-20260905`(已推送,远程核验一致)
- **worktree**:`/Users/harryhua/Documents/GitHub/ask-ai/.worktrees/comparison-evidence`
- **执行日期**:2026-09-05
- **最终状态**:**CANDIDATE READY**(待 Planner 验收)
- **PRODUCTION_MUTATIONS**:无(验证阶段仅容器内只读复现 + 真 LLM 直调,零 DB 写、零配置/文件变更)

---

## 1. 根因确认(承接冻结 RCA,实现证据零矛盾)

- **H1 候选构成污染**:ne301 资格空间 68,193 块被固件仓主导;per-target 配额 5 席按 RRF 序取 4 代码 + 1 官方 FAQ;
- **H2 对比句重排惩罚**:整句对比查询把该官方文档压至 0.2237 < 0.3(聚焦句式 0.7230);
- 叠加 → `own_after_rerank={ne301:0}` → D-preflight 按契约拒答。契约执行正确,其输入被两层排序失真污染。
- RCA 前置只读排查:见本任务调查记录(生产 trace 2b8bc7da + 容器内全路径复现,H2 受控实验 Q1/Q2/Q3)。

## 2. 实现设计与理由(Executor HOW)

**最小共享抽象:`_comparison_evidence_pipeline`**(RAGOrchestrator 方法),answer()/stream_answer() 同源调用,消除双路漂移:

1. **RC1 per-target 检索**(不变):每 target 以自身资格标签集独立跑三路融合;
2. **C1/C2 分层配额**(`_merge_per_target_candidates` 重构):目标自有候选分两层 —— tier1=官方产品证据(`chunk_type != "code"`,涵盖 wiki/官网/商店/规格资料)、tier2=代码;配额先由 tier1 按融合序填满,余量由 tier2 回填。理由:直接针对 H1 的构成问题;通用规则(按 chunk 类型,零产品硬编码);代码证据不消失,只在存在更相关官方证据时让出配额(AC6/AC7 保持);
3. **C3 按目标聚焦重排**(`_target_evidence_query`):每侧候选用确定性聚焦句 `"<展示名> overview specifications features capabilities"` 独立重排(零 LLM 调用)。措辞取自冻结 RCA H2 实验的验证句式(同文档 0.22→0.72,官方文档组 0.5→0.97),按 taxonomy 展示名泛化;
4. **共享/平台 rest 槽位语义不变**(对比句重排,仅 rest_cap>0 时参与)—— 平台证据保持 supplement(AC7);
5. **轮转交错**:逐侧幸存者按各自加权分排序后 round-robin 合并(双侧均衡),封顶 top_k;D-preflight 口径不变(最终证据逐侧计数),真缺失仍拒答(C4/C5/C6)。

## 3. 变更文件

| 文件 | 变更 |
|---|---|
| `backend/pipeline/rag.py` | `_merge_per_target_candidates` 分层重构(新签名 own/rest/stage);新增 `_target_evidence_query`、`_survivor_score`、`RAGOrchestrator._comparison_evidence_pipeline`;stream_answer 比较分支接入管线 + D-preflight 拒答 trace 补真实 retrieve/rerank 阶段;answer() 补比较分支 + D-preflight(parity)+ rerank stage 保留 per_target/candidates;顺带清理基线既有死变量 `rerank_fallback`(F841,ruff 实证 073f262 已存在) |
| `tests/pipeline/test_comparison_evidence_correctness.py` | 新增,AC1-AC6/AC8-AC10 + parity 共 10 用例(先 RED 后 GREEN) |
| `tests/pipeline/test_issue19_comparison.py` | merge 签名适配 + 新增分层回归 `test_official_evidence_fills_quota_before_code`;`_r` helper 加 chunk_type |
| `tests/pipeline/test_accepted_changes_integration_gate.py` | INT-G010 查询改单产品(原查询「NE301 与 NE503 的区别」意外落比较模式;其 fake 数据无逐侧证据,新契约下理应拒答;该测试断言目标是引用 URL 映射,单产品查询聚焦同一契约) |

## 4. 前后证据流(生产场景 "Compare NE503 and NE301")

**修复前**(生产 trace 2b8bc7da):检索正常(ne301 侧 5 候选)→ 整句对比重排 → `own_after_rerank={ne301:0, ne503:3}` → 拒答「couldn't find official information about NeoEye NE301」;拒答 trace 无 retrieve/rerank 阶段(UI 显示 0ms)。

**修复后**(生产等价复现,§7):ne301 侧 tier1 池 7 条(官方)先占 5 席(0 代码入配额)→ 聚焦句重排幸存 3、ne503 幸存 5 → 轮转交错进生成 → 真 LLM 产出双侧有据对比,`result_key=answered`,sources 含 ne503×3 + ne301×2,`retrieve 214ms / rerank 317ms` 如实入 trace。

## 5. 聚焦回归结果

- `tests/pipeline/test_comparison_evidence_correctness.py`:**10/10**(AC1 双侧有据生成;AC2 顺序无关;AC3/AC5 聚焦查询被实际使用+双侧官方证据入 sources;AC4 tier1_kept/own_after_rerank 断言;AC8 真缺失拒答+纯代码侧拒答;AC10 拒答 trace 阶段/计数/候选诊断;parity×2;AC6 单产品代码查询不受影响)
- `tests/pipeline/test_issue19_comparison.py`:9/9(含新分层回归)
- `tests/pipeline/` 全目录:**490 passed**

## 6. 全量回归 / lint

- 离线全量(隔离库 ask_ai_test_cmp,用后已 DROP):**1701 passed / 4 skipped / 0 failed**(46.2s;black 格式化后复跑确认)
- ruff / black(4 个改动文件):全绿

## 7. 生产等价只读复现(修复后,零生产触碰)

方法:backend 容器内按文件加载修复版 rag.py(importlib,PYTHONPATH 仍指向生产 /app 的其余模块)+ 生产真语料(Weaviate)+ 内部端点嵌入 + 真 BGEReranker(cuda)+ 生产 LLM 配置(DB providers);直调 orchestrator,零持久化。脚本已清除。

**A. 证据管线逐侧细目**:

```
tier1_pool: {ne503: 5, ne301: 7}   tier2_pool: {ne503: 0, ne301: 16}   ← H1 实证:代码 16 条被分层挡在配额外
tier1_kept: {ne503: 5, ne301: 5}   own_kept: {ne503: 5, ne301: 5}      ← 配额 5 席全为官方证据
own_after_rerank: {ne503: 5, ne301: 3}   missing_after_rerank: []
ne503: focused_query='NeoEye NE503 overview specifications features capabilities' survivors=5/5
ne301: focused_query='NeoEye NE301 overview specifications features capabilities' survivors=3/5
ne301 侧得分(聚焦句):wiki FAQ 0.836 / woo 2092#2 0.9952 / woo 2092#0 0.6996;未过阈者如实 None
```

**B. answer() 全管线直调**:

```
result_key: answered      is_answered: True
answer: "**Product Positioning** NE503 is a fixed-site, always-on 4K PoE edge AI camera
platform powered by Hailo-15H SoC with 20 TOPS … NE301 is a low-power wi…"(双侧有据)
sources: ne503×3(wiki/官网/商店)+ ne301×2(商店/wiki FAQ)—— 零 sibling 顶替
trace: retrieve 214ms / rerank 317ms(真实计时入 trace)
```

## 8. 可观测性结果

- D-preflight 短路拒答 trace 现包含:`retrieve{ms, hybrid_count, effective_min, path_counts, per_target}` + `rerank{ms, top_score, count, pruned, results, per_target{pool,survivors,focused_query}, candidates[{target,source_id,source_type,product,chunk_type,score}]}`;
- Admin 会话详情(读 `stages.retrieve/rerank`)不再对已执行阶段显示 0ms —— 后端修复,零 UI 改动;
- 被阈值滤除的候选 score=None(诚实口径),身份级诊断足以支撑未来 RCA,不落全文。

## 9. 残余风险

1. **聚焦句式为固定模板**:对描述型官方文档有效(RCA 实证),但若某 target 的官方证据以非概述型内容为主(如纯 API 参考),聚焦句仍可能压分 —— 由 AC8 fail-closed 兜底(拒答而非编造),且 trace 有 tier 池/幸存计数可观测;
2. **聚焦重排对代码同样有提分效应**(RCA H2 实验发现):分层配额先行挡住代码,但若某 target tier1 池为空,代码仍会占配额并在聚焦句下可能过阈进入上下文 —— 这是 C2 允许的 supplement,后续可在 Planner 授权下评估 product-intent 代码降权;
3. **INT-G010 gate 测试查询已改**(理由见 §3):该文件其余用例未动;
4. 基线既有 `test_query_preempts_queued_sync` CI 偶发(另行移交项)与本修复无关;
5. answer()/stream_answer() 比较路径外的既有不对称(如 page_boost 细节)未在本任务范围重排,既有 parity 测试守护。

## 10. 最终执行状态

**CANDIDATE READY** —— 候选 `64c43c5`(origin/worktree-exec/comparison-evidence-20260905),等待 Planner 验收。血统:073f262(v1.1.1)→ 64c43c5。
