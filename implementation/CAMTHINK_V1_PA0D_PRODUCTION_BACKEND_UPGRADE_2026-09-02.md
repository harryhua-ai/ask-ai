# CAMTHINK_V1_PA0D_PRODUCTION_BACKEND_UPGRADE_2026-09-02

- Gate: PA-0D — 生产 ASK-AI 后端替换为已验收 RC 镜像并完成运行时验收
- 执行窗口: 2026-09-01T16:38Z ~ 16:46Z(UTC)
- 生产主机: tesla-t4(43.132.189.162 / VM-0-4-ubuntu)
- 授权: PRODUCTION_ACCESS = AUTHORIZED;PRODUCTION_BACKEND_REPLACEMENT = AUTHORIZED;ROLLBACK_IF_REQUIRED = AUTHORIZED(仅限本 Gate)
- 结论: **PASS**(全部 10 项验收通过;回滚路径确认可用但未执行)

## 0. 冻结输入与一致性

| 输入 | 值 | 现场核验 |
|---|---|---|
| Application RC | `1ed84bbfcad08224c8c322f7c7a7a817b8916147` | 容器内 `/app/.git-sha` 实测一致 |
| Accepted image | `ghcr.io/harryhua-ai/ask-ai:sha-1ed84bb` | 本地 digest `sha256:ddacb7f5…` = PA-0A 记录 |
| Deployment tooling | `41a7a2d` | `/home/ubuntu/ask-ai-src` HEAD 实测 = `41a7a2d`;部署目录 compose/update.sh 字节级 diff = MATCH |
| PA-0C report | `077c4898a1760fbf4e3772c6849dccfe4c686e82` | — |
| PA-0C rollback anchor | image `sha256:c87518e1…` / in-image git_sha `bbfaa6a…` | 替换前实测完全一致(无漂移) |

## 1. PD-G001 Freshness Guard — PASS

- 主机身份:`VM-0-4-ubuntu`,用户 `ubuntu`,SSH Host 别名 `tesla-t4`。
- 当前 backend 与 PA-0C 回滚锚零漂移:container `tesla-t4-backend-1`(Id `b6ad7fcefa90…`),Image `sha256:c87518e1…`,in-image `git_sha=bbfaa6a…`,2026-08-31T05:33:16Z 起,healthy,Restarts=0。
- PA-0C 迁移仍然在位(read-only information_schema 查询):
  - `conversations.site_id` 列存在;
  - `site_experiences` 表存在;
  - `llm_allowed_hosts` 表存在。
- 部署文件 = 已验收 tooling:`deploy/prod/docker-compose.yml`、`deploy/prod/update.sh` 与 `/home/ubuntu/ask-ai-src@41a7a2d` 字节级一致(`diff -q` MATCH)。
- RC 镜像本地可用:`sha-1ed84bb`,digest `sha256:ddacb7f5848d7544a717026572cf4c3b261b656e367cf6068dd1d4f8305d53d1`,IMAGE ID `05f7d3961162` —— 与 PA-0A 五级溯源记录一致。
- 无 BLOCKED 级漂移。

## 2. PD-G002 Before-State — 已采集

| 项 | 值 |
|---|---|
| BEFORE_BACKEND container | `b6ad7fcefa90…`(tesla-t4-backend-1) |
| BEFORE_BACKEND image | `sha256:c87518e12bc324cd9ea63564b223982f2da512a0be43399ce5e30e03af249957` |
| BEFORE in-image git_sha | `bbfaa6a3adc977165d74db96738bec258d3a736d` |
| StartedAt | 2026-08-31T05:33:16.745856945Z |
| Health | healthy(Restarts=0) |
| conversations / traces | 104 / 104(site_id 非空 0 条) |
| GPU before | 15633/16384 MiB;backend(pid 1110263)=3762 MiB,llama-server(pid 2315780)=5910 MiB,root server.py(pid 2322392)=3492 MiB,neomind(pid 4001895)=2466 MiB |
| sync-cron | running,StartedAt 2026-08-28T12:24:19Z,image `sha256:0c4b2c32…`(旧镜像) |

未暴露任何 secret。

## 3. PD-G003 Configuration Handling — 无未授权变更

- 现场证据(生产 DB 权威,PA-0C 结论):`llm_providers` 恰 1 条 enabled 行,`type=openai_compatible`,`model=deepseek-v4-flash`,`api_key` 非空。生产 LLM 由 DB 配置驱动且已是 flash。
- `.env` 的 `DEEPSEEK_MODEL=deepseek-v4-pro` 仅为惰性默认值(seed/回退语义),RC 运行时语义不要求修改(DB 行优先)→ **`.env` 一字未动**。
- CORS / store origin / 站点门禁:未触碰(属后续 Multi-Site 激活 Gate)。

## 4. PD-G004 Backend Replacement — PASS

- tag 选择先证(生产 tooling 上 PA-0B 修复生效):
  `ASKAI_IMAGE_TAG=sha-1ed84bb docker compose … config backend` → `image: ghcr.io/harryhua-ai/ask-ai:sha-1ed84bb`。
- 执行(未跑 update.sh;未含 sync/sync-cron):
  ```
  cd /home/ubuntu/ask-ai
  ASKAI_IMAGE_TAG=sha-1ed84bb docker compose -f deploy/prod/docker-compose.yml up -d backend
  ```
  输出(摘要):`tesla-t4-postgres-1 Waiting/Healthy`、`tesla-t4-weaviate-1 Healthy`(均未重建)、`tesla-t4-backend-1 Starting → Started`。
- compose 依依赖等待 postgres/weaviate 属 up 语义,两依赖容器 Up 2 weeks 未动;sync-cron 不在本次命令范围。

## 5. PD-G005 Startup / GPU Observation — PASS

- 健康轮询(5s 步进):t=5s~20s `health=000 state=running/starting/0`,**t=25s health=200**,全程 Restarts=0。
- 启动日志(顺序完整、无致命异常):
  站点体验配置同步(3 个站点)→ LLM 供应商+路由迁移到 DB → Weaviate 连接 → **BGE-m3 加载完成(device=cuda)** → **bge-reranker-v2-m3 加载完成** → LLM 配置从 DB 加载(1 个供应商,跳过 0 个)→ Pruner 启用 → OverrideMatcher(1 条)→ SourceVisibilityGuard 启用 → `Ask AI 后端就绪` → `Application startup complete`。
- 无 CUDA OOM / 无 fatal / 无重启环。
- GPU after:13109/16384 MiB;新 backend 进程(pid 1257699)=1238 MiB(旧进程常驻期 3762 MiB;替换后整机空闲显存由 ~751 MiB 升至 ~3275 MiB);其余三个 GPU 进程 pid 与显存前后完全一致(root 3492 / llama-server 5910 / neomind 2466)——无关 GPU 服务零扰动。

## 6. PD-G006 Health Verification — PASS

| 项 | AFTER 值 |
|---|---|
| AFTER_BACKEND container | `86765258732b…`(tesla-t4-backend-1) |
| AFTER_BACKEND image | `sha256:05f7d396116236831e68de10720820b501f8e53f7b990fc6b5bb19ca43edf626`(= `sha-1ed84bb`) |
| IN_IMAGE_GIT_SHA | `1ed84bbfcad08224c8c322f7c7a7a817b8916147`(容器内 stamp 实测) |
| STARTED_AT | 2026-09-01T16:40:16.168735552Z |
| HEALTH | healthy(docker healthcheck converged;`GET /health` 200) |
| Restarts / OOMKilled | 0 / false |

## 7. PD-G007 Controlled Natural API Smoke — PASS

- 时间:2026-09-01T16:41:31Z;经生产 backend `localhost:18000`(同线上 nginx 反代入口)。
- 请求(一次,无重试):
  `POST /api/ask` `{"message":"What products does CamThink offer and what are they used for?","channel":"admin"}`
  (`channel=admin` 为管理后台测试渠道,不污染公共 widget 统计池;legacy 无 site_id,不触发站点门禁/CORS 激活。)
- 结果:HTTP 200,总耗时 31.73s;SSE `token`×337、`sources`×1、`done`×1;**无 error / declined 事件**。
- 有效回答:是(持久化 answer 1530 字符);引用 5 条,均为 camthink.ai 公开页(品牌发布新闻、NeoEyes NE503 产品页等,类型 web_crawl)。
- 未暴露 secret/token。

## 8. PD-G008 Persistence Verification — PASS(硬验收)

- 计数:conversations **104 → 105**,traces **104 → 105**。
- 新 conversation 行(即本次受控请求):
  `id=d2f8982c-3dae-417a-b157-ff9266c3dbb9`,`channel=admin`,`language=en`,`is_answered=t`,`response_time_ms=31713`,`intent_tag=product`,**`site_id=NULL`(legacy 路径;新列存在且写入成功——PA-0C 迁移正是为消除该列缺失导致的静默丢写)**,`answer` 1530 字符,`sources` jsonb 数组长度 5,`created_at=2026-09-01 16:42:03Z`。
- 对应 trace 行:`conversation_id=d2f8982c…`,`turn_index=0`,`type=rag`,`total_ms=31713`,`intent=product`。
- 日志无 `UndefinedColumn` / `column … does not exist` —— **无静默持久化失败**。

## 9. PD-G009 Runtime Regression Check — PASS

- 全量启动以来日志按 `cuda out of memory|oom|traceback|undefinedcolumn|column … does not exist|decryption|failed|error` 扫描:**零命中**。
- 非阻塞告警(既有已知):passlib `crypt` DeprecationWarning、`TRANSFORMERS_CACHE` FutureWarning、weaviate-client pypi 版本检查 INFO。均与 bbfaa6a 时代一致,不构成本次回归。
- LLM provider 初始化:正常(DB 1 供应商,跳过 0);检索/生成链路经真实冒烟验证。

## 10. PD-G010 Rollback Rule — 未触发;路径确认可用

- RC 全部硬验收通过 → **未回滚**。
- 回滚路径(仅当需要):旧镜像仍在宿主机且即 `:latest` tag(`latest` = `c87518e1…` = PA-0C 锚):
  ```
  cd /home/ubuntu/ask-ai && ASKAI_IMAGE_TAG=latest docker compose -f deploy/prod/docker-compose.yml up -d backend
  ```
  (PA-0B 修复后该命令真实生效;PA-0C 已验证 bbfaa6a 与现行 schema 加性兼容。)

## 11. 边界遵守声明

- 未运行 `update.sh`;未触碰 sync-cron(StartedAt 08-28 与 image 前后一致)、未运行 sync.py/--reindex;
- Weaviate/corpus 零变更(本 Gate 未发起任何写;gate 窗口 16:40–16:46Z 内 sync-cron 小时周期(xx:24)无触发,`sync_log` 最新可见行仍为 2026-08-09);
- postgres / weaviate 容器 Up 2 weeks 未重建;未停/动 llama-server、root 常驻服务、neomind;
- 未改 DB schema(仅只读 information_schema/数据查询)、未动 secrets/ENCRYPTION_KEY、未激活 CORS/widget/站点集成、未动 DNS/nginx;
- `.env` 零改动。

## 12. Evidence 汇总

| 字段 | 值 |
|---|---|
| BEFORE_BACKEND | container `b6ad7fcefa90…`,image `sha256:c87518e1…`,git_sha `bbfaa6a…` |
| AFTER_BACKEND | container `86765258732b…`,image `sha256:05f7d396…`(tag `sha-1ed84bb`) |
| IMAGE_ID | `sha256:05f7d396116236831e68de10720820b501f8e53f7b990fc6b5bb19ca43edf626` |
| IN_IMAGE_GIT_SHA | `1ed84bbfcad08224c8c322f7c7a7a817b8916147` |
| STARTED_AT | 2026-09-01T16:40:16Z |
| HEALTH | 200 / docker healthy,Restarts=0 |
| GPU_BEFORE / GPU_AFTER | 15633/16384 MiB → 13109/16384 MiB(无关进程 pid/显存不变) |
| SMOKE_QUESTION | "What products does CamThink offer and what are they used for?" |
| SMOKE_RESULT | HTTP 200,31.73s,337 tokens,5 引用,无 error/declined |
| CONVERSATION_COUNT_BEFORE/AFTER | 104 → 105 |
| PERSISTED_CONVERSATION_ID | `d2f8982c-3dae-417a-b157-ff9266c3dbb9` |
| SITE_ID | NULL(legacy 请求;列写入成功) |
| TRACE_PERSISTENCE | 是(traces 104→105,type=rag,total_ms=31713) |
| CRITICAL_LOG_ERRORS | 0 |
| ROLLBACK_REQUIRED | NO(路径可用:ASKAI_IMAGE_TAG=latest) |
| SYNC_CRON_CHANGED | NO |
| WEAVIATE_MUTATED | NO |
| CORPUS_MUTATED | NO |

## 13. 验收判定

PD-G001=PASS PD-G002=PASS(已采集) PD-G003=PASS(零未授权变更) PD-G004=PASS PD-G005=PASS PD-G006=PASS PD-G007=PASS PD-G008=PASS PD-G009=PASS PD-G010=PASS(未触发,路径可用)

**STATUS = PASS**

## 14. STOP 声明

按合同,本 Gate 到此为止:未进行 sync/corpus 激活、未激活站点集成/CORS、未执行 PA-0E 及之后任何 Gate。后续动作需新的显式授权。

(残留改进备忘,非本 Gate 范围:`sync-cron` 仍运行旧镜像 `0c4b2c32…`,待后续授权再随全栈升级对齐;`.env` 的 `DEEPSEEK_MODEL=deepseek-v4-pro` 为惰性默认值,可在未来维护窗口顺手对齐 flash 以消除歧义。)
