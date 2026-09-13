# V1.6.3 Reference Gap Register(2026-09-13 Reference Traceability Audit)

分类铁律:只允许 MATCH / IMPLEMENTATION DEFECT / PRODUCT-FUNCTIONAL GAP / USER-APPROVED DESIGN CHANGE / REFERENCE CONFLICT。旧豁免词汇(JD/APPROVED ABSENCE/ADAPT/N-A 等)全部作废,不得再作为分类。缺后端能力不是省略参考特性的许可——一律记 PRODUCT-FUNCTIONAL GAP。

追溯矩阵:docs/engineering/tasks/v163-reference-traceability-audit.md §3 索引。总计 152 条原子需求:MATCH 104 / IMPLEMENTATION DEFECT 4 / PRODUCT-FUNCTIONAL GAP 40 / USER-APPROVED DESIGN CHANGE 3 / REFERENCE CONFLICT 1。

---

## A 类 — IMPLEMENTATION DEFECT(4;既有权威真相内可修,零新后端语义)

| ID | 矩阵行 | 面 | 前端范围 | 后端范围 | 数据模型范围 | 依赖 | 验收要求 |
|---|---|---|---|---|---|---|---|
| DEF-A1 | SH-06 | 共享 chrome | admin/src/components/Sidebar.tsx:新增「系统」分组,用户管理/系统信息移入 | 无 | 无 | #52 冻结导航清单需同步修订记录 | /admin 侧栏出现 系统 组;vitest 断言组标签与归属;截图对照 PNG2 |
| DEF-A2 | DS-P5-02 | B1-P5 | admin/src/components/dataSources/SourceEditorDrawer.tsx:「产品线」label 收敛为「名称*」(真值 product 不变) | 无 | 无 | 无 | vitest label 断言;编辑抽屉截图对照 PNG1 面板5 |
| DEF-A3 | DS-P5-04 | B1-P5 | SourceEditorDrawer.tsx:编辑态类型字段禁用(参考语义:创建后类型不可变) | 无(不动 PUT 语义) | 无 | **需 User 决定**:匹配参考(禁用,让渡编辑类型能力)或批准维持超集(转 USER-APPROVED DESIGN CHANGE) | 若禁用:编辑抽屉类型 disabled+vitest;若批准:记录 UADC 编号 |
| DEF-A4 | DS-P5-05 | B1-P5 | SourceEditorDrawer.tsx:启用 checkbox → 「自动同步」toggle+说明文案「开启后,系统将按设定周期自动同步。」(真值 enabled 不变) | 无 | 无 | 无 | toggle 切换→保存→PUT enabled 真实生效;vitest+截图 |

## B 类 — PRODUCT-FUNCTIONAL GAP(40 矩阵行,归并为 18 个 Gap 族;每族给出实现边界,不过度设计)

### 共享 chrome

| GAP ID | 矩阵行 | 面 | 前端范围 | 后端范围 | 数据模型范围 | 依赖 | 验收要求 |
|---|---|---|---|---|---|---|---|
| GAP-SC-1 全局时间范围 | SH-09 | PNG2 顶栏 | Layout 顶栏范围控件 | 全局窗口语义贯通各读面参数(或明确页内等价契约) | 无新表 | 需 User 决定 YES/NO | 选择范围→各读面窗口真实联动(API 参数可见) |
| GAP-SC-2 帮助中心 | SH-10/11 | 顶栏 ?+侧栏底部入口 | 入口控件 | 帮助目标真相(路由/外链) | 无 | 需 User 决定 YES/NO | 点击到达真实帮助目标 |
| GAP-SC-3 侧栏收起 | SH-12 | 侧栏 | 折叠/展开+布局联动 | 无 | 无 | 无(纯前端产品功能) | 真实点击折叠/展开截图;状态可选记忆 |

### B1 数据源运营

| GAP ID | 矩阵行 | 面 | 前端范围 | 后端范围 | 数据模型范围 | 依赖 | 验收要求 |
|---|---|---|---|---|---|---|---|
| GAP-B1-1 品牌资产 | DS-P2-02 | 详情身份块 | 渲染 logo | 品牌资产字段读/写(config 或端点) | data_sources.config.logo_url(或等价) | 需 User 决定 YES/NO | 真实源配置 logo 后详情渲染品牌图 |
| GAP-B1-2 banner 原因分类 | DS-P2-10 | 详情 banner | 文案呈现 | 原因分类扩展(引用一致性重验真相)——与 GAP-B2-1 同一分类学契约 | 会话/文档级原因真相 | 依赖 GAP-B2-1 | banner 原因行与后端分类一一对应;「1 项引用需要重新验证」类可出现 |
| GAP-B1-3 逐文档内容类型 | DS-P2-16/20 | 详情工作区 | 类型列+类型过滤 | 连接器逐文档 content_type 抽取;documents 过滤参数 | documents 类型列/推导规则 | 需 User 决定 YES/NO | NE101=商品/Getting Started=页面/Legacy Guide=文档;过滤真实生效 |
| GAP-B1-4 行级修复 | DS-P2-25/26、DS-P3-07 | 详情行+展开行 | 处理按钮+行 ⋯ | 修复命令端点(类目/幂等/验证/RBAC/审计) | 修复任务+审计持久化 | 冻结修复契约后实现;需 User 决定 YES/NO | 真实点击→POST→重处理→文档转在服→UI 反映;审计行可查 |
| GAP-B1-5 chunk 级服务分数 | DS-P3-05 | 展开行 | 10/12 分数呈现 | chunk 级 serving/总数投影(复用 verify_source_vectors 口径) | 无新表(投影) | 依赖 GAP-B1-4(修复后分数变化可证) | 分数=真实核验值;修复前后分数变化可断言 |
| GAP-B1-6 逐文档恢复计数 | DS-P3-06、DS-P4-10 | 展开行 | 恢复注记 | 逐文档自动恢复事件计数投影 | 恢复事件记录(sync_runs 细化) | 需 User 决定 YES/NO | 注记次数=真实恢复事件数 |
| GAP-B1-7 修复验证卡 | DS-P3-08/09 | 展开行 | 成功卡+一致性行 | 修复结果+一致性核验入修复流 | 同 GAP-B1-4 | 依赖 GAP-B1-4/5 | 修复完成→卡片呈现 vN、12/12、一致性验证 通过(真实值) |
| GAP-B1-8 调度真值 | DS-P4-03 | 同步活动 | 下次同步倒计时 | next_run_at 调度真值端点 | 调度状态(现 sync_interval 推导) | 需 User 决定 YES/NO | 倒计时=调度器权威;同步完成后刷新 |
| GAP-B1-9 知识设置域 | DS-P6-01..05(5 行) | 知识设置 Drawer | 抽屉全面 | 知识设置读/写端点;时态角色资格语义;新鲜度阈值+超期提醒 | 源级策略持久化(时态角色/新鲜度);资格判定贯通检索 | 需 User 冻结时态/新鲜度契约 | 打开→读→写→重开一致;HISTORICAL 后检索资格真实变化;超期提醒出现 |
| GAP-B1-10 高风险预览域 | DS-P7-01..06(6 行) | 预览 Modal | Modal 全面 | mutation-preview API(影响计数服务端权威计算);确认后重验任务 | 无新表(计算+任务) | 依赖 GAP-B1-9 | 保存高风险变更→Modal 弹出;202/199/199 型计数=服务端真实计算;确认→变更生效+重验执行 |

### B2 技术洞察

| GAP ID | 矩阵行 | 面 | 前端范围 | 后端范围 | 数据模型范围 | 依赖 | 验收要求 |
|---|---|---|---|---|---|---|---|
| GAP-B2-1 原因分类扩展 | TI-09(联动 GAP-B1-2) | 回答缺口 filter+chips | 新词选项/徽章 | classify_gap_miss_types 扩展:内容过期/检索异常/生成异常/引用异常/内容冲突/内容缺失(须有会话级证据规则) | 分类真相(推导或列) | 需 User 决定 YES/NO(分类学扩展授权) | 每个新词至少 1 行真实分类证据;旧 4 类回归不变 |
| GAP-B2-2 观察状态机 | TI-07/18/36/37/41/42/43(7 行) | 队列+侧板+CTA | 观察中徽章/过滤/开始观察 CTA/内容补充区块/历史时间线 | OBSERVING 状态契约:进入命令(开始观察+同步核验)/观察期/转移任务/流转事件持久化 | question_clusters.status 扩展+观察元数据+流转事件表 | 需 User 冻结观察语义契约(时长/转移条件/权限) | 真实点击开始观察→同步核验→行转观察中;期满核验→已解决;历史 Tab 出现流转记录 |
| GAP-B2-3 导出与隐私 | TI-34/35/45(3 行) | 推荐操作卡 | 导出卡+隐私说明+下载行为 | 导出端点(范围=归属会话;字段=问题/上下文/回答/引用;CSV;审计) | 无新表(流式导出+审计行) | 需 User 冻结导出+隐私契约(先行) | 点击→真实 CSV 下载;内容与归属会话一致;不含个人身份字段;审计可查 |
| GAP-B2-4 用户聚合 | TI-27 | 侧板头 | 涉及 N 个用户 | 会话→用户去重聚合投影 | conversations 用户标识真相(现缺) | 隐私评估先行;需 User 决定 YES/NO | N=去重权威计数,与 API/DB 三角一致 |
| GAP-B2-5 gap→源归因 | TI-33 | 概览 | 相关数据源卡+外链 | gap→source 关联投影(会话证据→服务源归因规则) | 归因投影(只读) | 归因规则需冻结;需 User 决定 YES/NO | 外链真实到达源详情;归因有证据规则依据 |
| GAP-B2-6 主题短语 | TI-12 | 队列主列 | 主题式标题呈现 | 主题生成契约(LLM 派生需单独授权;或规则派生) | clusters topic 字段 | 需 User 决定 YES/NO | 主题稳定、忠实簇内问句;无主题时回退代表问句 |

## C 类 — USER-APPROVED DESIGN CHANGE(3;User 已裁,记录不重开)

| ID | 矩阵行 | 内容 | 批准来源 |
|---|---|---|---|
| UADC-1 | SH-13 | KB-OPS 三面(/data-sources、/data-sources/:id、/analytics)抑制 LoginChat 浮动 FAB | User 裁 V-2 ACCEPTED(remediation 附录 B) |
| UADC-2 | DS-P1-23 | 列表行高 41px(参考 ~36px) | User 裁 V-1 ACCEPTED 不变 |
| UADC-3 | DS-P4-01 | 同步状态/活动为页内 section(参考为浮层卡+X) | User 裁 V-3 ACCEPTED 不变 |

## D 类 — REFERENCE CONFLICT(1;两权威参考真矛盾,待 User 裁)

| ID | 矩阵行 | 冲突 | 现状 | 裁决选项 |
|---|---|---|---|---|
| CONFLICT-1 | SH-16 | 侧栏底色:PNG1 深色(近黑)vs PNG2 浅色(白) | 实现维持 PNG2 浅色 | a) 维持浅色;b) 深色侧栏;c) 双主题。审计已用 Read 直接复核两原始 PNG 确认真冲突(非实现差异可解释) |

---

## 与旧豁免的对应(摘要;全表见 remediation plan §4)

- 旧 23 JD + C 类 23 项中:21 个 PRODUCT GAP 族在新口径下**维持缺口定性并升级为 PRODUCT-FUNCTIONAL GAP**(APPROVED ABSENCE 不再是合法终态);C-B1-09 拆分出 3 条 IMPLEMENTATION DEFECT;C-02 拆分出 1 条 IMPLEMENTATION DEFECT(系统分组);C-B2-07(问题描述叙事)经运行时复核**升级为 MATCH**;C-03(侧栏明暗)确认为 REFERENCE CONFLICT 维持待裁。
- 旧 A 类 20 项:全部维持 MATCH(本轮运行时+代码双重复核)。
- 旧 B 类 6 组 fixture 族:全部有效且本轮重新核验(API=PG=UI 三角)。
