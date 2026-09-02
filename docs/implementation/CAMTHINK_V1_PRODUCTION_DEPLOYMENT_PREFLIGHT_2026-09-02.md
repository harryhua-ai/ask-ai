# CAMTHINK V1 PRODUCTION DEPLOYMENT PREFLIGHT_2026-09-02

**性质**:只读仓库调查 + 部署规划 Gate。**未访问生产,未变更生产,未变更产品代码。**
**STATUS = PASS**(仓库侧预检完成,足以支持 Planner 申请下一_gate 的只读生产核查;不代表部署已获授权)

---

# Executive Summary

- `origin/main = 193f206a3d0e8695f1c40766a1ba54667fcba2fb`,与 **SOURCE_FREEZE 完全一致**(零推进,未触发 BLOCKED)。
- 生产更新机制为 **镜像制**:CI(push main / tag / dispatch)→ GHCR → `deploy/prod/update.sh <tag>`(导出 `ASKAI_IMAGE_TAG` → `up -d backend` → 120s 健康轮询 → `up -d sync-cron`)。**update.sh 不执行任何数据库迁移** —— 迁移是独立手动步骤。
- 迁移清单核实:**M01/M02/M03/M04 均真实存在且幂等**;其中 **M03/M04 为硬前置**(新应用 ORM 映射了旧表缺失的列,`init_db=create_all` 只建表不加列,且 conversations 上的新索引会使旧表启动即失败);**M02**(新表)可由启动期 `create_all` 隐式创建,但建议显式脚本化执行;**M05 降级为 CONDITIONAL / PRECHECK / HIGHER-CAUTION**(运行时兼容旧字符串 chain;但脚本含 query_decomposition 路由删除等副作用,其中自定义 chain 会被丢弃 —— 是否执行须由扩展预检逐项裁决,见 §Planner Review Correction)。
- 关键兼容结论:**旧镜像 + 新 schema = 安全**(全部迁移为加性;旧 ORM 不映射新列/新表)→ 允许「旧应用继续服务时执行迁移」,最小化停机;**新应用 + 旧 schema = 禁止**(启动失败/对话持久化丢失/站点体验 500)。
- 部署后运维基线:Prompt 热重载已含于 freeze,普通替换/重启即完整生效,无需额外基础设施;单进程假设维持(多 worker 为显式部署约束,非本 Gate 重设计项)。

# Frozen Release Artifact

| 项 | 值 |
|---|---|
| SOURCE_FREEZE | `193f206a3d0e8695f1c40766a1ba54667fcba2fb`(= 当前 `origin/main`,逐字一致) |
| IMAGE | `ghcr.io/harryhua-ai/ask-ai:sha-193f206` |
| OCI INDEX DIGEST | `sha256:c7752f2941bb3188a4b852748bb4a9cfa208a908986752fffdb95f5bc323c347` |
| PLATFORM | linux/amd64 |
| CI | Build & Push GPU Image **#60**,Run ID `33603669506`,SUCCESS |
| IN-IMAGE STAMP | `/app/.git-sha = 193f206a3d0e8695f1c40766a1ba54667fcba2fb` |
| 历史生产基线 | `sha-3bf945b`(仅历史证据;生产现状以只读核查为准) |

# Repository Deployment Architecture(源码实证)

- **CI**(`.github/workflows/build-image.yml`):`push: main` → 构建 + tag `latest`+`sha-<short>`;`tags: v*.*.*` → semver;`workflow_dispatch` → 按需。ubuntu-latest 原生 amd64,推 GHCR。
  ⚠️ 推论:**向 main 推送任何提交(含 docs)都会触发镜像构建** —— 本报告因此落在专用分支,不推 main。
- **生产部署**:`deploy/prod/update.sh <tag>`:`export ASKAI_IMAGE_TAG=<tag>` → `docker compose -f deploy/prod/docker-compose.yml up -d backend` → `localhost:18000/health` 120s 轮询 → `up -d sync-cron`。**不含迁移步骤、不含 git pull**。
- **compose 拓扑**(project=`tesla-t4`):`backend`(18000→8000,GPU,admin/widget 静态资产在镜像内)、`sync`(一次性手动)、`sync-cron`(每小时 `scripts/sync.py` 循环)、`postgres:16`(命名卷 `tesla-t4_pgdata`)、`weaviate:1.28.0`(命名卷 `tesla-t4_weaviate_data`,容器内网 8080)。
- **配置**:`env_file ../../.env`;模型权重挂载 `/home/ubuntu/ask-ai/models:/models:ro`;语料挂载 `/home/ubuntu/ask-ai-corpus`;`config/` 目录打进镜像(`system_prompt.yaml`、`sites.yaml` 等)。
- **健康**:`GET /health`(main.py:541)+ 镜像 HEALTHCHECK;`restart: unless-stopped`。
- **同步**:sync-cron 每小时 `scripts/sync.py` 增量(启动即跑一轮);backend 启动含 lifespan 种子/加载(定制快照、站点 upsert、SourceVisibilityGuard 等)。

# Migration Inventory(逐脚本对 193f206 源码核实)

## M01 — `scripts/migrate_channel_visibility.py` → REQUIRED(条件:服务隔离承诺前)

- **数据变更**:仅写 Weaviate `Document.channel_visibility` 数组属性;**无 schema 变更、无 PG 变更**。
- **回填语义**:按 `data_sources.config.channel_visibility` 回填每个存量 chunk;缺失该键 → 默认公开 `["widget","api"]`(零回归);幽灵 chunk(前缀不在 data_sources)不动、单列 reported。
- **幂等/可恢复**:语义等价即跳过;中断可重跑(重复运行安全);`--dry-run` 默认、`--apply` 执行、`--source` 可单源;只写属性不重嵌入。
- **前后兼容**:应用前后均兼容(缺失属性读取按默认公开解释)。
- **回滚**:无需(属性写入;旧行为=全公开)。何时必须:任何依赖 channel_visibility 的公开/内部隔离承诺生效之前。生产是否已跑:**PRODUCTION_STATE_UNKNOWN → 只读预检 P7**。

## M02 — `scripts/migrate_sales_leads.py` → REQUIRED(新表)

- **数据变更**:创建 `sales_leads` 表(幂等:存在即 skip 并报行数;`--dry-run` 支持)。
- **兼容性**:`backend/db/models.py:368` 已映射 `SalesLead`;`init_db = Base.metadata.create_all`(session.py:83)**会在启动时隐式创建缺失表** → 新应用首启即可自建。但显式脚本化执行更优:①带存在性/行数预检与 dry-run;②避免「启动期 DDL」混入健康判定。**回滚**:加性表,无需回滚;旧镜像忽略该表。

## M03 — `scripts/migrate_conversations_session_id.py` → REQUIRED,**硬前置(先于新应用启动)**

- **数据变更**:`ALTER TABLE conversations ADD COLUMN session_id VARCHAR(64)` + `CREATE INDEX IF NOT EXISTS idx_conversations_session_id`;幂等(检查列存在);历史 NULL 不回填(按设计)。
- **为何硬前置**:
  1. `Conversation` ORM 已映射 `session_id`(models.py:89)且 metadata 定义同名索引(models.py:441)—— 新应用对**旧表**启动时,`create_all` 会尝试补建缺失索引 → 对无此列的旧表 **CREATE INDEX 失败 = lifespan 启动失败风险**;
  2. 每条 `/api/ask` 持久化 `session_id=req.session_id`(routes.py:126)→ 即便侥幸启动,**全部对话持久化静默失败**(写入被 fail-open 捕获)+ lead 会话线程断裂。
- **与 M02 关系**:两者无 DDL 依赖(sales_leads 自有 session_id 列);但产品流上 lead 线程依赖 conversations.session_id → **推荐顺序 M03 → M02**(先补会话线程基座,再建线索表)。

## M04 — `scripts/migrate_site_experiences_i18n.py` → REQUIRED,**硬前置(先于新应用启动)**

- **数据变更**:`site_experiences` 补 `welcome_i18n`/`starters_i18n` JSONB 列 + 从 **YAML 权威**回填(只补 NULL,不覆盖已有值);幂等。
- **为何硬前置**:ORM 已映射两列(models.py:313-314)—— 新应用对旧表任何 `site_experiences` 读取/启动期 upsert 都会 UndefinedColumn(widget site-config 500、lifespan 报错)。
- **「无迁移可安全回退」核实**:源码中的回退(`site_experiences.py:48-73`,按语言键取 i18n、缺失回退默认语言字段)是**列存在之后的键级回退**;列缺失时 ORM 直接失败 —— **合同预期的「安全回退」仅在迁移完成后成立**,故 M04 仍为硬前置。

## M05 — `scripts/migrate_llm_chain_format.py` → **CONDITIONAL / PRECHECK / HIGHER-CAUTION**

> ⚠️ 本节经 Planner FINAL REVIEW 修正(原报告误标「幂等、无损」——不成立,见文末 §Planner Review Correction)。

**全部副作用(源码逐行核实,scripts/migrate_llm_chain_format.py)**:
1. `migrate_providers_available_models`:改写 `llm_providers.config.available_models`(空则从 `config.model` 初始化;并把默认 model **强制置首**重排)—— 供应商 config 为含凭证的 JSON,脚本整体改写该 dict;
2. `migrate_routing_chain_format`:`llm_routing.chain` 字符串 → `{provider, model}` 对象(无损表示转换);
3. **`cleanup_query_decomposition`:删除 `query_decomposition` 路由行** —— 若其归一化 chain ≠ generation,execute 模式仅打 WARNING 后**仍然删除**,即**丢弃一份自定义路由配置(有损)**;
4. `ensure_routing_exists("intent")`:缺失则从 generation **复制**创建;
5. `ensure_routing_exists("query_rewrite")`:缺失则从 generation 复制创建。

**运行时兼容**:`_normalize_chain_item`(config_loader.py:40,读取路径)对旧字符串即时归一化 → **旧字符串表示本身不构成执行 M05 的必要条件**。
**幂等性**:重复执行安全(存在即 skip);但「幂等」≠「无损」—— 第 3 项首次执行即不可逆丢弃自定义 chain。
**生产裁决标准**:见 §Required Read-Only Production Precheck P6(扩展版:成员/格式/语义三查 + CASE 1-5 决策)。**默认裁决 = 不执行,除非扩展预检证明全部副作用可接受**。

## SUPERSEDED / HISTORICAL(逐项核实)

| 脚本 | 分类 | 依据 |
|---|---|---|
| `migrate_add_site_experiences.py` | **已应用(生产已知)** | PA-0C 曾在生产执行;site_experiences/site_id/llm_allowed_hosts 已在生产核实存在(PA-0C 报告+P0-B2 读数) |
| conversations.site_id | **已应用(生产已知)** | 同上(site_id 列生产在位,PA-0C/PA-0F 实证) |
| `migrate_add_country.py` | 生产大概率已应用(间接证据:生产 conversations 行含 country 值,PA-0D 冒烟读数);**脚本级确认 → PRODUCTION_STATE_UNKNOWN(P3 预检)** | — |
| `migrate_add_symbol_props.py` | Weaviate 属性类;生产 ne301 代码块已带 symbol_*(PA-0F 迭代证据)→ 大概率已应用;**PRODUCTION_STATE_UNKNOWN(P8)** | — |
| `migrate_github_source_schema.py` | 生产 github 源 config 已含 `branches[]` 新形态(P0-B2 data_sources 读数)→ **已应用(生产已知)** | — |
| `migrate_intent_tag_8to4.py` | 生产 intent_tag 已为 4 分类值(product/support/commercial,PA-0D/0E 会话行实证)→ **已应用(生产已知)** | — |
| `migrate_yaml_to_db.py` | 生产 llm_providers/llm_routing/configLoader DB 化已在位(PA-0C/0D 实证)→ **已应用(生产已知)** | — |
| 上述历史脚本重跑风险 | 均为幂等设计,但**不列入本次计划**(避免无谓触碰);如需重跑逐个另行裁决 | — |

# Migration Dependency & Compatibility Matrix

依赖/顺序(由实现推导,非默认假设):

```
M03(conversations.session_id+索引)  ─┐
                                      ├─ 均为「新应用启动前」硬前置;互相无 DDL 依赖
M02(sales_leads 建表)               ─┘   推荐次序 M03 → M02(会话线程基座先行)
M04(site_experiences i18n 列+回填)  ── 「新应用启动前」硬前置(与 M02/M03 无相互依赖)
M01(channel_visibility 回填)        ── 任意时刻;建议在镜像切换前完成(隔离承诺前置)
M05(llm chain 归一化+qd 删除等)     ── CONDITIONAL/HIGHER-CAUTION:仅当扩展预检 P6 证明全部副作用可接受(CASE 1/2);CASE 3 自定义 chain → 停,人工决策
```

**四态兼容矩阵**:

| 状态 | 兼容性 | 依据 |
|---|---|---|
| OLD APP(3bf945b) + OLD SCHEMA | ✅ 即当前生产 | 运行至今 |
| **OLD APP + NEW SCHEMA** | ✅ **安全**(全部迁移加性;旧 ORM 不映射新列/新表;新索引由新应用 metadata 定义,旧应用不执行) | **支持「旧应用服务中执行迁移」,停机最小化** |
| **NEW APP + OLD SCHEMA** | ❌ **禁止**:启动期索引补建失败风险 + conversations 持久化全量静默失败 + site_experiences 读写 500 | models.py:89/441/313-314 + init_db=create_all 语义 |
| NEW APP + NEW SCHEMA | ✅ 目标态 | — |

(注:NEW+OLD 的「启动失败风险」基于 SQLAlchemy create_all 对既有表缺失索引的补建语义,置信度高;预检后可在 staging/事务内再实证。)

# Configuration Compatibility(3bf945b → 193f206 diff 实测)

`git diff 3bf945b 193f206 -- backend/config.py deploy/prod/.env.example` = **空**(无新增必需环境变量);`config/system_prompt.yaml` 无结构变化;**唯一配置面变化 = `config/sites.yaml`(+35/−6,多语言 i18n 内容)**,随镜像分发。

| 项 | 分类 | 说明 |
|---|---|---|
| 环境变量 | BACKWARD_COMPATIBLE | 无新增 REQUIRED_BEFORE_START |
| `config/sites.yaml` i18n 内容 | REQUIRED_BEFORE_START(随镜像自动满足) | M04 回填的数据源 |
| Sales Lead | OPTIONAL_WITH_SAFE_DEFAULT | 表就绪即工作;lead 上下文失败 fail-open(routes.py:126-133),不阻断问答 |
| Customizations | BACKWARD_COMPATIBLE | 表已在生产(Task 9 迁移);热重载见下节 |
| 多语言站点体验 | MIXED | M04 列 + sites.yaml 内容;服务层键级回退 |
| channel visibility | BACKWARD_COMPATIBLE(读取按默认公开) | 隔离承诺生效前跑 M01 |
| session_id | REQUIRED_BEFORE_START | 见 M03 |
| website/github 数据源 | BACKWARD_COMPATIBLE | 源已在生产(P0-B2 实证 15 源) |
| 嵌入/重排模型路径 | BACKWARD_COMPATIBLE | `/models` 挂载不变 |
| GPU 运行时 | BACKWARD_COMPATIBLE | compose GPU 段不变;显存约束为已知运行风险(非本 Gate) |

# Prompt Hot Reload Deployment Implications

- freeze 含热重载(`set_customization_snapshot` rag.py:270;`refresh_runtime_customizations` config_loader.py:132)。
- **无 schema 迁移需求**(customizations/customization_bindings 表已在生产);**无新配置项**;普通镜像替换/重启即完整获得该能力。
- Admin 变更(创建/更新/删除/绑定)持久化成功后即时刷新运行时快照;刷新失败返回 HTTP 500 显式上报(运行时保持上一份有效快照)。
- **部署约束(记录,不重设计)**:快照刷新作用于受理请求的单进程 —— compose 单 backend 容器满足 V1 假设;未来多 worker/多容器需要分布式失效(另立 Gate)。

# Recommended Deployment Sequence(从实现推导)

前置顺序原则:利用「OLD APP + NEW SCHEMA = 安全」,迁移在旧应用服务期间执行,镜像切换一次性完成,预计停机 ≈ backend 重启窗口(~1-2 分钟,BGE 加载)。

1. 只读预检(见下节)全绿;
2. (可选维护窗)备份:`pg_dump ask_ai` + Weaviate 快照(或至少记录 counts/来源分布基线);
3. 迁移(旧应用运行中,逐脚本 dry-run → 执行):**M03 → M02 → M04**;P7 显示未跑则 **M01**;**M05 不随批执行** —— 仅当 P6 扩展预检进入 CASE 1(无需变更→跳过)或 CASE 2(全部副作用书面确认安全→单独授权执行);CASE 3/4/5 → STOP,人工发布决策;
4. schema 复核(只读查询:列/表/索引在位);
5. `./update.sh sha-193f206`(后端替换 → 健康门 → sync-cron 替换);
6. 启动健康:容器 healthy、`/app/.git-sha=193f206…`、日志无 Traceback、模型加载完成;
7. 部署验收冒烟(见 Deployment Acceptance);
8. 监控窗(≥1 个 sync-cron 周期):sync_log 状态、错误日志、GPU。

# Rollback Strategy(四轨分离)

| 轨道 | 策略 |
|---|---|
| IMAGE | 回滚到旧 tag/digest(预检确认现役镜像后定锚,如 `sha-3bf945b`):`ASKAI_IMAGE_TAG=<old> up -d backend` + sync-cron 同理 |
| DATABASE | **不做反向迁移**。全部迁移为加性(新表/新列/新索引/属性回填),**旧镜像与新 schema 兼容**(OLD APP + NEW SCHEMA ✅)→ 回滚 = 「schema 保留 + 旧镜像恢复」。任何破坏性 DDL 都不在计划内 |
| WEAVIATE | M01 仅写属性(旧行为=默认公开,属性冗余无害)→ 无需 Weaviate 回滚;恢复性退出 = 不执行 M01 即可 |
| CONFIG | 回滚 = 恢复旧镜像(配置随镜像);`.env` 未变更则无需处理 |

旧镜像(=预检确认的现役镜像)对新 schema 的可运行性:由「全部迁移加性」+「旧 ORM 未映射新列」从源码推出;置信度高,但仍列入预检 P9 的旧镜像×新 schema staging 实证(若生产现役镜像 ≠ 3bf945b 则必须重新评估)。

# Required Read-Only Production Precheck(最小集,供下一 Gate 申请)

| # | CHECK | WHY | 只读方法 | 安全结果 | 阻断结果 |
|---|---|---|---|---|---|
| P1 | 现役 backend/sync-cron 镜像 + `/app/.git-sha` | 确定回滚锚与真实起点(不得假设 3bf945b) | `docker inspect … --format Image/git_sha` | 任意已知值 | 未知镜像 |
| P2 | compose 服务状态/健康 | 部署窗口基线 | `docker compose ps` / `curl :18000/health` | 全 healthy | 服务缺失 |
| P3 | PG:conversations 是否已有 `session_id` 列/索引 | M03 必要性 | information_schema 查询 | 缺失→需 M03 | 已存在→跳过 |
| P4 | PG:`sales_leads` 表是否存在 | M02 必要性 | information_schema | 缺失→需 M02 | 已存在→跳过 |
| P5 | PG:`site_experiences` 是否已有 i18n 两列 | M04 必要性 | information_schema | 缺失→需 M04 | 已存在→跳过 |
| P6 | **M05 扩展预检**:A. `llm_providers`:id、`config.available_models` 缺失/空否、`config.model` 在否(**不输出凭证**);B. `llm_routing`:task 名单(generation/query_decomposition/intent/query_rewrite 是否存在)+ chain 结构格式(字符串 vs 对象);C. 若 query_decomposition 存在:归一化 chain 与 generation **语义比较** | M05 全副作用裁决 | `SELECT id, (config::json->>'available_models') IS NULL, (config::json->>'model') IS NULL FROM llm_providers`;`SELECT task, chain FROM llm_routing` | CASE 1(qd 缺席+intent/qr 合法+格式兼容)→ 跳过 M05;CASE 2(qd.chain==generation.chain)→ 仍须书面确认全部副作用后方可授权 | CASE 3/4/5(下节)→ 停,人工决策 |
| P7 | Weaviate:`channel_visibility` 属性覆盖率 + 按 data_sources 的分布 | M01 必要性/隔离基线 | aggregate/迭代抽样 | 缺失/全默认→需 M01 | 已回填→跳过 |
| P8 | Weaviate schema:symbol_* 属性在位否 | 历史迁移核对 | `/v1/schema` | 在位 | 缺失→人工裁决 |
| P9 | 旧镜像 × 新 schema staging 实证(可选) | 回滚可信度 | 预检外staging | 可启动 | — |
| P10 | 磁盘/GPU/模型资产 | 启动资源 | `df -h` `nvidia-smi` `ls /home/ubuntu/ask-ai/models` | 充足/在位 | 不足/缺失 |
| P11 | `sync_log` 最近状态 + conversations/traces 计数 | 恢复基线 | `SELECT … ORDER BY started_at DESC` | 正常 | 持续 failed |
| P12 | customizations/bindings 在位(default+widget) | 热重载/种子依赖 | `SELECT id FROM customizations` | 在位 | 缺失→启动种子补 |

(命令全部只读;不回显 secret。)

# Planned Production Mutation Runbook

## NOT AUTHORIZED FOR EXECUTION

仅当预检全绿并获得显式生产变更授权后,按仓库支持的机制执行:

| 步 | 动作 | 目的 | 前置 | 预期 | 失败停止条件 | 回滚 |
|---|---|---|---|---|---|---|
| 0 | 预检 P1-P12 | 事实基线 | 只读授权 | 全绿 | 任一阻断项 | 不开始 |
| 1 | 备份:`pg_dump` + Weaviate counts 基线快照 | 恢复锚 | P10 磁盘足 | dump 完成 | dump 失败 | 不开始 |
| 2 | 迁移 M03→M02→M04(逐个 `--dry-run` 再执行;P6/P7 条件触发 M05/M01) | schema 就位 | 旧应用运行中(加性安全) | 各脚本 [ok] | 脚本报错 | 无需(加性;保留 schema) |
| 3 | schema 复核(只读) | 确认 P3-P5 转绿 | 步 2 | 全在位 | 缺失 | 停;排查 |
| 4 | `./update.sh sha-193f206` | 镜像替换 | 步 3;健康门内置 | health 200,git_sha=193f206 | 120s 健康失败 | `ASKAI_IMAGE_TAG=<现役> up -d backend` |
| 5 | sync-cron 同 tag 替换 | 同步线对齐 | 步 4 健康 | running+git_sha 一致 | 反复重启 | 同 tag 回滚 |
| 6 | 部署验收(下节) | 证明 | 步 5 | 全过 | 任一硬失败 | 步 4 回滚 |
| 7 | 监控窗(≥1 sync 周期) | 稳定性 | 步 6 | 无新增 critical | OOM/持久化失败 | 评估回滚 |

# Deployment Acceptance

- 容器:backend/sync-cron 镜像=sha-193f206、`/app/.git-sha` 一致、healthy、Restarts=0;
- `/health` 200;启动日志:站点 upsert、lead/guard 加载、无 Traceback;
- schema:session_id 列+索引、sales_leads、i18n 列全部在位;
- API 冒烟:`/api/ask`(widget)200 且 conversation+trace 落库(**session_id 持久化生效**);
- Admin 冒烟:登录、customizations 列表/编辑(PATCH 后**下一条请求即生效**——热重载)、绑定读取;
- 多语言冒烟:widget site-config i18n 字段可取;
- Lead 冒烟:lead 流程端到端(创建→列表可见);
- 通道隔离冒烟:内部源对 widget 不可见(或与 M01 后基线一致);
- 语料/sync:sync-cron 周期 success,corpus 计数与基线一致。

# Natural Product Acceptance Boundary

部署验收之后,另立 Natural Product Acceptance(真实用户/产品行为):回答质量、引用合理性、lead 转化真实性、多语言体验、风格/边界定制的实际观感、长时稳定性与 GPU 行为。本 Gate 不做、也不预支其结论。

# Risks / Unknowns / Blockers

1. 生产现役镜像/迁移状态未知(历史证据 ≠ 现状)→ 预检 P1-P8 裁决;
2. NEW APP + OLD SCHEMA 的启动失败风险基于 create_all 语义推断(高置信),可在预检后用 staging 实证;
3. GPU 显存常驻约束(PA-0F P1)是运行期风险,与本 Gate 正交;
4. M01 在生产若从未运行,channel_visibility 隔离承诺在执行前不得开启;
5. 多 worker 热重载约束(当前单容器,满足);
6. **M05 有损路径**:query_decomposition 存在自定义 chain(≠generation)时执行 M05 将不可逆丢弃该路由配置 —— 已列入预检 CASE 3 = MANUAL MIGRATION DECISION REQUIRED。

# Acceptance Criteria Results

AC01✅(origin/main==freeze) AC02✅ §Frozen AC03✅ §Architecture AC04✅ §M01 AC05✅ §M02 AC06✅ §M03 AC07✅ §M04 AC08✅ §M05+P6 AC09✅ §Historical(不猜,UNKNOWN 标注) AC10✅ §Config AC11✅ §Hot Reload AC12✅ §Dependency AC13✅ §四态矩阵 AC14✅ §Rollback AC15✅ §Precheck(12 项) AC16✅ §Runbook(NOT AUTHORIZED) AC17✅ §两验收分离 AC18✅ AC19✅ AC20✅ AC21✅

# Production Access Declaration

PRODUCTION_ACCESS = NO;PRODUCTION_MUTATION = NO。全程仅本地仓库/一次性 worktree(`.worktrees/preflight-report`,已注册)。

# Final Status

**PASS** —— 仓库侧 Production Preflight 已完整,可支持 Planner 申请「READ-ONLY PROD ACCESS」下一 Gate。

---

## Planner Review Correction — M05 Safety

**前版报告错误**:将 M05 描述为「幂等、无损(表示形式归一化,不删数据)」。经 Planner FINAL REVIEW 指出并经本次源码重读确认,**该描述不成立**:脚本第 3 步 `cleanup_query_decomposition()` 在 execute 模式下**无条件删除** `query_decomposition` 路由行;当其 chain 与 generation 语义不同时,删除即**不可逆丢弃一份自定义路由配置**(dry-run 有 WARNING 提示,execute 无阻断)。此外脚本还会改写 `llm_providers.config.available_models`(含默认 model 重排)并按 generation 复制补建 intent/query_rewrite 路由 —— 均为必须显式核实的副作用。

**修正后的 M05 分类**:`CONDITIONAL / PRECHECK / HIGHER-CAUTION`。运行时 `_normalize_chain_item` 对旧字符串 chain 的读取期归一化仍然成立 → **旧字符串表示本身不使 M05 成为必需**;执行与否取决于扩展预检对全部副作用的逐项裁决。

**修正后的只读生产预检(P6 扩展)**:
- A. `llm_providers`:id、`available_models` 缺失/空、`config.model` 在否(不回显凭证);
- B. `llm_routing`:task 集合(generation / query_decomposition / intent / query_rewrite 在位情况)+ chain 结构格式;
- C. query_decomposition 存在时:归一化后与 generation.chain 语义比较。

**修正后的执行决策规则**(替换「旧字符串 → 跑 M05」):
```
READ-ONLY M05 STATE INSPECTION
  ├─ CASE 1:qd 不存在 + intent/query_rewrite 合法 + chain 格式运行时兼容 → NO CHANGE REQUIRED → SKIP M05
  ├─ CASE 2:qd 存在且归一化 chain == generation.chain → 删除大概率语义安全,但仍须书面确认
  │         available_models 重排与 intent/qr 补建副作用后 → M05 MAY BE AUTHORIZED(单独授权)
  └─ CASE 3:qd 存在且归一化 chain != generation.chain → STOP → MANUAL RELEASE DECISION → DO NOT RUN M05
      (CASE 4:intent/qr 缺失是否需 M05 补建 / CASE 5:available_models 需归一化 → 均须逐项书面确认)
```
本任务不授权上述任何动作。

**本修正仅改动本报告;产品代码零变更;生产零访问。**