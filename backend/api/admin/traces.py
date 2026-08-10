"""trace 查询端点。"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import Trace

traces_router = APIRouter(prefix="/conversations", tags=["trace"])
ViewerDep = Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))]


@traces_router.get("/{conversation_id}/traces")
async def list_traces(
    conversation_id: UUID,
    _: ViewerDep,
    request: Request,
) -> list[dict[str, Any]]:
    """返回该对话所有 trace(按 turn_index 排序)。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        rows = await session.execute(
            select(Trace)
            .where(Trace.conversation_id == conversation_id)
            .order_by(Trace.turn_index)
        )
        traces = rows.scalars().all()
    return [
        {
            "id": str(t.id),
            "conversation_id": str(t.conversation_id),
            "prev_trace_id": str(t.prev_trace_id) if t.prev_trace_id else None,
            "turn_index": t.turn_index,
            "type": t.type,
            "stages": t.stages,
            "total_ms": t.total_ms,
            "intent": t.intent,
            "confidence": t.confidence,
            "config_snapshot": t.config_snapshot,
            "created_at": t.created_at.isoformat() if t.created_at else "",
        }
        for t in traces
    ]
