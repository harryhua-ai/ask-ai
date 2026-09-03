# CamThink V1 — Data Source Center
# Shared Discovery(#16 Git 智能配置 / #17 网站自动发现 / #18 非阻塞删除)

- **日期**:2026-09-03
- **执行模式**:SINGLE EXECUTOR — DISCOVERY ONLY(CODE_MUTATION = NONE,PRODUCTION_MUTATIONS = NONE)
- **仓库**:harryhua-ai/ask-ai(本地 `/Users/harryhua/Documents/GitHub/ask-ai`);报告入 docs 独立仓
- **覆盖 Issue**:#16(Git repository intelligent setup)/ #17(Website automatic discovery)/ #18(Non-blocking deletion)
- **用途**:为 Data Source Center 统一 Product/Engineering Contract 冻结发现结论,供 Planner 拍板后并行实现
- **姊妹报告**:Worktree-1《RELIABILITY & OBSERVABILITY Shared Discovery》(docs 仓 c9ef948,#9-#15)——本轮**不复制**其 operation truth 契约,仅提接口需求(§16)

---

## 1. Executive Summary

**结论:READY_FOR_PARALLEL_IMPLEMENTATION(THREE_WAY,前置一个小型 Shared Foundation S0)。**

核心事实:

1. **推荐引擎的地基已经存在,不需要新建**。阶段1 交付的 `backend/connectors/safety.py` 已实现三层准入中的前两层领域原语:`TechnicalSafetyPolicy.check_path / check_content`(Layer 1,不可绕过)+ `classify_role / recommendation_for`(Layer 2,include/exclude/review 推荐)+ `FileAdmission` machine-readable 结构(字段注释明文写着"阶段6 Admin Repository Scan 将消费")。#16/#17 的 Discovery 本质 = 给这个已冻结的原语**接上数据源**(GitHub trees API / sitemap 枚举),再包一层聚合与 human-readable reason。
2. **#16 的关键裁决:推荐是 UX 时态的翻译层,不是新的同步语义**。Discovery 推荐最终编译回**现有 config JSONB 词表**(`file_types` / `exclude_dirs` / `branches`),`scripts/sync.py` 与全部 connector **零改动**即可消费。"用户填 URL+分支" → 系统扫描 → 管理员确认 → 落库的仍是今天的 config 形态。当前体验的反向问题已实证:前端「拉取分支」后把仓库**全部后缀自动填进 `file_types` 让用户手动删**(`DataSources.tsx:579-585`),这正是要反转的模型。
3. **#17 冻结能力边界时发现一个必须显式标记的缺口**:web_crawl 的 sitemap 发现是 **Yoast WordPress 专用**——只认子表名匹配 `/(post|page|product)-sitemap/` 的索引(`web_crawl.py:67`),无 robots.txt `Sitemap:` 指令发现、无通用 `/sitemap.xml` 回退;非 Yoast 站点会得到 **discovered=0 且静默 SUCCESS**(与 09-02 可靠性 Discovery 的「空 sitemap 判完整」P0 候选同根)。#17 的 auto-discovery 不是产品愿景,是补齐 V1 自己承诺过的能力。
4. **#18 根因实锤且代价被低估**:`DELETE /data-sources/{id}`(`data_sources.py:458-517`)在请求内同步完成全部清理,其中 `_purge_source_corpus_sync` 的孤儿段+验证段是**两次 Weaviate 全类迭代器扫描**(生产存量 207,294 对象级)——删除耗时 O(全库语料) 而非 O(该源语料)。且删除**无任何持久化状态**(无 DELETING/FAILED 标记),refresh 后界面完全不知道删除在进行;**与在途同步零互斥**(删除中同步重灌 → ghost 语料的竞态窗口)。而阶段⑨ 的手动同步 202+交接表已经给了现成的非阻塞模板。
5. **跨波碰撞面已识别**:Worktree-1 的 W2 拥有 `data_sources.py` / `schemas.py` hunk(sync-status 挂载);本轮 C1/C2 的 preview 端点与 C3 的删除状态字段也落在这两个文件。两个 wave 都未实现,需 Planner 裁定合并次序(建议 W0 波先合,本轮 rebase,见 §18/§19)。
6. **新发现的信任边界缺口(本轮唯一超出三 Issue 的事实)**:全链路**无任何 secrets 文件防线**——`safety.py` 与 `exclusion.py` 均无 `.env` / `.pem` / `.key` 类排除;叠加 C10 的"全后缀自动填充",含密钥仓库的 `.env` 会被**默认推荐纳入知识库**。修复建议已写入契约(§10),是否升 Layer 1 硬禁列为 PD 待拍板。

---

## 2. Discovery Baseline

```
DISCOVERY_BASELINE = 1d6f6b5(本地 main HEAD,= origin/main,三候选集成后权威主干)
```

- 与 Worktree-1 W0 报告同基线(1d6f6b5),两波发现可直接拼接。
- 证据方法:本地源码通读(backend connectors / api / services / pipeline / scripts / deploy / admin 前端全链路)+ 既有 docs 报告交叉引用;**零代码改动、零生产接触、零网络抓取**(GitHub/网站能力均以代码实证为准,不做线上验证)。

---

## 3. Current Source Architecture(真实链路)

### 3.1 存储

| 表 | 职责 | 关键列 |
|---|---|---|
| `data_sources`(`models.py:194-204`) | 源配置唯一权威(Task 7 起,DB 替代 YAML) | `id, type, product, enabled, config(JSONB), sync_interval`;**无任何生命周期状态列** |
| `documents`(`models.py:41-66`) | 已灌入文档账本 | `(content_hash, branch)` 复合主键;`source_id` 前缀 = 源的成员身份 |
| `sync_requests`(`models.py:207-245`) | 执行交接(阶段⑨/⑩,语义冻结) | backend 写 pending → sync-executor 领用 |
| `sync_runs`(`models.py:248-300`) | 运行遥测(Wave-0,Worktree-1 领域) | ONE SOURCE × ONE ATTEMPT |
| `sync_log`(`models.py:176-191`) | 业务历史结局 | status/items_*/error_detail |

connector 全部参数(含 clone_path/file_types/base_url/sitemap_url 等)都装在 `config` JSONB 里,**服务端零 schema 校验**(`DataSourceCreate.config: dict`,`schemas.py:67`)。`local_git` 已降为实现细节未注册(`local_git.py:32`),但创建 schema 的 type 枚举仍容忍 `local_git|sdk` 遗留值(`schemas.py:64`)。

### 3.2 配置 → 执行

`db_adapter.to_source_config`(`db_adapter.py:14-40`)把 ORM 行转 frozen `SourceConfig`,`branches` 与 `channel_visibility` 从 config JSONB 提取(`channel_visibility` 前端完全没有入口,仅 DB/API 层存在)。三个执行面共用同一个 runner `scripts/sync.py`:

| 执行面 | 触发 | 特征 |
|---|---|---|
| `sync-cron` 容器 | `while true; do python3 scripts/sync.py || true; sleep 3600; done`(`deploy/prod/docker-compose.yml:130-137`) | 每小时直跑,**不经过 sync_requests**(NULL request_id);每次循环开始时从 DB 重读 enabled 源 |
| `sync-executor` 容器 | 领用 `sync_requests`(FOR UPDATE SKIP LOCKED)→ 子进程 `sync.py --source X` | 手动同步专用,串行,容器级隔离(阶段⑨) |
| `sync` 容器 | 一次性手动(全量/reindex) | `restart: "no"` |

`_load_configs_from_db`(`sync.py:112-129`)在**每次 run 启动时**读 `enabled=true` 的源——这是理解删除竞态(§11)的关键:运行中的 run 对"源已被删"毫无感知。

### 3.3 Admin API 面(`backend/api/admin/data_sources.py`)

`list / create / patch / delete / {id}/upload / {id}/sync(202) / sync-all(202) / preview-dirs / preview-branches / preview-file-types`。角色:读=viewer+,写=admin/editor。同步已是"202 交接 + 前端 5s 轮询 last_sync"非阻塞模型;**删除是唯一还卡在同步模型上的写操作**。

### 3.4 前端(`admin/src/pages/DataSources.tsx`,1174 行)

单页单表单(react-hook-form + zod),仅有一个「高级选项」折叠区(github/filesystem 的 exclude_regex + max_file_size);github「拉取分支」按钮消费 `preview-branches`(分支勾选栅格)+ 自动调 `preview-file-types` 把全后缀灌进 `file_types` 输入框;filesystem 的 `include_dirs` 走 `DirPicker` 两级勾选树(消费 `preview-dirs`);删除 = `window.confirm` + 全局禁用删除钮,无进度、无失败 toast、成功才刷缓存;web_crawl 表单仅 4 字段(base_url 必填 + sitemap_url/exclude_patterns/crawl_delay_ms),`max_pages`/`min_content_chars` 无入口。admin 侧已有 `DataSources.test.tsx` 测试脚手架(W0 报告 §5.2)。

---

## 4. Git Current State(#16 现状)

| 调查项 | 现状(实证) |
|---|---|
| clone_path 是否必须用户提供 | **否**。缺省 `~/ask-ai-corpus/<repo>`(`github.py:68-71`);但表单仍暴露该字段,且同仓库第二源未显式配置不同 clone_path 时 409(`data_sources.py:204-234`)。属于实现细节泄漏给用户 |
| clone/fetch 机制 | 首次 `git clone --branch`;增量 = API SHA 感知短路 + `fetch` + `reset --hard origin/<branch>`(决策 3A);恢复重放 F16 旁路 SHA 短路;token 最小权限启动校验(`github.py:363-405`),错误信息全脱敏(C10) |
| file_types 语义 | 扩展名白名单,connector 缺省 `[".py"]`(`github.py:67`);前端 C10 已改为拉分支后**自动填全部后缀**——白名单语义从"用户选择知识范围"退化为"用户手工修剪垃圾清单" |
| exclude_dirs / exclude_regex / max_file_size | `ExclusionPolicy`(`exclusion.py`):BUILD_DIRS 硬目录集 + BINARY_EXT + `._*` AppleDouble + 用户目录/正则;max_file_size 仅限非源码 |
| include_dirs | **github 不支持**(仅 filesystem 有前缀白名单,`filesystem.py:55`) |
| Technical Safety 执行点 | Layer 1 `check_path`(扩展名类+尺寸)在 connector 读文件**之前**(`github.py:226-229`);Layer 1 `check_content`(NUL/控制字符/解码质量嗅探)在 ingest(`ingest.py:230,487`)。管理员配置不可绕过(G1 红线) |
| repo scan 可复用能力 | `preview-file-types`(`data_sources.py:578-607`)已用 GitHub trees API `recursive=1` 全量列举文件树——但只聚合了**后缀去重**,丢弃了 trees API 自带的 `size` 字段与路径结构 |
| 低成本 extension/type discovery | trees API 单次调用即可拿到 (path, size) 全集 → 叠加 `check_path + classify_role` 即完成**无 clone、不读内容**的整仓推荐扫描。这是 #16 Discovery 的实现基石 |
| recommendation preview 能否不 ingest | **能**(路径级)。内容嗅探(check_content)需要读文件;V1 用"抽样 blob 内容"可选增强,trees API 不含内容 |
| secrets/private files 处理 | **无专门防线**(缺口,见 §10)。`.env` 等只要在后缀白名单内即通过全部三层;GITHUB_TOKEN 只读校验是唯一相关机制 |
| images/PDF/HTML 真实能力 | 全后端**无任何 PDF/OCR/HTML 专用解析库**(pypdf/bs4/markitdown 零命中)。`.png/.pdf/.zip` 等被 BINARY_EXT/safety 拦(诚实);`.html` 会被当纯文本读入(噪音,不诚实);git 源内 `.md/.rst/.txt` 是唯一被结构化对待的文档形态 |

---

## 5. Git Target Contract(#16 目标契约)

### 5.1 Simple Mode(普通管理员唯一可见路径)

```
输入:Repository URL + Branch(可多选,缺省=远端默认分支)+ Source/Product identity
  → [Discovery](按钮触发,秒级:trees API 单调用)
  → Discovery Result(聚合视图:按知识角色/顶层目录汇总,附 recommended scope)
  → 管理员确认/微调(按目录或按角色勾选;secrets/二进制默认不可纳入)
  → 创建源(config = 编译后的现有词表)
  → Sync(现有链路,零改动)
```

clone_path、binary blacklist、build dirs、node_modules、vendor、cache、model artifacts **一律不出现**在 Simple Mode。Technical Safety 不可绕过性不变。

### 5.2 Advanced Mode

= 现有表单全量字段(clone_path / exclude_dirs / exclude_regex / max_file_size / 手工 file_types)。供 expert 管理员覆盖推荐结果;推荐结果预填后仍可进入 Advanced 微调(Simple 是 Advanced 的预编译态,不是两个世界)。

### 5.3 Discovery Result Contract(新端点返回结构,机器可读)

```jsonc
POST /api/admin/data-sources/preview/github-discovery
{ "repo_url": "...", "branch": "main" }
→ {
  "kind": "github",
  "target": { "owner": "...", "repo": "...", "branch": "..." },
  "totals": { "files": 1488, "safe_files": 1204, "excluded_unsafe": 12,
               "total_size_bytes": ..., "scanned_at": "..." },
  "by_role": {  // KnowledgeRole → 聚合(角色词表复用 safety.py,零新词)
    "technical_doc": { "count": 210, "size": ..., "recommendation": "include" },
    "vendor":        { "count": 892, "size": ..., "recommendation": "exclude" },
    "binary":        { "count": 12,  "size": ..., "recommendation": "exclude" },
    "secret_candidate": { "count": 3, "recommendation": "exclude" }   // 见 §10
  },
  "top_dirs": [ // 顶层目录卷积,供确认 UI 主视图(封顶 MAX_TOP_DIRS 复用 100)
    { "dir": "docs", "count": 128, "recommendation": "include",
      "sample": ["docs/quickstart.md", "..."] },
    { "dir": "vendor", "count": 892, "recommendation": "exclude", "sample": [] } ],
  "candidates": [ /* FileAdmission[](逐文件,封顶+分页,字段=safety.py:223-235 冻结结构) */ ],
  "recommended_config": {   // ★ 编译产物 = 现有 config 词表,sync 零改动
    "file_types": [".md", ".py", ".c", ".h", ".yaml"],
    "exclude_dirs": ["vendor", "build", "examples/bin"],
    "branches": ["main"]
  },
  "warnings": [ "检测到 3 个疑似密钥文件(.env 等),已默认排除",
                 "12 个文件超过 1MB,进入 review" ],
  "capability_notes": [ "html/svg 等 46 个文件当前 ingestion 仅可按纯文本处理,已推荐排除" ]
}
```

### 5.4 Recommendation Contract(逐文件)

复用 `FileAdmission` 冻结字段:`{path, size, technical_safe, technical_reason, knowledge_role, recommendation(include|exclude|review), policy_result, eligible}` + 新增一个人读字段 `reason_zh`(从 technical_reason/knowledge_role 派生的固定文案,枚举映射,不做自由文本生成)。**recommendation 三态语义**(冻结):
- `include`:角色 ∈ RECOMMENDED_INCLUDE_ROLES 且 technical_safe;
- `exclude`:technical_unsafe(不可纳入,红线)∨ 角色 ∈ RECOMMENDED_EXCLUDE_ROLES ∨ secret_candidate;
- `review`:超 review 尺寸阈值(1MB)、`.example` 类疑似密钥模板、其它无法确信的形态。管理员可把 review→include(技术安全边界内),不可把 unsafe→include。

### 5.5 能力诚实矩阵(冻结:UI 不得声称超出此表的支持)

| 形态 | 真实能力 | Discovery 处置 |
|---|---|---|
| .md/.rst/.txt/.adoc | 文本直读 | include 推荐 |
| 源码/脚本/配置(.py/.c/.h/.ts/.yaml/...) | 文本直读,code chunker | include 推荐 |
| .png/.jpg/.pdf/.zip/.hef/模型工件 | **不可处理**(safety/BINARY_EXT 拦截) | exclude(technical_reason 可见),UI 不提供纳入选项 |
| .html/.svg | 仅按纯文本读入(无抽取) | exclude 推荐 + capability_note 说明原因 |
| .env/.pem/.key | 文本可读但**不得入知识库**(信任边界) | secret_candidate:exclude(V1 默认;是否 Layer 1 硬禁列 = PD-1) |

---

## 6. Website Current State(#17 现状)

| 调查项 | 现状(实证,`web_crawl.py`) | 判定 |
|---|---|---|
| sitemap 配置/读取 | `sitemap_url` 缺省 `{base}/sitemap_index.xml`;索引解析通用(`parse_sitemap_index`) | HAVE |
| sitemap 子表选择 | **只保留路径匹配 `/(post\|page\|product)-sitemap/` 的子表**(`_SITEMAP_KIND_RE:67`,`_sitemap_entries:469-488`) | **Yoast 专用**,非通用 |
| 通用 sitemap.xml 回退 | **无**。站点只有 `/sitemap.xml`(urlset)时:GET sitemap_index 得 urlset → `parse_sitemap_index` 返回 [] → **discovered=0 → fetch_all 空转 → SUCCESS**(与 09-02「空 sitemap 判完整→孤儿批量退休」P0 候选同根) | **NEW(缺陷修复级)** |
| robots.txt | Disallow 前缀(具名组优先,`*` 回退);**`Sitemap:` 指令被忽略**;Allow/Crawl-delay 被忽略;robots 不可得=全允许 | HAVE(+NEW:读 Sitemap: 指令) |
| sitemap auto-discovery | 无(见上两行) | NEW |
| sitemap index / multiple sitemap | index 支持(受 Yoast 过滤限制);多子表合并去重支持 | HAVE(去专用化=NEW) |
| internal link crawling | BFS 同域链接发现,增量上限 `max_pages`(缺省 150)叠加在 sitemap 视野之上 | HAVE |
| domain/subdomain boundary | `canonical_url` host 严格相等 → **子域一律外域**(`resources.camthink.ai` 不可达) | HAVE(子域策略=NEW,Advanced) |
| redirects | requests 默认跟随;无 redirect 链规范化 | HAVE(消极) |
| canonical URLs | 仅 URL 形态规范化(去 query/fragment、host 小写、压缩 //、尾斜杠);**不解析 `<link rel=canonical>`**、不查 noindex | HAVE(HTML 级 canonical/noindex=NEW 可选) |
| query parameter handling | 一律剥离(内容页假设) | HAVE |
| dedupe | `_seen_urls` 规范形态集合 | HAVE |
| JS-rendered pages | **无**(纯 HTTP;SSR 站点契约已签,C8) | 冻结不支持(V1) |
| extraction | stdlib HTMLParser → Markdown;优先 main/article;剥 nav/footer/script/cookie 条 | HAVE |
| empty/low-content filtering | `min_content_chars` 缺省 200,计入 `rejected.low_content` | HAVE |
| PDF/images | 链接层扩展名跳表 `_SKIP_HREF_EXTS`;sitemap 里的 PDF 会被当 HTML 抓→失败/薄内容;**无 PDF ingestion** | 冻结不支持(V1) |
| noindex | 不检查 | NEW 可选 |
| rate limiting | 固定 `crawl_delay_ms`(缺省 500ms,页面间+子表间);**不读 robots Crawl-delay** | HAVE(Crawl-delay=NEW 可选) |
| max pages/depth | 页数上限(max_pages);无深度语义 | HAVE |
| 记账 | `run_stats`:discovered/accepted/extracted/failed/rejected{exclude,robots,low_content} + rejected_urls 证据(cap 500) | HAVE(Discovery preview 的现成记账骨架) |

**发现类缺口汇总(#17 真正要新建的)**:① robots `Sitemap:` 指令发现;② 通用 urlset 直取回退(/sitemap.xml 候选序列);③ 子表正则从**过滤器降级为偏好**(非 Yoast 子表名照收);④ URL 级 Discovery preview 端点(robots+sitemap 枚举+排除规则+规范化 → 逐 URL 分类,**不抓页面**);⑤ 空/零 sitemap 显式告警(Discovery 与 sync 双侧)。其余全部为已有能力的重包装。

---

## 7. Website Target Contract(#17 目标契约)

### 7.1 普通 UX(冻结产品方向)

```
输入:Website URL(唯一必填)
  → [Discovery](robots + sitemap 枚举,秒级~十秒级;不抓正文)
  → Preview(推荐纳入/排除/待审 三态清单 + 计数 + 理由)
  → Confirm(可微调排除清单)
  → Sync(现有链路)
```

"不要输入大型网站 URL 后立刻无边界 embed 全站"已由现有双保险满足:Discovery 阶段零 embed;Sync 阶段 sitemap 视野 + max_pages 封顶。**Discovery 优先知识类别映射**(path 语义 → KnowledgeRole,复用同一词表):product/specification/documentation/guide/FAQ(→product_doc / technical_doc / troubleshooting)/ API/SDK(→api_reference)/ support/solution(→technical_doc);低价值默认排除:login/register/account/search/cart/checkout/user-center(**`DEFAULT_EXCLUDE_PATTERNS:47-60` 已覆盖绝大多数,仅需补充 register/search/tag/archive**)、query 变体(已由规范化剥离)、空/模板页(low_content 阈值)、不支持的二进制资产(扩展名跳表)。

### 7.2 Sitemap URL / crawl delay / include-exclude / query / subdomain / depth → Advanced Mode

全部进高级折叠区(与 github/filesystem 的 Advanced 同一交互模式)。V1 冻结:无 JS 渲染、无 PDF/OCR、单主域、页数上限保留、crawl delay 固定值域(≥200ms,防压制站点)。

### 7.3 Discovery Result Contract(web 版)

与 §5.3 同构(同一 envelope):`kind="web_crawl"`;`by_role` 换成 URL 分类聚合;`top_dirs` 换成 `top_path_prefixes`(如 `/products/` 31 URL include、`/store/` 已排除);`candidates` = URL 级 admission(`{url, recommendation, reason_zh, lastmod?}`);`recommended_config` = `{base_url, exclude_patterns, sitemap_url?}`(仍是现有词表);`warnings` 必含空 sitemap 检出(`discovered=0 → "未发现任何 sitemap,请检查站点地址或手填 sitemap_url"`)。内容级(薄内容)判定**不在 preview 承诺**——如实标注"正文质量在 Sync 后由 run_stats 呈现",preview 可选抽样 N 页增强(标记为 sample,非全量承诺)。

---

## 8. Unified Source Intelligence Model(统一模型)

**不建立两套产品模型。** Git 与 Website 共享同一条流水线,差异只在 Candidate 的产生器:

```
┌─ Candidate Producer ──────────────────────────────┐
│ github: GitHub trees API(path, size)逐 blob      │
│ web_crawl: robots + sitemap 枚举 + URL 规范化逐 URL │
└──────────────┬────────────────────────────────────┘
               ▼
  ① Technical Safety(Layer 1,check_path;不可绕过)
               ▼
  ② Knowledge Role(Layer 2,classify_role / URL path 分类)
               ▼
  ③ Source Policy(file_types / include_dirs / exclude_patterns —— 第三层准入,管理员意志)
               ▼
  ④ Recommendation(include | exclude | review)
               ▼
  ⑤ Reason(枚举 → 固定 zh 文案)
```

代码落点:**一个共享服务模块** `backend/services/source_discovery.py`(S0,见 §18),内含 (a) DiscoveryCandidate envelope + 聚合器(by_role/top_dirs/candidates 封顶);(b) github producer(trees API,复用 `_fetch_github_branches` 的 token 处理);(c) web producer(复用 `parse_robots_disallows / parse_sitemap_index / parse_urlset / canonical_url / DEFAULT_EXCLUDE_PATTERNS` 纯函数——它们已是模块级可导入函数,零重构);(d) URL 级 admission 原语(与 FileAdmission 同构的 `UrlAdmission`,字段对齐)。producer 都不触碰 connector 实例与 ingest。

---

## 9. Knowledge Recommendation Contract

三层准入(产品合同 v1.1)**不新增不变量**,Discovery 是它的预演视图:

- `最终准入 = TECHNICALLY_SAFE ∧ KNOWLEDGE_ELIGIBLE ∧ SOURCE_POLICY_ALLOWED` —— preview 中 technical_unsafe 的候选永远 `eligible=false` 且不可被管理员翻转;
- 推荐词表复用 `KnowledgeRole` 12 值 + `RECOMMENDED_INCLUDE/EXCLUDE_ROLES`(`safety.py:115-151`),git 与 web 共用;web 的 FAQ/product 页映射进既有角色,**不新增角色值**;
- `secret_candidate` 作为**第 13 个推荐类**(非 KnowledgeRole,独立横切标记,可叠加在任何角色上)——是否并入 `MODEL_ARTIFACT_EXTS` 式 Layer 1 硬禁列 = **PD-1 待拍板**;
- reason 文案:枚举 `model_artifact_ext | hard_oversized | binary_content | poor_decode | vendor_dir | generated | test_dir | build_deploy | secret_file | thin_content_expected | robots_disallowed | exclude_pattern | off_topic_category` → `REASON_ZH` 固定映射表(Stage⑯ 冻结文案模式,单测锁定)。

---

## 10. Technical Safety Boundary

1. **边界不变**:Layer 1 三个不可绕过性质原样保留——判定先于昂贵操作、管理员配置不可解除、`ABSOLUTE_HARD_SIZE_MAX=64MB` 穿越保护(`safety.py:248-250`)。Discovery/preview 对**每个候选**执行 `check_path`(廉价、无内容 IO);`check_content` 仍只发生在 ingest(preview 抽样为可选增强,结果仅供 review 提示,不改变最终准入判定权)。
2. **新缺口(本轮新发现,超出三 Issue 原文)**:全链路无 secrets 文件防线。实证:`safety.py` 的 `MODEL_ARTIFACT_EXTS` 与 `exclusion.py` 的 BUILD_DIRS/BINARY_EXT 均不含 `.env/.pem/.key/.p12/.pfx`;叠加前端"全后缀自动填充 file_types",含密钥仓库会把 `.env` 内容 embed 进知识库并对 widget 访客可见(P0 信任边界先例:channel_visibility 事故)。**建议**(PD-1):
   - 方案 A(推荐):`safety.py` 新增 `SECRET_CANDIDATE_EXTS` frozenset,进 Layer 1(`check_path` 返回 `secret_file` 不可纳);`.env.example`/`*.sample` 降 review;
   - 方案 B:仅 Layer 2 推荐 exclude,管理员可翻转(弱防线,存在误操作面)。
   - 无论 A/B,Discovery 的 `recommended_config` 与 Simple Mode UI 都不提供 secrets 纳入入口。
3. **能力诚实红线**:§5.5 矩阵为 UI 声称上限;preview 的 `capability_notes` 机制保证"UI 不声称支持不能可靠处理的格式"可测试。
4. 上传路径(C9,20MB 上传护栏)与 filesystem 源不在本轮三 Issue 范围,safety 原语变更不影响其既有行为(`filesystem.py:150` 已声明与 safety 正交)。

---

## 11. Delete Current Root Cause(#18 病根)

### 11.1 同步链路(实证,`data_sources.py:458-517`)

```
DELETE /data-sources/{id}
  ① 枚举 documents 账本(source_id.startswith 前缀,autoescape)
  ② run_in_threadpool(_purge_source_corpus_sync):
      a. 账本段:确定性 UUID 批量点删(delete_many,500/批)
      b. 孤儿段:Weaviate 全类 iterator 全扫(207,294 对象级)→ 前缀过滤 → 逐个点删
      c. 验证段:第二次全类 iterator 全扫 → 残留>0 即 raise(不假报成功)
  ③ 同事务删 config 行 + 账本行 → 204
```

### 11.2 逐问回答

- **为什么会卡 Admin**:HTTP 请求在 ② 全部完成前不返回;② 的 b+c 两段成本是 **O(全库对象数)** 而非 O(该源文档数)——大库上秒级~分钟级。前端删除钮禁用期间用户无任何进度呈现(仅按钮灰),感知为"整个 Admin 卡死";(线程池让事件循环存活、其它 API 不真死,但用户视角等价于卡死,且 09-02 生产 504 事故后"请求内重型工作"已是惊弓之鸟)。
- **HTTP 是否同步执行重清理**:是。`run_in_threadpool` 只解决了事件循环阻塞,没解决请求时延。
- **vector deletion 是否主要耗时**:是,双全类扫描+逐对象点删是绝对大头;PG 两行 delete 可忽略。
- **active/pending sync 怎么处理**:**完全不处理**。删除端点不查 `sync_requests`/`sync_runs`。竞态矩阵:
  - run 已启动(cron/executor 均在启动时 `@1d6f6b5` 加载 configs)→ 删除清完向量后,run 轮到该源**重新 ingest** → 已删源的向量+账本行复活 = **ghost 语料**(无 config 行的孤儿,只能靠 ⑪⑫ reconciliation 兜底);
  - pending request 指向已删源 → executor 领用 → `_load_configs_from_db` 无此源 → 空转 run(无害但产生噪音 SyncRun/SyncLog);
  - cron 下一轮:DB 已无该源 → 自然排除(删除**完成后**无残留调度风险)。
- **scheduler 是否可能重新触发**:删除进行中可能(cron 不感知 DELETING,因为**没有 DELETING**);删除完成后不可能。
- **partial failure 后状态**:502 + config/账本原样保留(`data_sources.py:494-499`,失败安全,不假报成功——这部分是对的);但**无持久失败标记**,失败只是当次响应,刷新后界面无痕,重试=从头发起全量 purge(purge 本身幂等:点删可重入、验证段收敛)。
- **refresh 后是否知道 deletion 正在进行**:**不知道**。无 DELETING 态、无任何持久化痕迹——直接违反冻结产品方向"refresh/relogin restores truthful state"。

### 11.3 既有可复用资产

- purge 三段式本体(G2 后的 UUID 点删纪律)是**正确且幂等**的,#18 只需换执行时态,不需要重写清理逻辑;
- 阶段⑨ 的 `submit_sync_request` + 前端"202 → 5s 轮询列表"是现成非阻塞交互模板;
- 阶段⑩ 的"启动对账把孤儿 running 盖章"模式可平移到"backend 重启把卡死的 DELETING 复原/续跑"(purge 幂等使续跑安全)。

---

## 12. Delete Lifecycle Contract(#18 目标契约)

### 12.1 状态机(最小四态,持久化于源行)

```
(现行)            ── DELETE 202 ──▶  DELETING ──成功──▶ (源行删除,回到不存在)
                                             └─失败──▶  DELETE_FAILED ──重试(幂等续跑)──▶ DELETING
无 DELETE_REQUESTED 独立态:202 = 行内原子置 DELETING(请求即状态,免双写)
```

选择**扩展源生命周期持久化**(§16 选项 B)而非独立 job 表:一行真相、list API 天然携带、与 `enabled` 语义同位。列:`deletion_status`(NULL|deleting|failed)/ `deletion_error` / `deletion_started_at`(均 NULLABLE,见 §15)。

### 12.2 必须定义的行为(逐项)

| 场景 | 契约 |
|---|---|
| double click / 并发 DELETE | 第二个 DELETE 得 409(`deletion_status=deleting` 幂等闸);前端删除钮按行禁用 |
| retry | 仅 `failed` 可重试;复用同一 purge(幂等续跑,验证段兜底);成功后行删除 |
| active sync conflict | 触发删除时查 `find_active_request(source_id)` + sync_runs running 行(只读消费,§16)→ 有在途:409 + "请等待同步完成或先取消"(V1 不做自动取消 = PD-2 可选项) |
| queued sync conflict | pending request 指向 deleting 源:删除流程将其标记 failed(`error="source deleted"`,复用阶段⑩ 恢复字段的显式失败路径)——防 executor 空转 run |
| scheduler behavior | `_load_configs_from_db` 增加 `deletion_status IS NULL` 过滤(`sync.py:126` 一行;跨波 hunk,§16)→ cron/executor 任何启动时点都不会把 deleting/deleted 源再灌回来 |
| idempotency | purge 三段式已幂等(点删重入安全、验证段残留=0 才算成功);重复 DELETE 请求 409;对不存在 id 保持 404 |
| partial cleanup | purge 验证段残留>0 → `failed` + error 保留全状态(现行为保留);backend 容器重启于 DELETING 中 → lifespan 启动对账:置 `failed`(提示重试)或直接续跑(PD-3,V1 建议置 failed 简单诚实) |
| 交互时序 | 202 响应 < 1s(仅置状态+入队);Admin 页立即可用(仅该源行锁定);前端复用既有 5s 轮询呈现 DELETING 徽章 → 终态 toast;`DELETE_FAILED` 行内展示 error + 重试钮 |

### 12.3 执行面归属

删除 job 跑在 **backend 进程内**(Weaviate+PG 清理无 GPU 依赖,不需要 sync-executor):202 处理器 `asyncio.create_task` + `run_in_threadpool(purge)`,与 W0 波"ingest 阻塞事件循环"修复同款模式;启动对账覆盖重启窗口。**不改 sync_requests/sync_executor_loop 语义**(W0 冻结面零触碰)。

---

## 13. Simple vs Advanced UX

| | Simple Mode(缺省) | Advanced Mode(折叠) |
|---|---|---|
| github | repo_url + 分支(Discovery 后默认勾远端默认分支)+ 产品线;[扫描仓库] → 聚合推荐确认 | clone_path / exclude_dirs / exclude_regex / max_file_size / 手工 file_types / 手工分支逗号串 |
| web_crawl | base_url;[发现页面] → 三态清单确认 | sitemap_url / exclude_patterns / crawl_delay_ms(+ 新可入口:max_pages、min_content_chars) |
| filesystem / woocommerce | 本轮不动(已有 upload/DirPicker 简化流) | 不变 |

推荐结果与表单的关系:**推荐预填,确认即配置**——Simple 确认后写入的 config 与 Advanced 手填的 config 同构,编辑旧源时可随时切 Advanced 查看"推荐被如何编译"。Advanced 现有折叠区从 github/filesystem 扩展到 web_crawl。

---

## 14. API Requirements

| 端点 | 方法 | 契约要点 |
|---|---|---|
| `/api/admin/data-sources/preview/github-discovery` | POST | body `{repo_url, branch}`;走 trees API;≤30s;422(无法解析/分支不存在,复用 `_validate_github_branches` 语义)/502(上游不可达);角色 EditorDep |
| `/api/admin/data-sources/preview/website-discovery` | POST | body `{base_url, sitemap_url?}`;robots+sitemap 枚举,不抓正文;空 sitemap → 200 + `warnings`(不是错误,让用户看到真实发现为 0) |
| `/api/admin/data-sources/{id}` | DELETE | **204 同步 → 202 异步**(body `{status:"deleting"}`);在途同步 → 409;重复删除 → 409;唯一破坏性变更(消费方仅自家前端,§17) |
| `/api/admin/data-sources` (list) | GET | `DataSourceOut` 增 `deletion_status/deletion_error/deletion_started_at`(NULLABLE 向后兼容) |
| `/api/admin/data-sources/{id}/delete-retry` | POST | 仅 failed 态;202 重入 DELETING;其余态 409 |
| (无新读端点) | — | 删除进度无需独立端点:DELETING 是分钟级终态明确的短操作,list 轮询即真相;不重蹈 #9 "ephemeral state" 覆辙(状态在 DB 不在 React useState) |

Discovery 端点实现纪律(504 教训):trees/sitemap 抓取用 async httpx(既有 `_fetch_github_branches` 模式)或 threadpool,**禁止**同步网络调用落事件循环;两 preview 端点必须带超时与封顶(candidates ≤ N、top_dirs ≤ 100)。

---

## 15. Persistence Requirements

| 项 | 决定 | 理由 |
|---|---|---|
| 删除状态 | `data_sources` 增 3 NULLABLE 列(`deletion_status/deletion_error/deletion_started_at`) | 一行真相;list API 免 join;NULL=旧语义零迁移负担 |
| 迁移 | `scripts/migrate_add_data_source_lifecycle.py`,幂等 `ADD COLUMN IF NOT EXISTS` + 期望列校验(复刻 `migrate_add_sync_runs.py` 房式) | 房式模式;**禁生产自动迁移**——上线路径与既有四 REQUIRED 迁移清单同流程,需授权 |
| Discovery 结果 | **不持久化**(纯 preview,响应即弃) | 推荐 → 配置的编译产物落 config JSONB,中间态无审计价值;避免第二张快照表与 ⑪⑫ 的 expected_state 键空间混淆 |
| config JSONB 键 | **零新键**(推荐编译回现有词表);`expected_state`(W0 W2 预留)不碰 | 跨波键空间隔离 |

---

## 16. Shared Interface with Sync Truth(对 Worktree-1 的接口需求,零契约修改)

本轮对 W0 冻结契约(**只消费,不修改**):

1. **静默判定(读)**:删除流程需要"该源是否有在途同步"的权威判定 → 消费 `sync_requests.find_active_request(session, source_id)`(既有 service 函数)+ 需要一个 sync_runs running 行只读查询(`derive_run_state`/list 侧已具备数据,W0 W2 的读端点若含 per-source active 视图则直接消费;否则本轮在 `source_deletion.py` 内做只读 select,**不写** sync_runs)。
2. **调度排除(一行 hunk,跨波协调点)**:`_load_configs_from_db` 的 WHERE 增加 `deletion_status IS NULL`(`scripts/sync.py:126` 邻域)——该文件同时是 W0 波 W1/W2 双 hunk 所在地;本轮 hunk 与两者不同函数不同行区,但**三波叠加时 sync.py 成为三重交叉文件**,集成次序必须 Planner 冻结(建议:W0 波先合 → 本轮 rebase 后合)。
3. **删除不写 sync_runs/SyncLog**:删除不是 sync attempt,不进 W0 的 stage 词表/计数器词表;操作真相在 `data_sources` 自身列(§12.1)。两波状态体系正交:W0 管"同步运行真相",本轮管"源生命周期真相"。
4. **counters 词表**:`chunks_deleted`(W0 W2 可选键)语义不受影响——删除路径不产生 run,无需报数。
5. 前端 `admin/tests/DataSources.test.tsx` 脚手架为本轮 C3 测试复用(W0 §5.2 已确认存在)。

---

## 17. Backward Compatibility

- **config 词表冻结**:Discovery 只产出现有键 → 旧源、旧 runner、reindex、reconciliation 全部无感;无 Discovery 的源(手填/旧数据)行为零变化。
- **`DataSourceOut` 只增字段**(NULLABLE)→ 旧前端可忽略;新前端对 NULL 显示"-"。
- **DELETE 204→202 是唯一破坏性变更**:消费方仅 `admin/src`(grep 全仓无其它 API 消费者);前后端同镜像原子发布(CI 单镜像机制天然满足);文档(README API 面)同步更新。
- **迁移只增列**:与 M01-M05 既有迁移清单并存;生产执行需授权(不自动)。
- **type 枚举**:`local_git|sdk` 遗留容忍不变;Discovery 端点仅支持 `github|web_crawl`。
- **web_crawl 行为变化面**(§7 实现后):sitemap 发现变宽(多发现 URL)——这是修复而非回归,但**会改变既有源的增量视野**;需要灰度说明(第一个增量轮可能补齐历史缺口,items_new 上升是预期),并在实现验收中用固定 fixture 证明排序/去重确定性。

---

## 18. Exact File Ownership Matrix

图例:**OWN**=独占新文件/整文件;**HUNK**=共享文件冻结行区;✗=禁止。

| 文件/目录 | S0(Shared Foundation) | C1 Git Intelligence | C2 Website Intelligence | C3 Delete Lifecycle |
|---|---|---|---|---|
| `backend/services/source_discovery.py`(新) | **OWN**(envelope+聚合器+双 producer 骨架+URL admission) | 消费+github producer 细化 | 消费+web producer 细化 | ✗ |
| `backend/connectors/safety.py` | **HUNK**(SECRET_CANDIDATE_EXTS+check_path 一分支+REASON 枚举;≤30 行) | ✗ | ✗ | ✗ |
| `backend/connectors/web_crawl.py`(sitemap 发现升级:Sitemap: 指令/通用回退/子表偏好化/零发现告警) | ✗ | ✗ | **OWN** | ✗ |
| `backend/api/admin/data_sources.py`(preview 端点 + delete 异步化) | ✗ | **HUNK-P1**(preview 路由+handler,新增区块) | **HUNK-P2**(web preview handler;与 P1 相邻新区块,建议 P1/P2 同文件不同 handler 函数) | **HUNK-D**(delete/retry 端点 458-517 重写为 202+task) |
| `backend/api/admin/schemas.py`(Discovery/Deletion 的 Pydantic 模型) | ✗ | **HUNK**(Discovery 模型) | **HUNK**(同区块追加) | **HUNK**(DataSourceOut 增列+重试模型) |
| `backend/services/source_deletion.py`(新:状态机+task+启动对账) | ✗ | ✗ | ✗ | **OWN** |
| `backend/db/models.py`(DataSource 3 列) | ✗ | ✗ | ✗ | **OWN** |
| `scripts/migrate_add_data_source_lifecycle.py`(新) | ✗ | ✗ | ✗ | **OWN** |
| `scripts/sync.py`(`_load_configs_from_db` WHERE 一行) | ✗ | ✗ | ✗ | **HUNK**(跨波协调,§16.2) |
| `backend/main.py`(lifespan 启动对账挂点) | ✗ | ✗ | ✗ | **HUNK**(≤10 行;W0 红线文件——需 Planner 特批此 hunk) |
| `admin/src/pages/DataSources.tsx` | ✗ | **HUNK**(770-832 github 表单区+发现按钮接线) | **HUNK**(964-994 web 表单区+发现按钮接线) | **HUNK**(601-605 handleDelete+1139-1165 行操作区) |
| `admin/src/components/RepoDiscoveryPanel.tsx` / `SiteDiscoveryPanel.tsx` / `DeleteStateBadge`(均新) | ✗ | **OWN**(前者) | **OWN**(中者) | **OWN**(后者) |
| `admin/src/hooks/useDataSources.ts` / `admin/src/types/api.ts` | ✗ | HUNK(preview mutation+类型) | HUNK(同区块追加) | HUNK(delete-retry mutation+类型) |
| `tests/`(后端) | `tests/services/test_source_discovery.py`(新)+ safety 增量用例 | github producer 用例(同新文件或邻文件) | web producer/sitemap 升级用例 | `tests/services/test_source_deletion.py`(新)+ data_sources API 测试 |
| `admin/tests/**` | ✗ | HUNK(github 发现流) | HUNK(web 发现流) | HUNK(删除状态机流) |
| `docs/`、README API 面 | HUNK(契约引用) | ✗ | ✗ | HUNK |

冲突热区与消解:(a) `data_sources.py` 三 HUNK 全部为**新增 handler/重写既有 delete 函数**,行区互斥(P1/P2 追加在 preview-branches 邻域,D 在 458-517);(b) `DataSources.tsx` 三 HUNK 行区互斥且 UI 主体抽到新组件文件,把单文件增量压到接线级;(c) `schemas.py` 三 HUNK 同区块追加——**建议 S0 先建三组模型骨架占位**,三 C 只填充,消除同区块竞写。

---

## 19. Parallelization Recommendation

```
PARALLEL_RECOMMENDATION: THREE_WAY(条件:S0 Shared Foundation 先行小步合入)
```

- **S0 内容**(半天~一天量级):safety.py secrets 扩展 + `source_discovery.py` envelope/聚合器骨架 + schemas.py 三组模型占位 + 测试脚手架。先合 S0 后,C1/C2/C3 之间**零共享文件写冲突**(各自 OWN 新文件 + 冻结行区 HUNK)。
- **不跳过 S0 的替代**:TWO_WAY(C1+C2 串行共用 discovery 骨架,C3 独立并行)——仅当 Planner 裁定 secrets/PD-1 未决、S0 无法定型时降级。
- **集成次序(冻结建议)**:① W0 波(Worktree-1,W2→W1→W3)先合 main(其契约已冻结且 surface 更小);② 本轮 S0 合入;③ C1/C2/C3 任意次序并行,rebase 于 S0;④ C3 的 `sync.py` 一行 hunk 在 W0 波合入后 rebase 解决(三方合并可解析:不同函数)。若 W0 波与本轮必须同时合,**Planner 须显式指定 sync.py 与 data_sources.py 的合并基线仲裁方**。
- 红线:不为并行而并行——若实现期任一 HUNK 扩散出冻结行区,立即暂停上报(双仓协议 RE-PLAN REQUIRED)。

---

## 20. Acceptance Criteria

**#16(Git)**
- AC-16.1 给定测试仓库,Discovery 仅凭 trees API(无 clone、无 blob 内容拉取)返回 by_role/top_dirs/candidates,耗时 < 30s(匿名限流下有明确错误路径)。
- AC-16.2 推荐结果满足:vendor/generated/test/build/binary/secret 全部 exclude 且 reason_zh 非空;.env fixture 仓库 → secret 检出并默认排除(PD-1=A 时不可纳入)。
- AC-16.3 确认推荐创建的源,其 config 仅含现有词表键;`scripts/sync.py` 零改动通过既有全量测试。
- AC-16.4 UI 不出现 capability 矩阵之外的格式声称(.pdf/.png 无纳入入口)。

**#17(Website)**
- AC-17.1 非 Yoast fixture(通用 sitemap.xml / robots Sitemap: 指令 / 非标准子表名)三类站点均可发现 URL;Yoast 既有 fixture 行为不变(回归)。
- AC-17.2 preview 不抓正文即返回三态清单;`discovered=0` 产出显式 warning;login/cart 等排除项带 reason。
- AC-17.3 确认后 sync 语义与现状逐字节兼容(同一 fixture 全量轮 run_stats 对比:仅 discovered 集合按设计扩大)。
- AC-17.4 子域默认外域、query 剥离、max_pages 封顶行为不变。

**#18(Delete)**
- AC-18.1 大语料 fixture 上 DELETE 响应 < 1s(202);Admin 其余源操作全程可用。
- AC-18.2 状态机:DELETING 中重复 DELETE=409、sync 触发=409;refresh/relogin 后 DELETING/DELETE_FAILED 如实呈现;retry 幂等收敛到 0 残留(验证段通过)。
- AC-18.3 冲突:在途 active request/running run 时 DELETE=409;queued request 被显式 failed 不产生空转 run;`_load_configs_from_db` 过滤 deleting 源(fixture 断言)。
- AC-18.4 backend 重启于 DELETING 中 → 启动对账置 failed(或续跑,按 PD-3),无永久卡死态。
- AC-18.5 回归:全量离线套件绿(HF_HUB_OFFLINE=1 纪律);DataSources.test.tsx 增删除状态机用例全绿。

---

## 21. Risks / Unknowns

1. **GitHub API 限流**:匿名 60 req/h,trees Discovery 一次调用尚可但拒绝重试风暴;需依赖 GITHUB_TOKEN(已有 env)并在 403/429 时给出明确文案(中)。
2. **跨波三重交叉**:`sync.py`/`data_sources.py`/`schemas.py` 与 W0 波叠加——已给行区与次序方案,依赖 Planner 冻结合并基线(中,已缓解)。
3. **web_crawl 发现面扩大**的增量视野变化:既有源首轮 items_new 上升为预期,需发布说明 + AC-17.3 fixture 证明(低-中)。
4. **mid-run 删除竞态残余**:409 静默窗(检查后、删除中 cron 启动)仍理论上存在;验证段可检出残留→failed 可重试,但"删除成功后又被复活"的极端序列需要 sync 侧配合才能根除——V1 接受为文档化残余风险(低概率,⑪⑫ reconciliation 可兜底)(低)。
5. **secrets 名单误伤**:`.env.example`/`dummy` 密钥在 review 档;清单初版保守,工程可扩(低)。
6. **`DataSources.tsx` 1174 行**持续膨胀:本轮以新组件文件吸附增量,不做大重构(与 W0 W3 同纪律)(低)。
7. **20 万+对象孤儿扫描性能**:异步化不减少扫描成本,只改善时延体验;purge 的 O(全库) 成本根治(如按 source_id 前缀分片索引)属后续优化,不在 #18 V1(已文档化)(低)。
8. **PD 待拍板清单**:PD-1 secrets 进 Layer 1 硬禁列与否;PD-2 删除时在途 queued sync 自动取消 vs 409;PD-3 重启对账置 failed vs 续跑;PD-4 DELETE 202 化的发布窗口(与迁移同批)。

---

## 22. Final Verdict

```
READY_FOR_PARALLEL_IMPLEMENTATION
(THREE_WAY @ S0 Shared Foundation 先行;跨波合并次序与 4 项 PD 待 Planner 拍板)
```

三 Issue 均具备"地基已存在 + 缺口明确 + 行区可冻结"的并行条件;唯一超出原始范围的新事实(secrets 防线缺口)已按契约化方式并入,不影响其余范围先行。

---

## 附:证据索引(关键 file:line 汇总)

- 存储/适配:`backend/db/models.py:41-66,176-204,207-245,248-300`、`backend/connectors/db_adapter.py:14-40`、`backend/api/admin/schemas.py:48-80`
- Admin API/删除:`backend/api/admin/data_sources.py:458-517(delete)、385-455(purge 双全类扫 429/438)、610-679(sync 202)、554-607(preview-branches/file-types)、194-234(clone_path 冲突)`
- Git connector:`backend/connectors/github.py:56-82(config 缺省)、153-177(clone/fetch/reset)、215-231(safety 调用点)、363-405(token 校验)`
- 过滤与安全:`backend/connectors/exclusion.py:13-45(BUILD_DIRS/BINARY_EXT,无 secrets)、backend/connectors/safety.py:56-58(阈值)、67-112(工件名单,无 secrets)、115-151(角色+推荐)、213-235(FileAdmission)、236-250(不可穿越上限)`
- Website connector:`backend/connectors/web_crawl.py:47-60(默认排除)、67(Yoast 正则)、119-143(canonical)、146-170(robots 无 Sitemap:)、469-488(_sitemap_entries)、600-648(fetch_all/max_pages)、650-676(增量)`
- 同步执行面:`scripts/sync.py:112-129(DB 加载,过滤挂点:126)、902-1002(run_sync)`、`scripts/sync_executor_loop.py`、`backend/services/sync_requests.py:34-101`、`deploy/prod/docker-compose.yml:100-137`
- ingest 安全调用点:`backend/pipeline/ingest.py:230,487(check_content)、618-659(delete_document)`
- 前端:`admin/src/pages/DataSources.tsx:601-605(handleDelete)、770-832(github 表单)、964-994(web 表单)、996-1016(Advanced)、1076-1084(启用徽章)、1139-1165(行操作);admin/src/hooks/useDataSources.ts:34-102`
- 姊妹契约:docs 仓 `CAMTHINK_V1_DATA_SOURCE_RELIABILITY_OBSERVABILITY_SHARED_DISCOVERY_2026-09-03.md`(c9ef948,§16-§17 所有权与次序)

---

```
STATUS: DISCOVERY_COMPLETE — READY FOR PLANNER REVIEW
DISCOVERY_BASELINE: 1d6f6b5(本地 main = origin/main)
GIT_DISCOVERY: 推荐引擎地基已存在(safety.py FileAdmission 预留);preview 可无 clone 无 ingest(trees API);关键反转=推荐编译回现有 config 词表,sync 零改动;新发现 secrets 防线缺口(PD-1)
WEBSITE_DISCOVERY: V1 能力大半已备;真缺口=sitemap auto-discovery(robots Sitemap: 指令+通用回退+去 Yoast 专用化)+ URL 级 preview + 零发现告警;JS/PDF/OCR 冻结不支持
DELETE_ROOT_CAUSE: 同步请求内执行 purge,孤儿+验证两段全类迭代器扫描 O(全库);无持久化删除状态(refresh 失明);与在途同步零互斥(ghost 竞态);purge 本体幂等可保留
SHARED_FOUNDATION_REQUIRED: YES(S0=safety secrets 扩展+source_discovery 骨架+schemas 占位)
PARALLEL_RECOMMENDATION: THREE_WAY(条件:S0 先行;跨波 W0 先合、本轮 rebase;否则降 TWO_WAY)
BLOCKERS: 无(实现授权与 PD-1~4 待拍板不阻塞本 Discovery)
REPORT_PATH: docs/implementation/CAMTHINK_V1_DATA_SOURCE_CENTER_SHARED_DISCOVERY_2026-09-03.md
REPORT_COMMIT: (见本仓提交)
CODE_MUTATION: NONE
PRODUCTION_MUTATIONS: NONE
```
