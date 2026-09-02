"""数据源 CRUD + 手动同步端点。"""

import logging
import os
import re
from urllib.parse import urlparse
from pathlib import Path, PurePosixPath
from typing import Annotated, Any
from uuid import uuid4

import httpx
import weaviate
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from weaviate.classes.query import Filter

from backend.api.admin.schemas import DataSourceCreate, DataSourceOut, DataSourceUpdate
from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import DataSource, Document, SyncLog

router = APIRouter(prefix="/data-sources", tags=["数据源管理"])
logger = logging.getLogger(__name__)
EditorDep = Annotated[CurrentUser, Depends(require_role("admin", "editor"))]

# C9 上传护栏:单文件大小上限(20MB)
MAX_UPLOAD_FILE_BYTES = 20 * 1024 * 1024


def _upload_root(source_id: str) -> Path:
    """上传语料落盘根目录(相对仓库根,与 filesystem connector 同 CWD 语义)。"""
    return Path("data/uploads/data-sources") / source_id


def _safe_upload_path(base: Path, rel: str) -> Path:
    """相对路径规整 + 路径穿越防护:规整后必须落在 base 内,否则 400。

    拒绝:空路径 / 绝对路径 / 含 ``..`` 段;``resolve()`` 后再校验前缀,
    兜底已存在符号链接的逃逸。
    """
    if not rel or not rel.strip():
        raise HTTPException(status_code=400, detail="文件相对路径为空")
    p = PurePosixPath(rel)
    if p.is_absolute() or any(part == ".." for part in p.parts):
        raise HTTPException(status_code=400, detail=f"非法相对路径: {rel}")
    base_resolved = base.resolve()
    target = (base / p).resolve()
    if target != base_resolved and base_resolved not in target.parents:
        raise HTTPException(status_code=400, detail=f"路径越界: {rel}")
    return target


@router.post("/{source_id}/upload")
async def upload_source_files(
    source_id: str,
    _: EditorDep,
    request: Request,
    files: Annotated[list[UploadFile], File()],
    paths: Annotated[list[str], Form()],
) -> dict[str, object]:
    """上传语料文件到数据源上传目录(C9:持久语料,区别于聊天附件体系)。

    - 落盘 ``data/uploads/data-sources/<source_id>/``,保留相对路径嵌套结构
    - 路径穿越防护:相对路径规整后必须落在目标目录内
    - 护栏:单文件 ≤ 20MB;源配置了 file_types 白名单时按后缀校验
    - 再次上传 = 合并覆盖(同相对路径覆盖写;增量由 mtime/content_hash 检出)
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        result = await session.execute(select(DataSource).where(DataSource.id == source_id))
        ds = result.scalar_one_or_none()
    if ds is None:
        raise HTTPException(status_code=404, detail="数据源不存在")
    if ds.type != "filesystem":
        raise HTTPException(status_code=400, detail="仅 filesystem 数据源支持上传")
    if len(files) != len(paths):
        raise HTTPException(status_code=400, detail="files 与 paths 数量不一致")
    whitelist = {
        t.strip().lower()
        for t in (ds.config or {}).get("file_types", []) or []
        if str(t).strip()
    }
    base = _upload_root(source_id)
    saved = 0
    for uf, rel in zip(files, paths):
        rel_norm = str(rel).replace("\\", "/")
        if (uf.size or 0) > MAX_UPLOAD_FILE_BYTES:
            raise HTTPException(status_code=400, detail=f"文件超过 20MB 上限: {uf.filename}")
        ext = PurePosixPath(rel_norm).suffix.lower()
        if whitelist and ext not in whitelist:
            raise HTTPException(status_code=400, detail=f"文件类型不在白名单: {rel_norm}")
        target = _safe_upload_path(base, rel_norm)
        content = await uf.read()
        if len(content) > MAX_UPLOAD_FILE_BYTES:
            raise HTTPException(status_code=400, detail=f"文件超过 20MB 上限: {uf.filename}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        saved += 1
    return {"saved": saved, "root": f"data/uploads/data-sources/{source_id}"}

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

# github repo_url 解析(与 connectors/github.py _REPO_URL_RE 同语义)
_REPO_URL_RE = re.compile(r"github\.com/([^/\s]+)/([^\s/#]+?)(?:\.git)?/?$")
_DEFAULT_CLONE_ROOT = "~/ask-ai-corpus"


def _parse_repo_slug(repo_url: str) -> tuple[str, str] | None:
    """repo_url → (owner, repo);不合法返回 None。"""
    m = _REPO_URL_RE.search(repo_url or "")
    if not m:
        return None
    return m.group(1), m.group(2)


async def _fetch_github_branches(owner: str, repo: str) -> tuple[list[str], str]:
    """拉取远端分支列表与默认分支(校验与表单预览共用)。

    GITHUB_TOKEN 从环境变量读取(可选,匿名调用有速率限制)。
    """
    token = os.environ.get("GITHUB_TOKEN", "")
    headers = {
        "Accept": "application/vnd.github+json",
        **({"Authorization": f"Bearer {token}"} if token else {}),
    }
    async with httpx.AsyncClient(timeout=15, headers=headers) as client:
        repo_resp = await client.get(f"https://api.github.com/repos/{owner}/{repo}")
        repo_resp.raise_for_status()
        default_branch = str(repo_resp.json().get("default_branch", ""))
        br_resp = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/branches?per_page=100"
        )
        br_resp.raise_for_status()
        branches = [b["name"] for b in br_resp.json()]
    return branches, default_branch


def _configured_branches(cfg: dict) -> list[str]:
    """从源 config 取已配置分支(兼容 list 与逗号分隔字符串两种形态)。"""
    raw = cfg.get("branches") or []
    if isinstance(raw, str):
        return [b.strip() for b in raw.split(",") if b.strip()]
    return [str(b).strip() for b in raw if str(b).strip()]


async def _validate_github_branches(cfg: dict) -> None:
    """github 源校验 branches ⊆ 远端分支;不合法 → 400 拦截。

    无 repo_url / 未配置分支时跳过(兼容 owner/repo 旧配置与全量拉取场景);
    远端 API 不可达时放行并告警(无法核验 ≠ 不合法)。
    """
    slug = _parse_repo_slug(str(cfg.get("repo_url") or ""))
    branches = _configured_branches(cfg)
    if slug is None or not branches:
        return
    owner, repo = slug
    try:
        remote, _default = await _fetch_github_branches(owner, repo)
    except Exception as exc:  # noqa: BLE001 - 核验失败放行,不阻断创建/同步
        import logging

        logging.getLogger(__name__).warning(
            "分支合法性核验失败(放行): %s/%s: %s", owner, repo, str(exc)[:120]
        )
        return
    invalid = [b for b in branches if b not in remote]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"分支在远端仓库不存在: {', '.join(invalid)}"
            f"(远端可用: {', '.join(remote[:8])}{'...' if len(remote) > 8 else ''})",
        )


def _effective_clone_path(cfg: dict) -> str:
    """github 源的生效 clone 路径(显式配置优先,默认 ~/ask-ai-corpus/<repo>)。"""
    explicit = str(cfg.get("clone_path") or "").strip()
    if explicit:
        return explicit
    slug = _parse_repo_slug(str(cfg.get("repo_url") or ""))
    repo = slug[1] if slug else ""
    return f"{_DEFAULT_CLONE_ROOT}/{repo}"


async def _check_clone_path_conflict(
    factory: async_sessionmaker[AsyncSession], source_id: str, cfg: dict
) -> None:
    """同仓库已有源且未显式配置不同 clone_path → 409 拦截。

    背景:默认 clone 路径为 ~/ask-ai-corpus/<repo>,同仓库双源共用会互相
    fetch/reset 覆盖工作区。显式配置了不同 clone_path 的新源放行。
    """
    slug = _parse_repo_slug(str(cfg.get("repo_url") or ""))
    if slug is None:
        return
    owner, repo = slug
    # 新源已显式配置 clone_path → 视为调用方已处理冲突,放行
    if str(cfg.get("clone_path") or "").strip():
        return
    async with factory() as session:
        result = await session.execute(select(DataSource).where(DataSource.type == "github"))
        for ds in result.scalars():
            if ds.id == source_id:
                continue
            other_slug = _parse_repo_slug(str((ds.config or {}).get("repo_url") or ""))
            if other_slug != (owner, repo):
                continue
            other_explicit = str((ds.config or {}).get("clone_path") or "").strip()
            if not other_explicit:
                raise HTTPException(
                    status_code=409,
                    detail=f"仓库 {owner}/{repo} 已有数据源「{ds.id}」,两者默认 clone_path"
                    "相同会互相覆盖;请新源显式配置不同的 clone_path",
                )
        return


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


def _to_out(
    ds: DataSource,
    last_sync: str | None = None,
    last_sync_status: str | None = None,
    last_sync_error: str | None = None,
) -> DataSourceOut:
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
        last_sync_status=last_sync_status,
        last_sync_error=last_sync_error,
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
        # 每个 source 的最新一次同步(无论成功/失败,都是"最近一次尝试")+ 其 status/error
        # 用 MAX(started_at) 子查询 join 回 sync_log,取该行的 status/error_detail
        latest_sub = (
            select(SyncLog.source_id, func.max(SyncLog.started_at).label("max_started"))
            .where(SyncLog.source_id.in_([s.id for s in sources]))
            .group_by(SyncLog.source_id)
            .subquery()
        )
        rows = (
            await session.execute(
                select(
                    SyncLog.source_id,
                    SyncLog.status,
                    SyncLog.error_detail,
                    SyncLog.started_at,
                )
                .join(
                    latest_sub,
                    (SyncLog.source_id == latest_sub.c.source_id)
                    & (SyncLog.started_at == latest_sub.c.max_started),
                )
            )
        ).all()
        latest_by_source = {
            row[0]: {"started_at": row[3], "status": row[1], "error_detail": row[2]}
            for row in rows
        }
    return [
        _to_out(
            s,
            last_sync=(
                latest_by_source[s.id]["started_at"].isoformat()
                if s.id in latest_by_source
                else None
            ),
            last_sync_status=(
                latest_by_source[s.id]["status"] if s.id in latest_by_source else None
            ),
            last_sync_error=(
                latest_by_source[s.id]["error_detail"]
                if s.id in latest_by_source
                else None
            ),
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
    if req.type == "github":
        await _validate_github_branches(req.config)
        await _check_clone_path_conflict(factory, source_id, req.config)
    if req.type == "filesystem" and (req.config or {}).get("upload_mode"):
        # C9 上传模式:root_path 由服务端指向落盘目录,用户不可见不可手填
        req.config["root_path"] = f"data/uploads/data-sources/{source_id}"
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
        if ds.type == "github":
            await _validate_github_branches(ds.config)
        if ds.type == "filesystem" and (ds.config or {}).get("upload_mode"):
            # C9 上传模式:root_path 始终由服务端指向落盘目录,与创建时同语义,
            # 防止前端提交的空值把同步根路径抹掉
            ds.config["root_path"] = f"data/uploads/data-sources/{source_id}"
        await session.commit()
        await session.refresh(ds)
    return _to_out(ds)


def _purge_source_corpus_sync(
    weaviate_url: str, class_name: str, prefix: str, ledger: list[tuple[str, int]]
) -> dict:
    """清除某数据源名下的全部向量语料(G2 重写:PRUNE IS DOCUMENT-LOCAL)。

    三段式,前缀边界严格为 ``prefix + "/"``,**全路径无任何 TEXT 属性过滤
    删除原语**(P0-A/G2 冻结禁令:Weaviate 对 TEXT 的 equal/like 是分词
    语义,``equal("a/b")`` 会命中共享 token 的兄弟文档,生产实证可跨源
    误删):

        1. 账本段:对 PG documents 已知的每个 source_id,按该文档自己的
           确定性 UUID(uuid5(source_id, 0..chunk_count-1))批量点删——
           与 ingest._prune_stale_chunks/delete_document 同一文档局部保证;
        2. 孤儿段:迭代器全扫 + 客户端前缀边界过滤,收集**实际存量对象
           UUID** 后逐个删除(读侧允许 TEXT 前缀判断,删侧只点名对象 UUID);
        3. 验证段:再次边界扫描,残留 > 0 则 raise——调用方转 502,配置与
           账本原样保留可重试(不假报成功)。

    Returns:
        ``{"ledger_docs": N, "orphans": M, "residue": 0}`` 供日志观察。

    Raises:
        RuntimeError: 验证段发现残留(删除未收敛)。
    """
    from backend.pipeline.ingest import _deterministic_uuid

    parsed = urlparse(weaviate_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 8080
    client = weaviate.connect_to_local(host=host, port=port)
    try:
        collection = client.collections.get(class_name)

        # 1) 账本段:文档局部确定性 UUID 点删
        purge_uuids: list[str] = []
        for sid, cc in ledger:
            purge_uuids.extend(_deterministic_uuid(sid, i) for i in range(int(cc or 0)))
        for start in range(0, len(purge_uuids), 500):
            collection.data.delete_many(
                where=Filter.by_id().contains_any(purge_uuids[start : start + 500])
            )

        # 2) 孤儿段:实际存量扫描 → 对象 UUID 点删
        stale_uuids: list[str] = []
        for item in collection.iterator(return_properties=["source_id"]):
            sid = item.properties.get("source_id")
            if isinstance(sid, str) and sid.startswith(prefix + "/"):
                stale_uuids.append(str(item.uuid))
        for u in stale_uuids:
            collection.data.delete_by_id(u)

        # 3) 验证段:残留必须为 0
        residue = 0
        for item in collection.iterator(return_properties=["source_id"]):
            sid = item.properties.get("source_id")
            if isinstance(sid, str) and sid.startswith(prefix + "/"):
                residue += 1
        if residue:
            raise RuntimeError(
                f"purge 后仍有 {residue} 个残留向量对象(source={prefix}),保留状态可重试"
            )

        logger.info(
            "语料清理完成: 账本 %d 篇(UUID 点删 %d), 孤儿 %d chunks, 残留 0",
            len(ledger),
            len(purge_uuids),
            len(stale_uuids),
        )
        return {"ledger_docs": len(ledger), "orphans": len(stale_uuids), "residue": 0}
    finally:
        client.close()


@router.delete("/{source_id}", status_code=204)
async def delete_data_source(source_id: str, _: EditorDep, request: Request) -> None:
    """删除数据源（admin / editor）。

    AFP-001 生命周期契约:删除源 ⇒ 其独占知识退出访客检索。
    顺序(失败安全,绝不假报成功):
        1. 枚举账本内该源文档(source_id 前缀);
        2. 清理 Weaviate 向量(账本 Equal 精确删 + 前缀边界孤儿兜底删);
           失败 → 502,配置与账本原样保留(可重试);
        3. 同一事务删除 documents 账本行 + 配置行。
    """
    settings = request.app.state.settings
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        result = await session.execute(select(DataSource).where(DataSource.id == source_id))
        ds = result.scalar_one_or_none()
        if ds is None:
            raise HTTPException(status_code=404, detail="数据源不存在")
        ledger = (
            await session.execute(
                select(Document.source_id, Document.chunk_count).where(
                    # AC-FIX-01:源 ID 是字面标识符,不是 LIKE 模式 ——
                    # autoescape 转义 %/_ ,杜绝通配符越界吸走他源账本
                    Document.source_id.startswith(f"{source_id}/", autoescape=True)
                )
            )
        ).all()

    try:
        stats = await run_in_threadpool(
            _purge_source_corpus_sync,
            settings.weaviate_url,
            settings.weaviate_class_name,
            source_id,
            [(sid, int(cc or 0)) for sid, cc in ledger],
        )
    except Exception as exc:  # noqa: BLE001 - 清理失败必须可观察,保留全部状态可重试
        logger.error("数据源 %s 向量语料清理失败: %s", source_id, exc)
        raise HTTPException(
            status_code=502,
            detail=f"向量语料清理失败,已保留数据源与账本以便重试: {exc}",
        ) from exc
    logger.info(
        "数据源 %s 语料清理完成: 账本 %d 篇, 孤儿 %d chunks",
        source_id,
        stats.get("ledger_docs", 0),
        stats.get("orphans", 0),
    )

    async with factory() as session:
        result = await session.execute(select(DataSource).where(DataSource.id == source_id))
        ds = result.scalar_one_or_none()
        if ds is not None:
            await session.delete(ds)
        await session.execute(
            delete(Document).where(
                Document.source_id.startswith(f"{source_id}/", autoescape=True)
            )
        )
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
) -> dict[str, Any]:
    """预览 GitHub 仓库分支列表与默认分支(供前端多选与默认勾选)。

    GITHUB_TOKEN 从环境变量读取(可选,匿名调用有速率限制)。
    """
    branches, default_branch = await _fetch_github_branches(owner, repo)
    return {"branches": branches, "default_branch": default_branch}


@router.get("/preview-file-types")
async def preview_file_types(
    owner: str, repo: str, branch: str, _: EditorDep
) -> dict[str, Any]:
    """预览仓库内出现的全部文件后缀(C10 增补:默认全列,用户按需删)。

    GitHub trees API 递归列举指定分支文件树;点开头的文件名(如 .gitignore)
    不计后缀;去重排序返回。
    """
    token = os.environ.get("GITHUB_TOKEN", "")
    headers = {
        "Accept": "application/vnd.github+json",
        **({"Authorization": f"Bearer {token}"} if token else {}),
    }
    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        resp = await client.get(
            f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1"
        )
        resp.raise_for_status()
    extensions: set[str] = set()
    for item in resp.json().get("tree", []):
        if item.get("type") != "blob":
            continue
        name = str(item.get("path", "")).rsplit("/", 1)[-1]
        if name.startswith("."):
            continue
        ext = Path(name).suffix.lower()
        if ext:
            extensions.add(ext)
    return {"extensions": sorted(extensions)}


@router.post("/{source_id}/sync", status_code=202)
async def trigger_sync(source_id: str, _: EditorDep, request: Request) -> dict[str, Any]:
    """手动触发指定数据源同步 —— 提交交接请求给独立同步执行面,立即返回。

    P4(阶段9 冻结,2026-09-02 生产 504 事故回归防线):本端点只做校验 +
    向 ``sync_requests`` 交接表写入一行持久 pending 请求,**绝不**在本
    进程/本容器内执行重型 ingest。执行由独立 ``sync-executor`` 容器领用
    (``scripts/sync_executor_loop.py`` → 子进程 ``scripts/sync.py``),
    backend 容器重启/重建/换镜像不影响交接队列与进行中的同步(AC6
    容器级隔离)。

    **accepted = 请求已持久进入执行面交接队列 ≠ sync success**:业务
    结果以 sync_log 为准(前端 5s 轮询 last_sync 判定完成)。交接写库
    失败返回 502,不伪装成功。
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        result = await session.execute(select(DataSource).where(DataSource.id == source_id))
        ds = result.scalar_one_or_none()
        if ds is None:
            raise HTTPException(status_code=404, detail="数据源不存在")
        if not ds.enabled:
            raise HTTPException(status_code=400, detail="数据源已禁用")
        if ds.type == "github":
            await _validate_github_branches(ds.config)

        from backend.services.sync_requests import SyncRequestSubmitError, submit_sync_request

        try:
            submit = await submit_sync_request(session, source_id, triggered_by="manual")
        except SyncRequestSubmitError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
    return {
        "status": submit.state,
        "source_id": source_id,
        "request_id": submit.request_id,
    }


@router.post("/sync-all", status_code=202)
async def trigger_sync_all(_: EditorDep, request: Request) -> dict[str, Any]:
    """一键同步所有启用的数据源 —— 提交交接请求给独立同步执行面,立即返回。

    整批是**一个**交接请求(``source_id IS NULL``),执行面以**单个**
    ``scripts/sync.py`` 子进程顺序跑各源(单 pipeline,避免并发 BGE embed
    导致 GPU OOM)。返回保留 ``source_ids``/``count`` 键:前端据此批量
    种子轮询(触发时点启用的源;执行面领用时以 DB 当时状态为准)。
    **accepted = 已持久进入交接队列 ≠ success**:结果以各源 sync_log 为准。
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        result = await session.execute(
            select(DataSource).where(DataSource.enabled.is_(True)).order_by(DataSource.id)
        )
        sources = result.scalars().all()
        if not sources:
            return {"status": "noop", "source_ids": [], "count": 0}

        from backend.services.sync_requests import SyncRequestSubmitError, submit_sync_request

        try:
            submit = await submit_sync_request(session, None, triggered_by="manual")
        except SyncRequestSubmitError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
    return {
        "status": submit.state,
        "source_ids": [s.id for s in sources],
        "count": len(sources),
        "request_id": submit.request_id,
    }
