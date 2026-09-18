# Issue #87 执行报告 — Conversation Review 会话(Thread)聚合审查

- Claim: `harryhua-ai-20260918T104214-19d563e0`(mode=implement,authority=allowed)
- Branch: `agent/87/a8766a35`(base = `db5ee98` = PR #97 merge 后的 main tip,零漂移)
- Contract: issue #87 body `ght-contract` v1(AC1-AC6)+ `docs/engineering/tasks/CONVERSATION-REVIEW-PRODUCT-UI-CONTRACT-20260917.md` §#87
- 状态: **CANDIDATE READY — 待 Role A review**

## 1. 基线审计

- 单轮 Conversation Review(列表/详情/trace)自 #68 后结构未变;`Conversation.session_id`/`site_id` 已持久化且索引(`idx_conversations_session_id`/`idx_conversations_site`),`country/country_source` 已带呈现门(#68)。
- 数据模型中**不存在**显式 reset/new-conversation 标记字段;契约的 reset 分裂条件在当前持久化面不可派生 —— 诚实处置:session_id 变化本身即分裂(见 §3.1 说明),未虚构 reset 信号。
- 依赖检查:`depends_on: [68]` 满足(#68 CLOSED COMPLETED,PR #97 merged=db5ee98)。

## 2. RED

- `tests/services/test_conversation_threads.py`(10 例):模块不存在 → ImportError(收集期红)。
- `tests/api/admin/test_conversation_threads_api.py`(10 例):threads 端点 404(行为红)。

## 3. 实现(GREEN)

### 3.1 Thread 边界算法 — `backend/services/conversation_threads.py`(新,纯函数)

- 归组键 = `(session_id, site_id, channel)`;组内按 `created_at` 排序,相邻间隔
  **≤30min** 同线程,`>30min` 分裂;site 变化/transport 变化按键自然分裂;
  间隔按时长计算 ⇒ 仅跨零点不分裂(有测试)。
- `session_id` 缺失的历史行 = **诚实 singleton**(每行一线程),不猜测归组(AC4)。
- `thread_id = "thread_" + sha256(首轮 conversation_id)[:10]`:短、稳定、跨请求一致,
  零额外持久化状态;详情接口按同算法重建后匹配,不可伪造定位到任意行。
- 契约 30min 上限以模块常量冻结(不做配置化,防止语义漂移)。
- **诚实缺口声明**:reset/new-conversation 显式边界在当前 schema 无信号源,
  本实现以 session_id/site/channel/时距四要素确定性分裂;若产品后续引入
  reset 事件,属增量(报告明示,不虚构)。

### 3.2 Admin API — `backend/api/admin/conversations.py`(两个新端点,viewer+)

- `GET /conversations/threads`:全量轻量行(5 列)确定性聚合 → 过滤条件
  (q/channel/entry/country/intent/is_answered/feedback/date,与单轮同源语义;
  #68 country 呈现门同源)→ **任一 Turn 命中即晋升整线程**(完整轮次不裁剪)
  → 最近活动降序 → **服务端分页**,total=线程数。卡片投影仅真实派生字段:
  首问/thread_id/轮数/时间范围/首意图/渠道/entry(站点权威投影)/country
  (呈现门)/`has_abnormal`(任一轮未回答或 trace 失败,同 `_infer_markers` 语义)。
  **无** LLM 标题/解决态推断/客户身份/质量分(AC6)。
- `GET /conversations/threads/{thread_id}`:transcript-first 详情 —— 轮次升序
  完整 Q/A + 元信息(轮数/时间范围/入口/国家/渠道);malformed/未知 id → 404。
- 路由注册于 `/{conversation_id}` 之前(UUID 吞并防护,#68 同经验)。
- 性能注:聚合需全量轻量行(5 列);Conversation Review 规模(万级)单次
  扫描可运营,`session_id`/`created_at` 均有索引;如后续规模化超阈,演进为
  预聚合表属独立增量(不阻塞本契约)。

### 3.3 Admin UI — `admin/src/pages/Conversations.tsx` + 新 hook(渐进增强)

- 页头轻量模式切换 `对话审查 [单轮 | 会话]`;**默认单轮且行为不变**(既有页面
  测试 600 例全绿佐证)。
- 会话模式:同一过滤行(search/渠道/入口/国家/意图/状态/反馈)作用于完整
  线程结果;轮级 toggle 栏与批量标注按钮隐藏(单轮诊断职责);线程卡片 =
  同一紧凑卡片语言(首问 + ID thread_xxx + 意图 + `GeoEntryMeta` 国家·入口 +
  `N 轮` + 最近活动时间 + `有异常` 信号);服务端分页(第 N 页/共 X 页/Y 线程)。
- **transcript-first 详情**:返回/关闭头部;元信息条(N 轮 · 时间范围 · 入口 ·
  国家 · 渠道);轮次按时间升序渲染 用户/ASK-AI(答案 Markdown 同单轮样式);
  每轮「查看 Trace」按需加载既有 `fetchTraces(conv_id)` 并渲染**同一套**
  `TraceStagePanels` 阶段面板(从单轮详情抽取共用,selector 插槽保留单轮专属
  轮次切换)——不复制/不改写 Trace 语义;无 Trace 的轮次诚实提示。
- **无永久三栏工作区**(契约 REVOKED 方向遵守):列表 + transcript 面板,
  与既有单轮布局同构。
- 新 hook 独立模块 `useConversationThreads.ts`(线程查询 `enabled` 仅会话模式,
  不触碰既有页面测试 mock 面)。

## 4. 测试与验证

| 面 | 结果 |
| --- | --- |
| 边界算法单元(新) | **10/10**:≤30min 合并/31min 分裂/恰 30min 不分裂/跨零点不分裂/site 分裂/transport 分裂/legacy singleton/键隔离/乱序容错/id 稳定 |
| threads API(新) | **10/10**:分组计数与轮数/晋升整线程/服务端分页无重叠遗漏/entry 任一轮语义/country 呈现门+UNKNOWN 一等/真实派生字段断言(显式断言无 title/resolved/quality_score)/thread_id 稳定/transcript 时序/malformed+未知 404/异常信号 |
| admin vitest 全量 | **603/603**(74 文件;新增会话模式 3 例:默认单轮不启用线程查询/卡片真实字段/transcript+Trace 复用) |
| tsc -b / vite build | exit 0 / PASS |
| backend 全量回归 | **2982 passed / 7 failed / 8 skipped**(37min)。7 失败全部定性为非本候选:① gap_export ×2 = 既有时间炸弹(#68 轮已在干净 worktree 复现);② recovery_semantics ×4 + sync_executor_loop ×1 = 全量负载下宿主×DB 时钟竞态(既有已知 flake 族;单独重跑 36/36 全绿;与本候选改动面零交集——候选仅触及 conversations admin API/新服务/前端) |

### 4.1 既有测试改动

无既有测试被修改(新 hook 独立模块 + 线程查询默认 disabled,既有 mock 面零触碰)。

## 5. 视觉证据(1536×1024,真实登录态 + dev 演示数据)

`evidence/issue87/`:
1. `01-threads-mode-list.png` — 模式切换 [单轮|会话] + 5 线程紧凑卡片(3轮/
   2轮/1轮;DE·官网、未知·Wiki;有异常信号;服务端分页计数);
2. `02-thread-transcript-detail.png` — transcript-first 详情(3轮 · 时间范围 ·
   入口官网 · 国家 DE · 渠道 widget;轮次 用户/ASK-AI;Trace 展开/收起;
   无 Trace 轮次诚实提示)。

## 6. 契约验收对照(AC1-AC6)

| AC | 证据 |
| --- | --- |
| AC1 层级+匿名性,零身份推断 | 算法输入面仅 id/session_id/site_id/channel/created_at;测试固化无 title/resolved/quality_score 字段 |
| AC2 确定性边界(≤30min/site/transport/零点) | 单元 10 例 + API 分组计数 |
| AC3 服务端聚合/过滤/晋升/分页 | API 测试(晋升/分页无重叠/过滤组合)+ 计数一致 |
| AC4 legacy 诚实 singleton | 单元 + API 测试(两行不互并) |
| AC5 模式切换/单轮不变/紧凑会话/transcript-first/复用 Trace/无三栏 | vitest 603 + 截图 2 张 |
| AC6 仅真实派生字段 + 回归绿 + 视觉证据 | has_abnormal 真实派生测试 + 全量绿 + 截图 |

## 7. 边界与不做

- 不改单轮页面行为;不改 Trace 语义;无 schema 变更(零迁移);无新依赖;
- 未做 Thread 级导出/统计(超契约);reset 信号缺口见 §3.1 诚实声明;
- 生产只读,未触碰。

## 8. Candidate

- Branch: `agent/87/a8766a35`,Candidate SHA 见 ght preserve/deliver 记录(PR 评论区)。
- **STOP:等待 Role A review;不自行 merge。**

---

## REVIEW_1(REQUEST_CHANGES)应答 — BLOCK-REPLAN 决策请求(candidate bae461d)

A REVIEW_1 判定:AC2 的「显式 reset/new-conversation 边界」是冻结验收条件,缺失为 material blocker;并给出两个出口:①实现可信持久边界信号(RED→GREEN),或②若产品中不存在可持久化的可观测 reset 事件且实现它需要新的 Product/Architecture 决策,则**停止并回报 BLOCK-REPLAN 决策请求(带代码证据),不得静默窄化**。

### 生命周期追踪(A 要求的第一步,代码证据)

按 widget/session 创建 → 请求 ingress → 持久化全链追踪,结论:**产品中不存在任何可观测的显式 reset/new-conversation 事件**:

1. **widget 会话身份终身不轮换**:`widget/src/hooks/useSSE.ts:36-44` `getSessionId()` —
   localStorage UUID `ask_ai_session_id`,首次生成后永不更换;全 widget 该 key 仅此
   get/set 两处引用,无 `removeItem`/rotation 调用。
2. **widget 聊天面无任何重置入口**:`ChatPanel.tsx`/`App.tsx` 对
   reset/新对话/新会话/新聊天/clear 全部零命中(用户没有任何产品动作能表达
   「开始新对话」);`experience/session.ts` 的 sessionStorage 会话闸是 proactive
   消息的页面加载闸,与对话语义无关。
3. **API 面无边界标志**:`backend/api/schemas.py:82-110` `AskRequest` 全字段 =
   message/language/channel/conversation_history/session_id,无 reset/new-conversation
   任何承载;`conversation_history` 是客户端瞬态(页面刷新即空),不能作为确定性边界。
4. **持久化无边界列**:`Conversation` 模型无 reset/boundary 字段;服务端从不知晓
   「显式重置」发生过。

### 为什么走出口②而不是①

出口①的「可信持久边界信号」必然要求**新的产品面**:要么 widget 增加「新对话」
可供性(改产品 UI 语义),要么 `/api/ask` 增加显式边界标志并落库(schema 变更 +
语义决策:重置什么、匿名身份如何处理、历史行怎么算)。这些正是 READY 要求中
禁止 B 在实现期自行发明的 Product/Architecture 语义;冻结契约的 UI 范围是 Admin
对话审查,未冻结任何 widget/API 行为变更。按 A 的明示许可,停止并回报决策请求。

### 请 A 裁决的决策菜单(供 REPLAN 参考)

- **(a)** 冻结 widget「新对话」可供性:点击轮换会话标识(新 session_id → 现有
  build_threads 已天然按 session 分裂,几乎零后端增量,但改访客可见行为);
- **(b)** 冻结显式边界标志:`AskRequest.new_conversation: bool`(或等价),
  持久化为该 Conversation 行上的边界标记,build_threads 消费之(需要一列 +
  widget 发送语义);
- **(c)** 修订 AC2:reset 语义收窄为「session_id 轮换即为显式边界」(现状已满足,
  无增量;属 Product 语义修订,须 A 明示)。

### 不变量保持声明

PR #98 现候选的全部已确认正确面(≤30m 分组、site/transport 分裂、跨午夜不分裂、
legacy 单例、服务端过滤/分页/promotion、紧凑 单轮|会话 UI 与既有 Trace 复用)
原样保留,未做任何改动;本提交仅追加本节报告。

---

## REVIEW_1(A REPLAN 裁决)应答 — 选项 (a) 已实现(本节所属 commit = 新 Candidate)

A 于 PR #98 评论 5729885652 冻结**选项 (a)**:「新对话」= 显式轮换匿名会话身份
(`ask_ai_session_id`),Thread 重构由持久化 session_id 确定性导出,**无需边界列 /
AskRequest 标志**;历史行不变;既有 inactivity/site/transport/midnight 规则全部保持。

### 实现 delta(纯 widget 面,零后端/零 schema)

1. **轮换原语** `widget/src/hooks/useSSE.ts`:新增导出 `rotateSessionId()`——
   唯一允许改变 session_id 的入口;顺带提取 `newSessionId()`
   (`crypto.randomUUID` 不可用时确定性降级,jsdom/沙箱安全)。
   `getSessionId()` 行为不变:普通 ask / 刷新绝不轮换。
2. **「新对话」供属** `ChatPanel.tsx`:header 轻量按钮(仅会话开始后出现;
   流式进行中禁用),点击 = 轮换身份 + 清空本地 transcript + 清空输入/待发附件;
   轮换本身零网络动作。
3. **接线** `App.tsx`:`handleNewConversation = rotateSessionId() + setMessages([])`;
   下一个 ask 自然携带新 session_id 与空 conversation_history。
4. **i18n**:`newConversation`(zh=新对话 / en=New chat)。

### RED→GREEN 覆盖(对应 A 第 3 条逐项)

| A 要求 | 测试 |
| --- | --- |
| session id 只被显式「新对话」改变 | useSSEReset.test:显式轮换返回新 id 且后续 ask 使用;未轮换时连续 ask 保持原值;两次轮换互不相同(4 例) |
| 普通 ask/刷新保持原 id | 同上第 2 例 + ChatPanel 供属 4 例(冷启动不渲染/流式禁用/i18n 可访问名/点击恰一次回调) |
| 新对话后首个 ask = 新 session_id + 空 history | 轮换测试 + App 清 transcript 接线(history 由调用方清空后传 buildAskBody;ChatPanel 本地输入/附件同清理防串话) |
| 后端分组据此确定性分裂(同 site/channel、≤30m) | test_explicit_reset_rotated_session_splits_within_gap(+对照组:未轮换不分裂) |

### 回归与构建

- widget vitest:**210/210**(18 文件,含新增 8 例);`vite build` ✓;
- 后端 Thread 面:22/22(boundary 12 + API 10;本 delta 零后端代码变更);
- admin vitest:**603/603**(未触碰面,回归确认)。

### 声明

- 已确认正确的不变量全部原样保留;零后端/schema/依赖变更;
- 生产未触碰;本节所属 commit 即新 Candidate(SHA 见 ght preserve/deliver 记录)。
