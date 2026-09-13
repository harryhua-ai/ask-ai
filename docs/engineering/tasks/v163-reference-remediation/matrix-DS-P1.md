# V1.6.3 Reference Traceability Matrix — DS-P1 数据源列表(PNG1 面板1)

**PLANNING 修订(2026-09-13,Role A 裁决冻结)**:新增「冻结决定」列(U-x=remediation plan §5 编号,已冻结;N/A=无需产品裁决)。本面 24 行无分类变化:MATCH 21 / USER-APPROVED DESIGN CHANGE 2(UADC-2 行高 + MATCH(带外) 2 行内含)。方向获授权 ≠ 变 MATCH。

| ID | 区域 | 要求 | 期望呈现 | 期望行为 | 期望产品语义 | 前端:文件 | 运行时状态 | 当前行为 | 后端 API 依赖 | 持久化依赖 | 现有支持 | 权威数据真值 | 分类 | 证据/所需实现/验收/需User决定 | 冻结决定 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| DS-P1-01 | 面包屑 | 配置›数据源 | ›分隔两级 | 级可点 | 位置 | DataSources.tsx nav | 已实现 | 一致 | 无 | 无 | 有 | 无 | MATCH | RT/01 | N/A |
| DS-P1-02 | 页头 | 页标题「数据源」 | h1 | — | 页面身份 | DataSources.tsx h1 | 已实现 | 一致 | 无 | 无 | 有 | 无 | MATCH | RT/01 | N/A |
| DS-P1-03 | 页头 | 页描述「管理 ASK-AI 的知识来源…」 | 副标题句 | — | 页面职责说明 | DataSources.tsx p | 已实现 | 逐字一致 | 无 | 无 | 有 | 无 | MATCH | RT/01 | N/A |
| DS-P1-04 | 页头 | 「+ 添加数据源」主按钮(唯一主按钮) | 蓝色主按钮 | 打开新建流程 | 创建入口 | DataSources.tsx Button+SourceEditorDrawer | 已实现 | 打开新建抽屉 | POST /data-sources | data_sources | 有 | — | MATCH | RT/01;既有 G010 功能链 | N/A |
| DS-P1-05 | 页头 | 添加→新建 Drawer 真实可创建 | 抽屉表单 | 提交→列表出现新源 | 创建能力 | SourceEditorDrawer.tsx | 已实现 | 创建链真实(历史 F 链) | POST /data-sources | data_sources+连接器配置 | 有 | — | MATCH | 旧功能链证据;本次未重复执行写操作(零副作用审计纪律) | N/A |
| DS-P1-06 | 工具栏 | 搜索框「搜索数据源...」 | 圆角输入框 | 输入过滤列表 | 查找 | DataSources.tsx Input | 已实现 | 客户端过滤(名称/地址/id) | 无(呈现层) | 无 | 有 | — | MATCH | RT/01;admin/tests | N/A |
| DS-P1-07 | 工具栏 | 状态过滤 select | 紧凑 select | 按操作者状态过滤 | 异常定位 | DataSources.tsx select | 已实现 | 全部状态/需处理/正常/中间态/待分类/同步失败/已禁用 | attention-summary+sync-health | 同上 | 有 | operatorStateOf 映射 | MATCH | RT/01;10-attention-filter 历史证据 | N/A |
| DS-P1-08 | 工具栏 | 状态过滤真实生效 | 行集随值变化 | 组合过滤 | 同上 | 同上 | 已实现 | tone 过滤 | 同上 | — | 有 | — | MATCH | vitest DataSourcesConvergence | N/A |
| DS-P1-09 | 工具栏 | 类型过滤 select | 紧凑 select | 按类型过滤 | 定位 | DataSources.tsx select | 已实现 | 全部类型+清单内类型 | 无(呈现层) | — | 有 | — | MATCH | RT/01 | N/A |
| DS-P1-10 | 工具栏 | 类型过滤真实生效 | 行集随值变化 | — | — | 同上 | 已实现 | type 过滤 | — | — | 有 | — | MATCH | vitest | N/A |
| DS-P1-11 | 表头 | 列:名称 | 文本列 | — | — | Table | 已实现 | 名称 | — | — | 有 | — | MATCH | RT/01 | N/A |
| DS-P1-12 | 表头 | 列:类型 | 运营词(商城/Wiki/网站/文件系统) | — | 源类型 | sourceTypeLabel | 已实现 | 运营词映射 | — | — | 有 | data_sources.type | MATCH | RT/01(Partner Portal=文件系统) | N/A |
| DS-P1-13 | 表头 | 列:状态 | 操作者状态徽章(需处理/正常/待分类/同步失败) | hover 显示次级证据 | 健康一眼可读 | operatorStateOf+Badge | 已实现 | 四态+删除生命周期附加徽章 | /data-sources last_sync_status + attention-summary + /sync-health | data_sources/documents/sync_log | 有 | 后端权威值呈现映射 | MATCH | RT/01(同步失败/需处理/待分类/正常 四态同屏) | N/A |
| DS-P1-14 | 表头 | 列:知识数量 | 数字(千分位) | — | 内容规模 | attention-summary ledger_total | 已实现 | 1,204 等千分位 | GET /data-sources/attention-summary | documents 聚合 | 有 | 账本权威计数 | MATCH | RT/01(SDK Docs 1,204);API+DB 核验 | N/A |
| DS-P1-15 | 表头 | 列:需处理(一等列) | 红色数字/— | — | 待处置规模 | attention_count | 已实现 | 红/— | attention-summary | documents lifecycle | 有 | attention_count 权威 | MATCH | RT/01(3/1);API=PG 核验 | N/A |
| DS-P1-16 | 表头 | 列:最后同步 | 相对时间 | hover 精确时间 | 新鲜度 | relativeTime | 已实现 | 一致 | data_sources.last_sync | sync_log | 有 | — | MATCH | RT/01 | N/A |
| DS-P1-17 | 表头 | 列:操作(单「⋯」) | 单 ⋯ 按钮 | 开行操作菜单 | 动作收纳 | DropdownMenu | 已实现 | ⋯→详情/同步/编辑/可观测性/重试删除/删除 | 各动作既有端点 | — | 有 | — | MATCH | RT/01;旧 A-P1-04 闭环 | N/A |
| DS-P1-18 | 行为 | 名称点击进入详情 | 行名 hover 下划线 | 路由跳转 /data-sources/:id | 下钻 | navigate | 已实现 | 真实跳转 | — | — | 有 | — | MATCH | RT/02(到达 store-woo) | N/A |
| DS-P1-19 | 行为 | ⋯ 菜单动作真实执行 | 菜单项 | 同步触发 POST、删除受理、编辑开抽屉 | 运营动作 | hooks/useDataSources | 已实现 | 真实 API 调用(历史 F1 功能链) | POST /data-sources/:id/sync 等 | sync_runs | 有 | — | MATCH | 旧 v163-b1 功能链 functional-action-sync-chain.txt | N/A |
| DS-P1-20 | 行为 | 异常优先排序 | 同步失败/需处理在前 | 呈现层排序 | 异常先见 | TONE_PRIORITY sort | 已实现 | severity 升序+id 稳定 | — | — | 有 | — | MATCH | RT/01(Partner Portal 首行);参考行序非严重度序=板面示意,实现语义记录在案 | N/A |
| DS-P1-21 | 页脚 | 「共 6 个数据源」总数 | 文本计数 | — | 全集规模 | sources.length | 已实现 | 共 N 个数据源 | GET /data-sources | data_sources | 有 | 行数真值 | MATCH | RT/01(运行时 7 源含功能链残留 ne301,数据态非分类对象) | N/A |
| DS-P1-22 | 行为 | 行内「当前同步」运行中面板(参考未画;同步进行中应可见) | — | — | — | — | — | 运行时出现 QUEUED 面板(残留排队态) | /sync-status | sync_runs | 有(实现超出参考) | — | MATCH(带外记录) | RT/01 中两处「当前同步/排队中」为本地残留运行态真值,非参考要求项;提示验收环境应清理 fixture 残留 | N/A |
| DS-P1-23 | 视觉 | 列表行高 ~36px 密表 | 单行密表 | — | 密度 | [&_td]:!py-1.5 | 已实现 | 实测 41px | 无 | 无 | — | — | USER-APPROVED DESIGN CHANGE | User 已裁 V-1(41px ACCEPTED 不变) | UADC-2(V-1,既有 User 决定) |
| DS-P1-24 | 空态 | 无数据源空态(参考未画;必备诚实态) | — | — | — | 暂无数据源 行 | 已实现 | — | — | — | 有 | — | MATCH(带外记录) | vitest | N/A |
