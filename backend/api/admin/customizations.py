"""Customization CRUD + 渠道绑定端点。

viewer+ 可读取 Customization 与绑定;admin / editor 可写入。
所有端点从 ``request.app.state.session_factory`` 获取异步会话,
不依赖全局 DB 单例,便于测试隔离。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.admin.schemas import (
    BindingOut,
    BindingUpdate,
    CustomizationCreate,
    CustomizationOut,
    CustomizationUpdate,
)
from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import Customization, CustomizationBinding

router = APIRouter(tags=["Customization 管理"])
EditorDep = Annotated[CurrentUser, Depends(require_role("admin", "editor"))]
ViewerDep = Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))]

VALID_CHANNELS = {"widget", "discord", "whatsapp", "mcp"}


def _to_out(cust: Customization) -> CustomizationOut:
    """将 ORM 对象转换为 CustomizationOut,按 model_fields 投影避免漂移。"""
    return CustomizationOut(**{c: getattr(cust, c) for c in CustomizationOut.model_fields})


@router.get("/customizations", response_model=list[CustomizationOut])
async def list_customizations(_: ViewerDep, request: Request) -> list[CustomizationOut]:
    """列出全部 Customization(viewer+ 可访问),按 id 排序。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        result = await session.execute(select(Customization).order_by(Customization.id))
        custs = result.scalars().all()
    return [_to_out(cust) for cust in custs]


@router.post("/customizations", response_model=CustomizationOut, status_code=201)
async def create_customization(
    req: CustomizationCreate, _: EditorDep, request: Request
) -> CustomizationOut:
    """创建 Customization(admin / editor),ID 重复返回 409。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        existing = await session.execute(select(Customization).where(Customization.id == req.id))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="配置 ID 已存在")
        cust = Customization(**req.model_dump())
        session.add(cust)
        await session.commit()
        await session.refresh(cust)
    return _to_out(cust)


@router.patch("/customizations/{cust_id}", response_model=CustomizationOut)
async def update_customization(
    cust_id: str, req: CustomizationUpdate, _: EditorDep, request: Request
) -> CustomizationOut:
    """更新 Customization 字段(admin / editor),仅写入非 None 字段。"""
    values = req.model_dump(exclude_none=True)
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        cust = await session.execute(select(Customization).where(Customization.id == cust_id))
        cust = cust.scalar_one_or_none()
        if cust is None:
            raise HTTPException(status_code=404, detail="配置不存在")
        for key, value in values.items():
            setattr(cust, key, value)
        await session.commit()
        await session.refresh(cust)
    return _to_out(cust)


@router.delete("/customizations/{cust_id}", status_code=204)
async def delete_customization(cust_id: str, _: EditorDep, request: Request) -> None:
    """删除 Customization(admin / editor)。不存在返回 404。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        cust = await session.execute(select(Customization).where(Customization.id == cust_id))
        cust = cust.scalar_one_or_none()
        if cust is None:
            raise HTTPException(status_code=404, detail="配置不存在")
        await session.delete(cust)
        await session.commit()


@router.get("/customization-bindings", response_model=list[BindingOut])
async def list_bindings(_: ViewerDep, request: Request) -> list[BindingOut]:
    """列出全部渠道绑定(viewer+ 可访问)。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        result = await session.execute(select(CustomizationBinding))
        bindings = result.scalars().all()
    return [BindingOut(channel=b.channel, customization_id=b.customization_id) for b in bindings]


@router.put("/customization-bindings/{channel}")
async def update_binding(
    channel: str, req: BindingUpdate, _: EditorDep, request: Request
) -> dict[str, str]:
    """更新指定渠道的绑定(admin / editor)。

    Body 为 ``{"customization_id": "xxx"}``;若渠道不存在则创建,存在则覆盖。
    校验 customization_id 存在(404),校验 channel 合法(400)。
    """
    if channel not in VALID_CHANNELS:
        raise HTTPException(status_code=400, detail=f"无效渠道，允许：{VALID_CHANNELS}")
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        cust = await session.execute(
            select(Customization).where(Customization.id == req.customization_id)
        )
        if cust.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="配置不存在")
        binding = await session.execute(
            select(CustomizationBinding).where(CustomizationBinding.channel == channel)
        )
        binding = binding.scalar_one_or_none()
        if binding:
            binding.customization_id = req.customization_id
        else:
            session.add(
                CustomizationBinding(channel=channel, customization_id=req.customization_id)
            )
        await session.commit()
    return {"status": "ok"}
