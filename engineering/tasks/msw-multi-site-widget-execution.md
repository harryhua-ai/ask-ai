# MSW(CAMTHINK_V1_MULTI_SITE_WIDGET_INTEGRATION)— 执行记录

Date: 2026-09-01 · Executor 执行窗
完整报告:`docs/implementation/CAMTHINK_V1_MULTI_SITE_WIDGET_INTEGRATION_2026-09-01.md`(三十节全)
计划:`engineering/tasks/msw-multi-site-widget-plan.md` · 证据:`engineering/tasks/msw-evidence/`(E1–E12 + 六截图)

## 结果

- STATUS = **PASS**(自评;Planner 独立验收为准)
- Baseline `e945f59` → FINAL_COMMIT `441f22d`,8 提交线性,已推 `origin/worktree-exec/multi-site-widget`
- 后端全量:722 passed / 4 failed(embedder 离线 OSError,**基线同环境已证实为预存**)/ 5 skipped;新增 48 测试
- Widget:57/57 + tsc + build 绿
- SITE-G001..G012 全覆盖(自动化 + 隔离栈 :8012 实跑 + Playwright 浏览器证据)

## 架构一句话

sites.yaml(权威)→ site_experiences 表(幂等 upsert)→ /api/widget/site-config +
/ask 站点门禁(服务端 Origin 精确授权,fail-safe 403);page_context 消毒后仅软加分(1.2×,不过滤)
+ user 消息「非指令」背景段;conversations.site_id 落库,channel 恒 widget;legacy 请求体逐键不变。

## 环境自证

```text
WORKTREE: /Users/harryhua/Documents/GitHub/ask-ai/.worktrees/multi-site-widget / 分支 worktree-exec/multi-site-widget
BACKEND_PORT: 8012(health 实测 200;隔离库 ask_ai_msw)
未重新下载权重 / 未动 8000 主后端 / 未写共享 weaviate(仅只读)
```

## 过程要点(坑与裁决)

1. 全量回归首跑 hang 23min:未设 HF_HUB_OFFLINE=1 → embedder 测试联网查找被卡;加离线变量后 47–58s 跑完。
2. 首跑 18 个 admin ERROR:被强杀运行遗留的脏库状态;清态复跑消失(非代码回归)。
3. 我的 legacy 用例全量回归时吃假 429:slowapi 20/min 进程内计数被套件累计挤爆 → 测试文件内加
   `limiter.reset()` autouse fixture(T7 提交)。
4. embedder 4 失败:建基线 worktree 复跑同样失败 → 判预存环境性,不掩埋、如实上报。
5. TDD 真拦截一处实现缺陷:拒答路径 trace 引用未初始化 page_boost_stage(UnboundLocalError),
   RED 套件跑出的,非人为评审发现。
6. black 只植增量:格式化后逐一核对 diff 均落在本任务新增行;ruff 全仓本就不清白(77 处),
   本任务文件新增 lint = 0(仅存量 3 处与基线一致)。

## 部署红线(交 Planner/发布窗)

- 生产 + 本地主库须跑 `scripts/migrate_add_site_experiences.py`(幂等);
- CORS_ALLOW_ORIGINS 补三站点 origin;
- 核对 wiki/store 域名假设(wiki.camthink.ai / store.camthink.ai)。

## Acceptance Cleanup 附记(2026-09-01)

Planner 初审卫生项已清:441f22d 误入的 `.playwright-cli/` 临时产物(18 文件)已在 `2d27dd8` 删除 + `.gitignore` 补 `.playwright-cli/`;零产品变更;回归与清理前一致(722P/4F 环境既有/5S + Widget 57/57)。详见实现报告 Addendum。
