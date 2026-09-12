# FROZEN TASK CONTRACT — #50 Admin Data Source Workspace V2(B1)

Iteration:v1.6.2;owner=B1;依赖:无 inbound;对外:**FROZEN INTERFACE → #51**
(详情路由 `/data-sources/{source_id}`);报告文件:docs/engineering/tasks/
v162-i50-data-source-workspace-v2-execution.md(B1 产出)。

## Objective

管理员在 `配置 → 数据源` 打开任一数据源的**单一详情工作面**,不借助
SSH/SQL/Weaviate 即可回答:
1. 这个源里有什么知识(可搜索的内容清单)?
2. 这一条(item)现在可用吗(在服/检索状态)?
3. 不可用/有风险的话,为什么(权威原因)?
4. 这个源的同步/生命周期/生成健康如何,最近发生了什么变化?

## Product Semantics(页面表达的 truth)

- 内容清单与状态一律来自**权威账本**(documents / document_versions /
  document_version_chunks / index_generations / sync_log / sync_runs),
  Weaviate 永不作为 UI 真相源;计数展示"预期 vs 账本 vs 已索引"中以
  后端可证者为准(sync-health consistency / source-health 聚合已有定义)。
- 运营三桶语义(冻结桶定义,B1 冻结具体状态映射,须逐态可解释):
  - **Current**:当前在服集合(权威 = current_version_id ⋈ SERVING 语义);
  - **Needs Attention**:有权威证据的风险项(如 missing_candidate 标记、
    同步覆盖/一致性缺口、删除生命周期错误、失败生成);
  - **Retired**:已接替/删除/退役(superseded/deleted + 版本链与退役时间)。
- 每个非 Current(或有风险)条目**必须显示原因**;后端无记录的原因显示
  "后端无此记录",不得编造。
- L 轴/生成状态 → 运营标签与 badge 语义必须来自**单一权威前端映射模块**
  (语义级冻结:一处定义、详情面消费、#51 可复用;具体文件位置与形态 =
  B1 工程设计,合同不规定)。

## UX Intent

- 详情工作面路由 **`/data-sources/{source_id}`**(冻结);列表页行点击/操作进入;
  列表页现有能力(同步/编辑/删除/可观测性展开)**保持不变**。
- 信息层级:身份/配置摘要 → 同步与健康(复用现有三面板)→ 内容清单
  (搜索/过滤/分页表格)→ 生成/生命周期可见性 → 最近变化(同步历史)。
- 主操作仅:查看、搜索、过滤、分页、既有同步触发;**零新增破坏性控件**。
- 关键交互:item 行展开/点击显示单条真相(状态、原因、版本/生成归属、
  canonical URL、时间戳);loading/error/empty 沿用 LoadError 三态纪律。

## Current Truth(仓库证据)

已有:平铺列表 + 行内可观测性展开(SyncStatusPanel/SyncHistoryPanel/
SourceHealthPanel)、聚合计数(doc_count/chunk_count)、删除生命周期、
30 天可靠性、五维健康。
缺失:任何内容清单 UI 与端点;单文档真相;生成可见性;版本链可见性;
详情工作面本身。

## Change Boundary

- **EXPECTED**:新增只读 admin 端点族(逐源文档清单[分页/过滤/搜索]、
  单文档真相、逐源生成列表——端点形状由 B1 工程设计,所有权冻结见
  iteration plan §3 矩阵);详情工作面路由 + UI;L 轴/生成状态运营标签
  单一权威映射模块(位置=B1 设计自由);
  后端 pytest + admin vitest。
- **REQUIRED SUPPORTING**:现有三面板迁入/复用于详情面;列表页入详情的
  入口;auth 沿用 require_role 读约定(viewer 可读,写零新增)。
- **FORBIDDEN**:per-item 编辑/删除/重索引等破坏性控件;独立 Knowledge
  顶级模块;重复 Overview 标签页;虚构 content-role/discovered/last-seen
  等后端不存在的字段或状态;Weaviate 直连读;retention/时长设置 UI
  (#30 残余/P5);检索/排序/引用语义变更;**任何 P1/lifecycle/生成语义
  变更(本合同是只读观察面,状态机零改动)**。
- **BEHAVIORAL**:列表页全部现有行为零回归;新端点全部只读 GET;
  RBAC 不变。

## Dependencies

- inbound:NONE。
- outbound:FROZEN INTERFACE → #51:`/data-sources/{source_id}` 路由 +
  source_id 编码(DataSource.id 单段);COMMIT(可选复用):L 轴/生成状态
  前端标签映射模块(语义单一权威;B1 产出,#51 按需采用)。

## Acceptance Criteria(独立可验收)

1. 逐源文档清单端点:分页 + 至少按生命周期过滤 + title/url 子串搜索;
   行含 title、canonical url/path、L 轴状态、可检索状态、chunk_count、
   updated_at(权威时间戳);后端测试覆盖(含空源/全 Retired 源)。
2. 单文档真相:状态 + 不可用/风险原因(权威字段)+ 所属版本与生成
   (ordinal/status)+ canonical 身份;无记录原因显式表达。
3. 生成可见性端点:逐源 generations(ordinal/status/doc/chunk 计数、
   activated/retired 时间、failure 证据);失败生成显示原因。
4. 详情工作面:四问全部可答(§Objective);Current/Needs Attention/
   Retired 三桶可见,三桶映射逐态可解释(设计记录进执行报告)。
5. 计数真相:预期/账本/已索引按既有权威定义展示,不可证处显式标注。
6. 列表页零回归(既有测试全绿);新端点只读(无任何写路径);RBAC
   viewer 可读。
7. L 轴/生成状态标签来自单一权威映射模块并在详情面消费(文件位置 =
   B1 设计自由;语义一处定义、无第二份映射表)。
8. 后端 pytest 新增覆盖 + 全量回归绿;ruff 改动文件 0 error;admin
   vitest 新增覆盖 + 全绿。

## Runtime / Real-World Acceptance(强制,Phase 5)

生产或生产等价全栈部署上,运营员走查(截图/转写):
- 真实源 A(wiki-documents-local):找到一条已知文档 → 确认"可用";
- 真实源 B(woocommerce-mall):找到一条商品页 → 确认可用状态与 canonical URL;
- 构造/利用真实风险样例(如生产 index_generations 中 failed 的 ordinal=1
  审计行,或任一 Needs Attention 项)→ 界面显示原因;
- 界面显示的生成/生命周期事实与 psql 抽查一致(验收者可比对);
- 全程零 SSH/SQL 操作(比对仅在验收取证时使用)。
Issue 关闭前置:部署后生产可见面与本合同语义一致(版本号≠交付)。
