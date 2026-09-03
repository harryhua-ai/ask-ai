# CamThink V1 — Issue #8 Store Widget Origin 生产修复报告(已授权执行)

- 日期:2026-09-03
- 执行端:Executor(生产部署授权:AUTHORIZED,范围=camthink-store 正式 Origin
  生效 + 真实页面 smoke + 邻接回归)
- 候选/发布内容:`c83d21443732499313cb1dc3870e6ec186f24f64`
  (docs 仓报告:CAMTHINK_V1_STORE_WIDGET_ORIGIN_FIX_2026-09-03.md @ adc96a4)
- 状态:**PASS**

## 1. STATUS

**PASS** — 全部 Required 项完成并逐项实证;零回滚;无范围外生产变更。

## 2. OLD_RELEASE → NEW_RELEASE

| 项 | 值 | 证据 |
|---|---|---|
| OLD_RELEASE | `sha-1d6f6b5`(revision=1d6f6b5fe69…) | 部署前 backend 容器 image + `org.opencontainers.image.revision` label 实测 |
| NEW_RELEASE | `sha-c83d214`(revision=c83d2144373…) | 部署后 backend/sync-cron/sync-executor 三容器 label 实测一致 |
| 发布通道 | 正式发布流程 | FF 集成 c83d214 → `origin/main`(d4dc676..c83d214,远端核验一致)→ CI `Build & Push GPU Image` run **33740749903**(test ✓ + build-and-push ✓ 双绿)→ `ghcr.io/harryhua-ai/ask-ai:sha-c83d214` → `deploy/prod/update.sh sha-c83d214` |

## 3. DEPLOYED_COMMIT

`c83d21443732499313cb1dc3870e6ec186f24f64`(= main tip = 生产运行版本)。

部署动作(全部按既有合同,未手工改任何运行时数据):

1. 前置预检:磁盘 947G 空闲;`sync_runs` 无 running(87 号 website-camthink
   cron 增量已自然收工)后才动 sync-executor;备份
   `~/ask-ai-backup/site_experiences_pre_c83d214_20260903.sql`(37 行,含全部三站改前值)。
2. `./deploy/prod/update.sh sha-c83d214`(ASKAI_IMAGE_TAG 注入;backend 先行 +
   health 有界轮询 → sync-cron);
3. **显式补 `up -d sync-executor`**(update.sh 覆盖面之外;三服务统一 = 1d6f6b5
   部署同款惯例);
4. postgres / weaviate 容器零触碰(up 2 weeks 不变)——corpus / vectors /
   data sources 完全未动(Required #7/#8)。

## 4. RUNTIME_SITE_CONFIG(权威 upsert 实证)

新 backend lifespan `seed_default_sites` 启动时自动把镜像内 `config/sites.yaml`
幂等 upsert 进 `site_experiences`——**无任何手工 DB 写入**。部署后生产 DB 实测:

| site_id | enabled | allowed_origins(部署后) | 部署前 |
|---|---|---|---|
| camthink-store | t | `["https://www.camthink.ai", "http://42.194.138.11"]` | `["https://store.camthink.ai", "http://42.194.138.11"]` |
| camthink-website | t | `["https://www.camthink.ai", "https://camthink.ai", "http://42.194.138.11"]` | 同前(零变化) |
| camthink-wiki | t | `["https://wiki.camthink.ai", "http://42.194.138.11"]` | 同前(零变化) |

✅ camthink-store **包含** `https://www.camthink.ai`;✅ **不包含**
`https://store.camthink.ai`;✅ website(apex REDIRECT 契约)/wiki 逐字节不变。

## 5. STORE_PAGE_SMOKE(真实页面,真实浏览器)

页面:`https://www.camthink.ai/store/neoeyes-503/`(Playwright 真实 Chromium):

1. Widget 挂载(`#ask-ai-widget-root` + `.ask-ai-fab`),点击展开,面板显示
   **camthink-store 专属体验**(welcome「Shopping for a CamThink device?…」
   + 4 个 store starters —— 来自已授权的 site-config);
2. 真实输入提问「What is NeoEyes NE503? One sentence.」→ Send → SSE 流式返回
   **完整有据答案**:
   > "NeoEyes NE503 is a 4K PoE edge AI camera built on the Hailo-15H SoC with
   > 20 TOPS on-device inference, combining Sony IMX678 4K imaging, RTSP
   > streaming, structured event output, and containerized AI application
   > deployment…"
3. **「此站点未被授权使用 Ask AI」横幅:未出现**(DOM 全文断言 denied=false);
4. 截图证据:`store-origin-fix-evidence-20260903/store-widget-answer-ne503.png`
   (可见页面面包屑 STORE » NE503 与 widget 同框作答);
5. 服务端双保险:同 Origin 的 `POST /api/ask`(session_id=
   `deploy-smoke-c83d214-store`)返回 sources(命中 store 页本体 + wiki NE503
   overview + 官网新闻,BGE 检索正常)+ token 流;负例 ask(废弃子域 Origin)
   → **403** 拒绝,不触发生成。

## 6. 邻接回归

**端点级矩阵**(生产公网 `https://wiki-data.camthink.ai`,`GET
/api/widget/site-config`,11/11 符合合同):

| 组合 | 结果 |
|---|---|
| camthink-store + `https://www.camthink.ai` | 200 ✅ |
| camthink-store + `https://www.camthink.ai/store/neoeyes-503/`(带 path)| 200 ✅(授权只看 Origin) |
| camthink-store + `https://store.camthink.ai`(废弃)| **403** ✅ |
| camthink-website + `https://www.camthink.ai` | 200 ✅ |
| camthink-website + `https://camthink.ai`(apex,REDIRECT 契约)| 200 ✅ |
| camthink-wiki + `https://wiki.camthink.ai` | 200 ✅ |
| 三站 × `http://42.194.138.11`(临时合同)| 200/200/200 ✅ 零回归 |
| camthink-store + `https://evil.example`(unknown)| **403** ✅ |
| camthink-store + 无 Origin | **403** ✅ |

**真实页面级**:

- ✅ `https://www.camthink.ai/`:widget 展开,显示 camthink-website 体验
  (「Hi! I'm the CamThink assistant…」);
- ✅ `https://wiki.camthink.ai/`:widget 展开,显示 camthink-wiki 体验
  (「Ask me anything about CamThink device docs, configuration, and
  troubleshooting.」+ wiki starters);
- ✅ `http://42.194.138.11`:既有授权经端点矩阵三站 200 实证(该测试页内容
  归属方维护,页面级复核与本次修复无耦合);
- ✅ unknown Origin 拒绝:见上矩阵(service-config 与 /api/ask 双端点)。

## 7. PRODUCTION_MUTATIONS(授权范围内全额列账)

1. 镜像切换:backend / sync-cron / sync-executor 三容器 sha-1d6f6b5 → sha-c83d214;
2. `site_experiences.camthink-store.allowed_origins` 由新镜像 lifespan seed
   自动 upsert(非手工 DB 操作);
3. 备份文件新增:`~/ask-ai-backup/site_experiences_pre_c83d214_20260903.sql`;
4. 冒烟产生的正常业务数据:1 条 store 冒烟对话(session_id=
   `deploy-smoke-c83d214-store`)+ 常规 hourly cron 增量同步(既有行为,非新触发)。

**范围外变更:无。** corpus / vectors / data sources / 迁移 / CORS / nginx 零触碰。

## 8. 回滚路径(备用,未动用)

`ssh tesla-t4 'cd ~/ask-ai && ./deploy/prod/update.sh sha-1d6f6b5'`(旧镜像在位)
+ 必要时回灌备份 SQL;回滚后 store 页将回到 403 状态(即修复前行为)。

## 9. Final

```
STATUS:                 PASS
OLD_RELEASE:            sha-1d6f6b5
NEW_RELEASE:            sha-c83d214
DEPLOYED_COMMIT:        c83d21443732499313cb1dc3870e6ec186f24f64(main=生产,FF 零漂移)
RUNTIME_SITE_CONFIG:    site_experiences 三行实测见 §4;store=www+临时IP,废弃子域消失,
                        website/wiki 逐字节不变(lifespan 权威 upsert,非手工)
STORE_PAGE_SMOKE:       PASS(真实浏览器:store 体验欢迎+流式有据答案+无拒绝横幅;截图在案;
                        SSE ask sources 命中 NE503 语料;负例 ask 403)
WEBSITE_REGRESSION:     PASS(端点 www+apex 200;真实页面 website 体验正常)
WIKI_REGRESSION:        PASS(端点 wiki 200;真实页面 wiki 体验正常)
TEMP_SITE_REGRESSION:   PASS(http://42.194.138.11 三站 200 零回归)
UNKNOWN_ORIGIN_NEGATIVE: PASS(unknown 403/无 Origin 403/废弃子域 403,site-config 与 ask 双端点)
PRODUCTION_MUTATIONS:   §7 全额列账(镜像三服务切换+seed upsert+备份+冒烟对话);范围外=无
REPORT_PATH:            docs/implementation/CAMTHINK_V1_STORE_WIDGET_ORIGIN_PRODUCTION_FIX_2026-09-03.md
REPORT_COMMIT:          docs 仓(见 HEAD)
```
