"""r6(REQUIRED CORRECTION)#84 production failure boundary 回归。

Role A 指定的测试边界:真实 production failure boundary =
production-like main/lifespan provider wiring → session factory →
acquire 真实 Session → Session-only accessor → CachedSourceExclusions /
provider → withdrawn identities 返回。

- **A(RED 锚点)**:原始 8053352 wiring(直传 factory 给 Session-only
  accessor)复现 production failure class
  (`AttributeError: 'sessionmaker' object has no attribute 'execute'`,
  生产 /ask 全量中断根因);
- **B/C/D(修正 wiring GREEN)**:`_build_withdrawn_identity_provider`
  (factory → acquire 真实 Session → Session-only accessor → deterministic
  close)返回账本 withdrawn identity:墓碑在列、active 不在列;
- **E**:accessor 契约仍为 Session-only(签名 + 真实 Session 直调);
- **F**:query/session failure → fail-closed 传播(绝不回落空 exclusion set);
- **G**:Session lifetime deterministic close(成功与异常路径均 close)。

lifecycle accessor 自身不感知 factory、不创建/管理 Session(修复落在
caller/wiring ownership:backend/main.py)。

真实 Postgres(TEST_DATABASE_URL,同步会话)。
"""

import inspect
import os
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from backend.db.models import Base, Document, DocumentVersion, IndexGeneration
from backend.db.session import get_sync_session_factory
from backend.services import document_lifecycle as dl
from backend.services.document_lifecycle import (
    DocLifecycle,
    withdrawn_document_source_ids_sync,
)
from backend.services.knowledge_policy import CachedSourceExclusions

SRC = "u84r6wiring"
TOMBSTONE = f"{SRC}/main/2-sdk-reference.md"
ACTIVE = f"{SRC}/main/getting-started.md"
ORDINAL = 424747


def _doc(sid: str, lifecycle: str) -> Document:
    doc = Document(
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
    if lifecycle == "deleted":
        doc.deleted_at = datetime.now(UTC)
    return doc


@pytest.fixture()
def ledger_session_factory():
    """生产同构 sync sessionmaker(工厂)+ 测试库种子(墓碑 + 在服)。"""
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
            text("DELETE FROM index_generations WHERE source_id LIKE :p"),
            {"p": f"{SRC}%"},
        )
        session.commit()
        gen = IndexGeneration(ordinal=ORDINAL, source_id=SRC, status="ready")
        session.add(gen)
        session.flush()
        tomb = _doc(TOMBSTONE, "deleted")
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
                    generation_ordinal=ORDINAL,
                    status=status,
                    title=doc.source_id.rsplit("/", 1)[-1],
                    url=doc.url,
                    chunk_count=1,
                )
            )
        session.commit()
    yield factory
    with factory() as session:
        session.execute(
            text("DELETE FROM document_versions WHERE source_id LIKE :p"),
            {"p": f"{SRC}/%"},
        )
        session.execute(
            text("DELETE FROM documents WHERE source_id LIKE :p"),
            {"p": f"{SRC}/%"},
        )
        session.execute(
            text("DELETE FROM index_generations WHERE source_id LIKE :p"),
            {"p": f"{SRC}%"},
        )
        session.commit()
    sync_engine.dispose()


class _RecordingFactory:
    """包装工厂:记录创建的 Session 与 close() 调用(G:deterministic close)。"""

    def __init__(self, real):
        self._real = real
        self.created: list = []
        self.closed: list = []

    def __call__(self):
        s = self._real()
        original_close = s.close

        def _close():
            self.closed.append(True)
            original_close()

        s.close = _close
        self.created.append(s)
        return s


# --------------------------------------------------------------------------- #
# A. RED 锚点:原始 8053352 wiring 复现 production failure class
# --------------------------------------------------------------------------- #


def test_a_original_wiring_reproduces_production_failure_class(
    ledger_session_factory,
):
    """原始 wiring(main.py:430 形态:factory 直传 Session-only accessor)
    必然触发生产同类 AttributeError —— 本锚点固定 failure class 与根因
    位置;修复后生产不再使用该形态(由 B 的 corrected wiring 取代)。"""
    broken = CachedSourceExclusions(
        lambda: withdrawn_document_source_ids_sync(ledger_session_factory),
        ttl=30.0,
    )
    with pytest.raises(AttributeError, match="sessionmaker"):
        broken.get()


# --------------------------------------------------------------------------- #
# B/C/D. corrected wiring:factory → acquire 真实 Session → Session-only
# accessor → deterministic close → withdrawn identities
# --------------------------------------------------------------------------- #


def test_bcd_corrected_provider_wiring_returns_withdrawn_ids(
    ledger_session_factory,
):
    from backend import main as main_module

    provider = main_module._build_withdrawn_identity_provider(
        ledger_session_factory
    )
    result = provider()
    assert isinstance(result, list)
    assert TOMBSTONE in result, "C: 墓碑必须在 exclusion set"
    assert ACTIVE not in result, "D: 在服文档不得被误排除"


def test_b2_corrected_wiring_matches_production_call_shape(ledger_session_factory):
    """wiring 调用形态与 main.py lifespan 同构:get_sync_session_factory(...)
    的返回值直接交给 builder(生产调用形态回归)。"""
    from backend import main as main_module

    provider = main_module._build_withdrawn_identity_provider(
        get_sync_session_factory(os.environ["TEST_DATABASE_URL"])
    )
    result = provider()
    assert TOMBSTONE in result
    assert ACTIVE not in result


# --------------------------------------------------------------------------- #
# E. accessor 契约仍为 Session-only
# --------------------------------------------------------------------------- #


def test_e_accessor_contract_remains_session_only(ledger_session_factory):
    """accessor 签名必须为 Session-only(无 sessionmaker 兼容层);真实
    Session 直调行为保持。"""
    sig = inspect.signature(dl.withdrawn_document_source_ids_sync)
    (param,) = sig.parameters.values()
    assert param.name == "session"
    assert "sessionmaker" not in str(param.annotation), (
        "accessor 契约被扩大:不得接受 factory(R6 REQUIRED CORRECTION)"
    )
    assert "Session" in str(param.annotation)
    with ledger_session_factory() as session:
        ids = dl.withdrawn_document_source_ids_sync(session)
    assert TOMBSTONE in ids
    assert ACTIVE not in ids


# --------------------------------------------------------------------------- #
# F/G. fail-closed 传播 + deterministic close
# --------------------------------------------------------------------------- #


def test_f_query_failure_propagates_no_empty_exclusion_set(
    ledger_session_factory, monkeypatch
):
    """F:accessor/query 异常必须向上传播(绝不返回空 exclusion set),
    且 G:异常路径 session 仍 deterministic close。"""
    from backend import main as main_module

    recording = _RecordingFactory(ledger_session_factory)

    def _boom(session):
        raise RuntimeError("ledger unavailable")

    monkeypatch.setattr(
        dl, "withdrawn_document_source_ids_sync", _boom
    )  # builder 延迟导入解析到源模块属性,patch 源头即可拦截
    provider = main_module._build_withdrawn_identity_provider(recording)
    with pytest.raises(RuntimeError, match="ledger unavailable"):
        provider()
    assert len(recording.closed) == 1, "异常路径仍必须 deterministic close"


def test_g_session_closed_deterministically_on_success(ledger_session_factory):
    """G:成功路径 session 恰创建一次、恰 close 一次。"""
    recording = _RecordingFactory(ledger_session_factory)
    from backend import main as main_module

    provider = main_module._build_withdrawn_identity_provider(recording)
    result = provider()
    assert len(recording.created) == 1
    assert len(recording.closed) == 1
    assert TOMBSTONE in result


def test_g2_vocabulary_invariant_unchanged():
    """词表零触碰:serving 之外即排除,词表与转换原语不变。"""
    assert set(DocLifecycle.WITHDRAWN) <= set(DocLifecycle.ALL) - set(
        DocLifecycle.SERVING
    )
