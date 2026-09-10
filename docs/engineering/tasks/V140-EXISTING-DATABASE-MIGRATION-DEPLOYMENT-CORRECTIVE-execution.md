# V1.4.0 EXISTING-DATABASE MIGRATION / DEPLOYMENT CORRECTIVE — 执行报告

- 日期:2026-09-10
- 模式:ENGINEERING CORRECTIVE(生产变异:无 —— 全程未触碰生产数据库/服务)
- 基线:main = c92e88a2fb93148bfb0b8decb815ebb87057639d
- 分支:`impl/v140-existing-db-migration-corrective`(不合 main、不部署)
- 实现提交:`4d34fa9d56cbc2b7058d9f67f0af2f81849bc407`;候选 SHA 见 §15

---

## 1. Confirmed incident root cause

- **主因**:生产部署生命周期没有「既有库 schema 迁移执行」环节。v1.4.0 应用代码
  依赖 `site_experiences.launcher_presentation`,既有生产库(v1.3.0 schema)无该列 →
  backend 启动即 `asyncpg UndefinedColumnError` 崩溃循环 → update.sh [5/6] 健康轮询
  180s 超时 → run 34454739497 failure、生产中断(后经授权 break-glass 回滚 v1.3.0 恢复)。
- **次因**:发布/部署验收只测了 fresh-DB(create_all 直接建最终 schema),没有
  「v1.3 schema → 迁移 → v1.4 应用」的存量库升级路径测试 —— 测试盲区与事故类别完全一致。
- 既存事实:仓库已有 **25 个 `scripts/migrate_*.py` 独立幂等脚本**的迁移惯例,
  但全部依赖人工手动执行,没有任何编排层自动执行/校验机制。

## 2. Existing migration architecture discovered(§3 A–E)

| 项 | 结论 |
|---|---|
| A. schema 表示 | SQLAlchemy 模型(`backend/db/models.py`)+ 启动 `create_all`(只建表不改表) |
| B. 脚本形态 | 独立、幂等、**无序号、无清单、无 runner**;25 个 `scripts/migrate_*.py` 靠人工执行 |
| C. 其他工具 | 无 alembic 版本体系(pyproject 声明 `alembic>=1.14` 但无 alembic.ini/versions,未启用) |
| D. 冻结镜像内容 | Dockerfile `COPY scripts/ ./scripts/` → **v1.4.0 镜像内含迁移脚本**;迁移脚本 blob 在 main 与 `v1.4.0`(41278f0)完全一致(`b6840c5a`) |
| E. 主机运行时工件 | 主机 `~/ask-ai` 非 git 仓库,但持有现行 `deploy/prod/docker-compose.yml`(含 `ASKAI_IMAGE_TAG` 强制)与既有一次性服务 `sync`(`restart:no`/healthcheck disabled,README 同款 `run --rm sync python scripts/…` 执行模式) |
| F. 执行位置 | **冻结发布镜像内**(依赖齐备 + 身份可断言);载体 = 既有 compose `sync` 服务 —— 零新增主机文件、零 update.sh/compose 变更 |
| G. 凭据 | 容器经 compose `env_file: ../../.env` + `POSTGRES_DSN` 注入;脚本经 `resolve_migration_dsn`(Issue #20 守卫:prod+TEST_DATABASE_URL 硬失败)取 DSN;日志不落凭据(有测试锁定) |
| H. 成功/失败/重复 | 成功=退出 0+日志;失败=异常→非零退出;幂等=`ADD COLUMN IF NOT EXISTS`(测试双跑实证) |
| I. 回滚兼容 | 加性 nullable 列,v1.3.0 形状访问不受影响(测试实证,§9) |
| J. 加性/向后兼容 | v1.3.0→v1.4.0 模型 delta **恰一列** `launcher_presentation String(10) nullable=True`,无破坏性 ALTER/DROP(测试断言列集 diff 恰为一列且既有列属性逐列不变) |

## 3. Chosen migration ownership model and why(§7)

**发布自有迁移清单 + 窄历史桥**,解析器 `scripts/release_migration_plan.py`:

1. **权威机制(面向未来)**:冻结发布树内 `deploy/prod/migrations.json`
   `{"migrations": ["scripts/…"]}`(有序;空列表=无迁移)。清单与代码**同树同 tag**
   —— 迁移需求与冻结发布身份天然绑定,不存在 mutable-main 歧义。契约:清单机制
   存在后的每个发布树必须携带该文件(无迁移也要空列表);本候选已激活该文件。
2. **历史桥(封闭集合,只减不增)**:仅覆盖清单机制诞生**前**已冻结的发布
   (现仅 `v1.4.0`)。桥条目必须在冻结树内存在;workflow 在执行任何镜像代码前
   先断言镜像内 `RELEASE.json == 冻结身份` —— **迁移代码来源 = 冻结工件而非
   mutable main**,满足 §4.3 exact release binding。
3. 解析优先级:冻结树清单 → (无清单时)桥 → 都无则 `NONE`(MIGRATION NOT
   REQUIRED,stderr 显式提示清单契约,防未来发布忘带清单静默漏迁)。

拒绝的替代:按版本硬编码(任务明令禁止);启用 alembic(仓库无版本体系,引入
新框架违反「无证据不发明」);改 update.sh 内嵌迁移(主机副本手工维护,引入
主机同步前置与回归面,见 §6)。

## 4. Exact changed files

| 文件 | 变更 |
|---|---|
| `scripts/release_migration_plan.py` | **新增** 迁移计划解析器(冻结树清单/桥/fail-closed 校验,29 项契约测试) |
| `deploy/prod/migrations.json` | **新增** 发布自有迁移清单(首条=launcher_presentation 迁移) |
| `.github/workflows/deploy-production.yml` | 增设 **migrate 步**(record_create 与 deploy 之间);头部契约注释扩充;其余 7 步逐字未动 |
| `tests/scripts/test_v140_existing_db_upgrade_path.py` | **新增** 存量库升级路径集成测试(§8 全项) |
| `tests/scripts/test_release_migration_plan.py` | **新增** 解析器契约测试 |
| `tests/scripts/test_deploy_orchestration.py` | 扩充迁移阶段 13 项契约;原 `test_only_existing_primitive_no_docker_reimplementation` 按步作用域化(见 §13);`test_guard_before_any_mutation` 纳入 migrate 序 |

**未动**:update.sh(可执行体逐字未改)、docker-compose.yml、全部 backend/ 应用
代码、迁移脚本本体、tag/Release、recorder、verify_runtime_identity、release-integrity.yml。

## 5. Deployment ordering before/after

```
BEFORE: identity → guard → record_create(in_progress) → deploy(update.sh) → verify(/health) → record_success | record_failure
AFTER:  identity → guard → record_create(in_progress) → **migrate(发布绑定)** → deploy(update.sh) → verify(/health) → record_success | record_failure
```

生命周期属性(§2/§4.1):KNOWN EXISTING SCHEMA →(计划解析 fail-closed)→
REQUIRED MIGRATION(镜像内、镜像身份断言后执行)→ MIGRATION VERIFIED
(退出 0 + MIGRATION SUCCESS 日志)→ NEW APPLICATION(update.sh)→ RUNTIME
IDENTITY/HEALTH(双断言)→ SUCCESS EVIDENCE(recorder)。迁移失败存在于任何
环节 → rollout 不发生、记录收尾 failure、无 success 代码路径。

## 6. Immutable release binding mechanism

- 计划输入 = identity 步冻结的 `tag + 40位SHA`;解析器只读 `git show <SHA>:deploy/prod/migrations.json`(冻结树,非工作区);
- 执行环境 = `ghcr.io/…:<冻结tag>` 镜像;**先** `docker create`+`docker cp` 取镜像内
  RELEASE.json 断言 `version==tag 去v` 且 `git_sha==冻结SHA`(精确相等,严于
  update.sh [3/6] 的 git_sha 非空校验),**后** `compose run --rm sync python <脚本>`;
  因此桥时代(v1.4.0)执行的迁移代码被证明来自冻结工件;
- 未来发布走清单:清单本身就在冻结树,与发布同一身份。

## 7. Failure semantics(§4.2/§9)

- 计划解析失败(非法清单/条目越界/树内缺失/git 证据源不可用)→ migrate 步退出非零 → workflow 失败;
- 镜像身份断言失败 → 拒绝执行迁移 → workflow 失败;
- 迁移脚本非零退出 → migrate 步失败 → deploy 步不执行(默认 success 语义,无 bypass `if`)→ finalizer 按**未改动**的条件写 failure;
- `record_success` 仍 `if: success()` 且在 verify 之后 —— 迁移失败时 success 无代码路径(契约测试锁定);
- 无自动重试、无自动回滚(与既有语义一致)。

## 8. Retry / idempotency semantics(§4.4)

- 迁移语句 `ALTER TABLE … ADD COLUMN IF NOT EXISTS`(单条、nullable、零回填);
- 测试实证:同一存量库连续两次执行,第二次退出 0、列集/行数零变化;
- 部署重试(如上次中断于迁移后)重跑迁移安全,再进入 rollout。

## 9. Rollback compatibility(§4.5/§10)

- 迁移加性(列集 diff 恰为一列,既有列类型/长度/可空性逐列不变,测试断言);
- v1.3.0 形状访问(仅 v1.3 列集的 INSERT/SELECT,不引用新列)在迁移后照常成立,
  新列对旧应用不可见(NULL)—— 无 down-migration、无破坏性回填;
- v1.3.0 回滚(break-glass `update.sh v1.3.0`)在已迁移库上保持 schema 兼容
  (列级 + SQL 形状级证明;true 应用二进制回滚已在 2026-09-10 生产回滚事件实证)。

## 10. Upgrade-path test design(§8 —— 不用 create_all 代表既有库)

`tests/scripts/test_v140_existing_db_upgrade_path.py`(真实 postgres,CI test job
自带 postgres:16 服务,`TEST_DATABASE_URL` 惯例与既有迁移测试一致):

1. 以 **v1.3.0 模型等价 DDL**(25 列,逐列对应 `git show v1.3.0:backend/db/models.py`)显式建存量表(**非 create_all**);
2. 灌 3 行真实形态数据(含崩溃时生产正在查询的 `camthink-website`);
3. 断言初始无 `launcher_presentation` 且列集 == v1.3.0 全集;
4. **以部署同路径执行迁移**(脚本作为 `__main__` 子进程 = 镜像内 `python scripts/…` 同一入口;DSN 经 `resolve_migration_dsn` 路由测试库);
5. 断言成功(退出 0 + 完成日志;logging 默认流 stderr,编排日志两者皆收);
6. 断言列集 diff **恰为** launcher_presentation,既有列属性逐列不变;
7. 断言列语义 `VARCHAR(10) NULLABLE` == v1.4.0 模型;
8. 断言 3 行既有数据保全(行数 + 关键列值精确比较);
9. v1.4.0 模型 ORM 读写(NULL=未配置→icon 契约;可写 pill);
10. 再次执行 → 幂等(退出 0、列集/行数不变);
11. v1.3 形状 INSERT/SELECT 在迁移后成立(回滚兼容);
12. 附加:失败→非零退出;日志不泄露 DSN 口令;迁移脚本 blob == `v1.4.0` tag
    (冻结工件一致性;CI 浅检出无 tag 时诚实 skip)。

## 11. Test commands/results(§12)

```
# 离线契约
uv run pytest tests/scripts/test_release_migration_plan.py tests/scripts/test_deploy_orchestration.py -q
  → 71 passed(修复后)

# 升级路径(本机 postgres:16 docker,端口 5437,ask_ai_test 库)
TEST_DATABASE_URL='postgresql+asyncpg://ask_ai:changeme@localhost:5437/ask_ai_test' \
  uv run pytest tests/scripts/test_v140_existing_db_upgrade_path.py -q → 7 passed

# 提交后三套件
TEST_DATABASE_URL=… uv run pytest tests/scripts/test_v140_existing_db_upgrade_path.py \
  tests/scripts/test_release_migration_plan.py tests/scripts/test_deploy_orchestration.py -q
  → 77 passed, 0 skipped

# CI 同口径全量(build-image test job 同参,含 tests/db、pipeline、scripts 等集成)
TEST_DATABASE_URL=… uv run pytest tests/ -q --ignore=tests/api/admin \
  --ignore=tests/scripts/test_sync_db.py --ignore=tests/embedder --ignore=tests/e2e
  → fixture 修复后 **1844 passed, 1 skipped(提交后复跑该项亦过)/ 0 failed**

# 守卫回归(不变绿验证)
release_integrity_check.py --mode release-publish --tag v1.4.0 --expected-sha 41278f0… → PASS (6 invariants)
release_integrity_check.py --mode production-closure --tag v1.4.0 → FAIL (10 invariants, 3 failures)  # 冻结正确

# 语法:python -m py_compile 全部新改文件 OK;workflow YAML safe_load OK;
#       migrate run 块与远端脚本 bash -n OK
```

测试规模:新增 6(升级路径)+ 23(解析器契约)+ 13(编排迁移阶段契约,
编排文件 37→48)= 42 例;2 例既有编排契约按 §13 显式边界修订,其余逐字未动。

事故场景本地重演(§12):v1.3.0 存量 DDL + 生产同款行 → 同路径迁移 → v1.4 模型
查询通过 —— 即 run 34454739497 的失败链在测试环境被完整重演并修复。**未做、
也不声称任何生产验证。**

## 12. v1.4.0 frozen-artifact compatibility conclusion

**v1.4.0 冻结工件无需任何改动即可被矫正后的生命周期安全部署**:迁移脚本已在
v1.4.0 镜像内(Dockerfile COPY scripts/;blob `b6840c5a` 与候选树一致,测试锁定),
矫正只改编排工具层(orchestration-only)。桥机制为 v1.4.0 提供显式迁移计划,
执行前镜像身份断言绑定冻结 SHA 41278f07eb4abbf4f3420b2d7b65db28c7fdcbb1。
**不触发 V1.4.0 RELEASE ARTIFACT CORRECTIVE DECISION REQUIRED;不创建 v1.4.1、
不改 tag/Release。** tag v1.4.0、Release、RELEASE_SHA 全程未动(本任务零生产
变异、零身份变异)。

## 13. Scope reconciliation(§11)

- 边界内:全部 §4 表所列文件;
- **显式变更边界项(2 项,均测试锁定)**:
  1. `test_only_existing_primitive_no_docker_reimplementation` 由「全 workflow 禁
     `docker compose`」收敛为「按步作用域」:deploy 步仍禁(只调 update.sh,原
     语义全保留);migrate 步作为唯一例外,仅允许以**既有** compose 一次性服务
     `sync` 作镜像内迁移执行载体(README 既有同款用法;无 build、无 up、无新
     服务、无新主机文件)。理由:迁移必须在主机侧、镜像内执行,而 workflow 不
     改 update.sh/compose、不新增主机文件是本矫正的架构前提(主机副本手工维
     护,任何主机文件前置都会制造新的部署失败类)。
  2. `test_guard_before_any_mutation` 扩展为 guard < record_create < **migrate** <
     deploy(迁移本身是生产 DB 变异,必须在 Guard 与在途记录之后)。
- 未越界:无应用/UX/检索/认证/Widget 变更;无生产变异;未重试 v1.4.0;未动
  tag/Release;未回填历史 Release;未创建 Runtime Acceptance/closure 证据。

## 14. Remaining risks

1. **主机 compose 文件陈旧风险**:migrate 步假设主机 `~/ask-ai/deploy/prod/
   docker-compose.yml` 含 `sync` 服务与 `ASKAI_IMAGE_TAG` 必填守卫(现况成立;
   若未来主机漂移,迁移会在 compose 解析处显式失败 → fail-closed,不会静默错迁);
2. **迁移与 update.sh 之间锁间隙**:migrate 与 deploy 是两个步骤,各自持
   flock;同 workflow 并发由 GitHub concurrency 组串行化,间隙内第三方 break-glass
   理论上可插入(现单操作员风险极低;如需绝对串行,后续可把 flock 提升为
   跨步文件锁 —— 非阻塞跟进);
3. **迁移脚本普遍无 dry-run/预检**:本次仅就 launcher_presentation 提供升级路径
   证明;其余 24 个历史脚本未逐一验证幂等(它们属已部署历史,非本矫正范围);
4. 已冻结 v1.4.0 的首次受控部署仍需走既有授权门(Environment/审批语义不变)。
   (Role A 阻断项②修复后,原「清单契约依赖纪律」风险已消除 —— 契约时代
   缺清单现为硬失败,见 §16。)

## 15. Exact candidate commit SHA

- 实现提交:`4d34fa9d56cbc2b7058d9f67f0af2f81849bc407`
- Role A 审查修正提交:`bf88ce3e616822a1b1aa0470fb8ad7db52553411`
- 本报告提交(候选 tip):见 git log 下一提交

---

## 16. Role A REVIEW FIXES(第二轮,2026-09-10)

第一轮 Role A 审查 = CHANGES REQUIRED(2 阻断项)。两处均已修复并加测试锁定。

### 16.1 阻断项① — COMPOSE RELEASE TAG BINDING

- **发现**:迁移步携带 DEPLOY_TAG,但远端脚本调用 `docker compose pull sync` /
  `run --rm sync …` 前未显式提供 `ASKAI_IMAGE_TAG`,未证明 compose 拿到的就是
  冻结 tag。
- **根因**:实现时依赖了生产 compose 的必填插值守卫(`${ASKAI_IMAGE_TAG:?…}`)
  兜底 —— 该守卫确会 fail-closed(缺变量即报错),但那是「隐式失败」而非
  「显式绑定」:绑定语义未在编排层表达,失败也发生在 compose 插值处而非
  迁移身份校验语义处。
- **修正**:远端脚本在任何 compose 调用之前 `export ASKAI_IMAGE_TAG="$DEPLOY_TAG"`
  (DEPLOY_TAG = identity 步冻结、经 `^vX.Y.Z$` 校验的精确发布 tag)—— pull
  与 run 由此解析到**同一冻结镜像**,其 RELEASE.json 随后被断言 == 冻结身份
  (tag → 冻结 40 位 SHA → 镜像 RELEASE.json 断言 → 从该镜像执行迁移,链条
  保持)。compose 文件的必填守卫**原样保留,未削弱**。
- **新测试证据(真实 compose 契约,非字符串排序)**:
  `TestProductionComposeTagBinding` 将**生产** `deploy/prod/docker-compose.yml`
  复制进临时环境并**实际执行 `docker compose config`**:
  - 缺 `ASKAI_IMAGE_TAG` → 非零退出,报错含 `ASKAI_IMAGE_TAG`(不能静默进行);
  - `ASKAI_IMAGE_TAG=v1.4.0` → `backend`/`sync`/`sync-cron`/`sync-executor`
    四服务解析镜像**精确** `ghcr.io/harryhua-ai/ask-ai:v1.4.0`;全部服务无一
    `:latest`;postgres 保持 `postgres:16-alpine`;
  - workflow 契约测试锁定 `export ASKAI_IMAGE_TAG` 位于任何 `docker compose`
    调用之前。

### 16.2 阻断项② — FUTURE MANIFEST ABSENCE MUST FAIL CLOSED

- **发现**:解析器把「无清单 + 无历史桥」一律判为 MIGRATION NOT REQUIRED
  (仅 stderr 警告)—— 契约时代发布若忘带清单,会静默跳过迁移,重演 v1.4.0
  事故类。
- **根因**:第一轮把「文件缺失」同时当作「历史发布」与「忘带清单」两种情形的
  合并信号,只靠日志提醒,没有确定性边界。
- **修正(确定性契约边界,不依赖 mutable main)**:发布是否受清单契约约束,
  由**其自身冻结谱系**决定 —— 谱系中存在「新增 `deploy/prod/migrations.json`」
  的提交(`git log <sha> --diff-filter=A -- <path>`);浅检出无法判定边界 →
  fail-closed(编排 checkout 为 fetch-depth: 0,不受影响)。由此:
  - A. **契约前历史发布**(谱系从未引入清单):仅允许历史桥;桥无条目 →
    NONE(唯一允许缺清单的路径);
  - B. **契约时代发布**:树内**必须**存在 migrations.json;缺失 = 退出码 1,
    部署绝不得进行(含「曾入谱系后被删除」的情形 —— 不得以删除规避契约);
  - C. **空清单** `{"migrations":[]}` = 权威 MIGRATION NOT REQUIRED。
- **新测试证据**:`TestManifestContractEra` 8 例 —— 从未引入清单 → 历史时代;
  谱系含清单 → 契约时代;**added-then-deleted → 仍属契约时代**;契约时代
  缺清单 → 非零失败(stdout 绝不输出 NONE);契约时代空清单 → 权威 NONE;
  浅检出 → fail-closed;git 证据源不可用 → fail-closed;真实 v1.4.0(41278f0)
  → 历史时代(桥入口正确)。

### 16.3 §3 复验结果(全部在修正提交 bf88ce3 后执行)

```
uv run pytest tests/scripts/test_release_migration_plan.py tests/scripts/test_deploy_orchestration.py -q
  → 82 passed(含时代 8 例 + 真实 compose 契约 2 例)
TEST_DATABASE_URL=… uv run pytest tests/scripts/test_v140_existing_db_upgrade_path.py \
  tests/scripts/test_release_migration_plan.py tests/scripts/test_deploy_orchestration.py -q
  → 88 passed
TEST_DATABASE_URL=… uv run pytest tests/scripts/test_v140_existing_db_upgrade_path.py \
  tests/scripts/test_release_integrity_check.py -q → 98 passed
TEST_DATABASE_URL=… uv run pytest tests/ -q --ignore=tests/api/admin \
  --ignore=tests/scripts/test_sync_db.py --ignore=tests/embedder --ignore=tests/e2e
  → **1856 passed / 0 failed / 0 skipped**
守卫冒烟:v1.4.0 release-publish → PASS(6 invariants);production-closure → FAIL(10 invariants,3 failures)——不变绿保持
语法:py_compile 全过;workflow YAML safe_load OK;migrate run 块与远端脚本 bash -n OK
```

测试规模(修正后):升级路径 6 + 解析器契约 31 + 编排契约 51(37→51)= 50 例
净新增;2 例既有编排契约按 §13 边界修订。生产变异:零;v1.4.0 重试:无;
main 合并:无;tag/Release 变异:无。

### 16.4 修正轮提交

- Role A 修正实现提交:`bf88ce3`
- 本报告提交(新候选 tip):见下

---

## Final status

**V1.4.0 MIGRATION CORRECTIVE REVIEW FIX = CANDIDATE READY(两阻断项均关闭)**

- 根因系统修复(生命周期类,非一次性执行)✅
- 存量库升级路径已进入自动化测试(v1.3 DDL → 部署同路径迁移 → 双版本兼容)✅
- migration-before-dependent-app 由 workflow 步序 + 默认 success 语义强制 ✅
- 迁移失败 fail-closed(rollout 不发生、无 success 代码路径,契约测试锁定)✅
- 精确发布绑定(冻结树清单/桥 + 执行前镜像身份断言)✅
- v1.4.0 冻结工件证明可部署且身份零变异 ✅
- 幂等双跑实证 ✅;v1.3.0 回滚兼容实证 ✅
- CI 同口径全量 1844+ 绿;守卫冒烟 publish PASS/closure FAIL 不变绿 ✅
- 零生产变异 ✅

待独立 Role A 审查;不合 main、不部署。
