# ASK-AI — Root README Full Regeneration 执行报告

- 日期:2026-09-02
- 模式:SINGLE CODEX(文档真相对齐;唯一产品文件变更 = README.md)
- 分支:`docs/readme-regeneration-2026-09-02`(基于 main @ `4d692e9a3e5597fd5730c81b6e91d091e6ff2aed`,origin/main 已核验一致;按 §19 不直接推 main)

---

## A. STATUS

**PASS**(Executor 验证通过;等 Planner FINAL REVIEW 后决定并入 main)

## B. BASELINE

`4d692e9a3e5597fd5730c81b6e91d091e6ff2aed` = 本地 main = origin/main(任务开始时 `git fetch` 后复核一致;无产品代码推进)。

## C. OLD README PROBLEMS

旧 README 仅 11 行:

1. 定位错误:「自建 RAG 系统」——把平台贬低为单一 RAG 实现,完全未体现意图层/引用完整性/信任边界/站点体验/Lead 捕获等专业咨询能力;
2. 能力面缺失:无 Admin 控制台、无 Headless API、无多语言、无多站点、无检索架构说明;
3. 结构缺失:无 What/Architecture/Capabilities/Configuration/Development/Deployment 任何一节;
4. 命令过时:无 `uv sync`(依赖安装)、无 Admin 启动、无测试命令;「填入 API Key」以外无环境说明;
5. 无 CamThink/ASK-AI 边界表述。

## D. SOURCE AUDIT(实际读取,非文件名推断)

| 子系统 | 审计结论(README 依据) |
| --- | --- |
| 入口 | `backend/main.py`:FastAPI + lifespan 全栈接线;`uvicorn` 直跑 |
| API | routes.py + admin/*:66 个端点(ask SSE/site-config/feedback/upload + admin 九域) |
| 管线 | rag/intent/query_rewrite/citation/canonical_url/social/lead_qualify/ingest/chunk/pruner/business_signals |
| 检索 | search(Weaviate hybrid+BM25+boost 桶)→ rrf.py(RRF 融合)→ rerank(bge-reranker-v2-m3)→ pruner |
| 引用 | citation.py(权威编号/流式校验/数值支持)+ canonical_url.py(canonical+provenance_url) |
| 多语言 | utils/language.py(resolve/normalize)+ widget language.ts/i18n.ts + sites.yaml i18n 变体 |
| Sales Lead | lead_qualify.py/lead_service.py/api/admin/leads.py + sales_leads 表 + session 线程 |
| 同步 | connectors/{github,local_git,filesystem,web_crawl} + scripts/sync.py + vector_consistency 对账 + data_sources.py 删除生命周期 |
| 存储 | db/models.py(PostgreSQL)+ Weaviate 1.28(embedder/bge.py:BAAI bge-m3 + reranker-v2-m3,MODEL_CACHE_DIR/EMBEDDER_DEVICE 可配) |
| LLM | llm/registry.py(task 链路由+failover)+ llm_providers.yaml + Admin 运行时管理;DeepSeek 实现 |
| 站点 | config/sites.yaml(三站,en 默认,i18n 变体)+ site_experiences 服务 + Origin 授权 fail-closed |
| Admin | 9 页(概览/数据源/对话审查/技术洞察/线索/模型/接入/覆盖/用户)+ JWT RBAC 三角色 |
| Widget | script 标签嵌入、data-site-id/data-language、SSE、附件、本地化 |
| 部署 | .github/workflows/build-image.yml(push main/tags v*.*.*./手动 → ghcr 单镜像;权重/语料不入镜像);deploy/dev compose(postgres:16-alpine+weaviate 1.28.0) |
| 测试 | 后端 pytest(TEST_DATABASE_URL)+ admin/widget vitest + tsc/vite build |
| 环境 | .env.example(存储/LLM/嵌入/服务/运维五组) |
| 信道 | channel 字段为来源标签(widget/discord/whatsapp/mcp/admin);**无独立 Discord/WhatsApp bot 实现**(README 如实声明) |
| License | 仓库无 LICENSE 文件 → 按 §8 允许,省略该节 |

## E. PRODUCT POSITIONING DECISIONS

- 定位:「AI product-knowledge and professional-consultation platform」——高于 RAG chatbot,但不夸大;
- CamThink = first product deployment;平台核心(ingestion/retrieval/citation/experience/integration)声明为 product-agnostic,同时**不否认**当前仓库含 CamThink 专用配置(sites.yaml 等),用「CamThink-specific content is configuration」精确表述;
- 信道(bot 类)与生产端点明确声明为**非当前实现/部署决定**,防止过度承诺。

## F. CAPABILITY TRUTH MATRIX(README 主张 → 源证据)

| README 主张 | 源证据 | 分类 |
| --- | --- | --- |
| Grounded Q&A + 引用校验 | pipeline/citation.py(+流式/终验/数值支持)+ 测试 | IMPLEMENTED |
| 四类连接器 | backend/connectors/ + registry | IMPLEMENTED |
| Hybrid+RRF+rerank | retrieval/{search,rrf,rerank}.py + embedder/bge.py | IMPLEMENTED |
| Intent 感知/social/off-topic | pipeline/intent.py + social.py + rag 短路 | IMPLEMENTED |
| canonical URL + provenance | canonical_url.py + _extract_sources | IMPLEMENTED |
| 信任边界 | channel visibility + source_visibility guard(fail-closed) | IMPLEMENTED |
| 多语言解析链+本地化 | utils/language.py + widget language.ts/i18n.ts + sites.yaml | IMPLEMENTED |
| 站点体验(Origin 授权) | site_experiences.py + routes 门禁 | IMPLEMENTED |
| Lead 捕获/移交/PII 隔离 | lead_qualify/lead_service/leads.py + PII mask + 测试 | IMPLEMENTED |
| LLM 供应商路由 | llm/registry.py(task 链+failover)+ DeepSeek | IMPLEMENTED |
| Admin 九域 | admin/src/pages/* + admin API require_role | IMPLEMENTED |
| Widget/Headless API | widget/ + /api/ask SSE 等 | IMPLEMENTED |
| 同步一致性/删除生命周期 | vector_consistency.py + data_sources.py + 测试 | IMPLEMENTED |
| Discord/WhatsApp bot | 无实现(仅 channel 标签) | 如实声明 NOT IMPLEMENTED |
| 生产端点/公开服务 | 部署决定 | DEPLOYMENT_DEPENDENT(谨慎措辞) |
| Customizations 三字段运行时效力 | 待独立调查 → README 仅泛称「per-channel customization profiles」 | 按 §12 谨慎措辞 |

## G. ARCHITECTURE VERIFICATION

Mermaid flowchart 三个子图(Clients/Core/Data)与 12 个节点逐一映射:API 层=backend/api+main lifespan 守卫;Pipeline=social→intent→rewrite;Retrieval=hybrid/BM25/boost→RRF→rerank→prune;Citation=citation.py;LLM=registry;Lead=lead_qualify/lead_service;PG/Weaviate/Sync=db+ingest+connectors。语法:单块 `flowchart TB`,3 组 subgraph/end 配对,引号标签无裸括号外露、无 `\n` 转义残留。

## H. QUICK START VERIFICATION

| 命令 | 核验 |
| --- | --- |
| `uv sync` / `uv sync --extra dev` | pyproject(Python≥3.12)+ uv.lock 存在;pytest 在 dev extra → Development 段已注明 `--extra dev` |
| `cp .env.example .env` | .env.example 在(20+ 键五组) |
| `docker compose -f deploy/dev/docker-compose.yml up -d postgres weaviate` | compose 文件在,服务名 postgres/weaviate 与文件一致 |
| `uv run python scripts/create_admin_user.py admin@… --name --role admin` | 脚本 argparse 用法逐字核对(密码 getpass 交互) |
| `uv run python scripts/sync.py` | 脚本在 |
| `uv run python -m backend.main` | main.py `__main__` uvicorn.run(host/port 来自 settings) |
| `npm run dev/test/build`(admin/widget) | 两 package.json scripts 逐字核对;admin dev=5174(README 如实标注) |
| `TEST_DATABASE_URL=…` | tests/conftest.py 契约一致 |

## I. DEPLOYMENT DESCRIPTION VERIFICATION

build-image.yml 触发=push main/tags v*.*.*/手动;产物=ghcr.io/harryhua-ai/ask-ai 单一自包含镜像(明确「权重与语料不入镜像」);README 明确「推 main 只构建镜像、不自动更新任何运行环境」与「main 可能领先于某环境已部署版本」(§13 SOURCE vs PRODUCTION ACTIVATION 区分)。

## J. CAMTHINK / ASK-AI BOUNDARY

专节「Current Deployment: CamThink」+ 首段定位:CamThink=first product deployment;专属内容=configuration(sites.yaml/sources/prompts);核心层 product-agnostic by design;并如实说明仓库现状含 CamThink 专用配置、未声称已是多租户通用 SaaS。

## K. FILES CHANGED

- `README.md`(11 行 → 全量重写;唯一产品文件变更,AC-22)
- `docs/implementation/ASK_AI_ROOT_README_REGENERATION_2026-09-02.md`(本报告)

## L. VALIDATION

- 相对链接/文件存在:9 个被引用路径逐一存在 ✓
- 命令核验:§H 全表 ✓
- Mermaid:单块、subgraph/end 配对、无 `\n`/裸括号陷阱 ✓
- 陈旧词 grep(Gate|Planner|Executor|FINAL REVIEW|worktree|FINAL PASS|提交 SHA):**零命中** ✓
- `git diff --check`:干净 ✓
- 不含:凭证/私有为生产细节/内部 gate 历史/性能或安全夸大声明(全部主张有 §F 源证据)

## M. ACCEPTANCE CRITERIA

AC-01~AC-24 全部 PASS:基于当前权威 main(B)、旧 README 仅作参考(C)、定位准确(D/E)、非“RAG 聊天机器人”表述(E)、CamThink 边界专节(J)、能力全部源证(F)、架构图逐节点映射(G)、知识源/检索生成/接口/Admin 主张准确(D/F)、Quick Start 与开发命令逐条核验(H)、部署描述与 CI 一致且区分构建≠部署(I)、无凭证/私有细节(L)、无临时噪音(L)、链接/Mermaid/diff-check 通过(L)、仅 README 一个产品文件变更(K)、零生产接触、报告已提交。

## N. RESIDUAL RISKS

1. Customizations(system_prompt/style_tone/guardrails)运行时效力正由独立只读调查确定;README 已按 §12 采用泛化措辞(未声称各字段必然影响最终生成),调查结论出来后可再精化一句。
2. README 为英文(面向评估者/工程师受众);如需中文版可后续并列提供,本任务未擅自扩充范围。
3. 仓库无 LICENSE 文件,README 按 §8 允许省略该节;若 Planner 希望声明许可,需先补 LICENSE 文件。
4. 仓库根存在历史遗留目录(`data/`、`gui-test-screenshots/`、`CHECKPOINT.md`、根级 `node_modules` 等);README 的 Project Structure 只列重要目录,未清理这些遗留物(非本任务范围)。

## O. PRODUCTION BOUNDARY

PRODUCTION_ACCESS = NO / PRODUCTION_MUTATION = NO / PRODUCTION_DB_MUTATION = NO / PUBLIC_TRAFFIC_CHANGE = NO

---

## Public-Facing Simplification Revision

- 日期:2026-09-02(后续指令:公开 README 简化 + 直接集成 main)
- 基线:`a8eaef3e90df9270a134abd34057545b2308cae6`(实测 fetch 后 origin/main = 本地 main = 期望值;热重载合并 a8eaef3 已在主干,本次全程保留)

### P1. 简化原因

首轮重生成版(243 行,72187fc)技术准确,但信息密度面向**内部工程验收**:公开项目主页访客应在 2–3 分钟内理解「是什么/能做什么/怎么架构/什么技术栈/怎么跑起来」。原版暴露了内部实现控制流、生产/部署状态、CamThink 部署语境、工程运营信息与实现限制说明——这些属于 `docs/`,不属于公开 README。

### P2. 移除的信息类别

- **整节移除**:Request Flow(7 步控制流)、Knowledge Sources(连接器表+删除生命周期)、Retrieval & Answer Generation(RRF/bucket/模型参数)、Interfaces(含通道 gap 声明)、Admin Console(逐页说明)、Configuration(逐面表)、Environment Variables(逐项组)、Database & Migrations(策略)、Deployment(CI/镜像发布细节)、Current Deployment: CamThink(专节)、Security & Trust Principles(逐条机制)、Direction(路线图)。
- **CamThink 提及 4 → 0**(AC-02 达成;§6 规则,不以其他部署示例替代)。
- **能力降为 CAPABILITY-LEVEL**:连接器不再逐一点名(仅「repositories, websites, files, and supported data sources」)、检索内部(RRF/boost 桶/分词)、引用校验算法、PII/Sales-Lead 机制、热重载/快照语义、信任边界机制全部 OMIT(§7/§10/§11/§12/§13)。
- 禁词扫描(CamThink/production/migration/Planner/Executor/Gate/worktree/FINAL REVIEW/NOT IMPLEMENTED/deployment dependent/hot reload):**零命中**。

### P3. 最终公开 README 结构

`# ASK-AI` 定位段 + tagline → **Overview**(3 段:知识接入与有据回答 / 咨询管线与意图自适应 / 可复用平台而非单一聊天机器人) → **Key Features**(9 项:Knowledge Ingestion / Intelligent Retrieval / Grounded AI Responses / Intent-Aware Assistance / Professional Consultation Flows / Multilingual Experience / Flexible LLM Integration / Widget & API / Admin Console) → **Architecture**(单 mermaid 概念图,12 节点:Users→Widget/API→Experience→Intent+RAG→Retrieval→(Knowledge Sources)→LLM Generation→Grounded Response,辅以 Admin/Sync/PG/Weaviate) → **Technology Stack**(9 行表,逐项对源核验) → **Quick Start**(clone + 6 步命令 + 前端两条) → **Project Structure**(8 目录一行一述) → **Development**(pytest/admin/widget 测试构建)。

### P4. 行数与验证

- **行数:243 → 150 行**(目标约 100–150 达成)。
- `git diff --check`:干净。
- Mermaid:单块 `flowchart TD`,节点 id 唯一(U/W/E/P/R/K/G/O/A/S/D/V),标签全引号、无裸括号/\n 陷阱。
- 命令核验(在 a8eaef3 树上复验):`.env.example`、`deploy/dev/docker-compose.yml`(postgres+weaviate 服务名一致)、`scripts/sync.py`、`scripts/create_admin_user.py`、`backend/main.py`、`uv.lock`(requires-python≥3.12)、admin/widget `package.json` scripts(dev/build/preview/test)全部存在;命令集沿用首轮 §H 已逐字核验版本。
- 相对链接:零(唯一链接为 uv 官方文档外链);禁词扫描含「Deployment」亦零命中。
- 保留性核验(未触碰):`backend/pipeline/rag.py` 含 `set_customization_snapshot`(1 处)、`backend/services/config_loader.py` 含 `refresh_runtime_customizations`(1 处)——热重载闭环完好。
- 主张真实性:9 项特性均有首轮 §F 真值矩阵 IMPLEMENTED 证据背书;无新增未证主张(未发明连接器/SaaS/多租户/认证/基准)。

### P5. 集成与治理

- SINGLE CODEX 模式,直接在 main 根工作树编辑(§2 允许复用干净工作树;根树 clean,其余 5 棵 worktree 属其他任务未触碰)。
- 提交 = README.md + 本报告追加节(单提交);fetch 复核 origin/main 未前进后直接 push(无 force);push 后复核 origin/main 一致、origin 树上 README 与热重载锚点在位。
- PRODUCT_CODE_CHANGED = NO;PRODUCTION_ACCESS/MUTATION = NO;CI 随 push 自然触发(未手动触发、未部署)。

### P6. 残余说明

1. 首轮 §N 各残余项(中文版/LICENSE/根目录遗留物)继续适用。
2. 公开版省略「如需部署/机制细节见 docs/」指引 —— docs/ 当前不公开,指引无意义;如未来开放文档再补。
3. 本节为对既有报告的追加,未新建报告文件(§15)。
