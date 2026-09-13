# V1.6.3 Reference Traceability Matrix — SH-* 共享 chrome(两参考交叉)

矩阵列规范见主文档 §2。证据缩写:RT=runtime-checks 截图( acceptance/v163-traceability-audit-20260913/runtime-checks/ ),API=已验证 HTTP 读面,DB=已验证 psql 只读查询(运行时核验记录见主文档 §5)。分类只允许 MATCH / IMPLEMENTATION DEFECT / PRODUCT-FUNCTIONAL GAP / USER-APPROVED DESIGN CHANGE / REFERENCE CONFLICT。

| ID | 区域 | 要求 | 期望呈现 | 期望行为 | 期望产品语义 | 前端:文件 | 运行时状态 | 当前行为 | 后端 API 依赖 | 持久化依赖 | 现有支持 | 权威数据真值 | 分类 | 证据/所需实现/验收/需User决定 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SH-01 | 品牌 | 侧栏顶部品牌区(grid 图标 + ASK-AI 字标,PNG1;PNG2 为蓝色点阵 logo) | 深色/浅色侧栏头部 logo+字标 | 点击回首页(惯例) | 运营台身份识别 | Sidebar.tsx(品牌块) | 已实现 | 图标+ASK-AI,与 PNG1 同构 | 无 | 无 | 有 | 无(静态) | MATCH | RT/01,07;两参考品牌标形状互异(PNG1 方格/PNG2 蓝点阵),实现取 PNG1 语法,记录不另立冲突 |
| SH-02 | 侧栏层级 | 分组标签「运营」 | 组标签+其下导航项 | 静态层级 | 导航信息架构 | Sidebar.tsx OPS_ITEMS | 已实现 | 运营 组标签呈现 | 无 | 无 | 有 | 无 | MATCH | RT/01 |
| SH-03 | 侧栏层级 | 分组标签「配置」 | 组标签+其下导航项 | 静态层级 | 导航信息架构 | Sidebar.tsx CONFIG_ITEMS | 已实现 | 配置 组标签呈现 | 无 | 无 | 有 | 无 | MATCH | RT/01 |
| SH-04 | 侧栏层级 | 导航项全集与路由一一对应(业务概览/销售线索/对话审查/技术洞察/数据源/对话接入/模型配置/答案覆盖/Widget) | 每项 icon+label | 点击路由跳转 | 单一导航真相 | Sidebar.tsx + App.tsx 路由 | 已实现 | 9 项齐全可跳转 | 无 | 无 | 有 | 无 | MATCH | RT/01,06;PNG2 配置组未画「数据源」而 PNG1 画且 PNG2 侧板深链数据源详情=参考内部不一致,实现按 PNG1 含数据源,记录不豁免 |
| SH-05 | 选中态 | 当前路由项强选中(蓝) | 蓝色实底选中态(PNG1 语法) | 随路由联动 | 位置指示 | Sidebar.tsx NavLink isActive | 已实现 | 蓝实底白字,随路由联动 | 无 | 无 | 有 | 无 | MATCH | RT/01(数据源),RT/06(技术洞察) |
| SH-06 | 侧栏层级 | PNG2「系统」分组(用户管理/系统设置) | 独立 系统 组标签+2 项 | 点击路由 | 导航信息架构三分组 | Sidebar.tsx(现为 CONFIG_ITEMS 内) | 缺席 | 用户管理/系统信息 混在 配置 组,无 系统 组 | 无(路由 /users /system 已存在) | 无 | 路由已存在,纯前端重组 | 无 | IMPLEMENTATION DEFECT | 所需实现:Sidebar 分组重构(用户管理/系统信息 移入 系统 组);验收:vitest 断言组标签+归属;RT/01 现状证据 |
| SH-07 | 顶栏身份 | 顶栏右侧身份区(头像+名+角色+chevron) | 头像圆+显示名+角色+chevron | 点击开身份菜单 | 账号身份识别 | Layout.tsx DropdownMenu | 已实现 | avatar+admin@camthink.ai+admin+chevron | /auth 真相 | users 表 | 有 | user.name/email/role | MATCH | RT/01 |
| SH-08 | 顶栏身份 | 身份菜单(打开含账号信息+登出) | 菜单浮层 | 登出真实执行(清 token→登录页) | 会话终止 | Layout.tsx | 已实现 | 菜单含 退出,登出走既有 auth | /auth/logout | — | 有 | — | MATCH | 既有测试;旧验收 03/04 截图 |
| SH-09 | 顶栏 | 全局日期范围选择器(过去 7 天 2025-09-03→2025-09-09+日历,PNG2 顶栏) | 范围控件+起止日期 | 选择改变全局时间窗 | 全局运营时间窗真相 | 无(Layout.tsx 顶栏仅身份区) | 缺席 | 顶栏无日期范围控件;各页内局部 filter(技术洞察 7d/30d/all;分析页 TimeFilter) | 需全局窗口语义贯通各读面 | 无新表 | 无全局时间范围产品真相 | 各读面各自 window 参数 | PRODUCT-FUNCTIONAL GAP | 所需实现:全局时间范围语义契约+贯通参数+顶栏控件;需 User 决定 YES/NO(授权全局窗口 vs 接受页内局部 filter) |
| SH-10 | 顶栏 | 帮助中心 icon(?,PNG2 顶栏) | 圆形 ? 图标 | 点击进入帮助中心 | 帮助入口 | 无 | 缺席 | 无 | 帮助内容真相(路由/外链/内嵌)均无 | 无 | 无 | 无 | PRODUCT-FUNCTIONAL GAP | 需 User 决定 YES/NO(授权帮助中心目标语义) |
| SH-11 | 侧栏底部 | 帮助中心 入口(底部,带 ? 图标) | 底部导航项 | 点击进入帮助中心 | 帮助入口 | 无 | 缺席 | 无 | 同 SH-10 | 无 | 无 | 无 | PRODUCT-FUNCTIONAL GAP | 与 SH-10 同一产品决定 |
| SH-12 | 侧栏底部 | 收起菜单 折叠控件 | 底部折叠按钮+chevron | 点击折叠侧栏(可展开) | 工作区扩展 | 无 | 缺席 | 侧栏恒宽 240px 不可折叠 | 无 | 无(纯前端) | 无 | 无 | PRODUCT-FUNCTIONAL GAP | 所需实现:折叠态+展开态+记忆(可选);验收:真实点击折叠/展开截图 |
| SH-13 | 浮动控件 | KB-OPS 三面(/data-sources、/data-sources/:id、/analytics)不出现 LoginChat 浮动 FAB | 无 FAB | — | 参考无该元素 | LoginChat.tsx 路径抑制 | 已实现 | 三面 FAB 不挂载 | 无 | 无 | 有 | 无 | USER-APPROVED DESIGN CHANGE | User 已裁 V-2 ACCEPTED;证据:FINAL-AFTER/08,09,10 + LoginChatFabSuppression.test |
| SH-14 | 色彩 token | 主操作蓝(primary blue)按钮/选中/链接同一 token | 参考主蓝 | — | 单一主色语法 | tailwind primary/badge.tsx | 已实现 | 主蓝 token 全应用 | 无 | 无 | 有 | 无 | MATCH | 逐像素复核历史(旧 A 类闭环) |
| SH-15 | 面包屑 | 面包屑分隔符「›」与三级语法(配置›数据源[›源名]) | ›分隔 | 点击级跳转 | 位置+返回路径 | DataSources.tsx / DataSourceDetail.tsx / Analytics 无面包屑(参考 TI 页亦无) | 已实现 | › 分隔,级可点 | 无 | 无 | 有 | 无 | MATCH | RT/01,02 |
| SH-16 | 侧栏明暗 | 侧栏底色:PNG1 深色(#000 近黑)vs PNG2 浅色(白) | — | — | 共享 chrome 主题 | Sidebar.tsx(现浅色 bg-card) | 已实现(浅色) | 浅色侧栏 | 无 | 无 | — | — | REFERENCE CONFLICT | 两权威参考直接读取确认真冲突(PNG1 深黑/PNG2 白);待 User 裁(已知 SC-7);裁前 FINAL PASS 阻塞项 |
