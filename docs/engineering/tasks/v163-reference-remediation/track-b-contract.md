# Track B Contract — B1 编辑抽屉呈现缺陷(DEF-A2/A3/A4)

- **目标**:矩阵 DS-P5-02/04/05 三条 IMPLEMENTATION DEFECT 清零。
- **参考需求**:DS-P5-02(名称* 字段)、DS-P5-04(类型 编辑态禁用)、DS-P5-05(自动同步 toggle+说明)。
- **产品语义**:编辑抽屉呈现与参考面板5一致;真值(product/type/enabled)零变更;类型是否可改的让渡由 User 裁(U-5)。
- **变更边界**:仅 `admin/src/components/dataSources/SourceEditorDrawer.tsx` + 测试;零 hook/API 层变更;零后端。
- **后端数据要求**:无。
- **前端要求**:名称*(必填标记)label;自动同步 toggle+逐字说明「开启后，系统将按设定周期自动同步。」;类型字段按 User 裁决禁用或维持(转 UADC 记录)。
- **禁止捷径**:不得用 CSS 伪装 disabled;不得改 PUT payload 语义;不得删除新建态类型选择。
- **验收**:vitest(label/toggle/禁用态);切换自动同步→保存→PUT enabled 真实生效(本地栈);编辑抽屉截图对照 PNG1 面板5。
- **运行时状态**:交付后 vite 5184/backend 8104 真实栈复核。
- **视觉证据**:AFTER 抽屉截图。
- **功能 E2E**:打开编辑→改名称→保存→列表/详情反映;toggle 关→保存→同步不再自动触发(或 enabled=false 权威反映)。
- **交付物**:分支 `track/v163-b-drawer`、执行报告、截图、测试日志。
- **前置**:无(DEF-A3 的方向由 U-5 决定,可先行实现参考向,User 批超集则回退该子项)。
