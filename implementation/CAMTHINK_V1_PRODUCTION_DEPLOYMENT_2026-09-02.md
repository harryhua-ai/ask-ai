# CAMTHINK V1 — PRODUCTION DEPLOYMENT REPORT (2026-09-02)

# Executive Summary

生产已从 `sha-3bf945b` 成功升级到冻结发布版 **`sha-193f206`**（backend + sync-cron 双容器，身份核验一致），迁移 M03/M02/M04 按序执行并逐一验证，全部硬性验收通过，无需回滚。

- 备份先行（pg_dump custom 格式 6.2MB，归档完整性已验证）；
- 旧应用在加性 schema 上全程健康（兼容性契约 OLD APP + NEW ADDITIVE SCHEMA = SAFE 得到实证）；
- 部署后核心问答/会话持久化/session_id、多语言站点体验、销售线索、定制热重载、通道可见性全部冒烟通过；
- sync 首个自然周期（08:23–08:27Z）验证 P1 生命周期修复已生效：5 个确认退休 ghost 被精确删除，5 个仍属权威源的孤儿按设计保留，旧的不安全自愈循环消失；
- 遗留：website-camthink 因 5 个页面持续抽取失败（404/薄内容）仍报 partial（保守设计产物，非不安全行为）；"hi" 探针触发意图识别 fail-open（既有行为，记 backlog）。

# Authorization

Product Owner 显式授权（CAMTHINK V1 PRODUCTION DEPLOYMENT GATE）：

- 允许：备份、仅 M03/M02/M04 迁移、schema 只读复核、拉取并部署 `ghcr.io/harryhua-ai/ask-ai:sha-193f206`、经既有机制替换 backend/sync-cron、部署验收冒烟、有界监控窗、硬失败时回滚至 `sha-3bf945b`。
- 明确禁止（均未执行）：M01、M05、修改 query_decomposition / llm_routing / llm_providers、修复 Issue #4、Weaviate 语料/schema 变更、删除 ghost、无关 DB 清理、改 .env / 凭证 / DNS / 代理、部署冻结发布与授权回滚以外的任何镜像。

# Frozen Release

- AUTHORITATIVE_SOURCE = `193f206a3d0e8695f1c40766a1ba54667fcba2fb`
- TARGET_IMAGE = `ghcr.io/harryhua-ai/ask-ai:sha-193f206`
- TARGET_OCI_INDEX_DIGEST = `sha256:c7752f2941bb3188a4b852748bb4a9cfa208a908986752fffdb95f5bc323c347`
- PRE_DEPLOY_IMAGE = `sha-3bf945b`（ImageID `sha256:d2d39793…`，即回滚锚点）
- Preflight 证据：`docs/implementation/CAMTHINK_V1_PRODUCTION_DEPLOYMENT_PREFLIGHT_2026-09-02.md`（81c6fcc）
- 只读巡检证据：`docs/implementation/CAMTHINK_V1_PRODUCTION_READ_ONLY_INSPECTION_2026-09-02.md`（62ecedc）

# Pre-Mutation Reconfirmation

（首个生产写入前的只读复核，全部与巡检基线一致 → 无漂移）

| 检查 | 结果 |
|---|---|
| backend / sync-cron 镜像 | 均 `sha-3bf945b`，ImageID `d2d39793…`，git_sha `3bf945bd…` |
| Restarts / OOM | backend 0 / sync-cron 0，均 running，OOMKilled=false |
| `/health` | 200 |
| M02/M03/M04 仍缺失 | session_id 列/索引、sales_leads、welcome_i18n/starters_i18n 全部不存在 ✓ |
| 磁盘 | `/` 951G 可用（备份充足） |
| 目标镜像未部分部署 | 主机无 `sha-193f206` 镜像，容器均运行旧镜像 ✓ |
| 近 30 分钟错误 | 0（Traceback/CUDA OOM/UndefinedColumn/Connection refused） |

**结论：RECONFIRMATION = PASS（无 PRODUCTION_BASELINE_DRIFT）**

# Backup

- 机制：postgres 容器内 `pg_dump -Fc`（custom 格式，gzip 压缩），输出重定向至宿主机带时间戳路径；
- BACKUP_PATH = `/home/ubuntu/ask-ai/backups/pg_askai_predeploy_20260902T081832Z.dump`
- BACKUP_SIZE = 6,224,929 bytes（非空）
- BACKUP_TIMESTAMP = 2026-09-02T08:18:32Z
- 完整性验证：`pg_dump` 退出码 0；`pg_restore -l` 成功列出归档（TOC Entries 77，TABLE/TABLE DATA 条目 34，dbname `ask_ai`，Format CUSTOM）；
- 未做恢复演练（Gate 未要求）；Weaviate 备份未创建（本批迁移均为 PostgreSQL-only，M01 跳过，Gate 明确不要求）。

**BACKUP_STATUS = SUCCESS**

# Migration Execution

> 执行方式说明（与 Gate 默认设想的唯一偏差，已按"具体仓库事实"条款处理）：现行生产镜像 `sha-3bf945b` 内**不含**三个迁移脚本（`scripts/` 下无 migrate_conversations_session_id / migrate_sales_leads / migrate_site_experiences_i18n；其中 M02 脚本 import 的 `SalesLead` 模型亦只存在于目标代码）。因此先拉取目标镜像（仅 docker pull，非部署变更）并完成身份核验，再以 `ASKAI_IMAGE_TAG=sha-193f206 docker compose run --rm --no-deps backend python scripts/…` 一次性容器执行迁移；旧应用容器全程未动。迁移顺序仍严格为 M03 → M02 → M04。

## M03

- 脚本：`scripts/migrate_conversations_session_id.py`
- dry-run：`[dry-run] conversations.session_id 不存在,将在非 dry-run 模式添加`
- 执行：`[ok] conversations.session_id 列与索引已创建`
- 验证（information_schema / pg_indexes）：`session_id character varying(64)` ✓；`idx_conversations_session_id` ✓；conversations 行数不变（108）✓

## M02

- 脚本：`scripts/migrate_sales_leads.py`
- dry-run：`[dry-run] sales_leads 不存在,将在非 dry-run 模式创建`
- 执行：`[ok] sales_leads 表已创建`
- 验证：表存在，27 列与模型定义一致（id/session_id/status/contact_*/…/created_at/updated_at）；无既有表被改动

## M04

- 脚本：`scripts/migrate_site_experiences_i18n.py`
- dry-run：两列均不存在，将创建
- 执行：`[ok] welcome_i18n 已创建`、`[ok] starters_i18n 已创建`、`[ok] 回填完成,更新 3 行`
- 验证：两列均 JSONB；3 行既有站点全部保留；回填内容形状合理（`welcome_i18n = {"zh": …}`、`starters_i18n = {"zh": [4 项]}`，YAML 权威值），无覆盖性数据丢失

# Post-Migration Schema Verification

镜像替换前（老应用在跑）：

- `/health` = 200；backend Restarts=0（非 crash-loop）；
- 迁移后 10 分钟日志窗口：Traceback/UndefinedColumn/UndefinedTable/ERROR = 0；
- schema 汇总：session_id(1) + idx(1) + sales_leads(1 表) + i18n 列(2) 全部在位；
- 老应用读路径抽查：`/api/widget/site-config` 422（缺 site_id 参数）→ 403（Origin 守卫，应用层正常响应）——路由/应用行为正常，无 schema 类 500。

**兼容性契约 OLD APP + NEW ADDITIVE SCHEMA = SAFE：实证成立。**

# Image Deployment

- 拉取：`docker pull ghcr.io/harryhua-ai/ask-ai:sha-193f206`（Digest = `sha256:c7752f29…` 与冻结 digest 完全一致）；
- 部署：`deploy/prod/update.sh sha-193f206`（既有仓库机制：export ASKAI_IMAGE_TAG → pull → `up -d backend` → 120s 健康轮询 → `up -d sync-cron`）；
- 结果：backend 重建后 41 秒内 healthy；sync-cron 重建后正常启动；未发明新拓扑、未跑 reindex、未跑 ad-hoc sync；
- 部署时刻：sync-cron StartedAt = 2026-09-02T08:23:04Z（backend 略早，health 轮询通过）。

# Runtime Identity

| 容器 | Config.Image | ImageID | /app/.git-sha |
|---|---|---|---|
| backend | `ghcr.io/harryhua-ai/ask-ai:sha-193f206` | `sha256:b8528b58…` | `193f206a3d0e8695f1c40766a1ba54667fcba2fb` |
| sync-cron | `ghcr.io/harryhua-ai/ask-ai:sha-193f206` | `sha256:b8528b58…` | `193f206a3d0e8695f1c40766a1ba54667fcba2fb` |

- 双容器镜像/git_sha 对齐 ✓；OCI label `org.opencontainers.image.revision` = `193f206a…` ✓。

# Health Acceptance

- `/health` = 200；backend healthy，sync-cron running；Restarts 均为 0，OOMKilled=false；
- 启动日志扫描：Traceback / UndefinedColumn / CUDA OOM / FATAL = 0；
- 模型加载完成证据：`BGE-m3 加载完成`、`加载 bge-reranker-v2-m3(device=cuda…)`、`bge-reranker 加载完成`。

**HEALTH_ACCEPTANCE = PASS**

# Core API Acceptance

- `POST /api/ask`（widget 渠道，真实问题「CamThink NE503 有哪些主要特性?」）→ SSE 正常：sources → tokens → `done`，conversation_id `873eccb6-a153-4997-99fb-d7bb9b69126b`，带引用标记 token。

**CORE_API_ACCEPTANCE = PASS**

# Conversation / Trace / Session Persistence

- conversations 行在位：`873eccb6…`，channel=widget，**is_answered=t**；
- **session_id 持久化**：请求携带 `session_id=deploy-smoke-193f206-0902`，DB 行该列值一致 ✓；
- traces 在位：该会话 1 条（type=rag）✓；无静默持久化失败（部署后 conversations 计数增长与冒烟次数一致）。

**CONVERSATION_PERSISTENCE = PASS；SESSION_ID_PERSISTENCE = PASS**

# Multilingual Site Experience Acceptance

- `GET /api/widget/site-config?site_id=camthink-website&language=zh`（Origin=https://www.camthink.ai）→ 200，welcome/starters 返回**中文变体**（读自迁移产生的 `welcome_i18n`/`starters_i18n` 新列）；
- 同端点 `language=en` → 200，回落站点默认英文内容，响应形状不变；
- 无 500 / UndefinedColumn；未变更任何站点配置。

**MULTILINGUAL_ACCEPTANCE = PASS**

# Sales Lead Acceptance

- 冒烟路径：真实产品流 `POST /api/ask`，消息含合成联系方式 `deploy-smoke-test@example.com`（无真实 PII，example.com 明显可识别），session_id 同上；
- 结果：问答正常完成（conversation `0642d020…`）；`sales_leads` 新增一行：contact_type=email，contact_masked=`d***@example.com`，status=`contact_captured`，source_conversation_id 关联冒烟会话，session_id 一致 ✓；
- Admin 读路径（/api/admin/leads）未实测（需 admin 会话；以 DB 层证据 + 创建路径通为验收，记录为可选后续）；
- 合成测试记录按 Gate 条款**保留未删**（清理属额外变更），已在 Production Mutation Inventory 中列明。

**SALES_LEAD_ACCEPTANCE = PASS**

# Customization Hot Reload Acceptance

采用零用户可见影响的可逆方案（不动 default 配置、不动 widget 绑定）：

1. 记录现状：customizations 仅 `default` 1 行；绑定 `widget→default`；
2. `POST /api/admin/customizations` 创建临时未绑定配置 `zz-deploy-smoke-hotreload` → **201**（该端点在 commit 后调用热重载刷新 `_refresh_or_500`；若刷新失败将返回 500 —— 201 即证明「DB 已持久化 → 运行时快照已原子刷新」链路在生产真实跑通）；
3. `DELETE /api/admin/customizations/zz-deploy-smoke-hotreload` → **204**（再次走刷新路径）；
4. 复核：customizations 回到仅 `default`；绑定不变；随后 `POST /api/ask` 正常完成（刷新后运行时健康）。

未采用「改 default 提示词→观测→还原」的方案：任何注入测试标记都会短时暴露给真实 widget 用户，判为不必要风险；热重载机制路径（写库→刷新→生效）已由 201/204 + 后续问答正常所证明。

**HOT_RELOAD_ACCEPTANCE = PASS**（无测试配置残留）

# Channel Visibility Acceptance

- M01 按裁决跳过（ALREADY_APPLIED）；仅做读验证：
- Aggregate（weaviate v4 客户端，容器内只读）：`channel_visibility: api=126,413 且 widget=126,413`，双值全量覆盖，无缺失可观测；
- 当前生产 15 源均为公开配置，**本 Gate 无法从现有数据证明「内部源不泄漏」的反例**（如实记录，不构造）；
- widget 问答冒烟正常返回，无受限源暴露迹象。

**CHANNEL_VISIBILITY_ACCEPTANCE = PASS（含上述阴性用例不可证声明）**

# Sync Acceptance

部署后**首个自然 cron 周期**（未人为触发 sync）：

- 周期：2026-09-02T08:23:04Z 容器启动即开跑，08:23:32–08:27:43 完成全部 15 源；随后进入 3600s sleep；
- 结果：**14/15 源 success**；`website-camthink = partial`（error_detail 见下）；
- website-camthink 生命周期证据（新镜像行为）：
  - `EXTRA_CONFIRMED_RETIRED=5`：company、product-category/ai-cameras(+/feed、/ne101-cameras、/ne301-cameras) 已不在权威源（完整发现），**按各自确定性 UUID 精确删除**，每篇仅 1 个 chunk；
  - `EXTRA_UNRESOLVED_ORPHAN=5`：product、product/ne301、register、solutions/infrastructure-monitoring、tools 仍在权威成员集但本轮抽取失败（404 /shop/ 重试耗尽、薄内容跳过），**保留不删除**；
  - 复验：`366/361 chunks, MISSING_LEGITIMATE=0`；
  - **旧的不安全行为（no-change 分支全量重灌空转 + KeyError + 永久 partial 恶化）未再出现**；
- 语料基线对比：126,418 → 126,413（web_crawl 371→366 = 5 个确认退休 ghost 的精确退休；github 125,465 / filesystem 481 / woocommerce 101 稳定）；**无质量删除/语料损失**；
- 10 个已知 ghost 按产品逻辑处置中（5 已自动退休，5 保留待其页面可抽取或成员集变化），未做任何手动清理。

error_detail（website-camthink）：
`一致性校验发现缺口 371/361 chunks;孤儿处置:EXTRA_CONFIRMED_RETIRED=5(精确删除),账本重建=0(零 embedding),EXTRA_UNRESOLVED_ORPHAN=5(保留待人工裁决);复验:366/361 chunks,MISSING_LEGITIMATE=0,EXTRA_UNRESOLVED_ORPHAN=5`

**SYNC_ACCEPTANCE = PASS**（已知不安全行为消除并实证；残留 partial 为保守设计产物，见 Risks/Residuals）

# Monitoring Window

有界监控窗（2026-09-02T08:23Z 部署完成 → 08:35Z 末次复查）：

- backend/sync-cron：Restarts 恒 0，running，OOMKilled=false；`/health` = 200；
- backend 全量日志错误扫描 = 1：即「"hi" 探针触发意图识别 JSON 解析失败 → fail-open 为 product（设计内降级，问答照常完成）」；
- Postgres 45 分钟窗口 ERROR 计数 11 条——逐一核验**全部为本次验收自己的只读探查 SELECT**（列名/类型写错的失败探测，如 trace_type、sync_logs 复数、json_array_length(jsonb)），应用产生的数据库错误 = 0；
- Weaviate：panic/fatal = 0；
- 会话持久化持续正常（窗内 3 次冒烟会话全部落库）；
- corpus 稳定于 126,413，无异常波动；GPU 14,915/16,384 MiB（模型常驻，预期水位）；磁盘 951G 可用；
- 下一自然 sync 周期预计 ~09:27Z（超出本 Gate 窗口，第一期已观察；后续周期由既有运维节奏覆盖）；
- 未做任何投机性调参。

**MONITORING_ACCEPTANCE = PASS**（"hi" fail-open 记为 backlog 候选，见 Deferred Items）# Rollback

**NOT REQUIRED**（ROLLBACK_REQUIRED = NO）。全程未触发任何硬回滚条件；锚点镜像 `sha-3bf945b` 仍留在主机上可随时使用。

# Deferred Items

- **Issue #4**（Admin LLM provider 删除按钮失效）：按 Gate 明确 DEFERRED，未触碰 provider 路由/凭证；
- **M05 / query_decomposition 遗留行**：按 Planner 裁决 SKIPPED；未运行 M05，未改动 llm_routing/llm_providers；`query_decomposition=["deepseek"]` 旧字符串行原样保留（运行时零调用点，惰性遗留）；
- **意图识别对闲聊输入的健壮性**：非 JSON LLM 输出触发 fail-open（设计内降级，无功能损失），建议后续 backlog 增强；
- **website-camthink 5 个 unresolved 孤儿**：对应页面 /shop/(404)、/register/、/tools/、/product/、/solutions/infrastructure-monitoring/（薄内容）在权威成员集内但持续抽取失败 → 每轮 partial 保留。属源站内容/爬取策略问题（需产品侧裁决：修复页面内容、调整 sitemap、或将 min_content_chars 调优立项），非部署缺陷；
- **Admin leads 读路径实测**：本次以 DB 证据验收，Admin API 列表页可作后续人工检查项。

# Production Mutation Inventory

实际执行的生产变更类别（全部在授权范围内）：

1. PostgreSQL 逻辑备份 1 份（pg_dump，宿主机路径）；
2. DDL 迁移 3 个：M03（conversations.session_id + 索引）、M02（CREATE TABLE sales_leads）、M04（site_experiences 两 JSONB 列 + 3 行回填 UPDATE）；
3. docker pull 目标镜像 1 次（ghcr.io，digest 核验）；
4. `./update.sh sha-193f206` 重建并替换 backend、sync-cron 两容器（正常服务镜像替换；无 DNS/代理/端口变更）；
5. 验收冒烟产生的应用级数据：conversations +3（含 traces +3，session_id=deploy-smoke-193f206-0902）、sales_leads +1（合成 example.com 线索，按 Gate 保留）；
6. Admin API 应用级变更：customizations 临时行创建→删除（净变更 0，绑定未动）。

未执行：M01、M05、Weaviate 写操作、ghost 清理、.env/凭证/路由变更、无关清理。

# Risks / Residuals

1. website-camthink 每轮 partial（5 个 unresolved 孤儿按设计保留）——需产品侧对源站页面质量/爬取策略做后续裁决；不构成部署缺陷；
2. 5 个保留孤儿在页面恢复可抽取前将持续出现在一致性报告中（MISSING=0、无扩散）；
3. M05 遗留行仍在 DB（惰性）；若未来清理须独立小 Gate 用显式 SQL，不得运行 M05 全脚本；
4. GPU 常驻高水位（~14.7/16GB）依旧：本次部署重启窗口模型重载无碍，运行期 sync embed 通道决策仍开放（既有 PA-0F 遗留项）；
5. 合成冒烟数据（3 会话 + 1 线索）留存于生产库，session_id 统一 `deploy-smoke-193f206-0902` 便于识别与后续裁决；
6. admin 默认密码仍在用（既有安全隐患，另有改密拍板项在途，非本 Gate 范围）。

# Final Status

**STATUS = PASS**

判定依据：备份成功；M03/M02/M04 全部应用并验证；目标镜像部署且身份正确；硬性健康/Schema/API 验收全过；无回滚。Sync 冒烟与热重载冒烟均通过；唯一的 partial（website-camthink）为保守设计产物且不安全行为已实证消除，不构成硬验收失败。

# Production Access Declaration

- PRODUCTION_ACCESS = YES；PRODUCTION_MUTATION = YES；PRODUCTION_DB_MUTATION = YES；PRODUCTION_WEAVIATE_MUTATION = NO；
- PUBLIC_TRAFFIC_CHANGE = NONE（仅正常服务镜像替换，无 DNS/代理/路由变更）；
- 全程未输出任何 secret（登录凭据仅在命令内使用，未写入任何报告/日志摘录；供应商配置未读取）。
