# V1.6.3 Wave 0B — STRUCTURAL PREP 执行报告(Integration 轨)

日期:2026-09-13
执行者:Integration 轨 Wave 0B 执行 agent
授权:remediation plan §3.0.1(Wave 0B STRUCTURAL PREP,四零约束)+ §3.0.2(WAVE_0B_BASE_SHA 契约)+ IF-6 拆分地图
性质:纯结构 refactor;**零产品语义 / 零新业务行为 / 零 API 语义 / 零数据模型语义变化**

---

## 1. 基线门记录(§3.0.2 规则 1/5 复核)

- **WAVE_0B_BASE_SHA = `7e3e71cc1d50a19e8625fffcacbe1c0f7b11af76`**(冻结值)。
- Worktree:`/Users/harryhua/Documents/GitHub/ask-ai-v163-0b`,branch `prep/v163-wave0b`。
- 起始树复核(执行 agent 于开工时验证):
  - `git rev-parse HEAD` = `7e3e71cc1d50a19e8625fffcacbe1c0f7b11af76`
  - `git merge-base HEAD 7e3e71c…` = `7e3e71cc1d50a19e8625fffcacbe1c0f7b11af76` → **merge-base = HEAD = WAVE_0B_BASE_SHA**(规则 1 PASS,直接分支,无 planning b054d9f、无 origin/main 5c50191 混入)
  - `git status` = working tree clean(干净起始树)
  - planning 分支文档仅作只读合同证据(ask-ai-v163-audit worktree),零提交进入本实现链。
- models/.env/admin node_modules(+补齐 widget node_modules,均为 symlink,gitignore,零提交)。

## 2. 变更文件全表(16 文件;3 修改 + 13 新增;测试文件改动 = 0)

| 文件 | 状态 | 行数 | 内容 |
|---|---|---|---|
| `admin/src/pages/Analytics.tsx` | M | 1416→108 | 页面壳:默认导出 `Analytics` 不变 + 命名导出 `SourceHealthSummary` re-export(既有测试 import 零改动);tab 状态 + 顶栏 TimeFilter 接线原样 |
| `admin/src/pages/analytics/TechPerfTab.tsx` | A | 315 | 技术性能 tab(S1;逐字迁移含 RANGE_LABELS/STAGE_LABELS/windowLabel/rangeOf) |
| `admin/src/pages/analytics/IncidentSection.tsx` | A | 266 | 事件信号区(S3/S4;IncidentRow/syncRunRow/generationEventRow/SEVERITY_* 逐字迁移) |
| `admin/src/pages/analytics/SourceHealthSummary.tsx` | A | 52 | 数据源历史可靠性摘要(S2;named export,re-export 进壳) |
| `admin/src/pages/analytics/AnswerGapsTab.tsx` | A | 352 | 回答缺口队列 Tab(工具栏/队列表/排序/分页/选择,逐字迁移) |
| `admin/src/pages/analytics/GapPanel.tsx` | A | 315 | 诊断侧板(PANEL_TABS/概览/典型问题/相关对话/诊断详情/历史记录,逐字迁移) |
| `admin/src/pages/analytics/CauseBadge.tsx` | A | 32 | 原因徽章(CAUSE_TONE_STYLE + CauseBadge 逐字迁移) |
| `admin/src/pages/analytics/StatusBadge.tsx` | A | 55 | 状态徽章(圈形图标语法 A-B2-02 逐字迁移) |
| `admin/src/pages/analytics/relTime.ts` | A | 19 | 相对时间共享工具(逐字迁移) |
| `backend/api/admin/tech.py` | M | 765→31 | router 装配:`tech_router = APIRouter(prefix="/tech", tags=["技术性能"])` + 按原路由序 include 三个子模块;`backend/api/admin/router.py` 的 `from backend.api.admin.tech import tech_router` 零改动 |
| `backend/api/admin/tech_performance.py` | A | 482 | GET /tech/performance 实现 + NORMAL_MAX/STAGE_*/FAILURE_KIND_LABELS/HEALTH_*/MIN_CONFIDENT_SAMPLE + _percentile/_classify_trace/_derive_health/_empty_payload 等(逐字迁移) |
| `backend/api/admin/tech_generation_events.py` | A | 114 | GET /tech/generation-events 实现 + GENERATION_EVENT_STATUSES/SEVERITY + _generation_reason_summary(逐字迁移) |
| `backend/api/admin/tech_answer_gaps.py` | A | 222 | GET /tech/answer-gaps + GET /tech/answer-gaps/{gap_id}/conversations 实现 + ANSWER_GAP_WINDOWS(逐字迁移;status/cause pattern 改引常量模块,值逐字不变) |
| `backend/api/admin/analytics.py` | M | 548→559 | **仅常量 import 迁移**:classify_gap_miss_types 的 4 类字面量+未分类兜底 → gap_taxonomy 常量;status Query pattern → GAP_STATUS_PATTERN(值逐字不变) |
| `backend/services/gap_taxonomy.py` | A | 34 | 原因词表常量(既有 4 类 reject/low/召回空/召回不足 + 未分类;**零新增值**) |
| `backend/services/gap_status.py` | A | 16 | 状态词表常量(既有 open/resolved + pattern `^(open|resolved)$`;**零新增值**) |

**测试文件改动 = 0**(admin/tests/* 与 tests/* 零改动;公共入口 `export default Analytics`、`export { SourceHealthSummary }`、`tech_router` 全部保持稳定)。

## 3. 分解映射(IF-6 附录更新稿:文件 → 轨 → 区域)

### 3.1 后端

| 文件 | 区域 | 所有权轨 |
|---|---|---|
| `backend/api/admin/tech.py` | router 装配/挂载入口 | Integration(Wave 0B 落位;Wave 1 挂载新子模块仍归 Integration 仲裁) |
| `backend/api/admin/tech_performance.py` | S1 性能聚合(全文件);窗口参数面(range/from/to) | **Track A**(Wave 1:窗口面接线;§3.5 S1 后端已支持,仅前端接线) |
| `backend/api/admin/tech_generation_events.py` | S4 生成级事件流 | 例外面冻结(§3.5;latest-N 终态流,零窗口参数;Wave 1 不得引入窗口假联动) |
| `backend/api/admin/tech_answer_gaps.py` | 窗口参数面(window/ANSWER_GAP_WINDOWS) | **Track A**(BC-1,Wave 1:window 表达 IF-7 全词表;last_seen 未知保留 + total 真值语义不变) |
| 同上 | cause/分类挂载面(cause 参数、miss_type、miss_type_summary) | **Track D**(Wave 1:词表经 gap_taxonomy.py 挂载,禁止本文件新增词表值) |
| 同上 | status 挂载面(status 参数 pattern) | **Track E**(Wave 1:IF-1 词表经 gap_status.py 挂载;本 Wave 零 observing) |
| 同上 | 归属会话证据(/{gap_id}/conversations) | 例外面冻结(S6;gap 范围证据,零窗口参数) |
| `backend/api/admin/analytics.py` | source-health 窗口面 | **Track A**(BC-2,Wave 1) |
| 同上 | classify_gap_miss_types 分类判定 | **Track D**(Wave 1 扩展;本 Wave 仅字面量→常量引用,值逐字不变) |
| `backend/services/gap_taxonomy.py` | 原因词表常量(IF-2 挂载点) | **Track D**(Wave 1 唯一扩词处;其余轨禁止新增值) |
| `backend/services/gap_status.py` | 状态词表常量(IF-1 挂载点) | **Track E**(Wave 1 唯一扩状态处;本 Wave 零 observing) |
| Wave 1 预留 | tech_observation.py / tech_export.py(E)、tech_evidence.py(F) | 按 §3.2 拆分地图由各轨 Wave 1 自建并挂载(tech.py 头部已声明,零实现) |

### 3.2 前端

| 文件 | 区域 | 所有权轨 |
|---|---|---|
| `admin/src/pages/Analytics.tsx` | 页面壳:共享分析窗状态 + 顶栏范围接线 | **Track A**(Wave 1:IF-7 单一共享窗状态 + 三控制面绑定) |
| 同上 | 域内双 Tab 壳(ShellTab/标题) | Integration(Wave 0B) |
| `admin/src/pages/analytics/TechPerfTab.tsx` | 技术性能面板(含 range prop 窗面) | **Track A**(S1 窗面接线;面板其余=Integration 落位) |
| `admin/src/pages/analytics/IncidentSection.tsx` | 事件信号区 | S3/S4 例外面冻结(Integration;零窗口假联动) |
| `admin/src/pages/analytics/SourceHealthSummary.tsx` | 数据源历史可靠性摘要(days=30 硬编码) | **Track A**(Wave 1:绑定共享窗 + BC-2;DSH-01 语义原样) |
| `admin/src/pages/analytics/AnswerGapsTab.tsx` | status/cause filter | **Track D**(Wave 1) |
| 同上 | 观察态 filter(未来区域,仅注释占位) | **Track E**(Wave 1 IF-1;零占位控件/零观察语义) |
| 同上 | 工具栏窗选择 data-filter-window | **Track A**(Wave 1 IF-7 绑定) |
| 同上 | 队列行 cause chip | Track D(CauseBadge) |
| 同上 | 主题列/用户·源卡 meta 列(未来区域,仅注释占位) | **Track F**(Wave 1 U-19/U-17;零占位控件) |
| 同上 | 队列表/排序/分页/选择 | Integration(Wave 0B) |
| `admin/src/pages/analytics/GapPanel.tsx` | 诊断结论区(data-panel-conclusion) | **Track D**(Wave 1 随 IF-2 扩展) |
| 同上 | 历史记录 tab + 导出卡区(未来区域,仅注释占位;导出卡 absent-by-contract) | **Track E**(Wave 1 U-15/U-16) |
| 同上 | meta 计数区(data-panel-stats) | **Track F**(Wave 1 U-17 挂载面) |
| 同上 | 相关对话 tab | S6 例外面冻结 |
| 同上 | 侧板壳/tab 结构 | Integration(Wave 0B) |
| `admin/src/pages/analytics/CauseBadge.tsx` | 原因徽章(词表消费) | **Track D** |
| `admin/src/pages/analytics/StatusBadge.tsx` | 状态徽章(词表消费) | **Track E** |
| `admin/src/pages/analytics/relTime.ts` | 共享时间工具 | Integration(行为冻结,E 需新增时间语义不得改既有行为) |
| `admin/src/lib/gapCause.ts` | 前端原因/状态词表常量模块(既有,未改动) | 前端单一真相源:词表面=D、状态面=E(Wave 1 经其扩展;与 backend 常量模块同源语义) |

## 4. 行为等价证据(各门)

| 门 | 基线(文档/同环境复核) | Wave 0B 结果 | 判定 |
|---|---|---|---|
| backend pytest 全量(串行,HF_HUB_OFFLINE=1,TEST_DATABASE_URL=ask_ai_test) | 文档基线 2496 passed / 4 failed / 8 skipped(4 failed = test_recovery_semantics BASELINE flaky);**本机同环境 7e3e71c 复核 = 2500 passed / 0 failed / 8 skipped**(scratch worktree ask-ai-v163-0b-base 实测) | **2501 passed / 0 failed / 7 skipped**(收集总数 2508 与基线一致;首轮 2495/5 的 5 失败经双树对照证实为 flaky 族:同批失败于未改动 7e3e71c 树的 tests/scripts 子集运行,复跑全量 0 failed) | **PASS(优于基线)** |
| PA 套件 tests/project_automation/ | 114 passed | **114 passed** | PASS |
| admin vitest 全量 | 453/453 | **453/453(55 文件)** | PASS |
| 测试文件改动数 | 0 | **0** | PASS |
| tsc -b | 0 error(widget 子项目 78 error 噪声=已知正交,基线树实测同为 78) | **0 error**(非 widget;widget 噪声与基线逐条相同) | PASS |
| npm run build | ✓ | **✓(exit 0)** | PASS |
| ruff(全部改动 py 文件) | — | **All checks passed!** | PASS |
| OpenAPI 等价(TestClient app.openapi() JSON 全文 diff) | — | **IDENTICAL**(base vs prep 全 spec 逐字节相同:路径/方法/参数/pattern/tags/operationId) | PASS |
| 运行时 OpenAPI 等价(8104 vs 8105 live /openapi.json diff) | — | **IDENTICAL** | PASS |
| tech/analytics 端点测试子集 | 62 passed | **62 passed** | PASS |
| AST 等价审计(tech.py 拆分:4 端点体+helpers/constants) | — | 4 端点体 unparse 级 IDENTICAL(decorator 装配面与 2 处授权常量引用除外,值逐字不变) | PASS |
| 字面量等价审计(Analytics.tsx 拆分:新旧文件集字符串清单 diff) | — | **零字面量移除**;唯一新增=import 模块路径 | PASS |

pytest flaky 处置记录:首轮候选全量出现 5 failed(test_recovery_semantics×2 计入显示 + test_sync_executor_loop×1 等;日志 tail 截断仅存 3 条 FAILED 行)。处置:(a) 候选树 tests/scripts 子集复跑 = 4 failed(341 passed);(b) **未改动 7e3e71c 基线树同命令同批 = 4 failed(341 passed)** —— 失败集与候选完全一致,证实为环境/时序 flaky(BASELINE 族),非行为漂移;(c) 全量复跑 = 2501 passed / 0 failed / 7 skipped。收敛判定:与文档基线(2496/4/8,flaky 已知)完全一致或更好。

## 5. Runtime smoke(真实栈 A/B 对照)

栈:BASE = rem worktree vite 5184 / backend 8104(7e3e71c);PREP = 本 worktree vite 5185 / backend 8105(`ASKAI_API_PORT=8105 EMBEDDER_DEVICE=cpu uv run python -m backend.main` + `VITE_API_TARGET=http://localhost:8105 npx vite --port 5185 --strictPort`)。同库同数据(本地 PG ask_ai@5432,AUDIT-FIXTURE 只读,零 mutation)。
Playwright(独立 Chromium,1536×1024@1x,真实登录 admin@camthink.ai)。

| # | 对照项 | BASE(5184) | PREP(5185) |
|---|---|---|---|
| 1 | Data Sources list(9 行,badge 文本)/ detail store-woo(title+红色 attention banner+知识内容工作区) | PASS | PASS |
| 2 | 展开诊断(doc-row-toggle chevron → aria-expanded=true → 收起真相 原地展开) | PASS | PASS |
| 3 | sync/activity 区(#sync-activity:同步状态与活动 + 最近活动 timeline) | PASS | PASS |
| 4 | Technical Performance(技术洞察 h1 + KPI 三卡 真实失败/诊断异常/降级恢复 + 事件区标题 + health banner) | PASS | PASS |
| 5 | Answer Gaps 队列(10 行+工具栏+分页)+ 选中行 data-selected + 诊断侧板(meta 计数/诊断结论/tab 集) | PASS | PASS |
| 6 | 双下钻:事件行 → /admin/data-sources/store-woo(title 在);缺口 → /admin/conversations?q=NE101%20是否支持%20PoE,搜索框预填同值 | PASS | PASS |
| 7 | KB-OPS LoginChat FAB 抑制:/data-sources 无 FAB、/analytics 无 FAB、/conversations 有 FAB(.ask-ai-fab) | PASS | PASS |

**两栈各 29/29 PASS;断言逐项一致。**
截图证据对(`/Users/harryhua/Documents/GitHub/ask-ai-acceptance/v163-wave0b-20260913/`):`base/` 与 `prep/` 各 12 张对照(01 列表/02 详情/03 展开/04 同步活动/05 性能/06 队列/07 侧板/08 源下钻/09 会话下钻/10-12 FAB 三面)。**10/12 对逐字节相同(cmp);2 对(01/07,1 与 11 字节差)经目视复核内容一致(动态相对时间/PNG 编码差),零视觉/结构/数据漂移。** DOM 断言全文:smoke/dom-assertions.log;脚本:smoke/capture.mjs。

## 6. Diff audit(7e3e71c → PREP_BASE_SHA 逐文件)

`git diff 7e3e71c --stat`:3 文件修改(admin/src/pages/Analytics.tsx、backend/api/admin/analytics.py、backend/api/admin/tech.py)+ 13 新文件(上表),合计 +85/-2116(修改文件)+ 新文件。逐文件审计:

| 文件 | 审计结论 |
|---|---|
| admin/src/pages/Analytics.tsx | 纯拆出:代码逐字迁往 analytics/*;壳保留 tab 状态/TimeFilter/ShellTab/标题;新增仅 import 与 `export { SourceHealthSummary }` re-export。字面量清单零移除(§4) |
| admin/src/pages/analytics/*(8 文件) | 逐字迁移 + 文件头 Ownership 注释 + 区域占位注释(纯注释,零 UI/语义) |
| backend/api/admin/tech.py | 纯装配:APIRouter 定义 + 3 个 include_router(原路由序)。路由路径/方法/参数/响应形状由 OpenAPI 逐字节 diff 背书 |
| backend/api/admin/tech_*.py(3 文件) | 逐字迁移 + Ownership 头;唯一函数体差异 = 2 处授权常量引用(GAP_STATUS_PATTERN / GAP_MISS_UNCLASSIFIED,值逐字) |
| backend/api/admin/analytics.py | 仅常量 import 迁移(5 处字面量→常量;值逐字;OpenAPI 不变) |
| backend/services/gap_taxonomy.py / gap_status.py | 新增常量模块,既有值逐字;零新增词表值 |
| 测试文件 | **0 改动** |
| 越权项 | **无**(无新端点/无新参数语义/无 BC-1/BC-2 实现/无 observing/无词表扩条/无 fixture 与数据写入/无 UI 文案视觉交互变化) |

## 7. PREP_BASE_SHA

- **PREP_BASE_SHA = `<本报告随附的最终 commit SHA,见分支 tip>`**(= Wave 0B 唯一 commit;分支 `prep/v163-wave0b`,parent = 7e3e71c)。
- 实现父链:`7e3e71c(WAVE_0B_BASE_SHA) → Wave 0B 结构 refactor commit → PREP_BASE_SHA`;零 planning/docs 混入(本报告 add -f 随同一 commit,属 Wave 0B 交付物)。
- Wave 1 A–F 六轨强制全部从该 SHA 分支(§3.0.2 规则 7/8;§3.0.3);Integration 合并时必须核验 merge-base(track, integration) == PREP_BASE_SHA。

## 8. STOP 确认

- 未建 Wave 1 A–F 任何轨道分支/实现;未实现 BC-1/BC-2/观察态/导出/新词表值/新端点;
- 未 merge main、未 merge 任何 planning 分支、未 deploy、未关任何 issue;
- 零 fixture/数据 mutation(本地库只读;测试库 ask_ai_test 仅按既有 conftest 生命周期建删表,零业务数据写入);
- rem worktree(7e3e71c 基准)零改动;scratch 基线 worktree(ask-ai-v163-0b-base)仅作测试运行,已列入清理。
