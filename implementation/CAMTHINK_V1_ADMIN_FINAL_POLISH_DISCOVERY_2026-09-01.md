# CAMTHINK V1 — Admin Final Polish Discovery 报告

日期:2026-09-01
任务:CAMTHINK_V1_ADMIN_FINAL_POLISH_DISCOVERY(READ-ONLY 产品/UX 验收发现)
模式:只读发现 —— 未修改任何产品代码(Admin/Backend/Widget 零改动)
状态:**DISCOVERY_COMPLETE**

---

## 1. Executive Summary

以真实管理员视角对 Admin 九大界面做了浏览器级全量走查(真实登录、真实数据、
双角色、双宽度、对话框与空态),整体结论:**V1 Admin 已具备真实可用的生产
管理界面骨架**——页面无控制台错误、无失败请求、无水平溢出、主导航/深链/
空态/删除确认等基础质量扎实。

跨页走查发现 **2 个 P1**、**8 个 P2**、**1 个 FUTURE**:

- **P1-1 数据治理缺陷**:删除数据源只删配置行,该源全部文档与向量**原地
  留存且继续参与访客检索**,admin 无任何界面可见或可清理(实锤:旧源
  ne101-4382af41 已删,其 3,109 篇文档/57,912 chunks 仍在库)。
- **P1-2 RBAC 表面失真**:viewer 角色能看到全部写操作按钮(同步/新增/编辑/
  删除/应用变更/批量标注),受限直达页把 403 吞成「静默空表」。
- 其余为一致性/文案/空态/占位面板类小修(P2),见 §6-§9。

INT-CHK-008(Admin 浏览器级人工走查)**PASS**(§15)。

## 2. Environment / Baseline

- 走查 Admin 代码 = 已验收基线 **024e55bd**(Technical Insights 终点)。
  WEB-01 候选(0dc0f43)对 `admin/`、`widget/` **零改动**(`git diff
  024e55bd..0dc0f43 -- admin/ widget/` 为空)→ **全部发现均为
  A 类(可复现于已验收基线);B 类(WEB-01 专属观察)= 无**。
- 运行环境:worktree backend 127.0.0.1:8024(0dc0f43 代码,连接本地
  ask_ai 开发库真实数据)+ worktree admin dev :5177(基线 Admin 代码);
  未触碰主仓 :8000/:5174 与生产。
- 浏览器:Chromium(Playwright)1440×1000 与 1280×900;真实登录
  (admin@camthink.ai/admin123;临时 viewer 用户,走查后已删除)。
- 证据:27 个文件(docs 仓
  `implementation/evidence/admin-final-polish-20260901/`,24 截图 +
  walkthrough-report.json + viewer-report.json + overflow.txt)。

## 3. Pages Walked(仓库实况,无虚构)

| 路由 | 页面(侧边栏名) | 截图 |
|------|------|------|
| /login | 登录 | 01, 24(错误态) |
| / | 业务概览 | 02, 17(1280) |
| /conversations | 对话审查 | 03, 10(空搜索), 22(viewer) |
| /analytics | 技术洞察(技术性能+知识缺口双 tab) | 04, 15(1280) |
| /data-sources | 数据源管理 | 05, 16(1280), 19(viewer) |
| /customizations | 对话接入(渠道绑定+助手配置) | 06, 11 |
| /llm-providers | 模型配置 | 07, 13, 14(添加对话框), 20(viewer) |
| /answer-overrides | 答案覆盖管理 | 08(空态), 23(viewer) |
| /users | 用户管理 | 09(admin), 21(viewer) |

无其余管理路由(App.tsx 全量核对)。控制台错误 0、失败请求 0、水平溢出 0
(overflow.txt)。

## 4. Browser Acceptance Coverage

- 真实登录/退出、错误态登录(24);
- 9 页面全页截图(桌面 1440);
- 3 页面 1280 宽度 sanity(15/16/17);
- 对话框:数据源创建(12)、供应商添加(14);
- 状态:空搜索(10)、答案覆盖空态(08)、viewer 403 空态(21);
- RBAC:viewer 双角色对比(18-23)+ API 403 行为;
- API/代码交叉验证:business.py total 口径、data_sources.py DELETE、
  conversations 延迟着色阈值(10s/5s)、Login.tsx 错误透传路径。
- 未覆盖:移动端(桌面产品,按合同不做);真实 LLM 调用类按钮(批量标注,
  避免写操作)。

## 5. Cross-Page Findings(总览)

| ID | 页面 | 摘要 | 级别 | 分类 | Fixability |
|----|------|------|------|------|-----------|
| AFP-001 | 数据源(跨页:检索) | 删除源遗留孤儿语料继续参与检索 | **P1** | BUG/RELIABILITY/SEMANTIC | MEDIUM_FIX |
| AFP-002 | 全配置页 | viewer 可见全部写操作按钮;403 被吞成空态 | **P1** | RBAC/UX | SMALL_FIX |
| AFP-003 | 登录 | 登录错误透出后端英文校验原文 | P2 | COPY | SMALL_FIX |
| AFP-004 | 业务概览 | 「总服务客户」实为对话数 | P2 | SEMANTIC/COPY | SMALL_FIX |
| AFP-005 | 对话审查 | 「重试」筛选/标记在真实数据下永为空(死过滤器) | P2 | SEMANTIC | SMALL_FIX |
| AFP-006 | 对话接入 | 渠道绑定 select 变更即时写库,无确认/无 pending | P2 | UX | SMALL_FIX |
| AFP-007 | 技术洞察 | 「澄清漏斗(待接入)」占位空壳面板 | P2 | SEMANTIC/COPY | SMALL_FIX |
| AFP-008 | 对话审查/用户管理 | 空结果/无权限呈现为无声空表,无解释文案 | P2 | UX | SMALL_FIX |
| AFP-009 | 技术洞察 | P50/P95 趋势图整幅红色主导,诊断区视觉过警 | P2 | VISUAL | SMALL_FIX |
| AFP-010 | 对话审查 | trace 标记圆点无图例(仅 hover title) | P2 | UX | SMALL_FIX |
| AFP-011 | 用户管理 | 无停用/改角色/重置密码,仅删除(能力缺口) | FUTURE | NEW_REQUIREMENT | — |

P0:**无**。未发现数据丢失、权限突破、崩溃级或误导性核心数据缺陷。

## 6. P0 Findings

无。

## 7. P1 Findings

### AFP-001 删除数据源不清理语料 —— 孤儿知识继续回答访客
- **Page**:数据源管理(影响面:检索/对话质量,跨页)
- **Reproduction**:
  1. 本地库 data_sources 现存 `ne101-945fff13`(今日 10:04 重建的 GitHub 源);
     旧源 `ne101-4382af41` 已被删除(配置行不存在);
  2. `SELECT count(*) FROM documents WHERE source_id LIKE 'ne101-4382af41/%'`
     → **3,109 行**;Weaviate Document 集合计 70,574 对象,其中
     ne101-4382af41/* 抽样可见真实代码文档(chunk_index 22/225 等);
  3. 代码:`backend/api/admin/data_sources.py:381-395` DELETE 仅删
     data_sources 行;无任何文档/向量清理调用。
- **Expected**:删除源后,其知识应从检索中移除(或至少 admin 得到明确
  提示与一键清理入口)。
- **Actual**:全部文档与向量原地留存,**继续参与访客问答检索**
  (P0 信任边界按 channel_visibility 过滤,不感知源是否存活);且
  Technical Insights 的一致性自愈只作用于「仍存在的源」,孤儿永久不可见。
- **截图**:05(现行 admin 只显示新源 0 篇,旧源 3,109 篇不可见)。
- **Severity**:P1;**Classification**:BUG/RELIABILITY/SEMANTIC;
- **Why V1**:源重建/误删/测试源清理是真实运营动作;幽灵知识直接污染
  访客答案,且治理上不可见不可逆;
- **Proposed direction**:删除端点触发按前缀异步清除(documents 行 +
  Weaviate chunks;复用 ingest.delete_document 逐篇能力或按 uuid5 前缀批删);
  或最低限度:同步层孤儿自愈扩展到「无主前缀」+ admin 提示;
- **Fixability**:MEDIUM_FIX。

### AFP-002 viewer 角色被广告全部写操作;受限页 403 吞成空态
- **Page**:数据源/模型配置/答案覆盖/对话审查/用户管理(viewer 登录)
- **Reproduction**:
  1. 以 viewer 登录(discovery-viewer@example.com);
  2. /data-sources 可见「同步全部/新增数据源/同步/编辑/删除」;
     /llm-providers 可见「供应商凭证/端点授权/应用变更/添加」;
     /conversations 可见「批量标注 Intent」;直接访问 /users 渲染
     「用户管理」页+「新增用户」按钮+空表;
  3. 后端这些操作均为 editor/admin(viewer 调用返回 403 权限不足)。
- **Expected**:角色不可用的操作不展示(或禁用+原因);受限页给出
  「无权限」说明而非空数据表。
- **Actual**:按钮全部可点,点击后才迟滞失败;/users 把 403 渲染成
  「空表+分页+新增用户」,管理员误以为系统无用户。
- **截图**:19(data-sources 全按钮)、20、21(users 空表+新增按钮)、
  22、23;viewer-report.json。
- **Severity**:P1;**Classification**:RBAC/UX;
- **Why V1**:只读账号是交付给客户管理员的真实角色;广告不可用操作
  产生失败工单与不信任感;
- **Proposed direction**:前端按 auth state.role 条件渲染/禁用
  (角色信息已在顶栏展示);受限页 403 → 「无权限」提示组件;
- **Fixability**:SMALL_FIX。

## 8. P2 Findings

- **AFP-003 登录错误透出英文校验原文**(COPY,SMALL_FIX)
  复现:登录页输入 `bad-domain@test.local` → 红字显示
  "value is not a valid email address: The part after the @-sign is a
  special-use or reserved name..."(24-login-error.png;Login.tsx
  `setError(err.message)` 直传后端 detail)。方向:前端映射为中文文案
  (「邮箱格式不正确」等),后端 detail 仅记日志。
- **AFP-004 「总服务客户」实为对话数**(SEMANTIC/COPY,SMALL_FIX)
  business.py:65-71 `total = count(Conversation)`(窗口内对话行数),
  前端标签「总服务客户」(02 截图,值 16=对话数)。同一客户问 5 次计 5。
  方向:改名「服务对话数」或后端按 session 维度去重(后者属能力变更)。
- **AFP-005 「重试」筛选/标记永为空**(SEMANTIC,SMALL_FIX)
  生产从不写 retry_count 字段,`has_retry` 过滤与 marker 在真实现网恒空
  → 广告了一个永远无结果的过滤器。WEB-01 报告 F-4 已记录同源事实。
  方向:隐藏该 toggle 或文案注明「需管线重试插桩后启用」。
- **AFP-006 渠道绑定变更即时写库**(UX,SMALL_FIX)
  Customizations.tsx:60-66 select onChange 直接 updateBinding.mutate ——
  误触即改变线上渠道绑定,无确认/无 pending/可回滚但无提示。方向:
  显式保存按钮或至少 pending/成功反馈。
- **AFP-007 「澄清漏斗(待接入)」空壳面板**(SEMANTIC/COPY,SMALL_FIX)
  技术洞察-知识缺口 tab 底部常驻占位面板,上线即「暂无数据(待接入)」,
  广告产品没有的能力。方向:移除或明确标注「规划中」。
- **AFP-008 空结果/无权限呈现为无声空表**(UX,SMALL_FIX)
  对话审查无匹配搜索 → 空列表体+「共 0 页, 0 条」分页,无「无匹配结果」
  文案(10);viewer /users 403 → 空表(21)。方向:统一空态组件
  (区分「无数据/无匹配/无权限」+下一步动作)。
- **AFP-009 P50/P95 趋势图整幅红色主导**(VISUAL,SMALL_FIX)
  超基线日的 p95 段全部用告警红,单日数据即撑满整幅(04 截图下部),
  诊断区视觉过警,与「页面整体平静」的既定方向相悖。方向:基线超限用
  琥珀/描红边,配合 y 轴单位(ms)标注。
- **AFP-010 trace 标记圆点无图例**(UX,SMALL_FIX)
  对话审查行内 1-4 个彩色圆点(失败/澄清/拒答/降级/置信),含义仅存于
  hover title(03)。方向:筛选栏即图例(点色与 chip 对应)或加常显图例。

## 9. Future Findings

- **AFP-011 用户生命周期管理**(NEW_REQUIREMENT):用户管理仅支持
  新增/删除;无停用/启用切换、无角色变更、无密码重置(09 截图:状态列
  显示「启用」但无任何切换动作)。运维上收权只能删号(破坏性,丢审计)。
  需要新能力契约,不属 Final Polish。

## 10. Semantic Consistency Review(AFP-D02)

- 健康/样本不足/严重:数据源页与技术洞察 DSH 摘要**口径一致**
  (同一 source-health API,同一五态),✓;
- 技术洞察服务健康五态(healthy/degraded/critical/insufficient/no_data)
  为服务级,与源级健康并存但语义分级清晰(服务 vs 数据源),✓;
- **不一致**:「总服务客户」口径(AFP-004);「重试」标记语义
  (AFP-005);「补齐」badge(partial sync)是内部术语直出,建议
  「部分补齐(有缺口)」——并入 P2 备忘,未单列;
- 「拒答」在对话审查=拒答文案回答(含 off_topic),与业务概览「无关闲聊」
  分母口径不同(前者含商业拒答),可接受但建议文案统一「未作答」——
  备忘级,未单列。

## 11. Navigation / Deep-Link Review(AFP-D06)

- 侧边栏 8 项与路由一一对应,无死链;业务概览意图卡深链
  `/conversations?intent=*` 有效(对话审查按 URL 参数过滤 ✓);
- 技术洞察「在对话审查中排查」→ /conversations(通用,且明示限制)✓;
  「明细与操作 → 数据源管理」→ /data-sources ✓;
- 数据源行外链 github/camthink.ai 为源 URL 本身,语义正确 ✓;
- 失败深链 `/conversations?failure=true` 属 WEB-01 候选(基线无此参数),
  按 §16 规则未纳入基线走查结论;
- 浏览器后退/前进:全部列表页为 URL 参数态,可预期 ✓。

## 12. Empty / Loading / Error State Review(AFP-D04)

- 答案覆盖空态「暂无答案覆盖」✓;场景应用空态附下一步动作(「请先运行
  业务信号提取」+顶部刷新按钮)✓;满意度无数据「—」✓;
- 缺陷:空搜索无「无匹配」文案、viewer 403 吞成空表(AFP-008);
  加载态为纯文字「加载中...」,可接受;
- API 失败态(后端宕机)未专项演练(需停服务,影响共享环境)→
  见 NOT_VERIFIED。

## 13. RBAC Review(AFP-D08)

- 后端 RBAC 正确(viewer 写操作 403「权限不足」);侧边栏对 viewer 隐藏
  用户管理 ✓;
- 缺陷=AFP-002(按钮广告+403 空态)。未发现越权数据泄露(viewer 打不开
  用户列表数据,仅空壳)。

## 14. Visual Hierarchy Review(AFP-D03)

- 已验收的 Technical Insights 重构达到平静层级(横幅-三卡-诊断);
  遗留:趋势图红色主导(AFP-009);
- 业务概览四 KPI 平权但均有业务语义,意图分布双色条+深链可理解;
- 数据源页「删除」红色按钮行内直排(有 confirm 守卫)——可接受,
  备忘不单列;
- 模型配置流水线编号+「保存需重启」徽标清晰 ✓。

## 15. INT-CHK-008 Result(Admin 浏览器级人工走查)

**PASS**。覆盖:9 页面 × 真实登录 × 真实数据 × 双角色 × 桌面双宽度 ×
对话框 × 空态 × 错误态;0 控制台错误、0 失败请求、0 水平溢出;全部发现
均带浏览器截图证据。此前仅组件/单测覆盖的缺口已由本走查补齐。

## 16. WEB-01 Provisional Observations

- WEB-01 候选(0dc0f43)对 Admin/Widget 零改动 → **无 B 类发现**;
- 本发现全部结论不依赖 WEB-01 验收结果;
- 备注(非发现):worktree 后端运行的是 WEB-01 候选代码,但被走查的
  Admin 界面与后端 API 面(/tech/performance、/conversations 等)与
  基线行为一致(WEB-01 仅改 web_crawl connector 与 sync 脚本);
  数据源页显示的 website「2 篇/严重/一致性缺口」即 WEB-01 所修复问题的
  现网呈现,其修复效果依赖 WEB-01 验收,**不作为本报告发现**。

## 17. Evidence Index

docs 仓 `implementation/evidence/admin-final-polish-20260901/`:
- 截图 01-24(见 §3/§5 各条引用,文件名与发现对应);
- walkthrough-report.json(逐页链接/按钮/控制台/失败请求);
- viewer-report.json(viewer 侧边栏/按钮/页面正文头);
- overflow.txt(0 水平溢出)。

## 18. Recommended Final Polish Fix Set(供 Planner 裁量)

- 建议授权进入 Final Polish 修复合同:**AFP-002(SMALL)必做**;
  **AFP-001(MEDIUM)建议做**(治理风险,修复面收敛在删除端点+清理工具);
  P2 中 SMALL_FIX 六项(003/004/006/007/008/010)可打包一批;
  AFP-005/009 建议随 WEB-01 验收后一并处理(005 与 WEB-01 F-4 同源)。
- AFP-011 属新能力,需独立契约。

## 19. NOT_VERIFIED

- 后端宕机时各页 API 失败态 UI(需停共享服务,未演练);
- 编辑器(editor)角色的页面差异(仅验证 admin/viewer 两端);
- 真实 LLM 类按钮(批量标注/从 API 拉取)的端到端错误呈现;
- 删除数据源确认框后的实际删除链路(避免破坏共享开发数据,仅代码审计);
- Safari/Firefox 兼容(仅 Chromium)。

## 20. Final Discovery Status

DISCOVERY_COMPLETE —— CODE_CHANGED = NO。
无 P0;P1×2;P2×8;FUTURE×1;INT-CHK-008 = PASS。
本报告为发现清单,任何修复均待 Planner 授权后另行立约执行。
