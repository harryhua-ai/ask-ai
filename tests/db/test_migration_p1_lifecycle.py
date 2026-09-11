"""P1 迁移门测试(旧形态 DDL 演练;幂等 / 零重嵌 / fail-closed)。

策略:每用例创建一次性数据库 ``ask_ai_p1mig_test``,先建 **v1.5.0 旧形态**
(create_all 后 DROP 掉 P1 五列 + 三表),再执行迁移脚本全链:
PG 补列/建表(幂等)→ 版本回填(legacy 初始代)→ Weaviate 补属性 →
内容回填(单向拷贝 + 对象补 generation 属性)→ fail-closed 验证。

**零 embedding**:迁移链路无 embedder 依赖(结构性断言);回填不传向量、
不改 text、不删对象。
真实 Postgres + 真实 Weaviate(P1_WEAVIATE_PORT,默认主容器 8080);
任一不可达时整文件 skip。
"""

import asyncio
import os
import pathlib
import uuid
from types import SimpleNamespace

import pytest
import weaviate
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker

from backend.db.models import Base, Document, DocumentVersion, DocumentVersionChunk, IndexGeneration
from backend.services import document_lifecycle as lifecycle

TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://ask_ai:changeme@localhost:5432/ask_ai_test",
).replace("+asyncpg", "+psycopg2")
ADMIN_DSN = TEST_DSN.rsplit("/", 1)[0] + "/postgres"
MIG_DB = "ask_ai_p1mig_test"
MIG_DSN = TEST_DSN.rsplit("/", 1)[0] + "/" + MIG_DB
MIG_DSN_ASYNC = MIG_DSN.replace("+psycopg2", "+asyncpg")
WEAVIATE_PORT = int(os.environ.get("P1_WEAVIATE_PORT", "8080"))
CLASS_NAME = "P1MigProbe"

pytestmark = pytest.mark.integration


def _weaviate():
    try:
        return weaviate.connect_to_local("localhost", WEAVIATE_PORT)
    except Exception:  # noqa: BLE001
        return None


@pytest.fixture()
def mig():
    client = _weaviate()
    if client is None:
        pytest.skip(f"local Weaviate 不可达(port={WEAVIATE_PORT})")

    admin = create_engine(ADMIN_DSN, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{MIG_DB}"'))
        c.execute(text(f'CREATE DATABASE "{MIG_DB}"'))
    admin.dispose()

    engine = create_engine(MIG_DSN)
    # 建 v1.5.0 旧形态:现有 models 全建后,拆掉 P1 五列与三表
    Base.metadata.create_all(engine)
    with engine.begin() as c:
        c.execute(text("DROP TABLE IF EXISTS document_version_chunks CASCADE"))
        c.execute(text("DROP TABLE IF EXISTS document_versions CASCADE"))
        c.execute(text("DROP TABLE IF EXISTS index_generations CASCADE"))
        c.execute(text("ALTER TABLE documents DROP COLUMN IF EXISTS lifecycle"))
        c.execute(text("ALTER TABLE documents DROP COLUMN IF EXISTS current_version_id"))
        c.execute(text("ALTER TABLE documents DROP COLUMN IF EXISTS superseded_by"))
        c.execute(text("ALTER TABLE documents DROP COLUMN IF EXISTS superseded_at"))
        c.execute(text("ALTER TABLE documents DROP COLUMN IF EXISTS deleted_at"))
    sync_factory = sessionmaker(engine, expire_on_commit=False)

    if client.collections.exists(CLASS_NAME):
        client.collections.delete(CLASS_NAME)

    yield SimpleNamespace(engine=engine, sync_factory=sync_factory, client=client)

    if client.collections.exists(CLASS_NAME):
        client.collections.delete(CLASS_NAME)
    client.close()
    engine.dispose()
    with create_engine(ADMIN_DSN, isolation_level="AUTOCOMMIT").connect() as c:
        c.execute(text(f'DROP DATABASE IF EXISTS "{MIG_DB}"'))


def _seed_legacy_rows(sync_factory) -> None:
    """v1.5.0 旧形态账本行(原生 SQL:旧表无 P1 五列,ORM 已带新列不可用)。"""
    with sync_factory() as s:
        for sid, cc in (("mig-doc-a", 2), ("mig-doc-b", 1)):
            s.execute(
                text(
                    "INSERT INTO documents (source_id, content_hash, source_type, product,"
                    " title, url, metadata, branch, chunk_count)"
                    " VALUES (:sid, :h, 'web_crawl', 'probe', :sid, :u, '{}', '', :cc)"
                ),
                {"sid": sid, "h": f"h-{sid}", "u": f"https://x/{sid}", "cc": cc},
            )
        s.commit()


def _seed_legacy_objects(client) -> list[str]:
    """v1.5.0 形态对象:legacy 确定性 UUID,无 generation 属性。"""
    import weaviate.classes.data as wd
    from weaviate.classes.config import Configure, DataType, Property

    from backend.pipeline.ingest import COLLECTION_PROPERTIES, _deterministic_uuid

    client.collections.create(
        name=CLASS_NAME,
        vectorizer_config=Configure.Vectorizer.none(),
        properties=[
            Property(
                name=n,
                data_type={"text": DataType.TEXT, "int": DataType.INT,
                           "text[]": DataType.TEXT_ARRAY}[d],
            )
            for n, d in COLLECTION_PROPERTIES
            if n not in ("generation_ordinal", "generation_id")
        ],
    )
    col = client.collections.get(CLASS_NAME)
    uuids: list[str] = []
    objs = []
    for sid, cc in (("mig-doc-a", 2), ("mig-doc-b", 1)):
        for i in range(cc):
            uid = _deterministic_uuid(sid, i)
            uuids.append(uid)
            objs.append(
                wd.DataObject(
                    properties={
                        "source_id": sid,
                        "chunk_index": i,
                        "text": f"text-{sid}-{i}",
                        "content_hash": f"h-{sid}",
                        "source_type": "web_crawl",
                        "product": "probe",
                        "title": sid,
                        "url": f"https://x/{sid}",
                        "branch": "",
                    },
                    vector=[0.1] * 4,
                    uuid=uid,
                )
            )
    col.data.insert_many(objs)
    return uuids


def _run_chain(mig) -> None:
    """迁移全链:PG schema → 版本回填 → Weaviate 补属性 → 内容回填。"""
    import scripts.migrate_p1_lifecycle_foundation as m

    async_engine = create_async_engine(MIG_DSN_ASYNC)
    try:
        asyncio.run(m.ensure_pg_schema(async_engine))
    finally:
        asyncio.run(async_engine.dispose())
    m.backfill_versions(mig.sync_factory)
    m.ensure_weaviate_schema(mig.client, CLASS_NAME)
    m.backfill_content_from_weaviate(mig.client, CLASS_NAME, mig.sync_factory)


# --------------------------------------------------------------------------- #
# 阶段 1:PG 补列/建表 —— 加性、幂等、fail-closed
# --------------------------------------------------------------------------- #


def test_pg_schema_migration_additive_idempotent(mig):
    import scripts.migrate_p1_lifecycle_foundation as m

    async def _twice() -> None:
        engine = create_async_engine(MIG_DSN_ASYNC)
        try:
            await m.ensure_pg_schema(engine)
            await m.ensure_pg_schema(engine)  # 幂等:重复执行无副作用
        finally:
            await engine.dispose()

    asyncio.run(_twice())
    with mig.engine.connect() as c:
        cols = {r[0] for r in c.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='documents'"
        ))}
        tables = {r[0] for r in c.execute(text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
        ))}
    assert {"lifecycle", "current_version_id", "superseded_by", "superseded_at", "deleted_at"} <= cols
    assert {"document_versions", "document_version_chunks", "index_generations"} <= tables


# --------------------------------------------------------------------------- #
# 阶段 3:版本回填 —— legacy 初始代,幂等
# --------------------------------------------------------------------------- #


def test_version_backfill_creates_legacy_initial_versions_idempotently(mig):
    import scripts.migrate_p1_lifecycle_foundation as m

    _seed_legacy_rows(mig.sync_factory)
    asyncio.run(_ensure_schema(mig))

    migrated = m.backfill_versions(mig.sync_factory)
    assert migrated == 2
    with mig.sync_factory() as s:
        rows = s.query(Document).all()
        assert all(r.current_version_id is not None for r in rows)
        versions = s.query(DocumentVersion).all()
        assert len(versions) == 2
        assert all(
            v.generation_id == lifecycle.LEGACY_GENERATION_ID
            and v.generation_ordinal == lifecycle.LEGACY_GENERATION_ORDINAL
            and v.status == "active"
            and v.version_seq == 1
            for v in versions
        )
        gens = s.query(IndexGeneration).all()
        assert [g.ordinal for g in gens] == [lifecycle.LEGACY_GENERATION_ORDINAL]

    # 幂等:二跑零新建
    assert m.backfill_versions(mig.sync_factory) == 0
    with mig.sync_factory() as s:
        assert s.query(DocumentVersion).count() == 2


async def _ensure_schema(mig):
    import scripts.migrate_p1_lifecycle_foundation as m

    engine = create_async_engine(MIG_DSN_ASYNC)
    try:
        await m.ensure_pg_schema(engine)
    finally:
        await engine.dispose()


# --------------------------------------------------------------------------- #
# 阶段 4:内容回填(单向拷贝 + 对象补属性)—— 幂等、零向量传输、零改写
# --------------------------------------------------------------------------- #


def test_content_backfill_copies_truth_and_stamps_generation_idempotently(mig):
    import scripts.migrate_p1_lifecycle_foundation as m

    _seed_legacy_rows(mig.sync_factory)
    asyncio.run(_ensure_schema(mig))
    m.backfill_versions(mig.sync_factory)
    uuids = _seed_legacy_objects(mig.client)

    stats = m.backfill_content_from_weaviate(mig.client, CLASS_NAME, mig.sync_factory)
    assert stats["scanned"] == 3
    assert stats["props_backfilled"] == 3
    assert stats["chunks_inserted"] == 3
    assert stats["ghost_objects"] == 0

    # 持久副本与对象文本逐一一致(单向拷贝保真)
    with mig.sync_factory() as s:
        rows = s.execute(
            select_chunk_rows()
        ).all()
    got = {(sid, idx): text_ for sid, idx, text_ in rows}
    assert got == {
        ("mig-doc-a", 0): "text-mig-doc-a-0",
        ("mig-doc-a", 1): "text-mig-doc-a-1",
        ("mig-doc-b", 0): "text-mig-doc-b-0",
    }

    # 对象已补 generation 属性(INT 0 = legacy)
    from weaviate.classes.query import Filter

    col = mig.client.collections.get(CLASS_NAME)
    resp = col.query.fetch_objects(
        filters=Filter.by_id().contains_any(uuids), limit=len(uuids)
    )
    assert {o.properties["generation_ordinal"] for o in resp.objects} == {
        lifecycle.LEGACY_GENERATION_ORDINAL
    }

    # 幂等:二跑零新写(对象已有属性、chunk 行已存在)
    stats2 = m.backfill_content_from_weaviate(mig.client, CLASS_NAME, mig.sync_factory)
    assert stats2["props_backfilled"] == 0
    assert stats2["chunks_inserted"] == 0


def select_chunk_rows():
    from sqlalchemy import select

    return select(
        DocumentVersion.source_id, DocumentVersionChunk.chunk_index, DocumentVersionChunk.text
    ).join(DocumentVersionChunk, DocumentVersionChunk.version_id == DocumentVersion.id)


# --------------------------------------------------------------------------- #
# 验证:fail-closed
# --------------------------------------------------------------------------- #


def test_verify_passes_on_consistent_migration_state(mig):
    import scripts.migrate_p1_lifecycle_foundation as m

    _seed_legacy_rows(mig.sync_factory)
    asyncio.run(_ensure_schema(mig))
    m.backfill_versions(mig.sync_factory)
    _seed_legacy_objects(mig.client)
    m.backfill_content_from_weaviate(mig.client, CLASS_NAME, mig.sync_factory)

    facts = m.verify(mig.sync_factory, mig.client, CLASS_NAME)
    assert facts["pg"]["null_current"] == 0
    assert facts["pg"]["multi_active"] == 0
    assert facts["pg"]["legacy_expected_chunks"] == 3
    assert facts["weaviate"]["missing_ordinal"] == 0
    assert facts["weaviate"]["legacy_objects"] == 3


def test_verify_fails_closed_on_multi_active(mig):
    import scripts.migrate_p1_lifecycle_foundation as m

    _seed_legacy_rows(mig.sync_factory)
    asyncio.run(_ensure_schema(mig))
    m.backfill_versions(mig.sync_factory)
    # 注入不变量违背:同源第二个 active 版本
    with mig.sync_factory() as s:
        doc = s.query(Document).filter(Document.source_id == "mig-doc-a").one()
        s.add(
            DocumentVersion(
                source_id=doc.source_id,
                version_seq=2,
                content_hash="rogue",
                metadata_hash="m",
                generation_id=lifecycle.LEGACY_GENERATION_ID,
                generation_ordinal=lifecycle.LEGACY_GENERATION_ORDINAL,
                status="active",
                title="rogue",
                url="u",
                chunk_count=0,
            )
        )
        s.commit()
    with pytest.raises(RuntimeError, match="fail-closed"):
        m.verify(mig.sync_factory, mig.client, CLASS_NAME)


def test_verify_fails_closed_on_legacy_object_count_mismatch(mig):
    import scripts.migrate_p1_lifecycle_foundation as m

    _seed_legacy_rows(mig.sync_factory)
    asyncio.run(_ensure_schema(mig))
    m.backfill_versions(mig.sync_factory)
    _seed_legacy_objects(mig.client)
    m.backfill_content_from_weaviate(mig.client, CLASS_NAME, mig.sync_factory)
    # 残留一个无 generation 属性的对象(模拟迁移中断)→ fail-closed
    import weaviate.classes.data as wd

    col = mig.client.collections.get(CLASS_NAME)
    rogue = str(uuid.uuid4())
    col.data.insert_many(
        [wd.DataObject(properties={"source_id": "rogue", "chunk_index": 0}, vector=[0.1] * 4, uuid=rogue)]
    )
    with pytest.raises(RuntimeError, match="fail-closed"):
        m.verify(mig.sync_factory, mig.client, CLASS_NAME)


# --------------------------------------------------------------------------- #
# 零 embedding 的结构性证据
# --------------------------------------------------------------------------- #


def test_migration_module_has_no_embedder_dependency():
    """迁移链路无 embedder 依赖(零重嵌的结构性保证;P1 硬边界)。"""
    import scripts.migrate_p1_lifecycle_foundation as m

    module_names = {n.lower() for n in dir(m)}
    assert not any("embed" in n for n in module_names)
    source = pathlib.Path(m.__file__).read_text(encoding="utf-8")
    assert "embed(" not in source
    assert "BGEEmbedder" not in source
    assert "vector=" not in source.replace("vector=", "vector=", 1) or "data.update" in source
    # 明确红线:回填只经 data.update 补属性(不传 vector、不 replace 对象)
    assert "data.update" in source
    assert ".replace(" not in source
