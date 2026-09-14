"""INC-WEB-EMBED-413 矫正迁移测试:清除误挂进现行版本的越界 chunk 行。

范围契约(migrate_remove_contaminated_version_chunks):
- 删除:generation_ordinal > 0 的版本上 chunk_index >= chunk_count 的行
  (构建激活不变量被回填误挂破坏的行,生产 2026-09-14 实证 3 行/2 文档);
- 保留:ordinal = 0 legacy 初始版本的全量 1:1 拷贝行(迁移冻结契约);
- 保留:ordinal > 0 版本的权威范围内行(idx < chunk_count);
- 幂等:重跑 removed=0;fail-closed:删除数/残留数与计划不符即 raise。

真实 Postgres(一次性数据库);不可达时整文件 skip。
"""

import asyncio
import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.db.models import (
    Base,
    Document,
    DocumentVersion,
    DocumentVersionChunk,
    IndexGeneration,
)
from scripts.migrate_remove_contaminated_version_chunks import migrate

TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test",
).replace("+asyncpg", "+psycopg2")
ADMIN_DSN = TEST_DSN.rsplit("/", 1)[0] + "/postgres"
INC_DB = "ask_ai_inc413_test"
INC_DSN = TEST_DSN.rsplit("/", 1)[0] + "/" + INC_DB
INC_DSN_ASYNC = (
    os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test",
    ).rsplit("/", 1)[0]
    + "/"
    + INC_DB
)

pytestmark = pytest.mark.integration


@pytest.fixture()
def inc_db():
    admin = create_engine(ADMIN_DSN, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{INC_DB}"'))
        c.execute(text(f'CREATE DATABASE "{INC_DB}"'))
    admin.dispose()
    engine = create_engine(INC_DSN)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()
    with create_engine(ADMIN_DSN, isolation_level="AUTOCOMMIT").connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{INC_DB}"'))


def _seed(engine) -> dict:
    """播种生产同型状态(生产 2026-09-14 三行误挂的最小同构):

    - doc-a:legacy v1(ordinal 0,chunk_count 2,行 {0,1} 含超限行)+
      演进 v2(ordinal 10,chunk_count 1,权威行 {0} + 误挂行 idx 1 超限);
    - doc-b:legacy v1(ordinal 0,chunk_count 1,行 {0})+ 演进 v2
      (ordinal 11,chunk_count 1,权威行 {0} + 误挂行 idx 1、idx 2);
    - doc-c:健康 v1(ordinal 3,chunk_count 2,行 {0,1},零误挂)。
    """
    factory = sessionmaker(engine, expire_on_commit=False)
    ids = {}
    with factory() as s:
        # ordinal 全局唯一(生产同约束):恰一个共享 legacy 初始代
        legacy_gen = uuid.uuid5(uuid.NAMESPACE_URL, "legacy:shared")
        s.add(IndexGeneration(id=legacy_gen, ordinal=0, source_id="src-legacy", status="ready"))
        s.flush()
        for sid, cc in (("doc-a", 2), ("doc-b", 1), ("doc-c", 2)):
            s.add(
                Document(
                    content_hash=f"h-{sid}",
                    source_id=sid,
                    source_type="web_crawl",
                    product="probe",
                    title=sid,
                    url=f"https://x/{sid}",
                    branch="",
                    chunk_count=cc if sid != "doc-a" else 1,
                )
            )
        s.flush()
        for sid in ("doc-a", "doc-b", "doc-c"):
            doc = s.query(Document).filter(Document.source_id == sid).one()
            v1 = DocumentVersion(
                source_id=sid,
                version_seq=1,
                content_hash=f"h-{sid}",
                metadata_hash="m1",
                generation_id=legacy_gen,
                generation_ordinal=0,
                status="superseded" if sid != "doc-c" else "active",
                title=sid,
                url=f"https://x/{sid}",
                chunk_count=2 if sid == "doc-a" else 1,
            )
            s.add(v1)
            s.flush()
            n_legacy = 2 if sid in ("doc-a", "doc-c") else 1
            for i in range(n_legacy):
                s.add(
                    DocumentVersionChunk(
                        version_id=v1.id,
                        chunk_index=i,
                        # legacy 版本允许超限行(1:1 拷贝契约;不在矫正范围)
                        text="L" * (3000 if i == 1 and sid == "doc-a" else 100),
                        props={},
                    )
                )
            if sid != "doc-c":
                gen_id = uuid.uuid5(uuid.NAMESPACE_URL, f"gen:{sid}")
                s.add(IndexGeneration(id=gen_id, ordinal=10 if sid == "doc-a" else 11,
                                      source_id=f"src-{sid}", status="ready"))
                v2 = DocumentVersion(
                    source_id=sid,
                    version_seq=2,
                    content_hash=f"h-{sid}-v2",
                    metadata_hash="m2",
                    generation_id=gen_id,
                    generation_ordinal=10 if sid == "doc-a" else 11,
                    status="active",
                    title=sid,
                    url=f"https://x/{sid}",
                    chunk_count=1,
                )
                s.add(v2)
                s.flush()
                s.add(
                    DocumentVersionChunk(
                        version_id=v2.id, chunk_index=0, text="a" * 100, props={}
                    )
                )
                contaminated_indices = [1] if sid == "doc-a" else [1, 2]
                for i in contaminated_indices:
                    s.add(
                        DocumentVersionChunk(
                            version_id=v2.id,
                            chunk_index=i,
                            text="C" * 3000,  # 生产误挂同型:超限 legacy 文本
                            props={},
                        )
                    )
                doc.current_version_id = v2.id
            else:
                doc.current_version_id = v1.id
        s.commit()
        ids["doc_a_v2"] = (
            s.query(DocumentVersion)
            .filter(DocumentVersion.source_id == "doc-a", DocumentVersion.version_seq == 2)
            .one()
            .id
        )
    return ids


def _chunk_rows(engine, version_id):
    with engine.connect() as c:
        return sorted(
            (r[0], r[1])
            for r in c.execute(
                text(
                    "SELECT chunk_index, length(text) FROM document_version_chunks "
                    "WHERE version_id = :vid ORDER BY chunk_index"
                ),
                {"vid": str(version_id)},
            ).all()
        )


def test_corrective_removes_contaminated_rows_preserves_legit(inc_db):
    ids = _seed(inc_db)
    async_engine = create_async_engine(INC_DSN_ASYNC)

    # 迁移前:误挂行在位(生产同型)
    assert _chunk_rows(inc_db, ids["doc_a_v2"]) == [(0, 100), (1, 3000)]

    try:
        stats = asyncio.run(migrate(async_engine))
    finally:
        asyncio.run(async_engine.dispose())

    # 恰清除 3 行误挂(doc-a idx1 + doc-b idx1,idx2),权威范围与 legacy 全保留
    assert stats == {"planned": 3, "removed": 3}
    assert _chunk_rows(inc_db, ids["doc_a_v2"]) == [(0, 100)]

    with inc_db.connect() as c:
        # doc-b v2(ordinal 11)权威行保留
        doc_b_v2 = c.execute(
            text(
                "SELECT id FROM document_versions "
                "WHERE source_id='doc-b' AND version_seq=2"
            )
        ).scalar_one()
        assert _chunk_rows(inc_db, doc_b_v2) == [(0, 100)]
        # legacy ordinal-0 版本的 1:1 全量行(含超限)不在矫正范围,原样保留
        legacy_a = c.execute(
            text(
                "SELECT id FROM document_versions "
                "WHERE source_id='doc-a' AND version_seq=1"
            )
        ).scalar_one()
        assert _chunk_rows(inc_db, legacy_a) == [(0, 100), (1, 3000)]
        # 健康文档零触碰
        doc_c_v1 = c.execute(
            text(
                "SELECT id FROM document_versions "
                "WHERE source_id='doc-c' AND version_seq=1"
            )
        ).scalar_one()
        assert _chunk_rows(inc_db, doc_c_v1) == [(0, 100), (1, 100)]

    # 幂等:重跑零命中
    async_engine2 = create_async_engine(INC_DSN_ASYNC)
    try:
        assert asyncio.run(migrate(async_engine2)) == {"planned": 0, "removed": 0}
    finally:
        asyncio.run(async_engine2.dispose())
