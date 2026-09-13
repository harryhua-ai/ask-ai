# V1.6.3 Reference Traceability Matrix — TI-* 技术洞察·回答缺口(PNG2 全部原子)

**PLANNING 修订(2026-09-13,Role A 裁决冻结)**:新增「冻结决定」列(U-x=remediation plan §5 编号,已冻结;N/A=无需产品裁决)。分类不变:MATCH 32 / PRODUCT-FUNCTIONAL GAP 13。GAP 行方向全部获授权但**保持 GAP 直到实现+运行时验收完成**。

| ID | 区域 | 要求 | 期望呈现 | 期望行为 | 期望产品语义 | 前端:文件 | 运行时状态 | 当前行为 | 后端 API 依赖 | 持久化依赖 | 现有支持 | 权威数据真值 | 分类 | 证据/所需实现/验收/需User决定 | 冻结决定 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| TI-01 | 页头 | 「技术洞察」标题(深蓝)+副标题「从真实用户对话中发现回答问题…」 | h1+副标题 | — | 页面使命 | Analytics.tsx h1 | 已实现 | 深蓝 rgb(4,3,108)+逐字副标题 | 无 | 无 | 有 | 无 | MATCH | RT/06;旧 A-B2-01 闭环 | N/A |
| TI-02 | Tabs | 「技术性能 / 回答缺口」双 Tab | Tab 条 | 切换 | 双工作面 | ShellTab | 已实现 | 切换正常 | — | — | 有 | — | MATCH | RT/06 | N/A |
| TI-03 | Tabs | 回答缺口 选中态(下划线) | 下划线+加重 | — | 位置 | ShellTab active | 已实现 | 一致 | — | — | 有 | — | MATCH | RT/06 | N/A |
| TI-04 | 工具栏 | 搜索框(问题/主题、产品名称或关键词(如:NE101、价格、安装)) | 输入框+placeholder | 输入过滤 | 查找 | data-gap-search | 已实现 | placeholder 逐字;q 过滤 | q 参数(代表问题+样例) | question_clusters | 有 | — | MATCH | RT/06 | N/A |
| TI-05 | 工具栏 | 搜索真实生效 | 行集变化 | — | — | query q | 已实现 | ilike 命中 | /tech/answer-gaps?q | — | 有 | — | MATCH | API 核验 | N/A |
| TI-06 | 工具栏 | 「全部状态」filter | select | 状态过滤 | 定位 | data-filter-status | 已实现 | 全部/需要处理/已解决 | status 参数 | — | 有 | — | MATCH | RT/06 | N/A |
| TI-07 | 工具栏 | 状态词表含「观察中」 | 第三选项 | 观察中过滤 | 观察态定位 | 无观察中选项 | 缺席 | 词表仅 open/resolved | 需 OBSERVING 状态 | question_clusters.status 扩展 | 无(DB DISTINCT= open\|resolved) | — | PRODUCT-FUNCTIONAL GAP | 依赖观察状态机(TI-42);冻结语义见 U-15;仓库证据:可行(question_clusters.status 可扩展+sync_runs/verify_source_vectors 可作核验钩子) | **U-15 已冻结:实现 OPEN→OBSERVING→RESOLVED 状态机(进入条件/7 天观察窗/复现回 OPEN/满窗转 RESOLVED/可中止;全部转移持久化+可审计+History 可见)** |
| TI-08 | 工具栏 | 「全部原因」filter 控件 | select | 原因过滤 | 定位 | data-filter-cause | 已实现 | 控件在 | cause 参数 | — | 有 | — | MATCH | RT/06 | N/A |
| TI-09 | 工具栏 | 原因词表:知识缺失/服务知识不完整/内容过期/检索异常/生成异常/引用异常/内容冲突/内容缺失 | 全词表选项 | — | 原因分类学 | GAP_CAUSE_OPTIONS(权威 4 类+未分类) | 部分 | 仅 知识缺失/服务知识不完整/拒答/低相关/未分类;内容过期/检索异常/生成异常/引用异常/内容冲突/内容缺失 无权威分类 | 需分类器扩展(内容过期/引用/生成/检索/冲突/缺失 类) | 会话分类真相 | 部分(classify_gap_miss_types 4 类) | coverage-gaps 同源分类 | PRODUCT-FUNCTIONAL GAP | 所需实现:后端原因分类扩展契约;冻结语义:**实现参考要求的扩展词表;每类需证据规则;禁止 keyword-only 前端分类**;验收:每个新词至少 1 行真实分类证据;旧 4 类回归不变;旧 C-B2-01 | **U-14 已冻结:实现参考要求的扩展词表;每类需证据规则;禁 keyword-only 前端分类** |
| TI-10 | 工具栏 | 「过去 7 天」时间窗 filter | select | 窗口过滤 | 时窗 | data-filter-window 7d/30d/all | 已实现 | 一致 | window 参数 | — | 有 | — | MATCH | RT/06 | N/A(U-2 顶栏范围与本页窗语义衔接归 Track A/E2E) |
| TI-11 | 队列 | 复选框列 | checkbox | 勾选/取消,行高亮 | 批选 | data-gap-check | 已实现 | 勾选状态+已选择计数联动 | — | — | 有 | — | MATCH | RT/07 | N/A |
| TI-12 | 队列 | 列「问题 / 主题」主题式标题(NE101 PoE 支持信息缺失) | 主题短语 | 点击选行 | 主题级命名 | representative_question | 偏差 | 显示簇代表问句(NE101 是否支持 PoE) | 需主题/标题字段 | clusters 需 topic 字段 | 无 | — | PRODUCT-FUNCTIONAL GAP | 所需实现:主题生成契约;冻结语义:**优先确定性派生;仅当确定性质量明显不足且另行授权才用 LLM;必须稳定且忠实于 cluster 内容**;验收:主题稳定(同簇多次拉取不变)、忠实簇内问句;无主题回退代表问句;旧 C-B2-08 | **U-19 已冻结:实现;确定性派生优先;LLM 仅另行授权;稳定且忠实 cluster 内容** |
| TI-13 | 队列 | 副行样例问句 | 灰色副行 | — | 证据透出 | sample_questions[0] | 已实现 | 一致 | — | — | 有 | — | MATCH | RT/06 | N/A |
| TI-14 | 队列 | 列「相关提问」+排序 | 数字+↕ | 点击排序 | 规模 | question_count | 已实现 | 排序真实(questions) | order=questions | — | 有 | — | MATCH | RT/06;API | N/A |
| TI-15 | 队列 | 列「影响回答」+排序 | 数字+↕ | 点击排序 | 影响面 | impacted_answer_count | 已实现 | 排序真实(impacted) | conversations 计数 | conversations.cluster_id | 有 | 会话归属权威 | MATCH | API=PG(23/18) | N/A |
| TI-16 | 队列 | 列「原因」彩色 chips | tinted 徽章 | — | 原因可读 | CauseBadge(data-gap-type 机器值恒存) | 已实现 | 忠实映射+机器值属性 | — | — | 有 | — | MATCH | RT/06;旧 A-B2 系列 | N/A |
| TI-17 | 队列 | 列「状态」圈形图标徽章(需要处理 ⓘ/已解决 ✓) | 徽章 | — | 状态可读 | StatusBadge svg | 已实现 | 圈形图标 | — | — | 有 | — | MATCH | 旧 A-B2-02 闭环;RT/06 | N/A |
| TI-18 | 队列 | 「观察中」状态(蓝点徽章) | 徽章 | — | 观察生命周期 | 无 | 缺席 | 无(DB 词表仅 open/resolved) | 需 OBSERVING 状态机 | question_clusters.status 扩展+观察元数据 | 无 | — | PRODUCT-FUNCTIONAL GAP | 冻结语义见 U-15(观察窗 7 天;转移持久化/可审计/History 可见);验收:真实进入观察中的行呈蓝标 | **U-15 已冻结(同 TI-07)** |
| TI-19 | 队列 | 列「最近发生」+排序 | 相对时间+↕ | 排序;无证据显示诚实态 | 时近性 | last_seen_at | 已实现 | 排序真实;证据不可用 态诚实 | MAX(conversations.created_at) | — | 有 | — | MATCH | RT/06(5 小时前/证据不可用 并存) | N/A |
| TI-20 | 队列 | 行点击选中→诊断侧板 | 行高亮+左条 | 打开侧板 | 诊断入口 | selectRow | 已实现 | 真实打开 | — | — | 有 | — | MATCH | RT/07 | N/A |
| TI-21 | 队列页脚 | 「已选择 1 项」 | 计数 | 联动勾选 | 批选反馈 | data-selection-count | 已实现 | 一致 | — | — | 有 | — | MATCH | RT/06,07 | N/A |
| TI-22 | 队列页脚 | 页码「‹ 1 2 ›」+当前高亮 | 页码按钮组 | 真实翻页 | 规模 | data-gap-page-* | 已实现 | 12 条→2 页真实翻页 | page 参数 | — | 有 | — | MATCH | 旧 F8 PASS;旧 A-B2-03 闭环 | N/A |
| TI-23 | 队列页脚 | 「10 条/页」 | select | 改页大小 | 密度 | data-gap-page-size | 已实现 | 10/20/50 | size 参数 | — | 有 | — | MATCH | RT/06 | N/A |
| TI-24 | 侧板头 | 标题+「需要处理」徽章+X | 标题行 | 关闭侧板 | 诊断上下文 | GapPanel 头 | 已实现 | 一致 | — | — | 有 | — | MATCH | RT/07 | N/A |
| TI-25 | 侧板头 | 「23 次相关提问」 | meta 行 | — | 规模 | question_count | 已实现 | 一致 | — | — | 有 | — | MATCH | RT/07 | N/A |
| TI-26 | 侧板头 | 「18 次受影响回答」 | meta 行 | — | 影响面 | impacted_answer_count | 已实现 | 一致 | conversations 计数 | — | 有 | — | MATCH | API=PG=18 | N/A |
| TI-27 | 侧板头 | 「涉及 17 个用户」 | meta 行 | — | 受影响用户面 | 无 | 缺席 | 无(会话模型无用户实体聚合) | 需会话→用户去重聚合投影 | conversations 需用户标识真相 | 无 | — | PRODUCT-FUNCTIONAL GAP | 所需实现:用户聚合投影;冻结语义:**不引入真人身份追踪;定义=所选分析窗内去重的伪匿名会话/会话行为者;要求稳定匿名 actor/session 身份、不需要姓名/邮箱/IP、隐私保持聚合;历史数据不可回填则诚实显示 unavailable(不得编造计数);未来数据必须支持权威聚合**;仓库证据:可行——`conversations.session_id`(String(64),widget 匿名会话 ID,sales_leads.thread 依赖)已存在;历史 NULL session_id 行诚实 unavailable;旧 C-B2-05 | **U-17 已冻结:实现;去重伪匿名会话计数;禁真人身份追踪/姓名/邮箱/IP;历史不可回填则诚实 unavailable** |
| TI-28 | 侧板头 | 「最近发生: 2 小时前」 | meta 行 | — | 时近性 | last_seen_at | 已实现 | 一致 | — | — | 有 | — | MATCH | RT/07 | N/A |
| TI-29 | 侧板 | 五 Tab:概览/典型问题(6)/相关对话/诊断详情/历史记录 | Tab 条 | 切换 | 诊断分区 | PANEL_TABS | 已实现 | 五 Tab 齐全;典型问题带计数 | — | — | 有 | — | MATCH | RT/07 | N/A |
| TI-30 | 概览 | 「问题描述」段落(诊断式说明) | 段落 | — | 问题定性叙述 | data-panel-description | 已实现 | 权威字段事实汇总(围绕…多次提问,共 N 提问/M 受影响) | — | — | 有 | — | MATCH | RT/07;语义覆盖达成(事实 voice 记录在案,综合因果归 TI-31 诊断结论承担) | N/A |
| TI-31 | 概览 | 「诊断结论」红盒+原因 chip+因果解释 | 红系盒 | — | 根因定性 | data-panel-conclusion+gapCauseConclusion | 已实现 | 权威分类+忠实因果转述;无分类→证据不可用 | miss_type 分类 | — | 有 | — | MATCH | RT/07 | N/A |
| TI-32 | 概览 | 「典型问题示例」bullets+「查看全部 (6)」 | 5 条 bullets+链接 | 点击切到典型问题 Tab | 证据透出 | data-panel-typical | 已实现 | 一致 | — | — | 有 | — | MATCH | RT/07 | N/A |
| TI-33 | 概览 | 「相关数据源」:We WooCommerce / NE101+外链 | 源卡+外链 icon | 点击深链数据源 | 缺口→数据源归因 | 无 | 缺席 | 无(gap→source 权威关联不存在) | 需 gap→source 关联投影(会话证据→源) | 会话-源关联真相 | 无 | — | PRODUCT-FUNCTIONAL GAP | 所需实现:归因投影;冻结语义:**关联必须源自证据/对话/检索真值;禁止前端猜**;验收:外链真实到达源详情;归因有证据规则依据;旧 C-B2-06 | **U-18 已冻结:实现;归因源自证据/对话/检索真值;禁前端猜** |
| TI-34 | 概览 | 「推荐操作」卡:导出相关对话(导出问题主题对应的原始对话记录(CSV)) | 操作卡 | 点击真实导出 CSV | 证据导出动作 | 无(现为 查看相关对话 深链卡) | 缺席 | 深链替代(授权范围内呈现) | 需导出服务端点 | 会话数据 | 无导出端点 | — | PRODUCT-FUNCTIONAL GAP | 冻结语义:**admin-only 导出;最小必要字段;排除直接个人身份;导出动作可审计;CSV 必须与所选 gap/query 范围精确对应**;验收:点击→真实 CSV 下载且内容=所选范围权威数据;旧 C-B2-03 | **U-16 已冻结:实现 admin-only 导出;最小字段;排除直接个人身份;可审计;CSV=所选范围** |
| TI-35 | 概览 | 导出隐私说明(包含用户问题/上下文/当前回答及引用信息,不包含用户个人身份信息) | info 说明条 | — | 隐私边界承诺 | 无 | 缺席 | 无 | 与导出契约同源(内容范围=隐私规则) | — | 无 | — | PRODUCT-FUNCTIONAL GAP | 依赖 TI-34;隐私规则=U-16 冻结语义(最小必要字段+排除直接个人身份) | **U-16 已冻结(同 TI-34)** |
| TI-36 | 概览 | 「内容补充完成后」区块(请确认内容已加入权威数据源并完成数据同步…) | 说明区块 | — | 补充→同步→核验工作流说明 | 无 | 缺席 | 无 | 依赖观察工作流(TI-37) | — | 无 | — | PRODUCT-FUNCTIONAL GAP | 同 TI-37 契约(U-15) | **U-15 已冻结(同 TI-07)** |
| TI-37 | 概览 | 「▷ 内容已补充,开始观察」主 CTA(系统将验证数据同步状态,通过后进入观察中) | 蓝主按钮+副文案 | 点击→同步核验→进入观察中 | 修复闭环入口 | 无 | 缺席 | 无(零 mutation 语义) | 需观察命令+同步核验+状态迁移 | 观察状态持久化 | 无 | — | PRODUCT-FUNCTIONAL GAP | 冻结语义:进入 OBSERVING 需 操作者确认内容修复完成+相关源 sync/reindex 成功+post-sync 验证成功;仓库证据:可行(sync_runs status/finished_at/consistency+verify_source_vectors 钩子);验收:真实点击→核验→队列行转观察中 | **U-15 已冻结:进入 OBSERVING 需操作者确认+sync/reindex 成功+post-sync 验证成功** |
| TI-38 | 典型问题 Tab | 「典型问题 (6)」全量清单 | bullets 全列 | — | 证据全集 | typical 全列 | 已实现 | 一致 | sample_questions | — | 有 | — | MATCH | 旧 16 截图;RT | N/A |
| TI-39 | 相关对话 Tab | 归属对话清单(问题+已回答/未回答徽章+时间)+「在对话审查中查看→」深链 | 对话行列表 | 点击深链 /conversations?q= | 会话证据下钻 | data-panel-conv-row | 已实现 | 真实列表+深链预填命中 | /tech/answer-gaps/:id/conversations | conversations | 有 | 会话权威 | MATCH | 旧 F10 PASS;API 核验 | N/A |
| TI-40 | 诊断详情 Tab | 原因分类分布(权威)+聚类创建时间+统计周期 | 分布列表+元数据 | — | 分类证据明细 | miss_type_breakdown | 已实现 | 权威分布呈现 | breakdown | — | 有 | — | MATCH | 旧 18 截图 | N/A |
| TI-41 | 历史记录 Tab | 历史记录 Tab(观察/流转史) | Tab+时间线 | 查看生命周期史 | 生命周期审计 | Tab 在,内容=证据不可用 诚实态 | 部分 | Tab 存在;内容诚实缺席(无观察/流转数据) | 依赖观察生命周期(TI-37/42) | 需流转事件持久化 | 无 | — | MATCH(Tab 本体)/GAP 归属 TI-37 | Tab 呈现已达;历史内容随观察契约交付(不重复计 GAP);冻结语义:全部转移 History 可见 | **U-15 已冻结(流转史随 GAP-B2-2 交付)** |
| TI-42 | 生命周期 | 「观察中」状态呈现(队列+侧板+过滤) | 蓝态 | — | 修复后观察期 | 无 | 缺席 | 无 | 同 TI-18 | 同 | 无 | — | PRODUCT-FUNCTIONAL GAP | 与 TI-18/07 同一契约(不重复计数) | **U-15 已冻结(同 TI-07)** |
| TI-43 | 生命周期 | 观察后转移(观察期满核验→已解决) | 状态迁移 | 自动/规则转移 | 闭环 | 无 | 缺席 | 无 | 观察状态机转移任务 | 同 | 无 | — | PRODUCT-FUNCTIONAL GAP | 冻结语义:满 7 天观察窗无复现→转 RESOLVED;OBSERVING 期间同一 gap/证据失败复现→回 OPEN;操作者可中止 OBSERVING→OPEN;**不得直接强转 RESOLVED**;转移持久化/带时间戳/可审计/History 可见 | **U-15 已冻结:满窗无复现→RESOLVED;复现/中止→OPEN;禁直接强转 RESOLVED;转移全部持久化可审计** |
| TI-44 | 生命周期 | 「已解决」态(队列徽章+过滤) | 绿态 | — | 终态 | resolved | 已实现 | 已解决 徽章+过滤 | status=resolved | — | 有 | — | MATCH | RT/06 | N/A |
| TI-45 | 行为 | 导出执行(真实 CSV 文件生成下载) | 下载行为 | 内容=归属会话原始记录 | 数据可携带 | 无 | 缺席 | 无 | 同 TI-34 | — | 无 | — | PRODUCT-FUNCTIONAL GAP | 与 TI-34 同一契约(行为位独立记录);CSV 由权威范围数据构建 | **U-16 已冻结(同 TI-34)** |
