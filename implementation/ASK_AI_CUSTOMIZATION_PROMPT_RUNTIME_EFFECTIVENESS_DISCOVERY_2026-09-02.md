# ASK_AI_CUSTOMIZATION_PROMPT_RUNTIME_EFFECTIVENESS_DISCOVERY_2026-09-02

## A. STATUS

**PASS**(静态全链路追踪 + 本地动态运行时证明;零产品代码变更、零生产访问)

## B. BASELINE

- Repository: `harryhua-ai/ask-ai`;worktree `.worktrees/technical-insights`;branch `release/camthink-v1-rc-2026-09-01`;HEAD `f874ee45a6df2368ef8c5f55078ab3e35ddd4a8f`(工作树干净,未动任何并行工作)。
- 本任务仅新增本报告(docs 主仓 + docs 本地仓),无产品代码 commit。

## C. EXECUTIVE CONCLUSION

1. **三个字段在运行时全部生效,但不是三个独立运行时通道**:`style_tone` 与 `guardrails` 在 DB 加载时被**拼接进 system_prompt**(`config_loader.py:73-77`),三者合成为一条 system 消息;此后运行时只认识"渠道 system_prompt"这一个东西。
2. **生效是"启动时快照"而非"保存即生效"**:`load_customizations_from_db` 仅在 **lifespan** 执行一次(`main.py:338`);Admin CRUD(`backend/api/admin/customizations.py`)只写 DB,**不热重载** `app.state.rag._channel_customizations` → UI 保存后必须重启 backend 才生效。这是当前架构最重要的有效性事实。
3. `assistant_name` 与 `language`("auto")为 **STORED_BUT_UNUSED**:config_loader 返回后,`main.py:344` 只投影 `c["system_prompt"]`,两字段被丢弃,无任何运行时消费者;`auto` 由此确认 = `Customization.language` 列默认值,纯 UI 展示(`Customizations.tsx:149`),不影响运行时。
4. 回答语言由 `detect_language(query)` 运行时决定;意图风格(`intent_styles`)在定制 prompt **之后**追加 —— 运行时指令排在用户配置之后。
5. 架构评级:**C. INCOMPLETE**(字段存在且生效但接线不完整)+ **D. CONFLICT_PRONE**(与 `intent_styles`、yaml 内嵌规则存在指令重叠)。

## D. FIELD EFFECTIVENESS MATRIX

| Field | Stored | Loaded | Final LLM Input | Streaming | Non-streaming | Effective |
|---|---|---|---|---|---|---|
| system_prompt | ✅ `customizations.system_prompt` NOT NULL Text | ✅ lifespan 加载 | ✅ 合并串头部,role=system 首条消息 | ✅ | ✅ | **FULLY_EFFECTIVE**(保存后需重启) |
| style_tone | ✅ nullable Text | ✅(拼接进合并串,`## 风格语气` 小节) | ✅ 位于 system_prompt 之后、guardrails 之前 | ✅ | ✅ | **FULLY_EFFECTIVE**(同上;非独立通道) |
| guardrails | ✅ nullable Text | ✅(拼接进合并串,`## 边界规则` 小节) | ✅ 位于 style_tone 之后、intent_styles 之前 | ✅ | ✅ | **FULLY_EFFECTIVE**(同上;自然语言指令,无强制执行层) |

(附加:`assistant_name` / `language` = STORED_BUT_UNUSED;`CustomizationOut` 可读写,运行时丢弃。)

## E. PERSISTENCE TRACE(AC-01)

- **Model**:`backend/db/models.py:205-218` — `Customization`:id(PK)、name、`system_prompt: Text NOT NULL`、`style_tone: Text | None`、`guardrails: Text | None`、`language: String(10) default "auto"`、`assistant_name: String(50) default "CamThink 助手"`、is_active、version。
- **绑定**:`CustomizationBinding`(models.py:221-225):`channel`(PK,`{widget,discord,whatsapp,mcp}`,admin 侧 `VALID_CHANNELS`,`customizations.py:27`)→ `customization_id`(FK,CASCADE)。
- **API schema**(`backend/api/admin/schemas.py:105-141`):`CustomizationOut`(三字段全量出)/ `CustomizationCreate`(`system_prompt` 必填 min_length=1;style_tone/guardrails 可空默认 None;language 默认 "auto")/ `CustomizationUpdate`(None=不写,即 PATCH 语义)。
- **CRUD**(`backend/api/admin/customizations.py`):GET/POST/PATCH(customizations)+ `/customizations/bindings`(BindingUpdate 按渠道绑定);角色 admin/editor 写、viewer+ 读;**仅写库,无任何缓存失效/热重载调用**。
- **前端**:`admin/src/pages/Customizations.tsx` 三字段编辑 → `useUpdateCustomization()`(`admin/src/hooks/useCustomizations.ts`)→ admin API → DB。
- 种子:`main.py:244-256` 无 `default` 定制时以 yaml system_prompt 播种并绑定 widget。

## F. CHANNEL BINDING TRACE(AC-08)

- 加载:`load_customizations_from_db`(`config_loader.py:64-87`)读全部 bindings → `{channel: {system_prompt(合并串), assistant_name, language, id}}`;**无绑定 → None → 全局回退 yaml**(`main.py:347-348`)。
- 运行时选择:请求 `AskRequest.channel`(合法值 widget/discord/whatsapp/mcp/admin,`api/schemas.py:96`)→ `rag.stream_answer(channel=...)` → `_build_messages` → `self._channel_customizations.get(channel, self._system_prompt)`(rag.py:387)。**未绑定渠道 → 回退默认 system_prompt**(= widget 渠道定制或 yaml,main.py:340-341)。
- 实际消费面:**当前仅 widget 与 admin 渠道有真实请求路由**(`/api/ask`;routes.py:185 只调 `stream_answer`);discord/whatsapp/mcp 有 schema 合法值与绑定 UI,但仓库内无对应接入路由 —— 绑定对它们目前是"预配置"。
- `default`:只是种子 Customization 的 **id**,非特殊运行时语义;`auto`:见 §N。

## G. REQUEST → LLM CALL CHAIN(AC-03)

```
POST /api/ask (api/routes.py:96 ask())
  → mask_pii → site 门禁(可选 site_id → resolve_site)
  → S2 预算熔断(declined 事件:不进 RAG,定制无从参与)
  → rag.stream_answer(channel=req.channel)      [rag.py:695;生产唯一路径]
      → override_matcher.match → 命中:直接返回人工答案(跳过全部定制)
      → classify_intent(query, llm)              [intent.py:59;_INTENT_PROMPT 代码内嵌,
       │                                          定制不参与;off_topic → REJECT_OFF_TOPIC 拒答]
      → extract_query / rewrite_query (llm)      [query_rewrite.py;自有 prompt,定制不参与]
      → _retrieve_and_fuse → reranker.rerank     [检索;SourceVisibilityGuard/渠道可见性在此生效]
      → 空结果 → 拒答(不调 LLM)
      → build_citation_context                   [引用完整性运行时控制]
      → _build_messages(..., channel, intent)    [rag.py:357]
          system = channel_customizations[channel](=SYS+STYLE+GUARD 合并串)
                   + "\n\n" + intent_styles[intent](运行时意图风格,排在最后)
          + history(截断) + 附件段 + page_hint(仅 user 消息)
      → llm.stream(messages, task="generation")  [rag.py:949;LLMRouter → 供应商]
  → 引用流式过滤 → done(conversation_id) → conversations/traces 落库
```

非流式 `answer()`(rag.py:473)同构:同一 `_build_messages`(652 行调用),`llm.generate`。**注意:`answer()` 未被任何 API 路由调用**(仅测试),生产路径只有流式。

## H. FINAL PROMPT COMPOSITION(真实顺序,动态实证)

```
messages[0] role=system:
  ├─ Customization.system_prompt                     (合并串头部)
  ├─ "## 风格语气"  + Customization.style_tone        (config_loader 拼接;非空才拼)
  ├─ "## 边界规则"  + Customization.guardrails        (拼接;非空才拼)
  └─ intent_styles[intent.category]                  (rag.py:389 追加;运行时指令,最后)
messages[1..]: 截断 history(conversation_max_turns*2)
messages[last] role=user:
  ├─ 查询 + 证据上下文(检索;引用编号权威集)
  ├─ 附件段(日志/截图,条件)
  └─ page_hint(宿主页背景,"非指令"标签;仅 user)
```

**优先级(实证)**:同一 system 字符串内的自然语言冲突**无确定性裁决机制**,位置靠后者在注意力上更近 —— `intent_styles`(运行时)排在用户三字段之后;三字段内部 style 在 guardrails 之前。配置值与运行时追加指令冲突时,**没有"谁赢"的保证**,应视为非确定性(需靠产品措辞避免冲突)。

## I. SYSTEM_PROMPT ANALYSIS(AC-04)

1. 每请求都加载?——**加载发生在启动时**(lifespan 快照),每请求只做 dict 查找;保存后不重启不生效。
2. 真 system role?——是:`messages[0] = {"role": "system", "content": 合并串}`(动态实证)。
3. 拼接模板?——是(config_loader 合并三字段 + rag.py 追加 intent_styles)。
4. 流式/非流式一致?——一致(动态实证两者 system 含全部 TRACE 串)。
5. 所有意图?——commercial/product/support 都走同一构造;`off_topic` 在 `_build_messages` 之前已被运行时拒答(rag.py:541/776),**定制不参与该路径**。
6. 绕过路径:`override_matcher` 命中(人工答案覆盖)、`off_topic` 拒答、预算 `declined`、空检索拒答 —— 四类均不携带定制。
7. 前后其他 system 内容:`intent_styles` 在其后追加;无其他 system 消息(page_hint 只进 user)。
8. 覆盖/稀释:无硬覆盖;但"后置指令优先"的注意力倾向 + 无冲突裁决 → 见 §H。
9. 辅助 LLM 调用(intent 分类 / query rewrite / rerank / pruner)**均不使用定制** —— 各有代码内嵌 prompt;rerank 非 LLM 文本生成路径。
10. 结论:用户 system_prompt **只控制最终答案生成**,不控制管道行为(意图/检索/引用/可见性均运行时所有)。

## J. STYLE_TONE ANALYSIS(AC-05)

**FULLY_EFFECTIVE**(作为合并串小节)。加载/拼接:`config_loader.py:74-75`,非空才拼(`## 风格语气\n...`);位于 system_prompt 与 guardrails 之间;流式/非流式一致(动态实证)。空值被忽略(None/空串不拼接)。**但注意**:它不是独立通道 —— 与 system_prompt 在同一条消息里,不存在独立的"风格"机制;`response_style` 与 `intent_styles` 是另外两套风格来源(yaml 的 `response_style` 键当前无运行时消费者)。

## K. GUARDRAILS ANALYSIS(AC-06)

**FULLY_EFFECTIVE(作为自然语言指令)/ PARTIALLY_EFFECTIVE(作为边界保障)**:
- 与 style_tone 同机制(`## 边界规则` 小节,config_loader.py:76-77),动态实证进入 system;空值忽略;流式/非流式一致。
- **纯自然语言 LLM 指令,无任何确定性强制层**;且多项真实边界**已由运行时管道所有**(见 §O):知识信任边界(SourceVisibilityGuard + channel_visibility 检索过滤)、引用完整性(权威编号上下文 + 流式过滤)、off-topic(intention 分类拒答)、语言(detect_language)。yaml 里已有一份同主题 `guardrails:`(信任边界案例条款),与定制 guardrails 构成**第二重叠来源**(且 yaml 那份同样只在被拼进 system_prompt 时才生效 —— 种子链路只播种 `system_prompt` 键,故 yaml guardrails 实际未生效)。

## L. STREAMING / NON-STREAMING PARITY(AC-07)

代码级 parity:两路径共用 `_build_messages`(rag.py:652 / 928),同 channel → 同合并串 → 同 intent_styles 追加;动态实证两者 system 均含 SYS/STYLE/GUARD。语言两路径同为 `detect_language(query)`。引用:stream 有 `CitationStreamFilter`,answer 走 `build_citation_context` + 下行前处理 —— 机制不同源但同属运行时所有。**唯一不对称**:`answer()` 无生产调用方(仅测试),parity 属"代码一致、生产单路径"。

## M. SITE / CHANNEL OWNERSHIP MAP(AC-10)

| 能力 | 所有者 | 证据 |
|---|---|---|
| 助手展示名(widget 界面) | **SiteExperience.display_name** | `/widget/site-config`(routes.py:318-330);非 Customization.assistant_name |
| 欢迎语 | SiteExperience.welcome | 同上 |
| Starter 问题 | SiteExperience.starters | 同上 |
| widget UI 语言 | SiteExperience.language(下发给前端) | routes.py:325 |
| **回答语言** | **Runtime**:`detect_language(query)` | rag.py:715/737;Customization.language 不参与 |
| 最终 system prompt | Customization(system_prompt+style+guardrails 合并) | §H |
| 回答风格(意图级) | Runtime `intent_styles`(yaml) | rag.py:389 |
| 身份/任务基线 | `system_prompt.yaml` 的 system_prompt(种子默认) | main.py:252 |

## N. `auto` SEMANTIC(AC-09)

`auto` = **`Customization.language` 列的默认值**(`models.py:214`,db 端 `default="auto"`;schema 端 `CustomizationCreate.language="auto"`),UI 渲染为 `{cust.assistant_name} · {cust.language}`(`Customizations.tsx:149`)。它**不是**路由/绑定/语言运行时语义:`language` 字段无运行时消费者(main.py 只投影 system_prompt),回答语言由 `detect_language` 决定。`auto = 未使用的存储默认值,仅 UI 展示`。

## O. RUNTIME VS PROMPT RESPONSIBILITY MAP(AC-11)

| 行为 | 归属 |
|---|---|
| 知识信任边界(内部源过滤) | RUNTIME(SourceVisibilityGuard + channel_visibility 检索过滤;fail-closed) |
| 引用/证据编号与流式去伪 | RUNTIME(build_citation_context + CitationStreamFilter) |
| 回答语言 | RUNTIME(detect_language) |
| 意图分类(含 off_topic 判定) | RUNTIME(LLM 分类,代码内嵌 prompt) |
| off-topic 拒答 | RUNTIME(硬编码 REJECT_OFF_TOPIC;定制不可控) |
| 人工答案覆盖 | RUNTIME(AnswerOverride,优先于一切定制) |
| 预算熔断 | RUNTIME(S2,declined 不进生成) |
| Sales Lead | **NOT FOUND**(专用确定性逻辑不存在;REJECT_BUSINESS 常量为死代码;商务诉求现走 RAG 拒答措辞) |
| 语气/表达风格 | CUSTOMIZATION_PROMPT_CONTROLLED(style_tone;与 intent_styles 叠加) |
| 任务边界/安全边界(软性) | CUSTOMIZATION_PROMPT_CONTROLLED(guardrails 自然语言;硬边界在 RUNTIME) |
| 身份/知识范围基线 | CUSTOMIZATION_PROMPT_CONTROLLED(system_prompt;种子来自 yaml) |
| widget 体验(名/欢迎/starter) | RUNTIME 配置(SiteExperience,非 prompt) |

## P. DYNAMIC PROOF

**RUNTIME_DYNAMIC_PROOF = RUN**(本地 mock,未提交任何代码):
构造真实 `RAGOrchestrator`,注入 `TRACE_SYSTEM_PROMPT_X / TRACE_STYLE_TONE_X / TRACE_GUARDRAIL_X`(经 config_loader 同款合并串)+ 假检索/假 LLM 捕获 messages:
- stream:system role 含三 TRACE 串;`intent_styles.product` 追加在 guardrails 之后;style/guardrails 置空时 system 逐字等于定制 system_prompt;admin 渠道回退 DEFAULT_YAML_PROMPT;
- answer():同 composition(role=system,三 TRACE 全在)。
无外部请求、无持久配置改动。

## Q. ARCHITECTURE ASSESSMENT

**C. INCOMPLETE**(接线不完整)+ **D. CONFLICT_PRONE**(指令源重叠):
- INCOMPLETE:保存不生效(需重启);assistant_name/language 死字段;discord/whatsapp/mcp 绑定无消费路由;yaml `guardrails`/`response_style` 键无消费者。
- CONFLICT_PRONE:定制三字段(合并) vs `intent_styles`(后置) vs yaml 同主题文本,三源无优先级裁决。

## R. PRODUCT RECOMMENDATION(仅建议,不实现)

**推荐 OPTION 2(职责拆分)+ 配套修复**,理由:三字段已按"身份/风格/边界"语义分工且全部生效,拆开的价值在于**可解释与可治理**;应做:
1. 修复生效性:Admin 保存后热重载 `app.state.rag._channel_customizations`(或启动后定期/按写失效刷新),消除"保存需重启"。
2. system_prompt = 身份/任务/通用推理;style_tone = 表达风格(保持 `## 风格语气` 小节);guardrails = 证据/安全/边界(保持 `## 边界规则` 小节);文档写明拼接顺序与"运行时 intent_styles 后置、冲突非确定性"的事实。
3. 明确"运行时已拥有的行为不得写进 guardrails"(见 §O 表):信任边界/引用/off-topic/语言/覆盖 —— 写了也不产生强制力,反而制造虚假安全感与指令冲突。
4. `assistant_name`/`language`:要么接通(widget 身份从绑定定制取),要么从 UI 收敛掉,避免"auto"这类死配置展示。
5. OPTION 1(全塞 System Prompt)不推荐:丢失字段级治理与默认模板能力;现状骨架已对,补线即可。

## S. RESIDUAL UNCERTAINTIES

- discord/whatsapp/mcp 未来接入时,绑定语义即刻生效(机制已就绪);当前无真实流量验证。
- LLM 对同消息内指令冲突的实际取舍是经验行为,非代码保证(已如实标注非确定性)。
- 本地动态证明使用 mock 检索/LLM,未覆盖真实供应商响应差异(不影响 prompt 组成结论)。

## T. PRODUCTION BOUNDARY

PRODUCTION_ACCESS = NO;PRODUCTION_MUTATION = NO;无配置/数据库/定制内容改动;无产品代码 commit(仅本报告)。
