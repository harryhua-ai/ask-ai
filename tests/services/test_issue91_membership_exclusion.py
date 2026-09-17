"""Issue #91 membership 面单元回归:永久排除压制 missing 方向(AC4/AC10)。

契约:RECONCILABLE AUTHORITY = AUTHORITATIVE MEMBERSHIP − DETERMINISTIC
PERMANENT INGESTION EXCLUSIONS。排除物:
- 不再作为 actionable missing 反复上报(生产循环的直接根因面);
- 在对账事实(MembershipReconciliation.excluded_ids)与真值 detail 中如实
  暴露 —— 不假收敛(绝不把排除物插成在服账本行);
- 若身份已入服(政策放宽后重新灌入),陈旧登记不再压制任何事实。
"""

from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.config import load_settings
from backend.db.models import Document, DocumentVersion
from backend.db.session import get_engine, get_session_factory, init_db
from backend.services.membership_currency import reconcile_membership, truth_detail_of

pytestmark = pytest.mark.asyncio(loop_scope="session")

# DSN 纪律:load_settings() 首调会经 dotenv 把 .env 的 TEST_DATABASE_URL 注入
# 进程环境;异步(账本 seed)与同步(对账)两个引擎面必须在同一次解析上取值
# —— 惰性求值时机不同会落到不同库(ask_ai vs ask_ai_test,本套件实证教训)。
load_settings()  # 触发 dotenv 注入,统一两面的 DSN 解析
_DSN = os.environ.get("TEST_DATABASE_URL", load_settings().postgres_dsn)

SRC = "i91memb-local"
OK = f"{SRC}/main/docs/overview.md"
BIN = f"{SRC}/main/fw/x.mbin"
GONE = f"{SRC}/main/docs/gone.md"


def _hash(x: str) -> str:
    return hashlib.sha256(x.encode()).hexdigest()


@dataclass
class _Connector:
    members: set[str]

    def membership_source_ids(self) -> set[str]:
        return set(self.members)


@pytest_asyncio.fixture(loop_scope="session")
async def db_engine():
    engine = get_engine(_DSN)
    try:
        await init_db(engine)
        from scripts.migrate_add_membership_currency import migrate as _migrate

        await _migrate(engine)
        # #91/#92 幂等迁移(共享测试库:补表 + 身份列补容)
        from scripts.migrate_add_ingestion_exclusions import migrate as _excl
        from scripts.migrate_widen_document_source_id_500 import migrate as _widen

        await _excl(engine)
        await _widen(engine)
        yield engine
    finally:
        f = get_session_factory(engine)
        async with f() as session:
            from backend.db.models import DataSource

            await session.execute(delete(DataSource).where(DataSource.id == SRC))
            await session.execute(delete(Document).where(Document.source_id.like(f"{SRC}/%")))
            await session.execute(
                delete(DocumentVersion).where(DocumentVersion.source_id.like(f"{SRC}/%"))
            )
            from backend.db.models import IngestionExclusion

            await session.execute(
                delete(IngestionExclusion).where(
                    IngestionExclusion.source_id.like(f"{SRC}/%")
                )
            )
            await session.commit()
        await engine.dispose()


@pytest.fixture
def sync_factory():
    import sqlalchemy

    engine = sqlalchemy.create_engine(_DSN.replace("+asyncpg", "+psycopg2"))
    try:
        yield sqlalchemy.orm.sessionmaker(bind=engine)
    finally:
        engine.dispose()


def _seed_exclusion(sync_factory, source_id: str) -> None:
    from backend.db.models import IngestionExclusion

    with sync_factory() as session:
        session.add(
            IngestionExclusion(
                source_id=source_id,
                content_hash=_hash("x"),
                reason="binary_content",
                detail="NUL byte in head sample",
                stage="SAFETY_FILTER",
            )
        )
        session.commit()


async def _seed_document(db_engine, source_id: str, lifecycle: str) -> None:
    from backend.db.models import DataSource
    from backend.services.document_lifecycle import DocLifecycle

    factory = get_session_factory(db_engine)
    async with factory() as session:
        session.add(DataSource(id=SRC, type="github", product="wiki", config={}))
        doc = Document(
            source_id=source_id,
            source_type="github",
            product="wiki",
            title="t",
            url=f"https://x/{source_id}",
            branch="main",
            chunk_count=1,
            content_hash=_hash(source_id),
            lifecycle=lifecycle,
        )
        session.add(doc)
        if lifecycle in DocLifecycle.SERVING:
            session.add(
                DocumentVersion(
                    source_id=source_id,
                    version_seq=1,
                    content_hash=doc.content_hash,
                    metadata_hash=_hash("m" + source_id),
                    generation_id="00000000-0000-0000-0000-000000000000",
                    generation_ordinal=0,
                    status="active",
                    title="t",
                    url=doc.url,
                    chunk_count=1,
                )
            )
        await session.commit()


async def test_excluded_identity_suppressed_from_missing(db_engine, sync_factory):
    """排除物在枚举内、不在服:missing 不含它,excluded_ids 如实暴露。"""
    await _seed_document(db_engine, OK, "active")
    _seed_exclusion(sync_factory, BIN)
    connector = _Connector(members={OK, BIN, GONE})
    result = reconcile_membership(sync_factory, connector, SRC, reason="i91:test")
    assert result.missing_ids == (GONE,), "排除物不是 actionable missing;真缺失照常上报"
    assert result.excluded_ids == (BIN,), "排除事实必须单独暴露(AC10)"
    assert result.stale_ids == ()
    detail = truth_detail_of(result)
    assert detail["excluded_sample"] == [BIN]
    assert detail["missing_sample"] == [GONE], "真缺失(从未灌入)照常上报"


async def test_exclusion_suppression_does_not_touch_fresh_missing(db_engine, sync_factory):
    """无任何排除登记时对账事实与 #82 语义逐字节一致(不回归)。"""
    await _seed_document(db_engine, OK, "active")
    connector = _Connector(members={OK, GONE})
    result = reconcile_membership(sync_factory, connector, SRC, reason="i91:ctrl")
    assert result.missing_ids == (GONE,)
    assert result.excluded_ids == ()
