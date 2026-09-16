"""数据源 CRUD + 手动同步端点。"""

import asyncio
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Annotated, Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.admin.schemas import (
    BulkDocumentRepairItem,
    BulkDocumentRepairOut,
    ChunkServingTruth,
    DataSourceCreate,
    DataSourceDocumentItem,
    DataSourceDocumentsResponse,
    DataSourceDocumentTruth,
    DataSourceGenerationsResponse,
    DataSourceOut,
    DataSourceUpdate,
    DocumentCurrentVersionTruth,
    DocumentCitationTruth,
    DocumentCommerceTruth,
    DocumentGenerationTruth,
    DocumentRepairRequest,
    DocumentRepairTaskOut,
    DocumentVersionHistoryEntry,
    KnowledgePreviewRequest,
    KnowledgePreviewResponse,
    KnowledgeSettingsOut,
    KnowledgeSettingsUpdate,
    SourceAttentionSummaryItem,
    SourceAttentionSummaryResponse,
    SourceScheduleTruthOut,
)
from backend.api.admin.source_center_schemas import (
    DiscoveryResultOut,
    GitHubDiscoveryRequest,
    WebsiteDiscoveryRequest,
)
from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import (
    DataSource,
    Document,
    DocumentRepairTask,
    DocumentVersion,
    DocumentVersionChunk,
    IndexGeneration,
    SyncLog,
)
from backend.pipeline.canonical_url import wiki_canonical_url
from backend.pipeline.rag import LINK_STATE_NONE, _derive_link_state
from backend.services import knowledge_policy, repo_discovery, source_lifecycle
from backend.services import schedule_truth as schedule_truth_svc
from backend.services.chunk_serving import chunk_serving_for_doc
from backend.services.document_lifecycle import (
    DocLifecycle,
    get_absence_state,
    get_retirement_record,
)
from backend.services.document_repair import (
    create_repair_task,
    ensure_repair_stack,
    execute_repair_task,
)
from backend.services.recovery_events import recovery_counts
from backend.services.source_deletion import DeletionRequestError, request_deletion
from backend.services.source_discovery import parse_discovery_rules
from backend.services.source_lifecycle import DELETE_FAILED
from backend.services.website_discovery import build_website_preview

router = APIRouter(prefix="/data-sources", tags=["数据源管理"])
logger = logging.getLogger(__name__)
EditorDep = Annotated[CurrentUser, Depends(require_role("admin", "editor"))]
ViewerDep = Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))]

# C9 上传护栏:单文件大小上限(20MB)
MAX_UPLOAD_FILE_BYTES = 20 * 1024 * 1024

# 批量修复是数据源级命令:进程内立即拒绝重复请求,跨 worker 再由
# DataSource 行锁兜底。锁只覆盖一次批量操作的受理/执行窗口,不跨请求持久化。
_BULK_REPAIR_LOCKS: dict[str, asyncio.Lock] = {}


def _norm_discovery_target(value: object) -> str:
    """发现目标归一化(repo_url/base_url 匹配用):trim + 去尾斜杠 + 去 .git + 小写。"""
    v = str(value or "").strip().rstrip("/").lower()
    return v.removesuffix(".git")


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
    *,
    next_run_at: str | None = None,
    schedule_state: str | None = None,
    freshness_overdue: bool | None = None,
) -> DataSourceOut:
    """将 DataSource ORM 对象转换为 DataSourceOut schema。

    v1.6.3 Track C 加性真值(U-11/U-12):next_run_at/schedule_state 由
    调度 reconcile 提供(调用方注入,本函数零计算);knowledge_role/
    freshness_hours = 行上生效值(NULL 语义在 schema 层展开)。
    """
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
        next_run_at=next_run_at,
        schedule_state=schedule_state,
        knowledge_role=knowledge_policy.effective_role(ds),
        freshness_hours=knowledge_policy.effective_freshness_hours(ds),
        freshness_overdue=freshness_overdue,
        membership_status=ds.membership_status,
        membership_checked_at=(
            ds.membership_checked_at.isoformat() if ds.membership_checked_at else None
        ),
        membership_stale_detected=ds.membership_stale_detected,
        membership_stale_retired=ds.membership_stale_retired,
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
        # U-11:读面 reconcile——调度真值幂等收敛并持久化(权威列),禁止
        # 前端从 sync_interval 派生;U-12:后端权威新鲜度超期态(Admin 可见)。
        inflight = await schedule_truth_svc.inflight_request_map(
            session, [s.id for s in sources]
        )
        for s in sources:
            await schedule_truth_svc.reconcile_next_run_at(session, s)
        overdue_by_source = {
            s.id: knowledge_policy.freshness_truth(
                s, await knowledge_policy.last_success_at(session, s.id)
            )["overdue"]
            for s in sources
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
            next_run_at=(s.next_run_at.isoformat() if s.next_run_at else None),
            schedule_state=schedule_truth_svc.schedule_state_of(s, inflight.get(s.id, False)),
            freshness_overdue=overdue_by_source.get(s.id),
        )
        for s in sources
    ]


@router.get("/attention-summary", response_model=SourceAttentionSummaryResponse)
async def get_attention_summary(
    _: Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))],
    request: Request,
) -> SourceAttentionSummaryResponse:
    """v1.6.3 B1:全源运营桶聚合投影(只读 GET,viewer 可读)。

    与 ``GET /data-sources/{source_id}/documents`` 的聚合计数**同一定义**
    (current = active ∧ 现行版本可解析;retired = superseded + deleted;
    attention = ledger_total − current − retired;DocLifecycle 词表)。
    供扫描优先列表页一次取全,零语义新增,仅查 Postgres;
    无文档源以零值行出现(列表「需处理」一等列的权威计数来源)。
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        sources = (
            (await session.execute(select(DataSource).order_by(DataSource.id))).scalars().all()
        )
        resolvable = _current_version_resolvable()
        items = []
        for source in sources:
            lifecycle_rows = (
                await session.execute(
                    select(Document.lifecycle, func.count())
                    .where(_document_scope(source.id))
                    .group_by(Document.lifecycle)
                )
            ).all()
            lifecycle_counts = {row[0]: int(row[1]) for row in lifecycle_rows}
            ledger_total = sum(lifecycle_counts.values())
            retired = (
                lifecycle_counts.get(DocLifecycle.SUPERSEDED, 0)
                + lifecycle_counts.get(DocLifecycle.DELETED, 0)
            )
            current = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(Document)
                        .where(
                            _document_scope(source.id),
                            Document.lifecycle == DocLifecycle.ACTIVE,
                            resolvable,
                        )
                    )
                ).scalar()
                or 0
            )
            serving = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(Document)
                        .where(
                            _document_scope(source.id),
                            Document.lifecycle.in_(DocLifecycle.SERVING),
                            resolvable,
                        )
                    )
                ).scalar()
                or 0
            )
            items.append(
                SourceAttentionSummaryItem(
                    source_id=source.id,
                    ledger_total=ledger_total,
                    current_count=current,
                    serving_count=serving,
                    retired_count=retired,
                    attention_count=max(0, ledger_total - current - retired),
                    lifecycle_counts=lifecycle_counts,
                )
            )
    return SourceAttentionSummaryResponse(items=items)


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
        # U-11:调度配置变化(sync_interval/enabled)→ 立即 reconcile 调度真值
        await schedule_truth_svc.reconcile_next_run_at(session, ds)
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


# --------------------------------------------------------------------------- #
# #50 B1 Data Source Workspace V2:只读内容/生成真相读面(全部 GET,零写路径)
#
# 合同(docs/engineering/tasks/v162-i50-data-source-workspace-v2-contract.md):
# - 真相一律来自权威账本(documents / document_versions / document_version_chunks
#   / index_generations);Weaviate 永不作 UI 真相源(本读面零向量库访问);
# - 在服判定 = DocLifecycle.SERVING ∧ documents.current_version_id 可解析到
#   document_versions 行(与 active_generation_ordinals 同一权威关系);
# - 行只暴露权威存在的字段(title/url/source_id/lifecycle/chunk_count/
#   created_at/updated_at/superseded_*/deleted_at);不虚构 content-role、
#   discovered、last-seen;
# - 复合文档身份 ``<source_id>/<branch>/<rel_path>`` 含斜杠 → 单文档真相经
#   query 参数 ``doc_source_id`` 传递,规避 path 段斜杠编码歧义;
# - RBAC 与既有读约定一致:viewer 可读。
# --------------------------------------------------------------------------- #


def _escape_like(value: str) -> str:
    """LIKE 通配符转义(%/_/\\);配合 ``escape="\\")`` 使用。"""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _iso_or_none(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


async def _get_source_or_404(session: AsyncSession, source_id: str) -> DataSource:
    result = await session.execute(select(DataSource).where(DataSource.id == source_id))
    ds = result.scalar_one_or_none()
    if ds is None:
        raise HTTPException(status_code=404, detail="数据源不存在")
    return ds


def _document_scope(source_id: str):
    """源内文档范围(与 /sync-health document_count 同一 LIKE 前缀口径)。"""
    return Document.source_id.like(f"{_escape_like(source_id)}/%", escape="\\")


def _current_version_resolvable():
    """现行版本可解析谓词:current_version_id 非空且存在对应 document_versions 行。"""
    return Document.current_version_id.is_not(None) & select(
        DocumentVersion.id
    ).where(DocumentVersion.id == Document.current_version_id).exists()


def _bulk_repair_eligibility():
    """批量修复资格:只覆盖当前 attention 桶,不触碰健康或已退役文档。"""
    resolvable = _current_version_resolvable()
    return or_(
        Document.lifecycle.in_((DocLifecycle.MISSING_CANDIDATE, DocLifecycle.DISCOVERED)),
        (Document.lifecycle == DocLifecycle.ACTIVE) & ~resolvable,
    )


def _is_nowait_lock_conflict(exc: DBAPIError) -> bool:
    """识别 Postgres SELECT ... FOR UPDATE NOWAIT 的锁冲突。"""
    orig = getattr(exc, "orig", None)
    return str(getattr(orig, "sqlstate", "") or getattr(orig, "pgcode", "")) == "55P03"


@router.get("/{source_id}/documents", response_model=DataSourceDocumentsResponse)
async def list_source_documents(
    source_id: str,
    _: ViewerDep,
    request: Request,
    lifecycle: str | None = Query(default=None),
    # v1.6.3 B1 additive 只读参数(默认行为不变):
    # bucket = 运营桶投影(与冻结桶公式同定义);order = 排序(默认原行为);
    # source_type = documents.source_type 精确匹配。
    bucket: str | None = Query(default=None),
    order: str = Query(default="-updated_at", pattern="^(-updated_at|title)$"),
    source_type: str | None = Query(default=None),
    # v1.6.3 Track C(U-7):逐文档 content_type 精确匹配("none" = 不可用行)
    content_type: str | None = Query(default=None),
    search: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> DataSourceDocumentsResponse:
    """逐源文档清单(分页 + L 轴生命周期过滤 + title/url 子串搜索;只读)。

    聚合计数(lifecycle_counts / ledger_total / serving_count / current_count)
    为全源账本口径,不受本次过滤影响,供运营三桶(Current / Needs Attention /
    Retired)呈现。搜索不区分大小写,命中 title / url / 复合身份任一子串。

    v1.6.3 B1 additive 只读参数:
    - ``bucket``:运营桶投影。current = active ∧ 现行版本可解析;
      retired = superseded + deleted;attention = 其余(missing_candidate /
      discovered / active 悬挂)。与 attention-summary 聚合同一定义。
    - ``order``:``-updated_at``(默认,updated_at 倒序 nulls last,原行为)
      或 ``title``(title 升序)。
    - ``source_type``:documents.source_type 精确匹配。
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        await _get_source_or_404(session, source_id)
        if lifecycle is not None and lifecycle not in DocLifecycle.ALL:
            raise HTTPException(
                status_code=400,
                detail=f"非法 lifecycle 过滤值,可用词表: {', '.join(DocLifecycle.ALL)}",
            )
        if bucket is not None and bucket not in ("current", "attention", "retired"):
            raise HTTPException(
                status_code=400,
                detail="非法 bucket 过滤值,可用词表: current, attention, retired",
            )
        filters = [_document_scope(source_id)]
        if lifecycle is not None:
            filters.append(Document.lifecycle == lifecycle)
        if bucket is not None:
            resolvable_bucket = _current_version_resolvable()
            if bucket == "current":
                filters.append(
                    (Document.lifecycle == DocLifecycle.ACTIVE) & resolvable_bucket
                )
            elif bucket == "retired":
                filters.append(
                    Document.lifecycle.in_(
                        [DocLifecycle.SUPERSEDED, DocLifecycle.DELETED]
                    )
                )
            else:  # attention = 全集 − current − retired(同一冻结公式的行级投影)
                filters.append(
                    Document.lifecycle.in_(
                        [DocLifecycle.MISSING_CANDIDATE, DocLifecycle.DISCOVERED]
                    )
                    | (
                        (Document.lifecycle == DocLifecycle.ACTIVE)
                        & ~resolvable_bucket
                    )
                )
        if source_type is not None:
            filters.append(Document.source_type == source_type)
        if content_type is not None:
            if content_type == "none":
                filters.append(Document.content_type.is_(None))
            else:
                filters.append(Document.content_type == content_type)
        if search is not None and search.strip():
            term = f"%{_escape_like(search.strip())}%"
            filters.append(
                Document.title.ilike(term, escape="\\")
                | Document.url.ilike(term, escape="\\")
                | Document.source_id.ilike(term, escape="\\")
            )
        total = int(
            (
                await session.execute(
                    select(func.count()).select_from(Document).where(*filters)
                )
            ).scalar()
            or 0
        )
        # 全源账本聚合(不受过滤影响)
        lifecycle_rows = (
            await session.execute(
                select(Document.lifecycle, func.count())
                .where(_document_scope(source_id))
                .group_by(Document.lifecycle)
            )
        ).all()
        lifecycle_counts = {row[0]: int(row[1]) for row in lifecycle_rows}
        ledger_total = sum(lifecycle_counts.values())
        resolvable = _current_version_resolvable()
        serving_count = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(Document)
                    .where(
                        _document_scope(source_id),
                        Document.lifecycle.in_(DocLifecycle.SERVING),
                        resolvable,
                    )
                )
            ).scalar()
            or 0
        )
        current_count = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(Document)
                    .where(
                        _document_scope(source_id),
                        Document.lifecycle == DocLifecycle.ACTIVE,
                        resolvable,
                    )
                )
            ).scalar()
            or 0
        )
        # U-7:逐文档内容类型账本聚合(词表真实来源;NULL 不入计数)
        content_type_rows = (
            await session.execute(
                select(Document.content_type, func.count())
                .where(_document_scope(source_id), Document.content_type.is_not(None))
                .group_by(Document.content_type)
            )
        ).all()
        content_type_counts = {row[0]: int(row[1]) for row in content_type_rows if row[0]}
        rows = (
            (
                await session.execute(
                    select(Document)
                    .where(*filters)
                    .order_by(
                        Document.title.asc()
                        if order == "title"
                        else Document.updated_at.desc().nulls_last(),
                        Document.source_id,
                    )
                    .offset((page - 1) * size)
                    .limit(size)
                )
            )
            .scalars()
            .all()
        )
        version_by_id: dict[Any, DocumentVersion] = {}
        version_ids = [d.current_version_id for d in rows if d.current_version_id is not None]
        if version_ids:
            vrows = (
                (
                    await session.execute(
                        select(DocumentVersion).where(DocumentVersion.id.in_(version_ids))
                    )
                )
                .scalars()
                .all()
            )
            version_by_id = {v.id: v for v in vrows}
        items = [
            DataSourceDocumentItem(
                source_id=d.source_id,
                title=d.title,
                url=d.url,
                branch=d.branch,
                source_type=d.source_type,
                product=d.product,
                lifecycle=d.lifecycle,
                serving=(
                    d.lifecycle in DocLifecycle.SERVING
                    and d.current_version_id in version_by_id
                ),
                chunk_count=d.chunk_count,
                created_at=_iso_or_none(d.created_at),
                updated_at=_iso_or_none(d.updated_at),
                content_type=d.content_type,
                current_version_seq=(
                    version_by_id[d.current_version_id].version_seq
                    if d.current_version_id in version_by_id
                    else None
                ),
                generation_ordinal=(
                    version_by_id[d.current_version_id].generation_ordinal
                    if d.current_version_id in version_by_id
                    else None
                ),
            )
            for d in rows
        ]
    return DataSourceDocumentsResponse(
        source_id=source_id,
        total=total,
        ledger_total=ledger_total,
        page=page,
        size=size,
        lifecycle_counts=lifecycle_counts,
        serving_count=serving_count,
        current_count=current_count,
        content_type_counts=content_type_counts,
        items=items,
    )


# Issue #55:版本历史暴露上限(诚实截断;versions_truncated 标注,不静默)。
_INSPECTOR_VERSION_HISTORY_LIMIT = 20


def _inspector_citation_truth(doc: Document) -> DocumentCitationTruth:
    """Issue #55:引用与链接有效性真值(#48 既有权威派生,零第二真值)。

    复用检索序列化同一函数(``rag._derive_link_state``)与同一权威映射
    (``canonical_url.wiki_canonical_url``),输入全部来自账本权威列
    (documents.url / documents.metadata_ 的 frontmatter_slug 与
    visitor_reachability)。未记录 → 显式 None/unknown(零回填约束:
    unknown 不推断为 private,保持既有可点击语义)。
    """
    stored_url = doc.url or ""
    meta = doc.metadata_ or {}
    reachability = meta.get("visitor_reachability") or None
    if not stored_url.strip():
        # 知识案例语义:url='' → 显式 none,绝不伪造外部目的地。
        return DocumentCitationTruth(
            url=stored_url,
            citation_url=None,
            link_state=LINK_STATE_NONE,
            visitor_reachability=reachability,
        )
    citation_url = wiki_canonical_url(
        stored_url, frontmatter_slug=meta.get("frontmatter_slug") or None
    )
    return DocumentCitationTruth(
        url=stored_url,
        citation_url=citation_url,
        link_state=_derive_link_state(
            citation_url, stored_url, visitor_reachability=reachability or "unknown"
        ),
        visitor_reachability=reachability,
    )


def _inspector_commerce_truth(doc: Document) -> DocumentCommerceTruth | None:
    """Issue #28 / B1-4(集成义务 3):账本变体商业真值投影。

    单一接口词表:字段名与连接器 metadata / Weaviate COMMERCE_PROPS 同名;
    仅 woo 文档投影,且仅当账本行携带 commerce 标识(commerce_type 或
    product_id)——pre-migration / pre-resync 存量对象键缺失 → None
    (诚实缺席,绝不以空值伪装 0 价/缺货,契约 §4)。非 woo 文档恒 None。
    """
    if doc.source_type != "woocommerce":
        return None
    meta = doc.metadata_ or {}
    if not meta.get("commerce_type") and not meta.get("product_id"):
        return None

    def _str(key: str) -> str | None:
        value = meta.get(key)
        return str(value) if value is not None else None

    def _int(key: str) -> int | None:
        value = meta.get(key)
        return int(value) if value is not None else None

    def _bool(key: str) -> bool | None:
        value = meta.get(key)
        return bool(value) if value is not None else None

    attributes = meta.get("variation_attributes")
    return DocumentCommerceTruth(
        commerce_type=_str("commerce_type"),
        product_id=_int("product_id"),
        variation_id=_int("variation_id"),
        variation_identity_key=_str("variation_identity_key"),
        sku=_str("sku"),
        price=_str("price"),
        regular_price=_str("regular_price"),
        sale_price=_str("sale_price"),
        on_sale=_bool("on_sale"),
        stock_status=_str("stock_status"),
        stock_quantity=_int("stock_quantity"),
        purchasable=_bool("purchasable"),
        variation_attributes=(
            [str(a) for a in attributes] if isinstance(attributes, list) else None
        ),
        permalink=_str("permalink"),
        commerce_synced_at=_str("date_modified"),
    )


async def _inspector_version_history(
    session: AsyncSession, doc_source_id: str
) -> tuple[list[DocumentVersionHistoryEntry], bool]:
    """Issue #55:DocumentVersion 权威行降序展开(与现行版本同一权威关系)。"""
    rows = (
        (
            await session.execute(
                select(DocumentVersion)
                .where(DocumentVersion.source_id == doc_source_id)
                .order_by(DocumentVersion.version_seq.desc())
            )
        )
        .scalars()
        .all()
    )
    truncated = len(rows) > _INSPECTOR_VERSION_HISTORY_LIMIT
    entries = [
        DocumentVersionHistoryEntry(
            version_seq=v.version_seq,
            status=v.status,
            chunk_count=v.chunk_count,
            source_version=v.source_version,
            valid_from=_iso_or_none(v.valid_from),
            valid_to=_iso_or_none(v.valid_to),
            superseded_by_version_id=(
                str(v.superseded_by_version_id)
                if v.superseded_by_version_id is not None
                else None
            ),
            generation_ordinal=v.generation_ordinal,
        )
        for v in rows[:_INSPECTOR_VERSION_HISTORY_LIMIT]
    ]
    return entries, truncated


# --------------------------------------------------------------------------- #
# v1.6.4 Track A(A-6/A-2/A-3,#25):持久化退休决策与缺席确认的详情真相模型。
# 加性子类定义在本模块(读面所在;schemas.py 为冻结读模型文件,零改动)——
# None = 后端无该持久化事实(不推断、不编造,与 #50 只读真相面纪律一致)。
# --------------------------------------------------------------------------- #


class RetirementTruth(BaseModel):
    """持久化退休决策真相(documents.metadata_['retirement'] 投影)。

    reason/actor 为封闭词表(见 document_lifecycle 词表常量),evidence 为
    确认证据(确认计数/首缺时间/sync_run_id 等);gc_eligible_at = None 表示
    普通墓碑(物理 GC 走 opt-in 窗),非 None = 发现确认退休(A-2 + 7 天窗)。
    """

    reason: str
    actor: str | None = None
    evidence: dict | None = None
    retired_at: str | None = None
    gc_eligible_at: str | None = None


class AbsenceTruth(BaseModel):
    """缺席确认状态真相(documents.metadata_['absence'] 投影)。

    confirmations = 连续完整发现缺席计数(A-3:政策缺席恒 0 不计数);
    policy_reason 非空 = 范围外缺席(重包含可恢复),空 = 范围内缺席
    (两次连续 → RETIRED)。
    """

    confirmations: int = 0
    since: str | None = None
    policy_reason: str | None = None
    last_observed_at: str | None = None


class DataSourceDocumentTruthV25(DataSourceDocumentTruth):
    """#50 单文档真相的 Track A 加性投影(A-6/Acceptance 5;response_model)。

    组合树(94f2349 谱系):继承 #55 的身份/版本历史/引用真值字段,
    叠加 Track A 退休/缺席确认投影 —— 两面均为加性,零字段冲突。
    """

    retirement: RetirementTruth | None = None
    absence: AbsenceTruth | None = None


@router.get("/{source_id}/documents/detail", response_model=DataSourceDocumentTruthV25)
async def get_source_document_truth(
    source_id: str,
    _: ViewerDep,
    request: Request,
    doc_source_id: str = Query(..., description="复合文档身份 <source_id>/<branch>/<rel_path>"),
) -> DataSourceDocumentTruthV25:
    """单文档真相(状态 + 权威归属字段 + 现行版本/生成;只读)。

    - 文档行不存在 / 不属于本源 → 404 "后端无此记录"(显式缺席,不编造);
    - current_version / generation 为 null = 后端无该记录(前端显式呈现);
    - 不提供任何推断性原因,风险证据仅来自权威列(lifecycle /
      superseded_by / superseded_at / deleted_at / generation.failure)。
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        await _get_source_or_404(session, source_id)
        if not doc_source_id.startswith(f"{source_id}/"):
            raise HTTPException(status_code=404, detail="后端无此记录")
        doc = (
            await session.execute(select(Document).where(Document.source_id == doc_source_id))
        ).scalar_one_or_none()
        if doc is None:
            raise HTTPException(status_code=404, detail="后端无此记录")
        version: DocumentVersion | None = None
        if doc.current_version_id is not None:
            version = (
                await session.execute(
                    select(DocumentVersion).where(DocumentVersion.id == doc.current_version_id)
                )
            ).scalar_one_or_none()
        generation: IndexGeneration | None = None
        if version is not None:
            generation = (
                await session.execute(
                    select(IndexGeneration).where(IndexGeneration.id == version.generation_id)
                )
            ).scalar_one_or_none()
        chunks_total = 0
        if version is not None:
            chunks_total = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(DocumentVersionChunk)
                        .where(DocumentVersionChunk.version_id == version.id)
                    )
                ).scalar()
                or 0
            )
        serving = (
            doc.lifecycle in DocLifecycle.SERVING and version is not None
        )
        # ---- v1.6.3 Track C 加性真相(U-7/U-8/U-9/U-10)----
        chunk_serving_truth: ChunkServingTruth | None = None
        weaviate_client = getattr(request.app.state, "weaviate_client", None)
        if version is not None and weaviate_client is not None:
            # U-9:chunk 级 serving 投影(verify 口径);向量库不可用 → None
            # (前端诚实呈现「不可用」,绝不伪造 12/12)
            try:
                chunk_serving_truth = ChunkServingTruth(
                    **chunk_serving_for_doc(
                        weaviate_client,
                        request.app.state.weaviate_class_name,
                        doc.source_id,
                        chunks_total,
                    ).to_dict()
                )
            except Exception as exc:  # noqa: BLE001 - 不可用诚实降级
                logger.warning(
                    "chunk serving 投影不可用(%s): %s", doc.source_id, str(exc)[:120]
                )
        rec_failed, rec_succeeded = await recovery_counts(session, doc.source_id)
        versions_history, versions_truncated = await _inspector_version_history(
            session, doc.source_id
        )
        citation_truth = _inspector_citation_truth(doc)
        commerce_truth = _inspector_commerce_truth(doc)
        latest_task = (
            await session.execute(
                select(DocumentRepairTask)
                .where(DocumentRepairTask.doc_source_id == doc.source_id)
                .order_by(DocumentRepairTask.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        # v1.6.4 Track A(A-6/A-2/A-3,#25):持久化退休决策与缺席确认状态
        # 原样投影(权威 = documents.metadata_ 加性键;缺键 = None,不推断)。
        retirement_record = get_retirement_record(doc)
        absence_record = get_absence_state(doc)
        return DataSourceDocumentTruthV25(
            source_id=source_id,
            doc_source_id=doc.source_id,
            title=doc.title,
            url=doc.url,
            branch=doc.branch,
            source_type=doc.source_type,
            product=doc.product,
            lifecycle=doc.lifecycle,
            serving=serving,
            chunk_count=doc.chunk_count,
            content_type=doc.content_type,
            chunk_serving=chunk_serving_truth,
            retirement=(
                RetirementTruth(
                    reason=str(retirement_record.get("reason") or ""),
                    actor=retirement_record.get("actor"),
                    evidence=(
                        retirement_record.get("evidence")
                        if isinstance(retirement_record.get("evidence"), dict)
                        else None
                    ),
                    retired_at=retirement_record.get("retired_at"),
                    gc_eligible_at=retirement_record.get("gc_eligible_at"),
                )
                if retirement_record is not None
                else None
            ),
            absence=(
                AbsenceTruth(
                    confirmations=int(absence_record.get("confirmations") or 0),
                    since=absence_record.get("since"),
                    policy_reason=absence_record.get("policy_reason"),
                    last_observed_at=absence_record.get("last_observed_at"),
                )
                if absence_record is not None
                else None
            ),
            recovery_attempts_failed=rec_failed,
            recovery_attempts_succeeded=rec_succeeded,
            latest_repair_task=(
                DocumentRepairTaskOut(
                    id=str(latest_task.id),
                    source_id=latest_task.source_id,
                    doc_source_id=latest_task.doc_source_id,
                    status=latest_task.status,
                    stage=latest_task.stage,
                    requested_by=latest_task.requested_by,
                    idempotency_key=latest_task.idempotency_key,
                    result=latest_task.result,
                    error=latest_task.error,
                    events=latest_task.events or [],
                    created_at=_iso_or_none(latest_task.created_at),
                    finished_at=_iso_or_none(latest_task.finished_at),
                )
                if latest_task is not None
                else None
            ),
            created_at=_iso_or_none(doc.created_at),
            updated_at=_iso_or_none(doc.updated_at),
            superseded_by=doc.superseded_by,
            superseded_at=_iso_or_none(doc.superseded_at),
            deleted_at=_iso_or_none(doc.deleted_at),
            current_version=(
                DocumentCurrentVersionTruth(
                    id=str(version.id),
                    version_seq=version.version_seq,
                    status=version.status,
                    title=version.title,
                    url=version.url,
                    chunk_count=version.chunk_count,
                    chunks_total=chunks_total,
                    source_version=version.source_version,
                    valid_from=_iso_or_none(version.valid_from),
                    valid_to=_iso_or_none(version.valid_to),
                    superseded_by_version_id=(
                        str(version.superseded_by_version_id)
                        if version.superseded_by_version_id is not None
                        else None
                    ),
                    generation_id=str(version.generation_id),
                    generation_ordinal=version.generation_ordinal,
                )
                if version is not None
                else None
            ),
            generation=(
                DocumentGenerationTruth(
                    id=str(generation.id),
                    ordinal=generation.ordinal,
                    status=generation.status,
                    doc_count=generation.doc_count,
                    chunk_count=generation.chunk_count,
                    failure=generation.failure,
                    created_at=_iso_or_none(generation.created_at),
                    ready_at=_iso_or_none(generation.ready_at),
                    activated_at=_iso_or_none(generation.activated_at),
                    withdrawn_at=_iso_or_none(generation.withdrawn_at),
                    retired_at=_iso_or_none(generation.retired_at),
                    gc_eligible_at=_iso_or_none(generation.gc_eligible_at),
                    purged_at=_iso_or_none(generation.purged_at),
                )
                if generation is not None
                else None
            ),
            versions=versions_history,
            versions_truncated=versions_truncated,
            citation=citation_truth,
            commerce=commerce_truth,
        )


@router.get("/{source_id}/generations", response_model=DataSourceGenerationsResponse)
async def list_source_generations(
    source_id: str,
    _: ViewerDep,
    request: Request,
) -> DataSourceGenerationsResponse:
    """逐源索引生成列表(ordinal 倒序;失败证据原样;只读)。

    serving_ordinals = 权威在服代序集合(active_generation_ordinals 口径:
    documents.current_version_id ⋈ SERVING)的源内投影,用于"在服代"标记。
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        await _get_source_or_404(session, source_id)
        serving_rows = (
            await session.execute(
                select(DocumentVersion.generation_ordinal)
                .join(Document, Document.current_version_id == DocumentVersion.id)
                .where(
                    _document_scope(source_id),
                    Document.lifecycle.in_(DocLifecycle.SERVING),
                )
                .distinct()
            )
        ).scalars().all()
        gens = (
            (
                await session.execute(
                    select(IndexGeneration)
                    .where(IndexGeneration.source_id == source_id)
                    .order_by(IndexGeneration.ordinal.desc())
                )
            )
            .scalars()
            .all()
        )
        return DataSourceGenerationsResponse(
            source_id=source_id,
            total=len(gens),
            serving_ordinals=sorted(int(o) for o in serving_rows),
            items=[
                DocumentGenerationTruth(
                    id=str(g.id),
                    ordinal=g.ordinal,
                    status=g.status,
                    doc_count=g.doc_count,
                    chunk_count=g.chunk_count,
                    failure=g.failure,
                    created_at=_iso_or_none(g.created_at),
                    ready_at=_iso_or_none(g.ready_at),
                    activated_at=_iso_or_none(g.activated_at),
                    withdrawn_at=_iso_or_none(g.withdrawn_at),
                    retired_at=_iso_or_none(g.retired_at),
                    gc_eligible_at=_iso_or_none(g.gc_eligible_at),
                    purged_at=_iso_or_none(g.purged_at),
                )
                for g in gens
            ],
        )


# --------------------------------------------------------------------------- #
# v1.6.3 Track C 产品域(U-6..U-13 后端真值面;所有权 Track C)
#
# 合同(docs/engineering/tasks/v163-reference-remediation/track-c-contract.md):
# - U-11 调度真值:next_run_at 持久化权威(禁 sync_interval 纯派生倒计时);
# - U-8 行级修复:RBAC(EditorDep)/ 幂等(键 + 开放任务)/ 可审计(events)/
#   进度(stage)/ 结果(result)/ 修复后验证(chunk serving 投影复验);
# - U-12 知识设置:CURRENT/HISTORICAL 证据资格政策层 + 新鲜度政策(后端
#   权威、超期态 Admin 可见、检索资格消费政策真值);
# - U-13 高风险预览:影响计数服务端权威;确认施加与预览完全一致的
#   mutation;账本 drift → 409 失效(重算需重新预览)。
# --------------------------------------------------------------------------- #


@router.get("/{source_id}/schedule", response_model=SourceScheduleTruthOut)
async def get_source_schedule(
    source_id: str, _: ViewerDep, request: Request
) -> SourceScheduleTruthOut:
    """调度真值(U-11):reconcile 并返回权威 next_run_at 与调度现实状态。

    状态词表:scheduled(倒计时有效)/ syncing(进行中,无「下次」)/
    paused(禁用)/ waiting_first(从未同步)/ deleting(删除流程)。
    NULL 语义 = 调度现实不构成倒计时,前端诚实呈现对应状态。
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        ds = await _get_source_or_404(session, source_id)
        await schedule_truth_svc.reconcile_next_run_at(session, ds)
        inflight = await schedule_truth_svc.inflight_request_map(session, [source_id])
        state = schedule_truth_svc.schedule_state_of(ds, inflight.get(source_id, False))
        return SourceScheduleTruthOut(
            source_id=source_id,
            next_run_at=ds.next_run_at.isoformat() if ds.next_run_at else None,
            state=state,
            sync_interval=ds.sync_interval,
            enabled=bool(ds.enabled),
        )


def _task_out(task: DocumentRepairTask) -> DocumentRepairTaskOut:
    return DocumentRepairTaskOut(
        id=str(task.id),
        source_id=task.source_id,
        doc_source_id=task.doc_source_id,
        status=task.status,
        stage=task.stage,
        requested_by=task.requested_by,
        idempotency_key=task.idempotency_key,
        result=task.result,
        error=task.error,
        events=task.events or [],
        created_at=_iso_or_none(task.created_at),
        finished_at=_iso_or_none(task.finished_at),
    )


@router.post("/{source_id}/documents/repair-all", response_model=BulkDocumentRepairOut)
async def repair_all_source_documents(
    source_id: str, user: EditorDep, request: Request
) -> BulkDocumentRepairOut:
    """批量修复当前数据源的 attention 文档,返回逐项真实结果。

    资格与 ``/documents?bucket=attention`` 同源:missing_candidate/discovered
    或没有可解析现行版本的 active;healthy current 和 retired 永不入选。
    数据源行 ``FOR UPDATE NOWAIT`` 保证跨 worker 不重入,进程内锁覆盖 SQLite
    等不提供行锁的运行时。任务使用确定幂等键,重复请求不会制造重复执行记录。
    """
    lock = _BULK_REPAIR_LOCKS.setdefault(source_id, asyncio.Lock())
    if lock.locked():
        raise HTTPException(status_code=409, detail="该数据源已有批量修复正在执行")
    await lock.acquire()
    try:
        factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
        async with factory() as lock_session:
            try:
                source = (
                    await lock_session.execute(
                        select(DataSource)
                        .where(DataSource.id == source_id)
                        .with_for_update(nowait=True)
                    )
                ).scalar_one_or_none()
            except DBAPIError as exc:
                await lock_session.rollback()
                if _is_nowait_lock_conflict(exc):
                    raise HTTPException(
                        status_code=409, detail="该数据源已有批量修复正在执行"
                    ) from exc
                raise
            if source is None:
                raise HTTPException(status_code=404, detail="数据源不存在")

            docs = (
                (
                    await lock_session.execute(
                        select(Document)
                        .where(_document_scope(source_id), _bulk_repair_eligibility())
                        .order_by(Document.source_id)
                    )
                )
                .scalars()
                .all()
            )
            if not docs:
                return BulkDocumentRepairOut(
                    source_id=source_id, eligible=0, succeeded=0, failed=0, items=[]
                )

            # 依赖不可用时整体诚实返回 503;没有任何「成功」假象。
            weaviate_client, embedder = ensure_repair_stack(
                request.app.state, request.app.state.weaviate_class_name
            )
            requested_by = str(
                getattr(user, "username", None) or getattr(user, "id", None) or ""
            )
            items: list[BulkDocumentRepairItem] = []
            succeeded = 0
            rebuild_requested = 0
            for doc in docs:
                async with factory() as task_session:
                    task, _created = await create_repair_task(
                        task_session,
                        source_id,
                        doc.source_id,
                        requested_by=requested_by,
                        idempotency_key=f"bulk-repair-v1:{source_id}:{doc.source_id}",
                    )
                if task.status == "pending":
                    task = await execute_repair_task(
                        factory,
                        weaviate_client=weaviate_client,
                        embedder=embedder,
                        class_name=request.app.state.weaviate_class_name,
                        task_id=task.id,
                        # INC-WEB-EMBED-413:重放载荷嵌入契约预检(超契约路由
                        # 权威源重建交接,见 document_repair)
                        max_chunk_chars=getattr(
                            getattr(request.app.state, "settings", None),
                            "embedder_max_length",
                            None,
                        ),
                    )
                status = str(task.status)
                sync_request_id = (task.result or {}).get("sync_request_id")
                if status == "succeeded":
                    succeeded += 1
                elif status == "rebuild_requested":
                    rebuild_requested += 1
                items.append(
                    BulkDocumentRepairItem(
                        doc_source_id=doc.source_id,
                        status=status,
                        task_id=str(task.id) if task.id else None,
                        error=(task.error or ("已有修复任务正在执行" if status in {"pending", "running"} else None)),
                        sync_request_id=int(sync_request_id) if sync_request_id else None,
                    )
                )
            return BulkDocumentRepairOut(
                source_id=source_id,
                eligible=len(docs),
                succeeded=succeeded,
                failed=len(docs) - succeeded - rebuild_requested,
                rebuild_requested=rebuild_requested,
                items=items,
            )
    finally:
        lock.release()
        if not lock.locked() and _BULK_REPAIR_LOCKS.get(source_id) is lock:
            _BULK_REPAIR_LOCKS.pop(source_id, None)


@router.post("/{source_id}/documents/repair", response_model=DocumentRepairTaskOut)
async def repair_source_document(
    source_id: str, req: DocumentRepairRequest, user: EditorDep, request: Request
) -> DocumentRepairTaskOut:
    """行级修复命令(U-8):受理 + 执行 + 复验,任务/审计持久化。

    - RBAC:admin/editor(EditorDep;viewer 无修复授权);
    - 幂等:同 (doc, idempotency_key) 已有任务 → 原任务;同文档存在
      未完结任务 → 原任务;健康文档重复修复 = 真实复验 no-op;
    - 修复语义 = 持久 chunk 副本回放(gap-heal 同源),零源抓取;
    - 修复后验证:chunk serving 投影复验,serving/total 与一致性判定 =
      后端真值(验证卡数据源)。
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        await _get_source_or_404(session, source_id)
        task, _created = await create_repair_task(
            session,
            source_id,
            req.doc_source_id,
            requested_by=str(
                getattr(user, "username", None) or getattr(user, "id", None) or ""
            ),
            idempotency_key=req.idempotency_key,
        )
    task_id = task.id
    if task.status in ("pending",):
        # 依赖预检(诚实 503,绝不伪造修复);执行(plan→repair→verify)
        weaviate_client, embedder = ensure_repair_stack(
            request.app.state, request.app.state.weaviate_class_name
        )
        task = await execute_repair_task(
            factory,
            weaviate_client=weaviate_client,
            embedder=embedder,
            class_name=request.app.state.weaviate_class_name,
            task_id=task_id,
            # INC-WEB-EMBED-413:重放载荷嵌入契约预检(超限 fail-fast,不送 413)
            max_chunk_chars=getattr(
                getattr(request.app.state, "settings", None), "embedder_max_length", None
            ),
        )
    return _task_out(task)


@router.get("/{source_id}/documents/repair/{task_id}", response_model=DocumentRepairTaskOut)
async def get_repair_task(
    source_id: str, task_id: str, _: ViewerDep, request: Request
) -> DocumentRepairTaskOut:
    """修复任务进度/结果/审计查询(只读;viewer 可读,与详情一致)。"""
    from uuid import UUID as UUIDType

    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        await _get_source_or_404(session, source_id)
        try:
            tid = UUIDType(task_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="后端无此记录") from exc
        task = (
            await session.execute(
                select(DocumentRepairTask).where(
                    DocumentRepairTask.id == tid,
                    DocumentRepairTask.source_id == source_id,
                )
            )
        ).scalar_one_or_none()
        if task is None:
            raise HTTPException(status_code=404, detail="后端无此记录")
        return _task_out(task)


def _settings_out(session: AsyncSession, ds: DataSource) -> KnowledgeSettingsOut:
    return KnowledgeSettingsOut(
        source_id=ds.id,
        role=knowledge_policy.effective_role(ds),
        explicit_role=ds.knowledge_role,
        freshness_hours=knowledge_policy.effective_freshness_hours(ds),
        explicit_freshness_hours=ds.freshness_hours,
        freshness={},  # 由端点填充(异步真值)
        updated_at=_iso_or_none(ds.updated_at),
    )


@router.get("/{source_id}/knowledge-settings", response_model=KnowledgeSettingsOut)
async def get_knowledge_settings(
    source_id: str, _: ViewerDep, request: Request
) -> KnowledgeSettingsOut:
    """知识设置读面(U-12):生效政策 + 新鲜度真值(超期态 Admin 可见)。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        ds = await _get_source_or_404(session, source_id)
        out = _settings_out(session, ds)
        out.freshness = knowledge_policy.freshness_truth(
            ds, await knowledge_policy.last_success_at(session, source_id)
        )
        return out


@router.post("/{source_id}/knowledge-settings/preview", response_model=KnowledgePreviewResponse)
async def preview_knowledge_settings(
    source_id: str, req: KnowledgePreviewRequest, _: EditorDep, request: Request
) -> KnowledgePreviewResponse:
    """高风险变更影响预览(U-13):影响计数服务端权威 + 快照持久化。

    计数按当前账本权威计算(compute_policy_impact);token 为确认一致性锚
    (pending_policy + ledger_fingerprint 快照);drift → 确认时 409。
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        ds = await _get_source_or_404(session, source_id)
        pending_policy = {"role": req.role}
        if req.freshness_hours is not None:
            pending_policy["freshness_hours"] = req.freshness_hours
        counts = await knowledge_policy.policy_impact_counts(session, source_id)
        impact = knowledge_policy.compute_policy_impact(
            from_role=knowledge_policy.effective_role(ds),
            to_role=req.role,
            counts=counts,
        )
        fingerprint = await knowledge_policy.ledger_fingerprint(session, source_id)
        preview = await knowledge_policy.create_preview(
            session,
            source_id,
            pending_policy=pending_policy,
            impact=impact,
            fingerprint=fingerprint,
        )
        return KnowledgePreviewResponse(
            preview_token=str(preview.id),
            source_id=source_id,
            current_policy={
                "role": knowledge_policy.effective_role(ds),
                "freshness_hours": knowledge_policy.effective_freshness_hours(ds),
            },
            pending_policy=pending_policy,
            impact=impact,
            expires_at=_iso_or_none(preview.expires_at),
        )


@router.put("/{source_id}/knowledge-settings", response_model=KnowledgeSettingsOut)
async def update_knowledge_settings(
    source_id: str, req: KnowledgeSettingsUpdate, _: EditorDep, request: Request
) -> KnowledgeSettingsOut:
    """知识设置写入(U-12/U-13):确认一致性校验 → 施加与预览一致的 mutation。

    - 高风险变更(时态角色变化)必须携带有效 preview_token;
    - 校验:token 有效 / pending 策略与请求一致 / 账本指纹一致,
      任一不满足 → 409(预览失效,需重新预览);
    - 施加 = 角色/新鲜度政策列写入(政策层叠加,零 lifecycle 列语义改动);
    - 确认后服务状态重验:重算账本聚合与调度/新鲜度真值并快照回预览行。
    """
    from fastapi import HTTPException

    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    role_changed: bool
    async with factory() as session:
        ds = await _get_source_or_404(session, source_id)
        role_changed = knowledge_policy.effective_role(ds) != req.role
        pending_policy: dict = {"role": req.role}
        if req.freshness_hours is not None:
            pending_policy["freshness_hours"] = req.freshness_hours
        preview = None
        if role_changed:
            if not req.preview_token:
                raise HTTPException(
                    status_code=409,
                    detail="时态角色变更为高风险操作,必须先预览并携带 preview_token",
                )
            preview = await knowledge_policy.validate_confirm_token(
                session, source_id, req.preview_token, pending_policy
            )
        # ---- 施加 mutation(与预览一致;政策层加性列,零 lifecycle 改动)----
        ds.knowledge_role = req.role if req.role != knowledge_policy.ROLE_CURRENT else None
        ds.freshness_hours = req.freshness_hours
        await session.commit()
        # 确认后服务状态重验(真实重算:账本聚合 + 新鲜度 + 调度真值)
        counts = await knowledge_policy.policy_impact_counts(session, source_id)
        freshness = knowledge_policy.freshness_truth(
            ds, await knowledge_policy.last_success_at(session, source_id)
        )
        await schedule_truth_svc.reconcile_next_run_at(session, ds)
        if preview is not None:
            preview.status = "confirmed"
            preview.confirmed_at = datetime.now(UTC)
            preview.revalidation = {
                "revalidated_at": datetime.now(UTC).isoformat(),
                "ledger_counts": counts,
                "freshness": freshness,
                "retrieval_exclusion_applied": req.role == "historical",
            }
            await session.commit()
        out = _settings_out(session, ds)
        out.freshness = freshness
        return out
