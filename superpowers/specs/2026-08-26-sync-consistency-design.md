# 同步一致性修复 — 设计文档

> **问题**:admin "同步全部"按钮触发后，增量同步跳过"无变更"源，但 Weaviate shard 只读期间写入失败被吞，导致 Postgres 有记录、Weaviate 无向量的缺口（~408 篇）永不自愈。sync_log 永远 status=success，运维不可见。

**目标**:同步按钮确保内容最新 + 向量索引完整，含历史缺口自动补齐。

**架构**:双管齐下——(1) 修 `ingest` 的 replace 回退失败静默上报，让写失败走既有 `failed` 机制；(2) 在 sync 无变更跳过分支嵌入一致性校验器，发现缺口时 `fetch_all` 过滤缺口文档自动补齐，记 `partial` 状态。

**Tech Stack**:Python 3.12, Weaviate v4 Python SDK, SQLAlchemy, pytest

---

## 全局约束

- 绝不使用 `--reindex` 或任何删除 Weaviate collection 的操作（CLAUDE.md 红线）
- 一致性校验只读，不修改数据
- 重灌走确定性 UUID upsert（已有向量 replace 覆盖，无向量 insert 新建）
- 不删除孤儿向量（反方向差集只 warning）
- `failed` 与 `partial` 状态都不推进增量窗口（`_last_success_at` 只查 `status="success"`）
- 不破坏现有全量回归（admin 76 + 非 admin 391，实施时用真实 pytest 输出复核）

---

## 缺陷分析

### 缺陷 1:replace 回退失败被静默吞掉

`ingest.py:_ingest_doc_batch` 的写库流程：`insert_many` 失败 → 单条 `replace`
回退。`replace` 也失败时**只 `logger.warning`，不记入 `failed` 列表**，导致：

- `success_count = total - n_failed_in_doc`（replace 回退的"已尝试覆盖"仍算成功）
- `failed` 列表为空 → `ingest_all` 末尾不 `raise`
- `sync.py` 记 `status=success`，窗口推进，且永远不知道向量没写进去

> 注：`ingest_all` **已有**"失败 doc → `failed` 列表 → `raise RuntimeError` →
> sync 记 `failed`"的机制（8-17 提交）。缺陷 1 只是 replace 回退失败这条
> 细分路径没接进该机制。

### 缺陷 2:github/local_git SHA 跳过无一致性检查

`github.py` `_remote_has_updates` 返 False 时 `fetch_changes` 不 yield →
`sync.py` `existing>0` 直接跳过，不检查 Weaviate 是否真的有向量。

### 缺陷 3:缺口无自愈

1+2 叠加 → 408 篇缺口。Postgres 有记录、Weaviate 无向量的文档，后续同步永久跳过。

---

## 设计

### 数据流与状态机（核心）

```
同步某源 _sync_one:
  fetch_changes(since)
    ├─ 有 docs → ingest_all(docs)
    │     ├─ 成功                  → status=success（正常）
    │     └─ 写失败(replace 也失败) → ingest_all raise → status=failed
    │          （窗口不推进，下次重试同一窗口 ← 缺陷 1 修复生效点）
    └─ 无 docs(无变更) → existing>0?
          └─ verify_source_vectors   ← 缺陷 2 修复生效点
                ├─ 健康     → status=success + unchanged（正常跳过）
                └─ 有缺口   → fetch_all 过滤缺口 docs → ingest_all(缺口docs)
                      ├─ 成功 → status=partial（已补，下轮自确认）← 缺陷 3
                      └─ 失败 → ingest_all raise → status=failed
```

**两个非 success 状态的语义**（spec 必须区分，实施时不可混）：

| 状态 | 触发 | 含义 | 下一轮行为 |
|---|---|---|---|
| `failed` | 写库真失败（embed / replace 也失败） | 有真实错误，需重试 | 窗口不推进，重试同一窗口 |
| `partial` | 一致性校验发现缺口并补灌**成功** | 补了历史缺口，需自确认 | 窗口不推进，下轮校验健康 → 转 success |

两者都依赖 `_last_success_at` 只查 `status=="success"` 的既有逻辑（01fb513），
零新增状态管理。

### 一致性校验器

**新文件**: `backend/services/vector_consistency.py`

```python
@dataclass(frozen=True)
class VectorGapReport:
    """Postgres ↔ Weaviate 一致性校验结果。"""
    expected_chunks: int        # Postgres SUM(chunk_count)
    actual_chunks: int          # Weaviate 该源实际 chunk 数
    missing_source_ids: list[str]  # pg 有、Weaviate 无的 source_id
    orphan_count: int           # Weaviate 有、pg 无(仅 warning,不删)
    is_healthy: bool            # 汇总级相等 = 健康

async def verify_source_vectors(
    session_factory: async_sessionmaker[AsyncSession],
    pipeline: IngestionPipeline,   # Weaviate 从 pipeline._client 取(不新增公开 API)
    source_prefix: str,
) -> VectorGapReport:
    """两级校验。

    1. 汇总级(O(1)):
       - Postgres: SUM(chunk_count) WHERE source_id LIKE '{prefix}/%'
       - Weaviate: aggregate.over_all(total_count=True,
                      filter=source_id like '{prefix}/*')
       - 相等 → is_healthy=True, 直接返回(不深入)

    2. 精确级(仅汇总级不等时才执行):
       - Postgres: 逐 doc 的 (source_id, chunk_count)
       - Weaviate: cursor 迭代该源全部对象的 source_id
       - 差集 → missing_source_ids(pg 有、wv 无)+ orphan_count(wv 有、pg 无)
    """
```

### 写失败诚实上报

**修改**: `backend/pipeline/ingest.py` `_ingest_doc_batch`（**不改返回值**）

`replace` 回退失败的对象，从成功计数中扣除，并把其 doc 记入 `failed` 列表：

```python
# 现状(约 484-495 行):
for fi in failed_idx:  # replace 回退
    try:
        self._collection.data.replace(...)
    except Exception as exc2:
        logger.warning("replace 回退失败 uuid=%s: %s", ...)  # 只 warn,漏报

# 修改后:
replace_failed: list[int] = []
for fi in failed_idx:
    try:
        self._collection.data.replace(...)
    except Exception as exc2:
        logger.warning("replace 回退失败 uuid=%s: %s", ...)
        replace_failed.append(fi)          # 新增:记入失败

# 统计时(约 498-504 行):success_count 扣除 replace_failed,
# 且 replace_failed 对应的 doc 记入 failed 列表 → ingest_all 末尾 raise。
```

**为什么不改返回值**：`ingest_all` 已有 `failed` 列表 → `raise` 的完整链路，
只需把 replace 失败这条细分路径接进去。改返回结构会波及 `tests/test_ingest.py`
三处断言 + `sync.py` 统计逻辑，改动面大无收益。

### 自愈逻辑

**修改**: `scripts/sync.py` `_sync_one` 无变更跳过分支（约 254-260 行）

```python
if not docs:
    existing = await _count_documents(session_factory, cfg.id)
    if existing > 0:
        report = await verify_source_vectors(session_factory, pipeline, f"{cfg.id}/")
        if report.is_healthy:
            # 无缺口:正常跳过(与现行为一致)
            log_entry.items_unchanged = existing
        else:
            # 有缺口:fetch_all + 流过滤,只对缺口文档 embed 重灌
            logger.info("数据源 %s 一致性校验:缺口 %d 篇,触发补齐",
                        cfg.id, len(report.missing_source_ids))
            missing_set = set(report.missing_source_ids)
            docs = [d for d in connector.fetch_all() if d.source_id in missing_set]
            results = pipeline.ingest_all(docs)   # 失败仍走 raise → failed
            log_entry.status = "partial"
            log_entry.items_updated = sum(results.values())
            log_entry.error_detail = f"一致性校验发现缺口 {len(report.missing_source_ids)} 篇,已补齐"
```

**为什么 fetch_all + 流过滤**(而非全量重灌或按单篇拉取):
- `fetch_all` 的贵在 embed 阶段(缺口的原 embed 已存 pg,重灌才触发);文件
  遍历/API 拉取相对便宜
- 无需给 connector 加按 source_id 拉单篇的新接口(`source_id` 就在
  `RawDocument` 上,集合过滤即可)
- 确定性 UUID 幂等 upsert,误判只覆盖同内容,无副作用

**partial 的一轮性**:heal 成功记 `partial` → 下轮汇总级校验发现健康 →
恢复 `success`+unchanged。partial 不会常驻 UI,且强制下轮自确认。

### partial 状态展示

**修改**: admin 数据源管理页 / SyncLog 徽标组件

`status="partial"` → 黄色徽标，hover 显示 `error_detail`（补齐说明）。
需检查前端对未知 status 的兜底渲染（SyncLog.status 是 String(20) 无枚举
约束，加 "partial" 无 schema 迁移）。

### 已知局限(声明,不阻塞)

1. **部分写入盲区**:部分失败时 `_upsert_postgres(doc, success_count)` 会把
   pg.chunk_count 降级为实际写入数 → 汇总级 SUM 恰等 → 检测不到
   "N chunk 只写部分"。本次事故实测是全失败(0/N)，汇总级可抓住；部分写入
   跨批次边界是理论边缘场景，暂不处理。
2. **孤儿向量**（Weaviate 有、pg 无）：反方向差集不自动删除（红线不删向量），
   仅 warning + `orphan_count` 入报告，供人工评估。

### 文件改动清单

| 文件 | 操作 | 内容 |
|---|---|---|
| `backend/services/vector_consistency.py` | 新建 | 一致性校验器 |
| `backend/pipeline/ingest.py` | 修改 | replace 回退失败 → failed 列表（不改返回值） |
| `scripts/sync.py` | 修改 | 无变更跳过 → 校验+自愈，记 partial |
| `admin/src/...` | 小改 | partial 状态徽标 |
| `tests/` | 新增 | 见下方测试计划 |

---

## 测试计划

### 单元测试（TDD,先红后绿）

- `tests/services/test_vector_consistency.py`
  - 汇总级相等 → is_healthy=True（不调用精确级）
  - 汇总级不等 → 精确级差集正确（missing + orphan 分开）
- `tests/pipeline/test_ingest.py` 增补
  - replace 回退失败 → 该 doc 进 failed → ingest_all raise
- `tests/scripts/test_sync_gap_heal.py`（或并入现有 sync 测试）
  - mock fetch_changes 空 + verify 返回缺口 → fetch_all 过滤 + partial
  - mock verify 健康 → 维持 success + unchanged 跳过
- 既有回归：`pytest tests/ -q` 全量不破坏（实施时用真实输出复核，不写死数列）

### 验收标准

1. 部署后 admin 点"同步全部" → 4 个缺口源出现 `partial` + error_detail 显示补齐
2. 抽查 wiki NE503 product-wiring：Weaviate 命中 4/4（之前 0/4）
3. 第二次同步 → 全部源 `success` + unchanged（缺口已清）