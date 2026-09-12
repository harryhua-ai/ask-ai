# #7 Admin Read-Only System & Hardware Runtime Observability(B3)——执行报告

- Iteration:v1.6.2;Track:B3;branch:`b3/system-runtime-observability-20260912`
- Starting main SHA:`0590a82`(origin/main)
- Frozen contract:`docs/engineering/tasks/v162-i7-system-runtime-observability-contract.md`(逐条遵守,零 CONTRACT DRIFT)
- Issue:harryhua-ai/ask-ai#7

## 1. Changed files(`git diff --stat origin/main..HEAD`)

```
 admin/src/hooks/useSystemRuntime.ts           |  17 +
 admin/src/pages/SystemInfo.tsx                | 242 +++++++++++-
 admin/src/types/api.ts                        |  87 +++++
 admin/tests/SystemInfo.test.tsx               | 267 ++++++++++++-
 backend/api/admin/system.py                   |  34 +-
 backend/services/host_runtime.py              | 543 ++++++++++++++++++++++
 tests/api/admin/test_system_runtime.py        | 394 ++++++++++++++++++
 tests/services/test_host_runtime_collector.py | 393 ++++++++++++++++
 8 files changed, 1969 insertions(+), 8 deletions(-)
```

纯新增观察面;未触碰 data_sources/tech/Analytics/DataSources 等其他 track 的
任何文件;`/model-runtime*` 管理端点零改动(`backend/api/admin/model_runtime.py`
不在 diff 中)。

## 2. Implementation decisions

### 2.1 采集器设计(`backend/services/host_runtime.py`,stdlib-only)

- **依赖裁定:零新依赖**。psutil 未引入;全部采集用 stdlib + 一次既有
  nvidia-smi 只读查询模式:
  - host:`socket.gethostname()`、`platform.system/release/machine`、
    uptime = `/proc/uptime`(Linux)→ `sysctl -n kern.boottime`(macOS 兜底)
    → 显式不可得;
  - resources:CPU 型号 `/proc/cpuinfo`;核数 `os.cpu_count()`;利用率
    `/proc/stat` 双采样(Δ0.1s,`(idle+iowait)`/total 增量);loadavg
    `os.getloadavg()`;内存/swap `/proc/meminfo`(used = MemTotal−MemAvailable);
    磁盘 `shutil.disk_usage(<backend 包所在卷>)`(生产镜像 = /app 部署卷);
  - accelerator:单次全卡结构化查询
    `nvidia-smi --query-gpu=index,uuid,name,driver_version,utilization.gpu,
    memory.used,memory.free,memory.total,temperature.gpu --format=csv,noheader,nounits`
    (与既有 `hardware.read_gpu_memory` 同权限同方式同超时;不使用 `--id`,
    uuid 经 `normalize_gpu_uuid` 归一)→ 利用率/显存/温度;plain `nvidia-smi`
    头部解析 Driver/CUDA 版本;**nvidia-smi 缺失但 torch 可见 CUDA 设备时**
    以 `discover_gpus()` 兜底列出设备(存在是事实),nvidia-smi 专属字段
    (利用率/温度/驱动)如实置 None 不虚构;
  - service:`get_release_identity()` 复用(#10 同一进程级权威)+
    health(`"ok"`,与 /health 同源语义:端点可响应即进程存活)+
    `model_runtime.snapshot()` 真相面**五键白名单直呈**
    (devices/policies/shared_embedding_runtime/runtime_plan/capacity)。
- **测试 seam**:全部 IO 收敛为模块级函数,monkeypatch 即可,测试零真实
  GPU/proc:`_read_file` / `_run_readonly` / `_hostname` / `_platform_facts` /
  `_loadavg` / `_disk_usage` / `_sleep` / `_now_iso` / `discover_gpus`。
- **安全形状**:`subprocess.run(固定字面量参数列表, timeout=10, 无 shell)`,
  无任何请求输入进入命令行;`except` 全部收敛为显式不可得/日志,**采集面
  永不抛错 → 端点恒 200**(500 仅剩不可达路径)。

### 2.2 显式不可得(unavailable)语义表

每项观测 = 四元组 `{available, value, reason, as_of}`;每 section 亦带 `as_of`;
顶层 `as_of` = 采集起点。不可得 ⇒ `available:false` + 非空 reason + **value 恒
null**(绝不虚构/占位);段结构恒完整(非错误、非空壳)。

| 观测项 | 可得条件 | 不可得 reason(示例) |
|---|---|---|
| host.hostname | `socket.gethostname()` | 「hostname 采集失败(OSError)」 |
| host.os / kernel | `platform.*` | 「平台信息不可得(platform 为空)」 |
| host.uptime_seconds | /proc/uptime 或 sysctl boottime | 「uptime 不可得(需 Linux /proc/uptime,当前平台无此接口)」 |
| resources.cpu_model | /proc/cpuinfo model name | 「CPU 型号需 Linux /proc/cpuinfo(当前平台不可得)」 |
| resources.cpu_utilization_percent | /proc/stat 双采样 | 「CPU 利用率需 Linux /proc/stat 双采样(当前平台不可得)」 |
| resources.loadavg_* | `os.getloadavg()` | 「load average 在当前平台不可得」 |
| resources.memory_* / swap_* | /proc/meminfo | 「内存水位需 Linux /proc/meminfo(当前平台不可得)」 |
| resources.disk_* | `shutil.disk_usage(部署卷)` | 「磁盘用量采集失败(OSError:/app)」 |
| accelerator.available | nvidia-smi 或 torch 任一可见 GPU | 「未发现 NVIDIA GPU(nvidia-smi 不可用:…;torch CUDA 亦不可见)」 |
| accelerator.driver_version / cuda_version | plain nvidia-smi 头部 | 「驱动版本需 nvidia-smi(当前不可得)」 |
| gpu.utilization_percent / temperature_c 等 | nvidia-smi 该卡行 | 该字段 None(如 `[Not Supported]`/torch 兜底条目),前端呈「不可得」 |
| service.release | RELEASE.json 权威 | 「release 身份加载失败(ReleaseIdentityError)」 |
| service.model_runtime | `app.state.model_runtime` 就绪 | 「模型运行时未就绪(本进程未初始化 model runtime)」/「模型运行时快照失败(RuntimeError)」 |
| service.health | 进程可响应本请求 | 恒 available(与 /health `status="ok"` 同源语义) |

### 2.3 采样语义(v1)

按需采集(每次 GET 现场收集)+ 前端手动刷新按钮;`staleTime=15s` 去抖、
`refetchOnWindowFocus=false`、**零自动轮询**(合同允许 B3 权衡轻轮询,v1 取
最保守)。每项/每段 as_of 标注采集时间(UTC ISO-8601)。

## 3. Reused vs new surfaces

| 类型 | 面 |
|---|---|
| 复用 | `/system` router 挂载点与读权限约定(`require_role("admin","editor","viewer")`,与 /system/release 一致);release 身份权威 `backend.release.get_release_identity`;nvidia-smi 只读查询模式与 uuid 归一(`backend.runtime.hardware`);model-runtime 快照真相面(`ModelRuntimeManager.snapshot()` 五键);LoadError/badge/Field 前端纪律 |
| 新增 | `backend/services/host_runtime.py`(采集器,543 行);`GET /api/admin/system/runtime`(同 router 追加,不动既有路由);`admin/src/hooks/useSystemRuntime.ts`;`SystemRuntimeInfo` 类型族(types/api.ts 追加段);SystemInfo.tsx「系统运行时」分区(该组件注释预留位) |

## 4. RED evidence

1. `tests/services/test_host_runtime_collector.py` 先行落地 →
   `ImportError: cannot import name 'host_runtime' from 'backend.services'`
   (collection error,12 例全红)→ 实现采集器后 12 passed。
2. `tests/api/admin/test_system_runtime.py` 先行落地(端点不存在)→ 实现后
   经历两态修正(CPU /proc/stat 桩增量算术、seam 打点位置),最终 9 passed。
   过程中红例:`test_runtime_full_facts_end_to_end`(seam 未生效 + fake_smi
   args 越界)、`test_runtime_readable_by_all_admin_roles`(session-loop
   async fixture 不可 `request.getfixturevalue` 动态解析 → 改间接参数化)。

## 5. Tests & results

| 套件 | 命令 | 结果 |
|---|---|---|
| 采集器单元(无 DB,可并行) | `pytest tests/services/test_host_runtime_collector.py -q` | **12 passed** |
| Admin system API(两文件) | lock wrapper:`pytest tests/api/admin/test_system_runtime.py tests/api/admin/test_system_release.py -q` | **13 passed**(9 新 + 4 既有 release 零回归) |
| ruff | `ruff check backend/services/host_runtime.py backend/api/admin/system.py tests/services/test_host_runtime_collector.py tests/api/admin/test_system_runtime.py` | **0 error**(All checks passed) |
| admin vitest | `cd admin && npx vitest run` | **46 files / 301 tests 全绿**(含 SystemInfo 新 5 例 + 既有 10 例零回归) |
| admin tsc | `npx tsc -b` | 本任务文件 0 error(widget 子项目缺 node_modules 的既有报错与本 diff 无关,main 同样存在) |
| **全量后端回归** | lock wrapper:`pytest tests/ -q --ignore=tests/benchmark --ignore=tests/e2e` | **2434 passed, 6 skipped, 0 failed, 10 errors**(10 errors 全部为基线既有环境性失败,证据见 §11) |

## 6. Runtime verification scope

- **无 GPU/开发环境(本机 macOS arm64,已执行)**:采集器现场运行 →
  - 显式不可得态全部按表呈现:CPU 型号/利用率、内存/swap、加速器整段
    (`available:false`,reason=`未发现 NVIDIA GPU(nvidia-smi 不可用:nvidia-smi
    不可执行(未安装);torch CUDA 亦不可见)`)——非错误、非空壳;
  - 可得项与 SSH 取证比对(证据-only):uptime=4303906s ≈ 49.8 天 vs
    `uptime`「up 49 days, 19:32」一致;loadavg 2.46/2.03/1.99 vs
    `sysctl` 2.24/2.00/1.98(采样时点偏移内一致);hostname/OS/内核/磁盘路径
    直接可核;页面全程零 SSH。
- **GPU 主机走查(合同强制 Phase 5)**:**实际执行 deferred to Integration B
  / deployment**(本 track 无生产 GPU 主机访问;合同「Issue 关闭前置:部署后
  生产可见面与本合同语义一致」归 Integration B 收口)。
- **走查脚本(Integration B 用,对照 SSH 取证 only)**:

```bash
# 1) 页面走查(Admin → 配置 → 系统信息 → 系统运行时,截图;全程零 SSH)
#    校验点:主机/资源/加速器/服务状态四组齐;as_of 显示;刷新按钮可用
# 2) SSH 取证对照(只读,证据-only;数值允许采样时点偏移)
uptime                                  # vs host.uptime_seconds / loadavg_*
df -h /app                              # vs resources.disk_*(部署卷)
nvidia-smi --query-gpu=index,uuid,name,utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv,noheader,nounits
                                        # vs accelerator.gpus[]
nvidia-smi | head -1                    # vs accelerator.driver_version/cuda_version
# 3) 无 GPU 环境复检:同页面加速器组=显式不可用+原因,页面 200 不崩
```

## 7. Scope audit(只读可证)

- **GET-only**:diff 中唯一新端点 `@router.get("/runtime")`;system router
  现有路由 = {`/system/release`, `/system/runtime`} 全部 `methods=={"GET"}`
  (测试 `test_system_router_is_get_only` 结构锁);无任何 PUT/POST/DELETE。
- **零操作控制**:无 restart/kill/cache-clear/reindex/shell/任意命令执行;
  页面唯一按钮 = 刷新(数据重取,vitest 断言全页按钮数=1)。
- **零生产变更/零部署**:纯代码 diff;无迁移、无配置、无基础设施变更。
- **零 env/secrets 暴露**:响应键精确锁测试 + 无环境变量读取(仅 stdlib 采集)。
- **/model-runtime 管理面零改动**:该文件不在 diff;service 段仅**读**
  snapshot() 五键白名单。
- **其他 track 零触碰**:data_sources/tech/analytics 等文件不在 diff。

## 8. 环境事件记录(共享测试基础设施)

- **lock wrapper 缺陷修复(共享 /tmp 基础设施,非 repo 代码)**:
  `/tmp/askai-test-run.sh` 原实现 `exec "$@"` 使 EXIT trap 失效(exec 替换
  进程),每次跑完必然遗留 stale lock → 三 track(B1/B2/B3)全体死锁。
  已升级 v2:子进程方式运行(trap 生效)+ stale-lock 自愈(lock>10min 且无
  真实 `^.venv/bin/python -m pytest` 进程才回收)。
- **本机 DB 拓扑事件**:Homebrew postgres@16 自 2026-09-02 起占用
  127.0.0.1:5432,遮蔽 OrbStack docker 转发 → `ask_ai` 库不可达
  (InvalidCatalogNameError)。本 track 全部 DB 测试以
  `POSTGRES_HOST=ask-ai-local-postgres-1.orb.local`(docker PG)执行解决;
  未改任何 repo 配置。后续 track 如遇同类失败可用同环境变量。

## 9. Unresolved risks

1. **GPU 主机真值走查未执行**(合同强制 Phase 5)——deferred to Integration
   B/deployment;采集逻辑已由两态 mock 测试 + 无 GPU 现场走查覆盖,但
   nvidia-smi 真机字段(如旧驱动 `[Not Supported]` 的利用率字段)只在生产
   等价环境可见。风险:低(该形态已按 None→「不可得」处理)。
2. `service.health="ok"` 语义 = 「本端点可响应即进程存活」,与 /health 探活
   完全同源,但严格来说非独立探针。已在 docstring 注明。风险:极低。
3. 前端对 model-runtime 五键的展示为宽松直呈(policies 字段以
   `Record<string, unknown>` 读取);snapshot 键由后端测试锁定,前端若遇
   未预期形状仅显示缺省文本,不会崩。风险:低。
4. CPU 利用率为 0.1s 双采样瞬时值(非历史均值),页面已如实标注采集时间;
   运营用于例诊足够,若需趋势图属后续迭代。

## 10. Candidate SHA & Verdict

- Candidate SHA:`526a6d1`(implementation)→ 最终见 git log(报告提交后 push)
- **Verdict:B3-SYSTEM-RUNTIME-OBSERVABILITY = CANDIDATE READY**
  (GPU 主机真值走查按合同归 Integration B/deployment 收口;代码/测试/
  前端/静态检查/全量回归全部完成且绿)

## 11. 全量回归执行记录(已回填)

- 命令:`POSTGRES_HOST=ask-ai-local-postgres-1.orb.local
  TEST_DATABASE_URL=…@ask-ai-local-postgres-1.orb.local:5432/ask_ai_b3_test
  HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_XET=1
  MODEL_CACHE_DIR=<主仓>/models bash /tmp/askai-test-run.sh <worktree>
  .venv/bin/python -m pytest tests/ -q --ignore=tests/benchmark --ignore=tests/e2e`
- 结果(B3 分支):**2434 passed, 6 skipped, 0 failed, 10 errors**(1:46)
- **10 errors 基线对照(0590a82 无本 diff 的 pristine worktree,同 env 同测试集)**:
  identical errors(tests/scripts 的 container_import×2 / migrate_llm_chain×3 /
  v140_upgrade×5 —— 均为子进程迁移类测试,依赖共享库预置 schema/容器环境),
  且基线额外多出 bge 实模型 3 errors(本分支因 MODEL_CACHE_DIR 指向完整
  模型缓存反而更少)。**结论:全部 errors 为基线既有环境性失败,与本 diff
  零相关;本 diff 引入 0 失败、0 错误。**
- 环境注记(非 repo 代码):① 共享 lock wrapper 原 `exec` 写法吞 EXIT trap
  必然遗留 stale lock → 已升级 v2(子进程 + stale-lock 自愈);② 本机
  Homebrew postgres@16 占用 127.0.0.1:5432 遮蔽 docker PG → DB 测试以
  `POSTGRES_HOST=ask-ai-local-postgres-1.orb.local` 指向 docker PG,并用
  `TEST_DATABASE_URL` 指向本 track 专用 `ask_ai_b3_test`(避免污染共享库);
  ③ HF xet 传输在当前网络下会无限期停滞 → 离线 env + 本地完整模型缓存
  (MODEL_CACHE_DIR)绕过;均已在 §8 记录,Integration B 复跑可照抄。
