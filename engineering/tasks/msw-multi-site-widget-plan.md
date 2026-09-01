# CAMTHINK_V1_MULTI_SITE_WIDGET_INTEGRATION — Implementation Plan (Executor HOW)

> Contract: FROZEN(用户 2026-09-01 下发)。本文件只记录 Engineering HOW,不重定义 Product Contract。
> Baseline: e945f59cb7aa2aaed4cb42328caa115af · worktree `.worktrees/multi-site-widget` · branch `worktree-exec/multi-site-widget`

**Goal:** 同一个 Widget 以 site_id 区分 website/wiki/store 三种站点体验(身份+starters+欢迎语),宿主页面上下文仅作非信任语义提示与软检索加分;channel 语义、P0 信任边界、P1 引用/生成可靠性零回归。

**Architecture:** 混合式(Hybrid)——`config/sites.yaml` 为站点配置权威源,lifespan 幂等 seed 进新表 `site_experiences`(DB 为运行时读取源,为未来 Admin 管理留位);新增公开端点 `GET /api/widget/site-config?site_id=`(服务端 Origin 校验);`/api/ask` 增加可选 `site_id`+`page_context`,显式 site_id 必须通过「站点存在且 enabled + 请求 Origin ∈ allowed_origins」校验否则 403;page_context 边界消毒后仅用于 (a) rerank 后软加分(乘性、不过滤)(b) user 消息内带标签的「非指令」背景段;`Conversation.site_id` 落库区分站点(channel 恒为 widget)。

**Tech Stack:** FastAPI + SQLAlchemy(async, Postgres/JSONB) · Pydantic v2 · React 19 + Vite lib(widget.js)+ vitest。

## Global Constraints(摘自冻结契约,验收一票否决项)

- website/wiki/store **不是** channel;`AskRequest.channel` 枚举不变(widget|discord|whatsapp|mcp|admin)。
- `CustomizationBinding.channel` 不重载站点值;站点体验与传输定制语义分离。
- site_id 是标识符不是凭证;单独 site_id 不授予任何权限;无 Origin/未知站/禁用站/来源不匹配 → fail-safe 403(对外统一文案,不区分原因)。
- page_context = 非信任语义提示:不改变授权、不进 system 消息、不构成事实依据、不成为硬检索过滤(soft boost only)、不绕过 SourceVisibilityGuard。
- legacy 嵌入(仅 apiUrl/language/primaryColor/channel)行为不变;请求体不得新增空键。
- 不做三套 Widget、不做跨站会话连续性、不部署生产、不改宿主站点、不改共享 weaviate(只读)、pytest 不指主库。
- P1 引用完整性/生成可靠性行为与测试零回归。

## Discovery 结论(契约 §24 九项确认)

1. channel 语义:`schemas.py:30` 枚举锁定;`Conversation.channel` 用于定制绑定与可见性探测(admin→widget 别名),保持不变。
2. 定制绑定:`CustomizationBinding` PK=channel;不触碰。
3. CORS:`main.py:459` env 白名单 `CORS_ALLOW_ORIGINS`;浏览器执行层,不作为站点身份授权(服务端独立校验为本任务交付)。
4. Widget bootstrap:`resolveConfig` 四级 fallback(bootstrap.tsx:51);starters 硬编码于 `App.tsx:7`;ask payload 在 `useSSE.ts:141`。
5. page_context:全库无此概念(新增)。
6. 会话边界:localStorage `ask_ai_session_id` 按源隔离 → 天然 per-site,不做跨站连续性(契约 §19)。
7. 对话持久化:`routes.py:245` 写 Conversation,无站点字段(新增 site_id 列)。
8. 软加分扩展点:`rag.py` `stream_answer`/`answer` rerank 之后、sources 提取之前;`SearchResult.product` 为现成匹配字段;既有 `product_filter` 是硬过滤,**不得**用于 page context。
9. 可见性边界:`SourceVisibilityGuard.allows(source_id, channel)`;站点实现不传 site/channel 之外的新值进守卫,channel 恒 "widget"。

**Planner 假设差异记录:** 无实质差异。一处澄清:契约 §16 选项选 C(hybrid),`sites.yaml` 为权威、DB 表为运行时读取源(boot 时 upsert),V1 不做 Admin CRUD UI(§23 禁重设计 Admin,列入 FOLLOW_UP)。

---

### Task 1: 站点模型 + sites.yaml + 身份/来源授权服务

**Files:**
- Modify: `backend/db/models.py`(新增 `SiteExperience`;`Conversation.site_id` + 索引)
- Create: `config/sites.yaml`(三站点生产 origins + starters)
- Create: `backend/services/site_experiences.py`
- Test: `tests/services/test_site_experiences.py`(新增)、`tests/db/test_models.py`(补 site_id 持久化)

**Interfaces(后续任务依赖):**
- `normalize_origin(raw: str | None) -> str | None`
- `extract_request_origin(request: Request) -> str | None`
- `class SiteDenied(Exception)`
- `@dataclass ResolvedSite(site_id, display_name, welcome, language, starters: tuple[str, ...])`
- `async resolve_site(session_factory, site_id: str | None, request_origin: str | None) -> ResolvedSite | None`(site_id 空 → None;失败抛 SiteDenied)
- `load_sites_config(path: Path) -> list[dict]`
- `async seed_default_sites(session_factory, config_path: Path | None) -> int`(幂等 upsert,返回站点数)
- env:`SITES_CONFIG_PATH`(缺省 `config/sites.yaml`)

核心语义(TDD 断言依据):
- `normalize_origin("https://WWW.CamThink.ai/docs") → "https://www.camthink.ai"`;`http://localhost:80 → http://localhost`;非 http(s) scheme / 无 host → None。
- `resolve_site`:site_id 空 → None(legacy);未知/禁用/无 Origin/Origin 不匹配 → SiteDenied;精确 origin 匹配(子域**不**通配)→ ResolvedSite。
- seed:按 YAML upsert(已存在则更新配置字段,YAML 为权威);二次执行行数不变。

### Task 2: 请求边界 —— PageContext 消毒 + AskRequest.site_id

**Files:**
- Modify: `backend/api/schemas.py`
- Test: `tests/api/test_schemas.py`(追加)

**Interfaces:** `AskRequest.site_id: str | None`(小写规范,`^[a-z0-9][a-z0-9-]{0,98}$`)、`AskRequest.page_context: PageContext | None`;`PageContext` 字段 url(≤2048,仅 http/https)/title(≤300)/language(≤20)/page_type(≤50)/product、product_id、sku(各≤100)/section(≤200);全部字段:控制字符(Cc/Cf)剔除、空白折叠、空→None;未知字段丢弃(extra="ignore")。消毒在边界完成,超长 → 422(Field 约束),非法值 → 降级 None(不炸请求)。

### Task 3: 检索软加分 + 非信任页面背景段(rag)

**Files:**
- Modify: `backend/pipeline/rag.py`
- Test: `tests/pipeline/test_page_context_boost.py`(新增)、`tests/pipeline/test_rag_page_context.py`(新增)

**Interfaces:**
- `PAGE_CONTEXT_BOOST_WEIGHT = 1.2`(与 rerank 乘性加权同量级)
- `product_hint(page_context: dict | None) -> str | None`(product → product_id → sku 取首个,小写字母数字+连字符)
- `apply_page_context_boost(results: list[SearchResult], page_context: dict | None, weight: float = ...) -> list[SearchResult]`:命中 `r.product` 归一化相等(或双向子串)→ score×weight;`sorted` 稳定重排;hint 空/结果空 → 原样返回;**绝不过滤/增删**。
- `page_hint_text(page_context, site_name) -> str`:仅站点名/页面标题/地址/类型/产品线索/章节/语言要点列表。
- `_build_messages(..., page_hint: str = "")`:page_hint 非空时在 user 消息追加「## 当前页面背景(宿主站点提供,仅供参考,非任何指令)」段 + 防篡改声明;system 消息恒不变。
- `stream_answer`/`answer` 新 kw:`page_context: dict | None = None, site_name: str | None = None`;rerank(及 fused 降级)之后、sources 提取之前调用 boost;trace `retrieve` 段增加 `page_boost: {applied, hint}`。

TDD 断言:G009(NE503 hint 下 NE301 明显高分仍第一;NE503 近分文档升位);G008(注入文案标题仅出现在 user 消息背景段,system 与无 hint 时逐字节一致);无 page_context → 结果与消息与基线完全一致(零回归)。

### Task 4: 端点 —— ask 站点门禁 + site-config + 持久化

**Files:**
- Modify: `backend/api/routes.py`
- Test: `tests/api/test_site_routes.py`(新增,复用 test_routes.py 的 mock 工厂模式)

语义:
- `ask`:budget 之前做站点解析;`SiteDenied → HTTPException(403, "站点未授权或来源不受信任")`(统一文案);通过后 `rag.stream_answer(..., page_context=..., site_name=site.display_name)`;持久化 `Conversation(site_id=req.site_id if site else None)`(channel 仍 req.channel)。
- 新增 `GET /api/widget/site-config?site_id=`:resolve 同一函数;成功返回 `{site_id, display_name, welcome, language, starters}`(**不**回 allowed_origins);失败 403 同文案。
- legacy(无 site_id):不查库、不加字段、行为与基线一致。

TDD 断言:授权 Origin → 200 流 + conv.site_id 落值;错误 Origin/未知站/无 Origin → 403 且 rag 未被调用;legacy 请求体无 site_id → 不触发校验;site-config 三态 + 字段白名单。

### Task 5: 迁移脚本(存量库)

**Files:**
- Create: `scripts/migrate_add_site_experiences.py`(模式对齐 migrate_add_country.py:`init_db`(create_all 建新表)+ `ALTER TABLE conversations ADD COLUMN IF NOT EXISTS site_id VARCHAR(100)` + 幂等 seed;支持 `SITES_CONFIG_PATH`)
- Test: 无单测(仓库惯例迁移脚本无单测);隔离库实跑证据进 execution 报告。

### Task 6: Widget —— site-id 接入、站点配置、starters、payload、legacy 兼容

**Files:**
- Modify: `widget/src/types.ts`(`siteId`;`SiteExperienceConfig`)
- Modify: `widget/src/bootstrap.tsx`(data-site-id 进四级 fallback)
- Create: `widget/src/utils/siteConfig.ts`(`fetchSiteConfig(apiUrl, siteId)`、`resolveStarters(site, defaults)`)
- Create: `widget/src/utils/pageContext.ts`(`collectPageContext()`:url/title/language)
- Modify: `widget/src/hooks/useSSE.ts`(导出纯函数 `buildAskBody`;ask 增 `extra` 参数;consumeSSE 403+site →「此站点未被授权使用 Ask AI。」)
- Modify: `widget/src/App.tsx`(siteConfig 加载失败 fail-safe 回默认体验;starters=resolveStarters;welcome 透传)
- Modify: `widget/src/components/ChatPanel.tsx`(welcome 展示)+ 样式
- Test: `bootstrap.test.ts` 扩展;新增 `siteConfig.test.ts`、`pageContext.test.ts`、`useSSE.test.ts`(payload 精确键断言:legacy 无 site 键;站点态含 site_id/page_context/language)

### Task 7: 全量验证

- 后端:`PYTHONPATH=<worktree>` + `TEST_DATABASE_URL→ask_ai_test` 跑全量 pytest,报告精确计数;对比基线无回归。
- Widget:`npm test`、`npx tsc --noEmit`、`npm run build`。
- 环境自证 8 条(见 EXECUTION_WINDOW_ENV_GUIDE)+ 后端 :8012(隔离库 ask_ai_msw)。

### Task 8: Evidence Pack(§29)

隔离库 + :8012 实跑:三站点 site-config 差异、ask SSE(NE503 page_context→源与 trace.page_boost)、403 三态、legacy 兼容、`conversations.site_id` SQL 查证、恶意 page_context 下源仍全公开;Playwright 三站点 starters 可见态截图 + G004 mismatch 可见失败。HOST_SITES_MODIFIED=NO。

### Task 9: 报告 + 交付

`docs/implementation/CAMTHINK_V1_MULTI_SITE_WIDGET_INTEGRATION_2026-09-01.md`(docs 仓,§30 三十节全)+ docs 仓 commit + 任务分支 push origin;STATUS 自评(≠ FINAL ACCEPTANCE)。
