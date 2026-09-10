# CamThink Ask AI 网站接入指南（Website Integration Guide）

**目标读者**：负责 `www.camthink.ai`、`wiki.camthink.ai`、`store.camthink.ai` 的前端 / 网站开发人员，以及需要自建 Ask AI UI 的集成方。

**本文档是网站接入的唯一权威指南。** 不需要阅读 Ask AI 源码即可完成官方 Widget 或 Headless 集成。

- 文档版本：**3.0（2026-09-10）**
- 对应生产版本：**ASK-AI v1.3.0**
- 对应生产源码：`8bec1c0251d25630b5e2d461a9a5671cb2841b34`
- 生产 API 基址：`https://wiki-data.camthink.ai`
- v3.0 重点：同步 I-UX-001 新 UX——Entry A/B/C、Contextual Greeting、Trusted Actions、桌面 proactive mini-entry、移动端 nudge、主题/Launcher 配置以及新的接入验收要求。

> **核心结论：基础嵌入方式没有被推翻。** 仍然是 CSS + `widget.js` + `site_id`。
> 但 v1.3.0 后，**Page Context 从“推荐的问答辅助信息”升级为新 UX 的关键集成输入**：它同时影响 contextual greeting、Trusted Actions 是否安全显示以及 action query 的目标绑定。因此产品页、文档页、Store 商品页应按本文档提供结构化 Page Context。

---

# 0. v1.3.0 后集成方需要改变什么

| 项目 | v1.3.0 要求 |
|---|---|
| CSS / JS 嵌入 | **不变**，仍成对加载 `/widget/ask-ai-widget.css` 与 `/widget/widget.js` |
| `site_id` / Origin / CORS | **不变**，仍是站点身份与授权边界 |
| Page Context | **重要性提高**；产品/文档/商品页应提供真实结构化上下文 |
| Entry UX | 由 ASK-AI site config 管理：Legacy / Pill / Nudge / Mini Conversation Entry |
| 新站默认体验 | 新站默认 C：Mini Conversation Entry；既有站点未显式配置时保持 legacy 行为 |
| Desktop | C 模式可按配置延迟自动展开（默认 balanced ≈ 6 秒），同一 site session 只主动展开一次 |
| Mobile | 默认不自动展开完整 mini conversation；采用 B-style contextual nudge |
| Contextual Greeting | ASK-AI 根据可信 Page Context 确定性生成；**不会新增 LLM 调用** |
| Trusted Actions | 由 ASK-AI Admin 管理并经过 DRAFT → TEST → VERIFIED → PUBLISHED；访客只看到可公开动作 |
| 引用 | 官方 Widget 默认使用**答案内 inline citations**；不要求宿主再渲染重复 Sources 区 |
| 外观 | Launcher / Chat theme 主要由 ASK-AI Admin 管理；embed override 仅用于高级集成/特殊场景 |

宿主网站不应该自己复制 ASK-AI 的 contextual greeting、Trusted Actions 生命周期或 proactive state machine。**这些属于 Widget 产品行为；宿主负责提供正确上下文。**

---

# Part 1 — Official Widget Integration

## 1.1 生产接入架构

```text
访客浏览器
  ├─ GET https://wiki-data.camthink.ai/widget/ask-ai-widget.css
  ├─ GET https://wiki-data.camthink.ai/widget/widget.js
  ├─ GET /api/widget/site-config?site_id=...
  │      └─ Entry / proactive / launcher / chat theme / greeting override / Trusted Actions
  └─ POST /api/ask
         └─ ASK-AI: authorization → intent → retrieval → evidence → generation → citations → conversation
```

官方 Widget 是自包含浮层，不要求宿主实现聊天 UI。ASK-AI v1.3.0 的 contextual entry、mini conversation、mobile nudge、Trusted Actions 和 inline citations 均由 Widget 自己完成。

## 1.2 三站身份

| 站点 | `site_id` | 授权 Origin | 默认语言 |
|---|---|---|---|
| Website | `camthink-website` | `https://www.camthink.ai`、`https://camthink.ai` | en |
| Wiki | `camthink-wiki` | `https://wiki.camthink.ai` | en |
| Store | `camthink-store` | `https://store.camthink.ai` | en |

规则：

- `site_id` 必须逐字符一致；不要按语言拆分 site_id。
- `site_id` **不是凭证**。服务端同时检查 site 是否启用以及浏览器 Origin 是否属于该 site。
- 浏览器还受生产 `CORS_ALLOW_ORIGINS` 约束。一个 Origin 必须同时通过 site authorization 与 CORS。
- 新增域名 / 子域名 / 非标准端口时，先让 ASK-AI 运维侧加入授权，不要通过前端绕过。

## 1.3 推荐嵌入代码

### Website

```html
<link rel="stylesheet" href="https://wiki-data.camthink.ai/widget/ask-ai-widget.css">
<script
  src="https://wiki-data.camthink.ai/widget/widget.js"
  data-api-url="https://wiki-data.camthink.ai"
  data-site-id="camthink-website"
  async
></script>
```

### Wiki

```html
<link rel="stylesheet" href="https://wiki-data.camthink.ai/widget/ask-ai-widget.css">
<script
  src="https://wiki-data.camthink.ai/widget/widget.js"
  data-api-url="https://wiki-data.camthink.ai"
  data-site-id="camthink-wiki"
  async
></script>
```

### Store

```html
<link rel="stylesheet" href="https://wiki-data.camthink.ai/widget/ask-ai-widget.css">
<script
  src="https://wiki-data.camthink.ai/widget/widget.js"
  data-api-url="https://wiki-data.camthink.ai"
  data-site-id="camthink-store"
  async
></script>
```

CSS 与 JS **必须成对引入**。Widget 不会自动注入 stylesheet。

兼容方式仍支持：

```html
<link rel="stylesheet" href="https://wiki-data.camthink.ai/widget/ask-ai-widget.css">
<script>
window.AskAIConfig = {
  apiUrl: "https://wiki-data.camthink.ai",
  siteId: "camthink-website"
};
</script>
<script src="https://wiki-data.camthink.ai/widget/widget.js" async></script>
```

同一个配置键不要同时放在 `data-*` 和 `window.AskAIConfig` 中；逐键优先级为：

```text
<script data-*>
  > #ask-ai-widget-root data-*
  > window.AskAIConfig
  > Widget built-in fallback
```

## 1.4 Page Context — v1.3.0 的关键集成输入

Page Context 仍然不是事实证据；答案事实必须来自 ASK-AI 检索证据。但 v1.3.0 开始，它还驱动：

```text
Page Context
  ├─ query/reference understanding
  ├─ contextual greeting
  ├─ Trusted Action applicability
  └─ Trusted Action target binding
```

因此：**错误的 specific context 比不传 context 更危险。** 不确定时宁可省略字段，让 Widget fail closed 到通用 greeting / 无 contextual action。

### 字段

| 字段 | 来源 | 说明 |
|---|---|---|
| `url` | Widget 自动采集 | 当前 URL；宿主无需传 |
| `title` | Widget 自动采集 | `document.title` |
| `language` | Widget 自动采集/解析 | 页面/浏览器语言语境 |
| `page_type` | 宿主 | 建议：`home` / `product` / `documentation` / `article` / `category` / `checkout` |
| `product` | 宿主 | 产品名，例如 `NE503` |
| `product_id` | 宿主 | 稳定产品 ID |
| `sku` | 宿主 | Store SKU / variant SKU |
| `section` | 宿主 | 文档/站点栏目，例如 `firmware`、`quickstart`、`troubleshooting` |

### Website 产品页

```html
<script>
window.AskAIConfig = window.AskAIConfig || {};
window.AskAIConfig.pageContext = {
  page_type: "product",
  product: "NE503",
  product_id: "ne503"
};
</script>
```

### Wiki 文档页

```html
<script>
window.AskAIConfig = window.AskAIConfig || {};
window.AskAIConfig.pageContext = {
  page_type: "documentation",
  product: "NE503",       // 仅当该文档确实属于 NE503 时传
  section: "quickstart"
};
</script>
```

### Store 商品页

```html
<script>
window.AskAIConfig = window.AskAIConfig || {};
window.AskAIConfig.pageContext = {
  page_type: "product",
  product: "NE503",
  product_id: "ne503",
  sku: "CT-NE503-001"
};
</script>
```

Store 首页/分类页不要遗留上一商品的 `product` / `sku`。SPA 切页或商品 variant 切换时必须更新上下文。

## 1.5 SPA 集成

Widget 只挂载一次。不要在每次 route change 重新注入 `widget.js`。

```jsx
useEffect(() => {
  window.AskAIConfig = window.AskAIConfig || {};
  window.AskAIConfig.pageContext = matchRoute(location.pathname);
}, [location.pathname]);
```

`pageContext` 在发送/交互时读取；SPA route change 后更新对象即可。新页面上下文不会要求重新加载 Widget，也不会因为路由变化反复触发 proactive expansion。

如果新 route 无可信产品上下文，应显式清掉旧值：

```js
window.AskAIConfig.pageContext = { page_type: "category" };
// 或
window.AskAIConfig.pageContext = undefined;
```

不要让上一页 `product` / `sku` 泄漏到下一页。

---

# Part 2 — v1.3.0 Widget Experience

## 2.1 Entry Modes

ASK-AI 当前支持以下 entry semantics：

| 语义 | 配置值 | 访客表现 |
|---|---|---|
| Legacy | `legacy` | 既有 Widget 行为；用于兼容未迁移旧站 |
| A — Minimal Pill | `pill` | 紧凑 `Ask AI` 入口 |
| B — Contextual Nudge | `nudge` | 页面感知的短提示入口 |
| C — Mini Conversation Entry | `mini_entry` | contextual greeting + 最多 2 个 Trusted Actions + 直接输入 |

**新站默认 C；既有站点如果没有显式 entry config，则保持 legacy。** 网站集成方不要为了获得 C 模式而在页面代码里硬编码；正常运营配置应在 ASK-AI Admin 中完成。

## 2.2 Desktop / Mobile 行为

Desktop C：

```text
compact launcher
  → configured delay
  → contextual mini-entry
  → action / direct input
  → same anchored surface expands to floating chat
  → real ASK-AI streaming answer
```

默认 proactive timing 为 balanced（约 6 秒）。主动展开按 site session 抑制重复触发；用户 minimize / dismiss 后，本 session 不再反复打扰。

Mobile 默认采取更保守策略：不自动展开完整 mini conversation，而显示 B-style contextual nudge；访客显式点击后进入聊天。

宿主不需要实现这套状态机，只需要保证：

- 标准 viewport meta；
- 不删除 `#ask-ai-widget-root`；
- 不用宿主 CSS 强行改 Widget 内部布局；
- 页面自己的 overlay 与 Widget 层级冲突时，在宿主侧协调。

## 2.3 Contextual Greeting

Greeting 由 ASK-AI 确定性解析，不增加新的 LLM 调用。语义优先级由 ASK-AI 管理，核心原则是：

```text
explicit site/admin override
  > trusted structured Page Context
  > safe page-type fallback
  > generic greeting
```

宿主不应自行生成 greeting，也不要把未经验证的页面自由文本伪装成 `product`。

## 2.4 Trusted Actions

Trusted Actions 是经过治理的一键 intent，不是普通“推荐问题字符串”。ASK-AI Admin 生命周期：

```text
DRAFT → TEST → VERIFIED → PUBLISHED
```

只有符合公开条件的动作会进入 visitor site-config / Widget。动作包含稳定 semantic type、展示 label 和可绑定 query。

当前 semantic catalog 包括：

- `PRODUCT_SPECIFICATIONS`
- `SETUP_GUIDE`
- `EXPLAIN_PAGE`
- `TROUBLESHOOT`
- `FIND_DOCUMENTATION`
- `COMPARE_PRODUCTS`
- `COMPATIBILITY`
- `PRICING`

是否显示取决于动作发布状态和上下文是否足够绑定。缺少需要的 product/context 时应 fail closed，不显示无法安全绑定的 action。

**宿主网站不需要也不应该复制 Trusted Action 的 TEST / VERIFY / PUBLISH 逻辑。**

## 2.5 Inline Citations

官方 Widget 的 v1.3.0 visitor answer UX：

- 引用直接显示在答案相应位置；
- citation 可点击、可追溯；
- 默认不再为了同一批来源额外显示重复的 `Sources` 卡片区；
- ASK-AI Admin / Debug / Evaluation 或明确需要完整 source inventory 的场景可以查看更完整证据。

宿主不应通过 CSS/DOM 操作重新拼装官方 Widget 的 Sources 区。

## 2.6 外观配置与 Embed Override

常规站点应优先在 ASK-AI Admin 配置体验。Widget 仍提供 embed-level override，优先级高于 site-config，适合高级集成、预览或特殊站点约束。

| data-* | `AskAIConfig` | 值 |
|---|---|---|
| `data-entry-mode` | `entryMode` | `legacy` / `pill` / `nudge` / `mini_entry` |
| `data-proactive` | `proactive` | `off` / `fast` / `balanced` / `gentle` |
| `data-launcher-motion` | `launcherMotion` | `static` / `subtle_glow` / `soft_pulse` / `sparkle` |
| `data-launcher-size` | `launcherSize` | `small` / `medium` / `large` |
| `data-launcher-brand` | `launcherBrand` | `askai` / `match` / `custom` |
| `data-launcher-color` | `launcherColor` | `#RRGGBB`（custom） |
| `data-chat-theme` | `chatTheme` | `match` / `light` / `dark` / `custom` |
| `data-chat-accent` | `chatAccent` | `#RRGGBB`（custom） |
| `data-chat-size` | `chatSize` | `default` / `large` |
| `data-launcher-icon` | `launcherIcon` | 当前支持的 launcher icon semantic id |
| `data-launcher-shape` | `launcherShape` | `round` / `rounded-square` |
| `data-launcher-theme` | `launcherTheme` | `auto` / `light` / `dark` |

示例（仅当确实需要宿主 override）：

```html
<script
  src="https://wiki-data.camthink.ai/widget/widget.js"
  data-api-url="https://wiki-data.camthink.ai"
  data-site-id="camthink-website"
  data-entry-mode="mini_entry"
  data-proactive="balanced"
  data-launcher-motion="subtle_glow"
  data-launcher-size="medium"
  data-chat-theme="match"
  async
></script>
```

**推荐：不要把这些值散落硬编码在 Website/Wiki/Store 代码中。** 如果运营人员需要改变体验，应从 ASK-AI Admin 修改 site-level configuration；否则站点发布与 Widget 运营配置会形成双重 Source of Truth。

---

# Part 3 — Multilingual Integration

- 三个 site 默认语言均为 English，但支持 English / 中文。
- `site_id` 是站点身份，`language` 是当前页面语言；不要拆成六个 site。
- 可显式传 `data-language="en"` / `"zh"`。
- 同时保持 `<html lang>` 与实际页面语言一致。
- ASK-AI 的语言解析链会结合显式 host language、页面语言与浏览器 fallback。

示例：

```html
<script
  src="https://wiki-data.camthink.ai/widget/widget.js"
  data-api-url="https://wiki-data.camthink.ai"
  data-site-id="camthink-website"
  data-language="zh"
  async
></script>
```

SPA 如果语言切换不刷新页面，应确保页面的语言状态 / `<html lang>` 同步更新；不要让旧语言与新页面语义长期不一致。

---

# Part 4 — Headless / Custom UI Integration

## 4.1 定位

ASK-AI Core 仍是 headless 的。自建 UI 可以直接消费服务端 API，但不会绕过 retrieval / evidence / citations / conversation pipeline。

主要 API：

| Endpoint | Method | 用途 |
|---|---|---|
| `/api/widget/site-config?site_id=...` | GET | 获取 site experience；v1.3.0 包含新的 entry/theme/greeting/Trusted Actions 字段 |
| `/api/ask` | POST | SSE 问答 |
| `/api/upload` | POST | 附件上传 |
| `/api/feedback` | POST | answer feedback |

`channel` 对公共访客仍使用 `"widget"`。

## 4.2 site-config v1.3.0

自建 UI 如果希望复现官方 Widget 的产品体验，需要认识这些新增字段：

```jsonc
{
  "site_id": "...",
  "welcome": "...",
  "language": "en",
  "starters": [],
  "launcher_icon": "...",
  "launcher_shape": "...",
  "launcher_theme": "...",

  "entry_mode": "mini_entry",
  "proactive_timing": "balanced",
  "launcher_motion": "subtle_glow",
  "launcher_size": "medium",
  "launcher_brand": "askai",
  "launcher_color": null,
  "chat_theme": "match",
  "chat_accent_color": null,
  "chat_size": "default",
  "greeting_override": null,
  "trusted_actions": [
    { "type": "PRODUCT_SPECIFICATIONS", "label": "Specifications", "query": "..." }
  ]
}
```

字段可能因站点处于 legacy / 未配置状态而为空或缺省。**不要把 null 自动解释成新默认并覆盖旧站行为。**

Headless 实现如果不需要复制官方 Entry UX，可以忽略这些 presentation fields，继续只使用 `/api/ask`。如果要声称与官方 Widget UX 等价，则必须自行实现相同的 lifecycle、fail-closed、mobile behavior、accessibility 与 context binding；否则应明确称为 Custom UI，而不是 ASK-AI Official Widget 等价实现。

## 4.3 `/api/ask` 最小请求

```jsonc
{
  "message": "Does it support PoE?",
  "channel": "widget",
  "site_id": "camthink-website",
  "page_context": {
    "page_type": "product",
    "product": "NE503"
  },
  "language": "en",
  "conversation_history": []
}
```

响应仍为 SSE，核心事件：

```text
sources → token* → (error | declined)? → done
```

答案文本中的 `[N]` 对应 `sources[N-1]`。Custom UI 应将有效引用渲染成可点击 inline citation；无对应 source 的 citation marker 不应裸露给用户。不要默认再重复渲染整块 Sources 列表，除非你的产品明确需要完整 source inventory。

---

# Part 5 — v1.3.0 上线验收 Checklist

每个真实站点至少验证：

```text
[ ] CSS + widget.js 均成功加载
[ ] site-config = 200，site_id 正确
[ ] /api/ask = 200，无 CORS / Origin 授权错误
[ ] Desktop launcher / entry 正常，无宿主布局 reflow
[ ] Mobile viewport 下布局正常；proactive UX 不强制展开完整 mini conversation
[ ] 产品页/文档页/商品页 page_context 与当前页面一致
[ ] SPA route change 后旧 product / sku 不泄漏
[ ] Contextual greeting 不出现错误产品专名
[ ] Trusted Action 仅在上下文足够时出现
[ ] 点击 Trusted Action 只触发一次真实 ask，并绑定到当前对象
[ ] 无上下文时安全回退：generic greeting / 无错误 specific action
[ ] answer 正常 streaming
[ ] inline citations 可点击且来源正确
[ ] 官方 Widget 默认无重复 Sources section
[ ] dismiss / minimize 后当前 session 不反复主动弹出
[ ] Console 无新增 error；Network 无意外 4xx/5xx
[ ] 中文/英文页面语言与回答/UI 表现一致
```

建议产品页 smoke：

```text
Website / Store NE503 page
  page_context.product = NE503
  → greeting 应正确绑定 NE503（如站点配置启用 contextual entry）
  → Specifications action（如已 PUBLISHED）应绑定 NE503
  → 点击后真实 answer + inline citations
```

Wiki 文档页 smoke：

```text
page_type = documentation
section = 当前真实栏目
  → greeting/action 不伪造不存在的 product
  → Explain / Troubleshoot 类 action（如已 PUBLISHED）正常进入 ASK-AI
```

---

# Part 6 — Troubleshooting

| 症状 | 优先检查 |
|---|---|
| Widget 不出现 | `widget.js` / CSS 是否 200；CSP；脚本是否被拦截 |
| 无样式 / 布局错乱 | 是否漏掉 `ask-ai-widget.css` |
| API 指向 localhost | `data-api-url` / `AskAIConfig.apiUrl` 未设置；生产必须是 `https://wiki-data.camthink.ai` |
| 403 | `site_id`、Origin、site enabled、allowed_origins |
| CORS error | 生产 `CORS_ALLOW_ORIGINS` 是否包含当前精确 Origin |
| 出现错误产品 greeting | 检查 `pageContext.product/product_id/sku` 是否来自上一页或硬编码 |
| SPA 切页后仍问上一产品 | route change 时没有更新/清空 `window.AskAIConfig.pageContext` |
| Trusted Action 不显示 | action 是否 PUBLISHED；当前 context 是否足够绑定；不要在宿主侧强行显示 |
| Desktop 不 proactive | site entry/proactive config、session 是否已 dismiss/expand 过、是否 legacy site |
| Mobile 没出现完整 C mini | **通常是预期行为**；移动端默认 B-style nudge |
| 重复 Sources | 宿主/Custom UI 仍额外渲染 sources list；官方 v1.3.0 visitor UX 默认 inline-only |
| 主题不匹配 | 优先检查 ASK-AI Admin site config；其次才检查 embed override / 页面 theme signals |
| Headless 出现裸 `[1]` | Custom UI 未实现 sources → inline citation 映射 |

反馈问题时提供：页面 URL、Origin、site_id、Page Context、浏览器/设备、Console、`site-config` 与 `/api/ask` Network evidence、截图/录屏。

---

# Part 7 — 职责边界

## 网站 / 集成方负责

- 正确加载 CSS + JS，或正确实现 Headless API client；
- 传正确 `apiUrl`、`site_id`、页面语言；
- 在产品/文档/商品页提供真实 Page Context；
- SPA route change 时更新并清理上下文；
- 保证 viewport、宿主 overlay、CSP 等不会破坏 Widget；
- 不复制/绕过 ASK-AI 的 site authorization、Trusted Action lifecycle；
- 在真实授权域名完成 Part 5 验收。

## ASK-AI 负责

- site authorization / CORS 生产配置；
- site experience / Entry A-B-C / proactive 配置；
- contextual greeting 解析；
- Trusted Actions 的 TEST / VERIFY / PUBLISH 与 visitor exposure；
- launcher / chat theme 产品配置；
- retrieval / evidence / generation / citations / conversation；
- Admin / Debug / Evaluation 的完整 evidence visibility；
- Widget release 与生产运行时。

---

# 快速对照卡

**最小官方 Widget：**

```html
<link rel="stylesheet" href="https://wiki-data.camthink.ai/widget/ask-ai-widget.css">
<script src="https://wiki-data.camthink.ai/widget/widget.js"
        data-api-url="https://wiki-data.camthink.ai"
        data-site-id="camthink-website"
        data-language="en"
        async></script>
```

**产品页上下文：**

```html
<script>
window.AskAIConfig = window.AskAIConfig || {};
window.AskAIConfig.pageContext = {
  page_type: "product",
  product: "NE503",
  product_id: "ne503"
};
</script>
```

**原则：**

```text
Embed once.
Identify the site correctly.
Provide truthful page context.
Let ASK-AI own the experience.
Fail generic rather than wrong-specific.
```

---

## Change Log

### v3.0 — 2026-09-10

- 对齐 ASK-AI production `v1.3.0 / 8bec1c0`。
- 将生产 API 地址从历史占位符更新为 `https://wiki-data.camthink.ai`。
- 加入 I-UX-001 Entry A/B/C 与 legacy migration 语义。
- 明确 desktop C proactive / mobile B-nudge 行为。
- 将 Page Context 提升为 contextual greeting + Trusted Action binding 的关键接入输入。
- 加入 Trusted Actions lifecycle 与 fail-closed 接入边界。
- 加入 launcher/chat experience override 契约，并明确 Admin site-config 为常规 Source of Truth。
- 更新 Headless `site-config` 字段与 inline-citation UX。
- 更新 production acceptance checklist 与 troubleshooting。

### v2.0 — 2026-09-02

- 从 Widget-only 指南升级为 Website Integration Guide。
- 加入 Headless 与 Multilingual integration。
