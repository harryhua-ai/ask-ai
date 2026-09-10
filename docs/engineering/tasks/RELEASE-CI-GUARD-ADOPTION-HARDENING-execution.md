# RELEASE CI GUARD — PRODUCTION-CLOSURE ADOPTION HARDENING 执行报告

> Agent B 执行报告 · 2026-09-10 · 候选分支 `impl/release-ci-guard-adoption-hardening`
> 本报告所在提交即候选提交(SHA 见分支 HEAD;候选分支正常推送,未并 main)。

## 1. 任务与授权边界

四项已接受的 Release CI Guard adoption 跟进(production-closure 强制执行前必须完成),
治理裁决已冻结,本任务只负责 HOW:

1. production-closure 必须要求权威生产部署记录的 effective/latest status = success;
2. Runtime Acceptance manifest `report_path` 必须解析为真实入库仓库证据;
3. 生产记录运行簿必须把证据创建绑定到 update.sh 成功 + /health 身份核验之后;
4. workflow inputs 不得以 `${{ inputs.* }}` 直接内插进 shell 源码。

明确不做(与本任务无关,保持原状):不部署 v1.4.0;不创建生产/验收证据;
不动 v1.4.0 tag/Release/release-notes;不回填 v1.2.0/v1.2.1/v1.3.0;不改产品行为。

## 2. 基线

- 执行基线:`origin/main = 6b9d7f74ebf0915a6b1682b09d7f394a46e9de75`
  (新鲜 fetch 对账,零漂移;本地 main 同值,worktree clean)。
- 隔离工作树:`.worktrees/guard-adoption`,分支
  `impl/release-ci-guard-adoption-hardening` 自 6b9d7f7 创建。
- v1.4.0 发布身份(不可变):tag v1.4.0 → `41278f07eb4abbf4f3420b2d7b65db28c7fdcbb1`。
- 生命周期现状:v1.4.0 RELEASE CREATED / PRODUCTION NOT DEPLOYED /
  RUNTIME ACCEPTANCE PENDING / PRODUCTION CLOSURE NOT ESTABLISHED。

## 3. 调查

### 3.1 现状架构(改动前)

- `scripts/release_integrity_check.py`(577 行):closure/audit 采集
  deployments 列表后仅做「记录存在 + sha 与 payload.git_sha 互证 + ==release_sha」;
  manifest 仅校验 `report_path` 非空。status 维度完全缺失。
- `scripts/record_production_deployment.py`(138 行):创建 Deployment 并立即
  回写 status=success;docstring 已写 "update.sh 完成后运行一次" 但顺序未成契约。
- `.github/workflows/release-integrity.yml`:run: 块内 5 处
  `${{ inputs.* }}` 直接内插(GitHub 表达式在 run: 内是**文本替换**,
  等价于把外部输入拼进 shell 源码)。
- `deploy/prod/update.sh`:头部即权威部署契约([1/6] 显式 tag 拒 latest、
  [3/6] 镜像 RELEASE.json 断言、[5/6] /health 运行时版本核验、[6/6] 三服务同 tag),
  但没有"何时允许记录部署证据"的条款。
- `deploy/prod/README.md` 为 gitignore 本地文件(`.gitignore:58`),
  **不是**可入库的权威运行簿位置 → 选择扩展 update.sh 头部契约 + recorder
  docstring,不新建竞争文档。

### 3.2 GitHub Deployments Status API 语义核实(docs.github.com,REST 2022-11-28)

- 端点:`GET /repos/{owner}/{repo}/deployments/{deployment_id}/statuses`;
- 合法 state 枚举恰七个:`error / failure / inactive / in_progress / queued /
  pending / success`;
- **列表排序官方无文档保证**(文档只说 "GitHub tracks the most recent status
  for each deployment and uses it to display the deployment's current state")
  → 实现按 status **id 最大**选取 effective/latest(id 单调递增),
  免受排序假设影响;id 缺失退化 created_at 字典序;
- 空 status 列表(部署存在但从未被确认)与 404 的行为文档未显式定义
  → 两者都按 fail-closed 处理(空列表 = 无状态 FAIL;已列记录的 statuses
  端点 404 = 证据源不一致 FAIL),绝不把"取不到状态"解释成"成功"。

## 4. 实现

### 4.1 跟进 ① — PRODUCTION DEPLOYMENT STATUS == success

- 采集层(`collect_facts`,仅 closure/audit):对权威记录(deployments[0])
  追加拉取 `/deployments/{id}/statuses?per_page=100`,结果与新字段
  `production_statuses` / `production_statuses_error` 进入 `ReleaseFacts`
  (facts-json 离线路径同步支持)。fail-closed 映射:非列表 → 畸形;
  404 → 记录在册而状态源缺失(源不一致);网络/鉴权/5xx → CollectionError
  语义的 `_error` 字段;权威记录本身非 dict 或缺 id → 显式 `_error`。
- 判定层:新增不变量 **`PRODUCTION DEPLOYMENT STATUS == success`**(closure/audit
  必发,fail 边界全覆盖):
  - 生产源不可用 → FAIL(不得当作无状态);
  - 无权威记录 → FAIL(状态无从核验);
  - 状态源不可用 → FAIL(不得当作无状态或成功);
  - 空状态史 → FAIL(部署存在但从未被确认);
  - 载荷畸形(无可解析 state)→ FAIL;
  - state ∈ {queued,in_progress,pending,failure,error,inactive} → FAIL;
  - 仅 state=success → PASS(注明 status=success 是已通过运行时身份核验的
    部署的**机器可读镜像**,写记录本身不制造生产事实)。
- 权威模型保持:sha 与 payload.git_sha 互证、PRODUCTION_SHA == RELEASE_SHA
  原语义不动;本不变量是**追加**门槛而非替代。

### 4.2 跟进 ② — RUNTIME_ACCEPTANCE_REPORT_PROVENANCE

新增 `resolve_report_artifact()` + 新不变量 **`RUNTIME_ACCEPTANCE_REPORT_PROVENANCE`**
(closure/audit 必发),fail-closed 矩阵:空值 / 绝对路径 / 词汇穿越(../)/
符号链接真实路径逃逸仓库边界(realpath 包含性)/ 指向不存在文件或目录 /
git 不可用(无法核验入库状态 → 不放行)/ 未被 git 跟踪 —— 全部 FAIL。
判定在 `evaluate(..., repo_root, runner)` 内做(可注入,离线测试用真实临时
git 仓库);CLI 新增 `--repo-root`(缺省 `.`,workflow checkout 场景即仓库根)。
manifest schema docstring 同步:report_path 注释升级为"仓库相对路径;须解析为
被 git 跟踪的真实文件"。
本任务**不创建** v1.4.0 manifest、不伪造任何报告。

### 4.3 跟进 ③ — 运行簿契约(DEPLOY → VERIFY → RECORD)

- `deploy/prod/update.sh` 头部新增「部署后证据记录(运行簿契约)」条款:
  顺序不可颠倒;仅在本脚本完整成功(含 [3/6] RELEASE.json 断言 + [5/6]
  /health 身份核验)后才允许运行 recorder;违反顺序写入的记录是伪证。
  **零逻辑改动**(diff 单 hunk,全部位于 `set -euo pipefail` 之前的注释区;
  `bash -n` 通过,fail-closed 行为原样)。
- `scripts/record_production_deployment.py`:docstring 新增三步运行簿契约
  (DEPLOY/VERIFY/RECORD)与边界声明 —— 本脚本是低层记录原语,无法远程核验
  顺序;status=success 只是镜像不是事实;单条记录不足以闭环。
  **零代码改动**(diff 单 hunk 全在模块 docstring 内;POST 体、退出码、
  用法不变)。
- 不做 update.sh 自动接线(recorder 调用内嵌进 update.sh 会改变生产部署
  失败语义与凭证面,超出本授权;契约以文档显式化 + 守卫侧 fail-closed 兜底)。

### 4.4 跟进 ④ — workflow 输入 shell 硬化

`release-integrity.yml` guard step:run: 块内 5 处 `${{ inputs.* }}` 全部移除;
输入经 step `env` 数据边界传入(`GUARD_INPUT_MODE / GUARD_INPUT_TAG /
GUARD_INPUT_EXPECTED_SHA`),shell 以 `"$VAR"` 普通环境变量消费,并补
`set -euo pipefail`。保持:workflow_call + workflow_dispatch(默认值不变,
publish/audit)、无 push 触发、`permissions: contents: read`、checkout
fetch-depth: 0、GH_TOKEN 透传、Summary step 原样。

## 5. 变更清单(对基线 6b9d7f7)

| 文件 | 变更 | 说明 |
| --- | --- | --- |
| `scripts/release_integrity_check.py` | M(+268/−29) | ①② 实现;docstring 不变量表/schema 更新;`--repo-root` |
| `tests/scripts/test_release_integrity_check.py` | M(+402) | 52→92 用例(40 新增,基线扩展,零既有用例删除) |
| `.github/workflows/release-integrity.yml` | M(+17/−12 上下文内) | ④ env 边界 |
| `deploy/prod/update.sh` | M(+11,纯注释) | ③ 运行簿条款 |
| `scripts/record_production_deployment.py` | M(+15,纯 docstring) | ③ 运行簿契约 |

合计 5 文件,684 insertions / 29 deletions(经 `git status --porcelain` 审计,
无任何范围外文件)。recorder 与 update.sh 的"纯文档"属性经 diff hunk 位置
逐行核验(各仅一个 hunk,分别完全落在 docstring 区 / 头部注释区)。

## 6. 测试矩阵(全部离线确定性;`tests/scripts/` 全量 253 passed, 3 skipped)

- `tests/scripts/test_release_integrity_check.py`:**92 passed**(既有 52 全部
  保留;新增 40):

| 组 | 覆盖 |
| --- | --- |
| TestProductionStatusAuthority(15) | success PASS;queued/in_progress/pending/failure/error/inactive 六态全 FAIL;无状态 FAIL;状态源不可用 ≠ 缺失/成功;载荷畸形(4 形态)FAIL;最新状态覆盖旧 success;**id 序与列表顺序无关**(双序断言);success 后 inactive 不放行 |
| TestReportProvenance(11) | 入库报告 PASS;manifest 缺失/非法 FAIL;文件不存在 / 绝对路径 / `../` 穿越 / 深层穿越 / 符号链接逃逸 / 未跟踪 / 目录 / git 不可用 fail-closed 全 FAIL |
| TestCollection 增 5 | closure 拉取权威记录 status 史;statuses 404 = 源不一致;5xx fail-closed;非列表载荷畸形;权威记录非对象畸形 |
| TestWorkflowContract 增 4 | permissions 保持 contents:read;`${{ inputs.` 不在 run: 块;GUARD_INPUT_* 三映射在 env;run 以 `"$VAR"` 消费 + set -euo pipefail |
| TestRunbookContract 增 3 | recorder docstring 顺序契约在案;recorder 不探测 /health、subprocess 仅 git rev-parse 一处;update.sh 头部绑定记录顺序 |
| CLI 增 1 | closure 端到端全绿(status=success + manifest + 真实 git 仓库入库报告 → exit 0 / verdict PASS) |
| 既有语义回归 | 生产 SHA 背离 / payload 自相矛盾 / 缺记录 fail-closed / publish 不查生产 等全部保持 |

- `tests/scripts/test_release_tooling.py`:21 passed(无回归)。
- 语法检查:`bash -n update.sh` 通过;两脚本 `py_compile` 通过。

## 7. 真实 v1.4.0 只读冒烟(候选工作树,带凭据只读)

- `--mode release-publish --tag v1.4.0 --expected-sha 41278f0…`:
  **PASS(6 invariants, 0 failures),exit 0** —— 发布面六项不受硬化影响。
- `--mode production-closure --tag v1.4.0`:
  **FAIL(10 invariants, 4 failures),exit 1** —— 失败恰为生命周期真相:
  PRODUCTION_SHA(无任何生产记录)、PRODUCTION DEPLOYMENT STATUS(无权威记录)、
  RUNTIME_ACCEPTANCE_SHA(manifest 不存在)、RUNTIME_ACCEPTANCE_REPORT_PROVENANCE
  (无 manifest 即无报告来源)。
  **硬化未给 v1.4.0 制造任何 PASS;生产闭环依旧未确立。**

## 8. 范围审计

- 触碰文件 = 预期边界五文件;backend / widget / admin / 检索 / LLM /
  鉴权 / Docker / 镜像语义 / 版本号 / tag / Release / 生产基础设施:零改动。
- `deploy/prod/update.sh` 仅注释扩展(无自动化接线 —— 若接线将实质改变生产
  部署行为与失败语义,按任务条款不做,契约以文档显式化,边界已在 §4.3 论证)。
- 未实现第五项需求;未引入 `main HEAD == release SHA` 不变量
  (发布身份仍逐版本锚定:TAG_SHA == RELEASE_SHA == IMAGE RELEASE.json SHA ==
  PRODUCTION_SHA == RUNTIME_ACCEPTANCE_SHA;main 可独立前进)。

## 9. 剩余限制(诚实边界)

1. recorder 的顺序契约是**运行簿文档 + 操作员纪律**,工具无法远程证明
   update.sh 确实成功后才记录(守卫侧以 SHA 互证 + status 双门槛兜底);
2. status=success 的写入权限等同于 Deployments write —— 记录源可信度依赖
   token 治理,守卫无法鉴别"未经部署的成功状态";
3. statuses 列表以 `?per_page=100` 为窗口(状态史超百条的极端场景未特殊处理,
   effective 判定取窗口内 id 最大者);
4. `git ls-files` 核验的是工作树索引/HEAD 的跟踪状态 —— 与 workflow checkout
   场景(= 已提交内容)一致;对"已 staged 未提交"的边缘差异按未跟踪处理
   (fail-closed 方向)。

以上均为治理接受后的运维边界,不影响四项跟进的机器可核验性。

## 10. 生命周期状态(执行后,与执行前一致)

v1.4.0 RELEASE CREATED · PRODUCTION NOT DEPLOYED · RUNTIME ACCEPTANCE PENDING ·
PRODUCTION CLOSURE NOT ESTABLISHED(守卫硬化后依然 FAIL = 预期正确)。
下一门:Role A 独立审查;其后方为 production-closure 强制执行与生产部署授权。
