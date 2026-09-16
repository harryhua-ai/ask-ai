"""r6(v1.6.3-r6 re-spin)Release-Blocker 修复回归:#84 withdrawn provider 生产 wiring。

生产事故(v1.6.3-r5 @ 8053352 部署后,已受控回滚至 r4):每次 /ask 检索经
``_apply_knowledge_exclusion → _withdrawn_identities → provider`` 触发
``AttributeError: 'sessionmaker' object has no attribute 'execute'`` ——
main.py lifespan wiring 把 **sessionmaker 工厂**直接传给要求真实
``Session`` 的 ``withdrawn_document_source_ids_sync``。

本套件按 **生产同构 wiring**(factory(非 Session) → CachedSourceExclusions →
provider())锁定契约:

1. provider 经生产同构 wiring 调用时必须返回账本 withdrawn identity 列表
   (deleted/superseded 在列;active 不在列)—— serving-eligibility 语义
   不变,仅会话获取方式被修复;
2. fail-closed 语义保持:查询失败异常向上传播,绝不静默回落空集
   (空集会让墓碑知识复活)。

真实 Postgres(TEST_DATABASE_URL,同步会话)。
"""

import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from backend.db.models import (
    Base,
    Document,
    DocumentVersion,
    IndexGeneration,
)
from backend.db.session import get_sync_session_factory
from backend.services.document_lifecycle import (
    DocLifecycle,
    withdrawn_document_source_ids_sync,
)
from backend.services.knowledge_policy import CachedSourceExclusions

SRC = "u84r6wiring"
ORDINAL = 424747
TOMBSTONE = f"{SRC}/main/2-sdk-reference.md"
ACTIVE = f"{SRC}/main/getting-started.md"


def _doc(sid: str, lifecycle: str) -> Document:
    return Document(
        source_id=sid,
        content_hash=f"hash-{sid}",
        source_type="github",
        product="u84r6",
        title=sid.rsplit("/", 1)[-1],
        url=f"https://example.com/{sid.rsplit('/', 1)[-1]}",
        metadata_={},
        branch="main",
        chunk_count=1,
        lifecycle=lifecycle,
    )


@pytest.fixture()
def ledger_session_factory():
    """生产同构:sync sessionmaker(工厂,非 Session)+ 测试库种子。"""
    sync_engine = create_engine(
        os.environ["TEST_DATABASE_URL"].replace("+asyncpg", "+psycopg2")
    )
    Base.metadata.create_all(sync_engine)
    factory = sessionmaker(bind=sync_engine, expire_on_commit=False)
    with factory() as session:
        for row in session.execute(
            select(Document).where(Document.source_id.like(f"{SRC}/%"))
        ).scalars():
            session.delete(row)
        session.execute(
            text("DELETE FROM index_generations WHERE source_id LIKE :p"), {"p": f"{SRC}%"}
        )
        session.commit()
        gen = IndexGeneration(
            ordinal=ORDINAL,
            source_id=SRC,
            status="ready",
        )
        session.add(gen)
        session.flush()
        tomb = _doc(TOMBSTONE, "deleted")
        tomb.deleted_at = datetime.now(UTC)
        keep = _doc(ACTIVE, "active")
        session.add(tomb)
        session.add(keep)
        session.flush()
        for doc, status in ((tomb, "retired"), (keep, "active")):
            session.add(
                DocumentVersion(
                    source_id=doc.source_id,
                    version_seq=1,
                    content_hash="a" * 64,
                    metadata_hash="b" * 64,
                    generation_id=gen.id,
                    generation_ordinal=gen.ordinal,
                    status=status,
                    title=doc.source_id.rsplit("/", 1)[-1],
                    url=doc.url,
                    chunk_count=1,
                )
            )
        session.commit()
    yield factory
    with factory() as session:
        session.execute(text("DELETE FROM document_versions WHERE source_id LIKE :p"), {"p": f"{SRC}/%"})
        session.execute(text("DELETE FROM documents WHERE source_id LIKE :p"), {"p": f"{SRC}/%"})
        session.commit()
    sync_engine.dispose()


def test_r6_provider_via_production_wiring_returns_withdrawn_ids(
    ledger_session_factory,
):
    """生产同构 wiring(factory 直接传入 accessor)必须返回账本 withdrawn
    identity 列表:墓碑在列、active 不在列 —— serving-eligibility 语义不变。"""
    identities = CachedSourceExclusions(
        lambda: withdrawn_document_source_ids_sync(ledger_session_factory),
        ttl=30.0,
    )
    result = identities.get()
    assert TOMBSTONE in result, "墓碑必须保持检索排除(serving-eligibility 不变)"
    assert ACTIVE not in result, "在服文档不得被误排除"


def test_r6_accessor_accepts_session_factory_directly(ledger_session_factory):
    """accessor 兼容 Session 与 sessionmaker 两种入参(会话获取内聚于
    accessor,main.py lifespan wiring 形态保持零改动)。"""
    ids_from_factory = withdrawn_document_source_ids_sync(ledger_session_factory)
    assert TOMBSTONE in ids_from_factory
    with ledger_session_factory() as session:
        ids_from_session = withdrawn_document_source_ids_sync(session)
    assert ids_from_session == ids_from_factory


def test_r6_fail_closed_still_propagates(ledger_session_factory, monkeypatch):
    """fail-closed 不变:查询失败异常向上传播,绝不静默回落空集。"""
    from backend.services import document_lifecycle as dl

    class _Broken:
        def execute(self, *_a, **_k):
            raise RuntimeError("ledger unavailable")

    broken = _Broken()
    with pytest.raises(RuntimeError):
        dl.withdrawn_document_source_ids_sync(broken)
    # 词表不变式:serving 之外即排除,词表零触碰
    assert set(DocLifecycle.WITHDRAWN) <= set(DocLifecycle.ALL) - set(
        DocLifecycle.SERVING
    )
