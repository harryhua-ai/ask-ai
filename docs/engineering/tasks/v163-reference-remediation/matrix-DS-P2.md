# V1.6.3 Reference Traceability Matrix — DS-P2 数据源详情(PNG1 面板2)

| ID | 区域 | 要求 | 期望呈现 | 期望行为 | 期望产品语义 | 前端:文件 | 运行时状态 | 当前行为 | 后端 API 依赖 | 持久化依赖 | 现有支持 | 权威数据真值 | 分类 | 证据/所需实现/验收/需User决定 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| DS-P2-01 | 面包屑 | 配置›数据源›WooCommerce 三级 | ›分隔 | 点击「数据源」返回列表 | 位置+返回 | DataSourceDetail.tsx nav | 已实现 | 三级+可点返回 | 无 | 无 | 有 | 无 | MATCH | RT/02 |
| DS-P2-02 | 身份 | 源品牌图(Woo 紫色 W 方标) | 品牌图片块 | (可外链) | 品牌识别 | 字母块 product[0] | 缺席(字母块) | 蓝底字母「W」 | 无品牌资产端点/字段 | 无 logo 字段 | 无 | 无 | PRODUCT-FUNCTIONAL GAP | 所需实现:数据源品牌资产(config.logo_url 或资产端点)+前端渲染;验收:真实源渲染品牌图;需 User 决定 YES/NO(授权品牌资产字段;旧 C-B1-01) |
| DS-P2-03 | 身份 | 源名 + 需处理 徽章 | h1+状态徽章 | — | 操作者状态 | operatorStateOf+Badge | 已实现 | WooCommerce+需处理 | 同 P1 权威面 | — | 有 | — | MATCH | RT/02 |
| DS-P2-04 | 身份 | 类型 | URL 元信息(商城 | https://woocomerce.com) | 外链可点 | sourceLocation | 已实现 | 商城 | 链接(外链新窗) | — | 有 | — | MATCH | RT/02 |
| DS-P2-05 | 元信息 | 「最后同步 2 小时前 · 部分成功」 | 相对时间+结果词 | — | 新鲜度+结果 | last_sync+last_sync_status | 已实现 | 12小时前 · 部分成功 | GET /data-sources | sync_log | 有 | last_sync 权威 | MATCH | RT/02;API 核验 |
| DS-P2-06 | 元信息 | 部分成功 为可点链接/下拉 → 同步证据 | 蓝链接+chevron | 点击展开/滚动至同步活动证据 | 结果→证据路径 | partial-result-link scrollIntoView #sync-activity | 已实现 | 滚动至页内同步活动区(结构=页内 section,V-3 已裁) | — | — | 有 | — | MATCH | 旧 F4 真实点击 PASS;V-3 结构 ACCEPTED |
| DS-P2-07 | 元信息 | 「202 条知识 · 3 项需处理」 | 计数行 | — | 内容规模+待处置 | ledger_total+attentionCount | 已实现 | 8 条知识 3 项需处理 | /documents 聚合+attention | documents | 有 | 账本权威 | MATCH | RT/02 |
| DS-P2-08 | 页头动作 | 页头「⋯」菜单 | 单 ⋯ | 编辑/返回列表 | 动作收纳 | DropdownMenu | 已实现 | ⋯ 菜单 | — | — | 有 | — | MATCH | 旧 A-P2-05 闭环;RT/02 |
| DS-P2-09 | banner | 「有 3 项知识需要处理」标题 | 红系横幅+⚠图标 | — | 待处置总量警示 | banner 区 | 已实现 | 有 3 项知识需要处理 | attention 聚合 | documents lifecycle | 有 | lifecycle 计数 | MATCH | RT/02;API=PG 核验(2 missing+1 无现行) |
| DS-P2-10 | banner | 原因句「2 项内容未同步进入当前服务、1 项引用需要重新验证」 | 逐原因行 | — | 原因分类真相(内容未同步/引用需重验) | attentionReasonClasses | 部分实现 | 权威桶事实转述(2 项源内容缺失处于缺席宽限期/1 项现行版本缺失无法证明在服);「引用需重新验证」类不存在 | 需原因分类(含引用重验)权威 | 无引用重验真相 | 部分(lifecycle 原因类) | lifecycle 原因 | PRODUCT-FUNCTIONAL GAP | 所需实现:原因分类扩展(引用一致性重验真相)+banner 文案契约;验收:原因行与后端分类一一对应;需 User 决定 YES/NO(旧 C-B1-02) |
| DS-P2-11 | banner | 「查看需处理」按钮 → 过滤到需处理桶 | outline 按钮 | 设置 bucket=attention 过滤工作区 | 异常定位 | setBucket("attention") | 已实现 | 真实过滤 | /documents?bucket | — | 有 | — | MATCH | 旧 10-P2-attention-filter 证据 |
| DS-P2-12 | banner | 关闭 X | ghost ✕ | 本地关闭 | 免打扰 | bannerDismissed | 已实现 | 本地状态关闭 | 无 | 无 | 有 | — | MATCH | RT/02 |
| DS-P2-13 | 工作区 | 「知识内容」区块标题 | h2 | — | 内容账本工作区 | CardTitle | 已实现 | 一致 | — | — | 有 | — | MATCH | RT/02 |
| DS-P2-14 | 工作区 | 搜索框「搜索知识内容...」 | 输入框 | 防抖搜索过滤 | 查找 | Input+300ms 防抖 | 已实现 | 服务端 search 参数 | GET /:id/documents?search | documents | 有 | — | MATCH | RT/02 |
| DS-P2-15 | 工作区 | 状态过滤 select | select | bucket 过滤 | 状态定位 | BUCKET_OPTIONS | 已实现 | 全部/当前在服/需要关注/已退役 | /documents?bucket | — | 有 | — | MATCH | RT/02 |
| DS-P2-16 | 工作区 | 类型过滤(逐文档:商品/页面/文档) | select | 按文档内容类型过滤 | 内容类型真相 | 无逐文档类型 | 缺席 | 类型过滤为源级;逐文档类型不存在 | 需逐文档 content_type 抽取 | documents 需类型列/推导 | 无 | source_type 仅源级 | PRODUCT-FUNCTIONAL GAP | 所需实现:连接器逐文档内容类型抽取+持久化+过滤;验收:NE101=商品/Getting Started=页面;需 User 决定 YES/NO(旧 C-B1-03) |
| DS-P2-17 | 工作区 | 「共 202 条」计数 | 文本 | — | 规模 | docs.total | 已实现 | 共 8 条(账本 8) | /documents total | documents | 有 | — | MATCH | RT/02 |
| DS-P2-18 | 工作区 | 「更新时间」排序 | select | 排序提交 | 新鲜度排序 | SORT_OPTIONS order | 已实现 | 更新时间/名称 | /documents order | — | 有 | — | MATCH | RT/02 |
| DS-P2-19 | 表 | 列:名称(展开触发:chevron+名称) | ⌄/›+名称 | 点击展开行诊断 | 诊断入口 | doc-row-toggle | 已实现 | chevron+名称展开 | — | — | 有 | — | MATCH | 旧 A-P3-01 闭环;RT/03 |
| DS-P2-20 | 表 | 列:类型(逐文档:商品/页面/文档) | 文档级类型词 | — | 内容类型 | sourceTypeLabel(源级) | 缺席(源级「商城」) | 全部显示源级类型 | 同 DS-P2-16 | 同上 | 无 | — | PRODUCT-FUNCTIONAL GAP | 同 DS-P2-16(独立呈现位);需 User 决定 |
| DS-P2-21 | 表 | 列:状态(正常/需处理/待分类) | 徽章 | — | 文档健康 | knowledgeStatusOf | 已实现 | 正常/需处理/待分类(+已退役超集) | lifecycle+serving | documents | 有 | lifecycle 权威 | MATCH | RT/02 |
| DS-P2-22 | 表 | 列:当前版本 vN | v+序数 | hover 精确 | 版本链 | current_version_seq | 已实现 | v1(本地数据 v1;参考形状 v17/v5 为板面示意) | documents 版本链 | document_versions | 有 | 版本链权威 | MATCH | RT/02;API 核验 |
| DS-P2-23 | 表 | 列:服务(正常/不完整/—) | 色词映射 | — | 在服状态 | serving 映射 | 已实现 | 正常(绿)/不完整(蓝)/—(灰) | serving 真相 | 向量+账本 | 有 | serving 权威 | MATCH | 旧 A-P2-02 闭环;RT/02(Orphan Page —) |
| DS-P2-24 | 表 | 列:更新时间 | 相对时间 | hover 精确 | — | RelativeTime | 已实现 | 单格式+title | — | — | 有 | — | MATCH | 旧 A-P2-03 闭环 |
| DS-P2-25 | 表 | 行操作「处理」按钮(需处理行) | 蓝 outline 按钮 | 点击进入该文档异常处理流 | 行级修复入口 | 无 | 缺席 | 无行级动作(仅真相只读) | 需行级修复命令端点 | 需修复任务/审计持久化 | 无 | 无 | PRODUCT-FUNCTIONAL GAP | 所需实现:行级修复契约(类目/幂等/验证/RBAC/审计)+处理按钮;验收:真实点击→真实修复→状态迁移;需 User 决定 YES/NO(旧 C-B1-05) |
| DS-P2-26 | 表 | 行操作「⋯」菜单(每行) | ⋯ | 行级动作收纳 | 行级动作集 | 无(现为「真相」按钮) | 缺席(替代呈现) | 真相按钮承担展开 | 同 DS-P2-25 | 同上 | 无 | — | PRODUCT-FUNCTIONAL GAP | 依赖行级修复契约;与 DS-P2-25 同一 User 决定 |
| DS-P2-27 | 分页 | 分页控件 | 上一页/第N页/下一页 | 真实翻页 | 规模扩展 | Pagination | 已实现 | 真实分页(size=20) | /documents page | — | 有 | — | MATCH | RT/02 |
