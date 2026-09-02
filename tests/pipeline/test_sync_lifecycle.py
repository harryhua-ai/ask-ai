"""P1: website sync 生命周期稳定性回归(ghost/retirement/no-op)。

冻结语义(合同 §3/§4):
- PRUNE IS DOCUMENT-LOCAL(P0-A);
- RETIREMENT MUST BE SOURCE-CONFIRMED:完整且成功的权威源发现中确认消失,
  才允许按精确确定性 UUID 退休删除;发现失败/不完整 → 一律保留并上报;
- 无害 ghost 不得触发合法语料全量重灌/refill(G006);
- 真实缺失的合法 chunk 仍必须被检出并修复(G007)。

诊断三分类:MISSING_LEGITIMATE / EXTRA_CONFIRMED_RETIRED / EXTRA_UNRESOLVED_ORPHAN。
"""

import uuid as uuid_mod
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker

from backend.connectors.base import RawDocument
from backend.db.models import Base, Document, SyncLog
from backend.pipeline.ingest import _deterministic_uuid
from backend.services.vector_consistency import VectorGapReport
from scripts.sync import _handle_no_change

SRC = "site"


def _jsonb_sqlite(type_, compiler, **kw):
    return "JSON"


compiles(JSONB, "sqlite")(_jsonb_sqlite)


def _sqlite_session_factory():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _report(
    *,
    expected=361,
    actual=361,
    refill=(),
    missing=(),
    orphan_chunks=None,
) -> VectorGapReport:
    return VectorGapReport(
        expected_chunks=expected,
        actual_chunks=actual,
        missing_source_ids=list(missing),
        refill_source_ids=list(refill),
        orphan_count=len(orphan_chunks or {}),
        orphan_chunks=dict(orphan_chunks or {}),
    )


def _doc(sid: str, hash_: str = "h") -> RawDocument:
    return RawDocument(
        source_id=sid,
        source_type="web_crawl",
        product="website",
        title=sid,
        content="x",
        url=f"https://x/{sid}",
        metadata={},
        content_hash=hash_,
    )


def _make_pipeline(orphan_props: dict | None = None, orphan_indices: int = 1):
    """pipeline mock:ingest_all 可控;_collection 支持 by_id fetch/delete 断言。

    fetch_objects 返回 ``orphan_indices`` 个携带 orphan_props 的对象
    (对齐校验器扫描到的孤儿 chunk 数)。
    """
    pipeline = MagicMock()
    pipeline.ingest_all.return_value = {}

    fetched = MagicMock()
    if orphan_props is not None:
        fetched.objects = [
            MagicMock(properties={**orphan_props, "chunk_index": i}) for i in range(orphan_indices)
        ]
    else:
        fetched.objects = []
    pipeline._collection.query.fetch_objects.return_value = fetched
    return pipeline


def _ghost_props(sid: str = f"{SRC}/old-page") -> dict:
    return {
        "source_id": sid,
        "chunk_index": 0,
        "content_hash": f"hash-{sid}",
        "source_type": "web_crawl",
        "product": "website",
        "title": sid,
        "url": f"https://www.camthink.ai/{sid}",
        "branch": "",
    }


def _report_side_effect(*reports):
    m = AsyncMock(side_effect=list(reports))
    return m


# --------------------------------------------------------------------------- #
# G001 稳定 no-op
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_g001_healthy_source_is_stable_noop():
    report = _report()  # 完全健康
    connector = MagicMock()
    pipeline = _make_pipeline()
    log_entry = SyncLog(status="success")  # _sync_one 初始化即 success

    with patch(
        "scripts.sync.verify_source_vectors",
        _report_side_effect(report),
    ):
        await _handle_no_change(SRC, 110, connector, pipeline, MagicMock(), log_entry, 0.0)

    assert log_entry.status == "success"
    assert log_entry.items_unchanged == 110
    connector.fetch_all.assert_not_called()
    pipeline.ingest_all.assert_not_called()
    pipeline._collection.data.delete_many.assert_not_called()


# --------------------------------------------------------------------------- #
# G002 变更文档:只动 A,兄弟 B 不触碰
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_g002_changed_doc_refill_touches_only_that_doc():
    report1 = _report(expected=10, actual=8, refill=[f"{SRC}/a"])
    report2 = _report(expected=10, actual=10)  # 重灌后收敛
    connector = MagicMock()
    connector.fetch_all.return_value = iter([_doc(f"{SRC}/a"), _doc(f"{SRC}/b")])
    pipeline = _make_pipeline()
    pipeline.ingest_all.return_value = {f"{SRC}/a": 2}
    log_entry = SyncLog()

    with patch("scripts.sync.verify_source_vectors", _report_side_effect(report1, report2)):
        await _handle_no_change(SRC, 5, connector, pipeline, MagicMock(), log_entry, 0.0)

    ingested = [d.source_id for d in pipeline.ingest_all.call_args[0][0]]
    assert ingested == [f"{SRC}/a"]  # 兄弟 B 不进灌入
    assert log_entry.status == "success"  # 重灌后复验收敛 → success(窗口推进)


# --------------------------------------------------------------------------- #
# G003 源确认退休:精确删除,仅限退休文档
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_g003_confirmed_retirement_deletes_exact_uuids_only():
    ghost = f"{SRC}/old-page"
    report1 = _report(expected=361, actual=362, orphan_chunks={ghost: {0, 1, 2}})
    report2 = _report(expected=361, actual=361)
    connector = MagicMock()
    connector.fetch_all.return_value = iter([_doc(f"{SRC}/alive")])  # ghost 不在源
    pipeline = _make_pipeline(orphan_props=_ghost_props(ghost), orphan_indices=3)
    log_entry = SyncLog(status="success")

    with patch("scripts.sync.verify_source_vectors", _report_side_effect(report1, report2)):
        await _handle_no_change(SRC, 110, connector, pipeline, MagicMock(), log_entry, 0.0)

    pipeline.ingest_all.assert_not_called()  # 退休不重灌
    calls = pipeline._collection.data.delete_many.call_args_list
    expected_uuids = sorted(_deterministic_uuid(ghost, i) for i in (0, 1, 2))
    got = sorted(str(v) for c in calls for v in c.kwargs["where"].value)
    assert got == expected_uuids
    # 退休绝不触碰兄弟文档的确定性 uuid
    assert str(_deterministic_uuid(f"{SRC}/alive", 0)) not in got
    assert log_entry.status == "success"
    assert log_entry.items_deleted == 1


# --------------------------------------------------------------------------- #
# G004 源发现失败/不完整 → 不得退休
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_g004a_discovery_failure_keeps_ghosts_and_reports():
    ghost = f"{SRC}/old-page"
    report1 = _report(expected=361, actual=362, orphan_chunks={ghost: {0}})
    report2 = _report(expected=361, actual=362, orphan_chunks={ghost: {0}})
    connector = MagicMock()
    connector.fetch_all.side_effect = RuntimeError("sitemap timeout")
    pipeline = _make_pipeline(orphan_props=_ghost_props(ghost))
    log_entry = SyncLog()

    with patch("scripts.sync.verify_source_vectors", _report_side_effect(report1, report2)):
        await _handle_no_change(SRC, 110, connector, pipeline, MagicMock(), log_entry, 0.0)

    pipeline._collection.data.delete_many.assert_not_called()  # 不确定性发现 → 不删
    pipeline.ingest_all.assert_not_called()
    assert log_entry.status == "partial"
    detail = log_entry.error_detail or ""
    assert "EXTRA_UNRESOLVED_ORPHAN" in detail


@pytest.mark.asyncio
async def test_g004b_partial_crawl_coverage_cannot_retire():
    ghost = f"{SRC}/old-page"
    report1 = _report(expected=361, actual=362, orphan_chunks={ghost: {0}})
    report2 = _report(expected=361, actual=362, orphan_chunks={ghost: {0}})
    connector = MagicMock()
    connector.fetch_all.return_value = iter([_doc(f"{SRC}/alive")])
    # web_crawl 合同:全量轮覆盖率不足 → 发现不完整
    connector.run_stats = {"full": True, "accepted": 10, "extracted": 2}
    pipeline = _make_pipeline(orphan_props=_ghost_props(ghost))
    log_entry = SyncLog()

    with patch("scripts.sync.verify_source_vectors", _report_side_effect(report1, report2)):
        await _handle_no_change(SRC, 110, connector, pipeline, MagicMock(), log_entry, 0.0)

    pipeline._collection.data.delete_many.assert_not_called()
    assert log_entry.status == "partial"
    assert "EXTRA_UNRESOLVED_ORPHAN" in (log_entry.error_detail or "")


# --------------------------------------------------------------------------- #
# G005 历史 ghost:源里仍存在(账本行丢失)→ 零 embedding 账本修复,不删
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_g005_ledger_lost_active_doc_repaired_without_embedding():
    ghost = f"{SRC}/alive-but-unledgered"
    report1 = _report(expected=361, actual=362, orphan_chunks={ghost: {0, 1}})
    report2 = _report(expected=363, actual=362, refill=[ghost])  # 修复行 index 范围不符 → 下轮定向
    connector = MagicMock()
    connector.fetch_all.return_value = iter([_doc(ghost)])  # 源里仍存在
    session_factory = _sqlite_session_factory()
    pipeline = _make_pipeline(orphan_props=_ghost_props(ghost), orphan_indices=2)
    pipeline._session_factory = session_factory
    log_entry = SyncLog(status="success")

    with patch("scripts.sync.verify_source_vectors", _report_side_effect(report1, report2)):
        await _handle_no_change(SRC, 110, connector, pipeline, session_factory, log_entry, 0.0)

    pipeline._collection.data.delete_many.assert_not_called()  # 源在 → 不退休
    with session_factory() as s:
        row = s.query(Document).filter(Document.source_id == ghost).one_or_none()
    assert row is not None and row.chunk_count == 2  # 账本行按存量重建
    assert log_entry.items_new == 1


# --------------------------------------------------------------------------- #
# G006 ghost 不触发合法语料全量重灌(核心回归:旧实现 fetch_all+ingest_all 全量自愈)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_g006_ghosts_alone_never_trigger_full_refill():
    ghosts = {f"{SRC}/g{i}": {0} for i in range(10)}
    report1 = _report(expected=361, actual=371, orphan_chunks=ghosts)
    report2 = _report(expected=361, actual=361)  # 退休后收敛
    connector = MagicMock()
    connector.fetch_all.return_value = iter([_doc(f"{SRC}/alive")])  # 10 个 ghost 均不在源
    pipeline = _make_pipeline(orphan_props=_ghost_props())
    log_entry = SyncLog()

    with patch("scripts.sync.verify_source_vectors", _report_side_effect(report1, report2)):
        await _handle_no_change(SRC, 110, connector, pipeline, MagicMock(), log_entry, 0.0)

    pipeline.ingest_all.assert_not_called()  # 绝不全量重灌
    assert log_entry.status == "success"


# --------------------------------------------------------------------------- #
# G007 真实缺失的合法 chunk 仍被检出并修复(不得为忽略 ghost 而弱化校验)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_g007_missing_legitimate_chunk_still_repaired():
    report1 = _report(expected=361, actual=360, refill=[f"{SRC}/a"], missing=[f"{SRC}/a"])
    report2 = _report(expected=361, actual=361)
    connector = MagicMock()
    connector.fetch_all.return_value = iter([_doc(f"{SRC}/a")])
    pipeline = _make_pipeline()
    pipeline.ingest_all.return_value = {f"{SRC}/a": 1}
    log_entry = SyncLog()

    with patch("scripts.sync.verify_source_vectors", _report_side_effect(report1, report2)):
        await _handle_no_change(SRC, 110, connector, pipeline, MagicMock(), log_entry, 0.0)

    pipeline.ingest_all.assert_called_once()
    assert log_entry.status == "success"


# --------------------------------------------------------------------------- #
# G008 混合态:缺失 + ghost + 变更 同时存在,各归各类
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_g008_mixed_state_classes_handled_independently():
    ghost = f"{SRC}/retired-page"
    report1 = _report(
        expected=361,
        actual=361,
        refill=[f"{SRC}/changed"],
        orphan_chunks={ghost: {0}},
    )
    report2 = _report(expected=361, actual=361)
    connector = MagicMock()
    connector.fetch_all.return_value = iter(
        [_doc(f"{SRC}/changed"), _doc(f"{SRC}/other")]  # ghost 不在源
    )
    pipeline = _make_pipeline(orphan_props=_ghost_props(ghost))
    pipeline.ingest_all.return_value = {f"{SRC}/changed": 2}
    log_entry = SyncLog()

    with patch("scripts.sync.verify_source_vectors", _report_side_effect(report1, report2)):
        await _handle_no_change(SRC, 110, connector, pipeline, MagicMock(), log_entry, 0.0)

    ingested = [d.source_id for d in pipeline.ingest_all.call_args[0][0]]
    assert ingested == [f"{SRC}/changed"]  # 只灌变更文档
    got = sorted(
        str(v)
        for c in pipeline._collection.data.delete_many.call_args_list
        for v in c.kwargs["where"].value
    )
    assert got == sorted(_deterministic_uuid(ghost, i) for i in (0,))
    assert log_entry.status == "success"
    detail = log_entry.error_detail or ""
    assert "MISSING_LEGITIMATE" in detail
    assert "EXTRA_CONFIRMED_RETIRED" in detail


# --------------------------------------------------------------------------- #
# G009 幂等:健康源连续两轮均稳定 no-op
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_g009_repeated_healthy_sync_idempotent():
    connector = MagicMock()
    pipeline = _make_pipeline()
    log_entry = SyncLog(status="success")
    with patch(
        "scripts.sync.verify_source_vectors",
        _report_side_effect(_report(), _report()),
    ):
        await _handle_no_change(SRC, 110, connector, pipeline, MagicMock(), log_entry, 0.0)
        await _handle_no_change(SRC, 110, connector, pipeline, MagicMock(), log_entry, 0.0)

    assert log_entry.status == "success"
    connector.fetch_all.assert_not_called()
    pipeline.ingest_all.assert_not_called()
    pipeline._collection.data.delete_many.assert_not_called()


# --------------------------------------------------------------------------- #
# G004-C/D 权威成员资格 ≠ 抽取成功(Planner 修正:80% 覆盖率不得授权退休)
# --------------------------------------------------------------------------- #


def _web_connector_with_membership(membership: set[str], *, coverage_ok: bool = True):
    """web_crawl 形态连接器:fetch_all 仅产出抽取成功的文档;
    authoritative_source_ids() 返回权威成员集(含抓取失败/被拒页)。"""
    connector = MagicMock()
    connector.fetch_all.return_value = iter([_doc(f"{SRC}/alive")])
    connector.run_stats = (
        {"full": True, "accepted": 100, "extracted": 90}
        if coverage_ok
        else {"full": True, "accepted": 100, "extracted": 50}
    )
    connector.authoritative_source_ids = MagicMock(return_value=membership)
    return connector


@pytest.mark.asyncio
async def test_g004c_member_page_fetch_failure_never_retires():
    """G004-C:A 仍是权威源成员(sitemap/accepted),仅页面抓取失败;
    整体覆盖率 90% → A 不得被退休/删除。"""
    ghost = f"{SRC}/member-fetch-failed"
    report1 = _report(expected=361, actual=361, orphan_chunks={ghost: {0}})
    report2 = _report(expected=361, actual=361, orphan_chunks={ghost: {0}})
    connector = _web_connector_with_membership({f"{SRC}/alive", ghost})
    pipeline = _make_pipeline(orphan_props=_ghost_props(ghost))
    log_entry = SyncLog(status="success")

    with patch("scripts.sync.verify_source_vectors", _report_side_effect(report1, report2)):
        await _handle_no_change(SRC, 110, connector, pipeline, MagicMock(), log_entry, 0.0)

    pipeline._collection.data.delete_many.assert_not_called()
    assert log_entry.status == "partial"
    assert "EXTRA_UNRESOLVED_ORPHAN" in (log_entry.error_detail or "")


@pytest.mark.asyncio
async def test_g004d_member_page_low_content_rejection_never_retires():
    """G004-D:A 被临时薄内容/抽取拒绝,但仍是权威源成员;覆盖率 90% → 不退休。"""
    ghost = f"{SRC}/member-low-content"
    report1 = _report(expected=361, actual=361, orphan_chunks={ghost: {0}})
    report2 = _report(expected=361, actual=361, orphan_chunks={ghost: {0}})
    connector = _web_connector_with_membership({f"{SRC}/alive", ghost})
    pipeline = _make_pipeline(orphan_props=_ghost_props(ghost))
    log_entry = SyncLog(status="success")

    with patch("scripts.sync.verify_source_vectors", _report_side_effect(report1, report2)):
        await _handle_no_change(SRC, 110, connector, pipeline, MagicMock(), log_entry, 0.0)

    pipeline._collection.data.delete_many.assert_not_called()
    assert log_entry.status == "partial"


@pytest.mark.asyncio
async def test_g004e_incomplete_enumeration_never_retires_even_with_membership():
    """G004-E:权威枚举本身不完整(覆盖率 50%)→ 任何历史缺席文档都不得退休。"""
    ghost = f"{SRC}/old-page"
    report1 = _report(expected=361, actual=362, orphan_chunks={ghost: {0}})
    report2 = _report(expected=361, actual=362, orphan_chunks={ghost: {0}})
    connector = _web_connector_with_membership({f"{SRC}/alive", ghost}, coverage_ok=False)
    pipeline = _make_pipeline(orphan_props=_ghost_props(ghost))
    log_entry = SyncLog(status="success")

    with patch("scripts.sync.verify_source_vectors", _report_side_effect(report1, report2)):
        await _handle_no_change(SRC, 110, connector, pipeline, MagicMock(), log_entry, 0.0)

    pipeline._collection.data.delete_many.assert_not_called()
    assert log_entry.status == "partial"


@pytest.mark.asyncio
async def test_g003b_membership_confirmed_absence_still_retires_exactly():
    """G003 补充:成员集证据确认 A 已不在权威枚举中 → 仍按精确 UUID 退休。"""
    ghost = f"{SRC}/truly-removed"
    report1 = _report(expected=361, actual=362, orphan_chunks={ghost: {0, 1}})
    report2 = _report(expected=361, actual=361)
    connector = _web_connector_with_membership({f"{SRC}/alive"})  # 成员集无 ghost
    pipeline = _make_pipeline(orphan_props=_ghost_props(ghost), orphan_indices=2)
    log_entry = SyncLog(status="success")

    with patch("scripts.sync.verify_source_vectors", _report_side_effect(report1, report2)):
        await _handle_no_change(SRC, 110, connector, pipeline, MagicMock(), log_entry, 0.0)

    calls = pipeline._collection.data.delete_many.call_args_list
    got = sorted(str(v) for c in calls for v in c.kwargs["where"].value)
    assert got == sorted(_deterministic_uuid(ghost, i) for i in (0, 1))
    assert log_entry.status == "success"


# --------------------------------------------------------------------------- #
# 集成:真实 Weaviate 上 ghost 精确退休(不可达时 skip)
# --------------------------------------------------------------------------- #


def _real_client():
    import weaviate

    import os

    port = int(os.environ.get("P1_WEAVIATE_PORT", "21100"))
    try:
        return weaviate.connect_to_local("localhost", port)
    except Exception:  # noqa: BLE001
        return None


@pytest.mark.asyncio
async def test_integration_ghost_retired_exactly_on_real_weaviate():
    client = _real_client()
    if client is None:
        pytest.skip("local Weaviate 1.28 不可达(P1_WEAVIATE_PORT)")
    import weaviate.classes.config as wc
    import weaviate.classes.data as wd

    if client.collections.exists("ProbeP1"):
        client.collections.delete("ProbeP1")
    client.collections.create(
        "ProbeP1",
        properties=[
            wc.Property(name="source_id", data_type=wc.DataType.TEXT),
            wc.Property(name="chunk_index", data_type=wc.DataType.INT),
        ],
    )
    try:
        coll = client.collections.get("ProbeP1")
        objs = []
        for sid, n in {
            f"{SRC}/alive": 2,
            f"{SRC}/old-page": 1,  # ghost:源已无此页
        }.items():
            for i in range(n):
                objs.append(
                    wd.DataObject(
                        properties={
                            "source_id": sid,
                            "chunk_index": i,
                            "content_hash": f"h-{sid}",
                            "source_type": "web_crawl",
                            "product": "website",
                            "title": sid,
                            "url": f"https://x/{sid}",
                            "branch": "",
                        },
                        vector=[0.1] * 4,
                        uuid=_deterministic_uuid(sid, i),
                    )
                )
        coll.data.insert_many(objs)

        pipeline = MagicMock()
        pipeline._collection = coll
        pipeline._session_factory = None

        report1 = _report(expected=2, actual=3, orphan_chunks={f"{SRC}/old-page": {0}})
        report2 = _report(expected=2, actual=2)
        connector = MagicMock()
        connector.fetch_all.return_value = iter([_doc(f"{SRC}/alive")])
        log_entry = SyncLog()

        with patch(
            "scripts.sync.verify_source_vectors",
            _report_side_effect(report1, report2),
        ):
            await _handle_no_change(SRC, 1, connector, pipeline, MagicMock(), log_entry, 0.0)

        survivors = {
            o.properties["source_id"] for o in coll.iterator(return_properties=["source_id"])
        }
        assert survivors == {f"{SRC}/alive"}
        assert log_entry.status == "success"
        assert log_entry.items_deleted == 1
    finally:
        client.collections.delete("ProbeP1")
        client.close()
