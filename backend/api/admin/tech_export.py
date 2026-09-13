"""技术性能端点 —— 缺口对话导出与隐私(U-16;Ownership: Track E Wave 1)。

IF-6 拆分地图中的 tech_export.py(CSV 流式 + 审计)。冻结语义:
- **admin-only**(RBAC=require_role("admin");editor/viewer 403,未认证 401);
- **范围 = 所选 gap 的权威对话集**:真实查询 conversations.cluster_id
  (与队列/侧板同一权威归属真相,非当前渲染行);``window`` 参数继承队列
  激活窗词表(IF-7:7d/30d/all),只作用于 created_at 已知会话;
- **最小必要字段 + 排除直接个人身份**(IF-5 冻结,见 EXPORT_COLUMNS /
  PII_EXCLUDED_FIELDS;引用信息仅投影 title/url,内部 source_id 路径不外发);
- **真实 CSV 下载**(StreamingResponse;text/csv;UTF-8 BOM 兼容 Excel);
- **导出动作审计**(gap_export_audits 行,导出请求时落账,actor/范围/行数)。
"""

import csv
import io
import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import Conversation, GapExportAudit, QuestionCluster

# 子 router 无 prefix/tags:由 tech.py 的 tech_router(prefix="/tech",
# tags=["技术性能"])统一装配(同 tech_answer_gaps.py)。
router = APIRouter()

AdminDep = Annotated[CurrentUser, Depends(require_role("admin"))]

# IF-7 队列激活窗词表(导出范围继承;与 tech_answer_gaps 同一词表语义)。
EXPORT_WINDOWS = {"7d": 7, "30d": 30}

# ---- IF-5 冻结:CSV 列集(最小必要;顺序即契约) ----
EXPORT_COLUMNS: tuple[str, ...] = (
    "conversation_id",  # 会话 UUID(伪匿名标识,可回链审查面)
    "created_at",       # 发生时间(ISO-8601)
    "question",         # 用户问题
    "answer",           # 当前回答(上下文=问答对;widget 单轮语义)
    "is_answered",      # 是否已回答(true/false)
    "sources",          # 引用信息([{"title","url"}] JSON;最小投影)
)

# ---- IF-5 冻结:隐私排除清单(直接个人身份/身份可关联字段零包含) ----
# conversations 表上存在但绝不进入导出面的字段;IP/姓名/邮箱在本表本就不存,
# 清单同时作为「禁止将来加入」的契约边界。
PII_EXCLUDED_FIELDS: tuple[str, ...] = (
    "session_id",        # widget 匿名会话线程 ID(身份可关联)
    "country",           # 国家(地理位置,个人身份可关联)
    "channel",
    "intent_tag",
    "custom_tags",
    "customization_id",
    "site_id",
    "response_time_ms",
    "feedback",
    "gap_status",
    "override_answer",
)


def _project_sources(sources: Any) -> str:
    """引用信息最小投影:[{"title","url"}](剔除内部 source_id/chunk/score/text)。"""
    out: list[dict[str, str]] = []
    if isinstance(sources, list):
        for entry in sources:
            if not isinstance(entry, dict):
                continue
            title = entry.get("title")
            url = entry.get("url")
            if not title and not url:
                continue
            item: dict[str, str] = {}
            if isinstance(title, str):
                item["title"] = title
            if isinstance(url, str):
                item["url"] = url
            out.append(item)
    return json.dumps(out, ensure_ascii=False)


async def _iter_export_csv(
    factory: async_sessionmaker[AsyncSession], gap_id: str, window: str
) -> AsyncIterator[str]:
    """权威范围对话集 → CSV 行流(window 截止在查询内应用;时间升序)。"""
    # BOM:Excel 兼容(UTF-8 中文问答)
    yield "\ufeff"
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(EXPORT_COLUMNS)
    yield buf.getvalue()
    cutoff = None
    if window in EXPORT_WINDOWS:
        cutoff = datetime.now(UTC) - timedelta(days=EXPORT_WINDOWS[window])
    async with factory() as session:
        q = (
            select(Conversation)
            .where(Conversation.cluster_id == gap_id)
            .order_by(Conversation.created_at.asc(), Conversation.id.asc())
        )
        if cutoff is not None:
            q = q.where(Conversation.created_at >= cutoff)
        rows = await session.stream(q.execution_options(yield_per=50))
        async for row in rows:
            conv = row[0]
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(
                (
                    str(conv.id),
                    conv.created_at.isoformat() if conv.created_at else "",
                    conv.question or "",
                    (conv.answer or "").replace("\r", " ").replace("\n", " "),
                    "true" if conv.is_answered else "false",
                    _project_sources(conv.sources),
                )
            )
            yield buf.getvalue()


async def _get_gap_or_404(session: AsyncSession, gap_id: str) -> QuestionCluster:
    try:
        cid = uuid.UUID(gap_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail="answer gap not found") from e
    cluster = (
        await session.execute(
            select(QuestionCluster).where(
                QuestionCluster.id == cid, QuestionCluster.cluster_type == "gap"
            )
        )
    ).scalar_one_or_none()
    if cluster is None:
        raise HTTPException(status_code=404, detail="answer gap not found")
    return cluster


@router.get("/answer-gaps/{gap_id}/conversations/export")
async def export_gap_conversations(
    user: AdminDep,
    request: Request,
    gap_id: str,
    window: str = Query(default="all", pattern="^(7d|30d|all)$"),
) -> StreamingResponse:
    """导出所选 gap 的权威对话集(admin-only;真实 CSV 下载;动作可审计)。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        await _get_gap_or_404(session, gap_id)
        count_q = select(func.count()).select_from(Conversation).where(
            Conversation.cluster_id == gap_id
        )
        if window in EXPORT_WINDOWS:
            count_q = count_q.where(
                Conversation.created_at
                >= datetime.now(UTC) - timedelta(days=EXPORT_WINDOWS[window])
            )
        row_count = int((await session.execute(count_q)).scalar() or 0)
        # 审计行:导出动作落账(actor/范围/行数真值),先于流式响应
        session.add(
            GapExportAudit(
                cluster_id=uuid.UUID(gap_id),
                actor=user.email,
                actor_role=user.role,
                window=window,
                row_count=row_count,
            )
        )
        await session.commit()

    filename = f"gap-conversations-{gap_id[:8]}.csv"
    return StreamingResponse(
        _iter_export_csv(factory, gap_id, window),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/answer-gaps/{gap_id}/export-audits")
async def list_gap_export_audits(
    _: AdminDep,
    request: Request,
    gap_id: str,
) -> dict[str, Any]:
    """导出动作审计 trail(admin-only;时间降序)。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        await _get_gap_or_404(session, gap_id)
        rows = (
            (
                await session.execute(
                    select(GapExportAudit)
                    .where(GapExportAudit.cluster_id == uuid.UUID(gap_id))
                    .order_by(GapExportAudit.created_at.desc(), GapExportAudit.id.desc())
                )
            )
            .scalars()
            .all()
        )
        items = [
            {
                "id": str(a.id),
                "cluster_id": str(a.cluster_id),
                "actor": a.actor,
                "actor_role": a.actor_role,
                "window": a.window,
                "row_count": a.row_count,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in rows
        ]
    return {"items": items, "total": len(items)}
