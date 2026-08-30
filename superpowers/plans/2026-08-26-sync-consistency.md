# 同步一致性修复 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 admin"同步/同步全部"按钮在源码无变更时也能检测并自动补齐 Postgres↔Weaviate 的向量缺口，且写库失败不再被吞成 success。

**Architecture:** 三处修复——(1) `ingest._ingest_doc_batch` 的 replace 回退失败记入 `failed` 列表，让写失败走既有 `raise` 链路；(2) 新增 `vector_consistency` 服务做两级一致性校验；(3) `sync._sync_one` 无变更跳过分支先校验，有缺口则 `fetch_all` 过滤缺口文档重灌并记 `partial`。

**Tech Stack:** Python 3.12, Weaviate v4 Python SDK, SQLAlchemy (asyncpg + psycopg2), pytest, React/TS (admin 前端)

**Spec:** `docs/superpowers/specs/2026-08-26-sync-consistency-design.md`

## Global Constraints

- 绝不使用 `--reindex` 或任何删除 Weaviate collection 的操作（CLAUDE.md 红线）
- 一致性校验只读，不修改数据
- 重灌走确定性 UUID upsert（`backend/pipeline/ingest.py:_deterministic_uuid`，已有向量 replace 覆盖，无向量 insert 新建）
- 不删除孤儿向量（反方向差集只 warning）
- `failed` 与 `partial` 状态都不推进增量窗口（`scripts/sync.py:_last_success_at` 只查 `status=="success"`）
- 后端 `partial` 状态已合法：`backend/api/admin/sync_logs.py:22` 的 status 过滤 pattern 已含 `partial`，勿改
- 全量回归不能破坏（实施时用真实 pytest 输出复核，不写死数量）
- 语言：代码注释、docstring、提交信息用中文简体

---

## Task 1: replace 回退失败诚实上报（ingest 层）

**Files:**
- Modify: `backend/pipeline/ingest.py:484-504`（`_ingest_doc_batch` 的 replace 回退段 + 按 doc 统计段）
- Test: `tests/pipeline/test_ingest.py`（新增 1 个测试）

**Interfaces:**
- Consumes: 现有 `_ingest_doc_batch(self, docs, failed=None)` 的 `failed` 列表参数（已有机制，8-17 提交引入）
- Produces: 无新接口。行为变化：replace 回退失败的对象不再被计为成功，其 doc 记入 `failed` → `ingest_all` 末尾 `raise RuntimeError`。

**背景**：`_ingest_doc_batch` 写库流程是 `insert_many` 失败 → 单条 `replace` 回退。当前 replace 也失败时只 `logger.warning`，不记 `failed`，导致 `success_count = total - n_failed_in_doc` 仍把失败对象算成功，`ingest_all` 不 raise，sync 记 success。这是本次事故"写入失败被吞"的直接根因。

- [ ] **Step 1: 写失败测试**

在 `tests/pipeline/test_ingest.py` 末尾追加（复用文件顶部已有的 `_make_doc` / `_make_embedder` / `_make_weaviate_client`）：

```python
@pytest.mark.unit
def test_ingest_all_raises_when_replace_fallback_fails():
    """insert_many 失败 + replace 回退也失败 → 该 doc 计入 failed → ingest_all raise。

    复现缺陷 1:replace 回退失败只 warn 不计失败,导致 sync 误记 success。
    修复后 replace 失败对象计入 failed,ingest_all 末尾 raise,由 sync 记 failed。
    """
    embedder = _make_embedder()
    client = _make_weaviate_client()
    collection = client.collections.get.return_value
    # insert_many 抛块级异常(触发整块 replace 回退)
    collection.data.insert_many.side_effect = Exception("store is read-only")
    # replace 回退也失败(模拟 Weaviate 只读)
    collection.data.replace.side_effect = Exception("store is read-only")

    pipeline = IngestionPipeline(embedder, client)
    with pytest.raises(RuntimeError, match="灌入失败"):
        pipeline.ingest_all([_make_doc()])
```

- [ ] **Step 2: 跑测试确认失败**

Run: `TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test uv run pytest tests/pipeline/test_ingest.py::test_ingest_all_raises_when_replace_fallback_fails -q`
Expected: FAIL（`RuntimeError` 未抛出，因为 replace 失败只 warn 不记 failed）

> 若本地 postgres 未起，参考 CLAUDE.md 起依赖服务 `docker compose -f deploy/local/docker-compose.yml up -d postgres weaviate` 或仅跑该单测（该测试不碰真实 DB，但 conftest 可能要求 TEST_DATABASE_URL 环境变量存在）。

- [ ] **Step 3: 实现最小修复**

改 `backend/pipeline/ingest.py` 两处。先看当前 `replace` 回退段（约 484-487 行）：

```python
        for fi in failed_idx:  # replace 回退(用预计算向量,不重 embed)
            try:
                self._collection.data.replace(
                    properties=all_props[fi],
                    vector=all_vecs_flat[fi],
                    uuid=all_uuids[fi],
                )
            except Exception as exc2:  # noqa: BLE001
                logger.warning(
                    "replace 回退失败 uuid=%s: %s", all_uuids[fi], str(exc2)[:120]
                )
```

改为（新增 `replace_failed` 集合，把 replace 失败的对象索引也记为失败）：

```python
        replace_failed: set[int] = set()  # replace 回退也失败的对象索引(写库彻底失败)
        for fi in failed_idx:  # replace 回退(用预计算向量,不重 embed)
            try:
                self._collection.data.replace(
                    properties=all_props[fi],
                    vector=all_vecs_flat[fi],
                    uuid=all_uuids[fi],
                )
            except Exception as exc2:  # noqa: BLE001
                logger.warning(
                    "replace 回退失败 uuid=%s: %s", all_uuids[fi], str(exc2)[:120]
                )
                replace_failed.add(fi)
```

再改按 doc 统计段（约 490-504 行），`n_failed_in_doc` 把 replace 失败对象也算入，并把这些 doc 记入 `failed` 列表：

```python
        # 按 doc 统计成功数(insert 成功 + replace 回退成功计成功;replace 也失败计失败)
        for idx, (doc, chunks) in enumerate(doc_chunks):
            o_s, o_e = obj_spans[idx]
            total = o_e - o_s
            n_failed_in_doc = sum(
                1 for i in range(o_s, o_e) if i in failed_idx or i in replace_failed
            )
            success_count = total - n_failed_in_doc
            if failed is not None and n_failed_in_doc > 0:
                # 写库彻底失败(insert 失败且 replace 也失败)→ 记入 failed,由 ingest_all raise
                failed.append(doc.source_id)
            if self._session_factory is not None:
                try:
                    self._upsert_postgres(doc, success_count)
                except Exception as exc:  # noqa: BLE001
                    logger.error("Postgres upsert 失败 doc=%s: %s", doc.source_id, exc)
            logger.info(
                "已索引 %s: %d/%d chunk 成功",
                doc.source_id,
                success_count,
                total,
            )
            results[doc.source_id] = success_count
        return results
```

- [ ] **Step 4: 跑测试确认通过**

Run: `TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test uv run pytest tests/pipeline/test_ingest.py -q`
Expected: PASS（新增测试通过，且 test_ingest.py 其余测试不回归 — 未改返回值结构，`ingest_all` 仍返回 `{source_id: success_count}`）

- [ ] **Step 5: 提交**

```bash
git add backend/pipeline/ingest.py tests/pipeline/test_ingest.py
git commit -m "fix(ingest): replace 回退失败计入 failed,写库失败不再吞成 success"
```

---

## Task 2: 一致性校验器（新服务）

**Files:**
- Create: `backend/services/vector_consistency.py`
- Test: `tests/services/test_vector_consistency.py`

**Interfaces:**
- Consumes: `async_sessionmaker[AsyncSession]`（异步工厂，与 `scripts.sync.py` 的 `_count_documents` 同款）；`IngestionPipeline`（经 `pipeline._client` 取 Weaviate v4 client，经 `pipeline._class_name` 取 collection 名）
- Produces: `VectorGapReport`（frozen dataclass）+ `verify_source_vectors(session_factory, pipeline, source_prefix) -> VectorGapReport`

**关键实现细节**（执行者需知道，spec 已论证）：
- Weaviate v4 的 collection 对象：`pipeline._client.collections.get(pipeline._class_name)`，但 `_ensure_collection` 会惰性建 collection，校验器不建，直接 `collections.get`（已存在）。
- Weaviate `aggregate.over_all(total_count=True, filters=Filter.by_property("source_id").like(f"{source_prefix}*"))`（like 通配符是 `*` 不是 `%`，已实测验证 `like "wiki-documents-local/*"` 返 3961）。sum 级不等时深入：
  - Postgres 精确：`select(Document.source_id, Document.chunk_count).where(Document.source_id.like(f"{prefix}/%"))` — 注意这里 SQL LIKE 用的是 `%`。
  - Weaviate 精确：`collection.iterator(return_properties=["source_id", "chunk_index"])` 迭代该源前缀过滤后的对象，攒成 `source_id` 集合。
- 两级校验用 `type="scene"` 无关，纯数量/差集对比。前缀语义：Postgres 用 `LIKE '{prefix}/%'`（`%`），Weaviate 用 `like '{prefix}/*'`（`*`）——两者通配符不同，勿混。

- [ ] **Step 1: 写失败测试**

创建 `tests/services/test_vector_consistency.py`：

```python
"""向量一致性校验单元测试(纯 mock,无真实 DB / Weaviate)。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.vector_consistency import VectorGapReport, verify_source_vectors


def _make_session_factory(*, scalar=None, rows=None) -> MagicMock:
    """构造 mock 异步 session 工厂。

    ``async with factory() as session:`` → session 为 MagicMock;
    ``await session.execute(...)`` → AsyncMock 返回配置的 scalar/all。
    注意 factory 本身必须是 **MagicMock**(同步调用返回 context manager),
    AsyncMock 的调用返回 coroutine 会破坏 ``async with`` 协议。
    """
    session = MagicMock()
    exec_result = MagicMock()
    if scalar is not None:
        exec_result.scalar.return_value = scalar
    if rows is not None:
        exec_result.all.return_value = rows
    session.execute = AsyncMock(return_value=exec_result)
    session.commit = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = session
    return factory


def _make_pipeline(*, actual_chunks: int, wv_source_ids: set[str]) -> MagicMock:
    """构造 mock IngestionPipeline,返回指定 Weaviate 侧计数与 source_id 集合。"""
    collection = MagicMock()
    collection.aggregate.over_all.return_value.total_count = actual_chunks
    # 精确级:iterator 迭代产出对象(.properties 属性访问,对齐 weaviate v4 真实 API)
    collection.iterator.return_value = [
        MagicMock(properties={"source_id": sid}) for sid in wv_source_ids
    ]
    client = MagicMock()
    client.collections.get.return_value = collection
    pipeline = MagicMock()
    pipeline._client = client
    pipeline._class_name = "Document"
    return pipeline


@pytest.mark.asyncio
async def test_verify_healthy_when_counts_match():
    """汇总级相等 → is_healthy=True,不深入精确级(iterator 不被调用)。"""
    # Postgres SUM(chunk_count) == Weaviate total == 10
    session_factory = _make_session_factory(scalar=10)
    pipeline = _make_pipeline(actual_chunks=10, wv_source_ids=set())

    report = await verify_source_vectors(session_factory, pipeline, "wiki-documents-local")

    assert report.is_healthy is True
    assert report.missing_source_ids == []
    # 精确级不触发:iterator 未调用
    assert pipeline._client.collections.get.return_value.iterator.called is False


@pytest.mark.asyncio
async def test_verify_detects_missing_source_ids_when_counts_differ():
    """汇总级不等 → 深入精确级,差集出 pg 有、Weaviate 无的 source_id。"""
    # Postgres:3 篇文档 SUM=6;Weaviate 实际 3(缺 doc-a 全部 3 chunks)
    pg_rows = [("doc-a",), ("doc-b",), ("doc-c",)]
    session_factory = _make_session_factory(scalar=6, rows=pg_rows)
    # Weaviate 只有 doc-b / doc-c
    pipeline = _make_pipeline(actual_chunks=3, wv_source_ids={"doc-b", "doc-c"})

    report = await verify_source_vectors(session_factory, pipeline, "src")

    assert report.is_healthy is False
    # missing = pg 有而 Weaviate 无的 doc(source_id 完全缺失)
    assert report.missing_source_ids == ["doc-a"]
    # 孤儿(Weaviate 有、pg 无)为 0
    assert report.orphan_count == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/services/test_vector_consistency.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'backend.services.vector_consistency'`）

- [ ] **Step 3: 实现服务**

创建 `backend/services/vector_consistency.py`：

```python
"""Postgres ↔ Weaviate 向量一致性校验。

用于同步"无变更跳过"分支：源码无变更时，不轻信 documents 表有记录就跳过，
而是核对 Weaviate 是否真有对应向量。两级校验：
  1. 汇总级(O(1))：Postgres SUM(chunk_count) vs Weaviate total_count，相等即健康；
  2. 精确级(仅汇总级不等时)：逐 source_id 差集，找出 pg 有、Weaviate 无的缺口。
只读、不修改任何数据（孤儿向量仅 warning，不删）。
"""

import logging
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from weaviate.classes.query import Filter

from backend.db.models import Document

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VectorGapReport:
    """Postgres ↔ Weaviate 一致性校验结果。"""

    expected_chunks: int          # Postgres SUM(chunk_count)
    actual_chunks: int            # Weaviate 该源实际 chunk 数
    missing_source_ids: list[str] = field(default_factory=list)  # pg 有、Weaviate 无
    orphan_count: int = 0          # Weaviate 有、pg 无(仅 warning 不删)

    @property
    def is_healthy(self) -> bool:
        """汇总级相等即视为健康(不深入精确级)。"""
        return self.expected_chunks == self.actual_chunks


async def verify_source_vectors(
    session_factory: async_sessionmaker[AsyncSession],
    pipeline,
    source_prefix: str,
) -> VectorGapReport:
    """校验某数据源在 Postgres 与 Weaviate 间的向量一致性。

    Args:
        session_factory: 异步会话工厂(写 SyncLog / documents 用,与 sync.py 同款)。
        pipeline: IngestionPipeline,经其 ``_client`` / ``_class_name`` 访问 Weaviate。
        source_prefix: 数据源 ID(如 ``"wiki-documents-local"``)。内部按
            ``'{prefix}/%'``(SQL)与 ``'{prefix}/*'``(Weaviate like)前缀匹配。

    Returns:
        VectorGapReport。is_healthy=True 表示无需补齐。
    """
    # 1) 汇总级:Postgres SUM(chunk_count)
    async with session_factory() as session:
        result = await session.execute(
            select(func.coalesce(func.sum(Document.chunk_count), 0)).where(
                Document.source_id.like(f"{source_prefix}/%")
            )
        )
        expected = int(result.scalar() or 0)

    collection = pipeline._client.collections.get(pipeline._class_name)
    agg = collection.aggregate.over_all(
        total_count=True,
        filters=Filter.by_property("source_id").like(f"{source_prefix}/*"),
    )
    actual = int(getattr(agg, "total_count", 0) or 0)

    if expected == actual:
        return VectorGapReport(expected_chunks=expected, actual_chunks=actual)

    # 2) 精确级:差集(pg 有、Weaviate 无)
    async with session_factory() as session:
        result = await session.execute(
            select(Document.source_id).where(
                Document.source_id.like(f"{source_prefix}/%")
            )
        )
        pg_ids = {row[0] for row in result.all()}

    wv_ids: set[str] = set()
    for item in collection.iterator(return_properties=["source_id"]):
        props = item.get("properties", {})
        sid = props.get("source_id")
        if sid:
            wv_ids.add(sid)

    missing = sorted(pg_ids - wv_ids)
    orphans = len(wv_ids - pg_ids)
    if orphans:
        logger.warning(
            "一致性校验:数据源 %s 发现 %d 个孤儿向量(Weaviate 有、Postgres 无),不删除",
            source_prefix,
            orphans,
        )
    return VectorGapReport(
        expected_chunks=expected,
        actual_chunks=actual,
        missing_source_ids=missing,
        orphan_count=orphans,
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/services/test_vector_consistency.py -q`
Expected: PASS（2 个测试通过）

- [ ] **Step 5: 提交**

```bash
git add backend/services/vector_consistency.py tests/services/test_vector_consistency.py
git commit -m "feat(services): 新增向量一致性校验器(二级校验,只读)"
```

---

## Task 3: _sync_one 无变更跳过分支接入校验 + 自愈

**Files:**
- Modify: `scripts/sync.py:252-275`（`_sync_one` 的无变更跳过分支）
- Test: `tests/scripts/test_sync_gap_heal.py`（新建）

**Interfaces:**
- Consumes: `verify_source_vectors(session_factory, pipeline, source_prefix)`（Task 2）；`connector.fetch_all()`（返回 `Iterator[RawDocument]`，`source_id` 在 `RawDocument` 上）；`pipeline.ingest_all(docs)`（Task 1 已使写失败 raise）
- Produces: 行为变化——`_sync_one` 在无变更时校验缺口，有缺口则补灌并记 `status="partial"`。**不改 `_sync_one` 签名**。

**注意**：`_sync_one` 是无 IO 依赖的纯逻辑单元，但内部 `ConnectorRegistry.create` / `pipeline.ingest_all` 涉及真实组件。测试用 `patch` 替换 `ConnectorRegistry.create` 和 `pipeline`（MagicMock）来隔离。`verify_source_vectors` 也 patch 掉（它已在 Task 2 独立测试）。

- [ ] **Step 1: 写失败测试**

创建 `tests/scripts/test_sync_gap_heal.py`：

```python
"""sync._sync_one 无变更跳过分支的自愈逻辑单元测试(patch 隔离)。"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.db.models import SyncLog
from scripts.sync import _sync_one


def _make_cfg(source_id: str = "src") -> MagicMock:
    cfg = MagicMock()
    cfg.id = source_id
    cfg.type = "local_git"
    return cfg


def _make_pipeline() -> MagicMock:
    pipeline = MagicMock()
    pipeline.ingest_all.return_value = {"doc-a": 3}
    return pipeline


@pytest.mark.asyncio
@patch("scripts.sync._count_documents", new_callable=AsyncMock)
@patch("scripts.sync._last_success_at", new_callable=AsyncMock)
@patch("scripts.sync.verify_source_vectors", new_callable=AsyncMock)
@patch("scripts.sync.ConnectorRegistry.create")
async def test_no_change_but_vector_gap_triggers_heal_and_partial(
    mock_create, mock_verify, mock_last_success, mock_count
):
    """无变更 + 一致性校验发现缺口 → fetch_all 过滤缺口补灌,记 partial。"""
    mock_last_success.return_value = datetime(2026, 8, 18, 15, 39, tzinfo=UTC)
    mock_count.return_value = 500           # documents 已有记录(非首次)
    from backend.services.vector_consistency import VectorGapReport
    mock_verify.return_value = VectorGapReport(
        expected_chunks=500, actual_chunks=480, missing_source_ids=["doc-a"]
    )

    connector = MagicMock()
    # fetch_changes 空(无变更);fetch_all 返回缺口文档
    connector.fetch_changes.return_value = iter([])
    from backend.connectors.base import RawDocument
    connector.fetch_all.return_value = iter([
        RawDocument(
            source_id="doc-a", source_type="github", product="x",
            title="a", content="A", url="http://a", metadata={},
            content_hash="h1",
        ),
        RawDocument(  # 非缺口文档,应被过滤掉
            source_id="doc-keep", source_type="github", product="x",
            title="b", content="B", url="http://b", metadata={},
            content_hash="h2",
        ),
    ])
    connector.fetch_deleted.return_value = []
    mock_create.return_value = connector

    pipeline = _make_pipeline()
    session_factory = AsyncMock()
    pipeline._session_factory = None

    await _sync_one(_make_cfg(), pipeline, session_factory, triggered_by="manual")

    # 只对缺口文档重灌(非缺口被过滤)
    called_docs = pipeline.ingest_all.call_args[0][0]
    assert [d.source_id for d in called_docs] == ["doc-a"]
    # SyncLog 写入 partial + error_detail
    written = session_factory.return_value.__aenter__.return_value.add.call_args[0][0]
    assert isinstance(written, SyncLog)
    assert written.status == "partial"
    assert "缺口" in (written.error_detail or "")


@pytest.mark.asyncio
@patch("scripts.sync._count_documents", new_callable=AsyncMock)
@patch("scripts.sync._last_success_at", new_callable=AsyncMock)
@patch("scripts.sync.verify_source_vectors", new_callable=AsyncMock)
@patch("scripts.sync.ConnectorRegistry.create")
async def test_no_change_and_healthy_keeps_success_skip(
    mock_create, mock_verify, mock_last_success, mock_count
):
    """无变更 + 校验健康 → 维持 success + unchanged,不触发 fetch_all。"""
    mock_last_success.return_value = datetime(2026, 8, 18, 15, 39, tzinfo=UTC)
    mock_count.return_value = 500
    from backend.services.vector_consistency import VectorGapReport
    mock_verify.return_value = VectorGapReport(
        expected_chunks=500, actual_chunks=500, missing_source_ids=[]
    )

    connector = MagicMock()
    connector.fetch_changes.return_value = iter([])
    connector.fetch_all.return_value = iter([])  # 不应被调用
    connector.fetch_deleted.return_value = []
    mock_create.return_value = connector

    pipeline = _make_pipeline()
    session_factory = AsyncMock()

    await _sync_one(_make_cfg(), pipeline, session_factory, triggered_by="manual")

    assert not pipeline.ingest_all.called
    written = session_factory.return_value.__aenter__.return_value.add.call_args[0][0]
    assert written.status == "success"
    assert written.items_unchanged == 500
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/scripts/test_sync_gap_heal.py -q`
Expected: 两个测试均 FAIL（当前无变更分支直接 `return`，无校验无自愈；`verify_source_vectors` 未 import）

- [ ] **Step 3: 实现自愈逻辑**

先加 import。在 `scripts/sync.py` 顶部 import 区（约第 62-63 行的 `from backend...` 集群附近）加：

```python
from backend.services.vector_consistency import verify_source_vectors
```

再改无变更跳过分支（约 252-262 行）。当前：

```python
            docs = list(connector.fetch_changes(since))
            if not docs:
                # 区分首次(无 documents 记录)vs 无变更(已有记录)
                existing = await _count_documents(session_factory, cfg.id)
                if existing > 0:
                    # 无变更跳过:不回退全量,不灌入,直接记 SyncLog 返回
                    logger.info(
                        "数据源 %s 无变更,跳过(documents 已有 %d)", cfg.id, existing
                    )
                    log_entry.items_new = 0
                    log_entry.items_unchanged = existing
                    log_entry.finished_at = datetime.now(UTC)
                    log_entry.duration_ms = int((time.monotonic() - start) * 1000)
                    return
                # 首次同步:documents 表无记录,回退到全量拉取
                logger.info("数据源 %s 首次同步,回退到全量拉取", cfg.id)
                docs = list(connector.fetch_all())
```

改为：

```python
            docs = list(connector.fetch_changes(since))
            if not docs:
                # 区分首次(无 documents 记录)vs 无变更(已有记录)
                existing = await _count_documents(session_factory, cfg.id)
                if existing > 0:
                    _handle_no_change(
                        cfg.id, existing, connector, pipeline, session_factory,
                        log_entry, start,
                    )
                    # 无变更路径已内联写 SyncLog 并 return(见 _handle_no_change)
                    return
                # 首次同步:documents 表无记录,回退到全量拉取
                logger.info("数据源 %s 首次同步,回退到全量拉取", cfg.id)
                docs = list(connector.fetch_all())
```

并在模块级（`_compute_since` 之后任意位置）加 helper：

```python
async def _handle_no_change(
    source_id: str,
    existing: int,
    connector,
    pipeline,
    session_factory: Any,
    log_entry: SyncLog,
    start: float,
) -> None:
    """无变更路径:先做向量一致性校验,缺口则 fetch_all 过滤补灌并记 partial。"""
    report = await verify_source_vectors(session_factory, pipeline, f"{source_id}/")
    if report.is_healthy:
        logger.info("数据源 %s 无变更,跳过(documents 已有 %d)", source_id, existing)
        log_entry.items_new = 0
        log_entry.items_unchanged = existing
    else:
        # 有缺口:fetch_all 后只对缺口文档 embed 重灌(幂等 upsert)
        logger.info(
            "数据源 %s 一致性校验:缺口 %d 篇,触发补齐",
            source_id,
            len(report.missing_source_ids),
        )
        missing_set = set(report.missing_source_ids)
        docs = [d for d in connector.fetch_all() if d.source_id in missing_set]
        results = pipeline.ingest_all(docs)  # 写失败仍 raise → 走外层 except 记 failed
        log_entry.status = "partial"
        log_entry.items_new = 0
        log_entry.items_updated = sum(results.values())
        log_entry.error_detail = (
            f"一致性校验发现缺口 {len(report.missing_source_ids)} 篇,已补齐"
        )
    log_entry.finished_at = datetime.now(UTC)
    log_entry.duration_ms = int((time.monotonic() - start) * 1000)
```

> **实现替代**：若不想抽出 helper，也可把上述逻辑直接内联在 `_sync_one` 的 `if existing > 0:` 块内。抽 helper 的好处是 `_sync_one` 保持扁平、`return` 语义清晰、helper 可独立单测。任选其一，测试断言的是行为（SyncLog.status 与 ingest_all 调用），不绑定具体结构。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/scripts/test_sync_gap_heal.py -q`
Expected: PASS（2 个测试通过）

- [ ] **Step 5: 提交**

```bash
git add scripts/sync.py tests/scripts/test_sync_gap_heal.py
git commit -m "feat(sync): 无变更跳过接入一致性校验,向量缺口自动补齐并记 partial"
```

---

## Task 4: 前端 partial 状态展示

**Files:**
- Modify: `admin/src/pages/DataSources.tsx:387-429`（同步完成检测的 useEffect）+ `admin/src/pages/DataSources.tsx:688-691`（最新同步列，可选加徽标）

**Interfaces:**
- Consumes: 后端 `list_data_sources` 返回的 `last_sync_status`（已是 `string`，可能为 `"success" | "failed" | "partial"`）；`last_sync_error`（partial 时为补齐说明）
- Produces: 前端 toast + 可选徽标，把 `partial` 与 `success`/`failed` 区分展示

**注意**：后端 `sync_logs.py:22` 已把 `partial` 纳入合法 status（勿改后端）。前端目前只看 `failed`，其余一律 toast「同步完成」，partial 的"补齐"信息用户看不到——本任务补上。

- [ ] **Step 1: 定位改动点（无独立前端单测，用 tsc + 人工验收）**

前端 `admin/src` 有 vitest 单测，但 `DataSources.tsx` 无对应 `.test.tsx`。本任务以 **`npm run build`（tsc）通过 + 人工验收**为准，不新增单测。

- [ ] **Step 2: 改同步完成检测（partial 分支）**

在 `admin/src/pages/DataSources.tsx` 的 useEffect（约 387-429 行）中，把 `failed` 检测扩展为区分 `partial`。当前逻辑：

```typescript
      if (ts && ts > triggered) {
        // last_sync 推进 → 同步尝试已结束,按 status 区分成功/失败
        if (ds?.last_sync_status === "failed") {
          failed.push({ id, error: ds.last_sync_error ?? null });
        } else {
          completed.push(id);
        }
      }
```

改为增加 `partial` 分支（`partial` 也视为"完成"，但 toast 用 warning 提示补齐）：

```typescript
      if (ts && ts > triggered) {
        // last_sync 推进 → 同步尝试已结束,按 status 区分成功/失败/补齐
        if (ds?.last_sync_status === "failed") {
          failed.push({ id, error: ds.last_sync_error ?? null });
        } else if (ds?.last_sync_status === "partial") {
          partial.push({ id, error: ds.last_sync_error ?? null });
        } else {
          completed.push(id);
        }
      }
```

并在该 useEffect 顶部（`const failed = ...` 附近）加 partial 数组声明：

```typescript
    const partial: { id: string; error: string | null }[] = [];
```

在 `failed` 处理块之后加 partial 处理：

```typescript
    if (partial.length > 0) {
      partial.forEach(({ id, error }) =>
        toast.warning(`同步完成(补齐缺口):${error ?? id}`),
      );
      setSyncingIds((prev) => {
        const next = new Set(prev);
        partial.forEach(({ id }) => next.delete(id));
        return next;
      });
    }
```

- [ ] **Step 3: （可选）在最新同步列加 partial 徽标**

在 `admin/src/pages/DataSources.tsx` 的最新同步 `<TableCell>`（690-691 行）里，`last_sync_status === "partial"` 时在时间旁追加黄色 Badge：

```tsx
              <TableCell>
                <span title={ds.last_sync ?? "暂无同步记录"}>{formatSyncTime(ds.last_sync)}</span>
                {ds.last_sync_status === "partial" && (
                  <Badge variant="secondary" className="ml-2 bg-yellow-500/15 text-yellow-700" >
                    {ds.last_sync_error ?? "已补齐缺口"}
                  </Badge>
                )}
              </TableCell>
```

- [ ] **Step 4: 构建 + 类型检查**

Run: `cd admin && npm run build`
Expected: 构建成功（tsc 通过，无类型错误）。若 `variant="secondary"` 与项目 Badge variant 类型不匹配，改回项目已有的 variant 值（用 `grep` 查 `ui/badge.tsx` 支持哪些 variant）。

- [ ] **Step 5: 提交**

```bash
git add admin/src/pages/DataSources.tsx
git commit -m "feat(admin): 同步完成 toast 区分 partial 补齐状态,最新同步列加黄标"
```

---

## Task 5: 全量回归 + 部署

**Files:** 无代码改动，验证 + 部署。

- [ ] **Step 1: 后端全量测试**

Run:
```bash
TEST_DATABASE_URL=postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test \
  uv run pytest tests/ -q
```
Expected: 全量 PASS，尤其 `tests/pipeline/test_ingest.py`、`tests/scripts/`、`tests/services/` 无回归。（若 CI 环境无 postgres，参考 CLAUDE.md：先起 `docker compose -f deploy/dev/docker-compose.yml up -d postgres weaviate`，且必设 `TEST_DATABASE_URL`，否则 conftest `drop_all` 清开发库——这是红线。）

- [ ] **Step 2: 后端 lint + 格式**

Run:
```bash
ruff check . && ruff format --check .
black --check . && isort --check .
```
Expected: 通过（line-length=100）。若有格式问题，`ruff format .` + `black .` + `isort .` 再 check。

- [ ] **Step 3: 前端单测 + 构建**

Run:
```bash
cd admin && npm run test
cd admin && npm run build
```
Expected: vitest 通过 + build 通过。

- [ ] **Step 4: push 到 main 触发 CI**

```bash
git push origin main
```
CI `.github/workflows/build-image.yml` 会：test → build widget+admin → build GPU 镜像 → push GHCR `ghcr.io/harryhua-ai/ask-ai:latest`。

- [ ] **Step 5: 部署到 tesla-t4（纯镜像，禁源码挂载）**

等 CI 完成后（镜像 tag 更新为本次 commit）：
```bash
ssh tesla-t4 'cd ~/ask-ai/deploy/prod && ./update.sh'
```
`update.sh` = pull + 滚动更新 + 健康检查 `localhost:18000`。

- [ ] **Step 6: 验收（交用户实测）**

部署后请用户在 admin 点「同步全部」，按 spec 验收标准核对：
1. 4 个缺口源（wiki-documents-local / neomind-local / ne503-sdk-local / woocommerce-mall）出现 `partial` 状态 + error_detail 显示补齐
2. 抽查 wiki NE503 product-wiring：Weaviate 命中 4/4（之前 0/4）
3. 第二次同步：全部源 `success` + unchanged（缺口已清）

---

## Self-Review 结果

- **Spec 覆盖**：缺陷 1 → Task 1；缺陷 2+3 → Task 2（校验器）+ Task 3（接入自愈）；partial 展示 → Task 4；测试/部署 → Task 5。全部覆盖。
- **占位符**：无 TBD/TODO。每个 Task 含真实代码/测试。
- **类型/签名一致**：`verify_source_vectors(session_factory, pipeline, source_prefix)` 在 Task 2 定义、Task 3 调用签名一致；`VectorGapReport` 字段 `expected_chunks/actual_chunks/missing_source_ids/orphan_count/is_healthy` 在 Task 2 定义、Task 3 测试引用一致；`_sync_one` 签名未改，helper `_handle_no_change` 参数完整。