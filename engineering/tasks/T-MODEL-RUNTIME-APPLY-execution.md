# T-MODEL-RUNTIME-APPLY 执行报告

- **任务**:Admin「模型配置 → 模型运行」设备策略显式 Apply(保存即生效,无需重启)
- **优先级**:P0 HOTFIX
- **基线**:762eae3(= main = origin/main = v1.1.0 生产 SHA)
- **候选提交**:`d997782bc9d4e926d62f26fbe7d29d81395582f9` @ `origin/worktree-exec/model-runtime-apply-20260905`(已推送,远程核验一致)
- **worktree**:`/Users/harryhua/Documents/GitHub/ask-ai/.worktrees/model-runtime-apply`
- **执行日期**:2026-09-05
- **最终状态**:**CANDIDATE READY**(待 Planner 验收;本报告不自称 FINAL PASS)
- **PRODUCTION_MUTATIONS**:无(生产零触碰;无 tag、无 main 推送)

---

## 1. 契约映射(冻结产品条款 → 落地)

| # | 冻结条款 | 落地 |
|---|---|---|
| 1 | 设备策略可通过明确「应用更改」在当前生命周期内生效 | `POST /api/admin/model-runtime/apply` + `ModelRuntimeManager.apply()`;UI「应用更改」按钮(有待生效配置时出现) |
| 2 | Save Configured 与 Apply Effective 语义可区分 | PUT policies/gpu-budget 仍只持久化(不触碰 Effective);UI 保存 toast=「待『应用更改』生效」,Apply 按钮独立存在与触发 |
| 3 | Apply 成功后 GET 返回 Configured==Effective、restart_required=false | 单测 `test_apply_budget_only_*`/`test_apply_gpu_to_cpu_*`、API `test_apply_endpoint_success_*` 断言;`runtime_plan.restart_required` 同步归零 |
| 4 | Apply 失败保留旧 Effective Runtime 完整可用 | fail-before-mutate:候选装配为纯构造(零 self 突变),提交是最后一步;三拒绝面单测+API 测试+live 实证(409 后真实 query 照常 200) |
| 5 | 安全一致的 runtime transition,无半应用状态 | 锁内整组字段赋值(`_commit`);读侧经 `self._lock` 一次捕获(实例+设备事实)后在锁外执行;在飞批次持有自身引用用完旧实例 |
| 6 | 不改 GPU capacity/residency/sharing/fail-closed/sync fallback 契约 | `compute_residency_plan`、`_GpuGate`(B2/R2-2)、R2-1 fail-closed、#14 单向回退零改动;现有 38 个 runtime 测试全部原样通过 |
| 7 | 不经 Docker/K8s/进程重启 | 纯进程内换装;模型装载走 `asyncio.to_thread`(不阻塞事件循环,规避生产 504 模式) |
| 8 | 不扩展到 Provider/模型替换/Admin redesign | apply 只重读 model_runtime_policies + gpu_budget;UI 仅本 Tab 最小增量 |

## 2. 设计(HOW)

### 2.1 候选装配 + 原子换装(契约调查项的明确回答)

**需要 candidate-build + atomic swap,已实现。** `_build` 拆为:

- `_assemble(policies, budget_mode, manual_budget_mb) -> _RuntimeAssembly`:纯构造候选(实例、states、plan、built_from),失败即抛、零 `self` 突变 → 旧运行时结构上不可能被破坏(契约#4);
- `_commit(asm, ...)`:锁内整组赋值 + `generation += 1`,是唯一突变点。

### 2.2 差量重建(同卡双驻留规避)

Apply 对比当前装配的输入选择(`_built_from`,新增字段,记录上次提交的 configured 集合),**只重建设备选择变化的 workload**:

- query 重建条件:选择变化 或 实例缺失(退化装配);
- sync 重建条件:选择变化 / 共享关系变化 / 历史一次性回退待重置(`_sync_cpu_embedder` 非空);
- reranker 重建条件:选择变化 或 计划模式变化(transient↔dual 需换代理形态)或 实例缺失;
- 共享模式新增:`new_share = S_q.key() == S_s.key()`;共享成立时 sync 复用 query 实例(重建与否皆然)。

因此「仅 sync 移动」不会在同卡上短暂装配第二个 query 实例;「无变化的幂等 Apply」零模型构造(live 实测 0.30s)。

### 2.3 回退重置语义(Apply=重新物化,与重启一致)

历史一次性 sync GPU→CPU 回退属于旧装配的一次性反应。Apply 时:共享模式下被 OOM 过的正是共享实例 → 连带重建 query(全新共享运行时);非共享模式重建 sync 独立实例;`_sync_cpu_embedder` 指针在 `_commit` 清零。#14 回退机制本身不变(新装配内仍单向、仍显式标注)。

### 2.4 UNSAFE 候选先拒(R2-1 谱系)

候选计划为 `gpu_insufficient` → `ApplyRejectedError("capacity_unsafe")`,**先拒装配、不先全量硬载**(与启动路径 B4 一致,但对 Apply 是硬失败——契约明确 capacity unsafe ⇒ Apply FAIL)。undecided(预算不可读)沿用启动语义(维持装配,模型加载失败仍会被 2.5 拦截)。

### 2.5 三拒绝面(`ApplyRejectedError.code`)

| code | 触发 | 指引内容 |
|---|---|---|
| `capacity_unsafe` | 候选计划 gpu_insufficient | 提高预算/释放显存/部分负载改 CPU |
| `build_failed` | 配置 GPU 不存在/不可见;模型加载失败 | 核对设备策略与 GPU 可见性 |
| `not_loaded` | 启动装配未完成 | 稍后再试 |

所有 detail 含「当前运行配置未改变,线上查询不受影响」。API 映射 409(HTTPException detail=完整中文串,Admin `formatApiDetail` 直接可读)。

### 2.6 并发与热路径

- `embed()`/`rerank()`/proxy `dimension`:锁内一次捕获 `(instance, on_gpu 事实)`,锁外执行。换装后在飞批次自然用完旧实例(持有自身引用),新批次即用新装配(单测+live 证据);
- `_fallback_sync_to_cpu` 状态突变移入锁内(与 `_commit` 互斥);
- 多次 Apply 由 `_apply_lock` 串行化;`_GpuGate` 跨装配复用(B2 语义不因换装重置);
- 换装后 `_release_superseded_models()`:best-effort `gc.collect()` + `torch.cuda.empty_cache()`(加速显存归还;正确性不依赖)。

### 2.7 generation(装配纪元)

`runtime_plan.generation`:启动 load=1,每次成功 Apply +1。用途:Admin/日志确认「应用更改确实落到了当前进程」(契约验收「Apply 后真实 Query 证明新 Effective Runtime 被使用」的可观测锚点)。附加字段,向后兼容(UI 类型声明 optional)。

## 3. 变更文件(全部在候选提交内)

| 文件 | 变更 |
|---|---|
| `backend/runtime/manager.py` | `_assemble`/`_commit` 重构、`apply()`/`_apply_policies`、`ApplyRejectedError`、`_RuntimeAssembly`、差量重建、热路径捕获读、generation、`_effective_budget_mb` 参数化、`_read_budget_setting` 纯读化 |
| `backend/api/admin/model_runtime.py` | `POST /model-runtime/apply`(editor+;409 失败语义)+ docstring |
| `admin/src/components/ModelRuntimeTab.tsx` | 「应用更改」按钮(processing/成功刷新/失败说明)、文案改「待应用生效」、`runtime_plan.generation` 类型 |
| `tests/runtime/test_manager.py` | +13 Apply 单测(§4.1) |
| `tests/api/admin/test_model_runtime.py` | +4 API 测试(§4.2) |
| `admin/tests/ModelRuntimeTab.test.tsx` | +3 新用例、2 处文案断言更新(§4.3) |

## 4. 验证证据(全部在候选提交 d997782 的树上执行)

### 4.1 runtime 单元矩阵(tests/runtime/ 51 全绿,其中 Apply 新增 13)

- CPU→GPU Apply PASS:`test_apply_cpu_to_gpu_rebuilds_query_and_serves`(新实例 device=cuda、真实 embed 打到新实例、generation+1)
- GPU→CPU Apply PASS:`test_apply_gpu_to_cpu_rebuilds_and_serves`(全 workload 换装、restart_required 全 false)
- 同 GPU 共享保真:`test_apply_reshares_single_instance_when_sync_returns_to_query_device`(共享重建、零新建);`test_apply_preserves_unchanged_query_instance_when_only_sync_moves`(未变实例复用,只 +1 构造)
- Reranker residency 保真:`test_apply_reranker_residency_follows_budget_apply_both_ways`(dual↔transient 双向切换、瞬态调用即卸载语义不变)
- 失败三面:`test_apply_capacity_unsafe_*`(旧实例 identity 不变、零候选构造、generation 不进、embed 照常)、`test_apply_missing_gpu_*`、`test_apply_model_load_failure_*`(旧 reranker 照常工作)
- 无部分状态:以上断言 states/plan/实例/identity 全或无
- 在飞并发安全:`test_apply_inflight_query_completes_on_old_instance_new_served_by_new`(脚本化阻塞批次在旧实例完整结束;新查询打到新装配)
- 回退重置:`test_apply_clears_stale_sync_fallback_and_rebuilds`
- 契约#3:`test_apply_budget_only_materializes_plan_and_zeroes_restart_required`
- 幂等:`test_apply_noop_rebuilds_nothing_but_bumps_generation`(零构造)

### 4.2 API(tests/api/admin/test_model_runtime.py 9/9 绿,其中 Apply 新增 4)

- `test_apply_endpoint_success_configured_equals_effective`:PUT 三策略→apply 200→restart_required 全 false、configured==effective、GET 同真相、generation 1→2→3(幂等)
- `test_apply_endpoint_capacity_unsafe_409_previous_runtime_intact`:DB 直写 GPU 策略+manual 3800 → 409 + detail 含「当前运行配置未改变」;GET 后 effective 仍 cpu、generation 未进
- `test_apply_endpoint_requires_editor_role`:viewer 403
- `test_apply_endpoint_not_loaded_409`:未装配 manager → 409

### 4.3 Admin UI(vitest 277/277 全绿,tsc+build 绿)

- 新增:待生效→按钮出现并 POST /apply→成功刷新(徽标消失、计划行更新、按钮收起);processing「应用中…」+禁用;失败→「应用失败,当前运行配置未改变」+可操作错误可见且待生效状态保留
- 更新:保存提示「待『应用更改』生效」、计划行「点击『应用更改』后变为:…」(Save/Apply 语义区分)

### 4.4 回归

- 后端离线全量(隔离库 ask_ai_test_apply,用后已 DROP):**1682 passed / 4 skipped / 0 failed**(49s;含全部既有 runtime/容量/R2-1/R2-2/#14 用例零回归)
- admin:`vitest 277 passed`;`tsc -b` + `npm run build` 绿(worktree 需补装 widget 依赖,属环境非代码)
- lint:ruff 全绿、black --check 全绿(改动文件)
- 环境注记:初次全量出现的 4 embedder ERROR + lifespan smoke FAIL 为 worktree 缺 `models` 软链所致(测试首跑生成实体空目录吞掉软链位),重建软链后 30/30 过,与基线 worktree(v11-gpu-runtime @ 762eae3)对照一致——非代码回归。

## 5. Live 真栈实证(worktree 代码,本地 8033 端口,专用库 ask_ai_apply_live 用后已 DROP)

栈:真实 BGE-m3 / bge-reranker-v2-m3(HF_HUB_OFFLINE=1,models 缓存)、EMBEDDER_DEVICE=cpu、真实 weaviate(localhost:8080)、git_sha=762eae3 树+d997782 代码。

```
[1-startup]     plan=cpu_only gen=1 restart_required=False(三 workload 全 cpu)
[1-startup]     REAL query embed -> HTTP 200 dim=1024 device=cpu vectors=1   ← 真实 BGE-m3
[2-apply-noop]  POST /model-runtime/apply -> HTTP 200 in 0.30s  gen=2
[2-apply-noop]  REAL query embed -> HTTP 200 dim=1024 device=cpu vectors=1   ← 换装后真实查询连续
[3-pending]     DB 直写不可满足 GPU 策略(uuid=…00ff)
[3-apply-fail]  POST apply -> HTTP 409
                detail=应用更改失败:候选运行时装配出错(配置的 GPU 不存在或不可见:
                uuid=GPU-00000000-…-0000000000ff(fail-closed;请核对 model_runtime_policies
                或恢复该设备))。当前运行配置未改变,线上查询不受影响;请核对设备策略与 GPU…
[3-after-fail]  query effective=cpu status=loaded gen=2(未推进=未提交)
[3-after-fail]  REAL query embed -> HTTP 200 dim=1024 device=cpu vectors=1   ← 旧运行时完整可用
[4-cleanup]     策略行清除;后端停止;live 库 DROP
```

对应日志 `/tmp/apply-live-backend.log` 含两次「候选装配/已提交」记录与端点 200/409 轨迹。

### 5.1 诚实边界

1. **GPU 设备转换的成功路径(CPU→GPU / GPU→CPU)在本机无法用真实 CUDA 演示**(Mac 无 NVIDIA GPU):由确定性 fake-factory 单测覆盖(本仓 GPU 测试的标准做法);live 栈额外证明「cuda 配置+无 CUDA」场景被 fail-closed 语义正确拦截(candidate build_failed / 启动装配如实 undecided),生产 T4 的真实 GPU 转换验证留给部署门(本契约无生产授权,未触碰)。
2. live 实证中的 pending 由 DB 直写制造(本地无真实 GPU 可经 API 保存成功);产品正路「API 保存→pending 徽标→Apply」由 API/UI 测试完整覆盖。
3. `POST /api/internal/embeddings` 走 sync workload 通道(既有设计);「真实 Query」证据 = 真实模型、真实运行时、真实 HTTP 路径。

## 6. 遗留与建议(非阻塞)

- 部署到生产时,`backend` 与镜像无需迁移(零 schema 变更);建议 Planner 安排 T4 部署门做真实 GPU 转换 Apply 验收(可与下次发布窗口合并);
- `runtime_plan.generation` 已暴露,Admin UI 未展示(最小变更原则);如需可在后续迭代加「已应用版本」角标。

## 7. 最终执行状态

**CANDIDATE READY** —— 等待 Planner 验收。验收锚点:候选提交 `d997782`(origin/worktree-exec/model-runtime-apply-20260905),本报告所在 docs 仓 commit 即持久化记录。

---

## REV1 — Planner PARTIAL 阻断修复:Save/Apply 配置竞态守卫(2026-09-05)

- **Planner 判定**:PARTIAL(BLOCKER:Save/Apply configuration race)
- **修复提交**:`9b9435fc9dfbbc0734e8f519e707f3e3f320281f` @ 同分支(已推送,远程核验一致)
- **基线不变**:架构方向(候选装配+原子换装)零改动,仅新增配置事务边界。

### 7.1 根因

`_apply_lock` 只串行化 Apply-vs-Apply,未建立与 `save_policy`/`save_gpu_budget` 的配置事务边界:
save 在「Apply 读快照之后、_commit 之前」落地时,DB 已是 B(GPU)且内存 configured 已被 save 更新,
但旧快照候选(A)在 `_commit` 整组赋值 `states.configured/_built_from/预算` 时把内存拉回 A ——
出现「DB=GPU / 内存 Configured=CPU / effective=CPU」,较新持久保存被静默隐藏至重启。

### 7.2 选定的并发/顺序契约(配置纪元)

- **持久 Configured 是唯一权威,任何提交于 Apply 快照之后的保存不得被覆盖或隐藏。**
- `save_policy` / `save_gpu_budget`:DB 提交成功后,同锁(`self._lock`)原子推进
  `_config_version` + 内存 configured/预算(新增 `_commit_saved_config`/`_commit_saved_budget`)。
  ⇒ 纪元不变 ⇔ 快照后无新保存落地。
- `apply()`:DB 读后同锁捕获 `config_version_at_read`;`_apply_policies` 透传;
  `_commit(..., expected_config_version=...)` 在提交锁内校验,纪元已变 →
  `ApplyRejectedError("config_changed")` **整体拒决**(detail:「应用更改期间检测到新的配置保存…
  当前运行配置未改变…请重新点击『应用更改』以应用最新保存的配置」)。
- 拒决即满足契约:持久真相保持权威且 pending 可见(configured=新值 / effective=旧值 /
  restart_required=true),管理员重试一次即应用最新配置(deterministic,无合并复杂度)。
- 约束核验:不阻塞普通 Save(锁微秒级);不阻塞 Query/Sync 热路径(捕获读未动);
  不弱化候选装配+原子换装(拒决发生在提交点,纯新增前置校验);不部分应用;
  Apply-vs-Apply 仍由 `_apply_lock` 串行化;无进程/容器重启。

### 7.3 代码变更(d997782 → 9b9435f)

- `backend/runtime/manager.py`:`_config_version` 字段;`_commit_saved_config`/`_commit_saved_budget`;
  `save_policy`/`save_gpu_budget` 改用上述助手(DB 提交后同锁推进);`apply()` 读快照后捕获纪元并透传;
  `_apply_policies` 新参 `config_version_at_read`(缺省 None=不校验,启动 `_build` 路径不变);
  `_commit` 新增 `expected_config_version` 守卫(校验+提交同一锁内,校验通过后不可能被 save 插入)。
- `backend/api/admin/model_runtime.py`:非阻塞清理——`WorkloadPolicyUpdate` docstring
  「重启生效」→「『应用更改』或重启生效」。

### 7.4 确定性竞态回归测试(Events/钩子/run_coroutine_threadsafe,零 sleep)

| 测试 | 编排 | 断言 |
|---|---|---|
| `test_save_landing_mid_apply_aborts_and_keeps_newest_config_pending`(runtime) | 注入 `_assemble` 钩子,候选装配中途以 save 同款内存侧路径落地 Save B(GPU) | 409 类拒决 code=config_changed;configured=GPU/effective=CPU/pending=true;generation 不进;旧实例照常服务 |
| `test_budget_save_landing_mid_apply_aborts_and_keeps_pending`(runtime) | 同钩子,中途 `_commit_saved_budget(manual,4096)` | 拒决;预算保持 4096;pending_mode=transient 可见;executed 计划未被旧快照提交 |
| `test_apply_retry_after_config_changed_applies_newest_config`(runtime) | 拒决后以最新持久配置重放 | 成功;configured==effective;restart_required 全 false |
| `test_apply_endpoint_race_with_concurrent_save_409_truth_preserved`(API) | 全 CPU 干净态 → 注入钩子 + `run_coroutine_threadsafe` 把**真实** `save_policy`(DB 提交+纪元推进)调度到事件循环,在 apply 中途完成(fake GPU 注入 discover 使 gpu 策略可经 API 保存) | 409 + detail 含「新的配置保存/当前运行配置未改变」;configured=GPU/effective=CPU/pending=true/generation 未进;DB 行=gpu(真相一致) |

### 7.5 回归结果(9b9435f 树)

- runtime:`54 passed`(含 REV1 新增 3);Admin model-runtime API:`10 passed`(含端到端竞态)
- 后端离线全量(隔离库 ask_ai_test_apply):**1687 passed / 0 failed**(46.6s)
- admin:`vitest` 全绿(277)、`tsc`+`npm run build` 绿(UI 零改动)
- ruff/black(改动文件)全绿

### 7.6 REV1 后验收锚点

**CANDIDATE READY(REV1)** —— 等待 Planner 复审。候选 tip = `9b9435fc9dfbbc0734e8f519e707f3e3f320281f`
(@ origin/worktree-exec/model-runtime-apply-20260905;前序 d997782 为同分支历史提交)。


---

## REV2 — 残余竞态窗口修复:纪元捕获先于 DB 读(2026-09-05)

- **Planner 判定**:REV1 方向接受(配置纪元守卫正确);残余窗口一处。
- **修复提交**:`073f26236c08531212f6d5b12b8b8173f0557c79` @ 同分支(已推送,远程核验一致)。

### 8.1 根因

REV1 的 `apply()` 在**读库之后**捕获 `_config_version`。若 Save B 在「DB 读完成、
版本捕获」之间落地(commit→bump),Apply 会捕获到 B 的新纪元却仍持有旧快照 A
→ 提交校验误放行 → A 覆盖/隐藏 B。

### 8.2 修复(顺序契约定稿)

```
capture V(self._lock 内,绝不跨越异步 DB I/O)
→ read DB policies/budget(异步,锁外)
→ assemble(线程,零 self 突变)
→ commit only if current version == V(_lock 内校验+提交原子)
```

捕获严格先于读 ⇒ 任何在捕获后落地(commit→bump)的保存必被提交校验检出;
唯一放行路径是「捕获到提交全程纪元未变」,即窗口内零配置保存 ⇒ 持久权威
不可能被旧快照覆盖。`self._lock` 仅微秒级持有,不跨越任何 await。

### 8.3 代码变更(9b9435f → 073f262)

- `backend/runtime/manager.py`:`apply()` 捕获块移至 DB 读之前 + docstring 更新;
  其余(save 侧、_commit 守卫、装配、热路径、UX)零改动。

### 8.4 确定性边界回归(零 sleep)

| 测试 | 编排 | 断言 |
|---|---|---|
| `test_save_landing_between_version_capture_and_db_read_rejects`(runtime) | 钩 `_read_policies`:捕获后、快照完成前 Save B(GPU)完整落地,返回陈旧快照 A(等价「读先于 B 提交」) | config_changed 拒决;configured=GPU/effective=CPU/pending=true;generation 不进 |
| `test_budget_save_landing_between_capture_and_budget_read_rejects`(runtime) | 钩 `_read_budget_setting`:捕获后、预算读前 Save B(manual 4096)落地,返回陈旧 auto | 拒决;预算保持 4096;pending_mode=transient 可见;executed dual 未被旧快照提交 |
| `test_apply_via_session_boundary_without_save_still_applies`(runtime) | 同 fake-session 通道、无保存 | 正常应用(restart_required 全 false、generation 2、换装后 embed 可执行)——守卫不误伤 |
| `test_apply_endpoint_save_before_db_snapshot_409_truth_preserved`(API) | 端到端:钩 `_read_policies` 内 await **真实** save_policy(全 CPU 干净态上保存 query→GPU),返回陈旧快照 | 409 +「新的配置保存/当前运行配置未改变」;configured=GPU/effective=CPU/pending=true/generation 未进;DB 行=gpu |

### 8.5 回归结果(073f262 树)

- runtime `57 passed`;Admin model-runtime API `11 passed`(含 REV2 边界)
- 后端离线全量(隔离库):**1690 passed / 0 failed**(46.1s)
- admin vitest 277 全绿、tsc+build 绿(UI 零改动);ruff/black 绿

### 8.6 REV2 后验收锚点

**CANDIDATE READY(REV2)** —— 等待 Planner 复审。候选 tip =
`073f26236c08531212f6d5b12b8b8173f0557c79`(@ origin/worktree-exec/model-runtime-apply-20260905;
血统 762eae3 → d997782 → 9b9435f → 073f262)。