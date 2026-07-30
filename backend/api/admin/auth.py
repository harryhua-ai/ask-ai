"""Admin 认证端点：登录 / me / 改密码。"""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.admin.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    LoginResponse,
    UserOut,
)
from backend.auth.dependencies import CurrentUser
from backend.auth.jwt import create_access_token, hash_password, verify_password
from backend.db.models import User

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest, request: Request) -> LoginResponse:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    settings = request.app.state.settings
    async with factory() as session:
        result = await session.execute(select(User).where(User.email == req.email))
        user = result.scalar_one_or_none()
    if user is None or user.password_hash is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="邮箱或密码错误")
    if not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="邮箱或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账户已禁用")
    token = create_access_token(str(user.id), user.role, settings.jwt_secret)
    async with factory() as session:
        await session.execute(
            update(User).where(User.id == user.id).values(last_login_at=datetime.now(UTC))
        )
        await session.commit()
    return LoginResponse(
        access_token=token,
        user=UserOut(
            id=str(user.id),
            email=user.email,
            name=user.name,
            role=user.role,
            is_active=user.is_active,
        ),
    )


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> UserOut:
    return UserOut(
        id=str(user.id), email=user.email, name=user.name, role=user.role, is_active=user.is_active
    )


@router.put("/password")
async def change_password(
    req: ChangePasswordRequest, user: CurrentUser, request: Request
) -> dict[str, str]:
    if user.password_hash and not verify_password(req.old_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="原密码错误")
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        await session.execute(
            update(User)
            .where(User.id == user.id)
            .values(password_hash=hash_password(req.new_password))
        )
        await session.commit()
    return {"status": "ok"}
