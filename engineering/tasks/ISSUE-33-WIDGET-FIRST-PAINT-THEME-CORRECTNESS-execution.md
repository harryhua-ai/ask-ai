# ISSUE-33 — Widget First-Paint Theme Correctness — Execution Report

- **日期**: 2026-09-08
- **角色**: Engineering Executor
- **STATUS**: **CANDIDATE READY**(等 Planner 独立评审)
- **FINAL_CANDIDATE**: `2cff7bf` @ `origin/worktree-exec/issue33-first-paint-theme-20260908`
- **worktree**: `.worktrees/issue33-first-paint`(基线 = origin/main)
- **PRODUCTION_MUTATION**: **NONE**(未部署/未重启/未触生产库与配置/site_experiences 零触碰)
- **RCA 报告**: `docs/engineering/discovery/ISSUE-33-WIDGET-THEME-FLASH-RCA.md`(docs 0da88b9)

---

## 1. Baseline

| 项 | 值 |
|---|---|
| BASELINE_COMMIT | **`203eec5`**(= origin/main,实现前 `git fetch` 实取) |
| #24 功能存在性 | `b7a016d` **IS ancestor of** origin/main;`widget/src/launcher/*`、site-config `launcher_icon/launcher_shape/launcher_theme`(routes.py:464-467)、`launcher/registry.ts` 冻结契约注释俱在 ✓ |
| RCA 机制存在性 | App.tsx:47 `siteConfig` 初始 null;:78-93 useEffect 后于首帧拉取;:104-116 消解链落到默认;:207-215 `{!isOpen && <Launcher/>}` 恒渲染 ✓ |
| 契约可应用性 | 与 RCA 证据(b7a016d)逐点一致,无实质漂移 → **不触发 BLOCKED**;实现不基于 b7a016d,全部改动落在 203eec5 之上 |

## 2. RCA Confirmation(对当前基线)

203eec5 的缺陷机制与 RCA 完全一致:launcher 在权威 site-config 解析前即按客户端值同步渲染并可绘制;`useEffect` 后于首帧 + 网络往返后 setState 换肤。**缺陷非"慢响应",零延迟响应也至少产生一帧 provisional**(RED 用例 B 实证)。

## 3. RED Evidence(修复前取证)

新增 `widget/src/__tests__/firstPaint.test.tsx`(12 例,jsdom 裸 createRoot+act 状态机测试;"paint readiness"语义=提交进 document 即将可见——真实绘制由真实浏览器台架另证,见 §6)。

**修复前运行:6 failed / 6 passed**。失败集即缺陷签名(修复后同用例转绿):

| RED 用例 | 修复前实际行为 |
|---|---|
| A1 慢配置挂起期 launcher 不得可见 | **FAIL**:`expected <button class="ask-ai-fab" data-launcher-icon="current" data-launcher-shape="rounded-square" data-ask-ai-theme="light"> to be null` —— provisional 外观已提交可绘制 |
| A2 UNRESOLVED→RESOLVED 首个可见=权威值 | FAIL(同上,挂起期断言) |
| B 零延迟无一帧 provisional | FAIL(同上) |
| D1 失败回退 | FAIL(挂起期断言) |
| D2 超时 PENDING≠FAILED | FAIL |
| H/J 解析后可开面板+aria | FAIL(级联) |

绿的一侧(与现状一致,作守护断言):C 三键覆写立即渲染、E 服务器三维各自生效、I legacy 无 siteId 立即渲染、重拉不隐藏。

## 4. Implementation(最小正确实现)

**状态机**(App.tsx):

```
UNRESOLVED(权威外观未定:不渲染 launcher)
  ├─ site-config 成功 ──→ RESOLVED(渲染,值为权威消解结果)
  ├─ 失败/403/网络错 ──→ FAILED(渲染,值为既有 fail-safe 默认)
  └─ 5s 超时(abort)──→ FAILED(同上;PENDING ≠ FAILED 的确定性上界)
免等旁路(初始即 RESOLVED):嵌入级三键齐(icon/shape/theme,遗留 style 顶 icon)
  或无 siteId(legacy 公共 widget,服务端从不参与)
已 RESOLVED 后 uiLang 重拉:失败保留既有权威外观(不隐藏、不回退)
```

**Changed files**(5,+428/−10):
| 文件 | 变更 |
|---|---|
| `widget/src/App.tsx`(+40/−5) | `appearancePhase` 状态机;渲染门 `appearancePhase !== "unresolved"`;fetch 增加 AbortController+5s 超时;失败仅从 UNRESOLVED 转入 FAILED |
| `widget/src/launcher/registry.ts`(+41) | `resolveLocalLauncherAppearance()`:嵌入级三维齐备判定(复用既有 resolve*/legacyStyleToIcon 归一化,不引入第二权威,不改优先级) |
| `widget/src/utils/siteConfig.ts`(+7) | `LAUNCHER_RESOLUTION_TIMEOUT_MS = 5000`(冻结为确定性上界;fetch 已原生支持 signal) |
| `widget/vite.config.ts`(+7/−5) | `process.env.NODE_ENV=production` define 收窄到 build 命令——测试需要 development React 的 `act`;**产物字节面不变**(见 §7) |
| `widget/src/__tests__/firstPaint.test.tsx`(新,342 行) | 12 例状态机/首绘验收 |

未触碰:launcher 图标/形状/主题语义、优先级链、Admin UX、会话/开关语义、认证/站点授权/CORS、本地化、i18n、后端任何文件。无 schema/API/Admin 变更(符合范围约束)。

## 5. Initialization State Model(测试显式覆盖)

- `UNRESOLVED → RESOLVED`:A1(挂起期缺席)+ A2(首个可见=服务器三维)
- `UNRESOLVED → FAILED → FALLBACK`:D1(reject→默认)+ D2(永挂起→advanceTimers 跨 5000ms→默认)
- 免等旁路:C(三键覆写,fetch 仍 pending 即渲染覆写值)、I(无 siteId)
- 反向守护:重拉 pending 期间 launcher 不隐藏;覆写值不被低优先级 server 值覆盖

## 6. Acceptance Matrix A–J

| # | 验收 | 证据 | 结果 |
|---|---|---|---|
| A | 慢配置成功:provisional 永不可见;首见=服务器外观 | jsdom A1/A2 ✓;真实浏览器:t=23ms launcher 缺席 → t=2039ms 首现即 bubble-sparkle-fill/round/dark/橙(16ms 采样,`evidence/issue33-theme-flash/fixed/`) | **PASS** |
| B | 零延迟无一帧闪变 | jsdom B ✓;真实浏览器 t=25 缺席 → t=40 即权威值 | **PASS** |
| C | 显式覆写立即渲染,不等低优先级 | jsdom C ✓;真实浏览器 t=24ms 即 robot-smile/round/light,fetch pending 中 | **PASS** |
| D | 失败不永久空白;确定性回退 | 快速失败:HTTP500@200ms → t=239ms 默认外观可见;永挂起:t=5031ms(=5000ms 上界+抖动)默认回退;jsdom D1/D2 ✓ | **PASS** |
| E | Admin 权威 icon/shape/theme 正确解析 | jsdom E×3(三维逐一)+ A2 全维 ✓ | **PASS** |
| F | 冷载无错误主题过渡 | 真实浏览器多次独立加载序列一致(缺席→权威值);jsdom A1/A2 | **PASS** |
| G | 刷新/重开无初始化错误过渡 | 刷新=全新冷载,序列同 F;无会话持久化路径不受影响 | **PASS** |
| H | launcher 可操作;开合语义不变 | jsdom H/J:click→.ask-ai-panel 出现 ✓ | **PASS** |
| I | 集成契约兼容 | legacy 无 siteId 立即渲染(jsdom I);三键覆写/遗留 style 顶 icon 路径保持;cache 旧 widget 兼容面(launcher_style 回显)零触碰;MSW 三站共享同一 bootstrap | **PASS** |
| J | 无障碍不回归 | aria-label/aria-haspopup="dialog" 断言 ✓;52px 触达/CSS 焦点环未触碰 | **PASS** |

## 7. Tests / Build / Typecheck(实跑记录)

| 套件 | 结果 |
|---|---|
| widget vitest 全量(**修复前**) | firstPaint 12 例:**6 failed / 6 passed**(RED) |
| widget vitest 全量(**修复后**) | **10 files / 122 passed / 0 failed**(既有测试零弱化) |
| `tsc -b` | PASS(修复了一处测试类型:launcher_style null→undefined) |
| `vite build` | ✓ widget.js **259.46 kB**(gzip 91.42)vs #24 基线 258.92 kB → **+0.55 kB**;CSS 6.35 kB 不变;产物=IIFE,define 仍注入 build |
| 后端全量离线(隔离库 `i33_ask_ai_test`,HF_HUB_OFFLINE=1) | **1855 passed / 5 skipped / 0 failed**(49s)——首次运行 3 errors 系迁移测试的库命名守卫(要求 DSN 含 ask_ai_test 字样)误触,以隔离+守卫双满足的库名复跑消除;与变更无关 |
| `git diff --check` | PASS |

真实浏览器台架:rc-verify 同款官方构建流程产物 + 可控行为 site-config 服务 + 16ms 页内采样器(方法学与 RCA §3 一致;截图 `pending-no-launcher.png`(PENDING 期无球)与 `first-visible-resolved.png`(首见=橙圆权威值)入 `docs/evidence/issue33-theme-flash/fixed/`)。

## 8. Remaining Risks

1. **PENDING 期 launcher 缺席**是契约 §2 的必然语义(宁可短暂无球,不可错误球)。5s 上界内网络极慢时用户暂时无入口——超时常量可在 Planner 复核后调整(单常量,位置 siteConfig.ts)。
2. 重拉(本地化热切换)成功但 Admin 期间改了外观 → 球在页内存活期换肤一次:属"服务器权威即时生效"语义,非初始化缺陷,保持现状。
3. 浏览器缓存旧 widget.js 的站点在升级后仍按旧资产渲染(部署缓存卫生,§RCA 已剥离,另案)。
4. vite define 收窄理论上使 dev/test 使用 development React(此前 dev 亦被钉 production)——build 产物不受影响;若 CI 对 dev 依赖 production define 需注意(无此类依赖的证据:全量绿)。

## 9. Deliverable

- 主仓候选:`2cff7bf` @ `origin/worktree-exec/issue33-first-paint-theme-20260908`
- 本报告:docs 仓 `docs/engineering/tasks/ISSUE-33-WIDGET-FIRST-PAINT-THEME-CORRECTNESS-execution.md`
- 截图证据:docs 仓 `docs/evidence/issue33-theme-flash/fixed/`
