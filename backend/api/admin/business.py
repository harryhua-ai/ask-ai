"""业务概览聚合端点。"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import BusinessSignal, Conversation, QuestionCluster

router = APIRouter(prefix="/business", tags=["业务概览"])
ViewerDep = Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))]


@router.get("/overview")
async def business_overview(
    _: ViewerDep,
    request: Request,
    range: str = Query(default="7d"),
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
) -> dict[str, Any]:
    """返回业务概览:服务总览、销售线索、场景应用、产品需求、热门问题、地域。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    days = {"today": 1, "7d": 7, "30d": 30}.get(range, 7)
    end = datetime.now(UTC)
    start = end - timedelta(days=days)

    if date_from:
        start = datetime.fromisoformat(date_from).replace(tzinfo=UTC)
    if date_to:
        end = datetime.fromisoformat(date_to).replace(tzinfo=UTC)

    async with factory() as session:
        # 服务总览
        total_q = select(func.count()).select_from(Conversation).where(
            Conversation.created_at >= start, Conversation.created_at <= end
        )
        total = (await session.execute(total_q)).scalar() or 0

        # 意图分布
        intent_q = (
            select(Conversation.intent_tag, func.count())
            .where(Conversation.created_at >= start, Conversation.created_at <= end)
            .group_by(Conversation.intent_tag)
        )
        intent_rows = (await session.execute(intent_q)).all()
        _raw_intent = {row[0] or "unknown": row[1] for row in intent_rows}
        # 补全四意图键(前端契约固定 commercial/product/support/off_topic,缺失默认 0)
        intent_dist = {
            k: _raw_intent.get(k, 0)
            for k in ("commercial", "product", "support", "off_topic")
        }

        # 北极星:commercial 且 is_answered(占位,购买信号待业务方确认)
        north_star_q = select(func.count()).select_from(Conversation).where(
            Conversation.created_at >= start,
            Conversation.created_at <= end,
            Conversation.intent_tag == "commercial",
            Conversation.is_answered.is_(True),
        )
        north_star = (await session.execute(north_star_q)).scalar() or 0

        # 满意度(feedback up/down)
        up_q = select(func.count()).select_from(Conversation).where(
            Conversation.created_at >= start,
            Conversation.created_at <= end,
            Conversation.feedback == "up",
        )
        up_count = (await session.execute(up_q)).scalar() or 0
        down_q = select(func.count()).select_from(Conversation).where(
            Conversation.created_at >= start,
            Conversation.created_at <= end,
            Conversation.feedback == "down",
        )
        down_count = (await session.execute(down_q)).scalar() or 0
        feedback_total = up_count + down_count
        satisfaction = (
            round(up_count / feedback_total * 100, 1) if feedback_total else None
        )

        # 销售线索(commercial 对话数)
        commercial_count = intent_dist.get("commercial", 0)

        # 业务信号(场景/需求)
        signal_q = select(BusinessSignal).where(
            BusinessSignal.period_start >= start,
            BusinessSignal.period_end <= end,
        )
        signals = (await session.execute(signal_q)).scalars().all()
        scenes = [
            {"label": s.label, "count": s.count, "pct": s.pct}
            for s in signals
            if s.type == "scene"
        ]
        requirements = [
            {"label": s.label, "count": s.count, "pct": s.pct}
            for s in signals
            if s.type == "requirement"
        ]

        # 热门问题(复用 QuestionCluster)
        top_q = (
            select(QuestionCluster)
            .where(QuestionCluster.cluster_type == "top")
            .order_by(QuestionCluster.question_count.desc())
            .limit(10)
        )
        top_questions = (await session.execute(top_q)).scalars().all()
        top_q_list = [
            {
                "id": str(q.id),
                "question": q.representative_question,
                "count": q.question_count,
            }
            for q in top_questions
        ]

    return {
        "service": {
            "total": total,
            "intent_dist": intent_dist,
            "north_star": north_star,
            "satisfaction": satisfaction,
            "up_count": up_count,
            "down_count": down_count,
        },
        "leads": {
            "valid": north_star,
            "potential": commercial_count,
            "hot_products": [],
        },
        "scenes": scenes,
        "requirements": requirements,
        "top_questions": top_q_list,
        "geo": [],
        "geo_note": "地域字段待接入",
        "timeseries": [],
    }
