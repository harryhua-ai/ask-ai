"""Issue #94:零语义分块确定性分类的服务面单元测试。

契约(#94 ght-contract AC2/AC3):
- 每身份恰一行 = 对其当前权威内容的判定:persist source identity、内容指纹、
  零分块结果、chunker 策略指纹(确定性版本身份)、审计时间戳与确认次数;
- 与安全排除(#91 ingestion_exclusions)严格分表,绝不复用语义;
- 内容指纹或策略指纹变化 ⇒ 原位换判定(压制永不凌驾于新观察之上);
- 无可靠指纹的源按有界窗口重评估(不过期永久压制)。
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.db.models import Base, ZeroSemanticChunk
from backend.services.zero_semantic_chunks import (
    ZERO_CHUNK_REEVALUATION_DAYS,
    delete_for_identities,
    purge_expired_out_of_authority,
    record_zero_semantic_chunk,
    suppression_cutoff,
)

TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test",
).replace("+asyncpg", "+psycopg2")

SRC = "i94svc-local"
A = f"{SRC}/main/Makefile"
B = f"{SRC}/main/CMakeLists.txt"

FP1 = "f" * 64
FP2 = "e" * 64
POLICY_V1 = "policy-v1"
POLICY_V2 = "policy-v2"


@pytest.fixture()
def db():
    engine = create_engine(TEST_DSN)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as s:
        for row in s.query(ZeroSemanticChunk).all():
            s.delete(row)
        s.commit()
    yield factory
    with factory() as s:
        for row in s.query(ZeroSemanticChunk).all():
            s.delete(row)
        s.commit()
    engine.dispose()


def test_record_persists_full_deterministic_identity(db):
    """AC2:身份/内容指纹/策略指纹/零分块结果/审计时间戳全持久化。"""
    now = datetime(2026, 9, 18, 12, 0, 0, tzinfo=UTC)
    record_zero_semantic_chunk(
        db,
        source_id=A,
        content_fingerprint=FP1,
        chunker_policy_fingerprint=POLICY_V1,
        detail="semantic",
        now=now,
    )
    with db() as s:
        row = s.get(ZeroSemanticChunk, A)
        assert row is not None
        assert row.content_fingerprint == FP1
        assert row.chunker_policy_fingerprint == POLICY_V1
        assert row.times_confirmed == 1
        assert row.first_seen_at is not None
        assert row.last_confirmed_at is not None


def test_reconfirm_same_fingerprints_advances_confirmation(db):
    """同内容同策略再次零分块 = 确认(计数+1,末次确认前移;幂等非失败)。"""
    t1 = datetime(2026, 9, 18, 12, 0, 0, tzinfo=UTC)
    t2 = t1 + timedelta(hours=1)
    record_zero_semantic_chunk(
        db, source_id=A, content_fingerprint=FP1,
        chunker_policy_fingerprint=POLICY_V1, detail="semantic", now=t1,
    )
    record_zero_semantic_chunk(
        db, source_id=A, content_fingerprint=FP1,
        chunker_policy_fingerprint=POLICY_V1, detail="semantic", now=t2,
    )
    with db() as s:
        row = s.get(ZeroSemanticChunk, A)
        assert row.times_confirmed == 2
        assert row.first_seen_at == t1
        assert row.last_confirmed_at == t2


def test_content_fingerprint_change_swaps_verdict_in_place(db):
    """内容指纹变化 ⇒ 原位换判定(first_seen 保留审计,判定内容更新)。"""
    t1 = datetime(2026, 9, 18, 12, 0, 0, tzinfo=UTC)
    record_zero_semantic_chunk(
        db, source_id=A, content_fingerprint=FP1,
        chunker_policy_fingerprint=POLICY_V1, detail="semantic", now=t1,
    )
    t2 = t1 + timedelta(minutes=5)
    record_zero_semantic_chunk(
        db, source_id=A, content_fingerprint=FP2,
        chunker_policy_fingerprint=POLICY_V1, detail="semantic", now=t2,
    )
    with db() as s:
        rows = s.query(ZeroSemanticChunk).all()
        assert len(rows) == 1  # 每身份恰一行
        row = rows[0]
        assert row.content_fingerprint == FP2
        assert row.first_seen_at == t1
        assert row.last_confirmed_at == t2


def test_policy_fingerprint_change_swaps_verdict_in_place(db):
    """chunker 策略指纹变化 ⇒ 原位换判定(策略演进的确定性重评估路径)。"""
    record_zero_semantic_chunk(
        db, source_id=B, content_fingerprint=FP1,
        chunker_policy_fingerprint=POLICY_V1, detail="semantic",
    )
    record_zero_semantic_chunk(
        db, source_id=B, content_fingerprint=FP1,
        chunker_policy_fingerprint=POLICY_V2, detail="semantic",
    )
    with db() as s:
        row = s.get(ZeroSemanticChunk, B)
        assert row.chunker_policy_fingerprint == POLICY_V2
        assert row.times_confirmed == 2


def test_delete_for_identities_clears_classification(db):
    """后来产出有效分块 ⇒ 激活面调用删除,分类清除(AC3 后半)。"""
    record_zero_semantic_chunk(
        db, source_id=A, content_fingerprint=FP1,
        chunker_policy_fingerprint=POLICY_V1, detail="semantic",
    )
    with db() as s:
        delete_for_identities(s, [A])
        assert s.get(ZeroSemanticChunk, A) is None
    # 幂等:重复删除安全
    with db() as s:
        delete_for_identities(s, [A])


def test_suppression_window_is_bounded():
    """AC3:无可靠指纹的源按有界窗口重评估,窗口起点 = now - N 天。"""
    now = datetime.now(UTC)
    cutoff = suppression_cutoff(now)
    assert cutoff == now - timedelta(days=ZERO_CHUNK_REEVALUATION_DAYS)
    assert ZERO_CHUNK_REEVALUATION_DAYS > 0


def test_purge_expired_out_of_authority(db):
    """卫生:窗口过期 ∘ 已不在权威枚举 ⇒ 清除;枚举内过期行保留(重评估请求)。"""
    old = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
    fresh = datetime.now(UTC)
    record_zero_semantic_chunk(
        db, source_id=A, content_fingerprint=FP1,
        chunker_policy_fingerprint=POLICY_V1, detail="semantic", now=old,
    )
    record_zero_semantic_chunk(
        db, source_id=B, content_fingerprint=FP1,
        chunker_policy_fingerprint=POLICY_V1, detail="semantic", now=fresh,
    )
    cutoff = suppression_cutoff(fresh)
    with db() as s:
        purged = purge_expired_out_of_authority(s, SRC, {B}, cutoff=cutoff)
        # 卫生在调用方事务内生效(#91 同构:函数本身不 commit)
        s.commit()
        assert purged == 1
        assert s.get(ZeroSemanticChunk, A) is None  # 过期 + 不在枚举 → 清除
        assert s.get(ZeroSemanticChunk, B) is not None  # 枚举内 → 保留
