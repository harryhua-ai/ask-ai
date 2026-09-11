# TB-P1 — REINDEX / REMOTE EMBEDDER BATCH CORRECTIVE 执行报告

Final verdict: **TB-P1-REMOTE-EMBEDDER-BATCH-CORRECTIVE = CANDIDATE READY**

(仅客户端传输切批矫正;零生产触碰、零部署、零生成激活、零服务端限界
变更、零 P1 语义变更;待 Role A 独立评审)

- 候选分支:**`trace-b/remote-embedder-batch-corrective-20260912`**
  (RED `0880fb7` → 实现 `5d73620` → 本报告;基线 = origin/main `57717ea`)
- 执行窗口:2026-09-12
- 生产事实背景:v1.6.1 @ `98ab795`(TB-P1 PRODUCTION = PARTIAL,唯一
  阻断 = Phase 8C 非破坏重建,见
  `tb-p1-production-migration-runtime-acceptance.md` §17)

---

## 1. Current Main Baseline

- 任务起点 origin/main = **`57717ea`**(TB-P1 续执行终局报告提交;其父
  `98ab795` = v1.6.1 发布树)。本地与 origin 一致,工作树清洁,零漂移。
- 候选分支自该点创建,含且仅含 3 个新提交(RED / fix / 本报告),main 未动。

## 2. Exact Root Cause(代码级,与生产实证一致)

1. `backend/pipeline/ingest.py` `_ingest_doc_batch`(≈L774-782)把 ≤64 doc
   的全部 chunk 文本**拼平为一个逻辑列表**,单次调用
   `self._embedder.embed(all_texts)`(注释假设「embedder 内部按 batch_size
   批处理」)——该假设对**本地** embedder 成立(`_make_embedder_factory`
   把 `settings.embedder_batch_size` 传入 embedder 构造,内部切批)。
2. `backend/embedder/remote.py` `RemoteSyncEmbedder.embed` →
   `_RemoteEmbedderClient.embed` 把**整个逻辑列表直发单次 HTTP 请求**
   (零客户端切批)。
3. 服务端 `backend/api/internal_embeddings.py`(L46-52)按
   `settings.embedder_batch_size`(生产 `EMBEDDER_BATCH_SIZE=16`)强制
   422:`batch too large: 488 > 16`。

生产实证(09-11,验收报告 §17):`neomind-dashboard-local --reindex`
16 篇 → 488 chunk 单批 → 生成 1 构建失败;全 15 源均超界(最小 93
chunk);潜伏史 = 远程嵌入运行时上线后生产仅跑过小增量,`--reindex`
是首个大批次消费者。失败代 fail-safe 隔离已实证(gen1 failed / 零激活 /
零对象写入 / collection 未删 / 在服 gen0 连续)。

## 3. RED Evidence

- 提交 **`0880fb7`**:新增 `tests/embedder/test_remote_batching.py`,
  13 例批切契约全 RED——失败形态 =
  `TypeError: _RemoteEmbedderClient.__init__() got an unexpected keyword
  argument 'batch_size'`(能力不存在,13 failed / 0.12s,输出在案)。
- 测试矩阵(对应任务 12 例 + 集成回归):
  | # | 用例 | 断言核心 |
  | --- | --- | --- |
  | 1 | N<B(5/16) | 恰 1 次传输请求,载荷逐项一致 |
  | 2 | N==B(16/16) | 仍 1 次请求(不多切) |
  | 3 | N==B+1(17/16) | 恰 2 次,批尺寸 [16,1] |
  | 4 | 生产规模 488/16 | 31 次调用(30×16+8),每次 ≤16,总量 488 零丢失 |
  | 5 | 跨批顺序 | 应答向量编码全局序号,输出序 = 输入序(50 文本) |
  | 6 | 计数守恒 | 489 文本输出 489 向量 |
  | 7 | 空输入 | 不切批,单请求 `{"texts": []}` 原样到传输层(既有语义) |
  | 8 | 首批失败 | RuntimeError(HTTP 503)抛出;fail-fast 零后续批 |
  | 9 | 中批失败 | RuntimeError;成功首批不构成部分成功聚合 |
  | 10 | 末尾短批 | [16,16,3] 收尾;计数+顺序成立 |
  | 11 | 真实向量形状 | 1024 维 np.float32 跨批拼接;形状/dtype/顺序 |
  | 12 | 调用方零预切(集成回归,生产缺陷类复现) | fake 服务端 `server_batch_limit=16`(超界即 422,复现生产行为);`RemoteSyncEmbedder.embed(488 文本)` 单逻辑调用全链成功,31 批恒 ≤16,零 422 |
  | + | 构造布线 | `build_remote_sync_embedder` 以 `settings.embedder_batch_size`(=16)实例化客户端 |

- GREEN 期两处**测试装置自误**修正(实现未因之改动):fake 应答向量
  长度误为固定 4 维(与 dimension=1024 断言矛盾)→ 按 dimension 生成;
  monkeypatch `__init__` 返回实例违反 Python 协议 → 改 Spy 子类捕获。

## 4. Implementation Delta

改动面 = **恰 2 文件,+36/−9**(git diff --stat):

1. `backend/embedder/remote.py`(+32/−4):
   - `_RemoteEmbedderClient.__init__` 新增 `batch_size: int | None = None`
     (校验:非 None 时必须正整数,否则 ValueError);
   - `embed()` 重命名为传输层 `_embed_once()`(逐字节保留原请求/错误/
     设备遥测/向量数校验语义);新 `embed()` = 切批器:
     `None 或 len ≤ B → _embed_once(texts)`(空输入与单批自然落入既有
     单请求路径,零特判);否则 `range(0, N, B)` 串行
     `_embed_once(texts[start:start+B])` 按序 `extend`;
   - `build_remote_sync_embedder`:布线
     `batch_size=int(settings.embedder_batch_size)`;
   - 模块与类 docstring 同步为「客户端切批 + 服务端 422 兜底」。
2. `tests/embedder/test_remote_batching.py`(新增,13 例,§3)。

**未触碰**:`_ingest_doc_batch` / GenerationBuilder / 生命周期·版本·生成
语义 / reindex 编排 / Weaviate 写语义 / 服务端限界 / 重试架构 /
排序检索 / 引用 / 迁移模型 —— 远程客户端边界充分,无需扩大(未触发
STOP 条款)。

## 5. Batching Algorithm(冻结语义逐条对应)

```
embed(texts):
    texts = list(texts)                      # 防御性拷贝
    if batch_size is None or len(texts) <= B: return _embed_once(texts)
    vectors = []
    for start in range(0, len(texts), B):
        vectors.extend(_embed_once(texts[start:start+B]))   # 串行,按序
    return vectors
```

不变量逐条:_embed_once 返回数恒等于请求数(既有校验保留)→ 输出数=
输入数;`extend` 顺序拼接 + 切片保序 → 输出序=输入序、零丢失零重复、
零跨批重排;每次传输载荷 ≤B;空输入走 `_embed_once([])` = 既有单请求
行为;N≤B 单批零行为变化(同一函数体);任一批 HTTPError/URLError →
原样 raise(无捕获、无聚合、无重试语义变更)→ 生成构建保持 failed、
在服代不变;部分结果仅在全部批次成功后聚合返回。

## 6. Configuration Source

**唯一权威配置 = `settings.embedder_batch_size`**(backend/config.py;
生产 .env `EMBEDDER_BATCH_SIZE=16`,服务端 422 强制同源)。布线点唯一
(`build_remote_sync_embedder`,scripts/sync.py 唯一生产消费入口)。
**未硬编码 16,未引入第二配置源**;构造参数默认 `None` 仅保留直构测试
的 legacy 语义(生产构造恒显式传入)。

## 7. GREEN Results

| 层 | 结果 |
| --- | --- |
| RED(实现前) | 13/13 failed(`0880fb7`,TypeError 批切能力缺失) |
| 定向 embedder(含既有 6 例遥测/错误语义回归) | **61 passed / 0 failed** |
| 生成重建/投影重建/sync 生命周期 + P1 门(tests/pipeline/test_generation_builder + test_projection_rebuild + test_sync_lifecycle + tests/db 全部) | **55 passed / 0 failed** |
| 全量后端回归(`pytest tests/`) | **2434 passed / 7 skipped / 0 failed**(114s) |
| Project Automation 套件(tests/project_automation) | **107 passed / 0 failed**(本候选零 PA 文件触碰) |
| ruff(两改动文件) | **All checks passed** |

## 8. Scope Audit(逐项证明)

- **零生产触碰**:本任务全程零 SSH、零生产请求、零部署触发(生产仍
  v1.6.1 @ 98ab795);
- **零生成激活**:无任何对生产 generations/versions/Weaviate 的写路径
  执行;测试全部在本地 fixture(真实本地 PG/Weaviate 容器)运行;
- **零服务端批限变更**:`backend/api/internal_embeddings.py` 字节未动,
  `EMBEDDER_BATCH_SIZE` 语义不变(仍 16,客户端现与之对齐);
- **零 P1 生命周期语义变更**:lifecycle/builder/projection/GC/migration
  源码与测试零 diff(55 例门测试复绿为证);
- **零迁移变更**:`scripts/migrate_p1_*.py`、`deploy/prod/migrations.json`
  零触碰;
- **零无关性能优化**:diff 仅切批器 + 布线 + docstring;`_embed_once`
  为原 `embed` 体逐字节平移(除函数名),无重试/并发/缓存引入;
- **禁域未触碰**:`_ingest_doc_batch`、GenerationBuilder、reindex 编排、
  Weaviate 写语义、排序/引用/迁移模型零 diff;
- main 分支未动(`57717ea`),tag v1.6.0/v1.6.1 未动。

## 9. Candidate

- 分支:**trace-b/remote-embedder-batch-corrective-20260912**
  - `0880fb7` test(embedder): RED 13 例批切契约
  - `5d73620` fix(embedder): 客户端切批 + 唯一配置布线(GREEN 全绿)
  - 本报告(docs,add -f)
- 基线:origin/main `57717ea`;ahead 3 / behind 0。

---

TB-P1-REMOTE-EMBEDDER-BATCH-CORRECTIVE = CANDIDATE READY
(就此停止,待 Role A 独立评审;未部署)
