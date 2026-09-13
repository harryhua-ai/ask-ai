# V1.6.3 Reference Traceability Matrix — DS-P3 展开异常处理(PNG1 面板3)+ DS-P4 同步状态与活动(PNG1 面板4)

## DS-P3 知识内容异常处理(展开行)

| ID | 区域 | 要求 | 期望呈现 | 期望行为 | 期望产品语义 | 前端:文件 | 运行时状态 | 当前行为 | 后端 API 依赖 | 持久化依赖 | 现有支持 | 权威数据真值 | 分类 | 证据/所需实现/验收/需User决定 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| DS-P3-01 | 展开行 | 行头展开(⌄ Contact Us + 需处理徽章) | chevron+名称+徽章 | 点击展开/收起 | 原地诊断 | DataSourceDetail doc-row-toggle+展开 TableRow | 已实现 | 行下原地展开 | — | — | 有 | — | MATCH | RT/03(Contact Us 展开);旧 A-P3-01 |
| DS-P3-02 | 诊断 | 「问题」说明(当前有效知识已存在,但部分内容没有进入当前服务) | 问题描述段 | — | 异常性质判定 | notServingReason | 已实现 | 权威原因转述(该文档当前在服,无异常记录/缺席原因) | document-truth | documents | 有 | lifecycle 原因 | MATCH | RT/03 |
| DS-P3-03 | 诊断 | 「源内容」状态(正常) | 状态词 | — | 源健康 | lifecycleLabel | 已实现 | 源内容状态:在服/缺席 徽章 | document-truth lifecycle | — | 有 | — | MATCH | RT/03 |
| DS-P3-04 | 诊断 | 「当前有效版本」v2 | v+状态+生效时间 | — | 版本真相 | current_version | 已实现 | v1(active) · 生效自(人类化+title) | document-truth | document_versions | 有 | 版本链 | MATCH | 旧 A-P3-02 闭环;RT/03 |
| DS-P3-05 | 诊断 | 「当前服务 10 / 12」分数(持久 chunk 入服数/总数) | 分数 | — | chunk 级在服投影 | 现为二值「在服/不在服 · 持久 chunk N」 | 缺席(分数) | 显示 在服+持久 chunk 总数,无入服分数 | 需 chunk 级 serving 计数 | 向量一致性核验 | 部分(chunk 总数有) | verify_source_vectors | PRODUCT-FUNCTIONAL GAP | 所需实现:chunk 级 serving/总数投影端点;验收:分数=真实核验值;需 User 决定 YES/NO(旧 C-B1-04) |
| DS-P3-06 | 诊断 | 「系统已自动尝试恢复 1 次,未成功」注记 | info 行 | — | 逐文档自动恢复次数真相 | 无 | 缺席 | 无(recovery 为 sync_runs 源级) | 需逐文档恢复事件投影 | 恢复事件记录 | 无(sync_runs 源级) | — | PRODUCT-FUNCTIONAL GAP | 所需实现:逐文档恢复事件计数投影;验收:注记=真实恢复次数;需 User 决定 YES/NO(旧 C-B1-06) |
| DS-P3-07 | 动作 | 「重新处理」按钮 | 蓝主按钮 | 点击触发该文档真实重处理(入库→重建向量) | 行级修复命令 | 无 | 缺席 | 无(只读;页面自述「行级修复操作需待权威修复契约」) | 需 POST 修复命令端点 | 修复任务+审计持久化 | 无 | — | PRODUCT-FUNCTIONAL GAP | 所需实现:修复命令契约(类目/幂等/验证/RBAC/审计);验收:真实点击→POST→状态迁移→UI 反映;需 User 决定 YES/NO(旧 C-B1-05) |
| DS-P3-08 | 动作 | 「重新处理完成」绿色验证卡(知识内容已成功进入当前服务) | 成功卡 | 修复完成后呈现 | 修复结果反馈 | 无 | 缺席 | 无 | 依赖 DS-P3-07+验证 | 同上 | 无 | — | PRODUCT-FUNCTIONAL GAP | 依赖修复契约;验收:修复→卡片呈现真实结果;需 User 决定(旧 C-B1-07) |
| DS-P3-09 | 动作 | 验证卡内「一致性验证 通过」+ 12/12 | 校验行 | 修复后一致性核验通过 | 修复有效性证明 | 无 | 缺席 | 无 | 依赖 verify_source_vectors 级核验入修复流 | 向量 | 核验函数已存在(服务级) | — | PRODUCT-FUNCTIONAL GAP | 与 DS-P3-07/08 同契约;验收:核验值真实 |

## DS-P4 同步状态与活动(展开面板;结构 V-3 已裁)

| ID | 区域 | 要求 | 期望呈现 | 期望行为 | 期望产品语义 | 前端:文件 | 运行时状态 | 当前行为 | 后端 API 依赖 | 持久化依赖 | 现有支持 | 权威数据真值 | 分类 | 证据/所需实现/验收/需User决定 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| DS-P4-01 | 容器 | 「同步状态」浮层卡+X 关闭 | 浮层面板 | 关闭 | 可收纳证据面板 | SyncActivityPanel(页内 section) | 已实现(页内 section) | 页内「同步状态与活动」区块 | — | — | 有 | — | USER-APPROVED DESIGN CHANGE | User 已裁 V-3(同步/活动结构 ACCEPTED 不变) |
| DS-P4-02 | 字段 | 「最近成功 2 小时前」 | 相对时间 | hover 精确 | 上次成功 | lastSuccessIso(runs) | 已实现 | 一致 | GET /sync-runs | sync_runs | 有 | runs 权威 | MATCH | RT/04 |
| DS-P4-03 | 字段 | 「下次同步 4 小时后」倒计时 | 相对时间 | 随调度更新 | 调度真相 | 无 | 缺席 | 不呈现(以「同步周期」承载) | 需调度器下次执行真值 | 调度状态 | 无(周期有,下次时间无) | — | PRODUCT-FUNCTIONAL GAP | 所需实现:调度真值端点(next_run_at);验收:倒计时=调度权威;需 User 决定 YES/NO(旧 C-B1-08) |
| DS-P4-04 | 字段 | 「最近结果 部分成功」 | 徽章 | — | 最近结果 | LATEST_RESULT_META | 已实现 | 部分成功(琥珀) | last_sync_status | sync_log | 有 | — | MATCH | RT/04;API 核验 |
| DS-P4-05 | 字段 | 「同步可靠性 98.7%」 | 一位小数百分比 | hover 样本注记 | 窗口可靠性 | reliabilityLine toFixed(1) | 已实现 | 98.7%(77/78) | /analytics/source-health | sync_log 30d | 有 | 成功率权威公式 | MATCH | API=0.9872,PG=77+1;RT/04 |
| DS-P4-06 | 字段 | 「同步周期 每6小时」 | 周期词 | — | 周期配置 | humanizeInterval | 已实现 | 每 6 小时 | data_sources.sync_interval | — | 有 | — | MATCH | RT/04 |
| DS-P4-07 | 活动 | 「最近活动」时间线(时间+事件+色点) | 垂直时间线 | — | 事件史 | buildSyncActivity | 已实现 | 时间线渲染(异常优先;常规成功压缩组可展开) | /sync-runs | sync_runs/sync_log | 有 | runs 权威 | MATCH | RT/04 |
| DS-P4-08 | 活动 | 异常优先着色(绿完成/黄发现/红失败/灰手动) | 四色点 | — | 严重度视觉 | TONE_DOT | 已实现 | 红/琥珀/绿/灰 | — | — | 有 | — | MATCH | RT/04 |
| DS-P4-09 | 活动 | 「管理员触发同步」事件(triggered_by) | 时间线条目 | — | 人工操作入史 | runs.triggered_by | 已实现 | 手动同步事件呈现 | sync_runs.triggered_by | sync_runs | 有 | — | MATCH | 旧 F1 功能链产生真实事件 |
| DS-P4-10 | 活动 | 「自动恢复未成功」类事件粒度 | 时间线条目 | — | 自动恢复事件史 | 由 runs 状态推导 | 部分 | RECOVERING 态在「当前同步」面板可见;时间线条目粒度=run 级 | sync_runs 状态机 | — | 部分 | — | MATCH(带内记录) | 恢复期在 run 记录内可见;独立「恢复事件」粒度并入 DS-P3-06 契约;不重复开 GAP |
| DS-P4-11 | 动作 | 手动「同步」触发 | 按钮 | POST 受理→运行态可见 | 人工同步 | onTriggerSync | 已实现 | POST 受理+toast+轮询 | POST /:id/sync | sync_runs | 有 | — | MATCH | 旧 F1 功能链 PASS |
