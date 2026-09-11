"""生命周期 GC 地基(P1;物理清除仅经本接口,Freeze §8a / FC-4)。

资格(冻结时序,不以实现 convenient 度):
- **RETIRED 生成代**:retired_at + 7 天(``RETIRED_RETENTION_DAYS``)后可自动
  物理 GC —— 清除该代全部版本的对象 + 持久 chunk 副本;版本元数据行保留
  作审计(链可回放);
- **被接替文档**(identity superseded):superseded_at + 7 天后物理清除
  (行 + 版本 + 对象);
- **墓碑文档**(deleted):deleted_at + ``tombstone_days`` 后物理清除;
  **不设隐式默认**(None = 墓碑物理 GC 关闭,直至运营显式配置;已废除的
  30 天默认禁止回用;运营化归 P5)。

红线:
- 只按版本自身命名空间的确定性 UUID 点删(P0-A:禁止 TEXT 属性过滤删除);
- dry-run 默认;``apply=True`` 才落删除;
- 删除动作全部记录进 :class:`GCReport`(可审计)。
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.db.models import (
    Document,
    DocumentVersion,
    DocumentVersionChunk,
    IndexGeneration,
)
from backend.pipeline.ingest import chunk_uuids_for_version
from backend.services import document_lifecycle as lifecycle

logger = logging.getLogger(__name__)


@dataclass
class GCReport:
    """一次 sweep 的审计账本(dry-run 与 apply 同构)。"""

    now: datetime
    dry_run: bool
    generations_eligible: list[str] = field(default_factory=list)
    documents_eligible: list[str] = field(default_factory=list)
    objects_deleted: int = 0
    chunk_rows_deleted: int = 0
    versions_deleted: int = 0
    documents_deleted: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "now": self.now.isoformat(),
            "dry_run": self.dry_run,
            "generations_eligible": self.generations_eligible,
            "documents_eligible": self.documents_eligible,
            "objects_deleted": self.objects_deleted,
            "chunk_rows_deleted": self.chunk_rows_deleted,
            "versions_deleted": self.versions_deleted,
            "documents_deleted": self.documents_deleted,
            "errors": self.errors,
        }


def _delete_version_objects(collection: Any, version: DocumentVersion, chunk_count: int) -> int:
    """按版本命名空间点删对象(文档局部,P0-A);返回尝试删除数。"""
    from weaviate.classes.query import Filter

    uuids = chunk_uuids_for_version(
        version.source_id,
        str(version.generation_id),
        int(version.generation_ordinal),
        chunk_count,
    )
    for start in range(0, len(uuids), 500):
        collection.data.delete_many(
            where=Filter.by_id().contains_any(uuids[start : start + 500])
        )
    return len(uuids)


async def sweep(
    session_factory: Any,
    pipeline,
    *,
    tombstone_days: int | None = None,
    now: datetime | None = None,
    apply: bool = False,
) -> GCReport:
    """GC sweep:eligibility 判定 + (apply 时)物理清除。只读 PG 做裁决。"""
    ts = now or lifecycle.utcnow()
    report = GCReport(now=ts, dry_run=not apply)

    # ---- 1) RETIRED 生成代(retired + 7 天)----
    async with session_factory() as session:
        gens = (
            await session.execute(
                select(IndexGeneration).where(
                    IndexGeneration.status == lifecycle.GenerationStatus.RETIRED,
                    IndexGeneration.gc_eligible_at.is_not(None),
                    IndexGeneration.gc_eligible_at <= ts,
                    IndexGeneration.purged_at.is_(None),
                )
            )
        ).scalars().all()
        gen_ids = [g.id for g in gens]
        report.generations_eligible = [str(g) for g in gen_ids]
        versions_by_gen: dict[Any, list[DocumentVersion]] = {}
        if gen_ids:
            rows = (
                await session.execute(
                    select(DocumentVersion).where(DocumentVersion.generation_id.in_(gen_ids))
                )
            ).scalars().all()
            for v in rows:
                versions_by_gen.setdefault(v.generation_id, []).append(v)
    if apply and gen_ids:
        collection = pipeline._collection or _ensure_collection(pipeline)
        sync_sf = _sync_session_factory_of(pipeline)
        for gen_id in gen_ids:
            try:
                with sync_sf() as s:
                    for version in versions_by_gen.get(gen_id, []):
                        report.objects_deleted += _delete_version_objects(
                            collection, version, int(version.chunk_count)
                        )
                        deleted = s.execute(
                            select(DocumentVersionChunk).where(
                                DocumentVersionChunk.version_id == version.id
                            )
                        ).scalars().all()
                        for c in deleted:
                            s.delete(c)
                        report.chunk_rows_deleted += len(deleted)
                    row = s.execute(
                        select(IndexGeneration).where(IndexGeneration.id == gen_id)
                    ).scalar_one()
                    row.purged_at = ts
                    s.commit()
            except Exception as exc:  # noqa: BLE001 - 单代失败不阻断其余
                report.errors.append(f"gen {gen_id}: {str(exc)[:200]}")

    # ---- 2) 文档级物理清除:被接替(7 天冻结)+ 墓碑(tombstone_days 显式配置)----
    async with session_factory() as session:
        superseded_cut = ts - timedelta(
            days=lifecycle.RETIRED_RETENTION_DAYS
        )
        doomed: list[Document] = []
        sup_rows = (
            await session.execute(
                select(Document).where(
                    Document.lifecycle == lifecycle.DocLifecycle.SUPERSEDED,
                    Document.superseded_at.is_not(None),
                    Document.superseded_at <= superseded_cut,
                )
            )
        ).scalars().all()
        doomed.extend(sup_rows)
        if tombstone_days is not None:
            del_cut = ts - timedelta(days=tombstone_days)
            del_rows = (
                await session.execute(
                    select(Document).where(
                        Document.lifecycle == lifecycle.DocLifecycle.DELETED,
                        Document.deleted_at.is_not(None),
                        Document.deleted_at <= del_cut,
                    )
                )
            ).scalars().all()
            doomed.extend(del_rows)
        report.documents_eligible = [d.source_id for d in doomed]
        doc_versions: dict[str, list[DocumentVersion]] = {}
        if doomed:
            ids = [d.source_id for d in doomed]
            vrows = (
                await session.execute(
                    select(DocumentVersion).where(DocumentVersion.source_id.in_(ids))
                )
            ).scalars().all()
            for v in vrows:
                doc_versions.setdefault(v.source_id, []).append(v)

    if apply and doomed:
        collection = pipeline._collection or _ensure_collection(pipeline)
        sync_sf = _sync_session_factory_of(pipeline)
        for doc in doomed:
            try:
                with sync_sf() as s:
                    for version in doc_versions.get(doc.source_id, []):
                        report.objects_deleted += _delete_version_objects(
                            collection, version, int(version.chunk_count)
                        )
                        crows = s.execute(
                            select(DocumentVersionChunk).where(
                                DocumentVersionChunk.version_id == version.id
                            )
                        ).scalars().all()
                        for c in crows:
                            s.delete(c)
                        report.chunk_rows_deleted += len(crows)
                        s.delete(version)
                        report.versions_deleted += 1
                    d_row = s.execute(
                        select(Document).where(Document.source_id == doc.source_id)
                    ).scalar_one()
                    s.delete(d_row)
                    report.documents_deleted += 1
                    s.commit()
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"doc {doc.source_id}: {str(exc)[:200]}")

    logger.info(
        "GC sweep(dry_run=%s): 代资格 %d, 文档资格 %d, 对象 %d, chunk 行 %d",
        report.dry_run,
        len(report.generations_eligible),
        len(report.documents_eligible),
        report.objects_deleted,
        report.chunk_rows_deleted,
    )
    return report


def _ensure_collection(pipeline):
    pipeline._ensure_collection()
    return pipeline._collection


def _sync_session_factory_of(pipeline) -> sessionmaker[Session]:
    sf = pipeline._session_factory
    if sf is None:
        raise RuntimeError("GC 物理清除需要账本同步会话工厂(pipeline._session_factory)")
    return sf
