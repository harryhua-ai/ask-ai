# ask-ai PRODUCT ROADMAP

> **性质**:活文档 — 阶段规划、候选池、优先级框架、决策记录与待拍板清单。
> **沿革**:由原 `docs/product-roadmap.md`(v3)拆分而来(D-14 拍板,2026-08-31);定位与原则见 `PRODUCT_VISION.md`,现状快照见 `PRODUCT_STATE.md`。
> **维护约定**:产品事实变化时更新对应小节;重大 FINAL PASS 后同步 PRODUCT_STATE。

---

## 0. 速览(NOW / NEXT / LATER)

- **NOW**:**T1a 契约已签发(AUTHORIZED,docs 仓 476a204)**——Phase 1 执行提示词已给,等执行端交付 CANDIDATE READY
- **NEXT**:Phase 1 Review → push → Phase 2/3(T4 发布 + P-1 清洗)→ Phase 4 wiki 灰度(上线时刻用户确认)→ week-1 基线报告
- **LATER**:官网 → 商城波次 → T2/T3(commercial 占比数据裁决)→ T4 通用化 → T1b 标准件分发;灰度阈值冻结(week 2+,用户批)
- **CONTINUOUS**:候选池维护、D-12 恢复预案待窗口、数据侧用户持有项跟进

## 1. 原始四阶段规划(2026-07-27 founding spec)

| 阶段 | 主题 | 内容 |
|---|---|---|
| Phase 1 | 核心问答 | RAG 管线 + Widget + 同步框架 + 匿名统计 |
| Phase 2 | 管理后台 | 数据源/同步监控/Customization/LLM 管理/对话审查/RBAC + 语义分块与 channel 隔离 |
| Phase 3 | 分析与优化 | Coverage Gaps / Top Questions / Source Analytics / Improve This Answer / 报表推送 / 剪枝 |
| Phase 4 | 智能管理 | Platform Assistant / Skills / 多渠道 / MCP Server |

## 2. 实际演进(2026-07-27 → 2026-08-31)

实际执行大量超前与插队,原始 Phase 1-3 内容**已全部落地**,Phase 4 未启动:

| 时段 | 交付 | 对应规划 |
|---|---|---|
| 7-28 ~ 8-初 | 脚手架 → 核心管线 → Widget → 安全加固 → **核心问答上线** | Phase 1 ✅ |
| 8-初(超前) | 意图 4 分类、语义分块、channel_visibility 隔离、chunk 元数据加权 | Phase 1.5 ✅ |
| 8-初 ~ 8-05 | **管理后台全量** + 索引优化 | Phase 2 ✅ |
| 7-31 ~ 8-03(专题) | 代码库索引:多分支、tree-sitter AST 分块、**符号检索 + RRF 融合**、GPU 并行索引(8h→50min)、local_git 真增量、目录选择器 | Phase 3+ 超前 ✅ |
| 8-04 ~ 8-05 | 意图路由迁移、**WooCommerce connector**、GPU Docker + CI 镜像、**附件 Phase 1a**、GitHub 源统一 | 计划外 ✅ |
| 8-05 ~ 8-10 | **LLM 模型配置系统重设计**(6 环节网格、热重载、凭证加密) | 计划外 ✅ |
| 8-07 ~ 8-11 | **对话可观测体系**:trace 数据层、运营三页重做、业务信号 pipeline | Phase 3 主体 ✅ |
| 8-11 ~ 8-17 | **admin 设计稿对齐 P1+P2**:viz 组件库、Real-Run Gate + Playwright E2E | 计划外 ✅ |
| 8-17 | tesla-t4 overlay2 事故,恢复预案就绪(待窗口执行) | 运维 |
| 8-18 ~ 8-28 | 同步可靠性:增量窗口、诚实上报、**一致性校验 + 自愈** | 计划外 ✅ |
| 8-28 ~ 8-30 | **一致性二轮(chunk 级 + prune + 幽灵清理)+ admin channel 隔离 + 环境策略固化**;D-11 部署验收 | 计划外 ✅ |
| 8-30 | **WEB-DATA-WIN**(C10 表单健壮+脱敏 / C9 上传文件夹 / C8 官网爬取)+ **REL-WIN 发布**:生产 76d75e7,15/15 源全绿,admin 聊天恢复 | 上线就绪 ✅ |
| 8-31 | **C9-UPLOAD-FIX 三波加固**(创建流/编辑流/默认全选,FINAL PASS + 推送收口,main=4db4c41);**DUAL_AGENT_PROTOCOL v2.0 生效**;产品文档三件套(D-14) | 质量加固 ✅ |

> 注:"admin 设计稿对齐 P1/P2/P3" 是该专题内部编号,与 founding spec 的 Phase 1-4 是两套体系,勿混。

## 3. 候选池(待排优先级)

**A. 已立项未收尾**:
1. ~~sync-consistency~~ **✅ 已收口(2026-08-30 D-11;数据侧残留同日 A1 全线收官)**;功能盲区(消失文档)留候选池
2. tesla-t4 Docker 恢复预案执行(=D-12,待停机窗口;任何 T4 部署前查磁盘)

**B. 已设计待评审**(admin 对齐 Phase 3,spec 评审建议"不急做,按实际使用价值砍"):
1. 客户信息模型 + widget 留资表单(`conversation_contacts`)— **产品决策项**,通向商业闭环
2. Trace 采集层修复(degraded/retry_count/error_flags 真实落库)— 评审认为必做基础项
3. 多轮消息正文存储(`conversation_turns` 新表)
4. 来源准确率 eval 管道(每日抽样 100 条,复用 ask-ai-eval)
5. 澄清漏斗(依赖 2;占比 >10% 才做)

**C. 既有 spec 规划未启动**:
1. 附件 Phase 1b:图片 vision 分析(模型层已预留 kind="image")
2. sales 目录接入(commercial 资料底座,Knowledge/sales)
3. 报表推送(Email/Slack)
4. 答案缓存(Postgres + TTL,流量上来后)
5. 备用 LLM 供应商(deepseek 单点;框架就绪只需加 provider)
6. Weaviate 生产鉴权(现状待确认)
7. Task #25(挂起):数据源健康度归属与内容审查(D-9 已拍板拆分,待执行)
8. ~~官网爬取数据源~~ **✅ 已交付(C8,website-camthink 116 篇,NG4500 盲区解除)**
9. ~~filesystem 上传文件夹~~ **✅ 已交付(C9 + C9-UPLOAD-FIX 三波加固:创建/编辑/合并覆盖/默认全选/回滚,全链 FINAL PASS)**
10. ~~github 源可诊断性与表单缺陷~~ **✅ 已交付(C10:token 脱敏/stderr 摘要/default_branch 跟随/分支校验/双源冲突检测)**
11. **上传源磁盘生命周期收尾**(2026-08-31 立项,bug 驱动;**D-13 已拍板清盘**):① 上传端点校验前建目录,失败后残留目录 → 延后建目录或失败清理;② 删 upload_mode 源连带清理 `data/uploads/data-sources/<id>/`(UI 确认文案注明;服务器路径模式永不碰盘)。量级小(L2),**不挡 T1a,搭下一次发布**

**D. 入口层扩展**(v3 核心定位主线;D-3 拍板 web 插件优先):
1. **T1a 实例最小上线包(上线里程碑)**:widget.js 后端托管(仿 admin StaticFiles)+ Dockerfile 带 widget/dist + CORS 三域名(env)+ P-1 存量清洗(已拍板)+ 三站点嵌入。**灰度顺序(已拍板):wiki → 官网 → 商城**;北极星观察期自 wiki 灰度日启动。**官网波次前置 C8 ✅ 已就绪**。前置检查项均完成(admin channel 独立 ✅ / P-1 方案已拍板)
2. **T1b 标准件分发(产品线,与 T1a 并行或后置)**:品牌/文案/主题配置化、分发文档、多站点嵌入指南、分发域名策略——服务"第二个用户",不挡上线
3. (预留)渠道适配器框架 `ChannelAdapter`——等第一个非 web 入口需求
4. (预留)集成方 API 认证:API key + 按集成方配额/预算——等第一个系统级 HEADLESS 对接(D-4 随之决策)
5. (后续逐步)MCP Server / Discord / WhatsApp 入口
6. Platform Assistant、Skills 工作流。⚠️ 工具调用使 prompt injection 升级为指令执行,威胁模型需重做

**E. 通用化/标准件化**(差距全景见 §6;D-1 拍板后范围收敛):
1. CamThink 常量出仓:L1/L2 硬编码收敛到实例配置层
2. 意图体系配置化(最大单点;按科技公司典型意图体系设计默认档)
3. Alembic 版本化迁移(私有部署多实例升级后**从"建议"升为"必须"**)
4. 实例 onboarding:引导向导 + 部署者文档 + 品牌配置清单 + licensing(技术 + 法律,D-1 要求)

**建议优先级框架**(已按 D-1/D-2/D-3 调整):
- **T0 收尾**:✅ 已完成(A1/A2 收口,REL-WIN 发布)
- **T1 上线里程碑**:T1a 实例最小上线包 = 实例线上线;T1b 标准件分发 = 产品线,不挡上线
- **T2/T3 商业闭环 vs 质量地基**(排序由 commercial 占比数据裁决,D-5):占比高 → B1+C2;占比低 → B2+B4+B3。观察期:T1 落地后 2-4 周意图分布数据再裁
- **T4 通用化起步**:E3(Alembic)→ E1(常量出仓)→ E2(意图配置化)→ E4(onboarding+licensing)
- **T5 按需/预留**:B5、C1~C6、D3~D6、Platform Assistant;低优工程清单:ruff 12 处、schemas/CLAUDE.md 文档不一致、**候选 12:CI 测试范围扩围**(CI pytest 排除 `tests/api/admin`+`test_sync_db.py`,C9/C10 关键测试仅本地门,应入 CI);**挂起:GitHub PAT 本体轮换**(用户明确勿催办)

## 4. 关键产品决策记录(已锁定)

| 决策 | 选择 | 时间 |
|---|---|---|
| **产品主定位** | RAG 知识助手中台服务:多入口 + 可插拔数据源/LLM;CamThink 第一个用户 | 2026-08-28(v3) |
| **D-1 产品形态** | (c) 私有部署商业授权;配套 licensing/onboarding/版本化迁移 | 2026-08-28 |
| **D-2 目标客户** | 科技公司为主 | 2026-08-28 |
| **D-3 入口层路线** | 标准 web 插件优先,其他集成手段预留 | 2026-08-28 |
| **D-4 集成方模型** | 暂不定,等第一个系统级对接需求 | 2026-08-28 |
| **D-5 北极星** | 分层双指标(产品层自助解决率 / 实例层有效线索数) | 2026-08-28 |
| **D-7 信号提取** | cron 低峰定期 | 2026-08-28 |
| **D-8 日志保留期** | 90 天 | 2026-08-28 |
| **D-9 健康度归属** | 拆分:接入健康归数据源页 / 质量归因归技术洞察 | 2026-08-28 |
| **D-10 widget 嵌入目标** | 官网 + wiki + 商城三站点 | 2026-08-28 |
| **P-1 存量清洗** | T1 上线时 cutoff:pg_dump 备份后 DELETE 627 条混用 channel 对话 | 2026-08-30 |
| **环境策略** | mac local=开发/测试;CI=回归;T4=生产+部署验收;不建 staging | 2026-08-28,08-30 固化 |
| **窗口协作模式** | 规划窗 main 维护文档;执行窗独立 worktree;交接先提交再开 worktree | 2026-08-28 |
| **D-13 删源清盘语义** | 删 upload_mode 源连带清理磁盘上传目录(仅 upload_mode;UI 确认文案注明"将删除已上传文件";服务器路径模式永不碰盘);随候选 11 实现 | 2026-08-31 拍板(按建议) |
| **D-14 产品文档三件套** | 采纳 v2.0 协议 canonical 路径:docs/product/PRODUCT_VISION / ROADMAP / STATE;旧单文件留指向 | 2026-08-31 拍板(按建议,同日迁移完成) |
| 自建 vs SaaS | 自建(数据自主 → 标准件核心卖点) | founding spec |
| 意图体系 | 4 类:commercial/product/support/off_topic | 2026-08-03 |
| commercial 意图 | WooCommerce 灌库后检索作答 | bc6bc9b |
| 代码源接入 | github 统一类型,local_git 降为实现细节 | 2026-08-04~05 |
| LLM 供应商类型 | 仅 openai_compatible;chain 粒度 {provider, model} | 2026-08-05 |
| 运营三页划分 | 按使用者目的分页 | 2026-08-07 |
| admin 视觉 | B 方案:功能对齐,视觉合理偏差,不引第三方图表库 | 2026-08-11 |
| 部署模式 | 生产纯 CI 镜像(禁源码挂载),mac 本地热更 | 2026-08-10 |

## 5. 待拍板决策清单

> 拍板后移入 §4 决策记录。

| # | 决策 | 状态 |
|---|---|---|
| D-6 | admin Phase 3 取舍(重点 B1 留资) | 🔵 不单独拍:由 commercial 占比数据 + 三页实际使用牵引 |
| D-11 | sync-consistency 收尾 | ✅ 已关闭(08-30 Review=PARTIAL,数据侧分流) |
| D-12 | tesla-t4 恢复预案执行 | 🔵 待停机窗口(60-90 分钟 + owners 确认;任何 T4 部署前查磁盘) |
| ~~D-13~~ | 删源清盘 | ✅ 2026-08-31 拍板(§4) |
| ~~D-14~~ | 文档三件套 | ✅ 2026-08-31 拍板并完成迁移(§4) |

## 6. 通用化差距分析(标准件视角,E 类背景)

> 2026-08-28 代码审计:后端+配置 12 文件 32 处 "camthink" 硬编码;前端 6 文件。**分层结论:架构骨架已是标准件形态,差距集中在业务语义层,最深单点是意图体系。**

### 6.1 已具备的标准件素质

插件化双注册表(Connector/LLMProvider,`@Registry.register`)· 配置数据化(数据源/Customization/LLM 路由全在 Postgres+admin UI;yaml seed=实例引导雏形)· 多渠道预留(channel 贯穿)· 部署物化(单镜像+compose 三套+CI+滚动更新)· 安全治理基座(RBAC/AES/熔断/限流/PII/prod 校验)· 通用质量机制(拒答门/rerank/override/自愈)。

### 6.2 耦合点分级

**L1 浅层(换 seed 即可)**:助手人设与 intent_styles(`config/system_prompt.yaml`)· Widget 品牌+域白名单(`widget/src/*`、`urlPolicy.ts`)· admin 产品线文案。

**L2 中层(需设计不伤架构)**:`product` 产品线维度(→租户 taxonomy,schema 已字符串)· 业务信号分析域 prompt(→词表配置化)· 连接器域默认值(github org/woocommerce 域)· 业务概览页语义。

**L3 深层(标准件化必经)**:**意图体系**(分类定义+few-shot+路由行为硬编码,→实例配置)· **入口层**(渠道适配器框架+集成方 API 认证)· **多租户**(私有部署形态可不需要,但需 onboarding)· **schema 迁移**(无 Alembic,交付硬伤)· 国际化 · 部署门槛(CPU/远程 embedding 档位)· 第三方文档(部署者文档不存在)。

### 6.3 通用化路径

**"边用边抽"而非"先抽象后推广"**:由第二个实例的真实需求牵引,避免过早抽象。但三项无论形态如何都该早做(随时间变贵):① Alembic ② 意图体系配置化 ③ CamThink 常量出仓。
