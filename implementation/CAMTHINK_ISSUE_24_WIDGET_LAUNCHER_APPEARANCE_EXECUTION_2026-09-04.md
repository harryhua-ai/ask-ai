# Issue #24 — Widget Launcher Appearance 执行报告

- **日期**:2026-09-04
- **执行身份**:Engineering Executor(契约:ASK-AI v1.1 — Issue #24 Execution Contract,AUTHORIZED)
- **基线**:`698e727b743e65a13e5ba3a7b61de07c21ac470b`(Issue#22 已接受候选);实现 worktree `.worktrees/v11-issue24-widget-launcher`,分支 `v1.1/issue24-widget-launcher`
- **STATUS**:CANDIDATE READY(不宣告 FINAL PASS)

## 1. BASELINE_COMMIT / FINAL_COMMIT

```
BASELINE_COMMIT = 698e727b743e65a13e5ba3a7b61de07c21ac470b
FINAL_COMMIT    = 2306118a47a9b85ba843a802b38402c2fd0d84ab(已推 origin,远端核验一致)
DIFF            = 19 files(11 M + 8 A)
```

## 2. CHANGED_FILES

| 类别 | 文件 |
|---|---|
| widget 新增 | `src/launcher/registry.ts`(语义注册表+主题解析/hook)、`src/launcher/Launcher.tsx`(canonical 渲染组件)、`src/launcher/LauncherIcon.tsx`(风格→图标映射)、`src/__tests__/launcher.test.tsx` |
| widget 修改 | `src/App.tsx`(launcher 接线;外观解析优先级)、`src/bootstrap.tsx`(data-launcher-style/theme 配置链)、`src/types.ts`、`src/i18n.ts`(+launcherOpen 文案)、`src/styles/widget.css`(launcher 段 token 化) |
| backend | `db/models.py`(site_experiences 两列)、`services/site_experiences.py`(枚举/归一化;种子不写新列)、`api/routes.py`(site-config 响应增两字段)、`api/admin/widget_appearance.py`(新端点)、`api/admin/router.py`(注册)、`scripts/migrate_add_site_launcher_appearance.py`(新迁移) |
| admin | `pages/WidgetAppearance.tsx`(新页面)、`App.tsx`+`components/Sidebar.tsx`(路由/导航)、`tests/WidgetAppearance.test.tsx` |
| tests | `tests/api/admin/test_widget_appearance.py`、`tests/api/test_site_config_appearance.py` |

## 3. PERSISTENCE_MODEL

- `site_experiences` 加两列:`launcher_style VARCHAR(50) NULL`、`launcher_theme VARCHAR(10) NULL`;
- 迁移 `scripts/migrate_add_site_launcher_appearance.py`:`ADD COLUMN IF NOT EXISTS` ×2,**幂等(测试库连跑两遍实证)、零回填、零既有行改写**;
- **P7 关键语义**:`seed_default_sites` 的 upsert 字段集不含新列 → YAML 重启不覆写 Admin 独立持久值(测试锁定);
- 单一权威:无第二套外观配置系统;NULL = 未配置 → `current|auto`。

## 4. STYLE_MODEL / 5. THEME_MODEL

- `launcher_style ∈ {current, assistant-spark, chat-bubble, orbit-neural}`(PD-1 冻结);语义 id 即公开身份,S7 测试断言无资产路径后缀;SVG 几何/注册表为 HOW。
- `launcher_theme ∈ {auto, light, dark}`;auto 仅以 `matchMedia('(prefers-color-scheme: dark)')` 消解,**不可用/无匹配 → light**,运行时跟随系统 change 事件;显式 light/dark 忽略系统变化。禁止宿主背景采样/类名启发(未实现任何此类逻辑)。
- 解析优先级:`data-launcher-style/theme`(Admin 预览/测试覆写)→ site-config(持久权威,服务端已归一化)→ 兼容默认 `current|auto`;未知/非法值客户端二次 fail-safe(不破坏 bootstrap)。

## 6. ADMIN_PREVIEW_ARCHITECTURE

新「Widget 外观」页(/widget-appearance,Editor+):站点列表 → 风格卡片(4)→ 主题选择(auto/light/dark)→ 宿主背景切换(浅/深页面)→ **实时预览 iframe 加载真实生产产物**(`/widget/ask-ai-widget.css` + `/widget/widget.js`,与站点嵌入同一构建物)以 `srcDoc` + `data-launcher-style/theme` 覆写渲染。隔离与安全:`sandbox="allow-scripts"`(无同源)+ `pointer-events:none`(不可交互 → 零 /ask 流量、零会话创建、零授权触碰);未保存草稿只存在于页面状态(A4 测试锁定);保存 = PUT → 列表刷新(A5/A6)。

## 7. ACCESSIBILITY

- 按钮级 `aria-label`(i18n:打开 Ask AI 助手 / Open the Ask AI assistant)+ `aria-haspopup="dialog"`;图标 alt="" 不重复命名(§11 要求不再以图标为唯一命名机制);
- `:focus-visible` 品牌色轮廓(token 化);
- 触达目标 52×52px 不变;对比度:chat-bubble/orbit 双主题由 fg/surface 令牌对保证,spark 白星对渐变盘;SVG 矢量高 DPI 清晰;
- launcher 无动画;面板 typing 动画现状保留(未扩权)。

## 8-10. BUNDLE

| 产物 | 基线(698e727) | 候选 | Δ | gzip Δ |
|---|---|---|---|---|
| widget.js | 253,411 B(89.28 KB gz) | 257,240 B(90.45 KB gz) | **+3,829 B** | **+1.17 KB** |
| ask-ai-widget.css | 5,059 B(1.55 KB gz) | 5,756 B(1.73 KB gz) | +697 B | +0.18 KB |

零新增外链请求(新风格内联 SVG;`current` 沿用既有 base64 PNG)。

## 11. ACCEPTANCE_MATRIX → 测试映射

- **STYLE**:S1-S4 四风格渲染(renderToString 断言 data-launcher-style + svg/img)✅;S5 缺失→current、S6 非法(logo1.svg/任意串/非字符串)→current、S7 语义 id 稳定无资产后缀 ✅
- **THEME**:T1/T2 显式 ✅;T3/T4 auto×系统双态 ✅;T5 matchMedia 不可用→light ✅;T6 假 MediaQueryList 运行时翻转 + 取订 ✅;T7 显式不订阅 ✅;渲染层 data-ask-ai-theme 落地 ✅
- **PERSISTENCE**:P1/P2 PUT 保存 ✅;P3 重读恢复 ✅;P4 站点间零污染 ✅;P5 未配置行兼容默认 ✅;P6 非法持久值服务端+客户端双重回落 ✅;P7 种子不覆写 Admin 值(真实 seed_default_sites 回归)✅
- **ADMIN**:A1 四卡片 ✅;A2 选中态 aria-pressed+边框 ✅;A3 主题切换进预览 ✅;A4 未保存零写请求 ✅;A5 保存 PUT 载荷 ✅;A6 重载显示已保存 ✅;A7 srcDoc 引用真实 /widget 产物(css+js 成对)✅
- **WIDGET 行为**:W2/W3 开合路径零变化(Launcher 仅替换原 button 渲染,onClick=openPanel 原逻辑);W5/W6 starters/welcome/language 链未触碰(既有测试全绿);W7 legacy 无 siteId 路径不变 ✅;W8 site-config 失败 fail-safe(既有 catch 回退 + 外观回落默认)✅
- **SECURITY/ACCESS**:G1/G2 origin 授权回归全绿 + 新增 403 用例断言外观字段不出现 ✅;G3 无通配符引入(diff 无 CORS/allowed_origins 改动)✅;G4 外观字段不参与 resolve_site ✅;G5 预览 iframe sandbox + pointer-events none,不构成绕过 ✅

## 12. TEST_RESULTS

| 层 | 结果 |
|---|---|
| widget vitest | **88 passed**(新增 launcher 16) |
| admin vitest | **260 passed**(新增 WidgetAppearance 5) |
| admin build(tsc -b + vite) | 绿 |
| widget production build | 绿 |
| 后端 focused(appearance + site-config + site_routes + multilingual) | 26 passed |
| 迁移幂等 | 测试库连跑两遍 ✅ |
| 全量离线回归 | **1612 passed / 0 failed / 6 skipped**(47.7s;较 698e727 基线 1603 净增 9) |

## 13. SCOPE_AUDIT

`git diff --name-only 698e727` 全集 = §2 表;grep 审计 `connectors/|pipeline/|source_discovery|repo_discovery|website_discovery|source_center|sync_runs|source_lifecycle|source_deletion|scripts/sync` → **零命中**。#22 语义、摄取链、同步面、allowed-origin/CORS 策略、站点身份解析全部零触碰;`admin/src/types/api.ts` 未被本任务修改(#22 FROZEN INTERFACE 面实际未相交——Widget 外观类型放 widget/src/types.ts 与页面内联)。

## 14. COMPATIBILITY

- 旧站点(无 launcher 列值)→ `current|auto` = 升级零外观变化;legacy(无 siteId)widget 不拉 site-config → 恒 current;
- 旧 widget + 新后端:响应多两个字段被旧客户端忽略 ✅;新 widget + 旧后端:字段缺省 → 默认 ✅;
- 非法持久值:服务端归一化回落(P6)+ 客户端二次 fail-safe。

## 15. KNOWN_LIMITATIONS

1. V1 主题化范围仅 launcher;聊天面板仍为既有浅色(深色系统下开面板后观感切换)——面板 token 化建议另立(Discovery 即此建议,契约未授权扩围);
2. `current` 保留 PNG 位图(逐像素兼容优先);重绘为 SVG 属后续视觉债;
3. Admin 风格卡片为色点/文案 chip(导航 affordance),视觉真相由 canonical iframe 预览承担(避免复刻 SVG 漂移);
4. auto 只跟随系统主题:手工深色页面 + 浅色系统 → launcher 浅色(PD-4 冻结的确定性语义);
5. 预览 iframe 需 Admin 可达 /widget 产物(与生产同源部署;本地 dev 须 widget build 后可用)。

## 16. PRODUCTION_MUTATIONS

**NONE**。零生产接触;迁移仅对本地隔离测试库执行(两遍,幂等实证)。

## 17. 交付锚点

```
BRANCH        = v1.1/issue24-widget-launcher
FINAL_COMMIT  = 2306118a47a9b85ba843a802b38402c2fd0d84ab(origin 已核验)
REPORT_PATH   = docs/implementation/CAMTHINK_ISSUE_24_WIDGET_LAUNCHER_APPEARANCE_EXECUTION_2026-09-04.md
REPORT_COMMIT = 见 docs 本地仓(本文件所在提交)
```
