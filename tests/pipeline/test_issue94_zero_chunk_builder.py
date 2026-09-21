"""Issue #94 RED→GREEN:零语义分块在 builder 的确定性分类与分区。

生产机制(2026-09-17 只读取证,ne301-local=5 / lowpower-camera-local=18):
合法权威内容通过 connector/safety/materialization,但 chunk_document_semantic
确定性地产出 [] ⇒ builder 静默 ``continue`` ⇒ 不入账本 ⇒ membership 每轮
把它上报为 actionable missing ⇒ 永恒 missing 债(非故障,但账目不真)。

目标语义(#94 ght-contract AC1-AC5):
- 确定性 [] ⇒ 登记零分块分类(内容指纹+chunker 策略指纹),进 excluded
  分区(非 failed),绝不入账本/向量,绝不假收敛;
- 未变更的下轮 = 确认(times+1),核算分列,零嵌入;
- 内容变更 ⇒ 指纹原位换判定;后来产出有效分块 ⇒ 激活 + 分类清除;
- chunker 异常仍走 failed(fail-closed),永远造不出零分块真值(AC4)。
"""

from __future__ import annotations

import hashlib
import os
from types import SimpleNamespace

import pytest
import weaviate
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.connectors.base import RawDocument
from backend.db.models import (
    Base,
    Document,
    DocumentVersion,
    IndexGeneration,
    ZeroSemanticChunk,
)
from backend.pipeline.generation_builder import GenerationBuilder
from backend.services import document_lifecycle as lifecycle

TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test",
).replace("+asyncpg", "+psycopg2")
WEAVIATE_PORT = int(os.environ.get("P1_WEAVIATE_PORT", "8080"))
CLASS_NAME = "I94ZeroProbe"
SRC = "i94zero-src"
PREFIX = f"{SRC}/"

CHUNKABLE = PREFIX + "main/docs/overview.md"
ZERO_CHUNK = PREFIX + "main/build/Makefile"


def _hash(x: str) -> str:
    return hashlib.sha256(x.encode()).hexdigest()


def _doc(sid: str, content: str) -> RawDocument:
    return RawDocument(
        source_id=sid,
        source_type="github",
        product="probe",
        title=sid.rsplit("/", 1)[-1],
        content=content,
        url=f"https://x/{sid}",
        metadata={"path": sid},
        content_hash=_hash(content),
        branch=sid.split("/")[1],
    )


def _zero_doc(content="CC = gcc\n\nall: build\n") -> RawDocument:
    return _doc(ZERO_CHUNK, content)


class _FakeEmbedder:
    dimension = 8

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return [[0.1] * self.dimension for _ in texts]


@pytest.fixture()
def stack(monkeypatch):
    try:
        client = weaviate.connect_to_local("localhost", WEAVIATE_PORT)
    except Exception:  # noqa: BLE001 - 不可达即跳过(既有集成套件同模式)
        pytest.skip(f"local Weaviate 不可达(port={WEAVIATE_PORT})")
    sync_engine = create_engine(TEST_DSN)
    Base.metadata.create_all(sync_engine)
    sync_factory = sessionmaker(sync_engine, expire_on_commit=False)

    with sync_factory() as s:
        _purge(s)
    if client.collections.exists(CLASS_NAME):
        client.collections.delete(CLASS_NAME)

    embedder = _FakeEmbedder()
    from backend.pipeline.ingest import IngestionPipeline

    pipeline = IngestionPipeline(
        embedder,
        client,
        class_name=CLASS_NAME,
        max_tokens=40,
        overlap=0,
        session_factory=sync_factory,
        max_chunk_chars=2000,
    )
    builder = GenerationBuilder(pipeline, sync_factory)

    # 确定性零分块:仅对 ZERO_CHUNK 文档返回 [];其它文档走真实 chunker。
    import backend.pipeline.generation_builder as gb

    real_semantic = gb.chunk_document_semantic

    def fake_semantic(doc, max_tokens, overlap):
        if doc.source_id == ZERO_CHUNK:
            return []
        return real_semantic(doc, max_tokens, overlap)

    monkeypatch.setattr(gb, "chunk_document_semantic", fake_semantic)

    yield SimpleNamespace(
        client=client,
        sync_factory=sync_factory,
        pipeline=pipeline,
        builder=builder,
        embedder=embedder,
    )

    with sync_factory() as s:
        _purge(s)
    if client.collections.exists(CLASS_NAME):
        client.collections.delete(CLASS_NAME)
    client.close()
    sync_engine.dispose()


def _purge(s) -> None:
    from backend.db.models import DocumentVersionChunk

    for row in s.execute(
        select(Document).where(Document.source_id.like(f"{PREFIX}%"))
    ).scalars():
        s.delete(row)
    for row in s.execute(
        select(DocumentVersion).where(DocumentVersion.source_id.like(f"{PREFIX}%"))
    ).scalars():
        s.delete(row)
    for row in s.execute(
        select(DocumentVersionChunk).where(
            DocumentVersionChunk.version_id.in_(select(DocumentVersion.id))
        )
    ).scalars():
        s.delete(row)
    for row in s.execute(
        select(IndexGeneration).where(IndexGeneration.source_id == SRC)
    ).scalars():
        s.delete(row)
    for row in s.execute(select(ZeroSemanticChunk).where(ZeroSemanticChunk.source_id.like(f"{PREFIX}%"))).scalars():
        s.delete(row)
    s.commit()


def _companion() -> RawDocument:
    return _doc(
        CHUNKABLE,
        "# overview\n\nalpha paragraph about connectors and sync.\n\n"
        "beta paragraph about retrieval and ranking.\n\n",
    )

def _zero_rows(sync_factory):
    with sync_factory() as s:
        return s.query(ZeroSemanticChunk).all()


def test_zero_chunk_yield_records_classification_and_partitions(stack):
    """AC1/AC2:确定性 [] ⇒ 分类登记 + excluded 分区;不入账本、零嵌入。"""
    accounting = stack.builder.build_generation(source_id=SRC, docs=[_zero_doc(), _companion()])
    rows = _zero_rows(stack.sync_factory)
    assert len(rows) == 1
    row = rows[0]
    assert row.source_id == ZERO_CHUNK
    assert row.content_fingerprint == _hash("CC = gcc\n\nall: build\n")
    assert row.chunker_policy_fingerprint  # 策略指纹已持久化(确定性版本身份)
    # 分区:excluded(非 failed),不进 new/updated 桶
    assert ZERO_CHUNK in accounting.zero_chunk_docs
    assert ZERO_CHUNK not in accounting.new_docs
    assert ZERO_CHUNK not in accounting.updated_docs
    # 不入账本(无 serving 投影)
    with stack.sync_factory() as s:
        led = s.execute(
            select(Document).where(Document.source_id == ZERO_CHUNK)
        ).scalars().all()
        assert led == []
    # 零嵌入(排除物不产生任何向量工作)
    embedded_all = [t for batch in stack.embedder.calls for t in batch]
    assert all(ZERO_CHUNK not in t for t in embedded_all)


def test_unchanged_next_build_confirms_and_is_idempotent(stack):
    """AC1/AC5:未变更下轮 = 确认(times+1);账目依旧分列;不复活失败。"""
    stack.builder.build_generation(source_id=SRC, docs=[_zero_doc(), _companion()])
    first = _zero_rows(stack.sync_factory)[0].times_confirmed
    accounting = stack.builder.build_generation(source_id=SRC, docs=[_zero_doc(), _companion()])
    rows = _zero_rows(stack.sync_factory)
    assert len(rows) == 1
    assert rows[0].times_confirmed == first + 1
    assert accounting.zero_chunk_docs == [ZERO_CHUNK]


def test_content_change_swaps_fingerprint_in_place(stack):
    """AC3:内容变更 ⇒ 指纹原位换判定(同一行),不残留旧判定。"""
    stack.builder.build_generation(source_id=SRC, docs=[_zero_doc("CC = gcc\n\nall: build\n"), _companion()])
    stack.builder.build_generation(source_id=SRC, docs=[_zero_doc("CC = clang\n\nall: build\n"), _companion()])
    rows = _zero_rows(stack.sync_factory)
    assert len(rows) == 1
    assert rows[0].content_fingerprint == _hash("CC = clang\n\nall: build\n")


def test_later_valid_chunks_activate_and_clear_classification(stack):
    """AC3:内容变为可分块 ⇒ 正常激活 + 零分块分类清除(无陈旧压制)。"""
    stack.builder.build_generation(source_id=SRC, docs=[_zero_doc(), _companion()])
    assert len(_zero_rows(stack.sync_factory)) == 1
    # 「激活清除」路径:先人为登记 CHUNKABLE 的陈旧分类,再构建可分块文档
    with stack.sync_factory() as s:
        s.add(ZeroSemanticChunk(
            source_id=CHUNKABLE,
            content_fingerprint=_hash("stale"),
            chunker_policy_fingerprint="stale-policy",
            times_confirmed=1,
        ))
        s.commit()
    # 内容变更 ⇒ updated ⇒ 重建(真实语义:激活清除发生在重建代)
    changed = _doc(
        CHUNKABLE,
        "# overview v2\n\nalpha paragraph about connectors and sync.\n\n"
        "beta paragraph about retrieval and ranking.\n\n"
        "gamma paragraph about atomic generations.\n\n",
    )
    accounting = stack.builder.build_generation(source_id=SRC, docs=[changed])
    assert CHUNKABLE in accounting.updated_docs
    with stack.sync_factory() as s:
        assert s.get(ZeroSemanticChunk, CHUNKABLE) is None  # 分类被激活清除


def test_chunker_exception_stays_failed_never_zero_chunk_truth(stack, monkeypatch):
    """AC4:chunker 异常 = failed(fail-closed),绝不登记零分块真值。"""
    import backend.pipeline.generation_builder as gb

    def boom_semantic(doc, max_tokens, overlap):
        if doc.source_id == ZERO_CHUNK:
            raise RuntimeError("chunker boom")
        return []

    monkeypatch.setattr(gb, "chunk_document_semantic", boom_semantic)
    with pytest.raises(Exception) as excinfo:
        stack.builder.build_generation(source_id=SRC, docs=[_zero_doc()])
    assert "chunker boom" in str(excinfo.value)
    assert _zero_rows(stack.sync_factory) == []


# --------------------------------------------------------------------------- #
# REVIEW_1 accounting correction:零分块 ≠ 永久安全排除,两桶不相交,
# eligible_count 不扣除零分块(zero-chunk 仍是 eligible authoritative content)。
# --------------------------------------------------------------------------- #


def _accounting(**kw):
    from backend.pipeline.generation_builder import BuildAccounting

    defaults = dict(
        source_id=SRC,
        new_docs=[],
        updated_docs=[],
        unchanged_docs=[],
        metadata_docs=[],
        excluded_docs=[],
        zero_chunk_docs=[],
    )
    defaults.update(kw)
    return BuildAccounting(**defaults)


def test_review1_only_zero_chunk_not_permanent_excluded_and_stays_eligible():
    """REVIEW_1:仅零分块批次 ⇒ permanent_excluded 不出现(0),零分块独立分列,
    eligible_count **包含**零分块(它们仍是 eligible authoritative content)。"""
    from scripts.sync import _exclusion_delta

    acc = _accounting(
        new_docs=["d1"],
        excluded_docs=[ZERO_CHUNK, "z2"],
        zero_chunk_docs=[ZERO_CHUNK, "z2"],
    )
    delta = _exclusion_delta(acc)
    assert delta.get("permanent_excluded", 0) == 0, (
        "零分块绝不是 #91 永久安全排除 —— permanent_excluded 只统计 #91 safety"
    )
    assert delta["zero_semantic_chunk"] == 2, "零分块独立分列"
    assert delta["eligible_count"] == 3, (
        "eligible = new(1) + zero_chunk(2);零分块不得按永久排除从 eligible 扣除"
    )
    assert "permanent_excluded" not in delta or delta["permanent_excluded"] == 0


def test_review1_mixed_safety_and_zero_chunk_buckets_disjoint():
    """REVIEW_1:混合批次 ⇒ permanent_excluded=仅 #91 safety;zero_semantic_chunk=仅零分块;
    两桶不相交,且 eligible = total − safety(零分块保留在 eligible 侧)。"""
    from scripts.sync import _exclusion_delta

    acc = _accounting(
        new_docs=["n1"],
        unchanged_docs=["u1"],
        excluded_docs=["safety1", ZERO_CHUNK],
        zero_chunk_docs=[ZERO_CHUNK],
    )
    delta = _exclusion_delta(acc)
    assert delta["permanent_excluded"] == 1, "只有 #91 safety exclusion 计入永久排除"
    assert delta["zero_semantic_chunk"] == 1, "零分块独立分列,与 permanent_excluded 不相交"
    assert delta["eligible_count"] == 3, "eligible = n1 + u1 + zero_chunk(1) (total 4 − safety 1)"
    # 守恒算术:eligible + permanent_excluded == 全部参与判定的文档数
    assert delta["eligible_count"] + delta["permanent_excluded"] == 4


def test_review1_pure_safety_accounting_unchanged():
    """既有 #91 行为零回归:纯 safety 排除 ⇒ permanent_excluded=N,eligible 扣除之。"""
    from scripts.sync import _exclusion_delta

    acc = _accounting(
        new_docs=["ok1", "ok2"],
        excluded_docs=["bin1"],
        zero_chunk_docs=[],
    )
    delta = _exclusion_delta(acc)
    assert delta["permanent_excluded"] == 1
    assert delta["eligible_count"] == 2
    assert "zero_semantic_chunk" not in delta, "无零分块 ⇒ 不制造无信息键"


def test_review1_accounting_arithmetic_truthful_over_all_partitions():
    """REVIEW_1:任意分区组合下 eligible+permanent_excluded == 参与判定总数,
    且 zero_semantic_chunk ∈ eligible 侧、与 permanent_excluded 恒不相交。"""
    from scripts.sync import _exclusion_delta

    acc = _accounting(
        new_docs=["n1", "n2"],
        updated_docs=["up1"],
        unchanged_docs=["u1", "u2", "u3"],
        metadata_docs=["m1"],
        excluded_docs=["s1", "s2", "z1", "z2", "z3"],
        zero_chunk_docs=["z1", "z2", "z3"],
    )
    delta = _exclusion_delta(acc)
    total_input = 7 + 5  # new2 + updated1 + unchanged3 + metadata1 + safety2 + zero3
    assert delta["eligible_count"] + delta["permanent_excluded"] == total_input
    assert delta["permanent_excluded"] == 2, "safety-only"
    assert delta["zero_semantic_chunk"] == 3
    # disjoint: 永久排除与零分块两桶之和无歧义(z 们在 eligible 侧,不在 permanent 侧)
    assert delta["eligible_count"] == total_input - 2
