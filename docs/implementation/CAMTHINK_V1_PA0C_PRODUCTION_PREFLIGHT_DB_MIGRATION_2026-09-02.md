# CAMTHINK V1 — PA-0C Production Preflight DB Migration (2026-09-02)

**STATUS = PASS**(限本门授权范围:预检 + 幂等 DB 迁移;backend/sync-cron/语料/站点激活零触碰)

**AUTHORIZATION**:USER 授权 PRODUCTION_ACCESS + PRODUCTION_DB_MIGRATION(仅本门);所有执行均在该边界内,逐命令留痕。

---

## PA0C-1 Freshness / Identity Guard

| 项 | 值 | 时间(UTC) |
|---|---|---|
| 仓库 | `https://github.com/harryhua-ai/ask-ai.git`(本地 worktree @ release 分支) | 2026-09-01T16:21:19Z |
| RC commit | `1ed84bb…`(本地 HEAD 一致) | 同上 |
| 部署工具提交 | `41a7a2dd…`(本地存在并校验) | 同上 |
| 生产主机 | `tesla-t4`(hostname `VM-0-4-ubuntu`)——**ASK-AI 生产主机**(注:hermes 是另一系统 Trader 的主机,本门不涉及) | 2026-09-01T16:21:37Z |
| 无更新授权 | 以本合同为唯一操作授权 | — |

**工具同步**(主机部署目录 `/home/ubuntu/ask-ai` 非 git 仓;`ask-ai-src` 为旧克隆):

```
git -C /home/ubuntu/ask-ai-src fetch origin release/camthink-v1-rc-2026-09-01
git -C /home/ubuntu/ask-ai-src checkout 41a7a2dd…            # detached
cp ask-ai-src/deploy/prod/{update.sh,docker-compose.yml}  ask-ai/deploy/prod/   (原文件已备份 *.bak-pa0c)
```
安装后 md5:update.sh `e72e005a…`、docker-compose.yml `ca0f0e6c…`(与 41a7a2d 字节一致);`ASKAI_IMAGE_TAG` 插值在位。

## PA0C-2 Rollback Anchor(只读,未替换容器)

```
container = tesla-t4-backend-1
image_id  = sha256:c87518e12bc324cd9ea63564b223982f2da512a0be43399ce5e30e03af249957
in-image  = git_sha=bbfaa6a3adc977165d74db96738bec258d3a736d   ← 生产运行 bbfaa6a 谱系(与 PA-0B 基线假设一致)
started   = 2026-08-31T05:33:16Z · health = healthy · RepoTags = 无(以镜像 ID 为锚)
```

## PA0C-3 Configuration Preflight —— PASS(两项非阻塞记录)

| 项 | 结果 |
|---|---|
| CORS_ALLOW_ORIGINS | PRESENT(`https://www.camthink.ai,https://wiki.camthink.ai`)—— ⚠️ 缺 store origin(站点嵌入门补,非本门阻塞) |
| ASKAI_API_HOST / ASKAI_API_PORT | PRESENT(`0.0.0.0` / `8000`,命名正确) |
| DEEPSEEK_MODEL | PRESENT,值 = `deepseek-v4-pro` —— ⚠️ 与拍板(flash)不一致,但生产 `llm_providers` 有行(=1)且加载为 DB 优先、YAML 仅空库回退 ⇒ **运行时行为不受影响,非阻塞**;建议 PA-0D 一并改为 flash |
| ENCRYPTION_KEY / JWT_SECRET | PRESENT(值未读取、未修改、不轮换) |
| POSTGRES_DB/USER/PASSWORD | PRESENT(db=ask_ai, user=ask_ai) |
| 外部卷 | `tesla-t4_pgdata` + `tesla-t4_weaviate_data` ✓ |
| 挂载路径 | `/home/ubuntu/ask-ai-corpus`、`/home/ubuntu/ask-ai/models`、`/home/ubuntu/knowledge-support` 全部存在 ✓ |

## PA0C-4 Pull Exact RC Image(未启动任何服务)

```
docker pull ghcr.io/harryhua-ai/ask-ai:sha-1ed84bb
→ id=sha256:05f7d396116236831e68de10720820b501f8e53f7b990fc6b5bb19ca43edf626
  arch=amd64/linux · in-image git_sha=1ed84bbfcad0…(与 PA-0A 溯源链逐级一致)
```

## PA0C-5 DB 迁移前取证(生产真值,非基线推断)

PostgreSQL **16.15**;db=ask_ai:

| 项 | 迁移前 |
|---|---|
| `conversations.site_id` | **不存在** |
| `site_experiences` / `llm_allowed_hosts` | **均不存在** |
| conversations 行数 | **104** |
| llm_providers / llm_routing / users / customizations | 1 / 5 / 1 / 1 |
| conversations 索引 | pkey + channel/cluster_id/created_at/gap_status/is_answered(**无 site_id 索引**) |

## PA0C-6 Migration(经 RC 镜像、生产 DB)

- 第一次尝试失败于**任何 DB 操作之前**:`ModuleNotFoundError: No module named 'backend'` —— 已发布脚本缺 `sys.path` 自举(sync.py 有、该脚本没有;本机验证时被 PYTHONPATH 掩盖)。**零变更**。
- 正式执行(接受镜像 + 接受脚本字节,仅注入解释器路径):

```
ASKAI_IMAGE_TAG=sha-1ed84bb docker compose -f deploy/prod/docker-compose.yml \
  run --rm -e PYTHONPATH=/app sync python scripts/migrate_add_site_experiences.py
→ ✅ conversations.site_id 列已确保存在
  站点体验配置已同步(3 个站点)
```

## PA0C-7 验证

| 项 | 迁移后 |
|---|---|
| `conversations.site_id` | **存在**:character varying(100) / NULL 允许 / 无 FK(与模型一致;索引无 —— 既有表不加索引,代码声明索引未自动应用,仅性能相关,列为残余) |
| `site_experiences` | 存在,3 行:camthink-store / camthink-website / camthink-wiki(全部 enabled) |
| `llm_allowed_hosts` | 存在(0 行) |
| 行数不变性 | conversations 104 · llm_providers 1 · llm_routing 5 · users 1 · customizations 1 —— **全部不变** |
| Weaviate | 迁移脚本 0 处 weaviate 引用(代码面)+ weaviate 容器 `Up 2 weeks` 未重启 ⇒ 零变更 |
| backend 容器 | image_id/StartedAt/health 与锚点完全一致(`Up 35 hours`)—— 未升级未重启 |
| sync-cron | `Up 4 days` 未触碰 |

## PA0C-8 Idempotency

二次执行同命令 → 输出相同(列已确保/3 站点);site_experiences 仍 **3** 行、conversations 仍 **104**、其余计数不变、`information_schema.columns(conversations)` = 18 列无变化 ⇒ **二次运行零额外变更**。

## PA0C-9 Rollback Compatibility

回滚镜像 = 锚点 `bbfaa6a`(字节取证):其 `backend/db/models.py` 对 `site_id`/`site_experiences`/`llm_allowed_hosts` **0 引用**(ORM INSERT 不含 site_id → 可空列不受影响);其 `backend/main.py` 0 处站点 seed → 新表/新行对旧启动零触碰;bbfaa6a 为 origin/main 已知祖先。⇒ **迁移后旧生产镜像可直接安全运行**(未实际执行回滚,无需)。

## 验收矩阵

| 门 | 结论 | 门 | 结论 |
|---|---|---|---|
| G001 身份/新鲜度 | PASS | G009 幂等 | PASS(二次零额外变更) |
| G002 回滚锚 | PASS(bbfaa6a / c87518e1 / 08-31) | G010 既有数据保全 | PASS(104 对话与全部计数不变) |
| G003 配置预检 | PASS(2 项非阻塞记录) | G011 Weaviate/语料零变更 | PASS(代码面+容器状态) |
| G004 RC 镜像拉取+核验 | PASS(05f7d396/amd64/git_sha) | G012 backend 未升级/重启 | PASS(StartedAt/Id 不变) |
| G005 迁移前状态取证 | PASS | G013 sync-cron 未启动/重启 | PASS(Up 4 days) |
| G006 迁移成功执行 | PASS | G014 回滚兼容 | PASS(字节级论证) |
| G007 site_id 正确 | PASS(varchar(100) NULL,无 FK) | G015 无未授权变更 | PASS(仅备份+两文件工具同步+幂等迁移) |
| G008 site_experiences 正确 | PASS(3 行) | | |

## 残余记录

1. 首次迁移尝试的导入失败暴露已发布脚本缺 `sys.path` 自举(sync.py 有、此脚本无)——本次以 `PYTHONPATH=/app` 在接受镜像内运行解决;建议后续门给脚本补自举(非阻断)。
2. `conversations.site_id` 的代码声明索引未应用于既有表(create_all/脚本均不加)—— 仅性能项。
3. `.env` 两项不匹配(DEEPSEEK_MODEL=pro、CORS 缺 store)—— 非 PA-0C 范围,分别移交 PA-0D 与站点嵌入门。

## Delivery

```
STATUS = PASS
APPLICATION_RC = 1ed84bbfcad08224c8c322f7c7a7a817b8916147
APPLICATION_IMAGE = ghcr.io/harryhua-ai/ask-ai:sha-1ed84bb (Id sha256:05f7d396…, amd64)
DEPLOYMENT_TOOLING_COMMIT = 41a7a2dd5474d014fa2e63a7fac8f30e7a936e97(已同步至主机部署目录,备份 *.bak-pa0c)
PRODUCTION_HOST = tesla-t4 (VM-0-4-ubuntu)
ROLLBACK_IMAGE = sha256:c87518e1… (git_sha=bbfaa6a, tesla-t4-backend-1, healthy)
CONFIG_PREFLIGHT = PASS(DEEPSEEK_MODEL 值/CORS store 两项非阻塞记录)
DB_BEFORE = 无 site_id 列;site_experiences/llm_allowed_hosts 不存在;conversations=104
MIGRATION_EXECUTED = YES(RC 镜像内接受脚本;首次尝试导入失败零变更,已记录)
DB_AFTER = site_id varchar(100) NULL;site_experiences 3 行;llm_allowed_hosts 存在;计数全不变
IDEMPOTENCY = 二次运行零额外变更
ROLLBACK_COMPATIBILITY = ESTABLISHED(bbfaa6a 字节 0 引用新 schema)
PRODUCTION_BACKEND_CHANGED = NO(Same image/StartedAt/healthy)
SYNC_CRON_CHANGED = NO · WEAVIATE_MUTATED = NO · CORPUS_MUTATED = NO
PC_G001_G015 = 全 PASS(见 §验收矩阵)
REPORT_PATH = docs/implementation/CAMTHINK_V1_PA0C_PRODUCTION_PREFLIGHT_DB_MIGRATION_2026-09-02.md
REPORT_COMMIT = (见 docs 仓提交记录,交付响应给出)
```

**STOP。** 未升级 backend、未启动 sync-cron、未跑 sync/--reindex、未触碰 Weaviate/语料/secrets/站点激活/GPU。PA-0D(backend 生产升级)需新的显式授权。
