"""同步日志查询端点（只读）。"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.admin.schemas import SyncLogOut
from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import SyncLog

router = APIRouter(prefix="/sync-logs", tags=["同步监控"])
ViewerDep = Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))]


@router.get("")
async def list_sync_logs(
    _: ViewerDep,
    request: Request,
    source_id: str | None = Query(default=None),
    status: str | None = Query(default=None, pattern="^(success|failed|partial)$"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """查询同步日志（viewer+ 可访问），支持按 source_id / status 过滤 + 分页。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        q = select(SyncLog)
        count_q = select(func.count()).select_from(SyncLog)
        if source_id:
            q = q.where(SyncLog.source_id == source_id)
            count_q = count_q.where(SyncLog.source_id == source_id)
        if status:
            q = q.where(SyncLog.status == status)
            count_q = count_q.where(SyncLog.status == status)
        total = (await session.execute(count_q)).scalar() or 0
        result = await session.execute(
            q.order_by(SyncLog.started_at.desc()).offset((page - 1) * size).limit(size)
        )
        logs = result.scalars().all()

    items = [
        SyncLogOut(
            id=str(log.id),
            source_id=log.source_id,
            source_type=log.source_type,
            status=log.status,
            started_at=log.started_at.isoformat() if log.started_at else "",
            finished_at=log.finished_at.isoformat() if log.finished_at else None,
            duration_ms=log.duration_ms,
            items_new=log.items_new,
            items_updated=log.items_updated,
            items_deleted=log.items_deleted,
            error_detail=log.error_detail,
            triggered_by=log.triggered_by,
        )
        for log in logs
    ]
    return {"items": items, "total": total, "page": page, "size": size}
