# Issue #48 Investigation Report — Citation URL Integrity (Track C, v1.6.4)

- Executor: Trace Executor (INVESTIGATION mode) · Date: 2026-09-15 · Policy: r5-v1
- Claim: harryhua-ai-20260915T165934-03b85398 · Lane-3 worktree · Baseline main b338c3c
- Production probed: v1.6.3-r4 @ 484128d, `/health` ok, app_mode=production (read-only)

## RCA

**判决（residual, current main + production）：EXPLICIT_VISITOR_LINKABILITY_AUTHORITY_MISSING / PROVEN（与 Role A 2026-09-15 评论一致，本轮独立复核并收敛）。**

链路各组件都把「URL 字符串」当作 linkability 的唯一载体，没有任何组件拥有访客可达性真值；widget 从字符串形状猜测可点击性。

1. **Widget badge 无守卫（唯一会"渲染出假链接"的活跃缺陷）** — `widget/src/utils/sanitize.ts:84`：`<a href="${escapeHtml(src.url)}">` 不经过 `isAllowedUrl`（对比 :51 Markdown 链接有门）、无空 URL 守卫。后端对第一方知识案例**有意**序列化 `url:""`（`backend/pipeline/rag.py` `_collect_public_sources` knowledge-case 分支）→ 前端渲染成可点击的 `<a href="" target="_blank">` 自跳转（fake navigability）；任意 off-host 字符串也绕过 urlPolicy。vitest 探针实证（main 代码）：`url=""` → `<a href="" class="ask-ai-ref" target="_blank">`；`https://evil.example.com/...` → 可点击渲染。
2. **GitHub connector 伪造公开 blob URL（代码级隐患，当前生产无活跃实例）** — `backend/connectors/github.py` `_make_document`：token 克隆私库后仍无条件构造 `https://github.com/{owner}/{repo}/blob/{branch}/{path}`，`channel_visibility` 不参与 URL 可达性判定，无 visitor-reachability 状态。生产 12 个 github data_sources 抽样 6 个匿名 HEAD 全部 200（当前全公开）→ 隐患未爆发。
3. **branch-ref 陈旧无状态表达（生产活缺陷）** — wiki-documents main 已移除 `4-application-guide/1-app-development/` 子树；NE503 会话被引 `2-sdk-reference` chunk 的 blob URL 今日匿名 HEAD = **404**，且 `frontmatter_slug=None`（存量对象）→ r4 fallback 直发该死链，无 stale 状态可区分。
4. **`local_git` 仍在 PUBLIC_SOURCE_TYPES**（`backend/pipeline/citation.py:55`）而其 URL 类是 `file://` —— 当前被 `_is_renderable_public_url`（rag.py，scheme∉{http,https} 剔除）+ widget DOMPurify 剥 href 双重抑制，无活跃泄漏；契约 C-5 要求显式关闭。

**09-11 事故形态（历史根因，已在 r3/r4 修复）**：当日构建（含 0403248 路径猜测式 wiki canonical 映射，早于 3adce90/3316193 的 frontmatter-slug 权威化）把 NE503 的 wiki-documents 引用映射到**猜测的** wiki.camthink.ai 路由，目的地当时无效（3316193 提交说明自证"改名/重排目录会把 citation 变成 broken 或软 404"）。今日复验：该会话存储的 5 个 source URL 全部可达（4×200 + 1×301 尾斜杠归一）；r4 语义下其中 3 个改发 blob fallback，其中 2-sdk-reference blob 已 404 —— 事故家族从「猜测 canonical」迁移为「陈旧 blob fallback 无状态」。

**URL 覆盖率生产真值（2026-09-15，Weaviate `Document` 全量只读扫描，n=154,718 chunks）**：空 url = **0**；github 153,732（非 wiki 直通 blob 149,766 = 96.8%，wiki-documents 3,966 唯一映射类），filesystem 481（全 `file://`），web_crawl 384 / woocommerce 121（全 `https://www.camthink.ai`）。审计"93%"为 Postgres documents 行口径（11,183/12,000）；chunk 口径 96.8% 直通无映射 —— 两口径一致指向同一残余面。

**失败类别归类（按 issue 正文清单）**：#2（repo-relative/不可解析 URL）=#3（派生标题缺上下文）=#4（序列化丢 owner/repo/ref/path）=#5（ingest/渲染 URL 表示不一致）=#6（指向 build artifact/内部路径）→ **不成立**（identity 全链路保全，0403248 起 R3 已实现，生产 chunk url 0 空值）。#1（无 canonical URL）→ 仅知识案例类（后端有意置空）。#7（移动后 stale identity）→ **成立，生产活缺陷**（sdk-reference 404）。#8（无效 URL 仍渲染可点击）→ **成立，widget badge 无守卫**（本轮主修复面）。

**修复方向分类**：需要新的显式 linkability 状态语义（backend 拥有 + widget 按状态渲染 + stale/private 类）——**该产品语义已被冻结**：docs/v164-iteration-contracts-20260913 `docs/engineering/tasks/v164-track-c-citation-url-integrity-contract.md` §1 C-1～C-8（C-2 no fake navigability、C-3 backend-owned state、C-4 GitHub 可达性+stale 显式化、C-5 local_git 关闭、C-7 跨源链路回归套件）。状态词表留作实现 HOW。→ 见 STATUS。

## BASELINE
main `b338c3c7eeafec9f57176aa82dd743b9f195153d`（v1.6.3-r4 accepted；生产 484128d 同树）。

## CANDIDATE_BRANCH
`agent/48/03b85398`（investigation evidence branch，非实现候选）

## CANDIDATE_SHA
`34b002695a6624c5f217c5fcecd3a9360d0fa1e5`

## CHANGE_BUDGET (investigation paths)
仅两文件，全部在 assignment investigation_paths 内；零产品代码变更：
- `widget/src/utils/__tests__/issue48BadgeLinkabilityGuard.test.ts`（widget/**）
- `tests/pipeline/test_issue48_linkability_state.py`（tests/**）

## RED（characterization，intentionally failing on baseline）
- widget：2 RED —— (a) `url=""` 渲染可点击 `<a href="" class="ask-ai-ref" target="_blank">`（fake self-navigation）；(b) off-host URL 绕过 `isAllowedUrl`（Markdown 链接受门、badge 不受门）。
- backend：2 RED（词表无关可区分性断言）—— (a) 移动路径 branch-ref 引用与活 canonical URL 序列化完全同形、无 link state（C-3/C-4）；(b) token 私库文档得到公开形 blob URL 且 metadata 无 reachability 状态（C-4）。

## GREEN
- widget 全套件：**2 failed（恰为 RED）| 194 passed** —— 既有 sanitize/urlPolicy/pageContext/bootstrap 等全绿。
- backend 聚焦套件（citation 家族）：**2 failed（恰为 RED）| 71 passed** —— `test_rag_citation_source.py` / `test_canonical_url.py` / `test_citation_integrity.py` 全绿。
- 特征化：`file://` badge href 被 DOMPurify 兜底剥离（本 test 文件内 1 passed characterization）。

## REGRESSION（聚焦套件）
除上述 4 个**有意** RED 外零失败；citation numbering/stream-parity（R5/R6）既有断言不受影响（本调查零产品代码变更，无回归面）。

## LIMITATIONS
- 09-11 当日 wiki 侧真实 404 形态不可回放（wiki 站点历史状态不可只读重建）；以 3316193 提交说明 + 时间线（0403248 猜测式 vs 3adce90/3316193 slug 权威化）作证据链。
- 私有仓库类为代码级实证 + 生产抽样无活跃实例；未对生产做任何写操作/POST chat 复放（本轮纪律），`NE503开发SDK在哪？` 的 r4 现势 citations 由存储真值 + 代码路径推演（3 wiki 项→blob fallback，其中 sdk-reference 404）。
- DOMPurify 对 file:// 的抑制是隐式默认行为，非产品语义，升级 DOMPurify 可能失效（已特征化锁定）。
- 契约 C-8（click 遥测接线）未探针，属 optional 非 gate。

## PRODUCTION_ACCESS（授权=只读；实际命令清单）
1. `curl -s http://127.0.0.1:18000/health`（经 ssh）— 健康与版本确认
2. `docker ps --format …` — 容器清单定位 backend/postgres/weaviate
3. `docker exec tesla-t4-postgres-1 env | grep POSTGRES` + `docker inspect … Config.Env` — 只读发现 DB 名/用户
4. `docker exec tesla-t4-postgres-1 psql -U ask_ai -d ask_ai -c "\dt" / "\d conversations" / "\d data_sources"` — schema 只读检查
5. `psql … SELECT id, created_at, channel, sources FROM conversations WHERE question LIKE '%NE503%SDK%' AND created_at∈[09-11,09-12)` — 事故会话 citations 真值（1 行）
6. `psql … SELECT id, product, config->>'repo_url' … WHERE type='github'` — 12 个 github 源清单
7. `docker exec tesla-t4-backend-1 python -c "…weaviate iterator…url/source_type…"` — 全量 154,718 chunk URL 形态统计（只读）
8. `docker exec tesla-t4-backend-1 python -c "…fetch_objects Filter url=… frontmatter_slug…"` — 被引 wiki-docs chunk slug 真值
9. `docker exec tesla-t4-backend-1 python -c "…web_crawl/woocommerce/filesystem 抽样…"` — 非 GitHub 源形态
10. 本地（不触生产）：`curl -sI` 公开 URL HEAD（5 被引 URL + 2 provenance + 6 仓库可见性）；`gh api repos/camthink-ai/wiki-documents/git/trees/main`（公开 API 只读）— 404/移位实证
无任何写操作/POST chat/compose 生命周期/迁移/宿主写入。

## STATUS
**CONTRACT_READY_CANDIDATE** — 修复需要新语义（显式 linkability 状态 + widget 状态渲染 + stale/private 表达），该语义已在冻结契约 `docs/engineering/tasks/v164-track-c-citation-url-integrity-contract.md`（C-1～C-8，base 5c501914，frozen WHAT/implementation HOW open）完整冻结；词表与落点为实现 HOW。Gate：v1.6.3 COMPLETE 已达成（r4 ACCEPTED @484128d）；实施前须 fresh fetch main + drift 复查（本报告 baseline b338c3c 即现势 main，已含 drift 复核：3adce90/3316193 已在树，rag.py `_is_renderable_public_url` 已闭合部分 file:// 面）。
