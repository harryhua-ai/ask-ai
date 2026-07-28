# Ask AI — CamThink AI 知识助手 设计文档

- **日期**:2026-07-28(第二版,基于功能需求讨论更新)
- **状态**:待用户审阅
- **项目仓库**:https://github.com/harryhua-ai/ask-ai.git
- **本地路径**:`/Users/harryhua/Documents/GitHub/ask-ai`

---

## 1. 背景与目标

构建一个对标 Kapa.ai 的自建 RAG 知识助手平台,部署在 CamThink 自有基础设施上。服务两类场景:

- 售前产品咨询与选型
- 开发者技术支持与文档查询

**最终形态**:多渠道接入(官网 Widget / Discord / WhatsApp / MCP Server),全功能管理后台,数据驱动的知识库质量优化。

**Phase 1 边界**:官网 + Wiki 嵌入悬浮 Widget,只回答问题 + 推荐相关页面;不收集销售线索、不转人工、不建工单、不做账户/订单/售后查询、不执行任何操作。

## 2. 路线决策

> **自建一个对标 Kapa.ai 的 RAG 系统** —— 架构/能力参考 Kapa,但跑在自有基础设施,数据自主。

**排除**:
- **Kapa.ai SaaS**:数据出域到其 Google Cloud,与数据自主要求冲突
- **在 Hermes camthink profile 上改造**:定位/入口/隐私/交互范式四重错位,且 0% RAG;改造成本高于新建

**复用**:
- camthink 已沉淀的知识语料(Knowledge 仓库、wiki.camthink.ai)
- camthink 已验证的 LLM 栈(deepseek)
- Hermes camthink profile 保持原状,继续当内部飞书 agent

## 3. 多渠道架构

核心设计:**统一 HTTP API + 渠道适配器**。RAG 后端不关心消息来自哪个渠道。

```
┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐
│  Widget  │  │ Discord  │  │ WhatsApp │  │ Claude Code  │
│ (SSE)    │  │ (Bot)    │  │ (Business)│  │ (MCP Server) │
└────┬─────┘  └────┬─────┘  └────┬─────┘  └──────┬───────┘
     │             │              │               │
     ▼             ▼              ▼               ▼
  ┌─────────────────────────────────────────────────────┐
  │            渠道适配器(Channel Adapters)               │
  │  各渠道 SDK → 统一消息格式转换                          │
  └────────────────────────┬────────────────────────────┘
                           ▼
  ┌─────────────────────────────────────────────────────┐
  │  FastAPI 统一 API                                     │
  │  POST /api/ask                                        │
  │  入参: {message, language, channel, conversation_history?} │
  │  出参: SSE 流式 {answer, sources}                     │
  └────────────────────────┬────────────────────────────┘
                           ▼
                    RAG 管线(见第 5 节)
```

### 渠道优先级

| 优先级 | 渠道 | 阶段 | 说明 |
|---|---|---|---|
| **P0** | Widget(SSE) | Phase 1 | 官网 + Wiki 嵌入 |
| **P1** | Discord + WhatsApp | Phase 4 | 社区 + 消息渠道 |
| **P2** | MCP Server | Phase 4 | 面向 Claude Code/Cursor |

**API 设计从一开始就按多渠道设计**,`channel` 字段从一开始就有,后期加渠道只需写适配器,后端零改。

### 统一消息格式

```python
@dataclass(frozen=True)
class IncomingMessage:
    message: str
    language: str | None       # 自动识别或前端传
    channel: str               # "widget" | "discord" | "whatsapp" | "mcp"
    conversation_history: list[dict]  # 有限多轮(前端保留最近 5 轮)
```

## 4. 技术选型

| 层 | 选定 | 说明 |
|---|---|---|
| 嵌入 | **BGE-m3**(本地自托管) | 多语言强;dense 1024 维 |
| 重排 | **bge-reranker-v2-m3**(本地) | cross-encoder |
| 向量库 | **Weaviate**(自托管) | 关闭内置 vectorizer,自灌 BGE-m3 向量;hybrid = dense + BM25 |
| 双路检索 | Weaviate hybrid | `alpha` 调语义/关键词权重 |
| LLM 生成 | **deepseek**(Phase 1 单一供应商) | 外部 API;后期支持多供应商 |
| 元数据/原文/同步/统计 | **Postgres** | 一步到位 |
| 后端 | **FastAPI** | SSE + 限流 |
| 前端 | 自建独立 React widget | `<script>` 标签嵌入,跨站点复用 |
| 同步调度 | cron + 脚本 | 定时增量 |
| LLM 抽象 | `LLMProvider` Protocol | 多供应商支持,统一接口 |

## 5. RAG 管线

```
[访客提问]
   │
   ▼  有限多轮:前端保留最近 5 轮对话一起发给后端,后端无状态
   │
   ├── 查询处理:语言识别 + 查询分解(复杂问题)
   │
   ├── 双路检索:Weaviate hybrid(BGE-m3 dense + 内置 BM25)
   │     alpha=0.5,召回 top ~50
   │
   ├── 重排:bge-reranker-v2-m3 → top 5~10
   │
   ├── 依据可靠性检查:最高分 < 阈值 → 拒答
   │
   ├── LLM 生成(deepseek)
   │     → Markdown 回答 + 内联来源引用 + 同语言
   │     → system prompt:严格依据、不编造、不确定性放开头
   │
   └── 匿名记录(问题/回答/来源/反馈/耗时/语言)
```

### 检索参数(Phase 1)

| 步骤 | 参数 |
|---|---|
| 查询处理 | 语言识别 + (复杂问题)查询分解 |
| 双路检索 | Weaviate hybrid,`alpha=0.5` |
| 召回 | top ~50 |
| 重排 | bge-reranker-v2-m3 → top 5~10 |
| 剪枝 | Phase 3 |
| 依据检查 | 重排最高分 < 阈值 → 拒答 |
| 生成 | top 片段 + system prompt → deepseek |

### 对话模式

**有限多轮(Phase 1)**:前端保留最近 5 轮(10 条消息:5 问 + 5 答),超过则丢弃最早的。每次请求将历史对话一起发给后端,后端无状态。

### 答案格式

| 项目 | 规格 |
|---|---|
| **格式标准** | Markdown(CommonMark 子集) |
| **代码块** | 支持(语法高亮) |
| **来源引用** | **内联引用**(不是脚注式) |
| **来源标签** | `[官网]` `[Wiki]` `[GitHub]` `[博客]` 等 |
| **反馈** | 每条答案后 👍/👎 按钮 |
| **推荐问题** | 首屏展示 3-5 个常见问题 |

### 拒答策略

- 重排最高分 < 阈值 → 拒答
- 拒答话术:"暂未在官方资料中找到相关信息"
- 不推荐相关问题(Phase 1 简化)
- 拒答问题入匿名统计(用于后期 Coverage Gaps 分析)

### 助手人设

- **语气**:专业、简洁、友好(不过度热情,不啰嗦)
- **自称**:"我"或"CamThink 助手"
- **称呼用户**:"你"
- **风格**:直答问题,不铺垫,不寒暄
- **技术内容**:保留产品型号、接口名、代码术语不翻译
- **不确定时**:开头说明,不编造

### 缓存策略

Phase 1 **不做缓存**(对齐 Kapa),每次走完整管线。后期流量上来后可加答案缓存(Postgres + TTL)。

## 6. 数据接入框架

### 设计原则

所有数据源通过**统一接口**接入,配置驱动,可扩展。新增数据源类型只需实现接口 + 加配置,管线零改。

### 统一接口

```python
@dataclass(frozen=True)
class RawDocument:
    source_id: str          # 源内唯一 ID(文件路径/URL/GitHub path)
    source_type: str        # connector 类型标识
    product: str            # 产品线: ne101 | ne301 | ne503 | neomind | aitoolstack | wiki
    title: str
    content: str            # Markdown 正文
    url: str                # 原始链接(可点击跳转)
    metadata: dict          # version, language, updated_at 等扩展字段
    content_hash: str       # 变更检测用

class DataSourceConnector(Protocol):
    """所有数据源 Connector 的统一接口"""

    @property
    def source_id(self) -> str: ...

    @property
    def product(self) -> str: ...

    def fetch_all(self) -> Iterator[RawDocument]:
        """全量拉取(首次接入或全量重建)"""
        ...

    def fetch_changes(self, since: datetime) -> Iterator[RawDocument]:
        """增量拉取(定时同步)"""
        ...

    def fetch_deleted(self, since: datetime) -> list[str]:
        """检测已删除的文档 ID"""
        ...
```

### 注册表

```python
class ConnectorRegistry:
    """Connector 注册表 — 新增数据源类型时在此注册"""

    _connectors: dict[str, type[DataSourceConnector]] = {}

    @classmethod
    def register(cls, connector_type: str):
        def decorator(connector_cls: type[DataSourceConnector]):
            cls._connectors[connector_type] = connector_cls
            return connector_cls
        return decorator

    @classmethod
    def create(cls, config: SourceConfig) -> DataSourceConnector:
        connector_cls = cls._connectors[config.type]
        return connector_cls(config)
```

### 配置驱动

```python
@dataclass(frozen=True)
class SourceConfig:
    id: str                 # 唯一标识
    type: str               # "github" | "filesystem" | "web_crawl" | "sdk" | ...
    product: str            # 产品线
    enabled: bool           # 是否启用
    config: dict            # 类型特定配置(交给各 Connector 自行解析)
    sync_interval: str      # 同步频率
```

### Connector 类型

| Connector | 接入方式 | Phase | 说明 |
|---|---|---|---|
| **GitHubConnector** | GitHub API | Phase 1 | 覆盖所有 camthink-ai 仓库 |
| **FileSystemConnector** | 本地文件系统 | Phase 1 | 覆盖 Knowledge 仓库 |
| **WebCrawlConnector** | Firecrawl / 自写爬虫 | Phase 2+ | 仅用于无 API 的第三方站点 |
| **SDKConnector** | 各平台 SDK/API | Phase 2+ | 官网 SDK、商城 SDK 等 |

### 数据源:GitHub 仓库(camthink-ai org)

按产品线分类,共 10 个仓库:

| 产品线 | 仓库 | 语言 | 默认分支 |
|---|---|---|---|
| **NE101** | `lowpower_camera` | C | hw-v1.2 |
| **NE301** | `ne301` | C | main |
| **NE503(含 Hailo)** | `ne503-aipc-sdks` | Python | main |
| | `meta-hailo-os` | Shell | main |
| **NeoMind** | `NeoMind` | Rust | main |
| | `NeoMind-DeviceTypes` | JS | main |
| | `NeoMind-Dashboard-Components` | JS | main |
| | `NeoMind-Extensions` | Rust | main |
| **AIToolStack** | `AIToolStack` | Python | main |
| **Wiki** | `wiki-documents` | JS(Docusaurus) | main |

**未纳入**:`iot_samples`、`cinfer`、`ne301-model-converter`

### 数据源:Knowledge 仓库

- 路径:`~/Documents/GitHub/Knowledge/知识库/`
- 子目录:support / wiki-en / sales / 硬件 / 经验
- 接入方式:FileSystemConnector,git pull + 文件 hash 比对

### 处理流程

```
知识源(Connector) → RawDocument → 清洗 → 分段(~500-800 token/chunk, 重叠 50-100)
  → 加元数据 → BGE-m3 嵌入 → 灌 Weaviate + 原文/元数据入 Postgres
```

### 元数据 schema

```json
{
  "source_url": "https://github.com/camthink-ai/ne503-aipc-sdks/blob/main/docs/quickstart.md",
  "source_type": "github",
  "product": "ne503",
  "language": "en",
  "version": "main",
  "updated_at": "2026-07-20T10:00:00Z",
  "title": "NE503 AIPC SDK Quick Start"
}
```

### 同步策略

- cron 定时增量:各源按 content_hash / commit 比对
- 同步日志入 Postgres(表结构见第 11.3 节)
- 失败用上一版向量库(Weaviate 不动)+ 告警
- 支持管理员手动触发(Phase 2 UI)
- 失效文档及时从 Weaviate 移除

## 7. LLM 管理框架

### 统一接口

```python
@dataclass(frozen=True)
class LLMResponse:
    content: str
    model: str
    tokens_input: int
    tokens_output: int
    latency_ms: int

class LLMProvider(Protocol):
    """所有 LLM 供应商的统一接口"""

    @property
    def provider_id(self) -> str: ...

    def generate(self, messages: list[dict], **kwargs) -> LLMResponse:
        """同步生成"""
        ...

    def stream(self, messages: list[dict], **kwargs) -> Iterator[str]:
        """流式生成(SSE)"""
        ...

    def health_check(self) -> bool:
        """健康检查(用于故障转移判断)"""
        ...
```

### 注册表 + 路由

```python
class LLMRegistry:
    """LLM 供应商注册 + 创建"""

    _providers: dict[str, type[LLMProvider]] = {}

    @classmethod
    def register(cls, provider_type: str):
        def decorator(provider_cls: type[LLMProvider]):
            cls._providers[provider_type] = provider_cls
            return provider_cls
        return decorator

    @classmethod
    def create(cls, config: LLMConfig) -> LLMProvider:
        provider_cls = cls._providers[config.type]
        return provider_cls(config)


class LLMRouter:
    """按用途路由到不同供应商,支持故障转移"""

    def __init__(self, providers: dict[str, LLMProvider], routing: LLMRouting):
        self.providers = providers
        self.routing = routing

    def generate(self, messages: list[dict], task: str = "generation") -> LLMResponse:
        chain = self.routing.get_chain(task)  # ["deepseek", "anthropic"]
        for provider_id in chain:
            provider = self.providers[provider_id]
            if provider.health_check():
                return provider.generate(messages)
        raise RuntimeError("All providers unavailable")
```

### 数据模型(Postgres)

```sql
CREATE TABLE llm_providers (
    id          VARCHAR(50) PRIMARY KEY,
    type        VARCHAR(50) NOT NULL,       -- "openai_compatible" | "anthropic" | "openai" | ...
    enabled     BOOLEAN DEFAULT true,
    config      JSONB NOT NULL,             -- api_base, api_key(加密), model, max_tokens, temperature
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE llm_routing (
    task        VARCHAR(50) PRIMARY KEY,    -- "generation" | "query_decomposition" | "pruning"
    chain       JSONB NOT NULL,             -- ["deepseek", "anthropic"]
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);
```

### 阶段规划

| 阶段 | LLM 管理 |
|---|---|
| **Phase 1** | 单一 deepseek,YAML + 环境变量配置,无 UI |
| **Phase 2+** | 多供应商管理 UI + 路由 + 故障转移 + 连通性测试 + 用量统计 |

抽象层 Phase 1 就建好,但只实现一个 deepseek provider。

## 8. Widget 设计

### 打包与嵌入

- **独立 React 应用**,打包成 `widget.js`
- 以 `<script>` 标签嵌入任意站点(官网 + Wiki + 后续任意页面)
- 样式隔离:Shadow DOM 或 CSS 前缀,避免与宿主页面冲突
- 配置:通过 `data-*` 属性或全局变量传入(API 地址、语言、欢迎语等)

```html
<script src="https://ask.camthink.ai/widget.js" async></script>
```

### 宿主站点(Phase 1)

| 站点 | 技术栈 |
|---|---|
| camthink-site(官网) | Next.js 16 + React 19 |
| wiki.camthink.ai | Docusaurus(wiki-documents 仓库) |

### 交互

- 全站右下角悬浮按钮 → 展开聊天面板
- 桌面 + 移动响应式
- 免登录、匿名
- SSE 流式输出
- 答案含内联可点击来源链接 + 类型标签
- 答案后 👍/👎 反馈按钮
- 首屏 3-5 个推荐常见问题
- 有限多轮:支持追问(前端保留最近 5 轮)

### 品牌定制

- 主色(CamThink 品牌色)
- Logo
- 助手名称(待确认)
- 欢迎语(待确认)

## 9. GPU 后端抽象与部署

**核心要求**:推理(嵌入 + 重排)兼容 NVIDIA 与 Apple GPU。

```
业务层 → Embedder / Reranker 接口 → device 配置(auto|cuda|mps|cpu)→ PyTorch 后端
```

启动探测顺序:`cuda` > `mps` > `cpu`。一套代码(FlagEmbedding 库)三端可跑。

| 阶段 | 环境 | device | 说明 |
|---|---|---|---|
| Phase 1 | 本地 macOS(Apple Silicon) | mps(不行则 cpu) | docker compose 跑全栈;验证产品 |
| 后期 | tesla-t4(Ubuntu + NVIDIA T4 16GB) | cuda | 生产 |

## 10. 管理平台(分 4 期)

参考 Kapa.ai 的管理体系,全部功能按依赖关系分 4 期交付:

### Phase 1 — 核心问答

| 模块 | 内容 |
|---|---|
| RAG 管线 | 检索 → 重排 → 生成 → 拒答 |
| Widget | 独立 JS,嵌入官网 + Wiki |
| DataSourceConnector 框架 | GitHub + FileSystem 两个 Connector |
| 数据源配置 | YAML 配置文件(无 UI) |
| 同步脚本 | cron + 日志入 Postgres |
| 单套 Customization | system prompt 配置文件 |
| LLM 管理 | 单 deepseek,YAML + 环境变量 |
| 匿名统计采集 | 问题/答案/反馈/耗时入 Postgres |

### Phase 2 — 管理后台

| 模块 | 内容 |
|---|---|
| 管理后台 UI | Web 界面(Dashboard) |
| 数据源 CRUD | 可视化添加/编辑/删除/启停源 |
| 同步监控面板 | 实时状态、失败原因、历史记录 |
| Customization 管理 | 多套配置,按渠道绑定,实时预览 |
| LLM 供应商管理 | 多供应商 CRUD,连通性测试,路由配置 |
| 对话审查 | 匿名对话列表,多维过滤,Intent 标签 |
| 团队/RBAC | 用户管理,角色权限 |

### Phase 3 — 分析与优化

| 模块 | 内容 |
|---|---|
| Coverage Gaps | AI 聚类无法回答的问题 |
| Top Questions | 高频问题主题聚类 |
| Source Analytics | 最常引用页面,点击追踪 |
| Improve This Answer | 人工覆盖特定答案 |
| 报表 | Email/Slack 定期推送 |

### Phase 4 — 智能管理

| 模块 | 内容 |
|---|---|
| Platform Assistant | 对话式管理("上周哪些问题没答上来?") |
| Skills | AI 辅助工作流(覆盖盲区分析、文档审计等) |
| 多渠道 | Discord + WhatsApp 适配器 |
| MCP Server | 面向 Claude Code/Cursor |
| 剪枝 | 小 LLM 过滤低相关 chunk |

## 11. 数据模型(Postgres)

Phase 1 创建全部表,部分表有预留字段供后期功能使用,避免数据迁移。

### 11.1 对话与统计(Phase 1 采集,Phase 2-3 消费)

```sql
-- 匿名对话记录(Phase 1 采集,Phase 2 对话审查,Phase 3 分析)
CREATE TABLE conversations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Phase 1 字段
    question        TEXT NOT NULL,
    answer          TEXT,
    channel         VARCHAR(20) NOT NULL DEFAULT 'widget',   -- widget | discord | whatsapp | mcp
    language        VARCHAR(10),                              -- 识别出的语言
    sources         JSONB DEFAULT '[]',                       -- 引用的来源列表
    is_answered     BOOLEAN NOT NULL DEFAULT false,           -- 是否成功回答(非拒答)
    feedback        VARCHAR(10),                              -- 'up' | 'down' | NULL
    response_time_ms INT,                                     -- RAG 管线耗时
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Phase 2 预留字段(Phase 1 建表时创建,默认 NULL)
    intent_tag      VARCHAR(100),                             -- 意图标签(Phase 2 自动标注)
    custom_tags     JSONB DEFAULT '[]',                       -- 自定义标签(Phase 2)
    customization_id VARCHAR(50),                             -- 关联的配置 ID(Phase 2)

    -- Phase 3 预留字段
    cluster_id      VARCHAR(100),                             -- 聚类分组 ID(Phase 3 Top Questions)
    gap_status      VARCHAR(20),                              -- 'open' | 'resolved' | NULL(Phase 3 Coverage Gaps)
    override_answer TEXT                                      -- 人工覆盖答案(Phase 3 Improve This Answer)
);

CREATE INDEX idx_conversations_created_at ON conversations (created_at);
CREATE INDEX idx_conversations_is_answered ON conversations (is_answered);
CREATE INDEX idx_conversations_channel ON conversations (channel);
CREATE INDEX idx_conversations_cluster_id ON conversations (cluster_id) WHERE cluster_id IS NOT NULL;
CREATE INDEX idx_conversations_gap_status ON conversations (gap_status) WHERE gap_status IS NOT NULL;
```

### 11.2 来源点击追踪(Phase 1 采集,Phase 3 分析)

```sql
-- 用户点击答案中来源链接的记录(Phase 3 Source Analytics 消费)
CREATE TABLE source_clicks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
    source_url      TEXT NOT NULL,
    source_type     VARCHAR(20) NOT NULL,                     -- github | wiki | website | blog
    product         VARCHAR(50),                              -- ne101 | ne301 | ...
    clicked_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_source_clicks_conversation ON source_clicks (conversation_id);
CREATE INDEX idx_source_clicks_source_url ON source_clicks (source_url);
```

### 11.3 同步日志(Phase 1 采集,Phase 2 监控面板)

```sql
-- 数据源同步执行记录
CREATE TABLE sync_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id       VARCHAR(100) NOT NULL,                    -- 对应 SourceConfig.id
    source_type     VARCHAR(50) NOT NULL,                      -- github | filesystem | web_crawl | sdk
    status          VARCHAR(20) NOT NULL,                      -- 'success' | 'failed' | 'partial'
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    duration_ms     INT,
    items_new       INT DEFAULT 0,
    items_updated   INT DEFAULT 0,
    items_deleted   INT DEFAULT 0,
    items_unchanged INT DEFAULT 0,
    error_detail    TEXT,                                     -- 失败原因详情
    triggered_by    VARCHAR(20) DEFAULT 'cron'                -- 'cron' | 'manual'
);

CREATE INDEX idx_sync_log_source ON sync_log (source_id, started_at DESC);
CREATE INDEX idx_sync_log_status ON sync_log (status, started_at DESC);
```

### 11.4 数据源配置(Phase 1 YAML,Phase 2 迁入 Postgres + UI)

```sql
-- 数据源配置(Phase 2 管理 UI 操作;Phase 1 可不写入,仅建表)
CREATE TABLE data_sources (
    id              VARCHAR(100) PRIMARY KEY,                  -- 唯一标识
    type            VARCHAR(50) NOT NULL,                      -- github | filesystem | web_crawl | sdk
    product         VARCHAR(50) NOT NULL,                      -- 产品线
    enabled         BOOLEAN DEFAULT true,
    config          JSONB NOT NULL,                            -- 类型特定配置
    sync_interval   VARCHAR(20) DEFAULT '24h',                 -- 同步频率
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
```

### 11.5 Customization 配置(Phase 1 单套 YAML,Phase 2 多套 + UI)

```sql
-- 助手配置(system prompt、人设、语气等)
-- Phase 1 可不写入,仅建表;Phase 2 多套配置 + 按渠道绑定
CREATE TABLE customizations (
    id              VARCHAR(50) PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,                     -- 配置名称,如 "售前默认" "开发者技术"
    -- 三层结构(参考 Kapa)
    system_prompt   TEXT NOT NULL,                             -- 完整 system prompt
    style_tone      TEXT,                                      -- 风格语气指令
    guardrails      TEXT,                                      -- 边界规则(禁止回答的领域等)
    language        VARCHAR(10) DEFAULT 'auto',                -- 回答语言(auto = 跟随提问)
    assistant_name  VARCHAR(50) DEFAULT 'CamThink 助手',
    -- 版本管理(Phase 2+)
    is_active       BOOLEAN DEFAULT true,
    version         VARCHAR(20) DEFAULT '1.0',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- 配置与渠道绑定(一个渠道绑一套配置)
CREATE TABLE customization_bindings (
    channel         VARCHAR(20) PRIMARY KEY,                   -- widget | discord | whatsapp | mcp
    customization_id VARCHAR(50) REFERENCES customizations(id) ON DELETE CASCADE
);
```

### 11.6 人工覆盖答案(Phase 3 Improve This Answer)

```sql
-- 针对特定问题的人工覆盖答案
-- 匹配规则:当用户问题与此记录的 match_pattern 相似度 > 阈值时,直接返回 override_answer
CREATE TABLE answer_overrides (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    match_pattern   TEXT NOT NULL,                             -- 匹配的问题模式(或关键词)
    match_type      VARCHAR(20) DEFAULT 'semantic',            -- 'semantic' | 'keyword' | 'regex'
    override_answer TEXT NOT NULL,                             -- 人工覆盖的答案(Markdown)
    override_sources JSONB DEFAULT '[]',                       -- 来源链接
    created_by      VARCHAR(100),                              -- 创建者
    is_active       BOOLEAN DEFAULT true,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
```

### 11.7 用户与权限(Phase 2 RBAC)

```sql
-- 管理后台用户
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           VARCHAR(255) NOT NULL UNIQUE,
    name            VARCHAR(100),
    role            VARCHAR(20) NOT NULL DEFAULT 'viewer',     -- 'admin' | 'editor' | 'viewer'
    is_active       BOOLEAN DEFAULT true,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    last_login_at   TIMESTAMPTZ
);
```

### 11.8 LLM 供应商(已在第 7 节定义)

`llm_providers` 和 `llm_routing` 表见第 7 节,此处不重复。 表创建策略

| 表 | Phase 1 | 说明 |
|---|---|---|
| `conversations` | ✅ 创建 + 写入 | Phase 1 采集数据,预留字段为 NULL |
| `source_clicks` | ✅ 创建 + 写入 | Phase 1 采集点击 |
| `sync_log` | ✅ 创建 + 写入 | Phase 1 cron 写入 |
| `data_sources` | ✅ 创建(空表) | Phase 1 用 YAML,Phase 2 迁入 |
| `customizations` | ✅ 创建(空表) | Phase 1 用 YAML,Phase 2 迁入 |
| `customization_bindings` | ✅ 创建(空表) | Phase 2 使用 |
| `answer_overrides` | ✅ 创建(空表) | Phase 3 使用 |
| `users` | ✅ 创建(空表) | Phase 2 使用 |
| `llm_providers` | ✅ 创建(空表) | Phase 1 用 YAML,Phase 2 迁入 |
| `llm_routing` | ✅ 创建(空表) | Phase 1 用 YAML,Phase 2 迁入 |

**Phase 1 一次性建全部表,预留字段默认 NULL,后期功能直接填充,无需数据迁移。**

## 12. 管线扩展接口(预留)

### 12.1(Phase 3)

```python
class Pruner(Protocol):
    """剪枝接口 — Phase 3 插入重排与生成之间"""

    def prune(
        self,
        query: str,
        chunks: list[RetrievedChunk],
    ) -> list[RetrievedChunk]:
        """过滤低相关 chunk,保留高相关 chunk"""
        ...
```

管线插入点:
```
重排 → [Pruner(Phase 3)] → 依据检查 → 生成
```

Phase 1 不实现,管线中预留位置。

### 12.2(Phase 4)

```python
class ChannelAdapter(Protocol):
    """渠道适配器接口 — 每个渠道实现一个"""

    @property
    def channel_type(self) -> str: ...

    def receive_message(self, raw_event: dict) -> IncomingMessage:
        """将渠道原始事件转为统一消息格式"""
        ...

    def send_response(self, conversation_id: str, response: str | Iterator[str]) -> None:
        """将回复发送回渠道(支持流式)"""
        ...
```

`IncomingMessage` 已在第 3 节定义,`channel` 字段已预留所有渠道类型。

## 13. 隐私与数据收集

- 有限多轮:前端保留最近 5 轮,后端无状态,不落 session
- PII 脱敏(邮箱 / 电话正则,入库前)
- 不收集姓名 / 邮箱 / 电话,不存完整 IP
- 日志保留期:**90 天**(默认,待最终确认)
- 不用日志训练公开模型

## 14. 部署形态

**Phase 1(macOS 本地)**:
- docker compose:Weaviate + Postgres + RAG 服务(FastAPI)
- BGE-m3 + reranker 走 mps(或 cpu)
- LLM 走 deepseek 外部 API
- widget 嵌入官网 + Wiki(localhost)

**后期(tesla-t4 生产)**:
- 同 docker compose 搬到 Ubuntu
- device 切 cuda(T4 16GB)
- widget 嵌入生产站点

## 15. 项目结构(规划)

```
ask-ai/
├── docs/superpowers/specs/      # 设计文档
├── backend/                     # FastAPI RAG 服务
│   ├── api/                     # 统一 API(SSE 问答端点)
│   ├── retrieval/               # 检索 + 重排
│   ├── embedder/                # BGE-m3 + device 抽象
│   ├── connectors/              # 数据源 Connector 框架
│   │   ├── base.py              # DataSourceConnector Protocol + RawDocument
│   │   ├── registry.py          # ConnectorRegistry
│   │   ├── github.py            # GitHubConnector
│   │   └── filesystem.py        # FileSystemConnector
│   ├── llm/                     # LLM 管理框架
│   │   ├── base.py              # LLMProvider Protocol + LLMResponse
│   │   ├── registry.py          # LLMRegistry + LLMRouter
│   │   └── deepseek.py          # DeepseekProvider
│   ├── pipeline/                # 清洗 + 分段 + 嵌入管道
│   └── db/                      # Postgres 模型
├── widget/                      # 独立 React widget(打包成 widget.js)
├── channels/                    # 渠道适配器(Phase 4)
│   ├── discord/
│   ├── whatsapp/
│   └── common/
├── deploy/                      # docker-compose / 部署脚本
├── scripts/                     # 同步 cron / 管理
├── config/                      # YAML 配置文件
│   ├── data_sources.yaml
│   └── llm_providers.yaml
└── .env.example
```

## 16. Phase 1 验收标准

- 官网 + Wiki 右下角可打开助手,桌面 + 移动均可用
- 能识别并回答多语言问题
- 能回答主要产品(NE101 / NE301 / NE503 / NeoMind / AIToolStack)、解决方案、技术文档问题
- 每条有效答案含官方来源链接(内联引用 + 类型标签)
- 无依据问题不编造(重排分数阈值 + prompt 双重保险)
- 定时自动同步;失败时旧知识库仍可用
- 能采集匿名统计(热门问题、无答案问题、来源点击、反馈)
- 访客输入的常见敏感信息能被脱敏
- device 抽象在 macOS(mps/cpu)可跑,且可平滑迁移到 T4(cuda)
- DataSourceConnector 框架可扩展(GitHub + FileSystem 已实现)
- LLMProvider 框架可扩展(deepseek 已实现)
- Widget 可通过 `<script>` 标签嵌入不同站点

## 17. 待确认项与风险

### 待确认(不影响 Phase 1 开工)

- 日志保留期(默认 90 天)
- widget 视觉样式、助手名称、欢迎语、主色调
- macOS 开发机内存(建议 16G+)
- MPS 上 BGE-m3 兼容性需实测
- 首期优先验收的产品 / 技术问题清单
- Knowledge 仓库各子目录的具体纳入范围
- 各 GitHub 仓库的具体过滤规则(目录/文件类型)

### 风险

- **macOS 不宜长期作生产**(服务管理 / 稳定性 / docker 资源),需按计划迁移到 tesla-t4
- **deepseek API 可用性**:Phase 1 单一供应商,无故障转移;Phase 2 加备用供应商
- **Widget 跨框架兼容**:Shadow DOM 在不同宿主站点(Next.js / Docusaurus)需实测
