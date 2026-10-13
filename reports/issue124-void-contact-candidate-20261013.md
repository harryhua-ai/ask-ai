# Issue #124 Candidate Snapshot — Admin 错误联系方式可审计作废与线索漏斗无效计数

- 分支:`agent/124/bef87a7c`(base main `0b60f29`)
- 工程提交:`3024c84` feat(issue-124): auditable void of mis-captured sales lead contacts(15 文件,+845/−32)
- 本报告为 docs-only 提交,Candidate SHA 以 `ght preserve` 记录的分支 HEAD 为准(含本报告)
- Contract digest:`c35e9c9eec769367db44664b0717b2cc6e5336c4f2af0466e4237d4a608734e9`

## AC 对照

### AC1 — 已授权管理员明确确认后作废;保存操作人/时间/理由;幂等;不误改其它线索 — [x]

- `POST /api/admin/leads/{id}/void-contact` 仅 admin(`require_role("admin")`;editor/viewer 403):
  `backend/api/admin/leads.py` `void_lead_contact` + `AdminDep`。
- 明确确认:`VoidContactRequest` 强制 `confirm=true`(field_validator 拒绝 false/缺失)+
  `reason` 必填非空(strip 后非空,1..500)→ 缺任一 422。
- 审计:首写作废写 `contact_voided_at / contact_voided_by(操作人 email)/ contact_voided_reason`
  四列;重复提交直接返回现状,首写审计不被覆盖(首写优先幂等)。
- 目标性:仅按主键改写本行。
- 证据:`tests/api/admin/test_leads.py` — `test_void_contact_requires_auth`(401)、
  `test_void_contact_admin_only`(403 + 数据未变)、`test_void_contact_requires_confirm_and_reason`
  (4×422)、`test_void_contact_saves_audit_and_idempotent`(审计四列 + 二次提交审计不变 +
  bystander 线索零误改)、`test_void_contact_not_found_and_no_contact`(404×2 / 409)。
- UI:`admin/src/pages/SalesLeads.tsx` 破坏性「标记无效」入口仅 admin 且仅对有效在档联系方式
  开放;对话框二次确认,理由为空时确认按钮禁用。

### AC2 — 作废不再计入有效视图/有效联系数;漏斗单独统计;真实有效不受影响 — [x]

- 列表:`_serialize.has_contact = bool(contact_value) and not contact_voided`;
  `contact=with` 服务端排除已作废;新增 `contact=voided` 审计视图(与 with/without 三态互斥
  完整划分)。
- 漏斗:`backend/api/admin/business.py` `contactable` 排除作废;新增 `leads.contact_voided`
  单独计数;admin BusinessOverview 侧栏展示「已作废联系方式」(>0 时)。
- 聚合防复活:`backend/services/lead_service.py` `apply_lead_turn` 靠「contact_value 在档不
  覆盖」守卫,作废记录不会被自动聚合改写/复活(换号码重写与重新伪装两条路径均封死)。
- 证据:`test_voided_lead_list_and_filter_semantics`(with 排除、voided 可见、has_contact=false)、
  `test_funnel_counts_voided_separately`(contactable 恰好减一、contact_voided≥1、真实有效
  对照行不受影响)、`tests/services/test_lead_service.py::test_voided_contact_not_overwritten_
  or_resurrected`。UI:`admin/tests/SalesLeads.test.tsx` 已作废徽章/审计面板/入口收缩用例。

### AC3 — PII/权限边界不放宽;操作可追溯;旧记录不被自动聚合伪装有效 — [x]

- 未认证 401、editor/viewer 403 且数据零改写(见上)。
- 列表视图永不回 `contact_value` 原文(测试断言原文不出现在列表响应文本);原文仍只经授权
  只读详情出库;作废后详情保留原文 + 作废审计(必要历史,Contract 禁止不可恢复擦除)。
- 模型/迁移:`sales_leads` +4 加性列,存量行零回填(contact_voided=false);启动期幂等守卫
  (catalog 探测稳态零 DDL,有界 lock_timeout)+ 独立迁移脚本
  `scripts/migrate_add_sales_lead_contact_void.py`(登记 `deploy/prod/migrations.json`)。
- 证据:`tests/db/test_migrate_sales_lead_contact_void.py`(legacy 拆列 → 补列 → 幂等重跑
  no-op,真实 Postgres 一次性库)。

## 验证数字(本 worktree 实跑)

- `tests/db/test_migrate_sales_lead_contact_void.py`:1 passed(0.46s)
- `tests/services/test_lead_service.py`:13 passed(4.80s,含新增作废不复活用例)
- `tests/api/admin/test_leads.py`:15 passed(1.77s,含 6 个 #124 新用例)
- 邻接回归 `test_analytics_business.py + test_ask_lead_flow.py + test_init_db_lock_safety.py
  + test_models.py`:18 passed(7.26s)
- admin vitest:`SalesLeads.test.tsx` 7 + `BusinessOverview.test.tsx` 6 = 13 passed(1.19s)
- `tsc -b`:0 错误;迁移脚本 `uv run python -c "import ..."` OK
- ruff:改动文件仅 2 条**预存**告警(session.py import 排序、test_leads.py `_mk_lead` C408),
  均位于本次 diff 未触碰的行,CI 亦不强制 ruff,未越契约修线。

## 已知限制

- 历史生产处置:#116 所述 11 条存量记录的逐条复核与作废属运营动作,须待本能力过验并取得
  生产变更授权后,由授权管理员经同一可审计流程执行(本 Candidate 不含任何生产写入)。
- `contact=voided` 审计筛选已服务端可用;列表页暂未加独立筛选开关(列表默认视图已含作废
  徽章 + 详情审计面板,满足可观测;如 A 评审需要可后续补)。
- 已知基线失败(非本面,未触碰):admin `DataSources` G001、`test_gap_export`×2、
  `test_gap_observation`。
- `tests/api/admin/` 整目录并发跑存在互相污染(历史问题),本次全部按单文件 + timeout 实跑。
