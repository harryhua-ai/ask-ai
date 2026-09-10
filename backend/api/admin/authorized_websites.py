"""Authorized Websites 管理端点(I-UX-001 矫正,Issue #6)。

冻结契约(I-UX-001-POST-PRODUCTION-CORRECTIVE §3.11):
- 产品术语 Authorized Websites;授权 = 站点 enabled + 请求 Origin 归一化后
  **精确**命中 ``site_experiences.allowed_origins``;
- 唯一持久权威 = ``site_experiences.allowed_origins``(不建第二套 CORS 列表;
  浏览器 CORS 执行层由 backend/main.py 动态中间件消费同一 DB 权威);
- 输入策略:canonical 形式 = ``scheme://host[:port]``(默认端口剥除);
  通配符 / 路径 / 查询串 / 非 http(s) 一律 422 显式拒绝(fail closed);
- Admin 变更即时生效(无需重建镜像/重新部署),且跨重启存续
  (seed_default_sites 不覆写既有行的 origins —— 见 services 权威域划分);
- 变更可观测:遵循产品既有 logging 惯例(structlog 风格 info 日志),不发明
  独立审计平台。

删除语义:仅允许删除「存在的精确 origin」(404 兜底);是否删除**最后一个**
origin 的后果提示由 Admin UI 承担(契约允许的窄检测 = 列表长度),后端不阻止
(避免第二套策略引擎)。
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.auth.dependencies import CurrentUser, require_role
from backend.db.models import SiteExperience
from backend.services.site_experiences import normalize_origin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/authorized-websites", tags=["Authorized Websites"])

EditorDep = Annotated[CurrentUser, Depends(require_role("admin", "editor"))]


class OriginCreate(BaseModel):
    origin: str = Field(min_length=1, max_length=200)


class OriginDelete(BaseModel):
    origin: str = Field(min_length=1, max_length=200)


def _canonical_policy_origin(raw: str) -> str | None:
    """授权**策略输入**校验 + canonical 化(比请求侧 normalize 更严格)。

    契约 §3.11:拒绝通配符授权;拒绝以路径/查询串为授权范围(路径不是来源
    的一部分;输入含 path/query/fragment → 422,而非静默剥除——静默剥除会让
    Admin 误以为授权了带路径的 URL)。scheme 仅 http/https;host 非空;
    默认端口剥除,非默认端口保留。
    """
    from urllib.parse import urlparse

    text = raw.strip()
    if not text.lower().startswith(("http://", "https://")):
        return None
    if "*" in text:
        return None
    try:
        parsed = urlparse(text)
    except ValueError:
        return None
    if parsed.path not in ("", "/") or parsed.query or parsed.params or parsed.fragment:
        return None
    return normalize_origin(text)


def _serialize(row: SiteExperience) -> dict[str, Any]:
    return {
        "site_id": row.site_id,
        "display_name": row.display_name,
        "enabled": row.enabled,
        "allowed_origins": list(row.allowed_origins or []),
    }


async def _get_site(session: AsyncSession, site_id: str) -> SiteExperience:
    row = await session.get(SiteExperience, site_id)
    if row is None:
        raise HTTPException(status_code=404, detail="站点体验不存在")
    return row


@router.get("")
async def list_authorized_websites(
    _: EditorDep,
    request: Request,
) -> list[dict[str, Any]]:
    """各站点当前已授权的精确 origin 列表(授权现状快照)。"""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        rows = (
            (await session.execute(select(SiteExperience).order_by(SiteExperience.site_id)))
            .scalars()
            .all()
        )
        return [_serialize(row) for row in rows]


@router.post("/{site_id}/origins")
async def add_authorized_origin(
    site_id: str,
    body: OriginCreate,
    _: EditorDep,
    request: Request,
) -> dict[str, Any]:
    """新增精确授权 origin(canonical 化;通配符/路径/非法输入 422 显式拒绝)。"""
    canonical = _canonical_policy_origin(body.origin)
    if canonical is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "非法 origin:须为完整 http(s)://host[:port] 精确来源"
                "(禁止通配符、路径、查询串;80/443 默认端口自动剥除)"
            ),
        )
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        row = await _get_site(session, site_id)
        current = list(row.allowed_origins or [])
        if canonical in current:
            raise HTTPException(status_code=409, detail=f"origin 已存在: {canonical}")
        current.append(canonical)
        row.allowed_origins = current
        await session.commit()
        logger.info(
            "authorized_websites: site=%s origin_added=%s total=%d",
            site_id,
            canonical,
            len(current),
        )
        return _serialize(row)


@router.delete("/{site_id}/origins")
async def remove_authorized_origin(
    site_id: str,
    body: OriginDelete,
    _: EditorDep,
    request: Request,
) -> dict[str, Any]:
    """移除精确授权 origin(canonical 形式匹配;不存在 404)。"""
    canonical = normalize_origin(body.origin)
    if canonical is None:
        raise HTTPException(status_code=422, detail="非法 origin: 须为完整 http(s)://host[:port]")
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        row = await _get_site(session, site_id)
        current = list(row.allowed_origins or [])
        if canonical not in current:
            raise HTTPException(status_code=404, detail=f"origin 不存在: {canonical}")
        current.remove(canonical)
        row.allowed_origins = current
        await session.commit()
        logger.info(
            "authorized_websites: site=%s origin_removed=%s remaining=%d",
            site_id,
            canonical,
            len(current),
        )
        return _serialize(row)
