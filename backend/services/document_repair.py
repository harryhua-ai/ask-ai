"""v1.6.3 Track C(U-8):行级修复工作流(受控、可审计、幂等、带验证)。

冻结语义(DS-P2-25/26、DS-P3-07/08/09):真实修复工作流 = **授权/RBAC、
幂等命令、可审计执行、进度/结果、修复后验证**;禁止 UI-only repair。

实现语义迁移自 corpus_repair 受控工具(plan→apply→verify)与同步执行面
gap-heal 路径(从 PG 持久 chunk 副本重建,零源抓取、确定性 uuid、幂等):

- 计划(plan):chunk serving 投影(U-9 权威口径)得出缺失/多余 index;
- 修复(apply):对缺失 index,从 ``document_version_chunks`` 持久副本取
  text+props → embed → 在服代命名空间确定性 uuid(``chunk_uuids_for_version``;
  INT-C-01:按该文档现行版本 generation 写 generation_uuid + generation_id/
  generation_ordinal props,与 gap-heal/generation_builder 同款语义)幂等
  覆写回 Weaviate。零源抓取、只触碰本计划内对象(不整表/不做属性过滤删除);
- 复验(verify):重算投影并按在服代过滤(与 plan 同口径;legacy/旧代
  残留不计在服);在服集合 == 期望集合 → consistency=passed;
- 任务/审计持久化:``document_repair_tasks`` 行即审计记录(status/stage/
  events 追加/result 真值);
- 幂等:同文档存在未完结任务 → 返回同一任务;健康文档重复修复 = 真实
  复验 no-op(0 重灌,复验通过),绝不做假进度。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db.models import Document, DocumentRepairTask, DocumentVersion, DocumentVersionChunk
from backend.pipeline.ingest import chunk_uuids_for_version
from backend.services.chunk_serving import chunk_serving_for_doc

logger = logging.getLogger(__name__)

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"
# INC-WEB-EMBED-413 REMEDIATION:任务自身工作已完结(裁决 = 不可回放,已把
# 权威源重建交接给既有 sync 路径);终态呈现,不入 _OPEN_STATUSES。
STATUS_REBUILD_REQUESTED = "rebuild_requested"

STAGE_PLAN = "plan"
STAGE_REPAIR = "repair"
STAGE_VERIFY = "verify"
STAGE_REBUILD_REQUEST = "rebuild_request"

_OPEN_STATUSES = (STATUS_PENDING, STATUS_RUNNING)


class RepairUnavailableError(RuntimeError):
    """向量库/嵌入模型不可用(端点层转 503 诚实降级,绝不伪造修复)。"""


def _now() -> datetime:
    return datetime.now(UTC)


async def _append_event(session: AsyncSession, task: DocumentRepairTask, event: str, **detail: Any) -> None:
    task.events = [*(task.events or []), {"at": _now().isoformat(), "event": event, **detail}]


async def _request_source_rebuild(
    session_factory: "async_sessionmaker[AsyncSession]",
    session: AsyncSession,
    task: DocumentRepairTask,
    *,
    reason: str,
    detail: str,
) -> None:
    """REBUILD_REQUIRED 裁决:经既有 sync_requests 交接缝请求权威源重建。

    冻结产品真(REMEDIATION):管理员只选「修复此知识 / 一键修复全部」,
    机制由系统裁决 —— 不可回放(超嵌入契约 / 持久副本缺失 / 无现行版本)
    的合格知识问题路由到既有 sync 源重建路径(``sync --reindex --source``,
    P1-E 全量生成重建,经 ``_enforce_char_limit`` 的已验收摄取路径),本进程
    **不复制**任何 connector/重建逻辑,不绕过执行面串行/去重/有界重试。
    去重键 = (source_id, kind):在途同键请求共用(already-running,幂等,
    不重复入队);异键(在途普通同步)互不阻塞。

    交接写库失败 → SyncRequestSubmitError 上抛(调用方按真实失败落账)。
    """
    from backend.services.sync_requests import submit_sync_request

    async with session_factory() as submit_session:
        submit = await submit_sync_request(
            submit_session, task.source_id, triggered_by="manual", kind="rebuild"
        )
    task.status = STATUS_REBUILD_REQUESTED
    task.stage = STAGE_REBUILD_REQUEST
    task.result = {
        "repair_mode": "source_rebuild_requested",
        "reason": reason,
        "detail": detail,
        "sync_request_id": submit.request_id,
        "sync_request_state": submit.state,
        "rebuild_path": "sync --reindex --source " + task.source_id,
    }
    task.error = None
    task.finished_at = _now()
    await _append_event(
        session,
        task,
        "rebuild_requested",
        reason=reason,
        sync_request_id=submit.request_id,
        state=submit.state,
    )


async def create_repair_task(
    session: AsyncSession,
    source_id: str,
    doc_source_id: str,
    *,
    requested_by: str | None,
    idempotency_key: str | None = None,
) -> tuple[DocumentRepairTask, bool]:
    """受理修复命令(幂等;返回 (task, created))。

    - 幂等键:同 (doc_source_id, idempotency_key) 已有任务 → 原任务;
    - 并发幂等:同文档存在未完结(pending/running)任务 → 原任务;
    - 否则新建 pending 任务(受理 ≠ 完成;执行由 execute_repair_task)。
    """
    if not doc_source_id.startswith(f"{source_id}/"):
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="后端无此记录")
    doc = (
        await session.execute(select(Document).where(Document.source_id == doc_source_id))
    ).scalar_one_or_none()
    if doc is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="后端无此记录")
    if idempotency_key:
        existing = (
            await session.execute(
                select(DocumentRepairTask)
                .where(
                    DocumentRepairTask.doc_source_id == doc_source_id,
                    DocumentRepairTask.idempotency_key == idempotency_key,
                )
                .order_by(DocumentRepairTask.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing, False
    open_task = (
        await session.execute(
            select(DocumentRepairTask)
            .where(
                DocumentRepairTask.doc_source_id == doc_source_id,
                DocumentRepairTask.status.in_(_OPEN_STATUSES),
            )
            .order_by(DocumentRepairTask.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if open_task is not None:
        return open_task, False
    task = DocumentRepairTask(
        source_id=source_id,
        doc_source_id=doc_source_id,
        status=STATUS_PENDING,
        stage=None,
        requested_by=requested_by,
        idempotency_key=idempotency_key,
        events=[{"at": _now().isoformat(), "event": "requested", "requested_by": requested_by}],
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task, True


def _chunks_iterable(collection: Any):
    return collection.iterator(return_properties=["source_id", "chunk_index"])


async def execute_repair_task(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    weaviate_client: Any,
    embedder: Any,
    class_name: str,
    task_id: UUID,
    max_chunk_chars: int | None = None,
) -> DocumentRepairTask:
    """执行修复任务(plan→repair→verify;任务行持久化进度/审计/结果)。

    向量库/嵌入模型不可用 → 任务置 failed + RepairUnavailableError
    (端点层预检同条件转 503;任务层绝不静默)。

    INC-WEB-EMBED-413 REMEDIATION(冻结产品真:系统自选恢复机制):
    - REPLAYABLE(现行版本 + 持久副本完整 + 待回放文本尽在嵌入字符契约内)
      → 持久副本回放(廉价路径,语义不变);
    - REBUILD_REQUIRED(无现行版本 / 无持久副本 / 权威集缺行 / 文本超
      ``max_chunk_chars``)→ 经既有 sync_requests 交接缝请求权威源重建
      (``sync --reindex --source``,P1-E 路径,_enforce_char_limit 生效),
      任务终态 rebuild_requested 如实呈现;绝不把注定 413 的载荷发给嵌入。
    - 真实上游失败(嵌入失败/写库失败/复验不一致/交接写库失败)→ 任务
      如实 failed,绝不伪造成功。
    """
    async with session_factory() as session:
        task = (
            await session.execute(
                select(DocumentRepairTask).where(DocumentRepairTask.id == task_id)
            )
        ).scalar_one_or_none()
        if task is None:
            raise RuntimeError(f"修复任务不存在: {task_id}")
        doc_source_id = task.doc_source_id
        try:
            task.status = STATUS_RUNNING
            task.stage = STAGE_PLAN
            await _append_event(session, task, "stage_plan_started")
            await session.commit()

            doc = (
                await session.execute(select(Document).where(Document.source_id == doc_source_id))
            ).scalar_one_or_none()
            version = None
            if doc is not None and doc.current_version_id is not None:
                version = (
                    await session.execute(
                        select(DocumentVersion).where(DocumentVersion.id == doc.current_version_id)
                    )
                ).scalar_one_or_none()
            if doc is None or version is None:
                # REMEDIATION:系统自选机制 —— 无现行版本 = REBUILD_REQUIRED
                # (既有 sync 源重建路径可为源内存在的文档重建),不再终态拒绝。
                await _request_source_rebuild(
                    session_factory,
                    session,
                    task,
                    reason="no_current_version",
                    detail="无现行版本记录,持久副本回放不可用 → 权威源重建交接",
                )
                await session.commit()
                await session.refresh(task)
                return task
            chunks = (
                (
                    await session.execute(
                        select(DocumentVersionChunk)
                        .where(DocumentVersionChunk.version_id == version.id)
                        .order_by(DocumentVersionChunk.chunk_index)
                    )
                )
                .scalars()
                .all()
            )
            if not chunks:
                await _request_source_rebuild(
                    session_factory,
                    session,
                    task,
                    reason="no_persisted_chunks",
                    detail="现行版本无持久 chunk 副本,回放不可用 → 权威源重建交接",
                )
                await session.commit()
                await session.refresh(task)
                return task

            # INT-C-01:修复回写目标 = 该文档现行版本的**在服代命名空间**
            # (与 GenerationBuilder.repair_documents / generation_builder 同款
            # 语义)。回写对象 UUID 与 generation props 均按现行版本代归属:
            # ordinal=0 → legacy 寻址;ordinal>0 → generation_uuid 命名空间。
            # plan/verify 投影同步按在服代过滤 —— legacy/旧代残留对象不计入
            # 在服集合,绝不把非在服 chunk 计为成功修复。
            gen_id = str(version.generation_id)
            gen_ordinal = int(version.generation_ordinal)
            target_uuids = chunk_uuids_for_version(doc_source_id, gen_id, gen_ordinal, len(chunks))

            total = version.chunk_count or len(chunks)
            projection = chunk_serving_for_doc(
                weaviate_client,
                class_name,
                doc_source_id,
                total,
                generation_ordinals=(gen_ordinal,),
            )
            await _append_event(
                session,
                task,
                "plan_completed",
                serving_chunks=projection.serving_chunks,
                total_chunks=projection.total_chunks,
                missing=len(projection.missing_indices),
            )
            task.stage = STAGE_REPAIR
            await session.commit()

            repaired_indices: list[int] = []
            if projection.missing_indices:
                chunk_by_index = {c.chunk_index: c for c in chunks}
                missing_rows = [
                    i for i in projection.missing_indices if i not in chunk_by_index
                ]
                oversize: list[tuple[int, int]] = []
                if max_chunk_chars and max_chunk_chars > 0:
                    oversize = [
                        (i, len(chunk_by_index[i].text))
                        for i in projection.missing_indices
                        if i in chunk_by_index and len(chunk_by_index[i].text) > max_chunk_chars
                    ]
                if missing_rows or oversize:
                    # REMEDIATION:REPLAYABLE 判定失败 = REBUILD_REQUIRED。
                    # 超契约文本送嵌入必被 413 拒绝(重试同败);权威集缺行
                    # 则该 index 无文本可回放。二者经既有 sync 源重建路径恢复,
                    # 绝不把注定失败的请求发给嵌入(零嵌入调用)。
                    if oversize:
                        idx0, len0 = oversize[0]
                        detail = (
                            f"持久 chunk 文本超嵌入字符契约(max_length={max_chunk_chars}):"
                            f" index {idx0} 为 {len0} 字符(共 {len(oversize)} 个超限)"
                        )
                        reason = "persisted_text_over_contract"
                    else:
                        detail = (
                            "权威 chunk 集缺行(在服缺失 index 无持久副本): "
                            f"{missing_rows[:10]}"
                        )
                        reason = "persisted_copy_incomplete"
                    await _request_source_rebuild(
                        session_factory,
                        session,
                        task,
                        reason=reason,
                        detail=detail,
                    )
                    await session.commit()
                    await session.refresh(task)
                    return task
                collection = weaviate_client.collections.get(class_name)
                vectors = embedder.embed(
                    [chunk_by_index[i].text for i in projection.missing_indices]
                )
                if not vectors or len(vectors) != len(projection.missing_indices):
                    raise RuntimeError("嵌入模型返回空/缺向量,拒绝写入(诚实失败)")
                for idx, vec in zip(projection.missing_indices, vectors):
                    chunk = chunk_by_index[idx]
                    # INT-C-02:持久 chunk props 为底(灌入时完整 properties
                    # 快照;channel_visibility 等资格/呈现字段以持久真值恢复,
                    # 不硬编码默认可见渠道、不因 overlay 跳过而丢失)。
                    props: dict[str, Any] = {
                        k: v for k, v in (chunk.props or {}).items() if v is not None
                    }
                    # 身份字段以账本真值为准(防持久副本 props 缺失/过期时写出
                    # 错身份对象;账本 = 权威)。
                    props.update(
                        {
                            "source_id": doc.source_id,
                            "source_type": doc.source_type,
                            "product": doc.product,
                            "title": doc.title,
                            "text": chunk.text,
                            "url": doc.url,
                            "chunk_index": chunk.chunk_index,
                            "content_hash": version.content_hash,
                            "branch": doc.branch or "",
                        }
                    )
                    # INT-C-01:在服代归属 props(generation_id 仅审计展示;
                    # generation_ordinal INT = 检索在服代过滤真值)。强制后置,
                    # 持久副本中的过期代归属不可覆盖现行代。
                    props["generation_id"] = gen_id
                    props["generation_ordinal"] = gen_ordinal
                    collection.data.insert(
                        properties=props,
                        # float32→python float(Weaviate REST JSON 序列化要求)
                        vector=[float(x) for x in vec],
                        uuid=target_uuids[idx],
                    )
                    repaired_indices.append(idx)
                await _append_event(
                    session, task, "repair_applied", repaired_indices=repaired_indices
                )
            else:
                await _append_event(session, task, "repair_noop_already_consistent")

            task.stage = STAGE_VERIFY
            await session.commit()
            # INT-C-01:复验口径同步在服代 —— 与 plan 同一过滤(现行版本代);
            # 一致判定只承认在服代命名空间内的完整覆盖。
            verify = chunk_serving_for_doc(
                weaviate_client,
                class_name,
                doc_source_id,
                total,
                generation_ordinals=(gen_ordinal,),
            )
            passed = verify.consistent
            task.result = {
                "version_seq": version.version_seq,
                "generation_id": gen_id,
                "generation_ordinal": gen_ordinal,
                "chunks_serving": verify.serving_chunks,
                "chunks_total": verify.total_chunks,
                "consistency": "passed" if passed else "failed",
                "repaired_indices": repaired_indices,
                "repair_mode": "persisted_chunk_replay",
            }
            task.status = STATUS_SUCCEEDED if passed else STATUS_FAILED
            task.finished_at = _now()
            await _append_event(
                session,
                task,
                "verify_completed",
                serving=f"{verify.serving_chunks}/{verify.total_chunks}",
                consistency="passed" if passed else "failed",
            )
            await session.commit()
            await session.refresh(task)
            return task
        except RepairUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001 - 单任务失败如实持久化
            await session.rollback()
            task = (
                await session.execute(
                    select(DocumentRepairTask).where(DocumentRepairTask.id == task_id)
                )
            ).scalar_one()
            task.status = STATUS_FAILED
            task.error = str(exc)[:500]
            task.finished_at = _now()
            await _append_event(session, task, "failed", error=str(exc)[:300])
            await session.commit()
            await session.refresh(task)
            logger.error("修复任务 %s 失败: %s", task_id, str(exc)[:200])
            return task


def ensure_repair_stack(request_state: Any, class_name: str) -> tuple[Any, Any]:
    """从 app.state 取修复依赖(weaviate client + embedder);缺失 → 503 诚实。

    后端进程内已有两实例(lifespan wiring);无实例(未配置向量库)= 修复
    不可用,必须显式 503,绝不伪造"已修复"。
    """
    from fastapi import HTTPException

    client = getattr(request_state, "weaviate_client", None)
    embedder = getattr(request_state, "embedder", None)
    if client is None or embedder is None:
        raise HTTPException(
            status_code=503,
            detail="向量库/嵌入模型不可用,修复命令暂不能执行(诚实降级,不伪装)",
        )
    return client, embedder
