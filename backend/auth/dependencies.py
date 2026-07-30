"""FastAPI 认证与 RBAC 依赖。"""

import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.auth.jwt import decode_access_token
from backend.db.models import User

_security = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_security)],
) -> User:
    """从 JWT Bearer token 解析当前用户。无 token / 过期 / 用户不存在 → 401。"""
    if creds is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="未提供认证令牌")
    settings = request.app.state.settings
    try:
        payload = decode_access_token(creds.credentials, settings.jwt_secret)
        user_id = uuid.UUID(payload["sub"])
    except Exception:  # noqa: BLE001 - 认证边界: token 解码/sub 解析错误统一返回 401,避免信息泄露
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="令牌无效或已过期")
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        user = await session.execute(select(User).where(User.id == user_id))
        user = user.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在或已禁用")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*roles: str) -> Callable[[CurrentUser], Awaitable[User]]:
    """RBAC 角色校验依赖工厂。用法：Depends(require_role("admin", "editor"))。"""

    async def _check(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="权限不足")
        return user

    return _check
