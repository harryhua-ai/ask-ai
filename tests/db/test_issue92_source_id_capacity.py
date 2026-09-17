"""Issue #92 P1 RED→GREEN:canonical source_id 超过 varchar(200) 的无损存储。

生产失败(2026-09-16/17 live,`wiki-documents-local` 每轮):
    StringDataRightTruncation: value too long for type character varying(200)
    documents.source_id ← `wiki-documents-local/main/i18n/en/...`(~245 字符)

契约(Final Acceptance Contract):合法权威身份必须无损可存 —— 禁止截断/
哈希替换/别名;存量 ≤200 身份逐字节不变;迁移幂等且登记 canonical manifest。
"""

from __future__ import annotations

import hashlib
import os
import sys
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.config import load_settings
from backend.db.models import Document, DocumentRepairTask, DocumentRecoveryEvent, DocumentVersion
from backend.db.session import get_engine, get_session_factory, init_db

pytestmark = pytest.mark.asyncio(loop_scope="session")

# 生产实failure 的 canonical 身份(同构构造;>200 字符)
LONG_REL = (
    "i18n/en/docusaurus-plugin-content-docs/current/1-neoedge-ng4500-series/"
    "2-ng4500-cb01-development-board/2-software-guide/"
    "1-driver-installation-and-updates/0-interface-and-modules-configure.md"
)
LONG_ID = f"wiki-documents-local/main/{LONG_REL}"
LONG_ID_2 = LONG_ID + "-sibling.md"
SHORT_ID = "wiki-documents-local/main/short.md"


def _identity_length_guard():
    assert len(LONG_ID) > 200, "fixture 必须是 production-class 长身份"


@pytest_asyncio.fixture(loop_scope="session")
async def db_engine():
    engine = get_engine(
        os.environ.get("TEST_DATABASE_URL", load_settings().postgres_dsn)
    )
    try:
        await init_db(engine)
        from scripts.migrate_add_membership_currency import migrate as _migrate

        await _migrate(engine)
        yield engine
    finally:
        f = get_session_factory(engine)
        async with f() as session:
            await session.execute(delete(Document).where(Document.source_id.in_([LONG_ID, LONG_ID_2, SHORT_ID])))
            await session.execute(delete(DocumentVersion).where(DocumentVersion.source_id.in_([LONG_ID, LONG_ID_2, SHORT_ID])))
            await session.commit()
        await engine.dispose()


async def _insert_document(session, source_id: str, *, superseded_by: str | None = None) -> Document:
    doc = Document(
        source_id=source_id,
        content_hash=hashlib.sha256(source_id.encode()).hexdigest(),
        source_type="github",
        product="wiki",
        title=source_id.rsplit("/", 1)[-1],
        url=f"https://github.com/camthink-ai/wiki-documents/blob/{source_id}",
        metadata_={"path": source_id},
        branch="main",
        chunk_count=2,
        lifecycle="active",
        superseded_by=superseded_by,
    )
    session.add(doc)
    await session.flush()
    version = DocumentVersion(
        id=uuid.uuid4(),
        source_id=source_id,
        version_seq=1,
        content_hash=doc.content_hash,
        metadata_hash=hashlib.sha256(("m" + source_id).encode()).hexdigest(),
        generation_id="00000000-0000-0000-0000-000000000000",
        generation_ordinal=0,
        status="active",
        title=doc.title,
        url=doc.url,
        chunk_count=2,
    )
    session.add(version)
    doc.current_version_id = version.id
    await session.flush()
    return doc


async def test_red_long_identity_insert_fails_on_pre_fix_schema(db_engine):
    """RED(基线)/GREEN(修复后):>200 canonical 身份账本插入无损。"""
    _identity_length_guard()
    factory = get_session_factory(db_engine)
    async with factory() as session:
        doc = await _insert_document(session, LONG_ID, superseded_by=LONG_ID_2)
        await session.commit()
        assert doc.source_id == LONG_ID
        # 逐字节读回(AC3:无截断/哈希/别名)
        row = (
            await session.execute(select(Document).where(Document.source_id == LONG_ID))
        ).scalar_one()
        assert row.source_id == LONG_ID
        assert row.superseded_by == LONG_ID_2
        ver = (
            await session.execute(
                select(DocumentVersion).where(DocumentVersion.source_id == LONG_ID)
            )
        ).scalar_one()
        assert ver.source_id == LONG_ID


async def test_short_identity_byte_for_byte_unchanged(db_engine):
    """AC4:存量 ≤200 身份语义分毫不变(对照)。"""
    factory = get_session_factory(db_engine)
    async with factory() as session:
        await _insert_document(session, SHORT_ID)
        await session.commit()
        row = (
            await session.execute(select(Document).where(Document.source_id == SHORT_ID))
        ).scalar_one()
        assert row.source_id == SHORT_ID


async def test_repair_and_recovery_surfaces_accept_long_identity(db_engine):
    """AC1/AC5:修复/恢复面的身份列与账本容量一致。"""
    factory = get_session_factory(db_engine)
    async with factory() as session:
        task = DocumentRepairTask(
            source_id="wiki-documents-local",
            doc_source_id=LONG_ID,
            status="pending",
        )
        session.add(task)
        event = DocumentRecoveryEvent(
            source_id="wiki-documents-local",
            doc_source_id=LONG_ID,
            outcome="succeeded",
        )
        session.add(event)
        await session.commit()
        assert task.doc_source_id == LONG_ID
        assert event.doc_source_id == LONG_ID


async def test_widening_migration_idempotent_and_complete(db_engine):
    """AC9:迁移幂等;5 个身份列全部 ≥500;重复执行 no-op。"""
    from scripts.migrate_widen_document_source_id_500 import migrate as widen

    await widen(db_engine)
    await widen(db_engine)  # 幂等:第二次执行零错误零变化

    expected = {
        "documents": {"source_id", "superseded_by"},
        "document_versions": {"source_id"},
        "document_repair_tasks": {"doc_source_id"},
        "document_recovery_events": {"doc_source_id"},
    }
    factory = get_session_factory(db_engine)
    async with factory() as session:
        for table, columns in expected.items():
            for column in columns:
                row = (
                    await session.execute(
                        text(
                            "SELECT character_maximum_length FROM information_schema.columns "
                            "WHERE table_name = :t AND column_name = :c"
                        ),
                        {"t": table, "c": column},
                    )
                ).scalar_one()
                assert int(row) >= 500, f"{table}.{column} 容量不足: {row}"
