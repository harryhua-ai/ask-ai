"""数据源 CRUD + 手动同步端点。"""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.admin.schemas import DataSourceCreate, DataSourceOut, DataSourceUpdate
from backend.auth.dependencies import CurrentUser, require_role
from backend.connectors.registry import SourceConfig
from backend.db.models import DataSource

router = APIRouter(prefix="/data-sources", tags=["数据源管理"])
EditorDep = Annotated[CurrentUser, Depends(require_role("admin", "editor"))]


def _to_out(ds: DataSource) -> DataSourceOut:
    """将 DataSource ORM 对象转换为 DataSourceOut schema。"""
    return DataSourceOut(
        id=ds.id,
        type=ds.type,
        product=ds.product,
        enabled=ds.enabled,
        config=ds.config,
        sync_interval=ds.sync_interval,
        created_at=ds.created_at.isoformat() if ds.created_at else "",
        updated_at=ds.updated_at.isoformat() if ds.updated_at else "",
    )


@router.get("", response_model=list[DataSourceOut])
async def list_data_sources(
    _: Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))],
    request: Request,
) -> list[DataSourceOut]:
    """列出全部数据源（viewer+ 可访问）。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        result = await session.execute(select(DataSource).order_by(DataSource.id))
        sources = result.scalars().all()
    return [_to_out(s) for s in sources]


@router.post("", response_model=DataSourceOut, status_code=201)
async def create_data_source(
    req: DataSourceCreate, _: EditorDep, request: Request
) -> DataSourceOut:
    """创建数据源（admin / editor）。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        existing = await session.execute(select(DataSource).where(DataSource.id == req.id))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="数据源 ID 已存在")
        ds = DataSource(**req.model_dump())
        session.add(ds)
        await session.commit()
        await session.refresh(ds)
    return _to_out(ds)


@router.patch("/{source_id}", response_model=DataSourceOut)
async def update_data_source(
    source_id: str, req: DataSourceUpdate, _: EditorDep, request: Request
) -> DataSourceOut:
    """更新数据源字段（admin / editor），仅更新非 None 字段。"""
    values = req.model_dump(exclude_none=True)
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        result = await session.execute(select(DataSource).where(DataSource.id == source_id))
        ds = result.scalar_one_or_none()
        if ds is None:
            raise HTTPException(status_code=404, detail="数据源不存在")
        for key, value in values.items():
            setattr(ds, key, value)
        await session.commit()
        await session.refresh(ds)
    return _to_out(ds)


@router.delete("/{source_id}", status_code=204)
async def delete_data_source(source_id: str, _: EditorDep, request: Request) -> None:
    """删除数据源（admin / editor）。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        result = await session.execute(select(DataSource).where(DataSource.id == source_id))
        ds = result.scalar_one_or_none()
        if ds is None:
            raise HTTPException(status_code=404, detail="数据源不存在")
        await session.delete(ds)
        await session.commit()


@router.post("/{source_id}/sync")
async def trigger_sync(source_id: str, _: EditorDep, request: Request) -> dict[str, str]:
    """手动触发指定数据源同步（后台异步执行，立即返回）。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        result = await session.execute(select(DataSource).where(DataSource.id == source_id))
        ds = result.scalar_one_or_none()
        if ds is None:
            raise HTTPException(status_code=404, detail="数据源不存在")
        if not ds.enabled:
            raise HTTPException(status_code=400, detail="数据源已禁用")
        cfg = SourceConfig(
            id=ds.id,
            type=ds.type,
            product=ds.product,
            enabled=ds.enabled,
            config=ds.config,
            sync_interval=ds.sync_interval,
        )

    async def _run() -> None:
        """后台任务：构造 pipeline 并调用 _sync_one(triggered_by="manual")。"""
        from backend.pipeline.ingest import IngestionPipeline
        from scripts.sync import _sync_one

        pipeline = IngestionPipeline(
            request.app.state.embedder,
            request.app.state.weaviate_client,
            class_name=request.app.state.weaviate_class_name,
        )
        await _sync_one(cfg, pipeline, factory, triggered_by="manual")

    # 后台任务不阻塞响应；异常在 _sync_one 内已被捕获并写入 SyncLog
    asyncio.create_task(_run())
    return {"status": "syncing", "source_id": source_id}
