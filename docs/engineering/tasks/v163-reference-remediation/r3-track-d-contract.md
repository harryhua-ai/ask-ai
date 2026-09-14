# R3 Track D Contract — Citation Integrity（冻结）

- Reference（权威）：Issue #64 全文（根因/要求/Acceptance/Boundary）+ 生产三层实证（planning 期已核：①`backend/pipeline/canonical_url.py` 零 frontmatter 读取；②`3-resources.md` 显式 `slug: /neoeyes-ne503-series/application-guide/`；③wiki sitemap 权威路由含 `/docs/neoeyes-ne503-series/application-guide/`、不含 mapper 派生的 `.../application-guide/resources`，SPA 壳 200 软 404）。
- Issue IDs：**#64**（全部）。
- 基线：fresh main `94ddb64`。

## 1. Product Semantics（冻结）

1. canonical URL 必须来自**权威 Wiki route truth**：文档显式声明 `slug` 时以 frontmatter slug 为优先真值（`/docs` routeBasePath 拼接语义按站点权威路由实证冻结）；同时支持 `id`、index/category route、i18n 折叠既有语义保持。
2. fail-safe：无法确定公开可访问 canonical route 时——回退真实可解析 provenance GitHub URL 或显式标记不可链接；**禁输出「看似 canonical、实际 404」的链接**。
3. linkability contract（确定性三档）：canonical known/verified → 可点 canonical；unknown → provenance（公开可解析时）；neither safe → 不渲染为可点链接。
4. 一致性：widget/API 与对话审查 citation URL 构造性一致（映射单点 `rag.py` citation 构建链保持唯一调用源）。
5. 既有语义不变：普通 GitHub citation、Website/WooCommerce citation 行为零变化；i18n 折叠保持。
6. 存量语料：corpus-wide audit（显式 slug 清单+mapper 输出 vs 权威 route 一致），非单点修复。

## 2. 变更边界（文件所有权）

- 可改：`backend/pipeline/canonical_url.py`（route authority 重构）、wiki 文档 ingestion 连接器中 frontmatter 真相提取（`backend/connectors/github.py` / `local_git.py` / `filesystem.py` 中 wiki 源实际走行者——**执行首日前置调查确认并记录**，若生产 wiki 源为 local clone 则 frontmatter 本地可得）、新增 fixture 语料测试+corpus audit 测试+pytest。
- 允许触达（仅测试/装配层面）：`backend/pipeline/rag.py` 相关测试（实现调用点签名不变）。
- 禁改：admin/src；citation 编号/去重语义（`normalize_source_path` 语义保持）；连接器其它源（woocommerce/web_crawl 等）行为。

## 3. Backend/Data 要求

- route truth 来源分层：①ingestion 时提取的 frontmatter（slug/id）权威化（新持久化或映射时可得——由前置调查定，**禁止运行时逐请求抓取 GitHub**）；②无 frontmatter 文档沿用既有路径推导规则；③推导结果与权威 route（sitemap/构建真相）冲突时以权威为准并记 audit。
- corpus audit 作为可重复测试资产（fixture=真实 wiki-documents 子集：explicit slug/numbered/index/i18n/ordinary 五类），纳入 G3。
- 禁前端 hardcode 单个 URL（#64 Boundary 原文）。

## 4. Frontend 要求

无新前端实现（citation URL 消费面零变化；如「不渲染为可点链接」三档需要前端配合，以 sources[] 权威字段承载，经 Integration 仲裁）。

## 5. Forbidden shortcuts（r2 冻结清单沿用）

- 前端 hardcode 修复单 URL；keyword/regex 猜测 route；猜测性 canonical 输出；静默把 unknown 当 verified；只修 `3-resources.md` 单点；为过测试改 sitemap 对照基准（权威 route 真相不可篡改）。

## 6. Acceptance（验收门）

- 验收矩阵 Track D 全行证据填充；#64 Acceptance 1–10 逐条对应。
- pytest：五类 fixture（explicit slug/numbered filename/index route/i18n/ordinary GitHub）+ fail-safe + linkability 三档 + corpus audit（已知无效 route=0）+ 既有 canonical 测试回归（普通 GitHub/Website/WooCommerce 零变化）。
- G7 生产只读复核：真实会话引用不再产生 `/docs/neoeyes-ne503-series/application-guide/resources`。

## 7. Runtime states（必须覆盖）

explicit-slug 文档引用；numbered 文件引用；index route；i18n 引用；普通 GitHub 引用；不可判定输入（fail-safe 态）；同源三面一致性（widget/API/admin conversations）。

## 8. E2E

- 真实问题 `NE503开发SDK在哪？` 端到端：回答引用 [2]（`3-resources.md`）指向 frontmatter 定义的真实 route，点击可解析（G5；生产授权探针制度沿 r2，逐条登记）。

## 9. Deliverables

分支 + canonical route authority 实现 + frontmatter 真相提取（连接器归属调查记录）+ fixture/corpus audit 测试 + 执行报告（`docs/engineering/tasks/v163-r3-track-d-execution.md`，`git add -f`）。
