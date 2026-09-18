"""Issue #94:membership 对账的零分块压制方向(与 #91 安全排除严格分列)。

契约(#94 ght-contract AC3/AC5):
- 窗口内零分块分类 + 内容指纹一致 ⇒ 不计入 actionable missing(有界压制);
- 内容指纹漂移 ⇒ 立即失效,身份重回 actionable missing(重评估);
- 与 #91 安全排除(excluded_ids)**分列暴露**(zero_chunk_ids),绝不混算;
- truth detail 如实采样(不假收敛,绝不插成在服账本行)。
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.orm import sessionmaker

from backend.config import load_settings
from backend.db.models import Document, DocumentVersion, ZeroSemanticChunk
from backend.db.session import get_engine, get_session_factory, init_db
from backend.services.membership_currency import reconcile_membership, truth_detail_of

pytestmark = pytest.mark.asyncio(loop_scope="session")

load_settings()  # 触发 dotenv 注入,统一两面 DSN 解析
_DSN = os.environ.get("TEST_DATABASE_URL", load_settings().postgres_dsn)

SRC = "i94memb-local"
KEPT = f"{SRC}/main/docs/kept.md"  # 在服成员(对照组)
ZC = f"{SRC}/main/Makefile"  # 零分块身份
SAFE_EX = f"{SRC}/main/fw/x.mbin"  # #91 安全排除身份(分列对照)


def _hash(x: str) -> str:
    return hashlib.sha256(x.encode()).hexdigest()


@dataclass
class _Connector:
    members: set[str]
    fingerprints: dict[str, str] = field(default_factory=dict)

    def membership_source_ids(self) -> set[str]:
        return set(self.members)

    def membership_content_fingerprints(self, ids):
        return {i: self.fingerprints[i] for i in ids if i in self.fingerprints}


@pytest_asyncio.fixture(loop_scope="session")
async def db_engine():
    engine = get_engine(_DSN)
    try:
        await init_db(engine)
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture(loop_scope="session")
async def seeded(db_engine):
    """在服账本行 + 三个权威身份(在服/零分块/安全排除)。"""
    factory = get_session_factory(db_engine)
    async with factory() as s:
        await s.execute(delete(Document).where(Document.source_id.like(f"{SRC}/%")))
        await s.execute(delete(ZeroSemanticChunk).where(ZeroSemanticChunk.source_id.like(f"{SRC}/%")))
        s.add(
            Document(
                source_id=KEPT,
                source_type="github",
                product="probe",
                title="kept",
                url="https://x/" + KEPT,
                content_hash=_hash("kept"),
            )
        )
        await s.commit()
    yield factory
    async with factory() as s:
        await s.execute(delete(Document).where(Document.source_id.like(f"{SRC}/%")))
        await s.execute(delete(DocumentVersion).where(DocumentVersion.source_id.like(f"{SRC}/%")))
        await s.execute(delete(ZeroSemanticChunk).where(ZeroSemanticChunk.source_id.like(f"{SRC}/%")))
        await s.commit()


async def _seed_zero_chunk(factory, source_id, *, fp, age_days=0, policy="policy-v1"):
    from datetime import datetime, timezone

    ts = datetime.now(timezone.utc) - timedelta(days=age_days)
    async with factory() as s:
        s.add(
            ZeroSemanticChunk(
                source_id=source_id,
                content_fingerprint=fp,
                chunker_policy_fingerprint=policy,
                times_confirmed=1,
                first_seen_at=ts,
                last_confirmed_at=ts,
            )
        )
        await s.commit()


async def _run(seeded, fingerprints: dict[str, str]):
    connector = _Connector(
        members={KEPT, ZC, SAFE_EX},
        fingerprints=fingerprints,
    )
    from sqlalchemy import create_engine

    sync_engine = create_engine(_DSN.replace("+asyncpg", "+psycopg2"))
    sync_factory = sessionmaker(sync_engine, expire_on_commit=False)
    try:
        result = reconcile_membership(sync_factory, connector, SRC, reason="i94-probe")
    finally:
        sync_engine.dispose()
    return result


async def test_zero_chunk_in_window_suppressed_separately(seeded):
    """窗口内 + 指纹一致 ⇒ 零分块身份不入 missing,单列 zero_chunk_ids。"""
    factory = seeded
    await _seed_zero_chunk(factory, ZC, fp=_hash("makefile-content"), age_days=0)
    result = await _run(seeded, {ZC: _hash("makefile-content")})
    assert ZC not in result.missing_ids
    assert result.zero_chunk_ids == (ZC,)
    # 与安全排除分列:excluded_ids 不含零分块身份
    assert ZC not in result.excluded_ids


async def test_zero_chunk_fingerprint_drift_reopens_missing(seeded):
    """内容指纹漂移 ⇒ 立即失效压制,身份重回 actionable missing。"""
    factory = seeded
    await _seed_zero_chunk(factory, ZC, fp=_hash("old-makefile"), age_days=0)
    result = await _run(seeded, {ZC: _hash("new-makefile")})
    assert ZC in result.missing_ids
    assert result.zero_chunk_ids == ()


async def test_expired_zero_chunk_window_reopens_missing(seeded):
    """窗口过期(无新鲜确认)⇒ 有界重评估:身份重回 missing(AC3 兜底)。"""
    factory = seeded
    await _seed_zero_chunk(factory, ZC, fp=_hash("makefile-content"), age_days=30)
    result = await _run(seeded, {ZC: _hash("makefile-content")})
    assert ZC in result.missing_ids
    assert result.zero_chunk_ids == ()


async def test_zero_chunk_and_safety_exclusion_are_disjoint_buckets(seeded):
    """AC5:安全排除(excluded_ids)与零分块(zero_chunk_ids)同轮分列,不混算。"""
    factory = seeded
    await _seed_zero_chunk(factory, ZC, fp=_hash("makefile-content"), age_days=0)
    # #91 安全排除登记(SAFE_EX;窗口内)
    from datetime import datetime, timezone

    from backend.services.ingestion_exclusions import record_permanent_exclusion

    from sqlalchemy import create_engine

    sync_engine = create_engine(_DSN.replace("+asyncpg", "+psycopg2"))
    sync_factory = sessionmaker(sync_engine, expire_on_commit=False)
    record_permanent_exclusion(
        sync_factory,
        source_id=SAFE_EX,
        content_hash=_hash("binary"),
        reason="binary_content",
        detail="probe",
        stage="safety_filter",
        now=datetime.now(timezone.utc),
    )
    sync_engine.dispose()
    result = await _run(
        seeded,
        {ZC: _hash("makefile-content"), SAFE_EX: _hash("binary")},
    )
    assert result.zero_chunk_ids == (ZC,)
    assert result.excluded_ids == (SAFE_EX,)
    assert ZC not in result.missing_ids
    assert SAFE_EX not in result.missing_ids
    assert result.missing_ids == ()


async def test_truth_detail_exposes_zero_chunk_sample(seeded):
    factory = seeded
    await _seed_zero_chunk(factory, ZC, fp=_hash("makefile-content"), age_days=0)
    result = await _run(seeded, {ZC: _hash("makefile-content")})
    detail = truth_detail_of(result)
    assert detail["zero_chunk_sample"] == [ZC]
