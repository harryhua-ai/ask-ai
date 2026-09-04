# CAMTHINK — Hardware-Aware Model Runtime Discovery Report

- 日期:2026-09-04
- 角色:Engineering Executor
- BASELINE:`b7a016d0d3ec91ee69a2302a519d3ce4d9e9fdbb`(= 当前 main = 当前生产运行件)
- STATUS:**DISCOVERY READY FOR CONTRACT**
- **PRODUCTION_MUTATIONS = NONE**(全程只读;唯一一次性容器为 CPU-only 隔离基准,零 GPU 副本新增、零服务触碰)

---

## BASELINE

仓库 harryhua-ai/ask-ai @ b7a016d(工作树 `.worktrees/rc-verify-b7a016d`,detached 只读)。代码证据全部取自该树绝对路径;运行时证据取自 tesla-t4 生产只读观测。

## PRODUCTION_CONSTRAINT(既定架构约束)

- GPU:NVIDIA Tesla T4,15.56 GiB 可见显存(torch 报 16384 MiB 标称)。
- 永久第三方负载(实测,cgroup 归属核验,均非 ASK-AI 所有、不可动):
  - `locate-anything` server.py:**3,492 MiB**(root,8/17 起)
  - llama-server Qwen3.5-4B:**5,910 MiB**(ubuntu,8/19 起,`--n-gpu-layers 99`)
  - neomind extension-runner(paddle-ocr):**2,188 MiB**(9/3 起)
  - 第三方小计:**≈11,590 MiB**
- **ASK-AI 可用 GPU 预算 ≈ 4 GB**(实测瞬时 free 曾低至 126 MiB;外部负载波动不可控)。

## CURRENT_PROCESS_TOPOLOGY

| 容器 | 命令 | 进程模型 | CUDA 可见性 | 模型加载 |
|---|---|---|---|---|
| backend | `/app/.venv/bin/python -m backend.main` | 单进程(lifespan) | 有 GPU | **启动即构造** BGEEmbedder+ BGEReranker(backend/main.py:317-322,device=`EMBEDDER_DEVICE`=生产 cuda) |
| sync-executor | `python scripts/sync_executor_loop.py` | 循环 + 每请求 spawn 子进程(sync_executor_loop.py:308 `create_subprocess_exec`) | 有 GPU | 不自载;由子进程载入 |
| sync-cron | `sh -c while true; do python3 scripts/sync.py \|\| true; sleep 3600; done` | 每小时前台跑 sync.py | 有 GPU | 同上(子进程) |
| sync.py(瞬态) | `python scripts/sync.py …` | **每运行一个新进程**,经 `build_sync_embedder`(#14 路径)自载一份 BGE-m3 | 有 GPU | GPU-first + 探针 + 单向 CPU 回退 |

**结论:现拓扑结构性地制造重复 GPU 驻留** —— backend 常驻一份;任一 sync.py 运行期间再叠加一份(历史上限观测:两个 sync.py + backend 三份并存)。

## CURRENT_MODEL_OWNERSHIP(D1-D11)

- **D1** 嵌入模型实例化:① backend lifespan(`app.state.embedder`);② 每个 `scripts/sync.py` 进程内(`build_sync_embedder` → `_build_sync_embedder`,scripts/sync.py:97-101)。均为 `BGEM3FlagModel`(FlagEmbedding,fp16 on cuda,devices 显式传入)。
- **D2** 可实例化进程:backend、sync-executor 的 sync.py 子进程、sync-cron 的 sync.py 子进程(理论上限同时 3 份;已观测 3 份并存)。
- **D3** backend 自载一份:**是**(启动即载,非请求级)。
- **D4** sync-executor **容器主进程不载**;其 spawn 的 sync.py 每次运行各载一份(运行级副本)。
- **D5** sync-cron **容器主进程不载**(纯 shell 循环);其 sync.py 子进程每小时载一份。
- **D6** 模型对象:**进程局部**(`app.state` / sync.py 局部变量);应用全局于 backend 进程内;绝非请求级(backend 不按请求重建)。
- **D7** 同时可存在副本数:**当前拓扑上限 3**(1 backend 常驻 + 至多 2 个 sync.py);实测曾同时 3 份(1×backend 1,238→4,044 MiB + 2×sync.py 1,734/1,238 MiB)。
- **D8** Reranker 实例化:**仅 backend lifespan**(bge.py:322,`FlagReranker`,同 `EMBEDDER_DEVICE`)。**无独立 reranker 设备配置**——与 embedder 共用同一环境变量。
- **D9** Reranker 副本数上限:1(仅 backend)。
- **D10** 生命周期:backend 模型 = 容器进程生命周期(lifespan 构造,进程退出即随 CUDA 上下文销毁;无显式释放代码,亦无 resize);sync.py 模型 = 子进程运行期(进程退出即释放——实测两次 sync.py 退出后 GPU 列表即消失)。`_release_cuda_resources`(gc + empty_cache)仅用于 #14 回退路径。
- **D11** 「孤儿 CUDA 进程」解释:**修正此前误判** —— 09-04 发布门期间被标记为「孤儿」的 root sync.py/backend 进程,经 /proc/cgroup 归属核验实为**活容器进程与瞬态 sync.py 子进程**(host PID 回绕致低 PID 误读);sync.py 退出后 GPU 条目即消失,无进程泄漏。真正需要解释的是 09-03 cuInit=100 事故:旧容器实例的 CUDA 上下文存活于宿主(nvidia 容器运行时的进程生命周期语义),当时以 force-recreate 恢复——与本次 Discovery 的重复驻留问题是两个独立机制。

## HARDWARE_DISCOVERY

**最小可靠机制(容器内实测)**:

| 项 | 机制 | 实测 |
|---|---|---|
| GPU 名称/总显存 | `torch.cuda.get_device_properties(0)` | `Tesla T4, 15.56 GiB` ✓ |
| **GPU UUID(稳定身份)** | 同上 `.uuid` | `3caad314-5735-d4c2-64ce-e82bb88a11ba` ✓(torch≥2.x 原生,零新依赖) |
| CUDA index | 同上(runtime index)+ NVML 顺序映射 | 单卡host:index 0 恒等 |
| 已用/空闲 VRAM | **pynvml(镜像内 ABSENT,需新增依赖)** 或解析 `/usr/bin/nvidia-smi`(容器内存在) | pynvml 缺失;方案 = 新增 `nvidia-ml-py`(纯轮询只读)或 `nvidia-smi --query-gpu=... --format=csv`(结构化字段,非自由文本解析) |
| CPU 型号/核/内存 | `platform`/`/proc/cpuinfo`、`os.cpu_count`、`/proc/meminfo` | 零依赖可得 |
| 运行时可用性 | `torch.cuda.is_available()`(#14 已用) | ✓ |

- 容器可见性:容器经 nvidia runtime 直通可见物理 GPU 与其全局显存(NVML 数字含第三方占用)——**恰是容量模型需要的事实**。
- 建议:结构化 API 优先(torch props + 新增 nvidia-ml-py),nvidia-smi CSV 作回退。**Discovery 未安装任何生产依赖**。

## MODEL_MEMORY_FOOTPRINT(E1-E10)

| 项 | 值 | 方法 |
|---|---|---|
| 配置模型 | 嵌入 = BAAI/bge-m3(fp16);重排 = BAAI/bge-reranker-v2-m3(fp16);均 568M 级参数 | 代码+HF 标识 |
| E1 嵌入 CPU 内存(backend 进程 RSS,含 app) | **2,330 MB** | ps rss 只读采样 |
| E2 嵌入 GPU 驻留 | 分解近似 ~1.1-1.3 GiB 权重(fp16)+ 上下文分摊;**单项精确值 UNKNOWN**(无法从进程外分解,受控分解需重启窗口=另行授权) | nvidia-smi 进程级聚合 |
| E3 查询推理峰值 | **+490 MiB 单次分配请求**(09-04 OOM 事件实据,batch=1 查询嵌入) | 生产 OOM 消息 |
| E4 sync 批峰值 | batch=16 × max_length 8192;sync.py 进程驻留实测 1,238-1,734 MiB(含自身副本);**批内峰值 UNKNOWN**(受控测量需生产变异授权);历史:12 篇长文档批次在 ~15.4G 占用时 OOM | nvidia-smi + 同步事故记录 |
| E5 重排 GPU 驻留 | 同 E2,~1.1 GiB 权重(fp16)近似;精确分解 UNKNOWN | 同上 |
| E6 重排推理峰值 | 含于 E3 量级(30 候选 × ~800 字符);独立值 UNKNOWN | — |
| **E7 嵌入+重排稳态驻留(backend 单进程)** | **4,044 MiB(实测,查询活动后稳态)** | nvidia-smi 进程级 |
| E8 二者真实峰值 | ≥ E7 + 查询/重排激活(数百 MiB 量级)→ **≈4.3-4.6 GiB 估计**;精确值 UNKNOWN | 推算,未受控复测 |
| E9 CUDA 上下文/框架开销 | 观测差值 ≈ **1.8 GiB**(E7 − 两模型 fp16 权重和),含 context(~300-500MB)+ torch 缓存分配器池 | 差值法 |
| **E10 ~4GB 预算下安全余量** | **4,096 − 4,044 = 52 MiB 稳态余量 → 实际为零**(E8 峰值必然越线;现网任何 sync 副本叠加更是即刻 OOM——09-04 两次 ask 失败即实证) | 实测 |

## RERANKER_GPU_VS_CPU

- **GPU(生产实测,真实负载)**:`RAG timing` 日志(已有埋点,rag.py:1822)——rerank=**1,947ms** 与 **2,579ms**(两次真实 ask;30 候选 × ~800 字符档;当时 GPU 近满载,数值可能偏保守)。
- **CPU(隔离基准,T4 主机 CPU,一次显 CPU-only 容器,真实权重 bge-reranker-v2-m3 fp32)**:30 候选 × ~800 字符,**median 26,659ms / p95 28,216ms**,峰值 RSS 2,845 MB(10 轮)。
- **业务代价:重排移 CPU ≈ 每次 ask +24s**(26.7s vs 2.0-2.6s,~11×)。
- 结论:**在线重排不可移 CPU**(除非接受致命延迟);GPU 重排在近满载 GPU 上仍稳定可用。

## EMBEDDING_SHARING_FEASIBILITY

现状违反共享要求:query_embedding(backend)与 sync_embedding(sync.py)各自持有独立 GPU 副本,仅因进程边界而重复。

最小架构(推荐,详见 RECOMMENDED_ARCHITECTURE):**单owner = backend 进程内的单一驻留嵌入运行时**,sync 不再自载模型——sync-executor 保留编排职责,把 embed 工作单元经既有 DB 队列模式(sync_requests 已是跨进程 DB 交接的成熟先例)交由 backend 内的低优先级 embed worker 执行。两 workload 本就调用同一 `BGEEmbedder.embed(texts)`(bge.py:92),合并所有权无语义差异。

各选项对比:

| 选项 | 变更边界 | 进程拓扑 | 故障隔离 | 延迟 | 吞吐 | 部署复杂度 | 重启/重载 | 可观测 | 孤儿风险 |
|---|---|---|---|---|---|---|---|---|---|
| **A. DB 队列 + backend 内嵌 worker(推荐)** | sync.py 剥模型;backend 加 worker;配置/可观测小幅 | 不变(3 容器) | backend 崩 = 查询+sync embed 同停(查询本就如此;sync 编排存活) | 查询零损;sync 批间让路 | 受 worker 并发与批上限约束 | 低(无新服务) | 重启生效(与现一致的确定性) | 单点真相,易 | **消除**(无衍生 GPU 进程) |
| B. 容器内 HTTP/gRPC 模型服务 | 新服务+生命周期管理 | 4 容器 | 模型服务独立崩 | 多一跳(~ms 级) | 高 | 中-高 | 独立重启 | 需新遥测 | 低 |
| C. 共享内存/IPC(torch distributed 或 mmap) | 高(跨进程张量协议) | 不变 | 复杂 | 低 | 高 | 高 | 复杂 | 难 | 中 |
| D. 保持现状+仅缩小 sync 批 | 最小 | 不变 | 差(副本仍并存) | 受抢占 | 低 | 零 | — | 已有 | **保留**(结构性 OOM 不解) |

A 为满足冻结产品契约(§3E 单一驻留)的最小架构。

## SCHEDULING

现状:sync.py 独占进程 + 独立 CUDA 上下文,与 backend 在驱动层**时间片公平竞争**,无优先级语义;batch=16 × 8192 token 的长文档批可持续秒级占卡 → 在线查询确实可被劣化(09-04 事件中查询嵌入 490MiB 分配失败即发生于 sync 副本并存窗口)。无界性审计:sync_requests 已有 attempt 上限与退避(MAX_TOTAL_ATTEMPTS);批大小可配置但无 VRAM 峰值约束。

契约级建议(实现 HOW 不冻结):单一 owner 进程内,同一 GPU 串行流上以**批粒度**交织:查询请求即时执行(高优先),sync embed worker 在批间让路(每批 ≤ 有界 token 预算,批间检查查询等待);sync 队列有界(沿用 attempts/退避 + 队列深度上限),批大小受「VRAM 峰值预算」参数约束而非纯文档数。

## DEVICE_POLICY

- 配置面(目标):`workload × model × configured_device` 三元组,workload ∈ {query_embedding, sync_embedding, query_reranker}。
- **设备身份:持久化 GPU UUID(实测 `torch.cuda.properties().uuid` 原生可用)= 主身份;运行期解析为 CUDA index**(NVML 顺序);`cuda:0` 仅作运行时投影,不作为持久身份。
- 兼容:`EMBEDDER_DEVICE`(现仅此一个旋钮,同时喂给 embedder+reranker)保留为**引导默认/回退**;新策略存储缺省时行为逐字节等于现状(向后兼容)。
- 现状缺陷记录:reranker 无独立设备旋钮(D8)——新模型必须补齐(§3G Admin 可置 CPU)。

## DEVICE_CHANGE_LIFECYCLE

现状:backend 模型启动即载,**设备变更只能靠容器重启**;sync.py 每次运行重读配置(天然下一运行生效)。无热重载/惰性重载机制。
**V1 建议单一确定性行为:显式重启生效** —— Admin 保存 = 仅持久化 Configured Device;UI 明示 Effective Device = 当前运行值 + 「需重启生效」状态(§3I 真相要求);sync worker 侧在共享架构下同样隶属 backend 进程 → 同一重启语义。禁止静默热迁移(fp16 大模型跨设备迁移的 VRAM 双份峰值风险不可控)。

## EXISTING_FALLBACK(#14 审计)

- 触发面:`classify_cuda_failure` 三类 = cuda_init_failure / cuda_oom / cuda_runtime_error(fallback.py:131-145);解析/校验/存储错误**绝不**触发回退。
- 覆盖面:**仅 sync**(模块 docstring 明示 "online API owns its BGE and reranker lifecycles");**Query 无回退**——本次两次 OOM ask 直接失败即实证。
- 同模型:回退构造同 `BGEEmbedder`,仅 device=cpu(`_make_embedder_factory`)✓。
- OOM 后状态:`fallback_to_cpu` del 旧模型 + gc + `empty_cache` 再建 CPU,**单向一次**(`_fallback_attempted` 门),无 CPU→GPU 循环 → 不产生双驻留 ✓。
- 运行时安全:探针迁移(lazy CUDA init 前移到 setup 点,probe encode)✓;OOM 后旧上下文随 del/empty_cache 释放,未见残留(本次观测 sync.py 正常退出)。
- 遥测:`telemetry_execution_device` 三值 gpu/cpu/gpu_to_cpu + cpu_batches/cpu_docs 计数(W2 SyncRun 列)✓ 准确。
- 集成建议:新 Runtime Manager 直接吸纳 `classify_cuda_failure`/单向回退语义并**扩展到单一共享运行时**(届时 fallback 自然覆盖 sync——顺带修复「Query 无回退」缺口需另行产品决策,默认不自动扩展);#14 既有保证(单向、同模型、分类严格、遥测)全部保留为硬约束。

## ADMIN_CONTROL_PLANE

现状:Admin 页面 12 个;`SystemInfo.tsx` 只呈 release 身份(`/api/admin/system/release`,system_router 已挂载);`LLMProviders.tsx` 管 LLM 模型;**无任何硬件/运行时页**;设备唯一旋钮在 compose `.env`(非 Admin 面)。
最小统一位置建议:**扩展 System 页 = 「Hardware Resources + Model Runtime Policy」单一权威**(与 system_router 同源;不新增竞争配置权威;模型清单不进 LLMProviders——那是 LLM 供应商语义,与嵌入/重排运行时分离)。
未来 UX 概念(§3H/§3I):Hardware Resources(发现的 CPU/GPU/UUID/VRAM 已用/空闲)、每个 workload 的 Configured Device / Effective Device / 运行状态(loaded/fallback)/ 容量指示与警告。Discovery 不做视觉实现。

## CAPACITY_MODEL

分级证据驱动(不臆造阈值):可用物理 VRAM(NVML 全局)、ASK-AI 驻留(E7 实测法)、测量峰值(E3/E8)、安全余量(预算−驻留−峰值)、外部占用(外部总量,只读展示)。实测锚点:预算 ≈4,096 MiB;稳态驻留 4,044 MiB;查询峰值 +490 MiB 请求 → **当前双模型 GPU 配置在永久约束下分级为 UNSAFE(余量≈52MiB 且峰值必越线)**。HEALTHY/WARNING 具体阈值留待实现期以受控测量标定(Discovery 只定证据项,不拍数字)。

## OBSERVABILITY

已有可复用:①`RAG timing` 日志(rewrite/search/rerank/ttft/llm/total 全链,rag.py:1822)②W2 SyncRun 运行事实列(device/gpu_to_cpu/cpu_batches/cpu_docs,`telemetry_execution_device`)③sync_runs request→run→log 链路 ④`/api/admin/system/release` 直呈模式。
缺口:全局 VRAM/占用不可观测;pynvml 缺失;OOM/回退计数无聚合面;无 inference 延迟/吞吐时序。
建议:新增 `/api/admin/system/hardware`(发现的硬件 + NVML 占用,只读)+ Runtime Manager 状态端点(model×workload×configured/effective/status)+ OOM/fallback 计数器接入既有 admin 可观测;RAG timing 与 W2 列原样延用。

## PERFORMANCE_BASELINE(实测锚点,供实现对比)

| 项 | 值 | 来源 |
|---|---|---|
| rewrite / search | 504-636ms / 64-66ms | 生产 RAG timing ×2 |
| **rerank(GPU,30 候选)** | **1,947 / 2,579ms** | 同上 |
| ttft / llm_total / total | 477-593 / 2,270-2,448 / 10,597-11,130ms | 同上 |
| **rerank(CPU,同负载)** | **median 26,659ms,p95 28,216ms** | 隔离容器基准 ×10 |
| hybrid 候选规模 | recall_limit=30 → rerank 输入 30,输出 top_k=10 | 代码默认 |
| sync 嵌入批 | batch 16 × max_len 8192(compose);sync.py 驻留 1,238-1,734 MiB | 配置+观测 |
| sync 吞吐基线 | NOT MEASURED(未为 Discovery 触发生产同步) | — |

## RISKS

1. **预算红线的结构性越界**:现配置稳态 4,044MiB vs ~4,096MiB 预算,余量 52MiB——任何碎片化/外部波动/副本叠加即 OOM(已两次实证)。不做架构变更的话,连现状都不可持续。
2. 外部负载波动不可控(llama-server 5.9G 可随上下文/并发增长)。
3. 查询无 CPU 回退:单点(候选缺口,需产品决策)。
4. sync.py 瞬态副本与 backend 的驱动层竞争无优先级。
5. pynvml 需新增依赖(纯轮询、无 GPU 副本,风险低)。
6. 重启生效策略要求 Admin 真相 UI,否则「已保存≠已生效」误解会重现。

## CHANGE_BOUNDARY(未来实现)

EXPECTED:`backend/embedder/*`(Runtime Manager:发现/策略/单owner/回退吸纳)、`backend/main.py`(lifespan)、`scripts/sync.py` + `scripts/sync_executor_loop.py`(剥模型,改投递)、`backend/services/sync_requests.py`(工作单元交接)、`backend/config.py`、`backend/api/admin/system.py`(+hardware/runtime 端点)、`admin/src/pages/SystemInfo.tsx`(+Hardware/Runtime 面)、compose `EMBEDDER_*` 语义、迁移(策略持久化表/JSONB,若定 DB 存储)、测试。
REQUIRED SUPPORTING:遥测列沿用 W2;RAG timing 延用。
FORBIDDEN:嵌入模型身份/向量语义、重排算法与质量契约、RAG 含义、引用、LLM 行为、#22/#24、站点授权/CORS(§20)。

## RECOMMENDED_ARCHITECTURE

**单一 GPU owner = backend 进程内「Model Runtime Manager」**:
1. 发现层:torch props(UUID/名称/总显存)+ NVML(新增 nvidia-ml-py)读占用;CPU 经 /proc。
2. 所有权:backend 持唯一 GPU 驻留 BGE-m3(供 query_embedding 与 sync_embedding 两 workload)+ 唯一重排器(默认 GPU);策略 = workload×model×configured_device(UUID 主身份)。
3. sync 侧:sync-executor/cron 保留编排,embed 工作单元经 DB 队列交 backend 内低优先级 worker(批有界、批间让路、队列有界)——**消除一切衍生 GPU 进程**(孤儿/副本双缺口的根治)。
4. 容量分级:HEALTHY/WARNING/UNSAFE,证据项见 CAPACITY_MODEL;当前实测基线本身即 UNSAFE 案例。
5. 变更生命周期:V1 = 显式重启生效 + Configured/Effective 真相 UI。
6. #14 单向回退语义整体迁入 Manager(sync 侧行为保持;Query 侧是否获得回退 = 独立产品决策)。
7. 预算现实:在 ~4GB 预算下,双模型 GPU 稳态 4,044MiB 已无余量——**推荐同步批上 GPU 前必须先给 sync_embedding 峰值留出实测配额;若测量不支持,默认策略降级为 sync_embedding=CPU(后台可接受),重排保持 GPU**(CPU 重排 +24s/ask 不可接受)。

## OPEN_ENGINEERING_QUESTIONS

1. sync_embedding 在 CPU(bge-m3, batch≤16)的真实吞吐与每小时 cron 语料量的匹配度(需隔离基准,实现期测)。
2. 共享运行时下 sync 批的 VRAM 峰值标定(需受控测量 = REQUIRES SEPARATE PROD MUTATION AUTHORIZATION 或隔离环境)。
3. E2/E5 单模型驻留精确分解(需重启窗口实验 = 另行授权)。
4. 查询侧是否补 CPU 回退(产品决策,非 Discovery 可定)。
5. NVML 依赖选型(nvidia-ml-py 新增 vs nvidia-smi CSV 回退)——实现契约冻结项。
6. 策略持久化形态(DB 表 vs 既有 config JSONB 模式)——实现契约冻结项。

## PRODUCTION_MUTATIONS

**NONE**。只读观测(代码/Git/日志/nvidia-smi/ps//proc/docker inspect/exec 只读查询/DB 只读);唯一容器操作 = CPU-only 隔离基准一次性容器(`--network none`,`/models:ro`,无 GPU 直通,用后即焚);未杀进程、未重启/重建容器、未改任何配置/设备/模型位置、未触发同步、零 DB 写、零部署、零第三方负载改动。
