> **[历史证据归档 | HISTORICAL EVIDENCE — 非现行实现权威 / NOT CURRENT IMPLEMENTATION AUTHORITY]**
>
> 本文档为 Issue #33 Widget 主题闪变的 Discovery RCA 历史证据(2026-09-08,READ-ONLY discovery),
> 由 Repository Hygiene Phase 2B(2026-09-10,基线 `9343e65`)原样保存。
>
> - RCA 所分析的候选上下文含 **`b7a016d`**(#24 REV1 候选)与生产对照面 v1.0.0 `0e6a8a3`;
> - 其后已接受并合入 main 的现行实现 = first-paint/theme 正确性修复(候选 **`2cff7bf`**,REV1 **`3c5a56b`**,已在 main);
> - 现行 **I-UX-001 Post-Production Corrective 契约**
>   (`docs/engineering/tasks/I-UX-001-POST-PRODUCTION-CORRECTIVE-implementation-contract.md`,冻结于 `376565f`)
>   与上述已接受实现**在冲突处优先**;
> - 分隔线以下自原标题起为来源正文,逐字节未改写(来源 `0da88b9` @ `origin/docs/issue33-widget-theme-flash-rca`)。

# ISSUE-33 — Widget Theme Flash RCA Discovery

- **日期**: 2026-09-08
- **角色**: Engineering Discovery Agent(READ-ONLY;零源码变异、零生产变更、零修复)
- **现状**: P1 / NEEDS DISCOVERY / IMPLEMENTATION NOT AUTHORIZED
- **代码基线**:
  - **主题机制所在面** = Issue #24 REV1 候选 `b7a016d`(分支 `v1.1/issue24-launcher-design-rev1`,基线 2306118)— 本 RCA 的主对象
  - 生产 v1.0.0 = `0e6a8a3`(main)— **不存在任何服务器主题机制**(对照面,见 §2.4)
- **验证手段**: 源码逐行追痕 + 本地确定性浏览器复现(/tmp 台架,复用 rc-verify-b7a016d 的官方构建产物,16ms 页面内采样器抓首帧瞬态;台架与截图入 `docs/evidence/issue33-theme-flash/`)
- **PRODUCTION_MUTATIONS**: **NONE**

---

## 1. Current Bootstrap / Render Sequence(b7a016d 实码)

```
宿主页
 ├─ <link rel=stylesheet href="{origin}/widget/ask-ai-widget.css">      ← 静态 CSS(含默认外观规则)
 ├─ (可选) window.AskAIConfig / 预置 #ask-ai-widget-root data-*         ← 集成面覆写通道
 └─ <script src="{origin}/widget/widget.js">                            ← 后端静态托管(main.py:542-558)
      ↓ bootstrap.tsx mountWidget()
      ① resolveConfig():script data-* → 预置根 data-* → window.AskAIConfig → 默认
         (含 launcherIcon/launcherShape/launcherTheme 规范通道 + launcherStyle 遗留通道)
      ② React createRoot 渲染 #1(同步提交):
         App 以 siteConfig=null 渲染 → Launcher(悬浮球)以
         「嵌入显式覆写 ?? 遗留值退役 ?? [site-config 缺席] ?? 默认」解析外观
         = current 图标 | rounded-square | auto 主题 → **立即可绘制且恒可见**(面板外)
      ③ useEffect(React 保证在绘制之后)→ fetchSiteConfig(site_id, language)   [App.tsx:78-84]
         ← 仅当存在 siteId;网络 RTT + 服务端耗时
      ④ 响应 → setSiteConfig → 渲染 #2:Launcher 重渲染,
         data-launcher-icon/shape、data-ask-ai-theme 换为服务器值                [App.tsx:98-116,206-214]
      ⑤ 无任何持久化/缓存(siteConfig 不落 localStorage;每次页面加载重走①-④;
         uiLang 热切换会再拉取一次 → 二次应用窗口)
```

要点:**悬浮球(launcher)在服务端配置到达之前就已按客户端可解析值绘制**;面板未打开不影响——闪烁发生在恒可见的悬浮球上。

## 2. Theme Source-of-Truth Map

### 2.1 权威链(b7a016d)
| 层 | 载体 | 说明 |
|---|---|---|
| **Server SoT** | `site_experiences.launcher_theme`(+REV1 `launcher_icon`/`launcher_shape`) | Admin「Widget 外观」页写入(admin/editor 角色门禁);launcher_style 列冻结遗留 |
| 服务端出口 | `GET /api/widget/site-config` → `launcher_icon/launcher_shape/launcher_theme`(归一化)+ `launcher_style`(遗留回显,兼容缓存中旧 Widget) | routes.py:444-467;服务端已完成 legacy 桥与 fail-safe 归一 |
| 集成面覆写 | 嵌入 `data-launcher-icon/shape/theme`(显式)与遗留 `data-launcher-style` | **优先级高于 site-config**(Amendment #2 §3 消解链:显式嵌入 > 遗留嵌入 > site-config > 遗留 site 值 > 默认);这是契约警示的"integration-specific authority"唯一 sanctioned 形态=显式覆写 |
| 客户端默认 | registry:`DEFAULT_LAUNCHER_ICON="current"`、`SHAPE="rounded-square"`、`THEME="auto"`(auto=matchMedia 系统暗色,不可用→light) | registry.ts:30-50;未知/非法值全维回落(fail-safe) |
| CSS 呈现 | `.ask-ai-fab` 基线=黑 #000000(current 兼容外观);`[data-launcher-icon]:not(current)`=品牌橙 #f24a00;`[data-ask-ai-theme="dark"]` 变体;round 形状规则 | widget.css:27,44-84 |

### 2.2 主题在客户端的应用方式
属性驱动:Launcher 组件把消解结果写到按钮的 `data-launcher-icon/data-launcher-shape/data-ask-ai-theme`(`widget/src/launcher/Launcher.tsx`),CSS 按属性选择器换肤。**应用时机 = 渲染 #1(默认值)与渲染 #2(配置值)之间隔一次网络往返。**

### 2.3 无缓存参与
site-config 结果不持久化(无 localStorage/sessionStorage/service worker)。Admin 改主题 → 下次页面加载生效;**每次冷加载/刷新都重演"默认→配置"序列**。

### 2.4 对照面:生产 v1.0.0(0e6a8a3)无服务器主题
main 线的 widget:悬浮球/头部/发送钮全部**硬编码黑**;`config.primaryColor` 在 bootstrap 被解析但**无任何消费点(死配置)**;`--ask-ai-primary` 变量被消费但**无定义点**(恒回落 #2563eb);site-config 仅返回 display_name/welcome/starters/language,无主题字段;Admin 无主题 UI(customizations 仅 system_prompt/style_tone/guardrails/assistant_name/language)。
→ **Issue #33 所述"configured server theme"只存在于 #24 候选构建(v1.1 轨道);闪烁问题属于 v1.1 集成面,生产 v1.0.0 无此机制(也无此闪烁)。**

## 3. First-Paint Timeline(运行时实测)

台架:`/tmp/i33`(证据入仓 `docs/evidence/issue33-theme-flash/`)= rc-verify-b7a016d 官方构建产物(css 6,349B + js 258,916B = REV1 报告 BUNDLE_CANDIDATE 口径)+ 可控行为 site-config 服务 + 页面内 16ms 状态采样器。配置值取与默认全维度不同:icon=bubble-sparkle-fill / shape=round / theme=dark。

| 场景 | 时间线(实测) |
|---|---|
| **A 慢配置(delay 2s)** | `t=25ms` present icon=**current** shape=**rounded-square** theme=**light** bg=**rgb(0,0,0)** radius=12px → `t=2040ms` icon=**bubble-sparkle-fill** shape=**round** theme=**dark** bg=**rgb(242,74,0)** radius=**50%**。**闪变窗口 = 配置延迟全长。** |
| **B 瞬时配置(delay 0)** | `t=25ms` 默认黑 → `t=40ms` 配置橙。**即使配置零延迟,仍存在 ≥1 帧默认态**(React useEffect 恒后于首帧绘制)。 |
| **C 配置失败(HTTP 500)** | `t=25ms` 默认黑,**此后零转换**——永久保持默认外观,**非空白**(fail-safe 符合"不得永久空白"红线)。 |
| **D 显式嵌入覆写(launcherIcon=robot-smile/round/light)** | `t=24ms` 即终态(robot-smile/round/light/橙),**零转换**——覆写在渲染 #1 与 #2 同值,抑制闪烁。 |

截图证据:`first-paint-default.png`(黑方"ai"球)vs `after-config.png`(橙圆气泡球)——肉眼可见的主题闪变。

## 4. Reproduction Matrix

| # | 场景 | 行为 | 结论 |
|---|---|---|---|
| 1 | 冷首次加载(site-id 嵌入,配置≠默认) | 默认外观先绘制,配置到达后切换 | **闪烁复现**(窗口=site-config 延迟) |
| 2 | 正常刷新 | 无任何 site-config 缓存,序列完整重演 | **每次刷新都闪** |
| 3 | 重开既有对话 | Widget 无会话持久化/重开路径(conversationId 仅页内存活);同页内开合面板不重拉配置→不闪;新页面加载=场景 1 | 与冷载同路径 |
| 4 | Admin 改主题后 | 无实时推送;下次加载生效,且仍走"默认→新值"序列 | **改后首屏仍闪**(且短暂显示的"默认"正是用户眼中的 old theme) |
| 5 | 慢配置响应 | 场景 A 实测 2s 默认态 | 闪烁窗口≈网络+服务端延迟 |
| 6 | 配置请求失败/403 | 场景 C:永久默认外观,非空白 | fail-safe 保持;**不得在未来修复中变成空白** |
| 7 | 认证/匿名 | Widget 仅匿名路径(/ask 公共,SSE 层站点授权),无认证分支 | N/A |
| 8a | 集成面:MSW 三站(css+js 成对,带 site-id) | 与场景 1 同路径 | **主要受影响面** |
| 8b | 集成面:legacy 公共 widget(无 siteId) | App.tsx:78 `if (!config.siteId) return` → 不拉配置 | 无闪烁(恒默认) |
| 8c | 集成面:显式 data-launcher-* 覆写 | 场景 D:零转换 | 覆写抑制闪烁 |
| 8d | 升级后浏览器缓存旧 widget.js | 旧资产继续按遗留值渲染(site-config 的 launcher_style 回显为其兼容) | 相邻现象:**陈旧资产"旧主题"**,属部署缓存卫生,与页内闪变机理不同,勿混淆 |

## 5. RCA Evidence(代码 × 运行时双链)

**代码链(b7a016d)**
- `widget/src/App.tsx:47` `siteConfig` 初始 `null`;`:78-84` useEffect 异步拉取;`:104-116` 外观消解链 `config.launcherIcon ?? legacyStyleToIcon(config.launcherStyle) ?? siteConfig?.launcher_icon ?? …`,**siteConfig 为 null 时落到客户端默认**;`:206-214` Launcher 恒渲染(`!isOpen`)
- `widget/src/launcher/registry.ts:30-50` 默认值与 fail-safe;auto→matchMedia→light 确定性回退
- `widget/src/styles/widget.css:27,44-84` 黑(current)与品牌橙(新图标)双外观规则,按 data 属性切换
- `widget/src/bootstrap.tsx` 嵌入覆写通道(data-launcher-icon/shape/theme 规范 + launcherStyle 遗留)
- React 语义:`useEffect` 保证在浏览器绘制之后执行 → 渲染 #1 必然可被绘制(场景 B 实证 0 延迟仍有默认帧)

**运行时链**:§3 四场景实测时间线 + 双态截图;产物为官方 REV1 构建,非手工改写;采样器自 `performance.now()≈25ms` 起每 16ms 记录,捕获全部状态迁移。

## 6. Confirmed Root Cause

**RCA_STATUS = PROVEN**(代码语义 + 确定性运行时复现,无未证假设)

> **TRIGGER**:权威外观(site-config 的 launcher_theme/icon/shape)在**首帧绘制之后**才异步到达,且初始必然缺席(siteConfig=null)。
> **MECHANISM**:恒可见的 launcher 在挂载时即以客户端可解析值(嵌入覆写或默认 current/rounded-square/auto)同步渲染并绘制;配置经 useEffect+网络返回后 setState 触发重渲染,data 属性变更驱动 CSS 换肤。无任何持久化使每次页面加载重演。
> **VISIBLE EFFECT**:悬浮球在"默认/旧外观"(黑方)与"服务器配置外观"(如橙圆暗色)之间发生可见切换——即用户报告的首渲染主题闪变;窗口 ≈ site-config 全延迟,冷加载/刷新/Admin 改配置后首屏均复现。

题设示例链(配置不可用→默认可绘制→绘制→替换)与实证机理一致,但本 RCA 以独立证据确立,且额外证实:**零延迟配置仍有 ≥1 默认帧(useEffect 后于绘制)**、**失败路径=默认而非空白**、**显式覆写路径零闪变**。

## 7. Fix Boundary(仅方向,不冻 HOW)

候选方向(可组合,均须过 §9 验收):
- **D1 推迟可绘制性**:配置解析前不绘制最终外观(隐藏/占位/骨架),配置就绪或超时/失败后以确定值呈现。红线:失败/慢路径必须有界时间内可见默认外观,**绝不永久空白**(场景 C 语义必须保留)。
- **D2 上次配置持久化**(localStorage 等)实现首帧即用"上次已知配置"。风险:Admin 改主题后首帧显示**陈旧主题**=另一种"old theme flash",且缓存构成第三个主题权威——须保持服务端可覆盖、每次加载仍回 server SoT 刷新,并定义新鲜度/失效规则。
- **D3 关键 CSS 前置**(宿主页内联服务端生成的主题值)——**天然构成 integration-specific 主题权威,默认违反产品契约**,除非该值由服务端同源生成且仅作为加速镜像;Discovery 不推荐作为首选。

约束栈(未来契约必须全保):server theme SoT;无独立集成主题权威(显式 data-launcher-* 覆写除外);无可见错误首绘;失败不永久空白;匿名/授权行为与 site-config 403 语义;会话/本地化(uiLang 重拉)行为;legacy launcher_style 退役桥与缓存旧 widget 兼容。

**顺带发现(另案建议,不属本 RCA 修复)**:main 线 `primaryColor` 死配置与 `--ask-ai-primary` 无定义变量应在主题体系统一时收编,消除双轨残留。

## 8. Regression Risks(未来实现)

1. 失败/超时路径被改成空白或延迟不可控(违反产品红线)——需显式超时→默认外观的有界保证;
2. 持久化缓存的陈旧主题在 Admin 改配置后长期可见(把闪变换成"错误但持久");
3. legacy 三态:旧嵌入 `data-launcher-style`、缓存旧 widget.js(launcher_style 回显)、无 siteId 公共 widget——任一路径回归;
4. REV1 既有矩阵:T1-T7(主题)/S1-S10(形状)/I1-I8(图标)、Admin 实时预览(iframe srcDoc 复用同一产品)、C2/C3 fail-safe;
5. matchMedia auto 跟随系统(存活期 change 事件)与 D1 推迟绘制的交互;
6. site-config 403/未授权站点的 fail-safe 与新逻辑叠加后的可见性;
7. 本地化:uiLang 热切换触发重拉 → 二次应用窗口不得引入二次闪变。

## 9. Required Acceptance(未来实现的验收底线)

1. **零错误首绘**:site-id 嵌入且配置外观≠默认时,以 rAF 级采样(本报告台架方法)证明**没有任何一帧**以非配置外观被绘制;含慢配置(≥2s)与正常网络两档;
2. **失败有界可见**:配置失败/超时/403 时,launcher 在有界时间(建议 ≤1s 量级,具体由契约定)内以默认外观可见,持续可见、非空白(场景 C 断言自动化);
3. **SoT 单一**:配置到达后最终呈现恒等于服务端值(存在显式嵌入覆写时恒等于覆写值);若引入持久化,首帧陈旧值必须在首次配置响应后被替换,且 Admin 改配置后的下一屏不再显示旧主题超过一个配置往返;
4. **兼容矩阵**:legacy launcher_style、无 siteId、显式覆写、缓存旧 widget 四路径行为与现状逐项一致;
5. **既有回归**:REV1 全部测试矩阵 + site-config 契约形状不变 + Admin 预览不受影响 + 本地化重拉路径无二次闪变;
6. **可观测**:验收附时间线原始数据(同 §3 采样格式)。

## 10. Remaining Unknowns

1. **生产 site-config 延迟分布**(=真实闪变时长分布):生产只读 traces 未记录 site-config 端点延迟,后续可从 nginx/backend 访问日志只读聚合;不影响 RCA 成立。
2. **三站宿主页是否存在自加的 `.ask-ai-*` 覆盖样式**:G001 交接包为纯 css+js 对,未见宿主覆写,但宿主页面 CSS 由外部方持有,建议集成审计时确认(若存在,闪变表现会被宿主样式部分掩盖或放大)。
3. **`/widget/*` 静态资产的浏览器缓存策略**(升级后旧 widget.js 的存活窗口):属部署缓存卫生,与页内闪变机理无关,另案处理。
4. React 并发特性(StrictMode/并发渲染)是否在某些宿主环境改变双渲染时序:台架为生产构建直载,未复现差异;理论影响 ≤1 帧,不改变结论。

## 附录 A:复现台架(入仓 `docs/evidence/issue33-theme-flash/`)

- `server.py`:可控行为 site-config(delay/mode/payload)+ /widget 静态;`index.html`(16ms 采样器+AskAIConfig siteId)、`index-override.html`(显式覆写变体)
- `first-paint-default.png` / `after-config.png`:场景 A 双态截图
- 采样原始输出:
  - A:`[{t:25, current, rounded-square, light, rgb(0,0,0), 12px}, {t:2040, bubble-sparkle-fill, round, dark, rgb(242,74,0), 50%}]`
  - B:`[{t:25, 默认…}, {t:40, 配置…}]`;C:`[{t:25, 默认…}](后续零迁移)`;D:`[{t:24, robot-smile, round, light, rgb(242,74,0)}](单态)`
- 台架全程 /tmp 运行,未触碰任何 worktree/仓库文件;产物为 rc-verify-b7a016d 官方构建。
