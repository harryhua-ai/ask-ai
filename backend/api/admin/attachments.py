"""Admin 附件上传端点(Phase 1a:仅日志)。

走 admin_router(prefix=/api/admin),路由 /api/admin/upload,30/min 独立限流。
鉴权用 require_role("admin")。
"""

from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.routes import _do_upload, limiter
from backend.auth.dependencies import CurrentUser, require_role
from backend.services.attachments import MAX_ATTACHMENTS_PER_MESSAGE

router = APIRouter(tags=["附件上传"])
AdminUserDep = Annotated[CurrentUser, Depends(require_role("admin"))]


def _admin_session_factory(request: Request) -> async_sessionmaker[AsyncSession]:
    return request.app.state.session_factory


AdminSessionFactory = Annotated[async_sessionmaker[AsyncSession], Depends(_admin_session_factory)]


@router.post("/upload")
@limiter.limit("30/minute")
async def upload_attachments_admin(
    request: Request,
    user: AdminUserDep,
    background_tasks: BackgroundTasks,
    session_factory: AdminSessionFactory,
    files: list[UploadFile] = File(...),
) -> dict[str, Any]:
    """admin 上传:owner_type=admin,owner_id=str(user.id)。"""
    if len(files) > MAX_ATTACHMENTS_PER_MESSAGE:
        raise HTTPException(422, f"Too many files (max {MAX_ATTACHMENTS_PER_MESSAGE})")
    return await _do_upload(files, "admin", str(user.id), background_tasks, session_factory)
