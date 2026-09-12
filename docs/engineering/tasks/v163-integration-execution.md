# v1.6.3 Integration — 组合树执行报告

**Track:** Integration(Role A 接受 B1/B2 后的组合执行 agent,独立验证)
**Worktree:** `/Users/harryhua/Documents/GitHub/ask-ai-v163-int`
**Branch:** `integration/v163-20260913`
**Starting fresh origin/main SHA:** `5c501914636ae274bdf54896e3decf86c4584e12`(`5c50191`,v1.6.2 生产验收基线,零漂移复验)
**Design baseline:** KB-OPS-V163-002(DESIGN_RECOVERY_REVIEW_V002.md,FROZEN)
**Hard visual references:** 两张 ORIGINAL PNG(执行 agent 已用 Read 工具亲自重读后才允许渲染截图)
**Issues:** #52–#60(只读引用;零关闭、零改写)
**Viewport:** 1440×900 @ deviceScaleFactor 1(全部截图统一)
**日期:** 2026-09-13

---

## 1. 结论(三门)

| Gate | 结论 | 依据 |
| --- | --- | --- |
| Engineering Gate | **PASS** | 全量后端 pytest **2501 passed / 7 skipped / 0 failed**(串行,HF_HUB_OFFLINE=1,TEST_DATABASE_URL=ask_ai_test 全 DSN,122.8s);admin vitest **429 passed / 54 files**;`npx tsc -b` **0 error**;`npm run build` **✓**;改动后端文件 ruff **All checks passed**;Project-automation 套件 `tests/project_automation/` **114 passed**(与 v1.6.2 报告 "PA 114" 基线一致) |
| Functional Gate | **PASS**(FUNCTIONAL DEFECT = 0) | 真实组合栈(backend 8103 + vite 5183)上 B1 面与 B2 面 UI ↔ API(curl 带 JWT)↔ 本地 PG 只读 SELECT 三角核对全部 MATCH;既有授权同步动作链全链重证;两条跨轨下钻真实点击到达并附截图(§8) |
| Design Gate | **PASS**(Visual DEFECT = 0;剩余 JUSTIFIED DIFFERENCE 23 项待 Role A) | 21 张组合树真实截图 vs 两张硬参考逐面板独立比对;每处 material difference 恰好一档 MATCH / JUSTIFIED DIFFERENCE / DEFECT(§7);**A/B/C 三项 Integration-owned 共享视觉差异已解决并有逐项 resolution evidence(§4)** |

**Verdict: V1.6.3 INTEGRATION = CANDIDATE READY(JUSTIFIED DIFFERENCE 全部附权威真相证据,待 Role A 逐项裁决;B 侧不自批)**

---

## 2. 精确拓扑与 candidate SHA

```
5c50191 (fresh origin/main,已复验零漂移)
  └─ a6aad77 merge --no-ff B1 @ 336c7f5 (零冲突,20 files)
       └─ b7a8d0b merge --no-ff B2 @ 9e12746 (零冲突,9 files;组合计 30 changed files)
            └─ <INTEGRATION_COMMIT>  feat(admin-ui): v1.6.3 Integration 共享视觉语法收敛(A/B/C)
                 └─ <REPORT_COMMIT>   docs(engineering): v1.6.3 Integration 执行报告
```

- 已接受 candidate 历史(B1/B2 的 reviewed commits 与两个 merge commit)**零改写**,仅在其上追加。
- 最终 candidate SHA = 分支 tip(push 后以 `git rev-parse HEAD` 输出为准,见交付记录)。
- 分支已 push:`git push -u origin integration/v163-20260913`。

---

## 3. 组合 changed-file audit(5c50191..candidate)

既有组合树(两 merge 合计,30 files):B1 20 files(数据源列表/详情收敛 + 只读读面 attention-summary/documents additive 参数 + 编辑抽屉/同步活动组件 + 行为测试),B2 10 files(共享壳 Analytics 收敛 + answer-gaps 只读投影 + gapCause 权威映射 + 行为测试)。清单见 `git diff --name-status 5c50191..a6aad77` 与 `..b7a8d0b`,与本报告附录一致。

**Integration 增量(本 agent 改动,仅 4 个前端共享 chrome 文件):**

| 文件 | 改动 |
| --- | --- |
| `admin/src/index.css` | `--primary` 近黑(0 0% 9%)→ 参考蓝 `221.2 83.2% 53.3%`(#2563eb);`--ring` 同步为参考蓝;可观测性 accent `--acc` 靛蓝 #4f46e5 → 同一参考蓝 #2563eb(消除双蓝分裂,`--acc-t` 随调) |
| `admin/src/components/Layout.tsx` | 顶栏身份区:欢迎语+角色徽章+退出按钮 → 头像(首字母,蓝底)+用户名+角色 chip+chevron 的身份菜单;登出走既有 `useAuth().logout()`+`navigate("/login")`,语义不变 |
| `admin/src/components/Sidebar.tsx` | 品牌区:纯文本 "Ask AI" → 蓝底 LayoutGrid 标识 + "ASK-AI" 粗体;分组(运营/配置)与导航清单零变更 |
| `admin/src/components/ui/dropdown-menu.tsx` | additive 增加 `DropdownMenuLabel` 原语(身份菜单用),既有导出零变更 |

零后端文件改动;零路由增删;零检索/排序/引用/生命周期/generation 语义改动(全量 pytest 通过为证)。

---

## 4. A/B/C 逐项 resolution evidence(Integration-owned 差异,已解决)

> 改动前状态证据:B1 截图 `ask-ai-acceptance/v163-b1-20260913/01-source-list.png`(主按钮近黑、侧栏选中黑色实底)、B2 截图 `v163-b2-20260913/01-tech-shell-tech-tab.png`(顶栏欢迎语 chrome);改动后状态证据:本目录 01/02/03/04 截图。

### A. 共享主操作语法 → 参考蓝(解决 B1 Ledger #4)

- **改动文件:** `admin/src/index.css`(`--primary`/`--ring`/`--acc`)。`components/ui/button.tsx` 的 default variant(`bg-primary`)无需改动——token 收敛后全应用主按钮自动变蓝,这正是"语法统一而非逐页微调"的实现路径。
- **前后对比:** 前 = v163-b1 `01-source-list.png` 的黑色「+ 添加数据源」与黑色选中导航;后 = 本目录 `01-source-list.png`(蓝色主按钮)、`12-tech-shell-tech-tab.png`(技术性能页内蓝色应用按钮)、`09-edit-source-drawer.png`(蓝色保存)。
- **为何是收敛而非 JD:** KB-OPS-V163-002 §7 KEEP 明列 "primary blue actions" 属 Design Conformance;B1 #4 当时延后正是"待 Integration 统一裁决"。token 是共享语法唯一出处,一处收敛全应用一致(按钮/选中导航/链接/开关选中态),主题其余语义色(绿=健康/红=需处理/琥珀=中间态)不变,与两张参考协调。
- **验证:** vitest 429 全绿(无任何用例断言旧黑色);渲染复核 01/09/12/14/15 截图主操作与选中态全为参考蓝。

### B. 共享顶部 chrome → 身份 chip/菜单(解决 B2 Ledger J9)

- **改动文件:** `admin/src/components/Layout.tsx`(+ `dropdown-menu.tsx` additive 原语)。
- **前后对比:** 前 = 「欢迎,admin@camthink.ai + admin 徽章 + 退出」三段平铺;后 = `03-chrome-topbar-identity.png`(蓝底头像 A + 用户名 + admin chip + chevron)与 `04-chrome-identity-menu-open.png`(菜单:身份+邮箱+退出)。
- **为何是收敛而非 JD:** 参考 PNG1/PNG2 顶栏一致呈现「头像 + 用户名 + chevron」身份区。实现用真实 auth 真相(`user.name||user.email`、`user.role`、既有 logout 流程),无任何虚构;登出语义(清 token→跳登录)逐字保留。
- **未收敛(如实 JD):** PNG2 顶栏的「过去 7 天 2025-09-03→2025-09-09」全局日期范围选择器——无全局时间范围产品真相(技术洞察页内已有等价 TimeFilter,见 12 截图右上「今天/近7天/30天」),按纪律不得造功能,入 JD(J-C1)。

### C. 共享侧栏/导航语法(解决 B2 Ledger J10 的选中态部分)

- **改动文件:** `admin/src/components/Sidebar.tsx`(品牌区);选中态由 A 的 token 收敛自动达成(`bg-primary text-primary-foreground` → 蓝色强选中态)。
- **前后对比:** 前 = v163-b1 `01-source-list.png` 黑色实底选中 + 纯文本 "Ask AI" 品牌;后 = 本目录 `02-chrome-sidebar-selected.png`(ASK-AI 蓝标识 + 运营/配置 分组 + 数据源蓝色强选中态)。
- **为何是收敛而非 JD:** KB-OPS-V163-002 §7 KEEP 明列 "strong selected navigation state";参考两张 PNG 的选中项均为蓝色(PNG1 蓝实底/PNG2 蓝底左条),实现取 PNG1 的蓝色实底强选中语法,与主按钮同一 token,语法统一。
- **分组层级/标签排版/密度:** 运营/配置 两组、小号 muted 组标签、导航清单本身零变更(IA 语义属 #52 冻结修正;用户管理/系统信息 保持既有归属,路由零增删)——渲染与参考一致,记 MATCH。
- **未收敛(如实 JD):** PNG2 侧栏的 帮助中心/收起菜单 入口与 系统 分组——无对应路由/产品真相,不得发明(J-C2);PNG1 侧栏为深色而 PNG2 为浅色属**参考内部不一致**,实现保持与单视口参考 PNG2 一致的浅色共享 chrome(J-C3)。

---

## 5. 测试计数(组合树全量)

| 套件 | 结果 | 证据 |
| --- | --- | --- |
| 后端全量 pytest(串行,HF_HUB_OFFLINE=1,TEST_DATABASE_URL=ask_ai_test 全 DSN) | **2501 passed / 7 skipped / 0 failed**(122.8s) | `evidence/green-pytest-full.log` |
| admin vitest | **429 passed / 54 files / 0 failed**(B1 404 + B2 387 组合后含去重) | 本报告 §5 记录;执行日志见会话 |
| `npx tsc -b`(admin) | **0 error**(widget 子项目噪声经 node_modules symlink 后归零,环境性、正交) | 同上 |
| `npm run build` | **✓ built in 2.21s**(chunk>500kB 警告为既有) | `evidence/green-build.log` |
| ruff(组合树全部改动后端文件:data_sources/schemas/tech/analytics + 两测试文件) | **All checks passed!** | 本报告 §5 记录 |
| Project-automation(`tests/project_automation/`) | **114 passed in 0.07s** | `evidence/green-pa-suite.log` |

**PA 回归定位证据:** v1.6.2 integration 报告(`docs/engineering/tasks/v162-integration-execution.md` §3)"Project Automation **114 passed**";`docs/engineering/tasks/project-automation-closed-issue-event-audit.md` 记 "full suite 114 passed (107 baseline + 7 new)" → 仓内测试面 = `tests/project_automation/`,本次组合树独立运行 114 passed,**零回归**。

**失败分类:** 无真实失败。过程中一次全量 pytest 出现 541 errors/1 failed,定位为 **ENVIRONMENT**(执行 agent 首跑误用 `TEST_DATABASE_URL=ask_ai_test` 简写,非合法 SQLAlchemy DSN → 全部 DB fixture `ArgumentError`;与代码无关),以全 DSN 重跑后 2501/7/0 全绿。真实 REGRESSION = 0。

> 注:v1.6.2 基线 2490 → 组合 2501 = +11(B2 新增 `tests/api/admin/test_tech_answer_gaps.py` 11 用例;B1 的 attention-summary 测试已含于其单轨 2490 计数),增量与两轨报告 changed files 对账一致;B1 报告提及的 `test_recovery_semantics.py` 既有 flaky 本次全量未复现(0 failed)。

---

## 6. Runtime 环境(真实组合栈)

- 后端:worktree `uv sync --extra dev`;`ASKAI_API_PORT=8103 EMBEDDER_DEVICE=cpu uv run python -m backend.main` → Uvicorn 0.0.0.0:8103;BGE-m3 cpu 加载;`.env` 为 symlink(未提交)。
- 前端:`cd admin && VITE_API_TARGET=http://localhost:8103 npx vite --port 5183 --strictPort`(candidate 源码热载);worktree `widget/node_modules` 为本地 symlink(同 admin/node_modules 既有惯例,.gitignore AC-FIX-02 预期,未提交)。
- 数据层:本地 docker `ask-ai-local-postgres-1`(5432,用户 ask_ai/库 ask_ai)+ `ask-ai-local-weaviate-1`(8080);B1/B2 本地 seed 数据仍在(5 源/21 文档/7 聚类,B2 带 b2a/B2SEED 标记),代表性充分,**未补 seed**。
- 登录:本地库 `admin@camthink.ai`(admin 角色;密码经 `backend.auth.jwt.hash_password` 本地重置,仅本地;`UPDATE users SET password_hash=... WHERE email IN ('admin@camthink.ai','b2-render@camthink.ai')`)。
- 浏览器:独立 headless Chromium for Testing 1228(playwright-core),`viewport 1440×900 @1x`;登录经真实 UI 表单提交;跨轨下钻为真实点击(事件行/缺口行/侧板链接)。

---

## 7. 全新 Visual Difference Ledger(独立重建,非继承)

判定基准 = 两张硬参考逐面板元素;「MATCH」含对权威数据形状的 KB-OPS §2 ADAPT,内容数值随本地代表性数据不同不构成 material difference。组合树截图 = 本目录 NN-*.png。

### 7.0 共享 chrome(Integration-owned)

| # | 参考元素 | 判定 | 说明/权威证据 |
| --- | --- | --- | --- |
| C-a | 主操作蓝色(primary blue) | **MATCH** | A 已解决:`--primary`=#2563eb,01/09/12/14 全应用一致;原 B1 #4 / B2 J9-J10 相关项随之关闭 |
| C-b | 侧栏蓝色强选中态 | **MATCH** | A+C 已解决:02 截图 数据源 蓝色实底白字,与 PNG1 选中语法一致 |
| C-c | 侧栏品牌区 标识+ASK-AI | **MATCH** | C 已解决:02 截图 蓝底 LayoutGrid 标识+ASK-AI 粗体 |
| C-d | 分组层级/组标签排版(运营/配置) | **MATCH** | 02 截图;组标签小号 muted;导航清单零变更(#52 冻结) |
| C-e | 顶栏身份区 头像+用户名+chevron | **MATCH** | B 已解决:03/04 截图;登出语义不变(菜单内既有 auth 真相) |
| J-C1 | 顶栏全局日期范围选择器(过去 7 天 2025-09-03→2025-09-09) | **JUSTIFIED DIFFERENCE** | 无全局时间范围产品真相;技术洞察页内已有等价 TimeFilter(12 截图右上);KB-OPS §10 不得虚构;范围语义等价存在于页内 |
| J-C2 | 侧栏 帮助中心/收起菜单/系统分组(用户管理、系统设置) | **JUSTIFIED DIFFERENCE** | 无对应路由真相;#52 冻结修正导航清单不得增删;用户管理/系统信息 保持既有 IA 归属 |
| J-C3 | 侧栏底色:PNG1 深色 vs PNG2 浅色 | **JUSTIFIED DIFFERENCE** | 参考内部不一致;实现保持与单视口参考 PNG2 一致的浅色共享 chrome(01/12 与 B2 参考整体协调) |

### 7.1 B1 面(data-source-operations-original.png;截图 01/05/06/07/08/09/10/11)

| # | 参考元素 | 判定 | 说明/权威证据 |
| --- | --- | --- | --- |
| 1 | 面包屑/标题/副标题/搜索/状态类型过滤/页脚 共 N 个 | **MATCH** | 01/06/05 截图 |
| 2 | 「+ 添加数据源」主按钮 | **MATCH** | 01 截图(蓝色,C-a) |
| 3 | 列集 名称/类型/状态/知识数量/需处理(一等红列,零值 —)/最后同步(相对时间)/操作(紧凑 ⋯) | **MATCH** | 01 截图;异常优先排序;千分位见 API ledger_total |
| 4 | 状态徽章 需处理(红)/正常(绿)/待分类(琥珀)/同步失败(红) | **MATCH** | 01 截图 四态全由权威值映射(last_sync_status/attention-summary/sync-health) |
| 5 | 详情身份区 WooCommerce 品牌图 | **JUSTIFIED DIFFERENCE** | 后端无 logo 资产权威真值;伪造品牌图被禁;实现首字母 avatar(06) |
| 6 | 详情红 banner(标题+原因摘要+查看需处理+关闭)与右侧摘要 | **MATCH** | 06:有 3 项知识需要处理=2 缺失宽限中+1 现行版本缺失=DB 逐类计数;右侧 8 条知识·3 项需处理=API/DB |
| 7 | 知识内容工作区(搜索/筛选/共 N 条/排序/桶注记) | **MATCH** | 06:当前在服5/需要关注3/已退役0=documents 权威聚合;排序=additive 只读参数 |
| 8 | 文档行 类型列(商品/页面) | **JUSTIFIED DIFFERENCE** | 后端无逐文档内容类型真值(仅 source_type);KB-OPS §5.3 无分类不得推断 |
| 9 | 服务列 部分服务分数(10/12) | **JUSTIFIED DIFFERENCE** | 逐文档部分服务分数无权威真值;实现二值 在服/不在服(serving 关系),编造分数被禁 |
| 10 | 行内 处理 按钮与行级修复 | **JUSTIFIED DIFFERENCE** | #54 修正+合同 Forbidden:无既有权威行级修复操作;如实标注「行级修复操作需待权威修复契约(v1.6.3 不提供)」(07) |
| 11 | 展开行诊断(问题/源内容状态/当前有效版本/当前服务) | **MATCH** | 07:notServingReason 操作者语言、源中缺失(宽限中)、v1(active)·生效自、在服·持久 chunk 2=API/DB 逐键一致 |
| 12 | 系统已自动尝试恢复 N 次注记 | **JUSTIFIED DIFFERENCE** | 逐文档自动恢复次数无后端真值;sync_runs.recovery 为源级,归属到文档即伪造 |
| 13 | 处理后绿色验证结果卡 | **JUSTIFIED DIFFERENCE** | 依赖不存在的行级修复动作;无动作即无验证语义 |
| 14 | 同步状态卡(最近成功/最近结果/可靠性) | **MATCH** | 08:10天前/部分成功(琥珀)/**暂不评估**(样本 2 次不足,不编百分比)/每 6 小时=权威 |
| 15 | 下次同步 4 小时后 | **JUSTIFIED DIFFERENCE** | 后端无下次调度权威真值;以同步周期承载 cadence 真值 |
| 16 | 最近活动时间线(异常优先红/琥珀/绿/灰)+常规压缩+技术证据可展开 | **MATCH** | 08:同步失败(红,管理员触发,embedder 返回 0 向量)/部分成功(琥珀)/完成(绿,新增 8);run 行=DB sync_runs 逐条对应 |
| 17 | 编辑数据源 Drawer(context-preserving,取消/保存) | **MATCH** | 09:右侧抽屉不离开运营上下文;完整编辑器能力保持权威(字段超集) |
| 18 | Drawer 内 类型 禁用 | **JUSTIFIED DIFFERENCE** | 类型编辑是既有授权能力;禁用=移除既有操作,未被授权 |
| 19 | 知识设置 Drawer(时态角色/新鲜度) | **JUSTIFIED DIFFERENCE(未实现)** | KB-OPS §4.6 NEW REQUIREMENT;§10 NOT authorized;页面无该词表 |
| 20 | 高风险变更影响预览 Modal | **JUSTIFIED DIFFERENCE(未实现)** | KB-OPS §4.7;「No UI may fabricate affected counts」;预览契约不存在 |
| 21 | 查看需处理(attention bucket 过滤) | **MATCH** | 10:共 3 条=API bucket=attention=DB 行集(deprecated-api/legacy-pricing/orphan-page) |
| 22 | 行操作 ⋯ 紧凑菜单 | **MATCH** | 11:查看可观测性/删除等既有操作全保留 |

### 7.2 B2 面(technical-insights-answer-gaps-original.png;截图 12/13/14/15/16/17/18/19)

| # | 参考元素 | 判定 | 说明/权威证据 |
| --- | --- | --- | --- |
| 1 | 共享壳 技术洞察+恢复副标题;双 Tab 强选中(蓝下划线,aria-selected) | **MATCH** | 12/14 截图;技术性能/回答缺口 同壳(#57 冻结修订) |
| 2 | 搜索占位全文+全部状态/全部原因/过去 7 天 筛选 | **MATCH** | 14 截图 |
| 3 | 队列 7 列(问题/主题 主行+代表问句灰副行、相关提问、影响回答、原因、状态、最近发生排序) | **MATCH** | 14:NE101 是否支持 PoE 23/18/知识缺失/需要处理/8小时前=API=DB |
| 4 | 原因徽章语义色 | **MATCH(ADAPT)** | 知识缺失(红)/服务知识不完整(蓝紫)/低相关(琥珀)/未分类(灰)=权威 miss_type 忠实映射;参考 depicted 的 内容过期/检索异常/生成异常/引用异常/内容冲突 无权威分类 → **JUSTIFIED DIFFERENCE(J1/J12)** |
| 5 | 状态 需要处理(红)/已解决(绿);参考 观察中 | 观察:**JUSTIFIED DIFFERENCE(J2)** | open→需要处理/resolved→已解决;OBSERVING lifecycle NOT authorized(KB-OPS §10) |
| 6 | 行选中态=蓝底+左蓝条+checkbox;底部 已选择 1 项+分页+10 条/页 | **MATCH** | 15 截图 |
| 7 | 诊断侧板:标题+状态徽章+关闭;统计行+最近发生;五 Tab 蓝下划线 | **MATCH** | 15/16/17/18/19;「涉及 17 个用户」无权威用户聚合(会话无用户实体) → **JUSTIFIED DIFFERENCE(J5)** |
| 8 | 问题描述诊断式文案 | **JUSTIFIED DIFFERENCE(J7)** | 实现为权威字段事实性汇总(N 相关提问/M 受影响回答);不虚构诊断 |
| 9 | 队列主标题 主题式短语(NE101 PoE 支持信息缺失) | **JUSTIFIED DIFFERENCE(J8)** | 代表问句=簇内真实问句是聚类服务不变量(clustering.py);主题字段后端不存在 |
| 10 | 诊断结论红板+原因徽章+结论文案 | **MATCH** | 15:知识缺失红板,忠实转述权威分类语义;unavailable 态不推断(14 行 证据不可用) |
| 11 | 典型问题示例+查看全部 (6)+5 bullets | **MATCH** | 15/16:样例=cluster sample_questions 权威数组 |
| 12 | 推荐操作 导出相关对话(CSV)+隐私说明 | **JUSTIFIED DIFFERENCE(J3)** | 导出语义 NOT authorized;替换为授权动作 查看相关对话(冻结深链 /conversations?q=) |
| 13 | 内容补充完成后段+「内容已补充,开始观察」蓝 CTA | **JUSTIFIED DIFFERENCE(J4)** | §5.6 NEW REQUIREMENT;observation transitions NOT authorized;整段缺席 |
| 14 | 相关数据源 WooCommerce / NE101 外链 | **JUSTIFIED DIFFERENCE(J6)** | 后端无 gap→source 权威关联;拼接即发明 |
| 15 | 诊断详情/历史记录 Tab | **MATCH(ADAPT)** | 18:诊断详情=权威证据展开;19:历史记录如实「证据不可用:v1.6.3 暂无该缺口的权威历史记录数据」 |
| 16 | 技术性能:critical 横幅+失败卡红框+异常优先事件列表+证据可展开(raw JSON) | **MATCH** | 12/13:需要介入横幅文案=API reasons 原文;真实失败 6%(3/52)=traces 权威;证据展开=generation failure JSON 原样 |
| 17 | Trace 覆盖诚实标注 | **MATCH** | 12:「Trace 数据自 2026/9/7 起」;real zero/unavailable/populated 三态可区分(14) |

**计数:Visual DEFECT = 0;MATCH = 32;JUSTIFIED DIFFERENCE = 23(J-C1/J-C2/J-C3 + 上表 11+9 项,均附权威真相证据,待 Role A)。**
(B1 原 #4 主蓝、B2 原 J9 顶栏、B2 原 J10 选中态——三项旧 JD 因 Integration 解决转为 MATCH;旧 JD 其余均沿用并保留其权威证据引用。)

---

## 8. 全新 Functional Conformance Ledger(组合树重证,禁止继承)

Verdict 词表:MATCH / JUSTIFIED DIFFERENCE / FUNCTIONAL DEFECT。方法:UI 截图值 ↔ API 响应(curl 带 JWT,`evidence/functional-api-*.json|.txt`)↔ 本地 PG 只读 SELECT(`evidence/functional-db-verification.txt`)。

| # | UI surface/state/action | Authoritative source | API/backend evidence | Expected semantics | Observed result | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| F1 | 列表 知识数量列(3/6/8/4/0) | GET /data-sources/attention-summary ledger_total | attention-summary:partner-portal 3/wiki 6/store-woo 8/help-center 4/website 0 | 账本总数 | UI=API=DB(21 行按 source 前缀聚合逐源一致) | MATCH |
| F2 | 列表 需处理一等列(3/1/3/—/—) | 同上 attention_count | 3/1/3/0/0 | 冻结桶公式(ledger−current−retired;discovered 与现行版本缺失计入) | UI 徽章逐源=API=DB(missing_cand+active_no_current+discovered) | MATCH |
| F3 | 列表 操作者状态(同步失败×2/需处理/待分类×2) | /data-sources last_sync_status + attention + /sync-health | DB last sync:partner failed、wiki failed、store-woo partial、help success | 呈现映射零前端重判 | 01 截图四参考态全部由权威值复现 | MATCH |
| F4 | 详情右侧摘要+红 banner 原因摘要 | /documents 聚合 + last_sync_* | store-woo:8 知识/3 需处理;DB active 6−无现行 1 + missing 2 | 逐类投影只列非零 | 06 截图 2 项内容缺失+1 项现行版本缺失=DB 计数逐类一致 | MATCH |
| F5 | 查看需处理 bucket 过滤 | GET /documents?bucket=attention(只读参数) | total=3:deprecated-api/legacy-pricing/orphan-page | 服务端权威桶投影 | 10 截图 共 3 条=DB 行集 | MATCH |
| F6 | 展开行诊断(deprecated-api) | GET /documents/detail?doc_source_id=… | truth JSON:missing_candidate、serving、v1、chunks 2、gen 900001 ready | 只读真相零编造 | 07 截图=API=DB(missing_candidate∧has_cv∧chunks 2) | MATCH |
| F7 | 生成真相(#900001/#900002) | GET /generations | DB index_generations:900001 ready 8docs/40chunks;900002 failed has_failure | failure JSONB 原样 | 07/13 截图与 API/DB 逐键一致 | MATCH |
| F8 | 同步状态与活动时间线 | GET /sync-runs?source_id=store-woo | run4 failed(manual)/run3 partial/run2 success;DB sync_runs 三行 | 异常优先+常规压缩+技术证据可展开 | 08 截图事件与 API/DB 逐条对应 | MATCH |
| F9 | 既有授权动作:触发同步动作链 | POST /data-sources/{id}/sync(既有) | 202 {accepted,request_id:2} → DB sync_requests id=2 help-center manual pending → /sync-status help-center **QUEUED** request_id=2 | 202=受理≠成功;随后本地删除 pending 行回落(仅本地清理) | 全链重证通过(`functional-action-sync-chain.txt`) | MATCH |
| F10 | 编辑抽屉保存 | PATCH /data-sources/{id}(既有) | vitest round-trip payload 形态断言全绿 | 表单逻辑与提交形态不变 | 09 截图抽屉+测试通过 | MATCH |
| F11 | 技术性能 KPI 真实失败 6% | GET /tech/performance?range=7d | kpi 3/52;DB traces 7d:generation_error 3 / rag 49 = 52 | 分子=真实失败,分母=窗口 trace | UI「6% 3 / 52 条 trace」=API=DB | MATCH |
| F12 | critical 横幅(需要介入) | 同上 _derive_health 阈值 | reasons:5.8%≥5% 阈值、P95 40550ms>5000ms | 确定性推导 | 12 截图横幅文案=API reasons 原文 | MATCH |
| F13 | 事件行(生成失败/同步失败×源归属) | GET /tech/generation-events + /sync-runs?status=failed | store-woo 900002、wiki、partner-portal 行 | P 轴 failed=error;raw 证据默认折叠 | 12/13 截图行与 API/DB 一致 | MATCH |
| F14 | 回答缺口队列行(NE101 23/18/知识缺失/需要处理/8小时前) | GET /tech/answer-gaps | item b2a00001…:question_count 23/impacted 18/miss_type 召回空/status open/last_seen 15:25Z | 投影聚合=后端权威分类 | UI 逐字段=API=DB(count 18、max(created_at)) | MATCH |
| F15 | 原因/状态词表权威性(含 未分类/证据不可用) | classify_gap_miss_types(与 coverage-gaps 同源) | DB:无归属会话聚类 impacted 0/last_seen null;resolved 2 聚类 | 不发明 cause/recency/观察中 | 14 截图 未分类+证据不可用+已解决 2 行与 DB 一致 | MATCH |
| F16 | 侧板相关对话证据(归属对话(18)) | GET /tech/answer-gaps/{id}/conversations | total=18 items 最近在前 | 只读投影 | 17 截图 18 行=API=DB | MATCH |
| F17 | 队列只读边界 | 合同 Forbidden | POST answer-gaps=405(pytest);UI 无 导出/开始观察/解决控件 | 零 mutation 面 | vitest 缺席断言+pytest 通过 | MATCH |
| F18 | RBAC 不变 | 既有 require_role | 未认证 401(pytest) | 只读读面 RBAC 一致 | pytest 通过 | MATCH |

**FUNCTIONAL DEFECT = 0。**

### 跨轨强制下钻(真实点击)

| # | 路径 | 实测 | 证据 |
| --- | --- | --- | --- |
| D1 | 技术洞察 事件行 → `/data-sources/{source_id}` | 真实点击 `[data-incident-row][data-source-id=store-woo]` → URL `http://localhost:5183/admin/data-sources/store-woo`,到达 B1 新详情工作面(红 banner+知识内容工作区),权威源上下文正确 | `20-drill-event-to-source.png`;driver 日志 `drill1 url:` |
| D2 | Answer Gap → `/conversations?q=` | 真实点击缺口行 → 侧板 相关对话 → 「在对话审查中查看 →」→ URL `/admin/conversations?q=NE101%20是否支持%20PoE`(编码),搜索预填正确+真实命中对话(已回答 行列表) | `21-drill-gap-to-conversations.png`;driver 日志 `drill2 url:` |

---

## 9. 全新截图清单(1440×900 @1x,组合树真实渲染,独立于 B1/B2 截图)

目录:`/Users/harryhua/Documents/GitHub/ask-ai-acceptance/v163-integration-20260913/`

| 文件 | 状态 |
| --- | --- |
| 01-source-list.png | B1 扫描优先列表(蓝主按钮/状态/需处理红列/相对时间/⋯/页脚) |
| 02-chrome-sidebar-selected.png | 共享 chrome 侧栏近景(ASK-AI 标识+分组+蓝色强选中态) |
| 03-chrome-topbar-identity.png | 共享 chrome 顶栏身份区近景(头像+用户名+角色 chip+chevron) |
| 04-chrome-identity-menu-open.png | 身份菜单展开(身份+邮箱+退出) |
| 05-source-detail-normal.png | B1 详情常规层级(Help Center) |
| 06-source-detail-needs-attention.png | B1 详情需处理(WooCommerce 红 banner+权威原因摘要) |
| 07-expanded-diagnosis.png | B1 展开行只读诊断(问题/源内容状态/当前有效版本/当前服务/生成真相) |
| 08-sync-activity.png | B1 同步状态与活动(异常优先时间线) |
| 09-edit-source-drawer.png | B1 编辑数据源右侧抽屉 |
| 10-attention-filter.png | B1 查看需处理(服务端桶过滤 共 3 条) |
| 11-list-actions-menu.png | B1 列表 ⋯ 紧凑操作菜单 |
| 12-tech-shell-tech-tab.png | B2 共享壳+技术性能 Tab(critical 横幅/KPI/事件) |
| 13-incident-evidence-expanded.png | B2 事件 raw 证据展开(generation failure JSON) |
| 14-answer-gaps-queue.png | B2 回答缺口队列(7 列/原因状态徽章/证据不可用态) |
| 15-gap-selected-panel-overview.png | B2 缺口选中+诊断侧板 概览(蓝底选中+左蓝条) |
| 16-gap-panel-typical.png | B2 侧板 典型问题 Tab |
| 17-gap-panel-conversations.png | B2 侧板 相关对话 Tab(归属对话(18)) |
| 18-gap-panel-diag-details.png | B2 侧板 诊断详情 Tab |
| 19-gap-panel-history.png | B2 侧板 历史记录 Tab(证据不可用如实) |
| 20-drill-event-to-source.png | 跨轨下钻 1:事件行点击 → B1 详情工作面 |
| 21-drill-gap-to-conversations.png | 跨轨下钻 2:缺口 → /conversations?q= 预填+命中 |

截图说明:右下角 `ai` 悬浮球为 LoginChat 既有 FAB(baseline `5c50191` 既有产品真相,组合树零改动),非本轮引入,不入 Ledger。

---

## 10. 剩余 JUSTIFIED DIFFERENCE(23 项,均待 Role A 裁决)

- **共享 chrome(3):** J-C1 全局日期范围选择器(无全局时间范围真相;页内 TimeFilter 等价);J-C2 帮助中心/收起菜单/系统分组(无路由真相,#52 冻结);J-C3 侧栏底色明暗(参考内部不一致,实现取 PNG2 浅色)。
- **B1 面(11):** 详情 logo 品牌图;文档 类型列内容类型;部分服务分数;行级 处理/重新处理 按钮契约缺失;自动恢复次数注记;处理后验证结果卡;下次同步倒计时;编辑抽屉类型可编辑(既有能力保留);知识设置 Drawer(NEW REQUIREMENT 未实现);高风险预览 Modal(NEW REQUIREMENT 未实现)。
- **B2 面(9):** 原因词表超集(内容过期/检索异常/生成异常/引用异常/内容冲突 无权威分类);观察中 状态;导出相关对话(以授权 查看相关对话 替代);内容补充完成后段+开始观察 CTA;涉及 N 个用户;相关数据源外链;问题描述诊断式文案(以权威事实汇总替代);队列主标题主题式短语(代表问句不变量);depicted 状态重演边界(J12)。

---

## 11. Scope audit(逐项证明)

1. **零生产触碰:** 全程仅本地 docker(ask-ai-local-postgres-1/ask-ai-local-weaviate-1,localhost);无任何 SSH;生产 43.132.189.162 零网络访问;零 deploy。
2. **零检索/排序/引用/生成/生命周期语义漂移:** Integration 增量仅 4 个前端呈现层文件(index.css token/Layout/Sidebar/dropdown-menu additive);后端零改动文件;组合树全量 pytest 2501 passed(含既有 retrieval/citation/lifecycle 断言)为证。
3. **零伪造 backend truth:** 前端呈现值全部消费既有/新增只读投影端点;未实现语义如实缺席(见 Ledger 各 JD);渲染截图与测试 absent 断言一致。
4. **零未授权 remediation/OBSERVING/export 语义:** 页面无该词表/控件;B2 pytest 405 断言通过;无新持久化模型。
5. **零生产 mutation / 零 Issue 关闭 / 零无关 refactor:** 本地库变更仅:admin/b2-render 密码 hash 重置(仅本地 users 表 2 行)+ sync_requests id=2 动作链验证行插入后删除(仅本地,SQL 全文在 `functional-action-sync-chain.txt`);Issues #52–#60 全部保持 open;`git add` 显式列文件;models/.env/admin、widget node_modules symlink 未提交。
6. **candidate 历史零改写:** 仅追加两个 commit;B1/B2 已接受 commits(336c7f5、9e12746)与两 merge SHA 零变更。

---

## 12. 残余风险

1. 23 项 JUSTIFIED DIFFERENCE 待 Role A 逐项裁决;在裁决前本组合 candidate 不应进入 deploy 审批(迭代计划 §Difference Ledger)。
2. 首跑 pytest 的 ENVIRONMENT 失败(DSN 简写)已如实记录;后续 agent 必须使用完整 `postgresql+asyncpg://…/ask_ai_test` DSN。
3. widget 子项目 tsc/build 噪声为已知正交(经 symlink 缓解);不属本轮范围。
4. 截图内 LoginChat FAB(baseline 既有)与参考图无关;如未来参考纳入 chrome 范围需单独裁决。
5. 本地 seed 密码/账号重置仅限本地 dev 库;生产凭据未触碰。
