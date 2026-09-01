# CAMTHINK V1 — PA-0B Production Upgrade Readiness Discovery (2026-09-01)

**STATUS = PASS(PB-G005 查实部署机制阻断性缺陷,已按冻结非目标条款完成最小修复 `41a7a2d`)**
- RC / 镜像:`1ed84bbfcad0…` · `ghcr.io/harryhua-ai/ask-ai:sha-1ed84bb`(本门**未改变镜像内容**;修复仅触达部署工具)
- ACCESS CONTRACT:PRODUCTION_ACCESS = NO —— 本门全程**零生产访问**(无 SSH、无生产命令;取证全部来自 RC 仓库源码、GHCR/registry API、本机 Docker 与本地 Postgres 隔离实例)

---

## 1. 升级路径完整因果链(PB-G001)

`update.sh` → `docker compose pull` → `up -d backend`(重建容器)→ **lifespan 全量执行**(DB/seed/模型加载)→ 健康探测 → `up -d sync-cron`(启动即跑第一轮同步)。逐环节:

| 环节 | 源码事实 |
|---|---|
| `update.sh:18` | `TAG="${1:-latest}"` —— **修复前仅用于 3 处 echo** |
| `docker-compose.yml:25` | `image: ghcr.io/harryhua-ai/ask-ai:latest`(**硬编码**,修复前无插值) |
| `compose pull` | 按 compose 解析镜像引用拉取(修复前恒为 `:latest`) |
| `update.sh:41` | `up -d backend` 仅重建 backend 服务;postgres/weaviate 容器与外部命名卷不动 |
| `backend/main.py:195` | `init_db(engine)` = create_all —— lifespan **第一个** DB 效应 |
| `main.py:200-263` | 条件 seed(均为"不存在才创建"):website-camthink 数据源 / admin 用户 / default customization+widget 绑定 |
| `main.py:267-273` | `seed_default_sites` —— **每次启动无条件幂等 upsert** 3 个站点(sites.yaml 权威) |
| `main.py:276-…` | LLM seed —— **跳过已存在**(`session.get(...): continue`),生产既有 llm 行不被覆盖 |
| `main.py:~295-315` | weaviate 客户端连接(零语料写)+ BGE embedder/reranker 加载(~45s)+ LLM 状态(DB 优先) |
| `main.py:421 yield` | lifespan 结束后 uvicorn 才开始服务 → **`/health` 200 严格晚于全部 DB 效应** |
| compose:119 | sync-cron `while true; do python3 scripts/sync.py || true; sleep 3600; done` —— **启动即跑第一轮同步** |

## 2. 自动 PostgreSQL 变更清单(PB-G002)

RC backend 在生产库上启动时**自动**发生:

| 效应 | 机制 | 生产影响 |
|---|---|---|
| 新表 `site_experiences`、`llm_allowed_hosts`(create_all) | `init_db`(main.py:195) | 已实测发生(隔离库);纯新增 |
| `site_experiences` 3 行(website/wiki/store,enabled) | lifespan 站点 seed(无条件 upsert) | 已实测发生;对外零暴露(站点授权 fail-closed + 无 CORS/嵌入) |
| website-camthink 数据源(仅当不存在) | 条件 seed | 若生产已有则零操作 |
| admin 用户(仅当不存在;默认口令 admin123) | 条件 seed | 生产已有 admin → 零操作;**改密仍为激活必办项** |
| default customization+绑定(仅当不存在) | 条件 seed | 生产已有 → 零操作 |
| llm_providers / llm_routing | **跳过已存在** —— 生产行零覆盖 | 无 |
| **`conversations.site_id` 列** | **不会自动出现** —— create_all 不改既有表;唯一途径 = 幂等脚本 `scripts/migrate_add_site_experiences.py`(update.sh/compose 均不执行它) | **见 §3 危害实证** |

### §3 危害实证(隔离本地库,生产形态 = 无 site_id 列)

用 bbfaa6a 形态 schema(无 site_id)启动 RC backend:**`/health` = 200、`/api/ask` = HTTP 200(用户照常看到应答/错误事件)**,但每条对话的提交全部失败:

```
asyncpg.exceptions.UndefinedColumnError: column "site_id" of relation
"conversations" does not exist        (routes.py:296 → session.commit())
INSERT INTO conversations (…, site_id) VALUES (…)
conversations=0 · traces=0(持久化静默丢失)
```

即:**只跑 update.sh(不跑迁移)= 健康门照常通过、服务表面正常,但对话/trace 持久化 100% 静默丢失,对话审查/技术洞察全盲**。修复 = 首次 RC 服务前执行幂等迁移脚本(这是安全序列的硬性步骤,不是可选项)。

## 3. 自动 Weaviate/语料变更(PB-G003)

- **backend 启动:零语料变更**(仅 weaviate 客户端连接;collection 读写都发生在请求/同步路径)。
- **`up -d sync-cron` = 立即语料变更**:容器命令第一次迭代就执行 `sync.py`(sleep 在循环尾),即立刻抓取外部站点 + 重嵌入 + 写 Weaviate + 写账本;且 RC 的 sync 带 WEB-01 一致性自愈 —— 生产账本若存在旧漂移,首轮即触发全量重灌浪涌(SyncLog `partial`→下一轮 `success`)。
- 结论:sync-cron 的更新 = 语料激活动作,必须单独窗口、单独授权(见 §6 阶段 4)。

## 4. 健康门顺序(PB-G004)+ 已修复的假失败

- **顺序**:全部 DB 效应(init_db/seed/站点/LLM)→ 模型加载(~45s)→ lifespan 结束 → `/health` 200。即 **DB 变更必然先于健康门**,健康门通过不代表"无 DB 副作用",且 site_id 列缺失这类"服务可用但持久化坏"的状态**健康门无法发现**。
- **旧缺陷(已修)**:update.sh `sleep 5` 后单次探测 —— BGE 加载 ~45s+ 必然探测失败 → 脚本误报退出且跳过 sync-cron 更新(新旧混跑)。修复 = 120s 有界轮询(`41a7a2d`)。

## 5. 镜像/Tag 选择真值(PB-G005)—— 查实为阻断性缺陷,已修

- **修复前真值**:`update.sh` 的 `TAG` 参数只出现在 echo;compose 硬编码 `:latest` → `./update.sh sha-1ed84bb` **实际拉取/运行/回滚的永远是 latest**(最后一次 main 构建,非本 RC)。文档化回滚为空操作。判定:**release-blocking 部署机制缺陷**(无法部署已验收 RC 镜像)。
- **最小修复(`41a7a2d`,release 分支已推送)**:
  - compose:`image: ghcr.io/harryhua-ai/ask-ai:${ASKAI_IMAGE_TAG:-latest}`;
  - update.sh:`export ASKAI_IMAGE_TAG="$TAG"` + 健康门轮询;
  - 实测:`ASKAI_IMAGE_TAG=sha-1ed84bb compose config` 解析为 `…:sha-1ed84bb`;不设置解析为 `…:latest`(旧行为完全兼容);`bash -n` 通过;
  - **镜像制品不变**:已验收镜像仍 = `sha-1ed84bb`(1ed84bb 构建,config digest `sha256:05f7d396…`)。

## 6. 冻结的安全部署序列(PB-G008;下一门按此执行,勿整体跑 update.sh)

> 即使含修复,`update.sh` 端到端仍会跳过必需迁移并触发即时全量同步 —— **本次升级必须走分步手动控制**:

```
阶段 0 预备(授权后)
  0.1 主机仓库更新到含 PA-0B 修复的 release 分支(41a7a2d)—— 否则 TAG 修复不生效
  0.2 记录当前运行镜像(回滚锚点):
      docker inspect --format '{{.Image}}' tesla-t4-backend-1 | tee ~/prev_image.txt
  0.3 .env 审计:变量名必须为 CORS_ALLOW_ORIGINS(含三站)/ ASKAI_API_HOST/PORT /
      DEEPSEEK_MODEL=deepseek-v4-flash;ENCRYPTION_KEY 必须沿用现值(否则加密 api_key 不可解)
阶段 1 拉取精确镜像(不启动)
  ASKAI_IMAGE_TAG=sha-1ed84bb docker compose -f deploy/prod/docker-compose.yml pull backend sync sync-cron
  核验: docker image inspect --format '{{.Id}}' ghcr.io/harryhua-ai/ask-ai:sha-1ed84bb
        == sha256:05f7d3961162…(config digest,与 RC 溯源链一致)
阶段 2 DB 预迁移(★必须在 RC backend 首次对外服务前)
  ASKAI_IMAGE_TAG=sha-1ed84bb docker compose -f deploy/prod/docker-compose.yml \
      run --rm sync python scripts/migrate_add_site_experiences.py
  验证: conversations 具备 site_id 列;site_experiences = 3 行;重复执行幂等
阶段 3 backend 滚动 + 验证
  ASKAI_IMAGE_TAG=sha-1ed84bb docker compose -f deploy/prod/docker-compose.yml up -d backend
  轮询 /health 至 200(允许 ~90s BGE 加载);随后验证 admin 登录 / 对话审查 /
  一次 /ask(且日志无 site_id/UndefinedColumn)/ 对话确实落库
阶段 4 sync-cron = 语料激活,单独窗口单独授权(默认暂不更新,旧镜像与新 schema 兼容)
  ASKAI_IMAGE_TAG=sha-1ed84bb docker compose -f deploy/prod/docker-compose.yml up -d sync-cron
  ⚠️ 容器启动即跑第一轮同步:预期 WEB-01 自愈浪涌(账本漂移全量重灌,
     SyncLog partial→success);非故障。--reindex 仅限 schema 需要时
阶段 5 回滚预案(真实可用,依赖 PA-0B 修复)
  ASKAI_IMAGE_TAG=$(cat ~/prev_image.txt 对应 tag) ./deploy/prod/update.sh <prev_tag>
  DB 不需要回滚:RC 全部变更纯增量(新表/可空列/seed 行),旧代码兼容
阶段 6 独立后续门: GPU 冒烟(见 §7)、Trust Boundary channel_visibility 激活、
  站点 CORS/域名核对、Widget 嵌入、语料修复确认
```

## 7. GPU 容量风险分类(PB-G007;仅用 PA-0A 已记录证据)

- 已记录现实:Tesla T4 16384 MiB,**已用 ~15633 MiB,空闲 ~751 MiB**;占用者:llama-server 5910 MiB、python 服务 3492 MiB、生产 ask-ai backend 3762 MiB、neomind-extension-runner 2466 MiB。
- 仓库证据的显存需求:compose `EMBEDDER_DEVICE=cuda`;模型 = BAAI/bge-m3(568M 参数,fp32 ≈ 2.2 GB)+ BAAI/bge-reranker-v2-m3(≈ 2.2 GB)+ CUDA context/torch 运行时 ≈ 0.5–1 GB ⇒ **GPU 路径常驻需 ≥ ~5–6 GB 空闲**。
- 分类:**INFEASIBLE_AT_CURRENT_CAPACITY(0.75 GB)** —— 额外隔离容器的全 GPU 冒烟必然 CUDA OOM;升级本身(backend 容器一对一替换)不增加 GPU 压力,但**把生产 backend 切到 GPU 冒烟形态不属于本门**。解除条件 = 释放 ≥ ~6 GB 显存,涉及停止/迁移 llama-server 等既有业务进程 —— **这是需要所有者单独授权的运营决策**,本门不开处方、不执行。

## 8. 生产变更点全清单(PB-G009,授权前必须知情)

自动且不可回避(启动即发生):create_all 新表 ×2 → 站点 3 行 upsert → 其余条件 seed(生产大多已存在=零操作)。
条件性/手动:site_id 列迁移(★必须手动先跑)· sync-cron 更新(=立即语料同步)· CORS/嵌入/Trust Boundary(后续门)。
确定不发生:backend 启动不写 Weaviate 语料;llm 生产行不被覆盖;postgres/weaviate 容器与卷不被 compose 触碰;update.sh GPU 预检只读。

## 9. 验收映射

| 门 | 结论 |
|---|---|
| PB-G001 升级路径全映射 | PASS(§1 因果链,源码行级引用) |
| PB-G002 自动 PG 效应 | PASS(§2 清单 + §3 实证) |
| PB-G003 自动 Weaviate/语料效应 | PASS(§3:backend 零;sync-cron 启动=立即全量同步) |
| PB-G004 健康门顺序 | PASS(§4:DB 效应严格先于 /health;假失败已修) |
| PB-G005 精确镜像/Tag 选择 | PASS(修复前=装饰性参数已实证;修复 `41a7a2d` 后双向解析实测) |
| PB-G006 回滚兼容 | PASS(纯增量变更 ⇒ 旧镜像兼容;修复后回滚命令真实生效;升级前记录 prev image) |
| PB-G007 GPU 容量风险 | PASS(分类 INFEASIBLE_AT_CURRENT_CAPACITY;解除需授权,§7) |
| PB-G008 安全序列冻结 | PASS(§6 分步序列;禁止 update.sh 端到端) |
| PB-G009 变更点全清单 | PASS(§8) |
| PB-G010 生产未访问 | PASS(本门零 SSH/零生产命令) |

## 10. Non-goals 复核 / 残余风险

未部署、未迁移生产 DB、未动语料/Weaviate、未改 secrets、未激活站点、未停 GPU 进程;代码变更仅 §5 两处部署工具修复(阻断性缺陷实锚后按条款允许)。残余风险:①生产库确切 schema 时代未经生产侧确认(以 bbfaa6a 形态为代表性基线推断,migrate 幂等覆盖不确定性);②web_crawl 首轮自愈浪涌规模取决于生产账本漂移实际状态;③GPU 容量解除是组织决策;④update.sh 无 --dry-run(本门未加,列入下一门可选改进)。

## 11. Delivery

| 字段 | 值 |
| --- | --- |
| STATUS | PASS |
| RC_COMMIT | 1ed84bbfcad08224c8c322f7c7a7a817b8916147(镜像制品不变;部署修复 `41a7a2d` 在同分支已推送) |
| PRODUCTION_ACCESS | NO |
| UPDATE_PATH | update.sh→compose pull→up -d backend→lifespan(init_db+seed+模型加载)→health→up -d sync-cron(立即同步) |
| AUTOMATIC_DB_MUTATION | create_all 新表(site_experiences/llm_allowed_hosts)+ 站点 3 行 upsert + 条件 seed;site_id 列**不自动**(必须手动 migrate,否则对话持久化静默全失 —— 已实证) |
| AUTOMATIC_CORPUS_MUTATION | backend 启动零;sync-cron 更新=立即全量同步(WEB-01 自愈浪涌) |
| IMAGE_TAG_SELECTION | 修复前 TAG 装饰性(compose 硬编码 latest)=阻断性缺陷;修复后 ASKAI_IMAGE_TAG 真选择,双向解析实测 |
| GPU_CAPACITY_STATUS | INFEASIBLE_AT_CURRENT_CAPACITY(需 ≥~6GB,现 0.75GB;解除=独立授权决策) |
| SAFE_DEPLOYMENT_SEQUENCE | §6 六阶段(分步手动;禁 update.sh 端到端;migrate 先于首次服务;sync-cron 单独窗口) |
| PB_G001_G010 | 全 PASS(§9) |
| REPORT_PATH | docs/implementation/CAMTHINK_V1_PA0B_PRODUCTION_UPGRADE_READINESS_DISCOVERY_2026-09-01.md |
| REPORT_COMMIT | (见 docs 仓提交记录,交付响应给出) |

停在交接;未进入生产部署。Planner 独立验收。
