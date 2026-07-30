"""答案覆盖 CRUD 端点(admin/editor 可写,viewer 只读)。"""

import asyncio
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.admin.schemas import (
    AnswerOverrideCreate,
    AnswerOverrideOut,
    AnswerOverrideUpdate,
)
from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import AnswerOverride

router = APIRouter(prefix="/answer-overrides", tags=["答案覆盖"])
ViewerDep = Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))]
EditorDep = Annotated[CurrentUser, Depends(require_role("admin", "editor"))]


def _to_out(ov: AnswerOverride) -> AnswerOverrideOut:
    """把 ORM 对象转为输出 schema。"""
    return AnswerOverrideOut(
        id=str(ov.id),
        match_pattern=ov.match_pattern,
        match_type=ov.match_type,
        override_answer=ov.override_answer,
        override_sources=ov.override_sources or [],
        created_by=ov.created_by,
        is_active=ov.is_active,
        created_at=ov.created_at.isoformat() if ov.created_at else "",
        updated_at=ov.updated_at.isoformat() if ov.updated_at else "",
    )


def _refresh_matcher(request: Request) -> None:
    """触发 OverrideMatcher 刷新缓存(如果已初始化)。"""
    matcher = getattr(request.app.state, "override_matcher", None)
    if matcher is not None:
        asyncio.create_task(matcher.refresh())  # noqa: RUF006


@router.get("")
async def list_overrides(
    _: ViewerDep,
    request: Request,
    is_active: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """查询覆盖列表(viewer+ 可访问)。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        q = select(AnswerOverride)
        count_q = select(func.count()).select_from(AnswerOverride)
        if is_active is not None:
            q = q.where(AnswerOverride.is_active == is_active)
            count_q = count_q.where(AnswerOverride.is_active == is_active)

        total = (await session.execute(count_q)).scalar() or 0
        result = await session.execute(
            q.order_by(AnswerOverride.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        overrides = result.scalars().all()

    return {
        "items": [_to_out(o).model_dump() for o in overrides],
        "total": total,
        "page": page,
        "size": size,
    }


@router.post("", status_code=201)
async def create_override(
    body: AnswerOverrideCreate,
    user: EditorDep,
    request: Request,
) -> dict[str, Any]:
    """创建覆盖(admin/editor),触发 OverrideMatcher refresh。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        ov = AnswerOverride(
            match_pattern=body.match_pattern,
            match_type=body.match_type,
            override_answer=body.override_answer,
            override_sources=body.override_sources,
            created_by=user.email,
            is_active=True,
        )
        session.add(ov)
        await session.commit()
        await session.refresh(ov)

    _refresh_matcher(request)
    return _to_out(ov).model_dump()


@router.patch("/{override_id}")
async def update_override(
    override_id: UUID,
    body: AnswerOverrideUpdate,
    _: EditorDep,
    request: Request,
) -> dict[str, Any]:
    """更新覆盖(admin/editor),触发 OverrideMatcher refresh。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        result = await session.execute(
            select(AnswerOverride).where(AnswerOverride.id == override_id)
        )
        ov = result.scalar_one_or_none()
        if ov is None:
            raise HTTPException(status_code=404, detail="覆盖不存在")

        update_data = body.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(ov, key, value)
        await session.commit()
        await session.refresh(ov)

    _refresh_matcher(request)
    return _to_out(ov).model_dump()


@router.delete("/{override_id}", status_code=204)
async def delete_override(
    override_id: UUID,
    _: EditorDep,
    request: Request,
) -> None:
    """删除覆盖(admin/editor),触发 OverrideMatcher refresh。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        result = await session.execute(
            select(AnswerOverride).where(AnswerOverride.id == override_id)
        )
        ov = result.scalar_one_or_none()
        if ov is None:
            raise HTTPException(status_code=404, detail="覆盖不存在")
        await session.delete(ov)
        await session.commit()

    _refresh_matcher(request)
