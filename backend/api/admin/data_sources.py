"""数据源 CRUD + 手动同步端点。"""

import asyncio
import os
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.admin.schemas import DataSourceCreate, DataSourceOut, DataSourceUpdate
from backend.auth.dependencies import CurrentUser, require_role
from backend.connectors.db_adapter import to_source_config
from backend.db.models import DataSource, SyncLog

router = APIRouter(prefix="/data-sources", tags=["数据源管理"])
EditorDep = Annotated[CurrentUser, Depends(require_role("admin", "editor"))]

# 系统目录/构建产物:预览子目录时一律过滤,避免噪音与深层爆炸。
SYSTEM_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        "__pycache__",
        "build",
        "dist",
        ".venv",
        "venv",
        ".idea",
        ".vscode",
        "target",
        ".next",
    }
)
# 顶层/子层返回上限,防止巨型目录拖垮管理面板。
MAX_TOP_DIRS = 100
MAX_SUB_DIRS = 50


def _is_listable_dir(entry: Path) -> bool:
    """目录是否可列:是目录 + 非系统目录 + 非隐藏目录。"""
    return (
        entry.is_dir()
        and entry.name not in SYSTEM_DIRS
        and not entry.name.startswith(".")
    )


def _count_listable_subdirs(path: Path) -> int:
    """统计 path 下可列子目录数(单层,供前端展示 children_count)。"""
    try:
        return sum(1 for x in path.iterdir() if _is_listable_dir(x))
    except (PermissionError, OSError):
        return 0


def _to_out(ds: DataSource, last_sync: str | None = None) -> DataSourceOut:
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
        last_sync=last_sync,
    )


@router.get("", response_model=list[DataSourceOut])
async def list_data_sources(
    _: Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))],
    request: Request,
) -> list[DataSourceOut]:
    """列出全部数据源（viewer+ 可访问），并聚合每个源最新一次同步时间。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        result = await session.execute(select(DataSource).order_by(DataSource.id))
        sources = result.scalars().all()
        if not sources:
            return []
        # 每个 source 的最新一次同步(无论成功/失败/部分成功,都是"最近一次尝试")
        rows = (
            await session.execute(
                select(SyncLog.source_id, func.max(SyncLog.started_at))
                .where(SyncLog.source_id.in_([s.id for s in sources]))
                .group_by(SyncLog.source_id)
            )
        ).all()
        latest_by_source = {row[0]: row[1] for row in rows}
    return [
        _to_out(
            s,
            last_sync=latest_by_source[s.id].isoformat()
            if latest_by_source.get(s.id) is not None
            else None,
        )
        for s in sources
    ]


@router.post("", response_model=DataSourceOut, status_code=201)
async def create_data_source(
    req: DataSourceCreate, _: EditorDep, request: Request
) -> DataSourceOut:
    """创建数据源（admin / editor）。id 可选，缺省时按 product+短 hash 自动生成。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    source_id = req.id or f"{req.product}-{uuid4().hex[:8]}"
    async with factory() as session:
        existing = await session.execute(select(DataSource).where(DataSource.id == source_id))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="数据源 ID 已存在")
        ds = DataSource(**{**req.model_dump(exclude_unset=True), "id": source_id})
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


@router.get("/preview-dirs")
async def preview_dirs(root_path: str, _: EditorDep) -> dict[str, list[dict]]:
    """列出 root_path 下子目录(递归 2 层,过滤系统/隐藏目录),供前端目录选择器。

    安全:root_path 必须存在且为目录(否则 404);返回相对 root_path 的相对路径,
    不泄露服务器绝对路径结构。顶层限 100、子层限 50 防爆炸。
    """
    root = Path(root_path).expanduser()
    if not root.is_dir():
        raise HTTPException(status_code=404, detail=f"目录不存在: {root_path}")

    dirs: list[dict] = []
    try:
        top_entries = sorted(root.iterdir(), key=lambda p: p.name)
    except (PermissionError, OSError) as exc:
        raise HTTPException(status_code=403, detail=f"目录不可读: {root_path}") from exc

    for entry in top_entries:
        if not _is_listable_dir(entry):
            continue
        try:
            sub_entries = sorted(entry.iterdir(), key=lambda p: p.name)
        except (PermissionError, OSError):
            sub_entries = []
        children = [
            {
                "name": sub.name,
                "path": f"{entry.name}/{sub.name}",
                "children_count": _count_listable_subdirs(sub),
            }
            for sub in sub_entries
            if _is_listable_dir(sub)
        ]
        dirs.append(
            {
                "name": entry.name,
                "path": entry.name,
                "children": children[:MAX_SUB_DIRS],
                "children_count": len(children),
            }
        )
        if len(dirs) >= MAX_TOP_DIRS:
            break  # 防巨型目录爆炸
    return {"dirs": dirs}


@router.get("/preview-branches")
async def preview_branches(
    owner: str, repo: str, _: EditorDep
) -> dict[str, list[str]]:
    """预览 GitHub 仓库分支列表(供前端多选)。

    GITHUB_TOKEN 从环境变量读取(可选,匿名调用有速率限制)。
    """
    token = os.environ.get("GITHUB_TOKEN", "")
    headers = {
        "Accept": "application/vnd.github+json",
        **({"Authorization": f"Bearer {token}"} if token else {}),
    }
    async with httpx.AsyncClient(timeout=15, headers=headers) as client:
        resp = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/branches?per_page=100"
        )
        resp.raise_for_status()
    return {"branches": [b["name"] for b in resp.json()]}


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
        cfg = to_source_config(ds)

    # 捕获到闭包局部变量,避免后台任务引用已结束的 request 对象
    settings = request.app.state.settings
    embedder = request.app.state.embedder
    weaviate_client = request.app.state.weaviate_client
    weaviate_class_name = request.app.state.weaviate_class_name

    async def _run() -> None:
        """后台任务：构造 pipeline 并调用 _sync_one(triggered_by="manual")。"""
        from backend.db.session import get_sync_session_factory
        from backend.pipeline.ingest import IngestionPipeline
        from scripts.sync import _sync_one

        pipeline = IngestionPipeline(
            embedder,
            weaviate_client,
            class_name=weaviate_class_name,
            session_factory=get_sync_session_factory(settings.postgres_dsn),
        )
        await _sync_one(cfg, pipeline, factory, triggered_by="manual")

    # 后台任务不阻塞响应；异常在 _sync_one 内已被捕获并写入 SyncLog
    asyncio.create_task(_run())
    return {"status": "syncing", "source_id": source_id}
