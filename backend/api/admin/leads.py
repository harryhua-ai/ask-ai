"""销售线索 Admin API(/api/admin/leads)。

- GET /leads        列表(状态/联系方式/关键词过滤;列表不回联系方式原文,
                    也不回作废理由自由文本 —— R2 PII 投影最小化)
- GET /leads/{id}   详情(含联系方式原文与完整作废审计理由,授权角色可见)
- GET /leads/{id}/thread  原始会话线程(按 session_id 聚合,无则回退锚点轮次)
- POST /leads/{id}/handoff  手动移交销售(admin/editor;Contact Captured ≠ Sales Contacted,
  本接口只表达「人已接管跟进」,不触发任何自动通知)
- POST /leads/{id}/void-contact  错误联系方式作废(仅 admin;明确确认 + 理由;
  原子首写审计(条件 CAS,并发不可覆盖);contact_value 原文永不擦除,#124)

生效语义(#124 R2):raw status 只升不降、不可改写(历史审计);每行另暴露
effective_status —— 已作废联系方式不再宣称「有效已留联」:仅靠联系方式抵达
contact_captured 的行生效口径回落 potential,独立成立的 qualified/handed_off
(购买意图/人工移交)不被盲目降级。列表/筛选/运营计数一律按生效口径。

隐私边界(HARD):联系方式原文与作废理由自由文本只经此只读管理面详情出库;
列表视图仅回 contact_masked 与作废归因(操作人/时间),缩小 PII 暴露面。
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import Conversation, SalesLead
from backend.services.lead_service import void_lead_contact_atomic

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/leads", tags=["销售线索"])
ViewerDep = Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))]
EditorDep = Annotated[CurrentUser, Depends(require_role("admin", "editor"))]
# #124:作废是不可逆的人工处置(改变运营口径),比 handoff 更敏感 → 仅 admin
AdminDep = Annotated[CurrentUser, Depends(require_role("admin"))]


class VoidContactRequest(BaseModel):
    """作废请求体:显式确认 + 必填理由(审计;AC1「明确确认后」)。"""

    confirm: bool
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("confirm")
    @classmethod
    def _must_explicitly_confirm(cls, v: bool) -> bool:
        if v is not True:
            raise ValueError("必须显式 confirm=true 才能作废")
        return v

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("作废理由不能为空")
        return v


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _effective_status(lead: SalesLead) -> str:
    """生效状态(#124 R2,AC2):运营视图/筛选/计数的口径。

    raw status 只升不降且不可改写(不可变历史);作废仅使「资格只由该联系
    方式支撑」的 contact_captured 行不再宣称有效已留联 → 生效回落 potential
    (线索存在、意图未确证)。独立成立的 qualified / handed_off(购买意图、
    人工移交是独立历史事实)不因作废联系方式被盲目降级。
    """
    if lead.contact_voided and lead.status == "contact_captured":
        return "potential"
    return lead.status


def _serialize(lead: SalesLead, *, include_contact: bool) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": str(lead.id),
        "session_id": lead.session_id,
        "status": lead.status,
        # #124 R2:生效状态(运营口径);status 为不可变历史
        "effective_status": _effective_status(lead),
        "contact_type": lead.contact_type,
        "contact_masked": lead.contact_masked,
        # #124:has_contact = 有效联系方式在档(作废的联系方式不算有效)
        "has_contact": bool(lead.contact_value) and not lead.contact_voided,
        "contact_captured_at": _iso(lead.contact_captured_at),
        # #124:作废归因(列表/详情均可见,呈现已作废徽章;原文仍只在详情)。
        # R2 PII:理由是自由文本,只在详情(授权视图)回传,列表投影不含。
        "contact_voided": bool(lead.contact_voided),
        "contact_voided_at": _iso(lead.contact_voided_at),
        "contact_voided_by": lead.contact_voided_by,
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
        # 详情含原文:作废后仍返回(必要历史审计,AC3 可追溯),但仅授权角色可达
        data["contact_value"] = lead.contact_value
        # R2 AC3:完整作废理由属授权详情视图(自由文本,列表投影最小化)
        data["contact_voided_reason"] = lead.contact_voided_reason
    return data


@router.get("")
async def list_leads(
    _: ViewerDep,
    request: Request,
    status: str | None = Query(
        default=None, pattern="^(potential|qualified|contact_captured|handed_off)$"
    ),
    # #124:with = 有效联系方式在档(排除已作废);voided = 仅已作废(审计视图);
    # without = 从未捕获联系方式。三态互斥,完整划分。
    contact: str | None = Query(default=None, pattern="^(with|without|voided)$"),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    """线索列表(创建时间倒序)。列表视图不回联系方式原文/作废理由(PII 投影)。

    status 筛选按**生效状态**(#124 R2):status=contact_captured 排除已作废行
    (不再宣称有效已留联);作废的 contact_captured 行按生效口径出现在
    status=potential;raw 历史见每行 status 字段或 contact=voided 审计视图。
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        conds = []
        if status == "contact_captured":
            # 生效口径:有效已留联(作废的不算,#124 R2)
            conds.append(SalesLead.status == "contact_captured")
            conds.append(SalesLead.contact_voided.is_(False))
        elif status == "potential":
            conds.append(
                or_(
                    SalesLead.status == "potential",
                    and_(
                        SalesLead.status == "contact_captured",
                        SalesLead.contact_voided.is_(True),
                    ),
                )
            )
        elif status:
            conds.append(SalesLead.status == status)
        if contact == "with":
            # 有效联系方式 = 已捕获且未被作废(#124 AC2:误报不再冒充可联系线索)
            conds.append(SalesLead.contact_value.is_not(None))
            conds.append(SalesLead.contact_voided.is_(False))
        elif contact == "without":
            conds.append(SalesLead.contact_value.is_(None))
        elif contact == "voided":
            conds.append(SalesLead.contact_voided.is_(True))
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


@router.post("/{lead_id}/void-contact")
async def void_lead_contact(
    user: AdminDep,
    request: Request,
    lead_id: str,
    body: VoidContactRequest,
) -> dict[str, Any]:
    """错误联系方式作废/标记无效(仅 admin;#124)。

    - 明确确认(confirm=true)+ 必填理由,保存操作人/时间/理由(AC1 审计);
    - 原子首写:条件 CAS(UPDATE ... WHERE NOT contact_voided,见
      lead_service.void_lead_contact_atomic)——同行并发/重复提交下恰好一个
      事务首写成功,首写审计不可被后写者覆盖(AC1 R2);
    - 目标性:仅按主键改写本行,绝不误修改其它线索记录(AC1);
    - contact_value/contact_masked 原文与捕获时间永不擦除(必要历史审计,
      AC3 可追溯;禁止不可恢复擦除);状态生命周期不动(不改变 G001 资格)。
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        lead = await _get_lead_or_404(session, lead_id)
        if not lead.contact_value:
            raise HTTPException(status_code=409, detail="该线索没有已捕获的联系方式可作废")
        won = await void_lead_contact_atomic(
            session, lead.id, by=user.email, reason=body.reason.strip()
        )
        # won:首写审计落库;not won(并发已首写/幂等重复提交):空提交仅结束
        # 本事务快照,随后统一重载——返回的一律是首写者审计(现状)。
        await session.commit()
        await session.refresh(lead)
        logger.info(
            "lead contact voided: lead=%s won_first_write=%s by=%s",
            lead.id,
            won,
            user.email,
        )
    return _serialize(lead, include_contact=True)
