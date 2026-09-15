# INC-WEB-EMBED-422 REMEDIATION — RemoteSyncEmbedder 客户端切批(candidate)

- **任务**:ISSUE_72_EMBEDDING_BATCH_422_REMEDIATION(Role A FINAL PASS 后授权实现)
- **模式**:CANDIDATE READY — 未并 main、未部署、未出 tag、未触碰生产、未关 #72
- **日期**:2026-09-15
- **分支**:`inc/web-embed-422-20260915`(自 main `f4e67515af810840aa10fa800f0203c2ba290df0` 新建;独立轨,不与 413 候选分支共享 worktree)
- **调查报告**:Issue #72 https://github.com/harryhua-ai/ask-ai/issues/72(根因 FINAL PASS)

---

## 1. Executive finding

授权缝隙 `backend/embedder/remote.py` 内完成矫正:`_RemoteEmbedderClient.embed` 现按与 sync 运行时**同一 Settings 权威**(`settings.embedder_batch_size`,经 `build_remote_sync_embedder(settings)` 注入)把输入切为连续片,顺序 POST、按输入序拼接;空输入零请求直返;任一片失败即整体失败(无部分结果、无客户端重试),服务端错误如实透传并附 `slice i/n, items=m` 上下文;设备真相逐片合并保持单向 GPU→CPU、绝不回退 GPU。`RemoteSyncEmbedder.embed` 公共遥测语义不变(一次公共调用 = 一次 attempt、一次 cpu 批次记账)。**生产代码 delta 恰 = `backend/embedder/remote.py` 一个文件**(scope audit 通过);端点契约、GenerationBuilder 架构、ingest、Admin、#71 全部未触碰。

## 2. 变更文件(scope audit)

| 文件 | 变更 | 性质 |
|---|---|---|
| `backend/embedder/remote.py` | +切批契约(ctor `batch_size`、`embed` 切片循环、`_embed_slice` 单请求体+切片上下文、空输入直返、工厂注入 `settings.embedder_batch_size`、模块 docstring 更新) | **生产代码(唯一)** |
| `tests/embedder/test_remote_batching.py` | 新增 16 测试(切分边界/顺序/完整性/失败语义/回退真相/工厂) | 测试 |
| `tests/pipeline/test_generation_builder.py` | 追加 3 集成测试(A/B/C 暴露路径)+ 端点模拟 | 测试 |
| `reports/inc-web-embed-422-remediation-20260915.md` | 本报告 | 报告 |

无其他生产文件需要变更 —— 授权缝隙即为完整修复点。

## 3. 实现要点(与冻结行为逐条对账)

1. **Settings 权威**:`build_remote_sync_embedder` 传 `batch_size=int(settings.embedder_batch_size)`;ctor 缺省 12 = `backend/config.py` Settings 缺省(无 env 直构造时不越同配置服务端);`batch_size < 1` 构造期 `ValueError` fail-fast。
2. **切分**:78 → 16+16+16+16+14(实测见 §5);连续片、顺序请求、`vectors.extend` 按输入序拼接、返回恰每输入一向量。
3. **空输入**:直返 `[]`、零请求(披露:旧行为为一次注定 422 的空请求;生产零调用方传空 —— GenerationBuilder/repair 均有 `if texts else []` 守卫)。
4. **失败语义**:`_embed_slice` 内 HTTPError/URLError 均包 `RuntimeError` 并附 `(slice {i}/{n}, items={m})`;向量数不符同理。`embed()` 无部分返回;`GenerationBuilder` 原子失败语义零改动(集成 RED 实证 `IngestFailures` 面不变)。
5. **设备/回退**:逐片按响应合并,`device=="cpu" and execution_device!="cpu"` 守卫天然幂等 —— 一旦 CPU,后续片即使(异常地)报 `gpu` 也不回拉(test `test_no_gpu_regression_after_fallback`)。
6. **遥测**:`RemoteSyncEmbedder.embed` 逻辑未动 —— `+=1 attempt` 每公共调用一次;`record_cpu_batch(len(texts))` 按公共调用全量计(35 文本 3 片 → `cpu_batches==1, cpu_docs==35`,实测)。循环位于 client 层、遥测面之下。

**未做**(禁令对账):未提端点限、未改 `/internal/embeddings`、未截断/丢弃、未重排、无并发、无客户端重试、未动模型、未动 GenerationBuilder。

## 4. RED 证据(矫正前,base f4e6751)

**(a) 瑕疵复现脚本(当前代码,旧构造签名)** — `/tmp/prefix_repro_78.py` 转录:

```
REPRODUCED 422: internal embeddings HTTP 422: {"detail": "batch too large: 78 > 16"}
requests observed by endpoint: [78]
```

与生产 `index_generations` failure JSON 逐字一致(wiki ordinal 5,2026-09-14)。

**(b) 提交内 RED 套件 `tests/embedder/test_remote_batching.py`**(实现前运行):

```
16 failed in 0.12s(全部 16 测试)
- 15 项:TypeError: unexpected keyword argument 'batch_size'(API 缺失)
- 1 项行为性 RED:test_factory_passes_settings_batch_size
  assert [5] == [2, 2, 1] —— 真实工厂+真实客户端+传输模拟,5 文本单请求未切分
```

**(c) 集成 RED(stash 矫正后运行,暴露路径真实 422)**:

```
A: IngestFailures: 生成 1 构建失败(embed):batch embed failed:
   internal embeddings HTTP 422: {"detail": "batch too large: 24 > 16"}
   (generation_builder.py:295 —— 正常轮 Phase 2)
B: IngestFailures: 修复代 2 embed 失败(零激活):
   internal embeddings HTTP 422: {"detail": "batch too large: 24 > 16"}
   (generation_builder.py:683 —— repair embed)
C: IngestFailures: 生成 2 构建失败(embed):… 422 … 24 > 16
   (force_rebuild 路由 = reindex P1-E / 413 矫正回退同路径)
3 failed(8 deselected)
```

注:1/16 输入矫正前后均为单请求(非缺陷区);其切分断言([1]/[16])在 RED 轮因 API 缺参同败,GREEN 轮起为无回归锚。

## 5. GREEN 证据与实测切分

```
tests/embedder/test_remote_batching.py            16 passed
tests/embedder/test_remote.py(既有,零改动)      5 passed
tests/embedder/test_fallback.py(既有)           19 passed
→ 40 passed in 0.87s
```

实测请求切分(端点模拟逐请求记录 `len(texts)`):

| 输入 | 观测切分 |
|---|---|
| 1 | `[1]` |
| 16 | `[16]` |
| 17 | `[16, 1]` |
| 35(batch=16) | `[16, 16, 3]` |
| 78(端点强制 ≤16) | `[16, 16, 16, 16, 14]` ✓ 生产类 |
| 35(batch=12,ctor 缺省) | `[12, 12, 11]` |
| 35(工厂注入 settings=2) | `[2, 2, 1]` |
| [](空) | 零请求 |

顺序/完整性:全端点单调序号向量 `t"i" → [float(i)]`,35 输出逐位 `[0.0 … 34.0]` 顺序保持、无丢失、无重复;输入列表快照比对不可变。

集成 GREEN(真实 Postgres + Weaviate,`tests/pipeline/test_generation_builder.py`):

```
test_normal_build_over_16_chunks_via_remote_batching      PASSED(A)
test_repair_generation_over_16_chunks_via_remote_batching PASSED(B)
test_force_rebuild_route_over_16_chunks_via_remote_batching PASSED(C)
→ 全文件 11 passed(8 既有 + 3 新增)
```

集成观测切分:24 chunks(3 docs × 8)→ `[12, 12]`(ctor 缺省 12;`len≥2、每片≤16、sum==chunks_written` 全断言)。

端点防御不变(D):`backend/api/internal_embeddings.py` 与 `generation_builder.py`、`ingest.py` 生产 diff 为零;`tests/api/test_internal_embeddings.py` 3 passed —— 直发 >16 仍 422。**服务端保持防御,客户端成为契约合规。**

## 6. 回归结果

| 套件 | 结果 |
|---|---|
| focused remote embedder(batching+remote+fallback) | **40 passed** |
| GenerationBuilder(真实 PG+Weaviate) | **11 passed** |
| sync(test_sync / sync_lifecycle / progress_realtime / coverage / triggered_by / run_runtime_facts / device) | **75 passed(合并计)** |
| internal embeddings 端点契约 | **3 passed** |
| #45 字符契约(413 同面,`test_ingest_char_contract.py`) | 含于上行 75,**passed** |
| CI 等价全套 `pytest tests/ -q --ignore=tests/api/admin --ignore=tests/scripts/test_sync_db.py --ignore=tests/embedder --ignore=tests/e2e` | 见 §8 附注 |

## 7. 与 b46252c(INC-WEB-EMBED-413 候选)的关系

- **零文件重叠**:`inc/web-embed-413-20260915`(5741039+b46252c)改动 `repair_documents` 规划面(单文本重放资格)、sync_executor、migrations;本矫正只触 `backend/embedder/remote.py` + 测试/报告。
- **`git merge-tree --write-tree` 双分支试合并 = 无冲突**(clean tree `63a98b6`);另以 scratch worktree(413 tip + merge 本候选)执行组合测试,结果见 §8。
- 语义互补:413 分支把超字符契约文档路由 `unrepairable → force_rebuild` 源重建 —— 该回退正是本矫正集成测试 C 的路径;本矫正落地后,该回退在重分块 chunk 数 >16 时不再 422。**双方 accepted 行为均未被修改。**

## 8. 附注 / 残余

- CI 等价全套与组合树测试执行记录见 Issue #72 实现证据评论(数据以此为准)。
- 生产生效仍需经授权部署(本候选不含部署动作);部署前生产 422 行为不变。
- 客户端 `batch_size` 与服务端限值由同一 compose anchor 注入(生产均 16);若未来单服务覆盖 env 造成分歧,超限片仍以 422 如实失败(fail-safe = 现状),不产生静默错配。
- 顺序延迟:超大规模重建(reindex 12k docs)为顺序片请求;属离线维护路径,与授权范围一致(未引入并发)。

—— CANDIDATE READY,待 Role A 复审。
