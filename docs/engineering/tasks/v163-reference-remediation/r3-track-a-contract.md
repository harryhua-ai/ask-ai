# R3 Track A Contract — Data Source Admin UX（冻结）

- Reference（权威）：①APPROVED DESIGN INPUT `/tmp/v163-refs/r3-ds-detail-approved-design.png`（Role A 已批准，已亲读）；②Issue 文本 #61/#65/#66/#67（#66=已确认产品决策）；③`v163-r3-data-source-design-contract.md`（traceability+冻结呈现语义）。
- Issue IDs：**#61**（全部）、**#65**（呈现面：R3-65-DELTA/HONEST/STATES）、**#66**（全部）、**#67**（Phase-1 UX：R3-67-IA/DIM/ADV/UNK）。
- 基线：fresh main `94ddb64`（生产=v1.6.3-r2 @ fd5ca39）。

## 1. Product Semantics（冻结）

1. 操作可发现性：页级 1–2 常用动作直出；行级 2 常用动作直出；行级较多时 2 主动作直出+其余 ⋯；危险操作留 ⋯；重复导航删除。
2. 「重新处理」更名「修复此知识」+冻结 tooltip（「检查并修复该知识的索引一致性，不会重新从数据源获取内容。」）；repair≠sync 边界必须在 UI 可辨。
3. 「本次变化 新增·更新·淘汰」=最近已完成 run 的 `sync_log.items_*` 权威计数；0 显性；无证据 `—`；partial/failed 不伪装；淘汰=后端已确认退出在服集合语义；禁总数差值推断；禁 chunk 冒充知识（单位文案待 B 轨 R3-65-UNIT 签收）。
4. ④详情「同步状态与活动」=同步信息唯一主工作面；列表「同步记录」=轻量互补（3–5 条：时间/结果/新增/淘汰/耗时+「查看完整详情 →」）；同 run 双面严格一致。
5. ⑤「健康与诊断」默认折叠于页面下方；五维管理员词映射（连接状态/同步可靠性/知识覆盖/数据新鲜度/检索一致性）；raw evidence 下沉「高级诊断」；unknown 必须解释「为什么不可评估」；前端禁重判健康/禁组合推导业务影响；**Generation truth 区审计完成前冻结现状诚实呈现**。

## 2. 变更边界（文件所有权）

- 可改：`admin/src/pages/DataSources.tsx`、`admin/src/pages/DataSourceDetail.tsx`、`admin/src/components/dataSources/SyncActivityPanel.tsx`、`admin/src/components/dataSources/SourceHealthPanel.tsx`、新建 owned 组件（建议：`SyncRecordPanel.tsx`（列表轻记录）、`AdvancedDiagnostics.tsx`、管理员健康面板重构物）+ 对应 vitest。
- 禁改：任何 backend 文件；`admin/src/pages/Conversations.tsx`（Track C）；②③区既有交互/主体（设计注记「保持不变」）；现有测试的语义断言（仅允许随新词表/布局更新的最小迁移，逐条记录）。
- 共享壳触达（如需）：仅经 Integration 仲裁，逐条记录。

## 3. Backend/Data 要求

- 零新端点为基线：同步计数/活动经既有 `GET /sync-runs`（sync_log join）读路径消费。
- 若发现 latest-run 计数在读面缺口：**不得自建前端聚合口径**，提请 Track B 只读读面微扩（单一真相源原则）。
- 前置依赖签收：R3-65-UNIT（`items_*` 单位=知识/文档）未签收前，禁渲染「新增知识/淘汰知识」单位文案。

## 4. Frontend 要求

- 布局四处直出（R3-61-LH/LR/DH/DR）+ ⋯ 收敛；桌面端无拥挤/截断/错位（1536×1024 必核）。
- ②异常提醒（需处理→过滤；新鲜度过期→开知识设置抽屉）交互**保持现状**。
- ③主体（搜索/筛选/排序/分页）冻结，仅行级动作变更。
- ⑤折叠态=默认；高级诊断折叠承载全部 raw evidence；coverage unknown 中文解释+英文原句下沉。

## 5. Forbidden shortcuts（r2 冻结清单沿用）

- fake counts（前端差值/推断计数）；frontend-only state 冒充持久真相；keyword-only 分类；前端自算健康/业务影响；纯派生倒计时回潮；UI-only repair；**静默省略**（无真值处必须 `—`/「暂不可评估」诚实态，不得隐藏或编造）；Generation 区无审计授权的解释性文案。

## 6. Acceptance（验收门）

- 验收矩阵 Track A 全行（`v163-r3-acceptance-matrix.md`）证据填充（指针型）。
- G3：vitest 全量+tsc 0+新增断言全绿；既有 admin 测试零回归。
- G4 Visual Gate：①②③④⑤逐区+列表页头/行/展开态 candidate 截图（1536×1024 @1x）+对照表；FINAL PASS=Role A only。
- #61 验收清单全项+#65 验收 1–5/9（呈现部分）+#66 checklist 全项+#67 Phase-1 checklist 全项。

## 7. Runtime states（必须覆盖）

正常行/需处理行文档行三动作态；本次变化 有值/全零/无记录 三态；no-change 与 normal-change 活动态；⑤默认折叠/展开/高级诊断展开/coverage unknown 四态；列表 ⋯ 展开态+行内同步记录展开态；重试删除条件态（如可构造）。

## 8. E2E

- 列表 ⋯ 同步记录 ↔ 详情④ 同 run 计数一致走查（G5）。
- 需处理行→处理→修复→验证卡全链复用既有 E2E-C 语义回归（零 API 变化证明）。

## 9. Deliverables

分支（自冻结基线）+ 逐 commit ownership 台账 + vitest + 截图 manifest + 对照表 + 验收矩阵证据填充 + 执行报告（`docs/engineering/tasks/v163-r3-track-a-execution.md`，`git add -f`）。

## 10. #67 Truth Gate Amendment（2026-09-14）

依据 `docs/engineering/tasks/v163-r3-generation-truth-audit.md`，#67 选择 **B. EXISTING TRUTH SUFFICIENT WITH PRESENTATION CORRECTION**。原“Generation 区审计完成前冻结”门仅对审计前状态有效；现改为以下可实施的呈现契约，仍不授权本分支立即实施。

- `健康与诊断` 保持页面下方默认折叠，不增加导航层级。
- 健康五维显示为：`连接状态`、`同步可靠性`、`知识覆盖`、`数据新鲜度`、`检索一致性`。后端 state/evidence/as_of 原样消费，前端不重判。
- `知识覆盖` 只表达有权威 `accepted/extracted` 分母的候选抽取比率；无分母显示“暂不可评估”并解释原因；不使用文档总数/向量数/差值。
- `检索一致性` 明确说明是“现行 PG chunk 账本与 Weaviate 实际 chunk 投影”；不表述为 generation 完整性、全量覆盖、回答召回或引用有效性。
- Generation 子面仅为 `SECONDARY/TECHNICAL EVIDENCE`。`*legacy*` ordinal 0 显示“迁移初始代；计数不可用于完整性判断”；`doc_count/chunk_count=0/0` 不得作为当前 serving/知识数量。
- source-specific 空 Generation history 显示“没有该源的独立构建记录；当前服务状态请看文档/版本/检索一致性”，不得显示会让管理员理解为“该源没有索引”的短语。
- Generation ID/history 不进入默认管理员决策面；仅在高级诊断/失败证据中保留工程关联价值。
- #65 `items_*` 单位签收仍是前置门；签收前不渲染“新增/更新/淘汰知识”单位文案，不在前端自行换算。

本附录只解冻 Generation 的呈现契约；不改变 #61/#66 的操作范围，不修改后端文件，不改变 lifecycle/sync/repair API 语义。
