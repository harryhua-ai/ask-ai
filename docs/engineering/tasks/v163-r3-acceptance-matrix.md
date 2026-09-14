# v1.6.3-r3 Acceptance Matrix（合同态——执行后逐格填充证据，禁止自然语言「已实现」）

- 规则：每行 = Issue → Requirement ID → Design element → Interaction → API → Backend truth → DB/runtime truth → Test → Runtime evidence → Visual evidence。证据格执行前一律 `PENDING`（执行 agent 填充**指针型证据**：文件:行 / 测试名 / 截图 manifest 编号 / 探针输出 id；禁止「已实现/完成/OK」等叙述性表述）。Visual evidence FINAL PASS = Role A independent review only。
- Visual Gate：1536×1024 @1x；逐状态 reference crop ↔ candidate 对照；manifest 沿 r2 惯例（`ask-ai-acceptance/v163-r3-*/screenshots/`）。

## Track A — Data Source Admin UX（#61 / #65 呈现 / #66 / #67-UX）

| Issue | Req ID | Design element | Interaction | API | Backend truth | DB/runtime truth | Test | Runtime evidence | Visual evidence |
|---|---|---|---|---|---|---|---|---|---|
| #61 | R3-61-LH | DS-R3-L-01 | 页头 `+ 添加数据源`+`同步全部` 直出；页头 ⋯ 移除 | POST /data-sources/:id/sync（全部=既有逐源链） | 既有同步受理语义 | sync_runs(triggered_by=manual) | vitest：页头按钮集断言（无 ⋯ trigger） | PENDING | PENDING（DS 列表页头 crop↔candidate） |
| #61 | R3-61-LR | DS-R3-L-02 | 行 `详情`/`同步` 直出；⋯=编辑/同步记录/删除/重试删除(条件) | 既有各动作端点零变化 | 既有 | 既有 | vitest：行动作直出集+overflow 集断言；重试删除条件态 | PENDING | PENDING（列表行动作态） |
| #61 | R3-61-DH | DS-R3-1-02 | 页头 `编辑`/`知识设置` 直出；⋯ 移除；「返回列表」菜单项移除（面包屑保留） | PUT /data-sources/:id；knowledge-settings GET/PUT+preview | U-5 类型 disabled / U-12 / U-13 链零变化 | data_sources | vitest：详情页头按钮集断言；既有编辑/知识设置/预览测试回归 | PENDING | PENDING（DS-R3 ①区 crop↔candidate） |
| #61 | R3-61-DR | DS-R3-3-02/03/04 | 正常行=查看真相+修复此知识 直出（无 ⋯）；需处理行=处理+查看真相 直出、修复此知识 入 ⋯；「重新处理」→「修复此知识」+冻结 tooltip | 查看真相=既有；POST repair 命令零语义变化 | U-8 修复链（RBAC/幂等/审计/进度/验证卡）不触发上游抓取 | document_repair_tasks/document_versions/向量一致性 | vitest：行级动作三态断言+tooltip 文案逐字；既有修复链 pytest 回归 | PENDING | PENDING（③区正常行/需处理行两态） |
| #65 | R3-65-DELTA | DS-R3-4-03 | 「本次变化」与「最近结果」同级：+新增/更新/淘汰；0 显性；无证据显 `—` | GET /sync-runs 最新已完成 run（sync_log join） | items_*=持久化权威计数；禁前端差值推断 | sync_log(items_new/items_updated/items_deleted/items_unchanged) | vitest：三值渲染+0 显性+无证据 `—`；failed/partial 不显中间量 | PENDING | PENDING（④区 有变化/全零/无记录 三态） |
| #65 | R3-65-HONEST | DS-R3-4-03 | 0 显示 `0` 不隐藏；无已完成同步显 `—`/「暂无同步记录」 | 同上 | 诚实态语义 | 同上 | vitest：空态/零态断言 | PENDING | PENDING（零变化态） |
| #65 | R3-65-STATES | DS-R3-4-03/04 | 五代表状态（failed/partial/no-change/normal-change/retirement）各自呈现 | 同上 | run 状态机映射 | sync_runs+sync_log | pytest（B 轨 fixture）+vitest：五状态各自计数/文案 | PENDING | PENDING（至少 no-change 与 normal-change 两态截图） |
| #66 | R3-66-RENAME | DS-R3-L-02 | 「查看可观测性/收起可观测性」→「同步记录」 | 零新端点 | 既有 | 既有 | vitest：菜单项文案断言 | PENDING | PENDING（列表 ⋯ 展开态） |
| #66 | R3-66-LIGHT | DS-R3-L-03 | 行下展开 3–5 条：时间/结果/新增/淘汰/耗时+「查看完整详情 →」 | 同一 sync-runs 读路径 | 单一真相源（与④同口径） | sync_log.items_* | vitest：条数上限+列集+详情深链断言 | PENDING | PENDING（行内展开态） |
| #66 | R3-66-NOHEALTH | DS-R3-L-03 | 行内展开不再渲染 SourceHealthPanel/深度诊断 | — | — | — | vitest：展开区组件树断言（无 health panel 挂载） | PENDING | PENDING（同上） |
| #66 | R3-66-CONSIST | DS-R3-4-06/DS-R3-L-03 | 同一 run 双面四元组（新增/淘汰/结果/耗时）一致 | 同一读路径 | 单一口径冻结 | sync_log | vitest：同 run 双面值相等断言 | PENDING | PENDING（列表展开+详情④同屏对照） |
| #67 | R3-67-IA | DS-R3-5-01 | ⑤「健康与诊断」默认折叠于页面下方；替代「本地诊断（健康与生成真相）」首要表达；零新导航层级 | 既有 | 既有 | 既有 | vitest：默认折叠态断言 | PENDING | PENDING（⑤默认折叠+展开两态） |
| #67 | R3-67-DIM | DS-R3-5-02 | 五维管理员词映射：连接状态/同步可靠性/知识覆盖/数据新鲜度/检索一致性 | 零 API 变化；后端 status authority 不动 | 前端禁重判纪律保持 | sync-health 五维 | vitest：五维映射逐字断言 | PENDING | PENDING（数据源健康子面） |
| #67 | R3-67-ADV | DS-R3-5-03 | raw evidence/threshold/run id/expected/actual/missing/extra_orphan/generation ordinal 下沉「高级诊断」折叠 | 零 API 变化 | 零删除证据 | 同上 | vitest：高级诊断折叠内容断言 | PENDING | PENDING（高级诊断展开态） |
| #67 | R3-67-UNK | DS-R3-5-03 | coverage unknown→「暂不可评估」+中文解释；原始英文 evidence 保留于高级诊断 | 零 API 变化 | 禁前端推断业务影响 | 同上 | vitest：unknown 解释断言 | PENDING | PENDING（unknown 态） |

## Track B — Data Source Runtime Truth（#62 / #67 审计 / #65 单位）

| Issue | Req ID | Design element | Interaction | API | Backend truth | DB/runtime truth | Test | Runtime evidence | Visual evidence |
|---|---|---|---|---|---|---|---|---|---|
| #62 | R3-62-DUE | DS-R3-4-02 | —（执行语义） | — | cron tick 只执行 due 源：`enabled AND sync-eligible AND no inflight AND next_run_at<=now`（单一权威判定） | sync_runs 仅含到期 run | pytest 时间推进：1h/6h/24h 三源同一 tick 序列只在到期运行（#62 验收 10） | PENDING | — |
| #62 | R3-62-NRT | DS-R3-4-02 | — | schedule truth payload | `next_run_at` = 真实下次自动执行（非 UI 预测） | data_sources.next_run_at | pytest：run 完成后 next_run_at 重算=last_finished+interval | PENDING | — |
| #62 | R3-62-MAN | DS-R3-4-05 | 手动单源同步/同步全部/repair/recovery/CLI 即时执行 | POST /:id/sync 等 | 显式触发不受 due gate 限制 | sync_runs(triggered_by=manual) | pytest：due 未到时手动触发仍执行 | PENDING | — |
| #62 | R3-62-TBY | — | — | sync-runs 读面 | triggered_by 区分 cron/manual（生产已在位：cron 实证） | sync_runs.triggered_by | pytest：两类触发源历史可区分 | PENDING | — |
| #62 | R3-62-TST | — | — | — | disabled/deleting/inflight 约束保持；「同步全部」显式人工语义不被静默跳过 | 既有 | pytest：约束矩阵回归 | PENDING | — |
| #67 | R3-67-AUDIT | DS-R3-5-04 | — | generations 读面 | 审计 10 问逐项回答（#0 根因/API 空根因/legacy 范围/新同步计数/迁移需求） | index_generations/document_versions/documents/Weaviate（只读核验） | 审计报告（逐问证据指针）+新同步确定性验证运行（隔离数据态） | PENDING（审计报告路径） | — |
| #67 | R3-67-GENFIX | DS-R3-5-04 | 审计后：legacy/untracked 显式建模 或 migration/backfill（由审计裁决） | generations 读面（如需） | 后端显式建模，禁前端猜测 | index_generations（如迁移） | pytest：建模后读面契约；迁移幂等 | PENDING | PENDING（审计完成后 ⑤ Generation 面态） |
| #65 | R3-65-UNIT | DS-R3-4-03 | — | — | `items_*` 单位契约签收（知识/文档 vs chunk；禁错标「新增知识」） | sync_log | pytest：单位断言（fixture 源 N 文档→items_new=N） | PENDING（签收记录） | — |

## Track C — Conversation Review（#63）

| Issue | Req ID | Design element | Interaction | API | Backend truth | DB/runtime truth | Test | Runtime evidence | Visual evidence |
|---|---|---|---|---|---|---|---|---|---|
| #63 | R3-63-LIST | —（对话审查页） | 列表行次级弱化短 ID（如 `ID 3f19c8a2…`），不压缩 question 主视觉 | GET /api/admin/conversations（既有） | `Conversation.id` 唯一真相（禁第二套展示 ID） | conversations.id | vitest：行内短 ID+title 完整值断言；行 key/selectedId 一致 | PENDING | PENDING（列表态） |
| #63 | R3-63-DET | — | 详情「对话详情」元信息区完整 UUID（禁只显示缩写） | GET /api/admin/conversations/{id}（既有） | 同上 | 同上 | vitest：detail.id 完整渲染断言 | PENDING | PENDING（详情态） |
| #63 | R3-63-COPY | — | 可选择复制/复制按钮=完整原始 UUID | — | 同上 | 同上 | vitest：复制内容断言 | PENDING | — |
| #63 | R3-63-REG | — | 切换对话 ID 严格随 selectedId；viewer 权限可见 ID | 既有 | 权限模型零变化 | 既有 | vitest：切换一致性+viewer 角色断言 | PENDING | — |

## Track D — Citation Integrity（#64）

| Issue | Req ID | Design element | Interaction | API | Backend truth | DB/runtime truth | Test | Runtime evidence | Visual evidence |
|---|---|---|---|---|---|---|---|---|---|
| #64 | R3-64-FM | — | — | citation 构建链（rag.py 调用点不变） | canonical route authority：frontmatter `slug` 显式提供时为优先真值（含 id/index/category route/i18n 语义） | ingestion 真相（wiki 源连接器读取 frontmatter；执行首日前置调查确认连接器归属） | pytest fixture：explicit slug / numbered filename / index route / i18n / ordinary GitHub 五类 | PENDING | — |
| #64 | R3-64-FAILSAFE | — | — | 同上 | canonical 不确定→回退真实可解析 provenance GitHub URL 或显式不可链接；禁猜测性 canonical | 同上 | pytest：不可判定输入回退断言（零「看似 canonical 实 404」输出） | PENDING | — |
| #64 | R3-64-LINKVAL | — | 引用展示前确定性 linkability contract（verified→canonical；unknown→provenance；neither→不渲染可点） | sources[] 构建链 | 契约冻结 | 同上 | pytest：三档契约断言 | PENDING | — |
| #64 | R3-64-CORPUS | — | — | — | 存量 Wiki 语料 corpus-wide audit：显式 slug 清单+mapper 输出 vs 权威 route 一致（权威=sitemap/构建 route 真相） | wiki-documents 语料 | pytest/审计测试：已知无效 route=0 | PENDING（audit 输出指针） | — |
| #64 | R3-64-CONSIST | — | — | citation 构建单点（rag.py:1200 同源） | widget/API 与对话审查 citation URL 构造性一致 | 同上 | pytest：三面同 URL 断言 | PENDING | — |
| #64 | R3-64-E2E | — | 真实问题 `NE503开发SDK在哪？` 端到端 | /api/ask + admin conversations | 引用指向 frontmatter 定义 route；`/docs/neoeyes-ne503-series/application-guide/resources` 不再产生 | 生产 wiki route 真相（sitemap 实证） | E2E 台账（G5 门） | PENDING | PENDING（引用面板态） |

## Integration（G4/G5 汇总）

| 项 | 内容 | 证据 |
|---|---|---|
| Visual Gate manifest | 1536×1024 @1x 截图全集+逐状态 crop↔candidate 对照表 | PENDING |
| FINAL PASS | Role A independent review 签发记录（执行 agent 无权自授） | PENDING |
| E2E 台账 | 五轨跨链各 1 条（见各 Track 行） | PENDING |
| 七门 | G1–G7 逐门证据（release-plan §5） | PENDING |

## 禁止

- 证据格出现自然语言「已实现/完成/OK/通过」而无指针（文件:行/测试名/截图编号/探针 id）。
- 执行 agent 在 G4 Visual Gate 自授 FINAL PASS。
- 用生产 mutation 换取 Runtime evidence（授权探针制度沿 r2：逐条登记，零未授权写入）。
