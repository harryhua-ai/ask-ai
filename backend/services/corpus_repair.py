"""Production Repair 前置工具(Issue #13 Stage A;dry-run 为默认,apply 显式)。

为 Production Repair Gate 提供安全工具面(本轮仅本地/测试使用,生产执行需
独立授权):

- **四类操作**:
    RETIRE_UNSAFE_ARTIFACT        历史 invalid artifact 退休(D3:Technical
                                  Safety 判定为准,复用
                                  ``historical_artifact_verdict``,绝不硬编码
                                  扩展名清单);含账本行+向量,或仅孤儿向量。
    REBUILD_ORPHAN_LEDGER_ROW     孤儿账本重建(零 embedding,按向量存量属性
                                  重建路径身份行;D1/D2 后同内容兄弟路径共存,
                                  不再触发 (content_hash, branch) 冲突)。
    RETIRE_DELETED_DOCUMENT       源确认已删除文档的账本行+向量退休(仅在
                                  调用方提供权威 membership 证据时生成)。
    REPORT_DUPLICATE_IDENTITY     同内容多路径(D2 下为合法共存,仅事实呈现,
                                  零变更)。

- **安全不变量**:
    - dry-run(plan)绝不写库/删向量;apply 必须显式调用(CLI 另需 --apply);
    - 全部删除按确定性 UUID(uuid5(source_id#i))点删,批次 500,禁止任何
      collection 级操作 / TEXT 属性过滤(P0-A 红线);
    - 确定性:entries 按 path 排序,uuid 升序;幂等:重复 plan→空,重复
      apply→no-op;
    - source-scoped:一切按 ``'{prefix}/%'`` / 客户端前缀过滤圈定。

用法见 ``scripts/repair_corpus.py``(CLI 封装,--output 产出可审计 JSON)。
"""

from dataclasses import dataclass, field
import logging
from datetime import UTC, datetime

from sqlalchemy import delete, func, select

from backend.connectors.safety import historical_artifact_verdict
from backend.db.models import Document
from backend.services.vector_consistency import verify_source_vectors

logger = logging.getLogger(__name__)

ACTION_RETIRE_UNSAFE_ARTIFACT = "RETIRE_UNSAFE_ARTIFACT"
ACTION_REBUILD_ORPHAN_LEDGER_ROW = "REBUILD_ORPHAN_LEDGER_ROW"
ACTION_RETIRE_DELETED_DOCUMENT = "RETIRE_DELETED_DOCUMENT"
ACTION_REPORT_DUPLICATE_IDENTITY = "REPORT_DUPLICATE_IDENTITY"

# 携带账本行的操作(apply 时需删账本行);孤儿向量类操作仅删向量
_LEDGER_BEARING_ACTIONS = {
    ACTION_RETIRE_UNSAFE_ARTIFACT,
    ACTION_RETIRE_DELETED_DOCUMENT,
    ACTION_REPORT_DUPLICATE_IDENTITY,
}

_BATCH = 500  # delete_many 单批上限(与 ingest/sync 既有口径一致)


@dataclass(frozen=True)
class RepairEntry:
    """单条修复计划项(dry-run 输出的最小审计单元)。"""

    source: str  # 数据源 ID(前缀)
    path: str  # 复合文档键 <source>/<branch>/<rel_path>
    reason: str  # 机器可读原因(如 model_artifact_ext / orphan_no_ledger_row)
    document_count: int  # 该项涉及的账本行数(0/1)
    chunk_count: int  # 该项涉及的 chunk/向量数
    action: str  # 四类操作之一
    detail: str = ""  # 补充说明(审计用)
    chunk_indices: tuple[int, ...] = ()  # 孤儿向量类操作的实际存量 index(确定性升序)
    ledger_row: bool = True  # False = 仅向量孤儿(账本本就无行)

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "path": self.path,
            "reason": self.reason,
            "document_count": self.document_count,
            "chunk_count": self.chunk_count,
            "action": self.action,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class RepairPlan:
    """dry-run 产物:可序列化、可持久化审计、可确定性重放。"""

    source_prefix: str
    created_at: str
    entries: tuple[RepairEntry, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "source_prefix": self.source_prefix,
            "created_at": self.created_at,
            "dry_run": True,
            "total_entries": len(self.entries),
            "total_chunks": sum(e.chunk_count for e in self.entries),
            "by_action": {
                a: sum(1 for e in self.entries if e.action == a)
                for a in sorted({e.action for e in self.entries})
            },
            "entries": [e.to_dict() for e in self.entries],
        }


@dataclass
class RepairResult:
    """apply 产物:逐项执行结果(审计口径)。"""

    applied: list[str] = field(default_factory=list)  # 已执行 action@path
    skipped: list[str] = field(default_factory=list)  # 已不存在/幂等跳过
    failed: list[str] = field(default_factory=list)  # 失败并保留原因

    def to_dict(self) -> dict:
        return {
            "applied": self.applied,
            "skipped": self.skipped,
            "failed": self.failed,
        }


class CorpusRepairTool:
    """source-scoped corpus 修复工具(plan = dry-run,apply = 显式执行)。"""

    def __init__(self, *, async_session_factory, pipeline) -> None:
        """
        Args:
            async_session_factory: 异步会话工厂(账本读 + 一致性校验,与
                ``verify_source_vectors`` 同款)。
            pipeline: IngestionPipeline(经 ``_client/_class_name/_collection``
                访问 Weaviate;经 ``_session_factory`` 同步写账本)。
        """
        self._session_factory = async_session_factory
        self._pipeline = pipeline

    # ------------------------------------------------------------------ #
    # dry-run:plan(绝不产生任何写副作用)
    # ------------------------------------------------------------------ #

    async def plan(
        self,
        source_prefix: str,
        *,
        orphan_chunks: dict[str, set[int]] | None = None,
        membership: set[str] | None = None,
    ) -> RepairPlan:
        """生成修复计划(dry-run)。

        Args:
            source_prefix: 数据源 ID(严格前缀圈定)。
            orphan_chunks: 可选注入的孤儿明细(source_id → chunk_index 集合);
                缺省时内部调用 ``verify_source_vectors`` 全扫获取。
            membership: 可选权威源成员集(调用方经 connector 权威枚举取得);
                提供时才可能生成 RETIRE_DELETED_DOCUMENT(源确认退休必须有
                成员证据,与 sync reconciliation 同一证据标准)。
        """
        entries: list[RepairEntry] = []
        rows = await self._ledger_rows(source_prefix)
        ledger_sids = {sid for sid, _, _ in rows}

        # 1) 历史 unsafe artifact(账本行路径判定;D3:复用 Technical Safety)
        for sid, _hash, cc in rows:
            verdict = historical_artifact_verdict(sid)
            if not verdict.safe:
                entries.append(
                    RepairEntry(
                        source=source_prefix,
                        path=sid,
                        reason=verdict.reason or "unsafe_artifact",
                        document_count=1,
                        chunk_count=int(cc),
                        action=ACTION_RETIRE_UNSAFE_ARTIFACT,
                        detail=f"historical invalid artifact ({verdict.detail})",
                    )
                )

        # 2) 同内容多路径(D2:合法共存,仅事实呈现,零变更)
        dup_hashes = await self._duplicate_hashes(source_prefix)
        for content_hash, n in dup_hashes:
            sids = sorted(sid for sid, h, _ in rows if h == content_hash)
            entries.append(
                RepairEntry(
                    source=source_prefix,
                    path=f"{source_prefix}/*(content_hash={content_hash[:12]}…)",
                    reason="same_content_multiple_paths",
                    document_count=n,
                    chunk_count=sum(cc for sid, h, cc in rows if h == content_hash),
                    action=ACTION_REPORT_DUPLICATE_IDENTITY,
                    detail="valid coexistence per D2 (no mutation); paths: " + ", ".join(sids[:5]),
                )
            )

        # 3) 孤儿(Weaviate 有、账本无):artifact → 向量退休;安全路径 → 重建
        if orphan_chunks is None:
            report = await verify_source_vectors(
                self._session_factory, self._pipeline, source_prefix
            )
            orphan_chunks = report.orphan_chunks
        for sid in sorted(orphan_chunks):
            indices = tuple(sorted(orphan_chunks[sid]))
            verdict = historical_artifact_verdict(sid)
            if not verdict.safe:
                entries.append(
                    RepairEntry(
                        source=source_prefix,
                        path=sid,
                        reason=verdict.reason or "unsafe_artifact",
                        document_count=0,
                        chunk_count=len(indices),
                        action=ACTION_RETIRE_UNSAFE_ARTIFACT,
                        detail="orphan vector only (no ledger row)",
                        chunk_indices=indices,
                        ledger_row=False,
                    )
                )
            elif sid in ledger_sids:
                continue  # 已有账本行,非孤儿(扫描竞态防御)
            else:
                entries.append(
                    RepairEntry(
                        source=source_prefix,
                        path=sid,
                        reason="orphan_no_ledger_row",
                        document_count=0,
                        chunk_count=len(indices),
                        action=ACTION_REBUILD_ORPHAN_LEDGER_ROW,
                        detail="zero-embedding ledger rebuild from vector props",
                        chunk_indices=indices,
                        ledger_row=False,
                    )
                )

        # 4) 源确认已删除文档(仅在有权威成员证据时;缺证据一律不动)
        if membership is not None:
            for sid, _hash, cc in sorted(rows):
                if sid not in membership and historical_artifact_verdict(sid).safe:
                    entries.append(
                        RepairEntry(
                            source=source_prefix,
                            path=sid,
                            reason="source_confirmed_absence",
                            document_count=1,
                            chunk_count=int(cc),
                            action=ACTION_RETIRE_DELETED_DOCUMENT,
                            detail="path absent from authoritative membership",
                        )
                    )

        entries.sort(key=lambda e: (e.action, e.path))
        return RepairPlan(
            source_prefix=source_prefix,
            created_at=datetime.now(UTC).isoformat(),
            entries=tuple(entries),
        )

    # ------------------------------------------------------------------ #
    # apply:显式执行(幂等;只触碰计划内对象)
    # ------------------------------------------------------------------ #

    async def apply(self, plan: RepairPlan) -> RepairResult:
        """执行计划(仅计划内条目;幂等;失败项保留并报告,绝不静默)。"""
        from weaviate.classes.query import Filter

        from backend.pipeline.ingest import _deterministic_uuid

        result = RepairResult()
        self._pipeline._ensure_collection()
        collection = self._pipeline._collection

        for entry in plan.entries:
            tag = f"{entry.action}@{entry.path}"
            try:
                if entry.action == ACTION_REPORT_DUPLICATE_IDENTITY:
                    result.skipped.append(f"{tag} (report-only per D2)")
                    continue

                if entry.ledger_row:
                    if await self._delete_ledger_row(entry.path):
                        result.applied.append(f"{tag} ledger-row")
                    else:
                        result.skipped.append(f"{tag} ledger-row (already absent)")
                elif entry.action == ACTION_REBUILD_ORPHAN_LEDGER_ROW:
                    inserted = await self._rebuild_ledger_row(entry, collection, Filter)
                    if inserted:
                        result.applied.append(f"{tag} ledger-row")
                    else:
                        result.skipped.append(f"{tag} (row already present)")
                    continue  # 重建不动向量

                # 向量退休(账本行口径:0..chunk_count-1;孤儿口径:实际存量 index)
                indices = (
                    entry.chunk_indices if entry.chunk_indices else tuple(range(entry.chunk_count))
                )
                uuids = [_deterministic_uuid(entry.path, i) for i in indices]
                for start in range(0, len(uuids), _BATCH):
                    collection.data.delete_many(
                        where=Filter.by_id().contains_any(uuids[start : start + _BATCH])
                    )
                result.applied.append(f"{tag} vectors({len(uuids)})")
            except Exception as exc:  # noqa: BLE001 - 单项失败不中断,如实报告
                logger.error("repair apply 失败 %s: %s", tag, str(exc)[:200])
                result.failed.append(f"{tag}: {str(exc)[:160]}")
        return result

    # ------------------------------------------------------------------ #
    # 内部:账本访问
    # ------------------------------------------------------------------ #

    async def _ledger_rows(self, source_prefix: str) -> list[tuple[str, str, int]]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(Document.source_id, Document.content_hash, Document.chunk_count)
                    .where(Document.source_id.like(f"{source_prefix}/%"))
                    .order_by(Document.source_id)
                )
            ).all()
        return [(str(sid), str(h), int(cc)) for sid, h, cc in rows]

    async def _duplicate_hashes(self, source_prefix: str) -> list[tuple[str, int]]:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(Document.content_hash, func.count(Document.source_id))
                    .where(Document.source_id.like(f"{source_prefix}/%"))
                    .group_by(Document.content_hash)
                    .having(func.count(Document.source_id) > 1)
                    .order_by(Document.content_hash)
                )
            ).all()
        return [(str(h), int(n)) for h, n in rows]

    async def _delete_ledger_row(self, path: str) -> bool:
        """删除路径账本行;返回是否确有行被删(幂等口径)。"""
        async with self._session_factory() as session:
            result = await session.execute(delete(Document).where(Document.source_id == path))
            await session.commit()
        return bool(result.rowcount)

    async def _rebuild_ledger_row(self, entry: RepairEntry, collection, Filter) -> bool:
        """零 embedding 按向量存量重建账本行。返回是否真正插入(幂等判定)。"""
        from backend.pipeline.ingest import _deterministic_uuid

        sync_factory = self._pipeline._session_factory
        if sync_factory is None:
            raise RuntimeError("pipeline 无账本会话工厂,拒绝重建(保留孤儿,人工核查)")
        async with self._session_factory() as session:
            existing = (
                await session.execute(
                    select(Document.source_id).where(Document.source_id == entry.path)
                )
            ).scalar_one_or_none()
        if existing is not None:
            return False  # 幂等:行已在(并发修复/灌入),跳过

        uuids = [_deterministic_uuid(entry.path, i) for i in entry.chunk_indices]
        fetched = collection.query.fetch_objects(
            filters=Filter.by_id().contains_any(uuids), limit=len(uuids)
        )
        if len(fetched.objects) != len(entry.chunk_indices):
            raise RuntimeError(
                f"存量与计划不一致({len(fetched.objects)}/{len(entry.chunk_indices)}),"
                "拒绝重建(保留孤儿,人工核查)"
            )
        props = fetched.objects[0].properties
        content_hash = props.get("content_hash")
        if not content_hash:
            raise RuntimeError("缺 content_hash 属性,拒绝重建(保留孤儿,人工核查)")
        with sync_factory() as session:
            session.add(
                Document(
                    content_hash=str(content_hash),
                    source_id=entry.path,
                    source_type=str(props.get("source_type") or ""),
                    product=str(props.get("product") or ""),
                    title=str(props.get("title") or ""),
                    url=str(props.get("url") or ""),
                    branch=str(props.get("branch") or ""),
                    chunk_count=max(entry.chunk_indices) + 1,
                )
            )
            session.commit()
        return True
