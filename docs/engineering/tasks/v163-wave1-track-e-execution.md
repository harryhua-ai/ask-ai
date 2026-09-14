# V1.6.3 Wave 1 Track E 执行报告 — 观察状态机(U-15)+ 导出与隐私(U-16)

- **分支**:`track/v163-e-observation`(worktree `/Users/harryhua/Documents/GitHub/ask-ai-v163-we`)
- **基线**:PREP_BASE/FINAL_PREP_BASE = `d613e6aab787110e6c7839f92dbc28611b79ee7e`(父链 `7e3e71c→c016d50→acc6756→f83740c→d613e6a`,merge-base 复核 = 7e3e71c ✓);开树干净,零混合基线。
- **合同**:track-e-contract.md + IF-1/IF-5(本轨冻结责任)+ remediation plan §3.6(实现依赖 D→E=NONE,未等 D、未 merge/cherry-pick 他轨;D candidate joined 联测按 §3.6 留待 Wave 2,本报告附 joined 联测输入)。
- **Verdict:INTERFACE EXPANSION REQUIRED**(窄义:仅 概览-tab 挂载面;见 §7。U-15/U-16 语义/后端/API/测试/运行时全链 = 100% 实现并验收,除 UI 挂载区域外 candidate ready。)

## 1. Reference IDs 逐项实现矩阵

| 矩阵行 | 需求 | 实现 | 验收证据 |
|---|---|---|---|
| TI-07 | 状态词表含「观察中」过滤 | GapStatusFilter 挂载 observing 选项(值域 ""/open/observing/resolved);后端 GAP_STATUS_PATTERN 三态,gap_status.py 单一真相源,既有消费方零 diff 自动生效 | vitest(filter 选项断言)+ 运行时截图 02 + API `?status=observing` 行集真实 |
| TI-18 | 队列「观察中」蓝点徽章 | StatusBadge observing = 蓝圈形系(◎ 双圈,`--acc` 淡彩蓝底蓝字),延续 A-B2-02 圈形语法 | 截图 01/02(队列蓝标)+ vitest |
| TI-42 | 观察中呈现(队列+侧板+过滤) | 侧板头 StatusBadge 同源;观察态侧板区(观察开始/观察窗/中止) | 截图 03(三面同呈观察中) |
| TI-36 | 「内容补充完成后」区块 | GapObservationSection(E 新文件),文案按参考逐字 | 截图 06 + vitest 逐字断言 |
| TI-37 | 「▷ 内容已补充,开始观察」CTA(副文案逐字「系统将验证数据同步状态，通过后进入观察中。」) | 同上;点击→confirmed=true→后端三前置门(操作者确认+相关源 sync/reindex 成功[真实读 sync_runs]+post-sync 验证[consistency 结构化事实健康];NULL=未知拒绝) | API 链:gate① 409(gates.confirmation=false)/三门过 200 observing/重复 409 invalid_state;运行时截图 06;vitest(409 gates 明细诚实呈现) |
| TI-43 | 观察后转移(期满→已解决) | evaluate(lazy-on-read + 显式批量端点,双机制判定均持久化):复现→OPEN / 满窗(默认 7 天)无复现→RESOLVED;中止→OPEN;**RESOLVED 唯一进入路径=满窗评估,无任何手动 resolve 端点(OpenAPI 断言)** | API 链 G2(复现→open)/G3(模拟期满→resolved);单测 16 项;禁手动 RESOLVED 断言 |
| TI-41 | 历史记录 Tab 流转史 | PanelHistory 重写:时间线=GET observation/events(gap_observation_events append-only;时间戳/actor/from→to);空态诚实「暂无流转记录」 | 截图 03/05/06/07 + API/PG/UI 三角 |
| TI-34 | 推荐操作卡:导出相关对话 | GapExportCard(E 新文件):导出卡真实可点 | 截图 03/06 + 运行时真实下载 |
| TI-35 | 导出隐私说明 | 隐私条逐字:「导出内容包含用户问题、对话上下文、当前回答及引用信息,不包含用户个人身份信息。」 | 截图 03 + vitest 逐字 |
| TI-45 | 真实 CSV 下载 | 后端流式 CSV(text/csv;UTF-8 BOM;attachment);前端 blob 下载(非前端造 CSV) | 运行时 Playwright download 事件落地文件 + 内容断言 |

**Placement 偏差(唯一)**:参考 PNG 将 TI-34/35/36/37 置于侧板 概览 tab;本实现置于 E 冻结挂载面 PanelHistory.tsx(历史记录 tab,Integration 壳唯一 E import 点)。原因=壳禁触(§7)。

## 2. IF-1 / IF-5 冻结稿(Track E 冻结责任交付)

**IF-1(状态词表+观察元数据+流转事件形状)**:
- 词表:`GAP_STATUSES=("open","observing","resolved")`;`GAP_STATUS_PATTERN="^(open|observing|resolved)$"`(backend/services/gap_status.py;analytics.py/tech_answer_gaps.py 零 diff 消费)。
- 元数据表 `gap_observations`:cluster_id/started_at/window_days(默认 7)/window_ends_at/is_active/ended_at/ended_reason(recurrence|aborted|window_elapsed)。
- 事件表 `gap_observation_events`(append-only):cluster_id/event_type(start|recurrence|abort|resolve)/from_status/to_status/actor/detail(JSONB)/created_at。
- 状态权威:`question_clusters.status`(String(20) 既有列,零列变更;零既有表 migration——新表由 create_all additive 建立)。

**IF-5(CSV 列集+隐私排除+审计行形状)**:
- 列集(顺序即契约):`conversation_id, created_at, question, answer, is_answered, sources`(sources 仅投影 `{"title","url"}`,内部 source_id/chunk/score/text 不外发)。
- 排除清单(直接个人身份/身份可关联,零包含):session_id、country、channel、intent_tag、custom_tags、customization_id、site_id、response_time_ms、feedback、gap_status、override_answer(IP/姓名/邮箱在 conversations 本就不存,清单兼作将来禁止加入的契约边界)。
- 审计行 `gap_export_audits`:cluster_id/actor(email)/actor_role/window/row_count/created_at。

## 3. 交付物(18 代码文件:+11 修改 +7 新增,另有本报告)

新增:`backend/services/gap_observation.py`(状态机服务,语义单一来源)、`admin/src/pages/analytics/GapObservationSection.tsx`、`GapExportCard.tsx`、`admin/tests/GapObservationLifecycle.test.tsx`、`tests/api/admin/test_gap_observation.py`(16)、`tests/api/admin/test_gap_export.py`(6)。
修改:`backend/services/gap_status.py`(IF-1 挂载)、`backend/api/admin/tech_observation.py`(5 端点)、`tech_export.py`(2 端点)、`backend/db/models.py`(3 新 E 表 additive+注释)、`GapStatusFilter.tsx`、`StatusBadge.tsx`、`PanelHistory.tsx`、`lib/gapCause.ts`(状态呈现面 E 区)、`lib/gapCause.test.ts`(状态块)、`lib/api/techInsight.ts`(E API 面 additive)、`admin/tests/TechInsightConvergence.test.tsx`(仅 status-face 断言 1 处,见 §7.3)。

端点(router prefix=/tech):`POST /tech/answer-gaps/observation/evaluate`(admin/editor,批量评估,判定持久化)、`GET|POST /tech/answer-gaps/{gap_id}/observation[/start|/abort|/events]`(读=viewer+;转移=admin/editor;全部时间戳+actor 留痕)、`GET /tech/answer-gaps/{gap_id}/conversations/export`(admin-only;window 7d/30d/all 继承队列窗)、`GET /tech/answer-gaps/{gap_id}/export-audits`(admin-only)。

## 4. 测试数字(全绿)

| 门 | 结果 |
|---|---|
| pytest 全量(串行,TEST_DATABASE_URL=ask_ai_test_e,HF_HUB_OFFLINE=1) | **2523 passed / 0 failed / 7 skipped**(基线 2500/0/8 + 本轨 22;零回归;一次通过无 flaky) |
| 其中新增 | 观察状态机 16 + 导出 6 = 22(RED→GREEN;RED 以 ImportError/404 实证) |
| PA(tests/project_automation) | **114/114** |
| vitest 全量 | **56 文件 465/465**(基线 453 + 本轨新增净 12) |
| tsc -b | **0**(非 widget;widget 78 error 噪声=wave0b §10 已知基线逐条同) |
| build | ✓ built(2.13s) |
| ruff | 本轨 7 文件 All checks passed;全仓 301=基线 301 逐项一致(零新增) |

## 5. 运行时验收(ASKAI_API_PORT=8125 + vite 5225;本地库 ask_ai;fixture WE_ 标记,SQL 全文 `fixture-seed.sql`/`replay-state.sh` 存证据目录)

**三 gap 全链真实执行**(G1=完整链,G2=复现路径,G3=满窗路径):
1. seed:源 `we-src-e-runtime`(completed sync run + 健康 consistency 事实)+ 3 gap + 4 会话(引用该源;session_id/country 供 PII 断言)。
2. **前置门实证(API)**:未确认 start → 409 `{code:"gate_failed",gates:{confirmation:false}}`;确认后 start → 200 observing(window_days=7);重复 start → 409 invalid_state。G2/G3 同链进入 observing。
3. **复现路径(G2)**:观察开始后新归属失败会话(SQL 种入)→ evaluate → `observing→open, reason=recurrence`(事件 detail.new_evidence_count=1)。
4. **满窗路径(G3)**:证据时间线回拨 9 天(早于观察起点,模拟期满)→ evaluate → `observing→resolved, reason=window_elapsed`。
5. **中止路径(G1,UI 真实点击)**:中止观察(回到待处理)→ 行徽章 观察中→需要处理;history 出现 abort 事件。
6. **导出链(UI 真实下载)**:点击导出相关对话 → Playwright download 事件落地 CSV:header=IF-5 冻结列集;范围=该 gap 权威对话集 2 行(window=all);`sess-we-*`/`we-src-e-runtime` 零命中(无 PII/无内部路径);content-type text/csv、attachment。审计行落库(admin@camthink.ai/all/2)。
7. **三角一致**:UI 徽章/筛选/侧板/历史 = API(observation/events/export-audits/status=observing 过滤)= PG(question_clusters.status、gap_observation_events 6 条全带 actor+时间戳、gap_export_audits)逐项核对一致(§运行时转写)。
8. RBAC 实证:editor 导出 403(U-16 admin-only);editor 观察命令=操作者角色允许(admin/editor 既有 EditorDep 约定),非法态 409;viewer 转移 403、读面 200(单测覆盖)。

## 6. 视觉证据(1536×1024 @1x,ask-ai-acceptance/v163-wave1-e-20260913/)

01-queue-full(观察中蓝标行)/ 02-filter-observing(观察中过滤=唯一权威行集)/ 03-panel-observing-history(观察窗 meta+中止+导出卡+隐私条+start 流转)/ 04-panel-export-clicked / 05-panel-after-abort(abort 事件)/ 06-panel-open-cta-recurrence-history(内容补充完成后+蓝 CTA+副文案逐字+复现流转)/ 07-panel-resolved-history(满窗 resolve 流转)/ export-download-runtime.csv / dom-assertions.log(22/22 PASS)/ ui-chain.mjs / fixture-seed.sql / replay-state.sh。

## 7. Ownership audit / Interface expansion / 声明

**7.1 零触碰(逐项核验 git status)**:AnswerGapsTab.tsx、GapPanel.tsx、GapCauseFilter/CauseBadge/DiagnosisConclusion(D)、gap_taxonomy.py(D)、PanelStats/GapTopicCell(F)、tech_evidence.py(F)、tech.py 装配、tech_performance/tech_generation_events/tech_answer_gaps、data_sources 面、Sidebar/Layout —— 全部零 diff。

**7.2 声明 1(additive 共享文件)**:`backend/db/models.py` = 3 张 E 新表 class 追加(共享模型注册表,不在禁触清单;init_db create_all additive,零既有表列变更)。

**7.3 声明 2(Integration 测试 status-face)**:`TechInsightConvergence.test.tsx` 1 个用例的 status 断言按 IF-1 三态更新(「观察中不得出现」→「filter 选项在位+fixture 无 observing 行故无观察中徽章」);该断言冻结的 v1.6.3 两态词表正是本轨被授权变更的面(同 D 先例改 gapCause.test.ts cause 块)。其余用例零动且全绿。

**7.4 INTERFACE EXPANSION REQUIRED(唯一;窄义)**:参考 PNG 权威将 内容补充完成后/开始观察 CTA/导出卡/隐私条 置于侧板 **概览 tab**;GapPanel.tsx(Integration 壳,本轨禁触)未预留该 E 挂载点(wave0b 仅预挂 PanelHistory 于 历史记录 tab),故本实现按 wave0b §10.2/§10.4 冻结落位("渲染挂载面 Wave 1 由 E 在自有文件落地;Integration 壳不预设")将三区块置于 PanelHistory.tsx(历史记录 tab)。**请求 Integration 二选一**:
- (a) 授予 GapPanel.tsx 概览 tab 挂载(约 2 import+2 行:`<GapObservationSection gap={gap}/>`、`<GapExportCard gap={gap}/>` 组件已自包含,props=gap;PanelHistory 同时收回两区块保留纯时间线)→ 参考逐字逐位对齐,TI-34/35/36/37 可判 MATCH;
- (b) 接受现冻结落位(历史记录 tab,功能/文案/交互与参考一致,仅面板区域不同)→ 建议矩阵验收时对 TI-34/35/36/37 的「面」位记录呈现区域偏差。
无其他 expansion;无 Blockers;joined 联测(§3.6)输入已就绪:观察核验不消费 D 词表,联测点=分类×观察态共存(队列 chips×状态过滤同源)+ 本轨 status 过滤与 D cause 过滤正交组合(单测已含 status 面回归,joined 时按 D 实际词表复跑 22 项观察/导出测试即可)。

## 8. Issue 映射与 STOP 确认

- 落地后可关:**#58**(gap 状态机)、**#59**(导出部分;TI-34/35/45)。
- STOP 确认:未 merge 任何分支/未 deploy/未关 issue;未触碰他轨文件(§7.1);禁捷径零发生(无 unpersisted 转移——转移必落 gap_observation_events;无前端 fake CSV——真实后端流式+blob 下载;无跳过核验进入观察——三门后端权威;无直接强转 RESOLVED——唯一路径=满窗评估,OpenAPI+测试断言);本地 seed WE_ 标记仅本地,SQL 全文存档;rem 基准树零改动;runtime 栈(8125/5225)验收后停止。
