"""技术性能端点 —— 缺口观察状态机(U-15;Ownership: Track E Wave 1)。

IF-6 拆分地图中的 tech_observation.py(观察命令/转移评估/流转事件投影)。
状态词表 IF-1 经 backend/services/gap_status.py;状态机语义/前置门/持久化
单一来源 = backend/services/gap_observation.py(本文件仅 HTTP 装配)。

端点(router 无 prefix,由 tech.py tech_router(prefix="/tech") 装配):
- POST /tech/answer-gaps/observation/evaluate   操作者批量窗口评估(admin/editor;
  判定持久化;复现→OPEN / 满窗→RESOLVED;评估机制=显式触发 + 单聚类
  lazy-on-read,均为合同许可机制)
- GET  /tech/answer-gaps/{gap_id}/observation         观察状态(viewer+;先评估后读)
- POST /tech/answer-gaps/{gap_id}/observation/start   进入观察(admin/editor;三前置门)
- POST /tech/answer-gaps/{gap_id}/observation/abort   中止观察→OPEN(admin/editor)
- GET  /tech/answer-gaps/{gap_id}/observation/events  流转事件全量(viewer+;History)

路由序注意:``/answer-gaps/observation/evaluate`` 为静态段,必须先于
``/answer-gaps/{gap_id}/…`` 参数化路由注册,避免 gap_id="observation" 误配。
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import GapObservationEvent, QuestionCluster
from backend.services import gap_observation as obs
from backend.services.gap_observation import ObservationGateError, ObservationStateError

# 子 router 无 prefix/tags:由 tech.py 的 tech_router(prefix="/tech",
# tags=["技术性能"])统一装配(同 tech_answer_gaps.py)。
router = APIRouter()

ViewerDep = Annotated[CurrentUser, Depends(require_role("admin", "editor", "viewer"))]
OperatorDep = Annotated[CurrentUser, Depends(require_role("admin", "editor"))]


class ObservationStartRequest(BaseModel):
    """进入观察请求。``confirmed`` = 操作者确认内容修复完成(前置①)。"""

    confirmed: bool = False


async def _get_gap(session: AsyncSession, gap_id: str) -> QuestionCluster:
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


@router.post("/answer-gaps/observation/evaluate")
async def evaluate_gap_observations(
    user: OperatorDep,
    request: Request,
) -> dict[str, Any]:
    """批量观察窗评估(U-15 转移任务;判定持久化)。

    对全部 observing 聚类执行:复现→回 OPEN / 满窗无复现→RESOLVED /
    窗内无复现→不转移。全部转移经 gap_observation_events 持久化留痕;
    既有两态(open/resolved)零回归(评估只作用于 observing)。
    """
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        clusters = (
            (
                await session.execute(
                    select(QuestionCluster).where(
                        QuestionCluster.cluster_type == "gap",
                        QuestionCluster.status == "observing",
                    )
                )
            )
            .scalars()
            .all()
        )
        transitions = []
        for cluster in clusters:
            result = await obs.evaluate_observation(session, cluster)
            if result is not None:
                transitions.append(result)
        await session.commit()
    return {"evaluated": len(clusters), "transitions": transitions}


@router.get("/answer-gaps/{gap_id}/observation")
async def get_gap_observation(
    _: ViewerDep,
    request: Request,
    gap_id: str,
) -> dict[str, Any]:
    """观察状态(lazy-on-read:满窗/复现评估先于读发生,判定持久化)。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        cluster = await _get_gap(session, gap_id)
        await obs.evaluate_observation(session, cluster)
        await session.commit()
        state = await obs.serialize_observation_state(session, cluster)
    return state


@router.post("/answer-gaps/{gap_id}/observation/start")
async def start_gap_observation(
    user: OperatorDep,
    request: Request,
    gap_id: str,
    body: ObservationStartRequest,
) -> dict[str, Any]:
    """进入观察(OPEN→OBSERVING;三前置门:操作者确认+相关源 sync/reindex
    成功+post-sync 验证成功)。任一门未过 → 409(gates 明细机器真值),
    状态零变化;重复进入/非 OPEN 态 → 409 invalid_state。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        cluster = await _get_gap(session, gap_id)
        try:
            await obs.start_observation(
                session, cluster, actor=user.email, confirmed=body.confirmed
            )
            await session.commit()
        except ObservationGateError as e:
            await session.rollback()
            raise HTTPException(
                status_code=409, detail={"code": e.code, "gates": e.gates}
            ) from e
        except ObservationStateError as e:
            await session.rollback()
            raise HTTPException(
                status_code=409, detail={"code": e.code, "from_status": e.from_status}
            ) from e
        state = await obs.serialize_observation_state(session, cluster)
    return state


@router.post("/answer-gaps/{gap_id}/observation/abort")
async def abort_gap_observation(
    user: OperatorDep,
    request: Request,
    gap_id: str,
) -> dict[str, Any]:
    """中止观察(OBSERVING→OPEN;禁止把中止表达为 resolved)。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        cluster = await _get_gap(session, gap_id)
        try:
            await obs.abort_observation(session, cluster, actor=user.email)
            await session.commit()
        except ObservationStateError as e:
            await session.rollback()
            raise HTTPException(
                status_code=409, detail={"code": e.code, "from_status": e.from_status}
            ) from e
        state = await obs.serialize_observation_state(session, cluster)
    return state


@router.get("/answer-gaps/{gap_id}/observation/events")
async def list_gap_observation_events(
    _: ViewerDep,
    request: Request,
    gap_id: str,
) -> dict[str, Any]:
    """流转事件全量(时间升序;诊断侧板「历史记录」Tab 权威数据源)。

    lazy-on-read 评估同样先于读发生,保证 History 呈现含最新持久化判定。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        cluster = await _get_gap(session, gap_id)
        await obs.evaluate_observation(session, cluster)
        await session.commit()
        rows = (
            (
                await session.execute(
                    select(GapObservationEvent)
                    .where(GapObservationEvent.cluster_id == cluster.id)
                    .order_by(GapObservationEvent.created_at.asc(), GapObservationEvent.id.asc())
                )
            )
            .scalars()
            .all()
        )
        items = [
            {
                "id": str(ev.id),
                "event_type": ev.event_type,
                "from_status": ev.from_status,
                "to_status": ev.to_status,
                "actor": ev.actor,
                "detail": ev.detail or {},
                "created_at": ev.created_at.isoformat()
                if isinstance(ev.created_at, datetime)
                else None,
            }
            for ev in rows
        ]
    return {"items": items, "total": len(items)}
