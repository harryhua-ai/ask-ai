# V163_R4_ISSUE80_LATE_ADD_INTEGRATION — Integration Report

- 任务:V163_R4_ISSUE80_LATE_ADD_INTEGRATION(Release Integration Executor)
- 日期:2026-09-15
- 判定:**CANDIDATE READY**(待 Role A late-add 终审;不 tag、不部署、不推 main)

## 1. 基线

- 实测起点 origin/main = `0a14845968c6a50769a48db9ea41a58cdccc7bbb`(与任务书冻结态一致,零漂移)
- r4 核心谱系 `f643977` ⊂ 基线(is-ancestor 实证)

## 2–4. 接受候选、复核与集成方法

- 接受 #80 候选:`cba83eaef97ef59e70f7ab21362748468f880c5c`,Role A 判定 ENGINEERING FINAL PASS / READY_FOR_R4_LATE_ADD = YES
- 形状复核:恰 1 个 commit,parent = `f4e67515af810840aa10fa800f0203c2ba290df0`(旧 main),文件集恰为允许的 5 个(widget×3 + docs×2),无 backend/scripts/deploy/admin/.github 触碰 → 与接受口径逐项一致,无需 STOP
- 方法:全新隔离 worktree(基线即精确 `0a14845`,工作树 0 脏项)→ `git cherry-pick cba83ea`
- 结果:**零冲突**;picked 内容对 5 个路径与接受候选 **byte-identical**(diff = 0)
- cherry-pick commit:`6967bd1b28f6e83eb951ce82b1b4b067b6aaa7d0`

## 5. 冲突

无(TYPE 1/2/3 均未触发)。

## 6. 最终变更文件清单(origin/main…late-add,恰 5 个)

| 文件 | 变更 | 来源 |
|---|---|---|
| `widget/src/launcher/Launcher.tsx` | M | #80 cherry-pick |
| `widget/src/components/EntrySurfaces.tsx` | M | #80 cherry-pick |
| `widget/src/__tests__/issue80PluginTracking.test.tsx` | A | #80 cherry-pick |
| `docs/integration/CAMTHINK_ASK_AI_WEBSITE_INTEGRATION.md` | M | #80 cherry-pick + 治理元数据 commit |
| `docs/engineering/tasks/issue80-ask-ai-cta-analytics-implementation.md` | A | #80 cherry-pick |

## 7. 治理/文档元数据校正(commit `9008585`,docs-only)

A. 接入指南(CAMTHINK_ASK_AI_WEBSITE_INTEGRATION.md)最小真值更新:
- 文档版本 3.0(2026-09-10)→ **3.1(2026-09-15)**,保留 3.0 为上一版标注
- 新增「v3.1 重点(Issue #80)」行:四入口暴露 `data-track="contact"` / `data-type="ask_ai"`(语义见 1.6 节),并**明确标注该行为随 v1.6.3-r4 提供、当前生产 v1.6.3-r3 尚不包含**——不冒充生产行为
- Change Log 新增 `v3.1 — 2026-09-15` 条目(契约语义 + 发布状态区分)
- 未改写任何无关指南内容;v1.3.0 基线描述原样保留

B. #80 产品可追溯性:**接受候选内的实现报告已原文具备**,零编辑即满足——
- "The earlier `BLOCKED BY WEBSITE / STORE SOURCE ACCESS` conclusion **is superseded** by this corrected report"
- "ASK-AI owns the reusable **Widget/plugin integration contract** … Host application source ownership is not required"
- 未发明任何新产品契约;未触碰 Wiki 内容

## 8. TEST GATE

- **TEST-1..10**(widget/src/__tests__/issue80PluginTracking.test.tsx):**10/10 PASS**
  TEST-1 四入口冻结语义属性 / TEST-2 宿主委托监听可观测 / TEST-3 宿主可导出规范 element_click 载荷 / TEST-4 一次物理交互恰一个规范信号 / TEST-5 其他 contact CTA(email)与 Ask AI 隔离 / TEST-6 打开回调保留 / TEST-7 无 GA4/GTM/Analytics 凭证依赖 / TEST-8 语义与 class/label/DOM 位置无关 / TEST-9 点击不被 default-prevented 抵达宿主 / TEST-10 锚点形态与 button launcher 同契约
- **Widget 全量回归:15 test files / 193 tests = 全部 PASS**(与既有基线 15/193 一致)
- `tsc -b`:exit 1,4 个错误全部位于 `issue47UserBubbleAlignment.test.tsx`(node 类型缺失);**A/B 对当前 main(0a14845)逐字相同 = baseline-existing**,与 #80 无关;widget 的规范构建门为 `vite build`(package.json scripts),不含 tsc
- **Vite 生产构建:PASS**(exit 0;`dist/ask-ai-widget.css` 16.97 kB / `dist/widget.js` 279.06 kB)

## 9. HOST-INTEGRATION CONTRACT PROOF(A–F)

- **A. 四真实入口全部暴露语义属性**(均为可交互 `<button type="button">` + 原有 open/expand onClick):
  1. FAB — `Launcher.tsx` launcher 按钮(`data-launcher-shape` 形态面)
  2. Launcher Pill — `EntrySurfaces.tsx` `.ask-ai-pill`
  3. Minimal Pill — `Launcher.tsx` `.ask-ai-launcher-pill`
  4. Contextual Nudge — `EntrySurfaces.tsx` `.ask-ai-nudge-body`
  四处均带 `data-track="contact"` + `data-type="ask_ai"`(TEST-1 行为实证)
- **B. 无手动 tracker 调用**:对接受 delta 全文 grep(代码面)无 gtag/dataLayer/sendBeacon/track()/analytics 调用;TEST-7 证明无凭证依赖
- **C. 入口缝无 preventDefault / stopPropagation / stopImmediatePropagation**:delta 代码面为零;唯一 preventDefault 为既有 mini conversation 表单提交处理(非入口按钮);TEST-9 行为实证点击无阻碍抵达宿主
- **D. 无 iframe / Shadow DOM**:delta 代码面为零;`mountWidget` 保持宿主文档普通 light DOM
- **E. 一次合成物理点击 = 恰一个宿主可观测语义信号**:TEST-4 PASS(host 委托监听计数恰 1,canonical 载荷 element_click/contact/ask_ai/ask_ai)
- **F. 非 Ask-AI contact 控件可区分**:TEST-5 PASS(宿主样例控件 `data-type="email"` ≠ `ask_ai`,语义互不污染)

## 10. R4 CORE NON-REGRESSION / MIGRATION RE-CHECK

- `git diff origin/main...late-add` = **恰上表 5 个文件**,无任何其他变更
- 禁区审计:backend/、scripts/、deploy/、admin/、project automation、migrations.json **零触碰**
- 迁移计划重跑(`--tag v1.6.3-r4 --sha 9008585…`):**exit 0,恰 9 条**,与 main(0a14845)计划逐条 diff 相同(唯一差异 = PLAN SOURCE 行的 SHA 本身);#80 引入 **0** 迁移变更;未执行任何迁移
- Widget 打包所需检查(vitest 全量 + vite build)已全过;根 CI 等价后端套件不受 widget/docs 变更影响(禁区审计为证),故未重跑

## 11. ISSUE GOVERNANCE(#80)

- **不关闭 #80**;不改 iteration/release labels(未获授权)
- 状态:工程实现已集成于 pre-tag 候选(本分支);最终 closure 须待 r4 release 部署 + 真实宿主/runtime 验收
- 不主张任何历史 Analytics 连续性(v3.1 明确:r4 前生产无此行为)

## 12. NO PRODUCTION ACTIONS

push main = 无;tag = 无;release = 无;deploy = 无;生产配置/GTM/GA4/Analytics/宿主/Wiki/DB/resync-reindex = 全部无。产物 = 已推送的 late-add 候选分支。

## 13. FINAL

- 最终候选 SHA:`9008585a6c4a731a5087a27bc6416307941e5919`(= 6967bd1 cherry-pick + 9008585 治理)
- 下一门:Role A late-add final review
