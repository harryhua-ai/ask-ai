# CAMTHINK V1 — ⑯ Generation Failure / Localization Discovery 报告

- 日期:2026-09-03
- 角色:Engineering Discovery Agent(WINDOW B,并行发现)
- 基线:`1b8572abd74145bac5727688a957a2c37370c7ec`(worktree-exec/sync-isolation-20260902 分支 tip,阶段⑨+⑩ FINAL)
- CODE_MUTATION:NONE(零源码改动)
- PRODUCTION_ACCESS:NONE(零生产接触)
- 执行模式:BOUNDED / CROSS-CUTTING DISCOVERY——只建立 failure taxonomy、language resolution truth、acceptance contract,不实施修复

## 0. 基线核验方法

主仓 main=ebe10b8,基线 1b8572a **不是** main 祖先(阶段⑨/⑩在独立分支待 Planner 复核)。两树 diff:
`git diff ebe10b8..1b8572a -- backend/api/routes.py backend/api/schemas.py backend/pipeline/rag.py backend/llm/ backend/utils/language.py widget/ admin/` → **仅 `backend/api/admin/data_sources.py` 有差异**(sync 隔离相关)。因此本报告所有行号引用在工作区(main 检出)与基线**逐字节一致**,可直接作为 1b8572a 证据。

## 1. Current Failure Flow(现状失败流)

### 1.1 /api/ask 主链路(backend/api/routes.py L89-343)

```
请求 → PII mask → lead 上下文(fail-open)→ 站点门禁(site_id 时,失败 403)
  → S2 预算熔断(超限:declined + done,零持久化)
  → 附件归属校验(422/403,HTTP 层,不进 SSE)
  → rag.stream_answer(SSE 生成器内):
        sources → token(s) → complete
  → 用户可见内容发射(恰好一次)
  → 失败时:error 事件(done 之前)
  → Postgres 持久化(Conversation + Trace)
  → lead 落库(fail-open)→ done 事件
```

### 1.2 失败分类器(routes.py L196-246,PC-06,已实证)

| 场景 | 判定 | 依据 |
|---|---|---|
| `rag.stream_answer` 抛 `EmptyGenerationError` | `empty_generation` | rag.py L1223-1230:流正常结束但零可用内容(空流/仅空白/唯一内容是被剔除的悬空引用) |
| 抛其他异常且**已发过 token** | `stream_interrupted` | routes.py L246 `token_emitted` 标志 |
| 抛其他异常且**未发过 token** | `provider_error` | routes.py L246 |

失败后统一动作(routes.py L262-286):
1. 强制 `is_answered=False`(L263,NA-05:失败绝不持久化为成功);
2. 若无任何内容,补发 `SERVICE_UNAVAILABLE_MSG` 作为 token(L254-257);
3. 发 `error` SSE 事件 `{conversation_id, kind, message: SERVICE_UNAVAILABLE_MSG}`(L264-273);
4. Trace 改写:`type=generation_error` + `stages.error={kind}` + `config_snapshot.failure_kind`(L276-286)。

### 1.3 异常面归因(谁会真的失败)

- **LLM 层**(backend/llm/):`deepseek.py` L22-28 对瞬时网络异常(ReadTimeout/ConnectTimeout/ConnectError/RemoteProtocolError/ReadError)重试一次,HTTPStatusError(如 401)不重试;`registry.py` L91-117 LLMRouter.stream 按链路故障切换,**仅允许首 chunk 产出前切换**(produced 守卫,防重放重复),链路全灭抛 `RuntimeError("All LLM providers unavailable...")`。
- **intent / rewrite 层 fail-open,不产生失败**:intent.py L88-90 任何异常 → `category=product`;query_rewrite.py L77-79/L126-128 异常 → 返回原 query。供应商故障若发生在意图分类/改写阶段**用户与可观测层均不可见**(按设计降级,但属本 taxonomy 必须声明的边界)。
- **检索/重排层会真失败**:retrieve/rerank 异常向上传播 → 因未发 token 被归为 `provider_error`。**命名误导**:该 kind 实际语义是「首 token 前管线失败」,不限于 LLM 供应商。
- **social/override 路径**:确定性零 LLM,失败面≈0。

### 1.4 拒答/其他可见路径

- 无证据拒答:rag.py L1049-1123,fused 为空 → `complete(answer=REJECT_ANSWER, is_answered=False)` + `trace type=reject_short`,routes 层补发为 token(L252-253),**无 error 事件**(tests/api/test_reliability.py REL-G005 冻结)。
- off-topic 拒答:rag.py L971-1003,语言感知(`_off_topic_reply`,zh/en 双语,L58-73),trace reject_short。
- social 短路:rag.py L299-325 + social.py,zh/en 模板按匹配 pattern 语言选择,intent=smalltalk,is_answered=True。
- 预算熔断:routes.py L147-153,`declined` 事件 `reason="服务繁忙,请稍后再试"` + done(**conversation_id 是凭空 uuid4,无任何 DB 行**);完全不进 Admin。
- 站点拒绝:routes.py L65 `SITE_DENIED_MSG="站点未授权或来源不受信任"`(固定中文,403,L141/L366);widget 客户端对 403 用自己的文案覆盖(useSSE.ts L52-56)。
- 全局 500:main.py L452-460 `{"detail": "内部服务错误"}`(固定中文);限流 429:slowapi 默认 handler(英文)。附件/校验错误:英文 422/403(routes.py L158-174)。

## 2. Current Language Flow(现状语言流)

### 2.1 解析链(已冻结,ML Closure)

```
请求 language(AskRequest,归一化 fail-open None,schemas.py L100-105)
  → 显式 site_id 时回落 site.language(routes.py L215)
  → rag.stream_answer 入口:resolve_answer_language(query, language_hint)   ← rag.py L910-911
       规则(language.py L64-84):hint 为默认语境;文本检出 CJK 且与 hint 不同族 → 显式用户语言覆盖;无 hint → detect_language 原值(zh-cn/en/ja/ko)
  → 消费点:① 提示词「用 {language} 回答」(rag.py L574)
            ② complete 事件 language 字段
            ③ trace stages.language {hint, detected, resolved}
```

### 2.2 关键时点答案(B 的核心问题)

**resolved answer language 在 stream_answer 的第一行就被计算**(rag.py L911,先于任何 yield、先于意图分类 LLM 调用)。因此:**任何失败点(含首 token 前),系统都已经知道 resolved answer language**——它存在于 rag 的栈帧里。

**但它到不了 routes 层**:language 只通过 `complete` 事件离开 rag(routes.py L234),而失败路径永远没有 complete。routes 的事件生成器初始 `language="en"`(L190),失败时保持 "en"。后果:

- 英文问题 + 首 token 前失败:DB language="en",回答文案=中文 → 巧合一致、语义错位;
- 中文问题 + 首 token 前失败:DB language="en",回答文案=中文 → **双重不一致**(语言标错+文案错);
- Widget 通常随请求发 language 提示(html lang 链),legacy 请求不发 → `Conversation.language` 存在 **"zh-cn"**(无 hint 检测原值)与 **"zh"**(有 hint)两种形态混落库(language.py L79-80 返回 detected 原值)。

### 2.3 deterministic fallback 顺序(错误时点语言解析建议)

routes 层用**同一个纯函数、同一组输入**重算:`resolve_answer_language(masked_message, req.language or site.language)`。确定性成立:routes 传给 stream_answer 的 query 就是 masked_message(routes.py L204),hint 计算式完全相同(L215);函数无 I/O、无随机性 → 结果与 rag 内部值**逐位相等**,单一 authority 不破。备选方案(在 sources 事件或新增 meta 事件捎带 language)仅覆盖 generation 路径且改协议,列为备选。

### 2.4 前端语言轴(已冻结,不动)

widget/src/utils/language.ts L1-12:宿主显式 → `<html lang>` → 站点默认 → 浏览器 → 省略;UI_LANGUAGE(en/zh 二值)与 ANSWER_LANGUAGE(随 ask 发送)双轴分离。widget i18n.ts **已有双语 serviceUnavailable 文案**(L20 en / L30 zh)——正确文案客户端已存在,只是服务端不下发英文版。

## 3. Failure Taxonomy(最小稳定分类法)

| taxonomy | 语义 | is_answered | 用户可见 | SSE | Trace.type | failure_kind | Admin 应有标签 |
|---|---|---|---|---|---|---|---|
| **REFUSAL**(子类 no_evidence / off_topic) | 有意业务边界 | False | 本地化拒答/边界文本,作正常 token | **无 error**(token+done) | `reject_short` | — | 拒答 |
| **EMPTY_GENERATION** | 流正常结束但零可用内容(技术异常完成) | False(强制) | 本地化失败文案 + error | `error kind=empty_generation` | `generation_error` | empty_generation | 生成失败 |
| **PROVIDER_ERROR** | 首 token 前管线异常(LLM 链全灭 / 检索/重排崩溃;intent/rewrite 已 fail-open 不在此列) | False(强制) | 本地化失败文案 + error | `error kind=provider_error` | `generation_error` | provider_error | 生成失败 |
| **STREAM_INTERRUPTED** | 已产出部分 token 后异常 | False(强制) | 保留部分内容 + 追加本地化失败提示 | `error kind=stream_interrupted` | `generation_error` | stream_interrupted | 生成失败 |
| **BUDGET_DECLINED** | 预算熔断,未进管线 | — | 本地化繁忙提示 | `declined`(形状不变) | **现状无任何持久化** | — | 现状不可见(PD-3) |
| SMALLTALK | 社交回应 | True | 双语模板 | 无 | `social_reply` | — | 已回答 |
| SUCCESS / OVERRIDE | 正常回答 | True | 回答本体 | 无 | `rag` / `override` | — | 已回答 |

边界裁决(对应任务 HARD BOUNDARIES):
1. REFUSAL ≠ Generation Failure:refusal 是有意结果,无 error 事件,trace=reject_short;失败是异常完成,trace=generation_error + error 事件。现有行为已正确区分(REL-G005 冻结),**违例只在 Admin 呈现层与拒答文案语言**。
2. empty_generation ≠ business refusal:虽然两者 is_answered 都是 False,但前者必须走 error 通道 + generation_error trace,后者走 reject_short。现状正确。
3. provider_error/stream_interrupted 可观测:已通过 error 事件 + Trace.config_snapshot.failure_kind + tech 洞察 failure_kinds 分布(tech.py L80-90/L321/L331)三面落地;**缺口在 Admin 对话列表未下钻 failure_kind**、declined 完全不可观测。
4. 不把技术异常伪装成正常回答:服务端已做到(NA-05);残留伪装面=旧客户端忽略 error 事件时中文兜底 token 以普通回答气泡呈现(文档化降级,可接受)+ Admin「拒答」徽章语义污染。
5. Trace.type 列宽 String(20)(models.py L131):`generation_error`(16)/`budget_declined`(15)均容纳;新增类型须 ≤20 字符。

## 4. Misclassification Findings(误分类实证)

- **MF-1(高,任务样例证实)Admin 把生成失败表达成拒答**:Conversations.tsx L361-362 与 L433-434,状态徽章 `conv.is_answered ? "已回答" : "拒答"`;L218 筛选选项 `<option value="false">拒答</option>`。generation_error 对话(is_answered=False)被主标签判为「拒答」;failure 徽章存在(L302-308)但仅为次级 chip。业务拒答与技术失败在 Admin 主视图不可区分。
- **MF-2(高,冻结原则违例)失败文案固定中文污染英文会话**:routes.py L62 `SERVICE_UNAVAILABLE_MSG="服务暂时不可用,请稍后再试。"` 对所有语言下发(失败 token + error.message + conversations.answer 三处)。英文用户问 "How do I troubleshoot an NE301 flash failure?" 遇 provider_error → 收到中文。
- **MF-3(高,同上)无证据拒答固定中文**:rag.py L54 `REJECT_ANSWER="暂未在官方资料中找到相关信息。"` 不带语言参数(L1077 直接引用);对照 off-topic(L58-73 双语)与 social(双语)已闭环——拒答路径是 ML 闭环遗漏面。英文用户问冷门问题 → 中文拒答。
- **MF-4(中)失败行 language 字段失真**:失败路径 language 恒 "en"(routes.py L190),与中文兜底文案矛盾,污染语言维度分析。
- **MF-5(中)declined 不可观测 + 幽灵 conversation_id**:routes.py L149-152 done 下发随机 uuid4 但无 DB 行;客户端拿它发 feedback 静默 no-op;Admin 无任何呈现。
- **MF-6(低)provider_error 命名误导**:检索/重排异常也被计入(见 §1.3),字面指向 LLM 供应商。
- **MF-7(低)语言形态不统一**:"zh-cn" 与 "zh" 混落 Conversation.language(§2.2),取决于请求是否带 hint。
- **MF-8(低)死代码与文档漂移**:rag.py L68 `REJECT_BUSINESS` 定义后全仓零引用;language.py L26 docstring 声称拉丁文本用 langdetect,实现直接回 "en"(L34)。
- **MF-9(低,设计边界声明)intent/rewrite 供应商故障静默降级**:不产生 generation failure,答案质量可能下降而无观测痕迹。本轮仅声明,不提议改行为(避免扩张)。

## 5. User-visible Localization Matrix(用户可见文案矩阵)

| # | 路径 | 触发 | 现文案 | 现语言 | 本 Gate? |
|---|---|---|---|---|---|
| 1 | 失败兜底 token + error.message + DB answer | empty/provider/stream | 服务暂时不可用,请稍后再试。 | 固定 zh | **IN**(核心) |
| 2 | declined reason | 预算熔断 | 服务繁忙,请稍后再试 | 固定 zh | **IN** |
| 3 | 无证据拒答文本 | fused 空 | 暂未在官方资料中找到相关信息。 | 固定 zh | **IN**(refusal 文案本地化) |
| 4 | off-topic 边界文本 | off_topic 意图 | zh/en 按 resolved | 已合规 | 仅回归护栏 |
| 5 | social 模板 | 纯社交输入 | zh/en 按 pattern | 已合规 | 仅回归护栏 |
| 6 | 站点拒绝 403 detail | Origin 不匹配 | 站点未授权或来源不受信任 | 固定 zh(HTTP body;widget 用自有文案覆盖) | 边界→PD-6 |
| 7 | widget 客户端 HTTP 兜底(403/422/网络) | useSSE L50-61 | 此站点未被授权…/无权访问所选附件/问题内容过长…/服务暂时不可用 | 固定 zh(UI 语言无关) | **IN**(客户端侧,应走 uiStrings(UI_LANGUAGE)) |
| 8 | widget onDone 空流兜底 | 旧服务端零内容 | uiStrings(langNow).serviceUnavailable(App.tsx L134-139) | 双语合规 | 保持 |
| 9 | 附件错误 422/403 | 附件流 | 英文(routes.py L160-173) | 固定 en | Non-goal(PD 记录) |
| 10 | FastAPI 422 校验 | 请求体非法 | FastAPI 默认英文 | 固定 en | Non-goal |
| 11 | 限流 429 | >20/min | slowapi 默认英文 | 固定 en | Non-goal(PD 记录) |
| 12 | 全局 500 | 未捕获异常 | 内部服务错误 | 固定 zh(无语言上下文可用) | Non-goal |
| 13 | lead 邀请/确认文案 | capture 流 | 已本地化(ML-G013) | resolved | 范围外 |
| 14 | 回答本体 | 生成 | 提示词「用 {language} 回答」 | resolved | 范围外(答案正确性策略冻结) |

## 6. Observability Contract(可观测契约,现状+目标)

现状已落地(保持):
- Trace(type=generation_error, stages.error.kind, config_snapshot.failure_kind)——routes.py L276-286;
- tech 洞察:failure_kinds 分布 + anomaly type `generation_error:{kind}`(tech.py L321/L331/L462);
- Admin has_failure 过滤 + failure chip(conversations.py L33/L71-77 + _infer_markers L19-53,语义与 tech.py 同源);
- stages.language {hint, detected, resolved} 已入 rag/reject_short trace。

缺口(实现轮补齐,均不加表):
1. Admin 对话列表/详情下发 failure_kind(列表响应增列,additive;详情端点现不含 trace,L214-253);
2. declined 持久化决策(PD-3):若拍板持久化 → Conversation(is_answered=False)+Trace(type=budget_declined)落库,declined 的 done 使用真实 conversation_id;
3. 失败行 language 字段写入 resolved language(§2.3 方案);
4. (可选)sources 事件或 error 事件捎带 resolved language,便于客户端与对账。

## 7. Compatibility(兼容性验证)

- **旧 Widget 对未知 SSE 事件安全**:consumeSSE if/else 链只认 sources/token/error/declined/done(useSSE.ts L90-100),其余静默忽略——服务端新增事件类型/字段安全。error/declined/message 字段值变化安全(原样显示);**message 缺失**回落客户端硬编码中文(L24/L95)——若实现轮改服务端只发 key 不发 message 会破坏旧客户端,**禁止**(必须保留人类可读 message)。
- **done 契约**:恒为最后事件、`{conversation_id}`;error 在 done 之前;declined 路径也有 done。保持不变。
- **旧服务端 + 新 Widget**:新客户端兜底应改为 i18n(uiStrings),仅在 message 缺失/客户端本地 HTTP 失败时使用;对当前服务端行为零变化。
- **Admin API additive**:列表响应新增 failure_kind 字段不破坏现前端(未知字段忽略);badge 文案变化纯前端。
- **DB**:taxonomy 不需要 schema 变更(trace type + JSONB 已容纳);declined 持久化会**新增行**,影响 is_answered 相关统计口径(PD-3 必须评估)。
- **外部嵌入站点的陈旧 widget.js**:缓存滞后窗口内视同「旧客户端」,上述兼容结论已覆盖。

## 8. Scope / Non-goals

IN:§5 矩阵 #1/#2/#3(服务端本地化)+ #7(widget 客户端兜底双语化)+ Admin 生成失败/拒答标签分离 + 失败行 language 修正 + error/declined 增补 message_key(可选)。
OUT(Non-goals):§5 #9-#12(附件/校验/限流/500 文案——pre-SSE 或无语言上下文,记录 PD);lead 文案(已闭环);回答语言策略/检索正确性(冻结);完整 i18n framework(**明确不引入**,最小方案见 §9);multilingual subsystem 重设计;Stage⑰;生产;本轮任何代码改动。

## 9. Localization Strategy(最小方案建议)

- **服务端**:`backend/utils/user_messages.py`(或并入 language.py)提供 `MESSAGE_KEYS`(service_unavailable / budget_declined / no_evidence)+ `localized_message(key, language)`:zh→zh 文案,其余(zh/en/fr/ja/…)→en 文案(zh 之外统一 en,与 `_off_topic_reply` L73、UI_LANGUAGE 非 zh 即 en 的既有语义一致)。纯函数、无框架、无资源文件加载。
- **单一 authority**:`resolve_answer_language` 不动;routes 层在事件生成器入口用同函数同输入重算作为 language 默认值(complete 仍覆盖,值恒等);所有 Gate 内文案经 localized_message(key, 该语言)。
- **SSE 增量**:error/declined payload 增加可选 `message_key`;`message` 恒保留且已本地化。done/sources/complete 形状不变。
- **客户端**:useSSE 的本地兜底常量改由调用方传入 uiStrings 变体(或按 message_key 映射);服务端 message 仍是主显示。
- **拒绝路径**:REJECT_ANSWER → `_reject_answer(language)`(zh/en),同步 answer() 测试面一起改;OFF_TOPIC 机制已是范本。

## 10. Implementation Touchpoints(实现触点清单)

1. `backend/utils/language.py`(或新 user_messages.py):消息键表 + localized_message;
2. `backend/api/routes.py` L62/65/149-152/190/246-286:本地化文案、language 重算默认、message_key、declined 语言;(PD-3/PD-6 决议后)L65/147-153;
3. `backend/pipeline/rag.py` L54/L1077(+answer() 同步路径):拒答文本函数化;
4. `widget/src/hooks/useSSE.ts` L24/L52-59/L95/L97:兜底 i18n 化;`widget/src/i18n.ts` 增补 declined 等键;
5. `backend/api/admin/conversations.py`(列表响应增 failure_kind)+ `admin/src/pages/Conversations.tsx` L218/361/433(badge+筛选分离「生成失败」);
6. 测试:`tests/api/test_reliability.py`(REL-G001/002/003 断言现为硬编码中文文案 L30/145/150/162/189/235/347——**必改点**)+ 新增 EN 失败/拒答用例;`tests/api/test_multilingual_gate.py`/`tests/pipeline/test_multilingual_gate.py`(护栏);`tests/api/admin/test_conversations.py`(标记语义);widget `useSSE.test.ts`;
7. 文档:失败语义入产品合同(docs)。

## 11. Acceptance Draft(验收用例草案)

| # | 场景 | 用户看到 | DB Conversation | DB Trace | Admin 显示 |
|---|---|---|---|---|---|
| AC-1 | EN + empty_generation | "Service temporarily unavailable. Please try again later."(PD-1 文案)+ error kind=empty_generation | answer=英文文案,language=en,is_answered=False | generation_error,failure_kind=empty_generation | 生成失败徽章 + failure chip |
| AC-2 | ZH + empty_generation | 服务暂时不可用,请稍后再试。(现文案不变) | answer=中文文案,language=zh*,is_answered=False | 同上 | 同上 |
| AC-3 | EN + provider_error(首 token 前) | 同 AC-1 文案,kind=provider_error | 同 AC-1 | stages.error.kind=provider_error | 生成失败 |
| AC-4 | EN + stream_interrupted(部分 token 后) | 已输出英文部分内容保留 + 追加英文失败提示 | answer=部分内容+提示,is_answered=False | failure_kind=stream_interrupted | 生成失败 |
| AC-5 | ZH + 无证据拒答 | 暂未在官方资料中找到相关信息。;无 error 事件 | is_answered=False | reject_short(无 generation_error) | 拒答徽章 |
| AC-6 | EN + 无证据拒答 | **英文拒答文案(PD-1 新批)** | language=en | reject_short | 拒答 |
| AC-7 | 预算熔断(declined) | 本地化繁忙提示(EN/ZH);declined+done 形状不变 | PD-3:持久化或不 | PD-3 | PD-3 |
| AC-8 | EN + off_topic | 英文边界文本(现状已合规,回归护栏) | is_answered=False | reject_short | 拒答 |
| AC-9 | en hint + "你好" | 中文问候(CJK 显式覆盖,ML-G002 护栏) | language=zh* | social_reply | 已回答 |
| AC-10 | 旧 widget 兼容 | 现 widget build 正常消费 error/declined;未知字段忽略;done 契约不变 | — | — | — |
| AC-11 | ZH 问题 + 首 token 前失败 | 中文失败文案 | language=zh*(修复 MF-4) | generation_error | 生成失败 |

## 12. Product Decisions Required(待产品拍板)

- **PD-1 英文文案定稿**(本报告给建议稿,产品可改):service_unavailable="Service temporarily unavailable. Please try again later.";budget_declined="The service is busy. Please try again later.";no_evidence="I couldn't find relevant information in the official materials."
- **PD-2 非 en/zh 语言回落**:resolved 为 ja/ko/fr/… 时文案回落 en(建议:是,与 off-topic/UI_LANGUAGE 既有语义一致)。
- **PD-3 declined 持久化**:建议持久化最小行(is_answered=False + trace budget_declined,done 用真实 id),代价=is_answered 统计口径变化需公告;或 V1 维持 ephemeral。
- **PD-4 Admin 标签分离**:生成失败 vs 拒答 双徽章 + 筛选项拆分(建议:做,has_failure 过滤已存在)。
- **PD-5 provider_error 命名**:kind 值保持(compat),语义文档化为「首 token 前管线失败」,trace 保留异常阶段证据。
- **PD-6 site_denied 403 文案**:服务端中文 detail 是否本地化(widget 已自有文案覆盖,原始 API 客户端才可见;建议 V1 保持)。
- **PD-7 message_key 增补**:error/declined payload 加可选 message_key(建议:加,零破坏)。
- **PD-8 language 规范形**:Conversation.language 落库前归一(zh-cn→zh)?建议仅记录,不本轮改(analytics 口径敏感)。

## 13. Self-Check

- CODE_MUTATION:NONE(主仓零改动;本报告仅入 docs 仓);
- PRODUCTION_ACCESS:NONE;
- 基线事实重验:SERVICE_UNAVAILABLE_MSG 固定中文(routes.py L62)✅;empty_generation/provider_error/stream_interrupted 三分类存在(L196-246)✅;均从 1b8572a 等价工作区重新取证,非引用任务描述;
- 边界遵守:未重设计 multilingual subsystem(§9 最小方案)、未动 Retrieval/Answer 策略、未进 Stage⑰、未触生产。
