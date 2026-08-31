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
