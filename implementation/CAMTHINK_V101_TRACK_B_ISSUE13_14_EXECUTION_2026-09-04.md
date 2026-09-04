# v1.0.1 Track B — Issues #13 + #14 Reliability Lane 执行报告(验证型)

- baseline:0e6a8a3(v1.0.0);branch/worktree:`v1.0.1/track-b-reliability` @ `.worktrees/v101-track-b-reliability`
- **STATUS:CANDIDATE READY(verification-only;零代码变更、零提交——两 issue 在 v1.0.0 已交付且回归充分,诚实结论是不动手)**

## Issue #13(CLOSED)实码证明

任务要求的六点逐一对应 v1.0.0 代码与测试:

| 要求 | v1.0.0 事实 | 测试背书 |
| --- | --- | --- |
| documents PK/身份 schema | PK=(source_id) 路径身份,content_hash 降级普通索引(0e6a8a3 models + 生产已迁移,11,801 行守恒实证于部署门) | `tests/db/test_documents_pk.py`、`tests/db/test_migration_path_identity.py` |
| duplicate-content 行为 | 同内容不同路径 = D2 合法共存,PK 不再碰撞;repair 对重复仅 REPORT(apply 首分支 skip) | `test_a_same_hash_same_branch_diff_paths_coexist`、`test_a2_same_content_diff_branch_still_coexist`、`test_b_same_hash_across_sources_coexist`、`tests/services/test_corpus_repair.py` |
| reconciliation 路径 | `repair_corpus.py` plan(纯 SELECT)→ apply(确定性 uuid5 delete_many/零 embed 账本重建);生产修复门 60,394 向量+3 行+5 收养逐位吻合 | `test_corpus_repair.py`、`tests/scripts/test_reconcile_rebuild_identity.py` |
| 删除/恢复行为 | 账本行删/收养均可逆(dump/DELETE);向量退休=准入终态 | 修复门报告(Rollback 节) |
| 合法不同文件为何曾碰撞 | 旧 PK=(content_hash,branch) 行归属被先灌者抢占;Stage A 已切路径身份 | `test_a_pipeline_same_hash_diff_path_no_hijack`(no-hijack 回归) |
| 更安全身份机制是否已存在 | **已存在且已上产** —— 正是 #13 Stage A 交付物;孤儿/污染清零(修复门 15/15 源 verify 全零) | `tests/pipeline/test_ingest_ledger_identity.py`(幂等/跨源/删除保兄弟) |
| .so 类 unsafe 孤儿 | `historical_artifact_verdict`→RETIRE_UNSAFE_ARTIFACT;生产 artifact 剖析 .so=0 | 修复门 ARTIFACT_BREAKDOWN |

## Issue #14(CLOSED)实码证明

| 要求 | v1.0.0 事实 | 测试背书 |
| --- | --- | --- |
| 非全局禁 GPU | GPU-first + 一次性探针 + 单向有界 CUDA→CPU(`backend/embedder/fallback.py`,仅 cuda_init_failure/cuda_oom/cuda_runtime_error 白名单可回退) | `tests/embedder/test_fallback.py`(42 tests,含 classification 窄化、单向有界、禁用开关、终端失败) |
| mid-run 批 OOM | `pipeline/ingest.py`:批 embed 异常→classify→`fallback_to_cpu`→同批 CPU 重试;CPU 再失败→terminal CpuFallbackError(无重试环、不回 GPU) | `tests/pipeline/test_ingest_fallback.py` |
| 遥测/SyncRun 表示 | record_device(execution_device∈受控词表,fallback_reason 机器码,fallback_detail 有界)于全部终态路径、活动隔离 | `tests/scripts/test_sync_device.py` |
| OOM 不误判文档质量 | 批失败统一 raise→run failed;error_summary 含 `…after cuda_oom…` 资源原因;文档不单点记质量失败;fallback 业务成功≠health Severe(#21 侧收口) | `test_ingest_all_isolates_per_doc_failure_then_raises`(OOM 事故模式回归) |
| 在线 Q&A 不被同步破坏 | sync 与 backend 分容器;回退只发生在 sync 进程内模型构造/批处理,不触碰在线 BGE/reranker 生命周期 | 架构事实(fallback.py 模块 docstring + compose 拓扑) |

## 实跑结果
`tests/embedder` 42 passed;#13 语义集(pk/migration/repair/reconcile/ledger-identity)64 passed 合计 **64+42 全绿,零失败**。

## Scope audit / 结论
零代码变更 = 最大最小变更;残余观察(记录不实施):①主动式 VRAM 预检属增强,超出冻结 #14 反应式语义;②CPU 回退期与在线服务的宿主 CPU 争用属部署调优(#23 通道)。
