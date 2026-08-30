# ask-ai 产品定义、路线图与实现现状

> **日期**:2026-08-28(v3,同日两次定位升级)
> **性质**:产品基线文档 — 后续产品定义与规划工作的起点。事实部分(定位/能力/阶段)以代码与已归档 spec 为准;规划部分(§6.3、§9)含建议,待产品决策。
> **信息来源**:founding spec(`2026-07-27-ask-ai-design.md`)、全部 specs/plans/handoff、git 全量时间线、代码结构。
> **维护约定**:产品事实变化时更新本文档对应小节,不新建平行文档。
> **v2 变更**:产品主定位由"CamThink 自建系统"升级为"通用标准件,CamThink 是第一个用户",新增 §5 通用化差距分析。
> **v3 变更**:定位进一步精化为**中台服务**——核心是"多入口对接 + 可插拔数据源/LLM"的平台中枢(§1 三层产品架构)。入口层差距(渠道适配器、集成方 API 认证)纳入 §5,Phase 4 多渠道从远期项升为核心定位主线(§6.3-D)。

---

## 1. 产品定位

**一句话**:ask-ai 是一个**RAG 知识助手中台服务**——向上提供多个对接入口(Widget / 消息渠道 / MCP / HEADLESS API),向下可插拔接入各种数据源与 LLM 供应商,中间以统一管线完成检索增强问答,并配套管理后台、可观测与业务情报能力;**CamThink 是第一个用户/实例**。

**三层产品架构**(中台定位的产品视图):

| 层 | 角色 | 现状 |
|---|---|---|
| **入口层**(前台对接) | 渠道适配器:Widget / Discord / WhatsApp / MCP Server / 第三方系统 HEADLESS 调用 | 仅 Widget(官方旗舰前台);`POST /api/ask` 统一 HTTP+SSE 协议上已可被任意系统调用,但无集成方认证(API key)、配额按 IP 限流、预算为全局熔断——HEADLESS 半开放 |
| **中台层**(产品本体) | 统一 API + RAG 管线(意图/检索/重排/拒答/生成)+ 配置中心(Customization/意图/路由)+ 管理后台 + 可观测分析 | 已全部实现(§3);`channel` 字段自 Phase 1 贯穿数据模型,加入口"只写适配器、中台零改"的架构承诺成立 |
| **资源层**(可插拔后端) | 数据源连接器(github/filesystem/woocommerce/…)、LLM Provider(deepseek/openai_compatible/…)、embedder(BGE/CPU/GPU 档) | 双注册表插件化已就绪;已实现 3 类连接器 + 1 类 LLM provider,扩类型不改管线 |

> 该定位是 founding spec §3"统一 HTTP API + 渠道适配器"架构的**升格**:多渠道从 Phase 4 远期项变为产品核心定位的入口层;Widget 从"产品全部"变为"第一个/旗舰前台"。

**双层身份**(v2 起,仍有效):

| 层 | 身份 | 含义 |
|---|---|---|
| 产品层 | 通用中台标准件 | ask-ai 本体:可复用、可配置、可交付给第二个组织的 RAG 中台 |
| 实例层 | CamThink 实例 | 第一个部署:语料是 CamThink 产品线,业务参数(意图/品牌/分析域)是 CamThink 的 |

**历史背景**(立项决策,仍有效):Kapa.ai SaaS 数据出域,与数据自主冲突 → 自建;Hermes 改造四重错位 → 排除。"数据自主"从 CamThink 的要求升级为**标准件的核心卖点**(区别于 Kapa 的私有部署/自托管价值主张)。

**最终形态**:标准件多实例——每个租户/实例:自有语料接入(连接器插件)、自有品牌入口、自有意图体系与业务参数、自有 LLM 配置,数据全部留在自己基础设施;上游产品统一演进(入口层扩展 / 管线质量 / 运营闭环)。

**产品边界演进**:Phase 1 明确"只回答问题 + 推荐页面,不收集线索、不转人工、不做账户/订单查询"。此边界已部分松动——admin Phase 3 规划中的客户信息模型(§6.3-B1)将引入"留联系方式"轻量表单,是产品从纯问答向商业闭环的第一步,属规划未实施。

## 2. 用户与价值

| 用户群 | 触点 | 核心价值 | 当前状态 |
|---|---|---|---|
| **标准件客户**(未来实例的部署/运营者) | 部署物 + onboarding | 拿到即用的知识助手:接语料、配品牌、上线问答 | 未开始(差距见 §5) |
| **潜在客户**(商务,当前为 CamThink 访客) | Widget,匿名 | 价格/采购/渠道咨询(`commercial`) | WooCommerce 灌库后检索作答(曾为拒答转销售) |
| **产品选型者** | Widget,匿名 | 功能/参数/规格/选型/方案(`product`) | 已上线 |
| **开发者/集成方** | Widget,匿名 | 故障排查/集成/代码/调试(`support`),可上传日志 | 已上线;附件图片分析未做(1b) |
| **业务/管理者** | Admin 业务概览 | 销售线索、场景应用、产品需求三大业务信号 | 已上线(信号靠 LLM 手动批跑提取) |
| **运营** | Admin 对话审查 | 单条对话质量诊断(全链路 trace) | 已上线 |
| **技术** | Admin 技术洞察/数据源/模型配置 | 系统健康、知识缺口、索引与 LLM 配置 | 已上线 |

**北极星指标(2026-08-28 D-5 拍板,分层双指标)**:

| 层 | 北极星 | 价值故事 |
|---|---|---|
| 产品层(标准件,面向科技公司客户) | **自助解决率**(技术问题被助手直接答掉、未占人工支持的比率) | "省支持人力"——可复用、与客户定位咬合 |
| 实例层(CamThink) | **有效线索数**(commercial 且非 off_topic 的真实咨询条数) | "发现潜在客户"——CamThink 特有(商城 + 销售团队) |

两线近期排序不由拍脑袋定,由实例数据裁决:业务概览的 commercial 咨询占比高 → 优先商业闭环(留资/sales 目录);占比低 → 优先质量地基(质量管道,同时服务产品层北极星)。

**外部生态**:ask-ai-eval skill(位于 `camthink/skills/ask-ai-eval/`)共享 trace 数据层做答案优化,数据存 `Knowledge/Think/ASK AI/optimize/`。对话审查页与它在同一数据底座上分工(admin 浏览/skill 命令行优化)。

## 3. 产品能力地图(截至 2026-08-28,全部已实现)

### 3.1 C 端问答(Widget)

- 嵌入式聊天组件(`widget.js`,IIFE 打包,`<script>` 嵌入任意站点);右下角悬浮按钮展开
- SSE 流式输出,Markdown 渲染(XSS 清洗 + DOMPurify 兜底),内联来源引用 + 类型标签(链接过协议+域白名单)
- 有限多轮(前端保留最近 5 轮,后端无状态)
- 👍/👎 反馈;首屏推荐问题
- 附件上传(Phase 1a):txt/log 文本日志,作为补充上下文注入生成;有附件绕过拒答门;30 天清理
- 免登录匿名;PII 脱敏入库
- Admin 全局内嵌同一聊天窗口(login + 登录后所有页面)——**当前唯一的 widget 集成点,定位是管理员测试环境**(三目标站点嵌入后降级为内部对比/回归环境);已独立 `channel="admin"`(`c8117f4`,2026-08-30 审查通过),测试对话与访客数据落库可区分

### 3.2 RAG 管线(问答质量核心)

```
mask_pii → BudgetLimiter 预扣 → 附件注入
→ 意图分类(LLM,4 类:commercial/product/support/off_topic;off_topic 拒答)
→ 查询改写(多轮重写 + 长文本提取)
→ 混合检索(BGE-m3 dense + BM25 hybrid;文件级 + 符号级 BM25 召回 → RRF 融合)
→ 重排(bge-reranker-v2-m3 + chunk_type 加权;commercial 意图 boost 桶)
→ 拒答门(rerank min_score,不足 3 条拒答;rerank 滤光降级用 fused top-N 防误拒)
→ LLM 生成(deepseek 流式,按意图分风格 prompt)
→ SSE 事件序列 sources → tokens → done → 落库 conversations + trace
```

可选增强:Pruner(LLM 上下文裁剪,按路由启用)、OverrideMatcher(人工答案覆盖,keyword/regex/semantic 前置匹配)。

### 3.3 知识接入与索引(数据面)

- **13 个数据源在同步**:10 个 GitHub 代码仓库(wiki/ne101/ne301/ne503×2/neomind×4/aitoolstack,统一 github connector:clone/fetch/reset + API SHA 感知,多分支)、2 个 filesystem(Knowledge 公开/内部)、1 个 WooCommerce 商城
- 分块:文档语义分块(标题/段落边界,chunk_type/doc_section/chunk_visibility 元数据)+ 代码 tree-sitter AST 函数级分块(symbol 元数据)
- channel_visibility 隔离:内部记录不出现在 widget 渠道
- 增量同步:cron 每小时 + admin 手动(单源/全部);增量窗口按上次成功时间推进(失败不推进)
- **向量一致性自愈**(2026-08-26~30 两轮迭代,代码已归一 origin/main):无变更源触发两级校验(汇总级 SUM 对比 → **chunk 级差集**),缺口文档自动补灌、部分 chunk 丢失经 `refill_source_ids` 自愈重灌,记 `partial`;灌入时**清理陈旧 chunk 与 Postgres 幽灵行**(一致性漂移根因);写库失败诚实上报不再吞成 success。已知残余:pg 同步降级(chunk_count 写成实际数)时汇总级恰等测不到,由 failed 状态不推进窗口兜底
- 索引完整性依赖:确定性 UUID 幂等 upsert;filesystem 源必须 mac 同步(T4 无 Knowledge 仓库)

### 3.4 管理后台(管理面,8 页 + Login)

侧边栏两组:

**运营组**(重做于 2026-08-07~17):
- **业务概览**:KPI + 三列意图卡(销售咨询/产品方案/技术支持,各含 Top3 热门问题 + mini-trend + 环比)、每日趋势、销售线索、场景应用、产品需求、地域分布
- **对话审查**:列表(4 色阶段条 + 置信度 + markers 圆点:重试/澄清/短路/降级 + 4 toggle 筛选)+ 详情(5 泳道 trace 全链路诊断)
- **技术洞察**:技术性能 tab(P50/P95 双段柱、阶段表双色条、异常包含图、降级链路)+ 知识缺口 tab(四态 miss_type 聚类、澄清漏斗位、缺口趋势);全页下钻跳对话审查

**配置组**:
- **数据源**:结构化表单(github repo_url+clone_path+分支多选 / filesystem 目录选择器 / woocommerce)、启停、同步触发、partial 黄标
- **对话接入**(Customization):多套 system prompt 配置按渠道绑定
- **模型配置**(LLM Providers):6 环节职责网格(向量/排序只读 + 意图/查询/剪枝/生成可配),chain 路由 `{provider, model}`、连通性测试、热重载、available_models 拉取;凭证 AES 加密
- **答案覆盖**:OverrideMatcher CRUD,对话审查详情"改进此答案"一键 prefill
- **用户管理**:RBAC(admin/editor/viewer)

### 3.5 可观测与分析(智能面)

- **trace 数据层**:1 conversation : N trace,每轮一个(rag/clarify/reject_short 三型),stages jsonb 记 6 阶段耗时与细节、config_snapshot 留档
- **业务信号 pipeline**:LLM 批跑提取场景应用 + 产品需求标签 → BusinessSignal 表(admin 手动触发,不进 cron)
- **分析聚合**:Coverage Gaps、Top Questions、Source Analytics、聚类(K-Means gap/top 双模式)

### 3.6 平台与部署

- 生产:tesla-t4(GPU T4,纯 CI 镜像 `ghcr.io/harryhua-ai/ask-ai`,backend :18000 + sync + sync-cron),公网入口 wiki-data.camthink.ai
- 开发:mac 本地 CPU(`dev-local.sh` 秒级热更新)+ 数据从 T4 回同步
- CI:GitHub Actions(test → 前端构建 → GPU 镜像 → GHCR)
- Postgres 15 张表;Weaviate 单 collection(hybrid + symbol property)
- 安全:JWT/bcrypt/Fernet、成本熔断(请求+token 双阈值)、限流、prod 密钥强校验

## 4. 产品原则与不变量(红线,跨阶段不可破坏)

1. **拒答优先于编造**:无依据不回答(双层拒答:off_topic 检索前 + rerank 阈值检索后);拒答入统计供缺口分析
2. **数据自主**:全部语料/向量/对话数据在自有基础设施,不训练公开模型
3. **匿名与隐私**:不收集身份信息,PII 入库前脱敏,日志保留期待定(spec 默认 90 天)
4. **安全铁律**(spec §13.2):secret 不进 LLM 上下文;LLM 输出与知识库 chunk 均不视为可信内容;未来工具调用须最小权限 + 危险动作人工确认
5. **运营红线**(工程):`--reindex` 删全量 collection 非单源;测试必设 `TEST_DATABASE_URL`;生产纯镜像禁源码挂载

## 5. 通用化差距分析(标准件视角)

> 2026-08-28 基于代码审计:后端+配置 12 个文件、32 处 "camthink" 硬编码;前端 6 个文件。以下按改动深度分级,**分层结论:架构骨架已是标准件形态,差距集中在业务语义层,最深单点是意图体系**。

### 5.1 已具备的标准件素质(不需返工)

| 素质 | 现状证据 |
|---|---|
| 插件化扩展 | Connector / LLMProvider 双注册表,`@Registry.register` 装饰器,新增类型零改管线 |
| 配置数据化 | 数据源 / Customization / LLM 路由全部在 Postgres + admin UI 维护,换实例不改代码;`config/*.yaml` 首次启动 seed,即实例引导配置雏形 |
| 多渠道预留 | `channel` 字段自 Phase 1 贯穿数据模型与 Customization 绑定体系 |
| 部署物化 | 单 Docker 镜像 + compose 三套(dev/local/prod),CI 产出,健康检查 + 滚动更新脚本 |
| 安全与治理基座 | RBAC、API key AES 加密、预算熔断、限流、PII 脱敏、prod 密钥强校验 |
| 问答质量机制 | 拒答门、rerank 加权、override 人工覆盖、一致性自愈——机制与业务无关,通用 |

### 5.2 耦合点分级清单

**L1 浅层(配置/文案,不动架构,换 seed 即可)**:

| 耦合点 | 位置 | 通用化动作 |
|---|---|---|
| 助手人设/风格 | `config/system_prompt.yaml`("CamThink 助手" + 场景识别规则) | 已在 Customization 体系,换实例 seed 即换;仅需出"实例品牌配置清单" |
| intent_styles 三段商务/产品/支持风格 | 同上 | 同上 |
| Widget 品牌(标题 "Ask Camthink.ai"、主色、来源标签) | `widget/src/*`、`urlPolicy.ts` 域白名单(camthink/github) | 配置化白名单 + 品牌参数(data-* 传入) |
| admin 产品线中文文案 | `DataSources.tsx` 等 | 随 `product` 维度配置化一并解决 |

**L2 中层(数据模型/业务逻辑,需设计但不伤架构)**:

| 耦合点 | 位置 | 通用化动作 |
|---|---|---|
| `product` 产品线维度 | `RawDocument.product`(ne101/ne301/…)、DB、admin 表单 | 从枚举改为租户自定义 taxonomy(自定义维度/标签体系);schema 已是字符串,迁移成本低 |
| 业务信号分析域 | `business_signals.py` prompt("你是 CamThink 业务分析师" + 工业视觉/安防等场景示例硬编码) | 分析域(场景词表/需求词表)配置化,入 Customization 或独立实例配置 |
| 连接器域默认值 | `github.py`(camthink-ai org 假设)、`woocommerce.py`(camthink.ai) | 去默认值,全部显式配置(部分已是) |
| 业务概览页语义 | 意图标签中文映射、三列卡假设"销售/产品/支持"业务 | 跟随意图体系配置化(见 L3-1) |

**L3 深层(产品架构层,标准件化必经)**:

| 耦合点 | 现状 | 通用化动作 |
|---|---|---|
| **意图体系** | `intent.py` 的 `_INTENT_PROMPT` 硬编码 4 分类 + CamThink few-shot 示例(NE301/NE101);分类结果联动路由行为(commercial boost 桶、off_topic 拒答、阈值放行)散落 rag.py | **最大单点**:意图体系(类别定义 + 示例 + 每类的路由/阈值行为)提为实例配置;代码消费配置而非硬编码 |
| **入口层(渠道适配器 + 集成方体验)** | 仅 Widget 一个前台;`ChannelAdapter` Protocol 仅 spec 纸面预留(§12.2);`/api/ask` 无机器认证(widget 匿名 / admin JWT 人认证,无 API key 集成方模型)、限流 per-IP、预算熔断为全局内存计数(单 worker,未按集成方/渠道分账) | 渠道适配器框架落地(每渠道一个 Adapter);对外 API 认证体系(API key + 按集成方配额/预算);对接文档与示例 |
| **多租户** | 单租户 | 若 SaaS 形态:tenant 维度贯穿全部 15 张表 + 隔离;若私有部署形态:不需要多租户,但需实例引导(onboarding 向导) |
| **schema 迁移** | 无 Alembic,靠 `create_all` + 手写 migrate 脚本(migrate_*.py 已 7 个) | 标准件交付硬伤:多实例版本升级必须有版本化迁移体系;越晚引入,实例越多越痛 |
| **国际化** | admin UI / 注释 / 文档全中文,widget 文案英文 | 目标市场含海外则 admin i18n |
| **部署门槛** | 本地 GPU embed/rerank 是"数据自主"卖点也是门槛(T4 16GB) | 提供 CPU/远程 embedding API 档位(`EMBEDDER_DEVICE=cpu` 已可用,性能档位未标定) |
| **第三方文档** | CLAUDE.md 面向内部开发 | 面向部署者的 install/onboarding 文档不存在 |

### 5.3 通用化路径建议(供讨论)

**"边用边抽"而非"先抽象后推广"**:CamThink 实例继续产生真实需求(质量闭环、商业闭环),通用化工作由"第二个实例的真实需求"牵引,避免过早抽象。但有三项无论产品形态如何都该早做,因为它们随时间变贵:

1. **Alembic 版本化迁移**(L3,纯工程,收益确定)
2. **意图体系配置化**(L3 最大单点,且 CamThink 自身也会受益——调意图不再改代码)
3. **CamThink 常量出仓**:L1+L2 的硬编码收敛到实例配置层(seed/Customization),让"产品代码 ≠ CamThink 实例"边界清晰可见

## 6. 路线图

### 6.1 原始四阶段规划(2026-07-27 founding spec)

| 阶段 | 主题 | 内容 |
|---|---|---|
| Phase 1 | 核心问答 | RAG 管线 + Widget + 同步框架 + 匿名统计 |
| Phase 2 | 管理后台 | 数据源/同步监控/Customization/LLM 管理/对话审查/RBAC + 语义分块与 channel 隔离 |
| Phase 3 | 分析与优化 | Coverage Gaps / Top Questions / Source Analytics / Improve This Answer / 报表推送 / 剪枝 |
| Phase 4 | 智能管理 | Platform Assistant / Skills / 多渠道(Discord+WhatsApp)/ MCP Server |

### 6.2 实际演进(2026-07-27 → 2026-08-28,约 4.5 周)

实际执行大量超前与插队,原始 Phase 1-3 的内容**已全部落地**(含超前项),Phase 4 未启动:

| 时段 | 交付 | 对应规划 |
|---|---|---|
| 7-28 ~ 8-初 | 脚手架 → 核心管线 → Widget → 安全加固 → **Phase 1 核心问答上线** | Phase 1 ✅ |
| 8-初(超前) | 意图 4 分类、语义分块、channel_visibility 隔离、chunk 元数据加权 | Phase 1.5(超前) |
| 8-初 ~ 8-05 | **Phase 2B 管理后台全量**(用户/数据源/同步日志/Customization/LLM 供应商/对话审查+意图标注/生产托管)+ Phase 2A 索引优化 | Phase 2 ✅ |
| 7-31 ~ 8-03(专题) | 代码库索引:多分支、tree-sitter AST 分块、**符号检索 + RRF 融合**、GPU 并行索引(8h→50min)、local_git 真增量、目录选择器 | Phase 3+ 超前项 ✅ |
| 8-04 ~ 8-05 | 意图路由迁移、**WooCommerce connector**(commercial 数据源)、GPU Docker + CI 镜像、**附件分析 Phase 1a**(日志)、GitHub 源统一(clone/fetch/reset + SHA 感知,local_git 降为实现细节) | 计划外插入 ✅ |
| 8-05 ~ 8-10 | **LLM 模型配置系统重设计**(6 环节网格、chain {provider,model}、热重载、凭证加密) | 计划外插入 ✅ |
| 8-07 ~ 8-11 | **对话可观测体系**:trace 数据层、运营三页重做(业务概览/对话审查/技术洞察)、业务信号 pipeline | Phase 3 主体 ✅ |
| 8-11 ~ 8-17 | **admin 设计稿对齐 P1+P2**:可视化组件库(viz/)、三页功能补全、Real-Run Gate + Playwright E2E 验证 | 计划外插入 ✅ |
| 8-17 | tesla-t4 overlay2 事故,恢复预案就绪(待窗口执行) | 运维 |
| 8-18 ~ 8-28 | 同步可靠性:增量窗口按成功推进、写失败诚实上报、**向量一致性校验 + 缺口自愈(partial)** | 计划外插入 ✅ |
| 8-28 ~ 8-30 | **一致性增强二轮(chunk 级差集 + 自愈重灌 + 陈旧 chunk/幽灵行清理)+ admin channel 数据隔离 + 环境策略固化**:两轮执行 + 产品窗口审查;分支内容经 08-30 梳理确认已归一 origin/main(上一轮窗口 08-28"补齐漏推"所致),差 D-11 部署验收 | 计划外插入 ✅(D-11 待) |

> 注:"admin 设计稿对齐 P1/P2/P3" 是该专题内部编号,与 founding spec 的 Phase 1-4 是两套体系,勿混。

### 6.3 未来候选池(待排优先级)

**A. 已立项未收尾**:
1. ~~sync-consistency~~ **✅ 已收口(2026-08-30 D-11)**:代码全归一 main(`88a4c9f`)+ 部署验收通过——自愈循环幂等(两轮 SyncLog 逐字节一致)、幽灵清理闭环实证(knowledge 5 行 pg 遗留清除后 partial→success 481/481)、prune 零误触发。残留为**数据侧**(非代码),分列下条
1b. **数据侧残留(2026-08-30 终态,A1 全线收官)**:① P1 修复 `5ca3dfe` ② D4 记账修复 + 校验器口径统一 `ce59b15`/`fe98ca2` ③ 615 孤儿已清(D4-ACC Task3,5/5 源迭代器口径一致)——**全部 push origin(main=fe98ca2),CI run 33311417157**;④ 功能盲区(消失文档)留候选池。**剩余:一次性发布(部署动作,T1a 前)+ 发布后观察三项**(ne503 自愈收敛 / 五源 partial→success 翻转 / admin 聊天恢复)
2. tesla-t4 Docker 恢复预案执行(14 容器,数据零丢失,需停机窗口 + owners 确认;任何 T4 部署前查磁盘余量)

**B. 已设计待评审**(admin 对齐 Phase 3,spec 评审建议"不急做,按实际使用价值砍"):
1. 客户信息模型 + widget 对话后留资表单(`conversation_contacts` 表,规则版线索标记)— **产品决策项**,通向商业闭环
2. Trace 采集层修复(degraded/retry_count/error_flags 真实落库,废弃推断)— 评审认为必做基础项
3. 多轮消息正文存储(`conversation_turns` 新表)— 评审推荐
4. 来源准确率 eval 管道(每日抽样 100 条,复用 ask-ai-eval 判定)
5. 澄清漏斗(依赖 2;占比 >10% 才做)

**C. 既有 spec 规划未启动**:
1. 附件 Phase 1b:图片 vision 分析(模型层已预留 kind="image")
2. sales 目录接入(commercial 的价格/渠道/促销资料,Knowledge/sales)→ 补齐 `commercial` 意图的资料底座
3. 报表推送(Email/Slack 定期)
4. 答案缓存(Postgres + TTL,流量上来后)
5. 备用 LLM 供应商(deepseek 单点风险;框架已就绪,只需加 provider)
6. Weaviate 生产鉴权(spec 提及,现状待确认)
7. Task #25(挂起):数据源健康度归属与内容审查(归属已拍板 D-9 拆分,待执行)
8. **官网爬取数据源**(2026-08-30 立项,产品负责人需求):新增 `web_crawl` connector 类型(founding spec §6 预留),首实例 `website-camthink`(www.camthink.ai)。Inspect 已核:官网 SSR/SSG 纯 HTTP 可抓、标准 sitemap 索引(post/page/product 三子表,lastmod 增量天然支持);设计要点:HTML→Markdown 清洗(剥模板噪音,工作量重头)、**排除 `/store/`**(woocommerce-mall 已覆盖防重复)、language=en、product 维度整站标 `website`(contract 起草时核 schema 约束)。**额外价值:官网含 NG4500(Jetson 边缘盒)而现有 github 源无此产品,补知识覆盖盲区**。排序:与 widget 上线准备并行开发,wiki 灰度不依赖它,**官网页嵌入 widget 前必须就绪**(访客在官网问官网内容需有源可答);contract 在 P1-RES Review 后起草(起草前 Inspect:三子 sitemap 页面量、代表性页面 HTML 结构定清洗规则、product 字段值域)
9. **filesystem 数据源上传文件夹**(2026-08-30 立项,拍板"按建议";同日修正:文件数限制移除):filesystem 源新增"内容来源"两模式——服务器路径(现状保留)+ **上传文件夹**(浏览器 webkitdirectory 递归直传,保留目录结构,落盘 `data/uploads/data-sources/<source_id>/`,root_path 自动指向,**connector 零改动**);再次上传=**合并覆盖**(配合 mtime 增量零额外开发);护栏:file_types 白名单沿用(默认 .md/.txt)+ 单文件 ≤20MB,**无文件数限制**(前端自动分批上传,工程护栏对用户不可见);不做 zip 解压(防炸弹/路径穿越复杂度)。**价值:缓解 filesystem 源 mac-only 痛点(T4 可有 filesystem 语料)+ 标准件 onboarding 必备**(第二用户无服务器路径概念)。实现需新 admin 上传端点(持久语料,区别于聊天附件体系 30 天清理)。**排期:D4-ACC 后与 C8 同窗口,合入 T1a 前最后发布**
10. **github 源可诊断性与表单缺陷**(2026-08-30 立项,bug 驱动;根因定版=**表单对无 main 分支的仓库自动带入 main**:`DataSources.tsx:68` 新建默认值硬编码 `"main"` + `:227` 编辑回填兜底 `|| "main"` + 勾选追加式,预览列表无 main 项故用户不可见——有 main 的仓库默认值侥幸正确从未暴露,无 main 仓库(lowpower_camera,分支仅 flash_8M/hw-v1.2/hw-v2.0)必炸 clone exit 128;叠加 ③错误只报 exit code 丢 stderr 根因 ④错误明文泄漏 GITHUB_TOKEN)。修法:**① token 脱敏**(CalledProcessError 处理,安全优先)② 异常带 stderr 摘要(脱敏后,直接可读"Remote branch not found")③ 表单默认值跟随仓库真实默认分支(不写死 main;preview-branches API 需返回 default_branch,无则补)+ 两处硬编码清除 ④ 创建/同步前校验 branches ⊆ 远端分支列表 ⑤ 同 repo 双源 clone_path 冲突检测(clone_path 默认 `~/ask-ai-corpus/<repo>`,同仓库两源互相 reset 覆盖)。**排 C8/C9 同窗口**

**D. 入口层扩展**(v3 核心定位主线;2026-08-28 D-3 拍板后重排,web 插件优先):
1. **T1a 实例最小上线包(上线里程碑,2026-08-30 拆分拍板)**:widget.js 由 backend 托管(仿 admin StaticFiles)+ Dockerfile 带 widget/dist + CORS 白名单加三域名(纯 env 配置)+ P-1 存量清洗(已拍板 cutoff 执行)+ 三站点嵌入。**灰度顺序(已拍板):wiki → 官网 → 商城**(风险递进,商城价值最高放最后;北极星观察期自 wiki 灰度日启动)。Inspect 已核:widget 配置接口已标准化(`data-api-url`/`data-language`/`data-primary-color`,`widget/src/index.tsx:22-26`),唯一代码缺口是 widget 托管(一天级)。**官网波次前置:C8 官网爬取源就绪**(访客在官网问官网内容需有源可答)。前置检查项(均完成/已拍板):① admin 聊天独立 `channel="admin"`(`c8117f4` 审查通过);② P-1 存量清洗(pg_dump 备份后 DELETE 627 条)
2. **T1b 标准件分发(产品线,与 T1a 并行或后置)**:品牌/文案/主题全套配置化、分发文档、多站点嵌入指南与示例、分发域名策略——服务"第二个用户",**不挡实例上线**
2. (预留)渠道适配器框架:`ChannelAdapter` Protocol 从 spec 纸面变为代码框架——等第一个非 web 入口需求启动
3. (预留)集成方 API 认证:API key + 按集成方配额/预算——等第一个系统级 HEADLESS 对接需求启动(D-4 随之决策)
4. (后续逐步)MCP Server / Discord / WhatsApp 入口
5. Platform Assistant(对话式管理)、Skills 工作流。⚠️ 工具调用使 prompt injection 升级为指令执行,威胁模型需重做

**E. 通用化/标准件化**(v2 新增,差距全景见 §5;D-1 拍板 (c) 后范围收敛):
1. CamThink 常量出仓(§5.3-3):L1/L2 硬编码收敛到实例配置层
2. 意图体系配置化(§5.3-2,最大单点;按科技公司典型意图体系设计默认档)
3. Alembic 版本化迁移(§5.3-1;私有部署多实例升级后**从"建议"升为"必须"**)
4. 实例 onboarding:引导向导 + 部署者文档 + 品牌配置清单 + licensing 机制(技术 license 校验 + 法律授权条款,D-1 要求)

**建议优先级框架**(供讨论,非决定;已按 D-1/D-2/D-3 拍板调整):
- **T0 收尾**:A1 + A2(把已投入的工作变成生产价值)
- **T1 上线里程碑(2026-08-30 拆分拍板)**:**T1a 实例最小上线包**(widget 托管 + CORS + P-1 清洗 + 三站点灰度嵌入 **wiki→官网→商城**,官网波次需 C8 官网源就绪)= 实例线上线;**T1b 标准件分发**(品牌配置化/文档)= 产品线,并行或后置,不挡上线。北极星观察期自 wiki 灰度日启动
- **T2/T3 商业闭环 vs 质量地基**(排序由实例数据裁决,2026-08-28 D-5 定):业务概览 commercial 咨询占比高 → 先 B1(留资)+ C2(sales 目录)(推实例层线索数);占比低 → 先 B2(trace 真实化)+ B4(eval 管道)+ B3(推产品层自助解决率)。观察期:T1 落地后积累 2-4 周意图分布数据再裁
- **T4 通用化起步**:E3(Alembic,私有部署形态下必做)→ E1(常量出仓)→ E2(意图配置化)→ E4(onboarding + licensing)
- **T5 按需/预留**:B5、C1(1b)、C3~C7、D2-D5 入口扩展、D4 Platform Assistant(由真实对接需求牵引);低优工程清单:ruff 存量 12 处、schemas 与 CLAUDE.md 若干文档不一致

## 7. 当前实现阶段快照(2026-08-28)

**总体判断:产品处于「预上线(内部验证)」阶段——后端与数据面在生产稳定运行,但 C 端流量入口尚未嵌入任何公开站点,真实访客数据为零。** 原始 Phase 1-3 全部落地,当前唯一 widget 集成点是 admin 登录页 + 登录后页面(管理员测试用);**T1 三站点嵌入(商城/官网/wiki)是产品真正上线运营的里程碑**,北极星数据观察期(dual 指标裁决)自 T1 落地后起算。中台定位下,入口层 HEADLESS 半开放、资源层插件化已就绪。下一阶段三线:T1 上线里程碑(实例线+产品线共同入口)→ 通用化剥离(E 类)→ 数据裁决后的商业闭环/质量地基(T2/T3)。

| 维度 | 状态 |
|---|---|
| 生产运行 | 后端/数据面在 tesla-t4 生产运行(入口 wiki-data.camthink.ai);**公开站点零嵌入,真实访客流量为零**(唯一集成:admin 登录页 + 登录后页面,管理员测试用) |
| 通用化程度 | 架构层达标(插件/配置化/部署物);业务语义层 12 后端文件 + 6 前端文件 CamThink 硬编码,意图体系为最深单点(§5) |
| 代码(2026-08-30 收敛完成) | main 历史已重写 + **文档全部转仅本地**(`4651ca8`,GitHub 只留代码);**收敛完成:main = origin/main = `88a4c9f`**,分叉消除(旧 SHA 81bd1db/be93264 作废 → c8117f4/88a4c9f);分支已退役,backup/sync-consistency-pre-rebase 留至 D-11 后;规划文档(含本篇、CLAUDE.md)为本地 untracked,执行端经绝对路径读取;CLAUDE.md 已固化环境策略 |
| 已完成未验收 | **全部代码就绪待发布**:main = `76d75e7` = origin(P1 `5ca3dfe` + D4-ACC `ce59b15`/`fe98ca2` + WEB-DATA-WIN `309c1f5`..`76d75e7` 三契约);CI 33321125298;worktree 清零。**剩余:一次性发布(REL-WIN 契约)+ 发布后观察三项 → T1a** |
| 数据规模 | 13 源在同步(T4 现 5 success / 9 partial,残留均为数据侧根因);知识源幽灵清理闭环 481/481;曾误删 560k chunk 事故后重建 |
| 测试 | 后端 pytest(本地全量 **499 passed + 3 skipped**,排除 embedder/e2e 与 CI 同口径;embedder 无外网沙箱会因 BGE 下载挂起,缓存有模型后不卡)+ 前端 vitest(admin 88)+ Playwright E2E 三页;ruff 存量 12 处(I001×10/BLE001/SIM103,低优清单) |
| 已知风险 | T4 磁盘曾 91-96%(事故根因);GPU 显存与 3 服务共享(sync embed 偶发 OOM);dev 库稀疏导致三页真实数据视觉验证欠账 |
| 遗留挂起 | Task #25(数据源健康度;归属已拍板 D-9 拆分,待执行);TraceLanes 集成对话详情(deferred) |

## 8. 关键产品决策记录(已锁定,影响后续)

| 决策 | 选择 | 时间/出处 |
|---|---|---|
| **产品主定位** | **RAG 知识助手中台服务:多入口对接 + 可插拔数据源/LLM**;CamThink 是第一个用户(三层架构见 §1) | 2026-08-28,产品负责人(v2 标准件 → v3 精化中台) |
| **产品形态(D-1)** | **(c) 私有部署商业授权**:单实例交付,不做 SaaS 多租户改造;需配套 licensing(技术 + 法律)、onboarding、版本化迁移 | 2026-08-28 拍板 |
| **目标客户(D-2)** | **科技公司为主**——代码索引、开发者支持能力面为核心卖点;意图配置化/onboarding 按科技公司典型场景设计 | 2026-08-28 拍板 |
| **入口层路线(D-3)** | **先完成标准 web 插件**:widget 做成一行脚本可嵌入任意站点(官网/wiki/商城等)的标准插件;MCP/Discord/WhatsApp/HEADLESS API 等集成手段预留,后面逐步实现 | 2026-08-28 拍板 |
| **北极星指标(D-5)** | **分层双指标**:产品层 = 自助解决率(面向科技公司客户的价值主张);实例层 = 有效线索数(CamThink)。两线近期排序由 commercial 咨询占比数据裁决 | 2026-08-28 拍板 |
| **信号提取机制(D-7)** | cron 低峰定期(每日/每周),业务概览数据不再依赖 admin 手动触发 | 2026-08-28 拍板 |
| **日志保留期(D-8)** | 90 天(隐私承诺口径;后续清理任务按此参数化) | 2026-08-28 拍板 |
| **数据源健康度归属(D-9)** | 拆分:接入健康(同步/一致性)归数据源页;来源质量归因归技术洞察(配合 eval 管道) | 2026-08-28 拍板 |
| **widget 嵌入目标(D-10)** | 官网 `www.camthink.ai` + wiki `wiki.camthink.ai/docs/` + 商城 `www.camthink.ai/store/` | 2026-08-28 确认(当前实际嵌入与分发现状待盘点) |
| **存量对话清洗(P-1)** | T1 上线时 cutoff:先 pg_dump 备份(conversations + 级联 traces/source_clicks),再 DELETE 全部 627 条混用 channel 对话,数据池从零积累(保北极星干净) | 2026-08-30 拍板 |
| **环境策略(测试/生产分工)** | mac local = 开发/调试/后端测试;CI = 单元/集成回归;tesla-t4 prod = 生产运行 + 部署验收(对运行中服务真实验证,补 Real-Run Gate 缺陷);dev 模式 = 前端联调临时便利,**不作后端测试环境**。现阶段不建 staging,mac local 即 staging | 2026-08-28 拍板;2026-08-30 已固化至 CLAUDE.md + deploy/README.md(执行审查通过) |
| **窗口协作模式** | 规划/质量审查窗口在主工作区(main)维护文档;执行窗口在独立 worktree 分支(`worktree-exec/*`)实施,逐 Task commit,完成后合回 main 交规划窗口审查 diff。交接文档须先提交到 main 再开 worktree(worktree 看不到主工作区未提交文件) | 2026-08-28 拍板 |
| 自建 vs SaaS(实例层) | 自建(数据自主 → 升级为标准件核心卖点) | founding spec |
| 意图体系 | 4 类:commercial/product/support/off_topic(售前并入 product 后 commercial 独立) | 2026-08-03 校准 |
| commercial 意图 | WooCommerce 灌库后从"拒答转销售"改为检索作答 | bc6bc9b |
| 代码源接入 | github 统一类型(clone/fetch/reset),local_git 降为实现细节,多分支 | 2026-08-04~05 |
| LLM 供应商类型 | 仅 openai_compatible 一种(不新增 provider 类),chain 粒度 {provider, model} | 2026-08-05 重设计 |
| 运营三页划分 | 按使用者目的分页(业务概览/对话审查/技术洞察)而非技术维度 | 2026-08-07 |
| admin 视觉 | B 方案:功能对齐设计稿,视觉合理偏差,不引第三方图表库 | 2026-08-11 |
| 部署模式 | 生产纯 CI 镜像(禁源码挂载),mac 本地源码热更 | 2026-08-10(事故后固化) |

## 9. 待拍板决策清单(2026-08-28 汇总,含此前累积)

> "建议"列为规划视角的倾向性意见,供决策参考;拍板后移入 §8 决策记录。

### 9.1 产品战略层(决定 roadmap 走向)

| # | 决策 | 状态 |
|---|---|---|
| D-1 | 产品形态 → **(c) 私有部署商业授权** | ✅ 2026-08-28 拍板(§8) |
| D-2 | 目标客户 → **科技公司为主** | ✅ 2026-08-28 拍板(§8) |
| D-3 | 入口层路线 → **标准 web 插件优先**(集成到网站/wiki/商城等页面),其他集成手段(MCP/Discord/WhatsApp/HEADLESS)预留,后面逐步实现 | ✅ 2026-08-28 拍板(§8) |
| D-4 | 集成方模型(API key 粒度、预算分账) | ✅ 2026-08-28 拍板:**现在不定**,等第一个系统级对接需求出现再决策(§6.3-D3 已预留位) |
| D-5 | 北极星指标 → **分层双指标**(产品层自助解决率 / 实例层有效线索数),近期排序由 commercial 占比数据裁决 | ✅ 2026-08-28 拍板(§8) |

### 9.2 实例运营层(CamThink 实例)

| # | 决策 | 状态 |
|---|---|---|
| D-6 | admin Phase 3 取舍(重点 B1 留资) | 🔵 不单独拍:由 commercial 占比数据 + 三页实际使用情况牵引(与 §6.3 T2/T3 裁决同步) |
| D-7 | 场景/需求信号提取 → cron 低峰定期 | ✅ 2026-08-28 拍板(§8) |
| D-8 | 日志保留期 → 90 天 | ✅ 2026-08-28 拍板(§8) |
| D-9 | 数据源健康度归属 → 拆分(接入健康归数据源页 / 来源质量归因归技术洞察) | ✅ 2026-08-28 拍板(§8);Task #25 按此执行 |
| D-10 | widget 嵌入目标:官网 `www.camthink.ai` + wiki `wiki.camthink.ai/docs/` + 商城 `www.camthink.ai/store/` | ✅ 现状已补全(2026-08-28):**三个目标站点均未嵌入**;当前唯一 widget 集成点是 admin 登录页 + 登录后页面(管理员测试用);生产分发方式未落地。T1 对三站点均为"从零接入" |

### 9.3 运维执行层(需触发/窗口确认)

| # | 事项 | 内容 | 前置 |
|---|---|---|---|
| D-11 | sync-consistency 收尾 | **Review 判定 PARTIAL,任务关闭(08-30)**:部署 88a4c9f + 机制验收全过(自愈幂等/清理闭环/prune 零误触发);验收 c 字面未全绿(9 partial=数据侧遗留)不降 contract,分流 §6.3-A1b;Review artifact `docs/engineering/reviews/d11-...-review.md` | — |
| D-12 | tesla-t4 恢复预案执行 | 停机窗口(60-90 分钟)+ 5 方 owners 确认 | 预案已就绪;**任何 T4 部署前查磁盘**(08-30 实测 77% 余量健康) |

**建议决策顺序**:D-1 → D-3 → D-5(分别解锁产品线、入口线、实例线的最大不确定);D-11/D-12 随时可插队执行。

---

*本文件由产品规划窗口于 2026-08-28 建立基线(同日 v2 定位升级);§3 能力地图与 §7 快照应随大版本演进更新。*
