# R3 Track C Contract — Conversation Review（冻结）

- Reference（权威）：Issue #63 全文（Product 要求/Acceptance/Boundary）。
- Issue IDs：**#63**（全部）。
- 基线：fresh main `94ddb64`。

## 1. Product Semantics（冻结）

1. Conversation ID 是既有权威标识（`GET /api/admin/conversations` 与详情响应的 `id`）；UI 只补呈现，**禁生成第二套展示 ID**、禁改 schema/API 路由/identity 语义。
2. 列表行：次级弱化短格式（如 `ID 3f19c8a2…`）+ hover/title 或复制动作取得完整 UUID；不得显著压缩 question 主内容。
3. 详情页（审查/诊断工作面）：完整 Conversation ID 明确显示（「对话详情」标题下方或既有 metadata 行）；完整值可选取/复制；**禁只显示缩写**。
4. viewer 权限与现有对话审查读取权限一致（viewer 亦可见 ID）。
5. UUID 可复制后直接服务既有 `/conversations/{conversation_id}` / trace / DB 排障链路。

## 2. 变更边界（文件所有权）

- 可改：`admin/src/pages/Conversations.tsx`（唯一实现文件）+ 新增/扩展 vitest。
- 禁改：任何 backend 文件（后端 `id` 字段已足，除非执行调查发现真实契约缺口——发现时停下上报 Role A，不得自行改后端）；其它页面/共享组件（如需复制按钮通用化，优先页内实现，避免越权）。

## 3. Backend/Data 要求

无（additive UI observability；零新端点/零新列/零语义变化）。

## 4. Frontend 要求

- 列表行渲染短 ID：取 `conv.id` 前缀（弱化样式）；完整值经 title/复制可得。
- 详情区渲染 `detail.id` 完整 UUID；`user-select` 可选或复制按钮（复制内容=完整原始 UUID）。
- ID 与 selectedId 严格联动（切换对话即切换）。

## 5. Forbidden shortcuts（r2 冻结清单沿用）

- 第二套展示 ID/截断后当作完整值呈现/复制按钮复制缩写/仅详情显示而列表缺失（或反之）/借机改动对话审查其它布局。

## 6. Acceptance（验收门）

- 验收矩阵 Track C 全行证据填充；#63 Acceptance 1–9 逐条对应。
- vitest：列表短 ID+完整值可得；详情完整 UUID；复制内容断言；切换一致性；viewer 角色可见。
- G3：vitest 全量+tsc 0+零回归。

## 7. Runtime states（必须覆盖）

列表多行态；选中态（ID 联动）；详情态（完整 ID）；viewer 权限态；复制动作态。

## 8. E2E

- 从 UI 复制 ID → `/conversations/{conversation_id}` API 命中 → trace 查询联动（G5 排障链走查）。

## 9. Deliverables

分支 + Conversations.tsx 变更 + vitest + 截图（列表/详情 1536×1024 @1x）+ 验收矩阵证据填充 + 执行报告（`docs/engineering/tasks/v163-r3-track-c-execution.md`，`git add -f`）。
