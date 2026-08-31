# T1a-LAUNCH-PACKAGE Review — Phase 1(Gate-1,独立验收)

- 审查范围:`4db4c41 → bbfaa6a`(worktree `worktree-exec/t1a-launch`,未推送)
- 审查人:Role A(产品窗口)| 日期:2026-08-31
- **Verdict:Phase 1 = FINAL PASS;Gate-1 通过,放行推送(4db4c41..bbfaa6a 快进至 main)后进 Phase 2/3**

## Gate 1 — Contract Compliance:**PASS**

| 契约项 | 结果 | 证据 |
|---|---|---|
| T1 配置引导修复(四级逐键 fallback + 防双注入) | 满足 | Gate 2 代码审查 + Gate 3 TDD + Gate 4/5 判别器实测 |
| T2 `/widget` 托管(max-age=300、禁目录列表、镜像 admin 模式) | 满足 | AC2 审查端 curl 实证 |
| T3 构建链(CI widget build + Dockerfile COPY) | 满足 | diff 审计(各 +4/+1 行,最小变更) |
| AC1(三路径真实浏览器) | 满足 | 审查端独立 E2E 7/7(见 Gate 4/5) |
| AC2 | 满足 | 200 + `cache-control: public, max-age=300`;`/widget/` 404 且响应体零文件名;admin 深链 200 |

Deviation 裁定:①契约写 `backend/tests/*` 而仓库实际为根级 `tests/`——事实性路径差异,属 HOW,接受;②black 顺手重排已回滚,终 diff 仅 +28 行挂载块,核验属实;③primaryColor 不作判别器——合理(见下方产品观察)。

## Gate 2 — Scope Compliance / Change Audit:**PASS**

真实 diff = 7 文件 +317/-30,逐一核对全部 EXPECTED:`bootstrap.tsx`(新增,resolveConfig 逐键顺序与契约逐字一致、mountWidget 复用预置容器 + childElementCount 防重)/ `index.tsx`(32 行副作用 → 3 行入口)/ `main.py`(+28 行挂载块,CachedStaticFiles 仅覆写 Cache-Control)/ `tests/test_widget_hosting.py`(4 用例)/ `bootstrap.test.ts`(10 用例)/ CI workflow / Dockerfile。**零 UNEXPECTED;FORBIDDEN 面(pipeline/retrieval/connectors/api/admin/schema/CORS 代码)零触碰。**

## Gate 3 — Engineering Verification(独立复跑):**PASS**

审查端本机在 worktree 实际执行:widget vitest **27/27** + tsc 0;admin vitest **113/113** + tsc 0;后端 CI 口径 **447 passed**;`tests/api/admin + test_sync_db.py` **91 passed / 3 skipped / 0 failed**。

**与执行报告的一处差异(如实记录)**:执行端报 1 个失败(deepseek 掩码测试,当时主仓 baseline 同环境复现)→ 审查端新鲜运行**不复现**,全绿。判定:测试库瞬态数据状态(与其"数据状态预存"诊断相容),非本变更回归;审查结果以复现实验为准。测试库数据状态问题留待另开小任务(非本契约范围)。

## Gate 4/5 — Runtime / Real-World(审查端独立 E2E):**PASS**

方法:worktree 后端起于 **:8001**(ASKAI_API_PORT,零接触共享 :8000);测试页起于 localhost:5173(两个后端 CORS 白名单均含);**判别器 = Playwright 网络层捕获 `/api/ask` 请求主机**(比执行端的 performance entries 更底层,直接证明配置消费)。

| # | 检查 | 结果 |
|---|---|---|
| R1 | `data-api-url=127.0.0.1:8001` → 请求恰命中该主机(非默认) | PASS(426 字回答 + 6 来源) |
| R2 | `window.AskAIConfig` → 同上 | PASS(327 字 + 4 来源) |
| R3 | 无任何配置 → 请求恰命中默认 `localhost:8000` | PASS(452 字 + 6 来源,主仓后端 CORS 全通) |
| R4 | 双 script 注入 → 1 root / 1 FAB | PASS |
| AC2 | widget.js 200 + 缓存头;`/widget/` 404 零列表 | PASS |
| 回归 | `/admin/` 200、深链 200、`/health` 200 | PASS |

三路径主机互斥命中(R1/R2 不落默认、R3 不落 8001)= E4 缺陷关闭的直接证据。审查后清理:8001/5173 进程已停,共享 :8000 全程未动、终态健康。

## Remaining / 产品观察(转 backlog)

1. **AC3(镜像含 widget/dist)待 Phase 2 容器内实证**——本 Phase 以 CI/Dockerfile 变更 + 本地 249KB 产物佐证,契约本就排 Phase 2。
2. **primaryColor 配置当前零消费**:bootstrap 正确解析,但 UI 层无引用(执行端实证头部底色硬编码 #000000)。视觉区属 FORBIDDEN 未动,正确;但意味着 `data-primary-color` 现为 no-op——**转 T1b 品牌配置化范围**(wiki 灰度用默认品牌色不受影响)。
3. worktree 遗留环境工件(.env/软链/dist)均被 ignore/exclude,不进版本库,核验属实。

## Verdict

**Phase 1 = FINAL PASS。** 放行:推送 `worktree-exec/t1a-launch` → main(快进 `4db4c41..bbfaa6a`),CI 绿后按契约进 Phase 2(T4 发布)+ Phase 3(P-1 清洗),Gate-2 见。

## Gate-2 前置增补(Reviewer,2026-08-31,应用户"本地先测"要求核定)

本地已覆盖:Phase 1 全部单测/全量 + 审查端独立 E2E(本地全栈)。增补两项、明确一项不做:

1. **Phase 3 前置 P-1 本地演练**(增补,必做):在本地 postgres 完整走 pg_dump 备份 → DELETE conversations → 级联计数核验 → 备份恢复演练(恢复到临时库核对行数),全部原始输出入报告;生产序列照抄。
2. **Phase 2 增补 CORS 头实证**:T4 生效后 `curl -sI -H "Origin: https://wiki.camthink.ai"` 与 `Origin: https://www.camthink.ai"` 各打一次 `/api/ask` 预检(OPTIONS)与简单 GET,核响应含正确 `Access-Control-Allow-Origin`,截图/原始输出入报告。
3. **不做本地镜像构建**(核定):mac arm64 vs 生产 amd64+GPU 不等价且成本高;AC3 维持 Phase 2 容器内实证。

**执行偏差记录(同日)**:执行端已持**增补前**提示词开工(用户告知,中断成本高于增量价值,不召回)。裁定:原提示词已含安全底线(磁盘前置/P-1 备份先行/版本双验证/Gate-2 停点),上述两项转移为 **Gate-2 审查侧核验**——①CORS 头:审查端从公网 curl 带 Origin 头直接验证(无需 ssh);②P-1:审查端核执行报告的备份文件路径+行数对账证据,必要时 ssh 抽查备份文件存在性与大小。

---

# Gate-2 审查(Phase 2 发布 + Phase 3 P-1,2026-08-31 午后)

执行端交付:推送(CI 33360499079)+ T4 发布(bbfaa6a)+ P-1 清洗(632 条,备份+金标准恢复对账)。**审查端独立复核,全部证实:**

| 项 | 审查端独立证据 | 结果 |
|---|---|---|
| 推送 | main = origin/main = bbfaa6a,ahead 0;gh 查证 CI 33360499079 success,headSha 一致 | ✅ |
| 部署产物 | **公网 widget.js SHA256 == 本地审查版**(a9065b57…)——密码学级证实部署即所审 | ✅ |
| AC3 | (报告)容器内 ls dist + 字节数;审查端以公网哈希对账覆盖 | ✅ |
| AC2 公网 | widget.js 200 + cache-control max-age=300;`/widget/` 404 | ✅ |
| CORS | 公网带 Origin 实测:wiki→ACAO wiki ✓;www→ACOA www ✓;**localhost:3000→400 无 ACAO(正确拒绝)**——行为级证实 T4 env 只含两生产 origin | ✅ |
| AC6 P-1 | ssh 只读独立核:备份文件在(`/home/ubuntu/ask-ai-p1-…-20260831.sql`,2,025,109B 与报告一致);conversations/traces/source_clicks = **0/0/0**,business_signals = 31 | ✅ |

**两处事实修正,裁定采纳(Planner 假设错误,如实记录)**:
1. 契约"追加两 origin、保留 localhost 行"基于本地 .env 形态的错误外推——**FACT:T4 .env 本就只有两生产 origin**(无 localhost 行),目标状态早已满足。执行端 sed 误造重复后停-恢复-diff 核验,处置正确(协议"发现不符即停"的标准行为)。
2. E7 所列 feedback"表"实为 conversations 的列(随行删除);business_signals 无 conversation 外键(采样列),不级联——实测 31 行不动无孤儿,与该语义一致。627(08-30 推断)→ 实测 632,以实测为准。

**审查侧吸收项闭环**:①CORS 头(上表);②备份可用性——执行端用**金标准**(恢复进一次性库 p1_verify 对账 632/261/0 一致后删库)完成,强于审查端原方案。

**Verdict:Phase 2/3 = FINAL PASS(Gate-2 通过)。** 生产已运行 bbfaa6a、widget 公网可加载、CORS 双 origin 放行、数据池清零。剩余:Phase 4 wiki 嵌入,**等用户"wiki 上线确认"**(契约 Gate-3)。
