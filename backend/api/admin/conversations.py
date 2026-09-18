"""对话审查端点（多维过滤 + 分页 + 详情）。"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import Text, desc, exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import Conversation, SiteExperience, SourceClick, Trace
from backend.services.intent_tagger import tag_batch, tag_single

router = APIRouter(prefix="/conversations", tags=["对话审查"])
ViewerDep = Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))]
EditorDep = Annotated[CurrentUser, Depends(require_role("admin", "editor"))]

# #68:country 筛选值 = ISO 3166-1 alpha-2 或显式 UNKNOWN(一等可筛值)
_COUNTRY_PATTERN = r"^([A-Z]{2}|UNKNOWN)$"
# #68:entry 筛选值 = 站点标识(site_id)或 UNKNOWN;不做 URL/文本猜测
_ENTRY_PATTERN = r"^(UNKNOWN|[A-Za-z0-9][A-Za-z0-9._-]{0,99})$"


def _surfaced_country(conv: Conversation) -> str | None:
    """呈现门:country 仅在携带权威来源时才是地理事实。

    legacy 启发式存量(source NULL)迁移已转 Unknown;呈现门兜底迁移窗口期
    内旧代码写入的行 —— 任何无来源标记的值一律不作为地理事实呈现。
    """
    return conv.country if conv.country_source else None


def _infer_markers(trace_type: str, stages: dict) -> dict:
    """从 trace type + stages 推断标记(failure/retry/clarify/reject_short/degraded)。

    语义与 tech.py _classify_trace 同源(OBS-03 调查定案):
    - retry: 仅显式 retry_count 字段算 literal retry(生产 trace 无此字段;
      error 单独存在是错误证据,不是重试证据,不得虚标重试)
    - failure: trace type=generation_error(routes.py PC-06 唯一失败持久化
      路径)或 stage error 且未 recovered
    - degraded: retrieve.path_counts symbol/boost 全 0(单路检索)
    - clarify/reject_short: 直接看 trace type
    """
    retry = any(
        isinstance(sd, dict) and sd.get("retry_count") for sd in stages.values()
    )
    failure = trace_type == "generation_error" or any(
        isinstance(sd, dict) and sd.get("error") and not sd.get("recovered")
        for sd in stages.values()
    )
    # 降级判定同 tech.py:仅当 retrieve 阶段真实存在且带 path_counts 证据;
    # 失败/拒答 trace 无 retrieve 阶段,缺失证据≠降级证据
    retrieve_sd = stages.get("retrieve")
    degraded = False
    if isinstance(retrieve_sd, dict):
        path_counts = retrieve_sd.get("path_counts")
        if isinstance(path_counts, dict) and path_counts:
            degraded = (
                path_counts.get("symbol", 0) == 0 and path_counts.get("boost", 0) == 0
            )
    return {
        "retry": retry,
        "failure": failure,
        "clarify": trace_type == "clarify",
        "reject_short": trace_type == "reject_short",
        "degraded": degraded,
    }


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
    has_retry: bool | None = Query(
        default=None,
        description="literal 重试(stages 含显式 retry_count 字段;生产路径暂不写入)",
    ),
    has_failure: bool | None = Query(
        default=None,
        description="真实失败(存在 trace type=generation_error;与 tech.py 失败语义同源)",
    ),
    has_feedback: bool | None = Query(default=None, description="Phase 2:有反馈"),
    has_clarify: bool | None = Query(
        default=None, description="Phase 2:触发澄清(trace type=clarify)"
    ),
    country: str | None = Query(
        default=None,
        pattern=_COUNTRY_PATTERN,
        description="#68:ISO 3166-1 alpha-2 或 UNKNOWN(一等可筛值)",
    ),
    entry: str | None = Query(
        default=None,
        pattern=_ENTRY_PATTERN,
        description="#68:站点标识(site_id)或 UNKNOWN;入口维度独立于 transport channel",
    ),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """查询对话列表（viewer+ 可访问），支持 channel / is_answered / feedback /
    intent_tag / q(全文搜索) / date_from / date_to / has_retry / has_feedback /
    has_clarify / country / entry 多维过滤 + 分页(#68 过滤在分页/计数前执行)。
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
            # The UUID is the administrator's canonical support handle. Keep
            # question/answer full-text behavior and add an exact text search
            # path without manufacturing a second display identifier.
            cond = (
                Conversation.question.ilike(pattern)
                | Conversation.answer.ilike(pattern)
                | Conversation.id.cast(Text).ilike(pattern)
            )
            stmt = stmt.where(cond)
            count_q = count_q.where(cond)
        if date_from:
            stmt = stmt.where(Conversation.created_at >= date_from)
            count_q = count_q.where(Conversation.created_at >= date_from)
        if date_to:
            stmt = stmt.where(Conversation.created_at <= date_to)
            count_q = count_q.where(Conversation.created_at <= date_to)

        # Phase 2:has_feedback(Conversation.feedback 非空)
        if has_feedback is True:
            stmt = stmt.where(Conversation.feedback.is_not(None))
            count_q = count_q.where(Conversation.feedback.is_not(None))
        elif has_feedback is False:
            stmt = stmt.where(Conversation.feedback.is_(None))
            count_q = count_q.where(Conversation.feedback.is_(None))

        # Phase 2:has_clarify(trace type=clarify,EXISTS 半连接)
        if has_clarify is True:
            stmt = stmt.where(
                exists().where(
                    Trace.conversation_id == Conversation.id,
                    Trace.type == "clarify",
                )
            )
            count_q = count_q.where(
                exists().where(
                    Trace.conversation_id == Conversation.id,
                    Trace.type == "clarify",
                )
            )

        # literal retry(stages JSONB 文本含显式 retry_count 字段)
        if has_retry is True:
            stmt = stmt.where(
                exists().where(
                    Trace.conversation_id == Conversation.id,
                    Trace.stages.cast(Text).like('%"retry_count":%'),
                )
            )
            count_q = count_q.where(
                exists().where(
                    Trace.conversation_id == Conversation.id,
                    Trace.stages.cast(Text).like('%"retry_count":%'),
                )
            )

        # 真实失败:存在 generation_error trace(与 tech.py 失败语义同源)
        if has_failure is True:
            stmt = stmt.where(
                exists().where(
                    Trace.conversation_id == Conversation.id,
                    Trace.type == "generation_error",
                )
            )
            count_q = count_q.where(
                exists().where(
                    Trace.conversation_id == Conversation.id,
                    Trace.type == "generation_error",
                )
            )

        # #68 Country/Entry 过滤:服务端、在分页/计数之前;与既有过滤器组合。
        # country 语义走呈现门 —— 仅权威来源值可命中具体国家码;UNKNOWN 覆盖
        # 无权威值行(含 legacy 启发式遗留),不为其制造第二事实。
        if country == "UNKNOWN":
            unknown_country = (
                Conversation.country_source.is_(None) | Conversation.country.is_(None)
            )
            stmt = stmt.where(unknown_country)
            count_q = count_q.where(unknown_country)
        elif country:
            trusted_country = (
                Conversation.country == country) & Conversation.country_source.is_not(
                None
            )
            stmt = stmt.where(trusted_country)
            count_q = count_q.where(trusted_country)
        if entry == "UNKNOWN":
            stmt = stmt.where(Conversation.site_id.is_(None))
            count_q = count_q.where(Conversation.site_id.is_(None))
        elif entry:
            stmt = stmt.where(Conversation.site_id == entry)
            count_q = count_q.where(Conversation.site_id == entry)

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
                .order_by(desc(Trace.turn_index))
            )
            trace_rows = (await session.execute(trace_q)).scalars().all()
            for t in trace_rows:
                if t.conversation_id not in trace_map:
                    stages = t.stages or {}
                    trace_map[t.conversation_id] = {
                        "type": t.type,
                        "stages": stages,
                        "total_ms": t.total_ms,
                        "confidence": t.confidence,
                        "markers": _infer_markers(t.type or "rag", stages),
                        # 阶段⑯:生成失败下钻到 failure_kind(additive,旧前端忽略);
                        # budget_declined 为独立 trace type,非 generation_error
                        "failure_kind": (
                            (stages.get("error") or {}).get("kind")
                            if t.type == "generation_error"
                            else None
                        ),
                    }

        # #68:Entry 权威投影 —— site_id → 站点配置 display_name(服务端解析,
        # 无 URL/transport 猜测);页面级批量解析站点标签。
        site_ids = {c.site_id for c in convs if c.site_id}
        entry_map: dict[str, dict] = {}
        if site_ids:
            site_rows = (
                await session.execute(
                    select(SiteExperience).where(SiteExperience.site_id.in_(site_ids))
                )
            ).scalars().all()
            entry_map = {
                s.site_id: {"site_id": s.site_id, "display_name": s.display_name}
                for s in site_rows
            }

    def _entry_of(conv: Conversation) -> dict | None:
        return entry_map.get(conv.site_id or "")

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
            # #68:Country 权威值(呈现门后)+ 来源标记 + Entry 站点投影
            "country": _surfaced_country(c),
            "country_source": c.country_source,
            "entry": _entry_of(c),
        }
        for c in convs
    ]
    return {"items": items, "total": total, "page": page, "size": size}


@router.get("/entry-options")
async def list_entry_options(_: ViewerDep, request: Request) -> list[dict[str, str]]:
    """#68:Entry 筛选候选(站点标识 + 权威显示名)。

    site_id 是标识符而非凭证;display_name 是站点配置的权威标签。
    viewer+ 可读(筛选器是只读 UI 输入),独立于 Editor 专属的站点体验管理面。
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        sites = (
            await session.execute(select(SiteExperience).order_by(SiteExperience.site_id))
        ).scalars().all()
    return [
        {"site_id": s.site_id, "display_name": s.display_name}
        for s in sites
    ]


@router.get("/country-options")
async def list_country_options(_: ViewerDep, request: Request) -> dict[str, list[str]]:
    """#68:Country 筛选候选(仅权威来源值;legacy 行不得借候选复活为事实)。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        rows = (
            await session.execute(
                select(Conversation.country)
                .where(
                    Conversation.country.is_not(None),
                    Conversation.country_source.is_not(None),
                )
                .distinct()
                .order_by(Conversation.country)
            )
        ).scalars().all()
    return {"countries": list(rows)}


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
        # 阶段⑯:最新一条 trace 的 type/failure_kind(additive,详情徽章
        # 需要区分 拒答/生成失败/服务繁忙;列表 trace_summary 已有同源数据)
        latest_trace = (
            await session.execute(
                select(Trace)
                .where(Trace.conversation_id == conversation_id)
                .order_by(desc(Trace.turn_index))
                .limit(1)
            )
        ).scalar_one_or_none()
        entry: dict | None = None
        if conv.site_id:
            site = await session.get(SiteExperience, conv.site_id)
            if site is not None:
                entry = {"site_id": site.site_id, "display_name": site.display_name}
    trace_stages = (latest_trace.stages if latest_trace else None) or {}
    return {
        "trace_type": latest_trace.type if latest_trace else None,
        "failure_kind": (
            (trace_stages.get("error") or {}).get("kind")
            if latest_trace and latest_trace.type == "generation_error"
            else None
        ),
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
        # #68:与列表同源的权威 Country/Entry 真相
        "country": _surfaced_country(conv),
        "country_source": conv.country_source,
        "entry": entry,
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
