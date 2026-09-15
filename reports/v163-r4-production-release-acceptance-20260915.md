# V163_R4_TAG_RELEASE_DEPLOY — Production Release Acceptance Report

- 任务:V163_R4_TAG_RELEASE_DEPLOY(Release Executor B)
- 日期:2026-09-15

## TAG / TAG_TARGET / TAG_VERIFICATION

- **TAG = `v1.6.3-r4`**;**TAG_TARGET = `484128d34b496edea95217afc7b0248771c40fcf`**(冻结授权目标,非当时 main tip be01294)
- Pre-tag safety:commit 远端存在 ✓;484128d ⊂ origin/main ✓;无同名 tag(0 冲突)✓;planner 终跑 exit 0/9 条 ✓
- 约定:沿用既有 annotated tag(type=tag,同 v1.6.3/-r2/-r3);tag object `9e1f42e28a5ab8cbd09732f7b1800e287e9aa831`
- 验证:`git ls-remote --tags origin v1.6.3-r4` = 9e1f42e;gh api git/tags → `object.sha(commit) = 484128d…` = peeled 目标精确一致;仅推送 tag,未动 main

## RELEASE_WORKFLOW / IMAGE

- Build & Push GPU Image(tag 触发):run **34949867217** → **success**(test ✓ + build-and-push ✓)
- GitHub Release `v1.6.3-r4` 已按既有惯例创建(含冻结 SHA 与范围说明)
- Deploy Production(workflow_dispatch tag=v1.6.3-r4):run **34950997835** → **success**,全阶段绿:身份冻结 ✓ → release-publish guard ✓ → deployment record(in_progress)✓ → **Migrate database(release-bound;rollout 前)** ✓ → update.sh rollout(主机 flock)✓ → /health 运行时身份双断言 ✓ → deployment success ✓
- **IMAGE = `ghcr.io/harryhua-ai/ask-ai:v1.6.3-r4`**(backend/sync-executor/sync-cron 三容器全部运行该镜像)

## MIGRATIONS(发布绑定,rollout 前,冻结清单执行)

- 执行载体 = 冻结镜像内 compose 一次性服务;权威 = `deploy/prod/migrations.json`@484128d(9 条)
- 生产库事后只读实证:`data_sources.membership_*` 5 列在位(#71);`sync_requests.kind` 在位(#75)
- 未从 mutable main 执行任何迁移;无手动迁移

## DEPLOYED_VERSION / HEALTH

- **/health = `{"status":"ok","version":"1.6.3-r4","git_sha":"484128d34b496edea95217afc7b0248771c40fcf","app_mode":"production"}`**
- backend healthy,restarts=0;159 个 200 / **0 个 5xx**;admin API 全 200;widget.css/widget.js = 200(wiki-data 域,279,055B = r4 构建产物;www 边缘 404 = 既有正交观察,运行时注入实证正常);site-config 无 Origin = 403(fail-closed 既有契约);/api/ask 真实流式冒烟 4 次(917+ tokens/次,零错误)

## 后部署验收(逐 issue)

### #71 — RELEASE ACCEPTED(生产实证)
r4 后首轮同步(09:16–09:22)全量执行:14 源成员货币真值全部持久化 — 11 个 GitHub 源 `current`(含 enumerated/ledger_serving/stale_sample/residual 明细);filesystem/web_crawl/woocommerce 诚实 `unsupported`。陈旧退休实证:wiki-documents-local `stale_detected=24 / retired=24 / residual=0`(墓碑 reason=membership:*);neomind-local `7/7`;neoruntime-sdks `4/4`。sync ledger `membership_status` 仅在真值持久化后携带(fail-closed 语义在产线生效)。Admin 健康面与库内真值一致。

### #72 — RELEASE ACCEPTED(代码面 + 生产零 422)
r4 镜像部署后 0 条真实 422(日志 grep 命中均为端口号/tokenizer 速率误配)。部署后全轮同步零嵌入失败。代表值 78→16×4+14 的实机大轮分区未自然出现(无大重建轮),已由冻结树契约测试(Green)与部署身份覆盖;下一次大型重建时可在 sync 日志直接观测。

### #75 — RELEASE ACCEPTED(代码面 + 生产零 413)
零真实 413;`sync_requests.kind=rebuild → --reindex` 交接缝随镜像部署(库表 kind 列迁移已落)。未注入生产损坏数据以触发超限修复(按禁止清单);修复语义由冻结树契约测试覆盖。

### #76 — RELEASE ACCEPTED
部署/重启零失败;既有 Admin 原样保留(配置身份 users=1 role=admin,不变);无任何回退凭证注入;`admin123` 旧种子口令已失效(操作员已改密 —— 加固目标达成);启动无 ADMIN_PASSWORD 相关错误。

### #77 — RUNTIME ACCEPTANCE PARTIAL(工程已部署;运营矫正被凭证阻断)
- 工程(矫正路径 + 资格语义)已部署;只读探针 0 处 eval 证据外泄(见 #78)
- **运营矫正未执行**:neomind-local `exclude_dirs += ["eval"]` 需 Admin 数据源配置面;生产 Admin 口令已由操作员改密(#76 预期结果),执行者无凭证、按禁止清单不得重置
- 精确现状(只读):neomind-local eval/** 仍 serving = **298 documents / 298 paths**(git-tracked → 权威成员包含 → 非陈旧,必须先改排除配置)
- **剩余操作员动作**:Admin → 数据源 neomind-local → exclude_dirs 增加 `eval` → 下一轮同步自动按成员对账退休(与 #71 同机制);完成后验证 serving eval = 0 且邻接内容不变

### #78 — RELEASE ACCEPTED(双锚点生产实证)
只读真实问答探针:① shipping/support 问 → **`www.camthink.ai/shipping-policy/` 为第一引用源**(RCA 原失败锚点,现已入池并胜出);② contact 问 → **`company/contact-us/` 第一引用源**(第二锚点);④ code-oriented 问 → 第一源 = `crates/neomind-agent/.../stuck_detector.rs`(GitHub 代码路径,代码证据保序)。

### #79 — RELEASE ACCEPTED(live 实证)
真实 Sprint-less Project 上 per-issue sync(收敛 issue #50):run 34952732140 **success**,`result: ALREADY_CONVERGED`、`applied: []`、`iteration: v1.6.2` 保持、`iteration_clear: false` —— Sprint 缺席路径工作、Iteration 零意外变更、Priority/Status 语义正常。

### #80 — RELEASE ACCEPTED(Widget 契约生产实证;宿主 Analytics 观测 UNPROVEN)
- 部署产物:`widget.js` 279,055B 含 `"data-track":"contact"` 与 **4 处** `"data-type":"ask_ai"`(= 四入口面)
- 真机运行时(www.camthink.ai,GTM 运行时注入实证):Widget 挂载;主动式 mini(非 #80 范围面)关闭后 Launcher Pill 渲染,携带 `data-track="contact"` + `data-type="ask_ai"`
- 一次物理点击:宿主 document 监听恰计 **1 次点击**(track=contact/type=ask_ai,未被 preventDefault)→ Ask AI 正常打开(composer 出现,launcher 收起)—— 开/展 UX 不变
- **HOST_ANALYTICS_RUNTIME_CONFIRMATION = UNPROVEN**(宿主自有 tracker 记录不可从会话观测;不否定 Widget 契约 —— DOM/运行时行为已证);不主张历史 Analytics 连续性

## OPEN_BLOCKERS

1. **#77 运营矫正(唯一开放项)**:需操作员经 Admin 界面为 neomind-local 增加 `exclude_dirs: ["eval"]`(执行者无凭证;旧种子口令已按 #76 预期失效)。完成后下一轮同步自动退休 298 篇 eval 文档,并按冻结计划验证 serving eval = 0、邻接内容不变。

## PRODUCTION_MUTATIONS(授权范围内全记录)

tag + GitHub Release 创建;deploy workflow 触发(迁移 + rollout);1 轮常规计划同步(部署后自动发生);4 次只读问答探针(产生 4 条正常会话记录);1 次 Admin 登录尝试(失败,零变更);浏览器只读探测(1 次入口点击打开对话,未发送消息)。无 Wiki/GTM/GA4/凭证/手工 DB 变更。

## FINAL_VERDICT

**V163_R4_PRODUCTION_RELEASE = ACCEPTED**(带 1 项开放运营矫正:#77 eval 排除,阻断原因与精确动作如上)
