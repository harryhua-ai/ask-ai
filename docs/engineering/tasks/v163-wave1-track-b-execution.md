# V1.6.3 Wave 1 — Track B 执行报告(Source Editor Conformance:DEF-A2/A3/A4)

- **分支**:`track/v163-b-drawer`(worktree `/Users/harryhua/Documents/GitHub/ask-ai-v163-wb`)
- **基线**:HEAD 起点 = `d613e6aab787110e6c7839f92dbc28611b79ee7e`(FINAL_PREP_BASE,wave0b 冻结 tip);父链 `7e3e71c → c016d50 → acc6756 → f83740c → d613e6a`;merge-base(HEAD, 7e3e71c)=7e3e71c 复核 PASS(共同基线,无混合基线)。
- **合同**:docs/engineering/tasks/v163-reference-remediation/track-b-contract.md + remediation plan §6 Track B 授权包 + matrix-DS-P5-P6-P7.md DS-P5-02/04/05 行;硬参考 PNG = /tmp/v163-audit-refs/data-source-operations-original.png 面板5(编辑数据源 Drawer)。
- **verdict**:CANDIDATE READY

## 0. 在制工作继承说明(被中断执行接续)

本分支存在前次被中断执行的合法在制工作(未提交改动 3 文件),本轮**复核后保留并完成**,未推倒重来:

| 文件 | 状态 | 复核结论 |
|---|---|---|
| `admin/src/components/dataSources/SourceEditorDrawer.tsx`(+44/−8) | M | 逐项对照合同通过:DEF-A2 label 收敛(真值仍 `product`)、DEF-A3 `disabled={!!editing}` 真 disabled 属性(非 CSS 伪装;PUT payload type 真值不变)、DEF-A4 Radix Switch + 逐字说明(真值仍 `enabled`,`setValue` 映射);onSubmit/PUT 载荷与端点零变化(diff 证实仅 label/控件语法/注释/id 关联) |
| `admin/tests/setup.ts`(+12) | M | ResizeObserver stub,仅 `typeof globalThis.ResizeObserver === "undefined"` 时注入(Radix Switch 在 jsdom 下的测试基建依赖);受保护不覆盖宿主实现;零产品影响,保留合理 |
| `admin/tests/dataSources/SourceEditorDrawerConformance.test.tsx`(新) | ?? | 9 用例覆盖 DEF-A2/A3/A4 + PUT 真值不变断言;mock 面与 `useDataSources` 导出面一致;保留 |

继承后缺口 = 无(实现/测试/基建三件齐);本轮职责 = RED 记录 → GREEN 验证 → 回归 → 运行时验收 → 证据 → 报告。

## 1. 实现范围(仅冻结三项;U-5 已裁)

| DEF | 矩阵 ID | 实现 | 真值 |
|---|---|---|---|
| DEF-A2 | DS-P5-02 | 「产品线」label →「名称」+ 必填星号(`<span class="text-destructive">*</span>`),label htmlFor 关联 `ds-product` | `product` 字段零变更 |
| DEF-A3 | DS-P5-04(U-5) | edit 既有源:`<select id="ds-type" disabled={!!editing}>`(真 disabled 属性 + `disabled:opacity-50`);create 态类型选择保留可选 | PUT `type` 仍来自表单(既有源=原类型,值不可变) |
| DEF-A4 | DS-P5-05 | 「状态/启用」checkbox → 「自动同步」Radix Switch(`#ds-auto-sync`)+ 逐字说明「开启后，系统将按设定周期自动同步。」 | `enabled` 真值映射零变更(toggle → `setValue("enabled", v)`) |

P6/P7 属 Track C,零触碰;零 hook/API 层变更;零后端(`git diff HEAD -- backend/` = 0 行)。

## 2. RED 记录(继承工作先证失败形态)

对在制测试做 RED 还原验证:`git stash push` 仅 `SourceEditorDrawer.tsx` 后运行:

```
npx vitest run tests/dataSources/SourceEditorDrawerConformance.test.tsx
→ Test Files  1 failed (1)
   Tests  8 failed | 1 passed (9)
```

失败形态 = DEF 三项呈现缺失(名称 label 查找失败/类型未 disabled/switch 角色不存在等);恢复 stash 后同命令 **9/9 GREEN**。(前次执行中断于实现后、验证前,故直接运行即绿;本轮补做还原 RED 证据。)

## 3. 各门验证结果

| 门 | 结果 | 判定 |
|---|---|---|
| vitest 全量 | **56 文件 462/462 passed**(基线 453 + 新增 9) | PASS |
| vitest DataSources 全套 | 9 文件 146/146 passed | PASS |
| tsc(`--noEmit`) | 0 errors | PASS |
| build(`vite build`) | ✓ built in 2.15s | PASS |
| pytest 相关子集(后端零改动回归证明) | `tests/api/admin/test_data_sources{,_c9_edit,_c10,_upload}+test_data_source_{workspace,deletion_lifecycle,attention_summary}` **65 passed / 0 failed**(TEST_DATABASE_URL=postgresql+asyncpg://…/ask_ai_test_b) | PASS(零回归) |
| 后端 diff | 0 文件 0 行;OpenAPI 无由变化(零 .py 改动) | PASS |

## 4. Runtime 验收(真实栈:backend 8122 + vite 5222 + 本地 PG ask_ai;1536×1024 @1x 真实登录 admin@camthink.ai)

### 4.1 编辑链(UI→PUT→DB→GET→UI 三角)

目标源 `store-woo`(woocommerce):

1. 列表行 ⋯ → 编辑 → 抽屉呈现:类型「商城」**灰态 disabled**、名称「名称 *」红星、自动同步 Switch **on** + 逐字说明;
2. 改名称 `WooCommerce → WooCommerce-B163` + toggle 关 → 保存 → **PATCH /api/admin/data-sources/store-woo**(真实网络请求捕获);
3. **DB 真值链(SQL 逐次实测)**:

```sql
select enabled from data_sources where id='store-woo';
-- UI toggle off + 保存后: f
-- UI toggle on  + 保存后: t
select id,type,product,enabled,sync_interval from data_sources where id='store-woo';
-- store-woo | woocommerce | WooCommerce-B163 | t | 6h
```

   type/sync_interval/config 全程不变(DEF-A3 immutable 语义);名称与 enabled PUT 真值落库;
4. 重开抽屉:名称预填 `WooCommerce-B163`、Switch 呈 off(GET 回读=DB 真值)、类型仍 disabled——UI 反映真实持久态。

### 4.2 create 链(type 可选生效;WB_ 标记本地源)

- 添加数据源 → 类型 select **enabled**,切换 `web_crawl` 成功且类型化字段(网站地址)呈现 → 填名称 `WB_TRACKB_20260913` → 创建 → **POST /api/admin/data-sources**;

```sql
select id,type,product,enabled from data_sources where product like 'WB_%';
-- WB_TRACKB_20260913-528c9900 | web_crawl | WB_TRACKB_20260913 | t
```

- create 时类型选择真实生效(后端按所选 type 建源),id=product+短hash 自动生成。

**本地 DB mutation 声明(验收 SQL 全文见 §4.1/4.2)**:仅本地 PG `ask_ai` 库两行——`store-woo.product` 改名与 `enabled` 两轮切换(终态 t),新建 `WB_TRACKB_20260913-528c9900` 一行(WB_ 标记,留作 SQL 记录);零生产数据、零 fixture 注入代码。

## 5. 视觉证据(5 张,1536×1024 @1x)

目录:`/Users/harryhua/Documents/GitHub/ask-ai-acceptance/v163-wave1-b-20260913/`

| 文件 | 内容 |
|---|---|
| `v163-b-edit-drawer-p5-conformance.png` | 编辑抽屉对照 PNG1 面板5:名称* 星号 / 类型灰态 disabled / 自动同步 toggle on+说明 |
| `v163-b-edit-drawer-auto-sync-off.png` | toggle off 态(说明文案保留) |
| `v163-b-edit-drawer-after-put-reopen.png` | PUT 后重开:持久化真值回读 |
| `v163-b-create-drawer-type-selectable.png` | create 态类型可选(已切 web_crawl,类型化字段呈现) |
| `v163-b-create-drawer-filled.png` | create 态 WB_ 标记名称填写 |

## 6. Scope audit

- `git status --porcelain` = 恰 3 文件(§0 表);累计 diff 仅 `admin/src/components/dataSources/SourceEditorDrawer.tsx`(B-owned)、`admin/tests/setup.ts`(测试基建)、新增 B-owned 测试文件 + 本报告;
- **Ownership violations:NONE**(零触碰 Analytics/analytics/*、tech*/gap_*/analytics.py、DataSourceDetail.tsx、data_sources.py、AnswerGapsTab/GapPanel、Sidebar/Layout);
- **Interface expansions:NONE**(零新端点/零新参数/零 PUT 语义变更/零 hook 层变更);
- **禁止捷径核查**:disabled 为真 `disabled` 属性非 CSS 伪装(vitest `toBeDisabled` + 运行时灰态);PUT payload 逐字段与基线一致(vitest payload 断言 + 运行时 PATCH 捕获);create 态类型选择保留(运行时切换生效)。

## 7. Issue 映射

- 本执行落地后贡献 **#53/#54**(编辑抽屉字段范围)关闭材料:DEF-A2/A3/A4 三条 IMPLEMENTATION DEFECT 清零(矩阵 DS-P5-02/04/05);未直接关 issue(按 planning §6.5,落地后由 issue 责任面收口)。

## 8. STOP 确认

- 未 merge / 未 deploy / 未关 issue / 未新建其他轨道分支 / 未新增豁免类;
- P6/P7(Track C 范围)零触碰;后端零改动;
- 运行时栈(8122/5222)验收完成后停止;
- 候选 = 本报告 commit 后 `track/v163-b-drawer` tip,待 Integration 轨按 merge-base==FINAL_PREP_BASE_SHA 核验合并。
