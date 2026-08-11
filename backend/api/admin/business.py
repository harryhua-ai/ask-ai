"""业务概览聚合端点。"""

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import BusinessSignal, Conversation, QuestionCluster
from backend.services.signal_extractor import SignalExtractor

router = APIRouter(prefix="/business", tags=["业务概览"])
ViewerDep = Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))]
EditorDep = Annotated[CurrentUser, Depends(require_role("admin", "editor"))]

# 已知 e2e 测试问题前缀(精确匹配)
_TEST_QUESTION_PREFIXES = (
    "What is NE301",
    "What is the price of NE301",
    "What are NE503",
    "What is the recommended deployment",
    "How to purchase NE301",
    "How to purchase CamThink",
    "How to become CamThink",
    "NE101 price",
    "NE301 troubleshooting",
    "Can you write me a Python",
    "What's the weather",
    "提供完整命令",
)


def _is_test_question(question: str) -> bool:
    return question.strip().startswith(_TEST_QUESTION_PREFIXES)


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
    days = {"today": 1, "7d": 7, "30d": 30, "90d": 90}.get(range, 7)
    end = datetime.now(UTC)
    start = end - timedelta(days=days)

    if date_from:
        start = datetime.fromisoformat(date_from).replace(tzinfo=UTC)
    if date_to:
        end = datetime.fromisoformat(date_to).replace(tzinfo=UTC)

    async with factory() as session:
        # 服务总览
        total_q = (
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.created_at >= start, Conversation.created_at <= end)
        )
        total = (await session.execute(total_q)).scalar() or 0

        # 意图分布(含 unknown 兜底)
        intent_q = (
            select(Conversation.intent_tag, func.count())
            .where(Conversation.created_at >= start, Conversation.created_at <= end)
            .group_by(Conversation.intent_tag)
        )
        intent_rows = (await session.execute(intent_q)).all()
        _raw_intent: dict[str, int] = defaultdict(int)
        for row in intent_rows:
            tag = (
                row[0] if row[0] in ("commercial", "product", "support", "off_topic") else "unknown"
            )
            _raw_intent[tag] += row[1]
        intent_dist = {
            k: _raw_intent.get(k, 0) for k in ("commercial", "product", "support", "off_topic")
        }
        unknown_count = _raw_intent.get("unknown", 0)

        # 北极星:commercial 且 is_answered
        north_star_q = (
            select(func.count())
            .select_from(Conversation)
            .where(
                Conversation.created_at >= start,
                Conversation.created_at <= end,
                Conversation.intent_tag == "commercial",
                Conversation.is_answered.is_(True),
            )
        )
        north_star = (await session.execute(north_star_q)).scalar() or 0

        # 满意度(feedback up/down)
        up_q = (
            select(func.count())
            .select_from(Conversation)
            .where(
                Conversation.created_at >= start,
                Conversation.created_at <= end,
                Conversation.feedback == "up",
            )
        )
        up_count = (await session.execute(up_q)).scalar() or 0
        down_q = (
            select(func.count())
            .select_from(Conversation)
            .where(
                Conversation.created_at >= start,
                Conversation.created_at <= end,
                Conversation.feedback == "down",
            )
        )
        down_count = (await session.execute(down_q)).scalar() or 0
        feedback_total = up_count + down_count
        satisfaction = round(up_count / feedback_total * 100, 1) if feedback_total else None

        commercial_count = intent_dist.get("commercial", 0)

        # 业务信号(场景/需求)
        signal_q = select(BusinessSignal).where(
            BusinessSignal.period_start >= start,
            BusinessSignal.period_end <= end,
        )
        signals = (await session.execute(signal_q)).scalars().all()
        scenes = [
            {"label": s.label, "count": s.count, "pct": s.pct} for s in signals if s.type == "scene"
        ]
        requirements = [
            {"label": s.label, "count": s.count, "pct": s.pct}
            for s in signals
            if s.type == "requirement"
        ]

        # 热门问题(过滤测试数据)
        top_q = (
            select(QuestionCluster)
            .where(QuestionCluster.cluster_type == "top")
            .order_by(QuestionCluster.question_count.desc())
            .limit(20)
        )
        top_clusters = (await session.execute(top_q)).scalars().all()
        top_q_list = [
            {
                "id": str(q.id),
                "question": q.representative_question,
                "count": q.question_count,
            }
            for q in top_clusters
            if not _is_test_question(q.representative_question or "")
        ][:10]

        # 热门产品:从 commercial 对话的 sources 中提取 product 字段聚合
        product_q = select(Conversation.sources).where(
            Conversation.created_at >= start,
            Conversation.created_at <= end,
            Conversation.intent_tag == "commercial",
            Conversation.is_answered.is_(True),
        )
        product_rows = (await session.execute(product_q)).all()
        product_count: dict[str, int] = defaultdict(int)
        for row in product_rows:
            sources = row[0] if isinstance(row[0], list) else []
            for src in sources:
                if isinstance(src, dict):
                    p = src.get("product")
                    if p:
                        product_count[p] += 1
        hot_products = sorted(
            [{"name": k, "count": v} for k, v in product_count.items()],
            key=lambda x: -x["count"],
        )[:5]

        # 时间序列(按天聚合对话量)
        daily_q = (
            select(
                func.date_trunc("day", Conversation.created_at).label("day"),
                func.count().label("cnt"),
                Conversation.intent_tag,
            )
            .where(Conversation.created_at >= start, Conversation.created_at <= end)
            .group_by("day", Conversation.intent_tag)
        )
        daily_rows = (await session.execute(daily_q)).all()
        daily_map: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "date": "",
                "total": 0,
                "commercial": 0,
                "product": 0,
                "support": 0,
                "off_topic": 0,
            }
        )
        for row in daily_rows:
            day_str = row.day.strftime("%m-%d") if row.day else ""
            entry = daily_map[day_str]
            entry["date"] = day_str
            entry["total"] += row.cnt
            intent_key = (
                row.intent_tag
                if row.intent_tag in ("commercial", "product", "support", "off_topic")
                else "product"
            )
            entry[intent_key] += row.cnt
        timeseries = sorted(daily_map.values(), key=lambda x: x["date"])

        # 地域分布(从 country 字段聚合)
        geo_q = (
            select(
                Conversation.country,
                func.count().label("cnt"),
            )
            .where(
                Conversation.created_at >= start,
                Conversation.created_at <= end,
                Conversation.country.is_not(None),
            )
            .group_by(Conversation.country)
            .order_by(func.count().desc())
            .limit(10)
        )
        geo_rows = (await session.execute(geo_q)).all()
        geo_total = sum(r.cnt for r in geo_rows) or 1
        geo = [
            {
                "name": row.country,
                "count": row.cnt,
                "pct": round(row.cnt / geo_total * 100, 1),
            }
            for row in geo_rows
            if row.country
        ]
        geo_note = "地域分布" if geo else "暂无地域数据(新对话将自动捕获)"

    return {
        "service": {
            "total": total,
            "intent_dist": intent_dist,
            "unknown_intent_count": unknown_count,
            "north_star": north_star,
            "satisfaction": satisfaction,
            "up_count": up_count,
            "down_count": down_count,
        },
        "leads": {
            "valid": north_star,
            "potential": commercial_count,
            "hot_products": hot_products,
        },
        "scenes": scenes,
        "requirements": requirements,
        "top_questions": top_q_list,
        "geo": geo,
        "geo_note": geo_note,
        "timeseries": timeseries,
    }


@router.post("/signals/refresh")
async def refresh_signals(
    _: EditorDep,
    request: Request,
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
) -> dict[str, Any]:
    """触发业务信号提取(场景/需求),由 LLM 分析已回答对话(admin/editor)。"""
    llm_router = getattr(request.app.state, "llm", None)
    if llm_router is None:
        raise HTTPException(status_code=503, detail="LLM 路由器未初始化")

    try:
        df = datetime.fromisoformat(date_from).replace(tzinfo=UTC) if date_from else None
        dt = datetime.fromisoformat(date_to).replace(tzinfo=UTC) if date_to else None
    except ValueError:
        raise HTTPException(status_code=422, detail="日期格式无效,需 ISO 8601")

    extractor = SignalExtractor(request.app.state.session_factory, llm_router)
    result = await extractor.extract(df, dt)
    return result
