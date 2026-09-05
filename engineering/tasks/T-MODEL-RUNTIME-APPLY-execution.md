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
