# CamThink Ask AI 网站接入指南(Website Integration Guide)

**目标读者**:负责 `www.camthink.ai`(官网)、`wiki.camthink.ai`(Wiki)、`store.camthink.ai`(Store)的前端 / 网站开发人员。

**本文档的目标**:你**不需要阅读 Ask AI 任何源码**,只看这一份文档即可完成接入——无论使用官方聊天组件,还是自建界面。

- 文档版本:2.0(2026-09-02,由 CAMTHINK_WIDGET_INTEGRATION.md v1.0 升级重命名而来,本文是唯一权威接入指南)
- 依据的 Ask AI 版本:CAMTHINK V1 RC(`release/camthink-v1-rc-2026-09-01` 线,基线 `1ff2936`,含 2026-09-02 契约追加)
- 所有配置键、端点、事件、行为均直接取自真实实现,并经其自带测试套件验证(widget 57/57;站点授权 16/16)。

**本文档覆盖三种集成需求**:

| 你的场景 | 阅读部分 |
|---------|---------|
| 使用官方 Ask AI 聊天浮窗 | Part 1 — Official Widget Integration |
| 自建聊天 UI,调用 Ask AI 完整能力 | Part 2 — Headless / Custom UI Integration |
| 站点有 English / 中文双语 | Part 3 — Multilingual Integration(与上两者叠加) |

---

## 0. 接入前必读:生产 URL 状态

> **PRODUCTION_WIDGET_URL_READY = NO(截至 2026-09-02)**
>
> Ask AI 后端的公网接入地址(DNS + 反向代理)**尚未建立**,因此本文示例中的
> `https://<ASK-AI-PRODUCTION-API-BASE>` 是一个**待替换占位符**,不是已生效的地址。
>
> 在 Ask AI 团队正式提供生产 API 基址之前,你可以先把接入代码合入站点
> (官方 Widget 的浮动按钮可以正常渲染),但**问答功能要到生产地址就绪后才会通**。
> 请勿自行猜测或编造该地址。该状态对 Part 1 与 Part 2 同样适用。

**需要由 Ask AI 团队提供**(网站负责人无需操作,此处仅说明依赖):

| # | 待提供项 | 说明 |
|---|---------|------|
| B1 | 生产 API 基址 | 一个公网可达的 **https** 域名(最终以 Ask AI 团队正式通知为准),需同时路由 `/widget/*`(官方 Widget 静态脚本)与 `/api/*`(问答接口) |
| B2 | CORS 白名单激活 | 生产环境 `CORS_ALLOW_ORIGINS` 需包含三个站点来源(见 §1.4),否则浏览器会拦截所有请求 |
| B3 | 站点配置确认 | 三个 `site_id` 已在生产数据库启用,且来源白名单与 §1.2 一致 |

---

# Part 1 — Official Widget Integration

## 1.1 你将接入什么

Ask AI 官方 Widget 是一个自包含的嵌入式聊天组件:接入后,页面右下角出现一个
CamThink Logo 浮动按钮,点击展开对话面板。访客提问后,Widget 以流式方式返回
答案并附带可点击的引用来源。

```
访客浏览器(你的站点)
 ├─ 加载  {API基址}/widget/ask-ai-widget.css   (样式)
 ├─ 加载  {API基址}/widget/widget.js           (脚本,自动挂载浮动按钮)
 ├─ 启动时 GET {API基址}/api/widget/site-config?site_id=...   (读取本站欢迎语/推荐问题;失败自动回退,不阻塞)
 └─ 提问时 POST {API基址}/api/ask              (SSE 流式问答)
        └─ Ask AI 后端负责:站点鉴权 / 意图 / 检索 / 知识信任边界 / 生成 / 引用 / 会话记录(全部与你的站点无关)
```

官方 Widget 本质上就是 Part 2 所述 API 的一个**参考实现客户端**——你在 Part 1
做的事情,Part 2 的自建 UI 同样要做。

## 1.2 三站身份(冻结值,直接使用)

| 站点 | `site_id` | 授权来源(Origin) | 站点默认语言 |
|------|-----------|-------------------|-------------|
| 官网 Website | `camthink-website` | `https://www.camthink.ai` 以及 `https://camthink.ai` | en |
| Wiki | `camthink-wiki` | `https://wiki.camthink.ai` | en |
| Store | `camthink-store` | `https://store.camthink.ai` | en |

- `site_id` **必须逐字符照抄**(小写、连字符)。传错 `site_id` 或在未授权来源下
  运行,问答会得到 403"站点未授权"。
- **三个站点始终只有这三个 `site_id`**。站点支持 English / 中文切换**不**产生
  新的 site_id(语言维度见 Part 3,绝不要按语言拆分站点标识)。
- **Website 注意**:Ask AI 侧服务端授权已同时包含 www 与非 www 两个来源,但生产
  CORS 白名单模板当前只列了 `https://www.camthink.ai`。因此官网接入请**统一使用
  `https://www.camthink.ai` 域名**(建议在站点边缘把非 www 301 到 www),或要求
  Ask AI 团队把 `https://camthink.ai` 追加进 CORS 白名单。

## 1.3 快速接入(推荐路径)

### 两行标签(data-* 配置,推荐)

在站点**全站公共模板**的 `</body>` 前加入(以官网为例):

```html
<!-- Ask AI Widget:CSS 与 JS 必须成对引入,缺一不可 -->
<link rel="stylesheet" href="https://<ASK-AI-PRODUCTION-API-BASE>/widget/ask-ai-widget.css">
<script
  src="https://<ASK-AI-PRODUCTION-API-BASE>/widget/widget.js"
  data-api-url="https://<ASK-AI-PRODUCTION-API-BASE>"
  data-site-id="camthink-website"
  async
></script>
```

**必须成对引入的原因**:构建产物是两个文件,脚本**不会**自动注入样式。只放
`<script>` 不放 `<link>`,按钮和面板会以无样式状态渲染(错位、透明、不可用)。

### 兼容路径(window.AskAIConfig)

如果发布流程不便修改 script 标签属性,可以改用全局配置对象。
**该对象必须在 widget.js 之前定义**:

```html
<link rel="stylesheet" href="https://<ASK-AI-PRODUCTION-API-BASE>/widget/ask-ai-widget.css">
<script>
  window.AskAIConfig = {
    apiUrl: "https://<ASK-AI-PRODUCTION-API-BASE>",
    siteId: "camthink-website"
  };
</script>
<script src="https://<ASK-AI-PRODUCTION-API-BASE>/widget/widget.js" async></script>
```

两条路径**不要混用**同一个键(混用时 `data-*` 优先,容易造成排查困惑)。

### 完整配置键参考

| 键 | data-* 写法 | AskAIConfig 写法 | 必填 | 说明 |
|----|-------------|------------------|------|------|
| API 地址 | `data-api-url` | `apiUrl` | **是**(生产) | Ask AI API 基址,不带尾部 `/`。缺省值为 `http://localhost:8000`(仅本地开发有意义) |
| 站点标识 | `data-site-id` | `siteId` | **是**(三站接入) | 见 §1.2。缺省 = 旧版公共 Widget(不发送站点字段,三站接入**禁止**缺省) |
| 页面语言 | `data-language` | `language` | 见 Part 3 | 当前页面语言,如 `"en"` / `"zh"`。多语言站点按语言版本模板传值(语义与现状见 Part 3) |
| 主题色 | `data-primary-color` | `primaryColor` | 否 | CSS 颜色值,缺省 `#f24a00`(CamThink 品牌橙)。三站接入建议**保持缺省** |

配置解析顺序(逐键独立回退,已由测试锚定):

```
1. <script> 标签 data-*(最高)
2. 页面预置 <div id="ask-ai-widget-root" data-*> 的 data-*
3. window.AskAIConfig
4. 内置默认值
```

**读取时机**:`apiUrl` / `siteId` / `language` / `primaryColor` 在脚本加载时读取
一次;而 `window.AskAIConfig.pageContext`(下节)**每次发送时实时读取**。

## 1.4 授权模型:site_id、Origin 与 CORS

### site_id 不是凭证

`site_id` 只是站点标识,**不提供任何授权**。一个请求要被 Ask AI 接受,必须同时满足:

1. `site_id` 对应的站点**存在且已启用**;
2. 请求的 **Origin 精确命中**该站点的授权来源列表(§1.2)。

校验发生在 Ask AI **服务端**(`site-config` 与 `ask` 两个端点都查)。任一条件不满足
→ 统一返回 403(不区分具体原因,防枚举)。

### 两层配置:服务端授权 + 浏览器 CORS

| 层 | 配置 | 作用 | 三站清单(生产) |
|----|------|------|-----------------|
| 服务端站点授权 | 每站点 `allowed_origins`(§1.2) | 决定 403 与否 | website: www + 非 www;wiki;store |
| 浏览器 CORS | 环境变量 `CORS_ALLOW_ORIGINS` | 决定浏览器是否放行请求 | 生产模板:`https://www.camthink.ai, https://wiki.camthink.ai, https://store.camthink.ai` |

**推论**(排障时关键):

- 一个来源必须**同时**出现在两层,Widget 才能工作。
- Origin 匹配规则:`协议://主机[:端口]` 全小写精确匹配;80/443 默认端口可省略
  也可显式写(归一化后等价);**不支持通配符**;scheme 必须完全一致。
- `www` / 非 `www` 是两个不同的 Origin,需分别配置。
- **localhost 默认不在生产授权内**:本地静态预览能渲染出 Widget 外观,但所有
  API 请求都会失败。完整验收必须在真实授权域名下进行。
- 新增嵌入来源属于 Ask AI 侧配置变更:需提前申请,提供准确 scheme+host(+非标端口)。

## 1.5 Page Context:告诉 Ask AI "用户正在看什么"

### 它是什么、不是什么

Page Context 是随每次提问自动附带的一段**页面描述**,用于帮助 Ask AI 理解指代:

> 例:访客在 NE503 产品页问 "Does it support PoE?" —— Page Context 让 Ask AI
> 知道 `it` 大概率指 NE503。

**边界(重要)**:

- Page Context 是**非信任的语义提示**:Ask AI 只用它做指代解析与检索**软加权**
  (软加分,绝不过滤候选),不会把其中的内容当作事实依据。
- **它不是知识证据**。产品规格、技术参数、价格等答案内容,永远来自 Ask AI
  知识库检索与引用。
- 宿主**不需要为 Page Context 的内容正确性负责**——如实传递即可。

### 字段契约:自动采集 vs 宿主提供

| 字段 | 谁提供 | 来源 | 说明 |
|------|--------|------|------|
| `url` | **自动** | 当前页面地址 | 每次发送时实时采集,**宿主提供的同名值会被忽略** |
| `title` | **自动** | `document.title` | 同上 |
| `language` | **自动** | 浏览器语言(navigator.language) | 同上 |
| `page_type` | 宿主可选 | `window.AskAIConfig.pageContext` | 页面类型,建议值:`home` / `product` / `documentation` / `article` / `category` / `checkout`(自由文本,≤50 字符) |
| `product` | 宿主可选 | 同上 | 产品名,如 `"NE503"`(≤100 字符) |
| `product_id` | 宿主可选 | 同上 | 产品 ID(≤100 字符) |
| `sku` | 宿主可选 | 同上 | SKU 编码(≤100 字符) |
| `section` | 宿主可选 | 同上 | 栏目/分区,如 `"support"`、`"firmware"`(≤200 字符) |

规则(均来自真实实现):

- 宿主结构化字段通过 `window.AskAIConfig.pageContext` 提供,**每次发送时实时读取**
  ——SPA 路由切换时更新它即可,无需重新加载 widget。
- 自动采集的 `url` / `title` / `language` **不可被宿主覆盖**(防伪造设计)。
- **不知道的字段就不要传**。未知字段会被 Ask AI 后端直接丢弃。
- `url` 仅接受 http/https 形态;超长字段会被截断/拒绝,不影响提问本身。

### 提供方式示例(以产品页为例)

```html
<script>
  // 在 widget.js 之前或之后均可;widget 每次发送时实时读取
  window.AskAIConfig = window.AskAIConfig || {};
  window.AskAIConfig.pageContext = {
    page_type: "product",
    product: "NE503"
  };
</script>
```

## 1.6 三站接入示例

以下示例均为 production-style、可直接复制(替换唯一占位符
`<ASK-AI-PRODUCTION-API-BASE>`,见 §0)。

### A. 官网 Website(`camthink-website`)

**全站公共模板**(普通页面,如首页/关于我们):

```html
<!-- Ask AI Widget -->
<link rel="stylesheet" href="https://<ASK-AI-PRODUCTION-API-BASE>/widget/ask-ai-widget.css">
<script
  src="https://<ASK-AI-PRODUCTION-API-BASE>/widget/widget.js"
  data-api-url="https://<ASK-AI-PRODUCTION-API-BASE>"
  data-site-id="camthink-website"
  async
></script>
```

**产品详情页模板**(在公共接入之上追加 Page Context):

```html
<script>
  window.AskAIConfig = window.AskAIConfig || {};
  // 模板引擎按当前产品渲染;示例值以 NE503 页为例
  window.AskAIConfig.pageContext = {
    page_type: "product",
    product: "NE503"
  };
</script>
```

在首页等非产品页**不要**设置 `product`(保持 pageContext 未定义或只给 `page_type`)。

### B. Wiki(`camthink-wiki`)

```html
<!-- Ask AI Widget -->
<link rel="stylesheet" href="https://<ASK-AI-PRODUCTION-API-BASE>/widget/ask-ai-widget.css">
<script
  src="https://<ASK-AI-PRODUCTION-API-BASE>/widget/widget.js"
  data-api-url="https://<ASK-AI-PRODUCTION-API-BASE>"
  data-site-id="camthink-wiki"
  async
></script>
```

**文档页 Page Context**:

```html
<script>
  window.AskAIConfig = window.AskAIConfig || {};
  window.AskAIConfig.pageContext = {
    page_type: "documentation",
    section: "quickstart"   // 按文档栏目填,如 quickstart / firmware / api / troubleshooting
  };
</script>
```

### C. Store(`camthink-store`)

```html
<!-- Ask AI Widget -->
<link rel="stylesheet" href="https://<ASK-AI-PRODUCTION-API-BASE>/widget/ask-ai-widget.css">
<script
  src="https://<ASK-AI-PRODUCTION-API-BASE>/widget/widget.js"
  data-api-url="https://<ASK-AI-PRODUCTION-API-BASE>"
  data-site-id="camthink-store"
  async
></script>
```

**商品详情页 Page Context**(把 SKU 传给 Ask AI,购买决策类问题受益最大):

```html
<script>
  window.AskAIConfig = window.AskAIConfig || {};
  window.AskAIConfig.pageContext = {
    page_type: "product",
    product: "NE503",
    product_id: "ne503",     // 用商店真实 product id 渲染
    sku: "CT-NE503-001"      // 用商店真实 SKU 渲染;多变体页可在变体切换时更新
  };
</script>
```

> Store 首页/分类页:只给 `page_type: "category"`(或不给 pageContext),**不要**
> 把某个商品的 SKU 泄漏到全站。

## 1.7 框架指引

### 静态 HTML / 传统多页站(如服务端模板渲染)

按 §1.3/§1.6 把两行标签放进全站公共 footer 模板即可。每次整页跳转都会重新挂载
Widget,这是预期行为(访客会话通过浏览器 localStorage 延续,对话不会因翻页丢失)。

### React / SPA 类站点

1. **只挂载一次**:把 §1.3 的两行标签放进 SPA 的入口 HTML(`index.html`),
   **不要**在组件里动态插入 script、也不要在路由切换时重复注入。
   (Widget 自带防重复挂载保护:同一页面重复执行脚本会自动跳过,但请不要依赖它。)
2. **路由切换时更新 Page Context**:Widget 在**每次发送**时实时读取
   `window.AskAIConfig.pageContext` 与当前 `location`/`title`,在路由变化钩子里
   更新全局对象即可:

```jsx
// React Router v6 示例
useEffect(() => {
  window.AskAIConfig = window.AskAIConfig || {};
  window.AskAIConfig.pageContext = matchRoute(location.pathname);
}, [location.pathname]);
```

3. Widget 浮窗是独立的 fixed 定位 DOM(挂在 `#ask-ai-widget-root` 下),SPA 重渲染
   不影响它。

### Wiki / Store 实际技术栈说明

Ask AI 仓库内**没有**能证明 `wiki.camthink.ai` / `store.camthink.ai` 技术栈的
工程证据,因此不对其栈做任何假设——上述示例均为 framework-neutral(原生 HTML
标签),在任何能改公共模板/页脚的栈里都适用:

- WordPress / WooCommerce 类:放进主题 footer(`wp_footer` 或子主题模板);
  Page Context 片段放进对应页面模板(如 `single-product.php`),用模板函数输出
  真实商品字段。
- 静态站点生成器(Hugo/Docusaurus 等):放进全站布局模板,Page Context 用各自的
  前置参数/组件系统注入。

### 移动端与桌面端

- Widget 自带响应式样式(≤640px 视口自动切换为移动端布局),宿主只需保证页面
  `<head>` 有标准 viewport 声明:`<meta name="viewport" content="width=device-width, initial-scale=1.0">`。
- Widget 浮层使用 `position: fixed` 与 `z-index: 99999`。宿主页面的自有弹层如需
  盖过 Widget,需要更大的 z-index;发现遮挡冲突时优先调整宿主侧层级,并把案例
  反馈给 Ask AI 团队。

## 1.8 Widget 行为速查(排障时对照)

| 行为 | 真实表现 |
|------|---------|
| 重复加载保护 | 同一页面二次执行 widget.js 自动跳过(容器已有内容),不会出现双浮窗 |
| 脚本更新 | 后端对 widget.js/css 下发 5 分钟浏览器缓存 → 发布新版后约 5 分钟内全网生效;强刷可立即拿到新版 |
| site-config 失败 | 静默回退默认体验(英文默认欢迎语/推荐问题),**不阻塞** Widget 出现;站点是否授权在提问时由服务端最终裁决 |
| 站点未授权(403) | 提问后气泡显示"此站点未被授权使用 Ask AI。" |
| 内容超限(422) | 问题 >8000 字符或格式错误 → 提示精简后重试 |
| 限流(429) | 每 IP 每分钟 20 次提问;触发后显示"服务繁忙,请稍后再试" |
| 生成失败/流中断 | 气泡内显示失败提示,绝不留空白气泡伪装成功;部分内容已输出的会保留并追加提示 |
| 引用点击 | 答案中的引用徽标可点击跳转来源;来源由 Ask AI 知识库决定,宿主无需处理 |

---

# Part 2 — Headless / Custom UI Integration

## 2.1 定位与原则

**Ask AI Core 是 headless 的**:官方 Widget 只是核心能力之上的一个参考客户端,
不是产品边界。如果你的站点要自建聊天 UI(自己的浮窗样式、自己的消息流布局),
可以直接调用 Ask AI 的完整产品能力。

**Headless 不是直接调用大模型**。你的每一次提问仍然完整经过 Ask AI 服务端管线:

```
site identity / authorization(站点鉴权,与官方 Widget 完全同一套)
  → intent → retrieval(检索)→ knowledge trust boundary(知识信任边界)
  → generation(生成)→ citation(引用)→ conversation(会话记录)
  → page context / language(上下文与语言)→ analytics(分析统计)→ lead 行为
```

你只是把"渲染消息气泡"这一层换成了自己的实现。**不存在绕过检索直接问 LLM 的
接入方式**,也不需要——引用、信任边界、统计、线索行为都依赖服务端管线。

**当前状态:READY(浏览器直连)**。官方 Widget 生产形态消费的就是下述 API,
无任何 Widget 专属端点;下述契约全部来自真实实现并有其测试锚定。

## 2.2 API 面(完整清单)

| 端点 | 方法 | 限流 | 用途 |
|------|------|------|------|
| `/api/widget/site-config?site_id=…` | GET | —(同样受站点鉴权) | 可选:读取本站欢迎语/推荐问题,供自建 UI 使用 |
| `/api/ask` | POST | **20 次/分钟/IP** | 核心问答(SSE 流式响应) |
| `/api/upload` | POST | 10 次/分钟/IP | 可选:附件上传(FormData,≤5 文件) |
| `/api/feedback` | POST | — | 可选:答案反馈(up/down) |

约束(与官方 Widget 完全一致):

- **浏览器直连**。带 `site_id` 的请求必须携带浏览器 `Origin`(浏览器 fetch 自动
  带上;服务端代为转发的调用没有 Origin,会按设计被 403 拒绝——headless 模式
  请从前端页面直接调用)。CORS 白名单规则见 §1.4,headless 与 Widget 同一套。
- `channel` 固定用 `"widget"`(公共访客渠道;目前没有独立的 headless 渠道值,
  不要自创——自创会被 422 拒绝)。
- API 无版本号。当前契约为 CAMTHINK V1 RC 冻结形态,由 Ask AI 仓库测试锚定;
  变更会同步更新本文档。

## 2.3 提问:POST /api/ask

**请求体**(JSON,全部键为真实 schema 字段):

```jsonc
{
  "message": "Does it support PoE?",          // 必填,1~8000 字符
  "channel": "widget",                         // 必填,固定 "widget"
  "site_id": "camthink-website",               // 三站接入必填
  "page_context": {                            // 可选,见 §1.5 字段契约
    "page_type": "product", "product": "NE503"
  },
  "language": "en",                            // 可选,页面语言提示(语义见 Part 3)
  "conversation_history": [                    // 可选,客户端自带的上下文
    { "role": "user", "content": "..." },
    { "role": "assistant", "content": "..." }
  ],
  "session_id": "你的匿名会话UUID",             // 可选;用附件时必填(归属校验)
  "attachments": ["<upload 返回的附件id>"]      // 可选,≤5 个
}
```

注意:

- `conversation_history` 只保留 `role`/`content`,`role` 仅接受
  `user`/`assistant`(其他值会被服务端降级为 `user`,防注入);官方 Widget 发送
  最近 10 条,建议对齐。
- `message` 会经过服务端 PII 脱敏后进入管线;引用、信任边界、统计全部照常生效。

**响应**:`200` + SSE 流(`text/event-stream`)。**错误在流之前**返回:
`403` 站点/来源未授权、`422` 参数问题(超长/格式/site_id 形状非法/未知附件)、
`429` 超限流。浏览器端用 fetch 消费(原生 `EventSource` 不支持 POST,不可用)。

**SSE 事件契约**(逐事件,字段名精确):

| 事件 | data JSON | 说明 |
|------|-----------|------|
| `sources` | `{"conversation_id": "...", "sources": [{"url","title","type","product"?}]}` | **先于**任何 token 到达;引用来源数组,`[N]` 标记按 1-based 下标对应它 |
| `token` | `{"content": "..."}` | 答案增量,**Markdown 文本**;`[N]` 为引用标记 |
| `error` | `{"conversation_id","kind","message"}` | 生成失败信号,在 `done` 之前;`kind` ∈ `empty_generation`(零可用内容)/`provider_error`(首 token 前异常)/`stream_interrupted`(部分输出后中断) |
| `declined` | `{"reason"}` | 预算熔断(服务繁忙);之后仍会有 `done` |
| `done` | `{"conversation_id"}` | 流结束(总是最后一个事件) |

解析细节:事件以空行分隔,行格式 `event: <名>` 与 `data: <JSON>`;解析前先把
`\r\n` 归一为 `\n`(官方客户端即如此处理);不认识的**事件类型直接忽略**(向后
兼容契约);不认识的**字段直接忽略**。

## 2.4 引用契约(必须正确处理)

答案文本中的 `[N]` 是引用标记,**N 是 `sources` 事件数组中来源的 1-based 下标**。
官方客户端的权威处理规则(自建 UI 建议对齐):

1. `[N]` 且 `sources[N-1]` 存在 → 替换为指向 `sources[N-1].url` 的可点击引用徽标
   (徽标文本 = N,title = 来源标题);
2. `[N]` 但 `sources` 中无对应项 → **删除标记**(不渲染为文本);
3. 代码块(``` 包裹)内的 `[N]` **不是引用**,原样保留;
4. Markdown 链接只放行白名单域名(github.com、raw.githubusercontent.com、
   camthink.ai 及其子域、wiki.camthink.ai、docs.camthink.ai),白名单外链接按
   纯文本渲染。

答案文本本身是**受限 Markdown**:代码块/行内代码、`**粗体**`、`[文本](链接)`、
`# 标题`、`- 列表`。自建 UI 可以用任何 Markdown 渲染器,但**必须**实现上述
`[N]` → 来源徽标替换,否则用户看到裸 `[1]` 标记且无法溯源。

## 2.5 会话延续与反馈

- **会话由客户端驱动**:服务端不为公开访客提供"取回历史对话"的接口。要实现多轮,
  自建 UI 需自行保存消息并把最近若干轮放进下一次请求的 `conversation_history`
  (与官方 Widget 同构)。
- `conversation_id`(`sources`/`error`/`done` 事件都携带)用于:`POST /api/feedback`
  反馈:`{"conversation_id":"...","feedback":"up"|"down"}`;以及 Ask AI 侧分析
  对账(向 Ask AI 团队报告问题时提供)。
- 附件流:`POST /api/upload`(FormData:`session_id` + 多个 `files`)→ 返回
  `{attachments:[{id,filename,kind,ok,error}]}` → 把成功的 `id` 放进 `/api/ask`
  的 `attachments`。`session_id` 是你自行生成并持久化(如 localStorage)的
  匿名 UUID,服务端不签发。

## 2.6 Headless 最小可运行示例(真实契约,可直接改造)

```html
<script>
(async function () {
  const API = "https://<ASK-AI-PRODUCTION-API-BASE>";

  // 1. 可选:读取站点体验(欢迎语/推荐问题);403 时按未授权处理
  const cfg = await fetch(`${API}/api/widget/site-config?site_id=camthink-website`)
    .then(r => (r.ok ? r.json() : null))
    .catch(() => null);

  // 2. 提问(多轮:把历史放进 conversation_history)
  const resp = await fetch(`${API}/api/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      message: "Does it support PoE?",
      channel: "widget",
      site_id: "camthink-website",
      page_context: { page_type: "product", product: "NE503" },
      language: "en",
      conversation_history: [],           // 多轮时放最近 ~10 条 {role,content}
      session_id: crypto.randomUUID(),     // 用附件时请持久化同一 UUID
      attachments: [],
    }),
  });

  if (!resp.ok) {                          // 403 未授权 / 422 参数 / 429 限流
    showMyOwnErrorUI(resp.status);
    return;
  }

  // 3. 消费 SSE(POST 只能走 fetch 流;原生 EventSource 不支持 POST)
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "", sources = [], answer = "";
  const handle = (type, d) => {
    if (type === "sources")      sources = d.sources;         // 先到:先备好来源
    else if (type === "token") { answer += d.content; renderMyMarkdown(answer, sources); }
    else if (type === "error")   showMyOwnFailureUI(d.kind, d.message);
    else if (type === "declined") showMyOwnBusyUI(d.reason);
    /* done:流结束;可存 d.conversation_id 供反馈/对账 */
  };
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    const events = buffer.split("\n\n");
    buffer = events.pop() || "";
    for (const event of events) {
      let type = "", data = "";
      for (const line of event.trim().split("\n")) {
        if (line.startsWith("event: ")) type = line.slice(7).trim();
        if (line.startsWith("data: ")) data = line.slice(6);
      }
      if (data) handle(type, JSON.parse(data));
    }
  }
})();
// renderMyMarkdown:受限 Markdown 渲染 + §2.4 的 [N]→来源徽标替换规则
// showMyOwnErrorUI / showMyOwnFailureUI / showMyOwnBusyUI:自建 UI 的失败态
</script>
```

## 2.7 Headless 验收要点

在 Part 4 通用 Checklist 之上,自建 UI 额外确认:

```
[ ] sources 事件先于 token 渲染来源,[N] 徽标可点击且指向 sources[N-1].url
[ ] 无对应来源的 [N] 标记被移除,不裸露
[ ] error / declined 事件有用户可见的失败态,done 后 UI 复位可继续提问
[ ] 403(未授权)/ 429(限流)有用户可见文案
[ ] conversation_history 参与多轮:追问"它呢?"能继承上一轮对象
[ ] page_context / site_id / language 随请求发送且值正确
```

---

# Part 3 — Multilingual Integration(English / 中文)

## 3.1 冻结产品语义

- Website / Wiki / Store 三站**全部支持 English / 中文切换**,默认语言**全部为
  English**。
- `site_id` = Site Identity(站点身份),`language` = Current Page Language
  (当前页面语言)。**仍然只有三个 site_id**,绝不按语言拆成六个。
- Widget 应跟随**当前页面实际语言**;页面语言优先于浏览器语言;浏览器语言只在
  页面语言无法确定时兜底;最终 fallback = English。

## 3.2 接入方(宿主)该怎么做

宿主侧的能力**今天已具备**,按以下方式表达页面语言:

1. **按语言版本模板传 `data-language`**。三站的语言切换如果是独立页面/路径
   (如 `/en/...` 与 `/zh/...`,或独立语言模板),在每个语言版本的公共模板上写:

```html
<!-- 英文版页面模板 -->
<script src="…/widget.js" data-api-url="…" data-site-id="camthink-website" data-language="en" async></script>
<!-- 中文版页面模板 -->
<script src="…/widget.js" data-api-url="…" data-site-id="camthink-website" data-language="zh" async></script>
```

2. **SPA / 页内即时切换语言**:语言配置在脚本加载时读取一次,页内切换后需刷新
   页面(传统多语言站点的整页跳转天然满足)。
3. **保持 `<html lang>` 准确**(如 `<html lang="en">` / `<html lang="zh-CN">`)。
   这是 W3C 惯例,也是 Ask AI 后续把页面语言接入解析链时的权威读取点。
4. 不知道页面语言时**不要猜传**——留空即可,不要用浏览器探测逻辑自行赋值。

## 3.3 当前真实行为(如实说明)

| 维度 | 当前实现(真实行为) |
|------|---------------------|
| **AI 答案语言** | 由**提问文本自动检测**决定:含假名→日语、含汉字→中文、含谚文→韩语、**其余一律按英语回答**。即:中文页面中文提问→中文回答;英文页面英文提问→英文回答。**最终 fallback = English ✓** |
| 页面语言提示(`data-language` / `AskAIConfig.language`) | 已纳入请求契约随 ask 发送,但**当前不影响答案语言**(服务端管线尚未消费该提示)——属于预留契约,行为变更会更新本文档 |
| 浏览器语言(navigator.language) | 自动采集进 `page_context.language`,作为生成背景信息(软提示);**不**决定答案语言 |
| `<html lang>` | 当前**未**被读取(见 Gap G-L2) |
| 站点默认语言 | 站点配置(language 字段)三站均为 `en`(2026-09-02 已按冻结语义修正);宿主未传页面语言时随 ask 发送 `en` |
| 官方 Widget 界面文案 | 输入占位、错误提示、兜底欢迎语等界面文案**当前为中文,不随页面语言切换**(见 Gap G-L4) |
| 欢迎语 / 推荐问题 | 按站点单语配置(website 英文、store 英文、**wiki 当前为中文文案**),**不**随页面语言切换(见 Gap G-L5) |

**实践结论(今天可用)**:三站以 English/中文双语运营时,只要访客用页面语言
提问,答案语言天然正确(检测机制完整覆盖中英两大场景)。宿主按 §3.2 传
`data-language` 是**正确且推荐**的做法——它让请求契约完整,并与后续行为升级兼容。

## 3.4 期望的语言解析链(Gap 登记 → Planner)

期望 Resolution(冻结语义):

```
Current Page / Host Language(宿主显式,发送时读取)
        ↓ 缺省
<html lang> / explicit host language
        ↓ 缺省
browser language
        ↓ 缺省
English
```

| # | Gap(现状 → 期望) | 需要谁 | 性质 |
|---|---------------------|--------|------|
| G-L1 | 生成管线不消费请求 `language` 提示,仅靠提问文本检测(非中/日/韩问题一律英语) | Ask AI Core | 行为变更 |
| G-L2 | Widget 不读 `<html lang>`;`language` 配置仅加载时读取一次,不支持页内热切换 | Ask AI Widget | Widget 行为变更 |
| G-L3 | 浏览器语言未作为 ask 语言兜底(仅作背景提示) | Ask AI Core/Widget | 行为变更 |
| G-L4 | Widget 界面文案(占位/错误/按钮)硬编码中文,无 i18n | Ask AI Widget | Widget i18n |
| G-L5 | 欢迎语/推荐问题按站点单语(website/store 英文、wiki 中文文案),无双语变体;wiki 站点体验文案与"默认 English"尚未对齐 | Ask AI 站点配置契约 | 契约扩展 + 内容决策 |

以上均为 **Core/Widget 行为变更或内容决策,不在本接入契约授权范围内**,已登记
待 Planner 裁决;宿主接入**不被上述 Gap 阻塞**(§3.3 实践结论)。

---

# Part 4 — 验收 Checklist

每站上线前逐项勾选(**全部在真实授权域名下、生产 API 地址上执行**):

通用项:

```
[ ] Widget 浮动按钮正常出现(Headless:自建入口正常工作)
[ ] 页面上没有重复 Widget(含 iframe 场景)
[ ] 点击可打开面板,可关闭,可再次打开
[ ] 能发送问题,答案流式出现
[ ] 答案附带引用,引用可点击且指向合理来源
[ ] Network 中 site-config 请求返回 200,ask 请求返回 200
[ ] ask 请求 payload 中 site_id 正确(如 camthink-website)
[ ] ask 请求 Origin 为本站授权域名(DevTools → Request Headers)
[ ] Page Context 正确(payload 中 page_context.url/title 为当前页;结构化字段与页面一致)
[ ] 桌面端浏览器(Chrome/Safari 至少各一)布局与交互正常
[ ] 移动端(真机或 DevTools 移动模拟,≤640px)布局与交互正常
[ ] 站内跳转(或 SPA 路由切换)后再提问,上下文与新页面一致
[ ] Console 无新增严重错误(error 级)
[ ] Network 无 CORS 报错、无 4xx/5xx(除有意触发的排障验证)
```

多语言项(三站均适用,站点默认 English):

```
[ ] 中文版页面提问中文问题 → 中文回答;英文版页面提问英文问题 → 英文回答
[ ] 各语言版本模板的 data-language 与页面语言一致(payload 可查)
[ ] <html lang> 与页面实际语言一致
[ ] 语言切换(整页跳转)后 Widget 语言表现符合 §3.3 预期
```

分站验收示例(功能性冒烟,内容质量属 Ask AI 团队职责范围):

**Website(www.camthink.ai)**

- 首页提问 "What products does CamThink offer?" → 得到产品线概述与引用。
- 任一产品页(如 NE503)提问 "Does it support PoE?" → 回答围绕**当前页产品**展开
  (验证 Page Context 指代解析),并带引用。
- 中文版产品页用中文提问 "NE503 支持 PoE 吗?" → 中文回答。

**Wiki(wiki.camthink.ai)**

- 文档页提问/点击推荐问题 "这篇文档对应的设备如何开始配置?" → 得到与文档主题
  相关的步骤型回答与引用。
- 英文版文档页英文提问 → 英文回答。

**Store(store.camthink.ai)**

- 商品页(如 NE503)点击 "Is NE503 suitable for my project?" → 回答围绕该商品,
  `page_context.sku` 与页面商品一致。
- 提问 "What is included in the box?" → 得到包装清单类回答(来自知识库,带引用)。

---

# Part 5 — Troubleshooting

按症状定位。所有"联系 Ask AI 团队"的场合,请附上 §5.1 的证据包。

| 症状 | 最可能原因 | 处理 |
|------|-----------|------|
| **Widget 完全不出现** | ① script 未加载(地址错/网络/广告拦截插件/CSP 拦截) ② `widget.js` 404 | ① DevTools Network 看 widget.js 请求:失败→查地址与拦截;② 404→联系 Ask AI 团队 |
| **按钮/面板出现但样式错乱** | 引入了 JS 但**没引入 CSS** | 补上 `ask-ai-widget.css` 的 `<link>`(两者必须成对) |
| **API 请求失败(net::ERR_… / 请求不通)** | `data-api-url` 错误;生产地址未就绪;https 页面请求了 http 接口(混合内容被拦截) | 核对地址;确认 §0 生产地址已提供;API 必须与页面同为 https |
| **Console 出现 CORS error** | 本站 Origin 不在 Ask AI 生产 `CORS_ALLOW_ORIGINS` | 提供准确 Origin 给 Ask AI 团队加入白名单(注意 www/非 www、http/https 是不同 Origin) |
| **提问返回"此站点未被授权使用 Ask AI。"(403)** | `data-site-id` 拼写错误;或当前 Origin 不在该站点授权清单;或站点被禁用 | 核对 §1.2 逐字符 site_id;核对 Origin;排除后联系 Ask AI 团队查站点状态 |
| **Widget 出现但欢迎语/推荐问题是英文默认值**(预期应为站点定制文案) | site-config 拉取失败(网络/403),Widget 已静默回退 | 看 Network 里 `site-config` 请求的状态码与 Origin,按上两行排查 |
| **Widget 重复出现** | 页面被嵌入 iframe(内外各挂了一次);或两套模板各引了一次 | 确保全站只引一次;iframe 场景只需在最外层窗口挂载 |
| **Page Context 错误 / 产品解析不对** | 结构化字段没按页面渲染;或字段写死成演示值 | 检查 `window.AskAIConfig.pageContext` 是否随模板/路由更新;url/title 自动采集无需手工指定 |
| **SPA 路由切换后上下文不正确** | 路由钩子没有更新 `window.AskAIConfig.pageContext` | 在路由变化处更新 pageContext(§1.7) |
| **回答语言不符合预期** | 答案语言跟随**提问文本**(中文问题→中文,其余→英语);页面语言提示当前不改变答案语言(§3.3/§3.4) | 引导访客用页面语言提问;确认问题文本无混入他语言字符;Gap 已登记 Ask AI 团队 |
| **Headless:拿到的答案只有裸 `[1] [2]` 标记** | 自建 UI 未按 §2.4 处理 `[N]` → 来源徽标替换 | 实现引用替换规则(sources 事件先到) |
| **Headless:请求 403 但同源 Widget 正常** | 请求缺 `Origin`(服务端代理转发)或 `channel` 不是 `"widget"` | 浏览器直连;channel 固定 `"widget"`(§2.2) |
| **回答正常但 UI 异常**(面板被遮挡/字体错乱) | 宿主全局 CSS 冲突;宿主弹层 z-index > 99999;宿主脚本移除了 `#ask-ai-widget-root` | 调整宿主侧样式/层级;保留容器;收集证据反馈 Ask AI 团队 |

### 5.1 反馈 Ask AI 团队时的证据包

1. 发生问题的**页面 URL**(完整地址栏);
2. 该页面的 **Origin**(scheme+host,从任一 API 请求的 Request Headers `Origin` 复制);
3. 使用的 **site_id**(从 ask 请求 payload 复制);
4. **Console 全部报错**截图(含 CORS/混合内容提示);
5. **Network 面板**:`site-config` 与 `ask` 两条请求的状态码、请求头(Origin)、
   以及**响应体**(403 响应体为统一文案,可安全提供;其他响应体隐去敏感字段后提供);
6. 浏览器与设备(如 Chrome 12x / macOS;iPhone Safari iOS 17);
7. 问题现象截图/录屏。

---

# Part 6 — 职责边界

**网站负责人负责**:

- 正确加载 Widget(CSS + JS 成对)或正确调用 API(Headless);
- 传正确的 `site_id` 与 API 地址;
- 按需提供真实、准确的 Page Context 与页面语言(不知道就不传);
- 页面布局兼容(桌面/移动、z-index、viewport);
- SPA 场景的路由上下文更新;Headless 场景的 Markdown/引用渲染与多轮历史管理;
- Console/Network 无新增严重错误;
- 在真实站点上完成 Part 4 验收。

**Ask AI 团队负责**(网站负责人无需关心,出问题联系即可):

- RAG 检索、知识库(Corpus)、大模型生成、引用引擎、知识信任边界;
- 后端服务与 API 可用性、生产 API 地址的建立与通知;
- CORS 白名单与站点授权配置(新增 Origin 需申请);
- 站点体验配置(欢迎语/推荐问题/语言);多语言行为升级(G-L1~G-L5);
- 销售线索(Lead)、对话数据的存储与统计。

---

# 附:快速对照卡

**官方 Widget(全站模板 `</body>` 前):**

```html
<link rel="stylesheet" href="https://<ASK-AI-PRODUCTION-API-BASE>/widget/ask-ai-widget.css">
<script src="https://<ASK-AI-PRODUCTION-API-BASE>/widget/widget.js"
        data-api-url="https://<ASK-AI-PRODUCTION-API-BASE>"
        data-site-id="camthink-website|camthink-wiki|camthink-store"
        data-language="en|zh"
        async></script>
```

**页面上下文(需要指代解析的页面模板):**

```html
<script>window.AskAIConfig = window.AskAIConfig || {};
window.AskAIConfig.pageContext = { page_type: "...", product: "...", sku: "..." };</script>
```

**Headless(最小问答):** `POST {API}/api/ask`,body 含
`message` + `channel:"widget"` + `site_id`,fetch 流式消费
`sources → token* → (error|declined)? → done`,按 §2.4 渲染引用。

---

*本文档由 Ask AI 工程(Codex D,HANDOFF-G001 及其 2026-09-02 Multilingual/Headless
follow-up)基于真实实现冻结;文中行为均可在对应版本自动化测试中追溯。占位符
`<ASK-AI-PRODUCTION-API-BASE>` 的正式值由 Ask AI 团队另行通知。变更记录:v1.0
Widget 接入 → v2.0 升级为 Website Integration Guide(新增 Headless 与 Multilingual
部分;原 Widget 文件名已由本文件取代,不留双权威指南)。*
