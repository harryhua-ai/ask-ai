"""站点体验(Site Experience)身份与来源授权服务(MSW 多站点 Widget)。

冻结契约要点(不在此重定义,只落实 HOW):
- site_id 是标识符,不是凭证;单独 site_id 不授予任何权限。
- 授权 = 站点存在且 enabled + 请求 Origin 归一化后**精确**命中 allowed_origins。
  CORS 仅为浏览器执行层,不作为服务端站点身份授权。
- 未知站点 / 禁用站点 / 无 Origin / 来源不匹配 → 一律 :class:`SiteDenied`
  (fail-safe;端点层统一对外文案,不区分具体原因)。
- legacy(无 site_id)→ 返回 None,不触发任何校验(兼容契约 §14)。
- 本模块不触碰 channel 语义与 SourceVisibilityGuard:widget 渠道可见性
  仍由 P0 主防线 + 纵深守卫按 channel 决定,site_id 不进入授权链。

配置权威源 = ``config/sites.yaml``(env ``SITES_CONFIG_PATH`` 可覆盖),
lifespan / 迁移脚本经 :func:`seed_default_sites` 幂等 upsert 进
``site_experiences`` 表;运行时读取 DB(为未来 Admin 管理留位)。
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db.models import SiteExperience

logger = logging.getLogger(__name__)

#: 站点配置默认路径(相对启动 cwd;仓库惯例同 config/*.yaml)
DEFAULT_SITES_CONFIG = Path("config/sites.yaml")

_DEFAULT_PORTS = {"http": 80, "https": 443}


class SiteDenied(Exception):
    """站点身份校验失败(未知/禁用站点、无来源、来源不匹配)。

    端点层捕获后统一转 403 通用文案 —— 授权失败的具体原因不外泄。
    """


@dataclass(frozen=True)
class ResolvedSite:
    """通过授权校验的站点体验快照(只读)。

    ML 闭环(G-L5):``welcome_i18n`` / ``starters_i18n`` 为按语言键的可选
    变体(如 ``{"zh": ...}``);默认 ``welcome`` / ``starters`` 语义不变。
    """

    site_id: str
    display_name: str
    welcome: str | None
    language: str | None
    starters: tuple[str, ...]
    welcome_i18n: dict | None = None
    starters_i18n: dict | None = None

    def localized_welcome(self, language: str | None) -> str | None:
        """按请求语言取欢迎语;无变体或缺省回落站点默认(语言独立于站点身份)。"""
        if language and self.welcome_i18n:
            hit = self.welcome_i18n.get(language)
            if hit:
                return str(hit)
        return self.welcome

    def localized_starters(self, language: str | None) -> tuple[str, ...]:
        """按请求语言取推荐问题;无变体或缺省回落站点默认。"""
        if language and self.starters_i18n:
            hit = self.starters_i18n.get(language)
            if isinstance(hit, list) and hit:
                return tuple(str(x) for x in hit)
        return self.starters


def normalize_origin(raw: str | None) -> str | None:
    """Origin / Referer → ``scheme://host[:port]`` 小写规范形;解析失败返回 None。

    - 剥路径与查询串(Referer 场景);scheme 仅接受 http/https。
    - 默认端口(80/443)剥除,其余端口保留 → 同一站点的两种写法归一。
    """
    if not raw:
        return None
    candidate = raw.strip()
    if not candidate.lower().startswith(("http://", "https://")):
        return None
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return None
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    if scheme not in _DEFAULT_PORTS or not host:
        return None
    port = parsed.port
    if port is not None and port != _DEFAULT_PORTS[scheme]:
        return f"{scheme}://{host}:{port}"
    return f"{scheme}://{host}"


def extract_request_origin(request: object) -> str | None:
    """取请求来源:优先 ``Origin`` 头;缺失时回退 ``Referer`` 的 origin 部分。"""
    origin = getattr(request, "headers", None)
    if origin is None:
        return None
    raw = origin.get("origin")
    if raw:
        return raw
    referer = origin.get("referer")
    if referer:
        return referer
    return None


async def resolve_site(
    session_factory: async_sessionmaker[AsyncSession],
    site_id: str | None,
    request_origin: str | None,
) -> ResolvedSite | None:
    """按「站点存在 + enabled + Origin 精确命中」解析站点体验。

    Args:
        session_factory: 异步会话工厂。
        site_id: 客户端声明的站点标识;空 → legacy 路径,返回 None(不校验)。
        request_origin: 请求来源(未归一化)。

    Returns:
        :class:`ResolvedSite`;site_id 为空时 None。

    Raises:
        SiteDenied: 显式 site_id 下任一授权条件不满足(fail-safe)。
    """
    if not site_id:
        return None
    origin = normalize_origin(request_origin)
    if origin is None:
        raise SiteDenied("request origin missing or unparsable")
    async with session_factory() as session:
        row = await session.get(SiteExperience, site_id)
    if row is None or not row.enabled:
        raise SiteDenied("unknown or disabled site")
    allowed = {normalize_origin(o) for o in (row.allowed_origins or [])}
    allowed.discard(None)
    if origin not in allowed:
        raise SiteDenied("origin not allowed for site")
    return ResolvedSite(
        site_id=row.site_id,
        display_name=row.display_name,
        welcome=row.welcome,
        language=row.language,
        welcome_i18n=dict(row.welcome_i18n) if row.welcome_i18n else None,
        starters_i18n=dict(row.starters_i18n) if row.starters_i18n else None,
        starters=tuple(row.starters or []),
    )


def load_sites_config(path: Path | None = None) -> list[dict]:
    """读取站点配置 YAML(缺失 = 配置错误,大声失败)。"""
    config_path = path or DEFAULT_SITES_CONFIG
    with config_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    sites = data.get("sites") or []
    if not isinstance(sites, list):
        raise TypeError(f"站点配置格式错误:sites 必须为列表({config_path})")
    return sites


async def seed_default_sites(
    session_factory: async_sessionmaker[AsyncSession],
    config_path: Path | None = None,
) -> int:
    """把 YAML 站点配置幂等 upsert 进 site_experiences 表。

    YAML 为权威:已存在的 site_id 按 YAML 更新配置字段(ops 改 YAML + 重启生效);
    返回 seeded 站点数(当前 V1 = 3)。
    """
    sites = load_sites_config(config_path)
    async with session_factory() as session:
        for item in sites:
            site_id = str(item["site_id"])
            row = await session.get(SiteExperience, site_id)
            if row is None:
                row = SiteExperience(site_id=site_id)
                session.add(row)
            row.display_name = str(item.get("display_name") or site_id)
            row.allowed_origins = [str(o) for o in (item.get("allowed_origins") or [])]
            row.starters = [str(s) for s in (item.get("starters") or [])]
            row.welcome = item.get("welcome") or None
            row.language = item.get("language") or None
            row.welcome_i18n = dict(item["welcome_i18n"]) if item.get("welcome_i18n") else None
            row.starters_i18n = dict(item["starters_i18n"]) if item.get("starters_i18n") else None
            row.enabled = bool(item.get("enabled", True))
        await session.commit()
    logger.info("站点体验配置已同步(%d 个站点)", len(sites))
    return len(sites)


async def list_enabled_sites(
    session_factory: async_sessionmaker[AsyncSession],
) -> list[SiteExperience]:
    """列出启用站点(诊断/未来 Admin 复用;当前不对外暴露)。"""
    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    select(SiteExperience)
                    .where(SiteExperience.enabled.is_(True))
                    .order_by(SiteExperience.site_id)
                )
            )
            .scalars()
            .all()
        )
        return list(rows)
