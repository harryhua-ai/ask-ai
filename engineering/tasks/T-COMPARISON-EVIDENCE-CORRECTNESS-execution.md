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

## 10. 首轮候选

候选 `64c43c5`(origin/worktree-exec/comparison-evidence-20260905)—— Planner 复审 **PARTIAL**(2 阻断,见 REV1)。

---

## REV1 — 比较语义两阻断修复(2026-09-06)

- **Planner 判定**:PARTIAL(Blocker 1 维度语义 / Blocker 2 代码导向比较);管线架构整体 ACCEPTED。
- **修复提交**:`56aed49b4e2cd1cba986823d4384a0058ed3755f` @ 同分支(已推送,远程核验一致;血统 073f262→64c43c5→56aed49)。

### R1. 修复设计

**Blocker 1(维度语义)**:固定聚焦模板 `"<展示名> overview specifications features capabilities"` 丢失用户请求的比较维度。
- 新增 `_comparison_dimension(query, taxonomy, targets)`:确定性合成维度 —— 剥离目标词形(展示名/slug/大写形)与引导停用词(compare/and/vs/versus/的区别…)后剩余实质片段(零 LLM、零产品硬编码);无实质剩余 → 空串;
- `_target_evidence_query` 增维度参数:有维度 → `"<展示名> <维度>"`(目标身份+用户维度并存;形状与生产校准过的单产品成功查询 "NE301 battery life" 一致);无维度 → 原验证模板。整句对比查询仍不直接作为重排查询(H2 不回潮);
- trace 暴露 `dimension` / `code_oriented`(rerank stage)。

**Blocker 2(代码导向比较)**:分层配额对一切比较 code-last。
- 新增 `_is_code_oriented_comparison(text)`:确定性词面判定(通用技术词表 code/firmware/sdk/api/driver/implementation/固件/代码/…,零产品硬编码);
- `_merge_per_target_candidates` 增 `code_priority` 参数:代码导向比较 → `competitive`(代码与非代码按融合序公平竞争配额,相关代码不被非代码自动饿死);通用比较 → `tiered`(tier1-first 不变);trace `selection` 字段记录模式。

### R2. 变更文件

- `backend/pipeline/rag.py`:上述两函数 + merge 参数 + pipeline 接线(raw_query 入参、维度合成、模式选择)+ 3 处 trace 暴露;
- `tests/pipeline/test_comparison_evidence_correctness.py`:fake reranker 升级为维度敏感(维度词须真实进入聚焦查询才命中);新增 REV1 fixtures(MIXED/FWMIXED)与 3 用例(C/D/E)。

### R3. 阻断证据(确定性测试,先 RED 后 GREEN)

| 用例 | 场景 | RED(64c43c5) | GREEN(56aed49) |
|---|---|---|---|
| C `test_attribute_specific_comparison_surfaces_dimension_evidence` | "…power consumption",泛文档在前 | 聚焦句无维度 → generic 规则 → 泛 overview 过阈、功耗文档被滤 | 聚焦句含 "power consumption",双侧功耗证据胜出进 sources |
| D `test_code_oriented_comparison_lets_code_compete` | "…firmware architecture",官方文档+相关固件 | 代码被分层挡在配额外,代码证据不可达 | competitive 模式,相关固件证据入配额、过阈、进生成 |
| E `test_generic_comparison_code_does_not_regain_quota` | 同 D 语料 + generic 比较 | —(已过) | 仍过:无关代码不得回潮(锁定意图敏感,而非撤销 H1) |

### R4. 全量回归 / lint

- 聚焦:comparison 13/10→**13/13**;pipeline 目录 493 绿;
- 离线全量(隔离库 ask_ai_test_cmp2,用后已 DROP):**1705 passed / 3 skipped / 0 failed**;
- ruff / black(改动文件)全绿。

### R5. 生产等价只读复现(真语料 + 真 LLM 直调 answer(),零生产触碰;脚本已清除)

| 查询 | dimension | selection | own_after_rerank | 结果 |
|---|---|---|---|---|
| Compare NE503 and NE301 | ''(generic) | tiered | {ne503:5, ne301:3} | **answered**,双侧 sources(wiki/官网/商店),真 LLM 产出产品定位/架构对比 |
| Compare NE301 and NE503(反转) | '' | tiered | {ne301:3, ne503:4} | **answered**,双侧 sources |
| Compare NE301 and NE503 supported AI models(属性) | 'supported ai models' | tiered | {ne301:5, ne503:5} | **answered**,真 LLM 产出双侧 AI 模型对比(NE301 TFLite Int8/STM32N6 480×480/10MB vs NE503 侧) |
| Compare the NE301 and NE503 firmware architecture(代码导向) | 'firmware architecture' | **competitive** | {ne301:4, ne503:3} | **answered**,真 LLM 产出固件架构对比(TFLite Int8 量化推理…) |
| Compare NE301 and NE503 power consumption(对照) | 'power consumption' | tiered | {ne301:3, **ne503:0**} | **诚实 fail-closed**:真语料中 NE503 侧无合格功耗官方证据 → 按契约拒答并明示缺侧(C5:拒答反映真实证据可用性) |

维度可用性扫描(证据管线只读遍历):battery life/ne503=0、storage/ne301=0、sensor options/ne503=0 为单侧;wireless connectivity(3/4)、networking(4/4)、supported AI models(5/5)、power supply(2/4)双侧支撑 —— 属性比较证据选取了双侧支撑的维度,同时保留单侧维度拒答作为 fail-closed 正面证据。

### R6. REV1 候选

候选 `56aed49` —— Planner 复审 **PARTIAL**(2 阻断,见 REV2)。

---

## REV2 — 真融合序竞争 + 词边界判定(2026-09-06)

- **Planner 判定**:REV1 PARTIAL(Blocker 1 competitive 非真融合序 / Blocker 2 子串误报);架构整体 ACCEPTED。
- **修复提交**:`503c22954ac6de6fe2a2555a3b23672989ab060f` @ 同分支(已推送,远程核验一致;血统 073f262→64c43c5→56aed49→503c229)。

### R2.1 修复一:competitive 改为原始融合序竞争(Blocker 1)

- 根因:`(t1+t2)[:quota]` 中 t1/t2 已按代码/非代码重排,拼接后非代码恒在代码前;非代码数 ≥ quota 时相关代码零槽位。
- 修复:`_merge_per_target_candidates` 收集阶段另存 `own_fused[t]`(每 target 原始融合序的全部自有候选,跨路去重语义不变);`code_priority=True` 时 `keep = own_fused[t][:quota]` —— 代码与非代码按原始 RRF 排序公平竞争;`tiered`(generic)保持 tier1-first 完全不变。

### R2.2 修复二:代码导向判定改词/短语边界(Blocker 2)

- 根因:子串匹配产生 "capital"⊂api、"rapid startup"⊂api、"power source"⊂source 误报,误触发 competitive → 固件污染普通产品比较。
- 修复:`_is_code_oriented_comparison` 重写 —— 英文 token 化(`[^a-z0-9]+` 切分)后命中单 token 词表(code/firmware/sdk/api/apis/driver(s)/implementation/implement/middleware),或命中短语 "source code"(bigram);**"source" 单词不再判定**;中文按实现语义词子串(固件/源码/代码/驱动实现)。确定性保持,零产品硬编码。

### R2.3 RED 证据(56aed49 上先失败)

| 测试 | RED 失败点 |
|---|---|
| `test_competitive_selection_preserves_fused_order`(quota=5,相关代码融合序位 2,后随 4+ 非代码) | sources 无 fw/scheduler —— 相关代码被 (t1+t2)[:5] 挤掉,不可达生成 |
| `test_code_orientation_lexical_boundaries`(9 True/7 False 例表) | "capital cost"/"rapid startup"/"power source" 误判 True |
| `test_false_positive_source_keeps_tiered_selection` | "power source" 比较 code_oriented=True / selection=competitive(应 false/tiered) |

### R2.4 GREEN 与回归

- comparison 套件 **17/17**(含 REV2 新增 4:拥挤语料竞争、拥挤语料 generic 控制、词边界例表、false-positive tiered 保持);
- pipeline 目录 **497 绿**;离线全量(隔离库,用后已 DROP)black 前后各一轮:**1709/0** 与 **1708 passed / 4 skipped / 0 failed**;
- ruff / black(改动文件)全绿;顺带清理基线以来遗留的重复旧定义与本轮引入的过渡占位。

### R2.5 生产等价只读复现(真语料+真 LLM 直调 answer(),零生产触碰;脚本已清除)

| 查询 | dimension | code_oriented | selection | own_after | 结果 |
|---|---|---|---|---|---|
| Compare NE503 and NE301 | '' | false | tiered | 5/3 | answered,双侧 sources |
| Compare NE301 and NE503 | '' | false | tiered | 3/4 | answered,双侧 sources |
| … supported AI models | 'supported ai models' | false | tiered | 5/5 | answered(双侧 AI 模型对比) |
| … firmware architecture | 'firmware architecture' | **true** | **competitive** | 4/3 | **answered,真语料代码证据进入生成**(sources 含 github.com/camthink-ai/ne301/.../OTA 代码页) |
| … power source reliability(非代码 "source" 用法) | 'power source reliability' | **false**(不误判) | **tiered** | 2/3 | answered(电源可靠性对比,真语料双侧支撑) |

### R2.6 answer/stream parity

共享 `_comparison_evidence_pipeline` 未动签名语义;REV2 全部新用例走 stream_answer,parity 用例(answer+stream 同场景同结果)保持通过;两路 trace 均携带 dimension/code_oriented/selection。

### R2.7 REV2 候选

候选 `503c229` —— Planner 复审 **PARTIAL**(1 阻断 + 2 parity 缺陷,见 REV3)。

---

## REV3 — 比较感知剪枝 + parity 修复(2026-09-06)

- **Planner 判定**:REV2 两阻断 ACCEPTED;新阻断 = 剪枝不感知比较语义;另 2 parity 缺陷。
- **修复提交**:`346d3e6fa6e138da82d115f9608398640f475596` @ 同分支(已推送,远程核验一致;血统 073f262→64c43c5→56aed49→503c229→346d3e6)。

### R3.1 根因(剪枝伪象)

比较流:per-target 检索 → 均衡配额 → 聚焦重排 → 合并 → **全局 LLM 剪枝(整句查询,全局评估合并集)** → D-preflight。全局剪枝可把聚焦重排后某侧的全部合格证据剪除,D-preflight 把剪枝伪象误读为证据缺失 → 误拒。C1/C3 修复被后置剪枝回退。

### R3.2 修复设计(最小,共享抽象内)

比较路径剪枝移入 `_comparison_evidence_pipeline`(聚焦重排之后):
- **逐侧聚焦剪枝**:每侧以该侧聚焦句(目标身份+请求维度)调 `self._pruner.prune(...)` —— 与该侧重排完全同语义(C3 贯穿);
- rest 以对比句剪枝(supplement 语义不变);
- 剪后轮转交错 → D-preflight(口径不变);
- **外层全局剪枝对比较路径跳过**(`cmp_stage_info is None` 守卫;非比较路径不变,不禁用);
- 噪声仍可剪(聚焦语义下无关证据照样被删);真缺失仍 fail-closed。

parity 缺陷修复:
1. answer() 比较分支 `pre_prune_count=0` 未设 → 负 pruned_count;现比较分支 pruned_count 由管线返回(= Σ逐侧(重排后−剪后)),恒 ≥0;外层剪枝跳过不再二次污染;
2. 两路 prune 查询不同源(answer=search_query / stream=raw query)→ 比较剪枝统一为管线内聚焦逐侧调用(测试 F 断言两路 pruner 收到的全部是聚焦句)。

trace:rerank stage 新增 `per_target_after_prune`(与 `per_target`/own_after_rerank 区分)+ `pruned`(总剪除)—— 剪枝致单侧消失可直接诊断;无全文落盘。

### R3.3 RED 证据(503c229 上先失败,6 用例)

A(全局饿死→误拒)/ B(噪声仍剪+逐侧聚焦调用断言)/ C(属性维度穿越剪枝)/ D(代码证据穿越剪枝)/ G(pruned_count 精确非负,两路)/ F(parity 剪枝形状)—— 全部 RED;E(真缺失)在基线即通过(守护)。

### R3.4 GREEN 与回归

- comparison 套件 **24/24**(REV3 新增 7);pipeline 目录绿;
- 离线全量(隔离库 ask_ai_test_cmp4,用后已 DROP):**1716 passed / 3 skipped / 0 failed**;
- ruff / black(改动文件)全绿。

### R3.5 生产等价只读复现(**剪枝器实际启用**:真 LLMPruner 注入,pruning routing available=True;真语料+真 LLM 直调 answer(),零生产触碰;脚本已清除)

| 查询 | selection | after_focused_rerank | after_prune | 结果 |
|---|---|---|---|---|
| Compare NE503 and NE301 | tiered | {ne503:5, ne301:2} | 同左(pruned 0) | **answered** 双侧 sources |
| Compare NE301 and NE503 | tiered | {ne301:3, ne503:4} | 同左 | **answered** 双侧 sources |
| … supported AI models | tiered | {ne301:5, ne503:5} | 同左(fail-open×2,见下) | **answered** |
| … firmware architecture | **competitive** | {ne301:2, ne503:2} | 同左 | **answered**,真代码 chunk(NE301 Drivers 页)入上下文 |
| … power consumption | tiered | {ne301:3, **ne503:0**} | {ne301:3, ne503:0} | **诚实 fail-closed**(真缺失,剪枝未编造) |

观测注记:supported AI models 场景 pruning LLM 两次返回格式异常 → fail-open 保留全部(既有安全方向:fail-open 只可能多保留,不可能饿死单侧);聚焦语义下真语料证据全部被判相关,pruned_total=0 —— 「剪枝启用后不再饿死单侧」由生产语料直接实证,「噪声仍可剪」由确定性测试 B 证明。

### R3.6 REV3 候选

候选 `346d3e6` —— Planner 复审 **PARTIAL**(answer 终态覆盖阻断 + 测试空洞,见 REV4)。

---

## REV4 — 终态覆盖缺陷修复 + 非零剪枝证明链(2026-09-06)

- **Planner 判定**:REV3 核心架构 ACCEPTED;阻断 = answer() 比较 trace 丢失真实 pruned_count;测试缺口 = REV3 噪声 fixture 空洞绿。
- **修复提交**:`cdbcad38fc3512561e12c71ff6eda067d06257b5` @ 同分支(已推送,远程核验一致;血统 …→503c229→346d3e6→cdbcad3)。

### R4.1 覆盖根因与修复

- answer() 比较分支局部 `pruned_count` 保持初值 0(管线真值只写进了 stages 初建,外层剪枝又被跳过);公共终态 `stages["rerank"]["pruned"] = pruned_count` 把正确值覆盖为 0 → answer 与 stream 不一致,REV3-G 被违反。
- 修复(一行,与 stream 同源):answer() 比较分支 `pruned_count = cmp_stage_info["pruned_count"]`;公共终态保留。

### R4.2 连带发现:trace 语义冲突(D-preflight 覆盖)

stream/answer 两处 D-preflight 把「剪枝+纵深过滤后的最终计数」覆写进 `own_after_rerank` —— 挤掉「聚焦重排后」语义,导致剪枝事件在 trace 中不可诊断(own_after_rerank == after_prune)。修复:最终计数写独立字段 **`own_final`**;`own_after_rerank`(聚焦重排后)与 `per_target_after_prune`(剪枝后)构成两段轨迹,`own_final` 为终态。

### R4.3 测试空洞修复(非零剪枝证明链)

- 原噪声 fixture 无 OFFICIAL 标记 → 在聚焦重排即被滤除 → after_rerank == after_prune(0==0),answer 覆盖 bug 逃逸;
- 修正:噪声文档含 OFFICIAL(过聚焦重排、幸存计入 after_rerank)但无 KEEP(被 pruner 删);fake pruner 记录 `received`(查询+收到 id);
- 证明链(E):噪声 ①幸存聚焦重排(after_rerank > after_prune)②被送达 pruner(received 含 noise id)③被删除(after_prune/sources 不含)。

### R4.4 RED 证据(346d3e6 上)

6 用例先失败:A(4 > 4 不成立——trace 覆盖致 delta 不可见)、B(answer pruned=0 ≠ N-M)、C(stream 通过,作对照)、D(parity:0 ≠ 2)、E(证明链断于覆盖)、以及既有 G 用例(0==0 空洞暴露)。

### R4.5 GREEN 与回归

- comparison 套件 **29/29**(REV4 新增 5);pipeline 目录绿;
- 离线全量(隔离库 ask_ai_test_cmp5,用后已 DROP):**1721 passed / 3 skipped / 0 failed**;
- ruff / black(改动文件)全绿。

### R4.6 聚焦生产等价只读复现(answer 路径=此前覆盖 bug 路径;真语料+真 LLM+剪枝启用;脚本已清除)

| 查询 | selection | after_focused_rerank | after_prune | own_final | pruned | 三值自洽 |
|---|---|---|---|---|---|---|
| Compare NE503 and NE301 | tiered | {ne503:5, ne301:3} | {ne503:5, ne301:2} | {ne503:5, ne301:2} | **1** | ✓ (pruned = n-m, ≥0) |
| Compare the NE301 and NE503 firmware architecture | competitive | {ne301:4, ne503:3} | {ne301:2, ne503:2} | {ne301:2, ne503:2} | **3** | ✓ |

真语料下出现真实非零剪枝(1 与 3)——聚焦剪枝在生产语料上确实剪除无关候选;两段轨迹(after_focused_rerank → after_prune → own_final)完整可诊断。

### R4.7 REV4 候选

候选 `cdbcad3` —— 进入 FINAL VERIFICATION GATE(见下节)。

---

## FINAL VERIFICATION GATE — 新鲜可执行验证(2026-09-06)

- **模式**:VERIFICATION ONLY / READ-ONLY PRODUCTION OBSERVATION;零代码/数据/配置/生产变更。
- **结果**:**VERIFICATION PASS**

### F1. 候选身份

- `HEAD = cdbcad38fc3512561e12c71ff6eda067d06257b5`(精确匹配)
- 血统:`073f262` 为 HEAD 祖先(`git merge-base --is-ancestor` 通过);线性 5 提交 64c43c5→56aed49→503c229→346d3e6→cdbcad3
- worktree 状态:**clean**(无未提交改动);验证全程 SHA 未变(无 STOP 条件触发)

### F2. 新鲜测试验证(命令 + 退出码 + 计数)

| 验证项 | 命令(工作目录 = 候选 worktree) | exit | 结果 |
|---|---|---|---|
| 聚焦比较套件 | `.venv/bin/python -m pytest tests/pipeline/test_comparison_evidence_correctness.py -q -p no:cacheprovider` | 0 | **29 passed**, 31 warnings |
| Issue#19/boundary/citation/resolver/pruner/retrieval | `-m pytest tests/pipeline/test_issue19_comparison.py tests/pipeline/test_product_boundary_retrieval.py tests/pipeline/test_product_boundary_eval_matrix.py tests/pipeline/test_citation_product_eligibility.py tests/pipeline/test_product_resolver.py tests/pipeline/test_pruner.py tests/retrieval/ -q -p no:cacheprovider` | 0 | **136 passed** |
| CI 等价命令(同参数;本地项目 venv 替代 uv) | `-m pytest tests/ -q --ignore=tests/api/admin --ignore=tests/scripts/test_sync_db.py --ignore=tests/embedder --ignore=tests/e2e -p no:cacheprovider`(隔离库 ask_ai_test_verify,用后已 DROP) | 0 | **1414 passed, 172 warnings** |
| admin API 套件(CI 排除面的补充) | `-m pytest tests/api/admin -q -p no:cacheprovider` | 0 | **255 passed, 1 skipped** |
| ruff(4 个改动文件) | `ruff check backend/pipeline/rag.py tests/pipeline/test_comparison_evidence_correctness.py tests/pipeline/test_issue19_comparison.py tests/pipeline/test_accepted_changes_integration_gate.py` | 0 | All checks passed! |
| black --check(同文件) | `black --check -q …` | 0 | 通过 |

warnings 均为既有 deprecation/RuntimeWarning(mock 未 await 等),无失败;exclusions 与仓库 CI workflow 逐项一致。

### F3. REV4 非零剪枝契约(新鲜确定性回归,29 用例内)

- after_focused_rerank(6) > after_prune(4);pruned == 6−4 == **2 > 0**(双侧各一噪声);
- `answer_pruned == stream_pruned == 2`;`per_target_after_prune` 两路一致;answered 状态一致;
- 噪声证明链完整:①过聚焦重排(计入 after_rerank)②被送达 pruner(fake `received` 记录含 noise id)③被剪除(after_prune/sources 不含)。

### F4. trace 三字段语义(互不覆盖,新鮮验证)

`own_after_rerank`(聚焦重排后)/ `per_target_after_prune`(比较感知剪枝后)/ `own_final`(纵深过滤终态)三字段独立存在;非零剪枝 fixture 下 `own_after_rerank ≠ per_target_after_prune` 可观测(6 ≠ 4)。

### F5. 生产等价只读检查(真语料 + 真 LLM + **剪枝器实际启用**;answer 路径;零生产触碰;脚本已清除)

```
pruning_enabled: True
own_after_rerank: {'ne503': 5, 'ne301': 3}
per_target_after_prune: {'ne503': 5, 'ne301': 3}
own_final: {'ne503': 5, 'ne301': 3}
pruned: 0 (n-m = 0)
result_key: answered | is_answered: True
source products: ['ne301', 'ne503']
```

双侧均被代表;结果非误拒;真语料 pruned=0(可接受,非零证明由 F3 确定性回归权威承担);trace 三值自洽(pruned == n-m)。

### F6. 报告权威位置

- **工程报告存放于独立 docs 仓库**(与主仓互不可见,协议约定)
- Repository:harryhua-ai/ask-ai(主仓,代码)/ docs 本地仓(报告)
- Path:`docs/engineering/tasks/T-COMPARISON-EVIDENCE-CORRECTNESS-execution.md`
- Report commit:见本节所在 docs 仓 commit(含 REV0–REV4 完整历史 + 本 Final Verification 节)

### F7. 无变更确认

本门全程零实现改动、零生产数据/配置变更、零语料触碰;验证库与临时脚本均已清除;主仓 HEAD 未动。


---

## MERGE GATE — 受控集成(2026-09-06)

- **Planner 状态**:FINAL ENGINEERING REVIEW = PASS + FINAL VERIFICATION = PASS;授权集成,**不授权** tag/Release/部署/生产变更。
- **最终状态**:**MERGE PASS**

### M1. 预合并身份门

- `origin/main = 073f26236c08531212f6d5b12b8b8173f0557c79`(与期望基线精确一致)
- `origin/worktree-exec/comparison-evidence-20260905 = cdbcad38fc3512561e12c71ff6eda067d06257b5`(精确)
- `git merge-base --is-ancestor 073f262… cdbcad3…` 通过;candidate ahead 5 / behind 0;linear & fast-forwardable

### M2. 合并(FAST-FORWARD ONLY)

- `git checkout main && git pull --ff-only origin main && git merge --ff-only origin/worktree-exec/comparison-evidence-20260905`
- 推送前 `git rev-parse HEAD = cdbcad38fc3512561e12c71ff6eda067d06257b5`;正常 push(无 force)
- **无 merge commit / squash / replacement / amended commit**

### M3. 推送后身份(独立远端核验)

- `origin/main = cdbcad38fc3512561e12c71ff6eda067d06257b5`
- `origin/worktree-exec/comparison-evidence-20260905 = cdbcad38…`(候选分支保留,未删除)

### M4. 托管 CI / 镜像构建

- Workflow:**Build & Push GPU Image — run id `33981057517`**(push main 触发,headSha=cdbcad38… 精确)
- URL:https://github.com/harryhua-ai/ask-ai/actions/runs/33981057517
- 结果:overall **success**;job `test` = success;job `build-and-push` = success
- 镜像 tag:`ghcr.io/harryhua-ai/ask-ai:sha-cdbcad3`(amd64 index,digest sha256:59d67a76…)
- 开发版本(main 快照):`0.0.0+main.cdbcad38`
- **in-image RELEASE.json 断言日志**:「in-image RELEASE.json: version=0.0.0+main.cdbcad38 git_sha=cdbcad38fc3512561e12c71ff6eda067d06257b5」(workflow 内 Assert 步骤,与候选 SHA 精确一致)

### M5. 生产安全边界确认

本门**未执行**:update.sh / docker compose pull / docker compose up / 生产重启 / 生产健康验收 / 数据或配置变更 / reindex;**未创建** version tag、GitHub Release;未使用 latest 部署。latest/SHA 镜像仅为集成工件。

### M6. 最终状态

**MERGE PASS** —— main = origin/main = cdbcad38fc3512561e12c71ff6eda067d06257b5;托管 CI 绿;生产部署等待后续显式 Release / Production Gate(使用不可变 release tag)。