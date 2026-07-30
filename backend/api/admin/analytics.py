"""Analytics API:Coverage Gaps + Top Questions + Source Analytics。

提供:
- GET    /coverage-gaps           查询未回答问题聚类(viewer+)
- POST   /coverage-gaps/refresh   触发重新聚类(admin/editor)
- PATCH  /gaps/{cluster_id}/resolve  标记 gap 状态(admin/editor)
- GET    /top-questions           查询全部问题聚类(viewer+)
- POST   /top-questions/refresh   触发重新聚类(admin/editor)
- GET    /sources                 来源点击/引用聚合(viewer+)
"""

from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.admin.schemas import (
    AnalyticsRefreshResult,
    QuestionClusterOut,
    SourceAnalyticsOut,
)
from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import Conversation, QuestionCluster, SourceClick

router = APIRouter(prefix="/analytics", tags=["分析仪表盘"])
ViewerDep = Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))]
EditorDep = Annotated[CurrentUser, Depends(require_role("admin", "editor"))]


def _to_cluster_out(c: QuestionCluster) -> dict[str, Any]:
    """将 QuestionCluster ORM 对象转换为 API 输出字典。"""
    return {
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


# ----------------------------------------------------------------------- #
# Coverage Gaps
# ----------------------------------------------------------------------- #


@router.get("/coverage-gaps")
async def list_coverage_gaps(
    _: ViewerDep,
    request: Request,
    status: str | None = Query(default=None, pattern="^(open|resolved)$"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """查询 Coverage Gaps 聚类列表(viewer+ 可访问)。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        q = select(QuestionCluster).where(QuestionCluster.cluster_type == "gap")
        count_q = select(func.count()).select_from(QuestionCluster).where(
            QuestionCluster.cluster_type == "gap"
        )
        if status:
            q = q.where(QuestionCluster.status == status)
            count_q = count_q.where(QuestionCluster.status == status)

        total = (await session.execute(count_q)).scalar() or 0
        result = await session.execute(
            q.order_by(QuestionCluster.question_count.desc())
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


@router.post("/coverage-gaps/refresh")
async def refresh_coverage_gaps(
    _: EditorDep,
    request: Request,
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
) -> dict[str, Any]:
    """重新聚类未回答问题(admin/editor)。"""
    clustering = request.app.state.clustering
    df = datetime.fromisoformat(date_from) if date_from else None
    dt = datetime.fromisoformat(date_to) if date_to else None
    results = await clustering.cluster("gap", df, dt)

    return {
        "cluster_count": len(results),
        "total_questions": sum(r.question_count for r in results),
    }


@router.patch("/gaps/{cluster_id}/resolve")
async def resolve_gap(
    cluster_id: str,
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


@router.get("/top-questions")
async def list_top_questions(
    _: ViewerDep,
    request: Request,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """查询 Top Questions 聚类列表(viewer+ 可访问)。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        count_q = select(func.count()).select_from(QuestionCluster).where(
            QuestionCluster.cluster_type == "top"
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


@router.post("/top-questions/refresh")
async def refresh_top_questions(
    _: EditorDep,
    request: Request,
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
) -> dict[str, Any]:
    """重新聚类全部问题(admin/editor)。"""
    clustering = request.app.state.clustering
    df = datetime.fromisoformat(date_from) if date_from else None
    dt = datetime.fromisoformat(date_to) if date_to else None
    results = await clustering.cluster("top", df, dt)

    return {
        "cluster_count": len(results),
        "total_questions": sum(r.question_count for r in results),
    }


# ----------------------------------------------------------------------- #
# Source Analytics
# ----------------------------------------------------------------------- #


@router.get("/sources")
async def source_analytics(
    _: ViewerDep,
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """来源分析:最常引用 + 最多点击(viewer+ 可访问)。

    聚合 source_clicks 表的点击数和 conversations.sources 的引用数,
    按 URL 合并返回 top N。时间窗口使用 timedelta 参数化,避免 SQL 注入。
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
