"""对话审查端点（多维过滤 + 分页 + 详情）。"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import Conversation, SourceClick, Trace
from backend.services.intent_tagger import tag_batch, tag_single

router = APIRouter(prefix="/conversations", tags=["对话审查"])
ViewerDep = Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))]
EditorDep = Annotated[CurrentUser, Depends(require_role("admin", "editor"))]


@router.get("")
async def list_conversations(
    _: ViewerDep,
    request: Request,
    channel: str | None = Query(default=None),
    is_answered: bool | None = Query(default=None),
    feedback: str | None = Query(default=None, pattern="^(up|down)$"),
    intent_tag: str | None = Query(default=None),
    q: str | None = Query(default=None, description="全文搜索 question/answer"),
    date_from: str | None = Query(default=None, description="ISO 日期，如 2026-01-01"),
    date_to: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """查询对话列表（viewer+ 可访问），支持 channel / is_answered / feedback /
    intent_tag / q(全文搜索) / date_from / date_to 多维过滤 + 分页。
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        stmt = select(Conversation)
        count_q = select(func.count()).select_from(Conversation)
        if channel:
            stmt = stmt.where(Conversation.channel == channel)
            count_q = count_q.where(Conversation.channel == channel)
        if is_answered is not None:
            stmt = stmt.where(Conversation.is_answered == is_answered)
            count_q = count_q.where(Conversation.is_answered == is_answered)
        if feedback:
            stmt = stmt.where(Conversation.feedback == feedback)
            count_q = count_q.where(Conversation.feedback == feedback)
        if intent_tag:
            stmt = stmt.where(Conversation.intent_tag == intent_tag)
            count_q = count_q.where(Conversation.intent_tag == intent_tag)
        if q:
            pattern = f"%{q}%"
            cond = Conversation.question.ilike(pattern) | Conversation.answer.ilike(pattern)
            stmt = stmt.where(cond)
            count_q = count_q.where(cond)
        if date_from:
            stmt = stmt.where(Conversation.created_at >= date_from)
            count_q = count_q.where(Conversation.created_at >= date_from)
        if date_to:
            stmt = stmt.where(Conversation.created_at <= date_to)
            count_q = count_q.where(Conversation.created_at <= date_to)

        total = (await session.execute(count_q)).scalar() or 0
        result = await session.execute(
            stmt.order_by(Conversation.created_at.desc()).offset((page - 1) * size).limit(size)
        )
        convs = result.scalars().all()

        # 批量获取 trace 摘要(每条对话最新一条 trace 的 stages)
        conv_ids = [c.id for c in convs]
        trace_map: dict = {}
        if conv_ids:
            trace_q = (
                select(Trace)
                .where(Trace.conversation_id.in_(conv_ids))
                .order_by(Trace.turn_index)
            )
            trace_rows = (await session.execute(trace_q)).scalars().all()
            for t in trace_rows:
                if t.conversation_id not in trace_map:
                    trace_map[t.conversation_id] = {
                        "type": t.type,
                        "stages": t.stages or {},
                        "total_ms": t.total_ms,
                    }

    items = [
        {
            "id": str(c.id),
            "question": c.question,
            "answer": c.answer,
            "channel": c.channel,
            "language": c.language,
            "sources": list(c.sources or []),
            "is_answered": c.is_answered,
            "feedback": c.feedback,
            "response_time_ms": c.response_time_ms,
            "created_at": c.created_at.isoformat() if c.created_at else "",
            "intent_tag": c.intent_tag,
            "trace_summary": trace_map.get(c.id),
        }
        for c in convs
    ]
    return {"items": items, "total": total, "page": page, "size": size}


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: UUID,
    _: ViewerDep,
    request: Request,
) -> dict[str, Any]:
    """查询单条对话详情（含来源点击记录）。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        conv = await session.execute(select(Conversation).where(Conversation.id == conversation_id))
        conv = conv.scalar_one_or_none()
        if conv is None:
            raise HTTPException(status_code=404, detail="对话不存在")
        clicks_result = await session.execute(
            select(SourceClick).where(SourceClick.conversation_id == conversation_id)
        )
        clicks = clicks_result.scalars().all()
    return {
        "id": str(conv.id),
        "question": conv.question,
        "answer": conv.answer,
        "channel": conv.channel,
        "language": conv.language,
        "sources": conv.sources or [],
        "is_answered": conv.is_answered,
        "feedback": conv.feedback,
        "response_time_ms": conv.response_time_ms,
        "created_at": conv.created_at.isoformat() if conv.created_at else "",
        "intent_tag": conv.intent_tag,
        "clicks": [
            {
                "url": c.source_url,
                "type": c.source_type,
                "product": c.product,
                "clicked_at": c.clicked_at.isoformat() if c.clicked_at else "",
            }
            for c in clicks
        ],
    }


@router.post("/batch-tag")
async def batch_tag_conversations(
    _: EditorDep,
    request: Request,
    batch_size: int = Query(default=50, ge=1, le=500),
) -> dict:
    """批量标注未标注的对话（admin/editor）。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    llm = request.app.state.llm
    count = await tag_batch(factory, llm, batch_size)
    return {"tagged_count": count}


@router.post("/{conversation_id}/tag")
async def tag_conversation(
    conversation_id: UUID,
    _: EditorDep,
    request: Request,
) -> dict[str, str]:
    """手动标注单个对话的 intent（admin/editor）。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    llm = request.app.state.llm
    async with factory() as session:
        conv = await session.execute(select(Conversation).where(Conversation.id == conversation_id))
        conv = conv.scalar_one_or_none()
        if conv is None:
            raise HTTPException(status_code=404, detail="对话不存在")
    tag = await tag_single(str(conversation_id), conv.question, llm)
    async with factory() as session:
        await session.execute(
            update(Conversation).where(Conversation.id == conversation_id).values(intent_tag=tag)
        )
        await session.commit()
    return {"intent_tag": tag}
