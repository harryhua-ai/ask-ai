# V163_R4_ISSUE80_MAIN_PROMOTION_AND_FINAL_PRETAG — Execution Report

- 任务:V163_R4_ISSUE80_MAIN_PROMOTION_AND_FINAL_PRETAG(Release Integration Executor B)
- 日期:2026-09-15
- Role A 前置判定:V163_R4_ISSUE80_LATE_ADD = FINAL PASS / READY_FOR_MAIN_PROMOTION = YES

## 1. MAIN_BEFORE 与基线门

- MAIN_BEFORE(origin/main 实测)= `0a14845968c6a50769a48db9ea41a58cdccc7bbb` — 与冻结态一致,**BASELINE_DRIFT = NO**
- merge-base(origin/main, 484128d)= origin/main;origin/main is-ancestor of candidate:**PASS**
- ahead/behind = **3 / 0**(6967bd1 cherry-pick → 9008585 治理 → 484128d 报告)
- origin/integration/v1.6.3-r4-issue80-late-add-20260915 = `484128d34b496edea95217afc7b0248771c40fcf`(实测一致)

## 2. 最终 scope 审计(0a148459…484128d)

恰 6 个文件(含 Role A 已认定的预期第 6 文件 = 集成报告 artifact,非 blocker):

1. `widget/src/launcher/Launcher.tsx`(M)
2. `widget/src/components/EntrySurfaces.tsx`(M)
3. `widget/src/__tests__/issue80PluginTracking.test.tsx`(A)
4. `docs/integration/CAMTHINK_ASK_AI_WEBSITE_INTEGRATION.md`(M)
5. `docs/engineering/tasks/issue80-ask-ai-cta-analytics-implementation.md`(A)
6. `reports/v163-r4-issue80-late-add-integration-20260915.md`(A)

backend/、scripts/、deploy/、admin/、.github/ 零触碰;`deploy/prod/migrations.json` 零 diff。

## 3. 晋升(纯快进)

- 方法:既有隔离 main worktree(`ask-ai-r4-main`,0 脏项,HEAD 精确 = 0a14845)→ `git merge --ff-only 484128d…` → 普通推送
- push:`0a14845..484128d main -> main`(exit 0;零 merge commit/zero squash/零 rebase/零 force)
- **MAIN_AFTER(本地)= `484128d34b496edea95217afc7b0248771c40fcf`**

## 4. 独立远端验证(双通道)

1. `git ls-remote --heads origin main` → `484128d34b496edea95217afc7b0248771c40fcf`
2. `gh api repos/harryhua-ai/ask-ai/branches/main` → 同 SHA

接受谱系全部包含于 remote main(is-ancestor 实测):`f643977`、`804f98b`、`196cf4b`、`b46252c`、`808d2f4`、`0a32fe9`、`bd98bcc`、`f5ffa4a`、`241881e` — 全 CONTAINED。
`cba83ea` 非祖先(预期,cherry-pick 谱系);内容等价证明:4 个实现路径(2 src + test + 实现报告)对 cba83ea **diff = 0**;指南文件差异仅为已授权的 v3.1 治理元数据(9 行新增/2 行调整:版本行、发布状态区分、Change Log 条目),无其他内容变化。

## 5. FINAL PRE-TAG TEST GATE(对实际 main = 484128d 实测)

| 门 | 结果 |
|---|---|
| A. #80 聚焦契约 TEST-1..10 | **10/10 PASS** |
| B. Widget 全量回归 | **15 test files / 193 tests 全 PASS**(与接受基线一致) |
| C. Vite 生产构建 | **PASS**(exit 0;widget.js 279.06 kB / css 16.97 kB) |
| C'. `tsc -b` | exit 1,输出与既有 A/B 基线**逐字节相同**(issue47 测试缺 node 类型)→ baseline-existing,按授权不作 release blocker;widget 规范构建门 = `vite build` |
| D. 迁移计划(`--tag v1.6.3-r4 --sha 484128d…`) | **exit 0,恰 9 条**;membership/remove_contaminated/sync_request_kind 各恰 1 次;与晋升前计划全同;未执行任何迁移 |
| E. #76 Admin 预检(只读) | ADMIN_EXISTS = **YES**(配置身份 users=1 且 role=admin;生产 backend v1.6.3-r3 healthy)→ ADMIN_BOOTSTRAP_SECRET_REQUIRED = **NO**;零凭证回显、零写入 |
| F. #79 Project schema(只读) | Sprint 不存在 = ACCEPTED;Iteration/Priority/Status 均在 — **PASS** |

## 6. RELEASE TREE 负面审计(484128d 树内实证)

- 无新 analytics 事件族;无 `ask_ai_click`;无 `source_surface`
- 无手动 GA4 emitter(gtag/googletagmanager)、无手动 GTM emitter、无 `dataLayer.push`(widget src 代码面 grep = 0;TEST-7 行为实证无凭证依赖)
- 无 Analytics 凭证;无 Website/Store 源码依赖、无宿主源码依赖
- Wiki/content 零修改;生产配置零变更
- 冻结语义信号保持:宿主侧 = element_click / contact / ask_ai / ask_ai;Widget 责任仅为暴露 `data-track="contact"`、`data-type="ask_ai"`;观测/记录归宿主

## 7. FINAL PRE-TAG DECISION

**V163_R4_FINAL_PRETAG = PASS**

**TAG_AUTHORIZATION_CANDIDATE = YES**(授权归 Role A;本任务未建 tag/release/部署)

## 8. RELEASE TREE 身份(无歧义声明)

- **RELEASE_CODE_TREE_SHA = `484128d34b496edea95217afc7b0248771c40fcf`** ← v1.6.3-r4 预定 tag 目标
- 本报告按项目 report-on-main 惯例另以 docs-only commit 追加;**REPORT_SHA = 见下节 commit 记录**
- 两者的 delta 仅为本报告文件(reports/ 下 docs-only);tag 必须打在 RELEASE_CODE_TREE_SHA,不得打在报告 commit
- TAG_CREATED = NO;RELEASE_CREATED = NO;DEPLOYED = NO;PRODUCTION_MUTATION = NO
