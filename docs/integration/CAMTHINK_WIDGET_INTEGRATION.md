# CamThink 三站 Ask AI Widget 接入指南

**目标读者**:负责 `www.camthink.ai`(官网)、`wiki.camthink.ai`(Wiki)、`store.camthink.ai`(Store)的前端 / 网站开发人员。

**本文档的目标**:你**不需要阅读 Ask AI 任何源码**,只看这一份文档即可完成接入。

- 文档版本:1.0(2026-09-02)
- 依据的 Ask AI 版本:CAMTHINK V1 RC(`release/camthink-v1-rc-2026-09-01`,基线 `1ff2936`)
- 所有配置键、端点、行为均直接取自该版本真实实现,并已通过其自带测试套件验证(57/57 通过)。

---

## 0. 接入前必读:生产 URL 状态

> **PRODUCTION_WIDGET_URL_READY = NO(截至 2026-09-02)**
>
> Ask AI 后端的公网接入地址(DNS + 反向代理)**尚未建立**,因此本文示例中的
> `https://<ASK-AI-PRODUCTION-API-BASE>` 是一个**待替换占位符**,不是已生效的地址。
>
> 在 Ask AI 团队正式提供生产 API 基址之前,你可以先把接入代码合入站点
> (挂载图标可以正常渲染),但**问答功能要到生产地址就绪后才会通**。
> 请勿自行猜测或编造该地址。

**需要由 Ask AI 团队提供**(网站负责人无需操作,此处仅说明依赖):

| # | 待提供项 | 说明 |
|---|---------|------|
| B1 | 生产 API 基址 | 一个公网可达的 **https** 域名,例如 `https://ask-api.camthink.ai`(最终以 Ask AI 团队正式通知为准),需同时路由 `/widget/*`(静态脚本)与 `/api/*`(问答接口) |
| B2 | CORS 白名单激活 | 生产环境 `CORS_ALLOW_ORIGINS` 需包含三个站点来源(见 §5.2),否则浏览器会拦截所有请求 |
| B3 | 站点配置确认 | 三个 `site_id` 已在生产数据库启用,且来源白名单与本指南 §4 一致 |

---

## 1. 你将接入什么

Ask AI Widget 是一个自包含的嵌入式聊天组件:接入后,页面右下角出现一个 CamThink
Logo 浮动按钮,点击展开对话面板。访客可以就 CamThink 产品/文档/购买问题提问,
Widget 以流式方式返回答案并附带可点击的引用来源。

```
访客浏览器(你的站点)
 ├─ 加载  {API基址}/widget/ask-ai-widget.css   (样式)
 ├─ 加载  {API基址}/widget/widget.js           (脚本,自动挂载浮动按钮)
 ├─ 启动时 GET {API基址}/api/widget/site-config?site_id=...   (读取本站欢迎语/推荐问题;失败自动回退,不阻塞)
 └─ 提问时 POST {API基址}/api/ask              (SSE 流式问答)
        └─ Ask AI 后端负责:检索 / 知识库 / 大模型 / 引用(全部与你的站点无关)
```

你的工作只有三件事:**放两行标签、填对 `site_id`、(可选)提供页面上下文**。

---

## 2. 三站身份(冻结值,直接使用)

| 站点 | `site_id` | 授权来源(Origin) | 站点语言 |
|------|-----------|-------------------|---------|
| 官网 Website | `camthink-website` | `https://www.camthink.ai` 以及 `https://camthink.ai` | en |
| Wiki | `camthink-wiki` | `https://wiki.camthink.ai` | zh |
| Store | `camthink-store` | `https://store.camthink.ai` | en |

- `site_id` **必须逐字符照抄**(小写、连字符)。接入时传错 `site_id` 或在未授权的
  来源下运行,问答会得到 403"站点未授权"。
- 三个 `site_id` 与 Ask AI 生产站点配置(`config/sites.yaml`,启动时幂等同步进
  数据库)完全一致。
- **Website 注意**:Ask AI 侧服务端授权已同时包含 www 与非 www 两个来源,但生产
  CORS 白名单模板当前只列了 `https://www.camthink.ai`(见 §5.2)。因此官网接入请
  **统一使用 `https://www.camthink.ai` 域名**(建议在站点边缘把非 www 301 到 www),
  或要求 Ask AI 团队把 `https://camthink.ai` 追加进 CORS 白名单。

---

## 3. 快速接入(推荐路径)

### 3.1 两行标签(data-* 配置,推荐)

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

**推荐用 `data-*` 的原因**:这是 Ask AI 的一等配置路径,配置随 `<script>` 标签走,
可读性最好,且在所有配置来源中优先级最高。

### 3.2 兼容路径(window.AskAIConfig)

如果你们的发布流程不便修改 script 标签属性,可以改用全局配置对象。
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

### 3.3 完整配置键参考

| 键 | data-* 写法 | AskAIConfig 写法 | 必填 | 说明 |
|----|-------------|------------------|------|------|
| API 地址 | `data-api-url` | `apiUrl` | **是**(生产) | Ask AI API 基址,不带尾部 `/`。缺省值为 `http://localhost:8000`(仅本地开发有意义) |
| 站点标识 | `data-site-id` | `siteId` | **是**(三站接入) | 见 §2。缺省 = 旧版公共 Widget(不发送站点字段,三站接入**禁止**缺省) |
| 界面语言 | `data-language` | `language` | 否 | 如 `"en"` / `"zh"`。缺省时自动采用站点配置中的语言(官网 en / Wiki zh / Store en) |
| 主题色 | `data-primary-color` | `primaryColor` | 否 | CSS 颜色值,缺省 `#f24a00`(CamThink 品牌橙)。三站接入建议**保持缺省** |

配置解析顺序(逐键独立回退,已由测试锚定):

```
1. <script> 标签 data-*(最高)
2. 页面预置 <div id="ask-ai-widget-root" data-*> 的 data-*
3. window.AskAIConfig
4. 内置默认值
```

绝大多数站点只需要第 1 级;第 2 级用于高级场景(预置容器),第 3 级是兼容路径。

---

## 4. Page Context:告诉 Ask AI "用户正在看什么"

### 4.1 它是什么、不是什么

Page Context 是随每次提问自动附带的一段**页面描述**,用于帮助 Ask AI 理解指代:

> 例:访客在 NE503 产品页问 "Does it support PoE?" —— Page Context 让 Ask AI
> 知道 `it` 大概率指 NE503。

**边界(重要)**:

- Page Context 是**非信任的语义提示**:Ask AI 只用它做指代解析与检索**软加权**,
  绝不会因此跳过检索、也不会把其中的内容当作事实依据。
- **它不是知识证据**。产品规格、技术参数、价格等答案内容,永远来自 Ask AI
  知识库检索与引用,与你的页面写了什么无关。
- 宿主**不需要为 Page Context 的正确性负内容责任**——按下面 §4.2 如实传递即可。

### 4.2 字段契约:自动采集 vs 宿主提供

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

- 宿主结构化字段通过 `window.AskAIConfig.pageContext` 提供,**在每次发送时实时读取**
  ——所以 SPA 路由切换时更新它即可,无需重新加载 widget。
- 自动采集的 `url` / `title` / `language` **不可被宿主覆盖**(防伪造设计)。
- **不知道的字段就不要传**。传 `null`、空串或猜一个值都比不传更差;未知字段会被
  Ask AI 后端直接丢弃。
- `url` 仅接受 http/https 形态;超长字段会被截断/拒绝,不影响提问本身。

### 4.3 提供方式示例(以产品页为例)

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

---

## 5. 授权模型:site_id、Origin 与 CORS

### 5.1 site_id 不是凭证

`site_id` 只是站点标识,**不提供任何授权**。一个请求要被 Ask AI 接受,必须同时满足:

1. `site_id` 对应的站点**存在且已启用**;
2. 请求的 **Origin 精确命中**该站点的授权来源列表(§2)。

校验发生在 Ask AI **服务端**(`site-config` 与 `ask` 两个端点都查)。任一条件不满足
→ 统一返回 403(不区分具体原因,防枚举)。Widget 侧对应表现:
`site-config` 拉取失败会**静默回退默认体验**(英文默认欢迎语/推荐问题),提问时
显示"此站点未被授权使用 Ask AI。"。

### 5.2 两层配置:服务端授权 + 浏览器 CORS

Ask AI 的来源控制有**两层**,都由 Ask AI 团队维护,网站负责人需要理解其差异以便排障:

| 层 | 配置 | 作用 | 三站清单(生产) |
|----|------|------|-----------------|
| 服务端站点授权 | 每站点 `allowed_origins`(§2) | 决定 403 与否 | website: www + 非 www;wiki;store |
| 浏览器 CORS | 环境变量 `CORS_ALLOW_ORIGINS` | 决定浏览器是否放行请求 | 生产模板:`https://www.camthink.ai, https://wiki.camthink.ai, https://store.camthink.ai` |

**推论**(排障时关键):

- 一个来源必须**同时**出现在两层,Widget 才能工作。这就是 §2 中 Website 建议
  统一走 `https://www.camthink.ai` 的原因(非 www 目前不在生产 CORS 清单)。
- Origin 匹配规则(真实实现):`协议://主机[:端口]` 全小写精确匹配;80/443 默认端口
  可省略也可显式写(归一化后等价);**不支持通配符**;scheme 必须完全一致
  (`https` 页面配 `http` 来源 = 不匹配)。
- `www` / 非 `www` 是两个不同的 Origin,需分别配置(Website 两个都已进服务端授权)。
- **localhost 默认不在生产授权内**:本地静态预览(`http://localhost:xxxx`)打开的
  测试页能渲染出 Widget 外观,但所有 API 请求都会失败。完整验收必须在真实
  授权域名下进行(见 §7)。
- 新增嵌入来源(例如未来某个活动专用域名)属于 Ask AI 侧配置变更:网站负责人
  需提前向 Ask AI 团队申请,提供准确 scheme+host(+非标端口)。

---

## 6. 三站接入示例

以下示例均为 production-style、可直接复制(替换唯一的占位符
`<ASK-AI-PRODUCTION-API-BASE>`,该值待 Ask AI 团队提供,见 §0)。

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

效果:访客在 NE503 页问 "Does it support PoE?",Ask AI 能把 `it` 解析为 NE503。
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

**文档页 Page Context**(Wiki 站点语言为 zh,自动回退,无需传 `data-language`):

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

---

## 7. 框架指引

### 7.1 静态 HTML / 传统多页站(如服务端模板渲染)

按 §3/§6 把两行标签放进全站公共 footer 模板即可,无需其他工作。
每次整页跳转都会重新挂载 Widget,这是预期行为(访客会话通过浏览器
localStorage 延续,对话不会因翻页丢失)。

### 7.2 React / SPA 类站点

1. **只挂载一次**:把 §3.1 的两行标签放进 SPA 的入口 HTML(`index.html`),
   **不要**在 React 组件里动态插入 script、也不要在路由切换时重复注入。
   (Widget 自带防重复挂载保护:同一页面重复执行脚本会自动跳过,但请不要依赖它。)
2. **路由切换时更新 Page Context**:Widget 在**每次发送**时实时读取
   `window.AskAIConfig.pageContext` 与当前 `location`/`title`,所以在路由
   变化的钩子里更新全局对象即可:

```jsx
// React Router v6 示例
useEffect(() => {
  window.AskAIConfig = window.AskAIConfig || {};
  window.AskAIConfig.pageContext = matchRoute(location.pathname);
  // 同步 document.title 由各页面自行负责,Ask AI 自动采集最新 title
}, [location.pathname]);
```

3. Widget 浮窗是独立的 fixed 定位 DOM(挂在 `#ask-ai-widget-root` 下),SPA 重渲染
   不影响它;不要把它挂进会被卸载的路由容器内(它本来就不在那里,勿移动)。

### 7.3 Wiki / Store 实际技术栈说明

本指南编写时,Ask AI 仓库内**没有**能证明 `wiki.camthink.ai` / `store.camthink.ai`
技术栈的工程证据,因此不对其栈做任何假设——上述示例均为 framework-neutral
(原生 HTML 标签),在任何能改公共模板/页脚的栈里都适用:

- WordPress / WooCommerce 类:放进主题 footer(`wp_footer` 或子主题模板);
  Page Context 片段放进对应页面模板(如 `single-product.php`),用模板函数输出
  真实商品字段。
- 静态站点生成器(Hugo/Docusaurus 等):放进全站布局模板,Page Context 用
  各自的前置参数/组件系统注入。

(如 Wiki / Store 负责人能确认栈,可按 §7.1/§7.2 对号入座;Ask AI 侧无需任何适配。)

### 7.4 移动端与桌面端

- Widget 自带响应式样式(≤640px 视口自动切换为移动端布局),宿主只需保证页面
  `<head>` 有标准 viewport 声明:`<meta name="viewport" content="width=device-width, initial-scale=1.0">`。
- Widget 浮层使用 `position: fixed` 与 `z-index: 99999`。宿主页面的自有弹层
  (导航抽屉、cookie 横幅等)如需盖过 Widget,需要更大的 z-index;发现遮挡冲突时
  优先调整宿主侧层级,并把案例反馈给 Ask AI 团队。

---

## 8. Widget 行为速查(排障时对照)

| 行为 | 真实表现 |
|------|---------|
| 重复加载保护 | 同一页面二次执行 widget.js 自动跳过(容器已有内容),不会出现双浮窗 |
| 脚本更新 | 后端对 widget.js/css 下发 5 分钟浏览器缓存 → 发布新版后约 5 分钟内全网生效;强刷可立即拿到新版 |
| site-config 失败 | 静默回退默认体验(英文默认欢迎语/推荐问题),**不阻塞** Widget 出现;站点是否授权在提问时由服务端最终裁决 |
| 站点未授权(403) | 提问后气泡显示"此站点未被授权使用 Ask AI。" |
| 内容超限(422) | 问题 >8000 字符或格式错误 → 提示精简后重试 |
| 限流(429) | 每IP每分钟 20 次提问;触发后显示"服务繁忙,请稍后再试" |
| 生成失败/流中断 | 气泡内显示失败提示,绝不留空白气泡伪装成功;部分内容已输出的会保留并追加提示 |
| 引用点击 | 答案中的引用徽标可点击跳转来源;来源由 Ask AI 知识库决定,宿主无需处理 |

---

## 9. 验收 Checklist

每站上线前逐项勾选(**全部在真实授权域名下、生产 API 地址上执行**):

通用项:

```
[ ] Widget 浮动按钮正常出现
[ ] 页面上没有重复 Widget(含 iframe 场景)
[ ] 点击可打开面板,可关闭,可再次打开
[ ] 能发送问题,答案流式出现
[ ] 答案附带引用,引用可点击且指向合理来源
[ ] Network 中 site-config 请求返回 200,ask 请求返回 200
[ ] ask 请求 payload 中 site_id 正确(如 camthink-website)
[ ] ask 请求 Origin 为本站授权域名(DevTools → Request Headers)
[ ] Page Context 正确(payload 中 page_context.url/title 为当前页;结构化字段如 product/sku 与页面一致)
[ ] 桌面端浏览器(Chrome/Safari 至少各一)布局与交互正常
[ ] 移动端(真机或 DevTools 移动模拟,≤640px)布局与交互正常
[ ] 站内跳转(或 SPA 路由切换)后再提问,上下文与新页面一致
[ ] Console 无新增严重错误(error 级)
[ ] Network 无 CORS 报错、无 4xx/5xx(除有意触发的排障验证)
```

分站验收示例(功能性冒烟,内容质量属 Ask AI 团队职责范围):

**Website(www.camthink.ai)**

- 首页提问 "What products does CamThink offer?" → 得到产品线概述与引用。
- 任一产品页(如 NE503)提问 "Does it support PoE?" → 回答围绕**当前页产品**展开
  (验证 Page Context 指代解析),并带引用。
- 推荐问题应显示官网语义的四条(如 "Which product fits my project?"),欢迎语为
  英文官网文案 → 证明 site-config 生效。

**Wiki(wiki.camthink.ai)**

- 文档页提问/点击推荐问题 "这篇文档对应的设备如何开始配置?" → 得到与文档主题
  相关的步骤型回答与引用。
- 欢迎语为中文、推荐问题为文档语义四条 → 证明 site-config 生效。

**Store(store.camthink.ai)**

- 商品页(如 NE503)点击 "Is NE503 suitable for my project?" → 回答围绕该商品,
  `page_context.sku` 与页面商品一致。
- 提问 "What is included in the box?" → 得到包装清单类回答(来自知识库,带引用)。
- 欢迎语为英文购买语义文案 → 证明 site-config 生效。

---

## 10. Troubleshooting

按症状定位。所有"联系 Ask AI 团队"的场合,请附上 §10.2 的证据包。

| 症状 | 最可能原因 | 处理 |
|------|-----------|------|
| **Widget 完全不出现** | ① script 未加载(地址错/网络/广告拦截插件/CSP 拦截) ② `widget.js` 404 | ① DevTools Network 看 widget.js 请求:失败→查地址与拦截;② 404→联系 Ask AI 团队 |
| **按钮/面板出现但样式错乱** | 引入了 JS 但**没引入 CSS** | 补上 `ask-ai-widget.css` 的 `<link>`(两者必须成对,见 §3.1) |
| **API 请求失败(net::ERR_… / 请求不通)** | `data-api-url` 错误;生产地址未就绪;https 页面请求了 http 接口(混合内容被浏览器拦截) | 核对地址;确认 §0 生产地址已提供;API 必须与页面同为 https |
| **Console 出现 CORS error** | 本站 Origin 不在 Ask AI 生产 `CORS_ALLOW_ORIGINS` | 提供准确 Origin 给 Ask AI 团队加入白名单(注意 www/非 www、http/https 是不同 Origin) |
| **提问返回"此站点未被授权使用 Ask AI。"(403)** | `data-site-id` 拼写错误;或当前 Origin 不在该站点的服务端授权清单;或站点被禁用 | 核对 §2 逐字符 site_id;核对 Origin;排除后联系 Ask AI 团队查站点状态 |
| **Widget 出现但欢迎语/推荐问题是英文默认值**(预期应为站点定制文案) | site-config 拉取失败(网络/403),Widget 已静默回退 | 看 Network 里 `site-config` 请求的状态码与 Origin;按上两行排查 |
| **Widget 重复出现** | 页面被嵌入 iframe(内外各挂了一次);或两套模板各引了一次且容器不同 | 确保全站只引一次;iframe 场景只需在最外层窗口挂载 |
| **Page Context 错误 / 产品解析不对** | 结构化字段没按页面渲染;或字段写死成演示值 | 检查 `window.AskAIConfig.pageContext` 是否随模板/路由更新;`url/title` 由 Ask AI 自动采集,无需也无法手工指定 |
| **SPA 路由切换后上下文不正确** | 路由钩子没有更新 `window.AskAIConfig.pageContext`(自动采集的 url/title 始终是新的,通常是结构化字段过期) | 在路由变化处更新 pageContext(见 §7.2) |
| **回答正常但 UI 异常**(面板被遮挡/字体错乱/按钮消失) | 宿主全局 CSS 与 Widget 冲突;宿主弹层 z-index > 99999;宿主脚本移除了 `#ask-ai-widget-root` | 优先调整宿主侧样式/层级;保留 `#ask-ai-widget-root` 容器;收集证据反馈 Ask AI 团队 |

### 10.2 反馈 Ask AI 团队时的证据包

1. 发生问题的**页面 URL**(完整地址栏);
2. 该页面的 **Origin**(scheme+host,从任一 API 请求的 Request Headers `Origin` 复制);
3. 使用的 **site_id**(从 ask 请求 payload 复制);
4. **Console 全部报错**截图(含 CORS/混合内容提示);
5. **Network 面板**:`site-config` 与 `ask` 两条请求的状态码、请求头(Origin)、
   以及**响应体**(403 响应体为统一文案,可安全提供;其他响应体隐去敏感字段后提供);
6. 浏览器与设备(如 Chrome 12x / macOS;iPhone Safari iOS 17);
7. 问题现象截图/录屏。

---

## 11. 职责边界

**网站负责人负责**:

- 在页面正确加载 Widget(CSS + JS 成对);
- 传正确的 `site_id` 与 API 地址;
- 按需提供真实、准确的 Page Context(不知道就不传);
- 页面布局兼容(桌面/移动、z-index、viewport);
- SPA 场景的路由上下文更新;
- Console/Network 无新增严重错误;
- 在真实站点上完成 §9 验收。

**Ask AI 团队负责**(网站负责人无需关心,出问题联系即可):

- RAG 检索、知识库(Corpus)、大模型生成、引用引擎;
- 后端服务与 API 可用性、生产 API 地址的建立与通知;
- CORS 白名单与站点授权配置(新增 Origin 需申请);
- 站点体验配置(欢迎语/推荐问题/语言);
- 销售线索(Lead)、对话数据的存储与统计。

---

## 附:快速对照卡

```html
<!-- ① 全站模板 </body> 前 -->
<link rel="stylesheet" href="https://<ASK-AI-PRODUCTION-API-BASE>/widget/ask-ai-widget.css">
<script src="https://<ASK-AI-PRODUCTION-API-BASE>/widget/widget.js"
        data-api-url="https://<ASK-AI-PRODUCTION-API-BASE>"
        data-site-id="camthink-website|camthink-wiki|camthink-store"
        async></script>

<!-- ② 需要页面上下文的页面模板 -->
<script>window.AskAIConfig = window.AskAIConfig || {};
window.AskAIConfig.pageContext = { page_type: "...", product: "...", sku: "..." };</script>
```

*本文档由 Ask AI 工程(Codex D, HANDOFF-G001)基于真实实现冻结;文中行为均可在
对应版本的自动化测试中追溯。占位符 `<ASK-AI-PRODUCTION-API-BASE>` 的正式值由
Ask AI 团队另行通知。*
