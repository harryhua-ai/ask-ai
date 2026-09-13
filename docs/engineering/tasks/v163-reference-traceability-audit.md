# V1.6.3 REFERENCE → PRODUCT → BACKEND → FRONTEND FULL TRACEABILITY AUDIT

- **审计 ID**:v163-reference-traceability-20260913
- **审计分支**:`audit/v163-reference-traceability-20260913`(audit worktree /Users/harryhua/Documents/GitHub/ask-ai-v163-audit)
- **审计对象(candidate)**:7e3e71cc1d50a19e8625fffcacbe1c0f7b11af76(谱系 34c7d5b→2f0bc06→8fa121a→7e3e71c tip;rem worktree /Users/harryhua/Documents/GitHub/ask-ai-v163-rem 逐字同 SHA 且 status 干净)。**7e3e71c 不再被授权发布,仅作审计对象。**
- **origin/main**:@5c501914636ae274bdf54896e3decf86c4584e12(审计期间未动)
- **治理口径**:参考中每个 material 可见元素/交互默认 REQUIRED;终分类只允许 MATCH / IMPLEMENTATION DEFECT / PRODUCT-FUNCTIONAL GAP / USER-APPROVED DESIGN CHANGE / REFERENCE CONFLICT;一切旧豁免词汇作废;缺后端能力 = PRODUCT/FUNCTIONAL GAP,不是省略许可;USER-APPROVED DESIGN CHANGE 仅限 User 既有明确决定(V-1 行高 41px、V-3 同步/活动结构、V-2 FAB 抑制)。
- **铁律遵守**:本审计零产品代码修改、零 merge、零 deploy、零关 issue;仅新增 docs/engineering/tasks/v163-reference-* 文档并提交至审计分支。

---

## §0 Reference Inventory(权威输入核验)

| 项 | 值 |
|---|---|
| 参考 1(数据源运营) | docs/product/design/admin-knowledge-ops/references/data-source-operations-original.png |
| git blob | e9ff043d984985e1f56acf24553c9a282c15b105(docs branch origin/docs/v163-design-baseline-20260912) |
| SHA-256 | bdcaa87910f28684de7fc731254f4ad4f4353417eb14e9f29a03d0b424287efd |
| 尺寸 | 1536×1024 |
| 参考 2(技术洞察·回答缺口) | docs/product/design/admin-knowledge-ops/references/technical-insights-answer-gaps-original.png |
| git blob | 15af093eb78412e0f34d4e8bd59799244a59fc9d |
| SHA-256 | 3aea88a2ee53713aab819c65016abbcba313d05bd831b5ea42a30a6ae7af88d0 |
| 尺寸 | 1536×1024 |
| 本机逐字副本 | /tmp/v163-audit-refs/*.png |
| 副本 SHA-256 复核 | 本审计 agent 以 `shasum -a 256` 复核:**两文件与上值逐字一致**(复核输出存 acceptance/v163-traceability-audit-20260913/runtime-checks/) |
| Read 复核 | 两张 PNG 均由本 agent 用 Read 工具直接读取原图(非截图/裁剪/报告转述),读取时间 2026-09-13;原子分解以该直读为准 |

## §1 方法

1. 直读两张权威 PNG,逐面板逐元素原子分解(不合并、不为减数合并);稳定 ID:DS-*(P1..P7)/TI-*/SH-*。
2. 每条原子需求建矩阵行,列含:参考 ID/区域/要求/期望呈现/期望行为/期望产品语义 ‖ 前端组件:文件/运行时状态/当前行为 ‖ 后端 API 依赖/持久化依赖/现有支持/权威数据真值 ‖ 分类 ‖ 证据/所需实现/验收测试/需 User 决定。
3. 证据纪律:**截图不能独立证明功能 MATCH;代码不能独立证明运行时 MATCH**。功能控件以真实 UI→API→持久化三角验证;缺能力无法产生的状态 = PRODUCT/FUNCTIONAL GAP。
4. Runtime verification 仅走既有真实状态(真实 UI→API→DB);fixture 只允许真实 DB→真实 API→真实前端;零前端注入。写操作链本审计未重复执行(引用既有授权功能链证据),保持零副作用。
5. 旧验收材料(23 JD、C 类 23、A20/B6)全部映射到新矩阵,显式 PREVIOUSLY EXEMPTED → NEW CLASSIFICATION(见 remediation plan §4),不继承任何 PASS。

## §2 矩阵列规范

15 列,见各矩阵文件表头。分类列恰好一个值;「需 User 决定」列标注 U-* 编号(remediation plan §5)。

## §3 全量追溯矩阵索引(矩阵本体完整,按面拆分)

| 文件 | 覆盖 ID | 行数 |
|---|---|---|
| v163-reference-remediation/matrix-SH.md | SH-01..SH-16 | 16 |
| v163-reference-remediation/matrix-DS-P1.md | DS-P1-01..24 | 24 |
| v163-reference-remediation/matrix-DS-P2.md | DS-P2-01..27 | 27 |
| v163-reference-remediation/matrix-DS-P3-P4.md | DS-P3-01..09、DS-P4-01..11 | 20 |
| v163-reference-remediation/matrix-DS-P5-P6-P7.md | DS-P5-01..09、DS-P6-01..05、DS-P7-01..06 | 20 |
| v163-reference-remediation/matrix-TI.md | TI-01..45 | 45 |
| **合计** | | **152** |

### 终分类分布(2026-09-13 Planning 修订:Role A 裁决冻结后重算)

| 分类 | 行数 | 变化说明 |
|---|---|---|
| MATCH | **105** | +1:SH-16 经 U-1 解决(LIGHT=权威方向,实现已浅色) |
| IMPLEMENTATION DEFECT | **4**(SH-06、DS-P5-02/04/05) | 不变;DS-P5-04 方向已冻结(U-5)但仍为待修复缺陷 |
| PRODUCT-FUNCTIONAL GAP | **38**(归并 17 族,见 gap register) | −2:SH-10/11 经 U-3 转 UADC |
| USER-APPROVED DESIGN CHANGE | **5**(UADC-1/2/3 既有 + UADC-4 帮助中心推迟) | +2 行(SH-10/11) |
| REFERENCE CONFLICT | **0** | −1:SH-16 经 U-1 解决;UNRESOLVED REFERENCE CONFLICT 目标=0 已达成 |

矩阵行新增「冻结决定」列(U-x 或 N/A);方向获授权 ≠ 变 MATCH:GAP 行保持 GAP 直到实现+运行时验收完成。

## §4 Runtime Verification 记录(2026-09-13,真实栈)

- 栈:vite http://localhost:5184/admin/(伺服 rem=7e3e71c 干净树)+ backend http://localhost:8104(/health git_sha=34c7d5b 为启动时点旧值;后端代码与 7e3e71c 零 diff,不影响审计对象判定)+ docker ask-ai-local-postgres-1@5432(ask_ai)+ weaviate。
- 登录:admin@camthink.ai(真实 JWT 登录成功)。
- API→DB 三角核验(证据:acceptance/v163-traceability-audit-20260913/runtime-checks/,pg-truth.txt):
  - GET /data-sources:6 源 → PG data_sources=6 ✓
  - GET /data-sources/attention-summary:sdk-docs-auditfx ledger 1204/attention 0;store-woo attention 3 → PG documents(store-woo)=8、lifecycle {active:6, missing_candidate:2}+1 无现行 ✓
  - GET /analytics/source-health:store-woo 78 次(77 成功+1 partial)rate 0.9872 → PG sync_log 30d {success:77, partial:1} ✓(参考 98.7% 公式成立)
  - GET /tech/answer-gaps:total 12;b2a00001 23/18 → PG question_clusters=12、conversations(cluster b2a00001)=18 ✓
  - PG question_clusters.status DISTINCT = {open, resolved} → **观察中状态后端不存在(GAP-B2-2 的能力缺失直证)**
- UI 真实截图(Chromium headless 1536×1024 @1x,真实登录):01 列表 / 02 详情 / 03 展开真相 / 04 同步活动 / 05 编辑抽屉 / 06 回答缺口队列 / 07 诊断侧板 / 08 历史 Tab。
- 数据态记录:本地库含此前授权功能链残留(ne301 源、排队态「当前同步」面板);属运行数据漂移,非实现缺陷,验收前建议 fixture 重放清理。
- 能力缺失直证(代码+运行时双查):无 temporal/时态/新鲜度策略端点;无 reprocess/行级修复 admin 端点(corpus_repair 仅 CLI dry-run/apply,生产需独立授权);无 CSV 导出端点;无 observing 状态;无逐文档 serving 分数/恢复计数端点;无 next_run_at 调度真值;无 gap→source 关联;无用户聚合;无 topic 字段;documents 无逐文档 content_type。

## §5 Backend Reality Audit(GAP 实现边界摘要;详见 gap register 各族「后端范围」)

| 边界族 | 结论 |
|---|---|
| 呈现层可修(零后端) | SH-06、DS-P5-02/04/05 |
| 只读投影可修(无新表) | TI-27(需先补会话用户标识)、TI-33(需归因规则)、DS-P3-05(chunk 级 serving 投影)、DS-P4-03(调度器暴露 next_run_at) |
| 需新持久化/状态机 | GAP-B1-4(修复任务+审计)、GAP-B1-9(策略表+资格贯通)、GAP-B2-2(observing+流转事件表)、GAP-B1-3(documents content_type) |
| 需新服务 | GAP-B2-3(导出流式+隐私规则+审计)、GAP-B1-10(mutation-preview 权威计算+确认后重验) |
| 需分类学/生成契约 | GAP-B2-1(六新类证据规则)、GAP-B2-6(topic 生成,LLM 需单独授权)、GAP-B1-2(引用重验真相) |

## §6 结论

V1.6.3 CONFORMANCE = **FAIL**(仍待全部 GAP/DEFECT 实现+运行时验收)。修复拓扑、冻结合同、新终局验收规则、旧豁免全量 reconcile、执行授权包见:
- docs/engineering/tasks/v163-reference-gap-register.md
- docs/engineering/tasks/v163-reference-remediation-plan.md(含 IMPLEMENTATION AUTHORIZATION PACKAGE)
- docs/engineering/tasks/v163-reference-remediation/track-{a..f}-contract.md

---

## ROLE A PRODUCT DECISIONS — FROZEN(2026-09-13 Planning 修订)

19 项产品裁决(U-1..U-19)全部冻结,**不得再升给 User**。逐项结果+理由:

| # | 议题 | 裁决 | 性质 |
|---|---|---|---|
| U-1 | 侧栏明暗(SH-16) | **LIGHT 侧栏=权威实现方向,无双主题需求**;实现已浅色 → MATCH,REFERENCE CONFLICT 关闭 | Role A 定 |
| U-2 | 日期范围(SH-09) | **实现;范围=技术洞察分析窗(非全站假全局过滤);技术洞察相关 API 在语义适用处必须遵守所选窗口** | Role A 定 |
| U-3 | 帮助中心(SH-10/11) | **无权威目标 → USER-APPROVED DESIGN CHANGE(UADC-4)**:「Help Center 入口推迟至存在权威目的地」;保留追溯行;本批唯一获批缺席 | §2 默认冻结 |
| U-4 | 侧栏收起(SH-12) | **实现为纯 Admin shell 交互,零后端语义** | Role A 定 |
| U-5 | 编辑抽屉类型(DS-P5-04) | **create 可选;edit 既有源 immutable/disabled;匹配参考** | Role A 定 |
| U-6 | 品牌(DS-P2-02) | **实现,用权威的 source-type/品牌呈现内建映射;不得引入任意远程 logo_url 作为产品真值** | Role A 定 |
| U-7 | 逐文档内容类型(DS-P2-16/20) | **实现为结构化后端真值,connector/ingestion 所有;前端禁止从文件名/文本推断** | Role A 定 |
| U-8 | 行级修复(DS-P2-25/26、DS-P3-07..09) | **实现真实修复工作流:授权/RBAC、幂等命令、可审计执行、进度/结果、修复后验证;禁止假 UI-only repair** | Role A 定 |
| U-9 | serving 分数(DS-P3-05) | **实现,源自权威 chunk serving 投影;UI 比例(10/12)必须等于后端真值** | Role A 定 |
| U-10 | 恢复计数(DS-P3-06) | **实现,源自持久化权威恢复事件;禁止前端计数器** | Role A 定 |
| U-11 | 下次同步(DS-P4-03) | **实现 scheduler 权威 next_run_at;调度现实与 sync_interval 不符时禁止纯派生倒计时** | Role A 定 |
| U-12 | 知识设置(DS-P6 全部) | **实现,产品语义冻结**:CURRENT=有资格支撑当前事实型回答,受新鲜度政策约束,过期 CURRENT 证据必须诚实浮现;HISTORICAL=保留用于历史问题/溯源/证据链,**不得**支撑「当前价格/当前规格/当前可用性/当前运行状态」类断言。新鲜度政策:按 source/policy 域可配置、后端权威、过期态 Admin 可见、检索资格必须消费该政策真值。**不得重设计整个 lifecycle 模型**——叠加在现行 lifecycle 真值之上的证据资格政策层 | §2 默认冻结 |
| U-13 | 高风险预览(DS-P7 全部) | **实现;依赖知识设置语义;影响计数必须后端权威;确认必须施加与预览完全一致的 mutation,否则 drift 时失效/重算** | Role A 定 |
| U-14 | 原因词表(TI-09、DS-P2-10) | **实现参考要求的扩展词表;每类需证据规则;禁止 keyword-only 前端分类** | Role A 定 |
| U-15 | 观察状态机(TI-07/18/36/37/41/42/43) | **实现 OPEN→OBSERVING→RESOLVED**:进入 OBSERVING 需操作者确认内容修复完成+相关源 sync/reindex 成功+post-sync 验证成功;默认观察期 7 天;OBSERVING 期间同一 gap/证据失败复现→回 OPEN,满窗无复现→转 RESOLVED;操作者可中止 OBSERVING→OPEN;**不得直接强转 RESOLVED**;全部转移持久化、带时间戳、可审计、History 可见 | §2 默认冻结 |
| U-16 | 导出相关对话(TI-34/35/45) | **实现 admin-only 导出;最小必要字段;排除直接个人身份;导出动作可审计;CSV 必须与所选 gap/query 范围精确对应** | Role A 定 |
| U-17 | 受影响用户(TI-27) | **不引入真人身份追踪**;定义=所选分析窗内去重的伪匿名会话/会话行为者;稳定匿名 actor/session 身份、不需姓名/邮箱/IP、隐私保持聚合;历史数据不可回填则诚实显示 unavailable(不得编造计数);未来数据必须支持权威聚合。**仓库证据支持**:conversations.session_id(String(64),widget 匿名会话 ID)已存在,可直接承载;历史 NULL 行诚实 unavailable | §2 默认冻结 |
| U-18 | gap→源归因(TI-33) | **实现;关联必须源自证据/对话/检索真值;禁止前端猜** | Role A 定 |
| U-19 | 主题短语(TI-12) | **实现;优先确定性派生;仅当确定性质量明显不足且另行授权才用 LLM;必须稳定且忠实于 cluster 内容** | Role A 定 |

**按 §2 默认冻结项**:U-3、U-12、U-15、U-17。**仓库可行性复核结论**:四项均可行,无一项因仓库证据不可行而升级回 User——
- U-17:`conversations.session_id` 已存在(backend/db/models.py Conversation;sales_leads.thread 依赖),伪匿名会话身份可承载;
- U-15:`question_clusters.status` 词表可扩展(open/resolved);`sync_runs`(status/finished_at/consistency)+`sync_log`+verify_source_vectors 提供进入条件的同步/验证钩子;
- U-12:`data_sources` 加性策略列与现行 S0 lifecycle 列(documents.lifecycle 词表 active/superseded/missing_candidate/deleted/discovered)正交,政策层可叠加不重设计;
- U-3:无权威目的地证据确凿(无帮助路由/外链/内嵌内容源),获批缺席成立。

**升级回 User 项:无。**
