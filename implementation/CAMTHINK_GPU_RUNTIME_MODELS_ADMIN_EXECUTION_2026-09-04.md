# Hardware-Aware Model Runtime + Models Admin 重构 — 执行报告

- **日期**: 2026-09-04
- **执行角色**: Executor(独立 worktree;窗口协议 v2.0)
- **基线**: b7a016d(v1.1 FINAL_COMMIT;生产运行中 sha-b7a016d)
- **权威上游**: 硬件感知模型运行时 Discovery(docs 34b6651,D1-D11/E1-E10)
- **候选分支**: `v1.1/gpu-runtime-models-admin`
- **FINAL_COMMIT**: **35785a4**(已推 origin,候选=单提交于 b7a016d 之上)
- **STATUS**: **CANDIDATE READY**(未自评 FINAL PASS;Planner 拥有验收权)
- **PRODUCTION_MUTATIONS**: **NONE**(生产只读零触碰;无 tag/release/issue 关闭)

---

## 1. 交付概述

按冻结执行契约实现「硬件感知模型运行时」并重构 Models Admin。运行时语义从
「进程各自为政装载模型」改为 **MODEL × WORKLOAD × DEVICE** 三元调度:

| 维度 | 内容 |
|---|---|
| WORKLOAD | `query_embedding` / `sync_embedding` / `query_reranker`(冻结词表) |
| DEVICE | GPU(stable UUID + CUDA index)/ CPU(型号),拒绝裸 `cuda:0` 面向用户 |
| 单一驻留不变量 | 同模型+同设备 → query/sync embedding 至多 **一个** 活跃运行时实例 |
| 在线优先 | sync GPU 嵌入经信号量有界(并发=1);查询路径零排队语义不变 |
| Configured ≠ Effective | Admin 保存=Configured(持久),重启落地=Effective;UI 全程如实双示 |
| 容量真相 | auto(硬件实况推导)/ manual(规划预算,≤硬件实况封顶,不硬编码 4GB) |
| #14 保真 | GPU→CPU **单向**回退服务端化(仅 sync workload);查询无自动回退不变 |

结构性收益(对照 Discovery E1-E10):sync 不再每源子进程自载 BGE 副本;
backend 单一驻留权威承担 query+sync 嵌入;T4 生产 ~4GB ASK-AI 预算场景下
消除瞬态第二副本,§34 生产容量验收(v1.1.0 前置)由此解锁路径。

## 2. 实现清单(模块 → 文件)

### 2.1 后端 runtime 核心(新增 `backend/runtime/`)

- `hardware.py`:硬件发现。`discover_gpus()` = torch props(**原生 stable UUID**
  + index);`discover_cpu()`(/proc/cpuinfo 型号 + 逻辑核数;不可读→降级);
  `read_gpu_memory(uuid|None)` = nvidia-smi 结构化 CSV 查询(UUID 身份匹配;
  **uuid=None 读默认卡**;任何失败→None,绝不臆造数值)。只读观测,零 GPU 计算进程。
- `manager.py`:`ModelRuntimeManager` 单一驻留权威:
  - `load()` 读 `model_runtime_policies` / `model_runtime_settings`;缺省=
    EMBEDDER_DEVICE 引导默认(与 v1.1 前行为一致);
  - `_build()`:query 实例**始终构造**;同 key(kind+uuid,含双 CPU)→ sync 复用
    同一实例(`shared=True`);不同→独立实例;reranker 按自身策略独立构造;
  - UUID fail-closed:配置的 uuid 不在发现集 → 启动即 RuntimeError(拒绝静默 CPU);
  - `embed(workload, texts)`:sync 路径 `Semaphore(1)` 有界;`_embed_sync` 用
    `classify_cuda_failure` 三分类(cuda_init_failure/cuda_oom/cuda_runtime_error)
    → **单向** lazy CPU 实例 → 重试;后续批次继续 CPU;查询实例不受影响;
  - `rerank()`:无回退(契约:GPU 默认+CPU 可选,异常如实上抛);
  - `capacity()`:auto 预算=当前空闲+ASK-AI 驻留(torch reserved/allocated);
    manual=min(手动值, 空闲+驻留)(Effective ≤ 硬件实况);分级
    `HEALTHY`(预算≥驻留+查询峰值)/`CAPACITY_LIMITED`/`UNSAFE`(空闲<512MB)/
    `unknown`(观测通道不可用,如实);`QUERY_PEAK_RESERVE_MB=512`(Discovery
    实测查询峰值 490MiB,**代码零处硬编码 4GB**);
  - `snapshot()`:devices + 3 policies(configured/effective/status/shared/
    restart_required/fallback 事实)+ shared_embedding_runtime + capacity;
  - `save_policy()`:uuid ∈ 发现集校验(fail-closed)+ upsert;`save_gpu_budget()`
    upsert `gpu_budget` 行(auto/manual + manual_budget_mb)。
- `internal_auth.py`:内部令牌单一权威 = HMAC-SHA256(jwt_secret, `internal-api:v1`);
  常数时间校验;**零新配置**(两侧同 .env 的 JWT_SECRET 派生)。

### 2.2 内部嵌入端点(新增 `backend/api/internal_embeddings.py`)

`POST /api/internal/embeddings`(X-Internal-Token):
- 401 无/错令牌;503 runtime 未就绪;
- 有界:批 > EMBEDDER_BATCH_SIZE → 422;单文本 > EMBEDDER_MAX_LENGTH → 413;
  **无无界队列**(嵌入线程池执行,并发受 Manager 信号量约束);
- 响应如实:`{vectors, dimension, execution_device, fallback_reason, fallback_detail}`。

### 2.3 sync 侧消费(新增 `backend/embedder/remote.py`;改 `scripts/sync.py`)

- `RemoteSyncEmbedder(SyncEmbedderHandle)`:**isinstance 遥测契约保持**
  (activity_snapshot/has_activity_since/cpu_counters_since/telemetry_execution_device
  全继承可用,sync.py:887 检查零改动);
- 服务端真相镜像:execution_device=cpu **且服务端给出 fallback_reason** 才记
  `gpu_to_cpu` + cpu_batches/cpu_docs;**原生 CPU 常驻如实记 `cpu`,绝不臆造
  cuda_oom**(执行中发现并修复的缺陷,见 §5.2);
- `scripts/sync.build_sync_embedder` 默认返回 remote 句柄;`ASKAI_SYNC_EMBEDDER=local`
  保留进程内工厂(离线测试逃生口);模型装载代码路径不再被 sync 进程触达。

### 2.4 Admin API(新增 `backend/api/admin/model_runtime.py`)

- `GET /api/admin/model-runtime`(Viewer+):snapshot 真相面;
- `PUT /api/admin/model-runtime/policies/{workload}`(Editor):未知 workload 404、
  校验失败 422、未知 uuid fail-closed 422;
- `PUT /api/admin/model-runtime/gpu-budget`(Editor):mode 422 校验。

### 2.5 Admin 前端(改 `LLMProviders.tsx`;新增 `ModelRuntimeTab.tsx`)

- 侧边栏仍为「模型配置」;页内双 Tab `[模型流水线] [模型运行]`;
- **Tab1 重构**:「检索模型」区(embedding/reranker 卡:模型名、职责、
  **运行设备硬件标签**(如 `Tesla T4 · GPU 0`/`CPU`),无裸 cuda;深链按钮跳
  「模型运行」)+「LLM 流水线」区(阶段卡去冗余序号,流水线次序移入区副标题);
  头部动作分组 fieldset「连接管理」(供应商凭证/端点授权 ghost)+ 独立主按钮
  「应用变更」;
- **Tab2 新增**:可用执行设备(GPU/CPU 卡)、模型运行策略(3 workload 卡:
  配置设备/生效设备/状态 testid 齐备;双嵌入卡「共享模型运行实例」徽标;
  回退徽标/待重启徽标;设备选择+保存 Editor-only)、GPU 运行容量
  (自动管理(推荐)/手动上限+GB 输入;「规划预算不得超硬件实况」明示)、
  容量与建议(状态+业务建议+只读事实含**外部占用(非 ASK-AI)**)。

### 2.6 数据模型与迁移

- `ModelRuntimePolicy`(workload PK / model_name / device_kind / gpu_uuid)+
  `ModelRuntimeSetting`(key PK / mode / manual_budget_mb);
- `scripts/migrate_add_model_runtime_policy.py`:纯 `CREATE TABLE IF NOT EXISTS`×2,
  幂等;**缺省行=引导默认,部署本迁移不改变现有模型语义**。

### 2.7 既有文件改动(最小面)

- `backend/main.py`:lifespan 改经 ModelRuntimeManager 构造
  (`app.state.model_runtime`),include 内部路由(prefix="/api");
- `backend/api/admin/llm_providers.py`:`/local-models` 附 device_label
  (取自 manager.states effective 设备);
- `backend/config.py`:`internal_api_base_url`(默认 http://backend:8000);
- `backend/db/models.py`:两新表定义。

## 3. 验证证据(全绿)

### 3.1 测试套件

| 套件 | 结果 |
|---|---|
| 后端全量离线回归 | **1645 passed / 6 skipped / 0 failed**(43-45s,两轮) |
| 聚焦 runtime+内部端点+Admin API+embedder | 73 passed(含共享单实例/独立实例/单向回退/查询无回退/容量三分级/manual 封顶/uuid fail-closed/snapshot restart_required/proxy) |
| tests/pipeline/test_sync.py | 16 passed(remote 默认路径下 run_sync 全场景) |
| Admin vitest | **271 passed / 0 failed**(45 文件;含 ModelRuntimeTab 9 用例) |
| ruff / black(改动面) | clean(基线既有格式零波及,spill 已回退) |

新增测试清单:`tests/runtime/`(manager+hardware)、`tests/embedder/test_remote.py`
(令牌同源/回退镜像/**原生 CPU 非回退**/gpu 路径/HTTP 503/计数不符)、
`tests/api/test_internal_embeddings.py`(401 矩阵/422/413/服务端回退遥测/app.state
保存还原)、`tests/api/admin/test_model_runtime.py`(真相面/持久化/404/422/budget/401)、
`admin/tests/ModelRuntimeTab.test.tsx`(9 用例)。

### 3.2 构建与迁移

- Admin 生产构建(tsc -b + vite):**绿**(chunk>500kB 警告=基线既有);
- 迁移幂等:ask_ai_test 连跑 ×2 成功;ask_ai_accept 应用后 asyncpg 复核两表在位。

### 3.3 本地验收栈(§33 非 CUDA 项实测;Mac 无 GPU,EMBEDDER_DEVICE=cpu)

隔离栈:独立 DB `ask_ai_accept`(用后已 DROP)+ worktree backend @127.0.0.1:8811:

| # | 探针 | 实测 |
|---|---|---|
| A | GET /health | 200(git_sha=b7a016d 树) |
| B1 | snapshot 真相面 | devices=[CPU 卡];3 policies configured/effective/status=loaded;shared_embedding_runtime=**True**;restart_required=False;capacity=unknown(无 nvidia-smi,**如实**) |
| B2 | 内部端点 401 矩阵 | 无令牌 401 / 错令牌 401 / 正确 HMAC 200 |
| B3 | 真实嵌入 | 2 文本 → 2×**1024 维** bge-m3 向量,execution_device=cpu,fallback_reason=**None**(原生 CPU 如实) |
| C | sync 侧句柄 | build_sync_embedder 默认=RemoteSyncEmbedder;经端点 2 批×1024 维;telemetry_execution_device=**cpu**(非 gpu_to_cpu);fallback_reason=None;cpu_batches=0(非回退不计) |
| D1 | 策略校验 | PUT cpu 同值 200;gpu 无 uuid 422;gpu 未知 uuid **fail-closed 422**;未知 workload 404 |
| D2 | 容量策略 | PUT manual 4096MB 200;bad mode 422;snapshot budget_mode=manual |
| D3 | 授权 | 无令牌 GET snapshot 401 |
| E | 重启生效/持久 | backend 重启后 budget_mode=manual(设置表跨重启)、policies=cpu(loaded)、shared=True;DB 行 asyncpg 直查实证 |

F/G/H(semaphore 有界/单向回退状态机/共享实例同一性)= 假工厂单元测试覆盖
(本机无 CUDA,真 GPU 行为归 §34 生产容量验收门)。

### 3.4 Admin UX 真浏览器验收(§35;构建产物由 8811 后端 /admin 托管)

Playwright 实测:登录 → 「模型配置」:
- 双 Tab `[模型流水线][模型运行]` 渲染正确,role=tab 语义;
- Tab1:「检索模型」向量模型/排序模型卡(模型名、职责、运行设备:`CPU · CPU`、
  深链按钮);「LLM 流水线」阶段卡+流水线次序副标题;头部「连接管理」分组
  (供应商凭证/端点授权)+独立「应用变更」;
- Tab2:可用执行设备(CPU 卡,16 逻辑核);模型运行策略 3 卡,**双嵌入卡
  共享徽标**,配置设备/生效设备/状态:运行中;说明文案(共享+重启生效语义);
  GPU 运行容量:手动上限 radio 选中显示 **4.0 GB**(与 API 写入一致);
  容量与建议:「容量未知」+只读事实(外部占用行)+如实建议;
- 控制台:仅 favicon 404(基线既有装饰性),零 JS 错误。

## 4. 契约符合性对照(要点)

| 契约条款 | 落地 |
|---|---|
| §6 单一驻留不变量 | manager 共享实例 + B2/C 实测 shared=True、单一 embedder 工厂调用 |
| §9 查询优先+有界 | sync Semaphore(1);查询路径零等待;无无界队列(端点 422/413 有界) |
| §10 reranker 契约 | GPU 默认+CPU 可选;无自动回退;`rerank()` 如实上抛 |
| §11 容量契约 | auto/manual;manual≤硬件实况封顶;**全库无 4GB 硬编码**(grep 证据) |
| §12 容量分级 | HEALTHY/LIMITED/UNSAFE/unknown 证据驱动(单元+unknown 实测) |
| §13-15 Configured≠Effective | 双示 + restart_required 徽标;重启落地实测(E) |
| §14 集成 | 单向回退服务端化;三分类原因码;gpu/cpu/gpu_to_cpu+cpu_batches/docs 遥测全保真 |
| §17-20 Tab1 重构 | 见 §2.5/§3.4 |
| §21-27 Tab2 | 见 §2.5/§3.4(testid 与徽标齐备) |
| §28-29 非目标 | 未做模型替换生命周期/自动调度器/语义变更/系统信息大页(范围审计佐证) |
| §30-31 边界/不变量 | 改动面=§2.7 清单;PII/授权/site 语义零触碰 |
| §36 兼容 | 缺省=EMBEDDER_DEVICE 引导默认;迁移纯加表;REV0 行为零变化 |

## 5. 执行中修复的缺陷(Planner 关注点)

1. **manager._build 查询实例缺失 bug(实现期自测发现)**:设备不同分支只构造
   sync override、query 实例从未构建 → `test_gpu_missing_...fail_closed` 与独立
   实例测试双暴露。已改为「query 实例始终构造」结构,测试全绿。
2. **原生 CPU 误报回退(设计评审发现,上线前拦截)**:RemoteSyncEmbedder 对任何
   cpu 响应臆造 `fallback_reason="cuda_oom"` → CPU-only 部署每次同步都被遥测误报
   gpu_to_cpu。已改为**仅当服务端给出 fallback_reason 才记回退**;新增回归测试
   `test_remote_embedder_native_cpu_is_not_reported_as_fallback`;误导日志
   (「已回退 CPU(reason=None)」)同步改为如实两种措辞。
3. **容量观测盲区**:capacity() 原 `gpu_uuid 为 None 则不读显存` → 已配置 GPU 但
   uuid 未解析时容量永远 unknown。已改为始终读(读默认卡),hardware.read_gpu_memory
   接受 uuid=None。
4. **internal_auth 签名漂移**:统一为 `(jwt_secret: str)`;remote.py 侧删除重复
   HMAC 实现,改 import 别名复用(单一派生权威,杜绝两侧漂移)。
5. **内部路由前缀**:include 时补 `prefix="/api"`,端点落位
   `/api/internal/embeddings`(与契约路径一致,测试据实断言)。

## 6. 偏差与说明

- **无契约偏差**。两点澄清:
  - `ASKAI_SYNC_EMBEDDER=local` 逃生口为离线测试保留(生产默认 remote);
  - Mac 验收机上 CPU 卡标签呈现 `CPU · CPU`(/proc/cpuinfo 不可读时的回退命名,
    Linux 生产呈真实型号)— 装饰性,非契约项。
- 测试环境修正:`tests/pipeline/test_sync.py` 的 settings mock 补
  jwt_secret/internal_api_base_url 真实字符串(remote 构造期派生令牌需要);
  黑色格式化对基线文件的 2 处 spill 已手工回退(最小 diff 纪律)。

## 7. 风险与移交 Planner

1. **§34 生产容量验收是 v1.1.0 的前置门**(契约原文):本候选在 T4 上需复测
   capacity 分级(auto 应呈 HEALTHY/LIMITED 真相而非 unknown)+ 真实 GPU 下
   uuid 选择/共享单实例/信号量有界/单向回退演练。
2. 内部端点安全边界=「持 JWT_SECRET 派生令牌者可批量嵌入」:仅内部网络可达
   (backend/sync-executor 同 compose 网络);不授予任何其他能力;令牌随
   JWT_SECRET 轮换,无独立生命周期(V1 设计取舍,如实声明)。
3. 部署次序:迁移(加表)→ backend → sync-executor/sync-cron(新镜像);
   update.sh 版本化流程适配由 Release 治理线负责。
4. `sync_executor_loop.py` SAWarning(生产既有,主 干 1d6f6b5 报告已列)不在
   本契约范围,未触碰。

## 8. §40 交付字段

| 字段 | 值 |
|---|---|
| STATUS | **CANDIDATE READY** |
| BASELINE | b7a016d |
| BRANCH | `v1.1/gpu-runtime-models-admin`(origin 已推) |
| FINAL_COMMIT | **35785a4** |
| REPORT_COMMIT | docs 仓本提交(仅本地,commit 即持久化) |
| PRODUCTION_MUTATIONS | **NONE** |
| TAGS/RELEASES | 无 |
| 迁移 | `migrate_add_model_runtime_policy.py`(幂等 ×2 实证;生产未执行) |
| 测试 | 后端 1645/6/0;admin 271/0;ruff/black/ruff-check clean |
| 构建 | admin tsc+vite 绿;backend 镜像走 CI(未本地构建) |
| 已知边界 | 真 GPU 行为待 §34;CPU 卡标签回退命名(装饰性);JWT_SECRET 共享派生 |
| 未授权动作 | 无 tag、无 release、无 issue 关闭、无 roadmap 变更、无生产触碰 |

**STOP。等待 Planner 验收。**

---

# REV1 — Planner 阻断项修复(2026-09-04 追加)

- **REV1_BASELINE**: 35785a4(REV0 候选)
- **REV1_COMMIT**: **1e58dbd**(@origin/v1.1/gpu-runtime-models-admin,基线上单提交)
- **STATUS**: **CANDIDATE READY**;PRODUCTION_MUTATIONS=**NONE**;无 tag/release

## R1. 阻断项矩阵(Planner 五项 → 逐项处置)

| 阻断项 | 处置 | 关键证据 |
|---|---|---|
| **B1 非共享查询嵌入器** | `_query_embedder` 属性**始终构造并持有**(原缺陷:非共享分支 query 实例构造后被丢弃,`_shared_embedder=None`);`_embedder_for(query)` 恒返回有效实例;sync 解析序=CPU 回退实例 → 独立 override → 共享查询实例 | 双混合设备回归**真执行**:query GPU+sync CPU → query embed() 返回 2×4 维向量且打中 GPU 实例;query CPU+sync GPU → query embed() 返回 1×4 维、sync 独立 GPU 实例亦执行 |
| **B2 查询优先/GPU 执行协调** | 新增 `_GpuGate`(条件变量闸):同卡嵌入批次**互斥**(并发峰恒 1);**严格在线优先**=查询等待中(`_query_waiting>0`)sync 新批次不得启动;在飞 sync 批次有界(≤EMBEDDER_BATCH_SIZE),查询至多等待一个在飞批次 → sync 无法垄断;CPU 执行不入闸(无显存峰,不过度串行化) | 确定性并发测试×3:①8 线程混合 query/sync → max 并发=1;②脚本化批次:在飞 s1+排队 s2+后到 q → 释放后顺序确定性为 s1→q→s2(`query_waiting==1` 轮询去 sleep 竞态);③CPU 双批 Barrier 汇合(未被闸串行化) |
| **B3 后端 GPU 容量** | `compute_residency_plan` 驻留计划器(纯函数):`dual_resident` / `reranker_transient` / `gpu_insufficient` / `undecided`(预算不可读→维持现状)/ `cpu_only` / `embedder_only`。**瞬态驻留**:重排权重驻留主机内存,仅重排步骤上卡,完成即卸载(BGEReranker 新增 `gpu_residency_state/materialize/offload`;FlagEmbedding compute 自带 .half()+.to(device),代理负责卸载+empty_cache);瞬态模式与嵌入共用 B2 闸(query 优先级)→ **瞬态显存峰构造性有界 = max(嵌入步 3412, 重排步 4050) = 4050 ≤ 4096** | 计划阶梯测试;瞬态构建断言:reranker 装配为瞬态代理、residency=transient、effective 仍 GPU(不静默降级)、启动时未上卡;rerank 调用→offload 计数=1/次、权重回主机内存 |
| **B4 预算必须驱动计划** | 预算解析(Auto=空闲+ASK-AI 驻留实况;Manual=min(手动,实况),规划上限非 cgroup)→ **先计划后构造**;`gpu_insufficient` ⇒ **GPU 侧零装配**(嵌入+重排全部按计划落 CPU,status=`cpu_by_capacity_plan` 显式标注,非静默)再如实报 UNSAFE;预算变化 → `runtime_plan.restart_required`(已执行计划 vs 当前预算重算计划)| 预算 5000→dual / 4096→transient / 3800→insufficient(同硬件形态纯函数级);insufficient 集成测试:created 全无 cuda 设备、capacity=UNSAFE、查询 CPU 仍可执行;改预算→pending_mode=transient+restart_required=True 而已执行模式不变 |
| **B5 测试缺口** | 假阳性 different-device 测试改为**双侧真执行**断言(输出向量+实例调用记录,非 identity);四阻断项各配焦点回归;REV1 全套复跑 | 见 R3 |

## R2. 运行时架构增量(RUNTIME_ARCHITECTURE_DELTA)

```
装配期(lifespan / _build):
  budget = Auto(空闲+驻留实况) | min(Manual, 实况)     # B4,不可读→None
  plan  = compute_residency_plan(budget, embedder_gpu, reranker_gpu)
  ├─ undecided      → 双驻留(v1.1 现状;容量如实 unknown)
  ├─ dual_resident  → embedder+reranker 均 GPU 常驻(预算 ≥4562)
  ├─ reranker_transient → embedder GPU 常驻;reranker 权重驻留主机内存,
  │    经 _TransientGpuReranker 代理:入闸(query 优先)→ 上卡 compute
  │    → 卸载(host RAM + empty_cache)                 # B3,峰=4050 有界
  └─ gpu_insufficient → GPU 侧零装配;全部按计划 CPU(status 显式)→ UNSAFE 如实
运行期:
  query embed → [GPU? 入闸.query] → 查询实例(B1 恒有)
  sync  embed → [GPU? 入闸.sync(query 优先, 批粒度让路)] → CUDA 失败单向回退(#14)
  rerank      → 双驻留直呼 | 瞬态代理(入闸.query + 上卡/卸载)
```

- 模型身份/检索与重排语义:**零变化**(同一模型实例,仅 .to(device));
- 重排未移 CPU:瞬态模式执行设备仍 GPU(effective=gpu + residency=transient 双字段如实);
- 吞吐取舍(如实声明):瞬态计划下并发 Ask 的重排步骤排队(与嵌入互斥);
  生产有效预算 4096 下双驻留已被 Discovery 实测证伪(4044 稳态+490 峰>4096),
  此为最小安全解;真 GPU 验证归 §34 生产容量验收门。

## R3. REV1 验证结果(TEST_RESULTS)

| 项 | 结果 |
|---|---|
| 聚焦 runtime(23 用例:B1×2/B2×3/B3·B4×5/回退×3/容量×4/真相面×3…) | 23 passed(3× 复跑防 flake) |
| 聚焦 内部端点+Admin API+embedder+test_sync | 72 passed |
| **后端全量离线回归** | **1655 passed / 6 skipped / 0 failed(×2 轮,45s)** |
| Admin vitest(含 REV1 徽标/计划行/计划 CPU 标注×2 新用例) | **273 passed / 0 failed** |
| Admin 生产构建(tsc -b + vite) | 绿 |
| ruff / black(REV1 改动面) | clean |

测试文件增量:`tests/runtime/test_manager.py` 重写(B1-B5 全覆盖);
`tests/api/test_internal_embeddings.py` fixture 快照对齐计划语义(free 9000→双驻留,
使服务端回退路径可触达——旧 3960 快照在新计划下如实判 insufficient,属语义修正非放松)。

## R4. GPU 容量推理(GPU_CAPACITY_REASONING)

- 证据链(Discovery E1-E10 + 2026-09-03/04 生产实测):双模型稳态 4044MiB;
  重排 fp16 权重 ≈1150MiB → 嵌入常驻份额 ≈2900MiB(常量内含各自工作区/上下文份额);
  查询峰值 +490MiB(保留 512);外部常驻 ≈11.59GiB → 有效预算 ≈4096MiB。
- 双驻留 + 查询峰 = 4044+490 ≈ 4534 > 4096 → **现状结构性不安全**( Discovery 结论);
- 瞬态计划把「同时驻留」改为「按步驻留」:嵌入步峰 = 2900+512 = 3412;
  重排步峰 = 2900+1150 = 4050;跨 Ask 并发由 B2 闸串行 → **峰恒 ≤4050 < 4096**,
  后端 repeated-Ask 在冻结容量约束下可行;
- 常量是可调证据值而非产品硬编码:同一公式在 8GB/24GB 卡自动给出更宽计划
  (代码全库无 4GB 硬编码,`compute_residency_plan` 纯函数可验);
- 残余边界(如实):瞬态模式下 rerank 上卡瞬间若恰逢 embed 峰由闸互斥排除;
  观测通道不可用时计划退化为 undecided(维持现状,不臆造)。

## R5. §40 REV1 交付字段

| 字段 | 值 |
|---|---|
| STATUS | **CANDIDATE READY** |
| BASELINE | 35785a4 |
| REV1_COMMIT | **1e58dbd**(origin/v1.1/gpu-runtime-models-admin) |
| BLOCKER_MATRIX | R1(5/5 修复,各附测试证据) |
| RUNTIME_ARCHITECTURE_DELTA | R2 |
| TEST_RESULTS | R3(1655/6/0 ×2;admin 273/0;双构建绿) |
| GPU_CAPACITY_REASONING | R4 |
| REPORT_PATH | docs/implementation/CAMTHINK_GPU_RUNTIME_MODELS_ADMIN_EXECUTION_2026-09-04.md(本文件 REV1 追加节) |
| PRODUCTION_MUTATIONS | **NONE**(未部署生产;未打 tag;未关 issue) |

**STOP。等待 Planner 复审。**

---

# REV2 — 最终阻断修复(2026-09-04 追加)

- **REV2_BASELINE**: 1e58dbd(REV1 候选)
- **REV2_COMMIT**: **72cdcbf**(@origin/v1.1/gpu-runtime-models-admin)
- **STATUS**: **CANDIDATE READY**;PRODUCTION_MUTATIONS=**NONE**;无 merge main/无 tag/release
- 架构/Admin UX/瞬态重排策略:**零重设计**(按 REV2 契约约束)

## A1. R2-1 — 查询侧不再自动降级 CPU(UNSAFE fail-closed)

**授权边界修正**:`gpu_insufficient` 计划下,REV1 曾把配置为 GPU 的查询侧
workload 自动转为 CPU —— 超出产品授权。REV2 语义:

| 工作负载 | UNSAFE 计划下行为 | 授权依据 |
|---|---|---|
| 查询嵌入 | **零实例构造**(不上 GPU 冒险、不建 CPU 替身);`embed()`/`dimension` 抛 `UnsafeRuntimePlanError`(含可操作指引);status=`unsafe_no_safe_plan`;effective **不谎报为 CPU**(保持 configured GPU) | R2-1 冻结语义:查询嵌入默认 GPU;CPU 仅管理员可选;自动查询 CPU 回退未授权 |
| 查询重排 | 同上:`rerank()` 拒绝执行 | 同上(查询重排默认 GPU) |
| 同步嵌入 | 按既有授权 CPU 路径继续执行;status=`cpu_by_capacity_plan` 显式标注(非静默) | R2-1 明确仅禁止查询侧;#14 谱系的 sync CPU 路径既有授权;后台同步不因误配置中断 |

- **防不安全 GPU 执行**:GPU 侧零装配(先拒载后如实报告,B4 语义延续);
- **Admin 可达**:后端正常启动,仅查询请求显式失败;快照新增
  `runtime_plan.action_required`,UNSAFE 徽标/状态文案/行动提示(增量,零重设计);
- **不新增动态自动调度器**(fail-closed 是静态计划语义,非运行时调度)。

**回归测试(按 REV2 要求逐字)**:
- `test_r2_1_insufficient_budget_query_side_fail_closed_never_cpu`:配置查询 GPU +
  预算不足 → configured=effective=**gpu**(≠ CPU 执行)、status=unsafe_no_safe_plan、
  `_query_embedder is None`、`_reranker is None`、created 无任何 cuda 实例、
  embed/rerank 抛 UnsafeRuntimePlanError、capacity=UNSAFE、action_required=True;
- `test_r2_1_insufficient_budget_sync_background_continues_on_cpu_loud`:
  sync effective=cpu + cpu_by_capacity_plan 显式标注且真实执行;
- Admin 测试:UNSAFE 徽标 + 「无安全运行计划,已拒绝执行(未自动降级 CPU)」+ 行动提示。

## A2. R2-2 — 查询优先 + 有界公平(无 sync 永久饥饿)

`_GpuGate` 增加**配额让路**算法(有界公平,exact HOW 归执行方):

- 查询优先保留:有查询等待时(`query_waiting>0`),sync 新批次不得启动;
- **饥饿账本**:每个查询空档被占用时,若存在 sync 等待者则
  `starvation_credit += 1`;计满 `SYNC_FAIRNESS_QUOTA`(=4,模块常量)后
  闸转入公平窗口(`sync_priority=True`):新到查询在窗口内排队;
- **一次一批**:下一个空档让给已等待的 sync;执行后配额清零、窗口关闭,
  查询优先恢复;sync 最坏延迟 = QUOTA 个查询批次(嵌入批次毫秒级,有界);
- sync 单元仍有界(≤ EMBEDDER_BATCH_SIZE);无无界队列(闸不创建调用方之外的
  排队);无未受控并发 GPU 推理(互斥不变);
- 等待者消失时公平状态自动复位(防窗口悬挂)。

**确定性飢饿测试** `test_r2_2_waiting_sync_eventually_executes_under_query_pressure`:
持续查询压力(q2..q5 逐个排队→获取,credit 计满 4)+ 等待中的 s1 → 公平窗口开启,
第 6 个查询被拦,s1 获执行权;随后配额清零,q6 才执行;ends 顺序确定性断言
`q1..q5, s1, q6`。全部事件+闸状态轮询驱动,零 sleep 竞态(5× 复跑稳定)。

## A3. REV2 验证结果

| 项 | 结果 |
|---|---|
| 聚焦 runtime(含 R2-1×2、R2-2×1 新用例) | **25 passed(×5 复跑稳定)** |
| 聚焦 内部端点+Admin API+embedder+sync | 102 passed |
| **后端全量离线回归** | **1657 passed / 6 skipped / 0 failed** |
| Admin vitest(含 UNSAFE 标注新用例) | **274 passed / 0 failed** |
| Admin 生产构建(tsc -b + vite) | 绿 |
| ruff / black | clean |

## A4. REV2 交付字段

| 字段 | 值 |
|---|---|
| STATUS | **CANDIDATE READY** |
| BASELINE | 1e58dbd |
| **REV2_COMMIT(新候选 SHA)** | **72cdcbf**(origin/v1.1/gpu-runtime-models-admin) |
| TEST_RESULTS | A3(全量 1657/6/0;admin 274/0;双构建绿) |
| REPORT_PATH | docs/implementation/CAMTHINK_GPU_RUNTIME_MODELS_ADMIN_EXECUTION_2026-09-04.md(REV2 追加节) |
| REPORT_COMMIT | docs 仓本提交 |
| PRODUCTION_MUTATIONS | **NONE**(无生产变更/无 merge main/无 tag/release) |

**STOP。等待 Planner 复审。**

---

# REV3 — GPU UUID 归一化(2026-09-04 追加;窄修复)

- **BASELINE**: 72cdcbf(生产当前运行态;容量门 PARTIAL 的根因修复)
- **REV3_COMMIT**: **ab0e29c**(@origin/v1.1/gpu-runtime-models-admin;**未 push main、未触碰生产**)
- **STATUS**: **CANDIDATE READY**(按 §8 工程停点:待 Planner 审查授权后才可部署/集成)
- **PRODUCTION_MUTATIONS**: **NONE**

## ROOT_CAUSE(生产容量门 PARTIAL 的单点根因,已在生产容器内实证)

- `discover_gpus()` 经 `torch.cuda.get_device_properties().uuid` 取得**无前缀裸形**
  `3caad314-…`;
- `read_gpu_memory` 将其直接传给 `nvidia-smi --id=3caad314-…`;生产容器内驱动
  **拒绝非 `GPU-` 前缀形态**(返回码非 0),Python 侧身份匹配无从发生;
- 后果链:读数 None → 有效预算 None → 计划 `undecided`(fail-safe=维持双驻留)→
  reranker_transient / 预算驱动未激活、容量分级恒 unknown。

## UUID_NORMALIZATION(单一规范身份)

- 新增 `normalize_gpu_uuid(raw)`:剥 `GPU-` 前缀后统一重建规范形 `GPU-<uuid>`;
  torch 裸形与 nvidia-smi 规范形归一化结果一致(不依赖具体 UUID 值);
  空串/None→None;`MIG-` 等非 GPU- 前缀形态**原样保留**(不归一化、不破坏);
- `discover_gpus()` 发现期即产出**规范形** uuid:torch 发现、持久化策略、容量观测、
  Admin 呈现、CUDA index 投影共用同一身份表示;index 兜底行为不变(torch 无 uuid
  时 `index-N`,不臆造 GPU- 形态);
- `read_gpu_memory(uuid)` 改为**单次全卡查询 + 本地精确身份匹配**:
  彻底弃用 `--id`(驱动不再有机会拒绝任何形态——修复在命令之前,非事后放宽匹配);
  `None`→默认第一卡;规范形/裸形→同一物理卡;未知/不可见→**None 绝不回退他卡**;
  多卡按归一化精确相等逐行选择(支持未来多卡选择);
- `manager._read_policies`:历史策略行可能存有规范化前的裸形 uuid——读取期归一化
  (向后兼容,§3 身份契约;生产当前 0 行,纯防御)。

## CHANGED_FILES

- `backend/runtime/hardware.py`(归一化 + 发现规范形 + 读数重写)
- `backend/runtime/manager.py`(`_read_policies` 读取期归一化;向后兼容所需,最小面)
- `tests/runtime/test_hardware.py`(回归测试 A-F 重写/新增)

## TESTS(§6 A-F 全覆盖;全部 mock,无真实 GPU 依赖)

| 用例 | 证明 |
|---|---|
| A 裸形→规范形 | `read_gpu_memory("3caad314-…")` 解析 T4 快照;args 断言**无 `--id`** |
| B 规范形 | `read_gpu_memory("GPU-…")` 同一快照 |
| C None 默认卡 | 双卡 fixture 返回第一卡数值 |
| D 未知身份 | 规范形+裸形未知 UUID 均 → None(不回退 GPU 0) |
| E 多卡 fixture | 请求第二卡(A100)得第二卡数值,规范形/裸形一致且≠第一卡 |
| F discover 稳定身份 | 双卡 torch 裸形→规范形输出;index/name/total 不变;缺 uuid→index 兜底 |
| 归一化纯函数 | 空白容忍/None/空/MIG- 原样/GPU- 空壳 |

## REGRESSION

- 后端全量离线:**1663 passed / 6 skipped / 0 failed**;
- 聚焦 runtime + 内部端点 + Admin API + embedder + sync:**108 passed**;
- ruff / black:**clean**;
- Admin 代码零触碰 → 无 Admin 测试/构建需求(契约条款);生产零触碰。

## PRODUCTION_MUTATIONS

**NONE**。候选仅在候选分支(`v1.1/gpu-runtime-models-admin` @ ab0e29c);
main 未动(仍 72cdcbf = 生产运行态);部署须待 Planner 授权后按容量门流程重验
§9-§12/§17-§18(plan 预期 `reranker_transient` 激活 + 容量分级如实呈现)。
