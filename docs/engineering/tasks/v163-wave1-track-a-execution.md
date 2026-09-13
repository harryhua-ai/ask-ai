# V1.6.3 Wave 1 — Track A 执行报告(Shared Chrome + Analysis Window)

- 日期:2026-09-13
- 执行者:Track A 执行 agent
- 分支:`track/v163-a-chrome`(worktree `/Users/harryhua/Documents/GitHub/ask-ai-v163-wa`)
- 基线:HEAD 起点 = `d613e6aab787110e6c7839f92dbc28611b79ee7e`(FINAL_PREP_BASE;父链
  `7e3e71c → c016d50 → acc6756 → f83740c → d613e6a` 开工前复核一致;
  `merge-base(HEAD, 7e3e71c) = 7e3e71c` ✓,无 planning b054d9f、无 origin/main 5c50191 混入)
- 冻结合同:`track-a-contract.md` + IF-6/IF-7 + remediation plan §3.5 能力矩阵(Outcome B)+ §6 授权包
- 性质:DEF-A1 + GAP-SC-1(SH-09/U-2,含 BC-1/BC-2)+ GAP-SC-3(SH-12/U-4);SH-10/11 = UADC-4 缺席仅记录

---

## 1. 交付范围与参考需求映射(Implemented Reference IDs)

| ID | 内容 | 落地 |
|---|---|---|
| **SH-06 / DEF-A1** | 侧栏新增「系统」分组,用户管理/系统信息移入 | `Sidebar.tsx`:SYSTEM_ITEMS 分组渲染(运营/配置/系统 三组);既有分组语义保留(数据源仍在配置组);对照 PNG2 |
| **SH-16 / U-1** | LIGHT 侧栏=权威方向 | 既有实现已浅色(截图 01 对照 PNG2),按合同零动作 |
| **SH-10/11 / U-3 / UADC-4** | Help Center 入口推迟 | 未实现(零入口);vitest+runtime 双断言「帮助中心」缺席 |
| **SH-12 / GAP-SC-3 / U-4** | 侧栏收起(纯 Admin shell) | 收起/展开按钮(底部,对照 PNG2「收起菜单」语法);收起态=icon-only rail+布局重排;状态持久前端 localStorage(`askai.admin.sidebar.collapsed`);零后端、零产品语义副作用 |
| **SH-09 / GAP-SC-1 / U-2** | 技术洞察分析窗 | IF-7 单一共享窗状态 + 三控制面(顶栏/缺口工具栏/tech tab TimeFilter)+ 窗口面 S1/S2/S5 真实联动;BC-1/BC-2 参数能力(§2/§3);顶栏控件仅在 `/analytics` 呈现(非全站假全局过滤,对照 PNG1 数据源面顶栏无日期控件) |
| **S3/S4/S6** | 例外面冻结 | **零改动声明**:IncidentSection(sync-runs/generation-events)与 GapPanel 相关对话零 diff;tech_generation_events.py/tech.py 零 diff;未借例外引入窗口假联动 |
| **S7/S8** | 死导出 | 零消费、零新增消费 |

## 2. IF-7 分析窗合同落地

- **词表(冻结)**:`{今日 today, 过去 7 天 7d, 过去 30 天 30d, 全部时间 all, 明确起止 range:from/to}`;默认 近 7 天(7d)。
- **单一真相**:`admin/src/lib/analysisWindow.tsx`(新)= 序列化词表 + 解析 + React context;
  序列化值同时是 S5 `window` 查询参数值与三控制面受控值。Provider 挂载 Layout;隔离渲染回退局部状态(既有测试零回归)。
- **窗口语义定案(跨面一致)**:today=UTC 日历日 [00:00Z, now];7d/30d=[now-Nd, now](与 S1 既有 range 语义一致);
  all=显式起止表达 [2000-01-01, now](ALL_TIME_FROM 锚点);显式起止=[起日 00:00Z, 结束日 23:59:59.999Z](结束日全天含)。
  from/to 以无时区后缀 UTC ISO 传输(后端 fromisoformat+UTC 语义确定)。
- **三控制面**:
  1. SH-09 顶栏控件(Layout.tsx,`data-topbar-window`:标签+起止日期+日历 popover,快选四项+显式起止);
  2. TI-10 缺口工具栏窗选择(`AnalyticsWindowControl.tsx` 全文件,`data-filter-window`,与共享状态双向桥接);
  3. tech tab TimeFilter(Analytics.tsx 接线;**from/to 此前被丢弃未发送(§3.5)→ 现以显式起止入共享窗**)。
- **窗口面绑定**:S1 `TechPerfTab`(queryKey 含窗;from/to 真实发送;all/显式窗不发送 range 名 → 禁静默 7d 回退);
  S2 `TechPerfTab`→`SourceHealthSummary`(days=30 硬编码废除,以解析后的 from/to 请求;摘要窗标签=响应窗 echo 权威,缺省回退=端点文档默认 30 天窗);
  S5 `AnswerGapsTab` 经 `AnalyticsWindowControl` 桥接(壳文件零编辑)。

## 3. 后端参数能力(Outcome B;仅参数能力,零新表零新端点)

### BC-1 `/tech/answer-gaps`(`tech_answer_gaps.py` 窗口面)
- `window` pattern:`^(today|7d|30d|all|range:\d{4}-\d{2}-\d{2}/\d{4}-\d{2}-\d{2})$`;
- 新增 `_window_bounds` 解析:today=UTC 日历日;range:from/to=显式起止(结束日全天含);
  非法日历日期/from>to → **422**(fail loud,禁静默回退);default=all(既有值不变);
- 既有语义逐字保留:7d/30d 截断口径不变;last_seen 未知行永不被窗排除;total=过滤后真值。

### BC-2 `/analytics/source-health`(`analytics.py` source-health 窗口面)
- 新增可选 `from`/`to`(ISO 日期或日期时间;缺一 → 422 禁半开窗;倒挂 → 422;非法 → 422);
- 显式形态:评估窗=[from, to](日期形态结束日全天含),响应新增 `window:{from,to}` 权威回显(=实际评估窗)
  + `days`=含首尾天数 + item `window_days` 同步;**days 形态响应形状零变化**(不出现 window 字段);
- DSH-01 语义原样:signal=historical_reliability、MIN_SYNC_RUNS/insufficient_data、partial 计分母不计成功、阈值 ≥0.9/≥0.5/<0.5 不变。

## 4. 变更文件全表(9 修改 + 5 新增;14 文件)

| 文件 | 状态 | 内容 |
|---|---|---|
| `admin/src/lib/analysisWindow.tsx` | A | IF-7 共享窗单一真相(词表/解析/Provider/hook;新文件,Track A) |
| `admin/src/components/Sidebar.tsx` | M | DEF-A1 系统 分组 + U-4 收起/展开渲染(icon-only rail) |
| `admin/src/components/Layout.tsx` | M | AnalysisWindowProvider 挂载 + SH-09 顶栏窗控件(仅 /analytics)+ U-4 折叠状态(localStorage) |
| `admin/src/pages/Analytics.tsx` | M | 局部 range → 共享窗状态;TimeFilter 面绑定(from/to 不再丢弃);TechPerfTab prop `range`→`window` |
| `admin/src/pages/analytics/AnalyticsWindowControl.tsx` | M | IF-7 全词表(今日/明确起止+日期输入)+ 共享状态双向桥接(隔离渲染=纯受控,既有行为零回归) |
| `admin/src/pages/analytics/TechPerfTab.tsx` | M | S1 window prop+from/to 真实发送;S2 绑定共享窗;横幅/摘要窗标签=所选窗;移除内部 RANGE_LABELS/rangeOf 反推 |
| `admin/src/pages/analytics/SourceHealthSummary.tsx` | M | 窗标签 prop(运行时=响应 echo 权威;缺省=端点文档默认 30 天窗) |
| `admin/src/lib/api/techInsight.ts` | M | **窗口参数面前端(IF-6 窗口面,如实声明)**:S1 fetch 参数构建、S2 fetch 签名(days 位置参数逐字兼容 useDataSources)、S5 window 类型拓宽;S3/S4/S6/死导出零 diff |
| `backend/api/admin/tech_answer_gaps.py` | M | BC-1(window 面区域互斥;cause/status 面零 diff) |
| `backend/api/admin/analytics.py` | M | BC-2(source-health 窗口面区域互斥;classify_gap_miss_types 零 diff) |
| `admin/tests/TrackAChrome.test.tsx` | A | RED→GREEN:系统分组/帮助中心缺席/折叠持久/顶栏控件域呈现 |
| `admin/tests/AnalysisWindow.test.tsx` | A | RED→GREEN:词表解析/标签、三控制面绑定、S2 绑定、全词表控件、明确起止流 |
| `admin/tests/AnalysisWindowApi.test.ts` | A | RED→GREEN:S1 from/to 参数构建、S2 签名兼容 |
| `tests/api/admin/test_track_a_window_params.py` | A | RED→GREEN:BC-1 8 用例 + BC-2 7 用例(时间确定性设计:显式窗固定锚点/命名窗相对 now) |

**未触碰(所有权审计)**:AnswerGapsTab.tsx / GapPanel.tsx(Integration 壳)、GapCauseFilter/GapStatusFilter/CauseBadge/DiagnosisConclusion/StatusBadge/PanelHistory/PanelStats/GapTopicCell(D/E/F)、gap_taxonomy.py/gap_status.py、tech_observation/tech_export/tech_evidence.py、tech.py、tech_performance.py、tech_generation_events.py、SourceEditorDrawer.tsx(B)、DataSourceDetail.tsx/data_sources.py(C)、IncidentSection.tsx(S3/S4)、既有测试文件(0 改动)。
文件内区域互斥 diff 实证:analytics.py 零 classify/GAP_MISS 命中;tech_answer_gaps.py 新增行仅 `status_code=422` 命中 status 词;techInsight.ts 4 hunk 全在窗口面。

## 5. 各门验证结果(终局树)

| 门 | 基线 | 本轨结果 | 判定 |
|---|---|---|---|
| backend pytest 全量(串行,HF_HUB_OFFLINE=1,TEST_DATABASE_URL=ask_ai_test_a) | 2500/0/8(收集 2508) | **2516 passed / 0 failed / 7 skipped**(收集 2523 = 基线 2508 + 15 新增;零失败) | PASS |
| PA 套件 tests/project_automation/ | 114 | **114 passed** | PASS |
| admin vitest 全量 | 453/453(55 文件) | **478/478(58 文件)**= 基线 453 + 新增 25;**既有测试零修改** | PASS |
| tsc -b | 0 | **0 error** | PASS |
| npm run build | ✓ | **✓(exit 0;chunk 告警=既有)** | PASS |
| ruff(改动 py 文件) | — | **All checks passed!** | PASS |

RED 记录:后端首跑 10 failed/5 passed(5 个既有语义守卫如预期先绿);前端首跑 11 failed/4 passed → 实现后 focused 全绿(前端 25/25、后端 15/15)。

## 6. Runtime 验收(真实栈;零 mutation)

栈:vite **5221**(`VITE_API_TARGET=http://localhost:8121`)+ backend **8121**(`/health git_sha=d613e6a…`)+ 本地 PG ask_ai(只读)。真实登录 admin@camthink.ai。Playwright Chromium 1536×1024 @1x。

### 6.1 API 三角(换窗真实贯通;`runtime-checks/window-swap-api-evidence.txt`)

- **S1** `/tech/performance`:7d(trace_total=60)≠ 显式 2026-09-10→09-12(**39**);all=60;响应 `kpi.window` echo = 请求窗逐字段。
- **S5** `/tech/answer-gaps`(BC-1 全词表):7d/30d/all=18;**today=10**;**range:2026-09-01/09-09=5**;**range:2026-09-12/09-13=13** → 窗真实过滤;`window=5d`、倒挂 range → **422**。
- **S2** `/analytics/source-health`(BC-2):days=30 既有形状零变化(keys=['days','items'];store-woo 78 次/98.72%=参考 fixture 真值);显式窗 09-06→09-13(**22** 次/95.45%)、08-23→09-05(**56** 次/100%)、2000→2099(78 次)→ 窗真实过滤 + `window` echo=请求窗;缺一/倒挂 → **422**。

### 6.2 UI→API 参数可见变化 + 面板一致(`smoke/dom-assertions.log`,**27/27 PASS,0 FAIL**)

- 顶栏改 30d → UI 实发 `/tech/performance?range=30d&from=…&to=…` + `/analytics/source-health?from=…&to=…`;
- 顶栏显式起止 → S1/S2 实发 `from=2026-09-10…&to=2026-09-12T23:59:59.999`;**摘要标签=「数据源历史可靠性(2026-09-10 → 2026-09-12)」**(无卡片停留异窗);KPI 文本 7d≠显式窗(面板数据真实变化);
- 缺口工具栏与顶栏同步(顶栏显式窗 → 选择器呈显式值);工具栏改 all/today/range → S5 请求参数逐次可见变化;行集 all=10 行 vs 显式窄窗=5 行;
- tech tab TimeFilter 改 30 天 → 实发 range=30d+from/to(且顶栏同步呈现「过去 30 天」=三面一态互证);
- U-4:收起→`data-collapsed=true`+标签隐藏(布局重排)→ reload 仍收起(localStorage)→ 展开恢复;
- U-2 非全站:/data-sources 顶栏无窗控件;UADC-1/V-2 FAB 抑制零回归(/data-sources 无、/conversations 有);既有分组(数据源∈配置)保留。

### 6.3 视觉证据(1536×1024 @1x,对照 PNG2)

`/Users/harryhua/Documents/GitHub/ask-ai-acceptance/v163-wave1-a-20260913/`:01 浅色侧栏+系统分组+顶栏 7d(对照 PNG2 分组语法/收起菜单位);02 顶栏 30d;03 顶栏显式窗(横幅/KPI 随窗);04 缺口工具栏显式同步;05/06/07 队列 all/窄窗/range;08 TimeFilter 30d;09 折叠态;10 折叠持久(reload);11 展开恢复;12 数据源面(无顶栏窗控件+无 FAB);13 对话面(FAB 保留)。`smoke/dom-assertions.log`、`runtime-checks/window-swap-api-evidence.txt` 同目录。

## 7. 数据与隐私

- 本地 PG ask_ai 只读复核(仅 SELECT);测试库 ask_ai_test_a 仅按既有 conftest 生命周期建删表;
- 唯一持久化写入=前端 localStorage 折叠态(U-4 冻结允许的前端持久);
- **零 fixture 注入、零 seed 写入**(现库数据均为既有授权功能链残留,本次只读使用)。

## 8. 禁止捷径自查

- 无全站全局过滤语义(控件仅 /analytics 呈现;数据源页 fetchSourceHealth(30) 既有调用零改动);
- 无 frontend-only fake state(联动全部经 API 参数+响应 echo 双证);无 fake count/window/attribution;
- BC-1/BC-2 仅参数能力:零新表、零新端点、零既有窗口语义变化(days 路径/days 形态响应逐字不变);
- S1 不依赖 range 未知名静默回退(all/显式窗以显式起止表达,不发 range 名);
- S3/S4/S6 零改动、零假联动;S7/S8 零新增消费;未实现帮助中心(UADC-4);
- 未 merge main/planning 分支、未 deploy、未关 issue、未动他轨文件、未新增 JD/ADAPT/豁免。

## 9. Issue 映射

- **#52**(IA 收敛:系统 分组+导航清单修订):本轨交付 SH-06/SH-09/SH-12 → 满足关闭条件,建议 Integration 复核后关闭;
- **#60**(共享 chrome 部分):系统分组/收起/顶栏范围控件贡献。

## 10. STOP 确认

- 仅在本 worktree 追加 commits;未新建 worktree;未 merge 任何分支;未 deploy;未关任何 issue;
- 未触碰他轨 owned 文件(§4 清单);symlink(models/.env、admin/node_modules、widget/node_modules)未提交(gitignored);
- 候选栈(8121/5221)验收后停止。
