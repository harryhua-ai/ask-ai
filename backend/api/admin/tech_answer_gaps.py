"""技术性能聚合端点 —— GET /tech/answer-gaps(+/{gap_id}/conversations)实现。

v1.6.3 B2 Answer Gaps 只读操作者投影(#59 / KB-OPS-V163-002 §5.2/§5.5/§10)。
Wave 0B 自 tech.py 拆出,逐字迁移,零语义变化。

Ownership(IF-6 附录,文件内区域互斥):
- 窗口参数面(window / ANSWER_GAP_WINDOWS / WINDOW_PATTERN)= **Track A**
  (BC-1 已落地:window 表达 IF-7 全冻结词表 today|7d|30d|all|
  range:YYYY-MM-DD/YYYY-MM-DD;既有 last_seen 未知保留 + total 真值语义不变;
  非法显式起止 422 fail-loud,禁静默回退);
- 分类/cause 挂载面(cause 参数、miss_type 投影、miss_type_summary)=
  **Track D**(Wave 1:词表经 backend/services/gap_taxonomy.py 挂载,
  禁止在本文件新增词表值);
- status 挂载面(status 参数)= **Track E**(Wave 1:IF-1 词表经
  backend/services/gap_status.py 挂载;本 Wave 零 observing 语义);
- 归属会话证据面(/{gap_id}/conversations)= S6 例外面冻结(gap 范围证据,
  无窗口参数;Wave 1 不得引入窗口假联动)。
"""

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import String, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.admin.analytics import classify_gap_miss_types
from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import Conversation, QuestionCluster
from backend.services.gap_status import GAP_STATUS_PATTERN
from backend.services.gap_taxonomy import GAP_MISS_UNCLASSIFIED

# 子 router 无 prefix/tags:由 tech.py 的 tech_router(prefix="/tech",
# tags=["技术性能"])统一装配,保证 OpenAPI 逐字节不变。
router = APIRouter()

ViewerDep = Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))]

# 时间窗词表(IF-7 全冻结词表,Track A BC-1):
# - 既有命名窗 7d/30d:语义逐字不变(now - N 天);
# - today:UTC 日历日 [当日 00:00, now](与共享分析窗状态解析一致);
# - range:YYYY-MM-DD/YYYY-MM-DD:显式起止(起日 00:00 起,结束日全天含);
# - all:不过滤(既有语义);
# last_seen 未知(无归属会话证据)不因窗口被排除(不可用 ≠ 窗口外,语义不变)。
ANSWER_GAP_WINDOWS = {"7d": 7, "30d": 30}
WINDOW_PATTERN = r"^(today|7d|30d|all|range:\d{4}-\d{2}-\d{2}/\d{4}-\d{2}-\d{2})$"


def _window_bounds(window: str) -> tuple[datetime | None, datetime | None]:
    """解析 window 参数 → (起界, 止界);None = 该侧不设界。

    非法显式起止(日历日期无效 / from 晚于 to)→ 422(fail loud,禁静默回退)。
    """
    if window in ANSWER_GAP_WINDOWS:
        return datetime.now(UTC) - timedelta(days=ANSWER_GAP_WINDOWS[window]), None
    if window == "today":
        now = datetime.now(UTC)
        return now.replace(hour=0, minute=0, second=0, microsecond=0), None
    if window == "all":
        return None, None
    if window.startswith("range:"):
        raw_from, raw_to = window[len("range:") :].split("/", 1)
        try:
            w_from = datetime.strptime(raw_from, "%Y-%m-%d").replace(tzinfo=UTC)
            w_to = (
                datetime.strptime(raw_to, "%Y-%m-%d").replace(tzinfo=UTC)
                + timedelta(days=1)
                - timedelta(microseconds=1)
            )
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="window 显式起止无效,需 range:YYYY-MM-DD/YYYY-MM-DD",
            )
        if w_from.date() > w_to.date():
            raise HTTPException(
                status_code=422, detail="window 显式起止无效:from 晚于 to"
            )
        return w_from, w_to
    return None, None


@router.get("/answer-gaps")
async def tech_answer_gaps(
    _: ViewerDep,
    request: Request,
    status: str | None = Query(default=None, pattern=GAP_STATUS_PATTERN),
    cause: str | None = Query(default=None, max_length=50),
    q: str | None = Query(default=None, max_length=200),
    window: str = Query(default="all", pattern=WINDOW_PATTERN),
    order: str = Query(default="last_seen", pattern="^(last_seen|questions|impacted)$"),
    dir: str = Query(default="desc", pattern="^(asc|desc)$"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=10, ge=1, le=100),
) -> dict[str, Any]:
    """答案缺口只读操作者队列(question_clusters + conversations 权威投影)。

    v1.6.3 B2 收敛契约(v163-b2-technical-insights-contract):
    - 只读投影,非新持久化 Knowledge Issue 模型;零 mutation 语义
      (无 OBSERVING/修复/导出/刷新)。
    - 每项字段全部权威可溯源:
        question_count        ← question_clusters.question_count(相关提问)
        impacted_answer_count ← COUNT(conversations WHERE cluster_id=…)(受影响回答)
        status                ← question_clusters.status(open|resolved 两态词表;
                                OBSERVING/观察中 v1.6.3 NOT authorized)
        miss_type/breakdown   ← classify_gap_miss_types(与 /analytics/coverage-gaps
                                同一权威分类 helper,单一真相源)
        last_seen_at          ← MAX(conversations.created_at);无会话 → None
                                (UI 必须呈现 证据不可用,不得伪装近期)
    - 时间窗过滤只作用于 last_seen 已知的聚类;未知时间不被窗口排除。
      窗词表 = IF-7 全冻结词表(Track A BC-1):today(UTC 日历日)/7d/30d/all/
      range:YYYY-MM-DD/YYYY-MM-DD(显式起止,结束日全天含;非法 → 422)。
    - 搜索 q 命中 代表问题 或 样例问句(问题/主题语义);不扫描会话全文。
    - 原因过滤(cause)依赖分类结果,故在分类后、排序/分页前应用;
      total 为过滤后真值。
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        last_seen_expr = func.max(Conversation.created_at)
        base = (
            select(
                QuestionCluster,
                func.count(Conversation.id).label("impacted_count"),
                last_seen_expr.label("last_seen"),
            )
            .outerjoin(
                Conversation, Conversation.cluster_id == func.cast(QuestionCluster.id, String)
            )
            .where(QuestionCluster.cluster_type == "gap")
            .group_by(QuestionCluster.id)
        )

        if status:
            base = base.where(QuestionCluster.status == status)
        if q:
            like = f"%{q}%"
            base = base.where(
                func.coalesce(QuestionCluster.representative_question, "").ilike(like)
                | func.coalesce(func.cast(QuestionCluster.sample_questions, String), "").ilike(
                    like
                )
            )

        # 时间窗(IF-7 全词表):只约束已知 last_seen;NULL(时间不可用)始终保留;
        # total 为过滤后真值(既有语义不变)。
        w_from, w_to = _window_bounds(window)
        if w_from is not None or w_to is not None:
            cond = last_seen_expr.is_(None)
            if w_from is not None:
                cond = cond | (last_seen_expr >= w_from)
            if w_to is not None:
                cond = cond & (last_seen_expr.is_(None) | (last_seen_expr <= w_to))
            base = base.having(cond)

        rows = (await session.execute(base)).all()

        # 原因分类:与 /analytics/coverage-gaps 共用同一权威 helper(单一真相源)。
        # 同会话内完成,避免跨会话管理。
        miss_type_map, breakdown_map = await classify_gap_miss_types(
            session, [str(row.QuestionCluster.id) for row in rows]
        )

        # 可用性真值(#59 G1/C2 只读投影):全量缺口聚类计数与分类聚合覆盖上界
        # MAX(period_end),均来自既有 QuestionCluster 列,忽略筛选与窗口 ——
        # 空队列时 UI 据此区分「无聚类证据/证据未覆盖当前窗」与真实零态,
        # 不制造零、不发明刷新溯源(不区分「从未聚类」与「聚类零缺口」);
        # 零新表零新端点。
        gap_clusters_total, covered_through = (
            await session.execute(
                select(func.count(), func.max(QuestionCluster.period_end))
                .select_from(QuestionCluster)
                .where(QuestionCluster.cluster_type == "gap")
            )
        ).one()

    items: list[dict[str, Any]] = []
    for row in rows:
        c = row.QuestionCluster
        cid = str(c.id)
        miss_type = miss_type_map.get(cid, GAP_MISS_UNCLASSIFIED)
        if cause and miss_type != cause:
            continue
        last_seen = row.last_seen
        items.append(
            {
                "id": cid,
                "cluster_type": "gap",
                "representative_question": c.representative_question,
                "sample_questions": c.sample_questions or [],
                "question_count": c.question_count,
                "impacted_answer_count": int(row.impacted_count or 0),
                "status": c.status,
                "miss_type": miss_type,
                "miss_type_breakdown": breakdown_map.get(cid, {}),
                "last_seen_at": last_seen.isoformat() if last_seen else None,
                "period_start": c.period_start.isoformat() if c.period_start else None,
                "period_end": c.period_end.isoformat() if c.period_end else None,
                "created_at": c.created_at.isoformat() if c.created_at else "",
            }
        )

    # 排序(内存内,行数=聚类数,量级安全):默认最近发生优先,未知时间垫底
    reverse = dir == "desc"
    if order == "questions":
        items.sort(key=lambda it: it["question_count"], reverse=reverse)
    elif order == "impacted":
        items.sort(key=lambda it: it["impacted_answer_count"], reverse=reverse)
    else:
        with_seen = sorted(
            (it for it in items if it["last_seen_at"]),
            key=lambda it: it["last_seen_at"],
            reverse=reverse,
        )
        items = with_seen + [it for it in items if not it["last_seen_at"]]

    total = len(items)
    miss_type_summary: Counter[str] = Counter(it["miss_type"] for it in items)
    start = (page - 1) * size
    return {
        "items": items[start : start + size],
        "total": total,
        "page": page,
        "size": size,
        "miss_type_summary": dict(miss_type_summary),
        "availability": {
            "gap_clusters_total": int(gap_clusters_total or 0),
            "classification_covered_through": (
                covered_through.isoformat() if covered_through else None
            ),
        },
    }


@router.get("/answer-gaps/{gap_id}/conversations")
async def tech_answer_gap_conversations(
    _: ViewerDep,
    request: Request,
    gap_id: str,
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """缺口归属会话证据(诊断侧板「相关对话」只读投影)。

    证据面:conversation.question / is_answered / created_at,最近在前。
    深链下钻语义由前端 /conversations?q= 承担(冻结参数语法,#51 B2)。
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        cluster = (
            await session.execute(
                select(QuestionCluster).where(
                    QuestionCluster.id == gap_id,
                    QuestionCluster.cluster_type == "gap",
                )
            )
        ).scalar_one_or_none()
        if cluster is None:
            raise HTTPException(status_code=404, detail="answer gap not found")

        total = (
            await session.execute(
                select(func.count())
                .select_from(Conversation)
                .where(Conversation.cluster_id == gap_id)
            )
        ).scalar() or 0
        rows = (
            (
                await session.execute(
                    select(Conversation)
                    .where(Conversation.cluster_id == gap_id)
                    .order_by(Conversation.created_at.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )

    return {
        "items": [
            {
                "id": str(r.id),
                "question": r.question,
                "is_answered": bool(r.is_answered),
                "created_at": r.created_at.isoformat() if r.created_at else "",
            }
            for r in rows
        ],
        "total": int(total),
    }
