# Track E Contract — B2 观察生命周期 + 导出与隐私(GAP-B2-2 / GAP-B2-3)(Planning 修订:Role A 裁决冻结)

- **目标**:矩阵 TI-07/18/34/35/36/37/41(带内)/42/43/45 清零。
- **参考需求(精确 ID)**:TI-07/TI-18/TI-42(观察中 状态:队列蓝标+过滤选项+侧板呈现)、TI-36(「内容补充完成后」区块)、TI-37(「▷ 内容已补充,开始观察」CTA,点击→验证数据同步状态→通过后进入观察中)、TI-43(观察后转移)、TI-41(历史记录 Tab 流转史)、TI-34/TI-45(导出相关对话+真实 CSV 下载)、TI-35(隐私说明)。
- **冻结产品语义**:
  - U-15(TI-07/18/36/37/41/42/43):**实现 OPEN→OBSERVING→RESOLVED。进入 OBSERVING 需:操作者确认内容修复完成+相关源 sync/reindex 成功+post-sync 验证成功。默认观察期 7 天。OBSERVING 期间:同一 gap/证据失败复现→回 OPEN;满窗无复现→转 RESOLVED。操作者可中止 OBSERVING→OPEN;不得直接强转 RESOLVED。全部转移:持久化、带时间戳、可审计、History 可见。**(仓库可行性证据:question_clusters.status 可扩展;sync_runs status/finished_at/consistency+sync_log+verify_source_vectors 可作进入条件钩子)
  - U-16(TI-34/35/45):**admin-only 导出;最小必要字段;排除直接个人身份;导出动作可审计;CSV 必须与所选 gap/query 范围精确对应**。
- **权威数据源**:question_clusters.status+观察元数据+流转事件表(持久化真值);sync_runs/sync_log(同步核验);verify_source_vectors(post-sync 验证);conversations(导出内容=权威范围数据,非当前渲染行)。
- **变更边界**:前端 Analytics 拆分后观察/导出/历史面板文件(IF-6);后端独立子模块 tech_observation.py、tech_export.py、词表常量模块 gap_status.py(IF-1)、新观察服务、新导出服务;`question_clusters.status` 扩展 observing+观察元数据+流转事件表。
- **后端数据要求**:观察状态机(进入条件=操作者确认+sync/reindex 成功+post-sync 验证成功;观察期 7 天默认;复现检测;转移任务;RBAC);流转事件持久化(带时间戳、可审计);导出流式生成(范围=所选 gap/query 权威数据;列集=最小必要字段,IF-5 冻结;审计行);隐私排除清单(直接个人身份字段零包含)。
- **前端行为**:CTA 副文案逐字「系统将验证数据同步状态，通过后进入观察中。」;观察中蓝态+过滤选项;导出真实触发下载;历史 Tab 渲染全部流转事件。
- **运行时状态要求**:本地栈全链复核;fixture 标记隔离;转移时间线与 DB 事件三角一致。
- **视觉证据**:观察中态/CTA/导出卡/历史时间线 AFTER 截图(1536×1024 @1x)。
- **功能 E2E**:真实点击开始观察→核验(确认+sync/reindex 成功+post-sync 验证)→队列行转观察中(蓝标,过滤可选中)→双路径(模拟期满→转已解决;构造复现→回 OPEN)+中止路径(→OPEN,禁强转 RESOLVED 断言)→历史 Tab 出现全流转(持久化事件);导出→CSV 下载内容=所选范围权威数据且无隐私字段;审计行可查。
- **禁止捷径**:frontend-only fake state;跳过同步核验/操作者确认直接进观察;**unpersisted OBSERVING transitions(转移不留痕)**;直接强转 RESOLVED;前端造 CSV;**export 由当前渲染行而非权威范围数据构建**;导出包含隐私排除清单字段;两态既有行为零回归。
- **验收**:功能 E2E(观察双路径+中止+导出+审计)+ pytest+vitest+tsc+build;三角(API=PG=UI)。
- **交付物**:分支 `track/v163-e-observation`、观察契约(IF-1)+导出/隐私契约(IF-5)冻结稿、执行报告、截图、测试日志、fixture SQL 全文。
- **前置**:IF-1/IF-5 冻结;Track D 先行(分类稳定,IF-2);Analytics.tsx 拆分 prep 先行;可进入 Wave 1。
- **Issue 映射**:落地后关闭 #58、#59(gap 状态机/导出部分)。
- **B 级提示词要点**:worktree=实现授权树;branch `track/v163-e-observation`;冻结合同=本文件+IF-1/IF-5+remediation plan §6;范围=U-15 全状态机+U-16 导出;验收=观察双路径+中止+导出审计 E2E;交付物含契约冻结稿与 fixture SQL 全文。
