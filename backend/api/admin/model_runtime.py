"""模型运行时 Admin API(模型配置 → 模型运行 Tab 的后端权威)。

- GET  /model-runtime        — 真相面:发现设备 + 三 workload 的
                                Configured/Effective/Status + 共享运行时 +
                                容量(auto/manual 预算与分级状态);
- PUT  /model-runtime/policies/{workload} — 持久化 Configured Device
                                (「应用更改」或重启生效;不触碰 Effective;
                                非法值 422);
- PUT  /model-runtime/gpu-budget — GPU 运行容量策略(auto/manual 上限);
- POST /model-runtime/apply  — 显式生效:按最新持久配置候选装配 + 原子换装,
                                本生命周期内落地(失败 409 且当前运行时零改动,
                                detail 为管理员可读的完整中文说明)。

权限:读 viewer+,写 editor+(与模型配置页一致)。
UI 权威 = 模型配置 → 模型运行(本 API 不建第二配置系统)。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from backend.auth.dependencies import CurrentUser, require_role
from backend.runtime.manager import WORKLOADS, ApplyRejectedError

router = APIRouter(prefix="/model-runtime", tags=["模型运行时"])

ViewerDep = Annotated[CurrentUser, Depends(require_role("viewer", "editor", "admin"))]
EditorDep = Annotated[CurrentUser, Depends(require_role("editor", "admin"))]


def _manager(request: Request):
    manager = getattr(request.app.state, "model_runtime", None)
    if manager is None:
        raise HTTPException(status_code=503, detail="model runtime not ready")
    return manager


@router.get("")
async def get_model_runtime(
    _: ViewerDep,
    request: Request,
) -> dict[str, Any]:
    """运行时真相(发现设备 + 策略 + 共享 + 容量)。"""
    return _manager(request).snapshot()


class WorkloadPolicyUpdate(BaseModel):
    """Configured Device 更新(「应用更改」或重启生效)。"""

    device_kind: str = Field(min_length=1, max_length=10)
    gpu_uuid: str | None = None


@router.put("/policies/{workload}")
async def put_workload_policy(
    workload: str,
    body: WorkloadPolicyUpdate,
    _: EditorDep,
    request: Request,
) -> dict[str, Any]:
    if workload not in WORKLOADS:
        raise HTTPException(
            status_code=404,
            detail=f"未知 workload: {workload}(合法值: {', '.join(WORKLOADS)})",
        )
    manager = _manager(request)
    try:
        return await manager.save_policy(
            request.app.state.session_factory,
            workload,
            device_kind=body.device_kind,
            gpu_uuid=body.gpu_uuid,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class GpuBudgetUpdate(BaseModel):
    """GPU 运行容量策略(auto=自动管理;manual=手动规划上限)。"""

    mode: str = Field(min_length=1, max_length=10)
    manual_budget_mb: int | None = None


@router.put("/gpu-budget")
async def put_gpu_budget(
    body: GpuBudgetUpdate,
    _: EditorDep,
    request: Request,
) -> dict[str, Any]:
    manager = _manager(request)
    try:
        return await manager.save_gpu_budget(
            request.app.state.session_factory,
            mode=body.mode,
            manual_budget_mb=body.manual_budget_mb,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/apply")
async def apply_model_runtime(
    _: EditorDep,
    request: Request,
) -> dict[str, Any]:
    """显式生效(「应用更改」):候选装配 + 原子换装,返回换装后完整真相面。

    失败语义(409):当前 Effective Runtime 零改动,线上查询不受影响;
    detail 为管理员可读的完整说明(原因 + 可操作指引)。
    """
    manager = _manager(request)
    try:
        return await manager.apply(request.app.state.session_factory)
    except ApplyRejectedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
