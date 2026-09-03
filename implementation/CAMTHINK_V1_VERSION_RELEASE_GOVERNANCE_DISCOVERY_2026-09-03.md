# Issue #10 — CamThink V1 Version & Release Governance Discovery 报告(冻结契约)

- **Executor**: SINGLE EXECUTOR(Discovery only)
- **日期**: 2026-09-03
- **STATUS**: **DISCOVERY PASS → READY_PENDING_PRODUCT_CONFIRM**(契约已冻结;首版本号 v1.0.0 与两处治理拍板项待 Product 确认,见 §11)
- **ISSUE**: harryhua-ai/ask-ai #10(从 TRIAGED 推进到 READY)
- **READ_MODE**: 全程只读;未改主仓任何文件、零生产触碰
- **REPORT_PATH**: `docs/implementation/CAMTHINK_V1_VERSION_RELEASE_GOVERNANCE_DISCOVERY_2026-09-03.md`
- **PRODUCTION_MUTATIONS**: **NONE**

---

## 1. CURRENT_STATE(实证)

| 面 | 现状 | 证据 |
|---|---|---|
| 生产 release 身份 | 三服务统一 `ghcr.io/harryhua-ai/ask-ai:sha-c83d214`;溯源 = 镜像 OCI label `org.opencontainers.image.revision = c83d214437…`(全 sha)+ 镜像内 `/app/.git-sha`(short-sha 文件,**运行时零代码读取**,仅供人工容器内 grep 核验) | 生产只读验收报告 2026-09-03 §2;`Dockerfile:71-72` |
| **RELEASE.json** | **不存在**——仓库内无生成/消费代码,生产主机上也**无**(只读验收明确记录「无 RELEASE.json」)。派发单中「已有 RELEASE.json」与实况不符,本 Discovery 予以纠正:现有 release 身份只有 image tag + OCI revision label + `.git-sha` 文件 | `grep -rn RELEASE.json`(主仓零命中);docs 只读验收 §2 |
| CI(唯一 workflow `build-image.yml`) | push main → 镜像 tag `sha-<short>` + `latest`;**push tag `v*.*.*` → 已接好 semver 镜像 tag(`X.Y.Z` + `X.Y`)**(从未使用);metadata-action 自动注入 OCI labels(revision=全 sha、version=semver、created 等);`GIT_SHA` build-arg bust 代码层;test job 挂则不出镜像 | `.github/workflows/build-image.yml:7-11,88-111` |
| 版本号 | **零 git tag、零 GitHub Release**(仓库历史从未发过版本) | `git tag -l` 空;`gh release list` 空 |
| 运行时版本 API | 无。`/health` 仅 `{"status":"ok"}`(`backend/main.py:541`);backend 无任何 version/manifest 端点,`/app/.git-sha` 无代码读者 | 代码 grep |
| 环境标识 | `APP_MODE`(dev 默认;prod compose 硬设 `prod`)已在 3 处被读(启动护栏/cookie strict/admin 校验),是**既成事实的环境权威**,但无 Settings 字段、无对外暴露 | `backend/config.py:68`、`backend/main.py:417`、`backend/api/admin/schemas.py:223`、`deploy/prod/docker-compose.yml` |
| Admin 系统信息 | **完全不存在**:pages 无 System 页、无相关 API(`admin/tech.py` 是 Trace 性能分析,非系统信息);Admin 为 backend 托管的 SPA(`/admin`),全部数据走 admin API | `admin/src/pages/` 清单、`admin/src/App.tsx` 路由 |
| 部署脚本 | `deploy/prod/update.sh`:pull → GPU 预检 → `up -d backend` → 健康轮询 120s → `up -d sync-cron`。**`up -d` 不含 sync-executor**——已知风险为真,且 09-03 部署报告已列为「流程改进候选」 | `deploy/prod/update.sh`;docs 部署报告 line 78 |
| compose 拓扑 | backend / sync / sync-executor / sync-cron 四个后端侧服务**共用同一镜像引用** `:${ASKAI_IMAGE_TAG:-latest}`(YAML anchor `x-backend-base`)——单 release 身份由构造保证;TAG 由 update.sh export 注入 | `deploy/prod/docker-compose.yml` |
| 回滚 | `./update.sh <旧tag>`(PA-0B 修复后 TAG 真实生效);镜像不可变 → sha 身份随之回退 | `update.sh` 头注 + compose 注释 |
| 历史发布记录惯例 | 每次生产部署/发布都有 docs 仓实现报告(SHA+验收证据),但 docs 仓**是独立本地仓、不随代码版本化、无 remote**——不能充当 Release Notes 的 durable home | docs 仓协议(方案 B) |

## 2. C1 — AUTHORITATIVE_VERSION_SOURCE(冻结)

**决议:版本权威 = 构建产物内烘焙的 `RELEASE.json`(CI 构建时生成、打进镜像 `/app/RELEASE.json`),运行时只读该文件。不引入第二可变权威。**

`RELEASE.json` 字段(CI 生成为准,冻结词表):

```json
{
  "version": "1.0.0",
  "git_sha": "c83d21443732499313cb1dc3870e6ec186f24f64",
  "source_ref": "v1.0.0",
  "built_at": "2026-09-05T08:30:00Z",
  "image": "ghcr.io/harryhua-ai/ask-ai:1.0.0",
  "ci_run_id": "1234567890",
  "ci_run_url": "https://github.com/harryhua-ai/ask-ai/actions/runs/1234567890"
}
```

生成链(执行阶段实施,机制全部既有):
1. `build-image.yml` 在 `docker build` 前一步把 `RELEASE.json` 写入 build context(`version` = 触发 tag 名去 `v` 前缀;main push 构建为非生产身份 `version="0.0.0-main"`,`source_ref` = 分支名;`built_at` = CI UTC 时间 RFC3339;`git_sha` = `github.sha`);
2. `Dockerfile` 末段 `COPY RELEASE.json /app/RELEASE.json`(放在 GIT_SHA bust 层之后,单文件薄层);
3. CI 加一步 in-image 断言:构建出的镜像内 `version`/`git_sha` 与触发 ref 精确一致(不一致 = build fail,坏产物不出门)。

**被否决的备选**(rationale 记档):
- **DB 权威**:可变第二权威 + 需迁移 + 回滚时版本行与镜像脱钩——正是本任务要求避免的;
- **纯 env(如 ASKAI_VERSION)**:手工可改、与 artifact 无绑定、漂移不可证;
- **仅 OCI labels**:backend 无 docker socket 可自读(容器提权 = 破坏特权边界),否决;OCI labels 保留作**外部交叉验证源**(§C9 冒烟);
- **前端常量**:Issue #10 明令禁止。

运行时回退语义:文件缺失/损坏 → backend **拒绝启动**(fail-closed,与 APP_MODE=prod 启动护栏同哲学);本地开发环境(`/app/RELEASE.json` 不存在)回退 `version="0.0.0-dev"` + 本地 `git rev-parse HEAD`,并显式标注 dev 非权威。

## 3. C2 — VERSIONING_RULE 与 FIRST_V1_VERSION_RECOMMENDATION(冻结)

- **规则:SemVer,git tag `vMAJOR.MINOR.PATCH`,只在 main 上打 tag。**
  - MAJOR:不兼容的产品/配置/迁移边界(需运维显式动作);
  - MINOR:向后兼容的功能发布(生产发布的默认档位);
  - PATCH:纯缺陷修复,无 schema/config 语义变化。
- **首版本推荐:`v1.0.0`** —— 产品本体即 CamThink V1,首个正式受治理发布直接命名 1.0.0(一次给足语义,避免 0.x「未稳定」暗示)。
- **不回填历史**:生产史(193f206 → 1d6f6b5 → 269cadb → ebe10b8 → c83d214)保持 sha 身份,docs 仓部署报告即历史记录;机制上线前的版本不补 tag、不补 Release Notes(除非 Product 另行决定)。
- **不可变性**:tag 与 commit 一一对应;**禁止重打/移动 tag**;坏版本 → 发下一版本(通常 PATCH+1),永不改写。`latest` 镜像 tag 只随 main push 移动(现有 CI `is_default_branch` 语义已保证 tag 构建不动 latest),**生产从首版起禁止部署 `latest`**。

## 4. C3 — RUNTIME_PROPAGATION(冻结)

```
git tag v1.0.0(main 上,含 release-notes/v1.0.0.md)
  → CI test 全绿 → build:生成 RELEASE.json → COPY 入镜像 → in-image 断言
  → GHCR: ask-ai:1.0.0 / 1.0 / sha-<short>(+ OCI revision/version labels)
  → update.sh v1.0.0 → 三服务同一镜像(backend/sync-cron/sync-executor)
  → backend 启动加载 /app/RELEASE.json(单例,进程内不可变)
  → GET /health 扩展(机器可验)+ GET /api/admin/system/release(完整身份)
  → Admin「系统信息」页(运行时 fetch,零前端硬编码)
```

- `/health` 扩展(向后兼容,既有编排/探活零破坏):
  `{"status":"ok","version":"1.0.0","git_sha":"<full 40 hex>","app_mode":"prod"}`
  —— update.sh 健康轮询、部署冒烟、回滚核验零成本拿到 release truth;
- Admin 端点(读同一进程内单例,无第二 IO 权威):`GET /api/admin/system/release`,admin 角色要求,返回 RELEASE.json 全字段 + `app_mode`。
- `app_mode` 冻结为环境标识权威(既成事实:compose 按部署硬设;本契约将其从「隐式 env」升格为「显式暴露的部署身份」,不新增配置项)。

## 5. C4 — ADMIN_UI_CONTRACT(冻结)

- 新增 Admin 页面,**路由 `/system`**,导航名「**系统信息**」(admin/editor/viewer 可见——只读)。
- 页面第一区块「**版本 / Release**」:ASK-AI Version、Git Commit SHA(全 sha,可短显)、Build 时间(`built_at`,UTC 渲染)、运行环境(`app_mode`)、镜像 tag、CI run 链接;数据全部来自 `GET /api/admin/system/release`,**前端构建产物不得内嵌任何版本字符串**(admin build 不注入版本,E2E 断言页面值 == API 值)。
- 展示纪律(Issue #10 原文约束的落地):不允许 Version 与 running artifact 漂移——页面无本地缓存,进页面即拉取。
- **本页是 #7 的宿主页**:#7 后续硬件区块追加到同页,不得另开第二页面(§C6)。

## 6. C5 — RELEASE_NOTES_CONTRACT(冻结)

- **Durable home = 主仓 `release-notes/vX.Y.Z.md`**(⚠️ 不能放 `docs/`:docs 是独立本地仓、不随代码版本化、无 remote,且 CI 构建上下文不含它;Release Notes 必须与 tag 同 commit 可溯)。
- **时序纪律:Release Notes 文件先于 tag 存在**——发布 commit 包含 `release-notes/v1.0.0.md`,tag 打在该 commit 上(tag 永远能找到自己的说明)。
- 必备小节(冻结):Version、Release date、主要新增/改进、Bug fixes、重要行为/配置变化、Migration/compatibility notes(含「是否可回滚到上一版本」明示,见 §C8)、Known limitations、Release identity(Git SHA + 镜像 tag)。
- **GitHub Release = 发布镜像,不是另一权威**:`gh release create vX.Y.Z --notes-file release-notes/vX.Y.Z.md --target <sha>`,内容即仓库文件;文件是 durable source,GitHub Release 是对外发布物。CI **不**自动建 Release(发布是显式运维动作,防误发)。
- 历史收口记录(docs 仓 `release-batch-20260831-closure.md` 等)保持原位,不迁移、不改写。

## 7. C6 — ISSUE_7_DEPENDENCY(冻结:零阻塞)

- **结论:#10 可完全独立实施,不等 #7。**
- 边界:#10 的版本身份 = 构建产物元数据(纯文件读,无硬件采集);#7 = 宿主/硬件运行时可观测(hostname/CPU/内存/GPU…),其 Discovery 要点(平台可移植性、采集节奏、特权边界、不可用硬件降级)与 #10 零交集。
- 合流点唯一且已冻结:两者共用 `/system` 同一页面,#10 先建页并占住「版本/Release」区块;#7 实施时**追加**硬件区块,且版本字段永远由 release API 供给,硬件层无权写版本。
- #7 的 read-only 安全边界(无重启/kill/shell 执行)不受 #10 影响。

## 8. C7 — DEPLOYMENT_CONTRACT(冻结,含已知风险修复)

- **生产部署自 v1.0.0 起只接受显式版本 tag**:`./update.sh v1.0.0`;空参(回落 `latest`)在 update.sh v2 中改为**拒绝执行**(防误部署;回滚/应急用显式 `sha-<short>`,同样显式)。
- **修复既有风险(实证在案)**:update.sh v2 的滚动更新改为
  `docker compose up -d backend sync-cron sync-executor`(三常驻服务一体换镜像),消除「backend 新版 + sync-executor 旧镜像」混跑窗口——09-03 部署报告 line 78 与 269cadb 部署记忆均已记录该缺口。
- **部署后验证(update.sh 内建,失败即 exit 非 0)**:
  1. `/health` 的 `version` == 预期版本(由 TAG 推导,`v1.0.0 → 1.0.0`);
  2. `/health` 的 `git_sha` == `docker inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' ghcr.io/harryhua-ai/ask-ai:$TAG`(镜像 OCI label 交叉验证,host 上零额外凭据);
  3. `docker compose ps` 断言 backend/sync-cron/sync-executor 三服务镜像 tag 一致(混跑即失败)。
- 一次性 `sync` 服务(`run --rm`)天然用 `ASKAI_IMAGE_TAG` 同 tag,无需额外处理(compose 插值既有行为)。
- CI 面零新权限:build/push 既有;Release 创建为运维显式步骤(§C5)。

## 9. C8 — ROLLBACK_CONTRACT(冻结)

- 回滚 = `./update.sh <旧版本 tag 或 sha-<short>>`,与升级同一代码路径 → 三服务统一回到旧**不可变镜像**;旧镜像自带其 `RELEASE.json` → `/health` 立即报告旧 `version`+`git_sha`,**版本与 SHA 经构造保持对齐,无需任何手工同步**。
- 回滚完成后 update.sh 执行与部署相同的验证三件套(§C7),冒烟报告记录「rollback → Version+SHA」。
- **边界(冻结进 Release Notes 必写项)**:镜像回滚不回滚 DB schema。规则:MINOR/PATCH 发布的迁移必须对上一版本**向后兼容(additive-only)**,Release Notes 的 Migration/compatibility 节必须明示「可否直接回滚到上一版本」;MAJOR 发布必须写显式迁移/回退方案。

## 10. C9 — ACCEPTANCE_CRITERIA 与生产冒烟契约(冻结)

执行阶段验收(全部可在隔离环境先证,生产验证留独立授权门):

1. tag `v1.0.0` 构建的镜像内 `/app/RELEASE.json`:`version=1.0.0`、`git_sha`=该 tag commit 全 sha(CI 内断言,负例:篡改即红);
2. `/health` 返回四字段(旧字段 `status` 保留;既有探活/编排零破坏——回归测试锁定);
3. `GET /api/admin/system/release`:admin 可读全字段;未认证 401/越权 403;
4. Admin `/system` 页渲染值 == API 值(E2E);`admin/dist` 构建产物中无版本常量(grep 断言);
5. update.sh v2:三服务同 tag 部署 + 验证三件套(§C7)全过;对 sync-executor 旧镜像场景做一次**隔离演练**(local compose 起旧 executor → 跑 v2 → 断言被换新),作为「混跑修复」的实证;
6. 回滚演练:deploy → 回滚上一 tag → `/health` 版本+SHA 随镜像回退且验证通过(隔离环境演练;生产演练随首次 v1.0.0 部署窗口顺带执行);
7. `release-notes/v1.0.0.md` 在 tag commit 内存在且小节齐全;GitHub Release v1.0.0 存在且正文与文件一致;
8. 生产首次版本化部署的 Smoke 报告必须记录:**Version + Commit SHA + 镜像 tag + app_mode**(四元组),取代既往「只记 SHA」。

## 11. 待 Product 拍板项(不阻塞 READY,阻塞 v1.0.0 发布动作)

1. 首版本号 **v1.0.0**(本契约推荐值);
2. GitHub Release 可见性随仓库(当前私有)——是否需要在仓库公开前保持 Release 草稿态,由 Product 定;
3. `latest` 禁令的生效时点:建议与 v1.0.0 部署同窗生效(update.sh v2 合入即生效,窗口前 main push 仍可显式 sha 部署应急)。

## 12. CHANGE_BOUNDARY(执行阶段范围预冻结)

**允许**:backend 新增 `release.py`(文件读单例)+ `/health` 扩展 + `GET /api/admin/system/release`;Dockerfile +1 COPY;`build-image.yml` +生成/断言两步;`deploy/prod/update.sh` v2;admin 新页 `/system` + 导航 + hook + E2E;`release-notes/` 目录 + v1.0.0 notes(发布 commit);部署 runbook 文档;对应单元/集成测试。
**禁止**:DB 迁移/新表(零 schema 变更);新增 Python 依赖;CORS/鉴权模型变更;docs 仓承载 release notes;CI 自动建 Release;任何生产动作(部署/重启/拉镜像/建 Release 均 Playner 授权后另行执行)。

---

## Deliverable 摘要

```
STATUS:                          DISCOVERY PASS → READY_PENDING_PRODUCT_CONFIRM
ISSUE:                           #10(Version & Release Governance)
CURRENT_STATE:                   生产=sha-c83d214;身份=镜像tag+OCI revision label+/.git-sha
                                 (无运行时读者);⚠️RELEASE.json 实为不存在(派发单前提纠正);
                                 零 git tag/零 GitHub Release;/health 仅 status;无系统信息页;
                                 update.sh 缺 sync-executor(风险为真)
AUTHORITATIVE_VERSION_SOURCE:    CI 构建时生成、烘焙进镜像的 /app/RELEASE.json(单一构建产物
                                 权威;DB/env/OCI-label-only/前端常量均否决,rationale §2)
VERSIONING_RULE:                 SemVer,git tag vX.Y.Z 只打 main;tag↔commit 1:1 不可移动;
                                 latest 不再上生产;OCI labels 保留为外部交叉验证源
FIRST_V1_VERSION_RECOMMENDATION: v1.0.0(不回填历史)
RUNTIME_PROPAGATION:             tag→CI(生成+断言)→镜像→backend 启动单例读入→/health 扩展
                                 (status,version,git_sha,app_mode)+ /api/admin/system/release
                                 →Admin /system 页(fetch,零硬编码)
ADMIN_UI_CONTRACT:               新页 /system「系统信息」;版本/Release 区块(Version/SHA/build
                                 时间/app_mode/镜像/CI 链接);值==API;#7 未来硬件区块同页追加
RELEASE_NOTES_CONTRACT:          主仓 release-notes/vX.Y.Z.md(tag 同 commit,durable source;
                                 ⚠️不能放 docs/=独立本地仓不随代码版本化)+ GitHub Release 镜像
                                 (gh release create --notes-file,显式运维步骤);必备小节冻结
ISSUE_7_DEPENDENCY:              零依赖零阻塞;#10 独立交付版本身份;唯一合流点=/system 同页,
                                 版本字段永远归 release API 管
DEPLOYMENT_CONTRACT:             生产只部署显式版本 tag(update.sh v2 拒绝空参 latest);
                                 三服务 backend/sync-cron/sync-executor 一体 up -d(修复混跑缺口);
                                 部署后验证三件套:/health version==TAG、git_sha==OCI revision
                                 label、compose ps 三服务镜像一致;一次性 sync 天然同 tag
ROLLBACK_CONTRACT:               update.sh <旧tag> 同一路径;不可变镜像自带 RELEASE.json →
                                 版本+SHA 经构造对齐;镜像回滚不回滚 schema(additive-only 纪律
                                 + Release Notes 必写兼容性)
ACCEPTANCE_CRITERIA:             §10 八条(CI 内 in-image 断言/health 四字段回归/admin 端点鉴权/
                                 UI==API/dist 无版本常量/executor 换镜像演练/回滚演练/notes 齐全/
                                 生产冒烟四元组 Version+SHA+tag+app_mode)
CHANGE_BOUNDARY:                 §12(允许/禁止清单;零 DB 迁移、零新依赖)
BLOCKERS:                        无阻塞;3 个 Product 拍板项(§11:v1.0.0 确认/GH Release 可见
                                 性/latest 禁令生效时点)
READY_STATUS:                    READY(契约冻结;Product 确认 v1.0.0 后即可进入执行派发)
REPORT_PATH:                     docs/implementation/CAMTHINK_V1_VERSION_RELEASE_GOVERNANCE_DISCOVERY_2026-09-03.md
REPORT_COMMIT:                   见 docs 仓本文件 commit
PRODUCTION_MUTATIONS:            NONE
```
