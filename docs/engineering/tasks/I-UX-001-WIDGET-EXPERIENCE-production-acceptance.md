# I-UX-001 Production Release / Runtime Acceptance Report

- 日期:2026-09-09(UTC)
- 模式:AUTHORIZED PRODUCTION RELEASE / RUNTIME ACCEPTANCE GATE(发布 accepted main
  `8bec1c0` 并以真实浏览器/运行时证据证明源→工件→迁移→行为一致)
- **STATUS = PRODUCTION CANDIDATE VERIFIED**(B 级上限;Production Acceptance 由 Role A 独立裁定)

- EXECUTOR STATUS:**PRODUCTION CANDIDATE VERIFIED**(本报告全部结论均为执行端 B 级证据,不构成 FINAL PASS)
- ROLE A FINAL ACCEPTANCE:**PENDING**(Role A 现行裁决 = PROVISIONAL PASS,以本证据集独立可读为 FINAL PASS 前置;裁决归属 Role A)
- 证据发布:本报告与 `artifacts/I-UX-001-v1.3.0-production/`(含观察窗 transcript)以
  `review/iux001-v130-production-acceptance-20260910` 分支发布,供 Role A 独立读取;
  逐项映射见 `I-UX-001-WIDGET-EXPERIENCE-production-artifacts.md`。

## 1. Deployed Revision / Artifact(Gate 1)

| 项 | 值 |
| --- | --- |
| AUTHORITATIVE_SOURCE | `8bec1c0251d25630b5e2d461a9a5671cb2841b34`(accepted main;Role A FINAL PASS) |
| Release tag | `v1.3.0`(annotated,打在 8bec1c0;含 I-UX-001 全量 + I-002 比较门矫正 273a885) |
| TARGET_IMAGE | `ghcr.io/harryhua-ai/ask-ai:v1.3.0` |
| CI build | run `34342510200`(tag 触发,success;构建 ~11min) |
| 镜像内 RELEASE.json(目标镜像拉取后 docker cp 实测) | `version=1.3.0, git_sha=8bec1c0251d25630b5e2d461a9a5671cb2841b34, ci_run_id=34342510200, built_at=2026-09-09T10:56:12Z` |
| 运行时身份 | `GET /health` → `{"status":"ok","version":"1.3.0","git_sha":"8bec1c0…","app_mode":"production"}`;启动日志 `release identity: version=1.3.0 git_sha=8bec1c0… source=manifest` |

源 → 工件 → 运行时三者 git_sha 逐字一致 [FACT]。

## 2. Deployment Evidence(既有 runbook,零绕过)

- 机制:`deploy/prod/update.sh v1.3.0`(tesla-t4,六步:拉取→镜像内 RELEASE 断言→GPU
  预检→三服务同批 `up -d`(ASKAI_IMAGE_TAG 注入)→backend 健康轮询+运行时版本核验)。
- 部署前三服务均为 v1.2.1(Up 22h healthy);postgres/weaviate 未触碰(Up 3 weeks)。
- 部署后三服务同批 = v1.3.0:backend(healthy)/ sync-cron / sync-executor [FACT]。
- Preflight:磁盘 940G 可用;GPU 12.8/16GB(<15G 告警线);无并发变更;BGE 慢加载
  (~45s)由 update.sh 健康轮询覆盖,backend 最终 healthy [FACT]。
- 回滚锚:`./deploy/prod/update.sh v1.2.1`(镜像与库均在位,runbook 内建)。

## 3. Migration / Schema Evidence(Gate 2)

- 执行方式 = 仓库既有模式(sha-193f206 部署先例):先拉目标镜像,
  `ASKAI_IMAGE_TAG=v1.3.0 docker compose run --rm --no-deps backend python
  scripts/migrate_add_widget_experience.py`(一次性容器,旧容器全程未动)。
- Pre-state 实测:`site_experiences` 无 `entry_mode` 列;3 行既有站点
  (camthink-store/website/wiki)。
- 执行输出:`✅ site_experiences experience 列 + site_trusted_actions 表已确保存在`。
- Post-state 实测(information_schema):10 个新列全部存在(varchar);
  `site_trusted_actions` 表已创建(0 行);
  **3 个既有站点 entry_mode/greeting_override 全 NULL(legacy 语义保持)** ✓。
- 重启(reseed)后既有行仍 NULL —— lifespan seed 只更新 YAML 权威字段、绝不覆写
  experience 列的行为在生产得到实证 [FACT]。
- **new-site default(C)语义**:生产上未直接行使(生产站点仅由镜像内 YAML seed
  创建,本次不新增正式站点);以迁移契约 + `seed_default_sites` 单测
  (test_seed_new_site_defaults_mini_entry_and_preserves_existing)与既有行 NULL 的
  生产实证为证据链。见 §10 Known Limitations。

## 4. Runtime Environment

- tesla-t4(Ubuntu 22.04 / T4 16GB),compose project `tesla-t4`,对外
  `https://wiki-data.camthink.ai`(nginx HTTPS,SSE proxy_buffering off)。
- 浏览器证据端:本地 Chromium(Playwright),fixture 页面 `http://127.0.0.1:4174`。

## 5. 安全测试目标(任务要求声明)

- 生产无 Admin 建站 API(站点仅由 YAML seed 创建);为不触碰 3 个正式站点,采用
  **可逆 fixture**:`site_experiences` 新增 `iux001-acceptance`(显式 test 命名,
  entry_mode=mini_entry / proactive_timing=balanced / allowed_origins 仅测试来源),
  证据采集后**已删除**(级联删除其 Trusted Actions;删除后 count 实测 3 行/0 行)。
- 生产 `.env` 的 `CORS_ALLOW_ORIGINS` 临时追加 `http://127.0.0.1:4174`(先备份
  `.env.bak_iux001_acceptance`),验收后**已还原并重启验证**(grep 0 命中)。
- 未污染任何正式客户配置;正式站点全程 NULL/legacy。

## 6. Browser Scenarios Executed(Gates 3-11)

截图:`docs/engineering/tasks/iux001-prod-artifacts/prod-*.png`(7 张)。

| # | 场景 | 证据 | 判定 |
| --- | --- | --- | --- |
| 3 | Admin Widget 体验页真实可访问 | 浏览器登录 `https://wiki-data.camthink.ai/admin/widget-experience`:站点列表(3 正式站=保持现状(未配置),fixture=C)、入口四卡、可信动作区全渲染;screenshot | PASS |
| 4 | public site-config 正确 | fixture:`entry_mode=mini_entry, proactive_timing=balanced, trusted_actions=[published 的 Specifications]`;legacy 站 `camthink-website`:entry_mode=None, actions=[] | PASS |
| 5 | visitor Widget 真实加载 | 生产 `/widget/widget.js` + `/widget/ask-ai-widget.css` 经真实页面加载,site-config 拉取成功,零 console error | PASS |
| 6 | desktop C proactive | balanced ~6s 后 C mini 自动展开(`mini=1`,每会话一次由 session 闸保证) | PASS |
| 7 | C→floating chat→真实 ASK | 点击动作 → 浮动窗打开 + 恰 1 个 `POST /api/ask`,请求体实测 `message="What are the specifications of NE503?"`(占位符已按页面上下文绑定),`channel=widget, site_id=iux001-acceptance, page_context={product:NE503…}` | PASS |
| 8a | PUBLISHED 可见 / VERIFIED 不暴露 | fixture 两个动作: Specifications(test→verify→**published**)与 Find docs(test→verify 后**停留 verified**);public site-config 仅返回 published;UI chip 数=1 | PASS |
| 8b | DRAFT 不暴露 | draft 在 verify/publish 前从未出现于 site-config(生命周期 API 实测) | PASS |
| 8c | context 正确绑定 | 请求体为绑定后问句(见 #7),`refs=2` 真实生产语料回答 | PASS |
| 8d | missing context fail-closed | 无 pageContext 页面:chip **不渲染**(0 个)、`/api/ask` **0 次**、问候回落通用(无专名伪造) | PASS |
| 8e | 无 unresolved placeholder | 已发请求体含绑定问句;模板原文从未发送 | PASS |
| 9 | mobile 保持 B nudge | 390×844:`mini=0`(绝不自动展开)、`nudge=1`(上下文问候+dismiss)、nudge 点击(显式交互)→聊天打开 | PASS |
| 10 | citations/streaming/既有能力 | 真实流式回答(生产语料,NE503 规格)渲染 2 个行内引用徽标,无重复 Sources 段;对话持久化正常(conversation_id/done 事件) | PASS |
| 11 | console/network 无新 blocker error | 全场景 console error=0、requestfailed=0(初次 fixture 的 CORS 4xx 属测试配置问题,修正后复测干净;如实记录) | PASS |
| 12 | production smoke/health | `/health` 200 全程 1.3.0+8bec1c0;三容器 healthy/running;观察窗 3 检查点(≈10min)restarts=0、traceback/OOM/fatal=0 | PASS |

## 7. Trusted Action Lifecycle Evidence(生产实测)

```
create(draft)  → Specifications / Find docs 均 draft
test           → 真实 ASK-AI 管道(production RAG;Specifications 实测返回
                 规格类回答 + 3 sources;last_test_result 落库)
verify         → verified(依赖 last_test_result;未 test 直接 verify 被拒的
                 语义由 8 后端测试继续保障)
publish        → published(仅 verified 可发布)
exposure       → public site-config 仅 published;verified(Find docs)不可见
cleanup        → fixture 站点删除 → 动作级联删除(实测 0 行)
```

## 8. Regression Smoke(既有能力)

- legacy 站点 site-config 语义正确(NULL → 访客面保持既有行为)✓
- 问答核心流(SSE sources→token→done、引用、会话持久化)✓(v1.2.1 门同款冒烟形态)
- postgres/weaviate 零触碰(Up 3 weeks);sync-cron/sync-executor 同批升级后正常
  运行(观察窗零错误)✓
- 本任务零码树变更(无 correction commit;发现的两处操作性事项见 §9,均非产品缺陷)

## 9. 操作性发现(不构成 runtime defect,均已解决并记录)

1. **迁移脚本 sys.path 引导缺失**:`scripts/migrate_add_widget_experience.py` 直接
   `import backend`,而镜像内以 `python scripts/x.py` 运行时 sys.path[0]=/app/scripts
   (仓库旧迁移脚本均有 bootstrap 行,本脚本缺失,属脚本与仓库惯例的偏差)。
   运行侧以 `-e PYTHONPATH=/app` 解决(一次性容器 env,零代码改动)。建议后续
   correction task 给脚本补 bootstrap 行,与仓库惯例对齐。
2. **DSN guard 生产触发(按设计工作)**:生产 `.env` 携带 `TEST_DATABASE_URL`,
   `resolve_migration_dsn` fail-closed 拒绝执行(正是该守卫的设计目的);运行侧以
   `-e TEST_DATABASE_URL=` 清空覆盖后执行,迁移如实落在 compose 注入的生产 DSN。

## 10. Known Limitations

1. new-site 默认 C 的生产直接行使未做(见 §3);证据链 = 生产既有行 NULL 保持 +
   seed 单测 + 迁移契约,无生产新站点样例。
2. 观察 ~10 分钟(3 检查点),非 24h 长窗;期间 1 次本机 SSH 瞬断(本地网络,
   非生产故障,复连即恢复)。
3. fixture 站点与 CORS 临时 origin 已还原;生产库新增的验收会话记录(1-2 条测试
   对话)保留在 conversations 表,属既有验收实践,可按需清理。
4. `iux001-acceptance` 已删除;TA 生产级"发布后长期曝光"样例随之移除 —— 后续
   正式曝光属产品运营动作(在真实站点 publish),不在本验收范围。

## 11. Scope Audit

- 全程按既有 procedure:tag 发布 → CI 镜像 → 拉取 → 备份 → 一次性容器迁移 →
  update.sh → 验收 → 还原;**零码树改动、零 Contract 修改、零 force/历史改写、
  未绕过 runbook、无破坏性 DB 操作(仅 ADD COLUMN IF NOT EXISTS / CREATE TABLE IF
  NOT EXISTS + 可逆 fixture 行的增删)**。
- 发现可改进项(§9)均记录未修,交 Role A 决定是否开 correction task。
