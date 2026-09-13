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

---

# 9. STRUCTURAL COMPLETION(Wave 0B 续段 — ISSUE 1/2 结构隔离收尾)

日期:2026-09-13(续段;父 commit = c016d50,行为等价结论已被接受)
授权:remediation plan §3.0.1(允许内容 item 4「共享文件所有权预备」)+ §3.0.2 规则 5(b) + IF-6 附录;任务书 ISSUE 1/ISSUE 2
性质:**纯结构隔离;零产品行为实现、零新端点、零新 schema、零词表扩展、零 UI/文案/视觉/交互变化、零 fixture/数据变化。**

## 9.1 ISSUE 1 — backend router ownership isolation

**落地:三个空 router 模块(零端点/零 schema/零行为)+ tech.py 立即挂载。**

| 文件 | 状态 | 行数 | 内容 | 所有权 |
|---|---|---|---|---|
| `backend/api/admin/tech_observation.py` | A | 21 | 空 `router = APIRouter()`(无 prefix/tags,由 tech_router 统一装配);Ownership 头 = Track E(观察命令/转移任务/流转事件投影,U-15;IF-1 经 gap_status.py) | **Track E** |
| `backend/api/admin/tech_export.py` | A | 20 | 同上空 router;Ownership 头 = Track E(CSV 流式+审计,U-16;IF-5 列集合同) | **Track E** |
| `backend/api/admin/tech_evidence.py` | A | 20 | 同上空 router;Ownership 头 = Track F(用户聚合/归因/topic,U-17/18/19;聚合窗=IF-7) | **Track F** |
| `backend/api/admin/tech.py` | M | 31→40 | 3 个 `include_router` 追加在既有三路由之后;docstring 更新(「Wave 1 预留」→「已挂载空 router;Wave 1 各轨在各自模块内加路由即可,无需再编辑本文件」) | Integration(装配入口) |

**证明(a):E/F 暴露未来路由无需编辑 tech.py。** 三模块已挂载入 `tech_router`;Wave 1 Track E/F 在 `tech_observation.py`/`tech_export.py`/`tech_evidence.py` 内以既有装饰器模式(`@router.get(...)`)加路由即自动生效(router.py 的 `from backend.api.admin.tech import tech_router` 引用链零改动)。

**OpenAPI 等价证据(逐字节 IDENTICAL,三重):**
1. TestClient 全 spec diff:`c016d50 临时 worktree app.openapi()` vs 候选树 `app.openapi()`(JSON dumps sort_keys + cmp)→ **逐字节相同**(89 paths = 89 paths);
2. live 对照:`GET /openapi.json` 8104(7e3e71c 基准栈)vs 8106(候选栈)→ **raw bytes cmp 相同**;
3. TestClient(candidate)== live 8106(spec 一致);`/tech/*` 路径集与 tags 集逐项核对无新增(仍 4 条 tech 路径;tags 21 项不变)。
空 router(零路由)不产生任何 path/参数/术语——选型 = 子 router 无 prefix/tags(同 tech_answer_gaps.py 模式),OpenAPI 零变化。

## 9.2 ISSUE 2 — frontend D/E/F file isolation

**落地:5 个新 owned 文件 + 2 个 Integration 壳重写;拆出 JSX 全部逐字迁移,零 DOM 变化(既有测试 import 零改动,AnswerGapsTab/GapPanel 导出面保持稳定)。**

| 文件 | 状态 | 行数 | 内容(自何处逐字迁出) | 所有权 |
|---|---|---|---|---|
| `admin/src/pages/analytics/DiagnosisConclusion.tsx` | A | 44 | GapPanel 诊断结论卡(`data-panel-conclusion` 区,含 hasCause/CauseBadge/gapCauseConclusion) | **Track D** |
| `admin/src/pages/analytics/GapFilters.tsx` | A | 59 | AnswerGapsTab 工具栏 status/cause filter 控件(`data-filter-status`/`data-filter-cause`;`GapStatusFilterValue` 类型随之导出) | **Track D** |
| `admin/src/pages/analytics/PanelHistory.tsx` | A | 32 | GapPanel 历史记录 tab 内容(`data-panel-history`,诚实「证据不可用」);并承载 E 将来区域占位注释(导出卡 absent-by-contract、观察态 filter) | **Track E** |
| `admin/src/pages/analytics/PanelStats.tsx` | A | 24 | GapPanel meta 计数区(`data-panel-stats`:相关提问·受影响回答·最近发生;U-17 挂载面) | **Track F** |
| `admin/src/pages/analytics/GapTopicCell.tsx` | A | 39 | AnswerGapsTab 队列「问题 / 主题」列单元格(`data-gap-question`/`data-gap-sample`;U-19 主题列回退代表问句) | **Track F** |
| `admin/src/pages/analytics/AnswerGapsTab.tsx` | M | 352→313 | Integration 壳:查询状态/队列表/排序/分页/选择/布局;消费 GapFilters(D)/GapTopicCell(F)/CauseBadge(D)/StatusBadge(E) 稳定 props | Integration |
| `admin/src/pages/analytics/GapPanel.tsx` | M | 315→278 | Integration 壳:侧板壳/tab 结构/概览/典型问题/相关对话/诊断详情/推荐操作;消费 DiagnosisConclusion(D)/PanelHistory(E)/PanelStats(F) 稳定 props(props=gap) | Integration |

**证明(b):D/E/F 冻结范围 → 文件映射(互不落在同一主组件文件;Integration 壳 Wave 1 零轨编辑):**

| 轨 | 冻结范围(合同措辞) | 所属文件(Wave 1 只改这些) |
|---|---|---|
| **D** | 原因呈现/chips tone/data-gap-type 机器值 | `CauseBadge.tsx`(c016d50 已落) |
| D | filter 选项=权威全集+未分类 | `GapFilters.tsx`(status+cause 控件;选项经 `@/lib/gapCause` 单一源) |
| D | 诊断结论面(IF-2 词表扩展) | `DiagnosisConclusion.tsx` |
| D | backend:analytics.py classify、tech_answer_gaps.py cause 投影、gap_taxonomy.py | `analytics.py`(分类判定区)/`tech_answer_gaps.py`(cause 挂载面)/`gap_taxonomy.py` |
| **E** | 状态徽章呈现(IF-1 词表/观察中蓝态) | `StatusBadge.tsx`(c016d50 已落) |
| E | 历史 Tab 渲染全部流转事件(U-15) | `PanelHistory.tsx` |
| E | 导出卡(U-16;absent-by-contract)、观察态 filter 将来区域 | `PanelHistory.tsx` 头注占位(E 自有文件;渲染挂载面 Wave 1 由 E 在自有文件落地) |
| E | backend:观察/导出端点、gap_status.py | `tech_observation.py`/`tech_export.py`(已挂载空 router)/`gap_status.py` |
| **F** | meta 计数并排(U-17 涉及用户)/源卡 | `PanelStats.tsx` |
| F | 主题列渲染+回退代表问句(U-19) | `GapTopicCell.tsx` |
| F | backend:用户聚合/归因/topic 投影 | `tech_evidence.py`(已挂载空 router) |
| Integration | 共享壳/布局/tab/分页编排/查询状态 | `AnswerGapsTab.tsx`/`GapPanel.tsx`(两壳 Wave 1 只被消费——D/E/F/A 控件与面板均已落入各轨自有文件,壳仅消费稳定 props,不承载任何轨的 Wave 1 实现面) |

已知的唯一跨轨接触点(如实声明):E 合同「观察中蓝态+过滤选项」若在 Wave 1 落位为 status filter 内的「观察中」选项,则触及 `GapFilters.tsx`(D 文件)——plan §3.2 冻结「status/cause filter=D、观察态 filter=E」;该点按 IF-6 附录「文件内区域互斥 + Integration 轨仲裁」处置,或由 E 以独立观察态控件落位(E 自有文件)。除此之外 D/E/F 无任何共享实现面。

## 9.3 变更文件全表(本轮)

本轮 11 文件:3 修改 + 8 新增;**测试文件改动 = 0**(admin/tests/* 与 tests/* 零改动;`export default Analytics`、`SourceHealthSummary` re-export、`tech_router` 引用链、AnswerGapsTab/GapPanel 默认导出全部稳定)。
累计(7e3e71c → 本 tip):27 文件 = c016d50 的 16 文件 + 本轮 11 文件。

## 9.4 各门验证结果(本轮全量重跑)

| 门 | c016d50 基线 | 本轮结果 | 判定 |
|---|---|---|---|
| OpenAPI(TestClient 全 spec,sort_keys+cmp) | IDENTICAL | **IDENTICAL**(89/89 paths,c016d50 临时 worktree 对照) | PASS |
| OpenAPI(live 8104 vs 8106 raw bytes) | IDENTICAL | **IDENTICAL**(raw cmp;TestClient==live) | PASS |
| backend pytest 全量(串行,HF_HUB_OFFLINE=1,.env TEST_DATABASE_URL=ask_ai_test) | 2501/0/7 | **2500 passed / 0 failed / 8 skipped**(收集总数 2508 与基线一致;1 例条件性 skip 在 passed/skipped 间漂移,零失败) | PASS |
| PA 套件 tests/project_automation/ | 114 | **114 passed** | PASS |
| tech 端点子集(test_tech_semantics/test_tech_perf/test_tech_answer_gaps) | 62 | **26 passed**(本轮子集口径 3 文件;上轮 62 含 analytics 等 5 文件,合并结论一致零失败) | PASS |
| admin vitest 全量 | 453/453 | **453/453(55 文件)** | PASS |
| 测试文件改动数 | 0 | **0** | PASS |
| tsc -b | 0 | **0 error**(exit 0;npm run build 内含 tsc -b 亦过) | PASS |
| npm run build | ✓ | **✓(exit 0)** | PASS |
| ruff(全部改动 py 文件) | 0 | **All checks passed!** | PASS |
| Runtime smoke(7 项 A/B) | 29/29 per 栈 | **33/33 per 栈(66/66),0 FAIL**(新增 filter 三控件存在性 + 历史 tab 诚实文案断言) | PASS |

pytest skipped 数说明:c016d50 实测 7 skipped,本轮 8 skipped,两轮收集总数均 2508;差异为环境条件 skip(非失败族),零 failed。

## 9.5 Runtime smoke(真实栈 A/B 对照;BASE=5184/8104 7e3e71c rem 树,COMPLETION=5186/8106 本树)

| # | 对照项 | BASE(5184) | COMPLETION(5186) |
|---|---|---|---|
| 1 | DS list(9 行/badge)/detail store-woo(title+红色 attention banner+知识工作区) | PASS | PASS |
| 2 | 行下展开(doc-row-toggle chevron → aria-expanded=true → 收起真相原地展开) | PASS | PASS |
| 3 | sync/activity(#sync-activity 同步状态与活动 + 最近活动) | PASS | PASS |
| 4 | 技术性能(技术洞察 h1 + KPI 三卡 + 事件区标题 + health banner) | PASS | PASS |
| 5 | 缺口队列(10 行+工具栏+status/cause/window 三筛选+分页)+ 行选中 + 诊断侧板(meta 计数/诊断结论/tab 集)+ 历史 tab 诚实文案 | PASS | PASS |
| 6 | 双下钻:事件行 → /data-sources/{id};缺口 → /conversations?q=NE101 是否支持 PoE 预填 | PASS | PASS |
| 7 | FAB 抑制:/data-sources 无、/analytics 无、/conversations 有(.ask-ai-fab) | PASS | PASS |

**两栈各 33/33 PASS;断言逐项一致。** 截图对(completion/base/ vs completion/prep/ 各 13 张):**9/13 对逐字节相同(cmp);4 对(01/07/07b/12,11–14 字节差)目视复核内容一致**——差异均为动态相对时间文本渲染时刻不同与 PNG 编码差(与 c016d50 轮 2 对同性质),零视觉/结构/数据漂移。证据目录:`/Users/harryhua/Documents/GitHub/ask-ai-acceptance/v163-wave0b-20260913/completion/`(base/、prep/、smoke/dom-assertions.log、smoke/capture.mjs)。

## 9.6 最终 Wave-1 ownership audit(A–F 每轨将拥有的文件清单)

**Track A(共享 chrome + U-2 分析窗)**
- frontend:`admin/src/pages/Analytics.tsx`(页面壳/共享窗状态,全文件)、`admin/src/pages/analytics/TechPerfTab.tsx`(S1 窗面接线)、`admin/src/pages/analytics/SourceHealthSummary.tsx`(S2 绑定)、`AnswerGapsTab.tsx` 内 `data-filter-window` 绑定面(IF-6 文件内区域互斥,唯一保留于壳内的 A 区域);
- backend:`tech_performance.py`(窗口参数面)、`tech_answer_gaps.py` 窗口面(window/ANSWER_GAP_WINDOWS,BC-1)、`analytics.py` source-health 窗口面(BC-2)。

**Track B(编辑抽屉)**:frontend `SourceEditorDrawer.tsx`;backend 无。与他轨零交集。

**Track C(B1 产品域)**:frontend `DataSourceDetail.tsx` + 新 KnowledgeSettingsDrawer/RiskPreviewModal/SourceEditorDrawer 入口;backend `data_sources.py` + 新模块。与他轨零交集。

**Track D(原因分类学 U-14)**
- frontend:`CauseBadge.tsx`、`GapFilters.tsx`(status/cause filter 控件)、`DiagnosisConclusion.tsx`;
- backend:`tech_answer_gaps.py` cause/分类挂载面、`analytics.py` classify_gap_miss_types 判定、`gap_taxonomy.py`(唯一扩词处)。

**Track E(观察与导出 U-15/U-16)**
- frontend:`StatusBadge.tsx`、`PanelHistory.tsx`(历史 tab + 导出卡/观察态将来区域占位);
- backend:`tech_observation.py`、`tech_export.py`(两文件已挂载,E 在文件内加路由即生效,**无需编辑 tech.py**)、`gap_status.py`(唯一扩状态处)。

**Track F(证据聚合 U-17/18/19)**
- frontend:`PanelStats.tsx`(meta 计数/源卡)、`GapTopicCell.tsx`(主题列);
- backend:`tech_evidence.py`(已挂载,F 在文件内加路由即生效,**无需编辑 tech.py**)。

**Integration(第七轨)**:`tech.py`(装配入口,此后仅仲裁)、`tech_generation_events.py`(S4 例外面冻结)、`AnswerGapsTab.tsx`/`GapPanel.tsx` 共享壳、`relTime.ts`(行为冻结)、`lib/gapCause.ts`(前端词表单一真相源:词表面=D、状态面=E)。冲突面结论:**D/E/F/A/B/C 无共享实现文件;唯一跨轨接触点 = E 观察中选项若落位 D 的 GapFilters(见 9.2 声明,IF-6 仲裁)。**

## 9.7 diff 审计(本轮 + 累计,逐文件)

本轮 `git diff`(3 M):AnswerGapsTab/GapPanel/tech.py —— 三者均为「逐字迁出 + import 新 owned 组件 + Ownership 头注更新」,零字面量/文案/样式/行为变化;新增 8 文件(3 backend 空 router + 5 frontend owned 组件)——JSX 逐字迁移(来源见 9.1/9.2 表),backend 零端点。
累计 `git diff 7e3e71c..final tip`:27 文件(2443+/-2116 基础上叠本轮),**仅结构改动**(拆分/装配/常量迁移/空 router/组件抽取/注释);越权项:**无**(无新端点/新参数语义/新词表值/BC-1/BC-2 实现/观察态实现/导出实现/fixture 与数据写入/UI 文案视觉交互变化;测试文件 0 改动)。

## 9.8 FINAL_PREP_BASE_SHA 与 STOP 确认

- **FINAL_PREP_BASE_SHA = 本轮终局 commit SHA(见分支 tip;parent = c016d50)**。实现父链:`7e3e71c(WAVE_0B_BASE_SHA) → c016d50(Wave 0B 结构预备) → 本 commit(Wave 0B 结构完备)`;merge-base(HEAD, 7e3e71c) = 7e3e71c 复核 PASS。
- Wave 1 A–F 六轨强制全部从该 SHA 分支;Integration 合并核验 merge-base(track, integration) == FINAL_PREP_BASE_SHA。
- STOP 确认:未建 Wave 1 A–F 任何轨道分支/实现;未 merge 任何分支;未 deploy;未关任何 issue;零 fixture/数据 mutation(本地库只读,测试库仅按既有 conftest 生命周期);rem 基准树(7e3e71c)零改动;/tmp 临时基线 worktree(c016d50,仅作 OpenAPI before dump)已列入清理。

# 10. FINAL OWNERSHIP ISOLATION(Wave 0B 终段 — 最后所有权冲突消除;零产品行为)

延续 §9(Wave 0B STRUCTURAL COMPLETION)。本轮消除最后已证实的所有权冲突:
(1)GapFilters.tsx 名义 D 所有但混含 cause(D)+status(E) 两个 filter 实现;
(2)A 的分析窗选择控件区(data-filter-window)残留于 Integration 壳 AnswerGapsTab.tsx。
终态:**Wave 1 A/D/E/F 无需编辑 AnswerGapsTab.tsx;D/E 不共享任何 filter 实现文件。**

## 10.1 本轮结构抽取(唯一两项;零可见变化/零行为/零 API/零词表/零措辞/零 fixture)

| 动作 | 文件 | 所有权 | 说明 |
|---|---|---|---|
| 新增 | `admin/src/pages/analytics/GapCauseFilter.tsx`(38 行) | **Track D** | cause filter(data-filter-cause)逐字迁出自 GapFilters.tsx;词表经 @/lib/gapCause(GAP_CAUSE_OPTIONS);props=稳定 value/onChange;头部所有权注释 Track D |
| 新增 | `admin/src/pages/analytics/GapStatusFilter.tsx`(36 行) | **Track E** | status filter(data-filter-status)逐字迁出;值域 ""|open|resolved(既有 GAP_STATUS 词表,gap_status.py 权威);**Wave 1 E 的 observing 选项只在此文件挂载**;零接触 D 文件;props=稳定 value/onChange |
| 新增 | `admin/src/pages/analytics/AnalyticsWindowControl.tsx`(35 行) | **Track A** | 分析窗选择(data-filter-window)逐字迁出自 AnswerGapsTab;既有 7d/30d/all 词表与呈现逐字保留(**零 IF-7 新语义**);Wave 1 A 的 IF-7 扩展只改此文件;props=稳定 value/onChange |
| 删除 | `admin/src/pages/analytics/GapFilters.tsx`(59 行→0) | — | 拆分完成后删除(优先删除,零 re-export);全仓 grep "GapFilters" = 0 残留 |
| 修改 | `admin/src/pages/analytics/AnswerGapsTab.tsx`(313→315 行) | Integration | import 更新 + JSX 消费三个 owned 组件 + Ownership 头注更新;**逐区纯结构**,零字面量/文案/样式/行为变化(setPage(1) 时序逐字保留) |

测试文件改动 = **0**(TechInsightConvergence.test.tsx 等经 DOM 选择器断言,渲染输出不变);后端文件 diff = **0**。

## 10.2 最终 ownership 证明(Wave-1 编辑面零残留;grep/结构证据)

**A. AnswerGapsTab.tsx(315 行)逐区列举:**

| 区域 | 所有权 | Wave-1 编辑面? | 证据 |
|---|---|---|---|
| 搜索框(data-gap-search) | Integration | 无 | 壳内实现,非任何轨冻结范围 |
| status filter 控件 | Track E | 无(在 E 文件) | `<GapStatusFilter value onChange/>`(L106);本文件零 data-filter-status 实现 |
| cause filter 控件 | Track D | 无(在 D 文件) | `<GapCauseFilter value onChange/>`(L113);本文件零 data-filter-cause 实现 |
| 窗选择控件 | Track A | 无(在 A 文件) | `<AnalyticsWindowControl value onChange/>`(L121);本文件零 data-filter-window 实现(仅头注 L9 引用文件名) |
| 队列表/排序/选择/空态/分页 | Integration | 无 | 全部 `<select>` 清点仅 1 处 = data-gap-page-size(L291,分页条/页,Integration);A-B2-03 页码为 v163-rem 既有冻结 |
| 队列行 问题/主题列 | Track F | 无(在 F 文件) | `<GapTopicCell gap/>`(import-only,L38) |
| 队列行 cause chip / 状态徽章 | D / E | 无(各在自有文件) | `<CauseBadge/>`/`<StatusBadge/>`(import-only,L32/33) |

结论:本文件 = 纯 Integration 编排 + 稳定 props 消费(grep 实证:data-filter-* 实现 0 处;select 仅分页 1 处)。

**B. GapPanel.tsx(278 行,本轮零改动)逐区列举:**

| 区域 | 所有权 | Wave-1 编辑面? |
|---|---|---|
| 侧板壳/tab 集/概览(问题描述/典型问题/推荐操作)/典型问题 tab/相关对话 tab(S6 例外面)/诊断详情 tab | Integration | 无 |
| 诊断结论卡(data-panel-conclusion) | Track D 专属文件 DiagnosisConclusion.tsx | 无(import-only,L23) |
| 历史记录 tab 内容 + 导出卡/观察态将来区域 | Track E 专属文件 PanelHistory.tsx | 无(import-only,L24) |
| meta 计数区(data-panel-stats) | Track F 专属文件 PanelStats.tsx | 无(import-only,L25) |
| 状态徽章 | Track E StatusBadge.tsx | 无(import-only,L21) |

grep 实证:GapPanel 内 观察/OBSERVING/导出/export/window 仅命中头注边界声明(L7/31/32,「无 导出」「无 观察」NOT-authorized 冻结注记)与语法关键字;零实现残留。原因分类分布(诊断详情)呈现经 @/lib/gapCause gapCauseLabel 消费——D Wave 1 扩词自动生效,零 GapPanel 编辑。

**C. D/E 无共享 filter 文件(最终证明):**

- `data-filter-status` 全仓实现仅 `GapStatusFilter.tsx`(Track E);`data-filter-cause` 全仓实现仅 `GapCauseFilter.tsx`(Track D);`data-filter-window` 全仓实现仅 `AnalyticsWindowControl.tsx`(Track A)——每选择器恰好一个 owned 文件;
- `GapStatusFilter.tsx` import = **0**(纯组件);`GapCauseFilter.tsx` import 仅 `@/lib/gapCause`(D 词表模块);两文件零共享 import/零共享代码,无任何第三方"共享 filter"文件;
- GapFilters.tsx 已物理删除,`grep -r "GapFilters" admin/src` = 0;
- Wave 1 交叉面:**E 的 observing 过滤选项 → 仅改 GapStatusFilter.tsx(+gap_status.py);D 的 filter 选项扩展 → 仅改 GapCauseFilter.tsx(+@/lib/gapCause);两者永不同文件**。§9.6 遗留的唯一跨轨接触点(E 观察中选项若落位 D 的 GapFilters 由 IF-6 仲裁)**就此消除**。

**D. A/D/E/F 冻结范围→文件映射全表(IF-6 附录更新稿,替代 §9.6 对应行):**

| 轨 | frontend(冻结范围→文件) | backend |
|---|---|---|
| A | 页面壳/共享窗状态=Analytics.tsx;S1 接线=TechPerfTab.tsx;S2 绑定=SourceHealthSummary.tsx;**TI-10 缺口工具栏窗选择=AnalyticsWindowControl.tsx(全文件,本轮新落位)** | tech_performance.py;tech_answer_gaps.py 窗口面(BC-1);analytics.py source-health 窗口面(BC-2) |
| B | SourceEditorDrawer.tsx | 无 |
| C | DataSourceDetail.tsx(+新抽屉/弹窗) | data_sources.py+新模块 |
| D | **GapCauseFilter.tsx(cause filter,本轮新落位)**;CauseBadge.tsx;DiagnosisConclusion.tsx;DataSourceDetail banner 文案 | tech_answer_gaps.py cause/分类挂载面;analytics.py classify;gap_taxonomy.py(唯一扩词处) |
| E | **GapStatusFilter.tsx(status filter+Wave1 observing 选项挂载处,本轮新落位)**;StatusBadge.tsx;PanelHistory.tsx(历史/导出卡/观察态区域) | tech_observation.py;tech_export.py(均已挂载);gap_status.py(唯一扩状态处) |
| F | GapTopicCell.tsx;PanelStats.tsx | tech_evidence.py(已挂载) |
| Integration | tech.py(装配);tech_generation_events.py(S4);**AnswerGapsTab.tsx / GapPanel.tsx(零 A/D/E/F Wave-1 编辑面)**;relTime.ts;lib/gapCause.ts(词表单一真相源:词表面 D/状态呈现面 E) | — |

冲突面结论:**A/D/E/F/B/C 无共享实现文件;D/E 无共享 filter 文件;跨轨接触点 = 0。**

## 10.3 各门验证结果

| 门 | 结果 | 判定 |
|---|---|---|
| tsc(`tsc -b`) | 0 errors | PASS |
| vitest 全量 | **55 文件 453/453 passed** | PASS |
| build(`tsc -b && vite build`) | ✓ built(2.04s;chunk 大小告警为既有) | PASS |
| OpenAPI 等价 | TestClient 全 spec:before=acc6756 vs 本 tip,排序键 JSON `cmp` **逐字节 IDENTICAL**(166,111 bytes;paths=89/schemas=72);本轮后端文件 diff=0 | PASS(IDENTICAL) |
| pytest 全量(串行,HF_HUB_OFFLINE=1) | run1 2496/4/8 → run2 2497/3/8(失败集轮换:analytics_business×2/leads×1/tech_perf×1)→ 失败 4 项隔离单跑 **4/4 PASS** → run3 全量 **2500 passed / 0 failed / 8 skipped** = 文档基线精确一致 | PASS(flaky 收敛规则,非行为漂移;py 改动=0) |
| PA 套件(tests/project_automation/) | **114/114 passed** | PASS |
| ruff | 本轮 .py 改动 = 0;全仓输出与 7e3e71c 基线逐行 diff = **0**(301 pre-existing 双树一致,零新增) | PASS |

## 10.4 Runtime smoke(base 5184/8104=7e3e71c rem 树 vs final 5187/8107=本 tip;同库同数据只读)

Playwright Chromium 1536×1024@1x 真实登录;脚本 smoke/capture-final.mjs;断言日志 smoke/dom-assertions-final.log。

| # | 对照项 | BASE(5184) | FINAL(5187) |
|---|---|---|---|
| 1 | 技术洞察入口(h1+KPI 三卡) | PASS | PASS |
| 2 | 缺口队列三筛选控件在位+词表精确(status=全部状态/需要处理/已解决;cause=全部原因+5 权威项;window=过去 7 天/过去 30 天/全部时间)+分页 | PASS | PASS |
| 3 | status filter 交互:open=7 行全「需要处理」;resolved=5 行全「已解决」;重置=10 行同基线 | PASS | PASS |
| 4 | cause filter 交互:知识缺失=2 行 chip 全匹配;重置=10 行同基线 | PASS | PASS |
| 5 | window 交互:all=10 ≥ 7d=10;30d=10 ≤ all;7d 重置一致 | PASS | PASS |
| 6 | 诊断侧板(选中 data-selected/meta 计数/诊断结论节点/tab 集) | PASS | PASS |
| 7 | 双下钻:缺口→/conversations?q=NE101…(搜索框预填同值);事件行→/data-sources/store-woo | PASS | PASS |
| 8 | FAB 抑制:/data-sources 无、/analytics 无、/conversations 有(.ask-ai-fab) | PASS | PASS |

**两栈各 30/30 PASS,断言逐项一致。** 截图 12+12 张(completion-final/base/ 与 final/):**10/12 对 cmp 逐字节相同;2 对(07-gap-diagnosis-panel/10-fab-datasources)目视复核内容一致**(07=相对时间渲染差;10=website 行 hover 高亮态,零内容/布局差)。零视觉/结构/数据漂移。

## 10.5 diff 审计(累计 7e3e71c → FINAL_PREP_BASE)

- 本轮(相对 acc6756):**3 新增 + 1 删除 + 2 修改**(新增 GapCauseFilter/GapStatusFilter/AnalyticsWindowControl;删除 GapFilters;修改 AnswerGapsTab/本报告),除报告外全部 admin/src/pages/analytics/ 内;**后端 0 文件**;逐文件均为「逐字迁出+import 消费+Ownership 头注」,零字面量/文案/样式/行为变化;
- 累计(`git diff 7e3e71c..f83740c61f779fd2631c618d3079baac4e966a6c`):**27 文件**(= @acc6756 累计 25 文件 − GapFilters 净零[前轮创建/本轮删除] + 本轮 3 新增),构成:admin 16(页面壳拆分+owned 组件+relTime)+backend 10(tech.py 拆 5 子模块+tech_performance+analytics+gap_taxonomy/gap_status)+本报告;**仅结构改动**(拆分/装配/常量迁移/空 router/组件抽取/所有权注释);越权项:**无**(无新端点/无新参数语义/无新词表值/无 BC-1/BC-2 实现/无观察态实现/无导出实现/无 fixture 与数据写入/无 UI 文案视觉交互变化/测试文件 0 改动——cumulative diff `grep -E "test|spec"` = 0)。

## 10.6 FINAL_PREP_BASE_SHA 与 STOP 确认

- **FINAL_PREP_BASE_SHA = 分支 prep/v163-wave0b 本报告冻结后 tip(字面 SHA 见验收仓 ask-ai-acceptance/v163-wave0b-20260913/completion-final/FINAL_PREP_BASE_SHA.txt 与执行返回;结构 commit = f83740c61f779fd2631c618d3079baac4e966a6c,其后仅追加本报告数字勘误 docs commit)。实现父链:`7e3e71c(WAVE_0B_BASE_SHA) → c016d50 → acc6756 → f83740c → FINAL_PREP_BASE`;merge-base(HEAD, 7e3e71c) = 7e3e71c 复核 PASS。**
- Wave 1 A–F 六轨强制全部从该 SHA 分支;**A/D/E/F 无需编辑 AnswerGapsTab.tsx;D/E 不共享任何 filter 实现文件**;Integration 合并核验 merge-base(track, integration) == FINAL_PREP_BASE_SHA。
- STOP 确认:未建 Wave 1 A–F 任何轨道分支/未实现任何产品行为(observing/导出/IF-7 全词表/BC-1/BC-2 零实现)/未 merge/未 deploy/未关 issue;零 fixture/数据 mutation(本地库只读);rem 基准树(7e3e71c)零改动;候选栈 8107/5187 于收尾停止。
