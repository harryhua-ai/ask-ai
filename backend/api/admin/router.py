"""Admin API 路由汇总。"""

from fastapi import APIRouter

from backend.api.admin.auth import router as auth_router

admin_router = APIRouter(prefix="/api/admin")
admin_router.include_router(auth_router)
