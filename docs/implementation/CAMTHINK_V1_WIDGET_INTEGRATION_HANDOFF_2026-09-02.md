# CAMTHINK_V1_WIDGET_INTEGRATION_HANDOFF — 2026-09-02

任务:HANDOFF-G001 — 三站(Website/Wiki/Store)Widget 接入交付包
角色:Codex D(并行执行;其他线 = Corpus Integrity P0 / Citation & Conversational UX / Sales Lead Capture)

## 1. Baseline

| 项 | 值 |
|----|----|
| BASELINE_COMMIT | `1ff2936e37944af946fd691b47febbee01622a75`(`release/camthink-v1-rc-2026-09-01` tip,= origin) |
| 选基线理由 | RC 线 = main(76b2199,全部 FINAL PASS 合入)+ 统一集成门(9fffa0e,MSW 多站点 Widget 并入)+ RC 发布(1ed84bb)+ PA-0D/E/F 证据文档;**生产 backend 正运行该线镜像(sha-1ed84bb)** → 文档与生产现实对齐。不含任何并行线未验收修改(三并行线各在独立 worktree:-sales-lead@76b2199 等) |
| BRANCH | `worktree-exec/widget-integration-handoff` |
| WORKTREE | `/Users/harryhua/Documents/GitHub/ask-ai/.worktrees/widget-handoff` |
| worktree 复用检查 | 已复核 `git worktree list --porcelain`:multi-site-widget(他窗)、product-ux-closure-b(疑似 UX 线)、sales-lead(Lead 线)、v1-integration-checkpoint(用户测试栈)、technical-insights(RC 分支占用)均不安全复用 → 新建独立树 |

## 2. Evidence Sources(全部来自真实工程,零猜测)

| 证据 | 文件/位置 | 结论 |
|------|----------|------|
| Widget 构建定义 | `widget/vite.config.ts` | IIFE lib 构建,`fileName: () => "widget.js"`,globalName `AskAIWidget`,cssCodeSplit=false(产物为独立 .css) |
| 实际构建产物 | 本地 `npm run build` 输出 | `dist/widget.js`(251,209 B,gzip 88.38 kB)+ `dist/ask-ai-widget.css`(5,059 B);CSS 规则经 grep 定性**仅存在于 .css**,widget.js 不自注入样式 |
| 生产服务方式 | `backend/main.py:513-538` | dist 存在时挂载 `/widget`(CachedStaticFiles,`Cache-Control: public, max-age=300`);`Dockerfile:65-66` COPY admin/dist + widget/dist 入镜像 |
| 生产 API 端口证据 | `deploy/prod/docker-compose.yml:99-100`、`deploy/prod/update.sh` | 宿主 `18000:8000`;PA-0D 报告"经生产 backend localhost:18000(同线上 nginx 反代入口)" |
| 生产公网域名 | 全仓检索(deploy/config/docs) | **无任何公网 API 域名证据**;PA-0D/0E 明确"未动 DNS/nginx、未激活 CORS/widget/站点集成" |
| Bootstrap 契约 | `widget/src/bootstrap.tsx`、`index.tsx`、`types.ts` | 容器 `#ask-ai-widget-root`;逐键四级 fallback:script data-* → 预置容器 data-* → `window.AskAIConfig` → 默认(apiUrl `http://localhost:8000`,primaryColor `#f24a00`);容器已有内容即跳过挂载(防双浮窗) |
| 站点配置获取 | `widget/src/utils/siteConfig.ts`、`backend/api/routes.py:305-326` | `GET {apiUrl}/api/widget/site-config?site_id=…`;服务端同样做 Origin 校验;403/网络失败 → Widget 静默回退默认体验;响应仅体验字段(site_id/display_name/welcome/language/starters),**不回** allowed_origins |
| Page Context | `widget/src/utils/pageContext.ts`、`widget/src/App.tsx:103`、`backend/api/schemas.py:32-49` | 自动采集 url/title/language(每次发送时实时,宿主不可覆盖);宿主经 `window.AskAIConfig.pageContext` 提供 page_type/product/product_id/sku/section;后端 `PageContext` 模型 extra=ignore,url 仅 http/https,长度上限 2048/300/50/100/100/100/200/20 |
| page_context 语义 | `tests/pipeline/test_page_context_boost.py` | 冻结语义:SOFT BOOST(乘性加权+稳定重排),**绝不过滤/增删候选**;非信任提示,不进 system 消息,不构成事实依据 |
| ask 端点 | `backend/api/routes.py:86-136`、`widget/src/hooks/useSSE.ts` | POST `/api/ask`(SSE);body=message/channel/conversation_history(尾 10)/session_id(localStorage UUID)/attachments(≤5)+可选 site_id/page_context/language;事件 sources/token/error/declined/done;限流 20/min/IP;预算熔断→declined;显式 site_id 403 文案"此站点未被授权使用 Ask AI。" |
| site_id 规范化 | `backend/api/schemas.py:106-116` | trim+小写;形状 `^[a-z0-9][a-z0-9-]{0,98}[a-z0-9]$`,非法 422 |
| Origin 授权 | `backend/services/site_experiences.py` | site_id 非凭证;授权=enabled+Origin 归一化(`scheme://host[:port]` 小写,默认端口剥离)后**精确命中** allowed_origins;Origin 头缺失回退 Referer;未知/禁用/无来源/不匹配→`SiteDenied`→403 统一文案;无通配符支持 |
| 站点身份权威源 | `config/sites.yaml`(lifespan 幂等 upsert 进 `site_experiences` 表) | camthink-website(www+非 www,en)/ camthink-wiki(wiki,zh)/ camthink-store(store,en);starters/welcome 三站语义分离 |
| 浏览器 CORS 层 | `backend/main.py:467-480`、`deploy/prod/.env.example` | `CORS_ALLOW_ORIGINS` env(默认仅 localhost 三件套);allow_methods GET/POST,headers Content-Type;生产模板=www/wiki/store 三来源(**不含非 www camthink.ai**) |
| 布局事实 | `widget/src/styles/widget.css` | fixed 定位,z-index 99999,面板 max-width 480px,`@media (max-width: 640px)` 移动端断点 |
| 嵌入参考页 | `widget/devtest.html` | 真实可运行样例:`<link dist/ask-ai-widget.css>` + `<script dist/widget.js>`;`test-embed.html` 缺 CSS link(历史坑,已在新文档纠正为强制成对) |

## 3. 核心结论

- **Actual Widget Artifact**:`widget.js`(IIFE,全局 `AskAIWidget`)+ `ask-ai-widget.css`,二者**必须成对引入**;由 Ask AI 后端同源托管于 `/widget/` 路径。
- **Actual API URL**:生产后端 = tesla-t4 宿主 `:18000`(容器 8000),宿主 nginx 反代存在;**公网 API 域名无工程证据**。
- **Production Widget URL status**:`PRODUCTION_WIDGET_URL_READY = NO`。路径机制已就绪(`{API}/widget/widget.js`),缺的是公网基址(DNS/反代/CORS 激活)。BLOCKER 见 §6。
- **Site IDs**:三站与冻结语义**完全一致**,无 discrepancy,未触发 STOP。
- **双层授权**要点:site_id 非凭证;服务端 per-site allowed_origins 精确匹配(website 含非 www)+ 浏览器 `CORS_ALLOW_ORIGINS`(生产模板不含非 www)→ 文档已给 Website"统一走 www"的落地指引,并把非 www 列为 Ask AI 侧待办。
- **Wiki/Store 技术栈**:repo 内无证据 → 文档按 framework-neutral 编写,未做栈假设(NOT_VERIFIED,如实标注)。

## 4. Verification(任务 §15 逐项)

| 验证项 | 命令/方法 | 结果 |
|--------|----------|------|
| Widget tests | `npm test`(vitest) | **57/57 通过**(7 文件:bootstrap 10、bootstrapSite 4、useSSE 5+5、sanitize 24、siteConfig 6、pageContext 3) |
| Widget typecheck | `npx tsc --noEmit` | **PASS** |
| Widget build | `npm run build` | **PASS**,产物名实证 `widget.js` + `ask-ai-widget.css` |
| 产物文件名 | dist 目录清单 + vite.config | 一致;`/widget/widget.js`、`/widget/ask-ai-widget.css` 托管路径由 main.py 挂载实证 |
| 文档 config key 与源码一致 | grep 交叉验证(data-api-url/data-site-id/data-language/data-primary-color/pageContext 八键/端点/文案/20-per-min/max-age=300/z-index/断点) | 全部命中(data-primary-color 在源码为 dataset 驼峰 `primaryColor`,标准 HTML 映射,测试锚定) |
| site_id 与 sites config 一致 | `config/sites.yaml` grep | camthink-website / camthink-wiki / camthink-store 三站齐,与冻结语义一致 |
| production/deployment URL evidence | 全仓检索 + PA-0D/E 报告 | 内网 :18000 有据;公网域名无据 → 文档按 NOT READY 处理,零虚构 URL |
| 后端行为回归(站点门禁/403 语义) | 由既有 pytest 套件覆盖(resolve_site/site-config/ask 403 路径均有测试);本轮未重复全量后端回归(零后端代码改动) | NOT_APPLICABLE(无代码变更;未触碰后端行为) |

## 5. HANDOFF-G001..G014

| Gate | 结论 | 依据 |
|------|------|------|
| G001 三 site_id 与真实工程一致 | **PASS** | §2 sites.yaml 证据;与任务冻结语义逐字符一致 |
| G002 API URL 来自真实工程证据 | **PASS** | :18000 宿主端口(compose/update.sh/PA-0D);公网域名如实标 NOT_VERIFIED |
| G003 Widget production URL 来自真实证据或明确标未 Ready | **PASS** | `PRODUCTION_WIDGET_URL_READY = NO` + BLOCKER 清单;托管路径有代码证据 |
| G004 Embed syntax 与真实 bootstrap 一致 | **PASS** | 两行标签形态=devtest.html 实例 + bootstrap.tsx 四级 fallback;CSS 必配经构建产物 grep 定性 |
| G005 Page Context Contract 与真实实现一致 | **PASS** | pageContext.ts/schemas.PageContext/boost 测试三方对齐;自动 vs 宿主字段边界如实 |
| G006 Origin/CORS/site authorization 描述与真实实现一致 | **PASS** | site_experiences.py 归一化精确匹配/无通配符/scheme 必配 + main.py CORS env 双层模型;www/非 www、localhost、wildcard 均按实现写明 |
| G007 Website 可执行接入示例 | **PASS** | 文档 §6-A:全站模板 + 产品页 pageContext |
| G008 Wiki 可执行接入示例 | **PASS** | 文档 §6-B:documentation pageContext |
| G009 Store 可执行接入示例 | **PASS** | 文档 §6-C:product/product_id/sku |
| G010 Desktop/Mobile/SPA/重复加载验证要求 | **PASS** | §7.2 SPA、§7.4 移动端/层级、§8 防重复、§9 Checklist 含全部四类 |
| G011 完整 Troubleshooting | **PASS** | §10 覆盖任务列出的全部 9 症状 + 证据包清单 |
| G012 Host 无需读源码即可理解 | **PASS** | 面向宿主的完整闭环:接入→行为→验收→排障→职责边界;无内部实现术语泄漏 |
| G013 无虚构 Production URL/API/config | **PASS** | 唯一占位符 `<ASK-AI-PRODUCTION-API-BASE>` 显式标注"待 Ask AI 团队提供,勿猜";CORS 清单取自 .env.example 原文 |
| G014 无 Production access / mutation | **PASS** | 全程本地只读+构建;未 SSH、未改生产、未跑迁移、未碰 CORS 生产配置 |

## 6. Integration Blockers(ASK-AI 侧,均已在文档 §0 向宿主声明)

| # | Blocker | 需要谁提供什么 |
|---|---------|---------------|
| B1 | 生产公网 API 基址未建立(DNS/宿主 nginx 反代 `/widget` + `/api` → :18000) | ASK-AI 团队/运维:确定并公布基址,配置反代(建议 https) |
| B2 | 生产 `CORS_ALLOW_ORIGINS` 激活(当前生产未激活,.env 模板三来源;PA-0E 证实"未触 CORS") | ASK-AI 团队:按 RC 激活清单阶段 5 落地 |
| B3 | 站点前置:site_experiences 种子(启动自动,幂等)已随镜像就绪;**P0 红线**:公开暴露前须完成 channel_visibility 迁移(RC 激活清单阶段 2,超出本任务范围,仅提示依赖顺序) | ASK-AI 团队:按 RC-2026-09-01-ACTIVATION.md 阶段顺序执行 |
| 附加 | 非.www `https://camthink.ai` 在服务端授权内但不在生产 CORS 模板 → 若官网要支持非 www 直达,需追加 CORS 项,或官网侧 301 到 www | 二选一,Ask AI 团队与官网负责人对齐 |

## 7. Modified Files

| 文件 | 变更 |
|------|------|
| `docs/integration/CAMTHINK_WIDGET_INTEGRATION.md` | 新增(核心交付:三站接入指南,面向网站负责人) |
| `docs/implementation/CAMTHINK_V1_WIDGET_INTEGRATION_HANDOFF_2026-09-02.md` | 新增(本报告) |

无任何产品代码/后端/配置/测试代码变更。widget/dist、node_modules 为本地构建验证产物,已 gitignore 不入库。

## 8. Final Commit

- BRANCH = `worktree-exec/widget-integration-handoff`
- FINAL_COMMIT = 见文末 git 记录(本报告与指南同一提交)
- PUSHED = 推送至 `origin/worktree-exec/widget-integration-handoff`

## 9. Scope Compliance

- 未修改 Product Code;未 SSH 生产;未 DB 迁移;未 Weaviate/Corpus/Sync;未 CORS 生产 mutation;未 Lead/Citation/Multi-Site 语义改动;无 off-topic 重构。
- 唯一新增"示例文件"为零(接入示例全部内嵌于指南文档,未新增 sample 仓库文件,避免样例漂移)。
