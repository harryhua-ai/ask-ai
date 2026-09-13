# v1.6.3 Design Remediation 执行报告(Role A 裁决后 — 20 项 A 类强制修复)

**执行 ID:** v163-design-remediation-20260913
**裁决输入:** `/Users/harryhua/Documents/GitHub/ask-ai-acceptance/v163-design-audit-20260913/DESIGN-ACCEPTANCE-AUDIT.md`(Role A:20 项 A 类 IMPLEMENTATION DEFECT 全部强制修复;授权有限呈现收敛;23 项 C 类维持 PRODUCT GAP 不实现)
**起点:** branch `remediation/v163-design-20260913` @ `34c7d5b063ada48394fbde3eb07bb9ddb4d20bbb`(integration candidate,零改写入基)
**Candidate SHA:** 见本文末尾 git 记录(提交即 candidate;push 至 `origin/remediation/v163-design-20260913`)
**视口:** 1536×1024 @ deviceScaleFactor 1(Chromium for Testing 1228,与审计同规格;真实登录 admin@camthink.ai@本地)
**数据层:** 本地 docker ask-ai-local-postgres-1@5432 db=ask_ai;AUDIT-FIXTURE(audit-fixture.sql)已核对在库并全量有效(隔离标记 sdk-docs-auditfx / cafef00d- / md5('auditfx-*'));生产 43.132.189.162 全程零触碰
**端口:** backend 8104 / vite 5184(本 agent 专属;8103/5183 未动)

---

## 1. Changed files(13,全部 admin 呈现层/测试;零后端 diff)

```
admin/src/components/ui/badge.tsx                        A-P1-01/02 + info 徽章变体(A-P2-02 用)
admin/src/lib/dataSourceOps.ts                           toneVariant:unclassified→warning(A-P1-02)
admin/src/lib/sourceEditorModel.ts                       +sourceTypeLabel 运营呈现词表(A-P1-05)
admin/src/pages/DataSources.tsx                          A-P1-01..08(徽章/密表单行/单⋯/类型词/紧凑筛选/›/同步全部入菜单)
admin/src/pages/DataSourceDetail.tsx                     A-P2-01..05、A-P3-01/02、A-P1-03 同口径、A-P1-07
admin/src/components/dataSources/SyncActivityPanel.tsx   A-P4-01(98.7% 一位小数;样本注记入 title)
admin/src/pages/Analytics.tsx                            A-B2-01/02/03/04(标题深蓝/圈形图标/页码按钮组/侧板 460px+bullets)
admin/tests/DataSources.test.tsx                         受影响用例更新至新呈现(菜单入口/类型词/title 化副行)
admin/tests/dataSources/DataSourcesConvergence.test.tsx  同上 + 新增 A 类锁定用例 ×8
admin/tests/dataSources/DataSourceDetail.test.tsx        受影响用例更新(正常徽章/Wiki/真相行头 title)
admin/tests/dataSources/DataSourceDetailConvergence.test.tsx 同上 + 新增 A 类锁定用例 ×7
admin/tests/TechInsightConvergence.test.tsx              新增 A-B2-01..04 锁定用例 ×5
admin/tests/FinalPolish.test.tsx                         G010 写操作保留用例改经页头 ⋯ 菜单重证
```

`git diff 34c7d5b..HEAD --stat`:13 files changed(backend/tests(python) 零文件)。

## 2. 20 项 A 类逐项 closure 表

证据目录:`/Users/harryhua/Documents/GitHub/ask-ai-acceptance/v163-remediation-20260913/`(BEFORE=审计 current/ 副本;AFTER=本轮重摄;并排索引=side-by-side-index.html)。

| # | 缺陷(audit §4) | 修复 | 文件 | BEFORE→AFTER 证据 | 复核 |
| --- | --- | --- | --- | --- | --- |
| A-P1-01 | 红系徽章实底#ef4444+白字 → 淡彩底彩字 | Badge destructive 变体 → `bg-red-50 text-red-600`;计算样式实测 bg rgb(254,242,242) fg rgb(220,38,38) | badge.tsx | BEFORE/01 → AFTER/01(01-zoom-first-row) | MATCH(像素采样) |
| A-P1-02 | 待分类灰 → 琥珀 | Badge warning → `bg-amber-50 text-amber-600`;toneVariant unclassified→warning(列表/详情同一 token) | badge.tsx、dataSourceOps.ts | BEFORE/01 → AFTER/01 | MATCH(rgb 255,251,235 / 217,119,6) |
| A-P1-03 | 行高 67px+URL 副行 → ~36-40px 单行 | 名称列副行删除(收进行名 title);`[&_td]:!py-1.5 [&_th]:!h-9`;操作按钮 h-7 不撑行;详情知识表 doc_source_id 同口径 | DataSources.tsx、DataSourceDetail.tsx | BEFORE/01 → AFTER/01 | MATCH(实测行高 41px) |
| A-P1-04 | 操作列 4 按钮 → 单 ⋯ | 详情/同步/编辑 + 既有 查看可观测性/重试删除/删除 全部收进 ⋯ DropdownMenu;零授权能力删除 | DataSources.tsx | BEFORE/01 → AFTER/01 | MATCH |
| A-P1-05 | 类型词 → 文件系统/Wiki/网站/商城 | 新增 `sourceTypeLabel()` 运营呈现词表(列表/详情共用);编辑抽屉保留 TYPE_LABELS(既有编辑器权威);source_type 真值零变更 | sourceEditorModel.ts、DataSources.tsx、DataSourceDetail.tsx | BEFORE/01 → AFTER/01 | MATCH |
| A-P1-06 | 大号筛选 → 紧凑 | 状态/类型 select h-8 px-2 | DataSources.tsx | BEFORE/01 → AFTER/01 | MATCH |
| A-P1-07 | 面包屑「/」→「›」 | 列表+详情(三级 配置›数据源›{源};返回列表由面包屑承担) | DataSources.tsx、DataSourceDetail.tsx | BEFORE/01,02 → AFTER/01,02 | MATCH |
| A-P1-08 | 「同步全部」按钮 → 参考仅一枚主按钮 | 收进页头 ⋯ 菜单(更多页操作);功能保留(G010 用例重证) | DataSources.tsx | BEFORE/01 → AFTER/01 | MATCH |
| A-P2-01 | 「部分成功」纯文本+绝对时间戳 → 蓝链接+chevron | 链接态按钮(data-testid=partial-result-link),点击 scrollIntoView 至既有 #sync-activity 区;无新路由语义 | DataSourceDetail.tsx | BEFORE/02(zoom-meta) → AFTER/02 | MATCH(F4 真实点击滚动 PASS) |
| A-P2-02 | 服务列 在服/不在服(红) → 正常(绿)/不完整(蓝)/— | serving=true→正常(success);serving=false 且有现行版本→不完整(info 蓝);无现行版本→—(灰);真值仍来自 serving | DataSourceDetail.tsx、badge.tsx | BEFORE/02 → AFTER/02 | MATCH |
| A-P2-03 | 更新时间双格式 → 单格式 | RelativeTime 仅相对时间,精确 ISO 收进 title(全页 helper 级统一) | DataSourceDetail.tsx | BEFORE/02(zoom-meta) → AFTER/02 | MATCH |
| A-P2-04 | banner 裸「!」→ 红圈 ⚠ | `rounded-full bg-red-600 text-white` 圆形 ⚠ 图标 | DataSourceDetail.tsx | BEFORE/02 → AFTER/02 | MATCH |
| A-P2-05 | 页头 编辑/返回列表 双按钮 → 单 ⋯ | 页头 ⋯ 菜单(编辑/返回列表项保留) | DataSourceDetail.tsx | BEFORE/02 → AFTER/02 | MATCH(F5 真实点击 PASS) |
| A-P3-01 | 展开诊断表级附录 → 行下原地展开 | 真相行移入 docs.map,紧跟匹配行(doc_source_id 匹配);行头名称=chevron 展开(⌄/⌃ + aria-expanded);真相按钮保留 | DataSourceDetail.tsx | BEFORE/03 → AFTER/03 | MATCH(Contact Us 行下原地展开,与参考同构) |
| A-P3-02 | 「生效自」裸 ISO → 人类化 | formatSyncTime 本地化 + 完整 ISO 入 title | DataSourceDetail.tsx | BEFORE/03 → AFTER/03(生效自 09-03 01:33) | MATCH |
| A-P4-01 | 可靠性整数% → 98.7% | `(rate*100).toFixed(1)%`;样本注记(近30天 N 次 + 分子分母)保留在 title;无数据保持诚实态(证据不足/仅 N 次) | SyncActivityPanel.tsx | BEFORE/04 → AFTER/04 | MATCH(实测 98.7%=77/78 权威公式) |
| A-B2-01 | 技术洞察标题近黑 → 深蓝 rgb(4,3,108) | h1 style color rgb(4,3,108)(与参考采样精确一致,与主操作蓝区分) | Analytics.tsx | BEFORE/11 → AFTER/11 | MATCH(计算样式=rgb(4,3,108)) |
| A-B2-02 | 状态徽章裸圆点 → 圈形图标 | 需要处理=ⓘ(红圈 i)/已解决=✓(绿圈勾)svg;观察中不存在未造 | Analytics.tsx | BEFORE/12(zoom-badges) → AFTER/12 | MATCH |
| A-B2-03 | 分页「1 / 2」→ 页码按钮组 | ‹ 1 2 › 页码按钮+当前页高亮(aria-current)+既有 条/页;单页不造按钮组(诚实简洁) | Analytics.tsx | BEFORE/12(zoom-footer) → AFTER/12b(12 条→2 页) | MATCH |
| A-B2-04 | 侧板 390→~460px + bullets 偏淡 | w-[460px];典型问题 bullets `marker:text-[var(--t1)]` 文字升 t1;布局随宽重排不破(AFTER/13) | Analytics.tsx | BEFORE/13 → AFTER/13 | MATCH |

**20/20 closure 确认:全部修复→渲染→比对→复核完成;Visual DEFECT = 0。**

## 3. Fixture 清单(与审计附录 A 一致,重放核对)

| 族 | 断言(UI=API=DB) | 本轮核验 |
| --- | --- | --- |
| FX-1 | 第 6 源 sdk-docs-auditfx + 1,204 账本;页脚「共 6 个数据源」;知识数量 1,204;需处理 — | ✓(AFTER/01;attention-summary ledger 1204/attention 0) |
| FX-2 | store-woo 77 success+1 partial=78 → 98.7%;最近结果=部分成功 | ✓(API rate 0.9872 / PG 77|1 / AFTER/04) |
| FX-3 | b2a00001→2h/3h 近因刷新;队列+侧板相对时间 | ✓(AFTER/12,13:3 小时前,数据真值随窗口自然推移) |
| FX-4 | 5 个 cafef00d 聚类:拒答/知识缺失/服务知识不完整/低相关/未分类 × 需要处理/已解决;total 12 第 2 页 | ✓(API total 12 page2;AFTER/12 五原因词全渲染;无 观察中) |
| FX-5/6 | help-center/sdk-docs 30d 内 3 次 success → 正常(绿) | ✓(AFTER/01:Help Center/SDK Docs 正常) |
| 既有 B1 seed | store-woo 8 文档 2 missing_candidate+1 无现行 → banner 3 项 | ✓(AFTER/02:有 3 项知识需要处理=PG lifecycle 计数 2+1) |
| 显式不 seed | 观察中/部分服务分数/逐文档恢复/逐文档内容类型/logo/下次同步/用户聚合 | ✓(零伪造,AFTER 全部缺席) |

隔离:全部 fixture 行带 `sdk-docs-auditfx`/`cafef00d-`/`md5('auditfx-*')` 标记;本轮 PG 写操作仅 F1 功能链触发的一次 website 源手动同步(既有授权动作链,本地 dev 数据)。

## 4. Before→After 截图映射

| 状态 | BEFORE(审计 current/) | AFTER |
| --- | --- | --- |
| P1 列表 | 01-P1-source-list.png(+zoom-status-badges) | 01-P1-source-list.png(+01-zoom-first-row) |
| P2 详情 | 02-P2-source-detail-woo.png(+zoom-identity/zoom-meta) | 02-P2-source-detail-woo.png(+02-zoom-identity) |
| P3 展开行 | 03-P3-expanded-row.png | 03-P3-expanded-row.png |
| P4 同步活动 | 04-P4-sync-activity.png | 04-P4-sync-activity.png |
| P5 编辑抽屉 | 05-P5-edit-drawer.png | 05-P5-edit-drawer.png |
| P2 桶过滤 | 10-P2-attention-filter.png | 10-P2-attention-filter.png |
| B2 壳/技术性能 | 11-B2-shell-tech-tab.png | 11-B2-shell-tech-tab.png |
| B2 队列 | 12-B2-answer-gaps-queue.png(+zoom-badges/zoom-footer) | 12-B2-answer-gaps-queue.png + 12b-B2-answer-gaps-pagination.png |
| B2 选中+侧板 | 13-B2-row-selected-panel.png | 13-B2-row-selected-panel.png |
| 侧板 4 Tab | 14/15/16/17-B2-panel-*.png | 14/15/16/17-B2-panel-*.png |

## 5. Final Visual Difference Ledger(全新重验重分类;非豁免口径)

维度沿用审计 §3 十四维。终分类恰好一个:MATCH / APPROVED ABSENCE(PRODUCT GAP) / REFERENCE CONFLICT(Role A 已裁) / DEFECT。

### 5.0 共享 chrome
| ID | 项 | 终分类 |
| --- | --- | --- |
| SC-1..SC-5 | 顶栏身份/品牌区/主操作蓝/侧栏选中(PNG1 语法)/分组导航 | MATCH(重验) |
| SC-6 | 面包屑分隔符 | MATCH(A-P1-07 修复) |
| SC-7 | 侧栏底色 PNG1 深 vs PNG2 浅 | **REFERENCE CONFLICT(Role A 已裁;实现维持 PNG2 浅色)** |
| SC-8 | 顶栏全局日期范围选择器 | APPROVED ABSENCE(PRODUCT GAP;页内 TimeFilter 等价) |
| SC-9 | 侧栏 帮助中心/收起菜单/系统 分组 | APPROVED ABSENCE(PRODUCT GAP;#52 冻结清单) |
| SC-10 | LoginChat 悬浮球 | N/A(baseline 既有,两参考未描绘 chrome 注记) |

### 5.1 B1 P1 列表
M1 结构/M2 徽章四态/M3 需处理一等列/M4 千分位/M5 交互:MATCH(重验)。
A-P1-01..08:全部 **MATCH**(§2 closure)。
B1 fixture 族(FX-1/2/5/6):B(已落地断言)。

### 5.2 B1 P2 详情
M1 层级/M2 查看需处理/M3 桶注记:MATCH(重验)。
A-P2-01..05:**MATCH**。
| ID | 项 | 终分类 |
| C-B1-01(JD5) | Woo 品牌图 | APPROVED ABSENCE(后端无 logo 权威;呈现=授权首字母块「w」) |
| C-B1-02 | banner 原因句 polished 文案 | APPROVED ABSENCE(权威桶事实转述;「引用重验」无权威来源) |
| C-B1-03(JD8) | 逐文档内容类型(商品/页面/文档) | APPROVED ABSENCE(呈现源级 商城) |
| C-B1-04(JD9) | 部分服务分数 10/12 | APPROVED ABSENCE(服务列=二值 serving 投影) |
| C-B1-05(JD10) | 行级 处理/重新处理 | APPROVED ABSENCE(行头 chevron+真相=既有授权证据入口) |
| C-B1-06(JD12) | 自动恢复计数注记 | APPROVED ABSENCE |
| C-B1-07(JD13) | 修复后验证卡 | APPROVED ABSENCE |
| C-B1-08(JD15) | 下次同步倒计时 | APPROVED ABSENCE(同步周期承载) |

### 5.3 B1 P3 展开行
M1 要素/M2 诚实注记:MATCH。A-P3-01/02:**MATCH**。P3-C1..C4(10/12、恢复注记、重新处理、验证卡):APPROVED ABSENCE。

### 5.4 B1 P4 同步活动
M1 字段组/M2 最近结果与活动:MATCH(重验)。A-P4-01:**MATCH**。P4-C1(下次同步)/P4-C2(事件粒度超集):APPROVED ABSENCE。P4-N1(浮层卡 vs 页内 section):MATCH(ADAPT,记录在案)。

### 5.5 B1 P5 抽屉
M1 抽屉语法:MATCH。P5-C1(JD17/18 字段集):APPROVED ABSENCE(既有编辑器=权威超集;类型词呈现映射至运营词表)。

### 5.6 B1 P6/P7
整个状态无实现:APPROVED ABSENCE ×2(JD19/20;词表缺席证据=审计 06 html,维持)。

### 5.7 B2
M1..M10:MATCH(重验,含原因 tinted ADAPT、选中态、诚实缺席态)。
A-B2-01..04:**MATCH**。
| C-B2-01(J1/J12) | 原因词表超集(内容过期/检索异常/生成异常/引用异常/内容冲突/内容缺失) | APPROVED ABSENCE(权威词表子集+未分类如实) |
| C-B2-02(J2) | 观察中 | APPROVED ABSENCE |
| C-B2-03(J3) | 导出相关对话 CSV | APPROVED ABSENCE(授权深链 查看相关对话) |
| C-B2-04(J4) | 内容已补充,开始观察 | APPROVED ABSENCE |
| C-B2-05(J5) | 涉及 17 个用户 | APPROVED ABSENCE |
| C-B2-06(J6) | 相关数据源 Woo 外链 | APPROVED ABSENCE |
| C-B2-07(J7) | 问题描述诊断式叙事 | APPROVED ABSENCE(权威字段事实汇总) |
| C-B2-08(J8) | 队列主题式短语 | APPROVED ABSENCE(代表问句=聚类不变量) |
| C-B2-09(J12) | depicted 重演边界 | APPROVED ABSENCE(并入 C-B2-01) |

**终分类分布:MATCH = 33(审计)+ 20(A 类修复后转 MATCH)= 53;APPROVED ABSENCE(PRODUCT GAP)= 23;REFERENCE CONFLICT = 1(SC-7 侧栏明暗);DEFECT = 0。**

> 残余次要呈现差异(全部计入 MATCH 带内,记录不豁免):①行高 41px vs 参考 ~36px(带内);②数据行内容/计数为本地 fixture 真值形状(B 类,非像素复刻);③功能链触发后的 排队中 运行态徽章(运行时真值,非参考 depicted 状态);④P2 品牌块=蓝色首字母「w」(授权呈现选项)。

## 6. Functional Regression Gate(呈现变更零真值破坏)

**FUNCTIONAL DEFECT = 0。** 三角(日志 `logs/functional-api.txt` / `functional-pg.txt` / `functional-ui-clicks.log`):

| 断言 | API(JWT curl) | PG(psql 只读) | UI(真实渲染/点击) |
| --- | --- | --- | --- |
| source counts/status | 6 源:help-center success/partner-portal failed/sdk-docs-auditfx success/store-woo partial/website 无/wiki failed | data_sources 6 行同值 | AFTER/01 共 6 个数据源,状态徽章同权威值 |
| attention | store-woo 3(2 missing+1 无现行);sdk 0/1204 | documents lifecycle 6 active+2 missing_candidate | AFTER/02 banner 有 3 项知识需要处理 |
| 可靠性 | source-health store-woo 77/1/78 → 0.9872 healthy | sync_log 30d: success 77, partial 1 | AFTER/04 同步可靠性 98.7% |
| 真相/lifecycle/版本/生成 | /documents + /document-truth 权威读面 | 文档版本链/generation 行 | F3 行头展开真相 PASS;生成真相 #900001 呈现 |
| sync runs/activity | sync_runs+sync_log 读面 | 同上 | AFTER/04 时间线 红/琥珀/绿 异常优先;F1 ⋯菜单触发同步 POST 受理 PASS |
| answer-gaps | total 12;原因五词×状态两态;page2 存在 | question_clusters 12;cafef00d 5 簇 | AFTER/12 徽章全渲染;F8 第 2 页真实翻页 PASS |
| 双下钻 | — | conversations 关联 | F9 技术→/data-sources/store-woo 真实点击到达 PASS;F10 缺口→/conversations?q= 预填命中真实到达 PASS;F7 深链 href PASS |
| 授权操作链 | POST /sync 受理(F1) | sync_log 新行(website 源,本地) | 编辑抽屉预填(F5/F5b)PASS |

12/12 UI 功能点击 PASS;权威真值唯一来源=后端读面,前端零推导变更(本轮仅呈现映射/格式/收纳,零 hook/零 API 层变更)。

## 7. Engineering Gate

| 门 | 结果 | 分类 |
| --- | --- | --- |
| 后端 pytest 全量(串行,TEST_DATABASE_URL=ask_ai_test,HF_HUB_OFFLINE=1) | **2496 passed / 4 failed / 8 skipped**(`logs/pytest-full.log`) | 4 失败全部 **BASELINE**:tests/scripts/test_recovery_semantics.py::a3/b1/b2/b3 — 在未改动 base candidate 34c7d5b(ask-ai-v163-int worktree,零 diff)复跑同样失败(b1/b2/b3 全文件复跑 3 failed;a3 单测复跑 3/3 failed);且本轮 diff 零后端文件,回归不可能。与基线 2501/7/0 总量一致(2508)。 |
| PA 套件 tests/project_automation/ | **114 passed**(`logs/pytest-pa.log`) | PASS |
| admin vitest 全量 | **449 passed / 449**(基线 429 + 新增 20 项 A 类锁定用例;受影响 30 用例更新至新呈现) | PASS |
| tsc | **0 error** | PASS |
| npm run build | ✓ built(`logs/npm-build.log`) | PASS |
| ruff(改动文件) | 本轮零 .py 改动;backend/tests/scripts 全量 ruff 计数与 base 完全一致(301 项预存在,`git diff` 可证) | PASS(无改动面) |

## 8. Scope audit

- **零后端语义变更**:`git diff 34c7d5b..HEAD -- backend tests scripts` 为空;20 项修复全部呈现层(badge token/呈现映射/布局/收纳/格式化)。
- **零 PRODUCT-GAP 语义实现**:观察中/导出 CSV/开始观察/用户数/来源关联/主题短语/原因词超集/下次同步/知识设置 Drawer/高风险 Modal/行级修复/部分服务分数/逐文档恢复计数/修复验证卡/逐文档内容类型 — 全部缺席(AFTER 截图+vitest Forbidden 断言维持)。
- **零生产触碰**:生产 43.132.189.162 全程零网络访问;全部数据操作限于本地 docker PG。
- **fixture 与生产行为零混淆**:AUDIT-FIXTURE 全带隔离标记;测试库 ask_ai_test 与 dev 库分离。
- **不改分类**:23 项 C 类按 Role A 裁决原样保持 APPROVED ABSENCE,未重新解释;1 项 REFERENCE CONFLICT(SC-7)按已裁维持。

## 9. Residual risks

1. `test_recovery_semantics` 4 用例在本地环境常失败(base 同败)——后续 owner 应在 CI 规格环境复核;与本 candidate 无因果。
2. 行高 41px 与参考 36px 的 ~5px 差异在带内;若后续要求逐像素 36px,需进一步压缩 ⋯/真相按钮高度(呈现层,可独立迭代)。
3. F1 功能链在本地 dev 库触发了一次 website 源真实同步(授权动作),会在本地数据留下同步记录;不影响 fixture 断言族。
4. 侧板 460px 在 1280 以下视口的压缩表现未在参考口径内(参考 1536),未做额外断点收敛。
5. `sourceTypeLabel` 运营词(Wiki/文件系统/网站)若后续接通逐文档内容类型契约(C-B1-03),需同步复审该映射边界。

## 10. git candidate

见分支 `remediation/v163-design-20260913` 推送记录;commit message 含本报告路径与三门结论摘要。
