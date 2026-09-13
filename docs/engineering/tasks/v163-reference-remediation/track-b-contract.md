# Track B Contract — B1 编辑抽屉呈现缺陷(DEF-A2/A3/A4)(Planning 修订:Role A 裁决冻结)

- **目标**:矩阵 DS-P5-02/04/05 三条 IMPLEMENTATION DEFECT 清零。
- **参考需求(精确 ID)**:DS-P5-02(名称* 字段)、DS-P5-04(类型 编辑态禁用)、DS-P5-05(自动同步 toggle+说明)。
- **冻结产品语义**:U-5(DS-P5-04):**create 可选;edit 既有源 immutable/disabled;匹配参考**。真值(product/type/enabled)零变更。
- **变更边界**:仅 `admin/src/components/dataSources/SourceEditorDrawer.tsx` + 测试;零 hook/API 层变更;零后端。
- **后端数据要求**:无。
- **前端行为**:名称*(必填标记)label;自动同步 toggle+逐字说明「开启后，系统将按设定周期自动同步。」;**编辑态类型字段 disabled(既有源 immutable);新建态类型选择保留(create 可选)**。
- **运行时状态要求**:交付后 vite 5184/backend 8104 真实栈复核。
- **视觉证据**:AFTER 编辑抽屉截图(1536×1024 @1x)对照 PNG1 面板5。
- **功能 E2E**:打开编辑→改名称→保存→列表/详情反映;toggle 关→保存→PUT enabled=false 权威真实反映;编辑抽屉类型 disabled 断言。
- **禁止捷径**:不得用 CSS 伪装 disabled;不得改 PUT payload 语义;不得删除新建态类型选择;frontend-only fake state 禁止。
- **验收**:vitest(label/toggle/disabled);切换自动同步→保存→PUT enabled 真实生效(本地栈)。
- **交付物**:分支 `track/v163-b-drawer`、执行报告、截图、测试日志。
- **前置**:无(U-5 已冻结);可立即,与 A/C–F 全并行(Wave 1)。
- **Issue 映射**:落地后贡献 #53/#54 编辑抽屉字段范围关闭。
- **B 级提示词要点**:worktree=实现授权树;branch `track/v163-b-drawer`;冻结合同=本文件+remediation plan §6;范围=DEF-A2/A3/A4(U-5 冻结:edit 禁用);验收=vitest+真实栈 E2E+截图;交付物如上。
