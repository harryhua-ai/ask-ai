# CamThink V1 — Issue #10 Version & Release Governance 实现报告

- **日期**: 2026-09-03
- **基线**: `c83d214`(origin/main,生产血统;生产=sha-c83d214)
- **分支**: `worktree-exec/issue10-release-governance-20260903`
- **Worktree**: `.worktrees/issue10-release-governance`(.env/6.4G models 物理复制,零 symlink,offline 预验通过)
- **状态**: **CANDIDATE_READY(待 Planner FINAL REVIEW)**
- **PRODUCTION_MUTATIONS**: **NONE**(零部署/零重启/零打 tag/零 GitHub Release/零生产触碰)

---

## 1. 权威版本模型(实现形态)

```
git tag / exact commit
  → CI「Generate RELEASE.json」步骤(scripts/generate_release_manifest.sh)
  → docker build COPY /app/RELEASE.json(Dockerfile)
  → CI「Assert in-image RELEASE.json」步骤(docker create+cp → version/git_sha 断言)
  → backend lifespan 启动一次性加载(backend/release.py,进程级不可变)
  → GET /health(扩展字段)+ GET /api/admin/system/release
  → Admin /system 系统信息页(hook useReleaseInfo)
```

**排除面(逐条落实)**:无 DB 版本表、无可变 env 版本权威(APP_MODE 仅作
prod/dev 模式判定,不是版本)、无前端版本常量(admin dist 零版本字面量,
测试锁定值来自 API)、OCI revision labels 保留作独立交叉核对证据。

## 2. RELEASE.json 契约(§1)

- 字段:`version`(SemVer,tag v 前缀归一为无前缀存储)、`git_sha`
  (精确 commit,7..40 hex 归一小写)、`built_at`(构建钟 `date -u`)、
  `image`(完整镜像引用)、`ci_run_id`(可用时)。
- **fail-closed 语义**(单测锁定):
  - `APP_MODE=prod` 且文件缺失 → `ReleaseIdentityError`,lifespan 启动即失败
    (生产镜像不得假冒正式版本);
  - **任何模式下,存在但非法**(坏 JSON/缺字段/非法 SemVer/非法 sha)→ raise
    —— 坏文件 ≠ 缺失,绝不静默降级;
  - 非 prod 且缺失 → 显式开发兜底:`version="0.0.0-dev"`、`source="fallback"`、
    git_sha 本地 `git rev-parse` 尽力而为;
  - 进程级缓存一次性加载,加载后文件删除/篡改不影响本进程身份(不可变)。

## 3. 运行时契约(§2)

- **`GET /health`**:`status:"ok"` 保持(既有消费者兼容);新增
  `version` / `git_sha` / `app_mode`(production|development),与
  release authority 同源。既有两处精确相等断言测试按扩展契约更新
  (tests/test_main.py、tests/api/test_routes.py)。
- **`GET /api/admin/system/release`**(backend/api/admin/system.py,
  挂入 admin_router):viewer+ 既有 Admin auth 约定;只读;响应键精确锁定
  `{version, git_sha, built_at, app_mode, image, ci_run_id, source}`;
  无环境 dump、无密钥。

## 4. Admin UI(§3)

- `/system` 系统信息页(pages/SystemInfo.tsx)+ Sidebar「系统信息」入口
  (全角色可见)+ `useReleaseInfo` hook(staleTime=Infinity:身份进程内不可变)。
- 「版本 / 发布」Card:ASK-AI 版本(大字 mono)、完整 Git SHA、构建时间、
  运行环境、镜像/Tag、CI 链接(仅 `ci_run_id` 存在时渲染 Actions run 链接,
  否则如实「不可用」);`source=manifest→正式发布 / fallback→开发态` 徽章。
- loading(`正在加载发布信息…`,aria-live)与 error(LoadError+重试)truthful。
- **零版本常量**:全部值来自 API(测试以 fixture 值断言渲染)。
- **#7 预留**:页面文档注释明确「硬件/系统可观测性在本节后追加独立
  section,不改 release identity 权威」;本任务未实现任何 #7 内容,
  无重启/进程控制。

## 5. 版本化与发布说明(§4)

- **`release-notes/` 目录进仓库**(不进本地 docs 仓):`README.md`(惯例:
  仓库内 vX.Y.Z.md = 事实源;GitHub Release = 公开镜像非运行时权威;
  CI 不自动发布)+ `TEMPLATE.md` 语义的 `v1.0.0.md` 占位(九节必填清单:
  Version/Release date/Major additions/Bug fixes/Behavior-config changes/
  Migration-compatibility/Known limitations/Git-Tag-Artifact identity/
  Rollback compatibility;明确标注「Final RC Assembly 未完成,不得直接
  作为最终发布说明」)。

## 6. CI / 构建(§5)

build-image.yml 新增:
- **Generate RELEASE.json**(build 前):tag 构建(`refs/tags/v*`)→
  version=GITHUB_REF_NAME(SemVer,写入时归一)、image tag=vX.Y.Z 字面;
  main/manual → version=`0.0.0+main.<sha8>`(合法 SemVer build metadata,
  非正式版本)、image tag=sha-<short>。
- **Assert in-image RELEASE.json**(push 后):`docker create`+`docker cp`
  取出镜像内清单,断言 version(去 v)== 构建版本、git_sha == GITHUB.sha。
- metadata tags 增 `type=ref,event=tag`(vX.Y.Z 字面 tag 与 update.sh 契约
  对齐;sha/latest/1.2.3/1.2 兼容保留);OCI labels 保留。
- Dockerfile:`COPY RELEASE.json ./RELEASE.json`(代码层之后,避免 cache bust);
  `.gitignore` 屏蔽根目录 RELEASE.json(构建产物禁止提交)。
- **无自动 GitHub Release 发布步骤**(契约测试锁定:无 gh-release action、
  无 `gh release create`、release-notes/ 不进 CI)。

## 7. 部署契约(§6)

`deploy/prod/update.sh` 重写(#10 契约):
1. tag 必填(缺参 exit 2);`latest` 拒绝(exit 2);
2. `docker compose pull` 后 **先断言镜像内 RELEASE.json**:`docker create`+
   `cp`,version(去 v)== 请求 tag、git_sha 非空;无清单旧镜像显式拒绝
   (不会静默部署,消息注明仅适用 #10 后的版本化镜像);
3. GPU 预检保留;
4. `up -d backend` → 健康轮询(180s,BGE 加载期不误报)→ **核验 /health
   上报 version == 期望版本**(运行时身份 = 镜像身份,不一致拒绝完成);
5. `up -d sync-cron sync-executor`(**修复既有缺口:sync-executor 此前
   从不被 update.sh 更新**);
6. 三服务一致性核验:`docker inspect .Config.Image` 逐服务断言以 `:$TAG`
   结尾,任一不一致 exit 1。

`deploy/prod/docker-compose.yml`:镜像引用改为
`${ASKAI_IMAGE_TAG:?...}`(compose 插值必填语法)——未设置 tag 时任何
`docker compose` 操作直接报错,**生产面彻底消灭隐式 :latest**;
backend/sync/sync-executor/sync-cron 四服务共用同一 anchor 镜像引用。

dev/local compose 无本地 build、不受 Dockerfile COPY 影响(已核验)。

## 8. 回滚契约(§7)

回滚 = 同一脚本 + 上一个不可变版本 tag:三服务全部回到旧 tag(第 [6/6] 步
逐服务核验)→ 运行时 RELEASE.json/`/health`/Admin 页回显旧版本(第 [5/6] 步
version 核验对旧 tag 同样生效)→ 前端可见版本与实际工件不可能错位(值同源
后端)。schema 回滚自动化不做;release-notes 模板含 Migration/compatibility
必填节,强制说明迁移向后兼容。

## 9. 测试证据(§8)

| 门 | 结果 |
|---|---|
| A. RELEASE.json 解析/校验(tests/test_release_identity.py) | **15 passed**(合法 roundtrip/v 前缀归一/build metadata/缺字段 dev 也 raise/非法 SemVer/非法 sha/空字段/坏 JSON/prod 缺失 fail-closed/dev 兜底/进程单例不可变) |
| B. /health(tests/test_main.py + tests/api/test_routes.py) | status 兼容 + 三字段与 authority 同源 |
| C. Admin 端点(tests/api/admin/test_system_release.py) | **4 passed**(401 未认证/值=运行时权威/响应键锁定/health 同源) |
| D. Admin UI(admin/tests/SystemInfo.test.tsx) | **6 passed**(API 值直呈/开发态如实/loading/error 重试/CI 链接条件渲染/无假链接);Sidebar/路由注册 + tsc |
| E. 构建契约(tests/scripts/test_release_tooling.py) | 生成脚本合法输入产出 tag/SHA 清单、非法输入非零退出;workflow 断言步骤存在、semver 触发、无自动 Release、OCI labels 保留 |
| F. 部署脚本 | bash -n;缺参/latest 拒绝(实际执行断言);三服务更新;清单先断言后切换;/health 版本核验;回滚文档化;compose tag 必填 |
| G. 回归 | 后端全量 **1160 passed/6 skipped/0 failed**(基线 1120+新增 40,严格吻合);admin vitest **196/196**;`tsc -b` ✓;`npm run build` ✓;`git diff --check` ✓;offline 权重加载预验 ✓ |

## 10. Known Limitations

1. **update.sh 运行时行为未在生产演练**(任务禁止部署):docker/compose 交互
   路径以 bash 语法 + 静态契约锁 + 既有 PA-0B 演练经验为据;首次 v1.0.0
   部署门建议先以测试 tag 干跑。
2. **镜像内断言消耗 runner 拉取**:push 后 `docker create` 需从 GHCR 拉镜像
   (~9.6GB);换取「in-image 与构建一致」的强断言,在 45min 构建内占比可接受。
3. **旧镜像不兼容**:c83d214 及之前的镜像无 RELEASE.json,新 update.sh 会
   拒绝——这是有意的 fail-closed(过渡路径 = 继续旧脚本一次性,或直接从
   v1.0.0 起版本化)。
4. **dev 兜底身份** `0.0.0-dev` 仅用于本地开发/单测;prod compose 固定
   `APP_MODE: prod` → 兜底在生产不可达。
5. **CI 的 test job 未跑 admin vitest**(既有状态,非本任务引入);admin 门
   在本地/后续门补齐。
6. `built_at` 由生成脚本所在机器钟生成(CI = GitHub runner 钟,权威构建钟);
   单机本地构建即本机钟,语义不变。

## 11. 边界声明

未部署生产、未重启服务、未创建 v1.0.0 tag、未创建 GitHub Release、
未做 DB migration、未实现 #7 硬件监控、未引入 docker-socket 依赖、
未加前端版本常量、未做无关重构。生产交互:**NONE**。

## 12. 结构化结果

```
STATUS: CANDIDATE_READY(待 Planner FINAL REVIEW)
BASELINE: c83d214(origin/main,生产血统)
FINAL_COMMIT: c3928bf(@origin/worktree-exec/issue10-release-governance-20260903)
BRANCH: worktree-exec/issue10-release-governance-20260903
WORKTREE: .worktrees/issue10-release-governance(.env/models 物理复制,offline 预验)
RELEASE_MANIFEST_IMPLEMENTATION: scripts/generate_release_manifest.sh(CI/本地共用,
  SemVer+SHA 校验,构建钟 built_at)+ Dockerfile COPY /app/RELEASE.json +
  backend/release.py 进程级一次性加载(immutable;prod 缺失/非法 fail-closed,
  任何模式存在即非法必 raise,非 prod 缺失 0.0.0-dev 兜底)
RUNTIME_API: /health 扩展 version/git_sha/app_mode(status 兼容)+
  GET /api/admin/system/release(viewer+,只读,键锁定:version/git_sha/
  built_at/app_mode/image/ci_run_id/source)
ADMIN_UI: /system 系统信息页(版本/完整 SHA/构建时间/环境/镜像/CI 链接,
  loading/error truthful,零前端版本常量,#7 追加位预留)+ Sidebar 入口
VERSIONING_IMPLEMENTATION: tag 构建 version=git tag(SemVer 归一),
  main/manual=0.0.0+main.<sha8>;vX.Y.Z 字面 docker tag(与 update.sh 对齐)
RELEASE_NOTES_IMPLEMENTATION: release-notes/ 入仓(README 惯例 + v1.0.0.md
  模板占位;九节必填;GitHub Release=公开镜像非运行时权威,FINAL RC 前不发布)
CI_BUILD_IMPLEMENTATION: Generate RELEASE.json 步骤 + Assert in-image 步骤
  (docker create+cp,version/git_sha 双断言)+ OCI labels 保留 + 无自动发布
DEPLOYMENT_SCRIPT_IMPLEMENTATION: update.sh <tag>:tag 必填/latest 拒绝/
  镜像内清单先断言后切换/三服务(backend+sync-cron+sync-executor)同 tag+
  逐服务镜像核验/health 版本核验;prod compose tag 必填(:?)禁回退 latest
ROLLBACK_IMPLEMENTATION: 同命令+旧不可变 tag;三服务回退+运行时身份核验
  同一契约;schema 回滚不做,由 release-notes 迁移兼容节强制说明
TESTS: 新增 40(15 identity+4 endpoint+21 工具链契约)+ 2 处既有 health
  按扩展契约更新 + admin 6 例 SystemInfo
BACKEND_TESTS: 1160 passed/6 skipped/0 failed(全量,隔离库+离线;基线 1120+40)
ADMIN_TESTS: 196/196(37 files);tsc -b ✓
BUILD: admin vite build ✓;git diff --check ✓;update.sh bash -n ✓
REGRESSIONS: 零(基线严格吻合;health 契约扩展经测试更新,字段向后兼容)
KNOWN_LIMITATIONS: §10 六项(update.sh 未生产演练/断言步骤拉取开销/
  旧镜像不兼容为有意 fail-closed/dev 兜底边界/CI 未含 admin vitest 为既有/
  built_at=构建钟语义)
REPORT_PATH: docs/implementation/CAMTHINK_V1_VERSION_RELEASE_GOVERNANCE_IMPLEMENTATION_2026-09-03.md
REPORT_COMMIT: 见 docs 仓 log
PRODUCTION_MUTATIONS: NONE
```
