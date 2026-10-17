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


def _parse_iso_or_none(raw: Any) -> datetime | None:
    """防御式解析 ISO 时间串(畸形/缺失 → None)。"""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


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
    # v1.6.4 Track A(#25):发现确认退休行的资格观察(7 天自动窗内尚未
    # 到期者单列呈现;到期者已并入 documents_eligible)。A-6 证据面。
    retirement_pending: list[str] = field(default_factory=list)

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
            "retirement_pending": self.retirement_pending,
        }


def _version_object_uuids(
    version: DocumentVersion,
    chunk_rows: list[DocumentVersionChunk],
    *,
    allow_missing_chunk_rows: bool = False,
) -> list[str]:
    """验证 PG 身份完整后重建版本确定性 UUID 全集;身份不完整时拒绝猜测。"""
    source_id = version.source_id
    generation_id = version.generation_id
    generation_ordinal = version.generation_ordinal
    chunk_count = version.chunk_count
    if not isinstance(source_id, str) or not source_id:
        raise ValueError(f"version {version.id} has no source identity")
    if generation_id is None:
        raise ValueError(f"version {version.id} has no generation identity")
    if type(generation_ordinal) is not int or generation_ordinal < 0:
        raise ValueError(f"version {version.id} has an invalid generation ordinal")
    if type(chunk_count) is not int or chunk_count < 0:
        raise ValueError(f"version {version.id} has an invalid chunk count")
    is_legacy_generation = str(generation_id) == str(lifecycle.LEGACY_GENERATION_ID)
    if (generation_ordinal == 0) != is_legacy_generation:
        raise ValueError(f"version {version.id} has inconsistent generation identity")

    indexes = [chunk.chunk_index for chunk in chunk_rows]
    if allow_missing_chunk_rows:
        if indexes:
            raise ValueError(f"purged generation {version.generation_id} still has chunk rows")
    elif any(type(index) is not int for index in indexes) or sorted(indexes) != list(
        range(chunk_count)
    ):
        raise ValueError(f"version {version.id} chunk rows do not match chunk_count")

    uuids = chunk_uuids_for_version(
        source_id,
        str(generation_id),
        generation_ordinal,
        chunk_count,
    )
    if len(uuids) != chunk_count or len(set(uuids)) != chunk_count:
        raise ValueError(f"version {version.id} does not define a unique UUID range")
    return uuids


def _read_existing_uuids(collection: Any, uuids: list[str]) -> set[str]:
    """按精确 UUID filter 读回对象;响应结构或身份无法验证时失败关闭。"""
    if not uuids:
        return set()
    from weaviate.classes.query import Filter

    result = collection.query.fetch_objects(
        filters=Filter.by_id().contains_any(uuids), limit=len(uuids)
    )
    objects = getattr(result, "objects", None)
    if not isinstance(objects, (list, tuple)):
        raise TypeError("Weaviate UUID readback returned an unreadable response")

    requested = set(uuids)
    found: set[str] = set()
    for obj in objects:
        raw_uuid = getattr(obj, "uuid", None)
        if raw_uuid is None:
            raise RuntimeError("Weaviate UUID readback returned an object without a UUID")
        object_uuid = str(raw_uuid).lower()
        if object_uuid not in requested or object_uuid in found:
            raise RuntimeError("Weaviate UUID readback returned an inconsistent identity range")
        found.add(object_uuid)
    return found


def _delete_receipt_successes(receipt: Any, requested_count: int) -> int:
    """只接受完整且内部一致的 delete_many 计数回执;failed 非零一律停。"""
    if receipt is None:
        raise RuntimeError("Weaviate delete_many returned no receipt")
    counts = {name: getattr(receipt, name, None) for name in ("failed", "matches", "successful")}
    if any(type(value) is not int or value < 0 for value in counts.values()):
        raise RuntimeError("Weaviate delete_many returned an unreadable receipt")
    failed = counts["failed"]
    matches = counts["matches"]
    successful = counts["successful"]
    if failed:
        raise RuntimeError(f"Weaviate delete_many reported {failed} failed objects")
    if matches > requested_count or successful > requested_count:
        raise RuntimeError("Weaviate delete_many receipt exceeded the requested UUID range")
    if matches != successful + failed:
        raise RuntimeError("Weaviate delete_many receipt counts are inconsistent")
    if matches != requested_count or successful != requested_count:
        raise RuntimeError("Weaviate delete_many did not confirm the full requested UUID range")
    return successful


def _delete_version_objects(collection: Any, uuids: list[str]) -> int:
    """按确定性 UUID 点删,回执可信且整段读回缺席后返回确认删除数。"""
    if not uuids:
        return 0
    from weaviate.classes.query import Filter

    successful = 0
    batches = [uuids[start : start + 500] for start in range(0, len(uuids), 500)]
    for batch in batches:
        existing = _read_existing_uuids(collection, batch)
        if not existing:
            continue
        receipt = collection.data.delete_many(where=Filter.by_id().contains_any(sorted(existing)))
        successful += _delete_receipt_successes(receipt, len(existing))

    remaining = set()
    for batch in batches:
        remaining.update(_read_existing_uuids(collection, batch))
    if remaining:
        raise RuntimeError(
            f"Weaviate readback still found {len(remaining)} UUIDs in the requested range"
        )
    return successful


def _lock_version_generations(
    session: Session, versions: list[DocumentVersion]
) -> dict[Any, IndexGeneration]:
    """在锁版本行前按稳定顺序锁定其生成代,与 generation GC 保持同一锁序。"""
    generation_ids = {
        version.generation_id
        for version in versions
        if str(version.generation_id) != str(lifecycle.LEGACY_GENERATION_ID)
    }
    if not generation_ids:
        return {}
    generations = (
        session.execute(
            select(IndexGeneration)
            .where(IndexGeneration.id.in_(generation_ids))
            .order_by(IndexGeneration.id)
            .with_for_update()
        )
        .scalars()
        .all()
    )
    by_id = {generation.id: generation for generation in generations}
    if set(by_id) != generation_ids:
        raise ValueError("version references a missing generation identity")
    return by_id


def _generation_count_updates_for_document_versions(
    session: Session,
    versions: list[DocumentVersion],
    generations: dict[Any, IndexGeneration],
) -> list[tuple[IndexGeneration, int, int]]:
    """计算文档清理后未 purged 代的剩余计数,保持后续 generation GC 身份闭合。"""
    versions_by_generation: dict[Any, list[DocumentVersion]] = {}
    for version in versions:
        if str(version.generation_id) == str(lifecycle.LEGACY_GENERATION_ID):
            continue
        generation = generations.get(version.generation_id)
        if generation is None or version.generation_ordinal != generation.ordinal:
            raise ValueError("document version generation identity is inconsistent")
        if generation.purged_at is None:
            versions_by_generation.setdefault(version.generation_id, []).append(version)

    updates = []
    for generation_id, removing_versions in versions_by_generation.items():
        generation = generations[generation_id]
        all_versions = (
            session.execute(
                select(DocumentVersion)
                .where(DocumentVersion.generation_id == generation_id)
                .order_by(DocumentVersion.id)
                .with_for_update()
            )
            .scalars()
            .all()
        )
        if type(generation.doc_count) is not int or generation.doc_count < 0:
            raise ValueError("generation has an invalid document count")
        if type(generation.chunk_count) is not int or generation.chunk_count < 0:
            raise ValueError("generation has an invalid chunk count")
        if any(
            version.generation_id != generation.id
            or version.generation_ordinal != generation.ordinal
            or type(version.chunk_count) is not int
            or version.chunk_count < 0
            for version in all_versions
        ):
            raise ValueError("generation version identity is inconsistent")
        if len(all_versions) != generation.doc_count:
            raise ValueError("generation version identities are incomplete")
        if sum(version.chunk_count for version in all_versions) != generation.chunk_count:
            raise ValueError("generation chunk identity range is incomplete")
        removing_ids = {version.id for version in removing_versions}
        remaining = [version for version in all_versions if version.id not in removing_ids]
        if len(all_versions) - len(remaining) != len(removing_ids):
            raise ValueError("document versions are missing from generation identity")
        updates.append(
            (
                generation,
                len(remaining),
                sum(version.chunk_count for version in remaining),
            )
        )
    return updates


def _prepare_version_deletions(
    session: Session,
    versions: list[DocumentVersion],
    *,
    allow_purged_generation: bool = False,
    generations: dict[Any, IndexGeneration] | None = None,
):
    """锁定并验证所有 chunk 身份后再触碰 Weaviate。"""
    prepared = []
    for version in versions:
        chunks = (
            session.execute(
                select(DocumentVersionChunk)
                .where(DocumentVersionChunk.version_id == version.id)
                .order_by(DocumentVersionChunk.chunk_index)
                .with_for_update()
            )
            .scalars()
            .all()
        )
        missing_chunks_allowed = False
        if allow_purged_generation and str(version.generation_id) != str(
            lifecycle.LEGACY_GENERATION_ID
        ):
            generation = (generations or {}).get(version.generation_id)
            if generation is None or generation.ordinal != version.generation_ordinal:
                raise ValueError("document version generation identity is inconsistent")
            missing_chunks_allowed = generation.purged_at is not None
        uuids = _version_object_uuids(
            version, chunks, allow_missing_chunk_rows=missing_chunks_allowed
        )
        prepared.append((version, chunks, uuids))
    return prepared


def _document_is_gc_eligible(
    document: Document, *, now: datetime, tombstone_days: int | None
) -> bool:
    """apply 前复核当前行仍满足既有资格规则,不扩大或重定义资格集合。"""
    if document.lifecycle == lifecycle.DocLifecycle.SUPERSEDED:
        return document.superseded_at is not None and document.superseded_at <= (
            now - timedelta(days=lifecycle.RETIRED_RETENTION_DAYS)
        )
    if document.lifecycle != lifecycle.DocLifecycle.DELETED:
        return False

    record = lifecycle.get_retirement_record(document) or {}
    auto_eligible_at = _parse_iso_or_none(record.get("gc_eligible_at"))
    if auto_eligible_at is not None:
        return auto_eligible_at <= now
    if tombstone_days is None or document.deleted_at is None:
        return False
    return document.deleted_at <= now - timedelta(days=tombstone_days)


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
            (
                await session.execute(
                    select(IndexGeneration).where(
                        IndexGeneration.status == lifecycle.GenerationStatus.RETIRED,
                        IndexGeneration.gc_eligible_at.is_not(None),
                        IndexGeneration.gc_eligible_at <= ts,
                        IndexGeneration.purged_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        gen_ids = [g.id for g in gens]
        report.generations_eligible = [str(g) for g in gen_ids]
    if apply and gen_ids:
        collection = pipeline._collection or _ensure_collection(pipeline)
        sync_sf = _sync_session_factory_of(pipeline)
        for gen_id in gen_ids:
            physical_deleted = 0
            try:
                with sync_sf() as s:
                    row = s.execute(
                        select(IndexGeneration)
                        .where(IndexGeneration.id == gen_id)
                        .with_for_update()
                    ).scalar_one()
                    if (
                        row.status != lifecycle.GenerationStatus.RETIRED
                        or row.gc_eligible_at is None
                        or row.gc_eligible_at > ts
                        or row.purged_at is not None
                    ):
                        raise RuntimeError("generation is no longer eligible for GC")
                    versions = (
                        s.execute(
                            select(DocumentVersion)
                            .where(DocumentVersion.generation_id == gen_id)
                            .order_by(DocumentVersion.id)
                            .with_for_update()
                        )
                        .scalars()
                        .all()
                    )
                    if any(
                        version.generation_id != row.id or version.generation_ordinal != row.ordinal
                        for version in versions
                    ):
                        raise RuntimeError("generation version identity is inconsistent")
                    if type(row.doc_count) is not int or row.doc_count < 0:
                        raise RuntimeError("generation has an invalid document count")
                    if type(row.chunk_count) is not int or row.chunk_count < 0:
                        raise RuntimeError("generation has an invalid chunk count")
                    if len(versions) != row.doc_count:
                        raise RuntimeError("generation version identities are incomplete")
                    if sum(version.chunk_count for version in versions) != row.chunk_count:
                        raise RuntimeError("generation chunk identity range is incomplete")

                    prepared = _prepare_version_deletions(s, versions)
                    for _version, _chunks, uuids in prepared:
                        physical_deleted += _delete_version_objects(collection, uuids)

                    deleted_chunk_rows = 0
                    for _version, chunks, _uuids in prepared:
                        for chunk in chunks:
                            s.delete(chunk)
                        deleted_chunk_rows += len(chunks)
                    row.purged_at = ts
                    s.commit()
            except Exception as exc:  # noqa: BLE001 - 单代失败不阻断其余
                report.objects_deleted += physical_deleted
                report.errors.append(f"gen {gen_id}: {str(exc)[:200]}")
            else:
                report.objects_deleted += physical_deleted
                report.chunk_rows_deleted += deleted_chunk_rows

    # ---- 2) 文档级物理清除:被接替(7 天冻结)+ 墓碑(tombstone_days 显式配置)----
    async with session_factory() as session:
        superseded_cut = ts - timedelta(days=lifecycle.RETIRED_RETENTION_DAYS)
        doomed: list[Document] = []
        sup_rows = (
            (
                await session.execute(
                    select(Document).where(
                        Document.lifecycle == lifecycle.DocLifecycle.SUPERSEDED,
                        Document.superseded_at.is_not(None),
                        Document.superseded_at <= superseded_cut,
                    )
                )
            )
            .scalars()
            .all()
        )
        doomed.extend(sup_rows)

        # ---- v1.6.4 Track A(#25):发现确认退休行的 7 天自动窗(A-2 冻结时序)
        # 自动资格锚**只认** retirement 记录内显式可解析的 ``gc_eligible_at``
        # (confirm_absence_retirement 落笔 retired_at + 7d)。普通墓碑
        # (tombstone_document 原语写 gc_eligible_at=None;含键缺省/畸形
        # 的防御形态)不设隐式默认 —— **绝不回退 deleted_at + 7d**(#162:
        # 该回退会把全部普通墓碑偷偷拉进 7 天自动物理清理,违背 A-5
        # 「墓碑 GC 仍 opt-in」分层);其资格仅由运营显式配置的
        # ``tombstone_days`` 墓碑窗裁决(下方 opt-in 分支,deleted_at 锚)。
        ret_rows = (
            (
                await session.execute(
                    select(Document).where(
                        Document.lifecycle == lifecycle.DocLifecycle.DELETED,
                        Document.metadata_[lifecycle.RETIREMENT_META_KEY].is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in ret_rows:
            record = lifecycle.get_retirement_record(row) or {}
            eligible = _parse_iso_or_none(record.get("gc_eligible_at"))
            if eligible is None:
                # 普通墓碑(或畸形记录):无自动窗,交 opt-in 墓碑窗裁决
                continue
            if eligible <= ts:
                doomed.append(row)
            else:
                report.retirement_pending.append(row.source_id)

        if tombstone_days is not None:
            del_cut = ts - timedelta(days=tombstone_days)
            del_rows = (
                (
                    await session.execute(
                        select(Document).where(
                            Document.lifecycle == lifecycle.DocLifecycle.DELETED,
                            Document.deleted_at.is_not(None),
                            Document.deleted_at <= del_cut,
                        )
                    )
                )
                .scalars()
                .all()
            )
            for row in del_rows:
                # 持显式自动窗锚者(发现确认退休)只走自动窗(上方已裁决):
                # 墓碑窗更短也不得提前(A-2 时序不被 opt-in 配置压缩)。
                record = lifecycle.get_retirement_record(row) or {}
                if _parse_iso_or_none(record.get("gc_eligible_at")) is not None:
                    continue
                doomed.append(row)
        report.documents_eligible = [d.source_id for d in doomed]

    if apply and doomed:
        collection = pipeline._collection or _ensure_collection(pipeline)
        sync_sf = _sync_session_factory_of(pipeline)
        for doc in doomed:
            physical_deleted = 0
            try:
                with sync_sf() as s:
                    d_row = s.execute(
                        select(Document)
                        .where(Document.source_id == doc.source_id)
                        .with_for_update()
                    ).scalar_one()
                    if not _document_is_gc_eligible(d_row, now=ts, tombstone_days=tombstone_days):
                        raise RuntimeError("document is no longer eligible for GC")
                    version_refs = (
                        s.execute(
                            select(DocumentVersion)
                            .where(DocumentVersion.source_id == d_row.source_id)
                            .order_by(DocumentVersion.id)
                        )
                        .scalars()
                        .all()
                    )
                    if not version_refs:
                        raise RuntimeError("document has no recoverable version identity")
                    generation_rows = _lock_version_generations(s, version_refs)
                    versions = (
                        s.execute(
                            select(DocumentVersion)
                            .where(DocumentVersion.source_id == d_row.source_id)
                            .order_by(DocumentVersion.id)
                            .with_for_update()
                        )
                        .scalars()
                        .all()
                    )
                    if {version.id for version in versions} != {
                        version.id for version in version_refs
                    }:
                        raise RuntimeError("document version identity changed during GC")
                    if any(version.source_id != d_row.source_id for version in versions):
                        raise RuntimeError("document version identity is inconsistent")
                    if d_row.current_version_id is not None:
                        current = next(
                            (v for v in versions if v.id == d_row.current_version_id), None
                        )
                        if current is None or current.chunk_count != d_row.chunk_count:
                            raise RuntimeError("document current version identity is inconsistent")
                    elif d_row.chunk_count:
                        raise RuntimeError("document current version identity is missing")

                    generation_count_updates = _generation_count_updates_for_document_versions(
                        s, versions, generation_rows
                    )
                    prepared = _prepare_version_deletions(
                        s,
                        versions,
                        allow_purged_generation=True,
                        generations=generation_rows,
                    )
                    for _version, _chunks, uuids in prepared:
                        physical_deleted += _delete_version_objects(collection, uuids)

                    for generation, doc_count, chunk_count in generation_count_updates:
                        generation.doc_count = doc_count
                        generation.chunk_count = chunk_count
                    deleted_chunk_rows = 0
                    for version, chunks, _uuids in prepared:
                        for chunk in chunks:
                            s.delete(chunk)
                        deleted_chunk_rows += len(chunks)
                        s.delete(version)
                    s.delete(d_row)
                    s.commit()
            except Exception as exc:  # noqa: BLE001
                report.objects_deleted += physical_deleted
                report.errors.append(f"doc {doc.source_id}: {str(exc)[:200]}")
            else:
                report.objects_deleted += physical_deleted
                report.chunk_rows_deleted += deleted_chunk_rows
                report.versions_deleted += len(versions)
                report.documents_deleted += 1

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
