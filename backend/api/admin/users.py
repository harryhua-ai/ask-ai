"""用户管理 CRUD 端点（仅 admin）。"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.admin.schemas import UserCreate, UserOut, UserUpdate
from backend.auth.dependencies import CurrentUser, require_role
from backend.auth.jwt import hash_password
from backend.db.models import User

router = APIRouter(prefix="/users", tags=["用户管理"])
AdminDep = Annotated[CurrentUser, Depends(require_role("admin"))]


@router.get("", response_model=list[UserOut])
async def list_users(
    _: AdminDep,
    request: Request,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> list[UserOut]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        result = await session.execute(
            select(User).offset((page - 1) * size).limit(size).order_by(User.created_at.desc())
        )
        users = result.scalars().all()
    return [
        UserOut(id=str(u.id), email=u.email, name=u.name, role=u.role, is_active=u.is_active)
        for u in users
    ]


@router.post("", response_model=UserOut, status_code=201)
async def create_user(req: UserCreate, _: AdminDep, request: Request) -> UserOut:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        existing = await session.execute(select(User).where(User.email == req.email))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="邮箱已存在")
        user = User(
            email=req.email,
            name=req.name,
            role=req.role,
            password_hash=hash_password(req.password),
        )
        session.add(user)
        await session.commit()
    return UserOut(
        id=str(user.id), email=user.email, name=user.name, role=user.role, is_active=True
    )


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(user_id: UUID, req: UserUpdate, _: AdminDep, request: Request) -> UserOut:
    values = req.model_dump(exclude_none=True)
    if not values:
        raise HTTPException(status_code=400, detail="无更新字段")
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        result = await session.execute(
            update(User).where(User.id == user_id).values(**values).returning(User)
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        await session.commit()
    return UserOut(
        id=str(user.id), email=user.email, name=user.name, role=user.role, is_active=user.is_active
    )


@router.delete("/{user_id}", status_code=204)
async def delete_user(user_id: UUID, current: AdminDep, request: Request) -> None:
    if current.id == user_id:
        raise HTTPException(status_code=400, detail="不能删除自己")
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=404, detail="用户不存在")
        await session.delete(user)
        await session.commit()
