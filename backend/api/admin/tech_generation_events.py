"""技术性能聚合端点 —— GET /tech/generation-events 实现(Wave 0B 自 tech.py 拆出)。

Ownership: Integration(Wave 0B 落位);S4 生成级事件流 = §3.5 能力矩阵
例外面(冻结:无窗口参数,latest-N 终态流;Wave 1 不得借例外引入窗口假联动)。
#51 B2 事件信号区唯一新增读面,所有权归 #51。
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import IndexGeneration

# 子 router 无 prefix/tags:由 tech.py 的 tech_router(prefix="/tech",
# tags=["技术性能"])统一装配,保证 OpenAPI 逐字节不变。
router = APIRouter()

ViewerDep = Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))]

# P 轴事件词表:failed=构建/验证失败(严重);retired=服务撤出(常规生命周期)。
# pending/processing/ready 是处理态而非事件,不进入信号区。
GENERATION_EVENT_STATUSES = ("failed", "retired")

# 严重度机器词表(failed=error / retired=info);运营标签映射由前端 B2
# 自有模块(admin/src/lib/generationStatus.ts)承担,后端不重复语义。
GENERATION_EVENT_SEVERITY = {"failed": "error", "retired": "info"}


def _generation_reason_summary(row: IndexGeneration) -> str | None:
    """原因摘要:failure JSONB 自带 error 摘要优先;否则按状态给事实性描述。

    纪律:绝不虚构证据 —— failure 缺 error 键时只描述状态本身可证明的事实
    (构建/验证失败,构建 N 文档 / M chunk 后未激活),不猜测根因。
    """
    failure = row.failure or {}
    err = failure.get("error")
    if isinstance(err, str) and err:
        return err
    if row.status == "failed":
        return (
            f"索引生成构建/验证失败(构建 {row.doc_count} 文档 / "
            f"{row.chunk_count} chunk 后未激活)"
        )
    return "知识已从在服集撤出(被新一代接替)"


@router.get("/generation-events")
async def tech_generation_events(
    _: ViewerDep,
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """最近索引生成级事件(failed/retired;#51 B2 事件信号区唯一新增读面)。

    复用优先裁定(v162-i51 contract):同步级事件已由既有 GET /sync-runs
    权威表达(前端跨源消费,零新增后端);生成级事件
    (index_generations.status/failure)无既有读端点,故本端点只读补齐,
    所有权归 #51,不复制 #50 逐源清单。

    event_at 事实派生:retired → retired_at(撤出时刻);failed →
    updated_at(无 failed_at 列,最后一次状态变更即失败时刻的诚实近似;
    failure JSONB 保留原始证据)。排序 = event_at 倒序(最近在前)。
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    event_at_expr = func.coalesce(
        IndexGeneration.retired_at, IndexGeneration.updated_at
    )
    async with factory() as session:
        total = (
            await session.execute(
                select(func.count())
                .select_from(IndexGeneration)
                .where(IndexGeneration.status.in_(GENERATION_EVENT_STATUSES))
            )
        ).scalar() or 0
        rows = (
            (
                await session.execute(
                    select(IndexGeneration)
                    .where(IndexGeneration.status.in_(GENERATION_EVENT_STATUSES))
                    .order_by(event_at_expr.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )

    items = [
        {
            "generation_id": str(row.id),
            "ordinal": row.ordinal,
            "source_id": row.source_id,
            "status": row.status,
            "severity": GENERATION_EVENT_SEVERITY.get(row.status, "info"),
            "doc_count": row.doc_count,
            "chunk_count": row.chunk_count,
            "failure": row.failure,
            "reason_summary": _generation_reason_summary(row),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "activated_at": row.activated_at.isoformat() if row.activated_at else None,
            "retired_at": row.retired_at.isoformat() if row.retired_at else None,
            "event_at": (
                (row.retired_at or row.updated_at).isoformat()
                if (row.retired_at or row.updated_at)
                else None
            ),
        }
        for row in rows
    ]
    return {"items": items, "total": int(total)}
