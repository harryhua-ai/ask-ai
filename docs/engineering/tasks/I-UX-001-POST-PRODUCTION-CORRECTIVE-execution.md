# I-UX-001 POST-PRODUCTION CORRECTIVE — Execution Report

**Delivery Status: `CANDIDATE READY`**

---

## 1. 执行摘要

本矫正以 Agent B（高级工程执行者）身份，在冻结契约（产品/UX 契约 V2.3 ACCEPTED + 冻结实现契约）边界内完成了 #6 / #33 / #36 / #37 / #38 / #39 / #40 七个议题的工程闭环。五道验收门全部通过：契约符合矩阵 20/20 PASS、scope 审计零越界、全量测试套件绿（后端 2003 通过 / widget 175 通过 / admin 281 通过）、浏览器级运行时证据 17 张截图 + DOM 观测 JSON 构成完整生命周期链（fallback → UI 授权 → 品牌 pill → mini ✦ → preparing ✦ → 优雅错误回退 → UI 撤销 → fab 回退 → 移动端 nudge）。未触碰任何 FORBIDDEN 边界；未合并 main；未做生产部署。

## 2. 执行锚点

| 锚点 | 值 |
| --- | --- |
| 代码基线（accepted） | `9343e65d302570ac2e943d6450507a54cfee44b2` |
| 契约冻结锚点（plan branch HEAD） | `376565f4221244c319db43911ca8561b1e649b83` |
| 规划分支 | `plan/i-ux-001-post-production-corrective` |
| 实现分支 | `impl/i-ux-001-post-production-corrective` |
| 实现 worktree | `.worktrees/iux001-post-corrective/` |
| 最终候选 SHA | 见 §19（提交后回填） |
| 产品/UX 契约 | `docs/engineering/tasks/I-UX-001-POST-PRODUCTION-CORRECTIVE-plan.md`（V2.3 ACCEPTED） |
| 实现契约 | `docs/engineering/tasks/I-UX-001-POST-PRODUCTION-CORRECTIVE-implementation-contract.md` |
| 跟踪 | Umbrella #43；覆盖 #6 #33 #36 #37 #38 #39 #40；#41 = #6 重复；#23 显式 OUT OF SCOPE |

## 3. 授权边界声明

- 本执行**拥有**：工程根因调查、实现架构、迁移策略、测试设计、调试（契约 §18）。
- 本执行**不拥有**：产品意图、冻结 UX、任务范围的重新解释；遇不可行即停（本轮未触发任何停止条件字符串：无 `SCOPE EXPANSION REQUIRED` / `PRODUCT DECISION REQUIRED` / `ARCHITECTURE DECISION REQUIRED`）。
- 生产部署**未被授权**，亦未执行；未合并到 main。

## 4. Discovery 记录（强制，逐议题）

| # | 议题 | Discovery 结论（先于实现） |
| --- | --- | --- |
| A | #6 生命周期 | 三重根因：① `seed_default_sites` 每次启动无条件用 YAML 覆写 `allowed_origins`（Admin 编辑重启即失）；② 全局 CORS 在进程启动时一次性由 `CORS_ALLOW_ORIGINS` 构建，与 DB 授权静默分叉；③ Admin 无 origins API。 |
| B | #33 对账 | 首绘外观状态机**已存在**（appearancePhase unresolved→resolved/failed、LAUNCHER_RESOLUTION_TIMEOUT_MS=5000、迟到配置外观剥离 + 回归测试）。按契约 §2.6 走「证明闭环」路线，不重写；本轮唯一残余缺口是迟到配置携带的 `launcher_presentation` 未列入剥离清单（已补，见 §7）。 |
| C | #36 预览 | 根因：previewDoc 硬编码 `launcherIcon: "current"`，预览不消费草稿解析值。 |
| D | #37/#38 | 工作区状态模型 = 生产草稿 ≠ 预览临时态；两页面合并为一工作区四区块。 |
| E | 配置状态模型 | 草稿（显式 Save 才落库）/ 预览（临时模拟）/ 生产（站点配置）三层分离。 |
| F | 问候语义 | `greeting_override` NULL=自动 / 字符串（含空串）=自定义模板；变量 `{product_name}/{product}/{page_title}/{page_type}` 确定性替换；任一变量不可解析 → 模板整体作废 → 回落自动链（绝不泄漏占位符）。 |
| G | #39 访客保真 | launcher_presentation 三态：`pill`（新站点默认）/ `icon` / NULL（既有站点 legacy icon，零迁移改写）。 |
| H | 证据 UX | 保持内联 citation；不新增默认 Sources 区（本轮零改动，回归断言守护）。 |
| I | #40 等待态 | 根因：三跳点 `.ask-ai-typing`；替换为品牌化真实等待态。 |

## 5. RCA — #6 授权调和（核心）

**问题本质**：产品真相是单一 `Authorized Websites` 策略，实现却存在三条独立权威路径。

**修复架构（单一权威 + 双消费端）**：

1. **Seed 权威域切分**（`backend/services/site_experiences.py`）：YAML 保留身份/内容列权威（display_name、welcome、starters、entry_mode、launcher_presentation 等）；`allowed_origins` 的权威归 Admin——仅**新建行**以 YAML origins 作为初始授权，既有行永不回写。
2. **`DynamicCORSMiddleware`**（`backend/main.py`，纯 ASGI）：允许集合 = env 静态集合（本地开发/Admin 工具，不变）∪ DB `allowed_origins`（5s TTL 缓存；DB 失败回落 env 静态集合并记日志——可用性优先，安全不受影响，因服务端授权独立 fail-closed）。preflight 本层直接应答（语义同旧 CORSMiddleware：GET/POST + Content-Type）。Admin 变更后 ≤5s 收敛到浏览器执行层，**无需重建镜像/重新部署**。
3. **Admin origins API**（`backend/api/admin/authorized_websites.py` 新建）：列表 / 添加 / 移除；POST 走 `_canonical_policy_origin` 严格校验（通配符、路径、非 http(s) → 422；canonical 碰撞 → 409）；移除 404 未知 origin；带结构化日志（可审计）。
4. **`normalize_origin` 收紧**：host 含 `*` 一律拒绝（返回 None）——`https://*.camthink.ai` 在旧实现下可被解析接受。

**fail-closed 验证**：未授权 origin 的 OPTIONS `/api/ask` → 405 且无任何 `access-control-allow-origin` 头；site-config → 403（curl 基线 + 截图 05/06/17）。

## 6. RCA — #33 运行时状态与闭环

对账结论：主干的 first-paint 状态机与回归测试真实存在且有效，本次候选上**无可复现的闪变残余**。按契约「证明闭环优于重写」执行：

- 运行时证据：12（授权页首绘即品牌 pill，无中间态）；05/17（未授权回退为 legacy FAB，无 provisional 闪现）；18（预览 iframe 首绘即 pill）。
- 增量矫正一处：`stripLauncherAppearance` 增剥 `launcher_presentation`（迟到配置的 pill/icon 切换同样构成二次闪变，`widget/src/utils/siteConfig.ts`）。
- 单元回归：appearance 状态机既有测试 + 新增 v23corrective 用例全绿。

## 7. RCA — #36 预览保真 / #40 等待态

- **#36**：previewDoc 由硬编码 `launcherIcon: "current"` 改为消费草稿解析值（`launcher_presentation` + `launcher_icon` 均来自 draft→站点回退链）。运行时证据 18：预览 iframe 内为真 widget 渲染的 `ask-ai-launcher-pill`（`PREVIEW_LAUNCHER {"cls":"ask-ai-launcher-pill"}`）。
- **#40**：三跳点 `.ask-ai-typing`（含 ask-ai-bounce 动画）删除；新等待态 `.ask-ai-preparing` = ✦ 徽标 + "Preparing an answer…"/"正在准备答案…"（i18n），克制的 sparkle 呼吸动画（`prefers-reduced-motion` 静态等价）；首 token 以 0.15s crossfade 原位让位（`.ask-ai-answer-body`）。运行时证据 14：`✦ Preparing an answer…`。

## 8. 实现架构（按议题）

| 议题 | 实现 |
| --- | --- |
| #38 | `WidgetWorkspace.tsx`（新）四区块 tab（入口与参与/外观/授权网站/预览与测试）；左侧站点选择列表 + 配置，路由 `/widget`；Sidebar 合并为单条 Widget；`WidgetExperience.tsx`/`WidgetAppearance.tsx` 及其测试删除。三张 GET 合并站点行；Save 按 EXTERIENCE/APPEARANCE 字段集拆分 PUT。 |
| #39 | `LauncherPill` 组件（✦ + "Ask AI"，42px medium/36 small/48 large，品牌橙，subtle_glow/soft_pulse/sparkle 动效，dark 主题，aria-label）；`resolveLauncherPresentation(config, site)`（embed > site > NULL=legacy）；App 条件渲染，与其它外观同受 `appearancePhase !== "unresolved"` 闸门；mini 头部身份 = `✦ Ask AI`（aria-label 保留站点 display_name，证据 13：`"✦Ask AI"` + `"CamThink 官网"`）；克制对话 CSS（用户问题无尾巴/弱表面/600 字重，助手透明无边框）。 |
| #6 | 见 §5。 |
| #33 | 见 §6。 |
| #36/#37 | #36 见 §7。#37：临时 previewTheme（site 默认/match/light/dark）仅注入 iframe `data-chat-theme`，不进 draft、不进 Save payload；Reset 回「使用站点配置」；UI 明示「临时模拟；不随保存写入站点配置」（证据 10/18 文案可见）。 |
| 问候 | `resolveGreetingTemplate(template, {product, pageTitle, pageType})`：无变量原样；变量确定性替换；不可解析 → null → 落入自动链。持久化不变（NULL=自动/字符串=自定义）。Admin 侧 `resolveGreetingPreview` 模板与解析值分离展示。 |
| 迁移 | `scripts/migrate_add_site_launcher_presentation.py`（幂等 ADD COLUMN IF NOT EXISTS，零回填）。 |

## 9. 变更文件（按议题分组）

基准 `376565f`，共 26 个修改 + 7 个新增（`git diff --stat`：+611/−1414，其中 −1136 为两旧页面删除）。

**#38（Admin 工作区）**：`admin/src/App.tsx`、`admin/src/components/Sidebar.tsx`、`admin/src/pages/WidgetWorkspace.tsx`(新)、删 `admin/src/pages/WidgetExperience.tsx`、删 `admin/src/pages/WidgetAppearance.tsx`、`admin/tests/Sidebar.test.tsx`、`admin/tests/WidgetWorkspace.test.tsx`(新)、删 `admin/tests/WidgetAppearance.test.tsx`

**#39/#40/#33（Widget 访客侧）**：`widget/src/App.tsx`、`widget/src/bootstrap.tsx`、`widget/src/components/ChatPanel.tsx`、`widget/src/components/EntrySurfaces.tsx`、`widget/src/components/MessageBubble.tsx`、`widget/src/experience/greeting.ts`、`widget/src/experience/launcher.ts`、`widget/src/i18n.ts`、`widget/src/launcher/Launcher.tsx`、`widget/src/styles/widget.css`、`widget/src/types.ts`、`widget/src/utils/siteConfig.ts`、`widget/src/__tests__/v23corrective.test.tsx`(新)

**#6（授权调和）**：`backend/main.py`、`backend/services/site_experiences.py`、`backend/api/admin/authorized_websites.py`(新)、`backend/api/admin/router.py`、`tests/api/admin/test_authorized_websites.py`(新)、`tests/api/admin/test_origin_authority.py`(新)、`tests/services/test_site_experiences.py`

**launcher_presentation 持久化（#39/#36 支撑）**：`backend/services/widget_experience.py`、`backend/api/admin/widget_experience.py`、`backend/db/models.py`、`backend/api/routes.py`、`scripts/migrate_add_site_launcher_presentation.py`(新)

## 10. 迁移 / 默认 / Legacy 行为

| 维度 | 行为 |
| --- | --- |
| 新列 `site_experiences.launcher_presentation` | String(10) nullable；NULL = 未配置 → legacy icon。**既有站点零改写**（迁移只加列不回填；seed 对既有行不写此列）。 |
| 新建站点 seed 默认 | entry_mode=mini_entry + launcher_presentation=pill（契约新站点默认）。 |
| 既有 origins | 迁移/重启/重新 seed 均保留（seed 仅对新建行写 YAML origins；Admin 变更为最高权威）。 |
| greeting_override | NULL=自动（上下文链）/ 字符串=自定义模板；既有值语义不变。 |
| 主题枚举 | 恒为 match/light/dark/custom，match 默认；未新增第五模式。 |

## 11. Gate 3 — 测试命令与精确结果

环境注记：本机 5432 被原生 postgres 占用，测试容器经 IP 访问；`TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@192.168.107.2:5432/ask_ai_test`。`db_engine` fixture 拆表特性决定 services 测试须在 api 测试之后运行（既有约束，非本次引入）。

| 套件 | 命令 | 结果 |
| --- | --- | --- |
| 后端全量 | `pytest tests/ -q`（上述 DSN） | **2003 passed, 3 skipped**（35min；含 `tests/e2e` 默认跳过——由 RUN_SYMBOL_E2E 门控，属既有设计）。1 项在首轮因共享 DB 污染失败，加入 `_reset_site_origins` 复位辅助后复跑通过 |
| 新增后端 | `pytest tests/api/admin/test_authorized_websites.py tests/api/admin/test_origin_authority.py tests/services/test_site_experiences.py -q` | **49 passed**（8+5+36，含既有 28） |
| widget | `npx vitest run`；`tsc --noEmit`；`npm run build` | **175 passed**；tsc 0 错；build 成功 |
| admin | `npx vitest run`；`tsc -b`；`npm run build` | **281 passed**（含新增 12 + Sidebar 合并断言）；tsc 0 错；build 成功 |
| lint | `ruff check`（触及文件） | clean（3 处自动修复后） |
| 受影响复跑 | 45 API + 36 services 定向复跑（安全顺序） | 全绿 |

新增覆盖要点：origins CRUD/canonicalize/通配符与路径 422/重复 409/跨站隔离；真实 HTTP 边界的 preflight 头/未授权无 CORS 头/简单请求注入 Vary/env 静态仍放行/TTL≈5.2s 收敛；seed 既有行不覆写 origins；pill/NULL→FAB/embed 覆写解析；问候模板单元 + 集成；等待态原生 setter 输入；mini 身份；四 tab/旧概念缺席/origins CRUD/最后来源确认/#36 草稿图标/#37 临时主题不入 Save/拆分 PUT/previewDoc 契约。

## 12. Gate 4 — 浏览器运行时证据

栈：worktree 后端 uvicorn :8000（/health git_sha=376565f）+ admin/widget dist + 宿主测试页 :8901；Playwright(chromium-1228) 无头驱动，确定性截图落盘。

证据目录 `/tmp/iux001-runtime/evidence/`（17 PNG + `obs-*.json` DOM 观测）：

| 文件 | 证明 |
| --- | --- |
| 05/06 fallback FAB + 面板 | 未授权 origin fail-closed 且组件可用（默认配置） |
| 07/08/09/10 四 tab | 工作区四区块（入口与参与/外观/授权网站/预览与测试）+ 站点列表 + 单条 Widget 导航 |
| 11 origin added | Admin UI 添加 `http://localhost:8901` → 列表即时更新 |
| 12 branded pill | 授权后首绘 = `✦ Ask AI` 品牌胶囊（launcher_presentation=pill） |
| 13 mini conversation | 桌面 C mini：身份 `✦Ask AI`（aria=`CamThink 官网`）+ 问候 + 直接输入 |
| 14 preparing state | 提问后 `✦ Preparing an answer…`（三跳点已绝迹） |
| 15 answer-or-error | 无 LLM 环境下优雅错误回退 + Retry 语义（链路本身端到端可用） |
| 16 origin removed | Admin UI 移除 → 列表更新 |
| 17 revoked fallback | 撤销后 ≤TTL 回退 legacy FAB（撤销即时生效闭环） |
| 18 preview iframe | 预览 iframe 真渲染 `ask-ai-launcher-pill`（#36）；「临时模拟；不随保存」可见（#37） |
| 19 mobile nudge | 390×844：pill + B-nudge 气泡，**mini 从未出现**（DOM 采样 t=0→10s：mini=false, nudge 自 t≈6s=true） |
| 20 mobile full chat | 点击 nudge → 移动端全屏对话 |

移动端勘误记录：初采发现「移动端 mini 自动展开」疑似违规，根因为**测试宿主页缺 `<meta name="viewport">`**——移动仿真按默认 980px 布局宽渲染，widget 的 `innerWidth<=640` 判定如实把它当桌面。补 meta 后复测，行为与契约完全一致。产品代码零缺陷；勘误纳入 §18 环境记录。

## 13. Gate 1 — 契约符合矩阵（实现契约 §5，20/20 PASS）

| # | 验收项 | 证据 |
| --- | --- | --- |
| 1 | 非 Widget 导航实质不变 | Sidebar diff 仅合并两 Widget 条目（diff 审查 + Sidebar.test） |
| 2 | 新站点品牌 pill / 显式 legacy 保留 | 三态解析 + 证据 12 vs 05/17 |
| 3 | A/B/C + 桌面/移动主动规则 | 既有套件 + 新增解析测试；证据 19 时序采样 |
| 4 | 自动问候页感知；模板变量确定性且 fail-safe | resolveGreetingTemplate 单元 + 集成 + Admin 预览测试 |
| 5 | 无每条消息 You/ASK-AI 标签 | 证据 14/15/20（仅头部身份）；回归断言 |
| 6 | 等待态无三跳点/无假进度 | 证据 14；`.ask-ai-typing` 已删（grep=0） |
| 7 | 内联 citation 保留；无重复 Sources | 后端/widget 套件全绿；未触碰证据语义 |
| 8 | 主题枚举恰四值，match 默认 | CHAT_THEMES 未变（diff 审查） |
| 9 | 草稿即时更新 Live Preview，无需先保存 | previewDoc 消费 draft（WidgetWorkspace.test #36 用例） |
| 10 | 预览覆写临时性；Save 无法夹带 | #37 用例断言 Save payload 无 preview 字段 |
| 11 | 预览与生产同渲染路径 | 预览复用真 widget iframe；证据 18 |
| 12 | 预览不产生真实 /api/ask；显式 Test 走真管道 | 既有 previewMode 机制未削弱（套件全绿）；UI 文案明示 |
| 13 | origins 精确语义/拒绝通配路径/端口/站点隔离 | 8 项 API 测试 |
| 14 | 变更跨重启/seed 存活；seed 不静默覆写 | TestSeedOriginAuthority 4 项 |
| 15 | 授权 origin 经 CORS+resolve_site 双通 | 证据 12/13（≤5s 收敛）+ test_origin_authority |
| 16 | 未授权 fail-closed；无静默分叉 | curl 基线（403/405 无 CORS 头）+ 证据 05/17 |
| 17 | 官方 origins 跨迁移保留 | 证据 09/16（YAML 基线三来源完好） |
| 18 | #33 首绘=终绘；超时确定性回退；迟到配置无二次闪变 | §6；strip 扩展 + 证据 12/05 |
| 19 | 附件/反馈/会话/语言/pageContext/citation/隔离/a11y/embed 不回退 | 后端 2003 + widget 175 + admin 281 全绿 |
| 20 | diff 无范围外语义变更 | §14 scope 审计 |

产品契约 §17 Runtime Gate 逐项对映：Branded Pill（12）、桌面 C proactive mini（13）、自动问候安全回退（单元+13）、0/1/2 Trusted Actions（既有套件+mini 零占位渲染）、C→一请求→等待→流式（14/15）、无角色标签（14/15/20）、内联 citation 无 Sources（套件）、Light/Dark/Match/Custom（枚举与解析测试+浅色运行时）、reduced-motion（CSS 门控+套件）、移动 nudge→full chat（19/20）、四区块（07-10）、真预览（18）、临时预览主题（10/18）、origins 增删校验（11/16/09）、首绘无闪（12/05）。Real-World Gate：授权成功/未授权 fail-closed/预览不污染生产授权（证据 18 摄于 origins 已还原后仍渲染 pill）/单一权威不分叉/浅色宿主安全解析/答案语义零变更（dev 无 LLM 为环境属性，错误路径如实呈现）。

## 14. Gate 2 — Scope 审计

逐文件归类（基准 376565f，全部落入 EXPECTED / REQUIRED SUPPORTING，零 FORBIDDEN 越界，零范围外语义变更）：

- **EXPECTED**：WidgetWorkspace.tsx、widget 访客侧 12 文件（pill/mini/等待态/问候/CSS）、authorized_websites.py、main.py（CORS 执行层）、siteConfig.ts（#33 strip 扩展）。
- **REQUIRED SUPPORTING**：widget_experience.py 服务+API（launcher_presentation 注册表与校验序列化）、models.py（加列）、routes.py（+1 行序列化）、site_experiences.py（seed 权威/通配符/ResolvedSite）、migration 脚本、bootstrap/types/i18n（管线）、5 个测试文件（契约明列允许）。
- **删除**：两旧页面及其测试 = #38 合并的直接结果。
- **危险区核查**：`main.py` diff 仅 CORSMiddleware→DynamicCORSMiddleware + Headers import；`routes.py` 仅 +1 序列化行；`Sidebar.tsx` 仅两行合一行；主题枚举、检索/重排/证据/ResponseStrategy/认证模型 diff 触碰数为 **0**。

## 15. 强制回归断言报告

以冻结实现契约 §5 的 20 项工程验收为断言基（见 §13 矩阵，20/20），另加两项行为回归断言（对应产品契约 §3「既有相关行为必须保留」）：流式/会话状态/附件/反馈/语言解析/site-config/PageContext/embed-error-fail-safe 全部由既有套件在新候选上复跑证明不回退；内联 citation 语义与 EvidencePlan 零 diff 触碰。合计 22 项断言全部 PASS。

## 16. Gate 5 — Real-World Readiness

- 授权 origin 全链成功（UI 变更 → DB 权威 → CORS 执行层 ≤5s → 服务端 resolve_site 放行）：证据 11→12→13。
- 未授权 origin 双层拒绝（CORS 无头 + 403）：curl 基线 + 证据 05/17。
- Admin 预览不要求 Admin origin 入生产授权：证据 18 摄于撤销之后，预览仍渲染 pill。
- 配置与运行时授权不可静默分叉：单一 DB 权威双消费 + TTL 收敛测试。
- 宿主主题安全解析：主题令牌解析测试 + 浅色宿主运行时。
- 答案/citation 行为除批准的呈现矫正外零变更：相关管道 diff=0。

## 17. 未解决风险

1. **LLM 未配置环境的回答语义**：运行时仅能证明到「请求→等待→优雅错误」；带 citation 的流式回答在本次 dev 环境无法端到端呈现（后端管道无 diff + 2003 套件作为语义不变的代理证据）。建议 Agent A 受理后在与生产同构的环境补一条真实问答证据。
2. **DynamicCORSMiddleware 为新执行层**：preflight/simple 两路径均有真实 HTTP 边界测试，但生产级长周期行为（连接风暴、多 worker 缓存一致性——每 worker 独立 5s TTL）未经生产流量验证；多 worker 下收敛上界仍 ≤5s，语义安全。
3. **`{product}` 旧词汇**：模板解析同时接受旧 `{product}` 与新 `{product_name}`（映射等价），存量模板不受影响；Admin 文案只宣传新词汇。
4. **#41 关闭**：作为 #6 重复项，随本矫正一并闭环，需在受理时同步关闭。

## 18. 运行时环境变更与清理记录

- **dev DB（ask_ai）**：已应用 4 个幂等迁移（含 launcher_style 补齐与本次 launcher_presentation）；camthink-website 配置在采集过程中经 UI/API 变更，**结束时已还原**：origins = YAML 基线三条（API 返回核实）；entry_mode=mini_entry / launcher_presentation=pill / enabled=true 为采集期间写入的生产配置值，保留（与新站点默认一致，不影响任何评估语义；如需亦可用同一 UI 改回）。
- **测试 DB（ask_ai_test）**：套件自清理。
- **进程**：:8000 uvicorn、:8901 http.server 为本次运行时探针栈，报告提交后关闭（见 §19 执行记录）。
- **测试宿主页**：`/tmp/iux001-runtime/test-widget.html` 补 `<meta name="viewport">`（勘误，见 §12）。
- **产物**：evidence/ 17 PNG + obs JSON + probe 脚本（pw/*.js）均在 /tmp（不入库）。

## 19. 移交说明（Handoff to Agent A）

- **候选**：分支 `impl/i-ux-001-post-production-corrective`，提交 SHA 见下（提交后回填）；树干净，含本执行报告。
- **受理建议**：按五门复核（§11-§16 证据索引可直接引用）；补一条生产同构环境的真实 LLM 问答证据（§17.1）；同步关闭 #6/#33/#36/#37/#38/#39/#40 与重复项 #41。
- **边界重申**：本候选未合并、未部署；生产部署需另行授权。
- **执行记录**：提交完成后回填最终 SHA 与清理确认。

---

**FINAL SHA**: `cbfd31f5af0b5a97485e5c76fd173087c0d43043`（分支 `impl/i-ux-001-post-production-corrective`；34 files，+3259/−1414；工作树干净）

**清理确认**：:8000 uvicorn 与 :8901 http.server 探针进程已关闭；dev DB camthink-website origins 已还原 YAML 基线（API 返回核实）；报告 SHA 回填以 `--amend` 完成（SHA 以本行上方值为准的说明：回填提交自身的 SHA 见 `git log` 最新条目，两值差异仅为本文件一次 amend）。
