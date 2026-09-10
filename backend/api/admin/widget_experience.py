"""Widget Experience 管理端点(I-UX-001)。

- 唯一持久权威 = ``site_experiences``(experience 列)+ ``site_trusted_actions``;
- experience 字段全部封闭枚举,Admin 写入口显式 422(与 Widget 侧 fail-safe
  归一化不同:写不允许静默改写);
- Trusted Action 生命周期(冻结契约 §2.15):
  draft → (TEST 真实 ASK-AI) → verified → published;
  语义编辑(query/action_type)使既有验收失效回落 draft;纯 label 编辑不失效;
  TEST 执行**真实** ASK-AI 管道(rag.answer,channel=admin),结果快照存
  last_test_result 供 Admin 人工验收;无假预览、无自动评测架构。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import SiteExperience, SiteTrustedAction
from backend.services.site_experiences import (
    LAUNCHER_ICONS,
)
from backend.services.widget_experience import (
    ACTION_STATES,
    ACTION_TYPES,
    CHAT_SIZES,
    CHAT_THEMES,
    ENTRY_MODES,
    LAUNCHER_BRANDS,
    LAUNCHER_MOTIONS,
    LAUNCHER_PRESENTATIONS,
    LAUNCHER_SIZES,
    PROACTIVE_ELIGIBLE_ACTION_STATES,
    PROACTIVE_TIMINGS,
    normalize_action_state,
    normalize_action_type,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/widget-experience", tags=["Widget Experience"])

EditorDep = Annotated[CurrentUser, Depends(require_role("admin", "editor"))]


class ExperienceUpdate(BaseModel):
    """体验配置更新请求体(全部可选;None = 不修改;传 null 清除回默认)。

    launcher_icon 一并纳入(产品契约 §2.16 LAUNCHER 组的 Icon 维度;与
    /widget-appearance 写同一列,同一持久权威,双入口不冲突)。
    """

    launcher_icon: str | None = None
    entry_mode: str | None = None
    proactive_timing: str | None = None
    launcher_motion: str | None = None
    launcher_size: str | None = None
    launcher_brand: str | None = None
    launcher_color: str | None = None
    chat_theme: str | None = None
    chat_accent_color: str | None = None
    chat_size: str | None = None
    greeting_override: str | None = None
    # V2.3 矫正:launcher 呈现方式(pill=品牌胶囊 / icon=紧凑图标)
    launcher_presentation: str | None = None
    # 显式清除标记(区分「不修改」与「清除为 NULL」)
    clear_launcher_color: bool = False
    clear_chat_accent_color: bool = False
    clear_greeting_override: bool = False


class ActionCreate(BaseModel):
    action_type: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=60)
    query: str = Field(min_length=1, max_length=500)


class ActionUpdate(BaseModel):
    """动作更新(label = 纯展示;query/action_type = 语义编辑 → 验收失效)。"""

    label: str | None = Field(default=None, min_length=1, max_length=60)
    query: str | None = Field(default=None, min_length=1, max_length=500)
    action_type: str | None = Field(default=None, min_length=1, max_length=40)
    sort_order: int | None = Field(default=None, ge=0, le=999)


class ActionStateUpdate(BaseModel):
    state: str = Field(min_length=1, max_length=10)


def _validate_experience(body: ExperienceUpdate) -> None:
    """experience 枚举显式校验(非法 422;与 Admin 写入不允许静默改写一致)。"""
    checks: list[tuple[str | None, tuple[str, ...], str]] = [
        (body.launcher_icon, LAUNCHER_ICONS, "launcher_icon"),
        (body.entry_mode, ENTRY_MODES, "entry_mode"),
        (body.proactive_timing, PROACTIVE_TIMINGS, "proactive_timing"),
        (body.launcher_motion, LAUNCHER_MOTIONS, "launcher_motion"),
        (body.launcher_size, LAUNCHER_SIZES, "launcher_size"),
        (body.launcher_brand, LAUNCHER_BRANDS, "launcher_brand"),
        (body.launcher_presentation, LAUNCHER_PRESENTATIONS, "launcher_presentation"),
        (body.chat_theme, CHAT_THEMES, "chat_theme"),
        (body.chat_size, CHAT_SIZES, "chat_size"),
    ]
    for value, allowed, name in checks:
        if value is not None and value not in allowed:
            raise HTTPException(
                status_code=422,
                detail=f"未知 {name}: {value}(合法值: {', '.join(allowed)})",
            )
    for value, name in ((body.launcher_color, "launcher_color"), (body.chat_accent_color, "chat_accent_color")):
        if value is not None and not _valid_hex_color(value):
            raise HTTPException(status_code=422, detail=f"{name} 须为 #RRGGBB 十六进制色值")


def _valid_hex_color(value: str) -> bool:
    text = value.strip()
    if not text.startswith("#") or len(text) not in (4, 7):
        return False
    try:
        int(text[1:], 16)
    except ValueError:
        return False
    return True


def _serialize_experience(row: SiteExperience) -> dict[str, Any]:
    return {
        "site_id": row.site_id,
        "display_name": row.display_name,
        "enabled": row.enabled,
        "launcher_icon": getattr(row, "launcher_icon", None),
        "entry_mode": row.entry_mode,
        "proactive_timing": row.proactive_timing,
        "launcher_motion": row.launcher_motion,
        "launcher_size": row.launcher_size,
        "launcher_brand": row.launcher_brand,
        "launcher_color": row.launcher_color,
        "chat_theme": row.chat_theme,
        "chat_accent_color": row.chat_accent_color,
        "chat_size": row.chat_size,
        "greeting_override": row.greeting_override,
        "launcher_presentation": getattr(row, "launcher_presentation", None),
    }


def _serialize_action(row: SiteTrustedAction) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "site_id": row.site_id,
        "action_type": row.action_type,
        "label": row.label,
        "query": row.query,
        "state": row.state,
        "sort_order": row.sort_order,
        "last_tested_at": row.last_tested_at.isoformat() if row.last_tested_at else None,
        "last_verified_at": row.last_verified_at.isoformat() if row.last_verified_at else None,
        "last_test_result": row.last_test_result,
    }


async def _get_site(session: AsyncSession, site_id: str) -> SiteExperience:
    row = await session.get(SiteExperience, site_id)
    if row is None:
        raise HTTPException(status_code=404, detail="站点体验不存在")
    return row


async def _get_action(session: AsyncSession, action_id: UUID) -> SiteTrustedAction:
    row = await session.get(SiteTrustedAction, action_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Trusted Action 不存在")
    return row


@router.get("")
async def list_widget_experience(
    _: EditorDep,
    request: Request,
) -> list[dict[str, Any]]:
    """站点体验配置列表(experience 字段 + trusted actions;NULL = 未配置)。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        sites = (
            await session.execute(select(SiteExperience).order_by(SiteExperience.site_id))
        ).scalars().all()
        actions = (
            await session.execute(
                select(SiteTrustedAction).order_by(
                    SiteTrustedAction.sort_order, SiteTrustedAction.created_at
                )
            )
        ).scalars().all()
        by_site: dict[str, list[dict[str, Any]]] = {}
        for action in actions:
            by_site.setdefault(action.site_id, []).append(_serialize_action(action))
        return [
            {**_serialize_experience(site), "trusted_actions": by_site.get(site.site_id, [])}
            for site in sites
        ]


@router.put("/{site_id}")
async def update_widget_experience(
    site_id: str,
    body: ExperienceUpdate,
    _: EditorDep,
    request: Request,
) -> dict[str, Any]:
    """保存指定站点的体验配置(封闭枚举显式校验;未知站点 404)。"""
    _validate_experience(body)
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        row = await _get_site(session, site_id)
        for field in (
            "launcher_icon",
            "entry_mode",
            "proactive_timing",
            "launcher_motion",
            "launcher_size",
            "launcher_brand",
            "launcher_presentation",
            "chat_theme",
            "chat_size",
        ):
            value = getattr(body, field)
            if value is not None:
                setattr(row, field, value)
        if body.clear_launcher_color:
            row.launcher_color = None
        elif body.launcher_color is not None:
            row.launcher_color = body.launcher_color.strip()
        if body.clear_chat_accent_color:
            row.chat_accent_color = None
        elif body.chat_accent_color is not None:
            row.chat_accent_color = body.chat_accent_color.strip()
        if body.clear_greeting_override:
            row.greeting_override = None
        elif body.greeting_override is not None:
            row.greeting_override = body.greeting_override.strip()
        await session.commit()
        return _serialize_experience(row)


@router.post("/{site_id}/actions")
async def create_action(
    site_id: str,
    body: ActionCreate,
    _: EditorDep,
    request: Request,
) -> dict[str, Any]:
    """新建 Trusted Action(默认 draft,生产不可见)。"""
    if normalize_action_type(body.action_type) is None:
        raise HTTPException(
            status_code=422,
            detail=f"未知 action_type: {body.action_type}(合法值: {', '.join(ACTION_TYPES)})",
        )
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        await _get_site(session, site_id)
        row = SiteTrustedAction(
            site_id=site_id,
            action_type=body.action_type,
            label=body.label.strip(),
            query=body.query.strip(),
            state="draft",
            sort_order=0,
        )
        session.add(row)
        await session.commit()
        return _serialize_action(row)


@router.patch("/actions/{action_id}")
async def update_action(
    action_id: UUID,
    body: ActionUpdate,
    _: EditorDep,
    request: Request,
) -> dict[str, Any]:
    """编辑动作。label/sort_order = 纯展示(状态保持);query/action_type =
    语义编辑 → 既有验收失效(回落 draft,重新 TEST → 验收)。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        row = await _get_action(session, action_id)
        semantic_change = False
        if body.action_type is not None and body.action_type != row.action_type:
            if normalize_action_type(body.action_type) is None:
                raise HTTPException(
                    status_code=422,
                    detail=f"未知 action_type: {body.action_type}(合法值: {', '.join(ACTION_TYPES)})",
                )
            row.action_type = body.action_type
            semantic_change = True
        if body.query is not None and body.query.strip() != row.query:
            row.query = body.query.strip()
            semantic_change = True
        if body.label is not None:
            row.label = body.label.strip()
        if body.sort_order is not None:
            row.sort_order = body.sort_order
        if semantic_change and row.state != "draft":
            logger.info(
                "trusted action %s 语义编辑,验收失效(verified_at 保留为历史)",
                action_id,
            )
            row.state = "draft"
        await session.commit()
        return _serialize_action(row)


@router.delete("/actions/{action_id}")
async def delete_action(
    action_id: UUID,
    _: EditorDep,
    request: Request,
) -> dict[str, str]:
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        row = await _get_action(session, action_id)
        await session.delete(row)
        await session.commit()
    return {"status": "ok"}


@router.post("/actions/{action_id}/test")
async def test_action(
    action_id: UUID,
    _: EditorDep,
    request: Request,
) -> dict[str, Any]:
    """真实 ASK-AI 管道测试(冻结契约:禁止假预览)。

    以 action.query 走完整 rag.answer()(channel=admin,与 Admin 内嵌聊天
    同渠道语义),真实答案 + 真实引用/来源落 last_test_result 快照并返回。
    """
    rag = getattr(request.app.state, "rag", None)
    if rag is None:
        raise HTTPException(status_code=503, detail="RAG 管道尚未就绪")
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        row = await _get_action(session, action_id)
        query = row.query
    try:
        result = await rag.answer(query, channel="admin")
    except Exception as exc:  # noqa: BLE001 - 管道失败如实返回,不伪造结果
        raise HTTPException(status_code=502, detail=f"ASK-AI 管道执行失败: {exc}") from exc
    payload = {
        "answer": result.answer,
        "sources": list(result.sources or []),
        "is_answered": bool(result.is_answered),
        "tested_at": datetime.now(timezone.utc).isoformat(),
    }
    async with factory() as session:
        row = await _get_action(session, action_id)
        row.last_tested_at = datetime.now(timezone.utc)
        row.last_test_result = payload
        await session.commit()
        return _serialize_action(row)


@router.post("/actions/{action_id}/verify")
async def verify_action(
    action_id: UUID,
    _: EditorDep,
    request: Request,
) -> dict[str, Any]:
    """人工验收(必须先有真实测试结果;VERIFIED = 答案/证据经人工确认)。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        row = await _get_action(session, action_id)
        if not row.last_test_result:
            raise HTTPException(
                status_code=400,
                detail="请先执行 Test(真实 ASK-AI 管道)并人工确认结果后再验证",
            )
        row.state = "verified"
        row.last_verified_at = datetime.now(timezone.utc)
        await session.commit()
        return _serialize_action(row)


@router.post("/actions/{action_id}/state")
async def set_action_state(
    action_id: UUID,
    body: ActionStateUpdate,
    _: EditorDep,
    request: Request,
) -> dict[str, Any]:
    """显式状态迁移(publish 需 verified;unpublish 回 verified;draft 兜底)。"""
    if normalize_action_state(body.state) is None:
        raise HTTPException(
            status_code=422,
            detail=f"未知 state: {body.state}(合法值: {', '.join(ACTION_STATES)})",
        )
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        row = await _get_action(session, action_id)
        target = body.state
        if target == "published" and row.state not in PROACTIVE_ELIGIBLE_ACTION_STATES:
            raise HTTPException(
                status_code=400,
                detail="发布前必须先通过 Test 并 Verify(仅 VERIFIED 可发布)",
            )
        if target == "verified" and not row.last_test_result:
            raise HTTPException(status_code=400, detail="尚未执行真实测试,不能置为 verified")
        row.state = target
        await session.commit()
        return _serialize_action(row)
