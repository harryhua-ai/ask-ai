# CamThink V1 — 合作方测试 Origin 三站授权 Hotfix 生产部署报告

- 日期:2026-09-03
- STATUS:**PASS**(P1–P11 全过;零回滚)
- 用户产品决策:APPROVED;生产访问:本任务显式授权
- 前序背景:昨日 widget 单站 hotfix(ebe10b8,报告 cdcbc48/b9aebe8)+ 根因分析(/store/ 页 SITE_ID=camthink-store 而 IP 仅授权给 website)

## 1. Product Decision

合作方测试服务器 `http://42.194.138.11` 承载多页面(/、/wiki/、/store/),浏览器 Origin 统一为 `http://42.194.138.11`,按 `data-site-id` 区分三站体验。拍板:该 Origin 三站镜像授权。

## 2. Root Cause

Origin 授权按 site 精确匹配。昨日 hotfix 只把 IP 挂到 camthink-website;合作方 /store/ 页声明 `SITE_ID="camthink-store"`,`resolve_site("camthink-store", "http://42.194.138.11")` 在 store 的 allowed_origins(仅 https://store.camthink.ai)中查无此 Origin → SiteDenied → 403「此站点未被授权使用 Ask AI。」CORS 层无责(IP 已在生产 CORS,实证 preflight 回显)。

## 3. Git Lineage Before Integration(§2 调查实证)

- `main` = `origin/main` = **ebe10b8**(昨日 hotfix,经 ff 已入 main;= 当时生产)
- 阶段⑧⑨⑩ lineage:branch `worktree-exec/sync-isolation-20260902`(worktree `.worktrees/ingest-safety`)HEAD = **1b8572a**,commit 链 = f481f94(⑧)→ 8c27add/2933118(⑨)→ dd399dd/1b8572a(⑩)
- 两线 merge-base = `193f206`(确认 divergence);生产当时 = sha-ebe10b8

## 4. Authoritative Integration Baseline

- 分支 `fix/three-site-partner-origin-20260903`,自 **1b8572a** 起(保留全部阶段⑧⑨⑩),`git merge --no-ff ebe10b8`(**43cbe26**,merge-tree 预检零冲突,实际合并仅带出昨日 3 文件)→ 本次三站变更 **269cadb**
- 最终 lineage:193f206 → [⑧⑨⑩ 5 commits] → 43cbe26(merge ebe10b8)→ 269cadb

## 5. Source Changes(269cadb,2 文件 +57/−20)

1. `config/sites.yaml`:camthink-wiki / camthink-store 的 `allowed_origins` 各追加 `http://42.194.138.11`(canonical `scheme://host`,路径不进授权;camthink-website 已有不动)
2. `tests/services/test_site_experiences.py`:按 A1–A10 重写/新增(见 §7)

未改动:`deploy/prod/.env.example`(模板已含 IP,不动);CORS 相关零改动。

## 6. Security Invariants(冻结契约逐条保持)

exact origin ✓ / scheme 敏感(https 变体拒)✓ / 非默认端口敏感(:8080 拒)✓ / 无通配符 ✓ / 无路径授权(/store/ 不入 ACL)✓ / 无前缀/子串匹配(后缀欺骗拒)✓ / CORS 非授权层 ✓。`http://42.194.138.11/store/` → normalize → `http://42.194.138.11`。

## 7. Tests(隔离一次性库 `ask_ai_test_3site`,用后 DROP)

- 目标:`tests/services/test_site_experiences.py` + `tests/api/test_site_routes.py` = **35/35 PASS**
  - A1-A3 三站 × IP 授权 ✓(A2/A3 为本次新增 `test_bare_ip_origin_authorized_for_wiki_and_store`)
  - A4 相邻 IP / A5 https 变体 / A6 :8080 → 三站全拒 ✓(`test_unlisted_bare_ip_variants_denied_for_all_sites`)
  - A7 Referer 带路径(`http://42.194.138.11/store/foo`)归一化命中 ✓
  - A8 官方 origins 零回归 ✓(`test_official_origins_remain_authorized`)
  - A9 unknown/disabled 行为不变 ✓(既有用例)
  - A10 配置面禁通配符/带路径/裸 host ✓(`test_no_wildcard_or_path_origins_anywhere` + canonical 不变量)
- 合并树集成 sanity:阶段⑨ `test_sync_trigger_isolation.py` + `test_sync_triggered_by.py` = **18/18 PASS**
- 未跑全量套件(按契约 §5 快速通道条款;改动的授权/安全测试全绿)

## 8. Git Integration Evidence(§6 五血脉)

`git merge-base --is-ancestor` 实证(f481f94/8c27add/2933118/dd399dd/1b8572a/ebe10b8 全部 IN 269cadb);`git diff --stat main..269cadb` = 37 files +4553/−184(= 阶段体 + 昨日 hotfix + 本次变更,无其他内容)。

## 9. Build / CI Evidence

- workflow run **33711976094**(dispatch @ 候选分支):test ✅ + build-and-push ✅,conclusion=success

## 10. Source SHA

`269cadb0ce6a3ce47059e0f4b074f356e41612eb`(GIT_SHA build-arg 同值;三容器 /app/.git-sha 全串一致)

## 11. Image Tag

`ghcr.io/harryhua-ai/ask-ai:sha-269cadb`

## 12. Image Digest

index `sha256:1a88106cd8e040e72ba8d89b1f765afe31895f1e18f7b63c6deaa7787218e14c`;linux/amd64 `sha256:54ecc7e9a4ede2111644cd2c54b4fba89bd423d4e03637801c8b971841e780dc`;服务器本地 `docker images --digests` 与 GHCR index 一致(P2)。

## 13. Previous Production Image

`ghcr.io/harryhua-ai/ask-ai:sha-ebe10b8`(index `sha256:5010e1da…`;镜像仍在服务器,回滚锚)

## 14. Deployment Steps

1. 预检:生产=sha-ebe10b8 healthy;生产 `.env` CORS 仍含 IP(无 discrepancy);sync 前一轮 03:39 已收尾(无运行中 sync,满足红线)
2. compose 同步:服务器旧版 compose 无 sync-executor → 备份 `docker-compose.yml.bak-ebe10b8-3site` 后 scp 候选版(diff 仅注释 + sync-executor 服务块)
3. `./deploy/prod/update.sh sha-269cadb`:compose pull → GPU 预检 → backend 重建+健康轮询 ✅ → sync-cron 重建
4. `ASKAI_IMAGE_TAG=sha-269cadb docker compose up -d sync-executor`(release 必需服务:Admin 手动同步改写 sync_requests 交接行,由本服务领用执行;不启动则手动同步静默失效)
   - ⚠️ 教训:首次启动漏带 ASKAI_IMAGE_TAG,compose 插值回落 `:latest` 导致 wrong-image 崩溃循环;发现后带正确 tag 重建,现 git_sha 三容器一致
5. schema:backend lifespan `init_db(create_all)` 自动建 `sync_requests`(含 attempt_started_at 等恢复列),**零手工迁移**(psql 实证 to_regclass = sync_requests);seed 日志「站点体验配置已同步(3 个站点)」

## 15. SiteExperience Production Truth(部署后 psql 只读)

```
camthink-store|["https://store.camthink.ai", "http://42.194.138.11"]
camthink-website|["https://www.camthink.ai", "https://camthink.ai", "http://42.194.138.11"]
camthink-wiki|["https://wiki.camthink.ai", "http://42.194.138.11"]
```

## 16. Real Partner /store Acceptance(P6,API 行为证据 = widget 实际请求路径)

经公网 `https://wiki-data.camthink.ai`(nginx)以 `Origin: http://42.194.138.11` + `site_id=camthink-store`:
- `GET /api/widget/site-config` → **200**,返回 store 体验(welcome="Shopping for a CamThink device?…",store 推荐问题)
- `OPTIONS /api/ask` preflight → 200,`access-control-allow-origin: http://42.194.138.11`(精确回显)

合作方页面上 widget 发出的就是这两个请求,现已全通;合作方刷新页面即可用。

## 17. Negative Security Tests

| Origin | 结果 |
|---|---|
| http://42.194.138.12(相邻 IP) | 403;preflight 无 ACAO |
| https://42.194.138.11(scheme 变体) | 403 |
| http://42.194.138.11:8080(非默认端口) | 403 |
| http://42.194.138.11.evil.com(后缀欺骗) | 403 |

CORS preflight 回显精确 origin,**非 `*`**。

## 18. Rollback Artifact

- IMAGE:`sha-ebe10b8`(在服务器,`./update.sh sha-ebe10b8` 一键回滚)
- ENV:`~/ask-ai/.env`(本次未改);compose 备份 `docker-compose.yml.bak-ebe10b8-3site`
- **ROLLBACK = NOT_REQUIRED**(全验收通过)

## 19. Production Access Log(本任务全部生产操作)

只读:容器/git_sha/health/CORS 行/compose 检查、psql SELECT(site_experiences/sync_requests/sync_log/information_schema)、线上 API 验收请求、sync 日志检查。
写:compose 文件更新(备份在位)、`update.sh sha-269cadb`(镜像+backend+sync-cron)、`up -d sync-executor`(两次:首漏 tag 已即时纠正)、backend lifespan 自动 seed/auto create_all。

## 20. Sync / Corpus Statement(P11)

本任务零手动 sync/corpus 触发:`sync_requests` = 0 行,无手动 sync 命令。sync_log 中 03:44 起的新行 = sync-cron 容器重建后**自身 while 循环设计的例行增量周期**(每次部署皆然;03:34–03:39 前一轮在部署前已正常收尾,未被中断);partial 项为部署前即存在的同款瞬时失败,与新镜像无关。

## 21. Main Integration

本任务契约不含 main 集成章节:**main 仍 = ebe10b8,生产 = sha-269cadb(领先 main)**。main 的 Integration Gate(纳入 269cadb)留待 Planner 决定;未强推、未自动 merge。

## 22. Final Status

**PASS** — P1 ✅ health;P2 ✅ image/tag/digest 一致;P3/P4/P5 ✅ 三站授权;P6 ✅ /store/ 真实语义;P7 ✅ 官方 origins 零回归;P8 ✅ 负向全拒;P9 ✅ CORS 精确非通配;P10 ✅ SSE sources(1)+token(288)+done(1) 契约完整;P11 ✅ 零 sync/corpus mutation。零回滚。
