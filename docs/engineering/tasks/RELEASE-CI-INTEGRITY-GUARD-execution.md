# RELEASE CI INTEGRITY GUARD — 执行报告

- 日期:2026-09-10
- 角色:Agent B(Senior Engineering Executor)
- 任务:RELEASE LIFECYCLE CI INTEGRITY GUARD(#10 版本与发布治理 · 生命周期一致性守卫)
- 基线:origin/main = `9dead69d991a1fe2f3eecdd41623a9839afc0257`
- 分支:`release-ci-integrity-guard`(worktree `.worktrees/release-ci-guard`)
- 并行边界遵守:未创建/移动 tag,未创建/发布 GitHub Release,未部署生产,
  未合 main,未决定版本号,未修复历史 Release(见 §9 边界审计)。

---

## 1. DISCOVERED RELEASE ARCHITECTURE(实测,非推测)

仓库现有生命周期(#10 治理已落地的部分):

```
main(允许存在"已接受未发版"代码 —— 合法状态)
  → Final RC Assembly → release-notes/vX.Y.Z.md(发布说明事实源,人工撰写)
  → git tag vX.Y.Z(显式人工)
  → CI build-image.yml(tag 触发)
      test job → GPU 镜像构建 → RELEASE.json(version=X.Y.Z, git_sha=GITHUB_SHA)
      构建后断言镜像内 RELEASE.json == 本次构建(version + git_sha)
  → 显式人工 GitHub Release(以 release-notes/vX.Y.Z.md 为源;CI 不自动创建,
    tests/scripts/test_release_tooling.py 有契约锁)
  → deploy/prod/update.sh vX.Y.Z(fail-closed 契约:
      缺 tag 拒绝 / latest 拒绝 / 镜像内 RELEASE.json 与 tag 一致才放行 /
      三应用服务 backend+sync-cron+sync-executor 同批同 tag /
      /health 运行时 version 与镜像一致性核验)
  → 运行时验收(人工冒烟;证据记录在本地 docs 仓 —— 非机器可读)
```

机器可读权威 SHA 源盘点(实测):

| 事实 | 权威源 | 状态 |
|---|---|---|
| tag → release SHA | `git rev-parse <tag>^{commit}`(annotated tag 剥壳取 commit) | ✅ 可自动核验 |
| 构建 → SHA | 镜像内 `/app/RELEASE.json`(CI 生成+断言;`backend/release.py` 进程级加载) | ✅ 已有 |
| GitHub Release 对象 | Releases API(按 tag 查) | ✅ 可自动核验 |
| **生产部署 SHA** | **GitHub 侧无任何机器可读记录**(Deployments API 记录数=0;生产 SHA 只活在 tesla-t4 主机:容器 RELEASE.json + /health) | ❌ 缺接口 |
| **运行时验收 SHA** | **无机器可读记录**(人工冒烟,证据在本地 docs 仓) | ❌ 缺接口 |

GitHub Release 历史现状(只读清点,2026-09-10):
v1.0.0 / v1.1.0 / v1.1.1 / v1.1.2 有已发布 Release(带 notes);
**v1.2.0 / v1.2.1 / v1.3.0 有 tag 无 Release** —— 即本守卫要拦截的
"生命周期半途而废"在历史上真实存在。修复处置归并行 Role A,本任务不动。

---

## 2. CHANGED FILES(全部新增,零既有文件改动)

| 文件 | 作用 |
|---|---|
| `scripts/release_integrity_check.py` | 守卫本体:采集(git/GitHub API/manifest)+ 纯函数判定,逐不变量 EXPECTED/OBSERVED 诊断;stdlib-only |
| `scripts/record_production_deployment.py` | 生产部署证据接口:update.sh 完成后运行一次,把 (ref=SHA, environment=production, payload{tag,git_sha}) 记入 GitHub Deployments API;stdlib-only(T4 无 gh CLI 也可跑) |
| `.github/workflows/release-integrity.yml` | 可复用守卫 workflow:`workflow_call`(供发版/部署/闭环流程调用)+ `workflow_dispatch`(人工审计);**无 push 触发** |
| `tests/scripts/test_release_integrity_check.py` | 54 个离线确定性用例(判定矩阵/采集层/CLI/记录脚本/workflow 契约) |
| `docs/engineering/tasks/RELEASE-CI-INTEGRITY-GUARD-execution.md` | 本报告(git add -f,docs/ 在 .gitignore) |

---

## 3. CI DESIGN

**判定与采集分离**:evaluate(纯函数,吃 `ReleaseFacts`)+ collect(git CLI、
GitHub REST、manifest 文件)。测试通过注入 runner / monkeypatch HTTP 全离线,
不访问网络,可重复。`--facts-json` 支持离线喂事实(CI 调试/测试复放)。

**七个不变量与证据源**:

| # | 不变量 | 证据源 | 判定 |
|---|---|---|---|
| 1 | TAG_EXISTS | `git rev-parse <tag>^{commit}`(HEAD probe 区分"git 不可用") | AUTOMATED |
| 2 | TAG_SHA == RELEASE_SHA | 调用方冻结的 `--expected-sha` vs 剥壳 commit;`release-publish` 缺该参数 = FAIL(缺参不可核验,绝不降级 SKIP);`audit` 缺省锚定 tag 自身 SHA(只核验链内一致) | AUTOMATED |
| 3 | GITHUB_RELEASE_EXISTS | `GET /releases/tags/{tag}`;404=缺失;**draft=FAIL(未发布≠发布)**;非 404 错误=COLLECTION FAIL(证据源不可用≠证据缺失) | AUTOMATED |
| 4 | GITHUB_RELEASE_TAG == TAG | Release 对象 `tag_name` | AUTOMATED |
| 5 | RELEASE_NOTES_NONEMPTY | Release `body` 非空白 | AUTOMATED |
| 6 | PRODUCTION_SHA == RELEASE_SHA | Deployments API `environment=production` 最新记录;`sha` 与 `payload.git_sha` 内部自相矛盾也 FAIL(坏证据≠缺证据);**无记录=FAIL(fail-closed)** | PARTIALLY AUTOMATED:核验全自动,但记录依赖 §6 采纳项 |
| 7 | RUNTIME_ACCEPTANCE_SHA == RELEASE_SHA | `deployments/acceptance/<version>.json` manifest(schema 见脚本 docstring:version/tag/git_sha/verified_at/executor/report_path 必填);缺失、非法、字段缺、SHA 背离均 FAIL | PARTIALLY AUTOMATED:核验全自动,首个 manifest 待正式验收产生 |

附加观察项:`RELEASE_TARGET_COMMITISH == TAG_SHA`——target 为 40 位 SHA 时
强制一致;为分支名(如 main)时按创建约定视为一致(不伪造矛盾)。

**失败语义**:任何 FAIL → 退出码 1,stdout 逐行
`[FAIL] <INVARIANT>  expected=…  observed=…  # 诊断`;证据源不可用
(鉴权/限流/5xx)≠ 证据缺失,一律红。退出码:0 全 PASS / 1 生命周期失败
(含采集失败)/ 2 用法错误。无 warning 降级通道。

**模式**:`release-publish`(不变量 1–5,expected-sha 必填)/
`production-closure`(1–7)/ `audit`(同 closure;tag 缺省自动取最新
vX.Y.Z;expected-sha 缺省锚定 tag)。

---

## 4. INVARIANT MATRIX(AUTOMATED / PARTIAL / UNVERIFIABLE)

| 不变量 | 状态 | 缺口 |
|---|---|---|
| TAG_EXISTS | AUTOMATED | — |
| TAG_SHA == RELEASE_SHA | AUTOMATED | RELEASE_SHA 由调用方冻结输入(版本决策属 Role A/治理,守卫不发明) |
| GITHUB_RELEASE_EXISTS | AUTOMATED | — |
| GITHUB_RELEASE_TAG == TAG | AUTOMATED | — |
| RELEASE_NOTES_NONEMPTY | AUTOMATED | — |
| PRODUCTION_SHA == RELEASE_SHA | **PARTIALLY AUTOMATED** | 生产 SHA 无 GitHub 侧记录源 → 已提供最小接口 `record_production_deployment.py`;运行簿接入属流程采纳决策(见 §6) |
| RUNTIME_ACCEPTANCE_SHA == RELEASE_SHA | **PARTIALLY AUTOMATED** | 验收证据约定已定义(manifest schema);首个正式验收 manifest 待产生;不伪造样例数据 |

未实现 NOT YET MACHINE-VERIFIABLE 假证据:守卫对缺记录/坏记录一律
fail-closed,今天对 v1.3.0 跑 closure/audit = 红(与历史事实一致)。

---

## 5. ENFORCEMENT POINTS(实测评估 + 接入建议)

| 触发点 | 评估 | 本候选的动作 |
|---|---|---|
| 普通 push main | **不得挂** —— main 上"已接受未发版"合法,挂上必然误伤 | `release-integrity.yml` 无 push 触发(测试有契约锁);`build-image.yml` 零改动(测试证明无守卫引用) |
| tag push(镜像构建) | tag push 时 Release 往往尚未创建(现流程为显式人工步骤);硬挂会按错误顺序必红 | 不改 `build-image.yml`;由发版流程在**创建 Release 之后**显式调用守卫 |
| Release 创建/发布(建议) | Role A 冻结新发版流程时,在 Release 创建步骤后 `uses: ./.github/workflows/release-integrity.yml`(mode=release-publish, expected_sha=冻结 SHA) | workflow_call 已就绪 |
| 生产部署后(建议) | `update.sh vX.Y.Z` 成功后运行一次 `record_production_deployment.py --tag vX.Y.Z`,再触发守卫 closure 模式 | 接口已交付;**运行簿一行接入属流程采纳决策,本候选不改 update.sh**(零部署架构变更) |
| 事后审计 | `workflow_dispatch`(人工/未来可加 schedule)对任意或最新 tag 审计 | 已交付;schedule 默认不开(历史缺口未修复前会持续红,属已知事实而非噪声) |

MAIN UPDATED 与 FORMAL RELEASE/CLOSURE 的区分即由"无 push 触发 +
显式按 release 身份调用"保证。

---

## 6. TEST RESULTS(全部离线确定性)

```
tests/scripts/test_release_integrity_check.py   52 passed
  + tests/scripts/test_release_tooling.py(既有 #10 契约回归)      21 passed
  合计 73 passed(black 格式化后复跑通过;2 warnings =
  class-scoped fixture 弃用提示,与既有 test_release_tooling.py 同款写法)
```

覆盖矩阵(任务 §6 逐项):

- PASS:全身份一致(publish / closure / audit 锚定)✅
- FAIL:tag SHA ≠ 冻结 SHA ✅;Release 缺失(404)✅;Release tag ≠ 请求 tag ✅;
  notes 空 ✅;draft 未发布 ✅;target_commitish SHA 背离 ✅;
  生产 SHA ≠ release SHA ✅;生产记录缺失(fail-closed:正式部署不得静默
  当闭环)✅;生产记录内部自相矛盾 ✅;验收 SHA 背离 ✅;验收 manifest
  缺失 ✅;坏 manifest(缺字段/version 不一致)✅;
  publish 缺 expected-sha(fail-closed 缺参)✅;
  GitHub 401/5xx=采集失败非缺失 ✅
- workflow 契约:无 push 触发 ✅;仅 call+dispatch ✅;call inputs 完整 ✅;
  dispatch 默认 audit ✅;checkout fetch-depth 0 ✅;build-image.yml 未被
  接线 ✅
- 记录脚本:POST 体(ref/environment/payload/required_contexts)✅;
  status success ✅;缺 token 拒绝 ✅;API 失败非零 ✅;真实临时 git 仓
  解析 tag SHA ✅
- **真机只读冒烟**(对真实仓库 + 真实 GitHub API):
  - `audit v1.3.0` → FAIL(无 Release/无生产记录/无验收 manifest)——
    与已知历史缺口一致,确定性暴露 ✅
  - `release-publish v1.1.2 @ cdbcad38…`(annotated tag 剥壳 commit)
    → 6/6 PASS ✅(注:`git rev-parse v1.1.2` 得 073f262 是 tag 对象,
    权威 release SHA = `^{commit}` 剥壳结果,守卫语义与此对齐)
  - 坏 token → FAIL(401 采集失败,不得当缺失)✅

---

## 7. KNOWN GAPS(诚实清单)

1. **生产 SHA 记录源不存在**(PARTIALLY AUTOMATED)。最小补充接口已交付
   (`record_production_deployment.py`);把"update.sh 成功后运行一次记录"
   写进生产运行簿 = **一行流程采纳决策**,属 Planner/Role A 治理范围,
   本候选未改 update.sh(零部署架构变更,不触发 ARCHITECTURE DECISION)。
2. **验收 manifest 约定无实例**:首次正式验收时按 schema 提交
   `deployments/acceptance/<version>.json`(经 PR 可审阅)。本候选不伪造样例。
3. **历史缺口**:v1.2.0 / v1.2.1 / v1.3.0 无 GitHub Release、全部历史无
   生产/验收机器记录 —— 守卫如实红。修复处置(补发 Release / 追溯记录)
   归并行 Role A 的历史审计与修复授权,**本任务零触碰**。
4. `release-notes/vX.Y.Z.md`(事实源文件)存在性未纳入守卫不变量
   (任务授权的七项之外;历史 v1.1.x+ 也缺该文件)。建议历史修复后由
   Planner 决定是否增加 NOTES_FILE_EXISTS 不变量。
5. GHCR 镜像存在性(tag → image 是否已构建)未自动核验(GHCR API 需包
   读写权限,超出 contents:read);交叉证据由 build-image.yml 的构建期断言
   与 update.sh 的部署期断言承担。列为后续可选增强(需权限决策)。

---

## 8. 交付字段

- DISCOVERED RELEASE ARCHITECTURE:§1
- CHANGED FILES:§2(5 文件全新增,零既有文件改动)
- CI DESIGN:§3
- INVARIANT MATRIX:§4(5 AUTOMATED / 2 PARTIALLY AUTOMATED / 0 伪造)
- ENFORCEMENT POINTS:§5
- TEST RESULTS:§6(73 passed + 三轮真机只读冒烟)
- KNOWN GAPS:§7
- BRANCH:`release-ci-integrity-guard`
- CANDIDATE SHA:见交付消息(commit 后回填)
- REPORT PATH:`docs/engineering/tasks/RELEASE-CI-INTEGRITY-GUARD-execution.md`

## 9. CHANGE BOUNDARY AUDIT

- ✅ 未创建/移动/删除 tag;未创建/编辑/发布 GitHub Release
- ✅ 未部署生产;未 SSH 任何生产主机;未改 update.sh / compose / Dockerfile
- ✅ 未合 main;未动正确性活动谱系(I-UX-001 corrective 已并入 9dead69,零触碰)
- ✅ 未决定版本号、未写任何 vX.Y.Z 常量(守卫全参数化;用例里的 v1.3.0 仅为
  fixtures 样例数据)
- ✅ 未触碰产品行为 / Widget / 检索 / 证据语义 / 认证
- ✅ 无关 CI 零改动(build-image.yml 仅被测试只读断言)
- ✅ 无 ARCHITECTURE DECISION REQUIRED 事项:全部改动为新增 CI 支撑脚本
  + workflow + 测试 + 文档,部署架构与产品治理未被更改;§7.1/7.2 的
  采纳决策已显式留给 Planner。

**RELEASE CI INTEGRITY GUARD = CANDIDATE READY**
