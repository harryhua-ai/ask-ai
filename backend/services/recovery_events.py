"""v1.6.3 Track C(U-10):逐文档自动恢复事件账本与权威计数。

冻结语义(DS-P3-06):恢复注记必须**源自持久化权威恢复事件,禁止前端
计数器**。事件由同步执行面的自动恢复路径(无变更跳过分支的一致性缺口
自愈,``GenerationBuilder.repair_documents`` refill 集合)逐文档写入:

- outcome='succeeded':本次自动恢复使文档回到在服;
- outcome='failed':自动恢复尝试后文档仍未在服(注记「未成功」口径)。

恢复注记计数 = 本表 outcome='failed' 权威计数(逐文档),UI 仅呈现。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import DocumentRecoveryEvent

OUTCOME_SUCCEEDED = "succeeded"
OUTCOME_FAILED = "failed"


async def record_recovery_events(
    session_factory: Any,
    source_id: str,
    *,
    repaired: list[str] | set[str],
    unrepairable: list[str] | set[str],
    sync_run_id: int | None = None,
    detail: dict[str, Any] | None = None,
) -> int:
    """写入一次自动恢复尝试的逐文档事件(同步执行面唯一写入口)。

    幂等锚:每次尝试一条事件(事件 = 尝试事实,重复尝试产生新事件;
    去重键 = (sync_run_id, doc_source_id) 已存在则跳过,防同一 run 重放)。
    返回写入事件数(0 = 全部已记录)。
    """
    now = datetime.now(UTC)
    written = 0
    async with session_factory() as session:
        existing: set[tuple[int | None, str]] = set()
        docs = [*repaired, *unrepairable]
        if sync_run_id is not None and docs:
            rows = await session.execute(
                select(DocumentRecoveryEvent.doc_source_id).where(
                    DocumentRecoveryEvent.sync_run_id == sync_run_id,
                    DocumentRecoveryEvent.doc_source_id.in_(docs),
                )
            )
            existing = {(sync_run_id, r[0]) for r in rows.all()}
        for sid in repaired:
            if (sync_run_id, sid) in existing:
                continue
            session.add(
                DocumentRecoveryEvent(
                    source_id=source_id,
                    doc_source_id=sid,
                    outcome=OUTCOME_SUCCEEDED,
                    sync_run_id=sync_run_id,
                    detail=detail,
                    created_at=now,
                )
            )
            written += 1
        for sid in unrepairable:
            if (sync_run_id, sid) in existing:
                continue
            session.add(
                DocumentRecoveryEvent(
                    source_id=source_id,
                    doc_source_id=sid,
                    outcome=OUTCOME_FAILED,
                    sync_run_id=sync_run_id,
                    detail=detail,
                    created_at=now,
                )
            )
            written += 1
        if written:
            await session.commit()
    return written


async def recovery_counts(
    session: AsyncSession, doc_source_id: str
) -> tuple[int, int]:
    """逐文档恢复事件权威计数:(尝试未成功次数, 尝试成功次数)。"""
    rows = await session.execute(
        select(DocumentRecoveryEvent.outcome, func.count())
        .where(DocumentRecoveryEvent.doc_source_id == doc_source_id)
        .group_by(DocumentRecoveryEvent.outcome)
    )
    counts = {row[0]: int(row[1]) for row in rows.all()}
    return counts.get(OUTCOME_FAILED, 0), counts.get(OUTCOME_SUCCEEDED, 0)
