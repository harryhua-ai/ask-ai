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
