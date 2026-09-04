# CAMTHINK V1 — Issue #24 Widget Launcher Appearance — REV1 Execution Report

- 日期:2026-09-04
- 角色:Engineering Executor
- STATUS:**CANDIDATE READY**(等 Planner 独立评审;Executor 不宣告 FINAL PASS)
- 分支:`v1.1/issue24-launcher-design-rev1`(隔离 worktree `.worktrees/v11-issue24-launcher-design-rev1`)
- 主仓候选提交:**b7a016d**(基线 2306118 之上的单提交 delta)
- 集成文档(docs 仓):`docs/integration/WIDGET_INTEGRATION.md` @ **c13186c**
- 本报告(docs 仓):`docs/implementation/CAMTHINK_ISSUE_24_WIDGET_LAUNCHER_APPEARANCE_REV1_2026-09-04.md`
- **PRODUCTION_MUTATIONS = NONE**(零生产触碰;未合并 main;未部署)

---

## BASELINE_COMMIT

`2306118a47a9b85ba843a802b38402c2fd0d84ab`(Issue #24 REV0 已接受工程候选;v1.1 RC 流程按 §32 对此 SHA 暂停,由本 REV1 候选接替)

## AUTHORITATIVE_DESIGN_REFERENCE

`/Users/harryhua/Downloads/buttons.html`(Product Owner 供给,实现前已直接检视):
- 四个 SVG 设计逐路径采用:**bot-sparkle.svg**(24×24 描边机器人+星光)、**bubble-sparkle-fill.svg**(24×24 填充气泡+星光)、**gravity-ui--face-robot-smile.svg**(16×16 机器人笑脸)、**bubble-sparkle.svg**(48×48 描边气泡+星光,含 stroke-width 7.8 + translate/scale 变换子路径);
- 设计 token 采用:品牌橙 `#f24a00` 表面、白色图标、内嵌高光 `inset 0 1px 1px rgba(255,255,255,.3)`、内嵌深度 `inset 0 -6px 12px rgba(0,0,0,.15)`、外发光 `0 8px 24px -6px rgba(194,59,0,.6)`、hover 仅增强辉光无位移/缩放(`0 10px 30px -4px rgba(217,66,0,.85)`)、focus-visible 4px 光环 `0 0 0 4px rgba(255,106,31,.4)`;
- 72×72 展示网格按契约**不**作为生产尺寸;生产保持 52px,图标按设计占比 40px@72 → **29px@52**,圆角 20px@72 → 等比 **14px@52**;
- 演示聊天面板/X 切换动画**未采用**(§12/§13:不重设计 panel 归属;动画非正确性必需,零动画故 prefers-reduced-motion 无需处理)。

## CONTRACT_AMENDMENT

执行契约 = REV1 Delta(2306118 基线,icon×shape×theme)+ Amendment #2(统一外观语义/正常集成模型/高级嵌入覆盖/集成文档/契约版本 1.1/向后兼容)。两者全部落实;Amendment 验收 D1-D9 见下。

## FINAL_COMMIT

主仓:**b7a016d**(`v1.1/issue24-launcher-design-rev1`)
docs 仓:**c13186c**(集成文档)+ 本报告提交(见 git log)

## CHANGED_FILES

主仓 17 文件(+922/−314):
- `backend/db/models.py` — SiteExperience 增 `launcher_icon` VARCHAR(50) NULL / `launcher_shape` VARCHAR(20) NULL
- `scripts/migrate_add_site_launcher_icon_shape.py` — 新迁移(幂等加列、零回填)
- `backend/services/site_experiences.py` — LAUNCHER_ICONS/LAUNCHER_SHAPES 枚举、normalize_launcher_icon/shape、遗留桥 legacy_style_to_icon、ResolvedSite 统一外观字段、resolve_site 有效值解析
- `backend/api/routes.py` — site-config 响应增 launcher_icon/launcher_shape;launcher_style 降级遗留回显
- `backend/api/admin/widget_appearance.py` — GET 归一化有效值+legacy 回显;PUT 统一三字段封闭枚举 422
- `widget/src/types.ts` — LauncherIcon/LauncherShape 类型;WidgetConfig.launcherIcon/Shape;SiteExperienceConfig.launcher_icon/shape;launcherStyle 全链 @deprecated
- `widget/src/launcher/registry.ts` — 图标/形状注册表+解析器+遗留桥;主题机制原样保留
- `widget/src/launcher/LauncherIcon.tsx` — 四个权威 SVG 组件(逐路径)+ current PNG
- `widget/src/launcher/Launcher.tsx` — data-launcher-icon/shape + data-ask-ai-theme
- `widget/src/bootstrap.tsx` — data-launcher-icon/shape 规范通道(同源内压过遗留 data-launcher-style)
- `widget/src/App.tsx` — 覆盖链消解(显式嵌入 > 遗留嵌入 > site-config > 遗留 site 值 > 默认)
- `widget/src/styles/widget.css` — 权威设计 token(非 current 规则;current 基线规则零改动)
- `admin/src/pages/WidgetAppearance.tsx` — 图标视觉卡片(canonical mini-iframe)+形状/主题/背景+统一三字段保存
- `widget/src/__tests__/launcher.test.tsx` / `admin/tests/WidgetAppearance.test.tsx` / `tests/api/admin/test_widget_appearance.py` / `tests/api/test_site_config_appearance.py` — REV1 矩阵(语义更新,保留原行为保护)

**零触碰(边界审计)**:#22 语义(source_discovery/repo_discovery/website_discovery/admin types/api.ts)、connectors/safety、sync/RAG/LLM/检索/引用、allowed_origins/resolve_site 授权语义、CORS、config/sites.yaml、生产配置/数据。`git diff --stat 2306118..b7a016d` 全部落在 EXPECTED+SUPPORTING 面。

## REV0_COMPATIBILITY_STRATEGY

**冻结遗留列 + 确定性退役桥**(零数据迁移、零静默改观):
1. `launcher_style` 列原地冻结,REV1 写路径永不触碰 → 回滚到 REV0/旧应用时按遗留值渲染,行为保真(C6);
2. 有效图标解析:`launcher_icon` 列优先;否则遗留 `launcher_style` 经 `legacy_style_to_icon` 桥接——**任何**非空遗留值(含 current 与三个退役风格)→ `current`;未设置 → 走默认链;
3. REV0 发明的三个风格 id(assistant-spark/chat-bubble/orbit-neural)**不静默映射**到新图稿(§6E:无 Admin 显式选择不得获得新设计),退役为兼容身份 `current`;Admin UI 对此类站点显式提示「已退役,请重新选择」;
4. site-config 响应同时携带 `launcher_icon/launcher_shape/launcher_theme`(canonical)与 `launcher_style`(遗留回显,已归一)→ 缓存中的旧 Widget 按遗留值渲染,不崩溃;
5. 缺失/非法值全维 fail-safe:icon→current、shape→rounded-square、theme→auto(C2/C3/D 约束)。

## PERSISTENCE_MODEL

- `site_experiences` 增两 nullable 列(launcher_icon/launcher_shape);launcher_theme 沿用 REV0 列;launcher_style 冻结遗留;
- 新迁移 `scripts/migrate_add_site_launcher_icon_shape.py`:仅 `ADD COLUMN IF NOT EXISTS` ×2,零回填零改行;测试库实测连续执行 ×2 幂等通过(C7);
- 种子(seed_default_sites)不写任何外观列 → Admin 值跨 YAML 重启存续(P7 测试保持);
- 生产前置(未来授权窗口内):REV0 迁移(如未跑)→ 本迁移;顺序无依赖(IF NOT EXISTS)。

## ICON_MODEL

`launcher_icon ∈ current | bot-sparkle | bubble-sparkle-fill | robot-smile | bubble-sparkle-outline`(I1-I8 全过;未知→current;语义 id 无实现后缀)。

## SHAPE_MODEL

`launcher_shape ∈ round | rounded-square`(S1-S10 全过);独立于 icon 的配置维度(无组合硬编码 id);round=50% 圆角,rounded-square=14px@52(20px@72 等比);`current` 形状由遗留渲染器拥有(12px 圆角方逐像素兼容),形状规则以 `:not([data-launcher-icon="current"])` 严格隔离。

## THEME_MODEL

`launcher_theme ∈ auto | light | dark`,与 REV0 语义逐字不变(T1-T7 全过);auto 仅 matchMedia('(prefers-color-scheme: dark)'),不可用→light,跟随系统变化;显式值忽略系统变化;无宿主主题推断。REV1 delta 仅作用于**呈现**:非 current 图标的阴影/受光边按主题微调,品牌橙两域可辨(T8 视觉验证)。

## SVG_IMPLEMENTATION

- 四个权威 SVG 逐路径内联为 React 组件(几何零近似改画;I6 测试断言各设计路径签名);
- `current` 保持打包 PNG(兼容);全部零外链请求(I7:新图标无 `<img>`、current 无 http src);
- JSX 化属性映射(stroke-width→strokeWidth 等);48-viewBox 描边设计的 stroke-width 7.8 + translate/scale 变换子路径原样保留。

## ADMIN_UX

「Widget 外观」页(REV0 信息架构延续):站点体验列表(显示有效 icon·shape·theme)→ **图标样式** 5 张视觉卡片(current+4 新;卡片即真实 Widget 产物 mini-iframe,随形状/主题草稿即时联动)→ **按钮形状**(圆形/圆角方形)→ **主题**(自动/浅色/深色)→ **预览页面背景**(独立于主题)→ 大幅实时预览 → 保存。UI 全人类可读标签,**零 SVG 文件名/语义 id 泄漏**(A10 测试断言)。退役遗留选择显式提示。角色门禁不变(admin/editor;viewer 403 测试保持)。

## LIVE_PREVIEW

原理同 REV0:iframe srcDoc 加载真实生产产物(/widget/ask-ai-widget.css + /widget/widget.js,css+js 成对),data-launcher-* 覆写草稿;未保存即时可见、保存是唯一持久边界(A4/A6/A7)、iframe pointer-events:none + sandbox=allow-scripts 不可交互、零 /ask/会话/反馈/上传流量(G5 语义保持);预览背景切换独立于主题(A5)。

## ACCESSIBILITY

按钮级可访问名(aria-label,i18n launcherOpen)+ aria-haspopup;装饰 SVG aria-hidden="true";current 的 img alt="";focus-visible:current 沿用 2px 橙描边 outline,新图标用权威设计 4px 光环(规则置于末尾且特异性≥hover,键盘焦点+悬停并发时光环可见);52px 触达目标不变;高 DPI 矢量天然清晰;本版未引入动画(见 DESIGN_REFERENCE 节)。

## VISUAL_ACCEPTANCE

真实浏览器(Playwright+Chromium)对 REV1 生产构建产物截图验证:
- **8 组合(4 icon × 2 shape)× 明/暗背景 = 16 张**,52px 生产尺寸,全部正确渲染:图标居中、描边/填充清晰、内边距与形状平衡、品牌橙一致、阴影自然、小尺寸可辨(contact sheet 审查通过);
- 移动视口 375×667 ✓(bot-sparkle rounded-square,移动位 bottom/right 16px 正确);
- 混乱/繁忙背景 ✓(bubble-sparkle-fill round 于条纹+渐变背景上清晰可辨);
- `current` 兼容:明/暗背景与原版外观一致(黑色圆角方 ai 徽标,逐像素兼容)✓;
- hover/focus 为状态样式:CSS 采用权威设计 token(见上),未做交互态截图,以 CSS 规则+设计对照为证。

## BUNDLE_BASELINE

2306118 生产构建(detached worktree 同流程构建):JS raw **257,243 B**(vite gzip 90.45 kB);CSS **5,756 B**(gzip 1.73 kB)。

## BUNDLE_CANDIDATE

b7a016d 生产构建:JS raw **258,916 B**(gzip 实测 90,573 B;vite 91.21 kB);CSS **6,349 B**(gzip 1,860 B / vite 1.84 kB)。

## BUNDLE_DELTA

- JS raw:**+1,673 B(+0.65%)**;JS gzip:**+0.76 kB**(vite 口径)
- CSS raw:+593 B;CSS gzip:+~0.11 kB
- 新增外链请求:**0**(四个矢量图标全内联)
- 结论:有界增量,符合契约预期;无异常膨胀需调查。

## TEST_RESULTS

| 层 | 结果 |
|---|---|
| widget vitest | **110 passed**(REV0 88 → REV1 矩阵:I1-I8/S1-S10/T1-T7/a11y/覆盖链/遗留桥;REV0 语义更新保留原行为保护) |
| admin vitest | **264 passed**(REV0 260;A1-A10 REV1 矩阵,含 A10 无实现术语泄漏) |
| admin/widget 生产构建 | tsc -b + vite 全绿 |
| 后端 focused | **10 passed**(appearance 端点 5 + site-config 5) |
| 迁移幂等 | 测试库连续执行 ×2 通过(C7) |

## FULL_REGRESSION

全量离线(HF_HUB_OFFLINE=1 + models 软链 + 隔离测试库):**1613 passed / 0 failed / 6 skipped**(40.28s)= 基线 1612 + 净增 1 个后端测试;零回归。
(勘误:过程中一次 1609+4 errors 系 worktree 缺 `models` 软链的既有环境约定所致,与代码无关;软链后同环境 22/22 embedder 绿、全量绿。)

## SCOPE_AUDIT

CLEAN——见 CHANGED_FILES 节末。重点:#22 冻结接口 `admin/src/types/api.ts` 零改动;connectors/safety.py、sync、RAG/LLM、授权/CORS、种子 YAML、生产配置/数据零触碰。

## MIGRATION_SAFETY

加列幂等(IF NOT EXISTS)、零回填、launcher_style 零触碰;旧应用回滚行为确定(遗留列原值渲染);未授权前不跑生产。

## KNOWN_LIMITATIONS

1. **V1 主题作用域 = launcher**:auto 消解仅驱动 launcher(data-ask-ai-theme);ChatPanel 主题化不在本契约(沿用 REV0 边界);
2. **形状对 current 不生效**(契约 §7 允许:遗留渲染器拥有形状;UI 有提示文案);
3. **开启态图标切换/X 动画未采用**:与既有 panel 归属不兼容,契约明示不要求;ChatPanel 内建关闭按钮语义保持;
4. **退役风格的 Admin 提示是静态文案**:基于 legacy_launcher_style 回显,保存任一新外观后自然消失;
5. **预览卡片 iframe 依赖 /widget 产物可达**:Admin 与后端同源部署前提下成立(与 REV0 预览同一约束);
6. **site-config 的 launcher_style 遗留回显**为过渡兼容面,计划后续契约版本移除(已标 deprecated)。

## AMENDMENT #2 ACCEPTANCE(D1-D9)

- D1 清洁新站集成仅凭指南完成:✓ Quick Start=css+js 成对+data-api-url+data-site-id(与 runtime 逐项核对);
- D2 存量升级路径显式文档化:✓ Updating Existing Integrations 节(v1.0.x 零改动);
- D3 集中改外观无需改客户网页:✓ 架构即如此(site-config 承载),文档明示;
- D4 高级覆盖文档化:✓ data-launcher-icon/shape/theme+三通道(script/preset/global);
- D5 icon/shape/theme 术语跨 Widget/Admin/API/文档一致:✓ 全链统一 LAUNCHER_ICONS/SHAPES/THEMES;
- D6 遗留术语不再作为首选 API:✓ Compatibility/Deprecation 表格式化降级说明;
- D7 文档示例=真实 runtime 行为:✓ 逐属性对照 bootstrap/App/registry 实现核验(含默认值、枚举、优先级、fail-safe);
- D8 安全语义不弱化不误述:✓ siteId=标识非凭证、Origin 精确授权、外观值零授权语义;
- D9 文档已提交并入报告:✓ docs 仓 c13186c。

## PRODUCTION_MUTATIONS

**NONE**——零生产触碰、零合并、零部署。v1.1 RC 验证按 §32 保持暂停,待 Planner 对 b7a016d 独立评审 FINAL PASS 后恢复。
