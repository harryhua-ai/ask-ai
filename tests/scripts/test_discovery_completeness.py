"""发现完整性守卫测试(阶段1 / G3)。

冻结规则:UNKNOWN / INCOMPLETE DISCOVERY ≠ AUTHORITATIVE EMPTY SOURCE。
「0 discovered / 0 accepted」不能证明源权威成员集为空;无法证明完整时
禁止破坏性退休,孤儿一律保留并上报。
"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from scripts.sync import _discover_source_docs, _reconcile_orphan_vectors

pytestmark = pytest.mark.unit


class _StatsConnector:
    """带 run_stats 的假 connector(web_crawl 形态)。"""

    def __init__(
        self,
        stats: dict,
        docs=None,
        raise_on_fetch: Exception | None = None,
        membership: set[str] | None = None,
    ):
        self.run_stats = stats
        self._docs = docs or []
        self._raise = raise_on_fetch
        self._membership = membership

    def fetch_all(self):
        if self._raise:
            raise self._raise
        return iter(self._docs)

    def authoritative_source_ids(self):
        return self._membership


def test_sitemap_request_failure_is_incomplete():
    conn = _StatsConnector({"full": True}, raise_on_fetch=RuntimeError("sitemap fetch failed"))
    docs, complete, membership = _discover_source_docs(conn)
    assert docs == [] and complete is False and membership is None


def test_malformed_empty_sitemap_zero_discovered_is_incomplete():
    """畸形/空 sitemap(200,解析静默返回空)→ discovered=0 → 不完整(T20/T24)。"""
    conn = _StatsConnector({"full": True, "discovered": 0, "accepted": 0, "extracted": 0})
    docs, complete, membership = _discover_source_docs(conn)
    assert complete is False  # 禁止把空枚举当「权威空源」


def test_zero_accepted_with_provable_discovery_is_complete():
    """discovered>0 且 sitemap 可解析、全部被 robots/规则拒绝 → 允许集为空是
    **可证明的权威空**(保守性只约束「无法证明完整」的场景)。"""
    conn = _StatsConnector(
        {"full": True, "discovered": 50, "accepted": 0, "extracted": 0}, membership=set()
    )
    _, complete, membership = _discover_source_docs(conn)
    assert complete is True
    assert membership == set()


def test_missing_discovered_key_keeps_legacy_semantics():
    """run_stats 无 discovered 键(primitive/旧形态)→ 不触发 G3 守卫,
    覆盖率规则照旧(G003b 冻结语义不回退)。"""
    conn = _StatsConnector({"full": True, "accepted": 100, "extracted": 90}, membership={"s/a"})
    _, complete, membership = _discover_source_docs(conn)
    assert complete is True
    assert membership == {"s/a"}


def test_low_coverage_extraction_is_incomplete():
    conn = _StatsConnector({"full": True, "discovered": 100, "accepted": 100, "extracted": 30})
    _, complete, _ = _discover_source_docs(conn)
    assert complete is False


def test_authoritative_non_empty_discovery_is_complete():
    conn = _StatsConnector(
        {"full": True, "discovered": 100, "accepted": 100, "extracted": 95},
        membership={"s/a", "s/b"},
    )
    _, complete, membership = _discover_source_docs(conn)
    assert complete is True
    assert membership == {"s/a", "s/b"}


def test_primitive_connector_empty_fetch_is_complete():
    """git/fs/woo 无 run_stats:fetch_all 成功即权威枚举,空结果=真空(可退休)。"""

    class _Plain:
        def fetch_all(self):
            return iter([])

    _, complete, membership = _discover_source_docs(_Plain())
    assert complete is True and membership is None


# --------------------------------------------------------------- 退休禁令


class _Report:
    orphan_chunks = {"s/ghost": {0}}
    orphan_count = 1
    missing_source_ids: list = []
    refill_source_ids: list = []


def _fake_pipeline(fetch_objects):
    pipeline = MagicMock()
    pipeline._class_name = "Document"
    coll = pipeline._collection
    coll.query.fetch_objects.side_effect = fetch_objects
    return pipeline


def test_incomplete_discovery_never_deletes_even_when_membership_empty(caplog):
    """G1 精确场景:对象读得到、成员集为空集,但发现不完整 → 保留,零删除(T24)。"""
    obj = MagicMock(
        properties={
            "source_id": "s/ghost",
            "chunk_index": 0,
            "content_hash": "h",
            "title": "t",
            "url": "u",
            "source_type": "web_crawl",
            "product": "p",
            "branch": "",
        }
    )
    pipeline = _fake_pipeline(lambda filters, limit: MagicMock(objects=[obj]))
    conn = _StatsConnector(
        {"full": True, "discovered": 0, "accepted": 0, "extracted": 0},
        membership=set(),  # 空 sitemap → 权威成员集为空集
    )
    with caplog.at_level(logging.WARNING):
        retired, repaired, unresolved = _reconcile_orphan_vectors("s", conn, pipeline, _Report())
    assert (retired, repaired, unresolved) == (0, 0, 1)
    pipeline._collection.data.delete_many.assert_not_called()


def test_complete_discovery_with_empty_membership_retires_exactly():
    """对照:完整发现 + 权威成员集确无此文档 → 精确退休(既有语义不回退)。"""
    import uuid as uuid_mod

    from backend.pipeline.ingest import _deterministic_uuid

    sid = "s/ghost"
    obj = MagicMock(
        uuid=_deterministic_uuid(sid, 0), properties={"source_id": sid, "chunk_index": 0}
    )
    pipeline = _fake_pipeline(lambda filters, limit: MagicMock(objects=[obj]))
    conn = _StatsConnector(
        {"full": True, "discovered": 10, "accepted": 10, "extracted": 10},
        membership=set(),
    )
    retired, repaired, unresolved = _reconcile_orphan_vectors("s", conn, pipeline, _Report())
    assert (retired, repaired, unresolved) == (1, 0, 0)
    # 删除必须按确定性 UUID 点删
    called = pipeline._collection.data.delete_many.call_args
    assert called is not None
    assert uuid_mod.UUID(str(obj.uuid)) is not None
