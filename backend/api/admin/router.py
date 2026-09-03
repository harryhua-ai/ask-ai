"""Admin API 路由汇总。"""

from fastapi import APIRouter

from backend.api.admin.analytics import router as analytics_router
from backend.api.admin.answer_overrides import router as answer_overrides_router
from backend.api.admin.attachments import router as attachments_router
from backend.api.admin.auth import router as auth_router
from backend.api.admin.business import router as business_router
from backend.api.admin.conversations import router as conversations_router
from backend.api.admin.customizations import router as customizations_router
from backend.api.admin.data_sources import router as data_sources_router
from backend.api.admin.leads import router as leads_router
from backend.api.admin.llm_providers import router as llm_providers_router
from backend.api.admin.sync_logs import router as sync_logs_router
from backend.api.admin.sync_runs import router as sync_runs_router
from backend.api.admin.system import router as system_router
from backend.api.admin.tech import tech_router
from backend.api.admin.traces import traces_router
from backend.api.admin.users import router as users_router

admin_router = APIRouter(prefix="/api/admin")
admin_router.include_router(auth_router)
admin_router.include_router(users_router)
admin_router.include_router(data_sources_router)
admin_router.include_router(sync_logs_router)
admin_router.include_router(sync_runs_router)
admin_router.include_router(customizations_router)
admin_router.include_router(llm_providers_router)
admin_router.include_router(leads_router)
admin_router.include_router(conversations_router)
admin_router.include_router(answer_overrides_router)
admin_router.include_router(analytics_router)
admin_router.include_router(attachments_router)
admin_router.include_router(traces_router)
admin_router.include_router(tech_router)
admin_router.include_router(business_router)
admin_router.include_router(system_router)
