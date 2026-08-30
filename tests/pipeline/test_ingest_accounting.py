"""ingest 批量写入记账测试(P1-RES D4 缺陷回归,Task 1)。

背景:写入成功计数曾依赖已废弃的 ``result.all_responses``(v4 仅保留
末尾 ``MAX_STORED_RESULTS`` 条,超限丢弃最旧条目)→ 失败对象被静默
记成功、replace 回退不触发。迁移后统一读官方 ``result.errors``
(``Dict[原始下标, ErrorObject]``,键即对象在本次 insert_many 中的下标)。

本文件锁定:
1. 部分对象失败(errors 含该下标)→ failed 检出 + replace 回退触发;
2. replace 回退也失败 → 计数真实回落(不虚报成功);
3. all_responses 截断/缺失场景下记账依然正确;
4. 全部成功路径语义不变(replace 不被触发)。
"""

from unittest.mock import MagicMock

from weaviate.collections.classes.batch import BatchObjectReturn

from backend.connectors.base import RawDocument
from backend.pipeline.ingest import IngestionPipeline


def _make_doc(**overrides: object) -> RawDocument:
    """构造默认 RawDocument(1 chunk),允许测试覆盖字段。"""
    defaults: dict[str, object] = {
        "source_id": "test/1",
        "source_type": "github",
        "product": "ne503",
        "title": "Test",
        "content": "NE503 specs",
        "url": "https://github.com/test",
        "metadata": {"path": "README.md"},
        "content_hash": "abc123",
    }
    defaults.update(overrides)  # type: ignore[arg-type]
    return RawDocument(**defaults)  # type: ignore[arg-type]


def _make_embedder(dim: int = 1024) -> MagicMock:
    """构造按请求数量返回向量的 MagicMock embedder(支持跨 doc 批嵌入)。"""
    import numpy as np

    emb = MagicMock()
    emb.dimension = dim
    emb.embed.side_effect = lambda texts: [np.array([0.1] * dim) for _ in texts]
    return emb


def _make_client() -> MagicMock:
    """构造 MagicMock Weaviate client(insert_many 默认全成功)。"""
    client = MagicMock()
    collection = MagicMock()
    client.collections.get.return_value = collection
    results = MagicMock()
    results.objects = []
    collection.query.hybrid.return_value = results
    return client


def _batch_return(errors: dict[int, object], uuids: dict[int, object]) -> BatchObjectReturn:
    """构造真实 BatchObjectReturn:_all_responses 恒空(模拟废弃属性截断/缺失)。"""
    return BatchObjectReturn(
        _all_responses=[],
        errors=errors,  # type: ignore[arg-type]
        uuids=uuids,  # type: ignore[arg-type]
        has_errors=bool(errors),
    )


def test_partial_failure_triggers_replace_and_real_count():
    """errors 含下标 0 → failed 检出、replace 回退触发、回退成功计成功。"""
    embedder = _make_embedder()
    client = _make_client()
    collection = client.collections.get.return_value
    collection.data.insert_many.return_value = _batch_return(errors={0: MagicMock()}, uuids={})

    pipeline = IngestionPipeline(embedder, client)
    count = pipeline.ingest_document(_make_doc())

    collection.data.replace.assert_called_once()
    assert count == 1  # replace 成功 → 该 chunk 计成功


def test_replace_failure_counts_real_failure_not_false_success():
    """errors 检出失败 + replace 回退也失败 → 计数真实回落为 0(不虚报成功)。

    D4 缺陷场景:旧行为(all_responses 截断/缺失)下 failed 恒空,
    此处会假报 1;迁移后必须返回 0。
    """
    embedder = _make_embedder()
    client = _make_client()
    collection = client.collections.get.return_value
    collection.data.insert_many.return_value = _batch_return(errors={0: MagicMock()}, uuids={})
    collection.data.replace.side_effect = Exception("store is read-only")

    pipeline = IngestionPipeline(embedder, client)
    count = pipeline.ingest_document(_make_doc())

    assert count == 0  # 真实失败计数:insert 失败 + replace 也失败


def test_success_path_semantics_unchanged():
    """全部成功(errors 空)→ 不触发 replace,计数不变(成功路径语义保持)。"""
    import uuid as uuid_mod

    embedder = _make_embedder()
    client = _make_client()
    collection = client.collections.get.return_value
    collection.data.insert_many.return_value = _batch_return(
        errors={}, uuids={0: uuid_mod.UUID(int=0)}
    )

    pipeline = IngestionPipeline(embedder, client)
    count = pipeline.ingest_document(_make_doc())

    assert count == 1
    collection.data.replace.assert_not_called()


def test_ingest_all_block_offset_accounting():
    """ingest_all 跨 doc 批:块内 errors 原始下标 + 块偏移 → 回退命中正确对象。

    两个 doc 各 1 chunk,同一 insert_many 块;errors={0: err}(块内下标 0
    = 第一个 doc 的 chunk)→ 仅第一个对象走 replace,且 uuid 对应 doc1。
    """
    import uuid as uuid_mod

    embedder = _make_embedder()
    client = _make_client()
    collection = client.collections.get.return_value
    collection.data.insert_many.return_value = _batch_return(errors={0: MagicMock()}, uuids={})

    pipeline = IngestionPipeline(embedder, client)
    results = pipeline.ingest_all(
        [_make_doc(source_id="test/1"), _make_doc(source_id="test/2", content_hash="h2")]
    )

    collection.data.replace.assert_called_once()
    expected_uuid = str(uuid_mod.uuid5(uuid_mod.NAMESPACE_URL, "test/1#0"))
    assert collection.data.replace.call_args.kwargs["uuid"] == expected_uuid
    assert results == {"test/1": 1, "test/2": 1}
