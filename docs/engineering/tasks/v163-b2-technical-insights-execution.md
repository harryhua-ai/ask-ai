# v1.6.3 B2 — Technical Insights Convergence 执行报告

**Track:** B2(Role B2,独立 worktree 执行)
**Branch:** `b2/technical-insights-convergence-20260913`(基于 fresh origin/main = 5c501914636ae274bdf54896e3decf86c4584e12)
**Candidate SHA:** `b1e1b3a54cebad67edf6f75c41934d00d4fb6b58`
**设计基线:** KB-OPS-V163-002(FROZEN)+ `technical-insights-answer-gaps-original.png`(Hard Visual Reference,已由 B2 亲自 Read 重读验证)
**合同:** v163-b2-technical-insights-contract.md + Issues #57/#58/#59(+ #60 适用语法)
**日期:** 2026-09-13
**视口:** 1440×900 @ deviceScaleFactor 1(全部配对截图统一)

---

## 0. 三门结论

| Gate | 结论 | 依据 |
|---|---|---|
| Engineering Gate | **PASS** | vitest 51 files/387 tests 全绿;tsc -b 0 error;vite build ✓(exit 0);改动文件 ruff 0 error;后端 pytest 子集 60 passed(answer-gaps 11 新增 + tech 三件套 33 + analytics 回归 27,串行,HF_HUB_OFFLINE=1,TEST_DATABASE_URL=ask_ai_test) |
| Functional Gate | **PASS** | 真实全栈(backend 8102 + vite 5182)真实登录真实数据;两条下钻实测到达正确 URL/上下文;UI↔API↔DB 三角核对通过;real zero / unavailable / populated 诚实四态有渲染证据;Functional DEFECT = 0 |
| Design Gate | **PASS**(附 JUSTIFIED DIFFERENCE 12 项待 Role A 裁决) | 12 状态真实截图与 ORIGINAL PNG 逐区域比对;Visual DEFECT = 0(2 个过程中 DEFECT 已修复重摄);每处 material difference 均入 Ledger |

> JUSTIFIED DIFFERENCE 无自批项:全部附权威真相证据,留 Role A 裁决。B2 未关闭任何 Issue。

---

## 1. 执行循环记录

1. **Baseline reconstruction:** 通读冻结合同、KB-OPS-V163-002(全文)、迭代计划、#57/#58/#59/#60 原文(gh issue view);用 Read 工具亲自重读 ORIGINAL PNG,验证编排者解读逐项吻合(共享壳/双 Tab/队列 7 列/原因与状态徽章/行选中态/诊断侧板五 Tab/诊断结论红板/推荐操作/内容补充完成段)。
2. **Inventory:** Analytics.tsx(旧 Button 版 Tab、知识缺口 Tab=趋势+分布+覆盖缺口表)、observability/*、lib/api/techInsight.ts、backend/api/admin/tech.py(performance + generation-events)、analytics.py(coverage-gaps 权威 miss_type 分类)、clustering.py(representative_question=真实问句不变量)、DB 现状(question_clusters 2、conversations 3、traces 0、index_generations 3、sync_runs 1 failed)。
3. **RED:** 新增 `admin/tests/TechInsightConvergence.test.tsx`(25 用例)+ `src/lib/gapCause.test.ts`(8 用例)+ `tests/api/admin/test_tech_answer_gaps.py`(11 用例)。RED 证据:前端 33/33 失败、后端端点 404(见 evidence/RED-*.log)。
4. **Implementation:** 见 §2。
5. **GREEN:** 见 §0 Engineering Gate。
6. **Render:** 后端 `ASKAI_API_PORT=8102 EMBEDDER_DEVICE=cpu uv run python -m backend.main`;前端 `cd admin && VITE_API_TARGET=http://localhost:8102 npx vite --port 5182 --strictPort`;Playwright(独立 Chromium 实例,1440×900@1x)真实登录(b2-render@camthink.ai,B2 专用本地 admin 账号)驱动 12 状态。
7. **比对:** 逐区域对照 ORIGINAL PNG → Visual Difference Ledger(§4)。
8. **DEFECT 修复:** 见 §4.3(2 项已修复重摄)。
9. **Functional Gate runtime 证据:** 见 §5。

## 2. Changed files(9 个,git diff --stat main...HEAD)

```
admin/src/lib/api/techInsight.ts            |   77 ++   (fetchAnswerGaps/fetchGapConversations + 类型)
admin/src/lib/gapCause.ts                   |   90 ++   (权威原因/状态→运营词映射,新建)
admin/src/lib/gapCause.test.ts              |   77 ++   (新建)
admin/src/pages/Analytics.tsx               | 1012 +-----(共享壳+强选中 Tab;技术性能事件行层级+可展开证据;回答缺口队列+诊断侧板)
admin/tests/TechInsight.test.tsx            |   80 +-   (legacy 测试对齐冻结修订后的 IA)
admin/tests/TechInsightConvergence.test.tsx |  584 ++   (新建,25 行为用例)
backend/api/admin/analytics.py              |  124 +--  (提取 classify_gap_miss_types 共享 helper,行为不变)
backend/api/admin/tech.py                   |  198 +++  (GET /tech/answer-gaps + GET /tech/answer-gaps/{id}/conversations,只读)
tests/api/admin/test_tech_answer_gaps.py    |  299 ++   (新建,11 用例)
```

**后端读面语义(只读投影,零 mutation):**
- `GET /tech/answer-gaps`:question_clusters(gap)+ conversations 权威投影。相关提问=question_count;受影响回答=COUNT(归属会话);最近发生=MAX(归属会话 created_at),无会话→null(UI 呈现 证据不可用);原因=classify_gap_miss_types(与 /analytics/coverage-gaps 同一 helper,单一权威真相);状态=open|resolved 两态权威词表;支持 status/cause/q/window/order/dir/page/size;时间窗只约束 last_seen 已知聚类(未知时间≠窗口外);cause 过滤在分类后应用,total 为过滤后真值。
- `GET /tech/answer-gaps/{id}/conversations`:归属会话证据(question/is_answered/created_at,最近在前),非 gap 或不存在→404。
- analytics.py 仅做 helper 提取(逐行同语义)+ ruff `.values()` 修正;coverage-gaps 行为回归 27 用例通过。

## 3. Runtime evidence

- 启动:后端 uv run(8102,`.env` symlink,local PG/weaviate docker);前端 vite strictPort 5182(与 B1 的 5181 错开)。
- 登录:B2 专用本地账号 `b2-render@camthink.ai`(admin 角色,仅本地库;创建 SQL 见 scope audit 注记)。早期曾重置共享 admin@camthink.ai 密码,发现与并行 B1 的同库重置相互覆盖后,改为 B2 专用账号,互不干扰。
- 浏览器:独立 Chromium("Google Chrome for Testing" 1228,headless,fresh profile)——首用 playwright-cli 全局会话时被并行 B1 的自动化抢占驱动(页面被导航至 5181),遂改独立实例,零交叉。
- 驱动脚本:`/tmp/b2pw/render-evidence.mjs`(真实点击,断言 URL)。
- 下钻实测:
  - gap 行 → 侧板 查看相关对话 → `http://localhost:5182/admin/conversations?q=NE101%20%E6%98%AF%E5%90%A6%E6%94%AF%E6%8C%81PoE`(URL 编码),搜索预填 + 18 条命中(截图 09)。
  - 事件行(error)→ `http://localhost:5182/admin/data-sources/store-woo`,到达 main 上已存在的 B1 源工作台,上下文正确(截图 12),B2 未改动该路由与页面。

## 4. Visual Difference Ledger(对照 ORIGINAL PNG,1440×900)

### 4.1 MATCH(主要区域)

| # | 区域/元素 | 证据 |
|---|---|---|
| M1 | 页标题 技术洞察 + 恢复副标题全文 | 01/03 |
| M2 | 双 Tab 技术性能/回答缺口,选中=蓝色下划线强选中态,aria-selected | 01(技术性能选中)/03(回答缺口选中) |
| M3 | 搜索框占位「搜索问题/主题、产品名称或关键词(如:NE101、价格、安装)」 | 03 |
| M4 | 筛选 全部状态/全部原因/过去 7 天 | 03 |
| M5 | 表列 问题/主题(主行加粗+代表问句灰副行)、相关提问、影响回答、原因、状态、最近发生(排序指示) | 03 |
| M6 | 原因徽章语义色:知识缺失(红)/服务知识不完整(蓝紫)/低相关(琥珀)/未分类(灰) | 03 |
| M7 | 状态徽章 需要处理(红)/已解决(绿);无 观察中(NOT authorized,如实缺席) | 03/11 |
| M8 | 行选中态=蓝底+左侧蓝条+checkbox;底部 已选择 1 项+分页+10 条/页 | 04 |
| M9 | 诊断侧板:标题+状态徽章+关闭;统计行「23 次相关提问 · 18 次受影响回答」+ 最近发生 | 04 |
| M10 | 侧板 Tab 概览/典型问题/相关对话/诊断详情/历史记录,选中蓝下划线 | 04–08 |
| M11 | 诊断结论红板+原因徽章+结论文案(忠实转述后端分类语义) | 04 |
| M12 | 典型问题示例+查看全部 (6)+5 条 bullet | 04/05 |
| M13 | 技术性能:critical 横幅(需要介入+失败/P95 理由)+失败卡红框;异常优先事件列表 | 01 |
| M14 | 证据可展开:默认折叠,展开为 raw failure JSON/内部字段(截图 02 实拍展开态) | 02 |
| M15 | 诚实四态:未分类+证据不可用(无权威分类/无会话证据)与 populated 并存且视觉可区分 | 03/10 |

### 4.2 JUSTIFIED DIFFERENCE(12 项,B 不自批,待 Role A 裁决)

| # | 参考元素 | 实现差异 | 权威真相证据 |
|---|---|---|---|
| J1 | 原因词表含 内容过期/检索异常/生成异常/引用异常/内容冲突 | 仅呈现权威分类映射:召回空→知识缺失、召回不足→服务知识不完整、reject→拒答、low→低相关、无→未分类 | KB-OPS §5.3 ADAPT;backend/api/admin/analytics.py 分类 docstring;后端无其它分类真相;lib/gapCause.ts 注释;词表方向词不入筛选选项(unit test 断言) |
| J2 | 状态含 观察中 | 仅 open→需要处理 / resolved→已解决;观察中不实现 | 合同 Forbidden + KB-OPS §10(new OBSERVING lifecycle NOT authorized);gapStatusLabel 未知状态透传(unit test) |
| J3 | 推荐操作=导出相关对话(CSV)+隐私说明 | 替换为授权动作 查看相关对话(既有 /conversations?q= 冻结深链) | KB-OPS §5.5 Export=NEW REQUIREMENT unless authoritative surface exists;§10 不发明 conversation-export;#59 amendment |
| J4 | 内容补充完成后段+「内容已补充,开始观察」大蓝按钮 | 整段缺席 | §5.6 NEW REQUIREMENT;§10 observation transitions NOT authorized |
| J5 | 侧板统计「涉及 17 个用户」 | 缺席(仅相关提问/受影响回答) | conversations 无权威用户聚合真相(session_id 为匿名 widget 线程键,非用户实体);frontend inference 禁令 |
| J6 | 相关数据源(WooCommerce / NE101 外链) | 缺席 | 后端无 gap→source 权威关联;conversations.sources 为引用 URL/title,非 data_sources.source_id 映射;拼接即发明关联 |
| J7 | 侧板 问题描述为诊断式文案 | 为权威字段的事实性汇总(N 个相关提问/M 个受影响回答/状态) | 不虚构诊断;仅复述权威计数与分类语义 |
| J8 | 队列主标题为主题式短语(如「NE101 PoE 支持信息缺失」) | 主行=representative_question(真实问句,聚类服务不变量:代表问题取自簇内真实问题);主题字段后端不存在 | backend/services/clustering.py(代表问句=真实问题);KB-OPS §6 Knowledge Issue 为投影而非持久化 |
| J9 | 顶栏 过去 7 天 2025-09-03→2025-09-09 日期范围选择器+头像菜单 | 应用共享顶栏为 欢迎+角色徽章+退出;范围过滤在页内(今日/近7天/30天+自定义起止) | Layout.tsx 为 B1/B2 共享 chrome,单方改动制造合并冲突;范围语义等价存在;归属 Integration 收敛 |
| J10 | 侧边栏含 帮助中心/收起菜单;系统设置;选中项浅蓝样式 | 无 帮助中心/收起;系统信息;选中项深色底(既有共享样式) | Sidebar.tsx 共享 chrome(运营/配置组标签已与参考一致);帮助中心无路由真相,不发明;Integration 所有 |
| J11 | 未回答率趋势图/缺口类型分布卡(旧实现) | 回答缺口 Tab 按参考收敛为 队列+侧板,趋势/分布块移除 | Hard Reference 该 Tab 仅含 队列+侧板;#59 主诉即趋势/分布与队列矛盾(「暂无缺口数据,请先执行聚类刷新」vs 有缺口);gap-trends 端点保留未删 |
| J12 | 参考 depicted 状态:检索异常/生成异常/引用异常/内容冲突行、观察中行 | 以权威可达状态重演:知识缺失/服务知识不完整/低相关/未分类 × 需要处理/已解决/证据不可用 | 同 J1/J2;虚构 depicted 状态=伪造 backend semantics |

### 4.3 DEFECT(过程中发现并修复,最终 Visual DEFECT = 0)

| # | DEFECT | 修复 | 复验 |
|---|---|---|---|
| D1 | 侧板打开时队列表受压:表头竖排(相关提问 4 字竖排)、状态徽章截断(需…) | table-fixed+显式列宽+单元格 padding 压缩+overflow-x-auto | 重摄 04–11,列齐全不竖排(b1e1b3a) |
| D2 | 侧板打开时 状态/最近发生 列被横向裁出可视区 | 同上(table-fixed 布局修复) | 重摄 04,7 列全部可见 |
| D3(功能性) | gap→conversation 深链预填后 0 命中:seed 把代表问题写成主题式短语,违反聚类权威不变量(代表问题=真实问句),q 全文检索不命中 | 修正本地 seed 使 representative_question=真实问句(与 clustering.py 语义一致);同时将 J8 差异如实入册 | 重摄 09:预填+18 条命中 |

## 5. Functional Conformance Ledger

三角核对法:UI 值 ↔ API 响应(curl 带 JWT)↔ 本地 PG 只读 SELECT。

| # | UI surface/state/action | Authoritative source | API/backend evidence | Expected semantics | Observed result | Verdict |
|---|---|---|---|---|---|---|
| F1 | 技术性能 KPI 真实失败 6%(3/52) | traces(type=generation_error) | `GET /tech/performance?range=7d` kpi.fail_count=3,trace_total=52 | 分子=真实失败数,分母=窗口 trace 数,不裸百分比 | UI「3 / 52 条 trace」= API = DB count(*) | MATCH |
| F2 | 健康横幅 critical(需要介入) | 同上 + _derive_health 阈值 | health.status=critical,reasons 含 5.8%/≥5% 阈值文案 | 确定性推导,前端零二次推断 | UI 横幅文案=API reasons 原文 | MATCH |
| F3 | 事件行 生成失败 store-woo | index_generations(status=failed) | `GET /tech/generation-events` 含 source_id=store-woo,severity=error | P 轴 failed=error,行含源归属 | UI 行 data-source-id=store-woo=API=DB 行 | MATCH |
| F4 | 事件行同步失败 wiki-documents-local | sync_runs(status=failed) | `GET /sync-runs?status=failed` | 复用既有权威读面,零新增语义 | UI 行与 API item 一致 | MATCH |
| F5 | 事件行→源下钻 | #50 FROZEN INTERFACE 路由 | 点击后 URL=/admin/data-sources/store-woo | 到达正确源上下文,不改 B1 面 | 实测到达,页面为 main 的 B1 工作台(截图 12) | MATCH |
| F6 | 回答缺口队列行 NE101 是否支持 PoE(23/18/知识缺失/需要处理/2小时前) | question_clusters + conversations 投影 | `GET /tech/answer-gaps` item:id/…/question_count=23/impacted=18/miss_type=召回空/last_seen | UI 值逐字段=API 值;API=SQL 聚合 | 三角一致(DB:count=18,max(created_at) 匹配 2 小时前) | MATCH |
| F7 | 原因徽章 知识缺失(data-gap-type=召回空) | classify_gap_miss_types(与 coverage-gaps 同源) | 同一 helper 两端点输出一致 | 运营词=忠实映射,机器值 data 属性保留 | UI 徽章=API miss_type 映射;coverage-gaps 与 answer-gaps 同值 | MATCH |
| F8 | 未分类/证据不可用态 | 无归属会话的聚类(配件兼容性/NE101 的价格/NE503 APN) | API impacted=0,last_seen=null,miss_type=未分类 | 不发明 cause/recency | UI 未分类徽章+证据不可用文案(截图 03/10) | MATCH |
| F9 | 诊断结论 authoritative/unavailable 两态 | miss_type 权威性 | gapCauseAvailable(gate) | 权威→红板+结论;无→证据不可用,不推断 | 04(authoritative)/10(unavailable)两态渲染 | MATCH |
| F10 | 相关对话 Tab 归属会话证据 | conversations WHERE cluster_id | `GET /tech/answer-gaps/{id}/conversations` total=18 | 只读投影+深链保留 | UI 18 行=API total=DB count | MATCH |
| F11 | gap→conversation 深链 | /conversations?q= 冻结参数语法 | 点击后 URL=`/admin/conversations?q=NE101%20是否支持%20PoE`(编码) | 搜索预填+命中 | 实测预填+18 条命中(截图 09) | MATCH |
| F12 | 队列筛选(status=resolved) | question_clusters.status | `GET /tech/answer-gaps?status=resolved` total=2 | 服务端过滤,total 为真值 | UI 2 行(30 天退货/配件兼容性)=API(截图 11) | MATCH |
| F13 | 窗口过滤诚实语义 | conversations.created_at 聚合 | 7d 排除旧 last_seen;last_seen NULL 始终保留 | 不可用≠窗口外 | UI:未分类行在 7d 视图可见+证据不可用标注 | MATCH |
| F14 | real zero:traces 稀疏历史 | traces 表(seed 前=0) | /tech/performance trace_coverage_from 如实返回 | 无数据≠healthy;覆盖起点如实 | 「Trace 数据自 2026/9/7 起」展示;seed 前基线已由 OBS-G006 单测覆盖 no_data 态 | MATCH |
| F15 | 只读边界 | 合同 Forbidden | /tech/answer-gaps POST=405(pytest 断言);UI 无 导出/开始观察/解决/刷新控件 | 零 mutation 面 | vitest 断言 未授权元素全部缺席;pytest 405 通过 | MATCH |
| F16 | RBAC 不变 | 既有 require_role("admin","editor","viewer") | 未认证 401(pytest) | 只读读面 RBAC 与域内一致 | pytest 通过 | MATCH |

**Functional DEFECT = 0**(D3 为过程中发现的功能命中缺陷,已修 seed 并复验;实现代码本身语义正确)。

## 6. Scope audit

- **零生产触碰:** 全程仅本地 docker(ask-ai-local-postgres-1@5432、ask-ai-local-weaviate-1@8080);未 SSH 任何主机;生产 43.132.189.162 零网络访问(无任何生产连接命令)。
- **零语义变更证明:** 检索/排序/引用/生成/生命周期语义零改动;analytics.py 仅提取 helper(coverage-gaps 回归 27 用例通过);新端点只读(GET-only 405 断言、RBAC 断言);无新持久化模型/表;无 OBSERVING/修复/导出/刷新语义;前端 cause 映射仅为后端分类的忠实运营词转述(unit test 锁死)。
- **本地 seed 清单:** 见 `evidence/SEED-local-only-scope-audit.md`(5 聚类/51 会话/33 conf trace + B2SEED 前缀 21 会话/19 性能 trace;含清理 SQL)。seed 修正代表问句后与 clustering.py 不变量一致。
- **跨轨零触碰:** 未改 DataSources.tsx、DataSourceDetail.tsx、components/dataSources/*、useDataSourceWorkspace.ts、/data-sources/:sourceId 路由(仅作为下钻目标到达验证);未 cherry-pick 他轨实现;未 merge main。
- **与 B1 的潜在集成冲突面(供 Integration 预判):**
  1. 无共同改动文件(B1 面 = 数据源页/组件/hook;B2 面 = Analytics.tsx/techInsight.ts/tech.py/analytics.py)——`git diff --stat` 两轨文件集不相交预期成立。
  2. 共享 chrome(顶栏欢迎区/侧栏选中样式/系统信息标签/帮助中心缺席)= J9/J10,建议 Integration 统一收敛,双方不必单方改。
  3. 本地共享 DB:并行 reset 共享 admin 密码会互踩(B2 已改用专用账号 b2-render@camthink.ai);B2 的 seed 行以 `b2a%` UUID 前缀与 `B2SEED` 问题前缀标识,便于辨识与清理。
  4. Analytics 的 SourceHealthSummary/IncidentSection 消费 GET /analytics/source-health 与 GET /sync-runs:若 B1 改动这两个读面的响应形状,需组合回归。

## 7. 交付物索引

- 截图(12 状态):`/Users/harryhua/Documents/GitHub/ask-ai-acceptance/v163-b2-20260913/01…12*.png`
- 证据目录:`/Users/harryhua/Documents/GitHub/ask-ai-acceptance/v163-b2-20260913/evidence/`(RED×2、GREEN×4、SEED audit)
- 本报告:`docs/engineering/tasks/v163-b2-technical-insights-execution.md`(分支内)

## 8. 遗留与移交 Role A

1. §4.2 全部 12 项 JUSTIFIED DIFFERENCE 需 Role A 逐项裁决(尤其 J1 词表映射、J3 导出替代动作、J8 代表问句 vs 主题标题)。
2. 观察中/导出/修复/历史记录流:等专门契约,后续迭代。
3. Design Gate 的截图为 B2 单轨 candidate 树;Integration 需在组合树重摄并独立重建 Difference Ledger(迭代计划硬性要求)。
