# CAMTHINK V1 — 正式生产部署 + Production Smoke Acceptance 报告

- 日期:2026-09-03
- **STATUS: PRODUCTION_DEPLOYMENT_PASS**
- DEPLOYMENT_START: **2026-09-03T06:20:55Z** / DEPLOYMENT_END: **2026-09-03T06:45:25Z**(UTC)
- OLD_RELEASE: `sha-269cadb` → **FINAL_RUNNING_RELEASE: `sha-1d6f6b5`**(完整 SHA `1d6f6b5fe697b5f7a1b8decef1c29f51afcda937`)
- ROLLBACK_USED: **NO**
- PRODUCTION_MUTATIONS(恰在授权范围内):
  1. 拉取镜像 ghcr.io/harryhua-ai/ask-ai:sha-1d6f6b5;
  2. 执行 additive migration `scripts/migrate_add_sync_runs.py`(新建 sync_runs 表+部分唯一索引,幂等);
  3. `./deploy/prod/update.sh sha-1d6f6b5`(backend+sync-cron,既有生产流程);
  4. 显式 `ASKAI_IMAGE_TAG=sha-1d6f6b5 docker compose up -d sync-executor`(runbook 步骤,避免混跑);
  5. Smoke 产生的运行时数据:3 次问答会话、1 次手动增量同步请求(request id=1,业务增量、非破坏)。
- 未触碰:业务数据删除/修改、reindex、collection、secrets、站点配置、CORS、compose、代码。

## FRESHNESS GUARD(部署前实测)

- origin/main == 1d6f6b5 ✓;三服务均 sha-269cadb ✓;DB:sync_requests 在位+4 恢复列在位+sync_runs 不存在 ✓;backend health 200 ✓。与 Readiness Gate 无 material drift。

## PRE-DEPLOY SNAPSHOT

backend/sync-cron/sync-executor = ghcr.io/harryhua-ai/ask-ai:sha-269cadb(running;backend healthy);postgres 16-alpine(Up 2 weeks healthy);weaviate 1.28.0(healthy);health=200;磁盘 950G 可用。

## MIGRATION_RESULT: PASS

`migrate_add_sync_runs.py` 一次性容器执行 → `OK: sync_runs 就绪(17 列,身份索引在位,幂等迁移完成)`;迁移后实测:sync_runs=1 表、17 列、`uq_sync_runs_request_source_attempt` 索引在位;原 19 表无损、conversations=130 行原样。

## SERVICE_VERSIONS(Gate P1,读取真实 running 容器)

| 服务 | image | revision label | status |
| --- | --- | --- | --- |
| backend | ghcr.io/harryhua-ai/ask-ai:sha-1d6f6b5 | 1d6f6b5fe697b5f7a1b8decef1c29f51afcda937 | running/healthy,restarts=0 |
| sync-cron | 同上 | 同上 | running,restarts=0 |
| sync-executor | 同上 | 同上 | running,restarts=0 |

三服务版本统一 ✓(非仅 compose 配置判断)。

## SMOKE_RESULTS

| Gate | 结果 | 证据 |
| --- | --- | --- |
| P1 Release Identity | PASS | 三容器 image+revision 全 = sha-1d6f6b5 / 1d6f6b5(完整 SHA) |
| P2 Backend | PASS | health 200 `{"status":"ok"}`;restarts=0;错误/traceback/migration 错误日志 0 行 |
| P3 Admin | PASS | /admin/ 200;管理员登录 + Conversations API 正常读取(total=130);outcome 分类所需字段(is_answered/trace_summary/language)全部在 API 载荷中,前端 deriveOutcome(190 单测+构建已验)可正常渲染 |
| P4 Widget/三站 | PASS(附既有边界) | widget.js(`/widget/widget.js`)200;CORS 预检 www.camthink.ai ✓、wiki.camthink.ai ✓(精确 ACAO 回显);store.camthink.ai 域名公网 DNS 不解析+apex/ 预检 400 —— **部署前既有状态**(prod CORS env 未在本次触碰,与 handoff 期「store 待补」记录一致),非本次回归 |
| P5 中英问答 | PASS | EN:74 事件/72 token,sources 含 github/web_crawl/woocommerce 三源真实引用,conversation 落库 language=en/is_answered=t;ZH:90 token,落库 language=**zh**(Stage⑯ 归一新写入 ✓),中文问题原文入库 |
| P6 无证据拒答 | PASS | 知识库外问题 → 流式中文本地化拒答文案 + done+conversation_id;is_answered=f;无 500/空响应/幻觉报错 |
| P7 Stage⑯ 失败语义 | **NOT_TRIGGERED_SAFE** | 未注入故障;存量证据兼容性已验:13 条 is_answered=false + trace 血统(generation_error/reject_short)在库,outcome 模型输入齐备 |
| P8 Sync Request(Wave-0) | PASS | 见下节 |
| P9 既有知识 | PASS | EN/ZH 问答均命中既有 corpus(NE503 引用);增量同步实证「documents 已有 179,无变更跳过」 |
| P10 稳定窗口 | PASS | backend 起于 06:21Z,观测至 06:44Z(23 分钟>15 分钟):health 200(本地+公网)、三服务 restarts=0、坏日志 0 行、sync_runs=16 稳定、conversations=133(含 smoke 3 条) |

## SYNC_RUNTIME_EVIDENCE(P8 核心)

手动触发(Admin API,业务增量)→ `{"status":"accepted","request_id":1}`:

```
sync_requests  id=1  knowledge-support-cases  manual  attempt=1  done  exit=0
   └─ sync_runs     request_id=1  attempt=1  status=completed  sync_log_id 回填 ✓(恰 1 行,身份约束下唯一)
        └─ sync_log  同源同窗口  status=success(业务结局)
```

自然路径并证:sync-cron 重启即跑的增量同步产出 SyncRun id=13/14/15(woocommerce-mall/wiki-documents-local/website-camthink,**request_id=NULL 合法直跑**,completed/stage=DONE/log 链接=t)。合计 **sync_runs=16,16/16 终态,1 条 request-backed + 15 条 cron 直跑**——双路径在真实生产全部落地。

## STABILITY_WINDOW

06:21Z(backend 起)至 06:44Z,23 分钟:health 200(localhost:18000 + 公网域名);三服务 restarts=0;backend 近 20 分钟坏日志 0;executor 日志仅 INFO(无变更跳过);PostgreSQL 无错误事件;无 5xx。

## REGRESSIONS

**NONE**(所有 Gate PASS)。

## KNOWN_LIMITATIONS

1. **SAWarning(无害,后续小修候选)**:sync_executor_loop.py:281 SQLAlchemy 提示 SELECT 应显式 `.scalar_subquery()`——功能正确(本轮链路证据齐全),按「禁临场 hotfix」未动,建议并入下一窗口;
2. **store.camthink.ai 公网 DNS 不解析 + apex/ 预检 400**:部署前既有配置/域名状态(CORS env 与站点配置本次零触碰),与 Wave-0/Stage⑯ 无关;store Widget 对接本就处于「待补」状态(交接记录),待合作方窗口推进;
3. embedder 4 用例离线证据(见集成门报告)为测试环境事实,生产镜像模型挂载完整,无影响;
4. update.sh 仍不覆盖 sync-executor(本次以显式步骤补齐)——流程改进候选,非本次范围。

## REPORT_PATH / COMMIT

- 本报告:docs/implementation/CAMTHINK_V1_PRODUCTION_DEPLOYMENT_2026-09-03.md
- 未记录任何 secret/token/password(smoke 凭证仅存于会话内存,报告不含)。
