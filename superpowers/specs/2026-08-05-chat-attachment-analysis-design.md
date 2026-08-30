# 聊天附件分析能力（图片 + 日志）设计

- **日期**：2026-08-05
- **状态**：待审阅（spec self-review 已通过，等待用户确认）
- **作者**：brainstorming 会话产出
- **后续**：用户审阅通过后转入 `writing-plans` 制定实施计划

---

## 1. 目标与背景

ask-ai 当前是纯文本 RAG 系统（FastAPI + Weaviate + DeepSeek），聊天走 `/api/ask` SSE 流式，**零文件上传 / 零多模态能力**。本次新增：用户在聊天窗口上传**截图**和**纯文本日志**，系统将其作为**会话补充上下文**进行详细分析排查问题。

附件是**会话问题的补充**：日志作为文本补充，截图经 vision 模型处理后作为补充；附件内容要与**会话历史关联**（而非独立的"文档分析"任务）。

### 核心约束（已与用户确认）

| 维度 | 决策 |
|---|---|
| 文件类型 | 仅图片（png/jpg/jpeg/webp）和文本日志（txt/log），**其它一律拒绝** |
| 文件类型判定 | 扩展名白名单 **∩** magic bytes 白名单，两者都过才合格 |
| 处理方式 | 日志=文本提取注入；截图=vision 模型处理转描述文本后注入 |
| 耦合方式 | 两步式：先 `POST /api/upload` 拿 attachment_id，再带 `attachments` 调 `/api/ask` |
| 目标用户 | widget 匿名 + admin 登录，两者都要 |
| Vision 模型 | 新增独立 LLM provider（具体型号待定），走 `LLMRegistry`/`LLMRouter`，task=`vision` |
| 文本模型 | 现有 deepseek（`.env` 实际 `DEEPSEEK_MODEL=deepseek-v4-pro`） |
| 存储 | 短期保留，**30 天后自动清理**原始文件；提取结果留在会话上下文 |
| 大小上限 | 单文件 ≤ 5 MB |
| 附件数量 | 单条消息 ≤ 5 个 |
| 超大日志 | 全文注入（大窗口）；超过阈值自动 fallback RAG 检索日志片段 |
| Vision 描述 | **缓存复用**（首次跑完存 `extracted_text`，后续问题复用） |
| 图片传递 | **文件 URL**（非 base64） |
| UI 形态 | kapa.ai 风格（胶囊输入框 + 圆形 `+` 附件按钮 + 圆形黑底发送），配色沿用现有 widget |
| UI 文案 | 窗口内所有提示/错误文案**统一英文** |

---

## 2. 整体架构与数据流

```
[前端 widget/admin]
  ① 用户点 + 选文件(图/日志, ≤5MB, ≤5个)
  ② POST /api/upload (multipart) ─────────► [后端]
       • 校验(类型/大小/数量/magic bytes)
       • 落盘 data/attachments/YYYY-MM-DD/<id><ext>
       • DB 写 Attachment 行
       • 异步预处理(BackgroundTasks):
           - 日志 → 提取纯文本 → extracted_text, status=ready
           - 截图 → 暂存原图, extracted_text 空, vision_done=False, status=ready
  ③ 前端拿 attachment_id 列表, 显示 chip(就绪/上传中/失败)
  ④ 用户发问(带 attachments:[id...])
  ⑤ POST /api/ask {message, channel, conversation_history, attachments:[id]}
       │
       ▼ [RAGOrchestrator.stream_answer(query, ..., attachments)]
       • 加载 attachments(归属校验)
       • 日志: extracted_text
           - ≤ LOG_FULL_THRESHOLD → 全文注入
           - > 阈值 → 临时建索引 RAG 检索相关行
       • 截图: 逐张调 vision (task="vision")
           - 返回描述 → 缓存进 extracted_text, vision_done=True
           - 失败/预算超 → 占位文本, 不阻塞
       • _build_messages: user content 注入 [日志文本 + 图片描述]
       • 正常 generation 流式回答(SSE token 不变)
  ⑥ SSE: sources → token(s) → done
  ⑦ 定时任务: 清理 created_at > 30 天的原始文件
```

**关键边界**：
- 上传与问答解耦：上传只提取/落盘，问答才跑 vision（带问题看图，质量更高）。
- 附件归属校验：widget 用 `session_id`、admin 用 `user_id`；`/api/ask` 校验 attachment 归属当前调用者，**越权引用 403**。
- vision 结果缓存复用。
- 失败 fail-open：单附件失败降级为占位文本，不阻塞整次问答。

---

## 3. 数据库与存储模型

### 3.1 新增 `Attachment` 表（`backend/db/models.py`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID PK | |
| `conversation_id` | UUID FK→conversations.id, nullable | 问答关联时回填 |
| `owner_type` | Enum(widget_anon, admin) | |
| `owner_id` | str | widget=匿名 session_id；admin=user_id |
| `filename` | str | 原始文件名（清洗后，限 255 字符） |
| `mime_type` | str | image/png, image/jpeg, image/webp, text/plain, text/x-log |
| `kind` | Enum(image, log) | 按 mime 判定（仅两种） |
| `size_bytes` | int | |
| `storage_path` | str, nullable | 相对路径 `data/attachments/YYYY-MM-DD/<id><ext>`；清理后置 null |
| `extracted_text` | Text, nullable | 日志=全文；截图=vision 描述（空=未处理） |
| `parse_warning` | str, nullable | 日志解析降级原因（编码异常/截断等），非空表示 `extracted_text` 是降级后的原始片段 |
| `vision_done` | bool default False | 截图是否已跑过 vision |
| `created_at` | datetime | 清理任务依据 |

### 3.2 `Conversation` 表改动

- 新增反向关系 `attachments`（懒加载，避免历史无附件会话开销）。
- 不新增 `attachments_json` 字段（多对一用 FK 更规范）。

### 3.3 建表方式

项目**无 Alembic**，启动时 `init_db` 走 `Base.metadata.create_all`（`backend/db/session.py:74`）。Phase 1 沿用此机制——新增 `Attachment` 模型后自动建表，**不引入 Alembic 迁移**（避免范围蔓延；生产迁移留作后续独立工作）。

### 3.4 物理存储

- 路径策略：`data/attachments/YYYY-MM-DD/<attachment_id><ext>`，按日期分目录便于清理。
- 文件不进 DB（避免 JSONB/base64 膨胀），DB 只存 `storage_path` 相对路径。
- 部署：`deploy/docker-compose.yml` 新增 `data/attachments` 卷（与现有 corpus/knowledge 卷并列）。
- 清理：后台定时任务扫 `created_at > 30 天`，删物理文件 + 置 `storage_path=None`，**保留 DB 元数据**（`extracted_text` 留在会话）。

---

## 4. 上传端点 + 校验 + 限流

### 4.1 `POST /api/upload`（`backend/api/routes.py`）

```
请求: multipart/form-data
  files: list[UploadFile]   (1~5 个)
  channel: str              (widget|admin)
  session_id: str           (widget 匿名会话标识；admin 走 JWT)
返回:
  { attachments: [
      { id, filename, mime_type, kind, size_bytes,
        status: "ready" | "processing",
        ok: true } | { ok: false, error: "..." } ] }
```

职责：同步校验 + 落盘 + 写 DB；日志文本提取异步（`BackgroundTasks`）；截图直接 `ready`（vision 推迟到问答）。

**同步返回 status 语义**：日志返回 `status="processing"`（提取中，前端 chip 显示 spinner，提取完转 ready）；截图返回 `status="ready"`（原图已落盘即可发问，vision 推迟到 `/api/ask`）。

### 4.2 校验规则

| 规则 | widget 匿名 | admin 登录 |
|---|---|---|
| 单文件大小 | ≤ 5 MB | ≤ 5 MB（一期统一） |
| 单次数量 | ≤ 5 | ≤ 5 |
| 允许类型 | png/jpg/jpeg/webp/txt/log | 同左 |
| 类型判定 | 扩展名白名单 ∩ magic bytes 白名单 | 同左 |
| 文件名 | 清洗（去路径、限 255、去控制字符） | 同左 |

- 单文件失败不影响其他：逐项返回 `{ok:false, error}`；全部失败整体 422。
- magic bytes 嗅探：读首字节辨真实类型（防 `.txt` 里塞 exe、`.png` 实为文本伪装）。
- 白名单外一律拒绝（不需要可执行文件黑名单）。

### 4.3 限流（复用 slowapi）

- `/api/upload` widget 匿名 **10/min**（比 `/api/ask` 的 20/min 严）；admin JWT **30/min**。
- 按 channel 切换限流 key，复用 `routes.py` 现有 slowapi decorator 模式。

### 4.4 鉴权与归属

- widget：`session_id` 前端生成（localStorage UUID），upload 与 ask 一致；ask 时校验 `attachment.owner_id == session_id`。
- admin：JWT 拿 `user_id`，校验归属。
- 越权引用 **403**。
- **匿名模型局限**：widget 的 `session_id` 由前端生成、无服务端签发，攻击者可枚举 UUID 引用他人匿名附件。因此匿名附件的 `owner_id` 校验是**防误用**（不同浏览器/会话不串附件），**非防恶意越权**。如需更强保护，对 widget 附件额外加签名 token + 短时效（实施时评估，不阻塞 Phase 1a）。

### 4.5 异步预处理

- **日志**：`BackgroundTasks` 跑文本提取（去控制字符、统一编码 UTF-8/GBK/UTF-16、可选行数上限防乱码撑爆）→ 写 `extracted_text` + `status=ready`。
- **截图**：`status` 直接 `ready`，`extracted_text` 空，`vision_done=False`。
- **日志解析失败**：标 `ready` + `extracted_text` 存原始片段 + 标记 `parse_warning`，不阻塞问答。

---

## 5. RAG 编排：Vision + 上下文注入 + 超限 fallback

### 5.1 `stream_answer` 改动（`backend/pipeline/rag.py:469`）

签名新增 `attachments: list[Attachment] | None`，在 generation 前插入附件预处理：

```
for att in attachments:
    if att.kind == "log":
        log_text += extract_or_retrieve(att, query)
    elif att.kind == "image":
        if not att.vision_done:
            # vision 走 LLMRouter.stream(task="vision"),为 async generator
            # 需聚合为完整字符串后缓存(勿照抄 desc = await ...stream(...))
            desc = "".join([c async for c in self._llm.stream(
                build_vision_messages(att, query), task="vision")])
            att.extracted_text = desc; att.vision_done = True
            # session 传递（实施必做，否则缓存丢失）:
            #   (1) RAGOrchestrator 当前 __init__ 只注入 searcher/reranker/llm,
            #       无 session_factory —— 需新增注入,或 stream_answer 形参传入;
            #   (2) att.extracted_text = desc 的 vision 缓存写入必须在该 session
            #       作用域内 commit 才持久化(否则请求结束 session 关闭、下次同图重跑)。
            #   具体由调用方 routes.py(路由层持有 session_factory)负责 commit。
        image_context += att.extracted_text

messages = self._build_messages(
    query, context, language, conversation_history, channel, intent,
    log_text=log_text, image_context=image_context)
```

副管线（intent/rewrite/pruner）不受污染——附件只进 generation 的 user message。

### 5.2 Vision 编排细节

- **`build_vision_messages`**：构造 `[{role:user, content:[{type:text, text:"User question: {query}\nDescribe the error/UI/key info in this screenshot for troubleshooting"}, {type:image_url, image_url:{url: <file_url>}}]}]`。
- **图片传递**：文件 URL（需静态服务或签名 URL；spec 落实具体服务方式——倾向在 FastAPI 加一个 `/api/attachments/<id>/raw` 端点，仅限 vision provider 内网调用，不公网暴露）。
- **多图**：串行调用（一期不做并行），避免触发 provider 限流。
- **vision 失败**：`image_context="[Image analysis unavailable]"`，继续 generation，不阻塞。
- **预算**：vision 调用前 `BudgetLimiter.check_and_reserve` 再 reserve 一次（vision 通常更贵）；超限跳过 vision，`image_context="[Image skipped: budget limit]"`。
- **缓存复用**：`vision_done=True` 后复用 `extracted_text`，不重跑。

### 5.3 日志注入 + 超限 fallback（`extract_or_retrieve`）

```
def extract_or_retrieve(att, query):
    text = att.extracted_text
    if count_tokens(text) <= LOG_FULL_THRESHOLD:
        return text  # 全文注入
    else:
        return retrieve_log_chunks(text, query)  # fallback
```

- **阈值**：`LOG_FULL_THRESHOLD`（待查 v4-pro 实际上下文窗口后定具体数值；占位 300_000 tokens）。
- **fallback 检索**：按行/固定大小分块（如 500 行/块），用现有 `BGEEmbedder` 嵌入，按 query 召回 top-K 块拼接。**不进 Weaviate**（临时数据，问答后丢弃）。
- **注意**：`BGEEmbedder.embed`（`bge.py:86`）是**同步**方法，在 async `stream_answer` 内直接调用会阻塞事件循环——需用 `asyncio.to_thread` 包装，或预提取。
- **拼接顺序**：日志在前、图片描述在后，放 user message 的 context 段。
- **PII**：日志文本注入前复用 `mask_pii`（`backend/utils/pii.py:18`，`routes.py:80` 已用于 message）。

### 5.4 `_build_messages` 改动（`backend/pipeline/rag.py:257`）

`rag.py:288-307` 的 `user_content` f-string 拼接新增两段（现有 f-string 起于 288，`messages.append` 在 307）：

```
user_content = f"""
{existing_context_from_rag}

[User uploaded log]
{log_text}

[User uploaded screenshot analysis]
{image_context}

User question: {query}
"""
```

content 仍是 `str`（generation 模型吃纯文本；vision 已在前置步骤转描述）。**只有 vision 调用用多模态 content list，generation 仍是 str**，改动最小。

**注入位置（实施注意）**：现有 `user_content` 是固定中文 Markdown 模板（`## 检索到的资料` / `## 问题` / `## 要求`，`rag.py:288-307`）。不要替换模板结构，而是在 `## 检索到的资料` 段后追加 `[User uploaded log]` / `[User uploaded screenshot analysis]` 子段，保留原 Markdown 结构与"## 要求"规则段。

### 5.5 LLM 抽象层改动

核查结论（`backend/llm/`）：
- `DeepseekProvider.stream`（`deepseek.py:74`）原样透传 `messages`，多模态 dict 无需改 HTTP 层。
- `DeepseekProvider.generate`（`deepseek.py:47`）、构造（`:27`）、`@LLMRegistry.register("openai_compatible")`（`:19`）。
- `LLMRouter` 按 task 字典查找（`registry.py:48-50`），新增 task 不需改代码。
- 新增 `task="vision"` 落点：
  1. routing 表（YAML `config/llm_providers.yaml` 或 DB `llm_routing`，DB 优先）加 `vision` 条目。
  2. 新 provider 实例配置（DB `llm_providers` 或 YAML `providers:`）含 vision 模型名。
  3. 调用点 `stream_answer` 传 `task="vision"`（当前硬编码 `generation`）。
- 可走 admin API（`backend/api/admin/llm_providers.py`）热配 provider/routing，不必改代码。

---

## 6. 前端 UI/UX

### 6.1 视觉规范（kapa 形态 + 现有配色）

| 元素 | 样式 |
|---|---|
| 输入框容器 | 白底 `#ffffff`；border `1px solid #dbdbdb`；`border-radius:14px`；无阴影 |
| `+` 附件按钮 | 内联 SVG 细线 `plus`，圆形 32×32，`color:#888888`，hover 底色 `#f9f9f9` + 文字 `#333333` |
| 发送按钮 | 圆形 32×32，`background:#000000`，白色 arrow-up SVG |
| 附件 chip | `border-radius:8px`；`background:#f9f9f9`；border `#dbdbdb`；高 30px |
| chip 失败态 | **新增色** border `#dc2626` + 红 ✕，hover tooltip 显示原因（现有 widget.css 无此色值，本次新引入用于错误态） |
| chip 上传中 | 14px spinner，文字 `Uploading…` |
| 图标 | 全部内联 SVG，不引入图标库 |
| 文案 | 全英文（placeholder `Ask a question…`、提示、错误、aria-label） |

### 6.2 组件改动

- **`widget/src/components/ChatPanel.tsx`**：输入区改为胶囊容器；加 `+` 按钮（触发隐藏 `<input type="file" multiple accept=".png,.jpg,.jpeg,.webp,.txt,.log">`）；加 chip 行容器。
- **`widget/src/types.ts`**：`ChatMessage` 新增 `attachments?: [{id, filename, kind, thumbnail_url?}]`。
- **`widget/src/components/MessageBubble.tsx`**：气泡上方渲染附件 chip 行。
- **`widget/src/hooks/useSSE.ts`**：
  - `ask(message, history, attachments)`：请求体加 `attachments`。
  - `upload(files, sessionId)`：新方法，调 `/api/upload`。
- **session_id**：前端首次生成 UUID 存 localStorage，upload 与 ask 都带。
- **附件 chip 存储**：随消息存前端 state，**刷新即丢失**（与现有 widget 历史"纯内存、无会话恢复"行为一致；不额外做持久化回填）。
- **样式**：追加到 `widget/src/styles/widget.css`（原生 CSS，无新框架），复用现有 CSS 变量。
- **admin**：复用 widget `App`（`admin/src/components/LoginChat.tsx` 现状），自动获得。

### 6.3 不做（一期）

- 拖拽上传
- 粘贴上传（Ctrl+V）

---

## 7. 错误处理

| 层 | 错误 | 处理 |
|---|---|---|
| 前端 | 超量/超大/错格式 | 客户端预校验，英文 toast，不发请求 |
| 前端 | upload 网络失败 | chip 标 Failed + 重试 |
| `/api/upload` | MIME/magic 不符 | 单文件 `{ok:false, error:"Unsupported file type"}`，422 |
| `/api/upload` | 超 5MB / 超 5 个 | 422，英文错误 |
| `/api/upload` | session 不一致 | 401 |
| `/api/ask` | attachment 归属他人 | 403 |
| `/api/ask` | attachment 不存在 | 422 `Unknown attachment` |
| RAG · vision 失败/超时 | | `image_context="[Image analysis unavailable]"`，继续 |
| RAG · vision 预算超限 | | 跳过 vision，`image_context="[Image skipped: budget limit]"` |
| RAG · 日志解析失败 | | 原始片段 + `parse_warning`，继续 |
| RAG · 日志超限 | | 自动 RAG fallback，top-K 行拼接 |
| RAG · generation 超 context | | 现有 BudgetLimiter 兜底（declined 事件） |

原则：附件相关失败**永远 fail-open**——单附件失败降级为占位文本，用户至少拿到基于文本的回答。

---

## 8. 测试策略

**单元测试（pytest，`tests/`）**：
- `Attachment` 模型 CRUD、归属校验
- 文件校验：白名单 ∩ magic bytes（含伪装用例）
- `extract_or_retrieve`：小日志全文 / 大日志 fallback 阈值边界
- `build_vision_messages`：多模态 content 结构
- 清理任务：>30 天删除、<30 天保留

**集成测试**：
- `POST /api/upload` → `POST /api/ask` 全链路（mock LLM）
- 越权引用 attachment → 403
- vision 缓存：第二次同图不重跑
- 日志超限 fallback 触发检索

**E2E（Playwright）**：
- widget：点 `+` 选文件 → chip → 发送 → 收到带附件回答
- 上传失败红框展示

**fixtures**：mock vision provider，sample 日志/图片。覆盖率目标 80%+。

---

## 9. 风险与缓解

| 风险 | 等级 | 缓解 |
|---|---|---|
| vision provider 待定，v4-pro 可能不支持图片 | 高 | task="vision" 独立 provider，admin API 热配；Phase 1 可先不接真实 vision，图片暂返 `[Vision not configured]`，主流程（日志）先上线 |
| 文件 URL 服务方式未定 | 中 | FastAPI 加 `/api/attachments/<id>/raw`（内网/签名），不公网暴露 |
| 大日志全文注入拖慢首 token | 中 | `LOG_FULL_THRESHOLD` + fallback 检索；BudgetLimiter 兜底 |
| 附件存储增长（widget 匿名） | 中 | 30 天清理 + 限流 10/min |
| vision 成本失控 | 中 | BudgetLimiter 覆盖 vision；缓存复用 |
| PII 泄露（日志/截图） | 中 | 日志走 `mask_pii`；截图靠短期保留+清理 |
| 无 Alembic | 低 | 沿用 `create_all`（Phase 1 范围内） |

---

## 10. Phase 1 范围（拆分降低风险）

### Phase 1a（日志先行，可立即上线）

- `POST /api/upload` + `Attachment` 表 + 校验 + 限流
- 日志全文注入 + 超限 fallback
- 前端 `+` 上传 + chip UI（全部状态）
- 清理任务
- 越权校验、归属校验
- `ChatMessage` 扩展 + MessageBubble 附件展示
- **图片处理（1a）**：`accept` 暂限 `txt/log`（不开放图片选项），避免用户上传图片后无 vision 能处理；1b 接入 vision 后再开放图片 `accept`。

### Phase 1b（截图 vision，待 provider 确定）

- vision provider 接入（task="vision"，admin API 热配）
- `_build_messages` 多模态 content（仅 vision 调用）
- `build_vision_messages` + vision 缓存 + 预算 reserve
- 文件 URL 服务端点（`/api/attachments/<id>/raw`）

**目标**：日志分析能力不卡在 vision provider 选型上，能先交付。

---

## 11. 待定项（实施时确认，不阻塞设计）

1. `LOG_FULL_THRESHOLD` 具体数值——待查 `deepseek-v4-pro` 实际上下文窗口。
2. vision provider 具体型号——用户待定，通过 admin API 热配。
3. 文件 URL 服务方式细节（签名 URL vs 内网端点鉴权）——实施时定。

<!-- 以上为文档正文,以下为审核修复记录 -->

---

## 🔍 Dual Review Log

### Round 1 — 2026-08-05 · 单路两阶段（独立 sub-agent）

| # | 级别 | 阶段 | 标准性质 | 位置 | 问题 | 修复动作 |
|---|------|------|---------|------|------|---------|
| 1 | HIGH | P1 | 事实核查 | §5.1 | stream_answer 行号 456 错（实际 469） | 改为 rag.py:469 |
| 2 | HIGH | P1 | 事实核查 | §5.5 | deepseek.py:84 stream 错（实际 74） | 改为 74，补 generate:47/构造:27/register:19 |
| 3 | HIGH | P1 | 事实核查 | §5.5 | deepseek.py:56 generate 错（实际 47） | 同上合并修复 |
| 4 | MEDIUM | P1 | 事实核查 | §5.4 | _build_messages 行号 251 错（实际 257） | 改为 257 |
| 5 | MEDIUM | P1 | 事实核查 | §5.4 | f-string 行号 282-300 错（实际 288-307） | 改为 288-307（核实：起 288，append 307） |
| 6 | MEDIUM | P2 | 主观意见 | §5.1 | vision `stream` 是 async generator，伪代码 `desc = await ...stream()` 会卡 | 注明需聚合 `"".join([c async for c in ...])` |
| 7 | MEDIUM | P2 | 主观意见 | §5.1 | `await db.commit()` 假设 orchestrator 持有 session，实际未注入 | 注明 session 传递路径需由路由层负责 |
| 8 | LOW | P2 | 机械检测 | §6.1 | #dc2626 未标注为新增色，与"沿用现有配色"矛盾 | 标注为新增色（用于错误态） |
| 9 | LOW | P2 | 主观意见 | §4.4 | widget 匿名 session_id 鉴权弱（可枚举） | 注明为"防误用非防恶意"，签名 token 留待评估 |

**本轮修复**: 9 个（HIGH 3 / MEDIUM 4 / LOW 2） | **累计修复**: 9 个

---

### 汇总

- **收敛轮次**: 1（单轮即清零 CRITICAL/HIGH；修复后无新增问题）
- **累计修复**: 9 个（事实核查 5 / 机械检测 1 / 主观 3）
- **审核模式**: 单路两阶段（独立 sub-agent）
- **Phase 1 事实核查**: ✅ 通过（修复 5 处行号硬错后）
- **Phase 2 质量判断**: ✅ 通过（2 处实施陷阱已注明，鉴权局限已标注）
- **完成时间**: 2026-08-05

### Round 2 — 2026-08-05 · 单路两阶段（修复验证 + 残留深挖）

**修复验证**：Round 1 的 9 处修复全部 grep/read 核实通过（rag.py:469/257/288-307、deepseek.py:74/47/27/19、registry/budget/pii/routes 均准确），无新引入事实错误。✅

| # | 级别 | 阶段 | 标准性质 | 位置 | 问题 | 修复动作 |
|---|------|------|---------|------|------|---------|
| 1 | MEDIUM | P2 | 主观意见 | §4.1 | status 语义未厘清（日志该 processing、截图该 ready） | §4.1 显式标注日志=processing/截图=ready |
| 2 | MEDIUM | P2 | 主观意见 | §5.1 | session 注入路径不够具体（orchestrator 无 session_factory，缓存会丢） | §5.1 列明两个必要改动 + 路由层 commit |
| 3 | LOW | P2 | 主观意见 | §5.3 | BGEEmbedder.embed 同步，在 async 内阻塞事件循环 | 注明需 asyncio.to_thread 包装 |
| 4 | LOW | P2 | 主观意见 | §5.4 | 伪代码结构与真实中文 Markdown 模板不对应 | 注明在 ## 检索到的资料 段后追加子段，保留原模板 |
| 5 | LOW | P2 | 主观意见 | §6.2 | 历史附件回填未声明（刷新丢失） | 注明随前端 state，刷新丢（与现有一致） |
| 6 | LOW | P2 | 主观意见 | §10 | Phase 1a 与图片 accept 张力（1a 无 vision） | 1a accept 暂限 txt/log，1b 开放图片 |

**本轮修复**: 6 个（MEDIUM 2 / LOW 4） | **累计修复**: 15 个

---

### 汇总（收敛）

- **收敛轮次**: 2
- **累计修复**: 15 个（事实核查 5 / 机械检测 1 / 主观 9）
- **审核模式**: 单路两阶段（独立 sub-agent）
- **Phase 1 事实核查**: ✅ 通过（Round 1 修 5 处行号硬错；Round 2 验证全过，无新事实错）
- **Phase 2 质量判断**: ✅ 通过（Round 1 修 2 实施陷阱；Round 2 修 2 实施路径 + 4 边缘提示）
- **残留**: 0 CRITICAL / 0 HIGH / 0 MEDIUM；仅余设计层可接受的待定项（§11）
- **完成时间**: 2026-08-05

**收敛依据**：两轮均无 CRITICAL/HIGH，第二轮新发现全部为"实施路径不够具体"的可补注说明（已修），无逻辑矛盾。文档核心设计（上传/问答解耦、fail-open、vision 缓存、fallback 检索、归属校验、Phase 拆分）逻辑自洽，所有行号事实对齐代码现实。
