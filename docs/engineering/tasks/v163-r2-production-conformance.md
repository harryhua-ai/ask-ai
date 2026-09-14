# v1.6.3-r2 生产 Conformance 报告

- 发布身份：Product iteration = **v1.6.3** / Release = **v1.6.3-r2**（取代更早的 v1.6.3 生产 UI 实现）
- 冻结 commit：`fd5ca39d7ee1097abe10de513ce7e595f159270a`（tag `v1.6.3-r2`）
- 执行记录（R1 全量证据）：`docs/engineering/tasks/v163-wave2-integration-execution.md` § R1
- 本文件职责：发布/迁移/身份 = R1 已填充；**生产 UI 验收 ledger = R2 已填充（§4–§10，2026-09-14 生产真实数据验收）**

## 1. Release（已填充）

| 项 | 值 | 证据 |
|---|---|---|
| Clean-tree 门 | pytest 2630/0/7（=基线逐字）· PA 114/114 · planner 31/31 · vitest 540/540 · tsc 0 · build ✓ · ruff 全仓指纹=基线 | R1 §R1.1 |
| 部署契约扩展 | `-rN` 重转后缀最小扩展（授权），commit `801676a`；fail-closed 语义零弱化 | R1 §R1.2 |
| Tag / Release | `v1.6.3-r2` → fd5ca39；Release URL https://github.com/harryhua-ai/ask-ai/releases/tag/v1.6.3-r2 | R1 §R1.3 |
| CI / lineage | run 34803619956 test PASS + build PASS；镜像内 RELEASE.json `version=1.6.3-r2, git_sha=fd5ca39…`；镜像 `ghcr.io/harryhua-ai/ask-ai:v1.6.3-r2` | R1 §R1.4 |

## 2. Production Migration（已填充）

- 部署 run **34804523307** SUCCESS（3m37s）；GitHub Deployment id=6430201280 state=success
- 迁移桥按序 3 条（冻结镜像内执行,每条前镜像身份断言 ✅；PLAN SOURCE=manifest@fd5ca39d7ee1）：
  1. `migrate_add_site_launcher_presentation.py` → 完成（幂等,零回填）
  2. `migrate_p1_lifecycle_foundation.py` → 完成（PG documents 加列 + P1 三表；Weaviate 147999 legacy 对象验证全过）
  3. `migrate_add_track_c_product.py` → 完成（content_type 回填 **12000** 行 + data_sources 三列 + 三新表）
- Schema 在位（SSH 只读核验）：`documents.content_type`、`data_sources.next_run_at/knowledge_role/freshness_hours`、`document_repair_tasks/document_recovery_events/knowledge_settings_previews`、`gap_observations/gap_observation_events`、`documents` 生命周期五列、`site_experiences.launcher_presentation` —— 全部 ✓；三新表 0 行（加性）
- 回填诚实性：12000/12000 全部非空（document:11818 / page:141 / product:41），权威 `derive_content_type` 派生,零 NULL、零猜测值

## 3. Production Identity（已填充）

- `/health`：`{"status":"ok","version":"1.6.3-r2","git_sha":"fd5ca39d7ee1097abe10de513ce7e595f159270a","app_mode":"production"}`（workflow 双断言 + SSH 独立复核一致）
- 容器：backend/sync-cron/sync-executor = `ghcr.io/harryhua-ai/ask-ai:v1.6.3-r2`；backend restarts=0 / healthy；PG、Weaviate healthy
- backend 启动以来 ERROR 计数 = 0
- 生产 admin 凭据位置：`backend/main.py:253`（种子回退字面量,值不复述）+ 主机 `~/ask-ai/.env ADMIN_PASSWORD`（仓内仅占位符）+ `deploy/prod/RC-2026-09-01-ACTIVATION.md:43` 处置勾选项

## 4. 生产 UI 验收 Ledger（Role A 生产验收执行 · 2026-09-14）

> 执行方式：SSH 只读核验 + 生产 admin UI（backend :18000 托管，经 SSH 隧道访问；主机 80 端口 nginx 不路由 /admin）真实数据全量走查 + 只读/安全负向 API 探针。凭据不落任何报告/提交。截图与探针日志：`ask-ai-acceptance/v163-r2-production-20260914/`（1536×1024 @1x）。

| # | 验收项（参考需求映射） | 入口/路径 | 结果 | 证据 |
|---|---|---|---|---|
| 1 | 数据源修复工作流 | /data-sources/:id（需处理行「处理」/展开行「重新处理」） | PRODUCTION STATE NOT PRESENT | 生产 15 源 attention=0、document_repair_tasks=0 行,修复按钮无触发数据态;能力=R1 组合树 E2E-C 全链;本验收零修复执行 |
| 2 | 知识设置 CURRENT-HISTORICAL | 详情页 ⋯→知识设置 | PASS（呈现+真值） | 抽屉时态角色*/新鲜度*逐字呈现(09)；GET 全 15 源 role=current/24h;非法 25→422;无 token 角色变更→409 |
| 3 | 高风险预览确认流 | 知识设置→保存(角色变化) | PASS（Modal 可达,取消不确认） | Modal CURRENT→HISTORICAL 红 diff+后端权威计数 41/41/0(10)；取消→DB role 仍 current;预览快照行=合同授权(preview 表 2 行,均未确认) |
| 4 | 权威 content_type / serving score / 恢复计数 / 下次同步 | /data-sources/woocommerce-mall | PASS | 类型列=后端真值 product(41/41)(04/05);详情 truth chunk_serving 3/3 consistent+recovery 0/0(探针 p5);「下次同步: 23小时后」=scheduler 权威 next_run_at(06) |
| 5 | 扩展原因词表 | /analytics 回答缺口 全部原因 | PASS（词表全量） | 筛选器 11 项全集(知识缺失/服务知识不完整/拒答/低相关/内容过期/检索异常/生成异常/引用异常/内容冲突/内容缺失/未分类);生产 6 gap 全部真实=未分类(不造假);过滤真实生效(25 诚实空态) |
| 6 | OBSERVING 状态机 | 状态筛选/侧板/History | PRODUCTION STATE NOT PRESENT（词表 PASS） | 「观察中」筛选选项在位(13);生产 19 clusters 全 open、gap_observations=0 行,无观察中数据态;强转 RESOLVED 409 实证(§6-C);History Tab 诚实空(19) |
| 7 | CSV 导出 | 侧板 导出相关对话 | PASS（合同授权探针一次） | 0 会话 gap→header-only CSV(6 列+BOM+CRLF);审计行 +1 id=0b45a740-ca95-40f9-accd-4770928d700c row_count=0;PII 排除清单冻结面;UI 卡片呈现不二次点击(15) |
| 8 | 受影响用户聚合 | 侧板 meta 行 + /users API | PASS | 「涉及 0 个用户」诚实真值(15);API 仅聚合计数,响应零 session 原值(探针 p2);空集 users_available=true |
| 9 | gap→源归因 | 侧板 相关数据源 + /sources API | PASS（诚实不可用态） | 「无归因证据:归属会话无引用来源记录,系统不做猜测」(15);API 响应携带 evidence_rule=conversation_citation_identity_match;零前端猜 |
| 10 | 确定性主题 | 队列 主题/副行 + /topic API | PASS | 同 gap 两次请求逐字节同值(探针 p2);topic=null→诚实回退代表问句;派生主题在其它 gap 生效(13) |
| 11 | 全参考对齐 Admin UX（152 行 reconcile 抽样生产复核） | 两参考全部状态清单 | PASS | MATCH 24 状态 / UADC 4 项逐条复现 / PRODUCTION STATE NOT PRESENT 8 状态逐条如实标记 / DEFECT 0（§7 设计 ledger） |

### 功能 ledger A–F

| 项 | 结果 | 证据（生产真数据） |
|---|---|---|
| A 分析窗 | **PASS** | UI 窗选择=今日/过去 7 天/过去 30 天/全部时间/明确起止(data-filter-window;13/14/26);后端真窗:技术性能 trace_total today=11 / 7d=1195 / 30d=1415、p95 与异常率逐窗不同(探针 p5)=两档以上真窗差异;缺口队列各窗 total=6 为冻结语义正确呈现(last_seen NULL 不被窗口排除,代码契约逐字);非法 window=week / range:2026-13-01→**422** |
| B 源编辑 | **PASS（零保存）** | 编辑抽屉:label「名称 *」、类型 disabled=true、自动同步 toggle=ON(反映真实 enabled=true)+逐字说明「开启后，系统将按设定周期自动同步。」(07);两次打开均「取消」,零 PUT;API 复核配置/角色/新鲜度逐字不变 |
| C 数据源运营 | **PASS（零 policy mutation）** | content_type 列真实回填值(product);服务=正常;serving 分数 truth 3/3 consistent;恢复计数 0/0(持久投影);下次同步=调度真值;知识设置 Drawer 呈现(09);预览 Modal 可达+计数只读安全(确认键未点);修复入口数据态不存在(0 需处理)→未执行(安全) |
| D 原因词表 | **PASS** | 生产词表全集可见(§4#5);生产存在真实分类结果(全部未分类=真实分类器输出,与 /analytics/coverage-gaps 同源);无真实 8 新类案例→不造假如实记录;筛选链路真实(服务端 cause 参数) |
| E 观察/导出 | **PASS** | 状态词表含观察中(筛选选项在位);概览含 导出相关对话/内容补充完成后/开始观察区(INT-E-01 逐字,15);History 仅历史(流转历史诚实空,19);导出探针=合同授权一次(§4#7,审计行 0b45a740);生产 observing 数据态不存在(如实标记) |
| F 证据聚合 | **PASS（含诚实不可用）** | 用户数(涉及 0 个用户,users_available=true)/源归因(无归因证据+evidence_rule)/主题(两次请求同值+回退诚实)三面全在生产真实 gap 上验证;生产 6 gap 归属会话=0→聚合机制呈真值 0 而非编造 |

## 5. 关键语义检查（§9 不变量 · 生产探针）

| 项 | 结果 | 证据 |
|---|---|---|
| A HISTORICAL 检索排除 | **PRODUCTION-STATE-NOT-PRESENT（机制在位）** | 生产 15 源 knowledge_role 全 NULL(=current),无 HISTORICAL 数据态;机制验证:角色变更 409 门禁实时(无 token→409)、预览角色机实时(过期时间签发)、R1 组合树 C-settings 检索资格双向实证;生产态不存在如实标记 |
| B 修复在服代可见性 | **PRODUCTION-STATE-NOT-PRESENT（组合树证据）** | 生产不执行修复(document_repair_tasks=0);R1 E2E-C:succeeded+consistency passed 4/4+在服代权威写(uuid5 命名空间,legacy 0 命中) |
| C 直接强转 RESOLVED 不可能 | **PASS** | PATCH /api/admin/analytics/gaps/{真实gap}/resolve status=resolved → **409** `resolve_not_allowed from_status=open`;事后核验状态仍 open(零变更) |
| D 导出无 PII | **PASS** | CSV 仅列头(0 行);6 列=conversation_id(伪匿名 UUID)/created_at/question/answer/is_answered/sources(最小投影);冻结 PII 排除清单(session_id/country/channel/intent_tag/custom_tags/customization_id/site_id/response_time_ms/feedback/gap_status/override_answer) |
| E 用户聚合零身份泄漏 | **PASS** | /answer-gaps/{id}/users 响应仅聚合计数(conversations_in_window/with/without_identity/distinct_sessions/users/available/reason),响应结构无 session 原值字段 |
| F 归因非前端猜测 | **PASS** | /answer-gaps/{id}/sources 响应 items 携带 evidence_rule=conversation_citation_identity_match;无证据→unmatched_citations 透明列出;UI 逐字「系统不做猜测」 |
| G 非法 freshness 422 | **PASS** | PUT freshness_hours=25 → **422**(冻结词表 [6,12,24,72,168] 逐字报错);事后 GET role=current/24h 零状态变化 |
| H 预览 token drift 409 | **PRODUCTION-STATE-NOT-PRESENT（相邻门禁实证）** | 生产不制造 drift;相邻实证:角色变更无 token→**409**;预览签发 token+expires_at(一致性锚在位);R1 组合树 drift 409+干净 200 证据引用 |

## 6. 参考设计 ledger（生产状态清单 · 逐状态）

分类词表唯三：**MATCH / USER-APPROVED DESIGN CHANGE(UADC) / PRODUCTION STATE NOT PRESENT**（能力已实现但生产无该数据态——非缺陷、亦不称已视觉验证）。UADC 唯四、精确范围：V-2 FAB 抑制 / V-1 行高 41px / V-3 同步结构 / Help Center 推迟。

| # | 状态（参考出处） | 分类 | 证据截图/探针 |
|---|---|---|---|
| 1 | DS 列表 全列集+正常徽章+⋯+共 N 个 | MATCH | 02 |
| 2 | DS 列表 运营类型词(Wiki/文件系统/网站/商城) | MATCH | 02 |
| 3 | DS 列表 千分位计数(5,534) | MATCH | 02 |
| 4 | DS 列表 需处理/待分类/同步失败/已禁用徽章行 | PRODUCTION STATE NOT PRESENT | 生产全正常;筛选器四选项在位(02);R1 组合树 13/14 |
| 5 | DS 列表 需处理列 红色非零值 | PRODUCTION STATE NOT PRESENT | 列在位(值为 —);同上组合树 |
| 6 | DS 列表 行高 41px 密表 | **UADC-2(V-1)** | 02(41px 复现,既有 User 决定) |
| 7 | DS 详情 三级面包屑+品牌 W 方块+身份元信息 | MATCH | 04(U-6 内建映射,Woocommerce→紫 W) |
| 8 | DS 详情 需处理横幅+查看需处理 | PRODUCTION STATE NOT PRESENT | 0 attention;R1 组合树 |
| 9 | DS 详情 知识内容表 类型列=商品 | MATCH | 04(41/41 后端真值) |
| 10 | DS 详情 类型过滤(商品) | MATCH | 05(选项 商品(41)/类型不可用(存量),过滤生效) |
| 11 | DS 同步状态与活动(页内 section) | **UADC-3(V-3)** | 06(页内区块结构复现) |
| 12 | DS 下次同步 调度真值倒计时 | MATCH | 06(下次同步: 23小时后=scheduler next_run_at) |
| 13 | DS 可靠性 一位小数%(83.6%) | MATCH | 06(API=0.836 同源) |
| 14 | DS 编辑抽屉 名称*/类型 disabled/自动同步 toggle+逐字说明 | MATCH | 07(三要素同屏;disabled=true 实测) |
| 15 | DS 知识设置抽屉(CURRENT/新鲜度五值+逐字说明) | MATCH | 09(词表 6/12/24/72/168 小时逐字) |
| 16 | DS 高风险预览 Modal(CURRENT→HISTORICAL 红+三行计数+安全承诺) | MATCH | 10(41/41/0=预览端点逐数) |
| 17 | TI 顶栏全局分析窗(U-2) | MATCH | 11/26(过去 7 天 2026-09-07→2026-09-14;popover 快选+明确起止+应用) |
| 18 | TI 队列 主题+灰色副行样例问句 | MATCH | 13/15(派生主题生效;null→代表问句诚实回退) |
| 19 | TI 队列 原因 chips 全词表 | MATCH | 13+探针(11 选项逐字) |
| 20 | TI 队列 需要处理 徽章 | MATCH | 13 |
| 21 | TI 队列 观察中 徽章行 | PRODUCTION STATE NOT PRESENT | 筛选选项在位(13);生产 0 observing;R1 组合树 23 |
| 22 | TI 队列 已解决 徽章行 | PRODUCTION STATE NOT PRESENT | 筛选选项在位;生产 0 resolved(全 open 真值) |
| 23 | TI 侧板 meta 三行+最近发生 | MATCH | 15(涉及 0 个用户=诚实真值;证据不可用 逐字) |
| 24 | TI 侧板 诊断结论 红盒+chip | MATCH | 15(未分类+证据不可用诚实) |
| 25 | TI 侧板 相关数据源归因 | MATCH | 15(无归因证据逐字)+API evidence_rule |
| 26 | TI 侧板 导出卡+隐私说明 | MATCH | 15(逐字;未二次点击) |
| 27 | TI 侧板 内容补充完成后+开始观察(INT-E-01) | MATCH | 15(逐字落位) |
| 28 | TI 侧板 历史记录 流转史 | MATCH(Tab)/生产态缺席(条目) | 19(诚实空:「系统不做推断」) |
| 29 | TI 技术性能窗指标(KPI+降级信号) | MATCH | 11(1195 trace/35%/P95 15626ms 与 API 同源) |
| 30 | SH FAB KB-OPS 三面抑制 | **UADC-1(V-2)** | 02/04/13/24(三面 0 FAB)+20(conversations 面 FAB 在=精确范围) |
| 31 | SH Help Center 入口缺席(顶栏 ?+侧栏底部) | **UADC-4** | 02/13(两处缺席复现,既有 User 决定) |
| 32 | SH 系统 分组(用户管理/系统信息) | MATCH | 02/23 |
| 33 | SH 收起菜单/展开 | MATCH | 21/22 |
| 34 | SH LIGHT 侧栏(U-1 权威) | MATCH | 全部截图 |
| 35 | SH 主蓝 token/面包屑 ›/身份区 | MATCH | 02/04/13 |

**合计:MATCH 26 / USER-APPROVED DESIGN CHANGE 4 项逐条复现(UADC-1/2/3/4) / PRODUCTION STATE NOT PRESENT 5 项逐条如实标记(#4/#5/#21/#22+#28 条目态)/ DEFECT 0。**（R1 组合树=`docs/engineering/tasks/v163-wave2-integration-execution.md` §P2,P2.3 截图 manifest 01–35）

### 截图 manifest（`ask-ai-acceptance/v163-r2-production-20260914/screenshots/`,1536×1024 @1x,24 张）

01-login / 02-ds-list / 03-ds-list-type-filter-mall / 04-ds-detail-woo-top / 05-ds-detail-doc-type-product / 06-sync-status-activity / 07-edit-drawer-woo(凭据显示态已掩码,零保存) / 09-knowledge-settings-drawer / 10-risk-preview-modal-historical(已取消) / 11-ti-tech-performance-7d / 13-ti-answer-gaps-default / 14-ti-window-today / 15-gap-panel-overview / 16-gap-panel-typical / 17-gap-panel-conversations / 18-gap-panel-diagnostics / 19-gap-panel-history / 20-fab-conversations / 21-sidebar-collapsed / 22-sidebar-expanded / 23-users-system-group / 24-fab-absent-analytics / 25-ti-cause-filter-content-missing / 26-topbar-range-open

## 7. 健康与回归审计（§10）

| 面 | 结果 | 证据 |
|---|---|---|
| /health 身份 | PASS | `{"status":"ok","version":"1.6.3-r2","git_sha":"fd5ca39…","app_mode":"production"}`(SSH 独立复核) |
| admin 登录 | PASS | 登录 200(UI+API 双路) |
| DS 路由 | PASS | data-sources/attention-summary/documents/documents-detail/schedule/knowledge-settings 全 200 |
| TI 路由 | PASS | answer-gaps(窗/状态/原因/分页)/performance/users/sources/topic/observation/export-audits 全 200 |
| Conversations | PASS | /api/admin/conversations total=1415 真实可读(20) |
| Widget 后端端点 | PASS | POST /api/ask 空体→422 路由存活(零 mutation,未发送真实提问) |
| 容器 | PASS | backend/sync-cron/sync-executor=v1.6.3-r2 镜像一致;RestartCount=0/0/0;healthy |
| 生产 ERROR 日志 | PASS | backend/sync-cron/sync-executor ERROR+CRITICAL 计数=0 |
| PG / Weaviate | PASS | pg_isready accepting;weaviate ready OK;documents=12000(ct NULL=0:document 11818/page 141/product 41) |

**RELEASE REGRESSION = 0。**

### 正交观察（只记录不修）

1. **[安全·运维] 生产 admin 口令=代码种子回退值**：约定位置 `~/ask-ai/.env` 无 `ADMIN_PASSWORD`（各 .env/容器环境均无该键);种子回退口令可登录生产 admin(RC-2026-09-01-ACTIVATION §阶段3 处置项未执行)。建议立即按处置单改密/建独立管理员。非本发布回归(既有运维卫生),凭据值不落任何报告。
2. **[性能] 真实流量服务降级信号**：技术性能页 诊断异常率 35%(423/1195 trace)、P95 15626ms(>5000ms 阈值)、真实失败 0%(诚实分离呈现);30d failure_kinds=empty_generation 3/provider_error 2。属运行期观察,非缺陷。
3. **[可靠性] 源级 30d 健康信号**：woocommerce 83.6%(89 failed/555)、ne301 79.45%、neomind-dashboard 85.03% 等 degraded;最近同步全部 success。历史可靠性信号,UI 权威呈现。
4. **[质量] 稀疏语料主题派生退化**：1 个 gap 确定性主题派生为「to」(停用词级);派生确定性/稳定性契约不受影响(两次拉取同值),主题质量属数据量问题,诚实呈现。
5. **[部署] 公网 80 nginx 不路由 /admin**(404),admin UI 仅 backend :18000 可达(本验收经 SSH 隧道);与部署拓扑预期一致,如实记录。

## 8. 生产零 mutation 核对表

| 动作 | 结果 |
|---|---|
| 数据(policy/lifecycle/修复/观察/同步/删除/创建) mutation | **0(未执行——安全)** |
| 导出探针(合同唯一授权例外) | 1 次,审计行 id=`0b45a740-ca95-40f9-accd-4770928d700c`(gap 0 会话,header-only,row_count=0) |
| 知识设置预览快照(合同授权只读预览,非 policy 写) | 2 次(API 探针+UI Modal 打开),均**未确认**,pending 过期;previews 表 2 行,role/freshness 全库无 delta |
| 终态核验 | documents=12000/conversations=1415/clusters=19(全 open)/gap_observations=0/repair_tasks=0/15 源 role-freshness 零 delta/ERROR=0 —— 与验收前逐字一致 |

## 9. 残留风险

1. 观察/修复/三类异常徽章与 resolved 数据态的生产化验证依赖真实运营积累(能力已由 R1 组合树覆盖);建议运营产生首批真实 observing/resolved/attention 数据后补一次增量走查。
2. 生产 8 新类原因分类尚无真实命中(全未分类)——分类器在真实分布上的表现待数据积累复核。
3. 正交观察 #1(admin 口令处置)为最高优先级运维待办。
4. 验收经 SSH 隧道访问 :18000,公网 admin 暴露面与路由策略未在本次范围内变更。

## 10. 结论

**PRODUCTION CONFORMANCE PASS。**

- §9 不变量 FAIL 数=0(C/D/E/F/G 实证 PASS;A/B/H=PRODUCTION-STATE-NOT-PRESENT 且机制在位/组合树证据引用,如实标记不计 FAIL)
- 功能 ledger A–F 全 PASS;设计 ledger MATCH 26 / UADC 4 / PRODUCTION STATE NOT PRESENT 5 / DEFECT 0
- 健康全绿,restarts=0,ERROR=0,RELEASE REGRESSION=0
- 生产零 mutation(授权导出 1 行审计+2 行未确认预览快照除外,均逐条登记)


## 5. 边界声明

- 本发布**不宣称 iteration v1.6.3 COMPLETE**
- R1 期间零 force push / 零历史改写 / 零 issue 关闭 / 六候选与已 tag 历史未动 / 生产仅授权部署 + 只读核验（数据零 mutation）
- R2 生产验收期间：零代码修改（本报告除外）/ 零 merge / 零 deploy / 零 issue 关闭 / 零 force push；生产 mutation 仅合同授权导出探针 1 行审计 + 2 行未确认预览快照（§8 逐条登记）;凭据零落报告/提交
