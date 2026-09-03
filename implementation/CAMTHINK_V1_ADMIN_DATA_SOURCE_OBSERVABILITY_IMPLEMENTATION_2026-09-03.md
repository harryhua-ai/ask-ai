# CamThink V1 Admin Data Source Observability — Implementation 报告(Issues #9/#11/#12/#15,W3)

- **日期**: 2026-09-03
- **仓库**: harryhua-ai/ask-ai
- **WORKTREE**: `.worktrees/w3-admin-data-source-observability-20260903`
- **BRANCH**: `worktree-exec/w3-admin-data-source-observability-20260903`(已推 origin)
- **BASELINE**: `1d6f6b5`(= 生产 sha)
- **FINAL_COMMIT**: `69d26d7`(实现 5 提交 564d479→e9f800b + 本次 review 修复 1 提交)
- **PRODUCTION_MUTATIONS**: **NONE**(零部署/零后端/零 schema/零生产数据触碰)

---

## 1. STATUS

**STATUS: PARTIAL → 升级为 CANDIDATE_READY(待 Planner 复核本报告后定稿)**

预设的 PARTIAL 理由(admin build 被既有 widget 问题阻塞)**经实证不成立**:

- build 失败的真实根因 = 本 worktree 从未安装 widget 依赖(admin tsconfig 按架构设计
  `include: ["src", "../widget/src"]`,admin 经 `@widget/*` 引用 widget 组件),
  react/vitest/dompurify 类型全部无法解析 → 15 个错误全部来自 `../widget/src/**`。
- 在 widget/ 执行声明的 `npm install`(其 package.json 本就声明这些依赖)后,
  `tsc -b && vite build` **全绿**(仅 chunk 体积警告,非错误)。
- 「widget 缺少 CamThink.ai-black.png」诊断不实:该资产在 git 中(0e27292)且存在于本 worktree。
- 「widget 既有 implicit any/index 类型错误」不成立:依赖装齐后 admin strict tsc 对
  widget 源零报错(baseline 双构建全绿的记录一致)。

结论:admin 全量测试 227 绿 + build 绿,无遗留阻塞。最终状态以 Planner 对本报告复核为准。

## 2. 审查过程与 findings(本次会话执行的 Task 3 / 全分支只读 review)

前置核验:工作树干净,HEAD=e9f800b,diff 1d6f6b5..HEAD 全部 14 文件均位于 admin/
下(backend/schema 零触碰,边界遵守)。

### 2.1 六个重点检查项核验结论

| # | 检查项 | 结论 |
|---|---|---|
| 1 | freshness 无成功同步 | **符合**。`successfulSyncTime` 三级证据(latestRun.sync_log.status=success → sourceHealth.last_sync_status=success → source.last_sync_status=success)全无 → UNKNOWN(面板显示「证据不足」);有成功但超 `2×sync_interval` → DEGRADED(文案含最近成功时间与阈值);间隔证据无效 → UNKNOWN+解释文案。不伪造 stale 判定 |
| 2 | RECOVERING 无旧健康证据时的 overlay | **符合**。active overlay(SyncStatusPanel,`/sync-status` 驱动)只要 activeStatus 存在就渲染——含折叠行(`!expanded && !activeStatus` 才隐藏),不依赖任何健康证据;五维健康面板的「同步」维度仅在旧 30 天证据存在时叠加 RECOVERING 徽章,无证据时诚实显示「证据不足」(与 f8a537b 修复意图一致;恢复中是活跃事实,不该伪装成历史健康结论) |
| 3 | 主表健康 vs 五维层级 | **符合**。主表健康列 = 既有 30 天窗口徽章 + 历史行(healthMap join);五维健康(SourceHealthPanel:连接/同步/覆盖/新鲜度/一致性)只在展开的「查看可观测性」详情行渲染;主表另以 /sync-status 驱动「同步中...」按钮态(活跃即可见,不进健康列) |
| 4 | ExecutionDevice 类型严格性 | **发现并修复(F2)**。原 `"GPU" \| "CPU" \| "UNKNOWN" \| string` 中字面量被 `\| string` 吸收,是假联合;W2 下发设备原文(cuda/cpu 等),封闭联合反而失真。已改为文档化 `string`(doc 注释已知归一值,展示层 deviceLabel 归一 GPU/CPU/原文) |
| 5 | W2 字段无重新发明/误标 | **符合**。`SyncStatusItem` 与冻结契约 12 字段一一对应;`SyncRun` 18 字段 + `sync_log` 6 字段一一对应,无发明字段;`SyncCounters`/`SyncConsistency` 的索引签名仅为容错 W2 计数器扩展(如 missing/missing_count 双名宽容解析),业务语义一律以 W2 为准;前端不自行计算"健康真相",五维是 W2 事实+既有 30 天窗口的呈现层推导 |
| 6 | fallback/missing/orphan/未知分母文案 | **符合(含一处修复 F1)**。降级=`降级原因：{fallback_reason}` + 技术证据折叠区显示 fallback_detail;缺失与孤儿在历史卡片分列 span、一致性维度分行为;未知分母不显示百分比(`进度待确认`/`已处理 N 项`);SHA 短路文案逐字 `无上游变更 · 已检查 · 跳过灌入`。**F1**:verification_failed 时 evidence 后缀「；校验失败」会被拆分正则吞进「孤儿」行(显示成"孤儿 3；校验失败")——已收紧正则 `([^；]+)`,带后缀时整体呈现,附回归测试 |

### 2.2 修复提交

`69d26d7 fix(admin): review findings`(2 源文件 + 1 测试;RED→GREEN:先写「校验失败后缀不并入孤儿行」失败测试,再修正则)。

### 2.3 审查执行说明

Task 3 前一 reviewer(gpt-5.6-sol)已停止且零改动(git status 干净佐证);本报告 §2 的
review 与 findings 修复由本会话执行代理完成,未假设任何未完成的 review 结论。

## 3. UI_BEHAVIOR(交付的六项管理员可见能力)

1. **是否正在同步**:主表「同步」按钮按 `/sync-status` 活跃态(QUEUED/WAITING/RUNNING/RECOVERING)显示「同步中...」并禁用;5s 轮询仅在有活跃项时开启(空闲零请求,刷新后从 backend 恢复)。
2. **阶段与真实进度**:当前阶段 canonical 中文化(DISCOVER 发现内容 → DONE 完成);`stage_total` 已知 → `current/total · N%`,未知 → `已处理 N 项` 或 `进度待确认`,绝不伪造百分比。
3. **本次同步事实**:counters(docs_total/docs_processed/chunks_written/chunks_deleted)+ sync_log 业务结果(成功/补齐/失败)与 items_new/items_deleted/items_unchanged/chunks_written 分列;技术证据折叠区(request_id/attempt/recovering/fallback_detail/error_detail)。
4. **五维健康**(展开详情):连接/同步/覆盖/新鲜度/一致性五卡,每卡 状态徽章 + 证据行 + as_of;主表保留 30 天窗口历史可靠性徽章(DSH-01/02 主位不变)。
5. **失败/中断/降级原因**:FAILED/INTERRUPTED 状态徽章(destructive)+ 可重试;降级原因行 + 技术证据;一致性 校验失败/缺失/孤儿 分开陈述。
6. **刷新恢复**:active 同步态完全由 `/sync-status` 后端真相驱动(无本地 Set/时间戳猜测);同步历史 `/sync-runs?source_id=&status=&page=&size=` 懒加载(展开才拉)。

## 4. W2_API_CONTRACT(消费面)

- `GET /sync-status` → `SyncStatusResponse{items:[SyncStatusItem]}`:source_id,state,request_id,attempt,recovering,stage,stage_current,stage_total,counters,execution_device,started_at,updated_at —— 类型 1:1。
- `GET /sync-runs` → `SyncRunList{items,total,page,size}`:`SyncRun` id,source_id,triggered_by,request_id,attempt,recovery,status,started_at,finished_at,duration_seconds,stage,counters,consistency,execution_device,fallback_reason,fallback_detail,error_summary + `sync_log{status,items_new,chunks_written,items_deleted,items_unchanged,error_detail}` —— 类型 1:1,零发明。
- 状态词 8 态(QUEUED/WAITING/RUNNING/RECOVERING/COMPLETED/FAILED/INTERRUPTED/IDLE)与 canonical stage 9 态(DISCOVER…DONE)为封闭联合;`execution_device` 为文档化 string(§2.1 #4)。

## 5. TESTS

| 套件 | 结果 |
|---|---|
| admin vitest 全量 | **41 files / 227 passed**(修复后,含新增回归 1 例) |
| W3 focused(dataSources*/dataSourceObservability/useDataSources) | 全绿(含于上) |
| admin build(`tsc -b && vite build`) | **通过**(widget 依赖装齐后;仅 chunk>500kB 警告) |
| `git diff --check` | 通过 |
| 变更范围 | 1d6f6b5..HEAD 全部文件位于 admin/ 下 |

既有根仓 pytest 中断(BGE 模型下载)与本分支无关:本分支 diff 零 backend 文件,
不构成后端回归面(边界即证明)。

## 6. KNOWN_LIMITATIONS

1. `useSyncStatus` 轮询在有活跃项时开启、空闲停止:cron 等外部触发的同步在页面空闲期间不会主动出现,需列表查询刷新或手动刷新(刷新即恢复,符合目标 6;主动推送不在本期范围)。
2. 一致性「校验失败」时五维状态为 UNKNOWN+整体证据行,不拆分缺失/孤儿(呈现取舍,事实计数不丢)。
3. freshness 阈值 = `2×sync_interval` 的呈现层判定,阈值语义权威仍在后端/产品(taxonomy 式可调项)。
4. 五维中「连接」维度对 FAILED 的归因(连接阶段/错误关键词)是启发式证据陈述,非后端权威分类。
5. admin build 对 widget 源的类型检查依赖 widget/node_modules 安装(架构性 include;CI 环境需保证 install 步骤覆盖 widget)。

## 7. 交付物

- 实现+修复:`564d479 → e9f800b`(5 提交)+ `69d26d7`(review findings)@ origin 同名分支
- 本报告:docs 仓唯一新增 commit

---

## 8. REVIEW CORRECTION(Planner)#11 Health Authority——已闭环(6ad0cdd)

Planner 指正:五维健康不得由前端自派生(legacy source-health + sync-runs 本地推导)
构成第二健康权威;W2 `/sync-health` 是 #11 唯一权威读模型。修正提交 `6ad0cdd`(同分支):

1. **消费权威**:`fetchSyncHealth/useSyncHealth`(GET `/sync-health`)+ `SyncHealthItem/
   SyncHealthDimension/SyncHealthResponse` 契约类型;页面 5s 轮询(与活跃同步同节奏),
   `SourceHealthPanel` 改为接收后端条目直呈:五维卡片 + overall 徽章均来自后端
   (state 词表本地化、evidence/as_of 原样)。
2. **删除前端推导**(净 −152 行):connectivity 错误文案 regex 分类、freshness
   2×interval 阈值派生、coverage/consistency 本地分类、legacy 30 天健康导入五维
   (`deriveSourceHealth` 及其辅助函数整体移除);`withEvidenceState` 状态覆盖与
   从 /sync-status 注入 RECOVERING 的 overlay 一并删除——恢复中只能来自后端
   overall/state 表达。
3. **前端只本地化不重判**:`healthStateLabel` 已知词表(W2 维度级小写 10 个 +
   overall 大写 10 个)→ 中文;未知词表**原文透传**(测试锁定 vendor_future_state);
   空 evidence 仅「证据不足」占位提示,状态徽章不改写。
4. **30 天 source-health 降级为既有徽章**:主表健康列/内容数/tooltip 保留原用途,
   不再进五维面板。
5. **保持不变**:/sync-status 轮询、/sync-runs 懒加载历史、真实进度(未知分母不显
   百分比)、SHA 短路文案、设备/降级证据、FAILED/INTERRUPTED 呈现;后端/schema 零触碰。
6. **测试证明**:`SourceHealthPanel` 重写 6 例(五维+overall 按后端原文渲染;UNKNOWN
   不改判;RECOVERING 不合成;未知词表透传;STALE 只本地化不重算;空数据诚实态)+
   DSH 集成例(展开后五维由 /sync-health fixture 驱动,断言旧本地推导文案不存在)+
   hook 契约路径例(`/sync-health`)。

**验证**:admin vitest 41 files / **227 passed**;admin build(`tsc -b && vite build`)
通过;`git diff --check` 通过。FINAL_COMMIT 更新为 `6ad0cdd`。

---

*等待 Planner 独立 FINAL REVIEW;不自动合 main、不自动部署。*
