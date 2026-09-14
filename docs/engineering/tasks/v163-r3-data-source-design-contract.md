# v1.6.3-r3 数据源详情页 Design Source of Truth Contract（Approved Design traceability）

- **Reference 权威**：Role A 已批准 APPROVED DESIGN INPUT（已亲读，图片固定于 `/tmp/v163-refs/r3-ds-detail-approved-design.png`）。Reference = 呈现与交互意图权威；现有实现**非**设计权威；Backend/API/DB = 事实语义权威。
- 设计原则（图内冻结）：保持页面结构 / 优化命名布局而非重新设计 / 呈现前先验证 backend Truth / **Generation 在审计完成前保持冻结**。
- 规则：设计所需而 backend 无真值 → 标 **PRODUCT/FUNCTIONAL GAP**（禁前端猜测/静默省略）；逐元素标注真值状态：**[ Truth-OK ]** 现有真值可支撑 / **[ GAP ]** 需新 Truth / **[ FROZEN-UNTIL-AUDIT ]** Truth 审计前置冻结。
- 关联文档：`v163-r3-release-plan.md`、`v163-r3-acceptance-matrix.md`、`v163-reference-remediation/r3-track-{a,b,c,d}-contract.md`。

## 0. 页面骨架（Approved Design 五区）

| 区 | 名称（设计冻结） | 折叠语义 | 主责 Issue | Truth 状态 |
|---|---|---|---|---|
| ① | 数据源身份区 | 常显 | #61-3 | Truth-OK |
| ② | 异常提醒 | 常显（有异常数据态时） | #61（交互保持） | Truth-OK |
| ③ | 知识内容 | 常显（页面主体） | #61-4 | Truth-OK |
| ④ | 同步状态与活动 | 常显 | #65、#66 | Truth-OK（单位签收前置） |
| ⑤ | 健康与诊断 | **默认折叠，页面下方** | #67 | 五维术语 Truth-OK；Generation 区 FROZEN-UNTIL-AUDIT |
| — | 底部管理员操作路径条（①进页面→②处理异常→③管理知识→④查看同步→⑤深入诊断） | 常显 | 设计冻结 | 呈现性（Truth-OK） |

## 1. 逐元素 Traceability 全表

图例：Element ID = DS-R3-区-序。Interaction = 呈现+交互意图（Reference 权威）。API/Service/DB = 事实语义权威（main@94ddb64 现状核对）。

### ① 数据源身份区

| Element | 设计要求 | Issue Req | UI Interaction | API | Backend Service | DB/Runtime Truth | 验收 | Truth 状态 |
|---|---|---|---|---|---|---|---|---|
| DS-R3-1-01 | 源名+类型+地址+状态+「启用中」徽章+知识总量+最后同步（元信息行） | 既有 MATCH（矩阵 DS-P2-03/04/05/07；R2 ledger #7） | 静态呈现+外链 | GET /api/admin/data-sources/:id | data_sources 读面 | data_sources（enabled/last_sync/last_sync_status） | R2 已 PASS；r3 回归不破坏 | Truth-OK |
| DS-R3-1-02 | **「编辑」「知识设置」从 ⋯ 直出为页头按钮；删除页头 ⋯；删除冗余「返回列表」菜单项（面包屑承担导航）** | R3-61-DH | 页头两按钮；编辑开抽屉（context-preserving）；知识设置开抽屉 | 既有（PUT /data-sources/:id；知识设置 GET/PUT+preview 链） | 既有 U-5/U-12/U-13 链 | data_sources（product/type/enabled/knowledge_role/freshness_hours/next_run_at） | 四处布局按 #61 验收；类型 disabled 语义不变；高风险预览 Modal 链保持 | Truth-OK |
| DS-R3-1-03 | 同步操作移至 ④（身份区不放同步按钮） | R3-61-DH（布局收敛） | 无页头同步入口 | — | — | — | 视觉门逐区对照 | Truth-OK |

### ② 异常提醒

| Element | 设计要求 | Issue Req | UI Interaction | API | Backend Service | DB/Runtime Truth | 验收 | Truth 状态 |
|---|---|---|---|---|---|---|---|---|
| DS-R3-2-01 | 「有 N 项知识需要处理」横幅 + **「查看需处理」→ 过滤知识内容区（bucket=attention）** | 既有 MATCH（矩阵 DS-P2-09/11）+ #61（交互保持） | 点击过滤，不离页 | GET /:id/documents?bucket=attention | documents lifecycle 聚合 | documents 生命周期列 | 过滤真实生效（既有证据）；交互保持不变 | Truth-OK |
| DS-R3-2-02 | 「数据可能已过期」提醒 + **「调整知识设置」→ 打开知识设置抽屉** | 既有（U-12 链）+ #61（交互保持） | 点击开抽屉 | GET/PUT knowledge-settings + 高风险 preview | freshness 策略（词表 6/12/24/72/168h；25→422 已实证） | data_sources.freshness_hours/knowledge_role | 提醒触发=新鲜度政策真值；抽屉+预览链回归 | Truth-OK |
| DS-R3-2-03 | 设计注记：「这是一个很好的交互，保持不变」 | — | 冻结：②不得重设计 | — | — | — | 视觉门确认零漂移 | Truth-OK |

### ③ 知识内容（页面主体，设计注记「保持不变」+ 行级动作变更）

| Element | 设计要求 | Issue Req | UI Interaction | API | Backend Service | DB/Runtime Truth | 验收 | Truth 状态 |
|---|---|---|---|---|---|---|---|---|
| DS-R3-3-01 | 搜索/状态筛选/生命周期筛选/类型筛选/排序/分页（主体不变） | 既有 MATCH（矩阵 DS-P2-14/15/16/18/20/27；U-7 content_type） | 既有交互冻结 | GET /:id/documents（search/bucket/content_type/order/page） | 既有 | documents（含 content_type 41/41 生产真值） | r3 回归不破坏（vitest 既有套件） | Truth-OK |
| DS-R3-3-02 | **正常行：直接铺开 `查看真相`、`修复此知识`（无 ⋯）** | R3-61-DR | 行级两按钮直出 | 查看真相=既有 truth 只读；修复=POST 既有 repair 命令（U-8：RBAC/幂等/审计/进度/验证卡） | 既有 repair 链 | document_repair_tasks + document_versions + 向量一致性 | 桌面端不拥挤/截断/错位；修复链语义零变化 | Truth-OK |
| DS-R3-3-03 | **需处理行：直接铺开 `处理`、`查看真相`；`修复此知识` 留 ⋯** | R3-61-DR | 行级直出+overflow | 同上 + 既有处理流 | 既有 | 同上 | 条件态（disabled/pending/lifecycle）保持现有行为 | Truth-OK |
| DS-R3-3-04 | **`重新处理` 更名 `修复此知识` + tooltip「检查并修复该知识的索引一致性，不会重新从数据源获取内容。」** | R3-61-DR（语义命名） | 文案+tooltip | 零 API 变化 | repair 语义冻结（不触发上游抓取） | 同上 | UI 能明确区分 `同步` 与 `修复此知识`；「重新处理完成」验证卡等伴随文案同步更名 | Truth-OK |
| DS-R3-3-05 | 设计注记：「这是详情页的主体，保持不变」 | — | 冻结：③除行级动作外不得重设计 | — | — | — | 视觉门逐元素对照 | Truth-OK |

### ④ 同步状态与活动（设计冻结：**同步信息唯一主工作面，与列表页「同步记录」互补 #66**）

| Element | 设计要求 | Issue Req | UI Interaction | API | Backend Service | DB/Runtime Truth | 验收 | Truth 状态 |
|---|---|---|---|---|---|---|---|---|
| DS-R3-4-01 | 最近成功（相对时间+耗时）/最近结果 | 既有 MATCH（矩阵 DS-P4-02/04） | 静态 | GET /sync-runs（?source） | sync run 读面 | sync_runs/sync_log | 既有 | Truth-OK |
| DS-R3-4-02 | 同步可靠性（一位小数 %，30d）/同步周期/下次同步 | 既有 MATCH（矩阵 DS-P4-03/05/06；U-11） | 静态 | GET /sync-health + schedule truth payload | schedule_truth.reconcile_next_run_at | data_sources.next_run_at/sync_interval | r3 后：**next_run_at 必须与真实自动执行一致（#62 交付后）**；#62 未落地面禁止派生倒计时回潮 | Truth-OK → #62 后升级为执行真相 |
| DS-R3-4-03 | **本次变化：`+12 新增 · 8 更新 · 3 淘汰`（与「最近结果」同级的一等信息）** | R3-65-DELTA | 静态三值；0 显性显示 `0`；无已完成同步证据显 `—`/「暂无同步记录」 | GET /sync-runs 最新已完成 run 的 `sync_log.items_new/items_updated/items_deleted`（**权威持久化计数，禁前端差值推断**） | 既有 sync.py 写入点（items_new=len(new_docs) 等） | sync_log 四列（生产实证在位） | #65 验收 1–9；**单位=知识/文档（B 轨签收后 A 才可渲染「新增知识/淘汰知识」文案）**；partial/failed run 不伪装最终变化量 | Truth-OK（**UNIT 签收前置**） |
| DS-R3-4-04 | 最近同步活动（历史记录：时间/结果/新增/更新/淘汰/耗时/查看详情） | R3-65-DELTA + 既有 MATCH（矩阵 DS-P4-07/08/09） | 表格呈现；异常优先保持 | GET /sync-runs | 既有 buildSyncActivity（异常优先+常规压缩组） | sync_runs + sync_log | 每 run 行计数与 run 一致；与列表「同步记录」同 run 同值（R3-66-CONSIST） | Truth-OK |
| DS-R3-4-05 | 手动「立即同步」按钮 | 既有 MATCH（矩阵 DS-P4-11） | 点击 POST→运行态可见 | POST /:id/sync | 既有（**手动触发不受 #62 due gate 限制**） | sync_runs（triggered_by=manual） | 手动同步立即执行语义保持 | Truth-OK |
| DS-R3-4-06 | 设计冻结：④是同步信息唯一主工作面；列表页「同步记录」为轻量互补（3–5 条+查看完整详情） | R3-66-*（互补面在列表，见 Track A 合同） | 两面同 run 计数/状态/耗时/时间严格一致 | 同一读路径（sync-runs+sync_log join） | 单一真相源冻结 | sync_log.items_* 单一口径 | R3-66-CONSIST + #65 验收 7 | Truth-OK |

### ⑤ 健康与诊断（**页面下方默认折叠**）

| Element | 设计要求 | Issue Req | UI Interaction | API | Backend Service | DB/Runtime Truth | 验收 | Truth 状态 |
|---|---|---|---|---|---|---|---|---|
| DS-R3-5-01 | 折叠区默认收起；含「数据源健康」（5 维）+「索引生成记录」两子面；保持当前位置，不增加新导航层级 | R3-67-IA | 折叠/展开；展开不跳页 | 既有 GET /sync-health + generations 读面 | 既有 | sync-health 五维真值；index_generations | 默认折叠呈现；「本地诊断（健康与生成真相）」不再作为首要产品表达 | Truth-OK（结构） |
| DS-R3-5-02 | 数据源健康 5 维管理员术语映射：连接→连接状态、同步(30d)→同步可靠性、覆盖→知识覆盖、新鲜度→数据新鲜度、一致性→检索一致性 | R3-67-DIM | 静态映射（后端状态词不变，仅呈现词收敛） | 零 API 变化 | 前端禁重判（既有 SourceHealthPanel 纪律保持：无 regex/阈值派生/状态覆盖） | 后端五维 status/evidence/as_of 原样 | 名称映射逐字；后端 authority 保持 | Truth-OK |
| DS-R3-5-03 | 每项状态须能回答「当前状态/什么意思/为什么不可评估」；coverage unknown → 「暂不可评估」+中文解释；原始英文 evidence 下沉「高级诊断」 | R3-67-UNK / R3-67-ADV | raw evidence/threshold/run id/expected/actual/missing/extra_orphan/generation ordinal 等全部折叠进「高级诊断」 | 零 API 变化 | 零新结论（禁前端推断「是否影响 AI 回答」） | 同上 | unknown 说明可见；不新增未授权结论/推荐动作（#67 Phase 2 排除） | Truth-OK |
| DS-R3-5-04 | 索引生成记录（现状：「该源尚无索引生成记录」诚实空态） | R3-67-AUDIT/GENFIX | **FROZEN**：审计完成前保持现状诚实呈现（不改/不遮/不新解释） | generations 读面 | generation_builder + 迁移史 | index_generations（生产实证：3 行——`*legacy*` #0 ready 0/0 @迁移日、ordinal=1 failed 0/0、ordinal=2 ready 0/0；12000 document_versions 全指向非空 generation；wiki→`*legacy*` #0） | 审计报告回答 #67 审计 10 问（API 空原因/#0 根因/是否 legacy/新同步计数正常性/sentinel 建模/迁移需求）；**完成后**才可按后端建模渲染（如 legacy/untracked 显式状态）；UI 不再出现「7/7 在服 vs Generation 0/0」无解释反直觉态 | **FROZEN-UNTIL-AUDIT** |
| DS-R3-5-05 | 设计注记：「优化方向：使用管理员可理解的术语和描述 (#67)；Generation 真相需先完成数据审计 (#67)；审计完成前保持冻结」+「保持当前位置，不增加新的导航层级」 | — | 冻结 | — | — | — | 视觉门：折叠默认态+展开态双截图；Generation 区审计前后分别记录 | FROZEN-UNTIL-AUDIT |

### 补充：数据源列表页（#61-1/2 + #66；Reference=Issue 文本+已确认产品决策）

| Element | 要求 | Issue Req | UI Interaction | API | Backend Service | DB/Runtime Truth | 验收 | Truth 状态 |
|---|---|---|---|---|---|---|---|---|
| DS-R3-L-01 | 页头：`+ 添加数据源` + `同步全部` 直出；删除页头 ⋯ | R3-61-LH | 两按钮直出 | POST /data-sources/:id/sync（全部=逐源既有链） | 既有 | sync_runs | #61 验收；同步全部语义保持显式人工动作（#62 交付后不受 due gate 静默跳过） | Truth-OK |
| DS-R3-L-02 | 行级：`详情`、`同步` 直出；⋯ 保留 `编辑`、`同步记录`（原「查看可观测性」按 #66 更名）、`删除`、`重试删除`（条件态） | R3-61-LR + R3-66-RENAME | 直出+overflow；危险操作留在 ⋯ | 既有各动作端点 | 既有 | 既有 | #61+#66 合并验收；desktop 无拥挤/截断 | Truth-OK |
| DS-R3-L-03 | 行内「同步记录」：默认 3–5 条轻量记录（时间/结果/新增/淘汰/耗时）+「查看完整详情 →」；移除行内完整 SourceHealthPanel/深度诊断 | R3-66-LIGHT/NOHEALTH/DEEPLINK | 行下展开不离上下文 | 同一 sync-runs 读路径（与 ④ 单一真相源） | 既有 | sync_log.items_* | 后端无真值诚实显示不可用；同 run 双面一致 | Truth-OK（UNIT 签收前置） |

## 2. 冻结呈现语义（Track A 必须逐字遵守）

1. ②异常提醒交互保持不变（图内「很好的交互，保持不变」）；③主体除行级动作外不变；④是同步信息唯一主工作面；⑤默认折叠于页面下方、不加导航层级。
2. 「重新处理」→「修复此知识」+冻结 tooltip 文案；修复语义零变化（不触发上游抓取）；「同步」语义保持数据源级上游检查/获取+必要索引更新。
3. 本次变化三值来自最新已完成 run 的持久化 `sync_log.items_*`；0 显性显示；无证据显 `—`；partial/failed 不伪装；淘汰=后端已确认退出在服集合的权威语义，禁总数差值推断、禁 chunk 冒充知识。
4. 同步记录/最近活动同 run 双面（列表↔详情）计数/状态/耗时/时间严格一致。
5. 五维健康呈现词映射冻结（连接状态/同步可靠性/知识覆盖/数据新鲜度/检索一致性）；后端 status authority 不动；raw evidence 全部下沉「高级诊断」；unknown 必须解释为什么不可评估；禁前端组合五维推导业务影响（Service Readiness 属 #67 Phase 2 另立需求）。
6. Generation truth 区域审计完成前冻结现状诚实呈现。

## 3. GAP 清单（PRODUCT/FUNCTIONAL GAP，禁前端猜测/静默省略）

| # | Gap | 影响 Element | 归属 | 处置 |
|---|---|---|---|---|
| G-1 | 调度 due gate 真值（配置周期≠实际执行；next_run_at 未约束执行） | DS-R3-4-02 | Track B（#62） | r3 内交付；交付前 ④ 下次同步保持现有权威投影呈现、禁止派生倒计时 |
| G-2 | citation canonical route truth（frontmatter slug 无视 → 断链） | 非 DS 详情页元素（widget/admin 引用链） | Track D（#64） | r3 内交付 |
| G-3 | `items_*` 单位正式签收（知识 vs chunk） | DS-R3-4-03 / DS-R3-L-03 | Track B 签收（audit-lite）→ Track A 渲染 | 签收前 A 不得渲染「新增知识/淘汰知识」单位文案 |
| G-4 | Generation truth 审计（#0/0/0 根因、sentinel 建模、新同步计数验证、是否需迁移/backfill） | DS-R3-5-04 | Track B（#67 审计）→ A 解冻 | **FROZEN-UNTIL-AUDIT**；审计前现状诚实呈现 |
| G-5 | Service Readiness/业务化结论/推荐操作/真覆盖率（#67 Phase 2） | ⑤（未来） | 不在 r3 | 另立独立产品需求；后端权威返回结构已在 #67 冻结示例 |

## 4. STOP

本合同为 planning 产物：零实现、零后端变更、零生产写入。元素级「Truth 状态」的最终裁决权在 Role A；执行 agent 无权变更冻结语义。
