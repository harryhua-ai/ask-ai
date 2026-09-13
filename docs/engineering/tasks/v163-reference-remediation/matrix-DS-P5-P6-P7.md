# V1.6.3 Reference Traceability Matrix — DS-P5 编辑数据源 Drawer(PNG1 面板5)/ DS-P6 知识设置 Drawer(面板6)/ DS-P7 高风险预览 Modal(面板7)

**PLANNING 修订(2026-09-13,Role A 裁决冻结)**:新增「冻结决定」列(U-x=remediation plan §5 编号,已冻结;N/A=无需产品裁决)。分类不变:DS-P5 MATCH 7 / IMPLEMENTATION DEFECT 2;DS-P6 GAP 5;DS-P7 GAP 6。GAP 行方向全部获授权但**保持 GAP 直到实现+运行时验收完成**。

## DS-P5 编辑数据源 Drawer

| ID | 区域 | 要求 | 期望呈现 | 期望行为 | 期望产品语义 | 前端:文件 | 运行时状态 | 当前行为 | 后端 API 依赖 | 持久化依赖 | 现有支持 | 权威数据真值 | 分类 | 证据/所需实现/验收/需User决定 | 冻结决定 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| DS-P5-01 | 容器 | 「编辑数据源」右侧抽屉+X | Sheet 抽屉 | 打开/关闭,上下文保持 | 编辑容器 | SourceEditorDrawer Sheet | 已实现 | 右侧抽屉,不离开列表/详情 | — | — | 有 | — | MATCH | RT/05 | N/A |
| DS-P5-02 | 字段 | 「名称*」字段(必填,WooCommerce) | 名称 label+必填星号 | 编辑源显示名 | 源命名 | 现为「产品线」字段 | 部分 | 产品线 label,同真值(product) | PUT /data-sources | data_sources.product | 有 | — | IMPLEMENTATION DEFECT | 所需实现:label 收敛为 名称(或双语义标注);验收:vitest label 断言;RT/05 现状 | N/A |
| DS-P5-03 | 字段 | 「连接地址*」字段(https://woocomerce.com) | 地址 label+必填 | 按类型呈现地址字段 | 源连接 | 类型化字段(店铺地址/网站地址/仓库 URL) | 已实现 | 商城→店铺地址,同真值 | config | — | 有 | — | MATCH | RT/05;类型化 label 为忠实等价(记录) | N/A |
| DS-P5-04 | 字段 | 「类型」字段禁用(商城,灰) | 禁用 select | 编辑时类型不可改 | 创建后类型不可变 | 类型 select 可编辑 | 偏差 | 编辑时类型可改(既有编辑器超集能力) | PUT type | — | 有(超集) | — | IMPLEMENTATION DEFECT | 冻结语义:**create 可选;edit 既有源 immutable/disabled;匹配参考**;修复=编辑态禁用;验收:编辑抽屉类型 disabled+vitest;新建态类型选择保留(可选);旧 C-B1-09 | **U-5 已冻结:create 可选;edit 既有源 immutable/disabled;匹配参考** |
| DS-P5-05 | 字段 | 「自动同步」toggle(开)+说明「开启后,系统将按设定周期自动同步。」 | 开关控件+说明 | 切换自动同步 | 同步策略 | 现为「状态/启用」checkbox | 偏差 | 启用 checkbox,无说明文案,语法为 checkbox 非 toggle | PUT enabled | — | 有(同真值) | — | IMPLEMENTATION DEFECT | 所需实现:toggle 语法+说明文案(真值=enabled 不变);验收:开关切换真实保存 | N/A |
| DS-P5-06 | 字段 | 「同步周期 每6小时」select | select | 选择周期 | 周期配置 | 同步间隔 select(1h/12h/24h/自定义) | 已实现 | 6h 自定义呈现;周期真值一致 | sync_interval | — | 有 | — | MATCH | RT/05 | N/A |
| DS-P5-07 | 动作 | 「取消」 | outline 按钮 | 关闭不保存 | 放弃 | closeForm | 已实现 | — | — | — | 有 | — | MATCH | RT/05 | N/A |
| DS-P5-08 | 动作 | 「保存」真实更新 | 蓝主按钮 | 提交 PUT→列表/详情刷新 | 配置更新 | updateDs | 已实现 | 真实 PUT+缓存失效 | PUT /data-sources/:id | data_sources | 有 | — | MATCH | 既有功能链 | N/A |
| DS-P5-09 | 行为 | 上下文保持(编辑不离开当前面) | 抽屉浮层 | 保存后停留 | 连续运营 | context-preserving §4.5 | 已实现 | 一致 | — | — | 有 | — | MATCH | RT/05 | N/A |

## DS-P6 知识设置 Drawer(参考面板6;整面无实现)

| ID | 区域 | 要求 | 期望呈现 | 期望行为 | 期望产品语义 | 前端:文件 | 运行时状态 | 当前行为 | 后端 API 依赖 | 持久化依赖 | 现有支持 | 权威数据真值 | 分类 | 证据/所需实现/验收/需User决定 | 冻结决定 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| DS-P6-01 | 容器 | 「知识设置」抽屉入口+标题+X | 抽屉 | 打开源级知识设置 | 知识策略管理面 | 无 | 缺席 | 无该面(无入口/无实现) | 需知识设置读/写端点 | 需源级策略持久化 | 无 | 无 | PRODUCT-FUNCTIONAL GAP | 所需实现:知识设置域(端点+持久化+抽屉);冻结语义见 U-12(CURRENT/HISTORICAL 证据资格政策层+新鲜度政策;**不得重设计整个 lifecycle 模型**);验收:真实打开→读→写→重开一致;仓库证据:可行(data_sources 加性策略列,与 S0 lifecycle/documents.lifecycle 兼容);旧 C-B1-10 | **U-12 已冻结:实现;CURRENT=有资格支撑当前事实型回答(受新鲜度政策约束);HISTORICAL=仅历史/溯源/证据链,不得支撑当前价格/规格/可用性/运行状态断言;政策层叠加于现行 lifecycle 真值之上** |
| DS-P6-02 | 字段 | 「时态角色*」=CURRENT + 说明「用于支持当前有效知识回答。」 | select+必填+说明 | 选择 CURRENT/HISTORICAL | 知识时态资格语义 | 无 | 缺席 | 无 | 需时态角色字段+资格语义贯通服务端 | 策略列 | 无 | — | PRODUCT-FUNCTIONAL GAP | 时态角色影响检索资格;冻结语义:CURRENT/HISTORICAL 为证据资格政策层(非新 lifecycle 模型);**检索资格必须消费该政策真值**;过期 CURRENT 证据必须诚实浮现;验收:设置 HISTORICAL 后检索资格真实变化 | **U-12 已冻结(同 DS-P6-01;过期 CURRENT 诚实浮现;后端权威)** |
| DS-P6-03 | 字段 | 「新鲜度要求*」=12小时 + 说明「超过该时间没有成功更新时,系统将提醒知识更新服务。」 | select+必填+说明 | 设定新鲜度阈值 | 新鲜度提醒策略 | 无 | 缺席 | 无(freshness 仅健康维度词) | 需阈值字段+提醒机制 | 策略列 | 无(freshness 维度已有近义概念) | — | PRODUCT-FUNCTIONAL GAP | 所需实现:阈值持久化+超期提醒;冻结语义:新鲜度政策**按 source/policy 域可配置、后端权威、过期态 Admin 可见、检索资格消费该政策真值**;验收:超期→提醒呈现+过期态可见 | **U-12 已冻结(新鲜度政策:可配置/后端权威/过期态 Admin 可见/资格消费真值)** |
| DS-P6-04 | 动作 | 「取消/保存」 | 按钮组 | 保存持久化 | 策略写入 | 无 | 缺席 | 无 | 同上 | 同上 | 无 | — | PRODUCT-FUNCTIONAL GAP | 同 DS-P6-01 契约 | **U-12 已冻结(同 DS-P6-01)** |
| DS-P6-05 | 行为 | 保存后设置生效并反映在服务语义 | — | — | 策略→服务一致性 | 无 | 缺席 | 无 | 同上 | 同上 | 无 | — | PRODUCT-FUNCTIONAL GAP | 同上;验收:策略变化在检索/健康面真实可见 | **U-12 已冻结(同 DS-P6-01)** |

## DS-P7 高风险变更影响预览 Modal(参考面板7;整面无实现)

| ID | 区域 | 要求 | 期望呈现 | 期望行为 | 期望产品语义 | 前端:文件 | 运行时状态 | 当前行为 | 后端 API 依赖 | 持久化依赖 | 现有支持 | 权威数据真值 | 分类 | 证据/所需实现/验收/需User决定 | 冻结决定 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| DS-P7-01 | 容器 | 「确认知识设置变更」Modal(高风险变更时保存触发)+X | Modal+遮罩 | 弹出确认 | 高风险变更门禁 | 无 | 缺席 | 无 | 依赖 DS-P6 域 | — | 无 | 无 | PRODUCT-FUNCTIONAL GAP | 触发条件=时态角色类高风险变更;冻结语义:实现(依赖知识设置语义,U-12);旧 C-B1-11 | **U-13 已冻结:实现;依赖知识设置语义(U-12)** |
| DS-P7-02 | 内容 | 变更摘要「时态角色 CURRENT → HISTORICAL(红)」 | before→after diff | — | 变更可读 | 无 | 缺席 | 无 | 预览 diff | — | 无 | — | PRODUCT-FUNCTIONAL GAP | 同契约 | **U-13 已冻结(同 DS-P7-01)** |
| DS-P7-03 | 内容 | 「预计影响:受影响知识 202 / 当前知识资格将变化 199 / 历史知识资格将变化 199」 | 三行计数 | — | 影响面量化(权威计算,禁止前端伪造) | 无 | 缺席 | 无 | 需 mutation-preview API(服务端按当前账本计算) | documents+资格语义 | 无 | — | PRODUCT-FUNCTIONAL GAP | 冻结语义:**影响计数必须后端权威**;验收:计数=服务端真实计算 | **U-13 已冻结:影响计数必须后端权威** |
| DS-P7-04 | 内容 | 「不会删除持久知识。」说明 | 蓝系说明条 | — | 安全承诺语义 | 无 | 缺席 | 无 | — | — | 无 | — | PRODUCT-FUNCTIONAL GAP | 同契约 | **U-13 已冻结(同 DS-P7-01)** |
| DS-P7-05 | 内容 | 「变更后系统将重新验证服务状态。」说明 | 说明行 | 确认后触发重验 | 服务一致性 | 无 | 缺席 | 无 | 重验任务 | — | verify_source_vectors 服务级已有 | — | PRODUCT-FUNCTIONAL GAP | 冻结语义:**确认必须施加与预览完全一致的 mutation,否则 drift 时失效/重算**;验收:确认后重验真实执行 | **U-13 已冻结:确认施加与预览完全一致的 mutation;drift 时失效/重算** |
| DS-P7-06 | 动作 | 「取消/确认变更(红)」 | 按钮组 | 确认执行变更 | 高危操作确认 | 无 | 缺席 | 无 | 同上 | — | 无 | — | PRODUCT-FUNCTIONAL GAP | 同契约 | **U-13 已冻结(同 DS-P7-01/05)** |
