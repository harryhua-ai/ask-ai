# CAMTHINK V1 — Production Deployment Readiness Gate 报告

- 日期:2026-09-03
- **STATUS: DEPLOYMENT_READY**(待 Planner 独立验收 + 明确生产部署授权)
- **PRODUCTION_MUTATIONS: NONE**(全程只读;未部署/未迁移/未改配置/未重启/未切流)
- 诊断方式:仓库/CI/GHCR 读取 + `ssh tesla-t4` 只读诊断(docker ps/inspect、psql 元数据查询、df)

## 1. Release Authority

- `origin/main == 1d6f6b5fe697b5f7a1b8decef1c29f51afcda937` ✓(执行时实测)
- **CURRENT_PRODUCTION_RELEASE: `sha-269cadb`**(实证:运行中 backend 容器 image=ghcr.io/harryhua-ai/ask-ai:sha-269cadb,镜像 label version=sha-269cadb,Up healthy;sync-executor/sync-cron 同镜像)
- **TARGET_RELEASE: `1d6f6b5…`**

## 2. DEPLOYMENT_DIFF(CURRENT_PROD → TARGET)

`git diff 269cadb 1d6f6b5`:**32 files,+2887/−88**,零 deploy/ 文件变更。构成恰为三个已 FINAL PASS 候选:
- A Wave-0(观测面):sync_runs 表/服务/executor argv/retention/迁移脚本;
- B Stage⑯(生成失败/本地化):routes/rag/utils/language+user_messages/admin Conversations+outcome/widget SSE+i18n;
- C 测试闭环:conftest/embedder/connector 时序(**零生产代码改动**,env 相关 diff 28 处全部位于测试文件)。

## 3. DB_MIGRATION: **READY**

生产前置(只读实测):19 张表;`sync_requests` 在位且 **4 个阶段⑩恢复列齐全**;**`sync_runs` 不存在**(count=0)。

| 项 | 结论 | 证据 |
| --- | --- | --- |
| 前向安全 | ✓ | 全新 CREATE TABLE + 部分唯一索引,零存量数据、零既有列改动 |
| 幂等 | ✓ | checkfirst + IF NOT EXISTS;测试库连跑两次通过(集成门已证) |
| 索引创建安全 | ✓ | 新表无行,不可能撞唯一冲突;`WHERE request_id IS NOT NULL` 部分索引 |
| 停机需求 | **无** | 纯 additive;旧代码(269cadb)对新表零依赖;新代码启动 `create_all` 亦会自建该表(main.py:195 init_db,且该文件本 diff 未改动=双保险) |
| 执行方式 | runbook 项 | `ASKAI_IMAGE_TAG=sha-1d6f6b5 docker compose run --rm sync python scripts/migrate_add_sync_runs.py`(一次性容器,先于 up -d;顺序非硬性——additive 双向安全) |

## 4. CONFIG: **READY**

- `deploy/` 目录 diff=0;compose/update.sh 与生产现行完全一致;
- **零新增必需 env/secrets/volumes/ports/服务依赖**:候选 C 的 28 处 env 引用全为测试代码;Wave-0 无新 env;compose 端口/卷/camthink 三站 CORS 与站点配置零改动;
- 文件系统:模型缓存 ~/ask-ai/models 与 corpus 挂载不变。

## 5. ARTIFACT: **READY**

- CI run **33721194842**(Build & Push GPU Image)conclusion=success,**headSha=1d6f6b5…**(精确目标 release);镜像 `ghcr.io/harryhua-ai/ask-ai:sha-1d6f6b5` 已在 GHCR;
- 生产主机同 registry 拉取能力已被现役 sha-269cadb 镜像证明;磁盘 `/` 余量 **950G**(镜像 ~9.6GB 无压力);
- 部署流程未破坏:update.sh 与 prod compose 在 1d6f6b5 与生产运行的版本语义一致(`ASKAI_IMAGE_TAG` 注入、GPU 预检、backend 有界健康轮询、sync-cron 更新)。

## 6. Runtime Compatibility(逐项)

- A Wave-0 SyncRun:纯新增表面;旧路径(请求/日志)谓词零改动;
- B Stage⑯:本地化与 outcome 语义为代码层,无 schema 变更;存量 `conversations.language` 实测值 `en,zh,zh-cn`(130 行)——**无任何读路径按精确 language 过滤**(全仓无 `Conversation.language ==` 查询,Admin 无该筛选),Stage⑯ 冻结语义明示"仅约束新写入,不做历史迁移"→ 存量 zh-cn 行保持可见、不破坏;
- C/D request→run→log 链路与 SyncRun 生命周期:依赖 executor/runner/backend 同版本;**见 §8 部署步骤的 sync-executor 同步更新要求**;
- E 阶段⑧/⑨/⑩:零改动(1d6f6b5 的 ⑧⑨⑩ 语义即生产现行为);
- F 三站 Widget origin:widget.js 构建产物含 Stage⑯ SSE/i18n 增强,origin 授权(config/sites.yaml)零改动。

## 7. ROLLBACK: **READY**(exact contract)

- **APPLICATION ROLLBACK**:`cd ~/ask-ai && ASKAI_IMAGE_TAG=sha-269cadb docker compose up -d backend sync-executor sync-cron`(或 `./deploy/prod/update.sh sha-269cadb` + 手工补 sync-executor)。现役 sha-269cadb 镜像仍在主机本地,回滚=纯镜像切换,分钟级;
- **DATABASE**:本次 migration **纯 additive / backward compatible**——sync_runs 为新表,269cadb 旧应用完全不读不写;**旧应用在新 schema 上继续运行 ✓**;回滚**不需要任何 DB downgrade**;无 destructive 回滚设计;
- 若回滚后希望清掉 sync_runs(可选、非必需):属独立运维决策,不绑定回滚。

## 8. 部署 Runbook(授权后的建议步骤;本门未执行)

1. `ASKAI_IMAGE_TAG=sha-1d6f6b5 docker compose run --rm sync python scripts/migrate_add_sync_runs.py`(幂等,可重复);
2. `ASKAI_IMAGE_TAG=sha-1d6f6b5 docker compose up -d backend` + update.sh 的健康轮询;
3. **`ASKAI_IMAGE_TAG=sha-1d6f6b5 docker compose up -d sync-executor sync-cron`**——⚠️ 现行 update.sh 只覆盖 backend+sync-cron,sync-executor(stage⑨ 引入)必须显式更新,否则出现混跑窗口:旧 executor spawn 不带 `--request-id`,SyncRun.request_id 将为 NULL,request→run 链接在该窗口断裂(不崩溃,但违反 Wave-0 可观测契约);
4. Smoke(§9)。

## 9. SMOKE_PLAN(部署后冻结验收;安全方式,不制造故障)

1. backend `/health` 200(注意 BGE 加载 ~45s,有界轮询);
2. Admin 可达(经域名,登录页 200);
3. Widget js 可达(三站页面加载不 404);
4. CamThink website/wiki/store 页面正常;
5. 正常问答 1 次(中文)+ 1 次(英文)——语言归属 zh/en 正确;
6. 无证据拒答路径(诱导知识库外问题)→ 本地化拒答文案;
7. generation failure/service-busy 映射:仅以**既有安全注入方式**(不 kill、不制造生产故障;若无安全注入手段则该项降级为日志抽查);
8. Admin Conversations 页 outcome 渲染(含一条 declined/失败样例);
9. Admin 触发一次单源手动同步 → 202 accepted;
10. SyncRun 生命周期:同步期间/结束后 `sync_runs` 出现行(status 流转,source×attempt 一行);
11. request→run→log:SyncRun.request_id=该请求 id 且 sync_log_id 回填非空;
12. 既有数据可用:既有 conversation/document 抽查可见;
13. 观测 15 分钟:无异常 5xx/错误日志激增;sync_log 正常推进。

## 10. BLOCKERS

**NONE。**(注意项非阻塞:update.sh 不覆盖 sync-executor 的既有缺口,已并入 §8 步骤 3;embedder 离线 4 用例为测试环境证据,与生产无关——生产镜像内含全量模型挂载。)

## 11. Regression Evidence(复用,不重复)

三候选独立 FINAL PASS + 三候选集成门(1d6f6b5,全量离线 1112 passed/6 skipped/4 环境证据/31s,前端 190+72 双构建)——本轮未发现新风险,无需重跑。
