# CAMTHINK V1 Product UX Closure B — Wiki Citation URL + Conversational Boundary UX

- 日期:2026-09-02
- 角色:Engineering Executor(PARALLEL CODEX B)
- 状态:**PASS(自评)**
- 分支:`worktree-exec/product-ux-closure-b` @ **0420703**(已推 origin)

## 1. Baseline

| 项 | 值 |
|---|---|
| BASELINE_COMMIT | `cd12687`(= origin/main `76b2199` + 本任务前置的 `.worktrees/` ignore chore 一行;不含任何并行未验收修改) |
| WORKTREE | `/Users/harryhua/Documents/GitHub/ask-ai/.worktrees/product-ux-closure-b` |
| BRANCH | `worktree-exec/product-ux-closure-b` |
| 并行任务隔离 | Corpus Integrity P0 占用 technical-insights 树(ingest.py 有未提交改动,未触碰);Sales Lead 占用 sales-lead 树(执行中后出现,未触碰);其余树有用户进程/他窗占用,故新建独立 worktree |

## 2. Root Cause / Current Behavior

### A. Citation URL(修复前)

citation 链路:`GitHubConnector._make_document`(backend/connectors/github.py:222)把
`https://github.com/{owner}/{repo}/blob/{branch}/{rel}` 写入文档 `url` → Weaviate
chunk property `url` → `SearchResult.url` → `_extract_sources` **原样透传**给用户,
`_build_context` 也把 blob URL 交给 LLM。CamThink Wiki 知识源 =
`camthink-ai/wiki-documents`(Docusaurus 站点 wiki.camthink.ai,见 ask-ai-design.md),
因此 Wiki 引用全部落在 github.com blob 页。INGESTION SOURCE 与 USER-FACING
CANONICAL URL 未做区分。

### B. Conversational Boundary(修复前)

`classify_intent`(LLM 四分类)将问候/致谢归入 off_topic(「闲聊」),RAG 编排器对
off_topic 短路并返回硬话术 `REJECT_OFF_TOPIC = "我只能回答与 CamThink 产品相关的问题。"`
(answer 与 stream_answer 双路径)。无 social/smalltalk 概念,体验生硬。

## 3. Implementation

### A. Canonical Wiki Citation URL — 新模块 `backend/pipeline/canonical_url.py`

纯函数 `wiki_canonical_url(url) -> str`,展示层映射,**不要求语料回灌**:

- 仅匹配 `github.com/camthink-ai/wiki-documents/blob/<branch>/<path>` 且以 `.md`
  结尾;其余 URL(普通 GitHub 仓库 / Website / WooCommerce / 结构异常 / 空串)一律
  原样返回 —— G002/G005 零回归、G004 fallback。
- 变换规则(**逐条对照线上 `https://wiki.camthink.ai/sitemap.xml` 实证**,2026-09-01
  构建,Last-Modified 2026-09-01 07:15 GMT):
  1. `i18n/<locale>/docusaurus-plugin-content-docs/current/(docs/)?…` 翻译树镜像到
     默认 locale 同一 canonical 页面(与既有 `_normalize_source_path` 去重语义一致);
  2. 剥 `docs/` 前缀,逐段剥 Docusaurus number prefix(`5-`→去,`NE300-…`保留大小写);
  3. 剥 `.md`;`index.md` 或「剥前缀后与父目录同名」→ 折叠为目录路由
     (线上实证:ai-tool-stack、ne101-camera-component case studies);
  4. 任何结构意外 → 原 GitHub URL,不猜测。
- 实测命中率:对仓库 main 全部 180 篇 docs,**160(89%)映射命中当前线上路由**;
  20 篇未命中均为**部署滞后/内容改名**(线上软 404 由 SPA 兜底,无从谈起 404 码)。
  **生产语料验收证据(09-01)中的真实 chunk URL 抽检 4/4 命中**——存量语料与当前
  部署构建的偏差远小于仓库 HEAD。

rag.py 集成(最小侵入,8 个 hunk):

- `_extract_sources`:`url` = canonical;映射发生时附加 `provenance_url` = 原 GitHub
  URL(G006 追踪性,加法字段向后兼容);未映射时**无** `provenance_url` 键,payload
  与历史完全一致。去重键改为归一化后的 canonical URL(zh/en 翻译本就归并,G003 强化)。
- `_build_context`:LLM 上下文 URL 行同样呈现 canonical,防止模型把 blob URL 抄进
  答案文本。
- trace(`_rerank_snippets`)保留原始 `r.url`,内部可追溯 provenance。

### B. Conversational Boundary — 新模块 `backend/pipeline/social.py` + rag.py 接线

- `match_social(query) -> SocialReply | None`:**确定性整串锚定匹配**(zh/en 各一组),
  覆盖问候/致谢/身份/能力/告别五类(你好、hello、谢谢、thanks、你是谁、你能做什么
  及常见语气变体)。纯社交输入才命中——「你好,NE301 支持热成像吗」等带实质内容者
  一律不命中(G006 守门),不调 LLM,无 unrestricted LLM 介入。
- 回复模板为固定文案(产品语义示例,非冻结原文):问候/致谢自然回应;身份/能力
  介绍 CamThink Assistant 能力范围(选型/功能/方案/配置/支持)。
- rag.py:`_social_answer()` 在意图分类**之前**短路(省一次 LLM 意图调用),
  answer/stream_answer 双路径一致;`intent="smalltalk"`(与 off_topic 明确区分,
  契约 §6),trace `type="social_reply"`,is_answered=True(用户获得了完整回应,
  非拒答)。
- off_topic 话术:`REJECT_OFF_TOPIC` 退役,改为 `_off_topic_reply(language)` 中英双语
  友好边界(轻量回应+能力说明+引导,接近契约示例文案);**short-circuit 与 domain
  boundary 原样保留**(off_topic 依旧不进 RAG)。
- 落库:conversations.intent_tag 记 `smalltalk`;admin 分析对四类之外值有
  "unknown" 兜底/排除,无崩溃风险(business.py 已核)。

## 4. Modified Files

| 文件 | 变更 |
|---|---|
| `backend/pipeline/canonical_url.py` | 新增:Wiki canonical URL 映射(纯函数) |
| `backend/pipeline/social.py` | 新增:社交对话确定性识别 + zh/en 模板 |
| `backend/pipeline/rag.py` | +8 hunks:导入、双语 off_topic 话术、`_social_answer`、双路径社交短路、`_extract_sources` canonical+provenance、`_build_context` canonical |
| `tests/pipeline/test_canonical_url.py` | 新增:17 用例(映射 7 + fallback 8 + 边界) |
| `tests/pipeline/test_rag_citation_source.py` | 新增:6 用例(sources/context/stream 集成) |
| `tests/pipeline/test_social.py` | 新增:16 用例(matcher 10 + 编排器 6) |
| `tests/pipeline/test_rag.py` | 1 用例断言更新:旧话术「只能回答」→ 新友好边界语义(短路不变量保留) |

前置 chore(主仓 main):`cd12687` .gitignore 增加 `/.worktrees/`(此前 worktree
目录未被 ignore,git status 长期显示 `?? .worktrees/`)。

## 5. Tests(TDD:RED→GREEN 全程)

- RED 实证:新测试先跑——2 个 ModuleNotFoundError(功能缺失)+ 4 个断言失败
  (canonical 行为缺失);G002/G005 守护用例在现状即通过(锁零回归),符合预期。
- GREEN:39/39 新用例通过。
- 过程修正:i18n 树结构修正(`current/` 后无 `docs/` 段,依证据修正正则)、
  fake LLM stream 注入方式修正(测试侧)。

## 6. Acceptance Matrix

| 验收项 | 结果 | 证据 |
|---|---|---|
| CIT-URL-G001 Wiki citation → wiki 页面 | **PASS** | test_canonical_url.py 映射用例;期望 URL 均为当日线上 sitemap 实证存在的路由 |
| CIT-URL-G002 普通 GitHub 不变 | **PASS** | test_canonical_url + test_rag_citation_source(lowpower_camera blob 原样、无 provenance 键) |
| CIT-URL-G003 同文档不同 chunks 同 URL | **PASS** | test_same_doc_different_chunks_same_canonical + zh/en 翻译同 canonical + sources 去重用例 |
| CIT-URL-G004 无法映射 → fallback | **PASS** | 8 个 fallback 用例(非 md/非 docs/tree/非 wiki 仓/结构异常/空串);映射函数不产生猜测 URL |
| CIT-URL-G005 Website/WooCommerce 不变 | **PASS** | test_website_citation_unchanged;真实栈冒烟 web_crawl URL 原样落库 |
| CIT-URL-G006 GitHub provenance 可追踪 | **PASS** | sources[].provenance_url=原 blob URL;trace snippet 保留 r.url |
| OFFTOPIC-G001 创作请求 → 友好边界+引导 | **PASS** | test_off_topic_creative_request_gets_friendly_boundary + 真实栈「写诗」冒烟 |
| OFFTOPIC-G002 领域外问题 → 友好边界 | **PASS** | zh 用例 + en 用例(capital of France) |
| OFFTOPIC-G003 你好/hello 自然问候 | **PASS** | matcher 用例 + 编排器短路用例 + 真实栈「你好」冒烟(intent=smalltalk) |
| OFFTOPIC-G004 谢谢/thanks 自然回应 | **PASS** | matcher 用例(zh×3/en×3 变体) |
| OFFTOPIC-G005 你是谁/你能做什么 介绍能力 | **PASS** | identity/capability 用例(能力范围词断言)+ 编排器用例 |
| OFFTOPIC-G006 产品问题不被误判/拒绝 | **PASS** | test_product_question_with_greeting_prefix_not_social + test_product_question_still_enters_rag + 真实栈产品问题冒烟(intent=product,完整 RAG) |
| OFFTOPIC-G007 主流程无 regression | **PASS** | 后端全量 569 passed+3 skipped(pipeline/api/services/retrieval/connectors/llm/db/auth/utils/scripts/root) |
| OFFTOPIC-G008 中英文体验自然 | **PASS** | zh/en 模板用例 + off_topic 双语用例(detect_language 驱动) |

真实栈 E2E 冒烟(worktree 后端 :8033 + 隔离库 + 共享本地 Weaviate,SSE 实流):
1. 「你好」→ 单 token+done,友好问候,intent=smalltalk;
2. 「帮我写一首关于秋天的诗」→ 友好边界话术,intent=off_topic,不进检索;
3. 「NE301 是什么产品?」→ 完整 RAG(intent=product,345 token),sources 事件与
   落库行中 web_crawl URL 原样、无 provenance 键。

## 7. Regression Results

- `tests/pipeline/` 207 passed(含 39 新增);
- 全量(除 e2e):api 125 / services 32 / retrieval 54 / connectors 86 / llm 16 /
  db 8 / auth 6 / utils 19 / scripts 16+3 skipped / root 17 —— **合计 569 passed,
  0 failed**;
- 隔离说明:并行 Codex 同期占用共享 ask_ai_test,故主体套件跑一次性隔离库
  `ask_ai_puxb_test`(用后已 DROP);scripts 迁移用例因库名守卫在标准 ask_ai_test
  单独跑,16 passed;
- 唯一语义化测试更新即 §4 所列旧话术断言(契约 B 要求的行为变更,非削弱验收)。

## 8. Production Backfill Requirement

**PRODUCTION_CITATION_BACKFILL_REQUIRED = NO(功能层面) / 备注:可选优化**

- 本实现为展示层映射,存量 Weaviate chunk 的 GitHub URL 无需回灌即可呈现 canonical。
- 可选后续 Gate(非本 Contract 范围):ingest 时把 canonical_url 固化为 chunk property,
  消除「线上部署滞后改名」窗口内的极小概率失配;若立项则属 schema 变更+回灌,
  须单独授权。

## 9. Risks / Remaining Issues

1. **部署滞后失配(已量化)**:线上站点构建落后仓库 main 时,映射出的 canonical
   对 20/180(仓库 HEAD 口径)可能落在线上未部署路由(表现为 SPA 软 404)。
   生产语料口径抽检 4/4 命中,风险集中于未来仓库改名后未同步部署的窗口期。
2. **soft-404 不可探测**:wiki 线上对所有路径返回 200+同一 SPA 壳,无法在请求路径
   内校验页面存在性;fallback 只能做结构层(已做),不能做存在性层。
3. **smalltalk 新 intent 值**:admin 业务分析对四类之外记 unknown/排除,分布图暂不
   展示 smalltalk 桶( cosmetic,可后续补);聚类等已排除 off_topic 的查询同样
   应排除 smalltalk —— clustering.py 现按 `intent_tag != "off_topic"` 过滤,
   smalltalk 对话不落检索语料路径(其 sources 为空),无实际影响,已核对。
4. **误伤事故(如实记录)**:冒烟收尾时 `pkill -f backend.main` 误杀了用户主仓
   :8000 本地后端(已当场以原方式重启并验证 health 200)与一个 :8021 占用进程
   (归属不明,可能为并行任务栈)。教训再次验证 memory 既有警示:pkill 模式
   必须绑定端口/cwd 收窄。
5. **e2e 目录未跑**:tests/e2e 需完整本地栈与 Playwright,本门以真实栈 SSE 冒烟
   替代;widget/admin 前端零改动(provenance_url 为加法字段,前端 types 未声明
   不受影响)。

## 10. Final Commit 与交付状态

- 主仓:`0420703` `feat(ux): Wiki citation canonical URL + 社交对话/off-topic 友好边界`
  @ `origin/worktree-exec/product-ux-closure-b`(parent cd12687)
- 本报告持久化:①docs 本地仓 commit(见下 REPORT_COMMIT);②force-add 入主仓分支
  随 0420703 之后的报告 commit 推 origin(证据交接,Planner 独立审查可读;
  `docs/` 在主仓 .gitignore 内,与 PA-0F 报告 1ff2936「入主仓」同一模式)

| 字段 | 值 |
|---|---|
| STATUS | PASS(自评,待 Planner FINAL REVIEW) |
| BASELINE_COMMIT | cd12687 |
| FINAL_COMMIT | 0420703 |
| BRANCH | worktree-exec/product-ux-closure-b |
| WORKTREE | /Users/harryhua/Documents/GitHub/ask-ai/.worktrees/product-ux-closure-b |
| PRODUCTION_ACCESS | NO(全程未 SSH 生产、未触碰生产 DB/Weaviate/corpus) |
| PRODUCTION_MUTATION | NO(零生产写操作:无部署、无迁移、无回灌、无同步触发) |
| PUSHED | YES |

