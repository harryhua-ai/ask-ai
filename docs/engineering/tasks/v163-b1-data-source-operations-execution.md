# v1.6.3 B1 — Data Source Operations Convergence 执行报告

**Track:** B1(Role B1 执行 agent,独立 worktree)
**Branch:** `b1/data-source-ops-convergence-20260913`(从 fresh `origin/main` = `5c501914636ae274bdf54896e3decf86c4584e12` 创建)
**Design baseline:** KB-OPS-V163-002(DESIGN_RECOVERY_REVIEW_V002.md,冻结)
**Hard visual reference:** `docs/product/design/admin-knowledge-ops/references/data-source-operations-original.png`(1536×1024 组合板,7 面板,已由执行 agent 亲自 Read 重读)
**Frozen contract:** v163-b1-data-source-operations-contract.md
**Issues:** #52 #53 #54 #55 #56 + #60 的 B1 适用语法(只读引用,未关闭任何 issue)
**Viewport:** 1440×900 @1x(所有截图统一)

---

## 1. 结论(三门)

| Gate | 结论 | 依据 |
| --- | --- | --- |
| Engineering Gate | **PASS** | admin vitest 404/404(52 文件);`tsc -b` admin 0 error(widget 子项目噪声经本地 node_modules symlink 后归零,环境性、非代码);`npm run build` ✓;改动后端文件 ruff 0 error;全量 pytest **2490 passed, 7 skipped, 0 failed**(`HF_HUB_OFFLINE=1`,`TEST_DATABASE_URL=ask_ai_test`,串行,118s) |
| Functional Gate | **PASS**(FUNCTIONAL DEFECT = 0) | UI ↔ API ↔ 本地 PG 只读 SELECT 三角核对全部 MATCH;既有授权操作(触发同步、编辑抽屉)完成 action→request→backend validation→authoritative state→UI feedback→non-target preserved 全链验证(见 §6) |
| Design Gate | **PASS**(Visual DEFECT = 0;JUSTIFIED DIFFERENCE 13 项待 Role A 裁决) | 9 张真实候选截图 vs 硬参考逐面板比对;每个 material difference 恰好一条 MATCH / JUSTIFIED DIFFERENCE / DEFECT(见 §4 差异账本) |

**Verdict: B1 = CANDIDATE READY(待 Role A 对 13 项 JUSTIFIED DIFFERENCE 裁决)**

---

## 2. 交付物

1. **Branch 已 push:** `git push -u origin b1/data-source-ops-convergence-20260913`
2. **Candidate SHA:** 见 §8(分支 tip)
3. **Changed files:** 见 §3(`git diff --stat main...HEAD`)
4. **RED/GREEN evidence:** `/Users/harryhua/Documents/GitHub/ask-ai-acceptance/v163-b1-20260913/`
   - `red-backend-attention-summary.txt`(8 failed,新端点未实现前)
   - `red-frontend-convergence.txt`(15 failed,收敛组件未实现前)
   - `green-summary.txt` + `green-full-pytest.log`
5. **Runtime evidence:** §7
6. **Screenshots:** §5(9 张,命名 NN-state.png)
7. **Visual Difference Ledger:** §4
8. **Functional Conformance Ledger:** §6
9. **Remaining JUSTIFIED DIFFERENCE:** §4 各条(权威证据齐备,待 Role A)
10. **Counts:** Visual DEFECT = **0**;Functional DEFECT = **0**;JUSTIFIED DIFFERENCE = **13**
11. **Scope audit:** §9

---

## 3. Changed files(`git diff --stat main...HEAD` + 新增)

修改(9):
- `backend/api/admin/data_sources.py`(新增只读 GET attention-summary;documents 端点 additive 只读参数 bucket/order/source_type,默认行为不变)
- `backend/api/admin/schemas.py`(SourceAttentionSummaryItem/Response 只读 schema)
- `admin/src/hooks/useDataSources.ts`(useAttentionSummary/fetchAttentionSummary 只读 hook)
- `admin/src/hooks/useDataSourceWorkspace.ts`(documents 查询 additive 参数)
- `admin/src/pages/DataSources.tsx`(收敛为扫描优先列表)
- `admin/src/pages/DataSourceDetail.tsx`(收敛为恢复的运营者层级)
- `admin/tests/DataSources.test.tsx`、`admin/tests/FinalPolish.test.tsx`、`admin/tests/dataSources/DataSourceDetail.test.tsx`(按收敛后行为更新;更新清单见 §10)

新增(9):
- `admin/src/lib/dataSourceOps.ts`(呈现层唯一映射:相对时间/操作者状态/原因类投影/周期人性化/活动时间线)
- `admin/src/lib/sourceEditorModel.ts`(编辑器纯模型,自 DataSources.tsx 原样抽出,单一出处)
- `admin/src/components/ui/sheet.tsx`(右侧抽屉原语,radix dialog 基)
- `admin/src/components/ui/dropdown-menu.tsx`(紧凑 ⋯ 菜单原语)
- `admin/src/components/dataSources/SourceEditorDrawer.tsx`(§4.5 context-preserving 编辑抽屉,表单逻辑逐字等价迁移)
- `admin/src/components/dataSources/SyncActivityPanel.tsx`(panel 4 同步状态与活动)
- `admin/tests/dataSources/dataSourceOps.test.ts`、`admin/tests/dataSources/DataSourcesConvergence.test.tsx`、`admin/tests/dataSources/DataSourceDetailConvergence.test.tsx`(RED 先行行为测试)
- `tests/api/admin/test_data_source_attention_summary.py`(后端新读面 pytest)

---

## 4. Visual Difference Ledger(逐面板;每条恰好一档)

判定基准 = 硬参考 7 面板逐元素;「MATCH」含对权威数据形状的 ADAPT(KB-OPS-V163-002 §2 分类),内容数值随本地代表性数据而不同,不构成 material difference。

### Panel 1 数据源列表(截图 01)

| # | Reference 元素 | 判定 | 说明/权威证据 |
| --- | --- | --- | --- |
| 1 | 面包屑 配置>数据源 | MATCH | 01 截图 |
| 2 | 标题 数据源 + 副标题(管理知识来源) | MATCH | 01 |
| 3 | 主按钮「+ 添加数据源」 | MATCH | 位置/标签一致;颜色见 #4 |
| 4 | 主操作蓝色(primary blue) | **JUSTIFIED DIFFERENCE** | 实现用共享主题 token `bg-primary`(近黑)。改全局主色属 Integration 的 shared grammar(#60)与 B2 共享面,单轨擅改将分裂共享视觉语言;待 Role A/Integration 统一裁决。引用:#60 Frozen Amendment、合同「Preserve the broader shared Admin IA」 |
| 5 | 搜索框 搜索数据源 | MATCH | |
| 6 | 状态/类型过滤 | MATCH | 呈现层过滤;状态词表 = 操作者状态(权威值映射) |
| 7 | 列集 名称/类型/状态/知识数量/需处理/最后同步/操作 | MATCH | 原 历史可靠性/同步间隔 列移除(次级证据入徽章 title 与编辑抽屉),扫描优先 |
| 8 | 需处理 = 一等红色计数列,零值 — | MATCH | 计数 = 后端 attention-summary 权威投影(3/1/3 红,零 —) |
| 9 | 状态徽章 需处理(红)/正常(绿)/待分类(琥珀)/同步失败(红) | MATCH | 四态全部由权威值映射出现(last_sync_status/attention-summary/sync-health overall/enabled) |
| 10 | 最后同步相对时间(2小时前) | MATCH | 精确时间 title 保留(#54) |
| 11 | 千分位知识计数(1,204) | MATCH | toLocaleString 已实现;本地数据集无千位量级 |
| 12 | 异常优先排序 | MATCH | 同步失败/需处理行置前(呈现层) |
| 13 | 页脚 共 N 个数据源 | MATCH | 共 5 个数据源 |
| 14 | 操作列紧凑(⋯) | MATCH | 详情/同步/编辑 + ⋯(可观测性/重试删除/删除);既有操作全保留 |

### Panel 2 数据源详情(截图 03/08)

| # | Reference 元素 | 判定 | 说明/权威证据 |
| --- | --- | --- | --- |
| 15 | 面包屑 配置>数据源>名称 | MATCH | |
| 16 | 身份区 logo | **JUSTIFIED DIFFERENCE** | 参考为 WooCommerce 品牌图;后端无 logo 资产权威真值,伪造品牌图像被禁止;实现用首字母 avatar |
| 17 | 名称 + 需处理徽章 | MATCH | |
| 18 | 副标题 类型 \| URL | MATCH | 附源 id 次级证据(#54 允许精确证据次级) |
| 19 | 右侧 最后同步 相对时间 · 部分成功(琥珀) | MATCH | 权威 = /data-sources last_sync_*(partial→部分成功) |
| 20 | 右侧 N 条知识 · M 项需处理(红) | MATCH | 权威 = /documents 聚合(8/3) |
| 21 | 红色 attention banner:标题+原因摘要+查看需处理+关闭 | MATCH | 原因摘要 = 权威生命周期计数逐类投影(2 项源内容缺失…+1 项现行版本缺失…) |
| 22 | 知识内容:搜索+筛选+共 N 条+排序 | MATCH | 排序 = documents 端点 additive 只读 order 参数(默认原行为) |
| 23 | 表列 名称/类型/状态/当前版本/服务/更新时间/操作 | MATCH | |
| 24 | 类型列 内容类型(商品/页面/文档) | **JUSTIFIED DIFFERENCE** | 后端无逐文档内容类型真值;仅 documents.source_type 存在。KB-OPS-V163-002 §5.3:无统一分类不得推断 |
| 25 | 状态列 正常/需处理/待分类 | MATCH | 映射:active∧serving→正常;missing_candidate→需处理;active∧¬serving 与 discovered→待分类(证据不足);superseded/deleted→已退役 |
| 26 | 服务列 正常/不完整 10/12(部分服务分数) | **JUSTIFIED DIFFERENCE** | 逐文档「部分服务分数」无权威真值;实现二值 在服/不在服(/documents 权威 serving 关系);编造分数被禁止 |
| 27 | 行内 处理 按钮 | **JUSTIFIED DIFFERENCE** | #54 Frozen Amendment:行级修复仅在既有权威操作存在时允许;后端无该操作,新变更语义被禁止 |
| 28 | 更新时间人性化 | MATCH | 相对时间 + ISO 次级 |

### Panel 3 展开行诊断(截图 04)

| # | Reference 元素 | 判定 | 说明/权威证据 |
| --- | --- | --- | --- |
| 29 | 问题(操作者语言) | MATCH | = notServingReason(权威字段唯一出处) |
| 30 | 源内容状态 | MATCH | 源中缺失(宽限中) 徽章(权威 lifecycle) |
| 31 | 当前有效版本 | MATCH | v1(active)·生效自(权威版本链);缺席→「后端无此记录」 |
| 32 | 当前服务 | MATCH | 在服 + 持久 chunk 数(chunk 账本计数) |
| 33 | 系统已自动尝试恢复注记 | **JUSTIFIED DIFFERENCE** | 逐文档自动恢复次数无后端真值;sync_runs.recovery 为源级,归属到文档即伪造 |
| 34 | 重新处理 按钮 | **JUSTIFIED DIFFERENCE** | 合同 Forbidden「New reprocess/remediation semantics」;页面如实标注「行级修复操作需待权威修复契约(v1.6.3 不提供)」 |
| 35 | 处理后绿色验证结果卡(一致性验证 通过) | **JUSTIFIED DIFFERENCE** | 依赖 #34 的修复动作;无动作即无验证语义 |

### Panel 4 同步状态与活动(截图 05)

| # | Reference 元素 | 判定 | 说明/权威证据 |
| --- | --- | --- | --- |
| 36 | 最近成功 | MATCH | sync_runs×sync_log success 最近(row 4) |
| 37 | 下次同步 4小时后 | **JUSTIFIED DIFFERENCE** | 后端无下次调度权威真值;编造倒计时被禁止;以「同步周期 每 X 小时」承载 cadence 真值(sync_interval) |
| 38 | 最近结果 部分成功(琥珀) | MATCH | last_sync_status=partial 本地化 |
| 39 | 同步可靠性 98.7% | MATCH | /analytics/source-health 30 天窗口成功率;样本不足→「暂不评估」不编百分比(#21);窗口/分母在 title |
| 40 | 最近活动时间线 异常优先 | MATCH | 红(同步失败+错误摘要)/琥珀(部分成功)/绿(完成+新增)/灰;时间倒序,异常视觉优先 |
| 41 | 常规无变更运行压缩 | MATCH | 「N 次常规同步(无变更)」单组节点,可展开逐条核证(#56) |
| 42 | 技术证据可展开 | MATCH | 每个 run 事件 details(副作用/业务结果/fallback) |

### Panel 5 编辑数据源 Drawer(截图 06)

| # | Reference 元素 | 判定 | 说明/权威证据 |
| --- | --- | --- | --- |
| 43 | 右侧抽屉、不离开运营上下文 | MATCH | §4.5 context-preserving |
| 44 | 取消/保存 | MATCH | |
| 45 | 字段集为简化形(名称/连接/类型禁用/自动同步/周期) | MATCH(字段超集) | §4.5:「full editor capability remains authoritative」— 完整编辑器(类型/产品线/间隔/状态/连接配置/发现策略/上传)原样保留 |
| 46 | 类型 禁用 | **JUSTIFIED DIFFERENCE** | 类型编辑是既有授权能力;禁用=移除既有操作,未被授权(§10「preserve existing already-authorized safe operations」) |

### Panel 6 知识设置 Drawer

| # | Reference 元素 | 判定 | 说明/权威证据 |
| --- | --- | --- | --- |
| 47 | 时态角色/新鲜度要求 Drawer | **JUSTIFIED DIFFERENCE(未实现)** | KB-OPS-V163-002 §4.6 = NEW REQUIREMENT;v1.6.3 §10 明确 NOT authorized;无真值不实现(截图 03/08 页面断言无该词表) |

### Panel 7 高风险变更影响预览 Modal

| # | Reference 元素 | 判定 | 说明/权威证据 |
| --- | --- | --- | --- |
| 48 | 预览+受影响知识计数+确认变更 | **JUSTIFIED DIFFERENCE(未实现)** | §4.7 NEW REQUIREMENT;「No UI may fabricate affected counts」;预览 API/语义契约不存在 |

### 计数

- **Visual DEFECT = 0**
- **JUSTIFIED DIFFERENCE = 13**(#4、#16、#24、#26、#27、#33、#34、#35、#37、#46、#47、#48;共 12 条编号、13 项——以编号清单为准:#4,#16,#24,#26,#27,#33,#34,#35,#37,#46,#47,#48 = 12 项)

> 勘误:最终清点为 **12 项 JUSTIFIED DIFFERENCE**(上表 12 个编号),Visual DEFECT = 0。

---

## 5. Screenshots(1440×900 @1x,playwright-cli 真实自动化)

目录:`/Users/harryhua/Documents/GitHub/ask-ai-acceptance/v163-b1-20260913/`

1. `01-source-list.png` — 扫描优先列表(状态/知识数量/需处理/相对时间/⋯ 操作/页脚)
2. `02-source-detail-normal.png` — 详情常规层级(Help Center:身份→操作者状态→右侧摘要→知识内容→同步状态与活动)
3. `03-source-detail-needs-attention.png` — 需处理详情(WooCommerce:红色 banner+权威原因摘要+3 项需处理)
4. `04-expanded-diagnosis.png` — 展开行只读诊断(问题/源内容状态/当前有效版本/当前服务/生成真相)
5. `05-sync-activity.png` — 同步状态与活动(最近成功/最近结果/可靠性/周期+异常优先时间线+压缩组)
6. `06-edit-source-drawer.png` — 编辑数据源右侧抽屉(完整编辑器能力)
7. `07-local-diagnostics.png` — 本地诊断(五维健康+索引生成失败证据原文)
8. `08-attention-filter.png` — 查看需处理(服务端 bucket 过滤,共 3 条)
9. `09-list-observability-expanded.png` — 列表既有可观测性展开(失败运行卡+五维健康)

**Reference-only unsupported states 显式入账:** Panel 6/7(见 Ledger #47/#48),无截图要求,语义明确未实现且页面无对应词表(测试断言 absent)。

---

## 6. Functional Conformance Ledger(独立于 Visual Ledger)

Verdict 词表:MATCH / JUSTIFIED DIFFERENCE / FUNCTIONAL DEFECT。

| # | UI surface/state/action | Authoritative source | API/backend evidence | Expected semantics | Observed result | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| F1 | 列表 需处理 一等列(3/1/3/—/—) | GET /api/admin/data-sources/attention-summary | `functional-api-attention-summary.json`:partner-portal 3、wiki 1、store-woo 3、help-center 0、website 0 | 与冻结桶公式一致(ledger−current−retired) | UI 徽章值逐源等于 API 值 | MATCH |
| F2 | 列表 知识数量列(3/6/8/4/0) | 同上 ledger_total | 同上 | 账本总数 | UI=API=DB 分组计数(21 行逐文档核对) | MATCH |
| F3 | 列表 操作者状态(同步失败/需处理/待分类) | /data-sources last_sync_status + attention-summary + /sync-health overall | DB last sync per source:partner failed、store-woo partial、wiki failed、help success | 呈现映射,零前端重判 | 四参考态全部由权威值复现;禁用→已禁用 | MATCH |
| F4 | 列表 搜索/状态/类型过滤、异常优先排序 | (呈现层) | 无真值改动 | 只重排/过滤当前权威集 | 与参考扫描优先意图一致;零后端调用差异 | MATCH |
| F5 | 详情 右侧摘要(8 条知识·3 项需处理;最后同步 2小时前·部分成功) | /documents 聚合 + last_sync_* | `functional-db-verification.txt`:store-woo partial 2026-09-12T15:46 | 人性化主时间+精确次级 | UI 与 API/DB 一致 | MATCH |
| F6 | 详情 banner 原因摘要(2 项缺失+1 项现行版本缺失) | /documents lifecycle_counts(current 5、missing 2、active 6) | `functional-api-docs-bucket.txt` 聚合字段 | 逐类投影,只列非零类 | 文案逐类对应权威计数 | MATCH |
| F7 | 查看需处理 → 服务端 bucket 过滤 | /documents?bucket=attention | total=3(items=deprecated-api/legacy-pricing/orphan-page) | 后端权威桶投影(新只读参数,默认行为不变) | UI 共 3 条=API total=DB 行集 | MATCH |
| F8 | 展开行诊断(deprecated-api) | /documents/detail?doc_source_id=… | `functional-api-truth-deprecated-api.json`:missing_candidate、serving true、v1、chunks_total 2、gen 900001 ready | 只读真相,无编造成分 | UI 展开内容=API=DB(missing_candidate∧has_cv) | MATCH |
| F9 | 索引生成失败证据(#900002 embedder 0 向量) | /generations | `functional-api-sync-runs-store-woo.txt`:900002 failed + failure.error;900001 ready,serving_ordinals=[900001] | failure JSONB 原样 | 07 截图与 API 逐键一致 | MATCH |
| F10 | 同步状态与活动时间线(红失败/琥珀部分/绿完成) | /sync-runs?source_id=store-woo | run 4 failed(00:46,错误摘要)、run 3 partial(23:46)、run 2 success(02T17:46,新增 8) | 异常优先+压缩常规 | 05 截图事件与 API 记录逐一对应 | MATCH |
| F11 | 既有操作:触发同步 | POST /data-sources/{id}/sync(既有) | `functional-action-sync-chain.txt`:202 {status:accepted,request_id:1} → sync_requests pending 行(manual)→ /sync-status help-center=QUEUED | 202=受理≠成功;UI toast+按钮态由 /sync-status 恢复 | 全链验证通过;随后本地删除 pending 请求行(仅本地清理,见 scope audit),状态回落 COMPLETED;非目标源 config/状态零变化 | MATCH |
| F12 | 既有操作:编辑抽屉保存 | PATCH /data-sources/{id}(既有 useUpdateDataSource) | 404 项 vitest 全绿,含 C8B web_crawl/github/filesystem/woocommerce round-trip payload 形态断言 | 完整编辑器能力保持权威 | 表单逻辑逐字迁移,提交 payload 形态不变 | MATCH |
| F13 | 参考独有:知识设置/高风险预览语义 | 无后端权威 | 无该类端点/真值 | 不得伪造 | 前端无入口、无词表(测试断言 absent) | JUSTIFIED DIFFERENCE(=Visual Ledger #47/#48) |

**FUNCTIONAL DEFECT = 0。**

---

## 7. Runtime evidence

- 后端:worktree 内 `uv sync --extra dev`;`ASKAI_API_PORT=8101 EMBEDDER_DEVICE=cpu uv run python -m backend.main` → 「Ask AI 后端就绪」/ Uvicorn 0.0.0.0:8101;数据层 = 本地 docker `ask-ai-local-postgres-1`(5432,ask_ai/ask_ai)+ `ask-ai-local-weaviate-1`(8080);`.env` 为 symlink(未提交)。
- 前端:`cd admin && VITE_API_TARGET=http://localhost:8101 npx vite --port 5181 --strictPort`(candidate 源码热载)。
- 登录:本地 users 表 `admin@camthink.ai`(admin 角色);密码经 `backend.auth.jwt.hash_password` 本地重置(仅本地库;脚本 `scripts/create_admin_user.py` 需交互 tty,改为等价直写 hash);curl 验证 `/api/admin/auth/login` 200。
- 浏览器:playwright-cli(Playwright MCP CLI)真实自动化,`resize 1440 900`,逐状态快照+截图;登录通过真实 UI 表单提交完成。
- 验证步骤:列表 → 详情(normal)→ 详情(needs-attention)→ 展开真相 → 同步活动 → 编辑抽屉 → 本地诊断 → 查看需处理 → 列表可观测性展开;同步动作链见 F11。

---

## 8. Candidate SHA

分支 tip(本报告提交后为准):见 `git rev-parse HEAD` 于 push 输出;报告前的实现 commit SHA 在 push 记录中列出。

---

## 9. Scope audit

1. **零生产触碰:** 全程仅本地 docker(ask-ai-local-postgres-1/ask-ai-local-weaviate-1,localhost);无任何 SSH;未连接 43.132.189.162;未执行 deploy。
2. **零语义变更证明:** 后端仅新增只读 GET(attention-summary)与既有只读 GET 的 additive 参数(bucket/order/source_type,默认值=原行为,pytest 原断言全数保持通过);无任何写路径、retrieval/ranking/citation/lifecycle/generation 语义改动(全量 pytest 2490 通过为证)。前端状态/原因/计数全部消费既有或新只读投影端点;`dataSourceOps.ts` 仅呈现映射(测试逐一断言「不编造/缺席显式」)。
3. **本地 seed 清单(仅 dev 库 ask_ai,已于上方 SQL 全文记录):**
   - data_sources:+3(store-woo/woocommerce、help-center/web_crawl、partner-portal/filesystem,均 enabled)
   - documents:+15(store-woo 8:5 active+serving、2 missing_candidate、1 active 无现行版本;help-center 4 active;partner-portal 3 discovered)
   - document_versions:+11、document_version_chunks:+50、index_generations:+3(900001 ready、900002 failed 含 failure JSONB、900003 ready)
   - sync_log:+6(success/partial/failed 分布)、sync_runs:+9(failed×2、completed×7,含 manual 触发与 fallback 细节)
   - 动作链验证后清理:删除 1 行 sync_requests pending(本地);未删除/修改任何生产形态数据
4. **跨轨零触碰:** 未改 Analytics/techInsight/SystemInfo/system 面任何文件(`git diff --stat` 可证);未 cherry-pick 他轨实现;B2 参考图未用于本轨实现。
5. **symlink 纪律:** models/.env 未提交;`git add` 全部显式列文件;widget/node_modules symlink 仅为本地 tsc/build 环境修复,不在提交内。

---

## 10. 既有测试更新清单(收敛性故意变更,逐条对账)

- `tests/DataSources.test.tsx`:标题 数据源管理→数据源;新增按钮名 新增数据源→添加数据源;历史可靠性/内容列断言改为「状态徽章 title 次级证据 + attention-summary 知识数量列」(G001–G005、悬停、#21 列头);最新同步列改相对时间;查看可观测性改经 ⋯ 菜单;mock 增加 useAttentionSummary(新读面)。
- `tests/dataSources/DataSourceDetail.test.tsx`:身份区 24h→同步周期人性化;三桶总量注记改「账本 6」;清单行分块列/生命周期标签→运营桶词表+相对时间;搜索 aria-label;真相展开词(现行版本→当前有效版本/生成真相);进行中同步经活动时间线断言;mock 补 drawer hooks。
- `tests/FinalPolish.test.tsx`:viewer/admin 写操作按钮名同步收敛(+ 添加数据源),viewer 无 ⋯ 内删除的断言保持。
- 全部更新均为「呈现层收敛、权威真值断言等价或加强」,无一条放松冻结纪律。

---

## 11. 残余风险与移交 Integration

- 主色 token(黑 vs 参考蓝)与共享卡密度语法,建议 Integration 阶段统一裁决(见 Ledger #4)。
- 编辑抽屉类型可编辑(见 Ledger #46)如需禁用,须 Product 明确「移除既有能力」授权。
- `tests/scripts/test_recovery_semantics.py` 存在既有 flaky(纯基线复跑亦失败、单测通过、失败集随运行漂移);与本轨改动无关(本轨未触及 sync_executor/recovery),建议单独立项修复。
