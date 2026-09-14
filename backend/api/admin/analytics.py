"""Analytics API:Coverage Gaps + Top Questions + Source Analytics。

提供:
- GET    /coverage-gaps           查询未回答问题聚类(viewer+)
- POST   /coverage-gaps/refresh   触发重新聚类(admin/editor)
- PATCH  /gaps/{cluster_id}/resolve  标记 gap 状态(admin/editor)
- GET    /top-questions           查询全部问题聚类(viewer+)
- POST   /top-questions/refresh   触发重新聚类(admin/editor)
- GET    /sources                 来源点击/引用聚合(viewer+)
- GET    /gap-trends              缺口趋势(按天未回答率)(viewer+)
- GET    /source-health           数据源健康度(viewer+)
"""

import re
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.api.admin.schemas import (
    AnalyticsRefreshResult,
    QuestionClusterList,
    QuestionClusterOut,
    SourceAnalyticsList,
)
from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import (
    Conversation,
    DataSource,
    Document,
    QuestionCluster,
    SourceClick,
    SyncLog,
    Trace,
)
from backend.services.document_lifecycle import DocLifecycle
from backend.services.gap_status import GAP_STATUS_PATTERN
from backend.services.gap_taxonomy import (
    GAP_MISS_UNCLASSIFIED,
    CitedDocEvidence,
    classify_conversation_miss_type,
    extract_cited_source_ids,
)

router = APIRouter(prefix="/analytics", tags=["分析仪表盘"])
ViewerDep = Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))]
EditorDep = Annotated[CurrentUser, Depends(require_role("admin", "editor"))]


def _to_cluster_out(c: QuestionCluster, miss_type: str | None = None) -> dict[str, Any]:
    """将 QuestionCluster ORM 对象转换为 API 输出字典。"""
    out = {
        "id": str(c.id),
        "cluster_type": c.cluster_type,
        "representative_question": c.representative_question,
        "sample_questions": c.sample_questions or [],
        "question_count": c.question_count,
        "status": c.status,
        "period_start": c.period_start.isoformat() if c.period_start else None,
        "period_end": c.period_end.isoformat() if c.period_end else None,
        "created_at": c.created_at.isoformat() if c.created_at else "",
    }
    if miss_type is not None:
        out["miss_type"] = miss_type
    return out


# ----------------------------------------------------------------------- #
# Coverage Gaps
# ----------------------------------------------------------------------- #


async def classify_gap_miss_types(
    session: AsyncSession, cluster_ids: list[str]
) -> tuple[dict[str, str], dict[str, dict[str, int]]]:
    """对给定 gap 聚类批量计算权威 miss_type 分类(v1.6.3 B2 提取共享)。

    分类语义(唯一权威来源,消费方必须同源;单会话证据规则 =
    backend/services/gap_taxonomy.py:classify_conversation_miss_type,IF-2):
    - 既有 4 类(语义逐字不变;无新类证据时原判不变):
      reject:is_answered=False(拒答,用户未获回答)
      low:answered, sources 非空, 最新 trace confidence<0.6(低相关)
      召回空:answered, sources 空(已回答但未检索到任何知识来源)
      召回不足:answered, sources 非空, confidence>=0.6 或无 trace
    - U-14 六新类(每类=后端确定性证据规则,参考词表 TI-09):
      生成异常=Trace.type=generation_error(generation failure 真相,PC-06);
      内容缺失=未回答+零来源+检索零候选(知识缺失变体);
      引用异常=answered+sources 非空+答案引用编号越界(引用一致性违例);
      内容冲突=同会话同时引用 superseded 文档与其接替者(多源冲突真相);
      内容过期=所引文档内容更新早于会话超过 180 天(内容时间真相);
      检索异常=answered+sources 非空+检索未达最低有效召回(检索异常证据)。
      优先级与冻结细节见 gap_taxonomy 模块 docstring。

    返回 (miss_type_map: cluster_id → 主导分类, breakdown: cluster_id → 各分类计数)。
    主导 = 聚类内会话计数最多的分类;无任何会话证据 → 未分类。
    v1.6.3 B2:/tech/answer-gaps 只读投影复用本 helper,保证原因分类单一权威。
    """
    miss_type_map: dict[str, str] = {}
    breakdown: dict[str, dict[str, int]] = {}
    if not cluster_ids:
        return miss_type_map, breakdown

    conv_q = select(
        Conversation.cluster_id,
        Conversation.sources,
        Conversation.is_answered,
        Conversation.id,
        Conversation.answer,
        Conversation.created_at,
    ).where(Conversation.cluster_id.in_(cluster_ids))
    conv_rows = (await session.execute(conv_q)).all()

    # 批量查最新 trace 证据快照(turn_index 最大;confidence/type/stages 同行)
    conv_ids = [str(row.id) for row in conv_rows]
    trace_map: dict[str, tuple[float | None, str | None, Any]] = {}
    if conv_ids:
        trace_q = (
            select(
                Trace.conversation_id,
                Trace.confidence,
                Trace.turn_index,
                Trace.type,
                Trace.stages,
            )
            .where(Trace.conversation_id.in_(conv_ids))
            .order_by(Trace.turn_index.desc())
        )
        for row in (await session.execute(trace_q)).all():
            cid = str(row.conversation_id)
            if cid not in trace_map:
                trace_map[cid] = (row.confidence, row.type, row.stages)

    # 批量查被引用第一方文档证据(documents:内容时间/接替者 → 内容过期/内容冲突)
    cited_ids: set[str] = set()
    for row in conv_rows:
        cited_ids.update(extract_cited_source_ids(row.sources))
    doc_map: dict[str, CitedDocEvidence] = {}
    if cited_ids:
        doc_q = select(
            Document.source_id, Document.updated_at, Document.superseded_by
        ).where(Document.source_id.in_(cited_ids))
        for row in (await session.execute(doc_q)).all():
            doc_map[row.source_id] = CitedDocEvidence(
                updated_at=row.updated_at, superseded_by=row.superseded_by
            )

    cluster_stats: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in conv_rows:
        cid = str(row.cluster_id) if row.cluster_id else ""
        conf, trace_type, trace_stages = trace_map.get(
            str(row.id), (None, None, None)
        )
        miss = classify_conversation_miss_type(
            is_answered=bool(row.is_answered),
            sources=row.sources,
            answer=row.answer,
            trace_type=trace_type,
            trace_stages=trace_stages,
            trace_confidence=conf,
            cited_docs=doc_map,
            conversation_at=row.created_at,
        )
        cluster_stats[cid][miss] += 1
    for cid, stats in cluster_stats.items():
        dominant = max(stats, key=stats.get) if stats else GAP_MISS_UNCLASSIFIED
        miss_type_map[cid] = dominant
        breakdown[cid] = dict(stats)
    return miss_type_map, breakdown


@router.get("/coverage-gaps", response_model=QuestionClusterList)
async def list_coverage_gaps(
    _: ViewerDep,
    request: Request,
    status: str | None = Query(default=None, pattern=GAP_STATUS_PATTERN),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """查询 Coverage Gaps 聚类列表(viewer+ 可访问)。

    每个 gap 附 miss_type 分类:召回空(sources 为空)/ 召回不足(sources 非空但仍未回答)。
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        q = select(QuestionCluster).where(QuestionCluster.cluster_type == "gap")
        count_q = (
            select(func.count())
            .select_from(QuestionCluster)
            .where(QuestionCluster.cluster_type == "gap")
        )
        if status:
            q = q.where(QuestionCluster.status == status)
            count_q = count_q.where(QuestionCluster.status == status)

        total = (await session.execute(count_q)).scalar() or 0
        result = await session.execute(
            q.order_by(QuestionCluster.question_count.desc()).offset((page - 1) * size).limit(size)
        )
        clusters = result.scalars().all()

        miss_type_map, _breakdown = await classify_gap_miss_types(
            session, [str(c.id) for c in clusters]
        )
        miss_type_summary: dict[str, int] = defaultdict(int)
        for dominant in miss_type_map.values():
            miss_type_summary[dominant] += 1

    items = [
        _to_cluster_out(c, miss_type_map.get(str(c.id), GAP_MISS_UNCLASSIFIED))
        for c in clusters
    ]
    return {
        "items": items,
        "total": total,
        "page": page,
        "size": size,
        "miss_type_summary": dict(miss_type_summary),
    }


@router.post("/coverage-gaps/refresh", response_model=AnalyticsRefreshResult)
async def refresh_coverage_gaps(
    _: EditorDep,
    request: Request,
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
) -> dict[str, Any]:
    """重新聚类未回答问题(admin/editor)。"""
    clustering = request.app.state.clustering
    try:
        df = datetime.fromisoformat(date_from) if date_from else None
        dt = datetime.fromisoformat(date_to) if date_to else None
    except ValueError:
        raise HTTPException(status_code=422, detail="date_from/date_to 格式无效,需 ISO 8601")
    results = await clustering.cluster("gap", df, dt)

    return {
        "cluster_count": len(results),
        "total_questions": sum(r.question_count for r in results),
    }


@router.patch("/gaps/{cluster_id}/resolve", response_model=QuestionClusterOut)
async def resolve_gap(
    cluster_id: uuid.UUID,
    body: dict,
    _: EditorDep,
    request: Request,
) -> dict[str, Any]:
    """标记 gap 为 resolved/open(admin/editor)。"""
    new_status = body.get("status", "resolved")
    if new_status not in ("open", "resolved"):
        raise HTTPException(status_code=422, detail="status 必须为 open 或 resolved")

    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        cluster = await session.execute(
            select(QuestionCluster).where(QuestionCluster.id == cluster_id)
        )
        cluster = cluster.scalar_one_or_none()
        if cluster is None:
            raise HTTPException(status_code=404, detail="聚类不存在")
        cluster.status = new_status
        await session.commit()
        await session.refresh(cluster)

    return _to_cluster_out(cluster)


# ----------------------------------------------------------------------- #
# Top Questions
# ----------------------------------------------------------------------- #


@router.get("/top-questions", response_model=QuestionClusterList)
async def list_top_questions(
    _: ViewerDep,
    request: Request,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """查询 Top Questions 聚类列表(viewer+ 可访问)。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        count_q = (
            select(func.count())
            .select_from(QuestionCluster)
            .where(QuestionCluster.cluster_type == "top")
        )
        total = (await session.execute(count_q)).scalar() or 0
        result = await session.execute(
            select(QuestionCluster)
            .where(QuestionCluster.cluster_type == "top")
            .order_by(QuestionCluster.question_count.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
        clusters = result.scalars().all()

    return {
        "items": [_to_cluster_out(c) for c in clusters],
        "total": total,
        "page": page,
        "size": size,
    }


@router.post("/top-questions/refresh", response_model=AnalyticsRefreshResult)
async def refresh_top_questions(
    _: EditorDep,
    request: Request,
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
) -> dict[str, Any]:
    """重新聚类全部问题(admin/editor)。"""
    clustering = request.app.state.clustering
    try:
        df = datetime.fromisoformat(date_from) if date_from else None
        dt = datetime.fromisoformat(date_to) if date_to else None
    except ValueError:
        raise HTTPException(status_code=422, detail="date_from/date_to 格式无效,需 ISO 8601")
    results = await clustering.cluster("top", df, dt)

    return {
        "cluster_count": len(results),
        "total_questions": sum(r.question_count for r in results),
    }


# ----------------------------------------------------------------------- #
# Source Analytics
# ----------------------------------------------------------------------- #


@router.get("/sources", response_model=SourceAnalyticsList)
async def source_analytics(
    _: ViewerDep,
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """来源分析:source_clicks 按 URL 聚合(viewer+ 可访问)。

    仅聚合 source_clicks 表的点击数,按 URL 分组返回 top N。
    references 字段为预留占位(后续接入 conversations.sources 聚合)。
    时间窗口使用 timedelta 参数化,避免 SQL 注入。
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        clicks_result = await session.execute(
            select(
                SourceClick.source_url,
                SourceClick.source_type,
                SourceClick.product,
                func.count(SourceClick.id).label("clicks"),
            )
            .where(SourceClick.clicked_at >= func.now() - timedelta(days=days))
            .group_by(SourceClick.source_url, SourceClick.source_type, SourceClick.product)
            .order_by(func.count(SourceClick.id).desc())
            .limit(limit)
        )
        click_rows = clicks_result.all()

    return {
        "items": [
            {
                "url": row.source_url,
                "source_type": row.source_type,
                "product": row.product,
                "clicks": row.clicks,
                "references": 0,
            }
            for row in click_rows
        ],
        "days": days,
    }


# ----------------------------------------------------------------------- #
# Gap Trends — 按天未回答率时序
# ----------------------------------------------------------------------- #


@router.get("/gap-trends")
async def gap_trends(
    _: ViewerDep,
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
) -> dict[str, Any]:
    """缺口趋势:按天聚合对话总量与未回答数(viewer+ 可访问)。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    end = datetime.now(UTC)
    start = end - timedelta(days=days)

    async with factory() as session:
        q = (
            select(
                func.date_trunc("day", Conversation.created_at).label("day"),
                func.count().label("total"),
                func.count().filter(Conversation.is_answered.is_(False)).label("unanswered"),
            )
            .where(Conversation.created_at >= start, Conversation.created_at <= end)
            .group_by("day")
            .order_by("day")
        )
        rows = (await session.execute(q)).all()

    trends = [
        {
            "date": row.day.strftime("%m-%d") if row.day else "",
            "total": row.total,
            "unanswered": row.unanswered,
            "unanswered_rate": round(row.unanswered / row.total, 4) if row.total else 0.0,
        }
        for row in rows
    ]
    return {"trends": trends}


# ----------------------------------------------------------------------- #
# Source Health — 数据源健康度
# ----------------------------------------------------------------------- #

# DSH-01:可靠性结论的最小样本数。窗口内同步次数低于该值时不给
# healthy/degraded/critical 结论(health="insufficient_data"),避免
# 用 1~2 次运行伪造 100% 或 0% 的可靠性印象。
MIN_SYNC_RUNS = 3

# BC-2(Track A,IF-7 全冻结词表的显式起止/all 表达):from/to 为可选窗参数;
# 既有 days 形态语义逐字保留(days 形态响应形状零变化,不新增 window 字段)。
_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_window_bound(value: str, name: str, *, end_of_day: bool) -> datetime:
    """解析显式窗界(YYYY-MM-DD 或 ISO 日期时间)→ aware UTC datetime。

    - YYYY-MM-DD:起界=当日 00:00 UTC;止界(end_of_day)=当日 23:59:59.999999
      UTC(结束日全天含,与 /tech/answer-gaps range: 显式起止口径一致);
    - ISO 日期时间:naive 视为 UTC(与 /tech/performance from/to 既有语义一致),
      aware 转换为 UTC;
    - 非法格式 → 422(fail loud,禁静默回退)。
    """
    raw = value.strip()
    try:
        if _DATE_ONLY_RE.fullmatch(raw):
            dt = datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=UTC)
            if end_of_day:
                dt = dt + timedelta(days=1) - timedelta(microseconds=1)
            return dt
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise HTTPException(
            status_code=422, detail=f"{name} 需 ISO 8601 日期(YYYY-MM-DD 或日期时间)"
        )
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


@router.get("/source-health")
async def source_health(
    _: ViewerDep,
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    date_from: str | None = Query(default=None, alias="from"),
    date_to: str | None = Query(default=None, alias="to"),
) -> dict[str, Any]:
    """数据源健康度:当前态(最近一次同步)+ 历史可靠性(窗口内成功率)。

    评估窗(Track A BC-2,IF-7 显式起止/all 参数能力):
    - days 形态(既有,语义逐字不变):[now-days, …] 内 sync_log;
    - 显式起止形态:from/to 必须同时提供(缺一 422,禁半开窗),评估窗 =
      [from, to](日期形态结束日全天含);全部时间 = from 给远早锚点表达;
      非法/倒挂窗 → 422;响应新增 ``window: {from, to}`` 权威回显
      (=实际评估窗)与 ``days`` = 含首尾天数;window_days 同步为该值。
      days 形态响应形状零变化(不出现 window 字段)。

    语义(DSH-01,产品契约"当前 vs 历史"显式化;#21 矫正补充):
    - 历史可靠性 = 评估窗内 ``sync_log`` 中 ``status=success`` 的占比。
      ``partial``(一致性校验自愈)计入分母、不计入成功数——与 T28 数学口径
      一致,但分子/分母/窗口全部显式返回(window_days / success_syncs /
      partial_syncs / failed_syncs),不再出现无法解释的裸百分比。
    - ``health`` 是**历史窗口可靠性**结论,不是当前知识健康判定:
        disabled          数据源已禁用(禁用 ≠ 不健康,不作可靠性评价);
        insufficient_data 启用但窗口内同步次数 < MIN_SYNC_RUNS,样本不足;
        healthy / degraded / critical  既有阈值不变(≥0.9 / ≥0.5 / <0.5)。
      每条 item 附 ``signal: "historical_reliability"`` 显式标注该语义类,
      消费方(Admin)必须以历史可靠性呈现,不得当作当前 Severe/需处理。
      当前知识健康唯一权威 = ``GET /sync-health``(W2 五维,读时派生)。
    - 当前态单独透出:last_sync / last_sync_status / last_sync_error
      (全部时间范围内最近一次尝试,与 /data-sources 列表同口径),
      供 UI 并排展示"现在有没有问题" vs "过去稳不稳定"。
    - 列表以 data_sources 全表驱动(从未同步的源也出现,零历史不缺席),
      sync_log 中有而 data_sources 无的幽灵行保持可见(product=unknown)。
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory

    if (date_from is None) != (date_to is None):
        raise HTTPException(
            status_code=422, detail="from/to 必须同时提供(显式起止评估窗)"
        )

    window_echo: dict[str, str] | None = None
    window_end: datetime | None = None
    if date_from is not None and date_to is not None:
        window_start = _parse_window_bound(date_from, "from", end_of_day=False)
        window_end = _parse_window_bound(date_to, "to", end_of_day=True)
        if window_start > window_end:
            raise HTTPException(status_code=422, detail="from 晚于 to(评估窗倒挂)")
        window_echo = {"from": window_start.isoformat(), "to": window_end.isoformat()}
        days_value = max(1, round((window_end - window_start).total_seconds() / 86400))
        cutoff = window_start
    else:
        days_value = days
        cutoff = datetime.now(UTC) - timedelta(days=days)

    async with factory() as session:
        # 窗口内同步聚合(口径与 T28 相同:次数、成功、失败)
        sync_conds = [SyncLog.started_at >= cutoff]
        if window_end is not None:
            sync_conds.append(SyncLog.started_at <= window_end)
        sync_q = (
            select(
                SyncLog.source_id,
                func.count().label("total_syncs"),
                func.count().filter(SyncLog.status == "success").label("success_syncs"),
                func.count().filter(SyncLog.status == "failed").label("failed_syncs"),
                func.count().filter(SyncLog.status == "partial").label("partial_syncs"),
            )
            .where(*sync_conds)
            .group_by(SyncLog.source_id)
        )
        sync_rows = (await session.execute(sync_q)).all()

        # 当前态:全部时间内最近一次同步尝试(无论成败),与 list_data_sources 同口径
        latest_sub = (
            select(
                SyncLog.source_id,
                func.max(SyncLog.started_at).label("max_started"),
            )
            .group_by(SyncLog.source_id)
            .subquery()
        )
        latest_rows = (
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
        latest_map = {
            row.source_id: {
                "status": row.status,
                "error_detail": row.error_detail,
                "started_at": row.started_at,
            }
            for row in latest_rows
        }

        # documents.source_id 为复合键 "{数据源id}/{路径}"(五个 connector 一致),
        # 而 sync_log.source_id 是纯数据源 id → 按首段聚合对齐口径(无斜杠时整串即 id)。
        # P1:仅统计 SERVING 生命期(active + missing_candidate 宽限)——墓碑/
        # 被接替文档退出知识计数(与旧"物理删除即从计数消失"语义对齐;对象待 GC)。
        source_prefix = func.split_part(Document.source_id, "/", 1)
        doc_q = (
            select(
                source_prefix.label("source_prefix"),
                func.count().label("doc_count"),
                func.coalesce(func.sum(Document.chunk_count), 0).label("chunk_count"),
            )
            .where(Document.lifecycle.in_(DocLifecycle.SERVING))
            .group_by(source_prefix)
        )
        doc_rows = (await session.execute(doc_q)).all()
        doc_map = {row.source_prefix: (row.doc_count, row.chunk_count) for row in doc_rows}

        ds_q = select(DataSource.id, DataSource.type, DataSource.product, DataSource.enabled)
        ds_rows = (await session.execute(ds_q)).all()
        ds_map = {row.id: row for row in ds_rows}

    def _health(total_syncs: int, success_rate: float, enabled: bool) -> str:
        if not enabled:
            return "disabled"
        if total_syncs < MIN_SYNC_RUNS:
            return "insufficient_data"
        if success_rate >= 0.9:
            return "healthy"
        if success_rate >= 0.5:
            return "degraded"
        return "critical"

    items = []
    # 以 data_sources 全表驱动:零历史源也出现(不缺席、不伪造结论)
    seen_ids: set[str] = set()
    all_ids = list(ds_map.keys()) + [r.source_id for r in sync_rows if r.source_id not in ds_map]
    for source_id in all_ids:
        if source_id in seen_ids:
            continue
        seen_ids.add(source_id)
        ds = ds_map.get(source_id)
        agg = next((r for r in sync_rows if r.source_id == source_id), None)
        total = agg.total_syncs if agg else 0
        success = agg.success_syncs if agg else 0
        failed = agg.failed_syncs if agg else 0
        partial = agg.partial_syncs if agg else 0
        success_rate = round(success / total, 4) if total else 0.0
        latest = latest_map.get(source_id)
        if ds is not None:
            source_type, product, enabled = ds.type, ds.product, ds.enabled
        else:
            # 幽灵行:sync_log 有而 data_sources 无(保持 T28 可见性,不臆断配置)
            source_type = "unknown"
            product = "unknown"
            enabled = True
        items.append(
            {
                "source_id": source_id,
                "source_type": source_type,
                "product": product,
                "enabled": enabled,
                "doc_count": doc_map.get(source_id, (0, 0))[0],
                "chunk_count": doc_map.get(source_id, (0, 0))[1],
                "window_days": days_value,
                "total_syncs": total,
                "success_syncs": success,
                "partial_syncs": partial,
                "failed_syncs": failed,
                "sync_success_rate": success_rate,
                # #21:显式语义类标注 —— 本条是历史窗口可靠性参考信号,
                # 不是当前知识健康(当前权威 = W2 /sync-health)。
                "signal": "historical_reliability",
                "health": _health(total, success_rate, enabled),
                "last_sync": latest["started_at"].isoformat() if latest else None,
                "last_sync_status": latest["status"] if latest else None,
                "last_sync_error": latest["error_detail"] if latest else None,
            }
        )

    result: dict[str, Any] = {"items": items, "days": days_value}
    if window_echo is not None:
        result["window"] = window_echo
    return result
