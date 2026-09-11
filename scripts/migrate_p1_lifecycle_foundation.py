"""P1 生命周期地基迁移(documents 版本/生成演进;Trace B TB-P1)。

把 bb80c38/39723c2 形态的遗留生产状态(单代、无版本、内容仅在 Weaviate)
演进为 P1 模型,**零重嵌、零向量迁移、零强制全量重建**(契约 Migration
Boundary;先例:migrate_documents_path_identity / migrate_backfill_evidence_meta)。

四阶段(全部幂等,失败 fail-closed,可重复执行至收敛):
  1. PG schema:documents 加性补列 ×5 + 新建 document_versions /
     document_version_chunks / index_generations(既有行/列零改写;
     lifecycle server_default='active' 即旧行语义);
  2. Weaviate schema:collection 加性补 property(generation_ordinal INT /
     generation_id TEXT);已有 property 跳过(与 evidence props 迁移同款);
  3. 版本回填(PG-only):每文档补初始版本(seq=1,current 指针,归迁移
     初始代 ordinal=0 —— **对象寻址不变**,确定性 UUID 家族兼容);
  4. 内容回填(Weaviate → PG 单向拷贝):对象 text/props 持久化为
     document_version_chunks(I-1:此后 Weaviate 不再是唯一内容驻留),
     同一趟为对象补 generation 属性(ordinal=0);仅写新列/新行,绝不改
     text、绝不传 vector、绝不删对象。

验证(fail-closed,任何不满足 → 非零退出):
  - PG:无 current_version_id IS NULL 的文档行;每行恰一条 active 版本;
  - Weaviate:无缺失 generation_ordinal 的对象;ordinal=0 对象总数 ==
    初始代版本 SUM(chunk_count)。

用法:
    python scripts/migrate_p1_lifecycle_foundation.py                # 执行
    python scripts/migrate_p1_lifecycle_foundation.py --verify-only  # 只验证
"""

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv()

from typing import Any

import weaviate
from sqlalchemy import func, inspect, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.config import load_settings
from backend.db.models import (
    Document,
    DocumentVersion,
    DocumentVersionChunk,
    IndexGeneration,
)
from backend.db.session import get_engine, get_sync_session_factory
from backend.services import document_lifecycle as lifecycle

logger = logging.getLogger("migrate_p1_lifecycle")

DOCUMENT_COLUMNS_DDL = (
    ("ALTER TABLE documents ADD COLUMN IF NOT EXISTS lifecycle VARCHAR(20)" " NOT NULL DEFAULT 'active'"),
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS current_version_id UUID",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS superseded_by VARCHAR(200)",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS superseded_at TIMESTAMP WITH TIME ZONE",
    "ALTER TABLE documents ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMP WITH TIME ZONE",
)

P1_TABLES = (DocumentVersion, DocumentVersionChunk, IndexGeneration)

# Weaviate 补列(idempotent;与 _ensure_collection/COLLECTION_PROPERTIES 同源)
WEAVIATE_NEW_PROPS = (("generation_ordinal", "int"), ("generation_id", "text"))

_FLUSH_BATCH = 500


# --------------------------------------------------------------------------- #
# 阶段 1:PG schema(加性、幂等)
# --------------------------------------------------------------------------- #


async def ensure_pg_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        for ddl in DOCUMENT_COLUMNS_DDL:
            await conn.execute(text(ddl))
        for model in P1_TABLES:
            await conn.run_sync(
                lambda sc, _m=model: _m.__table__.create(sc, checkfirst=True)
            )
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS idx_documents_lifecycle ON documents (lifecycle)")
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_documents_current_version "
                "ON documents (current_version_id)"
            )
        )
    async with engine.connect() as conn:
        columns = await conn.run_sync(
            lambda sc: {c["name"] for c in inspect(sc).get_columns("documents")}
        )
    missing = {"lifecycle", "current_version_id", "superseded_by", "superseded_at", "deleted_at"} - columns
    if missing:
        raise RuntimeError(f"documents 补列失败,缺 {sorted(missing)}(fail-closed)")
    logger.info("PG schema 就绪(documents 加列 + P1 三表)")


# --------------------------------------------------------------------------- #
# 阶段 2:Weaviate schema(加性、幂等)
# --------------------------------------------------------------------------- #


def ensure_weaviate_schema(client, class_name: str) -> None:
    if not client.collections.exists(class_name):
        logger.info("collection %s 不存在(全新部署,跳过补列;init 时自建)", class_name)
        return
    col = client.collections.get(class_name)
    existing = {p.name for p in col.config.get().properties}
    from weaviate.classes.config import DataType, Property

    for name, dtype in WEAVIATE_NEW_PROPS:
        if name in existing:
            continue
        col.config.add_property(
            Property(name=name, data_type=DataType.INT if dtype == "int" else DataType.TEXT)
        )
        logger.info("collection %s 已补 property %s(%s)", class_name, name, dtype)


# --------------------------------------------------------------------------- #
# 阶段 3:版本回填(PG-only;幂等)
# --------------------------------------------------------------------------- #


def backfill_versions(sync_session_factory) -> int:
    """每文档补初始版本(seq=1,current 指针,legacy 代);返回本次补建数。"""
    migrated = 0
    with sync_session_factory() as session:
        lifecycle.ensure_legacy_generation(session)
        session.commit()
        need_ids = session.execute(
            select(Document.source_id).where(Document.current_version_id.is_(None))
        ).scalars().all()
        for sid in need_ids:
            doc = session.execute(select(Document).where(Document.source_id == sid)).scalar_one()
            lifecycle.ensure_initial_version(session, doc)
            migrated += 1
            if migrated % 1000 == 0:
                session.commit()
                logger.info("版本回填进度: %d", migrated)
        session.commit()
    logger.info("版本回填完成: 本次补建 %d 个初始版本", migrated)
    return migrated


# --------------------------------------------------------------------------- #
# 阶段 4:内容回填(Weaviate → PG 单向拷贝 + 对象补 generation 属性;幂等)
# --------------------------------------------------------------------------- #


def backfill_content_from_weaviate(client, class_name: str, sync_session_factory) -> dict:
    """单趟迭代:对象 text/props → document_version_chunks;对象补 generation 属性。

    仅写新行/新列;绝不改 text、绝不传 vector、绝不删对象(与
    migrate_backfill_evidence_meta 同红线)。幽灵对象(无账本行)只上报不写。
    """
    if not client.collections.exists(class_name):
        return {"scanned": 0, "props_backfilled": 0, "chunks_inserted": 0, "ghost_objects": 0}
    col = client.collections.get(class_name)
    stats = {"scanned": 0, "props_backfilled": 0, "chunks_inserted": 0, "ghost_objects": 0}

    pending_objects: list[tuple[str, dict]] = []
    pending_chunks: list[tuple[str, int, str, dict]] = []

    def _flush() -> None:
        if pending_objects:
            for uuid_, props in pending_objects:
                col.data.update(uuid=uuid_, properties=props)
            stats["props_backfilled"] += len(pending_objects)
            pending_objects.clear()
        if pending_chunks:
            with sync_session_factory() as session:
                for sid, idx, text_, props in pending_chunks:
                    version_id = _version_id_map(session).get(sid)
                    if version_id is None:
                        stats["ghost_objects"] += 1
                        continue
                    exists = session.execute(
                        select(func.count())
                        .select_from(DocumentVersionChunk)
                        .where(
                            DocumentVersionChunk.version_id == version_id,
                            DocumentVersionChunk.chunk_index == idx,
                        )
                    ).scalar()
                    if exists:
                        continue
                    session.add(
                        DocumentVersionChunk(
                            version_id=version_id, chunk_index=idx, text=text_, props=props
                        )
                    )
                    stats["chunks_inserted"] += 1
                session.commit()
        pending_chunks.clear()

    version_map_cache: dict[str, Any] = {}

    def _version_id_map(session):
        cache = version_map_cache
        if not cache:
            rows = session.execute(
                select(Document.source_id, Document.current_version_id).where(
                    Document.current_version_id.is_not(None)
                )
            ).all()
            cache.update({sid: vid for sid, vid in rows})
        return cache

    for item in col.iterator(return_properties=None):
        props = dict(item.properties or {})
        sid = props.get("source_id")
        idx = props.get("chunk_index")
        stats["scanned"] += 1
        if props.get("generation_ordinal") is None:
            update = {
                "generation_ordinal": lifecycle.LEGACY_GENERATION_ORDINAL,
                "generation_id": str(lifecycle.LEGACY_GENERATION_ID),
            }
            pending_objects.append((str(item.uuid), update))
            props.update(update)
        if sid is not None and idx is not None and props.get("text") is not None:
            pending_chunks.append(
                (str(sid), int(idx), str(props["text"]), props)
            )
        if len(pending_objects) >= _FLUSH_BATCH or len(pending_chunks) >= _FLUSH_BATCH:
            _flush()
    _flush()
    logger.info(
        "内容回填完成: 扫描 %d,补属性 %d,chunk 副本 %d,幽灵 %d",
        stats["scanned"],
        stats["props_backfilled"],
        stats["chunks_inserted"],
        stats["ghost_objects"],
    )
    return stats


# --------------------------------------------------------------------------- #
# 验证(fail-closed)
# --------------------------------------------------------------------------- #


def verify(sync_session_factory, client, class_name: str) -> dict:
    with sync_session_factory() as session:
        null_current = session.execute(
            select(func.count())
            .select_from(Document)
            .where(Document.current_version_id.is_(None))
        ).scalar()
        multi_active = session.execute(
            select(func.count())
            .select_from(
                select(
                    DocumentVersion.source_id,
                    func.count().label("n"),
                )
                .where(DocumentVersion.status == "active")
                .group_by(DocumentVersion.source_id)
                .having(func.count() > 1)
                .subquery()
            )
        ).scalar()
        legacy_expected = session.execute(
            select(func.coalesce(func.sum(DocumentVersion.chunk_count), 0)).where(
                DocumentVersion.generation_id == lifecycle.LEGACY_GENERATION_ID
            )
        ).scalar()
    pg_facts = {
        "null_current": int(null_current or 0),
        "multi_active": int(multi_active or 0),
        "legacy_expected_chunks": int(legacy_expected or 0),
    }
    if pg_facts["null_current"] or pg_facts["multi_active"]:
        raise RuntimeError(f"PG 验证失败(fail-closed): {pg_facts}")
    wv_facts = {"missing_ordinal": 0, "legacy_objects": 0}
    if client.collections.exists(class_name):
        col = client.collections.get(class_name)
        for item in col.iterator(return_properties=["generation_ordinal", "source_id"]):
            o = item.properties.get("generation_ordinal")
            if o is None:
                wv_facts["missing_ordinal"] += 1
            elif int(o) == lifecycle.LEGACY_GENERATION_ORDINAL:
                wv_facts["legacy_objects"] += 1
    if wv_facts["missing_ordinal"]:
        raise RuntimeError(f"Weaviate 验证失败(缺 generation_ordinal): {wv_facts}(fail-closed,重跑迁移)")
    if wv_facts["legacy_objects"] != pg_facts["legacy_expected_chunks"]:
        raise RuntimeError(
            "legacy 代对象数不一致(fail-closed): "
            f"weaviate={wv_facts['legacy_objects']} pg_sum={pg_facts['legacy_expected_chunks']}"
        )
    logger.info("验证通过: %s / %s", pg_facts, wv_facts)
    return {"pg": pg_facts, "weaviate": wv_facts}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


async def run(verify_only: bool = False) -> None:
    settings = load_settings()
    engine = get_engine(settings.postgres_dsn)
    sync_session_factory = get_sync_session_factory(settings.postgres_dsn)
    host, port = _parse_weaviate_endpoint(settings.weaviate_url)
    client = weaviate.connect_to_local(host=host, port=port)
    try:
        if verify_only:
            verify(sync_session_factory, client, settings.weaviate_class_name)
            return
        await ensure_pg_schema(engine)
        ensure_weaviate_schema(client, settings.weaviate_class_name)
        backfill_versions(sync_session_factory)
        backfill_content_from_weaviate(client, settings.weaviate_class_name, sync_session_factory)
        verify(sync_session_factory, client, settings.weaviate_class_name)
        logger.info("P1 迁移完成(幂等;可重复执行)")
    finally:
        client.close()
        await engine.dispose()


def _parse_weaviate_endpoint(weaviate_url: str) -> tuple[str, int]:
    from urllib.parse import urlparse

    if "://" not in weaviate_url:
        weaviate_url = f"http://{weaviate_url}"
    parsed = urlparse(weaviate_url)
    return parsed.hostname or "localhost", parsed.port or 8080


def main() -> None:
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="P1 生命周期地基迁移(幂等)")
    parser.add_argument("--verify-only", action="store_true", help="只验证,不执行迁移")
    args = parser.parse_args()
    asyncio.run(run(verify_only=args.verify_only))


if __name__ == "__main__":
    main()
