"""数据源 CRUD + 手动同步端点。"""

import logging
import os
import re
from pathlib import Path, PurePosixPath
from typing import Annotated, Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.admin.schemas import DataSourceCreate, DataSourceOut, DataSourceUpdate
from backend.api.admin.source_center_schemas import (
    DiscoveryResultOut,
    GitHubDiscoveryRequest,
    WebsiteDiscoveryRequest,
)
from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import DataSource, SyncLog
from backend.services import repo_discovery, source_lifecycle
from backend.services.source_deletion import DeletionRequestError, request_deletion
from backend.services.source_discovery import parse_discovery_rules
from backend.services.source_lifecycle import DELETE_FAILED
from backend.services.website_discovery import build_website_preview

router = APIRouter(prefix="/data-sources", tags=["数据源管理"])
logger = logging.getLogger(__name__)
EditorDep = Annotated[CurrentUser, Depends(require_role("admin", "editor"))]

# C9 上传护栏:单文件大小上限(20MB)
MAX_UPLOAD_FILE_BYTES = 20 * 1024 * 1024


def _norm_discovery_target(value: object) -> str:
    """发现目标归一化(repo_url/base_url 匹配用):trim + 去尾斜杠 + 去 .git + 小写。"""
    v = str(value or "").strip().rstrip("/").lower()
    return v[:-4] if v.endswith(".git") else v


async def _load_source_discovery_rules(
    request: Request, *, ds_type: str, config_key: str, target_value: str
) -> list[dict]:
    """按发现目标身份查找既有源的持久发现策略(#22 规则继承通道)。

    preview 端点按 repo_url/base_url 无状态发现(请求 schema 冻结,不携带
    source_id),规则继承由此服务端查找完成:同类型且 config 目标键归一化
    相同的**最近创建**源,读其 ``config.discovery_rules``(治理记忆;无匹配
    或无规则 → 空 = 全新分类)。查找只读,零配置写入。
    """
    want = _norm_discovery_target(target_value)
    if not want:
        return []
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        rows = await session.execute(
            select(DataSource)
            .where(DataSource.type == ds_type)
            .order_by(DataSource.created_at.desc())
        )
        for ds in rows.scalars():
            cfg = ds.config or {}
            if _norm_discovery_target(cfg.get(config_key)) != want:
                continue
            return parse_discovery_rules(cfg.get("discovery_rules"))
    return []


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
        t.strip().lower() for t in (ds.config or {}).get("file_types", []) or [] if str(t).strip()
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
    return entry.is_dir() and entry.name not in SYSTEM_DIRS and not entry.name.startswith(".")


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
        lifecycle_state=ds.lifecycle_state,
        lifecycle_since=ds.lifecycle_since.isoformat() if ds.lifecycle_since else None,
        lifecycle_error=ds.lifecycle_error,
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
                ).join(
                    latest_sub,
                    (SyncLog.source_id == latest_sub.c.source_id)
                    & (SyncLog.started_at == latest_sub.c.max_started),
                )
            )
        ).all()
        latest_by_source = {
            row[0]: {"started_at": row[3], "status": row[1], "error_detail": row[2]} for row in rows
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
                latest_by_source[s.id]["error_detail"] if s.id in latest_by_source else None
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


def _kick_deletion_worker(request: Request) -> None:
    """受理后即时唤醒删除 worker(未接线/测试环境静默跳过,sweep 兜底)。"""
    worker = getattr(request.app.state, "deletion_worker", None)
    if worker is not None:
        worker.kick()


# DELETE 端点可受理的来源状态:ACTIVE 正常删除;DELETE_FAILED 再点删除 =
# 安全 retry(碰撞校验后重新入队,清空旧错误)。已在途状态幂等返回。
_DELETE_ALLOWED_FROM = frozenset({source_lifecycle.ACTIVE, DELETE_FAILED})
_RETRY_ALLOWED_FROM = frozenset({DELETE_FAILED})


@router.delete("/{source_id}", status_code=202)
async def delete_data_source(source_id: str, _: EditorDep, request: Request) -> dict[str, Any]:
    """删除数据源（admin / editor）—— #18 非阻塞 durable 异步删除。

    **202 = 删除已受理并持久进入生命周期(DELETE_REQUESTED)≠ 删除完成**。
    本端点不做任何 Weaviate purge,立即返回;后台 worker
    (``SourceDeletionWorker``)完成 purge 收敛后才在同一事务删配置行与
    账本行(先 purge 后删行,不产生「配置行已删但 purge 未知」的静默半态)。

    语义:
    - 幂等:已在途(DELETE_REQUESTED/DELETING)→ 202 原样返回当前状态;
    - DELETE_FAILED 再点删除 = 安全 retry;
    - 在途同步碰撞(pending/running 交接请求,含 sync-all 批量;running
      SyncRun)→ 409,状态零改变;
    - DELETING/DELETE_FAILED 源的同步资格由 lifecycle deny-by-default 拒绝;
    - 失败 → DELETE_FAILED + lifecycle_error,刷新页面可见,可 retry。
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        try:
            req = await request_deletion(session, source_id, allowed_from=_DELETE_ALLOWED_FROM)
        except DeletionRequestError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    _kick_deletion_worker(request)
    return {"status": req.state, "source_id": source_id, "accepted": req.accepted}


@router.post("/{source_id}/delete/retry", status_code=202)
async def retry_delete_data_source(source_id: str, _: EditorDep, request: Request) -> dict[str, Any]:
    """重试失败的数据源删除(仅 DELETE_FAILED 可进入;其余状态 409)。

    与 DELETE 端点同一受理管道(碰撞校验 + 持久化 DELETE_REQUESTED),
    清空 ``lifecycle_error`` 后交由后台 worker 重新执行(purge 幂等)。
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        try:
            req = await request_deletion(session, source_id, allowed_from=_RETRY_ALLOWED_FROM)
        except DeletionRequestError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    _kick_deletion_worker(request)
    return {"status": req.state, "source_id": source_id, "accepted": req.accepted}


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
async def preview_branches(owner: str, repo: str, _: EditorDep) -> dict[str, Any]:
    """预览 GitHub 仓库分支列表与默认分支(供前端多选与默认勾选)。

    GITHUB_TOKEN 从环境变量读取(可选,匿名调用有速率限制)。
    """
    branches, default_branch = await _fetch_github_branches(owner, repo)
    return {"branches": branches, "default_branch": default_branch}


@router.get("/preview-file-types")
async def preview_file_types(owner: str, repo: str, branch: str, _: EditorDep) -> dict[str, Any]:
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


@router.post("/discover-repo")
async def discover_repo_source(
    req: GitHubDiscoveryRequest, _: EditorDep, request: Request
) -> DiscoveryResultOut:
    """#16 Simple Mode:Repo URL(+可选分支)→ 仓库内容发现 + 推荐纳入策略。

    S0 共享 Discovery 契约(Source Center foundation)的 Git producer:
    只读远程 trees 扫描——**不 clone、不落盘、不触发同步、零配置写入**;
    推荐产物 ``recommended_config`` 编译为既有 config 词表
    (file_types/exclude_dirs),用户确认后经既有创建/更新端点保存,
    同步语义与 ingestion authority 不变(PD-2)。

    #22 规则继承:同 repo_url 的既有源若持久了 ``config.discovery_rules``,
    本次发现自动继承(命中组带 admin_decision 呈现;L1 技术安全结论不可被
    规则翻转);无既有源/无规则 = 全新分类,行为与 v1.0.0 一致。

    技术安全边界:秘密文件/模型工件/超大文件在发现层即标为不可纳入,
    且内容层安全检查在同步灌入时仍会执行——任何 Admin allowlist 不可绕过。
    发现属 editor+ 操作(与既有 preview 端点同权限位)。
    """
    try:
        rules = await _load_source_discovery_rules(
            request, ds_type="github", config_key="repo_url", target_value=req.repo_url
        )
        result = await run_in_threadpool(
            repo_discovery.discover_repository,
            req.repo_url,
            req.branch,
            repo_discovery.default_api_get,
            discovery_rules=rules,
        )
    except repo_discovery.RepoDiscoveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DiscoveryResultOut.from_result(result)

# #17 Website Simple Mode:预览抓取 UA(标识用途;与 connector 同一爬虫身份)
_WEBSITE_DISCOVERY_UA = "ask-ai-crawler/0.1 (+camthink-ai knowledge indexer)"


def _website_fetch_text(url: str) -> str | None:
    """Discovery 预览用同步抓取:非 200/任何异常 → None(证据由发现层记账)。

    阻塞 IO,**必须**经 ``run_in_threadpool`` 调用(504 事故回归防线:
    禁止在事件循环内做网络等待)。
    """
    try:
        resp = httpx.get(
            url,
            headers={"User-Agent": _WEBSITE_DISCOVERY_UA},
            timeout=15,
            follow_redirects=True,
        )
        if resp.status_code != 200:
            return None
        return resp.text
    except Exception:  # noqa: BLE001 - 预览抓取失败属正常发现路径,不抛
        return None


@router.post("/preview-website", response_model=DiscoveryResultOut)
async def preview_website(
    req: WebsiteDiscoveryRequest, _: EditorDep, request: Request
) -> DiscoveryResultOut:
    """Website Simple Mode 自动发现预览(#17)。

    输入站点 URL(普通用户只需这一个字段)→ 按 PD-3 冻结顺序发现 sitemap
    (robots 指令 → 显式 sitemap_url → 通用回退 → index 全子表)→ 逐 URL
    知识分类推荐(include/exclude/review + 人读理由)→ 统一 DiscoveryResult。

    - 零发现不伪装成功:200 + 空 candidates + 冻结告警,由 UI 显式呈现
    - 同域边界:跨域 sitemap/URL 显式跳过并在结果中给出原因
    - Advanced 的 sitemap override 经同一端点验证(sitemap_url 可选传入)

    #22 规则继承:同 base_url 的既有源若持久了 ``config.discovery_rules``,
    本次预览自动继承;未知路径经族群证据/规则继承证据化分类(兜底 review
    保留,unknown path 本身永远不是 include/review 理由)。
    """
    parsed = urlparse(req.base_url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(status_code=400, detail="站点地址必须是合法的 http(s) URL")
    if req.sitemap_url:
        sp = urlparse(req.sitemap_url.strip())
        if sp.scheme not in ("http", "https") or not sp.netloc:
            raise HTTPException(status_code=400, detail="sitemap 地址必须是合法的 http(s) URL")
    rules = await _load_source_discovery_rules(
        request, ds_type="web_crawl", config_key="base_url", target_value=req.base_url
    )
    result = await run_in_threadpool(
        build_website_preview,
        req.base_url.strip().rstrip("/"),
        _website_fetch_text,
        sitemap_url=req.sitemap_url.strip() if req.sitemap_url else None,
        discovery_rules=rules,
    )
    return DiscoveryResultOut.from_result(result)


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
        if not source_lifecycle.is_sync_eligible(ds.lifecycle_state):
            # deny-by-default:删除在途/删除失败(含未来未知状态)一律
            # 拒绝新同步——同步 deleting 源会复活已清理语料
            raise HTTPException(
                status_code=409,
                detail="数据源处于删除流程,不能同步"
                f"(当前状态: {source_lifecycle.normalize(ds.lifecycle_state)})",
            )
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
        # 批量同步同样尊重 lifecycle deny-by-default:删除在途/失败源不进
        # 本批(执行面 WHERE 过滤是第二道防线,这里保证返回的 source_ids
        # 不含不可同步源,前端轮询不空等)
        sources = [
            s for s in result.scalars().all() if source_lifecycle.is_sync_eligible(s.lifecycle_state)
        ]
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
