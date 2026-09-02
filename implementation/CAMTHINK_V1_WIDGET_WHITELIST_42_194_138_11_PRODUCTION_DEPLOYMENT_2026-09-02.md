# Widget 白名单 42.194.138.11 生产部署报告(Fast-Lane Widget-Only Hotfix)

- 日期:2026-09-02
- STATUS:**PASS — PARTNER PAGE SMOKE PENDING**(生产侧 15/15 AC 全过;唯一 pending = 合作方页面尚未嵌入 widget 片段,见 §17)
- 实现报告:[ASK_AI_WIDGET_WHITELIST_42_194_138_11_2026-09-02.md](ASK_AI_WIDGET_WHITELIST_42_194_138_11_2026-09-02.md)(cdcbc48)
- Planner 独立验收:WIDGET WHITELIST IMPLEMENTATION FINAL REVIEW = PASS

## 1. Executive Result

`http://42.194.138.11`(camthink-website 合法 Widget Origin)已在生产生效:镜像 `sha-ebe10b8` 上线(backend+sync-cron)、生产 CORS 安全追加、runtime site policy 由 lifespan 自动 seed 落库、线上验收 A-F 全过、负向安全全拒、既有三站零回归、零回滚。

## 2. Authorization Boundary

仅限:将 `http://42.194.138.11` 加入生产 Widget 允许来源并部署对应 widget-only release。明令禁止项(Data Source Reliability/阶段⑧/⑨/corpus/sync/database cleanup/neoruntime-apps/其他配置)全程零接触。

## 3. Production Baseline(部署前实测)

- backend+sync-cron 镜像 = `ghcr.io/harryhua-ai/ask-ai:sha-193f206`,容器内 `/app/.git-sha` = `193f206a3d0e8695f1c40766a1ba54667fcba2fb`(全串一致)
- `/health` = ok;postgres/weaviate uptime 2 周(未触碰)
- 生产 `.env` CORS 真实值 = `https://www.camthink.ai,https://wiki.camthink.ai`(**store 不在生产 CORS**——与 handoff 文档一致,本次未加,不越权)
- 磁盘 279G/1.3T;GPU 14783/16384 MiB(未触发 update.sh 告警阈值)

## 4. Release Composition Evidence

- `git merge-base main ebe10b8` = `193f206…`;`git rev-list --count main..HEAD` = **1**
- `git diff --name-only 193f206..ebe10b8` = 恰好 3 文件:`config/sites.yaml`、`deploy/prod/.env.example`、`tests/services/test_site_experiences.py`
- `git log main..HEAD` = 仅 `ebe10b8` 一个 commit;无阶段⑧(f481f94)/⑨/Data Source/Sync 内容 → 组合门 PASS

## 5. Tests(部署前复跑,§4)

一次性隔离库 `ask_ai_test_wl42`(用后 DROP):`tests/services/test_site_experiences.py` + `tests/api/test_site_routes.py` = **33/33 PASS**(目标 origin 允许/相邻 IP 拒/https 变体拒/:8080 拒/wiki-store 不连带/既有 origins 无回归)。已知 4 个 embedder 基线既有失败(main@193f206 同败)未纳入本 hotfix 归因;部署前后均无新增 whitelist/site/CORS 回归。

## 6. CI / Build Artifact

- workflow:**33625668606**(`build-image.yml` dispatch @ `fix/widget-whitelist-42-194-138-11`),test ✅ + build-and-push ✅
- source SHA:`ebe10b89b6748f94adc20e80accb561f35a3c84f`(`GIT_SHA` build-arg 同值)
- image tag:`ghcr.io/harryhua-ai/ask-ai:sha-ebe10b8`
- main ff 集成后 push 触发的 main CI 从同一 commit 构建(同 tag 同源,可追溯)

## 7. Image Digest

- index digest:`sha256:5010e1da2d72f267602c69fcd3103f53adb87c81d5a6b228b490f2dcc528429a`
- linux/amd64:`sha256:feda9d199d045f69136c3d6ea9a52e5a961947986154cb978a84ae10a17a92b6`(unknown/unknown = provenance attestation)

## 8. Production Preflight

见 §3;结论:生产仍处 193f206 预期 lineage,无其他窗口改动迹象 → 放行部署。部署前另查:sync-cron 最后一轮 11:52:28 完成(无 sync 运行中,满足「sync 运行中禁 restart」红线)。

## 9. Sanitized CORS Change

1. 备份:`~/ask-ai/.env` → `~/ask-ai/.env.bak-wl42-ebe10b8`(权限/属主保留;内容未入报告/日志)
2. 幂等追加(grep 守卫 + sed 仅锚定 `^CORS_ALLOW_ORIGINS=` 行尾)
3. diff 实证:**仅第 35 行一行变化**,无任何既有 origin 删除/替换:
   - before:`CORS_ALLOW_ORIGINS=https://www.camthink.ai,https://wiki.camthink.ai`
   - after:`CORS_ALLOW_ORIGINS=https://www.camthink.ai,https://wiki.camthink.ai,http://42.194.138.11`
4. 无 `*`、无 regex、无相邻 IP/https 变体/其他端口;JWT/密钥等未触碰

## 10. Runtime Site Policy Activation

新镜像 backend 启动时 lifespan `seed_default_sites` 幂等 upsert(启动日志:`站点体验配置已同步(3 个站点)`),**零手工 SQL**。psql 只读复核:

```
camthink-store|t|["https://store.camthink.ai"]
camthink-website|t|["https://www.camthink.ai", "https://camthink.ai", "http://42.194.138.11"]
camthink-wiki|t|["https://wiki.camthink.ai"]
```

## 11. Deployment

`./deploy/prod/update.sh sha-ebe10b8`(既有机制):compose pull → GPU 预检 → `up -d backend` → 有界健康轮询 ✅ → `up -d sync-cron`。UPDATE_EXIT=0。nginx/DNS/其他服务未动。

## 12. Health

- `/health` = `{"status":"ok"}`(update.sh 轮询内通过)
- backend 容器 healthy;`docker logs` traceback 计数 = **0**
- 两容器 `/app/.git-sha` = `git_sha=ebe10b89b6748f94adc20e80accb561f35a3c84f`(backend+sync-cron 同 lineage)

## 13. New Origin Acceptance(server :18000 + 公网 https://wiki-data.camthink.ai 双路)

- `GET /api/widget/site-config?site_id=camthink-website`(Origin: http://42.194.138.11)→ **200**,返回体验字段(welcome/starters/language)
- 公网经 nginx 同请求 → **200**

## 14. Existing Origin Regression

www(camthink-website)/ wiki(camthink-wiki)/ store(camthink-store)site-config → 全 **200**(store 为服务端授权层 200;其浏览器 CORS 缺席为已知既有状态,未在本次授权范围内改动)

## 15. Negative Security Acceptance

| 变体 | site-config | CORS preflight |
|------|-------------|----------------|
| `http://42.194.138.12`(相邻 IP) | 403 | 400,无 ACAO 头 |
| `https://42.194.138.11`(scheme 变体) | 403 | — |
| `http://42.194.138.11:8080`(非默认端口) | 403 | — |
| `http://42.194.138.11.evil.com`(后缀欺骗) | 403 | — |

CORS preflight(新 origin)回显 `access-control-allow-origin: http://42.194.138.11`(精确 echo,**非 `*`**);实际 GET 同样回显。

## 16. Widget API Smoke

- `POST /api/ask`(Origin: http://42.194.138.11,site_id=camthink-website,session_id=`deploy-smoke-ebe10b8-0902`)→ SSE `token` + `done`,站点门→LLM 全链通
- 负向:同请求 Origin=http://42.194.138.12 → **403**(无副作用)

## 17. External Page Smoke

`http://42.194.138.11/` 本机可达(HTTP 200,197KB,Next.js SSR,CamThink 官网镜像,构建标记 2026-08-27)。页面 SSR HTML **尚无 ask-ai/widget 脚本引用** —— 合作方尚未贴入接入片段。

**EXTERNAL PAGE FINAL SMOKE = PENDING PARTNER**(生产侧 Origin/CORS/API 验收全 PASS;合作方嵌入后建议跑一遍集成文档 §验收清单)。

## 18. Rollback Readiness

- IMAGE:`ghcr.io/harryhua-ai/ask-ai:sha-193f206` 仍在服务器(docker images 实证,ID b8528b586275)
- ENV:`~/ask-ai/.env.bak-wl42-ebe10b8`(回滚时还原 CORS 行)
- 回滚命令:`cd ~/ask-ai && ./deploy/prod/update.sh sha-193f206` + 恢复 .env;**禁止以 CORS=\* 代替回滚**

## 19. Main Integration

`origin/main` 部署时仍为 `193f206`(无 divergence)→ `git merge --ff-only ebe10b8` + push:**main = origin/main = ebe10b8**,恰好 +1 commit,零 merge commit、零强推。main push 触发的 CI 同 commit 构建(同 tag)。

## 20. Production Mutations Performed

1. `~/ask-ai/.env`:`CORS_ALLOW_ORIGINS` 追加 `http://42.194.138.11`(备份已建,diff 单行)
2. `update.sh sha-ebe10b8`:拉取镜像并替换 backend + sync-cron(all-in-one 镜像双服务同 tag 为既有升级规则;release diff 证明 sync 路径代码零变化)
3. backend 启动 lifespan 自动 seed `site_experiences`(既有机制,无手工 SQL)

## 21. Explicit Non-Mutations

corpus 零变更;未触发任何 sync;Weaviate/postgres 容器未动(uptime 延续);无 Data Source/stage⑧(f481f94)/stage⑨ 代码或镜像内容;nginx/证书/DNS 未动;`.env` 其余变量未动;未手工执行任何 migration 脚本。

## 22. Final Status

**PASS — PARTNER PAGE SMOKE PENDING**

AC1 ✅(组合门) AC2 ✅(image source=ebe10b8) AC3 ✅(CORS 安全追加) AC4 ✅(runtime policy) AC5 ✅(health) AC6 ✅(既有 origins) AC7 ✅(server authz) AC8 ✅(preflight 非通配) AC9 ✅(负向全拒) AC10 ✅(widget API) AC11 ✅(零 DS/Sync/corpus mutation) AC12 ✅(rollback evidence) AC13 ✅(SHA 可追踪) AC14 ✅(本报告) AC15 ✅(main ff 恰 +1 commit)
