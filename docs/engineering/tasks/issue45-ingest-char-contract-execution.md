# ISSUE #45 实施执行报告 —— 文档级灌入失败诊断 + 字符契约对齐 + 自愈解锁

- 日期:2026-09-10
- 分支:`fix/45-ingest-char-contract`(自 main `03e6c57` 切出)
- 状态:CANDIDATE READY(未合并、未部署,待 Role A 独立评审)
- RCA:见 issue #45 评论(2026-09-10,CONFIRMED;生产只读 + 代码 + 本地复现)

## 1. 根因(已证实)

部署 env `EMBEDDER_MAX_LENGTH=1024`(字符)使内部嵌入端点对任一超长 text 显式 413;
分块器按 **token**(600)封顶、不感知字符契约;sync 嵌入客户端原样投递。
website-camthink 两个页面 **全部 chunk 超 1024 字符**(本地以仓库管道复现:
2437/2841/1514 与 2697/1162)→ 整文档必败;09-03 起每小时 cron 无效重试
(当前错误文案建议的「需重试」对该类失败永不生效)。

## 2. 冻结契约与落实(4 项)

| # | 契约 | 实现 |
| --- | --- | --- |
| 1 | 灌入边界执行嵌入字符契约 | `ingest.py::_enforce_char_limit`:切分后、embed 前,超限 chunk 按字符上限确定性硬切;切片继承父 chunk 语义元数据并全局重编 chunk_index —— 确定性 UUID/幂等覆盖/prune 全部基于最终 chunk 列表。`IngestionPipeline(max_chunk_chars=...)` 新参,None=旧行为;`scripts/sync.py` 传 `settings.embedder_max_length`(与服务端同源配置,生产 env 即刻生效,零生产改动) |
| 2 | 文档级失败结构化 | `DocFailure(source_id, stage, error_class, retryable, detail)`;4 处失败收集点全部结构化(CHUNK/EMBED/INDEX 词表复用);`IngestFailures(RuntimeError)` 携带 `.failures`,消息文本含逐文档明细行 → SyncLog.error_detail/SyncRun.error_summary 零签名变更即诊断化 |
| 3 | 可重试分类 | `classify_ingest_failure`:HTTP 413→`permanent_data_too_large`(false)、422→`permanent_config`(false)、unreachable/5xx/timeout→`retryable_transport`(true)、默认 `error`(true)。操作员从此可区分「重试有效/无效」,不再被「需重试」误导 |
| 4 | 自愈解锁(不遮蔽) | 零成功写不再 upsert 账本(批量路径 + 单文档路径):既有行保留原 chunk_count(缺口对 `verify_source_vectors`/refill 自愈可见),首灌失败不留 chunk_count=0 伪空文档行 |

另有 `scripts/sync.py::_sync_one`:`IngestFailures` → `SyncRun.counters.docs_failed` /
`docs_failed_retryable`(零迁移)。

## 3. 明确不做(边界)

- 不加死信队列、不加自动重试机器(分类是诊断,不是重试策略);
- 不改恢复调度 §14 边界(进程级恢复原样);
- 不改生产 env / 不触发生产同步(修复合入后的首轮 cron 即应自愈两个页面:
  字符契约对齐后 413 消失,窗口 lastmod 重抓)。

## 4. 测试

新增 `tests/pipeline/test_ingest_char_contract.py`(12 条):
- `_enforce_char_limit`:None/未超限 noop;超限无损切片;index/total 重编;父元数据与字符偏移保持;
- `classify_ingest_failure`:413/422/transport/default 四类;
- 端到端:严格 413 embedder + `max_chunk_chars` → 灌入成功且 embed 不收到超限文本;
- 端到端:不传上限(旧行为)→ `IngestFailures.failures` 结构化断言(permanent/retryable=false/stage=EMBED/明细含 413);
- 账本守护(真实测试库,与 ledger-identity 同模式):全失败保留既有行 chunk_count=5;首灌全失败不落 0 行;全成功照常 upsert;
- 夹具自清理(doc/% 前缀),不污染共用测试库。

全量后端:**2202 passed, 8 skipped**(基线 2190 + 新增 12;ingest 邻接套件 691 绿单独复跑)。

## 5. 候选

- 分支:`fix/45-ingest-char-contract` @ <push 后补>
- 变更面:`backend/pipeline/ingest.py`、`scripts/sync.py`、`tests/pipeline/test_ingest_char_contract.py`、本报告
- 交接:待 Role A 独立评审;与 `fix/34-…` 预期在 `scripts/sync.py` 有一处小相邻(不同函数),无语义冲突
