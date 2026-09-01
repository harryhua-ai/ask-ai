# CAMTHINK V1 — P1 Generation Reliability Closure(执行报告)

- **任务**: P1_GENERATION_RELIABILITY(PARALLEL_GROUP = CAMTHINK_V1_LAUNCH_CLOSURE_G1,EXECUTOR = CODEX_B)
- **日期**: 2026-09-01
- **STATUS**: **PASS**(含 1 项按任务 §9 规定报告为 PARTIAL 的截断检测子项,见 KNOWN_RISKS)
- **BASELINE_COMMIT**: `76b2199ff334194a4e145c80ab844726d7e50293`(与冻结基线一致,未漂移)
- **FINAL_COMMIT**(产品代码仓): `5c06151ac12543de39ce16f016f5d86af034580c`
- **BRANCH**: `worktree-exec/p1-reliability`
- **WORKTREE**: `/Users/harryhua/Documents/GitHub/ask-ai-p1-reliability`(独立 worktree,与 Codex A 无共享目录)
- **REPORT_PATH**: `docs/implementation/CAMTHINK_V1_P1_GENERATION_RELIABILITY_2026-09-01.md`(本文档,docs 本地仓)
- **REPORT_COMMIT**: 见 docs 仓提交记录(文末)
- **未部署生产**:遵照 §18,仅实现+验证+提交+报告;未发布,未声明 V1 Launch PASS。

---

## 1. Root Cause(系统性调试结论)

逐层实证追踪:DeepseekProvider.stream(httpx SSE)→ LLMRegistry/LLMRouter.stream → RAGOrchestrator.stream_answer → `/api/ask` event_generator → Postgres 持久化 → widget `useSSE`(Admin LoginChat 复用同一 widget App)。

**RC-1(主因,对应 A05/E04-t2 静默空答)**:`backend/api/routes.py` 旧兜底守卫 `if not token_emitted and full_answer:` 只在 `full_answer` **非空**时补发(为拒答文本设计)。零内容路径上:provider 流 200 正常关闭、零内容 delta → `rag.stream_answer` 无条件发 `complete(answer="", is_answered=True)` → routes 侧 `token_emitted=False` 且 `full_answer=""` → 守卫不触发 → 持久化 `Conversation(answer="", is_answered=True)` → `done`。**空答案 + done、无任何失败信号**,与验收基线 A05(47.5s,0 answer tokens,sources+done 齐全)签名完全一致。

**RC-2(部分输出后中断伪装成功,对应 A11 候选机理)**:旧代码 mid-stream 异常时 `if not token_emitted:` 才发兜底;已发 token 后异常被完全吞掉,部分文本后直接 `done`,用户无法区分「答完了」与「断了」。持久化侧 `is_answered=False`(初值)但无 Trace 行(trace_payload=None),与拒答不可区分。

**RC-3(路由层重放缺陷,调查中新发现)**:`backend/llm/registry.py` `LLMRouter.stream()` 对**所有**异常一律 `continue` 切换下一供应商。当前供应商已产出 token 后中途超时(即 deepseek.py 注释中的 Q32/Q50 路径)会触发下一供应商**从头重放整段答案** → SSE 已发出内容重复输出。(单供应商链退化为抛 RuntimeError,多供应商链即内容重复。)

**RC-4(客户端失败不可见)**:widget `useSSE.ts` 只处理 `sources`/`token`/`done`,**静默忽略 `declined` 与一切未知事件** → 预算熔断(declined+done)在 widget 上完全不可见(空白气泡);亦无任何失败事件的处理通道。

**RC-5(截断信号丢失)**:provider 层只取 `delta.content`,**`finish_reason` 被丢弃**(`backend/llm/deepseek.py` aiter_lines 循环)。下游(RAG/SSE/UI)无任何截断判据。A11 的句中截断可能来自 max_tokens 截断(finish_reason=length)或 RC-2 类中断,现有数据无法事后区分。

## 2. 十项调查问题结论(任务 §6)

1. **正常结束信号**:provider 收到 `data: [DONE]` 行后生成器正常返回;RAG 层据此发 `complete`;routes 层在 rag 生成器耗尽后发 `done`。
2. **异常/超时信号**:httpx 异常(ReadTimeout 等)抛出;provider 内部首 chunk 前重试一次(produced 守卫),已产出后直接抛。
3. **可否零 chunk 无错误返回**:**可以,已实证**——200 + 立即 [DONE]、或全部 delta 无 `content` 键、或 content 为空串(被 `if content :=` 过滤),均静默正常结束。
4. **`complete(answer="")` 可否出现**:**可以**——旧代码 `stream_answer` 末尾无条件发 `complete(answer=full_answer, is_answered=True)`,零内容时即伪成功。
5. **截断可否检测**:**当前抽象下不可靠检测**(RC-5,finish_reason 丢弃)。可检测子类:mid-stream 异常(已闭环)、零内容(已闭环)。max_tokens 截断需改 `stream()` 协议(AsyncIterator[str] → 富对象),按任务 §9「不得发明无依据的启发式」处理为 PARTIAL,见 KNOWN_RISKS。
6. **超时/取消传播**:ReadTimeout 经 provider→router→rag→routes 逐层传播(路由层缺陷 RC-3 已修);客户端断连触发 CancelledError(BaseException,不被 `except Exception` 吞),跳过持久化——与既有架构一致,未改动。
7. **部分响应持久化**:修复前 = `answer=部分文本, is_answered=False`,无 Trace,与拒答不可区分;修复后 = 同样落部分文本,`is_answered=False` + `Trace(type=generation_error, failure_kind=stream_interrupted)`。
8. **UI 对错误/拒答现状**:拒答文本作为 token → 可见;预算熔断 declined → **修复前 widget 不可见**(RC-4),现已可见;HTTP 层错误走 onError 文案(既有)。
9. **重试 UX**:无重试按钮(现状未改,属「与本缺陷无关的通用重试架构」,任务范围外);失败文案引导用户重新提问,满足 PC-02「可重试」。
10. **可观测性区分**:修复前失败路径无 Trace 行、与拒答不可区分;修复后所有失败路径均落 `Trace(type=generation_error)` + `config_snapshot.failure_kind` 三分类,Conversation.is_answered 强制 False。零新增表/字段(复用 Trace.type String(20) 与 JSONB)。

## 3. Implementation Summary(最小变更,5 个产品文件)

| 文件 | 变更 |
|---|---|
| `backend/pipeline/rag.py` | 新增 `EmptyGenerationError(RuntimeError)`;`stream_answer` 生成循环后零可用内容(空/仅空白)时 `raise EmptyGenerationError`(打 error 日志),不再发伪成功 complete。**未触碰检索/可见性代码**。 |
| `backend/llm/registry.py` | `LLMRouter.stream` 补 `produced` 守卫:已产出 chunk 后异常立即 `raise`,仅首 chunk 前允许故障切换(与 provider 层守卫语义对齐)。 |
| `backend/api/routes.py` | event_generator 重构:① 异常分类 `empty_generation / provider_error / stream_interrupted`(识别 EmptyGenerationError);② 用户可见内容发射三选一互斥(拒答补发 / 零内容兜底 / 正常转发),杜绝双发;③ `done` 前发结构化 `error` 事件(旧客户端忽略未知事件,退化为仅兜底 token 文本,仍满足可见失败);④ 失败时 `is_answered` 强制 False + Trace 重分类 `generation_error`;⑤ 兜底文案沿用既有「服务暂时不可用,请稍后再试。」。 |
| `widget/src/hooks/useSSE.ts` | 抽离**可单测的** `consumeSSE(response, callbacks)`(真实流消费路径,widget 与 Admin LoginChat 共用);新增 `error` 事件 → `onError(message, {kind})`、`declined` 事件 → `onError(reason)`(修复熔断不可见);未知事件仍忽略(向后兼容)。 |
| `widget/src/App.tsx` | `stream_interrupted` → 部分内容保留、失败提示追加(不覆盖);其余失败 → 替换内容(既有模式);`onDone` 空内容气泡兜底失败文案(客户端最后防线,兼容旧后端)。 |

**不变式(PC-05 验证)**:正常流 `sources → token(s) → done`、conversation_id 一致性、持久化、feedback/click、拒答与 declined 事件形状全部逐字节不变(见 REL-G004/005 与既有 test_routes.py 精确序列断言)。

## 4. Tests(TDD:先红后绿,无弱化)

**RED 实证**(实现前):G001/G002/G003/空白流 4 项失败(旧代码确实静默 done);路由重放测试 `DID NOT RAISE`(实证多供应商重放);rag 守卫 `DID NOT RAISE EmptyGenerationError`;widget 5 项因 `consumeSSE` 不存在失败。另 5 项既有行为守护测试(首 token 前切换、全失败 RuntimeError、拒答、熔断、正常流)实现前即绿,作回归锚。

| 测试文件 | 覆盖 |
|---|---|
| `tests/api/test_reliability.py`(新) | REL-G001 零 token 正常结束→token+error(empty_generation)+done、落库 is_answered=False+Trace(generation_error);REL-G002 首 token 前异常(异常细节不外泄断言);REL-G003 部分后中断(恰好 1 token,部分文本如实落库);REL-G005 拒答无 error + 熔断 [declined, done] 形状不变;空白流=零可用内容;正常流无 error 事件守护。 |
| `tests/pipeline/test_rag_reliability.py`(新) | 零内容/仅空白 → EmptyGenerationError 且无伪成功 complete;正常生成仍发 complete(不误伤)。 |
| `tests/llm/test_router_stream_failover.py`(新) | 首 token 前失败保留故障切换;**已产出后失败立即抛、禁止重放**;全失败 RuntimeError 语义保持。 |
| `widget/src/hooks/__tests__/useSSE.test.ts`(新) | AC-07:真实流消费路径 —— 正常分发、error(带 kind)、declined(reason)、未知事件忽略不崩、非 2xx 走 onError 固定文案。 |
| 既有回归 | `tests/api/test_routes.py` 精确事件序列断言(含拒答补发)全绿 = 正常/拒答语义逐字节未变。 |

**运行结果**:
- 全量后端 `pytest tests/ --ignore=tests/e2e`:**575 passed, 3 skipped, 4 failed** —— 4 个失败均为 `tests/embedder/test_bge.py` BGE 模型加载 OSError,**基线检出同环境同败**(已在本仓 pristine 基线复跑证实),且 **CI 工作流明确 `--ignore=tests/embedder`**;与本变更无关。
- 直接相关套件(tests/api + tests/llm + RAG 系列):**200 passed**;修后复跑 154 passed。
- widget:`vitest run` **35 passed**(含既有 30 + 新增 5);`tsc --noEmit` 通过;`vite build` 通过(widget.js 249.78 kB)。
- admin:`tsc --noEmit` + `vite build` 通过(LoginChat 复用 widget App,AC-07 Admin 兼容)。
- lint:ruff 对 3 个改动后端文件 **4 项 finding 与基线逐项相同**(B008/SIM102/F841/RUF100,全部预存;CI 无 ruff 步骤);isort 新文件通过;black 不整文件重排(遵循「只植增量」纪律,基线格式漂移未波及)。

## 5. Product Evidence(确定性采集,`scripts/p1_reliability_evidence.py`)

mock RAG 驱动**真实** FastAPI app + `/api/ask` 端点采集实际 SSE 序列与落库对象(SSE data 中 `\uXXXX` 为 json.dumps ensure_ascii 既有行为,widget JSON.parse 后正常显示中文)。结果 **ALL PASS**:

**Case 1 — 零 token(复现 A05/E04-t2)**
```
HTTP 200
event: sources  data: {"conversation_id": "4ff17e61-…", "sources": []}
event: token    data: {"content": "服务暂时不可用,请稍后再试。"}
event: error    data: {"conversation_id": "4ff17e61-…", "kind": "empty_generation", "message": "服务暂时不可用,请稍后再试。"}
event: done     data: {"conversation_id": "4ff17e61-…"}
落库: Conversation(answer='服务暂时不可用,请稍后再试。', is_answered=False)
      Trace(type='generation_error', failure_kind=empty_generation)
[PASS] 零内容完成不再是 sources→done 静默空白
```

**Case 2 — 首 token 前异常**
```
HTTP 200
event: token  data: {"content": "服务暂时不可用,请稍后再试。"}
event: error  data: {"kind": "provider_error", …}
event: done   data: {…}
落库: Conversation(is_answered=False) + Trace(type='generation_error', failure_kind=provider_error)
(异常文本 "All LLM providers unavailable…" 不出现在响应体,仅入日志)
[PASS] 显式可恢复失败,无静默空白,无细节泄漏
```

**Case 3 — 部分 token 后中断**
```
HTTP 200
event: token  data: {"content": "请先检查电源与指示灯:"}
event: error  data: {"kind": "stream_interrupted", …}
event: done   data: {…}
落库: Conversation(answer='请先检查电源与指示灯:', is_answered=False) + Trace(generation_error, stream_interrupted)
[PASS] 部分内容保留 + 结构化中断信号,非普通成功,无重复兜底
```

**Case 4 — 正常成功**
```
HTTP 200
event: sources data: {"conversation_id": "a0de34f6-…", "sources": [{"url": "https://example.com/wiki"}]}
event: token   data: {"content": "请检查"}
event: token   data: {"content": " CEREG 配置。"}
event: done    data: {"conversation_id": "a0de34f6-…"}
落库: Conversation(answer='请检查 CEREG 配置。', is_answered=True)   ← 无 Trace 重分类,无 error 事件
[PASS] 流式语义不变,conversation_id 一致,恰好一次 done
```

**Case 5 — 有意拒答**
```
5a 证据不足拒答: event: token{"暂未在官方资料中找到相关信息。"} → done(无 error)
                 落库 Conversation(is_answered=False),Trace 不重分类(仍 reject_short)
5b 预算熔断:     event: declined{"reason": "服务繁忙,请稍后再试"} → done(形状不变)
[PASS] 拒答是有意可见结果,未被转成生成错误(NA-03)
```

浏览器/Widget 层证据 = vitest 对真实流消费路径 `consumeSSE` 的 5 项契约测试 + widget/admin 双端 tsc+build 通过(双端共用同一组件树;「如实际可行」范围内未再起浏览器会话)。

## 6. Acceptance Criteria 逐条

- **AC-01** ✅ 零 token 完成不可能静默成功:REL-G001 + Case 1(守护点:routes 零内容兜底 + rag 层 EmptyGenerationError 双层防御)。
- **AC-02** ✅ 首 token 前异常用户可见:REL-G002 + Case 2(兜底 token + error 事件 + 落库失败状态;异常细节不外泄)。
- **AC-03** ✅ 部分输出后失败非普通成功:REL-G003 + Case 3(确定性:test 覆盖;行为=部分内容保留+stream_interrupted 信号+失败落库)。
- **AC-04** ✅ 正常流式不变:既有 test_routes.py 精确序列 + REL-G004 守护测试 + Case 4;无重复兜底 token、无重复 done、conversation_id 不丢。
- **AC-05** ✅ 有意拒答保持正确:REL-G005a(证据不足)/ 5b(预算熔断);off-topic 拒答走同一 complete(is_answered=False, 非空文本)通道由既有测试锚定。均不转通用 provider 错误。
- **AC-06** ✅ 持久化反映现实:失败 → is_answered=False + Trace(type=generation_error, failure_kind 三分类),**零 schema 扩展**(复用既有 Trace.type/JSONB);成功/拒答/失败三类可区分(PC-06)。
- **AC-07** ✅ 客户端实际路径已验证:consumeSSE(Widget+Admin 共用真实消费代码)vitest 契约测试;双端 tsc/build 通过。

## 7. Negative Acceptance 自查

NA-01 ✅不可能 | NA-02 ✅失败不再吞(provider+router+routes 三层均有显式出口) | NA-03 ✅拒答未被误标(Trace 拒答仍 reject_short,无 error 事件) | NA-04 ✅无重复文本(发射互斥设计+测试断言恰好 1 token) | NA-05 ✅中断/零内容不再记成功 | NA-06 ✅测试打在 SSE 事件层与路由/rag 守卫层,非仅 mock 最终 HTTP 输出;路由重放缺陷在真实协议层复现 | NA-07 ✅未动任何超时参数 | NA-08 ✅未改检索/可见性/Admin 页面/供应商管理 | NA-09 ✅未弱化测试(反而新增 24 项) | NA-10 ✅未部署生产。

## 8. KNOWN_RISKS

1. **【PARTIAL 子项】max_tokens 截断(finish_reason=length)不可检测**:provider 丢弃 finish_reason;可靠检测需改 `stream(): AsyncIterator[str]` 协议为富对象,将波及 base Protocol/deepseek/registry/rag 全链,与并行任务 P0 在 rag.py 的变更面叠加风险大,故按 §9 选择「不发明确定性、文档化限制、关闭全部可检测静默路径」。mid-stream 异常类中断(连接断/超时)已全闭环;残余风险仅剩「provider 主动正常结束但内容被 length 截断」且**无任何协议信号**的场景——该场景下连 provider 自身都无法零改动感知。建议后续任务:扩展 provider 协议透出 finish_reason 后,在 rag 层补 finish_reason=length → stream_interrupted 分类(预留的 failure_kind 枚举可直接复用)。A11 类历史案例无法事后归因。
2. 旧版本缓存 widget.js 在**部分中断**场景仍只显示部分文本+done(无 error 事件处理),与修复前行为持平、不劣化;零内容/首 token 前失败场景旧客户端即可见兜底 token 文本。新部署 widget/Admin 后全部场景完整可见。
3. `rag.answer()`(非流式)存在同型零内容孔,但**无生产调用方**(已 grep 实证:仅测试/预留),超出本任务授权面,未改动,仅记录。
4. 4 个 BGE embedder 测试在本机环境失败(OSError),基线同败、CI 排除该目录;T4 发布前应在完整环境复核。
5. `declined` 事件现在会显示给用户(修复前静默)——这是 PC-04 要求的「可见结果」,但若熔断文案需产品润色,属后续文案决策,非本任务范围。

## 9. MERGE_CONFLICT_RISK(与 Codex A / P0 Knowledge Trust Boundary)

- **`backend/pipeline/rag.py`(声明热点)**:本任务仅两处改动 —— ① 文件头部常量区后新增 `EmptyGenerationError` 类(≈L38-46);② 生成循环尾部(LLM stream 之后、complete 事件之前)新增零内容守卫块(≈L798-810)。**未触碰** `_retrieve_and_fuse` / `_extract_sources` / `PUBLIC_SOURCE_TYPES` / sources 可见性任何逻辑。Codex A 若改动检索/可见性区域,git 层面预计可自动合并;若 A 亦重构 stream_answer 签名/生成循环,需人工对齐。
- 其余改动文件(routes.py / registry.py / useSSE.ts / App.tsx 及全部新测试文件)不在 P0 授权范围内,预期无冲突。
- **独立 PASS ≠ 集成 PASS**:两分支合流后须跑全量回归(tests/api + tests/pipeline + tests/llm + widget vitest + 双端 build)再收口。

## 10. 提交与产物

- 产品代码仓(ask-ai,branch `worktree-exec/p1-reliability`):`5c06151` — 10 files changed, +1071/−69
- 确定性证据脚本:`scripts/p1_reliability_evidence.py`(可重放:`PYTHONPATH=. python scripts/p1_reliability_evidence.py`)
- 本报告:docs 本地仓 `docs/implementation/CAMTHINK_V1_P1_GENERATION_RELIABILITY_2026-09-01.md`

**Executor PASS 仅为本端证据;不部署生产、不声明 CamThink V1 Launch PASS,等待 Planner/Reviewer 独立审查。**
