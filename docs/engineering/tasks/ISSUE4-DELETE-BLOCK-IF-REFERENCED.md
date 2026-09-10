# Issue #4 执行报告 —— LLM 供应商凭证删除(block-if-referenced)Candidate Ready

- **Issue**:harryhua-ai/ask-ai#4(Admin: LLM provider credential delete button does not work)
- **Sprint**:Bug Fix Sprint — 2026-09(Wave 1 / P0)
- **基线**:authoritative main `c8d6e16fd8d2f6e47bfd673afc408e9569bf7392`(#47 整合后)
- **候选分支**:`fix/4-provider-delete-block-if-referenced`;候选 SHA 见分支 tip(未并 main、未部署)
- **结论**:CANDIDATE READY(待 Role A 独立评审;本报告随候选分支入库)

## 1. 根因(调查阶段确认,实现未偏移)

前端接线缺失,后端 API 早已存在:

- `admin/src/pages/LLMProviders.tsx:318` 向 `ProviderCredentialDialog` 传入 **`onDelete={() => {}}`** 空操作;
- `admin/src/hooks/useLLMProviders.ts` 缺少 `useDeleteProvider`(同文件已有 `useRevokeHost` 的 DELETE+invalidate 先例);
- 凭证弹窗垃圾桶按钮直接 `onDelete(p.id)`,**无任何确认环节** —— 三者叠加 = 点击无请求、无反馈。
- 后端 `DELETE /llm-providers/{provider_id}` 已存在(`backend/api/admin/llm_providers.py`,EditorDep,404)且有测试。

## 2. 冻结语义(block-if-referenced)与实现

删除仅当该供应商**不被任何路由链引用**时允许;被引用 → **409 Conflict** + 结构化
`detail.referenced_tasks`,**零突变**(不删供应商、不改任何路由);无级联、无悬空引用、
无静默清理。

### 后端(`backend/api/admin/llm_providers.py`)

- 新增 `_chain_item_provider()`:链元素兼容两种持久化形态(新 `{"provider": ...}` /
  旧字符串;非 string 的 provider 值视为不匹配,防御脏数据)。
- `delete_provider`:先查供应商(不存在 → 404,既有语义保持);再扫全部 `LLMRouting.chain`,
  命中即 409,`detail = {message, referenced_tasks(排序稳定)}`,**在该 return 路径上
  无任何 session 写操作**;无引用才 `session.delete + commit`,且只删请求的那一行。
- 认证语义零变化(EditorDep = admin|editor)。

### 前端

- `admin/src/lib/api.ts`:`ApiError` 增加可选 `detail` 字段(增量;message 仍为
  `formatApiDetail` 可读文本),让调用方能做 409 结构化分支。
- `admin/src/hooks/useLLMProviders.ts`:新增 `useDeleteProvider` —— DELETE(encodeURIComponent)
  + 成功后失效 `["llm-providers"]` **和** `["llm-routing"]` 两份缓存。
- `admin/src/components/ProviderCredentialDialog.tsx`:垃圾桶 → **行内两步确认**
  (「删除 {id}?」/确认删除/取消,与 ChainChip 确认移除同一模式;不用 window.confirm,
  嵌入式浏览器会拦截);请求进行中按钮禁用(「删除中...」);完成后退出确认态。
- `admin/src/pages/LLMProviders.tsx`:真实 `handleDeleteProvider` 替换 no-op ——
  成功 toast(`供应商 X 已删除,点「应用变更」后生效`);409 toast 指名引用任务
  (`删除失败:X 仍被路由链引用(intent、generation),请先在「模型流水线」对应链路中移除后再删除`);
  其他失败显式报错。全程查询缓存失效重取,**无整页刷新**。

## 3. 变更文件

| 文件 | 变更 |
| --- | --- |
| `backend/api/admin/llm_providers.py` | `_chain_item_provider` + `delete_provider` 引用预检(409/零突变) |
| `admin/src/lib/api.ts` | `ApiError` 增量携带原始 `detail` |
| `admin/src/hooks/useLLMProviders.ts` | 新增 `useDeleteProvider`(DELETE + 双缓存失效) |
| `admin/src/components/ProviderCredentialDialog.tsx` | 行内两步删除确认 + pending 禁用 |
| `admin/src/pages/LLMProviders.tsx` | 真实删除 handler(成功/409/普通失败三分支 toast) |
| `tests/api/admin/test_llm_providers.py` | 引用删除全链路测试(下 §4);fixture 路由清理放宽为 `test-%` 前缀 |
| `admin/tests/useLLMProviders.test.tsx` | hook 测试 |
| `admin/tests/ProviderCredentialDialog.test.tsx` | 两步确认测试 |
| `admin/tests/LLMProviders.test.tsx` | 页面删除链路测试;mock ApiError 与真实 api.ts 对齐(携带 detail) |

## 4. 测试与结果

**后端**(`tests/api/admin/test_llm_providers.py`,28/28 绿;全量 `pytest -q`
**2189 passed / 7 skipped / 0 failed**):

- `test_delete_provider_referenced_409_zero_mutation`(新增,一条全链路):
  - 创建 ref + other 两供应商;
  - 引用链 A(对象格式,经 PUT)+ 引用链 B(旧字符串格式,直插 DB);
  - DELETE ref → **409**,`referenced_tasks == [A, B]`(排序稳定)且含 message;
  - **零突变断言**:GET providers 仍含 ref;GET routing 两条链与原值语义级相等;
  - 无引用的 other 删除 → 204(不受影响);
  - 解除引用(PUT 移除 ref 项)后 DELETE ref → 204;再删 → 404(既有语义);
- 既有 `test_delete_provider_and_404`(无引用删除 + 404)原样通过;
- 既有认证/RBAC 测试原样通过。

**Admin 前端**(vitest,**290/290 绿**,45 文件;`tsc -b && vite build` 通过):

- hook:DELETE 端点与 id 编码、成功后 providers+routing 双缓存失效;
- 弹窗:垃圾桶仅进入确认态不调用 onDelete;取消零请求;确认恰调用一次且只带该行 id;
  进行中禁用(「删除中...」);其余行不受影响;
- 页面:确认前零请求;确认后 DELETE 恰一次 + 成功 toast;409 toast 含
  「仍被路由链引用」与 `intent、generation` 任务名且供应商保留;500 通用错误 toast;
  viewer 角色看不到删除入口(AFP-002 既有守卫,FinalPolish 回归绿)。

## 5. 边界确认

- 无级联删除、无路由引擎/Schema 重设计、无 Admin 宽改、认证未弱化、未触生产;
- 未动 #21/#34/#45/#26–#31;未并 main、未部署;
- **引用供应商删除执行零突变**(后端 409 路径无任何写操作,并有测试断言路由与供应商原样)。
