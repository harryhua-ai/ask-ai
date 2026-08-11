"""Analytics API:Coverage Gaps + Top Questions + Source Analytics。

提供:
- GET    /coverage-gaps           查询未回答问题聚类(viewer+)
- POST   /coverage-gaps/refresh   触发重新聚类(admin/editor)
- PATCH  /gaps/{cluster_id}/resolve  标记 gap 状态(admin/editor)
- GET    /top-questions           查询全部问题聚类(viewer+)
- POST   /top-questions/refresh   触发重新聚类(admin/editor)
- GET    /sources                 来源点击/引用聚合(viewer+)
- GET    /gap-trends              缺口趋势(按天未回答率)(viewer+)
- GET    /source-health           数据源健康度(viewer+)
"""

import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.admin.schemas import (
    AnalyticsRefreshResult,
    QuestionClusterList,
    QuestionClusterOut,
    SourceAnalyticsList,
)
from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import (
    Conversation,
    DataSource,
    Document,
    QuestionCluster,
    SourceClick,
    SyncLog,
    Trace,
)

router = APIRouter(prefix="/analytics", tags=["分析仪表盘"])
ViewerDep = Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))]
EditorDep = Annotated[CurrentUser, Depends(require_role("admin", "editor"))]


def _to_cluster_out(c: QuestionCluster, miss_type: str | None = None) -> dict[str, Any]:
    """将 QuestionCluster ORM 对象转换为 API 输出字典。"""
    out = {
        "id": str(c.id),
        "cluster_type": c.cluster_type,
        "representative_question": c.representative_question,
        "sample_questions": c.sample_questions or [],
        "question_count": c.question_count,
        "status": c.status,
        "period_start": c.period_start.isoformat() if c.period_start else None,
        "period_end": c.period_end.isoformat() if c.period_end else None,
        "created_at": c.created_at.isoformat() if c.created_at else "",
    }
    if miss_type is not None:
        out["miss_type"] = miss_type
    return out


# ----------------------------------------------------------------------- #
# Coverage Gaps
# ----------------------------------------------------------------------- #


@router.get("/coverage-gaps", response_model=QuestionClusterList)
async def list_coverage_gaps(
    _: ViewerDep,
    request: Request,
    status: str | None = Query(default=None, pattern="^(open|resolved)$"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """查询 Coverage Gaps 聚类列表(viewer+ 可访问)。

    每个 gap 附 miss_type 分类:召回空(sources 为空)/ 召回不足(sources 非空但仍未回答)。
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        q = select(QuestionCluster).where(QuestionCluster.cluster_type == "gap")
        count_q = (
            select(func.count())
            .select_from(QuestionCluster)
            .where(QuestionCluster.cluster_type == "gap")
        )
        if status:
            q = q.where(QuestionCluster.status == status)
            count_q = count_q.where(QuestionCluster.status == status)

        total = (await session.execute(count_q)).scalar() or 0
        result = await session.execute(
            q.order_by(QuestionCluster.question_count.desc()).offset((page - 1) * size).limit(size)
        )
        clusters = result.scalars().all()

        # 批量查询每个 cluster 的对话,按四态分类 miss_type(spec D4)
        # reject:is_answered=False(拒答)
        # low:answered, sources 非空, 最新 trace confidence<0.6(低相关)
        # 召回空:answered, sources 空
        # 召回不足:answered, sources 非空, confidence>=0.6 或无 trace
        miss_type_map: dict[str, str] = {}
        miss_type_summary: dict[str, int] = defaultdict(int)
        if clusters:
            cluster_ids = [str(c.id) for c in clusters]
            conv_q = select(
                Conversation.cluster_id,
                Conversation.sources,
                Conversation.is_answered,
                Conversation.id,
            ).where(Conversation.cluster_id.in_(cluster_ids))
            conv_rows = (await session.execute(conv_q)).all()

            # 批量查最新 trace confidence(turn_index 最大)
            conv_ids = [str(row.id) for row in conv_rows]
            conf_map: dict[str, float | None] = {}
            if conv_ids:
                trace_q = (
                    select(
                        Trace.conversation_id,
                        Trace.confidence,
                        Trace.turn_index,
                    )
                    .where(Trace.conversation_id.in_(conv_ids))
                    .order_by(Trace.turn_index.desc())
                )
                for row in (await session.execute(trace_q)).all():
                    cid = str(row.conversation_id)
                    if cid not in conf_map:
                        conf_map[cid] = row.confidence

            cluster_stats: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
            for row in conv_rows:
                cid = str(row.cluster_id) if row.cluster_id else ""
                sources = row.sources if isinstance(row.sources, list) else []
                conf = conf_map.get(str(row.id))
                if not row.is_answered:
                    miss = "reject"
                elif sources and conf is not None and conf < 0.6:
                    miss = "low"
                elif not sources:
                    miss = "召回空"
                else:
                    miss = "召回不足"
                cluster_stats[cid][miss] += 1
            for cid, stats in cluster_stats.items():
                dominant = max(stats, key=stats.get) if stats else "未分类"
                miss_type_map[cid] = dominant
                miss_type_summary[dominant] += 1

    items = [_to_cluster_out(c, miss_type_map.get(str(c.id), "未分类")) for c in clusters]
    return {
        "items": items,
        "total": total,
        "page": page,
        "size": size,
        "miss_type_summary": dict(miss_type_summary),
    }


@router.post("/coverage-gaps/refresh", response_model=AnalyticsRefreshResult)
async def refresh_coverage_gaps(
    _: EditorDep,
    request: Request,
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
) -> dict[str, Any]:
    """重新聚类未回答问题(admin/editor)。"""
    clustering = request.app.state.clustering
    try:
        df = datetime.fromisoformat(date_from) if date_from else None
        dt = datetime.fromisoformat(date_to) if date_to else None
    except ValueError:
        raise HTTPException(status_code=422, detail="date_from/date_to 格式无效,需 ISO 8601")
    results = await clustering.cluster("gap", df, dt)

    return {
        "cluster_count": len(results),
        "total_questions": sum(r.question_count for r in results),
    }


@router.patch("/gaps/{cluster_id}/resolve", response_model=QuestionClusterOut)
async def resolve_gap(
    cluster_id: uuid.UUID,
    body: dict,
    _: EditorDep,
    request: Request,
) -> dict[str, Any]:
    """标记 gap 为 resolved/open(admin/editor)。"""
    new_status = body.get("status", "resolved")
    if new_status not in ("open", "resolved"):
        raise HTTPException(status_code=422, detail="status 必须为 open 或 resolved")

    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        cluster = await session.execute(
            select(QuestionCluster).where(QuestionCluster.id == cluster_id)
        )
        cluster = cluster.scalar_one_or_none()
        if cluster is None:
            raise HTTPException(status_code=404, detail="聚类不存在")
        cluster.status = new_status
        await session.commit()
        await session.refresh(cluster)

    return _to_cluster_out(cluster)


# ----------------------------------------------------------------------- #
# Top Questions
# ----------------------------------------------------------------------- #


@router.get("/top-questions", response_model=QuestionClusterList)
async def list_top_questions(
    _: ViewerDep,
    request: Request,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """查询 Top Questions 聚类列表(viewer+ 可访问)。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        count_q = (
            select(func.count())
            .select_from(QuestionCluster)
            .where(QuestionCluster.cluster_type == "top")
        )
        total = (await session.execute(count_q)).scalar() or 0
        result = await session.execute(
            select(QuestionCluster)
            .where(QuestionCluster.cluster_type == "top")
            .order_by(QuestionCluster.question_count.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        clusters = result.scalars().all()

    return {
        "items": [_to_cluster_out(c) for c in clusters],
        "total": total,
        "page": page,
        "size": size,
    }


@router.post("/top-questions/refresh", response_model=AnalyticsRefreshResult)
async def refresh_top_questions(
    _: EditorDep,
    request: Request,
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
) -> dict[str, Any]:
    """重新聚类全部问题(admin/editor)。"""
    clustering = request.app.state.clustering
    try:
        df = datetime.fromisoformat(date_from) if date_from else None
        dt = datetime.fromisoformat(date_to) if date_to else None
    except ValueError:
        raise HTTPException(status_code=422, detail="date_from/date_to 格式无效,需 ISO 8601")
    results = await clustering.cluster("top", df, dt)

    return {
        "cluster_count": len(results),
        "total_questions": sum(r.question_count for r in results),
    }


# ----------------------------------------------------------------------- #
# Source Analytics
# ----------------------------------------------------------------------- #


@router.get("/sources", response_model=SourceAnalyticsList)
async def source_analytics(
    _: ViewerDep,
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """来源分析:source_clicks 按 URL 聚合(viewer+ 可访问)。

    仅聚合 source_clicks 表的点击数,按 URL 分组返回 top N。
    references 字段为预留占位(后续接入 conversations.sources 聚合)。
    时间窗口使用 timedelta 参数化,避免 SQL 注入。
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        clicks_result = await session.execute(
            select(
                SourceClick.source_url,
                SourceClick.source_type,
                SourceClick.product,
                func.count(SourceClick.id).label("clicks"),
            )
            .where(SourceClick.clicked_at >= func.now() - timedelta(days=days))
            .group_by(SourceClick.source_url, SourceClick.source_type, SourceClick.product)
            .order_by(func.count(SourceClick.id).desc())
            .limit(limit)
        )
        click_rows = clicks_result.all()

    return {
        "items": [
            {
                "url": row.source_url,
                "source_type": row.source_type,
                "product": row.product,
                "clicks": row.clicks,
                "references": 0,
            }
            for row in click_rows
        ],
        "days": days,
    }


# ----------------------------------------------------------------------- #
# Gap Trends — 按天未回答率时序
# ----------------------------------------------------------------------- #


@router.get("/gap-trends")
async def gap_trends(
    _: ViewerDep,
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
) -> dict[str, Any]:
    """缺口趋势:按天聚合对话总量与未回答数(viewer+ 可访问)。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    end = datetime.now(UTC)
    start = end - timedelta(days=days)

    async with factory() as session:
        q = (
            select(
                func.date_trunc("day", Conversation.created_at).label("day"),
                func.count().label("total"),
                func.count().filter(Conversation.is_answered.is_(False)).label("unanswered"),
            )
            .where(Conversation.created_at >= start, Conversation.created_at <= end)
            .group_by("day")
            .order_by("day")
        )
        rows = (await session.execute(q)).all()

    trends = [
        {
            "date": row.day.strftime("%m-%d") if row.day else "",
            "total": row.total,
            "unanswered": row.unanswered,
            "unanswered_rate": round(row.unanswered / row.total, 4) if row.total else 0.0,
        }
        for row in rows
    ]
    return {"trends": trends}


# ----------------------------------------------------------------------- #
# Source Health — 数据源健康度
# ----------------------------------------------------------------------- #


@router.get("/source-health")
async def source_health(
    _: ViewerDep,
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
) -> dict[str, Any]:
    """数据源健康度:同步成功率 + 文档数 + 最近同步(viewer+ 可访问)。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    cutoff = datetime.now(UTC) - timedelta(days=days)

    async with factory() as session:
        sync_q = (
            select(
                SyncLog.source_id,
                SyncLog.source_type,
                func.count().label("total_syncs"),
                func.count().filter(SyncLog.status == "success").label("success_syncs"),
                func.count().filter(SyncLog.status == "failed").label("failed_syncs"),
                func.max(SyncLog.started_at).label("last_sync"),
            )
            .where(SyncLog.started_at >= cutoff)
            .group_by(SyncLog.source_id, SyncLog.source_type)
        )
        sync_rows = (await session.execute(sync_q)).all()

        doc_q = select(
            Document.source_id,
            func.count().label("doc_count"),
            func.coalesce(func.sum(Document.chunk_count), 0).label("chunk_count"),
        ).group_by(Document.source_id)
        doc_rows = (await session.execute(doc_q)).all()
        doc_map = {row.source_id: (row.doc_count, row.chunk_count) for row in doc_rows}

        ds_q = select(DataSource.id, DataSource.product, DataSource.enabled)
        ds_rows = (await session.execute(ds_q)).all()
        ds_map = {row.id: (row.product, row.enabled) for row in ds_rows}

    items = []
    for row in sync_rows:
        doc_count, chunk_count = doc_map.get(row.source_id, (0, 0))
        product, enabled = ds_map.get(row.source_id, ("unknown", True))
        success_rate = round(row.success_syncs / row.total_syncs, 4) if row.total_syncs else 0.0
        health = (
            "healthy" if success_rate >= 0.9 else "degraded" if success_rate >= 0.5 else "critical"
        )
        items.append(
            {
                "source_id": row.source_id,
                "source_type": row.source_type,
                "product": product,
                "enabled": enabled,
                "doc_count": doc_count,
                "chunk_count": chunk_count,
                "sync_success_rate": success_rate,
                "total_syncs": row.total_syncs,
                "failed_syncs": row.failed_syncs,
                "health": health,
                "last_sync": row.last_sync.isoformat() if row.last_sync else None,
            }
        )

    return {"items": items, "days": days}
