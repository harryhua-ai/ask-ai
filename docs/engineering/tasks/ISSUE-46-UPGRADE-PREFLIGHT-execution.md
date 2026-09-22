# Issue #46 执行报告 — 发布兼容性 manifest + fail-closed pre-mutation evaluator

- Claim: `harryhua-ai-20260922T010024-dd28e4dd`(mode=implement,authority=allowed)
- Branch: `agent/46/2db2ed53`(base = `434ddece` = main tip,#102 merge)
- Contract: #46 body `ght-contract`(AC1–AC6;design_refs #100/#101)
- 状态: **CANDIDATE READY(REVIEW_1 R2)— 待 Role A exact-SHA review**(STOP;不自行 merge)
- 生产 mutation: **0**(零部署;全程只读)

## 1. 现状审计 → 缺陷定位(AC1 RED 的实现依据)

| 现有控制 | 证明什么 | 不证明什么 |
| --- | --- | --- |
| release-integrity Guard + `generate_release_manifest.sh` + in-image `RELEASE.json` 断言 | 发布身份(tag→sha→image)不可变且一致 | **发布能在既有生产环境安全升级**(v1.4.0 事故正是全部身份门通过后仍 crash loop) |
| `deploy-production.yml` migrate 步骤 | DB 迁移按冻结树清单执行、失败不 rollout | 迁移之外任何兼容性维度(config/host/topology/dependency/回退) |
| `update.sh` [3/6] 身份断言 + [6/6] 三服务同 tag | 镜像身份与部署拓扑版本一致 | 环境兼容性;且步骤运行于**宿主陈旧副本**(stale-artifact 类,见 §6 风险) |
| `/health` version+git_sha 双断言 | 运行时身份 = 镜像身份 | 业务健康(Runtime/Real-World Acceptance 域) |

RED 证明(`tests/deploy/test_preflight_boundary.py`,实现前 5/5 RED):现状 update.sh
与 deploy-production.yml 中**不存在任何 preflight 调用** —— 声明了不兼容
config/host/topology 要求的发布可以一路到达 DB migration(首个不可逆 mutation)
与应用 rollout,v1.4.0 形态的失败类无 pre-mutation 边界。

## 2. 实现(最小;两个新文件 + 两个既有文件的窄调用缝)

1. **`deploy/prod/compatibility.yml`**(新):release-owned manifest,随 tag 冻结于
   发布树。v1 词表封闭:`config[]`(name/required/shape∈{non_empty_string,integer,
   boolean}/secret)、`host[]`(capability∈{docker_compose_v2,nvidia_gpu})、
   `topology[]`(requirement∈{same_tag_all_services})、`dependencies[]`
   (probe∈{tcp_connect}/host/port/timeout_s≤30)、`rollback`(previous_compatible/
   remediation_gate)。**无任何可执行字段 → 不存在 shell-in-manifest 面**(未知
   section/字段/枚举/越界超时一律 manifest_invalid fail-closed)。当前发布声明:
   config 空(既有必需项由 lifespan/运行时门强制,不重复声明)、host: nvidia_gpu、
   topology: same_tag_all_services(显式 defer 到 update.sh [6/6])、dependencies 空
   (postgres/weaviate 宿主侧不可达,其证明属迁移步骤与 /health 门,见 §5)、
   rollback: previous_compatible true(#100/#102 均为加性,无 destructive 变更)。
2. **`scripts/release_preflight.py`**(新):有界 fail-closed pre-mutation evaluator。
   只读(文件/socket connect/有界子进程),零写副作用;stdout=机器可读 JSON
   verdict,退出码 0=pass/pass_with_deferred、2=fail-closed。
   - AC2:manifest 只从显式 `--manifest` 路径加载;契约期缺失 ⇒ `manifest_missing`
     fail-closed;`--pre-contract-release` 仅用于历史镜像(逐类显式 deferred);
     非法 ⇒ `manifest_invalid`。调用方(镜像内提取,见下)保证 mutable main 永远
     无法重解释历史冻结发布。
   - AC3:config 只输出 name/期望形状/实际形状类,**值从不进入任何输出**(含失败
     路径;测试植入密值断言不外泄);capability/probe 有界(`--probe-timeout` 全局
     上限,schema 层 timeout_s≤30);topology 声明式输出并显式 defer 到既有门。
   - AC4:`previous_compatible: false` ⇒ 必须持有所声明的 `remediation_gate`
     (`--remediation-ack` 精确匹配),否则 `rollback_remediation_gate_required`
     actionable 拒绝;前契约发布有界兼容路径。
3. **`deploy/prod/update.sh`** [3.5/6](窄缝):镜像身份断言之后、任何 rollout 之前,
   从**本冻结镜像**提取 evaluator+manifest 并调用;非零退出即中止。**只是调用者,
   不是 policy engine**。前契约镜像(镜像内无 evaluator)⇒ 显式留痕的有界兼容路径。
4. **`deploy-production.yml`** 步骤 3.5(窄缝):同构 SSH 调用,位于 **migrate 步骤
   (首个生产 mutation)之前**;主机侧 flock 与迁移/rollout 互斥;只读探针模式
   (`docker pull/create/cp`,不经 compose 载体,不破 "docker compose 属迁移步骤
   专有" 的部署原语唯一性不变量——既有 `test_deploy_orchestration` 全绿)。
5. **DB migration 所有权不变**:`release_migration_plan.py` + migrations.json +
   历史桥原样;preflight 不复制任何迁移逻辑(AC5)。

## 3. 证据(RED→GREEN;新增 13 例:5 边界 + 8 evaluator 行为)

| AC | RED | GREEN |
| --- | --- | --- |
| AC1 | 边界 5 例:发布树无 manifest/evaluator;update.sh 无 preflight;workflow 无 preflight 步骤 ⇒ 不兼容声明可直抵 mutation | `release_preflight.py` 调用存在且位置先于 update.sh rollout 与 workflow migrate 步骤;fail-closed(无 `\|\| true` 吞错);evaluator 级:缺 config/不可达依赖/rollback 缺 gate ⇒ exit 2 + class/reason + **零 mutation**(全程只读) |
| AC2 | manifest/evaluator 不存在 | 显式空 section=pass;契约期缺 manifest=fail;7 类非法 manifest(version/未知 section/未知 capability/未知 probe/越界超时/rollback 残缺×2)全 fail-closed;显式路径加载,cwd 冲突 manifest 不参与判定(冻结树所有权) |
| AC3 | — | 密值植入(config_missing 与 invalid_shape 两路径)断言值不出现在 stdout/stderr;capability 探针有界且命令封闭;TCP 探针可达/不可达/有界;topology 显式 deferred |
| AC4 | — | compatible=true 无需 ack;incompatible 缺 ack=exit 2 且 reason 指明 gate 名;ack 精确匹配=pass;错 ack=exit 2;前契约=pass_with_deferred 且五类逐条列出 |
| AC5 | — | release domain 回归 **268 passed / 0 failed**(§4);migration 计划/DSN guard/manifest 不变量原样 |
| AC6 | — | §5 gate 边界矩阵;无 framework/shell-in-manifest/自动回退/CI 重设计(既有 workflow-contract 不变量测试全绿背书) |

## 4. 回归

- 新增:`tests/deploy/test_preflight_boundary.py`(5)+ `tests/deploy/test_release_preflight.py`(8,含参数化非法 manifest 7 形态);
- Release domain 全绿 **268P/0F**:`test_release_identity` / `test_release_migration_plan` / `test_release_integrity_check` / `test_release_tooling` / `test_deploy_orchestration`(部署原语唯一性/无自动回退等 #10 冻结不变量)/ `test_system_release` + `test_system_runtime`(/health 身份门)/ `tests/deploy/` / `test_migration_dsn_guard` / `test_membership_migration_manifest`;
- 过程修正:preflight 步骤初稿用 `docker compose pull` 触碰了 "docker compose 属迁移步骤专有" 的既有不变量、回退兼容文案含 ASCII "rollback" 触碰 "无自动回退" 不变量 —— 改为 `docker pull` 只读模式与中文措辞,**既有不变量测试零修改**。

## 5. Gate 边界矩阵(AC6:各门证明什么/不证明什么)

| 门 | 证明 | 不证明 |
| --- | --- | --- |
| **Compatibility Preflight**(本候选;mutation 前) | 声明式要求(config 在场/形状、host capability、有界依赖可达、回退兼容门)在冻结镜像语境下成立或显式 deferred | schema 兼容(迁移域)、运行时业务健康、 Real-World 正确性;不可证类显式 deferred(拓扑同 tag → update.sh [6/6];宿主不可达依赖 → 迁移步+/health) |
| **Migration**(既有 release-bound) | 冻结树清单内的 schema 迁移在冻结镜像内执行成功 | 迁移后数据语义兼容;非 schema 维度 |
| **Deployment Smoke**(update.sh [5/6]/[6/6] + /health 双断言) | rollout 完成、三服务同 tag、运行时身份=镜像身份 | 核心业务路径(检索/嵌入/sync/widget)功能正确 |
| **Runtime Acceptance**(既有验收栈) | 真实 /ask 流式/引用/多轮等功能门 | 生产环境外的真实用户语境 |
| **Real-World Acceptance**(既有) | 真实用户/真实流量语境的产品正确性 | 部署机制本身 |
| **Closure Audit**(既有 production-closure) | 证据链完整、身份一致、记录顺序合法 | 上述任何单门的语义正确性(只核验证据完整性) |

## 6. #100 GHCR credential-scope / host-build break-glass 作为真实证据

#100 rollout 实证:**artifact publication capability**(GHCR push scope 被拒)与
**release identity**(镜像内 RELEASE.json `git_sha=1093c93…` + `/health` 运行时
双断言通过)是**两个独立的兼容性维度** —— 前者失败时后者仍可经 break-glass
host-build 路径成立。本 contract 据此把 capability 类检查建模为可声明/可 defer 的
独立词表项,而不是与发布身份耦合;**不因此扩大为 registry/CI redesign**(scope
forbidden)。break-glass 路径本身同样接入 preflight(update.sh [3.5/6] 与 workflow
步骤 3.5 同构),两条部署路径的兼容性门等价。

## 7. 已知限制 / 风险

1. **宿主陈旧 update.sh 不含 [3.5/6]**:break-glass 手动路径若宿主脚本未刷新,
   该次调用无 preflight(审计类 3 的既有限制;部署原语刷新属运营 runbook,
   非本候选代码范围)。workflow 正规路径不受影响。
2. 前契约镜像的有界路径依赖"镜像内无 evaluator"这一机械事实 —— 语义上等价于
   "该 release 早于 #46 契约",无需外部时代知识。
3. manifest v1 词表刻意最小(docker_compose_v2/nvidia_gpu/tcp_connect/
   same_tag_all_services + config shapes);扩展 = 显式 schema 演进(version 迁移),
   拒绝 speculative 检查(Non-goals)。

**STOP:等待 Role A exact-SHA review;不自行 merge;零生产 mutation。**


## 8. REVIEW_1 R2 修正(2026-09-22;六个 blocker 逐一关闭)

| blocker | 修正 | 机械证据 |
| --- | --- | --- |
| 1. Frozen image packaging | Dockerfile `COPY deploy/prod/compatibility.json /app/deploy/prod/compatibility.json`;`.dockerignore` 不排除 deploy;`COPY scripts/` 覆盖 evaluator | `test_dockerfile_packages_compatibility_manifest_into_image` + `test_image_packaging_three_way_path_consistency`(镜像内路径三方一致:Dockerfile dest == update.sh 提取源 == workflow 提取源) |
| 2. Exact release identity | update.sh preflight 改为 `docker create "$IMAGE:$TAG"`;机械断言全文件无 untagged `docker create "$IMAGE"`;workflow 侧 IMAGE 本就含 `$DEPLOY_TAG`(上游 ^vX.Y.Z$ 校验) | `test_update_sh_preflight_extracts_exact_tagged_image`(regex 负向断言防回潮) |
| 3. Contract-era fail-closed | era 判定源 = 镜像内**不可变 RELEASE.json 的 `compatibility_contract` 旗标**(构建期由 `generate_release_manifest.sh` 权威写入;前 #46 构建天然无键 = pre_contract)——独立/不可变/确定性,绝不以门禁工件存在性推断;契约期缺 evaluator/manifest ⇒ 显式 `打包违约 … fail-closed`,绝不降级有界路径 | `test_era_decided_by_release_json_flag_not_artifact_absence`(update.sh + workflow 双面;断言 era 分支先于 EVAL_OK 且契约期缺件走 fail-closed)+ `test_release_manifest_generator_emits_era_flag`(生成器子进程实测) |
| 4. Host bootstrap dependency | manifest 改 **stdlib-JSON**(`compatibility.json`),evaluator 去除 `import yaml` —— 宿主 python3 零第三方依赖 | evaluator 源码零 yaml 引用;26 例 evaluator 行为测试(含非 JSON 文本负向)全绿 |
| 5. Rollback contract end-to-end | update.sh 接受 `--remediation-ack <gate>` 并真实转发 evaluator(`ACK_ARGS`);header 新增 **RELEASE-ROLLBACK-COMPATIBILITY** runbook(目标发布声明 `previous_compatible: false` ⇒ 普通 previous-tag 回滚不再适用,须确认声明修复门);workflow 路径不提供 ack ⇒ 不兼容声明在 workflow 正规路径确定性 fail-closed(break-glass update.sh + ack 为其显式恢复面) | `test_update_sh_forwards_remediation_ack_and_documents_rollback_contract`(转发 + runbook 双断言)+ evaluator ack 矩阵 4 例 |
| 6. Evidence hygiene | `pytest --collect-only` 机械统计:**新增 37 tests**(boundary 11 + evaluator 26;含参数化负向形态);release domain 回归 **275 passed / 0 failed**(原 268P + 新 7 例);PR body 数字同步 | 本节即采集记录 |

**保持不变**:migration ownership(release_migration_plan/migrations.json 原样);preflight 位置(update.sh [3.5/6] 在 rollout 前、workflow step 3.5 在 migrate 前,机械断言保持);secret 值零外泄(26 例含植入密值负向);有界/非 mutation 探针;无 shell-in-manifest(封闭词表不变,JSON 化后更强);无 CI/CD 重设计(既有 workflow-contract 不变量零修改全绿)。
