"""技术性能端点 —— 证据聚合子模块(Wave 1 Track F:U-17/U-18/U-19)。

**Ownership(IF-6 附录):本文件 = Track F(证据聚合)Wave 1 专属。**
对应 remediation plan §3.2 item 2 拆分地图中的 tech_evidence.py
(用户聚合/归因/topic 投影;U-17 聚合窗 = IF-7 所选分析窗)。

本模块由 tech.py ``include_router`` 挂载(prefix="/tech",tags 继承),
Wave 1 在本文件内新增只读路由,**无需编辑 backend/api/admin/tech.py**。

**冻结合同**(track-f-contract.md / matrix-TI TI-12/TI-27/TI-33 /
remediation plan §3.5「跨轨衔接」):

- U-17(TI-27)GET /answer-gaps/{gap_id}/users —— 不引入真人身份追踪;
  定义 = 所选分析窗内去重的**伪匿名会话**(conversations.session_id,
  widget 匿名会话 ID,既有列零新增);零姓名/邮箱/IP;隐私保持聚合
  (DISTINCT 计数投影,响应不外泄任何 session_id 原值);历史行
  session_id NULL → 身份真值不足 → 诚实 unavailable(不得编造计数);
  无会话证据 → users=0(空集去重真值);窗口词表 = IF-7 全词表
  (today/7d/30d/all + 显式起止 from/to;词表外值 422,禁静默回退)。
- U-18(TI-33)GET /answer-gaps/{gap_id}/sources —— 归因关联必须源自
  真实证据链:gap 归属会话的引用真值(conversations.sources,citation
  truth)与数据源身份 (type, product) 匹配;证据规则 ID =
  conversation_citation_identity_match(可解释);引用真值存在但无对应
  数据源行(如第一方知识案例/已删源)→ 不归因,unmatched_citations
  透明列出;零前端猜测;只读投影,零新持久化。归因范围 = gap 自身
  证据跨度(§3.5 S6 例外面语义,无窗口参数)。
- U-19(TI-12)GET /answer-gaps/{gap_id}/topic —— 确定性主题派生
  (backend/services/gap_topic.py,纯函数,零 LLM);同簇多次拉取
  稳定不变;不可派生 → topic=null(UI 回退代表问句)。

只读(GET-only)、RBAC 与既有 /tech 读面一致(viewer+,未认证 401)、
未知 gap → 404。
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import Conversation, DataSource, QuestionCluster
from backend.services.gap_topic import derive_gap_topic

# 子 router 无 prefix/tags:由 tech.py 的 tech_router(prefix="/tech",
# tags=["技术性能"])统一装配(同 tech_answer_gaps.py)。
router = APIRouter()

ViewerDep = Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))]

# IF-7 冻结分析窗词表(Track F 消费端;显式起止经 from/to 表达)。
_WINDOW_PATTERN = r"^(today|7d|30d|all)$"
_WINDOW_DAYS = {"7d": 7, "30d": 30}

# U-18 证据规则 ID(冻结):会话引用真值 × 数据源身份 (type, product) 匹配。
_EVIDENCE_RULE = "conversation_citation_identity_match"


def _window_bounds(
    window: str,
    date_from: datetime | None,
    date_to: datetime | None,
) -> tuple[datetime | None, datetime | None, dict[str, Any]]:
    """解析聚合窗 → (start, end, echo)。显式起止优先于预设词表。"""
    if date_from is not None or date_to is not None:
        echo = {
            "preset": window,
            "from": date_from.isoformat() if date_from else None,
            "to": date_to.isoformat() if date_to else None,
        }
        return date_from, date_to, echo
    start: datetime | None = None
    end: datetime | None = None
    if window in _WINDOW_DAYS:
        start = datetime.now(UTC) - timedelta(days=_WINDOW_DAYS[window])
    elif window == "today":
        now = datetime.now(UTC)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    echo = {"preset": window, "from": None, "to": None}
    return start, end, echo


async def _require_gap(session: AsyncSession, gap_id: str) -> QuestionCluster:
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
    return cluster


@router.get("/answer-gaps/{gap_id}/users")
async def tech_answer_gap_users(
    _: ViewerDep,
    request: Request,
    gap_id: str,
    window: str = Query(default="all", pattern=_WINDOW_PATTERN),
    date_from: Annotated[datetime | None, Query(alias="from")] = None,
    date_to: Annotated[datetime | None, Query(alias="to")] = None,
) -> dict[str, Any]:
    """U-17 受影响用户聚合(TI-27)—— 伪匿名会话去重只读投影。

    定义(冻结):所选分析窗内该 gap 归属会话的去重伪匿名会话身份
    (conversations.session_id,widget 匿名会话 ID)。零真人身份追踪、
    零姓名/邮箱/IP;隐私保持聚合:响应只含 DISTINCT 计数,不外泄任何
    session_id 原值。

    诚实语义(禁编造计数):
    - 窗内全部会话含身份(或窗内无会话)→ ``users`` = DISTINCT 计数,
      ``users_available=true``(空集真值 0);
    - 窗内存在 session_id 缺失的会话(历史行)→ 身份真值不足,去重计数
      只是下界、不得伪称权威 → ``users=null``、``users_available=false``、
      ``unavailable_reason="session_identity_insufficient"``(诚实
      unavailable;未来数据天然支持权威聚合)。
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    start, end, echo = _window_bounds(window, date_from, date_to)

    async with factory() as session:
        await _require_gap(session, gap_id)

        preds = [Conversation.cluster_id == gap_id]
        if start is not None:
            preds.append(Conversation.created_at >= start)
        if end is not None:
            preds.append(Conversation.created_at <= end)

        row = (
            await session.execute(
                select(
                    func.count(Conversation.id).label("total"),
                    func.count(Conversation.session_id).label("with_identity"),
                    func.count(func.distinct(Conversation.session_id)).label("distinct_sessions"),
                )
                .select_from(Conversation)
                .where(*preds)
            )
        ).one()

    total = int(row.total or 0)
    with_identity = int(row.with_identity or 0)
    without_identity = total - with_identity
    distinct_sessions = int(row.distinct_sessions or 0)

    # 诚实裁决:身份真值不足(存在缺失身份的会话)→ unavailable,不编造。
    insufficient = total > 0 and without_identity > 0
    users = None if insufficient else distinct_sessions

    return {
        "gap_id": gap_id,
        "window": echo,
        "conversations_in_window": total,
        "conversations_with_session_identity": with_identity,
        "conversations_without_session_identity": without_identity,
        "distinct_sessions": distinct_sessions,
        "users": users,
        "users_available": not insufficient,
        "unavailable_reason": "session_identity_insufficient" if insufficient else None,
    }


@router.get("/answer-gaps/{gap_id}/sources")
async def tech_answer_gap_sources(
    _: ViewerDep,
    request: Request,
    gap_id: str,
) -> dict[str, Any]:
    """U-18 gap→源归因(TI-33)—— 引用真值 × 数据源身份匹配只读投影。

    证据规则(冻结 ID=conversation_citation_identity_match):gap 归属
    会话的引用真值(conversations.sources 条目的 (type, product) 身份,
    即 RAG citation truth 的来源元数据)与数据源行 (data_sources.type,
    data_sources.product) 精确匹配 → 归因成立;同一身份的多个数据源行
    均为证据支持的真实候选。引用真值存在但无对应数据源行(第一方知识
    案例 filesystem/knowledge、已删除源)→ 不归因,unmatched_citations
    透明列出(可解释、零猜测)。citing_conversations 按会话去重计数。

    归因范围 = gap 自身证据跨度(§3.5 S6 例外面语义,无窗口参数)。
    隐私:仅聚合计数与源身份元数据,零会话原文/零身份信息。
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        await _require_gap(session, gap_id)

        rows = (
            (
                await session.execute(
                    select(Conversation.sources, Conversation.id).where(
                        Conversation.cluster_id == gap_id
                    )
                )
            )
            .all()
        )

        # 引用真值聚合:身份 → 引用它的会话 id 集合(每会话去重)
        cited: dict[tuple[str, str], set[Any]] = {}
        citing_convs = 0
        for sources, conv_id in rows:
            identities: set[tuple[str, str]] = set()
            for src in sources or []:
                if not isinstance(src, dict):
                    continue
                stype = src.get("type")
                sproduct = src.get("product")
                if not isinstance(stype, str) or not stype:
                    continue
                identities.add((stype, sproduct if isinstance(sproduct, str) else ""))
            if identities:
                citing_convs += 1
            for ident in identities:
                cited.setdefault(ident, set()).add(conv_id)

        ds_rows = (
            (await session.execute(select(DataSource))).scalars().all()
        )
        ds_by_identity: dict[tuple[str, str], list[DataSource]] = {}
        for ds in ds_rows:
            ds_by_identity.setdefault((ds.type, ds.product), []).append(ds)

    items: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    for (stype, sproduct), conv_ids in cited.items():
        matches = ds_by_identity.get((stype, sproduct), [])
        if matches:
            for ds in matches:
                items.append(
                    {
                        "source_id": ds.id,
                        "source_type": ds.type,
                        "product": ds.product,
                        "citing_conversations": len(conv_ids),
                        "evidence_rule": _EVIDENCE_RULE,
                    }
                )
        else:
            unmatched.append(
                {
                    "source_type": stype,
                    "product": sproduct or None,
                    "citing_conversations": len(conv_ids),
                }
            )

    items.sort(key=lambda it: (-it["citing_conversations"], it["source_id"]))
    unmatched.sort(key=lambda it: (-it["citing_conversations"], it["source_type"]))

    return {
        "gap_id": gap_id,
        "conversations_total": len(rows),
        "citing_conversations_total": citing_convs,
        "items": items,
        "unmatched_citations": unmatched,
    }


@router.get("/answer-gaps/{gap_id}/topic")
async def tech_answer_gap_topic(
    _: ViewerDep,
    request: Request,
    gap_id: str,
) -> dict[str, Any]:
    """U-19 主题短语投影(TI-12)—— 确定性派生只读投影(零 LLM)。

    派生规则冻结于 backend/services/gap_topic.py(跨问句公共因子提取;
    纯函数,同簇内容多次拉取恒同值;忠实于 cluster 内容)。不可派生
    (单问句簇/无公共内容因子)→ ``topic=null``,``fallback``=代表问句
    (UI 回退路径,合同:无主题回退代表问句)。
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        cluster = await _require_gap(session, gap_id)
        topic, derivation = derive_gap_topic(
            cluster.representative_question, cluster.sample_questions
        )

    return {
        "gap_id": gap_id,
        "topic": topic,
        "derivation": derivation,
        "corpus_size": 1 + len([s for s in (cluster.sample_questions or []) if s]),
        "fallback": cluster.representative_question,
    }
