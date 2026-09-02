# CAMTHINK_V1_PRODUCTION_READ_ONLY_INSPECTION_2026-09-02

- 性质:只读生产检查(SSH + SELECT-only + Weaviate 读 + 容器/文件系统只读)
- 执行窗口:2026-09-02T07:59Z ~ 08:05Z(UTC)
- 授权:READ-ONLY PRODUCTION ACCESS(Product Owner 授权;未执行任何迁移/写入/部署/重启)
- 结论:生产健康;迁移决策矩阵:M02/M03/M04 = REQUIRED,M01 = ALREADY_APPLIED,**M05 = MANUAL_DECISION_REQUIRED**;部署变更就绪度 = NEEDS_DECISION

---

# Executive Summary

生产当前运行 **`sha-3bf945b`**(= P0-B2 部署态,未被进一步变更):backend/sync-cron healthy、Restarts=0、`/health` 200、启动以来零错误命中。PG/Weaviate 基线与 P0-B2 收官一致(conversations/traces 108/108,语料 126,418)。

迁移裁决(生产事实):
- **M03 REQUIRED**(conversations 无 session_id 列/索引)—— 新镜像启动即有失败风险,且对话持久化会静默失败 → 必须先于新镜像;
- **M02 REQUIRED**(`sales_leads` 表不存在;注意新应用启动期 create_all 会隐式建表,仍建议脚本化先行);
- **M04 REQUIRED**(`site_experiences` 无 i18n 两列;新应用对该表任何读写将失败);
- **M01 ALREADY_APPLIED**(`channel_visibility` 属性在位且全量覆盖,api=widget=126,418);
- **M05 MANUAL_DECISION_REQUIRED**:`query_decomposition` 路由存在且为旧字符串格式 `["deepseek"]`,归一化后 ≠ generation(`deepseek/deepseek-v4-flash`)→ 按 CASE_3 不自动执行;**补充决策证据:运行时代码无任何路径调用 task=query_decomposition(纯遗留行,删除不影响现有功能),但裁决权在 Planner**。

# Authorization Boundary

只读:SSH、docker inspect/ps/logs(有界)、`/health`、psql SELECT/catalog、Weaviate schema/aggregate/iterator 级读取、`df`/`nvidia-smi`/`ls`。未执行迁移/写入/DDL/同步/docker pull/重启/文件编辑;未读取任何 secret(供应商 config 仅 SELECT 安全键)。

# Actual Production Baseline

| 项 | 值 |
|---|---|
| backend | `tesla-t4-backend-1`,Image `sha256:d2d397935293…`(= `sha-3bf945b`),`/app/.git-sha = 3bf945bdc80829efabe5134dbc99711508d92b47`,healthy,Restarts=0,StartedAt 2026-09-02T03:09Z |
| sync-cron | 同镜像同 git_sha,running,Restarts=0,StartedAt 03:10:26Z |
| **镜像对齐** | backend 与 sync-cron **一致** ✓ |
| postgres / weaviate | Up 2 weeks,healthy(未动) |
| 主机镜像 | `sha-3bf945b`(d2d39793)= 现役;`sha-1ed84bb`、`latest`(c87518e1)在位;`sha-193f206` **未拉取**(符合只读边界) |
| **ROLLBACK_IMAGE_CANDIDATE** | **`sha-3bf945b`(d2d39793)= 当前现役镜像** |

# Service Health

- `GET /health` = 200;五容器全部 up(postgres/weaviate Up 2 weeks healthy)。
- 自本轮启动(03:09Z)日志有界扫描:Traceback/CUDA OOM/UndefinedColumn/Connection refused = **0**;「写入 conversations 表失败」= 0。

# PostgreSQL Migration State(SELECT-only)

| 检查 | 结果 |
|---|---|
| M03 列 | `conversations.session_id` **不存在** |
| M03 索引 | `idx_conversations_session_id` **不存在** |
| M02 表 | `sales_leads` **不存在** |
| M04 列 | `welcome_i18n` / `starters_i18n` **均不存在** |
| 计数基线 | conversations 108 / traces 108 / site_experiences 3 rows |
| 定制存储 | customizations 1 行(default)+ widget→default 绑定(**OK**) |

# M05 LLM Routing Safety State

- **llm_providers**(安全键,无凭证):单供应商 `deepseek`;`config.model = deepseek-v4-flash`;`available_models` 存在且 = `["deepseek-v4-flash"]` → **CASE 5 未触发**(M05 步骤 1 无变更可做;model 已在集中,无重排)。
- **llm_routing 成员**:generation ✓、intent ✓、query_rewrite ✓(均为对象格式)、**query_decomposition 存在(旧字符串格式 `["deepseek"]`)**、另有无害的 `pruning`。
- **语义比较**:归一化 qd = `[{provider:"deepseek", model:None}]` ≠ generation = `[{provider:"deepseek", model:"deepseek-v4-flash"}]` → **CASE_3**。
- **决策补充证据(供 Planner)**:`query_decomposition` 在运行时代码中**零调用点**(grep 全 backend 非测试代码无引用)—— 该路由行为遗留行;删除不影响现有功能,但按冻结规则仍属 MANUAL_DECISION_REQUIRED。
- **M05_STATE = MANUAL_DECISION_REQUIRED**(DO NOT RUN M05;若 Planner 决定清理 qd 遗留行,可由独立小 Gate 以显式 SQL 完成,无需运行 M05 全脚本)。

# M01 Channel Visibility State

- `Document.channel_visibility` 属性在 schema 中存在;
- 覆盖:aggregate `api=126,418` 且 `widget=126,418`(= 总量)→ 全量对象双值,**无缺失/空属性可观测**;
- 分布:与当前 data_sources 全公开配置一致(15 源均无 channel_visibility 覆盖键);
- **M01_STATE = ALREADY_APPLIED**。
- 单列报告:10 个已知 ghost 对象(旧 URL,账本外)仍保留于 web_crawl 371 中 —— 不影响 M01 判定(其属性同为双值),移交 P1 sync 生命周期部署 Gate 处置。

# Historical Schema Sanity

`Document` 的 `symbol_name/symbol_signature/symbol_node_type/symbol_tokens` 属性全部在位 → **SYMBOL_SCHEMA_STATE = OK**。不重跑历史迁移。

# Resource Readiness

- 磁盘:`/` 1.3T 总量,已用 278G(23%),余 951G —— 充足;
- GPU:T4 16,384 MiB,已用 14,687 MiB,util 0%(常驻约束已知,非部署阻断);
- 模型资产:`/home/ubuntu/ask-ai/models/` 在位(HF `hub`/`xet` 布局);运行证据:现役 backend 启动时 BGE-m3 + reranker 加载完成(5 小时前)→ 资产可用。
- **RESOURCE_READINESS = PASS**。

# Sync Health

- sync-cron:running,Restarts=0;最近周期(07:29–07:32):除 `website-camthink=partial` 外全部 success(woocommerce/wiki/neomind 家族等);
- `website-camthink` **partial 循环**:已知残留(10 ghost + 旧自愈分支,见 PA-0F/P1 线)—— 语料无损失(web_crawl 371 稳定),每轮空转重灌属已定位问题,修复已在 main(待部署);
- 最新成功:多源 07:29-07:32;corpus 基线:total **126,418**(github +4 为上游合法新内容),web_crawl 371 / filesystem 481 / woocommerce 101。
- **SYNC_BASELINE = WARN**(website-camthink partial 循环;无数据损失;修复待部署)。

# Customization Storage Sanity

`customizations`(1 行,default)与 `customization_bindings`(widget→default)在位;现役 backend 启动日志无定制加载错误 → **CUSTOMIZATION_STORAGE_STATE = OK**(热重载前置满足;未做任何 PATCH)。

# Migration Decision Matrix

| 迁移 | 裁决 | 依据 |
|---|---|---|
| M01 channel_visibility | **ALREADY_APPLIED** | §M01(属性全量覆盖,分布=配置语义) |
| M02 sales_leads | **REQUIRED** | 表不存在(建议镜像切换前脚本化执行;启动期 create_all 亦可兜底建表) |
| M03 conversations.session_id | **REQUIRED(硬前置)** | 列+索引缺失;新应用启动/持久化失败风险 |
| M04 site_experiences i18n | **REQUIRED(硬前置)** | 两列缺失;新应用对该表读写将失败 |
| M05 llm chain | **MANUAL_DECISION_REQUIRED** | CASE_3(qd 自定义 chain)+ 运行时零调用证据供裁决;CASE 5 未触发 |

# Blockers / Risks

1. **M05 遗留路由处置需 Planner 决策**(qd 运行时惰性 → 删除功能上无害;但冻结规则要求人工裁决;若裁决删除,建议独立小 Gate 以显式 SQL 执行,不运行 M05 全脚本以免连带 available_models 重排等副作用);
2. M02/M03/M04 必须先于新镜像启动执行(NEW+OLD = 启动失败/持久化丢失/站点体验 500,Preflight 四态矩阵);
3. GPU 常驻 14,687/16,384 —— 部署重启窗口内模型重载无额外风险,但运行期 sync embed 通道决策仍开放;
4. `website-camthink` partial 循环在 sha-3bf945b 上持续(无害空转);P1 生命周期修复部署后收敛;
5. 10 ghost 对象待 P1 修复部署后自动退休(预期 AUTO_SAFE_RETIREMENT)。

# Recommended Next Gate

**Production Deployment(变更授权 Gate)**:按 Preflight 报告 Runbook 执行 —— 预检已由本报告完成 → 备份(pg_dump)→ 迁移 M03→M02→M04(旧应用服务中,加性安全)→ schema 复核 → `./update.sh sha-193f206` → 健康/冒烟(对话持久化含 session_id、Admin 定制热重载、多语言、lead、通道隔离、sync)→ 监控窗。M05 不入批(除非 Planner 对 qd 做出裁决并另行授权)。

# Production Access Declaration

PRODUCTION_ACCESS = YES(READ-ONLY);PRODUCTION_MUTATION = NO;PRODUCTION_DB_MUTATION = NO;PRODUCTION_WEAVIATE_MUTATION = NO。实际使用的只读命令类别:`ssh`、`docker inspect/ps/logs(exec cat /app/.git-sha、exec python 只读 HTTP 查询 Weaviate)`、`psql(SELECT/catalog)`、`curl /health`、`df`、`nvidia-smi`、`ls`。未输出任何 secret。
