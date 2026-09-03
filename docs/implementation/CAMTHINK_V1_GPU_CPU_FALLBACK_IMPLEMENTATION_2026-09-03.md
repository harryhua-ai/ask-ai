# CamThink V1 — GPU→CPU Fallback Implementation Report

日期：2026-09-03
Issue：#14 / W1
状态：`CANDIDATE_READY`

## 1. 基线与交付边界

- 基线 commit：`1d6f6b5fe697b5f7a1b8decef1c29f51afcda937`
- 实现 commit：`88375b7`
- 分支：`codex/issue-14-w1-sync-runtime-reliability`
- 生产同步、部署、容器重启、生产数据 mutation：均未执行
- `backend/main.py`、在线 BGE/reranker 生命周期：未修改
- W2 migration、`SyncRun` schema、Admin API/UI：未修改

本交付只覆盖 sync executor 进程内的 embedding runtime。在线 Q&A 仍由
`backend/main.py` 直接创建并驻留自己的 BGE 与 reranker；W1 不会为同步回收、
卸载、重启或重建在线模型。

## 2. 实现结果

### GPU-first 与显式设备

`backend/embedder/fallback.py` 复用现有 `detect_device` 语义：

- `EMBEDDER_DEVICE=cuda` / `cuda:N`：先构造 CUDA BGE；
- `EMBEDDER_DEVICE=cpu`：只构造 CPU BGE，不探测 GPU，也不启用自动回退；
- `auto`：保持既有 CUDA > MPS > CPU 选择；
- CUDA 构造成功后执行一次最小 encode probe。健康路径仍使用 GPU，probe 不是
  CPU 默认化。

### 故障分类与回退边界

`classify_cuda_failure()` 只返回冻结的显式 CUDA 类别：

| 分类 | 示例 | 处置 |
| --- | --- | --- |
| `cuda_init_failure` | `CUDA initialization`、`cuInit=100`、NVML/driver 初始化失败 | 允许一次 GPU→CPU |
| `cuda_oom` | CUDA/GPU `out of memory`、qualified CUDA OOM exception | 允许一次 GPU→CPU |
| `cuda_runtime_error` | CUBLAS、cuDNN、NCCL、illegal memory access、device-side assert 等白名单运行时错误 | 允许一次 GPU→CPU |
| `None` | parse/bad document、network、Weaviate/PG、validation、application bug | 不换设备，沿既有失败隔离路径 |

没有使用 `except Exception => CPU`。分类失败返回 `None`，因此普通应用、
文档或向量库错误不会意外启动 CPU 模型。

### 有界、单向 fallback

`SyncEmbedderHandle` 管理同步进程内唯一的设备状态：

1. 释放旧 GPU embedder 引用；执行 `gc.collect()` 与 best-effort
   `torch.cuda.empty_cache()`；
2. 最多构造一次新的 `BGEEmbedder(device="cpu")`；
3. 当前批次使用同一批文本在 CPU 重嵌，后续批次保持 CPU；
4. CPU 构造或 CPU encode 失败直接抛 `CpuFallbackError`，不回 GPU、不逐文档
   重试、不无限 retry。

批量 embed 完成后才进入 Weaviate 写入阶段，因此 GPU 批量失败的重嵌不会重复
已成功写入的数据。`cpu_batches` / `cpu_docs` 只在 CPU encode 成功后计数，
   并按 source snapshot 计算本 source 的真实增量。

若 CPU 模型在 setup 阶段就不可用，sync runner 将 terminal error 延迟到
`_sync_one` 已建立的 source run 中，保留 failed `SyncLog` 与 runtime reason；
这条路径也不启动第二次 CPU 构造。

## 3. W2 冻结接口消费

W1 只消费以下冻结接口，不创建竞争 schema/API：

```python
record_device(
    session_factory,
    run_id,
    *,
    execution_device,
    fallback_reason,
    fallback_detail,
)
```

`scripts/sync.py` 的 `_RunTelemetry.device()` 按原签名透传，设备值为
`gpu`、`cpu` 或 `gpu_to_cpu`，原因与 detail 来自实际 classifier/fallback。
当前 W1 基线尚没有 W2 的 `record_device` 实现，因此使用 nullable import
适配层；测试通过 monkeypatch 验证精确调用。W2 合入时以 W2 persistence/API
实现为 authority，适配层应与其合并为最终单一 consumer。

### SHA short-circuit truth

健康 GPU handle 在“无 upstream change、零 encode”的 source run 中不会写
`gpu` device fact；因此不会制造“GPU embedding healthy”证据。只有真实 encode
活动或真实 fallback 事件才记录 runtime device。显式 CPU 的零 encode 也不会
冒充 GPU 健康。

## 4. 配置与在线保护

新增 sync-only 配置：`EMBEDDER_CPU_FALLBACK=on|off`，默认 `on`，并透传到
dev/prod compose backend anchor。该开关只由 W1 sync fallback 工厂读取；在线
backend 不消费它。设置为 `off` 时不自动构造 CPU fallback。

没有修改 executor 的独立 process boundary，也没有 kill/restart/unload 在线
模型。same-process fallback 仅发生在 sync runner 子进程内。

## 5. 验证证据

### W1 focused tests

```text
./.venv/bin/pytest -q \
  tests/embedder/test_fallback.py \
  tests/pipeline/test_ingest_fallback.py \
  tests/scripts/test_sync_device.py
26 passed
```

覆盖 healthy GPU、explicit CPU、CUDA init failure、CUDA OOM、unrelated
exception、CPU fallback failure、单向/无 retry、批次与文档计数、W2 参数、
short-circuit、failed run accounting。

### 既有相关回归

```text
./.venv/bin/pytest -q \
  tests/embedder/test_fallback.py tests/pipeline/test_ingest_fallback.py \
  tests/scripts/test_sync_device.py tests/embedder/test_bge.py \
  tests/pipeline/test_ingest.py tests/pipeline/test_sync.py \
  tests/scripts/test_sync_db.py tests/scripts/test_sync_run_core.py
129 passed, 3 skipped
```

```text
./.venv/bin/pytest -q --ignore=tests/api/admin
959 passed, 5 skipped
```

```text
./.venv/bin/ruff check [all changed W1 Python files]
All checks passed!

git diff --check
clean
```

完整 `./.venv/bin/pytest -q` 的非 Admin 测试同样通过（`959 passed, 5 skipped`），
但 Admin fixture 在 setup 阶段报告 `llm_providers` 表不存在，产生 184 个环境
schema errors；这不是 W1 测试失败，也未通过修改 W2/数据库来规避。

所有 CUDA 故障均使用 fake/mock fault injection 验证，未要求或执行生产 CUDA
故障注入。

## 6. 已知限制与 W2 集成事项

- 当前分支尚未包含 W2 migration/`record_device` persistence，因此本分支的
  telemetry 持久化依赖 W2 合入；调用契约已按冻结签名测试。
- 没有在真实生产 T4 上执行 CUDA OOM/init fault injection；同进程安全性由
  sync runner 的独立进程边界、资源释放路径及 fault-injection tests 覆盖。
- V1 不做 OOM 后 GPU batch-size 自适应；CPU fallback 可能明显增加同步耗时，
  但不设置无限重试或 kill timeout。
- 合入 W2 时如双方同时修改 `_RunTelemetry.device` 附近代码，应保留 W2 的
  schema/API ownership 与 W1 对冻结 `record_device` 的单一调用，不扩展 W1
  的 migration/API 范围。

## 7. 最终边界

`PRODUCTION_MUTATIONS: NONE`
