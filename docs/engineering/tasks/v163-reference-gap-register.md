# V1.6.3 Reference Gap Register(2026-09-13 Reference Traceability Audit;Planning 修订:Role A 裁决冻结)

分类铁律:只允许 MATCH / IMPLEMENTATION DEFECT / PRODUCT-FUNCTIONAL GAP / USER-APPROVED DESIGN CHANGE / REFERENCE CONFLICT。旧豁免词汇(JD/APPROVED ABSENCE/ADAPT/N-A 等)全部作废,不得再作为分类。缺后端能力不是省略参考特性的许可——一律记 PRODUCT-FUNCTIONAL GAP。

追溯矩阵:docs/engineering/tasks/v163-reference-traceability-audit.md §3 索引。总计 152 条原子需求(Planning 修订后):**MATCH 105 / IMPLEMENTATION DEFECT 4 / PRODUCT-FUNCTIONAL GAP 38(17 族)/ USER-APPROVED DESIGN CHANGE 5 / REFERENCE CONFLICT 0**。

---

## ROLE A PRODUCT DECISIONS — FROZEN(2026-09-13)

19 项产品裁决(U-1..U-19)全部冻结,不得再升给 User;逐项全文见主审计文档同名章节。按 §2 默认冻结:U-3/U-12/U-15/U-17(仓库可行性均复核通过,**升级回 User 项:无**)。矩阵行分类影响:SH-16 → MATCH(U-1);SH-10/11 → USER-APPROVED DESIGN CHANGE(UADC-4,U-3);其余 GAP/DEFECT 行保持原分类直到实现+运行时验收完成。每行「冻结决定」引用见各矩阵文件末列。

---

## A 类 — IMPLEMENTATION DEFECT(4;既有权威真相内可修,零新后端语义)

| ID | 矩阵行 | 面 | 前端范围 | 后端范围 | 数据模型范围 | 依赖 | 验收要求 | 冻结决定 |
|---|---|---|---|---|---|---|---|---|
| DEF-A1 | SH-06 | 共享 chrome | admin/src/components/Sidebar.tsx:新增「系统」分组,用户管理/系统信息移入 | 无 | 无 | #52 冻结导航清单需同步修订记录 | /admin 侧栏出现 系统 组;vitest 断言组标签与归属;截图对照 PNG2 | N/A |
| DEF-A2 | DS-P5-02 | B1-P5 | admin/src/components/dataSources/SourceEditorDrawer.tsx:「产品线」label 收敛为「名称*」(真值 product 不变) | 无 | 无 | 无 | vitest label 断言;编辑抽屉截图对照 PNG1 面板5 | N/A |
| DEF-A3 | DS-P5-04 | B1-P5 | SourceEditorDrawer.tsx:编辑态类型字段禁用(参考语义:创建后类型不可变) | 无(不动 PUT 语义) | 无 | ~~需 User 决定~~ **已解决(U-5)** | 编辑抽屉类型 disabled+vitest;新建态类型选择保留(create 可选) | **U-5 已冻结:create 可选;edit 既有源 immutable/disabled** |
| DEF-A4 | DS-P5-05 | B1-P5 | SourceEditorDrawer.tsx:启用 checkbox → 「自动同步」toggle+说明文案「开启后,系统将按设定周期自动同步。」(真值 enabled 不变) | 无 | 无 | 无 | toggle 切换→保存→PUT enabled 真实生效;vitest+截图 | N/A |

## B 类 — PRODUCT-FUNCTIONAL GAP(38 矩阵行,归并为 17 个 Gap 族;每族给出实现边界,不过度设计)

**方向已全部获授权(U-x 冻结)≠ 变 MATCH:各族保持 GAP 直到实现+运行时验收完成。**

### 共享 chrome

| GAP ID | 矩阵行 | 面 | 前端范围 | 后端范围 | 数据模型范围 | 依赖 | 验收要求 | 冻结决定 |
|---|---|---|---|---|---|---|---|---|
| GAP-SC-1 全局时间范围 | SH-09 | PNG2 顶栏 | Layout 顶栏范围控件 + BC-1/BC-2 后端窗口参数能力(remediation plan §3.5 能力矩阵 Outcome B:/tech/answer-gaps 与 /analytics/source-health 窗参数表 IF-7 全词表;仅参数能力,无新表无新端点) | 范围语义贯通技术洞察窗口面 S1/S2/S5(语义适用处;S3/S4/S6 例外面随冻结) | 无新表 | 无(U-2 已冻结) | 选择范围→技术洞察读面窗口真实联动(API 参数可见;无窗口面卡片停留异窗) | **U-2:实现;范围=技术洞察分析窗,非全站假全局过滤**(终轮 review fix:能力矩阵 Outcome B 冻结) |
| ~~GAP-SC-2 帮助中心~~ | ~~SH-10/11~~ | — | — | — | — | — | — | **已移出 GAP:U-3 → UADC-4(获批缺席,见 C 类)** |
| GAP-SC-3 侧栏收起 | SH-12 | 侧栏 | 折叠/展开+布局联动 | 无 | 无 | 无(纯前端产品功能) | 真实点击折叠/展开截图;状态可选记忆 | **U-4:实现;纯 Admin shell,零后端语义** |

### B1 数据源运营

| GAP ID | 矩阵行 | 面 | 前端范围 | 后端范围 | 数据模型范围 | 依赖 | 验收要求 | 冻结决定 |
|---|---|---|---|---|---|---|---|---|
| GAP-B1-1 品牌资产 | DS-P2-02 | 详情身份块 | 渲染品牌图 | source-type/品牌呈现内建映射 | 映射表(前后端约定;无任意 logo_url) | 无 | 真实源按内建映射渲染品牌图 | **U-6:source-type/品牌内建映射;禁任意远程 logo_url 作产品真值** |
| GAP-B1-2 banner 原因分类 | DS-P2-10 | 详情 banner | 文案呈现 | 原因分类扩展(引用一致性重验真相)——与 GAP-B2-1 同一分类学契约 | 会话/文档级原因真相 | 依赖 GAP-B2-1 | banner 原因行与后端分类一一对应;「1 项引用需要重新验证」类可出现 | **U-14:扩展词表+每类证据规则;禁 keyword-only 前端分类** |
| GAP-B1-3 逐文档内容类型 | DS-P2-16/20 | 详情工作区 | 类型列+类型过滤 | 连接器逐文档 content_type 抽取;documents 过滤参数 | documents 类型列/推导规则 | 无 | NE101=商品/Getting Started=页面/Legacy Guide=文档;过滤真实生效 | **U-7:结构化后端真值,connector/ingestion 所有;前端禁文件名/文本推断** |
| GAP-B1-4 行级修复 | DS-P2-25/26、DS-P3-07/08/09 | 详情行+展开行 | 处理按钮+行 ⋯+验证卡 | 修复命令端点(RBAC/幂等/审计/进度/修复后验证) | 修复任务+审计持久化 | 修复契约已冻结(U-8);GAP-B1-5 依赖其分数变化 | 真实点击→POST→重处理→文档转在服→UI 反映;审计行可查;验证卡 vN/12/12/一致性=真值 | **U-8:真实修复工作流(RBAC/幂等/可审计/进度/修复后验证);禁 UI-only repair** |
| GAP-B1-5 chunk 级服务分数 | DS-P3-05 | 展开行 | 10/12 分数呈现 | chunk 级 serving/总数投影(复用 verify_source_vectors 口径) | 无新表(投影) | 依赖 GAP-B1-4(修复后分数变化可证) | 分数=真实核验值;UI 比例必须=后端真值 | **U-9:源自权威 chunk serving 投影;UI 比例=后端真值** |
| GAP-B1-6 逐文档恢复计数 | DS-P3-06、DS-P4-10(带内) | 展开行 | 恢复注记 | 逐文档自动恢复事件计数投影 | 恢复事件记录(sync_runs 细化) | 无 | 注记次数=真实恢复事件数 | **U-10:源自持久化权威恢复事件;禁前端计数器** |
| GAP-B1-7 修复验证卡 | DS-P3-08/09 | 展开行 | 成功卡+一致性行 | 修复结果+一致性核验入修复流 | 同 GAP-B1-4 | 依赖 GAP-B1-4/5 | 修复完成→卡片呈现 vN、12/12、一致性验证 通过(真实值) | **U-8(同 GAP-B1-4)** |
| GAP-B1-8 调度真值 | DS-P4-03 | 同步活动 | 下次同步倒计时 | next_run_at 调度真值端点 | 调度状态(现 sync_interval 推导) | 无 | 倒计时=调度器权威;同步完成后刷新 | **U-11:scheduler 权威 next_run_at;调度现实与 sync_interval 不符时禁纯派生倒计时** |
| GAP-B1-9 知识设置域 | DS-P6-01..05(5 行) | 知识设置 Drawer | 抽屉全面 | 知识设置读/写端点;证据资格语义;新鲜度阈值+超期提醒+过期态 Admin 可见 | 源级策略持久化(资格角色/新鲜度);资格判定贯通检索 | 无 | 打开→读→写→重开一致;HISTORICAL 后检索资格真实变化;超期提醒出现;过期 CURRENT 诚实浮现 | **U-12:CURRENT=有资格支撑当前事实型回答(受新鲜度政策约束,过期诚实浮现);HISTORICAL=仅历史/溯源/证据链,不得支撑当前价格/规格/可用性/运行状态断言;新鲜度按 source/policy 域可配置、后端权威、资格消费政策真值;不重设计 lifecycle 模型(叠加政策层)** |
| GAP-B1-10 高风险预览域 | DS-P7-01..06(6 行) | 预览 Modal | Modal 全面 | mutation-preview API(影响计数服务端权威计算);确认后一致性保障 | 无新表(计算+任务) | 依赖 GAP-B1-9 | 保存高风险变更→Modal 弹出;202/199/199 型计数=服务端真实计算;确认→与预览完全一致的 mutation 生效;drift 时失效/重算 | **U-13:实现;影响计数必须后端权威;确认施加与预览完全一致的 mutation,否则 drift 失效/重算** |

### B2 技术洞察

| GAP ID | 矩阵行 | 面 | 前端范围 | 后端范围 | 数据模型范围 | 依赖 | 验收要求 | 冻结决定 |
|---|---|---|---|---|---|---|---|---|
| GAP-B2-1 原因分类扩展 | TI-09(联动 GAP-B1-2) | 回答缺口 filter+chips | 新词选项/徽章 | classify_gap_miss_types 扩展:内容过期/检索异常/生成异常/引用异常/内容冲突/内容缺失(须有会话级证据规则) | 分类真相(推导或列) | 无 | 每个新词至少 1 行真实分类证据;旧 4 类回归不变 | **U-14:实现参考要求的扩展词表;每类需证据规则;禁 keyword-only 前端分类** |
| GAP-B2-2 观察状态机 | TI-07/18/36/37/41(带内)/42/43(7 行) | 队列+侧板+CTA | 观察中徽章/过滤/开始观察 CTA/内容补充区块/历史时间线 | OPEN→OBSERVING→RESOLVED 状态机:进入命令(操作者确认+sync/reindex 成功+post-sync 验证成功)/观察期 7 天/复现回 OPEN/满窗转 RESOLVED/中止→OPEN;禁直接强转 RESOLVED;转移持久化/带时间戳/可审计/History 可见 | question_clusters.status 扩展+观察元数据+流转事件表 | 无 | 真实点击开始观察→同步核验→行转观察中;复现→回 OPEN;满窗→已解决;历史 Tab 出现流转记录 | **U-15:实现 OPEN→OBSERVING→RESOLVED;进入需操作者确认+sync/reindex 成功+post-sync 验证成功;默认观察期 7 天;复现回 OPEN;满窗转 RESOLVED;可中止;禁强转 RESOLVED;转移全部持久化可审计** |
| GAP-B2-3 导出与隐私 | TI-34/35/45(3 行) | 推荐操作卡 | 导出卡+隐私说明+下载行为 | admin-only 导出端点(范围=所选 gap/query;最小必要字段;排除直接个人身份;CSV;审计) | 无新表(流式导出+审计行) | 无 | 点击→真实 CSV 下载;内容与所选范围精确对应;不含直接个人身份;审计可查 | **U-16:admin-only 导出;最小必要字段;排除直接个人身份;可审计;CSV=所选范围** |
| GAP-B2-4 用户聚合 | TI-27 | 侧板头 | 涉及 N 个用户 | 会话→伪匿名会话去重聚合投影 | conversations.session_id(已存在,无需新列) | 无 | N=所选分析窗内去重权威计数,与 API/DB 三角一致;历史 NULL session_id 行诚实 unavailable | **U-17:不引入真人身份追踪;去重伪匿名会话;不需姓名/邮箱/IP;隐私保持聚合;历史不可回填诚实 unavailable;仓库证据:session_id 已存在,可行** |
| GAP-B2-5 gap→源归因 | TI-33 | 概览 | 相关数据源卡+外链 | gap→source 关联投影(会话证据→服务源归因规则) | 归因投影(只读) | 无 | 外链真实到达源详情;归因有证据规则依据 | **U-18:关联源自证据/对话/检索真值;禁前端猜** |
| GAP-B2-6 主题短语 | TI-12 | 队列主列 | 主题式标题呈现 | 主题生成契约(确定性派生优先) | clusters topic 字段 | 无 | 主题稳定(同簇多次拉取不变)、忠实簇内问句;无主题时回退代表问句 | **U-19:确定性派生优先;LLM 仅当确定性质量明显不足且另行授权;稳定且忠实 cluster 内容** |

## C 类 — USER-APPROVED DESIGN CHANGE(5)

| ID | 矩阵行 | 内容 | 批准来源 |
|---|---|---|---|
| UADC-1 | SH-13 | KB-OPS 三面(/data-sources、/data-sources/:id、/analytics)抑制 LoginChat 浮动 FAB | User 裁 V-2 ACCEPTED(remediation 附录 B) |
| UADC-2 | DS-P1-23 | 列表行高 41px(参考 ~36px) | User 裁 V-1 ACCEPTED 不变 |
| UADC-3 | DS-P4-01 | 同步状态/活动为页内 section(参考为浮层卡+X) | User 裁 V-3 ACCEPTED 不变 |
| UADC-4 | SH-10/11 | **Help Center 入口推迟至存在权威目的地**(无权威帮助路由/外链/内嵌目标;本批唯一获批缺席;保留追溯行) | Role A 裁 U-3 冻结(§2 默认) |

## D 类 — REFERENCE CONFLICT(0)

~~CONFLICT-1(SH-16 侧栏明暗)~~ **已解决(U-1,Role A 冻结)**:LIGHT 侧栏=权威实现方向,无双主题需求;实现已为浅色=与解决后权威一致 → SH-16 改判 MATCH。UNRESOLVED REFERENCE CONFLICT = 0(终局验收规则 §1.4 已达成)。

---

## 与旧豁免的对应(摘要;全表见 remediation plan §4)

- 旧 23 JD + C 类 23 项中:原 21 个 PRODUCT GAP 族在新口径下维持缺口定性并升级为 PRODUCT-FUNCTIONAL GAP(APPROVED ABSENCE 不再是合法终态);C-B1-09 拆分出 3 条 IMPLEMENTATION DEFECT;C-02 拆分出 1 条 IMPLEMENTATION DEFECT(系统分组);C-B2-07(问题描述叙事)经运行时复核升级为 MATCH;C-03(侧栏明暗)经 U-1 解决 → SH-16 MATCH。
- 旧 A 类 20 项:全部维持 MATCH(本轮运行时+代码双重复核)。
- 旧 B 类 6 组 fixture 族:全部有效且本轮重新核验(API=PG=UI 三角)。
- Planning 修订(2026-09-13):SH-10/11(帮助中心)经 U-3 由 PFG 转 UADC-4(获批缺席);全表 GAP 由 40 行/18 族修整为 38 行/17 族。
