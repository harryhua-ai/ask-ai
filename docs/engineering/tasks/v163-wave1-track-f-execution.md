# V1.6.3 Wave 1 — Track F 执行报告(证据聚合 U-17/U-18/U-19)

- **分支**:`track/v163-f-evidence`(worktree `/Users/harryhua/Documents/GitHub/ask-ai-v163-wf`,单 worktree 追加 commits,未新建 worktree)
- **基线**:FINAL_PREP_BASE = `d613e6aab787110e6c7839f92dbc28611b79ee7e`;merge-base(HEAD, 7e3e71c) = 7e3e71c 复核 PASS(实现父链冻结语义遵守)
- **合同**:track-f-contract.md(U-17/18/19 冻结语义)+ matrix-TI TI-12/TI-27/TI-33 + remediation plan §3.5(IF-7:U-17 聚合窗=所选分析窗)+ wave0b 报告 §10 ownership 表
- **参考 PNG**:/tmp/v163-audit-refs/technical-insights-answer-gaps-original.png(23 次相关提问 · 18 次受影响回答 · 涉及 17 个用户 / 相关数据源卡+外链 / 队列主题式标题 = 权威呈现目标)

---

## 1. 变更文件全表(9 文件 = 4 修改 + 5 新增;全部 F-owned)

| # | 文件 | 类型 | Ownership 依据 |
|---|---|---|---|
| 1 | `backend/api/admin/tech_evidence.py` | 修改(空 router → 3 只读端点) | F 专属(IF-6;已由 tech.py 挂载,零编辑 tech.py) |
| 2 | `backend/services/gap_topic.py` | **新增** | F-owned 新服务(确定性主题派生,规则冻结稿) |
| 3 | `admin/src/lib/api/techEvidence.ts` | **新增** | F-owned 新 API 客户端(类型+fetch,零推断) |
| 4 | `admin/src/pages/analytics/PanelStats.tsx` | 修改 | F 专属(meta 三计数 + 相关数据源卡) |
| 5 | `admin/src/pages/analytics/GapTopicCell.tsx` | 修改 | F 专属(主题列渲染+回退) |
| 6 | `tests/services/test_gap_topic.py` | **新增** | F-owned 测试(派生纯函数 16 用例) |
| 7 | `tests/api/admin/test_tech_evidence.py` | **新增** | F-owned 测试(端点 20 用例) |
| 8 | `admin/tests/TrackFEvidence.test.tsx` | **新增** | F-owned 测试(组件 10 用例) |
| 9 | `admin/tests/TechInsightConvergence.test.tsx` | 修改(仅 2 处断言块) | 共享回归文件:U-17 使 v1.6.3 B2「无 个用户」冻结缺席断言合法过时,修订为「计数仅权威、不编造」(逐字 diff 见 §7) |

**越权项:无。** 禁触清单逐项核验零 diff:AnswerGapsTab/GapPanel(Integration 壳)、GapCauseFilter/CauseBadge/DiagnosisConclusion/gap_taxonomy.py(D)、GapStatusFilter/StatusBadge/PanelHistory/tech_observation/tech_export/gap_status.py(E)、tech.py(装配)、tech_performance/tech_generation_events/tech_answer_gaps、data_sources/DataSourceDetail、Sidebar/Layout。`.env` symlink 未提交(gitignore)。测试库 `ask_ai_test_f` 仅按既有 conftest 生命周期使用;本地 dev 库仅追加 WF_/wf- 前缀行(SQL 全文随交付,清理脚本同目录)。

## 2. 实现语义(冻结合同逐条)

### 2.1 U-17 受影响用户聚合(TI-27)—— `GET /api/admin/tech/answer-gaps/{gap_id}/users`
- **定义(冻结)**:所选分析窗内该 gap 归属会话的**去重伪匿名会话**(`conversations.session_id`,widget 匿名会话 ID;既有列,零新身份列);零姓名/邮箱/IP;隐私保持聚合 —— 响应仅含 DISTINCT 计数,不外泄任何 session_id 原值(测试断言 `sess-` 不出现在响应)。
- **聚合窗 = IF-7 所选分析窗**:窗口词表全量 `today/7d/30d/all` + 显式起止 `from/to`(ISO,显式起止优先);词表外值 422(禁静默回退);响应回显实际窗口。**前端接线点**:`PanelStats` 的 `window?: EvidenceWindowValue` prop —— Integration 合并时由壳传入共享分析窗;独立运行默认 `"all"`(与既有 meta 计数的 gap 全证据跨度一致;壳文件属 Integration/禁区,F 不改壳)。窗口过滤权威在服务端投影,UI 不做任何估算。
- **诚实语义(禁编造)**:窗内全部会话含身份(或窗内无会话)→ `users`=DISTINCT 计数、`users_available=true`(空集真值 0);窗内存在 session_id 缺失的历史行 → 身份真值不足,去重计数只是下界不得伪称权威 → `users=null`、`users_available=false`、`unavailable_reason="session_identity_insufficient"`。UI 呈现:权威 → `涉及 N 个用户`(参考 PNG 逐字语义);不可用 → `涉及用户 证据不可用`(不出现任何编造数字,测试断言 `\d+ 个用户` 缺席)。

### 2.2 U-18 gap→源归因(TI-33)—— `GET /api/admin/tech/answer-gaps/{gap_id}/sources`
- **证据规则(冻结 ID=`conversation_citation_identity_match`)**:gap 归属会话的**引用真值**(`conversations.sources` 条目的 `(type, product)` 来源身份 —— 即 RAG citation truth,由检索结果 source_type/source product 写入)与数据源行 `(data_sources.type, data_sources.product)` 精确匹配 → 归因成立;同一身份的多个源行均为证据支持的真实候选;`citing_conversations` 按会话去重计数。
- **零前端猜测**:前端仅渲染后端归因投影(源卡 label=源类型+产品,`capitalize` 纯 CSS 呈现,零新词表);引用真值存在但无对应数据源行(第一方知识案例 `filesystem/knowledge`、已删源)→ **不归因**,`unmatched_citations` 透明列出(可解释);归属会话无引用记录 → 诚实空态「无归因证据:归属会话无引用来源记录,系统不做猜测」。
- **深链真实**:源卡 → `/data-sources/{source_id}`(运行时验证真实到达源详情页)。
- **归因范围 = gap 自身证据跨度**(§3.5 S6 例外面同语义,无窗口参数,窗口假联动不引入)。

### 2.3 U-19 主题短语(TI-12)—— `GET /api/admin/tech/answer-gaps/{gap_id}/topic`
- **确定性派生(规则冻结稿,`backend/services/gap_topic.py`)**:① 语料 = 代表问句 + 去重样例,去重后 <2 条不同问句 → None;② 拉丁/数字 token(≥2 字符,大小写归一)取全语料交集;③ CJK 极大公共子串(2..12 字)取全语料交集,纯疑问框架词候选(什么/怎么/是否/哪些…)剔除 —— 框架词不是内容;④ 片段按代表问句出现位置排序拼装(忠实原文语序,保留原文大小写);⑤ >40 字按片段边界截断。**零 LLM、零随机、零外部调用、零主题词表硬编码**;每片段逐字出现于语料每条问句(忠实性由构造保证 + 测试断言);LLM 路径未启用(确定性在本轨道全部验收场景充分,无 residual 缺口;如未来确定性不足须另行授权)。
- **稳定性**:纯函数,同簇内容多次拉取恒同值(运行时 ×5 同值 + UI reload 同值 + 单测 50 次同值/样例顺序无关)。
- **回退**:不可派生 → `topic=null`,`fallback`=代表问句;UI 主行回退代表问句、副行保持既有样例问句呈现(既有行为逐字保留为回退路径;既有 `data-gap-question` 属性在两种形态下均指向代表问句)。
- **持久化设计说明**:主题 = question_clusters 持久化内容之上的**确定性只读投影**(合同措辞「topic 投影」/「topic 派生」;gap-register 持久化依赖列「clusters topic 字段」在本实现中以派生投影满足 —— 不新增可变列可避免 create_all 无法补列的迁移风险[仓库无 Alembic,`init_db` 仅建缺失表]与 GET 侧回填 mutation 语义;同簇稳定性由纯函数而非持久化值保证。如 Integration 仲裁要求物化列,追加 `topic` 列与 `ensure_*` 迁移即可,派生函数原样复用)。

### 2.4 前端呈现(PanelStats / GapTopicCell)
- PanelStats:meta 行三项计数并排 `N 次相关提问 · M 次受影响回答 · 涉及 X 个用户|涉及用户 证据不可用`(既有两项计数+最近发生逐字保留);相关数据源卡区(参考 PNG:类型徽标+`WooCommerce / ne101`+外链 icon),数据 useQuery 自取(同 GapPanel convQuery 模式;Integration 壳零编辑)。
- GapTopicCell:主题真值存在 → 主行 `data-gap-topic` 主题短语 + 副行代表问句(参考 PNG 主题式标题行);无主题/加载/失败 → 回退渲染(不闪不造)。

## 3. 测试(RED→GREEN)

| 套件 | 结果 |
|---|---|
| `tests/services/test_gap_topic.py`(新增) | 16/16 PASS(拉丁/CJK 公共因子、框架词剔除、忠实性、稳定性 50 次、语料守卫、长度守卫) |
| `tests/api/admin/test_tech_evidence.py`(新增) | 20/20 PASS(去重权威计数、四窗词表+显式起止、422/401/404/405、NULL 身份诚实 unavailable、部分身份 unavailable、空集真值 0、归因命中/排序/无证据空态/未知 gap、主题投影/×5 稳定/回退/404) |
| `admin/tests/TrackFEvidence.test.tsx`(新增) | 10/10 PASS(meta 三计数、window 透传、unavailable 不编造、源卡深链/空态、主题主副行/回退/失败回退) |
| **pytest 全量(串行,`TEST_DATABASE_URL=…ask_ai_test_f`,HF_HUB_OFFLINE=1)** | **2537 passed / 0 failed / 7 skipped**(基线 2500/0/8;+36 新增;1 项原 skip 的 lifespan smoke 因本环境设置 TEST_DATABASE_URL 转为真实运行并 PASS;总数 2508→2544 逐一对账一致) |
| vitest 全量 | **56 文件 463/463 passed**(基线 453 + 10 新增) |
| tsc(`tsc -b`) | 0 errors |
| build(`tsc -b && vite build`) | ✓ built(chunk 告警为既有) |
| ruff(F-owned .py 四文件) | All checks passed(`Annotated` Query 形态规避 B008;与既有 FastAPI 端点风格一致) |

RED 证据:实现前运行 `ModuleNotFoundError: backend.services.gap_topic` + 端点 404/405 缺失(先测后码)。

## 4. 真实运行时验收(本地栈 8126/5226;seed 仅本地、仅 WF_ 前缀追加)

栈:backend `ASKAI_API_PORT=8126`(health git_sha=d613e6aa)+ vite 5226;登录 admin@camthink.ai。

**Seed(runtime-seed/seed.sql,SQL 全文随交付)**:数据源 `wf-woo-ne101`(woocommerce/ne101)、`wf-github-ne101`(github/ne101);gap 簇 A1(4 会话/3 个不同伪匿名会话 WF_seed_s1..s3,引用 woo+github 真值)、A2(2 条历史行 session_id 全 NULL)、A3(单问句+有身份);不触碰任何既有行。

**三角核对(SQL=API=UI)**:

| 项 | SQL 权威值 | API | UI |
|---|---|---|---|
| A1 users(all/30d/7d) | count=4 / with_sid=4 / **distinct=3** | users=3, available=true | 「涉及 3 个用户」 |
| A1 users(today) | 2/2/2 | users=2 | — |
| A1 users(from/to 近5日) | 4/4/3 | users=3, 窗口回显实际起止 | — |
| A2 users(历史 NULL 行) | 2/0/0 | **users=null, unavailable=session_identity_insufficient** | 「涉及用户 证据不可用」(零编造数字) |
| 既有历史簇(未 seed,天然案例) | 2/0/0 | 同上诚实 unavailable | 同上(截图 05) |
| A3 users | 1/1/1 | users=1 | 回退主题列正常 |
| A1 sources | (woocommerce,ne101)=3 会话;(github,ne101)=2 会话 | items=[wf-woo-ne101(3), wf-github-ne101(2)], evidence_rule=conversation_citation_identity_match | 2 张源卡,href=/admin/data-sources/… |
| A1 sources 深链 | — | — | 点击真实到达源详情页(截图 03) |
| A2 sources | 引用=0 | items=[] | 「无归因证据:归属会话无引用来源记录,系统不做猜测」 |
| A1 topic ×5 | — | "NE101 PoE" 逐字节同值 ×5 | 队列主题列「NE101 PoE」+ reload 同值 |
| A2 topic | — | "展会报名"(CJK 极大公共子串) | 队列主题列同值 |
| A3 topic | — | null + fallback=代表问句 | 主行回退代表问句 |
| 负向门 | — | 未认证 401 / window 词表外 422 / 未知 gap 404 / POST 405 | — |

UI 断言脚本 `ui-verify.mjs`(Playwright Chromium 1536×1024 @1x):**15/15 PASS**(logs/ui-verify.txt)。

## 5. 视觉证据(screenshots/,1536×1024 @1x)

1. `01-queue-topic-column.png` — 队列「问题 / 主题」列:主题式标题(NE101 PoE/展会报名)+代表问句副行 + 回退行(WF 独有问法样例缺省簇)
2. `02-panel-users-sources.png` — 侧板 meta 三计数(12 次相关提问 · 4 次受影响回答 · 涉及 3 个用户)+ 相关数据源双卡(含外链 icon)
3. `03-source-detail-deeplink.png` — 源卡外链真实到达 /data-sources/wf-woo-ne101
4. `04-panel-users-unavailable.png` — A2 历史行:「涉及用户 证据不可用」诚实态(零编造)+ 无归因证据空态
5. `05-panel-historical-cluster-unavailable.png` — 既有未 seed 历史簇天然 unavailable(诚实 unavailable 与参考 PNG「证据不可用」纪律并存)

对照参考 PNG 呈现目标:meta 三项计数并排 ✓、源卡+外链 ✓、主题式标题行 ✓(主题短语为确定性派生,非 LLM 文案;参考的「支持信息缺失」类解释性后缀属 LLM 语义,冻结规则下以忠实公共因子短语呈现)。

## 6. Ownership / Interface 说明

- **Ownership violations:无**(§1 逐项核验;tech.py 零编辑 — tech_evidence 路由在 F 专属文件内生效)。
- **Interface expansions:无新增跨轨接口**。说明两点:① `PanelStats` 新增 `window?: EvidenceWindowValue` prop = IF-7 共享分析窗接线点(默认 "all";接线动作属 Integration 壳合并工序,F 未改任何壳文件);② 新增 3 个 F 专属只读端点(OpenAPI paths 89→92,均为合同授权的 Track F 交付物)。
- **共享测试文件修订**:TechInsightConvergence.test.tsx 两处「无 个用户」断言(v1.6.3 B2 冻结缺席)因 U-17 落地而过时,修订为「计数仅来自权威聚合、不可用态不出现编造数字」(比原断言更强),diff 仅此 2 块(§7)。

## 7. TechInsightConvergence 修订 diff(全文)

```diff
-  it("v1.6.3 未授权能力不出现:无 导出相关对话 / 开始观察 / 内容已补充 / 涉及用户数", ...
+  it("v1.6.3 未授权能力不出现:无 导出相关对话 / 开始观察 / 内容已补充;U-17 用户计数仅权威(不编造)", ...
-    expect(screen.queryByText(/个用户/)).not.toBeInTheDocument();
+    // Wave 1 U-17 修订(原 v1.6.3 B2 断言「无 个用户」):「涉及用户」槽位已由
+    // Track F 落地,计数只能来自后端权威聚合(techEvidence);本 mock 环境无
+    // 权威聚合 mock → 槽位必须呈诚实 unavailable,不得出现任何编造数字。
+    expect(screen.queryByText(/涉及 \d+ 个用户/)).not.toBeInTheDocument();
+    await waitFor(() => { expect(document.querySelector("[data-panel-users]")?.textContent).toContain("证据不可用"); });

-  it("侧板标题=代表问题 + 状态徽章;统计行=相关提问/受影响回答 + 最近发生(无用户数)", ...
+  it("侧板标题=代表问题 + 状态徽章;统计行=相关提问/受影响回答 + 涉及用户(U-17)+ 最近发生", ...
-      expect(stats).not.toContain("个用户");
+      expect(document.querySelector("[data-panel-users]")?.textContent).toContain("证据不可用");
+      expect(stats).not.toMatch(/涉及 \d+ 个用户/);
```

## 8. 交付物清单

- 分支 commits(本报告随代码 commit 于 `track/v163-f-evidence`)
- 归因/主题规则冻结稿:本文档 §2.2/§2.3(规则 ID:`conversation_citation_identity_match` / `cross_question_common_factor`)
- 隐私评估记录:U-17 聚合仅消费既有 widget 匿名 session_id(String(64) 伪匿名会话 ID,非姓名/邮箱/IP);响应仅含 DISTINCT 计数(测试断言 session 原值零泄漏);U-18 归因仅含源身份 (type, product) 与聚合计数;U-19 仅消费操作者可见问句投影字段;三端点 admin/editor/viewer RBAC、GET-only、可审计(只读无 mutation 面)
- fixture SQL 全文:`/Users/harryhua/Documents/GitHub/ask-ai-acceptance/v163-wave1-f-20260913/runtime-seed/seed.sql`(+sql-triangle.txt)
- 测试日志:pytest/vitest 见 §3 数字;UI 断言 `ask-ai-acceptance/v163-wave1-f-20260913/logs/ui-verify.txt`;API 原始响应 `logs/api-u17-users.txt`、`logs/api-u18-u19-negative.txt`
- 截图:§5 五张(1536×1024 @1x)

## 9. STOP 确认

- 未 merge 任何分支 / 未 deploy / 未关任何 issue(#59 关闭条件为多轨聚合,归 Integration)/ 未新增豁免类 / 未触碰他轨文件与禁区文件 / 未在共享库伪造任何计数或主题
- 本地 dev 库仅追加 WF_/wf- 前缀验收数据(seed SQL 全文留档,cleanup 路径同前缀可逆);测试库 ask_ai_test_f 仅经 conftest 生命周期
- 运行时栈(8126/5226)为候选验收临时栈,报告完成后停止
