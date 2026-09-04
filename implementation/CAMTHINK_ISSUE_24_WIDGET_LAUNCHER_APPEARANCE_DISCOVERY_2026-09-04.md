# Issue #24 — Widget Launcher Appearance & Built-in Visual Styles · Discovery 报告

- **日期**:2026-09-04
- **模式**:READ-ONLY / DESIGN DISCOVERY ONLY(零实现、零生产接触)
- **执行身份**:Engineering Executor
- **基线**:`698e727b743e65a13e5ba3a7b61de07c21ac470b`(已验收 v1.1 Issue#22 候选;discovery worktree `.worktrees/discovery-issue24-widget-launcher`,分支 `discovery/issue24-widget-launcher`)
- **SoT**:GitHub Issue #24(产品方向权威)

---

## EXECUTIVE SUMMARY

**READY(架构无阻塞;4 项 Product Decision 附建议,由 Planner 在实现契约中冻结)。**

核心结论:

1. **Launcher 是一个 52×52 的固定定位 `<button class="ask-ai-fab">`,内嵌一张 base64 内联的 PNG(`CamThink.ai-black.png`)**,渲染于 `widget/src/App.tsx`;样式硬编码于 `widget/src/styles/widget.css`(黑底、12px 圆角、24px 边距,移动端 16px)。除此之外没有任何 launcher 视觉系统。
2. **Widget = 直接 DOM 嵌入**(React `createRoot` 挂宿主页 `#ask-ai-widget-root`),无 iframe、无 Shadow DOM。因此:① `prefers-color-scheme`(matchMedia)是**唯一可靠的主题信号** = `theme=auto` 的权威实现;宿主页面自身配色不可靠检测,按契约禁止猜测 → auto 确定性回退 = light;② 无隔离边界意味着样式令牌必须自带作用域(现状靠类名前缀 + 单根 id,无 token 体系)。
3. **主题现状 = 无**:全 CSS 硬编码浅色,零 `prefers-color-scheme`、零 `matchMedia`;仅有的两个 CSS 变量(`--ask-ai-primary`/`--ask-ai-text-secondary`)从未被赋值(恒走 fallback #2563eb);`primaryColor` 配置键存在但**没有任何消费点**(T1b 挂账的死配置)。Theme = light/dark 需要一个最小 token 层(建议 `#ask-ai-widget-root[data-ask-ai-theme]` 属性选择器),这是本特性唯一的前置基建。
4. **配置链路**:站点体验(welcome/starters/language)已由 `site_experiences` 表承载,`GET /api/widget/site-config` 按 Origin 授权返回;launcher 外观**按站点体验持久化**是唯一与现有架构一致的作用域(不发明第二权威)。表上无可复用的自由 JSONB 列 → 需要一次**加列迁移**(nullable,零回填;YAML 种子代码不写新列 → admin 值跨重启存续)。legacy(无 siteId)widget 无配置权威 → 恒为 `current` 默认外观,天然满足向后兼容。
5. **Admin 现状:不存在站点体验管理页**(`site_experiences` 由 YAML 启动种子入库,服务注释明言"为未来 Admin 管理留位")。因此 Admin UX 需要一个**新的最小「Widget 外观」面板**(站点列表 + 风格卡片 + 实时预览 + 主题切换 + 保存);实时预览的防漂移方案 = iframe 加载**真实生产 widget 产物**(`/widget/widget.js` + css)+ `data-launcher-style/theme` 预览覆写(沿 T1 data-* 配置链自然扩展),不复制任何 CSS。
6. **资产策略推荐:内联 SVG React 组件**(语义 style id 背后的实现细节):零额外网络请求(与现状 base64 PNG 同级)、CSP/CORS/隐私全绿、`currentColor` 原生支持双主题、高 DPI 矢量清晰、每风格 bundle 增量 ~1–2KB。
7. **与 #22 碰撞**:后端/-widget 零交集(NONE);唯一同文件面 = `admin/src/types/api.ts`(#22 改过 RepoDiscovery 类型,#24 亦会加类型)→ **FROZEN INTERFACE**;#6/#8 授权行为不受影响(site-config 仅对已授权 Origin 返回,新增外观字段不触碰 resolve_site/allowed_origins/CORS)。

---

## BASELINE

```
BASELINE_COMMIT = 698e727b743e65a13e5ba3a7b61de07c21ac470b(v1.1 Issue#22 已接受候选)
WORKTREE        = .worktrees/discovery-issue24-widget-launcher(独立,未触碰 #22 worktree)
生产形态        = widget IIFE 产物由后端 /widget 挂载(CachedStaticFiles),三站接入为
                  <link ask-ai-widget.css> + <script widget.js> 成对同源加载(G001 交接契约)
```

## CURRENT IMPLEMENTATION(问题 A:launcher 渲染现状)

| 维度 | 现状(文件级实证) |
|---|---|
| 渲染组件 | `widget/src/App.tsx` — `App()` 返回 `{!isOpen && <button className="ask-ai-fab" onClick={openPanel}><img className="ask-ai-fab-icon" src={fabIcon} alt="Ask AI"/></button>}`;`isOpen` 时 fab **卸载**、换渲染 `ChatPanel`(面板内 ✕ 按钮 `onClose`) |
| 资产来源 | `widget/src/assets/CamThink.ai-black.png`(11,166 bytes,Vite import → **base64 内联进 widget.js**,dist 实测仅 widget.js + ask-ai-widget.css 两文件,图标零额外请求);另有 `CamThink.ai-white.jpg`(12,302 bytes,当前**未被引用**) |
| 尺寸/布局/背景/阴影 | `widget.css:8-28`:`.ask-ai-fab{position:fixed;bottom:24px;right:24px;width:52px;height:52px;border-radius:12px;box-shadow:0 4px 12px rgba(0,0,0,.15);background:#000000;display:flex;...}`;`img{width/height:100%;object-fit:cover}`;移动端(≤640px)边距 16px |
| 开合状态关系 | 单布尔 `isOpen`;开=面板替换浮钮(浮钮卸载,无共享按钮、无 aria-expanded);关闭由 ChatPanel ✕ |
| 桌面/移动 | 仅边距与面板尺寸的 media query(`widget.css:245-256`);launcher 本体 52px 两端一致 |
| 可访问性 | 可访问名仅来自 `<img alt="Ask AI">`(按钮无 aria-label/aria-expanded);无 `:focus-visible` 定制(浏览器默认轮廓未被移除);无 reduced-motion 处理(typing 动画在面板侧,launcher 本体无动画) |
| 动画 | launcher 无动画(仅面板 typing dots) |
| 焦点行为 | 无焦点管理(开面板后焦点不迁移、关面板不返还浮钮)——属现状事实记录,不在本特性扩权范围 |

## WIDGET ARCHITECTURE(问题 B:隔离机制)

- **直接 DOM 嵌入**:`bootstrap.tsx mountWidget()` → `createRoot(#ask-ai-widget-root).render(<App/>)`;无 iframe、无 Shadow DOM、无 CSS-in-JS 隔离。
- launcher 与面板渲染在同一宿主文档;`#ask-ai-widget-root{position:fixed;bottom:0;right:0;z-index:99999}` 单根。
- 后果(CSS 继承):宿主样式可泄漏进 widget、widget 样式(类名前缀 `ask-ai-*` + 根 id 选择器)可影响宿主;主题检测运行在同一文档上下文(matchMedia 可用)。

## THEME TRUTH(问题 C:主题机制现状)

- **设计 token:不存在**。`widget.css` 全部硬编码(#ffffff/#333333/#dbdbdb/#000000 等);仅 `.ask-ai-ref`/`.ask-ai-sources` 引用 `var(--ask-ai-primary, #2563eb)` 与 `var(--ask-ai-text-secondary, #888)` 两个变量,而全仓**无任何赋值点**(grep `setProperty`/内联 style 均无)→ 恒走 fallback。
- **`primaryColor` 是死配置**:`bootstrap.tsx` 解析它(`DEFAULT_PRIMARY_COLOR="#f24a00"`),但 widget 渲染零消费点(grep 全源仅 types/bootstrap/tests;memory:T1b 挂账)。
- **`prefers-color-scheme`:零使用**;`matchMedia`:零使用;宿主主题继承:无。
- **`theme=auto` 今天可靠吗?** 部分可靠、边界清晰:
  - **可靠信号 = `window.matchMedia('(prefers-color-scheme: dark)')`**(直接 DOM 嵌入,标准 media query,可监听 change)→ 反映**操作系统/浏览器**主题,确定性强、可权威声明。
  - **不可靠 = 宿主页面自身配色**(页面可用类名/内联样式自选深浅,无语义信号;采样宿主背景色 = 启发式猜测,Issue 冻结「must not guess unpredictably」)。
  - **裁决建议**:`auto := prefers-color-scheme`,matchMedia 不可用/无匹配 → **light**(确定性回退);在配置语义与文档中明确 auto = 系统主题,而非宿主页面主题。
- 实现含义:需要一个**最小 token 层**(如 `#ask-ai-widget-root` 上 `--ask-ai-surface/--ask-ai-text/--ask-ai-border/...` + `[data-ask-ai-theme="dark"]` 覆写),launcher 风格消费 token;面板全量 token 化**不属于本特性**(只动 launcher 必需的子集,面板主题化为后续独立工作——避免范围爆炸)。

## CONFIGURATION TRUTH(问题 D:配置持久化)

链路现状(逐环实证):

```
嵌入页 <script data-site-id>  → bootstrap.resolveConfig(T1 四级 fallback:data-* → 预置元素 data-* →
  window.AskAIConfig → 默认值) → App 启动 fetchSiteConfig(GET /api/widget/site-config?site_id&language)
  → services/site_experiences.resolve_site(Origin 授权:enabled + allowed_origins 精确命中)
  → 返回 {site_id, display_name, welcome, language, starters}(仅体验字段,不含内部配置)
Admin 侧:site_experiences 由 config/sites.yaml 启动种子 upsert(seed_default_sites),"为未来 Admin 管理留位"
  → **当前无 Admin 管理页、无 admin API**
```

持久化面裁决:

- `site_experiences` 表列为强类型(display_name/allowed_origins/starters/welcome/language/welcome_i18n/starters_i18n/enabled),**无自由 config JSONB 列**可搭车 → 新增持久化必然需要**加列迁移**。
- **推荐**:加两列 `launcher_style: String(50) | null`、`launcher_theme: String(10) | null`(nullable、零回填、零默认值写入;单列 JSONB `appearance` 亦可,但两列更简单且无需 JSON 解析;V1 字段封闭,可扩展性由未来 PD 决定)。
- **关键约束(已实证)**:`seed_default_sites` 按 YAML upsert **显式列出**的字段——新列**不写入种子**即可保证 admin 设置不被重启覆盖(YAML 权威范围不变;sites.yaml 无需新键)。
- **向后兼容**:旧列值 NULL = 未配置 → 服务端不返回该字段或返回默认 `current|light`;客户端 `resolveConfig`/siteConfig 解析对未知值 sanitize(fail-safe,同 `resolveStarters` 纪律)→ 未知 `launcher_style`/`launcher_theme` 一律回落 `current`/`light`。
- API 变更:`/api/widget/site-config` 响应增 `launcher_style`/`launcher_theme`(仅体验字段扩展,不回 allowed_origins;授权路径零变化);admin 侧新增外观读写端点(见 F)。

## E. SITE SCOPE(作用域裁决)

现状可挂作用域:全局(无既有全局配置权威可搭车)、per site_experience(体验/品牌语义的既有权威:welcome/starters/language 都在此)、per Widget 实例(= data-* 启动参数,属嵌入页自配)。

**推荐:per site_experience(site_id)+ legacy 缺省**。理由:① launch 外观与 welcome/starters 同属「站点体验」语义,单一权威不重载;② legacy(无 siteId)widget 本就没有 site 行,恒为 `current` 默认 = 升级零外观变化,向后兼容免费达成;③ 不新增第二配置权威(PD-2 纪律同 #22)。

## F. ADMIN UX TRUTH

- **现状**:admin/src/pages 无任何站点体验/Widget 页(11 个页面枚举核实);site_experiences 管理「留位」未实现。
- **结论**:本特性需要一个**新的最小 Admin 面板**(建议页名「Widget 外观」):列出站点体验(site_id/display_name)+ 风格卡片(视觉缩略)+ 主题选择(auto/light/dark)+ **实时预览** + 保存;后端需配套**新 admin 端点**(外观只读写:GET 列表/PUT appearance;复用 admin 鉴权依赖,Editor+ 权限位)。
- **实时预览防漂移架构(推荐)**:**iframe 加载真实生产 widget 产物**——`srcdoc`/预览页引用 `/widget/ask-ai-widget.css` + `/widget/widget.js`(与生产同一构建物),经 `data-launcher-style` / `data-launcher-theme` 预览覆写沿 `resolveConfig` T1 data-* 链生效;iframe 同时天然隔离 Admin 自身 CSS 与宿主浅色背景。**不复制任何 launcher CSS/JSX 到 Admin**(杜绝第二渲染器漂移);Admin 侧只维护风格卡片缩略(纯展示,允许与实现解耦——预览真相由 iframe 承担)。
- 预览覆写键(`data-launcher-style/theme`)仅作 Admin 预览与测试钩子,不对外承诺为公开配置面。

## ASSET STRATEGY(问题 G)

| 方案 | CSP | CORS/隐私 | 主题 | 体积 | 小尺寸/高清 | 维护 |
|---|---|---|---|---|---|---|
| **内联 SVG React 组件(推荐)** | ✅ 无外链、无 img-src 诉求 | ✅ 零第三方 | ✅ `currentColor`/token 原生 | 每风格 ~1–2KB | ✅ 矢量任意缩放 | 单文件单组件,git 可审 |
| 现状 base64 PNG | ✅ 内联 | ✅ | ❌ 固定色(需两张图) | ~15KB/张(base64) | ❌ 位图缩放发糊 | 需设计源文件 |
| 打包静态 SVG 文件 | ✅ | ✅ | ⚠ 需 mask/fill 技巧 | 同内联 | ✅ | 多文件引用管理 |
| 外部图片 URL | ❌ img-src 放大面 | ❌ 第三方泄漏 | ❌ | 0 | ⚠ | 外部依赖 |

**推荐:内联 SVG React 组件**,置于 `widget/src/launcher/`(每个风格 id 一个纯组件 + 一个风格注册表:语义 id → {glyph, 配色 token 用法});风格注册表是唯一 style id→实现映射(语义身份稳定,资产可整体重构)。不冻结具体画稿。

## ACCESSIBILITY(问题 I:launcher 相关缺口)

- 可访问名:现依赖 `<img alt="Ask AI">`;换 SVG 后必须**按钮级 `aria-label`**(实现验收项);开合语义建议补 `aria-expanded`/`aria-controls`(若维持双元素开合,至少 aria-label 区分打开/关闭)。
- 键盘:button 原生可聚焦回车激活 ✅;无 `:focus-visible` 定制(默认轮廓未被移除 → 现状可用;风格化时必须保留可见焦点环,列为验收项)。
- 触达目标:52×52px ✅(≥44px 基线;移动端仅边距变化,尺寸不变)。
- 对比:黑底白图 ✅;新风格 light/dark 均须过对比检查(验收矩阵)。
- reduced-motion:launcher 现无动画;新风格若引入微动效必须 `@media (prefers-reduced-motion: reduce)` 降级(验收项)。
- 面板侧缺口(✕ 按钮无 aria-label 等)如实记录,**不扩入本特性**。

## PERFORMANCE(问题 J:实测)

- 构建实测(698e727,`npm run build`):`widget.js 253.41 kB(gzip 89.28 kB)` + `ask-ai-widget.css 5.06 kB(gzip 1.55 kB)`;launcher 图标 PNG base64 内联(无独立资产请求)。
- 请求基线:css + js 两个同源请求(嵌入成对契约),图标零额外请求;bootstrap 无阻塞外部资产。
- 多风格影响:内联 SVG 组件,3 个新风格预计 +2–6KB(gzip 更小),实现时实测并写进验收(bundle delta measured);不影响首帧(launcher 同步渲染,无懒加载依赖)。

## DEPENDENCY / COLLISION AUDIT(问题 K)

| 对象 | 分类 | 说明 |
|---|---|---|
| Issue #22 候选 698e727 | 后端/widget:**NONE**;`admin/src/types/api.ts`:**FROZEN INTERFACE** | #22 面=source/repo/website discovery + data_sources + DataSources 页;与 #24 面(widget/*、routes.py site-config、site_experiences、新 admin 页)零交集。唯一同文件=共享类型文件 `admin/src/types/api.ts`(#22 改 RepoDiscoveryGroup;#24 增 Widget 外观类型,不同区段,合并无冲突预期)→ 分类 FROZEN INTERFACE,建议 #24 实现契约可指定独立类型文件消解 |
| #6 Widget allowed origins / #8 CORS | **NONE(行为不可变)** | 外观字段只加在 site-config **已授权后**的响应体;`resolve_site`/`allowed_origins`/CORS 中间件零触碰;验收矩阵含「origin/CORS 行为不变」 |

## PROPOSED PRODUCT MODEL(问题 6;语义身份,非资产名)

```
launcher_style:  "current"(默认,向后兼容)| <内置语义 id,初始集合见 STYLE DIRECTIONS>
launcher_theme:  "auto"(默认)| "light" | "dark"
presentation 变体(icon-only/背景/浮钮):仅当架构支持干净引入才考虑——现状
  launcher 本就是单浮钮形态,"变体"会引入第二布局维度;建议 V1 不做(见 PD-2)。
```

- 持久化:`site_experiences.launcher_style/launcher_theme`(nullable;NULL=未配置)。
- 解析优先级(冻结建议):site-config 服务端值 → 客户端 sanitize(未知值回落)→ 预览覆写 data-*(仅 Admin 预览/测试)→ 默认 `current|light`。
- 风格 id 是**稳定语义身份**;SVG 组件/配色为注册表后的实现细节,可重构。

## STYLE DIRECTIONS(3–6 个方向;非最终画稿)

| 语义 id(建议) | 意图/性格 | 小尺寸 | light/dark | 实现形态 | 可访问性 |
|---|---|---|---|---|---|
| `current` | 现状保留:黑底圆角方 + CamThink 标 | ✅(现状即此) | 双主题同形(现状) | 现资产/迁移为 SVG | 维持并补 aria-label |
| `assistant-spark` | 极简助手:品牌色渐变圆盘 + 白色四芒星火花 | ✅ 单主形 | 渐变明暗双档 token | 内联 SVG + 渐变 token | 白 glyph 对比度高 |
| `chat-bubble` | 对话气泡:柔和气泡剪影 + 三点/尾巴 | ✅ 大剪影 | 单色 `currentColor` 适配 | 纯 path SVG | 剪影+底色双对比 |
| `orbit-neural` | 智能/系统:细线节点连边小星系 | ⚠ 需 ≥2.5px 线宽 | 细线随文本色 token | 线性 SVG | 线宽与对比需验证 |
| `quiet-gradient`(备选) | 主流 SaaS 助手:低饱和渐变圆 + 白色对话 glyph | ✅ | 渐变 token 双档 | SVG + 渐变 | 同 spark |
| `monogram`(备选) | 品牌字标徽章(抽象 "A") | ⚠ 依赖具体字形 | 面色+字形双 token | SVG path | 依赖最终字形 |

**建议初始集合**:`current` + `assistant-spark` + `chat-bubble` + `orbit-neural`(4 个:默认 + 3 个性格迥异的新风格;每增加一个 = 设计/双主题/双端 QA 成本线性增长,边际价值递减)。

## PROPOSED CHANGE BOUNDARY

**EXPECTED(实现主体)**
- `widget/src/App.tsx`(launcher 改从 launcher 模块取渲染)+ `widget/src/launcher/`(新:风格注册表 + SVG 组件 + launcher 呈现组件)
- `widget/src/styles/widget.css`(launcher 段 token 化;`[data-ask-ai-theme]` 覆写)
- `widget/src/bootstrap.tsx` / `widget/src/types.ts`(config 键 + 预览覆写 data-*;未知值 sanitize)
- `widget/src/utils/siteConfig.ts` / `SiteExperienceConfig` 类型(+launcher_style/theme)
- `backend/api/routes.py`(`/widget/site-config` 响应增两字段;授权路径零变化)
- `backend/services/site_experiences.py`(外观读取/normalize;**种子不写新列**)
- `backend/db/models.py`(site_experiences 两列)+ 新增加列迁移脚本(additive nullable)
- `backend/api/admin/` 新文件(外观 GET/PUT 端点,Editor+ 权限位)
- Admin 新页面(风格卡片/主题/iframe 实时预览/保存)+ 路由/导航项
- `widget/src/__tests__`、backend pytest(site-config/端点/回退)、admin vitest

**REQUIRED SUPPORTING**:devtest.html 更新(预览覆写示例)、sites.yaml 注释说明(不新增键)、G001 交接文档补充、`docs/implementation` 实现报告。
**FORBIDDEN**:`resolve_site`/allowed_origins/CORS 语义、/ask 管线、conversations、auth、#22 任何 surface、site_experiences 既有列语义变更、影子 DOM/iframe 化重构、生产环境。

## ACCEPTANCE MATRIX(提案)

| 域 | 用例 |
|---|---|
| STYLE | 每个内置风格渲染正确;`current` 与升级前逐像素一致(默认);未知 launcher_style → 回落 current |
| THEME | light ✓;dark ✓;auto = prefers-color-scheme(深/浅 OS 双态)✓;matchMedia 不可用 → light(确定性回退,文档化);dark 下面板仍是现状浅色 → 明确记录为 V1 边界(仅 launcher 主题化)或纳入范围由契约定 |
| ADMIN | 风格卡片可选;iframe 实时预览即时刷新;light/dark 预览切换;保存持久化;刷新/重登恢复选择 |
| WIDGET | 实际 launcher 与保存配置一致;开合行为不变;会话状态/starters/welcome 不变;origin/CORS 行为不变(403 路径回归) |
| VISUAL | desktop/mobile × light host/dark host/花哨背景 host × 高 DPI 截图矩阵 |
| ACCESSIBILITY | 键盘激活;focus-visible 可见;aria-label/accessible name;对比度(双主题);触达 52px;新风格动效 reduced-motion 降级 |
| PERFORMANCE | bundle delta 实测记录(gzip);零新增阻塞外部请求;bootstrap 首帧无回退 |
| COMPATIBILITY | 旧配置(无键)= current/light;缺 config(NULL 列)= current/light;非法值 = current/light;升级零静默外观变化 |

## PRODUCT DECISIONS(全部附建议;不问实现 HOW)

| PD | 议题 | 建议 | 权衡 |
|---|---|---|---|
| **PD-1** | 初始内置风格集合 | `current` + `assistant-spark` + `chat-bubble` + `orbit-neural`(4 个) | 风格越多设计/双主题/双端 QA 线性涨价;3 个新风格已覆盖极简/对话/科技三种性格 |
| **PD-2** | presentation 变体(icon-only/背景/浮钮)是否进 V1 | **不进 V1**(style+theme 已覆盖主要诉求;变体是第二布局维度,QA 矩阵翻倍) | Issue 列为 direction 而非冻结;延后不堵未来 |
| **PD-3** | 作用域:per-site vs 全局 | **per site_experience + legacy 缺省**(welcome/starters 同权威;legacy 升级零变化免费达成) | 全局更简单但与站点体验权威割裂;多站点品牌差异是真实诉求 |
| **PD-4** | auto 的回退语义 | **auto = prefers-color-scheme;不可用 → light;永不采样宿主配色**(文档化「auto=系统主题」) | 宿主页面深浅不可靠检测;可预测性优先于「看起来融入宿主」 |

## RISKS

1. 直接 DOM 嵌入 = 宿主 CSS 泄漏面不变;新风格用 CSS 变量 + 类名作用域缓解,不做 Shadow DOM 重构(超范围)。
2. `theme=auto` 只跟随系统主题:宿主页面手工深色 + 浅色系统 → launcher 显示浅色(确定性,文档化;PD-4)。
3. V1 主题化范围若仅 launcher,面板仍浅色——开面板后主题观感切换,需在契约中明确接受或扩围(默认建议:仅 launcher,面板 token 化另立)。
4. site-config 新增字段的向后兼容依赖客户端 sanitize;旧 widget + 新后端(多字段)已天然兼容(旧客户端忽略未知字段)✅。
5. 迁移为加列(nullable),但生产 site_experiences 已有 3 行真实数据 → 迁移脚本须幂等、零回填、锁粒度最小(与既有迁移纪律一致)。

## READY STATUS

```
READY_STATUS = READY
PD-1 初始风格集合(建议 current+spark+bubble+orbit)/ PD-2 变体不进 V1(建议)/
PD-3 作用域 per-site(建议)/ PD-4 auto=prefers-color-scheme→light 回退(建议)
PRODUCTION_MUTATIONS = NONE
NEXT: Planner 冻结实现契约(按本报告 Change Boundary + PD 裁决)→ 独立实现 worktree
```
