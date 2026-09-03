"""Reconciliation 重建分支身份语义测试(Issue #13 Stage A,D 测试项)。

RED→GREEN 契约:同内容兄弟孤儿(same-content different-path orphan)的
账本重建在旧 PK (content_hash, branch) 下必然 UniqueViolation → 永久
unresolved(Issue #13 根因);新 PK (source_id) 下重建成功。同时覆盖:
身份约束冲突(并发竞态)必须显式上报 unresolved,不得吞错假装成功。

全程零 embed(fake collection + 真实 PG 账本)。
"""

import logging
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.db.models import Document
from scripts.sync import _reconcile_orphan_vectors

SRC = "src"

pytestmark = pytest.mark.asyncio


class _StatsConnector:
    """git 形态 connector 抽象:抽取集 = 权威枚举(无 authoritative 原语)。"""

    def __init__(self, paths):
        self._paths = paths

    def fetch_all(self):
        return iter([MagicMock(source_id=p) for p in self._paths])


def _pipeline(sync_factory, orphan_obj, n_objects: int = 1):
    pipeline = MagicMock()
    pipeline._session_factory = sync_factory
    collection = MagicMock()
    collection.query.fetch_objects.return_value = MagicMock(objects=[orphan_obj] * n_objects)
    pipeline._collection = collection
    pipeline._ensure_collection.return_value = None
    return pipeline


def _report(orphan_chunks):
    report = MagicMock()
    report.orphan_chunks = orphan_chunks
    return report


def _orphan_obj(sid: str, content_hash: str) -> MagicMock:
    return MagicMock(
        properties={
            "source_id": sid,
            "chunk_index": 0,
            "content_hash": content_hash,
            "source_type": "github",
            "product": "p",
            "title": sid.rsplit("/", 1)[-1],
            "url": f"https://example.com/{sid}",
            "branch": "main",
        }
    )


@pytest.fixture
def sync_factory(db_engine):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import os

    engine = create_engine(os.environ["TEST_DATABASE_URL"].replace("+asyncpg", ""))
    try:
        yield sessionmaker(bind=engine)
    finally:
        engine.dispose()


def _seed(sync_factory, path: str, content_hash: str, chunk_count: int = 2) -> None:
    with sync_factory() as session:
        session.add(
            Document(
                content_hash=content_hash,
                source_id=path,
                source_type="github",
                product="p",
                title=path.rsplit("/", 1)[-1],
                url="u",
                branch="main",
                chunk_count=chunk_count,
            )
        )
        session.commit()


def _paths(sync_factory) -> set[str]:
    with sync_factory() as session:
        return set(session.execute(select(Document.source_id)).scalars())


@pytest.mark.asyncio
async def test_d_rebuild_same_content_sibling_orphan_no_unique_violation(db_engine, sync_factory):
    """D:同内容兄弟孤儿重建成功(旧 PK 下此场景必 UniqueViolation)。

    生产对照(2026-09-03 实测):ne301 cJSON.c 孤儿的账本行被 ne503-apic
    同内容路径占据,重建 INSERT 撞 documents_pkey → 永久 unresolved。
    """
    content_hash = "hash-same-content"
    _seed(sync_factory, f"{SRC}/main/a/util.py", content_hash)  # 兄弟路径占行
    orphan_sid = f"{SRC}/main/b/util.py"  # 同内容、同分支、账本无行

    connector = _StatsConnector([f"{SRC}/main/a/util.py", orphan_sid])
    pipeline = _pipeline(sync_factory, _orphan_obj(orphan_sid, content_hash), n_objects=3)

    retired, repaired, unresolved = _reconcile_orphan_vectors(
        SRC, connector, pipeline, _report({orphan_sid: {0, 1, 2}})
    )

    assert (retired, repaired, unresolved) == (0, 1, 0)
    assert _paths(sync_factory) == {f"{SRC}/main/a/util.py", orphan_sid}
    with sync_factory() as session:
        row = session.execute(select(Document).where(Document.source_id == orphan_sid)).scalar_one()
    assert row.content_hash == content_hash
    assert row.chunk_count == 3  # max(indices)+1
    pipeline._collection.data.delete_many.assert_not_called()  # 重建绝不动向量


@pytest.mark.asyncio
async def test_d2_rebuild_race_integrity_error_reported_not_swallowed(
    db_engine, sync_factory, caplog
):
    """身份约束冲突(并发竞态:行已存在)→ 显式 unresolved + 警告,不假装成功。"""
    orphan_sid = f"{SRC}/main/raced.md"
    _seed(sync_factory, orphan_sid, "hash-x")  # 竞态:扫描后行已出现

    connector = _StatsConnector([orphan_sid])
    pipeline = _pipeline(sync_factory, _orphan_obj(orphan_sid, "hash-x"))

    with caplog.at_level(logging.WARNING):
        retired, repaired, unresolved = _reconcile_orphan_vectors(
            SRC, connector, pipeline, _report({orphan_sid: {0}})
        )

    assert (retired, repaired) == (0, 0)
    assert unresolved == 1  # 显式上报,不吞错
    assert any("身份约束冲突" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_d3_chunk_totals_out_param(db_engine, sync_factory):
    """chunk_totals 出参:退休/重建 chunk 数供共享一致性遥测消费。"""
    gone_sid = f"{SRC}/main/gone.md"
    keep_sid = f"{SRC}/main/keep.md"
    _seed(sync_factory, keep_sid, "hash-keep")
    connector = _StatsConnector([keep_sid])  # 权威成员集确无 gone.md(完整发现)
    pipeline = _pipeline(
        sync_factory,
        MagicMock(
            uuid="not-used",
            properties={"source_id": gone_sid, "chunk_index": 0},
        ),
    )
    # 完整发现成员集退休分支需 fetch_objects 命中数 == index 数
    from backend.pipeline.ingest import _deterministic_uuid

    gone_obj = MagicMock(uuid=_deterministic_uuid(gone_sid, 0), properties={"source_id": gone_sid})
    pipeline._collection.query.fetch_objects.return_value = MagicMock(objects=[gone_obj])

    totals = {}
    retired, repaired, unresolved = _reconcile_orphan_vectors(
        SRC,
        connector,
        pipeline,
        _report({gone_sid: {0}}),
        chunk_totals=totals,
    )
    assert (retired, repaired, unresolved) == (1, 0, 0)
    assert totals == {"retired_chunks": 1, "repaired_chunks": 0}
