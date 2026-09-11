"""生成构建器(P1 索引生成 + 版本激活的核心执行单元)。

职责(契约 docs/engineering/tasks/tb-p1-lifecycle-foundation-plan.md,Gate P1-A..F):

1. **变更判定**:incoming RawDocument vs PG 权威现行版本(content_hash /
   metadata_hash)→ UNCHANGED / METADATA_CHANGED / CONTENT_CHANGED / NEW_VERSION;
2. **生成构建**:content 变更文档 → 新代(PENDING→PROCESSING)→ chunk →
   embed → 生成命名空间确定性 UUID 写入(uuid5(source_id#generation#index),
   旧代对象原位不动)→ 验证(对象数 == chunk 数,激活前,I-5);
3. **原子激活**:单事务 = 版本行+chunk 副本落库 + documents.current_version_id
   翻转 + 前任版本 superseded 留痕(服务视角要么旧版要么新版,Gate P1-D);
   前任代撤出完成后转 retired(+7 天 GC 资格,§8a);
4. **失败隔离**:任一文档失败 → 整轮不激活(既有「失败不推窗口」纪律),
   代标 failed + 失败证据,已写对象 best-effort 本文档局部清除(P0-A:
   只按自身确定性 UUID 点删),在服代分毫不动(Gate P1-C);
5. **metadata-only 路径**:不重嵌、不分叉版本/身份,仅更新对象文档级 props
   + 账本/版本 metadata_hash(FC-5);
6. **真值重建/修复**:从 PG 持久 chunk 副本(document_version_chunks)重建
   对象(repair / P1-A 投影重建 / P1-E 全量重建共用),绝不以 Weaviate
   现存对象为唯一内容来源。

无并发需求(同步 cron 串行;#18 删除与同步互斥),Postgres 写用同步会话。
"""

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from backend.db.models import (
    Document,
    DocumentVersion,
    DocumentVersionChunk,
    IndexGeneration,
)
from backend.pipeline.chunk import Chunk
from backend.pipeline.chunk_code import LANG_MAP as _CODE_LANG_MAP  # noqa: F401 (与 ingest 同源)
from backend.pipeline.ingest import (
    DocFailure,
    IngestFailures,
    IngestionPipeline,
    _build_props,
    _enforce_char_limit,
    _is_code,
    chunk_code,
    chunk_document_semantic,
    chunk_uuids_for_version,
    generation_chunk_uuids,
    generation_uuid,
    write_collection_objects,
)
from backend.services import document_lifecycle as lifecycle
from backend.services.sync_runs import (
    STAGE_CHUNK,
    STAGE_EMBED,
    STAGE_INDEX,
    STAGE_SAFETY_FILTER,
)

logger = logging.getLogger(__name__)


@dataclass
class BuildAccounting:
    """一轮构建的变更账本(SyncLog/SyncRun 记账 + 测试断言)。"""

    source_id: str
    new_docs: list[str] = field(default_factory=list)
    updated_docs: list[str] = field(default_factory=list)
    unchanged_docs: list[str] = field(default_factory=list)
    metadata_docs: list[str] = field(default_factory=list)
    generation_ordinal: int | None = None
    generation_status: str | None = None
    chunks_written: int = 0


@dataclass
class _PreparedDoc:
    """单文档构建中间态:chunk 切分结果(线程内先切分,后跨文档批量 embed)。"""

    doc: Any
    chunks: list[Chunk]


class GenerationBuilder:
    """生成构建器:包装 IngestionPipeline 的 chunk/embed/写能力,叠加
    版本/生成/激活语义。Postgres 写用同步 session(与管道惯例一致)。"""

    def __init__(
        self,
        pipeline: IngestionPipeline,
        session_factory: sessionmaker[Session],
    ) -> None:
        self._pipeline = pipeline
        self._session_factory = session_factory

    # ------------------------------------------------------------------ #
    # 判定
    # ------------------------------------------------------------------ #

    def classify_docs(self, docs: list[Any]) -> dict[str, tuple[Any, str, Document | None, DocumentVersion | None]]:
        """逐文档判定变更类别(权威 = PG 现行版本)。

        Returns:
            {source_id: (doc, change_class, document_row, current_version_row)}
        """
        out: dict[str, tuple[Any, str, Document | None, DocumentVersion | None]] = {}
        with self._session_factory() as session:
            for doc in docs:
                doc_row, version_row = lifecycle.load_document_and_current_version(
                    session, doc.source_id
                )
                meta_hash = lifecycle.compute_metadata_hash(
                    title=doc.title,
                    url=doc.url,
                    branch=doc.branch or "",
                    source_type=doc.source_type,
                    product=doc.product,
                    metadata={k: v for k, v in (doc.metadata or {}).items() if k != "channel_visibility"},
                    channel_visibility=doc.channel_visibility,
                )
                change = lifecycle.classify_change(
                    doc_row, version_row, doc.content_hash, meta_hash
                )
                out[doc.source_id] = (doc, change, doc_row, version_row)
        return out

    # ------------------------------------------------------------------ #
    # 主入口:一轮同步的构建(分类 → 构建 → 验证 → 原子激活)
    # ------------------------------------------------------------------ #

    def build_generation(
        self,
        docs: list[Any],
        *,
        source_id: str,
        force_rebuild: bool = False,
        progress: "Any | None" = None,
    ) -> BuildAccounting:
        """一轮变更 → 一个生成代 → 原子激活。

        - ``force_rebuild=True``(--reindex / refill 旧语义回退):忽略
          UNCHANGED/METADATA 判定,全部按内容重建(新版本,重分块重嵌);
        - 任一文档失败:raise IngestFailures(既有契约),本轮**零激活**。
        """
        accounting = BuildAccounting(source_id=source_id)
        if not docs:
            return accounting

        classified = self.classify_docs(docs)

        def _progress(stage: str, n: int) -> None:
            if progress is not None:
                progress(stage, n)

        # metadata-only:不进生成代(无重嵌、无新版本)
        metadata_targets: list[tuple[Any, Document, DocumentVersion]] = []
        rebuild_docs: list[Any] = []
        for doc in docs:
            _doc, change, doc_row, version_row = classified[doc.source_id]
            if force_rebuild or change == lifecycle.ChangeClass.CONTENT_CHANGED:
                rebuild_docs.append(doc)
            elif change == lifecycle.ChangeClass.METADATA_CHANGED:
                assert doc_row is not None and version_row is not None
                metadata_targets.append((doc, doc_row, version_row))
                accounting.metadata_docs.append(doc.source_id)
            elif change == lifecycle.ChangeClass.UNCHANGED:
                accounting.unchanged_docs.append(doc.source_id)
            else:
                rebuild_docs.append(doc)  # NEW_VERSION(首灌)

        if metadata_targets:
            self._apply_metadata_only(metadata_targets)

        if not rebuild_docs:
            _progress(STAGE_SAFETY_FILTER, len(docs))
            _progress(STAGE_CHUNK, len(docs))
            _progress(STAGE_EMBED, len(docs))
            _progress(STAGE_INDEX, len(docs))
            return accounting

        gen, total_chunks_activated = self._build_and_activate(
            rebuild_docs, source_id=source_id, progress=_progress
        )
        accounting.generation_ordinal = gen.ordinal
        accounting.generation_status = gen.status
        accounting.chunks_written = total_chunks_activated
        for d in rebuild_docs:
            row = classified[d.source_id][2]
            if row is None:
                accounting.new_docs.append(d.source_id)
            else:
                accounting.updated_docs.append(d.source_id)
        return accounting

    # ------------------------------------------------------------------ #
    # 构建核心:写对象 → 验证 → 单事务激活
    # ------------------------------------------------------------------ #

    def _build_and_activate(
        self,
        docs: list[Any],
        *,
        source_id: str,
        progress: "Any | None" = None,
    ) -> tuple[IndexGeneration, int]:
        pipeline = self._pipeline
        with self._session_factory() as session:
            gen = lifecycle.create_generation(session, source_id)
            gen_id = str(gen.id)
            gen_ordinal = int(gen.ordinal)
            session.commit()

        written: dict[str, list[Chunk]] = {}
        failed: list[DocFailure] = []
        results: dict[str, int] = {}
        done = 0

        def _progress(stage: str, n: int) -> None:
            if progress is not None:
                progress(stage, n)

        # Phase 1:逐文档安全过滤 + 切分(与 ingest 同源)
        prepared: list[_PreparedDoc] = []
        for doc in docs:
            done += 1
            _progress(STAGE_SAFETY_FILTER, done)
            try:
                verdict = pipeline._safety.check_content(doc.content)
                if not verdict.safe:
                    from backend.connectors.safety import record_safety_exclusion

                    record_safety_exclusion(
                        pipeline.safety_stats, doc.source_id, verdict.reason, verdict.detail
                    )
                    failed.append(
                        DocFailure(
                            source_id=doc.source_id,
                            stage=STAGE_SAFETY_FILTER,
                            error_class="permanent_safety_excluded",
                            retryable=False,
                            detail=verdict.reason,
                        )
                    )
                    continue
                if _is_code(doc):
                    chunks = chunk_code(doc, pipeline._max_tokens, pipeline._overlap)
                else:
                    chunks = chunk_document_semantic(doc, pipeline._max_tokens, pipeline._overlap)
                chunks = _enforce_char_limit(chunks, pipeline._max_chunk_chars)
                if not chunks:
                    logger.info("文档 %s 切分为空,跳过本代构建", doc.source_id)
                    continue
                prepared.append(_PreparedDoc(doc=doc, chunks=chunks))
                _progress(STAGE_CHUNK, done)
            except Exception as exc:  # noqa: BLE001 - 记入 failed,统一 raise(既有契约)
                logger.error("构建切分失败 %s: %s", doc.source_id, str(exc)[:200])
                failed.append(
                    DocFailure(
                        source_id=doc.source_id,
                        stage=STAGE_CHUNK,
                        error_class="error",
                        retryable=True,
                        detail=str(exc)[:200],
                    )
                )

        # Phase 2:跨文档拼平批量 embed(GPU 效率,与既有管道同策略)
        all_texts: list[str] = []
        spans: list[tuple[int, int]] = []
        for p in prepared:
            s = len(all_texts)
            all_texts.extend(c.text for c in p.chunks)
            spans.append((s, len(all_texts)))
        try:
            all_vectors = pipeline._embedder.embed(all_texts) if all_texts else []
            if len(all_vectors) != len(all_texts):
                raise RuntimeError(f"embedder 返回 {len(all_vectors)} 向量,期望 {len(all_texts)}")
        except Exception as exc:
            self._fail_generation(gen, {"error": str(exc)[:300], "stage": STAGE_EMBED})
            self._cleanup_written_objects(gen_id, written)
            for p in prepared:
                failed.append(
                    DocFailure(
                        source_id=p.doc.source_id,
                        stage=STAGE_EMBED,
                        error_class="retryable_transport",
                        retryable=True,
                        detail=f"batch embed failed: {str(exc)[:160]}",
                    )
                )
            raise IngestFailures(
                f"生成 {gen_ordinal} 构建失败(embed):{failed[0].detail if failed else exc}",
                failures=failed,
            ) from exc
        _progress(STAGE_EMBED, len(docs))

        # Phase 3:构造对象(生成命名空间 UUID + generation props)并写入
        pipeline._ensure_collection()
        collection = pipeline._collection
        import weaviate as _wv

        for p, (s, e) in zip(prepared, spans):
            vecs = all_vectors[s:e]
            objs = []
            for chunk, vector in zip(p.chunks, vecs):
                props = dict(_build_props(chunk, p.doc))
                props["generation_id"] = gen_id
                props["generation_ordinal"] = gen_ordinal
                objs.append(
                    _wv.classes.data.DataObject(
                        properties=props,
                        vector=np.asarray(vector).tolist(),
                        uuid=generation_uuid(p.doc.source_id, gen_id, chunk.chunk_index),
                    )
                )
            replace_failed = write_collection_objects(collection, objs)
            written[p.doc.source_id] = p.chunks
            ok = len(objs) - len(replace_failed)
            results[p.doc.source_id] = ok
            if replace_failed:
                failed.append(
                    DocFailure(
                        source_id=p.doc.source_id,
                        stage=STAGE_INDEX,
                        error_class="retryable_write",
                        retryable=True,
                        detail=f"{len(replace_failed)}/{len(objs)} chunk 写入 Weaviate 彻底失败(insert+replace)",
                    )
                )
        _progress(STAGE_INDEX, len(docs))

        if failed:
            self._fail_generation(
                gen, {"error": "doc build failures", "docs": [f.source_id for f in failed[:20]]}
            )
            self._cleanup_written_objects(gen_id, written)
            lines = [
                f"{f.source_id} stage={f.stage} class={f.error_class} detail={f.detail[:120]}"
                for f in failed[:10]
            ]
            raise IngestFailures(
                f"生成 {gen_ordinal} 构建失败({len(failed)} 篇,零激活): " + " | ".join(lines),
                failures=failed,
            )

        # Phase 4:激活前验证(对象数 == chunk 数;I-5 验证先于激活)
        invalid = self._validate_written(collection, gen_id, written)
        if invalid:
            self._fail_generation(
                gen,
                {"error": "validation failed", "docs": {k: v for k, v in invalid.items()}},
            )
            self._cleanup_written_objects(gen_id, written)
            raise IngestFailures(
                f"生成 {gen_ordinal} 验证失败({list(invalid.items())[:5]}),零激活",
                failures=[
                    DocFailure(
                        source_id=k,
                        stage=STAGE_INDEX,
                        error_class="validation",
                        retryable=True,
                        detail=f"expected {v[0]} chunks, found {v[1]}",
                    )
                    for k, v in invalid.items()
                ],
            )

        # Phase 5:原子激活(单事务:版本+chunk 副本+翻转+前任 superseded)
        predecessor_gens: list[Any] = []
        total_chunks = 0
        with self._session_factory() as session:
            gen_row = session.execute(
                select(IndexGeneration).where(IndexGeneration.id == gen.id)
            ).scalar_one()
            for p in prepared:
                doc_row, _old_version = lifecycle.load_document_and_current_version(
                    session, p.doc.source_id
                )
                if doc_row is None:
                    doc_row = Document(
                        source_id=p.doc.source_id,
                        content_hash=p.doc.content_hash,
                        source_type=p.doc.source_type,
                        product=p.doc.product,
                        title=p.doc.title,
                        url=p.doc.url,
                        metadata_=dict(p.doc.metadata or {}),
                        branch=p.doc.branch or "",
                        chunk_count=0,
                    )
                    session.add(doc_row)
                    session.flush()
                version = DocumentVersion(
                    source_id=p.doc.source_id,
                    version_seq=lifecycle.next_version_seq(session, p.doc.source_id),
                    content_hash=p.doc.content_hash,
                    metadata_hash=lifecycle.compute_metadata_hash(
                        title=p.doc.title,
                        url=p.doc.url,
                        branch=p.doc.branch or "",
                        source_type=p.doc.source_type,
                        product=p.doc.product,
                        metadata={k: v for k, v in (p.doc.metadata or {}).items() if k != "channel_visibility"},
                        channel_visibility=p.doc.channel_visibility,
                    ),
                    source_version=lifecycle.extract_source_version(p.doc.metadata),
                    generation_id=gen.id,
                    generation_ordinal=gen_ordinal,
                    status="active",
                    title=p.doc.title,
                    url=p.doc.url,
                    chunk_count=len(p.chunks),
                )
                session.add(version)
                session.flush()
                for chunk in p.chunks:
                    props = dict(_build_props(chunk, p.doc))
                    props["generation_id"] = gen_id
                    props["generation_ordinal"] = gen_ordinal
                    session.add(
                        DocumentVersionChunk(
                            version_id=version.id,
                            chunk_index=chunk.chunk_index,
                            text=chunk.text,
                            props=props,
                        )
                    )
                previous = lifecycle.activate_document_version(session, doc_row, version)
                if previous is not None and previous.generation_id != gen.id:
                    predecessor_gens.append(previous.generation_id)
                total_chunks += len(p.chunks)
            lifecycle.mark_generation_ready(
                session,
                gen_row,
                doc_count=len(prepared),
                chunk_count=total_chunks,
            )
            gen_row.activated_at = lifecycle.utcnow()
            session.commit()
        # gen 是早期独立会话的对象;账本状态以 Phase5 权威行为准(否则
        # accounting 会把 ready 代误报为 processing)
        gen.status = gen_row.status

        # Phase 6:前任代撤出退休(激活提交后 active 集已不含它们,即时撤出)
        with self._session_factory() as session:
            for gid in set(predecessor_gens):
                lifecycle.retire_generation_if_withdrawn(session, gid)
            session.commit()

        logger.info(
            "生成 %s(ord=%d)已激活: %d 篇 / %d chunks;前任代 %d 个",
            gen_id[:8],
            gen_ordinal,
            len(prepared),
            total_chunks,
            len(set(predecessor_gens)),
        )
        return gen, total_chunks

    # ------------------------------------------------------------------ #
    # 验证 / 失败清理(P0-A:只按本文档自身确定性 UUID 点删)
    # ------------------------------------------------------------------ #

    def _validate_written(
        self, collection: Any, gen_id: str, written: dict[str, list[Chunk]]
    ) -> dict[str, tuple[int, int]]:
        """逐文档验证:新代命名空间下对象数 == 期望 chunk 数(激活前置,I-5)。"""
        from weaviate.classes.query import Filter

        invalid: dict[str, tuple[int, int]] = {}
        for source_id, chunks in written.items():
            expected = len(chunks)
            uuids = generation_chunk_uuids(source_id, gen_id, expected)
            found = 0
            for start in range(0, len(uuids), 500):
                batch = uuids[start : start + 500]
                resp = collection.query.fetch_objects(
                    filters=Filter.by_id().contains_any(batch), limit=len(batch)
                )
                found += len(resp.objects)
            if found != expected:
                invalid[source_id] = (expected, found)
        return invalid

    def _fail_generation(self, gen: IndexGeneration, failure: dict[str, Any]) -> None:
        try:
            with self._session_factory() as session:
                row = session.execute(
                    select(IndexGeneration).where(IndexGeneration.id == gen.id)
                ).scalar_one_or_none()
                if row is not None:
                    lifecycle.mark_generation_failed(session, row, failure)
                    # 失败代对象永不进入服务集 → 无保留价值,立即具备 GC 资格
                    row.gc_eligible_at = lifecycle.utcnow()
                    session.commit()
        except Exception as exc:  # noqa: BLE001 - 失败记账失败不影响主失败路径
            logger.warning("生成 %s 失败记账失败: %s", str(gen.id)[:8], str(exc)[:160])

    def _cleanup_written_objects(
        self, gen_id: str, written: dict[str, list[Chunk]]
    ) -> None:
        """失败代已写对象 best-effort 清理(本文档自身新代 UUID 点删,P0-A)。"""
        if not written:
            return
        try:
            from weaviate.classes.query import Filter

            collection = self._pipeline._collection
            for source_id, chunks in written.items():
                uuids = generation_chunk_uuids(source_id, gen_id, len(chunks))
                for start in range(0, len(uuids), 500):
                    collection.data.delete_many(
                        where=Filter.by_id().contains_any(uuids[start : start + 500])
                    )
            logger.info("失败代 %s 已写对象清理完成(%d 篇)", gen_id[:8], len(written))
        except Exception as exc:  # noqa: BLE001 - 清理失败:残留不入服务集,GC 兜底
            logger.warning(
                "失败代 %s 残留对象清理失败(不影响在服,GC 兜底): %s",
                gen_id[:8],
                str(exc)[:160],
            )

    # ------------------------------------------------------------------ #
    # metadata-only 路径(不重嵌、不新版本、不分叉身份,FC-5)
    # ------------------------------------------------------------------ #

    def _apply_metadata_only(
        self, targets: list[tuple[Any, Document, DocumentVersion]]
    ) -> None:
        from weaviate.classes.query import Filter

        pipeline = self._pipeline
        pipeline._ensure_collection()
        collection = pipeline._collection
        for doc, doc_row, version in targets:
            new_meta_hash = lifecycle.compute_metadata_hash(
                title=doc.title,
                url=doc.url,
                branch=doc.branch or "",
                source_type=doc.source_type,
                product=doc.product,
                metadata={k: v for k, v in (doc.metadata or {}).items() if k != "channel_visibility"},
                channel_visibility=doc.channel_visibility,
            )
            # 1) 对象文档级 props 原位更新(merge update,向量不动)
            uuids = chunk_uuids_for_version(
                doc_row.source_id,
                str(version.generation_id),
                int(version.generation_ordinal),
                int(version.chunk_count),
            )
            stale_props = {
                "title": doc.title,
                "url": doc.url,
                "branch": doc.branch or "",
                "source_type": doc.source_type,
                "product": doc.product,
                "channel_visibility": list(doc.channel_visibility),
            }
            try:
                from backend.pipeline.ingest import _evidence_props

                stale_props.update(_evidence_props(doc))
                for start in range(0, len(uuids), 500):
                    batch = uuids[start : start + 500]
                    resp = collection.query.fetch_objects(
                        filters=Filter.by_id().contains_any(batch), limit=len(batch)
                    )
                    for obj in resp.objects:
                        collection.data.update(uuid=str(obj.uuid), properties=stale_props)
            except Exception as exc:  # noqa: BLE001 - 对象侧失败:账本已真,下轮 metadata 变更自愈
                logger.warning(
                    "metadata-only 对象更新失败 %s(账本先行,残留下轮自愈): %s",
                    doc.source_id,
                    str(exc)[:160],
                )
            # 2) 账本 + 版本 metadata_hash(权威先行)
            with self._session_factory() as session:
                row = session.execute(
                    select(Document).where(Document.source_id == doc.source_id)
                ).scalar_one()
                row.title = doc.title
                row.url = doc.url
                row.branch = doc.branch or ""
                row.source_type = doc.source_type
                row.product = doc.product
                row.metadata_ = dict(doc.metadata or {})
                ver = session.execute(
                    select(DocumentVersion).where(DocumentVersion.id == row.current_version_id)
                ).scalar_one()
                ver.metadata_hash = new_meta_hash
                ver.title = doc.title
                ver.url = doc.url
                # 持久 chunk 副本的 props 同步文档级字段(重建保真)
                chunks = session.execute(
                    select(DocumentVersionChunk).where(DocumentVersionChunk.version_id == ver.id)
                ).scalars().all()
                for c in chunks:
                    props = dict(c.props or {})
                    props.update(stale_props)
                    c.props = props
                session.commit()
            logger.info("metadata-only 更新 %s(零重嵌、零版本分叉)", doc.source_id)

    # ------------------------------------------------------------------ #
    # 真值重建 / 修复(P1-A 投影重建 / P1-E 全量重建 / gap-heal 共用)
    # ------------------------------------------------------------------ #

    def repair_documents(
        self,
        source_ids: list[str],
        *,
        source_id_scope: str,
        progress: "Any | None" = None,
    ) -> tuple[list[str], list[str], int]:
        """从 PG 持久 chunk 副本重建对象(零源抓取;embed 由存储文本再生)。

        不新建版本:current 版本关系不变,仅对象在新代重物化 + 版本代归属
        原子切换。旧代本文档对象(如有残留)在切换提交后按旧代命名空间
        本文档局部清除。

        Returns:
            (repaired, unrepairable, chunks_repaired) — unrepairable = 无持久
            chunk 副本(迁移缺口),调用方回退源抓取补灌。
        """
        repaired: list[str] = []
        unrepairable: list[str] = []
        plans: list[tuple[Document, DocumentVersion, list[DocumentVersionChunk]]] = []
        with self._session_factory() as session:
            for sid in source_ids:
                doc_row, version = lifecycle.load_document_and_current_version(session, sid)
                if doc_row is None or version is None:
                    unrepairable.append(sid)
                    continue
                chunks = (
                    session.execute(
                        select(DocumentVersionChunk)
                        .where(DocumentVersionChunk.version_id == version.id)
                        .order_by(DocumentVersionChunk.chunk_index)
                    )
                    .scalars()
                    .all()
                )
                if not chunks:
                    unrepairable.append(sid)
                    continue
                plans.append((doc_row, version, list(chunks)))
        if not plans:
            return repaired, unrepairable, 0

        gen = self._build_and_activate_repair(plans, source_id_scope=source_id_scope, progress=progress)
        _ = gen
        repaired = [p[0].source_id for p in plans]
        chunks_repaired = sum(len(p[2]) for p in plans)
        return repaired, unrepairable, chunks_repaired

    def _build_and_activate_repair(
        self,
        plans: list[tuple[Document, DocumentVersion, list[DocumentVersionChunk]]],
        *,
        source_id_scope: str,
        progress: "Any | None" = None,
    ) -> IndexGeneration:
        pipeline = self._pipeline
        with self._session_factory() as session:
            gen = lifecycle.create_generation(session, source_id_scope)
            gen_id = str(gen.id)
            gen_ordinal = int(gen.ordinal)
            session.commit()

        # embed 存储文本(向量再生;结构来自持久 props,不依赖 Weaviate 对象)
        texts = [c.text for _d, _v, chunks in plans for c in chunks]
        try:
            vectors = pipeline._embedder.embed(texts) if texts else []
            if len(vectors) != len(texts):
                raise RuntimeError(f"embedder 返回 {len(vectors)} 向量,期望 {len(texts)}")
        except Exception as exc:
            self._fail_generation(gen, {"error": str(exc)[:300], "stage": "repair_embed"})
            raise IngestFailures(
                f"修复代 {gen_ordinal} embed 失败(零激活): {str(exc)[:200]}",
                failures=[],
            ) from exc
        if progress is not None:
            progress(STAGE_EMBED, len(plans))

        pipeline._ensure_collection()
        collection = pipeline._collection
        import weaviate as _wv

        objs = []
        cursor = 0
        for _doc, version, chunks in plans:
            for c in chunks:
                props = dict(c.props or {})
                props["generation_id"] = gen_id
                props["generation_ordinal"] = gen_ordinal
                objs.append(
                    _wv.classes.data.DataObject(
                        properties=props,
                        vector=np.asarray(vectors[cursor]).tolist(),
                        uuid=generation_uuid(version.source_id, gen_id, c.chunk_index),
                    )
                )
                cursor += 1
        replace_failed = write_collection_objects(collection, objs)
        if replace_failed:
            self._fail_generation(
                gen, {"error": "repair write failures", "count": len(replace_failed)}
            )
            self._cleanup_repair_objects(gen_id, plans)
            raise IngestFailures(
                f"修复代 {gen_ordinal} 写入失败 {len(replace_failed)} 对象(零激活)",
                failures=[],
            )

        # 验证(激活前,I-5):新代命名空间下逐文档对象数 == 持久 chunk 数
        invalid: dict[str, tuple[int, int]] = {}
        for _doc, version, chunks in plans:
            found = self._count_objects(collection, gen_id, version.source_id, len(chunks))
            if found != len(chunks):
                invalid[version.source_id] = (len(chunks), found)
        if invalid:
            self._fail_generation(gen, {"error": "repair validation failed", "docs": invalid})
            self._cleanup_repair_objects(gen_id, plans)
            raise IngestFailures(f"修复代 {gen_ordinal} 验证失败:{invalid}", failures=[])

        # 原子切换版本代归属(单事务);切换前采集旧代归属(供提交后清理)
        old_refs = [
            (
                version.source_id,
                str(version.generation_id),
                int(version.generation_ordinal),
                len(chunks),
            )
            for _doc, version, chunks in plans
        ]
        predecessor_gens: list[Any] = []
        with self._session_factory() as session:
            gen_row = session.execute(
                select(IndexGeneration).where(IndexGeneration.id == gen.id)
            ).scalar_one()
            total = 0
            for _doc, version, chunks in plans:
                # plans 里的 version 是已关闭会话的 detached 实例——必须先
                # merge 进本事务再改,否则代归属翻转不会落库(detached 变更
                # 不进 session.dirty,commit 即静默丢失)。
                row = session.merge(version)
                old_gen = row.generation_id
                row.generation_id = gen.id
                row.generation_ordinal = gen_ordinal
                if str(old_gen) != gen_id:
                    predecessor_gens.append(old_gen)
                total += len(chunks)
            lifecycle.mark_generation_ready(session, gen_row, doc_count=len(plans), chunk_count=total)
            gen_row.activated_at = lifecycle.utcnow()
            session.commit()
        gen.status = gen_row.status
        with self._session_factory() as session:
            for gid in set(predecessor_gens):
                lifecycle.retire_generation_if_withdrawn(session, gid)
            session.commit()

        # 旧代本文档残留对象清除(提交后;撤出已生效,物理清理防重复命中;
        # P0-A:仅按本文档自身旧代命名空间 UUID 点删)
        try:
            from weaviate.classes.query import Filter

            for sid, old_gen_id, old_ordinal, count in old_refs:
                if str(old_gen_id) == gen_id:
                    continue
                old_uuids = chunk_uuids_for_version(sid, old_gen_id, old_ordinal, count)
                for start in range(0, len(old_uuids), 500):
                    collection.data.delete_many(
                        where=Filter.by_id().contains_any(old_uuids[start : start + 500])
                    )
        except Exception as exc:  # noqa: BLE001 - 清理失败:旧代对象已不服务,GC 兜底
            logger.warning("修复后旧代对象清理失败(GC 兜底): %s", str(exc)[:160])

        logger.info("修复代 %s(ord=%d)已激活: %d 篇", gen_id[:8], gen_ordinal, len(plans))
        return gen

    def _cleanup_repair_objects(
        self,
        gen_id: str,
        plans: list[tuple[Document, DocumentVersion, list[DocumentVersionChunk]]],
    ) -> None:
        """修复失败路径:已写新代对象 best-effort 清理(本文档局部,P0-A)。"""
        try:
            from weaviate.classes.query import Filter

            collection = self._pipeline._collection
            for _doc, version, chunks in plans:
                uuids = generation_chunk_uuids(version.source_id, gen_id, len(chunks))
                for start in range(0, len(uuids), 500):
                    collection.data.delete_many(
                        where=Filter.by_id().contains_any(uuids[start : start + 500])
                    )
        except Exception as exc:  # noqa: BLE001 - 残留不入服务集,GC 兜底
            logger.warning("修复代 %s 残留清理失败(GC 兜底): %s", gen_id[:8], str(exc)[:160])

    def _count_objects(self, collection: Any, gen_id: str, source_id: str, expected: int) -> int:
        from weaviate.classes.query import Filter

        uuids = generation_chunk_uuids(source_id, gen_id, expected)
        found = 0
        for start in range(0, len(uuids), 500):
            batch = uuids[start : start + 500]
            resp = collection.query.fetch_objects(
                filters=Filter.by_id().contains_any(batch), limit=len(batch)
            )
            found += len(resp.objects)
        return found
