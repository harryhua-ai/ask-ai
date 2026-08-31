# T1a-LAUNCH-PACKAGE Execution Contract(实例最小上线包)

- **Task ID**:t1a-launch-package | **Parent Initiative**:T1a 实例最小上线包(roadmap §3-D1)
- **Baseline Commit**:`4db4c41`(main = origin/main,CI 33355154229 success)
- **Risk Level**:**L3**(生产 CORS 配置变更 + 不可逆数据删除(P-1,已拍板含备份前置)+ 公网站点变更(wiki 上线时刻用户确认))
- **Contract Authorization**:**AUTHORIZED**(2026-08-31,Role A 签发)——所涉 material 用户决策均已拍板:D-10 三站点、P-1 存量清洗(2026-08-30,备份+cutoff+全删)、灰度顺序 wiki→官网→商城;无新增待决产品语义。唯一运行时门:Phase 4 wiki 公网上线时刻须用户一句确认(操作门,非产品决策)。
- **执行方式**:独立 worktree(`worktree-exec/t1a-launch`),逐 Phase commit。

---

## 1. Objective

把 widget 从"开发完成"推进到"wiki 灰度上线":widget.js 由生产 backend 托管 + CORS 放行目标站点 + P-1 存量清洗 + wiki 站点真实嵌入,启动北极星观察期第 1 周(观察模式,只出基线不设阈值)。

## 2. Product Intent

- 访客在 wiki 页面右下角看到助手浮窗,提问得到带来源引用的真实回答——**产品的第一个真实用户触点**;
- 数据池从零积累(P-1),北极星信号(自助解决率/有效线索)自灰度日起干净;
- 官网/商城为后续波次,本契约只做 wiki 波次的前置全部条件。

## 3. Current State / Evidence(Inspect @ 4db4c41)

| # | 事实 | 级别 |
|---|---|---|
| E1 | CORS 纯 env 控制(`main.py:437-451`),默认 localhost 三件套;allow_methods GET/POST | FACT |
| E2 | admin 托管模式:`_admin_dist` 存在才挂 `SPAStaticFiles` 于 `/admin`(`main.py:455-481`),widget 可镜像 | FACT |
| E3 | Dockerfile 仅 `COPY admin/dist`(:65);CI 仅 build admin(:70-72,widget 只 `npm ci` 不 build) | FACT |
| E4 | **widget 配置引导缺陷**:`index.tsx:16-28` 从脚本自建 div 读 data-*,嵌入页 `<script data-api-url>` 传参不可达;实际仅 `window.AskAIConfig.apiUrl` 生效;默认 fallback `http://localhost:8000` | FACT |
| E5 | widget 构建:vite lib IIFE,产物 `widget/dist/widget.js`;配置面 `data-api-url`/`data-language`/`data-primary-color`(类型层存在) | FACT |
| E6 | 生产入口 wiki-data.camthink.ai → backend :18000(T4);生产 CORS 需加 `https://wiki.camthink.ai` + `https://www.camthink.ai`(商城与官网同 origin) | FACT |
| E7 | P-1 对象:conversations 全表(级联 traces[delete-orphan/CASCADE]、source_clicks[CASCADE]、feedback[CASCADE];business_signals SET NULL);08-30 计划数字 627 条 | FACT / 条数 INFERENCE(执行时实测) |
| E8 | wiki 站点 = Docusaurus(数据源 wiki-47909975),嵌入点具体文件未核 | UNKNOWN(Phase 4 前执行端 Inspect) |

## 4. Scope(四 Phase)

**Phase 1 — 代码包(B 执行,本契约核心)**:
- T1 widget 配置引导修复:读 `document.currentScript` 的 dataset(`data-api-url`/`data-language`/`data-primary-color`),fallback 顺序 script dataset → 页面预置 `#ask-ai-widget-root` 元素 dataset(若存在则复用该元素而非新建)→ `window.AskAIConfig` → 现默认值;
- T2 backend 托管:`/widget` 挂 StaticFiles 指向 `widget/dist`(镜像 E2 模式,无需 SPA 回退);响应头 `Cache-Control: public, max-age=300`(冻结:更新 5 分钟内生效);
- T3 构建链:CI 增 widget build;Dockerfile 增 `COPY widget/dist /app/widget/dist`。

**Phase 2 — 发布(T4)**:update.sh 部署 → health(BGE 慢启动 ~45s 属预期)→ 容器内版本双验证(widget 挂载代码 + git-sha)→ T4 `.env` 追加 E6 两 origin → 公网 `GET /widget/widget.js` 可达。

**Phase 3 — P-1 清洗(T4 DB,不可逆,备份前置)**:pg_dump 导出 conversations 及级联表(单文件含 schema+data)→ 核对备份行数 → DELETE conversations 全表 → 复核 0 行 + 级联表清零(SET NULL 表除外)→ 备份文件留 T4 并记录路径。

**Phase 4 — wiki 灰度嵌入(公网变更,用户确认时刻后执行)**:Inspect E8 定嵌入点 → wiki 仓库加一行 `<script src="https://wiki-data.camthink.ai/widget/widget.js" data-api-url="https://wiki-data.camthink.ai" defer></script>` → 部署上线 → 真实浏览器验收(§8)。

## 5. Non-goals

官网/商城嵌入(后续波次);T1b 品牌配置化;灰度阈值冻结(week 2+ 由用户批);widget 视觉/多语言改造;API key/集成方认证;意图/管线任何改动;`/widget` 目录列表(禁 `html=True` 类目录浏览)。

## 6. Change Boundary

**Product**:允许新增 = 公网可加载 widget.js、wiki 页出现助手浮窗、conversations 清零;必须不变 = 现有问答行为、admin 功能、admin 托管、拒答/引用交互。
**Code EXPECTED**:`widget/src/index.tsx`(+少量 types/tests)、`backend/main.py`(挂载段)、`Dockerfile`、`.github/workflows/build-image.yml`、`widget/tests/*`、`backend/tests/*`(挂载测试)。
**CONDITIONAL**:T4 `.env`(CORS 行)、wiki-documents 仓库(仅一行 script)、`deploy/` 文档小节。
**FORBIDDEN**:`backend/pipeline|retrieval|connectors|api/`、DB schema、`admin/`(除零依赖类型共享)、widget UI 组件视觉、CORS 中间件代码逻辑、conversations 以外任何数据。
**System**:无 schema 变更;新增公开静态路由 `/widget/widget.js`(内容无敏感信息,与 admin 静态同级);无依赖变更。
**Regression**:admin SPA 托管不受影响;widget 既有 vitest 全绿;CI 全绿;`/health` 不变。

## 7. Frozen Contract

1. widget.js 由生产 backend 托管于 `/widget/widget.js`(Cache-Control max-age=300);
2. 嵌入页配置以 `<script data-*>` 为一等公民(引导顺序见 Phase 1-T1);
3. 生产 CORS 追加 `https://wiki.camthink.ai,https://www.camthink.ai`(保留既有 localhost 行);
4. P-1:先备份后 DELETE conversations 全表,备份可独立恢复;
5. wiki 上线 = 一行 script + defer;上线时刻用户确认;
6. 灰度 week 1 = 观察模式:只采集基线,不设阈值,不出判定。

## 8. Acceptance Criteria

| # | 验收 | 通过标准 |
|---|---|---|
| AC1 | 配置引导 | 本地跨 origin 测试页(`<script data-api-url>` 传参)真实加载 widget 并完成一次带 sources 的问答;jsdom 单测覆盖三级 fallback |
| AC2 | 托管与缓存 | `/widget/widget.js` 返回 200 + `Cache-Control: public, max-age=300`;`/widget/` 无目录列表 |
| AC3 | 构建链 | CI 全绿,镜像含 widget/dist(容器内 ls 实证) |
| AC4 | 发布验证 | T4 health ok + 容器内双版本特征 + 公网 GET widget.js 200 |
| AC5 | CORS | 从 `https://wiki.camthink.ai` 页面发起的 API 预检/请求无 CORS 报错(浏览器 console 实证);localhost 三件套不回归 |
| AC6 | P-1 | 备份文件存在且 `pg_restore`/导入行数对账一致;conversations=0;级联表符合级联语义 |
| AC7 | wiki 灰度 | 真实浏览器(无痕)打开 wiki 任意文档页:浮窗出现 → 提问 → 流式回答 + 来源引用 + 👍/👎 可点;对话落库 channel=widget |
| AC8 | 基线报告 | 灰度日 +7 天产出 week-1 基线报告(模板:日对话量/拒答率/反馈率/P95/来源点击率/Top 未答问题),数据取自现有表,零新代码 |

## 9. Real-World Acceptance(必须真实执行,不可用测试替代)

AC1/AC5/AC7 为 Real-World Gate:真实浏览器、真实跨 origin、真实公网 wiki 页面、真实问答流。**AC7 未执行 = FINAL PASS 禁止**(协议 PART XVIII)。

## 10. Regression Constraints

全量 pytest(CI 口径 + `tests/api/admin` + `test_sync_db.py`)+ admin vitest 全绿;`/admin` 深链刷新仍可用;widget 原有 vitest 断言不得削弱。

## 11. Required Verification

Phase 1:TDD(配置引导先红后绿)+ 上述全量;Phase 2-4:每步留原始输出(命令+响应);对抗性:重复注入 script 标签两次不产生双浮窗(如实现需防重,复用既有 id 判定)。

## 12. Dependencies / Parallelization

串行为主(Phase 1→Review→push→2→3→4);Phase 4 的 wiki 仓库 Inspect 可与 Phase 2/3 并行。单 executor。

## 13. Stage Gates(执行节奏)

- **Gate-1**:Phase 1 完成即停 → 报 CANDIDATE READY(代码部分)→ Review 放行 push;
- **Gate-2**:Phase 2+3 完成即停 → 运行时证据回报 → Review;
- **Gate-3**:Phase 4 前向用户要"wiki 上线确认"一句话 → 执行 → AC7/AC8 采数计划启动。
- 报告:`docs/engineering/tasks/t1a-launch-package-execution.md`(按 v2.0 §77 字段,分 Phase 追加)。

---

## 执行提示词(复制给执行端)

```text
# 任务:T1a-LAUNCH-PACKAGE Phase 1(widget 代码包)

你是 Senior Engineering Executor,先读:
- /Users/harryhua/Documents/GitHub/ask-ai/docs/engineering/DUAL_AGENT_PROTOCOL.md
- /Users/harryhua/Documents/GitHub/ask-ai/docs/engineering/role-B.md
- /Users/harryhua/Documents/GitHub/ask-ai/docs/engineering/tasks/t1a-launch-package-plan.md(权威契约)

本次只执行 Phase 1(T1 配置引导修复 / T2 /widget 托管 / T3 构建链),
完成即停等 Review,不做 Phase 2-4。

要点:
1. 独立 worktree(基于 4db4c41),TDD:先写红测再实现;
2. T1 严格按契约 fallback 顺序(currentScript dataset → 预置 #ask-ai-widget-root
   → window.AskAIConfig → 默认);注意 script 注入两次不得出现双浮窗;
3. T2 挂载镜像 main.py:455-481 admin 模式,Cache-Control: public, max-age=300,
   /widget/ 禁目录列表;
4. T3:CI 加 widget build;Dockerfile 加 COPY widget/dist;
5. 验证(全部实际执行):widget vitest + admin vitest + tsc + 后端全量
   (TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test,
   CI 口径 + tests/api/admin + tests/scripts/test_sync_db.py)+
   AC1 本地跨 origin 真实浏览器验证(起本地 backend,用一个非 8000 origin 的
   测试页 <script data-api-url="http://localhost:8000"> 加载,真实提问得 sources);
6. 报告:docs/engineering/tasks/t1a-launch-package-execution.md(Phase 1 节,
   按 v2.0 §77 字段),回复给报告路径 + commit + 状态(CANDIDATE READY/PARTIAL/FAIL/BLOCKED)。

红线:不动 pipeline/retrieval/connectors/api/、不动 admin/、不动 schema、
不 push、不部署、不碰任何数据;docs/ 不进主仓提交。
```
