"""P1 生命周期服务门测试(词表 / 判定 / 原语 / active 集 / 退休时序)。

契约锚点(docs/engineering/tasks/tb-p1-lifecycle-foundation-plan.md):
- FC-3 / Freeze FIX-3:P 轴**无 ACTIVE** 处理态;激活 = current_version
  关系翻转,不新增状态;
- Freeze §8a(915b5f7)接替时序:替代权威确立即时失去现势;服务撤出 ≤1 天
  (本模型=激活事务提交即时撤出);RETIRED 保留 7 天后可自动物理 GC;
  已废除的「墓碑 30 天默认」禁止回用;
- 服务选择唯一权威 = Postgres(I-1):active 集由 documents.current_version_id
  关系计算,绝不从向量索引反推。

真实 Postgres(TEST_DATABASE_URL;模型列含 PG UUID/JSONB,SQLite 不兼容)。
"""

import os
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.db.models import (
    Base,
    Document,
    DocumentVersion,
    IndexGeneration,
)
from backend.services import document_lifecycle as lifecycle

TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test",
).replace("+asyncpg", "+psycopg2")

SRC = "p1lf-lifecycle-probe"


@pytest.fixture()
def db():
    engine = create_engine(TEST_DSN)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as s:
        _purge(s)
    yield factory
    with factory() as s:
        _purge(s)
    engine.dispose()


def _purge(s) -> None:
    for row in s.execute(
        select(Document).where(Document.source_id.like(f"{SRC}%"))
    ).scalars():
        s.delete(row)
    for row in s.execute(
        select(DocumentVersion).where(DocumentVersion.source_id.like(f"{SRC}%"))
    ).scalars():
        s.delete(row)
    for row in s.execute(
        select(IndexGeneration).where(IndexGeneration.source_id == SRC)
    ).scalars():
        s.delete(row)
    s.commit()


def _make_doc(sid: str, *, content_hash: str = "h1", chunk_count: int = 2) -> Document:
    return Document(
        source_id=sid,
        content_hash=content_hash,
        source_type="github",
        product="probe",
        title=sid,
        url=f"https://x/{sid}",
        metadata_={},
        branch="",
        chunk_count=chunk_count,
    )


# --------------------------------------------------------------------------- #
# 词表红线(FC-3 / §8a)
# --------------------------------------------------------------------------- #


def test_p_axis_has_no_active_state():
    """P 轴词表无 ACTIVE:激活是关系翻转,不是处理状态(FIX-3/FC-3)。"""
    assert "active" not in lifecycle.GenerationStatus.ALL
    assert lifecycle.GenerationStatus.ALL == (
        lifecycle.GenerationStatus.PENDING,
        lifecycle.GenerationStatus.PROCESSING,
        lifecycle.GenerationStatus.READY,
        lifecycle.GenerationStatus.FAILED,
        lifecycle.GenerationStatus.RETIRED,
    )
    # 激活不引入 READY→ACTIVE 转换:词表没有 ACTIVE 可言
    assert not hasattr(lifecycle.GenerationStatus, "ACTIVE")


def test_supersession_timing_constants_frozen():
    """§8a 冻结时序:7 天 RETIRED 保留 + ≤1 天撤出上限;30 天默认不得回用。"""
    assert lifecycle.RETIRED_RETENTION_DAYS == 7
    assert lifecycle.SERVING_WITHDRAWAL_MAX_DAYS == 1
    # 已废除的 30 天墓碑默认禁止以任何形式回用为现役默认
    for name in dir(lifecycle):
        if "TOMBSTONE" in name or "GC_DEFAULT" in name:
            assert "30" not in name
    assert not hasattr(lifecycle, "TOMBSTONE_DAYS_DEFAULT")


def test_serving_and_withdrawn_partitions():
    """服务集 = active ∪ missing_candidate(缺席宽限);withdrawn 即时退出。"""
    assert lifecycle.DocLifecycle.SERVING == ("active", "missing_candidate")
    assert lifecycle.DocLifecycle.WITHDRAWN == ("superseded", "deleted")
    assert set(lifecycle.DocLifecycle.SERVING) & set(lifecycle.DocLifecycle.WITHDRAWN) == set()


# --------------------------------------------------------------------------- #
# 变更类别(FC-6)
# --------------------------------------------------------------------------- #


def test_classify_change_classes(db):
    with db() as s:
        # 无账本行 → NEW_VERSION(首灌)
        assert lifecycle.classify_change(None, None, "h1", "m1") == lifecycle.ChangeClass.NEW_VERSION
        doc = _make_doc(f"{SRC}/cls")
        s.add(doc)
        s.flush()
        ver = lifecycle.ensure_initial_version(s, doc)
        s.commit()
        assert lifecycle.classify_change(doc, ver, ver.content_hash, ver.metadata_hash) == (
            lifecycle.ChangeClass.UNCHANGED
        )
        assert lifecycle.classify_change(doc, ver, "other-hash", ver.metadata_hash) == (
            lifecycle.ChangeClass.CONTENT_CHANGED
        )
        assert lifecycle.classify_change(doc, ver, ver.content_hash, "other-meta") == (
            lifecycle.ChangeClass.METADATA_CHANGED
        )


def test_metadata_hash_order_insensitive():
    """等价 metadata(键序不同)→ 同一 metadata_hash(FC-5 幂等前提)。"""
    kw = {"title": "t", "url": "u", "branch": "b", "source_type": "github", "product": "p"}
    h1 = lifecycle.compute_metadata_hash(
        metadata={"a": 1, "b": 2}, channel_visibility=("widget",), **kw
    )
    h2 = lifecycle.compute_metadata_hash(
        metadata={"b": 2, "a": 1}, channel_visibility=("widget",), **kw
    )
    assert h1 == h2


# --------------------------------------------------------------------------- #
# active generation 集(服务选择唯一权威,I-1)
# --------------------------------------------------------------------------- #


def test_active_generation_ordinals_follow_current_version_and_lifecycle(db):
    """active 集 = SERVING 文档的 current 版本代序;墓碑/接替即时退出。"""
    with db() as s:
        lifecycle.ensure_legacy_generation(s)
        lifecycle.create_generation(s, SRC)
        doc = _make_doc(f"{SRC}/ord")
        s.add(doc)
        s.flush()
        ver = lifecycle.ensure_initial_version(s, doc)
        assert ver.generation_ordinal == lifecycle.LEGACY_GENERATION_ORDINAL
        s.commit()

        # 缺席候选仍在服务集(宽限期保上一代)
        lifecycle.mark_missing_candidate(s, f"{SRC}/ord")
        s.commit()
        assert lifecycle.active_generation_ordinals_sync(s) == [0]

        # 墓碑 → 即时退出服务集(≤1 天撤出上限的强形态)
        lifecycle.tombstone_document(s, f"{SRC}/ord")
        s.commit()
        assert lifecycle.active_generation_ordinals_sync(s) == []

        # 恢复 → 回到服务集
        lifecycle.restore_document(s, f"{SRC}/ord")
        s.commit()
        assert lifecycle.active_generation_ordinals_sync(s) == [0]


# --------------------------------------------------------------------------- #
# 激活原子语义(FC-6 接替动词;P1-D)
# --------------------------------------------------------------------------- #


def test_activation_supersedes_predecessor_and_flips_pointer_exactly_once(db):
    """激活:前任 unique superseded 留痕,指针单次翻转,恢复语义内置。"""
    with db() as s:
        gen1 = lifecycle.create_generation(s, SRC)
        doc = _make_doc(f"{SRC}/act", content_hash="v1")
        s.add(doc)
        s.flush()
        v1 = DocumentVersion(
            source_id=doc.source_id,
            version_seq=1,
            content_hash="v1",
            metadata_hash="m1",
            generation_id=gen1.id,
            generation_ordinal=gen1.ordinal,
            status="active",
            title="t1",
            url="u1",
            chunk_count=1,
        )
        s.add(v1)
        s.flush()
        doc.current_version_id = v1.id
        s.commit()

        gen2 = lifecycle.create_generation(s, SRC)
        assert gen2.ordinal == gen1.ordinal + 1  # ordinal 单调分配
        v2 = DocumentVersion(
            source_id=doc.source_id,
            version_seq=2,
            content_hash="v2",
            metadata_hash="m1",
            generation_id=gen2.id,
            generation_ordinal=gen2.ordinal,
            status="active",
            title="t2",
            url="u1",
            chunk_count=3,
        )
        s.add(v2)
        s.flush()
        previous = lifecycle.activate_document_version(s, doc, v2)
        s.commit()

        assert previous is v1
        assert v1.status == "superseded" and v1.valid_to is not None
        assert v1.superseded_by_version_id == v2.id
        assert doc.current_version_id == v2.id
        assert doc.content_hash == "v2" and doc.chunk_count == 3
        # Current Truth 恰一个:active 版本唯一(P1-D)
        actives = s.execute(
            select(DocumentVersion).where(
                DocumentVersion.source_id == doc.source_id,
                DocumentVersion.status == "active",
            )
        ).scalars().all()
        assert [v.id for v in actives] == [v2.id]
        # 接替后服务集只剩新代(撤出=激活提交即时)
        assert lifecycle.active_generation_ordinals_sync(s) == [gen2.ordinal]


def test_tombstone_idempotent_and_non_destructive(db):
    """墓碑幂等 + 逻辑删除:账本行与版本链保留,物理清除仅经 GC。"""
    with db() as s:
        doc = _make_doc(f"{SRC}/tomb")
        s.add(doc)
        s.flush()
        lifecycle.ensure_initial_version(s, doc)
        s.commit()
        assert lifecycle.tombstone_document(s, f"{SRC}/tomb") is True
        assert lifecycle.tombstone_document(s, f"{SRC}/tomb") is False  # 幂等
        row, ver = lifecycle.load_document_and_current_version(s, f"{SRC}/tomb")
        assert row is not None and row.lifecycle == "deleted"
        assert ver is not None  # 版本链保留(非破坏)


# --------------------------------------------------------------------------- #
# 退休与 GC 资格(§8a:RETIRED only after withdrawal;+7 天)
# --------------------------------------------------------------------------- #


def test_retire_only_after_withdrawal_and_gc_eligible_plus_7d(db):
    """有 active 版本引用的代不得 retired;撤出后 retired + gc=+7 天。"""
    with db() as s:
        gen = lifecycle.create_generation(s, SRC)
        doc = _make_doc(f"{SRC}/ret")
        s.add(doc)
        s.flush()
        ver = DocumentVersion(
            source_id=doc.source_id,
            version_seq=1,
            content_hash="h",
            metadata_hash="m",
            generation_id=gen.id,
            generation_ordinal=gen.ordinal,
            status="active",
            title="t",
            url="u",
            chunk_count=1,
        )
        s.add(ver)
        lifecycle.mark_generation_ready(s, gen, doc_count=1, chunk_count=1)
        s.commit()

        # 版本仍引用该代 → 不得退休(RETIREMENT/RETIRED 只在撤出后)
        assert lifecycle.retire_generation_if_withdrawn(s, gen.id) is False
        assert gen.status == lifecycle.GenerationStatus.READY

        ver.status = "superseded"
        s.commit()
        assert lifecycle.retire_generation_if_withdrawn(s, gen.id) is True
        assert gen.status == lifecycle.GenerationStatus.RETIRED
        assert gen.withdrawn_at is not None and gen.retired_at is not None
        expected = gen.retired_at + timedelta(days=lifecycle.RETIRED_RETENTION_DAYS)
        assert gen.gc_eligible_at == expected

        # 幂等:已 retired 不再重复
        assert lifecycle.retire_generation_if_withdrawn(s, gen.id) is False


def test_ensure_initial_version_idempotent(db):
    """初始版本原语幂等:重复调用不产生第二版本/第二指针。"""
    with db() as s:
        doc = _make_doc(f"{SRC}/init")
        s.add(doc)
        s.flush()
        v1 = lifecycle.ensure_initial_version(s, doc)
        v2 = lifecycle.ensure_initial_version(s, doc)
        s.commit()
        assert v1.id == v2.id
        versions = s.execute(
            select(DocumentVersion).where(DocumentVersion.source_id == doc.source_id)
        ).scalars().all()
        assert len(versions) == 1
        assert doc.current_version_id == v1.id


def test_legacy_generation_is_deterministic_and_singleton(db):
    """迁移初始代:确定性 UUID + ordinal 0,幂等锚(重复迁移无第二初始代)。"""
    with db() as s:
        g1 = lifecycle.ensure_legacy_generation(s)
        g2 = lifecycle.ensure_legacy_generation(s)
        s.commit()
        assert g1.id == g2.id == lifecycle.LEGACY_GENERATION_ID
        assert g1.ordinal == lifecycle.LEGACY_GENERATION_ORDINAL == 0
        assert lifecycle.LEGACY_GENERATION_ID == uuid.uuid5(
            uuid.NAMESPACE_URL, "ask-ai:p1:legacy-initial-generation"
        )


def test_extract_source_version_known_keys_only():
    """源版本元数据渐进提取:已知键、诚实未知(None)。"""
    assert lifecycle.extract_source_version({"commit_sha": "abc"}) == {"commit_sha": "abc"}
    assert lifecycle.extract_source_version({"commit_sha": None, "other": 1}) is None
    assert lifecycle.extract_source_version("not-a-dict") is None
