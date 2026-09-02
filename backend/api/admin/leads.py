"""销售线索 Admin API(/api/admin/leads)。

- GET /leads        列表(状态/联系方式/关键词过滤;列表不回联系方式原文)
- GET /leads/{id}   详情(含联系方式原文,授权 Admin/Editor/Viewer 可见)
- GET /leads/{id}/thread  原始会话线程(按 session_id 聚合,无则回退锚点轮次)
- POST /leads/{id}/handoff  手动移交销售(admin/editor;Contact Captured ≠ Sales Contacted,
  本接口只表达「人已接管跟进」,不触发任何自动通知)

隐私边界(HARD):联系方式原文只经此只读管理面出库;列表视图仅回
contact_masked,缩小 PII 暴露面。
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import Conversation, SalesLead

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/leads", tags=["销售线索"])
ViewerDep = Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))]
EditorDep = Annotated[CurrentUser, Depends(require_role("admin", "editor"))]


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _serialize(lead: SalesLead, *, include_contact: bool) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": str(lead.id),
        "session_id": lead.session_id,
        "status": lead.status,
        "contact_type": lead.contact_type,
        "contact_masked": lead.contact_masked,
        "has_contact": bool(lead.contact_value),
        "contact_captured_at": _iso(lead.contact_captured_at),
        "name": lead.name,
        "company": lead.company,
        "region": lead.region,
        "product_interest": lead.product_interest,
        "quantity": lead.quantity,
        "use_case": lead.use_case,
        "purchase_intent": lead.purchase_intent,
        "timeline": lead.timeline,
        "ai_summary": lead.ai_summary,
        "prompt_count": lead.prompt_count,
        "last_prompted_at": _iso(lead.last_prompted_at),
        "source_conversation_id": str(lead.source_conversation_id),
        "last_conversation_id": str(lead.last_conversation_id),
        "channel": lead.channel,
        "language": lead.language,
        "country": lead.country,
        "handoff_at": _iso(lead.handoff_at),
        "handoff_by": lead.handoff_by,
        "created_at": _iso(lead.created_at),
        "updated_at": _iso(lead.updated_at),
    }
    if include_contact:
        data["contact_value"] = lead.contact_value
    return data


@router.get("")
async def list_leads(
    _: ViewerDep,
    request: Request,
    status: str | None = Query(
        default=None, pattern="^(potential|qualified|contact_captured|handed_off)$"
    ),
    contact: str | None = Query(default=None, pattern="^(with|without)$"),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """线索列表(创建时间倒序)。列表视图不回联系方式原文(只回 masked)。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        conds = []
        if status:
            conds.append(SalesLead.status == status)
        if contact == "with":
            conds.append(SalesLead.contact_value.is_not(None))
        elif contact == "without":
            conds.append(SalesLead.contact_value.is_(None))
        if q:
            like = f"%{q}%"
            conds.append(
                or_(
                    SalesLead.company.ilike(like),
                    SalesLead.name.ilike(like),
                    SalesLead.product_interest.ilike(like),
                    SalesLead.ai_summary.ilike(like),
                    SalesLead.contact_masked.ilike(like),
                )
            )
        total_q = select(func.count()).select_from(SalesLead).where(*conds)
        total = (await session.execute(total_q)).scalar() or 0

        q_leds = (
            select(SalesLead)
            .where(*conds)
            .order_by(SalesLead.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        rows = (await session.execute(q_leds)).scalars().all()

    return {
        "leads": [_serialize(r, include_contact=False) for r in rows],
        "total": total,
    }


async def _get_lead_or_404(session: AsyncSession, lead_id: str) -> SalesLead:
    try:
        lead_uuid = uuid.UUID(lead_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="线索不存在")
    lead = await session.get(SalesLead, lead_uuid)
    if lead is None:
        raise HTTPException(status_code=404, detail="线索不存在")
    return lead


@router.get("/{lead_id}")
async def get_lead(
    _: ViewerDep,
    request: Request,
    lead_id: str,
) -> dict[str, Any]:
    """线索详情(含联系方式原文——销售跟进必需,仅授权角色可达)。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        lead = await _get_lead_or_404(session, lead_id)
        return _serialize(lead, include_contact=True)


@router.get("/{lead_id}/thread")
async def get_lead_thread(
    _: ViewerDep,
    request: Request,
    lead_id: str,
) -> dict[str, Any]:
    """原始会话线程:优先按 session_id 聚合全部轮次;无 session 的旧线索回退
    锚点轮次(创建轮 + 最近轮)。时间正序。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        lead = await _get_lead_or_404(session, lead_id)
        if lead.session_id:
            rows = (
                (
                    await session.execute(
                        select(Conversation)
                        .where(Conversation.session_id == lead.session_id)
                        .order_by(Conversation.created_at.asc())
                    )
                )
                .scalars()
                .all()
            )
        else:
            rows = (
                (
                    await session.execute(
                        select(Conversation)
                        .where(
                            Conversation.id.in_(
                                [lead.source_conversation_id, lead.last_conversation_id]
                            )
                        )
                        .order_by(Conversation.created_at.asc())
                    )
                )
                .scalars()
                .all()
            )

    return {
        "session_id": lead.session_id,
        "messages": [
            {
                "conversation_id": str(c.id),
                "role": "user",
                "question": c.question,
                "answer": c.answer,
                "intent_tag": c.intent_tag,
                "channel": c.channel,
                "created_at": _iso(c.created_at),
            }
            for c in rows
        ],
    }


@router.post("/{lead_id}/handoff")
async def handoff_lead(
    user: EditorDep,
    request: Request,
    lead_id: str,
) -> dict[str, Any]:
    """手动移交销售(admin/editor)。幂等:已移交的线索原样返回。

    契约 §8:此动作只表达「人工已接管」,不承诺、不触发任何自动联系。
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        lead = await _get_lead_or_404(session, lead_id)
        if lead.status != "handed_off":
            lead.status = "handed_off"
            lead.handoff_at = datetime.now(UTC)
            lead.handoff_by = user.email
            await session.commit()
            # commit 过期了 onupdate 列(updated_at),异步下须显式重载
            await session.refresh(lead)
        return _serialize(lead, include_contact=True)
