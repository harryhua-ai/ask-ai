# Ask AI — CamThink 官网 AI 助手 设计文档

- **日期**:2026-07-27
- **状态**:待用户审阅
- **项目仓库**:https://github.com/harryhua-ai/ask-ai.git
- **本地路径**:`/Users/harryhua/Documents/GitHub/ask-ai`

---

## 1. 背景与目标

在 CamThink 官网(www.camthink.ai)新增 AI 问答助手,帮助访客快速查询产品信息、技术文档与开发资料。同时服务两类场景:

- 售前产品咨询与选型
- 开发者技术支持与文档查询

**首期边界**:只回答问题 + 推荐相关页面;**不**收集销售线索、不转人工、不建工单、不做账户/订单/售后查询、不执行任何操作。

**形态**:全站右下角悬浮 widget,桌面 + 移动适配,访客免登录,答案必须附带官方来源链接。

## 2. 路线决策

经多路线评估(含对本地 Hermes camthink profile 的深度剖析),确定:

> **自建一个对标 Kapa.ai 的 RAG 系统** —— 架构/能力参考 Kapa,但跑在自有基础设施,数据自主。

**排除**:
- **Kapa.ai SaaS**:数据出域到其 Google Cloud,与数据自主要求冲突
- **在 Hermes camthink profile 上改造**:camthink 是"内部技术支持工程师"agent(接飞书/WeCom),定位/入口/隐私/交互范式四重错位,且 0% RAG;改造成本高于新建,且会破坏在用工具

**复用**(camthink 的价值在语料与领域知识,不在框架):
- camthink 已沉淀的知识语料(Knowledge 仓库、wiki.camthink.ai)—— 省下领域知识整理这块最大工作
- camthink 已验证的 LLM 栈(deepseek-v4-pro)
- Hermes camthink profile 保持原状,继续当内部飞书 agent;未来可选与官网助手共享索引

## 3. 整体架构(对标 Kapa 管线,组件自建)

```
[官网访客·匿名]
   │  悬浮 widget(嵌入 Next.js 官网,桌+移)
   ▼  SSE 流式
┌──────────────────────── 对话网关(FastAPI·公开端点)────────────────────────┐
│  限流(访客级+全局) · 缓存(常见问题) · 匿名会话 · PII 脱敏 · 匿名统计       │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   ▼
   查询处理:语言识别 + 查询分解(复杂问题)
                                   ▼
   双路检索:Weaviate hybrid(BGE-m3 dense + 内置 BM25)
                                   ▼
   重排:bge-reranker-v2-m3 → top 5~10
                                   ▼(剪枝后期再加)
   依据可靠性检查(最高分 < 阈值 → 拒答"未找到")
                                   ▼
   LLM 生成(deepseek-v4-pro)→ 同语言回答 + 官方来源链接
                                   ▼
   匿名记录(问题/回答/来源点击/反馈/耗时/语言)

数据管道(每天 cron 增量):
  知识源 → 抓取 → 清洗/分段 + 元数据 → BGE-m3 嵌入 → Weaviate + Postgres
```

## 4. 技术选型

| 层 | 选定 | 说明 |
|---|---|---|
| 嵌入 | **BGE-m3**(本地自托管) | 多语言强;dense 1024 维 |
| 重排 | **bge-reranker-v2-m3**(本地) | cross-encoder |
| 向量库 | **Weaviate**(自托管) | 关闭内置 vectorizer,自灌 BGE-m3 向量;hybrid = dense + BM25 |
| 双路检索 | Weaviate hybrid | `alpha` 调语义/关键词权重 |
| LLM 生成 | **deepseek-v4-pro** | 复用 camthink 已验证配置;外部 API |
| 元数据/原文/同步/统计 | **Postgres** | 一步到位 |
| 后端 | **FastAPI** | SSE + 限流 + 缓存 |
| 前端 | 自建轻量 React widget | 匿名、悬浮、桌+移 |
| 同步调度 | cron + 脚本 | 每天增量 |
| 抓取 | firecrawl + sitemap + git | 多源 |

## 5. GPU 后端抽象与部署迁移路径

**核心要求**:推理(嵌入 + 重排)兼容 NVIDIA 与 Apple GPU。

**抽象层**:
```
业务层 → Embedder / Reranker 接口 → device 配置(auto|cuda|mps|cpu)→ PyTorch 后端
```
启动探测顺序:`cuda` > `mps` > `cpu`。一套代码(FlagEmbedding 库)三端可跑。后期可扩 MLX / ONNX / Triton 实现。

**部署迁移路径**:

| 阶段 | 环境 | device | 说明 |
|---|---|---|---|
| 首期 | 本地 macOS(Apple Silicon) | mps(不行则 cpu) | docker compose 跑全栈;验证产品 |
| 后期 | **tesla-t4**(Ubuntu + NVIDIA Tesla T4 16GB) | cuda | 生产;T4 16GB 跑 BGE-m3 + reranker 显存富余 |

迁移时只换 `device=cuda` + docker 搬到 Linux,业务代码零改。

**设计显式处理的坑**:
- MPS 算子兼容:首期实测 BGE-m3 在 MPS 上能否正常出向量,不行则 Apple 走 CPU(开发够用)
- 数值一致性:建索引与查询必须同后端;索引记录所用 device
- macOS 内存:建议 16G+(Weaviate + Postgres + BGE-m3 + reranker + RAG 服务)

## 6. 数据管道与知识源

**知识源**(按优先级):
1. **Knowledge 仓库**(`~/Documents/GitHub/Knowledge/知识库/`:support / wiki-en / sales / 硬件 / 经验)—— **直接复用**,git pull + 文件 hash 比对
2. **wiki.camthink.ai**(Docusaurus):sitemap + markdown,作为权威产品定义源
3. **官网** www.camthink.ai:sitemap + firecrawl
4. **GitHub 产品仓**(ne301 / lowpower_camera / NeoMind 等):README / docs
5. **博客**

**处理流程**:抓取 → 清洗 → 分段(按文档结构,~500–800 token/chunk,重叠 50–100)→ 加元数据 → BGE-m3 嵌入 → 灌 Weaviate + 原文/元数据入 Postgres

**元数据 schema**:`{source_url, source_type, product, language, version, updated_at, title}`

## 7. 检索管线参数(首期)

| 步骤 | 参数 |
|---|---|
| 查询处理 | 语言识别 + (复杂问题)查询分解 |
| 双路检索 | Weaviate hybrid,`alpha=0.5` |
| 召回 | top ~50 |
| 重排 | bge-reranker-v2-m3 → top 5~10 |
| 剪枝 | ⏸ 首期跳过 |
| 依据检查 | 重排最高分 < 阈值 → 拒答"未找到" |
| 生成 | top 片段 + system prompt(严格依据 + 来源引用 + 同语言)→ deepseek-v4-pro |

## 8. 知识库同步策略

- 每天 cron 增量:各源按 last_updated / hash / commit 比对
- 同步日志入 Postgres(`sync_log`:源 / 时间 / 新增·更新·删除数 / 状态 / 失败原因)
- 失败用上一版向量库(Weaviate 不动)+ 告警
- 支持管理员手动触发
- 失效页面及时从 Weaviate 移除

## 9. 前端 Widget

- 全站右下角悬浮按钮 → 展开聊天面板
- 桌面 + 移动响应式
- 免登录、匿名
- SSE 流式输出
- 答案含可点击来源链接(标注来源类型:官网 / Wiki / GitHub / 博客)
- 满意 / 不满意反馈按钮

## 10. 隐私与数据收集

- 不落 session,只落匿名统计
- PII 脱敏(邮箱 / 电话正则,入库前)
- 不收集姓名 / 邮箱 / 电话,不存完整 IP
- 日志保留期:**90 天**(默认,待最终确认)
- 不用日志训练公开模型

## 11. 部署形态

**首期(macOS 本地)**:
- docker compose:Weaviate + Postgres + RAG 服务(FastAPI)
- BGE-m3 + reranker 走 mps(或 cpu)
- LLM 走 deepseek-v4-pro 外部 API
- widget 开发模式嵌入官网 Next.js(localhost)

**后期(tesla-t4 生产)**:
- 同 docker compose 搬到 Ubuntu
- device 切 cuda(T4 16GB)
- widget 嵌入生产官网

## 12. 项目结构(规划)

```
ask-ai/
├── docs/superpowers/specs/      # 设计文档
├── backend/                     # FastAPI RAG 服务
│   ├── api/                     # 路由(SSE 问答端点)
│   ├── retrieval/               # 检索 + 重排
│   ├── embedder/                # BGE-m3 + device 抽象
│   ├── pipeline/                # 抓取 + 同步管道
│   └── db/                      # Postgres 模型
├── widget/                      # React 悬浮 widget
├── deploy/                      # docker-compose / 部署脚本
├── scripts/                     # 同步 cron / 管理
└── .env.example
```

## 13. 首期 MVP 范围

| ✅ 首期做 | ⏸ 后期迭代 |
|---|---|
| 双路检索 + 重排 | 剪枝(小 LLM) |
| 精确来源引用 + 无依据拒答 | Coverage Gaps / Top Questions 分析 |
| 多语言(识别 + 同语言答) | 多数据源连接器(20+) |
| 匿名 SSE widget(桌+移) | Improve This Answer(人工覆盖) |
| 每天 cron 同步(官+wiki+Knowledge) | 飞书 / Discord 渠道(借 hermes) |
| 匿名统计 + PII 脱敏 | Agentic RAG(多轮工具调用) |

## 14. 验收标准

- 全站右下角可打开助手,桌面 + 移动均可用
- 能识别并回答多语言问题
- 能回答主要产品(NE101 / NE301 / NE503 / NG4500 / NeoMind)、解决方案、技术文档问题
- 每条有效答案含官方来源链接
- 无依据问题不编造
- 每天自动同步;失败时旧知识库仍可用
- 能统计热门问题、无答案问题、来源点击
- 访客输入的常见敏感信息能被脱敏
- device 抽象在 macOS(mps/cpu)可跑,且可平滑迁移到 T4(cuda)

## 15. 待确认项与风险

- 日志保留期(默认 90 天)
- widget 视觉样式、助手名称、欢迎语
- macOS 开发机内存(建议 16G+)
- MPS 上 BGE-m3 兼容性需首期实测
- 首期优先验收的产品 / 技术问题清单
- **风险**:macOS 不宜长期作生产(服务管理 / 稳定性 / docker 资源),需按计划迁移到 tesla-t4
