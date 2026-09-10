# PRODUCTION DEPLOYMENT ORCHESTRATION — 执行报告

> Agent B 执行报告 · 2026-09-10 · 候选分支 `impl/production-deployment-orchestration`
> 基线 `e1544ba47aa76c70e32fcaf023c46cda93b37feb`(新鲜对账零漂移);本报告所在提交即候选提交。
> 发现报告结论(READY FOR CONTRACT)的冻结决策全部落地;零生产 mutation。

## 1. 冻结架构 → 实现映射

```
workflow_dispatch(tag)                        deploy-production.yml(仅此触发)
→ production Environment 审批                 job.environment = production(审批由 GH 设置承担)
→ 校验输入 vX.Y.Z → git 解析 → 冻结 SHA       identity 步(^vX.Y.Z$ 正则;rev-parse <tag>^{commit};
                                              40 位校验;outputs tag/sha/version)
→ release-publish Guard(--expected-sha)      guard 步(调用既有 release_integrity_check.py,
                                              FAIL 即终止,SSH 之前)
→ Deployment = in_progress                    record_create 步(recorder --phase create)
→ GitHub 托管 runner SSH(严格主机键)         deploy 步(known_hosts 钉扎 + StrictHostKeyChecking=yes
                                              + BatchMode + trap 清理密钥材料)
→ 主机侧 flock                                远端命令 `flock -w 0 /tmp/askai-deploy.lock`
→ 既有 update.sh <tag>                        唯一部署原语;零 docker 逻辑复现
→ /health 双断言 version + git_sha            verify_identity 步(scripts/verify_runtime_identity.py)
→ Deployment = success                        record_success 步(if: success())
```

## 2. 变更清单(对基线 e1544ba)

| 文件 | 类型 | 内容 |
| --- | --- | --- |
| `.github/workflows/deploy-production.yml` | 新增 | 编排 workflow(§1 全序) |
| `scripts/record_production_deployment.py` | 扩展 | `--phase create\|success\|failure\|error` + `--deployment-id`;新增 `_get_request`(GET,404≠不可用)与按 sha 解析最新记录(按 id 最大,免排序假设);**原子模式(create+success)逐字节保持 = break-glass 兼容**(修复过一处实现错误,见 §6) |
| `scripts/verify_runtime_identity.py` | 新增 | /health 双断言(version + git_sha);编排与 break-glass **共用同一验证器** |
| `tests/scripts/test_deploy_orchestration.py` | 新增 | 37 个契约/单测(§5) |
| `deploy/prod/update.sh` | 纯注释 | 头部补"两条等价部署路径"(编排 + break-glass 等价、主机非 git 仓库的身份来源约束);`bash -n` 通过,零逻辑改动(单 hunk 全在注释区) |
| `docs/engineering/tasks/PRODUCTION-DEPLOYMENT-ORCHESTRATION-execution.md` | 新增 | 本报告 |

未动:`release-integrity.yml`、`build-image.yml`、backend/widget/admin、Dockerfile、compose、v1.4.0 tag/Release。

## 3. 关键工程决策

1. **权限最小化**:`contents: read + deployments: write`;**不含 packages:read** —— 冻结序列不含 workflow 侧 GHCR 预检(镜像缺失由 update.sh [2/6] pull 失败暴露并走 failure 记录路径),故不加。
2. **凭证面**:GitHub 侧新增仅一把专用部署私钥(Environment secret `PROD_DEPLOY_SSH_KEY`)+ 4 个 repository variables(`PROD_SSH_HOST/PROD_SSH_USER/PROD_SSH_KNOWN_HOSTS_B64/可选 PROD_BACKEND_PORT`)。**不提交主机 IP/主机名进仓库**(public 仓库);known_hosts 以 base64 var 钉扎,decode 后非空且须 `grep -q "$SSH_HOST"` 匹配,否则 fail-closed(绝不关闭严格主机键校验,workflow 全文无 `accept-new`/`StrictHostKeyChecking=no`)。GHCR 拉取凭证留在主机(现状);GITHUB_TOKEN(内置,deployments:write)做记录,**无 PAT**。
3. **env 数据边界**:全部 `inputs/secrets/vars/steps.outputs` 只出现在 env 值位;8 个 run 块均有 `set -euo pipefail` 且零 `${{` 插值(契约测试强制)。DEPLOY_TAG 经 `^vX.Y.Z$` 正则 + 单引号双层防护进远端命令。
4. **flock 语义**:`-w 0` 非阻塞 —— 已有部署在跑立即失败(不加塞不排队),与 GitHub concurrency(group=production-deployment, cancel-in-progress=false,排队不取消)构成双层防重;锁在 update.sh 之外,原语零改动。
5. **身份唯一性**:`github.sha` 全文不出现(契约测试断言);main HEAD 与发布身份无关;SHA 只在 identity 步解析一次后冻结贯穿 Guard/记录/双断言。
6. **失败矩阵**(全部"绝不 success"):
   - Guard 失败 → 无 SSH、无记录(record_create 的 created 标志未置,失败收尾步条件不触发);
   - 记录建立后任何失败(SSH/锁/update.sh/身份不匹配)→ `record_failure` 步收尾 failure(条件 `failure() && created=='true' && record_success.outcome != 'failure'`,避免覆盖已成功收尾);
   - 成功证据落盘失败(生产可能已变更)→ **不写 failure**(不得与真相矛盾),打印 `PRODUCTION STATE RECONCILIATION REQUIRED` 并红;
   - 取消/传输不确定 → 状态停留 in_progress(守卫侧非 success 一律 fail-closed),等操作员对账 —— 冻结决策 8(不做 nohup/setsid 脱离)如实遵守;
   - 无自动回滚:workflow 全文无 rollback 代码路径(契约测试断言);回滚 = 同一 workflow dispatch 上一不可变 tag。
7. **recorder 分阶段**:`create`=Deployment+in_progress(在途记录在 update.sh 启动**前**建立 —— in_progress 在守卫侧非 success,不构成部署声明);`success/failure/error` 按 (sha+environment) 解析最新记录(id 最大,免 API 排序假设;`--deployment-id` 可显式钉死)追加状态,找不到记录退出码 2(不得凭空新建成功)。

## 4. BREAK-GLASS 等价路径(已写入 update.sh 头部运行簿)

手动 SSH + `update.sh <tag>` → 用**同一** `verify_runtime_identity.py` 独立核验 version+git_sha(发布 SHA 来自仓库侧权威解析;主机 `~/ask-ai` 非 git 仓库,已明文禁止主机侧 git 解析身份)→ 同一 recorder(原子模式 create+success,或 --phase success)→ 同一 GitHub Deployment 模型。测试 `test_break_glass_atomic_mode_unchanged` + `test_create_phase_same_evidence_model_as_break_glass` 证明两条路径证据模型逐字段同构。

## 5. 测试结果

- **新增套件** `tests/scripts/test_deploy_orchestration.py`:**37 passed**,覆盖任务要求的每一项:
  输入校验(bash 级实证:合法 tag 解析冻结 8 断言;latest/main/v1/v1.2/1.2.3/v1.2.3-rc.1/abc123/v01.2.3/未知 v9.9.9 全拒)、Guard-先于-变更步序、成功收尾仅位于双断言后(if: success())、失败收尾条件与 RECONCILITION 横幅、env 数据边界(8 run 块零 `${{` 插值)、严格 SSH 键策略(含无 accept-new/no)、并发契约、recorder in_progress→success、failure/error 追加、无记录拒绝、SHA 不匹配拒绝、SSH/update.sh 失败→无成功、break-glass 等价、无 main-HEAD 身份、无自动回滚、release-integrity.yml 未被改动。
- **回归**:`tests/scripts/` 全量 **290 passed, 3 skipped**(基线 253 + 37);其中守卫套件 92 与 tooling 21 保持全绿(含既有 recorder 原子模式契约)。
- **真实 v1.4.0 只读冒烟**(候选树):release-publish **PASS(exit 0,6 不变量)**;production-closure **FAIL(exit 1,10 不变量 4 缺证据)** —— 编排工具的加入未给 v1.4.0 制造任何 PASS。
- 语法:`py_compile` ×2 OK;`bash -n update.sh` OK;workflow YAML safe_load OK。

## 6. 执行期间发现并修复的实现错误(诚实记录)

初版 recorder 把**原子模式**(break-glass)的收尾状态误写为 in_progress(复用了 create 分支的 `PHASE_STATE[...]` 缺省),被本任务新增测试 `test_break_glass_atomic_mode_unchanged` 当场拦截 —— 已修复为原子模式固定 `success`(其运行簿语义就是"部署成功并核验后一次性记录"),并用 create 阶段证据模型同构测试二次确认。此即"契约测试不信任实现"的直接价值。

## 7. CONNECTIVITY PREFLIGHT = **UNPROVEN**(如实报告)

Environment `production`、Environment secret `PROD_DEPLOY_SSH_KEY` 与 4 个 repository variables 尚未配置(GitHub 侧现状:0 environment / 0 secret,发现报告已勘明),因此**无法**从 GitHub 托管 runner 发起非破坏性连通性验证(且任何一次 dispatch 都会走完整部署路径,不可用作探针)。发现期实证仍有效:操作员主机 → 公网 SSH 密钥认证可达;runner 出口 → 主机的实际可达性保持 **UNKNOWN → UNPROVEN**。

操作员开通清单(全部为 GitHub/主机设置,非本仓提交数据):
1. 建 Environment `production`(建议 required reviewer = harryhua);
2. 生成专用部署密钥对,公钥入主机 `~ubuntu/.ssh/authorized_keys`(建议限 from= 源),私钥存 Environment secret `PROD_DEPLOY_SSH_KEY`;
3. 设 repository variables:`PROD_SSH_HOST`、`PROD_SSH_USER=ubuntu`、`PROD_SSH_KNOWN_HOSTS_B64`(`ssh-keyscan <host>` 结果整行 base64);
4. 首次部署前可用一条一次性探针(只读 `echo`)验证 runner→主机可达。

## 8. 生产 mutation 审计

零:未 dispatch 任何 workflow、未触碰容器/主机状态(发现期探测均为 echo/uname/docker ps 只读)、未创建 Deployment/Runtime Acceptance 证据、未动 v1.4.0 tag/Release、未回填历史、未并 main。生命周期保持:v1.4.0 RELEASE CREATED · PRODUCTION NOT DEPLOYED · RUNTIME ACCEPTANCE PENDING · LIFECYCLE NOT CLOSED。下一门:Role A 独立审查;其后为操作员开通(§7 清单)→ 首次受控部署(建议即 v1.4.0)。
