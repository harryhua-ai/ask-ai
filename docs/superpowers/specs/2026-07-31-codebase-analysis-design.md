# Ask AI 代码库分析能力 设计文档

- **日期**:2026-07-31
- **状态**:待用户审阅
- **范围**:在现有 RAG 系统上新增"全量代码库"索引与检索能力(纯 RAG,不含 agent 深挖层)
- **前序文档**:`2026-07-27-ask-ai-design.md`(基础 RAG 平台设计)

---

## 1. 背景与目标

现有 ask-ai 只索引产品文档与示例代码(`config/data_sources.yaml` 的 `include_dirs` 限定 `docs/examples/README`),Weaviate 仅 240 chunk。外部用户问代码级问题(函数用法、驱动配置、API 调用、跨分支版本差异)时召回不足,拿不到"最佳最完整"的答案。

### 目标

让管理员能在面板配置任意 GitHub / 本地代码源(含**多分支全量**),系统**高质量并行索引**,外部请求经**混合检索**获得精准、完整、带版本溯源的答案。

### 最终形态

- 管理面板配置数据源(github / 本地文件夹)+ **多分支多选** + 范围 + 排除规则
- **多分支全量**代码 + 文档入库(极保守排除,不丢有用内容)
- **纯 RAG**:tree-sitter AST 分块 + BGE-m3(GPU batch)+ **SCIP 精确符号表** + 向量/符号混合检索 + reranker
- 答案带 **分支/版本溯源链接**(文件:行号 @ branch)

### 本期不含(YAGNI,后续增量)

- **Agent 深挖层**:先做纯 RAG,看召回质量不够再加 agent 动态 grep/read 源码
- **代码图谱可视化**:SCIP 数据入库支持查询,但前端图谱 UI 后续
- **完整调用链分析 UI**:SCIP 引用数据入库,查询能力先行,可视化后续

---

## 2. 现状基线

### 2.1 数据源子系统现状(代码梳理结论)

| 层 | 现状 | 问题 |
|---|---|---|
| 配置 | YAML(`data_sources.yaml`)与 DB(`data_sources` 表)双轨;`sync.py` 只读 YAML | **P1**:管理员后台改的 DB 配置 sync 不读,不生效 |
| Connector | Protocol + 注册表良好;有 github/filesystem 两实现 | 可扩展,无需大改 |
| 分块 | `chunk_document_semantic` 为 Markdown 设计(标题/段落/fence) | **P2**:Python `#` 注释被误判为标题、代码无 fence 保护、函数被截断 |
| 灌入 | Weaviate 写入完整;`documents` 表写入可选 | **P3**:`sync.py`/`trigger_sync` 均未传 `session_factory`,documents 表恒空 |
| 检索 | intent / query_rewrite / search / rerank / pruner 齐全 | 检索侧组件不缺,短板在索引侧 |
| 同步 | cron 增量(24h 窗口)+ 手动触发;错误隔离良好 | 串行,无并发 |
| Admin 前端 | 数据源 CRUD + 同步日志;新建表单仅 4 字段(id/type/product/config_text JSON 文本域) | **P6**:owner/repo/branch/include_dirs/exclude 全靠手写 JSON;无编辑/删除 UI;**P7**:前端 type 枚举含 `web_crawl`/`sdk` 后端未注册 |

### 2.2 目标代码库规模(已 clone 到 `~/Documents/GitHub/ask-ai-corpus/`,1.8GB)

| 仓库 | 远程分支 | 单分支代码 LOC | 备注 |
|---|---|---:|---|
| ne301 | 7(`main` `v2.3.0-beta` `stedgeai-v2.2` `stedgeai-v4.0` `stedgeai-variant-unify` `halow` `ir-ver`) | 2,990,181 | STM32 固件,含 CMSIS/Middlewares/vendor |
| lowpower_camera | 3(`flash_8M` `hw-v1.2` `hw-v2.0`) | 1,056,736 | ESP32,ESP-IDF |
| NeoMind | 1(`main`) | 388,126 | Rust |
| NeoMind-Extensions | 1(`main`) | 148,868 | Rust |
| AIToolStack | 1(`main`) | 33,085 | Python |
| 其余 5 个 | 各 1(`main`) | ~24K | 小 |
| **合计(单分支)** | — | **4,641,111** | 9,706 代码文件 + 1,322 文档 |

**多分支并集估算**:ne301(7)× lowpower_camera(3)跨分支大量重叠但各有差异,粗估代码并集 **~8–10M LOC** → **20–30 万 chunk**。

**语言分布(单分支 LOC)**:.c 2.70M / .h 1.23M / .rs 355K / .tsx 139K / .py 118K / .ts 50K / .cpp 17K / .js 15K / .sh 8K / .hpp 6K。

**索引成本(多分支全量)**:BGE-m3 T4 索引 **15–25 分钟**,Weaviate **3–5GB**,symbols 表 **~50MB(10万+ 行)**。技术可行。

**关键特征**:大头(ne301/lowpower_camera)是嵌入式固件,含大量 vendor / CMSIS / 多版本中间件(stedgeai 2.2/3.0/4.0)/ 第三方库(mongoose)/ 测试数据(wave_1ch)。经讨论确认:**这些不视为噪音**——CamThink 产品基于 STM32+Hailo,客户问题恰恰可能落在 CMSIS 寄存器、ATON NPU 接口、中间件上,必须保留。

### 2.3 问题清单

| # | 问题 | 严重度 |
|---|---|---|
| P0 | 无智能排除策略(构建产物/二进制/纯测试数据会污染) | 🔴 |
| P1 | YAML/DB 配置双轨,sync 只读 YAML | 🔴 |
| P2 | 分块器不适配代码 | 🔴 |
| P6 | 前端配置 UX 简陋,关键字段靠手写 JSON,无分支多选 | 🔴 |
| P8(新) | `source_id` 不含 branch,多分支会互相覆盖混淆 | 🔴 |
| P3 | `documents` 表从不写 | 🟠 |
| P4 | 无精确符号索引(SCIP) | 🟡 |
| P5 | `include_dirs` 限定 docs/examples | 🟡 |
| P7 | 前后端 type 枚举不一致 | 🟡 |

---

## 3. 方案总览

**纯 RAG + SCIP 精确符号层 + 多分支全量 + 极保守排除 + GPU 并行索引**。

- 数据落点:**代码原文留文件系统(git 仓库)**,元数据/符号入 Postgres,向量入 Weaviate(职责分离)
- 配置:sync 切到读 DB;前端结构化表单(含分支多选、排除规则)
- 索引:多分支 checkout → 极保守过滤 → tree-sitter AST 分块(代码)/ 语义分块(Markdown)→ BGE-m3 GPU batch → Weaviate + documents 表
- 符号:SCIP indexer(优先)+ tree-sitter(兜底)→ PG `symbols` 表
- 检索:向量召回 + 符号精确/BM25 → RRF 融合 → reranker → 生成(带版本溯源)

---

## 4. 架构

### 4.1 索引侧

```
[Admin 结构化表单] ─POST─▶ Postgres data_sources 表
                                │  (sync 读 DB,废弃 YAML 运行时源 —— P1)
                                ▼
   本地 git 仓库(~/Documents/GitHub/ask-ai-corpus/)
     │  git pull 多分支增量
     ▼  对每个配置的分支 checkout:
   ┌──────────────────────────────────────────┐
   │  极保守过滤(P0,管理员可配)              │
   │  排:build/dist/node_modules/二进制/测试数据 │
   │  留:所有源码(含 vendor/CMSIS/Middlewares) │
   └──────────────────┬───────────────────────┘
                      │ 按扩展名路由
          ┌───────────┴────────────┐
        .md/.mdx              代码(.c/.rs/.py/.ts...)
          ▼                       ▼
   现有 chunk_document_semantic  tree-sitter AST 分块(P2)
                                   按函数/类/方法 + 签名摘要
          ▼                       ▼
          └───────────┬────────────┘
                      ▼
          BGE-m3 embed(GPU batch)
                      ▼
          ┌───────────┴────────────┐
          ▼                        ▼
   Weaviate(向量+chunk原文     Postgres documents 表(P3)
     + branch/version 元数据)    doc 级去重 + 文档列表
                      │
   并行:SCIP indexer(独立通路)→ Postgres symbols 表(P4)
```

### 4.2 检索侧(外部请求 → 答案)

```
/api/ask → intent(已有)→ query_rewrite(已有)
   → 混合检索:
       ├─ Weaviate 向量召回 top-K(可按 branch 过滤)
       └─ PG symbols 符号名精确/BM25(查询含标识符时)
     → RRF 融合(新)
   → rerank BGE-reranker-v2-m3(已有)→ pruner(已有)
   → DeepSeek 生成 → 答案 + 溯源(文件:行号 @ branch)
```

### 4.3 存储架构

#### 4.3.1 三类存储职责定位

| 存储 | 职责 | 存什么 | 不存什么 |
|---|---|---|---|
| **文件系统** | 完整原文 + 版本管理 | 代码(git)、文档原文、模型权重 | 结构化状态、向量 |
| **Postgres** | 结构化事实 + 状态 + 关系 | 配置、元数据、符号、日志、对话、用户、路由 | 完整原文、向量 |
| **Weaviate** | 语义向量检索 | chunk 向量 + 原文片段 + 元数据 | 完整文件、关系数据 |

原则:每份数据只存在最适合它的层,不重复;同一数据的不同表示分层(原文在 FS、片段在 Weaviate、元数据/符号在 PG)。**chunk 原文权威源是 Weaviate**(PG `documents` 只存 `chunk_count`,避免双写不一致)。

#### 4.3.2 全系统数据落点

| 数据 | 存储 | 容量 | 说明 |
|---|---|---|---|
| 代码原文(10 仓库多分支) | 文件系统 git | 1.8GB | corpus,git 管版本/增量 |
| 知识库文档原文 | 文件系统 | 数十 MB | `Knowledge/知识库/` |
| 模型权重(BGE-m3 + reranker) | 文件系统 `models/` | ~2–3GB | embedding/rerank |
| chunk 向量 + 片段 | Weaviate | 3–5GB | 多分支全量,检索+生成 |
| 文档元数据 | PG `documents` | ~50MB | 索引状态/去重/branch |
| 符号 | PG `symbols` | ~50MB | SCIP/tree-sitter 提取 |
| 数据源配置 | PG `data_sources` | <1MB | 管理员配 |
| 同步日志 | PG `sync_log` | 增长 | 每次同步一行 |
| 对话记录 | PG `conversations` | 几 GB/年 | 含 Phase2/3 字段,主要增长项 |
| 点击/定制/覆盖/聚类 | PG 4 表 | <10MB | 运行时 |
| 用户 / LLM 配置路由 | PG 3 表 | <1MB | 系统 |

#### 4.3.3 Postgres 内部分工(12 表分 3 组)

| 组 | 表 | 维护方 |
|---|---|---|
| **索引组** | `documents` `symbols`(新) `data_sources` `sync_log` | 索引管道 |
| **运行时组** | `conversations` `source_clicks` `answer_overrides` `customizations` `customization_bindings` `question_clusters` | 查询时读写 |
| **系统组** | `users` `llm_providers` `llm_routing` | 管理后台 |

#### 4.3.4 容量汇总

| 存储 | 容量 |
|---|---|
| 文件系统(corpus + models + 知识库) | ~5GB |
| Weaviate | 3–5GB |
| Postgres | 当前 <1GB,长期几 GB(对话/日志) |
| **总计** | **<15GB**(磁盘 2TB,无压力) |

#### 4.3.5 部署拓扑

**方案 A:全在一台 GPU 服务器**(索引 + 在线检索 + PG/Weaviate + corpus 同机)。

- 索引(BGE-m3 GPU batch + SCIP)与在线检索(FastAPI)共享同机的 PG/Weaviate/corpus
- 适合当前规模(<15GB 数据、单实例服务),最简运维
- docker-compose 统一编排(postgres + weaviate + backend + corpus volume)
- 后续若高并发,再拆分索引机与在线机、PG/Weaviate 中心化(过渡到 B/C 拓扑)

#### 4.3.6 备份策略

- **文件系统**:git 远程天然备份;corpus 丢了重新 clone;models 可重下
- **Postgres**:`pg_dump` 定期(配置 + 元数据 + 符号 + 对话,**最重要**,难重建)
- **Weaviate**:可从 PG + FS 重建(重新 embedding),非首要;或 volume 快照

---

## 5. 配置子系统(P1 / P6 / P7)

### 5.1 sync 读 DB(P1)

- `scripts/sync.py` 与 `trigger_sync` 改为从 Postgres `data_sources` 表读配置(不再读 YAML)
- YAML 降级为首次 seed(复用 `scripts/migrate_yaml_to_db.py`)
- `DataSource` ORM → `SourceConfig` 转换器

### 5.2 前端结构化表单(P6)

重做 `admin/src/pages/DataSources.tsx` 表单,按 `type` 动态展开字段:

- **通用**:id、type、product、enabled、sync_interval
- **github**:owner、repo、**branches(多选)**、token(复用全局)
- **filesystem**:root_path、**branches(不适用,隐藏)**
- **范围与排除**(所有类型):include_dirs、file_types、exclude_dirs、exclude_regex、max_file_size
- 补**编辑**与**删除** UI(hook 已有,接上)

branches 字段:新建数据源时,后端提供一个 `GET /data-sources/preview-branches`(传 owner/repo/token)拉远程分支列表供前端多选;默认勾选所有非开发/构建分支。

### 5.3 枚举对齐(P7)

前端 type 枚举收敛为后端实际注册的 `github` / `filesystem`(移除 `web_crawl`/`sdk` 或后端补注册)。

---

## 6. 代码索引核心

### 6.1 多分支(P8)

- **`source_id` 加 branch**:`{owner}/{repo}/{branch}/{path}`(原 `{owner}/{repo}/{path}`)
- **chunk 元数据加 branch**:Weaviate property 增 `branch`(TEXT);`Document.metadata_` 增 `branch`
- **检索按版本过滤**:用户可指定 branch,或返回时标注来源分支
- 同步流程:对配置的每个分支 `git checkout` 后独立索引一遍,source_id 天然区分

### 6.2 分块路由(P2)

新增 `tree-sitter` 分块器,按文件扩展名路由:

- `.md/.mdx` → 现有 `chunk_document_semantic`(Markdown 语义分块,保留)
- 代码(.c/.h/.cpp/.rs/.py/.ts/.tsx/.js/.sh...) → **tree-sitter AST 分块**(新)
  - 按函数/类/方法边界切,跨语言的语法解析
  - 每个 code chunk 前拼**上下文摘要**:`// repo @ branch > file_path > Class::method(签名)`,弥补无上下文时 embedding 质量损失
  - 复用现有 `Chunk.chunk_type="code"` 字段

### 6.3 极保守排除(P0,管理员可配)

**默认排除**(确定无疑的非源码):
- 目录:`build/ dist/ node_modules/ __pycache__/ target/ out/ .git/ .next/ .venv/ .idea/ .vscode/`
- 二进制:图片(`.png/.jpg/.gif/.svg/.webp`)、音频(`.wav/.mp3`)、视频、固件(`.bin/.elf/.hex`)、压缩包
- 纯测试数据文件:`exclude_regex` 默认含 `wave_.*\.c$`、`*_tables\.c$` 类生成查找表(管理员可调)

**保留**:所有源码(含 CMSIS / Middlewares / Drivers / Lib / vendor SDK / ATON)。

**管理员可配**(P6 表单字段):`exclude_dirs`、`exclude_regex`、`max_file_size`(默认 2MB,超过的代码文件单独标记或按需排除)。

**灰色地带**:超大生成查找表(如 `arm_common_tables.c` 4.7MB)按"别排除有用内容"原则**默认保留**,管理员可通过 `max_file_size` 调整。

### 6.4 GPU batch embedding

- BGE-m3 在 GPU 服务器上 batch 推理(批量 32/64),跨源跨分支并行
- 索引 worker 与在线检索后端可同机或分机(通过共享 Weaviate 解耦)

---

## 7. 符号层(SCIP 优先 + tree-sitter 兜底)

### 7.1 策略

| 语言 | 工具 | 精度 | 状态 |
|---|---|---|---|
| Python | scip-python | 精确(def+ref) | ✅ 成熟 |
| TypeScript/JavaScript | scip-typescript | 精确(def+ref) | ✅ 成熟 |
| Rust | scip-rust(基于 rust-analyzer) | 精确(def+ref) | ✅ 需项目能 cargo check |
| C/C++ | scip-clang | 精确(def+ref) | ⚠️ 需 `compile_commands.json` |
| Shell / BitBake | tree-sitter | 定义级符号 | 🟡 SCIP 不支持,兜底 |

### 7.2 C/C++ 高风险 spike

scip-clang 需要每个项目的 `compile_commands.json`:
- **lowpower_camera(ESP-IDF)**:`idf.py` 可生成,相对可行
- **ne301(STM32 CubeIDE/CubeMX)**:CubeIDE 是 Eclipse-based,生成 `compile_commands.json` 较折腾(需 Bear 拦截 make 或导出 CMake);工具链路径(arm-none-eabi-gcc)可能让 clang 解析出错

**落地**:C/C++ 尽力生成 `compile_commands.json` 跑 scip-clang;**失败则 tree-sitter 提取定义级符号兜底**(每语言用能拿到的最精确符号,这是"一步到位"的务实实现)。C/C++ 的 `compile_commands.json` 列为**实现期高风险 spike**,需先验证 ne301 能否生成。

### 7.3 symbols 表(PG,新)

```
symbols(
  id UUID PK,
  source_id TEXT,        -- {owner}/{repo}/{branch}/{path},关联 documents
  symbol_name TEXT,
  symbol_kind TEXT,      -- function/class/method/variable/definition/reference
  file_path TEXT,
  branch TEXT,
  line_start INT, line_end INT,
  signature TEXT,
  language TEXT,
  content_hash TEXT,
  INDEX(symbol_name), INDEX(source_id)
)
```

符号检索用 PG `pg_trgm` / 全文索引做符号名精确 + 模糊匹配。

---

## 8. 混合检索

- **向量召回**:Weaviate top-K(支持按 `branch` 过滤)
- **符号精确/BM25**:PG `symbols` 表,当查询含标识符(驼峰/下划线词)时触发
- **RRF 融合**(Reciprocal Rank Fusion):无需调参,鲁棒合并两路结果
- **rerank**:BGE-reranker-v2-m3(已有)
- **版本过滤/标注**:返回 chunk 带分支标签,答案溯源含 `文件:行号 @ branch`

---

## 9. documents 表启用(P3)

- `scripts/sync.py` 与 `trigger_sync` 构造 `IngestionPipeline` 时传入同步 `session_factory`(当前漏传)
- `documents` 表增 `branch` 字段;doc 级去重键含 branch
- 供 admin 文档列表、去重统计、增量对比使用

---

## 10. 并行索引架构

- 跨数据源 + 跨分支并发(当前串行)
- GPU batch embedding
- 任务调度:首期用 `concurrent.futures.ProcessPoolExecutor` + GPU batch(轻量,无新依赖);若需持久化队列/跨机,后续引入 Arq + Redis
- 单源/单文件/单符号失败不中断批次(沿用现有错误隔离)

---

## 11. 错误处理

- **单文件**抓取/分块/embedding 失败 → warning 跳过,不中断批次(沿用)
- **SCIP indexer** 失败 → 该语言/该源 fallback tree-sitter,记录到 SyncLog
- **C/C++ compile_commands.json 缺失/失败** → tree-sitter 兜底,SyncLog 标注降级
- **git pull 失败** → 该源标 failed,不影响其他源
- **Weaviate 写入**单 chunk 失败 → warning 继续(沿用)

---

## 12. 测试策略

- **单元**:tree-sitter 分块器(各语言函数/类边界)、极保守排除规则、source_id 多分支构造、RRF 融合、SCIP→symbols 解析
- **集成**:多分支全量索引(ne301/lowpower_camera 样本)→ 检索 → 验证召回与版本标注
- **回归**:现有 Markdown 索引/检索不退化(chunk 路由正确分流)
- **性能**:20–30 万 chunk 全量索引耗时与 Weaviate 存储符合预估
- C/C++ SCIP spike 单独验证(能否生成 compile_commands.json、scip-clang 能否解析)

---

## 13. Scope 风险与实现顺序

**风险**:用户选择"一次全做",工程量大。核心风险点:
1. **C/C++ SCIP**(compile_commands.json 生成,嵌入式固件高难度)
2. **tree-sitter 多语言覆盖**(C/C++/Rust/Python/TS/JS/Shell 语法)
3. **多分支索引量**(20–30 万 chunk,GPU 索引时间 + Weaviate 存储验证)

**建议实现顺序**(spec 内不分阶段,但实现按此推进降低风险):
1. P1 配置统一(sync 读 DB)+ P6 前端表单 + P7 枚举对齐
2. P8 多分支 source_id + P0 极保守排除 + P2 tree-sitter 分块
3. P3 documents 表启用
4. GPU 并行索引架构
5. P4 SCIP 符号层(SCIP 优先 + tree-sitter 兜底,含 C/C++ spike)
6. 混合检索 + RRF + 版本过滤
7. 端到端验证(用 ne301/lowpower_camera 多分支真实数据)

---

## 14. 附录:侦察规模报告(2026-07-31 实测)

### 14.1 各仓库单分支规模

| 仓库 | 代码文件 | 代码 LOC | 文档文件 | 文档 LOC |
|---|---:|---:|---:|---:|
| ne301 | 5,870 | 2,990,181 | 260 | 29,088 |
| lowpower_camera | 2,297 | 1,056,736 | 536 | 25,343 |
| NeoMind | 947 | 388,126 | 30 | 12,808 |
| NeoMind-Extensions | 462 | 148,868 | 130 | 39,355 |
| AIToolStack | 58 | 33,085 | 7 | 1,318 |
| wiki-documents | 20 | 2,250 | 343 | 93,345 |
| 其余 4 个 | 52 | ~22K | 16 | ~3K |
| **合计** | **9,706** | **4,641,111** | **1,322** | **204,490** |

### 14.2 语言分布(单分支 LOC)

```
.c    2,701,731  (5065 文件)
.h    1,230,547  (2643 文件)
.rs     355,439  ( 758 文件)
.tsx    139,290  ( 387 文件)
.py     118,180  ( 329 文件)
.ts      49,855  ( 318 文件)
.cpp     17,071  (  54 文件)
.js      15,535  (  50 文件)
.sh       7,884  (  61 文件)
.hpp      5,579  (  41 文件)
```

### 14.3 分支清单

| 仓库 | 索引分支 | 排除分支 |
|---|---|---|
| ne301 | main, v2.3.0-beta, stedgeai-v2.2, stedgeai-v4.0, stedgeai-variant-unify, halow, ir-ver | — |
| lowpower_camera | flash_8M, hw-v1.2, hw-v2.0 | — |
| wiki-documents | main | gh-pages(构建)、feat/*、docs/*(未发布) |
| 其余 | main | — |

### 14.4 索引成本估算(多分支全量)

- chunk / 向量数:**20–30 万**
- BGE-m3 T4 索引:**15–25 分钟**
- Weaviate 存储:**3–5 GB**(含 HNSW 索引开销)
- symbols 表:**~10 万+ 行 ≈ 50 MB**

### 14.5 最大代码文件(>200KB,需关注分块/排除配置)

```
4.7MB .c  ne301/Drivers/CMSIS/DSP/Source/CommonTables/arm_common_tables.c   (CMSIS 查找表)
3.5MB .h  ne301/.../STM32N6xx/Include/stm32n657xx.h                          (ST 寄存器定义)
3.4MB .h  ne301/Middlewares/ST/stedgeai-lib-2.2/.../ATON.h                   (NPU,多版本)
2.4MB .h  ne301/Middlewares/ST/stedgeai-lib-4.0/.../ATON.h
1.0MB .c  lowpower_camera/.../usb_stream/test_apps/.../wave_1ch_16bits.c     (音频测试数据,默认排除)
0.9MB .c  ne301/.../Lib/mongoose/mongoose.c                                  (第三方 web 库)
```
