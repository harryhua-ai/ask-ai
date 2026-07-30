"""Admin API 路由汇总。"""

from fastapi import APIRouter

from backend.api.admin.auth import router as auth_router
from backend.api.admin.data_sources import router as data_sources_router
from backend.api.admin.users import router as users_router

admin_router = APIRouter(prefix="/api/admin")
admin_router.include_router(auth_router)
admin_router.include_router(users_router)
admin_router.include_router(data_sources_router)
