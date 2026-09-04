"""Widget 外观管理端点(Issue #24 REV1:per-site launcher icon × shape × theme)。

- 唯一持久权威 = ``site_experiences``(不建第二套外观配置系统);
- 统一外观语义 = ``launcher_icon`` / ``launcher_shape`` / ``launcher_theme``
  (封闭枚举;与 Widget 注册表/集成文档同一冻结集合);
- 读 = 站点体验列表(site_id/display_name/enabled + 归一化有效外观值 +
  遗留 launcher_style 回显,供 UI 提示退役选择);
- 写 = 仅外观三列,枚举校验(非法值 422 显式拒绝——与 Widget 侧 fail-safe
  回落不同:Admin 写入口必须显式报错,不允许静默改写);遗留 launcher_style
  列零触碰(旧应用回滚行为保真);
- 种子(seed_default_sites)不写外观列 → Admin 值跨 YAML 重启存续(P7)。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import SiteExperience
from backend.services.site_experiences import (
    DEFAULT_LAUNCHER_ICON,
    LAUNCHER_ICONS,
    LAUNCHER_SHAPES,
    LAUNCHER_THEMES,
    legacy_style_to_icon,
    normalize_launcher_icon,
    normalize_launcher_shape,
    normalize_launcher_theme,
)

router = APIRouter(prefix="/widget-appearance", tags=["Widget 外观"])

EditorDep = Annotated[CurrentUser, Depends(require_role("admin", "editor"))]


class LauncherAppearanceUpdate(BaseModel):
    """外观更新请求体(统一语义三字段,均为封闭枚举,非法值 422)。"""

    launcher_icon: str = Field(min_length=1, max_length=50)
    launcher_shape: str = Field(min_length=1, max_length=20)
    launcher_theme: str = Field(min_length=1, max_length=10)


def _serialize(row: SiteExperience) -> dict[str, Any]:
    stored_icon = getattr(row, "launcher_icon", None)
    legacy_style = getattr(row, "launcher_style", None)
    effective_icon = (
        normalize_launcher_icon(stored_icon)
        if stored_icon is not None
        else (legacy_style_to_icon(legacy_style) or DEFAULT_LAUNCHER_ICON)
    )
    return {
        "site_id": row.site_id,
        "display_name": row.display_name,
        "enabled": row.enabled,
        "launcher_icon": effective_icon,
        "launcher_shape": normalize_launcher_shape(getattr(row, "launcher_shape", None)),
        "launcher_theme": normalize_launcher_theme(getattr(row, "launcher_theme", None)),
        # 遗留回显:REV0 风格选择已退役;UI 据此提示「需重新选择」,非集成契约面
        "legacy_launcher_style": legacy_style,
    }


@router.get("")
async def list_widget_appearance(
    _: EditorDep,
    request: Request,
) -> list[dict[str, Any]]:
    """站点体验外观列表(归一化后的有效值;NULL 行显示为兼容默认)。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        rows = (
            await session.execute(select(SiteExperience).order_by(SiteExperience.site_id))
        ).scalars().all()
        return [_serialize(row) for row in rows]


@router.put("/{site_id}")
async def update_widget_appearance(
    site_id: str,
    body: LauncherAppearanceUpdate,
    _: EditorDep,
    request: Request,
) -> dict[str, Any]:
    """保存指定站点的外观(封闭枚举显式校验;未知站点 404)。"""
    if body.launcher_icon not in LAUNCHER_ICONS:
        raise HTTPException(
            status_code=422,
            detail=f"未知 launcher_icon: {body.launcher_icon}(合法值: {', '.join(LAUNCHER_ICONS)})",
        )
    if body.launcher_shape not in LAUNCHER_SHAPES:
        raise HTTPException(
            status_code=422,
            detail=f"未知 launcher_shape: {body.launcher_shape}(合法值: {', '.join(LAUNCHER_SHAPES)})",
        )
    if body.launcher_theme not in LAUNCHER_THEMES:
        raise HTTPException(
            status_code=422,
            detail=f"未知 launcher_theme: {body.launcher_theme}(合法值: {', '.join(LAUNCHER_THEMES)})",
        )
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        row = await session.get(SiteExperience, site_id)
        if row is None:
            raise HTTPException(status_code=404, detail="站点体验不存在")
        row.launcher_icon = body.launcher_icon
        row.launcher_shape = body.launcher_shape
        row.launcher_theme = body.launcher_theme
        await session.commit()
        return _serialize(row)
